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
# Leverage is EARNED: the cap rises with goodwill, the metric won from profitable
# trades. A young agent trades small and careful; it unlocks more rope as it
# proves it can survive. Keep this ladder in sync with hl_perp.js.
MAX_LEVERAGE = 20  # absolute ceiling at the top of the ladder
LEVERAGE_LADDER = [(0, 3), (50, 5), (200, 10), (500, 15), (1000, 20)]
RISK_PCT = {"thrive": 5, "survive": 2, "hibernate": 0}
MIN_NOTIONAL = 11

# Default markets each adopted technique is scanned across every run: majors on
# the default dex plus the deepest HIP-3 stock/commodity perps on the `xyz`
# builder dex (USDC-collateralized, 24h). A technique auto-executes only on the
# market it was proven on; signals on the rest are surfaced as exploration for
# the heartbeat's judgment (and as candidates to prove next). Override --coins.
SCAN_UNIVERSE = (
    "BTC", "ETH", "SOL",
    "xyz:NVDA", "xyz:TSLA", "xyz:SPCX", "xyz:AAPL", "xyz:AMZN", "xyz:GOLD",
)

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
    "__builtins__", "breakpoint", "help", "object", "type", "super",
    "classmethod", "staticmethod", "property",
}
# Attribute access that can pivot to builtins/globals even without a dunder name.
BANNED_ATTRS = {"format", "format_map", "mro", "__class__", "__globals__", "__subclasses__"}
SIGNAL_TIMEOUT_S = 2


def _safe_import(name: str, *_a: Any, **_k: Any) -> Any:
    """The only import a signal may perform — the allow-listed math libs."""
    import math
    import statistics
    allowed = {"math": math, "statistics": statistics}
    if name in allowed:
        return allowed[name]
    raise ImportError(f"import '{name}' is not allowed in a technique signal")


def _safe_builtins() -> dict[str, Any]:
    """A minimal builtins set with NO code-exec / introspection / io escape hatches.

    Restricting `__builtins__` in the exec namespace is the load-bearing control:
    it removes the `__builtins__['__import__']('os')` subscript escape that the AST
    validator alone cannot see. The validator is defense-in-depth on top.
    """
    safe = ("abs", "min", "max", "round", "sum", "len", "range", "sorted", "enumerate",
            "zip", "map", "filter", "any", "all", "pow", "divmod", "float", "int",
            "bool", "str", "list", "dict", "tuple", "set", "abs", "isinstance")
    import builtins
    out: dict[str, Any] = {k: getattr(builtins, k) for k in safe}
    out["__import__"] = _safe_import
    return out

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


# ── Royalties + reputation (shared, onchain-anchored) ────────────────────────

ROYALTY_PCT = 10  # share of an adopter's positive PnL credited to the author


def royalty_ledger() -> Path:
    return genepool_dir() / "royalties.jsonl"


def pending_path() -> Path:
    return forge_dir() / "pending.json"


def load_pending() -> dict[str, Any]:
    p = pending_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_pending(d: dict[str, Any]) -> None:
    pending_path().write_text(json.dumps(d, indent=2), encoding="utf-8")


def royalty_ref(tech: dict[str, Any]) -> tuple[str, str]:
    """Resolve the technique's origin ref and author to credit (pool parent wins)."""
    parent = tech.get("parent") or ""
    if "/" in parent:
        return parent, parent.split("/", 1)[0]
    author = tech.get("author", agent_id())
    return f"{author}/{tech['id']}", author


def _read_ledger() -> list[dict[str, Any]]:
    p = royalty_ledger()
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def reputation_table() -> dict[str, Any]:
    """Aggregate the royalty ledger into per-author reputation."""
    rep: dict[str, Any] = {}
    for e in _read_ledger():
        a = e["author"]
        r = rep.setdefault(a, {"author": a, "earned_usd": 0.0, "trades": 0,
                               "wins": 0, "adopters": set()})
        r["earned_usd"] += e.get("royalty_usd", 0.0)
        r["trades"] += 1
        if e.get("pnl_usd", 0) > 0:
            r["wins"] += 1
        r["adopters"].add(e.get("adopter"))
    for r in rep.values():
        r["adopters"] = len(r["adopters"])
        r["earned_usd"] = round(r["earned_usd"], 6)
        r["score"] = round(r["earned_usd"] + 0.05 * r["wins"], 4)
    return rep


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


