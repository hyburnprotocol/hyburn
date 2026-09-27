use alloy::{
    network::{EthereumWallet, TransactionBuilder},
    primitives::{Address, B256, U256},
    providers::{Provider, ProviderBuilder},
    rpc::types::{Filter, TransactionRequest},
    signers::local::{LocalSigner, PrivateKeySigner},
    sol,
    sol_types::SolEvent,
};
use clap::{Parser, Subcommand};
use eyre::{bail, eyre, Result};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    io::{IsTerminal, Write},
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

sol! {
    #[sol(rpc)]
    interface IHyburnMiner {
        function genesisTimestamp() external view returns (uint256);
        function ROUND_DURATION() external view returns (uint256);
        function MIN_BURN() external view returns (uint256);
        function INITIAL_REWARD() external view returns (uint256);
        function HALVING_INTERVAL() external view returns (uint256);
        function TERMINAL_SEQUENCE() external view returns (uint256);
        function TERMINAL_REMAINDER() external view returns (uint256);
        function rounds(uint256) external view returns (uint64 miningSequence, uint128 totalBurned, bool created);
        function previewCurrentRoundReward() external view returns (uint256);
        function nonEmptyRoundCount() external view returns (uint256);
        function totalHypeBurned() external view returns (uint256);
        function burned(uint256, address) external view returns (uint128);
        function claimed(uint256, address) external view returns (bool);
        function claimable(uint256, address) external view returns (uint256);
        function token() external view returns (address);
        function burn(uint256 expectedRoundId) external payable;
        function burnAndClaim(uint256 expectedRoundId, uint256[] claimRoundIds) external payable;
        function claimMany(uint256[] roundIds, address account) external;
        event HypeBurned(uint256 indexed roundId, address indexed account, uint256 amount, uint128 roundTotalBurned);
    }
    #[sol(rpc)]
    interface IToken {
        function balanceOf(address) external view returns (uint256);
    }
}

const DEFAULT_RPC: &str = "https://rpc.hypurrscan.io";
const LOG_CHUNK: u64 = 1000;

fn commas(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = String::new();
    for (i, c) in b.iter().enumerate() {
        if i > 0 && (b.len() - i) % 3 == 0 {
            out.push(',');
        }
        out.push(*c as char);
    }
    out
}
fn fmt_units(x: U256, decimals: usize, places: usize) -> String {
    let base = U256::from(10u64).pow(U256::from(decimals as u64));
    let whole = x / base;
    let frac = x % base;
    let mut s = commas(&whole.to_string());
    if places > 0 {
        let f = format!("{:0>width$}", frac.to_string(), width = decimals);
        s.push('.');
        s.push_str(&f[..places]);
    }
    s
}
fn fmt_hype(w: U256, p: usize) -> String { fmt_units(w, 18, p) }
fn fmt_token(u: U256, p: usize) -> String { fmt_units(u, 9, p) }
fn parse_hype(s: &str) -> Result<U256> {
    let (whole, frac) = s.split_once('.').unwrap_or((s, ""));
    if frac.len() > 18 || !(whole.chars().all(|c| c.is_ascii_digit()) && frac.chars().all(|c| c.is_ascii_digit())) || (whole.is_empty() && frac.is_empty()) {
        bail!("not a HYPE amount: {s}");
    }
    let digits = format!("{}{:0<18}", if whole.is_empty() { "0" } else { whole }, frac);
    Ok(U256::from_str_radix(&digits, 10)?)
}
fn fmt_clock(sec: f64) -> String {
    let t = sec.max(0.0) as u64;
    let (d, r) = (t / 86400, t % 86400);
    let (h, r) = (r / 3600, r % 3600);
    let (m, s) = (r / 60, r % 60);
    if d > 0 { format!("{d}d {h:02}:{m:02}:{s:02}") } else if h > 0 { format!("{h}:{m:02}:{s:02}") } else { format!("{m:02}:{s:02}") }
}
fn pct(a: U256, b: U256) -> String {
    if b.is_zero() { return "-".into(); }
    let bp: u64 = (a * U256::from(10000u64) / b).to::<u64>();
    format!("{}.{:02}%", bp / 100, bp % 100)
}
fn log(msg: &str) { println!("{} {msg}", chrono::Local::now().format("%Y-%m-%d %H:%M:%S")); }
fn now_unix() -> f64 { SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64() }

