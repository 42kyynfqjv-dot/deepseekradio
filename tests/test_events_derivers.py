"""Fixtures for the five special-events derivers: each reads only published
sidecar shapes, stays strictly read-only (no live-ledger mutation), and is
deterministic.

Run directly (no pytest needed):  python3 tests/test_events_derivers.py
"""
import copy
import sys
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.events import derivers
from src.league import playoffs
from src.statehouse import calendar as scal

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def ctx(**kw):
    return SimpleNamespace(**kw)


def weekday_name(iso):
    return _date.fromisoformat(iso).strftime("%A")


# ── shared bracket fixture (real seed_bracket shape) ─────────────────────────

_TEAMS = [t for conf in playoffs.LEAGUE.values()
          for div in conf.values() for t in div]
_STANDINGS = {t: {"w": 10, "l": 60, "otl": 12, "streak": -1, "gp": 82,
                  "rw": 5, "row": 6} for t in _TEAMS}
# make the two tracked teams clear qualifiers so they land in the bracket
_STANDINGS["mtl"] = {"w": 55, "l": 20, "otl": 7, "streak": 3, "gp": 82,
                     "rw": 30, "row": 35}
_STANDINGS["nyg"] = {"w": 50, "l": 25, "otl": 7, "streak": 2, "gp": 82,
                     "rw": 28, "row": 33}
BRACKET = playoffs.seed_bracket(_STANDINGS)


# ── 1. playoff_nights ────────────────────────────────────────────────────────

# 2026-07-08 is a Wednesday (canon: first Center Ice broadcast). Range covers
# Wed 07-08, Sat 07-11, Wed 07-15 — three air nights.
WED = "2026-07-08"
check(weekday_name(WED) == "Wednesday", "fixture WED really is Wednesday")

c = ctx(today=WED, horizon="2026-07-15", bracket=BRACKET, tracked={"mtl"})
emitted = derivers.playoff_nights(c)
check(len(emitted) >= 1, "playoff_nights emits on tracked air nights")
check(all(d["date"] >= WED and d["date"] <= "2026-07-15" for d in emitted),
      "every playoff date inside [today, horizon]")
check(all("mtl" in (d["meta"]["home"], d["meta"]["away"]) for d in emitted),
      "every emitted row involves the tracked team")
one = emitted[0]
check(one["meta"]["arena"] in ("the Pardon Centre", "Standstill Garden",
                               "home ice"), "arena resolves from ARENAS")
check(one["meta"]["round_name"] == "Round 1"
      and one["meta"]["round"] == 1, "round + round_name in meta")
check(isinstance(one["meta"]["series"], list)
      and len(one["meta"]["series"]) == 2, "series is [h_wins, a_wins]")
check(one["meta"]["weekday"] == weekday_name(one["date"]), "weekday matches date")
check(one["meta"]["game"] == 1, "game 1 for an un-started series")

# every emitted date IS a Wed or Sat (tracked cadence pins air nights)
check(all(_date.fromisoformat(d["date"]).weekday() in (2, 5) for d in emitted),
      "tracked slate only lands on Wed/Sat air nights")

# risk #3 — the REAL bracket ledger is never advanced by look-ahead
check("_last_played" not in BRACKET,
      "look-ahead never wrote _last_played onto the live bracket")
snapshot = copy.deepcopy(BRACKET)
derivers.playoff_nights(c)
check(BRACKET == snapshot, "live bracket byte-identical after a second pass")

# determinism
check(derivers.playoff_nights(c) == emitted, "playoff_nights deterministic")

# dict-carrier ctx works exactly like the attribute carrier (_field contract)
dict_emitted = derivers.playoff_nights(
    {"today": WED, "horizon": "2026-07-15", "bracket": BRACKET,
     "tracked": {"mtl"}})
check(dict_emitted == emitted, "dict-ctx == namespace-ctx (field access)")

# a non-air day with no horizon slack -> tracked series not due -> nothing
SUN = "2026-07-12"
check(weekday_name(SUN) == "Sunday", "fixture SUN really is Sunday")
check(derivers.playoff_nights(
        ctx(today=SUN, horizon=SUN, bracket=BRACKET, tracked={"mtl"})) == [],
      "no air night in window -> no playoff emit")

# missing bracket / empty tracked -> no emit (dark-ship / never invent)
check(derivers.playoff_nights(ctx(today=WED, horizon="2026-07-15",
                                  bracket=None, tracked={"mtl"})) == [],
      "missing bracket -> no emit")
check(derivers.playoff_nights(ctx(today=WED, horizon="2026-07-15",
                                  bracket=BRACKET, tracked=set())) == [],
      "empty tracked -> no emit")

# arena override via ctx.arenas beats the local ARENAS constant
c_over = ctx(today=WED, horizon="2026-07-15", bracket=BRACKET,
             tracked={"mtl"}, arenas={"mtl": "Override Rink"})
ov = [d for d in derivers.playoff_nights(c_over)
      if d["meta"]["home"] == "mtl"]
if ov:
    check(ov[0]["meta"]["arena"] == "Override Rink", "ctx.arenas overrides ARENAS")
else:
    check(True, "ctx.arenas overrides ARENAS (mtl not home this window; skipped)")


# ── 2. election_nights ───────────────────────────────────────────────────────

