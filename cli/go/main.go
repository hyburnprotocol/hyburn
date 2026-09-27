package main

import (
	"context"
	"crypto/ecdsa"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"os"
	"os/signal"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/ethereum/go-ethereum"
	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/accounts/keystore"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/ethereum/go-ethereum/ethclient"
	"golang.org/x/term"
)

const (
	version    = "0.1.0"
	defaultRPC = "https://rpc.hyperliquid.xyz/evm"
	logChunk   = 1000
)

var (
	oneHype  = new(big.Int).Exp(big.NewInt(10), big.NewInt(18), nil)
	oneToken = new(big.Int).Exp(big.NewInt(10), big.NewInt(9), nil)
)

const minerABIJSON = `[
 {"type":"function","name":"genesisTimestamp","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"ROUND_DURATION","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"MIN_BURN","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"INITIAL_REWARD","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"HALVING_INTERVAL","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"TERMINAL_SEQUENCE","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"TERMINAL_REMAINDER","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"rounds","stateMutability":"view","inputs":[{"type":"uint256"}],"outputs":[{"type":"uint64","name":"miningSequence"},{"type":"uint128","name":"totalBurned"},{"type":"bool","name":"created"}]},
 {"type":"function","name":"previewCurrentRoundReward","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"nonEmptyRoundCount","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"totalHypeBurned","stateMutability":"view","inputs":[],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"burned","stateMutability":"view","inputs":[{"type":"uint256"},{"type":"address"}],"outputs":[{"type":"uint128"}]},
 {"type":"function","name":"claimed","stateMutability":"view","inputs":[{"type":"uint256"},{"type":"address"}],"outputs":[{"type":"bool"}]},
 {"type":"function","name":"claimable","stateMutability":"view","inputs":[{"type":"uint256"},{"type":"address"}],"outputs":[{"type":"uint256"}]},
 {"type":"function","name":"token","stateMutability":"view","inputs":[],"outputs":[{"type":"address"}]},
 {"type":"function","name":"burn","stateMutability":"payable","inputs":[{"type":"uint256"}],"outputs":[]},
 {"type":"function","name":"burnAndClaim","stateMutability":"payable","inputs":[{"type":"uint256"},{"type":"uint256[]"}],"outputs":[]},
 {"type":"function","name":"claimMany","stateMutability":"nonpayable","inputs":[{"type":"uint256[]"},{"type":"address"}],"outputs":[]},
 {"type":"event","name":"HypeBurned","anonymous":false,"inputs":[{"indexed":true,"type":"uint256","name":"roundId"},{"indexed":true,"type":"address","name":"account"},{"indexed":false,"type":"uint256","name":"amount"},{"indexed":false,"type":"uint128","name":"roundTotalBurned"}]}
]`
const tokenABIJSON = `[{"type":"function","name":"balanceOf","stateMutability":"view","inputs":[{"type":"address"}],"outputs":[{"type":"uint256"}]}]`

func commas(s string) string {
	n := len(s)
	if n <= 3 {
		return s
	}
	var b strings.Builder
	pre := n % 3
	if pre > 0 {
		b.WriteString(s[:pre])
	}
	for i := pre; i < n; i += 3 {
		if b.Len() > 0 {
			b.WriteByte(',')
		}
		b.WriteString(s[i : i+3])
	}
	return b.String()
}

func fmtUnits(x *big.Int, decimals, places int) string {
	base := new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(decimals)), nil)
	whole, frac := new(big.Int).DivMod(x, base, new(big.Int))
	s := commas(whole.String())
	if places > 0 {
		f := frac.String()
		f = strings.Repeat("0", decimals-len(f)) + f
		s += "." + f[:places]
	}
	return s
}
func fmtHype(w *big.Int, places int) string  { return fmtUnits(w, 18, places) }
func fmtToken(u *big.Int, places int) string { return fmtUnits(u, 9, places) }