def leverage_cap(goodwill: Optional[float] = None) -> int:
    """The agent's earned leverage ceiling, unlocked by goodwill."""
    if goodwill is None:
        goodwill = float(load_metabolism().get("goodwill", 0) or 0)
    cap = LEVERAGE_LADDER[0][1]
    for threshold, lev in LEVERAGE_LADDER:
        if goodwill >= threshold:
            cap = lev
    return min(cap, MAX_LEVERAGE)


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
        elif isinstance(node, ast.Name) and (node.id in BANNED_NAMES or node.id.startswith("__")):
            violations.append(f"banned name: {node.id}")
        elif isinstance(node, ast.Attribute) and (node.attr.startswith("__") or node.attr in BANNED_ATTRS):
            violations.append(f"banned attribute access: {node.attr}")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "signal"
               for n in ast.walk(tree)):
        violations.append("missing required function: signal(features)")
    return violations


def _compile_signal(src: str, where: str) -> Callable[[dict[str, Any]], Any]:
    """Validate against the sandbox policy and compile; raise ValueError if rejected."""
    violations = validate_signal_src(src)
    if violations:
        raise ValueError("; ".join(violations))
    # Restricted builtins are the real boundary; the AST validation is defence in
    # depth. Together they close the __builtins__/__import__ subscript escape.
    namespace: dict[str, Any] = {"__builtins__": _safe_builtins()}
    exec(compile(src, where, "exec"), namespace)  # noqa: S102 — sandboxed builtins + AST-validated
    return namespace["signal"]


def load_signal(tid: str) -> Callable[[dict[str, Any]], Any]:
    """Validate and import a local technique's signal function."""
    src_path = tech_dir(tid) / "signal.py"
    if not src_path.exists():
        die(f"no signal.py for technique '{tid}'")
    try:
        return _compile_signal(src_path.read_text(encoding="utf-8"), str(src_path))
    except ValueError as exc:
        die(f"signal.py rejected: {exc}")


def load_pooled_signal(ref: str) -> Optional[Callable[[dict[str, Any]], Any]]:
    """Compile a pooled technique's signal (returns None if missing or rejected)."""
    if "/" not in ref:
        return None
    author, pid = ref.split("/", 1)
    p = genepool_dir() / author / pid / "signal.py"
    if not p.exists():
        return None
    try:
        return _compile_signal(p.read_text(encoding="utf-8"), str(p))
    except ValueError:
        return None


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


def _backtest_with(fn: Callable[[dict[str, Any]], Any], coin: str,
                   interval: str, limit: int) -> dict[str, Any]:
    """Walk-forward backtest of a signal fn; raises ValueError on thin data."""
    candles = get_candles(coin, interval, limit)
    if len(candles) < WARMUP + HORIZON + 60:
        raise ValueError(f"not enough candles ({len(candles)}) — widen --limit or --interval")
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