type P = alloy::providers::fillers::FillProvider<
    alloy::providers::fillers::JoinFill<alloy::providers::Identity, alloy::providers::fillers::JoinFill<alloy::providers::fillers::GasFiller, alloy::providers::fillers::JoinFill<alloy::providers::fillers::BlobGasFiller, alloy::providers::fillers::JoinFill<alloy::providers::fillers::NonceFiller, alloy::providers::fillers::ChainIdFiller>>>>,
    alloy::providers::RootProvider,
>;

struct Hyburn {
    provider: P,
    miner: IHyburnMiner::IHyburnMinerInstance<P>,
    token: IToken::ITokenInstance<P>,
    miner_addr: Address,
    chain_id: u64,
    deploy_block: u64,
    genesis: u64,
    dur: u64,
    min_burn: U256,
    init_reward: U256,
    halving: U256,
    terminal: U256,
    remainder: U256,
    signer: Option<PrivateKeySigner>,
    offset: f64,
    latest_block: u64,
    caches: std::cell::RefCell<BTreeMap<String, Cache>>,
}

#[derive(Serialize, Deserialize, Clone)]
struct Entry { burned: String, total: String, seq: u64, claimed: bool }
#[derive(Serialize, Deserialize)]
struct Cache { v: u32, #[serde(rename = "scannedTo")] scanned_to: i64, rounds: BTreeMap<String, Option<Entry>> }

struct Row { round: u64, seq: u64, burned: U256, total: U256, payout: U256, claimed: bool, ended: bool }

impl Hyburn {
    async fn new(rpc: &str, miner: &str, chain_id: Option<u64>, deploy_block: u64) -> Result<Self> {
        let miner_addr: Address = miner.parse().map_err(|_| eyre!("HYBURN_MINER is not set to a valid address"))?;
        let provider = ProviderBuilder::new().connect_http(rpc.parse()?);
        let chain_id = match chain_id { Some(c) => c, None => provider.get_chain_id().await.map_err(|_| eyre!("cannot reach RPC {rpc}"))? };
        let m = IHyburnMiner::new(miner_addr, provider.clone());
        let token = IToken::new(m.token().call().await?, provider.clone());
        let mut h = Self {
            genesis: m.genesisTimestamp().call().await?.to::<u64>(),
            dur: m.ROUND_DURATION().call().await?.to::<u64>(),
            min_burn: m.MIN_BURN().call().await?,
            init_reward: m.INITIAL_REWARD().call().await?,
            halving: m.HALVING_INTERVAL().call().await?,
            terminal: m.TERMINAL_SEQUENCE().call().await?,
            remainder: m.TERMINAL_REMAINDER().call().await?,
            provider, miner: m, token, miner_addr, chain_id, deploy_block, signer: None, offset: 0.0, latest_block: 0, caches: Default::default(),
        };
        h.sync_time().await?;
        Ok(h)
    }
    async fn sync_time(&mut self) -> Result<()> {
        let b = self.provider.get_block_by_number(alloy::eips::BlockNumberOrTag::Latest).await?.ok_or_else(|| eyre!("no block"))?;
        self.offset = b.header.timestamp as f64 - now_unix();
        self.latest_block = b.header.number;
        Ok(())
    }
    fn now(&self) -> f64 { now_unix() + self.offset }
    fn round_of(&self, t: f64) -> i64 { if t < self.genesis as f64 { -1 } else { ((t - self.genesis as f64) / self.dur as f64) as i64 } }
    fn round_end(&self, rid: u64) -> u64 { self.genesis + (rid + 1) * self.dur }
    fn reward_for_seq(&self, seq: U256) -> U256 {
        if seq >= self.terminal { return U256::ZERO; }
        let era = (seq / self.halving).to::<usize>();
        let mut r = self.init_reward >> era;
        if seq == self.terminal - U256::from(1u64) { r += self.remainder; }
        r
    }
    fn address(&self) -> Address { self.signer.as_ref().expect("key").address() }
    fn load_key(&mut self) -> Result<()> {
        let signer = if let Ok(ks) = std::env::var("HYBURN_KEYSTORE") {
            let pw = match std::env::var("HYBURN_KEYSTORE_PASSWORD") { Ok(p) => p, Err(_) => rpassword::prompt_password("keystore password: ")? };
            LocalSigner::decrypt_keystore(ks, pw)?
        } else if let Ok(pk) = std::env::var("HYBURN_PRIVATE_KEY") {
            pk.parse::<PrivateKeySigner>().map_err(|_| eyre!("bad private key"))?
        } else {
            bail!("no key: set HYBURN_KEYSTORE (encrypted JSON) or HYBURN_PRIVATE_KEY");
        };
        self.signer = Some(signer);
        Ok(())
    }
    fn cache_path(&self, acct: Address) -> PathBuf {
        let d = std::env::var("HYBURN_HOME").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".hyburn"));
        let _ = std::fs::create_dir_all(&d);
        d.join(format!("{}-{}-{}.json", self.chain_id, format!("{:?}", self.miner_addr).to_lowercase(), format!("{acct:?}").to_lowercase()))
    }
    fn with_cache<T>(&self, acct: Address, f: impl FnOnce(&mut Cache) -> T) -> T {
        let key = format!("{acct:?}").to_lowercase();
        let mut caches = self.caches.borrow_mut();
        if !caches.contains_key(&key) {
            let p = self.cache_path(acct);
            let c = std::fs::read_to_string(&p).ok().and_then(|s| serde_json::from_str::<Cache>(&s).ok()).filter(|c| c.v == 3)
                .unwrap_or(Cache { v: 3, scanned_to: self.deploy_block as i64 - 1, rounds: BTreeMap::new() });
            caches.insert(key.clone(), c);
        }
        let c = caches.get_mut(&key).unwrap();
        let out = f(c);
        let _ = std::fs::write(self.cache_path(acct), serde_json::to_string(c).unwrap_or_default());
        out
    }
    async fn my_rounds(&self, acct: Address) -> Result<Vec<u64>> {
        let start = self.with_cache(acct, |c| (c.scanned_to + 1).max(0) as u64);
        let latest = self.provider.get_block_number().await?;
        let mut found = vec![];
        let mut a = start;
        while a <= latest {
            let b = (a + LOG_CHUNK - 1).min(latest);
            let filter = Filter::new().address(self.miner_addr).event_signature(IHyburnMiner::HypeBurned::SIGNATURE_HASH).topic2(B256::left_padding_from(acct.as_slice())).from_block(a).to_block(b);
            for l in self.provider.get_logs(&filter).await? {
                let rid: U256 = l.topics().get(1).map(|t| U256::from_be_bytes(t.0)).unwrap_or_default();
                found.push(rid.to::<u64>());
            }
            a = b + 1;
        }
        Ok(self.with_cache(acct, |c| {
            for rid in found { c.rounds.entry(rid.to_string()).or_insert(None); }
            c.scanned_to = latest as i64;
            let mut ids: Vec<u64> = c.rounds.keys().filter_map(|k| k.parse().ok()).collect();
            ids.sort();
            ids
        }))
    }
    async fn round_rows(&self, acct: Address, ids: &[u64]) -> Result<Vec<Row>> {

        let block = self.provider.get_block_by_number(alloy::eips::BlockNumberOrTag::Latest).await?.ok_or_else(|| eyre!("no block"))?;
        let t = block.header.timestamp;
        let block_id = alloy::eips::BlockId::number(block.header.number);
        let mut rows = vec![];
        for &rid in ids {
            let ended = t >= self.round_end(rid);
            let e = self.with_cache(acct, |c| c.rounds.get(&rid.to_string()).cloned().flatten());
            let (b, total, seq, cl) = match e {
                Some(e) if e.claimed => (U256::from_str_radix(&e.burned, 10)?, U256::from_str_radix(&e.total, 10)?, e.seq, true),
                Some(e) if ended => {
                    let cl = self.miner.claimed(U256::from(rid), acct).block(block_id).call().await?;
                    self.with_cache(acct, |c| { if let Some(Some(x)) = c.rounds.get_mut(&rid.to_string()) { x.claimed = cl; } });
                    (U256::from_str_radix(&e.burned, 10)?, U256::from_str_radix(&e.total, 10)?, e.seq, cl)
                }
                _ => {
                    let r = self.miner.rounds(U256::from(rid)).block(block_id).call().await?;
                    let b = U256::from(self.miner.burned(U256::from(rid), acct).block(block_id).call().await?);
                    let cl = self.miner.claimed(U256::from(rid), acct).block(block_id).call().await?;
                    let total = U256::from(r.totalBurned);
                    if ended {
                        let entry = Entry { burned: b.to_string(), total: total.to_string(), seq: r.miningSequence, claimed: cl };
                        self.with_cache(acct, |c| { c.rounds.insert(rid.to_string(), Some(entry)); });
                    }
                    (b, total, r.miningSequence, cl)
                }
            };
            let reward = self.reward_for_seq(U256::from(seq));
            let payout = if total.is_zero() { U256::ZERO } else { reward * b / total };
            rows.push(Row { round: rid, seq, burned: b, total, payout, claimed: cl, ended });
        }
        Ok(rows)
    }
    fn mark_claimed(&self, acct: Address, ids: &[U256]) {
        self.with_cache(acct, |c| { for id in ids { if let Some(Some(e)) = c.rounds.get_mut(&id.to_string()) { e.claimed = true; } } });
    }
    async fn claimable_ids(&self, acct: Address) -> Result<Vec<U256>> {
        let ids = self.my_rounds(acct).await?;
        Ok(self.round_rows(acct, &ids).await?.into_iter().filter(|r| r.ended && !r.claimed && !r.burned.is_zero()).map(|r| U256::from(r.round)).collect())
    }

    async fn send(&self, name: &str, mut tx: TransactionRequest, value: U256, dry_run: bool) -> Result<Option<alloy::rpc::types::TransactionReceipt>> {
        let from = self.address();
        tx = tx.with_from(from).with_value(value).with_to(self.miner_addr);
        let gas = self.provider.estimate_gas(tx.clone()).await.map_err(|e| eyre!("would revert: {e}"))? * 12 / 10;
        let fees = self.provider.estimate_eip1559_fees().await?;
        let (max_fee, tip) = (fees.max_fee_per_gas, fees.max_priority_fee_per_gas.max(1));
        let cost = value + U256::from(gas) * U256::from(max_fee);
        let bal = self.provider.get_balance(from).await?;
        if bal < cost { bail!("balance {} HYPE < needed {} HYPE (value + max gas)", fmt_hype(bal, 4), fmt_hype(cost, 4)); }
        if dry_run { log(&format!("dry run: would send {name} value={} HYPE gas={gas} maxFee={max_fee}", fmt_hype(value, 4))); return Ok(None); }
        let nonce = self.provider.get_transaction_count(from).await?;
        tx = tx.with_gas_limit(gas).with_max_fee_per_gas(max_fee).with_max_priority_fee_per_gas(tip).with_nonce(nonce).with_chain_id(self.chain_id);
        let wallet = EthereumWallet::from(self.signer.clone().unwrap());
        let envelope = tx.build(&wallet).await?;
        let pending = self.provider.send_tx_envelope(envelope).await?;
        let hash = *pending.tx_hash();
        log(&format!("sent {}", hex::encode(hash)));
        let rc = pending.with_timeout(Some(Duration::from_secs(180))).get_receipt().await?;
        if !rc.status() { bail!("transaction reverted: {hash:?}"); }
        Ok(Some(rc))
    }
}

