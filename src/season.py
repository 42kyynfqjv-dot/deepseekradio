"""Center Ice league state — a full 32-team league around the live engine.

Code decides everything factual. The BROADCAST game is rolled live by
src/livegame.py in lockstep with the show being generated — fresh entropy,
no predetermined outcome, the append-only log is the truth. This module owns
everything around that game: the league, the schedule, standings, rosters,
the out-list, the off-air slates (date-seeded on the SAME calibrated model —
nobody hears them unfold, and seeds self-heal), recording finals exactly
once, and publishing the website's league.json gated to AIR time so the
scorebug can never spoil the broadcast.

Structure mirrors the real thing: 2 conferences x 2 divisions x 8 teams,
82-game seasons. We broadcast the two tracked franchises (Wednesday and
Saturday); the other 30 teams play their own games every night.
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import time
from datetime import date as _date, timedelta
from pathlib import Path

from . import livegame

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
    # flavor is HOCKEY substance, not name-pun bait — the booth wore the
    # apology jokes out inside a week. The names carry themselves.
    "mtl": {"arena": "the Pardon Centre",
            "flavor": "historically proud, heavy forecheck, allergic to "
                      "praise; the oldest barn in the league"},
    "nyg": {"arena": "Standstill Garden",
            "flavor": "fast, furious, disciplined until the third period; "
                      "a crowd that arrives late and stays later"},
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
    # Try the live file, then .bak, then a fresh default — NEVER silently reset
    # a live season just because a cross-process reader caught a write window.
    for p in (_PATH, _PATH.with_suffix(".bak")):
        try:
            if p.exists():
                st = json.loads(p.read_text())
                if "league" in st:
                    if p is not _PATH:
                        print("  !! season.json unusable — recovered from .bak")
                    return st
        except Exception:
            continue
    return {"season": 1, "game_no": 0, "sim_through": "",
            "league": {k: {"w": 0, "l": 0, "otl": 0, "streak": 0, "gp": 0}
                       for k in _ALL},
            "recent_opponents": [], "last_result": "",
            "games": {}, "slates": {}, "out": {}}


def _save(st: dict) -> None:
    # copy (not rename) the live file to .bak so season.json NEVER disappears —
    # the scorebug publisher reads it every 30s from another process, and a
    # missing file would make it publish an all-zero league reset.
    tmp = _PATH.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(st, indent=2))
    if _PATH.exists():
        try:
            shutil.copy2(_PATH, _PATH.with_suffix(".bak"))
        except Exception:
            pass
    tmp.replace(_PATH)   # the single atomic mutation of the live path


def _league_v2(st: dict):
    """The v2 league runtime, or None. Gate lives in league.engine (ENABLED +
    VERIFIED hash). Any import/gate failure is a LOUD v1 — the proven path
    keeps the air."""
    try:
        from .league import engine
        if engine.v2_on(st["season"]):
            return engine
    except Exception as e:
        print(f"  !! league v2 unavailable ({e}) — v1 path")
    return None


def _apply(st: dict, hk: str, ak: str, hg: int, ag: int, ot: bool) -> None:
    """Fold one result. `ot` covers OT AND shootout losses — both earn the point."""
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


def _sim_day(st: dict, day: str) -> None:
    """Simulate the league slate for one date on the SAME calibrated model as
    the live engine (one model, two speeds), date-seeded: off-air games are
    never heard unfolding, and seeds self-heal against state loss."""
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
        hg, ag, ot, so = livegame.sim_instant(
            _strength(hk, st["season"]), _strength(ak, st["season"]), rng)
        _apply(st, hk, ak, hg, ag, ot or so)
        results.append([hk, ak, hg, ag, ot or so])
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


def _roster(key: str, season: int) -> dict:
    """Deterministic per-season roster: 8 notable skaters + a goalie."""
    rng = random.Random(f"roster:{season}:{key}")
    names, used = [], set()
    while len(names) < 9:
        n = f"{rng.choice(livegame.FIRST_NAMES)} {rng.choice(livegame.LAST_NAMES)}"
        if n not in used:
            used.add(n)
            names.append(n)
    return {"skaters": names[:8], "goalie": names[8]}


def _dress(st: dict, game: dict) -> None:
    """Attach everything the live engine and the booth need: strengths,
    out-list-filtered rosters, officials, color. None of it is an outcome —
    the outcome does not exist until the engine rolls it."""
    rng = random.Random(f"dress:{game['season']}:{game['date']}")
    outmap = st.setdefault("out", {})
    rosters, returning = {}, []
    for side, key in (("home", game["home_key"]), ("away", game["away_key"])):
        r = _roster(key, game["season"])
        lst = outmap.get(key, [])
        keep = [o for o in lst if o["until"] > game["game_no"]]
        returning += [o["player"] for o in lst
                      if o not in keep and o["player"] in r["skaters"]]
        outmap[key] = keep
        rosters[side] = {"skaters": [s for s in r["skaters"]
                                     if all(o["player"] != s for o in keep)],
                         "goalie": r["goalie"]}
    game["rosters"] = rosters
    game["returning"] = returning
    game["strength_home"] = _strength(game["home_key"], game["season"])
    game["strength_away"] = _strength(game["away_key"], game["season"])
    game["refs"] = rng.sample(livegame.REFS, 2)
    game["subplot"] = rng.choice(livegame.SUBPLOTS)
    game["attendance"] = rng.randint(9000, 18000) + rng.choice([0, 3, 7, 12])


def tonight_live(air_date: str) -> dict:
    """Tonight's broadcast matchup. Idempotent per date. The game dict
    carries NO final and NO ot flag — those keys are created by the engine's
    log at the moment they happen, and folded back here by record_live()."""
    st = _load()
    _sim_through(st, air_date)
    if air_date in st["games"]:
        game = st["games"][air_date]
        if not game.get("recorded"):     # strip any pre-rolled outcome (legacy)
            game.pop("final", None)
            game.pop("ot", None)
        if "rosters" not in game:
            _dress(st, game)
        _save(st)
        return game

    rng = random.Random(f"center-ice:{st['season']}:{air_date}")
    game_no = st["game_no"] + 1
    # v2: tonight's matchup comes from the REAL schedule matrix (the AIR-tagged
    # row); rivalry nights are the Crossover Series games the schedule pinned
    # to every 7th broadcast slot. v1 keeps the legacy rng selection.
    v2 = _league_v2(st)
    hk = ak = None
    if v2 is not None:
        try:
            sched = v2.load_side(f"schedule-s{st['season']}.json")
            for row in (sched or {}).get("days", {}).get(air_date, []):
                if len(row) > 2 and row[2] == "AIR":
                    hk, ak = row[0], row[1]
                    break
        except Exception as e:
            print(f"  !! v2 schedule lookup failed ({e}) — legacy matchup")
    if hk is not None:
        rivalry = hk in TRACKED and ak in TRACKED
    else:
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

    game = {"game_no": game_no, "date": air_date, "rivalry": rivalry,
            "season": st["season"],
            "home": _ALL[hk], "away": _ALL[ak], "home_key": hk, "away_key": ak,
            "arena": TRACKED.get(hk, {}).get("arena", "the road"),
            "recorded": False}
    _dress(st, game)
    if v2 is not None:
        try:  # deep rosters (18 skaters, lines, weights) + attribute strength;
            # refs/subplot/attendance/returning keep the v1 dressing above
            from .league import players as _plmod
            pl = v2.load_side(f"players-s{st['season']}.json")
            for side, key in (("home", hk), ("away", ak)):
                game["rosters"][side] = _plmod.dress(pl, key, air_date)
            game["strength_home"] = _plmod.team_strength(pl, {}, hk, False)
            game["strength_away"] = _plmod.team_strength(pl, {}, ak, False)
        except Exception as e:
            print(f"  !! v2 dressing failed ({e}) — v1 rosters stand")
        try:  # Gate 2 (economy): coach names, once minted, auto-activate
            # orchestrator's already-shipped "Coach's Corner" presser beat
            # (game.get("coaches") truthy gate) — additive, dark until the
            # sidecar exists.
            if (v2.SIDE / "ECON-ENABLED").exists():
                coaches_side = v2.load_side(f"coaches-s{st['season']}.json")
                c = (coaches_side or {}).get("coaches", {})
                hc = c.get(hk, {}).get("name")
                ac = c.get(ak, {}).get("name")
                if hc and ac:
                    game["coaches"] = {"home": hc, "away": ac}
        except Exception as e:
            print(f"  !! v2 coaches lookup failed ({e}) — presser beat stays dark")
    st["games"][air_date] = game
    st["game_no"] = game_no
    if len(st["games"]) > 90:
        for old in sorted(st["games"])[:-90]:
            del st["games"][old]
    if not rivalry:
        st["recent_opponents"] = (st["recent_opponents"] + [_ALL[ak]])[-8:]
    _save(st)
    return game


def record_live(air_date: str) -> str | None:
    """Fold the engine's final into the standings — the ONLY writer, exactly
    once (idempotency key: games[date]['recorded'] inside season.json, set in
    the same save that applies the result). Returns a lore line."""
    try:
        log = livegame.read_log(air_date)
    except ValueError as e:
        print(f"  !! {e}")
        return None
    if not log or not log["final"]:
        return None
    st = _load()
    game = st["games"].get(air_date)
    if not game or game.get("recorded"):
        return None
    # a stale-season game (a rollover happened between roll and this fold) must
    # never apply onto the freshly-zeroed new season — mark it done, don't fold
    if game.get("season") is not None and game["season"] != st["season"]:
        game["recorded"] = True
        _save(st)
        return None
    f = log["final"]
    hg, ag = f["h"], f["a"]
    _apply(st, game["home_key"], game["away_key"], hg, ag, f["ot"] or f["so"])
    game["recorded"] = True
    game["final"] = [hg, ag]
    game["ot"], game["so"] = f["ot"], f["so"]
    winner = game["home"] if hg > ag else game["away"]
    loser = game["away"] if hg > ag else game["home"]
    how = (" in overtime" if f["ot"] else " in a shootout" if f["so"] else "")
    line = (f"Center Ice: the {winner} beat the {loser} "
            f"{max(hg, ag)}-{min(hg, ag)}{how}")
    st["last_result"] = line
    # tonight's injuries become the out-list (the roll concerns FUTURE games)
    rng = random.Random(f"outlist:{game['season']}:{air_date}")
    for cid in log["order"]:
        for e in log["chunks"][cid]["events"]:
            if e["type"] != "injury":
                continue
            key = game["home_key"] if e["team"] == "home" else game["away_key"]
            lst = st.setdefault("out", {}).setdefault(key, [])
            if len(lst) < 2 and all(o["player"] != e["player"] for o in lst):
                lst.append({"player": e["player"],
                            "until": game["game_no"] + rng.randint(1, 3)})
    v2f = _league_v2(st)
    if v2f is not None:
        try:   # broadcast games join the season stat lines (exactly-once via
            v2f.fold_live(st, game, log)   # the recorded flag around us)
        except Exception as e:
            print(f"  (v2 live stats fold skipped: {e})")
    if any(st["league"][k]["gp"] >= SEASON_GAMES for k in TRACKED):
        # the RESET is air-gated in tick() (_maybe_rollover) — announcing the
        # finale is narration and may air now; zeroing the league before the
        # final horn reaches listeners is the spoiler this used to cause
        st["rolled_pending"] = True
        line += " — and that's the season; the offseason begins after tonight"
    _save(st)
    return line


def _maybe_rollover(st: dict) -> bool:
    """Execute a pending season reset ONLY once the finale's narration has
    AIRED (final_air_at in the past) and the game is recorded — the league
    can never zero itself under a broadcast listeners haven't heard yet.
    The trigger (rolled_pending) is set in record_live; execution lives here."""
    if not st.get("rolled_pending"):
        return False
    latest = max(st["games"]) if st["games"] else None
    if latest:
        g = st["games"][latest]
        if not g.get("recorded"):
            return False
        try:
            log = livegame.read_log(latest)
        except ValueError:
            log = None
        if log and log.get("final") is not None:
            at = log.get("final_air_at")
            if at is None or time.time() < at:
                return False
    st["season"] += 1
    st["game_no"] = 0
    st["sim_through"] = ""
    st["slates"] = {}
    st["out"] = {}
    st["rolled_pending"] = False
    st["league"] = {k: {"w": 0, "l": 0, "otl": 0, "streak": 0, "gp": 0}
                    for k in _ALL}
    print(f"  season rollover -> season {st['season']} (air-gated)")
    return True


def _reconcile(today: str) -> None:
    """No game may linger unfinished or unrecorded — recording must never
    depend on the broadcast loop reaching any particular line. Past-date
    non-final logs are force-finished with fresh entropy, loudly."""
    for p in sorted(livegame.DATA.glob("livegame-*.jsonl")):
        d = p.stem.replace("livegame-", "")
        try:
            log = livegame.read_log(d)
        except ValueError as e:
            print(f"  !! reconcile: {e}")
            continue
        if log is None:
            continue
        if not log["final"] and d < today:
            print(f"  !! reconcile: force-finishing abandoned game {d}")
            try:
                eng = livegame.LiveGame(log["game"])
                eng.finish_now("RECONCILE")
                eng.close()
                log = livegame.read_log(d)
            except RuntimeError:
                continue        # someone holds the lock; not ours to touch
        if log and log["final"]:
            record_live(d)      # no-ops unless unrecorded
        cutoff = (_date.fromisoformat(today) - timedelta(days=14)).isoformat()
        if d < cutoff:
            p.unlink(missing_ok=True)
            Path(str(p) + ".lock").unlink(missing_ok=True)


def tick(air_date: str) -> None:
    """Advance the league to today (off-air slates), sweep for abandoned or
    unrecorded games, republish the site data. Called every main-loop pass."""
    st = _load()
    v2 = _league_v2(st)
    if v2 is not None:
        try:
            v2.tick_v2(st, air_date, _apply, TRACKED)
        except Exception as e:
            print(f"  !! league v2 tick failed ({e}) — v1 fallback this pass")
            _sim_through(st, air_date)
        try:  # heal shardless v1-simmed days (pre-cutover tail) — idempotent
            v2.backfill_boxes(st)
        except Exception as e:
            print(f"  (league backfill skipped: {e})")
    else:
        _sim_through(st, air_date)
    if _maybe_rollover(st):
        # a fresh season resumes on v1 until the offseason machinery (gate 2)
        # mints the next season's sidecars — the mirror keeps standings whole
        _sim_through(st, air_date)
    _save(st)
    try:
        _reconcile(air_date)
    except Exception as e:
        print(f"  (reconcile skipped: {e})")
    export()


# --- the booth's factual sheets (never an outcome)

def _pts(t: dict) -> int:
    return 2 * t["w"] + t["otl"]


def _table(st: dict, div: str, top: int = 8) -> str:
    keys = [k for k, d in _DIV_OF.items() if d == div]
    keys.sort(key=lambda k: (-_pts(st["league"][k]), st["league"][k]["l"]))
    return ", ".join(f"{i+1}. {_ALL[k]} {_pts(st['league'][k])}pts"
                     for i, k in enumerate(keys[:top]))


def _rec(st: dict, key: str) -> str:
    t = st["league"][key]
    return f"{t['w']}-{t['l']}-{t['otl']}"


def pregame_brief(game: dict) -> str:
    """Everything true BEFORE the puck drops. Contains no final, no result,
    nothing about tonight's outcome — it does not exist yet."""
    st = _load()
    our_divs = {_DIV_OF[k] for k in TRACKED}
    standings = " | ".join(f"{d}: {_table(st, d, 4)}" for d in sorted(our_divs))
    slate = st["slates"].get(game["date"], [])
    around = "; ".join(f"{_ALL[a]} at {_ALL[h]}" for h, a, *_ in slate[:3])
    streaks = []
    for k in TRACKED:
        s = st["league"][k]["streak"]
        if abs(s) >= 3:
            streaks.append(f"the {_ALL[k]} are on a {abs(s)}-game "
                           f"{'winning' if s > 0 else 'losing'} streak")
    returning = (f"Back in the lineup tonight: {', '.join(game['returning'])}. "
                 if game.get("returning") else "")
    return (
        f"TONIGHT (game {game['game_no']} of the {SEASON_GAMES}-game season "
        f"{game['season']}{', RIVALRY NIGHT' if game['rivalry'] else ''}): "
        f"the {game['away']} ({_rec(st, game['away_key'])}) at the "
        f"{game['home']} ({_rec(st, game['home_key'])}), live from {game['arena']}. "
        "The game has NOT been played and does not exist yet: the score is 0-0, "
        "NOBODY knows the final, and you never predict one.\n"
        f"Starting goalies: {game['rosters']['home']['goalie']} for the "
        f"{game['home']}, {game['rosters']['away']['goalie']} for the "
        f"{game['away']}. Officials: {', '.join(game['refs'])}. {returning}"
        f"Attendance {game['attendance']:,}. Booth color subplot: {game['subplot']}.\n"
        f"DIVISION STANDINGS: {standings}.\n"
        + (f"STREAK WATCH: {'; '.join(streaks)}.\n" if streaks else "")
        + (f"HISTORY (last broadcast, already played): {st['last_result']}.\n"
           if st["last_result"] else "")
        + (f"Also around the league tonight: {around}." if around else "")
    )


