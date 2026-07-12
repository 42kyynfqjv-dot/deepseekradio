"""Storm Watch core — the blizzard engine's fact layer (Row 5).

A SOFT takeover: on a genuine snow day the Morning Scramble slot becomes
Storm Watch (Wesley + a closings sheet), energy shifts, the format does not
break. `run_blizzard` (the live-air wiring) is INTEGRATION's; this leaf owns
only the facts the booth is allowed to speak, in the frozen desk pattern:
code decides every number, the LLM only phrases it, and `verify` holds the
read to the sheet.

House rules honored: stdlib only; leaf module (imports nothing from the
station); no network (forecast text is passed in, never fetched here); seeded
determinism (`random.Random(f"...")`, never bare random / wall-clock);
`storm_sheet`/`closings` are PURE functions of their args (derive, don't
store — no state file). Every invented Halfway name below is small-town
generic and collision-checked against nameguard._WORLD_TOKENS/_WORLD_PHRASES
by the test suite.

Forecast text shape (spots._real_forecast): e.g.
  "now 32F wind 15mph code 73; today high 35F low 20F rain 90 percent; ..."
so `is_storm` reads both plain-language tells ("snow", "blizzard") and the
WMO `code NN` field; `storm_sheet` lifts the real wind number when present.
"""
from __future__ import annotations

import random
import re

# --- WMO weather codes that mean frozen precipitation (Open-Meteo `code`
# field): freezing drizzle 56/57, freezing rain 66/67, snow 71/73/75,
# snow grains 77, snow showers 85/86. Rain-only codes are deliberately out.
_SNOW_CODES = {56, 57, 66, 67, 71, 73, 75, 77, 85, 86}

# Plain-language storm tells (word-boundary matched, so "service"/"notice"
# never trip "ice", and "brain" never trips "rain").
_STORM_WORDS = (
    "blizzard", "snow", "snowfall", "snowstorm", "snowy", "flurries",
    "flurry", "sleet", "ice", "icy", "wintry", "freezing", "whiteout",
    "squall", "squalls", "nor'easter", "noreaster", "wind chill",
)

# --- Halfway closings bank (~30). All small-town generic, no real brand /
# person (collision-checked against nameguard in the test). Cumulative reveal
# draws a growing seeded prefix of this list, so a closing NEVER un-closes.
_CLOSINGS_BANK = (
    "Halfway Elementary",
    "Halfway Regional High",
    "the Little Acorns preschool",
    "the county courthouse annex",
    "the Halfway Grange",
    "the public library",
    "the library book sale",
    "the senior center hot-lunch",
    "the impound lot window",
    "town hall (except the plow office)",
    "the Fifth and Pine post office",
    "the Mill Road credit union",
    "the community pool (indoor, somehow)",
    "the volunteer fire hall bingo",
    "the farm stand out past the creek",
    "the Halfway food co-op",
    "the ice rink (closed, ironically)",
    "the animal shelter adoption day",
    "the DMV satellite trailer",
    "the parks department office",
    "the historical society open house",
    "the Wednesday farmers market",
    "the rec-league practice",
    "the knitting circle at the church basement",
    "the recycling transfer station",
    "the water district billing window",
    "the bridge appreciation walk",
    "the grange pancake supper",
    "the after-school robotics club",
    "the town band rehearsal",
    "the planning board meeting",
)

# Verbs of closure — every one is a CLOSING (never a re-open), so cumulative
# reveals only ever add shut things.
_CLOSE_VERBS = (
    "is closed",
    "is closed for the day",
    "won't open today",
    "is shut until the plow gets through",
    "cancels today's session",
    "is dark today",
    "stays closed",
    "calls it off for the day",
)

# --- Plow bank: fictional Halfway/Route-9 geography (shared canon with the
# traffic row). storm_sheet seeds where the plow IS and where it plainly IS
# NOT ("the plow is on Mill Road; it has not seen Route 9 or the bridge").
_PLOW_BANK = (
    "Mill Road",
    "Route 9",
    "the bridge",
    "the roundabout at Fifth and Pine",
    "the impound lot exit",
    "the high school hill",
    "Creamery Lane",
    "the Grange parking lot",
    "the north end of Main",
    "the county line stretch",
)


def is_storm(forecast_text: str | None) -> bool:
    """True when a forecast string carries a snow / blizzard / ice tell.
    `None` (or empty / the '(no forecast data ...)' sentinel) -> False. Pure,
    no network."""
    if not forecast_text:
        return False
    text = forecast_text.lower()
    for word in _STORM_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", text):
            return True
    for m in re.finditer(r"\bcode\s+(\d{1,3})\b", text):
        if int(m.group(1)) in _SNOW_CODES:
            return True
    return False


