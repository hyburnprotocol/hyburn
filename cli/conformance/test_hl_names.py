"""Name lookup must remain optional, verified, cached and display-only."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from hl_names import Names, NoRedirect
from insight_table import InsightTable
from terminal_ui import Dashboard

A = '0x' + 'ab' * 20
B = '0x' + 'cd' * 20


class NameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'HYBURN_HL_NAMES': '1', 'HYBURN_HOME': self.tmp.name})
        self.env.start()
        self.calls = []

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def fetch(self, path):
        self.calls.append(path)
        return {'primaryName': 'hyburn.hl'} if 'primary_name' in path else {'address': A.upper().replace('0X', '0x')}

    def test_forward_confirmation_and_disk_cache(self):
        names = Names(fetch=self.fetch)
        self.assertEqual(names.lookup(A), 'hyburn.hl')
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(Names(fetch=self.fetch).lookup(A), 'hyburn.hl')
        self.assertEqual(len(self.calls), 2)

    def test_mismatch_and_missing_cached(self):
        def wrong(path):
            self.calls.append(path)
            return {'primaryName': 'hyburn.hl'} if 'primary_name' in path else {'address': B}
        names = Names(fetch=wrong)
        self.assertIsNone(names.lookup(A))
        self.assertIsNone(names.lookup(A))
        self.assertEqual(len(self.calls), 2)

    def test_untrusted_terminal_names_rejected(self):
        for bad in ['evil\x1b[2J.hl', 'a\nb.hl', '\u202eevil.hl', 'hуburn.hl', '../evil.hl', 'a'*64+'.hl']:
            with self.subTest(bad=bad):
                names = Names(fetch=lambda _: {'primaryName': bad}, home=Path(self.tmp.name)/str(len(bad)))
                self.assertIsNone(names.lookup(A))

    def test_disabled_and_other_chain_no_requests(self):
        self.assertIsNone(Names(998, fetch=self.fetch).lookup(A))
        with patch.dict(os.environ, {'HYBURN_HL_NAMES': '0'}):
            self.assertIsNone(Names(fetch=self.fetch).get(A))
        self.assertEqual(self.calls, [])

    def test_failure_cooldown_no_retry_storm(self):
        def fail(path):
            self.calls.append(path)
            raise TimeoutError()
        names = Names(fetch=fail)
        self.assertIsNone(names.lookup(A))
        self.assertIsNone(names.lookup(B))
        self.assertEqual(len(self.calls), 1)

    def test_expired_and_corrupt_cache_revalidated(self):
        names = Names(fetch=self.fetch)
        names.lookup(A)
        path = names.root / (A+'.json')
        data = json.loads(path.read_text())
        data['expires'] = 0
        path.write_text(json.dumps(data))
        self.assertEqual(Names(fetch=self.fetch).lookup(A), 'hyburn.hl')
        path.write_text('not json')
        self.assertEqual(Names(fetch=self.fetch).lookup(A), 'hyburn.hl')
        self.assertEqual(len(self.calls), 6)

    def test_get_is_async_and_deduplicated(self):
        release = threading.Event()
        def slow(path):
            release.wait(1)
            return self.fetch(path)
        names = Names(fetch=slow)
        start = time.monotonic()
        for _ in range(20):
            self.assertIsNone(names.get(A))
        self.assertLess(time.monotonic()-start, .1)
        self.assertEqual(len(names.pending), 1)
        release.set()
        deadline = time.monotonic()+2
        while names.cached(A) is None and time.monotonic()<deadline:
            time.sleep(.01)
        names.close()
        self.assertEqual(names.cached(A), 'hyburn.hl')
        self.assertEqual(len(self.calls), 2)

    def test_privacy_hides_names_and_addresses(self):
        names = Names(fetch=self.fetch)
        names.lookup(A)
        ui = Dashboard(enabled=False)
        ui.names = names
        self.assertIn('hyburn.hl', ui.display_field('Wallet', A))
        ui.privacy = True
        self.assertEqual(ui.display_field('Wallet', A), '[hidden]')
        table = InsightTable(3, A)
        table.names = names
        table.set_records([dict(account=A, burned=1, txs=1, share='100%')], A)
        normal = '\n'.join(table.render(78, 10))
        self.assertIn('hyburn.hl', normal)
        self.assertIn(A, normal)
        hidden = '\n'.join(table.render(78, 10, privacy=True))
        self.assertNotIn('hyburn.hl', hidden)
        self.assertNotIn(A, hidden)
        self.assertEqual(table.identity(table.view()[0]), A)

    def test_redirect_rejected(self):
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid/')

    def test_read_only_home_keeps_in_memory_result(self):
        names = Names(fetch=self.fetch)
        with patch.object(Path, 'mkdir', side_effect=PermissionError()):
            self.assertEqual(names.lookup(A), 'hyburn.hl')
        self.assertEqual(names.cached(A), 'hyburn.hl')

    def test_wallet_frame_keeps_full_address_and_name_search(self):
        names = Names(fetch=self.fetch)
        names.lookup(A)
        ui = Dashboard(enabled=False)
        ui.names = names
        ui.update(Wallet=A, Chain=999)
        ui.page = 1
        frame = ui.frame(80, 24)
        self.assertIn(A, frame)
        self.assertIn('hyburn.hl', frame)
        ui.privacy = True
        self.assertNotIn(A, ui.frame(80, 24))
        self.assertNotIn('hyburn.hl', ui.frame(80, 24))
        table = InsightTable(3, A)
        table.names = names
        table.set_records([dict(account=A, burned=1, txs=1, share='100%')], A)
        table.query = 'hyburn.hl'
        self.assertEqual(table.view()[0]['account'], A)


if __name__ == '__main__':
    unittest.main()
