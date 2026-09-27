#!/usr/bin/env python3
import json
import sys
import urllib.request

ART = "out/HyburnMiner.sol/HyburnMiner.json"

def rpc(url, method, params):
    req = urllib.request.Request(url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(), headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=30))
    if "error" in r:
        raise SystemExit(f"rpc error: {r['error']}")
    return r["result"]

def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: verify_bytecode.py <miner address> [rpc]  (run forge build first)")
    addr = sys.argv[1]
    url = sys.argv[2] if len(sys.argv) > 2 else "https://rpc.hyperliquid.xyz/evm"
    art = json.load(open(ART))
    local = bytearray(bytes.fromhex(art["deployedBytecode"]["object"][2:]))
    refs = art["deployedBytecode"].get("immutableReferences", {})
    onchain = bytearray(bytes.fromhex(rpc(url, "eth_getCode", [addr, "latest"])[2:]))
    print(f"local runtime  {len(local)} bytes")
    print(f"onchain code   {len(onchain)} bytes")
    if len(local) != len(onchain):
        print("MISMATCH: different length")
        sys.exit(1)
    values = {}
    for ast_id, spans in refs.items():
        for sp in spans:
            s, l = sp["start"], sp["length"]
            values.setdefault(ast_id, set()).add(onchain[s:s + l].hex())
            local[s:s + l] = b"\0" * l
            onchain[s:s + l] = b"\0" * l
    if bytes(local) != bytes(onchain):
        first = next(i for i in range(len(local)) if local[i] != onchain[i])
        print(f"MISMATCH: code differs at byte {first} (outside immutables)")
        sys.exit(1)
    print("MATCH: deployed code equals the local build outside immutable slots")
    print("immutable values found on chain (each must be consistent and match the published deployment):")
    for ast_id, vals in values.items():
        for v in vals:
            n = int(v, 16)
            kind = f"uint {n}" if n < 2**64 else (f"address 0x{v[-40:]}" if n < 2**160 else f"uint {n}")
            print(f"  ast {ast_id}: {kind}")
        if len(vals) > 1:
            print(f"  WARNING: ast {ast_id} has inconsistent values across slots")
            sys.exit(1)

if __name__ == "__main__":
    main()
