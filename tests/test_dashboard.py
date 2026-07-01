"""Dashboard rendering — "The Mind, Alive, With Receipts".

The dashboard is now a hard I/O / render split: :func:`dashboard.refresh` does all
file/subprocess/network reads and returns a plain ``state`` dict; :func:`dashboard.render`
is a PURE function of that dict. These tests exercise ``render`` and the pure data-shaping
helpers against hand-built states — no network, no ``$GCLAW_HOME`` files needed — which is
the point of the split. A few regression tests still pin the leaderboard/hl_perp JS.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import dashboard


# --------------------------------------------------------------------------- #
# A minimal, self-contained state dict — the contract render() consumes.
# --------------------------------------------------------------------------- #
def _state(**overrides: object) -> dict[str, object]:
    born = "2026-06-17T00:11:24+00:00"
    state: dict[str, object] = {
        "metabolism": {
            "born_at": born,
            "mode": "thrive",
            "heartbeats": 346,
            "recodes": 6,
            "children": [],
            "onchain_identity": {"agentId": "55624", "chain": "base:8453"},
        },
        "genome": dashboard.genome("Gclaw", born),
        "reputation": {
            "trading": {
                "closed_trades": 52,
                "win_rate": 0.192,
                "realized_pnl_usd": -39.82,
                "expectancy_usd": -0.766,
            },
            "evolution": {
                "self_authored_techniques": 6,
                "proven_edge_count": 2,
                "children": 0,
            },
            "event_calibration": {"n": 0, "brier": None, "no_skill_baseline": None},
            "accountability": "re-derivable from onchain fills",
        },
        "style": {
            "adopted": [
                {"id": "stop-hunt-revert", "e": 0.1639, "trades": 9, "weight": 0.86},
                {"id": "stock-meanrev", "e": 0.057, "trades": 3, "weight": 0.86},
                {"id": "vol-momentum", "e": -0.0087, "trades": 7, "weight": 0.96},
            ]
        },
        "proven_markets": [
            {"technique": "vol-momentum", "coin": "xyz:MU", "oos_n": 129, "t": 4.74},
        ],
        "techniques": {
            "stop-hunt-revert": {"id": "stop-hunt-revert", "status": "proven", "card": {"proven": True, "oos": {"n": 13}}},
        },
        "authored_cards": [
            {
                "id": "trend-funding-squeeze",
                "claim": "crowd trapped = squeeze fuel",
                "status": "draft",
                "card": {"proven": False, "oos": {"n": 0, "expectancy": 0.0}},
            },
            {
                "id": "eff-trend-gate",
                "claim": "filters the chop entries dragging trend win-rate to 0.19",
                "status": "draft",
                "card": {"proven": False, "oos": {"n": 1, "expectancy": -0.0018}},
            },
            {
                "id": "stock-meanrev",
                "claim": "fade overextended stock perps",
                "status": "proven",
                "card": {"proven": True, "oos": {"n": 98}},
            },
        ],
        "journal": [],
        "telepathy": [],
        "positions": {"equity": 176.0, "positions": []},
        "gas": {},
        "leaderboard": {},
        "persona": {},
        "github_qr": "",
        "topup_qr": "",
        "banner": "",
    }
    state.update(overrides)
    return state


# --------------------------------------------------------------------------- #
# render() — the pure page.
# --------------------------------------------------------------------------- #
def test_render_produces_a_full_page():
    html = dashboard.render(_state())
    assert html.startswith("<!doctype")
    assert html.strip().endswith("</html>")
    assert len(html) > 5000


def test_hero_is_proven_edge_not_goodwill_or_equity():
    html = dashboard.render(_state())
    assert "// FITNESS · PROVEN EDGE" in html
    assert "techniques graduated" in html
    # the demoted framings are gone
    assert "power-up" not in html.lower()
    assert "leverage" not in html.lower()
    assert "goodwill to go" not in html


def test_proven_edge_counts_only_live_proven_techniques():
    proven = dashboard.proven_edge(_state()["style"])
    ids = {p["id"] for p in proven}
    assert ids == {"stop-hunt-revert", "stock-meanrev"}  # vol-momentum is -EV, excluded


def test_hero_shows_the_proven_count():
    html = dashboard.render(_state())
    assert 'id="provenEdge"' in html
    assert ">2</span>" in html  # two graduated techniques


def test_scientists_bench_narrates_authoring_with_verdicts():
    html = dashboard.render(_state())
    assert "// THE SCIENTIST'S BENCH" in html
    assert "eff-trend-gate" in html
    assert "REJECTED" in html  # the honest failed backtest
    assert "GRADUATED" in html  # the proven one
    assert "judging" in html  # the un-backtested draft


def test_track_record_is_honest_and_dignified():
    html = dashboard.render(_state())
    assert "TRACK RECORD" in html
    assert "39.82" in html
    assert "re-derivable onchain" in html
    # the loss is styled slate (trpnl), never the alarm red used for rejects/negatives
    assert "trpnl" in html


def test_track_record_empty_state():
    rec = dashboard.track_record({}, [])
    assert rec == {"pnl": 0.0, "closes": 0, "win_rate": 0.0}


def test_track_record_falls_back_to_journal_settles():
    journal = [
        {"event": "settle", "pnl": 1.0},
        {"event": "settle", "pnl": -3.0},
        {"event": "tick"},
    ]
    rec = dashboard.track_record({}, journal)
    assert rec["closes"] == 2
    assert rec["pnl"] == -2.0
    assert rec["win_rate"] == 0.5


def test_breed_gate_reflects_the_real_reproduction_rule():
    proven = dashboard.proven_edge(_state()["style"])
    gate = dashboard.breed_gate(_state(), proven)
    assert gate["proven"] == 2
    assert gate["have_edges"] is True
    # no last_replicate_edge_count => 2 > 0 => a new edge exists, no children => ready
    assert gate["have_new"] is True
    assert gate["ready"] is True


def test_breed_gate_locks_without_a_new_edge_since_last_birth():
    state = _state()
    state["metabolism"]["last_replicate_edge_count"] = 2
    proven = dashboard.proven_edge(state["style"])
    gate = dashboard.breed_gate(state, proven)
    assert gate["have_new"] is False
    assert gate["ready"] is False


def test_breed_gate_locks_below_min_edges():
    state = _state()
    state["style"] = {"adopted": [{"id": "a", "e": 0.1, "trades": 5}]}  # only 1 proven
    proven = dashboard.proven_edge(state["style"])
    gate = dashboard.breed_gate(state, proven)
    assert gate["proven"] == 1
    assert gate["have_edges"] is False
    assert gate["ready"] is False


def test_calibration_renders_honest_empty_state_at_n_zero():
    html = dashboard.calibration_html(_state())
    assert "learned to doubt itself" in html
    assert "// SELF-KNOWLEDGE" in html


def test_calibration_renders_brier_when_present():
    state = _state()
    state["reputation"]["event_calibration"] = {"n": 12, "brier": 0.21, "no_skill_baseline": 0.25}
    html = dashboard.calibration_html(state)
    assert "0.21" in html
    assert "learned to doubt itself" not in html


def test_proven_dna_marks_proven_and_bleeding_pairs():
    dna = dashboard.proven_dna(_state()["style"])
    by_id = {d["id"]: d for d in dna}
    assert by_id["stop-hunt-revert"]["proven"] is True
    assert by_id["vol-momentum"]["proven"] is False  # negative expectancy


def test_lineage_graph_buckets_by_stage():
    graph = dashboard.lineage_graph(_state(), dashboard.proven_edge(_state()["style"]))
    # only proven techniques land in PROVEN; inherited is empty (no children yet)
    assert any(p["id"] == "stop-hunt-revert" for p in graph["proven"])
    assert graph["inherited"] == []


def test_no_meta_refresh_lives_but_live_sync_is_wired():
    state = _state()
    state["positions"] = {
        "equity": 42.0,
        "managed": "0xBlaq",
        "spotUsdc": 0.0,
        "spotHold": 0.0,
        "positions": [{"coin": "ETH", "size": -0.1, "entryPx": 1700, "unrealizedPnl": 0.4}],
    }
    html = dashboard.render(state)
    assert 'http-equiv="refresh"' not in html  # the full-page reload is gone
    assert "api.hyperliquid.xyz" in html  # values update in place instead
    assert "0xBlaq" in html


def test_live_sync_noops_without_managed_address():
    assert dashboard.live_sync_script({"positions": {"equity": 0, "positions": []}}) == ""


def test_positions_panel_flat_then_open():
    flat = dashboard.positions_html(_state(positions={"equity": 50.0, "positions": []}))
    assert "Flat" in flat
    open_state = _state(
        positions={
            "equity": 50.0,
            "managed": "0xabc",
            "positions": [
                {"coin": "ETH", "size": -0.1, "entryPx": 1700, "unrealizedPnl": -2.18, "liquidationPx": 3386}
            ],
        }
    )
    panel = dashboard.positions_html(open_state)
    assert "ETH" in panel
    assert 'data-coin="ETH"' in panel
    assert 'id="posEquity"' in panel


def test_render_escapes_untrusted_technique_claims():
    # A malicious claim must be escaped, never injected as live markup.
    state = _state()
    state["authored_cards"] = [
        {"id": "x", "claim": "<img src=x onerror=alert(1)>", "status": "draft", "card": {"oos": {"n": 0}}}
    ]
    html = dashboard.render(state)
    assert "<img src=x onerror" not in html
    assert "&lt;img src=x onerror" in html


def test_techniques_table_flags_proven():
    html = dashboard.techniques_html(_state())
    assert "stop-hunt-revert" in html and "vol-momentum" in html
    assert "PROVEN" in html
    assert "on trial" in html
    assert "wbar" in html


# --------------------------------------------------------------------------- #
# End-to-end: cmd_render writes a valid page from real-ish home state.
# --------------------------------------------------------------------------- #
def _write(home: Path, name: str, obj: object) -> None:
    p = home / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def test_cmd_render_writes_a_valid_page(metabolism_fixture, gclaw_home):
    metabolism_fixture()
    dashboard.cmd_render(SimpleNamespace(no_live=True, out=None))
    page = gclaw_home / "dashboard.html"
    assert page.exists()
    html = page.read_text(encoding="utf-8")
    assert "</html>" in html
    assert "// FITNESS · PROVEN EDGE" in html
    assert (gclaw_home / "leaderboard.html").exists()  # co-deployed for the header link


def test_deploy_leaderboard_co_locates_the_board(gclaw_home):
    dashboard.deploy_leaderboard(gclaw_home)
    board = gclaw_home / "leaderboard.html"
    assert board.exists()
    assert "leaderboard" in board.read_text(encoding="utf-8").lower()


def test_leaderboard_link_in_header(metabolism_fixture, gclaw_home):
    metabolism_fixture()
    page = dashboard.render_html(metabolism_fixture())
    assert 'href="leaderboard.html"' in page


# --------------------------------------------------------------------------- #
# Genome + heredity regressions (kept — the organism metaphor is well-tested).
# --------------------------------------------------------------------------- #
def test_sigil_is_a_clean_glyph():
    tofu = {"🜂", "🜁", "🜃", "🜄", "🝆", "🝛", "🝬"}
    for born in ("genesis", "2026-01-01T00:00:00+00:00", "abc"):
        g = dashboard.genome("Gclaw", born)
        assert g["sigil"] in dashboard.SIGILS
        assert g["sigil"] not in tofu


def test_hl_perp_reads_perp_state_from_public_api():
    src = (Path(__file__).resolve().parent.parent / "scripts" / "hl_perp.js").read_text(encoding="utf-8")
    fs = src[src.index("async function fullState") : src.index("async function fullState") + 700]
    assert "hlInfo(" in fs
    assert "skill.getHlClearinghouseState" not in fs


def test_leaderboard_verifier_counts_the_perp_wallet():
    src = (Path(__file__).resolve().parent.parent / "leaderboard" / "leaderboard.html").read_text(encoding="utf-8")
    assert "clearinghouseState" in src
    assert "accountValue" in src
    assert "hold" in src
