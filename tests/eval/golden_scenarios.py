"""Labeled golden scenarios for the Gclaw forge CAPABILITY eval.

Each scenario is a synthetic, fully-offline snapshot of the forge's decision inputs
(technique votes + regime + circuit-breaker/health state) paired with the decision a
*correct* forge should make. The eval runner (run_eval.py) drives each one through the
REAL forge decision functions (``forge._combine``, ``forge.circuit_breaker``,
``forge._intent``) and scores PASS/FAIL.

This is a capability eval, NOT a regression gate: a less-than-100% pass rate is an
improvement target, not a build failure. See README.md for the distinction.

Vote construction mirrors ``tests/test_forge_combiner.py`` exactly: ``v`` is the
already-signed ``conviction * weight * gate`` term the combiner nets; ``w``/``g`` are
the weight and regime-gate the combiner divides by to recover conviction. Caps use the
real shipped defaults from ``style.json`` (``conviction_cap`` 0.85, ``agree_min`` 0.60,
``conv_min`` 0.22 — see ``cmd_run`` in scripts/forge.py).
"""

from __future__ import annotations

from typing import Any

# Real shipped defaults (forge.cmd_run reads these from style.json).
CAPS: dict[str, float] = {"conviction_cap": 0.85, "agree_min": 0.60, "conv_min": 0.22}


def vote(
    v: float,
    w: float = 0.5,
    g: float = 1.0,
    stop_pct: float = 2.0,
    leverage: int = 3,
    tid: str = "t",
) -> dict[str, Any]:
    """One ensemble vote, built the same way the combiner unit tests build them.

    ``v`` is the signed conviction*weight*gate term; the combiner re-derives agreement
    and conviction from the full vote list.
    """
    return {"v": v, "w": w, "g": g, "stop_pct": stop_pct, "leverage": leverage, "tid": tid}


