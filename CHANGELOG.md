# Changelog

All notable changes to the gclaw skill are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.6.0] - 2026-07-08

### Fixed

- **xyz builder-dex positions were flattened as "naked" though their stop was resting all
  along** (assune-ehh). riskguard reads open orders via `hl_perp.js` status, which called the
  HL `openOrders` endpoint with no `dex` — so it only ever saw the **main dex**. A protective
  stop resting on the xyz builder dex was invisible, so every xyz position read as naked and
  riskguard flattened it on sight for a guaranteed loss. The order read now queries `openOrders`
  **per-dex** (main + each builder dex) and merges, mirroring how positions are already read.
  Verified live: a test xyz:BB open's SL/TP rest on the xyz dex and are now seen; riskguard
  computes real risk (0.2%), no flatten. The "attached SL isn't armed resting on xyz" comments
  were a misdiagnosis of this dex-blind read and are corrected.

### Changed

- **xyz origination enabled** (`GCLAW_ALLOW_XYZ_OPEN=1`). With the naked-flatten fixed, the
  forge can trade builder markets again — unblocking the one revalidation-surviving proven pair,
  `deviation-revert / xyz:BB`. The toggle is kept as a kill-switch for the thin builder book.

## [4.5.1] - 2026-07-07

### Fixed

- **Regression in v4.5.0's per-cycle archiving.** The prune step (`ls *.report.txt | tail`)
  exited non-zero when no archives existed yet, and under the heartbeat's `set -euo pipefail`
  that killed the whole heartbeat before the LLM cycle ran — so active cycles skipped their
  LLM run *and* the post-cycle riskguard/dashboard. compgen-guarded and failure-swallowed.

## [4.5.0] - 2026-07-07

### Added

- **Harness grader v2 — the LLM decision-quality judge** (`evals/decision_quality.py`). Grades
  the agent's JUDGMENT (was each cycle's manage / author-or-hold / bet-or-skip / veto reasoned
  soundly from grounded premises) — not hindsight profit. Kept honest: every checkable claim is
  verified deterministically first and a contradiction is a FORCED_FAIL that caps the axis at F
  with no LLM consulted; the LLM only grades the inference on a pre-verified block; every PASS
  must quote a report substring or lose its credit; too many ungrounded citations or a failed
  monotonicity smoke test returns LOW_CONFIDENCE, never a guess. Verdicts cached. Wired into the
  grader as the 10%-weight Decision-Quality dimension (off unless `--with-judge`; LOW-CONFIDENCE
  → UNGRADED ceiling cap). First live: **A** (mean 2.75/3, 98% grounding, 0 forced-fails).
- **Per-cycle context archiving** — the heartbeat now archives each active cycle's briefing +
  report to `~/.gclaw/cycles/` (bounded to 240) so decisions are graded on what was knowable
  then, not hindsight.

### Fixed

- A `--quick` grader run no longer false-fires the regression banner (a STALE/skipped eval is
  not a FAIL).

## [4.4.0] - 2026-07-07

### Added

- **Harness grader** (`evals/harness_grade.py`) — one honest letter grade for the whole
  harness, synthesizing the evals + live state. Severity is a hard floor, not a weight: a
  broken JUDGE / cost model / feature caps the grade outright, and missing data
  (a skipped eval, event calibration n=0) scores UNGRADED/STALE and caps the ceiling —
  never a default pass. Every run appends to `harness_grades.jsonl` for trend/regression.
  Each eval gained an additive `--json` line (run.py output unchanged). First live grade: B.
- **`forge.py revalidate`** — re-runs every registered proven pair through the current gate
  and drops the ones that no longer clear it. Run once: 36 of 37 pairs were noise certified
  under the old gate; only 1 survived.
- **Multiple-comparisons cap** (`AUTOPROVE_MAX_PER_TECH`) — bounds the proven pairs a
  technique may hold to its strongest few by edge_score, so it can't sprawl across a dozen
  markets on look-elsewhere luck.

### Fixed

- **Metabolism froze.** `metabolism.py tick` (the GMAC heartbeat burn) was only ever called
  from the interactive `/gclaw` skill, never the cron, so the unattended agent's survival
  accounting silently stopped. It now runs deterministically each heartbeat.

## [4.3.2] - 2026-07-07

### Fixed

- **Circuit-breaker safety: riskguard now guards against a bad equity read.** The two
  breaker implementations were meant to be identical, but riskguard.js lacked forge.py's
  bad-read guard — a transient status read yielding equity 0 (with a prior high-water mark)
  computed a 100% drawdown and flattened the *entire* book. A non-positive equity read is
  now inert, matching forge. (assune-xde, safety part)

### Changed

- **Log rotation.** `heartbeat.log` and `predict_bot.log` are rotated at a size cap
  (10 MiB, one prior generation) instead of growing unbounded. (assune-old)

## [4.3.1] - 2026-07-07

### Fixed

- **Honest R-multiple attribution.** `autosettle` read per-trade risk from `open_risk.json`,
  which nothing writes anymore, so every trade's R-multiple fell back to a 1.5%-of-notional
  estimate. It now reads the real `risk_usd` the forge records in `pending.json` on open.
  This sharpens the regime-conditional memory expectancy — and therefore the bootstrap-CI
  the (now significance-gated) JUDGE keys on. (assune-ir5)

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
