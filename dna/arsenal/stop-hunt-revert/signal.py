"""stop-hunt-revert — fade a failed poke through an obvious level (prior-day price).

Offensive/adversarial: retail clusters stops at obvious levels; a sharp spike past
prevDayPx that FAILS to hold (low efficiency = went nowhere) is a liquidity grab.
We fade it back toward the mean. Tight invalidation beyond the sweep."""


def signal(f):
    mark = f.get("mark", 0.0)
    pdp = f.get("prevDayPx", 0.0)
    bz = f.get("bb_z", 0.0)
    eff = f.get("efficiency", 0.0)
    flow = f.get("flow_pressure", 0.0)
    rsi = f.get("rsi", 50.0)
    if not pdp or eff > 0.45:
        return {"action": "flat", "confidence": 0.0, "stop_pct": 1.5, "reason": "real move / no ref"}
    ext = (mark - pdp) / pdp
    if ext > 0.002 and bz > 1.8 and flow < 0.1 and rsi > 58:      # grabbed stops above, failing
        conv = min(1.0, 0.5 + (bz - 1.8) * 0.2 + (0.15 if eff < 0.3 else 0.0))
        return {"action": "short", "confidence": conv, "stop_pct": 1.3, "reason": "fade stop-hunt up"}
    if ext < -0.002 and bz < -1.8 and flow > -0.1 and rsi < 42:   # grabbed stops below, failing
        conv = min(1.0, 0.5 + (-bz - 1.8) * 0.2 + (0.15 if eff < 0.3 else 0.0))
        return {"action": "long", "confidence": conv, "stop_pct": 1.3, "reason": "fade stop-hunt down"}
    return {"action": "flat", "confidence": 0.0, "stop_pct": 1.5, "reason": "no grab"}
