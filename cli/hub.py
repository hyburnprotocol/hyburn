"""Interactive launcher. Opening the hub never starts mining or loads a signer."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
ENGINES = ('python', 'node', 'go', 'rust')


def banner(title, lines):
    color = sys.stdout.isatty() and not os.environ.get('NO_COLOR')
    cyan, reset = ('\033[96m', '\033[0m') if color else ('', '')
    print('\n' + cyan + '=' * 62)
    print(' HYBURN / ' + title)
    print('=' * 62 + reset)
    for line in lines:
        print(' ' + line)
    print()


def main(engine='python'):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SystemExit('Interactive hub needs a terminal. Use ./hyburn mine, setup or status explicitly.')
    while True:
        developer = (ROOT.parent/'script/developer/deployment.local.json').is_file()
        lines = [f'Engine: {engine.upper()}  |  HyperEVM',
                 '1  Mining dashboard / resume (start confirmation required)',
                 '2  Connect a mining wallet', '3  Mining status', '4  My mining history',
                 '5  Choose mining engine', '6  HYBURN pool overview (read-only)', '7  My liquidity (own wallet and positions)']
        if developer:
            lines.append('8  Local developer mining console (existing local session)')
        lines += ['Q  Exit', 'No transaction is sent by opening this menu.']
        banner('CONTROL CENTER', lines)
        try:
            choice = input('Select: ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print('\nClosed.'); return
        if choice == 'q': return
        if choice == '5':
            banner('MINING ENGINE', [f'{i+1}  {name}' for i,name in enumerate(ENGINES)])
            selected = input('Engine [Enter to keep current]: ').strip()
            if selected in ('1','2','3','4'): engine = ENGINES[int(selected)-1]
            continue
        command = {'1':'mine','2':'setup','3':'status','4':'history'}.get(choice)
        if command:
            args = [sys.executable,str(ROOT/'hyburn'),'--engine',engine,command]
        elif choice == '8' and developer:
            from tui import ensure_runtime
            args = [str(ensure_runtime()),str(ROOT/'python/deploy_console.py'),'--execute']
        elif choice in ('6','7'):
            from tui import ensure_runtime
            python = ensure_runtime()
            if choice == '6': args = [str(python),str(ROOT/'python/pool_status.py')]
            elif choice == '7': args = [str(python),str(ROOT/'python/liquidity_console.py')]
            else: continue
        else: continue
        try:
            subprocess.run(args,check=False)
        except KeyboardInterrupt:
            print('\nChild interrupted. Check its last status before restarting.')
        try: input('\nPress Enter to return to the control center...')
        except (EOFError, KeyboardInterrupt): return
