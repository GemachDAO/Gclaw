#!/usr/bin/env python3
"""judge_power — does the forge JUDGE certify signals that have no real edge?

The forge "proven" gate (``forge._backtest_with``) is the only thing between a
self-authored technique and real capital. Its rule is::

    proven = oos_n >= 20 and oos_mean > 0 and is_mean > 0

There is no significance test, no effect-size floor, and ``autoprove`` runs it
against dozens of coins with no multiple-comparisons control. The live symptom
is 37 ``proven_markets`` pairs from 7 techniques with 0 confirmed live.

We probe the gate the way the real pipeline fails: structured TA signals (no
established edge) run against SURROGATE candles — block-bootstrapped series that
keep each coin's return distribution and short-range autocorrelation but destroy
the long-range structure a signal could genuinely exploit. On surrogates every
"proven" verdict is a false positive, so the certification rate IS the gate's
false-positive rate. A sound significance-gated JUDGE certifies <= alpha of
these; a powerless one certifies many.

(An earlier version used random per-bar entries and the gate correctly rejected
them all — fees give symmetric noise negative drift. That is the wrong null: it
misses the look-elsewhere effect on clustered, structured bets, which is the
real failure mode here.)

Because it drives ``forge._backtest_with`` directly, re-running after the gate
gains a bootstrap-CI + effect-size test automatically re-scores the new gate.

Run:  uv run --no-project python3 evals/judge_power.py
Exit: 0 if surrogate-FPR <= FPR_TARGET, 1 if the gate certifies structureless data.
"""

from __future__ import annotations

import json
import random
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import forge  # noqa: E402
import memory  # noqa: E402  (forge's dependency; the gate's bootstrap CI lives here)

# The gate calls memory._bootstrap_ci at its production 2000 iters — too heavy to run a few
# hundred times in an eval. The ci_lo>0 verdict is statistically near-identical at 500 iters
# and FPR is a rate that averages out per-decision resample noise, so run the gate LOGIC
# unchanged at a lighter resample count purely for the eval's runtime.
EVAL_CI_ITERS = 500
_orig_ci = memory._bootstrap_ci
memory._bootstrap_ci = lambda rs, iters=EVAL_CI_ITERS: _orig_ci(rs, iters)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
COINS = ("BTC", "ETH", "SOL", "xyz:MSTR", "xyz:DRAM", "xyz:MU")
INTERVAL = "1h"
LIMIT = 700
SURROGATES = 15  # block-bootstrap draws per (signal, coin) — kept modest so the eval,
# which drives the real gate incl. its 2000-iter bootstrap CI, stays runnable routinely
BLOCK = 24
STOP_PCT = 1.5
FPR_TARGET = 0.075  # a significance-gated JUDGE certifies structureless data at ~alpha


def _decide(action: str) -> dict[str, Any]:
    return {"action": action, "confidence": 0.6, "leverage": 1, "stop_pct": STOP_PCT}


def _meanrev(f: dict[str, Any]) -> dict[str, Any]:
    r4 = f.get("ret4") or 0
    return _decide("long" if r4 < -0.02 else "short" if r4 > 0.02 else "flat")


def _momentum(f: dict[str, Any]) -> dict[str, Any]:
    r24 = f.get("ret24") or 0
    return _decide("long" if r24 > 0.03 else "short" if r24 < -0.03 else "flat")


def _rsi_rev(f: dict[str, Any]) -> dict[str, Any]:
    rsi = f.get("rsi")
    if rsi is None:
        return _decide("flat")
    return _decide("long" if rsi < 35 else "short" if rsi > 65 else "flat")


NULL_SIGNALS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "meanrev-ret4": _meanrev,
    "momentum-ret24": _momentum,
    "rsi-reversion": _rsi_rev,
}


def load_fixture(coin: str, fetch: Callable[..., list[dict[str, float]]]) -> list[dict[str, float]]:
    """Return cached candles for ``coin``, fetching + caching on first use."""
    safe = coin.replace(":", "_")
    path = FIXTURES / f"candles_{safe}_{INTERVAL}_{LIMIT}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    candles = fetch(coin, INTERVAL, LIMIT)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(candles), encoding="utf-8")
    return candles


