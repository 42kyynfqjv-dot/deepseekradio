"""World spine — the one-world bus (`world-events.json`).

Single leaf module, single writer (`project`, Row A), pure-read consumers
(`digest`, this file's Row B deliverable). Imports NOTHING from `season`,
`league.*`, `statehouse.*`, `spots`, `orchestrator` — those import *it*. It
only ever reads a sibling's committed, already-air-gated JSON (the established
cross-process pattern), never engine code.

This file carries Row B: the three-product consumer API `digest(day, show,
want)`. The frozen-signature read helpers it leans on (`load`, `on`) live here
too so the consumer surface is self-contained and instantly revocable — with
`data/world/ENABLED` absent, `digest` returns empty and every show renders
byte-identically to today. Row A grafts the producer side (`tick` +
`_weather_event`/`_league_events`/`_city_events` + `save`/prune) onto this
same module against these same constants; the two halves share only the bus
file's shape and never mutate each other's state. Row C grafts one dark
causal edge (Cup run -> governor approval) as a QUEUE the statehouse gate
will later drain, gets its own flag (`data/world/CAUSAL-ENABLED`), and is a
pure no-op — no file even created — while that flag is absent.
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import time
from pathlib import Path

# --------------------------------------------------------------- frozen paths
_REPO = Path(__file__).resolve().parent.parent
WORLD = _REPO / "world-events.json"          # bus file, season.json's sibling
FLAG = _REPO / "data" / "world" / "ENABLED"  # gate; absent => dormant
RETAIN_DAYS = 45                             # league catch-up window (Row A prunes)

# ------------------------------------------------------- frozen paths (Row A)
SEASON_JSON = _REPO / "season.json"                    # league's own state
BOX_DIR = _REPO / "data" / "league" / "box"            # box/{day}.json shards
BIBLE = _REPO / "station" / "bible.md"                 # sponsor roster source

# Halfway canon coords (world-spine-final.md judge fix #2): "44.98 N, -73.45
# W — northern border country, snow-plausible, Boreal-consistent." Single
# source of truth for the weather producer AND every consumer that needs the
# same city's sky (world_consumers._halfway_coords falls back to its own
# copy only while this leaf is mid-build).
HALFWAY_LATLON = {"lat": 44.98, "lon": -73.45}

# WMO weather codes that mean snow (Open-Meteo's `weather_code`).
_SNOW_CODES = {71, 73, 75, 77, 85, 86}

# Sponsor-roster line format, straight off spots._roster (duplicated, not
# imported — world.py reads on-disk/doc state, never engine code).
_ROSTER_RE = re.compile(r"^\s*-\s*\*([^*]+)\*\s*[—-]+\s*(.+?)\s*$")

# Seeded daily city-color templates — evergreen, non-causal, never a spoiler.
_CITY_KINDS = (
    ("goose_sighting", "a goose holds the {sponsor} lot again"),
    ("sponsor_spotted", "{sponsor} got a mention on the scanner"),
    ("quiet_day", "a quiet day around {sponsor}"),
)

# ------------------------------------------------------- frozen paths (Row C)
# The dark causal edge: Cup run -> governor approval. world.py never touches
# civics.json (no engine imports/mutates another) — it only enqueues a
# clamped delta for the statehouse's OWN `_EVENT_DELTA` table to drain on its
# own next-day tick, behind its OWN separate gate. Absent CAUSAL_FLAG, this
# whole edge is dark: the queue file is never created, let alone written.
CAUSAL_FLAG = _REPO / "data" / "world" / "CAUSAL-ENABLED"
APPROVAL_QUEUE = _REPO / "data" / "world" / "approval-queue.json"

# Mirrors the statehouse's own clamped event-delta shape (`_EVENT_DELTA`): a
# cup_run stage maps to a small mean-reverting bump, always clamped.
_CUP_APPROVAL_DELTA = {
    "round1_win": 0.5, "round2_win": 1.0, "round3_win": 1.5,
    "champion": 3.0, "early_exit": -0.5,
}
_CUP_DELTA_CLAMP = 3.0

# ---------------------------------------------------------- consumption model
# External-INPUT facts (weather, city color) are consumable SAME day they are
# projected. Cross-engine OUTPUT facts (a game final, a quorum failure) are
# consumable the day AFTER they settle and air — the next-day rule that breaks
# every intra-tick cycle and gives air-gating for free (full-causal §11 rule 3).
_SAME_DAY = {"weather", "city"}
_DAY_AFTER = {"league", "statehouse"}
_ALL_PRODUCERS = _SAME_DAY | _DAY_AFTER

# Reading order for deterministic assembly (weather sets the scene, then the
# league, the town, the Dome).
_PRODUCER_RANK = {"weather": 0, "league": 1, "city": 2, "statehouse": 3}

# Per-show relevance allowlist: which producers a show may CITE. A show never
# sees its own institution's facts echoed back — Center Ice gets civic/weather
# color but not the around-the-league scores it already narrates; the Dome desk
# gets the Cup run but authors its own civic numbers.
_SHOW_PRODUCERS = {
    "center-ice": {"weather", "city", "statehouse"},
    "morning": {"weather", "league", "city", "statehouse"},
    "daytime": {"weather", "league", "city", "statehouse"},
    "world-desk": {"weather", "league", "city", "statehouse"},
    "news": {"weather", "league", "city", "statehouse"},
    "statehouse": {"weather", "league", "city"},
}

# The SCOREBOARD-register prompt-block wrapper (texture-first prompt contract).
# Qualitative only: every hard number travels as verbatim WIRE copy, never here.
_BLOCK = (
    "AROUND WENDING TODAY (all real and already aired — reference in THIS "
    "show's own register; do NOT restate as a bulletin, do NOT invent or "
    "change any number, do NOT contradict): {facts}. You MAY color the "
    "weather delivery (the numbers are roughly right); you may NOT invent "
    "scores, tallies, or margins — any hard number you need has already been "
    "read for you on the wire."
)

_EMPTY = {"wire": [], "prompt": "", "guard": {}}


# ------------------------------------------------------------------ read side
def on() -> bool:
    """The gate. Absent flag => the whole spine is dormant and `digest`
    returns empty, so every consumer falls back to its current behavior."""
    try:
        return FLAG.exists()
    except Exception:
        return False


def load() -> dict:
    """Trust rule (season.json / league sidecar): live file, then `.bak`,
    then a fresh empty bus. A missing file is an empty bus, never an error."""
    for p in (WORLD, WORLD.with_suffix(".bak")):
        try:
            if p.exists():
                bus = json.loads(p.read_text())
                if isinstance(bus, dict) and isinstance(bus.get("days"), dict):
                    return bus
        except Exception:
            continue
    return {"schema": 1, "days": {}}


# --------------------------------------------------------------- consumer API
def digest(day: str, *, show: str, want: set | None = None,
           now: float | None = None) -> dict:
    """Assemble the three products for `show` on `day`.

    Returns ``{"wire": [str, ...], "prompt": str, "guard": {...}}``:

    - **wire**  — code-authored verbatim lines (each event's `wire`, produced
      by Row A in the sports-desk register), dropped in as-is by the
      orchestrator; the LLM never re-authors them so their numbers need no
      guard.
    - **prompt** — a single SCOREBOARD-register block of the events'
      qualitative `prompt` phrasings, or ``""`` when there is nothing to say.
    - **guard** — ``allow_pairs`` (score pairs) + ``names`` merged from the
      events' `guard`, ready to fold into the destination show's existing
      whitelist (`scoreguard.allow_pairs` / a name allowlist).

    Filters: air_at <= now (belt-and-braces; the bus only ever holds
    already-public projections), the next-day consumption rule for
    cross-engine events, per-show relevance, and `supersedes` (an append-only
    correction hides the fact it replaces). Total fallback: FLAG off or any
    exception -> empty, and the show renders byte-identically to today.
    """
    try:
        if not on():
            return dict(_EMPTY)
        if now is None:
            now = time.time()
        bus = load()
        allowed = _allowed_producers(show, want)
        events = _gather(bus, day, allowed, now)
        events.sort(key=_sort_key)

        wire, facts = [], []
        allow_pairs, names = [], []
        seen_pairs, seen_names = set(), set()
        for e in events:
            w = e.get("wire")
            if w:
                wire.append(w)
            p = e.get("prompt")
            if p:
                facts.append(p)
            g = e.get("guard") or {}
            for pair in (g.get("score_pairs") or g.get("allow_pairs") or []):
                try:
                    key = tuple(sorted((int(pair[0]), int(pair[1]))))
                except (TypeError, ValueError, IndexError):
                    continue
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    allow_pairs.append([key[0], key[1]])
            for nm in (g.get("names") or []):
                if nm not in seen_names:
                    seen_names.add(nm)
                    names.append(nm)

        guard = {}
        if allow_pairs:
            guard["allow_pairs"] = allow_pairs
        if names:
            guard["names"] = names
        return {
            "wire": wire,
            "prompt": _BLOCK.format(facts="; ".join(facts)) if facts else "",
            "guard": guard,
        }
    except Exception as exc:  # noqa: BLE001 — degrade to silence, never crash a show
        print(f"  !! world.digest degraded ({exc}) — empty digest")
        return dict(_EMPTY)


# --------------------------------------------------------------- helpers (read)
def _allowed_producers(show: str, want: set | None) -> set:
    base = _SHOW_PRODUCERS.get(show, set(_ALL_PRODUCERS))
    if want:
        return {p for p in want if p in _ALL_PRODUCERS}
    return set(base)


def _gather(bus: dict, day: str, allowed: set, now: float) -> list:
    """Collect the events consumable on `day`: SAME_DAY producers keyed to
    `day`, DAY_AFTER producers keyed to the previous day. So a league fact
    dated D is invisible on D (still settling/airing) and surfaces on D+1."""
    days = bus.get("days", {})
    prev = _prev_day(day)
    out = []
    for src_day, klass in ((day, _SAME_DAY), (prev, _DAY_AFTER)):
        if src_day is None:
            continue
        for e in days.get(src_day, []):
            if not isinstance(e, dict):
                continue
            prod = e.get("producer")
            if prod not in allowed or prod not in klass:
                continue
            if not _air_ok(e, now):
                continue
            out.append(e)
    # append-only corrections: a superseding event hides the id it replaces
    superseded = {e["supersedes"] for e in out if e.get("supersedes")}
    if superseded:
        out = [e for e in out if e.get("id") not in superseded]
    return out


def _air_ok(event: dict, now: float) -> bool:
    """Air-gate: an event with no air stamp (weather/city, always public) is
    always visible; otherwise it must have aired (air_at <= now)."""
    air = event.get("air_at")
    if air in (None, 0, 0.0):
        return True
    try:
        return float(air) <= now
    except (TypeError, ValueError):
        return True


def _sort_key(e: dict):
    return (_PRODUCER_RANK.get(e.get("producer"), 9),
            str(e.get("subject") or e.get("key") or ""),
            str(e.get("type") or ""),
            str(e.get("id") or ""))


def _prev_day(day: str) -> str | None:
    try:
        import datetime
        d = datetime.date.fromisoformat(day) - datetime.timedelta(days=1)
        return d.isoformat()
    except Exception:
        return None


# ===================================================================
# Row A — producer side: the single writer
# ===================================================================
# `tick(date)` derives the day's events from each engine's already-committed
# on-disk state (never engine code) and merges them into the bus. Merge is
# APPEND-ONLY: an event already on the bus is NEVER mutated or dropped by a
# later tick. A fresh derivation whose id is new is appended; a derivation
# whose id already exists but whose body now differs (a correction) is
# appended as a NEW versioned event carrying `supersedes` — the original
# stays exactly as it aired. Re-deriving from UNCHANGED source state is
# therefore a true no-op: byte-identical idempotent re-derivation.

def _read_json(path: Path) -> dict | None:
    try:
        if path.exists():
            data = json.loads(path.read_text())
            return data if isinstance(data, dict) else None
    except Exception:
        pass
    return None


def _read_text(path: Path) -> str | None:
    try:
        if path.exists():
            return path.read_text()
    except Exception:
        pass
    return None


def _atomic_write(path: Path, data: dict) -> None:
    """The established `_save` discipline (season.json / civics.json): copy
    (not rename) live -> `.bak` first so the file never disappears mid-read,
    then tmp+replace for the single atomic mutation of the live path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2))
    if path.exists():
        try:
            shutil.copy2(path, path.with_suffix(".bak"))
        except Exception:
            pass
    tmp.replace(path)


