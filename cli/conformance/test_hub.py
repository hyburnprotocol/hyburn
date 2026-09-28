"""The control center must never start a transaction from navigation alone."""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import os
import json
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hub

class HubTests(unittest.TestCase):
    def setUp(self):
        self.state = dict(ready=True, connection=True, session=True, developer=False, developer_session=False, profile=True, error='')
        self.target = patch.object(hub, 'menu_state', return_value=self.state)
        self.target.start()
        self.addCleanup(self.target.stop)

    def test_exit_does_not_start_a_child(self):
        with patch.object(sys.stdin,'isatty',return_value=True),patch.object(sys.stdout,'isatty',return_value=True),patch('builtins.input',return_value='q'),patch.object(hub.subprocess,'run') as run,patch('builtins.print'):
            hub.main()
        run.assert_not_called()
    def test_engine_choice_then_mining_uses_selected_engine_without_yes(self):
        with patch.object(sys.stdin,'isatty',return_value=True),patch.object(sys.stdout,'isatty',return_value=True),patch('builtins.input',side_effect=['5','4','1','','q']),patch.object(hub.subprocess,'run') as run,patch('builtins.print'):
            hub.main()
        argv=run.call_args.args[0]
        self.assertEqual(argv[-3:],['--engine','rust','mine'])
        self.assertNotIn('--yes',argv)
    def test_noninteractive_requires_explicit_command(self):
        with patch.object(sys.stdin,'isatty',return_value=False),patch.object(hub.subprocess,'run') as run:
            with self.assertRaises(SystemExit): hub.main()
        run.assert_not_called()
    def test_retired_menu_does_not_launch_a_child(self):
        with patch.object(sys.stdin,'isatty',return_value=True),patch.object(sys.stdout,'isatty',return_value=True),patch('builtins.input',side_effect=['9','q']),patch.object(hub.subprocess,'run') as run,patch.object(hub,'banner') as banner:
            hub.main()
        run.assert_not_called()
        self.assertFalse(any('Legacy local liquidity' in line for call in banner.call_args_list for line in call.args[1]))

    def test_first_session_limits_are_explicit_and_never_reset_budget(self):
        self.state['session'] = False
        with patch.object(sys.stdin,'isatty',return_value=True), patch.object(sys.stdout,'isatty',return_value=True), \
             patch('builtins.input',side_effect=['1','0.000999','0.001998','','q']), \
             patch.object(hub.subprocess,'run') as run, patch('builtins.print'):
            hub.main()
        argv = run.call_args.args[0]
        self.assertEqual(argv[-5:], ['mine','--amount','0.000999','--budget','0.001998'])
        self.assertNotIn('--yes', argv)
        self.assertNotIn('--new-session', argv)

    def test_cancel_configuration_does_not_launch(self):
        self.state['session'] = False
        with patch.object(sys.stdin,'isatty',return_value=True), patch.object(sys.stdout,'isatty',return_value=True), \
             patch('builtins.input',side_effect=['1','q','q']), patch.object(hub.subprocess,'run') as run, patch('builtins.print'):
            hub.main()
        run.assert_not_called()

    def test_invalid_limits_cannot_become_mining_arguments(self):
        with patch('builtins.input',side_effect=['NaN','-1','1e999999','0.000999','0.0001','0.001998']), patch('builtins.print'):
            args = hub.first_session_args()
        self.assertEqual(args, ['mine','--amount','0.000999','--budget','0.001998'])

    def test_below_minimum_burn_is_rejected_before_start(self):
        with patch('builtins.input', side_effect=['0.0001', '0.000999', '0.001998']):
            self.assertEqual(hub.first_session_args(), ['mine', '--amount', '0.000999', '--budget', '0.001998'])

    def test_unconfigured_menu_has_no_resume_or_configuration(self):
        state = dict(self.state, ready=False, connection=False, session=False, profile=False)
        entries = hub.menu_entries(state)
        self.assertEqual(entries[0][1], 'setup')
        self.assertNotIn('resume',[e[1] for e in entries])
        self.assertNotIn('configure',[e[1] for e in entries])
        self.assertNotIn('history',[e[1] for e in entries])

    def test_developer_resume_uses_existing_console_not_public_engine(self):
        with patch.object(hub, 'menu_state', return_value=dict(self.state, ready=False, session=False, developer=True, developer_session=True)), \
             patch.object(Path,'is_file',return_value=True), \
             patch.object(sys.stdin,'isatty',return_value=True), patch.object(sys.stdout,'isatty',return_value=True), \
             patch('builtins.input',side_effect=['1','','q']), patch.object(hub.subprocess,'run') as run, \
             patch('tui.ensure_runtime',return_value=Path('/test/python')), patch('builtins.print'):
            hub.main()
        self.assertTrue(run.call_args.args[0][1].endswith('deploy_console.py'))
        self.assertEqual(run.call_args.args[0][-1], '--execute')

    def test_ready_wallet_without_session_offers_configure_not_resume(self):
        entries = hub.menu_entries(dict(self.state, session=False))
        self.assertEqual(entries[0][1], 'configure')
        self.assertNotIn('resume', [e[1] for e in entries])

    def test_session_detection_matches_wallet_chain_and_miner(self):
        self.target.stop()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'HYBURN_HOME':directory}, clear=True), patch.object(hub,'ROOT',Path(directory)/'cli'):
            base=Path(directory); miner='0x'+'11'*20; account='0x'+'22'*20
            key=base/'wallet.json'; key.write_text(json.dumps({'address':account[2:]}))
            (base/'config.json').write_text(json.dumps({'HYBURN_MINER':miner,'HYBURN_CHAIN_ID':'999','HYBURN_KEYSTORE':str(key)}))
            self.assertTrue(hub.menu_state()['ready'])
            self.assertFalse(hub.menu_state()['session'])
            (base/f'999-{miner}-0x{"33"*20}.session.json').write_text('{}')
            self.assertFalse(hub.menu_state()['session'])
            (base/f'999-{miner}-{account}.session.json').write_text('{}')
            self.assertTrue(hub.menu_state()['session'])
            key.unlink()
            self.assertFalse(hub.menu_state()['ready'])
            self.assertFalse(hub.menu_state()['session'])

    def test_first_time_help_never_loads_engine(self):
        with patch.object(sys.stdin,'isatty',return_value=True), patch.object(sys.stdout,'isatty',return_value=True), \
             patch('builtins.input',side_effect=['h','','q']), patch.object(hub.subprocess,'run') as run, patch('builtins.print'):
            hub.main()
        run.assert_not_called()

if __name__=='__main__': unittest.main()
