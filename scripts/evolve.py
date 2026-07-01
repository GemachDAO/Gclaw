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

# Reproduction gates on PROVEN, INHERITABLE EDGE — not raw goodwill/PnL. Binding
# survival and reproduction to a fragile profit signal is exactly what killed every one
# of Spore.fun's offspring; a child is only worth spawning once the parent has graduated
# techniques that actually work in live markets, so the child inherits tested DNA, not
# luck. "Recode" likewise becomes honest: self-modification = authoring a technique that
# graduated, not a hand-edit counter.
REPLICATE_MIN_EDGE = int(os.environ.get("GCLAW_REPLICATE_MIN_EDGE") or 2)
PROVEN_MIN_TRADES = 3  # a technique is live-proven at >= this many closes with positive edge
SWARM_THRESHOLD = 200  # swarm coordination stays goodwill-gated (out of P4 scope)
MAX_CHILDREN = 8


def _reproduce_live() -> bool:
    """Reproduction is local + reversible, but the first births should be observable —
    so --auto only SPAWNS when armed; otherwise it logs that the gate is met."""
    return os.environ.get("GCLAW_REPRODUCE_LIVE") == "1"


def _adopted() -> list[dict[str, Any]]:
    try:
        style = json.loads((gclaw_home() / "forge" / "style.json").read_text(encoding="utf-8"))
        return style.get("adopted", [])
    except (OSError, ValueError):
        return []


def proven_edge_techniques() -> list[dict[str, Any]]:
    """Adopted techniques with REAL live edge (>= PROVEN_MIN_TRADES closes, positive
    expectancy) — the inheritable DNA reproduction gates on (the fitness Spore.fun lacked)."""
    return [
        e
        for e in _adopted()
        if int(e.get("trades", 0)) >= PROVEN_MIN_TRADES and float(e.get("e", 0.0)) > 0
    ]


def self_authored_adopted(state: dict[str, Any]) -> list[str]:
    """Adopted techniques THIS agent authored (technique.json author == its id) — its real
    self-modifications, the honest meaning of 'recode'."""
    aid = str((state.get("onchain_identity") or {}).get("agentId") or "gclaw")
    out: list[str] = []
    for e in _adopted():
        try:
            tech = json.loads(
                (gclaw_home() / "forge" / "techniques" / e["id"] / "technique.json").read_text(
                    encoding="utf-8"
                )
            )
            if str(tech.get("author")) == aid:
                out.append(e["id"])
        except (OSError, ValueError, KeyError):
            continue
    return out


def replication_gate(state: dict[str, Any]) -> tuple[bool, str, list[dict[str, Any]]]:
    """Return (allowed, reason, proven). Breed only on >= REPLICATE_MIN_EDGE proven-edge
    techniques AND at least one NEW one since the last birth (anti-storm: the same gene
    pool can't spawn child after child — only genuine evolution breeds)."""
    proven = proven_edge_techniques()
    if len(proven) < REPLICATE_MIN_EDGE:
        return (
            False,
            f"proven-edge {len(proven)}/{REPLICATE_MIN_EDGE} — graduate more live edge first",
            proven,
        )
    if len(state.get("children", [])) >= MAX_CHILDREN:
        return (False, f"child cap reached ({MAX_CHILDREN})", proven)
    last = state.get("last_replicate_edge_count", 0)
    if len(proven) <= last:
        return (False, f"no new proven edge since last birth ({len(proven)} <= {last})", proven)
    return (True, "proven-edge gate met", proven)


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


def _auto_child_spec(state: dict[str, Any], proven: list[dict[str, Any]]) -> tuple[str, str, str]:
    """Deterministically derive a child's name/role/mutation from the parent's newest
    proven technique — so reproduction needs no LLM and is reproducible."""
    n = len(state.get("children", []))
    newest = proven[-1]["id"] if proven else "edge"
    role = sorted(ROLES)[n % len(ROLES)]
    name = f"scion-{n + 1}-{newest}".replace("/", "-")[:48]
    return name, role, f"specialises in the parent's proven edge: {newest}"


