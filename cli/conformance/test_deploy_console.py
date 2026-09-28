"""Local-only deployment console regression tests; no external RPC."""
import argparse
import importlib.util
import json
import io
import stat
import sys
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock
from eth_account import Account

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'cli/python'))

spec = importlib.util.spec_from_file_location('console', Path(__file__).resolve().parents[2] / 'cli/python/deploy_console.py')
console = importlib.util.module_from_spec(spec)
spec.loader.exec_module(console)
console.ResilientHTTPProvider.MIN_INTERVAL = 0  # Tests use a disposable local node.

class RpcRetryTests(unittest.TestCase):
    def provider(self):
        return console.ResilientHTTPProvider('http://127.0.0.1:1', exception_retry_configuration=None)

    def test_invalid_height_read_recovers_after_long_outage(self):
        error = {'error': {'code': -32603, 'message': 'invalid block height: 47024900'}}
        ok = {'result': {'timestamp': '0x123'}}
        with patch.object(console.Web3.HTTPProvider, 'make_request', side_effect=[error] * 10 + [ok]) as call, patch.object(console, 'wait_locally') as wait:
            self.assertEqual(self.provider().make_request('eth_getBlockByNumber', ['latest', False]), ok)
            self.assertEqual(call.call_count, 11)
            self.assertEqual(max(c.args[0] for c in wait.call_args_list), 60)

    def test_rate_limit_cooldown_survives_successful_requests(self):
        error = {'error': {'code': -32005, 'message': 'rate limited'}}
        ok = {'result': '0x3e7'}
        provider = self.provider()
        with patch.object(console.Web3.HTTPProvider, 'make_request', side_effect=[error, ok, error, ok]), \
             patch.object(console, 'wait_locally') as wait, \
             patch.object(console.time, 'monotonic', return_value=100), \
             patch.object(console.time, 'sleep') as sleep:
            provider.make_request('eth_chainId', [])
            provider.make_request('eth_chainId', [])
            self.assertEqual([c.args[0] for c in wait.call_args_list], [30, 60])
            self.assertTrue(all(c.args[0] == 4 for c in sleep.call_args_list))

    def test_submission_is_never_replayed(self):
        error = {'error': {'code': -32603, 'message': 'invalid block height: 1'}}
        with patch.object(console.Web3.HTTPProvider, 'make_request', return_value=error) as call, patch.object(console, 'wait_locally') as wait:
            self.assertEqual(self.provider().make_request('eth_sendRawTransaction', ['test']), error)
            self.assertEqual(call.call_count, 1)
            wait.assert_not_called()

    def test_reverts_not_retried(self):
        error = {'error': {'code': 3, 'message': 'execution reverted'}}
        with patch.object(console.Web3.HTTPProvider, 'make_request', return_value=error) as call:
            self.assertEqual(self.provider().make_request('eth_call', []), error)
            self.assertEqual(call.call_count, 1)

    def test_request_spacing(self):
        provider = self.provider()
        provider.MIN_INTERVAL = 1.25
        with patch.object(console.Web3.HTTPProvider, 'make_request', return_value={'result': 1}), patch.object(console.time, 'monotonic', return_value=10), patch.object(console.time, 'sleep') as sleep:
            provider.make_request('eth_chainId', [])
            provider.make_request('eth_chainId', [])
            sleep.assert_called_once_with(1.25)

    def test_local_wait_has_no_rpc(self):
        with patch.object(console.time, 'monotonic', side_effect=[0, 0, 60, 120, 125]), patch.object(console.time, 'sleep') as sleep, patch.object(console.Web3.HTTPProvider, 'make_request') as rpc:
            console.wait_locally(125)
            self.assertEqual([c.args[0] for c in sleep.call_args_list], [60, 60, 5])
            rpc.assert_not_called()

