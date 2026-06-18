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
        f'<span>{value:g}</span></div><div class="gbar"><div class="gfill" '
        f'style="width:{pct:.0f}%;background:hsl({hue},70%,55%)"></div></div></div>'
    )


def identity_svg(g: dict[str, Any], name: str, mode: str) -> str:
    """Standalone DNA identity card — the deterministic avatar pinned to IPFS."""
    c1 = f"hsl({g['hue1']},75%,60%)"
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 470" width="400" height="470">'
        '<rect width="400" height="470" rx="24" fill="#0a0e14"/>'
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
    return (f'<div class="idrow"><span class="pill">ERC-8004</span> agent <b>#{aid}</b> '
            f'on {ident.get("chain", "base:8453")}</div>'
            f'<div class="muted" style="margin-top:8px">registry {reg}…</div>'
            f'<a class="link" href="{url}" target="_blank" rel="noopener">view on basescan ↗</a>')


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
    head = f'<div class="muted" style="margin-bottom:8px">goodwill {int(gw)} → cap <b style="color:#7CFFB2">{cap}×</b></div>'
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
    equity = float(snap.get("accountValue", 0) or 0)
    if not pos:
        tail = f" · as of {asof} UTC" if asof else ""
        return f'<p class="muted">Flat — no open positions · equity ${equity:.2f}{tail}</p>'
    rows = []
    for p in pos:
        size = float(p.get("size", 0) or 0)
        side = "LONG" if size > 0 else "SHORT"
        up = float(p.get("unrealizedPnl", 0) or 0)
        color = "#7CFFB2" if up >= 0 else "#ff7c8a"
        liq = float(p.get("liquidationPx") or 0)
        rows.append(
            f'<li><span class="pill">{side}</span><b>{html.escape(str(p.get("coin", "?")))}</b> '
            f'{abs(size):g} @ ${float(p.get("entryPx", 0) or 0):,.2f} '
            f'<span style="color:{color};font-weight:700">{up:+.3f}</span> '
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


def render_html(state: dict[str, Any], identity: str, journal: list, messages: list) -> str:
    name = "Gclaw"
    g = genome(name, state.get("born_at", "genesis"))
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
        refresh_roster(h)
        g = genome("Gclaw", state.get("born_at", "genesis"))
        pin_dna_image(h, g, "Gclaw", state.get("mode", "unknown").upper())
        subprocess.run(["node", str(SCRIPT_DIR / "stats.js"), "publish"],
                       capture_output=True, text=True, timeout=80)
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


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>{name} · {species}</title>
<style>
:root{{--bg:#0b1020;--card:#141b2e;--ink:#e7ecf6;--muted:#8a96b3;--line:#243049}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(1200px 600px at 70% -10%,#1b2540,#0b1020);
color:var(--ink);font:15px/1.5 'Segoe UI',system-ui,sans-serif;padding:24px}}
h1{{margin:0;font-size:26px;letter-spacing:.5px}}h2{{font-size:13px;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);margin:0 0 10px}}
.wrap{{max-width:1080px;margin:0 auto;display:grid;grid-template-columns:300px 1fr;gap:18px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px}}
.hero{{text-align:center}}.species{{color:var(--muted);font-size:13px;letter-spacing:2px;text-transform:uppercase}}
.sigil{{font-size:30px}}.mode{{display:inline-block;padding:4px 12px;border-radius:999px;font-weight:700;font-size:12px;letter-spacing:1px;margin-top:8px}}
.fp{{font-family:ui-monospace,monospace;color:var(--muted);font-size:11px;margin-top:10px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
.gauge{{margin:10px 0}}.glabel{{display:flex;justify-content:space-between;font-size:13px;color:var(--muted);margin-bottom:4px}}.glabel span{{color:var(--ink);font-weight:700}}
.gbar,.tbar{{height:9px;background:#0c1322;border-radius:6px;overflow:hidden}}.gfill,.tfill{{height:100%;border-radius:6px}}
.trait{{display:grid;grid-template-columns:90px 1fr 30px;align-items:center;gap:8px;margin:7px 0;font-size:13px}}.trait b{{text-align:right}}
ul{{list-style:none;margin:0;padding:0}}.family li,.events li{{padding:7px 0;border-bottom:1px solid var(--line);font-size:13px}}
.pill{{display:inline-block;background:#1d2a47;color:#9db4ff;padding:1px 8px;border-radius:999px;font-size:11px;margin-right:6px}}
.muted{{color:var(--muted);font-size:12px}}.foot{{text-align:center;color:var(--muted);font-size:11px;margin-top:18px}}
.lev{{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--line);font-size:13px;color:var(--muted)}}
.lev b{{color:var(--muted)}}.lev.on{{color:var(--ink)}}.lev.on b{{color:#7CFFB2;font-size:15px}}.lev.locked{{opacity:.5}}
.link{{display:inline-block;margin-top:10px;color:#9db4ff;text-decoration:none;font-size:12px}}.idrow{{font-size:15px}}
.decent h2{{color:#7CFFB2}}
@media(max-width:760px){{.wrap{{grid-template-columns:1fr}}.grid2{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">
<div class="card hero">
  <div class="species">{species}</div>
  <h1>{sigil} {name}</h1>
  {helix}
  <div class="mode" style="background:hsl({mode_hue},60%,22%);color:hsl({mode_hue},80%,70%)">{mode}</div>
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
  <div class="grid2" style="margin-top:18px">
    <div class="card"><h2>Life events</h2>{events}</div>
    <div class="card"><h2>The Show · family chatter</h2>{telepathy}</div>
  </div>
</div></div>
<div class="foot">Gclaw — the living trading agent · rendered {generated} · auto-refresh 60s</div>
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