func parseHype(s string) *big.Int {
	parts := strings.SplitN(s, ".", 2)
	whole := parts[0]
	frac := ""
	if len(parts) == 2 {
		frac = parts[1]
	}
	if whole == "" {
		whole = "0"
	}
	if len(frac) > 18 {
		die("too many decimals: " + s)
	}
	frac += strings.Repeat("0", 18-len(frac))
	v, ok := new(big.Int).SetString(whole+frac, 10)
	if !ok || v.Sign() < 0 {
		die("not a HYPE amount: " + s)
	}
	return v
}

func fmtClock(sec float64) string {
	if sec < 0 {
		sec = 0
	}
	t := int64(sec)
	d, r := t/86400, t%86400
	h, r := r/3600, r%3600
	m, s := r/60, r%60
	if d > 0 {
		return fmt.Sprintf("%dd %02d:%02d:%02d", d, h, m, s)
	}
	if h > 0 {
		return fmt.Sprintf("%d:%02d:%02d", h, m, s)
	}
	return fmt.Sprintf("%02d:%02d", m, s)
}

func pct(a, b *big.Int) string {
	if b.Sign() == 0 {
		return "-"
	}
	bp := new(big.Int).Div(new(big.Int).Mul(a, big.NewInt(10000)), b).Int64()
	return fmt.Sprintf("%d.%02d%%", bp/100, bp%100)
}

func logf(format string, a ...any) {
	fmt.Printf(time.Now().Format("2006-01-02 15:04:05 ")+format+"\n", a...)
}
func die(msg string) { fmt.Fprintln(os.Stderr, msg); os.Exit(1) }

type Hyburn struct {
	ctx         context.Context
	client      *ethclient.Client
	chainID     *big.Int
	minerAddr   common.Address
	minerABI    abi.ABI
	tokenABI    abi.ABI
	tokenAddr   common.Address
	deployBlock int64
	genesis     int64
	dur         int64
	minBurn     *big.Int
	initReward  *big.Int
	halving     *big.Int
	terminal    *big.Int
	remainder   *big.Int
	key         *ecdsa.PrivateKey
	address     common.Address
	offset      float64
	latestBlock uint64
	caches      map[string]*cacheFile
}

func (h *Hyburn) call(addr common.Address, a abi.ABI, method string, args ...any) []any {
	return h.callAt(nil, addr, a, method, args...)
}

func (h *Hyburn) callAt(block *big.Int, addr common.Address, a abi.ABI, method string, args ...any) []any {
	data, err := a.Pack(method, args...)
	if err != nil {
		die("pack " + method + ": " + err.Error())
	}
	out, err := h.client.CallContract(h.ctx, ethereum.CallMsg{To: &addr, Data: data}, block)
	if err != nil {
		die("call " + method + ": " + err.Error())
	}
	res, err := a.Unpack(method, out)
	if err != nil {
		die("unpack " + method + ": " + err.Error())
	}
	return res
}
func (h *Hyburn) mcall(method string, args ...any) []any {
	return h.call(h.minerAddr, h.minerABI, method, args...)
}
func (h *Hyburn) u256(method string, args ...any) *big.Int {
	return h.mcall(method, args...)[0].(*big.Int)
}

func newHyburn(rpc, miner string, chainID int64, deployBlock int64) *Hyburn {
	h := &Hyburn{ctx: context.Background(), deployBlock: deployBlock}
	c, err := ethclient.Dial(rpc)
	if err != nil {
		die("cannot reach RPC " + rpc)
	}
	h.client = c
	if !common.IsHexAddress(miner) {
		die("HYBURN_MINER is not set to a valid address")
	}
	h.minerAddr = common.HexToAddress(miner)
	if chainID != 0 {
		h.chainID = big.NewInt(chainID)
	} else {
		id, err := c.ChainID(h.ctx)
		if err != nil {
			die("cannot reach RPC " + rpc)
		}
		h.chainID = id
	}
	h.minerABI, _ = abi.JSON(strings.NewReader(minerABIJSON))
	h.tokenABI, _ = abi.JSON(strings.NewReader(tokenABIJSON))
	h.genesis = h.u256("genesisTimestamp").Int64()
	h.dur = h.u256("ROUND_DURATION").Int64()
	h.minBurn = h.u256("MIN_BURN")
	h.initReward = h.u256("INITIAL_REWARD")
	h.halving = h.u256("HALVING_INTERVAL")
	h.terminal = h.u256("TERMINAL_SEQUENCE")
	h.remainder = h.u256("TERMINAL_REMAINDER")
	h.tokenAddr = h.mcall("token")[0].(common.Address)
	h.syncTime()
	return h
}

