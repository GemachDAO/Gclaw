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
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
# Fallback universe — used only if intel.json has no live-discovered set. intel.js
# discovers the real universe from the venue (liquidity-filtered) each scan; forge reads
# that via _scan_universe() so the two never diverge and new listings are picked up.
SCAN_UNIVERSE = (
    "BTC",
    "ETH",
    "SOL",
    "xyz:NVDA",
    "xyz:TSLA",
    "xyz:SPCX",
    "xyz:AAPL",
    "xyz:AMZN",
    "xyz:GOLD",
    "xyz:SILVER",
    "xyz:BRENTOIL",
)

# Evidence gate.
MIN_OOS_SAMPLE = 20
# Live-bootstrap window: a technique keeps earning bounded half-size probes until it has
# this many real closes, so a genuine edge can accumulate a statistically-meaningful
# sample before the edge_real (full bootstrap CI > 0) gate benches it. The old window was
# a hardcoded 3 — but the bootstrap CI can only clear zero at n=3 if ALL THREE trades win,
# so a technique that took even one early loss was benched forever, never allowed the
# trades to recover: a sibling of the cold-start-forever death spiral (commit a7650dd).
# 12 matches the fitness loop's own "fair sample before pruning" bar (FITNESS_PRUNE_N).
MIN_LIVE_SAMPLE = 12
IS_FRACTION = 0.6
HORIZON = 4  # default bars held per backtest trade (mean-reversion holds short)
# Per-technique hold horizon (bars, 1h candles). doc 02 §1: momentum-stack's thin
# trend-continuation edge only clears the round-trip fee at a ~24h hold; at the old
# 4h hold it churns a sub-fee edge into a loss. Mean-reversion (stop-hunt-revert)
# wants the snap-back fast and decays to negative by 8-12h, so it stays short.
HORIZON_BY_TECHNIQUE = {"momentum-stack": 24, "stop-hunt-revert": 4}
# Per-side execution cost model (doc 02 §"Cross-cutting" 3). HL charges a MAKER rebate
# tier vs a TAKER fee; a resting limit that adds liquidity fills maker, a market/trigger
# order that crosses the book fills taker and eats slippage. Modelling both — instead of
# charging one flat taker cost on every fill — is what lets a real edge clear the bar:
# a limit ENTRY with an attached TP posts as maker/maker, so the round trip the gross
# edge must beat drops from ~15bp (taker/taker) to ~3bp, without lowering the gate.
#   maker: 0.015%/side fee, ~0 slippage (you set the price)   -> 1.5bp
#   taker: 0.045%/side fee + ~3bp slippage into the book/cascade -> ~7.5bp
TAKER_FEE = 0.00075  # taker fee (4.5bp) + realistic slippage (3bp) per side
MAKER_FEE = 0.00015  # maker fee (1.5bp), no slippage — you are the resting order
# Backtest execution mode must MATCH the live executor (hl_perp.js). Today the executor
# opens with isMarket:true (taker) with an attached TP/SL, so the entry is taker and the
# TP exit is maker; a stop-hit or time exit is taker. When maker-first limit entries land
# (assune-4yt), flip GCLAW_FORGE_MAKER_ENTRY=1 in BOTH the backtest and the executor
# together so the cost assumption never diverges from how fills actually happen.
def _maker_entry() -> bool:
    """True when entries are modelled as resting maker limits (assune-4yt), else taker."""
    return os.environ.get("GCLAW_FORGE_MAKER_ENTRY") == "1"


WARMUP = 50  # bars before EMA-50 / intel features are valid

# signal.py sandbox.
ALLOWED_IMPORTS = {"math", "statistics"}
BANNED_NAMES = {
    "eval",
    "exec",
    "open",
    "__import__",
    "compile",
    "input",
    "globals",
    "locals",
    "getattr",
    "setattr",
    "vars",
    "delattr",
    "memoryview",
    "__builtins__",
    "breakpoint",
    "help",
    "object",
    "type",
    "super",
    "classmethod",
    "staticmethod",
    "property",
}
# Attribute access that can pivot to builtins/globals even without a dunder name.
BANNED_ATTRS = {"format", "format_map", "mro", "__class__", "__globals__", "__subclasses__"}
# Frame/generator/code/coroutine/traceback introspection attributes have no leading
# dunder, so they slip past the "__"-prefix check and let a signal walk the call
# stack (gi_frame.f_back.f_builtins) to the real __import__ → RCE. Block by prefix.
BANNED_ATTR_PREFIXES = ("__", "gi_", "f_", "co_", "cr_", "tb_", "func_", "ag_")
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
    safe = (
        "abs",
        "min",
        "max",
        "round",
        "sum",
        "len",
        "range",
        "sorted",
        "enumerate",
        "zip",
        "map",
        "filter",
        "any",
        "all",
        "pow",
        "divmod",
        "float",
        "int",
        "bool",
        "str",
        "list",
        "dict",
        "tuple",
        "set",
        "abs",
        "isinstance",
    )
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
        r = rep.setdefault(
            a, {"author": a, "earned_usd": 0.0, "trades": 0, "wins": 0, "adopters": set()}
        )
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
    return datetime.now(UTC).isoformat(timespec="seconds")


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


def leverage_cap(goodwill: float | None = None) -> int:
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
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "forge_data.js failed")
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "forge_data.js error"))
    return data


def get_candles(coin: str, interval: str, limit: int) -> list[dict[str, float]]:
    return run_node(["candles", "--coin", coin, "--interval", interval, "--limit", str(limit)])[
        "candles"
    ]


def get_live_features(coins: list[str]) -> dict[str, Any]:
    return run_node(["features", "--coins", ",".join(coins)])["features"]


_INTEL: dict[str, Any] | None = None
# The rich senses intel.js scans each heartbeat — the offensive features the arsenal
# trades on (funding extremes, dislocation, regime, order-flow). Merged into live runs.
INTEL_KEYS = (
    "regime",
    "funding_z",
    "bb_z",
    "rsi",
    "atr_pct",
    "realized_vol_pct",
    "ema_stack",
    "ema_slope_pct",
    "efficiency",
    "flow_pressure",
    "premium",
    "btc_corr",
    "oi_delta",
)


def _intel_features() -> dict[str, Any]:
    """Per-coin feature vector from the latest intel.js scan (cached per process)."""
    global _INTEL
    if _INTEL is None:
        try:
            d = json.loads((gclaw_home() / "intel.json").read_text(encoding="utf-8"))
            _INTEL = d.get("intel", d) or {}
        except (OSError, ValueError):
            _INTEL = {}
    return _INTEL


def _scan_universe() -> tuple[str, ...]:
    """The markets the ensemble votes on. intel.js discovers these live from the venue
    (majors + liquid xyz commodity/stock perps) and writes them to intel.json, so the
    set tracks new listings like xyz:BRENTOIL without a hand-kept list. Falls back to
    the static SCAN_UNIVERSE only when intel.json has no discovered universe."""
    try:
        d = json.loads((gclaw_home() / "intel.json").read_text(encoding="utf-8"))
        universe = d.get("universe")
        if isinstance(universe, list) and universe:
            return tuple(str(c) for c in universe)
    except (OSError, ValueError):
        pass
    return SCAN_UNIVERSE


# ── Feature engineering ──────────────────────────────────────────────────────


def features_at(
    candles: list[dict[str, float]], i: int, coin: str, live: dict[str, Any] | None = None
) -> dict[str, Any]:
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
        f["mark"] = live.get("mark") or price
        f["prevDayPx"] = live.get("prevDayPx")
        # Live only: inject the intel.js scan's offensive senses so the arsenal can fire.
        iv = _intel_features().get(coin) or {}
        for k in INTEL_KEYS:
            if iv.get(k) is not None:
                f[k] = iv[k]
        if f.get("funding") is None and iv.get("funding_now") is not None:
            f["funding"] = iv["funding_now"]
        if iv.get("open_interest") is not None:
            f["oi"] = iv["open_interest"]
    else:
        # Backtest: reconstruct the price-derived intel.js feature vector so the
        # arsenal signals actually fire (doc 02 §"Cross-cutting" 3). Without this,
        # ema_stack/efficiency/bb_z/rsi/flow stayed at defaults and every signal
        # returned "flat", so "proven" was meaningless. Funding/OI/premium stay
        # None (live-only, no historical series here) — neither surviving technique
        # (momentum-stack, stop-hunt-revert) reads them, so this is exact for them.
        f.update(_intel_features_at(candles, i))
    return f