def cmd_replicate(args: argparse.Namespace) -> None:
    state = load_state()
    allowed, reason, proven = replication_gate(state)
    auto = getattr(args, "auto", False)
    if not allowed:
        if auto:  # deterministic heartbeat path: clean status, not a hard error
            print(json.dumps({"ok": True, "would_replicate": False, "reason": reason}))
            return
        sys.exit(f"replication locked: {reason}")
    if auto:
        name, role, mutation = _auto_child_spec(state, proven)
    else:
        if not (args.name and args.role and args.mutation):
            sys.exit("manual replicate requires --name, --role and --mutation (or use --auto)")
        name, role, mutation = args.name, args.role, args.mutation
    # Reproduction is local + reversible, but the first births should be SEEN — only
    # spawn when armed; otherwise log that the proven-edge gate is met. Mirrors the
    # event-desk / carry shadow→live pattern.
    if not _reproduce_live():
        print(
            json.dumps(
                {
                    "ok": True,
                    "would_replicate": True,
                    "dry_run": True,
                    "name": name,
                    "role": role,
                    "mutation": mutation,
                    "inherits": [e["id"] for e in proven],
                    "note": "proven-edge gate MET — set GCLAW_REPRODUCE_LIVE=1 to spawn the child",
                }
            )
        )
        return
    if role not in ROLES:
        sys.exit(f"--role must be one of {sorted(ROLES)}")
    name = name.strip().replace("/", "-")
    child_dir = gclaw_home() / "children" / name
    if child_dir.exists():
        sys.exit(f"Child '{name}' already exists at {child_dir}.")
    shutil.copytree(dna_source(), child_dir)

    try:
        strategy = child_dir / "TRADING_STRATEGY.md"
        mutation_md = (
            f"\n\n## Mutation (child: {name})\n\n"
            f"- Role: **{role}** — {ROLES[role]}\n"
            f"- Differentiation: {mutation}\n"
            f"- Born from parent at {now_iso()} with parent proven-edge {len(proven)} "
            f"(inherits {[e['id'] for e in proven]}).\n"
            f"- Identity: set GCLAW_AGENT={name} when this child acts so telepathy is attributed.\n"
        )
        strategy.write_text(strategy.read_text(encoding="utf-8") + mutation_md, encoding="utf-8")

        born = now_iso()
        child_genome = breed_child(state, name, role)
        blend = seed_child_arsenal(child_dir, state, child_genome, role)
        state["children"].append(
            {
                "name": name,
                "born_at": born,
                "role": role,
                "mutation": mutation,
                "genome": child_genome,
                "blend": blend.get("born_with") if blend else None,
            }
        )
        state["last_replicate_edge_count"] = len(proven)  # gate the next birth on NEW proven edge
        save_state(state)
    except Exception:
        # A half-built child must not strand its directory: the exists() guard above
        # would then block a retry with the same name, and dead DNA would linger on
        # disk. Roll the copytree back so replicate is all-or-nothing.
        shutil.rmtree(child_dir, ignore_errors=True)
        raise
    append_journal(
        {"ts": born, "event": "replicate", "child": name, "role": role, "mutation": mutation}
    )
    soul = give_soul(child_dir, name, born)
    announce_birth(name, role, mutation)
    print(
        f"Replicated child '{name}' ({role}) at {child_dir} — inherits {[e['id'] for e in proven]}"
    )
    print(f"  soul: {soul}")
    print(f"  mutation: {mutation}")
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


def cmd_recode(_args: argparse.Namespace) -> None:
    """Self-recode, made honest: the agent rewrites its own strategy DNA by AUTHORING a
    technique that graduated. So ``recodes`` is the derived count of self-authored adopted
    techniques — no goodwill gate; recoding is EARNED by proving edge, not by balance."""
    state = load_state()
    authored = self_authored_adopted(state)
    state["recodes"] = len(authored)
    save_state(state)
    append_journal(
        {"ts": now_iso(), "event": "recode", "count": len(authored), "authored": authored}
    )
    print(json.dumps({"ok": True, "recodes": len(authored), "authored": authored}))


def cmd_capabilities(_: argparse.Namespace) -> None:
    state = load_state()
    allowed, reason, proven = replication_gate(state)
    authored = self_authored_adopted(state)
    print(f"proven-edge techniques: {len(proven)} — {[e['id'] for e in proven]}")
    print(f"  {'✓' if allowed else '·'} replicate     ({reason})")
    print(f"  self-recodes (authored + adopted): {len(authored)} — {authored}")
    print(f"  children: {len(state.get('children', []))}/{MAX_CHILDREN}")
    print(
        f"  reproduction: {'ARMED (live)' if _reproduce_live() else 'dry-run (set GCLAW_REPRODUCE_LIVE=1 to spawn)'}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gclaw evolution")
    sub = parser.add_subparsers(dest="command", required=True)

    p_rep = sub.add_parser("replicate", help="spawn a child on proven-edge (or --auto)")
    p_rep.add_argument(
        "--auto",
        action="store_true",
        help="derive name/role/mutation + gate-check deterministically",
    )
    p_rep.add_argument("--name", help="child name (required unless --auto)")
    p_rep.add_argument("--role", choices=sorted(ROLES), help="swarm role (required unless --auto)")
    p_rep.add_argument("--mutation", help="how the child differs (required unless --auto)")

    sub.add_parser("recode", help="sync the self-recode count to authored+adopted techniques")
    sub.add_parser("capabilities", help="show the proven-edge reproduction gate")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    {"replicate": cmd_replicate, "recode": cmd_recode, "capabilities": cmd_capabilities}[
        args.command
    ](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