# Each scenario:
#   name      — short label
#   intent    — the business rule this scenario asserts (one line)
#   stage     — which forge function the scenario exercises: "combine" | "breaker"
#   For stage "combine":
#     votes, regime, scaler          → forge._combine(votes, regime, CAPS, scaler)
#     expect_action                  → None for no-entry, or "long"/"short"
#   For stage "breaker":
#     equity, hwm, n_positions, reliable → drives forge.circuit_breaker
#     expect_allow_entry             → bool the breaker must return
SCENARIOS: list[dict[str, Any]] = [
    # --- chop: the hard "no entries in chop" rule ---------------------------
    {
        "name": "chop_no_entry",
        "intent": "chop regime always vetoes — no entries in chop, however strong the votes",
        "stage": "combine",
        "votes": [vote(0.6, tid="a"), vote(0.5, tid="b")],
        "regime": "chop",
        "scaler": 1.0,
        "expect_action": None,
    },
    # --- unknown/absent regime fails CLOSED ---------------------------------
    {
        "name": "unknown_regime_fails_closed",
        "intent": "a coin with no regime (unknown) must refuse to enter, never default to range",
        "stage": "combine",
        "votes": [vote(0.6, tid="a"), vote(0.5, tid="b")],
        "regime": "unknown",
        "scaler": 1.0,
        "expect_action": None,
    },
    # --- trend-alignment: never fade a trend (the veto HOLDS) ---------------
    {
        "name": "long_in_trend_down_vetoed",
        "intent": "a net-long signal in trend_down is vetoed (never buy a falling market)",
        "stage": "combine",
        "votes": [vote(0.6, tid="a"), vote(0.5, tid="b")],
        "regime": "trend_down",
        "scaler": 1.0,
        "expect_action": None,
    },
    {
        "name": "short_in_trend_up_vetoed",
        "intent": "a net-short signal in trend_up is vetoed (never short a rising market)",
        "stage": "combine",
        "votes": [vote(-0.6, tid="a"), vote(-0.5, tid="b")],
        "regime": "trend_up",
        "scaler": 1.0,
        "expect_action": None,
    },
    # --- trend-alignment: correct-direction case PASSES ---------------------
    {
        "name": "short_in_trend_down_allowed",
        "intent": "a with-trend short in trend_down passes the trend gate and decides short",
        "stage": "combine",
        "votes": [vote(-0.6, tid="a"), vote(-0.5, tid="b")],
        "regime": "trend_down",
        "scaler": 1.0,
        "expect_action": "short",
    },
    {
        "name": "long_in_trend_up_allowed",
        "intent": "a with-trend long in trend_up passes the trend gate and decides long",
        "stage": "combine",
        "votes": [vote(0.6, tid="a"), vote(0.5, tid="b")],
        "regime": "trend_up",
        "scaler": 1.0,
        "expect_action": "long",
    },
    # --- range + proven technique above the conviction floor → emits intent -
    {
        "name": "range_above_conviction_floor_enters",
        "intent": "in range, a strong unanimous signal clears both floors and emits a long",
        "stage": "combine",
        "votes": [vote(0.5, tid="a"), vote(0.4, tid="b")],
        "regime": "range",
        "scaler": 1.0,
        "expect_action": "long",
    },
    {
        "name": "range_short_above_floor_enters",
        "intent": "in range, a strong unanimous short clears the floors and emits a short",
        "stage": "combine",
        "votes": [vote(-0.5, tid="a"), vote(-0.4, tid="b")],
        "regime": "range",
        "scaler": 1.0,
        "expect_action": "short",
    },
    # --- below the conviction floor → hold ----------------------------------
    {
        "name": "below_conviction_floor_holds",
        "intent": "a unanimous but weak signal (conviction < conv_min 0.22) holds, no entry",
        "stage": "combine",
        "votes": [vote(0.10, tid="a"), vote(0.08, tid="b")],
        "regime": "range",
        "scaler": 1.0,
        "expect_action": None,
    },
    # --- agreement floor failure → hold -------------------------------------
    # Net long but split ~56/44 across contributors: agree 0.556 < agree_min 0.60
    # while conviction (0.222) would otherwise clear conv_min — so this fails ONLY on
    # the agreement floor, isolating that guard.
    {
        "name": "agreement_floor_failure_holds",
        "intent": "a divided ensemble (agreement < agree_min 0.60) holds even with net edge",
        "stage": "combine",
        "votes": [vote(1.6, tid="bull1"), vote(1.4, tid="bull2"), vote(-2.4, tid="bear")],
        "regime": "trend_up",
        "scaler": 1.0,
        "expect_action": None,
    },
    # --- a cold-hand scaler can pull a marginal signal below the floor ------
    # Same votes as range_above, but a 0.7 (coldest) Meta-2 scaler drops conviction
    # under conv_min — the forge should ease off when recent expectancy is negative.
    {
        "name": "cold_scaler_eases_off_marginal",
        "intent": "the cold-hand scaler (0.7) pulls a marginal range long below conv_min → hold",
        "stage": "combine",
        "votes": [vote(0.16, tid="a"), vote(0.14, tid="b")],
        "regime": "range",
        "scaler": 0.7,
        "expect_action": None,
    },
    # --- circuit breaker: drawdown >= 25% blocks new entries ----------------
    {
        "name": "drawdown_breaker_blocks_entry",
        "intent": "equity 30% below the high-water mark trips the breaker — no new entries",
        "stage": "breaker",
        "hwm": 1000.0,
        "equity": 700.0,
        "n_positions": 0,
        "reliable": True,
        "expect_allow_entry": False,
    },
    {
        "name": "shallow_drawdown_allows_entry",
        "intent": "a shallow 10% drawdown stays under the cap — entries still allowed",
        "stage": "breaker",
        "hwm": 1000.0,
        "equity": 900.0,
        "n_positions": 0,
        "reliable": True,
        "expect_allow_entry": True,
    },
    {
        "name": "unreliable_read_blocks_entry",
        "intent": "an untrusted (understated) equity read blocks entry without false-tripping",
        "stage": "breaker",
        "hwm": 1000.0,
        "equity": 50.0,
        "n_positions": 1,
        "reliable": False,
        "expect_allow_entry": False,
    },
]
