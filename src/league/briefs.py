"""League briefs — the broadcast contract (minimal §10) plus the G1 reveal
clock. Every sheet here is a pure function of dicts already loaded by the
caller: no file I/O, no season.py/orchestrator.py import (leaf module), no
outcome invented that isn't already sitting in the box/stats/players the
caller handed us. Code decides the facts; these functions only phrase them.

**The reveal clock (G1).** Off-air games are fully simulated ahead of time
(one model, three speeds — the same story as season.py's existing off-air
slates), so their entire box score already exists the moment the slate is
folded. What listeners don't get is the illusion of it unfolding live. Each
such game is assigned a seeded virtual puck-drop `start_off` (0-90 minutes
after our own broadcast's pregame airs); `reveal(box, start_off, cursor)`
replays that already-known box against a shared wall clock (`cursor`,
seconds since pregame air) and answers "what would a listener plausibly know
right now" — upcoming, live with a partial score/period/clock, or final. It
is the ONLY function that turns a box into an in-progress read, so the
intermission sheet, the scores desk, and (per the design) export()'s
`around` rows all agree — one clock, no cross-feed contradictions.

**Schema-friction notes (frozen contract, conformed to as given):**
  - `intermission_sheet(date, cursor, boxes, stats, players)` has no
    `season` parameter, but G1's canonical start_off seed is
    `drop:{season}:{d}:{hk}-{ak}`. `_start_off` here drops the season
    component (`drop:{date}:{home}-{away}`) since date is already unique
    per season under the 1:1 calendar (§5) — collision-safe, just narrower
    entropy than the design's literal seed string.
  - `postgame_quote_grounding(game, final, box, stats)` has no `players`
    parameter, yet box-shape goal/assist/goalie fields are player IDs
    (`"scorer": "tbr-03"`, confirmed by the landed stats.py fold_box/
    milestones convention). Names are resolved without a players dict by
    reading `game["rosters"][side]["ids"]`/`["skaters"]` (parallel arrays,
    per players.dress()'s frozen shape) for skaters, and
    `game["rosters"][side]["goalie"]` (already a name) for goalies — the
    box's own `"goalies"` pids are used only to index `stats` for a
    goalie's season W-L-OTL line. This fully resolves ordinary nights; an
    emergency mid-game goalie change that never touched `game["rosters"]`
    would not get a season line (accepted edge-case gap).
  - `players` elsewhere is accepted in either shape stats.py already
    established: the whole minted body `{"players": {pid: {...}}, ...}`
    or an already-unwrapped `{pid: {...}}` map (`_plook` normalizes it,
    mirroring stats.py's private `_lookup`).
  - `leaders`/`goalie_form` are NOT reimplemented here: this module imports
    the already-landed `src/league/stats.py` (a sibling leaf module, not
    season.py/orchestrator.py, so the no-import rule doesn't apply) to
    keep one leaderboard definition system-wide.
"""
from __future__ import annotations

import random

from . import stats as leaguestats

# --- reveal clock geometry (mirrors livegame.py's constants; briefs.py may
# not import livegame — only boxscore.py may — so these are restated, not
# shared, and must stay numerically in lockstep with PERIOD_SECS/REG_SECS/
# OT_SECS over there).
PERIOD_SECS = 1200
REG_SECS = 3 * PERIOD_SECS
OT_SECS = 300
SO_SECS = 300   # narrative budget for an in-progress shootout window; a real
                # shootout has no game clock, this just bounds how long the
                # reveal clock treats the game as "live" before flipping final


def _period_secs(period) -> int:
    return REG_SECS if period == "OT" else (int(period) - 1) * PERIOD_SECS


def _mmss_to_secs(clock: str) -> int:
    m, s = clock.split(":")
    return int(m) * 60 + int(s)


def _goal_abs_secs(g: dict) -> int:
    return _period_secs(g.get("period", 1)) + _mmss_to_secs(g.get("clock", "0:00"))


def _fmt_clock(secs) -> str:
    secs = max(0, int(secs))
    return f"{secs // 60}:{secs % 60:02d}"


