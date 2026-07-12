"""Election Night returns-clock fixtures: window-scaled precinct drop
offsets, the monotonic reveal feeding sheets.election_sheet, the beat plan,
and the civicguard-shaped facts_at truth table — Row 4, town-texture/engines.

Run directly (no pytest):  python3 tests/test_statehouse_returns.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.statehouse import returns as R          # noqa: E402
from src.statehouse import elections as EL        # noqa: E402
from src.statehouse import sheets as SH           # noqa: E402
from src.statehouse import civicguard as CG       # noqa: E402

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


CYCLE = 2026
GA = 1
MEMBERS = {
    "members": {
        "H-03": {"name": "Doreen Vachon", "party": "round"},
        "S-01": {"name": "Earl Thibodeau", "party": "prov"},
    },
    "officials": {"potholes": {"name": "Bert Demers"}},
}
WINDOW = 21600          # 19:00-01:00, the booked air window (6h)
SEED = "election-night:2026-11-03"

el = EL.generate_cycle(CYCLE, MEMBERS, GA)
plan = R.build_night(el, WINDOW, SEED)

# --------------------------------------------------------------- build_night

check(plan["cycle"] == CYCLE, "plan carries cycle")
check(plan["window_secs"] == WINDOW, "plan carries window")
check(plan["seed"] == SEED, "plan carries seed")

# every physical precinct assigned exactly once
all_pids = {p["id"] for race in el["races"].values() for p in race["precincts"]}
check(set(plan["offsets"].keys()) == all_pids,
      "every physical precinct has one drop offset")

# offsets in-window (or None for rainouts); rainouts never report
rainout_pids = {p["id"] for race in el["races"].values()
                for p in race["precincts"] if p.get("rainout")}
for pid, off in plan["offsets"].items():
    if pid in rainout_pids:
        check(off is None, f"rainout precinct {pid} never reports")
    else:
        check(off is not None and 0 <= off < WINDOW,
              f"{pid} offset {off} inside [0,{WINDOW})")

# canon overrides: pharmacy lot first, Halfway central count last
if plan["offsets"].get("PHLOT-1") is not None:
    check(plan["offsets"]["PHLOT-1"] == 0, "PHLOT-1 (pharmacy lot) drops first")
if plan["offsets"].get("HFWC-1") is not None:
    check(plan["offsets"]["HFWC-1"] == WINDOW - 1, "HFWC-1 drops last")

# determinism: same inputs -> byte-identical plan
plan2 = R.build_night(el, WINDOW, SEED)
check(plan["offsets"] == plan2["offsets"], "build_night deterministic")
check(R.build_night(el, WINDOW, "other-seed")["offsets"] != plan["offsets"],
      "a different seed reshuffles the drop order")

# wave banding: wave-1 precincts (early trickle) never land after wave-3 ones
def _wave_of(pid):
    for race in el["races"].values():
        for p in race["precincts"]:
            if p["id"] == pid:
                return p["wave"]
w1 = [plan["offsets"][p] for p in all_pids
      if _wave_of(p) == 1 and plan["offsets"][p] is not None]
w3 = [plan["offsets"][p] for p in all_pids
      if _wave_of(p) == 3 and plan["offsets"][p] is not None]
if w1 and w3:
    check(max(w1) <= max(w3), "wave-1 trickle precedes the wave-3 stragglers")

# --------------------------------------------------------------- reveal_at

r0 = R.reveal_at(plan, el, 0)
rmid = R.reveal_at(plan, el, WINDOW // 2)
rend = R.reveal_at(plan, el, WINDOW)

# shape matches elections.reveal exactly (drops into election_sheet)
ref = EL.reveal(el, 0)
check(set(r0.keys()) == set(ref.keys()) == {"pct_in", "races"},
      "reveal_at top-level shape matches elections.reveal")
sample_rid = next(iter(r0["races"]))
check(set(r0["races"][sample_rid].keys()) ==
      {"tally", "wave", "status", "precincts_out", "precincts_total"},
      "per-race shape matches elections.reveal")

check(r0["pct_in"] <= rmid["pct_in"] <= rend["pct_in"], "pct_in non-decreasing")
check(rend["pct_in"] >= 90, "by window end nearly all precincts are in")

# at cursor 0 only PHLOT-1's wave (offset 0) has landed -> not everything
check(r0["pct_in"] < 100, "cursor 0 is not a finished count")

# monotonicity: sweep the window, no tally or status ever regresses
STATUS_RANK = {"too-early": 0, "leaning": 1, "called": 2, "recount": 2}
prev = None
mono_ok = True
for c in range(0, WINDOW + 1, WINDOW // 20):
    rv = R.reveal_at(plan, el, c)
    if prev is not None:
        for rid, cur in rv["races"].items():
            p = prev["races"][rid]
            if cur["precincts_out"] < p["precincts_out"]:
                mono_ok = False
            if sum(cur["tally"]) < sum(p["tally"]):
                mono_ok = False
            if STATUS_RANK[cur["status"]] < STATUS_RANK[p["status"]]:
                mono_ok = False
    prev = rv
check(mono_ok, "reveal_at monotonic across the window (tally/precincts/status)")

# every reportable precinct is in at window end; rainouts stay out
for rid, race in el["races"].items():
    reportable = [p for p in race["precincts"] if not p.get("rainout")]
    check(rend["races"][rid]["precincts_out"] == len(reportable),
          f"{rid}: all reportable precincts in at end")

# reveal_at output feeds election_sheet without error, tracked tally shown
tid = "H-01"
sheet_txt = SH.election_sheet(WINDOW, rend, tracked_id=tid)
check("ELECTION NIGHT" in sheet_txt and f"TRACKED RACE {tid}" in sheet_txt,
      "reveal_at drives sheets.election_sheet")

# reveal_at deterministic
check(R.reveal_at(plan, el, 5000) == R.reveal_at(plan, el, 5000),
      "reveal_at deterministic")

# --------------------------------------------------------------- beat_plan

beats = R.beat_plan(360)          # a 6-hour show
ids = [b["beat"] for b in beats]
check(ids == ["open", "board", "analyst", "call-watch", "the-call", "wrap"],
      "beat ids in registry order")
cursors = [b["target_cursor"] for b in beats]
check(cursors == sorted(cursors), "beat target cursors non-decreasing")
check(cursors[0] == 0, "the desk opens at cursor 0")
check(all(0 <= c <= 360 * 60 for c in cursors), "beat cursors inside the show")
# the four registry-backed beats carry their verbatim segment string
check(beats[0]["segment"].startswith("The Desk Opens"), "open segment verbatim")
check(beats[4]["segment"].startswith("The Call"), "the-call segment verbatim")
check(beats[3]["segment"] is None and beats[3]["label"],
      "call-watch has no registry segment but a label")
# zero-length show degrades gracefully
check(all(b["target_cursor"] == 0 for b in R.beat_plan(0)),
      "beat_plan(0) collapses to cursor 0")

# --------------------------------------------------------------- facts_at

facts = R.facts_at(plan, el, WINDOW // 3, "H-01")
check(facts["mode"] == "election_sheet", "facts_at builds election-mode facts")
check(facts["tracked_id"] == "H-01", "facts_at carries tracked_id")
check(facts["election"] is not None, "facts_at populates the election slot")
check(facts["election"]["races_ok"] == set(el["races"].keys()),
      "facts_at knows every race id")
# candidate surnames are grounded for name-fix / premature-call checks
some_cand = el["races"]["H-01"]["cands"][0]["name"]
check(some_cand.lower() in facts["names_ok"], "candidate names grounded")

# facts_at output actually drives enforce_civic: a premature race call at a
# cursor where H-01 is NOT yet 'called' gets replaced.
early = R.facts_at(plan, el, 0, "H-01")
h01_status = R.reveal_at(plan, el, 0)["races"]["H-01"]["status"]
if h01_status != "called":
    inc = el["races"]["H-01"]["cands"][0]
    surname = inc["name"].split()[-1]
    lines = [{"text": f"{inc['name']} wins H-01, no question about it."}]
    guarded = CG.enforce_civic(lines, early)
    check(guarded[0].get("_enforced") and "wins" not in guarded[0]["text"].lower(),
          "facts_at lets civicguard block a premature race call")

# a truthful line about a called race at window end passes untouched
called = [rid for rid, r in rend["races"].items() if r["status"] == "called"]
if called:
    rid = called[0]
    end_facts = R.facts_at(plan, el, WINDOW, rid)
    winner = el["races"][rid]["cands"]
    a, b = rend["races"][rid]["tally"]
    win = winner[0 if a >= b else 1]
    lines = [{"text": f"{win['name']} is re-elected in {rid}."}
             if win.get("inc") else {"text": f"{win['name']} wins {rid}."}]
    guarded = CG.enforce_civic(lines, end_facts)
    check(not guarded[0].get("_enforced"),
          "a truthful call on a called race passes civicguard untouched")

print(f"\nstatehouse returns {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
