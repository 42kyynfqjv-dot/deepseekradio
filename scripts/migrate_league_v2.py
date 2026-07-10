#!/usr/bin/env python3
"""Migrate live season 1 from v1 (season.json-only) to v2 sidecar state.

hockey-final.md §7 / hockey-minimal.md §7, gate OFF the whole time: this
script NEVER writes season.json (not even the additive `v2` key — the gate
is ENABLED/VERIFIED files only, per the frozen contract) and NEVER touches
`data/league/ENABLED`. It mints the v2 player pool around each team's
already-aired 9 names (re-derived from the exact seed that produced them),
builds the REMAINDER schedule for the rest of season 1, back-fills the
stats aggregate from every game already played, and writes
`data/league/canon-diff.txt` — a from-scratch, honest report of every
divergence from aired canon. Cutover (via scripts/verify_league.py) requires
that file to come out EMPTY; this script does not force it empty, it reports
whatever the real migration produced (see canon-diff docstring below).

Idempotent: re-running overwrites the sidecars with the same deterministic
derivation (mint_league/assign_days are pure functions of season+seed;
stats back-fill re-folds from the same source-of-truth logs/finals every
time, so a second run reproduces byte-different-but-equivalent aggregates,
never accumulates twice).

Runnable from the repo root or from /opt/kaos/app — every path here is
cwd-relative, exactly like season.py's `_PATH` and engine.py's `SIDE`.
"""
from __future__ import annotations

import random
import sys
from datetime import date as _date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import livegame                                      # noqa: E402
from src import season                                        # noqa: E402
from src.league import boxscore, engine, players, schedule    # noqa: E402
from src.league import stats as statsmod                      # noqa: E402

DEFAULT_SEASON = 1
DEFAULT_START = "2026-07-05"


# --------------------------------------------------------------- derivation

def derive_aired(season_n: int) -> dict[str, list[str]]:
    """Every team's protected-core 9 names, re-derived from the SAME seed
    that produced the live broadcast rosters (season._roster) — 8 skaters
    then the goalie, mint order (players.mint_league's expected shape)."""
    aired: dict[str, list[str]] = {}
    for key in season._ALL:
        r = season._roster(key, season_n)
        aired[key] = list(r["skaters"]) + [r["goalie"]]
    return aired


def derive_target_strength(season_n: int) -> dict[str, float]:
    """Every team's hidden v1 strength scalar (season._strength) — the
    competitive landscape aired to date, preserved not re-rolled."""
    return {key: season._strength(key, season_n) for key in season._ALL}


def gp_played(st: dict) -> dict[str, int]:
    """Games-played-to-date per team, straight from the (never-written)
    standings dict — advisory bookkeeping for schedule.assign_days and the
    canon-diff schedule-totals check."""
    return {k: v.get("gp", 0) for k, v in st["league"].items()}


def played_pairs(st: dict) -> list[tuple[str, str]]:
    """(home, away) pairs already aired — off-air slates plus recorded
    broadcast games — so assign_days trims exactly what's already happened
    off the NHL-matrix pool (minimal §7's "remainder" schedule)."""
    pairs: list[tuple[str, str]] = []
    for rows in st.get("slates", {}).values():
        for row in rows:
            pairs.append((row[0], row[1]))
    for g in st.get("games", {}).values():
        if g.get("recorded"):
            pairs.append((g["home_key"], g["away_key"]))
    return pairs


def name_to_pid(pl: dict) -> dict[str, str]:
    """League-wide name -> pid lookup. Safe: mint_league guarantees every
    minted name (aired or fresh) is globally unique."""
    return {p["name"]: pid for pid, p in pl["players"].items()}


# ------------------------------------------------------------- stats fill

def _safe_fold(stt: dict, box: dict) -> bool:
    """stats.fold_box's game-winning-goal derivation sorts goals by
    `(period, clock)`, but any OT-decided game's goal list mixes integer
    periods (1/2/3) with the literal string "OT" -- Python 3 raises
    comparing them (`TypeError: '<' not supported between instances of
    'str' and 'int'`), so fold_box crashes on EVERY OT/SO-decided game
    (confirmed empirically; not exercised by tests/test_league_stats.py,
    whose synthetic OT boxes deliberately omit a real OT-tagged goal event
    -- see that file's own "documented GWG-friction case" comment). This is
    a pre-existing src/league/stats.py bug, out of scope to fix here (never
    touch src/) -- flagged prominently in this script's own summary output.

    Every OTHER mutation fold_box makes (goalie w/l/otl/sa/sv/so, skater
    g/a/gp/hat) already commits in place BEFORE the crashing sort runs, and
    no shipped leaders()/milestones() call reads the gwg counter at all --
    so catching just this one TypeError costs nothing visible on air; it
    only skips that single game's (unused) gwg credit. Returns False when
    the crash was caught, so callers can report how often it fired."""
    try:
        statsmod.fold_box(stt, box)
        return True
    except TypeError:
        return False


