#!/usr/bin/env python3
"""tool_budget — is the GDEX MCP read surface economical with the model's context?

The LLM cycle reads market/account state through the mcp__gdex__* tools, and a single
unbounded tool result can consume a large fraction of the context window on low-signal
data. This eval checks the read tools for context hygiene:

  * get_hl_trade_history is bounded (a `limit` param) — it once dumped the entire
    lifetime fill history (~90KB) and overflowed the context.
  * handleToolCall serializes compact (no 2-space indent tax) and flags failures with
    isError so the model can branch instead of string-matching.
  * get_hl_meta_and_asset_ctxs can be filtered to the coins in play, not all ~231 assets.

It also quantifies the trade_history saving empirically from a real fills fixture.

Reads the GDEX MCP source at $GDEX_SKILL_DIR (default ~/gdex-skill). Run:
  uv run --no-project python3 evals/tool_budget.py
Exit: 0 if the critical hygiene checks pass, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

GDEX = Path(os.environ.get("GDEX_SKILL_DIR", str(Path.home() / "gdex-skill")))
SRC = GDEX / "mcp-server" / "src"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CHARS_PER_TOKEN = 4  # rough GPT-style estimate, good enough for an order-of-magnitude gauge


def _read(rel: str) -> str:
    path = SRC / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _tool_block(src: str, name: str) -> str:
    """Return the server.tool('<name>', …) block, up to the next tool registration."""
    start = src.find(f"'{name}'")
    if start < 0:
        return ""
    nxt = src.find("server.tool(", start + 1)
    return src[start : nxt if nxt > 0 else len(src)]


def checks() -> list[dict[str, object]]:
    """Static context-hygiene checks against the GDEX MCP source."""
    perp_read = _read("tools/perpRead.ts")
    sdk = _read("sdk.ts")
    hl_copy = _read("tools/hlCopyTrade.ts")
    hist = _tool_block(perp_read, "get_hl_trade_history")
    ctxs = _tool_block(hl_copy, "get_hl_meta_and_asset_ctxs")
    return [
        {"tool": "get_hl_trade_history", "check": "bounded by a limit param",
         "ok": "limit" in hist, "critical": True},
        {"tool": "handleToolCall", "check": "compact JSON (no 2-space indent tax)",
         "ok": bool(sdk) and "null, 2" not in sdk, "critical": True},
        {"tool": "handleToolCall", "check": "failures set isError for branching",
         "ok": "isError" in sdk, "critical": True},
        {"tool": "get_hl_meta_and_asset_ctxs", "check": "filterable to specific coins",
         "ok": bool(re.search(r"coins?\s*:", ctxs)), "critical": False},
    ]


def empirical() -> dict[str, float]:
    """Quantify the trade_history saving from a real fills fixture (unbounded vs limit=20)."""
    f = FIXTURES / "fills.json"
    if not f.exists():
        return {}
    fills = json.loads(f.read_text(encoding="utf-8"))
    full = len(json.dumps(fills))
    bounded = len(json.dumps(fills[:20]))
    return {
        "n_fills": len(fills),
        "full_tokens": full / CHARS_PER_TOKEN,
        "bounded_tokens": bounded / CHARS_PER_TOKEN,
        "saved_tokens": (full - bounded) / CHARS_PER_TOKEN,
    }


def main() -> int:
    if not SRC.exists():
        print(f"GDEX MCP source not found at {SRC} — set GDEX_SKILL_DIR", file=sys.stderr)
        return 1
    rows = checks()
    print("=" * 62)
    print("tool_budget — GDEX MCP read-surface context hygiene")
    print("=" * 62)
    print(f"{'tool':<28}{'check':<34}{'':>0}")
    for r in rows:
        mark = "PASS" if r["ok"] else ("FAIL" if r["critical"] else "warn")
        print(f"{r['tool']:<28}{r['check']:<34}{mark}")

    emp = empirical()
    if emp:
        print(f"\ntrade_history on {int(emp['n_fills'])} real fills:")
        print(f"  unbounded ~{emp['full_tokens']:,.0f} tok  ->  limit=20 ~{emp['bounded_tokens']:,.0f} tok"
              f"  (saves ~{emp['saved_tokens']:,.0f} tok/call)")

    critical_fail = [r for r in rows if r["critical"] and not r["ok"]]
    warns = [r for r in rows if not r["critical"] and not r["ok"]]
    if warns:
        print(f"\nremaining (non-critical): {', '.join(f'{r['tool']} — {r['check']}' for r in warns)}")
    verdict = "PASS" if not critical_fail else "FAIL"
    print(f"\nVERDICT: {verdict}  ({len(critical_fail)} critical hygiene failures)")
    return 0 if not critical_fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
