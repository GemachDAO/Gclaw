#!/usr/bin/env python3
"""run — the gclaw harness eval scorecard.

Runs every eval in this directory and prints one pass/fail scorecard, so refining the
harness is measured, not vibes. Each eval drives the real code (not a re-implementation)
and exits 0 on PASS, non-zero on FAIL; several double as regression guards for a specific
fix (see each eval's module docstring).

  uv run --no-project python3 evals/run.py            # run all
  uv run --no-project python3 evals/run.py --quick    # skip the slow judge_power

Exit: 0 if every eval passes, 1 otherwise.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# (module, guards) — order cheap-to-expensive; judge_power runs many backtests, so it is last.
EVALS = [
    ("cost_truth", "JUDGE + ledger charge the true round-trip cost (builderFee)"),
    ("feature_parity", "backtest features match the live intel.js definition"),
    ("tool_budget", "GDEX MCP read tools are economical with context"),
    ("judge_power", "the JUDGE rejects edgeless signals (slow: many backtests)"),
]


def run_one(module: str) -> tuple[bool, str]:
    """Run one eval; return (passed, its VERDICT line)."""
    proc = subprocess.run(
        [sys.executable, str(HERE / f"{module}.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    verdict = next(
        (ln.strip() for ln in reversed(proc.stdout.splitlines()) if "VERDICT:" in ln),
        "(no verdict line)",
    )
    return proc.returncode == 0, verdict


def main() -> int:
    quick = "--quick" in sys.argv
    evals = [e for e in EVALS if not (quick and e[0] == "judge_power")]
    print("=" * 70)
    print("gclaw harness eval scorecard")
    print("=" * 70)
    results = []
    for module, guards in evals:
        passed, verdict = run_one(module)
        results.append(passed)
        mark = "PASS" if passed else "FAIL"
        print(f"[{mark}] {module:<16} {guards}")
        print(f"        {verdict}")
    ok = all(results)
    print("-" * 70)
    print(f"{sum(results)}/{len(results)} eval(s) passing — harness {'GREEN' if ok else 'has regressions'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
