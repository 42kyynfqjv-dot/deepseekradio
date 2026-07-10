"""League players fixtures: mint a full 32-team league and check the
protected core survives, every slot count matches minimal §9-B's literal
target (12F/6D/2G+4R), team_strength hits target_strength within ±0.01 for
all 32 teams, dress() always returns a legal 18-skater/goalie/backup
lineup (even through injuries), the injury sampler's bucket shares and
man-games-lost land on the grounding bands, maybe_callup clears the
emergency-recall floors, and develop() is pure and never actually called
by anything else in the module (dormant until the economy gate).

Run directly (no pytest needed):  python3 tests/test_league_players.py
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.league import players as P

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


SEASON = 1
TEAMS = [f"t{i:02d}" for i in range(1, 33)]   # 32 synthetic team keys


def _build_aired(seed: str) -> dict:
    """Mimic season._roster()'s output shape: 8 skaters then a goalie, per
    team, globally unique (the real _roster is per-team-seeded and doesn't
    itself guarantee cross-team uniqueness, but a realistic fixture should)."""
    used = set()
    out = {}
    for team in TEAMS:
        rng = random.Random(f"{seed}:{team}")
        names = []
        while len(names) < 9:
            n = f"{rng.choice(P.FIRST_NAMES)} {rng.choice(P.LAST_NAMES)}"
            if n not in used:
                used.add(n)
                names.append(n)
        out[team] = names
    return out


def _build_targets(seed: str) -> dict:
    rng = random.Random(seed)
    return {team: 0.30 + rng.random() * 0.40 for team in TEAMS}


AIRED = _build_aired("aired-fixture")
TARGETS = _build_targets("target-fixture")
LEAGUE = P.mint_league(SEASON, AIRED, TARGETS)

# --- schema shape ------------------------------------------------------
check(LEAGUE["schema"] == 1, "schema tag")
check(LEAGUE["season"] == SEASON, "season tag")
check(set(LEAGUE["reserve"]) == set(TEAMS), "every team has a reserve list")
check(LEAGUE["out2"] == {} and LEAGUE["callups"] == {} and LEAGUE["retired"] == [],
      "fresh mint starts with empty out2/callups/retired")

# --- protected core: aired names survive verbatim ---------------------
all_ok = True
for team, names in AIRED.items():
    team_players = {pid: p for pid, p in LEAGUE["players"].items()
                    if p["team"] == team}
    aired_here = {pid: p for pid, p in team_players.items() if p["aired"]}
    aired_names = {p["name"] for p in aired_here.values()}
    if aired_names != set(names):
        all_ok = False
    if len(aired_here) != 9:
        all_ok = False
check(all_ok, "all 9 aired names appear per team, flagged aired=true, nothing extra")

# --- slot counts: minimal §9-B's literal 12F/6D/2G+4R ------------------
slot_ok = True
for team in TEAMS:
    team_players = [p for p in LEAGUE["players"].values() if p["team"] == team]
    by_slot = {}
    for p in team_players:
        by_slot.setdefault(p["slot"], 0)
        by_slot[p["slot"]] += 1
    if any(by_slot.get(s) != 3 for s in ("F1", "F2", "F3", "F4")):
        slot_ok = False
    if any(by_slot.get(s) != 2 for s in ("D1", "D2", "D3")):
        slot_ok = False
    if by_slot.get("G1") != 1 or by_slot.get("G2") != 1:
        slot_ok = False
    if by_slot.get("R") != 4:
        slot_ok = False
    if len(team_players) != 24:
        slot_ok = False
    if len(LEAGUE["reserve"][team]) != 4:
        slot_ok = False
check(slot_ok, "every team: F1-F4x3, D1-D3x2, G1, G2, +4 reserve = 24 total")

# --- name uniqueness league-wide ---------------------------------------
all_names = [p["name"] for p in LEAGUE["players"].values()]
check(len(all_names) == len(set(all_names)), "no duplicate names league-wide")
check(len(all_names) == 32 * 24, "expected total player count")

# --- required fields present on a sampled player -----------------------
sample = next(iter(LEAGUE["players"].values()))
for key in ("name", "team", "pos", "slot", "by", "ov", "sh", "pl", "dur",
            "aav", "yrs", "aired"):
    check(key in sample, f"player dict carries '{key}'")
check(0.0 <= sample["ov"] <= 1.0, "ov in [0,1]")

# goalie sh/pl are always 0.0
goalies = [p for p in LEAGUE["players"].values() if p["pos"] == "G"]
check(all(p["sh"] == 0.0 and p["pl"] == 0.0 for p in goalies),
      "goalies carry sh=0.0, pl=0.0")

# --- team_strength within +/-0.01 of target, all 32 teams ---------------
# target_strength is drawn uniform over [0.30, 0.70] (matching v1's
# season._strength() range), but team_strength()'s own output clamp is
# deliberately narrower (STR_LO/STR_HI -- calibrate_league.py's max-win-
# streak lever, see that constant's comment in players.py): a target
# outside [STR_LO, STR_HI] is unreachable by construction, and
# mint_league's bisection settles at the nearest clamp edge instead. So
# the +/-0.01 check is against clamp(target, STR_LO, STR_HI), not the raw
# target -- still exact for every team whose target already falls inside
# the clamp, and exercises the pulled-in-to-the-edge behavior for the ones
# that don't.
strength_ok = True
worst = 0.0
for team in TEAMS:
    got = P.team_strength(LEAGUE, {}, team, False)
    expected = max(P.STR_LO, min(P.STR_HI, TARGETS[team]))
    diff = abs(got - expected)
    worst = max(worst, diff)
    if diff > 0.01 + 1e-9:
        strength_ok = False
check(strength_ok, f"team_strength within +/-0.01 of clamp(target, STR_LO, STR_HI) "
                    f"for all 32 teams (worst diff {worst:.4f})")

# b2b dip and coach mod actually move the number
t0 = TEAMS[0]
base = P.team_strength(LEAGUE, {}, t0, False)
dipped = P.team_strength(LEAGUE, {}, t0, True)
check(dipped < base, "b2b flag lowers team_strength")
coached = P.team_strength(LEAGUE, {t0: {"mod": 0.02}}, t0, False)
check(coached > base, "positive coach mod raises team_strength")

# --- dress(): always a legal 18-skater lineup, L1 first -----------------
DATE = "2026-08-01"
d = P.dress(LEAGUE, t0, DATE)
check(len(d["skaters"]) == 18, "dress: 18 skaters")
check(len(d["ids"]) == 18, "dress: 18 ids, parallel to skaters")
check(len(d["weights"]) == 18 and len(d["pweights"]) == 18,
      "dress: weights/pweights parallel to skaters")
check(d["goalie"] is not None and d["backup"] is not None
      and d["goalie"] != d["backup"], "dress: distinct starter and backup")
check(len(set(d["skaters"])) == 18, "dress: no duplicate skaters")
f1_names = {p["name"] for p in LEAGUE["players"].values()
            if p["team"] == t0 and p["slot"] == "F1"}
check(set(d["skaters"][:3]) == f1_names, "dress: L1 (F1) skaters lead the list")

# weights/pweights formula sanity: (ov*(0.5+bias))**GAMMA, never negative
ids_by_name = {p["name"]: pid for pid, p in LEAGUE["players"].items()
               if p["team"] == t0}
for i, name in enumerate(d["skaters"]):
    pid = ids_by_name[name]
    p = LEAGUE["players"][pid]
    exp_w = round((p["ov"] * (0.5 + p["sh"])) ** P.GAMMA, 5)
    exp_pw = round((p["ov"] * (0.5 + p["pl"])) ** P.GAMMA, 5)
    if d["weights"][i] != exp_w or d["pweights"][i] != exp_pw:
        check(False, f"weight formula mismatch for {name}")
        break
else:
    check(True, "weights/pweights match (ov*(0.5+bias))**GAMMA for every skater")

# depth-curve monotonicity: average weight strictly decreases down the lines
avg_w = {}
for slot in ("F1", "F2", "F3", "F4"):
    ws = [round((p["ov"] * (0.5 + p["sh"])) ** P.GAMMA, 5)
          for p in LEAGUE["players"].values()
          if p["slot"] == slot]
    avg_w[slot] = sum(ws) / len(ws)
check(avg_w["F1"] > avg_w["F2"] > avg_w["F3"] > avg_w["F4"],
      f"forward-line draw weight strictly decreases F1>F2>F3>F4 {avg_w}")
avg_d = {}
for slot in ("D1", "D2", "D3"):
    ws = [round((p["ov"] * (0.5 + p["sh"])) ** P.GAMMA, 5)
          for p in LEAGUE["players"].values()
          if p["slot"] == slot]
    avg_d[slot] = sum(ws) / len(ws)
check(avg_d["D1"] > avg_d["D2"] > avg_d["D3"],
      f"D-pair draw weight strictly decreases D1>D2>D3 {avg_d}")
ratio = avg_w["F1"] / avg_w["F4"]
check(2.0 <= ratio <= 12.0, f"L1:L4 draw-weight ratio {ratio:.2f} in a plausible band")

# --- dress() survives injuries: F1 wiped out, still 18 legal skaters ---
import copy
injured_league = copy.deepcopy(LEAGUE)
f1_ids_all = [pid for pid, p in injured_league["players"].items()
              if p["team"] == t0 and p["slot"] == "F1"]
f1_ids = f1_ids_all[:2]   # 2 of the 3 -- the 4-reserve pool has only 2
                          # forward-capable bodies (LW, RW), by design
for pid in f1_ids:
    injured_league["out2"][pid] = {"until": "2026-12-01", "note": "test", "ir": True}
d2 = P.dress(injured_league, t0, DATE)
check(len(d2["skaters"]) == 18, "dress survives 2/3 of the F1 line out (still 18)")
check(not (set(f1_ids) & set(d2["ids"])), "injured F1 skaters are excluded from dress")
check(d2["skaters"] != d["skaters"], "lineup actually changes around the injury")

# healed-by-date player returns
d3 = P.dress(injured_league, t0, "2026-12-02")
check(any(pid in d3["ids"] for pid in f1_ids), "player back once 'until' has passed")

# --- injury sampler: bucket shares + MGL/team-season -------------------
rng = random.Random("injury-fixture")
N = 10000
buckets = {"day-to-day": 0, "week-to-week": 0, "long-term, IR": 0,
           "season-ending, LTIR": 0}
ir_true = 0
for _ in range(N):
    days, note, ir = P.sample_injury(rng)
    check(days >= 1, "injury days >= 1") if days < 1 else None
    buckets[note] += 1
    ir_true += ir
shares = {k: v / N for k, v in buckets.items()}
# FRICTION: the task mandates mu=ln(7), sigma=1.25 exactly. That precise
# lognormal, bucketed at the grounding doc's own 7/30/90-day cut points,
# lands at ~52/36/10/2% -- not the grounding prose's rough 50/30/15/5%
# (its heavier week-to-week tail eats into the long-term/season-ending
# shares). Asserting against the mandated formula's actual output, not
# the prose target, since the mu/sigma is the frozen, non-negotiable part.
check(abs(shares["day-to-day"] - 0.52) < 0.06, f"day-to-day share ~52% ({shares['day-to-day']:.3f})")
check(abs(shares["week-to-week"] - 0.36) < 0.06, f"week-to-week share ~36% ({shares['week-to-week']:.3f})")
check(abs(shares["long-term, IR"] - 0.10) < 0.04, f"long-term share ~10% ({shares['long-term, IR']:.3f})")
check(abs(shares["season-ending, LTIR"] - 0.02) < 0.02,
      f"season-ending share ~2% ({shares['season-ending, LTIR']:.3f})")
check(buckets["day-to-day"] == N - ir_true, "ir flag exactly matches non-day-to-day buckets")

GAMES_PER_DAY = 82.0 / 197.0   # 82 GP spread over the ~197-day season window
mgl_rng = random.Random("mgl-fixture")
trials = 500
mgls = []
for _ in range(trials):
    events = mgl_rng.randint(25, 35)
    total_days = sum(P.sample_injury(mgl_rng)[0] for _ in range(events))
    mgls.append(total_days * GAMES_PER_DAY)
mean_mgl = sum(mgls) / len(mgls)
check(195 - 85 <= mean_mgl <= 195 + 85,
      f"man-games-lost/team-season mean {mean_mgl:.1f} in the 195+/-85 band")

# --- maybe_callup: clears <12F/<6D/<2G floors from reserves -------------
callup_league = copy.deepcopy(LEAGUE)
non_reserve_f = [pid for pid, p in callup_league["players"].items()
                 if p["team"] == t0 and p["pos"] in ("C", "LW", "RW")
                 and pid not in callup_league["reserve"][t0]]
# knock out enough forwards to drop below the 12-healthy floor
for pid in non_reserve_f[:4]:
    callup_league["out2"][pid] = {"until": "2099-01-01", "note": "test", "ir": True}
promoted = P.maybe_callup(callup_league, t0)
promoted_positions = [callup_league["players"][pid]["pos"] for pid in promoted]
check(len(promoted) > 0, "maybe_callup promotes someone when forwards drop below floor")
check(all(pid in callup_league["reserve"][t0] for pid in promoted),
      "maybe_callup only ever promotes from that team's reserve list")
check(all(pos in ("C", "LW", "RW") for pos in promoted_positions),
      "maybe_callup promotes forwards to fill a forward shortfall")

healthy_league = copy.deepcopy(LEAGUE)
check(P.maybe_callup(healthy_league, t0) == [],
      "maybe_callup promotes nobody when the team is healthy")

# --- contract calibration: payroll band + top-heavy shape ----------------
# (the Gate-2 aav<->cap fix -- see players.py's contract-calibration block)
from src.league import economy as _E  # test-only import; players.py stays a leaf

payroll_ok = capok_ok = shape_ok = True
top7_shares = []
worst_pr = None
for mint_season in (1, 2, 3):
    ml = P.mint_league(mint_season, _build_aired(f"aav-fixture-{mint_season}"),
                       _build_targets(f"aav-targets-{mint_season}"))
    for team in TEAMS:
        pr = _E.payroll(ml, team)
        if not (P.PAYROLL_BAND[0] - 0.5 <= pr <= P.PAYROLL_BAND[1] + 0.5):
            payroll_ok = False
            worst_pr = (mint_season, team, pr)
        if not _E.cap_ok(ml, team):
            capok_ok = False
        active = sorted((p["aav"] for pid, p in ml["players"].items()
                         if p["team"] == team
                         and pid not in ml["reserve"][team]), reverse=True)
        share = sum(active[:7]) / _E.CAP_CEILING
        top7_shares.append(share)
        # measured envelope: p5-p95 [0.554, 0.634] over 5 seeds x 32 teams;
        # hard rails a little wider so one tail team can't flake the suite
        if not (0.50 <= share <= 0.68):
            shape_ok = False
        if min(p["aav"] for p in ml["players"].values()
               if p["team"] == team) < P.AAV_MIN - 1e-9:
            shape_ok = False
check(payroll_ok, f"every team payroll inside PAYROLL_BAND across 3 mint seeds "
                   f"(worst: {worst_pr})")
check(capok_ok, "economy.cap_ok true for all 32 teams, all 3 mint seeds")
mean_share = sum(top7_shares) / len(top7_shares)
check(0.55 <= mean_share <= 0.65,
      f"league-mean top-7 payroll share 55-65% of the cap ({mean_share:.3f})")
check(shape_ok, "per-team top-7 share in the [0.50, 0.68] rails and no aav "
                 "below the league minimum")

# --- develop(): pure, and dormant (never called by anything else here) --
before = dict(sample)
dev_rng = random.Random("develop-fixture")
after = P.develop(sample, SEASON, dev_rng)
check(sample == before, "develop() does not mutate its input")
check(isinstance(after, dict) and after is not sample, "develop() returns a new dict")
check(0.0 <= after["ov"] <= 1.0, "develop() keeps ov in range")

_calls = []
_real_develop = P.develop
P.develop = lambda *a, **kw: (_calls.append(1), _real_develop(*a, **kw))[1]
try:
    P.mint_league(SEASON, AIRED, TARGETS)
    P.dress(LEAGUE, t0, DATE)
    P.team_strength(LEAGUE, {}, t0, False)
    P.sample_injury(random.Random("dormant-check"))
    P.maybe_callup(LEAGUE, t0)
finally:
    P.develop = _real_develop
check(_calls == [], "develop() is never called by mint_league/dress/team_strength/"
                     "sample_injury/maybe_callup — dormant until the economy gate")

print(f"\nleague players {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
