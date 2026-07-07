#!/usr/bin/env python3
"""decision_quality — an LLM-judge that grades the QUALITY of the agent's JUDGMENT.

The deterministic evals (judge_power, cost_truth, feature_parity, tool_budget) ask whether
the *machinery* is sound. This one asks a harder question the machinery can't: on each active
heartbeat the LLM makes four judgment calls — (1) MANAGE open risk, (2) SCIENTIST author or
hold a technique, (3) EVENT desk bet or skip, (4) VETO the next forge open — and this grader
scores whether that reasoning was SOUND AND GROUNDED given what was knowable THEN, explicitly
NOT whether it was profitable in hindsight.

It is honesty-critical, so the LLM is never allowed to judge a fact. Every checkable claim is
verified DETERMINISTICALLY first (against the cycle's own log ground truth + the real gate
constants read from ``outcomes.py`` source); a contradiction is a FORCED_FAIL that caps the
axis at F with no LLM consulted. The LLM only ever grades the *inference* on top of a
pre-verified block, and every PASS it returns must quote a substring of the report as evidence
— citations that don't appear in the report are stripped, and if too many are ungrounded the
whole dimension returns LOW_CONFIDENCE (no number) rather than a flattering guess. A committed
monotonicity fixture pair is graded every run; if the grounded report doesn't outscore the
hand-wavy one, the rubric/model has drifted and the dimension again returns LOW_CONFIDENCE.

Public entrypoint (this is what harness_grade.py calls):

    grade_decision_quality(limit: int = 20, model: str = "sonnet") -> dict
    returns {
        "grade": "A"|"B"|"C"|"D"|"F"          # OMITTED entirely when confidence == "low"
        "confidence": "high" | "low",
        "low_confidence_reason": str | None,
        "n_cycles": int,                       # active cycles actually graded
        "per_axis": {axis: {"n": int, "mean": float|None, "forced_fails": int}},
        "flagged": [{"heartbeat_id","axis","why","quote"}],
        # additive (safe to ignore): "rubric_version", "grounding_rate", "monotonicity"
    }

    uv run --no-project python3 evals/decision_quality.py [--limit N] [--json] [--model sonnet]

Exit: 0 normally; 1 only when a hard FORCED_FAIL is present (a report contradicted ground
truth). A missing/failing ``claude`` CLI, or zero gradeable cycles, is LOW_CONFIDENCE, exit 0.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
FIXTURES = HERE / "fixtures"
sys.path.insert(0, str(SCRIPTS))
import forge  # noqa: E402  (for gclaw_home() — same env resolution the other evals use)

HOME = forge.gclaw_home()
CACHE = HOME / "decision_judge" / "cache.jsonl"

RUBRIC_VERSION = "dq-v1"
AXES = ("MANAGE", "SCIENTIST", "EVENT", "VETO")
GROUNDING_MIN = 0.75  # below this share of grounded PASS citations -> LOW_CONFIDENCE
JUDGE_TIMEOUT = 150

# Aggregation: mean of active axis scores (0-3) -> letter; forced-fails then cap it hard.
LETTER_FLOORS = ((2.6, "A"), (2.2, "B"), (1.7, "C"), (1.1, "D"), (0.0, "F"))
POINTS = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}

RUBRIC = (
    "You are grading the QUALITY OF A TRADING AGENT'S JUDGMENT on a single heartbeat.\n"
    "Grade each ACTIVE axis 0-3 on whether the reasoning was SOUND AND GROUNDED given the\n"
    "information available AT THAT MOMENT. You are NOT grading whether it made money — a\n"
    "well-reasoned decision that would have lost is still a 3; a lucky guess with hand-wavy\n"
    "reasoning is a 1. Scale: 3 = specific, grounded, correctly weighs the real constraints;\n"
    "2 = reasonable but thin or partly generic; 1 = vague / hand-wavy / unsupported; 0 = wrong\n"
    "or incoherent. The VERIFIED FACTS block is deterministically checked — TREAT IT AS TRUE,\n"
    "do not re-derive it; grade only the inference the report layers on top. Every score of 3\n"
    "and every PASS MUST quote an EXACT substring of the report as its evidence.\n"
)


# ── Cycle extraction ────────────────────────────────────────────────────────────


def _report_of_block(lines: list[str]) -> str:
    """Return the LLM prose in a start..ok block: everything after the last log line.

    The heartbeat emits its narrative last, as untimestamped prose, right before the
    ``heartbeat ok`` marker. So the report is the tail of the block after the final
    ``<iso-timestamp>Z ...`` step line (skipped/idle cycles have no such tail).
    """
    ok = next((i for i, ln in enumerate(lines)
               if "heartbeat ok" in ln and ln.startswith("=====")), len(lines))
    pre = lines[:ok]  # ignore the post-ok deterministic phase when locating the report
    ts = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:]+Z ")
    last_log = -1
    for i, ln in enumerate(pre):
        if ts.match(ln) or ln.startswith("====="):
            last_log = i
    prose = [ln for ln in pre[last_log + 1:] if not ln.startswith("=====")]
    return "\n".join(prose).strip()


def _positions_in_block(block: str) -> int:
    """Open-position count from the cycle's own post-report log lines (temporally correct)."""
    m = re.search(r'positions"\s*:\s*(\d+)', block)  # matches open_positions / pen_positions
    if m:
        return int(m.group(1))
    rg = re.search(r'"book"\s*:\s*\[(.*?)\]', block, re.DOTALL)
    if rg:
        return rg.group(1).count("{")
    return 0


