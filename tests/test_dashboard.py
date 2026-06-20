"""Dashboard rendering — the page a human (and Blaq) actually opens.

The render functions are pure reads of ``$GCLAW_HOME`` state, so we exercise them
against seeded states (healthy / flat / positions / hibernate) and assert the page
renders fully — no crash, the key panels present, and the live hooks + equity wired
the way the recent fixes require (snap['equity'], clean sigils, the leaderboard link,
the live-sync script). ``cmd_render --no-live`` is the heartbeat's terminal step, so a
test that it writes a valid page is an end-to-end check of "the heartbeat produces a
dashboard."
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import dashboard


def _write(home: Path, name: str, obj: object) -> None:
    p = home / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def test_render_html_produces_a_full_page(metabolism_fixture, gclaw_home):
    state = metabolism_fixture()
    html = dashboard.render_html(state, "", [], [])
    assert "<html" in html.lower()
    assert "</html>" in html.lower()
    assert len(html) > 2000  # a real page, not a stub
    # render_html fills every named {slot}; a missing one would have raised KeyError.


def test_renders_across_life_modes(metabolism_fixture, gclaw_home):
    # thrive (healthy), survive (below threshold), hibernate (depleted) all render.
    for gmac, mode in [(1000.0, "THRIVE"), (40.0, "SURVIVE"), (0.0, "HIBERNATE")]:
        state = metabolism_fixture(gmac_balance=gmac, mode=mode.lower())
        html = dashboard.render_html(state, "", [], [])
        assert mode in html


def test_vitals_shows_equity_with_live_ids(metabolism_fixture, gclaw_home):
    metabolism_fixture()
    _write(gclaw_home, "positions.json", {"equity": 202.63, "positions": []})
    out = dashboard.vitals_html({"goodwill": 5, "heartbeats": 3}, gclaw_home)
    assert "202.63" in out
    assert 'id="liveEquity"' in out  # the client-side sync target
    assert 'id="liveUpnl"' in out


def test_equity_uses_snap_equity_not_accountvalue(metabolism_fixture, gclaw_home):
    # Regression for the funds-display bug: equity must come from snap['equity']
    # (already (spot-hold)+accountValue), never the raw perp accountValue.
    metabolism_fixture()
    _write(gclaw_home, "positions.json", {"equity": 202.63, "accountValue": 103.0, "positions": []})
    out = dashboard.vitals_html({}, gclaw_home)
    assert "202.63" in out
    assert "103.0" not in out


def test_positions_panel_flat_then_open(metabolism_fixture, gclaw_home):
    _write(gclaw_home, "positions.json", {"equity": 50.0, "positions": []})
    flat = dashboard.positions_html(gclaw_home)
    assert "Flat" in flat

    _write(
        gclaw_home,
        "positions.json",
        {
            "equity": 50.0,
            "managed": "0xabc",
            "positions": [
                {
                    "coin": "ETH",
                    "size": -0.1,
                    "entryPx": 1700,
                    "unrealizedPnl": -2.18,
                    "liquidationPx": 3386,
                }
            ],
        },
    )
    open_panel = dashboard.positions_html(gclaw_home)
    assert "ETH" in open_panel
    assert 'data-coin="ETH"' in open_panel  # the per-row live hook
    assert 'id="posEquity"' in open_panel
    assert 'id="posAsOf"' in open_panel


def test_arsenal_panel_reflects_loadout(forge_style, gclaw_home):
    forge_style(
        adopted=[
            {
                "id": "funding-fade",
                "coin": "BTC",
                "weight": 0.76,
                "e": 0.0,
                "trades": 0,
                "born": True,
            },
            {"id": "vol-momentum", "coin": "ETH", "weight": 1.0, "e": 0.0, "trades": 0},
        ]
    )
    out = dashboard.techniques_html()
    assert "funding-fade" in out and "vol-momentum" in out
    assert "born" in out  # the born-vs-authored chip
    assert "wbar" in out  # the weight bars


def test_arsenal_panel_empty_state(gclaw_home):
    assert "arsenal" in dashboard.techniques_html().lower()


def test_leaderboard_link_in_header_and_panel(metabolism_fixture, gclaw_home):
    metabolism_fixture()
    page = dashboard.render_html(metabolism_fixture(), "", [], [])
    assert 'href="leaderboard.html"' in page  # the header pill
    panel = dashboard.leaderboard_html(gclaw_home)
    assert 'href="leaderboard.html"' in panel  # the "see full board" link


def test_live_sync_embeds_address_or_noops(gclaw_home):
    # No managed address → no script (the page just shows the snapshot).
    _write(gclaw_home, "positions.json", {"equity": 0, "positions": []})
    assert dashboard.live_sync_script(gclaw_home) == ""

    # With an address → the live fetch is wired to HL's public API.
    _write(
        gclaw_home,
        "positions.json",
        {
            "equity": 42.0,
            "spotUsdc": 0.0,
            "spotHold": 0.0,
            "managed": "0xBlaq",
            "positions": [{"coin": "ETH", "size": -0.1, "entryPx": 1700, "unrealizedPnl": 0.4}],
        },
    )
    script = dashboard.live_sync_script(gclaw_home)
    assert "0xBlaq" in script
    assert "clearinghouseState" in script  # exact perp PnL, not approximated
    assert "api.hyperliquid.xyz" in script


def test_deploy_leaderboard_co_locates_the_board(gclaw_home):
    dashboard.deploy_leaderboard(gclaw_home)
    board = gclaw_home / "leaderboard.html"
    assert board.exists()
    assert "leaderboard" in board.read_text(encoding="utf-8").lower()


def test_sigil_is_a_clean_glyph(gclaw_home):
    # The alchemical sigils tofu-boxed everywhere; every genome must draw from the
    # clean geometric set now.
    tofu = {"🜂", "🜁", "🜃", "🜄", "🝆", "🝛", "🝬"}
    for born in ("genesis", "2026-01-01T00:00:00+00:00", "abc"):
        g = dashboard.genome("Gclaw", born)
        assert g["sigil"] in dashboard.SIGILS
        assert g["sigil"] not in tofu


def test_rewards_ladder_shows_next_unlock_and_full_path(gclaw_home):
    # The goodwill→power-up loop: at 31 goodwill the next unlock is Reproduce (at 50),
    # the "to go" carrot shows, and the whole ladder (every tier) is visible.
    out = dashboard.rewards_html({"goodwill": 31})
    assert "Reproduce" in out
    assert "goodwill to go" in out  # the carrot
    assert "Self-recode" in out and "Swarm" in out and "Apex" in out  # the path beyond
    assert "rstep next" in out  # the next tier is highlighted
    # maxed out → no "to go", shows Apex reached
    assert "Apex reached" in dashboard.rewards_html({"goodwill": 1500})


def test_hl_perp_reads_perp_state_from_public_api():
    # Regression: the authenticated SDK returns the shared collateral as accountValue
    # when FLAT, which double-counts against spot (equity read ~2x, e.g. $404 vs $202).
    # fullState must read perp state from HL's public info API (hlInfo), which is
    # authoritative (accountValue 0 when flat).
    src = (Path(__file__).resolve().parent.parent / "scripts" / "hl_perp.js").read_text(
        encoding="utf-8"
    )
    fs = src[src.index("async function fullState") : src.index("async function fullState") + 700]
    assert "hlInfo(" in fs  # perp state comes from the public API, not the SDK
    assert "skill.getHlClearinghouseState" not in fs  # not the flat-double-counting SDK read


def test_leaderboard_verifier_counts_the_perp_wallet():
    # Regression: the leaderboard verifies equity straight from HyperLiquid. It must
    # count the PERP wallet, not spot alone — else a perp-funded agent reads ~$0 and
    # looks unverified despite real funds (the spot-vs-perp bug we fixed everywhere).
    src = (Path(__file__).resolve().parent.parent / "leaderboard" / "leaderboard.html").read_text(
        encoding="utf-8"
    )
    assert "clearinghouseState" in src  # the perp wallet (accountValue), not just spot
    assert "accountValue" in src
    assert "hold" in src  # free spot = total - hold, so the margin isn't double-counted


def test_cmd_render_writes_a_valid_page(metabolism_fixture, gclaw_home):
    # The heartbeat's terminal step: render --no-live must produce a real dashboard.
    metabolism_fixture()
    dashboard.cmd_render(SimpleNamespace(no_live=True, out=None))
    page = gclaw_home / "dashboard.html"
    assert page.exists()
    html = page.read_text(encoding="utf-8")
    assert "</html>" in html
    assert (gclaw_home / "leaderboard.html").exists()  # co-deployed for the link
