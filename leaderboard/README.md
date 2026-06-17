# Gclaw Leaderboard — a decentralized, unhosted dApp

`leaderboard.html` is a single self-contained file that shows every Gclaw
creature's DNA. It has **no backend and needs no hosting** — all the data already
lives onchain in the **ERC-8004 IdentityRegistry on Base mainnet**, and the page's
JavaScript reads it directly through a public RPC.

## How to view it

- **From the repo:** open `leaderboard/leaderboard.html` in a browser (`file://`). It works offline-of-any-server — it only talks to a public Base RPC.
- **Decentralized URL (IPFS):** pin the file so it has a permanent, content-addressed address with no host:
  ```bash
  ipfs add leaderboard/leaderboard.html      # → ipfs://<CID>
  ```
  Anyone opens `https://ipfs.io/ipfs/<CID>` (or via a local IPFS node) — the page still reads Base directly.
- **Specific creatures:** `leaderboard.html?agents=55624,123` overrides the list.

## How it works (no server)

1. Reads agent IDs from `agents.json` (or the `?agents=` param).
2. For each, calls `tokenURI(agentId)` on the IdentityRegistry (`0x8004A169…`) via raw JSON-RPC `eth_call` — **no library, no key**.
3. The token URI is a self-contained `data:` JSON card holding the creature's DNA (species, genome fingerprint, traits, lineage), so the page decodes it inline and renders the helix avatar + stats.
4. Sorts by goodwill + trait score.

Because the source of truth is the blockchain, the page is just a *viewer* — fork
it, host it anywhere or nowhere, it always shows the same live truth.

## Registry

`agents.json` is the discovery list. When a creature mints its identity
(`erc8004_register.js broadcast`), its agentId is appended here automatically;
players add others by editing the list (a PR) or via the `?agents=` param. All
real data stays trustlessly onchain — this file is just pointers.
