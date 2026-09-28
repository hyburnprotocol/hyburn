#!/usr/bin/env python3
"""Local deployment console. Signing keys and session files stay outside the public website."""
import argparse
import fcntl
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import sys
import threading
from contextlib import contextmanager, nullcontext
import terminal_ui
from mining_session import wallet_lock
from decimal import Decimal
from requests.exceptions import RequestException
from web3 import Web3
from eth_account import Account
from web3.exceptions import TransactionNotFound, ContractLogicError

ROOT = Path(__file__).resolve().parents[2]
WALLET = ''  # Set an expected wallet in the ignored local configuration.
CONFIG_PATH = ROOT / 'script/developer/deployment.local.json'
MIN_BURN = 999_000_000_000_000
UNIT = 10**18


@contextmanager
def activity(label):
    """TTY-only animation; the worker never performs RPC or reads signing data."""
    dashboard = terminal_ui.current()
    if dashboard:
        with dashboard.activity(label):
            yield
        return
    done = threading.Event()
    def animate():
        started = time.monotonic()
        i = 0
        while not done.is_set():
            text = label() if callable(label) else f'{label} | {int(time.monotonic() - started)}s'
            sys.stderr.write(f'\r\033[2K{"|/-"[i % 3]} {text}')
            sys.stderr.flush()
            i += 1
            done.wait(0.2)
    worker = None
    if sys.stderr.isatty():
        worker = threading.Thread(target=animate, daemon=True)
        worker.start()
    try:
        yield
    finally:
        done.set()
        if worker:
            worker.join()
            sys.stderr.write('\r\033[2K')
            sys.stderr.flush()


class ResilientHTTPProvider(Web3.HTTPProvider):
    # Only reads/simulations may be replayed. Never replay transaction submission.
    SAFE = {'eth_chainId', 'eth_blockNumber', 'eth_getBlockByNumber', 'eth_getBlockByHash',
            'eth_getBalance', 'eth_getTransactionCount', 'eth_getTransactionReceipt',
            'eth_getTransactionByHash', 'eth_getCode', 'eth_call', 'eth_estimateGas',
            'eth_gasPrice', 'eth_maxPriorityFeePerGas', 'eth_feeHistory', 'eth_getLogs'}

    MIN_INTERVAL = 1.25  # At most ~48 requests/minute from this console, including retries.

    def make_request(self, method, params):
        attempt = 0
        while True:
            limited = False
            try:
                with activity(f'RPC {method} (rate-limited)'):
                    remaining = getattr(self, '_next_request', 0) - time.monotonic()
                    if remaining > 0:
                        time.sleep(remaining)
                    interval = max(self.MIN_INTERVAL, 4 if time.monotonic() < getattr(self, '_rate_until', 0) else 0)
                    self._next_request = time.monotonic() + interval
                    reply = super().make_request(method, params)
            except RequestException as error:
                status = getattr(getattr(error, 'response', None), 'status_code', None)
                if method not in self.SAFE or (status is not None and status != 429 and status < 500):
                    raise
                limited = status == 429
            else:
                message = str(reply.get('error', {}).get('message', '')).lower()
                limited = reply.get('error', {}).get('code') == -32005 or any(word in message for word in ('rate limit', 'too many requests'))
                temporary = limited or any(word in message for word in ('invalid block height', 'rate limit', 'too many requests', 'temporarily unavailable', 'timeout', 'timed out'))
                if method not in self.SAFE or not temporary:
                    return reply
            # Read failures never trigger a send or a process restart. Ctrl-C still works.
            if limited:
                now = time.monotonic()
                strikes = getattr(self, '_rate_strikes', 0) if now < getattr(self, '_rate_until', 0) else 0
                delay = 30 if strikes == 0 else 60
                self._rate_strikes = strikes + 1
                self._rate_until = now + delay + 300
                print(f'RPC rate limit ({method}); cooling down {delay}s. Slowing requests to 4s apart for at least 5 minutes.', flush=True)
            else:
                delay = min(2 ** min(attempt, 6), 60)
                print(f'RPC read unavailable ({method}); waiting {delay}s before retry {attempt + 1}. No transaction resent.', flush=True)
            attempt += 1
            wait_locally(delay, 'RPC retry; no transaction resent')