CAL = scal.build_calendar(1, "2026-01-12")
today_summer = "2026-07-12"
el = derivers.election_nights(ctx(today=today_summer, calendar=CAL))
dates = [d["date"] for d in el]
check("2026-11-03" in dates, "election_nights emits the sidecar's 2026-11-03")
by = {d["date"]: d["meta"] for d in el}
check(by["2026-11-03"]["cycle"] == 2026, "2026 cycle from the sidecar")
check("potholes" in by["2026-11-03"]["races"], "2026 races carried through")
check(any(dd.startswith("2028-11") for dd in dates),
      "election_nights generalizes to 2028 (no registry edit)")
d2028 = [dd for dd in dates if dd.startswith("2028-11")][0]
check(by[d2028]["cycle"] == 2028, "2028 is an even full-race cycle")
check("senate-all" in by[d2028]["races"], "2028 full-chamber races")
# every emitted date is >= today, sorted, and weekday-stamped
check(dates == sorted(dates) and all(dd >= today_summer for dd in dates),
      "election dates sorted, all future")
check(all(d["meta"]["weekday"] == weekday_name(d["date"]) for d in el),
      "election weekday matches date")
# belt-and-suspenders: no statehouse sidecar -> still computes the cycle dates
noscal = derivers.election_nights(ctx(today=today_summer, calendar=None))
check("2026-11-03" in [d["date"] for d in noscal],
      "no sidecar -> deriver still computes 2026-11-03 (generalization)")
check(scal._election_day(2026) == "2026-11-03", "election-day algebra pinned")
# determinism
check(derivers.election_nights(ctx(today=today_summer, calendar=CAL)) == el,
      "election_nights deterministic")


# ── 3./4. draft_day & trade_deadline ─────────────────────────────────────────

SCHED = {"schema": 1, "start": "2026-07-01", "playoff_start": "2027-01-15"}
tctx = ctx(today="2026-08-01", schedule=SCHED, tracked={"mtl", "nyg"})

dd = derivers.trade_deadline(tctx)
exp_deadline = (_date.fromisoformat("2026-07-01")
                + _timedelta(days=derivers._DEADLINE_DAY)).isoformat()
check(len(dd) == 1 and dd[0]["date"] == exp_deadline,
      "trade_deadline = start + DEADLINE_DAY")
check(dd[0]["meta"]["kind"] == "deadline", "deadline meta kind")
check(sorted(dd[0]["meta"]["teams"]) == ["mtl", "nyg"], "deadline names tracked")

dr = derivers.draft_day(tctx)
exp_draft = (_date.fromisoformat("2027-01-15")
             + _timedelta(days=derivers._PLAYOFF_WINDOW_DAYS
                          + derivers._DRAFT_OFFSET_DAYS)).isoformat()
check(len(dr) == 1 and dr[0]["date"] == exp_draft,
      "draft_day = playoff_start + window + offset")
check(dr[0]["meta"]["phase"] == "offseason", "draft meta phase")

# missing schedule sidecar -> no emit (friction #2 dark-ship posture)
check(derivers.trade_deadline(ctx(today="2026-08-01", schedule=None)) == [],
      "no schedule -> no trade_deadline")
check(derivers.draft_day(ctx(today="2026-08-01", schedule=None)) == [],
      "no schedule -> no draft_day")
# a deadline already in the past this season -> not re-emitted
check(derivers.trade_deadline(
        ctx(today="2027-01-01", schedule=SCHED, tracked={"mtl"})) == [],
      "past deadline not re-emitted")
# names map applied when build_ctx injects one
named = derivers.trade_deadline(
    ctx(today="2026-08-01", schedule=SCHED, tracked={"mtl"},
        names={"mtl": "Apologies"}))
check(named[0]["meta"]["teams"] == ["Apologies"], "ctx.names -> display names")
# determinism
check(derivers.draft_day(tctx) == dr and derivers.trade_deadline(tctx) == dd,
      "draft/deadline deterministic")


# ── 5. blizzard_days ─────────────────────────────────────────────────────────

STORM = "2026-01-20"
snow = derivers.blizzard_days(ctx(today=STORM, weather={"snowfall": 2.4}))
check(len(snow) == 1 and snow[0]["date"] == STORM, "blizzard fires same-day on snow")
check(snow[0]["meta"]["weekday"] == weekday_name(STORM), "blizzard weekday meta")
check(derivers.blizzard_days(
        ctx(today=STORM, weather={"condition": "snow"})) == snow,
      "condition:snow also fires (is_snowfall parity)")
check(derivers.blizzard_days(ctx(today=STORM, weather={"snowfall": 0})) == [],
      "no snowfall -> no blizzard")
check(derivers.blizzard_days(ctx(today=STORM, weather=None)) == [],
      "missing weather -> no blizzard (never invents weather)")
# never looks ahead: only today, regardless of any horizon
check(all(d["date"] == STORM for d in snow), "blizzard is strictly same-day")


# ── registry ─────────────────────────────────────────────────────────────────

check(set(derivers.DERIVERS) == {"playoff_nights", "election_nights",
                                 "draft_day", "trade_deadline", "blizzard_days"},
      "DERIVERS names match the registry contract")
check(all(callable(f) for f in derivers.DERIVERS.values()),
      "every DERIVERS value is callable")


print(f"\nevents_derivers {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
