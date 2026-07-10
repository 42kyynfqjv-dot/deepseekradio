"""Canonguard fixtures: the facts table builds correctly, scope-gating is a
proven pass-through off the arc/followup beats it's flagged for, correct
lines survive untouched no matter how densely a beat is populated with canon
(the prime directive, property-tested), aired-stamp spoilers get blocked,
and every catch reaches for the register-appropriate neutral bank.

Run directly (no pytest needed):  python3 tests/test_canonguard.py
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import canonguard as cg

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
# Straight from arcs-census-continuity.md §2's own worked examples.

CIV = {
    "residents": {
        "cv-maureen-1": {
            "name": "Maureen", "surname": "Kowalczyk",
            "gender": "f", "hood": "the pharmacy-lot blocks",
            "problem": "a sock-drawer ceasefire with her upstairs neighbor",
            "status": "active", "register": "mundane",
            "facts": [
                {"fid": "f1", "kind": "relationship", "key": "neighbor",
                 "value": "upstairs", "aired": "2026-06-18"},
                {"fid": "f3", "kind": "outcome", "key": "sock_ceasefire",
                 "value": "a truce, holding", "aired": "2026-07-02"},
                {"fid": "f4", "kind": "quantity", "key": "weeks",
                 "value": 3, "aired": "2026-06-18"},
            ],
            "follow_up": {"due": "2026-07-23", "show": "culture_vulture",
                          "question": "how's the sock ceasefire holding?",
                          "consumed": False},
            "arc_ref": None,
        },
        "cv-doreen-2": {
            "name": "Doreen", "surname": "Vachon",
            "gender": "f", "hood": "the roundabout blocks",
            "status": "active", "register": "mundane",
            "facts": [],
        },
    },
}

ARCS = {
    "arcs": {
        "arc-roundabout-fern-3": {
            "title": "The Roundabout Fern",
            "premise": "someone left a potted fern in the Mile Zero roundabout",
            "register": "mundane", "stage": "COMPLICATION", "stage_idx": 2,
            "cast": {"civilians": ["cv-doreen-2"],
                     "canon": ["the roundabout", "Toivo Ostberg"]},
            "facts": [
                {"fid": "a1", "kind": "place", "key": "location",
                 "value": "the Mile Zero roundabout", "aired": "2026-07-04"},
                {"fid": "a2", "kind": "name", "key": "fern_name",
                 "value": "Sheila", "aired": "2026-07-06"},
                {"fid": "a3", "kind": "outcome", "key": "payoff",
                 "value": "the town votes to make Sheila the roundabout's "
                          "official tenant", "aired": None},
            ],
            "status": "active",
        },
        "arc-dreamcourt-9": {
            "title": "The Case of the Borrowed Ladder",
            "register": "dreamcourt", "stage": "OPEN", "stage_idx": 0,
            "cast": {"civilians": [], "canon": []},
            "facts": [
                {"fid": "d1", "kind": "outcome", "key": "verdict",
                 "value": "the ladder stays with Nils", "aired": None},
            ],
            "status": "active",
        },
    },
}

MAUREEN_FOLLOWUP = cg.build_canon_facts(
    ARCS, CIV, scope_ids=["cv-maureen-1"], scope="followup")
FERN_ARC = cg.build_canon_facts(
    ARCS, CIV, scope_ids=["arc-roundabout-fern-3"], scope="arc")
DREAM_ARC = cg.build_canon_facts(
    ARCS, CIV, scope_ids=["arc-dreamcourt-9"], scope="arc")
NONE_SCOPE = cg.build_canon_facts(ARCS, CIV, scope_ids=(), scope="none")

# ============================================================== A. facts table

subj = MAUREEN_FOLLOWUP["subjects"]["cv-maureen-1"]
check(MAUREEN_FOLLOWUP["scope"] == "followup", "scope stamped as given")
check("maureen" in MAUREEN_FOLLOWUP["names_ok"], "resident first name in names_ok")
check("kowalczyk" in MAUREEN_FOLLOWUP["names_ok"], "resident surname in names_ok")
check("Maureen" in MAUREEN_FOLLOWUP["full_names"], "display name in full_names")
check(subj["register"] == "mundane", "resident register carried through")
check(("relationship", "neighbor", "upstairs") in subj["aired"],
      "relationship fact digested as aired")
check(("outcome", "sock_ceasefire", "a truce, holding") in subj["aired"],
      "outcome fact digested as aired")
check(("place", "hood", "the pharmacy-lot blocks") in subj["aired"],
      "stored hood folded in as an aired place/hood fact (friction note)")
check(("quantity", "weeks", 3) in subj["aired"], "quantity fact digested")
check(subj["pending"] == [], "no pending facts for maureen in this fixture")

fern = FERN_ARC["subjects"]["arc-roundabout-fern-3"]
check(("place", "location", "the Mile Zero roundabout") in fern["aired"],
      "arc place fact digested as aired")
check(("name", "fern_name", "Sheila") in fern["aired"], "arc name fact aired")
check(("outcome", "payoff",
       "the town votes to make Sheila the roundabout's official tenant")
      in fern["pending"], "unaired arc payoff lands in pending, not aired")
check("toivo ostberg" in FERN_ARC["names_ok"],
      "arc canon cast full name in names_ok")
check("doreen" in FERN_ARC["names_ok"], "arc's cast civilian name in names_ok")
check("sheila" in FERN_ARC["names_ok"], "arc's own name-fact value in names_ok")
check("the" not in fern["tokens"],
      "canon-phrase splitting drops stopwords from the mention-token set (bug fix)")
check({"roundabout", "toivo", "ostberg"} <= fern["tokens"],
      "canon-phrase splitting keeps the real content tokens")
check(FERN_ARC["register"] == "mundane", "arc register digested")
check(len(FERN_ARC["banned_register_words"]) > 0,
      "mundane register bans the conspiracy lexicon")

check(DREAM_ARC["register"] == "dreamcourt", "dreamcourt arc register digested")

check(NONE_SCOPE["scope"] == "none", "empty scope_ids builds scope=none")
check(NONE_SCOPE["subjects"] == {}, "scope=none has no subjects")

# ============================================================ B. scope-gating

fresh_lines = [
    L("Bouchard scores again, unbelievable!"),
    L("Maureen's neighbor lives downstairs now, total flip."),   # would be a
    L("The fern's official name is Daisy, everyone agrees."),    # contradiction
    L("Nothing on record ties to any of this at all."),          # in scope
]
out_none = cg.enforce_canon(fresh_lines, NONE_SCOPE)
check(out_none == fresh_lines, "scope=none is a byte-identical pass-through")
check(all(o is i for o, i in zip(out_none, fresh_lines)),
      "scope=none preserves line object identity (no copying/mutation)")
check(all("_enforced" not in o for o in out_none),
      "scope=none never stamps _enforced")

# same two contradiction-shaped lines, now WITH scope -> must be caught,
# proving the pass-through above wasn't just "nothing ever matches"
in_scope_check = cg.enforce_canon(
    [fresh_lines[1]], MAUREEN_FOLLOWUP)
check(in_scope_check[0].get("_enforced") is True,
      "the same line IS caught once scope is on (pass-through isn't just dead code)")

# a non-arc beat literally never receives scope_ids/scope="arc" from the desk;
# build_canon_facts(..., scope_ids=(), scope="none") is the wiring contract.
default_facts = cg.build_canon_facts(ARCS, CIV)
check(default_facts["scope"] == "none",
      "build_canon_facts defaults to scope=none for ordinary call-in")

# ======================================================== C. replace-never-cut
# Prime directive: a correct line is never touched. Property-test across many
# generated "safe" lines against a densely-populated in-scope facts table.

random.seed(20260709)

SAFE_TEMPLATES = [
    "Maureen says the ceasefire is holding, three weeks running now.",
    "Her neighbor upstairs still isn't budging on the sock thing.",
    "Doreen dropped by the roundabout again today, nothing new there.",
    "Sheila the fern is doing fine, still just sitting pretty.",
    "The Mile Zero roundabout looks tidy this morning.",
    "Toivo Ostberg waved at us on his walk, nice guy.",
    "We might swing back to Maureen's story next week.",
    "Could be the fern gets a name change someday, who knows.",
    "Kowalczyk family's been quiet, no news to report.",
    "Just a normal Tuesday around here, nothing to add.",
]

safe_lines = [L(t) for t in SAFE_TEMPLATES]
combined_facts = cg.build_canon_facts(
    ARCS, CIV, scope_ids=["cv-maureen-1", "arc-roundabout-fern-3"], scope="arc")
out_safe = cg.enforce_canon(safe_lines, combined_facts)

untouched = sum(1 for o, i in zip(out_safe, safe_lines) if o is i)
check(untouched == len(safe_lines),
      f"every correct line survives byte-identical ({untouched}/{len(safe_lines)} untouched)")
check(all("_enforced" not in o for o in out_safe),
      "no correct line is ever stamped _enforced")

# fuzz: random shuffles/combinations of safe clauses, still no false positive
SAFE_CLAUSES = [
    "the fern is fine", "Maureen's doing okay", "still upstairs",
    "the roundabout looks nice", "nothing new to report", "Doreen said hi",
    "Toivo Ostberg stopped by", "just an ordinary day", "the truce holds",
    "no complaints here",
]
false_positives = 0
for _ in range(200):
    k = random.randint(1, 4)
    text = ", ".join(random.sample(SAFE_CLAUSES, k)) + "."
    ln = L(text)
    res = cg.enforce_canon([ln], combined_facts)[0]
    if res is not ln:
        false_positives += 1
        print(f"  (fuzz) unexpectedly touched: {text!r} -> {res}")
check(false_positives == 0,
      f"fuzz: 200 random safe-clause combinations, {false_positives} false positives")

# replace-never-cut: line COUNT is always preserved, mixed safe+bad batch
mixed = safe_lines + [
    L("Maureen's neighbor lives downstairs now, total flip."),
    L("They've named the fern Daisy this week, official now."),
    L("It's official: the fern votes were four weeks in the making."),
]
out_mixed = cg.enforce_canon(mixed, combined_facts)
check(len(out_mixed) == len(mixed), "enforce_canon never cuts a line (count preserved)")
check(sum(1 for o in out_mixed if o.get("_enforced")) >= 2,
      "the planted bad lines in the mixed batch got caught")
check(input_untouched := sum(
    1 for o, i in zip(out_mixed[:len(safe_lines)], safe_lines) if o is i)
      == len(safe_lines),
      "planting bad lines alongside safe ones doesn't touch the safe ones")

# input lines are never mutated in place
original = L("Maureen's neighbor lives downstairs now, total flip.")
copy_before = dict(original)
cg.enforce_canon([original], MAUREEN_FOLLOWUP)
check(original == copy_before, "enforce_canon never mutates its input dicts")

# ======================================================= D. contradiction catches

t1 = cg.enforce_canon(
    [L("Maureen's neighbor lives downstairs now, total flip.")], MAUREEN_FOLLOWUP)
check(t1[0]["_enforced"] is True, "relationship-family contradiction caught")
check(t1[0]["text"] != "Maureen's neighbor lives downstairs now, total flip.",
      "contradiction text replaced")
check("downstairs" not in t1[0]["text"].lower(),
      "replacement doesn't repeat the false claim")

t2 = cg.enforce_canon(
    [L("Maureen's over on Window-4 row these days.")], MAUREEN_FOLLOWUP)
check(t2[0]["_enforced"] is True, "hood/geography flip caught")
check(t2[0]["text"] in cg._GEO["mundane"] or
      any(t2[0]["text"] == tpl.format(name="Maureen") for tpl in cg._GEO["mundane"]),
      "geography catch pulls from the geography template bank")

t3 = cg.enforce_canon(
    [L("They've named the fern Daisy this week, everyone loves it.")], FERN_ARC)
check(t3[0]["_enforced"] is True, "name-fact contradiction caught (fern's real name is Sheila)")

t4 = cg.enforce_canon(
    [L("Maureen tells us the ceasefire lasted four weeks now, steady as she goes.")],
    MAUREEN_FOLLOWUP)
check(t4[0]["_enforced"] is True, "quantity contradiction caught (real tally is 3, not 4)")

t5 = cg.enforce_canon(
    [L("Maureen says three weeks now and counting, steady as ever.")],
    MAUREEN_FOLLOWUP)
check(t5[0] is not None and "_enforced" not in t5[0],
      "matching quantity (3 weeks, the real value) is NOT a contradiction")

# ============================================================ E. spoiler catch

spoiler_line = L("It's official, folks: the town votes and Sheila's the "
                  "roundabout's tenant, done deal.")
ts = cg.enforce_canon([spoiler_line], FERN_ARC)
check(ts[0]["_enforced"] is True,
      "settled-marker + pending-fact content overlap is caught as a pre-air spoiler")
check(ts[0]["text"] != spoiler_line["text"], "spoiler line replaced")

# same content, no settled marker -> legal advancing-the-story beat, passes
teaser_line = L("Folks keep talking about whether Sheila stays at the roundabout.")
tt = cg.enforce_canon([teaser_line], FERN_ARC)
check(tt[0] is teaser_line,
      "unsettled speculation about the same pending fact passes whole")

# modal/hypothetical framing passes even with a settled marker present
modal_line = L("Maybe someday it'll be official that Sheila stays for good.")
tm = cg.enforce_canon([modal_line], FERN_ARC)
check(tm[0] is modal_line, "modal/hypothetical framing passes whole (MODAL short-circuits)")

# an unrelated arc's pending fact never spoils under a different arc's scope
cross = cg.enforce_canon(
    [L("It's official: the ladder stays with Nils after all.")], FERN_ARC)[0]
check(cross.get("_enforced") is not True,
      "a pending fact only spoils under ITS OWN arc's scope, not an unrelated one")

# the same line, now correctly in the dreamcourt arc's own scope, IS a spoiler
own_scope = cg.enforce_canon(
    [L("It's official: the ladder stays with Nils after all.")], DREAM_ARC)[0]
check(own_scope.get("_enforced") is True,
      "the ladder verdict spoils once it's actually in the dreamcourt arc's scope")

# ==================================================== F. register-appropriate templates

dream_spoiler = cg.enforce_canon(
    [L("It's official: the ladder stays with Nils after all.")], DREAM_ARC)[0]
check(dream_spoiler["text"] in cg._SPOILER["dreamcourt"],
      "dreamcourt-register spoiler pulls from the dreamcourt neutral bank, not mundane")
check(dream_spoiler["text"] not in cg._SPOILER["mundane"] or
      dream_spoiler["text"] in cg._SPOILER["dreamcourt"],
      "dreamcourt bank text doesn't leak the mundane phrasing")

mundane_spoiler = cg.enforce_canon([spoiler_line], FERN_ARC)[0]
check(mundane_spoiler["text"] in cg._SPOILER["mundane"],
      "mundane-register spoiler pulls from the mundane neutral bank")

civ_arc = cg.build_canon_facts(
    {"arcs": {"arc-civic-1": {"title": "Zoning Fight", "register": "civic",
                              "cast": {"civilians": [], "canon": []},
                              "facts": [{"fid": "c1", "kind": "outcome",
                                         "key": "vote", "value": "the zoning passes",
                                         "aired": None}]}}},
    {"residents": {}}, scope_ids=["arc-civic-1"], scope="arc")
civ_spoiler = cg.enforce_canon(
    [L("It's official: the zoning passes tonight, no debate needed.")], civ_arc)[0]
check(civ_spoiler["text"] in cg._SPOILER["civic"],
      "civic-register spoiler pulls from the civic neutral bank")

# a register the template banks don't have an entry for falls back to mundane
weird_arc = cg.build_canon_facts(
    {"arcs": {"arc-sports-1": {"title": "Rink Feud", "register": "sports",
                               "cast": {"civilians": [], "canon": []},
                               "facts": [{"fid": "s1", "kind": "outcome",
                                          "key": "score", "value": "home wins",
                                          "aired": None}]}}},
    {"residents": {}}, scope_ids=["arc-sports-1"], scope="arc")
weird_spoiler = cg.enforce_canon(
    [L("It's official: the rink feud ends with home wins tonight, done deal.")],
    weird_arc)[0]
check(weird_spoiler["text"] in cg._SPOILER["mundane"],
      "a register with no dedicated bank falls back to the mundane templates")

# register-violation catch (conspiracy leak into a mundane arc)
consp_line = L("Some say it's all a cover-up, they don't want you to know.")
tc = cg.enforce_canon([consp_line], FERN_ARC)
check(tc[0]["_enforced"] is True, "conspiracy-lexicon leak caught in a mundane arc")
check(tc[0]["text"] in cg._REGISTER["mundane"],
      "register-violation replacement pulls from the mundane register bank")

# template rotation is stable (md5-hashed on original text, not random per call)
same1 = cg.enforce_canon([spoiler_line], FERN_ARC)[0]["text"]
same2 = cg.enforce_canon([spoiler_line], FERN_ARC)[0]["text"]
check(same1 == same2, "template pick is stable across repeated calls (md5, not hash())")

# ============================================================ G. phantom names

near = L("Maureeen's neighbor lives upstairs, all's well as ever.")
tn = cg.enforce_canon([near], MAUREEN_FOLLOWUP)
check(tn[0].get("_enforced") is True, "near-miss phantom spelling caught and fixed")
check("Maureen" in tn[0]["text"] and "Maureeen" not in tn[0]["text"],
      "phantom name corrected to the real scoped name, in place (not a full-sentence replace)")

far = L("Bartholomew's neighbor moved out over the weekend sometime.")
tf = cg.enforce_canon([far], MAUREEN_FOLLOWUP)
check(tf[0] is far,
      "a genuinely new walk-on far from every scoped name is never renamed into a resident")

known = L("Maureen's neighbor lives upstairs, everything's fine.")
tk = cg.enforce_canon([known], MAUREEN_FOLLOWUP)
check(tk[0] is known, "an exact, already-correct known name is left completely alone")


if __name__ == "__main__":
    print(f"\ncanonguard: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
