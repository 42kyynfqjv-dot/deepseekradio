"""Statehouse session calendar — 1 wall day = 1 legislative day, identity
mapping (mirror §5, this doc's Component A). Pure functions only, no state,
no imports from civics.py/orchestrator.py/league modules (leaf module).

Session windows are grounded in the small-state calendar
(`docs/sim-grounding/civics-grounding.md` A.1): odd wall years run a VT-model
**Regular Session** (~18 legislative weeks, convenes 2nd Monday of January);
even wall years run a WY-model **Budget Session** (20 floor days, convenes
2nd Monday of February, non-budget bills gated behind a 2/3 introduction
vote). Wednesday and Saturday the Half-Dome empties by 18:00 for Center Ice
(canon, `station/wending-bible.md`) — `hockey_adjourned()` reads the exact
Wed/Sat constant the hockey engine's `league.calendar.is_air_night()` uses,
one clock for two institutions.

GA 1 is the bootstrap exception (mirror §5/§9): convened retroactively
2026-01-12, running in **"regular-extended"** session because the sine die
resolution is itself referred to the Committee on Merging — which never
advances and never dies. That makes GA 1's sine die *permanently pending*:
`phase()` never lets a pending-sine-die session lapse into "interim" on its
own scheduled date, canon's closed loop rendered as a calendar rule.

Friction note (delta 5 compliance): the mirror's own worked example pinned
GA 1's sine die at 2026-09-26, a Saturday — exactly the hockey-night mistake
final.md's delta 5 calls out. This module moves the placeholder one day
earlier, to 2026-09-25 (Friday), to keep every schema-example date in this
file off Wednesday/Saturday. The date is moot regardless (see above), so the
shift changes no downstream behavior.
"""
from __future__ import annotations

from datetime import date as _date, timedelta as _timedelta

# --------------------------------------------------------------- constants

_WEEKDAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_COMMITTEE_DAYS = ["Mon", "Wed", "Fri"]
_FLOOR_DAYS = ["Tue", "Thu", "Sat"]
_HOCKEY_ADJOURN = ["Wed", "Sat"]           # canon: Center Ice nights
_HOCKEY_WEEKDAYS = (2, 5)                  # date.weekday(): Wed=2, Sat=5

_REGULAR_SESSION_WEEKS = 18                # VT-model (grounding A.1)
_REGULAR_CROSSOVER_WEEKS = 9               # ~mid-session, VT crossover ~day 65-70
_BUDGET_SESSION_FLOOR_DAYS = 20            # WY-model (grounding A.1)
_BUDGET_CROSSOVER_FLOOR_DAY = 13           # ~day 13/20 (grounding A.1)

_CAMPAIGN_LEAD_DAYS = 42                   # 6 weeks before any November election

# GA 1 bootstrap pins (mirror §5, §9) — see module docstring for the
# one-day sine-die shift off Saturday.
GA1_CONVENED = "2026-01-12"
GA1_CROSSOVER = "2026-03-20"
GA1_SINE_DIE = "2026-09-25"
GA1_ELECTION = "2026-11-03"


# ----------------------------------------------------------- date helpers

def _election_day(year: int) -> str:
    """First Tuesday after the first Monday of November (real small-state
    practice; reproduces canon's 2026-11-03 for `year=2026`)."""
    nov1 = _date(year, 11, 1)
    first_monday = nov1 + _timedelta(days=(0 - nov1.weekday()) % 7)
    return (first_monday + _timedelta(days=1)).isoformat()


def _add_floor_days(start: str, n: int) -> str:
    """Walk forward from `start` counting only floor-day weekdays (Tue/Thu/
    Sat) until `n` have elapsed; returns that date. Used for Budget Session
    windows, which are specified in floor days, not wall days."""
    d = _date.fromisoformat(start)
    floor_weekdays = {1, 3, 5}          # Tue, Thu, Sat
    count = 0
    while count < n:
        d += _timedelta(days=1)
        if d.weekday() in floor_weekdays:
            count += 1
    return d.isoformat()


# --------------------------------------------------------------- calendar

def build_calendar(ga: int, convened: str) -> dict:
    """Build the `calendar-ga{n}.json` sidecar body (mirror §2 schema).

    GA 1 is special-cased per the bootstrap exception: regular-extended
    session, sine die permanently pending in Merging. Every other GA derives
    its session window from `convened`'s year parity: odd wall years get a
    Regular Session (VT-model, ~18 legislative weeks); even wall years get a
    Budget Session (WY-model, 20 floor days, 2/3 introduction gate flagged).
    Election info attaches the nearest small-state election day for
    `convened`'s year — full-chamber races on even years, Pothole
    Commissioner every year (canon: perennially up for reelection).
    """
    d = _date.fromisoformat(convened)
    if ga == 1 and convened == GA1_CONVENED:
        session = {
            "kind": "regular-extended",
            "start": GA1_CONVENED,
            "crossover": GA1_CROSSOVER,
            "sine_die": GA1_SINE_DIE,
            "sine_die_pending": True,
            "note": "sine die resolution pending in the Committee on Merging",
        }
        election = {"date": GA1_ELECTION, "cycle": 2026,
                    "races": ["house-all", "senate-all", "potholes"]}
    else:
        year = d.year
        if year % 2 == 1:
            crossover = (d + _timedelta(weeks=_REGULAR_CROSSOVER_WEEKS)).isoformat()
            sine_die = (d + _timedelta(weeks=_REGULAR_SESSION_WEEKS)).isoformat()
            session = {"kind": "regular", "start": convened,
                       "crossover": crossover, "sine_die": sine_die,
                       "sine_die_pending": False, "note": None}
        else:
            crossover = _add_floor_days(convened, _BUDGET_CROSSOVER_FLOOR_DAY)
            sine_die = _add_floor_days(convened, _BUDGET_SESSION_FLOOR_DAYS)
            session = {"kind": "budget", "start": convened,
                       "crossover": crossover, "sine_die": sine_die,
                       "sine_die_pending": False, "intro_gate": "2/3",
                       "note": None}
        races = (["house-all", "senate-all", "potholes"] if year % 2 == 0
                  else ["potholes"])
        election = {"date": _election_day(year), "cycle": year if year % 2 == 0
                    else None, "races": races}

    return {
        "schema": 1, "ga": ga, "convened": convened,
        "sessions": [session],
        "committee_days": list(_COMMITTEE_DAYS),
        "floor_days": list(_FLOOR_DAYS),
        "hockey_adjourn": list(_HOCKEY_ADJOURN),
        "election": election,
    }


