"""Events registry loader/validator fixtures (Track D, component 1).

Asserts the design's component-1 contract: malformed record rejected; unknown
engine dropped and never dispatched; literal date/dates resolve; deriver records
classified; window (incl. midnight-wrapping) validated; gate field preserved;
`{..}` meta templating; missing file => empty list (no-op); mtime caching.

Run directly (no pytest needed):  python3 tests/test_events_registry.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.events import registry

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def write(tmp, text):
    p = Path(tmp) / "registry.yaml"
    p.write_text(text)
    registry.clear_cache()
    return p


# A minimal valid record body reused across malformed-field tests.
GOOD = """schema: 1
events:
  - id: ok_event
    engine: center_ice
    deriver: playoff_nights
    gate: "data/league/ECON-ENABLED"
    window: ["20:00", "23:00"]
    priority: 50
    show: {show: "Center Ice — Playoffs", cast: [bucky, sal]}
    site: {name: "Center Ice — Playoffs", hook: "Live from {arena}.", who: "BUCKY · SAL"}
    promo: {lead_days: 4, copy: ["Game {game}: {away} at {home}."]}
"""

tmp = tempfile.mkdtemp()

# ── the shipped seed registry loads and every record is valid ───────────────
seed = registry.load_registry(Path(__file__).parent.parent / "events/registry.yaml")
check(len(seed) == 5, f"seed registry has 5 valid records (got {len(seed)})")
ids = {r["id"] for r in seed}
check(ids == {"election_night", "playoff_night", "draft_day",
              "trade_deadline", "blizzard"}, f"seed ids as designed (got {ids})")
by_id = {r["id"]: r for r in seed}
for r in seed:
    ok, why = registry.validate_record(r)
    check(ok, f"seed record {r['id']} validates ({why})")
check(by_id["election_night"]["priority"] == 90, "election night priority 90")
check(by_id["election_night"]["gate"] == "data/statehouse/ELECTION-ENABLED",
      "election gate path preserved")
# integration gates blizzard dark until run_blizzard exists — an event whose
# engine isn't built must never reach air (design allows null once it is)
check(by_id["blizzard"]["gate"] == "data/events/BLIZZARD-ENABLED",
      "blizzard gated dark pending its engine")

# every seed show fragment is a valid daypart shape (name + window + cast the
# overlay/_current_daypart need)
for r in seed:
    show = r["show"]
    check(isinstance(show.get("show"), str) and isinstance(show.get("cast"), list),
          f"{r['id']} show fragment is a valid daypart shape")
    start, end = r["window"]
    check(registry._valid_hhmm(start) and registry._valid_hhmm(end),
          f"{r['id']} window parses")

# ── missing file => empty list (the no-op / evergreen station) ──────────────
registry.clear_cache()
check(registry.load_registry(Path(tmp) / "nope.yaml") == [],
      "missing file => [] (no-op)")

# ── dating classification + literal resolution ──────────────────────────────
check(registry.dating_kind(by_id["election_night"]) == "dates",
      "election_night classified as literal 'dates'")
check(registry.dating_kind(by_id["playoff_night"]) == "deriver",
      "playoff_night classified as 'deriver'")
check(registry.literal_dates(by_id["election_night"]) == ["2026-11-03"],
      "literal dates resolve to ['2026-11-03']")
check(registry.literal_dates(by_id["playoff_night"]) == [],
      "derived record has no literal dates")

# single literal `date:` also resolves
p = write(tmp, """schema: 1
events:
  - id: one_off
    engine: blizzard
    date: "2027-01-15"
    gate: null
    window: ["06:00", "10:00"]
    priority: 40
    show: {show: "Storm Watch", cast: [wesley]}
    site: {name: "Storm Watch"}
    promo: {lead_days: 0, copy: []}
