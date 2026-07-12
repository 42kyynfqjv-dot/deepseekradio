"""Special-events overlay fixtures (Track D, component 3).

Pure composition: no active event => eff IS base (identity); event blocks are
date-gated and prepended so they win their window; the date gate is wrap-aware
so Election Night rides continuously across midnight; a playoff night on the
static Wed/Sat slot dedupes so the game never double-books; priority breaks a
two-event window clash; and the memo re-resolves the instant a gate flips.

Self-contained fixtures (ctx dicts + a fake deriver) — no sidecars, no I/O.

Run directly (no pytest needed):  python3 tests/test_events_compose.py
"""
import sys
import time
from datetime import date as _date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.events import compose

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


# ── fixtures ─────────────────────────────────────────────────────────────────
def base_schedule(weekday="Wednesday"):
    """A miniature schedule.yaml: the day-gated center_ice block FIRST, then two
    everyday blocks that cover the evening on off days."""
    return {"dayparts": [
        {"id": "center_ice", "show": "Center Ice", "days": [weekday, "Saturday"],
         "window": ["20:00", "23:00"], "cast": ["bucky", "sal"]},
        {"id": "culture_vulture", "show": "Culture Vulture",
         "window": ["19:00", "22:00"], "cast": ["cosima"]},
        {"id": "night_shift", "show": "The Night Shift",
         "window": ["22:00", "01:00"], "cast": ["vivian"]},
    ]}


ELECTION = {
    "id": "election_night", "engine": "election_night",
    "dates": ["2026-11-03"], "gate": None,
    "window": ["19:00", "01:00"], "priority": 90,
    "show": {"show": "Election Night", "cast": ["vivian", "cosima"], "news": False},
    "site": {"name": "Election Night", "hook": "Live returns.", "who": "THE DESK"},
    "promo": {"lead_days": 7, "copy": ["Wending votes Tuesday."]},
}

ELECTION_GATED = dict(ELECTION, gate="data/statehouse/ELECTION-ENABLED")

PLAYOFF = {
    "id": "playoff_night", "engine": "center_ice", "deriver": "playoff_nights",
    "gate": None, "window": ["20:00", "23:00"], "priority": 50,
    "show": {"show": "Center Ice — Playoffs", "cast": ["bucky", "sal"]},
    "site": {"name": "Center Ice — Playoffs"},
    "promo": {"lead_days": 4, "copy": []},
}

DECOY = {  # overlaps Election Night's window but at lower priority
    "id": "decoy", "engine": "blizzard", "dates": ["2026-11-03"], "gate": None,
    "window": ["20:00", "22:00"], "priority": 40,
    "show": {"show": "Decoy"}, "site": {"name": "Decoy"},
    "promo": {"lead_days": 0, "copy": []},
}


def playoff_deriver_for(target_date):
    """A fake playoff_nights: emits the target date with plausible meta."""
    def _fn(ctx):
        if compose._field(ctx, "today") == target_date:
            return [{"date": target_date,
                     "meta": {"round": 1, "home": "mtl", "away": "nyg",
                              "arena": "the Pardon Centre"}}]
        return []
    return _fn


def ctx(today, records, *, derivers=None, gate_stats=(), registry_mtime=1.0,
        sidecar_mtimes=()):
    return {"today": today, "horizon": today, "records": records,
            "derivers": derivers or {}, "gate_stats": gate_stats,
            "registry_mtime": registry_mtime, "sidecar_mtimes": sidecar_mtimes,
            "tracked": ["mtl", "nyg"]}


# ── active_events: gate, priority clash, deriver ─────────────────────────────
c = ctx("2026-11-03", [ELECTION])
ev = compose.active_events(c)
check(len(ev) == 1 and ev[0]["id"] == "election_night", "literal date resolves today")
check(ev[0]["engine"] == "election_night" and ev[0]["priority"] == 90,
      "active event carries engine + priority")
check(ev[0]["window"] == ["19:00", "01:00"], "active event carries window")
check(ev[0]["promo"]["lead_days"] == 7, "active event carries promo block")

check(compose.active_events(ctx("2026-07-15", [ELECTION])) == [],
      "no record matches today => no active events")

