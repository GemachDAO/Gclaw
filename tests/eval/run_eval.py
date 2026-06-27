"""Capability eval runner for the Gclaw forge's trade decisions.

Drives every labeled golden scenario (golden_scenarios.py) through the REAL forge
decision functions and prints a scorecard: N/total passed, plus per-scenario PASS/FAIL
with a one-line reason.

This is a CAPABILITY eval, not a regression gate. It ALWAYS exits 0 — a low pass rate is
an improvement target to drive up, never a build failure. (Contrast the regression suites
under tests/, which must stay near-100% and DO fail the build.) See README.md.

Run:
    uv run --no-project python3 tests/eval/run_eval.py

Fully offline: no network, no forge_data.js, no real ~/.gclaw. The circuit-breaker
scenarios write breaker.json into a throwaway per-scenario $GCLAW_HOME tmp dir.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# Import the real forge module from scripts/ without any install step (same approach
# the unit-test conftest uses: put scripts/ on sys.path, then `import forge`).
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import forge  # noqa: E402

# Load golden_scenarios as a sibling module regardless of the current working directory.
_SCEN_PATH = Path(__file__).resolve().parent / "golden_scenarios.py"
_spec = importlib.util.spec_from_file_location("golden_scenarios", _SCEN_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - defensive
    raise RuntimeError(f"cannot load golden scenarios from {_SCEN_PATH}")
golden_scenarios = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(golden_scenarios)

CAPS = golden_scenarios.CAPS
SCENARIOS = golden_scenarios.SCENARIOS


def _run_combine(sc: dict[str, Any]) -> tuple[bool, str]:
    """Run a combiner scenario and compare the action to the expected one."""
    out = forge._combine(sc["votes"], sc["regime"], CAPS, sc["scaler"])
    got = None if out is None else out["action"]
    want = sc["expect_action"]
    if got == want:
        detail = "no entry" if got is None else f"{got} (conf {out['confidence']})"
        return True, f"{sc['regime']}: decided {detail} as expected"
    return False, f"{sc['regime']}: expected {want!r}, got {got!r}"


def _run_breaker(sc: dict[str, Any]) -> tuple[bool, str]:
    """Run a circuit-breaker scenario in an isolated $GCLAW_HOME and compare allow_entry.

    The high-water mark is established with a first call at ``hwm``, then the scenario's
    actual ``equity`` read is evaluated against it — mirroring how cmd_run accumulates the
    HWM across heartbeats.
    """
    prev_home = os.environ.get("GCLAW_HOME")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["GCLAW_HOME"] = tmp
        try:
            forge.circuit_breaker(sc["hwm"], 0, reliable=True)  # seed the high-water mark
            out = forge.circuit_breaker(sc["equity"], sc["n_positions"], reliable=sc["reliable"])
        finally:
            if prev_home is None:
                os.environ.pop("GCLAW_HOME", None)
            else:
                os.environ["GCLAW_HOME"] = prev_home
    got = bool(out["allow_entry"])
    want = bool(sc["expect_allow_entry"])
    if got == want:
        verb = "allows" if got else "blocks"
        return True, f"breaker {verb} entry (drawdown {out.get('drawdown_pct')}%) as expected"
    return False, f"expected allow_entry={want}, got {got} ({out.get('reason')})"


def _run_one(sc: dict[str, Any]) -> tuple[bool, str]:
    if sc["stage"] == "combine":
        return _run_combine(sc)
    if sc["stage"] == "breaker":
        return _run_breaker(sc)
    return False, f"unknown stage {sc['stage']!r}"


def main() -> int:
    """Run every scenario, print the scorecard, and ALWAYS exit 0 (capability eval)."""
    results: list[tuple[str, bool, str]] = []
    for sc in SCENARIOS:
        ok, reason = _run_one(sc)
        results.append((sc["name"], ok, reason))

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    width = max(len(name) for name, _, _ in results)

    print("Gclaw forge capability eval — golden trade decisions")
    print("=" * 72)
    for name, ok, reason in results:
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {name.ljust(width)}  {reason}")
    print("=" * 72)
    pct = (100.0 * passed / total) if total else 0.0
    print(f"SCORE: {passed}/{total} scenarios passed ({pct:.0f}%)")
    print("(capability eval — pass rate is an improvement target, not a build gate)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
