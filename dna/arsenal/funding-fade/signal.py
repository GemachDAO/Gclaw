"""funding-fade — tax the crowded, over-leveraged side at funding extremes.

Offensive: when funding_z is screaming, the crowd on the rich side pays us carry
AND is the fragile, liquidation-prone cohort. We fade them — but never fade a real
trend (efficiency/regime gate), and require momentum to already be rolling over.
"""


def signal(f):
    fz = f.get("funding_z", 0.0)
    rsi = f.get("rsi", 50.0)
    eff = f.get("efficiency", 0.0)
    regime = f.get("regime", "range")
    flow = f.get("flow_pressure", 0.0)
    gate = 3.2 if (eff > 0.5 or regime in ("trend_up", "trend_down")) else 2.0
    if fz > gate and rsi > 62 and flow < 0.2:            # crowded longs paying, rolling over
        conv = min(1.0, (fz - gate) / 2.0 + 0.3)
        return {"action": "short", "confidence": conv, "stop_pct": 2.2, "reason": f"fade crowded longs fz={fz:.1f}"}
    if fz < -gate and rsi < 38 and flow > -0.2:          # crowded shorts paying, rolling over
        conv = min(1.0, (-fz - gate) / 2.0 + 0.3)
        return {"action": "long", "confidence": conv, "stop_pct": 2.2, "reason": f"fade crowded shorts fz={fz:.1f}"}
    return {"action": "flat", "confidence": 0.0, "stop_pct": 2.0, "reason": "funding not extreme"}
