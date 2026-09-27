# Wallet setup for all four miners

Start with the [mainnet quickstart](../README.md#mine-on-hyperevm). The wallet
interface is the same in Python, Node.js, Go and Rust. These are local signers,
not browser extensions: no WalletConnect or hardware-wallet signing is included.

## Recommended: encrypted Ethereum JSON keystore

Use a dedicated mining account. If you already have a keystore, point to it:

```sh
export HYBURN_KEYSTORE="$HOME/.hyburn/miner.keystore.json"
```

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

The public miners are not yet a fully resumable mining session manager. Their
round-history cache is saved automatically under `~/.hyburn` (or `HYBURN_HOME`),
keyed by chain, Miner and account. That cache avoids repeat history reads; it does
not preserve your spending authorization or pending transaction journal.

| State | Public miners (Python / Node / Go / Rust) |
| --- | --- |
| Encrypted wallet file | Kept on disk; unlock again on launch. |
| RPC, contract, keystore path, burn settings | Supply via environment / arguments again in a new shell. |
| Round history and claim cache | Saved and reused automatically. |
| Burn budget used, burn count and last processed round | In memory only; reset on restart. |
| Submitted transaction awaiting receipt | Check the transaction hash before restarting; automatic recovery is not implemented. |
| Multiple processes for the same wallet | No session lock; run only one miner. |
| Last round's reward after stopping | Run `claim` once that round ends. |

During a running `mine` loop, timing and claiming older rounds with the next burn
are automatic. Closing the process or sleeping the computer interrupts mining.
A restart in the same round can burn again, and the same `--budget` authorizes a
fresh burn budget. Do not treat restarting as resuming an unchanged spending cap.

A fully resumable workflow needs persisted non-secret settings, an atomic session
journal with cumulative budget usage, pending-receipt recovery before any new send,
and a per-wallet process lock. These are not provided by the history cache or TUI.

### Common issues

| Symptom | What to check |
| --- | --- |
| `HYBURN_MINER is not set to a valid address` | Repeat the deployment exports from the quickstart in this terminal; use the Miner address, not the token address. |
| File not found / cannot unlock | Use the absolute keystore path and its encryption password, not necessarily your browser-wallet password. |
| Address differs from Rabby | Stop and check which account's key you imported. Do not fund an unverified address. |
| Balance is zero / insufficient funds | Check the same account on HyperEVM chain 999. Native HYPE pays both burns and gas. |
| RPC chain ID mismatch | The endpoint serves a different chain. Correct `--rpc` / `HYBURN_RPC`; do not simply remove the expected chain ID. |
| Countdown is running | `mine` waits until its send window, 30 seconds before round end by default. |
| Budget was reached | That run stopped. The public CLI's burn budget resets on restart and excludes gas. |
| Last reward has not arrived | Wait for that round to close, then run `claim`; keep HYPE for gas. |
| Transaction timed out | Check the printed transaction hash on the explorer before retrying; it may still confirm. |
| RPC rate limit / unavailable | Wait or use `--rpc` / `HYBURN_RPC` to choose another HyperEVM endpoint. Never start multiple miners to work around a stuck request. |

The `deploy_console.py` tool is for creating a separate protocol deployment.
Ordinary participants should use `hyburn.py`, `hyburn.mjs`, or the Go/Rust miner.
Their budgets are per-process burn budgets; the deploy console's saved budget has
different semantics and includes gas. Do not use it as an onboarding shortcut.
