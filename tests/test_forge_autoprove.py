"""Auto-prove: grow the tradeable surface to match the discovered universe.

The agent could only execute on its birth-arsenal coins (BTC/ETH/SOL/TSLA) while the
dynamic universe surfaced setups on oil/gold/semis it was forbidden to trade. autoprove
backtests each strategy across the new markets and registers the pairs with real
out-of-sample edge. These pin the registry + cooldown so the loop can't over-fire or
register edge-less pairs. The backtest itself is mocked (no network / no candle data).
"""

from __future__ import annotations

from argparse import Namespace

import forge


def _wire(monkeypatch, universe, bt):
    monkeypatch.setattr(forge, "load_style", lambda: {"adopted": [{"id": "mom", "coin": "ETH", "interval": "4h"}]})
    monkeypatch.setattr(forge, "_intel_features", lambda: universe)
    monkeypatch.setattr(forge, "load_signal", lambda _tid: None)  # ignored — backtest is mocked
    monkeypatch.setattr(forge, "_backtest_with", bt)


def _card(proven, n=50, exp=0.01):
    return {"proven": proven, "out_of_sample": {"n": n, "expectancy": exp}}


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
