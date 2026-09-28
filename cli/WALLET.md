# Wallet setup for all four miners

Start with the [mainnet quickstart](../README.md#mine-on-hyperevm). The wallet
interface is the same in Python, Node.js, Go and Rust. These are local signers,
not browser extensions: no WalletConnect or hardware-wallet signing is included.

## Recommended: encrypted Ethereum JSON keystore

Use a dedicated mining account. If you already have a keystore, point to it:

```sh
export HYBURN_KEYSTORE="$HOME/.hyburn/miner.keystore.json"
```

For automatic connection-profile setup, use [setup_miner.py](SESSION.md#first-setup-then-resume).
Otherwise, from the repository root, install the Python dependencies and run the
offline import helper. This helper can prepare a wallet for **any** of the miners:

```sh
python3 -m venv cli/python/.venv
cli/python/.venv/bin/python -m pip install -r cli/python/requirements.txt
cli/python/.venv/bin/python cli/python/wallet_setup.py
export HYBURN_KEYSTORE="$HOME/.hyburn/miner.keystore.json"
```

Private key and password input is hidden. No key is accepted as a command-line
argument, and no RPC is contacted. Import the private key of the dedicated account,
not a seed phrase. The default file is outside the repository; an existing file
is never overwritten. For another account use `--out /absolute/path/name.keystore.json`.
Compare the printed public address with the account in your wallet before funding.
Back up the encrypted file and remember its password; the project cannot recover it.

Every new CLI process prompts to unlock the keystore if a password is needed.
For unattended processes, `HYBURN_KEYSTORE_PASSWORD` is supported, but storing the
password alongside the keystore removes much of the protection of encryption.
Prefer entering it interactively. An account address alone cannot authorize burns.

## Existing raw-key workflows

All four miners also accept `HYBURN_PRIVATE_KEY`. The encrypted-keystore workflow
above is recommended for a first run. Never put keys in CLI arguments, committed
files, screenshots or chat. If both keystore and raw-key settings are present,
the keystore takes precedence. To switch to a keystore, remove stale settings:

```sh
unset HYBURN_PRIVATE_KEY HYBURN_KEYSTORE_PASSWORD
export HYBURN_KEYSTORE="$HOME/.hyburn/miner.keystore.json"
```

## Troubleshooting

### What survives a restart?

All four miners automatically save mining settings, budget usage, gas totals,
confirmed burn count and pending transactions. The same files work across
implementations. Use the [saved-session guide](SESSION.md) for one-time setup,
resume commands, explicit new budgets and recovery behavior.

### Common issues

| Symptom | What to check |
| --- | --- |
| `HYBURN_MINER is not set to a valid address` | Repeat the deployment exports from the quickstart in this terminal; use the Miner address, not the token address. |
| File not found / cannot unlock | Use the absolute keystore path and its encryption password, not necessarily your browser-wallet password. |
| Address differs from Rabby | Stop and check which account's key you imported. Do not fund an unverified address. |
| Balance is zero / insufficient funds | Check the same account on HyperEVM chain 999. Native HYPE pays both burns and gas. |
| RPC chain ID mismatch | The endpoint serves a different chain. Correct `--rpc` / `HYBURN_RPC`; do not simply remove the expected chain ID. |
| Countdown is running | `mine` waits until its send window, 30 seconds before round end by default. |
| Budget was reached | The saved budget is exhausted. Final rewards are claimed automatically; use `--new-session` with full settings to authorize another budget. |
| Last reward has not arrived | Keep the miner open for its automatic final claim, or resume `mine` / run `claim` after the round closes. |
| Transaction timed out | Restart to recover the saved transaction. It blocks new sends until settled. |
| RPC rate limit / unavailable | Wait or use `--rpc` / `HYBURN_RPC` to choose another HyperEVM endpoint. Never start multiple miners to work around a stuck request. |

The `deploy_console.py` tool is for creating a separate protocol deployment.
Ordinary participants should use `hyburn.py`, `hyburn.mjs`, or the Go/Rust miner.
Their saved budgets count burns; the deploy console's saved cap also includes gas. Do not use it as an onboarding shortcut.
