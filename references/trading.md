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
- **Builder/HIP-3 positions live under their own dex, NOT `default`.** A `xyz:NVDA` position
  shows up only when you query with `dex: "xyz"` — querying `default` returns it empty and looks
  like "nothing filled." When holding builder-dex perps, read each dex you trade (`dex: "xyz"`),
  not just `default`. (Live-confirmed: `xyz:NVDA`/`xyz:SPCX` opened fine but were invisible under
  `default` — the position migrates to the builder dex's isolated account.)
- `get_usdc_balance` / `get_hl_spot_state` with the managed HL address — HL USDC and spot balances.
- `get_account_state` can return `$0` for a funded account if it hits a different/empty builder DEX —
  trust `get_hl_clearinghouse_state` (with the right `dex`) over it.
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

**Act — `open_perp_position` (MCP) or `scripts/hl_perp.js` (fallback).** Both do the
proven sign-in (chainId 42161, fresh session, 0x-stripped signature) and trade on the
managed account. The helper emits JSON.

- `node scripts/hl_perp.js status` — spot USDC, account value, positions, open orders.
- `node scripts/hl_perp.js open --coin ETH --side long --notional 12 --leverage 3 --sl-pct 2 --tp-pct 3`
  — market entry with reduce-only TP/SL legs. A stop is mandatory; the $11 HL minimum is enforced.
- `node scripts/hl_perp.js close --coin ETH` — reduce-only market close, realizing PnL.

**Leverage is settable and you must set it.** Pass `leverage` in the open (the MCP
`open_perp_position` tool and `hl_perp.js --leverage` both forward it as a top-level
field on the order). HL defaults to **20x** if you omit it — never rely on that. The
strategy cap is **≤3x**. There is no separate `set_leverage` call (that endpoint is
404). Live-confirmed: opens land at exactly the leverage passed (3x isolated on builder
dexes, 3x on default). The MCP read tools (`get_mark_price`, `get_hl_meta_and_asset_ctxs`,
`get_hl_clearinghouse_state`) remain the way to gather intel.

### Builder/HIP-3 perps (stocks, commodities — verified working)

Beyond the default USDC dex, HL exposes builder dexes with stock and commodity perps:
`xyz:NVDA`, `xyz:TSLA`, `xyz:SPCX` (SpaceX), oil, etc. These are **USDC-collateralized,
24-hour markets** — no collateral swap needed. To trade them:

- Pass the coin with the **lowercase dex prefix** (`xyz:NVDA`, not `XYZ:NVDA`); the SDK
  normalizes casing but feed it correctly.
- Use the per-asset mark from `get_hl_all_assets` / `get_hl_meta_and_asset_ctxs` — plain
  `get_mark_price` returns 0 for builder coins.
- They open **isolated** automatically and honor the `leverage` you pass (3x verified live).
- Read the resulting position with `get_hl_clearinghouse_state { dex: "xyz" }`, not `default`.

Lead with default-dex USDC majors; treat builder stock/commodity perps as the same
mechanism with a dex-prefixed coin and a dex-scoped position read.

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

**Use the bundled helper** `scripts/hl_outcomes.js` (proven signed flow; emits JSON):
- `node scripts/hl_outcomes.js list` — active markets with `outcomeId` + sides (e.g. #104 "June Fed rate change" → Change/No Change). 122 live markets.
- `node scripts/hl_outcomes.js account --outcome <id>` — your positions/balance in a market.
- `node scripts/hl_outcomes.js enable` — one-time HL-trading enable (required before the first order; idempotent).
- `node scripts/hl_outcomes.js order --outcome <id> --coin <side> --buy --price <0..1> --size <n> [--market]` — take a side.
- `node scripts/hl_outcomes.js close --outcome <id> --coin <side>` — exit.

**Funding:** the outcome account is separate from perps. Move collateral with
`mcp__gdex__hl_swap_collateral` (perp → outcome) before betting; size it from the
survival buffer, not the whole treasury.

**Discipline:**
- Only enter markets with real volume (`mcp__gdex__get_hl_outcome_volumes`) and a clear, near-dated resolution.
- Price = implied probability. Only bet when your estimate diverges meaningfully from the price.
- Treat each ticket as fully-at-risk capital. In SURVIVE mode, prefer these defined-risk bets over leveraged perps.

## Settling PnL into metabolism

The metabolism script is the single source of truth for the GMAC balance. After
any realized close:

```
uv run --no-project python3 scripts/metabolism.py settle --pnl <realized_usd> --note "ETH perp long, +14.20"
```

Use the **realized** number from `get_perp_positions`/`hl_outcome_account` (or the close
response), never an estimate. Unrealized PnL never touches the balance.
