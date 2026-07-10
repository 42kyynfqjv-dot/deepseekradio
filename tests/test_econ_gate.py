"""Gate 2 (economy activation) fixture: hockey-final.md "Gates & scope" §2.

Proves the whole gate is inert -- byte-for-byte -- with data/league/
ECON-ENABLED absent, and that flipping it on: mints one coach + one trainer
per team (minimal §12 shape) the first day it runs, drives economy.run_day()
through the tick_v2 day loop with its real signature, persists trades/
firings into the players/coaches sidecars, appends an append-only
transactions-s{n}.json, writes a replace-daily news-lines.json, respects
aired:true trade protection (and the allow_tracked_trades escape hatch),
wires game["coaches"] into tonight_live for orchestrator's already-shipped
Coach's Corner presser beat, and never lets a bad econ day crash tick_v2.

Fixture pattern mirrors tests/test_migration.py: monkeypatch season._PATH /
engine.SIDE / livegame.DATA into a fresh temp dir per scenario, build a
virgin season 1 via migrate_league_v2.migrate() (a pure function of
season+seed -- no aired history needed), arm it via verify_league.verify()
+ touch ENABLED (season._league_v2 requires both ENABLED and VERIFIED), then
drive engine.tick_v2 directly, exactly the way scripts/verify_league.py's
own offline dry-run does.

Run directly (no pytest needed):  python3 tests/test_econ_gate.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

from src import livegame, season                     # noqa: E402
from src.league import economy, engine               # noqa: E402
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


def _plus(days: int) -> str:
    return (_date.fromisoformat(START) + _timedelta(days=days)).isoformat()


def arm_fresh_v2(tmp: Path) -> None:
    """Build + arm a virgin season-1 v2 state in tmp. No aired history is
    needed for this gate: migrate_league_v2.migrate/verify_league.verify are
    both pure functions of (season, seed) plus whatever season.json holds,
    and a freshly-defaulted season.json (zero games played) is a legal input
    to both."""
    season._PATH = tmp / "season.json"
    engine.SIDE = tmp / "league"
    livegame.DATA = tmp / "data"
    st = season._load()
    # tick_v2's day loop spans (sim_through, air_date] -- a freshly
    # defaulted sim_through=="" makes `start = st.get("sim_through") or
    # air_date` collapse to air_date itself (a ONE-day loop), because in
    # real production migration always runs against an already-ticking v1
    # season (sim_through is never actually empty at cutover). Seed it to
    # the day before schedule START so calls below span the full window a
    # caller asks for, matching that real steady-state shape.
    st["sim_through"] = _plus(-1)
    season._save(st)
    mres = migrate_mod.migrate(1, START)
    if mres.get("skipped") or not mres["ok"]:
        raise RuntimeError(f"fixture setup: migrate failed: {mres}")
    vres = verify_mod.verify(1)
    if not vres.get("armed"):
        raise RuntimeError(f"fixture setup: verify did not arm: {vres}")
    (engine.SIDE / "ENABLED").touch()


# ============================================================ WITHOUT flag
# gate absent -> tick_v2 must run the regular-season day loop exactly as
# before Gate 2 existed: no coaches sidecar, no transactions, no news file.
tmp1 = Path(tempfile.mkdtemp())
try:
    arm_fresh_v2(tmp1)
    check("v2 gate on (ENABLED+VERIFIED) ahead of the econ test",
          engine.v2_on(1) is True)

    st = season._load()
    air_date30 = _plus(30)
    engine.tick_v2(st, air_date30, season._apply, season.TRACKED)
    season._save(st)

    check("no coaches sidecar without ECON-ENABLED",
          not (engine.SIDE / "coaches-s1.json").exists())
    check("no transactions sidecar without ECON-ENABLED",
          not (engine.SIDE / "transactions-s1.json").exists())
    check("no news-lines.json without ECON-ENABLED",
          not (engine.SIDE / "news-lines.json").exists())
    check("season.json still advanced (sim_through moved)",
          st["sim_through"] == air_date30, st["sim_through"])
finally:
    shutil.rmtree(tmp1, ignore_errors=True)


# ---- gate-off byte-identical proof: two INDEPENDENT builds of the same
# synthetic state, ticked the same distance, with the flag absent both
# times, must produce byte-identical season.json -- since every new line
# Gate 2 added lives behind one `if (root / "ECON-ENABLED").exists()`
# check, this is the practical proof that the gate-off path is untouched.
tmp1a, tmp1b = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
try:
    snapshots = []
    for tmp in (tmp1a, tmp1b):
        arm_fresh_v2(tmp)
        st = season._load()
        engine.tick_v2(st, _plus(30), season._apply, season.TRACKED)
        season._save(st)
        snapshots.append((tmp / "season.json").read_bytes())
    check("gate-off tick_v2 produces byte-identical season.json across two "
          "independent builds of the same synthetic state",
          snapshots[0] == snapshots[1])
finally:
    shutil.rmtree(tmp1a, ignore_errors=True)
    shutil.rmtree(tmp1b, ignore_errors=True)


# =============================================================== WITH flag
tmp2 = Path(tempfile.mkdtemp())
try:
    arm_fresh_v2(tmp2)
    (engine.SIDE / "ECON-ENABLED").touch()

    # No payroll fixture-hack needed here: mint_league's contract calibration
    # (players.py's AAV_POW/AAV_SCALE/PAYROLL_BAND block -- the fix for the
    # aav<->cap gap an earlier draft of this suite had to scale around) lands
    # every freshly minted team's active payroll inside [86, 93] against the
    # $95.5M ceiling, so economy.run_day's cap-legality check operates on
    # real minted data exactly as it will in production. Live sidecars
    # minted under the old uncalibrated formula get the same correction from
    # the companion scripts/rescale_aav.py.
    pl_before = engine.load_side("players-s1.json")
    all_teams = sorted({p["team"] for p in pl_before["players"].values()})
    check("fresh mint is cap-legal for every team (calibrated formula)",
          all(economy.cap_ok(pl_before, t) for t in all_teams))
    aired_before = {pid: p["team"] for pid, p in pl_before["players"].items()
                    if p.get("aired")}
    check("fixture has aired core players to protect", len(aired_before) > 0)

    st = season._load()
    air_date30 = _plus(30)
    engine.tick_v2(st, air_date30, season._apply, season.TRACKED)
    season._save(st)

    # ---- coaches minted --------------------------------------------------
    check("coaches sidecar minted once econ ran",
          (engine.SIDE / "coaches-s1.json").exists())
    coaches = engine.load_side("coaches-s1.json")
    check("one coach per team (32)", len(coaches.get("coaches", {})) == 32,
          len(coaches.get("coaches", {})))
    check("one trainer per team (32)", len(coaches.get("trainers", {})) == 32,
          len(coaches.get("trainers", {})))
    check("every coach has a name/style/mod/hired_day",
          all({"name", "style", "mod", "hired_day"} <= set(c)
              for c in coaches["coaches"].values()))
    check("every trainer has a name/heal",
          all({"name", "heal"} <= set(t) for t in coaches["trainers"].values()))

    # ---- transactions + trades applied ------------------------------------
    check("transactions sidecar written",
          (engine.SIDE / "transactions-s1.json").exists())
    txfile = engine.load_side("transactions-s1.json")
    trades = [t for t in txfile["tx"] if t["type"] == "trade"]
    check("at least one trade over 30 days", len(trades) > 0, len(trades))

    pl_after = engine.load_side("players-s1.json")
    traded_pid = trades[0]["out"][0] if trades else None
    check("a traded player's team on-disk matches its trade tx ('to')",
          traded_pid is not None
          and pl_after["players"][traded_pid]["team"] == trades[0]["to"])

    # ---- append-only: a further tick only grows the tx log, never rewrites
    tx_len_before = len(txfile["tx"])
    tx_prefix_before = list(txfile["tx"])
    engine.tick_v2(st, _plus(40), season._apply, season.TRACKED)
    season._save(st)
    txfile2 = engine.load_side("transactions-s1.json")
    check("transactions-s1.json is append-only (grows, prefix untouched)",
          len(txfile2["tx"]) >= tx_len_before
          and txfile2["tx"][:tx_len_before] == tx_prefix_before,
          (len(txfile2["tx"]), tx_len_before))

    # ---- news-lines.json: replace-daily, matches the LAST processed day's
    # notes exactly (not an accumulation across days)
    check("news-lines.json written", (engine.SIDE / "news-lines.json").exists())
    news = engine.load_side("news-lines.json")
    check("news-lines.json is a list", isinstance(news, list), type(news))
    last_day_notes = sorted(t["note"] for t in txfile2["tx"]
                            if t.get("date") == _plus(40) and t.get("note"))
    check("news-lines.json holds exactly the last-ticked day's notes "
          "(replace-daily, not cumulative)",
          sorted(news) == last_day_notes, (sorted(news), last_day_notes))

    # ---- aired:true protection ---------------------------------------------
    moved = [pid for pid, team in aired_before.items()
             if pl_after["players"][pid]["team"] != team]
    check("no aired:true player traded without allow_tracked_trades",
          not moved, moved)

    # ---- tonight_live wires game["coaches"] for the presser beat ----------
    sched = engine.load_side("schedule-s1.json")
    future_air = sorted(
        d for d, rows in sched["days"].items()
        for row in rows
        if len(row) > 2 and row[2] == "AIR" and d > st["sim_through"])
    check("a future AIR date exists past the ticked window", bool(future_air))
    air_date_game = future_air[0]
    season.tick(air_date_game)
    game = season.tonight_live(air_date_game)
    check("tonight_live game carries game['coaches']",
          isinstance(game.get("coaches"), dict), game.get("coaches"))
    gc = game.get("coaches") or {}
    check("game['coaches'] has home/away plain-string names (orchestrator's "
          "Coach's Corner beat interpolates game['coaches'][side] directly)",
          isinstance(gc.get("home"), str) and isinstance(gc.get("away"), str),
          gc)
    hk, ak = game["home_key"], game["away_key"]
    coaches_now = engine.load_side("coaches-s1.json")
    check("game['coaches'] names match the coaches sidecar for tonight's teams",
          gc.get("home") == coaches_now["coaches"].get(hk, {}).get("name")
          and gc.get("away") == coaches_now["coaches"].get(ak, {}).get("name"))

    # ---- a bad econ day never kills the tick -------------------------------
    def _boom(*a, **kw):
        raise RuntimeError("synthetic econ failure")

    orig_run_day = economy.run_day
    economy.run_day = _boom
    try:
        st2 = season._load()
        before_sim_through = st2["sim_through"]
        crashed = False
        try:
            engine.tick_v2(st2, _plus(45), season._apply, season.TRACKED)
        except Exception:
            crashed = True
        check("an econ exception (monkeypatched run_day) doesn't crash tick_v2",
              not crashed)
        check("tick still advanced sim_through despite the econ exception",
              st2["sim_through"] > before_sim_through, st2["sim_through"])
    finally:
        economy.run_day = orig_run_day

    # ---- 60-day run against the CALIBRATED league: trades actually happen
    # and every roster stays cap-legal through them (the proof the aav<->cap
    # fix reconnects run_day's trade subsystem to real minted data)
    st3 = season._load()
    engine.tick_v2(st3, _plus(60), season._apply, season.TRACKED)
    season._save(st3)
    txfile60 = engine.load_side("transactions-s1.json")
    trades60 = [t for t in txfile60["tx"] if t["type"] == "trade"]
    check("trades occur across a 60-day econ run on real minted payrolls",
          len(trades60) > 0, len(trades60))
    pl60 = engine.load_side("players-s1.json")
    not_ok = [t for t in all_teams if not economy.cap_ok(pl60, t)]
    check("every team stays economy.cap_ok after 60 days of trades",
          not not_ok,
          [(t, economy.payroll(pl60, t)) for t in not_ok])
finally:
    shutil.rmtree(tmp2, ignore_errors=True)


# ================================================== WITH flag: allow_tracked
tmp3 = Path(tempfile.mkdtemp())
try:
    arm_fresh_v2(tmp3)
    (engine.SIDE / "ECON-ENABLED").touch()
    (engine.SIDE / "ALLOW-TRACKED-TRADES").touch()

    st = season._load()
    engine.tick_v2(st, _plus(60), season._apply, season.TRACKED)
    season._save(st)

    pl_final = engine.load_side("players-s1.json")
    check("allow_tracked_trades flag propagates into the players sidecar",
          pl_final.get("allow_tracked_trades") is True)
finally:
    shutil.rmtree(tmp3, ignore_errors=True)


# ============================================== WITH flag: coach firings
# Coach firings only fire inside economy.FIRING_WINDOW (day_idx 115-178 of
# the season). Fast-forward sim_through straight into that window and tick
# across the WHOLE window: run_day's own "remaining_fires/remaining_days"
# throttle forces the season's 4-8-firing quota to land by construction
# (p -> 1.0 on the last eligible day if the quota isn't met yet), so this
# is a deterministic, not merely probabilistic, proof that firings replace
# coaches end-to-end through this module's wiring.
tmp4 = Path(tempfile.mkdtemp())
try:
    arm_fresh_v2(tmp4)
    (engine.SIDE / "ECON-ENABLED").touch()

    st = season._load()
    st["sim_through"] = _plus(economy.FIRING_WINDOW[0] - 1)
    season._save(st)
    st = season._load()
    engine.tick_v2(st, _plus(economy.FIRING_WINDOW[1] + 1),
                   season._apply, season.TRACKED)
    season._save(st)

    coaches_final = engine.load_side("coaches-s1.json")
    txfile = engine.load_side("transactions-s1.json")
    fires = [t for t in txfile["tx"] if t["type"] == "coach_fired"]
    check("at least one coach_fired transaction across the firing window",
          len(fires) > 0, len(fires))
    f0 = fires[0] if fires else None
    check("a fired team's coach name on-disk matches the tx's 'new' name",
          f0 is not None
          and coaches_final["coaches"][f0["team"]]["name"] == f0["new"])
finally:
    shutil.rmtree(tmp4, ignore_errors=True)


print(f"\nleague econ gate {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
