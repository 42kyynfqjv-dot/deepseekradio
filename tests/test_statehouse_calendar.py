"""Statehouse calendar fixtures: session windows, Wed/Sat hockey adjournment,
GA 1's permanently-pending sine die, and the snow-quorum ledger hook.

Run directly (no pytest needed):  python3 tests/test_statehouse_calendar.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.statehouse import calendar as cal

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def weekday_of(d):
    return date.fromisoformat(d).weekday()


# --- delta 5: no schema-example date in this module lands on Wed/Sat --------
for name, d in [("GA1_CONVENED", cal.GA1_CONVENED),
                ("GA1_CROSSOVER", cal.GA1_CROSSOVER),
                ("GA1_SINE_DIE", cal.GA1_SINE_DIE),
                ("GA1_ELECTION", cal.GA1_ELECTION)]:
    check(weekday_of(d) not in (2, 5), f"{name}={d} is not Wed/Sat")

# --- day_index ---------------------------------------------------------------
check(cal.day_index("2026-01-12", "2026-01-12") == 0, "day_index day zero")
check(cal.day_index("2026-01-12", "2026-01-13") == 1, "day_index +1")
check(cal.day_index("2026-01-12", "2026-01-11") == -1, "day_index negative (precedes convened)")
check(cal.day_index("2026-01-12", "2026-02-11") == 30, "day_index a month out")

# --- hockey_adjourned: Wed/Sat only, over a long real range -----------------
check(cal.hockey_adjourned("2026-07-08") is True, "Wed 2026-07-08 adjourned")
check(cal.hockey_adjourned("2026-07-11") is True, "Sat 2026-07-11 adjourned")
check(cal.hockey_adjourned("2026-07-09") is False, "Thu not adjourned")
d0 = date(2026, 1, 1)
bad = [i for i in range(3 * 365)
       if cal.hockey_adjourned((d0 + timedelta(days=i)).isoformat())
       != ((d0 + timedelta(days=i)).weekday() in (2, 5))]
check(bad == [], f"hockey_adjourned matches Wed/Sat over 3 years ({len(bad)} mismatches)")

# --- build_calendar: GA 1 bootstrap exception -------------------------------
c1 = cal.build_calendar(1, cal.GA1_CONVENED)
check(c1["ga"] == 1 and c1["convened"] == "2026-01-12", "GA1 identity fields")
s1 = c1["sessions"][0]
check(s1["kind"] == "regular-extended", "GA1 session kind")
check(s1["sine_die_pending"] is True, "GA1 sine die flagged pending")
check("Merging" in s1["note"], "GA1 note cites the Committee on Merging")
check(s1["start"] < s1["crossover"] < s1["sine_die"], "GA1 start < crossover < sine_die ordering")
check(c1["election"]["date"] == "2026-11-03", "GA1 election date matches canon")
check(c1["election"]["races"] == ["house-all", "senate-all", "potholes"], "GA1 election races")
check(c1["hockey_adjourn"] == ["Wed", "Sat"], "GA1 hockey_adjourn constant")
check(c1["committee_days"] == ["Mon", "Wed", "Fri"], "GA1 committee days")
check(c1["floor_days"] == ["Tue", "Thu", "Sat"], "GA1 floor days")

# --- build_calendar: GA 2, "the proper rhythm" (mirror §5) ------------------
c2 = cal.build_calendar(2, "2027-01-11")
s2 = c2["sessions"][0]
check(s2["kind"] == "regular", "GA2 regular session (odd wall year)")
check(s2.get("sine_die_pending") is False, "GA2 sine die not pending")
check(s2["start"] < s2["crossover"] < s2["sine_die"], "GA2 ordering")
span = (date.fromisoformat(s2["sine_die"]) - date.fromisoformat(s2["start"])).days
check(115 <= span <= 140, f"GA2 regular session ~18 legislative weeks ({span} days)")
check(c2["election"]["races"] == ["potholes"], "GA2 odd wall year: potholes-only race")

# --- build_calendar: an even wall year is a Budget Session ------------------
c3 = cal.build_calendar(3, "2028-02-14")   # 2nd Monday of Feb 2028
check(weekday_of("2028-02-14") == 0, "fixture convened date is itself a Monday")
s3 = c3["sessions"][0]
check(s3["kind"] == "budget", "even wall year -> budget session")
check(s3.get("intro_gate") == "2/3", "budget session flags the 2/3 intro gate")
check(s3["start"] < s3["crossover"] < s3["sine_die"], "budget session ordering")
check(c3["election"]["races"] == ["house-all", "senate-all", "potholes"], "even wall year: full-chamber race")
check(c3["election"]["cycle"] == 2028, "even wall year cycle number set")

# crossover lands at floor-day #13, sine die at floor-day #20 (WY-model, grounding A.1)
d = date.fromisoformat(s3["start"])
floor_days_seen = 0
found_crossover_ok = found_sine_die_ok = False
probe = d
for _ in range(90):
    probe += timedelta(days=1)
    if probe.weekday() in (1, 3, 5):
        floor_days_seen += 1
        if floor_days_seen == 13 and probe.isoformat() == s3["crossover"]:
            found_crossover_ok = True
        if floor_days_seen == 20 and probe.isoformat() == s3["sine_die"]:
            found_sine_die_ok = True
check(found_crossover_ok, "budget crossover is exactly the 13th floor day")
check(found_sine_die_ok, "budget sine die is exactly the 20th floor day")

# --- election day formula reproduces canon ----------------------------------
check(cal.build_calendar(4, "2029-01-08")["election"]["date"].startswith("2026") is False, "sanity: not GA1 leakage")
c2026 = cal.build_calendar(3, "2026-02-09")
check(c2026["election"]["date"] == "2026-11-03", "election-day formula reproduces canon 2026-11-03")

# --- phase(): GA1's sine die is permanently pending -------------------------
check(cal.phase(c1, "2026-01-12") == "session", "GA1 phase session at start")
check(cal.phase(c1, "2026-05-01") == "session", "GA1 phase still session mid-year (extended)")
check(cal.phase(c1, "2026-09-25") == "campaign",
      "GA1's scheduled (moot) sine die already sits inside the campaign window")
check(cal.phase(c1, "2026-09-26") == "campaign", "...same for the day after it")
check(cal.phase(c1, "2027-06-01") == "session", "GA1 phase session a year past scheduled sine die (still pending)")

# --- phase(): campaign window wins even mid-session (GA1's own overlap) ----
check(cal.phase(c1, "2026-09-22") == "campaign", "GA1 campaign window opens 6 weeks before election")
check(cal.phase(c1, "2026-11-02") == "campaign", "GA1 campaign the day before election")
check(cal.phase(c1, "2026-11-03") == "election", "GA1 election day itself")
check(cal.phase(c1, "2026-11-04") == "session",
      "GA1 day after election: campaign/election override lifts, reverts to the "
      "still-pending session (it never had an interim to lapse into)")

# --- phase(): an ordinary (non-pending) session lapses to interim ----------
check(cal.phase(c2, "2027-01-11") == "session", "GA2 session at start")
mid = (date.fromisoformat(s2["start"]) + timedelta(days=30)).isoformat()
check(cal.phase(c2, mid) == "session", "GA2 mid-session")
after = (date.fromisoformat(s2["sine_die"]) + timedelta(days=5)).isoformat()
if cal.phase(c2, after) not in ("campaign", "election"):
    check(cal.phase(c2, after) == "interim", "GA2 lapses to interim after its own sine die")
before_convene = (date.fromisoformat(s2["start"]) - timedelta(days=10)).isoformat()
check(cal.phase(c2, before_convene) == "interim", "GA2 before convening is interim")

# --- is_session_day(): Sunday always False, weekday-in-window True ---------
check(cal.is_session_day(c1, "2026-01-12") is True, "Monday in session -> session day")
sunday_in_session = None
probe = date.fromisoformat(c1["sessions"][0]["start"])
for _ in range(14):
    if probe.weekday() == 6:
        sunday_in_session = probe.isoformat()
        break
    probe += timedelta(days=1)
check(sunday_in_session is not None, "fixture: found a Sunday within GA1 session window")
check(cal.is_session_day(c1, sunday_in_session) is False, "Sunday is never a session business day")
check(cal.phase(c1, sunday_in_session) == "session", "...but the phase is still 'session' on that Sunday")
check(cal.is_session_day(c1, "2025-01-01") is False, "date before convening is not a session day")

# --- day_kind(): floor/committee/quiet/election/canvass --------------------
check(cal.day_kind(c1, "2026-01-12") == "committee", "Monday is a committee day")
check(cal.day_kind(c1, "2026-01-13") == "floor", "Tuesday is a floor day")
check(cal.day_kind(c1, sunday_in_session) == "quiet", "Sunday is quiet")
check(cal.day_kind(c1, "2026-11-03") == "election", "election day")
check(cal.day_kind(c1, "2026-11-04") == "canvass", "day after election is canvass")
check(cal.day_kind(c1, "2025-01-01") == "quiet", "outside any session window is quiet")

# --- snow-quorum hook --------------------------------------------------------
check(cal.is_snowfall(None) is False, "missing weather feed => no snow (quorum holds)")
check(cal.is_snowfall({}) is False, "empty weather dict => no snow")
check(cal.is_snowfall({"snowfall": 0}) is False, "zero snowfall => no snow")
check(cal.is_snowfall({"snowfall": 2.5}) is True, "positive snowfall => snow")
check(cal.is_snowfall({"condition": "snow"}) is True, "condition=snow => snow")
check(cal.is_snowfall({"condition": "clear"}) is False, "condition=clear => no snow")

ledger = []
ledger2 = cal.record_snow_day(ledger, "2026-02-11", {"snowfall": 4})
check(ledger2 == ["2026-02-11"], "snow day appended")
check(ledger == [], "record_snow_day does not mutate the input ledger")
ledger3 = cal.record_snow_day(ledger2, "2026-02-11", {"snowfall": 4})
check(ledger3 == ["2026-02-11"], "re-recording the same snow day is idempotent")
ledger4 = cal.record_snow_day(ledger3, "2026-02-12", None)
check(ledger4 == ["2026-02-11"], "missing feed appends nothing")
ledger5 = cal.record_snow_day(ledger4, "2026-02-15", {"condition": "snow"})
check(ledger5 == ["2026-02-11", "2026-02-15"], "second distinct snow day appended in order")

print(f"\nstatehouse calendar {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
