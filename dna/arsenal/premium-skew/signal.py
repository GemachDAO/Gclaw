"""premium-skew — fade an exhausted perp premium before the funding tax + unwind.

Offensive: a rich premium with stalling momentum = exhausted longs still paying to
hold; we get short before the tax and the capitulation (mirror for discount)."""


def signal(f):
    prem = f.get("premium", 0.0)
    fz = f.get("funding_z", 0.0)
    slope = f.get("ema_slope_pct", 0.0)
    stack = f.get("ema_stack", 0)
    flow = f.get("flow_pressure", 0.0)
    atr = f.get("atr_pct", 0.0)
    if atr <= 0:
        return {"action": "flat", "confidence": 0.0, "stop_pct": 2.0, "reason": "no-vol"}
    pn = prem / (atr / 100.0)
    if pn > 0.6 and abs(slope) < 0.05 and stack <= 1 and fz < 1.5:
        conv = min(1.0, (pn - 0.6) / 0.6 + 0.25 + (0.2 if flow < -0.2 else 0.0))
        return {"action": "short", "confidence": conv, "stop_pct": 1.6, "reason": f"fade rich premium {pn:.2f}"}
    if pn < -0.6 and abs(slope) < 0.05 and stack >= -1 and fz > -1.5:
        conv = min(1.0, (-pn - 0.6) / 0.6 + 0.25 + (0.2 if flow > 0.2 else 0.0))
        return {"action": "long", "confidence": conv, "stop_pct": 1.6, "reason": f"fade deep discount {pn:.2f}"}
    return {"action": "flat", "confidence": 0.0, "stop_pct": 2.0, "reason": "premium normal"}
