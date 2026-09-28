# Miner changes

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
