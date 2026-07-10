"""Statehouse election engine — mirror §6 / final.md §"Election engine" bullet
(deltas 2, 4, 5 don't touch this module). Stdlib-only leaf module: pure
functions against §2's `election-{cycle}.json` shape, no import of
season.py/orchestrator.py/league modules, no import of any other
`src/statehouse/*` module (none exist yet — this is the first component
landed; `members.py`/`civics.py` will call in, not the reverse).

**Shared-clock reveal (mirrors `league/briefs.reveal`).** The whole cycle
(every precinct's true, final vote split) is fully simulated once at
`generate_cycle` time — the outcome exists in full the moment the file is
written. `reveal(el, cursor)` is the ONLY function that decides how much of
that already-known truth a listener could plausibly know `cursor` seconds
into the broadcast (seconds since `broadcast_anchor`); booth, news desk, and
the website all call it at the same cursor and therefore never disagree.

**171 precincts, pharmacy lot first, Halfway dumps late (mirror §6).** Every
House district (H-01..H-51) gets 3-4 physical precincts summing to exactly
171 statewide; Senate districts (S-01..S-09) and the statewide `potholes`
race reuse those same physical precincts (a voter marks all three contests
on one ballot at one precinct — no separate Senate/Commissioner precinct
map). District H-01 (Halfway, the capital) always contains two named
canon precincts: `PHLOT-1` (the pharmacy lot — small, wave 1, always
first to report) and `HFWC-1` (Halfway's own central count — the biggest
precinct in the state, wave 3, always last, and the one late "dump" that
can swing a close race, per grounding B.4). All other precincts get a
seeded wave (rural-fast/suburban-mid/urban-slow, 55/30/15) and a per-wave
report-time jitter, both derived purely from `(cycle, race_id, precinct_id)`
— nothing about report timing is stored; `reveal` re-derives it every call.

**Call logic (AP-style, grounding B.6).** `call_state` uses the EXACT
remaining-vote bound, not an estimate: the total votes a race's non-rainout
precincts will ever cast is a fixed constant known the moment the cycle is
generated (`reportable_total`), so `remaining = reportable_total -
(a + b)` is exact regardless of which precincts happen to have reported so
far. A race is only "called" once `abs(a - b) > remaining` — the trailing
candidate mathematically cannot catch up even if every uncounted vote broke
their way. This is what makes `reveal` provably monotonic: once that
inequality holds, it keeps holding as any further (truthful) precinct
reports, because reporting a precinct can only move `abs(a-b)` and
`remaining` in lockstep-safe directions (see the reveal docstring for the
one-line algebra). Races flagged `recount` at generation never reach
"called" at all — they sit at "leaning" until every reportable precinct is
in, then flip straight to "recount", satisfying "never call inside the
recount margin" by construction rather than by a runtime guard.

**Recount = re-narration, not re-simulation.** The margin-qualifying flip
(~1/10, grounding B.8's "rarely flips" read the other way round) is decided
ONCE at generation time by nudging `HFWC-1` (or the race's own biggest
wave-3 precinct, for districts that don't contain the capital) — the same
late central-count dump that plausibly would flip a true race, per B.4/B.5.
`race["recount_flip"]` is stored so `recount_script` only narrates the
already-decided fact; it never redraws.

**Friction notes (design frozen, conforming as written):**
  - The task names this file `elections.py`; mirror §3 names the module
    `election.py` (singular). Following the task's explicit deliverable
    path — flagged, not resolved unilaterally.
  - §3's `election.py` block lists `generate_cycle(cycle, members, ga)`
    but no other statehouse module exists yet to produce a real minted
    `members` sidecar. `_mlook` accepts the real `{"members": {...}}`
    sidecar shape, a bare `{mid: {...}}` map (stats.py/briefs.py's
    `_lookup`/`_plook` convention), or `None` — in the last case a small
    local placeholder name pool stands in so this module is fully
    testable standalone; production wiring (once `members.py` lands)
    passes the real sidecar and every incumbent/party comes from there.
  - `goose_price()`/floor-vote mechanics are `members.py`/`floor.py`'s
    business (delta 4), not this module's; the Goose party appears here
    only as an ordinary House-seat-holding candidate party (per the
    seat table, House only, never Senate), with no special electoral
    behavior beyond that.
"""
from __future__ import annotations

