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
