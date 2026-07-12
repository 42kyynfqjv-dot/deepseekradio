"""Draft Night — a fictional entry draft, OFFSEASON broadcast canon only.

Mirrors deadline.py's reveal clock, but the underlying event is minted right
here rather than read from the economy log: a seeded 32-prospect draft class
and a reverse-standings pick order, revealed one pick at a time across the
broadcast window. The prospects are NOT written into players-s{n}.json (the
season rollover owns rosters and mints its own draftees under economy.py) --
this module produces only what the BOOTH says on draft night, recorded to
`data/league/draft-s{n}.json` so a later show never contradicts who went
where. Derive-don't-store still holds: the whole class and order are pure
seeded functions; the recorded file is a convenience cache of that canon,
and re-recording the same season reproduces it byte-for-byte.

Leaf module: stdlib only, no season/orchestrator/engine import. Names are
drawn from the same invented pools players.py uses (livegame.FIRST_NAMES /
LAST_NAMES, plain data tuples), so every prospect is already inside the
nameguard-safe fiction.

Frozen row contract (docs/designs/town-texture-and-engines.md, Row 6):
  draft_class(season) -> list        (32 prospects, ages 18-19, balanced pos)
  order(standings) -> list           (reverse standings, worst picks first)
  picks_plan(...)/reveal_at(...)/sheet(...)/verify(...)   mirroring deadline
  record(season, ...) -> dict        (atomic write to draft-s{n}.json)
"""
from __future__ import annotations

import json
import os
import random
import re
from pathlib import Path

from ..livegame import FIRST_NAMES, LAST_NAMES

SIDE = Path("data/league")

# balanced 32-prospect position slate: forward-heavy like a real class, a
# handful of blueliners, a couple of goalies -- sums to exactly 32.
_POS_SLATE = (["C"] * 7 + ["LW"] * 6 + ["RW"] * 6 + ["LD"] * 5
              + ["RD"] * 5 + ["G"] * 3)

# scouting one-liners: a generic bank plus position flavor, all in-universe,
# no real names/teams (safe by construction -- pure hockey texture).
_SCOUT_GENERIC = (
    "a high-floor two-way player who never cheats a shift",
    "boom-or-bust upside, the room is split on the ceiling",
    "plays a heavy game, wins the wall battles",
    "elite skating, the rest is projection",
    "old for the class but pro-ready right now",
    "raw, but the compete level is off the charts",
    "a coach's dream, does the little things",
    "quiet point producer, better than the box score",
    "went under the radar at the combine, tools are real",
    "high hockey IQ, sees the ice a beat ahead",
    "took a huge second-half leap, riser all spring",
    "safe pick, projects as a dependable middle-sixer",
)
_SCOUT_POS = {
    "C": ("wins draws and drives the middle of the ice",
          "a pass-first pivot with a pro release"),
    "LW": ("a north-south winger who finishes his checks",
           "sneaky-good hands down the wall"),
    "RW": ("a shoot-first winger with a heavy one-timer",
           "plays bigger than his size on the forecheck"),
    "LD": ("a smooth-skating puck-mover from the back end",
           "defends the rush as well as anyone in the class"),
    "RD": ("a right-shot blueliner, and those don't grow on trees",
           "quarterbacks a power play, walks the line with poise"),
    "G": ("calm in the crease, tracks pucks through traffic",
          "athletic and raw, a project with a huge ceiling"),
}


def draft_class(season: int) -> list:
    """32 seeded prospects for `season`'s entry draft: ages 18-19, positions
    balanced (`_POS_SLATE`), each with a league-unique invented name and a
    scouting one-liner. `rank` is the pre-draft board ranking (1 = consensus
    #1). Pure and deterministic in `season`."""
    rng = random.Random(f"draftclass:{season}")
    slate = list(_POS_SLATE)
    rng.shuffle(slate)
    used: set = set()
    out = []
    for i, pos in enumerate(slate):
        while True:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            if name not in used:
                used.add(name)
                break
        age = rng.choice((18, 19))
        flavor = _SCOUT_POS.get(pos, ())
        pool = flavor + _SCOUT_GENERIC
        out.append({"rank": i + 1, "name": name, "pos": pos, "age": age,
                    "by": season - age, "scouting": rng.choice(pool)})
    return out


def _pts_pct(row: dict) -> float:
    gp = row.get("gp", 0)
    pts = row.get("w", 0) * 2 + row.get("otl", 0)
    return (pts / (2 * gp)) if gp else 0.5


def order(standings: dict) -> list:
    """Reverse standings -> draft order: worst points-percentage picks first.
    `standings` is season.json's `st["league"]` ({team: {"w","l","otl","gp",
    ...}}). Ties break on team key so the order is fully deterministic."""
    return sorted(standings.keys(), key=lambda k: (_pts_pct(standings[k]), k))


