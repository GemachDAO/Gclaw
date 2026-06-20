#!/usr/bin/env python3
"""sizing.py — the risk brain: vol-targeted position sizing with fractional Kelly.

Two jobs, both aimed at the diagnosed failures:

1. Vol-target — risk a fixed fraction of equity per trade, and derive the position
   size from an ATR-based stop so a wide-stop trade isn't automatically a big-loss
   trade. One trade can never again be 72% of the damage.
2. Fractional Kelly — scale that risk fraction by the technique's proven edge
   (win-rate + payoff). Proven edges get sized up; weak/coin-flip signals get sized
   down to the floor or skipped.

Pure arithmetic, no I/O, holds nothing. The $11 HyperLiquid min notional and the
goodwill leverage ladder are enforced.

    sizing.py size --equity 211 --price 68.9 --atr-pct 1.14 \
                   --win-rate 0.55 --payoff 1.5 --goodwill 3 [--confidence 0.7]
"""

from __future__ import annotations

import argparse
import json

MIN_NOTIONAL = 11.0
BASE_RISK_PCT = 0.005  # risk 0.5% of equity per trade at full Kelly confidence
KELLY_FRACTION = 0.25  # quarter-Kelly — survival agent, not a degen
STOP_ATR_MULT = 1.6  # stop sits 1.6 ATR from entry
# goodwill → max leverage (mirrors the trading DNA ladder)
LEVERAGE_LADDER = [(0, 2), (25, 3), (50, 5), (100, 8), (200, 12), (500, 20)]


def leverage_cap(goodwill: float) -> int:
    cap = 2
    for threshold, lev in LEVERAGE_LADDER:
        if goodwill >= threshold:
            cap = lev
    return cap


SHRINK_PSEUDO = 20  # pseudo-trades pulling a small-sample win-rate toward 0.5


def shrink_win_rate(win_rate: float, trades: int) -> float:
    """Shrink a small-sample win-rate toward 0.5 so we don't size up on noise: a
    Beta(k/2, k/2) prior, w_adj = (w*n + 0.5*k) / (n + k). 70% on 5 trades → ~0.54."""
    n = max(0, int(trades))
    return (win_rate * n + 0.5 * SHRINK_PSEUDO) / (n + SHRINK_PSEUDO)


def kelly_fraction(win_rate: float, payoff: float) -> float:
    """Edge as a fraction of bankroll: f* = W - (1-W)/b, then quarter it."""
    if payoff <= 0:
        return 0.0
    full = win_rate - (1 - win_rate) / payoff
    return max(0.0, full) * KELLY_FRACTION


def size_trade(
    equity: float,
    price: float,
    atr_pct: float,
    win_rate: float,
    payoff: float,
    goodwill: float,
    confidence: float,
    trades: int = 0,
) -> dict:
    """Return the position size, stop, and risk for one trade."""
    stop_pct = max(STOP_ATR_MULT * atr_pct, 0.8) / 100  # never tighter than 0.8%
    # risk fraction: base, scaled by the (sample-shrunk) Kelly edge and confidence.
    edge = kelly_fraction(shrink_win_rate(win_rate, trades), payoff)
    # an unknown/zero edge still gets a tiny probe; a real edge scales toward base.
    risk_pct = min(BASE_RISK_PCT, max(0.0015, edge)) * max(0.3, min(1.0, confidence))
    risk_usd = equity * risk_pct
    notional = risk_usd / stop_pct
    cap_notional = equity * leverage_cap(goodwill)
    notional = max(MIN_NOTIONAL, min(notional, cap_notional))
    # recompute realized risk after the min/cap clamp so the report is honest.
    realized_risk = notional * stop_pct
    size = notional / price if price else 0
    return {
        "ok": True,
        "notional_usd": round(notional, 2),
        "size": round(size, 6),
        "stop_distance_pct": round(stop_pct * 100, 2),
        "stop_long": round(price * (1 - stop_pct), 4),
        "stop_short": round(price * (1 + stop_pct), 4),
        "risk_usd": round(realized_risk, 2),
        "risk_pct_equity": round(realized_risk / equity * 100, 2) if equity else 0,
        "kelly_edge": round(edge, 4),
        "win_rate_shrunk": round(shrink_win_rate(win_rate, trades), 3),
        "leverage_cap": leverage_cap(goodwill),
        "clamped_to_min": notional <= MIN_NOTIONAL + 1e-9,
        "note": "sized to risk a fixed fraction of equity; size falls out of the ATR stop",
    }


def main() -> int:
    p = argparse.ArgumentParser(description="vol-targeted + Kelly position sizing")
    p.add_argument("command", choices=["size"])
    p.add_argument("--equity", type=float, required=True)
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--atr-pct", type=float, required=True)
    p.add_argument("--win-rate", type=float, default=0.5)
    p.add_argument("--payoff", type=float, default=1.5)
    p.add_argument("--goodwill", type=float, default=0)
    p.add_argument("--confidence", type=float, default=0.6)
    p.add_argument(
        "--trades", type=int, default=0, help="sample size behind win-rate (for shrinkage)"
    )
    a = p.parse_args()
    out = size_trade(
        a.equity, a.price, a.atr_pct, a.win_rate, a.payoff, a.goodwill, a.confidence, a.trades
    )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
