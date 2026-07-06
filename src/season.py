"""Center Ice league engine — a full 32-team league, deterministically simulated.

Code decides everything factual: the league slate, every score, streaks,
standings, tonight's broadcast game. The writer only NARRATES what it is
handed, so scores never drift and the standings are real across months.

Structure mirrors the real thing: 2 conferences x 2 divisions x 8 teams,
82-game seasons. We broadcast the two tracked franchises (Wednesday and
Saturday); the other 30 teams play their own games every night and their
results exist — the booth can check in on any of them.

Every result is seeded by (season, date, matchup), so restarts regenerate
identical games. State lives in season.json.
"""
from __future__ import annotations

import json
import random
from datetime import date as _date, timedelta
from pathlib import Path

_PATH = Path("season.json")

# conference -> division -> teams. Ours are mtl (Boreal/East) + nyg (Gridiron/East).
LEAGUE = {
    "Eastern": {
        "Boreal": [
            ("mtl", "Montreal Apologies"), ("tbr", "Thunder Bay Regrets"),
            ("hfx", "Halifax Fog Advisories"), ("trr", "Trois-Rivieres Third Rivers"),
            ("gan", "Gander Layovers"), ("bur", "Burlington Passive Aggression"),
            ("pmc", "Providence Mild Concern"), ("stj", "Saint John Tide Charts"),
        ],
        "Gridiron": [
            ("nyg", "New York Gridlock"), ("yon", "Yonkers Honkers"),
            ("uti", "Utica Umbrellas"), ("sch", "Schenectady Sirens"),
            ("alb", "Albany Administrative Delays"), ("scr", "Scranton Small Talk"),
            ("bal", "Baltimore Polite Disagreements"), ("rich", "Richmond Long Stories"),
        ],
    },
    "Western": {
        "Prairie": [
            ("ssk", "Saskatoon Static"), ("wpg", "Winnipeg Wind Chill"),
            ("mjm", "Moose Jaw Moose (singular)"), ("reg", "Regina Reasonable Doubts"),
            ("bra", "Brandon Second Opinions"), ("far", "Fargo Firm Handshakes"),
            ("bis", "Bismarck Broken Thermostats"), ("dul", "Duluth Dial Tones"),
        ],
        "Pacific": [
            ("vic", "Victoria Passive Voices"), ("kam", "Kamloops Loose Gravel"),
            ("spo", "Spokane Spare Keys"), ("eug", "Eugene Unsolicited Advice"),
            ("bak", "Bakersfield Long Yawns"), ("fre", "Fresno Filing Errors"),
            ("tuc", "Tucson Dry Heats"), ("boi", "Boise Beige Alerts"),
        ],
    },
}

TRACKED = {
    "mtl": {"arena": "the Pardon Centre",
            "flavor": "sorry about the forecheck; historically good, "
                      "emotionally burdened"},
    "nyg": {"arena": "Standstill Garden",
            "flavor": "aggressive, perpetually delayed, honks at the referee"},
}

SEASON_GAMES = 82
_RIVALRY_EVERY = 7   # every Nth broadcast is Apologies vs Gridlock

_ALL = {k: n for conf in LEAGUE.values() for div in conf.values() for k, n in div}
_DIV_OF = {k: dname for conf in LEAGUE.values()
           for dname, div in conf.items() for k, _ in div}


def _strength(key: str, season: int) -> float:
    """Hidden per-season team quality in [0.30, 0.70] — stable all season."""
    return 0.30 + random.Random(f"strength:{season}:{key}").random() * 0.40


def _load() -> dict:
    try:
        if _PATH.exists():
            st = json.loads(_PATH.read_text())
            if "league" in st:
                return st
    except Exception:
        pass
    return {"season": 1, "game_no": 0, "sim_through": "",
            "league": {k: {"w": 0, "l": 0, "otl": 0, "streak": 0, "gp": 0}
                       for k in _ALL},
            "recent_opponents": [], "last_result": "",
            "games": {}, "slates": {}}


def _save(st: dict) -> None:
    tmp = _PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2))
    tmp.replace(_PATH)


def _apply(st: dict, hk: str, ak: str, hg: int, ag: int, ot: bool) -> None:
    for key, won in ((hk, hg > ag), (ak, ag > hg)):
        t = st["league"][key]
        t["gp"] += 1
        if won:
            t["w"] += 1
            t["streak"] = max(1, t["streak"] + 1)
        elif ot:
            t["otl"] += 1
            t["streak"] = min(-1, t["streak"] - 1)
        else:
            t["l"] += 1
            t["streak"] = min(-1, t["streak"] - 1)


