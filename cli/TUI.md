# Shared mining dashboard

Python, Node.js, Go and Rust use the same terminal dashboard. The native engine
still owns its signer, saved spending budget and transactions. The shared Python
UI receives public status events; it never signs on behalf of a native engine.
The developer deployment console uses the same display and statistics modules.

## HL Names

On HyperEVM mainnet, the header, Wallet / Costs tab and visible ranking rows automatically
show a `.hl` primary name when it resolves back to the same wallet address.
Owning a name alone does not set a primary name. The selected ranking row always
retains its full address below the table; names are display labels, never signer,
session, reward, or ranking identifiers. Search also matches names already cached.
The sharing view hides wallet names along with personal addresses and rows.

Name lookups run independently of mining through the public HL Names HTTPS API,
not the mining RPC. Only public addresses/names are sent. The TUI requests names
for visible wallets, with one worker, a bounded queue, two-second request timeouts
and at most one wallet lookup per second. A failed request pauses lookups for a
minute. Positive results expire after one hour; missing/unverified results after
five minutes. Expired labels fall back to addresses while refreshing. Cache files
live in `~/.hyburn/names/999/` (or under `HYBURN_HOME`), separate from sessions.

All four plain CLIs show names at mining startup and in `status` and `history`.
Mining startup lookup is asynchronous. Read-only commands may wait briefly for
the label. Node/Go/Rust reuse the repository's dependency-free Python helper;
if Python or the helper is unavailable, they keep displaying addresses normally.
Only ASCII `.hl` labels are displayed, preventing terminal-control and visually
ambiguous Unicode labels. Names do not authenticate a person's identity.

No extra setup is needed: the integration uses the upstream's documented public
fallback API key. An optional `HLN_API_KEY` environment variable overrides it;
never commit a personal API key. Availability remains subject to HL Names limits.
Disable all name lookups with `HYBURN_HL_NAMES=0` before starting the CLI.
The native helper subprocess receives no wallet keys or passwords.

API source: [HL Names endpoint reference](https://github.com/HLnames/use-hln-api/blob/master/references/endpoints.md)
and [published public key](https://github.com/HLnames/use-hln-api/blob/master/SKILL.md).

## One entry point

From a clone of the repository on macOS/Linux or WSL, with Python 3.10+ and
pip/venv available:

For installation and wallet preparation from scratch, see the
[beginner walkthrough](GETTING_STARTED.md).

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

## Control center

From the repository root, run `./hyburn` (or `./cli/hyburn`). With no arguments,
this opens a numbered terminal menu instead of entering the miner. Select mining,
wallet setup, status, history, engine selection, or a read-only Project X pool
overview. Python, Node.js, Go and Rust are selected in the same menu. Explicit
commands such as `./hyburn --engine rust mine` continue to work. Mining retains
its own start confirmation. Noninteractive use requires an explicit command.

The public pool overview never loads a signer. It shows the existing canonical
HYBURN/WHYPE 0.3% pool and links to Project X. Choose **7 — My liquidity** to manage your own positions through the public
liquidity wizard. See [liquidity management](LIQUIDITY.md). Creating a position
does not create a different pool. Pool balances are not active depth or a trade quote.

The public liquidity menu is the single supported liquidity interface. Historical
pool-creation records remain local and are not required by this menu.

If the ignored local developer configuration exists, the hub also exposes a
separate developer mining console entry. This resumes its own configuration and
session through its existing start confirmation, not the public miner's profile.
The hub tests file existence only; it does not read the configuration or keys.

## Automatic reward settlement

After you authorize mining, the miner checks and claims ended rewards on startup
and once per observed round, even when a price limit skips a burn. Claims use gas
in addition to the burn budget. No claim is sent when nothing is claimable.
Opening the menu, cancelling the start prompt, status/history and dry runs do not
send claims. Pending transactions must be recovered before any new submission.

Press **Shift-F** (`F`) in the mining dashboard to finish: stop new burns, wait for
the last mined round to end, claim rewards, then exit. Keep the process running
and the computer awake. The finish request can take up to 30 seconds to leave a
local wait. Lowercase `f` still filters claim status in tables.
**Ctrl-C exits immediately** and leaves unfinished claims for the next mining
start. Already submitted transactions may still confirm. In a plain POSIX
terminal, `kill -USR1 <miner-pid>` requests the same graceful finish.

If gas, RPC access or a configured spending cap prevents settlement, the miner
stops with an error; rewards remain claimable. Restart with the same session after
resolving the issue. Nothing runs after the program exits.
