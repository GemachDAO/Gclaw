# Forge capability eval

A capability eval for the Gclaw forge's trade decisions: a set of labeled golden
scenarios that score whether the forge makes the **right** decision (enter / hold /
veto / block), reported as a pass-rate SCORE.

## Capability eval vs. regression test

These are two different things, and conflating them is a harness-engineering mistake:

| | Regression tests (`tests/test_forge_*.py`) | Capability eval (this dir) |
|---|---|---|
| Question | "Did a known invariant break?" | "Does the forge make the right call?" |
| Target | near-100%, a **protection** target | improve over time, an **improvement** target |
| On failure | **fails the build** (CI gate) | **never fails the build** — always exits 0 |
| Inputs | adversarial / property-based, pin exact code behavior | realistic labeled trade scenarios with an expected decision |

The regression suites protect the safety invariants (chop never trades, every perp
carries a stop, the breaker can't false-trip). This eval measures decision *quality*
against labeled scenarios — a low score is a signal to improve the forge, not a red CI.

## Scenarios

`golden_scenarios.py` holds 14 labeled scenarios. Each pairs synthetic technique votes +
regime + circuit-breaker state with the decision a correct forge should make. They cover:
chop → no entry; unknown regime fails closed; the trend-alignment veto (both the veto
holding *and* the correct-direction case passing); range above the conviction floor →
emits intent; below the conviction floor → hold; the agreement-floor failure → hold; the
cold-hand scaler easing off a marginal setup; and the drawdown ≥25% circuit breaker
blocking entries (plus the shallow-drawdown and unreliable-read cases).

Votes are built the same way `tests/test_forge_combiner.py` builds them, so the eval runs
the REAL `forge._combine`, `forge.circuit_breaker`, and `forge._intent` — fully offline
(no network, no `forge_data.js`, no real `~/.gclaw`).

## Run

```bash
uv run --no-project python3 tests/eval/run_eval.py
```

Prints a per-scenario PASS/FAIL scorecard and a `SCORE: N/total` line, and always exits 0.
