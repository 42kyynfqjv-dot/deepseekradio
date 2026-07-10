"""Civicguard fixtures: correct lines survive untouched (prime directive),
and every lie class the design calls out (mirror §8 + final.md delta 4's
goose-price grounding) gets caught and replaced.

Run directly (no pytest needed):  python3 tests/test_statehouse_civicguard.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.statehouse import civicguard as cg

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def L(text):
    return {"text": text}


# --------------------------------------------------------------- fixture state

DATE = "2026-07-09"   # Thursday — never Wed/Sat (delta 5)

MEMBERS = {
    "members": {
        "H-03": {"name": "Doreen Vachon", "chamber": "house", "party": "round"},
        "H-11": {"name": "Silas Trombley", "chamber": "house", "party": "prov"},
        "H-19": {"name": "Odette Marchetti", "chamber": "house", "party": "vang"},
    },
    "officials": {
        "governor": {"name": "Marty Bouchard", "canon": True},
        "clerk": {"name": "Gord Pelletier", "canon": True},
        "potholes": {"name": "Bert Demers", "canon": True},
        "roundabout": {"name": "Toivo Ostberg", "canon": True},
    },
}

DOCKET = {
    "schema": 1, "ga": 1, "next_no": {"H": 21, "S": 4},
    "bills": {
        "HB-7": {
            "title": "An Act Relating to the Numbering of Potholes Prior to Repair",
            "sponsor": "H-03", "committee": "roads", "stage": "REPORTED",
            "history": [["2026-07-01", "INTRODUCED"],
                        ["2026-07-07", "HEARING", "roads"],
                        ["2026-07-09", "REPORTED", "roads", [6, 3]]],
        },
        "SB-3": {
            "title": "An Act Establishing a Committee to Name the Candidate",
            "sponsor": "S-05", "committee": "merging", "stage": "MERGED",
            "history": [["2026-02-02", "INTRODUCED"],
                        ["2026-02-03", "MERGED", "merging"]],
        },
        "HB-12": {
            "title": "An Act Concerning the Roundabout Master Plan",
            "sponsor": "H-11", "committee": "transport", "stage": "SIGNED",
            "history": [["2026-07-02", "INTRODUCED"],
                        ["2026-07-07", "REPORTED", "transport", [27, 19]],
                        ["2026-07-09", "SIGNED"]],
        },
        "HB-20": {
            "title": "An Act Concerning the Roundabout Foreman's Timeline",
            "sponsor": "H-19", "committee": "transport", "stage": "VETOED",
            "history": [["2026-07-02", "INTRODUCED"],
                        ["2026-07-09", "VETOED"]],
        },
    },
}

CIVICS = {
    "ga": 1, "sim_through": DATE, "phase": "session",
    "seats": {
        "house": {"prov": 14, "round": 9, "vang": 11, "barb": 7, "grudge": 6, "goose": 4},
        "senate": {"prov": 3, "vang": 2, "round": 2, "barb": 1, "grudge": 1},
    },
    "approval": {"gov": 46.2, "streak": 3, "series": {DATE: 46.2}},
    "tracked": {"kind": "bill", "id": "HB-7", "since": "2026-07-07",
                "beat": "committee", "resolved": None},
    "quorum_fails": [],
    # HB-12:signed and HB-20:vetoed deliberately absent -> spoiler fixtures
    "aired": {"HB-7:reported": 1789200000.0, "SB-3:merged": 1780000000.0,
              "HB-12:signed": 1789200001.0},
}

STATE = {"civ": CIVICS, "dk": DOCKET, "members": MEMBERS, "date": DATE}
FACTS = cg.build_civic_facts(STATE, {"mode": "gavel_recap"})

ELECTION = {
    "races": {
        "H-03": {"cands": [{"name": "Doreen Vachon", "party": "round", "inc": True},
                            {"name": "Lucille Marchand", "party": "vang"}]},
    },
}
REVEALED_LEADING = {"pct_in": 61, "races": {
    "H-03": {"tally": [1121, 1002], "wave": 2, "status": "leading", "margin_pct": 5.7}}}
REVEALED_CALLED = {"pct_in": 92, "races": {
    "H-03": {"tally": [1980, 1240], "wave": 3, "status": "called", "margin_pct": 22.9}}}

STATE_EL = {"civ": CIVICS, "dk": DOCKET, "members": MEMBERS, "election": ELECTION,
            "date": DATE}
FACTS_LEADING = cg.build_civic_facts(STATE_EL, {"mode": "election_sheet",
                                                "revealed": REVEALED_LEADING})
FACTS_CALLED = cg.build_civic_facts(STATE_EL, {"mode": "election_sheet",
                                               "revealed": REVEALED_CALLED})

# ============================================================= build_civic_facts

check(FACTS["bill_ids"] == {"HB-7", "SB-3", "HB-12", "HB-20"}, "bill_ids collected")
check(FACTS["stage_of"]["HB-7"] == "REPORTED", "stage_of reads docket")
check(FACTS["allow_tallies"]["HB-7"] == {"yea": 6, "nay": 3}, "tally pulled from history")
check(FACTS["allow_tallies"]["HB-12"] == {"yea": 27, "nay": 19},
      "earlier-stage tally still on record after bill advances")
check(FACTS["approval_today"] == 46.2, "approval pulled from series[date]")
check("doreen vachon" in FACTS["names_ok"], "member name in names_ok")
check("marty bouchard" in FACTS["names_ok"], "official name in names_ok")
check(FACTS["tracked_id"] == "HB-7" and FACTS["tracked_kind"] == "bill",
      "tracked thread read from civ")
check(FACTS["seats"]["house"]["prov"] == 14, "seat aggregate read from civ")
check("a bread-adjacent amendment" in FACTS["goose_prices_ok"],
      "default goose price list present")

# ============================================================ prime directive
# Every one of these lines is TRUE against FACTS and must survive byte-for-byte.

CORRECT = [
    L("HB-7 cleared committee, 6-3."),
    L("SB-3 remains referred to the Committee on Merging."),
    L("HB-12 was signed into law."),
    L("The Governor's approval sits at 46.2% today."),
    L("The House holds 51 seats total."),
    L("The Provisional Party holds 14 seats in the House."),
    L("That's a quorum of 26 in the House."),
    L("The Goose delegation voted yea after securing a bread-adjacent amendment."),
    L("Delegate Doreen Vachon sponsors HB-7."),
    L("The Clerk logged 6 yea, 3 nay for HB-7."),
]
out = cg.enforce_civic(CORRECT, FACTS)
for orig, enf in zip(CORRECT, out):
    check(enf["text"] == orig["text"] and "_enforced" not in enf,
          f"correct line untouched: {orig['text']!r} -> {enf['text']!r}")

out_called = cg.enforce_civic([L("Doreen Vachon wins District 3.")], FACTS_CALLED)
check(out_called[0]["text"] == "Doreen Vachon wins District 3." and
      "_enforced" not in out_called[0], "true race call left untouched")

out_margin_ok = cg.enforce_civic([L("Vachon leads by a 5.7% margin.")], FACTS_LEADING)
check(out_margin_ok[0]["text"] == "Vachon leads by a 5.7% margin." and
      "_enforced" not in out_margin_ok[0], "true election margin left untouched")

# a prediction/hypothetical passes whole, even with wrong-looking numbers
out_modal = cg.enforce_civic(
    [L("If HB-7 passed 40-2 next session, the Roundabout bloc would be stunned.")],
    FACTS)
check("_enforced" not in out_modal[0], "hypothetical banter untouched")

# ================================================================= lie classes

# 1. invented tally
out = cg.enforce_civic([L("HB-7 cleared committee, 9-1.")], FACTS)
check(out[0].get("_enforced") is True, "invented tally caught")
check(out[0]["text"] != "HB-7 cleared committee, 9-1.", "invented tally text replaced")

# 2a. invented approval percentage
out = cg.enforce_civic([L("The Governor's approval sits at 52% today.")], FACTS)
check(out[0].get("_enforced") is True, "invented approval % caught")

# 2b. invented election margin
out = cg.enforce_civic([L("Vachon leads by a 12% margin.")], FACTS_LEADING)
check(out[0].get("_enforced") is True, "invented election margin caught")

# 3. invented committee outcome
out = cg.enforce_civic([L("HB-7 was signed into law.")], FACTS)
check(out[0].get("_enforced") is True, "invented committee outcome caught")
check(out[0]["text"] != "HB-7 was signed into law.", "wrong-stage claim replaced")

# 3b. MERGED is terminal-but-not-dead: any other claim gets the Merging joke
out = cg.enforce_civic([L("SB-3 was vetoed by the Governor.")], FACTS)
check(out[0].get("_enforced") is True, "false claim on a MERGED bill caught")
check("merging" in out[0]["text"].lower(),
      "MERGED bill corrected back to the Committee on Merging")

# 4. phantom bill number
out = cg.enforce_civic([L("Let's check in on HB-99 before we move on.")], FACTS)
check(out[0].get("_enforced") is True, "phantom bill id caught")
check("HB-99" not in out[0]["text"], "phantom bill id removed")
check(any(bid in out[0]["text"] for bid in FACTS["bill_ids"]),
      "phantom bill id replaced with a real one")

# 5. phantom member name
out = cg.enforce_civic(
    [L("Delegate Nathaniel Frobisher moved to recommit HB-7.")], FACTS)
check(out[0].get("_enforced") is True, "phantom name caught")
check("Frobisher" not in out[0]["text"], "phantom surname removed")
check(any(nm in out[0]["text"] for nm in FACTS["full_names"]),
      "phantom name replaced with a real one")

# 6a. invented seat count
out = cg.enforce_civic([L("The House now holds 55 seats.")], FACTS)
check(out[0].get("_enforced") is True, "invented seat count caught")

# 6b. invented quorum
out = cg.enforce_civic([L("That's a quorum of 30 in the Senate.")], FACTS)
check(out[0].get("_enforced") is True, "invented quorum caught")

# 7. one-thread rule: numeric detail leaking onto a non-tracked bill
out = cg.enforce_civic([L("HB-12 cleared committee, 27-19.")], FACTS)
check(out[0].get("_enforced") is True, "one-thread numeric leak caught")
check("27-19" not in out[0]["text"] and "27" not in out[0]["text"],
      "off-tracked tally stripped to stage/status words")

# untracked bill WITHOUT numbers is fine — stage/status words stay light on air
out = cg.enforce_civic([L("HB-12 was signed into law.")], FACTS)
check("_enforced" not in out[0],
      "off-tracked stage word alone (no numbers) is not one-thread'd")

# 8. result-before-air (pre-air spoiler)
out = cg.enforce_civic([L("HB-20 was vetoed by the Governor.")], FACTS)
check(out[0].get("_enforced") is True, "pre-air spoiler caught")
check("vetoed" not in out[0]["text"].lower(),
      "spoiler replaced with pre-resolution framing")

# 9. invented Goose-bloc price (final.md delta 4)
out = cg.enforce_civic(
    [L("The Goose delegation voted yea after securing a lifetime pharmacy discount.")],
    FACTS)
check(out[0].get("_enforced") is True, "invented goose deal caught")

# premature race call (before the reveal cursor's call moment)
out = cg.enforce_civic([L("Doreen Vachon wins District 3.")], FACTS_LEADING)
check(out[0].get("_enforced") is True, "premature race call caught")
check("too early" in out[0]["text"].lower() or "not called" in out[0]["text"].lower()
      or "nothing official" in out[0]["text"].lower(),
      "premature call replaced with a not-yet-called framing")

# ---------------------------------------------------------- replace-never-cut

out = cg.enforce_civic([L("HB-7 cleared committee, 9-1.")], FACTS)
check(len(out) == 1 and out[0].get("text"), "violating line replaced, never dropped")

# input lines are never mutated
original = L("HB-7 cleared committee, 9-1.")
_ = cg.enforce_civic([original], FACTS)
check(original["text"] == "HB-7 cleared committee, 9-1.", "input line dict not mutated")

print(f"\ncivicguard {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