def save(bus: dict) -> None:
    """The bus's one writer-side mutation. Atomic tmp+replace + `.bak`."""
    _atomic_write(WORLD, bus)


# ------------------------------------------------------------- weather (§4)
def _fetch_open_meteo(coords: dict) -> dict | None:
    """Real network fetch (Open-Meteo, free/keyless), isolated so tests can
    inject `fetch_fn` instead of hitting the network."""
    try:
        import requests
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": coords["lat"], "longitude": coords["lon"],
                    "current": "temperature_2m,weather_code,wind_speed_10m",
                    "daily": "temperature_2m_max,temperature_2m_min,"
                             "snowfall_sum",
                    "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
                    "timezone": "America/New_York", "forecast_days": 1},
            timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _weather_prompt(tmax, is_snow: bool, wind) -> str:
    cond = "snow falling" if is_snow else "clear skies"
    tail = f", wind up around {wind} mph" if wind else ""
    return f"{cond}, high near {tmax}F{tail}"


def _weather_event(date: str, *, fetch_fn=None) -> dict | None:
    """The weather producer: one Halfway fetch a day, projected into the bus
    schema. Missing-feed rule (unchanged from `calendar.is_snowfall`): no
    feed => no event, ever — weather is never invented. `fetch_fn(coords)`
    is the test seam; production defaults to the real Open-Meteo fetch,
    always called with `HALFWAY_LATLON` so every consumer reports the same
    city's sky."""
    fetch = fetch_fn or _fetch_open_meteo
    try:
        raw = fetch(HALFWAY_LATLON)
    except Exception:
        raw = None
    if not isinstance(raw, dict):
        return None
    cur = raw.get("current") or {}
    daily = raw.get("daily") or {}
    try:
        tmax = (daily.get("temperature_2m_max") or [None])[0]
        tmin = (daily.get("temperature_2m_min") or [None])[0]
        snowfall = (daily.get("snowfall_sum") or [0])[0] or 0
        code = cur.get("weather_code")
        wind = cur.get("wind_speed_10m")
    except Exception:
        return None
    if tmax is None or code is None:
        return None
    is_snow = bool(snowfall and snowfall > 0) or code in _SNOW_CODES
    return {
        "id": f"weather.day:{date}", "type": "weather.day",
        "producer": "weather", "subject": "halfway", "day": date, "air_at": 0,
        "payload": {"tmax": tmax, "tmin": tmin, "snow": is_snow,
                    "snowfall": snowfall, "code": code, "wind": wind},
        "wire": None,
        "prompt": _weather_prompt(tmax, is_snow, wind),
        "guard": {}, "tags": ["weather"] + (["snow"] if is_snow else []),
    }


