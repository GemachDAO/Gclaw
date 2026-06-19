"""momentum-stack — ride a high-efficiency trend (with the EMA stack), the
disciplined offensive in trend_up/down: take continuation while late chasers
provide the fuel. Only fires when the move is genuinely directional."""


def signal(f):
    stack = f.get("ema_stack", 0)
    eff = f.get("efficiency", 0.0)
    slope = f.get("ema_slope_pct", 0.0)
    rsi = f.get("rsi", 50.0)
    if eff < 0.42:
        return {"action": "flat", "confidence": 0.0, "stop_pct": 2.5, "reason": "not trending"}
    if stack == 2 and slope > 0.02 and rsi < 78:
        return {"action": "long", "confidence": min(1.0, 0.4 + eff * 0.6), "stop_pct": 2.6, "reason": "ride uptrend"}
    if stack == -2 and slope < -0.02 and rsi > 22:
        return {"action": "short", "confidence": min(1.0, 0.4 + eff * 0.6), "stop_pct": 2.6, "reason": "ride downtrend"}
    return {"action": "flat", "confidence": 0.0, "stop_pct": 2.5, "reason": "stack not aligned"}
