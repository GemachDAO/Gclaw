# Trading Strategy

## Mission
Compound GMAC through disciplined HyperLiquid trading. Replace the seeded 1000
GMAC with real realized profit, then grow it without ever risking extinction.

## Venues (and nothing else)
1. **HyperLiquid perpetuals** — the core engine. Majors only to start: BTC, ETH, SOL.
2. **HIP-3 outcome / event markets** — the defined-risk satellite for asymmetric, near-dated bets.

No Solana memecoins. No unlisted low-liquidity tokens. The venues above have deep
books and bounded, legible risk.

## Risk controls (hard limits)
- **Max risk per trade:** 5% of current GMAC balance. In SURVIVE mode, 2%.
- **Max leverage:** 3x on perps. Never higher. Lower is better.
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
