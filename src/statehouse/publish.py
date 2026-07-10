"""Statehouse website export — `.../statehouse.json`, the `season.export()`
mirror (mirror-doc §7's "Website statehouse page", scoped to the fields this
landing task calls for). Air-gated by construction: `engine.statehouse_on`
is the ONE switch — off, this writes nothing at all (not even an empty
shell), so a page that already shows pure-canon color from a prior gate-off
run stays byte-identical (mirror §9.7's "shows revert to canon color with no
numbers" applies to the site too, not only the on-air shows).

**Scope note (why no per-field aired-ledger gating here):** mirror §7 asks
export() to reveal "tracked bill status as of its LAST AIRED event" — the
scorebug precedent (`season.export`'s `broadcast` dict, gated chunk-by-chunk
on `narrated_air`). But `season.export` draws that same distinction at a
coarser grain too: the STANDINGS table (`_display_league`) is never gated at
all — only the single most-recent-game's own blow-by-blow is. This module
follows the standings precedent, not the scorebug one: everything here
(approval/streak, session phase/day, the tracked bill's CURRENT public-record
stage + title, the election countdown, the quorum-fails count) is
"standings-shaped" — always-current status, exactly what `session_brief`
already speaks freely with no aired check of its own. What this module
NEVER does is publish `gavel_recap`-shaped content: no stored tallies, no
docket `history` arrays, no per-event narrative text, no aired-ledger event
ids. That is the one-thread/no-spoiler line this build actually needs to
hold, and it holds it by simply never reading `gavel_recap` or `dk[...]
["history"]` here at all — nothing to gate because nothing narrative is ever
in scope. A future broadcast layer that adds the on-air `gavel_recap` segment
(and its `record_aired` stamping, per `sheets.gavel_recap`'s own docstring)
can tighten the tracked-bill field to the full mirror §7 aired-gated shape
without changing this module's contract.
"""
from __future__ import annotations

import json
import os
from datetime import date as _date
from pathlib import Path

from . import engine, sheets

# First General Assembly takeover (mirror §6/§9); overridden by the live
# calendar sidecar's own `election.date` when one is on disk.
FALLBACK_ELECTION_DATE = "2026-11-03"


def _days_to(today: str, election_date: str) -> int | None:
    try:
        return (_date.fromisoformat(election_date) - _date.fromisoformat(today)).days
    except Exception:
        return None


def export(path: str = "/var/www/bestairadio/data/statehouse.json") -> None:
    """Publish the statehouse to the website. Best-effort, atomic tmp+replace
    — identical discipline to `season.export`. Air-gated: while
    `engine.statehouse_on` is False this is a pure no-op (no directories
    made, no file touched, no exception raised) — gate-off runs are
    byte-identical to doing nothing at all."""
    try:
        civ = engine.load_civics()
        ga = civ.get("ga", 1)
        if not engine.statehouse_on(ga):
            return

        dk = engine.load_side(f"docket-ga{ga}.json") or {}
        cal = engine.load_side(f"calendar-ga{ga}.json") or {}

        tracked = civ.get("tracked") or {}
        bill_id = tracked.get("id")
        bill = dk.get("bills", {}).get(bill_id) if bill_id else None
        tracked_out = None
        if bill_id and bill:
            stage = bill.get("stage", "")
            tracked_out = {
                "id": bill_id,
                "title": bill.get("title", ""),
                "stage": sheets.STAGE_WORDS.get(stage, stage.lower().replace("_", " ")),
            }

        today = civ.get("sim_through") or ""
        election_date = ((cal.get("election") or {}).get("date")
                          or FALLBACK_ELECTION_DATE)
        days_to = _days_to(today, election_date) if today else None

        approval = civ.get("approval", {})
        out = {
            "ga": ga,
            "session": civ.get("session"),
            "phase": civ.get("phase"),
            "updated": today,
            "approval": {"gov": approval.get("gov"),
                         "streak": approval.get("streak", 0)},
            "tracked": tracked_out,
            "election": {"date": election_date, "days_to": days_to},
            "quorum_fails": len(civ.get("quorum_fails") or []),
        }

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(out))
        tmp.replace(p)
    except Exception as e:
        # the website is decoration; the broadcast is the product — but say
        # so, or a missing web dir is an invisible no-publish (season.export
        # precedent)
        print(f"  (statehouse.json publish skipped: {e})")