def slate_scores(day: str) -> list[str]:
    """Human-readable finals from the day's off-air slate — the intermission
    and scores-desk sheet. Every pair here is already guard-whitelisted via
    context_pairs()."""
    st = _load()
    out = []
    for hk, ak, hg, ag, ot in st["slates"].get(day, []):
        out.append(f"{_ALL[ak]} {ag}, {_ALL[hk]} {hg}{' (OT)' if ot else ''}")
    return out


def context_pairs(game: dict) -> list:
    """Score pairs legitimately mentionable tonight with outside context —
    around-the-league finals and the last broadcast — for the scoreguard."""
    st = _load()
    pairs = [(hg, ag) for _h, _a, hg, ag, _o in
             st["slates"].get(game["date"], [])]
    m = re.search(r"(\d+)-(\d+)", st.get("last_result", ""))
    if m:
        pairs.append((int(m.group(1)), int(m.group(2))))
    return pairs


def postgame_brief(game: dict, final: dict) -> str:
    """The writer's sheet for the postgame call-in show — final now exists."""
    how = (" in OVERTIME" if final["ot"] else
           " in a SHOOTOUT" if final["so"] else "")
    return (f"THE GAME IS OVER — this is the POSTGAME CALL-IN SHOW. FINAL "
            f"(authoritative, never contradict): {game['home']} {final['h']}, "
            f"{game['away']} {final['a']}{how}. Shots: {game['home']} "
            f"{final['shots'][0]}, {game['away']} {final['shots'][1]}. Three "
            f"stars: {', '.join(final['stars'])}. Structure the outline as: "
            "callers reacting (delighted, devastated, weirdly neutral), the "
            "booth re-arguing one moment, standings implications, and looking "
            "ahead to the next broadcast. Do NOT replay the game beat by beat, "
            "do NOT invent goals, saves, or plays, and never alter the final.")


