"""Safety-invariant property tests for the deterministic forge guards.

These are the invariants the agent's survival depends on, asserted over randomized
adversarial input (an attacker controls technique source, hence the signal decision
fields, and the market feed, hence equity/positions). We use Hypothesis because the
claims are universally-quantified ("for ALL equity <= 0 ...", "for ANY decision
without a stop ...") — example tables would leave gaps these guards must not have.

Covered:
  * ``circuit_breaker`` never trips (and never moves the high-water mark) on a bad
    equity read (equity <= 0) — a rate-limited status read must not false-flatten.
  * ``circuit_breaker`` ALWAYS trips once drawdown >= MAX_DRAWDOWN_PCT.
  * An intent built from a stop-less decision is never sized for execution
    (notional == 0) — "every perp carries a stop" enforced in code, not advice.
  * Any executable intent respects the $11 HL min notional (notional == 0 or >= 12).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import forge  # noqa: E402

# The `home` fixture seeds an isolated $GCLAW_HOME; it is intentionally NOT reset
# between generated examples (circuit_breaker accumulates a high-water mark within
# a test, which is the behavior under test). Suppress the function-scoped-fixture
# health check rather than fight it.
_FIXTURE_OK = settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated $GCLAW_HOME so circuit_breaker's breaker.json never escapes the sandbox."""
    h = tmp_path / "gclaw"
    h.mkdir()
    monkeypatch.setenv("GCLAW_HOME", str(h))
    return h


def _breaker_state(home: Path) -> dict[str, object]:
    p = home / "breaker.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _fresh_breaker(home: Path) -> None:
    """Clear any persisted high-water mark so one generated example can't poison the next.

    ``circuit_breaker`` persists ``breaker.json`` and the ``home`` fixture is reused
    across Hypothesis examples; without this reset a high HWM from a prior example
    inflates the measured drawdown of the current one (a real footgun the suppressed
    function-scoped-fixture health check is about). Each example starts from a clean
    breaker so its drawdown is measured against the HWM it sets itself.
    """
    p = home / "breaker.json"
    if p.exists():
        p.unlink()


class TestCircuitBreakerBadRead:
    """equity <= 0 means 'no read this cycle' — it must be inert, never a trip."""

    @settings(parent=_FIXTURE_OK, max_examples=200)
    @given(
        equity=st.floats(min_value=-1e9, max_value=0.0, allow_nan=False, allow_infinity=False),
        n_positions=st.integers(min_value=0, max_value=50),
    )
    def test_nonpositive_equity_never_trips(
        self, home: Path, equity: float, n_positions: int
    ) -> None:
        out = forge.circuit_breaker(equity, n_positions)
        assert out.get("skipped") == "no equity read"
        assert "allow_entry" not in out  # it short-circuits before computing entry permission

    @settings(parent=_FIXTURE_OK, max_examples=100)
    @given(
        good_equity=st.floats(min_value=1.0, max_value=1e7, allow_nan=False),
        n_positions=st.integers(min_value=0, max_value=2),
    )
    def test_bad_read_does_not_move_high_water_mark(
        self, home: Path, good_equity: float, n_positions: int
    ) -> None:
        """A spurious equity<=0 read must not raise or reset the high-water mark."""
        forge.circuit_breaker(good_equity, n_positions)  # establish HWM
        hwm_before = _breaker_state(home).get("hwm")
        forge.circuit_breaker(0.0, n_positions)  # the bad read
        forge.circuit_breaker(-123.45, n_positions)
        assert _breaker_state(home).get("hwm") == hwm_before

    def test_trip_survives_a_subsequent_bad_read(self, home: Path) -> None:
        """Once tripped on a real drawdown, a bad read keeps the breaker tripped."""
        forge.circuit_breaker(100.0, 0)
        tripped = forge.circuit_breaker(70.0, 0)  # 30% drawdown >= 25%
        assert tripped["allow_entry"] is False
        after_bad = forge.circuit_breaker(0.0, 0)
        assert after_bad["tripped"] is True


class TestCircuitBreakerTrips:
    """The breaker must always halt entries once the drawdown breaches the cap."""

    @settings(parent=_FIXTURE_OK, max_examples=200)
    @given(
        hwm=st.floats(min_value=10.0, max_value=1e6, allow_nan=False),
        drawdown_frac=st.floats(min_value=0.25, max_value=0.99, allow_nan=False),
    )
    def test_drawdown_at_or_past_cap_blocks_entry(
        self, home: Path, hwm: float, drawdown_frac: float
    ) -> None:
        _fresh_breaker(home)
        forge.circuit_breaker(hwm, 0)  # set the high-water mark
        equity = hwm * (1 - drawdown_frac)
        if equity <= 0:
            pytest.skip("equity <= 0 is the separate bad-read path")
        out = forge.circuit_breaker(equity, 0)
        # The breaker decides on its OWN rounded drawdown_pct, so assert its exact
        # contract: entries are blocked iff that figure is at/past the cap. (Asserting
        # on the input fraction is a float knife-edge — a 25.0% target can round to
        # 24.99% and legitimately not trip.)
        assert out["allow_entry"] is (out["drawdown_pct"] < forge.MAX_DRAWDOWN_PCT)

    @settings(parent=_FIXTURE_OK, max_examples=200)
    @given(
        hwm=st.floats(min_value=100.0, max_value=1e6, allow_nan=False),
        drawdown_frac=st.floats(min_value=0.0, max_value=0.20, allow_nan=False),
    )
    def test_shallow_drawdown_allows_entry(
        self, home: Path, hwm: float, drawdown_frac: float
    ) -> None:
        _fresh_breaker(home)
        forge.circuit_breaker(hwm, 0)
        out = forge.circuit_breaker(hwm * (1 - drawdown_frac), 0)
        assert out["allow_entry"] is True

    @settings(parent=_FIXTURE_OK, max_examples=100)
    @given(n_positions=st.integers(min_value=forge.MAX_OPEN_POSITIONS, max_value=20))
    def test_too_many_positions_blocks_entry(self, home: Path, n_positions: int) -> None:
        _fresh_breaker(home)
        out = forge.circuit_breaker(1000.0, n_positions)
        assert out["allow_entry"] is False


