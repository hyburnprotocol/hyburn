#!/usr/bin/env python3
"""Public wallet-owned Project X liquidity manager. Default: read-only or local fork preview."""
import argparse
import contextlib
import fcntl
import getpass
import json
import os
import shutil
import socket
import subprocess
import time
from decimal import Decimal as D, ROUND_FLOOR, ROUND_CEILING
from pathlib import Path
from web3 import Web3
from web3.exceptions import TransactionNotFound
import liquidity_protocol as p
from mining_session import home, atomic_json, wallet_lock
from setup_miner import load_profile

POOL = Web3.to_checksum_address('0x561fF10F136da03be56F31A53cd8D87f93694106')
ROOT = None
JOURNAL = None
POSITION_TYPES = ('uint96','address','address','address','uint24','int24','int24','uint128','uint256','uint256','uint128','uint128')
SLOT_TYPES = ('uint160','int24','uint16','uint16','uint16','uint8','bool')
MAX128 = 2**128-1


def units(value, decimals):
    n=D(value)*10**decimals
    p.require(n.is_finite() and n >= 0 and n == n.to_integral_value(), 'Invalid amount or too many decimal places')
    p.require(n < 2**256, 'Amount too large')
    return int(n)


def call(w,address,sig,types=(),values=(),outputs=('uint256',)):
    return p.read(w,address,sig,types,values,outputs)


def verify(w, nft):
    p.require(w.eth.chain_id in (999,31337),'Wrong chain')
    p.require(call(w,p.MANAGER,'factory()',outputs=('address',))[0].lower()==p.FACTORY.lower(),'Wrong manager factory')
    p.require(call(w,p.MANAGER,'WETH9()',outputs=('address',))[0].lower()==p.WHYPE.lower(),'Wrong wrapped token')
    p.require(call(w,p.FACTORY,'getPool(address,address,uint24)',('address','address','uint24'),(p.WHYPE,p.TOKEN,p.FEE),('address',))[0].lower()==POOL.lower(),'Wrong pool')
    p.require(call(w,p.TOKEN,'decimals()')[0]==9 and call(w,p.WHYPE,'decimals()')[0]==18,'Unexpected decimals')
    if nft is None: return None
    pos=call(w,p.MANAGER,'positions(uint256)',('uint256',),(nft,),POSITION_TYPES)
    p.require(pos[2].lower()==p.WHYPE.lower() and pos[3].lower()==p.TOKEN.lower() and pos[4]==p.FEE,'Position is not in this pool')
    p.require(call(w,p.MANAGER,'ownerOf(uint256)',('uint256',),(nft,),('address',))[0].lower()==p.WALLET.lower(),'Position not owned by configured wallet')
    return pos


def price(tick):
    return D('1e-9')/D('1.0001')**tick


def ticks(minimum,maximum,spacing):
    lo,hi=D(minimum),D(maximum)
    p.require(lo.is_finite() and hi.is_finite() and 0<lo<hi,'Price range must be positive and increasing')
    # Round outward in human HYPE/HYBURN price space.
    lower=int(((D('1e-9')/hi).ln()/D('1.0001').ln()/spacing).to_integral_value(rounding=ROUND_FLOOR))*spacing
    upper=int(((D('1e-9')/lo).ln()/D('1.0001').ln()/spacing).to_integral_value(rounding=ROUND_CEILING))*spacing
    p.require(-887272<=lower<upper<=887272,'Range outside supported ticks')
    return lower,upper


def status(w,nft):
    pos=verify(w,nft)
    if pos is None:
        return {'pool':POOL,'wallet':p.WALLET,'positions':owned_positions(w)}
    slot=call(w,POOL,'slot0()',outputs=SLOT_TYPES)
    # eth_call collect includes accrued fees without claiming them on mainnet.
    ct='(uint256,address,uint128,uint128)'
    collect=p.data('collect('+ct+')',(ct,),((nft,p.WALLET,MAX128,MAX128),))
    owed=w.codec.decode(('uint256','uint256'),w.eth.call({'from':p.WALLET,'to':p.MANAGER,'data':collect}))
    return {'pool':POOL,'position':nft,'price_HYPE_per_HYBURN':str(D('1e-9')/(D(slot[0])/2**96)**2),
            'sale_min':str(price(pos[6])),'sale_max':str(price(pos[5])), 'liquidity':str(pos[7]),
            'active':pos[5]<=slot[1]<pos[6],
            'collectable_WHYPE':str(D(owed[0])/10**18),'collectable_HYBURN':str(D(owed[1])/10**9),
            'note':'Collectable amounts can include previously removed principal, not only fees.'}