class DisplayTests(unittest.TestCase):
    def test_round_clock_uses_monotonic_time_and_waits_for_chain(self):
        dashboard = console.terminal_ui.Dashboard(enabled=False)
        with patch.object(console.time, 'monotonic', return_value=100), patch.object(console.Web3.HTTPProvider, 'make_request') as rpc:
            dashboard.sync_chain(1500, 1000, 999)
            self.assertIn('08:19', dashboard.countdown())
            with patch.object(console.time, 'monotonic', return_value=110):
                self.assertIn('08:09', dashboard.countdown())
            with patch.object(console.time, 'monotonic', return_value=600):
                self.assertEqual(dashboard.countdown(), 'Round 1: awaiting chain confirmation')
            dashboard.sync_chain(999, 1000, 999)
            self.assertIn('Next round 0', dashboard.countdown())
            rpc.assert_not_called()

    def test_color_preserves_layout_and_no_color_disables_it(self):
        dashboard = console.terminal_ui.Dashboard(enabled=False)
        dashboard.color = True
        dashboard.log('RPC unavailable; retry in 30s')
        colored = dashboard.styled_frame(80, 24)
        self.assertIn('\x1b[33m', colored)
        plain = dashboard.frame(80, 24)
        self.assertEqual('\n'.join(console.terminal_ui.clean(line) for line in colored.splitlines()), plain)
        self.assertTrue(all(len(line) <= 79 for line in plain.splitlines()))
        output = io.StringIO()
        output.isatty = lambda: True
        with patch.object(console.sys, 'stdout', output), patch.object(console.sys, 'stderr', output), patch.dict(console.os.environ, {'NO_COLOR': '', 'TERM': 'xterm'}):
            dashboard = console.terminal_ui.Dashboard()
            self.assertFalse(dashboard.color)
            self.assertNotIn('\x1b', dashboard.styled_frame(80, 24))

    def test_redirected_output_has_no_animation(self):
        output = io.StringIO()
        with patch.object(console.sys, 'stderr', output):
            with console.activity('RPC eth_call'):
                pass
        self.assertEqual(output.getvalue(), '')

    def test_interrupt_cleans_up_animation_without_rpc(self):
        output = io.StringIO()
        output.isatty = lambda: True
        with patch.object(console.sys, 'stderr', output), \
             patch.object(console.Web3.HTTPProvider, 'make_request') as rpc:
            with self.assertRaises(KeyboardInterrupt):
                with console.activity('Waiting locally'):
                    raise KeyboardInterrupt
            self.assertTrue(output.getvalue().endswith('\r\033[2K'))
            rpc.assert_not_called()

class ClaimJournalTests(unittest.TestCase):
    def console(self):
        c = console.Console.__new__(console.Console)
        c.address = 'test-account'
        c.state = dict(rounds=[0, 1, 2], claimed_rounds=[0], spent=0)
        c.save = MagicMock()
        return c

    def test_confirmed_claims_are_never_read_again(self):
        c = self.console()
        miner = MagicMock()
        miner.functions.claimed.return_value.call.side_effect = [True, False, False]
        self.assertEqual(c.unclaimed_rounds(miner), [2])
        self.assertEqual(c.state['claimed_rounds'], [0, 1])
        self.assertEqual(c.unclaimed_rounds(miner), [2])
        self.assertEqual([call.args[0] for call in miner.functions.claimed.call_args_list], [1, 2, 2])
        c.save.assert_called_once()

    def test_successful_receipt_records_claims_but_revert_does_not(self):
        for status in (1, 0):
            c = self.console()
            c.state['pending'] = dict(hash='test-hash', kind='burn', value=console.MIN_BURN, round=3, claims=[1, 2])
            c.w3 = MagicMock()
            c.w3.eth.get_transaction_receipt.return_value = dict(status=status, gasUsed=100, effectiveGasPrice=2)
            if status:
                c.settle()
                self.assertEqual(c.state['claimed_rounds'], [0, 1, 2])
            else:
                with self.assertRaisesRegex(RuntimeError, 'reverted'):
                    c.settle()
                self.assertEqual(c.state['claimed_rounds'], [0])

