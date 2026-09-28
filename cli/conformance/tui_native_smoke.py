#!/usr/bin/env python3
"""PTY smoke: each native entry point opens the same UI; Q never starts its engine."""
import fcntl
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import tempfile
import termios
import time
import sys,shlex
ROOT=Path(__file__).resolve().parents[2]
COMMANDS=[['node',str(ROOT/'cli/node/hyburn.mjs')],[str(ROOT/'cli/go/hyburn')],[str(ROOT/'cli/rust/target/release/hyburn')]]
if len(sys.argv)>1: COMMANDS=[[a for a in shlex.split(sys.argv[1]) if a not in ('--yes','--plain')]]
for command in COMMANDS:
    with tempfile.TemporaryDirectory() as home:
        env={k:v for k,v in os.environ.items() if not k.startswith('HYBURN_')}
        env.update(TERM='xterm',HYBURN_HOME=home,HYBURN_RPC='http://127.0.0.1:1',HYBURN_MINER='0x'+'11'*20)
        master,slave=pty.openpty()
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',30,110,0,0))
        process=subprocess.Popen(command+['mine'],cwd=ROOT,env=env,stdin=slave,stdout=slave,stderr=slave)
        os.close(slave)
        output=b'';sent=False;deadline=time.monotonic()+20
        try:
            while time.monotonic()<deadline:
                if select.select([master],[],[],.1)[0]:
                    try: output+=os.read(master,65536)
                    except OSError: break
                if b'S: START' in output and not sent:
                    os.write(master,b'7vq');sent=True
                if process.poll() is not None: break
            if process.poll() is None:
                process.kill()
            process.wait()
            assert sent and process.returncode==0 and b'7 Total' in output and b'\x1b[?1049l' in output,(command,output[-2000:])
            assert not list(Path(home).glob('*.session.json'))
            assert not (Path(home)/'insights').exists()
            print('ok',command[0],': shared TUI, total tab, privacy, Q cancels before RPC/session/key access')
        finally:os.close(master)
