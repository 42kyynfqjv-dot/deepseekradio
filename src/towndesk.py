"""The Town Desk — Halfway's small-town service desk.

Code owns the facts, the LLM authors the read. This leaf module bundles the
human-scale texture the morning and midday shows run on: the time-and-temp
drop, whose birthday it is, what's on the town calendar, and who's lost a pet
(with the follow-up when the pet turns up). Everything is a pure function of
the day plus the state the caller already holds — no network, no wall clock,
no bare random.

Two facts persist because they must span days: lost pets carry across to their
"has been found" follow-up (state at data/town/pets.json, atomic tmp+replace).
Everything else is DERIVED fresh every time it's asked for — a resident's
birthday is md5(name) folded into a month/day, so it never drifts and never
needs storing; the calendar is a seeded pick from a fixed bank.

The one number this desk ever hands the LLM is the temperature, parsed from a
forecast string the CALLER already fetched (spots._real_forecast()-style text,
passed in — this module never touches the network). Birthdays deliberately
carry NO age, so there is no other number for the read to get wrong. The
prompt block labels the temp as authoritative, the briefs.desk_sheet way.

Every invented name here (pet names, landmarks, calendar happenings) is checked
against nameguard._WORLD_TOKENS/_WORLD_PHRASES in the tests, so the desk can
never accidentally read a real brand or person on the air.

Stdlib-only leaf module: the writer/orchestrator import this, never the reverse.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
from datetime import date as _date, timedelta
from pathlib import Path

TOWN = "Halfway"
_PETS_PATH = Path("data/town/pets.json")

# how likely a still-missing pet turns up on any given later day (seeded)
_FOUND_CHANCE = 0.5
# found pets are kept this long (for continuity) then pruned to bound the file
_PET_RETAIN_DAYS = 10


# ============================================================ time & temperature

# 4+ phrasings so the drop never reads the same twice in a session. Each is a
# format template over {time}, {temp} (already "NN in Halfway") and bare {town}.
_TT_WITH_TEMP = (
    "It's about {time} on The Frequency — {temp}.",
    "{time} here on The Frequency, and it's {temp} out.",
    "Coming up on {time} in {town} — {temp} under the tower.",
    "The clock says about {time}, the thermometer says {temp}. This is The Frequency.",
    "{time} on the nose-ish, {temp}, and you're on The Frequency.",
)
_TT_NO_TEMP = (
    "It's about {time} on The Frequency.",
    "{time} here on The Frequency in {town}.",
    "Coming up on {time} under the tower in {town}.",
    "The clock says about {time}. This is The Frequency.",
    "{time} on the nose-ish, and you're on The Frequency.",
)


def _parse_temp(forecast_text: str | None):
    """First Fahrenheit reading in a spots._real_forecast()-style string
    ("now 71F wind 5mph ...") as an int, or None when there's nothing
    speakable (missing text, the "(no forecast data ...)" sentinel, or a
    string carrying no NNF token). Never raises."""
    if not forecast_text:
        return None
    m = re.search(r"(-?\d{1,3})\s*F\b", forecast_text)
    if not m:
        # tolerate a plain-degree phrasing too ("71 degrees", "71°")
        m = re.search(r"(-?\d{1,3})\s*(?:°|degrees?\b)", forecast_text)
    if not m:
        return None
    try:
        v = int(m.group(1))
    except ValueError:
        return None
    if not -80 <= v <= 140:      # a garbled number is no number
        return None
    return v


def time_temp(spoken_time: str, forecast_text: str | None, seed: str) -> str:
    """The time-and-temp drop: "It's about ten past four on The Frequency —
    71 in Halfway." `spoken_time` is the already-worded clock phrase the
    caller hands us (this module owns no clock). The temperature is parsed
    from `forecast_text` (pass-through, NO network) and omitted gracefully —
    a clean, temp-less drop — whenever it can't be read. Seeded phrasing
    across 4+ templates."""
    temp = _parse_temp(forecast_text)
    rng = random.Random(f"timetemp:{seed}")
    if temp is None:
        tmpl = rng.choice(_TT_NO_TEMP)
        return tmpl.format(time=spoken_time, town=TOWN)
    tmpl = rng.choice(_TT_WITH_TEMP)
    return tmpl.format(time=spoken_time, town=TOWN, temp=f"{temp} in {TOWN}")


# ==================================================================== birthdays

# days per month on a fixed non-leap calendar — a resident's birthday is drawn
# uniformly over these 365 days, so Feb 29 is simply never a birthday (nobody
# gets a once-in-four-years shout on this desk).
_MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_YEAR_DAYS = sum(_MONTH_DAYS)     # 365


def _birthday_md(name: str) -> tuple[int, int]:
    """A resident's STABLE birthday as (month, day), a pure function of the
    name via md5 — uniform over the 365-day fixed calendar, carrying NO age.
    Identical name -> identical birthday, forever, with zero stored state."""
    h = int(hashlib.md5(("bday:" + name).encode()).hexdigest(), 16)
    doy = h % _YEAR_DAYS          # 0 .. 364
    month = 0
    while doy >= _MONTH_DAYS[month]:
        doy -= _MONTH_DAYS[month]
        month += 1
    return month + 1, doy + 1


def birthdays(census: dict, date: str, n: int = 2) -> list[dict]:
    """Residents whose derived birthday falls on `date` (ISO YYYY-MM-DD),
    up to `n`. `census` is the census.py state shape ({"residents": {id:
    rec}}); each returned dict is {"name", "hood", "id"} — no age, ever.
    When more than `n` residents share the day the pick is seeded on the
    date, so a busy day still reads two different names each time but stays
    stable within the day."""
    try:
        _, mm, dd = (int(x) for x in date.split("-"))
    except (ValueError, AttributeError):
        return []
    residents = (census or {}).get("residents", {}) or {}
    hits = []
    for cid, rec in residents.items():
        name = (rec or {}).get("name")
        if not name:
            continue
        if _birthday_md(name) == (mm, dd):
            hits.append({"name": name, "hood": rec.get("hood"), "id": cid})
    hits.sort(key=lambda r: r["id"])          # deterministic base order
    if len(hits) <= n:
        return hits
    rng = random.Random(f"bday-pick:{date}")
    return [hits[i] for i in sorted(rng.sample(range(len(hits)), n))]


# ===================================================================== calendar

# ~24 recurring Halfway happenings — evergreen, PG, deadpan, and phrased for
# air. All invented; none collide with nameguard's real-world token/phrase
# sets (the tests assert it). No clock times: the desk owns the time drop.
_CALENDAR = (
    "The library book sale runs all day in the annex — hardcovers a quarter, "
    "the good chair by the window is first-come.",
    "It's the Bridge Appreciation Walk this morning; you meet at the near end "
    "and appreciate your way across.",
    "The Grange pancake supper is on tonight — bring a folding chair, the "
    "Grange ran short again.",
    "The Historical Society opens the one good room today; the other rooms "
    "remain, they say, aspirational.",
    "Halfway Community Band rehearses in the pharmacy lot — park wide.",
    "It's swap-table day outside the hardware store: leave a thing, take a "
    "thing, no thing left behind.",
    "The seed library is open for lending — return your beans, people.",
    "The roundabout committee meets again to discuss the roundabout.",
    "Cold Storage holds its monthly potluck; the theme, as ever, is casserole.",
    "The Zipper Row garden club is giving away rhubarb — take the rhubarb, "
    "they are not asking.",
    "It's the Tarpline mending circle in the church basement; bring a jacket "
    "with a hole in it and an opinion.",
    "The Mile-Zero walking group loops the commons twice and calls it a mile.",
    "The volunteer fire hall pancake breakfast is on — the truck is parked out "
    "front for the children, and for the adults.",
    "Story hour at the library is back; today's book is long.",
    "The quilting bee meets at the Grange; a raffle quilt is nearly finished, "
    "third year running.",
    "It's the annual bring-your-own-mug coffee morning at the Historical "
    "Society; the good mugs are already claimed.",
    "The town chess ladder plays outdoors by the bandstand — bring your own "
    "clock, the town clock is unreliable.",
    "The Provisional Blocks neighborhood watch meets to watch the neighborhood.",
    "The lost-and-found table at Town Hall is overflowing; there is a single "
    "unclaimed left mitten going back to winter.",
    "The birding club walks Lower Sieve at dawn; the geese are aware.",
    "It's the school bake sale — the good brownies go in the first ten minutes, "
    "you have been warned.",
    "The knit-a-square drive continues at the pharmacy counter; a very long "
    "scarf is being assembled by committee.",
    "Free compost is available behind the public works shed, one bucket per "
    "household, honor system, mostly.",
    "The Old Millwater ice cream social is on the green tonight; the churn is "
    "hand-cranked and volunteers are, quote, encouraged.",
)


def calendar_lines(date: str, n: int = 2) -> list[str]:
    """`n` seeded, distinct picks from the recurring-happenings bank, phrased
    for air. Seeded on the date so a given day's calendar is stable but the
    week doesn't repeat itself."""
    n = max(0, min(n, len(_CALENDAR)))
    rng = random.Random(f"calendar:{date}")
    return rng.sample(list(_CALENDAR), n)