# --- website publishing, gated to AIR time (the scorebug must never spoil)

def _display_league(st: dict, game: dict | None, log: dict | None,
                    now: float) -> dict:
    """Standings as the LISTENER may know them: if tonight's final is folded
    but hasn't aired yet, un-apply it for display."""
    table = {k: dict(v) for k, v in st["league"].items()}
    # a folded result is hidden from the public standings until its final horn
    # has AIRED (been narrated and the audio reached listeners) — same gate the
    # event export uses, so the table and the scorebug never disagree
    final_aired = (log and log.get("final_air_at") is not None
                   and now >= log["final_air_at"])
    if (game and game.get("recorded") and log and log.get("final")
            and not final_aired):
        f = log["final"]
        for k, won in ((game["home_key"], f["h"] > f["a"]),
                       (game["away_key"], f["a"] > f["h"])):
            t = table.get(k)
            if not t or t["gp"] < 1:
                continue
            t["gp"] -= 1
            if won:
                t["w"] = max(0, t["w"] - 1)
            elif f["ot"] or f["so"]:
                t["otl"] = max(0, t["otl"] - 1)
            else:
                t["l"] = max(0, t["l"] - 1)
    return table


def _around_rows(st: dict, slate: list) -> list:
    """Around-the-league rows for the site; v2 enriches finals with named
    scorers from the day's box shard (same reveal status as today: finals)."""
    rows = [{"home": _ALL[h], "away": _ALL[a], "score": [hg, ag], "ot": o}
            for h, a, hg, ag, o in slate]
    try:
        v2 = _league_v2(st)
        if v2 is None:
            return rows
        shard = v2.load_side(f"box/{st['sim_through']}.json") or {}
        pl = v2.load_side(f"players-s{st['season']}.json") or {}
        names = {pid: p.get("name", pid)
                 for pid, p in pl.get("players", {}).items()}
        by_pair = {(g.get("home"), g.get("away")): g
                   for g in shard.get("games", [])}
        # during a broadcast, the site reveals other games on the BOOTH'S
        # clock (air-anchor.json, written at show open) — never a final the
        # desk is still calling live
        cursor = None
        anchor = v2.load_side("air-anchor.json")
        if anchor and anchor.get("date") == st["sim_through"] and \
                0 <= time.time() - anchor.get("t0", 0) < 5 * 3600:
            # trail by the generation buffer: the site tracks what has AIRED
            cursor = max(0, int(time.time() - anchor["t0"]
                                - anchor.get("lag", 0)))
        if cursor is not None:
            from .league import briefs as _lgb
            out_rows = []
            for row, (h, a, *_r) in zip(rows, slate):
                g = by_pair.get((h, a))
                if not g or "drop" not in g:
                    # no reveal info mid-broadcast: WITHHOLD — never show a
                    # final the booth hasn't reached (backfill heals the shard)
                    row.pop("scorers", None)
                    row["score"] = None
                    row["ot"] = False
                    row["status"] = "upcoming"
                    out_rows.append(row)
                    continue
                rv = _lgb.reveal(g, g["drop"], cursor)
                if rv.get("status") == "upcoming":
                    # a real out-of-town board LISTS tonight's games before
                    # they start — matchup visible, score withheld (the booth
                    # may mention the game exists; nothing to spoil)
                    row.pop("scorers", None)
                    row["score"] = None
                    row["ot"] = False
                    row["status"] = "upcoming"
                    out_rows.append(row)
                    continue
                row["score"] = rv.get("score", row["score"])
                row["status"] = rv.get("status")
                if rv.get("status") == "live":
                    row["ot"] = False
                    row["period"] = rv.get("period")
                    row["clock"] = rv.get("clock")
                    sc = rv.get("scorers_so_far") or []
                    row["scorers"] = [names.get(s, s) for s in sc][:3]
                    out_rows.append(row)
                    continue
                out_rows.append(row)
            return out_rows
        for row, (h, a, *_r) in zip(rows, slate):
            g = by_pair.get((h, a))
            if not g:
                continue
            tally: dict = {}
            for goal in g.get("goals", []):
                s = goal.get("scorer")
                tally[s] = tally.get(s, 0) + 1
            row["scorers"] = [f"{names.get(s, s)}"
                              + (f" ({n})" if n > 1 else "")
                              for s, n in sorted(tally.items(),
                                                 key=lambda kv: -kv[1])[:3]]
    except Exception:
        pass
    return rows


