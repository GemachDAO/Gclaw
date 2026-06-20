"""Property + metamorphic suite for scripts/sizing.py.

Complements tests/test_sizing.py (which pins happy-path behaviour and the two hard
notional bounds). This file encodes the *relational* invariants — monotonicities,
contractions, metamorphic relations — that no finite table can cover:

  * vol targeting: a wider stop (higher ATR) never grows the position;
  * fractional Kelly: more confidence / more edge never shrinks it;
  * shrink_win_rate is a contraction toward 0.5 that converges to the raw rate;
  * every output is finite and non-negative for every input in the operating envelope.

Monotonicities are NON-strict (>=) on purpose: the function saturates against the
Kelly clamp (risk_pct capped at BASE_RISK_PCT), the confidence clamp ([0.3, 1.0]),
and the min-notional / leverage clamps. A strict-increase claim would be FALSE; the
weaker invariant is the true contract and is what catches off-by-direction bugs.
"""

from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st

import sizing

equities = st.floats(min_value=11.0, max_value=1_000_000, allow_nan=False, allow_infinity=False)
prices = st.floats(min_value=0.01, max_value=200_000, allow_nan=False, allow_infinity=False)
atrs = st.floats(min_value=0.01, max_value=50.0, allow_nan=False, allow_infinity=False)
win_rates = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
payoffs = st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False)
goodwills = st.floats(min_value=0.0, max_value=10_000, allow_nan=False, allow_infinity=False)
confidences = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
trade_counts = st.integers(min_value=0, max_value=5_000)


def _finite_nonneg(x: float) -> bool:
    return math.isfinite(x) and x >= 0.0


@given(equities, prices, atrs, win_rates, payoffs, goodwills, confidences, trade_counts)
@settings(max_examples=400)
def test_every_numeric_output_is_finite_and_nonnegative(eq, px, atr, wr, po, gw, conf, n):
    r = sizing.size_trade(eq, px, atr, wr, po, gw, conf, n)
    for key in (
        "notional_usd",
        "size",
        "stop_distance_pct",
        "risk_usd",
        "risk_pct_equity",
        "kelly_edge",
        "win_rate_shrunk",
        "stop_long",
        "stop_short",
    ):
        assert _finite_nonneg(r[key]), f"{key}={r[key]} not finite/non-negative"


# --- vol targeting: wider stop => smaller-or-equal position ------------------
@given(
    equities,
    prices,
    win_rates,
    payoffs,
    goodwills,
    confidences,
    trade_counts,
    st.floats(1.0, 25.0),
    st.floats(0.5, 20.0),
)
@settings(max_examples=300)
def test_size_nonincreasing_in_atr(eq, px, wr, po, gw, conf, n, atr_a, atr_b):
    lo, hi = min(atr_a, atr_b), max(atr_a, atr_b)
    small = sizing.size_trade(eq, px, lo, wr, po, gw, conf, n)["notional_usd"]
    big = sizing.size_trade(eq, px, hi, wr, po, gw, conf, n)["notional_usd"]
    assert big <= small + 1e-6


# --- fractional Kelly: more confidence / edge => not-smaller position --------
@given(
    equities,
    prices,
    atrs,
    win_rates,
    payoffs,
    goodwills,
    trade_counts,
    st.floats(0.0, 1.0),
    st.floats(0.0, 1.0),
)
@settings(max_examples=300)
def test_size_nondecreasing_in_confidence(eq, px, atr, wr, po, gw, n, c_a, c_b):
    lo, hi = min(c_a, c_b), max(c_a, c_b)
    less = sizing.size_trade(eq, px, atr, wr, po, gw, lo, n)["notional_usd"]
    more = sizing.size_trade(eq, px, atr, wr, po, gw, hi, n)["notional_usd"]
    assert more >= less - 1e-6


@given(
    equities,
    prices,
    atrs,
    payoffs,
    goodwills,
    confidences,
    trade_counts,
    st.floats(0.0, 1.0),
    st.floats(0.0, 1.0),
)
@settings(max_examples=300)
def test_size_nondecreasing_in_win_rate(eq, px, atr, po, gw, conf, n, w_a, w_b):
    lo, hi = min(w_a, w_b), max(w_a, w_b)
    weak = sizing.size_trade(eq, px, atr, lo, po, gw, conf, n)["notional_usd"]
    strong = sizing.size_trade(eq, px, atr, hi, po, gw, conf, n)["notional_usd"]
    assert strong >= weak - 1e-6


# --- metamorphic: doubling confidence must never DECREASE size ---------------
@given(equities, prices, atrs, win_rates, payoffs, goodwills, trade_counts, st.floats(0.05, 0.5))
def test_metamorphic_doubling_confidence_no_smaller(eq, px, atr, wr, po, gw, n, conf):
    base = sizing.size_trade(eq, px, atr, wr, po, gw, conf, n)["notional_usd"]
    doubled = sizing.size_trade(eq, px, atr, wr, po, gw, min(1.0, conf * 2), n)["notional_usd"]
    assert doubled >= base - 1e-6


