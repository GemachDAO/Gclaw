"""No-double-spend / no-double-settle tests for the metabolism ledger (metabolism.py).

GMAC and the real buy-back treasury change ONLY through metabolism.py — that is the
single chokepoint the whole money model depends on. Two invariants matter here:

  * ``gmac --spend`` (the treasury debit gmac_buy.js calls after a confirmed onchain
    buy) can never spend more than the treasury holds, and each spend debits exactly
    once. A forgotten/duplicated manual record must not double-decrement the ETH.
  * ``settle`` books realized PnL into the balance, accrues the 10% buy-back, and
    adjusts goodwill — driven by autosettle's deduped fills, so the no-double-settle
    guarantee upstream means each close hits settle once. We assert settle's own
    arithmetic is exact and that the buy-back treasury only ever grows on profit.

These run against an isolated $GCLAW_HOME (the ``metabolism`` fixture seeds state).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import metabolism  # noqa: E402


def _run(argv: list[str]) -> dict:
    """Invoke metabolism via its real argv parser and return the resulting state dict."""
    parser = metabolism.build_parser()
    args = parser.parse_args(argv)
    return metabolism.COMMANDS[args.command](args)


def _state(home: Path) -> dict:
    return json.loads((home / "metabolism.json").read_text(encoding="utf-8"))


class TestNoDoubleSpend:
    """The treasury debit guard — the load-bearing anti-double-spend control."""

    def test_spend_within_treasury_debits_once(self, metabolism_fixture: object) -> None:
        metabolism_fixture(gmac_treasury_usd=10.0)
        out = _run(["gmac", "--spend", "4", "--tokens", "100", "--tx", "0xabc"])
        assert out["gmac_treasury_usd"] == 6.0
        assert out["gmac_tokens_held"] == 100.0

    def test_spend_exceeding_treasury_is_rejected(self, metabolism_fixture: object) -> None:
        metabolism_fixture(gmac_treasury_usd=3.0)
        with pytest.raises(SystemExit) as exc:
            _run(["gmac", "--spend", "5", "--tokens", "100", "--tx", "0xabc"])
        assert "exceeds treasury" in str(exc.value)

    def test_rejected_spend_leaves_treasury_untouched(
        self, gclaw_home: Path, metabolism_fixture: object
    ) -> None:
        metabolism_fixture(gmac_treasury_usd=3.0, gmac_tokens_held=0.0)
        with pytest.raises(SystemExit):
            _run(["gmac", "--spend", "5", "--tokens", "100", "--tx", "0xabc"])
        # No partial debit, no phantom tokens — the failed buy must be a no-op.
        st = _state(gclaw_home)
        assert st["gmac_treasury_usd"] == 3.0
        assert st["gmac_tokens_held"] == 0.0

    def test_replayed_spend_cannot_drain_below_zero(
        self, gclaw_home: Path, metabolism_fixture: object
    ) -> None:
        """Two identical spends (a duplicated manual record) can't double-decrement.

        The first spend succeeds and lowers the treasury; the SECOND identical spend
        now exceeds the (reduced) treasury and is rejected — so the ETH is debited once.
        """
        metabolism_fixture(gmac_treasury_usd=5.0)
        _run(["gmac", "--spend", "5", "--tokens", "100", "--tx", "0xabc"])  # treasury -> 0
        assert _state(gclaw_home)["gmac_treasury_usd"] == 0.0
        with pytest.raises(SystemExit):
            _run(["gmac", "--spend", "5", "--tokens", "100", "--tx", "0xabc"])  # replay rejected
        assert _state(gclaw_home)["gmac_treasury_usd"] == 0.0  # never negative

    def test_exact_treasury_spend_allowed_to_the_cent(
        self, gclaw_home: Path, metabolism_fixture: object
    ) -> None:
        # The guard uses a 1e-9 epsilon so a float-exact full spend isn't spuriously blocked.
        metabolism_fixture(gmac_treasury_usd=2.5)
        _run(["gmac", "--spend", "2.5", "--tokens", "50", "--tx", "0xabc"])
        assert _state(gclaw_home)["gmac_treasury_usd"] == 0.0


class TestSettleArithmetic:
    """settle is the ONLY path that books PnL — its math must be exact and one-shot."""

    def test_profit_settles_balance_and_accrues_10pct_buyback(
        self, metabolism_fixture: object
    ) -> None:
        metabolism_fixture(gmac_balance=1000.0, gmac_treasury_usd=0.0)
        out = _run(["settle", "--pnl", "20", "--note", "win"])
        assert out["gmac_balance"] == 1020.0
        assert out["gmac_treasury_usd"] == 2.0  # 10% buy-back on the $20 profit
        assert out["goodwill"] > 0

    def test_loss_settles_balance_and_accrues_no_buyback(self, metabolism_fixture: object) -> None:
        metabolism_fixture(gmac_balance=1000.0, gmac_treasury_usd=0.0)
        out = _run(["settle", "--pnl", "-15", "--note", "loss"])
        assert out["gmac_balance"] == 985.0
        assert out["gmac_treasury_usd"] == 0.0  # buy-back only accrues on profit
        assert out["goodwill"] == 0  # max(0, 0 - penalty) floors at zero

    def test_two_distinct_settles_each_apply_once(
        self, gclaw_home: Path, metabolism_fixture: object
    ) -> None:
        """Settling two different closes accrues both — the ledger is additive, not idempotent.

        (Dedup of the SAME close is autosettle's job; metabolism settles whatever it's
        handed. This documents that two real closes net correctly, while the treasury
        only ever grows by the buy-back on the profitable portions.)
        """
        metabolism_fixture(gmac_balance=1000.0, gmac_treasury_usd=0.0)
        _run(["settle", "--pnl", "10", "--note", "close-1"])
        out = _run(["settle", "--pnl", "30", "--note", "close-2"])
        assert out["gmac_balance"] == 1040.0
        assert out["gmac_treasury_usd"] == 4.0  # 10% of 10 + 10% of 30

    def test_treasury_never_decreases_on_settle(
        self, gclaw_home: Path, metabolism_fixture: object
    ) -> None:
        metabolism_fixture(gmac_balance=1000.0, gmac_treasury_usd=7.0)
        out = _run(["settle", "--pnl", "-100", "--note", "big loss"])
        assert out["gmac_treasury_usd"] == 7.0  # a loss can't claw back earmarked buy-back

    def test_settle_writes_an_audit_journal_line(
        self, gclaw_home: Path, metabolism_fixture: object
    ) -> None:
        metabolism_fixture(gmac_balance=1000.0)
        _run(["settle", "--pnl", "5", "--note", "audited"])
        lines = (gclaw_home / "journal.jsonl").read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines]
        settle_events = [e for e in events if e.get("event") == "settle"]
        assert len(settle_events) == 1
        assert settle_events[0]["pnl"] == 5.0
        assert settle_events[0]["gmac_buyback_usd"] == 0.5