# ==================================================================== lost pets

_PET_SPECIES = ("dog", "cat", "goose", "parrot", "tortoise", "ferret",
                "rabbit", "goat", "pot-bellied pig", "cockatiel")
# invented pet names — homely, none colliding with nameguard tokens/phrases
_PET_NAMES = (
    "Chester", "Biscuit", "Marbles", "Waffles", "Pickles", "Noodle", "Dumpling",
    "Sergeant Whiskers", "Mister Tibbs", "Beans", "Gravy", "Pretzel", "Tugboat",
    "Clementine", "Barnaby", "Winifred", "Gus", "Petunia", "Otis", "Maple",
    "Dot", "Rufus", "Nutmeg", "Cornelius", "Bramble", "Tilly", "Moose the cat",
)
_PET_LANDMARKS = (
    "the roundabout at Fifth and Pine", "the bridge", "the pharmacy lot",
    "Mile Zero", "the impound lot exit", "the old millrace", "Lower Sieve",
    "the Grange", "the swap table", "the public works shed", "the bandstand",
    "the Exit-4 Flats",
)
_PET_QUIRKS = (
    "answers to a squeaky toy", "will not answer to anything",
    "is wearing a tiny sweater", "responds only to whistling in D",
    "is extremely food-motivated", "is missing the tip of one ear",
    "thinks it is a much larger animal", "has a very serious face",
    "comes when you pretend to leave", "is faster than it looks",
    "hums, and yes we checked", "is on a diet and knows it",
)