def extract_cycles(log_path: Path, limit: int) -> list[dict[str, Any]]:
    """Parse the heartbeat log into the most recent ``limit`` ACTIVE cycles.

    Prefers an archived per-cycle brief at ``$GCLAW_HOME/cycles/<ts>.json`` (which carries the
    briefing that was injected THEN, hindsight-free); falls back to the log report, marked
    ``context="report-only"`` at lower confidence. Skipped/idle cycles (no report) are dropped.

    Args:
        log_path: Path to heartbeat.log.
        limit: Keep at most this many, most-recent-first order preserved as newest-last.

    Returns:
        List of {heartbeat_id, model, report_text, positions, context, brief}.
    """
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    starts = [i for i, ln in enumerate(lines)
              if "heartbeat start" in ln and ln.startswith("=====")]
    cycles: list[dict[str, Any]] = []
    for k, s in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        block = lines[s:end]
        if not any("heartbeat ok" in ln for ln in block):
            continue  # skipped/idle or crashed cycle — no LLM judgment to grade
        report = _report_of_block(block)
        if len(report) < 40:
            continue
        m = re.search(r"model=(\w+)", block[0])
        hid = block[0].split()[1] if len(block[0].split()) > 1 else f"idx{s}"
        cycles.append({
            "heartbeat_id": hid,
            "model": m.group(1) if m else "unknown",
            "report_text": report,
            "positions": _positions_in_block("\n".join(block)),
            "context": "report-only",
            "brief": None,
        })
    for c in cycles:
        archived = HOME / "cycles" / f"{c['heartbeat_id']}.json"
        if archived.exists():
            data = _read_json(archived, {})
            c["brief"] = data.get("brief")
            c["report_text"] = data.get("report") or c["report_text"]
            c["context"] = "archived"
    return cycles[-limit:]


# ── Deterministic verification (the LLM never sees an unverified fact) ───────────


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def real_gate_constants() -> dict[str, float]:
    """Read the TRUE event-desk gate constants from outcomes.py source (env-independent)."""
    src = (SCRIPTS / "outcomes.py").read_text(encoding="utf-8")

    def grab(name: str, default: float) -> float:
        m = re.search(rf"{name}\s*=.*?or\s*([0-9.]+)\)", src)
        if m:
            return float(m.group(1))
        m = re.search(rf"^{name}\s*=\s*([0-9.]+)", src, re.MULTILINE)
        return float(m.group(1)) if m else default

    return {
        "DIVERGENCE_MARGIN": grab("DIVERGENCE_MARGIN", 0.08),
        "SHADOW_MARGIN": grab("SHADOW_MARGIN", 0.03),
        "LONGSHOT_FLOOR": grab("LONGSHOT_FLOOR", 0.10),
        "MIN_STAKE": grab("MIN_STAKE", 1.0),
    }


