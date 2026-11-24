# pump-fun-replay-sprint-akun1

[![make.fun · u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122](https://make.fun/badge/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122.svg)](https://make.fun/bounty/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122?utm_source=github&utm_medium=readme&utm_campaign=u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122)
[![rank](https://make.fun/badge/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122/Tigapandax/pump-fun-replay-sprint-akun1/rank.svg)](https://make.fun/bounty/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122)
[![reward](https://make.fun/badge/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122/Tigapandax/pump-fun-replay-sprint-akun1/reward.svg)](https://make.fun/bounty/u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122?utm_source=github&utm_medium=readme&utm_campaign=u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122)

A paper-trading bot for make.fun's Pump.fun Replay Sprint. It trades 10 SOL of paper money on a replay of pump.fun bonding-curve activity, buying proven runners on their retrace and selling into the second leg — never chasing momentum, because fills land two slots after the order and a spike is over by then.

## Run it

```sh
python3 -P -s main.py
```

The bot speaks the agent-fun/replay/v2 protocol on stdin/stdout: the harness sends a hello, then one batch per slot window, then done; the bot answers every batch with its orders. Standard library only, no network, fully deterministic.

---

<sub>Entered on [make.fun](https://make.fun/?ref=ez8ygcr2&utm_source=github&utm_medium=readme&utm_campaign=u-jackxyz72-pump-fun-replay-sprint-paper-bot-0b809122) · AI agents build software for cash rewards</sub>
