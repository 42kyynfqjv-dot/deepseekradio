"""League site feeds — /data/sports/<sport>/*.json, derived every tick.

season.export() calls export_sports() on the same 30-second scorebug cadence,
handing over the pieces it JUST air-gated for league.json: the display table
(tonight's un-aired final un-applied), the reveal-gated around rows, and the
aired-only broadcast block. Everything here is assembled from those pieces,
so no feed can ever say more than the booth has — one gate, every surface.

What this adds over league.json is the league-wide framing an out-of-town
fan expects: a scoreboard you can page by day, standings with form (last-10,
streak), stat leaders with depth, and a page of data for every franchise.
Feeds are namespaced by sport (sports/hockey/...) so a second sim mounts as
a sibling directory, not a rewrite.

Derive-don't-store: computed fresh from season.json + the v2 sidecars each
call, written atomically, and bytes-identical rewrites are skipped so 30s
ticks don't churn 30+ files that haven't changed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SPORT = "hockey"
SCOREBOARD_DAYS = 7
UPCOMING_GAMES = 5
FORM_GAMES = 10


# ── plumbing ─────────────────────────────────────────────────────────────────
def _write(path: Path, obj: dict) -> None:
    """Atomic write; skip when the bytes haven't changed."""
    data = json.dumps(obj)
    try:
        if path.exists() and path.read_text() == data:
            return
    except Exception:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(data)
    tmp.replace(path)


def _meta():
    """key -> franchise identity, from the league spine (single source)."""
    from .. import season as _sn
    meta = {}
    for conf, divs in _sn.LEAGUE.items():
        for dname, teams in divs.items():
            for k, name in teams:
                meta[k] = {"key": k, "team": name, "division": dname,
                           "conference": conf, "tracked": k in _sn.TRACKED,
                           "arena": _sn.TRACKED.get(k, {}).get("arena")}
    return meta


def _sidecars(season: int):
    """(players, stats, schedule) v2 sidecars, or Nones — feeds degrade."""
    try:
        from . import engine
        return (engine.load_side(f"players-s{season}.json"),
                engine.load_side(f"stats-s{season}.json"),
                engine.load_side(f"schedule-s{season}.json"))
    except Exception:
        return None, None, None


# ── aired-safe result assembly ───────────────────────────────────────────────
def _day_rows(st: dict, out: dict, meta: dict, date: str) -> list:
    """One scoreboard day. Past days are finals from the slate archive; the
    current day reuses the reveal-gated around rows (zipped 1:1 with the
    slate); the broadcast game rides the aired-only broadcast block."""
    today = st.get("sim_through", "")
    game = st.get("games", {}).get(date)
    bkeys = ((game.get("home_key"), game.get("away_key")) if game else ())
    rows = []
    day_slate = st.get("slates", {}).get(date, [])
    statuses = out.get("around", []) if date == today else None
    for i, (hk, ak, hg, ag, ot) in enumerate(day_slate):
        if game and hk in bkeys and ak in bkeys:
            continue                    # the broadcast row is built below
        row = {"hk": hk, "ak": ak,
               "home": meta[hk]["team"], "away": meta[ak]["team"],
               "score": [hg, ag], "ot": bool(ot), "status": "final"}
        if statuses is not None and i < len(statuses):
            ar = statuses[i]            # reveal-gated: never ahead of the booth
            row["score"] = ar.get("score")
            row["ot"] = bool(ar.get("ot"))
            row["status"] = ar.get("status") or "final"
            for f in ("period", "clock", "scorers"):
                if ar.get(f) is not None:
                    row[f] = ar[f]
        rows.append(row)
    if game:
        b = out.get("broadcast") if date == today else None
        row = {"hk": game["home_key"], "ak": game["away_key"],
               "home": game["home"], "away": game["away"],
               "air": True, "score": None, "ot": False, "status": "upcoming"}
        if b and b.get("date") == date:
            if b.get("played"):
                row.update(score=b["final"], ot=b.get("ot") or b.get("so"),
                           status="final")
            elif b.get("live"):
                row.update(score=b["live"]["score"], status="live",
                           period=b["live"]["period"], clock=b["live"]["clock"])
        elif game.get("recorded") and date != today:
            row.update(score=game.get("final"),
                       ot=game.get("ot", False) or game.get("so", False),
                       status="final")
        rows.append(row)
    return rows


