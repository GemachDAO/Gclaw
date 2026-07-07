# Changelog

All notable changes to the gclaw skill are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.3.0] - 2026-07-07

Harness red-team release: the backtest JUDGE was certifying noise as edge, so the agent
kept graduating techniques that were live-negative. This release fixes the origination
brain and, more importantly, ships an eval suite that measures the harness so future
refinement is a scorecard, not a guess.

### Added

- **`evals/` suite** — four instruments that drive the real code and gauge the harness,
  plus `evals/run.py` for a one-command scorecard:
  - `judge_power` — feeds structured signals through the real backtest gate on
    block-bootstrapped **surrogate** data and measures the noise-certification rate.
  - `cost_truth` — recomputes true round-trip cost (incl. builder fee) from real fills
    and re-nets every `proven_markets` pair.
  - `feature_parity` — asserts the backtest reconstructs features exactly as live
    `intel.js` computes them.
  - `tool_budget` — checks the GDEX MCP read tools for context hygiene.

### Fixed

- **The backtest JUDGE certified edgeless signals.** The "proven" gate required only a
  positive out-of-sample mean, with no significance test — so noise passed at scale
  (~22% of structureless signals certified; 37 "proven" market pairs from 7 techniques,
  0 confirmed live). It now requires the out-of-sample edge to clear a bootstrap-CI lower
  bound above zero (the same test the live gate uses) plus an in-sample sample floor.
  Surrogate certification drops to ~1%.
- **Cold-start traded blind to losing evidence.** A still-bootstrapping technique kept
  opening real half-size probes up to the sample window even after trade memory already
  showed a negative live edge. It is now benched once a fair interim sample is negative.
- **The builder fee was invisible.** The JUDGE's cost model and the settlement ledger
  both omitted GDEX's builder fee (~5bp/side, ~40% of true cost), so techniques graduated
  against a cost floor that was too cheap and sizing learned off fee-inflated PnL. Now
  charged on both legs and booked in settlement.
- **Backtest features did not match live.** The reconstruction used an expanding candle
  window and population stdev where live `intel.js` uses a fixed 120-bar window and sample
  stdev — a train/serve skew. Now mirrored exactly.
- **The scientist board hid real regime gaps.** A positive edge on a single trade counted
  as "coverage," so genuinely under-served regimes never got a technique. Coverage now
  requires a real sample.
- **The event desk could never calibrate.** One divergence margin gated both recording and
  placing, so no calibration ever accrued; and live mode was a bare env flag. Recording now
  uses a looser shadow bar (calibration accrues), while a live order requires the wider
  margin AND proven calibration (resolved Brier beats the no-skill baseline).
- **The cost-saver never engaged.** Every heartbeat ran on the expensive model because any
  single coin's routine dislocation counted as "active." Since origination is forge-only,
  the model now escalates only when there is an open position to manage; a flat book is a
  cheap research cycle.

### Changed

- **Universe discovery** now applies a spread/liquidity quality gate (rejecting wide-spread
  thin perps admitted on volume alone) and discovers across both the native-crypto and the
  stock/commodity venues, so the deepest, tightest markets win regardless of asset class.
