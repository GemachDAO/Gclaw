"""Property + metamorphic tests for the forge gated-weighted-ensemble combiner.

Units under test (scripts/forge.py, all pure given their inputs):

  * ``_combine(votes, regime, caps, scaler)`` — nets signed, weighted, gated votes
    into one long/short decision or ``None``;
  * ``_weighted_median(pairs)`` — robust stop aggregation;
  * ``_gate(tid, regime, rstats)`` — per-regime eligibility, bounded to [0.05, 1.2];
  * ``_update_fitness(tid, pnl, risk, regime)`` — multiplicative-weights (Hedge) update.

Invariants pinned (from the module docstrings + the DNA trading rules):

  * chop ALWAYS vetoes (returns None) — the hard "no entries in chop" rule;
  * unanimous same-sign votes => agreement reads 100% (and a decision passes the floor);
  * exactly-opposing equal votes net to zero => None (no edge to trade);
  * conviction is clamped into [0, conviction_cap];
  * the gate is bounded to [0.05, 1.2] for every regime / technique;
  * a winning trade RAISES the technique's weight, a losing trade LOWERS it, and the
    weight stays clamped to [0.05, 1.0]; weight response is monotone in realized return;
  * the weighted median lies within [min, max] of the input values.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

import forge

# A permissive default cap set so a genuine unanimous signal is *allowed* through;
# floors are tested explicitly where they matter.
CAPS = {"conviction_cap": 0.85, "agree_min": 0.60, "conv_min": 0.05}


def _vote(
    v: float,
    w: float = 0.5,
    g: float = 1.0,
    stop_pct: float = 1.0,
    leverage: int = 3,
    tid: str = "t",
) -> dict:
    """A single ensemble vote. ``v`` is the already-signed conviction*weight*gate term
    the combiner nets; the combiner re-derives agreement and conviction from it."""
    return {"v": v, "w": w, "g": g, "stop_pct": stop_pct, "leverage": leverage, "tid": tid}


# --- the hard DNA invariant: chop never trades -------------------------------
@given(
    st.lists(
        st.floats(-5, 5).map(lambda x: _vote(x, tid=f"t{abs(hash(x)) % 9}")), min_size=1, max_size=8
    ),
    st.floats(0.3, 1.3),
)
@settings(max_examples=200)
def test_chop_regime_always_returns_none(votes, scaler):
    assert forge._combine(votes, "chop", CAPS, scaler) is None


def test_empty_votes_returns_none():
    assert forge._combine([], "trend_up", CAPS, 1.0) is None


# --- opposing equal votes have no edge => None -------------------------------
@given(st.floats(0.1, 5.0), st.floats(0.3, 1.3))
def test_equal_opposing_votes_net_to_none(mag, scaler):
    votes = [_vote(mag, tid="bull"), _vote(-mag, tid="bear")]
    # total == 0 => conviction 0; agree == 0.5 < agree_min => None either way.
    assert forge._combine(votes, "trend_up", CAPS, scaler) is None


# --- unanimous same-sign votes => agreement 100%, a real decision ------------
@given(st.lists(st.floats(0.3, 3.0), min_size=2, max_size=6), st.floats(0.5, 1.3))
@settings(max_examples=200)
def test_unanimous_longs_decide_long_with_full_agreement(mags, scaler):
    votes = [_vote(m, tid=f"t{i}") for i, m in enumerate(mags)]
    out = forge._combine(votes, "trend_up", CAPS, scaler)
    assert out is not None
    assert out["action"] == "long"
    assert "100%" in out["reason"]  # agree == 1.0 renders as 100%
    assert out["contributors"] == [v["tid"] for v in votes]


@given(st.lists(st.floats(0.3, 3.0), min_size=2, max_size=6), st.floats(0.5, 1.3))
def test_unanimous_shorts_decide_short(mags, scaler):
    votes = [_vote(-m, tid=f"t{i}") for i, m in enumerate(mags)]
    out = forge._combine(votes, "trend_down", CAPS, scaler)
    assert out is not None
    assert out["action"] == "short"


# --- conviction is always within [0, conviction_cap] -------------------------
@given(
    st.lists(st.floats(-3, 3), min_size=1, max_size=8), st.floats(0.3, 1.3), st.floats(0.05, 0.95)
)
@settings(max_examples=300)
def test_conviction_within_cap(vs, scaler, cap):
    votes = [_vote(v, tid=f"t{i}") for i, v in enumerate(vs)]
    caps = {"conviction_cap": cap, "agree_min": 0.0, "conv_min": 0.0}
    out = forge._combine(votes, "trend_up", caps, scaler)
    if out is not None:
        # confidence is round(conviction, 3); allow one rounding step over the cap.
        assert 0.0 <= out["confidence"] <= cap + 5e-4


# --- metamorphic: duplicating the dominant vote keeps agreement & ratio, so
# conviction must NOT fall. (Adding a *weaker* agreeing vote legitimately pulls the
# weighted ratio |total|/eligible down — this combiner averages, it does not sum —
# so the sound metamorphic relation duplicates a contributor at equal strength.)
@given(st.lists(st.floats(0.3, 2.0), min_size=1, max_size=5))
@settings(max_examples=200)
def test_metamorphic_duplicate_vote_preserves_conviction(mags):
    caps = {"conviction_cap": 10.0, "agree_min": 0.0, "conv_min": 0.0}
    base_votes = [_vote(m, tid=f"t{i}") for i, m in enumerate(mags)]
    dominant = max(base_votes, key=lambda v: abs(v["v"]))
    more_votes = [*base_votes, dict(dominant, tid="dup")]
    base = forge._combine(base_votes, "trend_up", caps, 1.0)
    more = forge._combine(more_votes, "trend_up", caps, 1.0)
    assert base is not None and more is not None
    # Adding the strongest contributor again raises (or holds) the weighted ratio.
    assert more["confidence"] >= base["confidence"] - 1e-6


# --- metamorphic: a larger scaler never reduces conviction -------------------
@given(
    st.lists(st.floats(0.3, 2.0), min_size=2, max_size=5), st.floats(0.3, 1.0), st.floats(1.0, 1.3)
)
def test_metamorphic_higher_scaler_no_lower_conviction(mags, s_lo, s_hi):
    caps = {"conviction_cap": 10.0, "agree_min": 0.0, "conv_min": 0.0}
    votes = [_vote(m, tid=f"t{i}") for i, m in enumerate(mags)]
    lo = forge._combine(votes, "trend_up", caps, min(s_lo, s_hi))
    hi = forge._combine(votes, "trend_up", caps, max(s_lo, s_hi))
    assert hi["confidence"] >= lo["confidence"] - 1e-9


# --- weighted median is within [min, max] of inputs --------------------------
@given(
    st.lists(
        st.tuples(st.floats(-100, 100, allow_nan=False), st.floats(0.01, 50, allow_nan=False)),
        min_size=1,
        max_size=20,
    )
)
@settings(max_examples=400)
def test_weighted_median_within_value_range(pairs):
    vals = [v for v, w in pairs if w > 0]
    assume(vals)
    med = forge._weighted_median(pairs)
    assert min(vals) - 1e-9 <= med <= max(vals) + 1e-9


@given(st.lists(st.floats(-100, 100, allow_nan=False), min_size=1, max_size=20))
def test_weighted_median_equal_weights_is_a_real_input(values):
    """With equal weights the result is one of the supplied values (an order statistic)."""
    pairs = [(v, 1.0) for v in values]
    assert forge._weighted_median(pairs) in values


def test_weighted_median_empty_is_zero():
    assert forge._weighted_median([]) == 0.0


def test_weighted_median_ignores_nonpositive_weights():
    assert forge._weighted_median([(5.0, 0.0), (5.0, -1.0)]) == 0.0


# --- _gate is bounded to [0.05, 1.2] for any regime / technique --------------
# These exercise filesystem-backed state (style.json / technique.json under an isolated
# $GCLAW_HOME), so they are example/parametrized rather than @given: hypothesis does not
# compose with per-example function-scoped fixtures, and the input space here is the small
# set of regimes plus a swept edge range, fully covered by the parametrization below.
@pytest.mark.parametrize("regime", ["trend_up", "trend_down", "range", "chop", "unknown"])
def test_gate_bounded_with_no_technique_file(regime, gclaw_home):
    """A technique with no file on disk falls back to the static prior; the gate is
    still clamped into [0.05, 1.2]."""
    assert 0.05 <= forge._gate("missing-tid", regime, {}) <= 1.2


@pytest.mark.parametrize("regime", ["trend_up", "range", "trend_down"])
@pytest.mark.parametrize("edge", [-100.0, -3.0, -0.5, 0.0, 0.5, 3.0, 100.0])
def test_gate_learned_nudge_stays_bounded(edge, regime, gclaw_home, forge_technique):
    """Even with a huge learned edge and enough samples, the router nudge cannot push the
    gate outside [0.05, 1.2] (the tanh nudge is bounded)."""
    forge_technique("tid", {regime: 1.0})
    rstats = {"tid": {regime: {"e": edge, "n": 50}}}
    assert 0.05 <= forge._gate("tid", regime, rstats) <= 1.2


# --- _update_fitness: winners rise, losers fall, weight clamped [0.05, 1.0] ---
@pytest.mark.parametrize("pnl,risk", [(0.1, 1.0), (10.0, 5.0), (100.0, 100.0), (3.0, 1.0)])
def test_winning_trade_raises_weight(pnl, risk, gclaw_home, forge_style):
    forge_style([{"id": "t-w", "weight": 0.5, "e": 0.0, "trades": 0}])
    out = forge._update_fitness("t-w", pnl, risk, "trend_up")
    assert out["weight"] >= 0.5 - 1e-9
    assert 0.05 <= out["weight"] <= 1.0


@pytest.mark.parametrize("pnl,risk", [(0.1, 1.0), (10.0, 5.0), (100.0, 100.0), (3.0, 1.0)])
def test_losing_trade_lowers_weight(pnl, risk, gclaw_home, forge_style):
    forge_style([{"id": "t-l", "weight": 0.5, "e": 0.0, "trades": 0}])
    out = forge._update_fitness("t-l", -pnl, risk, "trend_up")
    assert out["weight"] <= 0.5 + 1e-9
    assert 0.05 <= out["weight"] <= 1.0


@pytest.mark.parametrize(
    "r_lo,r_hi", [(-3.0, -1.0), (-1.0, 0.0), (0.0, 1.0), (1.0, 3.0), (-2.0, 2.5)]
)
def test_fitness_weight_monotone_in_return(r_lo, r_hi, gclaw_home, forge_style):
    """weight *= exp(eta * r) is monotone in r: a strictly better realized return never
    yields a smaller post-update weight. r is driven via pnl with risk fixed at 1.0."""
    forge_style([{"id": "t-a", "weight": 0.5, "e": 0.0, "trades": 0}])
    w_lo = forge._update_fitness("t-a", r_lo, 1.0, "trend_up")["weight"]
    forge_style([{"id": "t-a", "weight": 0.5, "e": 0.0, "trades": 0}])  # reset
    w_hi = forge._update_fitness("t-a", r_hi, 1.0, "trend_up")["weight"]
    assert w_hi >= w_lo - 1e-9


def test_fitness_return_is_clamped(gclaw_home, forge_style):
    """A monster +PnL on tiny risk can't make r explode — it's clamped to [-3, 3]."""
    forge_style([{"id": "t-c", "weight": 0.5, "e": 0.0, "trades": 0}])
    out = forge._update_fitness("t-c", 1_000_000.0, 0.01, "trend_up")
    assert out["r"] == 3.0
    assert math.isfinite(out["weight"])
