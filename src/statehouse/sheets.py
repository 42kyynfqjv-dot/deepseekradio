"""Statehouse sheets — the broadcast contract (design freeze, mirror §7).

Leaf module: pure functions over the frozen `civics.json`/sidecar shapes
(`docs/designs/statehouse-mirror.md` §2, deltas in `statehouse-final.md`).
No file I/O, no imports of `season.py`/`orchestrator.py`/league modules, no
imports of sibling `src/statehouse/*` modules (those are separate leaf
components per the design's build-order table; this module only needs to
agree with their *output shapes*, per §10: "F needs B/C/E shapes only").
Code (the caller — eventually `civics.py`) owns every number; these
functions only phrase already-computed state. Nothing here invents a tally,
margin, or committee outcome that wasn't already sitting in the dicts handed
to us.

**The one-thread rule, structurally enforced**: only the TRACKED bill (in
`session_brief`/`gavel_recap`/`dome_desk`) or the TRACKED race (in
`election_sheet`) ever gets a numeric tally rendered. Every other bill/race
surfaces only as a stage word or status word — there is no code path in this
module that can print a whip count or a vote tally for an untracked id.
Fifty-nine other seats stay deep in code, light on air.

**Schema-friction notes (frozen contract, conformed to as given):**
  - Whip counts (`floor.whip_count`) and the election reveal clock
    (`election.reveal`) are computed by sibling leaf modules this module may
    not import (they may not even exist yet in a parallel build — the design
    explicitly scopes this module's dependency to their *shapes* only, §10).
    So `session_brief` takes an already-computed `whip` dict and
    `election_sheet` takes an already-computed `revealed` dict (exactly
    `election.reveal(el, cursor)`'s return shape) as parameters, rather than
    deriving them. This is the literal reading of this task's "all pure
    (state passed in)" instruction.
  - Committee "flavor names" (the design's own worked example renders
    committee "roads" as "Roads, Holes & Adjacent Depressions") are docket.py
    naming vocabulary (`bill_title`-style templates), not schema data, and
    are not specified anywhere frozen. Rather than invent unsanctioned canon,
    this module speaks the plain committee id it is given, title-cased
    ("the Roads committee"). Swapping in a flavored name table later is a
    docket.py addition, not a sheets.py change.
  - `docket-ga{n}.json` only documents the `REPORTED` history-tuple shape in
    full (`[date, "REPORTED", committee, [yea, nay]]`); floor-stage tuples
    (`PASSED_ORIGIN`, `PASSED_BOTH`, `SIGNED`, `VETOED`, ...) aren't given a
    worked example. `_parse_hist` therefore parses generically: the first
    2-int list/tuple among the trailing extras is the tally, the first bare
    string is the context tag (committee name, vote-type, whatever) — order
    -independent and forgiving of exactly which floor.py ends up emitting.
"""
from __future__ import annotations

# ---------------------------------------------------------------- vocabulary

# Stage enum (docket.py's, quoted verbatim from statehouse-mirror.md §2) —
# this is the guard's stage vocabulary; sheets speaks only these words for a
# bill's status, never an invented synonym.
STAGE_WORDS = {
    "INTRODUCED": "introduced",
    "IN_COMMITTEE": "in committee",
    "REPORTED": "reported out of committee",
    "CALENDARED": "calendared for floor action",
    "PASSED_ORIGIN": "passed its chamber of origin",
    "IN_SECOND": "in its second chamber",
    "REPORTED_2": "reported out of committee in its second chamber",
    "PASSED_BOTH": "passed both chambers",
    "CONFERENCE": "in conference committee",
    "ENROLLED": "enrolled, awaiting the Governor",
    "SIGNED": "signed into law",
    "VETOED": "vetoed",
    "OVERRIDDEN": "enacted over a veto",
    "LAW_NO_SIG": "law without the Governor's signature",
    "DIED_IN_COMMITTEE": "died in committee",
    "MERGED": "referred to the Committee on Merging",
    "CROSSOVER_BARRED": "barred at the crossover deadline",
    "FAILED_FLOOR": "failed on the floor",
    "POCKET": "died by pocket veto",
}

