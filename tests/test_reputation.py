"""reputation.py — the financially-accountable scorecard. It must derive reputation ONLY
from settled performance + forge graduation (not goodwill/activity), so the numbers are
re-derivable from the chain. The settled-PnL source is mocked (no journal/network)."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import reputation

AID = "55624"


def _seed(
    home: Path,
    adopted: list[dict],
    authored: list[str],
    backtest_proven: tuple[str, ...] = (),
) -> None:
    (home / "metabolism.json").write_text(
        json.dumps(
            {
                "born_at": "2026-06-17T00:00:00+00:00",
                "heartbeats": 346,
                "recodes": 4,
                "children": [{"name": "scion-1"}],
                "onchain_identity": {
                    "agentId": AID,
                    "chain": "base:8453",
                    "registry": "0xReg",
                    "agentUrl": "u",
                },
            }
        ),
        encoding="utf-8",
    )
    techs = home / "forge" / "techniques"
    techs.mkdir(parents=True, exist_ok=True)
    (home / "forge" / "style.json").write_text(json.dumps({"adopted": adopted}), encoding="utf-8")
    for tid in {e["id"] for e in adopted} | set(authored):
        (techs / tid).mkdir(parents=True, exist_ok=True)
        (techs / tid / "technique.json").write_text(
            json.dumps(
                {
                    "id": tid,
                    "author": AID if tid in authored else "other",
                    "status": "proven" if tid in backtest_proven else "draft",
                }
            ),
            encoding="utf-8",
        )


def test_card_separates_live_proven_from_backtest_proven(gclaw_home, monkeypatch):
    monkeypatch.setattr(
        reputation,
        "_economics",
        lambda: {
            "n": 52,
            "win_rate": 0.19,
            "avg_win": 1.2,
            "avg_loss": -1.23,
            "net": -39.82,
            "expectancy": -0.77,
        },
    )
    # The honest signal: only stop-hunt-revert has a REAL live edge (bootstrap CI > 0).
    # vol-momentum merely graduated a backtest; its loose EWMA looks positive but the
    # settled record does not clear the live gate — it must NOT count as proven edge.
    monkeypatch.setattr(
        reputation,
        "_live_techniques",
        lambda: {
            "stop-hunt-revert": {"live_proven": True},
            "vol-momentum": {"live_proven": False},
            "weak": {"live_proven": False},
        },
    )
    _seed(
        gclaw_home,
        adopted=[
            {"id": "stop-hunt-revert", "e": 0.16, "trades": 9},
            {"id": "vol-momentum", "e": 0.05, "trades": 5},
            {"id": "weak", "e": -0.01, "trades": 8},
        ],
        authored=["vol-momentum"],  # only this one is author==AID
        backtest_proven=("stop-hunt-revert", "vol-momentum"),
    )
    c = reputation.card()
    assert c["agentId"] == AID
    assert c["trading"]["realized_pnl_usd"] == -39.82 and c["trading"]["closed_trades"] == 52
    # Headline (attested onchain) counts ONLY live-proven edge.
    assert c["evolution"]["proven_edge_techniques"] == ["stop-hunt-revert"]
    assert c["evolution"]["proven_edge_count"] == 1
    # Backtest tier is reported separately and does not inflate the headline.
    assert set(c["evolution"]["backtest_proven_techniques"]) == {"stop-hunt-revert", "vol-momentum"}
    assert c["evolution"]["backtest_proven_count"] == 2
    assert c["evolution"]["self_authored_techniques"] == 1  # only vol-momentum is authored by AID
    assert c["evolution"]["children"] == 1
    assert c["verifiable_via"]["registry"] == "0xReg"
    assert "SETTLED" in c["accountability"]


def test_publish_writes_the_canonical_file(gclaw_home, monkeypatch):
    monkeypatch.setattr(reputation, "_economics", lambda: {"n": 3, "net": 1.5})
    monkeypatch.setattr(reputation, "_live_techniques", dict)
    _seed(gclaw_home, adopted=[], authored=[])
    reputation.cmd_publish(Namespace())
    written = json.loads((gclaw_home / "reputation.json").read_text(encoding="utf-8"))
    assert written["trading"]["realized_pnl_usd"] == 1.5
    assert written["evolution"]["proven_edge_count"] == 0
    assert written["evolution"]["backtest_proven_count"] == 0
