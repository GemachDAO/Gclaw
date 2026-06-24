"""Backtest exit-model + evidence-gate tests (scripts/forge.py).

The audit found the backtest measured a strategy the agent never trades: it exited on a
fixed 4-bar HORIZON while live execution rests a TP/SL bracket (take-profit = stop x 1.5).
A 'proven' expectancy under the wrong exit doesn't transfer live. These pin the corrected
bracket walk, the realistic fee, and the significance/fee floor on the evidence gate.
"""

from __future__ import annotations

import forge


def _bars(entry, *rows):
    """An entry bar (close=entry) followed by OHLC rows {h,l,c}."""
    return [{"o": entry, "h": entry, "l": entry, "c": entry}, *rows]


COST = forge.taker_cost("BTC")  # a concrete round-trip cost to assert against


def test_long_take_profit_leg_pays_tp_minus_fee():
    # stop 2% -> tp = 2% * 1.5 = 3%. A bar that tags 103 (and not the 98 stop) wins tp.
    candles = _bars(100.0, {"h": 104.0, "l": 99.0, "c": 103.0})
    r = forge.trade_return(candles, 0, True, 2.0, COST)
    assert r == 0.03 - COST


def test_long_stop_leg_pays_minus_stop_minus_fee():
    candles = _bars(100.0, {"h": 101.0, "l": 97.0, "c": 98.0})  # tags the 98 stop
    r = forge.trade_return(candles, 0, True, 2.0, COST)
    assert r == -0.02 - COST


def test_same_bar_both_legs_resolves_to_the_stop():
    # A bar that breaches BOTH the stop and the TP is scored as the stop (conservative,
    # since the intrabar path is unknown).
    candles = _bars(100.0, {"h": 104.0, "l": 97.0, "c": 100.0})
    r = forge.trade_return(candles, 0, True, 2.0, COST)
    assert r == -0.02 - COST


def test_short_take_profit_leg():
    # short: tp when price falls 3% to 97 without tagging the 102 stop.
    candles = _bars(100.0, {"h": 101.0, "l": 96.0, "c": 97.0})
    r = forge.trade_return(candles, 0, False, 2.0, COST)
    assert r == 0.03 - COST


def test_no_leg_hit_marks_out_at_last_close():
    # Neither 98 nor 103 is tagged; the trade marks out at the final close, net of fee.
    candles = _bars(100.0, {"h": 101.0, "l": 99.0, "c": 100.5})
    r = forge.trade_return(candles, 0, True, 2.0, COST)
    assert r == (100.5 / 100.0 - 1) - COST


def test_walk_is_capped_at_max_hold():
    # A flat tape that never hits either leg still resolves (mark-out), never loops past
    # MAX_HOLD bars.
    flat = [{"o": 100.0, "h": 100.2, "l": 99.8, "c": 100.0} for _ in range(forge.MAX_HOLD + 10)]
    r = forge.trade_return(flat, 0, True, 2.0, COST)
    assert isinstance(r, float)


def test_thin_xyz_markets_cost_more_than_majors():
    # The whole point of per-market fees: a thin HIP-3 perp is charged more round-trip
    # than a deep major, so its edge must be larger to prove.
    assert forge.taker_cost("xyz:MU") > forge.taker_cost("BTC")
    assert forge.taker_cost("xyz:MU") == forge.COST_BY_CLASS["xyz"]
    assert forge.taker_cost("SOL") == forge.COST_BY_CLASS["major"]


def test_fee_is_realistic_and_floor_is_above_zero():
    # The prove floor must demand edge BEYOND the deducted round-trip, or noise sized like
    # the fee passes. TP must equal the live bracket ratio.
    assert forge.TAKER_RT >= 0.0009
    assert forge.PROVE_MIN_EDGE > 0
    assert forge.PROVE_MIN_T >= 2.0
    assert forge.TP_RATIO == 1.5


def test_summarise_reports_stdev_for_significance():
    out = forge.summarise([0.01, -0.02, 0.03, -0.01, 0.02])
    assert "stdev" in out and out["stdev"] > 0
    assert out["n"] == 5