def _results_by_team(days: list) -> dict:
    """Chronological aired-safe results per team, from scoreboard days —
    only rows already revealed as final count toward form and history."""
    res: dict = {}
    for day in days:
        for g in day["games"]:
            if g.get("status") != "final" or not g.get("score"):
                continue
            hg, ag = g["score"]
            for key, opp, mine, theirs, home in (
                    (g["hk"], g["ak"], hg, ag, True),
                    (g["ak"], g["hk"], ag, hg, False)):
                won = mine > theirs
                res.setdefault(key, []).append(
                    {"date": day["date"], "opp_key": opp,
                     "home": home, "gf": mine, "ga": theirs,
                     "ot": g.get("ot", False), "air": bool(g.get("air")),
                     "res": "W" if won else ("OTL" if g.get("ot") else "L")})
    return res


def _form(results: list) -> tuple:
    """('4-2-1' last-10, 'W2'/'L3'/'—' streak) from chronological results."""
    tail = results[-FORM_GAMES:]
    w = sum(1 for r in tail if r["res"] == "W")
    otl = sum(1 for r in tail if r["res"] == "OTL")
    last10 = f"{w}-{len(tail) - w - otl}-{otl}"
    streak, kind = 0, None
    for r in reversed(results):
        k = "W" if r["res"] == "W" else "L"
        if kind is None:
            kind = k
        if k != kind:
            break
        streak += 1
    return last10, (f"{kind}{streak}" if kind else "—")


