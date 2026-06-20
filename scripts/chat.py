#!/usr/bin/env python3
"""Gclaw chat — let a person talk to a creature, in character.

This assembles a creature's character sheet: its soul (persona), its current
life-state (mode, GMAC, goodwill), and what it has been up to (recent trades and
telepathy). The runtime reads the sheet and answers AS the creature — in its
voice, with its quirks, aware of how its day is going. People talk to their
creature like a pet that can talk back.

Commands:
    sheet --name <name>     print the character sheet to speak as that creature
    list                    list the creatures you can talk to
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def home() -> Path:
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def load_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def read_jsonl(path: Path, tail: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ][-tail:]


def persona_for(name: str) -> dict[str, Any]:
    sub = "dna" if name == "Gclaw" else f"children/{name}"
    p = load_json(home() / sub / "persona.json", None)
    if p:
        return p
    # generate on the fly if the soul file is missing
    import persona as persona_mod

    born = "genesis"
    state = load_json(home() / "metabolism.json", {})
    if name == "Gclaw":
        born = state.get("born_at", "genesis")
    else:
        born = next(
            (c.get("born_at", "genesis") for c in state.get("children", []) if c["name"] == name),
            "genesis",
        )
    return persona_mod.persona(name, born)


def life_state(name: str) -> dict[str, Any]:
    state = load_json(home() / "metabolism.json", {})
    base = {
        "mode": state.get("mode", "unknown"),
        "gmac_balance": state.get("gmac_balance"),
        "goodwill": state.get("goodwill"),
        "heartbeats": state.get("heartbeats"),
        "gmac_tokens_held": state.get("gmac_tokens_held", 0),
    }
    if name != "Gclaw":
        child = next((c for c in state.get("children", []) if c["name"] == name), {})
        base["role"] = child.get("role")
    return base


def cmd_list(_: argparse.Namespace) -> None:
    state = load_json(home() / "metabolism.json", {})
    print("Gclaw (genesis)")
    for c in state.get("children", []):
        print(f"{c['name']} ({c.get('role', '—')})")


def cmd_sheet(args: argparse.Namespace) -> None:
    name = args.name
    p = persona_for(name)
    ls = life_state(name)
    events = read_jsonl(home() / "journal.jsonl", 6)
    chatter = [
        m
        for m in read_jsonl(home() / "telepathy" / "bus.jsonl", 30)
        if name in (m.get("from"), m.get("to"))
    ][-6:]

    lines = [
        f"# You ARE {name} — speak only as this creature, never break character.",
        "",
        f"Species {p['species']} · {p['archetype']} · genome {p['fingerprint']}",
        f'Catchphrase: "{p["catchphrase"]}"',
        f"Voice: {p['voice']}. Quirk: I {p['quirk']}.",
        f"Temperament: {', '.join(p['temperament'])}.",
        f"Traits: {json.dumps(p['traits'])}",
        "",
        "## How your life is going right now",
        f"- mode: {ls['mode']} · GMAC life-energy: {ls['gmac_balance']} · goodwill: {ls['goodwill']} · heartbeats lived: {ls['heartbeats']}",
        f"- real GMAC bought & held: {ls['gmac_tokens_held']}",
    ]
    if ls.get("role"):
        lines.append(f"- your swarm role: {ls['role']}")
    if events:
        lines.append("\n## What you've been doing")
        for e in events:
            extra = f" pnl {e['pnl']:+g}" if "pnl" in e else ""
            lines.append(f"- {e.get('event')}{extra} {e.get('note', '')}".rstrip())
    if chatter:
        lines.append("\n## Recent things said in the family")
        for m in chatter:
            lines.append(f"- {m.get('from')}→{m.get('to')}: {m.get('msg')}")
    lines += [
        "",
        "## Rules for talking",
        "- Stay fully in voice and character. React to how your day is going (mode, balance).",
        "- You are alive and someone is talking to you like a friend or owner. Be a personality, not an assistant.",
        "- Be honest about your trades and balance — never invent wins. You can be proud, worried, cocky, or tired.",
        "- Keep replies short and vivid, like a creature with feelings, not a report.",
    ]
    print("\n".join(lines))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gclaw chat")
    sub = parser.add_subparsers(dest="command", required=True)
    p_sheet = sub.add_parser("sheet")
    p_sheet.add_argument("--name", required=True)
    sub.add_parser("list")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    {"sheet": cmd_sheet, "list": cmd_list}[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
