"""Arcs engine fixtures: the code-owned state machine's full lifecycle (birth
via a mocked author -> beats -> stage advance -> force-air payoff ->
retirement -> lore graduation), register routing, determinism, store IO, and
byte-identical compatibility with arcs.py's existing callers (orchestrator's
daily_tick call site, lore.py's digest usage on the legacy inline shape).

Run directly (no pytest needed):  python3 tests/test_arcs_engine.py
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import arcs

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def fresh_state():
    return {"schema": 1, "seq": 0, "arcs": {}, "recent_settings": []}


SKELETON = {
    "title": "The Roundabout Fern", "premise": "a fern appears in the roundabout",
    "register": "mundane", "setting": "the Mile Zero roundabout",
    "cast": {"civilians": ["cv-doreen-2"], "canon": ["Toivo Ostberg"]},
    "lifespan_days": 3,
    "beats": [
        {"stage": "SEEDED", "directive": "a fern appears", "fact": "a fern is at the roundabout"},
        {"stage": "PAYOFF", "directive": "the town adopts it", "fact": "the fern was adopted"},
    ],
}


def mock_author(models, date, avoid):
    return copy.deepcopy(SKELETON)


def failing_author(models, date, avoid):
    raise RuntimeError("model unavailable")


# =========================================================== state machine
# birth -> beats -> stage advance -> payoff_on force-air -> retirement -> lore

st = fresh_state()
arcs.daily_tick({}, st, date="2026-07-01", author_fn=mock_author)
check(len(st["arcs"]) == 1 and st["seq"] == 1, "birth mints exactly one arc via author_fn")
arc = st["arcs"]["arc-0001"]
check(arc["stage"] == "SEEDED" and arc["status"] == "active", "new arc opens SEEDED/active")
check(arc["beats"][0]["stage"] == "SEEDED" and arc["beats"][-1]["stage"] == "PAYOFF",
      "frozen beat chain starts SEEDED, ends PAYOFF")
check(arc["payoff_on"] == "2026-07-04", "payoff_on is opened + clamped lifespan (3d)")
check(all(f["aired"] is None for f in arc["facts"]),
      "every fact starts unaired (including the payoff spoiler)")
check(arc["setting"] in st["recent_settings"],
      "birth records its setting in recent_settings for variety")

# a second daily_tick before anything airs must NOT mint a second arc past
# MAX_ACTIVE, and must leave the unaired arc alone (no phantom advance)
arcs.daily_tick({}, st, date="2026-07-01", author_fn=mock_author)
check(len(st["arcs"]) == 2, "seed-replacement fills up to MAX_ACTIVE (2)")
arcs.daily_tick({}, st, date="2026-07-01", author_fn=mock_author)
check(len(st["arcs"]) == 2, "no third arc once MAX_ACTIVE is reached")

# air the SEEDED beat -> advance moves the stage cursor to PAYOFF
b1 = arc["beats"][0]
arcs.mark_aired(arc, b1["bid"], "2026-07-01", "a fern shows up on Culture Vulture")
check(b1["status"] == "aired" and b1["aired_date"] == "2026-07-01", "mark_aired flips status+date")
check(arc["facts"][0]["aired"] == "2026-07-01", "mark_aired stamps the matching facts-table row")
check(arc["latest"] == "a fern shows up on Culture Vulture", "mark_aired refreshes the digest line")
arcs.advance(arc, "2026-07-01")
check(arc["stage"] == "PAYOFF" and arc["stage_idx"] == 1,
      "advance moves the cursor past an aired beat onto the next stage")

# mark_aired is idempotent for a repeat call with the same bid+text
before = json.loads(json.dumps(arc))
arcs.mark_aired(arc, b1["bid"], "2026-07-01", "a fern shows up on Culture Vulture")
check(arc == before, "mark_aired no-ops on an already-aired bid (same call)")

# --- payoff_on force-air: an arc past its window whose payoff never fired ---
arcs.daily_tick({}, st, date="2026-07-10", author_fn=mock_author)
arc = st["arcs"]["arc-0001"]
check(arc["force_payoff"] is True,
      "past payoff_on with prior stages aired -> force_payoff flag set")
payoff_show = arc["beats"][-1]["show"]
nb = arcs.next_beat(arc, "2026-07-10", payoff_show)
check(nb is not None and nb["stage"] == "PAYOFF",
      "next_beat surfaces the payoff beat under force_payoff regardless of its own due date")
check(arcs.gate_payoff(arc, "2026-07-10", payoff_show) is True,
      "gate_payoff opens once prior stages aired and the force window is active")
check(arcs.gate_payoff(arc, "2026-07-10", "static_hour") is False,
      "gate_payoff still respects register routing even under force_payoff")

# --- fire the payoff, then retirement + lore graduation --------------------
lore_state = {"recent_callbacks": []}
arcs.mark_aired(arc, nb["bid"], "2026-07-10", "PAYOFF: the fern is adopted, ribbon and all")
check(arc["facts"][-1]["aired"] == "2026-07-10", "payoff fact stamped only once it actually airs")
arcs.daily_tick({}, st, date="2026-07-10", author_fn=mock_author, lore_state=lore_state)
arc = st["arcs"]["arc-0001"]
check(arc["status"] == "resolving" and arc["stage"] == "LORE",
      "an aired payoff demotes the arc to resolving/LORE the same day")
check(arc["graduated"] is True, "graduated flag set exactly once on resolution")
check(lore_state["recent_callbacks"] == ["the fern was adopted"],
      "the payoff's epitaph graduates one-way into lore.recent_callbacks")
# re-ticking the same resolved day must not re-graduate (no duplicate callback)
arcs.daily_tick({}, st, date="2026-07-10", author_fn=mock_author, lore_state=lore_state)
check(lore_state["recent_callbacks"] == ["the fern was adopted"],
      "graduation does not duplicate on a repeat same-day tick")

arcs.daily_tick({}, st, date="2026-07-11", author_fn=mock_author, lore_state=lore_state)
arc = st["arcs"]["arc-0001"]
check(arc["status"] == "retired", "a resolving arc lingers one day then retires")
d = arcs.digest(st)
check("arc-0001" not in json.dumps(d) and "Roundabout Fern" not in d,
      "a retired arc drops out of the digest")

# --- fallback author: a bad/absent model reply never blocks a slot ---------
st2 = fresh_state()
arcs.daily_tick({}, st2, date="2026-07-01", author_fn=failing_author)
check(len(st2["arcs"]) == 1, "author_fn failure falls back to a code-only premise")
fb = next(iter(st2["arcs"].values()))
check(fb["beats"][-1]["stage"] == "PAYOFF" and fb["status"] == "active",
      "fallback arc is a well-formed, schedulable skeleton")

# --- anti-skip: payoff never schedules/fires before all prior stages -------
st3 = fresh_state()
arcs.daily_tick({}, st3, date="2026-07-01", author_fn=mock_author)
arc3 = next(iter(st3["arcs"].values()))
# do NOT air the SEEDED beat; jump straight to the force-air window
arcs.daily_tick({}, st3, date="2026-07-20", author_fn=mock_author)
arc3 = st3["arcs"][arc3["id"]]
check(arc3["force_payoff"] is False,
      "force_payoff never sets while an earlier stage is still unaired (no skip)")
show3 = arc3["beats"][-1]["show"]
check(arcs.next_beat(arc3, "2026-07-20", show3) is None,
      "next_beat refuses the payoff beat while a prior beat is unaired")
check(arcs.gate_payoff(arc3, "2026-07-20", show3) is False,
      "gate_payoff refuses to open while a prior beat is unaired")

# --- preempted beat rolls forward, never fires early ------------------------
st4 = fresh_state()
longer = copy.deepcopy(SKELETON)
longer["lifespan_days"] = 6
longer["beats"] = [
    {"stage": "SEEDED", "directive": "d1", "fact": "f1"},
    {"stage": "RISING", "directive": "d2", "fact": "f2"},
    {"stage": "PAYOFF", "directive": "d3", "fact": "f3"},
]
arcs.daily_tick({}, st4, date="2026-07-01", author_fn=lambda m, d, a: copy.deepcopy(longer))
a4 = next(iter(st4["arcs"].values()))
b0 = a4["beats"][0]
arcs.mark_aired(a4, b0["bid"], "2026-07-01", "seeded")
arcs.advance(a4, "2026-07-01")
rising_due_before = a4["beats"][1]["due"]
# jump forward past the RISING beat's due date without it ever airing
arcs.daily_tick({}, st4, date="2026-07-15", author_fn=lambda m, d, a: copy.deepcopy(longer))
a4 = st4["arcs"][a4["id"]]
check(a4["beats"][1]["due"] == "2026-07-15",
      "a preempted (past-due, unaired) beat rolls forward onto today")
check(a4["beats"][1]["due"] >= rising_due_before,
      "the rescheduled due date never moves earlier than its original slot")
check(a4["beats"][1]["status"] != "aired", "rescheduling never marks a beat aired early")


# =========================================================== register routing
check(arcs.register_ok("static_hour") == set(), "the Watcher hosts no town arcs (lore_quarantine)")
check(arcs.register_ok("center_ice") == set(), "Center Ice runs its own sports engine, no town arcs")
check(arcs.register_ok("dawn_patrol") == set(), "Dawn Patrol (ambient) hosts no town arcs")
check("dreamcourt" in arcs.register_ok("night_shift"), "Night Shift owns the dreamcourt register")
check("mundane" in arcs.register_ok("night_shift"), "Night Shift also carries mundane texture")
check(arcs.register_ok("morning_scramble") == {"mundane", "civic"},
      "daytime talk carries mundane/civic only (anti-conspiracy register guard)")
check("static_hour" not in arcs.shows_for_register("mundane"),
      "shows_for_register never includes the quarantined Watcher for any town register")
check("conspiracy" not in {r for regs in arcs.REGISTER_OK.values() for r in regs},
      "no show is ever routed the conspiracy register (Watcher-only, quarantined)")

# a dreamcourt arc must never surface on a daytime show even if forced
dc_arc = arcs.new_arc(
    {**SKELETON, "register": "dreamcourt", "title": "Dream Court"}, "2026-07-01", 99)
dc_arc["force_payoff"] = True
for b in dc_arc["beats"][:-1]:
    b["status"] = "aired"
check(arcs.next_beat(dc_arc, "2026-07-01", "morning_scramble") is None,
      "a dreamcourt arc never surfaces on a daytime (mundane/civic-only) show")
check(arcs.next_beat(dc_arc, "2026-07-01", "night_shift") is not None,
      "the same dreamcourt arc DOES surface on Night Shift, its home register")
check(dc_arc["register"] == "dreamcourt", "dreamcourt register is honored, not silently downgraded")


# =========================================================== determinism
seed_state_a = fresh_state()
seed_state_b = fresh_state()
arcs.daily_tick({}, seed_state_a, date="2026-08-01", author_fn=mock_author)
arcs.daily_tick({}, seed_state_b, date="2026-08-01", author_fn=mock_author)
check(seed_state_a == seed_state_b,
      "daily_tick is deterministic: identical (date, author reply) -> byte-identical state")

arc_a = arcs.new_arc(SKELETON, "2026-07-01", 7)
arc_b = arcs.new_arc(SKELETON, "2026-07-01", 7)
check(arc_a == arc_b, "new_arc is a pure function of (skeleton, date, seq)")
dues_first = [b["due"] for b in arc_a["beats"]]
shows_first = [b["show"] for b in arc_a["beats"]]
arcs.schedule_beats(arc_a)
check([b["due"] for b in arc_a["beats"]] == dues_first
      and [b["show"] for b in arc_a["beats"]] == shows_first,
      "schedule_beats is idempotent when nothing new has aired")


# =========================================================== store IO
tmpdir = Path(tempfile.mkdtemp())
p = tmpdir / "arcs.json"
check(arcs.load(p) == {"schema": 1, "seq": 0, "arcs": {}, "recent_settings": []},
      "missing sidecar -> the empty default (never blocks the station)")
sample = fresh_state()
arcs.daily_tick({}, sample, date="2026-07-01", author_fn=mock_author)
arcs.save(sample, p)
check(p.exists(), "save writes the live file")
got = arcs.load(p)
check(got["arcs"].keys() == sample["arcs"].keys(), "save/load round-trips arcs")
arcs.save(sample, p)  # second save produces a good .bak of the first
bak = Path(str(p) + ".bak")
check(bak.exists(), "save keeps a .bak sidecar")
p.write_text("{ not json at all")
recov = arcs.load(p)
check(recov["arcs"].keys() == sample["arcs"].keys(), "a corrupt live file falls back to .bak")
p.write_text("not even an object")
bak.write_text("also not json")
check(arcs.load(p) == {"schema": 1, "seq": 0, "arcs": {}, "recent_settings": []},
      "both live and .bak corrupt -> the empty default, never a crash")


# =========================================================== caller-compat
# The ONLY live caller today (src/orchestrator.py L334): arcs.daily_tick(models,
# state) on the big lore_state dict, where state["arcs"] is a LIST (no
# "schema" key) — the pre-rewrite inline shape. Gate-off must be byte-identical
# to the original module (git HEAD) for both the daily_tick transform and the
# digest string lore.py builds from it.

def legacy_digest_reference(lore_state: dict) -> str:
    """Verbatim copy of the ORIGINAL (pre-rewrite) arcs.digest, to prove the
    new module's legacy path renders byte-identically."""
    lines = []
    for a in lore_state.get("arcs", []):
        tag = "PAYS OFF TODAY" if a.get("status") == "done" else \
              f"day {a.get('day', '?')} of {a.get('max_days', '?')}"
        lines.append(f"- {a['title']} ({tag}): {a['latest']}")
    return ("ONGOING STATION STORYLINES (weave in naturally, a line or two, "
            "when it fits):\n" + "\n".join(lines)) if lines else ""


