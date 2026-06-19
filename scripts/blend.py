#!/usr/bin/env python3
"""blend.py — install a genome-weighted offensive arsenal as a creature's starting
loadout (the "new zero"). A newborn isn't empty: its traits + role select a weighted
blend of the seed techniques in dna/arsenal/, so families specialise and good blends
compound across generations (Darwin). Born with weapons, grows from there.

    blend.py install [--role scout|analyst|executor|leader]   # seed THIS creature's loadout
    blend.py show                                             # the blend it would install

Trait→technique affinity comes from each technique's `affinity` (in technique.json);
Vitality sets how many weapons (breadth/survivability), Aggression the risk envelope,
Fertility the wildcard explorers. Writes the forge style.json the loadout runs from.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

MIN_TRADES = 12  # a parent technique must clear this sample before it tilts a child's blend

SCRIPT_DIR = Path(__file__).resolve().parent

ROLE_MULT = {  # a role amplifies the technique cluster it specialises in
    "scout": {"momentum-stack": 1.3, "stop-hunt-revert": 1.2, "premium-skew": 1.2},
    "analyst": {"funding-fade": 1.3, "dislocation-revert": 1.3, "premium-skew": 1.2},
    "executor": {"funding-fade": 1.4, "contrarian-flow": 1.3, "momentum-stack": 1.2},
    "leader": {},  # generalist — carries a balanced book
}


def home() -> Path:
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def arsenal_dir() -> Path:
    for cand in (home() / "dna" / "arsenal", SCRIPT_DIR.parent / "dna" / "arsenal"):
        if cand.exists():
            return cand
    raise SystemExit("no dna/arsenal/ found — the seed library is missing")


def _norm(v: float) -> float:
    return max(0.0, min(1.0, (v - 25) / 69.0))  # trait 25-94 → 0..1


def creature_traits() -> tuple[dict, str | None]:
    """This creature's 5 traits + role (from its stored genome, else derived)."""
    meta = {}
    try:
        meta = json.loads((home() / "metabolism.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if meta.get("genome", {}).get("stats"):
        return meta["genome"]["stats"], meta.get("role")
    try:  # derive the root genome the same way the dashboard does
        import sys
        sys.path.insert(0, str(SCRIPT_DIR))
        import dashboard
        return dashboard.genome("Gclaw", meta.get("born_at", "genesis"))["stats"], meta.get("role")
    except Exception:  # noqa: BLE001
        return {t: 60 for t in ("Vitality", "Cunning", "Aggression", "Discipline", "Fertility")}, meta.get("role")


def _crowding(raw: dict, peers: list[set] | None) -> dict:
    """Anti-monoculture: damp a technique's birth weight by how much of the living
    family already runs it, so siblings occupy different niches of the zero-sum field."""
    if not peers:
        return raw
    n = len(peers)
    for tid in raw:
        share = sum(1 for s in peers if tid in s) / n
        raw[tid] *= 1.0 / (1.0 + 0.5 * share)
    return raw


def birth_blend(traits: dict, role: str | None, peers: list[set] | None = None) -> tuple[list[dict], dict]:
    """Genome-weighted technique selection → (blend, caps). ``peers`` (the family's
    current loadouts) applies a crowding penalty so the lineage diversifies."""
    techs = {}
    for d in sorted(arsenal_dir().glob("*/")):
        try:
            techs[d.name] = json.loads((d / "technique.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    agg, cun, dis = (_norm(traits.get(k, 60)) for k in ("Aggression", "Cunning", "Discipline"))
    vit, fert = _norm(traits.get("Vitality", 60)), _norm(traits.get("Fertility", 60))
    rm = ROLE_MULT.get(role or "leader", {})
    raw = {}
    for tid, t in techs.items():
        a = t["affinity"]
        score = a["base"] + a["Aggression"] * agg + a["Cunning"] * cun + a["Discipline"] * dis
        raw[tid] = max(0.01, score * rm.get(tid, 1.0))
    raw = _crowding(raw, peers)
    n_born = round(2 + 4 * vit)  # Vitality → 2-6 weapons (breadth / survivability)
    ranked = sorted(raw, key=lambda k: raw[k], reverse=True)
    chosen, explorers = ranked[:n_born], []
    for k in ranked[n_born:][:round(2 * fert)]:  # Fertility → low-weight wildcards
        explorers.append(k)
    top = max(raw[k] for k in chosen) if chosen else 1.0
    blend = []
    for k in chosen + explorers:
        w = 0.15 if k in explorers else round(min(1.0, max(0.10, raw[k] / top)), 3)
        blend.append({"id": k, "coin": techs[k]["coin"], "interval": techs[k].get("interval", "1h"),
                      "weight": w, "born": True, "explore": k in explorers})
    dis = _norm(traits.get("Discipline", 60)) * 69 + 25  # back to 25-94 scale for the floors
    caps = {"conviction_cap": round(0.55 + 0.40 * vit, 3), "risk_mult": round(0.6 + 0.8 * agg, 3),
            "agree_min": round(0.60 + 0.0020 * (dis - 50), 3), "conv_min": round(0.22 + 0.0024 * (dis - 50), 3)}
    return blend, caps


def inherit_blend(parent_style: dict, traits: dict, role: str | None,
                  peers: list[set] | None = None) -> tuple[list[dict], dict]:
    """A child's born blend: its genome-weighted selection, tilted toward the techniques
    the parent actually made money on (proven winners), so bloodlines compound."""
    blend, caps = birth_blend(traits, role, peers)
    winners = {e["id"]: float(e.get("e", 0.0)) for e in parent_style.get("adopted", [])
               if int(e.get("trades", 0)) >= MIN_TRADES and float(e.get("e", 0.0)) > 0}
    for e in blend:
        edge = winners.get(e["id"])
        if edge:  # memetic inheritance — heavier on what worked for the parent
            e["weight"] = round(min(1.0, e["weight"] * (1.0 + 0.6 * math.tanh(edge))), 3)
            e["inherited"] = True
    return blend, caps


def materialize(fdir: Path, blend: list[dict], caps: dict, role: str | None,
                agent: str | None = None) -> dict:
    """Copy the blend's techniques into a forge dir and write its style.json (merging
    with any technique the creature already adopted on its own)."""
    ad = arsenal_dir()
    (fdir / "techniques").mkdir(parents=True, exist_ok=True)
    for e in blend:
        dst = fdir / "techniques" / e["id"]
        if not dst.exists() and (ad / e["id"]).exists():
            shutil.copytree(ad / e["id"], dst)
    arsenal_ids = {e["id"] for e in blend}
    prev = {}
    try:
        prev = json.loads((fdir / "style.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    kept = [e for e in prev.get("adopted", []) if e.get("id") not in arsenal_ids]
    style = {"agent": agent or prev.get("agent", "gclaw"), "blend_source": "birth",
             "role": role or "leader", **caps, "adopted": blend + kept,
             "updated_at": datetime.now(timezone.utc).isoformat()}
    (fdir / "style.json").write_text(json.dumps(style, indent=2) + "\n", encoding="utf-8")
    return {"born_with": [e["id"] for e in blend], "kept_own": [e["id"] for e in kept], **caps}


def seed_child(child_home: str, parent_style: dict, traits: dict, role: str | None,
               peers: list[set] | None = None) -> dict:
    """Born-with-an-arsenal for a freshly bred child: inherit the parent's winners,
    tilt by the child's bred genome, diversify against the family. Called at replicate."""
    blend, caps = inherit_blend(parent_style, traits, role, peers)
    return materialize(Path(child_home) / "forge", blend, caps, role)


def cmd_install(args: argparse.Namespace) -> dict:
    traits, role = creature_traits()
    role = args.role or role
    blend, caps = birth_blend(traits, role)
    prev = {}
    try:
        prev = json.loads((home() / "forge" / "style.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    out = materialize(home() / "forge", blend, caps, role, prev.get("agent"))
    return {"ok": True, "role": role or "leader", **out}


def cmd_show(args: argparse.Namespace) -> dict:
    traits, role = creature_traits()
    blend, caps = birth_blend(traits, args.role or role)
    return {"ok": True, "traits": traits, "role": args.role or role or "leader",
            "blend": blend, **caps}


def main() -> int:
    p = argparse.ArgumentParser(description="install a genome-weighted offensive arsenal")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("install", cmd_install), ("show", cmd_show)):
        sp = sub.add_parser(name)
        sp.add_argument("--role", choices=list(ROLE_MULT), default=None)
        sp.set_defaults(fn=fn)
    args = p.parse_args()
    print(json.dumps(args.fn(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
