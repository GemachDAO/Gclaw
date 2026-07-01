"""The cycle briefing (scripts/briefing.py) pre-gathers everything the heartbeat LLM needs
into one blob so it decides from a single read instead of ~8 tool round-trips. render_briefing
is pure, so these pin its output for every state — and that it NEVER raises on partial data
(a crash here would blind the cycle). gather() is checked only for resilience (mocked I/O).
"""

from __future__ import annotations

import briefing


def _full() -> dict:
    return {
        "meta": {"mode": "thrive", "gmac_balance": 816.7, "seed": 1000, "goodwill": 29},
        "intel": {
            "BTC": {"regime": "chop"},
            "SOL": {"regime": "range", "tradeable": True},
            "xyz:MU": {"regime": "range", "tradeable": True},
            "ETH": {"regime": "chop"},
        },
        "account": {"equity": 202.13, "buyingPower": 202.13, "positions": [], "openOrders": []},
        "forge": {
            "mode": "thrive",
            "leverage_cap": 3,
            "breaker": {"allow_entry": True, "drawdown_pct": 0.1, "hwm": 202.36},
            "intents": [
                {"coin": "xyz:SNDK", "side": "long", "confidence": 0.542, "proven": False, "technique": "stop-hunt-revert"},
                {"coin": "SOL", "side": "short", "confidence": 0.371, "proven": True, "technique": "contrarian-flow"},
            ],
        },
        "economics": {"n": 11, "win_rate": 0.091, "expectancy": -1.282, "verdict": "🔴 still -EV"},
    }


def test_briefing_has_every_section_and_the_live_numbers():
    b = briefing.render_briefing(_full())
    assert "Survival:" in b and "mode thrive" in b and "goodwill 29" in b and "leverage cap 3x" in b
    assert "flat (0 open positions)" in b and "$202.13" in b
    assert "circuit breaker CLEAR" in b
    # tradeable markets surfaced, chop demoted to a count
    assert "Tradeable now (2):" in b and "SOL range✓" in b and "xyz:MU range✓" in b
    assert "Chop / sit out (2):" in b and "BTC" in b
    # the proven/unproven distinction is explicit — the whole point of the execution gate
    assert "xyz:SNDK long conf 0.542 — unproven" in b
    assert "SOL short conf 0.371 ✅ PROVEN" in b
    assert "11 real closes" in b and "still -EV" in b
    # the scientist board + a closer that discourages forced action (no-hypothesis → no technique)
    assert "Scientist board" in b
    assert "don't author busywork" in b.lower()


def test_open_positions_are_summarised_not_hidden():
    d = _full()
    d["account"]["positions"] = [{"coin": "xyz:MU", "size": "2", "entryPx": 150, "unrealizedPnl": 1.25}]
    b = briefing.render_briefing(d)
    assert "1 OPEN" in b and "xyz:MU long 2.0@$150.00" in b
    # the ACCOUNT line must not claim a flat book when positioned (the closer's generic
    # "a flat book your MAIN job…" guidance is instructional, not a state claim).
    assert "flat (0 open positions)" not in b


def test_tripped_breaker_says_no_entries():
    d = _full()
    d["forge"]["breaker"] = {"tripped": True, "drawdown_pct": 31.0, "hwm": 300.0}
    b = briefing.render_briefing(d)
    assert "TRIPPED — no new entries" in b


def test_no_intents_and_all_chop_render_cleanly():
    d = _full()
    d["forge"]["intents"] = []
    d["intel"] = {"BTC": {"regime": "chop"}, "ETH": {"regime": "chop"}}
    b = briefing.render_briefing(d)
    assert "no technique cleared" in b
    assert "whole board is chop" in b


def test_render_never_raises_on_empty_or_partial_data():
    # a blinded cycle is worse than a thin briefing — it must degrade, not crash
    for d in ({}, {"meta": None, "intel": None, "forge": None, "account": None, "economics": None},
              {"forge": {"intents": [{"coin": "X"}]}}, {"account": {"equity": "?"}}):
        b = briefing.render_briefing(d)
        assert isinstance(b, str) and "Cycle briefing" in b


def _crypto_binary_market() -> dict:
    return {
        "sides": [
            {"outcomeId": 173, "name": "Argentina", "side": "No", "coin": "#1731", "price": 0.81,
             "volumeUsd": 287125.0, "category": "sports"},
            {"outcomeId": 713, "name": "Recurring", "side": "Yes", "coin": "#7130", "price": 0.75,
             "volumeUsd": 188506.0, "category": "crypto-price",
             "resolution": {"underlying": "BTC", "targetPrice": 59122, "expiry": "20260702-0600", "period": "1d"}},
        ],
        "edgeable": [
            {"outcomeId": 713, "name": "Recurring", "side": "Yes", "coin": "#7130", "price": 0.75,
             "volumeUsd": 188506.0, "category": "crypto-price",
             "resolution": {"underlying": "BTC", "targetPrice": 59122, "expiry": "20260702-0600", "period": "1d"}},
        ],
        "edgeable_count": 1,
    }


def test_event_desk_shows_edgeable_market_with_resolution_criteria():
    d = _full()
    d["outcomes"] = _crypto_binary_market()
    b = briefing.render_briefing(d)
    # The edgeable header + the actual bet terms (not the bare "Recurring" name) must show.
    assert "edgeable markets" in b
    assert "BTC vs 59122 by 20260702-0600" in b
    # An efficient sports market that is NOT edgeable is demoted out of the edgeable view.
    assert "Argentina" not in b.split("Event desk")[1].split("Open tickets")[0]


def test_event_desk_shows_explicit_no_edgeable_market_when_only_sports():
    d = _full()
    d["outcomes"] = {
        "sides": [{"outcomeId": 173, "name": "Argentina", "side": "No", "coin": "#1731",
                   "price": 0.81, "volumeUsd": 287125.0, "category": "sports"}],
        "edgeable": [],
        "edgeable_count": 0,
        "no_edgeable_market": "1 sides clear the $10,000 floor but all are efficient (sports/World-Cup)",
    }
    b = briefing.render_briefing(d)
    assert "NO EDGEABLE MARKET" in b and "desk idle by design" in b


def test_gather_is_resilient_when_subprocesses_fail(monkeypatch, gclaw_home):
    # a failing helper must yield a default, not propagate — gather feeds a deterministic step
    def boom(*_a, **_k):
        raise OSError("node not found")

    monkeypatch.setattr(briefing.subprocess, "run", boom)
    g = briefing.gather()
    assert g["account"] == {} and g["forge"] == {}  # defaults, no exception
    assert isinstance(briefing.render_briefing(g), str)
