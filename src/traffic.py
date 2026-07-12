"""Traffic on the 8s — Halfway's drive-time road desk.

Fictional geography ONLY: the bridge that hums in D, the roundabout at Fifth
and Pine, Mill Road, Route 9, the impound-lot exit — the same made-up town
the rest of the station lives in. Nothing here touches a real map, and no
number is invented that the caller can't check against the sheet.

Code owns the facts; the LLM (if a drive show wants colour) only phrases what
`block()` hands it, and `verify()` holds any authored read to the sheet. The
station's own bulletins use `wire_line()` — code-BUILT copy that is
guard-true by construction and signed by our (invented) roving reporter.

Design (the frozen contract):
  * `incidents(date, slot)` is the single seeded source of truth for a rush.
    Each incident carries onset/clear minutes-of-day inside the slot's window,
    so every report drawn during that rush agrees with every other, and an
    incident that has cleared simply stops appearing — traffic RESOLVES across
    the morning the way real traffic does, without any stored state.
  * `traffic_sheet(date, hour)` is a pure view: the incidents from that hour's
    rush that overlap the hour, each with its delay in minutes.
  * seeded determinism only (`random.Random(f"...")`), stdlib-only, leaf
    module — nothing here imports the orchestrator or a performer.

Every invented name (the reporter, the locations, the causes) is checked
against nameguard's real-world token/phrase banks in the tests; none collide.
"""
from __future__ import annotations

import random
import re

# The roving reporter who signs every bulletin. Invented; not a real person.
REPORTER = "Merv Plunkett"

# ~12 fictional locations. A couple carry route numbers on purpose (real roads
# have them); verify() strips the location text before counting numbers, so a
# "Route 9" never reads as a spoken delay figure.
LOCATIONS = (
    "the bridge",
    "the roundabout at Fifth and Pine",
    "Mill Road",
    "Route 9",
    "the impound-lot exit",
    "the old Exit-4 merge",
    "the Mile Zero roundabout",
    "the pharmacy-lot cut-through",
    "the Tarpline crossing",
    "the Lower Sieve underpass",
    "the Cold Storage bend",
    "the zipper merge past the grange",
)

# ~14 causes — small-town, unhurried, occasionally airborne. Noun phrases that
# drop straight into a sentence. No digits, so they never trip verify().
CAUSES = (
    "a goose crossing",
    "plow staging",
    "a mattress in the eastbound lane",
    "a stalled hay truck",
    "a jackknifed trailer",
    "a downed branch",
    "a slow-moving tractor",
    "a fender-bender",
    "sun glare off the bridge",
    "a parade of ducks",
    "water over the road",
    "a lost sofa",
    "a signal stuck on red",
    "a flag truck that lost its load",
)

# Rush windows, minutes-of-day (inclusive start, exclusive-ish end). AM rush
# runs ~6:00-9:30, PM ~4:00-7:30.
_WINDOWS = {"am": (360, 570), "pm": (960, 1170)}


def _slot_for_hour(hour: int) -> str | None:
    """Which rush an hour belongs to, or None (no rush -> no incidents)."""
    if 6 <= hour <= 9:
        return "am"
    if 16 <= hour <= 19:
        return "pm"
    return None


def incidents(date: str, slot: str) -> list[dict]:
    """The seeded, resolving incident list for one rush.

    `slot` is "am" or "pm". Returns 2-4 incidents, each a dict:
      {"location": str, "cause": str, "delay": int,
       "onset": int, "clear": int}
    where onset/clear are minutes-of-day inside the slot's window and delay is
    a small integer (minutes). Locations are unique within a rush. Purely a
    function of (date, slot): every report during the rush sees the same list,
    and each incident clears at its own `clear` minute, so later reports show
    fewer of them — traffic resolves with no stored state.
    """
    if slot not in _WINDOWS:
        raise ValueError(f"slot must be 'am' or 'pm', got {slot!r}")
    rng = random.Random(f"traffic:{date}:{slot}")
    win_start, win_end = _WINDOWS[slot]
    n = rng.randint(2, 4)
    locs = rng.sample(LOCATIONS, n)
    out = []
    for loc in locs:
        cause = rng.choice(CAUSES)
        onset = rng.randint(win_start, win_end - 40)
        clear = min(onset + rng.randint(20, 90), win_end)
        delay = rng.randint(3, 25)
        out.append({"location": loc, "cause": cause, "delay": delay,
                    "onset": onset, "clear": clear})
    out.sort(key=lambda i: (i["onset"], i["location"]))
    return out


