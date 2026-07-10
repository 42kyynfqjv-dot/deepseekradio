"""World spine — Row C: the ONE dark causal edge (Cup run -> governor
approval), gated behind `data/world/CAUSAL-ENABLED`.

world.py never writes civics.json — it only enqueues a clamped delta into
`data/world/approval-queue.json` for the statehouse's own gated tick to
drain later through its `_EVENT_DELTA` table (full-causal.md §6, §11 B4).
This file's load-bearing property is GATE-OFF INERTNESS: with the flag
absent (the shipped default per world-spine-final.md), the edge must be a
total no-op — not just "returns nothing", but "never even creates the
queue file" — so flipping CAUSAL-ENABLED off at any moment reverts the
whole edge with zero on-disk trace to clean up.

Self-contained: every case points `world.WORLD`/`world.SEASON_JSON`/
`world.CAUSAL_FLAG`/`world.APPROVAL_QUEUE` at a fresh temp dir.

Run directly (no pytest needed):  python3 tests/test_world_causal.py
"""
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
    d = Path(tempfile.mkdtemp(prefix="world-causal-"))
    world.WORLD = d / "world-events.json"
    world.SEASON_JSON = d / "season.json"
    world.BOX_DIR = d / "box"
    world.BIBLE = d / "bible.md"
    world.CAUSAL_FLAG = d / "data" / "world" / "CAUSAL-ENABLED"
    world.APPROVAL_QUEUE = d / "data" / "world" / "approval-queue.json"
    return d


def gate_on():
    world.CAUSAL_FLAG.parent.mkdir(parents=True, exist_ok=True)
    world.CAUSAL_FLAG.write_text("")


D1, D2, D3, D4 = "2026-07-09", "2026-07-10", "2026-07-11", "2026-07-12"


def cup_season(day, team, stage, series=None):
    return {"season": 3, "slates": {},
            "cup_runs": {day: [{"team": team, "stage": stage, "series": series}]}}


def no_op_fetch(coords):
    return None            # weather stays out of the picture for this file


# =====================================================================
# 1. GATE-OFF INERTNESS — the load-bearing property
# =====================================================================
d = fresh_paths()
check(world.causal_on() is False, "causal_on(): false by default (flag absent)")

season = cup_season(D1, "mtl", "round2_win", "3-1")
bundle = world.tick(D1, fetch_fn=no_op_fetch, season=season, box={},
                     bible_text=None)
check(bundle["causal"] == [], "tick(): gate off => causal bundle is empty")
check(not world.APPROVAL_QUEUE.exists(),
      "gate off => tick() never creates the queue file")
check(not world.APPROVAL_QUEUE.parent.exists() or
      not any(world.APPROVAL_QUEUE.parent.iterdir()),
      "gate off => not even the queue's parent dir gets stray files")

# calling the drain function directly, repeatedly, on a day with a real
# cup_run sitting on the bus (consumable, next-day) — still nothing
for _ in range(3):
    r = world.enqueue_causal(D2, now=9e9)
    check(r == [], "gate off => enqueue_causal() returns [] every call")
check(not world.APPROVAL_QUEUE.exists(),
      "gate off => repeated calls never create the queue file")

# a totally malformed/absent CAUSAL_FLAG path (parent dir doesn't even
# exist) must not raise
world.CAUSAL_FLAG = Path("/nonexistent-dir-xyz/CAUSAL-ENABLED")
check(world.causal_on() is False, "causal_on(): unreadable path => False, no throw")
check(world.enqueue_causal(D2, now=9e9) == [],
      "enqueue_causal(): unreadable flag path degrades to inert, no throw")


# =====================================================================
# 2. gate ON — the edge actually fires, correctly
# =====================================================================
fresh_paths()
gate_on()
check(world.causal_on() is True, "causal_on(): true once the flag exists")

season = cup_season(D1, "mtl", "round2_win", "3-1")
world.tick(D1, fetch_fn=no_op_fetch, season=season, box={}, bible_text=None)
# D1's cup_run is a league (cross-engine OUTPUT) event -> next-day rule ->
# consumable on D2, not D1
check(world.enqueue_causal(D1, now=9e9) == [],
      "next-day rule: a cup_run dated D1 is not yet consumable on D1")
entries = world.enqueue_causal(D2, now=9e9)
check(len(entries) == 1, "gate on: the cup_run delta is queued exactly once")
e = entries[0]
check(e["team"] == "mtl" and e["stage"] == "round2_win",
      "queued entry carries the team/stage through")
