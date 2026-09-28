#!/usr/bin/env node

import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { uiEvent, routeUI } from "./tui.mjs";
import { promptPassword } from "./password.mjs";
import { Session, loadProfile } from "./session.mjs";
import { Contract, JsonRpcProvider, Wallet, parseEther, isAddress, getAddress } from "ethers";

const VERSION = "0.3.0";
const DEFAULT_RPC = "https://rpc.hypurrscan.io";
const LOG_CHUNK = 1000;
const ONE_HYPE = 10n ** 18n;
const ONE_TOKEN = 10n ** 9n;

const MINER_ABI = [
  "function currentRoundId() view returns (uint256)",
  "function genesisTimestamp() view returns (uint256)",
  "function ROUND_DURATION() view returns (uint256)",
  "function MIN_BURN() view returns (uint256)",
  "function INITIAL_REWARD() view returns (uint256)",
  "function HALVING_INTERVAL() view returns (uint256)",
  "function TERMINAL_SEQUENCE() view returns (uint256)",
  "function TERMINAL_REMAINDER() view returns (uint256)",
  "function rounds(uint256) view returns (uint64 miningSequence, uint128 totalBurned, bool created)",
  "function previewCurrentRoundReward() view returns (uint256)",
  "function nonEmptyRoundCount() view returns (uint256)",
  "function totalHypeBurned() view returns (uint256)",
  "function burned(uint256,address) view returns (uint128)",
  "function claimed(uint256,address) view returns (bool)",
  "function claimable(uint256,address) view returns (uint256)",
  "function token() view returns (address)",
  "function burn(uint256) payable",
  "function burnAndClaim(uint256,uint256[]) payable",
  "function claimMany(uint256[],address)",
  "event HypeBurned(uint256 indexed roundId, address indexed account, uint256 amount, uint128 roundTotalBurned)",
];
const TOKEN_ABI = ["function balanceOf(address) view returns (uint256)"];