def wait_locally(seconds, label='Waiting locally; no RPC requests'):
    """Monotonic countdown; animation never increases RPC traffic."""
    deadline = time.monotonic() + max(0, seconds)
    with activity(lambda: f'{label} | ~{max(0, int(deadline - time.monotonic()))}s remaining | Ctrl-C to stop'):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(60, remaining))


def read_local_config(path=CONFIG_PATH):
    if not path.exists():
        return {}
    os.chmod(path, 0o600)
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError):
        raise RuntimeError('Cannot read local deployment JSON; check its syntax and permissions') from None


def load_signer(expected, keystore_path=None, config_path=CONFIG_PATH):
    # Never echo third-party parser errors: they may contain secret input.
    if keystore_path:
        try:
            keystore = json.loads(Path(keystore_path).read_text())
            if '_TEMPLATE_ONLY' in keystore:
                raise ValueError('template')
            dashboard = terminal_ui.current()
            with dashboard.suspended() if dashboard else nullcontext():
                password = getpass.getpass('Keystore password (local terminal only): ')
            account = Account.from_key(Account.decrypt(keystore, password))
            del password
        except Exception:
            raise RuntimeError('Cannot unlock keystore; check the file and password') from None
    else:
        config = read_local_config(config_path)
        secret = config.pop('private_key', '')
        if not isinstance(secret, str) or not secret.strip():
            raise RuntimeError('Fill private_key in script/developer/deployment.local.json locally')
        try:
            account = Account.from_key(secret.strip())
        except Exception:
            raise RuntimeError('Invalid private_key: enter a 32-byte hex private key, not a recovery phrase') from None
        finally:
            del secret
    if account.address.lower() != expected.lower():
        raise RuntimeError('Private key address does not match the configured deployment wallet')
    return account


def ensure_config_untracked():
    relative = str(CONFIG_PATH.relative_to(ROOT))
    tracked = subprocess.run(['git', 'ls-files', '--error-unmatch', '--', relative],
                             cwd=ROOT, capture_output=True).returncode == 0
    ignored = subprocess.run(['git', 'check-ignore', '-q', '--', relative],
                             cwd=ROOT, capture_output=True).returncode == 0
    if tracked or not ignored:
        raise RuntimeError('Local deployment JSON must be untracked and ignored by Git')


def checked_source_commit():
    paths = ['src', 'foundry.toml', 'foundry.lock']
    for command in [['git', 'diff', '--quiet', 'HEAD', '--', *paths],
                    ['git', 'diff', '--cached', '--quiet', '--', *paths]]:
        if subprocess.run(command, cwd=ROOT).returncode:
            raise RuntimeError('Contract source/settings differ from the recorded commit')
    if subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '--', 'src'], cwd=ROOT).strip():
        raise RuntimeError('Untracked contract source found')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def verify_runtime(artifact, deployed, expected_values):
    local = bytearray.fromhex(artifact['deployedBytecode']['object'].removeprefix('0x'))
    actual = bytearray(deployed)
    if not actual or len(local) != len(actual):
        raise RuntimeError('Deployed runtime size mismatch')
    values = []
    for spans in artifact['deployedBytecode'].get('immutableReferences', {}).values():
        group = set()
        for span in spans:
            start, length = span['start'], span['length']
            group.add(int.from_bytes(actual[start:start + length], 'big'))
            local[start:start + length] = bytes(length)
            actual[start:start + length] = bytes(length)
        if len(group) != 1:
            raise RuntimeError('Inconsistent immutable slots')
        values.append(group.pop())
    if actual != local or sorted(values) != sorted(expected_values):
        raise RuntimeError('Deployed bytecode or immutable values mismatch')