def export(path: str = "/var/www/bestairadio/data/league.json") -> None:
    """Publish the league to the website. Live-game events appear only once
    their air_at has passed — the page ticks in listener time. Best-effort."""
    try:
        now = time.time()
        st = _load()
        latest = max(st["games"]) if st["games"] else None
        game = st["games"].get(latest) if latest else None
        log = None
        if latest:
            try:
                log = livegame.read_log(latest)
            except ValueError:
                log = None
        table = _display_league(st, game, log, now)
        divisions = {}
        for conf in LEAGUE.values():
            for dname in conf:
                keys = [k for k, d in _DIV_OF.items() if d == dname]
                keys.sort(key=lambda k: (-(2 * table[k]["w"] + table[k]["otl"]),
                                         table[k]["l"]))
                divisions[dname] = [
                    {"team": _ALL[k], "tracked": k in TRACKED,
                     **{f: table[k][f] for f in ("gp", "w", "l", "otl")},
                     "pts": 2 * table[k]["w"] + table[k]["otl"]} for k in keys]

        broadcast = None
        if game:
            broadcast = {"date": game["date"], "home": game["home"],
                         "away": game["away"], "arena": game.get("arena", ""),
                         "rivalry": game.get("rivalry", False),
                         "final": None, "ot": False, "so": False,
                         "played": False, "live": None, "events": None}
            if log:
                goals, pens, injury = [], [], None
                board, live_pos = [0, 0], None
                nair = log["narrated_air"]
                for cid in log["order"]:
                    ch = log["chunks"][cid]
                    # reveal a chunk ONLY once it has been narrated AND that
                    # narration has aired (never the roll-time stamp) — the
                    # scorebug ticks in listener time and cannot spoil
                    at = nair.get(cid)
                    if at is None or at > now:
                        continue
                    live_pos = max(ch["from"], ch["to"] - 1)
                    for e in ch["events"]:
                        if e["type"] == "goal":
                            goals.append({k: e[k] for k in
                                          ("period", "clock", "scorer", "assist",
                                           "strength")} | {"team": game[e["team"]]})
                            board = list(e["board"])
                        elif e["type"] == "penalty":
                            pens.append({k: e[k] for k in
                                         ("period", "clock", "player", "call")}
                                        | {"team": game[e["team"]], "min": 2})
                        elif e["type"] == "injury":
                            injury = {"player": e["player"], "note": e["note"],
                                      "period": e["period"],
                                      "team": game[e["team"]]}
                # the final shows only once the horn has been ANNOUNCED on air
                aired_final = (log["final"] is not None
                               and log["final_air_at"] is not None
                               and now >= log["final_air_at"])
                last_state = (log["chunks"][log["order"][-1]]["state"]
                              if log["order"] else None)
                broadcast["events"] = {
                    "goals": goals, "penalties": pens, "injury": injury,
                    "shots": ([int(last_state["shots"][0]),
                               int(last_state["shots"][1])] if aired_final and
                              last_state else None),
                    "goalies": {game["home"]: game["rosters"]["home"]["goalie"],
                                game["away"]: game["rosters"]["away"]["goalie"]},
                    "refs": game.get("refs", []),
                    "three_stars": log["final"]["stars"] if aired_final else [],
                    "disputed": None,
                    "attendance": game.get("attendance")}
                if aired_final:
                    f = log["final"]
                    broadcast.update(final=[f["h"], f["a"]], ot=f["ot"],
                                     so=f["so"], played=True, live=None)
                elif live_pos is not None:
                    broadcast["live"] = {
                        "period": livegame._period_of(live_pos),
                        "clock": livegame._clock_of(live_pos),
                        "score": board}
            elif game.get("recorded"):   # history from before tonight's log
                broadcast.update(final=game.get("final"),
                                 ot=game.get("ot", False),
                                 so=game.get("so", False), played=True)
        leaders = None
        try:
            v2x = _league_v2(st)
            if v2x is not None:
                from .league import stats as _lgs
                plx = v2x.load_side(f"players-s{st['season']}.json")
                stx = v2x.load_side(f"stats-s{st['season']}.json")
                if plx and stx:
                    leaders = {"points": _lgs.leaders(stx, plx, "p", 5),
                               "goals": _lgs.leaders(stx, plx, "g", 5),
                               "sv%": _lgs.leaders(stx, plx, "sv%", 3)}
        except Exception:
            leaders = None
        slate = st["slates"].get(st["sim_through"], [])
        out = {"season": st["season"], "updated": st["sim_through"],
               "divisions": divisions, "last_result": st["last_result"],
               "broadcast": broadcast,
               **({"leaders": leaders} if leaders else {}),
               "around": _around_rows(st, slate)}
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".tmp.{os.getpid()}")   # per-writer: the generator
        tmp.write_text(json.dumps(out))              # and the 30s publisher race
        tmp.replace(p)
        try:  # the sports section rides the same tick, gated by the same `out`
            from .league import sitefeed as _sfeed
            _sfeed.export_sports(st, out, root=p.parent)
        except Exception as e:
            print(f"  (sports feeds skipped: {e})")
    except Exception as e:
        # the website is decoration; the broadcast is the product — but say so,
        # or a missing web dir is an invisible no-publish
        print(f"  (league.json publish skipped: {e})")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "publish":
        export()                # the scorebug timer: re-render in listener time
    else:
        print("usage: python -m src.season publish")