# History entries dated `date` that count as a "resolved outcome" for the
# gavel recap / dome desk wire — introductions, hearings, and calendaring are
# color, not decisive news (delta/§7: "unresolved votes have no outcome yet").
_DECISIVE = {
    "REPORTED", "REPORTED_2", "PASSED_ORIGIN", "PASSED_BOTH", "CONFERENCE",
    "ENROLLED", "SIGNED", "VETOED", "OVERRIDDEN", "LAW_NO_SIG",
    "DIED_IN_COMMITTEE", "MERGED", "CROSSOVER_BARRED", "FAILED_FLOOR",
    "POCKET",
}

CHAMBER_NAME = {"house": "House", "senate": "Senate"}

# Election-reveal status vocabulary (election.reveal's contract, mirror §6/§7)
_RACE_STATUS_WORDS = {
    "too-early": "too early to call",
    "leaning": "leaning",
    "called": "called",
    "recount": "headed to a recount",
    "rainout": "delayed by a rain-out precinct",
}


def _bill_chamber(bill_id: str) -> str:
    """'HB-7' -> 'house', 'SB-3' -> 'senate' (docket.py's own id prefixes)."""
    return "house" if bill_id[:1].upper() == "H" else "senate"


def _committee_words(committee) -> str:
    if not committee:
        return ""
    return "the " + str(committee).replace("_", " ").title() + " committee"


def _member_name(members: dict, mid) -> str:
    if not mid:
        return ""
    return (members.get("members", {}).get(mid) or {}).get("name", mid)


def whip_line(whip: dict, flavor: str | None = None) -> str:
    """Render an already-computed whip dict (floor.whip_count's shape:
    yea/nay/und, optionally absent — delta 1) as the frozen TRACKED-block
    phrase. Absent is spoken only when nonzero; the yea+nay+und+absent ==
    chamber-size invariant is a guard/construction concern (members.py,
    tested there), not something this renderer re-derives or enforces."""
    parts = [f"{whip['yea']} yea", f"{whip['nay']} nay", f"{whip['und']} undecided"]
    if whip.get("absent"):
        parts.append(f"{whip['absent']} absent")
    line = ", ".join(parts)
    return f"{line} — {flavor}" if flavor else line


# ---------------------------------------------------------------- session_brief

def session_brief(civ: dict, dk: dict, members: dict, date: str,
                   whip: dict | None = None, today: list | None = None,
                   beats: list | None = None) -> str:
    """The pregame-analog sheet. `civ`/`dk`/`members` are the frozen
    civics.json / docket-ga{n}.json / members-ga{n}.json bodies (§2 verbatim).
    `whip` is floor.whip_count's already-computed dict for the tracked bill
    (None if no vote is pending — an unresolved bill NEVER gets a predicted
    tally). `today` is a list of bill ids with committee action scheduled
    today (docket.committee_day's day's-worth of ids) — rendered as titles
    and stage words only, no numbers (§7). `beats` is a list of already
    -composed one-line AROUND THE DOME beats (deficiency notices, Merging
    referrals, pothole news) — capped at 3.
    """
    bills = dk.get("bills", {})
    tracked = civ.get("tracked") or {}
    bill_id = tracked.get("id")
    bill = bills.get(bill_id) if bill_id else None

    lines = []
    if not bill_id or not bill:
        lines.append("TRACKED: no marquee thread currently tracked.")
    else:
        stage = bill.get("stage", "")
        stage_word = STAGE_WORDS.get(stage, stage.lower().replace("_", " "))
        sponsor = _member_name(members, bill.get("sponsor"))
        committee = _committee_words(bill.get("committee"))
        lines.append(f"TRACKED: {bill_id} — {bill.get('title', '')}")
        head = f"Status: {stage_word}"
        if sponsor:
            head += f", sponsored by {sponsor}"
        if committee:
            head += f", in {committee}"
        lines.append(head + ".")
        if tracked.get("resolved"):
            lines.append(f"Resolved: {bill_id} {stage_word}.")
        elif whip:
            lines.append("Whip count: " + whip_line(whip) + ".")
            lines.append("No outcome yet — nothing is decided until the vote is called.")
        else:
            lines.append("No vote scheduled yet. No outcome yet.")
        nxt = tracked.get("beat")
        if nxt:
            lines.append(f"Next scheduled action: {nxt}.")

    lines.append("")
    lines.append("TODAY AT THE DOME:")
    if today:
        for bid in today:
            b = bills.get(bid)
            if not b:
                continue
            sw = STAGE_WORDS.get(b.get("stage", ""), b.get("stage", "").lower())
            lines.append(f"  {bid} — {b.get('title', '')} ({sw})")
    else:
        lines.append("  A quiet calendar today.")

    approval = civ.get("approval", {})
    lines.append("")
    lines.append(f"APPROVAL: {approval.get('gov')}, a {approval.get('streak', 0)}-day streak.")

    snowed = date in (civ.get("quorum_fails") or [])
    lines.append(f"WEATHER RULE: {'quorum fails — snow' if snowed else 'quorum holds'}.")

    lines.append("")
    lines.append("AROUND THE DOME:")
    if beats:
        for b in list(beats)[:3]:
            lines.append(f"  {b}")
    else:
        lines.append("  Nothing further to report.")

    return "\n".join(lines)


