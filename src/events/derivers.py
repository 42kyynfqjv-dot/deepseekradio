"""Special-events engine — the five auto-derivers (design "Auto-derivation
contracts").

Each deriver is a PURE stdlib function ``(ctx) -> list[DerivedDate]`` where
``DerivedDate = {"date": "YYYY-MM-DD", "window"?: [...], "meta": {...}}``.
Derivers import NOTHING from the orchestrator; they read the sidecars the sims
already publish (carried on ``ctx``) and the sibling leaf modules
(``league.playoffs``/``league.calendar``/``statehouse.calendar``) that own the
same facts. They are strictly READ-ONLY: risk #3 — a look-ahead must never
advance a live ledger — so ``playoff_nights`` calls ``schedule_series`` against
a ``copy.deepcopy`` of the bracket, never the real ``_last_played`` cadence
ledger.

``ctx`` — the read-only per-pass snapshot the engine's ``build_ctx`` assembles
(that wiring is the orchestrator glue row). This module reads these fields via
``_field`` (attribute OR dict access, so a ``SimpleNamespace``, a dataclass, or
a plain dict all work — the frozen contract is the field NAMES, not the carrier
type):

    today     str  ISO "YYYY-MM-DD"        — the air date this pass resolves for
    horizon   str  ISO                     — today + max(lead_days); playoff
                                             look-ahead is bounded to [today,
                                             horizon] (the only deriver that is
                                             — the rest emit specific future
                                             dates and let active_events gate
                                             them to today)
    bracket   dict|None  playoffs-s{n}.json body (the frozen playoffs.py shape)
    calendar  dict|None  calendar-ga{n}.json body (statehouse calendar.build_calendar)
    weather   dict|None  the cached Open-Meteo feed is_snowfall() reads
    tracked   iterable   team codes whose every playoff game airs live
    schedule  dict|None  schedule-s{n}.json body (SCHEMA FRICTION #2 below)
    arenas    dict|None  optional {team_code: arena} override (see ARENAS below)

SCHEMA FRICTION (reported, per the discipline — not improvised around):

  1. The bracket carries no arena, and this leaf may not import the heavy
     season.py to fetch season.TRACKED (the arena source). Mirroring
     playoffs.py's own duplicated-``LEAGUE`` friction note, arenas are a small
     local constant ``ARENAS`` here, kept in sync with season.TRACKED by hand.
     ``ctx.arenas`` (if build_ctx chooses to inject season.TRACKED) wins over
     the local copy; absent both, a tracked home with no arena falls back to a
     generic "home ice" — never invents a venue.

  2. The design's frozen ``ctx`` field list names "season.json/bracket/
     calendar/weather"; it does NOT name the schedule-s{n}.json sidecar. But
     ``draft_day``/``trade_deadline`` are "fixed offsets into the league
     calendar" and the ONLY calendar->date anchor the league publishes is
     ``schedule["start"]`` / ``schedule["playoff_start"]``. So these two
     derivers additionally read ``ctx.schedule``; build_ctx must load it for
     them to emit. Absent it they emit NOTHING (never invent a date) — which is
     the correct dark-ship posture anyway, since both are gated behind
     ECON-ENABLED until Gate 2.

  3. ``economy.DEADLINE_DAY`` (142) and the ~70-day playoff window are private
     constants of sibling leaves this module may not import for a live value;
     they are duplicated below with the same must-stay-in-sync caveat.
"""
from __future__ import annotations

import copy
from datetime import date as _date, timedelta as _timedelta

from ..league import playoffs as _playoffs
from ..statehouse import calendar as _scal

# ── duplicated canon (friction #1/#3 — keep in sync with the cited source) ───

# season.TRACKED arenas (the only teams whose playoff games air, so the only
# homes that ever need a named venue). Duplicated per friction #1.
ARENAS = {
    "mtl": "the Pardon Centre",
    "nyg": "Standstill Garden",
}

# economy.DEADLINE_DAY (~78% through the 182-day season) and the league
# calendar's ~70-day playoff window. Duplicated per friction #3.
_DEADLINE_DAY = 142
_PLAYOFF_WINDOW_DAYS = 70
_DRAFT_OFFSET_DAYS = 7        # draft opens ~a week into the offseason