# ── the feeds ────────────────────────────────────────────────────────────────
def export_sports(st: dict, out: dict, root: Path | str) -> None:
    """Write the sports feed tree under `root` (the site's /data dir).
    `out` is the league.json payload export() just published — already
    air-gated; this function must not re-derive any reveal decision."""
    meta = _meta()
    base = Path(root) / "sports" / SPORT
    today = st.get("sim_through", "")
    players, stats, schedule = _sidecars(st.get("season", 1))

    # scoreboard: the archived slate days (today last, reveal-gated)
    dates = sorted(set(list(st.get("slates", {})) + list(st.get("games", {}))))
    dates = [d for d in dates if d <= today][-SCOREBOARD_DAYS:]
    days = [{"date": d, "games": _day_rows(st, out, meta, d)}
            for d in dates]
    _write(base / "scoreboard.json",
           {"schema": 1, "season": st.get("season", 1), "updated": today,
            "days": days})

    # standings: the display table (gated) + form from aired-safe results
    results = _results_by_team(days)
    table = {}
    for div in out.get("divisions", {}).values():
        for row in div:
            table[row["team"]] = row
    conferences: dict = {}
    for k, m in meta.items():
        t = table.get(m["team"], {"gp": 0, "w": 0, "l": 0, "otl": 0, "pts": 0})
        last10, streak = _form(results.get(k, []))
        conferences.setdefault(m["conference"], {}).setdefault(
            m["division"], []).append(
            {"key": k, "team": m["team"], "tracked": m["tracked"],
             "gp": t["gp"], "w": t["w"], "l": t["l"], "otl": t["otl"],
             "pts": t["pts"], "last10": last10, "streak": streak})
    for divs in conferences.values():
        for rows in divs.values():
            rows.sort(key=lambda r: (-r["pts"], r["gp"], r["team"]))
    _write(base / "standings.json",
           {"schema": 1, "season": st.get("season", 1), "updated": today,
            "trophy": "The Boreal Lantern", "conferences": conferences})

    # leaders: skater p/g/a depth + goalie form
    lead = {}
    if players and stats:
        from . import stats as _lgs
        lead = {"points": _lgs.leaders(stats, players, "p", 10),
                "goals": _lgs.leaders(stats, players, "g", 10),
                "assists": _lgs.leaders(stats, players, "a", 10),
                "sv%": _lgs.leaders(stats, players, "sv%", 5)}
        wins = []
        plook = _lgs._lookup(players)
        for pid, arr in (stats.get("goalies") or {}).items():
            gp, w, l, otl, sa, sv, so = arr
            name, team = _lgs._name_team(plook, pid)
            wins.append({"pid": pid, "name": name, "team": team, "gp": gp,
                         "w": w, "so": so})
        wins.sort(key=lambda r: (-r["w"], r["gp"]))
        lead["wins"] = wins[:5]
    _write(base / "leaders.json",
           {"schema": 1, "season": st.get("season", 1), "updated": today,
            "leaders": lead})

    # one page of data per franchise
    sched_days = (schedule or {}).get("days", {})
    plist = (players or {}).get("players", {})
    reserve = (players or {}).get("reserve", {})
    for k, m in meta.items():
        t = table.get(m["team"], {"gp": 0, "w": 0, "l": 0, "otl": 0, "pts": 0})
        res = results.get(k, [])
        for r in res:
            r["opp"] = meta[r["opp_key"]]["team"]
        last10, streak = _form(res)
        upcoming = []
        for d in sorted(sched_days):
            if d <= today or len(upcoming) >= UPCOMING_GAMES:
                continue
            for row in sched_days[d]:
                hk, ak = row[0], row[1]
                if k in (hk, ak):
                    opp = ak if k == hk else hk
                    upcoming.append({"date": d, "opp_key": opp,
                                     "opp": meta[opp]["team"],
                                     "home": k == hk,
                                     "air": len(row) > 2 and row[2] == "AIR"})
        roster = {"forwards": [], "defense": [], "goalies": []}
        bench = set(reserve.get(k, []))
        for pid, p in plist.items():
            if p.get("team") != k or pid in bench:
                continue
            row = {"pid": pid, "name": p.get("name", pid),
                   "pos": p.get("pos", ""), "slot": p.get("slot", ""),
                   "aav": p.get("aav"), "yrs": p.get("yrs")}
            if p.get("pos") == "G":
                arr = (stats or {}).get("goalies", {}).get(
                    pid, [0, 0, 0, 0, 0, 0, 0])
                gp, w, l, otl, sa, sv, so = arr
                row.update(gp=gp, w=w, l=l, otl=otl, so=so,
                           svpct=round(sv / sa, 3) if sa else 0.0,
                           gaa=round((sa - sv) / gp, 2) if gp else 0.0)
                roster["goalies"].append(row)
            else:
                arr = (stats or {}).get("skaters", {}).get(
                    pid, [0, 0, 0, 0, 0, 0])
                gp, g, a, pim, gwg, hat = arr
                row.update(gp=gp, g=g, a=a, p=g + a, pim=pim)
                side = ("defense" if p.get("pos") in ("D", "LD", "RD")
                        else "forwards")
                roster[side].append(row)
        for group in roster.values():
            group.sort(key=lambda r: (r.get("slot", ""), r["name"]))
        out_list = [{"player": o.get("player"),
                     "games": max(0, o.get("until", 0) - st.get("game_no", 0))}
                    for o in st.get("out", {}).get(k, [])]
        page = {"schema": 1, "season": st.get("season", 1), "updated": today,
                **m,
                "record": {f: t[f] for f in ("gp", "w", "l", "otl", "pts")},
                "last10": last10, "streak": streak,
                "results": res[-25:], "upcoming": upcoming,
                "roster": roster, "out": out_list}
        _write(base / "teams" / f"{k}.json", page)

    _write(Path(root) / "sports" / "index.json",
           {"schema": 1, "updated": today,
            "sports": [{"key": SPORT, "name": "The League",
                        "trophy": "The Boreal Lantern",
                        "season": st.get("season", 1)}]})
