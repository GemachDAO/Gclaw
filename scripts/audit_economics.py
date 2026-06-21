#!/usr/bin/env python3
"""Economics checkpoint — measure the agent's TRUE edge, not funding noise.

The realized "win rate" is misleading: most settles are tiny funding accruals. This
separates REAL position closes (|pnl| > $0.1) and, after every N of them, computes the
honest economics (win rate, avg win/loss, expectancy) and Telegrams a verdict — so the
question "is the strategy actually +EV?" gets answered automatically, on a clean batch.

    audit_economics.py baseline      # mark "start counting fresh from now"
    audit_economics.py report        # print the full economics right now
    audit_economics.py check [--n 5] # if >= N new real closes since the baseline, send the
                                     # verdict to Telegram and advance the baseline
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import urllib.request
from pathlib import Path

REAL_CLOSE_MIN = 0.1  # |pnl| above this is a real position close; below is funding dust
BASELINE = "economics_baseline.json"


def home() -> Path:
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def real_closes() -> list[float]:
    """Realized PnL of every actual position close (funding dust filtered out)."""
    out: list[float] = []
    try:
        for line in (home() / "journal.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            if e.get("event") == "settle" and abs(float(e.get("pnl", 0) or 0)) > REAL_CLOSE_MIN:
                out.append(float(e["pnl"]))
    except (OSError, ValueError):
        pass
    return out


def economics(pnls: list[float]) -> dict:
    """Win rate, avg win/loss, net, and expectancy/trade over a batch of real closes."""
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    return {
        "n": len(pnls),
        "wins": len(wins),
        "win_rate": round(len(wins) / len(pnls), 3) if pnls else 0.0,
        "avg_win": round(statistics.mean(wins), 2) if wins else 0.0,
        "avg_loss": round(statistics.mean(losses), 2) if losses else 0.0,
        "net": round(sum(pnls), 2),
        "expectancy": round(statistics.mean(pnls), 3) if pnls else 0.0,
    }


def verdict(e: dict) -> str:
    """Read the economics into a one-line edge call."""
    if e["n"] == 0:
        return "no real closes yet"
    if e["expectancy"] > 0:
        return "✅ PROFITABLE — the edge is showing through"
    if e["win_rate"] >= 0.4:
        return "↔ near break-even — winners are landing; watch the next batch"
    return "🔴 still -EV — the entries (not just the exits) need work"


def _send_telegram(text: str) -> bool:
    token = os.environ.get("GCLAW_TELEGRAM_TOKEN")
    chat = os.environ.get("GCLAW_TELEGRAM_CHAT")
    if not (token and chat):
        return False
    try:
        body = json.dumps({"chat_id": chat, "text": text}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body,
            headers={"content-type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=15).read()
        return True
    except (OSError, ValueError):
        return False


def _load_baseline() -> int:
    try:
        return int(json.loads((home() / BASELINE).read_text(encoding="utf-8")).get("closed", 0))
    except (OSError, ValueError):
        return 0


def _save_baseline(closed: int) -> None:
    (home() / BASELINE).write_text(json.dumps({"closed": closed}) + "\n", encoding="utf-8")


def cmd_baseline(_: argparse.Namespace) -> dict:
    n = len(real_closes())
    _save_baseline(n)
    return {
        "ok": True,
        "baseline_set_at": n,
        "note": "the next checkpoint reports the closes after this",
    }


def cmd_report(_: argparse.Namespace) -> dict:
    e = economics(real_closes())
    return {"ok": True, **e, "verdict": verdict(e)}


def cmd_check(args: argparse.Namespace) -> dict:
    closes = real_closes()
    base = _load_baseline()
    fresh = closes[base:]
    if len(fresh) < args.n:
        return {
            "ok": True,
            "milestone": False,
            "progress": f"{len(fresh)}/{args.n} new real closes",
        }
    e = economics(fresh)
    msg = (
        f"📊 Economics checkpoint — last {e['n']} real trades\n"
        f"win rate {e['win_rate']:.0%} ({e['wins']}/{e['n']}) · "
        f"avg win ${e['avg_win']:+.2f} · avg loss ${e['avg_loss']:+.2f}\n"
        f"net ${e['net']:+.2f} · expectancy ${e['expectancy']:+.2f}/trade\n"
        f"→ {verdict(e)}"
    )
    sent = _send_telegram(msg)
    _save_baseline(len(closes))  # advance so the next batch starts fresh
    return {
        "ok": True,
        "milestone": True,
        **e,
        "verdict": verdict(e),
        "telegram_sent": sent,
        "message": msg,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="economics checkpoint")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("baseline").set_defaults(fn=cmd_baseline)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    c = sub.add_parser("check")
    c.add_argument("--n", type=int, default=5)
    c.set_defaults(fn=cmd_check)
    args = p.parse_args()
    print(json.dumps(args.fn(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
