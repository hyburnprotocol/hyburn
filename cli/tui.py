#!/usr/bin/env python3
"""Automatic shared UI bootstrap for the native Node.js, Go and Rust engines."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def ensure_runtime():
    if sys.version_info < (3,10):
        raise SystemExit('The shared TUI needs Python 3.10+. Use --plain for native line output.')
    runtime = ROOT/'python'/'.venv'
    python = runtime/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    # Package installers never receive wallet secrets from the mining environment.
    install_env = {k:v for k,v in os.environ.items() if not k.startswith('HYBURN_')}
    runtime.mkdir(parents=True, exist_ok=True)
    with open(runtime/'.tui-setup.lock','a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            if lock.tell()==0:
                lock.write(b'0');lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_LOCK,1)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX)
        if not python.exists():
            print('Preparing the shared terminal UI (one-time setup)...', flush=True)
            subprocess.run([sys.executable,'-m','venv',str(runtime)],env=install_env,check=True)
        ready = subprocess.run([str(python),'-c','import web3; assert web3.__version__.split(".")[0] == "7"'],
                               env=install_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if not ready:
            print('Installing the shared UI dependencies; no wallet access...', flush=True)
            subprocess.run([str(python),'-m','pip','install','-r',str(ROOT/'python'/'requirements.txt')],env=install_env,check=True)
    return python


def main():
    python = ensure_runtime()
    os.execv(str(python), [str(python),str(ROOT/'python'/'engine_dashboard.py'),*sys.argv[1:]])

if __name__=='__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit('Setup cancelled. No mining engine started.')
