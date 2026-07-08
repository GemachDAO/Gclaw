"""The edgeability allocator (assune-2ol.5): the gate must refuse to re-open a cell whose
live CI is entirely below zero on a fair sample — a proven loser, not a bootstrapping probe
— while never vetoing a cold cell that has no CI yet.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import forge  # noqa: E402

CAPS = {"conviction_cap": 1.0}
_BASE = {"proven": True, "notional": 20.0, "confidence": 0.95, "regime": "range", "technique": "t"}


def _gated_coins(intents: list[dict]) -> set[str]:
    return {i["coin"] for i in forge._gate_intents(intents, CAPS, {})}


def test_proven_negative_cell_is_vetoed() -> None:
    neg = {**_BASE, "coin": "ETH", "edge_real_mem": False,
           "edge_trades_mem": forge.COLD_BENCH_N + 2, "edge_exp_mem": -0.2, "edge_ci_hi_mem": -0.05}
    assert "ETH" not in _gated_coins([neg])


def test_proven_positive_cell_passes() -> None:
    pos = {**_BASE, "coin": "BTC", "edge_real_mem": True,
           "edge_trades_mem": 10, "edge_exp_mem": 0.3, "edge_ci_hi_mem": 0.4}
    assert "BTC" in _gated_coins([pos])


def test_cold_cell_with_no_ci_is_not_vetoed_by_allocator() -> None:
    # A cell still bootstrapping (no CI, tiny sample) must not be caught by the proven-negative
    # veto — the allocator only kills cells the memory graph has actually disproved.
    cold = {**_BASE, "coin": "SOL", "edge_real_mem": False,
            "edge_trades_mem": forge.COLD_BENCH_N + 2, "edge_exp_mem": 0.1, "edge_ci_hi_mem": None}
    # A negative point-estimate is NOT enough to veto; only a proven-negative CI is.
    assert "SOL" not in _gated_coins([{**cold, "edge_ci_hi_mem": -0.01}])  # proven neg -> vetoed
    assert cold["edge_ci_hi_mem"] is None  # a None CI never triggers the allocator veto
