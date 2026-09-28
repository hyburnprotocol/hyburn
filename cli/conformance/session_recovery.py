#!/usr/bin/env python3
"""Local Anvil only: lost replies, cross-language resume, budget and wallet locks."""
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from eth_account import Account
from web3 import Web3

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = [ ['cli/python/.venv/bin/python','cli/python/hyburn.py','--yes'], ['node','cli/node/hyburn.mjs','--yes'], ['cli/go/hyburn','--yes'], ['cli/rust/target/release/hyburn','--yes'] ]
import sys
if len(sys.argv)>1:
    COMMANDS=[shlex.split(sys.argv[1])]

def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0)); return s.getsockname()[1]

def main():
    with tempfile.TemporaryDirectory(prefix='hyburn-sessions-') as temp:
        rpc = f'http://127.0.0.1:{port()}'
        node=subprocess.Popen(['anvil','--host','127.0.0.1','--port',rpc.rsplit(':',1)[1],'--chain-id','31337','--block-time','1','--silent'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        server=None
        try:
            w3=Web3(Web3.HTTPProvider(rpc))
            for _ in range(100):
                if w3.is_connected(): break
                time.sleep(.1)
            # Public Anvil fixture. Never a user's key.
            fixture='0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80'
            deployed=json.loads(subprocess.check_output(['forge','create','src/HyburnMiner.sol:HyburnMiner','--rpc-url',rpc,'--private-key',fixture,'--broadcast','--json'],cwd=ROOT))
            miner=deployed['deployedTo']
            import sys
            sys.path.insert(0,str(ROOT/'cli/python'))
            from hyburn import MINER_ABI
            contract=w3.eth.contract(address=miner,abi=MINER_ABI)
            def warp():
                w3.provider.make_request('evm_increaseTime',[999]);w3.provider.make_request('evm_mine',[])
            warp()
            w3.provider.make_request('evm_increaseTime',[2]);w3.provider.make_request('evm_mine',[])
            dropped={'armed':False}
            estimating=threading.Event(); release_estimate=threading.Event()
            class Proxy(BaseHTTPRequestHandler):
                def log_message(self,*_): pass
                def do_POST(self):
                    body=self.rfile.read(int(self.headers['Content-Length']))
                    request=json.loads(body)
                    requests=request if isinstance(request,list) else [request]
                    results=[]
                    for req in requests:
                        if req['method']=='eth_estimateGas' and dropped.get('pause_estimate'):
                            dropped['pause_estimate']=False;estimating.set();release_estimate.wait(15)
                        if req['method']=='eth_sendRawTransaction' and dropped.get('before'):
                            dropped['before']=False
                            res={'jsonrpc':'2.0','id':req['id'],'error':{'code':-32000,'message':'simulated interruption before broadcast'}}
                        else:
                            with urllib.request.urlopen(urllib.request.Request(rpc,json.dumps(req).encode(),{'Content-Type':'application/json'})) as response:
                                res=json.load(response)
                            if req['method']=='eth_sendRawTransaction' and dropped['armed']:
                                dropped['armed']=False
                                res.pop('result',None);res['error']={'code':-32000,'message':'simulated lost submission reply'}
                        results.append(res)
                    result=results if isinstance(request,list) else results[0]
                    encoded=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
            server=ThreadingHTTPServer(('127.0.0.1',0),Proxy)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            proxy=f'http://127.0.0.1:{server.server_port}'
            for i,cmd in enumerate(COMMANDS):
                account=Account.create();w3.provider.make_request('anvil_setBalance',[account.address,hex(10**19)])
                directory=Path(temp)/str(i);directory.mkdir()
                env={k:v for k,v in os.environ.items() if not k.startswith('HYBURN_')}
                env.update(HYBURN_HOME=str(directory),HYBURN_PRIVATE_KEY=account.key.hex())
                # Verify every language actually loads the saved non-secret profile.
                (directory/'config.json').write_text(json.dumps(dict(HYBURN_RPC=proxy,HYBURN_MINER=miner,HYBURN_CHAIN_ID='31337',HYBURN_DEPLOY_BLOCK='0')))
                def run(command,args,ok=True):
                    p=subprocess.run(command+args,cwd=ROOT,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=35)
                    if (p.returncode==0)!=ok: raise AssertionError(f'{command} {args}: {p.stdout}')
                    return p.stdout
                dropped['armed']=True
                run(cmd,['mine','--amount','0.000999','--budget','0.001998','--rounds','1','--at','998'],False)
                files=list(directory.glob('*.session.json'));assert len(files)==1
                journal=files[0];state=json.loads(journal.read_text());assert state['pending'] and state['spent']=='0'
                rid=state['pending']['round'];txhash=state['pending']['hash']
                w3.eth.wait_for_transaction_receipt(txhash, timeout=15)
                assert contract.functions.burned(rid,account.address).call()==999000000000000
                # Restart in a different implementation; receipt is settled exactly once.
                warp()
                other=COMMANDS[(i+1)%len(COMMANDS)]
                output=run(other,['mine'])
                state=json.loads(journal.read_text());assert state['pending'] is None and state['spent']=='999000000000000' and state['burns']==1 and int(state['gas'])>0
                assert contract.functions.claimed(rid,account.address).call()
                gas=state['gas'];run(cmd,['mine']);assert json.loads(journal.read_text())['gas']==gas
                assert contract.functions.burned(rid,account.address).call()==999000000000000
                run(cmd,['mine','--budget','1'],False)
                # A second local process/language cannot enter the same wallet session.
                waiting=subprocess.Popen(cmd+['mine','--new-session','--amount','0.000999','--budget','0.001998','--at','1'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                try:
                    deadline=time.time()+15
                    while time.time()<deadline:
                        state=json.loads(journal.read_text())
                        if state['settings']['at']=='1':break
                        if waiting.poll() is not None:raise AssertionError(waiting.stdout.read())
                        time.sleep(.1)
                    output=run(other,['mine'],False);assert 'lock unavailable' in output or 'already in use' in output,output
                finally:
                    waiting.terminate();waiting.wait(timeout=10)
                # Reserve prevents a new burn, and no pending transaction is fabricated.
                w3.provider.make_request('anvil_setBalance',[account.address,hex(1500000000000000)])
                run(other,['mine','--new-session','--amount','0.000999','--budget','0.000999','--at','998'],False)
                state=json.loads(journal.read_text());assert state['spent']=='0' and state['pending'] is None
                # Broken journal fails closed rather than silently granting a fresh budget.
                journal.write_text('{broken')
                run(cmd,['mine'],False)
                # Saved-but-never-broadcast raw transaction: after round rollover it
                # reverts on recovery, records gas and consumes no burn budget.
                account2=Account.create();w3.provider.make_request('anvil_setBalance',[account2.address,hex(10**19)])
                env['HYBURN_PRIVATE_KEY']=account2.key.hex()
                dropped['before']=True
                run(cmd,['mine','--amount','0.000999','--budget','0.001998','--rounds','1','--at','998'],False)
                journal2=next(p for p in directory.glob('*.session.json') if p!=journal)
                state2=json.loads(journal2.read_text());assert state2['pending'] is not None
                warp();run(other,['claim'])
                state2=json.loads(journal2.read_text());assert state2['spent']=='0' and state2['burns']==0 and state2['pending'] is None and int(state2['gas'])>0
                # Interrupt while an estimate is in flight: no signing/broadcast follows.
                nonce=w3.eth.get_transaction_count(account2.address)
                estimating.clear();release_estimate.clear();dropped['pause_estimate']=True
                interrupted=subprocess.Popen(cmd+['mine'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                try:
                    assert estimating.wait(15), 'miner did not reach estimate'
                    interrupted.send_signal(signal.SIGINT);time.sleep(.2);release_estimate.set()
                    output=interrupted.communicate(timeout=20)[0]
                    assert 'before signing' in output,output
                    after=json.loads(journal2.read_text())
                    assert after['pending'] is None and after['spent']=='0'
                    assert w3.eth.get_transaction_count(account2.address)==nonce
                finally:
                    release_estimate.set()
                    if interrupted.poll() is None:interrupted.kill();interrupted.wait()
                print(f'ok {shlex.join(cmd)}: lost reply -> cross-language resume; one burn; final claim; saved budget; lock; reserve; corruption; unbroadcast/reverted recovery; interrupt before signing',flush=True)
                warp()
        finally:
            if server:server.shutdown();server.server_close()
            node.terminate();node.wait(timeout=10)

if __name__=='__main__':main()