import random

# --------------------------------------------------------------------- canon

HOUSE_SEATS = 51
SENATE_SEATS = 9
PRECINCTS_TOTAL = 171
TURNOUT_RANGE = (0.35, 0.50)
WAVES = {1: (0, 2700), 2: (2700, 7200), 3: (7200, 12600)}
RECOUNT_MARGIN_PCT = 0.5
RECOUNT_MARGIN_VOTES = 12
RECOUNT_FLIP_P = 0.10
RAINOUT_RANGE = (0, 2)
CYCLE_YEARS = 2
FIRST_TAKEOVER = "2026-11-03"

HOUSE_PARTIES = ("prov", "round", "vang", "barb", "grudge", "goose")
SENATE_PARTIES = ("prov", "round", "vang", "barb", "grudge")

STATUS_TOO_EARLY = "too-early"
STATUS_LEANING = "leaning"
STATUS_CALLED = "called"
STATUS_RECOUNT = "recount"
_STATUS_RANK = {STATUS_TOO_EARLY: 0, STATUS_LEANING: 1,
                STATUS_CALLED: 2, STATUS_RECOUNT: 2}

# Standalone placeholder name pool — used only when `members` doesn't supply
# a real name for a seat (see module docstring friction note). Small and
# deliberately not the shared livegame bank (no cross-module import allowed).
_FIRST = ("Doreen", "Earl", "Lucille", "Mervin", "Ida", "Gaston", "Fern",
          "Roy", "Yvette", "Norm", "Colette", "Wendell")
_LAST = ("Vachon", "Thibodeau", "Marchand", "Ostberg", "Demers", "Pelletier",
         "Kranz", "Bouchard", "Fournier", "Racine", "Doiron", "Whelan")


