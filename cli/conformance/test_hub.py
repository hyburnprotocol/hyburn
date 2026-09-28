"""The control center must never start a transaction from navigation alone."""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hub

class HubTests(unittest.TestCase):
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

if __name__=='__main__': unittest.main()
