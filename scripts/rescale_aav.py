#!/usr/bin/env python3
"""Rescale an ALREADY-MINTED players-s{n}.json's contracts onto the
calibrated payroll band (the Gate-2 aav<->cap fix for live state that was
minted under the old, uncalibrated formula -- see the contract-calibration
block in src/league/players.py; freshly minted leagues land in band by
construction and this script then no-ops on them).

Per team: seeded target payroll = Random(f"aav-rescale:{season}:{team}")
.uniform(*players.PAYROLL_BAND); every one of the team's aav values (actives
AND reserves -- the whole sheet stays proportional) scales by one factor
solved on the ACTIVE payroll (the number the cap actually measures), rounded
to 0.1M, floored at the $0.775M league minimum. Nothing but `aav` is
touched: name/team/slot/ov/... are identity fields other systems (and
engine.sidecar_hash's VERIFIED gate) depend on -- the script recomputes the
hash before and after and refuses to save if it moved.

Idempotent: a team already within TOLERANCE of its seeded target is skipped
untouched, so a second run finds every team in tolerance (the first run's
rounding lands well inside it) and rewrites nothing.

Runnable from the repo root or from /opt/kaos/app (cwd-relative paths,
exactly like season.py's _PATH and engine.py's SIDE).
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.league import economy, engine, players  # noqa: E402

TOLERANCE = 1.5   # $M; 20 actives x 0.05 max rounding drift = 1.0, plus slack


def rescale(season_n: int) -> dict:
    name = f"players-s{season_n}.json"
    pl = engine.load_side(name)
    if pl is None:
        return {"skipped": f"no {name} to rescale"}

    hash_before = engine.sidecar_hash(season_n)
    teams = sorted({p["team"] for p in pl["players"].values()})
    rows, changed = [], 0
    for team in teams:
        target = random.Random(
            f"aav-rescale:{season_n}:{team}").uniform(*players.PAYROLL_BAND)
        before = economy.payroll(pl, team)
        if abs(before - target) <= TOLERANCE:
            rows.append((team, before, before, target, False))
            continue
        k = target / before if before else 1.0
        for p in pl["players"].values():
            if p["team"] == team:
                p["aav"] = max(players.AAV_MIN, round(p["aav"] * k, 1))
        after = economy.payroll(pl, team)
        rows.append((team, before, after, target, True))
        changed += 1

    if changed:
        engine.save_side(name, pl)
    hash_after = engine.sidecar_hash(season_n)
    if hash_after != hash_before:
        # identity fields are untouched by construction (only `aav` is
        # written, and aav is not part of sidecar_hash's identity tuple);
        # if this ever fires, something else moved and the VERIFIED gate
        # would shut on the next v2_on() check — restore from .bak.
        raise RuntimeError(
            f"sidecar_hash moved across rescale ({hash_before[:12]} -> "
            f"{hash_after[:12]}) — identity fields were touched; the .bak "
            f"written by save_side holds the pre-rescale state")

    return {"skipped": None, "season": season_n, "rows": rows,
            "changed": changed, "hash_before": hash_before,
            "hash_after": hash_after}


def _print_summary(res: dict) -> None:
    if res.get("skipped"):
        print(f"rescale_aav: {res['skipped']} — nothing to do, exiting 0")
        return
    print(f"rescale_aav: season {res['season']} — "
          f"{res['changed']}/{len(res['rows'])} team(s) rescaled")
    print("  team   before    after   target")
    for team, before, after, target, did in res["rows"]:
        mark = "" if did else "  (in tolerance, untouched)"
        print(f"  {team:<6} {before:7.2f}  {after:7.2f}  {target:7.2f}{mark}")
    ok = economy_all_ok(res)
    print(f"  cap_ok all teams: {'yes' if ok else 'NO'}")
    print(f"  sidecar_hash before: {res['hash_before']}")
    print(f"  sidecar_hash after:  {res['hash_after']}"
          f"  ({'unchanged — VERIFIED gate holds' if res['hash_after'] == res['hash_before'] else 'MOVED'})")


def economy_all_ok(res: dict) -> bool:
    pl = engine.load_side(f"players-s{res['season']}.json")
    if pl is None:
        return False
    teams = sorted({p["team"] for p in pl["players"].values()})
    return all(economy.cap_ok(pl, t) for t in teams)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=1)
    args = ap.parse_args(argv)
    res = rescale(args.season)
    _print_summary(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
