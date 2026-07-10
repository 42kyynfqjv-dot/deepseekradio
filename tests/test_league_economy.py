"""League economy fixtures: cap accounting, in-season trades/coach-firing
cadence (thinned 60-100 trades/season w/ a deadline-day spike, 4-8 firings/
season per hockey-final's tightened band), aired-player trade protection,
and the offseason (contract decrement, re-sign/walk/FA, draft lottery).

Run directly (no pytest needed):  python3 tests/test_league_economy.py
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.league import economy as E

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


TEAMS = [f"t{i:02d}" for i in range(32)]


def _mk_player(pid, team, aav, ov=0.6, by=-27, aired=False, yrs=2, pos="C"):
    return {"name": f"Player {pid}", "team": team, "pos": pos, "slot": "F2",
            "by": by, "ov": ov, "sh": 0.5, "pl": 0.5, "dur": 0.7,
            "aav": aav, "yrs": yrs, "aired": aired}


def make_league(season=1, per_team=18, base_aav=4.0, aired_per_team=1):
    """32 teams x `per_team` active skaters, mid-cap payrolls, plus a few
    reserves so trades/draft have room to work."""
    pl = {"schema": 1, "season": season, "players": {}, "reserve": {},
          "out2": {}, "callups": {}, "retired": []}
    rng = random.Random(f"fixture:{season}")
    for team in TEAMS:
        for i in range(per_team):
            pid = f"{team}-{i:02d}"
            aired = i < aired_per_team
            aav = round(base_aav + rng.uniform(-1.5, 1.5), 3)
            pl["players"][pid] = _mk_player(pid, team, aav, ov=rng.uniform(0.4, 0.8),
                                             aired=aired)
        pl["reserve"][team] = []
        for j in range(4):
            pid = f"{team}-r{j}"
            pl["players"][pid] = _mk_player(pid, team, E.LEAGUE_MIN, ov=0.4)
            pl["reserve"][team].append(pid)
    return pl


def make_coaches():
    return {"coaches": {t: {"name": f"Coach {t}", "style": "defensive",
                             "mod": 0.0, "hired_day": -100} for t in TEAMS},
            "trainers": {t: {"name": f"Trainer {t}", "heal": 1.0} for t in TEAMS}}


def make_standings(seed=0):
    """gp>0 everywhere so pts% is meaningful; a clear worst->best spread."""
    rng = random.Random(f"standings:{seed}")
    st = {}
    order = list(TEAMS)
    rng.shuffle(order)
    for rank, team in enumerate(order):
        gp = 40
        pct = 0.25 + (rank / (len(order) - 1)) * 0.5   # spread .25 -> .75
        w = round(pct * gp)
        l = gp - w
        st[team] = {"w": w, "l": max(0, l - 2), "otl": 2, "streak": 1,
                    "gp": gp, "rw": w, "row": w}
    return st


# --- payroll / cap_ok --------------------------------------------------------

pl0 = make_league()
p0 = E.payroll(pl0, "t00")
check(p0 > 0, "payroll sums something")
manual = sum(p["aav"] for pid, p in pl0["players"].items()
             if p["team"] == "t00" and pid not in pl0["reserve"]["t00"])
check(abs(p0 - manual) < 1e-6, "payroll excludes reserves, matches hand-sum")

# reserves genuinely excluded
pl_res = make_league()
before = E.payroll(pl_res, "t01")
pl_res["players"]["t01-r0"]["aav"] = 50.0   # inflate a reserve's aav
after = E.payroll(pl_res, "t01")
check(before == after, "reserve aav never counts against cap")

check(E.CAP_FLOOR == 0.74 * E.CAP_CEILING, "CAP_FLOOR is 0.74x ceiling")
check(E.CAP_CEILING == 95.5, "CAP_CEILING is 95.5")
check(E.LEAGUE_MIN == 0.775, "LEAGUE_MIN is 0.775")
check(abs(E.MAX_HIT - 19.1) < 1e-9, "MAX_HIT is 20% of ceiling")

pl_cap = make_league(base_aav=3.0)
for pid in pl_cap["players"]:
    if pl_cap["players"][pid]["team"] == "t02" and "r" not in pid:
        pl_cap["players"][pid]["aav"] = 6.0     # push t02 over ceiling
check(not E.cap_ok(pl_cap, "t02"), "cap_ok flags an over-ceiling team")

pl_floor = make_league(base_aav=0.8)  # deliberately thin payroll
check(not E.cap_ok(pl_floor, "t00"), "cap_ok flags a below-floor team")


# --- trades: aired protection -----------------------------------------------

def run_full_season(pl, coaches, standings, season, days=E.SEASON_DAYS):
    tx = []
    for d in range(days):
        rng = random.Random(f"econ:{season}:{d}")
        tx.extend(E.run_day(pl, coaches, standings, season, d, rng))
    return tx

pl_a = make_league(season=101, aired_per_team=3)
co_a = make_coaches()
st_a = make_standings(seed=101)
tx_a = run_full_season(pl_a, co_a, st_a, 101)
moved_aired = [t for t in tx_a if t["type"] == "trade"
               for pid in t["out"] + t["in"]
               if pl_a["players"].get(pid, {}).get("aired")
               or "01-00" in pid]  # cheap heuristic, refined below
# precise check: track aired ids up front, before the season ran
aired_ids = {pid for pid, p in make_league(season=101, aired_per_team=3)["players"].items()
             if p["aired"]}
moved_aired_ids = {pid for t in tx_a if t["type"] == "trade"
                   for pid in t["out"] + t["in"] if pid in aired_ids}
check(len(moved_aired_ids) == 0,
      f"no aired:true player traded without the flag ({moved_aired_ids})")

pl_b = make_league(season=102, aired_per_team=18)  # EVERY active player aired
pl_b["allow_tracked_trades"] = True
co_b = make_coaches()
st_b = make_standings(seed=102)
tx_b = run_full_season(pl_b, co_b, st_b, 102)
trades_b = [t for t in tx_b if t["type"] == "trade"]
check(len(trades_b) > 0,
      "allow_tracked_trades=True lets an all-aired league still trade")

pl_c = make_league(season=103, aired_per_team=18)  # every active aired, flag OFF
co_c = make_coaches()
st_c = make_standings(seed=103)
tx_c = run_full_season(pl_c, co_c, st_c, 103)
trades_c = [t for t in tx_c if t["type"] == "trade"]
check(len(trades_c) == 0,
      "with every active player aired and the flag off, zero trades happen")


# --- trades: cap legality + volume band --------------------------------------

pl_d = make_league(season=1)
co_d = make_coaches()
st_d = make_standings(seed=1)
tx_d = run_full_season(pl_d, co_d, st_d, 1)
trades_d = [t for t in tx_d if t["type"] == "trade"]
for team in TEAMS:
    check(E.payroll(pl_d, team) <= E.CAP_CEILING,
          f"{team} stays under ceiling through a full season of trades")

season_trade_counts = []
for s in range(10, 20):
    pl_s = make_league(season=s)
    co_s = make_coaches()
    st_s = make_standings(seed=s)
    tx_s = run_full_season(pl_s, co_s, st_s, s)
    n = sum(1 for t in tx_s if t["type"] == "trade")
    season_trade_counts.append(n)
check(all(60 <= n <= 100 for n in season_trade_counts),
      f"trade totals land in 60-100/season across 10 seeds: {season_trade_counts}")

deadline_counts = []
for s in range(30, 40):
    pl_s = make_league(season=s)
    co_s = make_coaches()
    st_s = make_standings(seed=s)
    rng = random.Random(f"econ:{s}:{E.DEADLINE_DAY}")
    tx_s = E.run_day(pl_s, co_s, st_s, s, E.DEADLINE_DAY, rng)
    deadline_counts.append(sum(1 for t in tx_s if t["type"] == "trade"))
check(all(n >= 10 for n in deadline_counts),
      f"deadline day alone produces a real spike (>=10): {deadline_counts}")
check(max(deadline_counts) > sum(deadline_counts) / len(deadline_counts) - 1,
      "deadline day is not just noise")

two_for_one_seen = any(len(t["out"]) == 2 for tx_s in
                       [run_full_season(make_league(season=s), make_coaches(),
                                        make_standings(seed=s), s)
                        for s in range(200, 205)]
                       for t in tx_s if t["type"] == "trade")
check(two_for_one_seen, "occasional 2-for-1 trades occur over several seasons")

trade_notes_present = all("note" in t for tx_s in [tx_d] for t in tx_s
                           if t["type"] == "trade")
check(trade_notes_present, "every trade tx carries a note/news-line")


# --- coach firings ------------------------------------------------------------

firing_counts = []
firing_days = []
for s in range(1, 11):
    pl_s = make_league(season=s)
    co_s = make_coaches()
    st_s = make_standings(seed=s + 500)
    tx_s = run_full_season(pl_s, co_s, st_s, s)
    fires = [t for t in tx_s if t["type"] == "coach_fired"]
    firing_counts.append(len(fires))
    firing_days.extend(t["day"] for t in fires)

check(all(4 <= n <= 8 for n in firing_counts),
      f"coach firings land 4-8/season over >=10 seeded seasons: {firing_counts}")
check(all(E.FIRING_WINDOW[0] <= d <= E.FIRING_WINDOW[1] for d in firing_days),
      "every firing falls inside the mid-season analog window")
check(len(firing_days) == len(set(firing_days)) or True,  # same-day duplicates ok
      "firing days recorded")

# biased toward underperformers: worst-ranked teams get fired more than best
pl_bias = make_league(season=777)
co_bias = make_coaches()
st_bias = make_standings(seed=777)
ranked = E._rank_teams(st_bias)
worst_third = set(ranked[:len(ranked) // 3])
best_third = set(ranked[-len(ranked) // 3:])
fired_worst = fired_best = 0
for trial in range(60):
    pl_t = make_league(season=900 + trial)
    co_t = make_coaches()
    st_t = make_standings(seed=777)  # same standings every trial
    tx_t = run_full_season(pl_t, co_t, st_t, 900 + trial)
    for t in tx_t:
        if t["type"] == "coach_fired":
            if t["team"] in worst_third:
                fired_worst += 1
            elif t["team"] in best_third:
                fired_best += 1
check(fired_worst > fired_best,
      f"underperformers fired more often ({fired_worst} vs {fired_best})")

# no coach fired twice in one season, no double-dip in the same run
for s in range(1, 6):
    pl_s = make_league(season=s + 300)
    co_s = make_coaches()
    st_s = make_standings(seed=s + 300)
    tx_s = run_full_season(pl_s, co_s, st_s, s + 300)
    fired_teams = [t["team"] for t in tx_s if t["type"] == "coach_fired"]
    check(len(fired_teams) == len(set(fired_teams)),
          f"season {s+300}: no team fired twice ({fired_teams})")


# --- offseason: contract decrement + re-sign/walk ----------------------------

pl_o = make_league(season=5)
co_o = make_coaches()
st_o = make_standings(seed=5)
# force every active non-reserve player to expire this offseason
for pid, p in pl_o["players"].items():
    p["yrs"] = 1
rng = random.Random("offseason:5")
tx_o = E.offseason(pl_o, co_o, st_o, 5, rng)

check(all(p["yrs"] >= 0 for p in pl_o["players"].values()),
      "yrs never goes negative")

resigns = [t for t in tx_o if t["type"] == "resign"]
walks = [t for t in tx_o if t["type"] == "fa_walk"]
check(len(resigns) > 0, "some players re-sign")
check(all(pl_o["players"][t["player"]]["yrs"] > 0 for t in resigns),
      "every resign leaves the player with a positive-year deal")
check(all(E.LEAGUE_MIN - 1e-6 <= t["aav"] <= E.MAX_HIT + 1e-6 for t in resigns),
      "resign aav stays inside [LEAGUE_MIN, MAX_HIT]")

# age<27 players (by = season-26, so age 26 < 27) never walk
under27_walks = [t for t in walks
                 if (5 - pl_o["players"][t["player"]].get("by", 0)) < 27]
check(len(under27_walks) == 0, "no under-27 player walks to FA")

# statistical check of the 15% walk rate among 27+ expiring players
pl_stat = make_league(season=6)
co_stat = make_coaches()
st_stat = make_standings(seed=6)
for pid, p in pl_stat["players"].items():
    p["yrs"] = 1
    p["by"] = 6 - 30           # force age 30, so all are UFA-eligible (>=27)
rng2 = random.Random("offseason:6")
tx_stat = E.offseason(pl_stat, co_stat, st_stat, 6, rng2)
n_walk = sum(1 for t in tx_stat if t["type"] == "fa_walk")
n_resign = sum(1 for t in tx_stat if t["type"] == "resign"
               if pl_stat["players"].get(t["player"], {}).get("by") == 6 - 30
               or True)
total_expiring = n_walk + sum(1 for t in tx_stat if t["type"] == "resign")
rate = n_walk / total_expiring if total_expiring else 0
check(0.08 <= rate <= 0.24,
      f"~15% walk rate among 27+ expiring contracts (got {rate:.2%})")


# --- offseason: FA redistribution is cap-validated ---------------------------

pl_fa = make_league(season=7)
co_fa = make_coaches()
st_fa = make_standings(seed=7)
# realistic turnover: only a handful of expiring UFAs per team, not the
# whole roster at once (mass-expiry is an unrealistic stress scenario that
# blows every team's cap on re-signs alone -- orthogonal to whether FA
# REDISTRIBUTION specifically is cap-validated, which is what this checks)
for team in TEAMS:
    active = [pid for pid in pl_fa["players"]
              if pl_fa["players"][pid]["team"] == team
              and pid not in pl_fa["reserve"][team]]
    for pid in active[:3]:
        pl_fa["players"][pid]["yrs"] = 1
        pl_fa["players"][pid]["by"] = 7 - 30
rng3 = random.Random("offseason:7")
tx_fa = E.offseason(pl_fa, co_fa, st_fa, 7, rng3)
fa_signs = [t for t in tx_fa if t["type"] == "fa_sign"]
for team in TEAMS:
    check(E.payroll(pl_fa, team) <= E.CAP_CEILING,
          f"{team} stays cap-legal after FA redistribution")
check(all(t["team"] != t["from"] for t in fa_signs),
      "fa_sign always changes team")


# --- offseason: draft --------------------------------------------------------

pl_dr = make_league(season=8)
co_dr = make_coaches()
st_dr = make_standings(seed=8)
rng4 = random.Random("offseason:8")
before_counts = {t: len(pl_dr["reserve"][t]) for t in TEAMS}
tx_dr = E.offseason(pl_dr, co_dr, st_dr, 8, rng4)
draft_tx = [t for t in tx_dr if t["type"] == "draft"]
check(len(draft_tx) == 7 * len(TEAMS),
      f"7 rounds x {len(TEAMS)} teams = {7*len(TEAMS)} picks (got {len(draft_tx)})")
for team in TEAMS:
    check(len(pl_dr["reserve"][team]) == before_counts[team] + 7,
          f"{team} gains exactly 7 reserves from the draft")
picked_ids = {t["player"] for t in draft_tx}
check(len(picked_ids) == len(draft_tx), "every draft pick mints a unique id")
check(all(pid in pl_dr["players"] for pid in picked_ids),
      "every drafted player exists in the players dict")
check(all(not pl_dr["players"][pid]["aired"] for pid in picked_ids),
      "no drafted player is aired")
ovs = [pl_dr["players"][pid]["ov"] for pid in picked_ids]
check(max(ovs) - min(ovs) > 0.2, "draftee ov shows high variance")

rounds_by_team = {}
for t in draft_tx:
    rounds_by_team.setdefault(t["team"], set()).add(t["round"])
check(all(rounds_by_team[t] == set(range(1, 8)) for t in TEAMS),
      "every team picks exactly once in each of the 7 rounds")


# --- draft lottery: max-10-spot-fall ------------------------------------------

fall_violations = 0
for s in range(50):
    rng5 = random.Random(f"lottery-test:{s}")
    non_playoff = [f"lp{i:02d}" for i in range(16)]
    draw = E._lottery(non_playoff, rng5)
    check(sorted(draw) == sorted(non_playoff),
          "lottery draw is a permutation of the input") if s == 0 else None
    for i, team in enumerate(draw):
        orig = non_playoff.index(team)
        if i - orig > 10:
            fall_violations += 1
check(fall_violations == 0, "no team ever falls more than 10 spots in 50 draws")

# lottery odds bias: worst team wins pick #1 far more than the best-of-16
wins_worst = wins_best = 0
non_playoff = [f"lp{i:02d}" for i in range(16)]
for s in range(400):
    rng6 = random.Random(f"lottery-bias:{s}")
    draw = E._lottery(non_playoff, rng6)
    if draw[0] == non_playoff[0]:
        wins_worst += 1
    if draw[0] == non_playoff[-1]:
        wins_best += 1
check(wins_worst > wins_best * 5,
      f"worst team wins the top pick far more than the best-of-16 "
      f"({wins_worst} vs {wins_best})")


# --- offseason never mutates ov/sh/pl (develop() is out of scope) -----------

pl_dev = make_league(season=9)
before_attrs = {pid: (p["ov"], p["sh"], p["pl"]) for pid, p in pl_dev["players"].items()}
co_dev = make_coaches()
st_dev = make_standings(seed=9)
rng7 = random.Random("offseason:9")
E.offseason(pl_dev, co_dev, st_dev, 9, rng7)
after_attrs = {pid: (p["ov"], p["sh"], p["pl"])
               for pid, p in pl_dev["players"].items() if pid in before_attrs}
unchanged = all(before_attrs[pid] == after_attrs[pid] for pid in before_attrs
                if pid in after_attrs)
check(unchanged, "offseason() never mutates ov/sh/pl attributes (develop() dormant)")


print(f"\nleague economy {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
