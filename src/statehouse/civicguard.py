"""Civicguard — anti-hallucination truth cop for the Wending Statehouse.

Scoreguard-mirrored (`src/scoreguard.py`): the docket/members/election dicts
roll the facts; performers narrate them at temp 0.9 and will invent tallies,
flip committee outcomes, and call races before the votes are in. This walks
a sheet's dialogue against the engine's authoritative fact tables:
contradicting lines are REPLACED (never cut — a cut dangles the partner's
reply) with a neutral line in the statehouse register, and — the prime
directive — no correct line is ever falsely touched. Stdlib-only leaf
module: performers/orchestrator import this, never the reverse. No imports
of `season.py`/`orchestrator.py`/league modules, and no imports of sibling
`src/statehouse/*` modules (a separate leaf component per the design's
build-order table; this module only needs to agree with their *output
shapes* — mirror §7/§10, "F needs B/C/E shapes only").

Catches (mirror §8, plus final.md's delta-4 goose-price grounding):
  1. invented tallies/margins             -> grounded tally or stage words
  2. invented election/approval margins   -> revealed figure or "too early"
  3. invented committee outcomes          -> the bill's real stage word
  4. phantom bill numbers                 -> nearest real id (edit-distance)
  5. phantom member/official names        -> nearest real name (edit-distance)
  6. seat-count / quorum inventions       -> neutral ("check the chart")
  7. one-thread numeric leakage           -> stage/status words only
  8. result-before-air (pre-air spoilers) -> pre-resolution framing
  9. invented Goose-bloc price claims     -> neutral ("not on record")

**Schema-friction notes (frozen contract, conformed to as given):**
  - `STAGE_WORDS` / `_DECISIVE` are restated verbatim from
    `src/statehouse/sheets.py` (that module's own docstring: leaf modules
    restate shared vocabulary rather than cross-import, exactly like
    `calendar.py`'s Wed/Sat constant restatement) — this keeps the guard's
    stage vocabulary in lockstep with what sheets.py actually emits, so a
    sheet's own correct phrasing can never be mistaken for a lie.
  - The design's final.md deltas call out **present-and-voting thresholds**
    (majority-of-present-and-voting for ordinary bills; 26/51 majority-of
    -elected reserved for the override class) as something "the guard
    learns" — `HOUSE_OVERRIDE`/`SENATE_OVERRIDE` (34/51, 6/9) are exposed
    alongside the elected/quorum constants and checked wherever a line
    states a bare seat/quorum/override number. Re-deriving pass/fail from a
    raw tally is `floor.py`'s construction concern (it only ever *stores* a
    tally that already satisfies the real rule); this guard verifies claims
    against the stored record, it does not re-run the arithmetic.
  - The Goose bloc's price list (final.md delta 4: "enumerable canon...
    civicguard can therefore verify any claimed goose deal") isn't yet
    authored anywhere frozen (`members.py`'s `goose_price()` doesn't exist
    yet, per the build-order table). `_DEFAULT_GOOSE_PRICES` is this
    module's own placeholder canon list (mile-zero/pharmacy-lot/oath
    flavored, per delta 4's "lot paving, waterfowl, oaths"); callers with a
    real enumeration pass `state["goose_prices"]` to override it.
"""
from __future__ import annotations

import hashlib
import re

# ---------------------------------------------------------------- canon constants

HOUSE_ELECTED, SENATE_ELECTED = 51, 9
HOUSE_QUORUM, SENATE_QUORUM = 26, 5
HOUSE_OVERRIDE, SENATE_OVERRIDE = 34, 6

PARTIES = ("prov", "round", "vang", "barb", "grudge", "goose")  # OIC seatless

# Stage enum vocabulary — restated verbatim from sheets.py (see friction note).
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

