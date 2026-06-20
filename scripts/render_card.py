#!/usr/bin/env python3
"""Render a shareable creature trading-card PNG (helix avatar + soul + traits).

A marketing/sharing tool, not part of the runtime. Pillow is pulled on the fly:

    uv run --with pillow --no-project python3 scripts/render_card.py --name Gclaw --out assets/zephlith.png

The card art is derived from the creature's genome, so it matches its DNA and soul
everywhere else.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont  # type: ignore[import-not-found]

sys.path.insert(0, str(Path(__file__).resolve().parent))
import persona as persona_mod

W, H = 620, 360
BG = (11, 16, 32)
CARD = (20, 27, 46)
INK = (231, 236, 246)
MUTED = (138, 150, 179)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = (
        ["DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold
        else ["DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def hsl(h: float, s: float, light: float) -> tuple[int, int, int]:
    c = (1 - abs(2 * light - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = light - c / 2
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
    return tuple(round((v + m) * 255) for v in (r, g, b))


def draw_helix(d: ImageDraw.ImageDraw, fp: str, cx: int, top: int, bottom: int) -> None:
    by = lambda i: int(fp[i * 2 : i * 2 + 2], 16)  # noqa: E731
    hue1, hue2, rungs = (
        by(0) / 255 * 360,
        (by(0) / 255 * 360 + 90 + by(1) / 255 * 120) % 360,
        16 + by(5) % 10,
    )
    c1, c2 = hsl(hue1, 0.75, 0.6), hsl(hue2, 0.75, 0.6)
    for i in range(rungs):
        t = i / (rungs - 1)
        y = top + t * (bottom - top)
        ph = t * math.pi * 4
        x1, x2 = cx + math.sin(ph) * 60, cx + math.sin(ph + math.pi) * 60
        d.line([(x1, y), (x2, y)], fill=(c1 if math.sin(ph) >= 0 else c2), width=2)
        d.ellipse([x1 - 4, y - 4, x1 + 4, y + 4], fill=c1)
        d.ellipse([x2 - 4, y - 4, x2 + 4, y + 4], fill=c2)


def render(name: str, out: Path) -> None:
    p = persona_mod.persona(name, persona_mod.creature_born_at(name, name != "Gclaw"))
    fp = p["fingerprint"]
    hue = int(fp[0:2], 16) / 255 * 360

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        [12, 12, W - 12, H - 12], radius=20, fill=CARD, outline=(36, 48, 73), width=1
    )
    draw_helix(d, fp, 110, 50, H - 50)

    x = 210
    d.text(
        (x, 40), p["species"].upper() + "  ·  " + p["archetype"].upper(), font=font(13), fill=MUTED
    )
    d.text((x, 60), name, font=font(34, bold=True), fill=INK)
    d.text((x, 104), f"“{p['catchphrase']}”", font=font(15), fill=hsl(hue, 0.7, 0.7))

    ty = 150
    for trait, val in p["traits"].items():
        d.text((x, ty), trait, font=font(13), fill=MUTED)
        d.rounded_rectangle([x + 96, ty + 3, x + 96 + 230, ty + 12], radius=5, fill=(12, 19, 34))
        d.rounded_rectangle(
            [x + 96, ty + 3, x + 96 + int(230 * val / 100), ty + 12],
            radius=5,
            fill=hsl(hue, 0.7, 0.55),
        )
        d.text((x + 334, ty), str(val), font=font(13, bold=True), fill=INK)
        ty += 26

    d.text((x, H - 54), f"genome {fp}  ·  ERC-8004 on Base", font=font(12), fill=MUTED)
    d.text((x, H - 36), "Gclaw — a living, onchain trading creature", font=font(12), fill=MUTED)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"card → {out}  ({name} · {p['archetype']})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="Gclaw")
    ap.add_argument("--out", default="assets/creature.png")
    a = ap.parse_args()
    render(a.name, Path(a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