def _name(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"


def _mlook(members) -> dict:
    """Normalize a members sidecar (mirrors briefs._plook/stats._lookup):
    accepts the real `{"members": {mid: {...}}}` sidecar, a bare
    `{mid: {...}}` map, or None/empty."""
    if isinstance(members, dict) and isinstance(members.get("members"), dict):
        return members["members"]
    return members or {}


# ------------------------------------------------------------- district ids

def house_ids() -> list:
    return [f"H-{i:02d}" for i in range(1, HOUSE_SEATS + 1)]


def senate_ids() -> list:
    return [f"S-{i:02d}" for i in range(1, SENATE_SEATS + 1)]


def _senate_groups() -> dict:
    """9 Senate districts partition the 51 House districts contiguously
    (divmod(51, 9) = 5 remainder 6 -> six groups of 6, three of 5)."""
    hids = house_ids()
    sizes = [6] * 6 + [5] * 3
    groups, i = {}, 0
    for sid, size in zip(senate_ids(), sizes):
        groups[sid] = hids[i:i + size]
        i += size
    return groups


# --------------------------------------------------------- precinct geometry

def _pid(district_id: str, n: int) -> str:
    return f"{district_id.replace('-', '')}-{n}"


def _house_precinct_counts(cycle: int) -> dict:
    """Deterministic 51-way split of 171 precincts: base 3 each (153),
    remaining 18 go +1 to 18 seeded-chosen districts. Every district gets
    >= 3, so H-01 always has room for its two named canon precincts."""
    hids = house_ids()
    counts = {hid: 3 for hid in hids}
    rng = random.Random(f"cycle:{cycle}:precinct-counts")
    extra = rng.sample(hids, PRECINCTS_TOTAL - 3 * len(hids))
    for hid in extra:
        counts[hid] += 1
    return counts


def _build_precincts(cycle: int) -> dict:
    """-> {house_district_id: [ {id, wave, electors}, ... ]}. Pure function
    of cycle only (the physical precinct map, shared by every race tier)."""
    counts = _house_precinct_counts(cycle)
    out = {}
    for hid, n in counts.items():
        rng = random.Random(f"cycle:{cycle}:{hid}:precincts")
        precincts = []
        start = 1
        if hid == "H-01":
            precincts.append({"id": "PHLOT-1", "wave": 1,
                               "electors": rng.randint(300, 700)})
            precincts.append({"id": "HFWC-1", "wave": 3,
                               "electors": rng.randint(3500, 6000)})
            start = 3
        for k in range(start, n + 1):
            wave = rng.choices([1, 2, 3], weights=[55, 30, 15])[0]
            electors = (rng.randint(3500, 6000) if wave == 3
                        else rng.randint(800, 3200))
            precincts.append({"id": _pid(hid, k), "wave": wave,
                               "electors": electors})
        out[hid] = precincts
    return out


# -------------------------------------------------------------- generation

def _party_pool(rid: str) -> tuple:
    return HOUSE_PARTIES if rid.startswith("H") else SENATE_PARTIES


def _pick_candidates(rid: str, cycle: int, mlook: dict) -> list:
    rng = random.Random(f"cycle:{cycle}:{rid}:cands")
    incumbent = mlook.get(rid)
    if incumbent:
        inc_name = incumbent.get("name") or _name(rng)
        inc_party = incumbent.get("party") or rng.choice(_party_pool(rid))
    else:
        inc_name, inc_party = _name(rng), rng.choice(_party_pool(rid))
    pool = [p for p in _party_pool(rid) if p != inc_party] or [inc_party]
    chal_party = rng.choice(pool)
    chal_name = _name(rng)
    while chal_name == inc_name:
        chal_name = _name(rng)
    return [{"name": inc_name, "party": inc_party, "inc": True},
            {"name": chal_name, "party": chal_party}]


def _potholes_candidates(cycle: int, mlook: dict) -> list:
    rng = random.Random(f"cycle:{cycle}:potholes:cands")
    official = mlook.get("potholes") if isinstance(mlook, dict) else None
    inc_name = (official or {}).get("name") or "Bert Demers"
    chal_name = _name(rng)
    while chal_name == inc_name:
        chal_name = _name(rng)
    return [{"name": inc_name, "party": None, "inc": True},
            {"name": chal_name, "party": None}]


def _hidden_lean(rid: str, cycle: int, has_incumbent: bool) -> float:
    """Hidden hidden-per-cycle lean (pct favoring the incumbent slot),
    never exported/narrated directly — only the resulting tallies are."""
    rng = random.Random(f"cycle:{cycle}:{rid}:lean")
    incumbency_bonus = 5.0 if has_incumbent else 0.0
    swing = rng.uniform(-6, 6)
    noise = rng.uniform(-14, 14)
    return max(6.0, min(94.0, 50.0 + incumbency_bonus + swing + noise))


def _mirage_pts(cycle: int) -> float:
    return random.Random(f"cycle:{cycle}:mirage").uniform(1.0, 4.0)


def _precinct_share(rid: str, cycle: int, pid: str, wave: int,
                     lean: float, mirage: float) -> float:
    rng = random.Random(f"cycle:{cycle}:{rid}:{pid}:share")
    share = lean + rng.gauss(0, 6)
    if wave == 3:
        share -= mirage * (2 if pid.startswith("HFWC") else 1)
    return max(2.0, min(98.0, share))


def _turnout(cycle: int) -> float:
    return random.Random(f"cycle:{cycle}:turnout").uniform(*TURNOUT_RANGE)


def _race_precincts(house_ids_for_race: list, phys: dict) -> list:
    out = []
    for hid in house_ids_for_race:
        out.extend(phys[hid])
    return out


def _precinct_total_votes(cycle: int, pid: str, electors: int, turnout: float) -> int:
    """Total ballots cast at one physical precinct — a function of the
    precinct alone, shared by every race tier on that ballot (House,
    Senate, potholes all count the SAME turnout; only the candidate
    split differs per race, computed separately in `_fill_votes`)."""
    jrng = random.Random(f"cycle:{cycle}:{pid}:turnout")
    t = max(0.20, min(0.65, turnout + jrng.uniform(-0.03, 0.03)))
    return round(electors * t)


def _fill_votes(rid: str, cycle: int, precincts: list, turnout: float,
                 has_incumbent: bool) -> list:
    """-> new precinct dicts (id, wave, votes:[a,b]) for one race."""
    lean = _hidden_lean(rid, cycle, has_incumbent)
    mirage = _mirage_pts(cycle)
    out = []
    for p in precincts:
        pid, wave, electors = p["id"], p["wave"], p["electors"]
        share = _precinct_share(rid, cycle, pid, wave, lean, mirage)
        votes = _precinct_total_votes(cycle, pid, electors, turnout)
        a = round(votes * share / 100.0)
        b = votes - a
        out.append({"id": pid, "wave": wave, "votes": [a, b]})
    return out


def _apply_recount_flip(rid: str, cycle: int, precincts: list) -> bool:
    """Nudges the race's biggest wave-3 precinct so the final tally flips
    sign, keeping the margin inside the recount band. Returns whether a
    flip was actually applied (False if there's no usable precinct, an
    edge case that just leaves the natural — already-tiny — margin as is)."""
    wave3 = [p for p in precincts if p["wave"] == 3]
    pool = wave3 or precincts
    if not pool:
        return False
    dump = max(pool, key=lambda p: p["votes"][0] + p["votes"][1])
    total_a = sum(p["votes"][0] for p in precincts)
    total_b = sum(p["votes"][1] for p in precincts)
    diff = total_a - total_b
    if diff == 0:
        return False
    rng = random.Random(f"cycle:{cycle}:{rid}:flipmag")
    target = rng.randint(2, 10)
    dump_diff = dump["votes"][0] - dump["votes"][1]
    other_diff = diff - dump_diff
    desired_total_diff = -1 if diff > 0 else 1
    desired_total_diff *= target
    new_dump_diff = desired_total_diff - other_diff
    total_votes = dump["votes"][0] + dump["votes"][1]
    new_a = round((total_votes + new_dump_diff) / 2)
    new_a = max(0, min(total_votes, new_a))
    dump["votes"][0] = new_a
    dump["votes"][1] = total_votes - new_a
    return True


def generate_cycle(cycle: int, members, ga: int) -> dict:
    """`election-{cycle}.json` body (mirror §2). Deterministic in `cycle`
    alone (plus whatever real names/parties `members` supplies) — calling
    twice with the same arguments is byte-identical."""
    mlook = _mlook(members)
    turnout = _turnout(cycle)
    phys = _build_precincts(cycle)
    groups = _senate_groups()

    races = {}
    for hid in house_ids():
        cands = _pick_candidates(hid, cycle, mlook)
        precincts = _fill_votes(hid, cycle, phys[hid], turnout, True)
        races[hid] = {"cands": cands, "precincts": precincts}
    for sid, hids in groups.items():
        cands = _pick_candidates(sid, cycle, mlook)
        precincts = _fill_votes(sid, cycle, _race_precincts(hids, phys),
                                 turnout, True)
        races[sid] = {"cands": cands, "precincts": precincts}
    cands = _potholes_candidates(cycle, mlook)
    precincts = _fill_votes("potholes", cycle, _race_precincts(house_ids(), phys),
                             turnout, True)
    races["potholes"] = {"cands": cands, "precincts": precincts}

    # rainouts: 0-2 physical precincts statewide, weather-delayed (never
    # report tonight); chosen once from the full physical pool, then
    # applied everywhere that precinct id appears (house/senate/potholes
    # all share the same physical precincts).
    all_pids = [p["id"] for plist in phys.values() for p in plist]
    rrng = random.Random(f"cycle:{cycle}:rainout")
    n_rain = rrng.randint(*RAINOUT_RANGE)
    rainouts = set(rrng.sample(all_pids, min(n_rain, len(all_pids))))

    for rid, race in races.items():
        for p in race["precincts"]:
            if p["id"] in rainouts:
                p["rainout"] = True
                p["provisional"] = random.Random(
                    f"cycle:{cycle}:{p['id']}:provisional").randint(5, 60)

        reportable = [p for p in race["precincts"] if not p.get("rainout")]
        total_a = sum(p["votes"][0] for p in reportable)
        total_b = sum(p["votes"][1] for p in reportable)
        margin_votes = abs(total_a - total_b)
        margin_pct = (100.0 * margin_votes / (total_a + total_b)
                      if (total_a + total_b) else 0.0)
        recount = (margin_pct <= RECOUNT_MARGIN_PCT
                   or margin_votes <= RECOUNT_MARGIN_VOTES)
        if recount:
            flip_rng = random.Random(f"cycle:{cycle}:{rid}:flip")
            flip = flip_rng.random() < RECOUNT_FLIP_P
            if flip:
                _apply_recount_flip(rid, cycle, reportable)
            race["recount_flip"] = flip
            total_a = sum(p["votes"][0] for p in reportable)
            total_b = sum(p["votes"][1] for p in reportable)
            margin_votes = abs(total_a - total_b)
            margin_pct = (100.0 * margin_votes / (total_a + total_b)
                          if (total_a + total_b) else 0.0)
        race["final"] = [total_a, total_b]
        race["margin_pct"] = round(margin_pct, 2)
        race["recount"] = recount

    return {"schema": 1, "cycle": cycle, "turnout": round(turnout, 3),
            "precincts": PRECINCTS_TOTAL, "races": races,
            "waves": {str(k): list(v) for k, v in WAVES.items()},
            "broadcast_anchor": None}


# ------------------------------------------------------------------- reveal

def call_state(race: dict, revealed_tally, precincts_out: int) -> str:
    """AP-style call: exact remaining-vote bound (see module docstring).
    Never returns CALLED for a `recount`-flagged race — it only ever
    reaches TOO_EARLY -> LEANING -> RECOUNT, satisfying "never call inside
    the recount margin" by construction."""
    reportable = [p for p in race["precincts"] if not p.get("rainout")]
    total_precincts = len(reportable)
    reportable_total = sum(p["votes"][0] + p["votes"][1] for p in reportable)
    a, b = revealed_tally
    reported_total = a + b
    remaining = max(reportable_total - reported_total, 0)

    if race.get("recount"):
        if precincts_out >= total_precincts and total_precincts > 0:
            return STATUS_RECOUNT
        return STATUS_LEANING if precincts_out > 0 else STATUS_TOO_EARLY

    if precincts_out == 0:
        return STATUS_TOO_EARLY
    if precincts_out >= total_precincts:
        return STATUS_CALLED
    if abs(a - b) > remaining:
        return STATUS_CALLED
    return STATUS_LEANING


def _report_offset(cycle: int, pid: str, wstart: int, wend: int) -> int:
    """When physical precinct `pid` phones in — shared by every race tier
    on that ballot (House/Senate/potholes report together), so this is
    seeded on `(cycle, pid)` only, never on the race id."""
    return wstart + random.Random(
        f"cycle:{cycle}:{pid}:when").randint(0, max(0, wend - wstart))


def _current_wave(cursor: int, waves: dict) -> int:
    ordered = sorted((int(k), v) for k, v in waves.items())
    wave = ordered[0][0]
    for k, (wstart, _wend) in ordered:
        if cursor >= wstart:
            wave = k
    return wave


def reveal(el: dict, cursor: int) -> dict:
    """THE ONLY renderer of election returns (mirror of `briefs.reveal`).
    `cursor` = seconds since `broadcast_anchor`. Monotonic in `cursor`: for
    a fixed `el`, each precinct's report time is a pure function of
    `(cycle, race_id, precinct_id)` (never stored, always re-derived), so
    raising `cursor` can only add precincts to a race's tally, never
    remove them — `precincts_out` and each race's `tally` are therefore
    non-decreasing. `status` cannot regress either: `call_state` uses the
    EXACT remaining-vote bound (`reportable_total - reported_total`, a
    fixed constant per race), so once `abs(a-b) > remaining` holds it
    keeps holding — reporting one more truthful precinct with `x_lead`
    votes to the leader and `x_trail` to the trailing candidate changes
    `margin - remaining` by `+2*x_lead >= 0`, so a positive gap never goes
    negative again. Recount races never leave the too-early/leaning/
    recount lane, so they can't un-call a "called" status they never had.
    """
    cycle = el["cycle"]
    races_out = {}
    total_reported_precincts = 0
    total_precincts_all = 0
    for rid, race in el["races"].items():
        tally = [0, 0]
        out_count = 0
        for p in race["precincts"]:
            total_precincts_all += 1
            if p.get("rainout"):
                continue
            wstart, wend = el["waves"][str(p["wave"])]
            report_at = _report_offset(cycle, p["id"], wstart, wend)
            if cursor >= report_at:
                tally[0] += p["votes"][0]
                tally[1] += p["votes"][1]
                out_count += 1
        total_reported_precincts += out_count
        status = call_state(race, tally, out_count)
        races_out[rid] = {"tally": tally, "wave": _current_wave(cursor, el["waves"]),
                           "status": status, "precincts_out": out_count,
                           "precincts_total": len(race["precincts"])}
    pct_in = (round(100 * total_reported_precincts / total_precincts_all)
              if total_precincts_all else 0)
    return {"pct_in": pct_in, "races": races_out}


def recount_script(race: dict, cycle: int) -> list:
    """OVERTIME: the same (already-decided) result re-narrated slower, with
    ceremony. Reads `race["recount_flip"]` — set once at `generate_cycle`
    time — rather than redrawing, so narration always matches the stored
    truth."""
    if not race.get("recount"):
        return []
    a, b = race["final"]
    winner = race["cands"][0 if a >= b else 1]
    flip = bool(race.get("recount_flip"))
    steps = [
        {"beat": "recount_open",
         "text": "Inside the automatic-recount threshold — the Clerk "
                 "counts the last dozen personally."},
        {"beat": "recount_tally",
         "text": "Ballots re-run, box by box, under observer eyes."},
    ]
    if flip:
        steps.append({"beat": "recount_result", "flip": True,
                       "text": f"The recount flips it: {winner['name']} "
                               "holds the seat."})
    else:
        steps.append({"beat": "recount_result", "flip": False,
                       "text": f"The recount confirms it: {winner['name']} "
                               "holds the seat."})
    return steps


def seat_new_assembly(el: dict, members) -> dict:
    """-> carryover map `{race_id: {"name","party","incumbent","chamber"}}`
    for the next Assembly's `mint_assembly` to consume (re-elected members
    keep their identity; challengers who won seat fresh). Excludes the
    non-legislative `potholes` race."""
    out = {}
    for rid, race in el["races"].items():
        if rid == "potholes":
            continue
        a, b = race["final"]
        winner = race["cands"][0 if a >= b else 1]
        out[rid] = {"name": winner["name"], "party": winner["party"],
                     "incumbent": bool(winner.get("inc")),
                     "chamber": "house" if rid.startswith("H") else "senate"}
    return out
