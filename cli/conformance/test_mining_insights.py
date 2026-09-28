"""Read-only statistics and explicit-start safety, without a live wallet or RPC."""
import argparse
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
import terminal_ui as ui
import mining_insights as stats
import hyburn
import deploy_console
from hexbytes import HexBytes

A = '0x'+'11'*20
B = '0x'+'22'*20


def event(kind=stats.BURN, rid=0, account=A, value=10**18, amount=0, block=5, tx=1):
    return dict(topics=[HexBytes(kind), HexBytes(rid.to_bytes(32, 'big')),
                        HexBytes('0x'+'00'*12+account[2:])],
                data=HexBytes(value.to_bytes(32,'big')+amount.to_bytes(32,'big')),
                blockNumber=block, transactionHash=HexBytes(tx.to_bytes(32,'big')), logIndex=0)


class InsightsTests(unittest.TestCase):
    def test_wallet_aggregation_and_actual_claim(self):
        events = [stats.decode(event(tx=1)), stats.decode(event(tx=2)), stats.decode(event(account=B, tx=3))]
        rows,total,wallets,txs = stats.round_rows(events,A)
        self.assertEqual((total,wallets,txs),(3*10**18,2,3))
        self.assertIn('1*', rows[1]); self.assertIn('66.66%', rows[1])
        events.append(stats.decode(event(stats.CLAIM,amount=123*10**9,tx=4)))
        own = [e for e in events if e['account']==A]
        rows,count = stats.history_rows(own,2000,0,999)
        self.assertEqual(count,1); self.assertIn('CLAIMED',rows[1]); self.assertIn('123.000000000',rows[1])
        self.assertIn('OPEN',stats.history_rows(own[:2],500,0,999)[0][1])
        self.assertIn('CLAIMABLE',stats.history_rows(own[:2],2000,0,999)[0][1])

    def test_transaction_count_is_unique_across_wallets(self):
        events = [stats.decode(event()), stats.decode(event(account=B))]
        self.assertEqual(stats.round_rows(events,A)[2:], (2,1))

    def test_invalid_event_rejected(self):
        bad = event(); bad['data']=b'bad'
        with self.assertRaises(ValueError): stats.decode(bad)

    def monitor(self):
        d=ui.Dashboard(False)
        m=stats.Insights(d,'http://localhost:1',999,A,A,0,999,0)
        m.request=lambda page,fn:fn()
        m.w3=MagicMock()
        m.w3.eth.get_block.side_effect=lambda n:dict(number=n,timestamp=n*10,hash=bytes([n%256]))
        return d,m

    def test_round_snapshot_replaces_reorged_logs(self):
        d,m=self.monitor()
        block=dict(number=50,timestamp=500,hash=b'2')
        m.logs=MagicMock(return_value=[event(block=5)])
        m.round_snapshot(block)
        self.assertIn('1 wallets / 1 txs',d.snapshots[3][1])
        m.logs.return_value=[]
        m.round_snapshot(block)
        self.assertIn('0 wallets / 0 txs',d.snapshots[3][1])

    def test_history_bounded_and_does_not_present_partial_round(self):
        d,m=self.monitor()
        m.logs=MagicMock(return_value=[event(block=5900)])
        m.history_snapshot(dict(number=6000,timestamp=60000,hash=bytes([6000%256])))
        self.assertEqual(m.logs.call_count,5)
        self.assertIn('Partial history',d.snapshots[4][1])
        self.assertEqual(len(d.snapshots[4][0]),1)

    def test_history_claim_is_from_event_and_reorg_resets(self):
        d,m=self.monitor()
        m.logs=MagicMock(return_value=[event(),event(stats.CLAIM,amount=7*10**9,tx=2)])
        m.history_snapshot(dict(number=50,timestamp=2000,hash=b'2'))
        self.assertIn('7.000000000',d.snapshots[4][0][1])
        m.history_hash=b'orphaned'
        m.logs.return_value=[]
        m.history_snapshot(dict(number=50,timestamp=2000,hash=b'2'))
        self.assertEqual(len(d.snapshots[4][0]),1)

    def test_total_index_saves_partial_progress_and_resumes_without_rescan(self):
        with tempfile.TemporaryDirectory() as directory:
            d,m=self.monitor()
            m.cache_dir=Path(directory)
            m.logs=MagicMock(side_effect=lambda page,start,end,topics:[event()] if start<=5<=end else [])
            block=dict(number=6000,timestamp=60000,hash=bytes([6000%256]))
            try:
                m.total_snapshot(block)
                self.assertEqual(m.index.end,4999)
                self.assertIn('PARTIAL',d.snapshots[6][1])
                self.assertEqual(d.tables[6].records[0]['burned'],10**18)
            finally:
                m.index.close()
            d,again=self.monitor()
            again.cache_dir=Path(directory)
            again.logs=MagicMock(return_value=[])
            try:
                again.total_snapshot(block)
                self.assertEqual(again.logs.call_args_list[0].args[1],5000)
                self.assertIn('COMPLETE',d.snapshots[6][1])
                self.assertEqual(d.tables[6].records[0]['burned'],10**18)
            finally:
                again.index.close()

    def test_corrupt_index_interrupted_rebuild_still_discovers_genesis(self):
        with tempfile.TemporaryDirectory() as directory:
            d,m=self.monitor();m.genesis=100;m.cache_dir=Path(directory)
            (Path(directory)/f'999-{A.lower()}.sqlite3').write_bytes(b'not a database')
            original=m.w3.eth.get_block.side_effect
            m.w3.eth.get_block.side_effect=stats.Paused()
            block=dict(number=6000,timestamp=60000,hash=bytes([6000%256]))
            try:
                with self.assertRaises(stats.Paused):m.total_snapshot(block)
                self.assertEqual(m.index.get('origin_ready'),'0')
                m.w3.eth.get_block.side_effect=original
                m.logs=MagicMock(return_value=[])
                m.total_snapshot(block)
                self.assertEqual(m.index.start,10)
                self.assertEqual(m.logs.call_args_list[0].args[1],10)
            finally:
                m.index.close()

    def test_inactive_tab_never_calls_rpc(self):
        d=ui.Dashboard(False)
        m=stats.Insights(d,'http://localhost:1',999,A,A,0,999,0)
        fn=MagicMock()
        with self.assertRaises(stats.Paused): m.request(3,fn)
        fn.assert_not_called()

    def test_rpc_failure_keeps_previous_snapshot(self):
        d,m=self.monitor()
        d.page=3
        d.insight_snapshot(3,['old data'],'block 1')
        previous=d.snapshots[3]
        m.checked_chain=True
        m.stop=MagicMock()
        m.stop.wait.side_effect=[False,True]
        m.w3.eth.get_block.side_effect=TimeoutError()
        m.run()
        self.assertEqual(d.snapshots[3],previous)
        self.assertIn('previous snapshot retained',d.insight_messages[3])
        self.assertGreater(m.next_due[3],time.monotonic())

    def test_all_pages_fit_and_render_never_calls_rpc(self):
        d=ui.Dashboard(False)
        d.insight_snapshot(3,['row']*40,'Round 1 | 2 wallets','wallets are not people')
        d.insight_snapshot(4,['history']*40,'block 50')
        with patch.object(stats.Web3.HTTPProvider,'make_request') as rpc:
            for key in '123456?':
                d.handle_key(key)
                for _ in range(5): d.handle_key('j')
                frame=d.frame(80,24)
                self.assertEqual(len(frame.splitlines()),24)
                self.assertTrue(all(len(l)<=79 for l in frame.splitlines()))
            rpc.assert_not_called()


