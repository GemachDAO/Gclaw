"""contrarian-flow — take the smart side when aggressive taker flow is maxed out
and aligned with crowded funding. Extreme one-sided flow in a non-trend = the crowd
is all-in on a move that's about to exhaust; we fade it."""


def signal(f):
    flow = f.get("flow_pressure", 0.0)
    fz = f.get("funding_z", 0.0)
    eff = f.get("efficiency", 0.0)
    rsi = f.get("rsi", 50.0)
    bz = f.get("bb_z", 0.0)
    if eff > 0.5:
        return {"action": "flat", "confidence": 0.0, "stop_pct": 2.0, "reason": "trending"}
    if flow > 0.6 and fz > 0.8 and rsi > 60 and bz > 1.0:        # everyone buying + paying + stretched
        return {"action": "short", "confidence": min(1.0, flow - 0.3), "stop_pct": 1.9, "reason": "fade max buy flow"}
    if flow < -0.6 and fz < -0.8 and rsi < 40 and bz < -1.0:     # everyone selling + paying + stretched
        return {"action": "long", "confidence": min(1.0, -flow - 0.3), "stop_pct": 1.9, "reason": "fade max sell flow"}
    return {"action": "flat", "confidence": 0.0, "stop_pct": 2.0, "reason": "flow not extreme"}
