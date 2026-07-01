"""Behavior tests for the spot/perp collateral split (assune-4fw.5).

HL keeps spot and perp as SEPARATE wallets; spot USDC is NOT auto-pledged as perp
margin. ``forge._account`` must therefore report the PERP wallet's free collateral
(``withdrawable``) as ``buying_power`` — the capital a new perp can actually draw as
margin — not the spot ``buyingPower``. Sizing a perp off spot buying power the perp
cannot touch produces an intent HL rejects for insufficient margin.

These tests mock only the ``hl_perp.js status`` subprocess (an external-process
boundary); the sizing/clamp logic under test runs for real.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import forge  # noqa: E402


def _status(**fields: object) -> SimpleNamespace:
    """A fake CompletedProcess whose stdout is one JSON line, like hl_perp.js status."""
    return SimpleNamespace(stdout=json.dumps(fields) + "\n", returncode=0)


class TestAccountUsesPerpFreeCollateral:
    """buying_power must be the perp wallet's withdrawable, never the spot balance."""

    def test_all_capital_in_spot_reads_zero_perp_buying_power(self, monkeypatch) -> None:
        # The live .5 state: $176 in spot, perp fully consumed by a position.
        monkeypatch.setattr(
            forge.subprocess,
            "run",
            lambda *a, **k: _status(
                equity=176.0, spotUsdc=176.0, buyingPower=176.0,
                accountValue=4.0, withdrawable=0.0, positions=[{"coin": "ETH"}],
            ),
        )
        acct = forge._account()
        assert acct["buying_power"] == 0.0, (
            "spot USDC was treated as perp margin — a perp sized off it is unfillable"
        )
        # equity stays whole-account for the breaker / health sizing.
        assert acct["equity"] == 176.0
        assert acct["positions"] == 1

    def test_perp_funded_reads_perp_free_collateral(self, monkeypatch) -> None:
        monkeypatch.setattr(
            forge.subprocess,
            "run",
            lambda *a, **k: _status(
                equity=200.0, spotUsdc=20.0, buyingPower=20.0,
                accountValue=180.0, withdrawable=150.0, positions=[],
            ),
        )
        acct = forge._account()
        assert acct["buying_power"] == 150.0
        assert acct["equity"] == 200.0

    def test_missing_withdrawable_is_conservative_zero(self, monkeypatch) -> None:
        # A partial/rate-limited read that omits withdrawable must NOT fall back to
        # equity (the old bug) — an unknown perp balance is treated as $0 margin.
        monkeypatch.setattr(
            forge.subprocess,
            "run",
            lambda *a, **k: _status(equity=176.0, spotUsdc=176.0, buyingPower=176.0),
        )
        assert forge._account()["buying_power"] == 0.0


class TestIntentZeroesWhenPerpUnfunded:
    """The margin-fit clamp: zero perp collateral => zero notional, regardless of edge."""

    def _decision(self) -> dict[str, object]:
        return {"action": "long", "stop_pct": 2.0, "confidence": 1.0, "leverage": 3}

    def test_zero_perp_collateral_zeroes_a_valid_major_intent(self, gclaw_home: Path) -> None:
        intent = forge._intent(
            "t", "ETH", self._decision(), "thrive",
            equity=176.0, cap=3, buying_power=0.0,
            intel={"atr_pct": 1.5, "price": 1600.0},
            edge={"win_rate": 0.6, "payoff": 1.5, "trades": 40},
        )
        assert intent["notional"] == 0, (
            "a major sized with $0 perp margin must clamp to 0, not a phantom notional"
        )

    def test_funded_perp_sizes_a_real_major_notional(self, gclaw_home: Path) -> None:
        intent = forge._intent(
            "t", "ETH", self._decision(), "thrive",
            equity=176.0, cap=3, buying_power=150.0,
            intel={"atr_pct": 1.5, "price": 1600.0},
            edge={"win_rate": 0.6, "payoff": 1.5, "trades": 40},
        )
        assert intent["notional"] == 0 or intent["notional"] >= forge.MIN_NOTIONAL
