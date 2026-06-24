"""Deviation-revert: when price is stretched far from its 24-bar mean (mom), fade
the stretch and play the snap back. Pure price; stdlib only."""


def signal(f):
    mom = f["mom"]
    vol = f["vol"] or 0.01
    stop_pct = max(1.5, round(vol * 220, 2))
    if mom < -0.025:
        return {"action": "long", "confidence": round(min(1.0, abs(mom) * 16), 3),
                "leverage": 3, "stop_pct": stop_pct, "reason": f"below mean {mom:+.3f}"}
    if mom > 0.025:
        return {"action": "short", "confidence": round(min(1.0, abs(mom) * 16), 3),
                "leverage": 3, "stop_pct": stop_pct, "reason": f"above mean {mom:+.3f}"}
    return {"action": "flat", "confidence": 0.0, "stop_pct": stop_pct, "reason": "near mean"}