def weather_fn(date: str, *, fetch_fn=None) -> dict | None:
    """The statehouse/league snow-hook adapter: the `{snowfall, cond, ...}`
    shape `calendar.is_snowfall` expects, or None (never invented) when
    there is no feed. Not wired into `statehouse.tick` by this build (ships
    behind its own `data/world/WEATHER-QUORUM` flag, per final.md)."""
    ev = _weather_event(date, fetch_fn=fetch_fn)
    if not ev:
        return None
    p = ev["payload"]
    return {"snowfall": p["snowfall"], "cond": "snow" if p["snow"] else "clear",
            "tmax": p["tmax"], "tmin": p["tmin"], "wind": p["wind"]}


# --------------------------------------------------------------- league (§5)
def _league_events(date: str, *, season: dict | None = None,
                    box: dict | None = None) -> list:
    """The league producer: off-air slate finals from `season.json`'s own
    `slates[date]` (the exact v1-mirror shape `season.py` writes) enriched
    with that day's box shard for OT/SO detail, plus any `cup_run` clinches
    recorded in `season.json["cup_runs"][date]`. Pure projection of
    committed state — no import of `season` or `league.*`."""
    if season is None:
        season = _read_json(SEASON_JSON)
    if not isinstance(season, dict):
        return []
    events = []

    slate = (season.get("slates") or {}).get(date) or []
    day_box = box if box is not None else (_read_json(BOX_DIR / f"{date}.json"))
    day_box = day_box if isinstance(day_box, dict) else {}
    by_pair = {}
    for g in day_box.get("games") or []:
        if isinstance(g, dict) and "home" in g and "away" in g:
            by_pair[(g["home"], g["away"])] = g

    for row in slate:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        hk, ak, hg, ag, ot = row[0], row[1], row[2], row[3], row[4]
        g = by_pair.get((hk, ak), {})
        so = bool(g.get("so"))
        ot = bool(ot) and not so
        hname = g.get("home_name") or hk
        aname = g.get("away_name") or ak
        suffix = " in a shootout" if so else (" in OT" if ot else "")
        events.append({
            "id": f"league.final:{date}:{hk}-{ak}", "type": "league.final",
            "producer": "league", "subject": hk, "day": date, "air_at": 0,
            "payload": {"home": hname, "away": aname, "score": [hg, ag],
                        "ot": ot, "so": so},
            "wire": f"Around the league: the {hname} took the {aname} "
                    f"{hg}-{ag}{suffix}.",
            "prompt": f"the {hname} beat the {aname} {hg}-{ag} last night",
            "guard": {"score_pairs": [[hg, ag]], "names": [hname, aname]},
            "tags": ["hockey", "result"],
        })

    for rec in (season.get("cup_runs") or {}).get(date, []) or []:
        if not isinstance(rec, dict):
            continue
        team, stage = rec.get("team"), rec.get("stage")
        if not team or not stage:
            continue
        events.append({
            "id": f"league.cup_run:{date}:{team}:{stage}",
            "type": "league.cup_run", "producer": "league", "subject": team,
            "day": date, "air_at": 0,
            "payload": {"team": team, "stage": stage,
                        "series": rec.get("series")},
            "wire": None,
            "prompt": f"{team} advance in the Cup run: {stage.replace('_', ' ')}",
            "guard": {}, "tags": ["hockey", "cup"],
        })
    return events


