"""Nameguard fixtures: scrub every real-world hockey entity, touch no fiction.

Run directly (no pytest needed):  python3 tests/test_nameguard.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.nameguard import enforce_names
from src.scoreguard import build_facts
from src.livegame import FIRST_NAMES, LAST_NAMES

POOL = frozenset(w.lower() for w in FIRST_NAMES + LAST_NAMES)

GAME = {
    "home": "Montreal Apologies", "away": "New York Gridlock",
    "rosters": {
        "home": {"skaters": ["Doug Bouchard", "Erik Larsson", "Petr Novak"],
                 "goalie": "Rene Tremblay"},
        "away": {"skaters": ["Vic Marino", "Lou Costa", "Dan Ferraro"],
                 "goalie": "Otto Kranz"}},
    "refs": ["Referee Ada Cole"],
}
PBP = {"speaker": "Bucky Merle", "voice": "am_onyx", "speed": 0.97}


def L(text, speaker="Sal Tarantella"):
    return {"speaker": speaker, "voice": "am_echo", "speed": 1.0, "text": text}


def facts():
    return build_facts(GAME, [], None, mode="postgame", pbp=PBP, final=(3, 2))


def run(text):
    return enforce_names([L(text)], facts(), extra_ok=POOL)[0]


def scrubbed(text):
    return run(text).get("_enforced") is True


def kept(text):
    return "_enforced" not in run(text)


PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


# --- real entities must be scrubbed ---------------------------------------
check(scrubbed("That reminds me of Suzuki back in his prime."), "real player Suzuki")
check(scrubbed("Caufield would've buried that one."), "real player Caufield")
check(scrubbed("Reminds me of the old Canadiens dynasty."), "real team Canadiens")
check(scrubbed("Just like a Habs power play."), "real team Habs")
check(scrubbed("This is a Stanley Cup kind of night."), "trophy Stanley Cup")
check(scrubbed("He could play in the NHL, folks."), "league NHL")
check(scrubbed("A real Gretzky move there."), "legend Gretzky")
check(scrubbed("Straight out of the Maple Leafs playbook."), "multiword Maple Leafs")
check(scrubbed("Like something on Hockey Night in Canada."), "broadcaster phrase")
check(scrubbed("Beliveau used to do that."), "Canadiens legend Beliveau")

# --- fiction must survive -------------------------------------------------
check(kept("Bouchard was flying out there tonight."), "roster+pool name Bouchard")
check(kept("Tremblay stood on his head in net."), "roster goalie Tremblay")
check(kept("Old Vachon used to say the same thing."), "off-roster pool name Vachon")
check(kept("Leclair had a heck of a shift."), "off-roster pool name Leclair")
check(kept("Thanks for the call, Darla. Great question."), "invented caller Darla")
check(kept("That's hall of fame stuff right there."), "common word 'hall'")
check(kept("Good point, Bucky, good point."), "common word 'point'")
check(kept("And now for the three stars of the game."), "core vocab 'stars'")
check(kept("The Apologies take it here in Montreal."), "home team + city")
check(kept("Referee Ada Cole waves it off."), "ref name")

# --- replacement hygiene --------------------------------------------------
r = run("Reminds me of Suzuki, honestly.")
check(r["speaker"] == "Sal Tarantella", "replacement keeps speaker")
check(r["voice"] == "am_echo", "replacement keeps voice")
check(not enforce_names([r], facts(), extra_ok=POOL)[0].get("_enforced")
      or enforce_names([r], facts(), extra_ok=POOL)[0]["text"] == r["text"],
      "replacement is idempotent (trips no check)")


# --- news guard: real brands never survive to air ---------------------------
from src.nameguard import enforce_news  # noqa: E402


def news_run(text):
    return enforce_news([{"speaker": "Frequency News", "voice": "am_onyx",
                          "text": text}])[0]


for bad in ("A shopper at Aldi's reported the carts have formed a union.",
            "Aldis says the carts are fine.",
            "The new Taco Bell item is, legally speaking, a cube.",
            "A recall notice from Toyota puzzled local mechanics."):
    r = news_run(bad)
    check(r.get("_enforced") is True, f"brand scrubbed: {bad[:38]!r}")
    check(r["speaker"] == "Frequency News", "news replacement keeps speaker")
for ok in ("Officials googled it and remain unsure.",
            "A discount grocery chain says its carts have formed a union.",
            "This hour is brought to you by Gary's Discount Teeth.",
            "The bridge is still humming in D."):
    check(not news_run(ok).get("_enforced"), f"clean news kept: {ok[:38]!r}")
check(not news_run(news_run("Aldi's again.")["text"]).get("_enforced"),
      "news replacement is idempotent")


# --- world guard: real people and companies never ride along ----------------
from src.nameguard import enforce_world  # noqa: E402


def world_run(text, **kw):
    return enforce_world([{"speaker": "The Watcher", "voice": "am_onyx",
                           "text": text}], **kw)[0]


for bad in ("The toasters report directly to Elon Musk. Think about it.",
            "Bill Gates put something in the crosswalk buttons.",
            "It goes all the way up to Taylor Swift.",
            "A Tesla idled outside the studio for nine hours.",
            "Rogan talked about this exact thing."):
    r = world_run(bad)
    check(r.get("_enforced") is True, f"world entity scrubbed: {bad[:40]!r}")
    check(r["speaker"] == "The Watcher", "world replacement keeps speaker")
for ok in ("The geese unionized behind the substation.",
            "A billionaire is behind the toasters. I won't say which.",
            "Swift action from the plow crew this morning.",
            "The gates of the impound lot were open. Wide open.",
            "Drake from the hardware store called in again."):
    check(not world_run(ok).get("_enforced"), f"fiction kept: {ok[:40]!r}")
check(not world_run("Elon from Fifth Street has a theory.",
                    extra_ok={"elon"}).get("_enforced"),
      "collisions favour the fiction via extra_ok")
check(not world_run(world_run("Musk again.")["text"]).get("_enforced"),
      "world replacement is idempotent")
# the news wrapper now backstops people too
check(enforce_news([{"speaker": "Frequency News", "voice": "am_onyx",
                     "text": "A statement from Oprah stunned officials."}]
                   )[0].get("_enforced") is True,
      "news guard backstops real people")

print(f"\nnameguard {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