# History actions that count as a "resolved outcome" needing an aired stamp
# before they may be claimed on a sheet — restated verbatim from sheets.py.
_DECISIVE = {
    "REPORTED", "REPORTED_2", "PASSED_ORIGIN", "PASSED_BOTH", "CONFERENCE",
    "ENROLLED", "SIGNED", "VETOED", "OVERRIDDEN", "LAW_NO_SIG",
    "DIED_IN_COMMITTEE", "MERGED", "CROSSOVER_BARRED", "FAILED_FLOOR",
    "POCKET",
}

_DEFAULT_GOOSE_PRICES = {
    "expanded pharmacy-lot paving",
    "a waterfowl-crossing sign at mile zero",
    "an oath exemption for the candidate",
    "a bread-adjacent amendment",
    "a lawn easement past the roundabout",
    "a corn subsidy rider",
}

# ---------------------------------------------------------------- lexicons

# claim phrase -> the set of *actual* bill stages it is truthfully compatible
# with (a claim is legal if the bill's real stage is anywhere downstream of
# what it asserts — "passed the house" stays true after the bill is signed).
_STAGE_CLAIMS = [
    (re.compile(r"\breported\b.{0,10}\bcommittee\b|\breported favorably\b|"
                r"\bcleared\b.{0,30}\bcommittee\b|\bvoted out of committee\b"),
     {"REPORTED", "REPORTED_2", "PASSED_ORIGIN", "IN_SECOND", "PASSED_BOTH",
      "CONFERENCE", "ENROLLED", "SIGNED", "VETOED", "OVERRIDDEN", "LAW_NO_SIG"}),
    (re.compile(r"\bpassed (?:its chamber of origin|the house|the senate)\b"),
     {"PASSED_ORIGIN", "IN_SECOND", "REPORTED_2", "PASSED_BOTH", "CONFERENCE",
      "ENROLLED", "SIGNED", "VETOED", "OVERRIDDEN", "LAW_NO_SIG"}),
    (re.compile(r"\bpassed both chambers\b"),
     {"PASSED_BOTH", "CONFERENCE", "ENROLLED", "SIGNED", "VETOED",
      "OVERRIDDEN", "LAW_NO_SIG"}),
    (re.compile(r"\bin conference committee\b"),
     {"CONFERENCE", "ENROLLED", "SIGNED", "VETOED", "OVERRIDDEN", "LAW_NO_SIG"}),
    (re.compile(r"\benrolled\b"),
     {"ENROLLED", "SIGNED", "VETOED", "OVERRIDDEN", "LAW_NO_SIG"}),
    (re.compile(r"\bsigned into law\b|\bthe governor signed\b|"
                r"\bsigned by the governor\b"),
     {"SIGNED"}),
    (re.compile(r"\bvetoed\b(?!\s*over)"),
     {"VETOED", "OVERRIDDEN"}),
    (re.compile(r"\benacted over a veto\b|\boverridden\b|\bveto override\b|"
                r"\boverride succeed"),
     {"OVERRIDDEN"}),
    (re.compile(r"\blaw without the governor'?s signature\b|"
                r"\bbecame law without signature\b"),
     {"LAW_NO_SIG"}),
    (re.compile(r"\bdied in committee\b"), {"DIED_IN_COMMITTEE"}),
    (re.compile(r"\breferred to the committee on merging\b|\bstill merging\b|"
                r"\bstill in the committee on merging\b"),
     {"MERGED"}),
    (re.compile(r"\bbarred at the crossover deadline\b|\bmissed crossover\b"),
     {"CROSSOVER_BARRED"}),
    (re.compile(r"\bfailed on the floor\b|\bfailed(?: its)? floor vote\b"),
     {"FAILED_FLOOR"}),
    (re.compile(r"\bdied by pocket veto\b|\bpocket veto(?:ed)?\b"),
     {"POCKET"}),
]

_BILL_ID = re.compile(r"\b([HS]B-\d+)\b")

_TITLE = re.compile(r"\b(?:Delegate|Senator|Governor|Clerk|Commissioner|"
                    r"Foreman|Speaker)\s+([A-Z][a-zA-Z']+(?:\s[A-Z][a-zA-Z']+)?)")