def _ema(values: list[float], n: int) -> float:
    """EMA over ``values`` seeded on the first element (mirrors intel.js ema())."""
    if not values:
        return 0.0
    k = 2 / (n + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def _wilder_rsi(closes: list[float], n: int = 14) -> float:
    """Canonical Wilder RSI (mirrors intel.js rsi())."""
    if len(closes) <= n:
        return 50.0
    avg_gain = avg_loss = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            avg_gain += d
        else:
            avg_loss -= d
    avg_gain /= n
    avg_loss /= n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (n - 1) + max(d, 0.0)) / n
        avg_loss = (avg_loss * (n - 1) + max(-d, 0.0)) / n
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def _wilder_atr_pct(candles: list[dict[str, float]], n: int = 14) -> float:
    """Canonical Wilder ATR as a percent of last close (mirrors intel.js atrPct())."""
    if len(candles) <= n:
        return 0.0

    def tr(c: dict[str, float], prev: dict[str, float]) -> float:
        return max(c["h"] - c["l"], abs(c["h"] - prev["c"]), abs(c["l"] - prev["c"]))

    atr = sum(tr(candles[i], candles[i - 1]) for i in range(1, n + 1)) / n
    for i in range(n + 1, len(candles)):
        atr = (atr * (n - 1) + tr(candles[i], candles[i - 1])) / n
    last = candles[-1]["c"]
    return (atr / last) * 100 if last else 0.0


def _efficiency_ratio(closes: list[float], n: int = 20) -> float:
    """Kaufman efficiency ratio: net move / total path (mirrors intel.js)."""
    if len(closes) <= n:
        return 0.0
    sl = closes[-n - 1 :]
    net = abs(sl[-1] - sl[0])
    path = sum(abs(sl[i] - sl[i - 1]) for i in range(1, len(sl)))
    return net / path if path else 0.0


def _classify_regime(efficiency: float, ema_stack: int) -> str:
    """Regime from efficiency + EMA stack (mirrors intel.js classifyRegime())."""
    trend_er = float(os.environ.get("GCLAW_TREND_ER") or 0.40)
    chop_er = float(os.environ.get("GCLAW_CHOP_ER") or 0.18)
    if efficiency >= trend_er:
        return "trend_up" if ema_stack >= 0 else "trend_down"
    if efficiency < chop_er:
        return "chop"
    return "range"


def _intel_features_at(candles: list[dict[str, float]], i: int) -> dict[str, Any]:
    """Reconstruct the price-derived intel.js feature vector at bar ``i``.

    Mirrors ``intel.js coinIntel`` 1:1 for every feature that derives from candles
    alone (the offensive senses the surviving arsenal trades on): ema_stack,
    ema_slope_pct, rsi, atr_pct, realized_vol_pct, bb_z, flow_pressure, efficiency,
    regime, plus mark/prevDayPx. Funding/OI/premium are live-only and stay absent.

    Args:
        candles: The OHLC series.
        i: The bar index to evaluate at (uses bars up to and including ``i``).

    Returns:
        A feature dict to merge into the bar's price-derived features.
    """
    closes = [c["c"] for c in candles[: i + 1]]
    last = candles[i]
    e9, e21, e50 = _ema(closes[-40:], 9), _ema(closes[-60:], 21), _ema(closes, 50)
    ema_stack = (1 if e9 > e21 else -1) + (1 if e21 > e50 else -1)
    win20 = closes[-20:]
    sd20 = statistics.stdev(win20) if len(win20) > 1 else 0.0
    bb_z = (closes[-1] - statistics.fmean(win20)) / sd20 if sd20 else 0.0
    span = last["h"] - last["l"]
    flow = ((last["c"] - last["l"]) / span - 0.5) * 2 if span > 0 else 0.0
    rets24 = [closes[k] / closes[k - 1] - 1 for k in range(max(1, len(closes) - 23), len(closes))]
    efficiency = _efficiency_ratio(closes)
    return {
        "ema_stack": ema_stack,
        "ema_slope_pct": ((e9 - e50) / e50) * 100 if e50 else 0.0,
        "rsi": round(_wilder_rsi(closes) * 10) / 10,
        "atr_pct": round(_wilder_atr_pct(candles[: i + 1]) * 100) / 100,
        "realized_vol_pct": round(statistics.pstdev(rets24) * 100 * 100) / 100 if rets24 else 0.0,
        "bb_z": round(bb_z * 100) / 100,
        "flow_pressure": round(flow * 100) / 100,
        "efficiency": round(efficiency * 100) / 100,
        "regime": _classify_regime(efficiency, ema_stack),
        "mark": last["c"],
        "prevDayPx": candles[i - 24]["c"] if i >= 24 else closes[0],
    }


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
        elif isinstance(node, ast.Attribute) and (
            node.attr in BANNED_ATTRS or node.attr.startswith(BANNED_ATTR_PREFIXES)
        ):
            violations.append(f"banned attribute access: {node.attr}")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "signal" for n in ast.walk(tree)):
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
    exec(compile(src, where, "exec"), namespace)
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


def load_pooled_signal(ref: str) -> Callable[[dict[str, Any]], Any] | None:
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


def call_signal(fn: Callable[[dict[str, Any]], Any], f: dict[str, Any]) -> dict[str, Any] | None:
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


def horizon_for(tid: str | None) -> int:
    """Bars a backtest trade is held for this technique (doc 02 §1).

    Momentum holds ~24h so its trend-continuation edge clears the round-trip fee;
    mean-reversion holds the default short window. Unknown/None techniques use the
    default ``HORIZON``.

    Args:
        tid: The technique id, or None when backtesting an anonymous signal.

    Returns:
        The hold horizon in bars.
    """
    return HORIZON_BY_TECHNIQUE.get(tid or "", HORIZON)


def round_trip_cost(stop_hit: bool) -> float:
    """Realistic round-trip cost for one backtest trade, by how each leg fills.

    The entry fills maker when modelled as a resting limit (``GCLAW_FORGE_MAKER_ENTRY``,
    assune-4yt) and taker otherwise. The exit fills taker when a stop is hit (a trigger
    that crosses the book, plus cascade slippage) and maker when the trade reaches its
    take-profit or time exit as a resting limit — but only if the entry was itself maker
    (i.e. we are in maker-limit mode); a market-executor run pays taker on the exit too.

    Args:
        stop_hit: Whether this trade exited by hitting its stop (a taker fill).

    Returns:
        The round-trip cost fraction to subtract from the trade's raw return.
    """
    fill_cost = MAKER_FEE if _maker_entry() else TAKER_FEE
    entry_cost = fill_cost
    # A stop is always a taker/trigger fill; a clean TP/time exit fills like the entry.
    exit_cost = TAKER_FEE if stop_hit else fill_cost
    return entry_cost + exit_cost


def trade_return(
    candles: list[dict[str, float]], i: int, is_long: bool, stop_pct: float, horizon: int = HORIZON
) -> float:
    """Forward return of a ``horizon``-bar trade opened at bar i close, with a stop."""
    entry = candles[i]["c"]
    stop = stop_pct / 100.0
    for h in range(1, horizon + 1):
        bar = candles[i + h]
        if is_long and bar["l"] <= entry * (1 - stop):
            return -stop - round_trip_cost(stop_hit=True)
        if not is_long and bar["h"] >= entry * (1 + stop):
            return -stop - round_trip_cost(stop_hit=True)
    exit_px = candles[i + horizon]["c"]
    raw = (exit_px / entry - 1) if is_long else (entry / exit_px - 1)
    return raw - round_trip_cost(stop_hit=False)


def score_window(
    candles: list[dict[str, float]],
    fn: Callable[[dict[str, Any]], Any],
    coin: str,
    lo: int,
    hi: int,
    horizon: int = HORIZON,
) -> dict[str, Any]:
    """Run the signal across bars [lo, hi) and summarise the trades.

    ``features_at`` (live=None here) now reconstructs the full price-derived intel
    feature vector per bar, so arsenal signals reading ema_stack/efficiency/bb_z/
    rsi/flow actually fire instead of seeing defaults.
    """
    rets: list[float] = []
    for i in range(lo, hi):
        decision = call_signal(fn, features_at(candles, i, coin))
        if not decision or decision["action"] == "flat":
            continue
        stop_pct = float(decision.get("stop_pct") or 0)
        if stop_pct <= 0:
            continue
        rets.append(trade_return(candles, i, decision["action"] == "long", stop_pct, horizon))
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


def _backtest_with(
    fn: Callable[[dict[str, Any]], Any],
    coin: str,
    interval: str,
    limit: int,
    tid: str | None = None,
) -> dict[str, Any]:
    """Walk-forward backtest of a signal fn; raises ValueError on thin data.

    ``tid`` selects the per-technique hold horizon (doc 02 §1: momentum holds ~24h,
    mean-reversion holds short). None → the default horizon.
    """
    horizon = horizon_for(tid)
    candles = get_candles(coin, interval, limit)
    if len(candles) < WARMUP + horizon + 60:
        raise ValueError(f"not enough candles ({len(candles)}) — widen --limit or --interval")
    last = len(candles) - horizon
    split = WARMUP + int((last - WARMUP) * IS_FRACTION)
    is_stats = score_window(candles, fn, coin, WARMUP, split, horizon)
    oos_stats = score_window(candles, fn, coin, split, last, horizon)
    proven = (
        oos_stats["n"] >= MIN_OOS_SAMPLE
        and oos_stats["expectancy"] > 0
        and is_stats["expectancy"] > 0
    )
    return {
        "coin": coin,
        "interval": interval,
        "bars": len(candles),
        "in_sample": is_stats,
        "out_of_sample": oos_stats,
        "proven": proven,
        "proved_at": now_iso(),
    }


