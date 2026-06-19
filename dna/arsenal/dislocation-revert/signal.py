"""dislocation-revert — fade non-economic, forced flow (liquidation wicks).

Offensive: a cascade/stop-run shoves price far past its statistical mean on a vol
spike (bb_z beyond +/-2.5). The forced sellers have no choice; we provide liquidity
at the dislocation and harvest the snap-back. Gated off in efficient trends.
"""


def signal(f):
    bz = f.get("bb_z", 0.0)
    atr = f.get("atr_pct", 0.0)
    rvol = f.get("realized_vol_pct", 0.0)
    rsi = f.get("rsi", 50.0)
    flow = f.get("flow_pressure", 0.0)
    eff = f.get("efficiency", 0.0)
    if eff > 0.5 or atr <= 0:
        return {"action": "flat", "confidence": 0.0, "stop_pct": 2.0, "reason": "directional/no-vol"}
    vol_spike = atr > 1.0 and rvol > 1.25 * atr
    if bz < -2.5 and vol_spike and rsi < 30:
        cap = 0.0 if flow > -0.3 else (-flow - 0.3)
        conv = min(1.0, (-bz - 2.5) / 1.5 + 0.3 + 0.3 * cap)
        return {"action": "long", "confidence": conv, "stop_pct": 1.8, "reason": f"fade down-wick bb_z={bz:.1f}"}
    if bz > 2.5 and vol_spike and rsi > 70:
        blow = 0.0 if flow < 0.3 else (flow - 0.3)
        conv = min(1.0, (bz - 2.5) / 1.5 + 0.3 + 0.3 * blow)
        return {"action": "short", "confidence": conv, "stop_pct": 1.8, "reason": f"fade blow-off bb_z={bz:.1f}"}
    return {"action": "flat", "confidence": 0.0, "stop_pct": 2.0, "reason": "no dislocation"}