# election_nights emits future cycles this many years past `today`'s year so
# 2028/2030 promote without a registry edit (design test: "2026-11-03 & 2028").
_ELECTION_HORIZON_YEARS = 4

_ROUND_NAMES = {1: "Round 1", 2: "Round 2",
                3: "Conference Final", 4: "Cup Final"}


# ── ctx / date helpers ───────────────────────────────────────────────────────

def _field(ctx, name, default=None):
    """Read `name` off ctx whether ctx is an object (attribute) or a dict."""
    if isinstance(ctx, dict):
        return ctx.get(name, default)
    return getattr(ctx, name, default)


def _daterange(start_iso: str, end_iso: str):
    """Inclusive [start, end] ISO date walk; empty if end < start."""
    try:
        d = _date.fromisoformat(start_iso)
        end = _date.fromisoformat(end_iso)
    except (TypeError, ValueError):
        return
    while d <= end:
        yield d.isoformat()
        d += _timedelta(days=1)


def _weekday(iso: str) -> str:
    return _date.fromisoformat(iso).strftime("%A")


def _arena(home: str, ctx) -> str:
    override = _field(ctx, "arenas") or {}
    return override.get(home) or ARENAS.get(home) or "home ice"


# ── 1. playoff series nights ─────────────────────────────────────────────────

def playoff_nights(ctx) -> list:
    """Every night in [today, horizon] on which a TRACKED team plays a playoff
    game, one DerivedDate per tracked slate row.

    Reads ``ctx.bracket`` (the frozen playoffs-s{n}.json shape) and calls the
    pure ``playoffs.schedule_series`` — but on a ``copy.deepcopy`` of the
    bracket, walked forward day-by-day so the cadence ledger (``_last_played``)
    advances realistically ACROSS the horizon while the real ledger is never
    touched (risk #3). Meta names {round, round_name, game, home, away, arena,
    series:[h_wins,a_wins], weekday, date} for the {..} templates; look-ahead
    can't know future results, so `game`/`series` reflect the series' state as
    of `today`, correct for tonight and a best-effort label for later nights.
    """
    bracket = _field(ctx, "bracket")
    if not bracket:
        return []
    tracked = set(_field(ctx, "tracked") or ())
    if not tracked:
        return []
    today = _field(ctx, "today")
    horizon = _field(ctx, "horizon") or today

    work = copy.deepcopy(bracket)     # NEVER the live ledger (risk #3)
    out = []
    for iso in _daterange(today, horizon):
        try:
            slate = _playoffs.schedule_series(work, iso, tracked)
        except Exception:
            continue
        for g in slate:
            if not ({g["home"], g["away"]} & tracked):
                continue
            po = g.get("playoff", {})
            rnd = po.get("round")
            out.append({
                "date": iso,
                "meta": {
                    "round": rnd,
                    "round_name": _ROUND_NAMES.get(rnd, "Playoffs"),
                    "game": po.get("game"),
                    "home": g["home"],
                    "away": g["away"],
                    "arena": _arena(g["home"], ctx),
                    "series": list(po.get("series", [])),
                    "weekday": _weekday(iso),
                    "date": iso,
                },
            })
    return out


# ── 2. Election Night ────────────────────────────────────────────────────────

def _election_meta(year: int) -> dict:
    even = (year % 2 == 0)
    return {
        "cycle": year if even else None,
        "races": (["house-all", "senate-all", "potholes"] if even
                  else ["potholes"]),
    }


def election_nights(ctx) -> list:
    """Every upcoming small-state November election day from `today` forward.

    Reads ``ctx.calendar`` (calendar-ga{n}.json) for THIS cycle's authoritative
    date/cycle/races, then generalizes to future cycles via the same
    ``statehouse.calendar._election_day(year)`` the sidecar itself uses — so
    2028/2030 promote with no registry edit. The registry's literal
    ``dates: ["2026-11-03"]`` is the belt-and-suspenders that fires even with
    NO statehouse sidecar; this deriver is the forward generalization. Dates
    strictly >= today; deduped by date so the sidecar's own election and its
    computed twin never double-emit.
    """
    today = _field(ctx, "today")
    if not today:
        return []
    try:
        base_year = _date.fromisoformat(today).year
    except ValueError:
        return []

    by_date = {}

    cal = _field(ctx, "calendar")
    if cal:
        el = cal.get("election") or {}
        d = el.get("date")
        if d and d >= today:
            by_date[d] = {
                "cycle": el.get("cycle"),
                "races": list(el.get("races", [])),
                "weekday": _weekday(d),
                "date": d,
            }

    for year in range(base_year, base_year + _ELECTION_HORIZON_YEARS + 1):
        d = _scal._election_day(year)
        if d < today or d in by_date:
            continue
        m = _election_meta(year)
        m["weekday"] = _weekday(d)
        m["date"] = d
        by_date[d] = m

    return [{"date": d, "meta": by_date[d]} for d in sorted(by_date)]


