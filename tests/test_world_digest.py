"""World spine — `world.digest` three-product consumer API.

Covers the wire/prompt/guard products, per-show relevance, the next-day
consumption rule for cross-engine events (the property test the brief names),
air-gating, supersedes, guard merge/dedup, the total gate-off / degraded
fallback, determinism, and the G3-style self-guard CI (a booth line quoting
the block trips zero scoreguard replacements).

Self-contained: every case builds its own bus file + ENABLED flag in a temp
dir and points `world.WORLD`/`world.FLAG` at it. Nothing touches the repo.

Run directly (no pytest needed):  python3 tests/test_world_digest.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import world
from src import scoreguard

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


# ---------------------------------------------------------------- bus fixture
D0 = "2026-07-08"
D1 = "2026-07-09"
D2 = "2026-07-10"
D3 = "2026-07-11"


def league_final(day, home, away, hk, ak, score, guard):
    return {
        "id": f"league.final:{day}:{hk}-{ak}", "type": "league.final",
        "producer": "league", "subject": hk, "air_at": 0,
        "payload": {"home": home, "away": away, "score": score},
        "wire": f"Around the league: the {home.split()[-1]} took the "
                f"{away.split()[-1]} {score[0]}-{score[1]}.",
        "prompt": f"the {home.split()[-1]} beat the {away.split()[-1]} last night",
        "guard": guard, "tags": ["hockey", "result"],
    }


def make_bus():
    return {
        "schema": 1,
        "days": {
            D1: [
                league_final(D1, "Montreal Apologies", "New York Gridlock",
                             "mtl", "nyg", [4, 2],
                             {"score_pairs": [[4, 2]],
                              "names": ["Montreal Apologies",
                                        "New York Gridlock"]}),
                {"id": f"civic.quorum_fail:{D1}", "type": "civic.quorum_fail",
                 "producer": "statehouse", "subject": "half-dome", "air_at": 0,
                 "payload": {"cause": "snow"},
                 "wire": "The Half-Dome lost quorum to the weather again.",
                 "prompt": "the statehouse couldn't make quorum in the snow",
                 "guard": {}, "tags": ["civic", "snow"]},
            ],
            D2: [
                {"id": f"weather.day:{D2}", "type": "weather.day",
                 "producer": "weather", "subject": "halfway", "air_at": 0,
                 "payload": {"tempF": 34, "snow": True},
                 "wire": None,
                 "prompt": "cold with snow off the lake, wind picking up",
                 "guard": {}, "tags": ["weather", "snow"]},
                {"id": f"city.billboard:{D2}", "type": "city.billboard",
                 "producer": "city", "subject": "teds-ladder", "air_at": 0,
                 "payload": {"sponsor": "Ted's Ladder Rental"},
                 "wire": "This hour brought to you by Ted's Ladder Rental.",
                 "prompt": "Ted's Ladder Rental has the hour downtown",
                 "guard": {}, "tags": ["city"]},
                # a league final dated D2 — must NOT surface until D3
                league_final(D2, "Regina Regrets", "Halifax Fog", "reg",
                             "hfx", [3, 2], {"score_pairs": [[3, 2]]}),
            ],
        },
    }


def with_bus(bus, flag=True, extra=None):
    """Write the bus to a fresh temp dir and repoint world's paths."""
    d = Path(tempfile.mkdtemp(prefix="world-"))
    (d / "world-events.json").write_text(json.dumps(bus))
    world.WORLD = d / "world-events.json"
    fl = d / "ENABLED"
    if flag:
        fl.write_text("")
    world.FLAG = fl
    return d


# ---------------------------------------------------- 1. gate-off is inert
with_bus(make_bus(), flag=False)
off = world.digest(D2, show="morning", now=2e9)
check(off == {"wire": [], "prompt": "", "guard": {}}, "gate off => empty digest")