def _score(rng: random.Random, ph: float) -> tuple[int, int, bool]:
    hg = rng.choice([1, 2, 2, 3, 3, 3, 4, 4, 5])
    ag = rng.choice([1, 2, 2, 3, 3, 4, 4, 5])
    if hg == ag:
        if rng.random() < ph:
            hg += 1
        else:
            ag += 1
    ot = abs(hg - ag) == 1 and rng.random() < 0.3
    return hg, ag, ot


def _sim_day(st: dict, day: str) -> None:
    """Simulate the league slate for one date (our teams excluded — their
    games only happen through tonight())."""
    if day in st["slates"]:
        return
    rng = random.Random(f"slate:{st['season']}:{day}")
    # tracked teams play OFF-AIR league games too (a real team plays ~3.5 a
    # week; we only broadcast two) — but never on broadcast nights (Wed/Sat)
    broadcast_night = _date.fromisoformat(day).weekday() in (2, 5)
    pool = [k for k in _ALL
            if st["league"][k]["gp"] < SEASON_GAMES
            and not (broadcast_night and k in TRACKED)]
    rng.shuffle(pool)
    results = []
    # ~10 league games a night: every team plays roughly every other night
    for hk, ak in zip(pool[0::2], pool[1::2]):
        if len(results) >= 10:
            break
        ph = 0.5 + (_strength(hk, st["season"]) - _strength(ak, st["season"])) + 0.05
        hg, ag, ot = _score(rng, min(max(ph, 0.15), 0.85))
        _apply(st, hk, ak, hg, ag, ot)
        results.append([hk, ak, hg, ag, ot])
    st["slates"][day] = results
    # keep the slate archive bounded
    if len(st["slates"]) > 30:
        for old in sorted(st["slates"])[:-30]:
            del st["slates"][old]


def _sim_through(st: dict, day: str) -> None:
    """Catch the league up to `day` (idempotent, deterministic)."""
    start = st["sim_through"] or day
    d = _date.fromisoformat(start)
    end = _date.fromisoformat(day)
    while d <= end:
        _sim_day(st, d.isoformat())
        d += timedelta(days=1)
    if day > st["sim_through"]:
        st["sim_through"] = day


def tonight(air_date: str) -> dict:
    """The broadcast game for this date. Idempotent: same date -> same game."""
    st = _load()
    _sim_through(st, air_date)
    if air_date in st["games"]:
        _save(st)
        return st["games"][air_date]

    rng = random.Random(f"center-ice:{st['season']}:{air_date}")
    game_no = st["game_no"] + 1
    rivalry = game_no % _RIVALRY_EVERY == 0
    ours = "mtl" if game_no % 2 else "nyg"

    if rivalry:
        hk, ak = ("mtl", "nyg") if game_no % 2 else ("nyg", "mtl")
    else:
        hk = ours
        division_mates = [k for k in _ALL if k not in TRACKED]
        pool = [k for k in division_mates
                if _ALL[k] not in st["recent_opponents"][-4:]]
        # home games mostly vs the division, like a real schedule
        div_pool = [k for k in pool if _DIV_OF[k] == _DIV_OF[hk]]
        ak = rng.choice(div_pool if div_pool and rng.random() < 0.6 else pool)

    ph = 0.5 + (_strength(hk, st["season"]) - _strength(ak, st["season"])) + 0.05
    hg, ag, ot = _score(rng, min(max(ph, 0.15), 0.85))

    game = {"game_no": game_no, "date": air_date, "rivalry": rivalry,
            "season": st["season"],
            "home": _ALL[hk], "away": _ALL[ak], "home_key": hk, "away_key": ak,
            "arena": TRACKED.get(hk, {}).get("arena", "the road"),
            "final": [hg, ag], "ot": ot, "recorded": False}
    st["games"][air_date] = game
    st["game_no"] = game_no
    if len(st["games"]) > 90:
        for old in sorted(st["games"])[:-90]:
            del st["games"][old]
    if not rivalry:
        st["recent_opponents"] = (st["recent_opponents"] + [_ALL[ak]])[-8:]
    _save(st)
    return game


