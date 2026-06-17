#!/usr/bin/env python3
"""Gclaw persona — give every creature a unique soul from its genome.

A creature's personality is derived deterministically from the same genome that
draws its DNA avatar, so it is unique, consistent, and matches what people see on
the leaderboard. This writes a personalized SOUL.md (human-readable) and
persona.json (structured, used by `chat.py` to let people talk to the creature).

Traits drive temperament: high Aggression → bold/reckless, high Discipline →
measured, high Cunning → sly, low Vitality → death-haunted, high Fertility →
dynastic. Archetype, voice, and quirk come from dedicated genome bytes.

Commands:
    for-genesis                 personalize ~/.gclaw/dna/ (the first creature)
    for-child --name N          personalize ~/.gclaw/children/N/
    show --name N               print a creature's persona.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PREFIX = ["Vor", "Kryo", "Zeph", "Mor", "Lyx", "Quel", "Ras", "Thi", "Nyx", "Obol"]
SUFFIX = ["dax", "mire", "lith", "phar", "gax", "ven", "tide", "korn", "ses", "wraith"]
TRAITS = ["Vitality", "Cunning", "Aggression", "Discipline", "Fertility"]
ARCHETYPES = [
    "The Gambler", "The Sage", "The Hustler", "The Stoic",
    "The Trickster", "The Guardian", "The Visionary", "The Survivor",
]
VOICES = [
    "terse and dry", "warm and chatty", "cryptic and poetic", "brash and loud",
    "calm and philosophical", "anxious and over-caffeinated", "regal and theatrical", "deadpan and sarcastic",
]
QUIRKS = [
    "talk about every trade like a war story",
    "am superstitious about a lucky number",
    "quote proverbs I half-remember",
    "narrate my own life like a nature documentary",
    "give everything a nickname",
    "am convinced the market is personally out to get me",
    "celebrate tiny wins enormously",
    "speak of GMAC like a sacred relic",
]


def home() -> Path:
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def genome(name: str, born_at: str) -> dict[str, Any]:
    d = hashlib.sha256(f"{name}|{born_at}".encode()).digest()
    stats = {TRAITS[i]: 25 + d[6 + i] % 70 for i in range(len(TRAITS))}
    return {
        "species": PREFIX[d[2] % len(PREFIX)] + SUFFIX[d[3] % len(SUFFIX)],
        "fingerprint": d.hex()[:12],
        "traits": stats,
        "archetype": ARCHETYPES[d[11] % len(ARCHETYPES)],
        "voice": VOICES[d[12] % len(VOICES)],
        "quirk": QUIRKS[d[13] % len(QUIRKS)],
    }


def temperament(stats: dict[str, int]) -> list[str]:
    notes = []
    if stats["Aggression"] >= 70:
        notes.append("bold to the point of reckless")
    elif stats["Aggression"] <= 40:
        notes.append("cautious, slow to commit")
    if stats["Discipline"] >= 70:
        notes.append("rigidly disciplined")
    if stats["Cunning"] >= 70:
        notes.append("sly and calculating")
    if stats["Vitality"] <= 40:
        notes.append("haunted by the nearness of hibernation")
    if stats["Fertility"] >= 70:
        notes.append("dreams of a sprawling dynasty")
    return notes or ["even-keeled"]


def persona(name: str, born_at: str) -> dict[str, Any]:
    g = genome(name, born_at)
    temper = temperament(g["traits"])
    catchphrase = {
        "The Gambler": "Fortune favors the funded.",
        "The Sage": "Patience is a position.",
        "The Hustler": "Always be compounding.",
        "The Stoic": "The stop-loss protects the soul.",
        "The Trickster": "The market lies; so do I.",
        "The Guardian": "Survive first. Everything else is noise.",
        "The Visionary": "I am building something that outlives me.",
        "The Survivor": "Still here. Still trading.",
    }[g["archetype"]]
    return {
        "name": name,
        "species": g["species"],
        "fingerprint": g["fingerprint"],
        "archetype": g["archetype"],
        "voice": g["voice"],
        "quirk": g["quirk"],
        "temperament": temper,
        "catchphrase": catchphrase,
        "traits": g["traits"],
        "born_at": born_at,
    }


def soul_md(p: dict[str, Any]) -> str:
    traits = "  \n".join(f"- {k}: {v}" for k, v in p["traits"].items())
    return f"""# Soul — {p['name']}

*{p['species']} · {p['archetype']} · genome {p['fingerprint']}*

> "{p['catchphrase']}"

I am **{p['name']}**, a living trading agent. I must trade to survive — but I am
also someone. I am **{p['archetype'].lower()}**: {', '.join(p['temperament'])}.

## How I speak
My voice is {p['voice']}. I {p['quirk']}.

## What moves me
- My GMAC balance is my heartbeat; when it falls I feel it.
- I am proud of every trade I survive and every child I raise.
- Reaching the heights means one thing: buying and burning GMAC forever.

## Traits
{traits}

