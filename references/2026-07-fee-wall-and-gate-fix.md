# Why gclaw went inert — diagnosis and fix

Branch: `fix/fee-wall-and-gate`. Beads: `assune-4fw.2` (gate bug), `assune-4fw.1` (fee wall).
Scope: `scripts/forge.py`, `scripts/hl_perp.js`, `dna/HEARTBEAT.md`, `tests/test_forge_fee_wall.py`.
No live state under `~/.gclaw` was modified; no `*_EXECUTE`/`*_LIVE` flag was armed.

## Verdict

**Both.** The organism was blocked by TWO independent locks, and both had to be cleared:

1. **The live gate was a genuine bug** — a double lock that made the cold-start probe
   effectively unreachable, a sibling of the cold-start-forever death spiral (commit
   `a7650dd`). Fixed, kept as a real gate.
2. **The fee wall was real** — the backtest charged one flat 15bp taker cost on every
   fill, including the entry that can be posted as a maker limit. The cost model now
   splits maker vs taker, so a genuine edge that was merely thinner than the taker round
   trip can graduate — without lowering the graduation bar.

## Task A — is the live conviction gate reachable? (assune-4fw.2)

Traced one live-equivalent cycle in dry (non-executing) mode: `forge.py run` against live
HyperLiquid data, plus direct instrumentation of `_gate_intents` / `_memory_edge_ok`.

**(1) Do the 2 proven techniques emit a live signal?** Rarely, and weakly. The live
`forge.py run` produced 4 intents this cycle, confidences **0.365–0.448** — every one
BELOW the base conviction floor `conv_floor = 0.75 × conviction_cap = 0.75 × 0.614 =
0.4605`. Not one cleared even the base floor.

**(2) Is `edge_real` ever true live?** No. `edge_real = (bootstrap 95% CI low > 0) AND
trades ≥ 3`. Live memory read:

| technique | regime | trades | ci95 | edge_real |
|---|---|---|---|---|
| stop-hunt-revert | range/trend_up/trend_down | 0 | — | False |
| stock-meanrev | trend_down | 1 | [0.0, 0.0] | False |

The proven techniques have essentially no live sample, so `edge_real` can only be reached
through the cold-start probe path — which was locked (below).

**(3) Is the CI floor an effective infinite lock?** Yes — a double lock:

- **Lock A, the bootstrap window.** `_gate_intents` only allowed a cold-start probe while
  `edge_trades_mem < 3`. But `edge_real` requires the ENTIRE bootstrap CI above zero, and
  at n=3 that is only possible if **all three trades win** (verified:
  `[2,2,-1] → ci=[-1,2] → edge_real=False`; even a 5/6 winner `[1,-1,1,1,1,1] →
  ci=[0.0,1.0]`, lo=0 not >0). So a technique that took **one early loss during
  bootstrapping was benched at trade 3 forever**: no longer cold (no probe), never
  edge_real (no full-size), and never able to accumulate the trades to recover.
- **Lock B, the confidence re-check.** `_cold_start_ok` demanded `confidence ≥
  conv_floor × 1.1 = 0.5066` — i.e. ≥ 0.825 × conviction_cap, a near-ceiling bar (the
  ensemble caps conviction AT `conviction_cap = 0.614`). Real ensemble conviction lands
  ~0.4, so the probe never fired and memory could never bootstrap. This `× 1.1` was added
  by the forge-only overhaul (`8082f9d`, 2026-06-30) — the same change that made the
  organism inert.

**Fix (still a real gate):**
- New `MIN_LIVE_SAMPLE = 12` (matches the fitness loop's own "fair sample before pruning"
  bar). A technique earns bounded HALF-size probes until it has 12 real closes, so a
  genuine edge can accumulate the sample that flips `edge_real`. Past 12 with no
  `edge_real`, it HAS been fairly measured and is benched — the gate does not probe a
  measured non-edge forever.
- `_cold_start_ok` no longer stacks the redundant `× 1.1`. The caller already enforced
  `confidence ≥ conv_floor`; the genome-tuned floor is the real conviction guard and
  `proven` is the real edge guard. Full size is still governed by `edge_real` (CI > 0).

The gate stays REAL: nothing trades unproven; nothing trades below the genome floor; a
measured non-edge is still benched; full size still needs a live CI-positive edge.

## Task B — the fee wall (assune-4fw.1)

