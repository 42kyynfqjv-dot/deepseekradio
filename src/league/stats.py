"""League stats: fold box scores into the season aggregate, rank leaders,
summarize goalie form, and mint groundable milestone lines.

Schema (minimal §2, frozen):
  stats-s{n}.json  {"schema":1,"season":n,
                     "skaters": {pid: [gp,g,a,pim,gwg,hat]},
                     "goalies": {pid: [gp,w,l,otl,sa,sv,so]}}
  box/{date}.json  games: [{"home","away","final":[hg,ag],"ot","so",
                             "goals":[{"t","period","clock","scorer",
                                       "a1","a2","str"}],
                             "shots":[h,a], "goalies":{"h","a"},
                             "stars":[...], "injuries":[...]}]

Friction note (schema is frozen, conforming as-is): the box carries no full
dressed-lineup list, only players who touch a goal (scorer/a1/a2) or start
in net. `fold_box` therefore can only award skater `gp` to players who
register a point in the game — a skater who dresses and is held off the
scoresheet gets no `gp` credit that night. This is a real fidelity gap
(a bottom-six shutdown guy's gp will lag their actual games-dressed) but
there is no way to recover full-roster attendance from this box shape
without widening it, which is out of scope for this component.

The box also carries no explicit game-winning-goal flag, so `fold_box`
derives it the standard NHL way: chronological goals (sorted by period,
then clock-elapsed-in-period), first goal by the eventual winner that
brings their tally to (loser's final + 1). Shootout-decided games whose
box has no goal event reaching that tally (the winning goal live only in
the shootout, not in `goals`) simply get no GWG credited — no player is
double-counted or guessed at.
"""

import re

MIN_GP_GOALIE_RATE = 10  # gp floor to qualify for sv% leaderboards


def _clock_secs(clock: str) -> int:
    """'5:12' (mm:ss elapsed in period) -> 312."""
    m, s = clock.split(":")
    return int(m) * 60 + int(s)


def _sk(stats: dict, pid: str) -> list:
    return stats.setdefault("skaters", {}).setdefault(pid, [0, 0, 0, 0, 0, 0])


def _gl(stats: dict, pid: str) -> list:
    return stats.setdefault("goalies", {}).setdefault(pid, [0, 0, 0, 0, 0, 0, 0])


def fold_box(stats: dict, box: dict) -> None:
    """Mutate `stats` in place, folding one box score into the season
    aggregate. Idempotent only if called once per box (no de-dup key is
    kept, per the frozen schema — the caller must not double-fold)."""
    stats.setdefault("skaters", {})
    stats.setdefault("goalies", {})

    home, away = box["home"], box["away"]
    hg, ag = box["final"]
    ot, so = box.get("ot", False), box.get("so", False)
    shots = box.get("shots", [0, 0])
    goalies = box.get("goalies", {})

    # --- goalies: gp/w/l/otl + sa/sv/so ---
    h_pid, a_pid = goalies.get("h"), goalies.get("a")
    if h_pid:
        g = _gl(stats, h_pid)
        g[0] += 1
        g[4] += shots[1] if len(shots) > 1 else 0
        g[5] += max(0, (shots[1] if len(shots) > 1 else 0) - ag)
        if hg > ag:
            g[1] += 1
        elif ot or so:
            g[3] += 1
        else:
            g[2] += 1
        if ag == 0:
            g[6] += 1
    if a_pid:
        g = _gl(stats, a_pid)
        g[0] += 1
        g[4] += shots[0] if len(shots) > 0 else 0
        g[5] += max(0, (shots[0] if len(shots) > 0 else 0) - hg)
        if ag > hg:
            g[1] += 1
        elif ot or so:
            g[3] += 1
        else:
            g[2] += 1
        if hg == 0:
            g[6] += 1

    # --- skaters: goals, assists, pim, gp, hat, gwg ---
    goals = box.get("goals", [])
    goals_this_game = {}   # pid -> goal count in this box
    participants = set()

    for ev in goals:
        scorer = ev.get("scorer")
        if scorer:
            _sk(stats, scorer)[1] += 1
            goals_this_game[scorer] = goals_this_game.get(scorer, 0) + 1
            participants.add(scorer)
        a1, a2 = ev.get("a1"), ev.get("a2")
        if a1:
            _sk(stats, a1)[2] += 1
            participants.add(a1)
        if a2:
            _sk(stats, a2)[2] += 1
            participants.add(a2)

    for pid in participants:
        _sk(stats, pid)[0] += 1

    for pid, n in goals_this_game.items():
        if n >= 3:
            _sk(stats, pid)[5] += 1

    # --- game-winning goal (derived: no explicit flag in the box) ---
    winner_side = "h" if hg > ag else "a"
    loser_final = ag if winner_side == "h" else hg
    # periods mix ints (1/2/3) with the strings "OT"/"SO" — map to a common
    # ordinal or every OT-decided game crashes the fold (found at verify)
    _PORD = {"OT": 4, "SO": 5}
    ordered = sorted(
        goals,
        key=lambda ev: (_PORD.get(ev.get("period", 0), ev.get("period", 0))
                        if isinstance(ev.get("period", 0), str)
                        else ev.get("period", 0),
                        _clock_secs(ev.get("clock", "0:00"))),
    )
    tally = 0
    for ev in ordered:
        if ev.get("t") == winner_side:
            tally += 1
            if tally == loser_final + 1:
                scorer = ev.get("scorer")
                if scorer:
                    _sk(stats, scorer)[4] += 1
                break