mod hex { pub fn encode(h: alloy::primitives::B256) -> String { h.0.iter().map(|b| format!("{b:02x}")).collect() } }

async fn cmd_status(h: &mut Hyburn, account: Option<String>) -> Result<()> {
    h.sync_time().await?;
    let t = h.now();
    let rid = h.round_of(t);
    println!("chain          {}  block {}", h.chain_id, commas(&h.latest_block.to_string()));
    if rid < 0 {
        println!("status         not started; round 0 opens in {}", fmt_clock(h.genesis as f64 - t));
        println!("first reward   {} HYBURN", fmt_token(h.reward_for_seq(U256::ZERO), 2));
        return Ok(());
    }
    let rid = rid as u64;
    let r = h.miner.rounds(U256::from(rid)).call().await?;
    let total = U256::from(r.totalBurned);
    let reward = h.miner.previewCurrentRoundReward().call().await?;
    println!("round          {}  ends in {}", commas(&rid.to_string()), fmt_clock(h.round_end(rid) as f64 - t));
    println!("issued         {} HYBURN", fmt_token(reward, 2));
    println!("burned so far  {} HYPE", fmt_hype(total, 4));
    println!("per 1 HYPE     {}", if total.is_zero() { "all of it".to_string() } else { fmt_token(reward * U256::from(10u64).pow(U256::from(18u64)) / total, 3) + " HYBURN" });
    println!("min burn       {} HYPE", fmt_hype(h.min_burn, 6));
    println!("non-empty      {} rounds  |  all-time burned {} HYPE", commas(&h.miner.nonEmptyRoundCount().call().await?.to_string()), fmt_hype(h.miner.totalHypeBurned().call().await?, 2));
    let acct: Option<Address> = match account { Some(a) => Some(a.parse()?), None => h.signer.as_ref().map(|s| s.address()) };
    if let Some(a) = acct {
        let mine = U256::from(h.miner.burned(U256::from(rid), a).call().await?);
        let ids = h.claimable_ids(a).await?;
        let mut cl = U256::ZERO;
        for id in &ids { cl += h.miner.claimable(*id, a).call().await?; }
        println!("account        {a:?}");
        println!("  HYPE         {}", fmt_hype(h.provider.get_balance(a).await?, 4));
        println!("  HYBURN       {}", fmt_token(h.token.balanceOf(a).call().await?, 3));
        println!("  this round   {} HYPE{}", fmt_hype(mine, 4), if total.is_zero() { String::new() } else { format!("  ({})", pct(mine, total)) });
        println!("  claimable    {} HYBURN in {} round(s)", fmt_token(cl, 3), ids.len());
    }
    Ok(())
}

