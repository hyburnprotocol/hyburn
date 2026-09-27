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
## Local deployment console

`deploy_console.py` deploys and runs minimum-size burns from a dedicated local
wallet. It is separate from the standard `hyburn.py` miner and is never a web
endpoint. From the repository root, create the ignored file
`script/developer/deployment.local.json` with your settings:

```json
{
  "wallet": "YOUR_EXPECTED_WALLET_ADDRESS",
  "private_key": "",
  "rpc": "https://rpc.hyperliquid.xyz/evm",
  "chain_id": 999,
  "reserve_hype": "0.001",
  "state_file": "output/developer-deploy/session.json"
}
```

Fill the private key locally, or use `--keystore /absolute/path/to/keystore.json`
for an encrypted keystore. Raw keys in the JSON are plaintext; never commit or
share this file. The console checks the derived address, Git exclusion and file
permissions. A read-only preview requires no signing key:

```sh
cli/python/.venv/bin/python cli/python/deploy_console.py
# Explicitly signs and sends, without an additional confirmation prompt:
cli/python/.venv/bin/python cli/python/deploy_console.py --execute
```

The console separates burned HYPE, gas paid (deployment plus mining), total
spending, the fixed session cap, remaining cap and protected reserve. Available
spending is the smaller of remaining cap and wallet balance minus reserve; it
must cover both burns and gas. The last confirmed transaction shows its actual
burn and gas separately. Display amounts are rounded to nine decimals; all
budget checks use integer wei. Pending transactions are excluded from totals.

The initial balance caps deployment, burns and gas for the whole saved session;
later deposits do not raise the cap. Every burn is 0.000999 HYPE. The reserve stays
untouched. The console verifies deployed code before mining. Only the initial
deployment updates local website facts and builds the website. Resuming with the
same state skips both operations. To explicitly refresh the local website on a
resume, add `--refresh-website --execute`; this never publishes to Vercel.

Interactive terminals show an animated RPC indicator and a local countdown for
rounds and retry backoff. The animation performs no network requests. Redirected
logs contain plain phase messages without terminal escape sequences. Ctrl-C
clears the indicator and preserves the existing transaction journal.

After a burn, it sleeps locally until the next round instead of polling every two
seconds. It checks chain time again before sending. RPC calls are spaced at least
1.25 seconds apart. Temporary read failures back off up to 60 seconds and keep
retrying until recovery or Ctrl-C. Transaction submissions are never automatically
replayed. Unresolved submissions and reverted transactions stop safely; inspect
the saved hash before recovery. Resume using the same configuration and state
file, never delete the journal or run another instance with a different journal.

The official endpoint's documented limit is 100 EVM JSON-RPC requests/minute per
IP ([Hyperliquid documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits)).
Other processes on the same IP share that limit. `invalid block height` alone
does not establish that rate limiting caused an error. Keep the computer awake;
missed rounds during downtime are not backfilled.
