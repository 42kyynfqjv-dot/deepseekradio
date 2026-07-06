"""clean_for_speech: everything written for the eye must come out sayable.

Run directly (no pytest needed):  python3 tests/test_clean_for_speech.py
"""
import re
import sys
from pathlib import Path

# import just the normalizer without pulling kokoro/scipy
src = (Path(__file__).parent.parent / "src" / "tts.py").read_text()
ns = {"re": re, "__name__": "tts"}
exec(compile(src.split("_kokoro = None")[0], "tts", "exec"), ns)
clean = ns["clean_for_speech"]

CASES = [
    # years
    ("the receipt from 1998.", "the receipt from nineteen ninety eight."),
    ("back in 2026, sure", "back in twenty twenty six, sure"),
    ("circa 2000", "circa two thousand"),
    ("in 2005 or 1907", "in two thousand five or nineteen oh seven"),
    # times + am/pm
    ("at 7:00 sharp", "at seven o'clock sharp"),
    ("the 11:47 drizzle", "the eleven forty seven drizzle"),
    ("around 8:05", "around eight oh five"),
    ("by 9 AM today", "by 9 ay em today"),
    ("it's 7:30pm now", "it's seven thirty pee em now"),
    ("I am not a clock", "I am not a clock"),
    ("so am I", "so am I"),
    # money / percent / degrees
    ("$50 fine", "50 dollars fine"),
    ("73% chance", "73 percent chance"),
    ("72°F and clear", "72 degrees fahrenheit and clear"),
    ("about 40° out", "about 40 degrees out"),
    # decimals, ordinals, ranges, phones
    ("a 0.4 reading", "a 0 point four reading"),
    ("the 3rd of May", "the third of May"),
    ("my 21st caller", "my twenty first caller"),
    ("delays of 5-10 minutes", "delays of 5 to 10 minutes"),
    ("call 555-0142 now", "call five five five, zero one four two now"),
    # abbreviations
    ("Dr. Plums will see you", "Doctor Plums will see you"),
    ("Mr. Wesley, please", "Mister Wesley, please"),
    ("on Main St. downtown", "on Main Street downtown"),
    ("St. Mary's bake sale", "Saint Mary's bake sale"),
    ("cats vs. dogs", "cats versus dogs"),
    ("mugs, spoons, etc.", "mugs, spoons, et cetera"),
    ("doing 80 mph", "doing 80 miles an hour"),
    # station furniture
    ("live twenty-four seven", "live twenty-four seven"),
    ("we're 24/7 now", "we're twenty-four seven now"),
    ("visit bestairadio.com today", "visit bestairadio dot com today"),
    ("complaint #12 filed", "complaint number 12 filed"),
    ("12,000 listeners", "12000 listeners"),
    # typography still stripped
    ("*sighs* fine", "fine"),
    ("well — actually", "well , actually"),
    ("wait… what", "wait. what"),
]

failures = 0
for given, want in CASES:
    got = clean(given)
    if got != want:
        failures += 1
        print(f"FAIL: {given!r}\n  want: {want!r}\n  got:  {got!r}")
if failures:
    print(f"\n{failures}/{len(CASES)} failed")
    sys.exit(1)
print(f"all {len(CASES)} cases pass")
