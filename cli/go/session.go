package main

import (
	"encoding/json"
	"fmt"
	"github.com/ethereum/go-ethereum"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
	"math/big"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"time"
)

type pendingTx struct {
	Hash   string `json:"hash"`
	Raw    string `json:"raw"`
	Value  string `json:"value"`
	Round  int64  `json:"round"`
	Mining bool   `json:"mining"`
}
type sessionState struct {
	V         int               `json:"v"`
	Identity  string            `json:"identity"`
	Settings  map[string]string `json:"settings"`
	Spent     string            `json:"spent"`
	Gas       string            `json:"gas"`
	Burns     int64             `json:"burns"`
	LastRound int64             `json:"last_round"`
	Pending   *pendingTx        `json:"pending"`
}
type Session struct {
	state sessionState
	path  string
	lock  net.Listener
}

func sessionHome() string {
	d := os.Getenv("HYBURN_HOME")
	if d == "" {
		h, e := os.UserHomeDir()
		if e != nil {
			die(e.Error())
		}
		d = filepath.Join(h, ".hyburn")
	}
	return d
}
func atomicJSON(path string, v any) {
	if e := os.MkdirAll(filepath.Dir(path), 0700); e != nil {
		die(e.Error())
	}
	b, e := json.Marshal(v)
	if e != nil {
		die(e.Error())
	}
	f, e := os.CreateTemp(filepath.Dir(path), ".session-")
	if e != nil {
		die(e.Error())
	}
	tmp := f.Name()
	defer os.Remove(tmp)
	if _, e = f.Write(b); e != nil {
		f.Close()
		die(e.Error())
	}
	if e = f.Sync(); e != nil {
		f.Close()
		die(e.Error())
	}
	if e = f.Close(); e != nil {
		die(e.Error())
	}
	if e = os.Rename(tmp, path); e != nil {
		die(e.Error())
	}
	d, e := os.Open(filepath.Dir(path))
	if e != nil {
		die(e.Error())
	}
	defer d.Close()
	if e = d.Sync(); e != nil {
		die(e.Error())
	}
}
func decimal(s string) *big.Int {
	v, ok := new(big.Int).SetString(s, 10)
	if !ok || v.Sign() < 0 {
		die("Invalid session amount; refusing budget reset")
	}
	return v
}
func (s *Session) save() { atomicJSON(s.path, s.state) }
func (h *Hyburn) openSession() *Session {
	if h.session != nil {
		return h.session
	}
	account := stringsLower(h.address.Hex())
	miner := stringsLower(h.minerAddr.Hex())
	n, _ := strconv.ParseInt(account[len(account)-4:], 16, 64)
	l, e := net.Listen("tcp4", fmt.Sprintf("127.0.0.1:%d", 32768+n%20000))
	if e != nil {
		die("Wallet already in use or local session lock unavailable; stop the other miner first.")
	}
	identity := h.chainID.String() + ":" + miner + ":" + account
	s := &Session{path: filepath.Join(sessionHome(), h.chainID.String()+"-"+miner+"-"+account+".session.json"), lock: l, state: sessionState{V: 1, Identity: identity, Settings: map[string]string{}, Spent: "0", Gas: "0", LastRound: -1}}
	b, e := os.ReadFile(s.path)
	if e == nil {
		if json.Unmarshal(b, &s.state) != nil || s.state.V != 1 || s.state.Identity != identity || s.state.Settings == nil || s.state.Burns < 0 || s.state.LastRound < -1 {
			die("Invalid session file; restore its backup. Refusing to reset the budget.")
		}
		decimal(s.state.Spent)
		decimal(s.state.Gas)
	} else if !os.IsNotExist(e) {
		die(e.Error())
	}
	h.session = s
	s.save()
	h.recoverSession()
	return s
}
func stringsLower(s string) string { // Addresses only, avoid locale differences.
	b := []byte(s)
	for i, c := range b {
		if c >= 'A' && c <= 'F' {
			b[i] = c + 32
		}
	}
	return string(b)
}
func (s *Session) configure(supplied map[string]string, fresh bool) map[string]string {
	if s.state.Pending != nil {
		die("Resolve the saved transaction before changing the session.")
	}
	settings := map[string]string{"amount": "", "budget": "", "max_cost": "", "at": "30", "rounds": "", "reserve": "1000000000000000"}
	if !fresh {
		for k, v := range s.state.Settings {
			settings[k] = v
		}
	}
	for k, v := range supplied {
		settings[k] = v
	}
	if settings["amount"] == "" {
		die("First run needs --amount. Later runs can use mine with no options.")
	}
	at, e := strconv.ParseInt(settings["at"], 10, 64)
	if e != nil || at < 1 || at > 998 || decimal(settings["amount"]).Sign() == 0 {
		die("Invalid mining settings; --at must be 1..998.")
	}
	decimal(settings["reserve"])
	for _, k := range []string{"budget", "max_cost", "rounds"} {
		if settings[k] != "" {
			v := decimal(settings[k])
			if k == "rounds" && (v.Sign() == 0 || !v.IsInt64()) {
				die("Invalid --rounds")
			}
		}
	}
	if settings["budget"] == "" {
		if settings["rounds"] == "" {
			die("First session needs --budget or --rounds; gas is additional.")
		}
		settings["budget"] = new(big.Int).Mul(decimal(settings["amount"]), decimal(settings["rounds"])).String()
	}
	if len(s.state.Settings) > 0 && !fresh {
		for k, v := range settings {
			if s.state.Settings[k] != v {
				die("Saved mining settings differ. Use --new-session with the full new settings to authorize a new budget.")
			}
		}
	}
	if fresh {
		atomicJSON(s.path[:len(s.path)-5]+".previous.json", s.state)
		s.state.Spent = "0"
		s.state.Gas = "0"
		s.state.Burns = 0
	}
	s.state.Settings = settings
	s.save()
	return settings
}
func (s *Session) prepare(tx *types.Transaction, value *big.Int, rid int64, mining bool) {
	if s.state.Pending != nil {
		die("Unresolved transaction; refusing another send.")
	}
	raw, e := tx.MarshalBinary()
	if e != nil {
		die(e.Error())
	}
	s.state.Pending = &pendingTx{tx.Hash().Hex(), "0x" + fmt.Sprintf("%x", raw), value.String(), rid, mining}
	s.save()
}
func (s *Session) settle(rc *types.Receipt) {
	p := s.state.Pending
	if p == nil || common.HexToHash(p.Hash) != rc.TxHash {
		die("Receipt does not match saved transaction.")
	}
	s.state.Gas = new(big.Int).Add(decimal(s.state.Gas), new(big.Int).Mul(new(big.Int).SetUint64(rc.GasUsed), rc.EffectiveGasPrice)).String()
	if rc.Status == 1 && decimal(p.Value).Sign() > 0 {
		s.state.LastRound = max(s.state.LastRound, p.Round)
		if p.Mining {
			s.state.Spent = new(big.Int).Add(decimal(s.state.Spent), decimal(p.Value)).String()
			s.state.Burns++
		}
	}
	s.state.Pending = nil
	s.save()
}
func (h *Hyburn) recoverSession() {
	p := h.session.state.Pending
	if p == nil {
		return
	}
	logf("Recovering saved transaction %s; no new transaction will be signed.", p.Hash)
	hash := common.HexToHash(p.Hash)
	rc, e := h.client.TransactionReceipt(h.ctx, hash)
	if e == ethereum.NotFound {
		raw := common.FromHex(p.Raw)
		if crypto.Keccak256Hash(raw) != hash {
			die("Invalid saved transaction; refusing broadcast.")
		}
		var tx types.Transaction
		if tx.UnmarshalBinary(raw) != nil {
			die("Invalid saved transaction")
		}
		_ = h.client.SendTransaction(h.ctx, &tx)
		deadline := time.Now().Add(180 * time.Second)
		for time.Now().Before(deadline) {
			rc, e = h.client.TransactionReceipt(h.ctx, hash)
			if e == nil {
				break
			}
			if e != ethereum.NotFound {
				die("RPC read failed; transaction remains saved")
			}
			time.Sleep(5 * time.Second)
		}
	}
	if e != nil {
		die("Saved transaction unresolved; restart to recover it.")
	}
	h.session.settle(rc)
	logf("Saved transaction settled; gas recorded.")
}

func loadProfile() {
	b, e := os.ReadFile(filepath.Join(sessionHome(), "config.json"))
	if os.IsNotExist(e) {
		return
	}
	if e != nil {
		die("Cannot read connection profile")
	}
	var values map[string]string
	if json.Unmarshal(b, &values) != nil || values == nil {
		die("Invalid connection profile")
	}
	for _, k := range []string{"HYBURN_RPC", "HYBURN_MINER", "HYBURN_CHAIN_ID", "HYBURN_DEPLOY_BLOCK", "HYBURN_KEYSTORE"} {
		if k == "HYBURN_KEYSTORE" && os.Getenv("HYBURN_PRIVATE_KEY") != "" {
			continue
		}
		if _, ok := os.LookupEnv(k); !ok {
			if v, ok := values[k]; ok {
				os.Setenv(k, v)
			}
		}
	}
}