function fmtUnits(x, decimals, places) {
  x = BigInt(x);
  const base = 10n ** BigInt(decimals);
  const whole = x / base, frac = x % base;
  let s = whole.toLocaleString("en-US");
  if (places) s += "." + frac.toString().padStart(decimals, "0").slice(0, places);
  return s;
}
const fmtHype = (w, p = 4) => fmtUnits(w, 18, p);
const fmtToken = (u, p = 3) => fmtUnits(u, 9, p);
function parseHype(s) {
  if (!/^\d*(\.\d*)?$/.test(s) || s === "" || s === ".") die(`not a HYPE amount: ${s}`);
  return parseEther(s);
}
const pad2 = (n) => String(n).padStart(2, "0");
function fmtClock(sec) {
  sec = Math.max(0, Math.floor(sec));
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  if (d) return `${d}d ${pad2(h)}:${pad2(m)}:${pad2(s)}`;
  if (h) return `${h}:${pad2(m)}:${pad2(s)}`;
  return `${pad2(m)}:${pad2(s)}`;
}
const pct = (a, b) => (Number((BigInt(a) * 10000n) / BigInt(b)) / 100).toFixed(2) + "%";
const stamp = () => new Date().toISOString().replace("T", " ").slice(0, 19) + " ";
const log = (m) => console.log(stamp() + m);
function die(m, code = 1) { console.error(m); process.exit(code); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitLocal(seconds, label, stopped) {
  uiEvent({type:"wait",seconds,label});
  log(`${label}; local wait ~${Math.ceil(seconds)}s, no RPC requests`);
  const deadline = performance.now() + Math.max(0, seconds) * 1000;
  const recheck = performance.now() + Math.min(30, Math.max(0, seconds)) * 1000;
  try {
    while (!stopped()) {
      const left = deadline - performance.now();
      if (left <= 0 || performance.now() >= recheck) break;
      if (process.stderr.isTTY) process.stderr.write(`\r\x1b[2K${label} | ~${fmtClock(left / 1000)} | Ctrl-C to stop`);
      await sleep(Math.min(500, left));
    }
  } finally {
    if (process.stderr.isTTY) process.stderr.write("\r\x1b[2K");
  }
}

class Hyburn {
  constructor(rpc, miner, chainId, deployBlock) {
    this.rpc = rpc; this.minerAddr = miner; this.chainIdOpt = chainId; this.deployBlock = deployBlock;
    this.account = null; this.offset = 0;
  }
  async init() {
    if (!isAddress(this.minerAddr)) die("HYBURN_MINER is not set to a valid address");
    this.provider = new JsonRpcProvider(this.rpc, this.chainIdOpt || undefined, this.chainIdOpt ? { staticNetwork: true } : {});
    try { this.chainId = Number((await this.provider.getNetwork()).chainId); } catch (e) { die(`cannot reach RPC ${this.rpc}`); }
    this.provider.pollingInterval = 5000;
    const actualChain = Number(await this.provider.send("eth_chainId", []));
    if (this.chainIdOpt && actualChain !== this.chainIdOpt) die(`RPC chain ID mismatch: expected ${this.chainIdOpt}, got ${actualChain}`);
    this.chainId = actualChain;
    this.miner = new Contract(getAddress(this.minerAddr), MINER_ABI, this.provider);
    const m = this.miner;
    [this.genesis, this.dur, this.minBurn, this.initReward, this.halving, this.terminal, this.remainder] = (await Promise.all([
      m.genesisTimestamp(), m.ROUND_DURATION(), m.MIN_BURN(), m.INITIAL_REWARD(), m.HALVING_INTERVAL(), m.TERMINAL_SEQUENCE(), m.TERMINAL_REMAINDER(),
    ])).map(Number.isSafeInteger ? (x) => BigInt(x) : (x) => x);
    this.token = new Contract(await m.token(), TOKEN_ABI, this.provider);
    await this.syncTime();
  }
  async syncTime() {
    const b = await this.provider.getBlock("latest");
    this.offset = Number(b.timestamp) - Date.now() / 1000;
    this.latestBlock = b.number;
    uiEvent({type:"clock",timestamp:b.timestamp,block:b.number,genesis:Number(this.genesis),duration:Number(this.dur)});
  }
  now() { return Date.now() / 1000 + this.offset; }
  roundOf(t) { const g = Number(this.genesis), d = Number(this.dur); return t >= g ? Math.floor((t - g) / d) : -1; }
  roundEnd(rid) { return Number(this.genesis) + (rid + 1) * Number(this.dur); }
  rewardForSeq(seq) {
    seq = BigInt(seq);
    if (seq >= this.terminal) return 0n;
    let r = this.initReward >> (seq / this.halving);
    if (seq === this.terminal - 1n) r += this.remainder;
    return r;
  }
  async loadKey() {
    if (this.account) return;
    const ks = process.env.HYBURN_KEYSTORE, pk = process.env.HYBURN_PRIVATE_KEY;
    let wallet;
    if (ks) {
      try {
        const pw = process.env.HYBURN_KEYSTORE_PASSWORD ?? (await promptPassword("keystore password: "));
        wallet = await Wallet.fromEncryptedJson(readFileSync(ks, "utf8"), pw);
      } catch { die("Cannot unlock keystore; check the file, password and interactive terminal."); }
    } else if (pk) {
      try { wallet = new Wallet(pk); } catch { die("Invalid private key; use a 32-byte hex key, not a seed phrase."); }
    }
    else die("no key: set HYBURN_KEYSTORE (encrypted JSON) or HYBURN_PRIVATE_KEY");
    this.account = wallet.connect(this.provider);
  }
  cachePath(account) {
    const d = process.env.HYBURN_HOME || join(homedir(), ".hyburn");
    mkdirSync(d, { recursive: true });
    return join(d, `${this.chainId}-${this.minerAddr.toLowerCase()}-${account.toLowerCase()}.json`);
  }

  cache(account) {
    this._caches ??= new Map();
    const key = account.toLowerCase();
    if (!this._caches.has(key)) {
      const p = this.cachePath(account);
      let c = null;
      try { c = existsSync(p) ? JSON.parse(readFileSync(p, "utf8")) : null; } catch { c = null; }
      if (!c || c.v !== 3) c = { v: 3, scannedTo: this.deployBlock - 1, rounds: {} };
      this._caches.set(key, c);
    }
    return this._caches.get(key);
  }
  save(account) { writeFileSync(this.cachePath(account), JSON.stringify(this.cache(account))); }
  async myRounds(account) {
    const c = this.cache(account);
    const latest = await this.provider.getBlockNumber();
    for (let a = c.scannedTo + 1; a <= latest; a += LOG_CHUNK) {
      const b = Math.min(a + LOG_CHUNK - 1, latest);
      const logs = await this.miner.queryFilter(this.miner.filters.HypeBurned(null, getAddress(account)), a, b);
      for (const l of logs) { const k = l.args.roundId.toString(); if (!(k in c.rounds)) c.rounds[k] = null; }
    }
    c.scannedTo = latest;
    this.save(account);
    return Object.keys(c.rounds).map(Number).sort((x, y) => x - y);
  }
  async roundRows(account, ids) {
    const c = this.cache(account);

    const block = await this.provider.getBlock("latest");
    const t = block.timestamp;
    const snapshot = { blockTag: block.number };
    const rows = [];
    for (const rid of ids) {
      const e = c.rounds[String(rid)];
      const ended = t >= this.roundEnd(rid);
      let b, total, seq, cl;
      if (e && e.claimed) { b = BigInt(e.burned); total = BigInt(e.total); seq = e.seq; cl = true; }
      else if (e && ended && e.total !== undefined) { b = BigInt(e.burned); total = BigInt(e.total); seq = e.seq; cl = await this.miner.claimed(rid, account, snapshot); e.claimed = cl; }
      else {
        const [r, bb, cc] = await Promise.all([this.miner.rounds(rid, snapshot), this.miner.burned(rid, account, snapshot), this.miner.claimed(rid, account, snapshot)]);
        b = bb; total = r.totalBurned; seq = Number(r.miningSequence); cl = cc;
        if (ended) c.rounds[String(rid)] = { burned: b.toString(), total: total.toString(), seq, claimed: cl };
      }
      const reward = this.rewardForSeq(seq);
      rows.push({ round: rid, seq, burned: b, total, reward, payout: total ? (reward * b) / total : 0n, claimed: cl, ended });
    }
    this.save(account);
    return rows;
  }
  markClaimed(account, ids) {
    const c = this.cache(account);
    for (const rid of ids) { const e = c.rounds[String(rid)]; if (e) e.claimed = true; }
    this.save(account);
  }
  async claimableIds(account) {
    const rows = await this.roundRows(account, await this.myRounds(account));
    return rows.filter((r) => r.ended && !r.claimed && r.burned > 0n).map((r) => r.round);
  }
  async openSession() {
    if (!this.session) { this.session = await Session.open(this.chainId, this.minerAddr, this.account.address); await this.session.recover(this.provider); }
    return this.session;
  }
  async send(fnName, args, value, dryRun) {
    uiEvent({type:"busy",value:true});
    try { return await this.sendInner(fnName,args,value,dryRun); }
    finally { uiEvent({type:"busy",value:false}); }
  }
  async sendInner(fnName, args, value, dryRun) {
    const c = this.miner.connect(this.account);
    const from = this.account.address;
    if (!dryRun) {
      await this.openSession();
      if (await this.provider.getTransactionCount(from, 'pending') !== await this.provider.getTransactionCount(from, 'latest')) throw new Error('Wallet has another pending transaction; wait for it before continuing.');
    }
    let gas;
    try { gas = await c[fnName].estimateGas(...args, { value }); }
    catch (e) { die(`would revert: ${e.reason || e.shortMessage || e.message}`); }
    gas = (gas * 12n) / 10n;
    const fee = await this.provider.getFeeData();
    const maxFee = fee.maxFeePerGas ?? fee.gasPrice, tip = fee.maxPriorityFeePerGas ?? 1n;
    const cost = value + gas * maxFee + (value ? (this.reserve ?? 0n) : 0n);
    const bal = await this.provider.getBalance(from);
    if (bal < cost) die(`balance ${fmtHype(bal)} HYPE < needed ${fmtHype(cost)} HYPE (value + max gas)`);
    if (dryRun) { log(`dry run: would send ${fnName} value=${fmtHype(value)} HYPE gas=${gas} maxFee=${maxFee}`); return null; }
    const request = await c[fnName].populateTransaction(...args, { value, gasLimit: gas, maxFeePerGas: maxFee, maxPriorityFeePerGas: tip });
    Object.assign(request, {chainId:this.chainId, nonce:await this.provider.getTransactionCount(from, 'latest'), type:2});
    if (this.shouldStop?.()) throw new Error("Stopped before signing; session preserved.");
    if (value && this.finishRequested?.()) { log("Finishing: new burn cancelled before signing."); return null; }
    const raw = await this.account.signTransaction(request);
    this.session.prepare(raw, value, value ? Number(args[0]) : -1, this.mining ?? false);
    const tx = await this.provider.broadcastTransaction(raw);
    log(`sent ${tx.hash.slice(2)}`);
    const rc = await this.provider.waitForTransaction(tx.hash, 1, 180000);
    if (!rc) throw new Error("Transaction still pending; restart to recover it.");
    this.session.settle(rc);
    if (rc.status !== 1) die(`transaction reverted: ${tx.hash}`);
    return rc;
  }
}

async function cmdStatus(hb, o) {
  await hb.syncTime();
  const t = hb.now(), rid = hb.roundOf(t);
  console.log(`chain          ${hb.chainId}  block ${hb.latestBlock.toLocaleString("en-US")}`);
  if (rid < 0) {
    console.log(`status         not started; round 0 opens in ${fmtClock(Number(hb.genesis) - t)}`);
    console.log(`first reward   ${fmtToken(hb.rewardForSeq(0n), 2)} HYBURN`);
    return;
  }
  const [r, reward, count, allBurned] = await Promise.all([hb.miner.rounds(rid), hb.miner.previewCurrentRoundReward(), hb.miner.nonEmptyRoundCount(), hb.miner.totalHypeBurned()]);
  const total = r.totalBurned;
  console.log(`round          ${rid.toLocaleString("en-US")}  ends in ${fmtClock(hb.roundEnd(rid) - t)}`);
  console.log(`issued         ${fmtToken(reward, 2)} HYBURN`);
  console.log(`burned so far  ${fmtHype(total)} HYPE`);
  console.log(`per 1 HYPE     ${total === 0n ? "all of it" : fmtToken((reward * ONE_HYPE) / total) + " HYBURN"}`);
  console.log(`min burn       ${fmtHype(hb.minBurn, 6)} HYPE`);
  console.log(`non-empty      ${count.toLocaleString("en-US")} rounds  |  all-time burned ${fmtHype(allBurned, 2)} HYPE`);
  const acct = o.account || hb.account?.address;
  if (acct) {
    const a = getAddress(acct);
    const mine = await hb.miner.burned(rid, a);
    const ids = await hb.claimableIds(a);
    let cl = 0n; for (const id of ids) cl += await hb.miner.claimable(id, a);
    console.log(`account        ${a}`);
    console.log(`  HYPE         ${fmtHype(await hb.provider.getBalance(a))}`);
    console.log(`  HYBURN       ${fmtToken(await hb.token.balanceOf(a))}`);
    console.log(`  this round   ${fmtHype(mine)} HYPE` + (total ? `  (${pct(mine, total)})` : ""));
    console.log(`  claimable    ${fmtToken(cl)} HYBURN in ${ids.length} round(s)`);
  }
}

async function cmdHistory(hb, o) {
  const acct = getAddress(o.account || hb.account?.address || die("history needs --account or a key"));
  const rows = await hb.roundRows(acct, await hb.myRounds(acct));
  if (!rows.length) { console.log("no burns from this account"); return; }
  console.log(`${"round".padStart(10)} ${"seq".padStart(9)} ${"you burned".padStart(16)} ${"round total".padStart(16)} ${"share".padStart(8)} ${"HYBURN".padStart(16)}  status`);
  for (const r of rows.reverse()) {
    const share = r.total ? pct(r.burned, r.total) : "-";
    const status = !r.ended ? "open" : r.claimed ? "claimed" : "claimable";
    console.log(`${r.round.toLocaleString("en-US").padStart(10)} ${r.seq.toLocaleString("en-US").padStart(9)} ${fmtHype(r.burned).padStart(16)} ${fmtHype(r.total).padStart(16)} ${share.padStart(8)} ${fmtToken(r.payout).padStart(16)}  ${status}`);
  }
}

async function cmdClaim(hb, o) {
  await hb.loadKey();
  if (!o.dryRun) await hb.openSession();
  const acct = hb.account.address;
  const ids = await hb.claimableIds(acct);
  if (!ids.length) { console.log("nothing to claim"); return; }
  let total = 0n; for (const id of ids) total += await hb.miner.claimable(id, acct);
  log(`claiming ${fmtToken(total)} HYBURN from ${ids.length} round(s)`);
  for (let i = 0; i < ids.length; i += 200) {
    const batch = ids.slice(i, i + 200);
    if (await hb.send("claimMany", [batch, acct], 0n, o.dryRun)) hb.markClaimed(acct, batch);
  }
  if (!o.dryRun) log(`done. HYBURN balance ${fmtToken(await hb.token.balanceOf(acct))}`);
}

async function doBurn(hb, amount, dryRun, expectedRound=null) {
  if (amount < hb.minBurn) die(`amount below minimum ${fmtHype(hb.minBurn, 6)} HYPE`);
  await hb.syncTime();
  const rid = hb.roundOf(hb.now());
  if (rid < 0) die("not started yet");
  if (expectedRound !== null && rid !== expectedRound) { log("Round changed during preflight; checking the new round before signing."); return false; }
  const ids = await hb.claimableIds(hb.account.address);
  log(`burn ${fmtHype(amount)} HYPE into round ${rid.toLocaleString("en-US")}` + (ids.length ? `, claiming ${ids.length} round(s)` : ""));
  let rc;
  try {
    rc = ids.length ? await hb.send("burnAndClaim", [rid, ids], amount, dryRun) : await hb.send("burn", [rid], amount, dryRun);
  } catch (e) {
    if (/RoundMismatch/.test(String(e))) { log("round changed before the transaction landed; nothing was burned"); return false; }
    throw e;
  }
  if (rc) {
    if (ids.length) hb.markClaimed(hb.account.address, ids);
    const r = await hb.miner.rounds(rid);
    const mine = await hb.miner.burned(rid, hb.account.address);
    log(`confirmed in block ${rc.blockNumber.toLocaleString("en-US")}; round total ${fmtHype(r.totalBurned)} HYPE, your share ${pct(mine, r.totalBurned)}`);
  }
  return true;
}

async function cmdBurn(hb, o) { await hb.loadKey(); await doBurn(hb, parseHype(o.amount), o.dryRun); }

async function cmdMine(hb, o) {
  await hb.loadKey();
  let settings;
  if (!o.dryRun) {
    const session = await hb.openSession();
    const supplied = {};
    for (const [key, arg] of Object.entries({amount:'amount', budget:'budget', max_cost:'maxCost', at:'at', rounds:'rounds', reserve:'reserve'}))
      if (o[arg] !== undefined) supplied[key] = ['amount','budget','max_cost','reserve'].includes(key) ? parseHype(o[arg]).toString() : String(o[arg]);
    settings = session.configure(supplied, o.newSession);
    hb.reserve = BigInt(settings.reserve); hb.mining = true;
    console.log(`Resuming saved session: ${session.state.burns} burns, ${fmtHype(BigInt(session.state.spent),9)} HYPE burned; gas ${fmtHype(BigInt(session.state.gas),9)} HYPE`);
  } else {
    if (!o.amount) throw new Error('--dry-run needs --amount');
    settings = {amount:parseHype(o.amount).toString(), budget:o.budget ? parseHype(o.budget).toString() : '', max_cost:o.maxCost ? parseHype(o.maxCost).toString() : '', at:String(o.at ?? 30), rounds:String(o.rounds ?? '')};
  }
  const amount = BigInt(settings.amount);
  if (amount < hb.minBurn) die(`--amount below minimum ${fmtHype(hb.minBurn, 6)} HYPE`);
  const maxCost = settings.max_cost ? BigInt(settings.max_cost) : null;
  const budget = settings.budget ? BigInt(settings.budget) : null;
  const at = Number(settings.at); o.rounds = Number(settings.rounds);
  if (!Number.isInteger(at) || at <= 0 || at >= Number(hb.dur) || (settings.rounds && (!Number.isInteger(o.rounds) || o.rounds<=0))) throw new Error('--at must be within the round; --rounds must be positive');
  let spent = o.dryRun ? 0n : BigInt(hb.session.state.spent), burns = o.dryRun ? 0 : hb.session.state.burns, stop = false, lastRound = o.dryRun ? -1 : hb.session.state.last_round;
  let finish = o.dryRun ? false : (hb.session.state.finishing ?? false), checkedRound = null;
  hb.finishRequested = () => finish;
  process.on("SIGUSR1", () => { finish = true; });
  hb.shouldStop = () => stop;
  process.on("SIGINT", () => { stop = true; });
  log(`mining as ${hb.account.address}: ${fmtHype(amount)} HYPE per round, send ${at}s before round end`
    + (maxCost !== null ? `, max cost ${fmtHype(maxCost, 6)} HYPE/HYBURN` : "") + (budget !== null ? `, budget ${fmtHype(budget)} HYPE` : "") + (o.dryRun ? ", DRY RUN" : ""));
  uiEvent({type:"meta",chain:hb.chainId,miner:hb.minerAddr,token:hb.token.target,account:hb.account.address,
    genesis:Number(hb.genesis),duration:Number(hb.dur),deploy:hb.deployBlock,at,amount:amount.toString(),
    budget:budget?.toString() ?? '',reserve:(hb.reserve ?? 0n).toString(),dry:o.dryRun});
  const usage=()=>uiEvent({type:"usage",spent:spent.toString(),burns,gas:o.dryRun?'0':hb.session.state.gas});
  log("Automatic claims enabled (gas applies). F in TUI: finish and claim; Ctrl-C: stop immediately.");
  while (!stop && !finish) {
    usage();
    if (budget !== null && spent + amount > budget) { log(`budget reached (${fmtHype(spent)} of ${fmtHype(budget)} HYPE); stopping`); break; }
    if (o.rounds && burns >= o.rounds) { log(`done: ${burns} round(s)`); break; }
    await hb.syncTime();
    const t = hb.now(), rid = hb.roundOf(t);
    if (!o.dryRun && checkedRound !== rid) { await cmdClaim(hb,o); checkedRound = rid; }
    if (rid < 0) { log(`not started; round 0 opens in ${fmtClock(Number(hb.genesis) - t)}`); await waitLocal(Math.max(1, Number(hb.genesis) - t), "Waiting for genesis", () => stop); continue; }
    if (rid === lastRound) { await waitLocal(Math.max(0.5, hb.roundEnd(rid) - t + 1), `Next round ${rid + 1}`, () => stop); continue; }
    const sendAt = hb.roundEnd(rid) - at;
    if (t < sendAt) { await waitLocal(sendAt - t, `Round ${rid}: waiting for send window`, () => stop); continue; }
    lastRound = rid;
    if (!o.dryRun && await hb.miner.burned(rid, hb.account.address) > 0n) { log(`round ${rid}: wallet already burned; skipping duplicate`); continue; }
    const [r, reward] = await Promise.all([hb.miner.rounds(rid), hb.miner.previewCurrentRoundReward()]);
    const cost = reward ? ((r.totalBurned + amount) * ONE_TOKEN) / reward : null;
    if (maxCost !== null && cost !== null && cost > maxCost) { log(`round ${rid.toLocaleString("en-US")}: cost ${fmtHype(cost, 6)} HYPE/HYBURN > max ${fmtHype(maxCost, 6)}; skipping`); continue; }
    if (budget !== null && spent + amount > budget) { log(`budget reached (${fmtHype(spent)} of ${fmtHype(budget)} HYPE); stopping`); break; }
    if (await doBurn(hb, amount, o.dryRun, rid)) {
      if (o.dryRun) { spent += amount; burns++; } else { spent = BigInt(hb.session.state.spent); burns = hb.session.state.burns; }
      if (o.rounds && burns >= o.rounds) { log(`done: ${burns} round(s)`); break; }
    }
  }
  if (!o.dryRun && !stop) {
    hb.session.state.finishing = true; hb.session.save();
    const finalRound = hb.session.state.last_round;
    while (finalRound >= 0 && !stop) {
      await hb.syncTime(); const left=hb.roundEnd(finalRound)-hb.now(); if (left<=0) break;
      await waitLocal(left, 'Finishing; waiting to claim final rewards', () => stop);
    }
    if (!stop) { await cmdClaim(hb,o); hb.session.state.finishing = false; hb.session.save(); }
  }
  usage();
  log(`mining stopped. burned ${fmtHype(spent)} HYPE in ${burns} round(s)`);
}

function parseArgs(argv) {
  const o = { rpc: process.env.HYBURN_RPC || DEFAULT_RPC, miner: process.env.HYBURN_MINER || "", chainId: Number(process.env.HYBURN_CHAIN_ID || 0), deployBlock: Number(process.env.HYBURN_DEPLOY_BLOCK || 0), dryRun: false };
  const pos = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i], next = () => { if (!argv[i+1] || argv[i+1].startsWith("--")) die(`missing value for ${a}`); return argv[++i]; };
    if (a === "--plain") o.plain=true; else if (a === "--yes") o.yes=true;
    else if (a === "--rpc") o.rpc = next(); else if (a === "--miner") o.miner = next(); else if (a === "--chain-id") o.chainId = Number(next());
    else if (a === "--deploy-block") o.deployBlock = Number(next()); else if (a === "--account") o.account = next();
    else if (a === "--amount") o.amount = next(); else if (a === "--max-cost") o.maxCost = next(); else if (a === "--at") o.at = Number(next());
    else if (a === "--new-session") o.newSession = true; else if (a === "--reserve") o.reserve = next();
    else if (a === "--budget") o.budget = next(); else if (a === "--rounds") o.rounds = Number(next()); else if (a === "--dry-run") o.dryRun = true;
    else if (a === "--version") { console.log(VERSION); process.exit(0); }
    else if (a === "-h" || a === "--help") { usage(); process.exit(0); }
    else if (a.startsWith("--")) die(`unknown option ${a}`); else pos.push(a);
  }
  o.cmd = pos[0]; if (o.cmd === "burn") o.amount = pos[1];
  return o;
}
function usage() {
  console.log(`usage: hyburn [--plain] [--yes] [--rpc URL] [--miner ADDR] [--chain-id N] [--deploy-block N] <command>
  status [--account ADDR]
  burn <hype> [--dry-run]
  mine [--amount HYPE] [--max-cost HYPE] [--at SECONDS] [--budget HYPE] [--rounds N]
       [--reserve HYPE] [--new-session] [--dry-run]
       No options: resume saved session. First run: --amount plus --budget or --rounds.
      --max-cost: skip the round if HYPE per HYBURN, counting your burn, is above this at send time
                  (later burns by others in the same round still lower everyone's payout)
  claim [--dry-run]
  history [--account ADDR]`);
}

let activeMiner;
try {
loadProfile();
const o = parseArgs(process.argv.slice(2));
if (!o.cmd) { usage(); process.exit(1); }
if (o.cmd === "burn" && !o.amount) die("burn needs an amount");

await routeUI(o,process.argv.slice(2));
const hb = new Hyburn(o.rpc, o.miner, o.chainId, o.deployBlock);
activeMiner=hb;
await hb.init();
if ((o.cmd === "status" || o.cmd === "history") && !o.account && (process.env.HYBURN_KEYSTORE || process.env.HYBURN_PRIVATE_KEY)) await hb.loadKey();
const cmds = { status: cmdStatus, burn: cmdBurn, mine: cmdMine, claim: cmdClaim, history: cmdHistory };
if (!cmds[o.cmd]) { usage(); process.exit(1); }
await cmds[o.cmd](hb, o);

} catch (error) {
  console.error(`Stopped: ${(error.shortMessage || error.message || 'RPC/local operation failed').split('\n')[0].slice(0,240)}`);
  console.error('Existing session kept; restore RPC/file access and restart to recover.');
  process.exitCode=1;
} finally {
  activeMiner?.provider?.destroy();
  activeMiner?.session?.lock.close();
}