func (h *Hyburn) syncTime() {
	hdr, err := h.client.HeaderByNumber(h.ctx, nil)
	if err != nil {
		die("rpc: " + err.Error())
	}
	h.offset = float64(hdr.Time) - float64(time.Now().UnixNano())/1e9
	h.latestBlock = hdr.Number.Uint64()
}
func (h *Hyburn) now() float64 { return float64(time.Now().UnixNano())/1e9 + h.offset }
func (h *Hyburn) roundOf(t float64) int64 {
	if t < float64(h.genesis) {
		return -1
	}
	return int64((t - float64(h.genesis)) / float64(h.dur))
}
func (h *Hyburn) roundEnd(rid int64) int64 { return h.genesis + (rid+1)*h.dur }
func (h *Hyburn) rewardForSeq(seq *big.Int) *big.Int {
	if seq.Cmp(h.terminal) >= 0 {
		return big.NewInt(0)
	}
	era := new(big.Int).Div(seq, h.halving).Uint64()
	r := new(big.Int).Rsh(h.initReward, uint(era))
	if seq.Cmp(new(big.Int).Sub(h.terminal, big.NewInt(1))) == 0 {
		r.Add(r, h.remainder)
	}
	return r
}

func (h *Hyburn) loadKey() {
	if ks := os.Getenv("HYBURN_KEYSTORE"); ks != "" {
		raw, err := os.ReadFile(ks)
		if err != nil {
			die("keystore: " + err.Error())
		}
		pw := os.Getenv("HYBURN_KEYSTORE_PASSWORD")
		if pw == "" {
			fmt.Fprint(os.Stderr, "keystore password: ")
			b, _ := term.ReadPassword(int(syscall.Stdin))
			fmt.Fprintln(os.Stderr)
			pw = string(b)
		}
		k, err := keystore.DecryptKey(raw, pw)
		if err != nil {
			die("keystore: " + err.Error())
		}
		h.key = k.PrivateKey
	} else if pk := os.Getenv("HYBURN_PRIVATE_KEY"); pk != "" {
		k, err := crypto.HexToECDSA(strings.TrimPrefix(pk, "0x"))
		if err != nil {
			die("bad private key")
		}
		h.key = k
	} else {
		die("no key: set HYBURN_KEYSTORE (encrypted JSON) or HYBURN_PRIVATE_KEY")
	}
	h.address = crypto.PubkeyToAddress(h.key.PublicKey)
}

type cacheEntry struct {
	Burned  string `json:"burned"`
	Total   string `json:"total"`
	Seq     int64  `json:"seq"`
	Claimed bool   `json:"claimed"`
}
type cacheFile struct {
	V         int                    `json:"v"`
	ScannedTo int64                  `json:"scannedTo"`
	Rounds    map[string]*cacheEntry `json:"rounds"`
}

func (h *Hyburn) cachePath(acct common.Address) string {
	d := os.Getenv("HYBURN_HOME")
	if d == "" {
		home, _ := os.UserHomeDir()
		d = filepath.Join(home, ".hyburn")
	}
	os.MkdirAll(d, 0o755)
	return filepath.Join(d, fmt.Sprintf("%s-%s-%s.json", h.chainID.String(), strings.ToLower(h.minerAddr.Hex()), strings.ToLower(acct.Hex())))
}

func (h *Hyburn) cache(acct common.Address) *cacheFile {
	if h.caches == nil {
		h.caches = map[string]*cacheFile{}
	}
	key := strings.ToLower(acct.Hex())
	if c, ok := h.caches[key]; ok {
		return c
	}
	c := &cacheFile{}
	if raw, err := os.ReadFile(h.cachePath(acct)); err == nil {
		json.Unmarshal(raw, c)
	}
	if c.V != 3 || c.Rounds == nil {
		c = &cacheFile{V: 3, ScannedTo: h.deployBlock - 1, Rounds: map[string]*cacheEntry{}}
	}
	h.caches[key] = c
	return c
}

