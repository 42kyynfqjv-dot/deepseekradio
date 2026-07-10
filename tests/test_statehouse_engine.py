"""Statehouse integration-spine fixture: bootstrap_statehouse.py ->
verify_statehouse.py end-to-end, the gate staying off until verify arms it,
sim_day's determinism/self-healing under total civics.json+sidecar loss, the
air-gated GA-rollover phase machine (refuses without an aired stamp,
executes once one appears), the chunked catch-up bound, and the snow-quorum
weather input hook.

Monkeypatches `engine.SIDE` / `engine._CIV_PATH` into a temp dir per
section, the same way tests/test_migration.py monkeypatches
`season._PATH` / `engine.SIDE` / `livegame.DATA`.

Run directly (no pytest needed):  python3 tests/test_statehouse_engine.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from datetime import date as _date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

from src.statehouse import calendar as cal_mod        # noqa: E402
from src.statehouse import docket                      # noqa: E402
from src.statehouse import engine                        # noqa: E402
from src.statehouse import members                        # noqa: E402
import bootstrap_statehouse as bootstrap_mod                # noqa: E402
import verify_statehouse as verify_mod                       # noqa: E402

PASS = FAIL = 0
GA = 1
BOOTSTRAP_TARGET = "2026-07-10"     # fixed date -- reproducible, ~180-day replay


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def _tmp_env():
    """A fresh temp dir with engine.SIDE/_CIV_PATH pointed at it. Returns
    (tmp, root, civ_path); caller is responsible for cleanup."""
    tmp = Path(tempfile.mkdtemp())
    root = tmp / "statehouse"
    civ_path = tmp / "civics.json"
    engine.SIDE = root
    engine._CIV_PATH = civ_path
    return tmp, root, civ_path


# =============================================================== section 1

def section_bootstrap_verify_green():
    """bootstrap -> verify end-to-end green: canon-diff empty, every
    gating check passes, VERIFIED written."""
    tmp, root, civ_path = _tmp_env()
    try:
        bres = bootstrap_mod.bootstrap(BOOTSTRAP_TARGET)
        check("bootstrap ok", bres["ok"], bres.get("canon_diff"))
        check("bootstrap canon-diff empty", not bres["canon_diff"], bres["canon_diff"])
        check("bootstrap reached target", bres["reached_target"])
        check("bootstrap docket in the 130-190 volume band (mirror §11)",
              130 <= bres["bills_total"] <= 190, bres["bills_total"])
        check("bootstrap tracked pointer set", bool(bres["tracked"].get("id")),
              bres["tracked"])
        check("aired ledger untouched by bootstrap (nothing has aired)",
              bres["civ"].get("aired") == {}, bres["civ"].get("aired"))

        vres = verify_mod.verify(GA)
        for c in vres["checks"]:
            check(f"verify: {c['name']}", c["ok"] or c["warn"], c["detail"])
        check("verify armed", vres["armed"] is True,
              [c for c in vres["checks"] if not c["ok"]])
        check("VERIFIED file written", (root / "VERIFIED").exists())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# =============================================================== section 2

def section_gate_off_until_verify():
    """The gate stays off through bootstrap and even through a written
    VERIFIED, until ENABLED is ALSO touched by hand (mirror §9.7/G4)."""
    tmp, root, civ_path = _tmp_env()
    try:
        bootstrap_mod.bootstrap(BOOTSTRAP_TARGET)
        check("gate off right after bootstrap (no VERIFIED yet)",
              engine.statehouse_on(GA) is False)

        vres = verify_mod.verify(GA)
        check("verify armed (VERIFIED written)", vres["armed"] is True)
        check("gate STILL off with VERIFIED but no ENABLED",
              engine.statehouse_on(GA) is False)

        (root / "ENABLED").touch()
        check("gate on once ENABLED + VERIFIED both present",
              engine.statehouse_on(GA) is True)

        # tamper with the immutable core after verify -- hash drift refuses
        cal = engine.load_side(f"calendar-ga{GA}.json", root)
        cal["sessions"][0]["note"] = "tampered"
        engine.save_side(f"calendar-ga{GA}.json", cal, root)
        check("gate refuses once the immutable core drifts from VERIFIED",
              engine.statehouse_on(GA) is False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# =============================================================== section 3

def section_self_healing():
    """sim_day is deterministic: two from-scratch bootstraps to the same
    target date produce byte-identical civ/dk/mem/cal. And the literal
    scenario the task names -- delete civics.json mid-flight, re-derive --
    self-heals to the same state a from-scratch run reaches, because
    bootstrap always re-mints GA 1 from scratch rather than trusting
    whatever partial state survived."""
    tmp_a, root_a, civ_a = _tmp_env()
    res_a = bootstrap_mod.bootstrap(BOOTSTRAP_TARGET, root=root_a, civ_path=civ_a)

    tmp_b, root_b, civ_b = _tmp_env()
    res_b = bootstrap_mod.bootstrap(BOOTSTRAP_TARGET, root=root_b, civ_path=civ_b)

    try:
        check("two from-scratch bootstraps: civics.json identical",
              res_a["civ"] == res_b["civ"])
        check("two from-scratch bootstraps: docket identical",
              res_a["dk"] == res_b["dk"])
        check("two from-scratch bootstraps: members identical",
              res_a["mem"] == res_b["mem"])
        check("two from-scratch bootstraps: calendar identical",
              res_a["cal"] == res_b["cal"])

        # the literal scenario: delete civics.json (the "sidecar state"),
        # re-derive by re-running bootstrap against the SAME root -- lands
        # on the identical spine every time.
        civ_a.unlink()
        check("civics.json actually deleted", not civ_a.exists())
        res_a2 = bootstrap_mod.bootstrap(BOOTSTRAP_TARGET, root=root_a, civ_path=civ_a)
        check("re-derive after deleting civics.json: identical civ",
              res_a2["civ"] == res_a["civ"])
        check("re-derive after deleting civics.json: identical docket",
              res_a2["dk"] == res_a["dk"])
    finally:
        shutil.rmtree(tmp_a, ignore_errors=True)
        shutil.rmtree(tmp_b, ignore_errors=True)

    # sim_day itself, called twice from identical inputs, mutates
    # identically (the narrower unit-level determinism claim).
    tmp_c, root_c, civ_c = _tmp_env()
    try:
        cal = cal_mod.build_calendar(GA, cal_mod.GA1_CONVENED)
        mem = members.mint_assembly(GA)
        dk1 = docket.empty_docket(GA)
        dk2 = docket.empty_docket(GA)
        civ1 = engine.default_civics(GA)
        civ2 = engine.default_civics(GA)
        for date in ("2026-01-12", "2026-01-13", "2026-01-14", "2026-01-19"):
            engine.sim_day(civ1, dk1, mem, cal, GA, date)
            engine.sim_day(civ2, dk2, mem, cal, GA, date)
        check("sim_day called twice on fresh identical inputs: civ matches",
              civ1 == civ2)
        check("sim_day called twice on fresh identical inputs: docket matches",
              dk1 == dk2)
    finally:
        shutil.rmtree(tmp_c, ignore_errors=True)


# =============================================================== section 4

def section_rollover_gate():
    """The air-gated GA-rollover phase machine: sim_day only ever SETS
    rolled_pending (at canvass); the actual transition refuses forever
    without an aired stamp, and executes cleanly once one appears --
    mirroring season._maybe_rollover exactly."""
    tmp, root, civ_path = _tmp_env()
    try:
        cal = cal_mod.build_calendar(GA, cal_mod.GA1_CONVENED)
        engine.save_side(f"calendar-ga{GA}.json", cal, root)
        mem = members.mint_assembly(GA)
        engine.save_side(f"members-ga{GA}.json", mem, root)
        dk = docket.empty_docket(GA)
        engine.save_side(f"docket-ga{GA}.json", dk, root)
        civ = engine.default_civics(GA)
        civ["sim_through"] = "2026-11-03"      # jump straight to election day
        civ["seats"] = members.seat_table(mem)
        engine.save_civics(civ, civ_path)

        res = engine.tick(GA, "2026-11-04", root=root, civ_path=civ_path)   # canvass
        check("rolled_pending set at canvass", res["civ"]["rolled_pending"] is True)
        check("ga unchanged right at canvass", res["civ"]["ga"] == GA)

        res = engine.tick(GA, "2026-11-20", root=root, civ_path=civ_path)   # 16 more days
        check("rollover REFUSES for 16 days with no aired stamp",
              res["civ"]["ga"] == GA and res["civ"]["rolled_pending"] is True)

        civ = res["civ"]
        civ.setdefault("aired", {})[f"ga{GA}:rollover"] = time.time() + 3600
        engine.save_civics(civ, civ_path)
        res = engine.tick(GA, "2026-11-21", root=root, civ_path=civ_path)
        check("rollover STILL refuses while the aired stamp is in the FUTURE",
              res["civ"]["ga"] == GA and res["civ"]["rolled_pending"] is True)

        civ = res["civ"]
        civ["aired"][f"ga{GA}:rollover"] = time.time() - 10
        engine.save_civics(civ, civ_path)
        res = engine.tick(GA, "2026-11-22", root=root, civ_path=civ_path)
        check("rollover EXECUTES once the aired stamp is in the past",
              res["civ"]["ga"] == GA + 1)
        check("rolled_pending cleared after rollover",
              res["civ"]["rolled_pending"] is False)
        check("new GA's calendar convened 2027-01-11 (2nd Monday of January)",
              res["cal"]["convened"] == "2027-01-11")
        check("new GA's members freshly minted (60 seats)",
              len(res["mem"]["members"]) == 60)
        check("new GA's docket is empty", res["dk"]["bills"] == {})
        # sim_through resets to "" the moment rollover executes -- GA 2
        # hasn't simmed a single day yet (it doesn't even convene until
        # 2027-01-11, an interim gap this simplified rollover doesn't
        # separately model -- mirrors season._maybe_rollover's own
        # `st["sim_through"] = ""` reset exactly).
        check("sim_through reset (empty) the moment rollover executes",
              res["civ"]["sim_through"] == "")

        # the day loop keeps ticking the NEW ga transparently afterward,
        # once its own convened date arrives
        res = engine.tick(GA + 1, "2027-01-15", root=root, civ_path=civ_path)
        check("day loop continues ticking the new GA after rollover",
              res["civ"]["sim_through"] == "2027-01-15" and res["civ"]["ga"] == GA + 1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# =============================================================== section 5

def section_catchup_chunking():
    """A single tick() pass never advances more than CHUNK_DAYS; repeated
    calls converge on the target (mirror §4 / league engine's pattern)."""
    tmp, root, civ_path = _tmp_env()
    try:
        cal = cal_mod.build_calendar(GA, cal_mod.GA1_CONVENED)
        engine.save_side(f"calendar-ga{GA}.json", cal, root)
        mem = members.mint_assembly(GA)
        engine.save_side(f"members-ga{GA}.json", mem, root)

        target = (_date.fromisoformat(cal_mod.GA1_CONVENED) +
                  timedelta(days=120)).isoformat()
        res = engine.tick(GA, target, root=root, civ_path=civ_path)
        expect_first = (_date.fromisoformat(cal_mod.GA1_CONVENED) +
                        timedelta(days=engine.CHUNK_DAYS - 1)).isoformat()
        check(f"first pass stops at CHUNK_DAYS ({engine.CHUNK_DAYS}), not target",
              res["civ"]["sim_through"] == expect_first,
              f"got {res['civ']['sim_through']}")

        passes = 1
        while res["civ"]["sim_through"] != target and passes < 10:
            res = engine.tick(GA, target, root=root, civ_path=civ_path)
            passes += 1
        check("repeated tick() calls converge on the target date",
              res["civ"]["sim_through"] == target)
        check("120-day catch-up took multiple chunked passes (not one shot)",
              passes >= 3, passes)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# =============================================================== section 6

def section_snow_quorum():
    """The weather input hook: snow days land in quorum_fails exactly on
    the dates the feed reports snow, never invented, never missed --
    default (no weather_fn) records no snow at all."""
    tmp, root, civ_path = _tmp_env()
    try:
        cal = cal_mod.build_calendar(GA, cal_mod.GA1_CONVENED)
        engine.save_side(f"calendar-ga{GA}.json", cal, root)
        mem = members.mint_assembly(GA)
        engine.save_side(f"members-ga{GA}.json", mem, root)

        snowy_dates = {"2026-01-14", "2026-01-17"}

        def weather_fn(date):
            return {"snowfall": 6.0} if date in snowy_dates else None

        res = engine.tick(GA, "2026-01-20", root=root, civ_path=civ_path,
                          weather_fn=weather_fn)
        check("snow days recorded exactly as the weather feed reported",
              set(res["civ"]["quorum_fails"]) == snowy_dates,
              res["civ"]["quorum_fails"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp2, root2, civ_path2 = _tmp_env()
    try:
        cal = cal_mod.build_calendar(GA, cal_mod.GA1_CONVENED)
        engine.save_side(f"calendar-ga{GA}.json", cal, root2)
        mem = members.mint_assembly(GA)
        engine.save_side(f"members-ga{GA}.json", mem, root2)
        res = engine.tick(GA, "2026-01-20", root=root2, civ_path=civ_path2)
        check("default weather_fn=None records zero snow days ('missing feed => holds')",
              res["civ"]["quorum_fails"] == [])
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)


# ------------------------------------------------------------------- main

def main():
    section_bootstrap_verify_green()
    section_gate_off_until_verify()
    section_self_healing()
    section_rollover_gate()
    section_catchup_chunking()
    section_snow_quorum()


if __name__ == "__main__":
    main()
    print(f"\nstatehouse engine {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
