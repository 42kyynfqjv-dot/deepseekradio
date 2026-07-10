"""Census fixtures: identity is derived and stable, follow-ups fire on the
right show in the 14-28d window, the desk's returning-caller preference and
name-sustainability rules hold, and pruning demotes without ever reusing a
name.

Run directly (no pytest needed):  python3 tests/test_census.py
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import census
from src.performers import _spare_voice

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def fresh():
    return {"schema": 1, "residents": {}, "used_names": [], "roster_by_hood": {}}


# --- derive-don't-store: same name -> same id/hood/voice, forever -----------
st = fresh()
r1 = census.mint("Maureen", "2026-06-18", "culture_vulture", st["residents"])
st["residents"][r1["id"]] = r1
check(r1["id"] == "cv-maureen-1", "id is cv-<slug>-<n>")
check(r1["hood"] in census.HOODS, "hood drawn from the locked 12-hood bank")
check(census.hood_of(r1["id"]) == r1["hood"], "hood is a pure function of id")
check(census.hood_of("cv-maureen-1") == census.hood_of("cv-maureen-1"),
      "hood derivation is stable across calls")
check("voice" not in r1, "voice is NEVER stored on the record")
check(census.voice_of("Maureen") == _spare_voice("Maureen"),
      "voice_of re-derives the exact spare voice")
# a returning caller keeps her name -> identical voice by construction
census.record_appearance(r1, "2026-07-02", "night_shift", "the truce holds")
check(census.voice_of(r1["name"]) == _spare_voice("Maureen"),
      "returning caller re-enters on the identical voice")
check(len(r1["appearances"]) == 2 and "night_shift" in r1["shows"],
      "record_appearance stamps a second aired appearance")

# gender pins for a bank name; ambiguous name -> None but never crashes
rr = census.mint("Ruth", "2026-06-18", "morning_scramble", st["residents"])
check(rr["gender"] == "f", "desk-bank name derives its gender by construction")

# --- new_id never collides --------------------------------------------------
a = census.mint("Al", "2026-06-18", "morning_scramble", st["residents"])
st["residents"][a["id"]] = a
b = census.mint("Al", "2026-06-19", "night_shift", st["residents"])
check(a["id"] != b["id"] and b["id"] == "cv-al-2", "second Al gets a distinct id")

# --- add_fact: append-only slots, aired canon immutable, placeholder freezes -
census.add_fact(r1, "relationship", "neighbor", "upstairs", "2026-06-18")
census.add_fact(r1, "relationship", "neighbor", "upstairs", "2026-06-18")
check(sum(1 for f in r1["facts"] if f["key"] == "neighbor") == 1,
      "identical fact is not appended twice")
census.add_fact(r1, "relationship", "neighbor", "her sister", "2026-07-01")
check([f for f in r1["facts"] if f["key"] == "neighbor"][0]["value"] == "upstairs",
      "aired canon is never rewritten by a contradicting value")
census.add_fact(r1, "outcome", "sock", "a truce, pending", None)   # placeholder
census.add_fact(r1, "outcome", "sock", "a truce, holding", "2026-07-02")  # freeze
sock = [f for f in r1["facts"] if f["key"] == "sock"][0]
check(sock["value"] == "a truce, holding" and sock["aired"] == "2026-07-02",
      "unaired placeholder freezes to the aired value on air")

# --- follow-up scheduler: 14-28d, keyed to the home show --------------------
rng = random.Random("fu-seed")
r1["problem"] = "the sock ceasefire"
census.schedule_follow_up(r1, "2026-07-02", rng)
fu = r1["follow_up"]
from datetime import date as _d
gap = (_d.fromisoformat(fu["due"]) - _d.fromisoformat("2026-07-02")).days
check(14 <= gap <= 28, f"follow-up due in the 14-28d window (got {gap})")
check(fu["show"] == "night_shift", "follow-up keyed to the record's home show")
check("sock ceasefire" in fu["question"], "question templated over the problem")
# never stacks a second pending follow-up
before = fu["due"]
census.schedule_follow_up(r1, "2026-07-05", rng)
check(r1["follow_up"]["due"] == before, "no second pending follow-up is stacked")

# --- due_follow_ups: unconsumed, due, show-matched, capped by the desk -------
due_here = census.due_follow_ups(st, fu["due"], "night_shift")
check(any(r["id"] == r1["id"] for r in due_here), "due follow-up surfaces on air")
check(census.due_follow_ups(st, fu["due"], "morning_scramble") == [],
      "follow-up does not surface on the wrong show")
check(census.due_follow_ups(st, "2026-07-02", "night_shift") == [],
      "follow-up is invisible before its due date")
census.consume_follow_up(r1)
check(census.due_follow_ups(st, fu["due"], "night_shift") == [],
      "a consumed follow-up never re-surfaces")

# --- returning pick: due follow-up preferred; else seeded ~1-in-4 -----------
st2 = fresh()
m = census.mint("Maureen", "2026-06-18", "night_shift", st2["residents"])
m["problem"] = "the sock ceasefire"
census.schedule_follow_up(m, "2026-06-18", random.Random("x"))
st2["residents"][m["id"]] = m
pick = census.returning_pick(st2, m["follow_up"]["due"], "night_shift",
                             random.Random("q"))
check(pick and pick["followup"] and pick["name"] == "Maureen",
      "a due follow-up is always the returning pick, as a check-in")
# with no follow-up due, the ~1-in-4 preference: measure the rate over 4000 rolls
st3 = fresh()
for nm in ("Ruth", "Al", "Doreen", "Vern", "Bev"):
    rec = census.mint(nm, "2026-06-01", "morning_scramble", st3["residents"])
    st3["residents"][rec["id"]] = rec
hits = sum(1 for i in range(4000)
           if census.returning_pick(st3, "2026-06-10", "the_handover",
                                     random.Random(f"r{i}")) is not None)
rate = hits / 4000
check(0.20 <= rate <= 0.30, f"spontaneous reuse fires ~1-in-4 (got {rate:.2f})")
check(census.returning_pick(fresh(), "2026-06-10", "x", random.Random("z")) is None,
      "no residents -> no returning pick, desk mints fresh")

# --- name sustainability: banks minus active, hood distinguisher on dry ------
st4 = fresh()
seen = set()
for i in range(400):  # far past a single gender pool
    nm = census.new_caller_name(st4, random.Random(f"n{i}"), want="f")
    check(nm not in st4["used_names"], "minted name never collides with used")
    st4["used_names"].append(nm)
    st4["residents"][census.new_id(nm, st4["residents"])] = census.mint(
        nm, "2026-06-01", "morning_scramble", st4["residents"])
    seen.add(nm)
check(any(" from " in n for n in seen),
      "pool exhaustion yields 'FirstName from the {hood}' distinguishers")
check(all(n.split(" from ")[1] in census.HOODS for n in seen if " from " in n),
      "distinguisher hood is drawn from the locked bank")
# a fresh mint can never take a name an active resident already holds
st5 = fresh()
held = census.mint("Doreen", "2026-06-01", "morning_scramble", st5["residents"])
st5["residents"][held["id"]] = held
for i in range(200):
    nm = census.new_caller_name(st5, random.Random(f"c{i}"), want="f")
    check(nm.split(" from ")[0] != "Doreen" or " from " in nm,
          "fresh mint never reuses an active resident's bare name")

# --- pruning / dormancy: demote without name reuse --------------------------
st6 = fresh()
cold = census.mint("Vera", "2026-01-01", "morning_scramble", st6["residents"])
cold["appearances"][-1]["date"] = "2026-01-01"
st6["residents"][cold["id"]] = cold
st6["used_names"].append("Vera")
warm = census.mint("Winnie", "2026-01-01", "night_shift", st6["residents"])
census.schedule_follow_up(warm, "2026-06-25", random.Random("w"))  # pending return
st6["residents"][warm["id"]] = warm
census.prune(st6, "2026-07-01")
check(cold["status"] == "dormant", "a cold, unbooked resident is demoted dormant")
check(warm["status"] == "active", "a resident with a pending return is kept active")
check("Vera" in st6["used_names"] and cold["id"] in st6["residents"],
      "dormancy never reuses the name nor deletes the record")
check(census.due_follow_ups(st6, "2026-07-01", "morning_scramble") == [],
      "dormant residents drop out of the follow-up promoter")
# a new call revives a dormant resident on the same identity
census.record_appearance(cold, "2026-07-02", "morning_scramble", "back again")
check(cold["status"] == "active", "a return revives a dormant resident")

# --- digest_for_guard: only scoped ids, aired vs unaired slots --------------
tables = census.digest_for_guard(st, [r1["id"]])
check("maureen" in tables["names_ok"], "scoped resident name is guard-ok")
check(tables["hoods"][r1["id"]] == r1["hood"], "scoped hood exposed to the guard")
check((r1["id"], "relationship", "neighbor") in tables["aired_keys"],
      "an aired fact is an aired key")
missing = census.digest_for_guard(st, ["cv-nobody-9"])
check(missing["names_ok"] == set(), "unknown scoped id contributes nothing")
check(rr["name"].lower() not in tables["names_ok"],
      "out-of-scope resident is NOT in the guard tables (fresh walk-ons stay free)")

# --- IO round-trip: atomic save/load, corrupt live falls back to .bak -------
import tempfile
tmpdir = Path(tempfile.mkdtemp())
orig = census._PATH
try:
    census._PATH = tmpdir / "civilians.json"
    census.save(st2)
    got = census.load()
    check(got["residents"].keys() == st2["residents"].keys(),
          "save/load round-trips residents")
    census.save(st2)  # second save creates a good .bak
    census._PATH.write_text("{ this is not json")   # corrupt the live file
    recov = census.load()
    check(recov["residents"].keys() == st2["residents"].keys(),
          "corrupt live file falls back to .bak")
    census._PATH = tmpdir / "absent.json"
    check(census.load()["residents"] == {}, "missing file -> empty default")
finally:
    census._PATH = orig

print(f"\ncensus {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
