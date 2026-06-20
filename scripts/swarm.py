#!/usr/bin/env python3
"""Gclaw swarm — leader coordination over the family (goodwill >= 200).

When the family is large enough, the leader stops everyone crowding the same
trade. This reads the children's telepathy signals, aggregates them per asset,
flags crowding/conflicts, computes a simple consensus, and assigns each child a
non-overlapping mandate (broadcast back over the bus). The leader's heartbeat
then acts on the consensus; the deterministic part here keeps it honest.

Commands:
    status              roster + whether swarm is unlocked
    signals [--recent N] aggregate child signals per asset; flag crowding
    consensus           net stance per asset from the signals
    assign              give each child a distinct mandate and broadcast it

Gates: signals/consensus/assign need goodwill >= 200 (SWARM_THRESHOLD).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SWARM_THRESHOLD = 200
ASSETS = ["BTC", "ETH", "SOL", "OUTCOME"]
LONG_WORDS = ("long", "buy", "bid", "bullish", "up", "yes")
SHORT_WORDS = ("short", "sell", "ask", "bearish", "down", "no")


def home() -> Path:
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def load_state() -> dict[str, Any]:
    path = home() / "metabolism.json"
    if not path.exists():
        sys.exit(f"No metabolism state at {path}.")
    return json.loads(path.read_text(encoding="utf-8"))


def read_bus() -> list[dict[str, Any]]:
    path = home() / "telepathy" / "bus.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def require_unlock(state: dict[str, Any]) -> None:
    if state.get("goodwill", 0) < SWARM_THRESHOLD:
        sys.exit(f"Swarm locked: goodwill {state.get('goodwill', 0)} < {SWARM_THRESHOLD}.")


def classify(msg: str) -> tuple[str | None, str | None]:
    """Heuristically extract (asset, side) from a free-text signal."""
    text = msg.lower()
    asset = next(
        (a for a in ASSETS if a.lower() in text or (a == "OUTCOME" and "outcome" in text)), None
    )
    side = None
    if any(w in text for w in LONG_WORDS):
        side = "long"
    if any(w in text for w in SHORT_WORDS):
        side = "short" if side is None else "conflict"
    return asset, side


def child_names(state: dict[str, Any]) -> set[str]:
    return {c["name"] for c in state.get("children", [])}


def aggregate(state: dict[str, Any], recent: int) -> dict[str, Any]:
    kids = child_names(state)
    signals = [
        m
        for m in read_bus()
        if m.get("from") in kids and m.get("type") in ("trade_signal", "market_insight")
    ][-recent:]
    book: dict[str, dict[str, Any]] = {
        a: {"long": 0, "short": 0, "long_voices": set(), "short_voices": set(), "voices": []}
        for a in ASSETS
    }
    for m in signals:
        asset, side = classify(m.get("msg", ""))
        if not asset:
            continue
        weight = 1 + int(m.get("priority", 1))
        if side in ("long", "short"):
            book[asset][side] += weight
            book[asset][f"{side}_voices"].add(m["from"])
            book[asset]["voices"].append(f"{m['from']}:{side}")
        elif side == "conflict":
            book[asset]["voices"].append(f"{m['from']}:conflict")
    # Crowding = >=2 DISTINCT children on one side with none opposing.
    crowding = {
        a: v
        for a, v in book.items()
        if (len(v["long_voices"]) >= 2 and not v["short_voices"])
        or (len(v["short_voices"]) >= 2 and not v["long_voices"])
    }
    for v in book.values():
        v["long_voices"] = sorted(v["long_voices"])
        v["short_voices"] = sorted(v["short_voices"])
    return {"considered": len(signals), "book": book, "crowding": list(crowding)}


def cmd_status(state: dict[str, Any]) -> None:
    unlocked = state.get("goodwill", 0) >= SWARM_THRESHOLD
    print(
        f"goodwill {state.get('goodwill', 0)} — swarm {'UNLOCKED' if unlocked else 'locked (need 200)'}"
    )
    children = state.get("children", [])
    if not children:
        print("  no children yet")
    for c in children:
        print(f"  · {c['name']:<16} role={c.get('role', '—'):<9} {c.get('mutation', '')[:48]}")


def cmd_signals(state: dict[str, Any], args: argparse.Namespace) -> None:
    require_unlock(state)
    agg = aggregate(state, args.recent)
    print(f"signals considered: {agg['considered']}")
    for asset, v in agg["book"].items():
        if v["long"] or v["short"]:
            print(f"  {asset:<8} long={v['long']} short={v['short']}  {', '.join(v['voices'])}")
    if agg["crowding"]:
        print(f"⚠ CROWDING on {', '.join(agg['crowding'])} — leader should diversify, not pile in.")


def cmd_consensus(state: dict[str, Any], args: argparse.Namespace) -> None:
    require_unlock(state)
    agg = aggregate(state, args.recent)
    for asset, v in agg["book"].items():
        net = v["long"] - v["short"]
        if v["long"] or v["short"]:
            stance = "LONG" if net > 0 else "SHORT" if net < 0 else "SPLIT — stand aside"
            print(f"  {asset:<8} net={net:+d} → {stance}")


def cmd_assign(state: dict[str, Any], _: argparse.Namespace) -> None:
    require_unlock(state)
    children = state.get("children", [])
    if not children:
        sys.exit("no children to assign.")
    bus_dir = home() / "telepathy"
    bus_dir.mkdir(parents=True, exist_ok=True)
    bus_path = bus_dir / "bus.jsonl"
    base_id = len(
        [
            line
            for line in (
                bus_path.read_text(encoding="utf-8").splitlines() if bus_path.exists() else []
            )
            if line.strip()
        ]
    )
    lines = []
    for i, child in enumerate(children):
        mandate = ASSETS[i % len(ASSETS)]
        lines.append(
            json.dumps(
                {
                    "id": base_id + i + 1,
                    "ts": now_iso(),
                    "from": "gclaw",
                    "to": child["name"],
                    "type": "strategy_update",
                    "priority": 2,
                    "msg": f"Swarm mandate: focus {mandate}. Do not crowd siblings on other assets.",
                },
                sort_keys=True,
            )
        )
        print(f"  {child['name']:<16} → {mandate}")
    with bus_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"assigned {len(children)} mandates via telepathy.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gclaw swarm coordination")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    for name in ("signals", "consensus"):
        p = sub.add_parser(name)
        p.add_argument("--recent", type=int, default=20)
    sub.add_parser("assign")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    state = load_state()
    handlers = {
        "status": lambda: cmd_status(state),
        "signals": lambda: cmd_signals(state, args),
        "consensus": lambda: cmd_consensus(state, args),
        "assign": lambda: cmd_assign(state, args),
    }
    handlers[args.command]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
