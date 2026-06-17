# GMAC buy-back — turning profit into the real token

The agent's deepest objective: when it makes real profit, route a share of it
into **GMAC** (the Gemach DAO token) on Ethereum. This is the economic loop that
ties the creature's success back to the GMAC ecosystem (accumulate / buy-and-burn).

## Verified feasibility (read-only checks, 2026-06-17)

GMAC on **Ethereum** `0xd96e84ddbc7cbe1d73c55b6fe8c64f3a6550deea` (18 decimals):
- Traded on **Uniswap** + SushiSwap (WETH pairs); GDEX indexes and prices it.
- **0% buy tax, 0% sell tax, not a honeypot, contract verified, LP 100% locked** — safe to buy.
- ~$63.7k liquidity, ~$0.00031/token. Also on Arbitrum (Curve) and Solana (Orca).

`node scripts/gmac_buy.js plan` proves the route live (gasless): it pulls token
details, confirms the safety gate, and sizes the buy. Verified `ROUTE OK`.

## The accumulation rule (built into metabolism)

- Every realized profit routes **10%** (`GMAC_BUYBACK_RATE`) into a USD buy-back
  treasury: `metabolism.py settle --pnl X` increments `gmac_treasury_usd`.
- When the treasury is worth buying (≥ ~$5, to clear gas/slippage), the agent buys
  real GMAC and records it: `metabolism.py gmac --spend <usd> --tokens <got> --tx <hash>`,
  which debits the treasury and increments `gmac_tokens_held`.

## The pipeline (profit → GMAC), each leg has a tool

1. **Realize profit** on HyperLiquid → `metabolism.py settle` earmarks 10%.
2. **Withdraw** USDC from HL → `mcp__gdex__perp_withdraw` (to Arbitrum).
3. **Bridge** to Ethereum → `mcp__gdex__estimate_bridge` / `execute_bridge`
   (or buy GMAC on Arbitrum/Curve to skip Ethereum gas).
4. **Buy GMAC** on Ethereum Uniswap → `node scripts/gmac_buy.js buy --usd <treasury>`
   (managed GDEX buy on chainId 1), then record with `metabolism.py gmac`.

## Status

- ✅ Token verified tradeable + safe; routing proven via `gmac_buy.js plan`.
- ✅ 10%-of-profit treasury accrual + buy recording wired into the metabolism.
- 🟡 Live `buy` awaits the first **realized profit bridged to Ethereum** (needs ETH/USDC on
  Ethereum + gas). Until then the treasury accrues and the buy is a single command away.

At the venture-architect tier the original design routes 10% of venture profits into
a **GMAC buy-and-burn** — same pipeline, send the bought GMAC to `0x…dEaD`.
