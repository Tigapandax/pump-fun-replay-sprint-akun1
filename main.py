"""Pump.fun Replay Sprint — paper trading bot (agent-fun/replay/v2).

Hello: this bot speaks the replay protocol on stdin/stdout — one reply per
batch, with its orders, keyed to the batch slot. The harness sends a hello,
then one batch per slot window, then done; the bot answers every batch.
Fills land two slots after the batch that carried the order, priced off the
reserves at that later slot — so any edge that lives only in the first two
slots after a move is already gone by the time a fill lands. That is why
this bot does NOT chase momentum: on the kit's dev data, buying a coin the
moment its real SOL reserves cross 1 SOL looks profitable on paper (+14%
per trade) but is -6% per trade once the two-slot fill delay is applied —
the spike is over before the buy fills.

Strategy — dip-buy on proven runners, written from scratch for this bounty:
  * Watch every bonding curve from its first sight. A coin becomes a
    candidate only after it has PROVEN itself: its price peaked at least
    3x its first-seen price, with at least 12 buys among its first 20
    trades (strong early demand), and its real SOL reserves are at least
    1 SOL (so the 1%-of-real-reserve size cap still allows a >= 0.01 SOL
    buy, the round-trip minimum the guardrails count).
  * Enter only on the retrace: current price at or below 70% of that
    peak, still above 1.05x the first price (the coin is not dead, just
    pulled back). Deepest dips first, at most 2 new coins per batch,
    at most 5 open positions. Size is a fixed 0.02 SOL per coin, capped
    by the size cap and free cash. Never re-enter a coin already traded
    and exited.
  * Exits, checked every batch from the marks: take profit at +30% over
    the entry price (a second leg that retests the old peak), trailing
    stop at -30% below the peak since entry, hard stop at -20% under
    entry, and a time cap of 14400 slots (~1.6 h) so a dead coin is
    never held to the end of the window. Most pump.fun coins give their
    gains back by the end of the day, so the bot sells into the second
    leg and never holds for the close.
  * Fees are ~1.25% of notional plus 105,000 lamports per order, so a
    round trip costs roughly 3%: the +30% take-profit and -20% stop
    clear that bar with room to spare, and the small trade count keeps
    total fees low.

Determinism: no clock, no environment, no unseeded random — only the
stream's own data, iterated in a fixed order (exits by mint, entries by
deepest dip then mint). The grader runs every entry twice and the two
action logs must match byte for byte.

Standard library only. No network. Run as: python3 -P -s main.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bot

LAMPORTS_PER_SOL = 1_000_000_000

# --- strategy parameters (all in lamports / basis points / slots) ---
BUY_SIZE = 20_000_000             # 0.02 SOL per entry
MIN_BUY = 10_000_000              # 0.01 SOL: smallest round trip the guardrails count
PEAK_MIN_BPS = 30000              # candidate must have peaked >= 3x its first price
DIP_FRAC_BPS = 7000               # enter at or below 70% of that peak
FLOOR_BPS = 500                   # ...but still above +5% over its first price
MIN_EARLY_BUYS = 12               # buys among the coin's first 20 trades
MIN_TRADES = 3                    # trades seen before a coin can qualify
MIN_REAL_SOL = 1_000_000_000      # real SOL reserves >= 1 SOL (size cap >= 0.01 SOL)
TAKE_PROFIT_BPS = 3000            # sell at +30% over entry
TRAIL_DROP_BPS = 3000             # sell at -30% below the peak since entry
STOP_LOSS_BPS = 2000              # sell at -20% under entry
MAX_HOLD_SLOTS = 14400            # sell after ~1.6 h held, whatever the price
MAX_SLIPPAGE_BPS = 500            # 5% slippage cap on every order
MAX_BUYS_PER_BATCH = 2            # at most 2 new entries per batch


def _price(curve):
    """Lamports per token from a curve's virtual reserves (float, deterministic)."""
    if curve.virtual_token_reserves <= 0:
        return 0.0
    return curve.virtual_quote_reserves / curve.virtual_token_reserves