def hype(n):
    return format(Decimal(n) / UNIT, '.9f')


def update_website(env, target=None):
    """Update only deployment facts; preserve unrelated local environment settings."""
    target = target or ROOT / 'web/.env.local'
    values = {f'NEXT_PUBLIC_{k}': str(v) for k, v in env.items()}
    old = target.read_text().splitlines() if target.exists() else []
    kept = [line for line in old if line.split('=', 1)[0].strip() not in values]
    tmp = target.with_suffix('.local.tmp')
    with open(tmp, 'w') as f:
        os.chmod(tmp, 0o600)
        f.write('\n'.join(kept + [f'{k}={v}' for k, v in values.items()]) + '\n')
    os.replace(tmp, target)


def affordable(balance, cap, spent, value, gas, fee, reserve):
    maximum = value + gas * fee
    return maximum <= cap - spent and maximum + reserve <= balance


class Console:
    def __init__(self, args):
        self.args = args
        self.w3 = Web3(ResilientHTTPProvider(args.rpc, request_kwargs={'timeout': 30}, exception_retry_configuration=None))
        if self.w3.eth.chain_id != args.chain_id:
            raise RuntimeError('RPC chain ID mismatch')
        self.address = Web3.to_checksum_address(args.wallet)
        self.source_commit = checked_source_commit()
        self.artifact = json.loads((ROOT / 'out/HyburnMiner.sol/HyburnMiner.json').read_text())
        self.bytecode = self.artifact['bytecode']['object']
        self.fingerprint = hashlib.sha256(self.bytecode.encode()).hexdigest()
        self.factory = self.w3.eth.contract(abi=self.artifact['abi'], bytecode=self.bytecode)
        self.state_path = Path(args.state).resolve()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = open(str(self.state_path) + '.lock', 'a')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else None
        if self.state:
            if (self.state['wallet'] != self.address or self.state['chain'] != args.chain_id
                    or self.state['build'] != self.fingerprint):
                raise RuntimeError('Saved session wallet/chain/build mismatch; use the original build')
        self.wallet_lease = wallet_lock(self.address)
        self.account = None

    def save(self):
        tmp = self.state_path.with_suffix('.tmp')
        with open(tmp, 'w') as f:
            os.chmod(tmp, 0o600)
            json.dump(self.state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.state_path)

    def screen(self, phase):
        balance = self.w3.eth.get_balance(self.address)
        dashboard = terminal_ui.current()
        if dashboard and self.state:
            burned = len(self.state['rounds']) * MIN_BURN
            remaining = max(0, self.state['cap'] - self.state['spent'])
            dashboard.update(**{
                'Phase': phase, 'Wallet': self.address,
                'Miner': self.state.get('miner', 'not deployed'),
                'Chain': self.args.chain_id,
                'Balance (snapshot)': f'{hype(balance)} HYPE',
                'Burn / transaction': f'{hype(MIN_BURN)} HYPE + gas',
                'Confirmed burns': len(self.state['rounds']),
                'Session burned': f'{hype(burned)} HYPE',
                'Session gas': f"{hype(self.state['spent'] - burned)} HYPE",
                'Session spent': f"{hype(self.state['spent'])} HYPE",
                'Spending cap': f"{hype(self.state['cap'])} HYPE",
                'Remaining cap': f'{hype(remaining)} HYPE',
                'Protected reserve': f"{hype(self.state['reserve'])} HYPE",
                'Available incl. gas': f"{hype(max(0, min(remaining, balance - self.state['reserve'])))} HYPE",
            })
            last = self.state.get('last_tx_cost')
            if last:
                print(f"Last tx: burn {hype(last['burn'])} + gas {hype(last['gas'])} HYPE")
            print(f'{phase}. Snapshot updated; amounts rounded to 9 decimals, confirmed transactions only.')
            return
        print(f'\nHYBURN / PRIVATE DEPLOY CONSOLE — {phase}', flush=True)
        print(f'Wallet  {self.address}\nChain   {self.args.chain_id}\nBalance {hype(balance)} HYPE', flush=True)
        if self.state:
            burned = len(self.state['rounds']) * MIN_BURN
            gas_paid = self.state['spent'] - burned
            cap_left = max(0, self.state['cap'] - self.state['spent'])
            available = max(0, min(cap_left, balance - self.state['reserve']))
            print(f"Burn per transaction  {hype(MIN_BURN)} HYPE + gas", flush=True)
            print(f"Session burned total  {hype(burned)} HYPE ({len(self.state['rounds'])} confirmed burns)", flush=True)
            print(f"Session gas paid      {hype(gas_paid)} HYPE (deployment + mining)", flush=True)
            print(f"Total spent           {hype(self.state['spent'])} HYPE (session burns + gas)", flush=True)
            print(f"Session spending cap  {hype(self.state['cap'])} HYPE (fixed initial budget)", flush=True)
            print(f"Remaining cap         {hype(cap_left)} HYPE", flush=True)
            print(f"Protected reserve     {hype(self.state['reserve'])} HYPE (minimum wallet balance)", flush=True)
            print(f"Available to spend    {hype(available)} HYPE (burns + gas; limited by cap and balance)", flush=True)
            print(f"Miner                 {self.state.get('miner', 'not deployed')}", flush=True)
            last = self.state.get('last_tx_cost')
            if last:
                print(f"Last confirmed tx     {last['kind']}: burn {hype(last['burn'])} + gas {hype(last['gas'])} = {hype(last['burn'] + last['gas'])} HYPE", flush=True)
            print('Amounts rounded to 9 decimals. Pending transactions are not included in totals.', flush=True)

    def prepare(self, fn, value=0):
        # Reject an unrelated pending transaction: this session uses a dedicated wallet.
        nonce = self.w3.eth.get_transaction_count(self.address, 'pending')
        if nonce != self.w3.eth.get_transaction_count(self.address, 'latest'):
            raise RuntimeError('Wallet has a pending transaction; resolve it before continuing')
        tx = fn.build_transaction({'from': self.address, 'chainId': self.args.chain_id,
                                   'nonce': nonce, 'value': value})
        estimate = self.w3.eth.estimate_gas(tx)
        tx['gas'] = (estimate * 125 + 99) // 100
        base = self.w3.eth.get_block('latest').get('baseFeePerGas')
        if base is None:
            raise RuntimeError('EIP-1559 fee data unavailable')
        tip = max(self.w3.eth.max_priority_fee, 1)
        tx.pop('gasPrice', None)
        tx['maxPriorityFeePerGas'] = tip
        tx['maxFeePerGas'] = base * 2 + tip
        return tx

    def settle(self):
        pending = self.state.get('pending')
        if not pending:
            return
        try:
            receipt = self.w3.eth.get_transaction_receipt(pending['hash'])
        except TransactionNotFound:
            raise RuntimeError('Saved transaction is unresolved. No replacement or new transaction will be sent. Check its hash and rerun when resolved.')
        gas_paid = receipt['gasUsed'] * receipt['effectiveGasPrice']
        self.state['last_tx_cost'] = dict(kind=pending['kind'],
                                          burn=pending['value'] if receipt['status'] == 1 else 0,
                                          gas=gas_paid)
        self.state['spent'] += gas_paid
        if receipt['status'] == 1:
            self.state['spent'] += pending['value']
            if pending['kind'] == 'deploy':
                self.state['miner'] = receipt['contractAddress']
                self.state['deploy_block'] = receipt['blockNumber']
                self.state['deploy_tx'] = pending['hash']
            elif pending['kind'] == 'burn':
                self.state['rounds'].append(pending['round'])
                known = set(self.state.get('claimed_rounds', []))
                known.update(pending.get('claims', []))
                self.state['claimed_rounds'] = sorted(known)
        self.state['pending'] = None
        if receipt['status'] != 1:
            self.state['halted'] = 'Transaction reverted; inspect before starting another session'
        self.save()
        if self.state.get('halted'):
            raise RuntimeError(self.state['halted'])

    @terminal_ui.transaction_activity
    def send(self, fn, kind, value=0, rid=None, claims=None):
        try:
            tx = self.prepare(fn, value)
        except ContractLogicError:
            if kind == 'burn' and self.state.get('genesis') is not None:
                now = self.w3.eth.get_block('latest')['timestamp']
                if (now - self.state['genesis']) // 999 != rid:
                    print('Round changed during RPC recovery; resynchronizing without sending.')
                    return None
            raise
        if kind == 'burn' and self.state.get('genesis') is not None:
            now = self.w3.eth.get_block('latest')['timestamp']
            if (now - self.state['genesis']) // 999 != rid:
                print('Round changed before signing; resynchronizing without sending.')
                return None
        balance = self.w3.eth.get_balance(self.address, 'pending')
        if not affordable(balance, self.state['cap'], self.state['spent'], value,
                          tx['gas'], tx['maxFeePerGas'], self.state['reserve']):
            print('STOP: remaining cap/balance cannot cover value + maximum gas + reserve.', flush=True)
            return False
        signed = self.account.sign_transaction(tx)
        tx_hash = Web3.to_hex(signed.hash)
        # Persist before broadcasting: even a timeout/crash cannot silently repeat a burn.
        self.state['pending'] = dict(hash=tx_hash, kind=kind, value=value, round=rid, claims=list(claims or []))
        self.save()
        print(f'Sending {kind}: {tx_hash}', flush=True)
        self.w3.eth.send_raw_transaction(signed.raw_transaction)
        print('Waiting for transaction confirmation (receipt checks every 5s).', flush=True)
        self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180, poll_latency=5)
        self.settle()
        return True

    def verify_deployment(self, miner):
        genesis = miner.functions.genesisTimestamp().call()
        token_address = miner.functions.token().call()
        vault_address = miner.functions.burnVault().call()
        receipt = self.w3.eth.get_transaction_receipt(self.state['deploy_tx'])
        tx = self.w3.eth.get_transaction(self.state['deploy_tx'])
        if (receipt['status'] != 1 or receipt['contractAddress'] != miner.address
                or receipt['blockNumber'] != self.state['deploy_block']
                or tx['from'] != self.address or tx['to'] is not None
                or bytes(tx['input']) != bytes.fromhex(self.bytecode.removeprefix('0x'))):
            raise RuntimeError('Deployment transaction does not match this wallet/build/session')
        verify_runtime(self.artifact, self.w3.eth.get_code(miner.address),
                       [int(token_address, 16), int(vault_address, 16), genesis])
        token_art = json.loads((ROOT / 'out/HyburnToken.sol/HyburnToken.json').read_text())
        vault_art = json.loads((ROOT / 'out/HypeBurnVault.sol/HypeBurnVault.json').read_text())
        verify_runtime(token_art, self.w3.eth.get_code(token_address), [int(miner.address, 16)])
        verify_runtime(vault_art, self.w3.eth.get_code(vault_address), [])
        token = self.w3.eth.contract(address=token_address, abi=token_art['abi'])
        if token.functions.MINTER().call() != miner.address or token.functions.decimals().call() != 9:
            raise RuntimeError('Token wiring mismatch')
        block = self.w3.eth.get_block(self.state['deploy_block'])
        if (genesis != block['timestamp'] + 999 or miner.functions.MIN_BURN().call() != MIN_BURN
                or miner.functions.START_DELAY().call() != 999 or miner.functions.ROUND_DURATION().call() != 999):
            raise RuntimeError('Genesis or mining constants mismatch')
        print('VERIFIED: Miner / Token / Vault runtime, immutables, deployment and genesis.', flush=True)
        return genesis, token_address, vault_address

    def unclaimed_rounds(self, miner):
        # Migrate old journals lazily; each confirmed claim survives interrupted scans.
        known = set(self.state.get('claimed_rounds', []))
        candidates = [r for r in self.state['rounds'] if r not in known]
        print(f'Checking {len(candidates)} uncached/unclaimed rounds; {len(known)} confirmed claims skipped.', flush=True)
        unclaimed = []
        for index, rid in enumerate(candidates, 1):
            print(f'Claim check {index}/{len(candidates)}: round {rid}', flush=True)
            if miner.functions.claimed(rid, self.address).call():
                known.add(rid)
                self.state['claimed_rounds'] = sorted(known)
                self.save()
            else:
                unclaimed.append(rid)
        return unclaimed

    def run(self):
        self.screen('READ-ONLY PREVIEW' if not self.args.execute else 'PREPARING')
        if not self.args.execute:
            if not self.state or not self.state.get('miner'):
                tx = self.prepare(self.factory.constructor())
                print(f"Deployment maximum gas cost: {hype(tx['gas'] * tx['maxFeePerGas'])} HYPE")
            print('No transaction sent. Fill private_key in the local JSON, then use --execute.')
            return
        label = 'Resume mining' if self.state and self.state.get('miner') else 'Deploy contracts and start mining'
        if not terminal_ui.choose_start(getattr(self.args, 'yes', False), label):
            print('Execution cancelled. No new transactions sent.')
            return
        if terminal_ui.current():
            terminal_ui.current().update(Mode="LIVE")
        ensure_config_untracked()
        self.account = load_signer(self.address, self.args.keystore)
        if not self.state:
            self.state = dict(wallet=self.address, chain=self.args.chain_id, build=self.fingerprint,
                              cap=self.w3.eth.get_balance(self.address), spent=0,
                              reserve=int(Decimal(self.args.reserve) * UNIT), rounds=[], pending=None,
                              commit=self.source_commit)
            self.save()
        first_deployment = not self.state.get('miner')
        self.settle()
        if self.state.get('halted'):
            raise RuntimeError(self.state['halted'])
        self.screen('READY')
        # The start choice above precedes signing and pending-transaction recovery.
        if not self.state.get('miner'):
            if not self.send(self.factory.constructor(), 'deploy'):
                return
        miner = self.w3.eth.contract(address=self.state['miner'], abi=self.artifact['abi'])
        print('Verifying deployed contracts and chain parameters; RPC reads are rate-limited.', flush=True)
        genesis, token_address, vault_address = self.verify_deployment(miner)
        self.state.update(genesis=genesis, token=token_address, vault=vault_address)
        self.save()
        if first_deployment or getattr(self.args, 'refresh_website', False):
            # Values are public deployment facts; output remains outside the public build.
            env = {'MINER': self.state['miner'], 'TOKEN': self.state['token'], 'VAULT': self.state['vault'],
                   'DEPLOY_BLOCK': self.state['deploy_block'], 'DEPLOY_TX': self.state['deploy_tx'], 'GENESIS': genesis,
                   'COMMIT': self.state['commit'],
                   'CHAIN_ID': self.args.chain_id}
            self.state_path.with_suffix('.public.env').write_text(''.join(f'NEXT_PUBLIC_{k}={v}\n' for k,v in env.items()))
            update_website(env)
            print('Website deployment facts updated: web/.env.local (not published).', flush=True)
            print('Building local website preview; Vercel is not invoked.', flush=True)
            try:
                subprocess.run(['npm', 'exec', '--', 'next', 'build', '--webpack'],
                               cwd=ROOT / 'web', check=True, timeout=120, capture_output=terminal_ui.current() is not None)
            except (subprocess.SubprocessError, OSError) as error:
                print(f'Local website build did not finish: {error}. Facts saved; mining will continue.', flush=True)
        else:
            print('Resuming mining; local website update/build skipped.', flush=True)
        dashboard = terminal_ui.current()
        if dashboard:
            dashboard.update(**{'Token CA': token_address})
            dashboard.attach_insights(rpc=self.args.rpc, chain=self.args.chain_id,
                                      miner=self.state['miner'], account=self.address,
                                      genesis=genesis, duration=999, deploy_block=self.state['deploy_block'],
                                      send_window=0)
        claim_candidates = self.unclaimed_rounds(miner)
        while True:
            now = self.w3.eth.get_block('latest')['timestamp']
            dashboard = terminal_ui.current()
            if dashboard:
                dashboard.sync_chain(now, genesis, 999)
            if now < genesis:
                delay = max(1, genesis - now)
                print(f'Genesis in {delay}s. Local wait; no background RPC polling.', flush=True)
                wait_locally(delay, 'Waiting for genesis')
                continue
            rid = (now - genesis) // 999
            if rid not in self.state['rounds'] and miner.functions.burned(rid, self.address).call() == 0:
                if miner.functions.miningFinished().call():
                    print('Mining schedule complete.')
                    return
                claims = [r for r in claim_candidates if r < rid]
                sent = self.send(miner.functions.burnAndClaim(rid, claims), 'burn', MIN_BURN, rid, claims)
                if sent is None:
                    continue
                if not sent:
                    print('Unclaimed rewards remain available via the standard CLI.')
                    return
                claim_candidates = [rid]
                self.screen(f'ROUND {rid} CONFIRMED')
            # Synchronize once after submission; sleep locally until the next round.
            chain_now = self.w3.eth.get_block('latest')['timestamp']
            if dashboard:
                dashboard.sync_chain(chain_now, genesis, 999)
            target = genesis + (rid + 1) * 999
            delay = max(1, target - chain_now)
            print(f'Next burn: round {rid + 1}, about {delay}s. Sleeping locally; Ctrl-C to stop.', flush=True)
            wait_locally(delay, f'Next burn: round {rid + 1}; no RPC requests')


