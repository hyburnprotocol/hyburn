import Link from "next/link";
import { CONFIG } from "@/lib/config";

function genesisDate(value: string) {
  if (!/^\d+$/.test(value)) return null;
  const date = new Date(Number(value) * 1000);
  return Number.isFinite(date.getTime()) ? date.toISOString() : null;
}

export function ProtocolIntro() {
  const genesis = genesisDate(CONFIG.genesis);
  const addresses = [
    ["Miner", CONFIG.miner],
    ["HYBURN token", CONFIG.token],
    ["Burn vault", CONFIG.vault],
  ];

  return (
    <div className="hb-intro">
      <section className="hb-raised hb-protocol-window" aria-labelledby="protocol-title">
        <div className="hb-window-title">
          <span>Hyburn</span>
          <span className="hb-num">{CONFIG.chainName} · {CONFIG.chainId}</span>
        </div>
        <div className="hb-hero">
          <div>
            <p className="hb-eyebrow">Burn-to-mint mining</p>
            <h1 id="protocol-title">Burn HYPE.<br />Mine HYBURN.</h1>
            <p className="hb-lead">Every 999 seconds, share a round&apos;s HYBURN in proportion to the HYPE you burn.</p>
            <p className="hb-hero-detail">HYPE goes to a vault with no withdrawal function. After the round ends, claim your share of its scheduled reward.</p>
            <div className="hb-actions">
              <Link className="hb-raised hb-action" href="/mine/">Get a miner →</Link>
              <Link className="hb-raised hb-action" href="/whitepaper/">Read the whitepaper</Link>
            </div>
            <p className="hb-principles">No premine. No team allocation. No admin.</p>
          </div>
          <aside className="hb-sunken hb-reward" aria-label="Initial round reward">
            <p className="hb-eyebrow">Initial reward per non-empty round</p>
            <div className="hb-reward-number hb-num">5,781.25</div>
            <p className="hb-reward-unit">HYBURN</p>
            <hr />
            <dl>
              <div><dt>Round duration</dt><dd className="hb-num">999 seconds</dd></div>
              <div><dt>Minimum per burn</dt><dd className="hb-num">0.000999 HYPE</dd></div>
              <div><dt>Halving interval</dt><dd className="hb-num">86,400<br /><span>non-empty rounds</span></dd></div>
            </dl>
            <p className="hb-small">Empty rounds issue nothing and do not advance the reward schedule.</p>
          </aside>
        </div>
        <div className="hb-window-status">
          <span>Supply cap: <strong className="hb-num">999,000,000 HYBURN</strong></span>
          <span>No upgrades · No pause function</span>
        </div>
      </section>

      <section className="hb-share-section" aria-labelledby="share-title">
        <div>
          <p className="hb-eyebrow">How your share is calculated</p>
          <h2 id="share-title">Your burn / total burn.</h2>
          <p>Your reward is the round reward multiplied by your share of all HYPE burned in that round.</p>
          <p className="hb-small">The final total is known when the round ends. Later burns can lower your share. Payouts round down to 0.000000001 HYBURN; rounding dust is never minted.</p>
        </div>
        <figure className="hb-sunken hb-example">
          <figcaption>Example · one initial-reward round</figcaption>
          <div className="hb-share-bar" aria-label="You burn 1 HYPE, 25 percent. Others burn 3 HYPE, 75 percent.">
            <span>You · 25%</span><span>Others · 75%</span>
          </div>
          <dl>
            <div><dt>Your burn / final total</dt><dd className="hb-num">1 / 4 HYPE</dd></div>
            <div><dt>Your share</dt><dd className="hb-num">25%</dd></div>
            <div className="hb-example-result"><dt>You can claim</dt><dd className="hb-num">1,445.3125 HYBURN</dd></div>
          </dl>
        </figure>
      </section>

      <section className="hb-deployment" aria-labelledby="source-title">
        <div className="hb-section-heading">
          <h2 id="source-title">Open source. Verifiable rules.</h2>
          <span className="hb-small">MIT licensed</span>
        </div>
        <div className="hb-sunken p-4 space-y-3">
          <p>Read the contracts, run the tests, or use a miner in Python, Node.js, Go or Rust. Hyburn&apos;s original source is available under the MIT License.</p>
          <p className="hb-small">The repository includes contract tests, shared miner regression scenarios and instructions for comparing deployed Miner bytecode with a local build. Open source does not mean independently audited.</p>
          <div className="hb-actions">
            <a className="hb-raised hb-action" href={CONFIG.repo} target="_blank" rel="noopener noreferrer">View source →</a>
            <a className="hb-raised hb-action" href={`${CONFIG.repo}/blob/HEAD/LICENSE`} target="_blank" rel="noopener noreferrer">MIT License</a>
          </div>
        </div>
      </section>

      <section className="hb-deployment" aria-labelledby="deployment-title">
        <div className="hb-section-heading">
          <h2 id="deployment-title">Deployment record</h2>
          <span className="hb-small">Published details · no live chain connection</span>
        </div>
        <div className="hb-sunken hb-deployment-body">
          <div className="hb-genesis">
            <h3>Mining begins</h3>
            {genesis ? <time className="hb-num" dateTime={genesis}>{genesis.replace("T", " ").replace(".000Z", " UTC")}</time> : <p>Genesis timestamp not yet published.</p>}
            <p className="hb-small">Mining starts 999 seconds (16 minutes, 39 seconds) after deployment.</p>
          </div>
          <dl className="hb-addresses">
            {addresses.map(([label, address]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{address ? <a className="hb-num" href={`${CONFIG.explorer}/address/${address}`} target="_blank" rel="noopener noreferrer">{address}</a> : <span className="hb-small">Not yet published</span>}</dd>
              </div>
            ))}
            {CONFIG.deployTx && <div><dt>Deployment transaction</dt><dd><a className="hb-num" href={`${CONFIG.explorer}/tx/${CONFIG.deployTx}`} target="_blank" rel="noopener noreferrer">{CONFIG.deployTx}</a></dd></div>}
          </dl>
        </div>
      </section>
    </div>
  );
}
