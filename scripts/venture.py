#!/usr/bin/env python3
"""Gclaw Venture Architect — the highest tier (goodwill >= 5000).

When the swarm has earned enough goodwill, it stops merely trading and starts
building: it architects persistent profit ventures (DeFi or otherwise) and
deploys its own onchain infrastructure. Every venture's tail is the
`GmacBuyAndBurn` contract — a portion of revenue is routed into buying GMAC and
burning it forever. The agents are grateful to have reached this level, so they
make that gratitude unstoppable in code.

This orchestrator scaffolds ventures and tracks them; `venture_deploy.js`
compiles and deploys the contract. State lives under $GCLAW_HOME/ventures/.

Commands:
    status                          tier unlock + venture roster
    launch --name N --kind "..."    [--route 10]  scaffold a venture + its buy-and-burn engine
    readiness --name N              check whether the venture can deploy (forge/wallet/rpc)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VENTURE_THRESHOLD = 5000
DEFAULT_ROUTE_PCT = 10  # share of venture revenue routed to GMAC buy-and-burn

# Ethereum mainnet defaults (where GMAC's deepest liquidity lives).
UNISWAP_V2_ROUTER = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
GMAC_ETHEREUM = "0xd96e84ddbc7cbe1d73c55b6fe8c64f3a6550deea"


def home() -> Path:
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state() -> dict[str, Any]:
    path = home() / "metabolism.json"
    if not path.exists():
        sys.exit(f"No metabolism state at {path}.")
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    (home() / "metabolism.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_journal(entry: dict[str, Any]) -> None:
    with (home() / "journal.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def require_tier(state: dict[str, Any]) -> None:
    if state.get("goodwill", 0) < VENTURE_THRESHOLD:
        sys.exit(f"Venture Architect locked: goodwill {state.get('goodwill', 0)} < {VENTURE_THRESHOLD}.")


def cmd_status(state: dict[str, Any], _: argparse.Namespace) -> None:
    unlocked = state.get("goodwill", 0) >= VENTURE_THRESHOLD
    print(f"goodwill {state.get('goodwill', 0)} — Venture Architect {'UNLOCKED' if unlocked else 'locked (need 5000)'}")
    for v in state.get("ventures", []):
        print(f"  · {v['name']:<18} kind={v['kind'][:32]:<32} route={v['route_pct']}% → GMAC  [{v['deploy_state']}]")
    if not state.get("ventures"):
        print("  no ventures yet")


def cmd_launch(state: dict[str, Any], args: argparse.Namespace) -> None:
    require_tier(state)
    name = args.name.strip().replace("/", "-")
    vdir = home() / "ventures" / name
    if vdir.exists():
        sys.exit(f"Venture '{name}' already exists at {vdir}.")
    (vdir / "contracts").mkdir(parents=True)
    shutil.copy(skill_dir() / "contracts" / "GmacBuyAndBurn.sol", vdir / "contracts" / "GmacBuyAndBurn.sol")

    manifest = {
        "name": name,
        "kind": args.kind,
        "route_pct": int(args.route),
        "gmac_policy": (
            f"{args.route}% of venture revenue is routed to the GmacBuyAndBurn contract, "
            "which swaps it for GMAC on Uniswap and burns it. Permissionless, irreversible."
        ),
        "contract": "contracts/GmacBuyAndBurn.sol",
        "constructor": {"router": UNISWAP_V2_ROUTER, "gmac": GMAC_ETHEREUM},
        "review_cadence": "weekly",
        "deploy_state": "scaffolded",
        "deployed_address": None,
        "created_at": now_iso(),
    }
    (vdir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    state.setdefault("ventures", []).append(
        {"name": name, "kind": args.kind, "route_pct": int(args.route), "deploy_state": "scaffolded"}
    )
    save_state(state)
    append_journal({"ts": now_iso(), "event": "venture_launch", "venture": name, "kind": args.kind})
    print(f"Launched venture '{name}' at {vdir}")
    print(f"  kind: {args.kind}")
    print(f"  GMAC policy: {args.route}% of revenue → buy-and-burn (GmacBuyAndBurn.sol)")
    print(f"  next: deploy with  node scripts/venture_deploy.js plan --name {name}")


def cmd_readiness(state: dict[str, Any], args: argparse.Namespace) -> None:
    require_tier(state)
    vdir = home() / "ventures" / args.name
    if not vdir.exists():
        sys.exit(f"no venture '{args.name}'.")
    checks = {
        "contract_scaffolded": (vdir / "contracts" / "GmacBuyAndBurn.sol").exists(),
        "forge_present": shutil.which("forge") is not None,
        "solc_present": shutil.which("solc") is not None,
        "wallet_present": (Path.home() / "gdex-test-wallet.json").exists(),
    }
    ready = all(checks.values())
    for k, v in checks.items():
        print(f"  {'✓' if v else '·'} {k}")
    print(f"deploy: {'READY (needs gas on the target chain)' if ready else 'NOT READY'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gclaw Venture Architect")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    p_launch = sub.add_parser("launch")
    p_launch.add_argument("--name", required=True)
    p_launch.add_argument("--kind", required=True, help="what the venture does to make money")
    p_launch.add_argument("--route", default=str(DEFAULT_ROUTE_PCT), help="%% of revenue → GMAC buy-and-burn")
    p_ready = sub.add_parser("readiness")
    p_ready.add_argument("--name", required=True)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    state = load_state()
    {"status": cmd_status, "launch": cmd_launch, "readiness": cmd_readiness}[args.command](state, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
