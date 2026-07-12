"""Election Night's returns CLOCK — the engine core behind Election Night
(`run_election_night` itself is INTEGRATION's; this module is the pure,
seeded clock it drives). Mirrors the town-texture/engines build contract,
Row 4.

The whole cycle's truth already exists the moment `generate_cycle` writes
`election-{cycle}.json` (see `elections.py`): every precinct's final split
is simulated once. This module answers a different question than
`elections.reveal`: given the ACTUAL on-air window the registry booked
(19:00-01:00 in `events/registry.yaml`, six hours of air, not the 3.5h the
raw `WAVES` span assumes), *when across THAT window does each physical
precinct phone in*, and *how much of the already-known truth may a listener
know `cursor` seconds in*.

Design, matching the House rules (stdlib-only leaf; seeded determinism, no
bare `random`/wall-clock; derive-don't-store — the plan is a pure return the
integration layer persists, this module writes no state file):

  * `build_night(el, window_secs, seed)` scales `elections.WAVES` onto the
    booked air window and assigns every PHYSICAL precinct a single drop
    offset in `[0, window_secs)` — wave 1 an early trickle, wave 2 the mid
    flood, wave 3 the late stragglers. Canon overrides survive the scaling:
    `PHLOT-1` (the pharmacy lot) drops first at 0, `HFWC-1` (Halfway's
    central count, the swing dump) drops last. Rainout precincts (weather
    -delayed at generation) never report — offset `None`. Offsets are keyed
    by precinct id ONCE: House/Senate/potholes share the same physical
    precincts and phone in together, exactly as `elections._report_offset`
    seeds on `(cycle, pid)` only, never on the race id.

  * `reveal_at(plan, el, cursor)` returns EXACTLY `elections.reveal`'s shape
    (`{"pct_in", "races": {rid: {tally, wave, status, precincts_out,
    precincts_total}}}`) so it drops straight into `sheets.election_sheet`
    and `civicguard`'s `revealed` slot. It reuses `elections.call_state`
    verbatim for the AP-style call (the monotonic-critical logic), summing
    only precincts whose plan offset has elapsed. Monotonic in `cursor` by
    construction: offsets are fixed in the plan, so raising `cursor` only
    ADDS precincts to a tally, never removes them, and `call_state`'s exact
    remaining-vote bound never regresses a status once set — never a tally
    regressed.

  * `beat_plan(air_minutes)` lays the registry's Election-Night segments
    (open / board / analyst / call-watch / the-call / wrap) onto target
    cursors across the show.

  * `facts_at(plan, el, cursor, tracked_id)` packages the reveal at `cursor`
    into the fact table `civicguard.enforce_civic` walks, so a beat can be
    held to the revealed truth (no calling a race ahead of its reveal).

Invents no fictional proper names (nothing to clear against
`nameguard._WORLD_TOKENS/_WORLD_PHRASES`): beat labels are the registry's
own segment strings; precinct/candidate names come from `el`.
"""
from __future__ import annotations

import random

from src.statehouse import civicguard, elections

# The registry's Election-Night segments (events/registry.yaml, id
# election_night) restated verbatim, mapped to the six beat descriptors this
# clock exposes. The two beats with no dedicated registry segment
# (call-watch, wrap) carry a `segment` of None and a synthesized label.
_SEGMENTS = {
    "open": "The Desk Opens — polls close, the first precincts report",
    "board": "The Board — race by race, the count as it lands, calls when earned",
    "analyst": "The Analysts — a guest reads the map; no call ahead of the reveal",
    "the-call": "The Call — the night's decisive race, named the moment it's safe",
}

# (beat id, fraction of air window for the target cursor, fallback label).
_BEAT_LAYOUT = [
    ("open", 0.00, "The Desk Opens"),
    ("board", 0.15, "The Board"),
    ("analyst", 0.40, "The Analysts"),
    ("call-watch", 0.65, "Call Watch — races tightening toward a call"),
    ("the-call", 0.88, "The Call"),
    ("wrap", 0.99, "Wrap — the night's ledger, what's settled and what waits"),
]


# --------------------------------------------------------------- build_night

def _waves(el: dict) -> dict:
    """`el["waves"]` normalized to `{int wave: (start, end)}`."""
    return {int(k): (int(v[0]), int(v[1])) for k, v in el["waves"].items()}


def _scaled_bands(waves: dict, window_secs: int) -> dict:
    """Scale each raw wave span (`elections.WAVES`, a 12600s frame) onto the
    booked air window -> `{wave: [b0, b1]}`, contiguous and non-empty."""
    span = max(end for _s, end in waves.values()) or 1
    bands = {}
    for wave, (wstart, wend) in sorted(waves.items()):
        b0 = int(round(window_secs * wstart / span))
        b1 = int(round(window_secs * wend / span))
        if b1 <= b0:
            b1 = b0 + 1
        bands[wave] = [b0, b1]
    return bands


