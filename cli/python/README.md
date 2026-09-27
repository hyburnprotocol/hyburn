# Hyburn miner (Python, reference implementation)

One file, one dependency (web3.py). Read `hyburn.py` before trusting it with a key.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export HYBURN_MINER=0x...            # HyburnMiner address
export HYBURN_DEPLOY_BLOCK=123456    # deployment block; history scans start here
```

Key: either an encrypted keystore (password prompted) or, for unattended use on a machine you control, a raw key in the environment. Never pass a key as an argument.

```bash
export HYBURN_KEYSTORE=~/.hyburn/miner.json
# or
export HYBURN_PRIVATE_KEY=0x...
```

Use a dedicated wallet that holds only the HYPE you intend to burn plus gas.

## Commands

```bash
.venv/bin/python hyburn.py status
.venv/bin/python hyburn.py burn 0.5
.venv/bin/python hyburn.py mine --amount 0.5 --max-cost 0.002 --at 30 --budget 50
.venv/bin/python hyburn.py claim
.venv/bin/python hyburn.py history
```

`mine` decides once per round, `--at` seconds before the round ends: if the HYPE cost per HYBURN at that moment, counting your own burn, is above `--max-cost` it skips the round; if `--budget` would be exceeded it stops. `--max-cost` is a condition at send time, not a guarantee: burns by others after yours in the same round lower everyone's payout, so the final cost can end up higher. Every burn names its round; if the transaction lands late the contract rejects it and nothing is burned. Unclaimed finished rounds are claimed in the same transaction as each burn. `--dry-run` prints what would be sent. Ctrl-C stops cleanly.

Other settings: `HYBURN_RPC` (default `https://rpc.hyperliquid.xyz/evm`), `HYBURN_CHAIN_ID`, `HYBURN_HOME` (cache directory, default `~/.hyburn`).