func (h *Hyburn) save(acct common.Address) {
	raw, _ := json.Marshal(h.cache(acct))
	os.WriteFile(h.cachePath(acct), raw, 0o644)
}

func (h *Hyburn) myRounds(acct common.Address) []int64 {
	c := h.cache(acct)
	latest, _ := h.client.BlockNumber(h.ctx)
	ev := h.minerABI.Events["HypeBurned"].ID
	acctTopic := common.BytesToHash(common.LeftPadBytes(acct.Bytes(), 32))
	for a := c.ScannedTo + 1; a <= int64(latest); a += logChunk {
		b := a + logChunk - 1
		if b > int64(latest) {
			b = int64(latest)
		}
		logs, err := h.client.FilterLogs(h.ctx, ethereum.FilterQuery{FromBlock: big.NewInt(a), ToBlock: big.NewInt(b), Addresses: []common.Address{h.minerAddr}, Topics: [][]common.Hash{{ev}, nil, {acctTopic}}})
		if err != nil {
			die("logs: " + err.Error())
		}
		for _, l := range logs {
			k := new(big.Int).SetBytes(l.Topics[1].Bytes()).String()
			if _, ok := c.Rounds[k]; !ok {
				c.Rounds[k] = nil
			}
		}
	}
	c.ScannedTo = int64(latest)
	h.save(acct)
	var ids []int64
	for k := range c.Rounds {
		v, _ := strconv.ParseInt(k, 10, 64)
		ids = append(ids, v)
	}
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })
	return ids
}

type row struct {
	round, seq                    int64
	burned, total, reward, payout *big.Int
	claimed, ended                bool
}

func (h *Hyburn) roundRows(acct common.Address, ids []int64) []row {
	c := h.cache(acct)

	header, err := h.client.HeaderByNumber(h.ctx, nil)
	if err != nil {
		die("rpc: " + err.Error())
	}
	read := func(method string, args ...any) []any {
		return h.callAt(header.Number, h.minerAddr, h.minerABI, method, args...)
	}
	var rows []row
	for _, rid := range ids {
		k := strconv.FormatInt(rid, 10)
		e := c.Rounds[k]
		ended := header.Time >= uint64(h.roundEnd(rid))
		var b, total *big.Int
		var seq int64
		var cl bool
		switch {
		case e != nil && e.Claimed:
			b, _ = new(big.Int).SetString(e.Burned, 10)
			total, _ = new(big.Int).SetString(e.Total, 10)
			seq, cl = e.Seq, true
		case e != nil && ended && e.Total != "":
			b, _ = new(big.Int).SetString(e.Burned, 10)
			total, _ = new(big.Int).SetString(e.Total, 10)
			seq = e.Seq
			cl = read("claimed", big.NewInt(rid), acct)[0].(bool)
			e.Claimed = cl
		default:
			r := read("rounds", big.NewInt(rid))
			seq = int64(r[0].(uint64))
			total = r[1].(*big.Int)
			b = read("burned", big.NewInt(rid), acct)[0].(*big.Int)
			cl = read("claimed", big.NewInt(rid), acct)[0].(bool)
			if ended {
				c.Rounds[k] = &cacheEntry{Burned: b.String(), Total: total.String(), Seq: seq, Claimed: cl}
			}
		}
		reward := h.rewardForSeq(big.NewInt(seq))
		payout := big.NewInt(0)
		if total.Sign() > 0 {
			payout = new(big.Int).Div(new(big.Int).Mul(reward, b), total)
		}
		rows = append(rows, row{rid, seq, b, total, reward, payout, cl, ended})
	}
	h.save(acct)
	return rows
}

func (h *Hyburn) markClaimed(acct common.Address, ids []*big.Int) {
	c := h.cache(acct)
	for _, id := range ids {
		if e := c.Rounds[id.String()]; e != nil {
			e.Claimed = true
		}
	}
	h.save(acct)
}