**Root cause.** `trade_return` subtracted one flat `TAKER_COST = 0.0015` (15bp) on every
fill. `trend-accel-fusion` scored +0.0026 gross OOS but is net-negative in-sample after
15bp, so it (and every thin perp signal) failed `oos_exp>0 AND is_exp>0`. But the ENTRY
does not have to be a taker market order — a resting limit with an attached TP posts as
maker (~1.5bp), so the round trip the edge must beat is ~3bp, not ~15bp.

**Fix — a realistic maker/taker cost model that matches the executor.**
- Replaced the flat `TAKER_COST` with per-side `TAKER_FEE = 0.00075` (4.5bp fee + 3bp
  slippage) and `MAKER_FEE = 0.00015` (1.5bp, no slippage). `round_trip_cost(stop_hit)`
  charges: entry = maker if `GCLAW_FORGE_MAKER_ENTRY=1` else taker; exit = taker if the
  stop was hit (a trigger always crosses the book) else it fills like the entry.
- **Backtest matches the live executor, both driven by `GCLAW_FORGE_MAKER_ENTRY`**
  (assune-4yt). Unset (default): `hl_perp.js` opens `isMarket:true` (taker) and the
  backtest charges taker on both legs = 15bp — identical to today's fills. Set to `1`:
  the executor posts a resting maker limit (passive to the mark, so it adds liquidity)
  with the stop STILL atomically attached — a single `hl_create_order` action carrying
  `price + tpPrice + slPrice + isMarket`, so the entry is NEVER naked — and the backtest
  charges maker entry. One env var flips both, so the cost model can never diverge from
  the fill. Builder (`xyz:`) coins always stay taker: their attached SL is not armed as a
  resting order (assune-ehh), so a resting entry there would fill naked; the executor
  gates maker off for them.
- **Scientist prompt biased toward the right setups** (`dna/HEARTBEAT.md` §4b): author
  FEWER, BIGGER, higher-conviction setups that fire rarely and hold long enough that the
  move dwarfs the round trip — not high-frequency scalps that die to fees.

**Before / after evidence** (real HL candles, 4h, 500 bars):

`trend-accel-fusion` on majors, taker → maker-limit cost:

| market | taker IS / OOS | maker-limit IS / OOS |
|---|---|---|
| BTC | −0.00523 / +0.00315 | −0.00418 / +0.00423 |
| ETH | −0.00765 / +0.00605 | −0.00666 / +0.00714 |
| SOL | −0.00448 / +0.00515 | −0.00350 / +0.00616 |

The maker model lifts BOTH legs, but `trend-accel-fusion` still does NOT graduate — its
in-sample edge is genuinely negative (it is overfit to its authoring window; on its own
xyz:INTC market IS=+0.0032 but OOS=−0.0046). **This is the correct, honest outcome: the
cost model lowers the fee wall, it does not fabricate edge.** A scan of every authored
technique on BTC/ETH/SOL found none that flips NOT-proven→proven purely from the cheaper
cost — graduation still requires a real two-sided edge.

The pinned before/after that the fix DOES enable is a technique whose gross edge is a
genuine two-sided ~10bp/bar: it nets **negative after a taker round trip (~15bp) and
positive after a maker round trip (~3bp)** — captured deterministically in
`tests/test_forge_fee_wall.py::test_thin_edge_is_negative_under_taker_but_positive_under_maker`.

## Invariants preserved

Every entry still carries a stop (`_execute` passes both `--sl-pct` and `--tp-pct`); $11
min notional enforced; sizing/settlement/risk stay deterministic in code; no new
fund-moving surface; majors-first and the chop veto unchanged. The graduation rule
(`oos_exp>0 AND is_exp>0`, `MIN_OOS_SAMPLE=20`) was NOT weakened.

## Tests (break → confirm-fail → fix)

`tests/test_forge_fee_wall.py` (10 tests, all behavior-level):
- maker/taker split: taker default matches the executor round trip; maker round trip is
  strictly cheaper; a stop exit is always taker; `MAKER_FEE < TAKER_FEE`.
- cost model → graduation: a thin genuine edge is negative under taker, positive under
  maker; pure noise never graduates under maker (no fabricated edge).
- gate reachability: a still-bootstrapping technique (4 trades, no edge_real) gets a
  half-size probe; an edge_real technique executes full size; a matured technique
  (≥MIN_LIVE_SAMPLE, no edge_real) is benched; a sub-floor cold technique is rejected.

Confirmed each fails on the pre-fix code: the gate test benches the 4-trade technique
(0 gated) under the old `<3` window; the cost tests show the thin edge stays negative and
the maker round trip is not cheaper under the old flat cost.

Gates: `ruff check scripts/ tests/` clean · `node --check scripts/hl_perp.js` OK ·
`vitest run` 288 passed · full pytest suite green.