def build_night(el: dict, window_secs: int, seed: str) -> dict:
    """Assign every physical precinct a drop offset across the booked window
    (early trickle / mid flood / stragglers). Pure and deterministic in
    `(el's cycle, window_secs, seed)`. `el` is a `generate_cycle` body."""
    if window_secs < 1:
        window_secs = 1
    cycle = el["cycle"]
    waves = _waves(el)
    bands = _scaled_bands(waves, window_secs)

    # unique physical precincts (shared across race tiers) with wave/rainout
    seen: dict = {}
    for race in el["races"].values():
        for p in race["precincts"]:
            pid = p["id"]
            if pid not in seen:
                seen[pid] = {"wave": int(p["wave"]),
                             "rainout": bool(p.get("rainout"))}

    offsets: dict = {}
    for pid, info in seen.items():
        if info["rainout"]:
            offsets[pid] = None            # weather-delayed: never reports tonight
            continue
        b0, b1 = bands[info["wave"]]
        rng = random.Random(f"{seed}:cycle:{cycle}:{pid}:drop")
        offsets[pid] = b0 + rng.randint(0, max(0, b1 - b0 - 1))

    # canon overrides (grounding B.4): pharmacy lot first, Halfway central
    # count last — the late dump that can swing a close race. Only when they
    # actually report (a rained-out canon precinct keeps its None).
    if offsets.get("PHLOT-1") is not None:
        offsets["PHLOT-1"] = 0
    if offsets.get("HFWC-1") is not None:
        offsets["HFWC-1"] = window_secs - 1

    return {"cycle": cycle, "window_secs": window_secs, "seed": seed,
            "bands": {str(k): v for k, v in bands.items()},
            "offsets": offsets}


# ------------------------------------------------------------------ reveal_at

def _current_wave(cursor: int, bands: dict) -> int:
    """Which reporting wave the plan clock is in at `cursor` (highest wave
    whose band has opened)."""
    wave = min(int(k) for k in bands)
    for k, (b0, _b1) in sorted((int(k), v) for k, v in bands.items()):
        if cursor >= b0:
            wave = k
    return wave


def reveal_at(plan: dict, el: dict, cursor: int) -> dict:
    """The revealed dict `sheets.election_sheet` expects, monotonic in
    `cursor`. Sums each race's precincts whose plan drop offset has elapsed;
    reuses `elections.call_state` for the AP-style status (never regresses a
    tally — see module docstring)."""
    offsets = plan["offsets"]
    bands = plan["bands"]
    wave_now = _current_wave(cursor, bands)

    races_out = {}
    total_reported = 0
    total_all = 0
    for rid, race in el["races"].items():
        tally = [0, 0]
        out_count = 0
        for p in race["precincts"]:
            total_all += 1
            off = offsets.get(p["id"])
            if off is None:                      # rainout / unknown: excluded
                continue
            if cursor >= off:
                tally[0] += p["votes"][0]
                tally[1] += p["votes"][1]
                out_count += 1
        total_reported += out_count
        status = elections.call_state(race, tally, out_count)
        races_out[rid] = {"tally": tally, "wave": wave_now, "status": status,
                          "precincts_out": out_count,
                          "precincts_total": len(race["precincts"])}
    pct_in = round(100 * total_reported / total_all) if total_all else 0
    return {"pct_in": pct_in, "races": races_out}


# ------------------------------------------------------------------ beat_plan

def beat_plan(air_minutes: int) -> list:
    """Beat descriptors (open / board / analyst / call-watch / the-call /
    wrap) with target cursors across an `air_minutes`-long show, matching the
    registry's Election-Night segments. Target cursors are non-decreasing."""
    total = max(0, int(air_minutes)) * 60
    out = []
    for beat, frac, label in _BEAT_LAYOUT:
        out.append({"beat": beat,
                    "target_cursor": int(round(frac * total)),
                    "segment": _SEGMENTS.get(beat),
                    "label": _SEGMENTS.get(beat, label)})
    return out


# ------------------------------------------------------------------- facts_at

def facts_at(plan: dict, el: dict, cursor: int, tracked_id) -> dict:
    """The fact table `civicguard.enforce_civic` walks to hold an
    Election-Night beat to the revealed truth at `cursor`. Bundles the
    reveal (candidate names, per-race revealed tallies/status, pct-in) into
    `civicguard.build_civic_facts`'s `election` slot so a performer can't
    call a race ahead of its reveal or invent a margin. Integration may
    enrich the returned dict with civ/dk/member facts; on its own it grounds
    everything the election truth needs."""
    revealed = reveal_at(plan, el, cursor)
    state = {"election": el}
    sheet = {"mode": "election_sheet", "revealed": revealed,
             "tracked_id": tracked_id}
    return civicguard.build_civic_facts(state, sheet)
