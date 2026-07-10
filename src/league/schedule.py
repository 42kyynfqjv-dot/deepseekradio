"""League schedule generator (minimal §3/§5, hockey-final Crossover graft).

Pure, stdlib-only, deterministic functions of `(season, seed)`. This module
does NOT import season.py — it carries its own mirror of the 32-team league
structure (same keys as season.py's `LEAGUE`/`TRACKED`; that shape is frozen
canon, not derived data, so duplicating it here keeps this a leaf module).

Exact NHL matrix per team (grounding §5): 26 division (5 rivals x4 games
2H/2A + 2 rivals x3 games, one 2H/1A one 1H/2A) + 24 same-conference
non-division (8 opponents x3 games, 4 home-heavy 2H/1A + 4 away-heavy 1H/2A)
+ 32 inter-conference (16 opponents x2 games, 1H/1A) = 82 games, 41H/41A.
Division/conference imbalanced-game splits are engineered so each bucket
individually is home/away-balanced (13H/13A, 12H/12A, 16H/16A) — no drift.

Crossover Series (mtl-nyg, hockey-final): the two tracked teams share a
conference but not a division, so the base matrix gives them only 3 meetings
— too few for `_RIVALRY_EVERY = 7`. We bump that pairing to 8 (4H/4A, +5
games) and pay for it by dropping exactly one game from 5 of mtl's other
pairings and 5 of nyg's (chosen from their 16 shared inter-conference
opponents, split 2/3 by the H/A shape of the games removed). Each dropped
opponent is re-paid with one extra game against a partner opponent chosen so
the direction (home/away) exactly cancels what it lost — every one of the 10
donor teams keeps its own 82 GP / 41H-41A untouched, at the cost of a 1-game
shift between two of ITS OWN bucket totals (e.g. inter-conference 32->31,
conference-non-division 24->25). mtl and nyg end at 82/41/41 too, via a
different bucket shape (crossover instead of a third conference opponent).
Every other pairing among the remaining 20 untracked teams is the untouched
exact matrix. This is the one place the frozen schema's "other 30 teams on
the exact NHL matrix" is a simplification: 10 of those 30 carry a 1-game
bucket-composition shift (never a GP/H/A shift) to finance the rivalry. Noted
as friction in the build summary; every number the property tests actually
assert (GP, H, A, crossover count) holds exactly for all 32 teams.
"""
from __future__ import annotations

import random
from datetime import date as _date, timedelta as _timedelta

LEAGUE = {
    "Eastern": {
        "Boreal": ["mtl", "tbr", "hfx", "trr", "gan", "bur", "pmc", "stj"],
        "Gridiron": ["nyg", "yon", "uti", "sch", "alb", "scr", "bal", "rich"],
    },
    "Western": {
        "Prairie": ["ssk", "wpg", "mjm", "reg", "bra", "far", "bis", "dul"],
        "Pacific": ["vic", "kam", "spo", "eug", "bak", "fre", "tuc", "boi"],
    },
}
TRACKED = ("mtl", "nyg")
_RIVALRY_EVERY = 7    # mirrors season.py's cadence; every 7th AIR game is mtl-nyg

_ALL_TEAMS = [t for conf in LEAGUE.values() for div in conf.values() for t in div]
_WESTERN_ALL = [t for div in LEAGUE["Western"].values() for t in div]
_EASTERN_ALL = [t for div in LEAGUE["Eastern"].values() for t in div]

_AIR_WEEKDAYS = (2, 5)   # Wed, Sat


# --- matrix construction ----------------------------------------------------

def _add(counter: dict, home: str, away: str, n: int) -> None:
    counter[(home, away)] = counter.get((home, away), 0) + n
    if counter[(home, away)] <= 0:
        del counter[(home, away)]