def traffic_sheet(date: str, hour: int) -> dict:
    """The active road picture at `hour` (0-23). A pure view over
    `incidents()`: only incidents whose [onset, clear) overlaps the hour band
    survive, so a 6:40 look and a 7:20 look agree on the shared incidents and
    disagree only where one has already cleared. Off-rush hours are clear.

    Returns {"date", "hour", "slot", "incidents": [...], "clear_road": bool}
    where each incident keeps its delay (small int minutes).
    """
    slot = _slot_for_hour(hour)
    incs: list[dict] = []
    if slot:
        start, end = hour * 60, hour * 60 + 60
        for inc in incidents(date, slot):
            if inc["onset"] < end and inc["clear"] > start:
                incs.append(inc)
    return {"date": date, "hour": hour, "slot": slot,
            "incidents": incs, "clear_road": not incs}


# --- code-BUILT bulletin copy (guard-true by construction) ------------------

_CLEAR_OPENERS = (
    "Roads are wide open across Halfway — nothing to slow you down.",
    "Clean sailing town-wide right now; the bridge is humming and clear.",
    "Nothing on the boards this pass — every route is running free.",
    "All quiet on the pavement; enjoy it while it lasts.",
)
_LEADS = (
    "Here's your drive:",
    "Watching the roads for you:",
    "On the roads this pass, here's the picture:",
    "Couple things out there:",
)
# Each template speaks exactly one number: the delay. That is the only figure
# in the copy, and it is always a sheet number, so wire_line is guard-true.
_INCIDENT_TEMPLATES = (
    "{location} is snarled by {cause} — budget about {delay} minutes.",
    "{cause} at {location}; tack on {delay} minutes through there.",
    "Give yourself {delay} extra minutes at {location}, thanks to {cause}.",
    "{location}'s slow with {cause} — call it {delay} minutes.",
)
_SIGNOFFS = (
    "That's {reporter}, back to you.",
    "{reporter} on the roads — drive it easy.",
    "Reporting from the shoulder, I'm {reporter}.",
    "{reporter} here; I'll have more next pass.",
)


def wire_line(sheet: dict, seed: str) -> str:
    """One code-built traffic bulletin with personality, signed by REPORTER.
    Guard-true by construction: the only numbers it ever speaks are the sheet's
    own delays. Seeded, so the same (sheet, seed) always yields the same read.
    """
    rng = random.Random(f"wire:{seed}:{sheet.get('date')}:{sheet.get('hour')}")
    incs = sheet.get("incidents", [])
    if not incs:
        opener = _CLEAR_OPENERS[rng.randrange(len(_CLEAR_OPENERS))]
        sign = _SIGNOFFS[rng.randrange(len(_SIGNOFFS))].format(reporter=REPORTER)
        return f"{opener} {sign}"
    lead = _LEADS[rng.randrange(len(_LEADS))]
    parts = []
    for inc in incs:
        tmpl = _INCIDENT_TEMPLATES[rng.randrange(len(_INCIDENT_TEMPLATES))]
        parts.append(tmpl.format(location=inc["location"], cause=inc["cause"],
                                 delay=inc["delay"]))
    sign = _SIGNOFFS[rng.randrange(len(_SIGNOFFS))].format(reporter=REPORTER)
    return f"{lead} " + " ".join(parts) + f" {sign}"


def block(sheet: dict) -> str:
    """The authoritative TRAFFIC SHEET prompt block for a drive show that wants
    to author its own read. Every fact a host may speak is here, and nowhere
    else; verify() holds the read to it."""
    ln = ["TRAFFIC SHEET (authoritative — the ONLY road conditions that exist):"]
    incs = sheet.get("incidents", [])
    if not incs:
        ln.append("- roads are clear town-wide; nothing to report")
    else:
        for inc in incs:
            ln.append(f"- {inc['location']}: {inc['cause']}, "
                      f"about {inc['delay']} minutes of delay")
    ln.append(f"Reporter on the beat: {REPORTER}. Speak only delays shown "
              "above; invent no times, no counts, no other numbers.")
    return "\n".join(ln)


# --- desk-style verify: every small number in a read is a sheet number ------

_NUM_WORDS = {"zero": 0, "nothing": 0, "nil": 0, "one": 1, "two": 2,
              "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
              "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
              "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20}


def verify(texts: list[str], sheet: dict) -> bool:
    """Nothing airs that isn't on the sheet: every small number in the read
    (digits or spelled) must be a sheet delay — or the incident count, which a
    host might legitimately say ("a couple of slow spots"). Location and cause
    strings are stripped first, so a road's own route number (Route 9, Exit-4)
    is never mistaken for a spoken delay. One stray number fails the read and
    the caller falls back to wire_line."""
    body = " " + " ".join(texts).lower() + " "
    for inc in sheet.get("incidents", []):
        for phrase in (inc["location"], inc["cause"]):
            body = body.replace(phrase.lower(), " ")
    for w, v in _NUM_WORDS.items():
        body = re.sub(rf"\b{w}\b", f" {v} ", body)
    allowed = {len(sheet.get("incidents", []))}
    for inc in sheet.get("incidents", []):
        allowed.add(inc["delay"])
    for tok in re.findall(r"\b\d{1,3}\b", body):
        if int(tok) not in allowed:
            return False
    return True
