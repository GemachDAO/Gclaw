"""Reproduction-on-proven-edge (scripts/evolve.py). Reproduction gates on forge-graduated
live edge — not raw goodwill (the fragile signal that killed Spore.fun's offspring) — and
only SPAWNS when armed (GCLAW_REPRODUCE_LIVE=1), so it's pinned before any real birth.
"""

from __future__ import annotations

import json
from argparse import Namespace

import pytest

import evolve

AID = "55624"


def _seed_dna(home):
    dna = home / "dna"
    dna.mkdir(parents=True, exist_ok=True)
    (dna / "TRADING_STRATEGY.md").write_text("# Strategy\n\nBase rules.\n", encoding="utf-8")


def _seed_forge(home, proven: int, authored: int = 0):
    """Write a forge/style.json with `proven` live-proven techniques (e>0, trades>=3) and
    `authored` self-authored technique.json files (author == AID)."""
    techs = home / "forge" / "techniques"
    techs.mkdir(parents=True, exist_ok=True)
    adopted = []
    for i in range(proven):
        tid = f"win{i}"
        adopted.append({"id": tid, "coin": "SOL", "interval": "1h", "e": 0.1, "trades": 5})
    for i in range(authored):
        tid = f"auth{i}"
        adopted.append({"id": tid, "coin": "ETH", "interval": "1h", "e": -0.01, "trades": 1})
        (techs / tid).mkdir(parents=True, exist_ok=True)
        (techs / tid / "technique.json").write_text(
            json.dumps({"id": tid, "author": AID}), encoding="utf-8"
        )
    (home / "forge" / "style.json").write_text(json.dumps({"adopted": adopted}), encoding="utf-8")


def _meta(metabolism_fixture, **kw):
    return metabolism_fixture(children=[], recodes=0, onchain_identity={"agentId": AID}, **kw)


def test_locked_without_enough_proven_edge(metabolism_fixture, gclaw_home, monkeypatch):
    monkeypatch.setenv("GCLAW_REPRODUCE_LIVE", "1")
    _meta(metabolism_fixture, goodwill=5)  # goodwill is now irrelevant
    _seed_dna(gclaw_home)
    _seed_forge(gclaw_home, proven=1)  # below REPLICATE_MIN_EDGE (2)
    with pytest.raises(SystemExit, match="proven-edge"):
        evolve.cmd_replicate(Namespace(auto=False, name="early", role="scout", mutation="x"))
    assert not (gclaw_home / "children" / "early").exists()


def test_goodwill_is_irrelevant_proven_edge_gates(metabolism_fixture, gclaw_home, monkeypatch):
    # goodwill 8 (never crosses the old 50) but 2 proven techniques → ARMED → spawns.
    monkeypatch.setenv("GCLAW_REPRODUCE_LIVE", "1")
    _meta(metabolism_fixture, goodwill=8)
    _seed_dna(gclaw_home)
    _seed_forge(gclaw_home, proven=2)
    evolve.cmd_replicate(Namespace(auto=True, name=None, role=None, mutation=None))
    state = json.loads((gclaw_home / "metabolism.json").read_text(encoding="utf-8"))
    assert len(state["children"]) == 1
    assert state["last_replicate_edge_count"] == 2  # next birth needs NEW proven edge
    strat = (
        gclaw_home / "children" / state["children"][0]["name"] / "TRADING_STRATEGY.md"
    ).read_text()
    assert "win0" in strat and "win1" in strat  # inherits the proven winners by name


def test_dry_run_is_the_default_and_spawns_nothing(metabolism_fixture, gclaw_home, monkeypatch):
    monkeypatch.delenv("GCLAW_REPRODUCE_LIVE", raising=False)  # default = dry-run
    _meta(metabolism_fixture, goodwill=8)
    _seed_dna(gclaw_home)
    _seed_forge(gclaw_home, proven=2)
    evolve.cmd_replicate(Namespace(auto=True, name=None, role=None, mutation=None))
    assert not (gclaw_home / "children").exists()  # gate met, but nothing spawned
    state = json.loads((gclaw_home / "metabolism.json").read_text(encoding="utf-8"))
    assert state["children"] == []


def test_anti_storm_requires_new_proven_edge(metabolism_fixture, gclaw_home, monkeypatch):
    monkeypatch.setenv("GCLAW_REPRODUCE_LIVE", "1")
    _meta(metabolism_fixture, goodwill=8)
    _seed_dna(gclaw_home)
    _seed_forge(gclaw_home, proven=2)
    evolve.cmd_replicate(Namespace(auto=True, name=None, role=None, mutation=None))
    # a second spawn with NO new proven edge (still 2) is refused
    with pytest.raises(SystemExit, match="no new proven edge"):
        evolve.cmd_replicate(Namespace(auto=False, name="second", role="analyst", mutation="b"))
    # graduate a third proven technique → allowed again
    _seed_forge(gclaw_home, proven=3)
    evolve.cmd_replicate(Namespace(auto=True, name=None, role=None, mutation=None))
    state = json.loads((gclaw_home / "metabolism.json").read_text(encoding="utf-8"))
    assert len(state["children"]) == 2 and state["last_replicate_edge_count"] == 3


def test_recode_syncs_to_authored_adopted_count(metabolism_fixture, gclaw_home):
    _meta(metabolism_fixture, goodwill=8)
    _seed_forge(gclaw_home, proven=2, authored=3)  # 3 self-authored adopted techniques
    evolve.cmd_recode(Namespace())
    state = json.loads((gclaw_home / "metabolism.json").read_text(encoding="utf-8"))
    assert state["recodes"] == 3  # honest count of self-modifications, no goodwill gate


def test_partial_failure_rolls_back_the_child_dir(metabolism_fixture, gclaw_home, monkeypatch):
    monkeypatch.setenv("GCLAW_REPRODUCE_LIVE", "1")
    _meta(metabolism_fixture, goodwill=8)
    _seed_dna(gclaw_home)
    _seed_forge(gclaw_home, proven=2)
    monkeypatch.setattr(
        evolve, "save_state", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("disk full"))
    )
    with pytest.raises(RuntimeError, match="disk full"):
        evolve.cmd_replicate(Namespace(auto=True, name=None, role=None, mutation=None))
    assert (
        not list((gclaw_home / "children").glob("*"))
        if (gclaw_home / "children").exists()
        else True
    )
    state = json.loads((gclaw_home / "metabolism.json").read_text(encoding="utf-8"))
    assert state["children"] == []
