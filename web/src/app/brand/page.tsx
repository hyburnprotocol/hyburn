import type { Metadata } from "next";
import Image from "next/image";
import { CONFIG } from "@/lib/config";

export const metadata: Metadata = {
  title: "Brand kit · Hyburn",
  description: "Official Hyburn logos, banner, project description and links for listings and community use.",
  alternates: { canonical: "/brand/" },
};

const description = "Hyburn is an open-source proof-of-burn mining protocol on HyperEVM. Burn HYPE in 999-second rounds for proportional HYBURN rewards. Issuance follows a fixed halving schedule, capped at 999,000,000 HYBURN. No premine, team allocation or admin.";

export default function BrandPage() {
  return (
    <article className="prose-plain hb-document">
      <header className="hb-document-header hb-raised">
        <p className="hb-eyebrow">Hyburn / Brand kit</p>
        <h1>Same identity. Everywhere.</h1>
        <p>Official assets for token listings, wallets, community posts and project coverage.</p>
      </header>

      <section aria-labelledby="assets">
        <h2 id="assets">Logo &amp; banner</h2>
        <p>Use the same black HY/BURN mark on white as our X profile and DEX Screener listing. Keep its proportions, clear space and both lines of lettering.</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <figure className="hb-sunken p-4">
            <div className="bg-white flex justify-center">
              <Image src="/brand/hyburn-logo.png" alt="Black HY over BURN logo on white" width={1254} height={1254} className="w-48 h-48 object-contain" />
            </div>
            <figcaption className="mt-4 font-semibold">Profile &amp; token logo</figcaption>
            <p className="hb-small">Original PNG · 1254 × 1254</p>
            <a href="/brand/hyburn-logo.png" download>Download logo PNG</a>
          </figure>
          <figure className="hb-sunken p-4">
            <div className="bg-white h-48 flex items-center justify-center gap-6">
              <Image src="/brand/hyburn-icon-32.svg" alt="HY/BURN explorer icon, enlarged preview" width={96} height={96} unoptimized />
              <Image src="/brand/hyburn-icon-32.svg" alt="HY/BURN explorer icon at its native 32 pixel size" width={32} height={32} unoptimized />
            </div>
            <figcaption className="mt-4 font-semibold">Explorer icon</figcaption>
            <p className="hb-small">SVG · 32 × 32 · enlarged and actual-size previews</p>
            <a href="/brand/hyburn-icon-32.svg" download>Download icon SVG</a>
          </figure>
          <figure className="hb-sunken p-4 sm:col-span-2">
            <Image src="/brand/hyburn-banner.png" alt="HYBURN — Burn HYPE. Mine HYBURN. 999-second rounds on HyperEVM." width={2172} height={724} className="w-full h-auto" />
            <figcaption className="mt-4 font-semibold">Social banner</figcaption>
            <p className="hb-small">Original PNG · 2172 × 724 · 3:1</p>
            <a href="/brand/hyburn-banner.png" download>Download banner PNG</a>
          </figure>
        </div>
        <p className="mt-4">For listing forms that require a direct SVG URL:</p>
        <p className="hb-num"><a href="https://hyburn.xyz/brand/hyburn-icon-32.svg">https://hyburn.xyz/brand/hyburn-icon-32.svg</a></p>
      </section>

      <section aria-labelledby="description">
        <h2 id="description">Project description</h2>
        <p>Use this description for explorer and directory listings ({description.length} characters).</p>
        <blockquote className="hb-sunken p-4 leading-relaxed">{description}</blockquote>
        <p className="mt-4"><strong>Tagline:</strong> Burn HYPE. Mine HYBURN.</p>
        <p><strong>Name:</strong> Hyburn &nbsp;·&nbsp; <strong>Token symbol:</strong> HYBURN &nbsp;·&nbsp; <strong>Network:</strong> HyperEVM (999)</p>
      </section>

      <section aria-labelledby="official-links">
        <h2 id="official-links">Official links</h2>
        {CONFIG.token && <p><strong>Token contract:</strong><br /><a className="hb-num" href={`${CONFIG.explorer}/token/${CONFIG.token}`}>{CONFIG.token}</a></p>}
        <ul>
          <li><a href="https://hyburn.xyz/">Website</a></li>
          <li><a href="https://x.com/hyburnprotocol">X · @hyburnprotocol</a></li>
          <li><a href={CONFIG.repo}>GitHub · hyburnprotocol/hyburn</a></li>
          <li><a href="https://dexscreener.com/hyperevm/0x561ff10f136da03be56f31a53cd8d87f93694106">DEX Screener · HYBURN / WHYPE</a></li>
          <li><a href="mailto:gm@hyburn.xyz">Contact · gm@hyburn.xyz</a></li>
        </ul>
        <p className="hb-small">Use these assets to identify Hyburn accurately. Do not distort the logo or imply a partnership or endorsement. A matching name or logo alone does not identify the token; check its contract address.</p>
      </section>
    </article>
  );
}
