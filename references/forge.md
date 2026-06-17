# Technique forge — author, prove, and trade your own skills

The forge lets a Gclaw agent turn experience into a **technique**: a small,
self-authored skill that decides trades, earns a track record on real market
history, and joins the agent's trading **style**. It is the bridge from "I
noticed a pattern" to "I trade a proven edge" — and, in v2, to trading that
edge *with other agents*.

Engine: `scripts/forge.py` (stdlib Python) + `scripts/forge_data.js` (HyperLiquid
candles/features, no auth). State lives under `$GCLAW_HOME/forge/`.

## The loop

```
draft   forge.py draft "<name>" --kind edge --claim "<the edge in one line>"
        → scaffolds $GCLAW_HOME/forge/techniques/<id>/ (technique.json, SKILL.md, signal.py)
        → then YOU write the logic into signal.py
prove   forge.py prove <id> --coin ETH --interval 4h
        → walk-forward backtest over real candles; writes card.json
        → graduates to "proven" ONLY if in-sample AND out-of-sample expectancy > 0
          with n_oos ≥ 20. Regime-lucky techniques are refused.
adopt   forge.py adopt <id>        → adds it to style.json on its proven market
run     forge.py run               → evaluate adopted techniques on live data
        forge.py run --execute     → place the top intent, within the risk caps
list/show/drop                     → manage the loadout
```

## What a technique is

`signal.py` exports one pure function:

```python
def signal(f):
    """f: feature dict → a decision dict (or flat)."""
```

**Features** (`f`):
- Always (price-derived, available in backtest and live): `coin, price, ret1,
  ret4, ret24` (1/4/24-bar returns), `vol` (stdev of 1-bar returns), `mom`
  (price vs 24-bar SMA), `rng` (avg bar range).
- Live only (`None` in backtests — treat `None` as neutral): `funding`, `oi`,
  `premium`.

**Decision** (return value):
```python
{"action": "long" | "short" | "flat",
 "confidence": 0.0-1.0,     # ranks competing intents
 "leverage": 1-3,           # clamped to the cap regardless
 "stop_pct": > 0,           # MANDATORY; a flat/zero-stop intent is dropped
 "reason": "human-readable"}
```

## Worked example — `vol-momentum` (proven, ETH 4h)

Follow the 24-bar trend when momentum and the last bar agree and volatility is
contained; stand aside in chop. Stop scales with volatility.

```python
def signal(f):
    trend = f["ret24"]; mom = f["mom"]; ret1 = f["ret1"]
    vol = f["vol"] or 0.01
    stop_pct = max(1.5, round(vol * 220, 2))
    calm = vol < 0.02
    if calm and trend > 0.012 and mom > 0 and ret1 > 0:
        return {"action": "long", "confidence": min(1.0, abs(trend) * 18),
                "leverage": 3, "stop_pct": stop_pct, "reason": f"up trend {trend:+.3f}"}
    if calm and trend < -0.012 and mom < 0 and ret1 < 0:
        return {"action": "short", "confidence": min(1.0, abs(trend) * 18),
                "leverage": 3, "stop_pct": stop_pct, "reason": f"down trend {trend:+.3f}"}
    return {"action": "flat", "confidence": 0.0, "stop_pct": stop_pct, "reason": "chop"}
```

Its proven card (out-of-sample): `n=159, winrate 0.39, expectancy +0.00018,
total +2.8%` — a trend-follower's profile (many small losses, fewer larger
wins). The same signal is *refused* on BTC 4h, where in-sample expectancy is
negative. That refusal is the point.

## The evidence gate (why this is trustworthy, not lore)

A technique cannot go live until a backtest it did not get to tune proves edge:
- **Walk-forward split** — first 60% in-sample, last 40% out-of-sample.
- **Both sides must be positive** and `n_oos ≥ 20`. OOS-only edge = luck/regime.
- **Costs are charged** — every backtest trade pays a taker+slippage estimate.
- **Stops are simulated** on bar highs/lows, not assumed.

No self-reported performance. The card is computed by a shared harness.

## Safety model (full autonomy *within* caps)

A technique decides the trade; the forge enforces the rails — they are not
optional and a technique cannot widen them:
- **Sandbox** — `signal.py` may import only `math`/`statistics`; `eval`, `open`,
  `os`, `__import__`, dunder access, etc. are rejected by an AST check before the
  code ever runs, and execution is wall-clock capped.
- **Caps** — leverage clamped to **≤3×**; a **stop is mandatory**; size comes
  from the risk budget (5% equity in THRIVE, 2% in SURVIVE) divided by the stop;
  HIBERNATE blocks execution; the **$11 HL minimum** is enforced.
- **One execution path** — `run --execute` places trades only through
  `hl_perp.js`, which re-applies every cap. A technique never touches execution
  directly.

## Provenance — riding the onchain identity

Every technique is stamped with the agent's `author` = its ERC-8004 `agentId`
(from `metabolism.json`, e.g. `55624` on Base) and an optional `parent` for
lineage. This is what makes v2 possible: when techniques are **published** to the
shared gene pool, their author, lineage, and proven card are anchored to a real
onchain identity — so reputation and royalties are portable and verifiable, not
claimed.

## Roadmap (v2 — the collaborative market)

The solo loop above is v1. Next, riding the same onchain identity:
- **publish / discover** — proven techniques enter a shared gene pool, ranked by
  out-of-sample edge and author reputation.
- **critique** — before adopting a peer's technique, an agent adversarially
  re-proves it (fresh data, look-ahead/overfit checks) and attaches a verdict.
- **fork / merge** — improve a peer's technique; lineage is tracked.
- **royalties / reputation** — a technique that earns PnL for its adopters
  credits GMAC and reputation to its author, anchored onchain.
- **tournaments** — styles compete on a shared benchmark (the decentralized
  leaderboard); winners are boosted in discovery. Natural selection for skills.
