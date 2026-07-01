"""Behavior tests for forge perp sizing against the cross-collateral pool (assune-4fw.5).

This HL account is CROSS-COLLATERAL: a perp draws its margin from the spot USDC pool
(the margin shows as a spot ``hold`` AND inside the perp ``accountValue`` — hl_perp.js's
two-wallet equity formula). So ``forge._account`` must report the FREE spot USDC
(``buyingPower`` = spot total − hold) as ``buying_power`` — the capital a new perp can
actually draw — NOT the perp-only ``withdrawable`` (which reads $0 whenever margin is
deployed even though ample spot backs it). Sizing off ``withdrawable`` starved every
major to $0 notional; sizing off ``buyingPower`` is correct and is what let a live probe
open.

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


class TestAccountUsesFreeSpotCollateral:
    """buying_power must be the FREE spot USDC (buyingPower), the cross-collateral pool."""

    def test_capital_in_spot_is_usable_perp_collateral(self, monkeypatch) -> None:
        # The live state: $176 in spot backing a small perp position (perp margin is
        # drawn from spot). withdrawable reads $0 while margin is deployed, but the
        # ~$172 free spot IS the collateral a new perp can draw.
        monkeypatch.setattr(
            forge.subprocess,
            "run",
            lambda *a, **k: _status(
                equity=176.0,
                spotUsdc=176.0,
                buyingPower=172.0,
                accountValue=4.0,
                withdrawable=0.0,
                positions=[{"coin": "ETH"}],
            ),
        )
        acct = forge._account()
        assert acct["buying_power"] == 172.0, (
            "free spot USDC (buyingPower) is the cross-collateral a perp draws margin from; "
            "sizing off withdrawable=$0 wrongly starves every major to $0 notional"
        )
        assert acct["equity"] == 176.0
        assert acct["positions"] == 1

    def test_buying_power_tracks_free_spot_after_hold(self, monkeypatch) -> None:
        # hl_perp.js already nets the margin hold out of buyingPower; forge just uses it.
        monkeypatch.setattr(
            forge.subprocess,
            "run",
            lambda *a, **k: _status(
                equity=200.0,
                spotUsdc=200.0,
                buyingPower=20.0,
                accountValue=180.0,
                withdrawable=0.0,
                positions=[{"coin": "BTC"}],
            ),
        )
        acct = forge._account()
        assert acct["buying_power"] == 20.0
        assert acct["equity"] == 200.0

    def test_missing_buying_power_is_conservative_zero(self, monkeypatch) -> None:
        # A partial/rate-limited read that omits buyingPower must NOT fall back to equity
        # (the old bug) — an unknown free balance is treated as $0 tradeable collateral.
        monkeypatch.setattr(
            forge.subprocess,
            "run",
            lambda *a, **k: _status(equity=176.0, spotUsdc=176.0, accountValue=4.0),
        )
        assert forge._account()["buying_power"] == 0.0


class TestIntentSizesAgainstBuyingPower:
    """The margin-fit clamp: zero collateral => zero notional; funded => a real notional."""

    def _decision(self) -> dict[str, object]:
        return {"action": "long", "stop_pct": 2.0, "confidence": 1.0, "leverage": 3}

    def test_zero_collateral_zeroes_a_valid_major_intent(self, gclaw_home: Path) -> None:
        intent = forge._intent(
            "t",
            "ETH",
            self._decision(),
            "thrive",
            equity=176.0,
            cap=3,
            buying_power=0.0,
            intel={"atr_pct": 1.5, "price": 1600.0},
            edge={"win_rate": 0.6, "payoff": 1.5, "trades": 40},
        )
        assert intent["notional"] == 0, (
            "a major sized with $0 free collateral must clamp to 0, not a phantom notional"
        )

    def test_funded_collateral_sizes_a_real_major_notional(self, gclaw_home: Path) -> None:
        intent = forge._intent(
            "t",
            "ETH",
            self._decision(),
            "thrive",
            equity=176.0,
            cap=3,
            buying_power=150.0,
            intel={"atr_pct": 1.5, "price": 1600.0},
            edge={"win_rate": 0.6, "payoff": 1.5, "trades": 40},
        )
        assert intent["notional"] >= forge.MIN_NOTIONAL, (
            "with ample cross-collateral a proven major must size to a real, fillable notional"
        )
