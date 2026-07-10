"""League economy: cap accounting, in-season trades/coach firings, and the
offseason (contract decrement, re-sign/walk, free agency, draft). Ships dark
behind `data/league/ECON-ENABLED` (Gate 2) -- this module has no knowledge of
gates or files; it is a pure leaf against the minimal-§2 sidecar shapes,
called by the integrator once the gate is open.

Schema (minimal §2, frozen) this module reads/mutates in place:
  pl       players-s{n}.json body: {"schema","season",
             "players": {pid: {"name","team","pos","slot","by","ov","sh",
                                "pl","dur","aav","yrs","aired"}},
             "reserve": {team: [pid,...]}, "out2": {...}, "callups": {...},
             "retired": [...]}
  coaches  coaches-s{n}.json body: {"coaches": {team: {"name","style","mod",
             "hired_day"}}, "trainers": {team: {"name","heal"}}}
  standings  season.json's `st["league"]` dict: {team: {"w","l","otl",
             "streak","gp","rw","row"}}

Both `pl` and `coaches` grow two private, additive bookkeeping keys this
module owns: `pl["_trade_state"]` (season trade-count target/progress) and
`coaches["_fires"]` (list of {"team","day"} already fired this season) --
neither collides with any key named in minimal §2, and both are meaningless
noise to every other reader (v1 fallback, briefs.py, the site export).

SCHEMA FRICTION (reported, not improvised around):
  1. `run_day`'s signature (minimal §3, frozen) carries no
     `allow_tracked_trades` flag, though minimal §12 / hockey-final gate 2
     require one ("tracked-team trades... require allow_tracked_trades, an
     owner flag"). Implemented as an optional, additive `pl["allow_tracked
     _trades"]` bool (default False = protected) rather than a new
     parameter, since the signature may not be changed. The integrator sets
     this key from whatever owner-facing flag file/config it wires up.
  2. minimal §12's literal trade deadline ("first Friday of month 8 of the
     season") falls AFTER this engine's own ~182-day, July-start regular
     season ends (month 8 = February; the finale is ~Jan 6, minimal §5) --
     the two halves of the frozen design disagree with each other on this
     one date. Implemented `DEADLINE_DAY` at ~78% through the season instead
     (day 142 of ~182), matching the *grounding* doc's actual NHL cadence
     (deadline day 150 of a 191-day Oct-Apr season, same ~0.785 fraction)
     over the literal-but-unreachable "month 8" reading.
  3. `run_day`/`offseason` receive no calendar date, only `day_idx`/`season`
     -- so `SEASON_DAYS`/`DEADLINE_DAY`/`FIRING_WINDOW` below are this
     module's own internal reference frame (documented assumptions), not a
     value derived from `calendar.py` (a sibling leaf module this one may
     not import). Transaction dicts for `offseason()` (draft/re-sign/FA)
     therefore have no `day` key -- there is no day_idx parameter to hang
     one on; the integrator can date-stamp them at the fixed rollover
     calendar milestone when appending to transactions-s{n}.json.
  4. Component rules bar this module from importing `livegame` (only
     `boxscore.py` may) -- so minted coach/draftee names use a small local
     name bank here (`_C_FIRST/_C_LAST`, `_D_FIRST/_D_LAST`) rather than
     `livegame.FIRST_NAMES/LAST_NAMES`. These are reserve/depth names, never
     the `aired:true` protected core, so they never reach the guarded
     broadcast surface.
  5. Draft "non-playoff" status is approximated as the bottom 16 teams by
     standings pts% -- `offseason`'s only input is the flat standings dict
     (no bracket, no division data; mirrors the same leaf-module limitation
     `playoffs.py` documents for its own division constant). The real
     16-team playoff field (top-3/div + 2 WC/conf) can differ slightly from
     a pure points-percentage ordering; inaudible in practice since the two
     rarely disagree by more than a team or two at the mid-teens boundary.
"""
from __future__ import annotations

import math
import random

CAP_CEILING = 95.5
CAP_FLOOR = 0.74 * CAP_CEILING
LEAGUE_MIN = 0.775
MAX_HIT = 0.20 * CAP_CEILING          # hockey-final's tightened band