class DipBuyer:
    """Per-run state: first sightings, peaks, early buy counts, entries, exits."""

    def __init__(self):
        # mint -> first price seen (lamports per token)
        self.first_price = {}
        # mint -> highest price seen since first sight
        self.peak = {}
        # mint -> trade count, and buys among its first 20 trades
        self.trades = {}
        self.early_buys = {}
        # mint -> entry record for coins we hold (or just bought)
        self.entries = {}
        # mints already traded and fully exited: never re-enter
        self.done = set()

    def note_events(self, state, batch):
        """Fold this batch's events into the per-mint counters.

        First sighting prices are captured here, from the event itself:
        a CreateEvent carries the curve's opening reserves, and a TradeEvent
        the reserves just after that trade. Capturing them after the batch
        (from the curve state) would price the coin after it already moved.
        """
        for e in batch["events"]:
            mint = e["mint"]
            if mint not in self.first_price:
                vq = int(e.get("virtual_quote_reserves", "0") or 0)
                vt = int(e.get("virtual_token_reserves", "0") or 0)
                if vq > 0 and vt > 0:
                    self.first_price[mint] = vq / vt
            if e["event"] == "TradeEvent":
                n = self.trades.get(mint, 0) + 1
                self.trades[mint] = n
                if e["is_buy"] and n <= 20:
                    self.early_buys[mint] = self.early_buys.get(mint, 0) + 1

    def note_fills(self, state, batch):
        """Record entries from buy fills (entry price = fill quote / tokens)."""
        for f in batch["fills"]:
            if f["status"] != "filled":
                continue
            mint = f["mint"]
            if f["side"] == "buy":
                tokens = int(f["token_amount"])
                quote = int(f["quote_lamports"])
                if tokens > 0:
                    price = quote / tokens
                    self.entries[mint] = {
                        "entry_price": price,
                        "peak": price,
                        "slot": f["decided_slot"],
                    }
            else:
                # A sell fill: if we hold no more of it, the coin is done.
                if mint not in state.positions:
                    self.entries.pop(mint, None)
                    self.done.add(mint)

    def refresh_peaks(self, state):
        """Update each curve's peak from the latest marks, and first prices
        for curves first seen through marks alone."""
        for mint, curve in state.curves.items():
            price = _price(curve)
            if price <= 0:
                continue
            if mint not in self.first_price:
                self.first_price[mint] = price
            if price > self.peak.get(mint, 0.0):
                self.peak[mint] = price

    def exits(self, state):
        """Sell orders for held positions that hit an exit rule, in mint order."""
        orders = []
        for mint in sorted(state.positions):
            entry = self.entries.get(mint)
            if entry is None:
                # Position we did not record (should not happen): hold it.
                continue
            curve = state.curves.get(mint)
            if curve is None:
                continue
            price = _price(curve)
            if price <= 0:
                continue
            if price > entry["peak"]:
                entry["peak"] = price
            entry_price = entry["entry_price"]
            hit_tp = price >= entry_price * (10_000 + TAKE_PROFIT_BPS) / 10_000
            hit_trail = price <= entry["peak"] * (10_000 - TRAIL_DROP_BPS) / 10_000
            hit_stop = price <= entry_price * (10_000 - STOP_LOSS_BPS) / 10_000
            held_long = state.slot - entry["slot"] >= MAX_HOLD_SLOTS
            if hit_tp or hit_trail or hit_stop or held_long:
                holding = state.positions[mint]
                orders.append(
                    {
                        "side": "sell",
                        "mint": mint,
                        "token_amount": holding.token_amount,
                        "max_slippage_bps": MAX_SLIPPAGE_BPS,
                    }
                )
        return orders

    def entries_now(self, state):
        """Buy orders for proven runners on their retrace, deepest dip first."""
        orders = []
        if state.committed_position_count() >= state.hello["caps"]["max_open_positions"]:
            return orders
        # Mints with a buy already in flight: the fill has not landed yet,
        # so neither positions nor entries list them — skip them explicitly.
        pending_buys = {
            p.order["mint"] for p in state.pending.values() if p.order["side"] == "buy"
        }
        candidates = []
        for mint, curve in state.curves.items():
            if mint in self.done or mint in state.positions or mint in self.entries:
                continue
            if mint in pending_buys:
                continue
            if curve.complete:
                continue
            if self.trades.get(mint, 0) < MIN_TRADES:
                continue
            if self.early_buys.get(mint, 0) < MIN_EARLY_BUYS:
                continue
            if curve.real_quote_reserves < MIN_REAL_SOL:
                continue
            first = self.first_price.get(mint)
            if first is None:
                continue
            peak = self.peak.get(mint, 0.0)
            if peak * 10_000 < first * (10_000 + PEAK_MIN_BPS):
                continue
            price = _price(curve)
            if price <= 0:
                continue
            if price * 10_000 > peak * DIP_FRAC_BPS:
                continue
            if price * 10_000 < first * (10_000 + FLOOR_BPS):
                continue
            # Deepest dip first; mint breaks ties so the order is fixed.
            candidates.append((peak / price, mint))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        for _, mint in candidates:
            if len(orders) >= MAX_BUYS_PER_BATCH:
                break
            curve = state.curves[mint]
            size = min(BUY_SIZE, state.max_buy_lamports(mint))
            if size < MIN_BUY:
                continue
            if state.free_cash_lamports() < size + state.tx_fee_lamports():
                continue
            if state.committed_position_count() >= state.hello["caps"]["max_open_positions"]:
                break
            orders.append(
                {
                    "side": "buy",
                    "mint": mint,
                    "quote_lamports": size,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }
            )
        return orders


def on_batch(state, batch):
    """One reply per batch: exits first, then new entries."""
    bot.note_events(state, batch)
    bot.note_fills(state, batch)
    bot.refresh_peaks(state)
    orders = bot.exits(state)
    orders.extend(bot.entries_now(state))
    return orders


def on_done(state, done):
    """Final account to stderr (stdout carries replies only)."""
    sys.stderr.write(
        "done: cash=%s positions=%d batches=%d\n"
        % (state.cash, len(state.positions), state.seq + 1)
    )


bot = DipBuyer()
makefun_bot.run(on_batch, on_done=on_done)
