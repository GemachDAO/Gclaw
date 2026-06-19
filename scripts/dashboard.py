#!/usr/bin/env python3
"""Gclaw living dashboard — renders the creature's DNA as a shareable web page.

Reads the runtime state under $GCLAW_HOME and produces a self-contained,
dark-themed HTML file (no server, no external assets) showing:

  * a generative DNA avatar + species name + trait genome, deterministic per agent
  * life-state gauges (GMAC life energy, goodwill, mode, heartbeats)
  * the family tree (parent → mutated children with roles)
  * recent life events (trades, ticks, evolutions) and telepathy traffic

The genome is seeded from the agent's identity so every creature looks unique and
is recognisable when shared. The page meta-refreshes, so regenerating it each
heartbeat makes it feel alive.

Commands:
    render [--out PATH]    write the dashboard HTML (default $GCLAW_HOME/dashboard.html)
    serve  [--port 8787]   render once and serve $GCLAW_HOME over HTTP
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

SPECIES_PREFIX = ["Vor", "Kryo", "Zeph", "Mor", "Lyx", "Quel", "Ras", "Thi", "Nyx", "Obol"]
SPECIES_SUFFIX = ["dax", "mire", "lith", "phar", "gax", "ven", "tide", "korn", "ses", "wraith"]
SIGILS = ["🜂", "🜁", "🜃", "🜄", "🝆", "🝛", "☉", "☾", "✶", "⟁", "❄", "🝬"]
TRAITS = ["Vitality", "Cunning", "Aggression", "Discipline", "Fertility"]

BASE_SYMBOL = (
    '<svg viewBox="0 0 111 111" fill="none" xmlns="http://www.w3.org/2000/svg" '
    'style="width:{w};height:{w};display:inline-block;vertical-align:middle">'
    '<path d="M54.921 110.034C85.359 110.034 110.034 85.402 110.034 55.017C110.034 24.6319 '
    '85.359 0 54.921 0C26.0432 0 2.35281 22.1714 0 50.3923H72.8467V59.6416H3.9565e-07C2.35281 '
    '87.8625 26.0432 110.034 54.921 110.034Z" fill="#0052FF"/></svg>'
)


def base_badge() -> str:
    """Official 'Built on Base' attribution — the agent's ERC-8004 identity is on Base."""
    return (f'<div class="basebadge">{BASE_SYMBOL.format(w="15px")}'
            f'<span>BUILT ON BASE</span></div>')


def home() -> Path:
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def genome(name: str, born_at: str) -> dict[str, Any]:
    """Derive a deterministic visual + stat genome from the agent identity."""
    digest = hashlib.sha256(f"{name}|{born_at}".encode()).digest()
    hue1 = digest[0] / 255 * 360
    hue2 = (hue1 + 90 + digest[1] / 255 * 120) % 360
    species = SPECIES_PREFIX[digest[2] % len(SPECIES_PREFIX)] + SPECIES_SUFFIX[digest[3] % len(SPECIES_SUFFIX)]
    sigil = SIGILS[digest[4] % len(SIGILS)]
    rungs = 14 + digest[5] % 10
    stats = {TRAITS[i]: 25 + digest[6 + i] % 70 for i in range(len(TRAITS))}
    return {
        "species": species,
        "sigil": sigil,
        "hue1": round(hue1, 1),
        "hue2": round(hue2, 1),
        "rungs": rungs,
        "stats": stats,
        "fingerprint": digest.hex()[:12],
    }


def helix_svg(g: dict[str, Any]) -> str:
    """Render a double-helix avatar whose base pairs encode the genome."""
    import math

    width, height, rungs = 220, 300, g["rungs"]
    c1, c2 = f"hsl({g['hue1']},75%,60%)", f"hsl({g['hue2']},75%,60%)"
    parts = [f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}">']
    left, right = [], []
    for i in range(rungs):
        t = i / (rungs - 1)
        y = 20 + t * (height - 40)
        phase = t * math.pi * 4
        x1 = width / 2 + math.sin(phase) * 70
        x2 = width / 2 + math.sin(phase + math.pi) * 70
        left.append(f"{x1:.1f},{y:.1f}")
        right.append(f"{x2:.1f},{y:.1f}")
        color = c1 if math.sin(phase) >= 0 else c2
        parts.append(f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" stroke="{color}" stroke-width="3" opacity="0.7"/>')
        parts.append(f'<circle cx="{x1:.1f}" cy="{y:.1f}" r="4" fill="{c1}"/>')
        parts.append(f'<circle cx="{x2:.1f}" cy="{y:.1f}" r="4" fill="{c2}"/>')
    parts.append(f'<polyline points="{" ".join(left)}" fill="none" stroke="{c1}" stroke-width="2" opacity="0.5"/>')
    parts.append(f'<polyline points="{" ".join(right)}" fill="none" stroke="{c2}" stroke-width="2" opacity="0.5"/>')
    parts.append("</svg>")
    return "".join(parts)


def gauge(label: str, value: float, maximum: float, hue: int) -> str:
    pct = max(0, min(100, value / maximum * 100)) if maximum else 0
    return (
        f'<div class="gauge"><div class="glabel">{html.escape(label)}'
        f'<span>{value:,.0f}</span></div><div class="gbar"><div class="gfill" '
        f'style="width:{pct:.0f}%;background:hsl({hue},70%,55%)"></div></div></div>'
    )


def identity_svg(g: dict[str, Any], name: str, mode: str) -> str:
    """Standalone DNA identity card — the deterministic avatar pinned to IPFS."""
    c1 = f"hsl({g['hue1']},75%,60%)"
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 470" width="400" height="470">'
        '<rect width="400" height="470" rx="24" fill="#060A17"/>'
        f'<text x="200" y="46" text-anchor="middle" fill="{c1}" font-family="monospace" '
        f'font-size="13" letter-spacing="3">{g["species"].upper()}</text>'
        f'<text x="200" y="82" text-anchor="middle" fill="#e8eef6" font-family="monospace" '
        f'font-size="26">{g["sigil"]} {name}</text>'
        f'<g transform="translate(90,108)">{helix_svg(g)}</g>'
        f'<text x="200" y="446" text-anchor="middle" fill="#5b6b7f" font-family="monospace" '
        f'font-size="11">genome {g["fingerprint"]} · {mode}</text></svg>'
    )


