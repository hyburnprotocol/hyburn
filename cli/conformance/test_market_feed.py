"""The optional spot footer must not mislabel a perpetual or block mining."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from market_feed import MarketFeed, resolve_pair

META = {'tokens': [{'name': 'HYPE', 'index': 150, 'isCanonical': False},
                   {'name': 'USDC', 'index': 0, 'isCanonical': True}],
        'universe': [{'name': '@107', 'index': 107, 'tokens': [150, 0]}]}


class MarketFeedTests(unittest.TestCase):
    def test_metadata_maps_spot_and_rejects_ambiguous_tokens(self):
        self.assertEqual(resolve_pair(META), '@107')
        with self.assertRaises(ValueError):
            resolve_pair({**META, 'tokens': META['tokens'] + [{'name': 'HYPE', 'index': 900}]})
        with self.assertRaises(ValueError):
            resolve_pair({**META, 'universe': [{'index': 1, 'tokens': [0, 150]}]})

    def test_only_matching_spot_context_updates_price(self):
        feed = MarketFeed()
        def msg(coin, px):
            return {'channel': 'activeSpotAssetCtx', 'data': {'coin': coin, 'ctx': {'midPx': px}}}
        self.assertFalse(feed._message(msg('HYPE', '900'), '@107'))
        self.assertTrue(feed._message(msg('@107', '25'), '@107'))
        self.assertEqual(feed.snapshot()['price'], 25)
        for bad in (None, True, 'nan', 'inf', '-3', '0', '\x1b[31m'):
            self.assertFalse(feed._message(msg('@107', bad), '@107'))
        self.assertEqual(feed.snapshot()['price'], 25)

    def test_snapshot_never_fetches_and_stale_history_stays_honest(self):
        now = [0]
        feed = MarketFeed(fetch=lambda _: self.fail('snapshot fetched network'), clock=lambda: now[0])
        self.assertTrue(feed.snapshot()['stale'])
        feed._record(10)
        now[0] = 2
        feed._record(11)
        self.assertEqual(feed.snapshot()['history'], (10,))
        self.assertAlmostEqual(feed.snapshot()['session_change_pct'], 10)
        now[0] = 50
        self.assertTrue(feed.snapshot()['stale'])
        self.assertEqual(feed.snapshot()['age'], 48)
        for i in range(70):
            now[0] += 5
            feed._record(20 + i)
        self.assertEqual(len(feed.snapshot()['history']), 60)

    def test_disabled_feed_and_stop_are_safe(self):
        feed = MarketFeed(chain=31337, fetch=lambda _: self.fail('disabled feed fetched'))
        feed.start()
        self.assertIsNone(feed.worker)
        self.assertEqual(feed.snapshot()['status'], 'disabled')
        with patch.dict(os.environ, {'HYBURN_MARKET_FEED': '0'}):
            self.assertFalse(MarketFeed().enabled)
        feed = MarketFeed()
        feed.stop()
        self.assertFalse(feed._record(10))
        feed.start()
        self.assertIsNone(feed.worker)

    def test_poll_does_not_fall_back_to_perpetual(self):
        feed = MarketFeed(fetch=lambda _: {'HYPE': '88'})
        with self.assertRaises(ValueError):
            feed._poll('@107')
        self.assertIsNone(feed.snapshot()['price'])

    def test_disconnect_reconnect_resets_backoff_and_preserves_price(self):
        now = [0]
        waits = []
        calls = []
        feed = MarketFeed(fetch=lambda payload: META if payload['type'] == 'spotMeta' else {},
                          connect=lambda *a, **k: None, clock=lambda: now[0])
        class Event:
            stopped = False
            def is_set(self):
                return self.stopped
            def set(self):
                self.stopped = True
            def wait(self, delay):
                state = feed.snapshot()
                self_outer.assertEqual(state['retry_in'], delay)
                waits.append(delay)
                now[0] += delay
                if len(waits) == 8:
                    self.set()
        self_outer = self
        feed.closed = Event()
        def stream(coin, connect):
            calls.append(coin)
            if len(calls) in (1, 7):
                feed._record(25 if len(calls) == 1 else 26)
            raise OSError('network disconnected')
        feed._stream = stream
        feed._run()
        self.assertEqual(waits, [2, 4, 8, 16, 30, 30, 2, 4])
        self.assertEqual(set(calls), {'@107'})
        self.assertEqual(feed.snapshot()['price'], 26)
        self.assertEqual(feed.snapshot()['status'], 'stopped')
        self.assertIsNone(feed.snapshot()['retry_in'])

    def test_blocked_websocket_uses_throttled_rest_fallback(self):
        now = [0]
        polls = []
        def fetch(payload):
            if payload['type'] == 'spotMeta':
                return META
            polls.append(now[0])
            return {'@107': '28', 'HYPE': '999'}
        def connect(*args, **kwargs):
            raise OSError('blocked')
        feed = MarketFeed(fetch=fetch, connect=connect, clock=lambda: now[0])
        def wait(delay):
            now[0] += delay
            if now[0] > 65:
                feed.stop()
        with patch.object(feed.closed, 'wait', side_effect=wait):
            feed._run()
        self.assertGreaterEqual(len(polls), 2)
        self.assertTrue(all(b - a >= 30 for a, b in zip(polls, polls[1:])))
        self.assertEqual(feed.snapshot()['price'], 28)
        self.assertEqual(feed.snapshot()['transport'], 'rest')

    def test_stream_accepts_reconnected_spot_and_exits_on_stop(self):
        feed = MarketFeed()
        sent = []
        class Socket:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def send(self, value):
                sent.append(json.loads(value))
            def recv(self, timeout):
                if feed.snapshot()['price'] is not None:
                    feed.stop()
                    raise TimeoutError()
                return json.dumps({'channel': 'activeSpotAssetCtx',
                    'data': {'coin': '@107', 'ctx': {'midPx': '29'}}})
        feed._stream('@107', lambda *a, **k: Socket())
        self.assertEqual(sent[0]['subscription']['coin'], '@107')
        self.assertEqual(feed.snapshot()['price'], 29)
        self.assertEqual(feed.snapshot()['transport'], 'websocket')


if __name__ == '__main__':
    unittest.main()
