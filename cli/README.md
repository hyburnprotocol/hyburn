# Hyburn miners

Four implementations, one interface. Every implementation passes the same scripted scenario before release.

| Language | Path | Run |
|---|---|---|
| Python (reference) | `python/hyburn.py` | `python/.venv/bin/python python/hyburn.py …` |
| Node.js | `node/hyburn.mjs` | `node node/hyburn.mjs …` |
| Go | `go/` | `cd go && go build -o hyburn . && ./hyburn …` |
| Rust | `rust/` | `cd rust && cargo build --release && ./target/release/hyburn …` |

Start with the [mainnet quickstart](../README.md#mine-on-hyperevm) and
[wallet guide](WALLET.md). No browser-wallet connection or contract deployment
is needed for ordinary mining.

## Interface (shared commands)

```text
hyburn [--rpc URL] [--miner ADDR] [--chain-id N] [--deploy-block N] <command>
  status  [--account ADDR]
  burn    <hype> [--dry-run]
  mine    [--amount HYPE] [--max-cost HYPE] [--at SECONDS] [--budget HYPE] [--rounds N] [--reserve HYPE] [--new-session] [--dry-run]
  claim   [--dry-run]
  history [--account ADDR]
```

`--budget` counts burns across restarts; gas is recorded separately. Settings,
pending transactions and confirmed usage are saved automatically. First live use
needs `--amount` plus `--budget` or `--rounds`; afterwards `mine` resumes them.
The default gas reserve is 0.001 HYPE. At completion the miner waits and claims
the final reward. See [setup and saved sessions](SESSION.md).

`--max-cost` is a condition at send time, not a guarantee of the final cost: burns by others after yours in the same round lower everyone's payout.

Default RPC in all four implementations: `https://rpc.hypurrscan.io` (third-party provider).
Override with `--rpc` or `HYBURN_RPC`; existing explicit settings are unchanged.

All four implementations open the same terminal dashboard for interactive `mine`.
The shared UI requires Python 3.10+; its packages are prepared automatically.
Use `--plain` for native line output or `--yes` for unattended starts.
The [common launcher and TUI guide](TUI.md) covers automatic builds and controls.

Environment: `HYBURN_RPC`, `HYBURN_MINER`, `HYBURN_CHAIN_ID`, `HYBURN_DEPLOY_BLOCK`, `HYBURN_HOME` (profile, sessions and cache; default `~/.hyburn`).
Key: `HYBURN_KEYSTORE` (encrypted JSON; password prompted or `HYBURN_KEYSTORE_PASSWORD`) or `HYBURN_PRIVATE_KEY`. Never as an argument.

Use a dedicated wallet holding only the HYPE you intend to burn plus gas. Burned HYPE does not come back.

## Waiting and terminal output

All four `mine` implementations display an estimated countdown in interactive
terminals. They wait locally and re-check chain time at most every 30 seconds
during long waits, and again at the send window. The display itself makes no RPC
requests. Ctrl-C interrupts the wait; redirected output uses plain log lines.
An estimated countdown is not a guarantee of transaction inclusion.

The Python deployment console is for deploying **your own protocol instance**.
To mine an existing deployment, use the standard `hyburn` commands above with its
Miner address and deployment block. No website build or Foundry installation is
needed for ordinary mining. The deployment console has a separate RPC throttle
(1.25 seconds between requests); do not assume that throttle applies to the other
miners or to other applications sharing your IP.

## Shared regression tests

From the repository root, build the contracts and install/build the selected miner:

```sh
forge build
python3 cli/conformance/cache_boundary.py "node cli/node/hyburn.mjs --yes"
cli/conformance/run.sh "node cli/node/hyburn.mjs --yes"
```

The first command checks chain-time cache boundaries and cache migration against
mock RPC responses. The second runs burn, claim and continuous-mining scenarios
on an isolated local Anvil chain. Test keys are public Anvil fixtures, never real
wallet credentials. Each run owns its temporary port, cache and child processes.

### Start screen and statistics

Every miner waits for **S: start / Q: exit** (`[y/N]` in plain mode). Unattended
execution requires `--yes`. Tabs 4/5/7 show current-round rankings, your recent
history and all-time participation. Tab 6 distinguishes Token CA from Miner.
Caches are created and resumed automatically for each chain/contract. Partial
coverage is explicitly labeled. See [the shared TUI guide](TUI.md).
