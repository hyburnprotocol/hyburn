# Miner changes

## Unreleased

- Automatically claim ended mining rewards at startup and on round changes in
  Python, Node.js, Go and Rust, even if a cost limit skips the next burn. Claims
  consume gas separately from the burn budget.
- Add Shift-F to finish mining, wait for the last round, claim and exit. Ctrl-C
  remains immediate; saved transactions and rewards recover on restart.
- Align the developer console with final settlement and durable claim receipts.

- Add a shared `./hyburn` control center and public wallet-owned liquidity menu.
- Manage positions in the existing Project X HYBURN/WHYPE 0.3% pool, with local
  fork previews, explicit signing and separate per-wallet records and budgets.
- Check whole-operation gas requirements and quote expiry before execution;
  reconcile confirmed transactions, review partial operations and revoke approvals.
- Add the website liquidity guide and repository onboarding/recovery instructions.
- Liquidity-change previews require Anvil. Normal mining and read-only pool views
  do not. The legacy developer liquidity tools were removed; creation records remain
  local and Git-ignored.

## 0.3.0

All four engines now use the same interactive TUI. Stop the running miner before
updating, then run `git pull --ff-only`. The new `./cli/hyburn --engine NAME mine`
launcher prepares packages and rebuilds changed Go/Rust sources automatically.
Python 3.10+ is required for the shared UI, along with the chosen engine toolchain.

- Mining waits for S: start / Q: exit before key loading and transaction recovery.
  **Unattended scripts must add `--yes` before `mine`.** `--plain` keeps native
  line output without the shared UI runtime.
- Tab 7 adds a persistent, incremental all-time burn/round/claim ranking. Initial
  partial coverage, saved progress, reorganization recovery and RPC cooldowns are
  explicit. The analytics cache never replaces the spending journal.
- Tables support search, sorting, own-wallet filtering, claim-status filtering,
  selection and paging. A privacy view hides addresses, amounts and log details.
- Statistics can be paused or refreshed independently of mining; refresh does not
  bypass rate limits. Both completed snapshots and scan coverage are displayed.
- Native engines keep their own signer and transaction implementation; the common
  UI receives only status events. Dependency/build processes do not inherit
  HYBURN wallet secrets.
- Updated onboarding and the website mining guide to describe saved budgets,
  automatic final claims and the shared launcher.

Existing 0.2.0 sessions resume without migration or a budget reset. No contract
redeployment is required. See [TUI.md](TUI.md).

## 0.2.0

All four public miners now save and resume a common session. **Stop older miners
before upgrading.** Older versions do not honor the new wallet lock or journal.

- One offline setup saves the connection profile and encrypted-keystore path.
- `mine` resumes saved settings, burn budget usage and burn count. Gas is extra.
- A first session requires an amount and either a budget or a round limit.
- `--new-session` explicitly authorizes new settings and resets the burn budget;
  repeating `mine` or depositing more HYPE does not reset or enlarge it.
- Pending signed transactions are journaled before broadcast and reconciled before
  any new send. Clients can resume a journal created by another implementation.
- Same-wallet concurrent clients are blocked locally, including the deploy console.
- The default 0.001 HYPE reserve protects claim gas during mining. On normal
  completion the miner waits for the final round and claims automatically.
- Previously burned rounds are skipped after restart. A round changing during
  preflight is rechecked. Ctrl-C during preflight prevents subsequent signing.
- Python retains the terminal dashboard; Node, Go and Rust retain their countdown
  display. Both line logs and the dashboard show session-based spending.

History caches from 0.1.0 remain usable. They are not budget journals: earlier
spending cannot be automatically assigned to the first new session. Keep new
session files when backing up or moving a miner. See [SESSION.md](SESSION.md).

No contract or website deployment is required for this update.
