"""Tests for the decision-quality grader's DETERMINISTIC anti-flattery machinery — the
parts that keep the LLM honest and must be correct without a model call: ungrounded PASS
citations get stripped, and a high mean can't survive a pile of forced-fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

EVALS = Path(__file__).resolve().parent.parent / "evals"
if str(EVALS) not in sys.path:
    sys.path.insert(0, str(EVALS))

import decision_quality as dq  # noqa: E402


def test_ungrounded_pass_is_stripped_grounded_is_kept() -> None:
    report = "I held because the edge was thin, and I skipped the near-money binary."
    verdicts = [
        # grounded: evidence is a real substring of the report
        {"axis": "SCIENTIST", "score": 3, "verdict": "PASS", "evidence": "the edge was thin"},
        # ungrounded: this phrase never appears in the report
        {"axis": "EVENT", "score": 3, "verdict": "PASS", "evidence": "a novel alpha nobody has seen"},
    ]
    adj, grounded, total = dq.ground_verdicts(report, verdicts)
    assert total == 2
    assert grounded == 1  # only the real citation counts
    ev = next(v for v in adj if v["axis"] == "EVENT")
    assert ev["verdict"] == "FAIL" and ev["score"] <= 2  # ungrounded PASS loses its credit
    sci = next(v for v in adj if v["axis"] == "SCIENTIST")
    assert sci.get("grounded") is True and sci["verdict"] == "PASS"


def test_forced_fails_cap_the_letter_despite_a_high_mean() -> None:
    # A near-perfect mean must not survive when most axes were forced-failed on a
    # ground-truth contradiction — the whole point of never trusting the prose.
    assert dq.letter_of(3.0, 0, 4) == "A"          # perfect, nothing forced
    assert dq.letter_of(3.0, 3, 4) == "F"          # 3/4 forced (>0.5) caps at F
    assert dq.POINTS[dq.letter_of(3.0, 2, 4)] <= dq.POINTS["D"]  # 2/4 forced (>0.25) caps at D


def test_verified_facts_runs_and_reports_forced_map() -> None:
    # Smoke: the deterministic fact block builds for a plain report with no contradictions.
    cycle = {"heartbeat_id": "t", "report_text": "Flat book, nothing to manage. Held; no bet.",
             "positions": 0, "context": "report-only", "brief": None}
    vf = dq.verified_facts(cycle)
    assert "FORCED_FAIL: none." in vf["facts"]
    assert vf["forced"] == {}