def day_index(convened: str, date: str) -> int:
    """Days elapsed since `convened` (day 0). Negative if `date` precedes
    convening — mirrors `league.calendar.day_index`."""
    return (_date.fromisoformat(date) - _date.fromisoformat(convened)).days


def hockey_adjourned(date: str) -> bool:
    """True on Wednesday or Saturday — the Half-Dome empties by 18:00 for
    Center Ice (canon). Reads the same Wed/Sat constant as
    `league.calendar.is_air_night()`: one clock, two institutions."""
    return _date.fromisoformat(date).weekday() in _HOCKEY_WEEKDAYS


def _in_session_window(cal: dict, date: str) -> bool:
    """True when `date` falls within a built session's date range, weekday
    ignored (the underlying "is the legislature convened" fact — Sundays are
    still mid-session, just quiet). A session whose sine die is
    `sine_die_pending` never closes by date alone (GA 1's permanently-pending
    Merging referral) — every day from `start` onward counts."""
    for session in cal.get("sessions", []):
        if date < session["start"]:
            continue
        if session.get("sine_die_pending"):
            return True
        if date <= session["sine_die"]:
            return True
    return False


def is_session_day(cal: dict, date: str) -> bool:
    """True when `date` is an active legislative *business* day: Sunday is
    always quiet regardless of session window; any other weekday counts if
    `date` falls within a built session's window (see `_in_session_window`)."""
    if _date.fromisoformat(date).weekday() == 6:        # Sunday: quiet, always
        return False
    return _in_session_window(cal, date)


def day_kind(cal: dict, date: str) -> str:
    """`"floor" | "committee" | "quiet" | "election" | "canvass"` for `date`
    (mirror §3 signature). Election day itself, and the single day after it
    (canvass), take priority over the weekly committee/floor texture."""
    election_date = cal["election"]["date"]
    if date == election_date:
        return "election"
    canvass_date = (_date.fromisoformat(election_date) +
                    _timedelta(days=1)).isoformat()
    if date == canvass_date:
        return "canvass"
    if not is_session_day(cal, date):
        return "quiet"
    weekday_abbr = _WEEKDAY_ABBR[_date.fromisoformat(date).weekday()]
    if weekday_abbr in cal["floor_days"]:
        return "floor"
    if weekday_abbr in cal["committee_days"]:
        return "committee"
    return "quiet"


def phase(cal: dict, date: str) -> str:
    """`"session" | "interim" | "campaign" | "election"` for `date` (mirror
    §3 signature). Election day wins outright; the 6-week campaign window
    ahead of it wins next (§5: "campaign phase opens 6 weeks before any
    November election," even while the legislature is still nominally in
    session — GA 1's regular-extended session overlaps its own campaign
    window, which is the joke); otherwise session-in-window, else interim."""
    election_date = cal["election"]["date"]
    if date == election_date:
        return "election"
    campaign_start = (_date.fromisoformat(election_date) -
                       _timedelta(days=_CAMPAIGN_LEAD_DAYS)).isoformat()
    if campaign_start <= date < election_date:
        return "campaign"
    if _in_session_window(cal, date):
        return "session"
    return "interim"


# ------------------------------------------------------------ snow-quorum

def is_snowfall(weather: dict | None) -> bool:
    """True when the cached Halfway (Open-Meteo) feed reports snowfall for
    the day. Missing feed => False — quorum defaults to *holds* on missing
    feed (mirror §4.2/risk #4), never invents weather."""
    if not weather:
        return False
    if weather.get("snowfall", 0) and weather["snowfall"] > 0:
        return True
    return weather.get("condition") == "snow"


def record_snow_day(quorum_fails: list, date: str, weather: dict | None) -> list:
    """Pure, non-mutating append into the `quorum_fails` ledger shape
    (civics.json §2 — the real-weather truth ledger snow-quorum reads back
    on catch-up). Idempotent: re-appending an already-recorded date is a
    no-op, so replaying the same weather during catch-up never duplicates
    ledger entries."""
    if is_snowfall(weather) and date not in quorum_fails:
        return [*quorum_fails, date]
    return list(quorum_fails)