_ACTION_NAME = re.compile(
    r"\b([A-Z][a-zA-Z']+(?:\s[A-Z][a-zA-Z']+)?)\s+(?:sponsors|sponsored|"
    r"introduced|chairs|chaired|voted|said|moved|withdrew|amended)\b")

_CALL_WORD = re.compile(r"\bwins?\b|\bholds? (?:the seat|onto)|"
                        r"\bdeclared the winner\b|\bre-?elected\b|\bunseats?\b|"
                        r"\bdefeats?\b|\bconcedes?\b")

_SEATS_N = re.compile(r"\b(\d{1,3})\s+seats?\b")
_QUORUM_N = re.compile(r"\bquorum of (\d{1,3})\b")
_OVERRIDE_N = re.compile(r"\boverride (?:threshold|margin) of (\d{1,3})\b")

_TALLY_PAIR = re.compile(r"(?<![\d.-])(\d{1,3})\s*(?:-|–|—|to)\s*(\d{1,3})(?!\d)")
_YEA = re.compile(r"\b(\d{1,3})\s+yeas?\b")
_NAY = re.compile(r"\b(\d{1,3})\s+nays?\b")
_UND = re.compile(r"\b(\d{1,3})\s+undecided\b")
_ABS = re.compile(r"\b(\d{1,3})\s+absent\b")

_PCT = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*%")
_MARGIN_CTX = re.compile(r"approval|margin|lead|trail|of the vote|reporting|"
                        r"precinct|turnout")
_APPROVAL_CTX = re.compile(r"approval")

_GOOSE_DEAL = re.compile(
    r"goose (?:delegation|bloc|party)[^.]{0,60}?(?:after|for|in exchange for|"
    r"in return for)\s+([a-z][^.,;]{3,60})")

_MODAL = re.compile(  # predictions/hypotheticals pass whole (mirror scoreguard's rule)
    r"next (?:week|session|time)|gonna|will (?:pass|sign|veto)|\bwould\b|"
    r"\bif |could'?ve|should'?ve|i bet|prediction|imagine|what if")

_NEUTRAL = ["The Clerk will read the tally as recorded.",
            "Check the docket — nothing to add there.",
            "That's not what's on the board; moving on."]
_STAGE_FIX = ["The Clerk will read the tally as recorded.",
              "Check the docket — {bill} hasn't reached that stage.",
              "As recorded, {bill} stands elsewhere on the calendar."]
_MERGED_FIX = ["{bill} remains in the Committee on Merging.",
               "Still merging — {bill} hasn't moved.",
               "The Committee on Merging still has {bill}; it stays there."]
_SPOILER_FIX = ["The Clerk hasn't gaveled a result on {bill} yet.",
                "Nothing official on {bill} to report just yet.",
                "{bill} is still pending; no call to make there."]
_TALLY_FIX = ["The Clerk will read the tally as recorded.",
              "Check the board for the real count on that one.",
              "That's not the recorded tally — moving on."]
_SEAT_FIX = ["Check the seat chart — the numbers are as filed.",
             "The Clerk will confirm the seat count as filed.",
             "That's not the filed count; check the chart."]
_MARGIN_FIX = ["Too early to put a number on that.",
               "The Clerk will read the figure as recorded.",
               "That's not the number on the board."]
_RACE_FIX = ["Too early to call — the votes are still coming in.",
             "Not called yet; the count continues.",
             "Nothing official yet on that race."]
_GOOSE_FIX = ["That's not one of the Goose bloc's known considerations.",
              "The Clerk has no such Goose deal on file.",
              "Nothing on record ties the Goose delegation to that."]
_ONETHREAD_FIX = [
    "That bill's still moving, but the numbers aren't tonight's story.",
    "Fifty-nine other seats keep working quietly — no tally on that one tonight.",
    "Deep in the Dome, light on air — nothing numeric there tonight."]

_TEMPLATES = {
    "stage": _STAGE_FIX, "merged": _MERGED_FIX, "spoiler": _SPOILER_FIX,
    "tally": _TALLY_FIX, "seat": _SEAT_FIX, "margin": _MARGIN_FIX,
    "race": _RACE_FIX, "goose": _GOOSE_FIX, "onethread": _ONETHREAD_FIX,
    "name": _NEUTRAL,
}


