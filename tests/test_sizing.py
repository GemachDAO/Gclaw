"""Exemplar: a pure-arithmetic Python unit test (no I/O, no fixtures needed).

sizing.size_trade is the risk brain. We test the *behavior* the docstring
promises — risk a fixed fraction of equity, never below the $11 HL min, never
above the goodwill leverage cap, size up on proven edge, down on noise — not the
exact float internals. Table-driven for the happy cases; explicit tests for the
edges and the invariants that protect real money.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

import sizing


def test_size_trade_risks_a_small_fixed_fraction_of_equity() -> None:
    out = sizing.size_trade(
        equity=1000,
        price=100,
        atr_pct=1.0,
        win_rate=0.55,
        payoff=1.5,
        goodwill=100,
        confidence=1.0,
        trades=200,
    )
    assert out["ok"] is True
    # Realized risk is a fraction of a percent of equity — survival, not degen.
    assert 0 < out["risk_pct_equity"] <= 0.6
    # Size is notional/price and the stop falls out of the ATR, both populated.
    assert out["size"] > 0
    assert out["stop_long"] < 100 < out["stop_short"]


def test_min_notional_floor_is_enforced() -> None:
    """A tiny account can't place a sub-$11 order — it clamps up and says so."""
    out = sizing.size_trade(
        equity=20,
        price=100,
        atr_pct=1.0,
        win_rate=0.5,
        payoff=1.5,
        goodwill=0,
        confidence=0.3,
        trades=0,
    )
    assert out["notional_usd"] >= sizing.MIN_NOTIONAL
    assert out["clamped_to_min"] is True


def test_leverage_cap_bounds_notional_by_goodwill_ladder() -> None:
    """Notional can never exceed equity x the goodwill-tier leverage cap."""
    out = sizing.size_trade(
        equity=1000,
        price=10,
        atr_pct=0.1,
        win_rate=0.9,
        payoff=5,
        goodwill=0,
        confidence=1.0,
        trades=500,
    )
    # goodwill 0 → cap 2x → notional <= 2000, even though a 90% edge wants more.
    assert out["leverage_cap"] == 2
    assert out["notional_usd"] <= 1000 * 2 + 1e-6


def test_more_goodwill_unlocks_more_leverage() -> None:
    low = sizing.size_trade(1000, 10, 0.1, 0.9, 5, goodwill=0, confidence=1.0, trades=500)
    high = sizing.size_trade(1000, 10, 0.1, 0.9, 5, goodwill=500, confidence=1.0, trades=500)
    assert high["leverage_cap"] > low["leverage_cap"]
    assert high["notional_usd"] >= low["notional_usd"]


def test_small_sample_winrate_is_shrunk_toward_a_coin_flip() -> None:
    """A 90% win-rate on 5 trades is noise; shrinkage pulls it back near 0.5."""
    shrunk = sizing.size_trade(1000, 100, 1.0, 0.9, 1.5, 0, 1.0, trades=5)["win_rate_shrunk"]
    assert 0.5 < shrunk < 0.65  # docstring promises ~0.54 for this shape


def test_zero_price_does_not_divide_by_zero() -> None:
    out = sizing.size_trade(
        1000, price=0, atr_pct=1.0, win_rate=0.5, payoff=1.5, goodwill=0, confidence=0.6
    )
    assert out["size"] == 0


def test_kelly_fraction_is_zero_for_negative_edge() -> None:
    # A coin flip with 1:1 payoff has no edge → Kelly clamps to 0, not negative.
    assert sizing.kelly_fraction(win_rate=0.4, payoff=1.0) == 0.0
    assert sizing.kelly_fraction(win_rate=0.5, payoff=0) == 0.0


def test_stop_distance_never_tighter_than_floor() -> None:
    """Even a near-zero ATR keeps a >=0.8% stop so size can't blow up."""
    out = sizing.size_trade(
        1000, 100, atr_pct=0.0, win_rate=0.5, payoff=1.5, goodwill=0, confidence=0.6
    )
    assert out["stop_distance_pct"] >= 0.8


# --- property-based: the invariants that protect real money must hold for ANY
# input in range, not just the table above. hypothesis searches the space and
# shrinks any violation to a minimal repro. This is why hypothesis is a dep.
@given(
    equity=st.floats(min_value=12, max_value=1_000_000),
    price=st.floats(min_value=0.01, max_value=200_000),
    atr_pct=st.floats(min_value=0.0, max_value=50),
    win_rate=st.floats(min_value=0.0, max_value=1.0),
    payoff=st.floats(min_value=0.1, max_value=10),
    goodwill=st.floats(min_value=0, max_value=10_000),
    confidence=st.floats(min_value=0.0, max_value=1.0),
)
def test_notional_always_within_min_and_leverage_cap(
    equity, price, atr_pct, win_rate, payoff, goodwill, confidence
) -> None:
    out = sizing.size_trade(equity, price, atr_pct, win_rate, payoff, goodwill, confidence)
    cap = equity * sizing.leverage_cap(goodwill)
    # The two hard invariants from the docstring, for every input in range.
    assert out["notional_usd"] >= sizing.MIN_NOTIONAL - 1e-6
    assert out["notional_usd"] <= max(sizing.MIN_NOTIONAL, cap) + 1e-6
    assert out["stop_distance_pct"] >= 0.8 - 1e-9