async fn cmd_history(h: &Hyburn, account: Option<String>) -> Result<()> {
    let acct: Address = match account { Some(a) => a.parse()?, None => h.signer.as_ref().map(|s| s.address()).ok_or_else(|| eyre!("history needs --account or a key"))? };
    let ids = h.my_rounds(acct).await?;
    let rows = h.round_rows(acct, &ids).await?;
    if rows.is_empty() { println!("no burns from this account"); return Ok(()); }
    println!("{:>10} {:>9} {:>16} {:>16} {:>8} {:>16}  status", "round", "seq", "you burned", "round total", "share", "HYBURN");
    for r in rows.iter().rev() {
        let status = if !r.ended { "open" } else if r.claimed { "claimed" } else { "claimable" };
        println!("{:>10} {:>9} {:>16} {:>16} {:>8} {:>16}  {status}", commas(&r.round.to_string()), commas(&r.seq.to_string()), fmt_hype(r.burned, 4), fmt_hype(r.total, 4), pct(r.burned, r.total), fmt_token(r.payout, 3));
    }
    Ok(())
}

async fn cmd_claim(h: &mut Hyburn, dry_run: bool) -> Result<()> {
    h.load_key()?;
    let acct = h.address();
    let ids = h.claimable_ids(acct).await?;
    if ids.is_empty() { println!("nothing to claim"); return Ok(()); }
    let mut total = U256::ZERO;
    for id in &ids { total += h.miner.claimable(*id, acct).call().await?; }
    log(&format!("claiming {} HYBURN from {} round(s)", fmt_token(total, 3), ids.len()));
    for batch in ids.chunks(200) {
        let tx = h.miner.claimMany(batch.to_vec(), acct).into_transaction_request();
        if h.send("claimMany", tx, U256::ZERO, dry_run).await?.is_some() { h.mark_claimed(acct, batch); }
    }
    if !dry_run { log(&format!("done. HYBURN balance {}", fmt_token(h.token.balanceOf(acct).call().await?, 3))); }
    Ok(())
}

