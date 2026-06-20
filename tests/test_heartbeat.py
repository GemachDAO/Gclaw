"""End-to-end heartbeat — the unattended loop's orchestration and its cadence brain.

The full heartbeat invokes the LLM + MCP, so it isn't hermetic. What IS testable and
hermetic — and is where breakage actually hurts — is the deterministic skeleton:
  * the STEP ORDERING + safety guards in heartbeat.sh (settle before render, riskguard
    after the cycle, the kill-switch / lock / fund-moving deny-list all present), and
  * the cadence brain (model_select.js): Opus + hourly when there's a position or live
    setup to weigh, Sonnet + stretch when flat — run as a real subprocess against an
    isolated home with a seeded status cache so it never touches the network or wallet.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
HEARTBEAT = (SCRIPTS / "heartbeat.sh").read_text(encoding="utf-8")
_PATH = os.environ.get("PATH", "/usr/bin:/bin")


def test_deterministic_steps_run_in_order():
    # Settle realized PnL BEFORE the dashboard renders it; the arsenal is seeded before
    # intel scans; riskguard enforces AFTER the cycle opens anything; predict resolves
    # before it opens; the dashboard render is the terminal artifact.
    seq = ["autosettle.js", "blend.py", "intel.js", "riskguard.js", "predict.js", "dashboard.py"]
    positions = [HEARTBEAT.index(s) for s in seq]
    assert positions == sorted(positions), f"heartbeat steps out of order: {seq}"


def test_safety_guards_are_wired():
    assert "PAUSE" in HEARTBEAT  # kill switch
    assert "flock" in HEARTBEAT  # never overlap two heartbeats
    # the LLM runs unattended with bypassPermissions, so every fund-moving tool is denied
    assert "bypassPermissions" in HEARTBEAT
    assert "--disallowedTools" in HEARTBEAT


# ── cadence brain (model_select.js) ──────────────────────────────────────────


def _seed_status(home: Path, positions: list[dict]) -> None:
    # status_cache.json with a far-future ts so `hl_perp status --cache` serves it
    # without ever signing in or hitting HL (hermetic).
    (home / "status_cache.json").write_text(
        json.dumps({"ts": 10_000_000_000_000, "data": {"ok": True, "positions": positions}}),
        encoding="utf-8",
    )


def _model_select(home: Path, arg: str) -> str:
    out = subprocess.run(
        ["node", str(SCRIPTS / "model_select.js"), arg],
        capture_output=True,
        text=True,
        timeout=30,
        env={"GCLAW_HOME": str(home), "PATH": _PATH},
    )
    return out.stdout.strip()


def test_cadence_idle_when_flat_and_quiet(metabolism_fixture, gclaw_home):
    metabolism_fixture()
    _seed_status(gclaw_home, [])  # no positions
    (gclaw_home / "intel.json").write_text(json.dumps({"intel": {}}), encoding="utf-8")
    assert _model_select(gclaw_home, "active") == "idle"
    assert _model_select(gclaw_home, "model") == "sonnet"


def test_cadence_active_with_open_position(metabolism_fixture, gclaw_home):
    metabolism_fixture()
    _seed_status(gclaw_home, [{"coin": "BTC", "size": 0.01, "unrealizedPnl": -0.5}])
    (gclaw_home / "intel.json").write_text(json.dumps({"intel": {}}), encoding="utf-8")
    assert _model_select(gclaw_home, "active") == "active"
    assert _model_select(gclaw_home, "model") == "opus"


def test_cadence_active_on_live_setup(metabolism_fixture, gclaw_home):
    metabolism_fixture()
    _seed_status(gclaw_home, [])  # flat …
    # … but a real, actionable setup (oversold + tradeable) is present → escalate.
    (gclaw_home / "intel.json").write_text(
        json.dumps(
            {
                "intel": {
                    "SOL": {
                        "tradeable": True,
                        "rsi": 22,
                        "bb_z": -2.6,
                        "funding_z": 0.1,
                        "ema_stack": 0,
                        "ema_slope_pct": 0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert _model_select(gclaw_home, "active") == "active"


def test_explicit_model_override_wins(metabolism_fixture, gclaw_home):
    metabolism_fixture()
    _seed_status(gclaw_home, [])
    (gclaw_home / "intel.json").write_text(json.dumps({"intel": {}}), encoding="utf-8")
    out = subprocess.run(
        ["node", str(SCRIPTS / "model_select.js"), "model"],
        capture_output=True,
        text=True,
        timeout=30,
        env={"GCLAW_HOME": str(gclaw_home), "PATH": _PATH, "GCLAW_MODEL": "opus"},
    )
    assert out.stdout.strip() == "opus"  # manual override beats the idle default


def test_discover_degrades_cleanly_offline(gclaw_home, metabolism_fixture):
    # Event-sourced discovery replays the registry's URI events. Point it at a dead RPC
    # so it can't touch the network — it must fail closed (ok:false, no crash, no garbage
    # peers), never throw. (The happy path is covered by the live family graph.)
    metabolism_fixture()
    (gclaw_home / "peers.json").write_text(json.dumps({"ids": [55671]}), encoding="utf-8")
    out = subprocess.run(
        ["node", str(SCRIPTS / "peers.js"), "--discover"],
        capture_output=True,
        text=True,
        timeout=30,
        env={"GCLAW_HOME": str(gclaw_home), "PATH": _PATH, "BASE_RPC": "http://127.0.0.1:1"},
    )
    res = json.loads(out.stdout.strip())
    assert res["ok"] is False  # dead RPC → degrades, doesn't throw
    # the known peer is untouched — a failed discovery never corrupts the roster
    assert json.loads((gclaw_home / "peers.json").read_text())["ids"] == [55671]


def test_heartbeat_runs_periodic_discovery(gclaw_home):
    # The loop must actually invoke discovery (throttled), or newcomers never get
    # folded into the peer graph the leaderboard crawls.
    assert "--discover" in HEARTBEAT
    assert HEARTBEAT.index("--discover") < HEARTBEAT.index("dashboard.py")  # before the beacon


def test_status_cache_keeps_cadence_hermetic(gclaw_home):
    # Guard: the seeded cache is what makes these tests offline — prove --cache reads it.
    _seed_status(gclaw_home, [{"coin": "ETH", "size": 1}])
    out = subprocess.run(
        ["node", str(SCRIPTS / "hl_perp.js"), "status", "--cache"],
        capture_output=True,
        text=True,
        timeout=30,
        env={"GCLAW_HOME": str(gclaw_home), "PATH": _PATH},
    )
    data = json.loads(out.stdout.strip().splitlines()[-1])
    assert len(data["positions"]) == 1
    assert time.time() > 0  # (touch time import; the far-future ts keeps it fresh)
