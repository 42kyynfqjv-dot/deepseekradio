"""Statehouse election engine fixtures: precinct geometry, hidden leans,
the monotonic reveal clock, AP-style call logic, recount flip/ceremony,
rainouts, and carryover — mirror §6 / final.md.

Run directly (no pytest needed):  python3 tests/test_statehouse_elections.py
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.statehouse import elections as el

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


CYCLE = 2026
GA = 1

# a synthetic members sidecar (real members.py doesn't exist yet — this is
# the shape mirror §2's members-ga1.json documents)
MEMBERS = {
    "members": {
        "H-03": {"name": "Doreen Vachon", "party": "round"},
        "S-01": {"name": "Earl Thibodeau", "party": "prov"},
    },
    "officials": {"potholes": {"name": "Bert Demers"}},
}

cycle_a = el.generate_cycle(CYCLE, MEMBERS, GA)
cycle_b = el.generate_cycle(CYCLE, MEMBERS, GA)

# --------------------------------------------------------------- structure

check(cycle_a["schema"] == 1, "schema field")
check(cycle_a["cycle"] == CYCLE, "cycle field")
check(cycle_a["precincts"] == el.PRECINCTS_TOTAL == 171, "171 precincts constant")
check(cycle_a["broadcast_anchor"] is None, "broadcast_anchor starts unset")
check(el.TURNOUT_RANGE[0] <= cycle_a["turnout"] <= el.TURNOUT_RANGE[1],
      "turnout in 35-50% band")

house_ids = set(el.house_ids())
senate_ids = set(el.senate_ids())
check(len(house_ids) == 51, "51 House district ids")
check(len(senate_ids) == 9, "9 Senate district ids")
race_ids = set(cycle_a["races"])
check(race_ids == house_ids | senate_ids | {"potholes"},
      "races cover 51 House + 9 Senate + potholes, nothing else")

# every physical precinct id appears exactly once across the 51 House races
# (the House tier is the ground truth partition; Senate/potholes reuse it)
seen = []
for hid in house_ids:
    seen.extend(p["id"] for p in cycle_a["races"][hid]["precincts"])
check(len(seen) == 171, f"House races' precincts sum to 171 (got {len(seen)})")
check(len(set(seen)) == 171, "House precinct ids are unique")

# Senate races reuse the same physical precincts (union of their House group)
groups = el._senate_groups()
for sid, hids in groups.items():
    expect = set()
    for hid in hids:
        expect |= {p["id"] for p in cycle_a["races"][hid]["precincts"]}
    got = {p["id"] for p in cycle_a["races"][sid]["precincts"]}
    check(got == expect, f"{sid} precinct set == union of its House districts")

potholes_ids = {p["id"] for p in cycle_a["races"]["potholes"]["precincts"]}
check(potholes_ids == set(seen), "potholes race spans all 171 physical precincts")

# ----------------------------------------------------- pharmacy lot/Halfway

h01 = cycle_a["races"]["H-01"]
by_id = {p["id"]: p for p in h01["precincts"]}
check("PHLOT-1" in by_id, "pharmacy lot precinct present in H-01")
check("HFWC-1" in by_id, "Halfway central-count precinct present in H-01")
check(by_id["PHLOT-1"]["wave"] == 1, "pharmacy lot is wave 1 (reports first)")
check(by_id["HFWC-1"]["wave"] == 3, "Halfway central count is wave 3 (dumps late)")

phys = el._build_precincts(CYCLE)
check(phys["H-01"][0]["electors"] < phys["H-01"][1]["electors"],
      "pharmacy lot precinct is smaller than Halfway's central count")

# same physical precinct reports at the same instant regardless of which
# race (House/Senate/potholes) is asking
wstart, wend = el.WAVES[1]
t_house = el._report_offset(CYCLE, "PHLOT-1", wstart, wend)
check(t_house == el._report_offset(CYCLE, "PHLOT-1", wstart, wend),
      "report offset is deterministic")
# find which senate race contains H-01 and confirm shared report time
sid_for_h01 = next(sid for sid, hids in groups.items() if "H-01" in hids)
sen_by_id = {p["id"]: p for p in cycle_a["races"][sid_for_h01]["precincts"]}
check(sen_by_id["PHLOT-1"]["wave"] == by_id["PHLOT-1"]["wave"],
      "pharmacy lot precinct has the same wave in its Senate race too")

# --------------------------------------------------------------- reveal: PL
# at a tiny cursor, pharmacy lot should very plausibly already be in (wave-1
# window is 0-2700s and PHLOT-1 has no rid-dependence), while HFWC-1
# (wave-3, window starts at 7200s) cannot possibly be in yet.
r_early = el.reveal(cycle_a, 50)
check(r_early["races"]["H-01"]["precincts_out"] <= len(by_id), "sane precinct_out at t=50")
r_before_wave3 = el.reveal(cycle_a, el.WAVES[3][0] - 1)
# HFWC-1's report_at is somewhere in [7200, 12600); it cannot have reported
# before the wave-3 window even opens.
hfwc_report_at = el._report_offset(CYCLE, "HFWC-1", *el.WAVES[3])
check(hfwc_report_at >= el.WAVES[3][0], "HFWC-1 cannot report before wave 3 opens")

# ------------------------------------------------------------- determinism

check(cycle_a == cycle_b, "generate_cycle is deterministic (same cycle -> byte-identical)")

# ---------------------------------------------------------- recount margin

for rid, race in cycle_a["races"].items():
    if race["recount"]:
        a, b = race["final"]
        mv = abs(a - b)
        mp = race["margin_pct"]
        check(mp <= el.RECOUNT_MARGIN_PCT + 1e-9 or mv <= el.RECOUNT_MARGIN_VOTES,
              f"{rid} flagged recount actually qualifies (margin {mv}v/{mp}%)")
        check("recount_flip" in race, f"{rid} recount race stores recount_flip")

# ------------------------------------------------------ recount_script

for rid, race in cycle_a["races"].items():
    script = el.recount_script(race, CYCLE)
    if race["recount"]:
        check(len(script) == 3, f"{rid} recount script has 3 ceremony beats")
        check(script[-1]["flip"] == bool(race["recount_flip"]),
              f"{rid} recount_script flip matches stored recount_flip")
    else:
        check(script == [], f"{rid} non-recount race gets no recount script")

# ------------------------------------------------------------ rainouts

n_rainouts = sum(1 for p in cycle_a["races"]["potholes"]["precincts"] if p.get("rainout"))
check(0 <= n_rainouts <= 2, f"0-2 rainout precincts this cycle (got {n_rainouts})")

r_far_future = el.reveal(cycle_a, 10 ** 9)
for rid, race in cycle_a["races"].items():
    rainout_ids = {p["id"] for p in race["precincts"] if p.get("rainout")}
    if rainout_ids:
        rr = r_far_future["races"][rid]
        check(rr["precincts_out"] == len(race["precincts"]) - len(rainout_ids),
              f"{rid}: rainout precincts never report even at cursor=1e9")
        check(rr["precincts_total"] == len(race["precincts"]),
              f"{rid}: precincts_total still counts rainout precincts")

# ----------------------------------------------- call_state never calls recount

for rid, race in cycle_a["races"].items():
    if race["recount"]:
        a, b = race["final"]
        total_precincts = len([p for p in race["precincts"] if not p.get("rainout")])
        status = el.call_state(race, [a, b], total_precincts)
        check(status == el.STATUS_RECOUNT,
              f"{rid} fully-counted recount race settles to RECOUNT, never CALLED")
    else:
        a, b = race["final"]
        total_precincts = len([p for p in race["precincts"] if not p.get("rainout")])
        status = el.call_state(race, [a, b], total_precincts)
        check(status == el.STATUS_CALLED,
              f"{rid} fully-counted non-recount race is CALLED")

# call_state with zero precincts in is always too-early
for rid, race in list(cycle_a["races"].items())[:5]:
    check(el.call_state(race, [0, 0], 0) == el.STATUS_TOO_EARLY,
          f"{rid} zero precincts in -> too-early")

# a landslide (huge margin, tiny remaining) calls almost immediately: one
# big precinct reports with an 800-vote spread while everything still
# outstanding is small enough that the trailing candidate can't catch up
# even winning all of it.
landslide_race = {
    "recount": False,
    "precincts": [{"id": "x1", "wave": 1, "votes": [900, 100]},
                  {"id": "x2", "wave": 1, "votes": [50, 50]},
                  {"id": "x3", "wave": 3, "votes": [50, 50]}],
}
early_status = el.call_state(landslide_race, [900, 100], 1)
check(early_status == el.STATUS_CALLED,
      "landslide race calls after just one precinct (comfortable margin >> remaining)")

# a genuine toss-up doesn't call early
tossup_race = {
    "recount": False,
    "precincts": [{"id": "y1", "wave": 1, "votes": [500, 500]},
                  {"id": "y2", "wave": 2, "votes": [500, 500]},
                  {"id": "y3", "wave": 3, "votes": [500, 500]}],
}
check(el.call_state(tossup_race, [500, 500], 1) == el.STATUS_LEANING,
      "tied race with lots left to count stays LEANING, not CALLED")

# ------------------------------------------------- reveal monotonicity (property)

def _run_monotonic_check(cycle_num, seed_label):
    body = el.generate_cycle(cycle_num, MEMBERS, GA)
    cursors = list(range(0, 13000, 137))
    prev = None
    prev_pct = -1
    bad = False
    for c in cursors:
        rv = el.reveal(body, c)
        if rv["pct_in"] < prev_pct:
            bad = True
        prev_pct = rv["pct_in"]
        if prev is not None:
            for rid, row in rv["races"].items():
                prow = prev["races"][rid]
                if row["precincts_out"] < prow["precincts_out"]:
                    bad = True
                if row["tally"][0] < prow["tally"][0] or row["tally"][1] < prow["tally"][1]:
                    bad = True
                if el._STATUS_RANK[row["status"]] < el._STATUS_RANK[prow["status"]]:
                    bad = True
                # a recount race must never become "called"; a non-recount
                # race must never become "recount"
                if body["races"][rid]["recount"] and row["status"] == el.STATUS_CALLED:
                    bad = True
                if not body["races"][rid]["recount"] and row["status"] == el.STATUS_RECOUNT:
                    bad = True
        prev = rv
    check(not bad, f"reveal monotonicity holds across full timeline ({seed_label})")


_run_monotonic_check(CYCLE, "cycle 2026")
_run_monotonic_check(2028, "cycle 2028")
_run_monotonic_check(2030, "cycle 2030")

# reveal is a pure function of cursor alone: querying cursors out of order
# gives identical results to querying them in order
sample_cursors = [12000, 500, 8000, 100, 4000, 12000, 500]
results_a = [el.reveal(cycle_a, c) for c in sample_cursors]
results_b = [el.reveal(cycle_a, c) for c in sample_cursors]
check(results_a == results_b, "reveal has no hidden state (order of calls doesn't matter)")
check(el.reveal(cycle_a, 500) == el.reveal(cycle_a, 500), "reveal is deterministic per cursor")

# final cursor equals the true final tally for every non-recount, non-rainout race
final_rv = el.reveal(cycle_a, 999999)
for rid, race in cycle_a["races"].items():
    row = final_rv["races"][rid]
    rainout_ids = {p["id"] for p in race["precincts"] if p.get("rainout")}
    if not rainout_ids:
        check(row["tally"] == race["final"],
              f"{rid}: fully-revealed tally matches true final at large cursor")

check(final_rv["pct_in"] >= 95, "pct_in approaches 100% at a very large cursor")

# ---------------------------------------------------------- seat_new_assembly

carry = el.seat_new_assembly(cycle_a, MEMBERS)
check("potholes" not in carry, "seat_new_assembly excludes the non-legislative potholes race")
check(set(carry) == house_ids | senate_ids, "carryover covers every House+Senate seat")
house_count = sum(1 for v in carry.values() if v["chamber"] == "house")
senate_count = sum(1 for v in carry.values() if v["chamber"] == "senate")
check(house_count == 51, f"51 House winners in carryover (got {house_count})")
check(senate_count == 9, f"9 Senate winners in carryover (got {senate_count})")
for rid, row in carry.items():
    a, b = cycle_a["races"][rid]["final"]
    expect_name = cycle_a["races"][rid]["cands"][0 if a >= b else 1]["name"]
    check(row["name"] == expect_name, f"{rid} carryover winner matches final tally")

# ------------------------------------------------------------- calibration
# loose, non-flaky envelopes over many cycles (§11): 0-2 recounts/cycle is
# the target but is itself a distribution — check the aggregate mean, not
# every single draw.
N = 60
recount_counts = []
close_counts = []  # races within 3 points
comfortable_counts = []
for c in range(5000, 5000 + N):
    body = el.generate_cycle(c, None, GA)
    chamber_races = [r for rid, r in body["races"].items() if rid != "potholes"]
    recount_counts.append(sum(1 for r in chamber_races if r["recount"]))
    close_counts.append(sum(1 for r in chamber_races if r["margin_pct"] <= 3.0))
    comfortable_counts.append(sum(1 for r in chamber_races if r["margin_pct"] > 10.0))

avg_recounts = sum(recount_counts) / N
avg_close = sum(close_counts) / N
avg_comfortable = sum(comfortable_counts) / N
check(0.0 <= avg_recounts <= 3.0, f"avg recounts/cycle in a loose 0-3 band (got {avg_recounts:.2f})")
check(1.0 <= avg_close <= 15.0, f"avg races within 3pts in a loose band (got {avg_close:.2f})")
check(avg_comfortable >= 25, f"most races are comfortable (>10pt margin), got avg {avg_comfortable:.2f}/60")

# generate_cycle works with no members at all (fully standalone)
standalone = el.generate_cycle(9999, None, GA)
check(len(standalone["races"]) == 61, "generate_cycle works with members=None")

# ---------------------------------------------------------------- constants

check(el.FIRST_TAKEOVER == "2026-11-03", "first takeover date constant")
check(el.CYCLE_YEARS == 2, "full-chamber cycles are 2 years")
check(el.HOUSE_SEATS == 51 and el.SENATE_SEATS == 9, "51 House / 9 Senate constant")
check("goose" in el.HOUSE_PARTIES and "goose" not in el.SENATE_PARTIES,
      "Goose party is House-only per the seat table (no Senate goose seats)")

print(f"\nstatehouse elections {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