def _wind_from_forecast(forecast_text: str | None):
    """Lift the real wind mph from spots._real_forecast text ('wind 15mph'),
    or None if absent — so a live storm reports the sky's actual wind."""
    if not forecast_text:
        return None
    m = re.search(r"\bwind\s+(\d{1,2})\s*mph\b", forecast_text.lower())
    return int(m.group(1)) if m else None


def storm_sheet(date: str, forecast_text: str) -> dict:
    """Seeded storm facts for `date`: inches so-far / expected (so-far never
    exceeds expected), wind mph (the forecast's real number when present, else
    seeded), and the plow's whereabouts — one road it's on, two it plainly
    isn't. PURE: same (date, forecast_text) -> same sheet, no I/O.

    Every number here is authoritative; `verify` holds the on-air read to it.
    """
    rng = random.Random(f"storm:{date}")
    inches_expected = rng.randint(6, 20)
    inches_so_far = rng.randint(1, inches_expected)
    wind = _wind_from_forecast(forecast_text)
    if wind is None:
        wind = rng.randint(15, 45)
    plow = list(_PLOW_BANK)
    rng.shuffle(plow)
    plow_at = plow[0]
    plow_not_at = plow[1:3]
    return {
        "date": date,
        "inches_so_far": inches_so_far,
        "inches_expected": inches_expected,
        "wind": wind,
        "plow_at": plow_at,
        "plow_not_at": plow_not_at,
    }


def _closing_line(entry: str, rng: random.Random) -> str:
    return f"{entry} {rng.choice(_CLOSE_VERBS)}."


def closings(date: str, beat: int) -> list[str]:
    """CUMULATIVE seeded closings for `date` at broadcast `beat` (0-indexed).
    The closings roll in as the morning goes: beat k's list is a superset of
    beat k-1's (closings never un-close), drawn as a growing prefix of a
    date-seeded shuffle of the ~30-entry bank. Each entry's closure verb is
    itself seeded, so a given closing reads identically at every later beat.

    beat < 0 -> empty; beat is clamped so the list saturates at the whole
    bank once every institution in town has given up.
    """
    if beat < 0:
        return []
    rng = random.Random(f"closings:{date}")
    order = list(range(len(_CLOSINGS_BANK)))
    rng.shuffle(order)
    # reveal 4 at beat 0, +3 per beat, saturating at the bank size
    count = min(len(order), 4 + 3 * beat)
    out = []
    for idx in order[:count]:
        entry = _CLOSINGS_BANK[idx]
        vrng = random.Random(f"closeverb:{date}:{idx}")
        out.append(_closing_line(entry, vrng))
    return out


def block(sheet: dict, closings_list: list[str]) -> str:
    """The authoritative STORM WATCH facts block handed to Wesley's writer.
    The ONLY numbers that may air are the three on the sheet; the closings are
    verbatim, code-built, and carry no numbers to spoil the count."""
    ln = ["STORM WATCH SHEET (authoritative — the ONLY storm facts that exist):"]
    ln.append(f"- snow so far: {sheet['inches_so_far']} inches; "
              f"expected total: {sheet['inches_expected']} inches")
    ln.append(f"- wind: {sheet['wind']} mph")
    ln.append(f"- the plow is on {sheet['plow_at']}; it has NOT reached "
              f"{' or '.join(sheet['plow_not_at'])}")
    ln.append("CLOSINGS (read these verbatim; do not invent any others):")
    if closings_list:
        for c in closings_list:
            ln.append(f"- {c}")
    else:
        ln.append("- nothing is closed yet — Halfway is stubborn")
    return "\n".join(ln)


_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20,
}


def verify(texts: list[str], sheet: dict) -> bool:
    """desk_verify-style guard: every small number in the authored read must
    be a sheet number (inches so-far, inches expected, or wind). Spelled
    numbers count (the chartguard lesson). One strike and the caller falls
    back to code-built copy."""
    body = " " + " ".join(texts).lower() + " "
    for w, v in _NUM_WORDS.items():
        body = re.sub(rf"\b{w}\b", f" {v} ", body)
    allowed = {sheet["inches_so_far"], sheet["inches_expected"], sheet["wind"]}
    # A plow location may itself carry a number (e.g. "Route 9"); a read that
    # names where the plow is/isn't must be allowed to speak that number.
    plow_text = " ".join([sheet.get("plow_at", "")] + list(sheet.get("plow_not_at", [])))
    for tok in re.findall(r"\d{1,2}", plow_text):
        allowed.add(int(tok))
    for tok in re.findall(r"\b\d{1,2}\b", body):
        if int(tok) not in allowed:
            return False
    return True
