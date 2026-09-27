# Hyburn miner (Rust)

```bash
cargo build --release
export HYBURN_MINER=0x... HYBURN_DEPLOY_BLOCK=123456
export HYBURN_KEYSTORE=~/.hyburn/miner.json   # or HYBURN_PRIVATE_KEY
./target/release/hyburn status
./target/release/hyburn mine --amount 0.5 --max-cost 0.002 --at 30 --budget 50
```

Single static binary. Dependency: alloy. Same commands and output as the Python reference; see `../README.md`.
