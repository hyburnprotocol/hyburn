import { Panel } from "@/components/Panel";
import { CONFIG } from "@/lib/config";

export const metadata = { title: "Mine · Hyburn" };

export default function MinePage() {
  return (
    <section className="prose-plain hb-mining-guide" aria-labelledby="mining-guide-title">
      <header className="hb-document-header hb-raised">
        <p className="hb-eyebrow">Hyburn / Mine</p>
        <h1 id="mining-guide-title">Mining guide</h1>
        <p>Your first mining session, step by step.</p>
      </header>
      <p>Run an open-source miner to burn HYPE and claim HYBURN on HyperEVM. This website does not connect to your wallet. Your chosen engine signs locally.</p>
      <p>Start with Python below. You do not need the other engines, Foundry, a contract deployment or a website build. Prefer a guide beside your terminal? Open the <a href={`${CONFIG.repo}/blob/main/cli/GETTING_STARTED.md`} target="_blank" rel="noopener noreferrer">beginner walkthrough</a>.</p>
      <Panel title="Before you start">
        <ul className="mb-0">
          <li>Use a dedicated wallet funded for your intended burns, transaction gas and the protected reserve. Burned HYPE does not come back.</li>
          <li>Opening the miner shows a start choice. Press S to start or Q to exit. Previously submitted transactions can still confirm after you stop.</li>
          <li>Each burn specifies its round. A late transaction reverts the burn but still spends gas.</li>
        </ul>
      </Panel>
      <h2>1. Prepare your terminal</h2>
      <p>Use Terminal on macOS, a Linux terminal, or a Windows WSL terminal. These commands are not for native PowerShell. Copy one line at a time and press Enter.</p>
      <pre><code>{`git --version\npython3 --version\npython3 -m pip --version`}</code></pre>
      <p>You need Git and Python 3.10+ with pip/venv. If a command is missing, use the official <a href="https://git-scm.com/downloads/" target="_blank" rel="noopener noreferrer">Git</a>, <a href="https://www.python.org/downloads/" target="_blank" rel="noopener noreferrer">Python</a> or <a href="https://learn.microsoft.com/en-us/windows/wsl/install" target="_blank" rel="noopener noreferrer">WSL</a> installation guide, then reopen your terminal. Windows users need Git and Python inside WSL.</p>
      <h2>2. Download the miner</h2>
      <p>Source: <a href={CONFIG.repo} target="_blank" rel="noopener noreferrer">{CONFIG.repo}</a>.</p>
      <pre><code>{`git clone ${CONFIG.repo}.git\ncd hyburn`}</code></pre>
      <p>Already downloaded it? Enter your existing hyburn folder instead. Keep all following commands in this folder, which contains README.md and cli/.</p>
      <h2>3. Set up a dedicated wallet</h2>
      <pre><code>./cli/hyburn setup</code></pre>
      <p>The launcher prepares its packages automatically. Wallet setup then runs offline: import a private key with hidden input, or choose an encrypted Ethereum JSON keystore. The shared connection profile stores the keystore path, not its password or private key. Never pass a private key as a command-line argument.</p>
      <ol>
        <li>At <code>Keystore path</code>, enter an existing Ethereum JSON keystore path, or press Enter to import your dedicated account&apos;s private key.</li>
        <li>Use your wallet&apos;s own interface to export that account&apos;s key. Do not enter a seed phrase. Hidden input shows no characters or dots; type or paste, then press Enter.</li>
        <li>For a new keystore, choose a password of at least 12 characters and repeat it. This encrypts the local file; it need not match your browser-wallet password.</li>
        <li>Check the printed address against your wallet. Back up the encrypted file and password separately. Setup does not send funds or overwrite existing settings.</li>
      </ol>
      <p>There is no browser-wallet popup. An address alone cannot sign, and hardware-wallet signing is not supported. Never enter a private key on this website or send it in a support message.</p>
      <h2>4. Fund and check</h2>
      <p>Fund the verified address with <strong>native HYPE on HyperEVM (chain 999)</strong>. HYPE held only on HyperCore, WHYPE and HYBURN cannot pay native gas here.</p>
      <Panel title="Example funding requirements">
        <p>Two burns × 0.000999 HYPE = <strong>0.001998 HYPE burn budget</strong>.</p>
        <p className="mb-0">Add variable transaction gas and the default <strong>0.001 HYPE protected reserve</strong>. Funding only the burn budget is not enough. The miner checks affordability before sending; gas is not a fixed amount.</p>
      </Panel>
      <p>For a read-only balance check without unlocking, copy the <code>status --account</code> command printed by setup; it already includes your public address.</p>
      <h3>Optional simulation — no transaction sent</h3>
      <pre><code>./cli/hyburn burn 0.000999 --dry-run</code></pre>
      <p>Enter the keystore password when asked. Simulation needs enough HYPE for the estimated transaction. Keep <code>--dry-run</code>: removing it sends a real burn. A successful simulation does not reserve a reward or guarantee inclusion.</p>
      <h2>5. Start mining — spends real HYPE</h2>
      <pre><code>./cli/hyburn mine --amount 0.000999 --budget 0.001998</code></pre>
      <p>This example authorizes at most two minimum burns, plus gas. Read the requested settings, then press <strong>S</strong> to continue or <strong>Q</strong> to cancel. In a small/plain terminal, enter y at <code>[y/N]</code> to continue; Enter alone cancels. Unlock your keystore when prompted.</p>
      <p>The first burn normally waits until 30 seconds before the round ends. A countdown near 999 seconds is normal. It is a local estimate; LIVE means execution mode, not a confirmed transaction. Keep the terminal open and computer awake.</p>
      <p>On reaching the saved limit, the miner waits for its final round to end and automatically claims its remaining rewards. Let that finish. If HYBURN is not visible in your wallet, use the official Token CA on tab 6 to import it; the Miner address is different.</p>
      <h2>6. Stop and resume</h2>
      <p>Press Ctrl-C to stop. Previously submitted transactions can still confirm. In a new terminal, enter the same project folder, then run:</p>
      <pre><code>{`./cli/hyburn mine`}</code></pre>
      <p>A restart resumes the same budget; it does not reset spending. Depositing more HYPE does not increase that budget. To authorize a new budget, use <code>mine --new-session</code> with your full intended settings. Run one engine at a time for a wallet.</p>
      <h2>Optional: choose another engine</h2>
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
              <p>This example authorizes at most two minimum burns, with gas additional. Press S to start. To switch engines, stop the previous process first. Resume with the command below.</p>
              <pre><code>{`./cli/hyburn --engine ${language.engine} mine`}</code></pre>
            </div>
          </details>
        ))}
      </div>
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
      <p>For screenshots, turn on Privacy with v. Public round information and aggregate statistics stay visible; personal wallet rows, ranks, shares, history, filters, amounts and raw logs are hidden. Crop to the TUI: window titles, previous shell output and plain logs are not protected. Small participant counts can still allow inference from public chain data.</p>
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
      <pre><code>{`git pull --ff-only\n./cli/hyburn mine`}</code></pre>
      <p>If Git reports conflicts or local changes, inspect them before continuing; do not blindly reset or delete wallet files. Setup is not needed again.</p>
      <p>Read your participation history:</p>
      <pre><code>./cli/hyburn history</code></pre>
      <p>Manually claim finished rewards (sends transactions and costs gas):</p>
      <pre><code>./cli/hyburn claim</code></pre>
      <p>There is no claim deadline. You can also call <code>burn(expectedRoundId)</code> or <code>claimMany(roundIds, account)</code> directly on the Miner contract. Claims always pay the named account.</p>
      <h2>If something goes wrong</h2>
      <table>
        <thead><tr><th>Situation</th><th>Next step</th></tr></thead>
        <tbody>
          <tr><td>Command not found</td><td>Check Git/Python installation and enter the downloaded hyburn folder.</td></tr>
          <tr><td>Cannot unlock keystore</td><td>Check the file and its password. Do not delete the keystore or share the key.</td></tr>
          <tr><td>Insufficient balance</td><td>Check native HYPE on HyperEVM, including gas and the protected reserve.</td></tr>
          <tr><td>RPC retry or connection failure</td><td>Wait for retries. If the process stops, resume with the same command; do not reset the budget.</td></tr>
          <tr><td>Wallet already in use</td><td>Stop the other miner using that wallet.</td></tr>
          <tr><td>Budget reached</td><td>Normal completion. Wait for the final reward claim; restarting does not grant a new budget.</td></tr>
        </tbody>
      </table>
    </section>
  );
}
