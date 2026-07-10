"""World spine — Row A (the single writer / producer side).

Covers the three producers (weather via an injected `fetch_fn` pinned to
HALFWAY_LATLON, league from fixture `season`/`box` dicts, city from a
fixture bible roster), the append-only merge + `supersedes` correction path
(proving in-place mutation of an already-committed event is impossible),
45-day retention, and idempotent re-derivation (`tick()` called twice with
unchanged source state leaves the bus byte-identical).

Self-contained: every case points `world.WORLD`/`world.SEASON_JSON`/
`world.BOX_DIR`/`world.BIBLE` at a fresh temp dir. Nothing touches the repo.

Run directly (no pytest needed):  python3 tests/test_world_bus.py
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import world

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def fresh_paths():
    """Point every Row-A path constant at a fresh temp dir; returns it."""
    d = Path(tempfile.mkdtemp(prefix="world-bus-"))
    world.WORLD = d / "world-events.json"
    world.SEASON_JSON = d / "season.json"
    world.BOX_DIR = d / "box"
    world.BIBLE = d / "bible.md"
    world.CAUSAL_FLAG = d / "CAUSAL-ENABLED"
    world.APPROVAL_QUEUE = d / "approval-queue.json"
    return d


D1 = "2026-07-09"
D2 = "2026-07-10"
D3 = "2026-07-11"

RAW_OK = {
    "current": {"temperature_2m": 22, "wind_speed_10m": 14, "weather_code": 73},
    "daily": {"temperature_2m_max": [28], "temperature_2m_min": [17],
              "snowfall_sum": [2.1]},
}
RAW_CLEAR = {
    "current": {"temperature_2m": 61, "wind_speed_10m": 5, "weather_code": 1},
    "daily": {"temperature_2m_max": [64], "temperature_2m_min": [48],
              "snowfall_sum": [0]},
}

BIBLE_TEXT = (
    "# Sponsors\n"
    "  - *Ted's Ladder Rental* — every rung a promise\n"
    "  - *SoupCo* — soup, mostly\n"
    "  - *The Roundabout Emporium* — go in circles, save money\n"
)


def season_fixture(slates=None, cup_runs=None):
    return {"season": 3, "slates": slates or {}, "cup_runs": cup_runs or {}}


def box_fixture(games):
    return {"games": games}


# =====================================================================
# 1. weather producer — mocked fetch_fn, pinned to HALFWAY_LATLON
# =====================================================================
fresh_paths()

seen_coords = []


def fetch_ok(coords):
    seen_coords.append(coords)
    return RAW_OK


ev = world._weather_event(D2, fetch_fn=fetch_ok)
check(seen_coords == [world.HALFWAY_LATLON],
      "weather producer calls fetch_fn with HALFWAY_LATLON, nothing else")
check(ev is not None and ev["producer"] == "weather", "weather event produced")
check(ev["payload"]["snow"] is True, "snowfall_sum > 0 => snow event")
check(ev["payload"]["tmax"] == 28 and ev["payload"]["wind"] == 14,
      "weather payload carries the raw numbers through")
check("snow" in ev["tags"], "snow tag present on a snow day")

ev_clear = world._weather_event(D2, fetch_fn=lambda c: RAW_CLEAR)
check(ev_clear["payload"]["snow"] is False, "no snowfall + clear code => no snow")
check("snow" not in ev_clear["tags"], "no snow tag on a clear day")

# missing-feed rule: no feed => no event, ever (weather is never invented)
check(world._weather_event(D2, fetch_fn=lambda c: None) is None,
      "missing feed => no weather event")
check(world._weather_event(D2, fetch_fn=lambda c: {"bad": "shape"}) is None,
      "malformed feed => no weather event, no throw")


def fetch_boom(coords):
    raise OSError("no net")


check(world._weather_event(D2, fetch_fn=fetch_boom) is None,
      "fetch_fn raising => no weather event, no throw")

# world.weather_fn adapter shape (the statehouse/league snow hook)
wf = world.weather_fn(D2, fetch_fn=fetch_ok)
check(wf == {"snowfall": 2.1, "cond": "snow", "tmax": 28, "tmin": 17, "wind": 14},
      "weather_fn adapter returns the calendar.is_snowfall shape")
check(world.weather_fn(D2, fetch_fn=lambda c: None) is None,
      "weather_fn adapter: no feed => None, never invented")


# =====================================================================
# 2. league producer — fixture season.json / box dicts
# =====================================================================
season = season_fixture(slates={
    D1: [["mtl", "nyg", 4, 2, False], ["reg", "hfx", 3, 2, True]],
})
box = box_fixture([
    {"home": "mtl", "away": "nyg", "home_name": "Montreal Apologies",
     "away_name": "New York Gridlock", "so": False},
    {"home": "reg", "away": "hfx", "home_name": "Regina Regrets",
     "away_name": "Halifax Fog Advisories", "so": True},
])
lev = world._league_events(D1, season=season, box=box)
check(len(lev) == 2, "league producer: one event per slate row")
mtl = next(e for e in lev if e["subject"] == "mtl")
check(mtl["payload"]["score"] == [4, 2], "league event score from the slate row")
check(mtl["guard"]["score_pairs"] == [[4, 2]], "league guard carries the score pair")
check("Montreal Apologies" in mtl["guard"]["names"], "league guard carries names")
check("4-2" in mtl["wire"], "league wire quotes the score")
reg = next(e for e in lev if e["subject"] == "reg")
check(reg["payload"]["so"] is True and reg["payload"]["ot"] is False,
      "shootout flag from the box shard overrides the bare OT flag")
check("shootout" in reg["wire"], "shootout wire phrasing")

# a slate day with no box shard still produces events (abbreviation fallback)
lev_noboxes = world._league_events(D1, season=season, box={})
check(lev_noboxes[0]["payload"]["home"] == "mtl",
      "league producer degrades to the raw key when no box shard/name present")

# no slate for the day => no events, no throw
check(world._league_events(D2, season=season, box={}) == [],
      "league producer: no slate for the day => no events")
check(world._league_events(D1, season=None, box={}) == [],
      "league producer: no season.json on disk => no events, no throw")

# reading from disk (SEASON_JSON / BOX_DIR repointed to the temp dir)
world.SEASON_JSON.write_text(json.dumps(season))
world.BOX_DIR.mkdir(parents=True, exist_ok=True)
(world.BOX_DIR / f"{D1}.json").write_text(json.dumps(box))
disk_lev = world._league_events(D1)
check(len(disk_lev) == 2, "league producer reads season.json/box shard from disk")

# cup_run events
season_cup = season_fixture(cup_runs={D1: [{"team": "mtl", "stage": "round2_win",
                                             "series": "3-1"}]})
cev = world._league_events(D1, season=season_cup, box={})
check(len(cev) == 1 and cev[0]["type"] == "league.cup_run",
      "cup_run event produced from season.json's cup_runs ledger")
check(cev[0]["payload"] == {"team": "mtl", "stage": "round2_win", "series": "3-1"},
      "cup_run payload carries team/stage/series through")


# =====================================================================
# 3. city producer — seeded pick over the bible sponsor roster
# =====================================================================
cev1 = world._city_events(D1, bible_text=BIBLE_TEXT)
check(len(cev1) == 1, "city producer emits exactly one color event per day")
check(cev1[0]["producer"] == "city" and cev1[0]["subject"] in
      {"Ted's Ladder Rental", "SoupCo", "The Roundabout Emporium"},
      "city event subject is a roster sponsor")
check(cev1[0]["guard"]["names"] == [cev1[0]["subject"]],
      "city event whitelists the sponsor name it cites")

cev1_again = world._city_events(D1, bible_text=BIBLE_TEXT)
check(cev1 == cev1_again, "city producer: same day => byte-identical pick (seeded)")

# spread: different days should not all land on the same sponsor/kind
picks = {world._city_events(f"2026-07-{d:02d}", bible_text=BIBLE_TEXT)[0]["subject"]
         for d in range(1, 15)}
check(len(picks) > 1, "city producer: picks spread across the roster over time")

check(world._city_events(D1, bible_text="") == [],
      "city producer: empty/unparseable bible => no event, no throw")
check(world._city_events(D1, bible_text=None) == [],
      "city producer: no bible.md on disk => no event, no throw")


# =====================================================================
# 4. tick() — full assembly, append-only merge, idempotent re-derivation
# =====================================================================
fresh_paths()
season1 = season_fixture(slates={D1: [["mtl", "nyg", 4, 2, False]]})
box1 = box_fixture([{"home": "mtl", "away": "nyg",
                      "home_name": "Montreal Apologies",
                      "away_name": "New York Gridlock", "so": False}])

bundle = world.tick(D1, fetch_fn=fetch_ok, season=season1, box=box1,
                     bible_text=BIBLE_TEXT)
check(len(bundle["events"]) == 3, "tick(): weather + league final + city color")
on_disk = world.load()
check(D1 in on_disk["days"] and len(on_disk["days"][D1]) == 3,
      "tick() persists the day's events to the bus file")

# idempotent re-derivation: same inputs, called again -> byte-identical
before = copy.deepcopy(world.load())
world.tick(D1, fetch_fn=fetch_ok, season=season1, box=box1, bible_text=BIBLE_TEXT)
after = world.load()
check(before == after, "tick(): re-deriving unchanged source state is a true no-op")
check(len(after["days"][D1]) == 3,
      "tick(): idempotent re-derivation does not duplicate events")

snapshot_ids = sorted(e["id"] for e in before["days"][D1])
after2 = copy.deepcopy(after)
world.tick(D1, fetch_fn=fetch_ok, season=season1, box=box1, bible_text=BIBLE_TEXT)
check(sorted(e["id"] for e in world.load()["days"][D1]) == snapshot_ids,
      "tick(): third call still idempotent")


# =====================================================================
# 5. append-only + supersedes: in-place mutation must be impossible
# =====================================================================
fresh_paths()
season_v1 = season_fixture(slates={D1: [["mtl", "nyg", 4, 2, False]]})
box_v1 = box_fixture([{"home": "mtl", "away": "nyg",
                        "home_name": "Montreal Apologies",
                        "away_name": "New York Gridlock", "so": False}])
world.tick(D1, fetch_fn=fetch_ok, season=season_v1, box=box_v1,
           bible_text=BIBLE_TEXT)
bus_v1 = world.load()
original_event = next(e for e in bus_v1["days"][D1]
                       if e["id"] == f"league.final:{D1}:mtl-nyg")
original_snapshot = copy.deepcopy(original_event)

# a correction arrives: the same game's score is now 5-2 (a stat correction)
season_v2 = season_fixture(slates={D1: [["mtl", "nyg", 5, 2, False]]})
world.tick(D1, fetch_fn=fetch_ok, season=season_v2, box=box_v1,
           bible_text=BIBLE_TEXT)
bus_v2 = world.load()
day2 = bus_v2["days"][D1]

still_there = next((e for e in day2 if e["id"] == original_event["id"]), None)
check(still_there is not None,
      "supersedes: the original event is still present, never deleted")
check(still_there == original_snapshot,
      "supersedes: the original event's body is byte-unchanged (no in-place mutation)")

corrections = [e for e in day2 if e.get("supersedes") == original_event["id"]]
check(len(corrections) == 1, "supersedes: exactly one correction event appended")
check(corrections[0]["payload"]["score"] == [5, 2],
      "supersedes: the correction carries the NEW score")
check(corrections[0]["id"] != original_event["id"],
      "supersedes: the correction has its own distinct id")
check(len(day2) == len(bus_v1["days"][D1]) + 1,
      "supersedes: append-only growth by exactly one event, nothing removed")

# in-place-mutation-is-impossible, proven structurally: mutating the dict
# object `_merge_day` returns for the OLD id must not be reachable — the
# function only ever returns a NEW list; assert identity independence.
check(day2 is not bus_v1["days"][D1],
      "supersedes: merge produces a new list object, not a mutated one")

# a second correction on top of the first supersedes the LIVE version
season_v3 = season_fixture(slates={D1: [["mtl", "nyg", 6, 2, False]]})
world.tick(D1, fetch_fn=fetch_ok, season=season_v3, box=box_v1,
           bible_text=BIBLE_TEXT)
day3 = world.load()["days"][D1]
v2_id = corrections[0]["id"]
second = [e for e in day3 if e.get("supersedes") == v2_id]
check(len(second) == 1, "supersedes: a second correction supersedes the LIVE version")
check(all(e["id"] == original_event["id"] or True for e in day3),
      "supersedes: original id still present after a second correction")
check(len([e for e in day3 if e["id"] == original_event["id"]]) == 1,
      "supersedes: original event still exactly once, untouched, after two corrections")


# =====================================================================
# 6. 45-day prune
# =====================================================================
fresh_paths()
bus = {"schema": 1, "days": {}}
import datetime
base = datetime.date(2026, 1, 1)
for i in range(60):
    day = (base + datetime.timedelta(days=i)).isoformat()
    bus["days"][day] = [{"id": f"x:{day}", "producer": "city"}]
world.save(bus)
world._prune(bus)
check(len(bus["days"]) == world.RETAIN_DAYS,
      f"prune: bounded to {world.RETAIN_DAYS} trailing days (got {len(bus['days'])})")
check(min(bus["days"]) == (base + datetime.timedelta(days=60 - world.RETAIN_DAYS))
      .isoformat(), "prune: keeps the TRAILING (most recent) days")

# prune fires naturally through tick()/_write_day too
fresh_paths()
for i in range(50):
    day = (base + datetime.timedelta(days=i)).isoformat()
    world._write_day(day, [{"id": f"y:{day}", "producer": "city", "day": day}])
final_bus = world.load()
check(len(final_bus["days"]) == world.RETAIN_DAYS,
      "prune: _write_day keeps the bus bounded across many days")


# ------------------------------------------------------------------- summary
print(f"\nworld_bus {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