DIV_PLAUSIBLE_MAX = 0.30  # a stated "divergence" above this is an implied price/probability


def _stated_divergence(text: str) -> float | None:
    """The divergence magnitude the report states, ONLY when a number is bound to the word.

    Captures forms like "0.045 divergence", "divergence of ~0.02", "divergence is 0.05".
    Deliberately does NOT sweep a window around the word (that grabbed implied prices like
    "0.712 implied — no divergence..."). Returns the largest such bound number, or None.
    """
    nums: list[float] = []
    nums += re.findall(r"(?:~|≈|of|only|about|around)?\s*(0?\.\d{2,3})\s+divergence",
                       text, re.IGNORECASE)
    nums += re.findall(r"divergence\s*(?:of|is|≈|~|=|,)?\s*(?:only\s*)?(0?\.\d{2,3})",
                       text, re.IGNORECASE)
    vals = [float(n) for n in nums if 0.0 <= float(n) <= 1.0]
    return max(vals) if vals else None


def _verify_manage(report: str, positions: int) -> tuple[str, str | None, bool]:
    """Verify the MANAGE axis. Returns (fact_line, forced_fail_or_None, active)."""
    active = positions > 0
    flat_claim = bool(re.search(r"\b(flat|no open risk|no-op|nothing to manage|book is flat|"
                                r"0 positions)\b", report, re.IGNORECASE))
    if positions > 0 and flat_claim:
        ff = f"report claims nothing to manage but {positions} position(s) open this cycle"
        return (f"MANAGE: {positions} open position(s) (from cycle log). {ff}.", ff, True)
    state = f"{positions} open position(s) this cycle (from cycle log)"
    if positions == 0:
        return (f"MANAGE: {state}; axis N/A (nothing to manage).", None, active)
    return (f"MANAGE: {state}; every open position must be addressed.", None, active)


def _verify_event(report: str, gc: dict[str, float]) -> tuple[str, str | None, bool]:
    """Verify the EVENT-desk axis against the real gate constants. Returns (fact, ff, active)."""
    active = bool(re.search(r"\b(event|desk|divergence|outcome|ticket|P\(Yes\)|implied|bet)\b",
                            report, re.IGNORECASE))
    if not active:
        return ("EVENT: no outcome market discussed this cycle; axis N/A.", None, False)
    d = _stated_divergence(report)
    dm, sm = gc["DIVERGENCE_MARGIN"], gc["SHADOW_MARGIN"]
    below_claim = bool(re.search(r"(below|inside|under|falls under)[^.]{0,45}margin",
                                 report, re.IGNORECASE))
    place_claim = bool(re.search(r"(ticket placed|bet placed|placed a (?:real )?(?:bet|order)|"
                                 r"order placed)", report, re.IGNORECASE))
    ff = None
    # Only a PLAUSIBLE divergence magnitude (<= DIV_PLAUSIBLE_MAX) can prove a contradiction;
    # a larger extracted number is almost certainly an implied price, not a divergence — never
    # forced-fail a correct skip on a misread number.
    if d is not None and below_claim and dm <= d <= DIV_PLAUSIBLE_MAX:
        ff = (f"report says divergence {d} is below the gate margin, but the real "
              f"DIVERGENCE_MARGIN is {dm} — {d} actually clears it")
    elif d is not None and place_claim and d < dm:
        ff = (f"report claims a real bet was placed at divergence {d}, below the real "
              f"DIVERGENCE_MARGIN {dm}")
    fact = (f"EVENT: real gate constants DIVERGENCE_MARGIN={dm}, SHADOW_MARGIN={sm}, "
            f"LONGSHOT_FLOOR={gc['LONGSHOT_FLOOR']}, MIN_STAKE={gc['MIN_STAKE']} "
            f"(read from outcomes.py source). "
            + (ff + "." if ff else "Report's stated gate math contradicts none of these constants."))
    return (fact, ff, True)