def _game_end_secs(box: dict) -> int:
    """Absolute reveal-clock second at which the box's real outcome is
    fully known. Regulation always counts; +5 for an OT decision; +5 more
    (a fixed narrative budget, not a real clock) for a shootout."""
    end = REG_SECS
    if box.get("so"):
        end += OT_SECS + SO_SECS
    elif box.get("ot"):
        end += OT_SECS
    return end


def reveal(box: dict, start_off: int, cursor: int) -> dict:
    """The ONLY renderer of off-air game progress. `box` is one already-
    simulated game (frozen §2 shape: final/ot/so/goals/shots/goalies/
    stars/injuries) — the outcome exists in full the moment this is
    called, `reveal` only decides how much of it a listener could
    plausibly know at `cursor` seconds into tonight's broadcast, given the
    game's seeded virtual puck-drop `start_off`.

    Returns `{"status": "upcoming"|"live"|"final", "score": [h, a],
    "period": 1|2|3|"OT", "clock": "mm:ss", "scorers_so_far": [...]}`;
    `scorers_so_far` is the prefix of `box["goals"]` that has "happened"
    by `cursor` (full goal dicts, so a caller can resolve names/assists/
    strength itself).

    Monotonic in `cursor` by construction: for a fixed `box`/`start_off`,
    virtual elapsed time `t = cursor - start_off` is itself monotonic in
    `cursor`, status is a non-decreasing function of `t` (upcoming <= live
    <= final), and the live score only accumulates more of the same sorted
    goal list as `t` grows. At `t >= game end` the score becomes
    `box["final"]` verbatim (never less than the last live partial, since
    a shootout winner not present in the timed goal list can only add to
    it) — so `reveal(...) == status final, score == box["final"]` for
    every `cursor >= start_off + game-end`.
    """
    t = cursor - start_off
    end = _game_end_secs(box)
    if t <= 0:
        return {"status": "upcoming", "score": [0, 0], "period": 1,
                "clock": "0:00", "scorers_so_far": []}
    if t >= end:
        h, a = box.get("final", (0, 0))
        goals = box.get("goals", [])
        if box.get("so"):
            period, clock = "OT", _fmt_clock(OT_SECS)
        elif goals:
            last = max(goals, key=_goal_abs_secs)
            period, clock = last.get("period", 3), last.get("clock", "20:00")
        else:
            period, clock = 3, "20:00"
        return {"status": "final", "score": [h, a], "period": period,
                "clock": clock, "scorers_so_far": list(goals)}
    goals = sorted(box.get("goals", []), key=_goal_abs_secs)
    score = [0, 0]
    so_far = []
    for g in goals:
        if _goal_abs_secs(g) > t:
            break
        score[0 if g.get("t") == "h" else 1] += 1
        so_far.append(g)
    if t < REG_SECS:
        period = t // PERIOD_SECS + 1
        clock = _fmt_clock(t - (period - 1) * PERIOD_SECS)
    else:
        period = "OT"
        clock = _fmt_clock(min(t - REG_SECS, OT_SECS))
    return {"status": "live", "score": score, "period": period,
            "clock": clock, "scorers_so_far": so_far}


# --- shared player-lookup normalizer (mirrors stats.py's private _lookup)

def _plook(players: dict) -> dict:
    if isinstance(players, dict) and isinstance(players.get("players"), dict):
        return players["players"]
    return players or {}


def _scorer_phrase(box: dict, plook: dict) -> list:
    """Named, order-preserving scorer callouts for one box: 'Name', 'Name
    twice', 'Name 3 times' — the shape both the scores desk and the
    intermission sheet narrate off of."""
    tally, order = {}, []
    for g in box.get("goals", []):
        pid = g.get("scorer")
        if not pid:
            continue
        name = plook.get(pid, {}).get("name", pid)
        if name not in tally:
            order.append(name)
        tally[name] = tally.get(name, 0) + 1
    out = []
    for name in order:
        n = tally[name]
        out.append(name if n == 1 else f"{name} twice" if n == 2
                   else f"{name} {n} times")
    return out


