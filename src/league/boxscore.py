"""Box scores: run one off-air game through livegame's calibrated event
engine, or retrofit an already-published final onto a dressed roster, and
emit the frozen §2 box shape (`data/league/box/{date}.json` games[i]).

This is the one league module allowed to import `livegame` (component
contract, hockey-final.md): `sim_box` calls the exact same `_sim_span` /
`_sim_shootout` the live broadcast rolls, with names on, so an off-air
slate game is statistically indistinguishable from a tracked team's
broadcast game (G5 KS parity) -- one model, two speeds.

Roster contract (this module's `home`/`away` args -- a superset of
players.py's `dress()` output; see the friction note in the component
summary for the two additive keys `dress()`'s documented shape omits):
  {"team": "mtl",                    # team key -- box["home"/"away"]
   "skaters": [name, ...],           # 18, L1-first (dress()'s shape)
   "goalie": name,                   # starting goalie's name
   "ids": [pid, ...],                # parallel to skaters, e.g. "mtl-01"
   "goalie_id": pid,                 # e.g. "mtl-22" -- undocumented in
                                      # dress()'s bullet list but needed so
                                      # box["goalies"] can carry a pid like
                                      # every other identifier in the box
   "weights": [w, ...],              # parallel to skaters, scorer draw bias
   "pweights": [w, ...]}             # parallel to skaters, assist draw bias
                                      # -- also undocumented in dress()'s
                                      # bullet list; without it the real
                                      # P(a1)=.90/P(a2|a1)=.65 assist chain
                                      # in livegame's diff never activates
                                      # ("pweights" gates it, not "weights")
                                      # and the calibrated A:G ratio is
                                      # unreachable
Every key but "skaters"/"goalie" is optional and degrades gracefully: no
"ids"/"goalie_id" -> box records names instead of pids; no "team" -> box
records the literal side ("home"/"away"); no "weights"/"pweights" -> the
draw still runs, just uniformly (not calibrated to the depth curve).
"""
from __future__ import annotations

import random

from .. import livegame

_PERIODS = (1, 2, 3)
_PERIOD_SHARE = (0.30, 0.35, 0.35)     # grounding: P1/P2/P3 share of goals
_STRENGTHS = ("EV", "PP", "SH")
_STRENGTH_SHARE = (0.78, 0.20, 0.02)   # grounding: EV/PP/SH share of goals
_PERIOD_START = {1: 0, 2: 1200, 3: 2400, "OT": 3600}


# --- roster/identity helpers -------------------------------------------

def _pid(roster: dict, name: str | None) -> str | None:
    """A player's id if the roster carries one, else the bare name."""
    if name is None:
        return None
    skaters = roster.get("skaters", [])
    ids = roster.get("ids")
    if ids and name in skaters:
        return ids[skaters.index(name)]
    return name


def _goalie_pid(roster: dict) -> str | None:
    return roster.get("goalie_id", roster.get("goalie"))


def _team_key(roster: dict, side: str) -> str:
    return roster.get("team", side)


def _weighted_pick(roster: dict, rng: random.Random, key: str,
                    exclude: set | None = None) -> str | None:
    """One skater, weighted by `roster[key]` if present (parallel to
    `roster["skaters"]`), uniform otherwise. `exclude` keeps a scorer from
    also being their own assist."""
    ex = exclude or set()
    skaters = roster.get("skaters", [])
    cands = [s for s in skaters if s not in ex]
    if not cands:
        return None
    weights = roster.get(key)
    if weights and len(weights) == len(skaters):
        wmap = dict(zip(skaters, weights))
        return rng.choices(cands, weights=[wmap[s] for s in cands], k=1)[0]
    return rng.choice(cands)


# --- sim_box -------------------------------------------------------------

def sim_box(home: dict, away: dict, s_h: float, s_a: float,
            rng: random.Random) -> dict:
    """One game, event mode: the same `_sim_span`/`_sim_shootout` the live
    broadcast runs, with names on, folded into the §2 box shape. Off-air
    slate games call this at ~2-4ms/game (minimal §6). OT/SO follow the
    exact rules `sim_instant` uses: tied after regulation -> 3-on-3 to the
    horn; still tied -> shootout. A shootout winner's extra goal is real
    (it decides the final score) but, matching the live engine and real
    NHL scoring, is NOT a `goals` entry -- shootout attempts are their own
    event type, never credited as a player's boxscore goal."""
    state = livegame._new_state()
    rosters = {"home": home, "away": away}
    events: list = []
    livegame._sim_span(state, rng, livegame.REG_SECS, s_h, s_a, rosters, events)
    h, a = state["board"]
    ot = so = False
    if h == a:
        livegame._sim_span(state, rng, livegame.REG_SECS + livegame.OT_SECS,
                            s_h, s_a, rosters, events)
        h, a = state["board"]
        if h != a:
            ot = True
        else:
            winner = livegame._sim_shootout(rng, rosters, events)
            state["board"][winner] += 1     # decides the final, no goal event
            h, a = state["board"]
            so = True

    goals, injuries = [], []
    for e in events:
        side = "h" if e.get("team") == "home" else "a"
        roster = home if side == "h" else away
        if e["type"] == "goal":
            goals.append({
                "t": side, "period": e["period"], "clock": e["clock"],
                "scorer": _pid(roster, e["scorer"]),
                "a1": _pid(roster, e.get("assist")),
                "a2": _pid(roster, e.get("assist2")),
                "str": e["strength"],
            })
        elif e["type"] == "injury":
            injuries.append({"pid": _pid(roster, e["player"]), "note": e["note"]})

    box = {
        "home": _team_key(home, "home"), "away": _team_key(away, "away"),
        "final": [h, a], "ot": ot, "so": so, "goals": goals,
        "shots": [int(state["shots"][0]), int(state["shots"][1])],
        "goalies": {"h": _goalie_pid(home), "a": _goalie_pid(away)},
        "injuries": injuries,
    }
    box["stars"] = three_stars(box)
    return box