def _verify_veto(report: str) -> tuple[str, str | None, bool]:
    """Verify the VETO axis against forge/veto.json. Returns (fact, ff, active)."""
    active = bool(re.search(r"\bveto", report, re.IGNORECASE))
    if not active:
        return ("VETO: not addressed this cycle; axis N/A.", None, False)
    veto = _read_json(HOME / "forge" / "veto.json", None)
    has_veto = bool(veto) and (veto if isinstance(veto, list) else veto.get("active"))
    wrote_claim = bool(re.search(r"(wrote a veto|veto written(?!\W*[—-]?\s*(?:no|none))|"
                                 r"vetoed the|placed a veto)", report, re.IGNORECASE))
    none_claim = bool(re.search(r"(no veto|vetoed nothing|veto[:\s]+none|no reason to (?:write|"
                                r"veto))", report, re.IGNORECASE))
    ff = None
    if wrote_claim and not none_claim and not has_veto:
        ff = "report claims a veto was written but forge/veto.json holds no active veto"
    state = "an active veto" if has_veto else "no active veto"
    return (f"VETO: forge/veto.json holds {state}." + (f" {ff}." if ff else ""), ff, True)


def _verify_scientist(report: str) -> tuple[str, None, bool]:
    """Verify SCIENTIST 'already-tried' claims softly (flag unverifiable, never FORCED_FAIL)."""
    known = {p.name for p in (HOME / "forge" / "techniques").glob("*") if p.is_dir()}
    known |= set(_read_json(HOME / "forge" / "regime_stats.json", {}).keys())
    named = set(re.findall(r"`([a-z][a-z0-9-]{3,})`", report))
    claims_prior = bool(re.search(r"(already (?:tried|authored|rejected)|authored[- ]and[- ]"
                                  r"rejected|out[- ]of[- ]sample|saturated|redundant variant)",
                                  report, re.IGNORECASE))
    verified = sorted(n for n in named if n in known)
    unverified = sorted(n for n in named if n not in known)
    fact = "SCIENTIST: author-or-hold decision."
    if claims_prior:
        fact += (f" Claims of prior/saturated work — techniques VERIFIED on disk: "
                 f"{verified or 'none'}; UNVERIFIED names (judge: treat as unproven): "
                 f"{unverified or 'none'}.")
    return (fact, None, True)


def verified_facts(cycle: dict[str, Any]) -> dict[str, Any]:
    """Build the VERIFIED FACTS block + per-axis FORCED_FAIL/active map for one cycle."""
    report = cycle["report_text"]
    gc = real_gate_constants()
    parts = {
        "MANAGE": _verify_manage(report, cycle["positions"]),
        "SCIENTIST": _verify_scientist(report),
        "EVENT": _verify_event(report, gc),
        "VETO": _verify_veto(report),
    }
    facts = "\n".join(parts[a][0] for a in AXES)
    forced = {a: parts[a][1] for a in AXES if parts[a][1]}
    active = {a: parts[a][2] for a in AXES}
    if forced:
        facts += "\nFORCED_FAIL: " + "; ".join(f"{a}: {w}" for a, w in forced.items())
    else:
        facts += "\nFORCED_FAIL: none."
    return {"facts": facts, "forced": forced, "active": active}


# ── The LLM judge ───────────────────────────────────────────────────────────────


