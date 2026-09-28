#!/usr/bin/env python3
import argparse
import getpass
import json
import os
import signal
import sys
import time
from decimal import Decimal
from pathlib import Path
from contextlib import nullcontext
import terminal_ui
from mining_session import Session

from eth_account import Account
from web3 import Web3
from web3.exceptions import ContractLogicError

VERSION = "0.2.0"
DEFAULT_RPC = "https://rpc.hypurrscan.io"
DEFAULT_CHAIN_ID = 999
LOG_CHUNK = 1000
ONE_HYPE = 10**18
ONE_TOKEN = 10**9

MINER_ABI = json.loads("""[
 {"type":"function","name":"currentRoundId","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"genesisTimestamp","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"ROUND_DURATION","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"MIN_BURN","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"INITIAL_REWARD","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"HALVING_INTERVAL","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"TERMINAL_SEQUENCE","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"TERMINAL_REMAINDER","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"rounds","stateMutability":"view","inputs":[{"type":"uint256"}],"outputs":[{"type":"uint64","name":"miningSequence"},{"type":"uint128","name":"totalBurned"},{"type":"bool","name":"created"}]},
 {"type":"function","name":"rewardForSequence","stateMutability":"pure","inputs":[{"type":"uint256"}],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"previewCurrentRoundReward","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"nonEmptyRoundCount","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"totalHypeBurned","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"burned","stateMutability":"view","inputs":[{"type":"uint256"},{"type":"address"}],"outputs":[{"type":"uint128"}]},
 {"type":"function","name":"claimed","stateMutability":"view","inputs":[{"type":"uint256"},{"type":"address"}],"outputs":[{"type":"bool"}]},
 {"type":"function","name":"claimable","stateMutability":"view","inputs":[{"type":"uint256"},{"type":"address"}],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"token","stateMutability":"view","inputs":[],"outputs":[{"type":"address"}]},
 {"type":"function","name":"burn","stateMutability":"payable","inputs":[{"type":"uint256","name":"expectedRoundId"}],"outputs":[]},
 {"type":"function","name":"burnAndClaim","stateMutability":"payable","inputs":[{"type":"uint256","name":"expectedRoundId"},{"type":"uint256[]","name":"claimRoundIds"}],"outputs":[]},
 {"type":"function","name":"claimMany","stateMutability":"nonpayable","inputs":[{"type":"uint256[]","name":"roundIds"},{"type":"address","name":"account"}],"outputs":[]},
 {"type":"event","name":"HypeBurned","anonymous":false,"inputs":[{"indexed":true,"type":"uint256","name":"roundId"},{"indexed":true,"type":"address","name":"account"},{"indexed":false,"type":"uint256","name":"amount"},{"indexed":false,"type":"uint128","name":"roundTotalBurned"}]}
]""")
TOKEN_ABI = json.loads('[{"type":"function","name":"balanceOf","stateMutability":"view","inputs":[{"type":"address"}],"outputs":[{"type":"uint256"}]}]')

def fmt_units(x: int, decimals: int, places: int) -> str:
    base = 10**decimals
    whole, frac = divmod(int(x), base)
    s = f"{whole:,}"
    if places:
        s += "." + str(frac).rjust(decimals, "0")[:places]
    return s

def fmt_hype(wei: int, places: int = 4) -> str:
    return fmt_units(wei, 18, places)

def fmt_token(units: int, places: int = 3) -> str:
    return fmt_units(units, 9, places)

def parse_hype(s: str) -> int:
    try:
        d = Decimal(s)
    except Exception:
        raise SystemExit(f"not a HYPE amount: {s}")
    if not d.is_finite() or d < 0 or d * ONE_HYPE != (d * ONE_HYPE).to_integral_value():
        raise SystemExit("amount must be positive")
    return int(d * ONE_HYPE)

def fmt_clock(sec: float) -> str:
    sec = max(0, int(sec))
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    if d:
        return f"{d}d {h:02}:{m:02}:{s:02}"
    if h:
        return f"{h}:{m:02}:{s:02}"
    return f"{m:02}:{s:02}"

def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S ") + msg, flush=True)

