"""Public liquidity isolation and input validation; no network or signing."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
import liquidity as m

A='0x1111111111111111111111111111111111111111'
B='0x2222222222222222222222222222222222222222'
class PublicLiquidityTests(unittest.TestCase):
    def test_no_developer_defaults(self):
        args=m.parser().parse_args([])
        self.assertIsNone(args.position); self.assertIsNone(args.wallet)
        self.assertFalse(args.execute)
    def test_amount_precision_and_range(self):
        self.assertEqual(m.units('0.000000001',9),1)
        for n in ('-1','NaN','Infinity','0.0000000001'):
            with self.assertRaises((RuntimeError,ValueError)):m.units(n,9)
        with self.assertRaises(RuntimeError):m.ticks('2','1',60)
    def test_wallet_state_isolation(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(m,'home',return_value=Path(tmp)),patch.object(m,'load_profile'),patch.dict(m.os.environ,{},clear=True):
            a=m.parser().parse_args(['status','--wallet',A]);m.configure(a);first=m.JOURNAL
            b=m.parser().parse_args(['status','--wallet',B]);m.configure(b)
            self.assertNotEqual(first,m.JOURNAL)
            self.assertIn(B.lower(),str(m.JOURNAL))
    def test_existing_position_required_for_mutation(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(m,'home',return_value=Path(tmp)),patch.object(m,'load_profile'),patch.dict(m.os.environ,{},clear=True):
            for action in ('add','remove','collect'):
                with self.assertRaisesRegex(RuntimeError,'Select an owned'):
                    m.configure(m.parser().parse_args([action,'--wallet',A]))
    def test_new_position_does_not_require_existing_nft(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(m,'home',return_value=Path(tmp)),patch.object(m,'load_profile'),patch.dict(m.os.environ,{},clear=True):
            args=m.parser().parse_args(['new','--wallet',A]);m.configure(args)
            self.assertIsNone(args.position)
    def test_foreign_position_rejected(self):
        w=MagicMock();w.eth.chain_id=999;m.p.WALLET=A
        position=(0,A,m.p.WHYPE,m.p.TOKEN,3000,-100,-40,10,0,0,0,0)
        with patch.object(m,'call',side_effect=[(m.p.FACTORY,),(m.p.WHYPE,),(m.POOL,),(9,),(18,),position,(B,)]):
            with self.assertRaisesRegex(RuntimeError,'not owned'):m.verify(w,123)


class RecoveryTests(unittest.TestCase):
    def state(self,root,entries,count=1):
        m.ROOT=Path(root);m.JOURNAL=m.ROOT/'management-journal.json';m.p.WALLET=A
        m.save({'wallet':A,'chain':999,'action':'collect','status':'started','planned_count':count,'transactions':entries})
    def test_confirmed_timeout_recovers_complete(self):
        with tempfile.TemporaryDirectory() as root,patch('builtins.print'):
            self.state(root,[{'hash':'0x01','status':'prepared'}])
            w=MagicMock();w.eth.get_transaction_receipt.return_value=MagicMock(status=1,gasUsed=5,effectiveGasPrice=2)
            self.assertEqual(m.reconcile(w)['status'],'complete')
            w.eth.send_raw_transaction.assert_not_called()
    def test_unknown_hash_never_allows_close(self):
        with tempfile.TemporaryDirectory() as root,patch('builtins.print'),patch('builtins.input') as prompt:
            self.state(root,[{'hash':'0x01','status':'prepared'}])
            w=MagicMock();w.eth.get_transaction_receipt.side_effect=m.TransactionNotFound('unknown')
            with self.assertRaisesRegex(RuntimeError,'pending or unknown'):m.recover(w)
            prompt.assert_not_called();w.eth.send_raw_transaction.assert_not_called()
    def test_no_broadcast_can_be_closed_explicitly(self):
        with tempfile.TemporaryDirectory() as root,patch('builtins.print'),patch('builtins.input',return_value='CLOSE REVIEWED OPERATION'),patch.object(m,'call',return_value=(0,)):
            self.state(root,[])
            w=MagicMock();w.eth.get_transaction_count.return_value=0
            m.recover(w)
            self.assertEqual(m.json.loads(m.JOURNAL.read_text())['status'],'reviewed')
            w.eth.send_raw_transaction.assert_not_called()
    def test_partial_is_not_reported_complete(self):
        with tempfile.TemporaryDirectory() as root,patch('builtins.print'):
            self.state(root,[{'hash':'0x01','status':'confirmed'}],3)
            w=MagicMock();w.eth.get_transaction_receipt.return_value=MagicMock(status=1,gasUsed=5,effectiveGasPrice=2)
            self.assertEqual(m.reconcile(w)['status'],'partial')
    def test_expired_quote_and_total_gas_rejected_before_signing(self):
        w=MagicMock();w.eth.get_block.return_value=MagicMock(timestamp=101)
        args=m.parser().parse_args(['wrap'])
        details={'quote_valid_until':100,'gas_limits':[100,100]}
        with self.assertRaisesRegex(RuntimeError,'expired'):m.preflight(w,args,[{'value':0}],details)
        details['quote_valid_until']=200
        with patch.object(m,'fee_price',return_value=(10**18,False)):
            with self.assertRaisesRegex(RuntimeError,'Whole-operation gas'):m.preflight(w,args,[{'value':0}],details)
        w.eth.send_raw_transaction.assert_not_called()

if __name__=='__main__':unittest.main()
