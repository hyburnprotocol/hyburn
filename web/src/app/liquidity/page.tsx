import Link from "next/link";
import { Panel } from "@/components/Panel";
import { CONFIG } from "@/lib/config";

export const metadata = { title: "Liquidity · Hyburn" };
const pool = "0x561fF10F136da03be56F31A53cd8D87f93694106";
const token = "0xC02E218F52ea5D38759BB1AfA92C197eF30673B4";

export default function LiquidityPage() {
  return (
    <section className="prose-plain hb-mining-guide" aria-labelledby="liquidity-title">
      <header className="hb-document-header hb-raised">
        <p className="hb-eyebrow">Hyburn / Liquidity</p>
        <h1 id="liquidity-title">Your liquidity. Your position.</h1>
        <p>Manage a position in the existing HYBURN / WHYPE pool on Project X.</p>
      </header>
      <p>Liquidity provision is optional and separate from <Link href="/mine/">mining</Link>. Each provider owns a position NFT with their chosen price range. Creating a position does not create a new pool or change HYBURN issuance.</p>
      <Panel title="Verify the pool">
        <p>Network: HyperEVM (999). Pool fee: 0.3%.</p>
        <p>HYBURN token CA:<br /><a className="break-all" href={`https://hyperevmscan.io/address/${token}`} target="_blank" rel="noopener noreferrer">{token}</a></p>
        <p>Project X pool:<br /><a className="break-all" href={`https://hyperevmscan.io/address/${pool}`} target="_blank" rel="noopener noreferrer">{pool}</a></p>
        <p>Verify addresses, not just the token name. HYPE used in this pool is wrapped as WHYPE.</p>
        <a href="https://www.prjx.com" target="_blank" rel="noopener noreferrer">Open Project X →</a>
      </Panel>
      <h2>Open the terminal menu</h2>
      <p>Already have the repository? Update it, then open the control center from its folder:</p>
      <pre><code>{`git pull --ff-only\n./hyburn`}</code></pre>
      <p>Choose <strong>7 — My liquidity</strong>, or run <code>./hyburn liquidity</code>. Python, Node.js, Go and Rust miners all share this liquidity tool. New here? Start with the <a href={`${CONFIG.repo}/blob/main/cli/GETTING_STARTED.md`} target="_blank" rel="noopener noreferrer">installation guide</a>.</p>
      <ol>
        <li>Use an encrypted wallet from <code>./hyburn setup</code>, or enter a public address for previews. Only explicit execution requests a local signing key or keystore password.</li>
        <li>View your positions and select an owned NFT. If you have none, choose <strong>New range in the SAME pool</strong>.</li>
        <li>Enter maximum token amounts and prices in HYPE per HYBURN. Review the actual range after tick rounding and the expected amounts.</li>
        <li>Run the preview. Stop mining with the same wallet before confirming and signing a liquidity operation.</li>
      </ol>
      <Panel title="Requirements and signing">
        <p>Use macOS, Linux or Windows WSL with Python 3.10+ and pip/venv. Liquidity-change previews also require <a href="https://getfoundry.sh" target="_blank" rel="noopener noreferrer">Foundry Anvil</a>; ordinary mining and pool reads do not.</p>
        <p>This website does not connect to your wallet or request keys. Do not enter a private key into this website, a command argument, GitHub or chat. The terminal uses hidden input only after you explicitly choose to execute.</p>
      </Panel>
      <h2>Choose what to manage</h2>
      <table>
        <thead><tr><th>Action</th><th>What changes</th></tr></thead>
        <tbody>
          <tr><td>Add liquidity</td><td>Add tokens to your selected range; the current price determines the usable ratio.</td></tr>
          <tr><td>New range</td><td>Create another position NFT in the same pool.</td></tr>
          <tr><td>Remove liquidity</td><td>Withdraw a percentage and collect the proceeds atomically. The NFT remains yours.</td></tr>
          <tr><td>Collect</td><td>Receive owed HYBURN and WHYPE, which may include previously withdrawn principal as well as fees.</td></tr>
          <tr><td>Wrap / unwrap</td><td>Explicitly convert native HYPE to WHYPE or back.</td></tr>
        </tbody>
      </table>
      <p>With prices expressed as HYPE per HYBURN, a position below its range needs HYBURN only; inside the range it needs both assets; above the range it needs WHYPE only. A range change requires withdrawal and a separately reviewed new position. Price can move between those operations.</p>
      <h2>Budgets, recovery and risk</h2>
      <p>Liquidity uses its own budget. Defaults are 0.5% slippage, a 0.01 HYPE gas budget and a 0.001 HYPE protected native balance. These are editable limits, not a fee quote. Token deposits and wrapping are additional to gas.</p>
      <p>The tool previews transactions before signing and saves transaction hashes before sending. After interruption, reconcile receipts first. Unknown or pending transactions block further execution. Closing a reviewed partial operation does not undo its confirmed steps or revoke remaining approvals.</p>
      <p>Trading can change your token mix and leave you with less value than simply holding the assets. Fees, buyers and exit liquidity are not guaranteed. Outside your range, the position stops earning swap fees until price returns. HYBURN mining does not automatically replenish pool liquidity.</p>
      <p><a href={`${CONFIG.repo}/blob/main/cli/LIQUIDITY.md`} target="_blank" rel="noopener noreferrer">Full CLI guide and recovery instructions →</a></p>
    </section>
  );
}