# ---------------------------------------------------------------- shared: today's decisive history

def _parse_hist(entry: list) -> tuple:
    """entry = [date, action, *extras] (docket §2). Returns
    (date, action, ctx, tally) where tally is a (yea, nay) int pair if any
    extra is a 2-int list/tuple, ctx is the first bare string extra, else
    None — order-independent parsing (see module friction note)."""
    date, action, *rest = entry
    tally, ctx = None, None
    for r in rest:
        if tally is None and isinstance(r, (list, tuple)) and len(r) == 2 and \
                all(isinstance(x, int) for x in r):
            tally = (int(r[0]), int(r[1]))
        elif ctx is None and isinstance(r, str):
            ctx = r
    return date, action, ctx, tally


def _today_decisive(dk: dict, date: str) -> list:
    """[(bill_id, action, ctx, tally), ...] for every DECISIVE history entry
    dated `date`, across the whole docket. This is pure schema reading — the
    docket schema itself stores resolved tallies in history at the moment
    they resolve (§2), so gavel_recap/dome_desk need no extra parameters
    beyond `dk` to find "what happened today"."""
    out = []
    for bill_id, bill in dk.get("bills", {}).items():
        for entry in bill.get("history", []):
            d, action, ctx, tally = _parse_hist(entry)
            if d == date and action in _DECISIVE:
                out.append((bill_id, action, ctx, tally))
    return out


def _recap_line(bills: dict, bill_id: str, action: str, ctx, tally) -> str:
    bill = bills.get(bill_id, {})
    if action in ("REPORTED", "REPORTED_2"):
        cmt = _committee_words(ctx or bill.get("committee"))
        if tally:
            return (f"{bill_id} cleared {cmt or 'committee'}, "
                     f"{tally[0]} votes to {tally[1]}")
        return f"{bill_id} cleared {cmt or 'committee'}"
    if action in ("PASSED_ORIGIN", "PASSED_BOTH", "FAILED_FLOOR"):
        chamber = _bill_chamber(bill_id)
        if action == "PASSED_BOTH":  # completed passage of the SECOND chamber
            chamber = "senate" if chamber == "house" else "house"
        cname = CHAMBER_NAME[chamber]
        verb = "failed on the floor of" if action == "FAILED_FLOOR" else "passed the"
        if tally:
            return f"{bill_id} {verb} {cname}, {tally[0]}-{tally[1]}"
        return f"{bill_id} {verb} {cname}"
    if action == "MERGED":
        return f"{bill_id} was referred to the Committee on Merging"
    return f"{bill_id} {STAGE_WORDS.get(action, action.lower())}"


