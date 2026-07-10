"""Dream Court clerk fixtures: the {feeling, tool, verdict} capture contract,
the injected/mockable llm_fn with a code-owned fallback, the G/PG guard on
captured text, and the follow-up copy that names the ACTUAL tool.

Run directly (no pytest needed):  python3 tests/test_census_clerk.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import census_clerk as cc

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def J(text, **kw):
    """A judge (Vivian, non-phone) line."""
    return {"speaker": "Vivian Nightshade", "voice": "af_sky", "speed": 0.95,
            "text": text, **kw}


def C(text, name="Maureen"):
    """A caller (phone) line."""
    return {"speaker": name, "voice": "af_kore", "speed": 1.0,
            "text": text, "phone": True}


# A representative aired Dream Court case: bizarre premise, real closure.
CASE = [
    J("Dream Court is now in session. Tell me the dream."),
    C("I dreamed my socks were migrating to my husband's side of the bed, "
      "one at a time, like little deserters."),
    J("And you wake up feeling what, exactly?"),
    C("Honestly? Unseen. Like he doesn't notice me anymore."),
    J("There it is. What you're really carrying isn't the socks — it's feeling "
      "unseen by someone you love."),
    J("Here's your tool for tonight: a four-count breath. Breathe in for four, "
      "out for four, and say the feeling out loud once."),
    J("The verdict of this court: case dismissed. The socks were never the "
      "defendant. Sleep easy, Maureen."),
]


# --- llm path: injected, mockable ------------------------------------------

def good_llm(messages):
    # a well-behaved model returns strict JSON
    return json.dumps({"dreamer": "IGNORED", "feeling": "she feels unseen",
                       "tool": "a four-count breath",
                       "verdict": "case dismissed; the socks were never the defendant"})


cap = cc.clerk_pass(CASE, llm_fn=good_llm)
check(cap is not None, "llm case captured")
check(cap["dreamer"] == "Maureen", "dreamer is the caller, NOT the model's field")
check(cap["feeling"] == "she feels unseen", "feeling captured from llm")
check(cap["tool"] == "a four-count breath", "tool captured from llm")
check("case dismissed" in cap["verdict"], "verdict captured from llm")

# fenced JSON tolerated (```json ... ```)
def fenced_llm(messages):
    return "```json\n" + json.dumps(
        {"feeling": "afraid of being forgotten", "tool": "box breathing",
         "verdict": "court adjourned"}) + "\n```"


cap_f = cc.clerk_pass(CASE, llm_fn=fenced_llm)
check(cap_f and cap_f["tool"] == "box breathing", "fenced json parsed")

# --- fallback: llm None, raising, or junk -----------------------------------

cap_none = cc.clerk_pass(CASE, llm_fn=None)
check(cap_none is not None, "no-llm falls back, still captures")
check(cap_none["dreamer"] == "Maureen", "fallback dreamer set")
check(cap_none["tool"] == "a four-count breath", "fallback extracts real tool")
check(cap_none["feeling"] and "unseen" in cap_none["feeling"], "fallback feeling")
check(cap_none["verdict"] and "dismissed" in cap_none["verdict"], "fallback verdict")


def boom_llm(messages):
    raise RuntimeError("network down")


cap_boom = cc.clerk_pass(CASE, llm_fn=boom_llm)
check(cap_boom is not None and cap_boom["tool"] == "a four-count breath",
      "raising llm degrades to fallback capture")


def junk_llm(messages):
    return "sorry, I can't help with that"


cap_junk = cc.clerk_pass(CASE, llm_fn=junk_llm)
check(cap_junk is not None and cap_junk["dreamer"] == "Maureen",
      "unparseable llm reply degrades to fallback")

# fallback determinism (pure) — identical across runs
check(cc.fallback_capture(CASE) == cc.fallback_capture(CASE),
      "fallback is deterministic")

# --- no dream case -> None --------------------------------------------------

check(cc.clerk_pass([J("The Quiet Part. No caller tonight, just us.")],
                    llm_fn=good_llm) is None, "no caller -> no case (None)")
check(cc.clerk_pass([], llm_fn=None) is None, "empty lines -> None")

# tool may be None (recognition preserved, specificity lost)
no_tool = [C("I dreamed I was a filing cabinet."),
           J("What you're really carrying is a fear of being forgotten."),
           J("The verdict: case dismissed.")]
cap_nt = cc.clerk_pass(no_tool, llm_fn=None)
check(cap_nt and cap_nt["dreamer"] and cap_nt["tool"] is None,
      "no tool given -> dreamer captured, tool None")

# --- G/PG guard on captured text --------------------------------------------

check(cc.gpg_clean("this is a damn mess of a dream") ==
      "this is a darn mess of a dream", "profanity softened, not cut")
check(cc.gpg_clean("what the hell was that") == "what the heck was that",
      "hell -> heck")
check(cc.gpg_clean("") is None and cc.gpg_clean(None) is None,
      "empty/None -> None")
check(cc.gpg_clean("a dream about sexual violence") is None,
      "adult/violent field rejected to None")
long = "breathe " * 60
cleaned = cc.gpg_clean(long)
check(cleaned is not None and len(cleaned) <= 160 and not cleaned.endswith(" "),
      "over-long field clamped on a word boundary")

# the guard is actually wired into capture
def foul_llm(messages):
    return json.dumps({"feeling": "she's damn tired of it",
                       "tool": "a four-count breath", "verdict": "case closed"})


cap_foul = cc.clerk_pass(CASE, llm_fn=foul_llm)
check(cap_foul["feeling"] == "she's darn tired of it",
      "captured feeling is G/PG-cleaned")

# a G/PG-rejected field comes back None but the case still captures
def reject_llm(messages):
    return json.dumps({"feeling": "a dream about suicide", "tool": None,
                       "verdict": "case closed"})


cap_rej = cc.clerk_pass(CASE, llm_fn=reject_llm)
check(cap_rej is not None and cap_rej["feeling"] is None
      and cap_rej["verdict"] == "case closed",
      "rejected field -> None, rest of case survives")

# --- follow-up copy names the ACTUAL tool -----------------------------------

line = cc.follow_up_copy(cap)  # tool == "a four-count breath"
check("four-count breath" in line, "follow-up names the actual tool")
check("that four-count breath" in line, "article stripped -> 'that ...'")
check(line == cc.follow_up_copy(cap), "follow-up copy is deterministic")
# the canonical example from the design
check(cc.follow_up_copy({"tool": "a four-count breath"}) ==
      cc.follow_up_copy({"tool": "a four-count breath"}), "stable render")
check(any("that four-count breath holding up" in
          cc.follow_up_copy({"tool": t}) for t in
          ["a four-count breath"] * 1) or "four-count breath" in
      cc.follow_up_copy({"tool": "a four-count breath"}),
      "tool phrase woven naturally")

# with a census problem woven alongside the tool
both = cc.follow_up_copy(cap, problem="sock ceasefire")
check("sock ceasefire" in both and "four-count breath" in both,
      "follow-up weaves problem + tool when both known")

# no tool -> generic warm check-in (recognition survives)
gen = cc.follow_up_copy({"dreamer": "Al", "tool": None})
check("Dream Court" in gen, "no-tool follow-up is a generic warm check-in")
gen_prob = cc.follow_up_copy({"tool": None}, problem="the leaky faucet saga")
check("leaky faucet saga" in gen_prob, "no-tool but known problem still named")
check(cc.follow_up_copy(None) and isinstance(cc.follow_up_copy(None), str),
      "None capture -> still a usable string")

# follow-up copy is itself G/PG (problem is cleaned)
foul_prob = cc.follow_up_copy({"tool": None}, problem="the damn faucet")
check("darn" in foul_prob and "damn" not in foul_prob,
      "follow-up copy G/PG-cleans a woven problem")

# every rendered follow-up line is clean of the profanity lexicon
for t in ["a four-count breath", "box breathing", None]:
    ln = cc.follow_up_copy({"tool": t, "dreamer": "Ruth"}, problem="the fence war")
    check("damn" not in ln.lower() and "hell" not in ln.lower(),
          f"rendered follow-up clean (tool={t})")

print(f"\ncensus_clerk {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
