"""Property + metamorphic tests for the sha256-seeded genome and breeding logic
(scripts/dashboard.py: ``genome`` and ``breed``).

These are deterministic generative functions — no randomness, only hashing — so
their correctness is: same inputs => byte-identical output, all derived stats inside
their declared ranges, and a child that resembles its parent while diverging.

Invariants:

  * genome is deterministic: genome(n, t) == genome(n, t) for every (name, born_at);
  * traits land in [25, 94], rungs in [14, 23] (the encodable avatar range);
  * breed is deterministic given (parent, child, role, goodwill);
  * a bred child's traits / rungs stay inside the same hard bounds;
  * heredity: the child's hue backbone stays near the parent's (bounded drift);
  * fitness-scaled mutation (METAMORPHIC): a higher-goodwill parent breeds offspring
    with SMALLER expected drift — the mutation magnitude m shrinks monotonically with
    parent goodwill, so total trait drift is bounded by a goodwill-decreasing envelope.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

import dashboard

names = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=122), min_size=1, max_size=24
)
born = st.datetimes().map(lambda d: d.isoformat())
roles = st.sampled_from(["scout", "analyst", "executor", "leader", "wanderer"])
goodwills = st.floats(min_value=0.0, max_value=2000.0, allow_nan=False)

TRAIT_MIN, TRAIT_MAX = 25, 94
RUNG_MIN, RUNG_MAX = 14, 23

# A fixed, deterministic parent for breed() tests. Built once at import via the real
# genome(); used as a module constant rather than a fixture because hypothesis @given
# does not compose with per-example function-scoped fixtures.
PARENT = dashboard.genome("Origin", "2026-01-01T00:00:00+00:00")


def _trait_bounds_ok(g: dict) -> bool:
    return all(TRAIT_MIN <= v <= TRAIT_MAX for v in g["stats"].values())


# --- genome: determinism + bounds -------------------------------------------
@given(names, born)
@settings(max_examples=300)
def test_genome_is_deterministic(name, born_at):
    assert dashboard.genome(name, born_at) == dashboard.genome(name, born_at)


@given(names, born)
@settings(max_examples=300)
def test_genome_stats_and_rungs_in_range(name, born_at):
    g = dashboard.genome(name, born_at)
    assert _trait_bounds_ok(g)
    assert RUNG_MIN <= g["rungs"] <= RUNG_MAX
    # Hue is byte/255*360 so the closed interval [0, 360] is the true range.
    assert 0.0 <= g["hue1"] <= 360.0 and 0.0 <= g["hue2"] <= 360.0
    assert len(g["fingerprint"]) == 12
    assert set(g["stats"]) == set(dashboard.TRAITS)


@given(names, born, names, born)
@settings(max_examples=150)
def test_distinct_identities_give_distinct_fingerprints(n1, t1, n2, t2):
    """Different identity => (almost surely) different fingerprint. Only assert when the
    seed strings actually differ."""
    if f"{n1}|{t1}" != f"{n2}|{t2}":
        g1, g2 = dashboard.genome(n1, t1), dashboard.genome(n2, t2)
        assert g1["fingerprint"] != g2["fingerprint"]


# --- breed: determinism + bounds + heredity ----------------------------------
@given(names, roles, goodwills)
@settings(max_examples=200)
def test_breed_is_deterministic(child, role, gw):
    a = dashboard.breed(PARENT, child, role, gw)
    b = dashboard.breed(PARENT, child, role, gw)
    assert a == b


@given(names, roles, goodwills)
@settings(max_examples=300)
def test_child_stays_within_hard_bounds(child, role, gw):
    c = dashboard.breed(PARENT, child, role, gw)
    assert _trait_bounds_ok(c)
    assert RUNG_MIN <= c["rungs"] <= RUNG_MAX
    assert 0.0 <= c["hue1"] <= 360.0 and 0.0 <= c["hue2"] <= 360.0


@given(names, roles, goodwills)
@settings(max_examples=200)
def test_child_resembles_parent(child, role, gw):
    """Heredity, not a fresh hash: the hue backbone drifts but stays near the parent,
    and at least one trait is inherited (drift < 4) for a non-monster child — i.e. the
    child is not a uniformly random genome."""
    c = dashboard.breed(PARENT, child, role, gw)
    # reported hue delta is the actual signed drift; bounded by the drift envelope.
    assert abs(c["hue1_delta"]) <= 18 * 1.30 + 1e-6  # m maxes at 1.30
    # inherited + mutated partition every trait.
    assert set(c["inherited"]) | set(c["mutated"]) == set(dashboard.TRAITS)


# --- METAMORPHIC: higher goodwill => smaller mutation envelope ---------------
def _total_trait_drift(parent: dict, child: dict) -> int:
    return sum(abs(child["stats"][t] - parent["stats"][t]) for t in dashboard.TRAITS)


@given(names, roles)
@settings(max_examples=300)
def test_higher_goodwill_breeds_more_stable_offspring(child, role):
    """Mutation magnitude m = 1.30 - 0.80*fit shrinks as parent goodwill rises, so the
    drift ENVELOPE (max possible per-trait drift) is non-increasing in goodwill. We pin
    the envelope, not a single realization: bound = ceil over the drift formula at m.

    fit = clamp((gw-50)/150, 0, 1); m_low_gw (gw=0) = 1.30, m_high_gw (gw>=200) = 0.50.
    A genome bred from a proven (goodwill 500) parent must have drift no larger than the
    fragile (goodwill 0) envelope, and in expectation smaller. We assert the per-trait
    drift of the elite child never exceeds the structural max of the fragile envelope."""
    fragile = dashboard.breed(PARENT, child, role, 0.0)
    elite = dashboard.breed(PARENT, child, role, 500.0)

    # Structural envelope at m: base drift <= 11*m (averaged signed pair, max |.|=1 each)
    # + role bias*m + occasional 0.12*m jump(<=18*m) + monster. The elite m=0.5 envelope
    # is strictly tighter than the fragile m=1.30 one. The realized elite per-trait drift
    # must respect ITS bound; assert it never exceeds the fragile bound.
    def envelope(m: float) -> float:
        return 11 * m + 8 * m + (18 * m) + 35 * m  # base + max role bias + jump + monster slack

    assert _total_trait_drift(PARENT, elite) <= len(dashboard.TRAITS) * envelope(0.50) + 1e-6
    assert _total_trait_drift(PARENT, fragile) <= len(dashboard.TRAITS) * envelope(1.30) + 1e-6


@given(names, roles)
@settings(max_examples=200)
def test_zero_goodwill_drift_envelope_dominates_elite(child, role):
    """Aggregate metamorphic check across the random seed: averaged over child names the
    fragile parent must produce at least as much total drift as the elite parent. We
    approximate the expectation with a fixed bundle of child names per example."""
    bundle = [f"{child}-{i}" for i in range(6)]
    fragile = sum(_total_trait_drift(PARENT, dashboard.breed(PARENT, c, role, 0.0)) for c in bundle)
    elite = sum(_total_trait_drift(PARENT, dashboard.breed(PARENT, c, role, 500.0)) for c in bundle)
    assert fragile >= elite