# ----------------------------------------------------------------- city (§7)
def _parse_roster(text: str) -> list:
    return [(m.group(1).strip(), m.group(2).strip())
            for line in text.splitlines()
            if (m := _ROSTER_RE.match(line))]


def _city_events(date: str, *, bible_text: str | None = None) -> list:
    """The city producer: a seeded daily pick over the sponsor roster
    (parsed straight from the bible, `spots.py`'s own source of truth) —
    evergreen color, never causal, deterministic per day (`Random(f"city:
    {date}")`, replay-stable, never wall-clock)."""
    if bible_text is None:
        bible_text = _read_text(BIBLE)
    roster = _parse_roster(bible_text) if bible_text else []
    if not roster:
        return []
    rng = random.Random(f"city:{date}")
    name, gag = rng.choice(roster)
    kind, tmpl = rng.choice(_CITY_KINDS)
    return [{
        "id": f"city.color:{date}", "type": "city.color", "producer": "city",
        "subject": name, "day": date, "air_at": 0,
        "payload": {"kind": kind, "sponsor": name, "gag": gag},
        "wire": None,
        "prompt": tmpl.format(sponsor=name),
        "guard": {"names": [name]},
        "tags": ["city"],
    }]


# ------------------------------------------------- append-only merge + prune
def _event_body(e: dict) -> dict:
    return {k: v for k, v in e.items() if k not in ("id", "supersedes")}


