"""Switchboard fixtures: ghosts get dropped, budgets get wrapped, nobody
gets resurrected, and hosts are never touched.

Run directly (no pytest needed):  python3 tests/test_switchboard.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import switchboard as SW

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def H(text):
    return {"speaker": "Vivian", "voice": "af_sky", "speed": 0.95, "text": text}


def C(text, name="Darla"):
    return {"speaker": name, "voice": "af_heart", "speed": 1.0,
            "text": text, "phone": True}


HOST = {"speaker": "Vivian", "voice": "af_sky", "speed": 0.95}

# --- ghost after wrap is dropped -------------------------------------------
lines = [H("Line two, you're on The Night Shift."),
         C("Hi Vivian, I dreamed my teeth were filing cabinets."),
         H("Let's open those drawers together."),
         C("They were all labeled 'later'."),
         H("Thanks for the call, Darla. Sleep will find you."),
         C("Wait, one more thing about the drawers!"),
         H("The night rolls on.")]
out, st = SW.enforce(lines, None, host=HOST)
check(len(out) == 6, f"ghost caller line dropped (got {len(out)})")
check(all("drawers!" not in ln["text"] for ln in out), "the ghost line is gone")
check(st["status"] == "wrapped" and st["name"] == "Darla", "state wrapped")

# --- no resurrection across beats without a fresh greeting ------------------
beat2 = [H("Anyway, where was I."),
         C("It's Darla again, about the cabinets.")]
out2, st2 = SW.enforce(beat2, st, host=HOST)
check(len(out2) == 1, "wrapped caller cannot return unannounced")
# ...but a NEW caller with a proper greeting is welcome
beat3 = [H("Line one, you're on the air."),
         C("Hi, first time caller.", name="Gus")]
out3, st3 = SW.enforce(beat3, st, host=HOST)
check(len(out3) == 2 and st3["name"] == "Gus" and st3["status"] == "live",
      "fresh greeting admits a new caller")

# --- budget overflow: wrap injected, overflow dropped -----------------------
long = [H("You're on the air.")] + \
    [C(f"And another thing, part {i}.") for i in range(15)]
out4, st4 = SW.enforce(long, None, budget=6, host=HOST)
callers = [ln for ln in out4 if ln.get("phone")]
inj = [ln for ln in out4 if ln.get("_enforced")]
check(len(callers) == 6, f"caller capped at budget (got {len(callers)})")
check(len(inj) == 1 and "Thanks for the call" in inj[0]["text"],
      "host wrap injected once")
check(st4["status"] == "wrapped", "budget overflow ends the call")

# --- hosts never touched; live continuation state carries -------------------
mid = [C("So the goose looked at me."), H("As they do.")]
out5, st5 = SW.enforce(mid, {"name": "Darla", "status": "live",
                             "lines_used": 3}, host=HOST)
check(len(out5) == 2, "live call flows untouched")
check(st5["lines_used"] == 4 and st5["status"] == "live", "line count carries")

# --- prompt lines read authoritatively --------------------------------------
p1 = SW.prompt_line({"name": "Darla", "status": "live", "lines_used": 4})
check("ON THE LINE" in p1 and "Darla" in p1, "live prompt names the caller")
p2 = SW.prompt_line({"name": "Darla", "status": "wrapped", "lines_used": 9})
check("CLEAR" in p2 and "CANNOT return" in p2, "wrapped prompt forbids return")
check("CLEAR" in SW.prompt_line(None), "no-state prompt is clear")

print(f"\nswitchboard {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
