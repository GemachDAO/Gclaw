#!/usr/bin/env python3
"""feature_parity — does the backtest reconstruct features the way live intel.js sees them?

``forge._intel_features_at`` claims to mirror ``intel.js coinIntel`` 1:1, but two
divergences were found: it used population stdev (``pstdev``) for realized_vol_pct
where intel.js uses sample stdev, and it computed the EMAs over the whole expanding
candle history instead of intel.js's fixed ~120-bar window. Any technique validated
on features computed one way but traded on features computed another is exposed to
train/serve skew — a backtest-proven, live-dead failure mode.

This eval builds a reference from intel.js's exact definitions (the fixed 120-bar
window + sample stdev, using forge's own — audit-verified-correct — indicator
helpers) and compares it to ``forge._intel_features_at`` across many bars. Any
per-feature divergence above tolerance means the two implementations disagree.

Run:  uv run --no-project python3 evals/feature_parity.py
Exit: 0 if every feature matches the live definition, 1 on any skew.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import forge  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
COIN = "BTC"
INTERVAL = "1h"
LIMIT = 1000
WINDOW = 120  # intel.js coinIntel: candles(coin,'1h',121).slice(0,-1) -> 120 closed bars
# Compared features and per-feature absolute tolerance (features are rounded in-code).
TOLERANCE = {
    "ema_stack": 0,  # a discrete -2..+2 label — must match exactly
    "rsi": 0.11,
    "atr_pct": 0.02,
    "realized_vol_pct": 0.02,
    "efficiency": 0.02,
    "bb_z": 0.02,
}


def intel_ref(candles: list[dict[str, float]], i: int) -> dict[str, Any]:
    """Reference features per intel.js coinIntel's exact definitions at bar ``i``.

    Uses the fixed 120-bar window and SAMPLE stdev intel.js uses, driving forge's own
    indicator helpers (RSI/ATR/EMA/efficiency are audit-verified correct — only the
    window and the stdev variant differed).
    """
    closes = [c["c"] for c in candles[: i + 1]][-WINDOW:]
    wc = candles[: i + 1][-WINDOW:]
    e9, e21, e50 = forge._ema(closes[-40:], 9), forge._ema(closes[-60:], 21), forge._ema(closes, 50)
    win20 = closes[-20:]
    sd20 = statistics.stdev(win20) if len(win20) > 1 else 0.0
    bb_z = (closes[-1] - statistics.fmean(win20)) / sd20 if sd20 else 0.0
    rets24 = [closes[k] / closes[k - 1] - 1 for k in range(max(1, len(closes) - 23), len(closes))]
    return {
        "ema_stack": (1 if e9 > e21 else -1) + (1 if e21 > e50 else -1),
        "rsi": round(forge._wilder_rsi(closes) * 10) / 10,
        "atr_pct": round(forge._wilder_atr_pct(wc) * 100) / 100,
        "realized_vol_pct": round(statistics.stdev(rets24) * 100 * 100) / 100 if len(rets24) > 1 else 0.0,
        "efficiency": round(forge._efficiency_ratio(closes) * 100) / 100,
        "bb_z": round(bb_z * 100) / 100,
    }


def main() -> int:
    path = FIXTURES / f"candles_{COIN}_{INTERVAL}_{LIMIT}.json"
    if not path.exists():
        candles = forge.get_candles(COIN, INTERVAL, LIMIT)
        FIXTURES.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(candles), encoding="utf-8")
    candles = json.loads(path.read_text(encoding="utf-8"))

    bars = list(range(WINDOW, len(candles), 10))  # only bars with a full live window
    worst = {k: 0.0 for k in TOLERANCE}
    mismatches = {k: 0 for k in TOLERANCE}
    for i in bars:
        got = forge._intel_features_at(candles, i)
        ref = intel_ref(candles, i)
        for k in TOLERANCE:
            d = abs(float(got[k]) - float(ref[k]))
            worst[k] = max(worst[k], d)
            if d > TOLERANCE[k]:
                mismatches[k] += 1

    print("=" * 60)
    print("feature_parity — forge backtest vs live intel.js definition")
    print("=" * 60)
    print(f"{COIN} {INTERVAL}, {len(bars)} sampled bars (window={WINDOW})\n")
    print(f"{'feature':<18}{'max |diff|':>12}{'tol':>8}{'mismatches':>12}")
    ok = True
    for k in TOLERANCE:
        flag = "" if mismatches[k] == 0 else "  <- SKEW"
        print(f"{k:<18}{worst[k]:>12.4f}{TOLERANCE[k]:>8}{mismatches[k]:>10}/{len(bars)}{flag}")
        ok = ok and mismatches[k] == 0
    print(f"\nVERDICT: {'PASS' if ok else 'FAIL'}  (backtest features "
          f"{'match' if ok else 'DIVERGE from'} the live definition)")
    if "--json" in sys.argv:
        print(json.dumps({
            "eval": "feature_parity", "worst": worst,
            "total_mismatches": sum(mismatches.values()), "verdict": "PASS" if ok else "FAIL",
        }))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