def _start_off(date: str, home: str, away: str) -> int:
    """Seeded virtual puck-drop offset, 0-90 minutes (G1). See the module
    docstring's friction note on the seed string omitting `season`."""
    return random.Random(f"drop:{date}:{home}-{away}").randint(0, 5400)


def intermission_sheet(date: str, cursor: int, boxes: list, stats: dict,
                        players: dict) -> dict:
    """The intermission / around-the-league beat. `boxes` is tonight's
    off-air slate (the `games` list of a box/{date}.json shard); every row
    is produced by `reveal` so a game airs as in-progress or final
    consistently with the scores desk and export() at the same `cursor`.
    Returns `{"around": [...], "leaders": [...], "race_note": "..."}`.
    """
    plook = _plook(players)
    around = []
    for box in boxes:
        home, away = box.get("home"), box.get("away")
        rv = reveal(box, _start_off(date, home, away), cursor)
        row = {"home": home, "away": away, "status": rv["status"],
               "score": rv["score"], "period": rv["period"],
               "clock": rv["clock"],
               "scorers": _scorer_phrase({"goals": rv["scorers_so_far"]}, plook)}
        if rv["status"] == "final":
            row["ot"] = bool(box.get("ot"))
            row["shots"] = box.get("shots")
        around.append(row)

    top = leaguestats.leaders(stats, players, "p", 5)
    if len(top) >= 2:
        gap = top[0]["p"] - top[1]["p"]
        race_note = (f"{top[0]['name']} leads the scoring race by {gap} "
                     f"over {top[1]['name']}." if gap > 0 else
                     f"{top[0]['name']} and {top[1]['name']} are tied atop "
                     "the scoring race.")
    elif top:
        race_note = f"{top[0]['name']} paces the league in scoring."
    else:
        race_note = "The scoring race hasn't taken shape yet."
    return {"around": around, "leaders": top, "race_note": race_note}


def scores_desk(date: str, boxes: list, players: dict, n: int = 5,
                first: tuple = ()) -> str:
    """One narratable wire-copy line, named scorers included: 'Last night
    in the league: Regrets 4, Fog Advisories 2 — Ostberg twice; ...'.
    `first` = team keys whose games LEAD the desk (the tracked franchises —
    the station's editorial voice and its scoreboard must agree on who we
    follow)."""
    plook = _plook(players)
    ordered = sorted(list(boxes),
                     key=lambda b: 0 if (b.get("home") in first
                                         or b.get("away") in first) else 1)
    games = []
    for box in ordered[:n]:
        h, a = box.get("final", (0, 0))
        tag = " (OT)" if box.get("ot") else " (SO)" if box.get("so") else ""
        scorers = _scorer_phrase(box, plook)
        tail = f" — {', '.join(scorers)}" if scorers else ""
        games.append(f"{box.get('away', 'the road team')} {a}, "
                     f"{box.get('home', 'the home team')} {h}{tag}{tail}")
    if not games:
        return f"No other league games to report for {date}."
    return "Last night in the league: " + "; ".join(games) + "."


# --- pregame blocks (LINES / INJURY REPORT / LEADERS / MILESTONE WATCH)

_F_SLOTS = ("F1", "F2", "F3", "F4")
_D_SLOTS = ("D1", "D2", "D3")
_MILE_G = (20, 30, 40, 50)
_MILE_P = (50, 75, 100)


def _lines_block(roster: dict, plook: dict, team_name: str) -> str:
    by_slot: dict = {}
    for pid in roster.get("ids") or []:
        info = plook.get(pid)
        if not info:
            continue
        by_slot.setdefault(info.get("slot", ""), []).append(info["name"])
    fwd = " | ".join(f"{s} {'-'.join(by_slot[s])}" for s in _F_SLOTS if by_slot.get(s))
    dpair = " | ".join(f"{s} {'-'.join(by_slot[s])}" for s in _D_SLOTS if by_slot.get(s))
    goalie = roster.get("goalie", "")
    backup = roster.get("backup")
    g_txt = f"G {goalie}" + (f" (backup {backup})" if backup else "")
    body = " | ".join(x for x in (fwd, dpair, g_txt) if x)
    return f"{team_name}: {body}"