def block_bootstrap(candles: list[dict[str, float]], rng: random.Random) -> list[dict[str, float]]:
    """Surrogate series: block-resample returns, keep each bar's intrabar shape.

    Preserves the return distribution and ``BLOCK``-bar autocorrelation but
    shuffles the macro sequence, so any multi-bar pattern a signal exploits is
    destroyed — a genuinely edgeless price path with realistic bars.
    """
    ratios = []
    for k in range(1, len(candles)):
        c, cp = candles[k]["c"], candles[k - 1]["c"]
        if cp <= 0 or c <= 0:
            continue
        ratios.append((c / cp, candles[k]["h"] / c, candles[k]["l"] / c, candles[k]["o"] / c))
    seq: list[tuple[float, float, float, float]] = []
    while len(seq) < len(candles) - 1:
        start = rng.randrange(0, max(1, len(ratios) - BLOCK))
        seq.extend(ratios[start : start + BLOCK])
    seq = seq[: len(candles) - 1]
    first = candles[0]
    out = [{"o": first["o"], "h": first["h"], "l": first["l"], "c": first["c"]}]
    running = first["c"]
    for r, hr, lr, orr in seq:
        running *= r
        out.append({"o": running * orr, "h": running * hr, "l": running * lr, "c": running})
    return out


def run_gate(candles: list[dict[str, float]], coin: str, fn: Callable[..., Any]) -> bool:
    """Drive the real forge gate on one candle series; return its proven verdict."""
    forge.get_candles = lambda _c, _i, _l: candles
    try:
        return bool(forge._backtest_with(fn, coin, INTERVAL, LIMIT)["proven"])
    except (ValueError, SystemExit):
        return False


def main() -> int:
    real_get = forge.get_candles
    reals = {c: load_fixture(c, real_get) for c in COINS}

    print("=" * 68)
    print("judge_power — JUDGE certification rate on structureless surrogate data")
    print("=" * 68)
    print(f"gate: proven = oos n>={forge.MIN_OOS_SAMPLE} & oos ci_lo>0 & is n>={forge.MIN_IS_SAMPLE} & is mean>0")
    print(f"{SURROGATES} surrogates/coin x {len(COINS)} coins x {len(NULL_SIGNALS)} structured nulls\n")

    total = proven_total = 0
    print(f"{'signal':<16}{'real proven':>13}{'surrogate proven':>18}{'FPR':>8}")
    for name, fn in NULL_SIGNALS.items():
        real_hits = sum(run_gate(reals[c], c, fn) for c in COINS)
        sur_hits = sur_runs = 0
        for c in COINS:
            rng = random.Random(hash((name, c)) & 0xFFFFFFFF)
            for _ in range(SURROGATES):
                sur_hits += run_gate(block_bootstrap(reals[c], rng), c, fn)
                sur_runs += 1
        total += sur_runs
        proven_total += sur_hits
        fpr = sur_hits / sur_runs if sur_runs else 0.0
        print(f"{name:<16}{real_hits:>6}/{len(COINS):<6}{sur_hits:>10}/{sur_runs:<6}{fpr:>7.1%}")

    fpr = proven_total / total if total else 0.0
    print("-" * 55)
    print(f"{'ALL':<16}{'':>13}{proven_total:>10}/{total:<6}{fpr:>7.1%}")
    mc = 1 - (1 - fpr) ** 30
    print(f"\nsurrogate-FPR {fpr:.1%} per (signal,coin). Under autoprove's ~30-coin sweep,")
    print(f"P(a null signal is 'proven' on >=1 coin) = 1-(1-{fpr:.3f})^30 = {mc:.0%}.")
    verdict = "PASS" if fpr <= FPR_TARGET else "FAIL"
    print(f"\nVERDICT: {verdict}  (surrogate-FPR {fpr:.1%} vs target <={FPR_TARGET:.1%})")
    if "--json" in sys.argv:  # additive: a final machine-readable line for the harness grader
        print(json.dumps({"eval": "judge_power", "fpr": fpr, "target": FPR_TARGET, "verdict": verdict}))
    return 0 if fpr <= FPR_TARGET else 1


if __name__ == "__main__":
    raise SystemExit(main())