def picks_plan(draftees: list, draft_order: list, window_secs: int,
               seed: str) -> dict:
    """First-round pick plan: prospect i (by board rank) goes to the team
    holding pick i in `draft_order`, revealed sequentially across
    `window_secs`. Unlike deadline trades, draft picks happen IN ORDER, so
    offsets are strictly increasing (pick k centered in its 1/n slot) --
    monotonic by construction. `seed` is accepted for signature parity with
    deadline; the deterministic spacing needs no randomness, but a small
    seeded intra-slot jitter keeps the cadence from feeling metronomic while
    preserving order."""
    win = max(0, int(window_secs))
    n = min(len(draftees), len(draft_order))
    rng = random.Random(f"draft:{seed}")
    picks = []
    prev = -1
    for i in range(n):
        slot = win / n if n else 0
        base = slot * i
        jitter = rng.uniform(0, slot * 0.4) if slot else 0
        off = int(base + jitter)
        if off <= prev:                     # guarantee strictly increasing
            off = prev + 1
        prev = off
        picks.append({"pick": i + 1, "team": draft_order[i],
                      "prospect": draftees[i], "offset": off})
    return {"window_secs": win, "quiet": n == 0, "picks": picks}


def reveal_at(plan: dict, cursor: int) -> list:
    """Picks a listener could know at `cursor` seconds in: every pick whose
    offset <= cursor, in pick order. Prefix-only growth -> monotonic."""
    return [p for p in plan.get("picks", []) if p["offset"] <= cursor]


def sheet(revealed: list, names: dict) -> str:
    """The authoritative DRAFT NIGHT facts block: each revealed pick with the
    team KEY resolved to its on-air name and the prospect's name/position/age
    and scouting line. Only truth; verify() holds the read to it."""
    names = names or {}
    ln = ["DRAFT NIGHT SHEET (authoritative — the ONLY picks that exist):"]
    if not revealed:
        ln.append("- we are on the clock: no picks are in yet.")
        return "\n".join(ln)
    for p in revealed:
        team = names.get(p.get("team"), p.get("team", "?"))
        pr = p.get("prospect", {})
        ln.append(f"- Pick {p['pick']}: {team} select {pr.get('name', '?')}, "
                  f"{pr.get('pos', '?')}, age {pr.get('age', '?')} "
                  f"— {pr.get('scouting', '')}".rstrip(" —"))
    return "\n".join(ln)


def verify(texts: list, revealed: list, names: dict,
           full_class: list | None = None) -> bool:
    """Nothing airs that isn't on the board. Hard guard (mirrors
    deadline.verify): every league team named in the read must be holding a
    revealed pick -- an empty board rejects any team mention, the stop against
    announcing a pick before it's in. Optional prospect guard: if `full_class`
    (this season's whole 32-prospect list) is supplied, any prospect SURNAME
    from the class that shows up in the read must belong to a REVEALED pick --
    catches "the pick is <unrevealed prospect>". Player names aren't forced
    when `full_class` is omitted (surnames overlap ordinary words less
    predictably than team nicks), keeping the default a strict superset of
    deadline.verify's contract."""
    names = names or {}
    body = " " + " ".join(texts).lower() + " "

    from .deadline import _TEAM_STOP
    allowed_teams = set()
    for p in revealed:
        nm = names.get(p.get("team"), p.get("team"))
        if nm:
            allowed_teams.add(str(nm).lower())
            allowed_teams.add(str(nm).split()[-1].lower().strip("()"))
    for _k, nm in names.items():
        if not nm:
            continue
        full = str(nm).lower()
        nick = full.split()[-1].strip("()")
        for probe in {full, nick} - _TEAM_STOP:
            if probe and re.search(rf"\b{re.escape(probe)}\b", body) \
                    and probe not in allowed_teams:
                return False

    if full_class:
        revealed_last = {p.get("prospect", {}).get("name", "").split()[-1].lower()
                         for p in revealed}
        revealed_last.discard("")
        for pr in full_class:
            last = str(pr.get("name", "")).split()[-1].lower()
            if last and re.search(rf"\b{re.escape(last)}\b", body) \
                    and last not in revealed_last:
                return False
    return True


# ---------------------------------------------------------------- recording

def _save(name: str, obj: dict, root: Path | None = None) -> None:
    """Atomic tmp+replace with a .bak copy — the engine.save_side pattern,
    restated here so this leaf never imports the integration spine."""
    p = (root or SIDE) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(obj))
    if p.exists():
        try:
            import shutil
            shutil.copy2(p, p.with_suffix(".bak"))
        except Exception:
            pass
    tmp.replace(p)


def record(season: int, standings: dict, root: Path | None = None) -> dict:
    """Freeze this season's draft as broadcast canon at
    `data/league/draft-s{n}.json`. Idempotent: if the file already exists it
    is loaded and returned UNCHANGED (the booth's earlier canon wins — a later
    show can never contradict what already aired), otherwise the seeded class
    + reverse-standings first round is built and written atomically.

    Body: {"schema":1, "season":n, "order":[team,...],
    "round1":[{"pick","team","prospect"}...], "class":[<all 32 prospects>]}.
    Prospects are recorded here ONLY -- never folded into players-s{n}.json."""
    root = root or SIDE
    p = root / f"draft-s{season}.json"
    for cand in (p, p.with_suffix(".bak")):
        try:
            if cand.exists():
                return json.loads(cand.read_text())
        except Exception:
            continue
    cls = draft_class(season)
    ordr = order(standings)
    n = min(len(cls), len(ordr))
    round1 = [{"pick": i + 1, "team": ordr[i], "prospect": cls[i]}
              for i in range(n)]
    body = {"schema": 1, "season": season, "order": ordr,
            "round1": round1, "class": cls}
    _save(f"draft-s{season}.json", body, root)
    return body
