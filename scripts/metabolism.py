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

# GMAC buy-back: a fixed share of every realized USD profit is set aside (in USD)
# to later buy real GMAC (the Gemach token) on Ethereum. See references/gmac.md.
# Note: `gmac_balance` is abstract life energy; `gmac_treasury_usd` is real money
# earmarked to buy the real token; `gmac_tokens_held` is the token actually bought.
GMAC_BUYBACK_RATE = 0.10


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
        "gmac_treasury_usd": 0.0,
        "gmac_tokens_held": 0.0,
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
    buyback = round(max(0.0, pnl) * GMAC_BUYBACK_RATE, 6)
    state["gmac_treasury_usd"] = round(state.get("gmac_treasury_usd", 0.0) + buyback, 6)
    refresh(state)
    save_state(state)
    append_journal(
        {
            "ts": now_iso(),
            "event": "settle",
            "pnl": pnl,
            "goodwill_delta": goodwill_delta,
            "goodwill": state["goodwill"],
            "gmac_buyback_usd": buyback,
            "gmac_treasury_usd": state["gmac_treasury_usd"],
            "balance": state["gmac_balance"],
            "mode": state["mode"],
            "note": args.note,
        }
    )
    return state


def _peek(name: str) -> dict[str, Any]:
    """Best-effort read of a sibling runtime file for the status card."""
    try:
        return json.loads((gclaw_home() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _bar(weight: float, width: int = 10) -> str:
    fill = max(0, min(width, round(float(weight) * width)))
    return "▰" * fill + "▱" * (width - fill)


def _arsenal_lines() -> list[str]:
    """The born arsenal as a tidy, weight-ranked loadout."""
    style = _peek("forge/style.json")
    adopted = style.get("adopted", [])
    if not adopted:
        return []
    caps = (f"conviction cap {style.get('conviction_cap', 0.85):.2f}"
            f" · risk ×{style.get('risk_mult', 1.0):.2f}")
    rows = [f"  {'Arsenal':<12}{len(adopted)} techniques · {caps}"]
    for e in sorted(adopted, key=lambda x: -float(x.get("weight", 1.0) or 1.0))[:6]:
        w = float(e.get("weight", 1.0) or 1.0)
        tag = " ·born" if e.get("born") else ""
        rows.append(f"       {e.get('id', '?'):<20}{_bar(w)}  {w:.2f}{tag}")
    return ["", *rows]


def render(state: dict[str, Any], as_json: bool) -> str:
    if as_json:
        return json.dumps(state, indent=2, sort_keys=True)
    persona = _peek("dna/persona.json")
    pos = _peek("positions.json")
    name = state.get("name") or persona.get("species") or "Gclaw"
    subtitle = f" — {persona['archetype']}" if persona.get("archetype") else ""
    upnl = sum(float(p.get("unrealizedPnl", 0) or 0) for p in (pos.get("positions") or []))
    npos = len(pos.get("positions") or [])
    sign = "+" if upnl >= 0 else "−"
    rule = "  " + "─" * 50

    def row(label: str, value: str) -> str:
        return f"  {label:<12}{value}"

    lines = [f"  ◇  {name}{subtitle}", rule, row("Mode", state["mode"].upper())]
    if pos:
        lines.append(row("Equity", f"${float(pos.get('equity', 0) or 0):,.2f}   ·  "
                         f"{sign}${abs(upnl):,.2f} unrealized · {npos} open"))
    lines += [
        row("Life energy", f"{state['gmac_balance']:.0f} GMAC  ·  seed {state['seed']:.0f}"
            f" · survive < {state['survival_threshold']:.0f}"),
        row("Goodwill", f"{state['goodwill']}        ·  {state['heartbeats']} heartbeats"
            f" · {len(state['children'])} children · {state['recodes']} recodes"),
    ]
    if state.get("gmac_treasury_usd", 0.0):
        lines.append(row("Treasury", f"${state['gmac_treasury_usd']:.2f} earmarked for GMAC buy-back"))
    lines += _arsenal_lines()
    if state["mode"] == "hibernate":
        lines += [rule, "  ⚠  Hibernating — life energy depleted. Trading paused; awaiting reseed."]
    elif state["mode"] == "survive":
        lines += [rule, "  ⚠  Survival mode — smallest sizing, discovery paused, accruing GMAC."]
    return "\n".join(lines)


def cmd_gmac(args: argparse.Namespace) -> dict[str, Any]:
    """Report the GMAC buy-back treasury, or record a completed onchain buy."""
    state = load_state()
    if args.spend:
        spent = round(float(args.spend), 6)
        tokens = round(float(args.tokens), 6)
        if spent > state.get("gmac_treasury_usd", 0.0) + 1e-9:
            sys.exit(f"spend ${spent} exceeds treasury ${state.get('gmac_treasury_usd', 0.0)}")
        state["gmac_treasury_usd"] = round(state["gmac_treasury_usd"] - spent, 6)
        state["gmac_tokens_held"] = round(state.get("gmac_tokens_held", 0.0) + tokens, 6)
        refresh(state)
        save_state(state)
        append_journal(
            {
                "ts": now_iso(),
                "event": "gmac_buy",
                "spent_usd": spent,
                "tokens": tokens,
                "tx": args.tx,
                "treasury_usd": state["gmac_treasury_usd"],
                "tokens_held": state["gmac_tokens_held"],
            }
        )
    return refresh(state)


COMMANDS = {
    "init": cmd_init,
    "status": cmd_status,
    "tick": cmd_tick,
    "charge": cmd_charge,
    "settle": cmd_settle,
    "gmac": cmd_gmac,
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

    p_gmac = sub.add_parser("gmac", help="GMAC buy-back treasury (report, or record a buy)")
    p_gmac.add_argument("--spend", help="USD spent on a completed GMAC buy")
    p_gmac.add_argument("--tokens", default="0", help="GMAC tokens received")
    p_gmac.add_argument("--tx", default="", help="onchain tx hash")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    state = COMMANDS[args.command](args)
    print(render(state, args.json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
