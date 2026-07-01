"""Tests for the maker/taker cost model and the cold-start gate-reachability fix.

Two behaviours are pinned here, both from the "un-stick the inert organism" work:

  * The graduation backtest charges a REALISTIC per-side execution cost — a taker fill
    on a market entry/stop, a maker fill on a resting-limit entry/TP. A resting-limit
    round trip must cost strictly less than a market round trip, and the default (no
    maker flag) must match the live executor's taker fill so the cost assumption never
    diverges from how orders actually fill.
  * A technique with a genuine two-sided edge that is merely THIN (gross edge below the
    taker round trip) graduates once the maker cost model is applied — WITHOUT lowering
    the graduation bar (oos_exp>0 AND is_exp>0 stays); and the live cold-start gate keeps
    probing a still-bootstrapping technique instead of benching it after 3 trades (the
    cold-start-forever sibling bug). Pure noise (no two-sided edge) still never graduates.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import forge  # noqa: E402


@pytest.fixture(autouse=True)
def _taker_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default every test to the live executor's taker mode unless it opts into maker."""
    monkeypatch.delenv("GCLAW_FORGE_MAKER_ENTRY", raising=False)


# ── round_trip_cost: the maker/taker distinction ────────────────────────────


def test_taker_default_matches_live_executor_round_trip():
    """Default (no maker flag) charges taker on both legs — matches hl_perp.js isMarket:true."""
    assert forge._maker_entry() is False
    assert forge.round_trip_cost(stop_hit=False) == pytest.approx(2 * forge.TAKER_FEE)
    assert forge.round_trip_cost(stop_hit=True) == pytest.approx(2 * forge.TAKER_FEE)


def test_maker_entry_round_trip_is_cheaper_than_taker(monkeypatch: pytest.MonkeyPatch):
    """A resting-limit entry+TP round trip costs strictly less than a market round trip."""
    taker_rt = forge.round_trip_cost(stop_hit=False)
    monkeypatch.setenv("GCLAW_FORGE_MAKER_ENTRY", "1")
    maker_rt = forge.round_trip_cost(stop_hit=False)
    assert maker_rt < taker_rt
    assert maker_rt == pytest.approx(2 * forge.MAKER_FEE)


def test_stop_hit_exit_is_always_taker(monkeypatch: pytest.MonkeyPatch):
    """A stop is a trigger/market fill: its exit leg is taker even in maker-entry mode."""
    monkeypatch.setenv("GCLAW_FORGE_MAKER_ENTRY", "1")
    stopped = forge.round_trip_cost(stop_hit=True)
    clean = forge.round_trip_cost(stop_hit=False)
    assert stopped == pytest.approx(forge.MAKER_FEE + forge.TAKER_FEE)
    assert stopped > clean  # the stop leg costs the taker fee, not the maker rebate


def test_maker_fee_below_taker_fee():
    """Sanity on the fee tiers themselves: maker rebate tier < taker fee tier."""
    assert 0 < forge.MAKER_FEE < forge.TAKER_FEE


# ── the cost model feeding graduation, over a synthetic edged technique ──────


def _thin_edge_candles(n: int = 400) -> list[dict[str, float]]:
    """A price series a mean-reversion signal harvests a THIN but genuine two-sided edge
    from: every bar dips then closes up ~10bp. The raw per-trade edge (~10bp) sits BELOW
    a taker round trip (~15bp) but ABOVE a maker round trip (~3bp) — exactly the fee-wall
    case. Deterministic, no randomness, so the graduation verdict is reproducible."""
    candles = []
    price = 100.0
    for _ in range(n):
        low = price * 0.998
        close = price * 1.001  # +10bp per bar, never hits a 1% stop
        high = close * 1.0005
        candles.append({"o": price, "h": high, "l": low, "c": close})
        price = close
    return candles


def _always_long(_f: dict) -> dict:
    return {"action": "long", "confidence": 0.7, "leverage": 2, "stop_pct": 1.0, "reason": "t"}


def _score(candles, maker: bool, monkeypatch) -> dict:
    if maker:
        monkeypatch.setenv("GCLAW_FORGE_MAKER_ENTRY", "1")
    else:
        monkeypatch.delenv("GCLAW_FORGE_MAKER_ENTRY", raising=False)
    return forge.score_window(candles, _always_long, "SYN", forge.WARMUP, len(candles) - 1, 1)


