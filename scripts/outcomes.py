#!/usr/bin/env python3
"""Gclaw Event Desk (Book A) — defined-risk bets on HIP-3/4 outcome markets.

The LLM's edge here is *reading an event into a calibrated probability*; this
module is the DETERMINISTIC gate that owns all sizing and risk. The LLM proposes
a side coin, its own probability, and a stake; ``bet`` accepts ONLY if every hard
rule passes (volume floor, divergence margin, favorite-longshot guard, stake
bounds, ticket cap, no double-down) and otherwise returns a clean skip — never a
crash. Safety is code, never prompt (the audit's core lesson, mirrored from the
forge's ``run`` gate).

Shadow mode is the default: a passing bet is recorded to the calibration ledger
with ``shadow:true`` and NO order is placed. Real orders are placed ONLY when
``GCLAW_OUTCOMES_LIVE=1`` — this lets the LLM's calibration prove out before a
dollar is risked ("prove before trade").

    outcomes.py markets [--min-vol 10000]          # tradeable sides (price + volume)
    outcomes.py bet --coin "#1731" --prob 0.92 --stake 8 [--reason "..."]
    outcomes.py resolve                            # settle resolved tickets, update Brier
    outcomes.py calibration                        # the proven-calibration board

Reads go through hl_outcomes.js ``markets`` (a public join of meta+mids+volume);
live orders go through hl_outcomes.js ``order``. Both are subprocess boundaries so
the gate logic and Brier math stay unit-testable with no network.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

# Gate constants — env-overridable, defined-risk by construction. These live in code
# (not the prompt) so an injected instruction can never widen them.
MIN_VOLUME = float(os.environ.get("GCLAW_OUTCOMES_MIN_VOL") or 10000)
DIVERGENCE_MARGIN = float(os.environ.get("GCLAW_OUTCOMES_MARGIN") or 0.08)
LONGSHOT_FLOOR = float(os.environ.get("GCLAW_OUTCOMES_LONGSHOT_FLOOR") or 0.10)
MAX_STAKE = float(os.environ.get("GCLAW_OUTCOMES_MAX_STAKE") or 15)
MIN_STAKE = 1.0
MAX_TICKETS = int(os.environ.get("GCLAW_OUTCOMES_MAX_TICKETS") or 3)

# Resolution is read from real HL settlement fills (dir:"Settlement", visible by
# address in userFills — the same feed autosettle books PnL from), NOT guessed from a
# live market's mid. The settle px (0 or 1) is the resolved value. See fetch_settlements.


def home() -> Path:
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def ledger_path() -> Path:
    return home() / "calibration.json"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def live_mode() -> bool:
    """True only when GCLAW_OUTCOMES_LIVE=1 — otherwise shadow (record, no order)."""
    return os.environ.get("GCLAW_OUTCOMES_LIVE") == "1"


def _write_atomic(path: Path, data: str) -> None:
    """Write via temp + os.replace so a concurrent reader never sees a half-file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


# ── Venue bridge (subprocess to hl_outcomes.js) ──────────────────────────────


def _run_outcomes_js(args: list[str], timeout: int = 90) -> dict[str, Any]:
    """Call hl_outcomes.js and parse its JSON from the first brace, or raise."""
    proc = subprocess.run(
        ["node", str(SCRIPT_DIR / "hl_outcomes.js"), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    out = proc.stdout
    i = out.find("{")
    if i < 0:
        raise RuntimeError(proc.stderr.strip() or "hl_outcomes.js produced no JSON")
    data = json.loads(out[i:])
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "hl_outcomes.js error"))
    return data


def fetch_sides(min_vol: float = MIN_VOLUME) -> list[dict[str, Any]]:
    """Active tradeable sides at or above the volume floor (one row per side).

    Args:
        min_vol: USD 24h volume floor a side must clear to be tradeable.

    Returns:
        Rows of {outcomeId, name, side, coin, price, volumeUsd}, descending volume.
    """
    sides = _run_outcomes_js(["markets", "--status", "active"]).get("sides", [])
    rows = [s for s in sides if float(s.get("volumeUsd", 0)) >= min_vol]
    rows.sort(key=lambda s: float(s.get("volumeUsd", 0)), reverse=True)
    return rows