def main():
    config = read_local_config()
    config.pop('private_key', None)
    def local_path(value):
        path = Path(value).expanduser()
        return str(path if path.is_absolute() else ROOT / path)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rpc', default=config.get('rpc', 'https://rpc.hypurrscan.io'))
    p.add_argument('--wallet', default=config.get('wallet', WALLET))
    p.add_argument('--chain-id', type=int, default=config.get('chain_id', 999))
    p.add_argument('--state', default=local_path(config.get('state_file', 'output/developer-deploy/session.json')))
    p.add_argument('--reserve', default=str(config.get('reserve_hype', '0.001')), help='HYPE left untouched; fixed on first execution')
    p.add_argument('--keystore', help='Optional encrypted keystore instead of private_key in local JSON')
    p.add_argument('--plain', action='store_true', help='Disable the interactive terminal dashboard')
    p.add_argument('--yes', action='store_true', help='Skip the start choice for intentional unattended execution')
    p.add_argument('--execute', action='store_true')
    p.add_argument('--refresh-website', action='store_true', help='With --execute, refresh local website facts and build on resume; never publishes')
    args = p.parse_args()
    reserve = Decimal(args.reserve)
    if not reserve.is_finite() or reserve < 0 or reserve * UNIT != int(reserve * UNIT):
        p.error('--reserve must be a non-negative HYPE amount with at most 18 decimals')
    print('Checking local contract build...', flush=True)
    subprocess.run(['forge', 'build', '--quiet'], cwd=ROOT, check=True)
    try:
        with terminal_ui.Dashboard(enabled=not args.plain, title='HYBURN / DEPLOY & MINE'):
            Console(args).run()
    except KeyboardInterrupt:
        print('\nStopped. Pending transactions may still confirm; rerun with the same state file.')
    except Exception as error:
        raise SystemExit(f'STOP: {error}')


if __name__ == '__main__':
    main()