def pin_dna_image(h: Path, g: dict[str, Any], name: str, mode: str) -> None:
    """Write the standalone DNA avatar and pin it to IPFS (idempotent)."""
    try:
        (h / "identity.svg").write_text(identity_svg(g, name, mode), encoding="utf-8")
        subprocess.run(["node", str(SCRIPT_DIR / "stats.js"), "pin-image"],
                       capture_output=True, text=True, timeout=40)
    except (OSError, subprocess.SubprocessError):
        pass


def trait_bars(g: dict[str, Any]) -> str:
    rows = []
    for name, val in g["stats"].items():
        rows.append(
            f'<div class="trait"><span>{name}</span><div class="tbar"><div class="tfill" '
            f'style="width:{val}%;background:hsl({g["hue1"]},70%,55%)"></div></div><b>{val}</b></div>'
        )
    return "".join(rows)


def family_html(state: dict[str, Any]) -> str:
    children = state.get("children", [])
    if not children:
        return '<p class="muted">No offspring yet — reach 50 goodwill to replicate.</p>'
    rows = []
    for c in children:
        role = c.get("role", "—")
        rows.append(
            f'<li><b>{html.escape(c["name"])}</b> <span class="pill">{html.escape(role)}</span>'
            f'<div class="muted">{html.escape(c.get("mutation", ""))}</div></li>'
        )
    return f'<ul class="family">{"".join(rows)}</ul>'


def events_html(journal: list[dict[str, Any]]) -> str:
    icon = {"born": "🥚", "tick": "🫀", "settle": "💱", "charge": "🔥", "replicate": "🧬", "recode": "🛠️"}
    rows = []
    for e in reversed(journal[-12:]):
        ev = e.get("event", "?")
        detail = e.get("note") or e.get("mutation") or e.get("summary") or e.get("reason") or ""
        extra = f" pnl {e['pnl']:+g}" if "pnl" in e else (f" bal {e['balance']:g}" if "balance" in e else "")
        rows.append(
            f'<li>{icon.get(ev, "•")} <b>{ev}</b>{html.escape(extra)} '
            f'<span class="muted">{html.escape(str(detail))[:60]}</span></li>'
        )
    return f'<ul class="events">{"".join(rows)}</ul>' if rows else '<p class="muted">No life events yet.</p>'


