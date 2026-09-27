#!/usr/bin/env python3
"""Regression checks against a disposable mock RPC; no wallet or real chain.

Run from the repository root after forge build:
python3 cli/conformance/cache_boundary.py 'node cli/node/hyburn.mjs'
"""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[2]
MINER = '0x' + '11' * 20
TOKEN = '0x' + '22' * 20
ACCOUNT = '0x' + '33' * 20
GENESIS = 1800000000
UNIT = 10**18

def words(*values):
    return '0x' + ''.join(f'{value:064x}' for value in values)

class Fixture:
    def __init__(self):
        artifact = json.loads((ROOT / 'out/HyburnMiner.sol/HyburnMiner.json').read_text())
        self.methods = {v: k.split('(')[0] for k, v in artifact['methodIdentifiers'].items()}
        self.ended = False
        self.claimed = False
        self.reads = []
        self.waiting = False
        self.block_reads = 0

    def handle(self, method, params):
        number = 11 if self.ended else 10
        if method == 'web3_clientVersion':
            return 'cache-boundary-test'
        if method == 'eth_chainId':
            return '0x3e7'
        if method == 'eth_blockNumber':
            return hex(number)
        if method == 'eth_getBlockByNumber':
            self.block_reads += 1
            return dict(
                number=hex(number), timestamp=hex(GENESIS + (10 if self.waiting else (999 if self.ended else 998))),
                hash='0x' + 'ab' * 32, parentHash='0x' + 'cd' * 32,
                nonce='0x0000000000000000', sha3Uncles='0x' + '00' * 32,
                logsBloom='0x' + '00' * 256, transactionsRoot='0x' + '00' * 32,
                stateRoot='0x' + '00' * 32, receiptsRoot='0x' + '00' * 32,
                miner=MINER, difficulty='0x0', totalDifficulty='0x0',
                extraData='0x', size='0x200', gasLimit='0x1c9c380', gasUsed='0x0',
                baseFeePerGas='0x1', mixHash='0x' + '00' * 32, transactions=[], uncles=[],
            )
        if method == 'eth_getLogs':

            if not self.ended:
                time.sleep(1.3)
            query = params[0]
            topic = query['topics'][0]
            if isinstance(topic, list):
                topic = topic[0]
            return [dict(
                address=MINER, topics=[topic, words(0), words(int(ACCOUNT, 16))],
                data=words(UNIT, UNIT), blockNumber=hex(number),
                blockHash='0x' + 'ab' * 32, transactionHash='0x' + 'ef' * 32,
                transactionIndex='0x0', logIndex='0x0', removed=False,
            )]
        if method == 'eth_call':
            name = self.methods[params[0].get('data', params[0].get('input'))[2:10]]
            constants = dict(genesisTimestamp=GENESIS, ROUND_DURATION=999,
                             MIN_BURN=999000000000000, INITIAL_REWARD=5781250000000,
                             HALVING_INTERVAL=86400, TERMINAL_SEQUENCE=3715200,
                             TERMINAL_REMAINDER=1209600, token=int(TOKEN, 16))
            if name in constants:
                return words(constants[name])
            self.reads.append((name, params[1]))

            pinned = params[1] == hex(number)
            if name == 'rounds':
                return words(0, (2 if self.ended else 1) * UNIT if pinned else 9 * UNIT, 1)
            if name == 'burned':
                return words(UNIT)
            if name == 'claimed':
                return words(int(self.claimed))
        raise AssertionError(f'unexpected RPC: {method} {params}')

