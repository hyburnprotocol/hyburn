"""Durable public-miner journal. Shared JSON format across all four clients."""
import json
import os
from pathlib import Path
import socket
import tempfile
from web3 import Web3
from web3.exceptions import TransactionNotFound


def home():
    return Path(os.environ.get('HYBURN_HOME', Path.home() / '.hyburn'))


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        d = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(d)
        finally:
            os.close(d)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def wallet_lock(account):
    # OS-owned loopback lease; crashes release it, collisions fail closed.
    lease = socket.socket()
    try:
        lease.bind(('127.0.0.1', 32768 + int(account[-4:], 16) % 20000))
        lease.listen(1)
    except OSError:
        lease.close()
        raise RuntimeError('Wallet already in use or local session lock unavailable; stop the other miner first.') from None
    return lease


class Session:
    def __init__(self, chain, miner, account):
        try:
            self.lock = wallet_lock(account)
        except RuntimeError as error:
            raise SystemExit(str(error)) from None
        self.path = home() / f'{chain}-{miner.lower()}-{account.lower()}.session.json'
        self.state = dict(v=1, identity=f'{chain}:{miner.lower()}:{account.lower()}', settings={}, spent='0', gas='0', burns=0, last_round=-1, pending=None)
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text())
                if not (saved['v'] == 1 and saved['identity'] == self.state['identity']
                        and isinstance(saved['settings'], dict)
                        and int(saved['spent']) >= 0 and int(saved['gas']) >= 0
                        and type(saved['burns']) is int and saved['burns'] >= 0
                        and type(saved['last_round']) is int and saved['last_round'] >= -1
                        and 'pending' in saved
                        and isinstance(saved.get('finishing', False), bool)):
                    raise ValueError('Invalid session schema')
                self.state = saved
            except Exception:
                raise SystemExit('Invalid session file; restore its backup. Refusing to reset the budget.') from None
        self.save()

    def save(self):
        atomic_json(self.path, self.state)

    def configure(self, supplied, fresh=False):
        if self.state['pending']:
            raise SystemExit('Resolve the saved transaction before changing the session.')
        previous = self.state['settings']
        settings = dict(amount='', budget='', max_cost='', at='30', rounds='', reserve=str(10**15))
        if not fresh:
            settings.update(previous)
        settings.update({k: v for k, v in supplied.items() if v is not None})
        if not settings['amount']:
            raise SystemExit('First run needs --amount. Later runs can use mine with no options.')
        try:
            if not (int(settings['amount']) > 0 and 0 < int(settings['at']) < 999 and int(settings['reserve']) >= 0):
                raise ValueError()
            for key in ('budget', 'max_cost', 'rounds'):
                if settings[key]:
                    if int(settings[key]) < (1 if key == 'rounds' else 0):
                        raise ValueError()
            if not settings['budget']:
                if not settings['rounds']:
                    raise SystemExit('First session needs --budget or --rounds; gas is additional.')
                settings['budget'] = str(int(settings['amount']) * int(settings['rounds']))
        except ValueError:
            raise SystemExit('Invalid mining settings; amounts must be nonnegative and --at must be 1..998.') from None
        if previous and not fresh and settings != previous:
            raise SystemExit('Saved mining settings differ. Use --new-session with the full new settings to authorize a new budget.')
        if fresh:
            atomic_json(self.path.with_suffix('.previous.json'), self.state)
            self.state.update(spent='0', gas='0', burns=0, finishing=False)
        self.state['settings'] = settings
        self.save()
        return settings

    def prepare(self, raw, value, rid, mining):
        if self.state['pending']:
            raise SystemExit('Unresolved transaction; refusing another send.')
        self.state['pending'] = dict(hash=Web3.to_hex(Web3.keccak(raw)), raw=Web3.to_hex(raw), value=str(value), round=rid, mining=mining)
        self.save()  # Must be durable BEFORE broadcast.

    def settle(self, receipt):
        p = self.state['pending']
        if not p or receipt['transactionHash'].hex().removeprefix('0x').lower() != p['hash'].removeprefix('0x').lower():
            raise SystemExit('Receipt does not match saved transaction.')
        self.state['gas'] = str(int(self.state['gas']) + receipt['gasUsed'] * receipt['effectiveGasPrice'])
        if receipt['status'] == 1 and int(p['value']) > 0:
            self.state['last_round'] = max(self.state['last_round'], p['round'])
            if p['mining']:
                self.state['spent'] = str(int(self.state['spent']) + int(p['value']))
                self.state['burns'] += 1
        self.state['pending'] = None
        self.save()

    def recover(self, w3):
        p = self.state['pending']
        if not p:
            return
        print(f"Recovering saved transaction {p['hash']}; no new transaction will be signed.", flush=True)
        try:
            rc = w3.eth.get_transaction_receipt(p['hash'])
        except TransactionNotFound:
            raw = bytes.fromhex(p['raw'].removeprefix('0x'))
            if Web3.to_hex(Web3.keccak(raw)) != p['hash']:
                raise SystemExit('Invalid saved transaction; refusing broadcast.')
            try:
                w3.eth.send_raw_transaction(raw)  # Identical signed bytes and nonce.
            except Exception:
                pass  # Already known / nonce used: receipt remains authoritative.
            rc = w3.eth.wait_for_transaction_receipt(p['hash'], timeout=180, poll_latency=5)
        self.settle(rc)
        print('Saved transaction confirmed.' if rc['status'] else 'Saved transaction reverted; gas recorded.', flush=True)
