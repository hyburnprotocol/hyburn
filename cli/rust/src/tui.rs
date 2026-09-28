use std::{io::{IsTerminal,Write},path::PathBuf,process::Command};
use eyre::{Result,eyre,bail};
use serde_json::{Value,json};

pub fn event(value:Value){
 if std::env::var("HYBURN_TUI_CHILD").as_deref()==Ok("1"){println!("@HYBURN_UI@{value}");}
}
pub struct Busy;
pub fn wallet_name(address:String,chain:u64,background:bool){
 if chain!=999 || std::env::var("HYBURN_HL_NAMES").as_deref()==Ok("0") || std::env::var("HYBURN_TUI_CHILD").as_deref()==Ok("1"){return}
 let Some(path)=script() else{return};
 let run=move || {
  let mut command=Command::new("python3");
  command.arg(path.parent().unwrap().join("python/hl_names.py")).args([address,"999".to_string()]);
  command.env_clear().stdin(std::process::Stdio::null()).stderr(std::process::Stdio::null());
  for key in ["PATH","HOME","HYBURN_HOME","HLN_API_KEY","SYSTEMROOT"]{if let Ok(value)=std::env::var(key){command.env(key,value);}}
  if let Ok(mut child)=command.spawn(){
   let start=std::time::Instant::now();
   loop {match child.try_wait(){Ok(Some(_))=>break,Err(_)=>{let _=child.kill();let _=child.wait();break},_=>{}}
    if start.elapsed()>=std::time::Duration::from_secs(5){let _=child.kill();let _=child.wait();break}
    std::thread::sleep(std::time::Duration::from_millis(50));
   }
  }
 };
 if background {std::thread::spawn(run);} else {run();}
}
impl Busy {pub fn new()->Self{event(json!({"type":"busy","value":true}));Self}}
impl Drop for Busy {fn drop(&mut self){event(json!({"type":"busy","value":false}));}}
fn script()->Option<PathBuf>{
 let exe=std::env::current_exe().ok()?;
 for start in [exe.parent()?.to_path_buf(),std::env::current_dir().ok()?]{
  for dir in start.ancestors(){let path=dir.join("cli/tui.py");if path.is_file(){return Some(path)}}
 }
 None
}
pub fn route(plain:bool,yes:bool)->Result<()>{
 if std::env::var("HYBURN_TUI_CHILD").as_deref()==Ok("1"){return Ok(())}
 let interactive=std::io::stdin().is_terminal()&&std::io::stdout().is_terminal()&&std::io::stderr().is_terminal();
 if interactive&&!plain{
  let script=script().ok_or_else(||eyre!("Shared TUI files not found; run from the repository or use --plain."))?;
  let executable=std::env::current_exe()?;
  let argv=serde_json::to_string(&vec![executable.to_string_lossy().to_string()])?;
  let mut command=Command::new("python3");
  command.arg(script).args(["--engine","rust","--command",&argv,"--"]).args(std::env::args().skip(1));
  #[cfg(unix)] {use std::os::unix::process::CommandExt;let _=command.exec();bail!("Shared TUI needs Python 3.10+; install it or use --plain. No mining started.");}
  #[cfg(not(unix))] {let status=command.status()?;std::process::exit(status.code().unwrap_or(130));}
 }
 if yes{return Ok(())}
 if !std::io::stdin().is_terminal(){bail!("Start choice requires a terminal; use --yes for intentional unattended mining.")}
 print!("Start mining? [y/N] ");std::io::stdout().flush()?;
 let mut answer=String::new();std::io::stdin().read_line(&mut answer)?;
 if !matches!(answer.trim().to_lowercase().as_str(),"y"|"yes"){println!("Mining not started. No new transactions sent.");std::process::exit(0)}
 Ok(())
}