def wait_local(seconds, label, stop):
    """Display an estimated countdown without querying the chain."""
    log(f"{label}; local wait ~{int(seconds)}s, no RPC requests")
    deadline = time.monotonic() + max(0, seconds)
    recheck = time.monotonic() + min(30, max(0, seconds))
    tty = sys.stderr.isatty()
    dashboard = terminal_ui.current()
    display = dashboard.activity(lambda: f"{label} | ~{fmt_clock(deadline - time.monotonic())} | local countdown") if dashboard else nullcontext()
    try:
        with display:
            while not stop["flag"]:
                left = deadline - time.monotonic()
                if left <= 0 or time.monotonic() >= recheck:
                    break
                if tty:
                    print(f"\r\033[2K{label} | ~{fmt_clock(left)} | Ctrl-C to stop", end="", file=sys.stderr, flush=True)
                time.sleep(min(0.5, left))
    finally:
        if tty:
            print("\r\033[2K", end="", file=sys.stderr, flush=True)

class Hyburn:
    def __init__(self, rpc: str, miner: str, chain_id: int | None, deploy_block: int):
        self.w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 30}))
        if not self.w3.is_connected():
            raise SystemExit(f"cannot reach RPC {rpc}")
        actual_chain = self.w3.eth.chain_id
        if chain_id is not None and chain_id != actual_chain:
            raise SystemExit(f"RPC chain ID mismatch: expected {chain_id}, got {actual_chain}")
        self.chain_id = actual_chain
        if not Web3.is_address(miner):
            raise SystemExit("HYBURN_MINER is not set to a valid address")
        self.miner_addr = Web3.to_checksum_address(miner)
        self.miner = self.w3.eth.contract(address=self.miner_addr, abi=MINER_ABI)
        self.deploy_block = deploy_block
        c = self.miner.functions
        self.genesis = c.genesisTimestamp().call()
        self.dur = c.ROUND_DURATION().call()
        self.min_burn = c.MIN_BURN().call()
        self.init_reward = c.INITIAL_REWARD().call()
        self.halving = c.HALVING_INTERVAL().call()
        self.terminal = c.TERMINAL_SEQUENCE().call()
        self.remainder = c.TERMINAL_REMAINDER().call()
        self.token = self.w3.eth.contract(address=c.token().call(), abi=TOKEN_ABI)
        self.account = None
        self._offset = 0.0
        self.sync_time()

    def sync_time(self) -> None:
        b = self.w3.eth.get_block("latest")
        self._offset = b["timestamp"] - time.time()
        self.latest_block = b["number"]
        dashboard = terminal_ui.current()
        if dashboard:
            dashboard.sync_chain(b["timestamp"], self.genesis, self.dur)

    def now(self) -> float:
        return time.time() + self._offset

    def round_of(self, t: float) -> int:
        return int((t - self.genesis) // self.dur) if t >= self.genesis else -1

    def round_end(self, rid: int) -> int:
        return self.genesis + (rid + 1) * self.dur

    def reward_for_seq(self, seq: int) -> int:
        if seq >= self.terminal:
            return 0
        r = self.init_reward >> (seq // self.halving)
        if seq == self.terminal - 1:
            r += self.remainder
        return r

    def load_key(self) -> None:
        if self.account is not None:
            return
        ks = os.environ.get("HYBURN_KEYSTORE")
        pk = os.environ.get("HYBURN_PRIVATE_KEY")
        if ks:
            try:
                dashboard = terminal_ui.current()
                with dashboard.suspended() if dashboard else nullcontext():
                    pw = os.environ.get("HYBURN_KEYSTORE_PASSWORD") or getpass.getpass("keystore password: ")
                self.account = Account.from_key(Account.decrypt(json.loads(Path(ks).read_text()), pw))
            except Exception:
                raise SystemExit("Cannot unlock keystore; check the file and password.") from None
        elif pk:
            try:
                self.account = Account.from_key(pk)
            except Exception:
                raise SystemExit("Invalid private key; use a 32-byte hex key, not a seed phrase.") from None
        else:
            raise SystemExit("no key: set HYBURN_KEYSTORE (encrypted JSON) or HYBURN_PRIVATE_KEY")

    CACHE_V = 3

    def _cache_path(self, account: str) -> Path:
        d = Path(os.environ.get("HYBURN_HOME", Path.home() / ".hyburn"))
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{self.chain_id}-{self.miner_addr.lower()}-{account.lower()}.json"

    def _cache(self, account: str) -> dict:
        key = account.lower()
        if not hasattr(self, "_caches"):
            self._caches = {}
        if key not in self._caches:
            p = self._cache_path(account)
            c = json.loads(p.read_text()) if p.exists() else None
            if not c or c.get("v") != self.CACHE_V:
                c = {"v": self.CACHE_V, "scannedTo": self.deploy_block - 1, "rounds": {}}
            self._caches[key] = c
        return self._caches[key]

    def _save(self, account: str) -> None:
        self._cache_path(account).write_text(json.dumps(self._cache(account)))

    def my_rounds(self, account: str) -> list[int]:
        c = self._cache(account)
        latest = self.w3.eth.block_number
        a = c["scannedTo"] + 1
        ev = self.miner.events.HypeBurned
        while a <= latest:
            b = min(a + LOG_CHUNK - 1, latest)
            for lg in ev.get_logs(from_block=a, to_block=b, argument_filters={"account": Web3.to_checksum_address(account)}):
                c["rounds"].setdefault(str(int(lg["args"]["roundId"])), None)
            a = b + 1
        c["scannedTo"] = latest
        self._save(account)
        return sorted(int(k) for k in c["rounds"])

    def round_rows(self, account: str, ids: list[int]) -> list[dict]:
        c = self._cache(account)

        block = self.w3.eth.get_block("latest")
        t = block["timestamp"]
        block_id = block["number"]
        rows = []
        for rid in ids:
            e = c["rounds"].get(str(rid))
            ended = t >= self.round_end(rid)
            if e and e.get("claimed"):
                b, total, seq, cl = int(e["burned"]), int(e["total"]), e["seq"], True
            elif e and ended and "total" in e:
                b, total, seq = int(e["burned"]), int(e["total"]), e["seq"]
                cl = self.miner.functions.claimed(rid, account).call(block_identifier=block_id)
                e["claimed"] = cl
            else:
                seq, total, _ = self.miner.functions.rounds(rid).call(block_identifier=block_id)
                b = self.miner.functions.burned(rid, account).call(block_identifier=block_id)
                cl = self.miner.functions.claimed(rid, account).call(block_identifier=block_id)
                if ended:
                    c["rounds"][str(rid)] = {"burned": str(b), "total": str(total), "seq": seq, "claimed": cl}
            reward = self.reward_for_seq(seq)
            payout = reward * b // total if total else 0
            rows.append({"round": rid, "seq": seq, "burned": b, "total": total, "reward": reward, "payout": payout, "claimed": cl, "ended": ended})
        self._save(account)
        return rows

    def mark_claimed(self, account: str, ids: list[int]) -> None:
        c = self._cache(account)
        for rid in ids:
            e = c["rounds"].get(str(rid))
            if e:
                e["claimed"] = True
        self._save(account)

    def claimable_ids(self, account: str) -> list[int]:
        return [r["round"] for r in self.round_rows(account, self.my_rounds(account)) if r["ended"] and not r["claimed"] and r["burned"] > 0]

    def open_session(self):
        if not hasattr(self, 'session'):
            self.session = Session(self.chain_id, self.miner_addr, self.account.address)
            self.session.recover(self.w3)
        return self.session

    def send(self, fn, value: int = 0, dry_run: bool = False) -> dict | None:
        acct = self.account
        if not dry_run:
            self.open_session()
            if self.w3.eth.get_transaction_count(acct.address, 'pending') != self.w3.eth.get_transaction_count(acct.address, 'latest'):
                raise SystemExit('Wallet has another pending transaction; wait for it before continuing.')
        tx = fn.build_transaction({"from": acct.address, "value": value, "chainId": self.chain_id, "nonce": self.w3.eth.get_transaction_count(acct.address)})
        try:
            gas = self.w3.eth.estimate_gas(tx)
        except ContractLogicError as e:
            raise SystemExit(f"would revert: {e}")
        tx["gas"] = int(gas * 12 // 10)
        fee = self.w3.eth.fee_history(1, "latest", [50])
        base = fee["baseFeePerGas"][-1]
        tip = max(fee["reward"][0][0], 1)
        tx["maxPriorityFeePerGas"] = tip
        tx["maxFeePerGas"] = base * 2 + tip
        cost = value + tx["gas"] * tx["maxFeePerGas"]
        bal = self.w3.eth.get_balance(acct.address)
        reserve = getattr(self, 'reserve', 0) if value else 0
        cost += reserve
        if bal < cost:
            raise SystemExit(f"balance {fmt_hype(bal)} HYPE < needed {fmt_hype(cost)} HYPE (value + max gas)")
        if dry_run:
            log(f"dry run: would send {fn.fn_name} value={fmt_hype(value)} HYPE gas={tx['gas']} maxFee={tx['maxFeePerGas']}")
            return None
        if getattr(self, "should_stop", lambda: False)():
            raise SystemExit("Stopped before signing; session preserved.")
        signed = acct.sign_transaction(tx)
        rid = int(fn.args[0]) if value else -1
        self.session.prepare(signed.raw_transaction, value, rid, getattr(self, 'mining', False))
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        log(f"sent {h.hex()}")
        rc = self.w3.eth.wait_for_transaction_receipt(h, timeout=180, poll_latency=5)
        self.session.settle(rc)
        if rc["status"] != 1:
            raise SystemExit(f"transaction reverted: {h.hex()}")
        return rc

def cmd_status(hb: Hyburn, args) -> None:
    hb.sync_time()
    t = hb.now()
    rid = hb.round_of(t)
    print(f"chain          {hb.chain_id}  block {hb.latest_block:,}")
    if rid < 0:
        print(f"status         not started; round 0 opens in {fmt_clock(hb.genesis - t)}")
        print(f"first reward   {fmt_token(hb.reward_for_seq(0), 2)} HYBURN")
        return
    seq, total, created = hb.miner.functions.rounds(rid).call()
    reward = hb.miner.functions.previewCurrentRoundReward().call()
    left = hb.round_end(rid) - t
    print(f"round          {rid:,}  ends in {fmt_clock(left)}")
    print(f"issued         {fmt_token(reward, 2)} HYBURN")
    print(f"burned so far  {fmt_hype(total)} HYPE")
    print(f"per 1 HYPE     {'all of it' if total == 0 else fmt_token(reward * ONE_HYPE // total) + ' HYBURN'}")
    print(f"min burn       {fmt_hype(hb.min_burn, 6)} HYPE")
    print(f"non-empty      {hb.miner.functions.nonEmptyRoundCount().call():,} rounds  |  all-time burned {fmt_hype(hb.miner.functions.totalHypeBurned().call(), 2)} HYPE")
    acct = args.account or (hb.account.address if hb.account else None)
    if acct:
        acct = Web3.to_checksum_address(acct)
        mine = hb.miner.functions.burned(rid, acct).call()
        ids = hb.claimable_ids(acct)
        cl = sum(hb.miner.functions.claimable(r, acct).call() for r in ids)
        print(f"account        {acct}")
        print(f"  HYPE         {fmt_hype(hb.w3.eth.get_balance(acct))}")
        print(f"  HYBURN       {fmt_token(hb.token.functions.balanceOf(acct).call())}")
        print(f"  this round   {fmt_hype(mine)} HYPE" + (f"  ({mine * 10000 // total / 100:.2f}%)" if total else ""))
        print(f"  claimable    {fmt_token(cl)} HYBURN in {len(ids)} round(s)")

def cmd_history(hb: Hyburn, args) -> None:
    acct = Web3.to_checksum_address(args.account or hb.account.address)
    rows = hb.round_rows(acct, hb.my_rounds(acct))
    if not rows:
        print("no burns from this account")
        return
    print(f"{'round':>10} {'seq':>9} {'you burned':>16} {'round total':>16} {'share':>8} {'HYBURN':>16}  status")
    for r in reversed(rows):
        share = f"{r['burned'] * 10000 // r['total'] / 100:.2f}%" if r["total"] else "-"
        status = "open" if not r["ended"] else ("claimed" if r["claimed"] else "claimable")
        print(f"{r['round']:>10,} {r['seq']:>9,} {fmt_hype(r['burned']):>16} {fmt_hype(r['total']):>16} {share:>8} {fmt_token(r['payout']):>16}  {status}")

def cmd_claim(hb: Hyburn, args) -> None:
    hb.load_key()
    if not args.dry_run:
        hb.open_session()
    acct = hb.account.address
    ids = hb.claimable_ids(acct)
    if not ids:
        print("nothing to claim")
        return
    total = sum(hb.miner.functions.claimable(r, acct).call() for r in ids)
    log(f"claiming {fmt_token(total)} HYBURN from {len(ids)} round(s)")
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        if hb.send(hb.miner.functions.claimMany(batch, acct), dry_run=args.dry_run) is not None:
            hb.mark_claimed(acct, batch)
    if not args.dry_run:
        log(f"done. HYBURN balance {fmt_token(hb.token.functions.balanceOf(acct).call())}")

def do_burn(hb: Hyburn, amount: int, dry_run: bool, expected_round=None) -> bool:
    if amount < hb.min_burn:
        raise SystemExit(f"amount below minimum {fmt_hype(hb.min_burn, 6)} HYPE")
    hb.sync_time()
    rid = hb.round_of(hb.now())
    if rid < 0:
        raise SystemExit("not started yet")
    if expected_round is not None and rid != expected_round:
        log("Round changed during preflight; checking the new round before signing.")
        return False
    ids = hb.claimable_ids(hb.account.address)
    fn = hb.miner.functions.burnAndClaim(rid, ids) if ids else hb.miner.functions.burn(rid)
    log(f"burn {fmt_hype(amount)} HYPE into round {rid:,}" + (f", claiming {len(ids)} round(s)" if ids else ""))
    try:
        rc = hb.send(fn, value=amount, dry_run=dry_run)
    except SystemExit as e:
        if "RoundMismatch" in str(e):
            log("round changed before the transaction landed; nothing was burned")
            return False
        raise
    if rc is not None:
        if ids:
            hb.mark_claimed(hb.account.address, ids)
        seq, total, _ = hb.miner.functions.rounds(rid).call()
        mine = hb.miner.functions.burned(rid, hb.account.address).call()
        log(f"confirmed in block {rc['blockNumber']:,}; round total {fmt_hype(total)} HYPE, your share {mine * 10000 // total / 100:.2f}%")
    return True

def cmd_burn(hb: Hyburn, args) -> None:
    hb.load_key()
    do_burn(hb, parse_hype(args.amount), args.dry_run)

def cmd_mine(hb: Hyburn, args) -> None:
    hb.load_key()
    if not args.dry_run:
        session = hb.open_session()
        supplied = {k: (str(parse_hype(getattr(args, k))) if k in ('amount', 'budget', 'max_cost', 'reserve') else str(getattr(args, k))) if getattr(args, k) is not None else None for k in ('amount', 'budget', 'max_cost', 'at', 'rounds', 'reserve')}
        settings = session.configure(supplied, args.new_session)
        amount = int(settings['amount'])
        max_cost = int(settings['max_cost']) if settings['max_cost'] else None
        budget = int(settings['budget']) if settings['budget'] else None
        args.at = int(settings['at'])
        args.rounds = int(settings['rounds']) if settings['rounds'] else None
        hb.reserve = int(settings['reserve'])
        hb.mining = True
        spent, burns = int(session.state['spent']), session.state['burns']
        log(f'Resuming saved session: {burns} burns, {fmt_hype(spent, 9)} HYPE burned; gas {fmt_hype(int(session.state["gas"]), 9)} HYPE')
    else:
        if args.amount is None:
            raise SystemExit('--dry-run needs --amount')
        amount = parse_hype(args.amount)
        max_cost = parse_hype(args.max_cost) if args.max_cost else None
        budget = parse_hype(args.budget) if args.budget else None
        args.at = args.at if args.at is not None else 30
        spent = burns = 0
    if not 0 < args.at < hb.dur or (args.rounds is not None and args.rounds <= 0):
        raise SystemExit('--at must be within the round; --rounds must be positive')
    if amount < hb.min_burn:
        raise SystemExit(f"--amount below minimum {fmt_hype(hb.min_burn, 6)} HYPE")
    stop = {"flag": False}
    hb.should_stop = lambda: stop["flag"]
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("flag", True))
    log(f"mining as {hb.account.address}: {fmt_hype(amount)} HYPE per round, send {args.at}s before round end"
        + (f", max cost {fmt_hype(max_cost, 6)} HYPE/HYBURN" if max_cost else "")
        + (f", budget {fmt_hype(budget)} HYPE" if budget else "") + (", DRY RUN" if args.dry_run else ""))
    dashboard = terminal_ui.current()
    if dashboard:
        dashboard.update(Wallet=hb.account.address, Miner=hb.miner_addr, Chain=hb.chain_id,
                         **{'Burn / round': f'{fmt_hype(amount, 9)} HYPE + gas',
                            'Burn budget': f'{fmt_hype(budget, 9)} HYPE (gas extra)' if budget is not None else 'Not set',
                            'Mode': 'DRY RUN' if args.dry_run else 'LIVE',
                            'Send window': f'{args.at}s before round end',
                            'Session burns': burns, 'Burn spending': f'{fmt_hype(spent, 9)} HYPE (gas extra)'})
        if not args.dry_run:
            dashboard.update(**{'Protected reserve': f'{fmt_hype(hb.reserve, 9)} HYPE',
                                'Session gas': f'{fmt_hype(int(hb.session.state["gas"]), 9)} HYPE',
                                'Session file': hb.session.path})
    last_round = hb.session.state['last_round'] if not args.dry_run else -1
    while not stop["flag"]:
        if budget is not None and spent + amount > budget:
            log(f"budget reached ({fmt_hype(spent)} of {fmt_hype(budget)} HYPE); stopping")
            break
        if args.rounds and burns >= args.rounds:
            log(f'done: {burns} round(s)'); break
        log("Synchronizing chain time and checking round...")
        hb.sync_time()
        t = hb.now()
        rid = hb.round_of(t)
        if dashboard:
            dashboard.update(**{'Round (last read)': rid, 'Block (last read)': hb.latest_block})
        if rid < 0:
            log(f"not started; round 0 opens in {fmt_clock(hb.genesis - t)}")
            wait_local(max(1, hb.genesis - t), "Waiting for genesis", stop)
            continue
        if rid == last_round:
            wait_local(max(0.5, hb.round_end(rid) - t + 1), f"Next round {rid + 1}", stop)
            continue
        send_at = hb.round_end(rid) - args.at
        if t < send_at:

            wait_local(send_at - t, f"Round {rid}: waiting for send window", stop)
            continue

        last_round = rid
        if not args.dry_run and hb.miner.functions.burned(rid, hb.account.address).call() > 0:
            log(f'round {rid}: wallet already burned; skipping duplicate')
            continue
        seq, total, _ = hb.miner.functions.rounds(rid).call()
        reward = hb.miner.functions.previewCurrentRoundReward().call()
        cost = (total + amount) * ONE_TOKEN // reward if reward else None
        if max_cost is not None and cost is not None and cost > max_cost:
            log(f"round {rid:,}: cost {fmt_hype(cost, 6)} HYPE/HYBURN > max {fmt_hype(max_cost, 6)}; skipping")
            continue
        if budget is not None and spent + amount > budget:
            log(f"budget reached ({fmt_hype(spent)} of {fmt_hype(budget)} HYPE); stopping")
            break
        try:
            if do_burn(hb, amount, args.dry_run, rid):
                if args.dry_run:
                    spent += amount; burns += 1
                else:
                    spent, burns = int(hb.session.state['spent']), hb.session.state['burns']
                if dashboard:
                    dashboard.update(**{'Session burns': burns, 'Burn spending': f'{fmt_hype(spent, 9)} HYPE (gas extra)'})
                    if not args.dry_run:
                        dashboard.update(**{'Session gas': f'{fmt_hype(int(hb.session.state["gas"]), 9)} HYPE'})
                if args.rounds and burns >= args.rounds:
                    log(f"done: {burns} round(s)")
                    break
        except SystemExit as e:
            log(f"stopped: {e}")
            raise
    if not args.dry_run and not stop['flag']:
        final_round = hb.session.state['last_round']
        while final_round >= 0 and not stop['flag']:
            hb.sync_time()
            left = hb.round_end(final_round) - hb.now()
            if left <= 0:
                break
            wait_local(left, 'Budget complete; waiting to claim final rewards', stop)
        if not stop['flag']:
            cmd_claim(hb, args)
    log(f"mining stopped. burned {fmt_hype(spent)} HYPE in {burns} round(s)")

def main() -> None:
    from setup_miner import load_profile, main as setup
    if sys.argv[1:] == ["setup"]:
        setup(); return
    load_profile()
    p = argparse.ArgumentParser(prog="hyburn", description="Hyburn miner (reference implementation)")
    p.add_argument("--plain", action="store_true", help="disable the interactive mining dashboard")
    p.add_argument("--rpc", default=os.environ.get("HYBURN_RPC", DEFAULT_RPC))
    p.add_argument("--miner", default=os.environ.get("HYBURN_MINER", ""), help="HyburnMiner contract address")
    p.add_argument("--chain-id", type=int, default=int(os.environ.get("HYBURN_CHAIN_ID", 0)) or None)
    p.add_argument("--deploy-block", type=int, default=int(os.environ.get("HYBURN_DEPLOY_BLOCK", 0)), help="block of the deployment; log scans start here")
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="current round and protocol state")
    s.add_argument("--account", help="show this account's position (default: your key's address if set)")
    s.set_defaults(fn=cmd_status, needs_key=False)

    s = sub.add_parser("burn", help="burn once into the current round (claims finished rounds too)")
    s.add_argument("amount", help="HYPE to burn, e.g. 0.5")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_burn, needs_key=True)

    s = sub.add_parser("mine", help="burn every round until stopped")
    s.add_argument("--amount", help="HYPE per round (saved for resume)")
    s.add_argument("--max-cost", help="only burn if HYPE per HYBURN, counting your burn, is at or below this at send time; later burns by others in the same round still lower everyone's payout")
    s.add_argument("--at", type=int, help="seconds before round end to send (default 30)")
    s.add_argument("--budget", help="saved session burn budget; gas extra")
    s.add_argument("--reserve", help="HYPE balance protected for gas (default 0.001)")
    s.add_argument("--new-session", action="store_true", help="explicitly start a new budget after recovering pending transactions")
    s.add_argument("--rounds", type=int, help="stop after this many burns")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_mine, needs_key=True)

    s = sub.add_parser("claim", help="claim every finished round you took part in")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_claim, needs_key=True)

    s = sub.add_parser("history", help="your rounds")
    s.add_argument("--account")
    s.set_defaults(fn=cmd_history, needs_key=False)

    args = p.parse_args()
    with terminal_ui.Dashboard(enabled=args.cmd == "mine" and not args.plain) as dashboard:
        with dashboard.activity('Connecting to RPC and verifying chain parameters'):
            hb = Hyburn(args.rpc, args.miner, args.chain_id, args.deploy_block)
        if args.cmd in ("status", "history") and not args.account and (os.environ.get("HYBURN_KEYSTORE") or os.environ.get("HYBURN_PRIVATE_KEY")):
            hb.load_key()
        if args.cmd == "history" and not args.account and not hb.account:
            raise SystemExit("history needs --account or a key")
        args.fn(hb, args)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print('Stopped. Saved transactions will be checked on restart.', file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f'Operation failed ({type(error).__name__}). Existing session kept; restore RPC/file access and restart to recover.', file=sys.stderr)
        raise SystemExit(1) from None
