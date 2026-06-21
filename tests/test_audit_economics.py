"""The economics checkpoint — measures the TRUE edge, not funding noise.

The whole point is to separate real position closes from funding dust and call the edge
honestly, then fire only after a fresh batch of N. These pin that logic so a future
change can't quietly mis-count or mis-verdict.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import audit_economics as ae


def _journal(gclaw_home, pnls):
    lines = [json.dumps({"event": "settle", "pnl": p}) for p in pnls]
    (gclaw_home / "journal.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_real_closes_filter_out_funding_dust(gclaw_home):
    # funding accruals (|pnl| <= 0.1) are noise; only real closes count
    _journal(gclaw_home, [0.01, -0.02, 0.009, -2.5, 1.3, 0.05])
    assert ae.real_closes() == [-2.5, 1.3]


def test_economics_math(gclaw_home):
    e = ae.economics([-1.0, -2.0, 3.0, -1.0])
    assert e["n"] == 4
    assert e["wins"] == 1 and e["win_rate"] == 0.25
    assert e["avg_win"] == 3.0 and e["avg_loss"] == round((-1 - 2 - 1) / 3, 2)
    assert e["net"] == -1.0 and e["expectancy"] == -0.25


def test_verdict_reads_the_edge():
    assert "PROFITABLE" in ae.verdict({"n": 5, "expectancy": 0.5, "win_rate": 0.6})
    assert "break-even" in ae.verdict({"n": 5, "expectancy": -0.1, "win_rate": 0.45})
    assert "-EV" in ae.verdict({"n": 5, "expectancy": -1.2, "win_rate": 0.1})


def test_check_fires_only_after_n_fresh_closes(gclaw_home, monkeypatch):
    monkeypatch.setattr(ae, "_send_telegram", lambda _t: False)  # never actually send
    _journal(gclaw_home, [-1.0, 2.0])  # 2 real closes
    ae.cmd_baseline(SimpleNamespace())  # baseline = 2 → only NEW closes count

    # 2 more real closes — below the threshold of 3
    _journal(gclaw_home, [-1.0, 2.0, -0.5, 0.6])
    out = ae.cmd_check(SimpleNamespace(n=3))
    assert out["milestone"] is False and out["progress"] == "2/3 new real closes"

    # a third fresh close trips it — and it reports ONLY the 3 fresh ones, then advances
    _journal(gclaw_home, [-1.0, 2.0, -0.5, 0.6, 1.0])
    out = ae.cmd_check(SimpleNamespace(n=3))
    assert out["milestone"] is True and out["n"] == 3
    assert ae.cmd_check(SimpleNamespace(n=3))["milestone"] is False  # baseline advanced
