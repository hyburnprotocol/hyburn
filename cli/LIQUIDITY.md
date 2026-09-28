# Manage your HYBURN liquidity

Run `./hyburn` from the repository root and choose **7 — My liquidity**.
Alternatively use `./hyburn liquidity`. This same public module is available
regardless of your Python, Node.js, Go or Rust mining-engine selection.

This manages your own positions in the existing HYBURN/WHYPE 0.3% Project X pool:
`0x561fF10F136da03be56F31A53cd8D87f93694106`.
It never creates another pool or deploys a token. Each new range creates an LP
NFT belonging to your signing wallet. There is no developer wallet or default NFT.

## First use

1. Run `./hyburn setup` if you want to reuse an encrypted mining-wallet profile.
   Opening liquidity only reads its public address, not its decrypted key.
   You may instead enter a public wallet address for previews and provide a key
   locally only when explicitly signing. Never paste a key into a command or chat.
2. Choose **My positions / overview** to discover your positions in this pool.
   Select an NFT from the owned-position list with **Select another owned position NFT**; choose 0 to clear the selection. The choice is saved
   per wallet. Ownership is rechecked before operations; a transferred NFT cannot
   be managed just because its ID was saved.
3. If you have no position, choose **New range in the SAME pool**. Enter maximum
   HYBURN/WHYPE amounts and prices in **HYPE per HYBURN**. No existing NFT is needed.
4. Review the fork preview: actual tick-aligned prices, expected token amounts,
   minimum amounts, transaction count and gas usage. The program may use less
   than your entered maximum. Outward tick rounding may require both assets.
5. To execute, stop mining with the same wallet, choose to continue, then confirm
   the action and unlock your wallet locally. It re-simulates before signing.

Changing liquidity requires **Foundry Anvil** for local fork verification.
Install it from https://getfoundry.sh using its official instructions. The CLI
does not install or run downloaded installers automatically. If Anvil is absent,
mutating operations stop with setup instructions. Pool/position reads do not
require Anvil. Supported terminals are macOS, Linux and Windows through WSL.

## Actions

- Add to a selected position, or create a new range in the same pool.
- Remove a percentage of liquidity and collect proceeds in one atomic transaction.
- Collect owed tokens. These may include previously withdrawn principal, not just fees.
- Explicitly wrap HYPE into WHYPE or unwrap WHYPE into HYPE.
- Read receipts after interruption with **Reconcile**; never automatically resend.

A range migration requires removal followed by a separately reviewed new
position; it is not an atomic migration. Price can change between operations.
Changing the 0.3% fee tier is not supported because that would require another pool.

## CLI examples (previews only)

```sh
./hyburn liquidity status
./hyburn liquidity status --wallet YOUR_PUBLIC_ADDRESS
./hyburn liquidity add --position YOUR_NFT_ID --hyburn 100 --whype 0.001
./hyburn liquidity new --hyburn 100 --min-price 0.00006 --max-price 0.0001
./hyburn liquidity remove --position YOUR_NFT_ID --percent 25
./hyburn liquidity collect --position YOUR_NFT_ID
./hyburn liquidity wrap --amount 0.01
./hyburn liquidity unwrap --amount 0.01
./hyburn liquidity reconcile
```

Replace placeholders with your own values. Prices/amounts are examples, not
recommendations; they may not be usable at the current pool price. Add
`--execute` only after reviewing a preview. `--keystore PATH` overrides the saved
keystore. An address alone cannot authorize transactions.

## Separate budgets and records

Liquidity operations do not inherit a mining budget. Default slippage is 0.5%,
gas budget 0.01 HYPE, and protected native HYPE reserve 0.001 HYPE. These are
editable in the wizard. Token deposits and wrapping are separate from gas cost.
The signer must match the selected public address. Mining and liquidity share a
wallet lock across the four engines, preventing simultaneous local signing.
Block mode is detected but never changed automatically.

State is stored outside the repository under
`~/.hyburn/liquidity/999/<wallet>/`, or the corresponding `HYBURN_HOME` location.
It includes selected NFT, preview and transaction journal. Completed journals
are archived. Private keys and signed raw transactions are never saved there.

An interrupted transaction batch blocks further execution until reviewed.
`reconcile` checks receipts without retrying or approving continuation. Partial
completion can leave approvals or an already minted position; never delete a
journal just to retry. After all submitted hashes are resolved, `./hyburn liquidity recover` shows
confirmed steps and remaining approvals. Explicitly closing that reviewed local
operation permits a fresh preview; it never undoes or repeats completed steps.
Use `./hyburn liquidity revoke` to preview clearing remaining token approvals,
then add `--execute` only after review. Pending or unknown hashes cannot be closed. Position discovery is bounded to 500 NFTs; specify an ID for larger wallets.

The legacy developer liquidity scripts were retired. Historical pool-creation
records remain local and Git-ignored; this module does not depend on them.

Before signing, the tool checks the entire batch gas ceiling and native balance.
Each transaction is still checked again because network fees can change. Quotes
expire after ten minutes; a stale preview cannot authorize a new liquidity step.
Confirmed operations interrupted before the final local save can be reconciled
back to complete. Remaining approval cleanup can still run after quote expiry.
