"""Cross-sectional residual (assune-2ol.9): the beta-hedged log-price residual z of a name vs
the basket index. A name that moves exactly with the index has ~0 residual; a divergence
shows up as |z|. Majors (no index context) are untouched.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import forge  # noqa: E402


def _candles(closes: list[float]) -> list[dict[str, float]]:
    return [{"t": i * 3600000, "c": c, "h": c, "l": c, "o": c, "v": 1.0} for i, c in enumerate(closes)]


def test_name_comoving_with_noise_has_bounded_residual() -> None:
    # name co-moves with the index plus small mean-reverting noise -> residual_z is a normal,
    # bounded z-score, never a spurious blow-up (the co-movement is hedged out by beta).
    idx_closes = [100 * math.exp(0.001 * i) for i in range(80)]
    name_closes = [2 * c * (1 + 0.02 * ((i % 4) - 1.5)) for i, c in enumerate(idx_closes)]
    ctx = {i * 3600000: c for i, c in enumerate(idx_closes)}
    z = forge._residual_z_at(ctx, _candles(name_closes), 79)
    assert abs(z) <= 3.0


def test_divergence_shows_as_residual() -> None:
    # name tracks the index then jumps up at the end -> a positive residual divergence
    idx_closes = [100 + i * 0.1 for i in range(80)]
    name_closes = [c for c in idx_closes]
    name_closes[-1] *= 1.05  # a 5% dislocation on the last bar
    ctx = {i * 3600000: c for i, c in enumerate(idx_closes)}
    z = forge._residual_z_at(ctx, _candles(name_closes), 79)
    assert z > 1.0  # the name is rich vs its index-implied level


def test_no_context_is_neutral() -> None:
    # a major (no index context) reads residual 0 — never a spurious signal
    assert forge._residual_z_at(None, _candles([100.0] * 80), 79) == 0.0


def test_thin_alignment_is_neutral() -> None:
    # fewer than 20 aligned bars -> 0, not a noisy estimate
    ctx = {0: 100.0, 3600000: 101.0}
    assert forge._residual_z_at(ctx, _candles([100.0, 101.0, 102.0]), 2) == 0.0