def _lookup(players: dict) -> dict:
    """players.py's mint_league body is {"players": {pid: {...}}, ...};
    accept either that whole body or an already-unwrapped pid->info dict."""
    if isinstance(players, dict) and "players" in players and isinstance(players["players"], dict):
        return players["players"]
    return players or {}


def _name_team(plookup: dict, pid: str) -> tuple:
    info = plookup.get(pid, {})
    return info.get("name", pid), info.get("team", pid.split("-")[0])


def leaders(stats: dict, players: dict, key: str = "p", n: int = 5) -> list:
    """Top-`n` leaders by `key` ('p' points, 'g' goals, 'a' assists for
    skaters; 'sv%' for goalies, gated by MIN_GP_GOALIE_RATE). Ties keep
    insertion order (Timsort is stable; dict iteration is stable in py3.7+),
    i.e. leaders are deterministic across repeated calls on the same stats."""
    plookup = _lookup(players)

    if key == "sv%":
        rows = []
        for pid, arr in stats.get("goalies", {}).items():
            gp, w, l, otl, sa, sv, so = arr
            if gp < MIN_GP_GOALIE_RATE:
                continue
            name, team = _name_team(plookup, pid)
            svp = sv / sa if sa else 0.0
            rows.append({"pid": pid, "name": name, "team": team, "gp": gp,
                         "sv%": round(svp, 3)})
        rows.sort(key=lambda r: -r["sv%"])
        return rows[:n]

    if key not in ("p", "g", "a"):
        raise ValueError(f"unknown leaders key: {key!r}")

    rows = []
    for pid, arr in stats.get("skaters", {}).items():
        gp, g, a, pim, gwg, hat = arr
        name, team = _name_team(plookup, pid)
        rows.append({"pid": pid, "name": name, "team": team,
                     "gp": gp, "g": g, "a": a, "p": g + a})
    rows.sort(key=lambda r: -r[key])
    return rows[:n]


def goalie_form(stats: dict, pid: str) -> dict:
    """sv%, gaa (goals-against per 60, assuming a 60-min regulation game),
    shutout count -- all zero if `pid` has no goalie record yet."""
    arr = stats.get("goalies", {}).get(pid)
    if not arr:
        return {"sv%": 0.0, "gaa": 0.0, "so": 0}
    gp, w, l, otl, sa, sv, so = arr
    svp = sv / sa if sa else 0.0
    gaa = (sa - sv) / gp if gp else 0.0
    return {"sv%": round(svp, 3), "gaa": round(gaa, 2), "so": so}


_ORD_SPECIAL = {11: "11th", 12: "12th", 13: "13th"}


def _ordinal(n: int) -> str:
    if n % 100 in _ORD_SPECIAL:
        return _ORD_SPECIAL[n % 100]
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _poss(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def milestones(stats: dict, players: dict, box: dict) -> list:
    """Groundable broadcast lines for the box just folded ('Bouchard's 20th
    of the season', hat tricks, shutouts). MUST be called after fold_box(
    stats, box) for the same box -- every number quoted is read straight
    back out of the just-mutated `stats`, never computed independently, so
    a line can never claim a total the aggregate doesn't actually hold."""
    plookup = _lookup(players)
    lines = []

    goals_this_game = {}
    for ev in box.get("goals", []):
        scorer = ev.get("scorer")
        if scorer:
            goals_this_game[scorer] = goals_this_game.get(scorer, 0) + 1

    for pid, n in goals_this_game.items():
        arr = stats.get("skaters", {}).get(pid)
        if not arr:
            continue
        g_after = arr[1]
        name, _ = _name_team(plookup, pid)
        if g_after > 0 and g_after % 10 == 0:
            lines.append(f"{_poss(name)} {_ordinal(g_after)} of the season")
        if n >= 3:
            hat_after = arr[5]
            lines.append(
                f"{_poss(name)} {_ordinal(hat_after)} hat trick of the season"
            )

    hg, ag = box.get("final", [0, 0])
    goalies = box.get("goalies", {})
    for side, opp_goals in (("h", ag), ("a", hg)):
        pid = goalies.get(side)
        if not pid or opp_goals != 0:
            continue
        arr = stats.get("goalies", {}).get(pid)
        if not arr:
            continue
        so_after = arr[6]
        name, _ = _name_team(plookup, pid)
        lines.append(f"{_poss(name)} {_ordinal(so_after)} shutout of the season")

    return lines