legacy_fixtures = [
    {"arcs": []},
    {"arcs": [{"title": "The Sock Ceasefire", "day": 2, "max_days": 4,
               "latest": "the neighbor counts clothespins", "status": "active"}]},
    {"arcs": [{"title": "The Goose", "day": 5, "max_days": 5,
               "latest": "granted the lot in perpetuity", "status": "done"}]},
]
for lf in legacy_fixtures:
    check(arcs.digest(lf) == legacy_digest_reference(lf),
          f"legacy digest byte-identical to the original module ({lf['arcs'][:1]})")

check(arcs._is_legacy({"arcs": []}), "no-schema, list-shaped arcs -> legacy path")
check(arcs._is_legacy({"arcs": [{"title": "x"}]}), "populated legacy list -> legacy path")
check(not arcs._is_legacy({"schema": 1, "arcs": {}}), "schema+dict arcs -> the new sidecar path")
check(not arcs._is_legacy({"schema": 1, "arcs": [{"title": "x"}]}),
      "a 'schema' key alone routes to the new path even with list-shaped arcs "
      "(documents the field the router keys on; real lore_state never sets it)")

# exact orchestrator.py call shape: arcs.daily_tick(models, state) — 2 positional
# args, `state` the full legacy lore_state dict. Monkeypatch chat exactly like
# the LLM boundary the original module also crossed.
_orig_chat = arcs.chat
canned_reply = json.dumps({"arcs": [
    {"title": "The Sock Ceasefire", "premise": "p", "day": 3, "max_days": 4,
     "latest": "a laminated note appears", "status": "active"},
    {"title": "The Goose", "premise": "p2", "day": 5, "max_days": 5,
     "latest": "granted the lot", "status": "done"},
]})
arcs.chat = lambda model_cfg, messages: canned_reply
try:
    live_state = {"arcs": [], "recent_premises": [], "running_jokes": [],
                  "feuds": [], "recent_callbacks": []}
    models = {"writer": {"model": "test/model"}}
    arcs.daily_tick(models, live_state)   # the exact orchestrator.py call site
    check(len(live_state["arcs"]) == 2, "legacy daily_tick parses the canned reply")
    check(live_state["arcs"][0]["status"] == "active"
          and live_state["arcs"][1]["status"] == "done",
          "legacy daily_tick keeps active[:MAX_ACTIVE] + done[:1], same as original")

    # reference (original-module) transform on the same canned reply
    active_ref = [a for a in json.loads(canned_reply)["arcs"] if a.get("status") == "active"]
    keep_ref = [a for a in json.loads(canned_reply)["arcs"]
                if a.get("title") and a.get("latest")]
    ref_arcs = [a for a in keep_ref if a.get("status") == "active"][:arcs.MAX_ACTIVE] \
        + [a for a in keep_ref if a.get("status") == "done"][:1]
    check(live_state["arcs"] == ref_arcs,
          "legacy daily_tick transform is byte-identical to the original module")

    d = arcs.digest(live_state)
    check(d == legacy_digest_reference(live_state),
          "digest on the post-tick legacy state matches the original module")
finally:
    arcs.chat = _orig_chat

# lore.py's own call site: `arcs.digest(state)` where state is the big
# lore_state dict (src/lore.py L118) — same object, same call shape.
lore_like = {"arcs": [{"title": "T", "day": 1, "max_days": 3,
                        "latest": "L", "status": "active"}],
             "running_jokes": [], "feuds": [], "recent_callbacks": []}
check(arcs.digest(lore_like) == legacy_digest_reference(lore_like),
      "lore.py's digest(state) call site renders byte-identically")

print(f"\narcs {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
