# Hyburn

**Burn HYPE. Mine HYBURN.**

Hyburn is a burn-to-mint protocol for HyperEVM. Every 999 seconds, participants share a round's scheduled HYBURN reward in proportion to the HYPE they burn. There is no premine, team allocation, administrator, upgrade path or pause function.

## How it works

1. **Wait for genesis.** Mining opens 999 seconds (16 minutes, 39 seconds) after the deployment block timestamp. Burns before genesis revert.
2. **Burn HYPE.** Call `burn(expectedRoundId)` with at least 0.000999 HYPE. The HYPE goes to a receive-only vault with no withdrawal function.
3. **Claim HYBURN.** Once the round ends, claim your share. Anyone may submit a claim for you, but the tokens always go to the burner. Claims have no deadline.

```text
your reward = floor(round reward × your HYPE burned / total HYPE burned in the round)
```

For an initial-reward round, burning 1 HYPE out of a final total of 4 HYPE earns 25% of 5,781.25 HYBURN: **1,445.3125 HYBURN**. The final total is only known when the round ends; later burns can reduce your share.

| Parameter | Value |
| --- | --- |
| Token | Hyburn / HYBURN, 9 decimals |
| Start delay | 999 seconds after deployment |
| Round duration | 999 seconds |
| Minimum per burn | 0.000999 HYPE |
| Initial round reward | 5,781.25 HYBURN |
| Halving interval | 86,400 non-empty rounds |
| Supply cap | 999,000,000 HYBURN |

Empty rounds issue nothing and do not advance the reward schedule. Integer rounding dust is never minted, and unclaimed rewards remain unminted, so actual minted supply can be below the cap. Burning locks HYPE economically; it does not reduce HyperCore's protocol-level supply. Burned HYPE cannot be recovered, and the contract provides no price or liquidity guarantee.

The [whitepaper source](web/src/app/whitepaper/page.tsx) describes the complete schedule, terminal remainder and trust assumptions.

## Repository

| Path | Contents |
| --- | --- |
| [`src/`](src/) | Miner, HYBURN token and receive-only HYPE vault |
| [`cli/`](cli/) | Python, Node.js, Go and Rust miners |
| [`web/`](web/) | Static website: Home, Mine and Whitepaper |
| [`test/`](test/) | Contract unit, fuzz, invariant and economic stress tests |
| [`cli/conformance/`](cli/conformance/) | Shared miner and cache regression scenarios |
| `lib/forge-std` | Pinned upstream testing dependency (submodule) |
| [`verify_bytecode.py`](verify_bytecode.py) | Miner runtime-code comparison |
| [`brand/`](brand/) | Project avatar and banner assets |

## Build the contracts

Install Foundry, clone this repository and run from its root:

```sh
git clone --recurse-submodules https://github.com/hyburnprotocol/hyburn.git
cd hyburn
forge build
```

Compiler settings are pinned in [`foundry.toml`](foundry.toml): Solidity 0.8.30, Cancun EVM, optimizer enabled with 1,000,000 runs, and no metadata hash. The production contracts have no external Solidity dependencies. Tests use forge-std, pinned as a Git submodule. If you cloned without submodules, run `git submodule update --init --recursive`.

## Run a miner

Choose one implementation; all expose `status`, `burn`, `mine`, `claim` and `history`:

| Implementation | Setup and usage |
| --- | --- |
| Python (reference) | [Python guide](cli/python/README.md) |
| Node.js | [Node.js guide](cli/node/README.md) |
| Go | [Go guide](cli/go/README.md) |
| Rust | [Rust guide](cli/rust/README.md) |

For example, from the repository root, using Bash or Zsh with Python 3.10+:

```sh
cd cli/python
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# Replace these placeholders with the published deployment facts.
export HYBURN_MINER='<MINER_ADDRESS>'
export HYBURN_DEPLOY_BLOCK='<DEPLOYMENT_BLOCK>'
.venv/bin/python hyburn.py status

# An existing encrypted Ethereum JSON keystore; its password is prompted.
export HYBURN_KEYSTORE="$HOME/.hyburn/miner.json"

# After genesis: estimate without sending. Requires a funded mining wallet.
.venv/bin/python hyburn.py burn 0.000999 --dry-run

# Sends up to two burns, with gas paid separately.
.venv/bin/python hyburn.py mine --amount 0.000999 --budget 0.001998 --rounds 2

# After the final round ends:
.venv/bin/python hyburn.py claim
.venv/bin/python hyburn.py history
```

