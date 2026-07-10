"""World-spine consumer wiring (Row D) fixtures.

Pure helpers over the frozen `world.digest` API: the news wire line, the
morning WORLD block, the Halfway-coords forecast copy, and — the load-bearing
one — a SELF-GUARD ROUND-TRIP proving that booth/host lines quoting the digest
pass scoreguard AND nameguard with ZERO replacements, using synthetic facts.

Run directly (no pytest needed):  python3 tests/test_world_consumers.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import world_consumers as wc
from src import scoreguard, nameguard

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


# stub digests -------------------------------------------------------------
FULL = {
    "wire": ["Last night in the league: the Fog Advisories beat the Regrets 4-2."],
    "prompt": ("cold and clear off the lake, wind up the valley; the Half-Dome "
               "lost quorum to the snow again; the Fog Advisories beat the "
               "Regrets last night"),
    "guard": {"score_pairs": [[4, 2]]},
}


def digest_full(day, *, show, want=None, now=None):
    return dict(FULL)


def digest_empty(day, *, show, want=None, now=None):
    return {"wire": [], "prompt": "", "guard": {}}


# --- news_world_line -------------------------------------------------------
line = wc.news_world_line("2026-07-10", digest_fn=digest_full)
check(line == FULL["wire"][0], "news line is the verbatim wire copy")
check(wc.news_world_line("2026-07-10", digest_fn=digest_empty) == "",
      "empty bus => empty news line (caller skips)")

# multi-line wire joins on a space
def _multi(day, *, show, want=None, now=None):
    return {"wire": ["Snow in the pass.", "Regrets fell 4-2."], "prompt": "",
            "guard": {}}
check(wc.news_world_line("d", digest_fn=_multi)
      == "Snow in the pass. Regrets fell 4-2.", "multi wire lines join")


# --- morning_block ---------------------------------------------------------
text, allow = wc.morning_block("2026-07-10", digest_fn=digest_full)
check(FULL["prompt"] in text, "block embeds the bus prompt verbatim")
check(text.startswith("AROUND WENDING TODAY"), "block wears the register head")
check("do NOT invent" in text, "block carries the no-invented-numbers rule")
check(allow == {"score_pairs": [[4, 2]]}, "block returns the guard allow payload")
et, ea = wc.morning_block("2026-07-10", digest_fn=digest_empty)
check(et == "" and ea == {}, "empty bus => empty block, empty allow")


# --- gate / bus-mid-build defensiveness (real _digest path) ----------------
# No data/world/ENABLED in the test cwd and world.py may not exist yet: the
# real adapter must degrade to the empty digest, never raise.
check(wc.news_world_line("2026-07-10") == "", "real bus dark => empty news line")
check(wc.morning_block("2026-07-10") == ("", {}), "real bus dark => empty block")
# the real adapter swallows a broken bus read (world.digest raising) too
def _boom_world():
    class _W:
        HALFWAY_LATLON = {"lat": 44.98, "lon": -73.45}
        @staticmethod
        def on():
            return True
        @staticmethod
        def digest(*a, **k):
            raise RuntimeError("bus mid-build")
    return _W()
import src.world_consumers as _wcmod
_orig_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
    else __builtins__.__import__
check(_wcmod._digest("d", show="news") == {"wire": [], "prompt": "", "guard": {}},
      "adapter degrades to empty digest when bus is absent/unreadable")


# --- weather coords: Halfway, not NYC --------------------------------------
class _FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"current": {"temperature_2m": 28, "wind_speed_10m": 14,
                            "weather_code": 73},
                "daily": {"temperature_2m_max": [30, 33],
                          "temperature_2m_min": [19, 21],
                          "precipitation_probability_max": [80]}}


class _FakeRequests:
    def __init__(self):
        self.params = None

    def get(self, url, params=None, timeout=None):
        self.params = params
        return _FakeResp()


_real = wc.requests
try:
    fake = _FakeRequests()
    wc.requests = fake
    out = wc._real_forecast()
    check(abs(fake.params["latitude"] - 44.98) < 1e-6,
          f"default forecast uses Halfway lat (got {fake.params['latitude']})")
    check(abs(fake.params["longitude"] - (-73.45)) < 1e-6,
          f"default forecast uses Halfway lon (got {fake.params['longitude']})")
    check(abs(fake.params["latitude"] - 40.71) > 1.0, "NOT the legacy NYC lat")
    check("28F" in out and "code 73" in out, "forecast copy parses like spots'")
    # explicit coords override the default
    wc._real_forecast({"lat": 1.5, "lon": 2.5})
    check(fake.params["latitude"] == 1.5 and fake.params["longitude"] == 2.5,
          "explicit coords override the Halfway default")
finally:
    wc.requests = _real


# --- forecast network failure => identical fallback string -----------------
class _BoomRequests:
    def get(self, *a, **k):
        raise OSError("no net")


_real = wc.requests
try:
    wc.requests = _BoomRequests()
    check(wc._real_forecast() == "(no forecast data — improvise gently, no numbers)",
          "forecast failure => the exact spots.py fallback string")
finally:
    wc.requests = _real


# --- THE SELF-GUARD ROUND-TRIP --------------------------------------------
# Synthetic tonight's game (a DIFFERENT matchup than the cross-league final the
# bus cites), a frozen pregame board. The guard allow_pairs come straight from
# the digest's own guard payload — the same event the block renders. Booth lines
# quoting the block must survive BOTH guards untouched.
GAME = {
    "home": "Halfway Roundabouts", "away": "Portage Mavens",
    "rosters": {
        "home": {"skaters": ["Guy Lafontaine", "Denis Ostberg"],
                 "goalie": "Sam Bruue"},
        "away": {"skaters": ["Theo Marchetti", "Cal Rutherford"],
                 "goalie": "Moe Delacroix"}},
    "refs": [],
}
PBP = {"speaker": "Bucky Merle", "voice": "am_onyx", "speed": 1.0}

_text, _allow = wc.morning_block("2026-07-10", digest_fn=digest_full)
facts = scoreguard.build_facts(
    GAME, [], None, mode="pregame", pbp=PBP,
    allow_pairs=_allow.get("score_pairs", ()))

# host/booth lines quoting EXACTLY what the block + wire gave them
quoting = [
    L("Cold and clear tonight, they tell me, real wind up the valley."),
    L("Word downtown is the Half-Dome lost quorum to the snow again."),
    L("And around the league last night, the Fog Advisories beat the Regrets 4-2."),
    L("Nothing to do with our barn — back to the Roundabouts and the Mavens."),
]
after_sg = scoreguard.enforce_scoreboard(quoting, facts)
after_ng = nameguard.enforce_names(after_sg, facts)
touched = [i for i, o in enumerate(after_ng) if o.get("_enforced")]
check(not touched, f"self-guard round-trip: ZERO replacements (touched {touched})")
check([o["text"] for o in after_ng] == [o["text"] for o in quoting],
      "every quoting line survives both guards byte-identical")

# NEGATIVE CONTROL: a hallucinated score about TONIGHT's team (not in allow,
# contradicts the (0,0) pregame board) MUST be replaced — proving the guard is
# live, so the zero above is meaningful, not a dead check.
bad = [L("The Roundabouts are up 5-1 on the Mavens right now.")]
bad_out = scoreguard.enforce_scoreboard(bad, facts)
check(bad_out[0].get("_enforced"), "control: hallucinated tonight-score IS replaced")

# NEGATIVE CONTROL: a real-world hockey name still gets scrubbed by nameguard.
bad2 = nameguard.enforce_names([L("This is nothing like the Montreal Canadiens.")],
                               facts)
check(bad2[0].get("_enforced"), "control: real-world team IS scrubbed by nameguard")


print(f"\nworld_consumers {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
