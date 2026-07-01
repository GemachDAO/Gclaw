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
    monkeypatch.setattr(
        forge, "load_style", lambda: {"adopted": [{"id": "mom", "coin": "ETH", "interval": "4h"}]}
    )
    monkeypatch.setattr(forge, "_intel_features", lambda: universe)
    monkeypatch.setattr(forge, "load_signal", lambda _tid: None)  # ignored — backtest is mocked
    monkeypatch.setattr(forge, "_backtest_with", bt)


def _card(proven, n=50, exp=0.01):
    return {"proven": proven, "out_of_sample": {"n": n, "expectancy": exp}}


def test_autoprove_registers_only_pairs_with_out_of_sample_edge(gclaw_home, monkeypatch):
    universe = {
        "ETH": {"regime": "range"},
        "xyz:MU": {"regime": "range"},
        "xyz:DUST": {"regime": "range"},
    }

    def bt(_fn, coin, _interval, _limit, _tid=None):
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

    def bt(_fn, coin, _interval, _limit, _tid=None):
        calls.append(coin)
        return _card(False)  # never proves → would be retried every run without a cooldown

    _wire(monkeypatch, universe, bt)
    forge.cmd_autoprove(Namespace(budget=10))  # attempts xyz:MU
    forge.cmd_autoprove(Namespace(budget=10))  # within cooldown → must NOT retry
    assert calls == ["xyz:MU"]  # attempted exactly once


def test_autoprove_no_intel_is_a_safe_noop(gclaw_home, monkeypatch):
    monkeypatch.setattr(
        forge, "load_style", lambda: {"adopted": [{"id": "mom", "coin": "ETH", "interval": "4h"}]}
    )
    monkeypatch.setattr(forge, "_intel_features", lambda: {})  # no scan yet
    out = forge.cmd_autoprove(Namespace(budget=10))
    assert out["ok"] and "skipped" in out


def test_proven_pairs_round_trips_the_registry(gclaw_home):
    path = gclaw_home / "forge" / "proven_markets.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"pairs":[{"technique":"mom","coin":"xyz:MU"}],"attempts":{}}', encoding="utf-8"
    )
    assert forge.proven_pairs() == {("mom", "xyz:MU")}
