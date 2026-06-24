"""Auto-prove: grow the tradeable surface to match the discovered universe.

The agent could only execute on its birth-arsenal coins (BTC/ETH/SOL/TSLA) while the
dynamic universe surfaced setups on oil/gold/semis it was forbidden to trade. autoprove
backtests each strategy across the new markets and registers the pairs with real
out-of-sample edge. These pin the registry + cooldown so the loop can't over-fire or
register edge-less pairs. The backtest itself is mocked (no network / no candle data).
"""

from __future__ import annotations

import json
from argparse import Namespace

import forge

_FLAT_SIGNAL = "def signal(f):\n    return {'action': 'flat', 'confidence': 0.0, 'stop_pct': 1.5}\n"


def _make_technique(tid: str, parent: str | None = None) -> None:
    """Write a minimal local draft technique (technique.json + a valid signal) to disk."""
    d = forge.tech_dir(tid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "technique.json").write_text(json.dumps({"id": tid, "parent": parent, "status": "draft"}))
    (d / "signal.py").write_text(_FLAT_SIGNAL)


def _proven_card(_fn, coin, interval, _limit):
    return {"proven": True, "coin": coin, "interval": interval,
            "out_of_sample": {"n": 80, "expectancy": 0.01}}


def _wire(monkeypatch, universe, bt):
    monkeypatch.setattr(forge, "load_style", lambda: {"adopted": [{"id": "mom", "coin": "ETH", "interval": "4h"}]})
    monkeypatch.setattr(forge, "_intel_features", lambda: universe)
    monkeypatch.setattr(forge, "load_signal", lambda _tid: None)  # ignored — backtest is mocked
    monkeypatch.setattr(forge, "_backtest_with", bt)


def _card(proven, n=50, exp=0.01):
    return {"proven": proven, "out_of_sample": {"n": n, "expectancy": exp}}


def test_draft_candidates_includes_local_drafts_excludes_pooled_and_adopted(gclaw_home):
    """The discovery loop mines un-adopted LOCAL drafts; a pooled technique (with a parent)
    must be hand-critiqued, and an already-adopted one isn't a candidate."""
    _make_technique("local-draft")
    _make_technique("pooled", parent="999/foo")
    _make_technique("already-in")
    cands = forge._draft_candidates({"already-in"})
    assert "local-draft" in cands
    assert "pooled" not in cands  # untrusted import — never auto-enters the rotation
    assert "already-in" not in cands


def test_autoprove_auto_adopts_a_draft_that_proves(gclaw_home, monkeypatch):
    """A local draft that proves on a market is registered AND adopted into the voting
    rotation, so cmd_run can actually trade the newly discovered edge."""
    forge.save_style({"adopted": [{"id": "mom", "coin": "ETH", "interval": "4h"}]})
    _make_technique("newmom")
    monkeypatch.setattr(forge, "_intel_features", lambda: {"xyz:ABC": {"regime": "range"}})
    monkeypatch.setattr(forge, "load_signal", lambda _tid: (lambda f: None))
    monkeypatch.setattr(forge, "_backtest_with", _proven_card)

    out = forge.cmd_autoprove(Namespace(budget=20))
    assert out.get("auto_adopted")  # the draft graduated
    assert "newmom@xyz:ABC" in out["auto_adopted"][0]
    assert "newmom" in {e["id"] for e in forge.load_style()["adopted"]}
    assert ("newmom", "xyz:ABC") in forge.proven_pairs()


def test_autoprove_respects_max_adopted_cap(gclaw_home, monkeypatch):
    """A proving draft must NOT enter the rotation once it is full — the cap stops
    auto-discovery from bloating the ensemble."""
    full = [{"id": f"t{i}", "coin": "ETH", "interval": "4h"} for i in range(forge.MAX_ADOPTED)]
    forge.save_style({"adopted": full})
    _make_technique("overflow")
    monkeypatch.setattr(forge, "_intel_features", lambda: {"xyz:ABC": {"regime": "range"}})
    monkeypatch.setattr(forge, "load_signal", lambda _tid: (lambda f: None))
    monkeypatch.setattr(forge, "_backtest_with", _proven_card)

    forge.cmd_autoprove(Namespace(budget=30))
    assert "overflow" not in {e["id"] for e in forge.load_style()["adopted"]}  # cap holds