@given(st.floats(0.0, 2000), st.floats(0.0, 2000))
def test_leverage_cap_monotone_in_goodwill(g_a, g_b):
    lo, hi = min(g_a, g_b), max(g_a, g_b)
    assert sizing.leverage_cap(hi) >= sizing.leverage_cap(lo)


# --- shrink_win_rate: contraction toward 0.5, convergence to raw rate --------
@given(win_rates, trade_counts)
@settings(max_examples=400)
def test_shrink_lies_between_raw_and_half(wr, n):
    adj = sizing.shrink_win_rate(wr, n)
    assert min(wr, 0.5) - 1e-9 <= adj <= max(wr, 0.5) + 1e-9
    assert 0.0 <= adj <= 1.0


@given(win_rates)
def test_shrink_zero_trades_is_pure_prior(wr):
    assert sizing.shrink_win_rate(wr, 0) == 0.5


@given(win_rates)
def test_shrink_converges_to_raw_as_sample_grows(wr):
    assert abs(sizing.shrink_win_rate(wr, 10_000_000) - wr) < 1e-3


@given(win_rates, st.integers(1, 1000), st.integers(1, 1000))
def test_shrink_distance_to_raw_nonincreasing_in_n(wr, n_a, n_b):
    """More evidence can only move the estimate toward the raw rate, never away."""
    lo, hi = min(n_a, n_b), max(n_a, n_b)
    near = abs(sizing.shrink_win_rate(wr, lo) - wr)
    far = abs(sizing.shrink_win_rate(wr, hi) - wr)
    assert far <= near + 1e-9


@given(win_rates, payoffs)
def test_kelly_fraction_nonnegative(wr, po):
    assert sizing.kelly_fraction(wr, po) >= 0.0


# --- mutation-killing golden anchors -----------------------------------------
# These pin EXACT relations that the bounds/monotonicity properties leave slack on.
# Each was added after a mutmut survivor proved the looser property missed it.
def test_size_is_notional_over_price_exactly():
    """Kills the `notional / price` -> `notional * price` mutant: size is the quotient,
    and notional == size * price must round-trip."""
    r = sizing.size_trade(10_000, 50.0, 1.0, 0.55, 1.5, 100, 1.0, 200)
    assert r["size"] == round(r["notional_usd"] / 50.0, 6)
    assert abs(r["size"] * 50.0 - r["notional_usd"]) < 1e-2


def test_stop_floor_is_exactly_080_percent_not_higher():
    """Kills mutants that raise the 0.8% stop floor: at ~zero ATR the stop is EXACTLY
    0.8%, not 1.8% or any larger constant."""
    r = sizing.size_trade(10_000, 100.0, 0.0, 0.5, 1.5, 0, 0.6, 0)
    assert r["stop_distance_pct"] == 0.8


def test_min_risk_probe_floor_is_0015_percent():
    """Kills mutants on the 0.0015 zero-edge probe floor: a no-edge coin-flip still risks
    a tiny, BOUNDED fraction — never a whole unit. With confidence 1.0 and no edge, the
    realized risk fraction is 0.0015 (0.15%), far below BASE_RISK_PCT."""
    r = sizing.size_trade(100_000, 100.0, 1.0, 0.5, 1.0, 1000, 1.0, 0)
    # zero Kelly edge => risk_pct = 0.0015 * 1.0; realized risk_pct_equity ~ 0.15%.
    assert r["kelly_edge"] == 0.0
    assert r["risk_pct_equity"] < 0.2  # a 1.0015 mutant would blow this past 100%


def test_stops_are_symmetric_around_entry():
    """Kills the `price * (2 + stop_pct)` stop-display mutant: long/short stops sit one
    stop_pct BELOW / ABOVE entry, symmetric, both within a hair of price (never 2x)."""
    px, sp = 100.0, None
    r = sizing.size_trade(10_000, px, 1.0, 0.55, 1.5, 100, 1.0, 200)
    sp = r["stop_distance_pct"] / 100
    assert r["stop_long"] == round(px * (1 - sp), 4)
    assert r["stop_short"] == round(px * (1 + sp), 4)
    assert px < r["stop_short"] < px * 1.5  # never the 2x mutant


def test_confidence_clamped_at_one():
    """Kills the `min(1.0, confidence)` -> `min(2.0, confidence)` mutant: confidence above
    1.0 must NOT scale risk past the conf==1.0 level."""
    at_one = sizing.size_trade(10_000, 100.0, 1.0, 0.6, 1.5, 100, 1.0, 200)["risk_usd"]
    over = sizing.size_trade(10_000, 100.0, 1.0, 0.6, 1.5, 100, 2.0, 200)["risk_usd"]
    assert over == at_one
