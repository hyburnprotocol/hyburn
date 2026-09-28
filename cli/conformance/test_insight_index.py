"""Persistent statistics correctness: exact integers, restart, duplication and reorgs."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
from insight_index import EventIndex
from insight_table import InsightTable
from terminal_ui import Dashboard
from engine_dashboard import EngineView, PREFIX
from unittest.mock import MagicMock

A='0x'+'11'*20
B='0x'+'22'*20


def event(tx='a',idx=0,block=1,kind='burn',account=A,rid=0,value=10**18,amount=0):
    return dict(tx=tx,idx=idx,block=block,kind=kind,account=account,round=rid,value=value,amount=amount)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'index.sqlite3'
        self.identity=dict(chain=999,miner=A,genesis=1)
        self.index=EventIndex(self.path,self.identity,1)
    def tearDown(self):
        self.index.close();self.tmp.cleanup()
    def test_exact_aggregates_distinct_rounds_and_duplicate_logs(self):
        huge=2**180
        events=[event(value=huge),event(value=huge),event(idx=1,value=7),event(tx='b',block=2,rid=1,value=3),
                event(tx='c',block=3,kind='claim',amount=2**190),event(tx='d',block=3,account=B)]
        self.assertTrue(self.index.append(1,3,'h3',events))
        a=next(r for r in self.index.wallets() if r['account']==A)
        self.assertEqual(a,dict(account=A,burned=huge+10,claimed=2**190,rounds=2,txs=2))
        self.assertFalse(self.index.append(1,3,'h3',events))
        self.assertEqual(next(r for r in self.index.wallets() if r['account']==A),a)
    def test_reopen_and_continue_automatically(self):
        self.index.append(1,9,'h9',[event()])
        self.index.close();self.index=EventIndex(self.path,self.identity,0)
        self.assertEqual((self.index.start,self.index.end),(1,9))
        self.index.append(10,12,'h12',[event(tx='b',block=10,rid=1)])
        self.assertEqual(self.index.wallets()[0]['burned'],2*10**18)
    def test_chunk_failure_rolls_back_progress_and_amounts(self):
        with self.assertRaises(ValueError):
            self.index.append(1,3,'h3',[event(),event(tx='b',block=9)])
        self.assertEqual(self.index.end,0);self.assertEqual(self.index.wallets(),[])
        self.assertEqual(self.index.checkpoints(),[])
    def test_reorg_rebuilds_only_surviving_participation_and_claims(self):
        self.index.append(1,3,'h3',[event(),event(tx='b',block=2,account=B)])
        self.index.append(4,9,'h9',[event(tx='c',block=5,rid=1),event(tx='d',block=6,kind='claim',amount=999)])
        self.index.rollback(3)
        a=next(r for r in self.index.wallets() if r['account']==A)
        self.assertEqual((a['burned'],a['claimed'],a['rounds'],a['txs']),(10**18,0,1,1))
        self.assertEqual(len(self.index.wallets()),2)
        self.index.append(4,9,'new9',[event(tx='e',block=5,value=7)])
        self.assertEqual(next(r for r in self.index.wallets() if r['account']==A)['burned'],10**18+7)
    def test_identity_mismatch_rebuilds_only_disposable_cache(self):
        self.index.append(1,3,'h3',[event()]);self.index.close()
        self.index=EventIndex(self.path,dict(chain=1,miner=B,genesis=0),0)
        self.assertTrue(self.index.rebuilt);self.assertEqual(self.index.wallets(),[])
        self.assertTrue(list(self.path.parent.glob('*.invalid-*')))
    def test_two_workers_cannot_double_count(self):
        second=EventIndex(self.path,self.identity,1)
        try:
            self.assertTrue(self.index.append(1,3,'h3',[event()]))
            self.assertFalse(second.append(1,3,'h3',[event()]))
            self.assertEqual(second.wallets()[0]['burned'],10**18)
        finally:second.close()


class TableTests(unittest.TestCase):
    def table(self):
        table=InsightTable(6,A)
        table.set_records([dict(account=A,burned=10**18,claimed=2*10**9,rounds=2,txs=3),
                           dict(account=B,burned=3*10**18,claimed=0,rounds=1,txs=1)],A)
        return table
    def test_sort_filter_preserves_global_rank_and_full_address(self):
        t=self.table();t.handle('m')
        self.assertEqual(t.view()[0]['rank'],2)
        self.assertIn(A,'\n'.join(t.render(77,10)))
        t.handle('o');self.assertEqual(t.sort,'rounds');self.assertEqual(t.view()[0]['rank'],1)
        t.handle('c');t.handle('/')
        for char in B:t.handle(char)
        t.handle('\r');self.assertEqual([r['account'] for r in t.view()],[B])
    def test_selection_survives_new_snapshot_and_privacy_masks_values(self):
        t=self.table();t.handle('j')
        t.set_records([dict(account=A,burned=5*10**18,claimed=2*10**9,rounds=2,txs=3),
                       dict(account=B,burned=3*10**18,claimed=0,rounds=1,txs=1)],A)
        self.assertEqual(t.view()[t.selected]['account'],A)
        frame='\n'.join(t.render(77,10,True))
        self.assertNotIn(A,frame);self.assertNotIn('5.000000000',frame)
    def test_search_does_not_trigger_start_or_navigation(self):
        d=Dashboard(False);d.insight_snapshot(6,[],'partial',records=self.table().records);d.handle_key('7');d.handle_key('/')
        d.feed_keys('123sqp');self.assertEqual(d.page,6);self.assertFalse(d.stats_paused)
        d.feed_keys('\x1b');d.feed_keys('[6~');self.assertEqual(d.page,6)
        d.handle_key('\x1b');self.assertIsNone(d.tables[6].editing)
    def test_frames_fit_and_privacy_covers_logs_and_fields(self):
        d=Dashboard(False);d.update(Wallet=A,**{'Session gas':'0.123456789 HYPE'})
        d.log('wallet '+A+' gas 0.123456789 HYPE')
        d.insight_snapshot(6,[],'PARTIAL 50%',records=self.table().records)
        d.handle_key('v')
        for key in '1234567?':
            d.handle_key(key)
            for width,height in [(80,24),(120,36)]:
                frame=d.frame(width,height)
                self.assertEqual(len(frame.splitlines()),height)
                self.assertTrue(all(len(l)<width for l in frame.splitlines()))
                self.assertNotIn(A,frame);self.assertNotIn('0.123456789',frame)
    def test_native_engine_metadata_uses_same_automatic_insights(self):
        d=Dashboard(False);d.attach_insights=MagicMock()
        view=EngineView(d,'http://localhost:1')
        meta=dict(type='meta',account=A,miner=B,token=B,chain=999,genesis=1,duration=999,deploy=4,at=30,
                  amount='999000000000000',budget='9990000000000000',reserve='1000000000000000',dry=False)
        view.consume(PREFIX+json.dumps(meta))
        self.assertEqual(d.fields['Wallet'],A)
        self.assertEqual(d.attach_insights.call_args.kwargs['account'],A)
        view.consume(PREFIX+json.dumps(dict(type='usage',spent='999000000000000',burns=1,gas='12000000000000')))
        self.assertEqual(d.fields['Session burns'],'1')
        view.consume(PREFIX+json.dumps(dict(type='busy',value=True)));self.assertTrue(d.signing)
        view.consume(PREFIX+json.dumps(dict(type='busy',value=False)));self.assertFalse(d.signing)

    def test_privacy_keeps_public_summary_but_not_wallet_fingerprints(self):
        d=Dashboard(False)
        d.update(Wallet=A,Engine='rust',**{'Block (last read)':'123456','Send window':'17s private timing'})
        table=self.table()
        d.insight_snapshot(6,[], 'private caption '+A, note='private note',
                           records=table.records, public_summary='COMPLETE | 2 wallets | 4 HYPE burned')
        t=d.tables[6]
        t.handle('m');t.query=A;t._view=None
        d.insight_status(6,'unsafe provider error '+A)
        d.handle_key('v');d.handle_key('7')
        frame=d.frame(120,36)
        for secret in (A,'YOU','Me only','private caption','private note','unsafe provider error'):
            self.assertNotIn(secret,frame)
        self.assertIn('2 wallets | 4 HYPE burned',frame)
        before=(t.query,t.mine_only,t.selected)
        d.handle_key('c');d.handle_key('m');d.handle_key('/')
        self.assertEqual(before,(t.query,t.mine_only,t.selected))
        self.assertIsNone(t.editing)
        self.assertEqual(d.display_field('Engine','rust'),'rust')
        self.assertEqual(d.display_field('Block (last read)','123456'),'123456')
        self.assertEqual(d.display_field('Send window','17s private timing'),'[hidden]')
        d.insight_snapshot(4,[], 'private history',records=[dict(round=42,burned=1,claimed=2,txs=3,status='CLAIMED')])
        d.handle_key('5')
        self.assertNotIn('42',d.frame(120,36))
        self.assertNotIn('CLAIMED',d.frame(120,36))
        d.handle_key('v');d.handle_key('7')
        self.assertEqual(before,(t.query,t.mine_only,t.selected))

    def test_table_privacy_does_not_expose_own_rank_share_or_filter(self):
        t=InsightTable(3,A)
        t.set_records([dict(account=A,burned=123,txs=7,share='100.00%')],A)
        t.handle('m');t.editing=A
        frame='\n'.join(t.render(100,12,True))
        for secret in (A,'YOU','100.00%','Me only','7'):
            self.assertNotIn(secret,frame)

if __name__=='__main__':unittest.main()
