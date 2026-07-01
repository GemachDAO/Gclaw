"""forge.author — the scientist loop's single gated primitive.

author = validate an LLM-proposed signal body in the sandbox, backtest it walk-forward,
and adopt it ONLY if it graduates on out-of-sample edge. It must NEVER open a trade, and
a sandbox-violating body must be rejected before anything is written to disk. The backtest
is mocked (no network / no candles); the sandbox validation is real.
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import forge

_VALID = (
    "def signal(features):\n"
    "    return {'action': 'flat', 'confidence': 0.0, 'leverage': 1, 'stop_pct': 0, 'reason': 'x'}\n"
)
_MALICIOUS = "import os\n\n\ndef signal(features):\n    os.system('echo pwned')\n    return {}\n"


def _args(tmp: Path, body: str, name: str) -> Namespace:
    f = tmp / "signal_body.py"
    f.write_text(body, encoding="utf-8")
    return Namespace(
        name=name, signal_file=str(f), claim="test", kind="edge",
        coin="BTC", interval="1h", limit=200, parent=None, force=False,
    )


def _card(proven: bool) -> dict:
    return {
        "proven": proven, "coin": "BTC", "interval": "1h",
        "out_of_sample": {"n": 50, "expectancy": 0.01 if proven else -0.01},
    }


def _no_execute(monkeypatch) -> None:
    def boom(_intent):
        raise AssertionError("author must NEVER execute a trade")
    monkeypatch.setattr(forge, "_execute", boom)


def test_malicious_body_is_rejected_before_any_write(gclaw_home, monkeypatch, tmp_path):
    _no_execute(monkeypatch)
    out = forge.cmd_author(_args(tmp_path, _MALICIOUS, "evil-os"))
    assert out["ok"] is False
    assert out["rejected"] == "sandbox"
    assert any("os" in v for v in out["violations"])
    assert out["adopted"] is False
    # nothing written: the technique dir must not exist
    assert not forge.tech_dir("evil-os").exists()


def test_valid_but_unproven_is_drafted_not_adopted(gclaw_home, monkeypatch, tmp_path):
    _no_execute(monkeypatch)
    monkeypatch.setattr(forge, "backtest", lambda *a, **k: _card(False))
    out = forge.cmd_author(_args(tmp_path, _VALID, "weak-edge"))
    assert out["ok"] is True
    assert out["proven"] is False
    assert out["adopted"] is False
    assert "weak-edge" not in [e["id"] for e in forge.load_style().get("adopted", [])]


def test_valid_and_proven_is_adopted(gclaw_home, monkeypatch, tmp_path):
    _no_execute(monkeypatch)
    monkeypatch.setattr(forge, "backtest", lambda *a, **k: _card(True))
    out = forge.cmd_author(_args(tmp_path, _VALID, "real-edge"))
    assert out["ok"] is True
    assert out["proven"] is True
    assert out["adopted"] is True
    assert "real-edge" in [e["id"] for e in forge.load_style().get("adopted", [])]