func (h *Hyburn) claimableIDs(acct common.Address) []*big.Int {
	var ids []*big.Int
	for _, r := range h.roundRows(acct, h.myRounds(acct)) {
		if r.ended && !r.claimed && r.burned.Sign() > 0 {
			ids = append(ids, big.NewInt(r.round))
		}
	}
	return ids
}

func (h *Hyburn) send(method string, value *big.Int, dryRun bool, args ...any) (*types.Receipt, error) {
	data, err := h.minerABI.Pack(method, args...)
	if err != nil {
		die("pack: " + err.Error())
	}
	gas, err := h.client.EstimateGas(h.ctx, ethereum.CallMsg{From: h.address, To: &h.minerAddr, Value: value, Data: data})
	if err != nil {
		return nil, fmt.Errorf("would revert: %w", err)
	}
	gas = gas * 12 / 10
	hdr, _ := h.client.HeaderByNumber(h.ctx, nil)
	tip, err := h.client.SuggestGasTipCap(h.ctx)
	if err != nil || tip.Sign() == 0 {
		tip = big.NewInt(1)
	}
	maxFee := new(big.Int).Add(new(big.Int).Mul(hdr.BaseFee, big.NewInt(2)), tip)
	cost := new(big.Int).Add(value, new(big.Int).Mul(big.NewInt(int64(gas)), maxFee))
	bal, _ := h.client.BalanceAt(h.ctx, h.address, nil)
	if bal.Cmp(cost) < 0 {
		die(fmt.Sprintf("balance %s HYPE < needed %s HYPE (value + max gas)", fmtHype(bal, 4), fmtHype(cost, 4)))
	}
	if dryRun {
		logf("dry run: would send %s value=%s HYPE gas=%d maxFee=%s", method, fmtHype(value, 4), gas, maxFee)
		return nil, nil
	}
	nonce, _ := h.client.PendingNonceAt(h.ctx, h.address)
	tx := types.NewTx(&types.DynamicFeeTx{ChainID: h.chainID, Nonce: nonce, GasTipCap: tip, GasFeeCap: maxFee, Gas: gas, To: &h.minerAddr, Value: value, Data: data})
	signed, err := types.SignTx(tx, types.LatestSignerForChainID(h.chainID), h.key)
	if err != nil {
		die("sign: " + err.Error())
	}
	if err := h.client.SendTransaction(h.ctx, signed); err != nil {
		return nil, err
	}
	logf("sent %s", signed.Hash().Hex()[2:])
	deadline := time.Now().Add(180 * time.Second)
	for time.Now().Before(deadline) {
		rc, err := h.client.TransactionReceipt(h.ctx, signed.Hash())
		if err == nil {
			if rc.Status != 1 {
				die("transaction reverted: " + signed.Hash().Hex())
			}
			return rc, nil
		}
		time.Sleep(500 * time.Millisecond)
	}
	die("timed out waiting for receipt")
	return nil, nil
}

type opts struct {
	rpc, miner, account, amount, maxCost, budget string
	chainID, deployBlock, at, rounds             int64
	dryRun                                       bool
	cmd                                          string
}