# priority breaks a two-event window clash: election (90) beats decoy (40)
clash = compose.active_events(ctx("2026-11-03", [ELECTION, DECOY]))
check(len(clash) == 1 and clash[0]["id"] == "election_night",
      "priority wins a two-event window clash; loser dropped")

# non-overlapping windows both survive
DECOY_EARLY = dict(DECOY, window=["06:00", "10:00"])
both = compose.active_events(ctx("2026-11-03", [ELECTION, DECOY_EARLY]))
check(len(both) == 2, "non-overlapping windows both stay active")

# derived record: the deriver's emitted date == today resolves
pderiv = {"playoff_nights": playoff_deriver_for("2026-06-10")}
pev = compose.active_events(ctx("2026-06-10", [PLAYOFF], derivers=pderiv))
check(len(pev) == 1 and pev[0]["id"] == "playoff_night", "deriver date resolves today")
check(pev[0]["meta"].get("home") == "mtl", "deriver meta flows onto the active event")
# a derived date that isn't today emits nothing
check(compose.active_events(ctx("2026-06-11", [PLAYOFF], derivers=pderiv)) == [],
      "deriver date != today => not active")

# ── gate arms/disarms resolution ─────────────────────────────────────────────
GATE = "data/statehouse/ELECTION-ENABLED"
armed = compose.active_events(ctx("2026-11-03", [ELECTION_GATED],
                                  gate_stats=((GATE, 123.0),)))
check(len(armed) == 1, "gate present => gated record arms")
disarmed = compose.active_events(ctx("2026-11-03", [ELECTION_GATED],
                                     gate_stats=((GATE, None),)))
check(disarmed == [], "gate absent => gated record inert")

# ── effective_schedule: identity when nothing is active ──────────────────────
compose.clear_cache()
base = base_schedule()
eff_idle = compose.effective_schedule(base, ctx("2026-07-15", [ELECTION]))
check(eff_idle is base, "no active event => eff IS base (identity)")

# ── effective_schedule: event block prepended + date-gated ───────────────────
compose.clear_cache()
base = base_schedule()
eff = compose.effective_schedule(base, ctx("2026-11-03", [ELECTION]))
check(eff is not base, "active event => eff is a new schedule")
top = eff["dayparts"][0]
check(top.get("_event") is True, "event block carries the _event marker")
check(top["id"] == "election_night" and top["date"] == "2026-11-03",
      "event block is prepended, date-stamped to today")
check(top["engine"] == "election_night" and top["window"] == ["19:00", "01:00"],
      "event block copies engine + window")
check(top.get("show") == "Election Night", "show fragment copied verbatim")
check([d["id"] for d in base["dayparts"]] ==
      ["center_ice", "culture_vulture", "night_shift"], "base is not mutated")

# ── dedupe: a playoff night on the static Wed slot never double-books ─────────
compose.clear_cache()
wd = _date.fromisoformat("2026-06-10").strftime("%A")
base = base_schedule(weekday=wd)
effp = compose.effective_schedule(
    base, ctx("2026-06-10", [PLAYOFF], derivers=pderiv))
ids = [d["id"] for d in effp["dayparts"]]
check("playoff_night" in ids, "playoff event block is present")
check(ids.count("center_ice") == 0,
      "static center_ice shadowed away (no double-book)")
# exactly one block owns the 20:00-23:00 window
at2023 = [d for d in effp["dayparts"]
          if compose._windows_overlap(d.get("window"), ["20:00", "23:00"])
          and d.get("engine") == "center_ice"]
check(len(at2023) == 1, "exactly one center_ice engine claims the game window")

# ── the wrap-aware date-gate clause ──────────────────────────────────────────
enight = {"date": "2026-11-03", "window": ["19:00", "01:00"]}


def dm(y, mo, d, h, mi):
    return compose.daypart_matches_date(enight, datetime(y, mo, d, h, mi))


check(dm(2026, 11, 3, 19, 30), "election matches at 19:30 on its date (pre)")
check(dm(2026, 11, 3, 23, 59), "election matches at 23:59 on its date")
check(dm(2026, 11, 4, 0, 0), "election matches at 00:00 next day (post/midnight)")
check(dm(2026, 11, 4, 0, 59), "election matches at 00:59 next day (tail)")
check(not dm(2026, 11, 4, 1, 30), "election has signed off by 01:30 next day")
check(not dm(2026, 11, 3, 18, 0), "election not on air before its window opens")
check(not dm(2026, 11, 2, 20, 0), "election not on air the night before")

