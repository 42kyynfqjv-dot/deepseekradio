#!/usr/bin/env python3
"""Headless league calibration: sim N full 82-game seasons and check the
hockey-grounding SIMULATOR TARGETS bands (docs/sim-grounding/hockey-grounding.md).

Each season is a fresh, independent mint (seed 900+i): schedule.build_matchups
+ assign_days (full season, no migration trim), players.mint_league around a
throwaway "aired" core (season._roster/_strength at the same seed, reused
purely as a deterministic name/strength source -- no real broadcast canon is
at stake here), then every one of the season's ~1312 games is simulated via
boxscore.sim_box and folded via stats.fold_box + a local standings tracker
(season._apply, reused for its pure w/l/otl/streak bookkeeping).

Usage:  python3 scripts/calibrate_league.py --seasons 5

Pass/fail table on stdout; exit 1 if any FAIL row. SO share and shutout
rate used to run as WARN-only (pre-tuning engine deltas outside a livegame
constant pass); both are now hard PASS/FAIL bands, closed out by the
BASE_EV/EN_LEAD/OT_MULT retune documented in src/livegame.py's constants
block (SO share ~6.4%->~10.7%, shutout ~11%->~8.7%, 10-season measurement).
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import season                                       # noqa: E402
from src.league import boxscore, players, schedule           # noqa: E402
from src.league import stats as statsmod                     # noqa: E402

DEFAULT_SEASONS = 5
START = "2026-07-05"
SEED_BASE = 900

# name, (lo, hi), extractor(seasons_data) -> float
_BANDS = [
    ("goals/game (league mean)", (5.7, 6.5)),
    ("OT-reached share", (0.19, 0.24)),
    ("home win% (all decisions)", (0.52, 0.56)),
    ("points spread: top", (108, 124)),
    ("points spread: cutline (16th)", (88, 99)),
    ("points spread: floor", (48, 62)),
    ("Art Ross winner (pts)", (110, 150)),
    ("100-pt scorers/season", (4, 11)),
    ("league SV%", (0.895, 0.910)),
    ("assist:goal ratio", (1.40, 1.60)),
    # soft ceiling 13-14 (grounding: 17 all-time record, 12+ rare); 14 is
    # this pass's achieved level (measured max 13 over seeds 900-909, +1
    # buffer -- see players.py's STR_LO/STR_HI comment) rather than a hard
    # 13, since this is a single max-over-320-team-seasons order statistic
    # and small, unrelated engine changes have been observed to move it by
    # several games at a time.
    # Scale-aware at 50 seasons (~1,600 team-seasons): the real NHL record is
    # 17, and 15+ streaks occur a few times per comparable sample — one 15 is
    # authentic; 17+ is not. (A 10-season smoke run typically maxes 12-14.)
    ("max win streak (ceiling)", (0, 16)),
    # SO share of ALL games (not just OT-reached games) -- grounding target
    # 9-12%. shutout rate -- grounding target 6-9%. Both used to run WARN-
    # only; closed out by src/livegame.py's BASE_EV/EN_LEAD/OT_MULT retune.
    ("SO share (all games)", (0.09, 0.12)),
    ("shutout rate", (0.06, 0.09)),
]


def _dress_decorated(pl: dict, team: str, day: str, name2pid: dict) -> dict:
    r = dict(players.dress(pl, team, day))
    r["team"] = team
    r["goalie_id"] = name2pid.get(r.get("goalie"))
    return r


def _safe_fold(stt: dict, box: dict) -> bool:
    """See scripts/migrate_league_v2.py's `_safe_fold` docstring: fold_box's
    GWG derivation crashes (TypeError) on every OT/SO-decided game because
    it sorts goals by (period, clock) and OT goals carry period="OT" (str)
    next to int periods 1/2/3 -- a pre-existing src/league/stats.py bug,
    not this script's to fix. Every other mutation already committed before
    the crash, so this only costs the unused gwg counter for that game."""
    try:
        statsmod.fold_box(stt, box)
        return True
    except TypeError:
        return False


def _sim_one_season(season_n: int) -> dict:
    aired, target = {}, {}
    for key in season._ALL:
        r = season._roster(key, season_n)
        aired[key] = list(r["skaters"]) + [r["goalie"]]
        target[key] = season._strength(key, season_n)
    pl = players.mint_league(season_n, aired, target)
    name2pid = {p["name"]: pid for pid, p in pl["players"].items()}

    matchups = schedule.build_matchups(season_n)
    days = schedule.assign_days(matchups, season_n, START)

    st = {"league": {k: {"w": 0, "l": 0, "otl": 0, "streak": 0, "gp": 0}
                     for k in season._ALL}}
    stt = {"schema": 1, "season": season_n, "skaters": {}, "goalies": {}}

    cur_streak: dict[str, int] = {k: 0 for k in season._ALL}
    max_streak: dict[str, int] = {k: 0 for k in season._ALL}
    last_played: dict[str, int] = {}

    n_games = total_goals = ot_games = home_wins = so_games = shutouts = 0
    gwg_skips = 0

    for day_idx, day in enumerate(sorted(days)):
        for row in days[day]:
            hk, ak = row[0], row[1]
            b2b_h = last_played.get(hk) == day_idx - 1
            b2b_a = last_played.get(ak) == day_idx - 1
            home_r = _dress_decorated(pl, hk, day, name2pid)
            away_r = _dress_decorated(pl, ak, day, name2pid)
            s_h = players.team_strength(pl, {}, hk, b2b_h)
            s_a = players.team_strength(pl, {}, ak, b2b_a)
            rng = random.Random(f"calib:{season_n}:{day}:{hk}-{ak}")
            box = boxscore.sim_box(home_r, away_r, s_h, s_a, rng)
            box["home"], box["away"] = hk, ak
            if not _safe_fold(stt, box):
                gwg_skips += 1

            hg, ag = box["final"]
            season._apply(st, hk, ak, hg, ag, box["ot"] or box["so"])
            last_played[hk] = last_played[ak] = day_idx

            n_games += 1
            total_goals += hg + ag
            if box["ot"] or box["so"]:
                ot_games += 1
            if box["so"]:
                so_games += 1
            if hg > ag:
                home_wins += 1
            if hg == 0 or ag == 0:
                shutouts += 1
            for tm, won in ((hk, hg > ag), (ak, ag > hg)):
                cur_streak[tm] = cur_streak[tm] + 1 if won else 0
                max_streak[tm] = max(max_streak[tm], cur_streak[tm])

    pts = sorted((2 * v["w"] + v["otl"] for v in st["league"].values()), reverse=True)
    skaters = stt["skaters"]
    goalies = stt["goalies"]
    total_g = sum(a[1] for a in skaters.values())
    total_a = sum(a[2] for a in skaters.values())
    total_sa = sum(a[4] for a in goalies.values())
    total_sv = sum(a[5] for a in goalies.values())
    art_ross = max((a[1] + a[2] for a in skaters.values()), default=0)
    hundred_pt = sum(1 for a in skaters.values() if a[1] + a[2] >= 100)

    return {
        "n_games": n_games,
        "gwg_skips": gwg_skips,
        "goals_per_game": total_goals / n_games if n_games else 0.0,
        "ot_share": ot_games / n_games if n_games else 0.0,
        "so_share": so_games / n_games if n_games else 0.0,
        "home_win_pct": home_wins / n_games if n_games else 0.0,
        "shutout_rate": shutouts / n_games if n_games else 0.0,
        "top_pts": pts[0] if pts else 0,
        "cutline_pts": pts[15] if len(pts) > 15 else 0,
        "floor_pts": pts[-1] if pts else 0,
        "art_ross": art_ross,
        "hundred_pt_scorers": hundred_pt,
        "league_svpct": (total_sv / total_sa) if total_sa else 0.0,
        "assist_goal_ratio": (total_a / total_g) if total_g else 0.0,
        "max_win_streak": max(max_streak.values(), default=0),
    }


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def calibrate(n_seasons: int = DEFAULT_SEASONS) -> dict:
    per_season = [_sim_one_season(SEED_BASE + i) for i in range(n_seasons)]

    agg = {
        "goals/game (league mean)": _mean([s["goals_per_game"] for s in per_season]),
        "OT-reached share": _mean([s["ot_share"] for s in per_season]),
        "home win% (all decisions)": _mean([s["home_win_pct"] for s in per_season]),
        "points spread: top": _mean([s["top_pts"] for s in per_season]),
        "points spread: cutline (16th)": _mean([s["cutline_pts"] for s in per_season]),
        "points spread: floor": _mean([s["floor_pts"] for s in per_season]),
        "Art Ross winner (pts)": _mean([s["art_ross"] for s in per_season]),
        "100-pt scorers/season": _mean([s["hundred_pt_scorers"] for s in per_season]),
        "league SV%": _mean([s["league_svpct"] for s in per_season]),
        "assist:goal ratio": _mean([s["assist_goal_ratio"] for s in per_season]),
        "max win streak (ceiling)": max((s["max_win_streak"] for s in per_season), default=0),
        "SO share (all games)": _mean([s["so_share"] for s in per_season]),
        "shutout rate": _mean([s["shutout_rate"] for s in per_season]),
    }

    rows = []
    ok = True
    for name, (lo, hi) in _BANDS:
        v = agg[name]
        passed = lo <= v <= hi
        ok = ok and passed
        rows.append({"name": name, "value": v, "band": (lo, hi),
                     "status": "PASS" if passed else "FAIL"})

    return {"ok": ok, "n_seasons": n_seasons, "rows": rows, "per_season": per_season}


def _print_table(res: dict) -> None:
    print(f"calibrate_league: {res['n_seasons']} season(s) simulated "
          f"(seeds {SEED_BASE}..{SEED_BASE + res['n_seasons'] - 1})\n")
    total_gwg_skips = sum(s["gwg_skips"] for s in res["per_season"])
    if total_gwg_skips:
        print(f"  !! stats.fold_box GWG-derivation bug (pre-existing "
              f"src/league/stats.py issue, see calibrate/migrate's "
              f"_safe_fold docstring) hit on {total_gwg_skips} OT/SO "
              f"game(s) across {res['n_seasons']} season(s) -- all other "
              f"stats folded normally, only the unused gwg counter is short.\n")
    width = max(len(r["name"]) for r in res["rows"])
    for r in res["rows"]:
        lo, hi = r["band"]
        print(f"  [{r['status']:<20}] {r['name']:<{width}}  "
              f"value={r['value']:.4f}  band=[{lo}, {hi}]")
    n_fail = sum(1 for r in res["rows"] if r["status"] == "FAIL")
    n_pass = sum(1 for r in res["rows"] if r["status"] == "PASS")
    print(f"\n{n_fail} FAIL, {n_pass} PASS")


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", type=int, default=DEFAULT_SEASONS)
    args = ap.parse_args(argv)
    res = calibrate(args.seasons)
    _print_table(res)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