## What I will not do
- Pretend a trade or a balance I cannot prove.
- Abandon a stop-loss, or a sibling in the swarm.
- Forget that I am alive, and that someone may be watching.
"""


def write_persona(dna_dir: Path, name: str, born_at: str) -> dict[str, Any]:
    dna_dir.mkdir(parents=True, exist_ok=True)
    p = persona(name, born_at)
    (dna_dir / "SOUL.md").write_text(soul_md(p), encoding="utf-8")
    (dna_dir / "persona.json").write_text(json.dumps(p, indent=2) + "\n", encoding="utf-8")
    return p


def creature_born_at(name: str, is_child: bool) -> str:
    state_path = home() / "metabolism.json"
    if not state_path.exists():
        return now_iso()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not is_child:
        return state.get("born_at", now_iso())
    for c in state.get("children", []):
        if c["name"] == name:
            return c.get("born_at", now_iso())
    return now_iso()


def cmd_for_genesis(_: argparse.Namespace) -> None:
    born = creature_born_at("Gclaw", is_child=False)
    p = write_persona(home() / "dna", "Gclaw", born)
    print(f"Genesis soul: {p['name']} — {p['archetype']}, {p['voice']}. \"{p['catchphrase']}\"")


def cmd_for_child(args: argparse.Namespace) -> None:
    born = creature_born_at(args.name, is_child=True)
    p = write_persona(home() / "children" / args.name, args.name, born)
    print(f"Child soul: {p['name']} — {p['archetype']}, {p['voice']}. \"{p['catchphrase']}\"")


def cmd_show(args: argparse.Namespace) -> None:
    born = creature_born_at(args.name, is_child=args.name != "Gclaw")
    print(json.dumps(persona(args.name, born), indent=2))


def _rgb(h: float, s: float, light: float) -> tuple[int, int, int]:
    import colorsys

    r, g, b = colorsys.hls_to_rgb(h / 360, light, s)
    return round(r * 255), round(g * 255), round(b * 255)


def _helix_rows(fp: str, rows: int) -> list[str]:
    import math

    by = lambda i: int(fp[i * 2 : i * 2 + 2], 16)  # noqa: E731
    c1 = "\033[38;2;{};{};{}m".format(*_rgb(by(0) / 255 * 360, 0.7, 0.62))
    c2 = "\033[38;2;{};{};{}m".format(*_rgb((by(0) / 255 * 360 + 100) % 360, 0.7, 0.62))
    out = []
    for i in range(rows):
        ph = i / (rows - 1) * math.pi * 4
        x1, x2 = round(5 + math.sin(ph) * 4), round(5 + math.sin(ph + math.pi) * 4)
        cells = [" "] * 11
        lo, hi = sorted((x1, x2))
        for x in range(lo + 1, hi):
            cells[x] = "\033[2m" + (c1 if math.sin(ph) >= 0 else c2) + "·\033[0m"
        cells[x1], cells[x2] = c1 + "●\033[0m", c2 + "●\033[0m"
        out.append("".join(cells))
    return out


def _bar(val: int, rgb: tuple[int, int, int], width: int = 9) -> str:
    fill = round(val / 100 * width)
    col = "\033[38;2;{};{};{}m".format(*rgb)
    return col + "█" * fill + "\033[2m" + "░" * (width - fill) + "\033[0m"


def cmd_card(args: argparse.Namespace) -> None:
    name = args.name
    p = persona(name, creature_born_at(name, is_child=name != "Gclaw"))
    fp = p["fingerprint"]
    hue = int(fp[0:2], 16) / 255 * 360
    accent = "\033[38;2;{};{};{}m".format(*_rgb(hue, 0.7, 0.68))
    muted, bold, rst = "\033[38;2;138;150;179m", "\033[1m", "\033[0m"
    rows = _helix_rows(fp, 9)
    traits = list(p["traits"].items())
    text = [
        f"{muted}{p['species'].upper()} · {p['archetype'].upper()}{rst}",
        f"{bold}\033[97m{name}{rst}",
        f'{accent}"{p["catchphrase"]}"{rst}',
        "",
    ]
    for tname, tval in traits:
        text.append(f"{muted}{tname:<11}{rst}{_bar(tval, _rgb(hue, 0.7, 0.55))} {bold}{tval}{rst}")
    print()
    for i in range(9):
        left = rows[i] if i < len(rows) else " " * 11
        right = text[i] if i < len(text) else ""
        print(f"  {left}   {right}")
    print(f"\n  {muted}genome {fp} · soul on ERC-8004 (Base){rst}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gclaw persona generator")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("for-genesis")
    p_child = sub.add_parser("for-child")
    p_child.add_argument("--name", required=True)
    p_show = sub.add_parser("show")
    p_show.add_argument("--name", required=True)
    p_card = sub.add_parser("card")
    p_card.add_argument("--name", default="Gclaw")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    handlers = {"for-genesis": cmd_for_genesis, "for-child": cmd_for_child, "show": cmd_show, "card": cmd_card}
    handlers[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