def _stable_hash(s):
    """hash() is salted per-process; md5 keeps template rotation stable."""
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


def _edit_distance(a, b):
    a, b = a.lower(), b.lower()
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _nearest(token, pool):
    best, bd = None, None
    for cand in pool:
        d = _edit_distance(token, cand)
        if bd is None or d < bd:
            best, bd = cand, d
    return best


# ---------------------------------------------------------------- build_civic_facts

def build_civic_facts(state: dict, sheet: dict | None = None) -> dict:
    """Digest engine truth into the lookup tables `enforce_civic` walks.

    `state` bundles the frozen bodies a sheet was built from: `civ`
    (civics.json), `dk` (docket-ga{n}.json), `members` (members-ga{n}.json),
    optionally `election` (election-{cycle}.json, for candidate-name/race
    lookups) and `goose_prices` (override for `_DEFAULT_GOOSE_PRICES`).
    `date` is the sim day the sheet describes.

    `sheet` carries the already-computed extras a briefs.py sheet needed
    that this module has no other way to see: `mode`
    ("session_brief"|"gavel_recap"|"dome_desk"|"election_sheet"), `whip`
    (floor.whip_count's dict for the tracked bill), `revealed`
    (election.reveal's output, for election_sheet), and `tracked_id`
    (overrides `civ["tracked"]["id"]`, matching election_sheet's own
    signature). `sheet=None` builds facts for whatever `civ`/`dk` alone can
    ground (no whip/revealed numbers in play).
    """
    sheet = sheet or {}
    civ = state.get("civ", {})
    members = state.get("members", {})
    dk = state.get("dk", {})
    election = state.get("election")
    date = state.get("date", civ.get("sim_through"))
    mode = sheet.get("mode", "session_brief")

    names_ok = set()
    full_names = set()
    for m in members.get("members", {}).values():
        nm = m.get("name")
        if not nm:
            continue
        names_ok.add(nm.lower())
        names_ok.update(w.lower() for w in nm.split())
        full_names.add(nm)
    for key, o in members.get("officials", {}).items():
        if isinstance(o, dict) and o.get("name"):
            names_ok.add(o["name"].lower())
            names_ok.update(w.lower() for w in o["name"].split())
            full_names.add(o["name"])
    cand_race = {}
    if election:
        for rid, race in election.get("races", {}).items():
            for cand in race.get("cands", []):
                nm = cand.get("name")
                if not nm:
                    continue
                names_ok.add(nm.lower())
                names_ok.update(w.lower() for w in nm.split())
                full_names.add(nm)
                cand_race[nm.split()[-1].lower()] = rid

    bills = dk.get("bills", {})
    bill_ids = set(bills.keys())
    stage_of = {bid: b.get("stage") for bid, b in bills.items()}

    allow_tallies = {}
    for bid, b in bills.items():
        for entry in b.get("history", []):
            for extra in entry[2:]:
                if isinstance(extra, (list, tuple)) and len(extra) == 2 and \
                        all(isinstance(x, int) for x in extra):
                    d = allow_tallies.setdefault(bid, {})
                    d["yea"], d["nay"] = int(extra[0]), int(extra[1])
    whip = sheet.get("whip") or {}
    for bid, w in whip.items():
        allow_tallies.setdefault(bid, {}).update(w)

    approval = civ.get("approval", {})
    approval_today = approval.get("gov")
    series = approval.get("series") or {}
    if date in series:
        approval_today = series[date]

    aired = set(civ.get("aired", {}).keys())
    seats = civ.get("seats", {})

    tracked = civ.get("tracked") or {}
    tracked_kind = tracked.get("kind")
    tracked_id = sheet.get("tracked_id", tracked.get("id"))

    election_facts = None
    revealed = sheet.get("revealed")
    if revealed:
        election_facts = {
            "races_ok": set(revealed.get("races", {}).keys()),
            "revealed": revealed.get("races", {}),
            "pct_in": revealed.get("pct_in"),
            "cand_race": cand_race,
        }

    goose_prices_ok = {g.lower() for g in state.get("goose_prices",
                                                    _DEFAULT_GOOSE_PRICES)}

    return {
        "mode": mode, "date": date,
        "names_ok": names_ok, "full_names": full_names,
        "bill_ids": bill_ids, "stage_of": stage_of,
        "allow_tallies": allow_tallies,
        "seats": seats,
        "approval_today": approval_today,
        "aired": aired,
        "election": election_facts,
        "goose_prices_ok": goose_prices_ok,
        "tracked_kind": tracked_kind, "tracked_id": tracked_id,
    }


