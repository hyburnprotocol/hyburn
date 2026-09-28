"""Read-only liquidity help and signing opt-in; no RPC or wallet access."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
import liquidity_console as ui
import mining_session
import setup_miner

WALLET = '0x1111111111111111111111111111111111111111'


class LiquidityConsoleTests(unittest.TestCase):
    def run_menu(self, inputs, run):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(setup_miner, 'load_profile'), \
             patch.object(mining_session, 'home', return_value=Path(directory)), \
             patch.dict(os.environ, {}, clear=True), \
             patch('builtins.input', side_effect=[WALLET, *inputs]), \
             patch('builtins.print'), patch.object(ui.subprocess, 'run', run):
            ui.main()

    def test_help_does_not_launch_or_sign(self):
        run = MagicMock()
        self.run_menu(['h', '', 'q'], run)
        run.assert_not_called()

    def test_successful_preview_still_needs_explicit_signing_choice(self):
        run = MagicMock(return_value=MagicMock(returncode=0))
        self.run_menu(['3', '100', '0', '0.00002', '0.00005', '', '', '', '', '', 'q'], run)
        self.assertEqual(run.call_count, 1)
        argv = run.call_args.args[0]
        self.assertNotIn('--execute', argv)
        self.assertEqual(argv[argv.index('--hyburn') + 1], '100')
        self.assertEqual(argv[argv.index('--whype') + 1], '0')
        self.assertEqual(argv[argv.index('--gas-budget') + 1], '0.01')


if __name__ == '__main__':
    unittest.main()
