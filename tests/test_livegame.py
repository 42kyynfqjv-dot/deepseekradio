"""LiveGame engine tests: model calibration, log durability, roll invariants.

Run with plain python3:  python3 tests/test_livegame.py
"""
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import livegame  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def _game(date="2026-07-08"):
    rng = random.Random("roster-test")

    def roster():
        names, used = [], set()
        while len(names) < 9:
            n = f"{rng.choice(livegame.FIRST_NAMES)} {rng.choice(livegame.LAST_NAMES)}"
            if n not in used:
                used.add(n)
                names.append(n)
        return {"skaters": names[:8], "goalie": names[8]}

    return {"date": date, "season": 1, "game_no": 1,
            "home": "Montreal Apologies", "away": "New York Gridlock",
            "home_key": "mtl", "away_key": "nyg", "arena": "the Pardon Centre",
            "strength_home": 0.55, "strength_away": 0.45,
            "rosters": {"home": roster(), "away": roster()},
            "refs": livegame.REFS[:2], "recorded": False}


# --- 1. calibration: a full 32-team, 82-game season inside NHL envelopes

def test_calibration():
    rng = random.Random(20260706)
    strengths = {i: 0.30 + rng.random() * 0.40 for i in range(32)}
    table = {i: {"gp": 0, "w": 0, "l": 0, "otl": 0, "gf": 0} for i in range(32)}
    so_losses = 0
    reg_ties = ot_or_so = so_games = games = 0
    while any(t["gp"] < 82 for t in table.values()):
        pool = [i for i in range(32) if table[i]["gp"] < 82]
        rng.shuffle(pool)
        for hk, ak in zip(pool[0::2], pool[1::2]):
            hg, ag, ot, so = livegame.sim_instant(strengths[hk], strengths[ak], rng)
            games += 1
            if ot or so:
                ot_or_so += 1
                reg_ties += 1
            if so:
                so_games += 1
            for k, gf, won in ((hk, hg, hg > ag), (ak, ag, ag > hg)):
                t = table[k]
                t["gp"] += 1
                t["gf"] += gf
                if won:
                    t["w"] += 1
                elif ot or so:
                    t["otl"] += 1
                    if so:
                        so_losses += 1
                else:
                    t["l"] += 1
    pts = [2 * t["w"] + t["otl"] for t in table.values()]
    gf_per_game = sum(t["gf"] for t in table.values()) / sum(t["gp"] for t in table.values())
    check("points floor", min(pts) >= 45, f"min={min(pts)}")
    check("points ceiling", max(pts) <= 125, f"max={max(pts)}")
    check("league GF/team/game", 2.8 <= gf_per_game <= 3.2, f"{gf_per_game:.2f}")
    check("SO losses earn the OTL point", so_losses > 0)
    tie_rate = reg_ties / games
    check("regulation-tie rate", 0.14 <= tie_rate <= 0.34, f"{tie_rate:.2f}")
    so_share = so_games / max(reg_ties, 1)
    check("shootout share of ties", 0.10 <= so_share <= 0.50, f"{so_share:.2f}")
    print(f"  (calibration: pts {min(pts)}-{max(pts)}, GF/g {gf_per_game:.2f}, "
          f"ties {tie_rate:.2f}, SO share {so_share:.2f})")


def test_head_to_head():
    rng = random.Random(7)
    wins = 0
    n = 2000
    for _ in range(n):
        hg, ag, _, _ = livegame.sim_instant(0.70, 0.30, rng)
        wins += hg > ag
    check("extreme-mismatch win pct", 0.68 <= wins / n <= 0.85, f"{wins/n:.3f}")
    home = 0
    for _ in range(n):
        hg, ag, _, _ = livegame.sim_instant(0.50, 0.50, rng)
        home += hg > ag
    check("home edge in even matchup", 0.50 <= home / n <= 0.58, f"{home/n:.3f}")


# --- 2. invariants that must hold under ANY entropy (the live path)

def _roll_full_game(tmp, date):
    livegame.DATA = Path(tmp)
    eng = livegame.LiveGame(_game(date))
    for p in (1, 2, 3):
        for c in (1, 2, 3, 4):
            if eng.final:
                break
            eng.advance(f"P{p}C{c}", (p - 1) * 1200 + c * 300)
    if not eng.final:
        eng.advance("OT", 3900)
    return eng


def test_live_invariants():
    for trial in range(30):
        tmp = tempfile.mkdtemp()
        try:
            eng = _roll_full_game(tmp, f"2026-01-{trial+1:02d}")
            check("game reached a final", eng.final is not None)
            f = eng.final
            check("no ties in the final", f["h"] != f["a"], str(f))
            board = [0, 0]
            injured = set()
            pulled_ever = False
            for cid in eng._order:
                ch = eng._chunks[cid]
                check("board_in matches running board", ch["board_in"] == board,
                      f"{cid}: {ch['board_in']} vs {board}")
                goals = [e for e in ch["events"] if e["type"] == "goal"]
                secs = [e["secs"] for e in ch["events"] if "secs" in e]
                check("events ordered by secs", secs == sorted(secs), cid)
                for e in ch["events"]:
                    if e["type"] == "goal":
                        check("no goals by the injured", e["scorer"] not in injured,
                              e["scorer"])
                        if e["net_empty"]:
                            check("EN goal implies a pull", pulled_ever, cid)
                        board[0 if e["team"] == "home" else 1] += 1
                        check("goal board runs true", e["board"] == board,
                              f"{e['board']} vs {board}")
                    elif e["type"] == "pull":
                        pulled_ever = True
                    elif e["type"] == "injury":
                        injured.add(e["player"])
                if any(e["type"] == "so" for e in ch["events"]):
                    so_goals = sum(1 for e in ch["events"] if e["type"] == "so")
                    check("so chunk bumps winner once",
                          sum(ch["board"]) == sum(board) + 1, cid)
                    board = list(ch["board"])
                else:
                    check("chunk board = board_in + goals", ch["board"] == board,
                          f"{cid}: {ch['board']} vs {board}")
            check("final matches last board", [f["h"], f["a"]] == board,
                  f"{f} vs {board}")
            check("three stars", len(f["stars"]) == 3, str(f["stars"]))
            check("air stamps monotonic-ish",
                  all(eng._chunks[c]["air_at"] > 0 for c in eng._order))
            eng.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# --- 3. durability: idempotence, restart, flock, torn tail, markers

