"""League calendar — 1 wall day = 1 league day, identity mapping (minimal §5).

No translation layer: `date` strings are ISO (`YYYY-MM-DD`) wall-clock dates,
identical to season.json's `sim_through`/game dates. Pure functions only, no
state, no imports from season.py/orchestrator.py (leaf module).
"""
from __future__ import annotations

from datetime import date as _date, timedelta as _timedelta

_AIR_WEEKDAYS = (2, 5)          # Wed, Sat (date.weekday(): Mon=0 .. Sun=6)
_PLAYOFF_WINDOW_DAYS = 70       # ~9-10 week postseason (hockey-grounding §5)


def day_index(start: str, date: str) -> int:
    """Days elapsed since `start` (day 0). Negative if `date` precedes `start`."""
    return (_date.fromisoformat(date) - _date.fromisoformat(start)).days


def is_air_night(date: str) -> bool:
    """True on Wednesday or Saturday — the two nights Center Ice broadcasts."""
    return _date.fromisoformat(date).weekday() in _AIR_WEEKDAYS


def phase(sched: dict, standings: dict, date: str) -> str:
    """`"regular" | "playoffs" | "offseason"` for `date`.

    Regular season ends only once EVERY team has reached 82 GP (standings is
    the full 32-team dict) — the calendar date alone can't know a catch-up
    backlog finished early, so both signals gate the transition. Playoffs then
    run for a fixed ~70-day window from `sched["playoff_start"]` (grounding:
    9-10 weeks); after that, offseason. Missing `playoff_start` (schedule not
    built that far yet) keeps the league "regular" — never invents a phase.
    """
    regular_done = bool(standings) and all(
        team.get("gp", 0) >= 82 for team in standings.values())
    ps = sched.get("playoff_start")
    if not regular_done or not ps or date < ps:
        return "regular"
    playoff_end = (_date.fromisoformat(ps) +
                   _timedelta(days=_PLAYOFF_WINDOW_DAYS)).isoformat()
    if date < playoff_end:
        return "playoffs"
    return "offseason"
