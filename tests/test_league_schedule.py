"""League schedule/calendar property tests (hockey-final Component A).

Run directly (no pytest needed): python3 tests/test_league_schedule.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.league import calendar, schedule

PASS = FAIL = 0
SEEDS = [1, 2, 3, 4, 5, 7, 11]     # >=5 seeds, per hockey-final's property-test mandate
ALL_TEAMS = schedule._ALL_TEAMS
MTL, NYG = schedule.TRACKED


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def bucket_of(a, b):
    for conf in schedule.LEAGUE.values():
        for teams in conf.values():
            if a in teams and b in teams:
                return "division"
    for conf in schedule.LEAGUE.values():
        conf_teams = [t for div in conf.values() for t in div]
        if a in conf_teams and b in conf_teams:
            return "conference"
    return "inter"


def team_totals(matchups):
    """{team: {"gp": n, "h": n, "a": n, "vs": {opp: [h_games, a_games]}}}"""
    t = {k: {"gp": 0, "h": 0, "a": 0, "vs": {}} for k in ALL_TEAMS}
    for h, a in matchups:
        t[h]["gp"] += 1; t[h]["h"] += 1
        t[a]["gp"] += 1; t[a]["a"] += 1
        t[h]["vs"].setdefault(a, [0, 0])[0] += 1
        t[a]["vs"].setdefault(h, [0, 0])[1] += 1
    return t


# --- build_matchups property tests ------------------------------------------

for season in SEEDS:
    m = schedule.build_matchups(season)
    check(len(m) == 1312, f"season {season}: 1312 pairs (got {len(m)})")

    totals = team_totals(m)
    for k in ALL_TEAMS:
        gp, h, a = totals[k]["gp"], totals[k]["h"], totals[k]["a"]
        check(gp == 82, f"season {season}/{k}: GP==82 (got {gp})")
        check(h == 41 and a == 41, f"season {season}/{k}: 41H/41A (got {h}H/{a}A)")

    # crossover: tracked pair exactly 8 meetings, 4H/4A each way
    mtl_vs_nyg = totals[MTL]["vs"].get(NYG, [0, 0])
    check(sum(mtl_vs_nyg) == 8, f"season {season}: mtl-nyg 8 meetings (got {sum(mtl_vs_nyg)})")
    check(mtl_vs_nyg == [4, 4], f"season {season}: mtl-nyg 4H/4A (got {mtl_vs_nyg})")

    # the other 30 teams' bucket totals: exact NHL matrix (26/24/32) for every
    # team whose composition wasn't touched to finance the Crossover; the 10
    # donor teams keep 82/41/41 exactly but carry a documented 1-game shift
    # between two bucket totals (module docstring "Crossover" section).
    off_matrix = 0
    for k in ALL_TEAMS:
        if k in schedule.TRACKED:
            continue
        buckets = {"division": 0, "conference": 0, "inter": 0}
        for opp, (hg, ag) in totals[k]["vs"].items():
            buckets[bucket_of(k, opp)] += hg + ag
        exact = (buckets["division"] == 26 and buckets["conference"] == 24
                 and buckets["inter"] == 32)
        if not exact:
            off_matrix += 1
            check(sum(buckets.values()) == 82,
                  f"season {season}/{k}: donor bucket shift still totals 82 (got {buckets})")
    check(off_matrix <= 10, f"season {season}: at most 10 donor-shifted teams (got {off_matrix})")

# --- assign_days property tests ---------------------------------------------

START = "2026-07-05"


def all_teams_in_day(row):
    return [g[0] for g in row] + [g[1] for g in row]


for season in SEEDS:
    m = schedule.build_matchups(season)
    days = schedule.assign_days(m, season, START)

    # every game placed exactly once
    placed = sum(len(v) for v in days.values())
    check(placed == 1312, f"season {season}: all 1312 games placed (got {placed})")

    # no team plays twice in a day
    bad_day = None
    for d, row in days.items():
        names = all_teams_in_day(row)
        if len(names) != len(set(names)):
            bad_day = d
            break
    check(bad_day is None, f"season {season}: no team twice in a day (first bad: {bad_day})")

    # Dec 24-26 empty, for every year the schedule's dates span
    years = {date.fromisoformat(d).year for d in days}
    blocked_hit = None
    for y in years:
        for md in ((12, 24), (12, 25), (12, 26)):
            iso = date(y, *md).isoformat()
            if days.get(iso):
                blocked_hit = iso
    check(blocked_hit is None, f"season {season}: Dec 24-26 empty (found game on {blocked_hit})")

    # exactly one AIR game every Wed/Sat, tracked-team involved, correct cadence.
    # Walk every calendar day in the schedule's actual span (not just `days`
    # keys) — a Wed/Sat with zero games at all would otherwise silently
    # vanish from this check instead of failing it.
    last_date = max(days)
    air_rows = []
    d = date.fromisoformat(START)
    end = date.fromisoformat(last_date)
    while d <= end:
        iso = d.isoformat()
        wd = d.weekday()
        row = days.get(iso, [])
        air_games = [g for g in row if len(g) == 3 and g[2] == "AIR"]
        if wd in (2, 5) and not schedule._is_blocked(d):
            check(len(air_games) == 1, f"season {season}/{iso}: exactly one AIR game (wed/sat)")
            if air_games:
                air_rows.append(air_games[0])
        else:
            check(len(air_games) == 0, f"season {season}/{iso}: no AIR game on a non-air night")
        d += timedelta(days=1)

    parity_ok = True
    rivalry_ok = True
    for i, g in enumerate(air_rows):
        idx = i + 1
        home, away = g[0], g[1]
        if idx % schedule._RIVALRY_EVERY == 0:
            want = (MTL, NYG) if idx % 2 else (NYG, MTL)
            if (home, away) != want:
                rivalry_ok = False
        else:
            want_home = MTL if idx % 2 else NYG
            if home != want_home or away in schedule.TRACKED:
                parity_ok = False
    check(parity_ok, f"season {season}: AIR home alternates mtl/nyg by game_no-like parity")
    check(rivalry_ok, f"season {season}: every {schedule._RIVALRY_EVERY}th AIR game is the Crossover")
    n_riv = sum(1 for i, g in enumerate(air_rows)
                if (i + 1) % schedule._RIVALRY_EVERY == 0)
    check(n_riv == 8, f"season {season}: 8 crossover AIR nights scheduled (got {n_riv})")

    # back-to-back sets: 10-16 per team
    play_days = {k: [] for k in ALL_TEAMS}
    for d, row in days.items():
        di = calendar.day_index(START, d)
        for name in all_teams_in_day(row):
            play_days[name].append(di)
    b2b_out_of_range = 0
    for k in ALL_TEAMS:
        ds = sorted(play_days[k])
        sets = sum(1 for x, y in zip(ds, ds[1:]) if y - x == 1)
        if not (10 <= sets <= 16):
            b2b_out_of_range += 1
    check(b2b_out_of_range == 0,
          f"season {season}: all 32 teams have 10-16 back-to-back sets "
          f"({b2b_out_of_range} out of range)")

# --- migration variant: remainder sums to exactly 82 ------------------------

for season in SEEDS[:3]:
    m = schedule.build_matchups(season)
    full_days = schedule.assign_days(m, season, START)
    # pretend the first ~20 scheduled dates already aired
    dates = sorted(full_days)[:20]
    played_pairs = [(g[0], g[1]) for d in dates for g in full_days[d]]
    gp_played = {k: 0 for k in ALL_TEAMS}
    for h, a in played_pairs:
        gp_played[h] += 1
        gp_played[a] += 1

    remainder_days = schedule.assign_days(m, season, START,
                                           gp_played=gp_played,
                                           played_pairs=played_pairs)
    remaining_gp = {k: 0 for k in ALL_TEAMS}
    for row in remainder_days.values():
        for g in row:
            remaining_gp[g[0]] += 1
            remaining_gp[g[1]] += 1
    all_82 = all(gp_played[k] + remaining_gp[k] == 82 for k in ALL_TEAMS)
    check(all_82, f"season {season} migration: gp_played + remainder == 82 for every team")

# --- migration variant: crossover cadence continues at the right ordinal ----
#
# The live box hands migration a real 4-day-old season 1 (game_no already >0)
# -- the remainder schedule's every-7th-AIR-ordinal Crossover placement must
# continue counting from THAT ordinal, not restart at 1. Exercised at several
# gp_played offsets (0/1/2/3 broadcasts already aired), each ALSO carrying
# incidental TRACKED-vs-TRACKED off-cadence pair(s) in played_pairs --
# season.py's live v1 off-air slate (`_sim_day`) only excludes the tracked
# teams from its pool on broadcast nights, so mtl/nyg can already have met
# off-air, by chance, before migration ever runs (a real, reproducible
# occurrence, not a fabricated edge case: this exact shape reproduces the live
# box's reported ordinal-49/56 drift). Direction and count of the injected
# chance meetings vary by offset (each single direction, then both at once).
# Asserted, matching verify_league.py's §7.7 bar byte-for-byte:
#   - every one of the 8 SCHEDULED Crossover meetings lands on an ordinal
#     ≡0 mod 7, counting every AIR broadcast the migrated schedule carries;
#   - scheduled crossovers == 8 exactly (the chance meetings never consume
#     the budget -- total season meetings = 8 + chance, the documented
#     season-1 approximation);
#   - EVERY team, tracked included, still totals exactly 82 GP / 41H / 41A
#     across played + remainder (schedule._absorb_chance_meeting's exact
#     donor-repayment cancellation).

_CHANCE_BY_OFFSET = {
    0: [(MTL, NYG)],
    1: [(NYG, MTL)],
    2: [(MTL, NYG), (NYG, MTL)],
    3: [(NYG, MTL), (MTL, NYG)],
}

for season in SEEDS[:3]:
    m = schedule.build_matchups(season)
    full_days = schedule.assign_days(m, season, START)
    air_full = sorted(
        (d, row) for d, rows in full_days.items() for row in rows
        if len(row) > 2 and row[2] == "AIR")

    for offset in (0, 1, 2, 3):
        cutoff = air_full[offset - 1][0] if offset > 0 else None
        played_pairs = []
        played_h = {k: 0 for k in ALL_TEAMS}
        played_a = {k: 0 for k in ALL_TEAMS}
        if cutoff is not None:
            for d, rows in full_days.items():
                if d <= cutoff:
                    for row in rows:
                        played_pairs.append((row[0], row[1]))
                        played_h[row[0]] += 1
                        played_a[row[1]] += 1
        # the incidental off-cadence mtl-nyg meeting(s) (see block comment)
        for ch, ca in _CHANCE_BY_OFFSET[offset]:
            played_pairs.append((ch, ca))
            played_h[ch] += 1
            played_a[ca] += 1
        gp_played = {k: played_h[k] + played_a[k] for k in ALL_TEAMS}

        remainder_days = schedule.assign_days(m, season, START,
                                               gp_played=gp_played,
                                               played_pairs=played_pairs)
        air_rows = sorted(
            (d, row) for d, rows in remainder_days.items() for row in rows
            if len(row) > 2 and row[2] == "AIR")
        bad = [(i, d, row) for i, (d, row) in enumerate(air_rows, start=1)
               if i % schedule._RIVALRY_EVERY == 0
               and {row[0], row[1]} != {MTL, NYG}]
        check(not bad,
              f"season {season} migration offset {offset}: every 7th AIR "
              f"ordinal is the crossover (bad: {bad})")
        n_riv_sched = sum(1 for rows in remainder_days.values() for row in rows
                          if {row[0], row[1]} == {MTL, NYG})
        check(n_riv_sched == 8,
              f"season {season} migration offset {offset}: exactly 8 crossover "
              f"games scheduled in the remainder (got {n_riv_sched})")
        n_riv_air = sum(1 for _, row in air_rows
                        if {row[0], row[1]} == {MTL, NYG})
        check(n_riv_air == 8,
              f"season {season} migration offset {offset}: all 8 scheduled "
              f"crossovers are AIR games (got {n_riv_air})")

        rem_h = {k: 0 for k in ALL_TEAMS}
        rem_a = {k: 0 for k in ALL_TEAMS}
        for rows in remainder_days.values():
            for row in rows:
                rem_h[row[0]] += 1
                rem_a[row[1]] += 1
        bad_totals = [
            (k, played_h[k] + rem_h[k], played_a[k] + rem_a[k])
            for k in ALL_TEAMS
            if played_h[k] + rem_h[k] != 41 or played_a[k] + rem_a[k] != 41]
        check(not bad_totals,
              f"season {season} migration offset {offset}: every team "
              f"(tracked included) at exactly 82/41H/41A across played + "
              f"remainder (bad: {bad_totals})")

# --- calendar.py -------------------------------------------------------------

check(calendar.day_index("2026-07-05", "2026-07-05") == 0, "day_index start==0")
check(calendar.day_index("2026-07-05", "2026-07-12") == 7, "day_index one week later == 7")
check(calendar.is_air_night("2026-07-08") is True, "2026-07-08 is a Wednesday (AIR)")
check(calendar.is_air_night("2026-07-11") is True, "2026-07-11 is a Saturday (AIR)")
check(calendar.is_air_night("2026-07-09") is False, "2026-07-09 (Thu) is not an AIR night")

empty_standings = {k: {"gp": 0} for k in ALL_TEAMS}
check(calendar.phase({}, empty_standings, "2026-07-05") == "regular",
      "phase: no playoff_start yet -> regular")
mid_standings = {k: {"gp": 40} for k in ALL_TEAMS}
check(calendar.phase({"playoff_start": "2027-01-09"}, mid_standings, "2027-02-01") == "regular",
      "phase: regular season not done -> regular even past playoff_start date")
done_standings = {k: {"gp": 82} for k in ALL_TEAMS}
check(calendar.phase({"playoff_start": "2027-01-09"}, done_standings, "2026-12-01") == "regular",
      "phase: done but before playoff_start date -> still regular")
check(calendar.phase({"playoff_start": "2027-01-09"}, done_standings, "2027-01-09") == "playoffs",
      "phase: done + at playoff_start -> playoffs")
check(calendar.phase({"playoff_start": "2027-01-09"}, done_standings, "2027-04-01") == "offseason",
      "phase: well past the playoff window -> offseason")

print(f"\nleague schedule {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