def _place_live_order(side: dict[str, Any], stake: float) -> dict[str, Any]:
    """Place a real defined-risk buy via hl_outcomes.js (LIVE mode only).

    Buying a side at price p costs ~p per contract and pays 1 if it resolves true,
    so size = stake / price contracts caps the max loss at the stake.

    Args:
        side: The market side row (carries outcomeId, coin, price).
        stake: USD to risk (already gate-validated).

    Returns:
        The hl_outcomes.js order result dict.
    """
    price = float(side["price"])
    # Outcome sides trade in integer contracts (sizeDecimals=0 on this venue), so floor
    # to whole contracts — this keeps cost (size*price) at or below the stake, preserving
    # defined risk, and avoids a venue reject on a fractional size.
    size = float(int(stake / price)) if price > 0 else 0.0
    return _run_outcomes_js(
        [
            "order",
            "--outcome", str(side["outcomeId"]),
            "--coin", str(side["coin"]),
            "--buy",
            "--price", str(price),
            "--size", str(size),
            "--market",
        ]
    )


# ── Calibration ledger ───────────────────────────────────────────────────────


def load_ledger() -> dict[str, Any]:
    """The calibration ledger: tickets + running Brier aggregates (memory.py style)."""
    try:
        d = json.loads(ledger_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("tickets", [])
    return d


def _price_bucket(price: float) -> str:
    """Coarse implied-probability bucket for the by-bucket Brier breakdown."""
    edges = (0.10, 0.25, 0.50, 0.75, 0.90)
    labels = ("0-10", "10-25", "25-50", "50-75", "75-90", "90-100")
    for edge, label in zip(edges, labels[:-1], strict=True):
        if price < edge:
            return label
    return labels[-1]


def _aggregate(tickets: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute running calibration aggregates over resolved tickets.

    brier_mean is the mean of (prob - outcome)^2 across resolved tickets (lower is
    better; a no-skill guesser at p=price scores ~price*(1-price)). Also reports the
    no-skill baseline at the prices actually bet and a per-price-bucket breakdown.

    Args:
        tickets: All ledger tickets (resolved and open).

    Returns:
        Aggregate dict: counts, brier_mean, baseline_mean, and by_bucket.
    """
    resolved = [t for t in tickets if t.get("resolved")]
    n = len(tickets)
    n_shadow = sum(1 for t in tickets if t.get("shadow"))
    agg: dict[str, Any] = {
        "n": n,
        "n_shadow": n_shadow,
        "n_live": n - n_shadow,
        "n_resolved": len(resolved),
        "brier_mean": None,
        "baseline_mean": None,
        "by_bucket": {},
    }
    if resolved:
        briers = [float(t["brier"]) for t in resolved]
        baselines = [float(t["price"]) * (1 - float(t["price"])) for t in resolved]
        agg["brier_mean"] = round(sum(briers) / len(briers), 6)
        agg["baseline_mean"] = round(sum(baselines) / len(baselines), 6)
        buckets: dict[str, list[float]] = {}
        for t in resolved:
            buckets.setdefault(_price_bucket(float(t["price"])), []).append(float(t["brier"]))
        agg["by_bucket"] = {
            b: {"n": len(v), "brier_mean": round(sum(v) / len(v), 6)} for b, v in buckets.items()
        }
    return agg


def save_ledger(led: dict[str, Any]) -> None:
    led["aggregates"] = _aggregate(led["tickets"])
    led["updated_at"] = now_iso()
    _write_atomic(ledger_path(), json.dumps(led, indent=2) + "\n")


def read_calibration() -> dict[str, Any]:
    """memory.py-style read for the briefing: tickets + aggregates, never raises."""
    led = load_ledger()
    return {
        "ok": True,
        "tickets": led["tickets"],
        "open": [t for t in led["tickets"] if not t.get("resolved")],
        "aggregates": led.get("aggregates") or _aggregate(led["tickets"]),
    }


# ── The gate ─────────────────────────────────────────────────────────────────


def _gate_skip(reason: str) -> dict[str, Any]:
    """A clean skip — the gate rejected the bet, but nothing crashed."""
    return {"ok": True, "placed": False, "skipped": reason}


def evaluate_bet(
    coin: str,
    prob: float,
    stake: float,
    sides: list[dict[str, Any]],
    open_coins: set[str],
    n_open: int,
) -> dict[str, Any]:
    """Pure deterministic gate — accept a bet only if every hard rule passes.

    Mirrors the forge ``run`` gate: the LLM supplies (coin, prob, stake) and the
    code owns risk. Rules, in order: (a) market exists and clears the volume floor;
    (b) edge = prob - price >= DIVERGENCE_MARGIN (buy only an underpriced side);
    (c) favorite-longshot guard rejects buying a longshot priced < LONGSHOT_FLOOR;
    (d) MIN_STAKE <= stake <= MAX_STAKE (defined risk = stake); (e) open tickets <
    MAX_TICKETS; (f) not already holding this coin.

    Args:
        coin: The proposed side coin id (e.g. "#1731").
        prob: The LLM's own probability the side resolves true, in [0, 1].
        stake: USD to risk on the ticket.
        sides: The active tradeable-sides board from ``fetch_sides``.
        open_coins: Coins with an open (unresolved) ticket already.
        n_open: Count of open tickets (the ticket-cap input).

    Returns:
        On pass: {"ok": True, "side": <row>, "edge": <float>}. On any failure a
        clean skip dict from ``_gate_skip`` (never raises).
    """
    side = next((s for s in sides if s.get("coin") == coin), None)
    if side is None:
        return _gate_skip(f"no active market for coin {coin} (or below volume floor)")
    if float(side.get("volumeUsd", 0)) < MIN_VOLUME:
        return _gate_skip(f"volume {side.get('volumeUsd')} < floor {MIN_VOLUME}")
    if not 0.0 <= prob <= 1.0:
        return _gate_skip(f"prob {prob} out of [0,1]")
    price = float(side["price"])
    edge = round(prob - price, 6)
    if edge < DIVERGENCE_MARGIN:
        return _gate_skip(f"edge {edge} < margin {DIVERGENCE_MARGIN} (not underpriced enough)")
    if price < LONGSHOT_FLOOR:
        return _gate_skip(
            f"longshot guard: price {price} < floor {LONGSHOT_FLOOR} (longshots are overpriced)"
        )
    if stake < MIN_STAKE or stake > MAX_STAKE:
        return _gate_skip(f"stake {stake} outside [{MIN_STAKE}, {MAX_STAKE}]")
    if n_open >= MAX_TICKETS:
        return _gate_skip(f"open tickets {n_open} >= cap {MAX_TICKETS}")
    if coin in open_coins:
        return _gate_skip(f"already holding {coin} (no double-down)")
    return {"ok": True, "side": side, "edge": edge}


def _new_ticket(side: dict[str, Any], prob: float, stake: float, edge: float, reason: str) -> dict[str, Any]:
    return {
        "coin": side["coin"],
        "outcomeId": side["outcomeId"],
        "name": side["name"],
        "side": side["side"],
        "prob": round(prob, 6),
        "price": round(float(side["price"]), 6),
        "stake": round(stake, 6),
        "edge": round(edge, 6),
        "reason": reason or "",
        "ts": now_iso(),
        "shadow": not live_mode(),
        "resolved": False,
    }


def cmd_bet(args: argparse.Namespace) -> dict[str, Any]:
    """The gated primitive: validate an LLM-proposed bet, then record (shadow) or place (live).

    The gate owns all risk. On a pass: in shadow mode (default) the ticket is recorded
    with shadow:true and NO order is placed; in live mode the order goes through
    hl_outcomes.js first, then the ticket is recorded with shadow:false. A gate
    rejection or a live-order failure is a clean skip, never a crash.
    """
    try:
        sides = fetch_sides()
    except (subprocess.SubprocessError, RuntimeError, ValueError, OSError) as exc:
        return _gate_skip(f"could not fetch markets ({exc})")
    led = load_ledger()
    open_tickets = [t for t in led["tickets"] if not t.get("resolved")]
    verdict = evaluate_bet(
        args.coin,
        float(args.prob),
        float(args.stake),
        sides,
        {t["coin"] for t in open_tickets},
        len(open_tickets),
    )
    if not verdict.get("side"):
        return verdict  # clean skip
    side, edge = verdict["side"], verdict["edge"]
    ticket = _new_ticket(side, float(args.prob), float(args.stake), edge, args.reason or "")
    if live_mode():
        try:
            ticket["order"] = _place_live_order(side, float(args.stake))
        except (subprocess.SubprocessError, RuntimeError, ValueError, OSError) as exc:
            return _gate_skip(f"live order failed ({exc}) — not recorded")
    led["tickets"].append(ticket)
    save_ledger(led)
    return {"ok": True, "placed": True, "shadow": ticket["shadow"], "ticket": ticket}


# ── Resolution + settlement ──────────────────────────────────────────────────


def _ts_ms(iso: str) -> float:
    """ISO timestamp → epoch ms, for matching a settlement fill to the ticket that preceded it."""
    try:
        return datetime.fromisoformat(iso).timestamp() * 1000
    except (ValueError, TypeError):
        return 0.0


def fetch_settlements() -> list[dict[str, Any]]:
    """The DEFINITIVE resolution signal: HL ``dir:"Settlement"`` fills for our sides.

    Returns each as {coin, settlePx (0|1), closedPnl, time(ms)}. The settle px is the
    resolved value, so outcome = 1 if px >= 0.5 else 0 — no price-band guessing.
    """
    data = _run_outcomes_js(["settlements"])
    return data.get("settlements", [])


def cmd_resolve(_args: argparse.Namespace) -> dict[str, Any]:
    """Score resolved tickets from real settlement fills — calibration ONLY, never PnL.

    A ticket resolves when HL emits a ``dir:"Settlement"`` fill for its side coin (after
    the bet). outcome = 1 if the side settled true (px ~1) else 0; brier = (prob-outcome)^2
    feeds the calibration ledger. **PnL is NOT settled here**: autosettle.js already books
    every outcome ``closedPnl`` from userFills (coin-agnostic), so settling again would
    double-count. We store the fill's closedPnl as informational only. Idempotent: an
    already-resolved ticket is skipped.
    """
    led = load_ledger()
    open_tickets = [t for t in led["tickets"] if not t.get("resolved")]
    if not open_tickets:
        return {"ok": True, "resolved": 0, "note": "no open tickets"}
    try:
        settlements = fetch_settlements()
    except (subprocess.SubprocessError, RuntimeError, ValueError, OSError) as exc:
        return {"ok": True, "resolved": 0, "note": f"could not fetch settlements ({exc})"}
    by_coin: dict[str, dict[str, Any]] = {}
    for s in settlements:  # keep the latest settlement per coin
        if s["coin"] not in by_coin or s["time"] > by_coin[s["coin"]]["time"]:
            by_coin[s["coin"]] = s
    resolved_now: list[dict[str, Any]] = []
    for t in open_tickets:
        s = by_coin.get(t["coin"])
        if s is None or float(s["time"]) < _ts_ms(t.get("ts", "")):
            continue  # not yet settled (or the settlement predates this ticket)
        outcome = 1 if float(s["settlePx"]) >= 0.5 else 0
        t["resolved"] = True
        t["outcome"] = outcome
        t["brier"] = round((float(t["prob"]) - outcome) ** 2, 6)
        t["settle_pnl"] = round(float(s.get("closedPnl", 0)), 6)  # informational; autosettle books it
        t["resolved_at"] = now_iso()
        resolved_now.append(t)
    save_ledger(led)
    return {
        "ok": True,
        "resolved": len(resolved_now),
        "tickets": [{"coin": t["coin"], "outcome": t["outcome"], "brier": t["brier"]} for t in resolved_now],
        "aggregates": led["aggregates"],
    }


# ── CLI verbs ────────────────────────────────────────────────────────────────


def cmd_markets(args: argparse.Namespace) -> dict[str, Any]:
    """List active tradeable sides at or above the volume floor (deterministic read)."""
    min_vol = float(args.min_vol) if args.min_vol is not None else MIN_VOLUME
    try:
        sides = fetch_sides(min_vol)
    except (subprocess.SubprocessError, RuntimeError, ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "min_vol": min_vol, "count": len(sides), "sides": sides}


def cmd_calibration(_args: argparse.Namespace) -> dict[str, Any]:
    """Print the proven-calibration board (the event-desk analogue of edge_real)."""
    return read_calibration()


def main() -> int:
    p = argparse.ArgumentParser(description="Gclaw Event Desk — defined-risk outcome bets")
    sub = p.add_subparsers(dest="command", required=True)
    m = sub.add_parser("markets", help="tradeable sides (price + volume)")
    m.add_argument("--min-vol", dest="min_vol", default=None)
    b = sub.add_parser("bet", help="the gated defined-risk primitive")
    b.add_argument("--coin", required=True)
    b.add_argument("--prob", required=True, type=float)
    b.add_argument("--stake", required=True, type=float)
    b.add_argument("--reason", default="")
    sub.add_parser("resolve", help="settle resolved tickets + update calibration")
    sub.add_parser("calibration", help="the proven-calibration board")
    args = p.parse_args()
    fn = {
        "markets": cmd_markets,
        "bet": cmd_bet,
        "resolve": cmd_resolve,
        "calibration": cmd_calibration,
    }[args.command]
    print(json.dumps(fn(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
