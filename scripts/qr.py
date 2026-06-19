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
        raise SystemExit("usage: qr.py <data> <chainId|raw> <out.(svg|png)>")
    data, chain, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    if out.exists() and out.stat().st_size > 0:
        print(str(out))
        return
    import qrcode

    payload = data if chain == "raw" else f"ethereum:{data}@{chain}"  # raw URL, else EIP-681
    out.parent.mkdir(parents=True, exist_ok=True)
    if str(out).endswith(".png"):
        qrcode.make(payload, box_size=10, border=2).save(str(out))  # raster (needs pillow)
    else:
        import qrcode.image.svg
        img = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
        img.save(str(out))
    print(str(out))


main()
