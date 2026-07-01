"""Tests for the Event Desk (Book A) deterministic gate, Brier math, and shadow/live.

The gate (``evaluate_bet``) is a pure function — every accept/reject rule (a)-(f) is
exercised directly, no network. ``cmd_bet`` and ``cmd_resolve`` are tested with the
venue bridge (``fetch_sides``) and the live-order/settle subprocesses monkeypatched, so
no test ever hits the SDK or places a real order. The shadow-vs-live test asserts that
in shadow mode NO order call is made.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import outcomes

SIDES = [
    {"outcomeId": 173, "name": "Argentina", "side": "No", "coin": "#1731", "price": 0.80, "volumeUsd": 263901.0},
    {"outcomeId": 173, "name": "Argentina", "side": "Yes", "coin": "#1730", "price": 0.20, "volumeUsd": 64944.0},
    {"outcomeId": 999, "name": "Thin", "side": "Yes", "coin": "#9990", "price": 0.50, "volumeUsd": 500.0},
    {"outcomeId": 888, "name": "Longshot", "side": "Yes", "coin": "#8880", "price": 0.05, "volumeUsd": 50000.0},
]


def _bet(coin: str, prob: float, stake: float, open_coins=None, n_open: int = 0) -> dict:
    return outcomes.evaluate_bet(coin, prob, stake, SIDES, open_coins or set(), n_open)


# ── Gate rules (a)-(f) ───────────────────────────────────────────────────────


def test_accept_when_every_rule_passes() -> None:
    v = _bet("#1731", prob=0.92, stake=8.0)  # edge 0.12 >= 0.08, vol ok, not longshot
    assert v["ok"] and v.get("side") and v["side"]["coin"] == "#1731"
    assert v["edge"] == pytest.approx(0.12)


def test_rule_a_reject_unknown_coin() -> None:
    v = _bet("#0000", 0.99, 5)
    assert v["placed"] is False
    assert v["skipped"].startswith("no active market")


def test_rule_a_reject_low_volume_side_present_in_board() -> None:
    sides = SIDES + [{"outcomeId": 7, "name": "x", "side": "y", "coin": "#70", "price": 0.5, "volumeUsd": 9000.0}]
    v = outcomes.evaluate_bet("#70", 0.99, 5, sides, set(), 0)
    assert "volume" in v["skipped"] and "floor" in v["skipped"]


def test_rule_b_reject_when_edge_below_margin() -> None:
    v = _bet("#1731", prob=0.85, stake=8.0)  # edge 0.05 < 0.08
    assert v["placed"] is False and "margin" in v["skipped"]


def test_rule_b_edge_exactly_at_margin_accepts() -> None:
    v = _bet("#1731", prob=0.88, stake=8.0)  # edge 0.08 == margin → accept (>=)
    assert v.get("side")


def test_rule_c_reject_longshot_below_floor() -> None:
    v = _bet("#8880", prob=0.50, stake=8.0)  # price 0.05 < 0.10 floor (big edge, still rejected)
    assert "longshot guard" in v["skipped"]


def test_rule_d_reject_stake_out_of_bounds() -> None:
    assert "stake" in _bet("#1731", 0.92, 0.5)["skipped"]  # < MIN_STAKE
    assert "stake" in _bet("#1731", 0.92, 99.0)["skipped"]  # > MAX_STAKE


def test_rule_e_reject_at_ticket_cap() -> None:
    v = _bet("#1731", 0.92, 8.0, n_open=outcomes.MAX_TICKETS)
    assert "cap" in v["skipped"]


def test_rule_f_reject_double_down() -> None:
    v = _bet("#1731", 0.92, 8.0, open_coins={"#1731"})
    assert "double-down" in v["skipped"]


def test_prob_out_of_range_is_a_clean_skip() -> None:
    assert _bet("#1731", 1.5, 8.0)["placed"] is False
    assert "out of [0,1]" in _bet("#1731", 1.5, 8.0)["skipped"]


# ── Brier math + aggregates ──────────────────────────────────────────────────


def test_brier_contribution_perfect_and_worst() -> None:
    # outcome=1, prob=1.0 → 0; prob=0.0 → 1. (prob - outcome)^2.
    assert (1.0 - 1) ** 2 == 0.0
    led = {"tickets": [
        {"price": 0.8, "prob": 0.9, "shadow": True, "resolved": True, "outcome": 1, "brier": (0.9 - 1) ** 2},
        {"price": 0.3, "prob": 0.4, "shadow": True, "resolved": True, "outcome": 0, "brier": (0.4 - 0) ** 2},
    ]}
    agg = outcomes._aggregate(led["tickets"])
    assert agg["n_resolved"] == 2
    assert agg["brier_mean"] == pytest.approx(((0.1**2) + (0.4**2)) / 2)
    # no-skill baseline = mean of price*(1-price) at the prices bet.
    assert agg["baseline_mean"] == pytest.approx((0.8 * 0.2 + 0.3 * 0.7) / 2)


def test_aggregate_counts_shadow_and_live_split() -> None:
    tickets = [{"shadow": True}, {"shadow": True}, {"shadow": False}]
    agg = outcomes._aggregate(tickets)
    assert (agg["n"], agg["n_shadow"], agg["n_live"], agg["n_resolved"]) == (3, 2, 1, 0)
    assert agg["brier_mean"] is None  # nothing resolved yet


def test_price_bucket_boundaries() -> None:
    assert outcomes._price_bucket(0.05) == "0-10"
    assert outcomes._price_bucket(0.10) == "10-25"
    assert outcomes._price_bucket(0.95) == "90-100"


# ── Shadow vs live: NO order call in shadow ──────────────────────────────────


def _args(coin="#1731", prob=0.92, stake=8.0, reason="") -> argparse.Namespace:
    return argparse.Namespace(coin=coin, prob=prob, stake=stake, reason=reason)


def test_shadow_mode_records_ticket_and_places_no_order(gclaw_home: Path, monkeypatch) -> None:
    monkeypatch.delenv("GCLAW_OUTCOMES_LIVE", raising=False)
    monkeypatch.setattr(outcomes, "fetch_sides", lambda min_vol=outcomes.MIN_VOLUME: SIDES)
    called = {"order": 0}

    def _boom(*_a, **_k):
        called["order"] += 1
        raise AssertionError("no live order may be placed in shadow mode")

    monkeypatch.setattr(outcomes, "_place_live_order", _boom)
    res = outcomes.cmd_bet(_args())
    assert res["placed"] is True and res["shadow"] is True
    assert called["order"] == 0
    led = json.loads((gclaw_home / "calibration.json").read_text())
    assert len(led["tickets"]) == 1 and led["tickets"][0]["shadow"] is True
    assert "order" not in led["tickets"][0]


def test_live_mode_calls_order_then_records_not_shadow(gclaw_home: Path, monkeypatch) -> None:
    monkeypatch.setenv("GCLAW_OUTCOMES_LIVE", "1")
    monkeypatch.setattr(outcomes, "live_mode", lambda: True)
    monkeypatch.setattr(outcomes, "fetch_sides", lambda min_vol=outcomes.MIN_VOLUME: SIDES)
    placed = {}

    def _order(side, stake):
        placed.update({"coin": side["coin"], "stake": stake})
        return {"ok": True, "action": "order"}

    monkeypatch.setattr(outcomes, "_place_live_order", _order)
    res = outcomes.cmd_bet(_args())
    assert res["placed"] is True and res["shadow"] is False
    assert placed == {"coin": "#1731", "stake": 8.0}
    led = json.loads((gclaw_home / "calibration.json").read_text())
    assert led["tickets"][0]["shadow"] is False and led["tickets"][0]["order"]["ok"]


def test_gate_rejection_records_nothing(gclaw_home: Path, monkeypatch) -> None:
    monkeypatch.setattr(outcomes, "fetch_sides", lambda min_vol=outcomes.MIN_VOLUME: SIDES)
    res = outcomes.cmd_bet(_args(coin="#8880"))  # a longshot — gate rejects
    assert res["placed"] is False and "longshot" in res["skipped"]
    assert not (gclaw_home / "calibration.json").exists()


# ── Resolution + settlement ──────────────────────────────────────────────────


_OLD_TS = "2026-01-01T00:00:00+00:00"


def test_resolve_scores_brier_from_settlement_fills_calibration_only(gclaw_home: Path, monkeypatch) -> None:
    led = {"tickets": [
        {"coin": "#1731", "outcomeId": 173, "name": "Argentina", "side": "No", "prob": 0.9,
         "price": 0.8, "stake": 8.0, "edge": 0.1, "shadow": True, "resolved": False, "ts": _OLD_TS},
        {"coin": "#8880", "outcomeId": 888, "name": "L", "side": "Yes", "prob": 0.7,
         "price": 0.5, "stake": 8.0, "edge": 0.2, "shadow": False, "resolved": False, "ts": _OLD_TS},
    ]}
    outcomes.save_ledger(led)
    # Real HL settlement fills: #1731 settled TRUE (px 1), #8880 settled FALSE (px 0).
    settlements = [
        {"coin": "#1731", "settlePx": 1.0, "closedPnl": 2.0, "time": 9.0e12},
        {"coin": "#8880", "settlePx": 0.0, "closedPnl": -8.0, "time": 9.0e12},
    ]
    monkeypatch.setattr(outcomes, "fetch_settlements", lambda: settlements)
    # The desk must NEVER settle PnL itself — autosettle owns it. Catch any subprocess
    # (a metabolism settle) as a double-count regression.
    monkeypatch.setattr(outcomes.subprocess, "run",
                        lambda *a, **k: pytest.fail("cmd_resolve must not settle PnL (autosettle owns it)"))
    res = outcomes.cmd_resolve(argparse.Namespace())
    assert res["resolved"] == 2
    final = json.loads((gclaw_home / "calibration.json").read_text())
    t1 = next(t for t in final["tickets"] if t["coin"] == "#1731")
    t2 = next(t for t in final["tickets"] if t["coin"] == "#8880")
    assert t1["outcome"] == 1 and t1["brier"] == pytest.approx((0.9 - 1) ** 2)
    assert t2["outcome"] == 0 and t2["brier"] == pytest.approx((0.7 - 0) ** 2)
    assert t1["settle_pnl"] == pytest.approx(2.0)  # informational, from the fill


def test_resolve_is_idempotent(gclaw_home: Path, monkeypatch) -> None:
    led = {"tickets": [
        {"coin": "#1731", "outcomeId": 173, "name": "A", "side": "No", "prob": 0.9, "price": 0.8,
         "stake": 8.0, "edge": 0.1, "shadow": False, "resolved": False, "ts": _OLD_TS},
    ]}
    outcomes.save_ledger(led)
    settlements = [{"coin": "#1731", "settlePx": 1.0, "closedPnl": 2.0, "time": 9.0e12}]
    monkeypatch.setattr(outcomes, "fetch_settlements", lambda: settlements)
    r1 = outcomes.cmd_resolve(argparse.Namespace())
    r2 = outcomes.cmd_resolve(argparse.Namespace())  # second pass resolves nothing new
    assert r1["resolved"] == 1 and r2["resolved"] == 0


def test_resolve_ignores_settlement_predating_the_ticket(gclaw_home: Path, monkeypatch) -> None:
    # A settlement that happened BEFORE the bet must not resolve it (stale-coin guard).
    led = {"tickets": [
        {"coin": "#1731", "outcomeId": 173, "name": "A", "side": "No", "prob": 0.9, "price": 0.8,
         "stake": 8.0, "edge": 0.1, "shadow": True, "resolved": False, "ts": "2026-06-01T00:00:00+00:00"},
    ]}
    outcomes.save_ledger(led)
    settlements = [{"coin": "#1731", "settlePx": 1.0, "closedPnl": 2.0, "time": 1.0e12}]  # ~2001, pre-bet
    monkeypatch.setattr(outcomes, "fetch_settlements", lambda: settlements)
    res = outcomes.cmd_resolve(argparse.Namespace())
    assert res["resolved"] == 0


def test_calibration_read_never_raises_on_empty(gclaw_home: Path) -> None:
    out = outcomes.read_calibration()
    assert out["ok"] and out["tickets"] == [] and out["aggregates"]["n"] == 0


# ── Edgeable partition + honest no-edgeable-market skip ───────────────────────

_CRYPTO_SIDE = {
    "outcomeId": 713, "name": "Recurring", "side": "Yes", "coin": "#7130",
    "price": 0.75, "volumeUsd": 188506.0, "category": "crypto-price",
    "resolution": {"underlying": "BTC", "targetPrice": 59122, "expiry": "20260702-0600", "period": "1d"},
}
_MACRO_SIDE = {
    "outcomeId": 510, "name": "No change", "side": "Yes", "coin": "#5100",
    "price": 0.6, "volumeUsd": 40000.0, "category": "macro",
    "description": "resolves to Yes if the July 2026 FOMC decision leaves the rate unchanged",
}
_SPORTS_SIDE = {
    "outcomeId": 173, "name": "Argentina", "side": "No", "coin": "#1731",
    "price": 0.81, "volumeUsd": 287125.0, "category": "sports",
    "description": "resolves to Yes if Argentina is the 2026 FIFA World Cup champion",
}


def test_partition_splits_crypto_and_macro_from_sports() -> None:
    edgeable, efficient = outcomes.partition_edgeable([_SPORTS_SIDE, _CRYPTO_SIDE, _MACRO_SIDE])
    assert {s["coin"] for s in edgeable} == {"#7130", "#5100"}
    assert [s["coin"] for s in efficient] == ["#1731"]


def test_partition_treats_uncategorized_side_as_efficient() -> None:
    # Fail closed: a side with no category (older bridge output) is never called edgeable.
    edgeable, efficient = outcomes.partition_edgeable([{"coin": "#x", "price": 0.5, "volumeUsd": 99999.0}])
    assert edgeable == [] and len(efficient) == 1


def test_markets_surfaces_edgeable_crypto_market(monkeypatch) -> None:
    monkeypatch.setattr(outcomes, "fetch_sides", lambda min_vol=outcomes.MIN_VOLUME: [_SPORTS_SIDE, _CRYPTO_SIDE])
    out = outcomes.cmd_markets(argparse.Namespace(min_vol=None))
    assert out["ok"] and out["edgeable_count"] == 1
    assert out["edgeable"][0]["coin"] == "#7130"
    assert "no_edgeable_market" not in out  # an edgeable market exists → no honest-skip reason


def test_markets_emits_explicit_no_edgeable_reason_when_only_sports(monkeypatch) -> None:
    # The honest-skip path: only efficient sports clear the floor. The desk must say so
    # in a structured, observable way — idle by market availability, not by bug.
    monkeypatch.setattr(outcomes, "fetch_sides", lambda min_vol=outcomes.MIN_VOLUME: [_SPORTS_SIDE])
    out = outcomes.cmd_markets(argparse.Namespace(min_vol=None))
    assert out["ok"] and out["edgeable_count"] == 0
    assert "no_edgeable_market" in out
    assert "efficient" in out["no_edgeable_market"] and "sports" in out["no_edgeable_market"]


def test_gate_still_refuses_no_edge_sports_side() -> None:
    # Surfacing the broader set must NOT weaken the gate: an efficient sports side where the
    # LLM's probability does not diverge past the margin is still cleanly skipped.
    sides = [_SPORTS_SIDE]
    v = outcomes.evaluate_bet("#1731", prob=0.83, stake=8.0, sides=sides, open_coins=set(), n_open=0)
    assert v["placed"] is False and "margin" in v["skipped"]
