"""League v2 runtime — the gate, sidecar IO, the nightly day loop, shadow mode.

This is the integration spine (component F of docs/designs/hockey-final.md).
season.py calls into here lazily and ONLY when the gate is on; every failure
path falls back loudly to the proven v1 behavior. The components this drives
(schedule/players/boxscore/stats/briefs) are pure functions against the frozen
schemas — this module owns all file IO and sequencing.

Gate discipline (final design G4): v2 requires data/league/ENABLED *and*
data/league/VERIFIED containing the current sidecar hash — verify_league.py is
the only writer of VERIFIED, so an unverified or drifted state can never drive
the broadcast. Fallback: `rm data/league/ENABLED` (v1 fields are mirrored on
every fold and stay warm).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import time
from datetime import date as _date, timedelta
from pathlib import Path

SIDE = Path("data/league")
CHUNK_DAYS = 45          # catch-up bound per tick pass (final §6 / minimal §6)

# sidecars covered by the VERIFIED hash — the state that must not drift
# between verification and air
_CORE = ("players-s{n}.json", "schedule-s{n}.json")


# ---------------------------------------------------------------- gate + IO

def _p(name: str, root: Path | None = None) -> Path:
    return (root or SIDE) / name


def load_side(name: str, root: Path | None = None) -> dict | None:
    """Sidecar read with the season.json trust rules: live file, then .bak."""
    for p in (_p(name, root), _p(name, root).with_suffix(".bak")):
        try:
            if p.exists():
                return json.loads(p.read_text())
        except Exception:
            continue
    return None


def save_side(name: str, obj: dict, root: Path | None = None) -> None:
    """Atomic tmp+replace with .bak copy — the established _save pattern."""
    p = _p(name, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(obj))
    if p.exists():
        try:
            shutil.copy2(p, p.with_suffix(".bak"))
        except Exception:
            pass
    tmp.replace(p)


def sidecar_hash(season: int, root: Path | None = None) -> str:
    """Hash over the IMMUTABLE core: the schedule bytes and the player
    identity table (pid/name/slot). Runtime-mutable state (out2, call-ups,
    and — since Gate 2 — a player's `team`) is deliberately excluded: the
    engine itself writes those, and a gate that drifts shut on its own
    approved mutations guards nothing. `team` moved out of the hashed
    identity tuple when Gate 2 (economy) landed: a trade legitimately
    reassigns a player's team, and hashing it meant the very first trade of
    a season would drift this hash and silently fall the WHOLE v2 engine
    back to v1 on the next season.tick()/tonight_live() call — self-
    defeating for the one feature Gate 2 exists to ship. pid/name/slot still
    catch what this gate actually guards against (wrong roster file,
    corrupted or hand-edited state)."""
    h = hashlib.sha256()
    p = _p(f"schedule-s{season}.json", root)
    h.update(p.read_bytes() if p.exists() else b"missing")
    pl = load_side(f"players-s{season}.json", root)
    ident = sorted((pid, v.get("name", ""), v.get("slot", ""))
                   for pid, v in (pl or {}).get("players", {}).items())
    h.update(json.dumps(ident).encode())
    return h.hexdigest()


def v2_on(season: int, root: Path | None = None) -> bool:
    """ENABLED + VERIFIED + hash match + core sidecars parse. Any miss is a
    loud no — v1 keeps the air."""
    root = root or SIDE
    if not (root / "ENABLED").exists():
        return False
    ver = root / "VERIFIED"
    if not ver.exists():
        print("  !! league v2: ENABLED but not VERIFIED — staying on v1")
        return False
    try:
        if ver.read_text().strip() != sidecar_hash(season, root):
            print("  !! league v2: sidecar hash drift since verify — staying on v1")
            return False
    except Exception as e:
        print(f"  !! league v2 gate check failed ({e}) — staying on v1")
        return False
    for tpl in _CORE:
        if load_side(tpl.format(n=season), root) is None:
            print(f"  !! league v2: {tpl.format(n=season)} unreadable — staying on v1")
            return False
    return True


def arm(season: int, root: Path | None = None) -> None:
    """Write VERIFIED for the current sidecar state. ONLY verify_league.py
    calls this, and only after every check passes (G4: the migrator refuses
    to arm a state it hasn't proven)."""
    root = root or SIDE
    (root / "VERIFIED").write_text(sidecar_hash(season, root))


# ---------------------------------------------------------------- day loop

def _virtual_drop(season: int, day: str, hk: str, ak: str) -> int:
    """Seeded virtual puck drop offset (0-90 min) for the reveal clock (G1)."""
    return random.Random(f"drop:{season}:{day}:{hk}-{ak}").randint(0, 5400)


# ------------------------------------------------------- Gate 2: economy

ECON_FLAG = "ECON-ENABLED"
ALLOW_TRACKED_TRADES_FLAG = "ALLOW-TRACKED-TRADES"


def _mint_coaches(season_n: int, teams) -> dict:
    """Deterministic day-0 coach + trainer per team (minimal §12 shape),
    minted exactly once — the first day the economy gate is open and no
    coaches-s{n}.json exists yet. Reuses economy.py's own coach name bank/
    style list (component G) rather than inventing a second one; trainers
    draw from the same bank under a distinct seed namespace, matching
    minimal §12's own worked example (a coach-bank name doubling as a
    trainer's)."""
    from . import economy
    coaches, trainers = {}, {}
    for team in teams:
        c_rng = random.Random(f"mint-coach:{season_n}:{team}")
        coaches[team] = {"name": economy._mint_coach_name(c_rng),
                          "style": c_rng.choice(economy._STYLES),
                          "mod": round(c_rng.uniform(-0.02, 0.02), 4),
                          "hired_day": 0}
        t_rng = random.Random(f"mint-trainer:{season_n}:{team}")
        trainers[team] = {"name": economy._mint_coach_name(t_rng),
                           "heal": round(t_rng.uniform(0.85, 1.15), 3)}
    return {"coaches": coaches, "trainers": trainers}


def tick_v2(st: dict, air_date: str, apply_fn, tracked: dict,
            root: Path | None = None) -> dict | None:
    """Advance the league day-by-day to air_date on the v2 engine. Mutates
    `st` (the season.json dict) with mirrored v1 folds; writes sidecars under
    `root`. `apply_fn` is season._apply (injected so shadow mode can run
    against a deep copy without touching live helpers' state). Returns the
    loaded sidecar bundle for reuse, or None if nothing to do.

    Gate 2 (economy activation, hockey-final.md "Gates & scope"): entirely
    dormant unless `root/ECON-ENABLED` exists — every new line this gate
    touches lives behind that single check below, so a gate-off tick_v2
    executes none of it (byte-identical to the pre-Gate-2 day loop)."""
    from . import boxscore, calendar, players, schedule, stats as statsmod  # noqa: F401

    root = root or SIDE
    season_n = st["season"]
    start = st.get("sim_through") or air_date
    d0, d1 = _date.fromisoformat(start), _date.fromisoformat(air_date)
    if d0 > d1:
        return None
    pl = load_side(f"players-s{season_n}.json", root)
    sched = load_side(f"schedule-s{season_n}.json", root)
    stt = load_side(f"stats-s{season_n}.json", root) or \
        {"schema": 1, "season": season_n, "skaters": {}, "goalies": {}}
    if pl is None or sched is None:
        raise RuntimeError("v2 sidecars missing mid-flight")
    coaches = load_side(f"coaches-s{season_n}.json", root)   # None until Gate 2

    days_done = 0
    d = d0
    stats_dirty = players_dirty = coaches_dirty = False
    while d <= d1 and days_done < CHUNK_DAYS:
        day = d.isoformat()
        if day not in st["slates"]:
            # returns first: heal expired injuries, then refresh call-ups
            healed = [pid for pid, o in pl.get("out2", {}).items()
                      if o["until"] <= day]
            for pid in healed:
                del pl["out2"][pid]
            if healed:
                players_dirty = True
            rows_v1, box_games = [], []
            for row in sched["days"].get(day, []):
                hk, ak = row[0], row[1]
                if len(row) > 2 and row[2] == "AIR":
                    continue          # the live engine owns the broadcast game
                for tm in (hk, ak):
                    pl.setdefault("callups", {})[tm] = players.maybe_callup(pl, tm)
                home = players.dress(pl, hk, day)
                away = players.dress(pl, ak, day)
                s_h = players.team_strength(pl, {}, hk, False)
                s_a = players.team_strength(pl, {}, ak, False)
                rng = random.Random(f"slate2:{season_n}:{day}:{hk}-{ak}")
                box = boxscore.sim_box(home, away, s_h, s_a, rng)
                box["home"], box["away"] = hk, ak
                box["drop"] = _virtual_drop(season_n, day, hk, ak)
                hg, ag = box["final"]
                apply_fn(st, hk, ak, hg, ag, box["ot"] or box["so"])
                statsmod.fold_box(stt, box)
                stats_dirty = True
                for inj in box.get("injuries", []):
                    days_out, note, ir = players.sample_injury(
                        random.Random(f"inj:{season_n}:{day}:{inj['pid']}"))
                    until = (_date.fromisoformat(day)
                             + timedelta(days=days_out)).isoformat()
                    pl.setdefault("out2", {})[inj["pid"]] = {
                        "until": until, "note": inj.get("note", note), "ir": ir,
                        "games": max(1, days_out // 2)}
                    players_dirty = True
                    team = pl["players"].get(inj["pid"], {}).get("team")
                    if team in tracked:      # keep the v1 fallback out-list warm
                        lst = st.setdefault("out", {}).setdefault(team, [])
                        name = pl["players"][inj["pid"]]["name"]
                        if len(lst) < 2 and all(o["player"] != name for o in lst):
                            lst.append({"player": name,
                                        "until": st["game_no"] + max(1, days_out // 4)})
                rows_v1.append([hk, ak, hg, ag, box["ot"] or box["so"]])
                box_games.append(box)
            st["slates"][day] = rows_v1        # v1 mirror stays warm
            if len(st["slates"]) > 30:
                for old in sorted(st["slates"])[:-30]:
                    del st["slates"][old]
            save_side(f"box/{day}.json", {"date": day, "games": box_games}, root)
            _prune_boxes(root, day)

            # --- Gate 2: economy activation --------------------------------
            # Dormant unless ECON-ENABLED exists (checked fresh every day, so
            # flipping the flag mid-catch-up picks up on the next unprocessed
            # day). The whole step is exception-isolated: a bad econ day must
            # never kill the tick — regular-season folding above already
            # happened and stands regardless of what follows here.
            if (root / ECON_FLAG).exists():
                try:
                    from . import economy
                    if coaches is None:
                        teams = sorted({p["team"]
                                        for p in pl["players"].values()})
                        coaches = _mint_coaches(season_n, teams)
                        coaches_dirty = True
                    # owner flag, re-read every day so revoking it takes
                    # effect immediately (economy._tradeable's own gate)
                    pl["allow_tracked_trades"] = \
                        (root / ALLOW_TRACKED_TRADES_FLAG).exists()
                    day_idx = calendar.day_index(sched.get("start", day), day)
                    econ_rng = random.Random(f"econ:{season_n}:{day_idx}")
                    tx = economy.run_day(pl, coaches, st["league"], season_n,
                                          day_idx, econ_rng)
                    # trades/firings already mutated pl/coaches in place
                    # (economy.run_day's own contract) -- our job is to
                    # persist that and record the transaction log + wire
                    # copy for other shows' scores desks.
                    for t in tx:
                        t.setdefault("date", day)
                    txfile = load_side(f"transactions-s{season_n}.json",
                                        root) or {"tx": []}
                    txfile["tx"].extend(tx)
                    save_side(f"transactions-s{season_n}.json", txfile, root)
                    save_side("news-lines.json",
                               [t["note"] for t in tx if t.get("note")], root)
                    players_dirty = True
                    coaches_dirty = True
                except Exception as e:
                    print(f"  !! league v2 economy step failed for {day} "
                          f"({e}) — econ skipped this day, tick continues")
        if day > st["sim_through"]:
            st["sim_through"] = day
        days_done += 1
        d += timedelta(days=1)

    if stats_dirty:
        save_side(f"stats-s{season_n}.json", stt, root)
    if players_dirty:
        save_side(f"players-s{season_n}.json", pl, root)
    if coaches_dirty and coaches is not None:
        save_side(f"coaches-s{season_n}.json", coaches, root)
    return {"players": pl, "schedule": sched, "stats": stt, "coaches": coaches}


def backfill_boxes(st: dict, root: Path | None = None) -> int:
    """Heal days the v1 mirror simmed while v2 was dark (the pre-cutover
    tail): their finals are folded canon, but no box shard or stats fold ever
    happened — scorers, leaders, and the reveal clock are blind for those
    dates. For each recent slate day with no shard, retrofit boxes from the
    recorded finals (box_from_final: the score is canon, only the names are
    allocated), fold them into the stats sidecar, and save the shard.
    Idempotent: a day with a shard (live or .bak) is never touched, and the
    window stays inside shard retention so a pruned v2 day can't double-fold.
    Broadcast games are skipped — fold_live folded them at the horn."""
    from . import boxscore, players, stats as statsmod
    root = root or SIDE
    season_n = st["season"]
    today = st.get("sim_through") or ""
    if not today or not v2_on(season_n, root):
        return 0
    lo = (_date.fromisoformat(today) - timedelta(days=20)).isoformat()
    pl = load_side(f"players-s{season_n}.json", root)
    if pl is None:
        return 0
    stt = load_side(f"stats-s{season_n}.json", root) or \
        {"schema": 1, "season": season_n, "skaters": {}, "goalies": {}}
    healed = 0
    for day in sorted(st.get("slates", {})):
        if day < lo:
            continue
        shard_p = _p(f"box/{day}.json", root)
        if shard_p.exists() or shard_p.with_suffix(".bak").exists():
            continue
        game = st.get("games", {}).get(day)
        bpair = ({game.get("home_key"), game.get("away_key")}
                 if game else set())
        box_games = []
        for hk, ak, hg, ag, o in st["slates"][day]:
            if hk in bpair and ak in bpair:
                continue
            home = players.dress(pl, hk, day)
            away = players.dress(pl, ak, day)
            rng = random.Random(f"retrofit:{season_n}:{day}:{hk}-{ak}")
            box = boxscore.box_from_final(home, away, [hg, ag],
                                          bool(o), False, rng)
            box["home"], box["away"] = hk, ak
            box["drop"] = _virtual_drop(season_n, day, hk, ak)
            statsmod.fold_box(stt, box)
            box_games.append(box)
        save_side(f"box/{day}.json", {"date": day, "games": box_games}, root)
        healed += 1
    if healed:
        save_side(f"stats-s{season_n}.json", stt, root)
        print(f"  league: retrofitted {healed} day(s) of box shards")
    return healed


def _prune_boxes(root: Path, today: str, keep: int = 21) -> None:
    cutoff = (_date.fromisoformat(today) - timedelta(days=keep)).isoformat()
    box = (root or SIDE) / "box"
    if not box.exists():
        return
    for p in box.glob("*.json*"):
        if p.name[:10] < cutoff:
            p.unlink(missing_ok=True)


def fold_live(st: dict, game: dict, log: dict) -> None:
    """Fold a BROADCAST game's live log into the season stats sidecar —
    called from record_live inside its exactly-once block (the recorded flag
    is the de-dup key fold_box itself doesn't keep). Names map to pids via
    the players sidecar; unknown names fold under their name string rather
    than being dropped (a stat must never vanish because a mapping aged)."""
    from . import stats as statsmod
    season_n = game["season"]
    stt = load_side(f"stats-s{season_n}.json")
    pl = load_side(f"players-s{season_n}.json")
    if stt is None or pl is None:
        return
    n2p = {p["name"]: pid for pid, p in pl["players"].items()
           if p.get("team") in (game["home_key"], game["away_key"])}
    f = log["final"]
    goals = []
    for cid in log["order"]:
        for e in log["chunks"][cid]["events"]:
            if e.get("type") == "goal":
                goals.append({
                    "t": "h" if e["team"] == "home" else "a",
                    "period": e.get("period"), "clock": e.get("clock"),
                    "scorer": n2p.get(e["scorer"], e["scorer"]),
                    "a1": n2p.get(e["assist"]) if e.get("assist") else None,
                    "a2": n2p.get(e.get("assist2")) if e.get("assist2") else None,
                    "str": e.get("strength", "EV")})
    r = game["rosters"]
    box = {"home": game["home_key"], "away": game["away_key"],
           "final": [f["h"], f["a"]], "ot": f["ot"], "so": f["so"],
           "goals": goals, "shots": f.get("shots", [0, 0]),
           "goalies": {"h": n2p.get(r["home"]["goalie"], r["home"]["goalie"]),
                       "a": n2p.get(r["away"]["goalie"], r["away"]["goalie"])},
           "stars": [n2p.get(s, s) for s in f.get("stars", [])],
           "injuries": []}
    statsmod.fold_box(stt, box)
    save_side(f"stats-s{season_n}.json", stt)


# ---------------------------------------------------------------- shadow (G2)

def shadow_tick(air_date: str) -> None:
    """Run the full v2 day loop against data/league-shadow — a copy that
    NEVER touches season.json, the site, or the live sidecars. Exception-
    isolated: shadow failures land in the report, never on the station.

    What the soak proves: zero exceptions, bounded per-pass cost, and sane
    structure (gp monotonic, no team past 82). It does NOT expect standings
    equality with live — v1 and v2 legitimately sim new days differently;
    played-day equality is the migrator's canon-diff job."""
    shadow = Path("data/league-shadow")
    try:
        from .. import season as season_mod
        st_live = season_mod._load()
        st = json.loads(json.dumps(st_live))    # deep copy — never the live dict
        if not shadow.exists() and SIDE.exists():
            shutil.copytree(SIDE, shadow,
                            ignore=shutil.ignore_patterns("*.tmp.*"))
        t0 = time.time()
        tick_v2(st, air_date, season_mod._apply, season_mod.TRACKED,
                root=shadow)
        gps = [v["gp"] for v in st["league"].values()]
        entry = {"ts": time.time(), "date": air_date,
                 "ms": round((time.time() - t0) * 1000, 1),
                 "gp_min": min(gps), "gp_max": max(gps),
                 "over_82": sum(1 for g in gps if g > 82),
                 "sim_through": st["sim_through"], "error": None}
    except Exception as e:
        entry = {"ts": time.time(), "date": air_date, "ms": None,
                 "error": f"{type(e).__name__}: {e}"}
    try:
        shadow.mkdir(parents=True, exist_ok=True)
        with open(shadow / "shadow-report.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
