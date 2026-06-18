#!/usr/bin/env python3
"""Generate a self-contained SVG QR for funding a wallet.

Run via uv so the (pure-Python, generation-only) encoder is available:

    uv run --no-project --with qrcode python3 qr.py <address> <chainId> <out.svg>

Encodes an EIP-681 URI (``ethereum:<addr>@<chainId>``) so a phone wallet
prefills the recipient and chain. Idempotent — skips if the output exists, so
the dashboard can call it every render for ~free. The cached SVG embeds offline;
the dependency is needed only when (re)generating.
"""
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: qr.py <address> <chainId> <out.svg>")
    addr, chain, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    if out.exists() and out.stat().st_size > 0:
        print(str(out))
        return
    import qrcode
    import qrcode.image.svg

    uri = f"ethereum:{addr}@{chain}"
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out))
    print(str(out))


main()
