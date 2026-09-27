# Hyburn miner (Node.js)

```bash
npm install
export HYBURN_MINER=0x... HYBURN_DEPLOY_BLOCK=123456
export HYBURN_KEYSTORE=~/.hyburn/miner.json   # or HYBURN_PRIVATE_KEY
node hyburn.mjs status
node hyburn.mjs mine --amount 0.5 --max-cost 0.002 --at 30 --budget 50
```

One file, one dependency (ethers 6). Same commands and output as the Python reference; see `../README.md`.
