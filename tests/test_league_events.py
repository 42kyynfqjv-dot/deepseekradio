"""Row 6 tests — trade deadline reveal clock + draft night, house style.

Plain python3, PASS/FAIL counters, exit code. Runs against a tmp cwd for the
record()-to-disk cases so no live sidecar is ever touched. Determinism and
reveal-clock monotonicity are the load-bearing properties; the quiet-deadline
case is exercised explicitly (a deadline with zero trades is a valid show).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.league import deadline as D          # noqa: E402
from src.league import draftday as DD         # noqa: E402

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


# --- fixtures ---------------------------------------------------------------

NAMES = {"mtl": "Montreal Apologies", "nyg": "New York Gridlock",
         "tbr": "Thunder Bay Regrets", "hfx": "Halifax Fog Advisories",
         "ssk": "Saskatoon Static"}

PLAYERS = {"players": {
    "mtl-11": {"name": "Gil Vantassel", "team": "mtl"},
    "mtl-12": {"name": "Otis Follett", "team": "mtl"},
    "tbr-09": {"name": "Bram Skeete", "team": "tbr"},
    "nyg-14": {"name": "Cy Marchetti", "team": "nyg"},
    "hfx-07": {"name": "Reid Kessling", "team": "hfx"},
}}

TX = [
    {"type": "trade", "from": "tbr", "to": "nyg", "out": ["tbr-09"],
     "in": ["nyg-14"], "note": "change of scenery", "date": "2026-11-01"},
    {"type": "trade", "from": "mtl", "to": "nyg", "out": ["mtl-11", "mtl-12"],
     "in": ["nyg-14"], "note": "cap dump", "date": "2026-11-01"},
    {"type": "trade", "from": "hfx", "to": "mtl", "out": ["hfx-07"],
     "in": [], "note": "change of scenery", "date": "2026-11-08"},
    {"type": "coach_fired", "team": "ssk", "old": "A", "new": "B",
     "note": "fired", "date": "2026-11-01"},
]

STANDINGS = {
    "mtl": {"w": 30, "l": 10, "otl": 5, "gp": 45},   # best
    "nyg": {"w": 20, "l": 20, "otl": 5, "gp": 45},
    "tbr": {"w": 10, "l": 30, "otl": 5, "gp": 45},   # worst
    "hfx": {"w": 25, "l": 15, "otl": 5, "gp": 45},
    "ssk": {"w": 15, "l": 25, "otl": 5, "gp": 45},
}


# --- deadline ---------------------------------------------------------------

WIN = 3600
plan = D.day_plan(TX, "2026-11-01", WIN, "s7")
check(not plan["quiet"], "deadline: Nov 1 has trades, not quiet")
check(len(plan["reveals"]) == 2, "deadline: only the 2 Nov-1 TRADES planned "
      "(coach firing + other-date trade excluded)")
offs = [r["offset"] for r in plan["reveals"]]
check(offs == sorted(offs), "deadline: reveals are offset-sorted")
check(all(0 <= o < WIN for o in offs), "deadline: offsets inside window")

# determinism
plan2 = D.day_plan(TX, "2026-11-01", WIN, "s7")
check(json.dumps(plan) == json.dumps(plan2), "deadline: day_plan deterministic")

# reveal_at monotonic: prefix only grows with cursor
prev = 0
mono = True
seen = []
for c in range(0, WIN + 200, 60):
    r = D.reveal_at(plan, c)
    if len(r) < prev:
        mono = False
    prev = len(r)
    seen.append(len(r))
check(mono, "deadline: reveal_at count is non-decreasing in cursor")
check(D.reveal_at(plan, WIN + 10000) == [t for t in
      [r["trade"] for r in plan["reveals"]]],
      "deadline: everything revealed once cursor passes the window")
check(D.reveal_at(plan, -5) == [], "deadline: nothing revealed before t=0")

# sheet resolves keys->names and pids->player names
full = D.reveal_at(plan, WIN)
sh = D.sheet(full, PLAYERS, NAMES)
check("Thunder Bay Regrets" in sh and "New York Gridlock" in sh,
      "deadline: sheet resolves team keys to on-air names")
check("Bram Skeete" in sh and "Gil Vantassel" in sh,
      "deadline: sheet resolves player ids to names")
# the Nov-8 trade sends a player for nothing coming back -> future considerations
nov8 = D.day_plan(TX, "2026-11-08", WIN, "s7")
sh8 = D.sheet(D.reveal_at(nov8, WIN), PLAYERS, NAMES)
check("future considerations" in sh8,
      "deadline: empty return side reads as future considerations")

# verify: a read naming only revealed teams passes
good = ["Big day: the Regrets sent a piece to the Gridlock, and the "
        "Apologies made a cap dump move to Gridlock."]
check(D.verify(good, full, NAMES), "deadline: verify passes on revealed teams")
# a read naming a NON-revealed team fails
bad = ["Word is the Saskatoon Static are shopping their captain."]
check(not D.verify(bad, full, NAMES),
      "deadline: verify rejects an unrevealed team (ssk not in any trade)")

# --- deadline quiet day -----------------------------------------------------
qplan = D.day_plan(TX, "2026-12-25", WIN, "s7")
check(qplan["quiet"] and qplan["reveals"] == [],
      "deadline: a date with no trades is a valid QUIET plan")
check(D.reveal_at(qplan, WIN) == [], "deadline: quiet plan reveals nothing")
qsh = D.sheet([], PLAYERS, NAMES)
check("board is quiet" in qsh, "deadline: quiet sheet says the board is quiet")
check(D.verify(["Quiet one tonight, folks. Nothing to report."], [], NAMES),
      "deadline: verify passes a truthful quiet read")
check(not D.verify(["The Apologies just landed a blockbuster!"], [], NAMES),
      "deadline: verify rejects an invented trade on a quiet board")

# also: an empty transactions list is fine
check(D.day_plan([], "2026-11-01", WIN, "s7")["quiet"],
      "deadline: empty tx list -> quiet")
# window_secs == 0 degenerate
z = D.day_plan(TX, "2026-11-01", 0, "s7")
check(all(r["offset"] == 0 for r in z["reveals"]),
      "deadline: zero window -> all offsets 0 (no crash)")


# --- draft class ------------------------------------------------------------

cls = DD.draft_class(7)
check(len(cls) == 32, "draft: class is 32 prospects")
check(all(p["age"] in (18, 19) for p in cls), "draft: all prospects age 18-19")
check(all(p["by"] == 7 - p["age"] for p in cls), "draft: by derived from age")
poss = {p["pos"] for p in cls}
check(poss == {"C", "LW", "RW", "LD", "RD", "G"},
      "draft: positions balanced across all six slots")
check(sum(1 for p in cls if p["pos"] == "G") >= 1
      and sum(1 for p in cls if p["pos"] == "G") <= 5,
      "draft: goalies a small share")
check(len({p["name"] for p in cls}) == 32, "draft: all prospect names unique")
check(all(p["scouting"] for p in cls), "draft: every prospect has scouting")
check(json.dumps(DD.draft_class(7)) == json.dumps(cls),
      "draft: draft_class deterministic in season")
check(DD.draft_class(8) != cls, "draft: different season -> different class")

# --- order (reverse standings) ---------------------------------------------
ordr = DD.order(STANDINGS)
check(ordr[0] == "tbr", "draft: worst team (tbr) picks first")
check(ordr[-1] == "mtl", "draft: best team (mtl) picks last")
check(set(ordr) == set(STANDINGS), "draft: order covers every team once")

# --- picks plan + reveal clock ---------------------------------------------
pplan = DD.picks_plan(cls, ordr, WIN, "s7")
check(len(pplan["picks"]) == len(ordr), "draft: one first-round pick per team")
poffs = [p["offset"] for p in pplan["picks"]]
check(poffs == sorted(poffs) and len(set(poffs)) == len(poffs),
      "draft: pick offsets strictly increasing (draft goes in order)")
check(pplan["picks"][0]["team"] == "tbr"
      and pplan["picks"][0]["prospect"]["rank"] == 1,
      "draft: pick 1 = worst team gets the #1-ranked prospect")

prev = 0
mono = True
for c in range(0, WIN + 200, 30):
    r = DD.reveal_at(pplan, c)
    if len(r) < prev:
        mono = False
    prev = len(r)
check(mono, "draft: reveal_at non-decreasing in cursor")

revealed = DD.reveal_at(pplan, poffs[2])   # first three picks in
check(len(revealed) == 3, "draft: three picks revealed at pick-3 offset")
dsh = DD.sheet(revealed, NAMES)
check("Thunder Bay Regrets" in dsh, "draft: sheet resolves team key to name")
check(revealed[0]["prospect"]["name"] in dsh,
      "draft: sheet names the drafted prospect")
check("Pick 1:" in dsh, "draft: sheet numbers the picks")
check("on the clock" in DD.sheet([], NAMES),
      "draft: empty board sheet says on the clock")

# verify: revealed teams/prospects pass, unrevealed fail
gtext = [f"With the first pick the Regrets take {revealed[0]['prospect']['name']}."]
check(DD.verify(gtext, revealed, NAMES), "draft: verify passes revealed pick")
# first three picks are tbr, ssk, nyg (reverse standings); hfx is unrevealed
btext = ["The Halifax Fog Advisories are on the clock next."]
check(not DD.verify(btext, revealed, NAMES),
      "draft: verify rejects an unrevealed team")
# prospect guard with full_class: naming a not-yet-picked prospect fails
later = cls[10]     # rank 11, not in first 3 revealed
lsurname = later["name"].split()[-1]
check(not DD.verify([f"Word is {lsurname} is the pick here."],
                    revealed, NAMES, full_class=cls),
      "draft: verify(full_class) rejects an unrevealed prospect surname")


# --- record() to disk: atomic + idempotent ----------------------------------
prev_cwd = os.getcwd()
with tempfile.TemporaryDirectory() as td:
    os.chdir(td)
    try:
        body = DD.record(7, STANDINGS)
        f = Path("data/league/draft-s7.json")
        check(f.exists(), "draft: record writes draft-s7.json")
        on_disk = json.loads(f.read_text())
        check(on_disk == body, "draft: returned body matches file")
        check(on_disk["season"] == 7 and len(on_disk["class"]) == 32,
              "draft: recorded body has season + full class")
        check(on_disk["round1"][0]["team"] == "tbr",
              "draft: recorded round1 opens with the worst team")
        check(len(on_disk["round1"]) == len(STANDINGS),
              "draft: round1 has a pick per team")
        # idempotent: a second record returns the SAME canon (even if we pass
        # different standings — the earlier board already aired and wins)
        body2 = DD.record(7, {k: {"w": 40, "l": 0, "otl": 0, "gp": 40}
                              for k in STANDINGS})
        check(body2 == body, "draft: record is idempotent — canon frozen")
        # prospects are NOT written to a players sidecar
        check(not Path("data/league/players-s7.json").exists(),
              "draft: record does not touch the roster sidecar")
        # no leftover tmp files
        check(not list(Path("data/league").glob("*.tmp.*")),
              "draft: atomic write leaves no tmp files")
    finally:
        os.chdir(prev_cwd)


print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
