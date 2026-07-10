"""SFX fixtures: every asset synthesizes clean, tags land on the right lines,
overlays mix where they should, and non-hockey audio is untouched.

Run directly (no pytest needed):  python3 tests/test_sfx.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import sfx

SR = 24000
PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def L(text, speaker="Bucky Merle", **kw):
    return {"speaker": speaker, "voice": "am_onyx", "speed": 1.0,
            "text": text, **kw}


def rms_db(x):
    return 20 * np.log1p(float(np.sqrt(np.mean(x ** 2))) - 1) if False else \
        20 * np.log10(max(float(np.sqrt(np.mean(x ** 2))), 1e-12))


# --- assets synthesize clean ------------------------------------------------
for name in sfx._RECIPES:
    a = sfx.asset(name, SR)
    check(isinstance(a, np.ndarray) and len(a) > SR // 4, f"{name} synthesizes")
    check(not np.any(np.isnan(a)), f"{name} no NaN")
    check(float(np.max(np.abs(a))) <= 1.5, f"{name} sane peak")
    check(abs(rms_db(a) - (-20.0)) < 1.5, f"{name} at house RMS (got {rms_db(a):.1f})")
    check(sfx.asset(name, SR) is a, f"{name} cached")

bed = sfx.crowd_bed(SR, seconds=20)
check(len(bed) > SR * 15, "bed length")
check(abs(rms_db(bed) - (-20.0)) < 1.5, "bed at house RMS")
check(not np.any(np.isnan(bed)), "bed no NaN")

# --- tagging ------------------------------------------------------------------
GOAL = {"type": "goal", "scorer": "Doug Bouchard", "team": "home"}
PEN = {"type": "penalty", "player": "Otto Kranz", "call": "hooking", "team": "away"}

lines = [
    L("Bouchard winds up... he SCORES! What a snipe!"),
    L("Unbelievable release on that one, Bucky.", speaker="Sal Tarantella"),
    L("Kranz is whistled for hooking, two minutes."),
    L("Big save by Tremblay! Robbed him blind!"),
    L("Another save! Denied again!"),
    L("And a third save there, stops it clean!"),
    L("I agree completely.", speaker="Darla", phone=True),
]
tagged = sfx.tag_sfx(lines, [GOAL, PEN], "p2c1")
cues = [dict(t).get("sfx") for t in tagged]

check(("organ_riff", "start") in (cues[0] or []), "period open gets organ")
check(("goal_horn", "end") in (cues[0] or []), "goal call gets horn")
check(("crowd_roar", "end") in (cues[0] or []), "goal call gets roar")
check(cues[1] is None, "color commentary untagged")
check(("whistle", "start") in (cues[2] or []), "penalty line gets whistle")
check(("crowd_ooh", "end") in (cues[3] or []), "first save gets ooh")
check(("crowd_ooh", "end") in (cues[4] or []), "second save gets ooh")
check(cues[5] is None, "third save capped (ooh budget 2)")
check(cues[6] is None, "phone caller never gets arena sound")
check("sfx" not in lines[0], "input lines not mutated")

# goal narrated WITHOUT a goal verb on the scorer line must not horn
t2 = sfx.tag_sfx([L("Bouchard has been strong all night.")], [GOAL], "p1c2")
check(t2[0].get("sfx") is None, "scorer name alone (no goal verb) no horn")

# final horn — only on the beats that actually contain the horn
t3 = sfx.tag_sfx([L("The final horn sounds, and this one is over!")], [], "wrap")
check(("period_horn", "end") in (t3[0].get("sfx") or []), "final horn tagged")
t3b = sfx.tag_sfx([L("And that's the game right there, you tip your cap.")],
                  [], "stars")
check(t3b[0].get("sfx") is None, "no phantom horn in interview/stars beats")

# short crowd_bed is clamp-safe, never a broadcast error
short_bed = sfx.crowd_bed(SR, seconds=1.0)
check(len(short_bed) > 0 and not np.any(np.isnan(short_bed)), "short bed safe")

# two goals -> two horns, in order
t4 = sfx.tag_sfx(
    [L("Bouchard buries it! He scores!"),
     L("And now Larsson lights the lamp! It's two nothing!")],
    [dict(GOAL), {"type": "goal", "scorer": "Erik Larsson", "team": "home"}],
    "p3c2")
check(("goal_horn", "end") in (t4[0].get("sfx") or []), "first goal horns")
check(("goal_horn", "end") in (t4[1].get("sfx") or []), "second goal horns")

# --- overlay mixing -----------------------------------------------------------
audio = np.zeros(SR * 12)
ln = {"sfx": [("goal_horn", "end"), ("crowd_roar", "end")]}
spans = [(SR * 2, SR * 4, ln)]
mixed = sfx.mix_overlays(audio.copy(), spans, SR)
check(len(mixed) == len(audio), "overlay preserves length")
before = float(np.abs(mixed[: SR * 3]).max())
after = float(np.abs(mixed[SR * 4: SR * 6]).max())
check(before == 0.0, "silence before the cue stays silent")
check(after > 0.001, "horn+roar audible after the call lands")

# overlay near the very end must clip, not crash
short = np.zeros(SR // 2)
ok = sfx.mix_overlays(short, [(0, SR // 2, ln)], SR)
check(len(ok) == len(short), "end-of-segment overlay clips safely")

# 'start' cue leads the line
audio2 = np.zeros(SR * 6)
mixed2 = sfx.mix_overlays(audio2.copy(),
                          [(SR * 3, SR * 5, {"sfx": [("whistle", "start")]})], SR)
lead = float(np.abs(mixed2[int(SR * 2.7): SR * 3]).max())
check(lead > 0.001, "start cue leads the line by ~200ms")

print(f"\nsfx {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