def _dress_decorated(pl: dict, team: str, day: str, name2pid: dict) -> dict:
    """players.dress()'s frozen shape is missing the two keys box_from_final
    needs to resolve team identity / goalie pid (its own docstring flags
    this as an undocumented-but-needed pair) — decorate a COPY here rather
    than touching players.py. Never mutates `pl`."""
    r = dict(players.dress(pl, team, day))
    r["team"] = team
    r["goalie_id"] = name2pid.get(r.get("goalie"))
    return r


def fold_aired_game(stt: dict, name2pid: dict, game: dict, date: str,
                     gwg_skips: list) -> bool:
    """Back-fill one broadcast game from its surviving livegame-<date>.jsonl
    log: real scorers, real assists, real goalies, folded by name -> pid.
    Returns False (no-op) if the log is gone or the game never finished —
    a season-1 approximation gap the migration can't recover, never a crash."""
    try:
        log = livegame.read_log(date)
    except ValueError:
        return False
    if not log or not log.get("final"):
        return False
    hk, ak = game["home_key"], game["away_key"]
    home_goalie = game.get("rosters", {}).get("home", {}).get("goalie")
    away_goalie = game.get("rosters", {}).get("away", {}).get("goalie")

    goals = []
    for cid in log["order"]:
        for e in log["chunks"][cid]["events"]:
            if e["type"] != "goal":
                continue
            side = "h" if e["team"] == "home" else "a"
            goals.append({
                "t": side, "period": e["period"], "clock": e["clock"],
                "scorer": name2pid.get(e["scorer"], e["scorer"]),
                "a1": name2pid.get(e["assist"], e["assist"]) if e.get("assist") else None,
                "a2": name2pid.get(e.get("assist2"), e.get("assist2")) if e.get("assist2") else None,
                "str": e.get("strength", "EV"),
            })
    injuries = []
    for cid in log["order"]:
        for e in log["chunks"][cid]["events"]:
            if e["type"] == "injury":
                injuries.append({"pid": name2pid.get(e["player"], e["player"]),
                                  "note": e.get("note", "")})

    fin = log["final"]
    box = {
        "home": hk, "away": ak, "final": [fin["h"], fin["a"]],
        "ot": fin.get("ot", False), "so": fin.get("so", False),
        "goals": goals, "shots": fin.get("shots", [0, 0]),
        "goalies": {"h": name2pid.get(home_goalie, home_goalie),
                    "a": name2pid.get(away_goalie, away_goalie)},
        "stars": [name2pid.get(s, s) for s in fin.get("stars", [])],
        "injuries": injuries,
    }
    if not _safe_fold(stt, box):
        gwg_skips.append(f"aired:{date}")
    return True


def fold_offair_slates(stt: dict, pl: dict, name2pid: dict,
                        st: dict, gwg_skips: list) -> int:
    """Back-fill every stored off-air slate final via boxscore.box_from_final
    (minimal §7): the score is canon and untouched, only the goal-by-goal
    allocation onto the dressed roster is retrofit. Seed f"retro:{season}:
    {day}" per the frozen contract. NOTE (documented approximation): v1's
    slate rows carry one combined ot-or-so flag (season._apply's `ot or so`),
    so this retrofit cannot distinguish a real overtime winner from a real
    shootout winner for already-played games — both are folded as `ot=True,
    so=False`. This is inert for every stat this file aggregates: fold_box's
    OTL bucket only ever tests `ot or so` together, never one alone."""
    season_n = st["season"]
    folded = 0
    for day, rows in st.get("slates", {}).items():
        for hk, ak, hg, ag, ot_or_so in rows:
            home_r = _dress_decorated(pl, hk, day, name2pid)
            away_r = _dress_decorated(pl, ak, day, name2pid)
            rng = random.Random(f"retro:{season_n}:{day}:{hk}-{ak}")
            box = boxscore.box_from_final(home_r, away_r, [hg, ag],
                                           ot_or_so, False, rng)
            if not _safe_fold(stt, box):
                gwg_skips.append(f"slate:{day}:{hk}-{ak}")
            folded += 1
    return folded


# ------------------------------------------------------------- canon-diff

