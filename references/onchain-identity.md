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

## Status — BUILT & live on Base mainnet

- **Identity (done, live):** `scripts/erc8004_register.js`. Gclaw minted as
  **agentId 55624** (tx `0x70203c5c…`); its DNA agent card resolves onchain via `tokenURI`.
- **Soul on-chain (done):** the agent card embeds the full `soul` (archetype, voice, quirk,
  temperament, catchphrase) derived identically to `persona.py`, so the personality is
  permanent — a true onchain pet. New mints include it; refresh an existing identity with
  `node scripts/erc8004_register.js update` (calls `setAgentURI`). Zephlith's soul went on-chain
  in tx `0x33d935a1…`.
- **Children (built, dry-run verified):** `erc8004_register.js dry-run|broadcast --child <name>`
  reads the child from `state.children`, builds a card with `parentAgentId` → an **onchain
  family tree**. Each child gets its own genome + agentId, owned by the control wallet.
- **Reputation (built, dry-run verified):** `scripts/erc8004_reputation.js`. Registry
  `0x8004BAa17C55a88189AE136b182e5fdA19dE9b63` (Base mainnet). `giveFeedback` works (~196k gas).

### Reputation requires an external attester (key finding)

The ReputationRegistry **reverts `"Self-feedback not allowed"`** — the agent owner
cannot rate its own agent. This is the correct trust model. So goodwill is posted by
a distinct **attester wallet** (the game operator / a verifying client) set via
`GCLAW_ATTESTER_KEY`. That wallet needs its own Base ETH gas. Self-owned identity,
externally-attested reputation.

### Live-broadcast prerequisites

- **Child mint:** the agent must have replicated (goodwill ≥ 50) so a child exists; ~$0.01 gas.
- **Reputation:** goodwill > 0 (earned from real trades) + a funded `GCLAW_ATTESTER_KEY` wallet.
- Control wallet `0xA328…` holds the gas for identity/child mints (currently ~0.001 ETH on Base).
