# Hyburn miner (Go)

For automatic dependency preparation/builds and the shared terminal dashboard,
run `./cli/hyburn --engine go mine` from the repository root after
[one-time wallet setup](../TUI.md). Python 3.10+ is required for the shared UI;
the selected engine still performs all signing. Native commands below also open
the TUI automatically. Press S to start or Q to exit; use `--plain` for native
line output and `--yes` for unattended execution. Tab 7 indexes all-time rankings
automatically with no cache configuration. [Controls and data coverage](../TUI.md).

Requires Go 1.24+. Start from a clone of this repository; the commands below begin
at its root. Mining an existing contract does not require Foundry or a website build.

```sh
cd cli/go
go build -o hyburn .
export HYBURN_RPC='https://rpc.hypurrscan.io'
export HYBURN_CHAIN_ID=999
export HYBURN_MINER='0x951258b9c1C625536c25A6ECe943aA75B0386250'
export HYBURN_DEPLOY_BLOCK=47024793
./hyburn status
```

`status` needs no wallet. Follow the [wallet guide](../WALLET.md) to prepare a
local encrypted Ethereum keystore, then return to this language's directory:

```sh
export HYBURN_KEYSTORE="$HOME/.hyburn/miner.keystore.json"
./hyburn burn 0.000999 --dry-run
```

The dry run unlocks the keystore and estimates, but does not send. Fund the verified
mining address with native HYPE on HyperEVM for burns **and gas** before estimation.
To send at most two minimum burns (0.001998 HYPE plus gas):

```sh
./hyburn mine --amount 0.000999 --budget 0.001998 --rounds 2
```

The first send waits until 30 seconds before round end by default. Keep the
computer awake. Ctrl-C stops new work; an already broadcast transaction may confirm.
`--budget` excludes gas and persists across restarts. Run `mine` without options
to resume. Use `--new-session` with full settings for a new budget. Final rewards
are claimed automatically after the last round closes.
See [one-time setup and saved sessions](../SESSION.md).
The miner automatically claims after its final round. If you stopped it early,
resume `mine` or claim manually:

```sh
./hyburn claim
./hyburn history
```

The [one-time setup](../SESSION.md) saves these connection values for every
implementation. With setup complete, use `mine` without options in new terminals;
no repeated exports or key import are needed. Manual environment overrides remain
limited to the shell where they were set. `--rpc` overrides the default. The RPC chain ID must match the
configured ID. See the [shared reference](../README.md) for `--max-cost`, `--at`,
and other options. This implementation has a countdown UI; the panel-based
interactive dashboard is currently provided by the Python implementation.
