#!/usr/bin/env python3
"""cost_truth — is the JUDGE's cost model the real cost the venue charges?

``forge.round_trip_cost`` models TAKER_FEE (+MAKER) per side but omits GDEX's
builderFee, which the managed backend applies opaquely on every fill. This eval
measures the true per-side cost empirically from real onchain fills and compares
it to what forge models, then re-nets every ``proven_markets`` pair against the
true cost to see how many were certified on cost the venue never actually let
them keep.

Because it reads ``forge.round_trip_cost`` live, adding builderFee to the model
(the fix) makes modeled cost meet true cost and this eval flips to PASS.

Run:  uv run --no-project python3 evals/cost_truth.py
Exit: 0 if forge models the true round-trip cost, 1 if it understates it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import forge  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROVEN = forge.gclaw_home() / "forge" / "proven_markets.json"
TOL = 1e-4  # 1bp tolerance for "model covers true cost"


def empirical_rates() -> dict[str, float]:
    """Per-side fee and builderFee as a fraction of notional, from real fills.

    Returns:
        Dict with fee_rate, builder_rate, true_side, and dollar totals.
    """
    fills = json.loads((FIXTURES / "fills.json").read_text(encoding="utf-8"))
    notional = fee = builder = 0.0
    n = 0
    for f in fills:
        px, sz = float(f.get("px", 0)), float(f.get("sz", 0))
        if px <= 0 or sz <= 0:
            continue
        notional += px * sz
        fee += float(f.get("fee") or 0)
        builder += float(f.get("builderFee") or 0)
        n += 1
    return {
        "fills": n,
        "fee_rate": fee / notional,
        "builder_rate": builder / notional,
        "true_side": (fee + builder) / notional,
        "total_fee": fee,
        "total_builder": builder,
    }


def classify_pairs(gap: float) -> dict[str, Any]:
    """Re-net each proven pair against the extra (unmodeled) cost.

    Args:
        gap: True round-trip cost minus modeled round-trip cost.

    Returns:
        Counts and the pairs that flip negative or become fragile.
    """
    pairs = json.loads(PROVEN.read_text(encoding="utf-8")).get("pairs", [])
    flipped, fragile = [], []
    for p in pairs:
        adj = float(p.get("expectancy", 0)) - gap
        row = {"tech": p.get("technique"), "coin": p.get("coin"), "exp": p.get("expectancy"), "adj": round(adj, 6)}
        if adj <= 0:
            flipped.append(row)
        elif adj <= gap:
            fragile.append(row)
    return {"total": len(pairs), "flipped": flipped, "fragile": fragile}


def main() -> int:
    r = empirical_rates()
    modeled_rt = forge.round_trip_cost(stop_hit=False)
    true_rt = 2 * r["true_side"]
    gap = true_rt - modeled_rt

    print("=" * 64)
    print("cost_truth — modeled vs true round-trip cost")
    print("=" * 64)
    print(f"empirical from {r['fills']} real fills:")
    print(f"  fee/side      {r['fee_rate']*1e4:6.2f} bp   (forge TAKER_FEE = {forge.TAKER_FEE*1e4:.2f} bp)")
    print(f"  builderFee/side {r['builder_rate']*1e4:6.2f} bp   (forge models: 0.00 bp)  <- omitted")
    print(f"  true cost/side  {r['true_side']*1e4:6.2f} bp   builderFee = {r['builder_rate']/r['true_side']:.0%} of cost")
    print(f"\nround-trip:  modeled {modeled_rt*1e4:5.1f} bp   true {true_rt*1e4:5.1f} bp   gap {gap*1e4:5.1f} bp")
    print(f"dollar drag omitted: ${r['total_builder']:.2f} builderFee (of ${r['total_fee']+r['total_builder']:.2f} total)")

    c = classify_pairs(gap)
    print(f"\nre-netting {c['total']} 'proven' pairs against +{gap*1e4:.1f}bp unmodeled cost:")
    print(f"  flip NEGATIVE: {len(c['flipped'])}    fragile (<1 gap of zero): {len(c['fragile'])}")
    for row in (c["flipped"] + c["fragile"])[:10]:
        tag = "NEG " if row["adj"] <= 0 else "frag"
        print(f"    [{tag}] {row['tech']:<16}{row['coin']!s:<12} exp {row['exp']:+.4f} -> {row['adj']:+.4f}")

    verdict = "PASS" if modeled_rt >= true_rt - TOL else "FAIL"
    print(f"\nVERDICT: {verdict}  (forge models {modeled_rt*1e4:.1f}bp vs true {true_rt*1e4:.1f}bp)")
    return 0 if modeled_rt >= true_rt - TOL else 1


if __name__ == "__main__":
    raise SystemExit(main())