def _injury_report(out2: dict, plook: dict, team_key) -> list:
    lines = []
    for pid, rec in (out2 or {}).items():
        info = plook.get(pid) or {}
        team = info.get("team", pid.split("-")[0])
        if team != team_key:
            continue
        name = info.get("name", pid)
        note = rec.get("note", "day-to-day")
        games = rec.get("games")
        tail = (f", out ~{games} more game{'s' if games != 1 else ''}"
                if games else "")
        lines.append(f"{name}, {note}{tail}")
    return lines


def _milestone_watch(stats: dict, plook: dict, ids: list) -> list:
    """Forward-looking ('X needs N for a milestone') — distinct from
    stats.milestones(), which reports milestones a just-folded box already
    hit. Pregame watches for what's imminent, not what's happened."""
    lines = []
    for pid in ids:
        arr = stats.get("skaters", {}).get(pid)
        info = plook.get(pid)
        if not arr or not info:
            continue
        g, a = arr[1], arr[2]
        pts = g + a
        near_g = [m for m in _MILE_G if 0 < m - g <= 3]
        if near_g:
            m = near_g[0]
            lines.append(f"{info['name']} needs {m - g} for {m} goals on the season")
            continue
        near_p = [m for m in _MILE_P if 0 < m - pts <= 5]
        if near_p:
            m = near_p[0]
            lines.append(f"{info['name']} needs {m - pts} for {m} points on the season")
    return lines


def pregame_blocks(game: dict, players: dict, stats: dict, out2: dict) -> str:
    """The LINES / INJURY REPORT / LEADERS / MILESTONE WATCH text blocks
    for tonight's game dict (already-dressed rosters, minimal §4 shape:
    `rosters[side]` carries `skaters`/`goalie`/`ids`/`weights`/`backup`)."""
    plook = _plook(players)
    home_r = game.get("rosters", {}).get("home", {})
    away_r = game.get("rosters", {}).get("away", {})
    lines_txt = "\n".join([
        "LINES:",
        _lines_block(home_r, plook, game.get("home", "Home")),
        _lines_block(away_r, plook, game.get("away", "Away")),
    ])

    inj = (_injury_report(out2, plook, game.get("home_key"))
           + _injury_report(out2, plook, game.get("away_key")))
    inj_txt = ("INJURY REPORT: "
               + ("; ".join(inj) if inj else "full lineups tonight, nobody new to report"))

    top_pts = leaguestats.leaders(stats, players, "p", 5)
    top_g = leaguestats.leaders(stats, players, "sv%", 1)
    lead_parts = [f"{r['name']} ({r['p']} pts, {r['team']})" for r in top_pts]
    if top_g:
        g0 = top_g[0]
        lead_parts.append(f"top netminder {g0['name']} .{int(g0['sv%'] * 1000):03d}")
    lead_txt = ("LEADERS: "
                + (", ".join(lead_parts) if lead_parts
                   else "the season is too young for a leaderboard"))

    watch_ids = list(home_r.get("ids") or []) + list(away_r.get("ids") or [])
    watch = _milestone_watch(stats, plook, watch_ids)
    watch_txt = ("MILESTONE WATCH: "
                 + ("; ".join(watch) if watch else "nothing imminent tonight"))

    return f"{lines_txt}\n{inj_txt}\n{lead_txt}\n{watch_txt}"


# --- postgame QUOTE GROUNDING


# Deliberately NOT "even strength"/"power play"/"empty net": those phrases
# are exactly what scoreguard's state-claim check (§8: _PP/_EN/_TIE_SOFT)
# treats as an unverified live claim (a bare "even" reads as a tie claim;
# "power play"/"empty net" read as a claim needing this chunk's pp_span/
# en_span, which a frozen postgame board never carries). A recap after the
# horn is retrospective, not a live state claim, so it's phrased to convey
# the same fact without the trigger words (G3 caught this).
_STR_NAME = {"EV": "at full strength", "PP": "up a skater",
             "PK": "down a skater", "SH": "down a skater",
             "EN": "with the net vacated"}