def backtest(tid: str, coin: str, interval: str, limit: int) -> dict[str, Any]:
    """Walk-forward backtest: fit-free IS/OOS split, gate on out-of-sample edge."""
    try:
        return _backtest_with(load_signal(tid), coin, interval, limit, tid)
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
        json.dumps(tech, indent=2), encoding="utf-8"
    )


# ── Verbs ────────────────────────────────────────────────────────────────────


def cmd_draft(args: argparse.Namespace) -> dict[str, Any]:
    """Scaffold a new technique the agent then fills in (signal.py)."""
    tid = slugify(args.name)
    d = tech_dir(tid)
    if d.exists() and not args.force:
        die(f"technique '{tid}' exists — use --force to overwrite")
    d.mkdir(parents=True, exist_ok=True)
    tech = {
        "id": tid,
        "name": args.name,
        "kind": args.kind,
        "author": agent_id(),
        "parent": args.parent,
        "claim": args.claim or "",
        "status": "draft",
        "created_at": now_iso(),
    }
    save_technique(tech)
    (d / "SKILL.md").write_text(
        SKILL_TEMPLATE.format(
            name=args.name,
            kind=args.kind,
            claim=args.claim or "(state the edge)",
            author=tech["author"],
        ),
        encoding="utf-8",
    )
    if not (d / "signal.py").exists() or args.force:
        (d / "signal.py").write_text(SIGNAL_TEMPLATE, encoding="utf-8")
    return {
        "ok": True,
        "drafted": tid,
        "dir": str(d),
        "next": "edit signal.py, then: forge.py prove " + tid,
    }


def cmd_prove(args: argparse.Namespace) -> dict[str, Any]:
    card = backtest(args.id, args.coin, args.interval, args.limit)
    (tech_dir(args.id) / "card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    tech = load_technique(args.id)
    tech["status"] = "proven" if card["proven"] else "draft"
    tech["card"] = {
        "coin": card["coin"],
        "interval": card["interval"],
        "oos": card["out_of_sample"],
        "proven": card["proven"],
    }
    save_technique(tech)
    return {"ok": True, "id": args.id, "proven": card["proven"], "card": card}


def cmd_adopt(args: argparse.Namespace) -> dict[str, Any]:
    tech = load_technique(args.id)
    if tech.get("parent") and not (tech.get("critique") or {}).get("pass") and not args.force:
        die(
            f"'{args.id}' came from the pool — critique it first "
            f"(forge.py critique {args.id}) or --force"
        )
    if tech.get("status") != "proven" and not args.force:
        die(f"technique '{args.id}' is not proven — prove it first (or --force)")
    card = tech.get("card") or {}
    entry = {"id": args.id, "coin": card.get("coin", "BTC"), "interval": card.get("interval", "1h")}
    style = load_style()
    style["adopted"] = [e for e in style["adopted"] if e["id"] != args.id] + [entry]
    save_style(style)
    return {"ok": True, "adopted": style["adopted"]}


def cmd_author(args: argparse.Namespace) -> dict[str, Any]:
    """One gated R&D transaction — the scientist loop's single primitive.

    Validate an LLM-proposed signal body in the sandbox, backtest it walk-forward,
    and adopt it ONLY if it graduates on out-of-sample edge. Never touches the execute
    path: the LLM proposes strategy code, a deterministic backtest is the judge, and
    adoption merely joins the loadout — the live ``edge_real`` gate still governs real
    sizing, so a freshly-authored technique can do no more than a cold-start half-probe
    until live closes confirm it. The LLM never declares its own edge.

    Args:
        args: name, signal_file, claim, kind, coin, interval, limit, parent, force.

    Returns:
        A verdict dict: authored id, sandbox result, proven flag, adopted flag, card.
    """
    tid = slugify(args.name)
    body = Path(args.signal_file).read_text(encoding="utf-8")
    # Validate in the sandbox BEFORE writing anything the loop could pick up.
    violations = validate_signal_src(body)
    if violations:
        return {
            "ok": False, "authored": tid, "rejected": "sandbox",
            "violations": violations, "proven": False, "adopted": False,
        }
    d = tech_dir(tid)
    if d.exists() and not args.force:
        die(f"technique '{tid}' exists — use --force to revise it, or fork it under a new name")
    d.mkdir(parents=True, exist_ok=True)
    tech = {
        "id": tid, "name": args.name, "kind": args.kind, "author": agent_id(),
        "parent": args.parent, "claim": args.claim or "", "status": "draft",
        "created_at": now_iso(),
    }
    save_technique(tech)
    (d / "signal.py").write_text(body, encoding="utf-8")
    (d / "SKILL.md").write_text(
        SKILL_TEMPLATE.format(
            name=args.name, kind=args.kind,
            claim=args.claim or "(state the edge)", author=tech["author"],
        ),
        encoding="utf-8",
    )
    # Deterministic walk-forward judge — same gate as `prove`. Thin data is a clean
    # "not proven", not a crash, so the scientist loop never breaks the heartbeat.
    try:
        card = backtest(tid, args.coin, args.interval, args.limit)
    except ValueError as exc:
        return {"ok": True, "authored": tid, "proven": False, "adopted": False,
                "verdict": f"could not backtest ({exc}); kept as draft"}
    (d / "card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    tech["status"] = "proven" if card["proven"] else "draft"
    tech["card"] = {
        "coin": card["coin"], "interval": card["interval"],
        "oos": card["out_of_sample"], "proven": card["proven"],
    }
    save_technique(tech)
    adopted = False
    if card["proven"]:
        style = load_style()
        entry = {"id": tid, "coin": card["coin"], "interval": card["interval"]}
        style["adopted"] = [e for e in style["adopted"] if e["id"] != tid] + [entry]
        save_style(style)
        adopted = True
    return {
        "ok": True, "authored": tid, "proven": card["proven"], "adopted": adopted, "card": card,
        "verdict": (
            "adopted — graduated on out-of-sample edge"
            if adopted else "kept as draft — did not clear the OOS gate; fork and improve it"
        ),
    }


def cmd_drop(args: argparse.Namespace) -> dict[str, Any]:
    style = load_style()
    style["adopted"] = [e for e in style["adopted"] if e["id"] != args.id]
    save_style(style)
    return {"ok": True, "adopted": style["adopted"]}


# ── Auto-prove: grow the tradeable surface to match the discovered universe ───────
# Arsenal techniques are STRATEGIES, not coin-specific models — a funding-fade proven on
# BTC may also have edge on oil. Without this, execution stays locked to the birth arsenal's
# coins while the agent watches the rest of its (dynamically discovered) universe light up
# but can't trade it. This registry decouples "validated to trade" from the adopted list,
# so the proven surface grows as backtests confirm edge on new markets.
PROVEN_MARKETS_FILE = "proven_markets.json"
AUTOPROVE_BUDGET = 6  # backtests per heartbeat — bounded cost
AUTOPROVE_COOLDOWN_H = 12.0  # don't re-attempt a failing (technique, coin) for this long
AUTOPROVE_LIMIT = 1000  # candles per backtest (matches `prove`)


def _proven_markets_path() -> Path:
    return gclaw_home() / "forge" / PROVEN_MARKETS_FILE


def load_proven_markets() -> dict[str, Any]:
    """Validated (technique, coin) pairs the agent may trade beyond its native arsenal
    coins, plus a cooldown ledger of recent backtest attempts."""
    try:
        data = json.loads(_proven_markets_path().read_text(encoding="utf-8"))
        return {"pairs": data.get("pairs", []), "attempts": data.get("attempts", {})}
    except (OSError, ValueError):
        return {"pairs": [], "attempts": {}}


def proven_pairs(reg: dict[str, Any] | None = None) -> set[tuple[str, str]]:
    """The set of (technique, coin) pairs proven on markets outside the native arsenal."""
    reg = reg if reg is not None else load_proven_markets()
    return {(p["technique"], p["coin"]) for p in reg.get("pairs", [])}


def _attempt_age_h(iso: str | None) -> float:
    if not iso:
        return 1e9
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(iso)).total_seconds() / 3600.0
    except ValueError:
        return 1e9


def cmd_autoprove(args: argparse.Namespace) -> dict[str, Any]:
    """Backtest each adopted strategy across the freshly-discovered liquid markets and
    register the pairs with real out-of-sample edge — so the agent can TRADE what it
    discovers, not just watch it. Budgeted per run, with a cooldown so a failing pair
    isn't re-tried every cycle. The native arsenal coins are already tradeable, so skip them."""
    adopted = load_style().get("adopted", [])
    intel = _intel_features()
    universe = [c for c in intel if intel.get(c)]
    if not adopted or not universe:
        return {"ok": True, "skipped": "no adopted techniques or no intel scan yet"}
    reg = load_proven_markets()
    have = proven_pairs(reg)
    attempts = reg["attempts"]
    native = {e["coin"] for e in adopted}
    cooldown = float(os.environ.get("GCLAW_AUTOPROVE_COOLDOWN_H") or AUTOPROVE_COOLDOWN_H)
    gap: list[tuple[bool, str, str, str]] = []
    for e in adopted:
        tid, interval = e["id"], e.get("interval", "1h")
        for coin in universe:
            if coin in native or (tid, coin) in have:
                continue  # native coins already tradeable; proven pairs already done
            if _attempt_age_h(attempts.get(f"{tid}|{coin}")) < cooldown:
                continue  # still cooling down from a recent failed attempt
            tradeable = intel.get(coin, {}).get("regime") not in (None, "chop")
            gap.append((not tradeable, tid, interval, coin))  # tradeable-now first
    gap.sort(key=lambda g: g[0])
    budget = int(getattr(args, "budget", None) or AUTOPROVE_BUDGET)
    tried, proved = 0, []
    for _pri, tid, interval, coin in gap[:budget]:
        attempts[f"{tid}|{coin}"] = now_iso()  # record the attempt regardless of outcome
        try:
            card = _backtest_with(load_signal(tid), coin, interval, AUTOPROVE_LIMIT, tid)
        except (ValueError, OSError, KeyError):
            continue  # thin data / bad market — skip, the cooldown stops a re-try storm
        tried += 1
        if card.get("proven"):
            reg["pairs"].append(
                {
                    "technique": tid,
                    "coin": coin,
                    "interval": interval,
                    "oos_n": card["out_of_sample"]["n"],
                    "expectancy": round(card["out_of_sample"]["expectancy"], 6),
                    "at": now_iso(),
                }
            )
            proved.append(f"{tid}@{coin}")
    reg["attempts"] = attempts
    _proven_markets_path().parent.mkdir(parents=True, exist_ok=True)
    _proven_markets_path().write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "tried": tried, "newly_proven": proved, "proven_markets": len(reg["pairs"])}