# continuity: no gap across the midnight boundary
check(dm(2026, 11, 3, 23, 59) and dm(2026, 11, 4, 0, 0),
      "Election Night is continuous across midnight (no early yank)")

# a same-day (non-wrapping) dated block requires date == today
same = {"date": "2026-06-10", "window": ["20:00", "23:00"]}
check(compose.daypart_matches_date(same, datetime(2026, 6, 10, 21, 0)),
      "same-day dated block matches on its date")
check(not compose.daypart_matches_date(same, datetime(2026, 6, 11, 21, 0)),
      "same-day dated block does NOT match the following day")

# a dateless block is unaffected (behaves exactly as today)
dateless = {"window": ["06:00", "10:00"]}
check(compose.daypart_matches_date(dateless, datetime(2026, 6, 10, 7, 0)),
      "dateless block always matches (unchanged behavior)")

# ── same_air (judge fix 2 comparator) ────────────────────────────────────────
check(compose.same_air({"id": "a", "date": None}, {"id": "a", "date": None}),
      "same_air: same id, both dateless")
check(not compose.same_air({"id": "a", "date": "x"}, {"id": "a", "date": "y"}),
      "same_air: same id, different date differs")
check(compose.same_air({"id": "a", "date": "x"}, {"id": "a", "date": "x"}),
      "same_air: same id+date matches")
check(compose.same_air(None, None) and not compose.same_air(None, {"id": "a"}),
      "same_air: None handling")

# ── engine_of (dispatch key + center_ice fallback) ───────────────────────────
check(compose.engine_of({"engine": "blizzard"}) == "blizzard", "engine_of reads engine")
check(compose.engine_of({"id": "center_ice"}) == "center_ice",
      "engine_of falls back to center_ice by id")
check(compose.engine_of({"id": "morning_scramble"}) is None,
      "engine_of => None for an everyday block")
check(compose.ENGINE_NAMES == compose._registry.VALID_ENGINES,
      "ENGINE_NAMES is the registry's frozen engine roster")

# ── memoization: hit is identity; a gate flip invalidates ────────────────────
compose.clear_cache()
base = base_schedule()
c_on = ctx("2026-11-03", [ELECTION_GATED], gate_stats=((GATE, 123.0),))
eff_on1 = compose.effective_schedule(base, c_on)
eff_on2 = compose.effective_schedule(base, c_on)
check(eff_on1 is eff_on2, "memo hit returns the SAME object (no recompute)")
check(eff_on1 is not base and eff_on1["dayparts"][0]["id"] == "election_night",
      "gate armed => event block present")

# flip the gate off: new key, re-resolves to the evergreen base
c_off = ctx("2026-11-03", [ELECTION_GATED], gate_stats=((GATE, None),))
eff_off = compose.effective_schedule(base, c_off)
check(eff_off is base, "gate cleared => memo invalidates, eff falls back to base")

# flip back on: original armed result is still cached (same key)
eff_on3 = compose.effective_schedule(base, c_on)
check(eff_on3 is eff_on1, "re-arming returns the cached armed schedule")

# ── steady state is ~1ms (a dict lookup) ─────────────────────────────────────
compose.effective_schedule(base, c_on)              # warm
N = 5000
t0 = time.perf_counter()
for _ in range(N):
    compose.effective_schedule(base, c_on)
per = (time.perf_counter() - t0) / N
check(per < 0.001, f"memoized steady state well under 1ms (got {per*1e6:.1f}us)")

# ── build_ctx never raises + carries the frozen fields ───────────────────────
try:
    bc = compose.build_ctx(datetime(2026, 11, 3, 19, 30))
    ok = (bc["today"] == "2026-11-03"
          and "records" in bc and "derivers" in bc
          and "gate_stats" in bc and "registry_mtime" in bc
          and "sidecar_mtimes" in bc and "horizon" in bc)
except Exception as e:
    ok = False
    print(f"  (build_ctx raised: {e})")
check(ok, "build_ctx(datetime) returns a ctx with the frozen fields, never raises")
check(compose.build_ctx("2026-11-03")["today"] == "2026-11-03",
      "build_ctx also accepts an ISO date string (publish._resolve_horizon)")

print(f"\nevents.compose {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
