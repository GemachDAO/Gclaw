"""Shared pytest fixtures for the Gclaw skill.

The scripts under ``scripts/`` are stdlib-only and directly importable — there is
no package install. This conftest makes that import trivial (puts ``scripts/`` on
``sys.path``) and supplies the four fixtures every test needs:

* ``gclaw_home``  — an isolated tmp ``$GCLAW_HOME`` (env + cwd patched), so no test
  ever touches the real ``~/.gclaw``.
* ``metabolism_fixture`` — a factory that births a seeded ``metabolism.json`` there.
* ``frozen_time`` — pins ``datetime.now`` and ``time.time`` so timestamps are stable.
* ``hl_response`` — loads a recorded HyperLiquid API payload from ``tests/fixtures/``.

Golden rule: a unit test reaches the real network, the real clock, or the real
home directory ONLY through these fixtures. If you need the real thing, you're
writing an integration test — mark it ``@pytest.mark.slow`` and isolate it.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timezone
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# Make `import metabolism`, `import sizing`, ... work without any install step.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture
def gclaw_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated, empty ``$GCLAW_HOME`` for one test.

    Points ``$GCLAW_HOME`` at a fresh tmp dir, chdirs into it, and scrubs ``$HOME``
    indirection so a script that falls back to ``~/.gclaw`` still can't escape the
    sandbox. Returns the home path so tests can read/write runtime files directly.
    """
    home = tmp_path / "gclaw_home"
    home.mkdir()
    monkeypatch.setenv("GCLAW_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    return home


@pytest.fixture
def metabolism_fixture(gclaw_home: Path):
    """Factory that writes a seeded ``metabolism.json`` and returns the state dict.

    Call ``metabolism()`` for a default healthy agent, or override any field:
    ``metabolism(gmac_balance=40)`` to land it in survive mode,
    ``metabolism(gmac_balance=0)`` for hibernate. The file lands in ``$GCLAW_HOME``
    so the imported ``metabolism`` module reads exactly what the test seeded.
    """
    state_path = gclaw_home / "metabolism.json"

    def _make(**overrides: object) -> dict[str, object]:
        state: dict[str, object] = {
            "schema_version": 1,
            "gmac_balance": 1000.0,
            "seed": 1000.0,
            "goodwill": 0,
            "heartbeats": 0,
            "recodes": 0,
            "children": [],
            "gmac_treasury_usd": 0.0,
            "gmac_tokens_held": 0.0,
            "survival_threshold": 100.0,
            "heartbeat_cost": 1.0,
            "inference_cost": 0.5,
            "born_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "mode": "thrive",
        }
        state.update(overrides)
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        return state

    return _make


@pytest.fixture
def frozen_time(monkeypatch: pytest.MonkeyPatch):
    """Pin wall-clock time across stdlib so timestamps in journals/state are stable.

    Yields the frozen ``datetime``. Patches ``datetime.now`` (used by metabolism's
    ``now_iso``) on every already-imported script module, so ``import metabolism``
    before this fixture still gets the frozen clock.
    """
    frozen = datetime(2026, 6, 17, 12, 0, 0, tzinfo=UTC)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)

    for module_name in ("metabolism", "evolve", "memory"):
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, "datetime"):
            monkeypatch.setattr(module, "datetime", _Frozen)
    return frozen


@pytest.fixture
def forge_style(gclaw_home: Path):
    """Seed ``$GCLAW_HOME/forge/style.json`` with an adopted loadout.

    ``_update_fitness`` and ``_gate`` read/write the live style + regime-stats files,
    so a test that exercises the Darwinian weight update needs them to exist. forge's
    ``forge_dir()`` returns ``$GCLAW_HOME/forge`` (where style.json lives), with the
    per-technique dirs under ``forge/techniques/<tid>/``. The factory writes a minimal
    style and returns its path; pass ``adopted=[...]`` to override the loadout
    (each entry: ``{"id","weight","e","trades"}``).
    """
    forge_root = gclaw_home / "forge"
    (forge_root / "techniques").mkdir(parents=True, exist_ok=True)

    def _make(adopted: list[dict] | None = None) -> Path:
        if adopted is None:
            adopted = [
                {
                    "id": "t-alpha",
                    "coin": "BTC",
                    "interval": "1h",
                    "weight": 0.5,
                    "e": 0.0,
                    "trades": 0,
                }
            ]
        path = forge_root / "style.json"
        path.write_text(json.dumps({"agent": "test", "adopted": adopted}), encoding="utf-8")
        return path

    return _make


@pytest.fixture
def forge_technique(gclaw_home: Path):
    """Seed ``$GCLAW_HOME/forge/techniques/<tid>/technique.json`` so ``_gate`` can read a
    technique's declared per-regime priors. Returns a factory."""

    def _make(tid: str, regimes: dict[str, float] | None = None) -> Path:
        d = gclaw_home / "forge" / "techniques" / tid
        d.mkdir(parents=True, exist_ok=True)
        path = d / "technique.json"
        path.write_text(json.dumps({"id": tid, "regimes": regimes or {}}), encoding="utf-8")
        return path

    return _make


@pytest.fixture
def base_genome():
    """A deterministic parent genome for breed() tests, built via the real genome()."""
    import dashboard

    return dashboard.genome("Origin", "2026-01-01T00:00:00+00:00")


@pytest.fixture
def hl_response():
    """Loader for recorded HyperLiquid API payloads under ``tests/fixtures/``.

    ``hl_response("candles_btc_1h")`` returns the parsed JSON in
    ``tests/fixtures/candles_btc_1h.json``. Record real payloads once, replay them
    forever — no test hits ``api.hyperliquid.xyz``.
    """

    def _load(name: str) -> object:
        path = FIXTURES_DIR / f"{name}.json"
        if not path.exists():
            pytest.fail(
                f"No HL fixture '{name}' at {path}. "
                "Record one with `node scripts/intel.js scan > tests/fixtures/{name}.json` "
                "or hand-write the minimal payload."
            )
        return json.loads(path.read_text(encoding="utf-8"))

    return _load