def _load_pets() -> dict:
    """Live file, then .bak, then a fresh default — never reset a live spine
    on a read race (the census/season discipline)."""
    default = {"schema": 1, "pets": {}, "days": {}}
    for p in (_PETS_PATH, _PETS_PATH.with_suffix(".bak")):
        try:
            if p.exists():
                st = json.loads(p.read_text())
                for k, v in default.items():
                    st.setdefault(k, v if not isinstance(v, (dict, list))
                                  else type(v)())
                return st
        except Exception:
            continue          # a corrupt file must never kill the desk
    return {"schema": 1, "pets": {}, "days": {}}


def _save_pets(st: dict) -> None:
    """Atomic tmp.<pid> + replace, keeping a .bak of the prior good file."""
    _PETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _PETS_PATH.exists():
        try:
            _PETS_PATH.with_suffix(".bak").write_text(_PETS_PATH.read_text())
        except Exception:
            pass
    tmp = _PETS_PATH.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(_PETS_PATH)


def _pet_article(species: str) -> str:
    return "an" if species[0] in "aeiou" else "a"


def _lost_line(pet: dict) -> str:
    sp, art = pet["species"], _pet_article(pet["species"])
    return (f"Lost {sp}: {pet['name']}, last seen near {pet['landmark']} — "
            f"{art} {sp} that {pet['quirk']}. Call the Town Desk if you see "
            f"{pet['name']}.")


def _found_line(pet: dict) -> str:
    return (f"Good news from the Town Desk: {pet['name']} the {pet['species']} "
            f"has been found, safe near {pet['landmark']}.")


def _mint_pet(date: str, i: int, rng: random.Random) -> dict:
    return {"name": rng.choice(_PET_NAMES),
            "species": rng.choice(_PET_SPECIES),
            "landmark": rng.choice(_PET_LANDMARKS),
            "quirk": rng.choice(_PET_QUIRKS),
            "reported": date, "found": None}


def _prune_pets(st: dict, date: str) -> None:
    """Bound the file: drop pets found more than _PET_RETAIN_DAYS ago."""
    try:
        today = _date.fromisoformat(date)
    except ValueError:
        return
    cutoff = (today - timedelta(days=_PET_RETAIN_DAYS)).isoformat()
    for pid in [pid for pid, p in st["pets"].items()
                if p.get("found") and p["found"] < cutoff]:
        del st["pets"][pid]
    for d in [d for d in st["days"] if d < cutoff]:
        del st["days"][d]


