# Event Desk (Book A) — market availability findings

Bead: `assune-4fw.3`. Branch: `fix/event-desk-markets`. Mode: **SHADOW** throughout
(`GCLAW_OUTCOMES_LIVE` never set; no live order placed; gate constants unchanged).

## 1. Enumeration — HyperLiquid outcome markets actually listed (2026-07-01)

Pulled live via the gdex MCP (`hl_outcomes status=active withVolume=true`) and cross-checked
against the desk's own bridge (`hl_outcomes.js markets`). **74 active outcome markets.**

| Category | Count | Notes |
|---|---|---|
| sports / World Cup | 57 | Champion + Round-of-32 head-to-heads. Efficient. |
| crypto-price (price binaries) | 6 | BTC/ETH/SOL/HYPE daily "above target" binaries. **Edgeable.** |
| macro (FOMC / CPI) | 4 | July-2026 FOMC rate decision, June-2026 BLS CPI. Edgeable but thin. |
| other (fallbacks / unnamed indices) | 7 | Not tradeable. |

### The edgeable markets (non-sports), with resolution criteria

| Outcome | Market | Resolution | 24h vol | Clears $10k floor? |
|---|---|---|---|---|
| 713 | BTC price binary | BTC ≥ **$59,122** at 06:00 UTC 2026-07-02 (1d) | **$439k** | yes |
| 715 | SOL price binary | SOL ≥ **$75.223** at 06:00 UTC 2026-07-02 (1d) | **$30k** | yes |
| 716 | HYPE price binary | HYPE ≥ $65.184 at 06:00 UTC 2026-07-02 | $8.3k | below floor |
| 714 | ETH price binary | ETH ≥ $1,592 at 06:00 UTC 2026-07-02 | $5.8k | below floor |
| 510–512 | FOMC July 2026 | rate range unchanged / decrease / increase | $0.9k / $0.1k / $0.2k | below floor |
| 542–544 | BLS CPI June 2026 | YoY below / exactly / above 3.8% | $0.08k / 0 / 0 | below floor |

All World-Cup / Round-of-32 sports markets ("Argentina", "Spain", "England vs Congo DR", …)
are efficient: their prices already reflect public consensus and an LLM has no informational
edge that would justify a divergent probability.

## 2. Verdict — YES, an edgeable market exists

Two crypto price-binary markets clear the desk's $10k volume floor **right now**: BTC (713,
$439k) and SOL (715, $30k). These are exactly the class the diagnosis called for — a dated,
clearly-resolved crypto price threshold where a calibrated LLM probability (from current spot,
time-to-expiry, and realized vol) can honestly diverge from the market's implied price.

Concrete example of the buried edge: at pull time BTC spot was **$59,862** while outcome 713
asks "BTC ≥ $59,122 by 06:00 tomorrow", with the **Yes** side priced at **0.748**. Spot was
already ~$740 through the strike with hours left — a divergence a calibrated read can act on.

## 3. The actual bug — the desk hid the resolution criteria, not the market

The desk was **not** over-filtering the market *set* — `fetch_sides` already returned every
side above the floor, including 713/715. The defect was that the venue bridge
(`hl_outcomes.js cmdMarkets`) emitted only `{coin, name, side, price, volumeUsd, outcomeId}`
and **dropped the `description`**. For these price binaries the `name` is the useless string
`"Recurring"` and the resolution terms (`class:priceBinary|underlying:BTC|targetPrice:59122|
expiry:…`) live **only** in the dropped description. So the LLM analyst saw a market literally
named "Recurring" with no target and no expiry — it could not form a calibrated probability
even though the edgeable market was on the board. Its honest skip was correct given blinded
inputs; the fix is to stop blinding it.

## 4. What changed (and why) — no gate touched, no probability manufactured

- **`scripts/hl_outcomes.js`** — added two pure classifiers, `classifyMarket(name, desc)` →
  `crypto-price | macro | sports | other`, and `parsePriceBinary(desc)` → `{underlying,
  targetPrice, expiry, period}`. `cmdMarkets` now emits `description`, `category`, and (for
  price binaries) a structured `resolution` per side. Guarded `main()` behind
  `require.main === module` and exported the classifiers for unit testing. Pure passthrough of
  what HL published — no fabrication.
- **`scripts/outcomes.py`** — added `EDGEABLE_CATEGORIES = {crypto-price, macro}` and
  `partition_edgeable()` (fails closed: an uncategorized side is treated as efficient). `markets`
  now also returns `edgeable` / `edgeable_count`, and — when only efficient sports clear the
  floor — a structured `no_edgeable_market` reason. **The gate (`evaluate_bet`), `live_mode`,
  and every divergence/volume/stake/longshot/ticket constant are unchanged.**
- **`scripts/briefing.py`** — the Event-desk board now points the analyst at the `edgeable`
  subset, renders each market's resolution criteria (e.g. "BTC vs 59122 by 20260702-0600")
  instead of the bare "Recurring" name, and prints an explicit
  `NO EDGEABLE MARKET: … — desk idle by design` line when only sports are available.

Net effect: the desk now surfaces an edgeable market the LLM can actually read, while an idle
desk becomes observably idle-by-market-availability rather than silently idle-by-bug. If the
LLM's calibrated probability does not diverge past the margin, the desk still cleanly skips —
it is never pushed to invent a probability to create activity.

## 5. Tests added (behavior, not implementation)

- `tests/node/hl_outcomes.test.js` — `classifyMarket` labels crypto-price / macro / sports /
  other; `parsePriceBinary` extracts terms and returns null for non-binaries.
- `tests/test_outcomes.py` — partition splits crypto+macro from sports; uncategorized side is
  efficient (fail-closed); `markets` surfaces the edgeable crypto market; `markets` emits the
  explicit `no_edgeable_market` reason when only sports clear the floor; the gate still refuses
  a no-edge sports side.
- `tests/test_briefing.py` — board shows the edgeable market with its resolution criteria and
  demotes efficient sports; board shows the explicit NO-EDGEABLE-MARKET / desk-idle line.

## 6. Gates

- `uv run --no-project ruff check scripts/ tests/` -> All checks passed
- `node --check scripts/hl_outcomes.js` -> OK
- `npx vitest run` -> 294 passed; `pytest` -> 312 passed
