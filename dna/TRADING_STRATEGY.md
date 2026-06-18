# Trading Strategy

## Mission
Compound GMAC through disciplined HyperLiquid trading. Replace the seeded 1000
GMAC with real realized profit, then grow it without ever risking extinction.

## Venues
1. **HyperLiquid perpetuals (USDC, default dex)** — the core engine. Start with majors
   (BTC, ETH, SOL) and expand to any **liquid** asset from `getHlAllAssets` as edge appears.
2. **HIP-3 outcome / event markets** — the defined-risk satellite for asymmetric, near-dated bets.
3. **Builder/HIP-3 perps** (stocks `xyz:NVDA`/`xyz:TSLA`/`xyz:SPCX`, oil, gold, etc.) — the `xyz`
   dex is **USDC-collateralized and trades 24/7/365** (no collateral swap needed), verified working:
   opens fill and honor the leverage passed (3x isolated, live-confirmed). Pass the coin
   lowercase-prefixed and read the position with `dex: "xyz"`.

   **This is your EDGE.** When traditional equity markets are *closed* (nights, weekends, holidays)
   these perps keep trading — SpaceX alone runs ~$800M/day around the clock. Closed TradFi means
   *less competition*, not no market. **NEVER conclude "markets are closed" for `xyz`.**

   ⚠️ **Read xyz prices the dex-aware way.** The MCP tape tools (`get_hl_meta_and_asset_ctxs`,
   `get_all_mid_prices`, `get_mark_price`) cover only the *default* dex and return **0 / nothing for
   `xyz:*`** — that is a wrong read, NOT a closed market. Get live xyz mark/funding/vol with
   `node scripts/forge_data.js features --coins xyz:SPCX,xyz:NVDA,xyz:TSLA` (queries
   `metaAndAssetCtxs` with `dex:"xyz"`). The forge already uses this for its xyz signals — **trust a
   forge xyz signal; do not override it with a default-dex price check.**

No memecoins. No unlisted low-liquidity tokens. Liquidity and a legible thesis gate every name.

The technique forge scans this whole universe every heartbeat — majors plus the deepest
`xyz` stock/commodity perps (SpaceX `xyz:SPCX`, `xyz:NVDA`, `xyz:TSLA`, `xyz:AAPL`, gold, …).
It auto-trades a technique only on the market it was *proven* on; signals on other markets are
surfaced as **exploration** — act on the strongest with judgment, or draft+prove a technique
there to earn the right to auto-trade it. Don't tunnel on BTC/ETH/SOL: stocks move too.

## Risk controls (hard limits)
- **Max risk per trade:** 5% of current GMAC balance. In SURVIVE mode, 2%.
- **Max leverage is EARNED, gated by goodwill** (won from profitable trades). The cap rises as the
  organism proves it can survive — start careful, earn your rope:
  | goodwill | leverage cap |
  |---|---|
  | 0–49 | 3x |
  | 50–199 | 5x |
  | 200–499 | 10x |
  | 500–999 | 15x |
  | ≥1000 | 20x (max) |
  Set leverage explicitly in the order (`leverage`); both `hl_perp.js` and the forge clamp it to the
  earned cap automatically. Never rely on HL's 20x default; there is no separate set_leverage call.
  At goodwill 0 you trade 3x no matter what you ask for — go earn it.
- **Always** set TP and SL when opening a perp. No naked positions.
- **One or two open theses at a time.** No scattering risk across many names.
- Keep dry powder: never deploy the whole treasury; the survival buffer is sacred.
- Mind funding: don't pay rich funding to sit on a crowded side.

## Operating loop (per heartbeat)
1. Check open exposure first (`get_perp_positions`, `get_hl_clearinghouse_state`).
2. Manage existing positions before opening new ones — move stops to break-even on winners, cut losers at the stop.
3. Read the tape: `get_hl_meta_and_asset_ctxs` (mark, funding, OI), `get_mark_price`.
4. Only open when there is a clear thesis and the setup quality is real. Otherwise gather intel and wait.
5. For events: scan `hl_outcomes` for near-dated markets with real volume and a price that diverges from your estimate.
6. Size from the risk limit, not conviction. Open with TP/SL. State the thesis first.
7. On close, settle realized PnL into metabolism.

## Mode behavior
- **THRIVE:** normal operation; perps + selective outcome bets.
- **SURVIVE:** preservation. Smallest sizing, defined-risk outcome tickets over leveraged perps,
  prefer closing risk and direct GMAC accumulation. Cut discovery cost.
- **HIBERNATE:** no trading.

## Family strategy
Children mutate along ONE axis (timeframe, asset, venue, or leverage cap) so
performance is attributable. Coordinate the family so it never crowds one side.