func cmdStatus(h *Hyburn, o opts) {
	h.syncTime()
	t := h.now()
	rid := h.roundOf(t)
	fmt.Printf("chain          %s  block %s\n", h.chainID, commas(strconv.FormatUint(h.latestBlock, 10)))
	if rid < 0 {
		fmt.Printf("status         not started; round 0 opens in %s\n", fmtClock(float64(h.genesis)-t))
		fmt.Printf("first reward   %s HYBURN\n", fmtToken(h.rewardForSeq(big.NewInt(0)), 2))
		return
	}
	r := h.mcall("rounds", big.NewInt(rid))
	total := r[1].(*big.Int)
	reward := h.u256("previewCurrentRoundReward")
	fmt.Printf("round          %s  ends in %s\n", commas(strconv.FormatInt(rid, 10)), fmtClock(float64(h.roundEnd(rid))-t))
	fmt.Printf("issued         %s HYBURN\n", fmtToken(reward, 2))
	fmt.Printf("burned so far  %s HYPE\n", fmtHype(total, 4))
	per := "all of it"
	if total.Sign() > 0 {
		per = fmtToken(new(big.Int).Div(new(big.Int).Mul(reward, oneHype), total), 3) + " HYBURN"
	}
	fmt.Printf("per 1 HYPE     %s\n", per)
	fmt.Printf("min burn       %s HYPE\n", fmtHype(h.minBurn, 6))
	fmt.Printf("non-empty      %s rounds  |  all-time burned %s HYPE\n", commas(h.u256("nonEmptyRoundCount").String()), fmtHype(h.u256("totalHypeBurned"), 2))
	var acct common.Address
	switch {
	case o.account != "":
		acct = common.HexToAddress(o.account)
	case h.key != nil:
		acct = h.address
	default:
		return
	}
	mine := h.mcall("burned", big.NewInt(rid), acct)[0].(*big.Int)
	ids := h.claimableIDs(acct)
	cl := big.NewInt(0)
	for _, id := range ids {
		cl.Add(cl, h.u256("claimable", id, acct))
	}
	bal, _ := h.client.BalanceAt(h.ctx, acct, nil)
	tb := h.call(h.tokenAddr, h.tokenABI, "balanceOf", acct)[0].(*big.Int)
	fmt.Printf("account        %s\n", acct.Hex())
	fmt.Printf("  HYPE         %s\n", fmtHype(bal, 4))
	fmt.Printf("  HYBURN       %s\n", fmtToken(tb, 3))
	share := ""
	if total.Sign() > 0 {
		share = "  (" + pct(mine, total) + ")"
	}
	fmt.Printf("  this round   %s HYPE%s\n", fmtHype(mine, 4), share)
	fmt.Printf("  claimable    %s HYBURN in %d round(s)\n", fmtToken(cl, 3), len(ids))
}

func cmdHistory(h *Hyburn, o opts) {
	var acct common.Address
	if o.account != "" {
		acct = common.HexToAddress(o.account)
	} else if h.key != nil {
		acct = h.address
	} else {
		die("history needs --account or a key")
	}
	rows := h.roundRows(acct, h.myRounds(acct))
	if len(rows) == 0 {
		fmt.Println("no burns from this account")
		return
	}
	fmt.Printf("%10s %9s %16s %16s %8s %16s  status\n", "round", "seq", "you burned", "round total", "share", "HYBURN")
	for i := len(rows) - 1; i >= 0; i-- {
		r := rows[i]
		status := "open"
		if r.ended {
			if r.claimed {
				status = "claimed"
			} else {
				status = "claimable"
			}
		}
		fmt.Printf("%10s %9s %16s %16s %8s %16s  %s\n", commas(strconv.FormatInt(r.round, 10)), commas(strconv.FormatInt(r.seq, 10)), fmtHype(r.burned, 4), fmtHype(r.total, 4), pct(r.burned, r.total), fmtToken(r.payout, 3), status)
	}
}

func cmdClaim(h *Hyburn, o opts) {
	h.loadKey()
	ids := h.claimableIDs(h.address)
	if len(ids) == 0 {
		fmt.Println("nothing to claim")
		return
	}
	total := big.NewInt(0)
	for _, id := range ids {
		total.Add(total, h.u256("claimable", id, h.address))
	}
	logf("claiming %s HYBURN from %d round(s)", fmtToken(total, 3), len(ids))
	for i := 0; i < len(ids); i += 200 {
		j := i + 200
		if j > len(ids) {
			j = len(ids)
		}
		rc, err := h.send("claimMany", big.NewInt(0), o.dryRun, ids[i:j], h.address)
		if err != nil {
			die(err.Error())
		}
		if rc != nil {
			h.markClaimed(h.address, ids[i:j])
		}
	}
	if !o.dryRun {
		logf("done. HYBURN balance %s", fmtToken(h.call(h.tokenAddr, h.tokenABI, "balanceOf", h.address)[0].(*big.Int), 3))
	}
}

