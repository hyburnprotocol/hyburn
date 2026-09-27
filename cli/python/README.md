# Hyburn miner (Python, reference implementation)

The reference miner uses web3.py and the bundled `terminal_ui.py` display module.
Read `hyburn.py` before trusting it with a key. Keep both Python files together.

## First run

Follow the [mainnet quickstart](../../README.md#mine-on-hyperevm), which includes
installation, verified deployment addresses, offline keystore import, a read-only
check, a dry run, bounded mining and the final claim. It does not require Foundry.
For wallet alternatives and common errors, see [wallet setup](../WALLET.md).

From `cli/python`, after the quickstart exports and wallet setup:

```sh
.venv/bin/python hyburn.py status
.venv/bin/python hyburn.py burn 0.000999 --dry-run
# Real transactions: two minimum burns; gas is additional.
.venv/bin/python hyburn.py mine --amount 0.000999 --budget 0.001998 --rounds 2
# After the final participated round closes:
.venv/bin/python hyburn.py claim
.venv/bin/python hyburn.py history
```

`mine` decides once per round, 30 seconds before its end by default (`--at`).
`--max-cost` is a send-time condition, not a guarantee: later burns can reduce
payout. `--budget` counts this process's burns only, excludes gas and resets on
restart. A restarted process can burn again in the same round. Keep the computer
awake and leave HYPE for claim gas. Full options: [CLI reference](../README.md).

Other settings: `HYBURN_RPC` (default `https://rpc.hypurrscan.io`),
`HYBURN_CHAIN_ID`, `HYBURN_HOME` (cache directory, default `~/.hyburn`).

## Local deployment console

`deploy_console.py` deploys and runs minimum-size burns from a dedicated local
wallet. It is separate from the standard `hyburn.py` miner and is never a web
endpoint. From the repository root, create the ignored file
`script/developer/deployment.local.json` with your settings:

```json
{
  "wallet": "YOUR_EXPECTED_WALLET_ADDRESS",
  "private_key": "",
  "rpc": "https://rpc.hypurrscan.io",
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
retrying until recovery or Ctrl-C. Rate-limit responses instead wait 30 seconds,
then 60 seconds for further limits, even if another read succeeded in between.
Requests slow to at least four seconds apart for five minutes after that cooldown.
The endpoint's limit is shared across the IP; staying below it in one console
does not guarantee availability.

Confirmed claims are persisted in the session journal and skipped on restart.
Old sessions need one migration scan; each confirmed result is saved immediately
so interrupting the scan does not discard its progress. Newly confirmed
`burnAndClaim` transactions record their claims from the successful receipt.

Transaction submissions are never automatically
replayed. Unresolved submissions and reverted transactions stop safely; inspect
the saved hash before recovery. Resume using the same configuration and state
file, never delete the journal or run another instance with a different journal.

The official endpoint's documented limit is 100 EVM JSON-RPC requests/minute per
IP ([Hyperliquid documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits)).
Other processes on the same IP share that limit. `invalid block height` alone
does not establish that rate limiting caused an error. Keep the computer awake;
missed rounds during downtime are not backfilled.

## Terminal dashboard

The header shows the next round's estimated start time, updated locally from the
last chain timestamp using a monotonic clock. It stays visible during RPC work;
at zero it waits for another chain read rather than treating local time as proof
that the round started. Rendering adds no RPC calls and does not change signing
or send timing. The activity panel separately shows the current operation.

The HyperEVM network mark is a terminal approximation of the supplied Hyperliquid
Blob SVG. UTF-8 terminals display the braille silhouette; other encodings fall
back to text. Cyan identifies navigation, green confirmed events, yellow retries,
and red errors. Set `NO_COLOR=1` for monochrome or use `--plain` for line logs.

`hyburn.py mine` and `deploy_console.py` automatically show a fixed dashboard in
interactive terminals at least 80 columns by 24 rows. It separates saved metrics,
current activity/countdown and recent events. Press `1` for Overview, `2` for
Wallet/Costs, `3` for Events, `?` for Help, or Tab to cycle. Use `j`/`k` to scroll
and `g` to reset; these keys never send transactions or change budgets. Screen refreshes perform no RPC
requests. Balances and round data are snapshots from the last read, not live feeds.

Use `hyburn.py --plain mine ...` or `deploy_console.py --plain --execute` for the
original line-by-line output. Redirected output and smaller terminals fall back
to plain logs. Ctrl-C restores the terminal; password prompts temporarily leave
the dashboard. The public miner's budget counts burns only; the deployment
console's saved cap includes deployment and transaction gas.

The default RPC is the third-party Hypurrscan endpoint. `--rpc` overrides it;
`HYBURN_RPC` also overrides it in the standard miner, while the deployment console
uses its local JSON configuration. Existing explicit settings are preserved.
Provider availability and limits may differ; the dashboard does not change them.
