# Hyburn miner (Node.js)

Requires Node.js 22 and npm. Start from a clone of this repository; the commands below begin
at its root. Mining an existing contract does not require Foundry or a website build.

```sh
cd cli/node
npm ci
export HYBURN_RPC='https://rpc.hypurrscan.io'
export HYBURN_CHAIN_ID=999
export HYBURN_MINER='0x951258b9c1C625536c25A6ECe943aA75B0386250'
export HYBURN_DEPLOY_BLOCK=47024793
node hyburn.mjs status
```

`status` needs no wallet. Follow the [wallet guide](../WALLET.md) to prepare a
local encrypted Ethereum keystore, then return to this language's directory:

```sh
export HYBURN_KEYSTORE="$HOME/.hyburn/miner.keystore.json"
node hyburn.mjs burn 0.000999 --dry-run
```

The dry run unlocks the keystore and estimates, but does not send. Fund the verified
mining address with native HYPE on HyperEVM for burns **and gas** before estimation.
To send at most two minimum burns (0.001998 HYPE plus gas):

```sh
node hyburn.mjs mine --amount 0.000999 --budget 0.001998 --rounds 2
```

The first send waits until 30 seconds before round end by default. Keep the
computer awake. Ctrl-C stops new work; an already broadcast transaction may confirm.
`--budget` excludes gas and resets on restart. Restarting can burn in the same round.
After your final round closes, leave HYPE for gas and run:

```sh
node hyburn.mjs claim
node hyburn.mjs history
```

Exports last for this terminal only. Repeat them in a new terminal; no need to
reimport your key. `--rpc` overrides the default. The RPC chain ID must match the
configured ID. See the [shared reference](../README.md) for `--max-cost`, `--at`,
and other options. This implementation has a countdown UI; the panel-based
interactive dashboard is currently provided by the Python implementation.
