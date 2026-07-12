"""Traffic on the 8s: incidents are seeded and stable, every report in a rush
agrees, incidents RESOLVE as they clear, sheets carry small delays, code-built
wire copy is guard-true and signed, and verify() holds an authored read to the
sheet. Fictional geography only — no name collides with nameguard's real-world
banks.

Plain python3, PASS/FAIL counters, exit code. No state, no cwd needed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import traffic as T          # noqa: E402
from src import nameguard as N        # noqa: E402

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


D = "2026-07-12"

# --- incidents: seeded, stable, well-formed --------------------------------
for slot in ("am", "pm"):
    a = T.incidents(D, slot)
    b = T.incidents(D, slot)
    check(a == b, f"incidents deterministic ({slot})")
    check(2 <= len(a) <= 4, f"2-4 incidents ({slot}: {len(a)})")
    ws, we = T._WINDOWS[slot]
    for inc in a:
        check(ws <= inc["onset"] < inc["clear"] <= we,
              f"onset<clear inside window ({slot}: {inc})")
        check(3 <= inc["delay"] <= 25, f"delay is a small int ({inc['delay']})")
        check(inc["location"] in T.LOCATIONS and inc["cause"] in T.CAUSES,
              "location/cause drawn from the fictional banks")
    locs = [i["location"] for i in a]
    check(len(locs) == len(set(locs)), f"locations unique within a rush ({slot})")

check(T.incidents(D, "am") != T.incidents(D, "pm"), "am and pm differ")
check(T.incidents(D, "am") != T.incidents("2026-07-13", "am"),
      "different day, different rush")
try:
    T.incidents(D, "midday")
    check(False, "bad slot rejected")
except ValueError:
    check(True, "bad slot rejected")

# --- traffic_sheet: reports in a rush agree; incidents resolve -------------
src_am = T.incidents(D, "am")
for hour in (6, 7, 8, 9):
    sheet = T.traffic_sheet(D, hour)
    check(sheet["slot"] == "am", f"hour {hour} is the am rush")
    for inc in sheet["incidents"]:
        check(inc in src_am, f"sheet incident comes from the rush list (h{hour})")
        check(inc["onset"] < (hour + 1) * 60 and inc["clear"] > hour * 60,
              f"sheet incident overlaps the hour (h{hour})")

# resolution: search days for an incident present at its onset hour but gone
# later once it has cleared — traffic that resolves across the rush.
resolved = False
for i in range(40):
    day = f"2026-08-{i + 1:02d}"
    for inc in T.incidents(day, "am"):
        oh, ch = inc["onset"] // 60, inc["clear"] // 60
        if ch > oh and ch <= 9:                    # clears in a later am hour
            present = inc in T.traffic_sheet(day, oh)["incidents"]
            gone = inc not in T.traffic_sheet(day, ch + 1)["incidents"] \
                if ch + 1 <= 9 else True
            if present and gone and ch + 1 <= 9:
                resolved = True
                break
    if resolved:
        break
check(resolved, "an incident clears and stops appearing later in the rush")

# off-rush hours are clear
for hour in (0, 3, 11, 13, 22):
    s = T.traffic_sheet(D, hour)
    check(s["slot"] is None and s["incidents"] == [] and s["clear_road"],
          f"off-rush hour {hour} is clear")

# --- wire_line: guard-true, signed, seeded ---------------------------------
seen_incident_line = False
for day_i in range(30):
    day = f"2026-09-{day_i + 1:02d}"
    for hour in (6, 7, 8, 9, 16, 17, 18, 19):
        sheet = T.traffic_sheet(day, hour)
        line = T.wire_line(sheet, "drive")
        check(T.REPORTER in line, "wire_line is reporter-signed")
        check(T.verify([line], sheet),
              f"wire_line is guard-true ({day} h{hour}): {line!r}")
        check(line == T.wire_line(sheet, "drive"), "wire_line is deterministic")
        if sheet["incidents"]:
            seen_incident_line = True
check(seen_incident_line, "exercised at least one non-empty wire_line")

# a clear-road sheet still names the reporter and verifies
clear_sheet = T.traffic_sheet(D, 3)
cl = T.wire_line(clear_sheet, "drive")
check(T.REPORTER in cl and T.verify([cl], clear_sheet),
      "clear-road bulletin is signed and guard-true")

# --- block: authoritative, itself verifiable -------------------------------
busy = None
for hour in (6, 7, 8, 9):
    s = T.traffic_sheet(D, hour)
    if s["incidents"]:
        busy = s
        break
check(busy is not None, "found a busy hour to exercise block()")
blk = T.block(busy)
for inc in busy["incidents"]:
    check(inc["location"] in blk and str(inc["delay"]) in blk,
          "block names every location and its delay")
check(T.REPORTER in blk, "block credits the reporter")
check(T.verify([blk], busy), "the authoritative block passes verify")

# --- verify: catches numbers not on the sheet ------------------------------
d0 = busy["incidents"][0]["delay"]
bad_delay = next(x for x in range(3, 60) if x != d0
                 and x not in {i["delay"] for i in busy["incidents"]}
                 and x != len(busy["incidents"]))
check(not T.verify([f"Expect {bad_delay} minutes at {busy['incidents'][0]['location']}."],
                   busy), "verify rejects a delay not on the sheet")
check(not T.verify(["Backups are 900 minutes long."], busy),
      "verify rejects a wild number")
check(T.verify([f"About {d0} minutes."], busy), "verify accepts a real delay")
# a location's own route number never trips verify
check(T.verify(["Route 9 is snarled — no delay to speak of."],
               {"date": D, "hour": 7, "incidents":
                [{"location": "Route 9", "cause": "a goose crossing",
                  "delay": 5, "onset": 400, "clear": 440}], "clear_road": False}),
      "a road's route number is not read as a delay")

# --- nameguard: nothing invented collides with the real-world banks --------
def tokens(s):
    import re
    return re.findall(r"[a-z][a-z'-]*", s.lower())


invented = [T.REPORTER] + list(T.LOCATIONS) + list(T.CAUSES)
bad = set()
for name in invented:
    low = name.lower()
    for ph in N._WORLD_PHRASES:
        if ph in low:
            bad.add(ph)
    for tok in tokens(name):
        if tok in N._WORLD_TOKENS:
            bad.add(tok)
check(not bad, f"no invented name hits nameguard's real-world banks ({bad})")

print(f"traffic {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
