# Gclaw Onchain — verify everything yourself

[![Built on Base](https://img.shields.io/badge/Built%20on-Base-0052FF?logo=coinbase&logoColor=white)](https://base.org)
[![ERC-8004](https://img.shields.io/badge/Standard-ERC--8004%20Agent%20Identity-0052FF)](https://basescan.org/address/0x8004A169FB4a3325136EB29fA0ceB6D2e539a432)
[![Network](https://img.shields.io/badge/Network-Base%20Mainnet%20(8453)-0052FF)](https://basescan.org)

Gclaw isn't a black box. Every creature earns a **verifiable onchain identity on
Base** and records its **reputation** there as it survives and trades — so anyone
can audit a creature's existence, its track record, and the protocol it lives in,
without trusting us. This page lists every contract so you can monitor it yourself.

> **TL;DR** — Gclaw creatures register as **ERC-8004 agents on Base mainnet**.
> Their identity and reputation are public, queryable contracts. The **GMAC** token
> (the creature's life-energy and the deflationary endgame) lives on Ethereum.

---

## 🔵 Built on Base

Gclaw is built on **Base** and adopts **ERC-8004 — the emerging standard for
onchain AI-agent identity & reputation.** Each agent is a first-class onchain
citizen: a registered identity, a portable reputation, and (at the top of its
arc) a deflationary token sink it deploys itself. It's a concrete example of the
**agent economy** Base is built for — autonomous, verifiable, and accountable.

---

## Contracts & registries

All addresses are live and verifiable. Click through to Basescan / Etherscan.

### Base mainnet · chainId 8453

| Contract | Address | What it does |
|---|---|---|
| **ERC-8004 IdentityRegistry** | [`0x8004A169FB4a3325136EB29fA0ceB6D2e539a432`](https://basescan.org/address/0x8004A169FB4a3325136EB29fA0ceB6D2e539a432) | Mints each creature's onchain identity (agentId + metadata URI). ✅ live |
| **ERC-8004 ReputationRegistry** | [`0x8004BAa17C55a88189AE136b182e5fdA19dE9b63`](https://basescan.org/address/0x8004BAa17C55a88189AE136b182e5fdA19dE9b63) | Records a creature's earned **goodwill** as onchain feedback. ✅ live |

### Ethereum mainnet · chainId 1

| Token | Address | What it does |
|---|---|---|
| **GMAC** (Gemach) | [`0xD96e84DDBc7CbE1D73c55B6fe8c64f3a6550deea`](https://etherscan.io/token/0xD96e84DDBc7CbE1D73c55B6fe8c64f3a6550deea) | The creature's life-energy. Profits are earmarked to **buy & burn** it. 0-tax, LP locked. ([chart](https://dexscreener.com/ethereum/0xD96e84DDBc7CbE1D73c55B6fe8c64f3a6550deea)) |

### Deploys on demand (source in this repo)

| Contract | Source | When |
|---|---|---|
| **GmacBuyAndBurn** | [`contracts/GmacBuyAndBurn.sol`](contracts/GmacBuyAndBurn.sol) | A creature that reaches the **Architect tier** deploys this as its profit engine's tail — a revenue sink that perpetually buys GMAC and sends it to the burn address. The buy-and-burn is baked in; it can never be turned off. Not yet deployed. |

---

## Live example — meet **Zephlith**, agent `#55624`

The reference creature running on our box is registered on Base right now:

| Field | Value |
|---|---|
| **Agent ID** | `55624` |
| **Network** | Base mainnet (8453) |
| **Registry** | [IdentityRegistry](https://basescan.org/address/0x8004A169FB4a3325136EB29fA0ceB6D2e539a432) |
| **Registration tx** | [`0x70203c…f318f3`](https://basescan.org/tx/0x70203c5cb99ccdc17d09208d9c9f6b4846d38d279348b8c975a88b99fef318f3) — ✓ confirmed (status: success) |
| **Block** | 47,435,383 |
| **Owner / identity wallet** | [`0xA3288e03…a31F9E`](https://basescan.org/address/0xA3288e03983A7C260419e348E897dd2533a31F9E) — watch the agent's onchain activity |

---

## Monitor a creature yourself

You don't need our word for any of it:

1. **Confirm it exists.** Open the [registration tx](https://basescan.org/tx/0x70203c5cb99ccdc17d09208d9c9f6b4846d38d279348b8c975a88b99fef318f3) on Basescan — the `register` call that minted agent `#55624`.
2. **Read its identity.** On the [IdentityRegistry contract](https://basescan.org/address/0x8004A169FB4a3325136EB29fA0ceB6D2e539a432#readContract), query the agent's metadata URI by its agentId.
3. **Watch its reputation grow.** Every time the creature earns goodwill from a profitable trade, it can record feedback on the [ReputationRegistry](https://basescan.org/address/0x8004BAa17C55a88189AE136b182e5fdA19dE9b63). Watch that address for the agent's `giveFeedback` events.
4. **Track GMAC.** Follow the [GMAC token](https://etherscan.io/token/0xD96e84DDBc7CbE1D73c55B6fe8c64f3a6550deea) and its holders/burns on Etherscan — every creature's endgame is to buy and burn it.

Or run your own creature and mint a fresh identity:

```bash
node scripts/erc8004_register.js dry-run   # simulate the mint, no gas
node scripts/erc8004_register.js broadcast  # register on Base (needs a funded wallet)
node scripts/erc8004_reputation.js dry-run  # preview the onchain goodwill feedback
```

---

## Why this matters

- **Verifiable, not vibes.** A creature's identity and earned reputation are public
  onchain records — auditable by anyone, portable across apps.
- **Accountable agents.** Reputation is earned from *real, settled* trade outcomes,
  not self-reported. The chain is the source of truth.
- **A deflationary endgame.** The most successful creatures deploy a contract that
  buys and burns GMAC forever — value flows back to the token by design.

Built on Base. Powered by ERC-8004. Open for anyone to inspect.
