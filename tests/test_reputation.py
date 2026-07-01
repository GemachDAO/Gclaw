"""reputation.py — the financially-accountable scorecard. It must derive reputation ONLY
from settled performance + forge graduation (not goodwill/activity), so the numbers are
re-derivable from the chain. The settled-PnL source is mocked (no journal/network)."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import reputation

AID = "55624"


def _seed(home: Path, adopted: list[dict], authored: list[str]) -> None:
    (home / "metabolism.json").write_text(json.dumps({
        "born_at": "2026-06-17T00:00:00+00:00", "heartbeats": 346, "recodes": 4,
        "children": [{"name": "scion-1"}],
        "onchain_identity": {"agentId": AID, "chain": "base:8453", "registry": "0xReg", "agentUrl": "u"},
    }), encoding="utf-8")
    techs = home / "forge" / "techniques"
    techs.mkdir(parents=True, exist_ok=True)
    (home / "forge" / "style.json").write_text(json.dumps({"adopted": adopted}), encoding="utf-8")
    for tid in authored:
        (techs / tid).mkdir(parents=True, exist_ok=True)
        (techs / tid / "technique.json").write_text(json.dumps({"id": tid, "author": AID}), encoding="utf-8")


def test_card_is_backed_by_settled_performance(gclaw_home, monkeypatch):
    monkeypatch.setattr(reputation, "_economics", lambda: {
        "n": 52, "win_rate": 0.19, "avg_win": 1.2, "avg_loss": -1.23, "net": -39.82, "expectancy": -0.77,
    })
    _seed(
        gclaw_home,
        adopted=[
            {"id": "stop-hunt-revert", "e": 0.16, "trades": 9},   # proven (seed author)
            {"id": "vol-momentum", "e": 0.05, "trades": 5},        # proven + self-authored
            {"id": "weak", "e": -0.01, "trades": 8},               # adopted but not proven
        ],
        authored=["vol-momentum"],  # only this one is author==AID
    )
    c = reputation.card()
    assert c["agentId"] == AID
    assert c["trading"]["realized_pnl_usd"] == -39.82 and c["trading"]["closed_trades"] == 52
    assert c["evolution"]["proven_edge_techniques"] == ["stop-hunt-revert", "vol-momentum"]
    assert c["evolution"]["proven_edge_count"] == 2
    assert c["evolution"]["self_authored_techniques"] == 1  # only vol-momentum is authored by AID
    assert c["evolution"]["children"] == 1
    assert c["verifiable_via"]["registry"] == "0xReg"
    assert "SETTLED" in c["accountability"]


def test_publish_writes_the_canonical_file(gclaw_home, monkeypatch):
    monkeypatch.setattr(reputation, "_economics", lambda: {"n": 3, "net": 1.5})
    _seed(gclaw_home, adopted=[], authored=[])
    reputation.cmd_publish(Namespace())
    written = json.loads((gclaw_home / "reputation.json").read_text(encoding="utf-8"))
    assert written["trading"]["realized_pnl_usd"] == 1.5
    assert written["evolution"]["proven_edge_count"] == 0
