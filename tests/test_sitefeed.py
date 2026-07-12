"""sitefeed: the sports feed tree derives correctly and can never spoil.

Runs export_sports against synthetic state in a temp cwd (the module reads
v2 sidecars relative to cwd, like everything else) and checks the contract
the web pages rely on: reveal statuses pass through untouched, standings
math, form strings, roster splits, AIR flags, and bytes-identical skip.
"""
import json
import os
import sys
import tempfile
from datetime import date as _date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import season as sn                      # noqa: E402
from src.league import sitefeed                   # noqa: E402

PASS = FAIL = 0


def check(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {label}")


TODAY = "2026-07-11"
D1, D2 = "2026-07-09", "2026-07-10"


def mk_state():
    league = {k: {"w": 0, "l": 0, "otl": 0, "streak": 0, "gp": 0}
              for k in sn._ALL}
    st = {"season": 1, "game_no": 2, "sim_through": TODAY,
          "league": league, "recent_opponents": [], "last_result": "",
          "games": {}, "slates": {}, "out": {}}
    # two finished days + today; mtl wins one, OT-loses one
    st["slates"][D1] = [["mtl", "tbr", 4, 2, 0], ["hfx", "gan", 1, 2, 0]]
    st["slates"][D2] = [["tbr", "mtl", 3, 2, 1], ["yon", "uti", 5, 0, 0]]
    st["slates"][TODAY] = [["hfx", "mtl", 2, 5, 0], ["gan", "tbr", 3, 3, 1]]
    # a recorded broadcast game yesterday
    st["games"][D2] = {"date": D2, "home_key": "nyg", "away_key": "wpg",
                       "home": sn._ALL["nyg"], "away": sn._ALL["wpg"],
                       "recorded": True, "final": [4, 3], "ot": True,
                       "so": False}
    for hk, ak, hg, ag, ot in (st["slates"][D1] + st["slates"][D2]
                               + [["nyg", "wpg", 4, 3, 1]]):
        sn._apply(st, hk, ak, hg, ag, bool(ot))
    st["out"]["mtl"] = [{"player": "Brick Lindqvist", "until": 5}]
    return st


def mk_out(st):
    """A league.json-shaped payload with TODAY reveal-gated: one game still
    upcoming, one live — exactly what _around_rows hands over mid-broadcast."""
    divisions = {}
    for conf in sn.LEAGUE.values():
        for dname, teams in conf.items():
            divisions[dname] = [
                {"team": sn._ALL[k], "tracked": k in sn.TRACKED,
                 **{f: st["league"][k][f] for f in ("gp", "w", "l", "otl")},
                 "pts": 2 * st["league"][k]["w"] + st["league"][k]["otl"]}
                for k, _ in teams]
    around = [
        {"home": sn._ALL["hfx"], "away": sn._ALL["mtl"], "score": None,
         "ot": False, "status": "upcoming"},
        {"home": sn._ALL["gan"], "away": sn._ALL["tbr"], "score": [1, 2],
         "ot": False, "status": "live", "period": 2, "clock": "07:41",
         "scorers": ["Somebody Once"]},
    ]
    broadcast = {"date": TODAY, "home": sn._ALL["mtl"], "away": sn._ALL["nyg"],
                 "final": None, "ot": False, "so": False, "played": False,
                 "live": {"period": 1, "clock": "12:02", "score": [1, 0]}}
    return {"divisions": divisions, "around": around, "broadcast": broadcast}


def mk_sidecars():
    Path("data/league").mkdir(parents=True)
    players = {"schema": 1, "season": 1, "players": {
        "mtl-01": {"team": "mtl", "pos": "C", "slot": "F1", "aav": 7.4,
                   "yrs": 2, "name": "Brick Lindqvist"},
        "mtl-04": {"team": "mtl", "pos": "LD", "slot": "D1", "aav": 5.0,
                   "yrs": 3, "name": "Moose Calhoun"},
        "mtl-09": {"team": "mtl", "pos": "G", "slot": "G1", "aav": 5.8,
                   "yrs": 5, "name": "Tug Petrenko"},
        "mtl-21": {"team": "mtl", "pos": "RW", "slot": "R1", "aav": 0.8,
                   "yrs": 1, "name": "Spare Guy"},
    }, "reserve": {"mtl": ["mtl-21"]}, "out2": {}, "callups": {},
        "retired": []}
    stats = {"schema": 1, "season": 1,
             "skaters": {"mtl-01": [3, 2, 4, 0, 1, 0],
                         "mtl-04": [2, 0, 1, 2, 0, 0]},
             "goalies": {"mtl-09": [3, 1, 2, 0, 90, 81, 0]}}
    day_after = (_date.fromisoformat(TODAY) + timedelta(days=1)).isoformat()
    sched = {"schema": 1, "season": 1, "start": "2026-07-05",
             "days": {day_after: [["mtl", "vic", "AIR"], ["tbr", "hfx"]]},
             "playoff_start": "2027-02-13"}
    json.dump(players, open("data/league/players-s1.json", "w"))
    json.dump(stats, open("data/league/stats-s1.json", "w"))
    json.dump(sched, open("data/league/schedule-s1.json", "w"))


prev = os.getcwd()
with tempfile.TemporaryDirectory() as td:
    os.chdir(td)
    try:
        st = mk_state()
        out = mk_out(st)
        st["games"][TODAY] = {"date": TODAY, "home_key": "mtl",
                              "away_key": "nyg", "home": sn._ALL["mtl"],
                              "away": sn._ALL["nyg"]}
        st["slates"][TODAY].append(["mtl", "nyg", 9, 9, 0])  # must be masked
        mk_sidecars()
        sitefeed.export_sports(st, out, root=Path("www"))

        sb = json.load(open("www/sports/hockey/scoreboard.json"))
        check([d["date"] for d in sb["days"]] == [D1, D2, TODAY],
              "scoreboard days ascending through today")
        today = {(g["hk"], g["ak"]): g for g in sb["days"][-1]["games"]}
        check(today[("hfx", "mtl")]["score"] is None
              and today[("hfx", "mtl")]["status"] == "upcoming",
              "reveal-gated upcoming row passes through unspoiled")
        live = today[("gan", "tbr")]
        check(live["status"] == "live" and live["clock"] == "07:41"
              and live["scorers"] == ["Somebody Once"],
              "live row keeps period/clock/scorers")
        bc = today[("mtl", "nyg")]
        check(bc.get("air") and bc["status"] == "live"
              and bc["score"] == [1, 0],
              "broadcast row rides the aired-only live board")
        check(all(g["score"] != [9, 9] for g in sb["days"][-1]["games"]),
              "slate row for the broadcast pair is masked")
        yest = {(g["hk"], g["ak"]): g for g in sb["days"][-2]["games"]}
        by = yest[("nyg", "wpg")]
        check(by["status"] == "final" and by["score"] == [4, 3] and by["ot"]
              and by.get("air"), "recorded past broadcast is a final with AIR")

        stn = json.load(open("www/sports/hockey/standings.json"))
        boreal = stn["conferences"]["Eastern"]["Boreal"]
        mtl_row = next(r for r in boreal if r["key"] == "mtl")
        check(mtl_row["pts"] == 2 * mtl_row["w"] + mtl_row["otl"],
              "standings points math")
        check(mtl_row["tracked"], "tracked flag survives")
        check(all(boreal[i]["pts"] >= boreal[i + 1]["pts"]
                  for i in range(len(boreal) - 1)), "division sorted by pts")
        # aired-safe form: mtl W then OTL; today's games not yet final
        check(mtl_row["last10"] == "1-0-1" and mtl_row["streak"] == "L1",
              f"form from aired results only "
              f"(got {mtl_row['last10']}/{mtl_row['streak']})")

        mtl = json.load(open("www/sports/hockey/teams/mtl.json"))
        check(len(list(Path("www/sports/hockey/teams").glob("*.json"))) == 32,
              "one page per franchise")
        check([r["res"] for r in mtl["results"]] == ["W", "OTL"],
              "team results chronological, today's unaired games excluded")
        check(mtl["results"][0]["opp"] == sn._ALL["tbr"],
              "opponent names joined")
        check(mtl["upcoming"] and mtl["upcoming"][0]["air"]
              and mtl["upcoming"][0]["opp_key"] == "vic",
              "upcoming honors the schedule's AIR tag")
        check(len(mtl["roster"]["forwards"]) == 1
              and len(mtl["roster"]["defense"]) == 1
              and len(mtl["roster"]["goalies"]) == 1,
              "roster splits by pos incl. LD/RD, reserve excluded")
        g1 = mtl["roster"]["goalies"][0]
        check(g1["svpct"] == 0.9 and g1["gaa"] == 3.0, "goalie derived stats")
        check(mtl["out"] == [{"player": "Brick Lindqvist", "games": 3}],
              "out list carries games remaining")
        check(mtl["arena"] == "the Pardon Centre", "tracked arena present")
        pmc = json.load(open("www/sports/hockey/teams/pmc.json"))
        check(pmc["arena"] is None and not pmc["tracked"],
              "untracked page has no invented arena")

        ld = json.load(open("www/sports/hockey/leaders.json"))
        check(ld["leaders"]["points"][0]["name"] == "Brick Lindqvist",
              "leaders fold from stats sidecar")
        check(ld["leaders"]["wins"][0]["pid"] == "mtl-09",
              "goalie wins leaderboard")

        before = Path("www/sports/hockey/standings.json").stat().st_mtime_ns
        sitefeed.export_sports(st, out, root=Path("www"))
        after = Path("www/sports/hockey/standings.json").stat().st_mtime_ns
        check(before == after, "bytes-identical rewrite skipped")

        idx = json.load(open("www/sports/index.json"))
        check(idx["sports"][0]["key"] == "hockey"
              and idx["sports"][0]["trophy"] == "The Boreal Lantern",
              "sports index names the sport and the trophy")
    finally:
        os.chdir(prev)

print(f"sitefeed {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
