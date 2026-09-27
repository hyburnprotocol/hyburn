import Link from "next/link";
import { CONFIG } from "@/lib/config";

export const metadata = { title: "Whitepaper · Hyburn" };

function Fact({ k, v, href }: { k: string; v: string; href?: string }) {
  return (
    <tr>
      <th scope="row">{k}</th>
      <td className="hb-num break-all">{href && v ? <a className="underline" href={href} target="_blank" rel="noopener">{v}</a> : v || "to be published at deployment"}</td>
    </tr>
  );
}

export default function WhitepaperPage() {
  const addr = (a: string) => (a ? `${CONFIG.explorer}/address/${a}` : undefined);
  return (
    <article className="prose-plain hb-document">
      <header className="hb-document-header hb-raised">
        <p className="hb-eyebrow">Hyburn / Whitepaper</p>
        <h1>Whitepaper</h1>
        <p>A fixed-supply token issued by burning HYPE.</p>
      </header>

      <h2>Abstract</h2>
      <p>Hyburn is a contract on HyperEVM that opens a round every 999 seconds. Anyone may burn HYPE into the open round. When it ends, the HYBURN issued for that round is divided among the burners in proportion to what each burned. Issuance per round is fixed in advance and halves every 86,400 non-empty rounds, 43 times, until exactly 999,000,000 HYBURN exist. Burned HYPE goes to a vault that cannot be opened. There is no premine, no team allocation, no administrator, no upgrade path, no randomness and no way to change any parameter after deployment.</p>

      <h2>1. Rounds</h2>
      <p>Time is divided into rounds of 999 seconds starting at a genesis timestamp fixed at deployment: round <code>r</code> covers <code>[genesis + 999r, genesis + 999(r+1))</code>. Genesis is the deployment block timestamp plus 999 seconds (16 minutes, 39 seconds). Burns are rejected before genesis; round 0 opens at genesis.</p>
      <p>A round that receives no burn issues nothing and does not advance the issuance schedule. Each round that receives at least one burn is assigned the next <em>mining sequence</em> number at its first burn. Issuance depends only on that number.</p>

      <h2>2. Burning</h2>
      <p>A burn is a call to <code>burn(expectedRoundId)</code> carrying HYPE as value, at least 0.000999 HYPE, with no upper bound. The HYPE is forwarded in the same transaction to a vault contract whose only function is to receive; nothing can withdraw from it. The contract records the amount against the sender for that round. Several burns by the same account in the same round accumulate.</p>
      <p>The caller names the round the burn is intended for. If the transaction is included after that round has ended, the call reverts and the HYPE is returned. A burn therefore never lands in a round the burner did not choose.</p>
      <p>This is an economic burn on HyperEVM. It removes the HYPE from circulation permanently; it is not a reduction of HYPE&apos;s protocol-level supply on HyperCore.</p>

      <h2>3. Issuance</h2>
      <pre>{`reward(seq) = 5,781.25 HYBURN >> floor(seq / 86,400)
reward(3,715,199) += 0.0012096 HYBURN   (arithmetic remainder, last sequence)`}</pre>
      <table>
        <thead><tr><th>Era</th><th>Sequences</th><th>Per round</th><th>Era total</th></tr></thead>
        <tbody>
          <tr><td>0</td><td>0 – 86,399</td><td>5,781.25</td><td>499,500,000 (50%)</td></tr>
          <tr><td>1</td><td>86,400 – 172,799</td><td>2,890.625</td><td>249,750,000</td></tr>
          <tr><td>2</td><td>172,800 – 259,199</td><td>1,445.3125</td><td>124,875,000</td></tr>
          <tr><td>…</td><td>…</td><td>…</td><td>…</td></tr>
          <tr><td>42</td><td>3,628,800 – 3,715,199</td><td>0.000000001</td><td>0.0000864 + remainder</td></tr>
        </tbody>
      </table>
      <p>The sum over all 3,715,200 sequences is exactly 999,000,000. If every round is non-empty, one era lasts 999 days and the schedule ends after about 117.6 years. Economically meaningful issuance ends much earlier: from era 13 a round issues less than one HYBURN. After the last sequence, burning is rejected.</p>

      <h2>4. Distribution</h2>
      <p>For an account that burned <code>b</code> wei into a round whose total is <code>T</code> wei, the payout is <code>reward × b / T</code> with integer division. The rounding loss is below one base unit (0.000000001 HYBURN) per account per round and is never minted, so the minted supply is at most the scheduled supply.</p>
      <p>Timing within the round does not change the payout. Splitting a burn across wallets does not change the payout. Burning more is the only way to receive more.</p>

      <h2>5. Claiming</h2>
      <p>Payouts are pulled, not pushed. After a round ends, <code>claim(round, account)</code> mints the account&apos;s share to the account. Anyone may call it for anyone; the tokens only ever go to the burner. There is no deadline. <code>claimMany</code> claims several rounds in one transaction, and a burn into a new round claims the caller&apos;s finished rounds in the same transaction.</p>

      <h2>6. Cost of a round</h2>
      <p>There is no difficulty parameter. The total burned in a round <em>is</em> the difficulty: the more HYPE in the round, the fewer HYBURN each HYPE receives. It adjusts every round with no retarget rule. Rounds with low participation pay more per HYPE.</p>

      <h2>7. Properties</h2>
      <ul>
        <li>No one received anything before the first burn. The deployer has no privileges; the deploying key can do nothing the public cannot.</li>
        <li>The supply cap, the schedule, the round length and the minimum burn are constants in the bytecode. There is no function that changes them, pauses the contract, upgrades it or withdraws from the vault.</li>
        <li>Nothing is drawn. Payouts are a deterministic function of the burns in a round. No validator, proposer, bot or operator can change who receives what.</li>
        <li>The burn record (every round, every account, every amount) is public on chain and sufficient to reconstruct every balance.</li>
      </ul>

      <h2>8. Trust assumptions and limits</h2>
      <ul>
        <li><strong>HyperBFT.</strong> Hyburn runs on HyperEVM and inherits its consensus entirely. The burn secures nothing; the chain does. If Hyperliquid stops, Hyburn stops.</li>
        <li><strong>The last block of a round.</strong> The validator producing it can leave a transaction out. The excluded burner misses the round and keeps the HYPE; the remaining burners&apos; shares rise proportionally. This is the entire extent of the influence and it is avoided by not burning in the final second.</li>
        <li><strong>Price.</strong> The contract guarantees the rules, the supply and that burning is the only source of HYBURN. It does not guarantee a price. HYBURN has no function inside the contract.</li>
        <li><strong>Liquidity.</strong> There is no treasury, so no one is obliged to provide a market.</li>
      </ul>

      <h2>9. Contracts</h2>
      <p>Three contracts, deployed by one transaction, none upgradeable. The Miner holds no funds at any time.</p>
      <table>
        <thead><tr><th>Contract</th><th>Role</th><th>State-changing functions</th></tr></thead>
        <tbody>
          <tr><td><code>HyburnMiner</code></td><td>rounds, burn, claim</td><td><code>burn</code>, <code>burnAndClaim</code>, <code>claim</code>, <code>claimMany</code></td></tr>
          <tr><td><code>HyburnToken</code></td><td>ERC-20, 9 decimals, minter fixed to the Miner</td><td>standard ERC-20 transfers; <code>mint</code> (Miner only)</td></tr>
          <tr><td><code>HypeBurnVault</code></td><td>receives burned HYPE</td><td>none</td></tr>
        </tbody>
      </table>
      <table>
        <tbody>
          <Fact k="Chain" v={`${CONFIG.chainName} · chain id ${CONFIG.chainId}`} />
          <Fact k="Miner" v={CONFIG.miner} href={addr(CONFIG.miner)} />
          <Fact k="Token (HYBURN)" v={CONFIG.token} href={addr(CONFIG.token)} />
          <Fact k="Burn vault" v={CONFIG.vault} href={addr(CONFIG.vault)} />
          <Fact k="Deployment tx" v={CONFIG.deployTx} href={CONFIG.deployTx ? `${CONFIG.explorer}/tx/${CONFIG.deployTx}` : undefined} />
          <Fact k="Deployment block" v={CONFIG.deployBlock} />
          <Fact k="Genesis" v={CONFIG.genesis} />
          <Fact k="Source repository" v={CONFIG.repo} href={CONFIG.repo || undefined} />
          <Fact k="Source commit" v={CONFIG.commit} />
        </tbody>
      </table>
      <p>Building the source at that commit with the compiler settings recorded in the repository must reproduce the deployed bytecode exactly. The comparison command and the test suite are in the repository README.</p>

      <h2>10. Parameters</h2>
      <table>
        <thead><tr><th>Parameter</th><th>Value</th></tr></thead>
        <tbody>
          <tr><td>Round length</td><td>999 seconds</td></tr>
          <tr><td>Start delay after deployment</td><td>999 seconds (16 minutes, 39 seconds)</td></tr>
          <tr><td>Initial issuance per round</td><td>5,781.25 HYBURN</td></tr>
          <tr><td>Halving interval</td><td>86,400 non-empty rounds</td></tr>
          <tr><td>Number of halvings</td><td>43</td></tr>
          <tr><td>Total supply</td><td>999,000,000 HYBURN</td></tr>
          <tr><td>Decimals</td><td>9</td></tr>
          <tr><td>Minimum burn</td><td>0.000999 HYPE</td></tr>
          <tr><td>Maximum burn</td><td>none</td></tr>
        </tbody>
      </table>

      <h2>11. Mining software</h2>
      <p>Four miner implementations (Python, Rust, Go, Node.js) share one command set and pass the same scripted scenario. See <Link className="underline" href="/mine/">Mine</Link>. Both actions are also plain contract calls from any explorer.</p>
    </article>
  );
}