def lost_pets(date: str) -> list[str]:
    """The lost-pets beat for `date`: 0-2 freshly-reported pets (seeded) plus
    the "has been found" follow-ups for pets reported on earlier days that
    turn up today (each still-missing pet gets one seeded found-roll per day).
    State lives at data/town/pets.json; the beat is IDEMPOTENT per date — the
    day's exact lines are recorded and replayed, and no found-roll ever fires
    twice for the same pet-day."""
    st = _load_pets()
    if date in st["days"]:
        return list(st["days"][date]["lines"])

    # 1. follow-ups: earlier-reported, still-missing pets turn up today
    found_lines = []
    for pid, pet in st["pets"].items():
        if pet.get("found") or pet.get("reported", date) >= date:
            continue
        if random.Random(f"found:{pid}:{date}").random() < _FOUND_CHANCE:
            pet["found"] = date
            found_lines.append(_found_line(pet))

    # 2. today's fresh losses (0-2, seeded)
    rng = random.Random(f"lostpets:{date}")
    k = rng.choices((0, 1, 2), weights=(35, 45, 20))[0]
    new_lines = []
    for i in range(k):
        pet = _mint_pet(date, i, rng)
        st["pets"][f"{date}:{i}"] = pet
        new_lines.append(_lost_line(pet))

    lines = found_lines + new_lines
    st["days"][date] = {"lines": lines}
    _prune_pets(st, date)
    _save_pets(st)
    return lines


# ============================================================= bundled desk copy

def _birthday_phrases(bdays: list[dict]) -> list[str]:
    out = []
    for b in bdays:
        hood = b.get("hood")
        where = f" over in {hood}" if hood else ""
        out.append(f"{b['name']}{where}")
    return out


def town_block(date: str, census: dict, forecast_text: str | None) -> str:
    """The authoritative TOWN DESK prompt block for the morning/midday shows.
    Bundles the day's birthdays, calendar happenings, and lost-pet beat, plus
    the parsed temperature marked authoritative (the desk_sheet discipline:
    the ONE number here, and the writer may not invent another). The LLM
    authors warm read copy FROM this; it never adds facts of its own."""
    temp = _parse_temp(forecast_text)
    bdays = birthdays(census, date, 2)
    cal = calendar_lines(date, 2)
    pets = lost_pets(date)

    ln = ["TOWN DESK SHEET (authoritative — read only what's here, invent no "
          "names, ages, or numbers):"]
    ln.append(f"- town: {TOWN}; date: {date}")
    if temp is not None:
        ln.append(f"- temperature (authoritative, the only number): {temp}F "
                  f"in {TOWN}")
    else:
        ln.append("- temperature: unavailable — do NOT state a temperature")

    if bdays:
        ln.append("- birthdays today (wish them well by NAME; NO ages, we "
                  "don't ask): " + "; ".join(_birthday_phrases(bdays)))
    else:
        ln.append("- birthdays today: none on the books — skip the segment")

    if cal:
        ln.append("- on the town calendar today:")
        ln.extend(f"    * {c}" for c in cal)

    if pets:
        ln.append("- lost & found desk (read verbatim facts; the pet's name, "
                  "place, and quirk are canon):")
        ln.extend(f"    * {p}" for p in pets)
    else:
        ln.append("- lost & found desk: quiet today, nothing to report")

    return "\n".join(ln)


def wire_lines(date: str, census: dict, forecast_text: str | None) -> list[str]:
    """Code-BUILT one-liners for the news bulletin — guard-true by
    construction (every fact comes straight from this desk's own derivations,
    no LLM in the loop). A short mix: a birthday shout, a calendar reminder,
    and any lost/found pet beat. Safe to drop straight into a bulletin."""
    out = []
    bdays = birthdays(census, date, 1)
    if bdays:
        names = " and ".join(b["name"] for b in bdays)
        out.append(f"Happy birthday today from the Town Desk to {names}.")
    cal = calendar_lines(date, 1)
    if cal:
        out.append(f"On the town calendar: {cal[0]}")
    out.extend(lost_pets(date))
    return out
