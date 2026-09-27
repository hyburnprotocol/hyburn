import { Panel } from "@/components/Panel";
import { CONFIG } from "@/lib/config";

export const metadata = { title: "Mine · Hyburn" };

export default function MinePage() {
  return (
    <section className="prose-plain hb-mining-guide" aria-labelledby="mining-guide-title">
      <header className="hb-document-header hb-raised">
        <p className="hb-eyebrow">Hyburn / Mine</p>
        <h1 id="mining-guide-title">Mining guide</h1>
        <p>Choose one implementation. The same protocol, in four languages.</p>
      </header>
      <p>Run a command-line miner to burn HYPE and claim HYBURN. Rewards become claimable when a round ends, with no claim deadline. Anyone can submit a claim for you; the tokens always go to your address. This website does not connect to your wallet.</p>

      <Panel title="Before you start">
        <ul className="mb-0">
          <li>Use a dedicated wallet that holds only the HYPE you intend to burn plus a little for gas. Never your main wallet.</li>
          <li>Burned HYPE does not come back. The miner will not ask twice.</li>
          <li>Every burn names the round it is for. If a transaction lands late, the contract rejects it and your HYPE is returned.</li>
        </ul>
      </Panel>

      <h2>1. Get the source</h2>
      <p>Download or clone the repository, then open a terminal in its root folder. You need Git to clone it. Review the miner source before using a key.</p>
      <p>Source: {CONFIG.repo ? <a href={CONFIG.repo} target="_blank" rel="noopener noreferrer">{CONFIG.repo}</a> : <span>repository link to be published</span>}.</p>
      <p>The commands below use Bash or Zsh on macOS/Linux, or Bash inside WSL on Windows. Choose just one language; each implementation supports the same commands.</p>

      <h2>2. Install one miner</h2>
      <p>Each block starts from the repository root. Keep that terminal in the chosen language folder for the remaining steps. The alias makes <code>hyburn</code> work in that shell; it is not a system-wide installation.</p>
      <div className="hb-language-guides">
        {[
          { name: "Python", note: "Reference implementation", needs: "Python 3.10+ with pip and venv support.", command: "cd cli/python\npython3 -m venv .venv\n.venv/bin/python -m pip install -r requirements.txt\nalias hyburn='.venv/bin/python hyburn.py'", run: ".venv/bin/python hyburn.py" },
          { name: "Node.js", note: "JavaScript implementation", needs: "Node.js 22 with npm.", command: "cd cli/node\nnpm ci\nalias hyburn='node hyburn.mjs'", run: "node hyburn.mjs" },
          { name: "Go", note: "Compiled binary", needs: "Go 1.24+; go build downloads the module dependencies.", command: "cd cli/go\ngo build -o hyburn .\nalias hyburn='./hyburn'", run: "./hyburn" },
          { name: "Rust", note: "Compiled binary", needs: "An up-to-date Rust toolchain with Cargo and a system linker. Cargo downloads and compiles the dependencies.", command: "cd cli/rust\ncargo build --release --locked\nalias hyburn='./target/release/hyburn'", run: "./target/release/hyburn" },
        ].map((language) => (
          <details key={language.name} className="hb-language hb-raised">
            <summary><strong>{language.name}</strong><span>{language.note}</span></summary>
            <div className="hb-language-body">
              <p><strong>Requires:</strong> {language.needs}</p>
              <pre><code>{language.command}</code></pre>
              <p>Without the alias, replace <code>hyburn</code> in every example with <code>{language.run}</code>. Repeat the alias command after opening a new terminal, from this same folder.</p>
            </div>
          </details>
        ))}
      </div>

      <h2>3. Set the deployment</h2>
      <p>Use the published Miner address and deployment block from the official deployment record. Replace the placeholders before running these commands.</p>
      <pre>{`export HYBURN_MINER=${CONFIG.miner || "<miner address>"}
export HYBURN_DEPLOY_BLOCK=${CONFIG.deployBlock || "<deployment block>"}
`}</pre>
      <p>The miner never takes a private key as a command-line argument. <code>HYBURN_RPC</code> defaults to <code>{CONFIG.rpc}</code>.</p>

      <p>Check the deployment without loading a key:</p>
      <pre><code>hyburn status</code></pre>
      <p>Before genesis, this reports that mining has not started. A connection or address error must be resolved before continuing.</p>

      <h2>4. Load your mining wallet</h2>
      <p>Use an existing encrypted Ethereum JSON keystore exported from your wallet. The miner reads this file and prompts for its password; it does not create the file.</p>
      <pre><code>{`export HYBURN_KEYSTORE="$HOME/.hyburn/miner.json"`}</code></pre>
      <p>Alternatively, unattended setups support <code>HYBURN_PRIVATE_KEY</code>. Use one key source. If both are set, the keystore takes precedence.</p>

      <h2>5. Check, then mine</h2>
      <p>After genesis, estimate one minimum-size burn without sending it. This still requires your key and enough HYPE for the burn plus estimated gas.</p>
      <pre><code>hyburn burn 0.000999 --dry-run</code></pre>
      <p>When ready, this example makes at most two burns of 0.000999 HYPE, plus gas. It waits until 30 seconds before each round ends.</p>
      <pre><code>{`hyburn mine --amount 0.000999 --at 30 --budget 0.001998 --rounds 2`}</code></pre>
      <p>After the final round ends, claim any remaining reward and inspect your history:</p>
      <pre><code>{`hyburn claim\nhyburn history`}</code></pre>
      <p><code>--budget</code> counts HYPE burned during this run, excludes gas, and resets when the process restarts. Keep extra HYPE available for transaction fees.</p>

      <h2>Commands</h2>
      <table>
        <thead><tr><th>Command</th><th>What it does</th></tr></thead>
        <tbody>
          <tr><td><code>status</code></td><td>Current round and time left, HYPE burned so far, HYBURN per HYPE right now, your position and unclaimed HYBURN.</td></tr>
          <tr><td><code>burn &lt;hype&gt;</code></td><td>Burn once into the current round. Claims your finished rounds in the same transaction.</td></tr>
          <tr><td><code>mine</code></td><td>Run continuously: burn every round according to the options below, claim as you go. Ctrl-C stops after the current transaction.</td></tr>
          <tr><td><code>claim</code></td><td>Claim every finished round you took part in.</td></tr>
          <tr><td><code>history</code></td><td>Your rounds: burned, round total, share, HYBURN, claimed or not.</td></tr>
        </tbody>
      </table>

      <h2>Options for <code>mine</code></h2>
      <table>
        <thead><tr><th>Option</th><th>Meaning</th></tr></thead>
        <tbody>
          <tr><td><code>--amount &lt;hype&gt;</code></td><td>HYPE to burn per round. Required.</td></tr>
          <tr><td><code>--max-cost &lt;hype&gt;</code></td><td>Only burn if the round&apos;s HYPE per HYBURN, counting your own burn, is at or below this at the moment of sending; skip the round otherwise. This is a condition, not a guarantee: burns by others after yours in the same round lower everyone&apos;s payout, so the final cost can be higher.</td></tr>
          <tr><td><code>--at &lt;seconds&gt;</code></td><td>Send this many seconds before the round ends. Default 30. Sending in the final second exposes you to the last-block risk described in the whitepaper.</td></tr>
          <tr><td><code>--budget &lt;hype&gt;</code></td><td>Stop after this much HYPE has been burned in total.</td></tr>
          <tr><td><code>--rounds &lt;n&gt;</code></td><td>Stop after this many burns.</td></tr>
          <tr><td><code>--dry-run</code></td><td>Estimate and print what would be sent; send nothing.</td></tr>
        </tbody>
      </table>

      <h2>Without a miner</h2>
      <p>Both actions are plain contract calls from any explorer&apos;s write tab: <code>burn(expectedRoundId)</code> with the HYPE as value, and <code>claimMany(roundIds, account)</code>. <code>currentRoundId()</code> tells you the round to name.</p>
    </section>
  );
}