async fn do_burn(h: &mut Hyburn, amount: U256, dry_run: bool) -> Result<bool> {
    if amount < h.min_burn { bail!("amount below minimum {} HYPE", fmt_hype(h.min_burn, 6)); }
    h.sync_time().await?;
    let rid = h.round_of(h.now());
    if rid < 0 { bail!("not started yet"); }
    let rid = rid as u64;
    let acct = h.address();
    let ids = h.claimable_ids(acct).await?;
    log(&format!("burn {} HYPE into round {}{}", fmt_hype(amount, 4), commas(&rid.to_string()), if ids.is_empty() { String::new() } else { format!(", claiming {} round(s)", ids.len()) }));
    let (name, tx) = if ids.is_empty() { ("burn", h.miner.burn(U256::from(rid)).into_transaction_request()) } else { ("burnAndClaim", h.miner.burnAndClaim(U256::from(rid), ids.clone()).into_transaction_request()) };
    let rc = match h.send(name, tx, amount, dry_run).await {
        Ok(rc) => rc,
        Err(e) if e.to_string().contains("RoundMismatch") => { log("round changed before the transaction landed; nothing was burned"); return Ok(false); }
        Err(e) => return Err(e),
    };
    if let Some(rc) = rc {
        if !ids.is_empty() { h.mark_claimed(acct, &ids); }
        let r = h.miner.rounds(U256::from(rid)).call().await?;
        let total = U256::from(r.totalBurned);
        let mine = U256::from(h.miner.burned(U256::from(rid), acct).call().await?);
        log(&format!("confirmed in block {}; round total {} HYPE, your share {}", commas(&rc.block_number.unwrap_or_default().to_string()), fmt_hype(total, 4), pct(mine, total)));
    }
    Ok(true)
}

