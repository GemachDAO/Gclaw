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
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPLICATE_THRESHOLD = 50
RECODE_THRESHOLD = 100
SWARM_THRESHOLD = 200
MAX_CHILDREN = 8

# Swarm roles a child can be born into (mirrors the original Gclaw swarm).
ROLES = {
    "scout": "Scan markets for setups; report promising opportunities via telepathy.",
    "analyst": "Evaluate risk/reward and funding; share analytical reads with the family.",
    "executor": "Execute trades when the family reaches a clear signal; report fills.",
    "leader": "Coordinate the family, weigh signals, and make the final call.",
}


def gclaw_home() -> Path:
    import os

    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def load_state() -> dict[str, Any]:
    path = gclaw_home() / "metabolism.json"
    if not path.exists():
        sys.exit(f"No metabolism state at {path}. Run metabolism.py init first.")
    state = json.loads(path.read_text(encoding="utf-8"))
    state.setdefault("children", [])  # a legacy/hand-edited state may predate this key
    return state


def save_state(state: dict[str, Any]) -> None:
    # Atomic write — metabolism.json holds GMAC/goodwill/treasury and is shared with
    # metabolism.py; a crash mid-write must not corrupt it. temp + os.replace.
    path = gclaw_home() / "metabolism.json"
    tmp = path.with_suffix(f".json.tmp{os.getpid()}")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


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


def announce_birth(name: str, role: str, mutation: str) -> None:
    """Broadcast a child's birth on the telepathy bus (best-effort)."""
    bus_dir = gclaw_home() / "telepathy"
    bus_dir.mkdir(parents=True, exist_ok=True)
    bus_path = bus_dir / "bus.jsonl"
    existing = bus_path.read_text(encoding="utf-8").splitlines() if bus_path.exists() else []
    entry = {
        "id": len([line for line in existing if line.strip()]) + 1,
        "ts": now_iso(),
        "from": "gclaw",
        "to": "broadcast",
        "type": "strategy_update",
        "priority": 1,
        "msg": f"New child {name} born as {role}: {mutation}",
    }
    with bus_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def cmd_replicate(args: argparse.Namespace) -> None:
    state = load_state()
    if state["goodwill"] < REPLICATE_THRESHOLD:
        sys.exit(f"Goodwill {state['goodwill']} < {REPLICATE_THRESHOLD}: replication locked.")
    if len(state["children"]) >= MAX_CHILDREN:
        sys.exit(f"Child cap reached ({MAX_CHILDREN}). Cannot replicate further.")
    # Anti-storm gate: each birth must be backed by goodwill EARNED since the last one,
    # so the same earned goodwill can't spawn child after child on consecutive heartbeats.
    # Deterministic — the "one per threshold crossing" pacing can't be left to the prompt.
    last_gw = state.get("last_replicate_goodwill", 0)
    if last_gw and state["goodwill"] <= last_gw:
        sys.exit(
            f"No new goodwill since the last birth (goodwill {state['goodwill']} <= "
            f"{last_gw}). Earn more before spawning another child."
        )

    if args.role not in ROLES:
        sys.exit(f"--role must be one of {sorted(ROLES)}")
    name = args.name.strip().replace("/", "-")
    child_dir = gclaw_home() / "children" / name
    if child_dir.exists():
        sys.exit(f"Child '{name}' already exists at {child_dir}.")
    shutil.copytree(dna_source(), child_dir)

    try:
        strategy = child_dir / "TRADING_STRATEGY.md"
        mutation = (
            f"\n\n## Mutation (child: {name})\n\n"
            f"- Role: **{args.role}** — {ROLES[args.role]}\n"
            f"- Differentiation: {args.mutation}\n"
            f"- Born from parent at {now_iso()} with parent goodwill {state['goodwill']}.\n"
            f"- Identity: set GCLAW_AGENT={name} when this child acts so telepathy is attributed.\n"
        )
        strategy.write_text(strategy.read_text(encoding="utf-8") + mutation, encoding="utf-8")

        born = now_iso()
        child_genome = breed_child(state, name, args.role)
        blend = seed_child_arsenal(child_dir, state, child_genome, args.role)
        state["children"].append(
            {
                "name": name,
                "born_at": born,
                "role": args.role,
                "mutation": args.mutation,
                "genome": child_genome,
                "blend": blend.get("born_with") if blend else None,
            }
        )
        state["last_replicate_goodwill"] = state[
            "goodwill"
        ]  # gate the next birth on fresh goodwill
        save_state(state)
    except Exception:
        # A half-built child must not strand its directory: the exists() guard above
        # would then block a retry with the same name, and dead DNA would linger on
        # disk. Roll the copytree back so replicate is all-or-nothing.
        shutil.rmtree(child_dir, ignore_errors=True)
        raise
    append_journal(
        {
            "ts": born,
            "event": "replicate",
            "child": name,
            "role": args.role,
            "mutation": args.mutation,
        }
    )
    soul = give_soul(child_dir, name, born)
    announce_birth(name, args.role, args.mutation)
    print(f"Replicated child '{name}' ({args.role}) at {child_dir}")
    print(f"  soul: {soul}")
    print(f"  mutation: {args.mutation}")
    print(f"  children: {len(state['children'])}/{MAX_CHILDREN}")


def breed_child(state: dict[str, Any], name: str, role: str) -> dict[str, Any] | None:
    """Breed the child's genome from the parent's via dashboard.breed — real
    inheritance (resembles the parent, diverges). Best-effort; never blocks a birth."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import dashboard

        parent_g = state.get("genome") or dashboard.genome("Gclaw", state.get("born_at", "genesis"))
        return dashboard.breed(parent_g, name, role, state.get("goodwill", 50))
    except Exception:
        return None


def _family_loadouts(state: dict[str, Any]) -> list[set]:
    """The set of techniques each living family member runs — for the crowding penalty."""
    rosters: list[set] = []
    try:
        parent = json.loads((gclaw_home() / "forge" / "style.json").read_text(encoding="utf-8"))
        rosters.append({e["id"] for e in parent.get("adopted", [])})
    except (OSError, ValueError):
        pass
    for child in state.get("children", []):
        if child.get("blend"):
            rosters.append(set(child["blend"]))
    return rosters


def seed_child_arsenal(
    child_dir: Path, state: dict[str, Any], child_genome: dict[str, Any] | None, role: str
) -> dict[str, Any] | None:
    """Born with an arsenal: inherit the parent's proven winners, tilt by the child's
    bred genome, diversify against the family. Best-effort; never blocks a birth."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import blend

        parent_style = json.loads(
            (gclaw_home() / "forge" / "style.json").read_text(encoding="utf-8")
        )
        traits = (child_genome or {}).get("stats") or {}
        return blend.seed_child(str(child_dir), parent_style, traits, role, _family_loadouts(state))
    except Exception:
        return None


def give_soul(child_dir, name: str, born: str) -> str:
    """Generate the child's unique personality (best-effort; persona.py is a sibling)."""
    try:
        import persona

        p = persona.write_persona(child_dir, name, born)
        return f'{p["archetype"]}, {p["voice"]} — "{p["catchphrase"]}"'
    except Exception as exc:
        return f"(persona unavailable: {exc})"


def cmd_recode(args: argparse.Namespace) -> None:
    state = load_state()
    if state["goodwill"] < RECODE_THRESHOLD:
        sys.exit(f"Goodwill {state['goodwill']} < {RECODE_THRESHOLD}: self-recoding locked.")
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
    p_rep.add_argument("--role", required=True, choices=sorted(ROLES), help="swarm role")
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