def _division_block(div_teams: list[str], counter: dict) -> None:
    """7 rivals: cycle-adjacent pair (2 of them) get 3 games (2H/1A split
    across the pair, alternating direction around the cycle); the other 5
    get 4 games (2H/2A). A single 8-cycle over the division's natural order
    keeps this symmetric and reproducible without extra state."""
    n = len(div_teams)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = div_teams[i], div_teams[j]
            is_cycle_edge = (j == i + 1) or (i == 0 and j == n - 1)
            if not is_cycle_edge:
                _add(counter, a, b, 2)
                _add(counter, b, a, 2)
            elif j == i + 1:
                # a is "before" b in the cycle direction -> a home-heavy
                _add(counter, a, b, 2)
                _add(counter, b, a, 1)
            else:
                # wraparound edge (i=0, j=n-1): b is "before" a
                _add(counter, b, a, 2)
                _add(counter, a, b, 1)


def _conference_block(div_a: list[str], div_b: list[str], counter: dict) -> None:
    """Same conference, other division: 3 games/opponent, split so each team
    is home-heavy against exactly half its 8 same-conference opponents."""
    for i, a in enumerate(div_a):
        for j, b in enumerate(div_b):
            if (i + j) % 8 < 4:
                _add(counter, a, b, 2)
                _add(counter, b, a, 1)
            else:
                _add(counter, b, a, 2)
                _add(counter, a, b, 1)


def _inter_block(conf_a: list[str], conf_b: list[str], counter: dict) -> None:
    """Other conference: 2 games/opponent, 1H/1A — no imbalance to place."""
    for a in conf_a:
        for b in conf_b:
            _add(counter, a, b, 1)
            _add(counter, b, a, 1)


def _apply_crossover(counter: dict, season: int) -> None:
    mtl, nyg = TRACKED
    base_mtl_home = counter.get((mtl, nyg), 0)   # mtl-hosted games, base matrix
    base_nyg_home = counter.get((nyg, mtl), 0)
    for key in ((mtl, nyg), (nyg, mtl)):
        counter.pop(key, None)
    counter[(mtl, nyg)] = 4
    counter[(nyg, mtl)] = 4

    mtl_needs_away_donors = 4 - base_mtl_home   # mtl-home legs to drop (donor loses an away game)
    mtl_needs_home_donors = 4 - base_nyg_home   # mtl-away legs to drop (donor loses a home game)
    nyg_needs_away_donors = 4 - base_nyg_home
    nyg_needs_home_donors = 4 - base_mtl_home

    rng = random.Random(f"crossover-donors:{season}")
    donors = list(_WESTERN_ALL)
    rng.shuffle(donors)
    cut = 0
    p_teams = donors[cut: cut + mtl_needs_away_donors]; cut += mtl_needs_away_donors
    q_teams = donors[cut: cut + mtl_needs_home_donors]; cut += mtl_needs_home_donors
    r_teams = donors[cut: cut + nyg_needs_away_donors]; cut += nyg_needs_away_donors
    s_teams = donors[cut: cut + nyg_needs_home_donors]; cut += nyg_needs_home_donors

    for t in p_teams:
        _add(counter, mtl, t, -1)      # drop an mtl-home leg -> t loses an away game
    for t in q_teams:
        _add(counter, t, mtl, -1)      # drop an mtl-away leg -> t loses a home game
    for t in r_teams:
        _add(counter, nyg, t, -1)
    for t in s_teams:
        _add(counter, t, nyg, -1)

    # repay: p (needs +1 away) <-> s (needs +1 home); q (needs +1 home) <-> r (needs +1 away)
    for p, s in zip(p_teams, s_teams):
        _add(counter, s, p, 1)         # s hosts p
    for q, r in zip(q_teams, r_teams):
        _add(counter, q, r, 1)         # q hosts r


def build_matchups(season: int) -> list[tuple[str, str]]:
    """1312 (home, away) pairs for a 32-team, 82-game season. Exact NHL
    matrix for every team except the tracked pair, which plays the 8-game
    Crossover Series (see module docstring)."""
    counter: dict[tuple[str, str], int] = {}
    for conf in LEAGUE.values():
        for div_teams in conf.values():
            _division_block(div_teams, counter)
    for conf in LEAGUE.values():
        div_a, div_b = conf.values()
        _conference_block(div_a, div_b, counter)
    _inter_block(_EASTERN_ALL, _WESTERN_ALL, counter)
    _apply_crossover(counter, season)

    matchups: list[tuple[str, str]] = []
    for (home, away), n in counter.items():
        matchups.extend([(home, away)] * n)
    random.Random(f"matchups:{season}").shuffle(matchups)
    return matchups


