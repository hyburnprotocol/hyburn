"""Offline UI acceptance checks: honest clocks, clear gates, and safe sharing."""
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
import terminal_ui as ui


class TerminalDesignTests(unittest.TestCase):
    def dashboard(self, engine='python'):
        dashboard = ui.Dashboard(False)
        dashboard.update(Engine=engine, Mode='DRY RUN', **{
            'Burn / round': '0.000999000 HYPE + gas',
            'Burn budget': '0.009990000 HYPE (gas extra)',
            'Burn spending': '0.001998000 HYPE',
            'Round (last read)': '2',
            'Session burns': '2',
            'Send window': '30s before round end',
        })
        return dashboard

    def test_animation_uses_local_clock_without_network_or_confirming_new_round(self):
        dashboard = self.dashboard()
        with patch.object(ui.time, 'monotonic', return_value=100):
            dashboard.sync_chain(3990, 1000, 999)
        before = dict(dashboard.fields)
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('UI made a network request')):
            with patch.object(ui.time, 'monotonic', return_value=101):
                early = dashboard.frame(100, 30)
            with patch.object(ui.time, 'monotonic', return_value=10000):
                late = dashboard.frame(100, 30)
                clock = dashboard.countdown().lower()
        self.assertNotEqual(early, late)
        self.assertIn('awaiting chain confirmation', clock)
        self.assertEqual(dashboard.fields, before)
        self.assertEqual(dashboard.fields['Round (last read)'], '2')

    def test_all_engine_overviews_show_actual_mode_and_burn_amount(self):
        for engine in ('python', 'node', 'go', 'rust'):
            with self.subTest(engine=engine):
                frame = self.dashboard(engine).frame(80, 24)
                self.assertIn('DRY RUN', frame)
                self.assertIn('0.000999000', frame)
                self.assertIn(engine, frame.lower())
                self.assertIn('gas', frame.lower())

    def test_start_navigation_never_releases_gate_and_decline_is_final(self):
        dashboard = self.dashboard()
        ui.preview_start(dashboard, ['mine', '--amount', '0.000999', '--budget', '0.00999'])
        dashboard.awaiting_start = True
        finish = MagicMock()
        dashboard.finish_callback = finish
        for key in ('2', '3', '4', '5', '6', '7', '?', 'v', 'F', '\t'):
            dashboard.handle_key(key)
            self.assertIsNone(dashboard.start_choice)
        finish.assert_not_called()
        dashboard.handle_key('q')
        dashboard.handle_key('s')
        self.assertFalse(dashboard.start_choice)

    def test_privacy_covers_status_name_logs_and_private_fields_on_every_page(self):
        dashboard = self.dashboard()
        address = '0x' + '12' * 20
        dashboard.names = MagicMock()
        dashboard.names.get.return_value = 'private-wallet.hl'
        dashboard.update(Wallet=address, **{'Balance (snapshot)': '7.123456789 HYPE'})
        dashboard.log('private-wallet.hl ' + address + ' 7.123456789 HYPE')
        dashboard.status = lambda: 'sending for private-wallet.hl ' + address
        dashboard.privacy = True
        for page in range(8):
            dashboard.page = page
            for width, height in ((40, 12), (64, 20), (80, 24), (120, 40)):
                with self.subTest(page=page, size=(width, height)):
                    frame = dashboard.frame(width, height)
                    self.assertLessEqual(len(frame.splitlines()), height)
                    self.assertTrue(all(len(line) < width for line in frame.splitlines()))
                    for secret in (address, 'private-wallet.hl', '7.123456789'):
                        self.assertNotIn(secret, frame)

    def test_small_terminal_does_not_claim_dry_run_is_mining(self):
        dashboard = self.dashboard()
        frame = dashboard.frame(60, 18)
        self.assertNotIn('Mining continues', frame)
        self.assertIn('DRY RUN', frame)

    def test_no_color_output_keeps_state_and_is_escape_free(self):
        dashboard = self.dashboard()
        dashboard.color = False
        frame = dashboard.styled_frame(80, 24)
        self.assertNotIn('\x1b', frame)
        self.assertIn('DRY RUN', frame)

    def test_pre_genesis_does_not_display_a_mining_round_or_burn_progress(self):
        dashboard = self.dashboard()
        with patch.object(ui.time, 'monotonic', return_value=100):
            dashboard.sync_chain(900, 1000, 999)
        with patch.object(ui.time, 'monotonic', return_value=150):
            progress = '\n'.join(dashboard.progress_rows(100))
        self.assertIn('GENESIS', progress)
        self.assertIn('50s', progress)
        self.assertNotIn('ROUND -1', progress)
        self.assertNotIn('Burn window', progress)
        with patch.object(ui.time, 'monotonic', return_value=2000):
            progress = '\n'.join(dashboard.progress_rows(100))
        self.assertIn('Awaiting chain confirmation', progress)
        self.assertNotIn('ROUND 0', progress)

    def test_progress_clamps_until_a_new_chain_observation(self):
        dashboard = self.dashboard()
        with patch.object(ui.time, 'monotonic', return_value=100):
            dashboard.sync_chain(3990, 1000, 999)
        with patch.object(ui.time, 'monotonic', return_value=10000):
            progress = '\n'.join(dashboard.progress_rows(100))
        self.assertIn('ROUND 2', progress)
        self.assertIn('100.0%', progress)
        self.assertIn('awaiting chain confirmation', progress)
        self.assertNotIn('ROUND 3', progress)

    def test_stale_market_snapshot_is_not_shown_as_live_or_mining_input(self):
        dashboard = self.dashboard()
        dashboard.market = MagicMock()
        dashboard.market.snapshot.return_value = {
            'price': 23.5, 'age': 125, 'stale': True,
            'session_change_pct': -1.25, 'history': [24, 23.5],
        }
        before = dict(dashboard.fields)
        frame = dashboard.frame(100, 30)
        self.assertIn('HYPE/USDC', frame)
        self.assertIn('SPOT MID', frame)
        self.assertIn('STALE 125s', frame)
        self.assertIn('Session -1.25%', frame)
        self.assertEqual(dashboard.fields, before)
        dashboard.market.snapshot.return_value = {'price': None, 'status': 'unavailable'}
        unavailable = dashboard.frame(100, 30)
        self.assertIn('UNAVAILABLE', unavailable)
        self.assertIn('DRY RUN', unavailable)

    def test_disconnected_fresh_quote_is_not_labeled_live(self):
        dashboard = self.dashboard()
        dashboard.market = MagicMock()
        dashboard.market.snapshot.return_value = {
            'price': 23.5, 'age': 2, 'stale': False, 'status': 'retrying',
        }
        footer = dashboard.market_line(100)
        self.assertIn('23.5000', footer)
        self.assertNotIn('| LIVE', footer)
        self.assertTrue('RETRYING' in footer or 'CACHED' in footer)


if __name__ == '__main__':
    unittest.main()
