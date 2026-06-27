"""Dual-trend: require the fast (4-bar) and slow (24-bar) returns to agree in sign
and each clear a threshold, so only well-established trends in calm vol trade. Pure price."""


def signal(f):
    fast = f["ret4"]
    trend = f["ret24"]
    vol = f["vol"] or 0.01
    stop_pct = max(1.5, round(vol * 210, 2))
    if vol < 0.02 and fast > 0.005 and trend > 0.015:
        return {"action": "long", "confidence": round(min(1.0, trend * 16), 3),
                "leverage": 3, "stop_pct": stop_pct, "reason": f"dual up {fast:+.3f}/{trend:+.3f}"}
    if vol < 0.02 and fast < -0.005 and trend < -0.015:
        return {"action": "short", "confidence": round(min(1.0, abs(trend) * 16), 3),
                "leverage": 3, "stop_pct": stop_pct, "reason": f"dual down {fast:+.3f}/{trend:+.3f}"}
    return {"action": "flat", "confidence": 0.0, "stop_pct": stop_pct, "reason": "not aligned"}