# ---------------------------------------------------- 2. the three products
with_bus(make_bus())
dg = world.digest(D2, show="morning", now=2e9)
check(set(dg) == {"wire", "prompt", "guard"}, "digest has three products")
# wire: same-day city + day-after (D1) league final + civic; weather wire null
check(any("Ted's Ladder Rental" in w for w in dg["wire"]), "wire: city billboard")
check(any("Apologies took the Gridlock 4-2" in w for w in dg["wire"]),
      "wire: yesterday's league final, verbatim")
check(any("Half-Dome lost quorum" in w for w in dg["wire"]), "wire: civic note")
check(all(w for w in dg["wire"]), "wire: no null lines leak in")
# prompt: SCOREBOARD-register block, qualitative
check(dg["prompt"].startswith("AROUND WENDING TODAY"), "prompt: register wrapper")
check("cold with snow" in dg["prompt"], "prompt: weather color present")
check("beat the Gridlock last night" in dg["prompt"], "prompt: league color present")
# guard: merged allow_pairs + names, ready for scoreguard
check(dg["guard"].get("allow_pairs") == [[2, 4]], "guard: 4-2 -> sorted allow_pair")
check("Montreal Apologies" in dg["guard"].get("names", []), "guard: names allowlist")

# ---------------------------------------------------- 3. PROPERTY: next-day rule
# A league event dated D is ABSENT from D's digest and PRESENT in D+1's.
with_bus(make_bus())
same = world.digest(D2, show="morning", now=2e9)
check(not any("Regrets took the Fog 3-2" in w for w in same["wire"]),
      "next-day: league final dated D2 ABSENT from digest(D2)")
nextd = world.digest(D3, show="morning", now=2e9)
check(any("Regrets took the Fog 3-2" in w for w in nextd["wire"]),
      "next-day: league final dated D2 PRESENT in digest(D3)")
# and weather (external input) is consumed SAME day
check("cold with snow" in same["prompt"], "same-day: weather consumed on D2")

# ---------------------------------------------------- 4. per-show relevance
with_bus(make_bus())
# Center Ice never sees its own scores echoed back (league excluded); it DOES
# get civic + weather color.
ci = world.digest(D2, show="center-ice", now=2e9)
check(not any("league" in w.lower() or "Apologies" in w for w in ci["wire"]),
      "center-ice: league scores excluded (own institution)")
check(any("Half-Dome" in w for w in ci["wire"]), "center-ice: civic color kept")
check(ci["guard"] == {}, "center-ice: no league allow_pairs bleed in")
# statehouse excludes its own civic facts but gets the league Cup-run color
sh = world.digest(D2, show="statehouse", now=2e9)
check(not any("Half-Dome" in w for w in sh["wire"]),
      "statehouse: own civic facts excluded")
check(any("Apologies" in w for w in sh["wire"]), "statehouse: league color kept")

# ---------------------------------------------------- 5. `want` override
with_bus(make_bus())
w = world.digest(D2, show="statehouse", want={"league"}, now=2e9)
check(any("Apologies" in x for x in w["wire"]), "want=league: league present")
check(not any("Half-Dome" in x or "Ted's" in x for x in w["wire"]),
      "want=league: everything else filtered out")

# ---------------------------------------------------- 6. air-gate filtering
bus = make_bus()
# push D1's league final behind a future air stamp
bus["days"][D1][0]["air_at"] = 5e9
with_bus(bus)
gated = world.digest(D2, show="morning", now=2e9)
check(not any("Apologies" in x for x in gated["wire"]),
      "air-gate: future air_at hides the final")
check(gated["guard"] == {}, "air-gate: hidden event contributes no guard")
open_now = world.digest(D2, show="morning", now=6e9)
check(any("Apologies" in x for x in open_now["wire"]),
      "air-gate: once air_at <= now the final surfaces")

# ---------------------------------------------------- 7. supersedes (append-only)
bus = make_bus()
bus["days"][D1].append({
    "id": f"league.final:{D1}:mtl-nyg#v2", "type": "league.final",
    "producer": "league", "subject": "mtl", "air_at": 0,
    "supersedes": f"league.final:{D1}:mtl-nyg",
    "payload": {"score": [5, 2]},
    "wire": "Correction — the Apologies took the Gridlock 5-2.",
    "prompt": "the Apologies beat the Gridlock last night",
    "guard": {"score_pairs": [[5, 2]]}, "tags": ["hockey", "result"]})
