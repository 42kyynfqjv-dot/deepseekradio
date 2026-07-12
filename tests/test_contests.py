"""Contests: the desk owns the giveaway (show, prize, winning caller), the
directive hands the writer exactly one number, and winners age out of the
follow-up feed on a seeded 2-5 day clock.

Plain python3, PASS/FAIL counters, exit code, tmp cwd (state is redirected
into a TemporaryDirectory so no real data/town/ file is touched).
"""
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import contests as C          # noqa: E402
from src import nameguard as NG        # noqa: E402

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


SPONSORS = [
    ("June's Mattress Barn", "the mattress store that's always closing"),
    ("Wesley's Weather Hut", "the forecast you can lean on"),
    ("Mile Zero Tackle", "bait, allegedly"),
]

# ------------------------------------------------------------ todays()

slate = C.todays("2026-07-12", SPONSORS)
check(1 <= len(slate) <= 2, f"1-2 contests per day (got {len(slate)})")
check(slate == C.todays("2026-07-12", SPONSORS),
      "todays is deterministic for a fixed (date, sponsors)")
shows = [c["show"] for c in slate]
check(len(shows) == len(set(shows)), "no two contests share a show on a day")
for c in slate:
    check(c["show"] in C.SHOWS, f"show is a known daypart id ({c['show']})")
    check(isinstance(c["prize"], str) and c["prize"], "prize is a nonempty str")
    check(c["n"] in C._CALLER_NS, f"winning caller is a bank number ({c['n']})")

# different days give different slates (sampled over a window)
slates = [C.todays(f"2026-07-{d:02d}", SPONSORS) for d in range(1, 29)]
variety = {tuple((x["show"], x["prize"], x["n"]) for x in s) for s in slates}
check(len(variety) > 10, f"slates vary day to day (got {len(variety)} distinct)")

# sponsor-tied prizes actually name a sponsor sometimes; station prizes appear
seen_sponsor = any(
    any(sp[0] in c["prize"] for sp in SPONSORS) for s in slates for c in s)
seen_station = any(
    c["prize"] in C._STATION_PRIZES for s in slates for c in s)
check(seen_sponsor, "sponsor-tied prizes are drawn from the roster")
check(seen_station, "station prizes are drawn from the bank")

# no-sponsor day still works (all-station prizes)
nosp = C.todays("2026-07-12", [])
check(all(c["prize"] in C._STATION_PRIZES for c in nosp),
      "with no sponsors every prize is a station prize")

# ------------------------------------------------------------ nameguard safety

_bad = []
for p in C._STATION_PRIZES:
    low = p.lower()
    for tok in re.findall(r"[a-z][a-z&'.-]*[a-z']", low):
        if tok in NG._WORLD_TOKENS:
            _bad.append((p, tok))
    for ph in NG._WORLD_PHRASES:
        if re.search(r"\b" + re.escape(ph) + r"\b", low):
            _bad.append((p, ph))
check(not _bad, f"no station prize collides with a real brand/person ({_bad})")

# ------------------------------------------------------------ directive()

d = C.directive({"show": "morning_scramble", "prize": "a Frequency mug that "
                 "hums", "n": 7}, "Deb from Halfway")
check("7th caller" in d, "directive names the winning caller ordinally")
check("Deb from Halfway" in d, "directive names the desk-assigned winner")
check("a Frequency mug that hums" in d, "directive states the prize")
check("once" in d.lower() and "one winner" in d.lower(),
      "directive forbids a re-run")
# the ONLY number in the block is n
nums = {int(x) for x in re.findall(r"\d+", d)}
check(nums == {7}, f"the winning caller is the only number handed over ({nums})")
check("11th" == C._ordinal(11) and "3rd" == C._ordinal(3)
      and "1st" == C._ordinal(1), "ordinal suffixes")

# ------------------------------------------------------------ winner state

prev = Path.cwd()
with tempfile.TemporaryDirectory() as td:
    C.PATH = Path(td) / "data/town/contests.json"

    C.record_winner("2026-07-12", "morning_scramble",
                    "a June's Mattress Barn gift basket", "June")
    check(C.PATH.exists(), "state file written atomically")

    # same-day: not yet 'unclaimed' (needs a later day to nag)
    check(C.uncollected("2026-07-12") == [], "win day itself yields no nag")

    # a later day within the window nags, naming winner + prize
    day1 = C.uncollected("2026-07-13")
    check(len(day1) == 1 and "June" in day1[0], "unclaimed prize nags next day")
    check(C.uncollected("2026-07-13") == day1, "follow-up is deterministic")

    # seeded 2-5 day window: by day +6 every prize has aged to collected
    check(C.uncollected("2026-07-18") == [],
          "prize ages to collected after its 2-5 day window")

    # idempotent record: re-logging the same win doesn't double the nag
    C.record_winner("2026-07-12", "morning_scramble",
                    "a June's Mattress Barn gift basket", "June")
    check(len(C._load()["winners"]) == 1, "re-recording a win is a no-op")

    # two winners on the same day, different shows -> up to two nags later
    C.record_winner("2026-07-12", "the_handover",
                    "a pair of Center Ice tickets", "Marv")
    got = " ".join(C.uncollected("2026-07-13"))
    # both are within their (seeded) windows on +1 day (min window is 2)
    check("June" in got and "Marv" in got, "each winner nags independently")

    # window length is seeded and stable across reloads
    w = C._load()["winners"][0]
    check(2 <= w["days"] <= 5, f"collect window is 2-5 days ({w['days']})")

    # old records are pruned so the file stays bounded
    C.record_winner("2026-08-30", "dawn_patrol", "a Frequency mug that hums",
                    "Ada")
    dates = {x["date"] for x in C._load()["winners"]}
    check("2026-07-12" not in dates and "2026-08-30" in dates,
          "records well past their window are pruned")

Path.cwd()  # (no chdir needed; PATH was absolute)

print(f"contests {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
