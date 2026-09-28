import { Panel } from "@/components/Panel";
import { CONFIG } from "@/lib/config";

export const metadata = { title: "Mine · Hyburn" };

export default function MinePage() {
  return (
    <section className="prose-plain hb-mining-guide" aria-labelledby="mining-guide-title">
      <header className="hb-document-header hb-raised">
        <p className="hb-eyebrow">Hyburn / Mine</p>
        <h1 id="mining-guide-title">Mining guide</h1>
        <p>Four mining engines. One terminal dashboard.</p>
      </header>
      <p>Run an open-source miner to burn HYPE and claim HYBURN on HyperEVM. This website does not connect to your wallet. Your chosen engine signs locally.</p>
      <Panel title="Before you start">
        <ul className="mb-0">
          <li>Use a dedicated wallet funded for your intended burns, transaction gas and the protected reserve. Burned HYPE does not come back.</li>
          <li>Opening the miner shows a start choice. Press S to start or Q to exit. Previously submitted transactions can still confirm after you stop.</li>
          <li>Each burn specifies its round. A late transaction reverts the burn but still spends gas.</li>
        </ul>
      </Panel>
      <h2>1. Get the source</h2>
      <p>Use Git and Python 3.10+ with pip/venv on macOS, Linux or WSL. Review the source before connecting a wallet.</p>
      <p>Source: <a href={CONFIG.repo} target="_blank" rel="noopener noreferrer">{CONFIG.repo}</a>.</p>
      <pre><code>{`git clone ${CONFIG.repo}.git\ncd hyburn`}</code></pre>
      <h2>2. Connect your wallet once</h2>
      <pre><code>./cli/hyburn setup</code></pre>
      <p>The launcher prepares its packages automatically. Wallet setup then runs offline: import a private key with hidden input, or choose an encrypted Ethereum JSON keystore. The shared connection profile stores the keystore path, not its password or private key. Never pass a private key as a command-line argument.</p>
      <p>Fund the verified wallet address with native HYPE. The default protected reserve is 0.001 HYPE; burns and gas need additional funds.</p>
      <h2>3. Choose an engine</h2>
      <p>Stay in the repository root. All four engines use the same dashboard, saved budget and public-event cache. The launcher installs packages and builds missing or changed engines; the selected runtime/toolchain must already be installed.</p>
      <div className="hb-language-guides">
        {[
          { name: "Python", engine: "python", needs: "Python 3.10+ with pip/venv. This is the default engine." },
          { name: "Node.js", engine: "node", needs: "Node.js 22+ and npm, plus Python 3.10+ for the shared UI." },
          { name: "Go", engine: "go", needs: "Go 1.24+, plus Python 3.10+ for the shared UI." },
          { name: "Rust", engine: "rust", needs: "A stable Rust toolchain and linker, plus Python 3.10+ for the shared UI." },
        ].map((language) => (
          <details key={language.engine} className="hb-language hb-raised">
            <summary><strong>{language.name}</strong><span>Shared terminal dashboard</span></summary>
            <div className="hb-language-body">
              <p>{language.needs}</p>
              <pre><code>{`./cli/hyburn --engine ${language.engine} mine --amount 0.000999 --budget 0.001998`}</code></pre>
              <p>This example authorizes at most two minimum burns, with gas additional. Press S to start. Later, use the same command with just <code>mine</code> to resume the saved settings.</p>
            </div>
          </details>
        ))}
      </div>
      <h2>4. Check, start and resume</h2>
      <p>Check the deployment and simulate a burn before sending. Simulation needs an unlocked wallet and enough HYPE for the estimated transaction.</p>
      <pre><code>{`./cli/hyburn status\n./cli/hyburn burn 0.000999 --dry-run\n./cli/hyburn mine --amount 0.000999 --budget 0.001998`}</code></pre>
      <p>The first burn normally waits until 30 seconds before the round ends. The countdown runs locally. Keep the computer awake. On reaching the saved limit, the miner waits for its final round to end and automatically claims its remaining rewards.</p>
      <pre><code>{`./cli/hyburn mine`}</code></pre>
      <p>A restart resumes the same budget; it does not reset spending. Depositing more HYPE does not increase that budget. To authorize a new budget, use <code>mine --new-session</code> with your full intended settings. Run one engine at a time for a wallet.</p>
      <h2>Explore the dashboard</h2>
      <table>
        <thead><tr><th>Key</th><th>View</th></tr></thead>
        <tbody>
          <tr><td>1 / 2 / 3</td><td>Overview, wallet costs and engine logs.</td></tr>
          <tr><td>4</td><td>Current-round wallets ranked by burned HYPE.</td></tr>
          <tr><td>5</td><td>Your recent participation and actual reward claims.</td></tr>
          <tr><td>6</td><td>Token CA, Miner contract and chain.</td></tr>
          <tr><td>7</td><td>All-time participation: cumulative burns, rounds and claimed rewards.</td></tr>
        </tbody>
      </table>
      <p>Use / to search, o to sort, m to filter to your wallet, f to filter claim status, and v for privacy view. The p key pauses statistics only, not mining. Ctrl-C stops the engine.</p>
      <p>The all-time cache is created and resumed automatically. Initial coverage is marked PARTIAL; COMPLETE is always through a stated block. Rankings count wallets, not people. Claimed rewards are not token balances. Statistics use limited background reads only while their page is open.</p>
      <h2>Options</h2>
      <table>
        <thead><tr><th>Option</th><th>Meaning</th></tr></thead>
        <tbody>
          <tr><td><code>--amount</code></td><td>HYPE per round; required for the first session and then saved.</td></tr>
          <tr><td><code>--budget / --rounds</code></td><td>Saved cumulative burn or round limit, across restarts. Gas is additional.</td></tr>
          <tr><td><code>--reserve</code></td><td>Balance protected for gas; default 0.001 HYPE.</td></tr>
          <tr><td><code>--at</code></td><td>Seconds before round end to send; default 30.</td></tr>
          <tr><td><code>--max-cost</code></td><td>A condition checked at send time. Later burns by others reduce your share, so it is not a final unit-price guarantee.</td></tr>
          <tr><td><code>--dry-run</code></td><td>Simulate without sending a transaction.</td></tr>
          <tr><td><code>--plain / --yes</code></td><td>Before mine: line output / explicitly skip the start choice for unattended execution.</td></tr>
        </tbody>
      </table>
      <h2>Updates and manual claims</h2>
      <p>Run <code>git pull --ff-only</code> while the miner is stopped. The next launcher run prepares changed dependencies or builds. Your saved budget and statistics remain separate from the source checkout.</p>
      <pre><code>{`./cli/hyburn claim\n./cli/hyburn history`}</code></pre>
      <p>There is no claim deadline. You can also call <code>burn(expectedRoundId)</code> or <code>claimMany(roundIds, account)</code> directly on the Miner contract. Claims always pay the named account.</p>
    </section>
  );
}
