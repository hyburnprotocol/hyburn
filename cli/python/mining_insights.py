"""Optional read-only TUI snapshots. No signer, transaction methods or session writes."""
from collections import defaultdict
from decimal import Decimal
import threading
import time
from web3 import Web3

BURN = Web3.to_hex(Web3.keccak(text='HypeBurned(uint256,address,uint256,uint128)'))
CLAIM = Web3.to_hex(Web3.keccak(text='RewardClaimed(uint256,address,uint128,uint256)'))


def decode(log):
    topics = log['topics']
    kind = Web3.to_hex(topics[0]).lower()
    if kind not in (BURN.lower(), CLAIM.lower()) or len(topics) != 3:
        raise ValueError('Unexpected event')
    data = bytes(log['data'])
    if len(data) != 64:
        raise ValueError('Unexpected event data')
    return dict(kind=kind, round=int.from_bytes(topics[1], 'big'),
                account=Web3.to_checksum_address('0x' + bytes(topics[2])[-20:].hex()),
                value=int.from_bytes(data[:32], 'big'), amount=int.from_bytes(data[32:], 'big'),
                block=log['blockNumber'], hash=Web3.to_hex(log['transactionHash']),
                index=log['logIndex'])


def units(value, decimals):
    result = f'{Decimal(value) / Decimal(10**decimals):.{min(decimals, 9)}f}'
    return result if len(result) <= 15 else f'{Decimal(value) / Decimal(10**decimals):.5E}'


def round_rows(events, own):
    wallets = defaultdict(lambda: [0, set()])
    transactions = set()
    for e in events:
        if e['kind'] == BURN.lower():
            transactions.add(e['hash'])
            wallets[e['account']][0] += e['value']
            wallets[e['account']][1].add(e['hash'])
    total = sum(v[0] for v in wallets.values())
    ordered = sorted(wallets.items(), key=lambda item: (-item[1][0], item[0]))
    rows = ['Rank Wallet                                      HYPE burned    Share  Txs']
    for rank, (wallet, (value, txs)) in enumerate(ordered, 1):
        marker = '*' if wallet.lower() == own.lower() else ' '
        share = f'{value * 10000 // total / 100:.2f}%' if total else '0.00%'
        rows.append(f'{rank:>3}{marker} {wallet} {units(value,18):>14} {share:>7} {len(txs):>3}')
    return rows, total, len(wallets), len(transactions)


def history_rows(events, timestamp, genesis, duration, limit=20):
    rounds = {}
    for e in events:
        row = rounds.setdefault(e['round'], dict(burned=0, txs=set(), claimed=None))
        if e['kind'] == BURN.lower():
            row['burned'] += e['value']; row['txs'].add(e['hash'])
        else:
            row['claimed'] = e['amount']
    burn_ids = sorted((rid for rid, r in rounds.items() if r['burned']), reverse=True)
    rows = ['Round       HYPE burned   Txs  Status       Claimed HYBURN']
    for rid in burn_ids[:limit]:
        r = rounds[rid]
        status = 'CLAIMED' if r['claimed'] is not None else ('OPEN' if timestamp < genesis+(rid+1)*duration else 'CLAIMABLE')
        amount = units(r['claimed'],9) if r['claimed'] is not None else '--'
        rows.append(f'{rid:>6} {units(r["burned"],18):>17} {len(r["txs"]):>5}  {status:<10} {amount:>16}')
    return rows, len(burn_ids)


class Paused(Exception):
    pass


