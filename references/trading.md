# Trading — HyperLiquid perps & HIP-3 outcome markets

Gclaw trades two venues through the GDEX MCP. **No Solana memecoins.** All tool
names below are `mcp__gdex__*`; load their schemas with ToolSearch before use.

## Account & funding (do this once, verify every cycle)

HyperLiquid perps settle in USDC on the HL L1. Before any order can fill the
managed account needs a settled USDC deposit.

### Resolving the funded address (critical — easy to get wrong)

Managed custody uses a **control wallet** (signs in) and **per-chain managed
wallets** (hold funds and trade). HyperLiquid funds live under the **managed
Arbitrum/HL wallet address, NOT the control address.** Querying the control
wallet shows `$0` even when the account is funded — that is the single most
common false "it's broken" signal.

Read the managed addresses from the wallet JSON (`~/gdex-test-wallet.json`):
`managed["Arbitrum (HyperLiquid)"].address` is the HL trading address;
`managed.Solana.address` is the Solana spot address.

### Balance reads that actually work (no auth, address-keyed)

- `get_hl_clearinghouse_state` with `userAddress = <managed HL address>` and `dex: "default"` —
  authoritative perp account: `accountValue`, `withdrawable`, positions. **Use this one.**
- `get_usdc_balance` / `get_hl_spot_state` with the managed HL address — HL USDC and spot balances.
- `get_account_state` can return `$0` for a funded account if it hits a different/empty builder DEX —
  trust `get_hl_clearinghouse_state` with `dex: "default"` over it.
- `get_portfolio` / `get_balances` are known-buggy (wrong params); for spot use the raw
  `client.get('/v1/portfolio', {userId, chainId, data})` flow. Note **native SOL/ETH are NOT in
  `portfolio.holding[]`** — check native balance separately.

### Funding controls

- `perp_deposit` / `perp_withdraw` — move USDC in/out (can auto-fund from Arbitrum ETH first).
- `hl_enable_trading` — enable trading on the managed HL account if not yet enabled.

Only report "unfunded" after checking the **managed** HL address with
`get_hl_clearinghouse_state`. Never fake fills.

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