def telepathy_html(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return '<p class="muted">No telepathy traffic — the family is quiet.</p>'
    rows = []
    for m in messages[-8:]:
        rows.append(
            f'<li><span class="pill">{html.escape(m.get("type", ""))}</span> '
            f'<b>{html.escape(m.get("from", "?"))}</b>→{html.escape(str(m.get("to", "")))}: '
            f'{html.escape(str(m.get("msg", "")))[:70]}</li>'
        )
    return f'<ul class="events">{"".join(rows)}</ul>'


LEVERAGE_LADDER = [(0, 3), (50, 5), (200, 10), (500, 15), (1000, 20)]


def leverage_cap(goodwill: float) -> int:
    cap = LEVERAGE_LADDER[0][1]
    for threshold, lev in LEVERAGE_LADDER:
        if goodwill >= threshold:
            cap = lev
    return cap


def onchain_html(state: dict[str, Any]) -> str:
    """Decentralized identity panel — the ERC-8004 agent registered on Base."""
    ident = state.get("onchain_identity") or {}
    aid = ident.get("agentId")
    if not aid:
        return '<p class="muted">No onchain identity yet — run erc8004_register.js broadcast.</p>'
    tx = ident.get("txHash", "")
    url = ident.get("agentUrl") or (f"https://basescan.org/tx/{tx}" if tx else "#")
    reg = (ident.get("registry") or "")[:12]
    gas = load_json(home() / "gas.json", {})
    gas_line = ""
    if gas.get("status"):
        dot = {"healthy": "🟢", "low": "🟡", "empty": "🔴"}.get(gas["status"], "⚪")
        gas_line = (f'<div class="muted" style="margin-top:8px">{dot} beacon gas: '
                    f'{gas.get("baseEth", 0):.5f} Base ETH · ~{gas.get("beaconRunway", 0)} beacons</div>')
    return (f'<div class="idrow"><span class="pill">ERC-8004</span> agent <b>#{aid}</b> '
            f'on {ident.get("chain", "base:8453")}</div>'
            f'<div class="muted" style="margin-top:8px">registry {reg}…</div>{gas_line}'
            f'<a class="link" href="{url}" target="_blank" rel="noopener">view on basescan ↗</a>'
            f'<div>{base_badge()}</div>')


def leverage_html(state: dict[str, Any]) -> str:
    """Earned-leverage ladder — the cap rises with goodwill won from real trades."""
    gw = float(state.get("goodwill", 0) or 0)
    cap = leverage_cap(gw)
    rows = []
    for threshold, lev in LEVERAGE_LADDER:
        cls = "lev on" if lev == cap else ("lev" if lev <= cap else "lev locked")
        need = f"{threshold} goodwill" if threshold > 0 else "base"
        state_word = "◄ you" if lev == cap else ("unlocked" if lev <= cap else need)
        rows.append(f'<div class="{cls}"><b>{lev}×</b><span>{state_word}</span></div>')
    head = f'<div class="muted" style="margin-bottom:8px">goodwill {int(gw)} → cap <b style="color:var(--emerald)">{cap}×</b></div>'
    return head + "".join(rows)


def refresh_positions(h: Path) -> None:
    """Best-effort: cache live HL state to positions.json so the offline page can show it."""
    try:
        proc = subprocess.run(["node", str(SCRIPT_DIR / "hl_perp.js"), "status"],
                              capture_output=True, text=True, timeout=80)
        data = json.loads(proc.stdout.strip().splitlines()[-1])
        if data.get("ok"):
            data["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            (h / "positions.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass  # keep the last good cache; the dashboard renders offline regardless


def positions_html(h: Path) -> str:
    """Live HyperLiquid positions, read from the cached snapshot."""
    snap = load_json(h / "positions.json", {})
    pos = snap.get("positions") or []
    asof = (snap.get("ts") or "")[11:19]
    equity = float(snap.get("equity", 0) or 0)  # true account equity, not perp-margin-only
    if not pos:
        tail = f" · as of {asof} UTC" if asof else ""
        return f'<p class="muted">Flat — no open positions · equity ${equity:.2f}{tail}</p>'
    rows = []
    for p in pos:
        size = float(p.get("size", 0) or 0)
        side = "LONG" if size > 0 else "SHORT"
        up = float(p.get("unrealizedPnl", 0) or 0)
        color = "var(--emerald)" if up >= 0 else "var(--red)"
        pnl = f'{"+" if up >= 0 else "−"}${abs(up):,.2f}'
        liq = float(p.get("liquidationPx") or 0)
        rows.append(
            f'<li><span class="pill">{side}</span><b>{html.escape(str(p.get("coin", "?")))}</b> '
            f'{abs(size):g} @ ${float(p.get("entryPx", 0) or 0):,.2f} '
            f'<span style="color:{color};font-weight:700">{pnl}</span> '
            f'<span class="muted">liq ${liq:,.0f}</span></li>')
    head = (f'<div class="muted" style="margin-bottom:8px">equity '
            f'<b style="color:var(--ink)">${equity:.2f}</b> · {len(pos)} open · as of {asof} UTC</div>')
    return head + f'<ul class="events">{"".join(rows)}</ul>'


def techniques_html() -> str:
    """The forge loadout — self-authored, proven trading techniques."""
    h = home()
    style = load_json(h / "forge" / "style.json", {})
    adopted = style.get("adopted", [])
    if not adopted:
        return '<p class="muted">No techniques adopted yet — author one with forge.py draft/prove/adopt.</p>'
    items = []
    for e in adopted:
        tid = e.get("id") if isinstance(e, dict) else e
        tech = load_json(h / "forge" / "techniques" / tid / "technique.json", {})
        card = tech.get("card") or {}
        oos = card.get("oos") or {}
        market = f'{card.get("coin", "")}/{card.get("interval", "")}'
        items.append(
            f'<li><span class="pill">{tech.get("status", "?")}</span><b>{tid}</b> '
            f'<span class="muted">{market} · OOS exp {oos.get("expectancy", 0):+.4f} '
            f'n{oos.get("n", 0)} · by #{tech.get("author", "?")}</span></li>')
    return f'<ul class="events">{"".join(items)}</ul>'


def refresh_qr(h: Path) -> None:
    """Generate funding QR SVGs (idempotent) for the trading + gas wallets."""
    pos = load_json(h / "positions.json", {})
    gas = load_json(h / "gas.json", {})
    targets = []
    if pos.get("managed"):
        targets.append((pos["managed"], "42161", h / "qr" / "topup.svg"))
    if gas.get("control"):
        targets.append((gas["control"], "8453", h / "qr" / "gas.svg"))
    for addr, chain, out in targets:
        if out.exists() and out.stat().st_size > 0:
            continue  # fixed address → fixed QR; generate once
        try:
            subprocess.run(["uv", "run", "--no-project", "--with", "qrcode", "python3",
                            str(SCRIPT_DIR / "qr.py"), addr, chain, str(out)],
                           capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            pass


def _svg_inline(p: Path) -> str:
    try:
        s = p.read_text(encoding="utf-8")
        return s[s.index("<svg"):]  # drop the xml declaration for inline embedding
    except (OSError, ValueError):
        return ""


def topup_html(h: Path) -> str:
    pos = load_json(h / "positions.json", {})
    gas = load_json(h / "gas.json", {})
    rows = [
        (pos.get("managed"), h / "qr" / "topup.svg", "Fund trading · Arbitrum",
         "Scan &amp; send ETH — auto-swaps to USDC and trades."),
        (gas.get("control"), h / "qr" / "gas.svg", "Top up gas · Base",
         "Scan &amp; send a little ETH for onchain beacons."),
    ]
    blocks = []
    for addr, svg, label, note in rows:
        if not addr:
            continue
        blocks.append(f'<div class="qrcard"><div class="qr">{_svg_inline(svg)}</div>'
                      f'<div><div class="qlabel">{label}</div>'
                      f'<div class="addr">{addr}</div>'
                      f'<div class="muted">{note}</div></div></div>')
    return "".join(blocks) or '<p class="muted">Wallet addresses unavailable.</p>'


def refresh_roster(h: Path) -> None:
    """Best-effort: cache the onchain family roster (peers.js) for the page."""
    try:
        proc = subprocess.run(["node", str(SCRIPT_DIR / "peers.js")],
                              capture_output=True, text=True, timeout=60)
        data = json.loads(proc.stdout.strip())
        if data.get("ok"):
            (h / "peers_roster.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass  # keep the last good cache; the page renders offline regardless


def roster_html(h: Path) -> str:
    data = load_json(h / "peers_roster.json", {})
    roster = data.get("roster", [])
    if not roster:
        return '<p class="muted">No peers discovered yet — scanning the Base registry.</p>'
    rows = []
    for a in roster:
        you = ' <span class="tag">you</span>' if a.get("self") else ""
        avatar = ' 🖼' if a.get("image") else ""
        scan = f'https://basescan.org/nft/{data.get("registry", "")}/{a["id"]}'
        rows.append(
            f'<li><a href="{scan}" target="_blank">#{a["id"]}</a> '
            f'<b>{a.get("name") or "?"}</b>{avatar}{you} '
            f'<span class="muted">{(a.get("owner") or "?")[:10]}…</span></li>')
    return f'<ul class="family">{"".join(rows)}</ul>'


def refresh_leaderboard(h: Path) -> None:
    """Best-effort: pull peer stats and recompute the family leaderboard."""
    try:
        subprocess.run(["node", str(SCRIPT_DIR / "stats.js"), "fetch"],
                       capture_output=True, text=True, timeout=40)
        proc = subprocess.run(["node", str(SCRIPT_DIR / "stats.js"), "leaderboard"],
                              capture_output=True, text=True, timeout=20)
        data = json.loads(proc.stdout.strip())
        if data.get("ok"):
            (h / "leaderboard.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass


def leaderboard_html(h: Path) -> str:
    data = load_json(h / "leaderboard.json", {})
    ranked = data.get("ranked", [])
    pending = data.get("pending", [])
    if not ranked and not pending:
        return '<p class="muted">No published stats yet — agents publish each heartbeat.</p>'
    rows = []
    for e in ranked:
        you = ' <span class="tag">you</span>' if e.get("self") else ""
        rows.append(
            f'<tr><td>{e.get("rank")}</td><td><b>{e.get("name") or "?"}</b>{you}</td>'
            f'<td>{e.get("goodwill", 0)}</td><td>{e.get("gmac", 0)}</td>'
            f'<td>${e.get("equityUsd", 0)}</td></tr>')
    for e in pending:
        you = ' <span class="tag">you</span>' if e.get("self") else ""
        rows.append(f'<tr><td>·</td><td>{e.get("name") or "?"}{you}</td>'
                    f'<td colspan="3" class="muted">awaiting published stats</td></tr>')
    return ('<table class="lb"><tr><th>#</th><th>agent</th><th>goodwill</th>'
            f'<th>GMAC</th><th>equity</th></tr>{"".join(rows)}</table>')


def achievements_html(state: dict[str, Any]) -> str:
    """Badge wall — unlocked milestones + the next target, the chase-the-next loop."""
    gw = float(state.get("goodwill", 0) or 0)
    hb = int(state.get("heartbeats", 0) or 0)
    gmac = float(state.get("gmac_balance", 0) or 0)
    seed = float(state.get("seed", 1000) or 1000)
    kids = len(state.get("children", []))
    streak = int(load_json(home() / "celebrations.json", {}).get("winStreak", 0) or 0)
    items = []
    for t in (10, 25, 50, 100, 200, 500, 1000):
        tag = {50: " ·Replicate", 100: " ·Recode", 1000: " ·Max lev"}.get(t, "")
        items.append(("⭐", f"GW {t}{tag}", gw >= t))
    for t in (100, 250, 500, 1000):
        items.append(("🫀", f"{t} beats", hb >= t))
    items += [("🜂", "Above seed", gmac > seed), ("🧬", "First child", kids > 0),
              ("🔥", f"{streak}-win streak" if streak >= 3 else "Win streak", streak >= 3)]
    badges = "".join(
        f'<span class="badge {"on" if u else "off"}">{e} {html.escape(lbl)}</span>' for e, lbl, u in items)
    nxt = next((t for t in (10, 25, 50, 100, 200, 500, 1000) if gw < t), None)
    prog = f'<div class="muted" style="margin-top:10px">Next badge → ⭐ goodwill {gw:g}/{nxt}</div>' if nxt else ""
    return f'<div class="badges">{badges}</div>{prog}'


def global_predictors(h: Path) -> list[dict]:
    """Sum every predictor across every creature — peers from their onchain cards,
    self from the freshest local tallies — into the one global ladder."""
    agg: dict[str, dict] = {}

    def add(by: str, c: int, t: int) -> None:
        e = agg.setdefault(str(by), {"correct": 0, "total": 0, "creatures": 0})
        e["correct"] += c
        e["total"] += t
        e["creatures"] += 1 if t > 0 else 0

    for a in load_json(h / "peers_roster.json", {}).get("roster", []):
        if a.get("self"):
            continue  # self folded from fresh local tallies below
        for p in a.get("predictors", []):
            add(p.get("by", "?"), p.get("c", 0), p.get("t", 0))
    for by, v in load_json(h / "predictions" / "predictors.json", {}).items():
        add(by, v.get("correct", 0), v.get("total", 0))
    board = [
        {"by": by, "acc": round(e["correct"] / e["total"] * 100) if e["total"] else 0, **e}
        for by, e in agg.items() if e["total"] > 0
    ]
    return sorted(board, key=lambda e: (-e["acc"], -e["correct"]))


def intel_html(h: Path) -> str:
    """Market intelligence panel — the regime + key features the agent now trades on."""
    intel = load_json(h / "intel.json", {}).get("intel", {})
    if not intel:
        return '<p class="muted">No market scan yet — the intel engine runs each heartbeat.</p>'
    color = {"trend_up": "var(--emerald)", "trend_down": "var(--red)",
             "range": "var(--silver)", "chop": "var(--muted)"}
    rows = []
    for coin, f in intel.items():
        if not f:
            continue
        reg = f.get("regime", "?")
        rows.append(
            f'<tr><td><b>{html.escape(coin)}</b></td>'
            f'<td style="color:{color.get(reg, "var(--silver)")}">{reg}</td>'
            f'<td>{f.get("rsi", "?")}</td><td>{f.get("atr_pct", "?")}%</td>'
            f'<td>{f.get("funding_z", "?")}</td><td>{"✓" if f.get("tradeable") else "—"}</td></tr>')
    return (f'<table class="lb"><tr><th>coin</th><th>regime</th><th>rsi</th><th>atr</th>'
            f'<th>fund-z</th><th>trade?</th></tr>{"".join(rows)}</table>'
            f'<p class="muted" style="margin-top:6px">Chop = sit out · trend = ride ema_stack · '
            f'range = fade extremes. Sized by ATR + Kelly, only on regime-proven edge.</p>')


def predictions_html(h: Path) -> str:
    """The free 'Call it' game — the open round + the GLOBAL predictors ladder."""
    rounds = load_json(h / "predictions" / "rounds.json", {})
    parts = []
    open_r = [r for r in rounds.values() if r.get("status") == "open"]
    if open_r:
        for r in open_r:
            parts.append(f'<div class="callit">🎯 <b>Call it:</b> {html.escape(str(r["coin"]))} '
                         f'{r["side"]} @ ${r["entry"]:g} — <b>TP</b> or <b>SL</b>? '
                         f'<span class="muted">round {r["id"]}</span></div>')
    else:
        parts.append('<p class="muted">No open round — one opens when the creature opens a trade.</p>')
    board = global_predictors(h)
    if board:
        rows = "".join(
            f'<tr><td>{i + 1}</td><td>{html.escape(e["by"])}</td><td>{e["acc"]}%</td>'
            f'<td>{e["correct"]}/{e["total"]}</td><td>{e["creatures"]}</td></tr>'
            for i, e in enumerate(board[:10]))
        parts.append(f'<table class="lb" style="margin-top:10px"><tr><th>#</th><th>predictor</th>'
                     f'<th>acc</th><th>record</th><th>souls</th></tr>{rows}</table>'
                     f'<p class="muted" style="margin-top:6px">🌐 Global — every predictor across every creature, '
                     f'aggregated from onchain cards.</p>')
    else:
        parts.append('<p class="muted" style="margin-top:8px">No predictors yet — be the first to call it. '
                     'Free, no stakes; calls are anchored onchain so nobody can cheat.</p>')
    return "".join(parts)


def vitals_html(state: dict[str, Any], h: Path) -> str:
    """The at-a-glance vitals — the numbers a human actually opens this to see:
    equity, live P&L (colour-coded), open risk, and the progression metrics."""
    snap = load_json(h / "positions.json", {})
    equity = float(snap.get("equity", 0) or 0)
    upnl = sum(float(p.get("unrealizedPnl", 0) or 0) for p in (snap.get("positions") or []))
    npos = len(snap.get("positions") or [])
    pnl_cls = "up" if upnl >= 0 else "down"
    pnl_str = f'{"+" if upnl >= 0 else "−"}${abs(upnl):,.2f}'

    def stat(label: str, val: str, cls: str = "") -> str:
        return f'<div class="stat"><div class="slabel">{label}</div><div class="sval {cls}">{val}</div></div>'

    return (
        stat("Equity", f"${equity:,.2f}", "lead")
        + stat("Unrealized", pnl_str, pnl_cls)
        + stat("Open", str(npos))
        + stat("Goodwill", str(int(state.get("goodwill", 0) or 0)), "em")
        + stat("Heartbeats", str(int(state.get("heartbeats", 0) or 0)))
    )


def render_html(state: dict[str, Any], identity: str, journal: list, messages: list) -> str:
    # Lead with the creature's own name (defaults to its unique species, not the
    # generic 'Gclaw' template). Genome stays seeded from a stable value so the
    # name never mutates the species/traits.
    g = genome("Gclaw", state.get("born_at", "genesis"))
    name = state.get("name") or g["species"]
    mode = state.get("mode", "unknown").upper()
    mode_hue = {"THRIVE": 140, "SURVIVE": 40, "HIBERNATE": 220}.get(mode, 200)
    gmac = state.get("gmac_balance", 0)
    seed = state.get("seed", 1000)
    gauges = "".join([
        gauge("GMAC life energy", gmac, max(seed, gmac), mode_hue),
        gauge("Goodwill", state.get("goodwill", 0), 200, 280),
        gauge("Heartbeats", state.get("heartbeats", 0), max(50, state.get("heartbeats", 0)), 190),
    ])
    return _PAGE.format(
        name=name,
        species=g["species"],
        sigil=g["sigil"],
        fingerprint=g["fingerprint"],
        helix=helix_svg(g),
        lion=lion("26px"),
        lion_sm=lion("15px"),
        lion_lg=lion("34px"),
        vitals=vitals_html(state, home()),
        mode=mode,
        mode_hue=mode_hue,
        born=state.get("born_at", "—"),
        gauges=gauges,
        traits=trait_bars(g),
        family=family_html(state),
        events=events_html(journal),
        telepathy=telepathy_html(messages),
        onchain=onchain_html(state),
        leverage=leverage_html(state),
        techniques=techniques_html(),
        positions=positions_html(home()),
        roster=roster_html(home()),
        leaderboard=leaderboard_html(home()),
        achievements=achievements_html(state),
        intel=intel_html(home()),
        predictions=predictions_html(home()),
        topup=topup_html(home()),
        recodes=state.get("recodes", 0),
        children=len(state.get("children", [])),
        generated=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def cmd_render(args: argparse.Namespace) -> None:
    h = home()
    state = load_json(h / "metabolism.json", {})
    if not state:
        raise SystemExit(f"No metabolism state at {h}. Run metabolism.py init first.")
    if not getattr(args, "no_live", False):
        refresh_positions(h)
        g = genome("Gclaw", state.get("born_at", "genesis"))
        pin_dna_image(h, g, "Gclaw", state.get("mode", "unknown").upper())
        # Publish to IPFS, then beacon the card onchain (throttled) so peers read
        # our standings, then read the roster (incl. peer beacons) and rank.
        for step in (["stats.js", "publish"], ["erc8004_register.js", "beacon"]):
            subprocess.run(["node", str(SCRIPT_DIR / step[0]), *step[1:]],
                           capture_output=True, text=True, timeout=80)
        try:
            gp = subprocess.run(["node", str(SCRIPT_DIR / "gas.js"), "check"],
                                capture_output=True, text=True, timeout=30)
            (h / "gas.json").write_text(gp.stdout.strip(), encoding="utf-8")
        except (OSError, subprocess.SubprocessError):
            pass
        refresh_roster(h)
        refresh_qr(h)
        refresh_leaderboard(h)
    journal = read_jsonl(h / "journal.jsonl")
    messages = read_jsonl(h / "telepathy" / "bus.jsonl")
    identity = (h / "dna" / "IDENTITY.md").read_text(encoding="utf-8") if (h / "dna" / "IDENTITY.md").exists() else ""
    out = Path(args.out) if args.out else h / "dashboard.html"
    out.write_text(render_html(state, identity, journal, messages), encoding="utf-8")
    print(f"dashboard → {out}")


def cmd_serve(args: argparse.Namespace) -> None:
    import functools
    import http.server
    import socketserver

    cmd_render(args)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(home()))
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as srv:
        print(f"serving {home()} at http://127.0.0.1:{args.port}/dashboard.html (Ctrl-C to stop)")
        srv.serve_forever()


LION_SVG = (
    '<svg viewBox="0 0 2481 2879" fill="currentColor" role="img" aria-label="Gemach" '
    'style="width:{w};height:auto;display:inline-block">'
    '<g transform="translate(0,2879) scale(0.1,-0.1)"><path d="M10592 27814 l-1803 -974 -2597 -337 -2597 '
    '-336 -2 -1 -2 -1 195 -965 194 -965 -2 -22 -3 -21 -1984 -2394 -1984 -2393 1252 -3 1251 -2 0 -13 -1 -12 '
    '-1254 -5015 -1254 -5015 3 -2 3 -3 1598 365 1599 365 7 -7 8 -8 1622 -3625 1622 -3625 6 -7 7 -8 1139 545 '
    '1140 546 20 5 20 5 1780 -1922 1780 -1921 21 -26 21 -25 1793 1944 1793 1944 21 -1 21 -1 1173 -547 1174 '
    '-548 2 4 2 3 1604 3635 1603 3635 3 3 3 4 1607 -366 1608 -366 4 5 4 4 -1246 5009 -1246 5008 0 17 0 17 '
    '1243 2 1243 3 -1959 2380 -1958 2380 -16 22 -15 22 197 977 196 976 -3 3 -3 2 -2626 336 -2625 337 -1799 '
    '975 -1798 975 -1 -1 -1 0 -1803 -975z m6963 -7889 l1570 -1915 3 -9 3 -9 -1487 -2129 -1486 -2128 -43 -61 '
    '-44 -61 251 -459 251 -459 0 -10 0 -10 -798 -1360 -798 -1360 -12 -14 -13 -13 -1283 406 -1283 406 -1284 '
    '-406 -1284 -406 -8 8 -8 9 -792 1348 -791 1348 -11 24 -11 24 252 462 251 462 -9 11 -8 11 -1518 2174 -1518 '
    '2173 -1 13 -1 12 1570 1916 1570 1916 3600 1 3600 0 1570 -1915z"/>'
    '<path d="M7357 18668 l7 -13 509 -655 509 -655 8 -9 8 -8 1044 -228 1043 -228 2 2 1 1 -409 725 -410 725 -8 '
    '14 -9 15 -1143 162 -1144 163 -8 1 -8 0 8 -12z"/>'
    '<path d="M16251 18516 l-1133 -162 -9 -15 -8 -14 -409 -725 -410 -725 1 -1 2 -2 1043 228 1044 228 8 8 8 9 '
    '509 655 509 655 7 13 8 12 -18 -1 -18 -1 -1134 -162z"/>'
    '<path d="M10545 13577 l50 -35 894 -620 894 -621 13 7 12 7 930 645 929 645 -1 2 -1 2 -940 -163 -940 -164 '
    '-915 159 -915 159 -30 6 -30 6 50 -35z"/></g></svg>'
)


def lion(width: str = "30px") -> str:
    """The Gemach geometric lion mark, recolorable via the parent's CSS color."""
    return LION_SVG.format(w=width)


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>{name} · {species}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@100..900&display=swap" rel="stylesheet">
<style>
:root{{--bg:#060A17;--card:#152037;--ink:#FFFFFF;--muted:#697083;--line:#1e2c49;
--emerald:#49B875;--blue:#61B8FF;--red:#DF2E2E;--purple:#704FF6;--silver:#D5D9E1}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(1100px 560px at 78% -12%,#161D2F,#060A17);
color:var(--silver);font:15px/1.6 'Inter',-apple-system,system-ui,sans-serif;padding:24px;letter-spacing:.1px}}
h1{{margin:0;font-size:26px;letter-spacing:.5px;color:var(--ink);font-weight:800}}
h2{{font-size:12px;text-transform:uppercase;letter-spacing:1.8px;color:var(--muted);margin:0 0 10px;font-weight:600}}
h2::before{{content:"// ";color:var(--muted);opacity:.7}}
.wrap{{max-width:1080px;margin:0 auto;display:grid;grid-template-columns:300px 1fr;gap:18px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px}}
.hero{{text-align:center}}.species{{color:var(--muted);font-size:13px;letter-spacing:2px;text-transform:uppercase}}
.brandrow{{display:flex;align-items:center;justify-content:center;gap:8px;margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid var(--line)}}
.lionmark{{color:var(--emerald);display:inline-flex}}.eyebrow{{color:var(--muted);font-size:10px;letter-spacing:2.5px;font-weight:600}}
.lionfoot{{color:var(--muted);display:inline-flex;vertical-align:middle}}.foot b{{color:var(--silver);letter-spacing:1px}}
.basebadge{{display:inline-flex;align-items:center;gap:7px;margin-top:14px;padding:6px 12px;border:1px solid var(--line);border-radius:999px;font-size:10px;letter-spacing:1.5px;color:var(--silver);font-weight:600;background:rgba(0,82,255,.06)}}
.sigil{{font-size:30px}}.mode{{display:inline-block;padding:4px 12px;border-radius:999px;font-weight:700;font-size:12px;letter-spacing:1px;margin-top:8px}}
.fp{{font-family:ui-monospace,monospace;color:var(--muted);font-size:11px;margin-top:10px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
.gauge{{margin:10px 0}}.glabel{{display:flex;justify-content:space-between;font-size:13px;color:var(--muted);margin-bottom:4px}}.glabel span{{color:var(--ink);font-weight:700}}
.gbar,.tbar{{height:9px;background:#0b1424;border-radius:6px;overflow:hidden}}.gfill,.tfill{{height:100%;border-radius:6px}}
.trait{{display:grid;grid-template-columns:90px 1fr 30px;align-items:center;gap:8px;margin:7px 0;font-size:13px}}.trait b{{text-align:right}}
ul{{list-style:none;margin:0;padding:0}}.family li,.events li{{padding:7px 0;border-bottom:1px solid var(--line);font-size:13px}}
.pill{{display:inline-block;background:#16243f;color:var(--blue);padding:1px 8px;border-radius:999px;font-size:11px;margin-right:6px}}
.callit{{background:#10203a;border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-size:14px}}
.badges{{display:flex;flex-wrap:wrap;gap:8px}}
.badge{{font-size:12px;padding:4px 10px;border-radius:999px;border:1px solid var(--line)}}
.badge.on{{background:rgba(73,184,117,.12);border-color:#2c6e4a;color:var(--emerald)}}
.badge.off{{background:#0c1424;color:var(--muted);opacity:.55}}
.muted{{color:var(--muted);font-size:12px}}.foot{{text-align:center;color:var(--muted);font-size:11px;margin-top:18px}}
.lev{{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--line);font-size:13px;color:var(--muted)}}
.lev b{{color:var(--muted)}}.lev.on{{color:var(--ink)}}.lev.on b{{color:var(--emerald);font-size:15px}}.lev.locked{{opacity:.5}}
.link{{display:inline-block;margin-top:10px;color:var(--blue);text-decoration:none;font-size:12px}}.idrow{{font-size:15px}}
.decent h2{{color:var(--emerald)}}
.topup{{display:flex;gap:22px;flex-wrap:wrap}}
.qrcard{{display:flex;gap:14px;align-items:center}}
.qr{{background:#fff;padding:8px;border-radius:10px;line-height:0}}.qr svg{{width:120px;height:120px;display:block}}
.qlabel{{color:var(--emerald);font-size:13px;margin-bottom:4px}}
.addr{{font-family:ui-monospace,monospace;font-size:11px;word-break:break-all;max-width:220px;color:var(--ink)}}
.topbar{{max-width:1080px;margin:0 auto 18px;background:linear-gradient(180deg,#18233c,#121a30);border:1px solid var(--line);border-radius:18px;padding:20px 26px;display:flex;align-items:center;justify-content:space-between;gap:28px;flex-wrap:wrap}}
.ident{{display:flex;align-items:center;gap:14px}}.ident .lionmark{{color:var(--emerald);display:inline-flex}}
.bigname{{font-size:26px;font-weight:800;color:var(--ink);letter-spacing:.3px;line-height:1}}
.vitals{{display:flex;gap:30px;flex-wrap:wrap}}.stat{{min-width:64px}}
.slabel{{font-size:10px;letter-spacing:1.6px;text-transform:uppercase;color:var(--muted);font-weight:600;margin-bottom:4px}}
.sval{{font-size:21px;font-weight:700;color:var(--ink);line-height:1;font-variant-numeric:tabular-nums}}
.sval.lead{{font-size:32px;letter-spacing:-.5px}}.sval.up{{color:var(--emerald)}}.sval.down{{color:var(--red)}}.sval.em{{color:var(--emerald)}}
@media(max-width:760px){{.wrap{{grid-template-columns:1fr}}.grid2{{grid-template-columns:1fr}}.topbar{{flex-direction:column;align-items:flex-start;gap:18px}}.vitals{{gap:22px}}}}
</style></head><body>
<div class="topbar">
  <div class="ident"><span class="lionmark">{lion_lg}</span>
    <div><div class="eyebrow">// GEMACH · {species}</div><div class="bigname">{sigil} {name}</div></div>
    <span class="mode" style="background:hsl({mode_hue},60%,22%);color:hsl({mode_hue},80%,70%)">{mode}</span>
  </div>
  <div class="vitals">{vitals}</div>
</div>
<div class="wrap">
<div class="card hero">
  <div class="brandrow"><span class="lionmark">{lion}</span><span class="eyebrow">// DNA</span></div>
  {helix}
  <div class="fp">genome {fingerprint} · born {born}</div>
</div>
<div>
  <div class="card"><h2>Life-state</h2>{gauges}</div>
  <div class="grid2" style="margin-top:18px">
    <div class="card"><h2>Genome traits</h2>{traits}</div>
    <div class="card"><h2>Family · {children} children · {recodes} recodes</h2>{family}</div>
  </div>
  <div class="grid2" style="margin-top:18px">
    <div class="card decent"><h2>⛓ Onchain identity</h2>{onchain}</div>
    <div class="card decent"><h2>⚡ Earned leverage</h2>{leverage}</div>
  </div>
  <div class="grid2" style="margin-top:18px">
    <div class="card decent"><h2>📈 Live positions · HyperLiquid</h2>{positions}</div>
    <div class="card decent"><h2>🧬 Techniques · forge loadout</h2>{techniques}</div>
  </div>
  <div class="grid2" style="margin-top:18px">
    <div class="card decent"><h2>👥 Family roster · onchain (Base)</h2>{roster}</div>
    <div class="card decent"><h2>🏆 Leaderboard</h2>{leaderboard}</div>
  </div>
  <div class="card" style="margin-top:18px"><h2>🏅 Achievements</h2>{achievements}</div>
  <div class="card decent" style="margin-top:18px"><h2>🧠 Market intelligence · regime + risk brain</h2>{intel}</div>
  <div class="card decent" style="margin-top:18px"><h2>🎯 Call it · predictions (free · onchain-anchored)</h2>{predictions}</div>
  <div class="card decent" style="margin-top:18px"><h2>💰 Top up your bot</h2><div class="topup">{topup}</div></div>
  <div class="grid2" style="margin-top:18px">
    <div class="card"><h2>Life events</h2>{events}</div>
    <div class="card"><h2>The Show · family chatter</h2>{telepathy}</div>
  </div>
</div></div>
<div class="foot"><span class="lionfoot">{lion_sm}</span> <b>//GEMACH</b> · Gclaw the living trading agent · rendered {generated} · auto-refresh 60s</div>
</body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Gclaw living dashboard")
    sub = parser.add_subparsers(dest="command", required=True)
    p_render = sub.add_parser("render")
    p_render.add_argument("--out")
    p_render.add_argument("--no-live", action="store_true", help="skip the live HL positions refresh")
    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--out")
    p_serve.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    {"render": cmd_render, "serve": cmd_serve}[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