# ---------------------------------------------------------------- fix helpers

def _fix_phantom_bills(text, facts):
    changed = [False]

    def repl(m):
        bid = m.group(1)
        if bid in facts["bill_ids"] or not facts["bill_ids"]:
            return bid
        changed[0] = True
        return _nearest(bid, facts["bill_ids"]) or bid

    return _BILL_ID.sub(repl, text), changed[0]


def _fix_phantom_names(text, facts):
    changed = [False]

    def repl(m):
        name = m.group(1)
        if name.lower() in facts["names_ok"] or \
                name.split()[-1].lower() in facts["names_ok"]:
            return m.group(0)
        if not facts["full_names"]:
            return m.group(0)
        changed[0] = True
        nearest = _nearest(name, facts["full_names"])
        return m.group(0)[:m.start(1) - m.start(0)] + nearest + \
            m.group(0)[m.end(1) - m.start(0):]

    for pat in (_TITLE, _ACTION_NAME):
        text = pat.sub(repl, text)
    return text, changed[0]


# ---------------------------------------------------------------- the walk

def _check(text, facts, last_bill):
    """-> (kind, bill_id) | None. `text` already has phantom bills/names
    substituted, so any `[HS]B-\\d+` it contains is a real id."""
    low = text.lower()
    mentioned = _BILL_ID.findall(text)
    subject_bill = mentioned[-1] if mentioned else last_bill

    # 3 + 8: invented committee outcomes / result-before-air
    if subject_bill and subject_bill in facts["stage_of"]:
        stage = facts["stage_of"][subject_bill]
        for pat, legal in _STAGE_CLAIMS:
            if pat.search(low):
                if stage not in legal:
                    return (("merged" if stage == "MERGED" else "stage"),
                            subject_bill)
                if stage in _DECISIVE:
                    event_id = f"{subject_bill}:{stage.lower()}"
                    if event_id not in facts["aired"]:
                        return "spoiler", subject_bill
                break

    # 7: one-thread rule — numeric detail on a non-tracked bill
    if facts["tracked_kind"] == "bill" and mentioned:
        has_number = bool(_TALLY_PAIR.search(low) or _YEA.search(low) or
                          _NAY.search(low) or _UND.search(low) or
                          _ABS.search(low))
        for bid in mentioned:
            if bid != facts["tracked_id"] and has_number:
                return "onethread", bid

    # 1: invented tallies
    def _known_pair(x, y):
        for t in facts["allow_tallies"].values():
            if "yea" in t and "nay" in t and \
                    tuple(sorted((x, y))) == tuple(sorted((t["yea"], t["nay"]))):
                return True
        return False

    for m in _TALLY_PAIR.finditer(low):
        x, y = int(m.group(1)), int(m.group(2))
        if x > 99 or y > 99:
            continue
        if subject_bill and subject_bill in facts["allow_tallies"]:
            t = facts["allow_tallies"][subject_bill]
            if "yea" in t and "nay" in t and \
                    tuple(sorted((x, y))) == tuple(sorted((t["yea"], t["nay"]))):
                continue
            return "tally", subject_bill
        if not _known_pair(x, y):
            return "tally", subject_bill

    for pat, bucket in ((_YEA, "yea"), (_NAY, "nay"), (_UND, "und"), (_ABS, "absent")):
        for m in pat.finditer(low):
            n = int(m.group(1))
            if subject_bill and subject_bill in facts["allow_tallies"] and \
                    bucket in facts["allow_tallies"][subject_bill]:
                if facts["allow_tallies"][subject_bill][bucket] != n:
                    return "tally", subject_bill
            elif not any(bucket in t and t[bucket] == n
                        for t in facts["allow_tallies"].values()):
                return "tally", subject_bill

    # 6: seat-count / quorum inventions
    for m in _SEATS_N.finditer(low):
        n = int(m.group(1))
        valid = {HOUSE_ELECTED, SENATE_ELECTED, HOUSE_ELECTED + SENATE_ELECTED}
        for chamber in ("house", "senate"):
            valid |= set(facts["seats"].get(chamber, {}).values())
        if n not in valid:
            return "seat", subject_bill
    for m in _QUORUM_N.finditer(low):
        if int(m.group(1)) not in (HOUSE_QUORUM, SENATE_QUORUM):
            return "seat", subject_bill
    for m in _OVERRIDE_N.finditer(low):
        if int(m.group(1)) not in (HOUSE_OVERRIDE, SENATE_OVERRIDE):
            return "seat", subject_bill

    # 2: invented margins / percentages (approval or election)
    for m in _PCT.finditer(low):
        window = low[max(0, m.start() - 30):m.end() + 30]
        if not _MARGIN_CTX.search(window):
            continue
        n = float(m.group(1))
        if _APPROVAL_CTX.search(window):
            if facts["approval_today"] is not None and \
                    abs(n - facts["approval_today"]) > 0.05:
                return "margin", subject_bill
            continue
        if facts["election"]:
            races = facts["election"]["revealed"]
            hit = any(abs(r.get("margin_pct", -1) - n) < 0.05 for r in races.values())
            pct_in = facts["election"].get("pct_in")
            if not hit and pct_in is not None and abs(n - pct_in) < 0.05:
                hit = True
            if not hit:
                return "margin", subject_bill

    # premature race calls (only checkable with a revealed reveal() dict)
    if facts["election"] and _CALL_WORD.search(low):
        for surname, rid in facts["election"]["cand_race"].items():
            if re.search(r"\b%s\b" % re.escape(surname), low):
                status = facts["election"]["revealed"].get(rid, {}).get("status")
                if status != "called":
                    return "race", rid

    # 9: invented Goose-bloc price claims
    m = _GOOSE_DEAL.search(low)
    if m:
        claim = m.group(1).strip()
        if not any(claim in g or g in claim for g in facts["goose_prices_ok"]):
            return "goose", subject_bill

    return None


