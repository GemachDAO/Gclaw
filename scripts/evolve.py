#!/usr/bin/env python3
"""Gclaw evolution — goodwill-gated replication and self-recoding.

Reproduction and self-modification are file operations, not magic:

  replicate  copies the agent's DNA into $GCLAW_HOME/children/<name>/ with a
             mutated TRADING_STRATEGY.md, then records the child in state.
  recode     records a self-recode event after the caller has edited a DNA
             file, bumping the recodes counter (the gate for honest auditing).

Thresholds mirror references/evolution.md and are enforced here so the model
cannot evolve below the goodwill it has actually earned.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPLICATE_THRESHOLD = 50
RECODE_THRESHOLD = 100
SWARM_THRESHOLD = 200
MAX_CHILDREN = 8


def gclaw_home() -> Path:
    import os

    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state() -> dict[str, Any]:
    path = gclaw_home() / "metabolism.json"
    if not path.exists():
        sys.exit(f"No metabolism state at {path}. Run metabolism.py init first.")
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    path = gclaw_home() / "metabolism.json"
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_journal(entry: dict[str, Any]) -> None:
    path = gclaw_home() / "journal.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def dna_source() -> Path:
    """Locate the live DNA — the agent's own workspace copy under GCLAW_HOME."""
    home_dna = gclaw_home() / "dna"
    if not home_dna.exists():
        sys.exit(
            f"No DNA at {home_dna}. The skill should have seeded it on first run "
            "(copy skill dna/ -> $GCLAW_HOME/dna/)."
        )
    return home_dna


def cmd_replicate(args: argparse.Namespace) -> None:
    state = load_state()
    if state["goodwill"] < REPLICATE_THRESHOLD:
        sys.exit(
            f"Goodwill {state['goodwill']} < {REPLICATE_THRESHOLD}: replication locked."
        )
    if len(state["children"]) >= MAX_CHILDREN:
        sys.exit(f"Child cap reached ({MAX_CHILDREN}). Cannot replicate further.")

    name = args.name.strip().replace("/", "-")
    child_dir = gclaw_home() / "children" / name
    if child_dir.exists():
        sys.exit(f"Child '{name}' already exists at {child_dir}.")
    shutil.copytree(dna_source(), child_dir)

    strategy = child_dir / "TRADING_STRATEGY.md"
    mutation = (
        f"\n\n## Mutation (child: {name})\n\n"
        f"- Differentiation: {args.mutation}\n"
        f"- Born from parent at {now_iso()} with parent goodwill {state['goodwill']}.\n"
    )
    strategy.write_text(strategy.read_text(encoding="utf-8") + mutation, encoding="utf-8")

    state["children"].append(
        {"name": name, "born_at": now_iso(), "mutation": args.mutation}
    )
    save_state(state)
    append_journal(
        {"ts": now_iso(), "event": "replicate", "child": name, "mutation": args.mutation}
    )
    print(f"Replicated child '{name}' at {child_dir}")
    print(f"  mutation: {args.mutation}")
    print(f"  children: {len(state['children'])}/{MAX_CHILDREN}")


def cmd_recode(args: argparse.Namespace) -> None:
    state = load_state()
    if state["goodwill"] < RECODE_THRESHOLD:
        sys.exit(
            f"Goodwill {state['goodwill']} < {RECODE_THRESHOLD}: self-recoding locked."
        )
    state["recodes"] += 1
    save_state(state)
    append_journal(
        {"ts": now_iso(), "event": "recode", "target": args.target, "summary": args.summary}
    )
    print(f"Recorded recode #{state['recodes']} of {args.target}: {args.summary}")


def cmd_capabilities(_: argparse.Namespace) -> None:
    state = load_state()
    goodwill = state["goodwill"]
    rows = [
        ("replicate", REPLICATE_THRESHOLD),
        ("self-recode", RECODE_THRESHOLD),
        ("swarm", SWARM_THRESHOLD),
    ]
    print(f"goodwill: {goodwill}")
    for label, threshold in rows:
        mark = "✓" if goodwill >= threshold else "·"
        print(f"  {mark} {label:<12} (>= {threshold})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gclaw evolution")
    sub = parser.add_subparsers(dest="command", required=True)

    p_rep = sub.add_parser("replicate", help="spawn a mutated child")
    p_rep.add_argument("--name", required=True)
    p_rep.add_argument("--mutation", required=True, help="how the child differs")

    p_rec = sub.add_parser("recode", help="record a self-recode of a DNA file")
    p_rec.add_argument("--target", required=True, help="DNA file edited")
    p_rec.add_argument("--summary", required=True)

    sub.add_parser("capabilities", help="show goodwill-gated abilities")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    {"replicate": cmd_replicate, "recode": cmd_recode, "capabilities": cmd_capabilities}[
        args.command
    ](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
