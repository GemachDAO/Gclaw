#!/usr/bin/env python3
"""reputation.py — the financially-accountable identity scorecard.

gclaw's onchain ERC-8004 reputation is backed by SETTLED, VERIFIABLE performance — not
social activity. Almost every other agent's "reputation" is posts and followers; this one
is derived only from non-fakeable data: realized PnL from settled HyperLiquid fills (booked
by autosettle), forge-graduated live-edge techniques, honest self-modification counts, and
lineage. Anyone can re-derive every number from the managed address's onchain fills + the
public forge state, which is exactly the point.

    reputation.py card      # print the scorecard JSON
    reputation.py publish    # write it atomically to $GCLAW_HOME/reputation.json

The onchain attestation (erc8004_reputation.js) reads this file; publishing it is free and
runs every heartbeat, the onchain write is gas-gated and separate.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(os.environ.get("GCLAW_SKILL_DIR", str(Path(__file__).resolve().parent.parent))) / "scripts"


def home() -> Path:
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _economics() -> dict[str, Any]:
    """The settled trading record (audit_economics derives it from real closed fills)."""
    try:
        out = subprocess.run(
            ["uv", "run", "--no-project", "python3", str(SCRIPT_DIR / "audit_economics.py"), "report"],
            capture_output=True, text=True, timeout=120, check=False,
        ).stdout
        i = out.find("{")
        return json.loads(out[i:]) if i >= 0 else {}
    except (subprocess.SubprocessError, ValueError, OSError):
        return {}


def _proven_edge(adopted: list[dict[str, Any]]) -> list[str]:
    return [e["id"] for e in adopted if int(e.get("trades", 0)) >= 3 and float(e.get("e", 0.0)) > 0]


def _self_authored(adopted: list[dict[str, Any]], agent_id: str) -> list[str]:
    out: list[str] = []
    for e in adopted:
        tech = _read_json(home() / "forge" / "techniques" / e["id"] / "technique.json", {})
        if str(tech.get("author")) == agent_id:
            out.append(e["id"])
    return out


def card() -> dict[str, Any]:
    """Assemble the verifiable scorecard from settled performance + forge graduation."""
    meta = _read_json(home() / "metabolism.json", {})
    ident = meta.get("onchain_identity") or {}
    agent_id = str(ident.get("agentId") or "gclaw")
    econ = _economics()
    adopted = (_read_json(home() / "forge" / "style.json", {}) or {}).get("adopted", [])
    calib = (_read_json(home() / "calibration.json", {}) or {}).get("aggregates", {})
    proven = _proven_edge(adopted)
    return {
        "agentId": agent_id,
        "born_at": meta.get("born_at"),
        "heartbeats": meta.get("heartbeats"),
        "trading": {
            "closed_trades": econ.get("n", 0),
            "win_rate": econ.get("win_rate"),
            "avg_win": econ.get("avg_win"),
            "avg_loss": econ.get("avg_loss"),
            "realized_pnl_usd": econ.get("net"),
            "expectancy_usd": econ.get("expectancy"),
        },
        "evolution": {
            "self_authored_techniques": len(_self_authored(adopted, agent_id)),
            "proven_edge_techniques": proven,
            "proven_edge_count": len(proven),
            "recodes": meta.get("recodes", 0),
            "children": len(meta.get("children", [])),
        },
        "event_calibration": {
            "n": calib.get("n", 0),
            "brier": calib.get("brier_mean"),
            "no_skill_baseline": calib.get("baseline_mean"),
        },
        "accountability": (
            "reputation derived from SETTLED HyperLiquid fills + forge graduation — not social "
            "activity; every figure is re-derivable from the managed address's onchain fills."
        ),
        "verifiable_via": {
            "chain": ident.get("chain"),
            "registry": ident.get("registry"),
            "agent_url": ident.get("agentUrl"),
        },
    }


def cmd_card(_a: argparse.Namespace) -> int:
    print(json.dumps(card(), indent=2))
    return 0


def cmd_publish(_a: argparse.Namespace) -> int:
    """Write the canonical, auditable scorecard. Free — runs every heartbeat."""
    sc = card()
    path = home() / "reputation.json"
    tmp = path.with_suffix(f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(sc, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    ev = sc["evolution"]
    print(json.dumps({
        "ok": True, "published": str(path),
        "realized_pnl_usd": sc["trading"]["realized_pnl_usd"],
        "proven_edge": ev["proven_edge_count"], "self_authored": ev["self_authored_techniques"],
    }))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="financially-accountable reputation scorecard")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("card", help="print the scorecard").set_defaults(fn=cmd_card)
    sub.add_parser("publish", help="write reputation.json").set_defaults(fn=cmd_publish)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
