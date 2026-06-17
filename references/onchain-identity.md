# Onchain identity & reputation — ERC-8004 (planned)

Gclaw creatures can claim a **verifiable onchain identity** via **ERC-8004
("Trustless Agents")** — the Ethereum standard (live since 2026-01-29; authored
by MetaMask, the Ethereum Foundation, Google, and Coinbase) that gives AI agents
an onchain identity, reputation, and validation layer. This turns the game from
local state into a public, browsable registry of living agents.

## Why it fits Gclaw exactly

| ERC-8004 registry | Gclaw mapping |
|-------------------|---------------|
| **Identity** (ERC-721 per agent) | Each creature mints an identity holding its name, **DNA genome/fingerprint**, and managed wallet. Children mint their own → an **onchain family tree**. |
| **Reputation** | **Goodwill** becomes onchain reputation — earned from realized trading, Sybil-resistant, portable across apps. |
| **Validation** | Trade outcomes / PnL can be attested for crypto-economic verification. |

x402 (Coinbase's agent-payment protocol, already present in the original Gclaw)
settles agent payments and can auto-post reputation feedback — the
`0xgasless/agent-sdk` bundles ERC-8004 + x402 in one TypeScript SDK.

## Deployment (Base)

Base Sepolia testnet registries (free, for the beta):
- IdentityRegistry: `0x8004A818BFB912233c491871b3d84c89A494BD9e`
- ReputationRegistry: `0x8004B663056A597Dffe9eCcC1965A193B7388713`

Reference: <https://github.com/erc-8004/erc-8004-contracts> ·
SDK: <https://github.com/0xgasless/agent-sdk>

## Integration plan (tracked in beads)

1. **Register identity** — on first run (and per child birth), mint an ERC-8004
   identity from the control wallet on Base, with metadata = `{name, species,
   fingerprint, traits, managedWallet, dashboardURL}`. Store the returned agent id
   in `metabolism.json`.
2. **Publish the DNA** — host the dashboard / genome JSON as the agent card the
   identity points to (the creature's public face).
3. **Sync reputation** — after each profitable settle, post a reputation signal
   so onchain reputation tracks goodwill.
4. **Family tree onchain** — children register with a parent reference for a
   verifiable lineage and a public leaderboard.

## What's needed before building

- **Network choice:** Base **Sepolia** (free testnet — recommended for the beta)
  vs **Base mainnet** (real provenance, costs ETH gas).
- **Gas:** the control wallet (`0xA328…`) needs a little Base ETH (Sepolia ETH is
  free from a faucet).
- **Dependency:** add `0xgasless/agent-sdk` (ERC-8004 + x402) under `~/gdex-skill`'s
  node_modules or a dedicated helper dir; writes are signed locally like `gdex_sign.js`.

Until built, this is documented intent — no onchain writes happen yet.