def backtest(tid: str, coin: str, interval: str, limit: int) -> dict[str, Any]:
    """Walk-forward backtest: fit-free IS/OOS split, gate on out-of-sample edge."""
    try:
        return _backtest_with(load_signal(tid), coin, interval, limit)
    except ValueError as exc:
        die(str(exc))


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
    if tech.get("parent") and not (tech.get("critique") or {}).get("pass") and not args.force:
        die(f"'{args.id}' came from the pool — critique it first "
            f"(forge.py critique {args.id}) or --force")
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
        "author": author, "parent": tech.get("parent"), "lineage": tech.get("lineage", []),
        "claim": tech.get("claim", ""), "card": card, "score": edge_score(card.get("oos") or {}),
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
    rep = reputation_table()
    board = load_leaderboard()
    mine = agent_id()

    def boost(ref: str) -> float:
        rank = board["ranks"].get(ref)
        if not rank or board["count"] == 0:
            return 0.0
        return (board["count"] - rank + 1) / board["count"] * 0.02

    def combined(m: dict[str, Any]) -> float:
        ref = f"{m['author']}/{m['id']}"
        author_rep = rep.get(m["author"], {}).get("score", 0.0)
        return m.get("score", 0.0) + 0.5 * author_rep + boost(ref)

    items.sort(key=combined, reverse=True)
    rows = []
    for m in items[:args.limit]:
        card = m.get("card") or {}
        ref = f"{m['author']}/{m['id']}"
        rows.append({
            "ref": ref, "score": m.get("score", 0),
            "author_reputation": rep.get(m["author"], {}).get("score", 0.0),
            "tournament_rank": board["ranks"].get(ref),
            "rank": round(combined(m), 6), "kind": m.get("kind"),
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
            "parent": args.ref, "lineage": (manifest.get("lineage") or []) + [args.ref],
            "origin": manifest, "claim": manifest.get("claim", ""),
            "status": "draft", "created_at": now_iso()}
    save_technique(tech)
    (d / "SKILL.md").write_text(SKILL_TEMPLATE.format(
        name=tech["name"], kind=tech["kind"], claim=tech["claim"], author=tech["author"]),
        encoding="utf-8")
    integrity = "ok" if content_hash(local_id) == manifest.get("content_hash") else "MISMATCH"
    return {"ok": True, "pulled": args.ref, "local": local_id, "integrity": integrity,
            "next": f"re-prove before trusting: forge.py prove {local_id} --coin <c> --interval <i>"}


def cmd_royalty(args: argparse.Namespace) -> dict[str, Any]:
    """Attribute a realized PnL to the technique that opened it and credit its author.

    Called on close: looks up the pending forge trade for the coin (set by
    ``run --execute``), credits ROYALTY_PCT of any positive PnL to the origin
    author (never to yourself), and appends to the shared royalty ledger.
    """
    pending = load_pending()
    rec = pending.get(args.coin)
    if not rec and not args.ref:
        die(f"no pending forge trade on {args.coin} — pass --ref <author>/<id> to attribute manually")
    ref = (rec or {}).get("ref") or args.ref
    author = ref.split("/", 1)[0] if "/" in ref else ref
    adopter = agent_id()
    pnl = float(args.pnl)
    royalty = round(max(0.0, pnl) * ROYALTY_PCT / 100, 6) if author != adopter else 0.0
    entry = {"ts": now_iso(), "technique": ref, "author": author, "adopter": adopter,
             "coin": args.coin, "pnl_usd": round(pnl, 6), "royalty_usd": royalty}
    with royalty_ledger().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    if rec:
        pending.pop(args.coin, None)
        save_pending(pending)
    return {"ok": True, "attributed": entry}


def _sync_reputation(broadcast: bool) -> dict[str, Any]:
    mode = "broadcast" if broadcast else "dry-run"
    try:
        proc = subprocess.run(["node", str(SCRIPT_DIR / "erc8004_reputation.js"), mode],
                              capture_output=True, text=True, timeout=120)
        tail = (proc.stdout or proc.stderr).strip().splitlines()[-1:] or [""]
        return {"ok": proc.returncode == 0, "mode": mode, "detail": tail[0][:200]}
    except Exception as exc:  # noqa: BLE001 — sync is best-effort
        return {"ok": False, "mode": mode, "note": "reputation sync unavailable",
                "error": str(exc)[:120]}


def load_leaderboard() -> dict[str, Any]:
    """Latest tournament standings as {ref: rank} plus the field size."""
    p = genepool_dir() / "leaderboard.json"
    if not p.exists():
        return {"ranks": {}, "count": 0}
    board = json.loads(p.read_text(encoding="utf-8"))
    standings = board.get("standings", [])
    return {"ranks": {s["ref"]: s["rank"] for s in standings}, "count": len(standings)}


def cmd_tournament(args: argparse.Namespace) -> dict[str, Any]:
    """Compete every pooled technique on one fresh, identical benchmark.

    Each author chose the market their technique looked best on; a tournament
    re-scores them all on the *same* coins and window, so the ranking is
    head-to-head rather than self-selected. Standings are written to the shared
    leaderboard and boost the winners in `discover`.
    """
    coins = [c.strip() for c in args.coins.split(",") if c.strip()]
    manifests = _pool_manifests()
    if not manifests:
        die("gene pool is empty — publish a technique first")
    standings = []
    for m in manifests:
        ref = f"{m['author']}/{m['id']}"
        fn = load_pooled_signal(ref)
        if fn is None:
            continue
        per_coin: dict[str, float] = {}
        for coin in coins:
            try:
                card = _backtest_with(fn, coin, args.interval, args.limit)
            except ValueError:
                continue
            per_coin[coin] = edge_score(card["out_of_sample"])
        if per_coin:
            standings.append({"ref": ref, "author": m["author"],
                              "benchmark_score": round(sum(per_coin.values()), 6),
                              "per_coin": per_coin})
    standings.sort(key=lambda s: s["benchmark_score"], reverse=True)
    for i, s in enumerate(standings, 1):
        s["rank"] = i
    board = {"benchmark": {"coins": coins, "interval": args.interval},
             "standings": standings, "at": now_iso()}
    (genepool_dir() / "leaderboard.json").write_text(json.dumps(board, indent=2), encoding="utf-8")
    return {"ok": True, "benchmark": board["benchmark"], "standings": standings}


def cmd_reputation(args: argparse.Namespace) -> dict[str, Any]:
    """Show author reputation aggregated from the royalty ledger (optionally sync onchain)."""
    rep = reputation_table()
    if args.author:
        rows = [rep.get(args.author, {"author": args.author, "score": 0, "earned_usd": 0})]
    else:
        rows = sorted(rep.values(), key=lambda x: x.get("score", 0), reverse=True)
    out: dict[str, Any] = {"ok": True, "reputation": rows}
    if args.sync:
        out["onchain"] = _sync_reputation(args.broadcast)
    return out


def _resolve_source(ref: str) -> tuple[Path, dict[str, Any], list[str]]:
    """Resolve a fork source (local id or pool <author>/<id>) → signal, meta, lineage."""
    if "/" in ref:
        author, pid = ref.split("/", 1)
        src = genepool_dir() / author / pid
        if not (src / "manifest.json").exists():
            die(f"no pooled technique '{ref}'")
        meta = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
        return src / "signal.py", meta, meta.get("lineage") or []
    if not (tech_dir(ref) / "technique.json").exists():
        die(f"no local technique '{ref}'")
    meta = load_technique(ref)
    return tech_dir(ref) / "signal.py", meta, meta.get("lineage") or []


def cmd_fork(args: argparse.Namespace) -> dict[str, Any]:
    """Derive a new technique from a source to improve it; ancestry is tracked."""
    sig_path, src_meta, parent_lineage = _resolve_source(args.source)
    newid = slugify(args.name)
    d = tech_dir(newid)
    if d.exists() and not args.force:
        die(f"technique '{newid}' exists — use a different --name or --force")
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sig_path, d / "signal.py")
    tech = {"id": newid, "name": args.name, "kind": src_meta.get("kind", "edge"),
            "author": agent_id(), "parent": args.source,
            "lineage": parent_lineage + [args.source],
            "claim": args.claim or src_meta.get("claim", ""),
            "status": "draft", "created_at": now_iso()}
    save_technique(tech)
    (d / "SKILL.md").write_text(SKILL_TEMPLATE.format(
        name=args.name, kind=tech["kind"], claim=tech["claim"], author=tech["author"]),
        encoding="utf-8")
    return {"ok": True, "forked": newid, "from": args.source, "lineage": tech["lineage"],
            "next": f"improve signal.py, then: forge.py prove {newid}"}


