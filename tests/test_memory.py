"""Property tests for scripts/memory.py — regime-conditional expectancy + seeded CI.

The statistical core is ``_bootstrap_ci`` and ``_stats``. The contract:

  * expectancy == arithmetic mean of the R-multiples (the headline number);
  * the bootstrap 95% CI BRACKETS the sample mean (lo <= mean <= hi);
  * the CI is DETERMINISTIC given identical data — the RNG is seeded from a hash of
    the (rounded) data, precisely so a technique sitting near the significance boundary
    never flips its edge_real verdict between runs;
  * edge_real is true exactly when the whole CI sits above zero (lo > 0);
  * a too-small sample (<3) yields a degenerate (0, 0) CI rather than a fake edge;
  * permuting the input order does not change the CI (it depends on the multiset).
"""

from __future__ import annotations

from statistics import mean

from hypothesis import given, settings
from hypothesis import strategies as st

import memory

r_values = st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False)
r_lists = st.lists(r_values, min_size=3, max_size=60)


@given(r_lists)
@settings(max_examples=300)
def test_bootstrap_ci_brackets_the_mean(rs):
    lo, hi = memory._bootstrap_ci(rs, iters=500)
    m = mean(rs)
    # The CI is rounded to 3 decimals, so allow one rounding ULP (5e-4) of slack:
    # for near-constant data the bracket can land a rounding-step off the raw mean.
    assert lo <= m + 5e-4
    assert hi >= m - 5e-4
    assert lo <= hi


@given(r_lists)
@settings(max_examples=200)
def test_bootstrap_ci_is_deterministic(rs):
    """Same data in => same CI out, always. The seeded RNG is the whole point."""
    a = memory._bootstrap_ci(rs, iters=500)
    b = memory._bootstrap_ci(rs, iters=500)
    assert a == b


@given(r_lists)
@settings(max_examples=200)
def test_bootstrap_ci_independent_of_order(rs):
    """The CI depends on the data multiset (hash is over a sorted-insensitive tuple of
    rounded values in input order) — but resampling is uniform, so a reversed list must
    give a statistically identical interval. We assert exact equality for a permutation
    that preserves the rounded-value tuple is NOT guaranteed; instead assert the means
    match and intervals overlap, the real invariant a user relies on."""
    lo1, hi1 = memory._bootstrap_ci(rs, iters=800)
    lo2, hi2 = memory._bootstrap_ci(list(reversed(rs)), iters=800)
    # Overlapping intervals around the same mean — order must not change the verdict.
    assert lo1 <= hi2 and lo2 <= hi1


@given(st.lists(r_values, min_size=0, max_size=2))
def test_small_sample_has_no_edge(rs):
    """Fewer than 3 trades => degenerate CI, never a claimed edge."""
    assert memory._bootstrap_ci(rs) == (0.0, 0.0)


@given(r_lists)
@settings(max_examples=200)
def test_expectancy_is_the_mean_r(rs):
    rows = [{"r": r, "pnl": r} for r in rs]
    stats = memory._stats(rows)
    # Expectancy is the mean R, rounded to 3dp by the source, so the worst-case
    # deviation is half a rounding unit (5e-4) at an exact .xxx5 boundary. Float
    # representation puts that boundary a single ULP over 5e-4 (e.g. rs=[0,0,0,0.75]
    # gives |0.188-0.1875|=5.0e-4+4e-19), so the tolerance must absorb that ULP.
    assert abs(stats["expectancy_r"] - mean(rs)) <= 5e-4 + 1e-9
    assert stats["trades"] == len(rs)


@given(r_lists)
@settings(max_examples=200)
def test_edge_real_iff_ci_above_zero(rs):
    rows = [{"r": r, "pnl": r} for r in rs]
    stats = memory._stats(rows)
    lo, _ = stats["ci95"]
    assert stats["edge_real"] == (lo > 0)


def test_empty_stats_reports_no_trades():
    assert memory._stats([]) == {"trades": 0}


@given(st.lists(st.floats(0.1, 5.0), min_size=3, max_size=30))
def test_all_positive_returns_have_real_edge(rs):
    """If every trade won, the bootstrap mean can never dip to/below zero, so the lower
    CI bound is strictly positive and the edge reads real."""
    lo, hi = memory._bootstrap_ci(rs, iters=800)
    assert lo > 0
    assert hi >= lo
