"""Local-only deployment console regression tests; no external RPC."""
import argparse
import importlib.util
import json
import stat
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from eth_account import Account

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
                original_spent = c.state['spent']
                # Exercise the actual execution orchestration on a second local deployment.
                args2 = argparse.Namespace(**vars(args))
                args2.state = str(Path(temp)/'automated.json')
                args2.execute = True
                args2.keystore = None
                args2.reserve = '0.001'
                auto = console.Console(args2)
                target = Path(temp) / 'website.env'
                write_env = console.update_website
                def advance(_):
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
                auto.lock.close()

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
            finally:
                proc.terminate()
                proc.wait(timeout=10)

if __name__ == '__main__':
    unittest.main()