# --- this module's internal calendar reference frame (see friction #3) -----
SEASON_DAYS = 182                     # ~26-week regular season (minimal §5)
DEADLINE_DAY = 142                    # ~78% through season (friction #2)
FIRING_WINDOW = (115, 178)            # Nov-Feb analog, back ~1/3 of season
FIRE_COOLDOWN = 20                    # days before a just-hired coach is
                                       # eligible to be fired again

_STYLES = ["defensive", "offensive", "chaotic-neutral", "stoic", "screamer",
           "analytics-pilled", "old-school", "player's coach", "grinder"]

# --- local name banks (friction #4): coaches + draftees only, never aired ---
_C_FIRST = ("Marcel Gord Ruth Sal Denise Artie Hollis Trudy Wade Fern Odell "
            "Junie Casper Lorraine Buck").split()
_C_LAST = ("Demers Sopel Pruitt Tarantella Vachon Yun Ferland Onions Brix "
           "Halloran Meacham Osgood Prewitt Landreth").split()
_D_FIRST = ("Wyatt Cole Miko Anton Reid Soren Jules Denny Otis Cy Bram Nils "
            "Iggy Zane Corwin Hux").split()
_D_LAST = ("Vantassel Okonkwo Brix Halversen Muth Pigeon Voss Quantrell "
           "Brannigan Skeete Follett Marchetti Bellweather Ostroff "
           "Kessling Draper").split()

_LOTTERY_ODDS = [18.5, 13.5, 11.5, 9.5, 8.5, 7.5, 6.5, 6.0, 5.0, 3.5, 3.0,
                  2.5, 2.0, 1.5, 0.5, 0.5]                      # sums to 100
_MAX_LOTTERY_FALL = 10


# --- cap accounting ---------------------------------------------------------

def payroll(pl: dict, team: str) -> float:
    """Sum of `aav` for `team`'s ACTIVE roster (reserve/minor-league entries
    in `pl["reserve"][team]` don't count against the cap, matching the real
    NHL's AHL-doesn't-count rule)."""
    reserve = set(pl.get("reserve", {}).get(team, []))
    total = 0.0
    for pid, p in pl.get("players", {}).items():
        if p.get("team") == team and pid not in reserve:
            total += p.get("aav", 0.0)
    return round(total, 6)


def cap_ok(pl: dict, team: str) -> bool:
    """Team payroll (active roster only) inside [CAP_FLOOR, CAP_CEILING]."""
    pr = payroll(pl, team)
    return CAP_FLOOR <= pr <= CAP_CEILING


# --- shared helpers ----------------------------------------------------------

def _pts(standings: dict, team: str) -> int:
    t = standings[team]
    return t["w"] * 2 + t.get("otl", 0)


def _pts_pct(standings: dict, team: str) -> float:
    t = standings[team]
    gp = t.get("gp", 0)
    return (_pts(standings, team) / (2 * gp)) if gp else 0.5


def _rank_teams(standings: dict) -> list:
    """Worst -> best by points percentage. Ties keep dict insertion order
    (stable sort), a deterministic tie-break of last resort."""
    return sorted(standings.keys(), key=lambda k: _pts_pct(standings, k))


def _tradeable(pl: dict, team: str) -> list:
    """Active-roster player ids for `team` eligible to be traded: excludes
    reserves and, unless `pl["allow_tracked_trades"]` is truthy, excludes
    every `aired: true` player (friction #1) -- the aired 9 are canon and
    stay put by default."""
    allow = bool(pl.get("allow_tracked_trades"))
    reserve = set(pl.get("reserve", {}).get(team, []))
    out = []
    for pid, p in pl.get("players", {}).items():
        if p.get("team") != team or pid in reserve:
            continue
        if p.get("aired") and not allow:
            continue
        out.append(pid)
    return out


def _remaining_non_deadline_days(day_idx: int) -> int:
    left = SEASON_DAYS - day_idx
    if DEADLINE_DAY >= day_idx:
        left -= 1
    return max(left, 0)


# --- trades ------------------------------------------------------------------

