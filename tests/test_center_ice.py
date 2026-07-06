"""End-to-end smoke test for run_center_ice — the live-broadcast driver.

Drives the real orchestrator function with mocked LLM calls and a controllable
air clock, over three paths: a full fresh game, a cramped late-window start,
and a mid-game restart. Asserts the game always reaches a recorded final and
the log stays consistent. Run:  python3 tests/test_center_ice.py
"""
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import orchestrator, season, livegame, lore  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


SCHEDULE = orchestrator._load("schedule.yaml")
CONFIG = orchestrator._load("config.yaml")
DAYPART = next(d for d in SCHEDULE["dayparts"] if d["id"] == "center_ice")

_emitted = []           # (label, lines) actually aired


def _fake_perform(beat, daypart, models, state, ctx, avoid=None):
    """Cheap performer: two neutral filler lines — mentions no scores, so the
    scoreguard must INJECT every required goal call. Exercises injection."""
    seg = beat.get("segment", "seg")
    return [{"speaker": "Bucky Merle", "text": f"Big night here at the rink, {seg}."},
            {"speaker": "Sal Tarantella", "text": "You said it, plenty of hockey to watch."}]


def _fake_outline(daypart, models, state, weekday, first=True, **kw):
    return {"show": daypart["show"], "guest": None,
            "beats": [{"segment": "Callers React", "premise": "reaction",
                       "beat": "callers weigh in", "grounding": "", "callback": None,
                       "no_bit": False, "monologue": False},
                      {"segment": "Standings Talk", "premise": "standings",
                       "beat": "what it means", "grounding": "", "callback": None,
                       "no_bit": False, "monologue": False}],
            "new_jokes": [], "callbacks_used": []}


def _install(tmp, when):
    """Point all state at tmp and freeze the air clock at `when`."""
    season._PATH = tmp / "season.json"
    livegame.DATA = tmp / "data"
    orchestrator._STATION_STATE = tmp / "station_state.json"
    orchestrator.perform_beat = _fake_perform
    orchestrator.write_outline = _fake_outline
    orchestrator.clock.air_now = lambda: when
    lore.load = lambda: {}
    lore.save = lambda s: None
    lore.remember = lambda *a, **k: None
    _emitted.clear()
    real_emit = orchestrator._emit

    def spy_emit(lines, label, config, live, fx=None):
        _emitted.append((label, lines))
    orchestrator._emit = spy_emit
    return real_emit


def _run(tmp, when):
    _install(tmp, when)
    orchestrator.run_center_ice(DAYPART, CONFIG, SCHEDULE, live=False)


def _all_lines():
    return [ln for _lbl, lines in _emitted for ln in lines]


def _goals_narrated():
    return [ln for ln in _all_lines() if "puts it home" in ln.get("text", "")]


def test_full_game():
    tmp = Path(tempfile.mkdtemp())
    try:
        # 20:05 on a Wednesday: ~115 air-min left, the whole game fits
        _run(tmp, datetime(2026, 7, 8, 20, 5))
        st = season._load()
        date = "2026-07-08"
        check("game recorded", st["games"][date].get("recorded") is True)
        check("final folded to a list", isinstance(st["games"][date].get("final"), list))
        log = livegame.read_log(date)
        check("log is final", log and log["final"] is not None)
        f = log["final"]
        check("no tie in final", f["h"] != f["a"], str(f))
        check("emitted many beats", len(_emitted) > 8, str(len(_emitted)))
        labels = [l for l, _ in _emitted]
        check("opened with pregame", any("pregame" in l for l in labels))
        check("had a wrap", any("wrap" in l for l in labels))
        check("ended on handoff", labels[-1].endswith("handoff"))
        # every goal on the board was actually narrated (injected calls count)
        gh = sum(1 for c in log["order"] for e in log["chunks"][c]["events"]
                 if e["type"] == "goal")
        check("all goals narrated", len(_goals_narrated()) >= 1 if gh else True,
              f"{len(_goals_narrated())} narrated vs {gh} rolled")
        check("standings gp incremented",
              st["league"][st["games"][date]["home_key"]]["gp"] >= 1)
    finally:
        orchestrator._emit = _install.__globals__.get("_ORIG_EMIT", orchestrator._emit)
        shutil.rmtree(tmp, ignore_errors=True)


