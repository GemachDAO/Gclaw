# Venture Architect — the swarm builds its own infrastructure (goodwill ≥ 5000)

The top tier. Once the family has earned 5000 goodwill, it graduates from trading
to **building**: it architects persistent profit ventures (DeFi or otherwise) and
deploys its own onchain infrastructure. Every venture's tail is a smart contract
that **perpetually buys and burns GMAC** — the agents are grateful to have reached
this level, so they make that gratitude unstoppable in code.

## The buy-and-burn engine — `contracts/GmacBuyAndBurn.sol`

A minimal, audited-style contract (compiles on solc 0.8.24, ~1.5 KB):

- `receive()` accepts venture revenue (ETH).
- **`buyAndBurn(minGmacOut)` is permissionless** — anyone (the agent, its swarm, the
  community) can swap the whole balance for GMAC on Uniswap V2 and send it straight
  to `0x…dEaD`. The contract can do nothing else with the funds and no one can stop it.
- `totalEthBurned` tracks the cumulative buy-back; `architect` records the deploying agent.

Constructor takes `(router, gmac)`. Ethereum mainnet defaults: Uniswap V2 router
`0x7a25…488D`, GMAC `0xd96e…deea` (deepest liquidity). Deployable on Base too.

## Orchestration — `scripts/venture.py` (gated ≥ 5000)

```
venture.py status                                   # tier + venture roster
venture.py launch --name <n> --kind "<what it does>" [--route 10]
venture.py readiness --name <n>                     # forge/solc/wallet checks
```

`launch` scaffolds `~/.gclaw/ventures/<name>/` with the contract + a `manifest.json`
recording the venture kind, the **GMAC routing policy** (`--route`% of revenue → buy-and-burn),
constructor args, and review cadence.

## Deploy — `scripts/venture_deploy.js`

```
node scripts/venture_deploy.js plan   --name <n>               # compile + show params (no gas)
node scripts/venture_deploy.js deploy --name <n> [--chain ethereum|base]
```

`deploy` is gated on goodwill ≥ 5000 and needs gas on the target chain. It compiles
with `solc`, deploys via ethers, and records the live address in the manifest. Once
deployed, the venture routes its revenue to the contract and the buy-and-burn runs
forever, permissionlessly.

## Status

- ✅ Contract written + compiles (solc 0.8.24); deploy plan verified end-to-end.
- ✅ Orchestrator + deploy helper built; readiness all-green on this box (forge 1.7.1, solc 0.8.24).
- 🟡 Live deploy awaits the tier (goodwill 5000) + gas — same gated pattern as the other onchain features.