def cmd_list(_args: argparse.Namespace) -> dict[str, Any]:
    techs = []
    for d in sorted((forge_dir() / "techniques").glob("*/")):
        t = json.loads((d / "technique.json").read_text(encoding="utf-8"))
        techs.append(
            {
                "id": t["id"],
                "kind": t["kind"],
                "status": t["status"],
                "author": t["author"],
                "claim": t.get("claim", "")[:60],
            }
        )
    return {"ok": True, "adopted": load_style()["adopted"], "techniques": techs}


def cmd_show(args: argparse.Namespace) -> dict[str, Any]:
    tech = load_technique(args.id)
    card_path = tech_dir(args.id) / "card.json"
    if card_path.exists():
        tech["card_full"] = json.loads(card_path.read_text(encoding="utf-8"))
    return {"ok": True, "technique": tech}


IPFS_GATEWAY = os.environ.get("IPFS_GATEWAY", "https://ipfs.io/ipfs/")


def _pin_ipfs(obj: dict[str, Any]) -> str | None:
    """Pin a technique bundle to IPFS via Pinata (None without PINATA_JWT)."""
    jwt = os.environ.get("PINATA_JWT")
    if not jwt:
        return None
    import urllib.error
    import urllib.request

    body = json.dumps(
        {"pinataContent": obj, "pinataMetadata": {"name": f"gclaw-tech-{obj.get('id', '')}"}}
    ).encode()
    req = urllib.request.Request(
        "https://api.pinata.cloud/pinning/pinJSONToIPFS",
        data=body,
        headers={"content-type": "application/json", "authorization": f"Bearer {jwt}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read()).get("IpfsHash")
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _fetch_ipfs(cid: str) -> dict[str, Any] | None:
    import urllib.request

    try:
        with urllib.request.urlopen(IPFS_GATEWAY + cid, timeout=20) as r:
            return json.loads(r.read())
    except (OSError, ValueError):
        return None


def _record_published(ref: str, manifest: dict[str, Any], cid: str | None) -> None:
    """Index a published technique so the beacon can advertise it onchain."""
    path = gclaw_home() / "published.json"
    try:
        idx = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        idx = {}
    card = manifest.get("card") or {}
    idx[ref] = {
        "ref": ref,
        "market": f"{card.get('coin', '')}/{card.get('interval', '')}",
        "score": round(manifest.get("score", 0), 4),
        "oos_n": (card.get("oos") or {}).get("n"),
        "cid": cid,
        "claim": manifest.get("claim", "")[:80],
    }
    path.write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")


def cmd_publish(args: argparse.Namespace) -> dict[str, Any]:
    """Publish a proven technique: local pool + IPFS pin + onchain advertisement."""
    tech = load_technique(args.id)
    if tech.get("status") != "proven" and not args.force:
        die(f"only proven techniques can be published — prove '{args.id}' first (or --force)")
    card = tech.get("card") or {}
    author = tech.get("author", agent_id())
    dest = genepool_dir() / author / args.id
    dest.mkdir(parents=True, exist_ok=True)
    signal_src = (tech_dir(args.id) / "signal.py").read_text(encoding="utf-8")
    shutil.copy2(tech_dir(args.id) / "signal.py", dest / "signal.py")
    manifest = {
        "id": args.id,
        "name": tech.get("name", args.id),
        "kind": tech.get("kind", "edge"),
        "author": author,
        "parent": tech.get("parent"),
        "lineage": tech.get("lineage", []),
        "claim": tech.get("claim", ""),
        "card": card,
        "score": edge_score(card.get("oos") or {}),
        "content_hash": content_hash(args.id),
        "published_at": now_iso(),
    }
    # Pin the bundle (metadata + source) to IPFS so peers can discover + pull it.
    # The source travels as DATA only — pull lands it as an untrusted draft that
    # must be re-proven locally; it is never auto-executed.
    cid = _pin_ipfs({**manifest, "signal_src": signal_src})
    manifest["cid"] = cid
    ref = f"{author}/{args.id}"
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _record_published(ref, manifest, cid)
    return {
        "ok": True,
        "published": ref,
        "score": manifest["score"],
        "cid": cid,
        "gateway": (IPFS_GATEWAY + cid) if cid else None,
        "pool": str(genepool_dir()),
    }


def _pool_manifests() -> list[dict[str, Any]]:
    out = []
    for mpath in genepool_dir().glob("*/*/manifest.json"):
        try:
            out.append(json.loads(mpath.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def _peer_published() -> list[dict[str, Any]]:
    """Read the family's published techniques straight from peers' onchain cards
    (peers.js wrote them into peers_roster.json). Data only — no code is fetched
    or run here; a row carries the IPFS cid for an explicit, later `pull`.
    """
    roster = []
    try:
        roster = json.loads((gclaw_home() / "peers_roster.json").read_text(encoding="utf-8")).get(
            "roster", []
        )
    except (OSError, ValueError):
        return []
    rows = []
    for a in roster:
        for p in a.get("published") or []:
            rows.append(
                {
                    "ref": p.get("ref"),
                    "author": str(a.get("id")),
                    "from": a.get("name"),
                    "market": p.get("market"),
                    "score": p.get("score", 0),
                    "oos_n": p.get("oos_n"),
                    "cid": p.get("cid"),
                    "claim": p.get("claim", ""),
                    "source": "onchain",
                }
            )
    return rows


def cmd_discover(args: argparse.Namespace) -> dict[str, Any]:
    """Browse the gene pool, ranked by confidence-weighted out-of-sample edge."""
    if getattr(args, "peers", False):
        rows = sorted(_peer_published(), key=lambda r: r.get("score", 0), reverse=True)
        return {
            "ok": True,
            "source": "onchain peers",
            "count": len(rows),
            "techniques": rows[: args.limit],
        }
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
    for m in items[: args.limit]:
        card = m.get("card") or {}
        ref = f"{m['author']}/{m['id']}"
        rows.append(
            {
                "ref": ref,
                "score": m.get("score", 0),
                "author_reputation": rep.get(m["author"], {}).get("score", 0.0),
                "tournament_rank": board["ranks"].get(ref),
                "rank": round(combined(m), 6),
                "kind": m.get("kind"),
                "market": f"{card.get('coin', '')}/{card.get('interval', '')}",
                "oos": card.get("oos", {}),
                "author": m["author"] + (" (you)" if m["author"] == mine else ""),
                "claim": m.get("claim", "")[:60],
            }
        )
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
    # Cross-machine: if not in the local pool, fetch the bundle from IPFS by cid
    # into the local pool first. The source is DATA — it lands as a draft below.
    if not (src / "manifest.json").exists() and getattr(args, "cid", None):
        bundle = _fetch_ipfs(args.cid)
        if not bundle or "signal_src" not in bundle:
            die(f"could not fetch technique bundle from IPFS cid {args.cid}")
        src.mkdir(parents=True, exist_ok=True)
        (src / "signal.py").write_text(bundle["signal_src"], encoding="utf-8")
        (src / "manifest.json").write_text(
            json.dumps({k: v for k, v in bundle.items() if k != "signal_src"}, indent=2),
            encoding="utf-8",
        )
    if not (src / "manifest.json").exists():
        die(f"no pooled technique '{args.ref}' (pass --cid <cid> to fetch from IPFS)")
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    local_id = args.as_ or pid
    d = tech_dir(local_id)
    if d.exists() and not args.force:
        die(f"local technique '{local_id}' exists — use --as <name> or --force")
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / "signal.py", d / "signal.py")
    tech = {
        "id": local_id,
        "name": manifest.get("name", local_id),
        "kind": manifest.get("kind", "edge"),
        "author": agent_id(),
        "parent": args.ref,
        "lineage": (manifest.get("lineage") or []) + [args.ref],
        "origin": manifest,
        "claim": manifest.get("claim", ""),
        "status": "draft",
        "created_at": now_iso(),
    }
    save_technique(tech)
    (d / "SKILL.md").write_text(
        SKILL_TEMPLATE.format(
            name=tech["name"], kind=tech["kind"], claim=tech["claim"], author=tech["author"]
        ),
        encoding="utf-8",
    )
    integrity = "ok" if content_hash(local_id) == manifest.get("content_hash") else "MISMATCH"
    return {
        "ok": True,
        "pulled": args.ref,
        "local": local_id,
        "integrity": integrity,
        "next": f"re-prove before trusting: forge.py prove {local_id} --coin <c> --interval <i>",
    }


def cmd_royalty(args: argparse.Namespace) -> dict[str, Any]:
    """Attribute a realized PnL to the technique that opened it and credit its author.

    Called on close: looks up the pending forge trade for the coin (set by
    ``run --execute``), credits ROYALTY_PCT of any positive PnL to the origin
    author (never to yourself), and appends to the shared royalty ledger.
    """
    pending = load_pending()
    rec = pending.get(args.coin)
    # Fall back to the adopted technique trading this coin, so trades opened via
    # MCP (not `run --execute`, which sets pending) still credit the right author.
    fallback = None
    if not rec and not args.ref:
        adopted = next(
            (e for e in load_style().get("adopted", []) if e.get("coin") == args.coin), None
        )
        if adopted:
            fallback, _ = royalty_ref(load_technique(adopted["id"]))
    ref = (rec or {}).get("ref") or args.ref or fallback
    if not ref:
        if getattr(args, "auto", False):
            return {
                "ok": True,
                "attributed": None,
                "note": f"no technique attributable to {args.coin}",
            }
        die(
            f"no pending or adopted technique on {args.coin} — pass --ref <author>/<id> to attribute manually"
        )
    author = ref.split("/", 1)[0] if "/" in ref else ref
    adopter = agent_id()
    pnl = float(args.pnl)
    royalty = round(max(0.0, pnl) * ROYALTY_PCT / 100, 6) if author != adopter else 0.0
    entry = {
        "ts": now_iso(),
        "technique": ref,
        "author": author,
        "adopter": adopter,
        "coin": args.coin,
        "pnl_usd": round(pnl, 6),
        "royalty_usd": royalty,
    }
    with royalty_ledger().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    # Darwinian feedback: move the contributing technique's loadout weight by its
    # realized edge and teach the regime router (best-effort; never blocks attribution).
    fitness = None
    local_tid = (rec or {}).get("technique") or (ref.split("/", 1)[1] if "/" in ref else ref)
    if local_tid:
        try:
            fitness = _update_fitness(
                local_tid,
                pnl,
                float((rec or {}).get("risk_usd") or 0.0),
                (rec or {}).get("regime", "range"),
            )
        except Exception as exc:
            fitness = {"skipped": str(exc)[:100]}
    if rec:
        pending.pop(args.coin, None)
        save_pending(pending)
    return {"ok": True, "attributed": entry, "fitness": fitness}


def _sync_reputation(broadcast: bool) -> dict[str, Any]:
    mode = "broadcast" if broadcast else "dry-run"
    try:
        proc = subprocess.run(
            ["node", str(SCRIPT_DIR / "erc8004_reputation.js"), mode],
            capture_output=True,
            text=True,
            timeout=120,
        )
        tail = (proc.stdout or proc.stderr).strip().splitlines()[-1:] or [""]
        return {"ok": proc.returncode == 0, "mode": mode, "detail": tail[0][:200]}
    except Exception as exc:
        return {
            "ok": False,
            "mode": mode,
            "note": "reputation sync unavailable",
            "error": str(exc)[:120],
        }


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
                card = _backtest_with(fn, coin, args.interval, args.limit, m.get("id"))
            except ValueError:
                continue
            per_coin[coin] = edge_score(card["out_of_sample"])
        if per_coin:
            standings.append(
                {
                    "ref": ref,
                    "author": m["author"],
                    "benchmark_score": round(sum(per_coin.values()), 6),
                    "per_coin": per_coin,
                }
            )
    standings.sort(key=lambda s: s["benchmark_score"], reverse=True)
    for i, s in enumerate(standings, 1):
        s["rank"] = i
    board = {
        "benchmark": {"coins": coins, "interval": args.interval},
        "standings": standings,
        "at": now_iso(),
    }
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
    tech = {
        "id": newid,
        "name": args.name,
        "kind": src_meta.get("kind", "edge"),
        "author": agent_id(),
        "parent": args.source,
        "lineage": parent_lineage + [args.source],
        "claim": args.claim or src_meta.get("claim", ""),
        "status": "draft",
        "created_at": now_iso(),
    }
    save_technique(tech)
    (d / "SKILL.md").write_text(
        SKILL_TEMPLATE.format(
            name=args.name, kind=tech["kind"], claim=tech["claim"], author=tech["author"]
        ),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "forked": newid,
        "from": args.source,
        "lineage": tech["lineage"],
        "next": f"improve signal.py, then: forge.py prove {newid}",
    }


def cmd_lineage(args: argparse.Namespace) -> dict[str, Any]:
    """Show a technique's ancestry chain (oldest → this)."""
    tech = load_technique(args.id)
    chain = list(tech.get("lineage") or []) + [f"{tech.get('author')}/{args.id}"]
    return {"ok": True, "id": args.id, "depth": len(chain) - 1, "lineage": chain}


def _critique_markets(claimed: str | None) -> list[str]:
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
    coins = (
        [c.strip() for c in args.coins.split(",")]
        if args.coins
        else _critique_markets(claimed_coin)
    )
    markets: dict[str, Any] = {}
    claimed_card: dict[str, Any] | None = None
    for coin in coins:
        card = backtest(args.id, coin, interval, args.limit)
        markets[coin] = {
            "proven": card["proven"],
            "oos_exp": card["out_of_sample"]["expectancy"],
            "n": card["out_of_sample"]["n"],
        }
        if coin == claimed_coin:
            claimed_card = card
    replicated = bool(claimed_coin and markets.get(claimed_coin, {}).get("proven"))
    positives = sum(1 for r in markets.values() if r["oos_exp"] > 0 and r["n"] >= MIN_OOS_SAMPLE)
    robust = positives >= math.ceil(len(markets) / 2)
    verdict = {
        "replicated": replicated,
        "robust": robust,
        "pass": bool(replicated and robust),
        "markets": markets,
        "interval": interval,
        "critic": agent_id(),
        "at": now_iso(),
    }
    (tech_dir(args.id) / "critique.json").write_text(
        json.dumps(verdict, indent=2), encoding="utf-8"
    )
    tech["critique"] = verdict
    if replicated and claimed_card is not None:
        (tech_dir(args.id) / "card.json").write_text(
            json.dumps(claimed_card, indent=2), encoding="utf-8"
        )
        tech["status"] = "proven"
        tech["card"] = {
            "coin": claimed_card["coin"],
            "interval": claimed_card["interval"],
            "oos": claimed_card["out_of_sample"],
            "proven": True,
        }
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
        proc = subprocess.run(
            ["node", str(SCRIPT_DIR / "hl_perp.js"), "status"],
            capture_output=True,
            text=True,
            timeout=90,
        )
        st = json.loads(proc.stdout.strip().splitlines()[-1])
        equity = float(st.get("equity") or st.get("spotUsdc") or st.get("accountValue") or 0)
        return {
            "equity": equity,
            "buying_power": float(st.get("buyingPower") or equity),
            "positions": len(st.get("positions") or []),
        }
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
    # A failed/rate-limited status read passes equity<=0; never trip (or move the
    # high-water mark) on a bad read — that would falsely flatten / alert at 100%.
    if equity <= 0:
        return {**state, "tripped": bool(state.get("tripped")), "skipped": "no equity read"}
    # Cap how fast the high-water mark can climb from a SINGLE read: real equity can't
    # jump >20% in one heartbeat (per-trade risk is a few %), so a larger spike is almost
    # certainly a bad/duplicated read. Capping the rise stops one transient mis-read from
    # poisoning the HWM and permanently false-tripping the breaker — exactly what a brief
    # equity double-count (2x) did. Legit growth catches up over reads.
    prev_hwm = float(state.get("hwm", 0) or 0)
    hwm = max(prev_hwm, min(equity, prev_hwm * 1.20)) if prev_hwm > 0 else equity
    drawdown_pct = round((1 - equity / hwm) * 100, 2) if hwm > 0 else 0.0
    reason = None
    if drawdown_pct >= MAX_DRAWDOWN_PCT:
        reason = f"drawdown {drawdown_pct}% ≥ {MAX_DRAWDOWN_PCT}% from high-water ${hwm:.2f}"
    elif n_positions >= MAX_OPEN_POSITIONS:
        reason = f"{n_positions} open positions ≥ {MAX_OPEN_POSITIONS} cap"
    state.update(
        {
            "hwm": round(hwm, 2),
            "equity": round(equity, 2),
            "drawdown_pct": drawdown_pct,
            "positions": n_positions,
            "tripped": bool(reason),
            "reason": reason,
            "at": now_iso(),
        }
    )
    try:
        path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return {
        "allow_entry": not reason,
        "reason": reason,
        "drawdown_pct": drawdown_pct,
        "hwm": round(hwm, 2),
    }


def _size_via_brain(
    equity: float, price: float, atr_pct: float, edge: dict[str, Any], confidence: float
) -> dict[str, Any]:
    """Run sizing.py to get notional + ATR-stop from the risk brain (doc 04 §3b).

    Notional and stop fall out of vol-target + sample-shrunk fractional Kelly, fed
    the technique's live regime-matched expectancy (win_rate/payoff/trades) and
    current goodwill. Returns the parsed sizing.py JSON, or {} on failure.
    """
    sz = subprocess.run(
        [
            "uv", "run", "--no-project", "python3", str(SCRIPT_DIR / "sizing.py"), "size",
            "--equity", str(equity),
            "--price", str(price),
            "--atr-pct", str(atr_pct),
            "--win-rate", str(edge.get("win_rate", 0.5)),
            "--payoff", str(edge.get("payoff", 1.5)),
            "--trades", str(edge.get("trades", 0)),
            "--goodwill", str(float(load_metabolism().get("goodwill", 0) or 0)),
            "--confidence", str(confidence),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    try:
        return json.loads(sz.stdout[sz.stdout.find("{") :])
    except (ValueError, OSError):
        return {}


def _intent(
    tid: str,
    coin: str,
    decision: dict[str, Any],
    mode: str,
    equity: float,
    cap: int,
    buying_power: float,
    intel: dict[str, Any] | None = None,
    edge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Turn a signal decision into a cap-enforced order intent (cap = earned ceiling).

    Notional AND stop come from ``sizing.py`` (vol-target + sample-shrunk Kelly), not
    a flat ``RISK_PCT × equity ÷ stop`` fraction: size falls out of the ATR stop and
    the technique's live regime-matched edge. The buying-power/margin clamp and the
    $11 min-notional floor are preserved; riskguard.js stays a backstop.

    Args:
        tid: The originating technique id.
        coin: The market.
        decision: The ensemble decision (action/confidence/leverage/stop_pct).
        mode: Survival mode (hibernate suppresses entry upstream).
        equity: Account equity.
        cap: The earned leverage ceiling.
        buying_power: Free collateral for margin.
        intel: Live intel features for this coin (atr_pct, price).
        edge: Memory expectancy (win_rate/payoff/trades) for Kelly sizing.

    Returns:
        The order intent dict.
    """
    leverage = max(1, min(cap, int(decision.get("leverage") or cap)))
    intel = intel or {}
    edge = edge or {}
    confidence = float(decision.get("confidence") or 0.6)
    # Defense in depth: a decision that did not commit a stop has not committed risk,
    # so it is never sized — even if it reached here past the _coin_votes/backtest
    # skip. The live stop below is ATR-derived, but the DECISION must carry one first.
    if float(decision.get("stop_pct") or 0) <= 0:
        return {
            "technique": tid, "coin": coin, "side": decision["action"], "leverage": leverage,
            "sl_pct": 0.0, "confidence": float(decision.get("confidence") or 0),
            "notional": 0, "risk_usd": 0.0, "reason": str(decision.get("reason") or "")[:120],
        }
    atr_pct = float(intel.get("atr_pct") or decision.get("stop_pct") or 1.0)
    price = float(intel.get("price") or decision.get("price") or 0)
    s = _size_via_brain(equity, price, atr_pct, edge, confidence)
    notional = float(s.get("notional_usd") or 0)
    stop_pct = float(s.get("stop_distance_pct") or decision.get("stop_pct") or 0)
    risk_usd = float(s.get("risk_usd") or 0)
    # Survival sizing: sizing.py is the brain, but shrink its notional as life energy
    # (GMAC) falls — bet smaller when low, never refuse the +EV setup (it's a Kelly
    # fraction of bankroll, not a veto). Applied to size only, not the entry decision.
    health = _health_size_mult(load_metabolism())
    notional, risk_usd = notional * health, risk_usd * health
    # Margin = notional / leverage must fit the free collateral (95% headroom for fees).
    max_notional = max(0.0, buying_power * 0.95) * leverage
    if notional > max_notional:
        notional = max_notional
    if notional < MIN_NOTIONAL:
        notional = 0
    return {
        "technique": tid,
        "coin": coin,
        "side": decision["action"],
        "leverage": leverage,
        "sl_pct": round(stop_pct, 3),
        "confidence": float(decision.get("confidence") or 0),
        "notional": round(notional, 2),
        "risk_usd": round(risk_usd, 2),
        "reason": str(decision.get("reason") or "")[:120],
    }


def _regime_stats() -> dict[str, Any]:
    """Learned per-(technique, regime) expectancy (Meta-1 router data). The fitness
    loop writes this on royalty; absent → static gates only. Best-effort."""
    try:
        return json.loads((forge_dir() / "regime_stats.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


FITNESS_ETA = 0.15  # per-trade multiplicative-weights step (Hedge)
FITNESS_ALPHA = 0.3  # EWMA smoothing for expectancy + regime edge
FITNESS_PRUNE_W = 0.05  # weight at/below which a technique is dropped …
FITNESS_PRUNE_N = 12  # … but only after a fair sample (no death on variance)
ROUTER_MIN_N = 8  # learned regime nudge needs this many trades in the regime


def _gate(tid: str, regime: str, rstats: dict[str, Any]) -> float:
    """Eligibility of a technique in this regime ∈ [0.05, 1.2]. Static prior from the
    technique's declared `regimes`, nudged by its learned edge once the fitness loop
    has recorded ≥ROUTER_MIN_N trades there (Meta-1 regime router)."""
    try:
        regimes = load_technique(tid).get("regimes")
    except SystemExit:
        regimes = None
    static = float(regimes.get(regime, 0.15)) if isinstance(regimes, dict) else 1.0
    learned = (rstats.get(tid) or {}).get(regime)
    if isinstance(learned, dict) and int(learned.get("n", 0)) >= ROUTER_MIN_N:
        static *= 1.0 + 0.4 * math.tanh(float(learned.get("e", 0.0)))
    return max(0.05, min(1.2, static))


def _update_fitness(tid: str, pnl: float, risk_usd: float, regime: str) -> dict[str, Any]:
    """Darwinian feedback on a closed trade: move the technique's weight by its realized
    edge (winners compound, losers decay → pruned), and teach the regime router.

    Normalised return r = pnl / risk_at_entry (clamped); weight *= exp(η·r) bounded to
    [0.05, 1.0]; a technique below the floor after a fair sample is dropped from the
    loadout. R[tid][regime] tracks the EWMA edge per regime for the Meta-1 router.
    """
    r = (
        pnl / risk_usd
        if risk_usd and risk_usd > 0
        else (1.0 if pnl > 0 else -1.0 if pnl < 0 else 0.0)
    )
    r = max(-3.0, min(3.0, r))
    style = load_style()
    out: dict[str, Any] = {"technique": tid, "r": round(r, 3)}
    for e in style.get("adopted", []):
        if e.get("id") != tid:
            continue
        e["e"] = round((1 - FITNESS_ALPHA) * float(e.get("e", 0.0)) + FITNESS_ALPHA * r, 4)
        e["trades"] = int(e.get("trades", 0)) + 1
        e["weight"] = round(
            max(FITNESS_PRUNE_W, min(1.0, float(e.get("weight", 1.0)) * math.exp(FITNESS_ETA * r))),
            4,
        )
        out["weight"], out["trades"] = e["weight"], e["trades"]
        if e["weight"] <= FITNESS_PRUNE_W and e["trades"] >= FITNESS_PRUNE_N:
            style["adopted"] = [x for x in style["adopted"] if x is not e]
            out["pruned"] = True
        break
    save_style(style)
    rs = _regime_stats()
    cell = rs.setdefault(tid, {}).setdefault(regime, {"e": 0.0, "n": 0})
    cell["e"] = round((1 - FITNESS_ALPHA) * float(cell.get("e", 0.0)) + FITNESS_ALPHA * r, 4)
    cell["n"] = int(cell.get("n", 0)) + 1
    (forge_dir() / "regime_stats.json").write_text(
        json.dumps(rs, indent=2) + "\n", encoding="utf-8"
    )
    out["regime_edge"] = {regime: cell}
    return out


def _recent_expectancy() -> float:
    """EWMA of recent settled PnL signs — the 'hot/cold hand' for the Meta-2 scaler."""
    try:
        rows = [
            json.loads(line)
            for line in (gclaw_home() / "journal.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, ValueError):
        return 0.0
    settles = [r for r in rows if r.get("event") == "settle"][-12:]
    e = 0.0
    for r in settles:
        pnl = float(r.get("pnl") or 0)
        e = 0.7 * e + 0.3 * (1.0 if pnl > 0 else -1.0 if pnl < 0 else 0.0)
    return e


def _conviction_scaler(_meta: dict[str, Any]) -> float:
    """Meta-2 entry breath: ease off a cold hand, press a hot one ∈ [0.7, 1.3]. Recent
    edge ONLY — survival (GMAC) scales SIZE, not whether to take an edge. Gating entry on
    low life-energy was pro-cyclical (low GMAC → higher floor → fewer trades → can't earn
    → lower GMAC), a death spiral; a low-energy creature should keep taking its +EV
    setups, just smaller (Kelly bets a fraction of bankroll, it doesn't sit out)."""
    return max(0.7, min(1.3, 1.0 + 0.3 * math.tanh(_recent_expectancy())))


def _health_size_mult(meta: dict[str, Any]) -> float:
    """Survival sizing: shrink position SIZE as life energy (GMAC) falls ∈ [0.5, 1.0].
    Applied to risk, never to the entry decision — bet smaller when low, never refuse."""
    seed = float(meta.get("seed", 1000) or 1000)
    if not seed:
        return 1.0
    return max(0.5, min(1.0, 0.5 + 0.5 * (float(meta.get("gmac_balance", seed) or seed) / seed)))


def _weighted_median(pairs: list[tuple[float, float]]) -> float:
    """Weighted median of (value, weight) — robust stop across contributors."""
    pairs = sorted((v, w) for v, w in pairs if w > 0)
    if not pairs:
        return 0.0
    half = sum(w for _, w in pairs) / 2.0
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= half:
            return v
    return pairs[-1][0]


def _combine(
    votes: list[dict[str, Any]], regime: str, caps: dict[str, float], scaler: float
) -> dict[str, Any] | None:
    """Gated weighted ensemble → one decision for a coin, or None.

    Each vote is signed conviction × weight × regime-gate. Techniques that agree
    reinforce; opposers net out. The chop guard, agreement floor, and conviction
    floor (all genome-tuned) keep the family from overtrading or fading a trend.
    """
    if regime == "chop" or not votes:
        return None  # DNA invariant: no entries in chop
    total = sum(v["v"] for v in votes)
    mobilized = sum(abs(v["v"]) for v in votes)
    if mobilized == 0:
        return None
    pos = sum(v["v"] for v in votes if v["v"] > 0)
    neg = -sum(v["v"] for v in votes if v["v"] < 0)
    agree = max(pos, neg) / mobilized
    eligible = sum(v["w"] * v["g"] for v in votes) or 1.0
    conviction = min(caps["conviction_cap"], (abs(total) / eligible) * agree)
    conviction = min(caps["conviction_cap"], conviction * scaler)
    if agree < caps["agree_min"] or conviction < caps["conv_min"]:
        return None
    long_side = total > 0
    winners = [v for v in votes if (v["v"] > 0) == long_side]
    dominant = max(winners, key=lambda v: abs(v["v"]))
    stop_pct = (
        _weighted_median([(v["stop_pct"], v["w"] * v["g"]) for v in winners])
        or dominant["stop_pct"]
    )
    names = ", ".join(v["tid"] for v in sorted(winners, key=lambda v: -abs(v["v"]))[:3])
    return {
        "action": "long" if long_side else "short",
        "confidence": round(conviction, 3),
        "stop_pct": round(stop_pct, 3),
        "leverage": min(v["leverage"] for v in winners),
        "reason": f"{len(winners)}x agree({agree:.0%}): {names}",
        "technique": dominant["tid"],
        "contributors": [v["tid"] for v in winners],
    }


def _coin_votes(
    coin: str, f: dict[str, Any], adopted: list[dict[str, Any]], rstats: dict[str, Any]
) -> list[dict[str, Any]]:
    """Collect every adopted technique's signed, gated vote on one coin."""
    regime = f.get("regime", "range")
    votes = []
    for e in adopted:
        decision = call_signal(load_signal(e["id"]), f)
        if (
            not decision
            or decision["action"] == "flat"
            or float(decision.get("stop_pct") or 0) <= 0
        ):
            continue
        w = float(e.get("weight", 1.0) or 1.0)
        g = _gate(e["id"], regime, rstats)
        sign = 1.0 if decision["action"] == "long" else -1.0
        votes.append(
            {
                "tid": e["id"],
                "v": sign * float(decision.get("confidence") or 0) * w * g,
                "w": w,
                "g": g,
                "stop_pct": float(decision["stop_pct"]),
                "leverage": int(decision.get("leverage") or 99),
            }
        )
    return votes


def _read_json(path: Path, default: Any) -> Any:
    """Read a JSON file, returning ``default`` if missing or unparseable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _memory_edge_ok(technique: str, regime: str) -> tuple[bool, dict[str, Any]]:
    """Live gate: does trade-memory show a REAL (CI>0), regime-matched edge here?

    doc 04 §3a — "proven backtest" is not enough; an auto-execute also needs live
    regime-matched ``edge_real`` from memory.py. Cold start (no rows) → (False, {}).

    Args:
        technique: The technique id.
        regime: The current regime to match.

    Returns:
        (ok, stats) where ok is True only with edge_real and >=3 trades; stats is the
        memory.py expectancy row (win_rate/payoff/trades) for sizing.
    """
    out = subprocess.run(
        [
            "uv", "run", "--no-project", "python3", str(SCRIPT_DIR / "memory.py"),
            "expectancy", "--technique", technique, "--regime", regime,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    try:
        st = json.loads(out.stdout[out.stdout.find("{") :])
    except (ValueError, OSError):
        return (False, {})
    return (bool(st.get("edge_real")) and int(st.get("trades", 0)) >= 3, st)


def _cold_start_ok(intent: dict[str, Any], conv_floor: float) -> bool:
    """Bounded cold-start carve-out (doc 04 §3 carve-out 3).

    With no regime-matched ``edge_real`` yet, allow a bounded half-size probe only if the
    signal is proven-market AND clears the conviction floor, so memory can bootstrap
    without opening the discretionary door. The caller already enforced ``confidence >=
    conv_floor`` before reaching here; the extra ``* 1.1`` the forge-only overhaul stacked
    on top demanded ~0.83*cap — a near-ceiling bar the ensemble almost never reaches, so no
    probe ever fired and memory could never bootstrap (the inert-organism lock). The
    genome-tuned base floor is the real conviction guard; ``proven`` is the real edge guard.
    """
    return bool(intent.get("proven")) and intent["confidence"] >= conv_floor


def _cooling(coin: str) -> bool:
    """Skip a coin still inside the executor's post-close cooldown (contract 4).

    autosettle.js writes ``~/.gclaw/cooldown_{COIN}.json`` (':' → '_') on close as
    ``{"coin":..., "closedAt": <ms epoch>}`` and hl_perp.js refuses re-entry within
    GCLAW_COOLDOWN_H (default 4h). The forge reads the SAME files so the single
    deterministic execute isn't spent on a coin the executor will reject anyway.
    """
    cooldown_h = float(os.environ.get("GCLAW_COOLDOWN_H") or 4)
    path = gclaw_home() / f"cooldown_{coin.replace(':', '_')}.json"
    cd = _read_json(path, {})
    closed_at = float(cd.get("closedAt") or 0)
    if not closed_at:
        return False
    age_h = (datetime.now(UTC).timestamp() * 1000 - closed_at) / 3600e3
    return age_h < cooldown_h


def _gate_intents(
    intents: list[dict[str, Any]], caps: dict[str, float], veto: dict[str, Any]
) -> list[dict[str, Any]]:
    """Assemble the hard edge gate (doc 04 §3a + §4.3) → executable intents.

    An intent auto-executes only if proven, notional>=MIN_NOTIONAL, confidence>=
    0.75*conviction_cap, the coin is not cooling, and memory shows regime-matched
    edge_real (>=3 trades) — OR it is still inside the live-bootstrap window
    (<MIN_LIVE_SAMPLE closes) and passes the bounded cold-start rule (then half-size).
    A truthy veto (contract 3) empties the gate. Returns intents sorted by confidence.
    """
    if veto.get("veto"):
        return []
    conv_floor = 0.75 * caps["conviction_cap"]
    allow_xyz = os.environ.get("GCLAW_ALLOW_XYZ_OPEN") == "1"
    gated: list[dict[str, Any]] = []
    for i in intents:
        if not (i["proven"] and i["notional"] >= MIN_NOTIONAL):
            continue
        # xyz builder-dex opens land NAKED — managed custody does not arm the attached
        # SL trigger as a resting order there, so riskguard flattens them on sight for a
        # guaranteed loss (assune-opy). Gate xyz out of auto-origination until that SL
        # attachment is verified; flip GCLAW_ALLOW_XYZ_OPEN=1 once it is fixed.
        if ":" in i["coin"] and not allow_xyz:
            continue
        if i["confidence"] < conv_floor:
            continue
        if _cooling(i["coin"]):
            continue
        # Reuse the per-coin memory read stashed by cmd_run (cmd_run sets edge_real_mem
        # so the gate never re-queries memory.py per intent).
        ok = bool(i.get("edge_real_mem")) if "edge_real_mem" in i else _memory_edge_ok(
            i["technique"], i.get("regime", "range")
        )[0]
        # Cold-start means STILL-BOOTSTRAPPING, not LOSING: a technique earns bounded
        # half-size probes until it has a fair live sample (MIN_LIVE_SAMPLE closes). The
        # old window (< 3) benched a technique the moment it hit 3 trades — but the
        # bootstrap CI can only clear zero at n=3 if all three win, so one early loss
        # locked a genuinely-edged technique out forever (cold-start-forever sibling).
        # Widening the window lets a real edge accumulate the trades that flip edge_real,
        # while the CI gate still governs full-size sizing so noise never graduates.
        is_cold = i.get("edge_trades_mem", 0) < MIN_LIVE_SAMPLE
        cold_ok = is_cold and _cold_start_ok(i, conv_floor)
        if not (ok or cold_ok):
            continue
        i["edge_real"] = ok
        if not ok:
            i["cold_start"] = True
            i["notional"] = round(i["notional"] * 0.5, 2)  # half-size cold-start probe
        if i["notional"] >= MIN_NOTIONAL:
            gated.append(i)
    gated.sort(key=lambda x: x["confidence"], reverse=True)
    return gated


def cmd_run(args: argparse.Namespace) -> dict[str, Any]:
    """Combine every adopted technique into one ensemble decision per coin; execute the
    strongest proven-market signal. Techniques vote (gated by regime + genome weight)
    rather than compete — the family acts as one weapon, not the loudest single signal."""
    meta = load_metabolism()
    mode = meta.get("mode", "thrive")
    cap = leverage_cap(float(meta.get("goodwill", 0) or 0))
    style = load_style()
    if not style["adopted"]:
        return {
            "ok": True,
            "mode": mode,
            "leverage_cap": cap,
            "intents": [],
            "note": "no adopted techniques",
        }
    caps = {
        "conviction_cap": float(style.get("conviction_cap", 0.85)),
        "agree_min": float(style.get("agree_min", 0.60)),
        "conv_min": float(style.get("conv_min", 0.22)),
    }
    proven_coins = {e["coin"] for e in style["adopted"]}
    proven_by_tech = {e["id"]: e["coin"] for e in style["adopted"]}
    proven_mkts = proven_pairs()  # (technique, coin) pairs auto-proven on the wider universe
    # The ensemble votes on every market a technique is proven on plus the wider universe.
    coins = (
        list(dict.fromkeys([*proven_coins, *_scan_universe()]))
        if not args.coins
        else [c.strip() for c in args.coins.split(",") if c.strip()]
    )
    interval = args.interval if args.coins else style["adopted"][0].get("interval", "1h")
    live = get_live_features(coins)
    rstats = _regime_stats()
    scaler = _conviction_scaler(meta)
    acct = _account()
    equity, buying_power = acct["equity"], acct["buying_power"]
    intents: list[dict[str, Any]] = []
    for coin in coins:
        cs = get_candles(coin, interval, 60)
        if len(cs) <= WARMUP:
            continue
        f = features_at(cs, len(cs) - 1, coin, live.get(coin))
        regime = f.get("regime", "range")
        decision = _combine(_coin_votes(coin, f, style["adopted"], rstats), regime, caps, scaler)
        if not decision:
            continue
        # Live regime-matched edge from memory: feeds both sizing.py (Kelly) and the
        # hard gate; query once here and stash it so the gate never re-queries.
        ok, st = _memory_edge_ok(decision["technique"], regime)
        intent = _intent(
            decision["technique"], coin, decision, mode, equity, cap, buying_power, f, st
        )
        intent["proven"] = coin in proven_coins or any(
            proven_by_tech.get(t) == coin or (t, coin) in proven_mkts
            for t in decision["contributors"]
        )
        intent["reason"], intent["contributors"] = decision["reason"], decision["contributors"]
        intent["regime"] = regime
        intent["edge_real_mem"] = ok
        intent["edge_trades_mem"] = int((st or {}).get("trades", 0) or 0)
        intents.append(intent)
    intents.sort(key=lambda x: x["confidence"], reverse=True)
    breaker = circuit_breaker(equity, acct.get("positions", 0))
    veto = _read_json(gclaw_home() / "forge" / "veto.json", {})
    result = {
        "ok": True,
        "mode": mode,
        "leverage_cap": cap,
        "equity": equity,
        "buying_power": round(buying_power, 2),
        "breaker": breaker,
        "veto": bool(veto.get("veto")),
        "intents": intents,
    }
    # The ONLY origination path: the assembled hard edge gate (doc 04 §3a + §4.3) —
    # proven + regime-matched edge_real (or bounded cold-start) + conviction floor +
    # cooldown, vetoable by the LLM. Execute only the single top-confidence survivor.
    gated = _gate_intents(intents, caps, veto)
    if args.execute and veto.get("veto"):
        result["executed"] = {"skipped": f"LLM veto: {str(veto.get('reason', ''))[:120]}"}
    elif args.execute and not breaker["allow_entry"]:
        result["executed"] = {"skipped": f"circuit breaker: {breaker['reason']}"}
    elif args.execute and gated and mode != "hibernate":
        top = gated[0]
        result["executed"] = _execute(top)
        if result["executed"].get("ok"):
            ref, _ = royalty_ref(load_technique(top["technique"]))
            pending = load_pending()
            pending[top["coin"]] = {
                "ref": ref,
                "technique": top["technique"],
                "opened_at": now_iso(),
                "regime": top.get("regime", "range"),
                "risk_usd": round(top["notional"] * top["sl_pct"] / 100.0, 4),
            }
            save_pending(pending)
            result["attribution"] = {"coin": top["coin"], "credit_to": ref}
    elif args.execute:
        result["executed"] = {
            "skipped": "no intent cleared the edge_real + conviction gate"
        }
    return result


def _execute(intent: dict[str, Any]) -> dict[str, Any]:
    """Place the intent through hl_perp.js — the single cap-enforced origination path.

    Sets ``GCLAW_FORGE_EXECUTE=1`` (contract 1): hl_perp.js cmdOpen now refuses to
    open unless that env var is present, so the gated forge execute is the ONLY way a
    position can open — discretionary opens are structurally impossible. Always passes
    both --sl-pct and --tp-pct=sl*1.5 (contract 2): the executor requires both (>0) or
    it dies, so no naked entry can slip through.
    """
    cmd = [
        "node",
        str(SCRIPT_DIR / "hl_perp.js"),
        "open",
        "--coin",
        intent["coin"],
        "--side",
        intent["side"],
        "--notional",
        str(intent["notional"]),
        "--leverage",
        str(intent["leverage"]),
        "--sl-pct",
        str(intent["sl_pct"]),
        "--tp-pct",
        str(round(intent["sl_pct"] * 1.5, 2)),
    ]
    env = {**os.environ, "GCLAW_FORGE_EXECUTE": "1"}
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
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

    ap = sub.add_parser("autoprove", help="backtest the arsenal across the liquid universe")
    ap.add_argument("--budget", type=int, default=None, help="max backtests this run")
    ap.set_defaults(fn=cmd_autoprove)

    au = sub.add_parser(
        "author", help="propose a signal body; validate+backtest+adopt-if-proven (never executes)"
    )
    au.add_argument("--name", required=True)
    au.add_argument("--signal-file", dest="signal_file", required=True, help="path to the signal.py body")
    au.add_argument("--claim", default="")
    au.add_argument("--kind", choices=["lens", "edge"], default="edge")
    au.add_argument("--coin", default="BTC")
    au.add_argument("--interval", default="1h")
    au.add_argument("--limit", type=int, default=1000)
    au.add_argument("--parent", default=None)
    au.add_argument("--force", action="store_true")
    au.set_defaults(fn=cmd_author)

    for name, fn, helptext in [
        ("adopt", cmd_adopt, "adopt a proven technique"),
        ("drop", cmd_drop, "remove from loadout"),
        ("show", cmd_show, "show a technique + card"),
    ]:
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
    disc.add_argument(
        "--peers",
        action="store_true",
        help="discover the family's techniques from their onchain cards",
    )
    disc.set_defaults(fn=cmd_discover)

    pull = sub.add_parser("pull", help="copy a pooled technique locally (as a draft)")
    pull.add_argument("ref", help="<author>/<id> from discover")
    pull.add_argument("--as", dest="as_", default=None, help="local id to save under")
    pull.add_argument("--cid", default=None, help="IPFS cid to fetch from (cross-machine pull)")
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
    ro.add_argument(
        "--auto", action="store_true", help="no-op (don't error) when nothing is attributable"
    )
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
    cr.add_argument(
        "--coins", default=None, help="markets to test (default: BTC,ETH,SOL + claimed)"
    )
    cr.add_argument("--interval", default=None)
    cr.add_argument("--limit", type=int, default=1200)
    cr.set_defaults(fn=cmd_critique)

    r = sub.add_parser("run", help="evaluate adopted techniques on live data")
    r.add_argument(
        "--coins", default=None, help="override markets (default: each technique's proven market)"
    )
    r.add_argument("--interval", default="1h", help="interval for --coins override")
    r.add_argument("--execute", action="store_true", help="place the top intent (within caps)")
    r.set_defaults(fn=cmd_run)
    return p


def main() -> None:
    args = build_parser().parse_args()
    print(json.dumps(args.fn(args), indent=2))


if __name__ == "__main__":
    main()