def _live_version(out: list, base_id: str) -> str:
    """Which version of `base_id` is currently unsuperseded on `out` — the
    correct `supersedes` target for a NEW correction (handles a second
    correction landing on top of a first)."""
    superseded = {e.get("supersedes") for e in out if e.get("supersedes")}
    candidates = [e.get("id") for e in out
                  if e.get("id") == base_id
                  or str(e.get("id", "")).startswith(base_id + "#v")]
    live = [i for i in candidates if i not in superseded]
    return max(live) if live else base_id


def _merge_day(existing: list, derived: list) -> list:
    """Append-only merge. Events already on `existing` are NEVER mutated,
    reordered, or removed — a new Python object is always what changes,
    never the old one in place. A derived event with a brand-new id is
    appended. A derived event whose id already exists but whose body now
    differs is appended as a NEW versioned id carrying `supersedes` pointing
    at the currently-live version. A derived event identical to what is
    already stored is a no-op — this is what makes re-derivation
    idempotent."""
    by_id = {e.get("id"): e for e in existing if isinstance(e, dict)}
    out = list(existing)
    for ev in derived:
        old = by_id.get(ev["id"])
        if old is None:
            out.append(ev)
            by_id[ev["id"]] = ev
        elif _event_body(old) == _event_body(ev):
            continue                       # unchanged -> idempotent no-op
        else:
            live_id = _live_version(out, ev["id"])
            n = 2
            new_id = f"{ev['id']}#v{n}"
            while new_id in by_id:
                n += 1
                new_id = f"{ev['id']}#v{n}"
            corrected = dict(ev)
            corrected["id"] = new_id
            corrected["supersedes"] = live_id
            out.append(corrected)
            by_id[new_id] = corrected
    return out