def compute_canon_diff(st: dict, pl: dict, sched: dict,
                        season_n: int) -> list[str]:
    """A from-scratch, honest divergence report (G6). NOT guaranteed empty
    by construction — if real aired history doesn't cleanly subset the NHL
    matrix (schedule.py's own documented "approximation gap" friction), the
    mismatch is reported here, not hidden. Cutover requires this list empty;
    that is a property of the DATA, verified independently by
    scripts/verify_league.py, not asserted by this function."""
    diffs: list[str] = []
    aired = derive_aired(season_n)

    # 1. every aired name present on its team at the right slot
    core_slots = [s for s, _ in players._CORE_SKATER_SLOTS]  # F1,F1,F1,F2,F2,F2,D1,D1
    by_name = {}
    for pid, p in pl["players"].items():
        by_name.setdefault((p.get("team"), p.get("name")), []).append((pid, p))
    for team, names in aired.items():
        for i, name in enumerate(names[:8]):
            expect_slot = core_slots[i]
            hits = by_name.get((team, name), [])
            hit = next((p for _, p in hits if p.get("aired")), None)
            if hit is None:
                diffs.append(f"aired name missing: {team} {name!r} (expected slot {expect_slot})")
            elif hit.get("slot") != expect_slot:
                diffs.append(f"aired slot mismatch: {team} {name!r} "
                             f"got {hit.get('slot')!r} want {expect_slot!r}")
        goalie_name = names[8]
        hits = by_name.get((team, goalie_name), [])
        hit = next((p for _, p in hits if p.get("aired")), None)
        if hit is None:
            diffs.append(f"aired goalie missing: {team} {goalie_name!r} (expected slot G1)")
        elif hit.get("slot") != "G1":
            diffs.append(f"aired goalie slot mismatch: {team} {goalie_name!r} "
                         f"got {hit.get('slot')!r} want 'G1'")

    # 2. standings dict untouched (defense-in-depth: this script never calls
    # season._save, so a fresh reload must be byte-identical to what we read)
    if season._PATH.exists():
        reloaded = season._load()
        if reloaded.get("league") != st.get("league"):
            diffs.append("standings dict changed on disk since migration read it")

    # 3. schedule totals 82 / 41H / 41A per team (played + remainder, HARD
    # for every team, tracked included), and the crossover budget: exactly
    # 8 SCHEDULED mtl-nyg games (HARD — the Series the every-7th-AIR-ordinal
    # cadence spends). Already-PLAYED chance mtl-nyg meetings (v1's off-air
    # slate could legally pair them pre-migration — see schedule._remainder's
    # docstring) are tolerated in the total-meetings count only:
    # schedule._absorb_chance_meeting charges their GP/H/A cost back to the
    # tracked teams' own remaining games, so the totals above stay exact;
    # the surplus meetings themselves are the documented season-1
    # approximation, reported as an info line by _print_summary /
    # verify_league, never a diff here.
    pairs = played_pairs(st)
    total = {k: 0 for k in season._ALL}
    home_ct = {k: 0 for k in season._ALL}
    away_ct = {k: 0 for k in season._ALL}
    crossover_played = 0
    crossover_sched = 0
    mtl, nyg = "mtl", "nyg"
    for h, a in pairs:
        if h in total:
            total[h] += 1
            home_ct[h] += 1
        if a in total:
            total[a] += 1
            away_ct[a] += 1
        if {h, a} == {mtl, nyg}:
            crossover_played += 1
    for day_rows in sched.get("days", {}).values():
        for row in day_rows:
            h, a = row[0], row[1]
            if h in total:
                total[h] += 1
                home_ct[h] += 1
            if a in total:
                total[a] += 1
                away_ct[a] += 1
            if {h, a} == {mtl, nyg}:
                crossover_sched += 1
    for k in season._ALL:
        if total[k] != 82:
            diffs.append(f"schedule total != 82: {k} got {total[k]}")
        if home_ct[k] != 41:
            diffs.append(f"schedule home count != 41: {k} got {home_ct[k]}")
        if away_ct[k] != 41:
            diffs.append(f"schedule away count != 41: {k} got {away_ct[k]}")
    if crossover_sched != 8:
        diffs.append(f"scheduled crossover (mtl-nyg) != 8: got {crossover_sched}"
                     f" (+{crossover_played} already played)")

    return diffs


# ------------------------------------------------------------------- main

