"""Auto-promo fixtures: in-window selection + template fill, the expires sidecar,
lead_days:0 reactivity, idempotence (no re-synth on an unchanged 2nd pass), the
2-event concurrency cap with 3 overlapping November events, and expiry purge.

Never synthesizes: render_fn is mocked (writes a stub wav, records the call).

Run directly (no pytest needed):  python3 tests/test_events_promo.py
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

# load src/events/promo.py by path — no dependence on the shared package __init__
_SPEC = importlib.util.spec_from_file_location(
    "events_promo", Path(__file__).resolve().parent.parent / "src" / "events" / "promo.py")
promo = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(promo)

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def mock_render():
    """A render_fn that writes a 1-byte stub and logs every (line, out) call."""
    calls = []

    def fn(line, out_path):
        calls.append((line, str(out_path)))
        Path(out_path).write_bytes(b"\0")
        return True

    fn.calls = calls
    return fn


def ev(id, date, lead, copy, priority=50, meta=None):
    return {"id": id, "date": date, "priority": priority,
            "window": ["20:00", "23:00"],
            "promo": {"lead_days": lead, "copy": copy},
            "meta": meta or {}}


# ── in-window selection + template fill from meta + expires sidecar ───────────
with tempfile.TemporaryDirectory() as d:
    r = Path(d)
    e = ev("playoff_night", "2026-06-11", 4,
           ["Game {game}: {away} at {home}. Live {weekday}."],
           meta={"game": 7, "away": "Otters", "home": "Bears", "weekday": "Thursday"})
    fn = mock_render()
    # today is inside [2026-06-07, 2026-06-11): 4 days ahead
    out = promo.render_promos([e], "2026-06-08", reserve=r, render_fn=fn)
    check(len(fn.calls) == 1, "one in-window promo rendered")
    check(fn.calls[0][0] == "Game 7: Otters at Bears. Live Thursday.",
          f"template filled from meta (got {fn.calls[0][0]!r})")
    f = r / "promo_playoff_night_2026-06-11_0.wav"
    check(f.exists(), "promo_{id}_{date}_{i}.wav written")
    sc = promo._load(r / "promos.json")
    check(len(sc["promos"]) == 1, "sidecar has one record")
    rec = sc["promos"][0]
    check(rec["expires"] == "2026-06-11", "expires sidecar == event date")
    check(rec["event_id"] == "playoff_night" and rec["i"] == 0, "sidecar keys correct")
    check(rec["file"] == "promo_playoff_night_2026-06-11_0.wav", "sidecar file name")

# ── out of window: too early and on/after event date render nothing ──────────
with tempfile.TemporaryDirectory() as d:
    r = Path(d)
    e = ev("x", "2026-06-11", 4, ["line"])
    fn = mock_render()
    promo.render_promos([e], "2026-06-06", reserve=r, render_fn=fn)   # 5 days ahead
    check(len(fn.calls) == 0, "too-early event not promoted")
    fn2 = mock_render()
    promo.render_promos([e], "2026-06-11", reserve=r, render_fn=fn2)  # ON event day
    check(len(fn2.calls) == 0, "event-day (window closed at date) not promoted")

# ── lead_days:0 (reactive, e.g. blizzard) never promotes ─────────────────────
with tempfile.TemporaryDirectory() as d:
    r = Path(d)
    blizzard = ev("blizzard", "2026-06-08", 0, ["should never render"])
    fn = mock_render()
    promo.render_promos([blizzard], "2026-06-08", reserve=r, render_fn=fn)
    check(len(fn.calls) == 0, "lead_days:0 reactive event never promotes")

# ── idempotence: 2nd pass on unchanged state renders nothing new ─────────────
with tempfile.TemporaryDirectory() as d:
    r = Path(d)
    e = ev("playoff_night", "2026-06-11", 4, ["A {game}", "B {game}"],
           meta={"game": 7})
    fn = mock_render()
    promo.render_promos([e], "2026-06-08", reserve=r, render_fn=fn)
    check(len(fn.calls) == 2, "first pass renders both copy lines")
    fn2 = mock_render()
    out2 = promo.render_promos([e], "2026-06-08", reserve=r, render_fn=fn2)
    check(len(fn2.calls) == 0, "second pass re-synths nothing (idempotent)")
    check(len(out2["rendered"]) == 0, "second pass reports zero new")
    check(len(out2["state"]["promos"]) == 2, "sidecar still holds two records")
    # judge fix 5: a present file alone (sidecar wiped) still blocks re-synth
    (r / "promos.json").unlink()
    fn3 = mock_render()
    promo.render_promos([e], "2026-06-08", reserve=r, render_fn=fn3)
    check(len(fn3.calls) == 0, "existing file blocks re-render even w/o sidecar")

# ── idempotence locks meta at first render (later meta change ignored) ───────
with tempfile.TemporaryDirectory() as d:
    r = Path(d)
    e1 = ev("g7", "2026-06-11", 4, ["Arena: {arena}"], meta={"arena": "Ice Barn"})
    fn = mock_render()
    promo.render_promos([e1], "2026-06-08", reserve=r, render_fn=fn)
    e2 = ev("g7", "2026-06-11", 4, ["Arena: {arena}"], meta={"arena": "The Dome"})
    fn2 = mock_render()
    promo.render_promos([e2], "2026-06-08", reserve=r, render_fn=fn2)
    check(len(fn2.calls) == 0, "reseeded meta does not re-render (facts canon forever)")
    rec = promo._load(r / "promos.json")["promos"][0]
    check(rec["line"] == "Arena: Ice Barn", "first-rendered line locked in")

# ── 2-event cap: 3 overlapping November events -> only top-2 by priority ─────
with tempfile.TemporaryDirectory() as d:
    r = Path(d)
    today = "2026-11-01"
    a = ev("election_night", "2026-11-03", 7, ["A"], priority=90)
    b = ev("playoff_night", "2026-11-04", 7, ["B"], priority=50)
    c = ev("trade_deadline", "2026-11-05", 7, ["C"], priority=40)
    fn = mock_render()
    promo.render_promos([c, a, b], today, reserve=r, render_fn=fn)   # unordered input
    ids = sorted({name.split("promo_")[1].rsplit("_", 2)[0]
                  for _, name in fn.calls})
    check(len(fn.calls) == 2, "3 in-window events -> only 2 promoted")
    check(ids == ["election_night", "playoff_night"],
          f"top-2 by priority promoted, lowest waits (got {ids})")
    # the 3rd waits deterministically; nothing already rendered is un-rendered
    check(not (r / "promo_trade_deadline_2026-11-05_0.wav").exists(),
          "3rd (lowest priority) event waits for a slot")

# ── priority tie broken by id (deterministic) ────────────────────────────────
with tempfile.TemporaryDirectory() as d:
    r = Path(d)
    p1 = ev("aaa", "2026-11-03", 7, ["x"], priority=50)
    p2 = ev("bbb", "2026-11-03", 7, ["y"], priority=50)
    p3 = ev("ccc", "2026-11-03", 7, ["z"], priority=50)
    fn = mock_render()
    promo.render_promos([p3, p2, p1], "2026-11-01", reserve=r, render_fn=fn)
    ids = sorted({name.split("promo_")[1].rsplit("_", 2)[0] for _, name in fn.calls})
    check(ids == ["aaa", "bbb"], f"equal priority -> lowest ids win (got {ids})")

# ── expiry purge: past-event promos deleted + dropped from sidecar ───────────
with tempfile.TemporaryDirectory() as d:
    r = Path(d)
    past = ev("g7", "2026-06-11", 4, ["old"])
    live = ev("election_night", "2026-11-03", 7, ["new"], priority=90)
    promo.render_promos([past], "2026-06-08", reserve=r, render_fn=mock_render())
    promo.render_promos([live], "2026-11-01", reserve=r, render_fn=mock_render())
    check(len(promo._load(r / "promos.json")["promos"]) == 2, "two promos on disk")
    # now it's 2026-06-12: the g7 promo's expiry (2026-06-11) has passed
    purged = promo.purge_expired("2026-06-12", reserve=r)
    check(len(purged) == 1 and purged[0]["event_id"] == "g7", "expired promo purged")
    check(not (r / "promo_g7_2026-06-11_0.wav").exists(), "expired wav deleted")
    check((r / "promo_election_night_2026-11-03_0.wav").exists(), "future wav kept")
    left = promo._load(r / "promos.json")["promos"]
    check(len(left) == 1 and left[0]["event_id"] == "election_night",
          "sidecar keeps only the un-expired promo")
    # purge is idempotent — a re-run on the same date removes nothing more
    check(promo.purge_expired("2026-06-12", reserve=r) == [], "purge idempotent")
    # on the event date itself the promo is NOT yet expired (expires == date)
    with tempfile.TemporaryDirectory() as d2:
        r2 = Path(d2)
        promo.render_promos([past], "2026-06-08", reserve=r2, render_fn=mock_render())
        check(promo.purge_expired("2026-06-11", reserve=r2) == [],
              "promo not purged on its own expiry date")

# ── missing sidecar / empty registry are no-ops ──────────────────────────────
with tempfile.TemporaryDirectory() as d:
    r = Path(d)
    out = promo.render_promos([], "2026-06-08", reserve=r, render_fn=mock_render())
    check(out["rendered"] == [] and out["state"]["promos"] == [], "empty registry no-op")
    check(promo.purge_expired("2026-06-08", reserve=r) == [], "purge on empty no-op")

print(f"\nevents_promo {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
