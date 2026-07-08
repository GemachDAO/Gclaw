"""Pins forge._session_at to known US-equity sessions across DST, so the closed-market
feature can't silently drift. Cross-language parity with intel.js sessionAt is verified
separately (a full-year hourly diff); this guards the Python definition itself.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import forge  # noqa: E402


def _ms(y: int, mo: int, d: int, h: int, mi: int) -> int:
    return int(datetime(y, mo, d, h, mi, tzinfo=UTC).timestamp() * 1000)


def test_summer_rth() -> None:
    # 2026-07-08 15:00 UTC = 11:00 EDT (UTC-4) — mid-session
    s = forge._session_at(_ms(2026, 7, 8, 15, 0))
    assert s["is_rth"] == 1 and s["session"] == "rth" and s["mins_to_open"] == 0


def test_winter_rth() -> None:
    # 2026-01-08 15:00 UTC = 10:00 EST (UTC-5) — DST off, still RTH
    s = forge._session_at(_ms(2026, 1, 8, 15, 0))
    assert s["is_rth"] == 1 and s["session"] == "rth"


def test_premarket_and_mins_to_open() -> None:
    # 2026-07-08 12:00 UTC = 08:00 EDT — pre-market, 90 min to the 09:30 open
    s = forge._session_at(_ms(2026, 7, 8, 12, 0))
    assert s["is_rth"] == 0 and s["session"] == "pre" and s["mins_to_open"] == 90


def test_afterhours() -> None:
    # 2026-07-08 21:00 UTC = 17:00 EDT — after the 16:00 close
    s = forge._session_at(_ms(2026, 7, 8, 21, 0))
    assert s["is_rth"] == 0 and s["session"] == "post"


def test_weekend_closed() -> None:
    # 2026-07-11 is a Saturday — closed regardless of the clock
    s = forge._session_at(_ms(2026, 7, 11, 15, 0))
    assert s["is_rth"] == 0 and s["session"] == "closed"


def test_overnight_closed() -> None:
    # 2026-07-08 04:00 UTC = 00:00 EDT — before pre-market
    s = forge._session_at(_ms(2026, 7, 8, 4, 0))
    assert s["session"] == "closed"
