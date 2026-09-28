"""Public bootstrap/launcher isolation; never install dependencies or start a miner."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
CLI=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CLI))
import tui
loader=importlib.machinery.SourceFileLoader('public_launcher',str(CLI/'hyburn'))
spec=importlib.util.spec_from_loader(loader.name,loader)
launcher=importlib.util.module_from_spec(spec);loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def test_installer_does_not_receive_wallet_environment(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(tui,'ROOT',Path(directory)), \
             patch.dict(os.environ,{'HYBURN_PRIVATE_KEY':'dummy-secret','HYBURN_KEYSTORE_PASSWORD':'dummy-password'}), \
             patch.object(tui.subprocess,'run',return_value=MagicMock(returncode=1)) as run:
            runtime=tui.ensure_runtime()
            self.assertEqual(runtime,Path(directory)/'python/.venv/bin/python')
            self.assertEqual(len(run.call_args_list),3)
            for call in run.call_args_list:
                self.assertFalse(any(k.startswith('HYBURN_') for k in call.kwargs['env']))
                self.assertNotIn('dummy-secret',str(call.args))
    def test_native_build_does_not_receive_wallet_environment(self):
        with patch.dict(os.environ,{'HYBURN_PRIVATE_KEY':'dummy-secret'}), \
             patch.object(launcher.shutil,'which',return_value='/bin/go'),patch.object(launcher.subprocess,'run') as run:
            launcher.build(['go','build'],CLI/'go')
        self.assertNotIn('HYBURN_PRIVATE_KEY',run.call_args.kwargs['env'])
    def test_selected_engine_gets_original_mining_arguments(self):
        with patch.object(sys,'argv',['hyburn','--engine','rust','mine','--amount','0.000999','--budget','1']), \
             patch.object(launcher,'stale',return_value=False),patch.object(launcher.os,'execv') as execute:
            launcher.main()
        argv=execute.call_args.args[1]
        self.assertEqual(argv[1:],['mine','--amount','0.000999','--budget','1'])
        self.assertIn('rust/target/release/hyburn',argv[0])
    def test_setup_uses_offline_wallet_setup_for_any_engine(self):
        with patch.object(sys,'argv',['hyburn','--engine','go','setup']), \
             patch.object(launcher,'ensure_runtime',return_value=Path('/test/python')),patch.object(launcher.os,'execv') as execute:
            launcher.main()
        self.assertEqual(execute.call_args.args[1][-1],'setup')

if __name__=='__main__':unittest.main()
