"""Statehouse docket fixtures: bill lifecycle golden values + property/
calibration tests against civics-grounding.md and the final.md deltas.

Run directly (no pytest needed):  python3 tests/test_statehouse_docket.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.statehouse import docket

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


# --------------------------------------------------------------- fixtures

REGULAR_CAL = {
    "sessions": [{"kind": "regular", "start": "2026-01-12",
                  "crossover": "2026-03-20", "sine_die": "2026-09-25",
                  "sine_die_pending": False}],
    "committee_days": ["Mon", "Wed", "Fri"], "floor_days": ["Tue", "Thu", "Sat"],
}
EMPTY_MEMBERS = {"members": {}}


def _add_floor_days(start, n):
    d = date.fromisoformat(start)
    floor_wd = {1, 3, 5}     # Tue, Thu, Sat
    count = 0
    while count < n:
        d += timedelta(days=1)
        if d.weekday() in floor_wd:
            count += 1
    return d.isoformat()


def _budget_cal(start="2026-02-09"):
    return {
        "sessions": [{"kind": "budget", "start": start,
                      "crossover": _add_floor_days(start, 13),
                      "sine_die": _add_floor_days(start, 20),
                      "sine_die_pending": False}],
        "committee_days": ["Mon", "Wed", "Fri"], "floor_days": ["Tue", "Thu", "Sat"],
    }


def run_session(ga, cal, members=EMPTY_MEMBERS, days=140):
    """Drive a full session end-to-end: introduce -> committee -> floor,
    one simulated day at a time, exactly once per date (matching the
    facade's own single-pass-per-day contract — these functions are not
    specified safe to re-invoke for a date already processed)."""
    dk = docket.empty_docket(ga)
    d = date.fromisoformat(cal["sessions"][0]["start"])
    for _ in range(days):
        ds = d.isoformat()
        docket.introduce_day(dk, members, cal, ga, ds)
        docket.committee_day(dk, members, cal, ga, ds)
        floor_open = d.weekday() in (1, 3, 5)   # Tue/Thu/Sat
        docket.floor_and_beyond_day(dk, members, ga, ds, floor_open=floor_open)
        d += timedelta(days=1)
    return dk


# ===================================================== stage-enum plumbing

check(docket.is_terminal("MERGED"), "MERGED is terminal")
check(not docket.is_dead("MERGED"), "MERGED is NOT dead (terminal-but-not-dead)")
check(docket.is_enacted("SIGNED") and docket.is_enacted("OVERRIDDEN")
      and docket.is_enacted("LAW_NO_SIG"), "enacted stages recognized")
check(docket.is_dead("DIED_IN_COMMITTEE") and docket.is_dead("CROSSOVER_BARRED")
      and docket.is_dead("FAILED_FLOOR") and docket.is_dead("POCKET")
      and docket.is_dead("VETOED"), "dead stages recognized")
check(not docket.is_terminal("IN_COMMITTEE") and not docket.is_terminal("CALENDARED"),
      "mid-pipeline stages are non-terminal")
for s in docket.STAGE_ORDER:
    check(not docket.is_terminal(s), f"{s} non-terminal")
check(docket.ALL_STAGES == frozenset(docket.STAGE_ORDER) | docket.TERMINAL_STAGES,
      "ALL_STAGES is the union")

verbs = docket.stage_verbs("MERGED")
check(verbs and verbs[0] == "referred to the Committee on Merging",
      "stage_verbs(MERGED) leads with the canonical civicguard phrase")
check(docket.stage_verbs("DIED_IN_COMMITTEE")[0] == "died in committee",
      "stage_verbs(DIED_IN_COMMITTEE) matches civicguard.STAGE_WORDS")
check(docket.stage_verbs("nonsense-stage") == [], "unknown stage -> no verbs, no crash")

# --------------------------------------------------- golden: bill_title

import random as _random
t1 = docket.bill_title(_random.Random("title:1:HB-1"), "roads")
check(t1 == "An Act Relating to the Numbering of Potholes Prior to Repair",
      f"golden bill_title (roads, seed title:1:HB-1) got {t1!r}")
t2 = docket.bill_title(_random.Random("title:1:HB-1"), "judiciary")
check(t2 == "An Act Relating to the Admissibility of Laminated Documents",
      f"golden bill_title (judiciary, same seed) got {t2!r}")
t3 = docket.bill_title(_random.Random("anything"), "unknown-committee-xyz")
check(t3 in docket.COMMITTEES.get("local") or t3 in
      ["An Act Relating to Window 4's Posted Hours",
       "An Act Concerning Fixture 12's Maintenance Ticket"],
      "unknown committee falls back to the 'local' bank, never crashes")

# ------------------------------------------------- golden: introduce_day

dk_g = docket.empty_docket(1)
new_g = docket.introduce_day(dk_g, EMPTY_MEMBERS, REGULAR_CAL, 1, "2026-01-12")
check(len(new_g) == 10, f"golden introduce_day count on 2026-01-12: got {len(new_g)}")
check(dk_g["next_no"] == {"H": 11, "S": 1}, f"golden next_no: got {dk_g['next_no']}")
first = new_g[0]
check(first["sponsor"] == "H-08" and first["committee"] == "natural"
      and first["title"] == "An Act Relating to the Pharmacy Lot Drainage Easement",
      "golden first minted bill's sponsor/committee/title")
check(first["stage"] == "IN_COMMITTEE", "new bill starts IN_COMMITTEE")
check(first["history"] == [["2026-01-12", "INTRODUCED"]],
      "new bill's history is exactly one INTRODUCED entry (no phantom REFERRED)")
for b in new_g:
    check(0.0 <= b["marquee"] <= 1.0, "marquee in [0,1]")
    check(0.0 <= b["axis"] <= 1.0, "axis in [0,1]")
    check(b["class"] == "ordinary", "new bills default to ordinary class")
    check(isinstance(b["tags"], list), "tags is always a list")
    check(b["committee"] != "merging", "no bill is ever INTRODUCED straight into Merging")

check(docket.introduce_day(docket.empty_docket(1), EMPTY_MEMBERS, REGULAR_CAL,
                           1, "2026-01-18") == [],
      "Sunday is always quiet, regardless of session window")
check(docket.introduce_day(docket.empty_docket(1), EMPTY_MEMBERS,
                           {"sessions": []}, 1, "2026-01-12") == [],
      "no active session -> no introductions, no crash")

# determinism: same inputs, independently-run, byte-identical output
dk_a = docket.empty_docket(1)
dk_b = docket.empty_docket(1)
na = docket.introduce_day(dk_a, EMPTY_MEMBERS, REGULAR_CAL, 1, "2026-01-14")
nb = docket.introduce_day(dk_b, EMPTY_MEMBERS, REGULAR_CAL, 1, "2026-01-14")
check(na == nb, "introduce_day is fully deterministic given identical inputs")

# ------------------------------------------------------- sponsor cap

dk_cap = docket.empty_docket(1)
d = date.fromisoformat("2026-01-12")
for _ in range(30):
    docket.introduce_day(dk_cap, EMPTY_MEMBERS, REGULAR_CAL, 1, d.isoformat())
    d += timedelta(days=1)
sponsor_counts = {}
for b in dk_cap["bills"].values():
    sponsor_counts[b["sponsor"]] = sponsor_counts.get(b["sponsor"], 0) + 1
over_cap = [m for m, n in sponsor_counts.items() if n > docket._SPONSOR_CAP]
check(not over_cap or len(dk_cap["bills"]) > 60 * docket._SPONSOR_CAP,
      f"sponsor cap ({docket._SPONSOR_CAP}) respected while pool has headroom: "
      f"over-cap sponsors {over_cap}")

# ===================================================== committee mechanics

# --- crossover-bar sweep -----------------------------------------------
# Most bills resolve (report/die/merge) well before crossover — search for
# a bill id whose specific per-bill seed happens to never trigger a
# resolution draw before the deadline, so the sweep itself is exercised.
crossover = REGULAR_CAL["sessions"][0]["crossover"]
swept, swept_on, bid_x = False, None, None
for i in range(300):
    bid = f"XB-{i}"
    dk_try = docket.empty_docket(1)
    dk_try["bills"][bid] = {
        "title": "t", "sponsor": "H-01", "cosponsors": [], "committee": "roads",
        "stage": "IN_COMMITTEE", "intro": "2026-01-12", "marquee": 0.5,
        "history": [["2026-01-12", "INTRODUCED"]], "deficiency": None,
        "axis": 0.5, "tags": [], "class": "ordinary",
    }
    d = date.fromisoformat("2026-01-14")
    for _ in range(120):
        ds = d.isoformat()
        docket.committee_day(dk_try, EMPTY_MEMBERS, REGULAR_CAL, 1, ds)
        stage = dk_try["bills"][bid]["stage"]
        if stage == "CROSSOVER_BARRED":
            swept, swept_on, bid_x, dk_x = True, ds, bid, dk_try
            break
        if stage != "IN_COMMITTEE":
            break            # resolved some other way — try the next seed
        d += timedelta(days=1)
    if swept:
        break
check(swept, "a perpetually-unresolved bill is swept to CROSSOVER_BARRED by crossover "
             "(found within 300 candidate seeds)")
if swept:
    check(swept_on >= crossover, "the sweep never fires before the crossover date itself")
    check(dk_x["bills"][bid_x]["history"][-1] == [swept_on, "CROSSOVER_BARRED"],
          "CROSSOVER_BARRED is logged in history at the moment it resolves")

    # once terminal, further committee days never touch it again (MERGED-
    # style permanence applies to every terminal stage, not just MERGED)
    before = list(dk_x["bills"][bid_x]["history"])
    for i in range(20):
        ds = (date.fromisoformat(swept_on) + timedelta(days=1 + i)).isoformat()
        docket.committee_day(dk_x, EMPTY_MEMBERS, REGULAR_CAL, 1, ds)
    check(dk_x["bills"][bid_x]["history"] == before,
          "a terminal (CROSSOVER_BARRED) bill never advances again")

# --- MERGED terminal-but-not-dead permanence ----------------------------
dk_m = docket.empty_docket(1)
dk_m["bills"]["HB-50"] = {
    "title": "t", "sponsor": "H-01", "cosponsors": [], "committee": "merging",
    "stage": "MERGED", "intro": "2026-01-12", "marquee": 0.3,
    "history": [["2026-01-12", "INTRODUCED"], ["2026-01-14", "REFERRED", "merging"]],
    "deficiency": None, "axis": 0.5, "tags": [], "class": "ordinary",
}
snapshot = list(dk_m["bills"]["HB-50"]["history"])
d = date.fromisoformat("2026-01-15")
for _ in range(60):
    ds = d.isoformat()
    docket.committee_day(dk_m, EMPTY_MEMBERS, REGULAR_CAL, 1, ds)
    docket.floor_and_beyond_day(dk_m, EMPTY_MEMBERS, 1, ds, floor_open=True)
    d += timedelta(days=1)
check(dk_m["bills"]["HB-50"]["stage"] == "MERGED",
      "MERGED never advances across 60 days of committee+floor sweeps")
check(dk_m["bills"]["HB-50"]["history"] == snapshot,
      "MERGED bill's history never grows once referred (never dies, never moves)")

# --- pick_tracked --------------------------------------------------------
dk_t = docket.empty_docket(1)
dk_t["bills"] = {
    "HB-1": {"intro": "2026-01-12", "marquee": 0.4, "stage": "IN_COMMITTEE"},
    "HB-2": {"intro": "2026-01-12", "marquee": 0.9, "stage": "IN_COMMITTEE"},
    "HB-3": {"intro": "2026-02-01", "marquee": 0.99, "stage": "IN_COMMITTEE"},
}
check(docket.pick_tracked(dk_t, 1, "2026-01-15") == "HB-2",
      "pick_tracked ignores not-yet-introduced HB-3 and picks the best marquee so far")
check(docket.pick_tracked(dk_t, 1, "2026-02-05") == "HB-3",
      "pick_tracked promotes HB-3 once its intro date has passed")
dk_t["bills"]["HB-3"]["stage"] = "SIGNED"
check(docket.pick_tracked(dk_t, 1, "2026-02-05") == "HB-2",
      "pick_tracked skips terminal bills even with the highest marquee")
for b in dk_t["bills"].values():
    b["stage"] = "SIGNED"
check(docket.pick_tracked(dk_t, 1, "2026-02-05") is None,
      "pick_tracked returns None once every bill is terminal")

# --- committee_day is a no-op off its own weekday/session ----------------
check(docket.committee_day(docket.empty_docket(1), EMPTY_MEMBERS, REGULAR_CAL,
                            1, "2026-01-13") == [],
      "Tuesday (a floor day, not a committee day) -> committee_day no-ops")

# --- OIC deficiency notice: search a seed that trips it, verify freeze ----
found_bid = None
for i in range(400):
    bid = f"HB-{9000+i}"
    dk_o = docket.empty_docket(1)
    dk_o["bills"][bid] = {
        "title": "t", "sponsor": "H-01", "cosponsors": [], "committee": "roads",
        "stage": "IN_COMMITTEE", "intro": "2026-01-12", "marquee": 0.5,
        "history": [["2026-01-12", "INTRODUCED"]], "deficiency": None,
        "axis": 0.5, "tags": [], "class": "ordinary",
    }
    docket.committee_day(dk_o, EMPTY_MEMBERS, REGULAR_CAL, 1, "2026-01-14")
    if dk_o["bills"][bid].get("deficiency"):
        found_bid = bid
        break
check(found_bid is not None, "OIC deficiency notices do occur (found within 400 seeds)")
if found_bid:
    defc = dk_o["bills"][found_bid]["deficiency"]
    check(defc["since"] == "2026-01-14", "deficiency notice records its start date")
    check(defc["until"] > defc["since"], "deficiency freeze window is forward-looking")
    frozen_stage = dk_o["bills"][found_bid]["stage"]
    check(frozen_stage == "IN_COMMITTEE", "a deficiency notice does not change the stage")
    # advance through the freeze window: bill should not resolve while frozen
    d = date.fromisoformat("2026-01-15")
    while d.isoformat() < defc["until"]:
        docket.committee_day(dk_o, EMPTY_MEMBERS, REGULAR_CAL, 1, d.isoformat())
        check(dk_o["bills"][found_bid]["deficiency"] is not None
              or dk_o["bills"][found_bid]["stage"] != "IN_COMMITTEE",
              "bill stays frozen (or has since resolved via clearing+same-day "
              "resolution) through its own deficiency window")
        d += timedelta(days=1)

# ===================================================== floor mechanics

# a REPORTED bill on a floor day becomes CALENDARED; a CALENDARED bill on a
# floor day resolves to PASSED_ORIGIN or FAILED_FLOOR with a stored tally
dk_f = docket.empty_docket(1)
dk_f["bills"]["HB-1"] = {
    "title": "t", "sponsor": "H-01", "cosponsors": [], "committee": "roads",
    "stage": "REPORTED", "intro": "2026-01-01", "marquee": 0.5,
    "history": [], "deficiency": None, "axis": 0.5, "tags": [], "class": "ordinary",
}
docket.floor_and_beyond_day(dk_f, EMPTY_MEMBERS, 1, "2026-02-03", floor_open=True)
check(dk_f["bills"]["HB-1"]["stage"] == "CALENDARED",
      "REPORTED -> CALENDARED on a floor-open day")
ev = docket.floor_and_beyond_day(dk_f, EMPTY_MEMBERS, 1, "2026-02-05", floor_open=True)
stage_after = dk_f["bills"]["HB-1"]["stage"]
check(stage_after in ("PASSED_ORIGIN", "FAILED_FLOOR"),
      f"CALENDARED resolves to a floor outcome, got {stage_after}")
tally = dk_f["bills"]["HB-1"]["history"][-1][-1]
check(isinstance(tally, list) and len(tally) == 2, "floor outcome stores a [yea, nay] tally")
yea, nay = tally
check(yea + nay <= 51, "House floor tally never exceeds the 51-seat chamber")
if stage_after == "PASSED_ORIGIN":
    check(yea > nay, "PASSED_ORIGIN implies yea > nay (present-and-voting majority)")
else:
    check(yea <= nay, "FAILED_FLOOR implies yea <= nay")

# floor_open=False withholds floor-stage resolution (e.g. hockey adjournment)
dk_snow = docket.empty_docket(1)
dk_snow["bills"]["HB-1"] = {
    "title": "t", "sponsor": "H-01", "cosponsors": [], "committee": "roads",
    "stage": "CALENDARED", "intro": "2026-01-01", "marquee": 0.5,
    "history": [], "deficiency": None, "axis": 0.5, "tags": [], "class": "ordinary",
}
docket.floor_and_beyond_day(dk_snow, EMPTY_MEMBERS, 1, "2026-02-03", floor_open=False)
check(dk_snow["bills"]["HB-1"]["stage"] == "CALENDARED",
      "floor_open=False leaves a CALENDARED bill untouched (e.g. snow/hockey night)")

# ENROLLED eventually resolves to a governor action
dk_g2 = docket.empty_docket(1)
dk_g2["bills"]["HB-1"] = {
    "title": "t", "sponsor": "H-01", "cosponsors": [], "committee": "roads",
    "stage": "ENROLLED", "intro": "2026-01-01", "marquee": 0.5,
    "history": [], "deficiency": None, "axis": 0.5, "tags": [], "class": "ordinary",
}
d = date.fromisoformat("2026-02-01")
for _ in range(60):
    docket.floor_and_beyond_day(dk_g2, EMPTY_MEMBERS, 1, d.isoformat(), floor_open=True)
    if docket.is_terminal(dk_g2["bills"]["HB-1"]["stage"]):
        break
    d += timedelta(days=1)
check(dk_g2["bills"]["HB-1"]["stage"] in
      ("SIGNED", "VETOED", "OVERRIDDEN", "LAW_NO_SIG"),
      f"ENROLLED eventually resolves to a governor action, got "
      f"{dk_g2['bills']['HB-1']['stage']}")

# ===================================================== per-bill independence

# Two bills processed together vs. one of them processed completely alone
# must produce byte-identical histories for the SHARED bill — proving each
# bill's seeded draws never depend on which siblings share its docket.
def _seed_bill(bid, committee="roads"):
    return {
        "title": "t", "sponsor": "H-01", "cosponsors": [], "committee": committee,
        "stage": "IN_COMMITTEE", "intro": "2026-01-12", "marquee": 0.5,
        "history": [["2026-01-12", "INTRODUCED"]], "deficiency": None,
        "axis": 0.5, "tags": [], "class": "ordinary",
    }


dk_pair = docket.empty_docket(1)
dk_pair["bills"]["HB-A"] = _seed_bill("HB-A")
dk_pair["bills"]["HB-B"] = _seed_bill("HB-B")
dk_solo = docket.empty_docket(1)
dk_solo["bills"]["HB-A"] = _seed_bill("HB-A")

d = date.fromisoformat("2026-01-14")
for _ in range(80):
    ds = d.isoformat()
    docket.committee_day(dk_pair, EMPTY_MEMBERS, REGULAR_CAL, 1, ds)
    docket.committee_day(dk_solo, EMPTY_MEMBERS, REGULAR_CAL, 1, ds)
    d += timedelta(days=1)
check(dk_pair["bills"]["HB-A"] == dk_solo["bills"]["HB-A"],
      "HB-A's fate is identical whether or not HB-B shares its docket "
      "(per-bill seed independence)")

# insertion-order independence: same bills, different dict insertion order
dk_order1 = docket.empty_docket(1)
dk_order1["bills"]["HB-A"] = _seed_bill("HB-A")
dk_order1["bills"]["HB-B"] = _seed_bill("HB-B")
dk_order2 = docket.empty_docket(1)
dk_order2["bills"]["HB-B"] = _seed_bill("HB-B")
dk_order2["bills"]["HB-A"] = _seed_bill("HB-A")
d = date.fromisoformat("2026-01-14")
for _ in range(80):
    ds = d.isoformat()
    docket.committee_day(dk_order1, EMPTY_MEMBERS, REGULAR_CAL, 1, ds)
    docket.committee_day(dk_order2, EMPTY_MEMBERS, REGULAR_CAL, 1, ds)
    d += timedelta(days=1)
check(dk_order1["bills"] == dk_order2["bills"],
      "docket dict insertion order never affects the outcome")

# ===================================================== calibration (Monte Carlo)
# civics-grounding.md + mirror §11: Regular 130-190 introduced, Budget 45-80;
# committee mortality 55-70% (15-25 of those points via Merging referral);
# floor failure <5% of bills reaching third reading. Aggregated over many
# independently-seeded sessions (mirror §10 row C: "50-session Monte Carlo"),
# checking the DISTRIBUTION's mean, not every single session individually.

N_SESSIONS = 30
CM_STAGES = {"DIED_IN_COMMITTEE", "MERGED", "CROSSOVER_BARRED"}

totals, mortalities, merged_pts, floor_fails = [], [], [], []
for ga in range(1, N_SESSIONS + 1):
    dk = run_session(ga, REGULAR_CAL)
    n = len(dk["bills"])
    totals.append(n)
    cm = sum(1 for b in dk["bills"].values() if b["stage"] in CM_STAGES)
    merged = sum(1 for b in dk["bills"].values() if b["stage"] == "MERGED")
    mortalities.append(cm / n)
    merged_pts.append(merged / n)
    resolved = [b for b in dk["bills"].values()
                if any(h[1] in ("PASSED_ORIGIN", "FAILED_FLOOR") for h in b["history"])]
    fails = sum(1 for b in resolved
                if any(h[1] == "FAILED_FLOOR" for h in b["history"]))
    if resolved:
        floor_fails.append(fails / len(resolved))

mean_total = sum(totals) / len(totals)
mean_mortality = sum(mortalities) / len(mortalities)
mean_merged = sum(merged_pts) / len(merged_pts)
mean_floor_fail = sum(floor_fails) / len(floor_fails)

check(130 <= mean_total <= 190,
      f"Regular Session mean bill volume in [130,190]: got {mean_total:.1f}")
check(all(90 <= t <= 230 for t in totals),
      f"every session's volume within a generous sanity band: {min(totals)}-{max(totals)}")
check(0.55 <= mean_mortality <= 0.70,
      f"mean committee mortality (dead+MERGED)/introduced in [0.55,0.70]: "
      f"got {mean_mortality:.3f}")
check(0.15 <= mean_merged <= 0.25,
      f"mean Merging-referral share of introduced in [0.15,0.25] points: "
      f"got {mean_merged:.3f}")
check(mean_floor_fail < 0.05,
      f"mean floor-failure rate of third-reading bills < 5%: got "
      f"{mean_floor_fail:.3f}")

# --- Budget Session volume band ------------------------------------------
budget_totals = []
for ga in range(1, N_SESSIONS + 1):
    cal_b = _budget_cal()
    end = date.fromisoformat(cal_b["sessions"][0]["sine_die"]) + timedelta(days=15)
    days = (end - date.fromisoformat(cal_b["sessions"][0]["start"])).days
    dk = run_session(ga, cal_b, days=days)
    budget_totals.append(len(dk["bills"]))
mean_budget = sum(budget_totals) / len(budget_totals)
check(45 <= mean_budget <= 80,
      f"Budget Session mean bill volume in [45,80]: got {mean_budget:.1f}")

# --- invariant sweep across every simulated bill --------------------------
# yea+nay never exceeds the (51 House / 9 Senate) chamber it was cast in,
# and every stored REPORTED/floor tally is directionally consistent with
# the stage it produced.
bad = []
for ga in range(1, 6):
    dk = run_session(ga, REGULAR_CAL)
    for bid, b in dk["bills"].items():
        origin_size = 51 if bid.startswith("H") else 9
        second_size = 9 if bid.startswith("H") else 51
        # once a bill has crossed (a PASSED_ORIGIN or later entry exists),
        # any subsequent floor tally (REPORTED_2 or a second FAILED_FLOOR)
        # was cast in the OTHER chamber.
        crossed = False
        for h in b["history"]:
            tag = h[1]
            tally = h[-1] if isinstance(h[-1], list) else None
            if tag == "PASSED_ORIGIN":
                crossed = True
            if tally is None:
                continue
            yea, nay = tally
            if tag == "REPORTED":
                if yea <= nay:
                    bad.append((bid, h, "REPORTED without a yea majority"))
                continue    # committee tally, not chamber-sized
            chamber_size = second_size if crossed and tag != "PASSED_ORIGIN" else origin_size
            if yea + nay > chamber_size:
                bad.append((bid, h, f"tally exceeds chamber size {chamber_size}"))
            if tag in ("PASSED_ORIGIN", "PASSED_BOTH", "REPORTED_2") and yea <= nay:
                bad.append((bid, h, "passage stage without yea majority"))
            if tag == "FAILED_FLOOR" and yea > nay:
                bad.append((bid, h, "FAILED_FLOOR with a yea majority"))
check(not bad, f"all stored tallies pass/fail-consistent and chamber-bounded: {bad[:5]}")

print(f"\nstatehouse docket {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