@contextlib.contextmanager
def fork(rpc,block):
    executable=shutil.which('anvil') or str(Path.home()/'.foundry/bin/anvil')
    p.require(Path(executable).is_file(),'Install Foundry Anvil from https://getfoundry.sh before liquidity previews; mining does not require it')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    process=subprocess.Popen([executable,
        '--fork-url',rpc,'--fork-block-number',str(block),'--chain-id','31337','--host','127.0.0.1',
        '--port',str(port),'--gas-limit','30000000','--silent'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        env={k:v for k,v in os.environ.items() if not k.startswith('HYBURN_')})
    try:
        local=Web3(Web3.HTTPProvider(f'http://127.0.0.1:{port}',request_kwargs={'timeout':90}))
        for _ in range(150):
            p.require(process.poll() is None,'Fork exited')
            if local.is_connected(): break
            time.sleep(.2)
        p.require(local.eth.chain_id==31337,'Local fork guard failed')
        response=local.provider.make_request('anvil_impersonateAccount',[p.WALLET])
        p.require('error' not in response,'Cannot impersonate on local fork')
        yield local
    finally:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill(); process.wait()


def tx(to,payload,value=0):
    return {'from':p.WALLET,'to':to,'data':'0x'+payload.hex(),'value':value}


def local_send(w,t):
    p.require(w.eth.chain_id==31337,'Simulation send refused outside localhost fork')
    gas=w.eth.estimate_gas(t)*12//10
    receipt=w.eth.wait_for_transaction_receipt(w.eth.send_transaction(dict(t,gas=gas)))
    p.require(receipt.status==1,'Fork transaction reverted')
    return receipt


def build(w,args):
    pos=verify(w,args.position)
    deadline=w.eth.get_block('latest').timestamp+1200
    result=[]; details={}
    if args.action=='revoke':
        result=[tx(token,p.data('approve(address,uint256)',('address','uint256'),(p.MANAGER,0))) for token in (p.WHYPE,p.TOKEN)]
        details={'note':'Revoke this manager approval for WHYPE and HYBURN; no liquidity is withdrawn.'}
    elif args.action in ('wrap','unwrap'):
        amount=units(args.amount,18); p.require(amount>0,'Amount must be positive')
        if args.action=='wrap':
            result=[tx(p.WHYPE,p.data('deposit()'),amount)]
        else:
            result=[tx(p.WHYPE,p.data('withdraw(uint256)',('uint256',),(amount,)))]
        details={'amount_HYPE_or_WHYPE':args.amount}
    elif args.action=='collect':
        ct='(uint256,address,uint128,uint128)'
        result=[tx(p.MANAGER,p.data('collect('+ct+')',(ct,),((args.position,p.WALLET,MAX128,MAX128),)))]
        details={'recipient':p.WALLET,'note':'Collects WHYPE and HYBURN, including any previously removed principal.'}
    elif args.action=='remove':
        pct=D(args.percent)
        p.require(pct.is_finite() and 0<pct<=100,'Percent must be > 0 and <= 100')
        liquidity=int(D(pos[7])*pct/100); p.require(liquidity>0,'No liquidity to remove')
        dt='(uint256,uint128,uint256,uint256,uint256)'
        def decrease(a,b): return p.data('decreaseLiquidity('+dt+')',(dt,),((args.position,liquidity,a,b,deadline),))
        quote=w.codec.decode(('uint256','uint256'),w.eth.call(tx(p.MANAGER,decrease(0,0))))
        mins=tuple(x*(10000-args.slippage_bps)//10000 for x in quote)
        ct='(uint256,address,uint128,uint128)'
        collect=p.data('collect('+ct+')',(ct,),((args.position,p.WALLET,MAX128,MAX128),))
        result=[tx(p.MANAGER,p.data('multicall(bytes[])',('bytes[]',),([decrease(*mins),collect],)))]
        details={'liquidity_removed':str(liquidity),'principal_quote_WHYPE':str(D(quote[0])/10**18),
                 'principal_quote_HYBURN':str(D(quote[1])/10**9),'minimum_raw':mins,
                 'note':'Removal and collection are atomic. NFT remains owned by the wallet.'}
    else:
        amounts=(units(args.whype,18),units(args.hyburn,9))
        p.require(any(amounts),'At least one deposit amount is required')
        lower,upper=pos[5:7] if pos else (0,0)
        if args.action=='new':
            spacing=call(w,p.FACTORY,'feeAmountTickSpacing(uint24)',('uint24',),(p.FEE,),('int24',))[0]
            lower,upper=ticks(args.min_price,args.max_price,spacing)
        for token,amount in zip((p.WHYPE,p.TOKEN),amounts):
            if amount:
                p.require(call(w,token,'balanceOf(address)',('address',),(p.WALLET,))[0]>=amount,'Insufficient token balance; wrap HYPE explicitly first if needed')
                allowance=call(w,token,'allowance(address,address)',('address','address'),(p.WALLET,p.MANAGER))[0]
                if allowance!=amount:
                    approval=tx(token,p.data('approve(address,uint256)',('address','uint256'),(p.MANAGER,amount)))
                    local_send(w,approval); result.append(approval)
        def deposit(mins):
            if args.action=='add':
                dt='(uint256,uint256,uint256,uint256,uint256,uint256)'
                return p.data('increaseLiquidity('+dt+')',(dt,),((args.position,*amounts,*mins,deadline),))
            dt='(address,address,uint24,int24,int24,uint256,uint256,uint256,uint256,address,uint256)'
            return p.data('mint('+dt+')',(dt,),((p.WHYPE,p.TOKEN,p.FEE,lower,upper,*amounts,*mins,p.WALLET,deadline),))
        output=('uint128','uint256','uint256') if args.action=='add' else ('uint256','uint128','uint256','uint256')
        quote=w.codec.decode(output,w.eth.call(tx(p.MANAGER,deposit((0,0)))))
        used=quote[-2:]; p.require(quote[-3]>0,'No liquidity minted')
        mins=tuple(x*(10000-args.slippage_bps)//10000 for x in used)
        p.require(all(x==0 or m>0 for x,m in zip(used,mins)),'Deposit too small for protected minima')
        result.append(tx(p.MANAGER,deposit(mins)))
        # Revoke unused approvals after a partially used deposit.
        for token,amount in zip((p.WHYPE,p.TOKEN),amounts):
            if amount: result.append(tx(token,p.data('approve(address,uint256)',('address','uint256'),(p.MANAGER,0))))
        details={'maximum_WHYPE':args.whype,'maximum_HYBURN':args.hyburn,
                 'quote_WHYPE':str(D(used[0])/10**18),'quote_HYBURN':str(D(used[1])/10**9),
                 'minimum_raw':mins,'sale_min':str(price(upper)),'sale_max':str(price(lower)),
                 'ticks':[lower,upper],'note':'Outward tick rounding can require both assets. Preview actual deposited amounts.'}
    return result,details


def save(journal):
    atomic_json(JOURNAL,journal)


def reconcile(w):
    if not JOURNAL.exists():
        print('No operation to reconcile.'); return None
    journal=json.loads(JOURNAL.read_text())
    p.require(journal.get('wallet',p.WALLET).lower()==p.WALLET.lower(),'Journal wallet mismatch')
    uncertain=False
    for entry in journal['transactions']:
        try:
            receipt=w.eth.get_transaction_receipt(entry['hash'])
        except TransactionNotFound:
            entry['status']='unresolved'; uncertain=True; continue
        p.require(Web3.to_hex(receipt.transactionHash).lower()==entry['hash'].lower(),'Receipt hash mismatch; journal preserved')
        entry['status']='confirmed' if receipt.status==1 else 'reverted'
        entry['gas_paid_wei']=receipt.gasUsed*receipt.effectiveGasPrice
        if journal['action']=='new' and receipt.status==1:
            event=Web3.keccak(text='Transfer(address,address,uint256)')
            for log in receipt.logs:
                if log.address.lower()==p.MANAGER.lower() and len(log.topics)==4 and log.topics[0]==event:
                    journal['new_position']=int.from_bytes(log.topics[3],'big')
    entries=journal['transactions']
    all_done=(len(entries)==journal.get('planned_count') and all(e['status']=='confirmed' for e in entries))
    if all_done:
        if journal['action']=='new':
            p.require('new_position' in journal,'Position receipt missing')
            verify(w,journal['new_position'])
        journal['status']='complete'
    elif uncertain:
        journal['status']='unresolved'
    else:
        journal['status']='partial' if entries else 'not_submitted'
    save(journal)
    display=dict(journal,transactions=[{k:v for k,v in entry.items() if k!='raw'} for entry in journal['transactions']])
    print(json.dumps(display,indent=2))
    print('Receipt review only. No transaction was resent.')
    return journal


def recover(w):
    journal=reconcile(w)
    if not journal or journal['status']=='complete': return
    if journal['status']=='unresolved':
        entries=[e for e in journal['transactions'] if e['status']=='unresolved']
        p.require(len(entries)==1 and entries[0].get('raw'),'A transaction is pending or unknown. Legacy journal has no signed bytes; manual reconciliation required.')
        entry=entries[0]
        raw=bytes.fromhex(entry['raw'].removeprefix('0x'))
        p.require(Web3.to_hex(Web3.keccak(raw)).lower()==entry['hash'].lower(),'Saved transaction hash mismatch')
        p.require(w.eth.account.recover_transaction(raw).lower()==p.WALLET.lower(),'Saved transaction signer mismatch')
        p.require(w.eth.chain_id==journal['chain']==999,'Recovery chain mismatch')
        print('Recovery resubmits only the identical signed transaction: '+entry['hash'])
        print('Original amounts, fees, nonce and deadline apply. An expired operation may revert and still cost gas. No later step runs automatically.')
        p.require(input('Type REBROADCAST SAVED TRANSACTION: ').strip()=='REBROADCAST SAVED TRANSACTION','Cancelled')
        try:
            w.eth.send_raw_transaction(raw)
        except Exception:
            print('Broadcast outcome unavailable; journal preserved. Checking receipt only.')
        try:
            w.eth.wait_for_transaction_receipt(entry['hash'],timeout=180,poll_latency=5)
        except Exception:
            raise RuntimeError('Saved transaction remains unresolved; journal preserved. No new transaction signed.') from None
        journal=reconcile(w)
        if journal['status']=='complete': return
    p.require(journal['status']!='unresolved','A transaction is pending or unknown. Do not retry; inspect its hash first.')
    p.require(w.eth.get_transaction_count(p.WALLET,'pending')==w.eth.get_transaction_count(p.WALLET,'latest'),'Pending wallet transactions')
    print('Confirmed steps remain onchain. This closes the local operation; it does NOT undo or repeat them.')
    for token in (p.WHYPE,p.TOKEN):
        allowance=call(w,token,'allowance(address,address)',('address','address'),(p.WALLET,p.MANAGER))[0]
        print(f'Remaining approval for {token}: {allowance} base units')
    print('Review the amounts and any new NFT above before planning another action. Approvals remain until explicitly changed.')
    p.require(input('Type CLOSE REVIEWED OPERATION: ').strip()=='CLOSE REVIEWED OPERATION','Cancelled')
    journal['status']='reviewed'; save(journal)
    print('Operation closed locally. Nothing resent. Start a fresh preview for any remaining work.')


def fee_price(w):
    response=w.provider.make_request('eth_usingBigBlocks',[p.WALLET])
    p.require('error' not in response and isinstance(response.get('result'),bool),'Cannot determine block mode')
    big=response['result']
    if big:
        fee=w.provider.make_request('eth_bigBlockGasPrice',[])
        p.require('error' not in fee,'Big-block fee unavailable')
        price=int(fee['result'],16)*2
    else: price=w.eth.gas_price*2
    p.require(price>0,'Invalid gas price')
    return price,big


def preflight(w,args,transactions,details):
    p.require(w.eth.get_block('latest').timestamp<=details['quote_valid_until'],'Preview expired. Run a fresh preview; no new transaction sent.')
    price,big=fee_price(w)
    limits=details['gas_limits']
    p.require(big or max(limits)<=3_000_000,'Operation requires big blocks')
    maximum=sum(limits)*price
    p.require(maximum<=units(args.gas_budget,18),'Whole-operation gas budget is insufficient')
    p.require(w.eth.get_balance(p.WALLET)>=sum(t['value'] for t in transactions)+maximum+units(args.reserve,18),'Whole operation would breach protected HYPE reserve')
    p.require(w.eth.get_transaction_count(p.WALLET,'pending')==w.eth.get_transaction_count(p.WALLET,'latest'),'Pending wallet transactions')
    print(f'Whole-operation gas ceiling at current fee: {D(maximum)/10**18} HYPE')


def execute(w,args,transactions,details):
    if JOURNAL.exists():
        previous=json.loads(JOURNAL.read_text())
        p.require(previous.get('status') in ('complete','reviewed'),'Previous operation is incomplete. Run reconcile and review it; automatic retry is disabled.')
    p.require(w.eth.chain_id==999,'Execution requires chain 999')
    verify(w,args.position)
    preflight(w,args,transactions,details)
    print('Stop mining with this wallet. Confirm the preview; no automatic block-mode changes.')
    print('Gas budget: '+args.gas_budget+' HYPE; reserve: '+args.reserve+' HYPE')
    p.require(input('Type '+args.action.upper()+' LIQUIDITY to sign: ').strip()==args.action.upper()+' LIQUIDITY','Cancelled')
    try:
        if args.keystore:
            key=w.eth.account.decrypt(Path(args.keystore).expanduser().read_text(),getpass.getpass('Keystore password: '))
        else: key=getpass.getpass('Private key (hidden, never saved): ').strip()
        account=w.eth.account.from_key(key); del key
    except Exception:
        raise RuntimeError('Cannot unlock signing wallet; check the local key or keystore password') from None
    p.require(account.address==p.WALLET,'Wrong signer')
    preflight(w,args,transactions,details)
    if JOURNAL.exists():
        archive=ROOT/('management-'+str(time.time_ns())+'.json')
        JOURNAL.rename(archive)
    journal={'wallet':p.WALLET,'chain':999,'planned_count':len(transactions),'action':args.action,'position':args.position,'details':details,'status':'started','transactions':[]}
    save(journal); spent=0
    budget=units(args.gas_budget,18); reserve=units(args.reserve,18)
    for index,template in enumerate(transactions):
        cleanup=template['data']=='0x'+p.data('approve(address,uint256)',('address','uint256'),(p.MANAGER,0)).hex()
        if not cleanup:
            p.require(w.eth.get_block('latest').timestamp<=details['quote_valid_until'],'Preview expired; stop and reconcile completed steps')
        p.require(w.eth.chain_id==999,'Chain changed')
        p.require(w.eth.get_transaction_count(p.WALLET,'pending')==w.eth.get_transaction_count(p.WALLET,'latest'),'Pending transaction; stop')
        # Revalidate ownership before every step, including allowance cleanup.
        verify(w,args.position)
        w.eth.call(template)
        gas=w.eth.estimate_gas(template)*12//10
        gas_price,big=fee_price(w)
        p.require(big or gas<=3_000_000,'Transaction requires big blocks')
        maximum=gas*gas_price
        p.require(spent+maximum<=budget,'Gas budget exceeded')
        p.require(w.eth.get_balance(p.WALLET)>=template['value']+maximum+reserve,'Protected HYPE reserve would be breached')
        transaction=dict(template,chainId=999,nonce=w.eth.get_transaction_count(p.WALLET,'latest'),gas=gas,gasPrice=gas_price)
        signed=account.sign_transaction(transaction)
        h='0x'+Web3.keccak(signed.raw_transaction).hex().removeprefix('0x')
        entry={'step':index+1,'hash':h,'raw':Web3.to_hex(signed.raw_transaction),'nonce':transaction['nonce'],'to':transaction['to'],'status':'prepared'}
        journal['transactions'].append(entry); save(journal)
        print('Sending '+h,flush=True)
        w.eth.send_raw_transaction(signed.raw_transaction)
        receipt=w.eth.wait_for_transaction_receipt(h,timeout=900,poll_latency=5)
        entry['status']='confirmed' if receipt.status==1 else 'reverted'
        cost=receipt.gasUsed*receipt.effectiveGasPrice; spent+=cost
        entry['gas_paid_wei']=cost; save(journal)
        p.require(receipt.status==1,'Transaction reverted')
        if args.action=='new':
            transfer=Web3.keccak(text='Transfer(address,address,uint256)')
            for log in receipt.logs:
                if log.address.lower()==p.MANAGER.lower() and len(log.topics)==4 and log.topics[0]==transfer:
                    journal['new_position']=int.from_bytes(log.topics[3],'big'); save(journal)
    if args.action=='new':
        p.require('new_position' in journal,'Mint receipt did not identify a position')
        verify(w,journal['new_position'])
    journal['status']='complete'; save(journal)
    print('COMPLETE. Saved receipts: '+str(JOURNAL))


def owned_positions(w):
    count=call(w,p.MANAGER,'balanceOf(address)',('address',),(p.WALLET,))[0]
    p.require(count<=500,'More than 500 positions: specify --position explicitly')
    result=[]
    for index in range(count):
        nft=call(w,p.MANAGER,'tokenOfOwnerByIndex(address,uint256)',('address','uint256'),(p.WALLET,index))[0]
        pos=call(w,p.MANAGER,'positions(uint256)',('uint256',),(nft,),POSITION_TYPES)
        if pos[2].lower()==p.WHYPE.lower() and pos[3].lower()==p.TOKEN.lower() and pos[4]==p.FEE:
            result.append({'id':nft,'liquidity':str(pos[7])})
    return result

def configure(args):
    global ROOT,JOURNAL
    load_profile()
    args.rpc=args.rpc or os.environ.get('HYBURN_RPC',p.RPC)
    args.keystore=args.keystore or os.environ.get('HYBURN_KEYSTORE')
    address=args.wallet
    if not address and args.keystore:
        metadata=json.loads(Path(args.keystore).expanduser().read_text())
        address=metadata.get('address')
        if address and not address.startswith('0x'): address='0x'+address
    p.require(address and Web3.is_address(address),'Connect an encrypted wallet with ./hyburn setup, or provide --wallet ADDRESS for read-only previews')
    p.WALLET=Web3.to_checksum_address(address)
    ROOT=home()/'liquidity'/'999'/p.WALLET.lower()
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    JOURNAL=ROOT/'management-journal.json'
    if args.action in ('add','remove','collect'):
        p.require(args.position is not None,'Select an owned --position NFT ID first')

def main(args):
    configure(args)
    p.require(0<=args.slippage_bps<=500,'Slippage must be 0 to 500 bps')
    p.require(units(args.gas_budget,18)>0,'Gas budget must be positive')
    units(args.reserve,18)
    w=Web3(Web3.HTTPProvider(args.rpc,request_kwargs={'timeout':30}))
    p.require(w.eth.chain_id==999,'Expected HyperEVM mainnet')
    if args.action in ('reconcile','recover'):
        lock=(ROOT/'execution.lock').open('a')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with wallet_lock(p.WALLET):
            recover(w) if args.action=='recover' else reconcile(w)
        return
    print(json.dumps(status(w,args.position),indent=2),flush=True)
    if args.action=='status': return
    lock=(ROOT/'execution.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    block=w.eth.block_number
    with fork(args.rpc,block) as local:
        transactions,details=build(local,args)
        # build already applied approvals to obtain the deposit quote; replay is safe.
        receipts=[]; gas_limits=[]
        for template in transactions:
            gas_limits.append(local.eth.estimate_gas(template)*12//10)
            receipts.append(local_send(local,template))
        details['gas_limits']=gas_limits
        details['quote_valid_until']=w.eth.get_block(block).timestamp+600
        preview={'action':args.action,'position':args.position,'fork_block':block,'details':details,
                 'slippage_bps':args.slippage_bps,'transaction_count':len(transactions),
                 'fork_gas_used':sum(r.gasUsed for r in receipts),'mainnet_transactions_sent':0}
        (ROOT/'management-preview.json').write_text(json.dumps(preview,indent=2)+'\n')
        print(json.dumps(preview,indent=2),flush=True)
    if args.execute:
        with wallet_lock(p.WALLET):
            execute(w,args,transactions,details)
    else: print('Preview passed. No mainnet transactions sent. Add --execute only after reviewing these amounts.')


def parser():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('action',nargs='?',default='status',choices=['status','add','new','remove','collect','wrap','unwrap','reconcile','recover','revoke'])
    a.add_argument('--position',type=int)
    a.add_argument('--wallet',help='Public wallet address; defaults to saved encrypted keystore metadata')
    a.add_argument('--hyburn',default='0',help='Maximum HYBURN deposit')
    a.add_argument('--whype',default='0',help='Maximum existing WHYPE deposit; wrap native HYPE separately')
    a.add_argument('--amount',default='0',help='Exact HYPE/WHYPE wrap or unwrap amount')
    a.add_argument('--percent',default='0',help='Percentage of position liquidity to remove and collect')
    a.add_argument('--min-price',default='0',help='New range minimum HYPE per HYBURN')
    a.add_argument('--max-price',default='0',help='New range maximum HYPE per HYBURN')
    a.add_argument('--slippage-bps',type=int,default=50)
    a.add_argument('--gas-budget',default='0.01')
    a.add_argument('--reserve',default='0.001')
    a.add_argument('--execute',action='store_true')
    a.add_argument('--keystore')
    a.add_argument('--rpc')
    return a

if __name__=='__main__':
    try: main(parser().parse_args())
    except (Exception,KeyboardInterrupt) as error:
        raise SystemExit('STOP: '+str(error)+'\nDo not blindly retry a signed operation. Inspect management-journal.json and use reconcile.')
