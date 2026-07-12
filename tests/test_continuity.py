"""Continuity fixtures: break promises get kept, early goodbyes get caught,
handoffs stay untouched.  Run:  python3 tests/test_continuity.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import continuity as CN

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def L(text, speaker="Roz"):
    return {"speaker": speaker, "voice": "af_bella", "speed": 1.0, "text": text}


# break promise -> wants_break, line untouched
out, wb = CN.enforce([L("We'll be right back after this."), L("Sure.")])
check(wb is True, "break promise detected")
check(out[0]["text"].startswith("We'll"), "promise line kept verbatim")

out, wb = CN.enforce([L("Anyway, the tribunal resumes."), L("Objection!")])
check(wb is False, "no promise, no break")

# premature sign-off replaced; co-host reply survives
out, wb = CN.enforce([L("That's our show, goodnight everybody!"),
                      L("Wait, we have two hours left.", "Peach")])
check(out[0].get("_enforced") is True, "sign-off replaced")
check("show" not in out[0]["text"].lower(), "replacement is a continuation")
check(out[1]["text"].startswith("Wait"), "reply line untouched")

# the handoff beat may say goodbye
out, wb = CN.enforce([L("That's all for tonight — Vivian, you're up.")],
                     handoff=True)
check(not out[0].get("_enforced"), "handoff goodbye untouched")

# both at once: promise fulfilled AND rogue goodbye caught
out, wb = CN.enforce([L("Quick break, then more — see you tomorrow folks!")])
check(wb is True and out[0].get("_enforced") is True, "mixed line handled")

# show clock lines
check("Do NOT sign off" in CN.show_clock_line(45), "long-clock forbids wrap")
check("handoff is coming" in CN.show_clock_line(6), "short-clock warns")


# --- the numbers ritual: a ritual, not a tic --------------------------------
RIT = "Seven. Nineteen. Four. Four. Zero. Eleven."
RIT2 = "7... 19... 4... 4... 0..."
INTRO = "And now... the numbers."
check(CN.is_numbers_ritual(RIT), "spelled read-out detected")
check(CN.is_numbers_ritual(RIT2), "digit read-out detected")
check(CN.is_numbers_ritual(INTRO), "throw to the ritual detected")
for ok in ("Tug Halloran has 17 points in 8 games.",
           "The numbers don't lie, folks.",
           "One more thing about the toasters.",
           "It was four in the morning when the geese moved."):
    check(not CN.is_numbers_ritual(ok), f"ordinary talk kept: {ok[:30]!r}")

W = lambda txt: {"speaker": "The Watcher", "voice": "am_onyx", "text": txt}
beat = [W("The crosswalk button connects to the toasters."), W(RIT),
        W("Think about it.")]
out, did = CN.numbers_guard(beat, allowed=False)
check(len(out) == 3 and out[1].get("_enforced") and not did,
      "off-cadence ritual replaced, beat length kept")
check(out[1]["speaker"] == "The Watcher", "replacement keeps the speaker")
check(not CN.is_numbers_ritual(out[1]["text"]),
      "replacement itself trips nothing")
out2, did2 = CN.numbers_guard(beat, allowed=True)
check(out2[1]["text"] == RIT and did2, "owned ritual airs and stamps clock")
out3, did3 = CN.numbers_guard([W("Just theory talk.")], allowed=True)
check(not did3, "owned beat without a ritual does not stamp the clock")

print(f"\ncontinuity {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
