#!/usr/bin/env python3
"""Bootstrap the Wending Statehouse from government.html/wending-bible.md
canon (statehouse-mirror.md §9, deltas in statehouse-final.md), gate OFF the
whole time: this script NEVER touches `data/statehouse/ENABLED` or
`VERIFIED` — `scripts/verify_statehouse.py` is the sole armer.

Idempotent: every run mints GA 1 from scratch (calendar -> members -> an
empty docket -> a fresh civics.json spine) and replays `engine.tick()`
day-by-day up to TODAY — the exact same deterministic derivation
`migrate_league_v2.py` uses ("re-running overwrites the sidecars with the
same deterministic derivation"). Every seed downstream of the mint is
`(ga, id, date)` only, so two runs on the same calendar day produce
byte-identical sidecars; a run on a LATER day just replays a few more days,
same as it always would. The retro fill is free (mirror §9.4): nothing has
aired yet, so nothing here is spoiler-gated and nothing can contradict air.

Writes `data/statehouse/canon-diff.txt` — a from-scratch, honest divergence
report (G6 mirror) against `government.html`/`wending-bible.md` canon: the
51/9 seat split, the closed seven-party roster, the four pinned officials
("nine good chairs and a tenth no one trusts"), and GA 1's sine-die
resolution permanently pending in the Committee on Merging. Cutover (via
verify_statehouse.py) requires this file EMPTY; this script reports whatever
the mint actually produced, it does not force it empty.

Friction note: the task's own bootstrap instruction seeds civics.json's
approval "in the 50s" — mirror §2's own worked JSON example shows 46.2, a
different number for a different purpose (a mid-session snapshot, not a
bootstrap seed). Conformed to the task's literal instruction (`SEED_APPROVAL
= 52.0`); `_approval_drift`'s mean-reversion (`engine.py`, target 46) pulls
it toward the mirror's steady-state band over the retro replay regardless of
which of the two numbers seeds day zero.

Runnable from the repo root or from /opt/kaos/app — every path here is
cwd-relative, exactly like season.py's `_PATH` and league engine.py's `SIDE`.
"""
from __future__ import annotations

import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.statehouse import calendar as cal_mod   # noqa: E402
from src.statehouse import docket                # noqa: E402
from src.statehouse import engine                # noqa: E402
from src.statehouse import members               # noqa: E402

DEFAULT_GA = 1
SEED_APPROVAL = 52.0    # "the 50s" (task's explicit bootstrap seed, see friction note)
_MAX_PASSES = 30        # ~180 days / CHUNK_DAYS(45) rounds up to 4 -- generous headroom


# ------------------------------------------------------------- canon-diff

def compute_canon_diff(mem: dict, cal: dict) -> list[str]:
    """A from-scratch, honest divergence report (G6 mirror) against every
    government.html / wending-bible.md fact the design calls out: seat
    sums, the closed seven-party roster, the four pinned officials, and
    GA 1's sine-die-pending-in-Merging bootstrap exception. NOT guaranteed
    empty by construction -- verify_statehouse.py re-derives this
    independently and gates VERIFIED on it."""
    diffs: list[str] = []
    agg = members.seat_table(mem)
    house, senate = agg.get("house", {}), agg.get("senate", {})

    # government.html: "HOUSE OF DELEGATES: 51 SEATS · SENATE: 9 GOOD
    # CHAIRS AND A TENTH NO ONE TRUSTS" (wending-bible.md line 53-54)
    if sum(house.values()) != 51:
        diffs.append(f"house seat sum != 51: got {sum(house.values())}")
    if sum(senate.values()) != 9:
        diffs.append(f"senate seat sum != 9: got {sum(senate.values())}")
    if "oic" in house or "oic" in senate:
        diffs.append("OIC holds a seat -- canon: seatless, fields no candidates")

    # the closed seven parties (government.html "The Ballot"; wending-bible.md
    # "the political axis and the parties", items 1-7)
    want_parties = {"prov", "round", "vang", "barb", "grudge", "goose", "oic"}
    got_parties = set(members.PARTY_NAMES.keys())
    if got_parties != want_parties:
        diffs.append(f"party roster != canon 7: got {sorted(got_parties)}")
    seat_holding = set(house) | set(senate)
    if seat_holding != (want_parties - {"oic"}):
        diffs.append(f"seat-holding parties != canon 6: got {sorted(seat_holding)}")

    # the four pinned officials (government.html "Recurring Officials";
    # wending-bible.md "the government")
    want_officials = {
        "governor": "Marty Bouchard", "clerk": "Gord Pelletier",
        "potholes": "Bert Demers", "roundabout": "Toivo Ostberg",
    }
    officials = mem.get("officials", {})
    for key, name in want_officials.items():
        o = officials.get(key)
        if not o or o.get("name") != name or not o.get("canon"):
            diffs.append(f"official {key!r} not pinned to canon {name!r}: got {o}")

    # "nine good chairs and a tenth no one trusts"
    tenth = officials.get("tenth_chair")
    if not tenth or tenth.get("name") is not None or tenth.get("trusted") is not False:
        diffs.append(f"tenth_chair not canon-shaped (name=None, trusted=False): got {tenth}")

    # GA 1's sine-die resolution permanently pending in the Committee on
    # Merging (wending-bible.md: "The Committee on Merging is still
    # merging. Referral there is where questions go to live forever.")
    sessions = cal.get("sessions", [])
    if not sessions or not sessions[0].get("sine_die_pending"):
        diffs.append("GA 1 session is not sine-die-pending (Merging must hold the resolution)")
    note = (sessions[0].get("note") or "") if sessions else ""
    if "Merging" not in note:
        diffs.append(f"GA 1 session note doesn't cite the Committee on Merging: {note!r}")
    if cal.get("convened") != cal_mod.GA1_CONVENED:
        diffs.append(f"GA 1 convened != {cal_mod.GA1_CONVENED}: got {cal.get('convened')}")

    return diffs


