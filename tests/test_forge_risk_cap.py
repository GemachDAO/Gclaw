"""The forge sizes to the SAME per-trade risk cap riskguard.js enforces (assune-met).

The failure this pins: ``forge.py run --execute`` used to size to full notional, so a
position could open risking ~4.3% of equity — ~2.85x the 1.5% per-trade cap. riskguard.js
would then have to TRIM its own freshly-opened trade, churning fees and orphaning brackets.

The fix caps the $-at-stop in ``_intent`` BEFORE the order is built, using the cap read
from riskguard.js (one source of truth — never a duplicated constant). So:

  * ``risk_cap_pct()`` returns EXACTLY the value riskguard.js exports (RISK_CAP_PCT).
  * A would-be oversized entry is capped to that % of equity at build time — the notional
    is shrunk so risk == cap, not left oversized for the guard to trim after the fact.
  * The cap holds for ANY oversized upstream sizing (property test over the whole space).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import forge  # noqa: E402

_FIXTURE_OK = settings(
    suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated $GCLAW_HOME with a neutral metabolism (health multiplier == 1.0)."""
    h = tmp_path / ".gclaw"
    h.mkdir()
    (h / "metabolism.json").write_text(
        json.dumps({"mode": "thrive", "goodwill": 0, "seed": 1000, "gmac_balance": 1000}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GCLAW_HOME", str(h))
    return h


@pytest.fixture(autouse=True)
def _reset_cap_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cap is read once and cached on the module; reset it per test."""
    monkeypatch.setattr(forge, "_RISK_CAP_PCT", None, raising=False)


def _decision(stop_pct: float) -> dict[str, object]:
    return {"action": "long", "stop_pct": stop_pct, "confidence": 0.9, "leverage": 3}


def _riskguard_cap_pct() -> float:
    """The cap as riskguard.js itself reports it — the authority forge must match."""
    out = subprocess.run(
        ["node", str(SCRIPTS_DIR / "riskguard.js"), "cap"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return float(json.loads(out.stdout.strip().splitlines()[-1])["risk_cap_pct"])


def test_forge_reads_the_same_cap_riskguard_enforces() -> None:
    """One source of truth: forge's cap is exactly the number riskguard.js owns."""
    assert forge.risk_cap_pct() == pytest.approx(_riskguard_cap_pct())


def test_oversized_entry_is_capped_before_it_opens(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A would-be 4.3%-risk entry (the assune-met repro) is capped to 1.5% AT BUILD TIME.

    We force the brain to return the over-sized position the old flat-notional path would
    (SOL long, ~$543 notional on $190.50 equity, ~4.3% at the stop) and assert ``_intent``
    shrinks it so the entry opens already at the cap — riskguard never has to trim it.
    """
    equity = 190.50
    stop_pct = 4.75  # ATR stop distance, %
    oversized_notional = 543.0
    oversized_risk = oversized_notional * stop_pct / 100.0  # ~= $25.79, ~13.5% of equity

    def fake_brain(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "notional_usd": oversized_notional,
            "stop_distance_pct": stop_pct,
            "risk_usd": oversized_risk,
        }

    monkeypatch.setattr(forge, "_size_via_brain", fake_brain)
    intent = forge._intent(
        "t", "SOL", _decision(stop_pct), "thrive", equity, cap=3, buying_power=equity
    )

    cap_pct = forge.risk_cap_pct()
    cap_usd = equity * cap_pct / 100.0
    # The REAL position is intent["notional"] (reported cents); its $-at-stop must be
    # at or under the cap — capped before open, not trimmed after. No fudge factor: the
    # notional is floored to cents so realized risk never tips over the cap.
    realized = intent["notional"] * stop_pct / 100.0
    assert realized <= cap_usd, (
        f"entry risks ${realized:.4f} > ${cap_usd:.4f} cap ({cap_pct}% of ${equity})"
    )
    # It was shrunk to sit right at the cap (within one cent of notional rounding).
    assert realized == pytest.approx(cap_usd, abs=stop_pct / 100.0 * 0.01)
    # It really is smaller than the oversized input — the cap bound, not the margin clamp.
    assert intent["notional"] < oversized_notional


@_FIXTURE_OK
@given(
    equity=st.floats(min_value=50.0, max_value=1e6, allow_nan=False),
    stop_pct=st.floats(min_value=0.5, max_value=25.0, allow_nan=False),
    over_mult=st.floats(min_value=1.01, max_value=50.0, allow_nan=False),
)
def test_capped_for_any_oversized_sizing(
    home: Path, monkeypatch: pytest.MonkeyPatch, equity: float, stop_pct: float, over_mult: float
) -> None:
    """For ANY oversized brain output, the built entry risks <= the riskguard cap.

    buying_power is set huge so the margin clamp never binds — this isolates the
    per-trade RISK cap as the thing that must hold.
    """
    cap_usd = equity * forge.risk_cap_pct() / 100.0
    # A notional whose $-at-stop is `over_mult` times the cap — always over-cap.
    notional = (cap_usd * over_mult) / (stop_pct / 100.0)

    def fake_brain(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "notional_usd": notional,
            "stop_distance_pct": stop_pct,
            "risk_usd": notional * stop_pct / 100.0,
        }

    monkeypatch.setattr(forge, "_size_via_brain", fake_brain)
    intent = forge._intent(
        "t", "BTC", _decision(stop_pct), "thrive", equity, cap=20, buying_power=1e12
    )
    if intent["notional"] == 0:
        return  # sub-min-notional entries are dropped, which is also compliant
    realized = intent["notional"] * stop_pct / 100.0
    assert realized <= cap_usd, f"realized ${realized} over ${cap_usd} cap"
