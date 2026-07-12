"""Storm Watch core tests (Row 5). Plain python3, PASS/FAIL counters, exit
code — the house style (see tests/test_sfx.py, tests/test_podcast.py).

Covers: is_storm tells (words + WMO code, None-safe, no false-positive on
'service'/'brain'); storm_sheet determinism, bounds (so-far <= expected),
and real-wind lift; closings cumulative monotonicity + saturation +
per-entry stability; block content; verify pass/fail incl. spelled numbers
and plow-location numbers; and a nameguard collision sweep of every invented
name.

  python3 tests/test_blizzard.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import blizzard as B  # noqa: E402

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


# --- is_storm ---------------------------------------------------------------
check(B.is_storm(None) is False, "None -> False")
check(B.is_storm("") is False, "empty -> False")
check(B.is_storm("(no forecast data — improvise gently, no numbers)") is False,
      "the no-data sentinel is not a storm")
check(B.is_storm("now 68F wind 5mph code 1; today high 74F low 55F rain 10 percent")
      is False, "a clear summer day is not a storm")
check(B.is_storm("now 71F wind 8mph code 61; rain 90 percent") is False,
      "plain rain (code 61) is not a storm")

check(B.is_storm("Heavy snow through the morning") is True, "snow word")
check(B.is_storm("BLIZZARD WARNING in effect") is True, "blizzard, case-insensitive")
check(B.is_storm("freezing rain glazing the roads") is True, "freezing tell")
check(B.is_storm("sleet then flurries by noon") is True, "sleet/flurries")
check(B.is_storm("now 30F wind 20mph code 75; today high 31F") is True,
      "WMO snow code 75")
check(B.is_storm("now 28F wind 22mph code 67") is True, "freezing-rain code 67")

# no false positives on substrings
check(B.is_storm("thanks for the great service this morning") is False,
      "'service' does not trip 'ice'")
check(B.is_storm("use your brain, the roads are fine") is False,
      "'brain' does not trip 'rain'-adjacent tells")
check(B.is_storm("a nice choice for breakfast") is False, "'nice' does not trip 'ice'")

# --- storm_sheet ------------------------------------------------------------
fc = "now 30F wind 24mph code 73; today high 31F low 18F rain 100 percent"
s1 = B.storm_sheet("2026-01-14", fc)
s1b = B.storm_sheet("2026-01-14", fc)
check(s1 == s1b, "storm_sheet is deterministic for a fixed (date, forecast)")
check(B.storm_sheet("2026-01-15", fc) != s1, "different date -> different sheet")

check(1 <= s1["inches_so_far"] <= s1["inches_expected"],
      f"so-far within [1, expected] ({s1['inches_so_far']}/{s1['inches_expected']})")
check(s1["wind"] == 24, "wind lifted from the real forecast text")
check(B.storm_sheet("2026-01-14", "snowing hard, no numbers")["wind"] != 0
      and isinstance(B.storm_sheet("2026-01-14", "snowing")["wind"], int),
      "wind is seeded when the forecast carries no mph number")
check(s1["plow_at"] not in s1["plow_not_at"], "the plow can't be where it isn't")
check(len(s1["plow_not_at"]) == 2, "two roads the plow hasn't reached")
check(all(isinstance(s1[k], int) for k in ("inches_so_far", "inches_expected", "wind")),
      "sheet numbers are small ints")

# --- closings: cumulative, monotonic, stable --------------------------------
check(B.closings("2026-01-14", -1) == [], "negative beat -> empty")
c0 = B.closings("2026-01-14", 0)
c1 = B.closings("2026-01-14", 1)
c2 = B.closings("2026-01-14", 2)
check(len(c0) == 4, f"beat 0 opens with 4 closings (got {len(c0)})")
check(len(c1) > len(c0) and len(c2) > len(c1), "the list grows beat over beat")
check(c0 == B.closings("2026-01-14", 0), "closings deterministic per (date, beat)")
# cumulative: every earlier beat's closings survive verbatim into later beats
check(c0 == c1[:len(c0)] and c1 == c2[:len(c1)],
      "closings never un-close (each beat is a prefix-superset of the last)")
# saturation: eventually the whole town is shut, and it stays put
big = B.closings("2026-01-14", 50)
check(len(big) == len(B._CLOSINGS_BANK), "closings saturate at the full bank")
check(B.closings("2026-01-14", 999) == big, "saturated list is stable")
check(len(set(big)) == len(big), "no duplicate closings in the saturated list")
# no digits leak into closings copy (would trip verify if read aloud)
import re as _re
check(not any(_re.search(r"\d", ln) for ln in big),
      "closings copy carries no numbers")

# --- block ------------------------------------------------------------------
blk = B.block(s1, c1)
check("authoritative" in blk.lower(), "block announces itself authoritative")
check(str(s1["inches_so_far"]) in blk and str(s1["inches_expected"]) in blk
      and str(s1["wind"]) in blk, "block states the three sheet numbers")
check(s1["plow_at"] in blk and all(p in blk for p in s1["plow_not_at"]),
      "block states the plow's whereabouts")
check(all(c in blk for c in c1), "every handed closing appears verbatim in the block")
check("nothing is closed yet" in B.block(s1, []), "empty closings has a graceful line")

# --- verify -----------------------------------------------------------------
sf, ex, wd = s1["inches_so_far"], s1["inches_expected"], s1["wind"]
check(B.verify([f"We've had {sf} inches, {ex} on the way, winds at {wd}."], s1) is True,
      "a read using only sheet numbers passes")
check(B.verify(["Snow keeps falling across Halfway this morning."], s1) is True,
      "a numberless read passes")
# spelled numbers are checked too
tricky = {"inches_so_far": 3, "inches_expected": 9, "wind": 20,
          "plow_at": "Mill Road", "plow_not_at": ["the bridge", "Creamery Lane"]}
check(B.verify(["Three inches down, nine to come."], tricky) is True,
      "spelled sheet numbers pass")
check(B.verify(["We're up to seven inches already."], tricky) is False,
      "a spelled number not on the sheet fails")
check(B.verify([f"Winds gusting to {wd + 11}."], s1) is False,
      "an invented wind number fails")
# a plow location's own number is allowed
plowy = {"inches_so_far": 4, "inches_expected": 10, "wind": 18,
         "plow_at": "Route 9", "plow_not_at": ["the bridge", "Mill Road"]}
check(B.verify(["The plow finally reached Route 9."], plowy) is True,
      "a number inside the plow location is allowed")

# --- nameguard collision sweep ---------------------------------------------
from src import nameguard as NG  # noqa: E402
_banned = set(NG._WORLD_TOKENS) | set(NG._WORLD_PHRASES)
_words = set()
for entry in B._CLOSINGS_BANK + B._PLOW_BANK:
    for w in _re.findall(r"[a-z']+", entry.lower()):
        _words.add(w)
check(not (_words & _banned), f"no invented name collides with nameguard tokens "
      f"(overlap: {_words & _banned})")
for phrase in NG._WORLD_PHRASES:
    for entry in B._CLOSINGS_BANK + B._PLOW_BANK:
        check(phrase not in entry.lower(), f"no banned phrase in {entry!r}")

print(f"blizzard {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
