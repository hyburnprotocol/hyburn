"""Optional, display-only Hyperliquid spot midpoint feed.

No keys, wallet addresses, mining RPC, or transaction methods are used. Prices
are informational USDC midpoints, not USD valuations or executable quotes.
"""
from collections import deque
import json
import math
import os
import threading
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler

INFO_URL = 'https://api.hyperliquid.xyz/info'
WS_URL = 'wss://api.hyperliquid.xyz/ws'
MAX_BYTES = 2_000_000
STALE_AFTER = 45
POLL_INTERVAL = 30


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Market service redirects are disabled')


def request(payload):
    req = Request(INFO_URL, data=json.dumps(payload).encode(),
                  headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
    with build_opener(NoRedirect).open(req, timeout=5) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Market response too large')
    return json.loads(raw)


def resolve_pair(meta):
    """Resolve unique spot token indices; never substitute perpetual HYPE."""
    if not isinstance(meta, dict):
        raise ValueError('Invalid spot metadata')
    tokens = meta.get('tokens', [])
    def token_index(name):
        matches = [t['index'] for t in tokens if isinstance(t, dict)
                   and t.get('name') == name]
        if len(matches) != 1:
            raise ValueError('Spot token unavailable or ambiguous')
        return matches[0]
    wanted = [token_index('HYPE'), token_index('USDC')]
    matches = [p for p in meta.get('universe', []) if isinstance(p, dict)
               and p.get('tokens') == wanted]
    if len(matches) != 1:
        raise ValueError('HYPE/USDC spot pair unavailable or ambiguous')
    pair = matches[0]
    index = pair.get('index')
    if not isinstance(index, int) or index < 0:
        raise ValueError('Invalid spot pair index')
    # Spot API uses @index except the legacy PURR/USDC pair at index zero.
    if index == 0:
        raise ValueError('Unexpected HYPE spot pair index')
    return '@' + str(index)


def positive_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


class MarketFeed:
    def __init__(self, chain=999, fetch=request, connect=None, clock=time.monotonic):
        self.enabled = str(chain) == '999' and os.environ.get('HYBURN_MARKET_FEED', '1') != '0'
        self.fetch, self.connect, self.clock = fetch, connect, clock
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.worker = None
        self.price = self.updated = self.first_price = None
        self.history = deque(maxlen=60)
        self.last_sample = None
        self.status = 'connecting' if self.enabled else 'disabled'

    def start(self):
        with self.lock:
            if not self.enabled or self.closed.is_set() or self.worker is not None:
                return
            self.worker = threading.Thread(target=self._run, name='hyburn-market', daemon=True)
            self.worker.start()

    def stop(self):
        # Do not delay transaction shutdown on an optional network worker.
        self.closed.set()
        with self.lock:
            if self.enabled:
                self.status = 'stopped'

    def snapshot(self):
        with self.lock:
            age = None if self.updated is None else max(0, self.clock() - self.updated)
            return {'pair': 'HYPE/USDC', 'source': 'Hyperliquid spot mid',
                    'price': self.price, 'age': age,
                    'stale': age is None or age > STALE_AFTER,
                    'status': self.status, 'history': tuple(self.history),
                    'session_change_pct': None if self.first_price is None else
                    (self.price / self.first_price - 1) * 100}

    def _record(self, value):
        price = positive_number(value)
        if price is None or self.closed.is_set():
            return False
        now = self.clock()
        with self.lock:
            self.price, self.updated, self.status = price, now, 'live'
            if self.first_price is None:
                self.first_price = price
            # Actual received observations only; at most one sample per five seconds.
            if self.last_sample is None or now - self.last_sample >= 5:
                self.history.append(price)
                self.last_sample = now
        return True

    def _message(self, message, coin):
        if not isinstance(message, dict) or message.get('channel') not in ('activeAssetCtx', 'activeSpotAssetCtx'):
            return False
        data = message.get('data')
        if not isinstance(data, dict) or data.get('coin') != coin:
            return False
        ctx = data.get('ctx')
        if not isinstance(ctx, dict):
            return False
        # A missing midpoint must not silently become a mark price.
        return self._record(ctx.get('midPx'))

    def _poll(self, coin):
        mids = self.fetch({'type': 'allMids'})
        if not isinstance(mids, dict) or not self._record(mids.get(coin)):
            raise ValueError('Spot midpoint unavailable')

    def _stream(self, coin, connect):
        with connect(WS_URL, open_timeout=5, close_timeout=1, max_size=MAX_BYTES) as ws:
            ws.send(json.dumps({'method': 'subscribe',
                               'subscription': {'type': 'activeAssetCtx', 'coin': coin}}))
            last_valid = last_ping = self.clock()
            while not self.closed.is_set():
                try:
                    raw = ws.recv(timeout=1)
                except TimeoutError:
                    raw = None
                if raw is not None and self._message(json.loads(raw), coin):
                    last_valid = self.clock()
                now = self.clock()
                if now - last_ping >= 20:
                    ws.send('{"method":"ping"}')
                    last_ping = now
                if now - last_valid > STALE_AFTER:
                    raise TimeoutError('Spot stream stale')

    def _run(self):
        connect = self.connect
        if connect is None:
            try:
                from websockets.sync.client import connect
            except ImportError:
                connect = None
        coin = None
        retry = 5
        while not self.closed.is_set():
            try:
                if coin is None:
                    coin = resolve_pair(self.fetch({'type': 'spotMeta'}))
                if connect is None:
                    self._poll(coin)
                    retry = 5
                    self.closed.wait(POLL_INTERVAL)
                else:
                    self._stream(coin, connect)
            except Exception:
                # Never forward upstream errors into a terminal or the mining engine.
                with self.lock:
                    if not self.closed.is_set():
                        self.status = 'retrying'
                self.closed.wait(retry)
                retry = min(120, retry * 2)
        with self.lock:
            self.status = 'stopped'
