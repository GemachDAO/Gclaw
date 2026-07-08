"""The panel-pooled significance machinery (assune-2ol.2): Benjamini-Hochberg FDR must
reject only the significant tail of a batch, and _window_trades must reproduce exactly the
returns score_window summarises (the refactor is behaviour-preserving).
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import forge  # noqa: E402


def test_bh_fdr_rejects_only_the_significant_tail() -> None:
    assert forge._bh_fdr([0.9, 0.8, 0.95, 0.7], 0.1) == [False, False, False, False]
    assert forge._bh_fdr([0.001, 0.8, 0.9, 0.7], 0.1) == [True, False, False, False]
    assert forge._bh_fdr([0.001, 0.01, 0.9, 0.7, 0.8], 0.1) == [True, True, False, False, False]
    assert forge._bh_fdr([]) == []


def test_bh_fdr_is_monotone_in_alpha() -> None:
    pv = [0.02, 0.03, 0.2, 0.5]
    strict = forge._bh_fdr(pv, 0.01)
    loose = forge._bh_fdr(pv, 0.2)
    # a looser FDR can only reject a superset of a stricter one
    assert all((not s) or lo for s, lo in zip(strict, loose, strict=True))


def test_window_trades_returns_match_score_window() -> None:
    # A deterministic synthetic series; _window_trades' returns must be exactly what
    # score_window summarises, or the refactor silently changed the JUDGE.
    candles = [{"c": 100 + (k % 7) - 3, "h": 105, "l": 95, "t": k} for k in range(200)]

    def sig(f):
        return {"action": "long", "confidence": 0.5, "leverage": 1, "stop_pct": 50.0, "reason": "x"}

    trades = forge._window_trades(candles, sig, "X", forge.WARMUP, 190, forge.HORIZON)
    summ = forge.score_window(candles, sig, "X", forge.WARMUP, 190, forge.HORIZON)
    assert summ["n"] == len(trades)
    if trades:
        # summarise() rounds expectancy to 6 dp, so compare within that rounding
        assert abs(summ["expectancy"] - sum(t["r"] for t in trades) / len(trades)) < 1e-6