def enforce_civic(lines, facts):
    """Walk `lines` (scoreguard-shaped `{"text": ..., ...}` dicts) against
    `facts`. Violating lines are REPLACED (never cut) with a neutral line in
    the statehouse register; phantom bill ids/names are corrected in place.
    Returns a new list; input dicts are never mutated (the prime directive:
    a correct line is never touched)."""
    out = []
    last_bill = None
    for ln in lines:
        text = ln.get("text", "")
        if _MODAL.search(text.lower()):   # predictions/hypotheticals pass whole
            out.append(ln)
            continue

        fixed, changed_b = _fix_phantom_bills(text, facts)
        fixed, changed_n = _fix_phantom_names(fixed, facts)
        changed = changed_b or changed_n

        mentioned = _BILL_ID.findall(fixed)
        if mentioned:
            last_bill = mentioned[-1]

        kind = _check(fixed, facts, last_bill)
        if kind:
            what, bid = kind
            tpl = _TEMPLATES[what]
            new = dict(ln)
            new["text"] = tpl[_stable_hash(text) % len(tpl)].format(
                bill=bid or facts.get("tracked_id") or "the bill")
            new["_enforced"] = True
            out.append(new)
        elif changed:
            new = dict(ln)
            new["text"] = fixed
            new["_enforced"] = True
            out.append(new)
        else:
            out.append(ln)
    return out
