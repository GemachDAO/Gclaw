#!/usr/bin/env python3
"""Cycle briefing — pre-gather everything the heartbeat LLM needs into ONE blob.

The LLM used to spend ~8 sequential tool round-trips re-fetching positions, market data,
and forge intents that the deterministic steps had already computed — and each round-trip
is an Opus reason→call→read cycle, which is what drove cycle time toward the timeout. This
assembles all of it into a single briefing injected into the cycle prompt, so the LLM reads
once and decides. Cycle time then stays flat as the universe grows (the briefing gains a few
tokens per market, not a round-trip).

    briefing.py        # print the briefing for the current cycle (gathers live state)

gather() does the I/O (subprocess + disk); render_briefing() is a pure function of the
gathered dict, so it is unit-tested without touching the network.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SKILL_DIR = Path(os.environ.get("GCLAW_SKILL_DIR", str(Path(__file__).resolve().parent.parent)))


def home() -> Path:
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def _read_json(path: Path, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _run_json(args: list[str], default: object) -> object:
    """Run a helper and parse its JSON output from the first brace (tolerates a banner)."""
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=120, check=False).stdout
        i = out.find("{")
        return json.loads(out[i:]) if i >= 0 else default
    except (subprocess.SubprocessError, ValueError, OSError):
        return default


def gather() -> dict:
    """Collect live cycle state — the same reads the LLM used to make, done once, deterministically."""
    h, scripts = home(), SKILL_DIR / "scripts"
    return {
        "meta": _read_json(h / "metabolism.json", {}),
        "intel": (_read_json(h / "intel.json", {}) or {}).get("intel", {}),
        # LIVE read, NOT --cache: the briefing is the LLM's authoritative state, and the 90s
        # status cache can still report a position that closed within the window (a phantom).
        # This also refreshes the cache for cheaper downstream consumers.
        "account": _run_json(["node", str(scripts / "hl_perp.js"), "status"], {}),
        "forge": _run_json(
            ["uv", "run", "--no-project", "python3", str(scripts / "forge.py"), "run"], {}
        ),
        "economics": _run_json(
            ["uv", "run", "--no-project", "python3", str(scripts / "audit_economics.py"), "report"],
            {},
        ),
        # Scientist board: the adopted loadout (each entry carries weight/e/trades) and
        # the learned per-(technique, regime) edge — the raw material for authoring.
        "style": _read_json(h / "forge" / "style.json", {}),
        "regime_stats": _read_json(h / "forge" / "regime_stats.json", {}),
        # Event desk (Book A): the top-by-volume tradeable outcome-market sides and the
        # agent's open tickets + proven calibration — the raw material for an event read.
        "outcomes": _run_json(
            ["uv", "run", "--no-project", "python3", str(scripts / "outcomes.py"), "markets"], {}
        ),
        "calibration": _run_json(
            ["uv", "run", "--no-project", "python3", str(scripts / "outcomes.py"), "calibration"],
            {},
        ),
    }


def _f(x: object, default: float = 0.0) -> float:
    try:
        return float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _resolution_label(side: dict) -> str:
    """Human-readable resolution terms for a side, so the LLM sees the actual bet.

    For a price-binary the desk carries a parsed ``resolution`` ({underlying, targetPrice,
    expiry, period}); render it as e.g. "BTC > 59122 by 20260702-0600". Otherwise fall back
    to the market description (truncated), and finally to nothing. Never raises.

    Args:
        side: A tradeable-side row from the desk board.

    Returns:
        A short resolution string, or "" when no criteria are available.
    """
    res = side.get("resolution")
    if isinstance(res, dict) and res.get("underlying") and res.get("targetPrice") is not None:
        expiry = res.get("expiry") or "?"
        return f"{res['underlying']} vs {res['targetPrice']} by {expiry}"
    desc = str(side.get("description") or "").strip()
    return (desc[:80] + "…") if len(desc) > 80 else desc


def _spot_reference(side: dict, intel: dict) -> str:
    """The underlying's current mark vs the strike — the reference the analyst needs.

    A price-binary is only judgeable against the underlying's live price: "BTC ≥ 59122"
    is cheap or dear only once you know BTC is at 59,519. The briefing already carries the
    per-coin mark (``intel[coin]['price']``); surface it next to the strike with the signed
    distance so the LLM can form a calibrated probability instead of skipping for lack of a
    spot reference. Never raises; returns "" when the mark or strike is unavailable.

    Args:
        side: A tradeable-side row carrying a parsed ``resolution`` ({underlying, targetPrice}).
        intel: The per-coin regime blob ({coin: {price, regime, ...}}).

    Returns:
        A short " · spot … (±x% above/below strike)" suffix, or "" when not computable.
    """
    res = side.get("resolution")
    if not (isinstance(res, dict) and res.get("underlying") and res.get("targetPrice") is not None):
        return ""
    mark = (intel.get(res["underlying"]) or {}).get("price")
    try:
        mark, target = float(mark), float(res["targetPrice"])
    except (TypeError, ValueError):
        return ""
    if not target:
        return ""
    pct = (mark - target) / target * 100
    where = "above" if mark >= target else "below"
    spot = f"{mark:,.2f}" if abs(mark) < 1000 else f"{mark:,.0f}"
    return f" · spot {spot} ({pct:+.2f}% {where} strike)"


def _money(x: object) -> str:
    try:
        return f"${float(x):,.2f}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return f"${x}"


def render_briefing(d: dict) -> str:
    """Render the gathered state into a compact markdown briefing. Pure + defensive: never
    raises on partial/missing data, since a crash here would blind the cycle."""
    meta = d.get("meta") or {}
    intel = d.get("intel") or {}
    acct = d.get("account") or {}
    forge = d.get("forge") or {}
    econ = d.get("economics") or {}
    breaker = forge.get("breaker") or {}

    mode = meta.get("mode") or forge.get("mode") or "?"
    equity = acct.get("equity", forge.get("equity"))
    bp = acct.get("buyingPower", forge.get("buying_power"))
    positions = acct.get("positions") or []
    orders = acct.get("openOrders") or []
    allow = breaker.get("allow_entry", not breaker.get("tripped", False))

    out = [
        "## Cycle briefing — PRE-GATHERED (do not re-fetch positions, market data, or run the forge)",
        "",
    ]
    out.append(
        f"**Survival:** mode {mode} · GMAC {_f(meta.get('gmac_balance')):.0f}/"
        f"{_f(meta.get('seed'), 1000):.0f} · goodwill {meta.get('goodwill', 0)} · "
        f"leverage cap {forge.get('leverage_cap', '?')}x"
    )
    if positions:
        pos = "; ".join(
            f"{p.get('coin')} {'long' if _f(p.get('size')) > 0 else 'short'} "
            f"{abs(_f(p.get('size')))}@{_money(p.get('entryPx'))} (uPnL {_money(p.get('unrealizedPnl'))})"
            for p in positions
        )
        out.append(
            f"**Account:** equity {_money(equity)} · buying power {_money(bp)} · "
            f"{len(positions)} OPEN — {pos} · {len(orders)} resting orders"
        )
    else:
        out.append(
            f"**Account:** equity {_money(equity)} · buying power {_money(bp)} · "
            f"**flat (0 open positions)** · {len(orders)} resting orders"
        )
    dd = breaker.get("drawdown_pct", breaker.get("drawdown", "?"))
    out.append(
        f"**Risk gate:** circuit breaker {'CLEAR — entries allowed' if allow else 'TRIPPED — no new entries'} "
        f"(drawdown {dd}% from hwm {_money(breaker.get('hwm'))})"
    )
    live = sorted((c, f) for c, f in intel.items() if f and f.get("regime") != "chop")
    chop = sorted(c for c, f in intel.items() if f and f.get("regime") == "chop")
    if live:
        names = " · ".join(
            f"{c} {f.get('regime')}{'✓' if f.get('tradeable') else ''}" for c, f in live
        )
        out.append(f"**Tradeable now ({len(live)}):** {names}")
    else:
        out.append("**Tradeable now:** none — whole board is chop")
    if chop:
        out.append(f"**Chop / sit out ({len(chop)}):** {', '.join(chop)}")
    intents = forge.get("intents") or []
    if intents:
        out.append("**Forge intents (ranked by confidence):**")
        for it in intents[:6]:
            tag = "✅ PROVEN (executable)" if it.get("proven") else "— unproven (explore only)"
            out.append(
                f"  {it.get('coin')} {it.get('side')} conf {it.get('confidence')} {tag} [{it.get('technique')}]"
            )
    else:
        out.append("**Forge intents:** none — no technique cleared on any market this scan")
    if econ.get("n"):
        out.append(
            f"**Edge check:** {econ.get('n')} real closes · win rate {econ.get('win_rate')} · "
            f"expectancy {_money(econ.get('expectancy'))}/trade · {econ.get('verdict', '')}"
        )
    out += _scientist_board(d.get("style") or {}, d.get("regime_stats") or {}, intel)
    out += _event_desk_board(d.get("outcomes") or {}, d.get("calibration") or {}, intel)
    out += [
        "",
        "**Origination is forge-only and already done; you do NOT open trades. With a flat book your "
        "MAIN job is SCIENTIST: from the board above, if you have a specific edge hypothesis for an "
        "under-served or losing regime, author ONE technique (write signal.py → forge.py author …) and "
        "let the backtest judge it — it adopts only on out-of-sample edge. If positioned, MANAGE the "
        "risk first. VETO the next forge open via ~/.gclaw/forge/veto.json if warranted. Don't author "
        "busywork — no hypothesis, no technique. Decide from the above; it is complete.**",
    ]
    return "\n".join(out)


def _scientist_board(style: dict, regime_stats: dict, intel: dict) -> list[str]:
    """Render the strategy-R&D board: adopted techniques with fitness, and the regime gaps.

    Gives the LLM-scientist the raw material to form an edge hypothesis — which techniques
    are decaying (low weight / negative edge) and which live regimes no proven technique
    covers — without it having to re-derive any of it.
    """
    adopted = style.get("adopted") or []
    lines = ["", "**Scientist board — your techniques (weight · edge · trades):**"]
    if adopted:
        for e in sorted(adopted, key=lambda x: _f(x.get("weight")), reverse=True):
            lines.append(
                f"  {e.get('id')} [{e.get('coin')}] w={_f(e.get('weight')):.2f} "
                f"e={_f(e.get('e')):+.3f} n={e.get('trades', 0)}"
            )
    else:
        lines.append("  (none adopted)")
    # Which live (non-chop) regimes have NO technique with positive learned edge → gaps to invent for.
    live_regimes = {
        f.get("regime") for f in intel.values() if f and f.get("regime") not in (None, "chop")
    }
    covered = {
        rg for stats in regime_stats.values() for rg, s in stats.items() if _f(s.get("e")) > 0
    }
    gaps = sorted(live_regimes - covered)
    if gaps:
        lines.append(f"**Regime gaps (live now, no positive-edge technique):** {', '.join(gaps)}")
    return lines


def _event_desk_board(outcomes: dict, calibration: dict, intel: dict) -> list[str]:
    """Render the Event Desk (Book A): top tradeable markets, open tickets, calibration.

    Gives the LLM-as-event-analyst the deterministic board it reads: the top-by-volume
    sides with both side prices, the agent's open defined-risk tickets, and the running
    Brier calibration vs the no-skill baseline (the event-desk analogue of edge_real).

    Args:
        outcomes: ``outcomes.py markets`` output ({sides:[...]}).
        calibration: ``outcomes.py calibration`` output ({open, aggregates}).

    Returns:
        Markdown lines, never raising on partial data.
    """
    # Prefer the desk's edgeable partition (dated crypto/macro) — the markets where a
    # calibrated probability can honestly diverge. Fall back to the full board only when the
    # desk reports none, so the LLM analyst is pointed at read-material it can actually beat.
    edgeable = outcomes.get("edgeable") or []
    sides = edgeable or (outcomes.get("sides") or [])
    by_market: dict[object, dict] = {}
    for s in sides:
        m = by_market.setdefault(
            s.get("outcomeId"),
            {
                "name": s.get("name"),
                "sides": [],
                "vol": 0.0,
                "resolution": _resolution_label(s),
                "ref_side": s,
            },
        )
        m["sides"].append(s)
        m["vol"] += _f(s.get("volumeUsd"))
    top = sorted(by_market.values(), key=lambda m: m["vol"], reverse=True)[:6]
    header = "edgeable markets" if edgeable else "top tradeable markets"
    lines = ["", f"**Event desk (Book A) — {header} (vol · sides @ implied prob):**"]
    if top:
        for m in top:
            quoted = " / ".join(
                f"{s.get('side')} {s.get('coin')}@{_f(s.get('price')):.3f}" for s in m["sides"]
            )
            label = f"{m['name']} — {m['resolution']}" if m["resolution"] else m["name"]
            label += _spot_reference(m["ref_side"], intel)
            lines.append(f"  {label} (${m['vol']:,.0f}): {quoted}")
    else:
        lines.append("  (no markets clear the volume floor)")
    if not edgeable and outcomes.get("no_edgeable_market"):
        lines.append(
            f"  ↳ NO EDGEABLE MARKET: {outcomes['no_edgeable_market']} — desk idle by design"
        )
    open_t = calibration.get("open") or []
    if open_t:
        held = "; ".join(
            f"{t.get('coin')} {t.get('name')}/{t.get('side')} p={_f(t.get('prob')):.2f} "
            f"vs px={_f(t.get('price')):.2f} ${_f(t.get('stake')):.0f}{'(shadow)' if t.get('shadow') else '(LIVE)'}"
            for t in open_t
        )
        lines.append(f"**Open tickets ({len(open_t)}):** {held}")
    else:
        lines.append("**Open tickets:** none")
    agg = calibration.get("aggregates") or {}
    brier, baseline = agg.get("brier_mean"), agg.get("baseline_mean")
    if agg.get("n_resolved"):
        verdict = (
            "BEATING no-skill"
            if brier is not None and baseline is not None and brier < baseline
            else "below no-skill baseline"
        )
        lines.append(
            f"**Calibration:** {agg.get('n')} tickets ({agg.get('n_shadow')} shadow / "
            f"{agg.get('n_live')} live) · {agg.get('n_resolved')} resolved · "
            f"Brier {brier} vs no-skill {baseline} — {verdict}"
        )
    else:
        lines.append(
            f"**Calibration:** {agg.get('n', 0)} tickets, none resolved yet — "
            "shadow-mode until proven (no order placed)"
        )
    return lines


def main() -> int:
    print(render_briefing(gather()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
