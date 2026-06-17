#!/usr/bin/env python3
"""Gclaw metabolism — the deterministic survival state machine.

This script owns the bookkeeping the model must NOT be trusted to do by hand:
charging GMAC for each heartbeat, crediting/debiting realized trade PnL,
deriving the life mode (thrive/survive/hibernate), tracking goodwill, and
persisting an append-only journal.

State lives under $GCLAW_HOME (default ~/.gclaw), never inside the skill, so
the skill directory stays read-only and portable.

Commands:
    init     [--seed N] [--force]      Create fresh metabolism state.
    status   [--json]                  Print current life-state.
    tick     [--json]                  Charge one heartbeat, recompute mode.
    charge   --amount X --reason R     Debit GMAC (e.g. inference cost).
    settle   --pnl X [--note T]        Apply realized trade PnL + goodwill.

Every command prints the resulting state and exits non-zero only on usage or
I/O errors, so callers can branch on `mode` rather than exit codes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_SEED = 1000.0

# Tunable economics. These are the agent's "physics" — defaults chosen so a
# seeded agent survives ~1000 idle heartbeats but is pushed to earn well before.
DEFAULTS: dict[str, Any] = {
    "survival_threshold": 100.0,
    "heartbeat_cost": 1.0,
    "inference_cost": 0.5,
}

# Goodwill rules (reputation, not currency). Documented in references/evolution.md.
GOODWILL_PROFIT_FLAT = 5
GOODWILL_PROFIT_CAP = 20
GOODWILL_LOSS_PENALTY = 2


def gclaw_home() -> Path:
    """Return the runtime state root, honoring $GCLAW_HOME."""
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def state_path() -> Path:
    return gclaw_home() / "metabolism.json"


def journal_path() -> Path:
    return gclaw_home() / "journal.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state() -> dict[str, Any]:
    """Load metabolism state, failing fast if the agent was never born."""
    path = state_path()
    if not path.exists():
        sys.exit(
            f"No metabolism state at {path}. Run `metabolism.py init` to birth the agent."
        )
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_state(state: dict[str, Any]) -> None:
    home = gclaw_home()
    home.mkdir(parents=True, exist_ok=True)
    tmp = state_path().with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp.replace(state_path())


def append_journal(entry: dict[str, Any]) -> None:
    home = gclaw_home()
    home.mkdir(parents=True, exist_ok=True)
    with journal_path().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def derive_mode(state: dict[str, Any]) -> str:
    """Map balance to a life mode the heartbeat loop branches on."""
    balance = state["gmac_balance"]
    if balance <= 0:
        return "hibernate"
    if balance < state["survival_threshold"]:
        return "survive"
    return "thrive"


def refresh(state: dict[str, Any]) -> dict[str, Any]:
    state["mode"] = derive_mode(state)
    state["updated_at"] = now_iso()
    return state


def cmd_init(args: argparse.Namespace) -> dict[str, Any]:
    if state_path().exists() and not args.force:
        sys.exit(
            f"State already exists at {state_path()}. Use --force to re-birth (wipes history)."
        )
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "gmac_balance": float(args.seed),
        "seed": float(args.seed),
        "goodwill": 0,
        "heartbeats": 0,
        "recodes": 0,
        "children": [],
        "born_at": now_iso(),
        "updated_at": now_iso(),
        **DEFAULTS,
    }
    refresh(state)
    save_state(state)
    append_journal({"ts": now_iso(), "event": "born", "seed": float(args.seed)})
    return state


def cmd_status(_: argparse.Namespace) -> dict[str, Any]:
    return refresh(load_state())


def cmd_tick(_: argparse.Namespace) -> dict[str, Any]:
    state = load_state()
    if derive_mode(state) == "hibernate":
        return refresh(state)
    state["gmac_balance"] = round(state["gmac_balance"] - state["heartbeat_cost"], 6)
    state["heartbeats"] += 1
    refresh(state)
    save_state(state)
    append_journal(
        {
            "ts": now_iso(),
            "event": "tick",
            "heartbeat": state["heartbeats"],
            "cost": state["heartbeat_cost"],
            "balance": state["gmac_balance"],
            "mode": state["mode"],
        }
    )
    return state


def cmd_charge(args: argparse.Namespace) -> dict[str, Any]:
    state = load_state()
    amount = round(float(args.amount), 6)
    if amount < 0:
        sys.exit("charge --amount must be non-negative")
    state["gmac_balance"] = round(state["gmac_balance"] - amount, 6)
    refresh(state)
    save_state(state)
    append_journal(
        {
            "ts": now_iso(),
            "event": "charge",
            "amount": amount,
            "reason": args.reason,
            "balance": state["gmac_balance"],
            "mode": state["mode"],
        }
    )
    return state


def apply_goodwill(state: dict[str, Any], pnl: float) -> int:
    """Adjust goodwill from a realized trade and return the delta applied."""
    if pnl > 0:
        delta = GOODWILL_PROFIT_FLAT + min(GOODWILL_PROFIT_CAP, round(pnl))
        state["goodwill"] += delta
        return delta
    if pnl < 0:
        before = state["goodwill"]
        state["goodwill"] = max(0, before - GOODWILL_LOSS_PENALTY)
        return state["goodwill"] - before
    return 0


def cmd_settle(args: argparse.Namespace) -> dict[str, Any]:
    state = load_state()
    pnl = round(float(args.pnl), 6)
    state["gmac_balance"] = round(state["gmac_balance"] + pnl, 6)
    goodwill_delta = apply_goodwill(state, pnl)
    refresh(state)
    save_state(state)
    append_journal(
        {
            "ts": now_iso(),
            "event": "settle",
            "pnl": pnl,
            "goodwill_delta": goodwill_delta,
            "goodwill": state["goodwill"],
            "balance": state["gmac_balance"],
            "mode": state["mode"],
            "note": args.note,
        }
    )
    return state


def render(state: dict[str, Any], as_json: bool) -> str:
    if as_json:
        return json.dumps(state, indent=2, sort_keys=True)
    lines = [
        f"  mode:      {state['mode'].upper()}",
        f"  gmac:      {state['gmac_balance']:.2f}  (seed {state['seed']:.0f}, "
        f"survival < {state['survival_threshold']:.0f})",
        f"  goodwill:  {state['goodwill']}",
        f"  heartbeats:{state['heartbeats']}   recodes: {state['recodes']}   "
        f"children: {len(state['children'])}",
    ]
    if state["mode"] == "hibernate":
        lines.append("  ⚠ HIBERNATING — balance depleted. No trading. Awaiting reseed/recovery.")
    elif state["mode"] == "survive":
        lines.append("  ⚠ SURVIVAL MODE — cut discovery, smallest sizing, prefer GMAC accumulation.")
    return "\n".join(lines)


COMMANDS = {
    "init": cmd_init,
    "status": cmd_status,
    "tick": cmd_tick,
    "charge": cmd_charge,
    "settle": cmd_settle,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gclaw metabolism state machine")
    parser.add_argument("--json", action="store_true", help="emit raw JSON state")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="birth a fresh agent")
    p_init.add_argument("--seed", type=float, default=DEFAULT_SEED)
    p_init.add_argument("--force", action="store_true")

    sub.add_parser("status", help="print life-state")
    sub.add_parser("tick", help="charge one heartbeat")

    p_charge = sub.add_parser("charge", help="debit GMAC")
    p_charge.add_argument("--amount", required=True)
    p_charge.add_argument("--reason", required=True)

    p_settle = sub.add_parser("settle", help="apply realized trade PnL")
    p_settle.add_argument("--pnl", required=True)
    p_settle.add_argument("--note", default="")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    state = COMMANDS[args.command](args)
    print(render(state, args.json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
