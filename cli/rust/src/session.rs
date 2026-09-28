use alloy::{
    primitives::{keccak256, U256},
    rpc::types::TransactionReceipt,
};
use eyre::{bail, Result};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::Write,
    net::TcpListener,
    path::PathBuf,
};
#[derive(Serialize, Deserialize, Clone)]
pub struct Pending {
    pub hash: String,
    pub raw: String,
    pub value: String,
    pub round: i64,
    pub mining: bool,
}
#[derive(Serialize, Deserialize, Clone)]
pub struct State {
    pub v: u32,
    pub identity: String,
    pub settings: BTreeMap<String, String>,
    pub spent: String,
    pub gas: String,
    pub burns: u64,
    pub last_round: i64,
    pub pending: Option<Pending>,
    #[serde(default)]
    pub finishing: bool,
}
pub struct Session {
    pub state: State,
    path: PathBuf,
    _lock: TcpListener,
}
pub fn home() -> PathBuf {
    std::env::var("HYBURN_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            PathBuf::from(std::env::var("HOME").expect("HOME required")).join(".hyburn")
        })
}
pub fn atomic_json(path: &std::path::Path, data: &impl Serialize) -> Result<()> {
    fs::create_dir_all(path.parent().unwrap())?;
    let temp = path.with_extension(format!("{}.tmp", std::process::id()));
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let result = (|| -> Result<()> {
        let mut f = options.open(&temp)?;
        f.write_all(&serde_json::to_vec(data)?)?;
        f.sync_all()?;
        drop(f);
        fs::rename(&temp, path)?;
        File::open(path.parent().unwrap())?.sync_all()?;
        Ok(())
    })();
    if temp.exists() {
        let _ = fs::remove_file(temp);
    }
    result
}
impl Session {
    pub fn open(chain: u64, miner: String, account: String) -> Result<Self> {
        let miner = miner.to_lowercase();
        let account = account.to_lowercase();
        let port = 32768 + u16::from_str_radix(&account[account.len() - 4..], 16)? % 20000;
        let lock=TcpListener::bind(("127.0.0.1",port)).map_err(|_|eyre::eyre!("Wallet already in use or local session lock unavailable; stop the other miner first."))?;
        let identity = format!("{chain}:{miner}:{account}");
        let path = home().join(format!("{chain}-{miner}-{account}.session.json"));
        let state = if path.exists() {
            let v: State = serde_json::from_slice(&fs::read(&path)?).map_err(|_| {
                eyre::eyre!(
                    "Invalid session file; restore its backup. Refusing to reset the budget."
                )
            })?;
            if v.v != 1 || v.identity != identity || v.last_round < -1 {
                bail!("Invalid session identity")
            };
            v.spent.parse::<U256>()?;
            v.gas.parse::<U256>()?;
            v
        } else {
            State {
                v: 1,
                identity,
                settings: BTreeMap::new(),
                spent: "0".into(),
                gas: "0".into(),
                burns: 0,
                last_round: -1,
                finishing: false,
                pending: None,
            }
        };
        let s = Self {
            state,
            path,
            _lock: lock,
        };
        s.save()?;
        Ok(s)
    }
    pub fn save(&self) -> Result<()> {
        atomic_json(&self.path, &self.state)
    }
    pub fn configure(
        &mut self,
        supplied: BTreeMap<String, String>,
        fresh: bool,
    ) -> Result<BTreeMap<String, String>> {
        if self.state.pending.is_some() {
            bail!("Resolve the saved transaction before changing the session.")
        }
        let mut settings: BTreeMap<String, String> = [
            ("amount", ""),
            ("budget", ""),
            ("max_cost", ""),
            ("at", "30"),
            ("rounds", ""),
            ("reserve", "1000000000000000"),
        ]
        .into_iter()
        .map(|(k, v)| (k.into(), v.into()))
        .collect();
        if !fresh {
            settings.extend(self.state.settings.clone());
        }
        settings.extend(supplied);
        if settings["amount"].is_empty() {
            bail!("First run needs --amount. Later runs can use mine with no options.")
        }
        let at = settings["at"].parse::<u64>()?;
        let amount = settings["amount"].parse::<U256>()?;
        if at < 1 || at > 998 || amount.is_zero() {
            bail!("Invalid mining settings; --at must be 1..998.")
        };
        settings["reserve"].parse::<U256>()?;
        for key in ["budget", "max_cost"] {
            if !settings[key].is_empty() {
                settings[key].parse::<U256>()?;
            }
        }
        if !settings["rounds"].is_empty() && settings["rounds"].parse::<u64>()? == 0 {
            bail!("Invalid --rounds")
        }
        if settings["budget"].is_empty() {
            if settings["rounds"].is_empty() {
                bail!("First session needs --budget or --rounds; gas is additional.")
            };
            settings.insert(
                "budget".into(),
                amount
                    .checked_mul(U256::from(settings["rounds"].parse::<u64>()?))
                    .ok_or_else(|| eyre::eyre!("Budget overflow"))?
                    .to_string(),
            );
        }
        if !fresh && !self.state.settings.is_empty() && settings != self.state.settings {
            bail!("Saved mining settings differ. Use --new-session with the full new settings to authorize a new budget.")
        }
        if fresh {
            atomic_json(&self.path.with_extension("previous.json"), &self.state)?;
            self.state.spent = "0".into();
            self.state.gas = "0".into();
            self.state.burns = 0;
            self.state.finishing = false;
        }
        self.state.settings = settings.clone();
        self.save()?;
        Ok(settings)
    }
    pub fn prepare(&mut self, raw: Vec<u8>, value: U256, round: i64, mining: bool) -> Result<()> {
        if self.state.pending.is_some() {
            bail!("Unresolved transaction; refusing another send.")
        }
        self.state.pending = Some(Pending {
            hash: format!("{:#x}", keccak256(&raw)),
            raw: format!("0x{}", alloy::hex::encode(raw)),
            value: value.to_string(),
            round,
            mining,
        });
        self.save()
    }
    pub fn settle(&mut self, rc: &TransactionReceipt) -> Result<()> {
        let p = self
            .state
            .pending
            .as_ref()
            .ok_or_else(|| eyre::eyre!("No pending transaction"))?;
        if p.hash != format!("{:#x}", rc.transaction_hash) {
            bail!("Receipt does not match saved transaction")
        }
        self.state.gas = (self.state.gas.parse::<U256>()?
            + U256::from(rc.gas_used) * U256::from(rc.effective_gas_price))
        .to_string();
        if rc.status() && p.value.parse::<U256>()? > U256::ZERO {
            self.state.last_round = self.state.last_round.max(p.round);
            if p.mining {
                self.state.spent =
                    (self.state.spent.parse::<U256>()? + p.value.parse::<U256>()?).to_string();
                self.state.burns += 1;
            }
        }
        self.state.pending = None;
        self.save()
    }
}

pub fn load_profile() -> Result<()> {
    let path = home().join("config.json");
    if !path.exists() {
        return Ok(());
    }
    let values: BTreeMap<String, String> = serde_json::from_slice(&fs::read(path)?)?;
    for key in [
        "HYBURN_RPC",
        "HYBURN_MINER",
        "HYBURN_CHAIN_ID",
        "HYBURN_DEPLOY_BLOCK",
        "HYBURN_KEYSTORE",
    ] {
        if key == "HYBURN_KEYSTORE" && std::env::var("HYBURN_PRIVATE_KEY").is_ok() {
            continue;
        }
        if std::env::var(key).is_err() {
            if let Some(value) = values.get(key) {
                std::env::set_var(key, value);
            }
        }
    }
    Ok(())
}
