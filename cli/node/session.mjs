import { readFileSync, existsSync, mkdirSync, openSync, writeFileSync, fsyncSync, closeSync, renameSync, unlinkSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, dirname } from 'node:path';
import { randomUUID } from 'node:crypto';
import { createServer } from 'node:net';
import { keccak256 } from 'ethers';
export const home = () => process.env.HYBURN_HOME || join(homedir(), '.hyburn');
export function atomicJSON(path, data) {
  mkdirSync(dirname(path), {recursive:true, mode:0o700});
  const temp = `${path}.${randomUUID()}.tmp`;
  const fd = openSync(temp, 'wx', 0o600);
  try { writeFileSync(fd, JSON.stringify(data)); fsyncSync(fd); } finally { closeSync(fd); }
  try { renameSync(temp, path); const dir = openSync(dirname(path), 'r'); try { fsyncSync(dir); } finally { closeSync(dir); } }
  finally { if (existsSync(temp)) unlinkSync(temp); }
}
export class Session {
  static async open(chain, miner, account) {
    const s = new Session();
    s.lock = createServer(socket => socket.destroy());
    await new Promise((resolve, reject) => {
      s.lock.once('error', () => reject(new Error('Wallet already in use or local session lock unavailable; stop the other miner first.')));
      s.lock.listen({host:'127.0.0.1', port:32768 + parseInt(account.slice(-4),16) % 20000, exclusive:true}, resolve);
    });
    s.lock.unref();
    s.path = join(home(), `${chain}-${miner.toLowerCase()}-${account.toLowerCase()}.session.json`);
    s.state = {v:1, identity:`${chain}:${miner.toLowerCase()}:${account.toLowerCase()}`, settings:{}, spent:'0', gas:'0', burns:0, last_round:-1, pending:null};
    if (existsSync(s.path)) {
      try {
        const v = JSON.parse(readFileSync(s.path, 'utf8'));
        if (v.v !== 1 || v.identity !== s.state.identity || !v.settings || BigInt(v.spent)<0n || BigInt(v.gas)<0n || !Number.isInteger(v.burns) || v.burns<0 || !Number.isInteger(v.last_round) || v.last_round < -1 || !('pending' in v)) throw Error();
        s.state = v;
      } catch { throw new Error('Invalid session file; restore its backup. Refusing to reset the budget.'); }
    }
    s.save(); return s;
  }
  save() { atomicJSON(this.path, this.state); }
  configure(supplied, fresh=false) {
    if (this.state.pending) throw new Error('Resolve the saved transaction before changing the session.');
    const previous = this.state.settings;
    const settings = {amount:'', budget:'', max_cost:'', at:'30', rounds:'', reserve:'1000000000000000', ...(fresh ? {} : previous)};
    for (const [k,v] of Object.entries(supplied)) if (v !== undefined && v !== null) settings[k] = v;
    if (!settings.amount) throw new Error('First run needs --amount. Later runs can use mine with no options.');
    if (BigInt(settings.amount)<=0n || BigInt(settings.reserve)<0n || !/^\d+$/.test(settings.at) || Number(settings.at)<1 || Number(settings.at)>998 || (settings.rounds && (!/^\d+$/.test(settings.rounds) || BigInt(settings.rounds)<1n)) || (settings.budget && BigInt(settings.budget)<0n) || (settings.max_cost && BigInt(settings.max_cost)<0n)) throw new Error('Invalid mining settings; --at must be 1..998.');
    if (!settings.budget) { if (!settings.rounds) throw new Error('First session needs --budget or --rounds; gas is additional.'); settings.budget=(BigInt(settings.amount)*BigInt(settings.rounds)).toString(); }
    if (Object.keys(previous).length && !fresh && Object.keys(settings).some(k => settings[k] !== previous[k])) throw new Error('Saved mining settings differ. Use --new-session with the full new settings to authorize a new budget.');
    if (fresh) { atomicJSON(this.path.replace(/\.json$/, '.previous.json'), this.state); Object.assign(this.state, {spent:'0', gas:'0', burns:0}); }
    this.state.settings = settings; this.save(); return settings;
  }
  prepare(raw, value, round, mining) {
    if (this.state.pending) throw new Error('Unresolved transaction; refusing another send.');
    this.state.pending = {hash:keccak256(raw), raw, value:value.toString(), round, mining}; this.save();
  }
  settle(rc) {
    const p = this.state.pending;
    if (!p || rc.hash.toLowerCase() !== p.hash.toLowerCase()) throw new Error('Receipt does not match saved transaction.');
    this.state.gas = (BigInt(this.state.gas) + rc.gasUsed * rc.gasPrice).toString();
    if (rc.status === 1 && BigInt(p.value)>0n) {
      this.state.last_round = Math.max(this.state.last_round, p.round);
      if (p.mining) { this.state.spent = (BigInt(this.state.spent)+BigInt(p.value)).toString(); this.state.burns++; }
    }
    this.state.pending = null; this.save();
  }
  async recover(provider) {
    const p = this.state.pending; if (!p) return;
    console.log(`Recovering saved transaction ${p.hash}; no new transaction will be signed.`);
    let rc = await provider.getTransactionReceipt(p.hash);
    if (!rc) {
      if (keccak256(p.raw) !== p.hash) throw new Error('Invalid saved transaction; refusing broadcast.');
      try { await provider.broadcastTransaction(p.raw); } catch { /* receipt remains authoritative */ }
      rc = await provider.waitForTransaction(p.hash, 1, 180000);
    }
    if (!rc) throw new Error('Saved transaction still pending; restart to recover it.');
    this.settle(rc); console.log(rc.status ? 'Saved transaction confirmed.' : 'Saved transaction reverted; gas recorded.');
  }
}

export function loadProfile() {
  const path = join(home(), 'config.json'); if (!existsSync(path)) return;
  let values; try { values = JSON.parse(readFileSync(path,'utf8')); if (!values || Array.isArray(values) || typeof values !== 'object') throw Error(); }
  catch { throw new Error('Invalid ~/.hyburn/config.json; fix the connection profile before continuing.'); }
  for (const key of ['HYBURN_RPC','HYBURN_MINER','HYBURN_CHAIN_ID','HYBURN_DEPLOY_BLOCK','HYBURN_KEYSTORE']) {
    if (key === 'HYBURN_KEYSTORE' && process.env.HYBURN_PRIVATE_KEY) continue;
    if (key in values) { if (typeof values[key] !== 'string') throw new Error('Invalid connection profile value'); process.env[key] ??= values[key]; }
  }
}