def migrate(season_n: int = DEFAULT_SEASON, start: str = DEFAULT_START) -> dict:
    """Run the whole migration. Returns a result dict (never raises on a
    normal 'nothing to do' state; genuine bugs still raise)."""
    if not season._PATH.exists():
        return {"ok": True, "skipped": "no live state"}

    st = season._load()   # read-only: this name is NEVER passed to _save

    aired = derive_aired(season_n)
    target_strength = derive_target_strength(season_n)
    pl = players.mint_league(season_n, aired, target_strength)
    engine.save_side(f"players-s{season_n}.json", pl)

    gpp = gp_played(st)
    pairs = played_pairs(st)
    matchups = schedule.build_matchups(season_n)
    days = schedule.assign_days(matchups, season_n, start,
                                 gp_played=gpp, played_pairs=pairs)
    last_day = max(days) if days else start
    playoff_start = (_date.fromisoformat(last_day) + timedelta(days=3)).isoformat()
    sched = {"schema": 1, "season": season_n, "start": start,
             "days": days, "playoff_start": playoff_start}
    engine.save_side(f"schedule-s{season_n}.json", sched)

    name2pid = name_to_pid(pl)
    stt = {"schema": 1, "season": season_n, "skaters": {}, "goalies": {}}
    gwg_skips: list = []
    aired_folded = 0
    for date, g in st.get("games", {}).items():
        if g.get("recorded"):
            if fold_aired_game(stt, name2pid, g, date, gwg_skips):
                aired_folded += 1
    offair_folded = fold_offair_slates(stt, pl, name2pid, st, gwg_skips)
    engine.save_side(f"stats-s{season_n}.json", stt)

    diffs = compute_canon_diff(st, pl, sched, season_n)
    diff_path = engine.SIDE / "canon-diff.txt"
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.write_text("\n".join(diffs) + ("\n" if diffs else ""))

    # per-team strength solve check (mandated ±0.01) -- reported, not fatal
    strength_rows = []
    for k in season._ALL:
        achieved = players.team_strength(pl, {}, k, False)
        strength_rows.append((k, target_strength[k], achieved,
                              abs(achieved - target_strength[k])))

    chance_meetings = sum(1 for h, a in pairs if {h, a} == {"mtl", "nyg"})

    return {
        "ok": not diffs,
        "season": season_n, "start": start,
        "players_minted": len(pl["players"]),
        "schedule_days": len(days),
        "aired_games_folded": aired_folded,
        "offair_games_folded": offair_folded,
        "gwg_skips": gwg_skips,
        "chance_meetings": chance_meetings,
        "canon_diff": diffs,
        "canon_diff_path": str(diff_path),
        "strength_rows": strength_rows,
        "pl": pl, "sched": sched, "stt": stt,
    }


def _print_summary(res: dict) -> None:
    if res.get("skipped"):
        print(f"migrate_league_v2: {res['skipped']} — nothing to migrate, exiting 0")
        return
    print(f"migrate_league_v2: season {res['season']} (start {res['start']})")
    print(f"  players minted:      {res['players_minted']}")
    print(f"  schedule days built: {res['schedule_days']}")
    print(f"  aired games folded:  {res['aired_games_folded']}")
    print(f"  off-air games folded:{res['offair_games_folded']}")
    if res["gwg_skips"]:
        print(f"  !! stats.fold_box GWG-derivation bug hit on "
              f"{len(res['gwg_skips'])} OT/SO game(s) (pre-existing "
              f"src/league/stats.py issue, not touched here — see "
              f"_safe_fold docstring). All other stats for those games "
              f"folded normally; only their (unused) gwg counter is short.")
    if res.get("chance_meetings"):
        print(f"  (info) {res['chance_meetings']} chance mtl-nyg meeting(s) "
              f"already played off-air pre-migration: season total meetings "
              f"= 8 scheduled + {res['chance_meetings']} (documented season-1 "
              f"approximation, see schedule._remainder). Schedule totals "
              f"stay exactly 82/41H/41A for every team.")
    worst = sorted(res["strength_rows"], key=lambda r: -r[3])[:5]
    print("  strength solve (worst 5 |delta|):")
    print("    team   target achieved   |delta|")
    for k, tgt, ach, d in worst:
        flag = "" if d <= 0.01 else "  !! > +/-0.01"
        print(f"    {k:<6} {tgt:.4f}  {ach:.4f}   {d:.4f}{flag}")
    print(f"  canon-diff -> {res['canon_diff_path']} "
          f"({len(res['canon_diff'])} divergence(s))")
    if res["canon_diff"]:
        for line in res["canon_diff"]:
            print(f"    !! {line}")
    else:
        print("    (empty — clean migration)")


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=DEFAULT_SEASON)
    ap.add_argument("--start", default=DEFAULT_START)
    args = ap.parse_args(argv)
    res = migrate(args.season, args.start)
    _print_summary(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
