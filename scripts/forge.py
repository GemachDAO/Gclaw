#!/usr/bin/env python3
"""Gclaw technique forge — agents author, prove, and trade their own skills.

A *technique* is a small skill the agent writes for itself: a pure
``signal(features) -> decision`` function plus a perf card earned on real
market history. The loop is deterministic file operations, not magic:

  draft   scaffold a technique dir (technique.json, SKILL.md, signal.py)
  prove   backtest signal.py over HyperLiquid candles, walk-forward, and
          write a perf card; only out-of-sample edge graduates it
  adopt   add a proven technique to the agent's style loadout (style.json)
  run     evaluate adopted techniques on live features and, with --execute,
          trade the top intent through hl_perp.js under the global risk caps

Every technique is stamped with the agent's onchain identity (agentId from
metabolism.json), so provenance and reputation are portable to the gene pool.
Generated signal.py is constrained by an import allow-list and executed with a
wall-clock cap; the agent has full autonomy *within* the risk caps enforced in
``run`` (leverage <= MAX_LEVERAGE, mandatory stop, $11 min, mode gating).
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import re
import shutil
import signal as signalmod
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# Risk caps (mirror dna/TRADING_STRATEGY.md — enforced, never bypassable).
MAX_LEVERAGE = 3
RISK_PCT = {"thrive": 5, "survive": 2, "hibernate": 0}
MIN_NOTIONAL = 11

# Evidence gate.
MIN_OOS_SAMPLE = 20
IS_FRACTION = 0.6
HORIZON = 4          # bars held per backtest trade
TAKER_COST = 0.0006  # round-trip fee + slippage estimate
WARMUP = 26          # bars before features are valid

# signal.py sandbox.
ALLOWED_IMPORTS = {"math", "statistics"}
BANNED_NAMES = {
    "eval", "exec", "open", "__import__", "compile", "input", "globals",
    "locals", "getattr", "setattr", "vars", "delattr", "memoryview",
}
SIGNAL_TIMEOUT_S = 2

SCRIPT_DIR = Path(__file__).resolve().parent


def gclaw_home() -> Path:
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def forge_dir() -> Path:
    d = gclaw_home() / "forge" / "techniques"
    d.mkdir(parents=True, exist_ok=True)
    return d.parent


def tech_dir(tid: str) -> Path:
    return forge_dir() / "techniques" / tid


def genepool_dir() -> Path:
    """The shared gene pool — common to every agent/child on the box.

    Independent of ``GCLAW_HOME`` so a parent and its children publish to and
    discover from one pool. Override with ``GCLAW_GENEPOOL``.
    """
    d = Path(os.environ.get("GCLAW_GENEPOOL", str(Path.home() / ".gclaw" / "genepool")))
    d.mkdir(parents=True, exist_ok=True)
    return d


def content_hash(tid: str) -> str:
    """Integrity hash over a technique's signal + claim (provenance anchor)."""
    tech = load_technique(tid)
    src = (tech_dir(tid) / "signal.py").read_text(encoding="utf-8")
    payload = json.dumps({"claim": tech.get("claim", ""), "signal": src}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def edge_score(oos: dict[str, Any]) -> float:
    """Confidence-weighted edge: expectancy scaled by sqrt(sample) (Sharpe-ish)."""
    n = int(oos.get("n", 0))
    if n <= 0:
        return 0.0
    return round(float(oos.get("expectancy", 0.0)) * math.sqrt(n), 6)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "technique"


def load_metabolism() -> dict[str, Any]:
    path = gclaw_home() / "metabolism.json"
    if not path.exists():
        return {"mode": "thrive", "onchain_identity": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def agent_id() -> str:
    ident = load_metabolism().get("onchain_identity") or {}
    return str(ident.get("agentId") or "local")


def die(msg: str) -> None:
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


# ── Market data (via the node bridge) ────────────────────────────────────────


def run_node(args: list[str]) -> dict[str, Any]:
    """Call forge_data.js and return its parsed JSON, or raise on failure."""
    proc = subprocess.run(
        ["node", str(SCRIPT_DIR / "forge_data.js"), *args],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "forge_data.js failed")
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "forge_data.js error"))
    return data


def get_candles(coin: str, interval: str, limit: int) -> list[dict[str, float]]:
    return run_node(["candles", "--coin", coin, "--interval", interval,
                     "--limit", str(limit)])["candles"]


