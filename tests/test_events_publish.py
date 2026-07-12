"""events.publish fixtures: the /data/takeovers.json feed is shaped exactly like
a date-keyed F.TAKEOVERS row, filters to a 14-day horizon, writes atomically,
and no-ops safely; the edited schedule.js parses and its date-branch gating works.

Run directly (no pytest needed):  python3 tests/test_events_publish.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.events import publish

PASS = FAIL = 0
REPO = Path(__file__).parent.parent


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


# ── fixtures: active_events-shape event dicts ────────────────────────────────
def ev(id_, date, window, name, hook, who, meta=None):
    return {"id": id_, "engine": "x", "date": date, "window": window,
            "priority": 50, "show": {}, "promo": {},
            "site": {"name": name, "hook": hook, "who": who},
            "meta": meta or {}}


TODAY = "2026-11-01"

ELECTION = ev("election_night", "2026-11-03", ["19:00", "01:00"],
              "Election Night", "Live returns from all 171 precincts.",
              "THE RETURNS DESK")
PLAYOFF = ev("playoff_night", "2026-11-05", ["20:00", "23:00"],
             "Center Ice — {round}", "Game {game}. Live from {arena}.",
             "BUCKY · SAL",
             meta={"round": "Round 1", "game": 3, "arena": "the Ice Barn"})
FAR = ev("draft", "2026-11-30", ["12:00", "15:00"], "Draft Day", "Picks.", "DESK")
PAST = ev("old", "2026-10-20", ["20:00", "23:00"], "Old", "gone", "X")

ALL = [ELECTION, PLAYOFF, FAR, PAST]

# ── build_feed: shape + horizon + wrap + template fill ───────────────────────
feed = publish.build_feed(ALL, TODAY, horizon_days=14, now=1730600000)
check(feed["schema"] == 1, "schema is 1")
check(feed["generated"] == 1730600000, "generated stamp honored")
check(isinstance(feed["takeovers"], list), "takeovers is a list")

rows = feed["takeovers"]
dates = [r["date"] for r in rows]
check("2026-11-03" in dates, "in-horizon election kept")
check("2026-11-05" in dates, "in-horizon playoff kept")
check("2026-11-30" not in dates, "beyond 14-day horizon dropped")
check("2026-10-20" not in dates, "past event dropped")

erow = next(r for r in rows if r["date"] == "2026-11-03")
check(set(erow.keys()) == set(publish.ROW_KEYS), "row keys are the TAKEOVERS shape")
check(erow["start"] == 19 and erow["end"] == 25, "wrap window -> start 19 end 25")
check(erow["name"] == "Election Night", "name verbatim")

prow = next(r for r in rows if r["date"] == "2026-11-05")
check(prow["start"] == 20 and prow["end"] == 23, "non-wrap window hours")
check(prow["name"] == "Center Ice — Round 1", "name template filled from meta")
check(prow["hook"] == "Game 3. Live from the Ice Barn.", "hook template filled from meta")

# missing template key -> string left verbatim, never a crash
bad = ev("b", "2026-11-04", ["9:00", "10:00"], "{nope} show", "h", "w")
brow = publish.build_feed([bad], TODAY)["takeovers"][0]
check(brow["name"] == "{nope} show", "unknown template key left verbatim")

# sorted by (date, start, name) and deduped
dup = publish.build_feed([PLAYOFF, dict(PLAYOFF)], TODAY)["takeovers"]
check(len(dup) == 1, "duplicate (date,start,name) deduped")
check(dates == sorted(dates), "rows sorted by date")

# empty input -> empty feed (Stage 0 no-op)
empty = publish.build_feed([], TODAY)
check(empty["takeovers"] == [], "no events -> empty feed")

# ── publish_takeovers: atomic write, round-trips, horizon respected ──────────
tmpd = tempfile.mkdtemp()
try:
    out = os.path.join(tmpd, "takeovers.json")
    ok = publish.publish_takeovers(path=out, events=ALL, today=TODAY, now=42)
    check(ok is True, "publish returns True on write")
    check(os.path.exists(out), "feed file written")
    got = json.loads(Path(out).read_text())
    check(got["schema"] == 1 and got["generated"] == 42, "written feed parses w/ stamp")
    check({r["date"] for r in got["takeovers"]} == {"2026-11-03", "2026-11-05"},
          "written feed honors horizon")
    check(not any(n.startswith("takeovers.json.tmp") for n in os.listdir(tmpd)),
          "no tmp file left behind after atomic replace")

    # empty events -> valid empty feed still written (Stage 0)
    ok2 = publish.publish_takeovers(path=out, events=[], today=TODAY)
    check(ok2 is True and json.loads(Path(out).read_text())["takeovers"] == [],
          "empty events -> empty feed written")
finally:
    shutil.rmtree(tmpd, ignore_errors=True)

# missing web dir -> silent no-op, returns False, writes nothing
missing = os.path.join(tempfile.gettempdir(), "no_such_dir_%d" % os.getpid(), "t.json")
check(publish.publish_takeovers(path=missing, events=ALL, today=TODAY) is False,
      "missing web dir -> returns False")
check(not os.path.exists(missing), "missing web dir -> nothing written")

# resolver default (no registry siblings) -> no-op empty, never raises
try:
    r = publish.build_feed(publish._resolve_horizon(TODAY, 14), TODAY)
    check(r["takeovers"] == [], "Stage-0 resolver -> empty (no siblings)")
except Exception as e:
    check(False, f"resolver raised: {e}")

# station_today returns an ISO date string
st = publish.station_today(now=1730600000)
check(len(st) == 10 and st[4] == "-" and st[7] == "-", "station_today is ISO YYYY-MM-DD")

# ── schedule.js: node --check + date-branch gating (or python sanity) ─────────
JS = REPO / "web" / "schedule.js"
node = shutil.which("node")
if node:
    r = subprocess.run([node, "--check", str(JS)], capture_output=True, text=True)
    check(r.returncode == 0, f"schedule.js node --check: {r.stderr.strip()}")

    driver = (
        "const F = require(%r).__NOPE__ || (globalThis.FREQ);\n"
        "let ok = true;\n"
        "// weekday-keyed row still gates on days\n"
        "F.TAKEOVERS = [{start:20,end:23,days:['Wednesday','Saturday'],name:'CI'}];\n"
        "if (!F.onDay(F.TAKEOVERS[0], 'Wednesday')) ok=false;\n"
        "if (F.onDay(F.TAKEOVERS[0], 'Monday')) ok=false;\n"
        "// date-keyed row gates on today; also must not throw (no .days)\n"
        "const today = F.todayISO();\n"
        "if (!/^\\d{4}-\\d{2}-\\d{2}$/.test(today)) ok=false;\n"
        "const dk = {start:19,end:25,date:today,name:'Election'};\n"
        "if (!F.onDay(dk, 'Whatever')) ok=false;\n"
        "const past = {start:19,end:25,date:'2000-01-01',name:'Old'};\n"
        "if (F.onDay(past, 'Whatever')) ok=false;\n"
        "// effective() tolerates a date-keyed takeover today without throwing\n"
        "F.TAKEOVERS = [dk];\n"
        "const eff = F.effective(F.stationDay());\n"
        "if (!eff.some(s => s._takeover && s.date === today)) ok=false;\n"
        "// activeTakeover finds the date-keyed row in-window\n"
        "if (!F.activeTakeover('Whatever', 20)) ok=false;\n"
        "process.stdout.write(ok ? 'OK' : 'BAD');\n"
    ) % str(JS)
    d = subprocess.run([node, "-e", driver], capture_output=True, text=True)
    check(d.stdout.strip() == "OK",
          f"schedule.js date-branch gating (out={d.stdout!r} err={d.stderr.strip()})")
else:
    src = JS.read_text()
    check("F.todayISO" in src, "todayISO present")
    check("function onDay" in src, "onDay helper present")
    check("F.loadTakeovers" in src, "loadTakeovers present")
    check(src.count("t.days.indexOf") == 0, "no unguarded t.days.indexOf remains")

print(f"\nevents.publish {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
