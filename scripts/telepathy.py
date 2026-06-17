#!/usr/bin/env python3
"""Gclaw telepathy — the family message bus.

Parent and child agents coordinate by passing messages through a shared
append-only bus under $GCLAW_HOME/telepathy/bus.jsonl. There is no live runtime;
agents read the bus on their heartbeat. Each agent has an identity (the parent is
``gclaw``; children use their name), set via $GCLAW_AGENT.

Commands:
    send --to <name|broadcast> --type <kind> --msg "..." [--priority 0|1|2]
    inbox [--agent <name>]      messages for me since my last read (advances cursor)
    feed  [--limit N]           recent traffic for the whole family (dashboard view)

Message kinds: trade_signal | market_insight | strategy_update | warning
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

KINDS = {"trade_signal", "market_insight", "strategy_update", "warning"}


def home() -> Path:
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def bus_dir() -> Path:
    return home() / "telepathy"


def bus_path() -> Path:
    return bus_dir() / "bus.jsonl"


def cursor_path(agent: str) -> Path:
    return bus_dir() / f"cursor-{agent}.txt"


def me() -> str:
    return os.environ.get("GCLAW_AGENT", "gclaw")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_bus() -> list[dict[str, Any]]:
    path = bus_path()
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def cmd_send(args: argparse.Namespace) -> None:
    if args.type not in KINDS:
        sys.exit(f"--type must be one of {sorted(KINDS)}")
    bus_dir().mkdir(parents=True, exist_ok=True)
    messages = read_bus()
    entry = {
        "id": len(messages) + 1,
        "ts": now_iso(),
        "from": me(),
        "to": args.to,
        "type": args.type,
        "priority": int(args.priority),
        "msg": args.msg,
    }
    with bus_path().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    print(f"sent #{entry['id']} {me()} → {args.to} [{args.type}]")


def cmd_inbox(args: argparse.Namespace) -> None:
    agent = args.agent or me()
    messages = read_bus()
    cursor = 0
    cpath = cursor_path(agent)
    if cpath.exists():
        cursor = int(cpath.read_text().strip() or "0")
    fresh = [
        m
        for m in messages
        if m["id"] > cursor and m["from"] != agent and m["to"] in (agent, "broadcast")
    ]
    if messages:
        bus_dir().mkdir(parents=True, exist_ok=True)
        cpath.write_text(str(messages[-1]["id"]))
    if not fresh:
        print(f"({agent}) inbox empty")
        return
    for m in sorted(fresh, key=lambda x: (-x["priority"], x["id"])):
        flag = {0: " ", 1: "·", 2: "!"}.get(m["priority"], "·")
        print(f"{flag} #{m['id']} {m['from']} [{m['type']}] {m['msg']}")


def cmd_feed(args: argparse.Namespace) -> None:
    messages = read_bus()[-args.limit :]
    if not messages:
        print("(no telepathy traffic yet)")
        return
    for m in messages:
        print(f"#{m['id']} {m['ts']} {m['from']}→{m['to']} [{m['type']}] {m['msg']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gclaw telepathy bus")
    sub = parser.add_subparsers(dest="command", required=True)
    p_send = sub.add_parser("send", help="broadcast or direct a message")
    p_send.add_argument("--to", required=True, help="agent name or 'broadcast'")
    p_send.add_argument("--type", required=True)
    p_send.add_argument("--msg", required=True)
    p_send.add_argument("--priority", default="1", choices=["0", "1", "2"])
    p_inbox = sub.add_parser("inbox", help="unread messages for me")
    p_inbox.add_argument("--agent")
    p_feed = sub.add_parser("feed", help="recent family traffic")
    p_feed.add_argument("--limit", type=int, default=20)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    {"send": cmd_send, "inbox": cmd_inbox, "feed": cmd_feed}[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
