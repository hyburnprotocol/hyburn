export const CONFIG = {
  chainId: Number(process.env.NEXT_PUBLIC_CHAIN_ID ?? 999),
  chainName: process.env.NEXT_PUBLIC_CHAIN_NAME ?? "HyperEVM",
  rpc: process.env.NEXT_PUBLIC_RPC ?? "https://rpc.hypurrscan.io",
  explorer: process.env.NEXT_PUBLIC_EXPLORER ?? "https://hyperevmscan.io",
  miner: process.env.NEXT_PUBLIC_MINER ?? "",
  token: process.env.NEXT_PUBLIC_TOKEN ?? "",
  vault: process.env.NEXT_PUBLIC_VAULT ?? "",
  deployBlock: process.env.NEXT_PUBLIC_DEPLOY_BLOCK ?? "",
  deployTx: process.env.NEXT_PUBLIC_DEPLOY_TX ?? "",
  commit: process.env.NEXT_PUBLIC_COMMIT ?? "",
  genesis: process.env.NEXT_PUBLIC_GENESIS ?? "",
  repo: process.env.NEXT_PUBLIC_REPO ?? "https://github.com/hyburnprotocol/hyburn",
};