check(e["delta"] == 1.0, "queued entry's delta matches the stage table (round2_win)")
check(e["source"] == f"league.cup_run:{D1}:mtl:round2_win",
      "queued entry cites its source bus-event id for provenance")
check(world.APPROVAL_QUEUE.exists(), "gate on: the queue file now exists")

on_disk = json.loads(world.APPROVAL_QUEUE.read_text())
check(on_disk["days"][D2] == entries,
      "queue file on disk matches what enqueue_causal returned")


# =====================================================================
# 3. delta table + clamping
# =====================================================================
fresh_paths()
gate_on()
cases = [("round1_win", 0.5), ("round2_win", 1.0), ("round3_win", 1.5),
         ("champion", 3.0), ("early_exit", -0.5)]
for i, (stage, want) in enumerate(cases):
    day = f"2026-08-{i + 1:02d}"
    nxt = f"2026-08-{i + 2:02d}"
    season = cup_season(day, "reg", stage)
    world.tick(day, fetch_fn=no_op_fetch, season=season, box={}, bible_text=None)
    got = world.enqueue_causal(nxt, now=9e9)
    check(len(got) == 1 and got[0]["delta"] == want,
          f"delta table: {stage} -> {want} (got {got})")
    check(abs(got[0]["delta"]) <= world._CUP_DELTA_CLAMP,
          f"delta clamp: {stage}'s delta never exceeds the clamp")

# an unrecognized stage (schema drift / a future stage not yet in the table)
# is silently skipped, never a crash, never an unbounded delta
fresh_paths()
gate_on()
season = cup_season(D1, "mtl", "mystery_stage_v9")
world.tick(D1, fetch_fn=no_op_fetch, season=season, box={}, bible_text=None)
check(world.enqueue_causal(D2, now=9e9) == [],
      "unknown cup_run stage => skipped, not queued, no throw")
check(not world.APPROVAL_QUEUE.exists(),
      "unknown-stage-only day => queue file still never created (nothing to queue)")


# =====================================================================
# 4. idempotency + append-only day-keyed queue
# =====================================================================
fresh_paths()
gate_on()
season = cup_season(D1, "mtl", "champion")
world.tick(D1, fetch_fn=no_op_fetch, season=season, box={}, bible_text=None)
first = world.enqueue_causal(D2, now=9e9)
before = json.loads(world.APPROVAL_QUEUE.read_text())
for _ in range(3):
    again = world.enqueue_causal(D2, now=9e9)
    check(again == first, "re-queuing an already-queued day returns the same entries")
after = json.loads(world.APPROVAL_QUEUE.read_text())
check(before == after, "re-queuing an already-queued day never rewrites the file")

# a second, later cup_run on a different day appends a new day-key; the
# first day's entry is untouched (append-only across days too)
season2 = cup_season(D3, "hfx", "early_exit")
world.tick(D3, fetch_fn=no_op_fetch, season=season2, box={}, bible_text=None)
world.enqueue_causal(D4, now=9e9)
q = json.loads(world.APPROVAL_QUEUE.read_text())
check(set(q["days"]) == {D2, D4}, "queue accumulates day-keys, append-only")
check(q["days"][D2] == first, "an earlier day's queued entries are never mutated")


# =====================================================================
# 5. flipping the gate back off mid-flight
# =====================================================================
fresh_paths()
gate_on()
season = cup_season(D1, "mtl", "round1_win")
world.tick(D1, fetch_fn=no_op_fetch, season=season, box={}, bible_text=None)
world.enqueue_causal(D2, now=9e9)
check(world.APPROVAL_QUEUE.exists(), "sanity: queue exists after a live enqueue")
snapshot = json.loads(world.APPROVAL_QUEUE.read_text())

world.CAUSAL_FLAG.unlink()                 # gate flips back off
check(world.causal_on() is False, "gate can be flipped back off")
season3 = cup_season(D3, "hfx", "champion")
world.tick(D3, fetch_fn=no_op_fetch, season=season3, box={}, bible_text=None)
r = world.enqueue_causal(D4, now=9e9)
check(r == [], "gate off again => no further enqueuing, even with a fresh cup_run")
still = json.loads(world.APPROVAL_QUEUE.read_text())
check(still == snapshot,
      "gate off again => the existing queue file is left exactly as it was")


# ------------------------------------------------------------------- summary
print(f"\nworld_causal {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
