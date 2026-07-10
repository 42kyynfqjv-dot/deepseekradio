#!/usr/bin/env python3
"""Seed data/league/records.json with the canon trophy name (owner-decided,
hockey-final.md "Trophy"): THE BOREAL LANTERN. Idempotent -- safe to re-run
any number of times; never overwrites existing per-season award data, only
ensures the `trophy` and `seasons` keys are present with the right shape.

Deliberately a separate tiny script rather than folding into
migrate_league_v2.py: records.json is season-independent (it survives every
season rollover, minimal §2), so seeding it has no business being coupled to
one season's player/schedule/stats migration.

Runnable from the repo root or from /opt/kaos/app (cwd-relative, exactly like
season.py's _PATH and engine.py's SIDE).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.league import engine  # noqa: E402

TROPHY = "The Boreal Lantern"


def seed() -> dict:
    rec = engine.load_side("records.json") or {}
    changed = False
    if rec.get("trophy") != TROPHY:
        rec["trophy"] = TROPHY
        changed = True
    if "seasons" not in rec or not isinstance(rec.get("seasons"), dict):
        rec["seasons"] = {}
        changed = True
    if changed:
        engine.save_side("records.json", rec)
    return rec


def main() -> int:
    rec = seed()
    print(f"records.json: trophy={rec['trophy']!r}, "
          f"{len(rec['seasons'])} season(s) on file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