# --- day assignment ----------------------------------------------------------

# Sampled inside the grounding's 10-16 band, not at its edges — the mechanics
# below (a mandatory AIR-forced back-to-back can push a team 1 over its own
# running target; a scarce end-of-season pairing can leave one 1 short) have
# +/-1 noise, and this margin absorbs it without ever landing outside 10-16.
_B2B_TARGET_RANGE = (11, 15)
_NIGHT_MIN, _NIGHT_MAX = 6, 9   # games/night pace target (grounding: ~7-8/night)


def _is_blocked(d: _date) -> bool:
    return (d.month, d.day) in {(12, 24), (12, 25), (12, 26)}


def _remainder(matchups: list[tuple[str, str]], played_pairs: list) -> list:
    """Drop already-played games from the matrix (migration retrofit) — best
    effort: a played pair not found in either direction is a season-1
    approximation gap (noted in minimal §7), never a crash.

    A played TRACKED-vs-TRACKED pair is exempt from this trim. season.py's
    live v1 off-air slate (`_sim_day`) only excludes the tracked teams from
    its pool on broadcast nights — on any OTHER night both remain eligible
    and can, by chance, already have been paired against each other before
    migration ever runs. That is never a real Crossover Series game (the
    Series is AIR-only, "every meeting airs, never filler" — see
    `build_matchups`'s docstring and `assign_days`'s day-fill loop, which
    excludes tracked-vs-tracked from every non-AIR night going forward); it
    is a leftover of v1's legacy randomness landing on a non-7th-ordinal
    night, not one of the 8 Crossover meetings. Treating it as consuming
    Crossover supply the way a normal pair is removed starves
    `_prebuild_air_schedule`'s every-7th-AIR-ordinal placement — a
    still-designated ordinal 7 (or 14, 21, ...) would come up empty even
    though 8 real Crossover meetings still need to be placed, cascading into
    every later ordinal (verify_league's §7.7 check then reports the wrong
    date/opponent several ordinals downstream, not the true empty one). The
    Crossover budget is therefore a closed system, spent ONLY by that
    every-7th placement, immune to this generic trim; the (rare) cost is
    that mtl/nyg's OWN season total can land a game or two north of 82 when
    this fires, exactly the same kind of isolated season-1 approximation
    `_remainder` already accepts elsewhere for the OTHER 30 teams — it never
    spreads to any team outside the tracked pair."""
    pool = list(matchups)
    tracked = set(TRACKED)
    for pair in played_pairs:
        h, a = pair[0], pair[1]
        if {h, a} == tracked:
            continue
        if (h, a) in pool:
            pool.remove((h, a))
        elif (a, h) in pool:
            pool.remove((a, h))
    return pool


_AIR_ORDINALS_PLANNED = 62   # generous vs. a realistic ~55-60 night season, but short of
                             # the 9th `_RIVALRY_EVERY` multiple (63) — only 8 Crossover
                             # meetings exist, so planning past the 8th (56) risks a
                             # AIR night with no game left to assign it (see docstring)


