#!/usr/bin/env python3
"""Public liquidity wizard; delegates signing and protection to liquidity.py."""
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hub import banner
import liquidity as manage

ROOT=Path(__file__).parent


def ask(label,default):
    return input(f'{label} [{default}]: ').strip() or default


def main():
    from setup_miner import load_profile
    import os, json
    load_profile()
    keystore=os.environ.get('HYBURN_KEYSTORE')
    wallet=''
    if keystore:
        address=json.loads(Path(keystore).expanduser().read_text()).get('address','')
        wallet=address if address.startswith('0x') else '0x'+address
    if not wallet:
        wallet=input('Your public wallet address (or run ./hyburn setup first): ').strip()
    if not manage.Web3.is_address(wallet): raise SystemExit('Invalid wallet address')
    wallet=manage.Web3.to_checksum_address(wallet)
    from mining_session import home, atomic_json
    preferences=home()/'liquidity'/'999'/wallet.lower()/'menu.json'
    nft=str(json.loads(preferences.read_text()).get('position','')) if preferences.exists() else ''
    while True:
        banner('YOUR LIQUIDITY',[
            'Project X / HYBURN-WHYPE / 0.3%',
            f'Wallet: {wallet}',f'Position NFT: {nft or "not selected"}',
            '1  My positions / overview', '2  Add to this position',
            '3  New range in the SAME pool', '4  Remove liquidity and collect',
            '5  Collect fees / owed tokens', '6  Wrap HYPE into WHYPE',
            '7  Unwrap WHYPE into HYPE', '8  Select another owned position NFT',
            '9  Reconcile interrupted operation (read-only)', 'R  Close a reviewed partial operation', 'A  Revoke token approvals', 'Q  Back',
            'Preview first. Mining budgets and liquidity budgets are separate.'])
        selection=input('Select: ').strip().lower()
        if selection=='q': return
        if selection=='8':
            try:
                settings=manage.parser().parse_args(['status','--wallet',wallet])
                manage.configure(settings)
                w=manage.Web3(manage.Web3.HTTPProvider(settings.rpc,request_kwargs={'timeout':20}))
                manage.verify(w,None)
                positions=manage.owned_positions(w)
                print('0  Clear selection')
                for i,position in enumerate(positions,1):
                    print(f'{i}  NFT {position["id"]} | liquidity {position["liquidity"]}')
                value=input('Select a position number [Enter to cancel]: ').strip()
                if value=='0': nft=''
                elif value.isdigit() and 1<=int(value)<=len(positions): nft=str(positions[int(value)-1]['id'])
                else: continue
                atomic_json(preferences,{'position':nft})
            except Exception:
                print('Could not load owned positions. Check RPC connectivity and retry.')
            continue
        action={'1':'status','2':'add','3':'new','4':'remove','5':'collect','6':'wrap','7':'unwrap','9':'reconcile','r':'recover','a':'revoke'}.get(selection)
        if not action: continue
        args=[action,'--wallet',wallet]
        if nft and action in ('status','add','remove','collect'): args+=['--position',nft]
        if action in ('add','remove','collect') and not nft:
            print('View your positions with 1, then select an NFT with 8.'); continue
        if action in ('add','new'):
            args+=['--hyburn',ask('Maximum HYBURN to deposit','0'),'--whype',ask('Maximum existing WHYPE to deposit','0')]
            if action=='new':
                print('Prices are HYPE per HYBURN. A new range creates a new NFT, not a new pool.')
                args+=['--min-price',ask('Minimum sale price','0'),'--max-price',ask('Maximum sale price','0')]
        elif action=='remove':
            args+=['--percent',ask('Percent of liquidity to remove (0-100)','0')]
        elif action in ('wrap','unwrap'): args+=['--amount',ask('Amount to convert','0')]
        if action not in ('status','reconcile','recover'):
            args+=['--slippage-bps',ask('Slippage in basis points (50 = 0.5%)','50'),
                   '--gas-budget',ask('Maximum gas budget in HYPE','0.01'),
                   '--reserve',ask('Protected native HYPE balance','0.001')]
        command=[sys.executable,str(ROOT/'liquidity.py'),*args]
        result=subprocess.run(command,check=False)
        if result.returncode==0 and action not in ('status','reconcile','recover'):
            print('\nPreview finished. Execution will re-simulate and request local signing.')
            if input('Stop the miner first. Continue to signing? [y/N]: ').strip().lower()=='y':
                subprocess.run([*command,'--execute'],check=False)
        input('\nPress Enter to return...')

if __name__=='__main__':
    try: main()
    except (EOFError,KeyboardInterrupt): print('\nClosed. If signing had started, inspect the journal before retrying.')
