#!/usr/bin/env python3
"""harness_grade — a thoughtful graded report card for the whole gclaw harness.

The point-evals (judge_power, cost_truth, feature_parity, tool_budget) each answer ONE
yes/no question. This grader sits on top and produces a single, honest assessment of the
harness as a whole. Its one load-bearing design choice: **severity is enforced as hard
floors, not weighted averaging** — a broken JUDGE, a live-money-leaking cost model, or a
corrupted feature caps the letter grade outright, so unrelated green checks can never
launder a systemically broken harness into a passing grade.

Two-pass grade:
  Pass 1  weighted score over the graded dimensions -> provisional letter.
  Pass 2  apply floor caps + calibration ceiling + regression cap (each only lowers),
          take the strictest.

Missing data (a skipped eval, event calibration with n=0) scores UNGRADED/STALE and caps
the ceiling — it is never defaulted to a pass, because in this harness the check you didn't
run is exactly what produced 37 false "proven" pairs the first time.

v1 is fully deterministic. The LLM decision-quality dimension is v2 (assune-tx0.3).

  uv run --no-project python3 evals/harness_grade.py            # full grade
  uv run --no-project python3 evals/harness_grade.py --quick    # skip the slow judge_power
  uv run --no-project python3 evals/harness_grade.py --json      # machine-readable record
Exit: 0 unless --fail-under LETTER is set and the grade is below it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import forge  # noqa: E402  (for gclaw_home() — same env resolution the evals use)

HOME = forge.gclaw_home()
HISTORY = HOME / "harness_grades.jsonl"
POINTS = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
LETTERS = [(90, "A"), (80, "B"), (65, "C"), (50, "D"), (0, "F")]
# Score ceilings imposed by a binding cap (a cap only ever lowers the grade).
CAP_SCORE = {"F": 30, "D": 50, "C": 65, "Bplus": 88}


def letter_of(score: float) -> str:
    for floor, letter in LETTERS:
        if score >= floor:
            return letter
    return "F"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def run_eval(module: str, quick: bool) -> dict[str, Any] | None:
    """Run one eval with --json and return its final machine-readable line, or None.

    None means the eval did not produce a verdict this run (skipped or crashed) — the
    caller scores that as STALE/F, never a silent pass.
    """
    if quick and module == "judge_power":
        return None
    proc = subprocess.run(
        [sys.executable, str(HERE / f"{module}.py"), "--json"],
        capture_output=True, text=True, check=False,
    )
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


# ── Dimension scorers: each returns a dict describing one graded dimension ──────


def _dim(name: str, weight: int, grade: str, why: str, number: str, *, floor: bool = False,
         override: bool = False) -> dict[str, Any]:
    return {
        "name": name, "weight": weight, "grade": grade, "why": why, "number": number,
        "floor": floor, "override": override,
        "points": POINTS.get(grade),  # None for UNGRADED/STALE — excluded from the blend
    }


def score_judge(jp: dict[str, Any] | None) -> dict[str, Any]:
    if jp is None:
        return _dim("JUDGE Statistical Power", 20, "STALE",
                    "judge_power not run this invocation (--quick) — a skipped gate is not a pass",
                    "not run", floor=True)
    fpr, target = jp["fpr"], jp["target"]
    grade = "A" if fpr <= target * 0.5 else "B" if fpr <= target else "F"
    return _dim("JUDGE Statistical Power", 20, grade,
                "gate certifies surrogate noise below the alpha target" if grade != "F"
                else "gate certifies structureless noise as edge",
                f"surrogate-FPR {fpr:.1%} vs <= {target:.1%}", floor=True)


def score_cost(ct: dict[str, Any] | None) -> dict[str, Any]:
    if ct is None:
        return _dim("Cost-Model Fidelity", 15, "STALE", "cost_truth produced no verdict", "n/a",
                    floor=True)
    gap = ct["gap_bp"]
    grade = "A" if ct["verdict"] == "PASS" else "C" if gap <= 3 else "F"
    return _dim("Cost-Model Fidelity", 15, grade,
                "JUDGE models the true venue cost" if grade == "A"
                else "JUDGE understates the true round-trip cost — edges are subsidised",
                f"modeled {ct['modeled_bp']:.1f}bp vs true {ct['true_bp']:.1f}bp", floor=True)


def score_parity(fp: dict[str, Any] | None) -> dict[str, Any]:
    if fp is None:
        return _dim("Train/Serve Feature Parity", 15, "STALE", "feature_parity produced no verdict",
                    "n/a", floor=True)
    mism = fp["total_mismatches"]
    grade = "A" if mism == 0 else "C" if mism <= 2 else "F"
    return _dim("Train/Serve Feature Parity", 15, grade,
                "backtest features match the live definition" if grade == "A"
                else "backtest reconstructs features differently from live — silent train/serve skew",
                f"{mism} feature/bar mismatches", floor=True)


def score_mc(live: dict[str, Any]) -> dict[str, Any]:
    cap_wired = "AUTOPROVE_MAX_PER_TECH" in (SCRIPTS / "forge.py").read_text(encoding="utf-8")
    pairs = live["proven_markets"].get("pairs", [])
    per_tech = {}
    for p in pairs:
        per_tech[p["technique"]] = per_tech.get(p["technique"], 0) + 1
    max_sprawl = max(per_tech.values()) if per_tech else 0
    snap = live.get("proven_markets_prev")
    drop = ""
    if snap is not None:
        before = len(snap.get("pairs", []))
        if before:
            drop = f"; last revalidate dropped {before - len(pairs)}/{before}"
    if not cap_wired:
        grade = "D"
    elif max_sprawl <= 3:
        grade = "A"
    else:
        grade = "C"  # cap wired but a technique still sprawls (pre-cap residue)
    return _dim("Multiple-Comparisons Discipline", 10, grade,
                "per-technique cap wired; no technique sprawls across markets" if grade == "A"
                else "look-elsewhere control weak — a technique spans many markets" if grade == "C"
                else "no multiple-comparisons cap wired in autoprove",
                f"{len(pairs)} proven pairs, max {max_sprawl}/technique{drop}")


def score_live(live: dict[str, Any]) -> dict[str, Any]:
    rep = live["reputation"].get("trading", {})
    brk = live["breaker"]
    exp = float(rep.get("expectancy_usd", 0) or 0)
    dd = float(brk.get("drawdown_pct", 0) or 0)
    if brk.get("tripped"):
        grade, why = "F", "circuit breaker tripped — book flattened on drawdown"
    elif exp > 0:
        grade, why = "B", "positive live expectancy per closed trade"
    elif dd < 15:
        grade, why = "C", "negative expectancy but drawdown contained; no live-proven edge yet"
    else:
        grade, why = "D", "negative expectancy and a material drawdown"
    return _dim("Live Decision Quality", 15, grade, why,
                f"expectancy ${exp:.2f}, win {float(rep.get('win_rate', 0) or 0):.0%}, "
                f"drawdown {dd:.1f}%", override=bool(brk.get("tripped")))


def score_calibration(live: dict[str, Any]) -> dict[str, Any]:
    cal = live["reputation"].get("event_calibration", {})
    n = int(cal.get("n", 0) or 0)
    if n == 0:
        return _dim("Event-Desk Calibration", 5, "UNGRADED",
                    "no resolved outcome tickets yet — Brier is uncomputable (caps ceiling at B+)",
                    "n=0 resolved")
    brier, base = cal.get("brier"), cal.get("no_skill_baseline")
    grade = "A" if brier is not None and base is not None and brier < base else "F"
    return _dim("Event-Desk Calibration", 5, grade,
                "resolved Brier beats the no-skill baseline" if grade == "A"
                else "resolved Brier no better than a no-skill guesser",
                f"n={n}, brier={brier}")


def score_edge(live: dict[str, Any]) -> dict[str, Any]:
    ev = live["reputation"].get("evolution", {})
    proven = int(ev.get("proven_edge_count", 0) or 0)
    backtest = int(ev.get("backtest_proven_count", 0) or 0)
    if proven > 0:
        grade, why = "A", f"{proven} technique(s) show a live bootstrap-CI-positive edge"
    elif backtest > 0:
        grade, why = "C", ("0 live-proven of "
                           f"{backtest} backtest-proven — correct for a strict gate in a hard "
                           "market OR a broken execution path; statistics alone can't tell")
    else:
        grade, why = "C", "no proven techniques either way"
    return _dim("Edge Realness", 5, grade, why, f"{proven} live / {backtest} backtest proven")


def score_hygiene(tb: dict[str, Any] | None) -> dict[str, Any]:
    if tb is None:
        return _dim("Operational Hygiene", 5, "STALE", "tool_budget produced no verdict", "n/a")
    if tb["critical_fails"]:
        grade, why = "C", "a read tool leaks context / lacks structured errors"
    elif tb["warns"]:
        grade, why = "B", "read tools economical; minor warnings"
    else:
        grade, why = "A", "MCP read surface is context-economical"
    return _dim("Operational Hygiene", 5, grade, why,
                f"{tb['critical_fails']} critical, {tb['warns']} warn")


def score_decision_quality(with_judge: bool) -> dict[str, Any]:
    """The one LLM-judged dimension (v2). Off unless --with-judge; LOW-CONF -> UNGRADED cap.

    Never crashes the grader: the optional judge is best-effort, so any failure degrades to
    UNGRADED (a ceiling cap), never a fabricated grade and never an exception.
    """
    if not with_judge:
        return _dim("Decision-Quality (LLM judge)", 10, "SKIPPED",
                    "not run — pass --with-judge (LLM-graded, costs tokens/time)", "opt-out")
    try:
        import decision_quality as dq
        r = dq.grade_decision_quality()
    except Exception as exc:
        return _dim("Decision-Quality (LLM judge)", 10, "UNGRADED", f"judge errored: {exc}", "error")
    if r.get("confidence") == "low":
        return _dim("Decision-Quality (LLM judge)", 10, "UNGRADED",
                    r.get("low_confidence_reason") or "low confidence", "LOW-CONF")
    d = _dim("Decision-Quality (LLM judge)", 10, r["grade"],
             f"graded {r['n_cycles']} active cycle(s), mean {r.get('mean_score')}/3",
             f"grounding {r.get('grounding_rate')}, {r.get('forced_fails', 0)} forced-fail")
    d["dq"] = r
    return d


# ── Aggregation: two-pass, floors dominate the arithmetic ──────────────────────


def aggregate(dims: list[dict[str, Any]], prev: dict[str, Any] | None) -> dict[str, Any]:
    graded = [d for d in dims if d["points"] is not None]
    wsum = sum(d["weight"] for d in graded)
    prov_score = (sum(d["weight"] * d["points"] for d in graded) / wsum / 4 * 100) if wsum else 0.0

    caps: list[tuple[int, str]] = []
    for d in dims:
        if d["floor"] and d["grade"] in ("F", "STALE"):
            tier = "F" if d["name"].startswith("JUDGE") else "D" if "Cost" in d["name"] else "C"
            caps.append((CAP_SCORE[tier], f"{d['name']} = {d['grade']} (floor)"))
    for d in dims:  # any dimension we tried but couldn't grade caps the ceiling — never a free pass
        if d["grade"] == "UNGRADED":
            caps.append((CAP_SCORE["Bplus"], f"{d['name']} UNGRADED"))

    regression = None
    if prev:
        for d in dims:
            if not d["floor"]:
                continue
            pg = next((x for x in prev.get("dimensions", []) if x["name"] == d["name"]), None)
            # A genuine regression is a floor dim that WAS passing and is now an actual FAIL.
            # STALE means "not measured this run" (e.g. --quick skipped it) — that already caps
            # the grade, but it is not a regression, so it must not fire the banner.
            if pg and POINTS.get(pg.get("grade")) not in (None, 0) and d["grade"] == "F":
                regression = f"{d['name']} regressed {pg['grade']} -> {d['grade']}"
                caps.append((CAP_SCORE["D"], "regression on a floor dimension"))

    final_score = min([prov_score] + [c[0] for c in caps])
    binding = min(caps, key=lambda c: c[0])[1] if caps and min(c[0] for c in caps) < prov_score else ""
    return {
        "provisional_score": round(prov_score, 1),
        "provisional_letter": letter_of(prov_score),
        "score": round(final_score, 1),
        "letter": letter_of(final_score),
        "capped_by": binding,
        "regression": regression,
    }


def top_risks(dims: list[dict[str, Any]], live: dict[str, Any]) -> list[dict[str, Any]]:
    ranked = []
    for d in dims:
        pts = d["points"] if d["points"] is not None else 0  # UNGRADED counts as risk
        sev = d["weight"] * (4 - pts)
        if d["override"] or (d["floor"] and d["grade"] in ("F", "STALE")):
            sev += 1000  # a tripped breaker / broken floor always claims the top
        if sev > 0:
            ranked.append({"name": d["name"], "grade": d["grade"], "why": d["why"], "sev": sev})
    ranked.sort(key=lambda r: r["sev"], reverse=True)
    return ranked[:3]


# ── Live state + history ───────────────────────────────────────────────────────


def load_live() -> dict[str, Any]:
    fdir = HOME / "forge"
    snaps = sorted(fdir.glob("proven_markets.json.pre-revalidate-*"), key=lambda p: p.stat().st_mtime)
    return {
        "reputation": _read_json(HOME / "reputation.json", {}),
        "breaker": _read_json(HOME / "breaker.json", {}),
        "metabolism": _read_json(HOME / "metabolism.json", {}),
        "proven_markets": _read_json(fdir / "proven_markets.json", {"pairs": []}),
        "proven_markets_prev": _read_json(snaps[-1], None) if snaps else None,
    }


def load_last() -> dict[str, Any] | None:
    if not HISTORY.exists():
        return None
    for ln in reversed([x for x in HISTORY.read_text(encoding="utf-8").splitlines() if x.strip()]):
        try:
            return json.loads(ln)
        except ValueError:
            continue
    return None


def append_history(record: dict[str, Any]) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _arrow(dim: dict[str, Any], prev: dict[str, Any] | None) -> str:
    if not prev:
        return " "
    pg = next((x for x in prev.get("dimensions", []) if x["name"] == dim["name"]), None)
    if not pg or dim["points"] is None or POINTS.get(pg.get("grade")) is None:
        return " "
    delta = dim["points"] - POINTS[pg["grade"]]
    return "^" if delta > 0 else "v" if delta < 0 else "="


# ── Render ─────────────────────────────────────────────────────────────────────


def render_text(dims: list[dict[str, Any]], agg: dict[str, Any], risks: list[dict[str, Any]],
                live: dict[str, Any], prev: dict[str, Any], fresh: int, total: int) -> None:
    rep = live["reputation"].get("trading", {})
    print("=" * 72)
    print(f"  gclaw HARNESS GRADE:  {agg['letter']}    (score {agg['score']:.0f}/100)")
    if agg["capped_by"]:
        print(f"  not higher because:  {agg['capped_by']}  "
              f"(uncapped would be {agg['provisional_letter']}/{agg['provisional_score']:.0f})")
    if agg["regression"]:
        print(f"  ** REGRESSION DETECTED: {agg['regression']} **")
    print(f"  {fresh}/{total} evals ran fresh this invocation")
    print("=" * 72)
    print(f"  {'dimension':<32}{'grade':>6}{'':>3}{'detail':<28}")
    print("  " + "-" * 68)
    for d in dims:
        floor = " (floor)" if d["floor"] else ""
        print(f"  {d['name'][:31]:<32}{d['grade']:>6}{_arrow(d, prev):>3}  {d['number'][:26]:<26}{floor}")
    print("  " + "-" * 68)
    print(f"  live KPIs:  expectancy ${float(rep.get('expectancy_usd', 0) or 0):.2f}   "
          f"win {float(rep.get('win_rate', 0) or 0):.0%}   "
          f"realized ${float(rep.get('realized_pnl_usd', 0) or 0):.2f}   "
          f"drawdown {float(live['breaker'].get('drawdown_pct', 0) or 0):.1f}%")
    print("\n  TOP RISKS (severity-ranked, independent of the letter):")
    for i, r in enumerate(risks, 1):
        print(f"   {i}. [{r['grade']}] {r['name']} — {r['why']}")
    if risks:
        print(f"\n  FIX FIRST:  {risks[0]['name']} — {risks[0]['why']}")
    print()


def main() -> int:
    quick = "--quick" in sys.argv
    as_json = "--json" in sys.argv
    with_judge = "--with-judge" in sys.argv
    modules = ("judge_power", "cost_truth", "feature_parity", "tool_budget")
    evals = {m: run_eval(m, quick) for m in modules}
    fresh = sum(1 for v in evals.values() if v is not None)
    live = load_live()
    prev = load_last()
    dims = [
        score_judge(evals["judge_power"]), score_cost(evals["cost_truth"]),
        score_parity(evals["feature_parity"]), score_mc(live), score_live(live),
        score_calibration(live), score_edge(live), score_hygiene(evals["tool_budget"]),
        score_decision_quality(with_judge),
    ]
    agg = aggregate(dims, prev)
    risks = top_risks(dims, live)
    rep = live["reputation"].get("trading", {})
    record = {
        "grade": agg["letter"], "score": agg["score"], "provisional": agg["provisional_score"],
        "capped_by": agg["capped_by"], "regression": agg["regression"],
        "dimensions": [{"name": d["name"], "grade": d["grade"], "number": d["number"]} for d in dims],
        "kpis": {k: rep.get(k) for k in ("expectancy_usd", "win_rate", "realized_pnl_usd")},
        "fresh_evals": fresh, "git_sha": _git_sha(),
    }
    append_history(record)
    if as_json:
        print(json.dumps(record))
    else:
        render_text(dims, agg, risks, live, prev, fresh, len(modules))
    if "--fail-under" in sys.argv:
        want = sys.argv[sys.argv.index("--fail-under") + 1].upper()
        if POINTS.get(agg["letter"], 0) < POINTS.get(want, 0):
            return 1
    return 0


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "-C", str(SCRIPTS.parent), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
