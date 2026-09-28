"""Interactive launcher. Opening the hub never starts mining or loads a signer."""
import os
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
ENGINES = ('python', 'node', 'go', 'rust')


def banner(title, lines):
    color = sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb'
    truecolor = os.environ.get('COLORTERM', '').lower() in ('truecolor', '24bit')
    mint = ('\033[38;2;151;252;228m' if truecolor else '\033[96m') if color else ''
    reset = '\033[0m' if color else ''
    print('\n' + mint + ' HY/BURN  /  ' + title)
    print(' ' + '-' * 60 + reset)
    for line in lines:
        print(' ' + line)
    print()


def first_session_args():
    """Collect explicit limits without reading a wallet or changing a saved budget."""
    banner('CONFIGURE FIRST SESSION', [
        'Burns spend native HYPE on HyperEVM. Gas is additional.',
        'You choose the burn amount and the total burn budget.',
        'A 0.001 HYPE wallet reserve is kept by default.',
        'Example: 0.000999 per round, 0.001998 total = two burns.',
        'An existing session is never reset here. Use Resume mining when available.',
        'Enter Q at either prompt to return without starting.',
    ])
    values = []
    for label in ('HYPE to burn per round', 'Total HYPE burn budget (gas extra)'):
        while True:
            raw = input(label + ': ').strip()
            if raw.lower() == 'q':
                return None
            try:
                if len(raw) > 78 or not re.fullmatch(r'(?:[0-9]+(?:\.[0-9]{1,18})?|\.[0-9]{1,18})', raw):
                    raise ValueError()
                value = Decimal(raw)
                if not value.is_finite() or value <= 0 or value.as_tuple().exponent < -18:
                    raise ValueError()
                if not values and value < Decimal('0.000999'):
                    print('Minimum burn is 0.000999 HYPE per round. Enter that amount or more, or Q.')
                    continue
                if values and value < Decimal(values[0]):
                    print('Budget must cover at least one burn. Enter a larger budget or Q.')
                    continue
            except (InvalidOperation, ValueError):
                print('Enter a positive HYPE amount with at most 18 decimals, or Q.')
                continue
            values.append(format(value, 'f'))
            break
    print('Next: review the start screen. Choose Start to authorize mining or Exit to cancel.')
    return ['mine', '--amount', values[0], '--budget', values[1]]


def getting_started():
    banner('YOUR FIRST SESSION', [
        '1. Choose Set up wallet to connect a dedicated wallet (offline).',
        '   Import an encrypted keystore or a private key using hidden input.',
        '   There is no browser-wallet popup. Never enter a seed phrase.',
        '2. Fund that wallet with native HYPE on HyperEVM, chain 999.',
        '   Allow for burns, transaction gas and the protected reserve.',
        '3. Choose Configure mining to enter your burn amount and total burn budget.',
        '4. Review the start screen, then choose Start or Exit.',
        '   Mining normally waits until 30 seconds before round end.',
        '5. Keep the terminal open. Choose Finish & claim for a clean finish.',
        '   Ctrl-C stops the process; a submitted transaction may still confirm.',
        'Later: choose Resume mining. The saved budget does not refill.',
        'Liquidity is optional; you do not need to provide it to mine.',
        'Full walkthrough: cli/GETTING_STARTED.md',
    ])


def menu_state():
    """Read connection metadata only. Never unlock a signer or read developer keys."""
    base = Path(os.environ.get('HYBURN_HOME', str(Path.home()/'.hyburn'))).expanduser()
    profile = base/'config.json'
    config = {}
    error = ''
    if profile.is_file():
        try:
            config = json.loads(profile.read_text())
            if not isinstance(config, dict):
                raise ValueError()
        except (OSError, ValueError):
            config = {}
            error = 'Connection profile is unreadable. Repair it before mining.'
    def setting(key, default=''):
        return os.environ.get(key, config.get(key, default))
    miner = setting('HYBURN_MINER')
    chain = str(setting('HYBURN_CHAIN_ID','999'))
    connection = isinstance(miner,str) and bool(re.fullmatch(r'0x[0-9a-fA-F]{40}',miner)) and int(miner[2:],16) != 0 and chain.isdigit()
    key_path = setting('HYBURN_KEYSTORE')
    wallet_ready = bool(os.environ.get('HYBURN_PRIVATE_KEY'))
    account = ''
    if not wallet_ready and isinstance(key_path,str) and key_path:
        try:
            # Only the public address is used; ciphertext is never decrypted.
            metadata = json.loads(Path(key_path).expanduser().read_text())
            account = metadata.get('address','')
            account = account if account.startswith('0x') else '0x'+account
            wallet_ready = bool(re.fullmatch(r'0x[0-9a-fA-F]{40}',account))
        except (OSError,ValueError,TypeError,AttributeError):
            error = 'Saved wallet file is missing or invalid. Repair wallet setup first.'
    ready = bool(connection and wallet_ready and not error)
    # Match the wallet, chain and Miner. Another wallet's journal is not resumable.
    session = ready and bool(account) and (base/f'{chain}-{miner.lower()}-{account.lower()}.session.json').is_file()
    developer = (ROOT.parent/'script/developer/deployment.local.json').is_file()
    developer_session = developer and (ROOT.parent/'output/developer-deploy/session.json').is_file()
    return dict(ready=ready, connection=bool(connection), session=bool(session),
                developer=developer, developer_session=developer_session,
                profile=profile.is_file(), error=error)


