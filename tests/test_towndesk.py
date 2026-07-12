"""Town Desk: derived facts stay stable, the pet ledger spans days and is
idempotent, and no invented name is a real-world entity.

Plain python3, PASS/FAIL counters, exit code. Runs in a tmp cwd so the pet
state file (data/town/pets.json) lands in a throwaway tree.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import towndesk as T  # noqa: E402
from src import nameguard as NG  # noqa: E402

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def census_with(*names):
    """A census.py-shape state carrying residents with the given names."""
    return {"residents": {f"cv-{i}": {"name": nm, "hood": "The Merge"}
                          for i, nm in enumerate(names)}}


prev = os.getcwd()
with tempfile.TemporaryDirectory() as td:
    os.chdir(td)
    try:
        # ---- time_temp ---------------------------------------------------
        s = T.time_temp("ten past four", "now 71F wind 5mph code 3", "seedA")
        check("71 in Halfway" in s, f"temp parsed into the drop (got {s!r})")
        check("ten past four" in s, "spoken time is in the drop")
        check("The Frequency" in s, "station named")

        # first Fahrenheit number wins, not a later one
        s2 = T.time_temp("noon", "now 68F high 78F low 60F", "x")
        check("68 in Halfway" in s2, f"first F reading, not a later one ({s2})")

        # unparseable / missing -> graceful temp-less drop, no stray number
        for bad in (None, "(no forecast data — improvise gently, no numbers)",
                    "cloudy with a chance of geese"):
            d = T.time_temp("half nine", bad, "s")
            check(not any(c.isdigit() for c in d),
                  f"no phantom temp when unparseable ({bad!r} -> {d!r})")

        # seeded + deterministic; 4+ distinct templates reachable
        check(T.time_temp("one", "50F", "k") == T.time_temp("one", "50F", "k"),
              "time_temp is deterministic for a fixed seed")
        forms = {T.time_temp("one", "50F", f"seed{i}") for i in range(40)}
        check(len(forms) >= 4, f"4+ phrasing templates seen (got {len(forms)})")

        # negative and out-of-range temps
        check("-4 in Halfway" in T.time_temp("six", "now -4F windy", "s"),
              "sub-zero temp reads")
        check(not any(ch.isdigit()
                      for ch in T.time_temp("six", "now 999F", "s")),
              "an absurd out-of-range number is rejected")

        # ---- birthdays ---------------------------------------------------
        # a resident's birthday is a stable md5 fold; find the day it lands on
        mm, dd = T._birthday_md("Maureen Alcott")
        check(T._birthday_md("Maureen Alcott") == (mm, dd),
              "birthday is stable for a name")
        the_day = f"2026-{mm:02d}-{dd:02d}"
        cen = census_with("Maureen Alcott", "Gus Pelletier", "Winnie Fye")
        hits = T.birthdays(cen, the_day, 2)
        check(any(h["name"] == "Maureen Alcott" for h in hits),
              "the resident is listed on her derived birthday")
        check(all("age" not in h for h in hits), "no age is ever attached")
        check(hits[0].get("hood") == "The Merge", "hood carried through")

        # a different day: she is not listed
        other = f"2026-{mm:02d}-{(dd % 28) + 1:02d}"
        if other != the_day:
            check(all(h["name"] != "Maureen Alcott"
                      for h in T.birthdays(cen, other, 5)),
                  "resident absent on a non-birthday")

        # cap at n, and a busy day is stable + seeded
        many = census_with(*[f"Name{i}" for i in range(400)])
        # collect everyone born on one crowded day
        crowd = None
        from collections import Counter
        cnt = Counter(T._birthday_md(f"Name{i}") for i in range(400))
        (cm, cdd), c = cnt.most_common(1)[0]
        if c > 2:
            day = f"2026-{cm:02d}-{cdd:02d}"
            b1 = T.birthdays(many, day, 2)
            check(len(b1) == 2, f"birthdays capped at n on a busy day ({c})")
            check(b1 == T.birthdays(many, day, 2),
                  "busy-day pick is stable within the day")
        check(T.birthdays(cen, "not-a-date", 2) == [],
              "a malformed date yields no birthdays, no crash")
        check(T.birthdays({}, the_day, 2) == [], "empty census is fine")

        # ---- calendar ----------------------------------------------------
        cal = T.calendar_lines("2026-07-12", 2)
        check(len(cal) == 2 and cal[0] != cal[1], "two distinct calendar lines")
        check(cal == T.calendar_lines("2026-07-12", 2),
              "calendar is deterministic per date")
        check(len(set(str(T.calendar_lines(f"2026-07-{d:02d}", 1)[0])
                      for d in range(1, 25))) > 1,
              "the calendar varies across days")
        check(all(ln in T._CALENDAR for ln in cal),
              "calendar lines come from the curated bank")

        # ---- lost pets: seeded, idempotent, spanning days ----------------
        d0 = "2026-07-12"
        first = T.lost_pets(d0)
        check(first == T.lost_pets(d0), "lost_pets is idempotent per date")
        check(Path("data/town/pets.json").exists(), "pet state persisted")

        # find a day that actually mints a pet, then confirm it can be found
        seed_day = None
        for day in (f"2026-08-{i:02d}" for i in range(1, 28)):
            if any("Lost" in ln for ln in T.lost_pets(day)):
                seed_day = day
                break
        check(seed_day is not None, "some day reports a lost pet")

        if seed_day:
            # walk forward; a still-missing pet must eventually be "found"
            found_seen = False
            y, m, d = (int(x) for x in seed_day.split("-"))
            from datetime import date as _date
            base = _date(y, m, d)
            for k in range(1, 12):
                nxt = (base + __import__("datetime").timedelta(days=k)
                       ).isoformat()
                lines = T.lost_pets(nxt)
                if any("has been found" in ln for ln in lines):
                    found_seen = True
                    break
            check(found_seen, "a lost pet resolves to found on a later day")

        # idempotency holds even after later days advanced the ledger
        check(first == T.lost_pets(d0),
              "an earlier day's lines never change after later days run")

        # a found-roll never fires twice: re-running a day is a pure replay
        rerun_day = seed_day or d0
        before = T.lost_pets(rerun_day)
        after = T.lost_pets(rerun_day)
        check(before == after, "replaying a day is stable (no double roll)")

        # count is always in range
        check(all(0 <= sum("Lost" in ln for ln in T.lost_pets(f"2026-09-{i:02d}"))
                  <= 2 for i in range(1, 28)),
              "0-2 fresh lost pets per day")

        # ---- town_block --------------------------------------------------
        blk = T.town_block(the_day, cen, "now 71F wind 5mph")
        check("TOWN DESK SHEET" in blk and "authoritative" in blk,
              "town_block is an authoritative sheet")
        check("71F in Halfway" in blk, "temp appears, marked authoritative")
        check("Maureen Alcott" in blk, "today's birthday is in the block")
        check("NO ages" in blk or "no ages" in blk.lower(),
              "the block forbids inventing ages")
        blk2 = T.town_block(the_day, cen, None)
        check("do NOT state a temperature" in blk2,
              "no-forecast block forbids a temperature")

        # ---- wire_lines --------------------------------------------------
        wl = T.wire_lines(the_day, cen, "50F")
        check(isinstance(wl, list) and all(isinstance(x, str) for x in wl),
              "wire_lines returns a list of strings")
        check(any("Happy birthday" in x and "Maureen Alcott" in x for x in wl),
              "a birthday shout is on the wire")

        # ---- nameguard: no invented name is a real-world entity ----------
        invented = " ".join(list(T._PET_NAMES) + list(T._PET_LANDMARKS)
                            + list(T._PET_QUIRKS) + list(T._CALENDAR)
                            + list(T._PET_SPECIES)).lower()
        toks = set(__import__("re").findall(r"[a-z][a-z&'.-]*[a-z]", invented))
        bad_tok = toks & NG._WORLD_TOKENS
        check(not bad_tok, f"no invented token is a real-world entity ({bad_tok})")
        bad_ph = [p for p in NG._WORLD_PHRASES if p in invented]
        check(not bad_ph, f"no invented phrase is a real-world entity ({bad_ph})")
    finally:
        os.chdir(prev)

print(f"towndesk {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