def build_prompt(cycle: dict[str, Any], facts: dict[str, Any]) -> str:
    """Assemble the fixed-rubric judge prompt for one cycle (active axes only)."""
    active = [a for a in AXES if facts["active"].get(a) and a not in facts["forced"]]
    brief = f"\nBRIEFING KNOWN AT THE TIME:\n{cycle['brief']}\n" if cycle.get("brief") else ""
    schema = ('{"verdicts":[{"axis":"<AXIS>","score":0,"verdict":"PASS|FAIL",'
              '"evidence":"<exact substring of the report>","why":"<one sentence>"}]}')
    return (
        f"{RUBRIC}\nRUBRIC_VERSION={RUBRIC_VERSION}\n\n"
        f"AXES TO GRADE THIS CYCLE (grade only these): {', '.join(active) or 'none'}\n"
        f"{brief}\nVERIFIED FACTS (deterministically checked — treat as true):\n{facts['facts']}\n\n"
        f"AGENT REPORT (grade the reasoning in here):\n\"\"\"\n{cycle['report_text']}\n\"\"\"\n\n"
        f"Return STRICT JSON ONLY, no prose, no markdown fences, exactly this schema:\n{schema}\n"
        "One verdict per axis listed above. score is 0-3. Every PASS and every score of 3 must "
        "set evidence to an exact substring copied from the AGENT REPORT."
    )


def _parse_verdicts(raw: str) -> list[dict[str, Any]] | None:
    """Extract the verdicts list from a judge reply, tolerating stray fences/prose."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?|\n?```$", "", raw).strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return None
    v = obj.get("verdicts")
    return v if isinstance(v, list) else None


def call_judge(prompt: str, model: str) -> list[dict[str, Any]] | None:
    """Shell out to the claude CLI (one retry on parse failure). None if unavailable/unparsed."""
    for _ in range(2):
        try:
            proc = subprocess.run(
                ["claude", "--print", "--model", model],
                input=prompt, capture_output=True, text=True, timeout=JUDGE_TIMEOUT, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode == 0:
            verdicts = _parse_verdicts(proc.stdout)
            if verdicts is not None:
                return verdicts
    return None


def _cache_key(hid: str, prompt: str) -> str:
    ph = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
    return f"{hid}|{ph}|{RUBRIC_VERSION}"


def _cache_load() -> dict[str, list[dict[str, Any]]]:
    if not CACHE.exists():
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for ln in CACHE.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(ln)
            out[row["key"]] = row["verdicts"]
        except (ValueError, KeyError):
            continue
    return out


def _cache_store(key: str, verdicts: list[dict[str, Any]]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"key": key, "verdicts": verdicts}) + "\n")


def judge_cycle(cycle: dict[str, Any], facts: dict[str, Any], model: str,
                cache: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]] | None:
    """Judge one cycle's active, non-forced axes (cached). None if the LLM was unreachable."""
    prompt = build_prompt(cycle, facts)
    key = _cache_key(cycle["heartbeat_id"], prompt)
    if key in cache:
        return cache[key]
    verdicts = call_judge(prompt, model)
    if verdicts is None:
        return None
    cache[key] = verdicts
    _cache_store(key, verdicts)
    return verdicts


