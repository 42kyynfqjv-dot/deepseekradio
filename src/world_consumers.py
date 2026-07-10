"""World-spine consumer wiring (Row D) — pure helpers + integration patch spec.

Phase-1 texture-first citation layer. This is a LEAF: it imports the shared
`world` bus leaf defensively (never an engine, never the orchestrator, never
spots) and offers two code-authored consumer surfaces plus the weather-coords
unification that lets Wesley, the weather spots and the spine all report the
SAME city's sky:

  * `news_world_line(day)`  — the sports-desk pattern: one code-authored wire
    line for `_news_bulletin`, guard-true because the LLM never re-authors it.
  * `morning_block(day)`    — a SCOREBOARD-register WORLD prompt block (+ the
    guard allow-list payload) for the morning show's prompt.
  * `_real_forecast(coords)` — an EXACT-DIFF COPY of `spots._real_forecast`
    with a `coords` parameter, so the network fetch can be pointed at Halfway
    (§Halfway canon) instead of the legacy NYC constant. The diff to apply to
    spots.py, and the Wesley-hook patch, are documented verbatim below — this
    module DOES NOT edit spots.py or orchestrator.py (integration owns them).

Gate discipline: everything degrades to inert. If `data/world/ENABLED` is
absent, or the bus is mid-build / unreadable, every helper returns its empty
value and every consuming show renders byte-identically to today.

Stdlib-only, except `requests` in the weather-fetch path — allowed there
because that path mirrors `spots._real_forecast` exactly (per the frozen scope
rule). No number this module surfaces is ever re-authored by a model: numeric
facts travel as verbatim wire copy or as guard-verified allow-list pairs.
"""
from __future__ import annotations

import requests

# Halfway canon coords (world-spine-final.md §2: "44.98 N, -73.45 W — northern
# border country, snow-plausible, Boreal-consistent"). The single source of
# truth is `world.HALFWAY_LATLON`; this is the fallback when the bus leaf is not
# importable yet (sibling mid-build), so the two never silently disagree.
HALFWAY_LATLON = {"lat": 44.98, "lon": -73.45}

_EMPTY = {"wire": [], "prompt": "", "guard": {}}

# The SCOREBOARD-register frame the morning block wraps the bus prompt in
# (world-spine texture-first §prompt-block-contract). Qualitative only: any hard
# number the show might legitimately cite arrives as verbatim wire copy or as a
# guard-verified allow pair — never invented in the block.
_BLOCK_HEAD = (
    "AROUND WENDING TODAY (all real and already aired — reference in THIS "
    "show's own register; do NOT restate as a bulletin, do NOT invent or "
    "change any number, do NOT contradict): ")
_BLOCK_TAIL = (
    ". You MAY color the weather delivery (the numbers are roughly right); you "
    "may NOT invent scores, tallies, or margins — any hard number you need has "
    "already been read for you on the wire.")


# ------------------------------------------------------------ bus adapter

def _digest(day: str, *, show: str, want=None, now=None) -> dict:
    """Defensive adapter over the frozen `world.digest(day, *, show, want,
    now) -> {"wire":[...], "prompt":str, "guard":{...}}` API.

    Returns a normalized digest, or the empty digest on ANY failure — the bus
    leaf not built yet, `data/world/ENABLED` absent, or a read blowing up. The
    single-writer bus is never touched here; this is pure-read only."""
    try:
        from . import world
    except Exception:
        return dict(_EMPTY)
    try:
        on = getattr(world, "on", None)
        if callable(on) and not on():
            return dict(_EMPTY)
        d = world.digest(day, show=show, want=want, now=now)
    except Exception:
        return dict(_EMPTY)
    if not isinstance(d, dict):
        return dict(_EMPTY)
    wire = [str(w).strip() for w in (d.get("wire") or []) if str(w).strip()]
    return {"wire": wire,
            "prompt": str(d.get("prompt") or "").strip(),
            "guard": dict(d.get("guard") or {})}


# ------------------------------------------------------------ news wire line

def news_world_line(day: str, *, digest_fn=_digest) -> str:
    """Sports-desk pattern: one code-authored wire line for the news bulletin,
    or "" when the bus has nothing (caller skips it exactly like the Sports
    Desk skips an empty `scores_desk`).

    Returns the wire STRING only; the caller wraps it in a produced segment
    (`speaker`/`voice`) — see the `_news_bulletin` patch spec below. The line
    is dropped in verbatim, so its numbers need no guard.

    `digest_fn` is an injection seam for tests; production uses the real bus."""
    d = digest_fn(day, show="news")
    return " ".join(d["wire"])


# ------------------------------------------------------------ morning block