class DashboardTests(unittest.TestCase):
    def test_restores_terminal_on_exception_and_does_not_call_rpc(self):
        output = io.StringIO()
        output.isatty = lambda: True
        with patch.dict(__import__('os').environ, {'TERM': 'xterm'}), \
             patch.object(console.sys, 'stdout', output), patch.object(console.sys, 'stderr', output), \
             patch.object(console.terminal_ui.shutil, 'get_terminal_size', return_value=__import__('os').terminal_size((100, 32))), \
             patch.object(console.Web3.HTTPProvider, 'make_request') as rpc:
            with self.assertRaises(KeyboardInterrupt):
                with console.terminal_ui.Dashboard() as dashboard:
                    dashboard.update(Balance='1 HYPE (snapshot)')
                    print('Test event')
                    raise KeyboardInterrupt
            self.assertIs(console.sys.stdout, output)
            self.assertIsNone(console.terminal_ui.current())
            self.assertIn('\x1b[?25h\x1b[?1049l', output.getvalue())
            rpc.assert_not_called()

    def test_navigation_keeps_fields_and_spending_unchanged(self):
        dashboard = console.terminal_ui.Dashboard(enabled=False)
        dashboard.update(**{'Spending cap': '1 HYPE', 'Wallet': '0x123'})
        for index in range(30):
            dashboard.log(f'event {index}')
        before = dict(dashboard.fields)
        for key in ['2', 'j', 'k', '3', 'k', 'k', 'j', 'g', '?', '\t', '1']:
            dashboard.handle_key(key)
            frame = dashboard.frame(80, 24)
            self.assertLessEqual(len(frame.splitlines()), 24)
            self.assertTrue(all(len(line) <= 79 for line in frame.splitlines()))
        self.assertEqual(dashboard.fields, before)
        self.assertIn('MINING', dashboard.frame(80, 24))

    def test_plain_output_and_frame_sanitization(self):
        output = io.StringIO()
        with patch.object(console.sys, 'stdout', output), patch.object(console.sys, 'stderr', output):
            with console.terminal_ui.Dashboard() as dashboard:
                self.assertFalse(dashboard.enabled)
                print('plain log')
            self.assertEqual(output.getvalue(), 'plain log\n')
        dashboard.update(Status='unsafe\x1b[2Jtext')
        frame = dashboard.frame(80, 24)
        self.assertNotIn('\x1b', frame)
        self.assertTrue(all(len(line) <= 79 for line in frame.splitlines()))

class WalletImportTests(unittest.TestCase):
    def test_encrypted_round_trip_permissions_and_no_overwrite(self):
        import wallet_setup
        account = Account.create()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'miner.keystore.json'
            password = 'local-test-password-only'
            self.assertEqual(wallet_setup.write_keystore(target, account.key.hex(), password), account.address)
            saved = target.read_bytes()
            self.assertEqual(Account.from_key(Account.decrypt(json.loads(saved), password)).address, account.address)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                wallet_setup.write_keystore(target, account.key.hex(), password)
            self.assertEqual(target.read_bytes(), saved)

    def test_invalid_private_key_is_not_echoed(self):
        import wallet_setup
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'miner.keystore.json'
            with self.assertRaises(ValueError) as error:
                wallet_setup.write_keystore(target, 'SECRET_SENTINEL', 'local-test-password-only')
            self.assertNotIn('SECRET_SENTINEL', str(error.exception))
            self.assertFalse(target.exists())

class SetupProfileTests(unittest.TestCase):
    def test_existing_keystore_setup_saves_only_connection_fields(self):
        import setup_miner
        import wallet_setup
        account = Account.create()
        with tempfile.TemporaryDirectory() as temp:
            keyfile = Path(temp) / 'test.keystore.json'
            wallet_setup.write_keystore(keyfile, account.key.hex(), 'test-password-123')
            with patch.dict(console.os.environ, {'HYBURN_HOME': temp}), \
                 patch('builtins.input', return_value=str(keyfile)), \
                 patch.object(setup_miner.sys.stdin, 'isatty', return_value=True), \
                 patch.object(setup_miner.getpass, 'getpass', return_value='test-password-123'):
                setup_miner.main()
                profile = Path(temp) / 'config.json'
                contents = profile.read_text()
                self.assertEqual(set(json.loads(contents)), set(setup_miner.ALLOWED))
                self.assertNotIn(account.key.hex(), contents)
                self.assertNotIn('test-password-123', contents)
                self.assertEqual(stat.S_IMODE(profile.stat().st_mode), 0o600)
                setup_miner.main()
                self.assertEqual(profile.read_text(), contents)

    def test_setup_invalid_key_explains_recovery_without_exposing_input(self):
        import setup_miner
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(console.os.environ, {'HYBURN_HOME':directory}), \
             patch.object(setup_miner.sys.stdin,'isatty',return_value=True), \
             patch('builtins.input',return_value=''), \
             patch.object(setup_miner.getpass,'getpass',side_effect=['PRIVATE_SENTINEL','test-password-123','test-password-123']):
            with self.assertRaises(SystemExit) as result:
                setup_miner.main()
            self.assertIn('32-byte hex private key',str(result.exception))
            self.assertNotIn('PRIVATE_SENTINEL',str(result.exception))
            self.assertFalse((Path(directory)/'config.json').exists())


    def test_explicit_key_and_rpc_override_saved_profile(self):
        import setup_miner
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'config.json').write_text(json.dumps({'HYBURN_RPC': 'saved', 'HYBURN_KEYSTORE': 'saved-path'}))
            with patch.dict(console.os.environ, {'HYBURN_HOME': temp, 'HYBURN_PRIVATE_KEY': 'test-only', 'HYBURN_RPC': 'explicit'}, clear=True):
                setup_miner.load_profile()
                self.assertEqual(console.os.environ['HYBURN_RPC'], 'explicit')
                self.assertNotIn('HYBURN_KEYSTORE', console.os.environ)

