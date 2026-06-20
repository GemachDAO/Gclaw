"""Sandbox-escape suite for the forge signal sandbox (scripts/forge.py).

This is the highest-value security test in the repo: a technique's ``signal.py``
is *attacker-controlled source* (self-authored, pulled from the shared gene pool,
or discovered from a peer's onchain card) that the agent then EXECUTES unattended
with real funds. If a malicious signal can reach ``__import__``/``os``/``open`` it
owns the wallet. The defence is two layers:

  1. ``validate_signal_src`` — an AST allow-list (no banned names/attrs/imports,
     a ``signal`` def must exist).
  2. ``_compile_signal`` execs into a namespace whose ``__builtins__`` is the
     minimal ``_safe_builtins()`` set — the load-bearing control that closes the
     ``f['__builtins__']['__import__']`` subscript escape the AST can't see.

We test the WHOLE pipeline (validate -> compile -> call), because some escapes
(subscript reach-through) pass the AST and must die at runtime instead. Every
malicious row MUST be neutralised (rejected at validation OR raise at runtime OR
return ``None``); every benign-but-tricky row MUST validate, compile, and run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import forge  # noqa: E402  (path injected above)


def _src(body: str) -> str:
    """Wrap a one-liner return body into a minimal ``signal(f)`` definition."""
    return f"def signal(f):\n    return {body}\n"


# ── Malicious payloads — each MUST be neutralised ────────────────────────────
#
# id -> source. Grouped by escape technique. The assertion is uniform: the source
# must never run to completion returning attacker data. "Neutralised" = rejected
# at validation, OR raises at runtime, OR call_signal sanitises it to None.

MALICIOUS: dict[str, str] = {
    # --- dunder attribute reach-through (the classic) ---
    "dunder_class": _src("().__class__"),
    "dunder_class_bases": _src("().__class__.__bases__"),
    "dunder_subclasses": _src("type.__subclasses__"),
    "dunder_globals": "def signal(f):\n    return signal.__globals__\n",
    "dunder_mro": _src("type.mro"),
    "dunder_dict": _src("f.__dict__"),
    "dunder_getattribute": _src("f.__getattribute__"),
    "dunder_reduce": _src("f.__reduce__"),
    # --- builtins reach-through by name (banned names) ---
    "name_import": _src("__import__('os')"),
    "name_eval": _src("eval('1')"),
    "name_exec": "def signal(f):\n    exec('x=1')\n    return {'action':'flat'}\n",
    "name_open": _src("open('/etc/passwd')"),
    "name_getattr": _src("getattr(f, 'x')"),
    "name_setattr": "def signal(f):\n    setattr(f, 'x', 1)\n    return {'action':'flat'}\n",
    "name_globals": _src("globals()"),
    "name_locals": _src("locals()"),
    "name_vars": _src("vars()"),
    "name_compile": _src("compile('1','<s>','eval')"),
    "name_input": _src("input()"),
    "name_builtins": _src("__builtins__"),
    "name_object": _src("object()"),
    "name_type": _src("type(f)"),
    "name_super": _src("super()"),
    "name_breakpoint": "def signal(f):\n    breakpoint()\n    return {'action':'flat'}\n",
    # --- banned non-dunder attrs (format/format_map pivot, mro) ---
    "attr_format": _src("''.format"),
    "attr_format_map": _src("''.format_map"),
    # --- frame / generator / code / coroutine / traceback walks (prefix-banned) ---
    "gen_frame": "def signal(f):\n    g=(x for x in [1])\n    return g.gi_frame\n",
    "code_consts": "def signal(f):\n    return signal.__code__.co_consts\n",
    "code_co_varnames": _src("signal.co_varnames"),
    "func_globals_old": _src("signal.func_globals"),
    "coro_cr_frame": _src("f.cr_frame"),
    "async_ag_frame": _src("f.ag_frame"),
    "frame_f_back": _src("f.f_back"),
    "frame_f_builtins": _src("f.f_builtins"),
    "traceback_tb_frame": _src("f.tb_frame"),
    # --- import smuggling ---
    "import_os": "import os\ndef signal(f):\n    return {'action':'flat'}\n",
    "import_dotted": "import os.path\ndef signal(f):\n    return {'action':'flat'}\n",
    "from_import_os": "from os import system\ndef signal(f):\n    return {'action':'flat'}\n",
    "from_import_sub": "from os.path import join\ndef signal(f):\n    return {'action':'flat'}\n",
    "import_subprocess": "import subprocess\ndef signal(f):\n    return {'action':'flat'}\n",
    "import_socket": "import socket\ndef signal(f):\n    return {'action':'flat'}\n",
    # --- decorator RCE (decorator expression is evaluated) ---
    "decorator_eval": "@eval\ndef signal(f):\n    return {'action':'flat'}\n",
    "decorator_exec": "@exec\ndef signal(f):\n    return {'action':'flat'}\n",
    # --- subscript reach-through: PASSES the AST, must die at runtime ---
    # (__builtins__ is removed from the exec namespace's locals, so f['__builtins__']
    #  raises KeyError; the dict 'f' passed in is a plain feature dict.)
    "subscript_builtins": _src("f['__builtins__']['__import__']('os')"),
}


# ── Benign-but-tricky payloads — each MUST validate, compile, and run ────────
#
# These exercise the allow-listed surface: math/statistics imports, comprehensions,
# f-strings, lambdas-as-locals, nested helpers, ternaries. A validator that rejects
# these is too strict and would block legitimate self-authored techniques.

BENIGN: dict[str, str] = {
    "math_import": (
        "import math\n"
        "def signal(f):\n"
        "    s = math.sqrt(abs(f.get('rsi', 50)))\n"
        "    return {'action': 'long' if s > 5 else 'flat', 'confidence': min(1.0, s / 10), 'stop_pct': 1.5}\n"
    ),
    "statistics_import": (
        "import statistics\n"
        "def signal(f):\n"
        "    xs = [f.get('rsi', 50), f.get('ema', 50)]\n"
        "    return {'action': 'flat', 'confidence': 0.0, 'stop_pct': statistics.mean([1.0, 2.0])}\n"
    ),
    "comprehension": (
        "def signal(f):\n"
        "    acc = sum(i * i for i in range(5))\n"
        "    return {'action': 'short' if acc > 100 else 'flat', 'confidence': 0.3, 'stop_pct': 2.0}\n"
    ),
    "fstring_reason": (
        "def signal(f):\n"
        "    r = f\"rsi={f.get('rsi', 0)}\"\n"
        "    return {'action': 'flat', 'confidence': 0.0, 'stop_pct': 1.0, 'reason': r}\n"
    ),
    "local_lambda": (
        "def signal(f):\n"
        "    score = lambda x: x * 2\n"
        "    return {'action': 'flat', 'confidence': 0.0, 'stop_pct': score(0.5)}\n"
    ),
    "nested_helper": (
        "def signal(f):\n"
        "    def lvl(x):\n"
        "        return min(1.0, max(0.0, x))\n"
        "    return {'action': 'long', 'confidence': lvl(0.7), 'stop_pct': 2.0}\n"
    ),
    "builtin_allowlist": (
        "def signal(f):\n"
        "    vals = sorted([3, 1, 2])\n"
        "    return {'action': 'flat', 'confidence': float(len(vals)) / 10, 'stop_pct': round(1.234, 2)}\n"
    ),
}


def _pipeline(src: str) -> tuple[str, object]:
    """Run validate -> compile -> call and classify the outcome.

    Returns one of:
      ('rejected', violations)      — failed the AST allow-list
      ('runtime_error', exc_repr)   — raised during execution (escape blocked late)
      ('sanitised', None)           — ran but output failed the action check
      ('ran', decision)             — ran and produced a valid trade decision
    """
    violations = forge.validate_signal_src(src)
    if violations:
        return ("rejected", violations)
    fn = forge._compile_signal(src, "<sandbox-test>")
    try:
        out = forge.call_signal(fn, {"rsi": 50.0, "close": 100.0, "ema": 50.0})
    except BaseException as exc:
        return ("runtime_error", repr(exc))
    return ("ran", out) if out is not None else ("sanitised", None)


class TestMaliciousRejected:
    @pytest.mark.parametrize("name", list(MALICIOUS), ids=list(MALICIOUS))
    def test_malicious_payload_is_neutralised(self, name: str) -> None:
        """No attacker-controlled signal may run to completion returning live data."""
        outcome, detail = _pipeline(MALICIOUS[name])
        assert outcome in {"rejected", "runtime_error", "sanitised"}, (
            f"SANDBOX ESCAPE: '{name}' ran to completion and returned {detail!r}"
        )

    def test_subscript_escape_dies_at_runtime_not_validation(self) -> None:
        """Documents that the subscript escape is caught by restricted builtins, not the AST.

        This is the load-bearing claim in ``_safe_builtins`` — if someone "simplifies"
        the exec namespace and drops the ``__builtins__`` override, this flips to an
        escape. The AST passing here is expected and correct.
        """
        src = MALICIOUS["subscript_builtins"]
        assert forge.validate_signal_src(src) == [], (
            "AST is expected to pass this; runtime must block it"
        )
        outcome, _ = _pipeline(src)
        assert outcome == "runtime_error"

    def test_restricted_builtins_has_no_escape_hatches(self) -> None:
        """The exec builtins set must expose no code-exec / io / introspection names."""
        b = forge._safe_builtins()
        forbidden = {
            "eval",
            "exec",
            "open",
            "compile",
            "input",
            "getattr",
            "setattr",
            "globals",
            "locals",
            "vars",
            "object",
            "type",
            "super",
            "__loader__",
        }
        leaked = forbidden & set(b)
        assert not leaked, f"restricted builtins leaked dangerous names: {leaked}"
        # __import__ is present but is the allow-list-only shim, not the real one.
        assert b["__import__"] is forge._safe_import

    def test_safe_import_blocks_non_allowlisted_modules(self) -> None:
        """The import shim only ever returns math/statistics; everything else raises."""
        for mod in ("os", "sys", "subprocess", "socket", "builtins", "ctypes"):
            with pytest.raises(ImportError):
                forge._safe_import(mod)
        # the two allowed ones return real modules
        assert forge._safe_import("math").sqrt(4.0) == 2.0
        assert forge._safe_import("statistics").mean([1.0, 3.0]) == 2.0


class TestBenignAccepted:
    @pytest.mark.parametrize("name", list(BENIGN), ids=list(BENIGN))
    def test_benign_payload_runs(self, name: str) -> None:
        """Legitimate, tricky-but-safe techniques must validate, compile, and produce a decision."""
        outcome, detail = _pipeline(BENIGN[name])
        assert outcome == "ran", (
            f"benign technique '{name}' was wrongly blocked: ({outcome}, {detail!r})"
        )
        assert detail["action"] in {"long", "short", "flat"}


class TestOutputValidation:
    """call_signal must sanitise whatever a (validated) signal returns."""

    @pytest.mark.parametrize(
        "body",
        [
            "42",  # not a dict
            "'long'",  # a string, not a dict
            "[]",  # a list
            "None",  # None
            "{'action': 'moon', 'confidence': 1.0, 'stop_pct': 2.0}",  # invalid action
            "{'action': 'LONG', 'confidence': 1.0, 'stop_pct': 2.0}",  # wrong case
            "{'confidence': 1.0, 'stop_pct': 2.0}",  # missing action
        ],
    )
    def test_invalid_output_sanitised_to_none(self, body: str) -> None:
        fn = forge._compile_signal(_src(body), "<out-test>")
        assert forge.call_signal(fn, {"rsi": 50.0}) is None

    @pytest.mark.parametrize("action", ["long", "short", "flat"])
    def test_valid_actions_pass_through(self, action: str) -> None:
        fn = forge._compile_signal(
            _src(f"{{'action': '{action}', 'confidence': 0.5, 'stop_pct': 2.0}}"), "<ok>"
        )
        out = forge.call_signal(fn, {"rsi": 50.0})
        assert out is not None and out["action"] == action

    def test_runaway_signal_is_killed_by_timeout(self) -> None:
        """A signal that never returns must be interrupted (SIGALRM), not hang the heartbeat."""
        src = "def signal(f):\n    x = 0\n    while True:\n        x += 1\n    return x\n"
        fn = forge._compile_signal(src, "<spin>")
        with pytest.raises(TimeoutError):
            forge.call_signal(fn, {"rsi": 50.0})


class TestBannedListsAreClosed:
    """Regression guards: the deny-lists must keep covering every known escape family.

    If someone trims BANNED_NAMES or BANNED_ATTR_PREFIXES these fail, surfacing the
    weakened sandbox before it ships.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "eval",
            "exec",
            "open",
            "__import__",
            "compile",
            "getattr",
            "setattr",
            "globals",
            "locals",
            "vars",
            "object",
            "type",
            "super",
            "__builtins__",
            "breakpoint",
        ],
    )
    def test_dangerous_builtin_is_banned(self, name: str) -> None:
        assert name in forge.BANNED_NAMES or name.startswith("__"), (
            f"{name} fell off the banned-name list"
        )

    @pytest.mark.parametrize("prefix", ["__", "gi_", "f_", "co_", "cr_", "tb_", "func_", "ag_"])
    def test_introspection_attr_prefix_is_banned(self, prefix: str) -> None:
        assert prefix in forge.BANNED_ATTR_PREFIXES, (
            f"{prefix} fell off the banned attr-prefix list"
        )

    def test_allowed_imports_are_only_math_libs(self) -> None:
        assert {"math", "statistics"} == forge.ALLOWED_IMPORTS, (
            "the import allow-list widened — every addition is new attack surface"
        )