class Insights:
    """Only visible insights tabs fetch. Requests spaced >=2s; snapshots >=60s apart."""
    def __init__(self, dashboard, rpc, chain, miner, account, genesis, duration, deploy_block, send_window=30):
        self.ui = dashboard
        self.w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={'timeout':8}, exception_retry_configuration=None))
        self.chain, self.miner, self.account = chain, Web3.to_checksum_address(miner), Web3.to_checksum_address(account)
        self.genesis, self.duration, self.deploy = genesis, duration, max(0, deploy_block)
        self.send_window = send_window
        self.history_hash = None
        self.stop = threading.Event()
        self.last_request = 0
        self.next_due = {3:0,4:0}
        self.checked_chain = False
        self.round_cache = None
        self.history = {}
        self.history_end = None
        self.history_cursor = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        # Reads have a bounded timeout; never hold up terminal restoration.
        self.thread.join(timeout=.1)

    def request(self, page, fn):
        while True:
            if self.stop.is_set() or self.ui.page != page:
                raise Paused()
            with self.ui.lock:
                clock = self.ui.chain_clock
                signing = self.ui.signing
            left = clock[1] - (time.monotonic()-clock[0]) if clock else None
            near_send = left is not None and (left >= 0 and (abs(left-self.send_window) <= 15 or
                                                   (self.send_window == 0 and left >= self.duration-20)))
            if signing or near_send:
                self.ui.insight_status(page, 'Paused near mining window; existing snapshot retained')
                if self.stop.wait(.5): raise Paused()
                continue
            delay = 2 - (time.monotonic()-self.last_request)
            if delay > 0:
                if self.stop.wait(min(delay,.5)): raise Paused()
                continue
            self.last_request = time.monotonic()
            return fn()

    def logs(self, page, start, end, topics):
        return self.request(page, lambda:self.w3.eth.get_logs(dict(address=self.miner, fromBlock=start, toBlock=end, topics=topics)))

    def round_snapshot(self, block):
        rid = (block['timestamp']-self.genesis)//self.duration
        if rid < 0:
            self.ui.insight_snapshot(3, ['Mining has not started.'], f'Block {block["number"]}')
            return
        target = self.genesis+rid*self.duration
        # Locate the exact start by timestamp, rather than guessing block time.
        lo, hi = self.deploy, block['number']
        cache = self.round_cache
        if cache and cache[0] == rid and cache[2] <= block['number']:
            previous = self.request(3, lambda:self.w3.eth.get_block(cache[2]))
            if previous['hash'] != cache[3]:
                cache = None
        else:
            cache = None
        if cache:
            start = cache[1]
        else:
            while lo < hi:
                self.ui.insight_status(3, 'Locating round start on chain...')
                mid=(lo+hi)//2
                b=self.request(3,lambda:self.w3.eth.get_block(mid))
                if b['timestamp'] < target: lo=mid+1
                else: hi=mid
            start=lo
        # Re-read this entire round; never retain logs from an orphaned block.
        events = {}
        lo = start
        a=lo
        while a <= block['number']:
            b=min(a+999,block['number'])
            self.ui.insight_status(3, f'Loading round {rid}: blocks {a}-{b}')
            for log in self.logs(3,a,b,[BURN,Web3.to_hex(rid.to_bytes(32,'big'))]):
                e=decode(log);events[(e['hash'],e['index'])]=e
            a=b+1
        check=self.request(3,lambda:self.w3.eth.get_block(block['number']))
        if check['hash'] != block['hash']: raise ValueError('Snapshot changed; retry')
        self.round_cache=(rid,start,block['number'],block['hash'])
        rows,total,wallets,txs=round_rows(events.values(),self.account)
        caption=f'Round {rid} | {wallets} wallets / {txs} txs | {units(total,18)} HYPE'
        self.ui.insight_snapshot(3, rows, caption+f' | block {block["number"]}',
                                 note='Rank by this round\'s burns. * = you. Wallets are not people.')

    def history_snapshot(self, block):
        end=block['number']
        # Reset on a chain reorganization or a long absence; bounded backfill resumes.
        if self.history_end is not None:
            invalid = end < self.history_end or end-self.history_end > 4000
            if not invalid:
                previous = self.request(4, lambda:self.w3.eth.get_block(self.history_end))
                invalid = previous['hash'] != self.history_hash
            if invalid:
                self.history = {}
                self.history_end = self.history_cursor = None
        events=dict(self.history)
        topic_account='0x'+'00'*12+self.account[2:].lower()
        topics=[[BURN,CLAIM],None,topic_account]
        cursor=self.history_cursor
        # Incremental recent tail, overlapping to replace shallow reorganizations.
        if self.history_end is not None:
            low=max(self.deploy,self.history_end-12)
            if end < self.history_end:
                events={};cursor=None;low=end+1
            else:
                events={k:v for k,v in events.items() if v['block'] < low}
            while low<=end:
                upper=min(low+999,end)
                for log in self.logs(4,low,upper,topics):
                    e=decode(log);events[(e['hash'],e['index'])]=e
                low=upper+1
        if cursor is None: cursor=end
        count=len({e['round'] for e in events.values() if e['kind']==BURN.lower()})
        # At most five backward chunks per refresh; show coverage instead of fake zero.
        for _ in range(5):
            if cursor < self.deploy or count>20: break
            low=max(self.deploy,cursor-999)
            self.ui.insight_status(4,f'Loading your history: blocks {low}-{cursor}')
            for log in self.logs(4,low,cursor,topics):
                e=decode(log);events[(e['hash'],e['index'])]=e
            cursor=low-1
            count=len({e['round'] for e in events.values() if e['kind']==BURN.lower()})
        check=self.request(4,lambda:self.w3.eth.get_block(end))
        if check['hash'] != block['hash']: raise ValueError('Snapshot changed; retry')
        self.history,self.history_end,self.history_cursor=events,end,cursor
        self.history_hash = block["hash"]
        complete=cursor<self.deploy or count>20
        # If incomplete, the oldest round can straddle the unscanned boundary.
        visible=list(events.values())
        if not complete:
            ids=[e['round'] for e in visible if e['kind']==BURN.lower()]
            if ids: visible=[e for e in visible if e['round']!=min(ids)]
        rows,_=history_rows(visible,block['timestamp'],self.genesis,self.duration)
        coverage='Latest 20 rounds covered' if count>20 else ('All history covered' if complete else 'Partial history; older blocks pending')
        self.ui.insight_snapshot(4,rows,f'{coverage} | block {end}',
                                 note='Claimed HYBURN = actual claim events, not estimated allocation.')

    def run(self):
        while not self.stop.wait(.5):
            page=self.ui.page
            if page not in (3,4): continue
            if time.monotonic()<self.next_due[page]: continue
            self.ui.insight_status(page,'Reading snapshot; mining remains independent')
            try:
                if not self.checked_chain:
                    if self.request(page,lambda:self.w3.eth.chain_id)!=self.chain:
                        raise ValueError('Statistics RPC chain mismatch')
                    self.checked_chain=True
                block=self.request(page,lambda:self.w3.eth.get_block('latest'))
                self.ui.sync_chain(block['timestamp'], self.genesis, self.duration)
                if page==3:self.round_snapshot(block)
                else:self.history_snapshot(block)
            except Paused:
                continue
            except Exception:
                self.ui.insight_status(page,'Statistics unavailable; previous snapshot retained. Retry in 60s.')
            self.next_due[page]=time.monotonic()+60
