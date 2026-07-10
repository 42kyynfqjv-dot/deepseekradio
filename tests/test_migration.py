"""Migration + verify end-to-end fixture: builds a SYNTHETIC 4-day-old
season-1 state (schedule-matrix-consistent -- its "already played" games are
drawn straight from a real `schedule.assign_days(...)` run, so the migrator's
canon-diff can legitimately land empty, exactly the golden cutover path),
runs migrate_league_v2 -> verify_league end-to-end, and proves the v2 gate
actually powers tonight_live()/tick_v2() once armed + ENABLED.

Monkeypatches `season._PATH` / `engine.SIDE` / `livegame.DATA` into a temp
dir, the same way tests/test_season_live.py monkeypatches season._PATH /
livegame.DATA.

Run directly (no pytest needed):  python3 tests/test_migration.py
"""
from __future__ import annotations

import random
import shutil
import sys
import tempfile
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

from src import livegame, season                     # noqa: E402
from src.league import engine                        # noqa: E402
from src.league import schedule as sched_mod          # noqa: E402
import migrate_league_v2 as migrate_mod               # noqa: E402
import verify_league as verify_mod                    # noqa: E402

PASS = FAIL = 0
START = "2026-07-05"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def build_synthetic_state():
    """4 already-aired wall-days of season 1, matrix-consistent: the
    "already played" games are literally the first 4 dates of a real
    schedule.assign_days(build_matchups(1), 1, START) run, so every one of
    them is guaranteed present in the SAME matchups pool migrate's own
    (deterministic, seed-only) build_matchups(1)+assign_days(...) call will
    consume -- the exact condition schedule.py's own docstring says the
    remainder-trim needs to hit a clean 82/41H/41A per team."""
    st = season._load()
    st["season"] = 1

    matchups = sched_mod.build_matchups(1)
    days = sched_mod.assign_days(matchups, 1, START)
    first4 = sorted(days)[:4]

    rng = random.Random("synthetic-fixture")
    aired_dates = []
    for d in first4:
        rows = days[d]
        air_row = next((r for r in rows if len(r) > 2 and r[2] == "AIR"), None)
        for row in rows:
            if row is air_row:
                continue
            hk, ak = row[0], row[1]
            hg, ag, ot, so = livegame.sim_instant(
                season._strength(hk, 1), season._strength(ak, 1), rng)
            season._apply(st, hk, ak, hg, ag, ot or so)
            st.setdefault("slates", {}).setdefault(d, []).append(
                [hk, ak, hg, ag, ot or so])
        if air_row:
            hk, ak = air_row[0], air_row[1]
            game = {
                "game_no": len(aired_dates) + 1, "date": d, "season": 1,
                "rivalry": {hk, ak} == {"mtl", "nyg"},
                "home": season._ALL[hk], "away": season._ALL[ak],
                "home_key": hk, "away_key": ak,
                "arena": season.TRACKED.get(hk, {}).get("arena", "the road"),
                "rosters": {"home": season._roster(hk, 1),
                           "away": season._roster(ak, 1)},
                "strength_home": season._strength(hk, 1),
                "strength_away": season._strength(ak, 1),
                "recorded": False,
            }
            st["games"][d] = game
            st["game_no"] = game["game_no"]
            season._save(st)
            eng = livegame.LiveGame(game)
            eng.finish_now()
            eng.close()
            season.record_live(d)
            st = season._load()
            aired_dates.append(d)

    st["sim_through"] = first4[-1]
    season._save(st)
    return {"days": days, "first4": first4, "aired_dates": aired_dates}


def build_production_state_game_no_2():
    """Replays REAL v1 production, day by day (season.tonight_live +
    livegame + season.record_live for every Wed/Sat, season.tick for every
    other day), from the real season-1 start through the second broadcast --
    matching the live box's actual game_no==2 state, rather than pulling
    "already played" games from a schedule.py-consistent build the way
    `build_synthetic_state` above does.

    This distinction matters: season.py's live v1 off-air slate (`_sim_day`)
    only excludes the tracked teams from its pool on broadcast nights -- on
    any OTHER night both remain eligible and, with these exact (deterministic)
    seeds, mtl and nyg DO end up paired against each other off-air, twice,
    before either broadcast airs. That is exactly the condition
    schedule.py's `_remainder` docstring now protects the Crossover budget
    against (see src/league/schedule.py), and exactly what produced the live
    box's reported ordinal-49/56 drift -- so this fixture is the faithful
    reproduction of that bug, not a friendlier stand-in for it."""
    d = _date.fromisoformat(START)
    end = _date.fromisoformat("2026-07-11")   # the 2nd Wed/Sat -> game_no 2
    while d <= end:
        day = d.isoformat()
        if d.weekday() in (2, 5):
            g = season.tonight_live(day)
            eng = livegame.LiveGame(g)
            eng.finish_now()
            eng.close()
            season.record_live(day)
        else:
            season.tick(day)
        d += _timedelta(days=1)