def gavel_recap(civ: dict, dk: dict, date: str) -> tuple:
    """The postgame-analog sheet: today's resolved outcomes with the tallies
    already stored in docket history, plus the approval move. Returns
    `(text, event_ids)` — `event_ids` are `"{bill_id}:{action.lower()}"`
    strings matching civics.json's `aired` ledger key shape (§2), which the
    orchestrator stamps via `record_aired(ids, air_at)` once the audio ships
    (the `final_air_at` mirror)."""
    bills = dk.get("bills", {})
    decisive = _today_decisive(dk, date)
    lines, ids = [], []
    for bill_id, action, ctx, tally in decisive:
        lines.append(_recap_line(bills, bill_id, action, ctx, tally) + ".")
        ids.append(f"{bill_id}:{action.lower()}")
    if not lines:
        lines.append(f"No decisive Dome action on {date}.")

    approval = civ.get("approval", {})
    lines.append(f"APPROVAL: {approval.get('gov')}, a {approval.get('streak', 0)}-day streak.")
    return "\n".join(lines), ids


# ---------------------------------------------------------------- dome_desk

def dome_desk(civ: dict, dk: dict, date: str, beats: list | None = None,
              n: int = 5) -> str:
    """The news-desk equivalent of the league scores desk: ONE narratable
    wire line for today's Dome action, semicolon-joined, capped at `n`
    items (decisive history first, then any extra caller-supplied `beats`).
    """
    bills = dk.get("bills", {})
    decisive = _today_decisive(dk, date)
    items = [_recap_line(bills, bid, action, ctx, tally)
             for bid, action, ctx, tally in decisive]
    items += list(beats or [])
    items = items[:n]
    if not items:
        return f"No Dome wire for {date}."
    return f"At the Dome today: " + "; ".join(items) + "."


# ---------------------------------------------------------------- election_sheet

def election_sheet(cursor: int, revealed: dict, tracked_id: str | None = None,
                    prev_revealed: dict | None = None,
                    civ: dict | None = None) -> str:
    """Election-Night takeover sheet. `revealed` is exactly
    `election.reveal(el, cursor)`'s return shape (`{"pct_in": int,
    "races": {race_id: {"tally": [h, a], "wave": int, "status": str, ...}}}`
    — see module friction note on why this module takes the already-revealed
    dict rather than importing election.py itself). One-thread rule: ONLY
    `tracked_id`'s race ever gets a numeric tally; every other race surfaces
    as a status word alone, exactly like the design's "the Vanguard holds
    District 30" — no invented tallies for the other fifty-odd races.
    `prev_revealed` (an earlier beat's `revealed`, optional) drives the
    NEW CALLS line by diffing status per race. `civ` (optional) overlays
    today's approval/streak, per the design's "approval rides the night."
    """
    races = revealed.get("races", {})
    lines = [f"ELECTION NIGHT: {revealed.get('pct_in', 0)}% of precincts in."]

    if tracked_id and tracked_id in races:
        r = races[tracked_id]
        tally = r.get("tally", [0, 0])
        status = _RACE_STATUS_WORDS.get(r.get("status"), r.get("status", ""))
        lines.append(f"TRACKED RACE {tracked_id}: {tally[0]}-{tally[1]}, {status}.")
    else:
        lines.append("TRACKED RACE: too early to call.")

    prev_races = (prev_revealed or {}).get("races", {})
    new_calls = []
    for rid, r in races.items():
        if rid == tracked_id:
            continue
        was, now = prev_races.get(rid, {}).get("status"), r.get("status")
        if now == was:
            continue
        word = _RACE_STATUS_WORDS.get(now, now or "")
        if now in ("called", "recount", "rainout"):
            new_calls.append(f"{rid} {word}")
    if new_calls:
        lines.append("NEW CALLS: " + "; ".join(new_calls) + ".")

    if civ and civ.get("approval"):
        ap = civ["approval"]
        lines.append(f"APPROVAL OVERLAY: {ap.get('gov')}, "
                      f"a {ap.get('streak', 0)}-day streak.")

    return "\n".join(lines)
