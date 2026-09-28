#!/usr/bin/env bash
set -euo pipefail
# Run only against a disposable local Anvil chain. These are PUBLIC Anvil test keys.
# Usage: cli/conformance/run.sh "node cli/node/hyburn.mjs"
read -r -a CLI <<< "${1:?provide a miner command}"
# Avoid inheriting a real wallet/chain configuration from the invoking shell.
unset HYBURN_KEYSTORE HYBURN_KEYSTORE_PASSWORD HYBURN_PRIVATE_KEY HYBURN_CHAIN_ID
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
S=$(mktemp -d "${TMPDIR:-/tmp}/hyburn-conformance.XXXXXX")
PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
RPC="http://127.0.0.1:$PORT"
K0=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
K1=0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d
K2=0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a
A1=0x70997970C51812dc3A010C7d01b50e0d17dc79C8

ANVIL=""
MINING_PID=""
stop_miner() {
  if [ -n "$MINING_PID" ]; then
    kill "$MINING_PID" 2>/dev/null || true
    wait "$MINING_PID" 2>/dev/null || true
    MINING_PID=""
  fi
}
cleanup() {
  result=$?
  stop_miner
  if [ -n "$ANVIL" ]; then
    kill "$ANVIL" 2>/dev/null || true
    wait "$ANVIL" 2>/dev/null || true
  fi
  if [ "$result" -eq 0 ]; then rm -rf "$S"; else echo "Test logs: $S" >&2; fi
}
trap cleanup EXIT
anvil --host 127.0.0.1 --chain-id 999 --port "$PORT" --block-time 1 --silent > "$S/anvil.log" 2>&1 &
ANVIL=$!
sleep 2
kill -0 "$ANVIL" || { cat "$S/anvil.log"; exit 1; }
OUT=$(forge create --root "$ROOT" src/HyburnMiner.sol:HyburnMiner --rpc-url "$RPC" --private-key "$K0" --broadcast --json)
MINER=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["deployedTo"])' <<< "$OUT")
DB=$(cast block-number --rpc-url $RPC)
GEN=$(cast call $MINER "genesisTimestamp()(uint256)" --rpc-url $RPC | awk '{print $1}')
export HYBURN_RPC=$RPC HYBURN_MINER=$MINER HYBURN_DEPLOY_BLOCK=$DB HYBURN_HOME="$S/home" HYBURN_PRIVATE_KEY=$K1
warp(){ cast rpc evm_increaseTime "$1" --rpc-url $RPC >/dev/null; cast rpc evm_mine --rpc-url $RPC >/dev/null; }
to_window(){ NOW=$(cast block latest --field timestamp --rpc-url $RPC | awk '{print $1}'); RID=$(( (NOW-GEN)/999 )); END=$(( GEN+(RID+1)*999 )); T=$(( END-$1+1 )); [ "$T" -le "$NOW" ] && T=$(( T+999 )); warp $(( T-NOW )); }
fail(){ echo "FAIL: $1"; exit 1; }
pass(){ echo "ok   $1"; }

echo "== conformance: ${CLI[*]}  (miner $MINER)"
grep -q "not started" <<<"$("${CLI[@]}" status 2>&1)" && pass "status before genesis" || fail "status before genesis"
"${CLI[@]}" burn 0.001 >/dev/null 2>&1 && fail "pre-genesis burn accepted" || pass "pre-genesis burn rejected"
NOW=$(cast block latest --field timestamp --rpc-url "$RPC" | awk '{print $1}')
warp $(( GEN-NOW ))
grep -q "round          0" <<<"$("${CLI[@]}" status 2>&1)" && pass "status shows round 0" || fail "status round 0"
"${CLI[@]}" burn 0.0001 >/dev/null 2>&1 && fail "burn below minimum accepted" || pass "burn below minimum rejected"
cast send $MINER "burn(uint256)" 0 --value 0.5ether --rpc-url $RPC --private-key $K2 >/dev/null
grep -q "your share 75.00%" <<<"$("${CLI[@]}" burn 1.5 2>&1)" && pass "burn 1.5 gives 75% share" || fail "burn share"
grep -q "open" <<<"$("${CLI[@]}" history 2>&1)" && pass "history shows open round" || fail "history open"
warp 999
grep -q "4,335.937" <<<"$("${CLI[@]}" claim 2>&1)" && pass "claim mints 4,335.937" || fail "claim amount"
grep -q "nothing to claim" <<<"$("${CLI[@]}" claim 2>&1)" && pass "second claim is a no-op" || fail "double claim"
CACHE="$S/home/999-$(echo "$MINER" | tr 'A-Z' 'a-z')-$(echo "$A1" | tr 'A-Z' 'a-z').json"
python3 -c "import json,sys; c=json.load(open(sys.argv[1])); e=c['rounds']['0']; assert c.get('v')==3 and e['claimed'] is True and int(e['burned'])==1500000000000000000 and int(e['total'])==2000000000000000000" "$CACHE" 2>/dev/null && pass "cache records the claimed round's final state (not re-queried)" || fail "cache format/state at $CACHE"
# Leave a 90s window after each artificial time jump so the 30s local
# resynchronization can observe it before the round closes.
"${CLI[@]}" mine --amount 0.3 --budget 1 --at 90 --max-cost 0.00001 > "$S/mineA.log" 2>&1 & MINING_PID=$!; sleep 2; to_window 90; sleep 35; stop_miner; sleep 1
grep -q "skipping" "$S/mineA.log" && pass "mine skips when cost above max-cost" || { cat "$S/mineA.log"; fail "max-cost skip"; }
"${CLI[@]}" mine --new-session --amount 0.3 --at 90 --rounds 2 > "$S/mineB.log" 2>&1 & MINING_PID=$!; sleep 2; to_window 90; sleep 35; to_window 90; sleep 35; stop_miner; sleep 1
[ "$(grep -c "confirmed in block" "$S/mineB.log")" = "2" ] && pass "mine burns in two rounds" || { cat "$S/mineB.log"; fail "mine two rounds"; }
grep -q "claiming 1 round" "$S/mineB.log" && pass "second burn claims the first round" || { cat "$S/mineB.log"; fail "auto-claim"; }
grep -q "done: 2 round" "$S/mineB.log" && pass "mine stops after --rounds" || fail "--rounds stop"
"${CLI[@]}" mine --new-session --amount 0.3 --at 90 --budget 0.5 > "$S/mineC.log" 2>&1 & MINING_PID=$!; sleep 2; to_window 90; sleep 35; to_window 90; sleep 35; stop_miner; sleep 1
[ "$(grep -c "confirmed in block" "$S/mineC.log")" = "1" ] && grep -q "budget reached" "$S/mineC.log" && pass "mine stops at budget after one burn" || { cat "$S/mineC.log"; fail "budget"; }
BAL=$(cast call $(cast call $MINER "token()(address)" --rpc-url $RPC) "balanceOf(address)(uint256)" $A1 --rpc-url $RPC | awk '{print $1}')
[ "$BAL" = "21679687500000" ] && pass "HYBURN balance 21,679.6875 after automatic final claim (rounds 0,1,2,3)" || fail "final balance $BAL"
[ "$(grep -c "claimable\|claimed" <<<"$("${CLI[@]}" history 2>&1)")" = "4" ] && pass "history lists 4 rounds" || fail "history count"
echo "== all checks passed"