def _attempt_trade(pl: dict, standings: dict, rng: random.Random):
    """One cap-legal swap between a bottom-third 'seller' and a top-third
    'buyer', matched to minimize cap disruption. Returns a §2 transaction
    dict, or None if no legal trade could be formed this attempt (thin
    tradeable pools, or every candidate pairing would blow the ceiling)."""
    ranked = _rank_teams(standings)
    n = len(ranked)
    if n < 4:
        return None
    third = max(1, n // 3)
    sellers, buyers = ranked[:third], ranked[-third:]
    seller = rng.choice(sellers)
    buyer_pool = [t for t in buyers if t != seller]
    if not buyer_pool:
        return None
    buyer = rng.choice(buyer_pool)

    s_pool = _tradeable(pl, seller)
    b_pool = _tradeable(pl, buyer)
    if not s_pool or not b_pool:
        return None

    two_for_one = rng.random() < 0.15 and len(s_pool) >= 2
    s_players = rng.sample(s_pool, 2 if two_for_one else 1)
    s_out_aav = sum(pl["players"][pid]["aav"] for pid in s_players)

    # pick the buyer piece whose aav is closest to what the seller sent, to
    # keep both sides' payrolls near where they started ("cap-legal" swap)
    b_players = [min(b_pool,
                      key=lambda pid: abs(pl["players"][pid]["aav"] - s_out_aav))]
    b_out_aav = pl["players"][b_players[0]]["aav"]

    before_s, before_b = payroll(pl, seller), payroll(pl, buyer)
    after_s = before_s - s_out_aav + b_out_aav
    after_b = before_b - b_out_aav + s_out_aav
    if after_s > CAP_CEILING or after_b > CAP_CEILING:
        return None                          # cap-legal check (ceiling only;
                                              # floor is a compliance metric,
                                              # not a per-trade blocker)

    for pid in s_players:
        pl["players"][pid]["team"] = buyer
    for pid in b_players:
        pl["players"][pid]["team"] = seller

    return {"type": "trade", "from": seller, "to": buyer,
            "out": s_players, "in": b_players,
            "note": "cap dump" if two_for_one else "change of scenery"}


def _season_trade_target(season: int) -> int:
    aux = random.Random(f"econ-trade-target:{season}")
    return aux.randint(60, 100)


def _season_deadline_target(season: int, total: int) -> int:
    aux = random.Random(f"econ-deadline-target:{season}")
    return min(aux.randint(15, 25), total)


def _run_trades(pl: dict, standings: dict, season: int, day_idx: int,
                 rng: random.Random) -> list:
    state = pl.setdefault("_trade_state",
                           {"done": 0, "deadline_done": 0,
                            "target": None, "deadline_target": None})
    if state["target"] is None:
        state["target"] = _season_trade_target(season)
        state["deadline_target"] = _season_deadline_target(season, state["target"])

    tx = []
    if day_idx == DEADLINE_DAY:
        need = state["deadline_target"] - state["deadline_done"]
        for _ in range(max(0, need)):
            t = _attempt_trade(pl, standings, rng)
            if t:
                t["day"] = day_idx
                tx.append(t)
                state["deadline_done"] += 1
        return tx

    remaining_total = state["target"] - state["deadline_target"]
    remaining_days = _remaining_non_deadline_days(day_idx)
    remaining_needed = remaining_total - state["done"]
    if remaining_days > 0 and remaining_needed > 0:
        p = min(1.0, remaining_needed / remaining_days)
    else:
        p = 0.0
    if rng.random() < p:
        t = _attempt_trade(pl, standings, rng)
        if t:
            t["day"] = day_idx
            tx.append(t)
            state["done"] += 1
    return tx


# --- coach firings -------------------------------------------------------

def _season_fire_target(season: int) -> int:
    """Poisson(lambda=5.5) via Knuth's algorithm, clamped to hockey-final's
    tightened 4-8 band. Seeded off `season` alone (not the per-day `rng`
    argument) so every day's call within one season agrees on the same
    target without needing extra persisted state beyond the running
    `coaches["_fires"]` tally."""
    aux = random.Random(f"econ-fire-target:{season}")
    L = math.exp(-5.5)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= aux.random()
        if p <= L:
            break
    return min(8, max(4, k - 1))


def _fire_candidate(coaches: dict, standings: dict, day_idx: int,
                     rng: random.Random):
    fired = {f["team"] for f in coaches.get("_fires", [])}
    hired_day = {t: c.get("hired_day", -10 ** 9)
                 for t, c in coaches.get("coaches", {}).items()}
    candidates = [t for t in standings
                  if t not in fired
                  and day_idx - hired_day.get(t, -10 ** 9) > FIRE_COOLDOWN]
    if not candidates:
        return None
    # bias toward underperformers: further below .500 pace -> higher weight
    weights = [max(0.01, 0.55 - _pts_pct(standings, t)) for t in candidates]
    return rng.choices(candidates, weights=weights, k=1)[0]


def _mint_coach_name(rng: random.Random) -> str:
    return f"{rng.choice(_C_FIRST)} {rng.choice(_C_LAST)}"


def _run_firings(pl: dict, coaches: dict, standings: dict, season: int,
                  day_idx: int, rng: random.Random) -> list:
    if not (FIRING_WINDOW[0] <= day_idx <= FIRING_WINDOW[1]):
        return []
    coaches.setdefault("coaches", {})
    fires = coaches.setdefault("_fires", [])
    target = _season_fire_target(season)
    remaining_fires = target - len(fires)
    if remaining_fires <= 0:
        return []
    remaining_days = FIRING_WINDOW[1] - day_idx + 1
    p = min(1.0, remaining_fires / remaining_days)
    if rng.random() >= p:
        return []
    team = _fire_candidate(coaches, standings, day_idx, rng)
    if team is None:
        return []
    old = coaches["coaches"].get(team, {}).get("name", "the previous coach")
    new_name = _mint_coach_name(rng)
    coaches["coaches"][team] = {
        "name": new_name,
        "style": rng.choice(_STYLES),
        "mod": round(rng.uniform(-0.02, 0.02), 4),
        "hired_day": day_idx,
    }
    fires.append({"team": team, "day": day_idx})
    return [{"day": day_idx, "type": "coach_fired", "team": team,
             "old": old, "new": new_name,
             "note": f"the {team.upper()} have relieved {old} of his "
                     f"duties; {new_name} takes over behind the bench."}]


# --- public: in-season daily tick --------------------------------------------

def run_day(pl: dict, coaches: dict, standings: dict, season: int,
            day_idx: int, rng: random.Random) -> list:
    """One day's economy activity, called from the day-boundary loop (tick
    §6.f) with a date-seeded `rng` (e.g. `random.Random(f"econ:{season}:
    {day_idx}")`). Mutates `pl`/`coaches` in place (trades move `team`
    fields; firings replace a `coaches["coaches"][team]` entry) and returns
    the list of §2 transaction dicts generated today (empty most days)."""
    tx = []
    tx.extend(_run_trades(pl, standings, season, day_idx, rng))
    tx.extend(_run_firings(pl, coaches, standings, season, day_idx, rng))
    return tx


# --- offseason ---------------------------------------------------------------

def _resign(p: dict, rng: random.Random) -> tuple:
    """ov-scaled re-sign formula with seeded noise, clipped to the league's
    salary band."""
    base = LEAGUE_MIN + (max(0.0, min(1.0, p.get("ov", 0.5))) ** 1.6) * (
        MAX_HIT - LEAGUE_MIN)
    noise = rng.uniform(0.85, 1.15)
    aav = round(min(MAX_HIT, max(LEAGUE_MIN, base * noise)), 3)
    yrs = rng.randint(1, 4)
    return aav, yrs


def _weighted_order(items: list, weights: list, rng: random.Random) -> list:
    """Weighted sample-without-replacement full ordering."""
    pool = list(zip(items, weights))
    order = []
    while pool:
        total = sum(w for _, w in pool)
        r = rng.uniform(0, total)
        upto = 0.0
        for i, (t, w) in enumerate(pool):
            upto += w
            if upto >= r:
                order.append(t)
                pool.pop(i)
                break
        else:
            order.append(pool[-1][0])
            pool.pop()
    return order


def _lottery(non_playoff: list, rng: random.Random) -> list:
    """`non_playoff`: worst -> best, up to 16 teams. Weighted draw per the
    grounding odds table, then a repair pass enforcing the max-10-spot-fall
    rule (a team may never draw a pick more than 10 spots worse than its
    actual worst-to-best position)."""
    weights = _LOTTERY_ODDS[:len(non_playoff)]
    draw = _weighted_order(non_playoff, weights, rng)
    orig_pos = {t: i for i, t in enumerate(non_playoff)}
    for _ in range(len(draw) * 2):
        violated = next((t for i, t in enumerate(draw)
                          if i - orig_pos[t] > _MAX_LOTTERY_FALL), None)
        if violated is None:
            break
        draw.remove(violated)
        draw.insert(orig_pos[violated] + _MAX_LOTTERY_FALL, violated)
    return draw


def _mint_draftee(pl: dict, team: str, season: int, rng: random.Random):
    while True:
        pid = f"{team}-dr{rng.randint(1000, 9999)}"
        if pid not in pl.get("players", {}):
            break
    name = f"{rng.choice(_D_FIRST)} {rng.choice(_D_LAST)}"
    ov = round(min(0.90, max(0.25, rng.gauss(0.50, 0.16))), 3)   # high-variance
    player = {
        "name": name, "team": team, "pos": rng.choice(["C", "LW", "RW", "D", "G"]),
        "slot": "R", "by": season - 18, "ov": ov,
        "sh": round(rng.random(), 3), "pl": round(rng.random(), 3),
        "dur": round(rng.uniform(0.5, 0.9), 3),
        "aav": LEAGUE_MIN, "yrs": 3, "aired": False,
    }
    return pid, player


def _draft(pl: dict, standings: dict, season: int, rng: random.Random) -> list:
    ranked = _rank_teams(standings)                       # worst -> best
    non_playoff = ranked[:16]
    playoff_teams = ranked[16:]                            # already worst-first
    round1_order = _lottery(non_playoff, rng) + playoff_teams
    later_order = ranked

    tx = []
    for rnd in range(1, 8):
        order = round1_order if rnd == 1 else later_order
        for team in order:
            pid, player = _mint_draftee(pl, team, season, rng)
            pl.setdefault("players", {})[pid] = player
            pl.setdefault("reserve", {}).setdefault(team, []).append(pid)
            tx.append({"type": "draft", "team": team, "round": rnd,
                       "player": pid, "name": player["name"],
                       "note": f"{team.upper()} select {player['name']} "
                               f"in round {rnd}"})
    return tx


def offseason(pl: dict, coaches: dict, standings: dict, season: int,
              rng: random.Random) -> list:
    """Contract decrement + re-sign/walk + seeded FA redistribution + 7-round
    draft. Does NOT touch player attributes (`develop()`-style aging deltas
    are explicitly out of scope for this component, per hockey-final) and
    does NOT process retirements (no `retired`-list mandate in this
    component's row; `pl["retired"]` is left untouched)."""
    tx = []

    for p in pl.get("players", {}).values():
        p["yrs"] = max(0, p.get("yrs", 1) - 1)

    fa_pool = []
    for pid, p in list(pl.get("players", {}).items()):
        if p["yrs"] > 0:
            continue
        team = p["team"]
        age = season - p.get("by", season - 27)
        if age < 27:
            aav, yrs = _resign(p, rng)
            p["aav"], p["yrs"] = aav, yrs
            tx.append({"type": "resign", "team": team, "player": pid,
                       "aav": aav, "yrs": yrs,
                       "note": f"{p['name']} re-signs with {team.upper()}"})
        elif rng.random() < 0.15:
            fa_pool.append(pid)
            tx.append({"type": "fa_walk", "team": team, "player": pid,
                       "note": f"{p['name']} walks in free agency"})
        else:
            aav, yrs = _resign(p, rng)
            p["aav"], p["yrs"] = aav, yrs
            tx.append({"type": "resign", "team": team, "player": pid,
                       "aav": aav, "yrs": yrs,
                       "note": f"{p['name']} re-signs with {team.upper()}"})

    rng.shuffle(fa_pool)
    teams = sorted(standings.keys())
    for pid in fa_pool:
        p = pl["players"][pid]
        old_team = p["team"]
        candidates = [t for t in teams if t != old_team]
        rng.shuffle(candidates)
        for t in candidates:
            room = CAP_CEILING - payroll(pl, t)
            if room >= p["aav"]:
                p["team"] = t
                tx.append({"type": "fa_sign", "team": t, "from": old_team,
                           "player": pid, "aav": p["aav"],
                           "note": f"{p['name']} signs with {t.upper()}"})
                break

    tx.extend(_draft(pl, standings, season, rng))
    return tx