with_bus(bus)
corr = world.digest(D2, show="morning", now=2e9)
check(any("5-2" in x for x in corr["wire"]), "supersedes: correction shown")
check(not any("4-2" in x for x in corr["wire"]),
      "supersedes: superseded fact hidden")
check(corr["guard"]["allow_pairs"] == [[2, 5]],
      "supersedes: only the live pair whitelisted")

# ---------------------------------------------------- 8. guard merge / dedup
bus = make_bus()
# a second league final on D1 repeating the 4-2 pair -> dedup to one allow_pair
bus["days"][D1].append(league_final(D1, "Boise Bylaws", "Ottawa Owes",
                                     "boi", "ott", [4, 2],
                                     {"score_pairs": [[4, 2]]}))
with_bus(bus)
mg = world.digest(D2, show="morning", now=2e9)
check(mg["guard"]["allow_pairs"] == [[2, 4]], "guard: duplicate pair deduped")

# ---------------------------------------------------- 9. determinism
with_bus(make_bus())
a = world.digest(D2, show="morning", now=2e9)
b = world.digest(D2, show="morning", now=2e9)
check(a == b, "digest is deterministic across calls")

# ---------------------------------------------------- 10. degraded fallbacks
# missing bus file
d = Path(tempfile.mkdtemp(prefix="world-"))
world.WORLD = d / "nope.json"
(d / "ENABLED").write_text("")
world.FLAG = d / "ENABLED"
check(world.digest(D2, show="morning", now=2e9) ==
      {"wire": [], "prompt": "", "guard": {}}, "missing bus => empty, no throw")
# malformed bus file
(d / "bad.json").write_text("{ not json ]")
world.WORLD = d / "bad.json"
check(world.digest(D2, show="morning", now=2e9)["wire"] == [],
      "malformed bus => empty, no throw")

# ---------------------------------------------------- 11. self-guard CI (G3)
# Render the block's guard facts, synthesize a booth line quoting a cross-game
# score the digest whitelisted, run the destination guard over it, and require
# ZERO replacements — the bus can never phrase its truth in a way its own show's
# guard would flag.
with_bus(make_bus())
booth = world.digest(D2, show="morning", now=2e9)
allow = booth["guard"]["allow_pairs"]        # [[2, 4]]
# the booth's OWN game is a different matchup (final 3-1); it cites the league
# final (4-2) as around-the-league color.
game = {
    "home": "Wending Lanterns", "away": "Boreal Bishops",
    "rosters": {"home": {"skaters": ["Doug Bouchard"], "goalie": "Ed Poole"},
                "away": {"skaters": ["Otto Kranz"], "goalie": "Sy Vance"}},
    "refs": [],
}
pbp = {"speaker": "Bucky Merle", "voice": "am_onyx", "speed": 1.0}
facts = scoreguard.build_facts(
    game, prior_events=[], chunk=None, mode="pregame", pbp=pbp,
    allow_pairs=allow, final=(3, 1))
lines = [
    {"speaker": "Bucky Merle", "voice": "am_onyx", "speed": 1.0,
     "text": "Around the league last night, the Apologies took the Gridlock "
             "4-2 — quite a night."},
    {"speaker": "Sal Tarantella", "voice": "am_echo", "speed": 1.0,
     "text": "And here at home it's the Lanterns on top, 3-1."},
]
enforced = scoreguard.enforce_scoreboard(lines, facts)
replaced = sum(1 for o in enforced if o.get("_enforced"))
check(replaced == 0, f"self-guard CI: booth quoting the block => 0 replacements "
                     f"(got {replaced})")
check(len(enforced) == 2, "self-guard CI: no phantom injections")

# ------------------------------------------------------------------- summary
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