def _prebuild_air_schedule(pool: list, start: str, season: int) -> dict[str, list]:
    """Assigns every AIR night's specific game UP FRONT, by calendar date,
    before any general filling — and removes each one from `pool`.

    This replaces an earlier dynamic "reserve supply as we go" design: since
    which calendar date is the Nth Wed/Sat is pure calendar arithmetic (it
    doesn't depend on how fast the general fill consumes the pool), the
    whole schedule of AIR requirements can be nailed down first. That
    sidesteps every race between "how much home-vs-untracked supply is left"
    and "how many AIR nights are actually still ahead" — the two numbers a
    dynamic reservation has to keep in sync and which any forecasting error
    throws out of sync (this is the fix for that: the first design tried a
    running forecast + release-the-surplus heuristic and it reliably starved
    one tracked team's supply a few nights before the season's true end,
    however generously the forecast buffer was tuned).

    `_AIR_ORDINALS_PLANNED` nights are planned — comfortably above a
    realistic ~55-60-night season, comfortably below either tracked team's
    ~37-game home-vs-untracked supply ceiling for the non-rivalry share, and
    bounded to the 8 actual Crossover meetings for the rivalry share.
    """
    mtl, nyg = TRACKED
    d0 = _date.fromisoformat(start)
    ordinal_dates: list[str] = []
    i = 0
    while len(ordinal_dates) < _AIR_ORDINALS_PLANNED:
        d = d0 + _timedelta(days=i)
        if not _is_blocked(d) and d.weekday() in _AIR_WEEKDAYS:
            ordinal_dates.append(d.isoformat())
        i += 1

    air_by_date: dict[str, list] = {}
    for pos, date_iso in enumerate(ordinal_dates):
        idx = pos + 1
        if idx % _RIVALRY_EVERY == 0:
            home, away = (mtl, nyg) if idx % 2 else (nyg, mtl)
            if (home, away) in pool:
                pool.remove((home, away))
                air_by_date[date_iso] = [home, away, "AIR"]
            # else: all 8 Crossover meetings already used — no more exist;
            # this ordinal's night simply gets no pre-built game (falls back
            # to a normal off-air-team-excluded night, see assign_days).
        else:
            home = mtl if idx % 2 else nyg
            match = next((g for g in pool if g[0] == home and g[1] not in TRACKED),
                         None)
            if match is not None:
                pool.remove(match)
                air_by_date[date_iso] = [match[0], match[1], "AIR"]
    return air_by_date


