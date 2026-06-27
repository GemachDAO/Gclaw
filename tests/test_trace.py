"""trace.py appends a structured cycle record and never raises on partial state."""

from __future__ import annotations

import json

import cycle_trace


def test_record_appends_one_line_and_is_parseable(gclaw_home):
    (gclaw_home / "metabolism.json").write_text(
        json.dumps({"heartbeats": 5, "mode": "thrive", "gmac_balance": 700, "goodwill": 11})
    )
    (gclaw_home / "positions.json").write_text(
        json.dumps(
            {
                "ok": True,
                "positionsOk": True,
                "equity": 192.17,
                "buyingPower": 192.17,
                "positions": [],
                "openOrders": [],
            }
        )
    )
    (gclaw_home / "breaker.json").write_text(
        json.dumps({"tripped": False, "drawdown_pct": 7.9, "hwm": 208.66})
    )

    rec = cycle_trace.record(model="opus", active="active", rc="0")
    assert rec["mode"] == "thrive" and rec["equity"] == 192.17 and rec["account_ok"] is True
    assert rec["open_positions"] == 0 and rec["rc"] == "0"

    lines = (gclaw_home / "cycles.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["heartbeat"] == 5


def test_record_survives_missing_state(gclaw_home):
    # a blind cycle still gets a record — fields are None, but it never raises.
    rec = cycle_trace.record(model="sonnet", active="idle", rc="skipped")
    assert rec["mode"] is None and rec["account_ok"] is False and rec["rc"] == "skipped"
    assert (gclaw_home / "cycles.jsonl").exists()