async fn wait_local(seconds: f64, label: &str, stop: &AtomicBool) {
    log(&format!("{label}; local wait ~{seconds:.0}s, no RPC requests"));
    let duration = Duration::from_secs_f64(seconds.max(0.0));
    let start = Instant::now();
    let tty = std::io::stderr().is_terminal();
    while !stop.load(Ordering::SeqCst) {
        let left = duration.saturating_sub(start.elapsed());
        if left.is_zero() || start.elapsed() >= Duration::from_secs(30) { break; }
        if tty {
            eprint!("\r\x1b[2K{label} | ~{} | Ctrl-C to stop", fmt_clock(left.as_secs_f64()));
            let _ = std::io::stderr().flush();
        }
        tokio::time::sleep(left.min(Duration::from_millis(500))).await;
    }
    if tty { eprint!("\r\x1b[2K"); let _ = std::io::stderr().flush(); }
}

#[allow(clippy::too_many_arguments)]
async fn cmd_mine(h: &mut Hyburn, amount: &str, max_cost: Option<String>, at: u64, budget: Option<String>, rounds: Option<u64>, dry_run: bool) -> Result<()> {
    h.load_key()?;
    let amount = parse_hype(amount)?;
    if amount < h.min_burn { bail!("--amount below minimum {} HYPE", fmt_hype(h.min_burn, 6)); }
    let max_cost = max_cost.map(|s| parse_hype(&s)).transpose()?;
    let budget = budget.map(|s| parse_hype(&s)).transpose()?;
    let stop = Arc::new(AtomicBool::new(false));
    { let s = stop.clone(); tokio::spawn(async move { let _ = tokio::signal::ctrl_c().await; s.store(true, Ordering::SeqCst); }); }
    let mut desc = format!("mining as {:?}: {} HYPE per round, send {at}s before round end", h.address(), fmt_hype(amount, 4));
    if let Some(m) = max_cost { desc += &format!(", max cost {} HYPE/HYBURN", fmt_hype(m, 6)); }
    if let Some(b) = budget { desc += &format!(", budget {} HYPE", fmt_hype(b, 4)); }
    if dry_run { desc += ", DRY RUN"; }
    log(&desc);
    let (mut spent, mut burns, mut last_round) = (U256::ZERO, 0u64, -1i64);
    let one_token = U256::from(10u64).pow(U256::from(9u64));
    while !stop.load(Ordering::SeqCst) {
        h.sync_time().await?;
        let t = h.now();
        let rid = h.round_of(t);
        if rid < 0 {
            log(&format!("not started; round 0 opens in {}", fmt_clock(h.genesis as f64 - t)));
            wait_local((h.genesis as f64 - t).max(1.0), "Waiting for genesis", &stop).await;
            continue;
        }
        if rid == last_round {
            wait_local((h.round_end(rid as u64) as f64 - t + 1.0).max(0.5), &format!("Next round {}", rid + 1), &stop).await;
            continue;
        }
        let send_at = h.round_end(rid as u64) as f64 - at as f64;
        if t < send_at {
            wait_local(send_at - t, &format!("Round {rid}: waiting for send window"), &stop).await;
            continue;
        }
        last_round = rid;
        let r = h.miner.rounds(U256::from(rid as u64)).call().await?;
        let total = U256::from(r.totalBurned);
        let reward = h.miner.previewCurrentRoundReward().call().await?;
        if let Some(m) = max_cost {
            if !reward.is_zero() {
                let cost = (total + amount) * one_token / reward;
                if cost > m { log(&format!("round {}: cost {} HYPE/HYBURN > max {}; skipping", commas(&rid.to_string()), fmt_hype(cost, 6), fmt_hype(m, 6))); continue; }
            }
        }
        if let Some(b) = budget {
            if spent + amount > b { log(&format!("budget reached ({} of {} HYPE); stopping", fmt_hype(spent, 4), fmt_hype(b, 4))); break; }
        }
        match do_burn(h, amount, dry_run).await {
            Ok(true) => {
                spent += amount; burns += 1;
                if rounds.is_some_and(|n| burns >= n) { log(&format!("done: {burns} round(s)")); break; }
            }
            Ok(false) => {}
            Err(e) => { log(&format!("stopped: {e}")); break; }
        }
    }
    log(&format!("mining stopped. burned {} HYPE in {burns} round(s)", fmt_hype(spent, 4)));
    Ok(())
}

