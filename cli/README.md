# Hyburn miners

Four implementations, one interface. Every implementation passes the same scripted scenario before release.

| Language | Path | Run |
|---|---|---|
| Python (reference) | `python/hyburn.py` | `python/.venv/bin/python python/hyburn.py …` |
| Node.js | `node/hyburn.mjs` | `node node/hyburn.mjs …` |
| Go | `go/` | `cd go && go build -o hyburn . && ./hyburn …` |
| Rust | `rust/` | `cd rust && cargo build --release && ./target/release/hyburn …` |

## Interface (identical in all four)

```text
hyburn [--rpc URL] [--miner ADDR] [--chain-id N] [--deploy-block N] <command>
  status  [--account ADDR]
  burn    <hype> [--dry-run]
  mine    --amount HYPE [--max-cost HYPE] [--at SECONDS] [--budget HYPE] [--rounds N] [--dry-run]
  claim   [--dry-run]
  history [--account ADDR]
```

`--max-cost` is a condition at send time, not a guarantee of the final cost: burns by others after yours in the same round lower everyone's payout.

Environment: `HYBURN_RPC`, `HYBURN_MINER`, `HYBURN_CHAIN_ID`, `HYBURN_DEPLOY_BLOCK`, `HYBURN_HOME` (cache, default `~/.hyburn`).
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
python3 cli/conformance/cache_boundary.py "node cli/node/hyburn.mjs"
cli/conformance/run.sh "node cli/node/hyburn.mjs"
```

The first command checks chain-time cache boundaries and cache migration against
mock RPC responses. The second runs burn, claim and continuous-mining scenarios
on an isolated local Anvil chain. Test keys are public Anvil fixtures, never real
wallet credentials. Each run owns its temporary port, cache and child processes.