# ------------------------------------------------------------------- main

def bootstrap(target_date: str | None = None, root: Path | None = None,
              civ_path: Path | None = None) -> dict:
    """Mint GA 1 from scratch and replay to `target_date` (default: today).
    Returns a result dict (never raises on a normal run; genuine bugs still
    raise)."""
    root = root or engine.SIDE
    target = target_date or _date.today().isoformat()

    cal = cal_mod.build_calendar(DEFAULT_GA, cal_mod.GA1_CONVENED)
    engine.save_side(f"calendar-ga{DEFAULT_GA}.json", cal, root)

    mem = members.mint_assembly(DEFAULT_GA)
    engine.save_side(f"members-ga{DEFAULT_GA}.json", mem, root)

    dk = docket.empty_docket(DEFAULT_GA)
    engine.save_side(f"docket-ga{DEFAULT_GA}.json", dk, root)

    civ = engine.default_civics(DEFAULT_GA)
    civ["approval"]["gov"] = SEED_APPROVAL
    civ["seats"] = members.seat_table(mem)
    engine.save_civics(civ, civ_path)

    result = {"civ": civ, "dk": dk, "mem": mem, "cal": cal}
    passes = 0
    while result["civ"]["sim_through"] != target and passes < _MAX_PASSES:
        result = engine.tick(DEFAULT_GA, target, root=root, civ_path=civ_path)
        passes += 1

    civ, dk, mem, cal = result["civ"], result["dk"], result["mem"], result["cal"]

    diffs = compute_canon_diff(mem, cal)
    diff_path = root / "canon-diff.txt"
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.write_text("\n".join(diffs) + ("\n" if diffs else ""))

    stage_counts: dict = {}
    for b in dk["bills"].values():
        stage_counts[b["stage"]] = stage_counts.get(b["stage"], 0) + 1

    return {
        "ok": not diffs and result["civ"]["sim_through"] == target,
        "ga": civ["ga"], "target": target, "passes": passes,
        "reached_target": result["civ"]["sim_through"] == target,
        "bills_total": len(dk["bills"]), "stage_counts": stage_counts,
        "tracked": civ.get("tracked"),
        "approval": civ.get("approval", {}).get("gov"),
        "streak": civ.get("approval", {}).get("streak"),
        "canon_diff": diffs, "canon_diff_path": str(diff_path),
        "civ": civ, "dk": dk, "mem": mem, "cal": cal,
    }


def _print_summary(res: dict) -> None:
    print(f"bootstrap_statehouse: GA {res['ga']} -> {res['target']} "
          f"({res['passes']} tick pass(es), reached target: {res['reached_target']})")
    print(f"  members minted:      60 (51 House + 9 Senate)")
    print(f"  bills in docket:     {res['bills_total']}")
    stages = ", ".join(f"{k}={v}" for k, v in sorted(res["stage_counts"].items()))
    print(f"  stage breakdown:     {stages or '(empty)'}")
    print(f"  approval:            {res['approval']}, {res['streak']}-day streak")
    print(f"  tracked:             {res['tracked']}")
    print(f"  canon-diff -> {res['canon_diff_path']} "
          f"({len(res['canon_diff'])} divergence(s))")
    if res["canon_diff"]:
        for line in res["canon_diff"]:
            print(f"    !! {line}")
    else:
        print("    (empty — clean bootstrap)")


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default=None,
                     help="replay through this date (default: today)")
    args = ap.parse_args(argv)
    res = bootstrap(args.target)
    _print_summary(res)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
