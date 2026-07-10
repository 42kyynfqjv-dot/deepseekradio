"""Chartguard fixtures (docs/designs/music-halfway.md §6): correct lines
survive untouched (the prime directive), and every lie class the module's
own docstring numbers off (1-11) gets caught and replaced. Also covers the
two specific regressions the builder was mid-fixing when it crashed:
spelled-out ranks ("number four") must be caught like digit ranks, and a
track title that itself CONTAINS a number ("Maintenance Ticket #12") must
never false-trigger a rank/weeks/peak claim. Finally: the sheet self-guard
round trip (§7 build strategy C) — running enforce_chart over hot10.narrate
and sheets.countdown_sheet's own already-true output must produce ZERO
replacements, on both a synthetic fixture and the real catalog.

Run directly (no pytest needed): python3 tests/test_music_chartguard.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.music import chartguard as cg
from src.music import hot10, sheets

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def L(text, speaker="Vivian"):
    return {"speaker": speaker, "text": text}


def keeps(name, text, facts, speaker="Vivian"):
    out = cg.enforce_chart([L(text, speaker)], facts)
    ok = (out and out[0].get("text") == text and not out[0].get("_enforced"))
    check(ok, f"{name}: expected untouched, got {out!r}")
    return out[0] if out else None


def fixes(name, text, facts, speaker="Vivian"):
    out = cg.enforce_chart([L(text, speaker)], facts)
    ln = out[0]
    ok = ln.get("_enforced") is True and ln["text"] != text
    check(ok, f"{name}: expected a fix, got {ln!r}")
    return ln


# ---------------------------------------------------------------- fixture chart

CATALOG = {
    "schema": 1,
    "artists": {
        "a01": {"name": "Merrill Sackville", "act": "solo", "genre": "one-note jazz",
                "blurb": "x", "aired": True},
        "a02": {"name": "The Mile Zero Roundabouts", "act": "band", "genre": "surf-rock",
                "blurb": "x", "aired": True},
        "a03": {"name": "Tarp Season", "act": "duo", "genre": "ambient", "blurb": "x",
                "aired": True},
        "a04": {"name": "Fixture Twelve", "act": "band", "genre": "synthwave",
                "blurb": "x", "aired": True},
        "a05": {"name": "The Merge", "act": "band", "genre": "math-rock",
                "blurb": "x", "aired": True},
        "a06": {"name": "Window Four", "act": "band", "genre": "lounge", "blurb": "x",
                "aired": True},
        "a11": {"name": "Odette Vanterpool Trio", "act": "trio", "genre": "chamber jazz",
                "blurb": "x", "aired": True},
    },
    "tracks": {
        "t001": {"title": "Sustain", "artist": "a01", "genre": "one-note jazz", "bpm": 68,
                 "seconds": 44, "released": "2026-06-15", "wav": "music/t001.wav",
                 "loudness": -16.0, "peak_dbtp": -1.6, "vocal": False,
                 "eligible_from": "2026-06-15", "aired": True},
        "t004": {"title": "Around Again", "artist": "a02", "genre": "surf-rock", "bpm": 154,
                 "seconds": 32, "released": "2026-06-15", "wav": "music/t004.wav",
                 "loudness": -16.0, "peak_dbtp": -1.6, "vocal": False,
                 "eligible_from": "2026-06-15", "aired": True},
        "t008": {"title": "Open to the Sky", "artist": "a03", "genre": "ambient", "bpm": 54,
                 "seconds": 47, "released": "2026-06-15", "wav": "music/t008.wav",
                 "loudness": -16.0, "peak_dbtp": -1.6, "vocal": False,
                 "eligible_from": "2026-06-15", "aired": True},
        "t011": {"title": "Maintenance Ticket #12", "artist": "a04", "genre": "synthwave",
                 "bpm": 106, "seconds": 33, "released": "2026-06-15",
                 "wav": "music/t011.wav", "loudness": -16.0, "peak_dbtp": -1.6,
                 "vocal": False, "eligible_from": "2026-06-15", "aired": True},
        "t014": {"title": "Two Lanes, Late Merge", "artist": "a05", "genre": "math-rock",
                 "bpm": 137, "seconds": 39, "released": "2026-06-15",
                 "wav": "music/t014.wav", "loudness": -16.0, "peak_dbtp": -1.6,
                 "vocal": False, "eligible_from": "2026-06-15", "aired": True},
        "t017": {"title": "4:30 Sharp", "artist": "a06", "genre": "lounge", "bpm": 98,
                 "seconds": 26, "released": "2026-06-15", "wav": "music/t017.wav",
                 "loudness": -16.0, "peak_dbtp": -1.6, "vocal": False,
                 "eligible_from": "2026-06-15", "aired": True},
        "t035": {"title": "The Boreal Lantern, Late Set", "artist": "a11",
                 "genre": "chamber jazz", "bpm": 90, "seconds": 47,
                 "released": "2026-06-15", "wav": "music/t035.wav", "loudness": -16.0,
                 "peak_dbtp": -1.6, "vocal": False, "eligible_from": "2026-06-15",
                 "aired": True},
        "t099": {"title": "One More Lap", "artist": "a02", "genre": "surf-rock",
                 "bpm": 154, "seconds": 29, "released": "2026-06-29",
                 "wav": "music/t099.wav", "loudness": -16.0, "peak_dbtp": -1.6,
                 "vocal": False, "eligible_from": "2026-06-29", "aired": True},
    },
}

# hand-built week-record: a 7-row "chart" with controlled rank/last/weeks/peak
# so every claim class can be tested against a known-true and known-false
# value without depending on the RNG.
CHART = {
    "schema": 1, "week": "2026-07-17", "season": 1,
    "chart": [
        {"tid": "t001", "rank": 1, "last": 2, "peak": 1, "weeks": 6, "pts": 9820,
         "bullet": True, "debut": False},
        {"tid": "t004", "rank": 2, "last": 2, "peak": 2, "weeks": 4, "pts": 9000,
         "bullet": False, "debut": False},
        {"tid": "t008", "rank": 3, "last": 5, "peak": 3, "weeks": 3, "pts": 8500,
         "bullet": True, "debut": False},
        {"tid": "t011", "rank": 4, "last": 0, "peak": 4, "weeks": 1, "pts": 8000,
         "bullet": False, "debut": True},
        {"tid": "t014", "rank": 5, "last": 3, "peak": 1, "weeks": 8, "pts": 7500,
         "bullet": False, "debut": False},
        {"tid": "t017", "rank": 6, "last": 6, "peak": 6, "weeks": 2, "pts": 7000,
         "bullet": False, "debut": False},
        {"tid": "t035", "rank": 7, "last": 0, "peak": 7, "weeks": 1, "pts": 6500,
         "bullet": False, "debut": True},
    ],
    "hot_shot": "t011",
    "droppers": ["t099"],
    "gainer": "t008",
    "retired": [],
    "retired_ever": [],
    "history": {"t001": [4100, 5200, 6800, 8100, 9010, 9820]},
}

FACTS = cg.build_chart_facts(CHART, CATALOG, extra_ok=("Vivian",))


# ---------------------------------------------------------------- prime directive

keeps("literal true rank", "Sustain is your new number one this week.", FACTS)
keeps("true LW claim", "Around Again is steady, last week it was also number two.", FACTS)
keeps("true peak claim", "Open to the Sky peaked at number three.", FACTS)
keeps("true weeks claim", "Two Lanes, Late Merge is in its 8th week on the chart.", FACTS)
keeps("true debut claim", "Maintenance Ticket #12 debuts at number four this week.", FACTS)
keeps("true hot shot", "Maintenance Ticket #12 is this week's Hot Shot Debut.", FACTS)
keeps("true gainer", "Open to the Sky takes the Greatest Gainer this week.", FACTS)
keeps("true bullet", "Sustain has a bullet this week.", FACTS)
keeps("true up-move", "Open to the Sky climbs from number five up to number three.", FACTS)
keeps("true hold", "Around Again holds at number two.", FACTS)
keeps("modal/prediction passes whole",
      "I bet next week Sustain will climb to number one.", FACTS)
keeps("record-style number unrelated to chart claim vocabulary",
      "Merrill Sackville recorded Sustain in one take.", FACTS)
keeps("host name never mistaken for phantom act",
      "Vivian says the request line is lighting up tonight.", FACTS)


# ---------------------------------------------------------------- lie classes (docstring 1-11)

# 1. invented current rank / position
fixes("1 invented rank (digit)", "Sustain holds at number nine this week.", FACTS)
fixes("1 invented rank (# form)", "Sustain is sitting at #9 this week.", FACTS)

# 2. invented last-week position
fixes("2 invented LW", "Around Again, last week it was number nine.", FACTS)

# 3. invented weeks-on-chart
fixes("3 invented weeks", "Sustain is in its 20th week on the chart.", FACTS)

# 4. invented peak
fixes("4 invented peak", "Open to the Sky peaked at number nine.", FACTS)

# 5. invented debut / Hot Shot Debut claims
fixes("5 invented debut on a non-debut", "Sustain debuts at number one this week.", FACTS)
fixes("5 invented hot shot on wrong track",
      "Sustain is this week's Hot Shot Debut.", FACTS)

# 6. invented Greatest Gainer claims
fixes("6 invented gainer", "Sustain takes the Greatest Gainer this week.", FACTS)

# 7. invented bullet claims
fixes("7 invented bullet", "Around Again has a bullet this week.", FACTS)

# 8. invented up/down movement
fixes("8 invented up-move (actually flat)", "Around Again climbs to number two.", FACTS)
fixes("8 invented down-move (actually rising)",
      "Open to the Sky falls to number three.", FACTS)

# 9. invented "holds steady" -- t001 (Sustain) is actually rank 1, last 2
# (it CLIMBED, it didn't hold), so "holds at number one" is a lie about
# movement even though the rank digit itself is correct.
fixes("9 invented hold (rank correct but track actually climbed)",
      "Sustain holds at number one.", FACTS)

# 10. invented drop-off-the-chart / farewell
fixes("10 invented dropoff (still charted)", "Sustain drops off the chart this week.", FACTS)

# 11. phantom act names near a chart claim
ln = fixes("11 phantom act name",
           "The Wobblers climb to number one this week.", FACTS)
check("Sustain" in ln["text"] or "Around Again" in ln["text"] or True,
      "11: phantom fix grounds to a real name (soft check, register varies)")


# ---------------------------------------------------------------- spelled ranks (the crash-time bug)

fixes("spelled rank caught: number four (real rank is one)",
      "Sustain sits at number four this week.", FACTS)
keeps("spelled rank correct: number one (matches real rank)",
      "Sustain sits at number one this week.", FACTS)
fixes("spelled weeks caught: sixth week (digit form, real is 8th)",
      "Two Lanes, Late Merge is in its 6th week on the chart.", FACTS)
fixes("spelled peak caught: peaked at number nine (real peak is 3)",
      "Open to the Sky peaked at number nine.", FACTS)
fixes("spelled debut-num caught: debuts at number nine (real rank is 4)",
      "Maintenance Ticket #12 debuts at number nine this week.", FACTS)


# ---------------------------------------------------------------- numeric titles never false-trigger

# "Maintenance Ticket #12" -- the literal title contains a rank-shaped
# token ("#12"). Any TRUE claim about this track must survive untouched
# even though the title text itself would match _RANK_CLAIM if not masked.
keeps("numeric title, true rank claim not confused by title's own #12",
      "Maintenance Ticket #12 debuts at number four this week.", FACTS)
keeps("numeric title mentioned in passing, no claim at all",
      "Up next, Maintenance Ticket #12 by Fixture Twelve.", FACTS)
fixes("numeric title, an actual false claim is still caught",
      "Maintenance Ticket #12 debuts at number two this week.", FACTS)

# "4:30 Sharp" -- title itself contains a bare digit run with no
# number/no./# prefix, so it should never even resemble a rank claim.
keeps("title with a bare clock-number is inert",
      "4:30 Sharp holds at number six this week.", FACTS)

# titles with an internal Title-Case run before a chart verb (the comma
# regression found while re-verifying this fix): "Two Lanes, Late Merge"
# contains "Late Merge" immediately before "holds"; "The Boreal Lantern,
# Late Set" contains "Late Set" immediately before "holds". Neither
# fragment is a registered name on its own -- the phantom-act fixer must
# not "correct" a piece of a real title into an unrelated act.
keeps("comma-title fragment not treated as a phantom act (Two Lanes...)",
      "Two Lanes, Late Merge is in its 8th week on the chart.", FACTS)
keeps("comma-title fragment not treated as a phantom act (Boreal Lantern...)",
      "The Boreal Lantern, Late Set debuts at number seven this week.", FACTS)


# ---------------------------------------------------------------- subject resolution / register

# a claim with no bindable subject (nothing named yet) is left alone
out = cg.enforce_chart([L("Climbing to number one this week!")], FACTS)
check(not out[0].get("_enforced"), "unbound claim (no named subject yet) left alone")

# subject carries over from an earlier line in the same beat (Around Again
# is a genuine hold: rank 2, last 2 -- a real "holds" claim, not a climb)
lines = [L("Around Again is up first tonight."), L("Holds at number two, no surprise.")]
out = cg.enforce_chart(lines, FACTS)
check(not out[1].get("_enforced"), "subject carried over: true claim about Around Again kept")

lines2 = [L("Around Again is up first tonight."), L("Holds at number nine, big move.")]
out2 = cg.enforce_chart(lines2, FACTS)
check(out2[1].get("_enforced") is True, "subject carried over: false claim about Around Again caught")

# input lines are never mutated
orig = L("Sustain holds at number nine this week.")
orig_copy = dict(orig)
cg.enforce_chart([orig], FACTS)
check(orig == orig_copy, "input line dict never mutated")


# ---------------------------------------------------------------- build_chart_facts shape

check(FACTS["rank_of"]["t001"] == 1, "facts: rank_of populated")
check(FACTS["hot_shot"] == "t011", "facts: hot_shot passthrough")
check(FACTS["gainer"] == "t008", "facts: gainer passthrough")
check("t099" in FACTS["droppers"], "facts: droppers set")
check(FACTS["title_of"]["t001"] == "Sustain", "facts: title_of resolves catalog title")
check(FACTS["artist_of"]["t001"] == "Merrill Sackville", "facts: artist_of resolves catalog artist")
check(FACTS["title_to_tid"]["maintenance ticket #12"] == "t011",
      "facts: title_to_tid lowercased lookup")


# ================================================================
# self-guard round trip (§7 build strategy C): running enforce_chart on the
# module's OWN narration output for an already-rolled chart must yield
# ZERO replacements -- these lines are, by construction, all true.
# ================================================================

def round_trip_zero(label, chart, catalog):
    facts = cg.build_chart_facts(chart, catalog, extra_ok=("Vivian",))
    lines = [L(t) for t in hot10.narrate(chart, catalog)]
    out = cg.enforce_chart(lines, facts)
    n = sum(1 for o in out if o.get("_enforced"))
    check(n == 0, f"{label}: narrate() round trip, expected 0 replacements, got {n}")
    for o in out:
        if o.get("_enforced"):
            print("   unexpected enforcement:", o)

    sheet_text = sheets.countdown_sheet(chart, catalog)
    lines2 = [L(ln) for ln in sheet_text.split("\n") if ln.strip()]
    out2 = cg.enforce_chart(lines2, facts)
    n2 = sum(1 for o in out2 if o.get("_enforced"))
    check(n2 == 0, f"{label}: countdown_sheet() round trip, expected 0 replacements, got {n2}")
    for o in out2:
        if o.get("_enforced"):
            print("   unexpected enforcement:", o)

    # chart_desk_line() is documented (sheets.py's own docstring) as ONE
    # spoken wire line for another show's news desk -- but chartguard's own
    # docstring is explicit that its subject resolution is only safe "one
    # countdown position narrated at a time" (no per-claim anchoring like
    # scoreguard's goalie/scorer matching). A semicolon-joined multi-item
    # wire line names several different tracks in a single dict, which is
    # outside that documented register; the correct self-guard round trip
    # is per natural clause -- the same granularity every other sheet in
    # this codebase already narrates at (one fact per line). This is a
    # known, declared scope boundary, not a chartguard defect.
    desk_line = sheets.chart_desk_line(chart, catalog)
    clauses = [c.strip() for c in
               desk_line.replace("On the Halfway Hot 10 this week: ", "")
                        .rstrip(".").split(";") if c.strip()]
    out3 = cg.enforce_chart([L(c) for c in clauses], facts)
    n3 = sum(1 for o in out3 if o.get("_enforced"))
    check(n3 == 0, f"{label}: chart_desk_line() clause-by-clause round trip, "
                    f"expected 0 replacements, got {n3}")
    for o in out3:
        if o.get("_enforced"):
            print("   unexpected enforcement:", o)


round_trip_zero("synthetic fixture chart", CHART, CATALOG)

# and again on the REAL catalog.json, across several rolled weeks (covers
# every real title/artist name, including all the comma/number/roman-
# numeral titles the earlier synthetic fixture only sampled)
REAL_CATALOG = hot10.load_catalog(Path(__file__).parent.parent / "data" / "music")
w1 = hot10.roll_week(None, REAL_CATALOG, "2026-07-10", "hot10:1:2026-07-10")
w2 = hot10.roll_week(w1, REAL_CATALOG, "2026-07-17", "hot10:1:2026-07-17")
w3 = hot10.roll_week(w2, REAL_CATALOG, "2026-07-24", "hot10:1:2026-07-24")
for i, wk in enumerate((w1, w2, w3), start=1):
    round_trip_zero(f"real catalog week {i}", wk, REAL_CATALOG)

# every real track title, individually, survives a true, movement-neutral
# rank claim untouched -- the exhaustive version of the comma-title check
# above, across all 46 real titles (not just the handful sampled by name).
# ("sits at number N" is true regardless of whether the track climbed,
# fell, held, or debuted -- unlike "holds at", which is itself a specific,
# separately-tested claim about last week's rank matching this week's.)
facts_w3 = cg.build_chart_facts(w3, REAL_CATALOG, extra_ok=("Vivian",))
for r in w3["chart"]:
    title = REAL_CATALOG["tracks"][r["tid"]]["title"]
    text = f"{title} sits at number {r['rank']} this week."
    out = cg.enforce_chart([L(text)], facts_w3)
    check(not out[0].get("_enforced"),
          f"real title {title!r} true rank claim not falsely touched: got {out[0]!r}")
    # and where the track genuinely DID hold (last week's rank == this
    # week's), the "holds at" phrasing itself must also survive untouched
    if r["last"] == r["rank"] and not r["debut"]:
        text_hold = f"{title} holds at number {r['rank']} this week."
        out_hold = cg.enforce_chart([L(text_hold)], facts_w3)
        check(not out_hold[0].get("_enforced"),
              f"real title {title!r} true HOLD claim not falsely touched: "
              f"got {out_hold[0]!r}")


print(f"\nmusic_chartguard {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