def morning_block(day: str, *, digest_fn=_digest) -> tuple[str, dict]:
    """The morning show's WORLD prompt block, as `(text, allow)`.

    `text` is the SCOREBOARD-register block quoting the bus's qualitative
    facts, or "" when the bus is dark (an absent block ⇒ the prompt is
    unchanged from today). `allow` is the guard payload
    (`{"score_pairs": [...], ...}`) the show merges into its EXISTING
    whitelist — `scoreguard.build_facts(allow_pairs=...)` / `nameguard`'s
    `extra_ok` — so any number the block legitimately carries is code-owned and
    a number the model invents around it is still caught and replaced.

    `digest_fn` is an injection seam for tests; production uses the real bus."""
    d = digest_fn(day, show="morning")
    prompt = d["prompt"]
    if not prompt:
        return "", {}
    return _BLOCK_HEAD + prompt + _BLOCK_TAIL, d["guard"]


# ------------------------------------------------------------ weather coords

def _halfway_coords() -> dict:
    """The one Halfway coord, preferring `world.HALFWAY_LATLON` (canon owner)
    and falling back to the local constant when the bus leaf is mid-build."""
    try:
        from . import world
        c = getattr(world, "HALFWAY_LATLON", None)
        if isinstance(c, dict) and "lat" in c and "lon" in c:
            return {"lat": c["lat"], "lon": c["lon"]}
        if isinstance(c, (tuple, list)) and len(c) == 2:
            return {"lat": c[0], "lon": c[1]}
    except Exception:
        pass
    return dict(HALFWAY_LATLON)


def _real_forecast(coords: dict | None = None) -> str:
    """EXACT-DIFF COPY of `spots._real_forecast`, with ONE change: a `coords`
    parameter (default: the Halfway canon coord) replaces the hard-coded NYC
    latitude/longitude. Real numbers from Open-Meteo (free, keyless) for the
    writer to twist; same missing-feed fallback string, byte-for-byte.

    ================= EXACT DIFF TO APPLY TO src/spots.py =================
    Integration owns this edit; this module does NOT touch spots.py. Apply:

        -def _real_forecast() -> str:
        +def _real_forecast(coords: dict | None = None) -> str:
             \"\"\"Real numbers from Open-Meteo (free, keyless) ...\"\"\"
        +    from .world import HALFWAY_LATLON            # canon Halfway coord
        +    c = coords or HALFWAY_LATLON
             try:
                 r = requests.get(
                     "https://api.open-meteo.com/v1/forecast",
        -            params={"latitude": 40.71, "longitude": -74.01,
        +            params={"latitude": c["lat"], "longitude": c["lon"],
                             "current": ...,  # (rest of params UNCHANGED)

    Every other line of `_real_forecast` — the params dict body, the response
    parsing, the except fallback — stays IDENTICAL. `spots._generate` keeps
    calling `_real_forecast()` with no args (defaulting to Halfway), so the
    weather SPOTS now describe the same storm the spine and the statehouse read.

    ================= WESLEY HOOK PATCH (src/orchestrator.py ~L346) =========
    In `run_show`, the morning-scramble forecast fetch already calls
    `_real_forecast()`; once the spots.py diff above lands it Halfway-targets
    automatically (no orchestrator edit needed for coords). To ALSO give the
    morning show the WORLD block, add beside the existing Wesley fetch:

        from .world_consumers import morning_block
        _wb, _wb_allow = morning_block(f"{clock.air_now():%Y-%m-%d}")
        if _wb:
            daypart["_extra_context"] = (daypart.get("_extra_context", "")
                                         + "\\n\\n" + _wb)
            # merge _wb_allow into the show's scoreguard allow_pairs / nameguard
            # extra_ok wherever it builds guard facts (same seam context_pairs
            # already feeds).

    ================= NEWS DESK PATCH (src/orchestrator.py ~L206) ===========
    In `_news_bulletin`, mirror the Sports Desk / Dome Desk blocks:

        from .world_consumers import news_world_line
        _wl = news_world_line(f"{clock.air_now():%Y-%m-%d}")
        if _wl:
            lines.append({"speaker": "Frequency World", "voice": NEWS_VOICE,
                          "text": "Around Wending. " + _wl})
    ========================================================================
    """
    c = coords or _halfway_coords()
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": c["lat"], "longitude": c["lon"],
                    "current": "temperature_2m,weather_code,wind_speed_10m",
                    "daily": "temperature_2m_max,temperature_2m_min,"
                             "precipitation_probability_max",
                    "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
                    "timezone": "America/New_York", "forecast_days": 2},
            timeout=15)
        r.raise_for_status()
        d = r.json()
        cur, daily = d.get("current", {}), d.get("daily", {})
        return (f"now {cur.get('temperature_2m')}F wind {cur.get('wind_speed_10m')}mph "
                f"code {cur.get('weather_code')}; today high {daily.get('temperature_2m_max', ['?'])[0]}F "
                f"low {daily.get('temperature_2m_min', ['?'])[0]}F "
                f"rain {daily.get('precipitation_probability_max', ['?'])[0]} percent; "
                f"tomorrow high {daily.get('temperature_2m_max', ['?', '?'])[1]}F")
    except Exception:
        return "(no forecast data — improvise gently, no numbers)"