Use a dedicated mining wallet. The CLI does not create a keystore. `--budget` counts only burns in the current process, excludes gas, and resets on restart. `--max-cost` checks the estimated cost at send time; it cannot guarantee the final round's cost. See the [shared CLI reference](cli/README.md) for all options and environment variables.

## Verify a deployment

Use the source commit published with the deployment. From the repository root:

```sh
forge build
python3 verify_bytecode.py <MINER_ADDRESS>
# Optional custom RPC:
python3 verify_bytecode.py <MINER_ADDRESS> <RPC_URL>
```

`MATCH` means the Miner runtime matches the local build **outside immutable slots**. The script checks consistency across repeated immutable slots and prints their values. Compare the token address, vault address and genesis timestamp with the published deployment record.

This script does not verify the Token or Vault runtime, prove their wiring, or perform a security audit. Check those contracts separately, including the token's `MINTER` address. Compiler settings must match the deployment.

The Python `mine` command automatically opens a terminal dashboard on supported
interactive terminals; use `--plain` before `mine` for line-by-line logs. All four
miners default to `https://rpc.hypurrscan.io`. Set `HYBURN_RPC` or `--rpc` to use
another provider. See [terminal behavior](cli/README.md#waiting-and-terminal-output).

## Build the website

Requires Node.js 22 and npm:

```sh
cd web
npm ci
npm run lint
npm run build
```

The static export is written to `web/out/`. Routes are `/`, `/mine/` and `/whitepaper/`. The website has no wallet connection and does not query live chain state. Without deployment configuration, addresses and genesis are displayed as unpublished.

Set these public environment variables **before building**, then rebuild after changing them:

| Variable | Value |
| --- | --- |
| `NEXT_PUBLIC_MINER`, `NEXT_PUBLIC_TOKEN`, `NEXT_PUBLIC_VAULT` | Deployed contract addresses |
| `NEXT_PUBLIC_DEPLOY_BLOCK`, `NEXT_PUBLIC_DEPLOY_TX` | Deployment block number and transaction hash |
| `NEXT_PUBLIC_GENESIS` | Genesis Unix timestamp, in seconds |
| `NEXT_PUBLIC_COMMIT` | Deployed source commit hash |
| `NEXT_PUBLIC_REPO` | Public source repository URL |
| `NEXT_PUBLIC_CHAIN_ID`, `NEXT_PUBLIC_CHAIN_NAME` | Defaults: `999`, `HyperEVM` |
| `NEXT_PUBLIC_RPC`, `NEXT_PUBLIC_EXPLORER` | Optional RPC and explorer overrides |

Never put private keys or keystore passwords in `NEXT_PUBLIC_*` variables. Full defaults are in [`config.ts`](web/src/lib/config.ts).

## Run the tests

From the repository root, after initializing submodules:

```sh
forge fmt --check src test
forge test
forge test --match-contract InvariantTest
forge test --match-contract StressSimulationTest -vv
```

For each miner, install its dependencies or build its binary first. The following
example uses Python; replace the quoted command to test another implementation:

```sh
forge build
python3 cli/conformance/cache_boundary.py "cli/python/.venv/bin/python cli/python/hyburn.py"
cli/conformance/run.sh "cli/python/.venv/bin/python cli/python/hyburn.py"
```

The boundary regression uses a local mock RPC. The conformance scenario launches
its own Anvil chain on a temporary local port with public Anvil test keys. It tests
pre-genesis rejection, proportional rewards, claims, auto-claims, mining limits,
and cache behavior. It does not use your wallet or an external chain and stops
only its own processes. Bash, Python 3 and Foundry are required.

CI runs the contract tests and invariants, website lint/build, and both shared
miner scenarios for Python, Node.js, Go and Rust. Tests demonstrate the checked
properties; they are not an independent security audit.

## License

Hyburn's original source code is available under the [MIT License](LICENSE). Third-party dependencies remain subject to their respective licenses.