def test_royalty_surfaces_real_risk_technique_regime_for_the_settler(gclaw_home):
    """cmd_royalty must return the local technique, the REAL sized risk_usd, and the entry
    regime at TOP level so the settler records an honest R-multiple (pnl / real risk).

    The bug: autosettle read `.technique` but royalty nested it under `.attributed`, so
    every forge trade was mis-tagged 'discretionary' and its risk fabricated from a dead
    open_risk.json. These three fields are what make the trade-memory accurate.
    """
    forge.save_pending({
        "SOL": {"ref": "55624/stop-hunt-revert", "technique": "stop-hunt-revert",
                "risk_usd": 3.12, "regime": "range", "opened_at": "x"},
    })
    out = forge.cmd_royalty(Namespace(coin="SOL", pnl=5.0, auto=True, ref=None))
    assert out["ok"] is True
    assert out["technique"] == "stop-hunt-revert"
    assert out["risk_usd"] == 3.12
    assert out["regime"] == "range"
    assert "SOL" not in forge.load_pending()  # consumed on close, can't re-attribute


def test_royalty_auto_on_unknown_coin_returns_empty_attribution(gclaw_home):
    """No pending + no adopted technique → auto mode returns cleanly (no real risk to
    surface), so the settler falls back to its stop estimate rather than crashing."""
    out = forge.cmd_royalty(Namespace(coin="DOGE", pnl=1.0, auto=True, ref=None))
    assert out["ok"] is True
    assert out.get("technique", "") == ""
    assert out.get("risk_usd", 0.0) == 0.0


def test_autoprove_registers_only_pairs_with_out_of_sample_edge(gclaw_home, monkeypatch):
    universe = {"ETH": {"regime": "range"}, "xyz:MU": {"regime": "range"}, "xyz:DUST": {"regime": "range"}}

    def bt(_fn, coin, _interval, _limit):
        return _card(coin == "xyz:MU")  # only MU has edge

    _wire(monkeypatch, universe, bt)
    out = forge.cmd_autoprove(Namespace(budget=10))

    assert out["newly_proven"] == ["mom@xyz:MU"]  # only the one with edge graduates
    pairs = forge.proven_pairs()
    assert ("mom", "xyz:MU") in pairs
    assert ("mom", "xyz:DUST") not in pairs  # tried but no edge → not registered
    assert ("mom", "ETH") not in pairs  # native arsenal coin is skipped (already tradeable)


def test_autoprove_cooldown_skips_a_recently_attempted_pair(gclaw_home, monkeypatch):
    universe = {"xyz:MU": {"regime": "range"}}
    calls = []

    def bt(_fn, coin, _interval, _limit):
        calls.append(coin)
        return _card(False)  # never proves → would be retried every run without a cooldown

    _wire(monkeypatch, universe, bt)
    forge.cmd_autoprove(Namespace(budget=10))  # attempts xyz:MU
    forge.cmd_autoprove(Namespace(budget=10))  # within cooldown → must NOT retry
    assert calls == ["xyz:MU"]  # attempted exactly once


def test_autoprove_no_intel_is_a_safe_noop(gclaw_home, monkeypatch):
    monkeypatch.setattr(forge, "load_style", lambda: {"adopted": [{"id": "mom", "coin": "ETH", "interval": "4h"}]})
    monkeypatch.setattr(forge, "_intel_features", lambda: {})  # no scan yet
    out = forge.cmd_autoprove(Namespace(budget=10))
    assert out["ok"] and "skipped" in out


def test_proven_pairs_round_trips_the_registry(gclaw_home):
    path = gclaw_home / "forge" / "proven_markets.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"pairs":[{"technique":"mom","coin":"xyz:MU"}],"attempts":{}}', encoding="utf-8")
    assert forge.proven_pairs() == {("mom", "xyz:MU")}
