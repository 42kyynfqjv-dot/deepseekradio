"""Statehouse sheets tests: session_brief / gavel_recap / dome_desk /
election_sheet against the frozen civics.json/sidecar shapes (mirror §2/§7).

Every sheet test includes a self-guard round-trip placeholder — render, then
assert the sheet's numeric claims are internally consistent (tally sums,
chamber sizes). The real `civicguard` component wires the full guard; this
is the sheets-side sanity check the design calls for.

Run directly (no pytest needed): python3 tests/test_statehouse_sheets.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.statehouse import sheets

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


# ------------------------------------------------------------ fixtures

HOUSE_SEATS = {"prov": 14, "round": 9, "vang": 11, "barb": 7, "grudge": 6, "goose": 4}
SENATE_SEATS = {"prov": 3, "vang": 2, "round": 2, "barb": 1, "grudge": 1}
CHAMBER_SIZE = {"house": sum(HOUSE_SEATS.values()), "senate": sum(SENATE_SEATS.values())}
check(CHAMBER_SIZE["house"] == 51, "fixture: 51 House seats (canon)")
check(CHAMBER_SIZE["senate"] == 9, "fixture: 9 Senate seats (canon)")


def make_civ(**over):
    civ = {
        "ga": 1, "session": "regular-extended", "sim_through": "2026-07-12",
        "phase": "session",
        "seats": {"house": dict(HOUSE_SEATS), "senate": dict(SENATE_SEATS)},
        "approval": {"gov": 46.2, "streak": 3, "series": {"2026-07-12": 46.2}},
        "tracked": {"kind": "bill", "id": "HB-7", "since": "2026-07-10",
                    "beat": "committee", "resolved": None},
        "quorum_fails": ["2026-02-11"],
        "aired": {},
        "last_line": "", "rolled_pending": False,
    }
    civ.update(over)
    return civ


def make_dk(**over):
    dk = {
        "schema": 1, "ga": 1, "next_no": {"H": 41, "S": 12},
        "bills": {
            "HB-7": {
                "title": "An Act Relating to the Numbering of Potholes Prior to Repair",
                "sponsor": "H-03", "cosponsors": ["H-14", "H-22"],
                "committee": "roads", "stage": "REPORTED",
                "intro": "2026-07-01", "marquee": 0.91,
                "history": [["2026-07-01", "INTRODUCED"],
                            ["2026-07-06", "HEARING", "roads"],
                            ["2026-07-10", "REPORTED", "roads", [6, 3]]],
                "deficiency": None,
            },
            "SB-3": {
                "title": "An Act Establishing a Committee to Name the Candidate",
                "sponsor": "S-05", "committee": "merging", "stage": "MERGED",
                "intro": "2026-02-02", "marquee": 0.30,
                "history": [["2026-02-02", "INTRODUCED"],
                            ["2026-02-03", "REFERRED", "merging"]],
                "deficiency": None,
            },
        },
    }
    dk.update(over)
    return dk


MEMBERS = {
    "schema": 1, "ga": 1,
    "members": {
        "H-03": {"name": "Doreen Vachon", "chamber": "house", "district": 3,
                 "party": "round", "zipper": 0.44, "maverick": 0.12,
                 "tenure": 3, "aired": False},
        "S-05": {"name": "Earl Thibodeau", "chamber": "senate", "district": 105,
                 "party": "prov", "zipper": 0.21, "maverick": 0.05,
                 "tenure": 6, "aired": False},
    },
    "officials": {
        "governor": {"name": "Marty Bouchard", "canon": True},
        "speaker": "H-19", "protem": "S-02",
    },
    "leaders": {"house": {"prov": "H-11", "vang": "H-30"}, "senate": {"prov": "S-02"}},
}


def _tally_pairs(text):
    """Every '(N) votes to (N)' / '(N)-(N)' numeric pair mentioned."""
    pairs = [(int(a), int(b)) for a, b in re.findall(r"(\d+) votes to (\d+)", text)]
    pairs += [(int(a), int(b)) for a, b in re.findall(r"\b(\d+)-(\d+)\b", text)]
    return pairs


# ================================================================ session_brief

def test_session_brief_tracked_with_whip():
    civ = make_civ()
    dk = make_dk()
    whip = {"yea": 27, "nay": 19, "und": 2, "absent": 3}
    out = sheets.session_brief(civ, dk, MEMBERS, "2026-07-10", whip=whip,
                                today=["HB-7"], beats=["Deficiency notice: SB-3 frozen 4 days."])
    check("TRACKED: HB-7" in out, "session_brief names the tracked bill")
    check("Doreen Vachon" in out, "session_brief resolves sponsor name")
    check("reported out of committee" in out, "session_brief uses STAGE_WORDS vocabulary")
    check("27 yea, 19 nay, 2 undecided, 3 absent" in out, "session_brief renders full whip incl. absent")
    check("No outcome yet" in out, "session_brief never predicts an unresolved tally")
    check("TODAY AT THE DOME" in out and "HB-7" in out.split("TODAY AT THE DOME")[1],
          "session_brief lists today's committee bill")
    committee_block = out.split("TODAY AT THE DOME:")[1].split("APPROVAL:")[0]
    check(not re.search(r"\d+ (?:yea|nay|votes)", committee_block),
          "TODAY AT THE DOME carries stage words only, no vote numbers")
    check("46.2" in out and "3-day streak" in out, "session_brief renders approval + streak")
    check("quorum holds" in out, "session_brief: no snow on 2026-07-10")
    check("Deficiency notice" in out, "session_brief renders AROUND THE DOME beats")

    # self-guard placeholder: whip bucket sum == chamber size for HB-7 (House)
    total = whip["yea"] + whip["nay"] + whip["und"] + whip["absent"]
    check(total == CHAMBER_SIZE["house"],
          "self-guard: yea+nay+und+absent == chamber size (delta 1 invariant)")


def test_session_brief_snow_and_untracked():
    civ = make_civ(tracked={"kind": None, "id": None, "since": None,
                             "beat": None, "resolved": None})
    dk = make_dk()
    out = sheets.session_brief(civ, dk, MEMBERS, "2026-02-11")
    check("no marquee thread currently tracked" in out, "session_brief handles no-tracked state")
    check("quorum fails" in out and "snow" in out, "session_brief renders snow-quorum day")
    check("A quiet calendar today." in out, "session_brief default TODAY block with no `today`")
    check("Nothing further to report." in out, "session_brief default AROUND block with no beats")


def test_session_brief_resolved_no_whip_predicted():
    civ = make_civ(tracked={"kind": "bill", "id": "HB-7", "since": "2026-07-01",
                             "beat": None, "resolved": "2026-07-10"})
    dk = make_dk()
    dk["bills"]["HB-7"]["stage"] = "SIGNED"
    out = sheets.session_brief(civ, dk, MEMBERS, "2026-07-10", whip={"yea": 1, "nay": 0, "und": 0})
    check("Resolved: HB-7 signed into law." in out, "session_brief renders resolved outcome")
    check("No outcome yet" not in out, "session_brief drops the never-predict caveat once resolved")


# ================================================================ gavel_recap

def test_gavel_recap_decisive_events():
    civ = make_civ()
    dk = make_dk()
    text, ids = sheets.gavel_recap(civ, dk, "2026-07-10")
    check("HB-7 cleared the Roads committee, 6 votes to 3." in text,
          "gavel_recap renders the stored REPORTED tally verbatim")
    check(ids == ["HB-7:reported"], "gavel_recap returns aired-ledger-shaped event ids")
    check("46.2" in text and "3-day streak" in text, "gavel_recap carries the approval move")
    # self-guard: every tally number printed matches the docket's own stored tally
    for a, b in _tally_pairs(text):
        check((a, b) == (6, 3), "self-guard: printed tally matches docket history exactly")


def test_gavel_recap_merged_and_no_events():
    civ = make_civ()
    dk = make_dk()
    dk["bills"]["SB-3"]["history"].append(["2026-07-10", "MERGED"])
    text, ids = sheets.gavel_recap(civ, dk, "2026-07-10")
    check("SB-3 was referred to the Committee on Merging." in text,
          "gavel_recap renders MERGED with canon Committee phrasing")
    check("SB-3:merged" in ids, "gavel_recap event id for MERGED matches aired-ledger shape")

    text2, ids2 = sheets.gavel_recap(civ, dk, "2099-01-01")
    check(ids2 == [], "gavel_recap returns no event ids on a day with no decisive history")
    check("No decisive Dome action on 2099-01-01." in text2,
          "gavel_recap renders the quiet-day placeholder")


def test_gavel_recap_chamber_and_pass_both():
    civ = make_civ()
    dk = make_dk()
    dk["bills"]["HB-7"]["history"].append(["2026-07-11", "PASSED_ORIGIN", [29, 20]])
    dk["bills"]["SB-3"]["stage"] = "PASSED_BOTH"
    dk["bills"]["SB-3"]["history"].append(["2026-07-11", "PASSED_BOTH", [7, 2]])
    text, ids = sheets.gavel_recap(civ, dk, "2026-07-11")
    check("HB-7 passed the House, 29-20." in text, "gavel_recap: HB (origin) passes the House")
    check("SB-3 passed the House, 7-2." in text,
          "gavel_recap: SB-3 PASSED_BOTH resolves to the House (opposite of its Senate origin)")
    check(sorted(ids) == ["HB-7:passed_origin", "SB-3:passed_both"],
          "gavel_recap event ids for floor-stage actions")
    for a, b in _tally_pairs(text):
        check((a, b) in ((29, 20), (7, 2)), "self-guard: floor tallies match stored history")


# ================================================================ dome_desk

def test_dome_desk_one_line():
    civ = make_civ()
    dk = make_dk()
    out = sheets.dome_desk(civ, dk, "2026-07-10", beats=["Bert Demers filled Gerald."])
    check(out.startswith("At the Dome today: "), "dome_desk is one narratable wire line")
    check("\n" not in out, "dome_desk never spans multiple lines")
    check("HB-7 cleared the Roads committee, 6 votes to 3" in out,
          "dome_desk carries today's decisive docket action")
    check("Bert Demers filled Gerald." in out, "dome_desk appends caller-supplied beats")
    for a, b in _tally_pairs(out):
        check((a, b) == (6, 3), "self-guard: dome_desk tally matches docket history")


def test_dome_desk_empty_and_cap():
    civ = make_civ()
    dk = make_dk()
    out = sheets.dome_desk(civ, dk, "2099-01-01")
    check(out == "No Dome wire for 2099-01-01.", "dome_desk quiet-day placeholder")

    out2 = sheets.dome_desk(civ, dk, "2026-07-10",
                             beats=[f"beat {i}" for i in range(10)], n=3)
    check(out2.count(";") == 2, "dome_desk caps at n items (n-1 separators)")


# ================================================================ election_sheet

def test_election_sheet_tracked_only_numeric():
    revealed = {
        "pct_in": 61,
        "races": {
            "H-03": {"tally": [1121, 1002], "wave": 2, "status": "leaning"},
            "H-14": {"tally": [800, 300], "wave": 2, "status": "called"},
            "H-22": {"tally": [50, 3000], "wave": 1, "status": "rainout"},
        },
    }
    out = sheets.election_sheet(61, revealed, tracked_id="H-03")
    check("61% of precincts in." in out, "election_sheet renders pct_in")
    check("TRACKED RACE H-03: 1121-1002, leaning." in out,
          "election_sheet renders the tracked race's numeric tally")
    # one-thread rule: no OTHER race's numeric tally is ever printed
    for rid in ("H-14", "H-22"):
        block = out
        check(f"{rid} called" in block or f"{rid} delayed by a rain-out precinct" in block,
              f"election_sheet surfaces {rid} as a status word")
        check("800-300" not in block and "50-3000" not in block,
              f"self-guard/one-thread: {rid}'s tally never printed (untracked race)")


def test_election_sheet_new_calls_and_overlay():
    prev = {"pct_in": 30, "races": {"H-03": {"tally": [400, 380], "wave": 1, "status": "too-early"},
                                     "H-14": {"tally": [200, 80], "wave": 1, "status": "leaning"}}}
    now = {"pct_in": 70, "races": {"H-03": {"tally": [1121, 1002], "wave": 2, "status": "leaning"},
                                    "H-14": {"tally": [900, 350], "wave": 2, "status": "called"}}}
    civ = make_civ()
    out = sheets.election_sheet(2000, now, tracked_id="H-03", prev_revealed=prev, civ=civ)
    check("NEW CALLS: H-14 called." in out, "election_sheet reports only the newly-called race")
    new_calls_block = out.split("NEW CALLS:")[1]
    check("H-03" not in new_calls_block,
          "election_sheet: the tracked race (unchanged status) doesn't reappear in NEW CALLS")
    check("APPROVAL OVERLAY: 46.2, a 3-day streak." in out,
          "election_sheet overlays the approval streak per design")


def test_election_sheet_tracked_missing():
    out = sheets.election_sheet(0, {"pct_in": 0, "races": {}}, tracked_id="H-99")
    check("TRACKED RACE: too early to call." in out,
          "election_sheet falls back cleanly when the tracked race isn't in `revealed` yet")


# ================================================================ run

for _name, _fn in sorted(list(globals().items())):
    if _name.startswith("test_") and callable(_fn):
        _fn()

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
