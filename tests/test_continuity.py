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

print(f"\ncontinuity {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
