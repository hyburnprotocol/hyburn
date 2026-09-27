# Hyburn miner (Go)

```bash
go build -o hyburn .
export HYBURN_MINER=0x... HYBURN_DEPLOY_BLOCK=123456
export HYBURN_KEYSTORE=~/.hyburn/miner.json   # or HYBURN_PRIVATE_KEY
./hyburn status
./hyburn mine --amount 0.5 --max-cost 0.002 --at 30 --budget 50
```

Single static binary. Dependency: go-ethereum. Same commands and output as the Python reference; see `../README.md`.
