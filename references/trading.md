# Trading — HyperLiquid perps & HIP-3 outcome markets

Gclaw trades two venues through the GDEX MCP. **No Solana memecoins.** All tool
names below are `mcp__gdex__*`; load their schemas with ToolSearch before use.

## Account & funding (do this once, verify every cycle)

HyperLiquid perps settle in USDC on the HL L1. Before any order can fill the
managed account needs a settled USDC deposit.

- `get_hl_clearinghouse_state` — margin summary, withdrawable, open positions. Empty/zero → unfunded.
- `perp_deposit` / `perp_withdraw` — move USDC in/out (can auto-fund from Arbitrum ETH first).
- `get_balances` — control-wallet token balances per chain.
- `hl_enable_trading` — enable trading on the managed HL account if not yet enabled.

If the account is unfunded, that is the blocker behind "trading doesn't work" — report it,
don't fake fills.

## A. Perpetuals (the core engine)

Trade **majors only** to start: BTC, ETH, SOL. They have the deepest books, the
tightest spreads, and the most reliable funding — the opposite of memecoin risk.

**Read / orient:**
- `get_hl_all_assets` — tradable perps + max leverage per asset.
- `get_hl_meta_and_asset_ctxs` — per-asset mark, funding, open interest, premium. Primary signal.
- `get_mark_price` — current mark for one asset.
- `get_perp_positions` — your open positions (size, entry, unrealized PnL, liq price).
- `get_hl_top_traders_by_pnl` — top 30 by `pnl`/`roi` with `windowPerformances` (day/week/month).
  Use as a *sentiment* read, not a copy signal, unless explicitly running copy-trading.
- `get_hl_user_stats` — a specific trader's stats by address (`ethAddress`).

**Act:**
- `set_leverage` — set leverage per asset BEFORE opening. Start low (2–3x), never above the
  strategy cap. Lower leverage = farther liquidation = survives noise.
- `open_perp_position` — open with size, direction, and **always** TP/SL.
- `place_perp_order` — limit/market order with optional TP/SL legs.
- `close_perp_position` / `close_all_positions` — realize PnL.
- `cancel_perp_order` / `cancel_all_perp_orders` — pull resting orders.

**Discipline:**
- One thesis per trade, stated before you open it.
- Size from the strategy's max-risk-per-trade, not from conviction.
- Funding matters: paying funding to hold a crowded side bleeds GMAC. Check the funding sign.
- After a position closes, read its realized PnL from the MCP and feed it to `metabolism.py settle`.

## B. HIP-3 outcome / event markets (defined-risk satellite)

Outcome markets are HyperLiquid event markets (e.g. "June Fed rate change" →
Change / No Change; per-country Yes/No markets). Each market exposes `outcomes`
with `sideSpecs` and a `quoteToken`. They are **defined-risk** directional bets —
good for survival mode because the downside is bounded.

**Read:**
- `hl_outcomes` — list markets (filter by `status`/`dex`; `withVolume=true` adds 24h notional, slower).
- `get_hl_outcome_volumes` — 24h volume per outcome market (liquidity filter).
- `hl_outcome_account` — your outcome positions and balances.

**Act:**
- `hl_create_outcome_order` — take a side of an outcome at a price.
- `hl_close_outcome_order` / `hl_cancel_outcome_order` — exit / pull.
- `hl_swap_collateral` — move collateral between perp and outcome accounts.

**Discipline:**
- Only enter markets with real volume (`get_hl_outcome_volumes`) and a clear, near-dated resolution.
- Price = implied probability. Only bet when your estimate diverges meaningfully from the price.
- Treat each ticket as fully-at-risk capital; size as a fraction of the survival buffer, not the whole treasury.

## Settling PnL into metabolism

The metabolism script is the single source of truth for the GMAC balance. After
any realized close:

```
uv run --no-project python3 scripts/metabolism.py settle --pnl <realized_usd> --note "ETH perp long, +14.20"
```

Use the **realized** number from `get_perp_positions`/`hl_outcome_account` (or the close
response), never an estimate. Unrealized PnL never touches the balance.