def tick(air_date: str) -> None:
    """Advance the league to today (off-air slates) and republish the site
    data — called daily so standings stay fresh between broadcasts."""
    st = _load()
    _sim_through(st, air_date)
    _save(st)
    export()


def record(air_date: str) -> str | None:
    """Fold tonight's result into the standings (idempotent). Returns a
    one-line result for station lore. Rolls the season over at 82 games."""
    st = _load()
    game = st["games"].get(air_date)
    if not game or game.get("recorded"):
        return None
    hg, ag = game["final"]
    _apply(st, game["home_key"], game["away_key"], hg, ag, game["ot"])
    winner = game["home"] if hg > ag else game["away"]
    loser = game["away"] if hg > ag else game["home"]
    line = (f"Center Ice: the {winner} beat the {loser} "
            f"{max(hg, ag)}-{min(hg, ag)}{' in overtime' if game['ot'] else ''}")
    game["recorded"] = True
    st["last_result"] = line
    if any(st["league"][k]["gp"] >= SEASON_GAMES for k in TRACKED):
        st["season"] += 1
        st["game_no"] = 0
        st["sim_through"] = ""
        st["slates"] = {}
        st["league"] = {k: {"w": 0, "l": 0, "otl": 0, "streak": 0, "gp": 0}
                        for k in _ALL}
        line += f" — and that's the season; season {st['season']} starts next game"
    _save(st)
    return line


# --- event-level game simulation: the factual play-by-play the booth narrates

_FIRST = ("Doug Marty Gilles Pete Anders Toivo Brick Lars Chuck Remy Sven "
          "Gord Wally Jean-Guy Boone Alexei Dmitri Cliff Norm Tug Moose "
          "Stanislav Bert Olaf Petr Randy Curtis Yvon Merle Stu").split()
_LAST = ("Bouchard Larsson Petrenko Gustafsson Tremblay Kowalski O'Rourke "
         "Vachon Lindqvist Dubois Sorensen Mackenzie Novak Fitzpatrick "
         "Berube Halloran Jurgens Pelletier Sopel Grimsby Thibodeau Vrana "
         "Ostberg Callahan Demers Sikora Brandt Leclair Mulligan Ruud").split()

_PENALTIES = ["tripping", "hooking", "interference", "delay of game",
              "too many men on the ice", "high-sticking", "holding",
              "excessive apologizing", "slashing", "unsportsmanlike conduct",
              "embellishment", "arguing with the zamboni"]

_INJURY_NOTES = ["day-to-day, lower body", "day-to-day, upper body",
                 "questionable, general body", "day-to-day, morale"]

_REFS = ["Referee Don Pelkey", "Referee Marcel Aube", "Referee Sandy Kowalchuk",
         "Referee Wes Trudel", "Referee Pat Onions", "Referee Gil Ferland"]


def _roster(key: str, season: int) -> dict:
    """Deterministic per-season roster: 8 notable skaters + a goalie."""
    rng = random.Random(f"roster:{season}:{key}")
    names, used = [], set()
    while len(names) < 9:
        n = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
        if n not in used:
            used.add(n)
            names.append(n)
    return {"skaters": names[:8], "goalie": names[8]}


def _clock(rng: random.Random) -> str:
    return f"{rng.randint(0, 19)}:{rng.randint(0, 59):02d}"