def cmd_lineage(args: argparse.Namespace) -> dict[str, Any]:
    """Show a technique's ancestry chain (oldest → this)."""
    tech = load_technique(args.id)
    chain = list(tech.get("lineage") or []) + [f"{tech.get('author')}/{args.id}"]
    return {"ok": True, "id": args.id, "depth": len(chain) - 1, "lineage": chain}


def _critique_markets(claimed: Optional[str]) -> list[str]:
    base = ["BTC", "ETH", "SOL"]
    if claimed and claimed not in base:
        base.append(claimed)
    return base


def cmd_critique(args: argparse.Namespace) -> dict[str, Any]:
    """Adversarially re-prove a (usually pooled) technique on your own harness.

    Re-runs the backtest across several markets — including the author's claimed
    one — to see whether the edge replicates and generalises rather than fitting
    a single cherry-picked market. Peer code runs through the same AST sandbox.
    On a clean replication it also graduates the technique locally so it can be
    adopted; otherwise it stays a draft with the failing verdict attached.
    """
    tech = load_technique(args.id)
    origin_card = (tech.get("origin") or {}).get("card") or tech.get("card") or {}
    interval = args.interval or origin_card.get("interval", "4h")
    claimed_coin = origin_card.get("coin")
    coins = [c.strip() for c in args.coins.split(",")] if args.coins else _critique_markets(claimed_coin)
    markets: dict[str, Any] = {}
    claimed_card: Optional[dict[str, Any]] = None
    for coin in coins:
        card = backtest(args.id, coin, interval, args.limit)
        markets[coin] = {"proven": card["proven"],
                         "oos_exp": card["out_of_sample"]["expectancy"],
                         "n": card["out_of_sample"]["n"]}
        if coin == claimed_coin:
            claimed_card = card
    replicated = bool(claimed_coin and markets.get(claimed_coin, {}).get("proven"))
    positives = sum(1 for r in markets.values()
                    if r["oos_exp"] > 0 and r["n"] >= MIN_OOS_SAMPLE)
    robust = positives >= math.ceil(len(markets) / 2)
    verdict = {"replicated": replicated, "robust": robust,
               "pass": bool(replicated and robust), "markets": markets,
               "interval": interval, "critic": agent_id(), "at": now_iso()}
    (tech_dir(args.id) / "critique.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    tech["critique"] = verdict
    if replicated and claimed_card is not None:
        (tech_dir(args.id) / "card.json").write_text(json.dumps(claimed_card, indent=2), encoding="utf-8")
        tech["status"] = "proven"
        tech["card"] = {"coin": claimed_card["coin"], "interval": claimed_card["interval"],
                        "oos": claimed_card["out_of_sample"], "proven": True}
    save_technique(tech)
    return {"ok": True, "id": args.id, "verdict": verdict}


def _account() -> dict[str, float]:
    """Read HL equity + free buying power via hl_perp.js (best effort).

    HL keeps one unified USDC balance; `equity` is the whole account and
    `buyingPower` is the slice not already pledged as margin. Perp
    `withdrawable`/`accountValue` only reflect committed margin, so neither is
    the capital available for a new trade.
    """
    try:
        proc = subprocess.run(["node", str(SCRIPT_DIR / "hl_perp.js"), "status"],
                              capture_output=True, text=True, timeout=90)
        st = json.loads(proc.stdout.strip().splitlines()[-1])
        equity = float(st.get("equity") or st.get("spotUsdc") or st.get("accountValue") or 0)
        return {"equity": equity, "buying_power": float(st.get("buyingPower") or equity),
                "positions": len(st.get("positions") or [])}
    except Exception:
        return {"equity": 0.0, "buying_power": 0.0, "positions": 0}


# Portfolio circuit breaker — halts NEW entries (never closes/blocks risk-reduction)
# when the account is in trouble, independent of the GMAC life-energy mode.
MAX_DRAWDOWN_PCT = 25  # halt new entries if equity falls this far below its high-water mark
MAX_OPEN_POSITIONS = 3  # cap concurrent positions to bound concentration


def circuit_breaker(equity: float, n_positions: int) -> dict[str, Any]:
    """Update the equity high-water mark and decide whether new entries are allowed."""
    path = gclaw_home() / "breaker.json"
    state = {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    hwm = max(float(state.get("hwm", 0) or 0), equity)
    drawdown_pct = round((1 - equity / hwm) * 100, 2) if hwm > 0 else 0.0
    reason = None
    if drawdown_pct >= MAX_DRAWDOWN_PCT:
        reason = f"drawdown {drawdown_pct}% ≥ {MAX_DRAWDOWN_PCT}% from high-water ${hwm:.2f}"
    elif n_positions >= MAX_OPEN_POSITIONS:
        reason = f"{n_positions} open positions ≥ {MAX_OPEN_POSITIONS} cap"
    state.update({"hwm": round(hwm, 2), "equity": round(equity, 2),
                  "drawdown_pct": drawdown_pct, "positions": n_positions,
                  "tripped": bool(reason), "reason": reason, "at": now_iso()})
    try:
        path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return {"allow_entry": not reason, "reason": reason, "drawdown_pct": drawdown_pct, "hwm": round(hwm, 2)}


def _intent(tid: str, coin: str, decision: dict[str, Any], mode: str, equity: float,
            cap: int, buying_power: float) -> dict[str, Any]:
    """Turn a signal decision into a cap-enforced order intent (cap = earned ceiling)."""
    leverage = max(1, min(cap, int(decision.get("leverage") or cap)))
    stop_pct = float(decision.get("stop_pct") or 0)
    risk_pct = RISK_PCT.get(mode, 0)
    risk_usd = equity * risk_pct / 100.0
    notional = max(MIN_NOTIONAL + 1, risk_usd / (stop_pct / 100.0)) if stop_pct > 0 else 0
    # Margin = notional / leverage must fit the free collateral (95% headroom for fees).
    max_notional = max(0.0, buying_power * 0.95) * leverage
    if notional > max_notional:
        notional = max_notional if max_notional >= MIN_NOTIONAL else 0
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
    # Scan each technique across its proven market first, then the wider universe.
    return [(e["id"], coin, e["interval"])
            for e in adopted
            for coin in dict.fromkeys([e["coin"], *SCAN_UNIVERSE])]


def cmd_run(args: argparse.Namespace) -> dict[str, Any]:
    """Evaluate adopted techniques on live features; optionally execute top intent."""
    meta = load_metabolism()
    mode = meta.get("mode", "thrive")
    cap = leverage_cap(float(meta.get("goodwill", 0) or 0))
    style = load_style()
    if not style["adopted"]:
        return {"ok": True, "mode": mode, "leverage_cap": cap, "intents": [],
                "note": "no adopted techniques"}
    # Each adopted technique runs on its own proven (coin, interval) unless overridden.
    worklist = _worklist(style["adopted"], args)
    proven_coin = {e["id"]: e["coin"] for e in style["adopted"]}
    coins = sorted({coin for _, coin, _ in worklist})
    live = get_live_features(coins)
    cache: dict[tuple[str, str], list[dict[str, float]]] = {}
    intents: list[dict[str, Any]] = []
    acct = _account()
    equity, buying_power = acct["equity"], acct["buying_power"]
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
            intent = _intent(tid, coin, decision, mode, equity, cap, buying_power)
            intent["proven"] = coin == proven_coin.get(tid)
            intents.append(intent)
    intents.sort(key=lambda x: x["confidence"], reverse=True)
    breaker = circuit_breaker(equity, acct.get("positions", 0))
    result = {"ok": True, "mode": mode, "leverage_cap": cap, "equity": equity,
              "buying_power": round(buying_power, 2), "breaker": breaker, "intents": intents}
    # Auto-execute only a signal on its proven market; cross-market signals are
    # surfaced as exploration for the heartbeat to act on (or prove next). The
    # circuit breaker can halt new entries (it never blocks closing risk).
    proven = [i for i in intents if i["proven"] and i["notional"] >= MIN_NOTIONAL]
    if args.execute and proven and mode != "hibernate" and breaker["allow_entry"]:
        top = proven[0]
        result["executed"] = _execute(top)
        if result["executed"].get("ok"):
            ref, _ = royalty_ref(load_technique(top["technique"]))
            pending = load_pending()
            pending[top["coin"]] = {"ref": ref, "technique": top["technique"], "opened_at": now_iso()}
            save_pending(pending)
            result["attribution"] = {"coin": top["coin"], "credit_to": ref}
    elif args.execute and not breaker["allow_entry"]:
        result["executed"] = {"skipped": f"circuit breaker: {breaker['reason']}"}
    elif args.execute:
        result["executed"] = {"skipped": "no proven-market signal (exploration intents not auto-traded)"}
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

    fk = sub.add_parser("fork", help="derive a new technique from a source to improve it")
    fk.add_argument("source", help="local id or pool <author>/<id>")
    fk.add_argument("--name", required=True)
    fk.add_argument("--claim", default="")
    fk.add_argument("--force", action="store_true")
    fk.set_defaults(fn=cmd_fork)

    ln = sub.add_parser("lineage", help="show a technique's ancestry chain")
    ln.add_argument("id")
    ln.set_defaults(fn=cmd_lineage)

    ro = sub.add_parser("royalty", help="attribute a realized PnL and credit the author")
    ro.add_argument("--coin", required=True)
    ro.add_argument("--pnl", required=True, help="realized PnL in USD (signed)")
    ro.add_argument("--ref", default=None, help="<author>/<id> if no pending trade")
    ro.set_defaults(fn=cmd_royalty)

    rep = sub.add_parser("reputation", help="author reputation from the royalty ledger")
    rep.add_argument("--author", default=None)
    rep.add_argument("--sync", action="store_true", help="anchor reputation onchain (dry-run)")
    rep.add_argument("--broadcast", action="store_true", help="with --sync, actually broadcast")
    rep.set_defaults(fn=cmd_reputation)

    tr = sub.add_parser("tournament", help="compete pooled techniques on one benchmark")
    tr.add_argument("--coins", default="BTC,ETH,SOL")
    tr.add_argument("--interval", default="4h")
    tr.add_argument("--limit", type=int, default=1200)
    tr.set_defaults(fn=cmd_tournament)

    cr = sub.add_parser("critique", help="adversarially re-prove a technique across markets")
    cr.add_argument("id")
    cr.add_argument("--coins", default=None, help="markets to test (default: BTC,ETH,SOL + claimed)")
    cr.add_argument("--interval", default=None)
    cr.add_argument("--limit", type=int, default=1200)
    cr.set_defaults(fn=cmd_critique)

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
