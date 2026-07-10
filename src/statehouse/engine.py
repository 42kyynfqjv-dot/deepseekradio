"""Statehouse integration spine — wires the seven finished leaf modules
(calendar, members, docket, votes, elections, sheets, civicguard) into a
persistent daily simulator. Mirrors `src/league/engine.py` component-for-
component (docs/designs/statehouse-final.md/-mirror.md, "the hockey engine's
verification harness ... is reused wholesale"): the gate (ENABLED + VERIFIED
hash over IMMUTABLE identity), atomic sidecar IO with `.bak`, a chunked day
loop, and an air-gated GA-rollover phase machine (the hockey rollover fix,
born air-gated here from day one, mirroring `season._maybe_rollover`).

NOTHING here touches live air: no orchestrator/show/performer wiring, no
gate flag creation — `scripts/verify_statehouse.py` is the sole writer of
VERIFIED (mirror G4), and even once armed the gate stays OFF: this module
never touches `data/statehouse/ENABLED`.

`civics.json` is the spine, repo-root, cwd-relative — season.json's sibling
(mirror §2/§9: "civics.json beside season.json"). Everything heavy lives in
per-General-Assembly sidecars under `data/statehouse/`.

FRICTION NOTES (scope decisions made building the facade the seven leaf
modules' own docstrings point at):
  1. `docket.floor_and_beyond_day` is explicitly a calibration stand-in
     ("explicitly a stand-in to be retired in favor of real
     votes.floor_result calls once the integration facade (civics.py) wires
     the two leaf modules together") and `votes.py`'s own docstring says a
     bill dict needs an explicit `bill_id` threaded in (the frozen schema
     never embeds a bill's own id in its per-bill dict). This module is that
     facade: `_floor_and_beyond_day` below reproduces docket's stand-in's
     STRUCTURE (the same stage-transition shape and the same timing
     constants for the steps no leaf module owns — calendaring cadence,
     conference/governor-action timing, none of which votes.py claims) but
     replaces every actual chamber vote (CALENDARED->PASSED_ORIGIN,
     IN_SECOND->REPORTED_2, and a veto-override attempt) with a real
     `votes.floor_result(bill_id, bill, members, ga, chamber=...)` call,
     passing the bill's own id explicitly per that module's contract.
  2. `approval.py` and `floor.py` are named in the design docs' module table
     but were never built as one of the seven finished leaf components (only
     calendar/civicguard/docket/elections/members/sheets/votes exist under
     `src/statehouse/`). Mirror §3's approval.py spec (mean-reverting to 46,
     seeded daily +/-0.8, event deltas, streak, clamp [25,71]) is fully
     specified prose, not a schema this module could get wrong — implemented
     directly here (`_approval_drift`/`_streak`), exactly as
     `src/league/engine.py` owns its own `_virtual_drop` helper rather than
     spinning up a one-function sibling module for it. `floor.py`'s
     `whip_count`/`floor_day`/`quorum` roles are covered by the real
     `votes.py` (whip_count/floor_result/quorum_ok) that already shipped
     under that name instead — nothing here reimplements them.
  3. Election-night generation/reveal (`elections.generate_cycle`/`reveal`)
     is deliberately NOT wired into the day loop. The design scopes Election
     Night as its own broadcast surface (mirror §6/§7 — booth/desk/site
     narration, sheets.election_sheet, the reveal cursor) explicitly
     downstream of "the future broadcast layer," and this task's own
     instruction is that the aired ledger stays untouched by this build.
     `sim_day` therefore only ever SETS `rolled_pending=True` at canvass
     (mirror §4.7's trigger) — mirroring `season.record_live`'s "trigger is
     set in record_live; execution lives [elsewhere]" split exactly.
     `_execute_rollover` is the gated executor: it refuses forever until an
     aired stamp appears at `civ["aired"][f"ga{ga}:rollover"]` in the past —
     a stamp nothing in this build (or the retro replay, which never reaches
     GA 1's 2026-11-03 election day) ever writes. The carryover wiring
     (`elections.seat_new_assembly` -> `members.mint_assembly(carryover=)`)
     is left as a documented seam (`civ["_rollover_carryover"]`) for the
     future broadcast layer to populate once it actually runs Election
     Night — this build guarantees the STRUCTURAL gate is correct and
     tested, not the show.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import time
from datetime import date as _date, timedelta
from pathlib import Path

from . import calendar as cal_mod
from . import docket
from . import members
from . import sheets
from . import votes

SIDE = Path("data/statehouse")
_CIV_PATH = Path("civics.json")
CHUNK_DAYS = 45          # catch-up bound per tick() pass (mirror §4 / league engine)

# Sidecars covered by the VERIFIED hash — the IMMUTABLE identity that must
# never drift between verification and the gate flip: the calendar
# (immutable once written, mirror §2) and the members identity table.
_CORE = ("calendar-ga{n}.json", "members-ga{n}.json")

DEFAULT_APPROVAL = 46.0
_APPROVAL_DAILY_SIGMA = 0.8
_APPROVAL_CLAMP = (25.0, 71.0)
_APPROVAL_REVERSION = 0.05           # fraction of the gap to 46 closed/day
_EVENT_DELTA = {
    "pothole_filled": 2.5, "pothole_discovered": -1.0,
    "quorum_fail": -1.5, "override": -4.0, "session_milestone": 2.0,
}
_P_POTHOLE_EVENT = 0.10

# Non-vote stage-transition timing (friction #1): docket.floor_and_beyond_day's
# own tuned constants for the steps no leaf module owns (calendaring cadence,
# conference/governor-action timing) — reused verbatim, since that stand-in is
# retired here only for the steps votes.py actually decides.
_P_CONFERENCE = 0.06
_P_2ND_CHAMBER_DAY = 0.4
_P_CONFERENCE_RESOLVE_DAY = 0.4
_P_GOVERNOR_ACTS_DAY = 0.6
_P_VETO = 0.04
_P_LAW_NO_SIG = 0.03
_P_OVERRIDE_ATTEMPT = 0.5


# =================================================================== sidecar IO

def _p(name: str, root: Path | None = None) -> Path:
    return (root or SIDE) / name


def load_side(name: str, root: Path | None = None) -> dict | None:
    """Sidecar read, the established trust rule: live file, then `.bak`."""
    for p in (_p(name, root), _p(name, root).with_suffix(".bak")):
        try:
            if p.exists():
                return json.loads(p.read_text())
        except Exception:
            continue
    return None


def save_side(name: str, obj: dict, root: Path | None = None) -> None:
    """Atomic tmp+replace with a `.bak` copy — the established `_save`
    pattern (`src/league/engine.py`/`src/season.py`)."""
    p = _p(name, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(obj))
    if p.exists():
        try:
            shutil.copy2(p, p.with_suffix(".bak"))
        except Exception:
            pass
    tmp.replace(p)


# =================================================================== civics.json

def default_civics(ga: int = 1) -> dict:
    """A fresh `civics.json` spine (mirror §2 schema)."""
    return {
        "ga": ga, "session": "regular-extended", "sim_through": "",
        "phase": "session",
        "seats": {"house": dict(members.DEFAULT_SEATS["house"]),
                   "senate": dict(members.DEFAULT_SEATS["senate"])},
        "approval": {"gov": DEFAULT_APPROVAL, "streak": 0, "series": {}},
        "tracked": {"kind": "bill", "id": None, "since": None,
                    "beat": None, "resolved": None},
        "quorum_fails": [],
        "aired": {},
        "last_line": "",
        "rolled_pending": False,
    }


def load_civics(path: Path | None = None) -> dict:
    """`civics.json` read, season.json's own trust rule: live file, then
    `.bak`, else a fresh default (NEVER silently resets a live spine just
    because a reader caught a write window)."""
    p = path or _CIV_PATH
    for cand in (p, p.with_suffix(".bak")):
        try:
            if cand.exists():
                civ = json.loads(cand.read_text())
                if "ga" in civ:
                    return civ
        except Exception:
            continue
    return default_civics()


def save_civics(civ: dict, path: Path | None = None) -> None:
    """Atomic tmp+replace with `.bak` — identical discipline to
    `season._save` (the scorebug/site publisher reads this from another
    process; it must never see a missing file)."""
    p = path or _CIV_PATH
    tmp = p.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(civ, indent=2))
    if p.exists():
        try:
            shutil.copy2(p, p.with_suffix(".bak"))
        except Exception:
            pass
    tmp.replace(p)


# =================================================================== the gate

def sidecar_hash(ga: int, root: Path | None = None) -> str:
    """Hash over the IMMUTABLE core: the calendar bytes (immutable once
    written, mirror §2) and the members identity table — every field
    EXCEPT `aired` (the one runtime-mutable per-member flag, toggled by a
    future broadcast layer once a member's name airs) — mirrors
    `league.engine.sidecar_hash`'s own exclusion of runtime-mutable state
    (out2/callups) from the gate."""
    h = hashlib.sha256()
    p = _p(f"calendar-ga{ga}.json", root)
    h.update(p.read_bytes() if p.exists() else b"missing")
    mem = load_side(f"members-ga{ga}.json", root)
    ident = sorted(
        (sid, m.get("name", ""), m.get("chamber", ""), m.get("district", 0),
         m.get("party", ""), str(m.get("zipper")), m.get("maverick", 0.0),
         m.get("discipline", 0.0), m.get("attend", 0.0), m.get("tenure", 0))
        for sid, m in (mem or {}).get("members", {}).items()
    )
    h.update(json.dumps(ident).encode())
    return h.hexdigest()


def statehouse_on(ga: int, root: Path | None = None) -> bool:
    """ENABLED + VERIFIED + hash match + core sidecars parse. Any miss is a
    loud no — the caller keeps pure-canon color with zero numbers (mirror
    §9.7 fallback: `rm ENABLED` reverts forever, sidecars stay warm)."""
    root = root or SIDE
    if not (root / "ENABLED").exists():
        return False
    ver = root / "VERIFIED"
    if not ver.exists():
        print("  !! statehouse: ENABLED but not VERIFIED — staying off")
        return False
    try:
        if ver.read_text().strip() != sidecar_hash(ga, root):
            print("  !! statehouse: sidecar hash drift since verify — staying off")
            return False
    except Exception as e:
        print(f"  !! statehouse gate check failed ({e}) — staying off")
        return False
    for tpl in _CORE:
        if load_side(tpl.format(n=ga), root) is None:
            print(f"  !! statehouse: {tpl.format(n=ga)} unreadable — staying off")
            return False
    return True


def arm(ga: int, root: Path | None = None) -> None:
    """Write VERIFIED for the current sidecar state. ONLY
    scripts/verify_statehouse.py calls this, and only after every check
    passes (mirror G4) — a human can't skip it at 2am."""
    root = root or SIDE
    (root / "VERIFIED").write_text(sidecar_hash(ga, root))


# =================================================================== approval

def _streak(series: dict) -> int:
    """Consecutive same-direction days at the tail of `series` (date ->
    value), as an unsigned magnitude — mirror §2's own worked example
    (`"streak": 3`, no sign) and `sheets.py`'s `"{streak}-day streak"`
    rendering both read it unsigned."""
    dates = sorted(series)
    if len(dates) < 2:
        return 0
    vals = [series[d] for d in dates]
    diffs = [vals[i] - vals[i - 1] for i in range(1, len(vals))]
    n, direction = 0, None
    for d in reversed(diffs):
        if d == 0:
            break
        sign = d > 0
        if direction is None:
            direction = sign
        if sign != direction:
            break
        n += 1
    return n


def _approval_drift(civ: dict, ga: int, date: str, events: list) -> None:
    """Mean-reverting to 46, seeded daily +/-0.8, event deltas, clamp
    [25,71] (mirror §3's approval.py spec, implemented here per friction
    note #2). Mutates `civ["approval"]` in place; prunes `series` to the
    trailing 30 days (mirror §2)."""
    approval = civ.setdefault("approval",
                               {"gov": DEFAULT_APPROVAL, "streak": 0, "series": {}})
    prev = approval.get("gov", DEFAULT_APPROVAL)
    rng = random.Random(f"approval:{ga}:{date}")
    delta = (DEFAULT_APPROVAL - prev) * _APPROVAL_REVERSION + \
        rng.gauss(0, _APPROVAL_DAILY_SIGMA)
    for ev in events:
        delta += _EVENT_DELTA.get(ev, 0.0)
    new = round(max(_APPROVAL_CLAMP[0], min(_APPROVAL_CLAMP[1], prev + delta)), 2)
    series = approval.setdefault("series", {})
    series[date] = new
    if len(series) > 30:
        for old in sorted(series)[:-30]:
            del series[old]
    approval["gov"] = new
    approval["streak"] = _streak(series)


def _pothole_event(ga: int, date: str) -> str | None:
    rng = random.Random(f"pothole:{ga}:{date}")
    if rng.random() >= _P_POTHOLE_EVENT:
        return None
    return "pothole_filled" if rng.random() < 0.6 else "pothole_discovered"


# =================================================================== floor+beyond

def _floor_and_beyond_day(dk: dict, mem: dict, ga: int, date: str,
                           floor_open: bool) -> list:
    """CALENDARED..governor-action lifecycle (friction note #1): the same
    stage-transition SHAPE as `docket.floor_and_beyond_day`'s calibration
    stand-in, but every actual chamber vote calls the real
    `votes.floor_result` — this IS the integration that stand-in's own
    docstring says should retire it. `floor_open=False` (non-floor day,
    snow) withholds floor-VOTE resolution only; conference/governor action
    are not floor votes and keep running regardless (docket's own rule)."""
    events = []
    members_map = (mem or {}).get("members", {})
    for bid in sorted(dk["bills"]):
        bill = dk["bills"][bid]
        stage = bill["stage"]
        if docket.is_terminal(stage) or stage in ("INTRODUCED", "IN_COMMITTEE"):
            continue
        rng = random.Random(f"engine:{ga}:{bid}:{date}")
        origin = votes.chamber_of(bill)
        second = "senate" if origin == "house" else "house"
        changed = False

        if stage == "REPORTED" and floor_open:
            bill["stage"] = "CALENDARED"
            bill["history"].append([date, "CALENDARED"])
            changed = True

        elif stage == "CALENDARED" and floor_open:
            fr = votes.floor_result(bid, bill, members_map, ga, chamber=origin)
            if fr["passed"]:
                bill["stage"] = "PASSED_ORIGIN"
                bill["history"].append([date, "PASSED_ORIGIN", [fr["yea"], fr["nay"]]])
            else:
                bill["stage"] = "FAILED_FLOOR"
                bill["history"].append([date, "FAILED_FLOOR", [fr["yea"], fr["nay"]]])
            changed = True

        elif stage == "PASSED_ORIGIN":
            bill["stage"] = "IN_SECOND"
            bill["history"].append([date, "CROSSED"])
            changed = True

        elif stage == "IN_SECOND" and floor_open and rng.random() < _P_2ND_CHAMBER_DAY:
            fr = votes.floor_result(bid, bill, members_map, ga, chamber=second)
            if fr["passed"]:
                bill["stage"] = "REPORTED_2"
                bill["history"].append([date, "REPORTED_2", [fr["yea"], fr["nay"]]])
            else:
                bill["stage"] = "FAILED_FLOOR"
                bill["history"].append([date, "FAILED_FLOOR", [fr["yea"], fr["nay"]]])
            changed = True

        elif stage == "REPORTED_2" and floor_open:
            if rng.random() < _P_CONFERENCE:
                bill["stage"] = "CONFERENCE"
                bill["history"].append([date, "CONFERENCE"])
            else:
                bill["stage"] = "PASSED_BOTH"
                bill["history"].append([date, "PASSED_BOTH"])
            changed = True

        elif stage == "CONFERENCE" and rng.random() < _P_CONFERENCE_RESOLVE_DAY:
            bill["stage"] = "PASSED_BOTH"
            bill["history"].append([date, "PASSED_BOTH"])
            changed = True

        elif stage == "PASSED_BOTH":
            bill["stage"] = "ENROLLED"
            bill["history"].append([date, "ENROLLED"])
            changed = True

        elif stage == "ENROLLED" and rng.random() < _P_GOVERNOR_ACTS_DAY:
            roll = rng.random()
            if roll < _P_VETO:
                bill["history"].append([date, "VETOED"])
                bill["stage"] = "VETOED"
                if rng.random() < _P_OVERRIDE_ATTEMPT:
                    ov_bill = dict(bill, **{"class": "override"})
                    ov_id = f"{bid}:override"
                    fr_o = votes.floor_result(ov_id, ov_bill, members_map, ga,
                                               chamber=origin)
                    fr_s = votes.floor_result(ov_id, ov_bill, members_map, ga,
                                               chamber=second)
                    if fr_o["passed"] and fr_s["passed"]:
                        bill["stage"] = "OVERRIDDEN"
                        bill["history"].append(
                            [date, "OVERRIDDEN",
                             [fr_o["yea"], fr_o["nay"]], [fr_s["yea"], fr_s["nay"]]])
            elif roll < _P_VETO + _P_LAW_NO_SIG:
                bill["stage"] = "LAW_NO_SIG"
                bill["history"].append([date, "LAW_NO_SIG"])
            else:
                bill["stage"] = "SIGNED"
                bill["history"].append([date, "SIGNED"])
            changed = True

        if changed:
            events.append(bill)
    return events


# =================================================================== the tracked pointer

def _advance_tracked(civ: dict, dk: dict, ga: int, date: str) -> None:
    """The one-thread rule (mirror §4.6/§7): at most one decisive TRACKED
    event per day. If today's history entry resolved the tracked bill,
    mark `tracked.resolved` (and stop — no promotion the same day, so a
    resolution and a fresh promotion never both land on one date).
    Otherwise, promote the highest-marquee unresolved bill via
    `docket.pick_tracked` when there is no live tracked thread."""
    tracked = civ.setdefault("tracked", {"kind": "bill", "id": None,
                                          "since": None, "beat": None,
                                          "resolved": None})
    if tracked.get("kind") != "bill":
        return
    tid = tracked.get("id")
    if tid and not tracked.get("resolved"):
        tb = dk["bills"].get(tid)
        if tb and docket.is_terminal(tb["stage"]) and tb["history"] and \
                tb["history"][-1][0] == date:
            tracked["resolved"] = date
            return
    if (not tid or tracked.get("resolved")) and tracked.get("resolved") != date:
        new_id = docket.pick_tracked(dk, ga, date)
        if new_id and new_id != tid:
            civ["tracked"] = {"kind": "bill", "id": new_id, "since": date,
                               "beat": "committee", "resolved": None}


# =================================================================== sim_day

def sim_day(civ: dict, dk: dict, mem: dict, cal: dict, ga: int, date: str,
            weather_fn=None) -> list:
    """One calendar day's worth of statehouse simulation (mirror §4),
    mutating `civ`/`dk` in place (`mem`/`cal` are read-only here — members
    never drift day to day, "derive, don't store"). Returns the list of
    docket bills touched today (never written anywhere itself — the aired
    ledger is untouched by this function, per this task's own instruction;
    that stamping is the future broadcast layer's job).

    Pure given its five inputs: every seed is `(ga, id, date)` — never
    wall-clock, never civ-state — so replaying the same day against the
    same sidecars always produces the same mutations (self-healing: a lost
    civics.json is recoverable by re-deriving from scratch against the same
    seeds, never by partial replay against already-mutated sidecars).
    """
    weather = weather_fn(date) if weather_fn else None
    civ["quorum_fails"] = cal_mod.record_snow_day(
        civ.get("quorum_fails", []), date, weather)
    snowed = date in civ["quorum_fails"]

    day_kind = cal_mod.day_kind(cal, date)
    civ["phase"] = cal_mod.phase(cal, date)

    docket.introduce_day(dk, mem, cal, ga, date)
    docket.committee_day(dk, mem, cal, ga, date, snowed=snowed)

    floor_open = (day_kind == "floor") and not snowed
    touched = _floor_and_beyond_day(dk, mem, ga, date, floor_open)

    _advance_tracked(civ, dk, ga, date)

    approval_events = []
    pev = _pothole_event(ga, date)
    if pev:
        approval_events.append(pev)
    if snowed and day_kind == "floor":
        approval_events.append("quorum_fail")
    for bill in touched:
        if bill["history"] and bill["history"][-1][0] == date and \
                bill["history"][-1][1] == "OVERRIDDEN":
            approval_events.append("override")
    for sess in cal.get("sessions", []):
        if sess.get("start", "9999") > date:
            continue
        if date == sess.get("crossover"):
            approval_events.append("session_milestone")
        if date == sess.get("sine_die") and not sess.get("sine_die_pending"):
            approval_events.append("session_milestone")
    _approval_drift(civ, ga, date, approval_events)

    recap_text, _event_ids = sheets.gavel_recap(civ, dk, date)
    first_line = recap_text.splitlines()[0] if recap_text else ""
    if first_line and not first_line.startswith(("No decisive Dome action",
                                                   "APPROVAL:")):
        civ["last_line"] = first_line

    if day_kind == "canvass" and not civ.get("rolled_pending"):
        civ["rolled_pending"] = True

    return touched


# =================================================================== rollover

def _next_convened(prev_year: int) -> str:
    """2nd Monday of January (odd year -> Regular) or February (even year
    -> Budget), the real small-state rhythm (mirror §5) — GA 2 onward
    (GA 1 itself is the bootstrap exception, never derived this way)."""
    year = prev_year + 1
    month = 1 if year % 2 == 1 else 2
    d = _date(year, month, 1)
    first_monday = d + timedelta(days=(0 - d.weekday()) % 7)
    return (first_monday + timedelta(days=7)).isoformat()


def _execute_rollover(civ: dict, ga: int, root: Path | None):
    """Mirror `season._maybe_rollover`: execute a pending GA transition
    ONLY once a rollover-gating event has an aired stamp in the past
    (friction note #3 — nothing in this build ever writes that stamp, so
    this refuses forever absent an external broadcast layer). Returns
    `(executed: bool, new_ga: int)`."""
    if not civ.get("rolled_pending"):
        return False, ga
    at = civ.get("aired", {}).get(f"ga{ga}:rollover")
    if at is None or time.time() < at:
        return False, ga

    root = root or SIDE
    prev_cal = load_side(f"calendar-ga{ga}.json", root) or {}
    prev_convened = prev_cal.get("convened") or civ.get("sim_through") or \
        _date.today().isoformat()
    next_convened = _next_convened(_date.fromisoformat(prev_convened).year)
    new_ga = ga + 1

    new_cal = cal_mod.build_calendar(new_ga, next_convened)
    new_mem = members.mint_assembly(new_ga, carryover=civ.get("_rollover_carryover") or {})
    new_dk = docket.empty_docket(new_ga)

    save_side(f"calendar-ga{new_ga}.json", new_cal, root)
    save_side(f"members-ga{new_ga}.json", new_mem, root)
    save_side(f"docket-ga{new_ga}.json", new_dk, root)

    civ["ga"] = new_ga
    civ["session"] = new_cal["sessions"][0]["kind"]
    civ["sim_through"] = ""
    civ["phase"] = "session"
    civ["seats"] = members.seat_table(new_mem)
    civ["tracked"] = {"kind": "bill", "id": None, "since": None,
                       "beat": None, "resolved": None}
    civ["quorum_fails"] = []
    civ["rolled_pending"] = False
    civ.pop("_rollover_carryover", None)
    civ["last_line"] = f"General Assembly {new_ga} convened {next_convened}."
    print(f"  statehouse rollover -> GA {new_ga} (air-gated)")
    return True, new_ga


# =================================================================== the day loop

def tick(ga: int, target_date: str, weather_fn=None, root: Path | None = None,
         civ_path: Path | None = None) -> dict:
    """Advance civics.json + the current GA's sidecars to `target_date`,
    CHUNK_DAYS per call (mirror §4 / `league.engine.tick_v2`'s pattern).
    Loads sidecars once, saves dirty state atomically at the end.
    `weather_fn(date) -> dict|None` is the snow-quorum input hook (default
    None — no snow, ever; "missing feed => quorum holds", mirror §4.2/risk
    #4). A rollover mid-pass can change `civ["ga"]`; the loop re-reads it
    every iteration so it always ticks the CURRENT Assembly. Returns the
    loaded bundle `{"civ","dk","mem","cal"}` after the pass."""
    root = root or SIDE
    civ = load_civics(civ_path)
    cur_ga = civ.get("ga", ga)
    cal = load_side(f"calendar-ga{cur_ga}.json", root)
    if cal is None:
        cal = cal_mod.build_calendar(cur_ga, civ.get("sim_through") or target_date)
        save_side(f"calendar-ga{cur_ga}.json", cal, root)
    dk = load_side(f"docket-ga{cur_ga}.json", root)
    if dk is None:
        dk = docket.empty_docket(cur_ga)
    mem = load_side(f"members-ga{cur_ga}.json", root)
    if mem is None:
        mem = members.mint_assembly(cur_ga)
        save_side(f"members-ga{cur_ga}.json", mem, root)
    civ["seats"] = members.seat_table(mem)

    start = civ.get("sim_through") or cal["convened"]
    d0, d1 = _date.fromisoformat(start), _date.fromisoformat(target_date)
    if civ.get("sim_through"):
        d0 += timedelta(days=1)
    if d0 > d1:
        save_civics(civ, civ_path)
        return {"civ": civ, "dk": dk, "mem": mem, "cal": cal}

    d, days_done = d0, 0
    while d <= d1 and days_done < CHUNK_DAYS:
        date = d.isoformat()
        sim_day(civ, dk, mem, cal, cur_ga, date, weather_fn)
        civ["sim_through"] = date
        days_done += 1
        if civ.get("rolled_pending"):
            rolled, new_ga = _execute_rollover(civ, cur_ga, root)
            if rolled:
                save_side(f"docket-ga{cur_ga}.json", dk, root)
                cur_ga = new_ga
                cal = load_side(f"calendar-ga{cur_ga}.json", root)
                dk = load_side(f"docket-ga{cur_ga}.json", root)
                mem = load_side(f"members-ga{cur_ga}.json", root)
        d += timedelta(days=1)

    save_side(f"docket-ga{cur_ga}.json", dk, root)
    civ["ga"] = cur_ga
    save_civics(civ, civ_path)
    return {"civ": civ, "dk": dk, "mem": mem, "cal": cal}
