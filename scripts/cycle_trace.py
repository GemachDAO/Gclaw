#!/usr/bin/env python3
"""Structured per-cycle trace — append one JSON line of cycle state to cycles.jsonl.

The prose heartbeat.log is for humans; this is the queryable record. One line per
heartbeat captures the deterministic state the cycle ended in (mode, life energy,
equity, open risk, circuit breaker) plus how it ran (model, active/idle, return code),
so a bad cycle can be root-caused — "show every cycle where rc != 0", "plot drawdown
over the last 50 cycles" — instead of grepping prose.

    trace.py record --model opus --active active --rc 0   # append one record
    trace.py summary [--n 20]                              # print the last N records

record() is pure of its inputs + the on-disk state files; it never raises on partial
state (a crash here must not fail the heartbeat), mirroring the briefing's discipline.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def home() -> Path:
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def trace_path() -> Path:
    return home() / "cycles.jsonl"


def _read_json(name: str, default: object) -> Any:
    try:
        return json.loads((home() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def build_record(model: str, active: str, rc: str) -> dict[str, Any]:
    """Assemble one cycle record from the current on-disk state. Never raises."""
    meta = _read_json("metabolism.json", {}) or {}
    acct = _read_json("positions.json", {}) or {}
    breaker = _read_json("breaker.json", {}) or {}
    positions = acct.get("positions") or []
    return {
        "ts": datetime.now(UTC).isoformat(),
        "heartbeat": meta.get("heartbeats"),
        "model": model,
        "active": active,
        "rc": rc,
        "mode": meta.get("mode"),
        "gmac": meta.get("gmac_balance"),
        "goodwill": meta.get("goodwill"),
        "equity": acct.get("equity"),
        "buying_power": acct.get("buyingPower"),
        "open_positions": len(positions),
        "open_orders": len(acct.get("openOrders") or []),
        "account_ok": bool(acct.get("ok")) and acct.get("positionsOk") is not False,
        "breaker_tripped": breaker.get("tripped"),
        "drawdown_pct": breaker.get("drawdown_pct"),
        "hwm": breaker.get("hwm"),
    }


def record(model: str, active: str, rc: str) -> dict[str, Any]:
    """Append one trace record to cycles.jsonl and return it."""
    rec = build_record(model, active, rc)
    path = trace_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(rec) + "\n")
    return rec


def summary(n: int) -> str:
    """Render the last n trace records as compact one-liners (newest last)."""
    try:
        lines = trace_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return "no cycles recorded yet"
    out = []
    for line in lines[-n:]:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        out.append(
            f"#{r.get('heartbeat')} {r.get('ts', '')[:19]} {r.get('mode')} "
            f"rc={r.get('rc')} model={r.get('model')} eq={r.get('equity')} "
            f"pos={r.get('open_positions')} dd={r.get('drawdown_pct')}%"
        )
    return "\n".join(out) or "no cycles recorded yet"


def main() -> int:
    parser = argparse.ArgumentParser(description="Gclaw structured cycle trace.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="append one cycle record")
    rec.add_argument("--model", default="?")
    rec.add_argument("--active", default="?")
    rec.add_argument("--rc", default="?")
    summ = sub.add_parser("summary", help="print the last N records")
    summ.add_argument("--n", type=int, default=20)
    args = parser.parse_args()
    if args.cmd == "record":
        print(json.dumps(record(args.model, args.active, args.rc)))
    else:
        print(summary(args.n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
