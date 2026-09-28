# Shared mining dashboard

Python, Node.js, Go and Rust use the same terminal dashboard. The native engine
still owns its signer, saved spending budget and transactions. The shared Python
UI receives public status events; it never signs on behalf of a native engine.
The developer deployment console uses the same display and statistics modules.

## One entry point

From a clone of the repository on macOS/Linux or WSL, with Python 3.10+ and
pip/venv available:

```sh
./cli/hyburn setup
./cli/hyburn mine --amount 0.000999 --budget 0.001998
```

Setup imports your wallet offline (after any dependency installation). Fund your
mining wallet with native HYPE for burns, gas and the protected reserve. The
example authorizes two minimum burns, plus gas. On subsequent starts:

```sh
./cli/hyburn mine
./cli/hyburn --engine node mine
./cli/hyburn --engine go mine
./cli/hyburn --engine rust mine
```

Choose one process at a time for a wallet. Node requires Node.js 22+ and npm;
Go requires Go 1.24+; Rust requires a stable Rust toolchain and linker. The launcher
installs packages and builds missing or outdated engines automatically. It does
not install system runtimes, download repository updates, or change your budget.
Run `git pull --ff-only` to receive updates; the next launcher run builds changed
sources if needed. Package/build subprocesses do not receive HYBURN wallet secrets.

Existing native commands also open this UI automatically when stdin/stdout/stderr
are interactive. The UI runtime is prepared in `cli/python/.venv` on first use.
A missing Python runtime stops with an explanation; it never silently starts
mining instead. Direct native commands with `--plain` need no Python UI runtime.

Opening `mine` waits for **S: start / Q: exit**. Plain/small terminals ask `[y/N]`.
No signer loading or saved-transaction recovery starts before this choice.
Previously broadcast transactions can still confirm independently. Unattended
runs must explicitly pass `--yes` before `mine`. Use `--plain` for line output.

## Pages and controls

| Key | Page |
|---|---|
| 1 | Mining overview, local countdown and recorded costs |
| 2 | Wallet, saved limits, spending and connection facts |
| 3 | Engine log |
| 4 | Current-round wallet burn ranking |
| 5 | Your latest 20 participation rounds and actual claims |
| 6 | Token CA, Miner contract and chain |
| 7 | All-time mining participation ranking |
| ? | Help |

Tab changes pages. In tables, j/k or arrows select rows; PgUp/PgDn move five rows;
g/G jump to the first/last row. The selected wallet's full address is shown below
the table. Abbreviated addresses in rows are only a display convenience.

- `/`: search address, round or status; Enter applies, Esc cancels.
- `o`: change descending sort. All-time: burned HYPE, participated rounds,
  actual claimed HYBURN or burn transaction count.
- `m`: show only your wallet in a ranking; its rank remains the position in the
  complete loaded table before filtering, not rank 1 of the filtered list.
- `f`: filter your history by ALL / OPEN / CLAIMABLE / CLAIMED.
- `c`: clear search and filters.
- `r`: request a refresh without bypassing RPC cooldowns.
- `p`: pause/resume **statistics only**. Mining keeps running.
- `v`: sharing view. Keeps public round/chain information, contract addresses and
  aggregate statistics. Hides personal wallet rows, ranks, shares, history, filters,
  amounts, spending settings and raw logs. Personal filters are preserved but
  inactive for display/input until privacy is disabled.

Privacy masks the TUI, not the blockchain or your terminal window. Small public
participation counts may still allow inference. Crop screenshots to the TUI;
window titles, previous shell output, setup prompts and `--plain` logs are outside
this protection. Never share a private key, password or authenticated RPC URL.
  This is presentation masking, not deletion or anonymization of on-chain data.
- Ctrl-C: stop mining. Submitted transactions may confirm after exit.

TUI rendering and the countdown make no RPC requests. Statistics run only while
a statistics page is visible. Requests are spaced at least two seconds apart;
normal snapshots are refreshed at most once per 60 seconds. Initial all-time
backfill continues in batches of at most five 1,000-block ranges while tab 7 is
open. Switching tabs or pausing stops new reads; an in-flight read can complete.
New statistics reads pause around the send window and transaction preparation.
An RPC failure keeps the previous snapshot, marks it unavailable and waits 60
seconds before retrying. Limits remain shared with the engine and other clients
using the same provider/IP.

## Automatic, persistent statistics

No paths or cache settings are needed. All users get an automatically created
`~/.hyburn/insights/<chain>-<miner>.sqlite3` cache (`HYBURN_HOME` overrides the
base directory). It is scoped to the actual connected chain and contract, shared
across wallets and implementations, and contains only public burn/claim events.
The private mining transaction journal remains separate and authoritative.

When no deployment block was configured, the index locates genesis by chain
block timestamps instead of scanning millions of pre-mining blocks. Each range
is committed atomically with a block hash. Restarting continues from the saved
cursor. A changed checkpoint rolls back to a matching checkpoint and repairs
affected wallet totals; a deeper reorganization rebuilds from genesis. Duplicate
logs and competing cache writers cannot increase totals twice. Integer amounts
are stored exactly as decimal strings; display values round to nine decimals.
A corrupt/incompatible analytics cache is preserved with an `.invalid-*` suffix
and rebuilt. Locked/unwritable caches are not treated as corruption, and failures
do not reset the spending journal or stop the mining engine.

`PARTIAL` means only the displayed block coverage has been indexed. Its rankings
are provisional, even if your wallet currently ranks first. `COMPLETE through
block N` means coverage through that snapshot's block, not a live chain feed.
The timestamp/age indicates the last completed local snapshot update.

Ranks measure mining participation, not token holdings. Wallets are not people;
a single person may use several wallets. Current-round shares can change before
the round closes. Claimed HYBURN is the amount in RewardClaimed events, not an
estimate of outstanding rewards and not the wallet's transferable token balance.
Equal values use address order as a deterministic tie-breaker.
