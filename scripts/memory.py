#!/usr/bin/env python3
"""memory.py — the agent's trade-memory and regime-conditional expectancy store.

The right-sized "knowledge graph": every closed trade is one record linking
technique x coin x regime x feature-snapshot -> outcome (R-multiple). From that
relational memory the agent answers the question that fixes entry quality:

    "In conditions like RIGHT NOW (this regime), which of my techniques actually
     has positive, statistically-real expectancy — and how should I size it?"

Expectancy is reported with a bootstrap confidence interval, so a technique that
is merely lucky (CI straddles zero) is not treated as an edge. File-based and
transparent: one JSONL line per trade at $GCLAW_HOME/memory.jsonl.

    memory.py record --coin SOL --technique stock-meanrev --regime range \
                     --side long --pnl 0.84 --risk 0.84
    memory.py expectancy --technique stock-meanrev [--regime range]
    memory.py query --regime range          # rank techniques for this regime
    memory.py summary                        # per (technique,regime) table (for the swarm)
"""

from __future__ import annotations

import argparse
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def store() -> Path:
    return home() / "memory.jsonl"


def load() -> list[dict]:
    p = store()
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def record(args: argparse.Namespace) -> dict:
    """Append one closed-trade outcome. R-multiple normalises pnl by risk taken."""
    risk = abs(args.risk) if args.risk else 0.0
    r_multiple = (args.pnl / risk) if risk else 0.0
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "coin": args.coin,
        "technique": args.technique,
        "regime": args.regime,
        "side": args.side,
        "pnl": round(args.pnl, 4),
        "risk": round(risk, 4),
        "r": round(r_multiple, 3),
    }
    home().mkdir(parents=True, exist_ok=True)
    with store().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return {"ok": True, "recorded": row, "total": len(load())}


def _bootstrap_ci(rs: list[float], iters: int = 2000) -> tuple[float, float]:
    """95% CI on the mean R via bootstrap resampling — is the edge real or luck?"""
    if len(rs) < 3:
        return (0.0, 0.0)
    means = []
    n = len(rs)
    for _ in range(iters):
        means.append(sum(rs[int(random.random() * n)] for _ in range(n)) / n)
    means.sort()
    return (round(means[int(0.025 * iters)], 3), round(means[int(0.975 * iters)], 3))


def _stats(rows: list[dict]) -> dict:
    if not rows:
        return {"trades": 0}
    rs = [row["r"] for row in rows]
    wins = [r for r in rs if r > 0]
    pnl = sum(row["pnl"] for row in rows)
    lo, hi = _bootstrap_ci(rs)
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    losses = [abs(r) for r in rs if r < 0]
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    return {
        "trades": len(rs),
        "win_rate": round(len(wins) / len(rs), 3),
        "expectancy_r": round(sum(rs) / len(rs), 3),
        "ci95": [lo, hi],
        "edge_real": lo > 0,  # whole CI above zero = a real edge, not luck
        "payoff": round(avg_win / avg_loss, 2) if avg_loss else (avg_win or 0.0),
        "pnl_usd": round(pnl, 2),
    }


def _filter(rows: list[dict], technique: str | None, regime: str | None) -> list[dict]:
    return [r for r in rows
            if (technique is None or r.get("technique") == technique)
            and (regime is None or r.get("regime") == regime)]


def expectancy(args: argparse.Namespace) -> dict:
    rows = _filter(load(), args.technique, args.regime)
    return {"ok": True, "technique": args.technique, "regime": args.regime, **_stats(rows)}


def query(args: argparse.Namespace) -> dict:
    """Rank techniques by expectancy in a regime — the 'what should I trade now' call."""
    rows = _filter(load(), None, args.regime)
    by_tech: dict[str, list[dict]] = {}
    for row in rows:
        by_tech.setdefault(row["technique"], []).append(row)
    ranked = [{"technique": t, **_stats(rs)} for t, rs in by_tech.items()]
    ranked.sort(key=lambda e: (e.get("edge_real", False), e.get("expectancy_r", 0)), reverse=True)
    return {"ok": True, "regime": args.regime, "techniques": ranked}


def summary(_args: argparse.Namespace) -> dict:
    """Compact per-(technique, regime) expectancy table — published to the swarm."""
    rows = load()
    cells: dict[str, list[dict]] = {}
    for row in rows:
        cells.setdefault(f'{row["technique"]}|{row.get("regime", "?")}', []).append(row)
    table = []
    for key, rs in cells.items():
        tech, regime = key.split("|", 1)
        s = _stats(rs)
        table.append({"technique": tech, "regime": regime, "trades": s["trades"],
                      "expectancy_r": s["expectancy_r"], "edge_real": s["edge_real"]})
    table.sort(key=lambda e: e["expectancy_r"], reverse=True)
    return {"ok": True, "table": table}


def main() -> int:
    p = argparse.ArgumentParser(description="trade-memory + regime-conditional expectancy")
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("record")
    r.add_argument("--coin", required=True)
    r.add_argument("--technique", required=True)
    r.add_argument("--regime", required=True)
    r.add_argument("--side", default="long")
    r.add_argument("--pnl", type=float, required=True)
    r.add_argument("--risk", type=float, default=0.0)
    e = sub.add_parser("expectancy")
    e.add_argument("--technique", required=True)
    e.add_argument("--regime")
    q = sub.add_parser("query")
    q.add_argument("--regime", required=True)
    sub.add_parser("summary")
    args = p.parse_args()
    fn = {"record": record, "expectancy": expectancy, "query": query, "summary": summary}[args.command]
    print(json.dumps(fn(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