def get_live_features(coins: list[str]) -> dict[str, Any]:
    return run_node(["features", "--coins", ",".join(coins)])["features"]


# ── Feature engineering ──────────────────────────────────────────────────────


def features_at(candles: list[dict[str, float]], i: int, coin: str,
                live: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Build the feature dict the signal sees at bar ``i`` (price-derived).

    funding/oi/premium are live-only (None in backtests) — a robust signal
    treats None as neutral. ``live`` injects them when running on real time.
    """
    closes = [candles[k]["c"] for k in range(i - 24, i + 1)]
    rets = [closes[k] / closes[k - 1] - 1 for k in range(1, len(closes))]
    price = candles[i]["c"]
    sma = statistics.fmean(closes)
    rng = statistics.fmean(
        (candles[k]["h"] - candles[k]["l"]) / candles[k]["c"] for k in range(i - 23, i + 1)
    )
    f: dict[str, Any] = {
        "coin": coin,
        "price": price,
        "ret1": price / candles[i - 1]["c"] - 1,
        "ret4": price / candles[i - 4]["c"] - 1,
        "ret24": price / candles[i - 24]["c"] - 1,
        "vol": statistics.pstdev(rets),
        "mom": price / sma - 1,
        "rng": rng,
        "funding": None,
        "oi": None,
        "premium": None,
    }
    if live:
        f["funding"] = live.get("funding")
        f["oi"] = live.get("openInterest")
        f["premium"] = live.get("premium")
    return f


# ── signal.py sandbox ────────────────────────────────────────────────────────


def validate_signal_src(src: str) -> list[str]:
    """Return a list of policy violations in a technique's signal source."""
    violations: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [f"syntax error: {exc}"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    violations.append(f"import not allowed: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                violations.append(f"import not allowed: from {node.module}")
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            violations.append(f"banned name: {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            violations.append(f"dunder access not allowed: {node.attr}")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "signal"
               for n in ast.walk(tree)):
        violations.append("missing required function: signal(features)")
    return violations


def load_signal(tid: str) -> Callable[[dict[str, Any]], Any]:
    """Validate and import a technique's signal function."""
    src_path = tech_dir(tid) / "signal.py"
    if not src_path.exists():
        die(f"no signal.py for technique '{tid}'")
    src = src_path.read_text(encoding="utf-8")
    violations = validate_signal_src(src)
    if violations:
        die(f"signal.py rejected: {'; '.join(violations)}")
    namespace: dict[str, Any] = {}
    exec(compile(src, str(src_path), "exec"), namespace)  # noqa: S102 — AST-validated above
    return namespace["signal"]


def _timeout(_signum: int, _frame: Any) -> None:
    raise TimeoutError("signal exceeded time budget")


def call_signal(fn: Callable[[dict[str, Any]], Any], f: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Call signal(features) with a wall-clock cap and validate the decision."""
    signalmod.signal(signalmod.SIGALRM, _timeout)
    signalmod.setitimer(signalmod.ITIMER_REAL, SIGNAL_TIMEOUT_S)
    try:
        out = fn(dict(f))
    finally:
        signalmod.setitimer(signalmod.ITIMER_REAL, 0)
    if not isinstance(out, dict):
        return None
    action = out.get("action")
    if action not in ("long", "short", "flat"):
        return None
    return out


# ── Backtest ─────────────────────────────────────────────────────────────────


def trade_return(candles: list[dict[str, float]], i: int, is_long: bool, stop_pct: float) -> float:
    """Forward return of a HORIZON-bar trade opened at bar i close, with a stop."""
    entry = candles[i]["c"]
    stop = stop_pct / 100.0
    for h in range(1, HORIZON + 1):
        bar = candles[i + h]
        if is_long and bar["l"] <= entry * (1 - stop):
            return -stop - TAKER_COST
        if not is_long and bar["h"] >= entry * (1 + stop):
            return -stop - TAKER_COST
    exit_px = candles[i + HORIZON]["c"]
    raw = (exit_px / entry - 1) if is_long else (entry / exit_px - 1)
    return raw - TAKER_COST


def score_window(candles: list[dict[str, float]], fn: Callable[[dict[str, Any]], Any],
                 coin: str, lo: int, hi: int) -> dict[str, Any]:
    """Run the signal across bars [lo, hi) and summarise the trades."""
    rets: list[float] = []
    for i in range(lo, hi):
        decision = call_signal(fn, features_at(candles, i, coin))
        if not decision or decision["action"] == "flat":
            continue
        stop_pct = float(decision.get("stop_pct") or 0)
        if stop_pct <= 0:
            continue
        rets.append(trade_return(candles, i, decision["action"] == "long", stop_pct))
    return summarise(rets)


def summarise(rets: list[float]) -> dict[str, Any]:
    if not rets:
        return {"n": 0, "winrate": 0.0, "expectancy": 0.0, "total": 0.0, "max_dd": 0.0}
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for r in rets:
        equity += r
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    wins = sum(1 for r in rets if r > 0)
    return {
        "n": len(rets),
        "winrate": round(wins / len(rets), 4),
        "expectancy": round(statistics.fmean(rets), 6),
        "total": round(equity, 6),
        "max_dd": round(max_dd, 6),
    }


def backtest(tid: str, coin: str, interval: str, limit: int) -> dict[str, Any]:
    """Walk-forward backtest: fit-free IS/OOS split, gate on out-of-sample edge."""
    fn = load_signal(tid)
    candles = get_candles(coin, interval, limit)
    if len(candles) < WARMUP + HORIZON + 60:
        die(f"not enough candles ({len(candles)}) — widen --limit or --interval")
    last = len(candles) - HORIZON
    split = WARMUP + int((last - WARMUP) * IS_FRACTION)
    is_stats = score_window(candles, fn, coin, WARMUP, split)
    oos_stats = score_window(candles, fn, coin, split, last)
    proven = (oos_stats["n"] >= MIN_OOS_SAMPLE
              and oos_stats["expectancy"] > 0
              and is_stats["expectancy"] > 0)
    return {
        "coin": coin, "interval": interval, "bars": len(candles),
        "in_sample": is_stats, "out_of_sample": oos_stats,
        "proven": proven, "proved_at": now_iso(),
    }


# ── Style loadout ────────────────────────────────────────────────────────────


def load_style() -> dict[str, Any]:
    path = forge_dir() / "style.json"
    if not path.exists():
        return {"agent": agent_id(), "adopted": [], "updated_at": now_iso()}
    style = json.loads(path.read_text(encoding="utf-8"))
    style["adopted"] = [
        e if isinstance(e, dict) else {"id": e, "coin": "BTC", "interval": "1h"}
        for e in style.get("adopted", [])
    ]
    return style


def save_style(style: dict[str, Any]) -> None:
    style["updated_at"] = now_iso()
    (forge_dir() / "style.json").write_text(json.dumps(style, indent=2), encoding="utf-8")


def load_technique(tid: str) -> dict[str, Any]:
    path = tech_dir(tid) / "technique.json"
    if not path.exists():
        die(f"no technique '{tid}'")
    return json.loads(path.read_text(encoding="utf-8"))


def save_technique(tech: dict[str, Any]) -> None:
    (tech_dir(tech["id"]) / "technique.json").write_text(
        json.dumps(tech, indent=2), encoding="utf-8")


# ── Verbs ────────────────────────────────────────────────────────────────────


def cmd_draft(args: argparse.Namespace) -> dict[str, Any]:
    """Scaffold a new technique the agent then fills in (signal.py)."""
    tid = slugify(args.name)
    d = tech_dir(tid)
    if d.exists() and not args.force:
        die(f"technique '{tid}' exists — use --force to overwrite")
    d.mkdir(parents=True, exist_ok=True)
    tech = {
        "id": tid, "name": args.name, "kind": args.kind,
        "author": agent_id(), "parent": args.parent,
        "claim": args.claim or "", "status": "draft",
        "created_at": now_iso(),
    }
    save_technique(tech)
    (d / "SKILL.md").write_text(SKILL_TEMPLATE.format(
        name=args.name, kind=args.kind, claim=args.claim or "(state the edge)",
        author=tech["author"]), encoding="utf-8")
    if not (d / "signal.py").exists() or args.force:
        (d / "signal.py").write_text(SIGNAL_TEMPLATE, encoding="utf-8")
    return {"ok": True, "drafted": tid, "dir": str(d),
            "next": "edit signal.py, then: forge.py prove " + tid}


def cmd_prove(args: argparse.Namespace) -> dict[str, Any]:
    card = backtest(args.id, args.coin, args.interval, args.limit)
    (tech_dir(args.id) / "card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    tech = load_technique(args.id)
    tech["status"] = "proven" if card["proven"] else "draft"
    tech["card"] = {"coin": card["coin"], "interval": card["interval"],
                    "oos": card["out_of_sample"], "proven": card["proven"]}
    save_technique(tech)
    return {"ok": True, "id": args.id, "proven": card["proven"], "card": card}


def cmd_adopt(args: argparse.Namespace) -> dict[str, Any]:
    tech = load_technique(args.id)
    if tech.get("status") != "proven" and not args.force:
        die(f"technique '{args.id}' is not proven — prove it first (or --force)")
    card = tech.get("card") or {}
    entry = {"id": args.id, "coin": card.get("coin", "BTC"),
             "interval": card.get("interval", "1h")}
    style = load_style()
    style["adopted"] = [e for e in style["adopted"] if e["id"] != args.id] + [entry]
    save_style(style)
    return {"ok": True, "adopted": style["adopted"]}


def cmd_drop(args: argparse.Namespace) -> dict[str, Any]:
    style = load_style()
    style["adopted"] = [e for e in style["adopted"] if e["id"] != args.id]
    save_style(style)
    return {"ok": True, "adopted": style["adopted"]}


def cmd_list(_args: argparse.Namespace) -> dict[str, Any]:
    techs = []
    for d in sorted((forge_dir() / "techniques").glob("*/")):
        t = json.loads((d / "technique.json").read_text(encoding="utf-8"))
        techs.append({"id": t["id"], "kind": t["kind"], "status": t["status"],
                      "author": t["author"], "claim": t.get("claim", "")[:60]})
    return {"ok": True, "adopted": load_style()["adopted"], "techniques": techs}


def cmd_show(args: argparse.Namespace) -> dict[str, Any]:
    tech = load_technique(args.id)
    card_path = tech_dir(args.id) / "card.json"
    if card_path.exists():
        tech["card_full"] = json.loads(card_path.read_text(encoding="utf-8"))
    return {"ok": True, "technique": tech}


def cmd_publish(args: argparse.Namespace) -> dict[str, Any]:
    """Publish a proven technique to the shared gene pool with onchain provenance."""
    tech = load_technique(args.id)
    if tech.get("status") != "proven" and not args.force:
        die(f"only proven techniques can be published — prove '{args.id}' first (or --force)")
    card = tech.get("card") or {}
    author = tech.get("author", agent_id())
    dest = genepool_dir() / author / args.id
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tech_dir(args.id) / "signal.py", dest / "signal.py")
    manifest = {
        "id": args.id, "name": tech.get("name", args.id), "kind": tech.get("kind", "edge"),
        "author": author, "parent": tech.get("parent"), "claim": tech.get("claim", ""),
        "card": card, "score": edge_score(card.get("oos") or {}),
        "content_hash": content_hash(args.id), "published_at": now_iso(),
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"ok": True, "published": f"{author}/{args.id}", "score": manifest["score"],
            "pool": str(genepool_dir())}


def _pool_manifests() -> list[dict[str, Any]]:
    out = []
    for mpath in genepool_dir().glob("*/*/manifest.json"):
        try:
            out.append(json.loads(mpath.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def cmd_discover(args: argparse.Namespace) -> dict[str, Any]:
    """Browse the gene pool, ranked by confidence-weighted out-of-sample edge."""
    items = _pool_manifests()
    if args.kind:
        items = [m for m in items if m.get("kind") == args.kind]
    if args.coin:
        items = [m for m in items if (m.get("card") or {}).get("coin") == args.coin]
    items.sort(key=lambda m: m.get("score", 0), reverse=True)
    mine = agent_id()
    rows = []
    for m in items[:args.limit]:
        card = m.get("card") or {}
        rows.append({
            "ref": f"{m['author']}/{m['id']}", "score": m.get("score", 0),
            "kind": m.get("kind"),
            "market": f"{card.get('coin', '')}/{card.get('interval', '')}",
            "oos": card.get("oos", {}),
            "author": m["author"] + (" (you)" if m["author"] == mine else ""),
            "claim": m.get("claim", "")[:60],
        })
    return {"ok": True, "count": len(items), "techniques": rows}


def cmd_pull(args: argparse.Namespace) -> dict[str, Any]:
    """Copy a pooled technique into the local workshop as an unproven draft.

    A pulled technique always lands as a draft with ``parent`` set to its pool
    ref — you must re-prove it on your own data before adopting. Trust nothing
    a peer claims until your own harness confirms it.
    """
    if "/" not in args.ref:
        die("ref must be <author>/<id> (see: forge.py discover)")
    author, pid = args.ref.split("/", 1)
    src = genepool_dir() / author / pid
    if not (src / "manifest.json").exists():
        die(f"no pooled technique '{args.ref}'")
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    local_id = args.as_ or pid
    d = tech_dir(local_id)
    if d.exists() and not args.force:
        die(f"local technique '{local_id}' exists — use --as <name> or --force")
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / "signal.py", d / "signal.py")
    tech = {"id": local_id, "name": manifest.get("name", local_id),
            "kind": manifest.get("kind", "edge"), "author": agent_id(),
            "parent": args.ref, "origin": manifest, "claim": manifest.get("claim", ""),
            "status": "draft", "created_at": now_iso()}
    save_technique(tech)
    (d / "SKILL.md").write_text(SKILL_TEMPLATE.format(
        name=tech["name"], kind=tech["kind"], claim=tech["claim"], author=tech["author"]),
        encoding="utf-8")
    integrity = "ok" if content_hash(local_id) == manifest.get("content_hash") else "MISMATCH"
    return {"ok": True, "pulled": args.ref, "local": local_id, "integrity": integrity,
            "next": f"re-prove before trusting: forge.py prove {local_id} --coin <c> --interval <i>"}


def _equity_usd() -> float:
    """Read HL account value via hl_perp.js (best effort; 0 on failure)."""
    try:
        proc = subprocess.run(["node", str(SCRIPT_DIR / "hl_perp.js"), "status"],
                              capture_output=True, text=True, timeout=90)
        return float(json.loads(proc.stdout.strip().splitlines()[-1]).get("accountValue", 0))
    except Exception:
        return 0.0


def _intent(tid: str, coin: str, decision: dict[str, Any], mode: str, equity: float) -> dict[str, Any]:
    """Turn a signal decision into a cap-enforced order intent."""
    leverage = max(1, min(MAX_LEVERAGE, int(decision.get("leverage") or MAX_LEVERAGE)))
    stop_pct = float(decision.get("stop_pct") or 0)
    risk_pct = RISK_PCT.get(mode, 0)
    risk_usd = equity * risk_pct / 100.0
    notional = max(MIN_NOTIONAL + 1, risk_usd / (stop_pct / 100.0)) if stop_pct > 0 else 0
    return {
        "technique": tid, "coin": coin, "side": decision["action"],
        "leverage": leverage, "sl_pct": round(stop_pct, 3),
        "confidence": float(decision.get("confidence") or 0),
        "notional": round(notional, 2),
        "reason": str(decision.get("reason") or "")[:120],
    }


def _worklist(adopted: list[dict[str, Any]], args: argparse.Namespace) -> list[tuple[str, str, str]]:
    """Resolve (technique, coin, interval) pairs to evaluate this run.

    Default: each technique on the market it was proven on. ``--coins`` overrides
    to explore a technique on other markets (at ``--interval``).
    """
    if args.coins:
        coins = [c.strip() for c in args.coins.split(",") if c.strip()]
        return [(e["id"], coin, args.interval) for e in adopted for coin in coins]
    return [(e["id"], e["coin"], e["interval"]) for e in adopted]


def cmd_run(args: argparse.Namespace) -> dict[str, Any]:
    """Evaluate adopted techniques on live features; optionally execute top intent."""
    meta = load_metabolism()
    mode = meta.get("mode", "thrive")
    style = load_style()
    if not style["adopted"]:
        return {"ok": True, "mode": mode, "intents": [], "note": "no adopted techniques"}
    # Each adopted technique runs on its own proven (coin, interval) unless overridden.
    worklist = _worklist(style["adopted"], args)
    coins = sorted({coin for _, coin, _ in worklist})
    live = get_live_features(coins)
    cache: dict[tuple[str, str], list[dict[str, float]]] = {}
    intents: list[dict[str, Any]] = []
    equity = _equity_usd()
    for tid, coin, interval in worklist:
        key = (coin, interval)
        if key not in cache:
            cache[key] = get_candles(coin, interval, 60)
        cs = cache[key]
        if len(cs) <= WARMUP:
            continue
        f = features_at(cs, len(cs) - 1, coin, live.get(coin))
        decision = call_signal(load_signal(tid), f)
        if decision and decision["action"] != "flat" and float(decision.get("stop_pct") or 0) > 0:
            intents.append(_intent(tid, coin, decision, mode, equity))
    intents.sort(key=lambda x: x["confidence"], reverse=True)
    result = {"ok": True, "mode": mode, "equity": equity, "intents": intents}
    if args.execute and intents and mode != "hibernate" and intents[0]["notional"] >= MIN_NOTIONAL:
        result["executed"] = _execute(intents[0])
    elif args.execute:
        result["executed"] = {"skipped": "hibernate, no intent, or below min notional"}
    return result


def _execute(intent: dict[str, Any]) -> dict[str, Any]:
    """Place the intent through hl_perp.js — the single cap-enforced path."""
    cmd = ["node", str(SCRIPT_DIR / "hl_perp.js"), "open",
           "--coin", intent["coin"], "--side", intent["side"],
           "--notional", str(intent["notional"]), "--leverage", str(intent["leverage"]),
           "--sl-pct", str(intent["sl_pct"]), "--tp-pct", str(round(intent["sl_pct"] * 1.5, 2))]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return {"ok": False, "error": proc.stderr.strip()[:200] or "execution failed"}


SKILL_TEMPLATE = """---
name: technique-{name}
kind: {kind}
author: agent {author}
---

# Technique: {name}

**Edge claimed:** {claim}

A self-authored Gclaw technique. `signal.py` exports `signal(features) -> decision`.

## Features available
`coin, price, ret1, ret4, ret24, vol, mom, rng` (always) and
`funding, oi, premium` (live only — None in backtests; treat None as neutral).

## Decision
Return `{{"action": "long"|"short"|"flat", "confidence": 0..1,
"leverage": 1..3, "stop_pct": >0, "reason": str}}`.

Prove it: `forge.py prove {name}` — only out-of-sample edge graduates.
"""

SIGNAL_TEMPLATE = '''"""Self-authored technique signal. Pure function; stdlib math/statistics only."""


def signal(f):
    """Map a feature dict to a trade decision (or flat)."""
    return {"action": "flat", "confidence": 0.0, "stop_pct": 2.0, "reason": "stub"}
'''


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Gclaw technique forge")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("draft", help="scaffold a new technique")
    d.add_argument("name")
    d.add_argument("--kind", choices=["lens", "edge"], default="edge")
    d.add_argument("--claim", default="")
    d.add_argument("--parent", default=None)
    d.add_argument("--force", action="store_true")
    d.set_defaults(fn=cmd_draft)

    pr = sub.add_parser("prove", help="backtest a technique and write its card")
    pr.add_argument("id")
    pr.add_argument("--coin", default="BTC")
    pr.add_argument("--interval", default="1h")
    pr.add_argument("--limit", type=int, default=1000)
    pr.set_defaults(fn=cmd_prove)

    for name, fn, helptext in [("adopt", cmd_adopt, "adopt a proven technique"),
                               ("drop", cmd_drop, "remove from loadout"),
                               ("show", cmd_show, "show a technique + card")]:
        s = sub.add_parser(name, help=helptext)
        s.add_argument("id")
        if name == "adopt":
            s.add_argument("--force", action="store_true")
        s.set_defaults(fn=fn)

    sub.add_parser("list", help="list techniques + loadout").set_defaults(fn=cmd_list)

    pub = sub.add_parser("publish", help="publish a proven technique to the gene pool")
    pub.add_argument("id")
    pub.add_argument("--force", action="store_true")
    pub.set_defaults(fn=cmd_publish)

    disc = sub.add_parser("discover", help="browse the gene pool, ranked by edge")
    disc.add_argument("--kind", choices=["lens", "edge"], default=None)
    disc.add_argument("--coin", default=None)
    disc.add_argument("--limit", type=int, default=20)
    disc.set_defaults(fn=cmd_discover)

    pull = sub.add_parser("pull", help="copy a pooled technique locally (as a draft)")
    pull.add_argument("ref", help="<author>/<id> from discover")
    pull.add_argument("--as", dest="as_", default=None, help="local id to save under")
    pull.add_argument("--force", action="store_true")
    pull.set_defaults(fn=cmd_pull)

    r = sub.add_parser("run", help="evaluate adopted techniques on live data")
    r.add_argument("--coins", default=None, help="override markets (default: each technique's proven market)")
    r.add_argument("--interval", default="1h", help="interval for --coins override")
    r.add_argument("--execute", action="store_true", help="place the top intent (within caps)")
    r.set_defaults(fn=cmd_run)
    return p


def main() -> None:
    args = build_parser().parse_args()
    print(json.dumps(args.fn(args), indent=2))


if __name__ == "__main__":
    main()
