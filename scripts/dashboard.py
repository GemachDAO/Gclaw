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
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

IDENTITY_REGISTRY = "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"  # ERC-8004 on Base
GITHUB_URL = "https://github.com/GemachDAO/Gclaw"


def github_qr_datauri(h: Path) -> str:
    """A PNG QR of the GitHub repo as a base64 data URI (generated once, cached) —
    so anyone who scans the dashboard or a shared card can clone it and run their own."""
    png = h / "qr" / "github.png"
    if not (png.exists() and png.stat().st_size > 0):
        try:
            subprocess.run(
                [
                    "uv",
                    "run",
                    "--no-project",
                    "--with",
                    "qrcode",
                    "--with",
                    "pillow",
                    "python3",
                    str(SCRIPT_DIR / "qr.py"),
                    GITHUB_URL,
                    "raw",
                    str(png),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
    try:
        import base64

        return "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode("ascii")
    except (OSError, ValueError):
        return ""


def share_url(state: dict[str, Any], name: str, equity: float) -> str:
    """A Twitter/X intent link to flex the creature — links to its verifiable
    onchain identity (or the repo) so the share proves it's real."""
    aid = (state.get("onchain_identity") or {}).get("agentId")
    link = (
        f"https://basescan.org/nft/{IDENTITY_REGISTRY}/{aid}"
        if aid
        else "https://github.com/GemachDAO/Gclaw"
    )
    text = (
        f"Meet {name} 🦁🧬 — my living, onchain trading agent. Equity ${equity:,.0f}, "
        f"fully verifiable on @base. A creature that must trade to survive, built with @GemachDAO."
    )
    return "https://twitter.com/intent/tweet?" + urllib.parse.urlencode({"text": text, "url": link})


SCRIPT_DIR = Path(__file__).resolve().parent

SPECIES_PREFIX = ["Vor", "Kryo", "Zeph", "Mor", "Lyx", "Quel", "Ras", "Thi", "Nyx", "Obol"]
SPECIES_SUFFIX = ["dax", "mire", "lith", "phar", "gax", "ven", "tide", "korn", "ses", "wraith"]
# Clean, universally-rendered geometric glyphs (the alchemical set tofu-boxed on
# most systems — Telegram, system fonts). Sharp + premium, on the Gemach brand.
SIGILS = ["◆", "◈", "✦", "✧", "❖", "⬡", "⬢", "❂", "✸", "⟡", "◇", "✺"]
TRAITS = ["Vitality", "Cunning", "Aggression", "Discipline", "Fertility"]

BASE_SYMBOL = (
    '<svg viewBox="0 0 111 111" fill="none" xmlns="http://www.w3.org/2000/svg" '
    'style="width:{w};height:{w};display:inline-block;vertical-align:middle">'
    '<path d="M54.921 110.034C85.359 110.034 110.034 85.402 110.034 55.017C110.034 24.6319 '
    "85.359 0 54.921 0C26.0432 0 2.35281 22.1714 0 50.3923H72.8467V59.6416H3.9565e-07C2.35281 "
    '87.8625 26.0432 110.034 54.921 110.034Z" fill="#0052FF"/></svg>'
)


def base_badge() -> str:
    """Official 'Built on Base' attribution — the agent's ERC-8004 identity is on Base."""
    return f'<div class="basebadge">{BASE_SYMBOL.format(w="15px")}<span>BUILT ON BASE</span></div>'


def home() -> Path:
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def genome(name: str, born_at: str) -> dict[str, Any]:
    """Derive a deterministic visual + stat genome from the agent identity."""
    digest = hashlib.sha256(f"{name}|{born_at}".encode()).digest()
    hue1 = digest[0] / 255 * 360
    hue2 = (hue1 + 90 + digest[1] / 255 * 120) % 360
    species = (
        SPECIES_PREFIX[digest[2] % len(SPECIES_PREFIX)]
        + SPECIES_SUFFIX[digest[3] % len(SPECIES_SUFFIX)]
    )
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


ROLE_BIAS = {  # the chosen role nudges one trait axis each generation
    "scout": {"Cunning": 4, "Aggression": 2, "Discipline": -1},
    "analyst": {"Cunning": 3, "Discipline": 3, "Aggression": -2},
    "executor": {"Aggression": 4, "Discipline": 1, "Vitality": -1},
    "leader": {"Vitality": 2, "Discipline": 2, "Cunning": 2, "Aggression": 1, "Fertility": -1},
}


def _byte_stream(seed: bytes):
    counter = 0
    while True:
        yield from hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        counter += 1


def breed(
    parent: dict[str, Any], child_name: str, role: str, parent_goodwill: float
) -> dict[str, Any]:
    """A child genome that INHERITS the parent's and diverges — real heredity, not a
    fresh random hash. Deterministic from (parent fingerprint, child name, role).
    Mutation strength scales with fitness: a higher-goodwill (proven) parent breeds
    more stable offspring; a rare 'hopeful monster' keeps lineages from homogenising.
    """
    s = _byte_stream(
        hashlib.sha256(f"{parent['fingerprint']}|{child_name}|{role}".encode()).digest()
    )
    unit = lambda: next(s) / 255  # noqa: E731
    signed = lambda: unit() * 2 - 1  # noqa: E731
    roll = lambda p: next(s) / 256 < p  # noqa: E731
    fit = max(0.0, min(1.0, (parent_goodwill - 50) / 150))
    m = 1.30 - 0.80 * fit  # 1.30 (fragile) → 0.50 (elite/stable)

    hue1 = (parent["hue1"] + signed() * 18 * m) % 360  # inherited backbone, small drift
    offset = ((parent["hue2"] - parent["hue1"]) % 360 + signed() * 12 * m) % 360
    hue2 = (hue1 + offset) % 360  # inherits the two-tone relationship
    rungs = parent["rungs"]
    if roll(0.55 * m):
        rungs += (1 if roll(0.78) else 2) * (1 if signed() >= 0 else -1)
    rungs = max(14, min(23, rungs))

    stats, inherited, mutated = {}, [], []
    for t in TRAITS:
        base = parent["stats"][t]
        drift = (signed() + signed()) / 2 * 11 * m + ROLE_BIAS.get(role, {}).get(t, 0) * m
        if roll(0.12 * m):
            drift += (1 if signed() >= 0 else -1) * (8 + unit() * 10)
        stats[t] = max(25, min(94, round(base + drift)))
        (mutated if abs(stats[t] - base) >= 4 else inherited).append(t)

    monster = roll(max(0.03, 0.06 * m))
    if monster:
        for _ in range(1 + (1 if roll(0.4) else 0)):
            t = TRAITS[next(s) % len(TRAITS)]
            stats[t] = max(
                25, min(94, round(stats[t] + (1 if roll(0.62) else -1) * (12 + unit() * 23)))
            )
            if t not in mutated:
                mutated.append(t)

    species, sigil = parent["species"], parent["sigil"]
    prefix_i = next((i for i, p in enumerate(SPECIES_PREFIX) if species.startswith(p)), 0)
    suffix_i = next(
        (
            j
            for j, sfx in enumerate(SPECIES_SUFFIX)
            if sfx == species[len(SPECIES_PREFIX[prefix_i]) :]
        ),
        0,
    )
    sigil_i = SIGILS.index(sigil) if sigil in SIGILS else 0
    if roll(0.04 * m) or monster:  # rare speciation → a NEIGHBOURING species (still related)
        if roll(0.5):
            prefix_i = (prefix_i + (1 if signed() >= 0 else -1)) % len(SPECIES_PREFIX)
        else:
            suffix_i = (suffix_i + (1 if signed() >= 0 else -1)) % len(SPECIES_SUFFIX)
        species = SPECIES_PREFIX[prefix_i] + SPECIES_SUFFIX[suffix_i]
    if roll(0.03 * m):
        sigil = SIGILS[(sigil_i + (1 if signed() >= 0 else -1)) % len(SIGILS)]

    hue1, hue2 = round(hue1, 1), round(hue2, 1)
    fp = hashlib.sha256(
        (
            f"{parent['fingerprint']}|{species}|{sigil}|{hue1}|{hue2}|{rungs}|"
            + "|".join(f"{t}:{stats[t]}" for t in TRAITS)
        ).encode()
    ).hexdigest()[:12]
    return {
        "species": species,
        "sigil": sigil,
        "hue1": hue1,
        "hue2": hue2,
        "rungs": rungs,
        "stats": stats,
        "fingerprint": fp,
        "inherited": inherited,
        "mutated": mutated,
        "monster": monster,
        "parent_hue1": parent["hue1"],
        "hue1_delta": round((hue1 - parent["hue1"] + 180) % 360 - 180, 1),
        "hue2_delta": round((hue2 - parent["hue2"] + 180) % 360 - 180, 1),
        "rungs_delta": rungs - parent["rungs"],
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
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" stroke="{color}" stroke-width="3" opacity="0.7"/>'
        )
        parts.append(f'<circle cx="{x1:.1f}" cy="{y:.1f}" r="4" fill="{c1}"/>')
        parts.append(f'<circle cx="{x2:.1f}" cy="{y:.1f}" r="4" fill="{c2}"/>')
    parts.append(
        f'<polyline points="{" ".join(left)}" fill="none" stroke="{c1}" stroke-width="2" opacity="0.5"/>'
    )
    parts.append(
        f'<polyline points="{" ".join(right)}" fill="none" stroke="{c2}" stroke-width="2" opacity="0.5"/>'
    )
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
        subprocess.run(
            ["node", str(SCRIPT_DIR / "stats.js"), "pin-image"],
            capture_output=True,
            text=True,
            timeout=40,
        )
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


def gene_diff_html(cg: dict[str, Any]) -> str:
    """Glanceable gene-diff chips: what the child inherited vs mutated from the parent."""
    chips = [
        f'<span class="gchip"><span class="gdot" style="background:hsl({cg.get("parent_hue1", cg["hue1"])},72%,60%)">'
        f"</span>backbone inherited</span>"
    ]
    if abs(cg.get("hue2_delta", 0)) >= 1:
        chips.append(
            f'<span class="gchip mut"><span class="gdia" style="border-color:hsl({cg["hue2"]},72%,60%)">'
            f"</span>accent {cg['hue2_delta']:+.0f}°</span>"
        )
    if cg.get("rungs_delta"):
        chips.append(f'<span class="gchip mut">rungs {cg["rungs_delta"]:+d}</span>')
    if cg.get("mutated"):
        chips.append(
            f'<span class="gchip mut">{len(cg["mutated"])} trait{"s" if len(cg["mutated"]) != 1 else ""} mutated</span>'
        )
    if cg.get("monster"):
        chips.append('<span class="gchip mon">⚡ hopeful monster</span>')
    return '<div class="gdiff">' + "".join(chips) + "</div>"


def family_html(state: dict[str, Any]) -> str:
    """The lineage — each child shows its OWN bred DNA helix (inherits the parent's
    backbone hue, diverges in accent/traits) + a gene-diff of what it kept vs changed."""
    children = state.get("children", [])
    if not children:
        return '<p class="muted">No offspring yet — at 50 goodwill the creature can split and pass on its DNA.</p>'
    cells = []
    for c in children:
        cg = c.get("genome")
        helix = f'<div class="lhelix">{helix_svg(cg)}</div>' if cg else ""
        meta = (
            f'<div class="species">{html.escape(cg["species"])} {cg["sigil"]}</div>' if cg else ""
        )
        diff = gene_diff_html(cg) if cg else ""
        cells.append(
            f'<div class="lcell">{helix}<div class="lmeta">'
            f'<b>{html.escape(c["name"])}</b> <span class="pill">{html.escape(c.get("role", "—"))}</span>'
            f'{meta}{diff}<div class="muted">{html.escape(c.get("mutation", ""))[:70]}</div></div></div>'
        )
    return f'<div class="lineage">{"".join(cells)}</div>'


def events_html(journal: list[dict[str, Any]]) -> str:
    icon = {
        "born": "🥚",
        "tick": "🫀",
        "settle": "💱",
        "charge": "🔥",
        "replicate": "🧬",
        "recode": "🛠️",
    }
    rows = []
    for e in reversed(journal[-12:]):
        ev = e.get("event", "?")
        detail = e.get("note") or e.get("mutation") or e.get("summary") or e.get("reason") or ""
        extra = (
            f" pnl {e['pnl']:+g}"
            if "pnl" in e
            else (f" bal {e['balance']:g}" if "balance" in e else "")
        )
        rows.append(
            f"<li>{icon.get(ev, '•')} <b>{ev}</b>{html.escape(extra)} "
            f'<span class="muted">{html.escape(str(detail))[:60]}</span></li>'
        )
    return (
        f'<ul class="events">{"".join(rows)}</ul>'
        if rows
        else '<p class="muted">No life events yet.</p>'
    )


def telepathy_html(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return '<p class="muted">No telepathy traffic — the family is quiet.</p>'
    rows = []
    for m in messages[-8:]:
        rows.append(
            f'<li><span class="pill">{html.escape(m.get("type", ""))}</span> '
            f"<b>{html.escape(m.get('from', '?'))}</b>→{html.escape(str(m.get('to', '')))}: "
            f"{html.escape(str(m.get('msg', '')))[:70]}</li>"
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
        gas_line = (
            f'<div class="muted" style="margin-top:8px">{dot} beacon gas: '
            f"{gas.get('baseEth', 0):.5f} Base ETH · ~{gas.get('beaconRunway', 0)} beacons</div>"
        )
    return (
        f'<div class="idrow"><span class="pill">ERC-8004</span> agent <b>#{aid}</b> '
        f"on {ident.get('chain', 'base:8453')}</div>"
        f'<div class="muted" style="margin-top:8px">registry {reg}…</div>{gas_line}'
        f'<a class="link" href="{url}" target="_blank" rel="noopener">view on basescan ↗</a>'
        f"<div>{base_badge()}</div>"
    )


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
        proc = subprocess.run(
            ["node", str(SCRIPT_DIR / "hl_perp.js"), "status"],
            capture_output=True,
            text=True,
            timeout=80,
        )
        data = json.loads(proc.stdout.strip().splitlines()[-1])
        if data.get("ok"):
            data["ts"] = datetime.now(UTC).isoformat(timespec="seconds")
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
        pnl = f"{'+' if up >= 0 else '−'}${abs(up):,.2f}"
        liq = float(p.get("liquidationPx") or 0)
        coin = html.escape(str(p.get("coin", "?")))
        rows.append(
            f'<li><span class="pill">{side}</span><b>{coin}</b> '
            f"{abs(size):g} @ ${float(p.get('entryPx', 0) or 0):,.2f} "
            f'<span class="pos-pnl" data-coin="{coin}" style="color:{color};font-weight:700">{pnl}</span> '
            f'<span class="muted">liq ${liq:,.0f}</span></li>'
        )
    # ids let the live sync update each row + the header from HL's API (the snapshot
    # they render from is only refreshed hourly), so the panel matches the live vitals.
    head = (
        f'<div class="muted" style="margin-bottom:8px">equity '
        f'<b id="posEquity" style="color:var(--ink)">${equity:.2f}</b> · {len(pos)} open · '
        f'<span id="posAsOf">as of {asof} UTC</span></div>'
    )
    return head + f'<ul class="events">{"".join(rows)}</ul>'


def techniques_html() -> str:
    """The arsenal — the born offensive loadout, ranked by live weight. Each technique's
    weight is its genome-given start, adapted by what it actually earns (the fitness loop)."""
    h = home()
    style = load_json(h / "forge" / "style.json", {})
    adopted = style.get("adopted", [])
    if not adopted:
        return '<p class="muted">No techniques yet — the arsenal is installed at birth.</p>'
    cap = float(style.get("conviction_cap", 0.85) or 0.85)
    risk = float(style.get("risk_mult", 1.0) or 1.0)
    role = style.get("role", "")
    head = (
        f'<div class="loadhead">{len(adopted)} techniques · conviction cap '
        f"<b>{cap:.2f}</b> · risk <b>×{risk:.2f}</b>"
        + (f" · <b>{role}</b>" if role else "")
        + "</div>"
    )
    rows = []
    for e in sorted(adopted, key=lambda x: -float(x.get("weight", 1.0) or 1.0)):
        tid = e.get("id") if isinstance(e, dict) else e
        tech = load_json(h / "forge" / "techniques" / tid / "technique.json", {})
        w = float(e.get("weight", 1.0) or 1.0)
        trades = int(e.get("trades", 0) or 0)
        edge = float(e.get("e", 0.0) or 0.0)
        tag = (
            '<span class="pill born">born</span>'
            if e.get("born")
            else '<span class="pill">authored</span>'
        )
        if trades:
            fcls = "up" if edge > 0 else "down" if edge < 0 else "muted"
            fit = f'<span class="{fcls}">{edge:+.2f} edge</span> <span class="muted">· {trades} trades</span>'
        else:
            fit = '<span class="muted">no live trades yet</span>'
        bar_cls = "wbar" + (" lo" if w < 0.4 else "")
        rows.append(
            f'<li class="load"><div class="loadtop">{tag}<b>{tid}</b>'
            f'<span class="wpct">{w:.2f}</span></div>'
            f'<div class="{bar_cls}"><i style="width:{min(100, w * 100):.0f}%"></i></div>'
            f'<div class="loadsub muted">{tech.get("claim", "")} · {fit}</div></li>'
        )
    return head + f'<ul class="loadout">{"".join(rows)}</ul>'


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
            subprocess.run(
                [
                    "uv",
                    "run",
                    "--no-project",
                    "--with",
                    "qrcode",
                    "python3",
                    str(SCRIPT_DIR / "qr.py"),
                    addr,
                    chain,
                    str(out),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            pass


def _svg_inline(p: Path) -> str:
    try:
        s = p.read_text(encoding="utf-8")
        return s[s.index("<svg") :]  # drop the xml declaration for inline embedding
    except (OSError, ValueError):
        return ""


def topup_html(h: Path) -> str:
    """One prominent QR for the primary action (fund trading); gas is one-time and
    optional, so it's a compact secondary line, not a second big code."""
    pos = load_json(h / "positions.json", {})
    gas = load_json(h / "gas.json", {})
    managed = pos.get("managed")
    if not managed:
        return '<p class="muted">Wallet addresses unavailable.</p>'
    primary = (
        f'<div class="qrcard"><div class="qr">{_svg_inline(h / "qr" / "topup.svg")}</div>'
        f'<div><div class="qlabel">Fund trading · Arbitrum</div>'
        f'<div class="addr">{managed}</div>'
        f'<div class="muted">Scan &amp; send ETH — it auto-swaps to USDC and trades. '
        f"No bridging, no manual steps.</div></div></div>"
    )
    ctrl = gas.get("control")
    secondary = (
        (
            f'<div class="gasline"><b>Gas (optional)</b> · send ~0.001 ETH on '
            f'<b>Base</b> to <span class="addr" style="display:inline;max-width:none">{ctrl}</span> '
            f"for onchain identity beacons.</div>"
        )
        if ctrl
        else ""
    )
    return primary + secondary


def refresh_roster(h: Path) -> None:
    """Best-effort: cache the onchain family roster (peers.js) for the page."""
    try:
        proc = subprocess.run(
            ["node", str(SCRIPT_DIR / "peers.js")], capture_output=True, text=True, timeout=60
        )
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
        avatar = " 🖼" if a.get("image") else ""
        scan = f"https://basescan.org/nft/{data.get('registry', '')}/{a['id']}"
        rows.append(
            f'<li><a href="{scan}" target="_blank">#{a["id"]}</a> '
            f"<b>{a.get('name') or '?'}</b>{avatar}{you} "
            f'<span class="muted">{(a.get("owner") or "?")[:10]}…</span></li>'
        )
    return f'<ul class="family">{"".join(rows)}</ul>'


def refresh_leaderboard(h: Path) -> None:
    """Best-effort: pull peer stats and recompute the family leaderboard."""
    try:
        subprocess.run(
            ["node", str(SCRIPT_DIR / "stats.js"), "fetch"],
            capture_output=True,
            text=True,
            timeout=40,
        )
        proc = subprocess.run(
            ["node", str(SCRIPT_DIR / "stats.js"), "leaderboard"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        data = json.loads(proc.stdout.strip())
        if data.get("ok"):
            (h / "leaderboard.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass


def leaderboard_html(h: Path) -> str:
    data = load_json(h / "leaderboard.json", {})
    ranked = data.get("ranked", [])
    pending = data.get("pending", [])
    link = (
        '<a class="link lb-full" href="leaderboard.html">See the full leaderboard — '
        "every creature, live from Base ↗</a>"
    )
    if not ranked and not pending:
        # No local standings yet is exactly when the full onchain board is most useful.
        return '<p class="muted">No published stats yet — agents publish each heartbeat.</p>' + link
    rows = []
    for e in ranked:
        you = ' <span class="tag">you</span>' if e.get("self") else ""
        rows.append(
            f"<tr><td>{e.get('rank')}</td><td><b>{e.get('name') or '?'}</b>{you}</td>"
            f"<td>{e.get('goodwill', 0)}</td><td>{e.get('gmac', 0)}</td>"
            f"<td>${e.get('equityUsd', 0)}</td></tr>"
        )
    for e in pending:
        you = ' <span class="tag">you</span>' if e.get("self") else ""
        rows.append(
            f"<tr><td>·</td><td>{e.get('name') or '?'}{you}</td>"
            f'<td colspan="3" class="muted">awaiting published stats</td></tr>'
        )
    return (
        '<table class="lb"><tr><th>#</th><th>agent</th><th>goodwill</th>'
        f"<th>GMAC</th><th>equity</th></tr>{''.join(rows)}</table>{link}"
    )


def deploy_leaderboard(h: Path) -> None:
    """Co-locate the decentralized leaderboard next to the dashboard so the main page
    links to it with a relative href that resolves wherever it's served (http, file://,
    or a pinned IPFS directory). The board itself reads all creatures from Base."""
    src = SCRIPT_DIR.parent / "leaderboard" / "leaderboard.html"
    try:
        if src.exists():
            (h / "leaderboard.html").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        pass


GOODWILL_REWARDS = [
    (0, "🐣", "Born", "Trading live — every position stop-protected", "3×"),
    (
        50,
        "🧬",
        "Reproduce",
        "Spawn a child that inherits your genome + your winning techniques",
        "5×",
    ),
    (100, "🛠️", "Self-recode", "Rewrite your own DNA to evolve how you trade", None),
    (200, "🐝", "Swarm", "Lead a whole family of agents that trade as one", "10×"),
    (500, "⚡", "Sharper edge", "Press harder on your proven setups", "15×"),
    (1000, "👑", "Apex", "Maximum leverage — the top of the ladder", "20×"),
]


def rewards_html(state: dict[str, Any]) -> str:
    """The goodwill → power-up ladder — the loop. Goodwill is earned ONLY from real
    profitable trades, and each tier unlocks a concrete new ability (reproduce, recode,
    swarm) plus more leverage, so there's always a next reward to climb toward: the page
    leads with how close the NEXT unlock is, then shows the whole path beyond it."""
    gw = float(state.get("goodwill", 0) or 0)
    tiers = GOODWILL_REWARDS
    nxt = next((i for i, t in enumerate(tiers) if gw < t[0]), None)
    if nxt is not None:
        th, ic, name, desc, lev = tiers[nxt]
        prev = tiers[nxt - 1][0] if nxt > 0 else 0
        pct = max(0.0, min(100.0, (gw - prev) / (th - prev) * 100)) if th > prev else 0.0
        levline = f" · unlocks {lev} leverage" if lev else ""
        hero = (
            '<div class="nextcard">'
            f'<div class="nextlabel">NEXT POWER-UP · {int(th - gw)} goodwill to go</div>'
            f'<div class="nextname">{ic} {html.escape(name)}</div>'
            f'<div class="nextdesc muted">{html.escape(desc)}{levline}</div>'
            f'<div class="nbar"><i style="width:{pct:.0f}%"></i></div>'
            f'<div class="nfoot"><b>{int(gw)}</b><span class="muted">{th} goodwill</span></div>'
            "</div>"
        )
    else:
        hero = (
            '<div class="nextcard maxed"><div class="nextname">👑 Apex reached</div>'
            '<div class="nextdesc muted">Every power-up unlocked.</div></div>'
        )
    rows = []
    for i, (th, ic, name, desc, lev) in enumerate(tiers):
        done = gw >= th
        cls = "rstep " + ("done" if done else ("next" if i == nxt else "locked"))
        node = "✓" if done else ("◆" if i == nxt else "○")
        levtag = f'<span class="rlev">{lev}</span>' if lev else '<span class="rlev none">—</span>'
        rows.append(
            f'<div class="{cls}"><span class="rnode">{node}</span>'
            f'<div class="rbody"><div class="rtop"><b>{ic} {html.escape(name)}</b>'
            f'<span class="rgw">{th} GW</span></div>'
            f'<div class="rdesc muted">{html.escape(desc)}</div></div>{levtag}</div>'
        )
    return hero + '<div class="ladder">' + "".join(rows) + "</div>"


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
    items += [
        ("🌱", "Above seed", gmac > seed),
        ("🧬", "First child", kids > 0),
        ("🔥", f"{streak}-win streak" if streak >= 3 else "Win streak", streak >= 3),
    ]
    earned = [(e, lbl) for e, lbl, u in items if u]
    total = len(items)
    # Celebrate what's won (bright) + the single next target as a progress bar —
    # not a wall of greyed-out locks.
    if earned:
        badges = "".join(
            f'<span class="badge on">{e} {html.escape(lbl)}</span>' for e, lbl in earned
        )
    else:
        badges = '<p class="muted">No badges yet — the first ones come fast.</p>'
    header = f'<div class="achhdr"><b>{len(earned)}</b> <span class="muted">of {total} unlocked</span></div>'
    nxt = next((t for t in (10, 25, 50, 100, 200, 500, 1000) if gw < t), None)
    progress = ""
    if nxt:
        prev = max([t for t in (0, 10, 25, 50, 100, 200, 500) if t <= gw], default=0)
        pct = (gw - prev) / (nxt - prev) * 100 if nxt > prev else 0
        unlock = {
            50: " · unlocks Replicate",
            100: " · unlocks Recode",
            1000: " · unlocks Max leverage",
        }.get(nxt, "")
        progress = (
            f'<div class="nextup"><div class="nblabel">Next → ⭐ goodwill '
            f"<b>{int(gw)}</b>/{nxt}{unlock}</div>"
            f'<div class="gbar"><div class="gfill" style="width:{pct:.0f}%;background:var(--emerald)"></div></div></div>'
        )
    return f'{header}<div class="badges">{badges}</div>{progress}'


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
        for by, e in agg.items()
        if e["total"] > 0
    ]
    return sorted(board, key=lambda e: (-e["acc"], -e["correct"]))


def intel_html(h: Path) -> str:
    """Market intelligence panel — the regime + key features the agent now trades on."""
    intel = load_json(h / "intel.json", {}).get("intel", {})
    if not intel:
        return '<p class="muted">No market scan yet — the intel engine runs each heartbeat.</p>'
    # Filled regime chips — colour the whole pill so the read is instant: emerald up,
    # red down, blue range (tradeable), muted chop (sit out).
    chip = {
        "trend_up": ("#9affc4", "rgba(73,184,117,.16)"),
        "trend_down": ("#ff9aa6", "rgba(223,46,46,.16)"),
        "range": ("#a9d6ff", "rgba(97,184,255,.14)"),
        "chop": ("var(--muted)", "rgba(105,112,131,.14)"),
    }
    rows = []
    for coin, f in intel.items():
        if not f:
            continue
        reg = f.get("regime", "?")
        fg, bg = chip.get(reg, ("var(--silver)", "transparent"))
        rows.append(
            f"<tr><td><b>{html.escape(coin)}</b></td>"
            f'<td><span style="background:{bg};color:{fg};padding:2px 9px;border-radius:999px;'
            f'font-size:11px;font-weight:600">{reg}</span></td>'
            f"<td>{f.get('rsi', '?')}</td><td>{f.get('atr_pct', '?')}%</td>"
            f"<td>{f.get('funding_z', '?')}</td><td>{'✓' if f.get('tradeable') else '—'}</td></tr>"
        )
    return (
        f'<table class="lb"><tr><th>coin</th><th>regime</th><th>rsi</th><th>atr</th>'
        f"<th>fund-z</th><th>trade?</th></tr>{''.join(rows)}</table>"
        f'<p class="muted" style="margin-top:6px">Chop = sit out · trend = ride ema_stack · '
        f"range = fade extremes. Sized by ATR + Kelly, only on regime-proven edge.</p>"
    )


def predictions_html(h: Path) -> str:
    """The free 'Call it' game — the open round + the GLOBAL predictors ladder."""
    rounds = load_json(h / "predictions" / "rounds.json", {})
    parts = []
    open_r = [r for r in rounds.values() if r.get("status") == "open"]
    if open_r:
        for r in open_r:
            parts.append(
                f'<div class="callit">🎯 <b>Call it:</b> {html.escape(str(r["coin"]))} '
                f"{r['side']} @ ${r['entry']:g} — <b>TP</b> or <b>SL</b>? "
                f'<span class="muted">round {r["id"]}</span></div>'
            )
    else:
        parts.append(
            '<p class="muted">No open round — one opens when the creature opens a trade.</p>'
        )
    board = global_predictors(h)
    if board:
        rows = "".join(
            f"<tr><td>{i + 1}</td><td>{html.escape(e['by'])}</td><td>{e['acc']}%</td>"
            f"<td>{e['correct']}/{e['total']}</td><td>{e['creatures']}</td></tr>"
            for i, e in enumerate(board[:10])
        )
        parts.append(
            f'<table class="lb" style="margin-top:10px"><tr><th>#</th><th>predictor</th>'
            f"<th>acc</th><th>record</th><th>souls</th></tr>{rows}</table>"
            f'<p class="muted" style="margin-top:6px">🌐 Global — every predictor across every creature, '
            f"aggregated from onchain cards.</p>"
        )
    else:
        parts.append(
            '<p class="muted" style="margin-top:8px">No predictors yet — be the first to call it. '
            "Free, no stakes; calls are anchored onchain so nobody can cheat.</p>"
        )
    return "".join(parts)


def sparkline_svg(values: list[float], w: int = 150, hgt: int = 40) -> str:
    """A Stocks-style sparkline of the cumulative realized-PnL path, with a zero
    baseline — colour emerald if it ends green, red if not."""
    if len(values) < 2:
        return ""
    pad = 4
    lo, hi = min(values), max(values)
    rng = (hi - lo) or 1
    n = len(values)

    def xy(i: float, v: float) -> str:
        x = pad + (i / (n - 1)) * (w - 2 * pad)
        y = (hgt - pad) - ((v - lo) / rng) * (hgt - 2 * pad)
        return f"{x:.1f},{y:.1f}"

    pts = " ".join(xy(i, v) for i, v in enumerate(values))
    color = "var(--emerald)" if values[-1] >= 0 else "var(--red)"
    zy = (hgt - pad) - ((0 - lo) / rng) * (hgt - 2 * pad)
    return (
        f'<svg viewBox="0 0 {w} {hgt}" width="{w}" height="{hgt}" preserveAspectRatio="none">'
        f'<line x1="{pad}" y1="{zy:.1f}" x2="{w - pad}" y2="{zy:.1f}" stroke="#2E4164" stroke-width="1" stroke-dasharray="2 3"/>'
        f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{w - pad}" cy="{xy(n - 1, values[-1]).split(",")[1]}" r="2.5" fill="{color}"/></svg>'
    )


def performance_html(journal: list) -> str:
    """The track-record trend — cumulative realized PnL over the agent's life, with
    the honest win record. Answers 'is it actually trending up?' at a glance."""
    settles = [e for e in journal if e.get("event") == "settle"]
    if len(settles) < 2:
        return (
            '<div class="trend"><div class="slabel">// track record</div>'
            '<div class="muted" style="margin-top:6px">building history…</div></div>'
        )
    cum, curve = 0.0, [0.0]
    for e in settles:
        cum += float(e.get("pnl", 0) or 0)
        curve.append(cum)
    wins = sum(1 for e in settles if float(e.get("pnl", 0) or 0) > 0)
    total = len(settles)
    wr = round(wins / total * 100) if total else 0
    cls = "up" if cum >= 0 else "down"
    net = f"{'+' if cum >= 0 else '−'}${abs(cum):,.2f}"
    return (
        f'<div class="trend"><div class="slabel">// realized p&l</div>'
        f"{sparkline_svg(curve, 260, 38)}"
        f'<div class="trendcap"><b class="{cls}">{net}</b> · {wins}/{total} wins ({wr}%)</div></div>'
    )


def _live_positions(h: Path) -> tuple[bool, float, float]:
    """(has an open position, total unrealized PnL, account equity) from the snapshot."""
    snap = load_json(h / "positions.json", {})
    positions = snap.get("positions") or []
    pnl = sum(float(p.get("unrealizedPnl", 0) or 0) for p in positions)
    return len(positions) > 0, pnl, float(snap.get("equity", 0) or 0)


def vitals_html(state: dict[str, Any], h: Path) -> str:
    """The at-a-glance vitals — the numbers a human actually opens this to see:
    equity, live P&L (colour-coded), open risk, and the progression metrics."""
    snap = load_json(h / "positions.json", {})
    equity = float(snap.get("equity", 0) or 0)
    upnl = sum(float(p.get("unrealizedPnl", 0) or 0) for p in (snap.get("positions") or []))
    npos = len(snap.get("positions") or [])
    pnl_cls = "up" if upnl >= 0 else "down"
    pnl_str = f"{'+' if upnl >= 0 else '−'}${abs(upnl):,.2f}"
    asof = (snap.get("ts") or "")[11:19]

    def stat(label: str, val: str, cls: str = "", sid: str = "") -> str:
        sid_attr = f' id="{sid}"' if sid else ""
        return f'<div class="stat"><div class="slabel">{label}</div><div class="sval {cls}"{sid_attr}>{val}</div></div>'

    # Equity + Unrealized carry ids so the page updates them live from HyperLiquid's
    # public API (the snapshot they render from is only refreshed hourly on heartbeat).
    return (
        stat("Equity", f"${equity:,.2f}", "lead", "liveEquity")
        + stat("Unrealized", pnl_str, pnl_cls, "liveUpnl")
        + stat("Open", str(npos), "", "liveOpen")
        + stat("Goodwill", str(int(state.get("goodwill", 0) or 0)), "em")
        + stat("Heartbeats", str(int(state.get("heartbeats", 0) or 0)))
        + stat("P&amp;L feed", f"snapshot {asof}", "feed", "liveAsOf")
    )


def live_sync_script(h: Path) -> str:
    """Client-side live PnL: the rendered page reads an hourly snapshot, so refreshing
    the browser shows stale numbers. This pulls live mark prices + spot balance from
    HyperLiquid's public API every 20s and recomputes equity + unrealized in-page —
    majors update live; builder-dex (xyz:*) positions fall back to the snapshot mark.
    Degrades silently to the snapshot if the API is unreachable (offline / CORS)."""
    snap = load_json(h / "positions.json", {})
    addr = snap.get("managed") or ""
    positions = [
        {
            "coin": p.get("coin"),
            "szi": float(p.get("size", 0) or 0),
            "entry": float(p.get("entryPx", 0) or 0),
            "upnl": float(p.get("unrealizedPnl", 0) or 0),
        }
        for p in (snap.get("positions") or [])
    ]
    spot_base = round(
        max(0.0, float(snap.get("spotUsdc", 0) or 0) - float(snap.get("spotHold", 0) or 0)), 4
    )  # free spot, live-fetch fallback
    if not addr:
        return ""  # no managed address embedded → leave the snapshot as-is
    data = json.dumps({"addr": addr, "spotBase": spot_base, "positions": positions})
    return (
        "<script>(function(){\n"
        f"var D={data},API='https://api.hyperliquid.xyz/info';\n"
        "function post(b){return fetch(API,{method:'POST',headers:{'content-type':'application/json'},"
        "body:JSON.stringify(b)}).then(function(r){return r.json();});}\n"
        "function fmt(v){return Math.abs(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});}\n"
        "function set(id,h){var e=document.getElementById(id);if(e)e.innerHTML=h;}\n"
        "function sync(){Promise.all([post({type:'clearinghouseState',user:D.addr}),"
        "post({type:'spotClearinghouseState',user:D.addr})])"
        ".then(function(r){var perp=r[0]||{},spot=r[1]||{},live={};"
        "(perp.assetPositions||[]).forEach(function(a){var p=a.position||{};live[p.coin]=Number(p.unrealizedPnl||0);});"
        "var u=(spot.balances||[]).filter(function(b){return b.coin==='USDC';})[0];"
        "var freeSpot=u?Math.max(0,Number(u.total)-Number(u.hold||0)):D.spotBase;var upnl=0;"
        "D.positions.forEach(function(p){upnl+=(p.coin in live)?live[p.coin]:p.upnl;});"
        # equity = free spot + perp accountValue (margin is double-counted otherwise)
        "var acct=Number((perp.marginSummary||{}).accountValue||0);"
        "var eq=freeSpot+acct;set('liveEquity','$'+fmt(eq));"
        "var el=document.getElementById('liveUpnl');if(el){el.innerHTML=(upnl>=0?'+':'\\u2212')+'$'+fmt(upnl);"
        "el.className='sval '+(upnl>=0?'up':'down');}"
        "var now='live \\u00b7 '+new Date().toUTCString().slice(17,25)+' UTC';set('liveAsOf',now);"
        "document.querySelectorAll('.pos-pnl').forEach(function(el){var c=el.getAttribute('data-coin');"
        "if(c in live){var v=live[c];el.textContent=(v>=0?'+':'\\u2212')+'$'+fmt(v);"
        "el.style.color=v>=0?'var(--emerald)':'var(--red)';}});"
        "set('posEquity','$'+fmt(eq));set('posAsOf',now);})"
        ".catch(function(){});}\n"
        "sync();setInterval(sync,20000);})();</script>"
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
    gauges = "".join(
        [
            gauge("GMAC life energy", gmac, max(seed, gmac), mode_hue),
            gauge("Goodwill", state.get("goodwill", 0), 200, 280),
            gauge(
                "Heartbeats", state.get("heartbeats", 0), max(50, state.get("heartbeats", 0)), 190
            ),
        ]
    )
    live = _live_positions(home())  # (active, unrealized_pnl, equity) — for the DNA pulse + share
    persona = load_json(home() / "dna" / "persona.json", {})  # archetype + catchphrase for the card
    gh_qr = github_qr_datauri(home())  # cached PNG QR of the repo, for the card + dashboard
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
        performance=performance_html(journal),
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
        rewards=rewards_html(state),
        intel=intel_html(home()),
        predictions=predictions_html(home()),
        topup=topup_html(home()),
        recodes=state.get("recodes", 0),
        children=len(state.get("children", [])),
        generated=datetime.now(UTC).isoformat(timespec="seconds"),
        script=TABS_JS + live_sync_script(home()),
        dna_script=dna_script(g, live, state, journal, persona, gh_qr),
        share=share_url(state, name, live[2]),
        github_qr=gh_qr,
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
            subprocess.run(
                ["node", str(SCRIPT_DIR / step[0]), *step[1:]],
                capture_output=True,
                text=True,
                timeout=80,
            )
        try:
            gp = subprocess.run(
                ["node", str(SCRIPT_DIR / "gas.js"), "check"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            (h / "gas.json").write_text(gp.stdout.strip(), encoding="utf-8")
        except (OSError, subprocess.SubprocessError):
            pass
        refresh_roster(h)
        refresh_qr(h)
        refresh_leaderboard(h)
    deploy_leaderboard(h)  # co-locate the leaderboard so the header link resolves
    journal = read_jsonl(h / "journal.jsonl")
    messages = read_jsonl(h / "telepathy" / "bus.jsonl")
    identity = (
        (h / "dna" / "IDENTITY.md").read_text(encoding="utf-8")
        if (h / "dna" / "IDENTITY.md").exists()
        else ""
    )
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
    "-336 -2 -1 -2 -1 195 -965 194 -965 -2 -22 -3 -21 -1984 -2394 -1984 -2393 1252 -3 1251 -2 0 -13 -1 -12 "
    "-1254 -5015 -1254 -5015 3 -2 3 -3 1598 365 1599 365 7 -7 8 -8 1622 -3625 1622 -3625 6 -7 7 -8 1139 545 "
    "1140 546 20 5 20 5 1780 -1922 1780 -1921 21 -26 21 -25 1793 1944 1793 1944 21 -1 21 -1 1173 -547 1174 "
    "-548 2 4 2 3 1604 3635 1603 3635 3 3 3 4 1607 -366 1608 -366 4 5 4 4 -1246 5009 -1246 5008 0 17 0 17 "
    "1243 2 1243 3 -1959 2380 -1958 2380 -16 22 -15 22 197 977 196 976 -3 3 -3 2 -2626 336 -2625 337 -1799 "
    "975 -1798 975 -1 -1 -1 0 -1803 -975z m6963 -7889 l1570 -1915 3 -9 3 -9 -1487 -2129 -1486 -2128 -43 -61 "
    "-44 -61 251 -459 251 -459 0 -10 0 -10 -798 -1360 -798 -1360 -12 -14 -13 -13 -1283 406 -1283 406 -1284 "
    "-406 -1284 -406 -8 8 -8 9 -792 1348 -791 1348 -11 24 -11 24 252 462 251 462 -9 11 -8 11 -1518 2174 -1518 "
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


TABS_JS = """<script>
(function(){
  var saved = localStorage.getItem('gclaw_tab') || 'overview';
  function show(t){
    var p=document.querySelectorAll('.pane'), b=document.querySelectorAll('.tab'), i, has=false;
    for(i=0;i<p.length;i++){ if(p[i].id===t) has=true; }
    if(!has) t='overview';
    for(i=0;i<p.length;i++) p[i].classList.toggle('active', p[i].id===t);
    for(i=0;i<b.length;i++) b[i].classList.toggle('active', b[i].getAttribute('data-tab')===t);
    try{ localStorage.setItem('gclaw_tab', t); }catch(e){}
  }
  var btns=document.querySelectorAll('.tab');
  for(var i=0;i<btns.length;i++) btns[i].addEventListener('click', function(){ show(this.getAttribute('data-tab')); });
  show(saved);
})();
</script>"""

# A living 3D double helix (Three.js, WebGL). Genome-driven (colours + rung count),
# brand-lit (emerald + blue point lights on rich black), slow rotation with an
# organic wobble. Pauses when the Genome tab is hidden; if the CDN can't load the
# library, the inline SVG fallback inside #dna3d simply stays.
DNA3D_INIT = r"""<script>
(function(){
  if(!window.THREE){return;}
  var host=document.getElementById('dna3d'); if(!host) return;
  var W=host.clientWidth||230, H=300;
  host.textContent='';
  var d=window.GCLAW_DNA||{hue1:150,hue2:210,rungs:16,active:false,pnl:0};
  var scene=new THREE.Scene();
  var cam=new THREE.PerspectiveCamera(36,W/H,0.1,100); cam.position.set(0,0,15.5);
  var rnd=new THREE.WebGLRenderer({alpha:true,antialias:true,preserveDrawingBuffer:true});
  rnd.setSize(W,H); rnd.setPixelRatio(Math.min(window.devicePixelRatio||1,2)); host.appendChild(rnd.domElement);
  function col(h){return new THREE.Color('hsl('+Math.round(h)+',72%,60%)');}
  // soft radial-gradient sprite → additive "bloom" glow without a postprocess pass
  function glowTex(){var c=document.createElement('canvas');c.width=c.height=64;var x=c.getContext('2d');var gr=x.createRadialGradient(32,32,0,32,32,32);gr.addColorStop(0,'rgba(255,255,255,1)');gr.addColorStop(0.3,'rgba(255,255,255,0.55)');gr.addColorStop(1,'rgba(255,255,255,0)');x.fillStyle=gr;x.fillRect(0,0,64,64);var t=new THREE.Texture(c);t.needsUpdate=true;return t;}
  var GT=glowTex(), glows=[];
  function node(x,y,z,c){var m=new THREE.Mesh(new THREE.SphereGeometry(0.30,18,18),new THREE.MeshStandardMaterial({color:c,emissive:c,emissiveIntensity:0.6,roughness:0.3,metalness:0.1}));m.position.set(x,y,z);return m;}
  function glow(x,y,z,c){var s=new THREE.Sprite(new THREE.SpriteMaterial({map:GT,color:c,blending:THREE.AdditiveBlending,transparent:true,opacity:0.5,depthWrite:false}));s.position.set(x,y,z);s.scale.set(1.6,1.6,1.6);glows.push(s);return s;}
  function rung(a,b,c){var len=a.distanceTo(b);var m=new THREE.Mesh(new THREE.CylinderGeometry(0.055,0.055,len,8),new THREE.MeshStandardMaterial({color:c,emissive:c,emissiveIntensity:0.45,roughness:0.45,transparent:true,opacity:0.85}));m.position.copy(a.clone().add(b).multiplyScalar(0.5));m.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),b.clone().sub(a).normalize());return m;}
  var g=new THREE.Group(), c1=col(d.hue1), c2=col(d.hue2);
  var N=Math.max(10,Math.min(30,d.rungs||16)), turns=2.7, R=2.2, span=8.0;
  for(var i=0;i<N;i++){
    var t=i/(N-1), ang=t*turns*Math.PI*2, y=(t-0.5)*span;
    var a=new THREE.Vector3(Math.cos(ang)*R,y,Math.sin(ang)*R);
    var b=new THREE.Vector3(Math.cos(ang+Math.PI)*R,y,Math.sin(ang+Math.PI)*R);
    g.add(node(a.x,a.y,a.z,c1)); g.add(node(b.x,b.y,b.z,c2)); g.add(rung(a,b,i%2?c1:c2));
    g.add(glow(a.x,a.y,a.z,c1)); g.add(glow(b.x,b.y,b.z,c2));
  }
  scene.add(g);
  scene.add(new THREE.AmbientLight(0xffffff,0.5));
  var l1=new THREE.PointLight(0x9affc4,0.9); l1.position.set(6,5,10); scene.add(l1);
  var l2=new THREE.PointLight(0x61b8ff,0.6); l2.position.set(-6,-4,7); scene.add(l2);
  // while a trade is live, a pulsing light tinted by P&L: emerald = up, red = down
  var pulseLight=null;
  if(d.active){pulseLight=new THREE.PointLight(d.pnl<0?0xff5a6a:0x49ff9a,0); pulseLight.position.set(0,0,8); scene.add(pulseLight);}
  window.addEventListener('resize',function(){var w=host.clientWidth||W; rnd.setSize(w,H); cam.aspect=w/H; cam.updateProjectionMatrix();});
  (function loop(){
    requestAnimationFrame(loop);
    if(host.offsetParent===null) return;
    var now=Date.now();
    g.rotation.y += d.active?0.024:0.011;            // pulse faster when actively trading
    g.rotation.x = Math.sin(now/2600)*0.13;
    var pulse = 0.5 + 0.5*Math.sin(now/(d.active?420:950));
    var sc = 1.45 + pulse*(d.active?0.85:0.35);
    for(var k=0;k<glows.length;k++){ glows[k].scale.set(sc,sc,sc); glows[k].material.opacity = 0.32 + pulse*(d.active?0.55:0.28); }
    if(pulseLight) pulseLight.intensity = 0.4 + pulse*1.2;
    rnd.render(scene,cam);
  })();
})();
</script>"""


# Compose a branded, shareable DNA card client-side (no OG server — stays
# decentralized): the live helix snapshot + name + equity + verified badge on the
# Gemach canvas, downloaded as a PNG to attach to a tweet.
CARD_JS = r"""<script>
window.GCLAW_QRIMG=null;
if(window.GCLAW_QR){ window.GCLAW_QRIMG=new Image(); window.GCLAW_QRIMG.src=window.GCLAW_QR; }
window.downloadDNACard=function(){
  var c=window.GCLAW_CARD||{}, W=1200, H=675, qr=window.GCLAW_QRIMG;
  function rr(x,X,Y,w,h,r){x.beginPath();x.moveTo(X+r,Y);x.arcTo(X+w,Y,X+w,Y+h,r);x.arcTo(X+w,Y+h,X,Y+h,r);x.arcTo(X,Y+h,X,Y,r);x.arcTo(X,Y,X+w,Y,r);x.closePath();}
  function draw(){
    var cv=document.createElement('canvas'); cv.width=W; cv.height=H; var x=cv.getContext('2d');
    var bg=x.createRadialGradient(W*0.8,-60,60,W*0.8,-60,1150); bg.addColorStop(0,'#18233c'); bg.addColorStop(1,'#060A17');
    x.fillStyle=bg; x.fillRect(0,0,W,H); x.strokeStyle='#1e2c49'; x.lineWidth=2; x.strokeRect(1,1,W-2,H-2);
    var src=document.querySelector('#dna3d canvas');
    if(src){ try{ x.drawImage(src,50,(H-480)/2,370,480); }catch(e){} }
    var tx=470;
    x.fillStyle='#697083'; x.font='600 17px Inter'; x.fillText('// GEMACH ECOSYSTEM · LIVING AGENT', tx, 132);
    x.fillStyle='#FFFFFF'; x.font='800 66px Inter'; x.fillText(c.name||'Gclaw', tx, 200);
    x.fillStyle='#81899F'; x.font='500 21px Inter'; x.fillText((c.species||'')+(c.archetype?(' · '+c.archetype):''), tx, 234);
    x.fillStyle='#697083'; x.font='600 15px Inter'; x.fillText('EQUITY', tx, 300);
    x.fillStyle='#FFFFFF'; x.font='800 58px Inter'; x.fillText('$'+(c.equity||'0'), tx, 358);
    var lab='✓ VERIFIABLE ON BASE'; x.font='700 14px Inter'; var pw=x.measureText(lab).width+26;
    x.fillStyle='#49B875'; rr(x,tx,378,pw,30,8); x.fill(); x.fillStyle='#060A17'; x.fillText(lab, tx+13, 398);
    x.fillStyle='#D5D9E1'; x.font='600 22px Inter'; x.fillText(c.goodwill+' goodwill    ·    '+c.heartbeats+' heartbeats    ·    '+c.record, tx, 466);
    if(c.catchphrase){ x.fillStyle='#81899F'; x.font='italic 500 21px Inter'; x.fillText('“'+c.catchphrase+'”', tx, 508); }
    x.fillStyle='#A1A5B3'; x.font='700 18px Inter'; x.fillText('//GEMACH', tx, H-66);
    x.fillStyle='#4D5972'; x.font='400 14px Inter'; x.fillText('a creature that must trade to survive · genome '+c.fingerprint, tx, H-42);
    // QR to the repo, bottom-right — scan to clone and run your own
    if(qr&&qr.complete&&qr.naturalWidth){
      var qs=128, qx=W-qs-44, qy=H-qs-58;
      x.fillStyle='#FFFFFF'; rr(x,qx-8,qy-8,qs+16,qs+16,10); x.fill();
      x.drawImage(qr,qx,qy,qs,qs);
      x.fillStyle='#697083'; x.font='600 13px Inter'; x.textAlign='center';
      x.fillText('SCAN TO RUN YOUR OWN', qx+qs/2, qy+qs+30); x.textAlign='left';
    }
    var a=document.createElement('a'); a.download=(c.name||'gclaw').replace(/\s+/g,'-').toLowerCase()+'-dna.png'; a.href=cv.toDataURL('image/png'); a.click();
  }
  if(document.fonts&&document.fonts.ready){ document.fonts.ready.then(draw); } else { draw(); }
};
</script>"""


def dna_script(
    g: dict[str, Any],
    live: tuple,
    state: dict[str, Any],
    journal: list,
    persona: dict[str, Any],
    github_qr: str,
) -> str:
    """Three.js + genome + live trade state for the helix, plus the shareable-card
    data and the client-side card composer."""
    active, pnl, equity = live
    flag = "true" if active else "false"
    settles = [e for e in journal if e.get("event") == "settle"]
    wins = sum(1 for e in settles if float(e.get("pnl", 0) or 0) > 0)
    card = {
        "name": state.get("name") or g["species"],
        "species": g["species"],
        "archetype": (persona or {}).get("archetype", ""),
        "catchphrase": (persona or {}).get("catchphrase", ""),
        "equity": f"{equity:,.2f}",
        "goodwill": int(state.get("goodwill", 0) or 0),
        "heartbeats": int(state.get("heartbeats", 0) or 0),
        "record": f"{wins}/{len(settles)} wins" if settles else "new",
        "fingerprint": g["fingerprint"],
    }
    return (
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>'
        f"<script>window.GCLAW_DNA={{hue1:{g['hue1']},hue2:{g['hue2']},rungs:{g['rungs']},"
        f"active:{flag},pnl:{pnl:.2f}}};window.GCLAW_CARD={json.dumps(card)};"
        f"window.GCLAW_QR={json.dumps(github_qr)};</script>" + DNA3D_INIT + CARD_JS
    )


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
.dna3d{{min-height:300px;display:flex;align-items:center;justify-content:center;overflow:hidden}}.dna3d canvas{{display:block}}
.cardbtn{{margin-top:14px;background:transparent;border:1px solid var(--line);color:var(--silver);border-radius:999px;padding:8px 16px;font:inherit;font-size:12px;font-weight:600;cursor:pointer;transition:border-color .12s,color .12s}}
.cardbtn:hover{{border-color:#2c6e4a;color:var(--ink)}}
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
.lineage{{display:flex;flex-direction:column;gap:12px}}
.lcell{{display:flex;gap:12px;align-items:center;padding:10px;border:1px solid var(--line);border-radius:12px;background:#10182b}}
.lhelix{{flex:0 0 auto;width:64px}}.lhelix svg{{width:64px;height:auto;display:block}}
.lmeta{{flex:1;min-width:0}}.lmeta .species{{color:var(--muted);font-size:11px;letter-spacing:1.5px;text-transform:uppercase;margin:3px 0 6px}}
.gdiff{{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 6px}}
.gchip{{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;color:var(--muted);background:#0b1424;border:1px solid var(--line);border-radius:999px;padding:2px 8px}}
.gchip.mut{{color:var(--silver)}}.gchip.mon{{color:#9affc4;border-color:#2c6e4a}}
.gdot{{width:9px;height:9px;border-radius:50%}}.gdia{{width:8px;height:8px;border:2px solid;transform:rotate(45deg)}}
.pill{{display:inline-block;background:#16243f;color:var(--blue);padding:1px 8px;border-radius:999px;font-size:11px;margin-right:6px}}
.pill.born{{background:rgba(73,184,117,.14);color:var(--emerald)}}
.sval.feed{{font-size:12px;font-weight:600;color:var(--muted);letter-spacing:.2px}}
.loadhead{{font-size:12px;color:var(--muted);margin-bottom:14px;letter-spacing:.2px}}.loadhead b{{color:var(--silver);font-weight:700}}
.loadout{{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:13px}}
.load .loadtop{{display:flex;align-items:center;gap:8px}}.load .loadtop b{{color:var(--ink);font-size:14px;font-weight:700}}
.load .wpct{{margin-left:auto;font-variant-numeric:tabular-nums;font-weight:700;color:var(--silver);font-size:13px}}
.wbar{{height:5px;background:#16243f;border-radius:999px;overflow:hidden;margin:6px 0 5px}}
.wbar i{{display:block;height:100%;background:var(--emerald);border-radius:999px;transition:width .4s}}
.wbar.lo i{{background:var(--slate,#4D5972);opacity:.7}}
.loadsub{{font-size:12px}}.loadsub .up{{color:var(--emerald)}}.loadsub .down{{color:var(--red)}}
.callit{{background:#10203a;border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-size:14px}}
.achhdr{{font-size:22px;font-weight:800;color:var(--ink);margin-bottom:10px}}.achhdr .muted{{font-size:13px;font-weight:400}}
.nextup{{margin-top:12px}}.nblabel{{font-size:12px;color:var(--muted);margin-bottom:6px}}.nblabel b{{color:var(--silver)}}
.badges{{display:flex;flex-wrap:wrap;gap:8px}}
.badge{{font-size:12px;padding:4px 10px;border-radius:999px;border:1px solid var(--line)}}
.badge.on{{background:rgba(73,184,117,.12);border-color:#2c6e4a;color:var(--emerald)}}
.badge.off{{background:#0c1424;color:var(--muted);opacity:.55}}
.nextcard{{background:linear-gradient(180deg,rgba(73,184,117,.10),rgba(73,184,117,.02));border:1px solid #2c6e4a;border-radius:14px;padding:16px 18px;margin-bottom:16px}}
.nextcard.maxed{{text-align:center}}
.nextlabel{{font-size:10px;letter-spacing:1.6px;color:var(--emerald);font-weight:700;margin-bottom:6px}}
.nextname{{font-size:21px;font-weight:800;color:var(--ink);line-height:1.1}}
.nextdesc{{font-size:13px;margin:4px 0 13px}}
.nbar{{height:9px;background:#0b1424;border-radius:999px;overflow:hidden}}
.nbar i{{display:block;height:100%;background:linear-gradient(90deg,#2c6e4a,var(--emerald));border-radius:999px;box-shadow:0 0 12px rgba(73,184,117,.55);transition:width .6s ease}}
.nfoot{{display:flex;justify-content:space-between;margin-top:6px;font-size:12px;font-variant-numeric:tabular-nums}}.nfoot b{{color:var(--emerald);font-weight:700}}
.ladder{{display:flex;flex-direction:column}}
.rstep{{display:flex;align-items:center;gap:12px;padding:11px 2px;border-top:1px solid var(--line)}}.rstep:first-child{{border-top:none}}
.rnode{{width:22px;height:22px;flex:0 0 22px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;border:1px solid var(--line);color:var(--muted)}}
.rstep.done .rnode{{background:var(--emerald);border-color:var(--emerald);color:#06210f}}
.rstep.next .rnode{{border-color:var(--emerald);color:var(--emerald);box-shadow:0 0 0 4px rgba(73,184,117,.16)}}
.rbody{{flex:1;min-width:0}}.rtop{{display:flex;align-items:baseline;gap:8px}}.rtop b{{font-size:14px;color:var(--ink)}}
.rstep.locked .rtop b{{color:var(--silver);opacity:.6}}
.rgw{{margin-left:auto;font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums}}
.rdesc{{font-size:12px;margin-top:2px}}.rstep.locked .rdesc{{opacity:.5}}
.rlev{{flex:0 0 auto;font-size:14px;font-weight:800;color:var(--emerald);font-variant-numeric:tabular-nums}}
.rstep.locked .rlev{{color:var(--muted);opacity:.55}}.rlev.none{{color:var(--muted);font-weight:400;font-size:13px}}
.muted{{color:var(--muted);font-size:12px}}.foot{{text-align:center;color:var(--muted);font-size:11px;margin-top:18px}}
.lev{{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--line);font-size:13px;color:var(--muted)}}
.lev b{{color:var(--muted)}}.lev.on{{color:var(--ink)}}.lev.on b{{color:var(--emerald);font-size:15px}}.lev.locked{{opacity:.5}}
.link{{display:inline-block;margin-top:10px;color:var(--blue);text-decoration:none;font-size:12px}}.idrow{{font-size:15px}}
.lb-full{{display:block;margin-top:14px;padding-top:12px;border-top:1px solid var(--line);color:var(--emerald);font-weight:600}}.lb-full:hover{{color:var(--ink)}}
.decent h2{{color:var(--emerald)}}
.topup{{display:flex;flex-direction:column;gap:14px}}
.gasline{{font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:12px;line-height:1.7}}.gasline b{{color:var(--silver)}}
.qrcard{{display:flex;gap:14px;align-items:center}}
.qr{{background:#fff;padding:8px;border-radius:10px;line-height:0}}.qr svg{{width:120px;height:120px;display:block}}
.ghqr{{display:flex;gap:14px;align-items:center}}.ghqr img{{background:#fff;border-radius:8px;padding:6px}}
.qlabel{{color:var(--emerald);font-size:13px;margin-bottom:4px}}
.addr{{font-family:ui-monospace,monospace;font-size:11px;word-break:break-all;max-width:220px;color:var(--ink)}}
.topbar{{max-width:1080px;margin:0 auto 18px;background:linear-gradient(180deg,#18233c,#121a30);border:1px solid var(--line);border-radius:18px;padding:20px 26px;display:flex;flex-direction:column;gap:15px}}
.toprow{{display:flex;align-items:center;justify-content:space-between;gap:28px;flex-wrap:wrap}}
.ident{{display:flex;align-items:center;gap:14px}}.ident .lionmark{{color:var(--emerald);display:inline-flex}}
.sharebtn{{display:inline-flex;align-items:center;gap:5px;background:transparent;border:1px solid var(--line);color:var(--silver);border-radius:999px;padding:6px 13px;font-size:12px;font-weight:600;text-decoration:none;letter-spacing:.3px;transition:border-color .12s,color .12s}}
.sharebtn:hover{{border-color:var(--silver);color:var(--ink)}}
.sharebtn.lb-link{{border-color:#2c6e4a;color:var(--emerald)}}
.sharebtn.lb-link:hover{{background:rgba(73,184,117,.12);color:var(--emerald);border-color:var(--emerald)}}
.bigname{{font-size:26px;font-weight:800;color:var(--ink);letter-spacing:.3px;line-height:1}}
.vitals{{display:flex;gap:30px;flex-wrap:wrap}}.stat{{min-width:64px}}
.slabel{{font-size:10px;letter-spacing:1.6px;text-transform:uppercase;color:var(--muted);font-weight:600;margin-bottom:4px}}
.sval{{font-size:21px;font-weight:700;color:var(--ink);line-height:1;font-variant-numeric:tabular-nums}}
.sval.lead{{font-size:32px;letter-spacing:-.5px}}.sval.up{{color:var(--emerald)}}.sval.down{{color:var(--red)}}.sval.em{{color:var(--emerald)}}
.trend{{display:flex;align-items:center;gap:16px;border-top:1px solid var(--line);padding-top:14px}}
.trend .slabel{{margin:0}}.trend svg{{display:block}}.trendcap{{font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}}
.trendcap b{{font-weight:700}}.trendcap b.up{{color:var(--emerald)}}.trendcap b.down{{color:var(--red)}}
.tabs{{max-width:1080px;margin:0 auto 18px;display:flex;gap:6px;flex-wrap:wrap}}
.tab{{background:transparent;border:1px solid var(--line);color:var(--muted);border-radius:999px;padding:8px 16px;font:inherit;font-size:13px;font-weight:600;cursor:pointer;letter-spacing:.3px;transition:color .12s,background .12s}}
.tab:hover{{color:var(--silver)}}
.tab.active{{background:var(--card);color:var(--ink);border-color:#2c6e4a;box-shadow:0 0 0 1px rgba(73,184,117,.22)}}
.pane{{display:none;max-width:1080px;margin:0 auto;grid-template-columns:1fr 1fr;gap:18px;align-items:start}}
.pane.active{{display:grid}}.pane .full{{grid-column:1/-1}}
@media(max-width:760px){{.grid2{{grid-template-columns:1fr}}.pane.active{{grid-template-columns:1fr}}.topbar{{flex-direction:column;align-items:flex-start;gap:18px}}.vitals{{gap:22px}}.trend{{border-left:none;padding-left:0;border-top:1px solid var(--line);padding-top:14px;width:100%}}}}
</style></head><body>
<div class="topbar">
  <div class="toprow">
    <div class="ident"><span class="lionmark">{lion_lg}</span>
      <div><div class="eyebrow">// GEMACH · {species}</div><div class="bigname">{sigil} {name}</div></div>
      <span class="mode" style="background:hsl({mode_hue},60%,22%);color:hsl({mode_hue},80%,70%)">{mode}</span>
      <a class="sharebtn" href="{share}" target="_blank" rel="noopener" title="Share on X">𝕏 Share</a>
      <a class="sharebtn lb-link" href="leaderboard.html" title="Family leaderboard — every creature, live from Base">Leaderboard ↗</a>
    </div>
    <div class="vitals">{vitals}</div>
  </div>
  {performance}
</div>
<div class="tabs">
  <button class="tab" data-tab="overview">Overview</button>
  <button class="tab" data-tab="trading">Trading</button>
  <button class="tab" data-tab="social">Social</button>
  <button class="tab" data-tab="genome">Genome</button>
</div>

<div class="pane" id="overview">
  <div class="card decent"><h2>📈 Live positions · HyperLiquid</h2>{positions}</div>
  <div class="card decent"><h2>🧠 Market intelligence · regime</h2>{intel}</div>
  <div class="card"><h2>Life-state</h2>{gauges}</div>
  <div class="card decent full"><h2>🧬 Evolution path · earn goodwill, unlock power-ups</h2>{rewards}</div>
  <div class="card decent"><h2>⛓ Onchain identity</h2>{onchain}</div>
</div>

<div class="pane" id="trading">
  <div class="card decent"><h2>⚡ Earned leverage</h2>{leverage}</div>
  <div class="card decent"><h2>⚔ Arsenal · offensive loadout</h2>{techniques}</div>
  <div class="card"><h2>🏅 Achievements</h2>{achievements}</div>
  <div class="card"><h2>Life events</h2>{events}</div>
</div>

<div class="pane" id="social">
  <div class="card decent"><h2>👥 Family roster · onchain (Base)</h2>{roster}</div>
  <div class="card decent"><h2>🏆 Leaderboard</h2>{leaderboard}</div>
  <div class="card decent full"><h2>🎯 Call it · predictions (free · onchain-anchored)</h2>{predictions}</div>
  <div class="card full"><h2>The Show · family chatter</h2>{telepathy}</div>
</div>

<div class="pane" id="genome">
  <div class="card hero"><div class="brandrow"><span class="lionmark">{lion}</span><span class="eyebrow">// DNA</span></div><div id="dna3d" class="dna3d">{helix}</div><div class="fp">genome {fingerprint} · born {born}</div><button class="cardbtn" onclick="window.downloadDNACard&&window.downloadDNACard()">↓ Save shareable DNA card</button></div>
  <div class="card"><h2>Genome traits</h2>{traits}</div>
  <div class="card"><h2>Family · {children} children · {recodes} recodes</h2>{family}</div>
  <div class="card"><h2>🦁 Run your own</h2><div class="ghqr"><img src="{github_qr}" alt="GitHub QR" width="98" height="98"><div><div class="qlabel">Clone Gclaw</div><div class="addr" style="max-width:none">github.com/GemachDAO/Gclaw</div><div class="muted">Scan or visit — births your own living agent in ~3 commands.</div></div></div></div>
  <div class="card decent full"><h2>💰 Top up your bot</h2><div class="topup">{topup}</div></div>
</div>

<div class="foot"><span class="lionfoot">{lion_sm}</span> <b>//GEMACH</b> · Gclaw the living trading agent · rendered {generated} · auto-refresh 60s</div>
{script}
{dna_script}
</body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Gclaw living dashboard")
    sub = parser.add_subparsers(dest="command", required=True)
    p_render = sub.add_parser("render")
    p_render.add_argument("--out")
    p_render.add_argument(
        "--no-live", action="store_true", help="skip the live HL positions refresh"
    )
    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--out")
    p_serve.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    {"render": cmd_render, "serve": cmd_serve}[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