def test_thin_edge_is_negative_under_taker_but_positive_under_maker(
    monkeypatch: pytest.MonkeyPatch,
):
    """The fee wall, pinned: a ~10bp/bar edge nets NEGATIVE after a taker round trip and
    POSITIVE after a maker round trip. The maker model lets a real edge clear the fee —
    the graduation rule (expectancy>0) is untouched; only the cost the edge beats changed.
    """
    candles = _thin_edge_candles()
    taker = _score(candles, maker=False, monkeypatch=monkeypatch)
    maker = _score(candles, maker=True, monkeypatch=monkeypatch)
    assert taker["n"] == maker["n"] > 20
    assert taker["expectancy"] < 0 < maker["expectancy"]


def test_pure_noise_never_graduates_under_maker(monkeypatch: pytest.MonkeyPatch):
    """The honest guard: a flat price (zero raw edge) stays NEGATIVE even under the cheap
    maker cost — the model lowers the wall, it does not fabricate edge from noise."""
    flat = [{"o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0} for _ in range(400)]
    maker = _score(flat, maker=True, monkeypatch=monkeypatch)
    assert maker["expectancy"] <= 0


# ── the cold-start gate-reachability fix (assune-4fw.2) ──────────────────────

CAPS = {"conviction_cap": 0.614, "agree_min": 0.608, "conv_min": 0.23}


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A $GCLAW_HOME with no cooldown files so _cooling never blocks the gated intent."""
    h = tmp_path / "gclaw"
    h.mkdir()
    monkeypatch.setenv("GCLAW_HOME", str(h))
    return h


def _intent(trades: int, *, edge_real: bool = False, conf: float = 0.6) -> dict:
    """A gate-ready intent for a proven major, with a pre-stashed memory read."""
    return {
        "technique": "t", "coin": "SOL", "side": "long", "leverage": 2, "sl_pct": 1.0,
        "confidence": conf, "notional": 30.0, "proven": True, "regime": "range",
        "edge_real_mem": edge_real, "edge_trades_mem": trades,
    }


def test_cold_start_probes_a_still_bootstrapping_technique(isolated_home: Path):
    """A proven technique with 4 live trades and no edge_real yet (still inside the
    MIN_LIVE_SAMPLE window) is NOT benched — it earns a bounded half-size probe. This is
    the reachability fix: the old <3 window locked it out at trade 3 forever."""
    assert forge.MIN_LIVE_SAMPLE > 4  # premise of the test
    gated = forge._gate_intents([_intent(trades=4)], CAPS, {})
    assert len(gated) == 1
    assert gated[0].get("cold_start") is True
    assert gated[0]["notional"] == pytest.approx(15.0)  # half-size probe


def test_edge_real_technique_executes_full_size(isolated_home: Path):
    """A technique whose memory shows edge_real executes at FULL size — the probe halving
    applies only while it is still cold, never to a proven-live edge."""
    gated = forge._gate_intents([_intent(trades=8, edge_real=True)], CAPS, {})
    assert len(gated) == 1
    assert gated[0].get("cold_start") is not True
    assert gated[0]["notional"] == pytest.approx(30.0)


def test_matured_technique_without_edge_real_is_benched(isolated_home: Path):
    """Past the bootstrap window (>=MIN_LIVE_SAMPLE trades) with no edge_real, the
    technique HAS been fairly measured and is benched — the gate stays REAL, it does not
    probe a measured non-edge forever."""
    gated = forge._gate_intents(
        [_intent(trades=forge.MIN_LIVE_SAMPLE, edge_real=False)], CAPS, {}
    )
    assert gated == []


def test_low_conviction_cold_start_is_rejected(isolated_home: Path):
    """The gate stays REAL on the conviction axis too: a cold technique below the
    genome-tuned floor (0.75*cap) never probes, no matter how cold."""
    conv_floor = 0.75 * CAPS["conviction_cap"]
    gated = forge._gate_intents([_intent(trades=2, conf=conv_floor - 0.05)], CAPS, {})
    assert gated == []
