#!/usr/bin/env python3
"""Decompose winner fills into size-invariant, clonable skill patterns.

READ-ONLY forensics for Gclaw's Scientist loop. Consumes the raw blob written by
``winners.js`` (``$GCLAW_HOME/forge/winners_raw.json``) and emits a distilled
intel artifact (``winner_intel.json``) describing *what skill-proven HyperLiquid
wallets actually do* — machine type, exit fingerprint, coin/hour concentration —
so the Scientist can reverse-engineer encodable techniques from it.

Nothing here trades, settles, or moves funds; it only reads a local JSON file.

Pipeline:
    1. MM/clonability filter (F3) — drop uncopyable liquidity providers.
    2. Round-trip reconstruction — flat->flat trades per coin (with a truncation
       fallback that treats each realized-PnL fill as a mini-trade).
    3. Per-wallet scorecard — win rate, payoff, kelly, machine type, disposition.
    4. Aggregate features — only patterns holding in >=40% of survivors AND >=3
       wallets are reported.
    5. Pre-rendered ``desk_text`` — a <1500 char brief written for the LLM.

Usage:
    uv run --no-project python3 scripts/decompose.py
"""

from __future__ import annotations

import datetime
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

GCLAW_HOME = Path(os.environ.get("GCLAW_HOME") or (Path.home() / ".gclaw"))
FORGE_DIR = GCLAW_HOME / "forge"
RAW_PATH = FORGE_DIR / "winners_raw.json"
OUT_PATH = FORGE_DIR / "winner_intel.json"

# F3 MM/clonability thresholds — a $177 market-taker cannot clone liquidity providers.
MAX_FILLS_PER_HOUR = 60.0
MIN_MEDIAN_NOTIONAL = 1000.0
MAX_MAKER_FRACTION = 0.8

# Round-trip flatness: |net size| below this fraction of the trade's peak size is "flat".
FLAT_EPS_FRAC = 0.02
MS_PER_HOUR = 3_600_000.0

# Aggregate reporting gate.
MIN_PREVALENCE = 0.40
MIN_SUPPORT = 3


def _num(value: Any, default: float = 0.0) -> float:
    """Coerce an SDK string/number field to float, tolerating None/blank.

    Args:
        value: raw field value (HL returns numerics as strings).
        default: fallback when the value is missing or unparseable.

    Returns:
        The parsed float, or ``default``.
    """
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _window_perf(entry: dict[str, Any], window: str) -> dict[str, Any]:
    """Return the ``{pnl, roi, vlm}`` perf dict for one leaderboard window.

    Args:
        entry: a raw wallet record carrying ``windowPerformances``.
        window: one of ``day``/``week``/``month``/``allTime``.

    Returns:
        The perf dict, or an empty dict if the window is absent.
    """
    for pair in entry.get("windowPerformances") or []:
        if isinstance(pair, list) and len(pair) == 2 and pair[0] == window:
            return pair[1] or {}
    return {}


def _fill_notional(fill: dict[str, Any]) -> float:
    """Absolute USD notional of a fill (``|px * sz|``).

    Args:
        fill: a raw HL fill.

    Returns:
        Absolute notional in USD.
    """
    return abs(_num(fill.get("px")) * _num(fill.get("sz")))


def clonability_stats(fills: list[dict[str, Any]]) -> dict[str, float]:
    """Compute the F3 MM/clonability signals over a wallet's fill window.

    Args:
        fills: the wallet's fills (any order).

    Returns:
        Dict with ``fills_per_hour``, ``median_fill_notional``,
        ``maker_fraction`` and ``window_hours``.
    """
    if not fills:
        return {
            "fills_per_hour": 0.0,
            "median_fill_notional": 0.0,
            "maker_fraction": 0.0,
            "window_hours": 0.0,
        }
    times = [_num(f.get("time")) for f in fills]
    span_ms = max(times) - min(times)
    window_hours = span_ms / MS_PER_HOUR if span_ms > 0 else 0.0
    fills_per_hour = len(fills) / window_hours if window_hours > 0 else float(len(fills))
    notionals = [_fill_notional(f) for f in fills]
    maker_fraction = sum(1 for f in fills if f.get("crossed") is False) / len(fills)
    return {
        "fills_per_hour": fills_per_hour,
        "median_fill_notional": statistics.median(notionals),
        "maker_fraction": maker_fraction,
        "window_hours": window_hours,
    }