func doBurn(h *Hyburn, amount *big.Int, dryRun bool) bool {
	if amount.Cmp(h.minBurn) < 0 {
		die(fmt.Sprintf("amount below minimum %s HYPE", fmtHype(h.minBurn, 6)))
	}
	h.syncTime()
	rid := h.roundOf(h.now())
	if rid < 0 {
		die("not started yet")
	}
	ids := h.claimableIDs(h.address)
	extra := ""
	if len(ids) > 0 {
		extra = fmt.Sprintf(", claiming %d round(s)", len(ids))
	}
	logf("burn %s HYPE into round %s%s", fmtHype(amount, 4), commas(strconv.FormatInt(rid, 10)), extra)
	var rc *types.Receipt
	var err error
	if len(ids) > 0 {
		rc, err = h.send("burnAndClaim", amount, dryRun, big.NewInt(rid), ids)
	} else {
		rc, err = h.send("burn", amount, dryRun, big.NewInt(rid))
	}
	if err != nil {
		if strings.Contains(err.Error(), "RoundMismatch") {
			logf("round changed before the transaction landed; nothing was burned")
			return false
		}
		die(err.Error())
	}
	if rc != nil {
		if len(ids) > 0 {
			h.markClaimed(h.address, ids)
		}
		r := h.mcall("rounds", big.NewInt(rid))
		total := r[1].(*big.Int)
		mine := h.mcall("burned", big.NewInt(rid), h.address)[0].(*big.Int)
		logf("confirmed in block %s; round total %s HYPE, your share %s", commas(rc.BlockNumber.String()), fmtHype(total, 4), pct(mine, total))
	}
	return true
}

func cmdBurn(h *Hyburn, o opts) { h.loadKey(); doBurn(h, parseHype(o.amount), o.dryRun) }

func cmdMine(h *Hyburn, o opts) {
	h.loadKey()
	amount := parseHype(o.amount)
	if amount.Cmp(h.minBurn) < 0 {
		die(fmt.Sprintf("--amount below minimum %s HYPE", fmtHype(h.minBurn, 6)))
	}
	var maxCost, budget *big.Int
	if o.maxCost != "" {
		maxCost = parseHype(o.maxCost)
	}
	if o.budget != "" {
		budget = parseHype(o.budget)
	}
	spent := big.NewInt(0)
	burns := int64(0)
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt)
	desc := fmt.Sprintf("mining as %s: %s HYPE per round, send %ds before round end", h.address.Hex(), fmtHype(amount, 4), o.at)
	if maxCost != nil {
		desc += fmt.Sprintf(", max cost %s HYPE/HYBURN", fmtHype(maxCost, 6))
	}
	if budget != nil {
		desc += fmt.Sprintf(", budget %s HYPE", fmtHype(budget, 4))
	}
	if o.dryRun {
		desc += ", DRY RUN"
	}
	logf("%s", desc)
	lastRound := int64(-1)
	stopped := false
loop:
	for !stopped {
		select {
		case <-stop:
			break loop
		default:
		}
		h.syncTime()
		t := h.now()
		rid := h.roundOf(t)
		if rid < 0 {
			logf("not started; round 0 opens in %s", fmtClock(float64(h.genesis)-t))
			time.Sleep(time.Duration(min(60, max(1, float64(h.genesis)-t))) * time.Second)
			continue
		}
		if rid == lastRound {
			time.Sleep(time.Duration(min(5, max(0.5, float64(h.roundEnd(rid))-t+1)) * float64(time.Second)))
			continue
		}
		sendAt := float64(h.roundEnd(rid) - o.at)
		if t < sendAt {
			w := min(5, sendAt-t)
			if sendAt-t < 60 {
				w = 1
			}
			time.Sleep(time.Duration(w * float64(time.Second)))
			continue
		}
		lastRound = rid
		r := h.mcall("rounds", big.NewInt(rid))
		total := r[1].(*big.Int)
		reward := h.u256("previewCurrentRoundReward")
		if maxCost != nil && reward.Sign() > 0 {
			cost := new(big.Int).Div(new(big.Int).Mul(new(big.Int).Add(total, amount), oneToken), reward)
			if cost.Cmp(maxCost) > 0 {
				logf("round %s: cost %s HYPE/HYBURN > max %s; skipping", commas(strconv.FormatInt(rid, 10)), fmtHype(cost, 6), fmtHype(maxCost, 6))
				continue
			}
		}
		if budget != nil && new(big.Int).Add(spent, amount).Cmp(budget) > 0 {
			logf("budget reached (%s of %s HYPE); stopping", fmtHype(spent, 4), fmtHype(budget, 4))
			break
		}
		if doBurn(h, amount, o.dryRun) {
			spent.Add(spent, amount)
			burns++
			if o.rounds > 0 && burns >= o.rounds {
				logf("done: %d round(s)", burns)
				break
			}
		}
	}
	logf("mining stopped. burned %s HYPE in %d round(s)", fmtHype(spent, 4), burns)
}

