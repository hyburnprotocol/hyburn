# Saved mining sessions

All four public miners use the same connection profile and transaction journal.
A normal restart resumes the saved budget; it never grants a fresh budget.

## First setup, then resume

From the repository root (Python 3.10+; macOS/Linux or WSL):

```sh
python3 -m venv cli/python/.venv
cli/python/.venv/bin/python -m pip install -r cli/python/requirements.txt
cli/python/.venv/bin/python cli/python/setup_miner.py
```

Setup runs offline. Select an existing Ethereum JSON keystore or import a private
key with hidden input. It saves the mainnet RPC, chain, Miner, deployment block and
keystore **path**, not its password or private key, in `~/.hyburn/config.json`.
All four implementations load that profile; explicit environment variables and
command-line connection options take precedence. A raw-key environment override
also takes precedence over the profile's keystore path. Existing files are never
overwritten by setup. Back up the encrypted keystore and password separately.

Choose the amount and a bounded budget once. This example authorizes two minimum
burns, plus gas, and keeps 0.001 HYPE available for later claim gas:

```sh
cli/python/.venv/bin/python cli/python/hyburn.py mine --amount 0.000999 --budget 0.001998
```

The equivalent `mine` options work with Node, Go and Rust. Thereafter, even in a
new terminal, use your installed implementation with **no repeated options**:

```sh
cli/python/.venv/bin/python cli/python/hyburn.py mine
# Or switch implementation after stopping the first process:
node cli/node/hyburn.mjs mine
cli/go/hyburn mine
cli/rust/target/release/hyburn mine
```

Enter the keystore password at launch. Keep the computer awake and the process
running. Timing, earlier-round claims and session saving are automatic. On reaching
the budget or round limit, the miner waits for the last round to close and claims
its remaining rewards automatically. This may take up to one round. Ctrl-C skips
that remaining work; the next `mine` resumes it. You can also run `claim` directly.

## Spending rules

- `--budget` is the saved cumulative **burn** budget. Gas is additional and recorded
  separately. At least `--budget` or `--rounds` is required for a new live session;
  a round limit alone sets its burn budget to `amount × rounds`.
- `--rounds` counts confirmed burns across restarts, not per process.
- `--reserve` defaults to **0.001 HYPE**. A burn must leave this balance after its
  value plus maximum gas fee. Claims can use this reserve. It is a floor, not a
  promise that every future gas price will be affordable.
- Changing saved settings requires `--new-session` and the complete intended
  settings. It recovers pending transactions first, archives the previous session,
  and resets the burn budget usage/count. It does not repeat an already-burned round.
- Depositing more HYPE does not increase the saved burn budget.
- Manual `burn` is a separate explicit authorization and is not charged to the
  automatic mining budget. Its transaction is still journaled and wallet-locked.
- `--dry-run` does not create or reset a live session or broadcast a transaction.

For example, after an exhausted session, explicitly authorize another two burns:

```sh
cli/python/.venv/bin/python cli/python/hyburn.py mine --new-session --amount 0.000999 --budget 0.001998
```

## Recovery and boundaries

Before broadcasting, the miner atomically writes the transaction hash and signed
bytes. After confirmation it records actual receipt gas, successful burn value,
burn count and last round. If submission or confirmation is interrupted, restart:
it checks the saved hash first and can rebroadcast only the **identical signed
transaction**, never a replacement burn. A reverted transaction records gas but
adds no burn value. Recovery is attempted before a new budget or transaction.

Unresolved transactions block new sends. Prolonged RPC failures/timeouts stop the
process with the journal intact; restore RPC access and run `mine` again. There is
no automatic fee replacement or background service. An unrelated pending wallet
transaction must settle first. Use one dedicated wallet and one machine; the local
lock cannot coordinate with a second computer or an external wallet app.

The local lock is an OS-owned loopback listener (no RPC server or signing API).
It spans implementations and `HYBURN_HOME` directories and is released on exit,
including a crash. A port collision fails closed with a lock error. Filesystems
and process environments must be local; shared network homes are not supported.

Files live under `HYBURN_HOME` (default `~/.hyburn`):

| File | Purpose |
| --- | --- |
| `config.json` | Non-secret connection values and keystore path |
| `<chain>-<miner>-<wallet>.session.json` | Version 1 settings, confirmed burn/gas totals and pending signed transaction |
| `<chain>-<miner>-<wallet>.session.previous.json` | Previous session when explicitly starting a new budget |
| `<chain>-<miner>-<wallet>.json` | Rebuildable history cache; **not** the spending journal |

Journal writes use a private temporary file, fsync and atomic replacement. A
malformed journal stops mining instead of silently resetting spending. Do not
remove session files to resolve errors; retain them when backing up or moving a
miner. Older CLI versions do not understand these journals or locks; stop them
and upgrade before using the new session workflow. Historical burns made before
the journal existed are not retroactively charged to the new budget.
