"""Tests for the harness grader — the invariant that matters is anti-gaming: a broken
FLOOR dimension must cap the overall grade regardless of how green everything else is,
so unrelated passing checks can never launder a systemically broken harness into a pass.
"""

from __future__ import annotations

import sys
from pathlib import Path

EVALS = Path(__file__).resolve().parent.parent / "evals"
if str(EVALS) not in sys.path:
    sys.path.insert(0, str(EVALS))

import harness_grade as hg  # noqa: E402


def test_letter_thresholds() -> None:
    assert hg.letter_of(95) == "A"
    assert hg.letter_of(80) == "B"
    assert hg.letter_of(65) == "C"
    assert hg.letter_of(50) == "D"
    assert hg.letter_of(49.9) == "F"


def test_judge_scorer_grades() -> None:
    assert hg.score_judge({"fpr": 0.02, "target": 0.075})["grade"] == "A"  # well under
    assert hg.score_judge({"fpr": 0.06, "target": 0.075})["grade"] == "B"  # under
    assert hg.score_judge({"fpr": 0.30, "target": 0.075})["grade"] == "F"  # certifies noise
    assert hg.score_judge(None)["grade"] == "STALE"  # skipped is never a pass
    assert hg.score_judge(None)["floor"] is True


def _all_A_except(broken: dict) -> list[dict]:
    """A dimension set that is all A except the one broken floor dim passed in."""
    dims = [
        hg._dim("Cost-Model Fidelity", 15, "A", "", "", floor=True),
        hg._dim("Train/Serve Feature Parity", 15, "A", "", "", floor=True),
        hg._dim("Multiple-Comparisons Discipline", 10, "A", "", ""),
        hg._dim("Live Decision Quality", 15, "A", "", ""),
        hg._dim("Edge Realness", 5, "A", "", ""),
        hg._dim("Operational Hygiene", 5, "A", "", ""),
    ]
    return [broken, *dims]


def test_broken_judge_caps_grade_at_F_despite_all_else_A() -> None:
    # The anti-gaming core: JUDGE = F (certifies noise) with everything else A.
    dims = _all_A_except(hg._dim("JUDGE Statistical Power", 20, "F", "", "", floor=True))
    agg = hg.aggregate(dims, None)
    # Averaging alone would NOT fail it — the 20%-weighted F only pulls the blend to a
    # non-failing C. The floor cap is what correctly forces F; that gap is the whole point.
    assert hg.POINTS[agg["provisional_letter"]] >= hg.POINTS["C"]
    assert agg["letter"] == "F"  # the floor cap dominates the arithmetic
    assert "JUDGE" in agg["capped_by"]


def test_skipped_judge_also_caps() -> None:
    dims = _all_A_except(hg._dim("JUDGE Statistical Power", 20, "STALE", "", "", floor=True))
    assert hg.aggregate(dims, None)["letter"] == "F"


def test_broken_cost_caps_at_D() -> None:
    dims = _all_A_except(hg._dim("JUDGE Statistical Power", 20, "A", "", "", floor=True))
    dims = [d if "Cost" not in d["name"] else hg._dim("Cost-Model Fidelity", 15, "F", "", "", floor=True)
            for d in dims]
    agg = hg.aggregate(dims, None)
    assert agg["letter"] == "D"  # cost floor caps at D, not F


def test_ungraded_calibration_caps_ceiling_and_is_excluded() -> None:
    dims = _all_A_except(hg._dim("JUDGE Statistical Power", 20, "A", "", "", floor=True))
    dims.append(hg._dim("Event-Desk Calibration", 5, "UNGRADED", "", ""))
    agg = hg.aggregate(dims, None)
    assert agg["provisional_score"] == 100.0  # UNGRADED excluded from the blend, not scored 0
    assert agg["letter"] == "B"  # ceiling-capped at B+ (88)


def test_regression_on_floor_dim_fires_banner_and_caps() -> None:
    prev = {"dimensions": [{"name": "JUDGE Statistical Power", "grade": "A"}]}
    dims = _all_A_except(hg._dim("JUDGE Statistical Power", 20, "F", "", "", floor=True))
    agg = hg.aggregate(dims, prev)
    assert agg["regression"] is not None and "JUDGE" in agg["regression"]
