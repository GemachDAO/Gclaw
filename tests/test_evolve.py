"""The replication / breed path (scripts/evolve.py) — never run live, so pin it before
goodwill first crosses 50. A child must be created AND recorded atomically: if anything
fails after the DNA is copied, the half-built directory must be rolled back, or the
exists() guard would block every future retry with that name and dead DNA would linger.
"""

from __future__ import annotations

import json
from argparse import Namespace

import pytest

import evolve


def _seed_dna(home):
    """Minimal live DNA so dna_source() resolves and the mutation append has a file."""
    dna = home / "dna"
    dna.mkdir(parents=True, exist_ok=True)
    (dna / "TRADING_STRATEGY.md").write_text("# Strategy\n\nBase rules.\n", encoding="utf-8")


def _boom(*_a, **_k):
    raise RuntimeError("disk full")


def test_replicate_creates_and_records_a_child(metabolism_fixture, gclaw_home):
    metabolism_fixture(goodwill=60)
    _seed_dna(gclaw_home)
    evolve.cmd_replicate(Namespace(name="scalper", role="scout", mutation="BTC 5m momentum"))

    child = gclaw_home / "children" / "scalper"
    assert child.is_dir()
    strat = (child / "TRADING_STRATEGY.md").read_text(encoding="utf-8")
    assert "Mutation (child: scalper)" in strat  # the differentiation was appended
    assert "BTC 5m momentum" in strat

    state = json.loads((gclaw_home / "metabolism.json").read_text(encoding="utf-8"))
    assert [c["name"] for c in state["children"]] == ["scalper"]
    assert state["children"][0]["role"] == "scout"
    journal = (gclaw_home / "journal.jsonl").read_text(encoding="utf-8")
    assert '"event": "replicate"' in journal


def test_replication_is_locked_below_the_goodwill_threshold(metabolism_fixture, gclaw_home):
    metabolism_fixture(goodwill=49)  # one short of REPLICATE_THRESHOLD
    _seed_dna(gclaw_home)
    with pytest.raises(SystemExit):
        evolve.cmd_replicate(Namespace(name="early", role="scout", mutation="x"))
    assert not (gclaw_home / "children" / "early").exists()


def _bump_goodwill(home, value):
    """Raise goodwill without disturbing children / last_replicate_goodwill."""
    st = json.loads((home / "metabolism.json").read_text(encoding="utf-8"))
    st["goodwill"] = value
    (home / "metabolism.json").write_text(json.dumps(st), encoding="utf-8")


def test_anti_storm_gate_requires_fresh_goodwill_between_births(metabolism_fixture, gclaw_home):
    # The same earned goodwill must not spawn child after child on consecutive cycles.
    metabolism_fixture(goodwill=60)
    _seed_dna(gclaw_home)
    evolve.cmd_replicate(Namespace(name="first", role="scout", mutation="a"))
    # birth #1 recorded the gate at goodwill 60
    state = json.loads((gclaw_home / "metabolism.json").read_text(encoding="utf-8"))
    assert state["last_replicate_goodwill"] == 60

    # a second spawn at the SAME goodwill is refused — nothing new earned since birth #1
    with pytest.raises(SystemExit, match="No new goodwill"):
        evolve.cmd_replicate(Namespace(name="second", role="analyst", mutation="b"))
    assert not (gclaw_home / "children" / "second").exists()

    # once goodwill grows, the next birth is allowed again
    _bump_goodwill(gclaw_home, 72)
    evolve.cmd_replicate(Namespace(name="third", role="analyst", mutation="c"))
    assert (gclaw_home / "children" / "third").is_dir()


def test_a_partial_failure_rolls_back_the_child_dir(metabolism_fixture, gclaw_home, monkeypatch):
    metabolism_fixture(goodwill=60)
    _seed_dna(gclaw_home)
    # save_state throws AFTER the DNA is copied — the classic half-built-child window.
    monkeypatch.setattr(evolve, "save_state", _boom)
    with pytest.raises(RuntimeError, match="disk full"):
        evolve.cmd_replicate(Namespace(name="doomed", role="scout", mutation="x"))

    # the stranded directory is gone, so a retry with the same name is NOT blocked
    assert not (gclaw_home / "children" / "doomed").exists()
    # and nothing was half-recorded into shared state
    state = json.loads((gclaw_home / "metabolism.json").read_text(encoding="utf-8"))
    assert state["children"] == []
