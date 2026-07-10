"""Assignment desk fixtures: deterministic picks, no reuse, no collisions,
authoritative blocks.  Run:  python3 tests/test_assignments.py
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import assignments as A
from src.performers import _gender_of

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


# caller minting: no reuse, gender deterministic, voice pin agrees
rng = random.Random("desk")
used = set()
for _ in range(30):
    n = A.next_caller(used, rng)
    check(n not in used, f"caller {n} not reused")
    used.add(n)
nf = A.next_caller(set(), random.Random(1), want="f")
nm = A.next_caller(set(), random.Random(1), want="m")
check(_gender_of(nf) == "f", f"female pick {nf} pins female voice")
check(_gender_of(nm) == "m", f"male pick {nm} pins male voice")
check(A.next_caller(set(A.CALLERS_F), random.Random(2), want="f") in
      A.CALLERS_F, "exhausted pool falls back, never crashes")

# guest rotation: seen guests excluded
POOL = ("- **The one-note jazz musician** (voice: am_michael) — x\n"
        "- **A ghost from 1974** (voice: bm_lewis) — y\n"
        "- **The time-traveler** (voice: am_echo) — z\n")
g = A.pick_guest(POOL, ["The one-note jazz musician", "The time-traveler"],
                 random.Random(3))
check(g == "A ghost from 1974", f"recently-seen guests excluded (got {g})")
check(A.pick_guest("", [], random.Random(4)) is None, "empty pool -> None")

# callback: from lore, deterministic per seed
st = {"running_jokes": ["the doorknob review", "Fixture 12"],
      "feuds": ["Hank vs Kai"], "recent_callbacks": []}
cb = A.pick_callback(st, random.Random(5))
check(cb in ("the doorknob review", "Fixture 12", "Hank vs Kai"),
      "callback comes from lore")
check(A.pick_callback({}, random.Random(6)) is None, "no lore -> None")

# props: worn excluded, count honored, no stray non-ascii
props = A.prop_candidates([A.PROPS[0], A.PROPS[1]], random.Random(7), n=10)
check(len(props) == 10 and A.PROPS[0] not in props, "worn props excluded")
check(all(p.isascii() for p in A.PROPS), "prop bank is clean ascii")

# writer block renders all assignments, empty when nothing assigned
blk = A.writer_block("A ghost from 1974", ("SoupCo", "it's soup"),
                     "Fixture 12", ["a jar of pens that all skip"])
check("ASSIGNED: A ghost from 1974" in blk and "SoupCo" in blk
      and "Fixture 12" in blk and "jar of pens" in blk, "block renders all")
check(A.writer_block(None, None, None, []) == "", "no assignments -> empty")

print(f"\nassignments {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