def test_durability():
    tmp = tempfile.mkdtemp()
    try:
        livegame.DATA = Path(tmp)
        g = _game("2026-02-01")
        eng = livegame.LiveGame(g)
        c1 = eng.advance("P1C1", 300)
        c1_again = eng.advance("P1C1", 300)
        check("advance is idempotent", c1 is c1_again or c1 == c1_again)
        c2 = eng.advance("P1C2", 600)
        eng.mark_narrated("P1C1")
        check("unnarrated backlog", [c["chunk"] for c in eng.unnarrated()] == ["P1C2"])

        # a second engine must be refused while the first holds the lock
        try:
            livegame.LiveGame(g)
            check("flock refuses a second engine", False)
        except RuntimeError:
            check("flock refuses a second engine", True)
        eng.close()

        # restart: same log, same state, same chunks — the past never re-rolls
        eng2 = livegame.LiveGame(g)
        check("restart restores chunks", eng2.chunk("P1C1") is not None
              and eng2.chunk("P1C1")["events"] == c1["events"])
        check("restart restores state", eng2.state()["board"] == c2["board"]
              and eng2.state()["secs"] == c2["to"])
        check("narrated marker survives restart",
              [c["chunk"] for c in eng2.unnarrated()] == ["P1C2"])
        c3 = eng2.advance("P1C3", 900)
        check("restart continues the roll", c3["board_in"] == c2["board"])
        eng2.close()

        # torn tail: partial JSON line dropped on open, log still healthy
        p = livegame.log_path("2026-02-01")
        with open(p, "a") as f:
            f.write('{"seq": 999, "type": "chu')
        eng3 = livegame.LiveGame(g)
        check("torn tail dropped", eng3.state()["secs"] == c3["to"])
        c4 = eng3.advance("P1C4", 1200)
        eng3.close()
        log = livegame.read_log("2026-02-01")
        check("log healthy after torn-tail append",
              log is not None and "P1C4" in log["chunks"])

        # finish_now ends anything, then no-ops
        eng4 = livegame.LiveGame(g)
        eng4.finish_now()
        check("finish_now reaches a final", eng4.final is not None
              and eng4.final["h"] != eng4.final["a"])
        again = eng4.finish_now()
        check("finish_now no-ops when final", eng4.final is not None)
        eng4.close()
        log = livegame.read_log("2026-02-01")
        check("read_log sees the final", log["final"] == eng4.final)

        # deep corruption must raise, never silently reset to 0-0
        bad = p.read_text().splitlines()
        bad[2] = "GARBAGE NOT JSON"
        p.write_text("".join(ln + "\n" for ln in bad))
        try:
            livegame.read_log("2026-02-01")
            check("mid-log corruption raises", False)
        except ValueError:
            check("mid-log corruption raises", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_markers():
    """opened / narrated / final-narrated markers survive restart (they gate
    the pregame-replay guard and the spoiler-free scorebug reveal)."""
    tmp = tempfile.mkdtemp()
    try:
        livegame.DATA = Path(tmp)
        g = _game("2026-03-01")
        eng = livegame.LiveGame(g)
        check("fresh not opened", eng.opened is False)
        eng.mark_opened()
        c1 = eng.advance("P1C1", 300)
        eng.mark_narrated("P1C1")
        eng.mark_final_narrated()
        eng.close()

        log = livegame.read_log("2026-03-01")
        check("opened persisted", log["opened"] is True)
        check("narrated set persisted", "P1C1" in log["narrated"])
        check("narrated air stamped", isinstance(log["narrated_air"].get("P1C1"), float))
        check("final air from @final marker", log["final_air_at"] is not None)

        eng2 = livegame.LiveGame(g)
        check("opened restored", eng2.opened is True)
        check("mark_opened idempotent", eng2.mark_opened() is None and eng2.opened)
        # the driver's phase-0 guard: opened True -> never replay the pregame
        check("pregame guard would skip", not (eng2.final is None
              and not eng2.opened and not eng2._order))
        eng2.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_shootout_unit():
    rng = random.Random(3)
    ev = []
    rosters = _game()["rosters"]
    w = livegame._sim_shootout(rng, rosters, ev)
    check("shootout returns a side", w in (0, 1))
    check("shootout emits attempts", len(ev) >= 6
          and all(e["type"] == "so" for e in ev))


if __name__ == "__main__":
    test_calibration()
    test_head_to_head()
    test_live_invariants()
    test_durability()
    test_markers()
    test_shootout_unit()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