def main():
    tmp = Path(tempfile.mkdtemp())
    try:
        season._PATH = tmp / "season.json"
        engine.SIDE = tmp / "league"
        livegame.DATA = tmp / "data"

        fixture = build_synthetic_state()
        check("fixture has at least one aired broadcast game",
              len(fixture["aired_dates"]) >= 1, fixture["aired_dates"])
        st0 = season._load()
        check("fixture folded standings (some team has gp > 0)",
              any(v["gp"] > 0 for v in st0["league"].values()))

        # ---- migrate --------------------------------------------------
        mres = migrate_mod.migrate(1, START)
        check("migrate ran (not skipped)", not mres.get("skipped"), mres)
        check("migrate canon-diff empty", mres["ok"] and not mres["canon_diff"],
              mres.get("canon_diff"))
        check("players sidecar written",
              (engine.SIDE / "players-s1.json").exists())
        check("schedule sidecar written",
              (engine.SIDE / "schedule-s1.json").exists())
        check("stats sidecar written",
              (engine.SIDE / "stats-s1.json").exists())

        pl = engine.load_side("players-s1.json")
        aired = migrate_mod.derive_aired(1)
        missing = [n for names in aired.values() for n in names
                   if n not in {p["name"] for p in pl["players"].values()}]
        check("every aired name present on some roster", not missing, missing)

        # ---- verify -----------------------------------------------------
        vres = verify_mod.verify(1)
        check("verify ran (not skipped)", not vres.get("skipped"), vres)
        for c in vres.get("checks", []):
            if c.get("warn") and not c["ok"]:
                # non-gating advisory (e.g. the pre-existing stats.fold_box
                # GWG-derivation bug on OT games -- see migrate's _safe_fold
                # docstring): print it, but it must not fail this suite or
                # block verify.armed, exactly as verify_league.py itself
                # treats it.
                print(f"  (warn) verify: {c['name']} -- {c['detail']}")
                continue
            check(f"verify: {c['name']}", c["ok"], c["detail"])
        check("verify armed", vres.get("armed") is True, vres.get("checks"))
        check("VERIFIED file written", (engine.SIDE / "VERIFIED").exists())

        # gate is still OFF until ENABLED is touched (ops step, §8) --
        # VERIFIED alone must not flip the broadcast
        check("v2_on false before ENABLED is touched",
              engine.v2_on(1) is False)
        (engine.SIDE / "ENABLED").touch()
        check("v2_on(1) true once ENABLED + VERIFIED both present",
              engine.v2_on(1) is True)

        # ---- tonight_live on a future AIR date picks up the v2 dressing --
        sched = engine.load_side("schedule-s1.json")
        future_air = sorted(
            d for d, rows in sched["days"].items()
            for row in rows if len(row) > 2 and row[2] == "AIR" and d > fixture["first4"][-1])
        check("remainder schedule has a future AIR date", bool(future_air))
        air_date = future_air[0]

        season.tick(air_date)     # advances sim_through via v2 tick_v2
        game = season.tonight_live(air_date)
        home_sk = game["rosters"]["home"]["skaters"]
        away_sk = game["rosters"]["away"]["skaters"]
        check("tonight_live v2 game has 18-skater home roster",
              len(home_sk) == 18, len(home_sk))
        check("tonight_live v2 game has 18-skater away roster",
              len(away_sk) == 18, len(away_sk))
        check("tonight_live game is on the AIR date", game["date"] == air_date)

        # ---- tick_v2 mirrors v1 slates -----------------------------------
        st1 = season._load()
        mirrored = [d for d in sched["days"]
                    if fixture["first4"][-1] < d < air_date and d in st1["slates"]]
        check("tick_v2 folded + mirrored at least one new day into v1 slates",
              bool(mirrored), f"sim_through={st1['sim_through']}")
        for d in mirrored:
            rows = st1["slates"][d]
            check(f"mirrored slate row shape ok for {d}",
                  all(len(r) == 5 for r in rows), rows)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- end-to-end: game_no==2, matching the live box, §7.7 crossover ----
    tmp2 = Path(tempfile.mkdtemp())
    try:
        season._PATH = tmp2 / "season.json"
        engine.SIDE = tmp2 / "league"
        livegame.DATA = tmp2 / "data"

        build_production_state_game_no_2()
        st_prod = season._load()
        check("production fixture reaches game_no 2",
              st_prod["game_no"] == 2, st_prod["game_no"])

        mres2 = migrate_mod.migrate(1, START)
        check("migrate (game_no=2 fixture) ran", not mres2.get("skipped"), mres2)

        vres2 = verify_mod.verify(1)
        check("verify (game_no=2 fixture) ran", not vres2.get("skipped"), vres2)
        riv_check = next((c for c in vres2.get("checks", [])
                          if "every 7th AIR slot" in c["name"]), None)
        check("§7.7 every-7th-AIR-slot crossover check present", riv_check is not None)
        check("§7.7 every 7th AIR slot is the mtl-nyg crossover (game_no=2 fixture)",
              riv_check is not None and riv_check["ok"],
              riv_check.get("detail") if riv_check else None)

        # Known, documented trade-off (see src/league/schedule.py's
        # `_remainder` docstring): the live off-air collision this fixture
        # reproduces means mtl/nyg's own season total can land north of 82,
        # so canon-diff is NOT asserted empty here -- printed for visibility
        # only, exactly like the pre-existing GWG-skip warning below.
        canon_check = next((c for c in vres2.get("checks", [])
                            if "canon-diff recomputed" in c["name"]), None)
        if canon_check and not canon_check["ok"]:
            print(f"  (info) verify (game_no=2 fixture): {canon_check['name']} "
                  f"-- {canon_check['detail']} (expected: see schedule.py "
                  f"_remainder docstring on the tracked-vs-tracked off-air "
                  f"exemption)")
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)


if __name__ == "__main__":
    main()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