# ── 3./4. draft day & trade deadline ─────────────────────────────────────────

def _season_start(ctx) -> str | None:
    sched = _field(ctx, "schedule")
    if sched:
        return sched.get("start")
    return None


def _team_names(ctx):
    """Display names if build_ctx injected them; else the codes themselves."""
    names = _field(ctx, "names") or {}
    return [names.get(t, t) for t in sorted(set(_field(ctx, "tracked") or ()))]


def draft_day(ctx) -> list:
    """The offseason draft — a single fixed offset past the playoff window.

    Anchored on ``ctx.schedule["playoff_start"]`` (friction #2): draft opens
    ``_DRAFT_OFFSET_DAYS`` after the ~70-day playoff window closes, i.e. in the
    ``league.calendar.phase == "offseason"`` region. Emits nothing if the
    schedule sidecar / playoff_start is absent (never invents a date). Gated
    dark behind ECON-ENABLED by the registry until Gate 2.
    """
    sched = _field(ctx, "schedule")
    today = _field(ctx, "today")
    if not sched or not today:
        return []
    ps = sched.get("playoff_start")
    if not ps:
        return []
    try:
        draft = (_date.fromisoformat(ps)
                 + _timedelta(days=_PLAYOFF_WINDOW_DAYS + _DRAFT_OFFSET_DAYS))
    except ValueError:
        return []
    d = draft.isoformat()
    if d < today:
        return []
    return [{
        "date": d,
        "meta": {
            "phase": "offseason",
            "teams": _team_names(ctx),
            "weekday": _weekday(d),
            "date": d,
        },
    }]


def trade_deadline(ctx) -> list:
    """The trade deadline — the economy's DEADLINE_DAY offset off the season
    start.

    Anchored on ``ctx.schedule["start"]`` (friction #2) + ``_DEADLINE_DAY``
    (economy's ~78%-through-season constant, friction #3). Emits nothing absent
    the schedule sidecar (never invents a date). Gated dark behind ECON-ENABLED
    until Gate 2.
    """
    start = _season_start(ctx)
    today = _field(ctx, "today")
    if not start or not today:
        return []
    try:
        deadline = (_date.fromisoformat(start)
                    + _timedelta(days=_DEADLINE_DAY))
    except ValueError:
        return []
    d = deadline.isoformat()
    if d < today:
        return []
    return [{
        "date": d,
        "meta": {
            "kind": "deadline",
            "teams": _team_names(ctx),
            "weekday": _weekday(d),
            "date": d,
        },
    }]


# ── 5. blizzard mode ─────────────────────────────────────────────────────────

def blizzard_days(ctx) -> list:
    """Same-day storm coverage: a single DerivedDate for `today` iff the cached
    Open-Meteo feed reports snowfall today.

    Uniquely reactive (design lead_days: 0) — weather isn't known 4 days out —
    so it never looks ahead and never promos. Reads the EXACT
    ``statehouse.calendar.is_snowfall`` predicate the snow-quorum uses; a
    missing feed => no blizzard (never invents weather).
    """
    today = _field(ctx, "today")
    if not today:
        return []
    weather = _field(ctx, "weather")
    if not _scal.is_snowfall(weather):
        return []
    return [{
        "date": today,
        "meta": {"weekday": _weekday(today), "date": today},
    }]


# ── registry ─────────────────────────────────────────────────────────────────

DERIVERS = {
    "playoff_nights": playoff_nights,
    "election_nights": election_nights,
    "draft_day": draft_day,
    "trade_deadline": trade_deadline,
    "blizzard_days": blizzard_days,
}
