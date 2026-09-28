"""Optional public display names. Never used for signing or account identity.

API contract and public fallback key published by HLnames/use-hln-api.
Only forward-confirmed primary names are displayed. No wallet secrets needed.
"""
import json
import os
from pathlib import Path
import queue
import re
import tempfile
import threading
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler

API = 'https://api.hlnames.xyz'
PUBLIC_KEY = 'NILB2EY-R4LUDOA-WN5G5JQ-KHAQOLA'
ADDRESS = re.compile(r'0x[0-9a-fA-F]{40}\Z')
# Restrict terminal labels to unambiguous printable ASCII. Other names fall back
# to addresses rather than accepting escapes, bidi controls or lookalikes.
NAME = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.hl\Z')
TTL = 3600
NEGATIVE_TTL = 300
MAX_BYTES = 16384


def enabled(chain):
    return str(chain) == '999' and os.environ.get('HYBURN_HL_NAMES', '1') != '0'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Name service redirects are disabled')


def request(path):
    req = Request(API + path, headers={'Accept': 'application/json',
        'X-API-Key': os.environ.get('HLN_API_KEY') or PUBLIC_KEY})
    with build_opener(NoRedirect).open(req, timeout=2) as response:
        # Do not accept redirects to other hosts.
        if not response.url.startswith(API + '/'):
            raise ValueError('Unexpected name service host')
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Name response too large')
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError('Invalid name response')
    return result


class Names:
    def __init__(self, chain=999, fetch=request, home=None):
        self.enabled = enabled(chain)
        self.fetch = fetch
        self.root = Path(home or os.environ.get('HYBURN_HOME', Path.home() / '.hyburn')) / 'names' / '999'
        self.entries = {}
        self.pending = set()
        self.queue = queue.Queue(maxsize=64)
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.worker = None
        self.cooldown = 0

    def cached(self, address):
        if not self.enabled or not ADDRESS.fullmatch(address):
            return None
        address = address.lower()
        with self.lock:
            if address not in self.entries:
                try:
                    path = self.root / (address + '.json')
                    if path.stat().st_size > MAX_BYTES:
                        raise ValueError('Cache too large')
                    entry = json.loads(path.read_text())
                    name, expires = entry['name'], entry['expires']
                    if entry.get('version') != 1 or entry.get('address') != address:
                        raise ValueError('Cache mismatch')
                    if name is not None and (not isinstance(name, str) or not NAME.fullmatch(name)):
                        raise ValueError('Invalid label')
                    if not isinstance(expires, (float, int)) or not time.time() < expires <= time.time() + TTL:
                        raise ValueError('Expired cache')
                    self.entries[address] = (name, expires)
                except (OSError, ValueError, KeyError, TypeError):
                    self.entries[address] = (None, 0)
            name, expires = self.entries[address]
            return name if time.time() < expires else None

    def lookup(self, address):
        """Bounded synchronous lookup for short-lived read-only commands."""
        if not self.enabled or not ADDRESS.fullmatch(address):
            return None
        address = address.lower()
        self.cached(address)
        with self.lock:
            name, expires = self.entries[address]
            if time.time() < expires:
                return name
        if time.monotonic() < self.cooldown:
            return None
        name = None
        try:
            value = self.fetch('/resolve/primary_name/' + address).get('primaryName')
            if isinstance(value, str) and NAME.fullmatch(value):
                resolved = self.fetch('/resolve/address/' + value).get('address', '')
                if isinstance(resolved, str) and resolved.lower() == address:
                    name = value
        except Exception:
            # One failed lookup pauses the entire optional service; no retry loop.
            self.cooldown = time.monotonic() + 60
        expires = time.time() + (TTL if name else NEGATIVE_TTL)
        with self.lock:
            self.entries[address] = (name, expires)
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, tmp = tempfile.mkstemp(dir=self.root, prefix='.name-')
            try:
                with os.fdopen(fd, 'w') as out:
                    json.dump(dict(version=1, address=address, name=name, expires=expires), out)
                os.replace(tmp, self.root / (address + '.json'))
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except OSError:
            pass  # Read-only home must never prevent mining.
        return name

    def get(self, address):
        """Return immediately; schedule at most one lookup per visible address."""
        name = self.cached(address)
        if not self.enabled or not ADDRESS.fullmatch(address):
            return name
        address = address.lower()
        with self.lock:
            if (self.closed.is_set() or address in self.pending or
                    self.entries[address][1] > time.time() or time.monotonic() < self.cooldown):
                return name
            try:
                self.queue.put_nowait(address)
            except queue.Full:
                return name
            self.pending.add(address)
            if self.worker is None:
                self.worker = threading.Thread(target=self._run, daemon=True, name='hl-names')
                self.worker.start()
        return name

    def _run(self):
        while not self.closed.is_set():
            try:
                address = self.queue.get(timeout=.2)
            except queue.Empty:
                continue
            self.lookup(address)
            with self.lock:
                self.pending.discard(address)
            # At most one address per second (two HTTP requests if named).
            if self.closed.wait(1):
                return

    def close(self):
        self.closed.set()


def announce(address, chain, background=True):
    """Plain output retains the full address; lookup failures stay silent."""
    def run():
        name = Names(chain).lookup(address)
        if name:
            print(f'Wallet name    {name} ({address})', flush=True)
    if enabled(chain):
        if background:
            threading.Thread(target=run, daemon=True, name='hl-name-label').start()
        else:
            run()


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 3:
        announce(sys.argv[1], sys.argv[2], background=False)
