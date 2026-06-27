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
        "account": {
            "ok": True,
            "positionsOk": True,
            "spotOk": True,
            "equity": 202.13,
            "buyingPower": 202.13,
            "positions": [],
            "openOrders": [],
        },
        "forge": {
            "mode": "thrive",
            "leverage_cap": 3,
            "breaker": {"allow_entry": True, "drawdown_pct": 0.1, "hwm": 202.36},
            "intents": [
                {
                    "coin": "xyz:SNDK",
                    "side": "long",
                    "confidence": 0.542,
                    "proven": False,
                    "technique": "stop-hunt-revert",
                },
                {
                    "coin": "SOL",
                    "side": "short",
                    "confidence": 0.371,
                    "proven": True,
                    "technique": "contrarian-flow",
                },
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
    assert "do not force a trade" in b.lower() or "Otherwise HOLD" in b


def test_open_positions_are_summarised_not_hidden():
    d = _full()
    d["account"]["positions"] = [
        {"coin": "xyz:MU", "size": "2", "entryPx": 150, "unrealizedPnl": 1.25}
    ]
    b = briefing.render_briefing(d)
    assert "1 OPEN" in b and "xyz:MU long 2.0@$150.00" in b
    assert "flat" not in b


def test_failed_account_read_is_never_rendered_as_flat():
    # A blind read (subprocess failed -> {}, or positionsOk False) must NOT print "flat":
    # that once reported a naked unprotected short as a clean account.
    for bad in ({}, {"ok": True, "positionsOk": False, "positions": [], "openOrders": []}):
        d = _full()
        d["account"] = bad
        b = briefing.render_briefing(d)
        assert "LIVE READ FAILED" in b and "Do NOT assume flat" in b
        assert "flat (0 open positions)" not in b


def test_spot_degraded_read_is_flagged_not_shown_as_fact():
    # positions still trusted, but equity/buying power are understated -> annotate, don't lie.
    d = _full()
    d["account"] = {
        "ok": True,
        "positionsOk": True,
        "spotOk": False,
        "equity": 0.0,
        "buyingPower": 0.0,
        "positions": [],
        "openOrders": [],
    }
    b = briefing.render_briefing(d)
    assert "spot read degraded" in b and "flat (0 open positions)" in b


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
    for d in (
        {},
        {"meta": None, "intel": None, "forge": None, "account": None, "economics": None},
        {"forge": {"intents": [{"coin": "X"}]}},
        {"account": {"equity": "?"}},
    ):
        b = briefing.render_briefing(d)
        assert isinstance(b, str) and "Cycle briefing" in b


def test_gather_is_resilient_when_subprocesses_fail(monkeypatch, gclaw_home):
    # a failing helper must yield a default, not propagate — gather feeds a deterministic step
    def boom(*_a, **_k):
        raise OSError("node not found")

    monkeypatch.setattr(briefing.subprocess, "run", boom)
    g = briefing.gather()
    assert g["account"] == {} and g["forge"] == {}  # defaults, no exception
    assert isinstance(briefing.render_briefing(g), str)