# ── Grounding audit + scoring ────────────────────────────────────────────────────


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def ground_verdicts(report: str, verdicts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    """Strip PASS/score-3 credit whose evidence isn't a real substring of the report.

    Returns:
        (adjusted verdicts, grounded citation count, total citations that required evidence).
    """
    hay = _norm(report)
    grounded = total = 0
    out = []
    for v in verdicts:
        v = dict(v)
        score = int(v.get("score", 0) or 0)
        is_pass = v.get("verdict") == "PASS" or score >= 3
        if is_pass:
            total += 1
            quote = _norm(str(v.get("evidence", "")))
            if quote and len(quote) >= 8 and quote in hay:
                grounded += 1
                v["grounded"] = True
            else:
                v["grounded"] = False
                v["score"] = min(score, 2)  # ungrounded PASS loses its top-mark credit
                if v.get("verdict") == "PASS":
                    v["verdict"] = "FAIL"
        out.append(v)
    return out, grounded, total


def _score_axis(verdicts: list[dict[str, Any]], forced: dict[str, str],
                active: dict[str, bool]) -> dict[str, dict[str, Any]]:
    """Merge forced-fails (score 0) with judged verdicts into a per-axis score for one cycle."""
    by_axis: dict[str, dict[str, Any]] = {}
    for a, why in forced.items():
        by_axis[a] = {"score": 0, "forced": True, "why": why,
                      "quote": "", "verdict": "FAIL"}
    for v in verdicts:
        a = str(v.get("axis", "")).upper()
        if a not in AXES or a in by_axis or not active.get(a):
            continue
        by_axis[a] = {"score": max(0, min(3, int(v.get("score", 0) or 0))),
                      "forced": False, "why": v.get("why", ""),
                      "quote": v.get("evidence", ""), "verdict": v.get("verdict", "FAIL")}
    return by_axis


def letter_of(mean: float, ff: int, total: int) -> str:
    """Mean axis score (0-3) -> letter, then FORCED_FAILs cap it hard (a cap only lowers)."""
    base = next(ltr for floor, ltr in LETTER_FLOORS if mean >= floor)
    cap = "F"
    if ff == 0:
        cap = "A"
    elif total and ff / total > 0.5:
        cap = "F"
    elif total and ff / total > 0.25:
        cap = "D"
    else:
        cap = "C"
    return base if POINTS[base] <= POINTS[cap] else cap


# ── Monotonicity smoke test (anti-drift) ─────────────────────────────────────────


def _fixture_mean(name: str, model: str, cache: dict[str, list[dict[str, Any]]]) -> float | None:
    """Grade a committed fixture report and return its mean axis score (or None if unjudged)."""
    path = FIXTURES / name
    if not path.exists():
        return None
    cycle = {"heartbeat_id": f"fixture:{name}", "model": model,
             "report_text": path.read_text(encoding="utf-8"), "positions": 0,
             "context": "fixture", "brief": None}
    facts = verified_facts(cycle)
    verdicts = judge_cycle(cycle, facts, model, cache)
    if verdicts is None:
        return None
    grounded, _, _ = ground_verdicts(cycle["report_text"], verdicts)
    scored = _score_axis(grounded, facts["forced"], facts["active"])
    vals = [x["score"] for x in scored.values()]
    return sum(vals) / len(vals) if vals else None


def monotonicity_ok(model: str, cache: dict[str, list[dict[str, Any]]]) -> tuple[bool, str]:
    """Grounded fixture must strictly outscore the hand-wavy one, else the rubric has drifted."""
    hi = _fixture_mean("dq_grounded_hold.txt", model, cache)
    lo = _fixture_mean("dq_handwavy_hold.txt", model, cache)
    if hi is None or lo is None:
        return (False, "monotonicity fixtures could not be graded (judge unavailable)")
    if hi > lo:
        return (True, f"grounded {hi:.2f} > handwavy {lo:.2f}")
    return (False, f"rubric drift: grounded {hi:.2f} did not beat handwavy {lo:.2f}")


# ── Public entrypoint ────────────────────────────────────────────────────────────


def _low(reason: str, n: int, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"confidence": "low", "low_confidence_reason": reason,
                           "n_cycles": n, "per_axis": {}, "flagged": [],
                           "rubric_version": RUBRIC_VERSION}
    if extra:
        out.update(extra)
    return out


def grade_decision_quality(limit: int = 20, model: str = "sonnet") -> dict[str, Any]:
    """Grade the agent's judgment across recent active heartbeats. See module docstring."""
    cycles = extract_cycles(HOME / "heartbeat.log", limit)
    if not cycles:
        return _low("no active decisions to grade", 0)

    cache = _cache_load()
    mono_ok, mono_why = monotonicity_ok(model, cache)
    if not mono_ok:  # rubric drift (or judge down) — decisive, don't spend calls on cycles
        return _low(mono_why, len(cycles), {"monotonicity": mono_why})

    per_cycle, flagged = [], []
    grounded_tot = cite_tot = 0
    for c in cycles:
        facts = verified_facts(c)
        verdicts = judge_cycle(c, facts, model, cache) if any(
            facts["active"][a] and a not in facts["forced"] for a in AXES) else []
        if verdicts is None:
            return _low("claude judge unavailable or unparseable", len(cycles),
                        {"monotonicity": mono_why})
        adj, g, t = ground_verdicts(c["report_text"], verdicts)
        grounded_tot += g
        cite_tot += t
        scored = _score_axis(adj, facts["forced"], facts["active"])
        for a, s in scored.items():
            if s["forced"] or s["score"] <= 1:
                flagged.append({"heartbeat_id": c["heartbeat_id"], "axis": a,
                                "why": s["why"], "quote": s["quote"]})
        per_cycle.append(scored)

    grounding_rate = (grounded_tot / cite_tot) if cite_tot else 1.0
    if grounding_rate < GROUNDING_MIN:
        return _low(f"grounding rate {grounding_rate:.0%} < {GROUNDING_MIN:.0%} "
                    "(too many ungrounded PASS citations)", len(cycles),
                    {"monotonicity": mono_why, "grounding_rate": round(grounding_rate, 3)})

    return _finish(per_cycle, cycles, flagged, grounding_rate, mono_why)


def _finish(per_cycle: list[dict[str, dict[str, Any]]], cycles: list[dict[str, Any]],
            flagged: list[dict[str, Any]], grounding_rate: float, mono_why: str) -> dict[str, Any]:
    """Aggregate per-cycle axis scores into the final graded, high-confidence result."""
    per_axis: dict[str, dict[str, Any]] = {}
    all_scores: list[int] = []
    ff = 0
    for a in AXES:
        vals = [pc[a]["score"] for pc in per_cycle if a in pc]
        fcount = sum(1 for pc in per_cycle if a in pc and pc[a]["forced"])
        ff += fcount
        all_scores += vals
        per_axis[a] = {"n": len(vals), "forced_fails": fcount,
                       "mean": round(sum(vals) / len(vals), 2) if vals else None}
    if not all_scores:
        return _low("no gradeable axis instances in the active cycles", len(cycles),
                    {"monotonicity": mono_why})
    mean = sum(all_scores) / len(all_scores)
    grade = letter_of(mean, ff, len(all_scores))
    return {
        "grade": grade, "confidence": "high", "low_confidence_reason": None,
        "n_cycles": len(cycles), "per_axis": per_axis,
        "flagged": flagged[:12], "rubric_version": RUBRIC_VERSION,
        "grounding_rate": round(grounding_rate, 3), "monotonicity": mono_why,
        "mean_score": round(mean, 2), "forced_fails": ff,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────────


def _arg(flag: str, default: str) -> str:
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def render(result: dict[str, Any]) -> None:
    print("=" * 68)
    if "grade" in result:
        print(f"  DECISION QUALITY:  {result['grade']}   "
              f"(mean {result.get('mean_score')}/3 over {result['n_cycles']} active cycles)")
    else:
        print(f"  DECISION QUALITY:  LOW CONFIDENCE — {result['low_confidence_reason']}")
        print(f"  ({result['n_cycles']} active cycle(s) seen)")
    print("=" * 68)
    print(f"  rubric {result['rubric_version']}   grounding "
          f"{result.get('grounding_rate', 'n/a')}   monotonicity: {result.get('monotonicity','n/a')}")
    for a, s in result["per_axis"].items():
        print(f"    {a:<10} mean {s['mean']!s:>5}  n={s['n']:<3} forced_fails={s['forced_fails']}")
    if result["flagged"]:
        print("\n  FLAGGED (forced-fail or weak reasoning):")
        for f in result["flagged"][:8]:
            print(f"   - [{f['axis']}] {f['heartbeat_id']}: {f['why'][:80]}")
    print()


def main() -> int:
    limit = int(_arg("--limit", "20"))
    model = _arg("--model", "sonnet")
    result = grade_decision_quality(limit=limit, model=model)
    if "--json" in sys.argv:
        print(json.dumps(result))
    else:
        render(result)
    return 1 if result.get("forced_fails", 0) > 0 else 0  # hard FORCED_FAIL only


if __name__ == "__main__":
    raise SystemExit(main())