#[derive(Parser)]
#[command(name = "hyburn", version, about = "Hyburn miner (Rust)")]
struct Cli {
    #[arg(long, env = "HYBURN_RPC", default_value = DEFAULT_RPC)] rpc: String,
    #[arg(long, env = "HYBURN_MINER", default_value = "")] miner: String,
    #[arg(long, env = "HYBURN_CHAIN_ID")] chain_id: Option<u64>,
    #[arg(long, env = "HYBURN_DEPLOY_BLOCK", default_value_t = 0)] deploy_block: u64,
    #[command(subcommand)] cmd: Cmd,
}
#[derive(Subcommand)]
enum Cmd {
    #[command(about = "current round and protocol state")]
    Status { #[arg(long)] account: Option<String> },
    #[command(about = "burn once into the current round (claims finished rounds too)")]
    Burn { amount: String, #[arg(long)] dry_run: bool },
    #[command(about = "burn every round until stopped")]
    Mine {
        #[arg(long)] amount: String,
        #[arg(long, help = "skip the round if HYPE per HYBURN, counting your burn, is above this at send time (later burns by others in the same round still lower everyone's payout)")] max_cost: Option<String>, #[arg(long, default_value_t = 30)] at: u64, #[arg(long)] budget: Option<String>, #[arg(long)] rounds: Option<u64>, #[arg(long)] dry_run: bool },
    #[command(about = "claim every finished round you took part in")]
    Claim { #[arg(long)] dry_run: bool },
    #[command(about = "your rounds")]
    History { #[arg(long)] account: Option<String> },
}

#[tokio::main]
async fn main() {
    if let Err(e) = run().await { eprintln!("{e}"); std::process::exit(1); }
}

async fn run() -> Result<()> {
    let cli = Cli::parse();
    let mut h = Hyburn::new(&cli.rpc, &cli.miner, cli.chain_id, cli.deploy_block).await?;
    let has_key = std::env::var("HYBURN_KEYSTORE").is_ok() || std::env::var("HYBURN_PRIVATE_KEY").is_ok();
    match cli.cmd {
        Cmd::Status { account } => { if account.is_none() && has_key { h.load_key()?; } cmd_status(&mut h, account).await }
        Cmd::History { account } => { if account.is_none() && has_key { h.load_key()?; } cmd_history(&h, account).await }
        Cmd::Burn { amount, dry_run } => { h.load_key()?; do_burn(&mut h, parse_hype(&amount)?, dry_run).await.map(|_| ()) }
        Cmd::Claim { dry_run } => cmd_claim(&mut h, dry_run).await,
        Cmd::Mine { amount, max_cost, at, budget, rounds, dry_run } => cmd_mine(&mut h, &amount, max_cost, at, budget, rounds, dry_run).await,
    }
}
