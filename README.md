# Hyburn

**Burn HYPE. Mine HYBURN.**

[Start mining](#mine-on-hyperevm) · [Website](https://hyburn.xyz) · [Wallet setup](cli/WALLET.md)

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

## Mine on HyperEVM

Mining the existing deployment does **not** require Foundry, a contract deployment,
or a website build. Start with Python below, or choose the [Node.js](cli/node/README.md),
[Go](cli/go/README.md) or [Rust](cli/rust/README.md) guide.

### 1. Install and inspect without a wallet

These commands are for macOS/Linux Bash or Zsh (Windows users can use WSL).
You need Git and Python 3.10+ with pip/venv support.

```sh
git clone https://github.com/hyburnprotocol/hyburn.git
cd hyburn/cli/python
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

export HYBURN_RPC='https://rpc.hypurrscan.io'
export HYBURN_CHAIN_ID=999
export HYBURN_MINER='0x951258b9c1C625536c25A6ECe943aA75B0386250'
export HYBURN_DEPLOY_BLOCK=47024793
.venv/bin/python hyburn.py status
```

| Live deployment | Value |
| --- | --- |
| Network | HyperEVM mainnet, chain ID 999 |
| Miner | [`0x951258b9c1C625536c25A6ECe943aA75B0386250`](https://hyperevmscan.io/address/0x951258b9c1C625536c25A6ECe943aA75B0386250) |
| HYBURN token | [`0xC02E218F52ea5D38759BB1AfA92C197eF30673B4`](https://hyperevmscan.io/address/0xC02E218F52ea5D38759BB1AfA92C197eF30673B4) |
| Deployment block | 47024793 |

Use the **Miner** address for `HYBURN_MINER`, not the token address. Cross-check
these addresses with [hyburn.xyz](https://hyburn.xyz). Explicit chain ID settings
are checked against the RPC before key loading or signing.

### 2. Set up a dedicated mining wallet

There is no browser-wallet connection popup. The CLI signs locally with an
Ethereum JSON keystore or an environment-supplied private key. An address alone
can be used for read-only checks but cannot sign. Hardware-wallet signing and
WalletConnect are not supported by these CLIs.

Use a dedicated software-wallet account, such as a separate account in Rabby.
To import that account's private key into an encrypted file, run this **offline** helper:

```sh
.venv/bin/python hyburn.py setup
```

Setup accepts an existing keystore or asks for a private key and a new password
with hidden input. It saves the connection profile for all four miners, so later
terminals do not need repeated exports.
Do not enter a seed phrase. It prints the derived public address, creates an
owner-only encrypted file, never overwrites a file and makes no network requests.
Check that the printed address matches your chosen wallet account. Back up the
file and password separately. This password is for the new keystore; it need not
be your browser wallet's password.

If you already have an encrypted Ethereum JSON keystore, enter its absolute path
during setup, or override `HYBURN_KEYSTORE` yourself. The same file works with all four miners.
See the [wallet guide](cli/WALLET.md) for alternatives and troubleshooting.

### 3. Fund, then preview

Send only the amount you intend to use to the mining address **on HyperEVM**:
native HYPE is needed for both burns and gas. HYPE held only on HyperCore, WHYPE,
or HYBURN cannot pay this CLI's native HYPE transaction costs.

```sh
# Replace this with the PUBLIC address printed by the helper; no key needed.
.venv/bin/python hyburn.py status --account YOUR_MINING_ADDRESS

# Unlocks the keystore and estimates a burn, but does not send a transaction.
.venv/bin/python hyburn.py burn 0.000999 --dry-run
```

A successful dry run is a simulation, not a reserved price or guaranteed inclusion.

### 4. Start bounded mining

The following command **spends real HYPE**. It sends at most two minimum burns
(0.001998 HYPE total), with gas paid separately:

```sh
.venv/bin/python hyburn.py mine --amount 0.000999 --budget 0.001998 --rounds 2
```

The first send normally waits until 30 seconds before the current round ends;
the countdown can initially be almost 999 seconds. A supported terminal opens a
dashboard. Use `hyburn.py --plain mine ...` for plain logs. Keep the computer awake.
Ctrl-C stops the process; a transaction already broadcast may still confirm.

`--budget` counts **burns across restarts**; gas is additional. Settings and
pending transactions are saved automatically. Later, run `.venv/bin/python hyburn.py mine`
to resume without resetting the budget. A new budget requires `--new-session` and
complete settings. A 0.001 HYPE reserve is protected for claim gas. See
[saved sessions](cli/SESSION.md) for recovery and spending details. `--max-cost` is a condition at send time, not a final
price guarantee. The [shared CLI reference](cli/README.md) explains all options.

### 5. Automatic final claim

Each successful burn also claims eligible earlier rounds. At the budget or round
limit, the miner waits for the final round to close and claims it automatically.
If interrupted, resume `mine`; you can also claim manually:

```sh
.venv/bin/python hyburn.py claim
.venv/bin/python hyburn.py history
```

Claiming also costs HYPE gas. Leave enough HYPE in the wallet for that transaction.
Rewards go to the burner address; there is no claim deadline. To display HYBURN in
a wallet, import the token address above with **9 decimals**.

With setup completed, a new terminal needs only the project directory and
`.venv/bin/python hyburn.py mine`. The saved connection profile and mining session
are loaded automatically; enter the keystore password to resume. Environment
overrides apply only to the terminal where you set them.

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

## Build the contracts (developers)

For contract development or bytecode verification, install Foundry, clone this repository and run from its root:

```sh
git clone --recurse-submodules https://github.com/hyburnprotocol/hyburn.git
cd hyburn
forge build
```

Compiler settings are pinned in [`foundry.toml`](foundry.toml): Solidity 0.8.30, Cancun EVM, optimizer enabled with 1,000,000 runs, and no metadata hash. The production contracts have no external Solidity dependencies. Tests use forge-std, pinned as a Git submodule. If you cloned without submodules, run `git submodule update --init --recursive`.

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