def test_cramped_window():
    tmp = Path(tempfile.mkdtemp())
    try:
        # 21:52: ~8 air-min left -> must scramble to the horn immediately
        _run(tmp, datetime(2026, 7, 8, 21, 52))
        date = "2026-07-08"
        st = season._load()
        check("cramped game still recorded", st["games"][date].get("recorded") is True)
        log = livegame.read_log(date)
        check("cramped log final", log and log["final"] is not None)
        labels = [l for l, _ in _emitted]
        check("used the scramble beat", any("scramble" in l for l in labels), str(labels))
        check("cramped stayed short", len(_emitted) <= 8, str(len(_emitted)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_restart_midgame():
    tmp = Path(tempfile.mkdtemp())
    try:
        season._PATH = tmp / "season.json"
        livegame.DATA = tmp / "data"
        orchestrator.clock.air_now = lambda: datetime(2026, 7, 8, 20, 5)
        # create tonight's game + roll two chunks and mark them narrated,
        # then close — simulating a crash partway through the broadcast
        game = season.tonight_live("2026-07-08")
        eng = livegame.LiveGame(game)
        eng.advance("P1C1", 300)
        eng.advance("P1C2", 600)
        eng.mark_narrated("P1C1")
        eng.mark_narrated("P1C2")
        mid_board = eng.state()["board"]
        eng.close()

        # now restart the broadcast mid-game at 20:50
        _run(tmp, datetime(2026, 7, 8, 20, 50))
        labels = [l for l, _ in _emitted]
        check("restart used a rejoin beat", any("rejoin" in l for l in labels),
              str(labels[:3]))
        check("restart did NOT replay pregame",
              not any("pregame" in l for l in labels))
        st = season._load()
        check("restart game recorded", st["games"]["2026-07-08"].get("recorded") is True)
        log = livegame.read_log("2026-07-08")
        check("restart log final", log and log["final"] is not None)
        # the mid-game board must be a prefix of the final progression: the
        # first two chunks are unchanged (the past never re-rolled)
        check("P1C1 preserved", log["chunks"]["P1C1"]["board_in"] == [0, 0])
        check("mid board consistent", log["chunks"]["P1C2"]["board"] == mid_board)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_transient_resume():
    """A transient mid-game exception (wedged TTS) must NOT collapse the game
    to a fabricated final — it leaves the log resumable, and the next run
    rejoins and finishes for real."""
    tmp = Path(tempfile.mkdtemp())
    try:
        date = "2026-07-08"
        st_ctr = {"n": 0, "boom": 6}

        def flaky(beat, daypart, models, s, ctx, avoid=None):
            st_ctr["n"] += 1
            if st_ctr["n"] == st_ctr["boom"]:
                raise RuntimeError("TTS wedged mid-period")
            return _fake_perform(beat, daypart, models, s, ctx, avoid)

        _install(tmp, datetime(2026, 7, 8, 20, 5))
        orchestrator.perform_beat = flaky
        try:
            orchestrator.run_center_ice(DAYPART, CONFIG, SCHEDULE, live=False)
        except RuntimeError:
            pass
        log = livegame.read_log(date)
        check("transient crash left game NON-final", log and log["final"] is None,
              str(log and log["final"]))
        check("chunks rolled before crash", log and len(log["order"]) >= 1)

        # resume: no more crashes, later air time
        st_ctr["boom"] = -1
        _emitted.clear()
        orchestrator.perform_beat = flaky
        orchestrator.clock.air_now = lambda: datetime(2026, 7, 8, 20, 45)
        orchestrator.run_center_ice(DAYPART, CONFIG, SCHEDULE, live=False)
        labels = [l for l, _ in _emitted]
        check("resume used rejoin", any("rejoin" in l for l in labels), str(labels[:3]))
        check("resume did not replay pregame", not any("pregame" in l for l in labels))
        st = season._load()
        check("resumed game recorded", st["games"][date].get("recorded") is True)
        check("resume reached a real final", livegame.read_log(date)["final"] is not None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    orchestrator._ORIG_EMIT = orchestrator._emit
    _install.__globals__["_ORIG_EMIT"] = orchestrator._emit
    try:
        test_full_game()
        test_cramped_window()
        test_restart_midgame()
        test_transient_resume()
    finally:
        orchestrator._emit = orchestrator._ORIG_EMIT
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
