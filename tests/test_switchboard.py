"""Switchboard fixtures: calls end cleanly and completely, both sides.

The prime rule under test: the guard repairs toward two-sided coherence —
it never airs a host talking to a caller whose lines were dropped. Wraps
need the caller to actually fall silent; budget overruns cut the whole
beat after an aired goodbye; unannounced callers get the announcement
injected; pacing and budgets are code-owned.

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

# --- a real hangup: wrap-tell and the caller stays silent --------------------
lines = [H("Line two, you're on The Night Shift."),
         C("Hi Vivian, I dreamed my teeth were filing cabinets."),
         H("Let's open those drawers together."),
         C("They were all labeled 'later'."),
         H("Thanks for the call, Darla. Sleep will find you."),
         H("The night rolls on.")]
out, st = SW.enforce(lines, None, host=HOST)
check(len(out) == 6, f"clean call airs untouched (got {len(out)})")
check(st["status"] == "wrapped" and st["name"] == "Darla",
      "wrap with silent caller ends the call")
check(st["calls_done"] == 1, "one call on the meter")

# --- a mid-call pleasantry must NOT amputate the conversation ----------------
# (the Eugene incident: 'take care' matched, every later caller line dropped,
#  the host kept counseling dead air)
pleasant = [H("You're on the air."),
            C("I can't stop thinking about the email."),
            H("Take care out there — but first, what does it say?"),
            C("Two sentences. That's all it is."),
            H("Sometimes the small ones are the hardest.")]
outP, stP = SW.enforce(pleasant, None, host=HOST)
check(len(outP) == 5, f"pleasantry keeps the call two-sided (got {len(outP)})")
check(stP["status"] == "live", "call continues past the pleasantry")
check(stP["lines_used"] == 2, "both caller lines counted against budget")

# --- no resurrection across beats: an isolated straggler is a ghost ---------
beat2 = [H("Anyway, where was I."),
         C("It's Darla again, about the cabinets.")]
out2, st2 = SW.enforce(beat2, st, host=HOST)
check(len(out2) == 1, "isolated wrapped-caller line dropped")
check(st2["status"] == "wrapped", "state stays wrapped")

# --- ...but a CONTINUED conversation un-wraps instead of going one-sided ----
beat2b = [C("Wait — sorry, one more thing about the drawers.", name="Darla"),
          H("Alright, Darla, one more."),
          C("The bottom one was unlocked the whole time."),
          H("It usually is.")]
out2b, st2b = SW.enforce(beat2b, st, host=HOST)
check(len(out2b) == 4, f"premature wrap re-opens, nothing dropped "
      f"(got {len(out2b)})")
check(st2b["status"] == "live", "call runs long instead of going one-sided")
check(st2b["lines_used"] == st["lines_used"] + 2,
      "re-opened call keeps counting against the SAME budget")
check(st2b["calls_done"] == st["calls_done"], "re-open is not a new call")

# --- a NEW caller with a proper greeting is welcome --------------------------
beat3 = [H("Line one, you're on the air."),
         C("Hi, first time caller.", name="Gus")]
out3, st3 = SW.enforce(beat3, st, host=HOST)
check(len(out3) == 2 and st3["name"] == "Gus" and st3["status"] == "live",
      "fresh greeting admits a new caller")
check(st3["calls_done"] == st["calls_done"] + 1, "new call increments meter")

# --- a NEW caller with NO greeting gets the announcement INJECTED -----------
# (the 'Hi, uh, first-time caller' incident: previously eaten whole)
cold = [H("The night is long, friends."),
        C("Hi, uh, first-time caller. I just found you flipping around.",
          name="Miriam"),
        H("Welcome in. What's keeping you up?")]
out4, st4 = SW.enforce(cold, st, host=HOST)
inj = [ln for ln in out4 if ln.get("_enforced")]
check(len(out4) == 4 and len(inj) == 1, "missing announcement injected")
check("Miriam" in inj[0]["text"] and not inj[0].get("phone"),
      "injection is the host announcing the caller by name")
check(out4.index(inj[0]) < [i for i, l in enumerate(out4)
                            if l.get("phone")][0],
      "announcement airs BEFORE the caller's first line")
check(st4["name"] == "Miriam" and st4["status"] == "live",
      "cold caller admitted properly")

# --- cold caller from a clean slate also gets announced ----------------------
out5, st5 = SW.enforce([C("Is this the station? Am I on?", name="Lou"),
                        H("You're with us, Lou.")], None, host=HOST)
check(any(ln.get("_enforced") for ln in out5),
      "announce injected even with no prior state")
check(st5["calls_done"] == 1, "meter counts the cold call")

# --- budget overflow: wrap injected, then the WHOLE beat is cut --------------
long = [H("You're on the air.")] + \
    [C(f"And another thing, part {i}.") for i in range(15)] + \
    [H("Mm-hm."), H("And how did that make you feel?")]
out6, st6 = SW.enforce(long, None, budget=6, host=HOST)
callers = [ln for ln in out6 if ln.get("phone")]
inj6 = [ln for ln in out6 if ln.get("_enforced")]
check(len(callers) == 6, f"caller capped at budget (got {len(callers)})")
check(len(inj6) == 1 and "Thanks for the call" in inj6[0]["text"],
      "host wrap injected once")
check(out6[-1] is inj6[0],
      "beat CUT at the wrap — no host lines to a dead caller after it")
check(st6["status"] == "wrapped", "budget overflow ends the call")

# --- caller saying goodnight, then silent: terminal --------------------------
bye = [H("You're on."),
       C("Thank you, Vivian. I think I can actually sleep now. Goodnight."),
       H("Goodnight. The Frequency keeps the light on.")]
outB, stB = SW.enforce(bye, None, host=HOST)
check(len(outB) == 3 and stB["status"] == "wrapped",
      "caller's own goodbye ends the call")
# ...but a goodbye with the caller still talking after is NOT terminal
bye2 = [H("You're on."),
        C("I should let you go... but one more thing."),
        H("Go on."),
        C("The hallway in the dream was my old school.")]
outB2, stB2 = SW.enforce(bye2, None, host=HOST)
check(stB2["status"] == "live" and len(outB2) == 4,
      "caller goodbye mid-thought does not amputate")

# --- live continuation state carries, hosts never touched --------------------
mid = [C("So the goose looked at me."), H("As they do.")]
out7, st7 = SW.enforce(mid, {"name": "Darla", "status": "live",
                             "lines_used": 3, "calls_done": 1}, host=HOST)
check(len(out7) == 2, "live call flows untouched")
check(st7["lines_used"] == 4 and st7["status"] == "live", "line count carries")

# --- prompt lines read authoritatively ---------------------------------------
p1 = SW.prompt_line({"name": "Darla", "status": "live", "lines_used": 4})
check("ON THE LINE" in p1 and "Darla" in p1, "live prompt names the caller")
check("NEARLY SPENT" not in p1, "no early wrap pressure at 4/12")
p1b = SW.prompt_line({"name": "Darla", "status": "live", "lines_used": 10})
check("NEARLY SPENT" in p1b, "75% budget escalates to land the ending")
p2 = SW.prompt_line({"name": "Darla", "status": "wrapped", "lines_used": 9})
check("CLEAR" in p2 and "CANNOT return" in p2, "wrapped prompt forbids return")
check("CLEAR" in SW.prompt_line(None), "no-state prompt is clear")
p3 = SW.prompt_line(None, 24, {"target": 12, "done": 3})
check("about 12 calls" in p3 and "3 taken" in p3,
      "pacing prompt carries the show's call target")
p4 = SW.prompt_line({"name": "X", "status": "wrapped", "lines_used": 24},
                    24, {"target": 4, "done": 4})
check("phones are done" in p4, "pacing closes the phones at target")

# --- announcement discipline --------------------------------------------------
# the reported stutter: announce, re-announce, THEN the caller — one survives
stutter = [H("We've got a caller on line two."),
           H("Hold that thought — there's a caller!"),
           C("Hi Vivian, it's about my mailbox."),
           H("Tell me about the mailbox.")]
out8, _ = SW.enforce(stutter, None, host=HOST)
ann = [ln for ln in out8 if not ln.get("phone") and not ln.get("_enforced")
       and ("caller" in ln["text"].lower())]
check(len(ann) == 1, f"exactly one announcement survives (got {len(ann)})")
check(out8[0].get("_enforced") is True, "the earlier duplicate is replaced")
check(any(ln["text"].startswith("Hi Vivian") for ln in out8),
      "the call itself untouched")

# a single clean announcement + caller is never touched
clean = [H("Caller on line one — you're on."), C("Hey there, night owls.")]
out9, _ = SW.enforce(clean, None, host=HOST)
check(not any(ln.get("_enforced") for ln in out9), "clean announce untouched")

# an undelivered trailing tease is still replaced
tease = [H("Anyway, the tribunal continues."),
         H("Hold that thought — there's a caller!")]
out10, _ = SW.enforce(tease, None, host=HOST)
check(out10[1].get("_enforced") is True, "undelivered tease replaced")
check("tribunal" in out10[0]["text"], "non-tease line untouched")

# soft forward-looking teases are legit (the wrap's 'phone lines are opening')
soft = [H("Stick around — the phone lines are opening after the break.")]
out11, _ = SW.enforce(soft, None, host=HOST)
check(not out11[0].get("_enforced"), "soft forward tease untouched")

# --- phantom calls: one-sided phone theater about nobody ---------------------
# the Twyla incident: greet, hang up, hang up again — caller never spoke
phantom = [H("Twyla, you're on the air."),
           H("No — you know what, I'm hanging up. Click."),
           H("She called back. And I hung up again."),
           H("The numbers don't lie, folks.")]
outT, _ = SW.enforce(phantom, None, host=HOST)
enforced = sum(1 for ln in outT if ln.get("_enforced"))
check(enforced >= 2, f"phantom-call lines replaced (got {enforced})")
check("numbers" in outT[3]["text"], "non-call line untouched")
# ...but a cross-beat wrap of a REAL carried caller is legit
carry = [H("Alright, thanks for the call, Darla — sleep well.")]
outQ, stQ = SW.enforce(carry, {"name": "Darla", "status": "live",
                               "lines_used": 5, "calls_done": 1}, host=HOST)
check(not outQ[0].get("_enforced"), "cross-beat wrap of live caller kept")
check(stQ["status"] == "wrapped", "and it ends the call")

# --- handoff to a second caller mid-beat counts on the meter -----------------
two = [H("Line one — you're on."),
       C("Quick one: the bridge hums in D.", name="Ana"),
       H("Noted. Line two, go ahead."),
       C("It's actually D flat.", name="Bo")]
outW, stW = SW.enforce(two, None, host=HOST)
check(stW["name"] == "Bo" and stW["calls_done"] == 2,
      "caller handoff counts two distinct calls")

print(f"\nswitchboard {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
