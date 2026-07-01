#!/usr/bin/env python3
"""Gclaw living dashboard — "The Mind, Alive, With Receipts".

Renders the creature as a scientist: the hero is PROVEN EDGE (forge-graduated,
out-of-sample, inheritable techniques), not PnL. One scrolling page, three
altitudes — GLANCE (proven-edge hero + vitals + honest track record), SUBSTANCE
(the Scientist's Bench authoring loop, proven techniques, proven-DNA helix, a
lineage graph), and PROOF (the three books, lineage, onchain identity + the
reputation scorecard, collapsed below the fold).

Architecture — a hard I/O / render split:

  * ``refresh(home)`` does ALL data-fetch: subprocess (node, IPFS, beacon), the
    HyperLiquid snapshot, QR generation, and reads every runtime JSON/JSONL into
    one plain ``state`` dict.
  * ``render(state)`` is a PURE function of that dict — no I/O, no network, no
    subprocess — so it is unit-testable and can't inject untrusted values (all
    dynamic text flows through the autoescaping :func:`el` / :func:`esc` helpers).

Commands:
    render [--out PATH] [--no-live]   write the dashboard HTML
    serve  [--port 8787]              render once and serve $GCLAW_HOME over HTTP
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import os
import subprocess
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

IDENTITY_REGISTRY = "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"  # ERC-8004 on Base
GITHUB_URL = "https://github.com/GemachDAO/Gclaw"
SCRIPT_DIR = Path(__file__).resolve().parent
PROVEN_MIN_TRADES = 3  # a technique is live-proven at >= this many closes w/ positive e
REPLICATE_MIN_EDGE = 2  # proven-edge techniques required to breed (mirrors evolve.py)


# --------------------------------------------------------------------------- #
# Autoescaping HTML helpers — the ONLY way dynamic text reaches the page.
# --------------------------------------------------------------------------- #
def esc(value: Any) -> str:
    """HTML-escape any value (quotes included) for safe interpolation."""
    return html.escape(str(value), quote=True)


def el(tag: str, *children: str, cls: str = "", **attrs: str) -> str:
    """Build one element, escaping attribute values; children are already-safe HTML.

    Children must be strings produced by :func:`el` / :func:`esc` / trusted
    constants — never raw user data. This is a deliberately tiny composer (not a
    full template engine) so the whole render path stays stdlib-only and auditable.
    """
    parts = [tag]
    if cls:
        parts.append(f'class="{esc(cls)}"')
    for key, val in attrs.items():
        parts.append(f'{key.rstrip("_").replace("_", "-")}="{esc(val)}"')
    open_tag = " ".join(parts)
    return f"<{open_tag}>{''.join(children)}</{tag}>"


def home() -> Path:
    return Path(os.environ.get("GCLAW_HOME", str(Path.home() / ".gclaw")))


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# --------------------------------------------------------------------------- #
# Deterministic genome + heredity (the organism metaphor — kept, well-tested).
# --------------------------------------------------------------------------- #
SPECIES_PREFIX = ["Vor", "Kryo", "Zeph", "Mor", "Lyx", "Quel", "Ras", "Thi", "Nyx", "Obol"]
SPECIES_SUFFIX = ["dax", "mire", "lith", "phar", "gax", "ven", "tide", "korn", "ses", "wraith"]
SIGILS = ["◆", "◈", "✦", "✧", "❖", "⬡", "⬢", "❂", "✸", "⟡", "◇", "✺"]
TRAITS = ["Vitality", "Cunning", "Aggression", "Discipline", "Fertility"]
ROLE_BIAS = {
    "scout": {"Cunning": 4, "Aggression": 2, "Discipline": -1},
    "analyst": {"Cunning": 3, "Discipline": 3, "Aggression": -2},
    "executor": {"Aggression": 4, "Discipline": 1, "Vitality": -1},
    "leader": {"Vitality": 2, "Discipline": 2, "Cunning": 2, "Aggression": 1, "Fertility": -1},
}


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


def _byte_stream(seed: bytes):
    counter = 0
    while True:
        yield from hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        counter += 1


def breed(
    parent: dict[str, Any], child_name: str, role: str, parent_goodwill: float
) -> dict[str, Any]:
    """A child genome that INHERITS the parent's and diverges — real heredity.

    Deterministic from (parent fingerprint, child name, role). Mutation strength
    scales with fitness: a higher-goodwill parent breeds more stable offspring; a
    rare 'hopeful monster' keeps lineages from homogenising.
    """
    s = _byte_stream(
        hashlib.sha256(f"{parent['fingerprint']}|{child_name}|{role}".encode()).digest()
    )
    unit = lambda: next(s) / 255  # noqa: E731
    signed = lambda: unit() * 2 - 1  # noqa: E731
    roll = lambda p: next(s) / 256 < p  # noqa: E731
    fit = max(0.0, min(1.0, (parent_goodwill - 50) / 150))
    m = 1.30 - 0.80 * fit

    hue1 = (parent["hue1"] + signed() * 18 * m) % 360
    offset = ((parent["hue2"] - parent["hue1"]) % 360 + signed() * 12 * m) % 360
    hue2 = (hue1 + offset) % 360
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
    if roll(0.04 * m) or monster:
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


def identity_svg(g: dict[str, Any], name: str, mode: str) -> str:
    """Standalone DNA identity card — the deterministic avatar pinned to IPFS."""
    c1 = f"hsl({g['hue1']},75%,60%)"
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 470" width="400" height="470">'
        '<rect width="400" height="470" rx="24" fill="#060A17"/>'
        f'<text x="200" y="46" text-anchor="middle" fill="{c1}" font-family="monospace" '
        f'font-size="13" letter-spacing="3">{esc(g["species"].upper())}</text>'
        f'<text x="200" y="82" text-anchor="middle" fill="#e8eef6" font-family="monospace" '
        f'font-size="26">{esc(g["sigil"])} {esc(name)}</text>'
        f'<g transform="translate(90,108)">{helix_svg(g)}</g>'
        f'<text x="200" y="446" text-anchor="middle" fill="#5b6b7f" font-family="monospace" '
        f'font-size="11">genome {esc(g["fingerprint"])} · {esc(mode)}</text></svg>'
    )


# --------------------------------------------------------------------------- #
# Brand assets — the Gemach lion, Base badge, atmospheric banner.
# --------------------------------------------------------------------------- #
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
BASE_SYMBOL = (
    '<svg viewBox="0 0 111 111" fill="none" xmlns="http://www.w3.org/2000/svg" '
    'style="width:{w};height:{w};display:inline-block;vertical-align:middle">'
    '<path d="M54.921 110.034C85.359 110.034 110.034 85.402 110.034 55.017C110.034 24.6319 '
    "85.359 0 54.921 0C26.0432 0 2.35281 22.1714 0 50.3923H72.8467V59.6416H3.9565e-07C2.35281 "
    '87.8625 26.0432 110.034 54.921 110.034Z" fill="#0052FF"/></svg>'
)
_BANNER_CACHE: str | None = None


def lion(width: str = "30px") -> str:
    """The Gemach geometric lion mark, recolorable via the parent's CSS color."""
    return LION_SVG.format(w=width)


def base_badge() -> str:
    """Official 'Built on Base' attribution — the ERC-8004 identity is on Base."""
    return f'<div class="basebadge">{BASE_SYMBOL.format(w="15px")}<span>BUILT ON BASE</span></div>'


def banner_datauri() -> str:
    """The committed Gemach atmospheric banner as a base64 data URI (cached)."""
    global _BANNER_CACHE
    if _BANNER_CACHE is not None:
        return _BANNER_CACHE
    img = SCRIPT_DIR.parent / "assets" / "brand" / "dashboard-banner.jpg"
    try:
        _BANNER_CACHE = "data:image/jpeg;base64," + base64.b64encode(img.read_bytes()).decode(
            "ascii"
        )
    except (OSError, ValueError):
        _BANNER_CACHE = ""
    return _BANNER_CACHE


_HERO_CACHE: str | None = None


def hero_datauri() -> str:
    """The GLANCE hero — the self-evolving-DNA-organism art (Gemach brand), as a cached
    base64 data URI so the dashboard stays a single self-contained file. Empty if absent."""
    global _HERO_CACHE
    if _HERO_CACHE is not None:
        return _HERO_CACHE
    img = SCRIPT_DIR.parent / "assets" / "generated" / "dashboard-hero.jpg"
    try:
        _HERO_CACHE = "data:image/jpeg;base64," + base64.b64encode(img.read_bytes()).decode("ascii")
    except (OSError, ValueError):
        _HERO_CACHE = ""
    return _HERO_CACHE


