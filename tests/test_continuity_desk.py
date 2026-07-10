"""Continuity-desk fixtures: the CONTINUITY DESK block renders authoritative and
canon-complete, the returning-resident identity pins name->voice, and the
beat-flagging contract tightens the guard ONLY on beats that actually surface
the assigned arc/resident (a fresh caller is never scoped).

Self-contained (fixtures inline; census/arcs/canonguard need not exist).
Run directly (no pytest needed):  python3 tests/test_continuity_desk.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import continuity_desk as cd

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def L(text, speaker="Hank Steele", phone=False):
    return {"speaker": speaker, "voice": "am_adam", "speed": 1.0,
            "text": text, "phone": phone}


# ---- fixtures (the frozen input shapes arcs.py / census.py hand the desk) ----
ARC = {
    "arc_id": "arc-roundabout-fern-3", "title": "The Roundabout Fern",
    "bid": "b3", "stage": "COMPLICATION", "day": 3,
    "directive": "the town starts leaving it tiny gifts",
    "canon": ["the fern is at the Mile Zero roundabout", "its name is Sheila",
              "Toivo Ostberg is the foreman"],
    "payoff": False, "register": "mundane",
    "cast_ids": ["cv-doreen-2"], "cast_names": ["Doreen", "Toivo Ostberg"],
    "names": ["Sheila"],
}
ARC_PAYOFF = dict(ARC, payoff=True, day=6, stage="PAYOFF",
                  directive="the town formally adopts Sheila")
FU = {
    "cid": "cv-maureen-1", "name": "Maureen", "gender": "f",
    "hood": "the pharmacy-lot blocks",
    "status_line": "her upstairs-neighbor sock ceasefire is holding",
    "question": "how's the sock ceasefire holding?",
}

# ---- canon_block: both picks -------------------------------------------------
blk = cd.canon_block(ARC, FU)
check(blk.startswith(cd.HEADER), "block opens with the authoritative header")
check("authoritative" in blk and "do not contradict" in blk, "authoritative register")
check('"The Roundabout Fern"' in blk, "arc title quoted")
check("day 3" in blk, "arc day rendered")
check("town starts leaving it tiny gifts" in blk, "tonight's directive present")
check("the fern is at the Mile Zero roundabout" in blk
      and "its name is Sheila" in blk and "Toivo Ostberg is the foreman" in blk,
      "all canon facts carried into the block")
check("Do NOT resolve the story tonight." in blk, "non-payoff beat is spoiler-locked")
check("pays off" not in blk, "non-payoff beat never says it pays off")
check("MAUREEN returns tonight" in blk, "returning resident named, uppercased")
check("the pharmacy-lot blocks" in blk, "resident hood carried")
check("sock ceasefire is holding" in blk, "resident status carried")
check("how's the sock ceasefire holding?" in blk, "follow-up question carried")
check("returning caller" in blk, "greeted AS a returning caller")

# ---- canon_block: payoff copy flips -----------------------------------------
pb = cd.canon_block(ARC_PAYOFF, None)
check("TONIGHT the story pays off" in pb, "payoff beat announces the ending")
check("Do NOT resolve" not in pb, "payoff beat drops the spoiler-lock line")
check("day 6" in pb, "payoff day rendered")

# ---- canon_block: single picks and the empty (gate-off) path ----------------
arc_only = cd.canon_block(ARC, None)
check("ARC BEAT" in arc_only and "CALL BACK" not in arc_only, "arc-only omits resident")
fu_only = cd.canon_block(None, FU)
check("CALL BACK" in fu_only and "ARC BEAT" not in fu_only, "resident-only omits arc")
check(cd.canon_block(None, None) == "", "no picks -> empty (gate-off byte-identical)")
check(cd.canon_block(None, {"name": ""}) == "", "nameless follow-up -> empty")

# ---- switchboard identity ----------------------------------------------------
ident = cd.switchboard_identity(FU)
check(ident == ("Maureen", "f"), "returning resident pins (name, gender)")
check(cd.switchboard_identity(None) is None, "no follow-up -> None (fresh mint)")
check(cd.switchboard_identity({"name": "  "}) is None, "blank name -> None")
check(cd.switchboard_identity({"name": "Al"}) == ("Al", None),
      "gender may be absent (mint pins by name alone)")

# ---- beat_scope: the flagging contract --------------------------------------
# a beat where only the resident surfaces -> followup scope, her cid only
s = cd.beat_scope(ARC, FU, [L("Maureen, welcome back!", phone=True),
                            L("Oh, the ceasefire's holding, mostly.")])
check(s["scope"] == "followup", "resident named -> followup scope")
check(s["scope_ids"] == ["cv-maureen-1"],
      "only the resident's cid scoped when the arc does not surface")

# a beat where BOTH the resident and the arc surface -> followup wins, both ids
sb = cd.beat_scope(ARC, FU, [L("Maureen, you'll love this — the fern at the "
                               "roundabout has a sign now.", phone=True)])
check(sb["scope"] == "followup", "resident outranks arc for scope label")
check(sb["scope_ids"] == ["cv-maureen-1", "arc-roundabout-fern-3", "cv-doreen-2"],
      "followup+arc ids both loaded when both surface")

# an arc beat: title/cast token present, resident absent -> arc scope
s2 = cd.beat_scope(ARC, FU, [L("Someone left a fern at the roundabout again.")])
check(s2["scope"] == "arc", "arc token (fern/roundabout) -> arc scope")
check("cv-maureen-1" not in s2["scope_ids"], "resident not scoped when absent")
check("arc-roundabout-fern-3" in s2["scope_ids"] and "cv-doreen-2" in s2["scope_ids"],
      "arc id + cast ids loaded for an arc beat")

# a cast proper noun alone triggers the arc
s3 = cd.beat_scope(ARC, FU, [L("Toivo says it's still not planted.")])
check(s3["scope"] == "arc", "cast proper noun (Toivo) triggers arc scope")
s3b = cd.beat_scope(ARC, FU, [L("They're calling the fern Sheila now.")])
check(s3b["scope"] == "arc", "extra proper noun (Sheila) triggers arc scope")

# THE SAFETY PROPERTY: an ordinary fresh caller, neither surfaced -> pass-through
s4 = cd.beat_scope(ARC, FU, [L("Ernie here, long-time listener, the potholes on "
                               "Third are eating my tires!", phone=True)])
check(s4 == {"scope": "none", "scope_ids": []},
      "fresh caller, no arc/resident token -> scope none (guard pass-through)")

# word-boundary: 'fernando' must NOT fire 'fern'; 'always' must not fire nothing
s5 = cd.beat_scope(ARC, FU, [L("My cousin Fernando always says hi.")])
check(s5["scope"] == "none", "'Fernando' does not trigger 'fern' (word boundary)")

# no assignment at all -> none (the gate-off beat loop)
s6 = cd.beat_scope(None, None, [L("Anything can be said here.")])
check(s6 == {"scope": "none", "scope_ids": []}, "no picks -> scope none")
check(cd.beat_scope(ARC, FU, []) == {"scope": "none", "scope_ids": []},
      "empty beat -> scope none")

# arc present but no follow-up assigned, resident-shaped word absent
s7 = cd.beat_scope(ARC, None, [L("The fern's got a little sign now.")])
check(s7["scope"] == "arc" and "cv-maureen-1" not in s7["scope_ids"],
      "no follow-up assigned -> never followup scope")

# ---- determinism & non-mutation --------------------------------------------
lines_in = [L("Maureen and the fern at the roundabout.", phone=True)]
before = [dict(x) for x in lines_in]
r1 = cd.beat_scope(ARC, FU, lines_in)
r2 = cd.beat_scope(ARC, FU, lines_in)
check(r1 == r2, "beat_scope deterministic")
check(cd.canon_block(ARC, FU) == blk, "canon_block deterministic")
check(lines_in == before, "beat_scope never mutates input lines")

print(f"\ncontinuity_desk {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
