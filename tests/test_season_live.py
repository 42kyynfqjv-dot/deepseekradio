"""Season-layer integration: tonight_live, record_live, reconcile, air-gated
export. Run with plain python3:  python3 tests/test_season_live.py
"""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import livegame, season  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def _air_out(date):
    """Simulate the broadcast airing: mark every chunk + the final narrated,
    so the air-gated export will reveal them (scorebug shows only what aired)."""
    eng = livegame.LiveGame(livegame.read_log(date)["game"])
    for cid in eng._order:
        eng.mark_narrated(cid)
    eng.mark_final_narrated()
    eng.close()


def main():
    tmp = Path(tempfile.mkdtemp())
    season._PATH = tmp / "season.json"
    livegame.DATA = tmp / "data"
    league_json = tmp / "league.json"
    today = "2026-07-08"          # a Wednesday

    # 1. tonight_live: no outcome exists, dressing does
    g = season.tonight_live(today)
    check("no final key", "final" not in g and "ot" not in g)
    check("dressed", all(k in g for k in ("rosters", "refs", "subplot",
                                          "strength_home", "attendance")))
    check("roster shape", len(g["rosters"]["home"]["skaters"]) == 8)
    g2 = season.tonight_live(today)
    check("idempotent matchup", g2["home_key"] == g["home_key"]
          and g2["game_no"] == g["game_no"])
    check("tracked team hosts", g["home_key"] in season.TRACKED
          or g["away_key"] in season.TRACKED)

    # legacy pre-rolled outcome is stripped
    st = season._load()
    st["games"][today]["final"] = [9, 9]
    st["games"][today]["ot"] = True
    season._save(st)
    g3 = season.tonight_live(today)
    check("legacy pre-roll stripped", "final" not in g3)

    # 2. record_live: exactly once, from the log's final
    check("record before final is a no-op", season.record_live(today) is None)
    eng = livegame.LiveGame(g3)
    eng.finish_now()
    eng.close()
    gp_before = season._load()["league"][g3["home_key"]]["gp"]
    line = season.record_live(today)
    check("record returns lore line", bool(line) and "Center Ice" in line)
    st = season._load()
    check("gp folded once", st["league"][g3["home_key"]]["gp"] == gp_before + 1)
    check("recorded flag", st["games"][today]["recorded"] is True)
    check("final folded back", isinstance(st["games"][today].get("final"), list))
    check("second record is a no-op", season.record_live(today) is None)
    check("gp still once", season._load()["league"][g3["home_key"]]["gp"]
          == gp_before + 1)

    # 3. export after the game has AIRED (narration marked; buffer empty in
    # tests -> narrated air_at ~ now, so the scorebug reveals it)
    _air_out(today)
    season.export(str(league_json))
    d = json.loads(league_json.read_text())
    check("export written", "divisions" in d and d["broadcast"] is not None)
    check("aired final published", d["broadcast"]["played"] is True
          and d["broadcast"]["final"] is not None)
    log = livegame.read_log(today)
    check("export final matches log",
          d["broadcast"]["final"] == [log["final"]["h"], log["final"]["a"]])

    # 4. spoiler gate: generation runs ~45 min ahead of air; even NARRATED
    # chunks stamped in the future must not reveal until that air moment passes
    day2 = "2026-07-11"           # Saturday
    gB = season.tonight_live(day2)
    real_air = livegame._air_at
    livegame._air_at = lambda: time.time() + 3600      # 45-min-ahead generation
    engB = livegame.LiveGame(gB)
    engB.advance("P1C1", 300)
    engB.advance("P1C2", 600)
    engB.mark_narrated("P1C1")     # narrated, but air_at is 1h out
    engB.mark_narrated("P1C2")
    season.export(str(league_json))
    b = json.loads(league_json.read_text())["broadcast"]
    check("future-stamped narrated events hidden",
          b["final"] is None and b["live"] is None
          and (b["events"] is None or not b["events"]["goals"]))
    engB.finish_now()
    engB.mark_final_narrated()     # final announced, but air_at is 1h out
    engB.close()
    gpb = season._load()["league"][gB["home_key"]]["gp"]
    season.record_live(day2)
    season.export(str(league_json))
    d = json.loads(league_json.read_text())
    check("folded but unaired final not published",
          d["broadcast"]["final"] is None)
    row = next(r for div in d["divisions"].values() for r in div
               if r["team"] == gB["home"])
    check("standings un-applied for display", row["gp"] == gpb,
          f"{row['gp']} vs {gpb}")
    # (reveal-after-air is proven in step 3 via _air_out at real time; here the
    # narration stamps are permanently ~1h ahead, so they stay hidden by design)
    livegame._air_at = real_air

    # 5. reconciliation: an abandoned mid-game log gets finished + recorded
    day3 = "2026-07-04"           # in the past
    st = season._load()
    st["games"][day3] = dict(st["games"][today], date=day3, game_no=99,
                             recorded=False)
    st["games"][day3].pop("final", None)
    st["games"][day3].pop("ot", None)
    st["games"][day3].pop("so", None)
    season._save(st)
    engC = livegame.LiveGame(st["games"][day3])
    engC.advance("P1C1", 300)
    engC.close()
    season.tick("2026-07-12")
    st = season._load()
    check("abandoned game finished + recorded",
          st["games"][day3].get("recorded") is True)
    check("abandoned log final", livegame.read_log(day3)["final"] is not None)

    # 6. slates on the shared model; tracked teams rest on broadcast nights
    st = season._load()
    wed_slate = st["slates"].get("2026-07-08", [])
    check("slates exist", bool(wed_slate))
    tracked_in_wed = any(h in season.TRACKED or a in season.TRACKED
                         for h, a, *_ in wed_slate)
    check("tracked rest on broadcast nights", not tracked_in_wed)
    thu_slate = st["slates"].get("2026-07-09", [])
    check("weekday slates played", bool(thu_slate))

    # 7. context pairs for the scoreguard allowlist
    pairs = season.context_pairs(st["games"][day2])
    check("context pairs shape", all(len(p) == 2 for p in pairs))

    # 8. season rollover is AIR-GATED: the reset may never run while the
    # finale's narration hasn't reached listeners (the old spoiler bug)
    day4 = "2026-07-15"
    st = season._load()
    st["league"]["mtl"]["gp"] = season.SEASON_GAMES - 1
    g4 = dict(st["games"][today], date=day4, game_no=41, recorded=False,
              home_key="mtl", away_key="nyg",
              home=season._ALL["mtl"], away=season._ALL["nyg"])
    for k in ("final", "ot", "so"):
        g4.pop(k, None)
    st["games"][day4] = g4
    season._save(st)
    livegame._air_at = lambda: time.time() + 3600   # finale narrated, unaired
    engD = livegame.LiveGame(g4)
    engD.finish_now()
    engD.mark_final_narrated()
    engD.close()
    line4 = season.record_live(day4)
    st = season._load()
    check("finale sets rolled_pending", st.get("rolled_pending") is True)
    check("finale lore announces season end", "season" in (line4 or ""))
    season.tick(day4)
    st = season._load()
    check("rollover BLOCKED while finale unaired",
          st["season"] == 1 and st["league"]["mtl"]["gp"] >= season.SEASON_GAMES)
    livegame._air_at = real_air
    # a later finale whose narration HAS aired releases the gate
    day5 = "2026-07-16"
    g5 = dict(g4, date=day5, game_no=42, recorded=False)
    for k in ("final", "ot", "so"):
        g5.pop(k, None)
    st["games"][day5] = g5
    season._save(st)
    engE = livegame.LiveGame(g5)
    engE.finish_now()
    engE.close()
    season.record_live(day5)
    _air_out(day5)
    time.sleep(0.02)
    season.tick(day5)
    st = season._load()
    check("rollover executes once the finale aired", st["season"] == 2,
          f"season={st['season']}")
    check("standings zeroed after gated roll",
          st["league"]["mtl"]["gp"] == 0 and not st.get("rolled_pending"))

    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
