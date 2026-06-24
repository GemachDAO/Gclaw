"""Momentum-accel: enter a trend when the recent 4-bar pace exceeds the pace the
24-bar trend implies — momentum that is speeding up, not fading. Pure price; stdlib only."""


def signal(f):
    fast = f["ret4"]
    trend = f["ret24"]
    vol = f["vol"] or 0.01
    stop_pct = max(1.3, round(vol * 200, 2))
    expected = trend * (4.0 / 24.0)
    accel = fast - expected
    if vol < 0.025 and trend > 0 and accel > 0.006:
        return {"action": "long", "confidence": round(min(1.0, accel * 40), 3),
                "leverage": 3, "stop_pct": stop_pct, "reason": f"accel {accel:+.3f}"}
    if vol < 0.025 and trend < 0 and accel < -0.006:
        return {"action": "short", "confidence": round(min(1.0, abs(accel) * 40), 3),
                "leverage": 3, "stop_pct": stop_pct, "reason": f"decel {accel:+.3f}"}
    return {"action": "flat", "confidence": 0.0, "stop_pct": stop_pct, "reason": "no accel"}