""")
recs = registry.load_registry(p)
check(len(recs) == 1 and registry.dating_kind(recs[0]) == "date",
      "single 'date:' classified as literal 'date'")
check(registry.literal_dates(recs[0]) == ["2027-01-15"],
      "single 'date:' resolves to a one-element list")

# ── window wrap detection ───────────────────────────────────────────────────
check(registry.window_wraps(["19:00", "01:00"]), "19:00->01:00 wraps midnight")
check(not registry.window_wraps(["20:00", "23:00"]), "20:00->23:00 same-day")

# ── malformed records are each rejected (drop-with-log, siblings survive) ────
def rejects(body, why):
    ok, _ = registry.validate_record(body)
    check(not ok, f"rejected: {why}")


base = {
    "id": "x", "engine": "center_ice", "deriver": "playoff_nights",
    "gate": None, "window": ["20:00", "23:00"], "priority": 10,
    "show": {"show": "S", "cast": []},
    "site": {"name": "S"}, "promo": {"lead_days": 1, "copy": ["hi"]},
}
ok, _ = registry.validate_record(dict(base))
check(ok, "baseline record validates")

rejects({**base, "engine": "made_up_engine"}, "unknown engine")
rejects({k: v for k, v in base.items() if k != "engine"}, "missing engine")
rejects({**base, "deriver": "not_a_deriver"}, "unknown deriver")
rejects({**base, "date": "2026-11-03"}, "two dating mechanisms (deriver+date)")
rejects({k: v for k, v in base.items() if k != "deriver"}, "no dating mechanism")
rejects({**base, "window": ["20:00"]}, "window not a pair")
rejects({**base, "window": ["25:99", "23:00"]}, "window not parseable HH:MM")
rejects({**base, "priority": "high"}, "priority not int")
rejects({**base, "priority": True}, "priority bool is not an int")
rejects({**base, "gate": ""}, "empty-string gate")
rejects({**base, "show": {"cast": []}}, "show fragment missing name")
rejects({**base, "site": {}}, "site missing name")
rejects({**base, "promo": {"lead_days": -1, "copy": []}}, "negative lead_days")
rejects({**base, "promo": {"lead_days": 1, "copy": [3]}}, "non-string copy line")
rejects({**base, "bogus": 1}, "unknown top-level field (frozen field set)")
rejects({**{k: v for k, v in base.items() if k != "deriver"},
         "date": "2026-13-40"}, "bad ISO date")
rejects({**{k: v for k, v in base.items() if k != "deriver"},
         "dates": []}, "empty 'dates' list")

# a malformed record is DROPPED at load; valid siblings survive with a log line
p = write(tmp, """schema: 1
events:
  - id: good_one
    engine: center_ice
    deriver: playoff_nights
    gate: null
    window: ["20:00", "23:00"]
    priority: 50
    show: {show: "Center Ice", cast: [bucky]}
    site: {name: "Center Ice"}
    promo: {lead_days: 4, copy: []}
  - id: bad_engine
    engine: totally_bogus
    date: "2026-11-03"
    gate: null
    window: ["19:00", "01:00"]
    priority: 90
    show: {show: "X", cast: []}
    site: {name: "X"}
    promo: {lead_days: 1, copy: []}
""")
loaded = registry.load_registry(p)
check([r["id"] for r in loaded] == ["good_one"],
      "unknown-engine record dropped, valid sibling survives")

# duplicate ids: keep first, drop the rest
p = write(tmp, """schema: 1
events:
  - id: dupe
    engine: center_ice
    deriver: playoff_nights
    gate: null
    window: ["20:00", "23:00"]
    priority: 50
    show: {show: "A", cast: []}
    site: {name: "A"}
    promo: {lead_days: 1, copy: []}
  - id: dupe
    engine: blizzard
    deriver: blizzard_days
    gate: null
    window: ["06:00", "10:00"]
    priority: 40
    show: {show: "B", cast: []}
    site: {name: "B"}
    promo: {lead_days: 0, copy: []}
""")
loaded = registry.load_registry(p)
check(len(loaded) == 1 and loaded[0]["show"]["show"] == "A",
      "duplicate id: first kept, second dropped")

# empty / non-mapping / non-list events => [] not a crash
check(registry.load_registry(write(tmp, "")) == [], "empty file => []")
check(registry.load_registry(write(tmp, "schema: 1\nevents: not_a_list\n")) == [],
      "events not a list => []")
check(registry.load_registry(write(tmp, "- just\n- a\n- list\n")) == [],
      "top-level list (not a mapping) => []")

# ── {..} meta templating ────────────────────────────────────────────────────
meta = {"round": "Semifinal", "game": 7, "home": "Frost", "away": "Gale",
        "arena": "the Ice Barn", "weekday": "Wednesday"}
line = "Center Ice, {round}, Game {game}: {away} at {home}. Live {weekday} night."
check(registry.fill_template(line, meta)
      == "Center Ice, Semifinal, Game 7: Gale at Frost. Live Wednesday night.",
      "promo template fills from meta")
check(registry.fill_template("Live from {arena}.", meta) == "Live from the Ice Barn.",
      "site hook fills from meta")
# unknown placeholder left verbatim, never a KeyError
check(registry.fill_template("Game {game} vs {mystery}", meta)
      == "Game 7 vs {mystery}", "unknown placeholder left intact (no crash)")
check(registry.fill_template("no placeholders here", meta) == "no placeholders here",
      "plain string passes through")
check(registry.fill_template("Live from {arena}.", None) == "Live from {arena}.",
      "None meta leaves placeholders intact")

# ── mtime caching: same bytes => same object; changed mtime => reload ────────
registry.clear_cache()
p = write(tmp, GOOD)
a = registry.load_registry(p)
b = registry.load_registry(p)
check(a is b, "unchanged file returns the SAME cached list object")
# bump mtime forward -> re-parse -> fresh object, same content
os.utime(p, (a and os.stat(p).st_atime, os.stat(p).st_mtime + 5))
c = registry.load_registry(p)
check(c is not b, "changed mtime re-parses to a fresh list")
check([r["id"] for r in c] == [r["id"] for r in b], "reload yields same records")

print(f"\nevents_registry {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