def simulate(game: dict) -> dict:
    """The full factual event log for a game — goals with scorers/assists/
    times/strength, penalties, refs, goalies, shots, three stars, the odd
    injury. Deterministic: same game dict -> same events."""
    rng = random.Random(f"events:{game['season']}:{game['date']}")
    hk, ak = game["home_key"], game["away_key"]
    hr, ar = _roster(hk, game["season"]), _roster(ak, game["season"])
    hg, ag = game["final"]
    periods = {1: [], 2: [], 3: [], "OT": []}

    # penalties first (power plays explain goals)
    pens = []
    for _ in range(rng.randint(3, 7)):
        against_home = rng.random() < 0.5
        team = game["home"] if against_home else game["away"]
        player = rng.choice((hr if against_home else ar)["skaters"])
        pens.append({"period": rng.randint(1, 3), "clock": _clock(rng),
                     "team": team, "player": player,
                     "call": rng.choice(_PENALTIES), "min": 2})

    # distribute goals across periods (last goal in OT if applicable)
    def _spread(n, ot_last):
        ps = [rng.choice([1, 1, 2, 2, 2, 3, 3, 3]) for _ in range(n)]
        if ot_last and ps:
            ps[-1] = "OT"
        return ps

    goals = []
    home_periods = _spread(hg, game["ot"] and hg > ag)
    away_periods = _spread(ag, game["ot"] and ag > hg)
    for team_name, roster, opp_pens, plist in (
            (game["home"], hr, [p for p in pens if p["team"] == game["away"]], home_periods),
            (game["away"], ar, [p for p in pens if p["team"] == game["home"]], away_periods)):
        stars = roster["skaters"][:3]
        for p in plist:
            scorer = rng.choice(stars + stars + roster["skaters"])  # stars score more
            assist = rng.choice([None] + roster["skaters"])
            strength = "PP" if opp_pens and rng.random() < 0.3 else "EV"
            goals.append({"period": p, "clock": _clock(rng), "team": team_name,
                          "scorer": scorer,
                          "assist": assist if assist != scorer else None,
                          "strength": strength})
    def _secs(c: str) -> int:
        m, s = c.split(":")
        return int(m) * 60 + int(s)
    goals.sort(key=lambda g: (4 if g["period"] == "OT" else g["period"],
                              _secs(g["clock"])))

    shots_h = max(hg, rng.randint(22, 38))
    shots_a = max(ag, rng.randint(20, 36))
    injury = None
    if rng.random() < 0.12:
        side = rng.random() < 0.5
        injury = {"player": rng.choice((hr if side else ar)["skaters"]),
                  "team": game["home"] if side else game["away"],
                  "note": rng.choice(_INJURY_NOTES),
                  "period": rng.randint(1, 3)}
    scorers = [g["scorer"] for g in goals]
    win_goalie = (hr if hg > ag else ar)["goalie"]
    stars3 = list(dict.fromkeys(scorers[::-1]))[:2] + [win_goalie]
    disputed = rng.choice(pens) if pens and rng.random() < 0.6 else None

    return {"goals": goals, "penalties": pens, "injury": injury,
            "shots": [shots_h, shots_a],
            "goalies": {game["home"]: hr["goalie"], game["away"]: ar["goalie"]},
            "refs": rng.sample(_REFS, 2), "three_stars": stars3,
            "disputed": disputed,
            "attendance": rng.randint(9000, 18000) + rng.choice([0, 3, 7, 12])}


def _event_sheet(game: dict) -> str:
    """Compact factual play-by-play sheet for the writer to narrate."""
    ev = simulate(game)

    def _secs(c: str) -> int:
        m, s = c.split(":")
        return int(m) * 60 + int(s)

    out = []
    for p in (1, 2, 3, "OT"):
        timed = []
        for g in ev["goals"]:
            if g["period"] == p:
                a = f" (assist {g['assist']})" if g["assist"] else " (unassisted)"
                pp = " on the POWER PLAY" if g["strength"] == "PP" else ""
                timed.append((_secs(g["clock"]),
                              f"GOAL {g['team']}: {g['scorer']}{a}{pp}, {g['clock']}"))
        for pen in ev["penalties"]:
            if pen["period"] == p:
                timed.append((_secs(pen["clock"]),
                              f"PENALTY {pen['team']}: {pen['player']}, "
                              f"{pen['min']} min for {pen['call']}, {pen['clock']}"))
        if ev["injury"] and ev["injury"]["period"] == p:
            i = ev["injury"]
            timed.append((1200, f"INJURY {i['team']}: {i['player']} leaves, "
                                f"listed {i['note']}"))
        timed.sort()
        lines = [t[1] for t in timed]
        if lines or p != "OT":
            out.append(f"Period {p}: " + ("; ".join(lines) if lines else
                                          "no scoring, no penalties"))
    d = ev["disputed"]
    return ("EVENT SHEET (narrate EXACTLY these events in order — you may add "
            "color, saves, and near-misses between them, but no other goals, "
            "penalties, or injuries; game clocks like '14:32 of the second' "
            "are correct usage):\n"
            + "\n".join(out) + "\n"
            f"Shots: {game['home']} {ev['shots'][0]}, {game['away']} {ev['shots'][1]}. "
            f"Goalies: {ev['goalies'][game['home']]} vs {ev['goalies'][game['away']]}. "
            f"Officials: {', '.join(ev['refs'])}."
            + (f" The {d['call']} call on {d['player']} is DISPUTED — the booth "
               "disagrees about it all night." if d else "")
            + f" Three stars: {', '.join(ev['three_stars'])}. "
            f"Attendance {ev['attendance']:,}.")