# A decision dict an attacker-controlled signal might return, fed straight into _intent.
def _decision(action: str, stop_pct: float, confidence: float, leverage: int) -> dict[str, object]:
    return {"action": action, "stop_pct": stop_pct, "confidence": confidence, "leverage": leverage}


class TestEveryPerpCarriesAStop:
    """No stop -> no executable size. The stop is the safety floor; it can't be optional."""

    @settings(parent=_FIXTURE_OK, max_examples=300)
    @given(
        action=st.sampled_from(["long", "short"]),
        stop_pct=st.floats(
            min_value=-100.0, max_value=0.0, allow_nan=False
        ),  # absent / zero / negative
        confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        equity=st.floats(min_value=11.0, max_value=1e6, allow_nan=False),
        buying_power=st.floats(min_value=11.0, max_value=1e6, allow_nan=False),
    )
    def test_stopless_decision_is_never_sized(
        self,
        home: Path,
        action: str,
        stop_pct: float,
        confidence: float,
        equity: float,
        buying_power: float,
    ) -> None:
        intent = forge._intent(
            "t",
            "BTC",
            _decision(action, stop_pct, confidence, 5),
            "thrive",
            equity,
            cap=10,
            buying_power=buying_power,
            risk_mult=1.0,
        )
        assert intent["notional"] == 0, (
            f"a stop_pct={stop_pct} decision was sized to {intent['notional']}"
        )

    def test_vote_collector_drops_stopless_decisions(self) -> None:
        """The ensemble vote path (_coin_votes) must skip any signal with stop_pct <= 0.

        Asserts on the source as a structural guard — the executable path is gated by
        the same condition that this string check verifies, so a refactor that removes
        the guard trips this test.
        """
        src = (SCRIPTS_DIR / "forge.py").read_text(encoding="utf-8")
        assert 'float(decision.get("stop_pct") or 0) <= 0' in src, (
            "the stop-required gate in _coin_votes was removed or rewritten — re-verify "
            "that a stop-less decision can never become a live vote/intent"
        )


class TestMinNotionalEnforced:
    """An intent is either skipped (notional 0) or at/above the $11 HL minimum."""

    @settings(parent=_FIXTURE_OK, max_examples=400)
    @given(
        action=st.sampled_from(["long", "short"]),
        stop_pct=st.floats(min_value=0.1, max_value=80.0, allow_nan=False),
        confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        equity=st.floats(min_value=11.0, max_value=1e6, allow_nan=False),
        buying_power=st.floats(min_value=0.0, max_value=1e6, allow_nan=False),
        leverage=st.integers(min_value=1, max_value=20),
        risk_mult=st.floats(min_value=0.1, max_value=5.0, allow_nan=False),
        mode=st.sampled_from(["thrive", "survive", "hibernate"]),
    )
    def test_notional_is_zero_or_above_min(
        self,
        home: Path,
        action: str,
        stop_pct: float,
        confidence: float,
        equity: float,
        buying_power: float,
        leverage: int,
        risk_mult: float,
        mode: str,
    ) -> None:
        intent = forge._intent(
            "t",
            "BTC",
            _decision(action, stop_pct, confidence, leverage),
            mode,
            equity,
            cap=10,
            buying_power=buying_power,
            risk_mult=risk_mult,
        )
        notional = intent["notional"]
        assert notional == 0 or notional >= forge.MIN_NOTIONAL, (
            f"intent notional {notional} is a sub-${forge.MIN_NOTIONAL} dust trade that HL would reject"
        )

    def test_hibernate_execution_is_gated_at_run_not_in_intent(self) -> None:
        """A hibernating agent must never auto-execute — enforced at the cmd_run gate.

        Subtle but important: ``_intent`` itself does NOT zero a hibernate-mode notional.
        Because ``RISK_PCT['hibernate'] == 0`` makes ``risk_usd == 0``, the
        ``max(MIN_NOTIONAL + 1, ...)`` floor produces a $12 *intent* even in hibernate.
        That intent is harmless ONLY because the auto-execute gate in ``cmd_run`` carries
        an explicit ``mode != "hibernate"`` clause. This asserts both facts so a refactor
        that drops the gate (trusting a non-existent _intent zeroing) fails loudly here.
        """
        intent = forge._intent(
            "t",
            "BTC",
            _decision("long", 2.0, 1.0, 5),
            "hibernate",
            1000.0,
            cap=10,
            buying_power=1000.0,
            risk_mult=2.0,
        )
        assert intent["notional"] == forge.MIN_NOTIONAL + 1  # documents the floor quirk
        src = (SCRIPTS_DIR / "forge.py").read_text(encoding="utf-8")
        assert 'mode != "hibernate"' in src, (
            "the hibernate execution gate vanished from cmd_run — a hibernating agent "
            "could now open a trade; re-add the mode guard before the _execute call"
        )