class StartTests(unittest.TestCase):
    def test_plain_default_is_no_and_unattended_requires_flag(self):
        with patch.object(sys.stdin,'isatty',return_value=True), patch('builtins.input',return_value=''):
            self.assertFalse(ui.choose_start())
        with patch.object(sys.stdin,'isatty',return_value=False):
            with self.assertRaisesRegex(SystemExit,'--yes'):ui.choose_start()
            self.assertTrue(ui.choose_start(True))

    def test_start_keys_only_work_in_standby_and_choice_cannot_flip(self):
        d=ui.Dashboard(False)
        d.handle_key('s'); self.assertIsNone(d.start_choice)
        d.awaiting_start=True
        d.handle_key('q'); d.handle_key('s')
        self.assertFalse(d.start_choice)

    def test_decline_public_precedes_key_and_session_recovery(self):
        hb=MagicMock()
        with patch.object(sys,'argv',['hyburn','mine']), patch('setup_miner.load_profile'), \
             patch.object(hyburn,'Hyburn',return_value=hb) as connection, patch.object(ui,'choose_start',return_value=False):
            hyburn.main()
        connection.assert_not_called()
        hb.load_key.assert_not_called(); hb.open_session.assert_not_called()

    def test_start_preview_is_explicit_and_privacy_safe(self):
        d=ui.Dashboard(False)
        ui.preview_start(d,['mine','--amount','0.000999','--budget=0.001998','--new-session'])
        d.awaiting_start=True
        frame=d.frame(100,30)
        self.assertIn('0.000999',frame)
        self.assertIn('0.001998',frame)
        self.assertIn('NEW budget requested',frame)
        self.assertIn('Transaction gas is extra',frame)
        d.privacy=True
        self.assertNotIn('0.001998',d.frame(100,30))

    def test_decline_developer_precedes_signing_and_settle(self):
        c=deploy_console.Console.__new__(deploy_console.Console)
        c.args=argparse.Namespace(execute=True,yes=False)
        c.state={'miner':A}; c.screen=MagicMock(); c.settle=MagicMock(); c.send=MagicMock()
        with patch.object(ui,'choose_start',return_value=False), patch.object(deploy_console,'load_signer') as signer:
            c.run()
        signer.assert_not_called(); c.settle.assert_not_called(); c.send.assert_not_called()

    def test_submission_guard_restored_on_failure(self):
        d=ui.Dashboard(False)
        @ui.transaction_activity
        def fn():
            self.assertTrue(d.signing)
            raise ValueError()
        with patch.object(ui,'_CURRENT',d):
            with self.assertRaises(ValueError):fn()
        self.assertFalse(d.signing)

if __name__=='__main__': unittest.main()