class KeyTests(unittest.TestCase):
    def test_private_key_loading_address_check_and_permissions(self):
        account = Account.create()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'deployment.local.json'
            path.write_text(json.dumps({'private_key': account.key.hex()}))
            path.chmod(0o644)
            signer = console.load_signer(account.address, config_path=path)
            self.assertEqual(signer.address, account.address)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaisesRegex(RuntimeError, 'does not match'):
                console.load_signer('0x' + '11' * 20, config_path=path)

    def test_bad_key_errors_do_not_echo_input(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'deployment.local.json'
            for value in ['', 'PRIVATE_SENTINEL_DO_NOT_PRINT']:
                path.write_text(json.dumps({'private_key': value}))
                with self.assertRaises(RuntimeError) as error:
                    console.load_signer(console.WALLET, config_path=path)
                self.assertNotIn('PRIVATE_SENTINEL', str(error.exception))

class BudgetTests(unittest.TestCase):
    def test_website_facts_preserve_other_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / '.env.local'
            target.write_text('NEXT_PUBLIC_MINER=old\nCUSTOM_SETTING=keep\n')
            console.update_website({'MINER': 'confirmed', 'GENESIS': 123}, target)
            self.assertEqual(target.read_text(), 'CUSTOM_SETTING=keep\nNEXT_PUBLIC_MINER=confirmed\nNEXT_PUBLIC_GENESIS=123\n')

    def test_runtime_rejects_modified_code_or_immutables(self):
        artifact = {'deployedBytecode': {'object': '0x600000', 'immutableReferences': {'1': [{'start': 1, 'length': 1}]}}}
        console.verify_runtime(artifact, bytes.fromhex('600700'), [7])
        for data, values in [('610700', [7]), ('600800', [7]), ('6007', [7])]:
            with self.assertRaises(RuntimeError):
                console.verify_runtime(artifact, bytes.fromhex(data), values)

    def test_fee_and_reserve_included(self):
        self.assertTrue(console.affordable(120, 100, 0, 70, 10, 3, 20))
        self.assertFalse(console.affordable(119, 100, 0, 70, 10, 3, 20))
        self.assertFalse(console.affordable(1000, 100, 1, 70, 10, 3, 0))

    def test_topups_do_not_expand_cap(self):
        self.assertFalse(console.affordable(10000, 100, 90, 11, 0, 0, 0))

class ChainTest(unittest.TestCase):
    def test_deploy_genesis_minimum_burn_and_resume(self):
        with tempfile.TemporaryDirectory(prefix='hyburn-console-test-') as temp:
            with socket.socket() as s:
                s.bind(('127.0.0.1', 0))
                port = s.getsockname()[1]
            proc = subprocess.Popen(['anvil', '--host', '127.0.0.1', '--port', str(port), '--chain-id', '31337', '--silent'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                # Public, disposable Anvil test key, never a funded wallet.
                account = Account.from_key('0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80')
                args = argparse.Namespace(rpc=f'http://127.0.0.1:{port}', wallet=account.address, chain_id=31337, state=str(Path(temp)/'session.json'))
                for _ in range(50):
                    try:
                        c = console.Console(args)
                        break
                    except Exception:
                        time.sleep(.1)
                else:
                    self.fail('Anvil failed to start')
                c.account = account
                c.state = dict(wallet=c.address, chain=31337, build=c.fingerprint, cap=10**18, spent=0, reserve=10**15, rounds=[], pending=None)
                self.assertTrue(c.send(c.factory.constructor(), 'deploy'))
                miner = c.w3.eth.contract(address=c.state['miner'], abi=c.artifact['abi'])
                self.assertEqual(c.verify_deployment(miner)[1], miner.functions.token().call())
                deployed = c.w3.eth.get_block(c.state['deploy_block'])
                genesis = miner.functions.genesisTimestamp().call()
                self.assertEqual(genesis, deployed['timestamp'] + 999)
                with self.assertRaises(Exception):
                    c.prepare(miner.functions.burn(0), console.MIN_BURN)
                c.w3.provider.make_request('evm_setNextBlockTimestamp', [genesis])
                c.w3.provider.make_request('evm_mine', [])
                self.assertTrue(c.send(miner.functions.burnAndClaim(0, []), 'burn', console.MIN_BURN, 0))
                self.assertEqual(miner.functions.burned(0, account.address).call(), console.MIN_BURN)
                self.assertEqual(c.state['rounds'], [0])
                self.assertEqual(c.state['last_tx_cost']['burn'], console.MIN_BURN)
                receipt = c.w3.eth.get_transaction_receipt(c.w3.eth.get_block('latest')['transactions'][0])
                self.assertEqual(c.state['last_tx_cost']['gas'], receipt['gasUsed'] * receipt['effectiveGasPrice'])
                original_spent = c.state['spent']
                # Exercise the actual execution orchestration on a second local deployment.
                args2 = argparse.Namespace(**vars(args))
                args2.state = str(Path(temp)/'automated.json')
                args2.execute = True
                args2.yes = True
                args2.keystore = None
                args2.reserve = '0.001'
                c.wallet_lease.close()  # The same wallet cannot run two consoles.
                auto = console.Console(args2)
                from mining_session import Session
                with self.assertRaisesRegex(SystemExit, 'Wallet already in use'):
                    Session(31337, '0x' + '11' * 20, account.address)
                target = Path(temp) / 'website.env'
                write_env = console.update_website
                def advance(_, *labels):
                    if auto.state['rounds']:
                        raise StopIteration('first automatic burn verified')
                    auto.w3.provider.make_request('evm_setNextBlockTimestamp', [auto.state['genesis']])
                    auto.w3.provider.make_request('evm_mine', [])
                with patch.object(console, 'ensure_config_untracked'), \
                     patch.object(console, 'load_signer', return_value=account), \
                     patch.object(console, 'update_website', side_effect=lambda env: write_env(env, target)), \
                     patch.object(console.subprocess, 'run') as build, \
                     patch.object(console, 'wait_locally', side_effect=advance):
                    with self.assertRaisesRegex(StopIteration, 'automatic burn'):
                        auto.run()
                    self.assertIn('NEXT_PUBLIC_MINER=' + auto.state['miner'], target.read_text())
                    self.assertEqual(auto.state['rounds'], [0])
                    self.assertTrue(any(call.args[0][:2] == ['npm', 'exec'] for call in build.call_args_list))
                # A resumed miner must not write/build the website.
                with patch.object(console, 'ensure_config_untracked'), \
                     patch.object(console, 'load_signer', return_value=account), \
                     patch.object(console, 'update_website') as website, \
                     patch.object(console.subprocess, 'run') as build, \
                     patch.object(console, 'wait_locally', side_effect=StopIteration('resumed')):
                    with self.assertRaisesRegex(StopIteration, 'resumed'):
                        auto.run()
                    website.assert_not_called()
                    build.assert_not_called()
                auto.lock.close()
                auto.wallet_lease.close()

                c.lock.close()
                c = console.Console(args)
                self.assertEqual(c.state['spent'], original_spent)
                c.account = account
                c.state['cap'] = c.state['spent']
                current = miner.functions.currentRoundId().call()
                self.assertFalse(c.send(miner.functions.burn(current), 'burn', console.MIN_BURN, current))
                c.state['pending'] = dict(hash='0x'+'ab'*32, kind='burn', value=console.MIN_BURN, round=1)
                with self.assertRaisesRegex(RuntimeError, 'unresolved'):
                    c.settle()
                c.lock.close()
                c.wallet_lease.close()
            finally:
                proc.terminate()
                proc.wait(timeout=10)

if __name__ == '__main__':
    unittest.main()