def main():
    fixture = Fixture()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))

            def reply(item):
                try:
                    result = fixture.handle(item['method'], item.get('params', []))
                    return dict(jsonrpc='2.0', id=item['id'], result=result)
                except Exception as error:
                    return dict(jsonrpc='2.0', id=item['id'], error=dict(code=-32000, message=str(error)))

            result = [reply(item) for item in request] if isinstance(request, list) else reply(request)
            payload = json.dumps(result).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    with tempfile.TemporaryDirectory(prefix='hyburn-cache-test-') as home:
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            env = {k: v for k, v in os.environ.items() if not k.startswith('HYBURN_')}
            env.update(HYBURN_HOME=home, HYBURN_RPC=f'http://127.0.0.1:{server.server_port}',
                       HYBURN_MINER=MINER, HYBURN_DEPLOY_BLOCK='10', HYBURN_CHAIN_ID='999')
            wrong_chain = dict(env, HYBURN_CHAIN_ID='1')
            rejected = subprocess.run(shlex.split(sys.argv[1]) + ['status'], env=wrong_chain,
                                      cwd=ROOT, capture_output=True, text=True, timeout=30)
            assert rejected.returncode != 0 and 'RPC chain ID mismatch' in rejected.stdout + rejected.stderr, rejected.stdout + rejected.stderr
            print('ok   incorrect expected chain ID is rejected before signing')
            for setting in [dict(HYBURN_PRIVATE_KEY='SECRET_SENTINEL'),
                            dict(HYBURN_KEYSTORE=str(Path(home) / 'missing.json'), HYBURN_KEYSTORE_PASSWORD='test-password')]:
                failed = subprocess.run(shlex.split(sys.argv[1]) + ['claim', '--dry-run'],
                                        env=dict(env, **setting), cwd=ROOT, capture_output=True, text=True, timeout=30)
                assert failed.returncode != 0 and 'SECRET_SENTINEL' not in failed.stdout + failed.stderr, failed.stdout + failed.stderr
                assert ('private key' if 'HYBURN_PRIVATE_KEY' in setting else 'keystore') in (failed.stdout + failed.stderr).lower(), failed.stdout + failed.stderr
            print('ok   invalid key and missing keystore errors are actionable and redact input')

            cache_path = Path(home) / f'999-{MINER}-{ACCOUNT}.json'
            command = shlex.split(sys.argv[1]) + ['history', '--account', ACCOUNT]

            def run():
                fixture.reads.clear()
                result = subprocess.run(command, env=env, cwd=ROOT, capture_output=True, text=True, timeout=30)
                assert result.returncode == 0, result.stdout + result.stderr
                cache = json.loads(cache_path.read_text())
                assert cache['v'] == 3, cache
                expected = '0xb' if fixture.ended else '0xa'
                assert all(tag == expected for _, tag in fixture.reads), fixture.reads
                return cache['rounds']['0'], result.stdout

            entry, output = run()
            assert entry is None and 'open' in output, (entry, output)
            assert len(fixture.reads) == 3, fixture.reads
            print('ok   wall clock crossing the boundary does not finalize an open chain round')

            fixture.ended = True
            entry, output = run()
            assert int(entry['total']) == 2 * UNIT and int(entry['burned']) == UNIT, entry
            assert not entry['claimed'] and 'claimable' in output, (entry, output)
            print('ok   exact end timestamp finalizes all values from one numbered block')

            fixture.claimed = True
            entry, _ = run()
            assert entry['claimed'] and fixture.reads == [('claimed', '0xb')], fixture.reads
            run()
            assert not fixture.reads, fixture.reads
            print('ok   unclaimed rounds read only claimed; claimed rounds read no contract state')

            cache_path.write_text(json.dumps(dict(v=2, scannedTo=11, rounds={
                '0': dict(burned=str(UNIT), total=str(9 * UNIT), seq=0, claimed=True)
            })))
            entry, _ = run()
            assert int(entry['total']) == 2 * UNIT and len(fixture.reads) == 3, (entry, fixture.reads)
            print('ok   old potentially incorrect v2 cache is rebuilt')

            # A waiting miner must stay responsive without polling once a second.
            fixture.waiting = True
            env['HYBURN_PRIVATE_KEY'] = '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80'
            log_path = Path(home) / 'waiting.log'
            with log_path.open('w') as output:
                proc = subprocess.Popen(shlex.split(sys.argv[1]) + ['mine', '--amount', '0.001', '--dry-run'],
                                        env=env, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 15
                    while 'local wait' not in log_path.read_text():
                        assert proc.poll() is None, log_path.read_text()
                        assert time.monotonic() < deadline, log_path.read_text()
                        time.sleep(0.1)
                    reads = fixture.block_reads
                    time.sleep(3)
                    assert fixture.block_reads == reads, 'RPC polling continued during local wait'
                    proc.send_signal(signal.SIGINT)
                    assert proc.wait(timeout=5) == 0, log_path.read_text()
                    text = log_path.read_text()
                    assert 'mining stopped' in text and '\x1b' not in text, text
                    print('ok   local countdown makes no RPC requests, logs stay plain, Ctrl-C exits')
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait(timeout=5)

        finally:
            server.shutdown()
            server.server_close()

if __name__ == '__main__':
    main()