def _name_by_id(game: dict) -> dict:
    """Skater id->name, both sides, from the dress()-shape parallel
    `skaters`/`ids` arrays already sitting in `game["rosters"]` — the
    bridge that lets postgame_quote_grounding resolve box-shape player IDs
    without a `players` parameter (see module docstring friction note)."""
    m = {}
    for side in ("home", "away"):
        r = game.get("rosters", {}).get(side, {})
        for pid, name in zip(r.get("ids") or [], r.get("skaters") or []):
            m[pid] = name
    return m


def _goal_lines(game: dict, box: dict) -> list:
    name_by_id = _name_by_id(game)
    out = []
    for g in box.get("goals", []):
        scorer = name_by_id.get(g.get("scorer"), g.get("scorer"))
        assists = [name_by_id.get(a, a) for a in (g.get("a1"), g.get("a2")) if a]
        atxt = (f", assist{'s' if len(assists) > 1 else ''} to "
                f"{' and '.join(assists)}" if assists else " (unassisted)")
        strn = _STR_NAME.get(g.get("str", "EV"), g.get("str", "EV"))
        out.append(f"P{g.get('period', '?')} {g.get('clock', '')} — "
                   f"{scorer}{atxt}, {strn}")
    return out


def _save_counts(game: dict, box: dict) -> list:
    shots, final = box.get("shots"), box.get("final")
    if not (shots and final):
        return []
    h_shots, a_shots = shots
    h_goals, a_goals = final
    home_g = game.get("rosters", {}).get("home", {}).get("goalie")
    away_g = game.get("rosters", {}).get("away", {}).get("goalie")
    out = []
    if away_g:
        out.append(f"{away_g}: {max(h_shots - h_goals, 0)} saves on {h_shots} shots")
    if home_g:
        out.append(f"{home_g}: {max(a_shots - a_goals, 0)} saves on {a_shots} shots")
    return out


def _season_lines(game: dict, final: dict, box: dict, stats: dict) -> list:
    id_by_name = {name: pid for pid, name in _name_by_id(game).items()}
    goalie_pid = {
        game.get("rosters", {}).get("home", {}).get("goalie"): box.get("goalies", {}).get("h"),
        game.get("rosters", {}).get("away", {}).get("goalie"): box.get("goalies", {}).get("a"),
    }
    out = []
    for name in final.get("stars", []):
        pid = id_by_name.get(name)
        if pid and pid in stats.get("skaters", {}):
            gp, g, a, pim, gwg, hat = stats["skaters"][pid]
            out.append(f"{name} now has {g + a} points ({g}g, {a}a) on the season")
            continue
        gpid = goalie_pid.get(name)
        if gpid and gpid in stats.get("goalies", {}):
            gp, w, l, otl, sa, sv, so = stats["goalies"][gpid]
            out.append(f"{name} is {w}-{l}-{otl} on the season")
    return out


def postgame_quote_grounding(game: dict, final: dict, box: dict, stats: dict) -> str:
    """The QUOTE GROUNDING block: goal list with strengths/clocks, save
    counts per goalie, each star's season line. `final` is the livegame
    final dict (h/a/ot/so/stars/shots); `box` is the same game normalized
    to the frozen §2 box shape (goal-by-goal, goalie ids) so this shares
    one goal-list format with every off-air game's box."""
    goals = _goal_lines(game, box)
    saves = _save_counts(game, box)
    season = _season_lines(game, final, box, stats)
    parts = ["QUOTE GROUNDING:",
             "Goals: " + ("; ".join(goals) if goals else "none"),
             "Saves: " + ("; ".join(saves) if saves else "n/a")]
    if season:
        parts.append("Season lines: " + "; ".join(season))
    coaches = game.get("coaches")   # Gate-2 dark feature; additive, no-op until populated
    if isinstance(coaches, dict):
        recs = []
        for side in ("home", "away"):
            c = coaches.get(side) or coaches.get(game.get(f"{side}_key", ""))
            if isinstance(c, dict) and c.get("name"):
                recs.append(f"{c['name']} ({c.get('record', 'record TBD')})")
        if recs:
            parts.append("Coaches: " + "; ".join(recs))
    return "\n".join(parts)