def share_url(state: dict[str, Any], name: str, proven_edge: int) -> str:
    """A share intent link — flexes PROVEN EDGE (the fitness), not equity, and links
    to the verifiable onchain identity so the claim proves itself."""
    aid = (state.get("onchain_identity") or {}).get("agentId")
    link = (
        f"https://basescan.org/nft/{IDENTITY_REGISTRY}/{aid}"
        if aid
        else "https://github.com/GemachDAO/Gclaw"
    )
    text = (
        f"Meet {name} 🦁🧬 — my living, onchain trading agent. {proven_edge} proven edges "
        f"graduated (forge-tested, out-of-sample), fully verifiable on @base, built with @GemachDAO."
    )
    return "https://twitter.com/intent/tweet?" + urllib.parse.urlencode({"text": text, "url": link})


# --------------------------------------------------------------------------- #
# REFRESH — all I/O: subprocess, HyperLiquid snapshot, IPFS, QR, file reads.
# Everything below writes cache files or returns a plain dict; render() never
# touches the network or the shell.
# --------------------------------------------------------------------------- #
def _run_node(script: str, *args: str, timeout: int = 60) -> str:
    """Best-effort node call; returns stdout or '' (never raises)."""
    try:
        proc = subprocess.run(
            ["node", str(SCRIPT_DIR / script), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def refresh_positions(h: Path) -> None:
    """Cache live HL state to positions.json so the offline page can show it."""
    out = _run_node("hl_perp.js", "status", timeout=80)
    try:
        data = json.loads(out.splitlines()[-1]) if out else {}
    except (ValueError, IndexError):
        return
    if data.get("ok"):
        data["ts"] = datetime.now(UTC).isoformat(timespec="seconds")
        (h / "positions.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def refresh_roster(h: Path) -> None:
    """Cache the onchain family roster (peers.js) for the page."""
    out = _run_node("peers.js", timeout=60)
    try:
        data = json.loads(out) if out else {}
    except ValueError:
        return
    if data.get("ok"):
        (h / "peers_roster.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def refresh_leaderboard(h: Path) -> None:
    """Pull peer stats and recompute the family leaderboard."""
    _run_node("stats.js", "fetch", timeout=40)
    out = _run_node("stats.js", "leaderboard", timeout=20)
    try:
        data = json.loads(out) if out else {}
    except ValueError:
        return
    if data.get("ok"):
        (h / "leaderboard.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def refresh_gas(h: Path) -> None:
    out = _run_node("gas.js", "check", timeout=30)
    if out:
        (h / "gas.json").write_text(out, encoding="utf-8")


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
            continue
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


def github_qr_datauri(h: Path) -> str:
    """A PNG QR of the repo as a base64 data URI (generated once, cached)."""
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
        return "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode("ascii")
    except (OSError, ValueError):
        return ""


def pin_dna_image(h: Path, g: dict[str, Any], name: str, mode: str) -> None:
    """Write the standalone DNA avatar and pin it to IPFS (idempotent)."""
    try:
        (h / "identity.svg").write_text(identity_svg(g, name, mode), encoding="utf-8")
        _run_node("stats.js", "pin-image", timeout=40)
    except OSError:
        pass


def deploy_leaderboard(h: Path) -> None:
    """Co-locate the decentralized leaderboard next to the dashboard so the header
    link resolves wherever it's served (http, file://, or a pinned IPFS dir)."""
    src = SCRIPT_DIR.parent / "leaderboard" / "leaderboard.html"
    try:
        if src.exists():
            (h / "leaderboard.html").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        pass


def refresh(h: Path, live: bool = True) -> dict[str, Any]:
    """Gather ALL page data into one plain dict — the sole I/O boundary.

    When ``live`` is true, first refreshes the network-backed caches (HL snapshot,
    onchain beacon/roster/leaderboard, gas, QRs, IPFS pin) and co-deploys the
    leaderboard. Then reads every runtime file into the returned state, which
    :func:`render` consumes purely.

    Args:
        h: the ``$GCLAW_HOME`` directory to read runtime state from.
        live: run the network refresh steps before reading (heartbeat sets true).

    Returns:
        A JSON-serialisable state dict with every value the page renders.
    """
    metabolism = load_json(h / "metabolism.json", {})
    if not metabolism:
        raise SystemExit(f"No metabolism state at {h}. Run metabolism.py init first.")
    g = genome("Gclaw", metabolism.get("born_at", "genesis"))
    if live:
        refresh_positions(h)
        pin_dna_image(h, g, "Gclaw", metabolism.get("mode", "unknown").upper())
        _run_node("stats.js", "publish", timeout=80)
        _run_node("erc8004_register.js", "beacon", timeout=80)
        refresh_gas(h)
        refresh_roster(h)
        refresh_qr(h)
        refresh_leaderboard(h)
    deploy_leaderboard(h)
    style = load_json(h / "forge" / "style.json", {})
    return {
        "metabolism": metabolism,
        "genome": g,
        "reputation": load_json(h / "reputation.json", {}),
        "style": style,
        "proven_markets": load_json(h / "forge" / "proven_markets.json", {}).get("pairs", []),
        "techniques": _load_techniques(h, style.get("adopted", [])),
        "authored_cards": _load_authored(
            h, (metabolism.get("onchain_identity") or {}).get("agentId", "")
        ),
        "journal": read_jsonl(h / "journal.jsonl"),
        "telepathy": read_jsonl(h / "telepathy" / "bus.jsonl"),
        "positions": load_json(h / "positions.json", {}),
        "gas": load_json(h / "gas.json", {}),
        "leaderboard": load_json(h / "leaderboard.json", {}),
        "persona": load_json(h / "dna" / "persona.json", {}),
        "github_qr": github_qr_datauri(h),
        "topup_qr": _svg_inline(h / "qr" / "topup.svg"),
        "banner": banner_datauri(),
        "hero_bg": hero_datauri(),
    }


def _load_techniques(h: Path, adopted: list) -> dict[str, dict[str, Any]]:
    """Read each adopted technique's card (claim/status/author/oos) once."""
    out: dict[str, dict[str, Any]] = {}
    for e in adopted:
        tid = e.get("id") if isinstance(e, dict) else e
        if tid:
            out[tid] = load_json(h / "forge" / "techniques" / str(tid) / "technique.json", {})
    return out


def _load_authored(h: Path, aid: str) -> list[dict[str, Any]]:
    """Every technique THIS agent authored (technique.json ``author == agentId``),
    newest first by ``created_at`` — the raw authoring history the Scientist's Bench
    narrates (including drafts still under the judge, not just the adopted survivors)."""
    root = h / "forge" / "techniques"
    if not root.exists():
        return []
    cards = []
    for d in root.iterdir():
        card = load_json(d / "technique.json", {})
        if card and str(card.get("author")) == str(aid):
            cards.append(card)
    cards.sort(key=lambda c: str(c.get("created_at", "")), reverse=True)
    return cards


def _svg_inline(p: Path) -> str:
    try:
        s = p.read_text(encoding="utf-8")
        return s[s.index("<svg") :]
    except (OSError, ValueError):
        return ""


# --------------------------------------------------------------------------- #
# Pure data-shaping — small functions that turn the state dict into the exact
# values each render section needs. No I/O; unit-testable.
# --------------------------------------------------------------------------- #
def proven_edge(style: dict[str, Any]) -> list[dict[str, Any]]:
    """Adopted techniques with REAL live edge (>= PROVEN_MIN_TRADES closes, positive
    expectancy) — the inheritable DNA the fitness signal counts (mirrors evolve.py)."""
    return [
        e
        for e in style.get("adopted", [])
        if int(e.get("trades", 0) or 0) >= PROVEN_MIN_TRADES and float(e.get("e", 0.0) or 0) > 0
    ]


def breed_gate(state: dict[str, Any], proven: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate the REAL reproduction gate: >= REPLICATE_MIN_EDGE proven edges AND at
    least one new since the last birth. Returns the gate's checklist + ready flag."""
    metabolism = state["metabolism"]
    n = len(proven)
    last = int(metabolism.get("last_replicate_edge_count", 0) or 0)
    have_edges = n >= REPLICATE_MIN_EDGE
    have_new = n > last
    return {
        "proven": n,
        "need": REPLICATE_MIN_EDGE,
        "have_edges": have_edges,
        "have_new": have_new,
        "new_since": max(0, n - last),
        "ready": have_edges and have_new and not metabolism.get("children"),
    }


def track_record(reputation: dict[str, Any], journal: list[dict[str, Any]]) -> dict[str, Any]:
    """The honest settled scorecard — realized PnL, closes, win-rate. Prefers the
    reputation snapshot; falls back to summing settle events from the journal."""
    trading = reputation.get("trading") or {}
    if trading:
        return {
            "pnl": float(trading.get("realized_pnl_usd", 0.0) or 0.0),
            "closes": int(trading.get("closed_trades", 0) or 0),
            "win_rate": float(trading.get("win_rate", 0.0) or 0.0),
        }
    settles = [e for e in journal if e.get("event") == "settle"]
    pnl = sum(float(e.get("pnl", 0) or 0) for e in settles)
    wins = sum(1 for e in settles if float(e.get("pnl", 0) or 0) > 0)
    total = len(settles)
    return {"pnl": pnl, "closes": total, "win_rate": (wins / total) if total else 0.0}


def _verdict_of(card: dict[str, Any]) -> tuple[str, int, float]:
    """A technique card → (verdict, oos_n, expectancy). ``proven`` graduated; ``judging``
    not yet backtested (n=0); ``rejected`` backtested but not proven — the judge said no."""
    oos = (card.get("card") or {}).get("oos") or {}
    n = int(oos.get("n", 0) or 0)
    exp = float(oos.get("expectancy", 0.0) or 0.0)
    if card.get("status") == "proven" or (card.get("card") or {}).get("proven"):
        return "proven", n, exp
    return ("judging" if n == 0 else "rejected"), n, exp


def author_events(state: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    """The Scientist's Bench feed: the newest authored techniques, each with its live
    verdict (proven / rejected / judging). Newest first.

    Reads the self-authored technique cards (``author == agentId``, ordered by
    ``created_at``) — including drafts still under the judge — so the feed narrates the
    real authoring loop: invented → judged → adopted or rejected. Falls back to the
    ``recode`` journal events when no authored cards are present (e.g. a test fixture).
    """
    cards = state.get("authored_cards") or []
    if not cards:
        seen: list[str] = []
        for e in reversed([j for j in state["journal"] if j.get("event") == "recode"]):
            for tid in e.get("authored", []):
                if tid not in seen:
                    seen.append(tid)
        cards = [state["techniques"].get(t, {"id": t}) for t in seen]
    events: list[dict[str, Any]] = []
    for card in cards[:limit]:
        verdict, n, exp = _verdict_of(card)
        events.append(
            {
                "id": card.get("id", "?"),
                "claim": card.get("claim", ""),
                "verdict": verdict,
                "oos_n": n,
                "expectancy": exp,
            }
        )
    return events


def proven_dna(style: dict[str, Any]) -> list[dict[str, Any]]:
    """Every adopted technique as a base pair for the helix — id, live expectancy,
    trades, weight, and whether it is proven. Fed to the 3D strand as real DNA."""
    out = []
    for e in style.get("adopted", []):
        tid = e.get("id") if isinstance(e, dict) else e
        exp = float(e.get("e", 0.0) or 0.0)
        trades = int(e.get("trades", 0) or 0)
        out.append(
            {
                "id": tid,
                "e": round(exp, 4),
                "trades": trades,
                "weight": round(float(e.get("weight", 1.0) or 1.0), 3),
                "proven": trades >= PROVEN_MIN_TRADES and exp > 0,
            }
        )
    return out


def lineage_graph(state: dict[str, Any], proven: list[dict[str, Any]]) -> dict[str, Any]:
    """Technique flow for the living graph: nodes bucketed draft → judged → proven →
    inherited. Draws the real authoring pipeline + the (currently empty) inherit column."""
    proven_ids = {p["id"] for p in proven}
    cards = state["techniques"]
    draft, judged, prov = [], [], []
    for tid, card in cards.items():
        oos = (card.get("card") or {}).get("oos") or {}
        n = int(oos.get("n", 0) or 0)
        if tid in proven_ids or card.get("status") == "proven":
            prov.append({"id": tid, "e": next((p["e"] for p in proven if p["id"] == tid), 0.0)})
        elif n == 0:
            draft.append({"id": tid})
        else:
            judged.append({"id": tid, "n": n})
    children = [{"name": c.get("name", "child")} for c in state["metabolism"].get("children", [])]
    return {"draft": draft, "judged": judged, "proven": prov, "inherited": children}


# --------------------------------------------------------------------------- #
# RENDER — pure section functions. Each takes the state (or a slice) and returns
# safe HTML built via el()/esc(). No I/O below this line.
# --------------------------------------------------------------------------- #
def _fmt_money(v: float) -> str:
    sign = "−" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def _fmt_edge(v: float) -> str:
    return f"{v:+.3f}".rstrip("0").rstrip(".") if v else "0"


def hero_html(state: dict[str, Any], proven: list[dict[str, Any]], gate: dict[str, Any]) -> str:
    """GLANCE — the PROVEN EDGE hero: the count of graduated techniques (the fitness),
    with a breed-ready ribbon when the reproduction gate is met."""
    n = len(proven)
    born_count = int((state["reputation"].get("evolution") or {}).get("proven_edge_count", n) or n)
    delta = el("span", esc(f"+{born_count} since birth"), cls="herodelta") if born_count else ""
    ribbon = el("span", "⚡ BREED-READY", cls="ribbon", id="breedRibbon") if gate["ready"] else ""
    # The self-evolving-DNA hero art sits behind the number, aligned right (its subject),
    # under a left-heavy rich-black scrim so the PROVEN EDGE count stays razor-crisp.
    bg = state.get("hero_bg") or ""
    style = (
        (
            "background:linear-gradient(90deg,rgba(6,10,23,.97) 0%,rgba(6,10,23,.82) 38%,"
            f"rgba(6,10,23,.32) 72%,rgba(6,10,23,.6) 100%),url({bg}) center right/cover no-repeat;"
            "border:1px solid var(--line);padding:34px 30px;min-height:220px;"
            "display:flex;flex-direction:column;justify-content:center"
        )
        if bg
        else ""
    )
    attrs = {"style": style} if style else {}
    return el(
        "section",
        el("div", "// FITNESS · PROVEN EDGE", cls="eyebrow"),
        el(
            "div",
            el("span", esc(str(n)), cls="heronum", id="provenEdge"),
            el(
                "div",
                el("div", "techniques graduated", cls="herolabel"),
                delta,
                ribbon,
                cls="herometa",
            ),
            cls="herorow",
        ),
        el("div", "forge-proven · out-of-sample · inheritable", cls="herosub"),
        cls="hero",
        **attrs,
    )


def vitals_html(state: dict[str, Any], gate: dict[str, Any]) -> str:
    """The three glance-layer vitals: self-authored, event calibration, breed-ready."""
    evo = state["reputation"].get("evolution") or {}
    cal = state["reputation"].get("event_calibration") or {}
    authored = int(evo.get("self_authored_techniques", state["metabolism"].get("recodes", 0)) or 0)
    brier = cal.get("brier")
    cal_val = f"{brier:.3f}" if isinstance(brier, (int, float)) else "—"
    cal_sub = "warming up" if not isinstance(brier, (int, float)) else f"n={cal.get('n', 0)}"
    if gate["ready"]:
        breed_val, breed_sub = "✓ ready", "gate met"
    elif gate["have_edges"]:
        breed_val, breed_sub = "◆ 1 new", "needs a new edge"
    else:
        breed_val, breed_sub = f"{gate['proven']}/{gate['need']}", "graduate more edge"

    def vital(label: str, val: str, sub: str, em: bool = False) -> str:
        return el(
            "div",
            el("div", esc(label), cls="vlabel"),
            el("div", esc(val), cls="vval em" if em else "vval"),
            el("div", esc(sub), cls="vsub"),
            cls="vital",
        )

    return el(
        "div",
        vital(
            "Self-authored",
            str(authored),
            f"{int(state['metabolism'].get('recodes', 0) or 0)} recodes",
        ),
        vital("Event calibration", cal_val, cal_sub),
        vital("Breed-ready", breed_val, breed_sub, em=gate["ready"]),
        cls="vitals",
    )


def track_record_html(state: dict[str, Any]) -> str:
    """The honest scorecard line — realized PnL in dignified slate (never red),
    closes, win-rate, and a re-derivable-onchain verify link."""
    rec = track_record(state["reputation"], state["journal"])
    ident = state["metabolism"].get("onchain_identity") or {}
    verify = ident.get("agentUrl") or (
        f"https://basescan.org/nft/{IDENTITY_REGISTRY}/{ident.get('agentId')}"
        if ident.get("agentId")
        else GITHUB_URL
    )
    if rec["closes"] == 0:
        body = el("span", "no closed trades yet — the desk is warming up", cls="trslate")
    else:
        body = (
            el("b", esc(_fmt_money(rec["pnl"])), cls="trpnl")
            + esc(f" · {rec['closes']} closes · {rec['win_rate'] * 100:.0f}% win · ")
            + el(
                "a",
                "re-derivable onchain ↗",
                cls="trlink",
                href=verify,
                target="_blank",
                rel="noopener",
            )
        )
    return el(
        "div",
        el("span", "TRACK RECORD", cls="trhead"),
        el("span", body, cls="trbody"),
        cls="trackrec",
    )


def _verdict_chip(ev: dict[str, Any]) -> str:
    if ev["verdict"] == "proven":
        return el("span", "✓ GRADUATED", cls="vd proven")
    if ev["verdict"] == "judging":
        return el("span", "▸ judging", cls="vd judging")
    detail = f"✗ REJECTED · oos n={ev['oos_n']} · E {ev['expectancy'] * 100:+.2f}%"
    return el("span", esc(detail), cls="vd rejected")


def bench_html(state: dict[str, Any]) -> str:
    """SUBSTANCE — the Scientist's Bench: the live authoring loop. Each authored
    technique with its claim (the mind narrating its reasoning) and the judge's verdict."""
    events = author_events(state)
    if not events:
        rows = el("p", "The bench is quiet — no techniques authored yet.", cls="muted")
    else:
        cards = []
        for ev in events:
            cards.append(
                el(
                    "li",
                    el(
                        "div",
                        el("span", "✎ AUTHORED", cls="authtag"),
                        el("b", esc(ev["id"]), cls="authid"),
                        _verdict_chip(ev),
                        cls="benchtop",
                    ),
                    el("div", esc(ev["claim"]), cls="benchclaim"),
                    cls="benchrow",
                )
            )
        rows = el("ul", *cards, cls="bench")
    return el(
        "div",
        el("div", "// THE SCIENTIST'S BENCH", cls="eyebrow"),
        el("div", el("span", "● authoring", cls="livedot"), cls="benchhead"),
        rows,
        cls="section bench-section",
    )


def proven_tech_html(state: dict[str, Any], proven: list[dict[str, Any]]) -> str:
    """The proven techniques with their PROVEN flag + OOS/live expectancy + trades —
    the fitness itself, not ensemble weight. Non-proven adopted shown demoted below."""
    adopted = state["style"].get("adopted", [])
    proven_ids = {p["id"] for p in proven}
    stars = {p["technique"]: p for p in _best_oos(state["proven_markets"])}
    rows = []
    for p in proven:
        star = stars.get(p["id"])
        oos = (
            el("span", esc(f"OOS n={star['oos_n']} t={star.get('t', 0):.2f} ★"), cls="oosstar")
            if star
            else ""
        )
        rows.append(
            el(
                "li",
                el("span", "●", cls="pdot"),
                el("b", esc(p["id"]), cls="pname"),
                el("span", "PROVEN", cls="pflag"),
                el("span", esc(f"{_fmt_edge(p['e'])} live · {p['trades']} trades"), cls="pedge"),
                oos,
                cls="provenrow",
            )
        )
    trial = [e for e in adopted if e.get("id") not in proven_ids]
    if trial:
        rows.append(
            el(
                "li",
                el("span", "○", cls="pdot dim"),
                esc(f"{len(trial)} more on trial — adopted, not yet live-proven"),
                cls="provenrow dim",
            )
        )
    if not rows:
        rows = [el("li", "No proven edge yet — the forge is still judging.", cls="muted")]
    return el(
        "div",
        el("div", "// PROVEN DNA", cls="eyebrow"),
        el("ul", *rows, cls="provenlist"),
        cls="section",
    )


def _best_oos(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Best out-of-sample pair per technique (highest oos_n) for the ★ callout."""
    best: dict[str, dict[str, Any]] = {}
    for p in pairs:
        tid = p.get("technique")
        if tid and int(p.get("oos_n", 0) or 0) > int(best.get(tid, {}).get("oos_n", 0) or 0):
            best[tid] = p
    return list(best.values())


def calibration_html(state: dict[str, Any]) -> str:
    """The event-desk Brier reliability curve — the mind watching how well it knows
    what it knows. Honest empty-state at n=0 (the desk hasn't learned to doubt itself)."""
    cal = state["reputation"].get("event_calibration") or {}
    n = int(cal.get("n", 0) or 0)
    diag = '<line x1="10" y1="130" x2="130" y2="10" stroke="#61B8FF" stroke-width="1.5" stroke-dasharray="3 3" opacity="0.6"/>'
    curve = ""
    if n and isinstance(cal.get("buckets"), list):
        pts = []
        for b in cal["buckets"]:
            x = 10 + float(b.get("p", 0)) * 120
            y = 130 - float(b.get("obs", 0)) * 120
            pts.append(f"{x:.1f},{y:.1f}")
        curve = (
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="#49B875" stroke-width="2"/>'
        )
    svg = (
        '<svg viewBox="0 0 140 140" width="140" height="140" class="calsvg">'
        '<rect x="10" y="10" width="120" height="120" fill="none" stroke="#1e2c49"/>'
        f"{diag}{curve}</svg>"
    )
    if n == 0:
        note = el(
            "p",
            "n=0 — the mind hasn't yet learned to doubt itself. Brier appears after the first calibrated event forecasts.",
            cls="muted",
        )
    else:
        brier = cal.get("brier")
        base = cal.get("no_skill_baseline")
        note = el("p", esc(f"Brier {brier} vs no-skill {base} · {n} settled"), cls="muted")
    return el(
        "div",
        el("div", "// SELF-KNOWLEDGE · CALIBRATION", cls="eyebrow"),
        el("div", svg, note, cls="calrow"),
        cls="section",
    )


def breed_gate_html(gate: dict[str, Any]) -> str:
    """The REAL reproduction gate — proven-edge count + one-new-since-birth. Replaces
    the retired goodwill leverage ladder; reproduction gates on proven edge now."""

    def check(ok: bool, label: str) -> str:
        return el(
            "li",
            el("span", "✓" if ok else "◆", cls="gcheck ok" if ok else "gcheck"),
            esc(label),
            cls="gaterow",
        )

    return el(
        "div",
        el("div", "// REPRODUCTION GATE", cls="eyebrow"),
        el(
            "ul",
            check(
                gate["have_edges"],
                f"≥{gate['need']} proven edges  [{gate['proven']}/{gate['need']}]",
            ),
            check(gate["have_new"], f"1 new edge since last birth  [{gate['new_since']}]"),
            cls="gatelist",
        ),
        el(
            "p",
            "Breed-ready ✓ — children inherit only proven DNA."
            if gate["ready"]
            else "Reproduction locked — graduate a new edge to breed.",
            cls="muted",
        ),
        cls="section",
    )


def positions_html(state: dict[str, Any]) -> str:
    """Live HyperLiquid positions, read from the cached snapshot (Book A / forge perps)."""
    snap = state["positions"]
    pos = snap.get("positions") or []
    asof = (snap.get("ts") or "")[11:19]
    equity = float(snap.get("equity", 0) or 0)
    if not pos:
        tail = f" · as of {asof} UTC" if asof else ""
        return el("p", esc(f"Flat — no open positions · equity ${equity:.2f}{tail}"), cls="muted")
    rows = []
    for p in pos:
        size = float(p.get("size", 0) or 0)
        side = "LONG" if size > 0 else "SHORT"
        up = float(p.get("unrealizedPnl", 0) or 0)
        color = "var(--emerald)" if up >= 0 else "var(--red)"
        coin = str(p.get("coin", "?"))
        rows.append(
            el(
                "li",
                el("span", esc(side), cls="pill"),
                el("b", esc(coin)),
                esc(f" {abs(size):g} @ ${float(p.get('entryPx', 0) or 0):,.2f} "),
                el(
                    "span",
                    esc(_fmt_money(up)),
                    cls="pos-pnl",
                    data_coin=coin,
                    style=f"color:{color};font-weight:700",
                ),
                el("span", esc(f" liq ${float(p.get('liquidationPx') or 0):,.0f}"), cls="muted"),
                cls="posrow",
            )
        )
    head = el(
        "div",
        esc("equity "),
        el("b", esc(f"${equity:.2f}"), id="posEquity", style="color:var(--ink)"),
        esc(f" · {len(pos)} open · "),
        el("span", esc(f"as of {asof} UTC"), id="posAsOf"),
        cls="muted poshead",
    )
    return head + el("ul", *rows, cls="events")


def techniques_html(state: dict[str, Any]) -> str:
    """The full adopted loadout table — every technique, its live edge/trades, weight,
    and PROVEN flag. The proof, not just a bar."""
    adopted = state["style"].get("adopted", [])
    if not adopted:
        return el("p", "No techniques yet — the arsenal is installed at birth.", cls="muted")
    proven_ids = {p["id"] for p in proven_edge(state["style"])}
    rows = []
    for e in sorted(adopted, key=lambda x: -float(x.get("weight", 1.0) or 1.0)):
        tid = str(e.get("id"))
        w = float(e.get("weight", 1.0) or 1.0)
        trades = int(e.get("trades", 0) or 0)
        edge = float(e.get("e", 0.0) or 0.0)
        flag = (
            el("span", "PROVEN", cls="pflag")
            if tid in proven_ids
            else el("span", "on trial", cls="pill dim")
        )
        fit_cls = "up" if edge > 0 else "down" if edge < 0 else "muted"
        fit = (
            el("span", esc(f"{_fmt_edge(edge)} edge · {trades} tr"), cls=fit_cls)
            if trades
            else el("span", "no live trades yet", cls="muted")
        )
        rows.append(
            el(
                "li",
                el(
                    "div",
                    el("b", esc(tid)),
                    flag,
                    el("span", esc(f"w {w:.2f}"), cls="wpct"),
                    cls="loadtop",
                ),
                el("div", el("i", style=f"width:{min(100, w * 100):.0f}%"), cls="wbar"),
                el("div", fit, cls="loadsub"),
                cls="load",
            )
        )
    return el("ul", *rows, cls="loadout")


def books_html(state: dict[str, Any]) -> str:
    """PROOF — the three books: forge perps (live positions), event desk (calibration,
    honest n=0), carry floor. The honest PnL lives here, framed by the books."""
    cal_n = int((state["reputation"].get("event_calibration") or {}).get("n", 0) or 0)
    npos = len(state["positions"].get("positions") or [])
    return el(
        "div",
        el(
            "div",
            el("div", "A · FORGE PERPS", cls="bookhead"),
            positions_html(state),
            cls="book",
        ),
        el(
            "div",
            el("div", "B · EVENT DESK", cls="bookhead"),
            calibration_html(state),
            cls="book",
        ),
        el(
            "div",
            el("div", "C · CARRY FLOOR", cls="bookhead"),
            el(
                "p",
                esc(f"Δ-neutral funding harvest · {npos} perp open · {cal_n} event settles"),
                cls="muted",
            ),
            cls="book",
        ),
        cls="books",
    )


def onchain_html(state: dict[str, Any]) -> str:
    """PROOF — onchain identity + the reputation scorecard, with a verify link. The
    −$39.82 shown proudly as proof the reputation is real, not farmed."""
    ident = state["metabolism"].get("onchain_identity") or {}
    aid = ident.get("agentId")
    rep = state["reputation"]
    rec = track_record(rep, state["journal"])
    evo = rep.get("evolution") or {}
    trading = rep.get("trading") or {}
    verify = ident.get("agentUrl") or (
        f"https://basescan.org/nft/{IDENTITY_REGISTRY}/{aid}" if aid else GITHUB_URL
    )
    gas = state["gas"]
    gas_line = ""
    if gas.get("status"):
        gas_line = el(
            "div",
            esc(
                f"beacon gas: {gas.get('baseEth', 0):.5f} Base ETH · ~{gas.get('beaconRunway', 0)} beacons"
            ),
            cls="muted",
        )
    idrow = (
        el(
            "div",
            el("span", "ERC-8004", cls="pill"),
            esc(" agent "),
            el("b", esc(f"#{aid}")),
            esc(f" on {ident.get('chain', 'base:8453')}"),
            cls="idrow",
        )
        if aid
        else el("p", "No onchain identity yet.", cls="muted")
    )

    def score(label: str, val: str) -> str:
        return el("div", el("span", esc(label), cls="sclab"), el("b", esc(val)), cls="scoreitem")

    return el(
        "div",
        el("div", "// ACCOUNTABLE IDENTITY", cls="eyebrow"),
        idrow,
        el(
            "div",
            score("Settled PnL", _fmt_money(rec["pnl"])),
            score("Proven edge", str(evo.get("proven_edge_count", 0))),
            score("Self-authored", str(evo.get("self_authored_techniques", 0))),
            score("Win rate", f"{rec['win_rate'] * 100:.1f}% ({rec['closes']})"),
            score("Expectancy", _fmt_money(float(trading.get("expectancy_usd", 0) or 0))),
            score("Children", str(evo.get("children", 0))),
            cls="scoregrid",
        ),
        el("p", esc(rep.get("accountability", "")), cls="muted"),
        el("a", "verify on basescan ↗", cls="link", href=verify, target="_blank", rel="noopener"),
        gas_line,
        el("div", base_badge()),
        cls="section",
    )


def family_html(state: dict[str, Any]) -> str:
    """The lineage — each child shows its own bred DNA helix + a gene-diff."""
    children = state["metabolism"].get("children", [])
    if not children:
        return el(
            "p",
            "No offspring yet — at ≥2 proven edges (one new since last birth) the creature breeds, passing on its proven DNA.",
            cls="muted",
        )
    cells = []
    for c in children:
        cg = c.get("genome")
        helix = el("div", helix_svg(cg), cls="lhelix") if cg else ""
        meta = el("div", esc(f"{cg['species']} {cg['sigil']}"), cls="species") if cg else ""
        cells.append(
            el(
                "div",
                helix,
                el(
                    "div",
                    el("b", esc(c.get("name", "child"))),
                    el("span", esc(c.get("role", "—")), cls="pill"),
                    meta,
                    el("div", esc(str(c.get("mutation", ""))[:70]), cls="muted"),
                    cls="lmeta",
                ),
                cls="lcell",
            )
        )
    return el("div", *cells, cls="lineage")


# --------------------------------------------------------------------------- #
# Client-side scripts — self-contained JS embedded in the page. These are the
# "alive" layer: live PnL sync (kills the meta-refresh), the proven-DNA strand,
# the living lineage graph, and the shareable card composer.
# --------------------------------------------------------------------------- #
def live_sync_script(state: dict[str, Any]) -> str:
    """Live in-place updates — no full-page reload. Pulls live mark prices + spot
    balance from HyperLiquid's public API every 20s and recomputes equity + per-position
    PnL in the page. Degrades silently to the snapshot if the API is unreachable."""
    snap = state["positions"]
    addr = snap.get("managed") or ""
    if not addr:
        return ""
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
    )
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
        "var acct=Number((perp.marginSummary||{}).accountValue||0);"
        "var eq=freeSpot+acct;set('posEquity','$'+fmt(eq));"
        "var now='live \\u00b7 '+new Date().toUTCString().slice(17,25)+' UTC';set('posAsOf',now);"
        "document.querySelectorAll('.pos-pnl').forEach(function(el){var c=el.getAttribute('data-coin');"
        "if(c in live){var v=live[c];el.textContent=(v>=0?'+':'\\u2212')+'$'+fmt(v);"
        "el.style.color=v>=0?'var(--emerald)':'var(--red)';}});})"
        ".catch(function(){});}\n"
        "sync();setInterval(sync,20000);})();</script>"
    )


def dna_script(state: dict[str, Any], proven: list[dict[str, Any]]) -> str:
    """The 3D proven-DNA strand + the lineage graph + the shareable card data — all
    fed REAL proven-edge DNA (not a hash). Reuses the existing Three.js engine."""
    g = state["genome"]
    dna = proven_dna(state["style"])
    active = len(state["positions"].get("positions") or []) > 0
    graph = lineage_graph(state, proven)
    persona = state["persona"] or {}
    rec = track_record(state["reputation"], state["journal"])
    card = {
        "name": state["metabolism"].get("name") or g["species"],
        "species": g["species"],
        "archetype": persona.get("archetype", ""),
        "catchphrase": persona.get("catchphrase", ""),
        "proven": len(proven),
        "authored": int(
            (state["reputation"].get("evolution") or {}).get("self_authored_techniques", 0) or 0
        ),
        "record": f"{rec['closes']} closes · {_fmt_money(rec['pnl'])}",
        "fingerprint": g["fingerprint"],
    }
    payload = {
        "hue1": g["hue1"],
        "hue2": g["hue2"],
        "rungs": g["rungs"],
        "active": active,
        "dna": dna,
        "graph": graph,
    }
    return (
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>'
        f"<script>window.GCLAW_DNA={json.dumps(payload)};"
        f"window.GCLAW_CARD={json.dumps(card)};"
        f"window.GCLAW_QR={json.dumps(state['github_qr'])};</script>"
        + DNA3D_INIT
        + LINEAGE_JS
        + CARD_JS
    )


DNA3D_INIT = r"""<script>
(function(){
  if(!window.THREE){return;}
  var host=document.getElementById('dna3d'); if(!host) return;
  var W=host.clientWidth||230, H=300; host.textContent='';
  var d=window.GCLAW_DNA||{hue1:150,hue2:210,rungs:16,active:false,dna:[]};
  var pairs=(d.dna&&d.dna.length)?d.dna:null;
  var scene=new THREE.Scene();
  var cam=new THREE.PerspectiveCamera(36,W/H,0.1,100); cam.position.set(0,0,15.5);
  var rnd=new THREE.WebGLRenderer({alpha:true,antialias:true,preserveDrawingBuffer:true});
  rnd.setSize(W,H); rnd.setPixelRatio(Math.min(window.devicePixelRatio||1,2)); host.appendChild(rnd.domElement);
  function col(h){return new THREE.Color('hsl('+Math.round(h)+',72%,60%)');}
  var EMER=new THREE.Color(0x49B875), SLATE=new THREE.Color(0x4D5972), RED=new THREE.Color(0xDF2E2E);
  function pairColor(i){ if(!pairs) return i%2?col(d.hue1):col(d.hue2); var p=pairs[i%pairs.length]; if(p.proven) return EMER; return p.e<0?RED:SLATE; }
  function glowTex(){var c=document.createElement('canvas');c.width=c.height=64;var x=c.getContext('2d');var gr=x.createRadialGradient(32,32,0,32,32,32);gr.addColorStop(0,'rgba(255,255,255,1)');gr.addColorStop(0.3,'rgba(255,255,255,0.55)');gr.addColorStop(1,'rgba(255,255,255,0)');x.fillStyle=gr;x.fillRect(0,0,64,64);var t=new THREE.Texture(c);t.needsUpdate=true;return t;}
  var GT=glowTex(), glows=[];
  function node(x,y,z,c){var m=new THREE.Mesh(new THREE.SphereGeometry(0.30,18,18),new THREE.MeshStandardMaterial({color:c,emissive:c,emissiveIntensity:0.6,roughness:0.3,metalness:0.1}));m.position.set(x,y,z);return m;}
  function glow(x,y,z,c,on){var s=new THREE.Sprite(new THREE.SpriteMaterial({map:GT,color:c,blending:THREE.AdditiveBlending,transparent:true,opacity:on?0.6:0.25,depthWrite:false}));s.position.set(x,y,z);s.scale.set(1.6,1.6,1.6);s.userData.on=on;glows.push(s);return s;}
  function rung(a,b,c){var len=a.distanceTo(b);var m=new THREE.Mesh(new THREE.CylinderGeometry(0.055,0.055,len,8),new THREE.MeshStandardMaterial({color:c,emissive:c,emissiveIntensity:0.45,roughness:0.45,transparent:true,opacity:0.85}));m.position.copy(a.clone().add(b).multiplyScalar(0.5));m.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),b.clone().sub(a).normalize());return m;}
  var g=new THREE.Group();
  var N=pairs?Math.max(6,Math.min(30,pairs.length)):Math.max(10,Math.min(30,d.rungs||16)), turns=2.7, R=2.2, span=8.0;
  for(var i=0;i<N;i++){
    var t=i/(N-1), ang=t*turns*Math.PI*2, y=(t-0.5)*span;
    var a=new THREE.Vector3(Math.cos(ang)*R,y,Math.sin(ang)*R);
    var b=new THREE.Vector3(Math.cos(ang+Math.PI)*R,y,Math.sin(ang+Math.PI)*R);
    var c=pairColor(i), on=pairs?!!pairs[i%pairs.length].proven:true;
    g.add(node(a.x,a.y,a.z,c)); g.add(node(b.x,b.y,b.z,c)); g.add(rung(a,b,c));
    g.add(glow(a.x,a.y,a.z,c,on)); g.add(glow(b.x,b.y,b.z,c,on));
  }
  scene.add(g);
  scene.add(new THREE.AmbientLight(0xffffff,0.5));
  var l1=new THREE.PointLight(0x9affc4,0.9); l1.position.set(6,5,10); scene.add(l1);
  var l2=new THREE.PointLight(0x61b8ff,0.6); l2.position.set(-6,-4,7); scene.add(l2);
  window.addEventListener('resize',function(){var w=host.clientWidth||W; rnd.setSize(w,H); cam.aspect=w/H; cam.updateProjectionMatrix();});
  (function loop(){
    requestAnimationFrame(loop);
    if(host.offsetParent===null) return;
    var now=Date.now();
    g.rotation.y += d.active?0.020:0.011;
    g.rotation.x = Math.sin(now/2600)*0.13;
    var pulse = 0.5 + 0.5*Math.sin(now/950);
    for(var k=0;k<glows.length;k++){ var base=glows[k].userData.on?0.85:0.32; glows[k].material.opacity = (glows[k].userData.on?0.4:0.18) + pulse*base*0.4; }
    rnd.render(scene,cam);
  })();
})();
</script>"""


LINEAGE_JS = r"""<script>
(function(){
  var host=document.getElementById('lineageGraph'); if(!host) return;
  var G=(window.GCLAW_DNA||{}).graph||{draft:[],judged:[],proven:[],inherited:[]};
  var W=host.clientWidth||360, H=200, dpr=Math.min(window.devicePixelRatio||1,2);
  var cv=document.createElement('canvas'); cv.width=W*dpr; cv.height=H*dpr; cv.style.width=W+'px'; cv.style.height=H+'px';
  host.appendChild(cv); var x=cv.getContext('2d'); x.scale(dpr,dpr);
  var cols=[['DRAFT',G.draft,'#697083'],['JUDGED',G.judged,'#61B8FF'],['PROVEN',G.proven,'#49B875'],['INHERITED',G.inherited,'#704FF6']];
  var motes=[]; for(var m=0;m<24;m++) motes.push({x:Math.random()*W,y:Math.random()*H,s:0.15+Math.random()*0.35});
  function draw(){
    x.clearRect(0,0,W,H);
    var cw=W/4;
    for(var m2=0;m2<motes.length;m2++){var mo=motes[m2]; mo.x+=mo.s; if(mo.x>W)mo.x=0; x.fillStyle='rgba(161,165,179,0.10)'; x.beginPath(); x.arc(mo.x,mo.y,1,0,7); x.fill();}
    for(var c=0;c<cols.length;c++){
      var cx=cw*c+cw/2, items=cols[c][1]||[], color=cols[c][2];
      x.fillStyle='#4D5972'; x.font='600 9px Inter'; x.textAlign='center'; x.fillText(cols[c][0], cx, 18);
      var n=Math.max(1,items.length);
      for(var i=0;i<items.length;i++){
        var cy=44+(i+0.5)*((H-56)/n), r=(c===2)?6:4;
        var pulse=(c===2)?(0.7+0.3*Math.sin(Date.now()/600+i)):1;
        x.beginPath(); x.arc(cx,cy,r*pulse,0,7); x.fillStyle=color; x.globalAlpha=(c===0)?0.5:1; x.fill(); x.globalAlpha=1;
        x.fillStyle='#81899F'; x.font='400 8px Inter';
        var lbl=(items[i].id||items[i].name||''); if(lbl.length>14)lbl=lbl.slice(0,13)+'…';
        x.fillText(lbl, cx, cy+r+9);
      }
      if(items.length===0){ x.fillStyle='#2E4164'; x.font='400 8px Inter'; x.fillText('—', cx, H/2); }
    }
    requestAnimationFrame(draw);
  }
  draw();
})();
</script>"""


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
    x.fillStyle='#697083'; x.font='600 15px Inter'; x.fillText('PROVEN EDGE', tx, 300);
    x.fillStyle='#49B875'; x.font='800 58px Inter'; x.fillText((c.proven||0)+' graduated', tx, 358);
    var lab='✓ VERIFIABLE ON BASE'; x.font='700 14px Inter'; var pw=x.measureText(lab).width+26;
    x.fillStyle='#49B875'; rr(x,tx,378,pw,30,8); x.fill(); x.fillStyle='#060A17'; x.fillText(lab, tx+13, 398);
    x.fillStyle='#D5D9E1'; x.font='600 22px Inter'; x.fillText((c.authored||0)+' authored    ·    '+(c.record||''), tx, 466);
    if(c.catchphrase){ x.fillStyle='#81899F'; x.font='italic 500 21px Inter'; x.fillText('“'+c.catchphrase+'”', tx, 508); }
    x.fillStyle='#A1A5B3'; x.font='700 18px Inter'; x.fillText('//GEMACH', tx, H-66);
    x.fillStyle='#4D5972'; x.font='400 14px Inter'; x.fillText('a mind that must prove edge to survive · genome '+c.fingerprint, tx, H-42);
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


# --------------------------------------------------------------------------- #
# PAGE — the shell CSS + assembly. render(state) is a pure function of state.
# --------------------------------------------------------------------------- #
PAGE_CSS = """
:root{--bg:#060A17;--card:#152037;--ink:#FFFFFF;--line:rgba(161,165,179,.10);
--emerald:#49B875;--blue:#61B8FF;--purple:#704FF6;--red:#DF2E2E;
--slate:#697083;--slate2:#81899F;--silver:#A1A5B3;--silver2:#D5D9E1;
--s1:8px;--s2:16px;--s3:24px;--s4:32px}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--silver2);
font:15px/1.6 'Inter',-apple-system,system-ui,sans-serif;letter-spacing:.1px}
.page{max-width:960px;margin:0 auto;padding:var(--s4) var(--s3)}
a{color:var(--emerald);text-decoration:none}a:hover{color:var(--ink)}
.eyebrow{font:600 11px/1 'Inter';letter-spacing:2.5px;text-transform:uppercase;color:var(--slate);margin:0 0 var(--s2)}
.hairline{height:1px;background:var(--line);margin:var(--s3) 0;border:0}
.muted{color:var(--slate);font-size:13px}
.header{display:flex;align-items:center;justify-content:space-between;gap:var(--s2);padding-bottom:var(--s2);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:12px}.lionmark{color:var(--emerald);display:inline-flex}
.brandtext{line-height:1.2}.brandtext .name{font:800 18px 'Inter';color:var(--ink);letter-spacing:.3px}
.brandtext .sub{color:var(--slate);font-size:12px}
.headright{display:flex;align-items:center;gap:14px}
.livedot{color:var(--emerald);font-size:12px;font-weight:600;letter-spacing:.5px}
.livedot::before{content:"● ";animation:pulse 2.4s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.sharebtn{border:1px solid var(--line);color:var(--silver);border-radius:999px;padding:6px 13px;font-size:12px;font-weight:600}
.sharebtn:hover{border-color:var(--silver);color:var(--ink)}
/* GLANCE */
.hero{margin:var(--s4) 0 var(--s3)}
.herorow{display:flex;align-items:center;gap:var(--s3);flex-wrap:wrap}
.heronum{font:900 84px/1 'Inter';color:var(--emerald);font-variant-numeric:tabular-nums;letter-spacing:-2px}
.herometa{display:flex;flex-direction:column;gap:6px}
.herolabel{font:700 20px 'Inter';color:var(--ink)}
.herodelta{color:var(--emerald);font-size:13px;font-weight:600}
.herosub{color:var(--slate2);font-style:italic;margin-top:10px;font-size:14px}
.ribbon{display:inline-block;background:rgba(73,184,117,.14);border:1px solid var(--emerald);color:var(--emerald);
border-radius:999px;padding:3px 12px;font:700 12px 'Inter';letter-spacing:1px;width:fit-content}
.vitals{display:grid;grid-template-columns:repeat(3,1fr);gap:var(--s3);margin:var(--s3) 0}
.vlabel{font:600 10px 'Inter';letter-spacing:1.6px;text-transform:uppercase;color:var(--slate);margin-bottom:6px}
.vval{font:700 22px 'Inter';color:var(--silver2);font-variant-numeric:tabular-nums;line-height:1}
.vval.em{color:var(--emerald)}.vsub{color:var(--slate);font-size:12px;margin-top:4px}
.trackrec{display:flex;gap:14px;align-items:baseline;flex-wrap:wrap;padding-top:var(--s2);border-top:1px solid var(--line);font-variant-numeric:tabular-nums}
.trhead{font:600 10px 'Inter';letter-spacing:1.6px;color:var(--slate)}
.trbody{color:var(--slate2);font-size:14px}.trpnl{color:var(--slate2);font-weight:700}
.trlink{color:var(--emerald)}.trslate{color:var(--slate)}
/* SUBSTANCE */
.section{margin:var(--s4) 0}
.benchhead{margin:-8px 0 12px}
.bench{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:2px}
.benchrow{padding:12px 0;border-bottom:1px solid var(--line)}
.benchtop{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.authtag{font:600 10px 'Inter';letter-spacing:1px;color:var(--slate)}
.authid{color:var(--ink);font-weight:700}
.benchclaim{color:var(--slate2);font-size:13px;margin-top:6px;font-style:italic}
.vd{font:600 11px 'Inter';letter-spacing:.5px;border-radius:999px;padding:2px 10px}
.vd.proven{background:rgba(73,184,117,.14);color:var(--emerald)}
.vd.judging{background:rgba(97,184,255,.12);color:var(--blue);animation:pulse 1.8s ease-in-out infinite}
.vd.rejected{background:rgba(105,112,131,.14);color:var(--slate2)}
.provenlist{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:2px}
.provenrow{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--line);font-size:14px;flex-wrap:wrap}
.provenrow.dim{color:var(--slate)}
.pdot{color:var(--emerald)}.pdot.dim{color:var(--slate)}
.pname{color:var(--ink)}
.pflag{font:700 10px 'Inter';letter-spacing:1px;color:var(--emerald);background:rgba(73,184,117,.12);border-radius:999px;padding:2px 9px}
.pedge{color:var(--silver2);font-variant-numeric:tabular-nums}
.oosstar{color:var(--blue);font-size:12px;font-variant-numeric:tabular-nums}
.gridtwo{display:grid;grid-template-columns:1fr 1fr;gap:var(--s3)}
.dna3d{min-height:300px;display:flex;align-items:center;justify-content:center;overflow:hidden}.dna3d canvas{display:block}
#lineageGraph{width:100%;min-height:200px}
.calrow{display:flex;gap:var(--s2);align-items:center}.calsvg{flex:0 0 auto}
.gatelist{list-style:none;margin:0 0 8px;padding:0}
.gaterow{display:flex;align-items:center;gap:10px;padding:8px 0;font-size:14px}
.gcheck{width:20px;height:20px;flex:0 0 20px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;
font-size:11px;border:1px solid var(--line);color:var(--slate)}
.gcheck.ok{background:var(--emerald);border-color:var(--emerald);color:#06210f}
/* PROOF */
details{border-top:1px solid var(--line);padding:var(--s2) 0}
details>summary{cursor:pointer;font:600 11px 'Inter';letter-spacing:2.5px;text-transform:uppercase;color:var(--slate);list-style:none}
details>summary::-webkit-details-marker{display:none}
details[open]>summary{color:var(--silver)}
details>summary::before{content:"▸ ";color:var(--slate)}details[open]>summary::before{content:"▾ "}
.books{display:grid;grid-template-columns:repeat(3,1fr);gap:var(--s3);margin-top:var(--s2)}
.book{border:1px solid var(--line);border-radius:12px;padding:var(--s2)}
.bookhead{font:600 11px 'Inter';letter-spacing:1.6px;color:var(--slate2);margin-bottom:10px}
.book .eyebrow{font-size:9px;margin-bottom:8px}
.scoregrid{display:grid;grid-template-columns:repeat(3,1fr);gap:var(--s2);margin:var(--s2) 0}
.scoreitem{display:flex;flex-direction:column;gap:3px}
.sclab{font:600 10px 'Inter';letter-spacing:1px;color:var(--slate)}
.scoreitem b{font:700 18px 'Inter';color:var(--silver2);font-variant-numeric:tabular-nums}
.idrow{font-size:15px;margin-bottom:8px}
.pill{display:inline-block;background:#16243f;color:var(--blue);padding:1px 8px;border-radius:999px;font-size:11px;margin-right:6px}
.pill.dim{background:#0c1424;color:var(--slate)}
.loadout{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:13px}
.load .loadtop{display:flex;align-items:center;gap:8px}.load .loadtop b{color:var(--ink);font-size:14px}
.load .wpct{margin-left:auto;font-variant-numeric:tabular-nums;color:var(--silver);font-size:13px}
.wbar{height:5px;background:#16243f;border-radius:999px;overflow:hidden;margin:6px 0 5px}
.wbar i{display:block;height:100%;background:var(--emerald);border-radius:999px}
.loadsub{font-size:12px}.loadsub .up{color:var(--emerald)}.loadsub .down{color:var(--red)}
.events{list-style:none;margin:0;padding:0}.events li{padding:7px 0;border-bottom:1px solid var(--line);font-size:13px}
.poshead{margin-bottom:8px}
.lineage{display:flex;flex-direction:column;gap:12px}
.lcell{display:flex;gap:12px;align-items:center;padding:10px;border:1px solid var(--line);border-radius:12px;background:#10182b}
.lhelix{flex:0 0 auto;width:64px}.lhelix svg{width:64px;height:auto;display:block}
.lmeta{flex:1;min-width:0}.lmeta .species{color:var(--slate);font-size:11px;letter-spacing:1.5px;text-transform:uppercase;margin:3px 0 6px}
.link{display:inline-block;margin-top:10px;color:var(--blue);font-size:12px}
.basebadge{display:inline-flex;align-items:center;gap:7px;margin-top:14px;padding:6px 12px;border:1px solid var(--line);border-radius:999px;font-size:10px;letter-spacing:1.5px;color:var(--silver);font-weight:600}
.watermark{position:fixed;right:-60px;bottom:-40px;color:rgba(161,165,179,.03);z-index:-1;pointer-events:none}
.foot{text-align:center;color:var(--slate);font-size:11px;margin-top:var(--s4);padding-top:var(--s3);border-top:1px solid var(--line)}
.foot .lionmark{color:var(--slate);vertical-align:middle}
@media(max-width:720px){.vitals,.books,.scoregrid,.gridtwo{grid-template-columns:1fr}.heronum{font-size:60px}}
"""


def _header_html(state: dict[str, Any], proven: list[dict[str, Any]]) -> str:
    """The brand header — lion mark, name/species/agent-id, live heartbeat, share links."""
    g, metabolism = state["genome"], state["metabolism"]
    name = metabolism.get("name") or g["species"]
    mode = metabolism.get("mode", "unknown").upper()
    hb = int(metabolism.get("heartbeats", 0) or 0)
    aid = (metabolism.get("onchain_identity") or {}).get("agentId", "—")
    return el(
        "header",
        el(
            "div",
            el("span", lion("30px"), cls="lionmark"),
            el(
                "div",
                el("div", esc(f"{g['sigil']} {name}"), cls="name"),
                el("div", esc(f"// GEMACH · {g['species']} · agent #{aid}"), cls="sub"),
                cls="brandtext",
            ),
            cls="brand",
        ),
        el(
            "div",
            el("span", esc(f"{mode} · heartbeat {hb}"), cls="livedot"),
            el(
                "a",
                "𝕏 Share",
                cls="sharebtn",
                href=share_url(metabolism, name, len(proven)),
                target="_blank",
                rel="noopener",
            ),
            el("a", "Leaderboard ↗", cls="sharebtn", href="leaderboard.html"),
            cls="headright",
        ),
        cls="header",
    )


def _substance_html(
    state: dict[str, Any], proven: list[dict[str, Any]], gate: dict[str, Any]
) -> str:
    """SUBSTANCE — the beating heart: bench, proven techniques, proven-DNA helix +
    lineage graph, calibration + the reproduction gate."""
    helix_col = el(
        "div",
        el("div", "// PROVEN DNA", cls="eyebrow"),
        el("div", helix_svg(state["genome"]), cls="dna3d", id="dna3d"),
    )
    graph_col = el(
        "div",
        el("div", "// LINEAGE GRAPH", cls="eyebrow"),
        el("div", "", id="lineageGraph"),
        el("p", "draft → judged → proven → inherited", cls="muted"),
    )
    return (
        bench_html(state)
        + '<hr class="hairline">'
        + proven_tech_html(state, proven)
        + el("div", helix_col, graph_col, cls="gridtwo section")
        + el("div", calibration_html(state), breed_gate_html(gate), cls="gridtwo section")
    )


def _proof_html(state: dict[str, Any]) -> str:
    """PROOF — collapsed below the fold: the three books, full loadout, lineage, and
    the onchain identity + reputation scorecard."""
    return (
        el("details", el("summary", "// THE THREE BOOKS"), books_html(state))
        + el(
            "details",
            el("summary", "// FULL LOADOUT · every adopted technique"),
            techniques_html(state),
        )
        + el("details", el("summary", "// LINEAGE · children & inheritance"), family_html(state))
        + el("details", el("summary", "// ONCHAIN IDENTITY & SCORECARD"), onchain_html(state))
    )


def render(state: dict[str, Any]) -> str:
    """Render the whole page as safe HTML — a PURE function of the state dict.

    No I/O, no network, no subprocess: every value comes from ``state`` (gathered by
    :func:`refresh`) and flows through the autoescaping :func:`el` / :func:`esc`
    helpers. This is the unit-testable core — the point of the refresh/render split.
    """
    g = state["genome"]
    name = state["metabolism"].get("name") or g["species"]
    proven = proven_edge(state["style"])
    gate = breed_gate(state, proven)

    glance = hero_html(state, proven, gate) + vitals_html(state, gate) + track_record_html(state)
    foot = el(
        "div",
        el("span", lion("14px"), cls="lionmark"),
        esc(
            f" //GEMACH · a mind that must prove edge to survive · rendered {datetime.now(UTC).isoformat(timespec='seconds')}"
        ),
        cls="foot",
    )
    scripts = live_sync_script(state) + dna_script(state, proven)
    body = el(
        "div",
        _header_html(state, proven),
        glance,
        '<hr class="hairline">',
        _substance_html(state, proven, gate),
        _proof_html(state),
        foot,
        el("span", lion("520px"), cls="watermark"),
        cls="page",
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{esc(name)} · {esc(g['species'])} · PROVEN EDGE {len(proven)}</title>"
        '<meta property="og:type" content="website">'
        f'<meta property="og:title" content="{esc(name)} · self-evolving trading organism">'
        f'<meta property="og:description" content="PROVEN EDGE {len(proven)} — a living onchain '
        'agent that authors its own trading strategies; reputation is settled PnL, re-derivable on Base.">'
        '<meta property="og:image" content="og-card.jpg">'
        '<meta name="twitter:card" content="summary_large_image">'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@100..900&display=swap" rel="stylesheet">'
        f"<style>{PAGE_CSS}</style></head><body>{body}{scripts}</body></html>"
    )


def render_html(
    state: dict[str, Any],
    identity: str = "",
    journal: list | None = None,
    messages: list | None = None,
) -> str:
    """Back-compat shim: accept a bare metabolism dict (as the old tests do) and wrap
    it into the full state the pure :func:`render` needs, reading the rest from home."""
    if "metabolism" in state and "genome" in state:
        return render(state)
    metabolism = state
    h = home()
    style = load_json(h / "forge" / "style.json", {})
    full: dict[str, Any] = {
        "metabolism": metabolism,
        "genome": genome("Gclaw", metabolism.get("born_at", "genesis")),
        "reputation": load_json(h / "reputation.json", {}),
        "style": style,
        "proven_markets": load_json(h / "forge" / "proven_markets.json", {}).get("pairs", []),
        "techniques": _load_techniques(h, style.get("adopted", [])),
        "authored_cards": _load_authored(
            h, (metabolism.get("onchain_identity") or {}).get("agentId", "")
        ),
        "journal": journal if journal is not None else read_jsonl(h / "journal.jsonl"),
        "telepathy": messages
        if messages is not None
        else read_jsonl(h / "telepathy" / "bus.jsonl"),
        "positions": load_json(h / "positions.json", {}),
        "gas": load_json(h / "gas.json", {}),
        "leaderboard": load_json(h / "leaderboard.json", {}),
        "persona": load_json(h / "dna" / "persona.json", {}),
        "github_qr": "",
        "topup_qr": "",
        "banner": "",
        "hero_bg": "",
    }
    return render(full)


def cmd_render(args: argparse.Namespace) -> None:
    h = home()
    state = refresh(h, live=not getattr(args, "no_live", False))
    out = Path(args.out) if args.out else h / "dashboard.html"
    out.write_text(render(state), encoding="utf-8")
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
