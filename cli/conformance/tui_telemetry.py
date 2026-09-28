#!/usr/bin/env python3
"""Native UI event integration, disposable Anvil + public test key, dry-run only."""
import json, os, socket, subprocess, sys, tempfile, time, shlex
from pathlib import Path
from web3 import Web3
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cli/python'))
from engine_dashboard import EngineView,PREFIX
from terminal_ui import Dashboard
from unittest.mock import MagicMock
commands=[['node','cli/node/hyburn.mjs'],['cli/go/hyburn'],['cli/rust/target/release/hyburn']]
if len(sys.argv)>1: commands=[[a for a in shlex.split(sys.argv[1]) if a not in ('--yes','--plain')]]
with socket.socket() as sock:
 sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
rpc=f'http://127.0.0.1:{port}'
node=subprocess.Popen(['anvil','--port',str(port),'--silent'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
 w3=Web3(Web3.HTTPProvider(rpc))
 for _ in range(50):
  if w3.is_connected():break
  time.sleep(.1)
 # Public, disposable Anvil fixture, never a real wallet.
 key='0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80'
 artifact=json.loads((ROOT/'out/HyburnMiner.sol/HyburnMiner.json').read_text())
 factory=w3.eth.contract(abi=artifact['abi'],bytecode=artifact['bytecode']['object'])
 receipt=w3.eth.wait_for_transaction_receipt(factory.constructor().transact({'from':w3.eth.accounts[0]}))
 miner=w3.eth.contract(address=receipt.contractAddress,abi=artifact['abi'])
 genesis=miner.functions.genesisTimestamp().call()
 w3.provider.make_request('evm_setNextBlockTimestamp',[genesis+2]);w3.provider.make_request('evm_mine',[])
 for command in commands:
  with tempfile.TemporaryDirectory() as home:
   env={k:v for k,v in os.environ.items() if not k.startswith('HYBURN_')}
   env.update(HYBURN_HOME=home,HYBURN_TUI_CHILD='1',HYBURN_RPC=rpc,HYBURN_MINER=miner.address,
              HYBURN_PRIVATE_KEY=key,HYBURN_CHAIN_ID='31337')
   result=subprocess.run(command+['--yes','mine','--amount','0.000999','--rounds','1','--at','998','--dry-run'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
   assert result.returncode==0,(command,result.stdout,result.stderr)
   dashboard=Dashboard(False);dashboard.attach_insights=MagicMock();view=EngineView(dashboard,rpc)
   events=[]
   for line in result.stdout.splitlines():
    view.consume(line)
    if line.startswith(PREFIX):events.append(json.loads(line[len(PREFIX):])['type'])
   assert {'meta','clock','usage','busy'}<=set(events),(command,events)
   assert dashboard.fields['Mode']=='DRY RUN' and dashboard.fields['Session burns']=='1'
   assert dashboard.attach_insights.call_args.kwargs['send_window']==998
   assert dashboard.fields['Token CA'].lower()==miner.functions.token().call().lower()
   assert not dashboard.signing
   assert miner.functions.totalHypeBurned().call()==0
   assert key not in result.stdout+result.stderr
   print('ok',command[0],': actual native telemetry -> shared fields, clock, costs, analytics; zero HYPE burned')
finally:
 node.terminate();node.wait()