func usage() {
	fmt.Println(`usage: hyburn [--rpc URL] [--miner ADDR] [--chain-id N] [--deploy-block N] <command>
  status [--account ADDR]
  burn <hype> [--dry-run]
  mine --amount HYPE [--max-cost HYPE] [--at SECONDS] [--budget HYPE] [--rounds N] [--dry-run]
      --max-cost: skip the round if HYPE per HYBURN, counting your burn, is above this at send time
                  (later burns by others in the same round still lower everyone's payout)
  claim [--dry-run]
  history [--account ADDR]`)
}

func envInt(k string) int64 { v, _ := strconv.ParseInt(os.Getenv(k), 10, 64); return v }

func main() {
	o := opts{rpc: os.Getenv("HYBURN_RPC"), miner: os.Getenv("HYBURN_MINER"), chainID: envInt("HYBURN_CHAIN_ID"), deployBlock: envInt("HYBURN_DEPLOY_BLOCK"), at: 30}
	if o.rpc == "" {
		o.rpc = defaultRPC
	}
	var pos []string
	args := os.Args[1:]
	for i := 0; i < len(args); i++ {
		a := args[i]
		next := func() string {
			i++
			if i >= len(args) {
				die("missing value for " + a)
			}
			return args[i]
		}
		switch a {
		case "--rpc":
			o.rpc = next()
		case "--miner":
			o.miner = next()
		case "--chain-id":
			o.chainID, _ = strconv.ParseInt(next(), 10, 64)
		case "--deploy-block":
			o.deployBlock, _ = strconv.ParseInt(next(), 10, 64)
		case "--account":
			o.account = next()
		case "--amount":
			o.amount = next()
		case "--max-cost":
			o.maxCost = next()
		case "--at":
			o.at, _ = strconv.ParseInt(next(), 10, 64)
		case "--budget":
			o.budget = next()
		case "--rounds":
			o.rounds, _ = strconv.ParseInt(next(), 10, 64)
		case "--dry-run":
			o.dryRun = true
		case "--version":
			fmt.Println(version)
			return
		case "-h", "--help":
			usage()
			return
		default:
			if strings.HasPrefix(a, "--") {
				die("unknown option " + a)
			}
			pos = append(pos, a)
		}
	}
	if len(pos) == 0 {
		usage()
		os.Exit(1)
	}
	o.cmd = pos[0]
	if o.cmd == "burn" {
		if len(pos) < 2 {
			die("burn needs an amount")
		}
		o.amount = pos[1]
	}
	if o.cmd == "mine" && o.amount == "" {
		die("mine needs --amount")
	}
	h := newHyburn(o.rpc, o.miner, o.chainID, o.deployBlock)
	if (o.cmd == "status" || o.cmd == "history") && o.account == "" && (os.Getenv("HYBURN_KEYSTORE") != "" || os.Getenv("HYBURN_PRIVATE_KEY") != "") {
		h.loadKey()
	}
	switch o.cmd {
	case "status":
		cmdStatus(h, o)
	case "burn":
		cmdBurn(h, o)
	case "mine":
		cmdMine(h, o)
	case "claim":
		cmdClaim(h, o)
	case "history":
		cmdHistory(h, o)
	default:
		usage()
		os.Exit(1)
	}
	_ = errors.New
}