def is_liquidity_provider(stats: dict[str, float]) -> bool:
    """Return True if the F3 filter marks this wallet as an uncopyable MM.

    Args:
        stats: output of :func:`clonability_stats`.

    Returns:
        Whether the wallet should be dropped.
    """
    return (
        stats["fills_per_hour"] > MAX_FILLS_PER_HOUR
        or stats["median_fill_notional"] < MIN_MEDIAN_NOTIONAL
        or stats["maker_fraction"] > MAX_MAKER_FRACTION
    )


def _sorted_fills(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return fills sorted time-ascending (stable).

    Args:
        fills: raw fills.

    Returns:
        A new list ordered by ``time`` then original index.
    """
    return sorted(fills, key=lambda f: _num(f.get("time")))


def reconstruct_flat_to_flat(coin_fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reconstruct flat->flat round trips for one coin.

    A trade opens when the net position leaves ~0 and closes when it returns to
    ~0. ``pnl`` sums the ``closedPnl`` of the trade's reducing fills; ``hold``
    is close-time minus open-time; ``entry_dir`` is the first fill's ``dir``.

    Args:
        coin_fills: this coin's fills, time-ascending.

    Returns:
        A list of trade dicts (may be empty if never flat).
    """
    trades: list[dict[str, Any]] = []
    open_time: float | None = None
    entry_dir = ""
    entry_side = ""
    pnl_acc = 0.0
    add_sizes: list[float] = []
    peak_abs = 0.0
    net = None
    for fill in coin_fills:
        start = _num(fill.get("startPosition"))
        signed = _num(fill.get("sz")) * (1.0 if fill.get("side") == "B" else -1.0)
        net = start + signed if net is None else net + signed
        if open_time is None and abs(start) <= FLAT_EPS_FRAC * max(abs(signed), 1e-9):
            open_time = _num(fill.get("time"))
            entry_dir = fill.get("dir", "")
            entry_side = fill.get("side", "")
            pnl_acc = 0.0
            add_sizes = []
            peak_abs = abs(net)
        if open_time is None:
            continue
        peak_abs = max(peak_abs, abs(net))
        pnl_acc += _num(fill.get("closedPnl"))
        if _is_add(fill, entry_side):
            add_sizes.append(abs(_fill_notional(fill)))
        if abs(net) <= FLAT_EPS_FRAC * max(peak_abs, 1e-9):
            trades.append(
                {
                    "coin": fill.get("coin"),
                    "pnl": pnl_acc,
                    "hold_ms": _num(fill.get("time")) - open_time,
                    "entry_dir": entry_dir,
                    "add_notionals": add_sizes,
                }
            )
            open_time = None
    return trades


def _is_add(fill: dict[str, Any], entry_side: str) -> bool:
    """Return True if the fill increases the position (same side as entry).

    Args:
        fill: the fill to classify.
        entry_side: the opening fill's ``side`` (``B``/``A``).

    Returns:
        Whether this fill adds to (rather than reduces) the position.
    """
    dir_val = fill.get("dir", "")
    return dir_val.startswith("Open") and fill.get("side") == entry_side


def reconstruct_mini_trades(coin_fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fallback: treat each realized-PnL fill as a mini round trip.

    Used when 2000-fill truncation prevents a clean flat->flat reconstruction.
    Hold time is unknowable per mini-trade, so it is reported as ``None``.

    Args:
        coin_fills: this coin's fills, time-ascending.

    Returns:
        One trade per reducing fill with nonzero ``closedPnl``.
    """
    trades: list[dict[str, Any]] = []
    for fill in coin_fills:
        pnl = _num(fill.get("closedPnl"))
        if pnl != 0.0:
            trades.append(
                {
                    "coin": fill.get("coin"),
                    "pnl": pnl,
                    "hold_ms": None,
                    "entry_dir": fill.get("dir", ""),
                    "add_notionals": [],
                }
            )
    return trades


def build_trades(fills: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """Reconstruct trades for a wallet, choosing flat->flat or the fallback.

    Flat->flat is preferred; if it yields no clean round trips (heavy
    truncation), fall back to per-fill mini-trades and record which method won.

    Args:
        fills: all of the wallet's fills.

    Returns:
        ``(trades, method)`` where method is ``flat_to_flat`` or ``mini_trade``.
    """
    by_coin: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fill in _sorted_fills(fills):
        by_coin[fill.get("coin", "?")].append(fill)
    flat_trades: list[dict[str, Any]] = []
    for coin_fills in by_coin.values():
        flat_trades.extend(reconstruct_flat_to_flat(coin_fills))
    if flat_trades:
        return flat_trades, "flat_to_flat"
    mini: list[dict[str, Any]] = []
    for coin_fills in by_coin.values():
        mini.extend(reconstruct_mini_trades(coin_fills))
    return mini, "mini_trade"


def _payoff(wins: list[float], losses: list[float]) -> float:
    """Payoff ratio = mean win / |mean loss| (0.0 if undefined).

    Args:
        wins: positive trade pnls.
        losses: negative trade pnls.

    Returns:
        The payoff ratio.
    """
    if not wins or not losses:
        return 0.0
    mean_loss = abs(statistics.mean(losses))
    return statistics.mean(wins) / mean_loss if mean_loss > 0 else 0.0


def _machine_type(win_rate: float, payoff: float) -> str:
    """Classify the wallet's edge shape.

    Args:
        win_rate: fraction of winning trades.
        payoff: payoff ratio.

    Returns:
        ``TREND``, ``MEANREV`` or ``MIXED``.
    """
    if win_rate < 0.45 and payoff > 2.0:
        return "TREND"
    if win_rate > 0.6 and payoff < 1.0:
        return "MEANREV"
    return "MIXED"


def _martingale_ratio(trades: list[dict[str, Any]]) -> float:
    """Avg add-size while losing / while winning (>1.5 = adds to losers).

    Args:
        trades: reconstructed trades carrying ``add_notionals`` and ``pnl``.

    Returns:
        The ratio, or 0.0 if not computable.
    """
    losing_adds = [n for t in trades if t["pnl"] < 0 for n in t["add_notionals"]]
    winning_adds = [n for t in trades if t["pnl"] > 0 for n in t["add_notionals"]]
    if not losing_adds or not winning_adds:
        return 0.0
    win_mean = statistics.mean(winning_adds)
    return statistics.mean(losing_adds) / win_mean if win_mean > 0 else 0.0


def _top5_win_share(wins: list[float]) -> float:
    """Share of total winnings from the top-5 wins (>0.6 hints at luck).

    Args:
        wins: positive trade pnls.

    Returns:
        Fraction of gross wins concentrated in the 5 largest.
    """
    total = sum(wins)
    if total <= 0:
        return 0.0
    return sum(sorted(wins, reverse=True)[:5]) / total


def _coin_weights(trades: list[dict[str, Any]]) -> dict[str, float]:
    """Notional-fraction weight per coin (proxied by |pnl| exposure).

    Args:
        trades: reconstructed trades.

    Returns:
        Coin -> weight, summing to ~1.0 (empty if no exposure).
    """
    raw: dict[str, float] = defaultdict(float)
    for trade in trades:
        raw[trade["coin"]] += abs(trade["pnl"])
    total = sum(raw.values())
    if total <= 0:
        counts = Counter(t["coin"] for t in trades)
        n = sum(counts.values())
        return {c: k / n for c, k in counts.items()} if n else {}
    return {c: v / total for c, v in raw.items()}


def _median_hold_hours(trades: list[dict[str, Any]], winning: bool) -> float | None:
    """Median hold time (hours) of winners or losers with known holds.

    Args:
        trades: reconstructed trades.
        winning: select winners (True) or losers (False).

    Returns:
        Median hold in hours, or None when holds are unknown/absent.
    """
    holds = [
        t["hold_ms"] / MS_PER_HOUR
        for t in trades
        if t["hold_ms"] is not None and ((t["pnl"] > 0) == winning)
    ]
    return statistics.median(holds) if holds else None


def _skill_components(
    win_rate: float, payoff: float, top5: float, martingale: float, n_trades: int
) -> dict[str, float]:
    """Break the skill score into named 0..1 components.

    Rewards positive expectancy shape and sample size; penalizes luck
    concentration and adding to losers.

    Args:
        win_rate: fraction of winning trades.
        payoff: payoff ratio.
        top5: top-5 win share.
        martingale: martingale ratio.
        n_trades: number of reconstructed trades.

    Returns:
        Named components each in ``[0, 1]``.
    """
    edge = win_rate * payoff / (win_rate * payoff + (1 - win_rate)) if payoff > 0 else 0.0
    return {
        "edge": max(0.0, min(1.0, edge)),
        "payoff": max(0.0, min(1.0, payoff / 3.0)),
        "not_luck": max(0.0, min(1.0, 1.0 - top5)),
        "not_martingale": max(0.0, min(1.0, 1.0 - max(0.0, martingale - 1.0))),
        "sample": max(0.0, min(1.0, math.log10(n_trades + 1) / 2.0)),
    }


def _skill_score(components: dict[str, float]) -> float:
    """Weighted 0-100 skill score from its components.

    Args:
        components: output of :func:`_skill_components`.

    Returns:
        A score in ``[0, 100]``.
    """
    weights = {"edge": 0.35, "payoff": 0.2, "not_luck": 0.2, "not_martingale": 0.15, "sample": 0.1}
    return round(100.0 * sum(components[k] * w for k, w in weights.items()), 1)


def scorecard(address: str, trades: list[dict[str, Any]], stats: dict[str, float], method: str) -> dict[str, Any]:
    """Build the full per-wallet scorecard.

    Args:
        address: wallet address.
        trades: reconstructed trades.
        stats: clonability stats (for window hours).
        method: reconstruction method used.

    Returns:
        The scorecard dict.
    """
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    n = len(pnls)
    win_rate = len(wins) / n if n else 0.0
    payoff = _payoff(wins, losses)
    expectancy = statistics.mean(pnls) if pnls else 0.0
    kelly = win_rate - (1 - win_rate) / payoff if payoff > 0 else 0.0
    top5 = _top5_win_share(wins)
    martingale = _martingale_ratio(trades)
    components = _skill_components(win_rate, payoff, top5, martingale, n)
    return {
        "address": address,
        "n_trades": n,
        "win_rate": round(win_rate, 3),
        "payoff": round(payoff, 3),
        "expectancy": round(expectancy, 4),
        "kelly_frac": round(kelly, 3),
        "machine_type": "UNKNOWN" if method == "mini_trade" else _machine_type(win_rate, payoff),
        "martingale_ratio": round(martingale, 3),
        "top5_win_share": round(top5, 3),
        "median_hold_win_h": _round_opt(_median_hold_hours(trades, True)),
        "median_hold_loss_h": _round_opt(_median_hold_hours(trades, False)),
        "coin_weights": {c: round(w, 3) for c, w in _coin_weights(trades).items()},
        "luck_flag": top5 > 0.6,
        "window_hours": round(stats["window_hours"], 1),
        "method": method,
        "skill_score": _skill_score(components),
        "skill_components": {k: round(v, 3) for k, v in components.items()},
        "caveats": _scorecard_caveats(method),
    }


def _scorecard_caveats(method: str) -> list[str]:
    """Return honesty caveats for a scorecard given its reconstruction method.

    Args:
        method: ``flat_to_flat`` or ``mini_trade``.

    Returns:
        A list of caveat strings (empty for clean flat->flat).
    """
    if method == "mini_trade":
        return [
            "Fill window is a truncated slice of continuous positions (never flat->flat); "
            "win_rate/payoff/hold are derived from per-fill realized-PnL signs, not true "
            "round trips, and can be badly distorted (e.g. a single scaled-out winner reads "
            "as many wins). Treat machine_type and hold fields as unavailable.",
        ]
    return []


def _round_opt(value: float | None) -> float | None:
    """Round an optional float to 2dp, preserving None.

    Args:
        value: a value or None.

    Returns:
        Rounded value or None.
    """
    return round(value, 2) if value is not None else None


def _entry_direction(entry_dir: str) -> str | None:
    """Map an entry ``dir`` string to ``long``/``short``/None.

    Args:
        entry_dir: the first fill's ``dir`` (e.g. "Open Long").

    Returns:
        ``long``, ``short`` or None if undeterminable.
    """
    lowered = entry_dir.lower()
    if "long" in lowered and "short" not in lowered:
        return "long"
    if "short" in lowered and "long" not in lowered:
        return "short"
    if ">" in entry_dir:
        return "short" if entry_dir.strip().endswith("Short") else "long"
    return None


def _feature(fid: str, desc: str, prevalence: float, support: int, magnitude: Any, caveats: str) -> dict[str, Any]:
    """Assemble one aggregate feature with a confidence tier.

    Args:
        fid: feature id.
        desc: human description.
        prevalence: fraction of survivors exhibiting it.
        support: number of supporting wallets.
        magnitude: the feature's value/direction payload.
        caveats: caveat string.

    Returns:
        The feature dict.
    """
    if prevalence >= MIN_PREVALENCE and support >= MIN_SUPPORT:
        confidence = "HIGH"
    elif support >= 2:
        confidence = "MED"
    else:
        confidence = "LOW"
    return {
        "id": fid,
        "description": desc,
        "prevalence": round(prevalence, 3),
        "support_wallets": support,
        "magnitude": magnitude,
        "confidence": confidence,
        "caveats": caveats,
    }


def direction_feature(per_wallet_trades: dict[str, list[dict[str, Any]]], n_surv: int) -> dict[str, Any] | None:
    """Aggregate long/short entry bias across survivors.

    Args:
        per_wallet_trades: address -> reconstructed trades.
        n_surv: number of survivors.

    Returns:
        The feature dict, or None if unsupported.
    """
    long_biased = 0
    fractions = []
    for trades in per_wallet_trades.values():
        dirs = [_entry_direction(t["entry_dir"]) for t in trades]
        dirs = [d for d in dirs if d]
        if not dirs:
            continue
        long_frac = sum(1 for d in dirs if d == "long") / len(dirs)
        fractions.append(long_frac)
        if long_frac > 0.55:
            long_biased += 1
    if not fractions:
        return None
    prevalence = long_biased / n_surv
    return _feature(
        "direction_bias",
        "Fraction of survivors that are net-long at entry (>55% long).",
        prevalence,
        long_biased,
        {"mean_long_fraction": round(statistics.mean(fractions), 3), "long_biased_wallets": long_biased},
        "Directional bias in a bull month is not a persistent edge; walk-forward must confirm.",
    )


def coin_feature(scorecards: list[dict[str, Any]], n_surv: int) -> dict[str, Any] | None:
    """Coins traded by >=40% of survivors.

    Args:
        scorecards: per-wallet scorecards (carry coin_weights).
        n_surv: number of survivors.

    Returns:
        The feature dict, or None if none qualify.
    """
    counts: Counter[str] = Counter()
    for card in scorecards:
        for coin in card["coin_weights"]:
            counts[coin] += 1
    common = {c: k for c, k in counts.items() if k / n_surv >= MIN_PREVALENCE and k >= MIN_SUPPORT}
    if not common:
        return None
    top = max(common, key=lambda c: common[c])
    return _feature(
        "coin_concentration",
        "Coins that >=40% of surviving winners trade.",
        common[top] / n_surv,
        common[top],
        {"coins": {c: common[c] for c in sorted(common, key=lambda x: -common[x])}},
        "Popular coins reflect liquidity, not necessarily edge.",
    )


def hour_feature(raw_wallets: list[dict[str, Any]], survivors: set[str], n_surv: int) -> dict[str, Any] | None:
    """UTC entry-hour concentration across survivors.

    An "entry" fill is any ``Open ...`` fill; hours are pooled and the peak
    3-hour block is reported when it is meaningfully above uniform.

    Args:
        raw_wallets: raw wallet records (for fill times).
        survivors: surviving addresses.
        n_surv: number of survivors.

    Returns:
        The feature dict, or None if unsupported.
    """
    per_wallet_peak: Counter[int] = Counter()
    pooled: Counter[int] = Counter()
    for record in raw_wallets:
        if record["address"] not in survivors:
            continue
        hours = [
            int((_num(f.get("time")) / MS_PER_HOUR) % 24)
            for f in record["fills"]
            if str(f.get("dir", "")).startswith("Open")
        ]
        if not hours:
            continue
        local = Counter(hours)
        pooled.update(local)
        per_wallet_peak[local.most_common(1)[0][0]] += 1
    if not pooled:
        return None
    total = sum(pooled.values())
    block = _peak_block(pooled)
    block_share = sum(pooled[h % 24] for h in block) / total
    support = sum(per_wallet_peak[h] for h in block)
    return _feature(
        "hour_of_day_concentration",
        "UTC entry-hour block (3h) where winners most often open.",
        support / n_surv,
        support,
        {"peak_block_utc": block, "block_share": round(block_share, 3), "uniform_share": round(3 / 24, 3)},
        "Entry timing may track a coin's liquidity session, not a tradable clock edge.",
    )


def _peak_block(pooled: Counter[int]) -> list[int]:
    """Return the 3-hour UTC block with the most entries (wrapping midnight).

    Args:
        pooled: hour -> count histogram.

    Returns:
        The three consecutive hours of the peak block.
    """
    best_start, best = 0, -1
    for start in range(24):
        window = sum(pooled[(start + k) % 24] for k in range(3))
        if window > best:
            best, best_start = window, start
    return [(best_start + k) % 24 for k in range(3)]


def hold_asymmetry_feature(scorecards: list[dict[str, Any]], n_surv: int) -> dict[str, Any] | None:
    """Do winners systematically hold winners longer than losers?

    The key encodable exit principle. Counts wallets whose median winning hold
    exceeds their median losing hold (both known).

    Args:
        scorecards: per-wallet scorecards.
        n_surv: number of survivors.

    Returns:
        The feature dict, or None if no wallet has both holds.
    """
    ratios = []
    holds_longer = 0
    comparable = 0
    for card in scorecards:
        win_h, loss_h = card["median_hold_win_h"], card["median_hold_loss_h"]
        if win_h is None or loss_h is None or loss_h <= 0:
            continue
        comparable += 1
        ratios.append(win_h / loss_h)
        if win_h > loss_h:
            holds_longer += 1
    if comparable == 0:
        return None
    return _feature(
        "hold_time_asymmetry",
        "Winners hold winning trades longer than losing trades (disposition-inverse).",
        holds_longer / n_surv,
        holds_longer,
        {
            "wallets_hold_winners_longer": holds_longer,
            "comparable_wallets": comparable,
            "median_hold_ratio_win_over_loss": round(statistics.median(ratios), 2),
        },
        "Only computable on flat->flat wallets; truncated (mini-trade) wallets lack holds.",
    )


def build_aggregates(
    scorecards: list[dict[str, Any]],
    per_wallet_trades: dict[str, list[dict[str, Any]]],
    raw_wallets: list[dict[str, Any]],
    survivors: set[str],
) -> list[dict[str, Any]]:
    """Assemble every supported aggregate feature.

    Args:
        scorecards: per-wallet scorecards.
        per_wallet_trades: address -> reconstructed trades.
        raw_wallets: raw wallet records.
        survivors: surviving addresses.

    Returns:
        The list of feature dicts (only those with data).
    """
    n_surv = len(survivors)
    candidates = [
        direction_feature(per_wallet_trades, n_surv),
        coin_feature(scorecards, n_surv),
        hour_feature(raw_wallets, survivors, n_surv),
        hold_asymmetry_feature(scorecards, n_surv),
    ]
    return [feature for feature in candidates if _passes_gate(feature)]


def _passes_gate(feature: dict[str, Any] | None) -> bool:
    """Enforce the hard >=40%-of-survivors AND >=3-wallet reporting gate.

    Args:
        feature: a candidate feature or None.

    Returns:
        Whether the feature is present and meets both thresholds.
    """
    return (
        feature is not None
        and feature["prevalence"] >= MIN_PREVALENCE
        and feature["support_wallets"] >= MIN_SUPPORT
    )


def _machine_mix(scorecards: list[dict[str, Any]]) -> Counter[str]:
    """Count machine types across scorecards.

    Args:
        scorecards: per-wallet scorecards.

    Returns:
        machine_type -> count.
    """
    return Counter(card["machine_type"] for card in scorecards)


def render_desk_text(scorecards: list[dict[str, Any]], features: list[dict[str, Any]]) -> str:
    """Render the compact (<1500 char) Scientist-facing brief.

    Every number is drawn from the computed scorecards/features.

    Args:
        scorecards: per-wallet scorecards.
        features: aggregate features.

    Returns:
        The desk_text string.
    """
    n = len(scorecards)
    by_id = {f["id"]: f for f in features}
    lines = [f"REVERSE-ENGINEERING DESK: {n} skill-proven clonable wallet(s)."]
    if n < MIN_SUPPORT:
        lines.append(
            "THIN FEED this cycle: too few clonable survivors to form trustworthy "
            "aggregate patterns (need >=3) — the board was dominated by uncopyable "
            "market-makers. Do NOT over-fit to the wallet(s) below; wait for a richer pull."
        )
    top = _top_patterns(by_id)
    if top:
        lines.append("What they do: " + " ".join(top))
    mix = _machine_mix(scorecards)
    lines.append("Machine mix: " + ", ".join(f"{k} {v}" for k, v in mix.most_common()) + ".")
    hold = by_id.get("hold_time_asymmetry")
    if hold:
        ratio = hold["magnitude"]["median_hold_ratio_win_over_loss"]
        lines.append(
            f"Exit fingerprint: winners held ~{ratio}x longer than losers"
            f" ({hold['magnitude']['wallets_hold_winners_longer']}/{hold['magnitude']['comparable_wallets']} wallets)."
        )
    coins = by_id.get("coin_concentration")
    if coins:
        watch = ", ".join(list(coins["magnitude"]["coins"])[:5])
        lines.append(f"Watchlist coins: {watch}.")
    lines.append(
        "Contrast with your book (win 0.236, payoff 0.83): they win by "
        + _contrast_line(scorecards, by_id)
    )
    text = " ".join(lines)
    return text[:1499]


def _top_patterns(by_id: dict[str, dict[str, Any]]) -> list[str]:
    """Turn the strongest features into short numbered phrases.

    Args:
        by_id: feature-id -> feature.

    Returns:
        Up to four short phrases with numbers.
    """
    out: list[str] = []
    direction = by_id.get("direction_bias")
    if direction:
        out.append(f"lean {int(direction['magnitude']['mean_long_fraction'] * 100)}% long at entry.")
    hold = by_id.get("hold_time_asymmetry")
    if hold:
        out.append("cut losers fast, let winners run.")
    coins = by_id.get("coin_concentration")
    if coins:
        out.append(f"concentrate in {'/'.join(list(coins['magnitude']['coins'])[:3])}.")
    hour = by_id.get("hour_of_day_concentration")
    if hour:
        blk = hour["magnitude"]["peak_block_utc"]
        out.append(f"cluster entries around {blk[0]:02d}:00-{(blk[-1] + 1) % 24:02d}:00 UTC.")
    return out[:4]


def _contrast_line(scorecards: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]) -> str:
    """One reverse-engineering directive contrasting winners with the book.

    Args:
        scorecards: per-wallet scorecards.
        by_id: feature-id -> feature.

    Returns:
        A single directive sentence fragment.
    """
    reliable = [c for c in scorecards if c["method"] == "flat_to_flat"]
    payoffs = [c["payoff"] for c in reliable if c["payoff"] > 0]
    if by_id.get("hold_time_asymmetry"):
        return "asymmetric exits, not entry accuracy — encode a let-winners-run exit rule."
    if payoffs:
        return f"payoff ~{round(statistics.median(payoffs), 2)} vs your 0.83 — widen your winners' R-multiple."
    if not by_id:
        return "nothing trustworthy yet — no reverse-engineerable edge in this pull."
    return "coin focus and entry timing above; treat as a lead, not a proven edge."


def summarize(raw: dict[str, Any]) -> dict[str, Any]:
    """Run the whole pipeline over the raw blob and build the intel artifact.

    Args:
        raw: parsed ``winners_raw.json``.

    Returns:
        The ``winner_intel`` dict ready to serialize.
    """
    wallets = raw.get("wallets", [])
    board_n = raw.get("filter_counts", {}).get("board_n", len(wallets))
    dropped_mm = 0
    scorecards: list[dict[str, Any]] = []
    per_wallet_trades: dict[str, list[dict[str, Any]]] = {}
    survivors: set[str] = set()
    for record in wallets:
        fills = record.get("fills") or []
        stats = clonability_stats(fills)
        if not fills or is_liquidity_provider(stats):
            dropped_mm += 1
            continue
        trades, method = build_trades(fills)
        if not trades:
            dropped_mm += 1
            continue
        survivors.add(record["address"])
        per_wallet_trades[record["address"]] = trades
        scorecards.append(scorecard(record["address"], trades, stats, method))
    scorecards.sort(key=lambda c: c["skill_score"], reverse=True)
    features = build_aggregates(scorecards, per_wallet_trades, wallets, survivors)
    return {
        "generated_at": _raw_mtime_iso(),
        "universe": {
            "board_n": board_n,
            "cheap_survivors_n": raw.get("filter_counts", {}).get("survivors_after_cheap", len(wallets)),
            "pulled_n": len(wallets),
            "survivors_n": len(scorecards),
            "filtered_counts": {**raw.get("filter_counts", {}), "dropped_mm_or_empty": dropped_mm},
        },
        "scorecards": scorecards,
        "aggregate_features": features,
        "desk_text": render_desk_text(scorecards, features),
    }


def _raw_mtime_iso() -> str:
    """Deterministic timestamp: the mtime of the raw input file (ISO 8601 UTC).

    Returns:
        An ISO timestamp derived from ``winners_raw.json``'s mtime.
    """
    mtime = RAW_PATH.stat().st_mtime
    return datetime.datetime.fromtimestamp(mtime, tz=datetime.UTC).isoformat()


def main() -> None:
    """Load the raw blob, decompose it, and write ``winner_intel.json``."""
    with RAW_PATH.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    intel = summarize(raw)
    FORGE_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(intel, handle, indent=2)
        handle.write("\n")
    print(
        f"decompose: pulled {intel['universe']['pulled_n']} -> survivors {intel['universe']['survivors_n']}; "
        f"{len(intel['aggregate_features'])} aggregate features; wrote {OUT_PATH}"
    )


if __name__ == "__main__":
    main()