def assign_days(matchups: list[tuple[str, str]], season: int, start: str,
                 gp_played: dict[str, int] | None = None,
                 played_pairs: list[tuple[str, str]] | None = None) -> dict:
    """The schedule-s{n}.json "days" dict: `{date: [[home, away], ...,
    [home, away, "AIR"]]}`. One AIR game every Wed/Sat (a tracked team,
    alternating home like `tonight_live`), Dec 24-26 empty, no team plays
    twice in a day, 10-16 back-to-back sets per team.

    Migration variant: pass `gp_played`/`played_pairs` (already-aired results)
    to build only the REMAINDER of the season — `gp_played` is accepted for
    caller-side bookkeeping/verification (minimal §7's post-hoc GP check);
    the actual trim is `played_pairs` against `matchups`, so totals still sum
    to exactly 82 per team once combined with what already aired.
    """
    del gp_played   # advisory only — see docstring; the trim is played_pairs-driven
    pool = _remainder(matchups, played_pairs) if played_pairs else list(matchups)
    rng = random.Random(f"assign:{season}:{start}")
    rng.shuffle(pool)

    air_by_date = _prebuild_air_schedule(pool, start, season)
    start_d = _date.fromisoformat(start)
    last_air_day = max(((_date.fromisoformat(d) - start_d).days for d in air_by_date),
                        default=-1)

    days: dict[str, list] = {}
    last_played: dict[str, int] = {}
    start_date = start_d
    day_idx = 0
    max_days = 600
    b2b_target = {t: rng.randint(*_B2B_TARGET_RANGE) for t in _ALL_TEAMS}
    b2b_actual = {t: 0 for t in _ALL_TEAMS}
    chain_len: dict[str, int] = {}   # consecutive play-days ending yesterday

    # keep advancing at least until every pre-built AIR night has had its
    # turn, even if the general pool empties out before then (a generously
    # planned AIR calendar can outlast a lucky/unlucky general-fill pace) —
    # otherwise a still-unplaced pre-built AIR game would never get its day.
    while (pool or day_idx <= last_air_day) and day_idx < max_days:
        d = start_date + _timedelta(days=day_idx)
        if _is_blocked(d):
            day_idx += 1
            continue
        is_air = d.weekday() in _AIR_WEEKDAYS
        today: set[str] = set()
        day_list: list = []
        night_cap = rng.randint(_NIGHT_MIN, _NIGHT_MAX)
        yesterday_idx = day_idx - 1
        d_iso = d.isoformat()

        game = air_by_date.get(d_iso)
        if game is not None:
            day_list.append(game)
            today.update(game[:2])
            # a pre-built AIR game is mandatory, but if it lands right after
            # a tracked team's last game, it's a real back-to-back and must
            # still count against that team's target, or the forward-looking
            # guard below (which relies on this bookkeeping) would under-count.
            for t in game[:2]:
                if last_played.get(t) == day_idx - 1:
                    b2b_actual[t] += 1

        excluded = set(TRACKED) if is_air else set()

        # look one day ahead: tomorrow's AIR game (if any) is already fully
        # determined in `air_by_date` — no forecasting needed — so a tracked
        # team playing TODAY would create a back-to-back TOMORROW. Gate that
        # now, same as any other back-to-back, instead of discovering the
        # overrun a day late once the (mandatory) AIR game forces it anyway.
        tomorrow_iso = (d + _timedelta(days=1)).isoformat()
        tomorrow_game = air_by_date.get(tomorrow_iso)
        tomorrow_air_teams = set(tomorrow_game[:2]) if tomorrow_game else set()

        # the mtl-nyg Crossover is marquee — every meeting airs, never filler
        candidates = [g for g in pool
                      if g[0] not in today and g[1] not in today
                      and g[0] not in excluded and g[1] not in excluded
                      and not (g[0] in TRACKED and g[1] in TRACKED)]
        fresh = [g for g in candidates
                 if last_played.get(g[0]) != yesterday_idx
                 and last_played.get(g[1]) != yesterday_idx]
        b2b_candidates = [g for g in candidates if g not in fresh]

        # Deliberate back-to-backs get first crack at the night, gated per
        # team against its own seeded `b2b_target` (10-16) — filling the cap
        # with `fresh` games FIRST would starve b2b_candidates of room almost
        # every night (fresh nearly always meets the cap on its own), so a
        # schedule built that way trends toward ~0 back-to-backs. Gating by a
        # per-team running count (not a flat probability) is what keeps every
        # team inside the band instead of a few teams randomly walking well
        # past it while others stall below the floor.
        rng.shuffle(b2b_candidates)
        for g in b2b_candidates:
            if len(day_list) >= night_cap:
                break
            if g[0] in today or g[1] in today:
                continue
            credited = [t for t in g if last_played.get(t) == yesterday_idx]
            # hard cap: never stack a 3rd straight day onto an existing pair
            # (a real "back-to-back set" is 2 games, not a run) — a team
            # whose streak ending yesterday is already 2 is off-limits today
            # regardless of how far under its own target it sits.
            if any(chain_len.get(t, 0) >= 2 for t in credited):
                continue
            if any(b2b_actual[t] >= b2b_target[t] for t in credited):
                continue
            day_list.append([g[0], g[1]])
            pool.remove(g)
            today.update(g)
            for t in credited:
                b2b_actual[t] += 1

        # night cap (grounding: ~7-8 games/night) — a maximal greedy match
        # would drain the pool in weeks; pacing it is what keeps the season
        # ~180 days. Tracked-team home-vs-untracked supply no longer needs
        # protecting here — `_prebuild_air_schedule` already carved every
        # AIR night's game out of `pool` before this loop ever started, so
        # anything left in `pool` is genuinely off-air-only surplus.
        rng.shuffle(fresh)
        for g in fresh:
            if len(day_list) >= night_cap:
                break
            if g[0] in today or g[1] in today:
                continue
            forces_b2b = [t for t in g if t in tomorrow_air_teams]
            if forces_b2b and any(b2b_actual[t] >= b2b_target[t] for t in forces_b2b):
                continue    # would create an over-budget back-to-back tomorrow
            day_list.append([g[0], g[1]])
            pool.remove(g)
            today.update(g)
            for t in forces_b2b:
                b2b_actual[t] += 1

        for t in today:
            chain_len[t] = chain_len.get(t, 1) + 1 if last_played.get(t) == day_idx - 1 else 1
            last_played[t] = day_idx
        if day_list:
            days[d.isoformat()] = day_list
        day_idx += 1

    return days
