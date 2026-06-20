"""Exemplar: a test that uses the GCLAW_HOME + metabolism + frozen_time fixtures.

metabolism.py owns the survival state machine. These tests verify the *behavior*
the heartbeat loop branches on — mode derivation from balance, that a tick burns
exactly one heartbeat of GMAC, and that settle credits PnL, moves goodwill, and
earmarks the buy-back — all against an isolated tmp $GCLAW_HOME, never the real one.
"""

from __future__ import annotations

import argparse
import json

import pytest

import metabolism


@pytest.mark.parametrize(
    ("balance", "expected_mode"),
    [
        (1000.0, "thrive"),  # well above survival_threshold (100)
        (100.0, "thrive"),  # exactly at threshold is still thrive (< is survive)
        (99.9, "survive"),  # below threshold, still has energy
        (0.0, "hibernate"),  # depleted
        (-5.0, "hibernate"),  # overdrawn
    ],
)
def test_mode_is_derived_from_balance(metabolism_fixture, balance, expected_mode) -> None:
    state = metabolism_fixture(gmac_balance=balance)
    assert metabolism.derive_mode(state) == expected_mode


def test_tick_burns_one_heartbeat_of_gmac(gclaw_home, metabolism_fixture, frozen_time) -> None:
    metabolism_fixture(gmac_balance=500.0, heartbeats=0)
    metabolism.cmd_tick(argparse.Namespace())
    state = json.loads((gclaw_home / "metabolism.json").read_text())
    assert state["gmac_balance"] == 499.0  # heartbeat_cost == 1.0
    assert state["heartbeats"] == 1
    assert state["updated_at"] == frozen_time.isoformat(timespec="seconds")


def test_tick_is_a_noop_while_hibernating(gclaw_home, metabolism_fixture) -> None:
    """A depleted agent doesn't go further negative each heartbeat."""
    metabolism_fixture(gmac_balance=0.0, heartbeats=7)
    metabolism.cmd_tick(argparse.Namespace())
    state = json.loads((gclaw_home / "metabolism.json").read_text())
    assert state["gmac_balance"] == 0.0
    assert state["heartbeats"] == 7  # not incremented


def test_settle_profit_credits_balance_goodwill_and_buyback(gclaw_home, metabolism_fixture) -> None:
    metabolism_fixture(gmac_balance=100.0, goodwill=0, gmac_treasury_usd=0.0)
    metabolism.cmd_settle(argparse.Namespace(pnl="40", note="win"))
    state = json.loads((gclaw_home / "metabolism.json").read_text())
    assert state["gmac_balance"] == 140.0
    # GOODWILL_PROFIT_FLAT (5) + min(cap 20, round(40)) = 25
    assert state["goodwill"] == 25
    # 10% of profit earmarked for the GMAC buy-back treasury.
    assert state["gmac_treasury_usd"] == 4.0


def test_settle_loss_penalizes_goodwill_without_going_negative(
    gclaw_home, metabolism_fixture
) -> None:
    metabolism_fixture(gmac_balance=100.0, goodwill=1)
    metabolism.cmd_settle(argparse.Namespace(pnl="-30", note="stopped out"))
    state = json.loads((gclaw_home / "metabolism.json").read_text())
    assert state["gmac_balance"] == 70.0
    assert state["goodwill"] == 0  # max(0, 1 - 2), never negative
    assert state["gmac_treasury_usd"] == 0.0  # no buy-back on a loss


def test_load_state_fails_fast_when_unborn(gclaw_home) -> None:
    """No metabolism.json → a clear birth instruction, not a stack trace."""
    with pytest.raises(SystemExit, match="init"):
        metabolism.load_state()


def test_apply_goodwill_profit_is_capped(metabolism_fixture) -> None:
    state = metabolism_fixture(goodwill=0)
    delta = metabolism.apply_goodwill(state, pnl=10_000.0)
    assert delta == metabolism.GOODWILL_PROFIT_FLAT + metabolism.GOODWILL_PROFIT_CAP
