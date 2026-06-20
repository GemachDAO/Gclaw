"""Crash-safety / atomicity tests for the file-based state writers.

Gclaw runs unattended; a crash (or a kill -9, or a full disk) mid-write must NEVER
leave a state file half-written, because the next heartbeat reads it back and would
mis-book GMAC / goodwill / treasury or lose the trade memory. Every writer uses the
temp-file + ``os.replace`` pattern, which is atomic on a single filesystem: a reader
sees either the OLD file or the NEW file, never a torn one.

We prove that by injecting a crash AFTER the temp file is written but BEFORE the
rename commits (monkeypatching ``os.replace`` to raise), then asserting the original
file is still present and still valid JSON. We also assert the readers degrade on a
corrupt/empty/missing file instead of crashing.

Covered writers:
  * metabolism.save_state   (metabolism.json — GMAC/goodwill/treasury)
  * evolve.save_state       (the same shared metabolism.json)
  * memory._write_atomic    (edges.json — the proven-edge cache)
"""

from __future__ import annotations

import json

import pytest

import memory
import metabolism


def _read(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestMetabolismSaveStateAtomicity:
    """metabolism.save_state must never corrupt the prior metabolism.json."""

    def test_a_committed_save_is_readable(self, gclaw_home, metabolism_fixture) -> None:
        metabolism_fixture(gmac_balance=1000.0)
        state = metabolism.load_state()
        state["gmac_balance"] = 1234.5
        metabolism.save_state(state)
        assert _read(metabolism.state_path())["gmac_balance"] == 1234.5

    def test_crash_during_rename_leaves_the_old_file_intact(
        self, gclaw_home, metabolism_fixture, monkeypatch
    ) -> None:
        """Inject a crash between writing the temp file and committing the rename.

        The OLD metabolism.json must survive untouched and stay valid JSON — the
        next heartbeat reads the last-good state, not a corrupt one.
        """
        metabolism_fixture(gmac_balance=1000.0, goodwill=7)
        before = _read(metabolism.state_path())

        def boom(_src, _dst):
            raise OSError("simulated crash before commit")

        monkeypatch.setattr(metabolism.os, "replace", boom)
        new_state = metabolism.load_state()
        new_state["gmac_balance"] = -999.0  # the write we will lose
        with pytest.raises(OSError):
            metabolism.save_state(new_state)

        # The original file is byte-for-byte the last good state.
        after = _read(metabolism.state_path())
        assert after == before
        assert after["gmac_balance"] == 1000.0
        assert after["goodwill"] == 7

    def test_no_temp_file_is_left_after_a_successful_save(
        self, gclaw_home, metabolism_fixture
    ) -> None:
        metabolism_fixture(gmac_balance=1000.0)
        state = metabolism.load_state()
        metabolism.save_state(state)
        leftovers = [p.name for p in gclaw_home.iterdir() if ".tmp" in p.name]
        assert leftovers == []


class TestEvolveSaveStateAtomicity:
    """evolve.save_state writes the SAME shared metabolism.json — same guarantee."""

    def test_crash_during_rename_leaves_old_metabolism_intact(
        self, gclaw_home, metabolism_fixture, monkeypatch
    ) -> None:
        import evolve

        metabolism_fixture(gmac_balance=500.0, goodwill=3)
        before = _read(gclaw_home / "metabolism.json")

        def boom(_src, _dst):
            raise OSError("crash before commit")

        monkeypatch.setattr(evolve.os, "replace", boom)
        state = evolve.load_state()
        state["goodwill"] = 99999
        with pytest.raises(OSError):
            evolve.save_state(state)

        assert _read(gclaw_home / "metabolism.json") == before


class TestMemoryAtomicWrite:
    """memory._write_atomic (edges.json) — same temp+replace contract."""

    def test_crash_during_rename_leaves_the_prior_edges_intact(
        self, gclaw_home, monkeypatch
    ) -> None:
        edges = gclaw_home / "edges.json"
        memory._write_atomic(edges, json.dumps([{"t": "a", "r": "trend", "e": 0.4}]))
        before = edges.read_text(encoding="utf-8")

        def boom(_src, _dst):
            raise OSError("crash before commit")

        monkeypatch.setattr(memory.os, "replace", boom)
        with pytest.raises(OSError):
            memory._write_atomic(edges, json.dumps([{"corrupt": True}]))

        assert edges.read_text(encoding="utf-8") == before

    def test_no_temp_turds_after_a_successful_write(self, gclaw_home) -> None:
        memory._write_atomic(gclaw_home / "edges.json", "[]")
        assert [p.name for p in gclaw_home.iterdir() if ".tmp" in p.name] == []


class TestReadersDegradeOnBadState:
    """The READ side must fail-conservative on a corrupt/empty file, not explode."""

    def test_metabolism_load_state_fails_fast_with_a_clear_message_when_unborn(
        self, gclaw_home
    ) -> None:
        # No metabolism.json -> a clear actionable exit, not a stack trace.
        with pytest.raises(SystemExit) as exc:
            metabolism.load_state()
        assert "init" in str(exc.value)

    def test_metabolism_load_state_raises_on_corrupt_json(
        self, gclaw_home, metabolism_fixture
    ) -> None:
        # A corrupt state file is a hard error (json.JSONDecodeError) — the metabolism
        # is the source of truth for money and must NOT silently default to a fresh
        # seed (that would mint life energy). Fail loud so an operator notices.
        metabolism_fixture()
        metabolism.state_path().write_text("{ corrupt", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            metabolism.load_state()

    def test_memory_peek_style_reads_degrade_on_corrupt_file(self, gclaw_home) -> None:
        # memory._read_json (used for the swarm roster) returns the default on bad JSON.
        bad = gclaw_home / "peers_roster.json"
        bad.write_text("{ not json", encoding="utf-8")
        assert memory._read_json(bad, {"roster": []}) == {"roster": []}

    def test_memory_load_returns_empty_on_missing_store(self, gclaw_home) -> None:
        # No memory.jsonl yet (just-born home) -> an empty history, not a crash.
        assert memory.load() == []

    def test_memory_load_skips_blank_lines(self, gclaw_home) -> None:
        store = gclaw_home / "memory.jsonl"
        store.write_text(
            json.dumps({"r": 1.0, "pnl": 1.0, "technique": "t", "regime": "trend"}) + "\n\n",
            encoding="utf-8",
        )
        rows = memory.load()
        assert len(rows) == 1