def _prune(bus: dict) -> None:
    """45-day retention (RETAIN_DAYS), matching league catch-up. Anything
    older is canon already living in the producing engine's own state."""
    days = bus.setdefault("days", {})
    if len(days) <= RETAIN_DAYS:
        return
    for old in sorted(days)[:-RETAIN_DAYS]:
        del days[old]


def _write_day(date: str, derived: list) -> list:
    bus = load()
    days = bus.setdefault("days", {})
    merged = _merge_day(days.get(date, []), derived)
    days[date] = merged
    _prune(bus)
    save(bus)
    return merged


def tick(date: str, *, fetch_fn=None, season: dict | None = None,
         box: dict | None = None, bible_text: str | None = None,
         now: float | None = None) -> dict:
    """Derive + persist `date`'s events from committed engine state (weather
    first, then the league, then the town — the reading order `_PRODUCER_
    RANK` also uses), append-only merged onto the bus, then drain Row C's
    dark causal edge for `date`. Returns the day's bundle. Idempotent:
    calling `tick(date)` twice with unchanged source state leaves the bus
    for `date` byte-identical."""
    derived = []
    w = _weather_event(date, fetch_fn=fetch_fn)
    if w:
        derived.append(w)
    derived.extend(_league_events(date, season=season, box=box))
    derived.extend(_city_events(date, bible_text=bible_text))
    events = _write_day(date, derived)
    causal = enqueue_causal(date, now=now)
    return {"day": date, "events": events, "causal": causal}


# ===================================================================
# Row C — the dark causal edge: Cup run -> governor approval
# ===================================================================
def causal_on() -> bool:
    """The Row-C gate. Absent => the whole causal edge is dark: no queue
    file is created or touched, ever — total gate-off inertness."""
    try:
        return CAUSAL_FLAG.exists()
    except Exception:
        return False


def enqueue_causal(date: str, *, now: float | None = None) -> list:
    """If (and only if) `data/world/CAUSAL-ENABLED` exists, read `date`'s
    consumable `league.cup_run` bus events (the SAME next-day/air-gate rule
    `_gather` already enforces for every other consumer) and append their
    clamped approval deltas to the queue — day-keyed, append-only, 45-day
    pruned, idempotent (re-running for an already-queued day is a no-op).
    world.py never writes civics.json itself; the statehouse's own gated
    tick drains this queue through its own `_EVENT_DELTA` table. Gate off
    (the default) is a pure no-op: the queue file is never even created."""
    if not causal_on():
        return []
    try:
        if now is None:
            now = time.time()
        bus = load()
        runs = [e for e in _gather(bus, date, {"league"}, now)
                if e.get("type") == "league.cup_run"]
        if not runs:
            return []
        queue = _read_json(APPROVAL_QUEUE) or {"schema": 1, "days": {}}
        days = queue.setdefault("days", {})
        if date in days:                   # idempotent: already queued
            return days[date]
        entries = []
        for ev in runs:
            stage = ev.get("payload", {}).get("stage")
            base = _CUP_APPROVAL_DELTA.get(stage)
            if base is None:
                continue
            delta = max(-_CUP_DELTA_CLAMP, min(_CUP_DELTA_CLAMP, base))
            entries.append({"team": ev["payload"].get("team"), "stage": stage,
                             "delta": delta, "source": ev.get("id")})
        if not entries:
            return []
        days[date] = entries
        if len(days) > RETAIN_DAYS:
            for old in sorted(days)[:-RETAIN_DAYS]:
                del days[old]
        _atomic_write(APPROVAL_QUEUE, queue)
        return entries
    except Exception as exc:  # noqa: BLE001 — dark edge must never break a tick
        print(f"  !! world.enqueue_causal degraded ({exc}) — queue unchanged")
        return []