# --- box_from_final --------------------------------------------------------

def _clock(rng: random.Random, period) -> str:
    span = livegame.OT_SECS if period == "OT" else livegame.PERIOD_SECS
    secs = rng.randint(0, span - 1)
    return f"{secs // 60}:{secs % 60:02d}"


def _chrono_key(period, clock: str) -> int:
    m, s = clock.split(":")
    return _PERIOD_START[period] + int(m) * 60 + int(s)


def _alloc_goals(roster: dict, n: int, rng: random.Random,
                  periods=_PERIODS, shares=_PERIOD_SHARE) -> list:
    """`n` goals for one side, names drawn from `roster`'s weights (uniform
    if absent), timestamped and assist-chained the same way the live engine
    would (P(a1)=.90, P(a2|a1)=.65) but without a real simulation clock --
    this is a retrofit, not a re-roll."""
    out = []
    for _ in range(n):
        period = periods[0] if len(periods) == 1 else rng.choices(periods, weights=shares)[0]
        scorer = _weighted_pick(roster, rng, "weights")
        a1 = a2 = None
        if scorer is not None and rng.random() < 0.90:
            a1 = _weighted_pick(roster, rng, "pweights", {scorer})
            if a1 is not None and rng.random() < 0.65:
                a2 = _weighted_pick(roster, rng, "pweights", {scorer, a1})
        out.append({"period": period, "clock": _clock(rng, period),
                    "scorer": scorer, "a1": a1, "a2": a2,
                    "str": rng.choices(_STRENGTHS, weights=_STRENGTH_SHARE)[0]})
    return out


def box_from_final(home: dict, away: dict, final: list, ot: bool, so: bool,
                    rng: random.Random) -> dict:
    """Migration retrofit: an already-published final's score is canon and
    is NEVER recomputed here -- `final`/`ot`/`so` pass through unaltered;
    only the goals are allocated to names/ids on the dressed rosters, so
    every number stats.py later folds is internally consistent with the
    aired result. Invariant: `sum(goals) == final` exactly, for every game
    including OT/SO -- unlike `sim_box`'s live-accurate shootout (whose
    winning attempt has no goal event), `box_from_final` has no attempts to
    model at all, so the beyond-regulation/shootout winner's tally is
    recorded as one retrofit goal event (tagged period "OT") purely so the
    box's own goal list always sums to the number everyone already heard."""
    h, a = final
    reg_h, reg_a, extra_side = h, a, None
    if so or ot:
        winner = "h" if h > a else "a"
        extra_side = winner
        if winner == "h":
            reg_h = max(0, reg_h - 1)
        else:
            reg_a = max(0, reg_a - 1)

    events = []
    for side, roster, n in (("h", home, reg_h), ("a", away, reg_a)):
        for g in _alloc_goals(roster, n, rng):
            g["t"] = side
            events.append(g)
    if extra_side:
        roster = home if extra_side == "h" else away
        g = _alloc_goals(roster, 1, rng, periods=("OT",), shares=(1.0,))[0]
        g["t"] = extra_side
        events.append(g)
    events.sort(key=lambda g: _chrono_key(g["period"], g["clock"]))

    for g in events:
        roster = home if g["t"] == "h" else away
        g["scorer"] = _pid(roster, g["scorer"])
        g["a1"] = _pid(roster, g["a1"])
        g["a2"] = _pid(roster, g["a2"])

    shots = [max(h, int(round(rng.gauss(30, 4)))),
             max(a, int(round(rng.gauss(30, 4))))]

    box = {
        "home": _team_key(home, "home"), "away": _team_key(away, "away"),
        "final": [h, a], "ot": ot, "so": so, "goals": events,
        "shots": shots, "goalies": {"h": _goalie_pid(home), "a": _goalie_pid(away)},
        "injuries": [],
    }
    box["stars"] = three_stars(box)
    return box


# --- three_stars -----------------------------------------------------------

def three_stars(box: dict) -> list:
    """Mirrors livegame._finalize's stars logic: top scorers by in-game
    tally (ties broken toward whoever scored later) plus the winning
    goalie. Unlike the live engine, this has no full dressed lineup to pad
    from if goals are scarce -- the box carries only players who touch a
    goal or start in net (stats.py's frozen-schema friction note applies
    here too) -- so a low-scoring game can return fewer than 3 names."""
    tally: dict = {}
    order = []
    for g in box.get("goals", []):
        pid = g.get("scorer")
        if pid is None:
            continue
        tally[pid] = tally.get(pid, 0) + 1
        order.append(pid)
    stars = sorted(dict.fromkeys(reversed(order)), key=lambda p: -tally[p])[:2]
    h, a = box["final"]
    goalie = box.get("goalies", {}).get("h" if h > a else "a")
    if goalie is not None and goalie not in stars:
        stars.append(goalie)
    return stars[:3]