def export(path: str = "/var/www/bestairadio/league.json") -> None:
    """Publish the league to the website: standings, tonight/last game with
    its event log, recent around-the-league scores. Best-effort."""
    try:
        st = _load()
        latest_date = max(st["games"]) if st["games"] else None
        game = st["games"].get(latest_date) if latest_date else None
        divisions = {}
        for conf in LEAGUE.values():
            for dname in conf:
                keys = [k for k, d in _DIV_OF.items() if d == dname]
                keys.sort(key=lambda k: (-_pts(st["league"][k]),
                                         st["league"][k]["l"]))
                divisions[dname] = [
                    {"team": _ALL[k], "tracked": k in TRACKED,
                     **{f: st["league"][k][f] for f in ("gp", "w", "l", "otl")},
                     "pts": _pts(st["league"][k])} for k in keys]
        slate = st["slates"].get(st["sim_through"], [])
        out = {"season": st["season"], "updated": st["sim_through"],
               "divisions": divisions, "last_result": st["last_result"],
               "broadcast": ({"date": game["date"], "home": game["home"],
                              "away": game["away"], "final": game["final"],
                              "ot": game["ot"], "arena": game["arena"],
                              "played": game["recorded"],
                              "events": simulate(game)} if game else None),
               "around": [{"home": _ALL[h], "away": _ALL[a],
                           "score": [hg, ag], "ot": o}
                          for h, a, hg, ag, o in slate]}
        p = Path(path)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(out))
        tmp.replace(p)
    except Exception:
        pass  # the website is decoration; the broadcast is the product


def _pts(t: dict) -> int:
    return 2 * t["w"] + t["otl"]


def _table(st: dict, div: str, top: int = 8) -> str:
    keys = [k for k, d in _DIV_OF.items() if d == div]
    keys.sort(key=lambda k: (-_pts(st["league"][k]), st["league"][k]["l"]))
    return ", ".join(f"{i+1}. {_ALL[k]} {_pts(st['league'][k])}pts"
                     for i, k in enumerate(keys[:top]))


def brief(game: dict) -> str:
    """The factual sheet the writer must narrate — not negotiate with."""
    st = _load()
    hg, ag = game["final"]
    hk = game["home_key"]
    our_divs = {_DIV_OF[k] for k in TRACKED}
    standings = " | ".join(f"{d}: {_table(st, d, 4)}" for d in sorted(our_divs))
    around = ""
    slate = st["slates"].get(game["date"], [])
    if slate:
        around = ("AROUND THE LEAGUE TONIGHT (for scoreboard check-ins, all "
                  "FINAL and factual): " +
                  "; ".join(f"{_ALL[a]} {agg} at {_ALL[h]} {hgg}"
                            f"{' (OT)' if o else ''}"
                            for h, a, hgg, agg, o in slate[:6]) + ".")
    streaks = []
    for k in TRACKED:
        s = st["league"][k]["streak"]
        if abs(s) >= 3:
            streaks.append(f"the {_ALL[k]} are on a {abs(s)}-game "
                           f"{'winning' if s > 0 else 'losing'} streak")
    t = st["league"][hk]
    return (
        f"TONIGHT'S GAME (game {game['game_no']} of the {SEASON_GAMES}-game "
        f"season {game['season']}"
        f"{', RIVALRY NIGHT' if game['rivalry'] else ''}): "
        f"the {game['away']} at the {game['home']} ({t['w']}-{t['l']}-{t['otl']}), "
        f"live from {game['arena']}.\n"
        f"THE FINAL SCORE IS PREDETERMINED AND NON-NEGOTIABLE: "
        f"{game['home']} {hg}, {game['away']} {ag}"
        f"{' — decided in OVERTIME' if game['ot'] else ''}. Structure the whole "
        "broadcast so the game genuinely arrives at exactly this score; goals "
        "may only happen where a beat says they happen, and the running score "
        "in every beat must be consistent with reaching this final.\n"
        f"DIVISION STANDINGS: {standings}.\n"
        + (f"STREAK WATCH: {'; '.join(streaks)}.\n" if streaks else "")
        + (f"LAST BROADCAST: {st['last_result']}.\n" if st["last_result"] else "")
        + around + "\n\n" + _event_sheet(game)
    )