def menu_entries(state):
    entries = []
    if state['session']:
        entries.append(('MINING','resume','Resume mining (saved budget; review before starting)'))
    if state['developer_session']:
        entries.append(('MINING','developer','Resume local developer mining (existing saved budget)'))
    if state['ready']:
        if not state['session']:
            entries.append(('MINING','configure','Configure mining (amount and budget; review before starting)'))
        entries.append(('MINING','setup','Wallet setup information'))
    else:
        entries.append(('MINING','setup','Review wallet setup' if state['profile'] else 'Set up wallet (first step; offline)'))
    if state['connection']:
        entries.append(('MINING','status','Mining status (read-only)'))
    if state['ready']:
        entries.append(('MINING','history','My mining history (read-only)'))
    entries.append(('MINING','engine','Choose mining engine'))
    entries.append(('LIQUIDITY (OPTIONAL)','pool','Pool overview (read-only)'))
    entries.append(('LIQUIDITY (OPTIONAL)','liquidity','Manage liquidity (wallet address required; preview first)'))
    if state['developer'] and not state['developer_session']:
        entries.append(('LOCAL DEVELOPER','developer','Open developer console (review configuration)'))
    return entries


def main(engine='python'):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SystemExit('Interactive hub needs a terminal. Use ./hyburn mine, setup or status explicitly.')
    while True:
        state = menu_state()
        entries = menu_entries(state)
        lines = [f'Engine: {engine.upper()}  |  HyperEVM']
        if state['error']:
            lines += [state['error']]
        elif not state['ready'] and not state['developer_session']:
            lines += ['Get started: set up wallet -> fund with HYPE -> configure mining.']
        elif state['ready'] and not state['session']:
            lines += ['Wallet configured. Next: configure your first mining session.']
        section = None
        actions = {}
        for number,(group,action,label) in enumerate(entries,1):
            if group != section:
                lines += ['',group]
                section = group
            lines.append(f'{number}  {label}')
            actions[str(number)] = action
        lines += ['', 'H  First-time guide', 'Q  Exit', 'No transaction is sent by opening this menu.']
        banner('CONTROL CENTER',lines)
        try:
            choice = input('Select: ').strip().lower()
        except (EOFError,KeyboardInterrupt):
            print('\nClosed.'); return
        if choice == 'q': return
        if choice == 'h':
            getting_started()
            try: input('Press Enter to return...')
            except (EOFError,KeyboardInterrupt): return
            continue
        action = actions.get(choice)
        if action == 'engine':
            banner('MINING ENGINE',[f'{i+1}  {name}' for i,name in enumerate(ENGINES)])
            try: selected = input('Engine [Enter to keep current]: ').strip()
            except (EOFError,KeyboardInterrupt): return
            if selected in ('1','2','3','4'): engine=ENGINES[int(selected)-1]
            continue
        if action == 'configure':
            try: configured = first_session_args()
            except (EOFError,KeyboardInterrupt):
                print('\nConfiguration cancelled. No mining started.'); continue
            if configured is None: continue
            args = [sys.executable,str(ROOT/'hyburn'),'--engine',engine,*configured]
        elif action in ('resume','setup','status','history'):
            command = 'mine' if action == 'resume' else action
            args = [sys.executable,str(ROOT/'hyburn'),'--engine',engine,command]
        elif action in ('developer','pool','liquidity'):
            from tui import ensure_runtime
            script = {'developer':'deploy_console.py','pool':'pool_status.py','liquidity':'liquidity_console.py'}[action]
            args = [str(ensure_runtime()),str(ROOT/'python'/script)]
            if action == 'developer': args += ['--execute']
        else:
            print('Choose a displayed number, H for help, or Q to exit.')
            continue
        try: subprocess.run(args,check=False)
        except KeyboardInterrupt:
            print('\nChild interrupted. Check its last status before restarting.')
        try: input('\nPress Enter to return to the control center...')
        except (EOFError,KeyboardInterrupt): return
