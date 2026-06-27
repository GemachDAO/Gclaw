"""Pin the heartbeat's anti-drain deny-list so it can't silently erode.

The unattended heartbeat runs under bypassPermissions and reads untrusted text, so a
gap in the deny-list is a real drain surface. This parses the DENY set straight out of
heartbeat.sh and asserts every fund-moving / order-placing / account-mutating GDEX tool
is present. Adding such a tool to the GDEX MCP without denying it here fails the build.
"""

from __future__ import annotations

import re
from pathlib import Path

HEARTBEAT = Path(__file__).resolve().parent.parent / "scripts" / "heartbeat.sh"

# Every GDEX tool that moves funds, opens/increases risk, places an order, spends, or
# mutates the account. Risk-REDUCING tools (close_*/cancel_*) and reads are intentionally
# absent — they stay reachable so the model can always de-risk.
REQUIRED_DENIED = {
    "transfer_native",
    "transfer_token",
    "execute_bridge",
    "perp_withdraw",
    "perp_deposit",
    "hl_swap_collateral",
    "managed_sell",
    "sell_token",
    "buy_token",
    "managed_purchase",
    "execute_spot",
    "execute_cross_perp",
    "execute_isolated_perp",
    "open_perp_position",
    "place_perp_order",
    "limit_buy",
    "limit_sell",
    "hl_create_outcome_order",
    "create_copy_trade",
    "create_hl_copy_trade",
    "update_copy_trade",
    "update_hl_copy_trade",
    "trending_register",
    "associate_email",
}


def _denied_tools() -> set[str]:
    text = HEARTBEAT.read_text(encoding="utf-8")
    match = re.search(r'DENY="([^"]*)"', text)
    assert match, "DENY=... assignment not found in heartbeat.sh"
    return {
        t.removeprefix("mcp__gdex__") for t in match.group(1).split() if t.startswith("mcp__gdex__")
    }


def test_every_dangerous_tool_is_denied():
    missing = REQUIRED_DENIED - _denied_tools()
    assert not missing, f"deny-list is missing dangerous GDEX tools: {sorted(missing)}"


def test_denylist_does_not_block_derisking():
    # closing/cancelling must stay reachable so the model can always reduce exposure.
    denied = _denied_tools()
    for derisk in ("close_perp_position", "close_all_positions", "cancel_perp_order"):
        assert derisk not in denied, f"{derisk} must NOT be denied — it reduces risk"
