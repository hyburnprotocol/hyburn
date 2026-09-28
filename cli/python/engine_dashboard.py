"""Common TUI for native mining engines. Only the selected engine signs transactions."""
import argparse
import getpass
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from decimal import Decimal
import terminal_ui

PREFIX = '@HYBURN_UI@'


def option(args, name, default=None):
    for i, value in enumerate(args):
        if value == name and i+1 < len(args):
            return args[i+1]
        if value.startswith(name+'='):
            return value.split('=',1)[1]
    return default


def hype(value):
    return f'{Decimal(value)/Decimal(10**18):.9f} HYPE'


class EngineView:
    def __init__(self, dashboard, rpc):
        self.ui, self.rpc = dashboard, rpc

    def consume(self, line):
        if not line.startswith(PREFIX):
            self.ui.log(line)
            return
        try:
            event=json.loads(line[len(PREFIX):])
            kind=event['type']
            if kind=='clock':
                self.ui.sync_chain(int(event['timestamp']),int(event['genesis']),int(event['duration']))
                self.ui.update(**{'Round (last read)': max(-1,(int(event['timestamp'])-int(event['genesis']))//int(event['duration'])),
                                  'Block (last read)':event['block']})
            elif kind=='meta':
                self.ui.update(Wallet=event['account'],Miner=event['miner'],Chain=event['chain'],
                               Mode='DRY RUN' if event['dry'] else 'LIVE',
                               **{'Token CA':event['token'],'Burn / round':hype(event['amount'])+' + gas',
                                  'Burn budget':hype(event['budget'])+' (gas extra)' if event['budget'] else 'Not set',
                                  'Protected reserve':hype(event['reserve']), 'Send window':f'{event["at"]}s before round end'})
                self.ui.attach_insights(rpc=self.rpc,chain=int(event['chain']),miner=event['miner'],
                                        account=event['account'],genesis=int(event['genesis']),duration=int(event['duration']),
                                        deploy_block=int(event['deploy']),send_window=int(event['at']))
            elif kind=='usage':
                self.ui.update(**{'Session burns':int(event['burns']),'Burn spending':hype(event['spent']),
                                  'Session gas':hype(event['gas'])})
            elif kind=='busy':
                self.ui.signing=bool(event['value'])
            elif kind=='wait':
                deadline=time.monotonic()+max(0,float(event['seconds']))
                label=terminal_ui.clean(event['label'])
                self.ui.status=lambda:f'{label} | ~{max(0,int(deadline-time.monotonic()))}s | local wait'
        except (ValueError, KeyError, TypeError, ArithmeticError):
            self.ui.log('Display update unavailable; mining engine remains authoritative.')


def stop_engine(process):
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        # The native durable journal was written before broadcast. A submitted
        # transaction may confirm after exit and will be recovered on next start.
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def run_engine(command, args, engine):
    from setup_miner import load_profile
    load_profile()
    rpc=option(args,'--rpc',os.environ.get('HYBURN_RPC','https://rpc.hypurrscan.io'))
    with terminal_ui.Dashboard(title=f'HYBURN / {engine.upper()} MINER') as ui:
        ui.update(Engine=engine,Mode='STANDBY - no transactions sent')
        terminal_ui.preview_start(ui,args)
        if not terminal_ui.choose_start('--yes' in args):
            print('Mining not started. No new transactions sent.')
            return 0
        env=dict(os.environ,HYBURN_TUI_CHILD='1')
        # Password stays in memory and is passed only to the selected engine;
        # this display process does not decrypt keys or save passwords.
        if env.get('HYBURN_KEYSTORE') and not env.get('HYBURN_KEYSTORE_PASSWORD'):
            with ui.suspended():
                env['HYBURN_KEYSTORE_PASSWORD']=getpass.getpass('Keystore password (not saved): ')
        ui.update(Mode='CONNECTING')
        ui.log('Starting selected engine; verifying chain and recovering saved session...')
        process=subprocess.Popen([*command,*args],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT,env=env,text=True,bufsize=1,start_new_session=os.name!='nt')
        env.pop('HYBURN_KEYSTORE_PASSWORD',None)
        messages=queue.Queue(maxsize=2000)
        finished=threading.Event()
        def read():
            try:
                for line in process.stdout:
                    # Keep bounded memory even during a temporary slow display.
                    while not finished.is_set():
                        try:
                            messages.put(line.rstrip(),timeout=.2)
                            break
                        except queue.Full:
                            continue
            finally:
                finished.set()
        reader=threading.Thread(target=read,daemon=True)
        reader.start()
        view=EngineView(ui,rpc)
        try:
            while process.poll() is None or not messages.empty() or not finished.is_set():
                try:
                    line=messages.get(timeout=.1)
                    if ui.enabled:
                        view.consume(line)
                    elif not line.startswith(PREFIX):
                        print(line,flush=True)
                except queue.Empty:
                    continue
            return process.returncode
        except KeyboardInterrupt:
            ui.log('Stopping engine; previously submitted transactions may still confirm.')
            stop_engine(process)
            return 130
        finally:
            stop_engine(process)
            finished.set()
            reader.join(timeout=1)
            process.stdout.close()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--engine',choices=['node','go','rust'],required=True)
    p.add_argument('--command',required=True,help='JSON argv supplied by the native entry point')
    p.add_argument('args',nargs=argparse.REMAINDER)
    options=p.parse_args()
    command=json.loads(options.command)
    if not isinstance(command,list) or not command or not all(isinstance(x,str) for x in command):
        p.error('Invalid engine argv')
    args=options.args[1:] if options.args[:1]==['--'] else options.args
    return run_engine(command,args,options.engine)

if __name__=='__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        raise SystemExit(f'Terminal UI stopped ({type(error).__name__}); saved transactions remain recoverable.') from None
