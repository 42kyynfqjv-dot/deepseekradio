"""HALFWAY HOT 10 — the code-owned weekly chart sim (docs/designs/music-halfway.md
§4). Mirrors `src/league/stats.py`: code owns every number, the LLM narrates,
`chartguard.py` verifies. Every function below is a pure function of its
arguments (catalog dict, week string, seed string) — no dependency on real
play logs, no hidden global state. `chart()` is the one impure entry point
(derive-once-store file IO under `data/music/`); everything it calls is pure.

Schema (frozen, §4/§2):
  data/music/catalog.json     {"schema":1, "artists": {aid: {...}},
                                "tracks": {tid: {...}}} — authored off-box,
                                deployed read-only to the box (§2/§3). This
                                module only reads it.
  data/music/hot10-s{n}.json  {"schema":1, "season": n,
                                "weeks": {week: <week-record>}}
    where a week-record is exactly the design's worked example:
      {"schema":1, "week":"2026-07-10", "season":1,
       "chart":[{"tid","rank","last","peak","weeks","pts","bullet","debut"}],
       "hot_shot": tid|None, "droppers":[tid], "gainer": tid|None,
       "retired":[tid], "history": {tid:[pts,...]}}

**Schema-friction notes (frozen contract, conforming as given):**
  - The design shows hot10-s{n}.json AS a single week-record (top-level
    "week" key holding one string). That shape is exactly what `roll_week`
    returns for one week; the *sidecar file* wraps a `{"weeks": {...}}` dict
    of those records so a whole season's worth of weeks persists — the
    natural reading of "per-season shard" (`stats-s{n}.json`'s own analogue)
    combined with the task's "history append-only" requirement: `weeks` keys
    are written once and never edited again (see `chart()`). This also
    *is* the mechanism behind "aired weeks read-only canon" (§6): once a
    week is a key in `weeks`, `chart()` returns that stored record forever,
    never re-derives it, even if catalog.json or the scoring constants
    change later.
  - `roll_week`'s two extra return fields beyond the doc's worked example
    (`"season"` is in the doc; `"retired_ever"` is not) carry the cumulative
    ever-retired set forward across weeks without needing a second sidecar
    or a mutable field on catalog.json (which must stay off-box-authored and
    read-only per §2/§3). `retired` (no suffix) stays exactly what the doc
    shows: this week's *newly* retired tids.
  - `score_week`/`roll_week`/`narrate` take a `catalog` argument beyond the
    doc's terse `chart.py` sketch needs to resolve titles/artist names for
    narration — the doc's own §6 worked example ("1. Sustain — Merrill
    Sackville") is unreachable from tid alone. `catalog.py`'s `load`/
    `eligible` are folded into this module rather than split into a second
    file, per this build's five-deliverable scope.
  - Season boundaries: `_season_of(week)` buckets weeks into fixed 52-week
    blocks from `SEASON0_START` ("2026-07-10", the doc's own first chart
    week). Crossing a boundary starts a fresh chart (`prev=None`) — the
    same simplifying choice hockey makes with a new `stats-s{n}.json` each
    season. A season's shard is thus naturally bounded to ~52 entries,
    serving the same purpose as `_prune_boxes`' explicit deletion without
    needing one.
  - `seed` is exactly the doc's `f"hot10:{season}:{week}"`, but a track's
    intrinsic quality/life-cycle shape must be *week-invariant* ("fixed per
    track from the seed") while the same seed varies weekly by design. This
    module derives a week-invariant sub-seed (`_season_seed`) by stripping
    the week suffix back off — both readings of "the seed" are satisfied:
    the week-varying seed still gates weekly noise (spins/streams/sales),
    the season-scoped seed gates the fixed quality/shape per track.
"""
from __future__ import annotations

import json
import os
import random
import shutil
from datetime import date as _Date, timedelta
from pathlib import Path

SIDE = Path("data/music")

# ---------------------------------------------------------------- constants
# All tuned here, not scattered — the doc's own instruction ("the numbers are
# constants at the top of chart.py, tuned by the §8 calibration"). §8's
# calibration script itself is out of this build's five-deliverable scope.

CHART_SIZE = 10
SEASON0_START = "2026-07-10"     # the doc's own first chart week
WEEKS_PER_SEASON = 52

# Blended score weights (§4: "STREAM_W ~ SPIN_W >> SALES_W")
SPIN_W, STREAM_W, SALES_W = 0.40, 0.40, 0.05
SPIN_MAX, STREAM_MAX, SALES_MAX = 14000.0, 14000.0, 6000.0
NOISE_LO, NOISE_HI = 0.85, 1.15

# Per-track life-cycle shape (heat rises to a peak, then decays)
QUALITY_LO, QUALITY_HI = 0.55, 1.0     # intrinsic quality q
RISE_LO_WEEKS, RISE_HI_WEEKS = 2.0, 4.0  # weeks to climb to peak
DECAY_LO, DECAY_HI = 0.78, 0.94          # per-week retention after peak

# Recurrent retirement thresholds (§4, any one trips it)
RETIRE_A_WEEKS, RETIRE_A_RANK = 8, 6     # back half after two months
RETIRE_B_WEEKS, RETIRE_B_RANK = 12, 3
RETIRE_C_WEEKS = 16                      # regardless of rank

HISTORY_TAIL = 20   # trailing points kept per charted track (bounded tail)


# ---------------------------------------------------------------- catalog

def load_catalog(root: Path | None = None) -> dict:
    """Parse + minimally validate catalog.json (§2's schema)."""
    p = (root or SIDE) / "catalog.json"
    data = json.loads(p.read_text())
    if data.get("schema") != 1:
        raise ValueError(f"unsupported catalog schema: {data.get('schema')!r}")
    if not isinstance(data.get("artists"), dict) or not isinstance(data.get("tracks"), dict):
        raise ValueError("catalog.json missing artists/tracks")
    return data


def eligible(catalog: dict, week: str, retired: frozenset = frozenset()) -> list:
    """tids released & eligible-from by `week`, and not (yet) retired.
    Deterministic order (sorted) — callers re-sort by score anyway, but a
    stable base order keeps this function's own output reproducible."""
    out = []
    for tid, tr in catalog.get("tracks", {}).items():
        if tid in retired:
            continue
        released = tr.get("released", "")
        elig_from = tr.get("eligible_from", released)
        if released > week or elig_from > week:
            continue
        out.append(tid)
    return sorted(out)


# ---------------------------------------------------------------- dates/seed

def _season_of(week: str) -> int:
    """Weeks before SEASON0_START must NOT clamp to 0: clamping made every
    week before the start read as season 1 too (same as week 0), so
    `chart()`'s "is prev_week still in this season" recursion guard never
    saw a season boundary and walked `_prev_week` back through calendar
    history forever (RecursionError on the very first call). Floor division
    on a possibly-negative `weeks_since` naturally yields season 0, -1, ...
    for anything before the doc's first chart week, which differs from
    season 1 and stops the recursion exactly where `chart()`'s own
    docstring promises it will (bounded to WEEKS_PER_SEASON calls)."""
    d, d0 = _Date.fromisoformat(week), _Date.fromisoformat(SEASON0_START)
    weeks_since = (d - d0).days // 7
    return 1 + weeks_since // WEEKS_PER_SEASON


def _prev_week(week: str) -> str:
    return (_Date.fromisoformat(week) - timedelta(days=7)).isoformat()


def _season_seed(seed: str) -> str:
    """seed is 'hot10:{season}:{week}'; strip the week suffix so a track's
    intrinsic quality/shape stays fixed across weeks (see module docstring)."""
    parts = seed.split(":")
    return ":".join(parts[:2]) if len(parts) >= 2 else seed


def _weeks_since_release(released: str, week: str) -> int:
    return (_Date.fromisoformat(week) - _Date.fromisoformat(released)).days // 7


# ---------------------------------------------------------------- score_week

def _quality(tid: str, sseed: str) -> float:
    return random.Random(f"{sseed}:quality:{tid}").uniform(QUALITY_LO, QUALITY_HI)


def _lifecycle_shape(tid: str, sseed: str) -> tuple:
    r = random.Random(f"{sseed}:shape:{tid}")
    return (r.uniform(RISE_LO_WEEKS, RISE_HI_WEEKS), r.uniform(DECAY_LO, DECAY_HI))


def _heat(catalog: dict, tid: str, week: str, sseed: str) -> float:
    """Life-cycle curve: rises after release, peaks, decays; scaled by the
    track's fixed intrinsic quality. 0.0 before release (so score_week is
    naturally 0 for any not-yet-released track — no separate branch needed
    for 'last week's points' on a track that didn't exist yet)."""
    track = catalog.get("tracks", {}).get(tid)
    if not track:
        return 0.0
    t = _weeks_since_release(track["released"], week)
    if t < 0:
        return 0.0
    rise, decay = _lifecycle_shape(tid, sseed)
    q = _quality(tid, sseed)
    climb = min(1.0, (t + 1) / rise)
    fall = decay ** max(0, t - rise)
    return q * climb * fall


def score_week(catalog: dict, tid: str, week: str, seed: str) -> int:
    """Blended points for one track in one week — pure function of
    (catalog, tid, week, seed). §4: spins/streams roughly equal and
    dominant, sales a deliberately small lever (mirrors the "divisor 10"
    era). Safe to call for ANY tid/week, charted or not, past or future —
    used both to build this week's chart and to recover 'what would this
    track have scored last week' for gain/bullet computation."""
    sseed = _season_seed(seed)
    h = _heat(catalog, tid, week, sseed)
    if h <= 0:
        return 0
    rs = random.Random(f"{seed}:spins:{tid}")
    rt = random.Random(f"{seed}:streams:{tid}")
    ra = random.Random(f"{seed}:sales:{tid}")
    spins = h * SPIN_MAX * rs.uniform(NOISE_LO, NOISE_HI)
    streams = h * STREAM_MAX * rt.uniform(NOISE_LO, NOISE_HI)
    sales = h * SALES_MAX * ra.uniform(NOISE_LO, NOISE_HI)
    return round(SPIN_W * spins + STREAM_W * streams + SALES_W * sales)


# ---------------------------------------------------------------- roll_week

def roll_week(prev: dict | None, catalog: dict, week: str, seed: str) -> dict:
    """Roll one new chart week from `prev` (last week's week-record, or None
    for a season's first week / a fresh season). Pure — no file IO. Returns
    a week-record exactly matching §4's schema (plus `retired_ever`, see
    module docstring)."""
    season = _season_of(week)
    prev_chart = list((prev or {}).get("chart", []))
    prev_by_tid = {r["tid"]: r for r in prev_chart}
    retired_ever = set((prev or {}).get("retired_ever", []))
    prev_week = _prev_week(week)

    # --- recurrent retirement: evaluated on LAST week's tenure/rank, before
    # this week's pool is even built, so a forced retiree naturally becomes
    # this week's dropper too (matches the doc's own worked example, where
    # t002 appears in both "droppers" and "retired" the same week).
    newly_retired = []
    for r in prev_chart:
        tid = r["tid"]
        if tid in retired_ever:
            continue
        wk, rk = r["weeks"], r["rank"]
        if ((wk >= RETIRE_A_WEEKS and rk >= RETIRE_A_RANK) or
                (wk >= RETIRE_B_WEEKS and rk >= RETIRE_B_RANK) or
                (wk >= RETIRE_C_WEEKS)):
            newly_retired.append(tid)
    retired_ever |= set(newly_retired)

    pool = eligible(catalog, week, retired=frozenset(retired_ever))
    scored = sorted(((tid, score_week(catalog, tid, week, seed)) for tid in pool),
                     key=lambda x: (-x[1], x[0]))       # deterministic tie-break
    top = scored[:CHART_SIZE]

    chart_rows, gains = [], []
    for rank, (tid, pts) in enumerate(top, start=1):
        prevrow = prev_by_tid.get(tid)
        debut = prevrow is None
        pts_prev = 0 if debut else score_week(catalog, tid, prev_week, seed)
        weeks_on = (prevrow["weeks"] + 1) if prevrow else 1
        peak = min(rank, prevrow["peak"]) if prevrow else rank
        last = prevrow["rank"] if prevrow else 0
        bullet = (not debut) and (pts > pts_prev)
        chart_rows.append({"tid": tid, "rank": rank, "last": last, "peak": peak,
                            "weeks": weeks_on, "pts": pts, "bullet": bullet,
                            "debut": debut})
        if not debut:
            gains.append((tid, pts - pts_prev))

    hot_shot = None
    if prev is not None:
        debuts = [r for r in chart_rows if r["debut"]]
        if debuts:
            hot_shot = min(debuts, key=lambda r: r["rank"])["tid"]

    this_tids = {r["tid"] for r in chart_rows}
    droppers = [r["tid"] for r in prev_chart if r["tid"] not in this_tids]

    gainer = None
    if gains:
        best_tid, best_gain = max(gains, key=lambda x: x[1])
        if best_gain > 0:
            gainer = best_tid

    history = {}
    for r in chart_rows:
        prev_hist = (prev or {}).get("history", {}).get(r["tid"], [])
        history[r["tid"]] = (list(prev_hist) + [r["pts"]])[-HISTORY_TAIL:]

    return {"schema": 1, "week": week, "season": season,
            "chart": chart_rows, "hot_shot": hot_shot,
            "droppers": droppers, "gainer": gainer,
            "retired": newly_retired, "retired_ever": sorted(retired_ever),
            "history": history}


# ---------------------------------------------------------------- deltas/narrate

def deltas(chart: dict) -> dict:
    """Re-shape an already-rolled week-record into a narration-ready deltas
    view. Pure re-derivation of what's already sitting in `chart` — never
    recomputes a fact from the catalog/seed."""
    rows = chart.get("chart", [])
    debuts = [r["tid"] for r in rows if r.get("debut")]
    bullets = [r["tid"] for r in rows if r.get("bullet")]
    longest = max(rows, key=lambda r: r["weeks"])["tid"] if rows else None
    return {"debuts": debuts, "bullets": bullets,
            "hot_shot": chart.get("hot_shot"), "gainer": chart.get("gainer"),
            "droppers": list(chart.get("droppers", [])),
            "retired": list(chart.get("retired", [])),
            "longest_on_chart": longest}


def _title_artist(catalog: dict, tid: str) -> tuple:
    tr = catalog.get("tracks", {}).get(tid, {})
    title = tr.get("title", tid)
    artist = catalog.get("artists", {}).get(tr.get("artist"), {}).get("name", "")
    return title, artist


def narrate(chart: dict, catalog: dict) -> list:
    """The SCOREBOARD-register prompt block (§6): every fact the host may
    quote, spelled out as authoritative lines, in exactly the "do-not-alter"
    register scoreguard/civicguard's prompt blocks already use. `catalog` is
    needed to resolve titles/artist names (see module docstring)."""
    d = deltas(chart)
    row_by_tid = {r["tid"]: r for r in chart.get("chart", [])}
    lines = [f"HOT 10 — WEEK OF {chart.get('week')} "
             "(authoritative, do not change any number):"]
    for r in chart.get("chart", []):
        title, artist = _title_artist(catalog, r["tid"])
        lw = "NEW" if r["debut"] else (str(r["last"]) if r["last"] else "—")
        tags = []
        if r["debut"]:
            tags.append("HOT SHOT DEBUT" if r["tid"] == d["hot_shot"] else "debut")
        if r["bullet"]:
            tags.append("▲bullet")
        if r["tid"] == d["gainer"]:
            tags.append("Greatest Gainer")
        tagstr = f" {' · '.join(tags)}" if tags else ""
        lines.append(f"{r['rank']}. {title} — {artist} "
                     f"(LW {lw}, {r['weeks']} wks, peak {r['peak']}){tagstr}")
    if d["hot_shot"]:
        title, artist = _title_artist(catalog, d["hot_shot"])
        lines.append(f"HOT SHOT DEBUT: {title} — {artist}")
    if d["droppers"]:
        names = "; ".join(f"{_title_artist(catalog, t)[0]} — "
                          f"{_title_artist(catalog, t)[1]}" for t in d["droppers"])
        lines.append(f"DROPPED OUT: {names}")
    if d["gainer"]:
        title, artist = _title_artist(catalog, d["gainer"])
        lines.append(f"BIGGEST JUMP: {title} — {artist}")
    if d["longest_on_chart"]:
        tid = d["longest_on_chart"]
        title, artist = _title_artist(catalog, tid)
        wks = row_by_tid.get(tid, {}).get("weeks", 0)
        lines.append(f"LONGEST ON CHART: {title} — {artist} ({wks} wks)")
    return lines


# ---------------------------------------------------------------- sidecar IO

def _shard_path(season: int, root: Path | None = None) -> Path:
    return (root or SIDE) / f"hot10-s{season}.json"


def _load_shard(season: int, root: Path | None = None) -> dict:
    p = _shard_path(season, root)
    for cand in (p, p.with_suffix(".bak")):
        try:
            if cand.exists():
                return json.loads(cand.read_text())
        except Exception:
            continue
    return {"schema": 1, "season": season, "weeks": {}}


def _save_shard(season: int, obj: dict, root: Path | None = None) -> None:
    """Atomic tmp+replace with a .bak copy — the established sidecar
    pattern (src/league/engine.py's save_side)."""
    p = _shard_path(season, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(obj))
    if p.exists():
        try:
            shutil.copy2(p, p.with_suffix(".bak"))
        except Exception:
            pass
    tmp.replace(p)


def chart(week: str, catalog: dict | None = None, root: Path | None = None) -> dict:
    """Derive-once-store entry point (§4/§6). If `week` was already rolled
    for its season, returns the STORED record unchanged — never re-derives
    it, even if catalog.json or the constants above change later. That's
    what makes an aired week read-only canon: chartguard's facts for a past
    week always come from this stored record, not a fresh roll_week() call.
    A missing/lost shard re-derives the whole season from week 1 forward —
    derive-don't-store at the season level, exactly like a lost box score
    re-deriving from its own seed. Recursively backfills any gap within the
    same season (bounded to WEEKS_PER_SEASON calls)."""
    season = _season_of(week)
    shard = _load_shard(season, root)
    if week in shard.get("weeks", {}):
        return shard["weeks"][week]

    catalog = catalog if catalog is not None else load_catalog(root)
    prev_week = _prev_week(week)
    prev = None
    if _season_of(prev_week) == season:
        prev = shard["weeks"].get(prev_week) or chart(prev_week, catalog, root)

    seed = f"hot10:{season}:{week}"
    record = roll_week(prev, catalog, week, seed)

    shard = _load_shard(season, root)   # reload: recursion above may have moved it
    shard.setdefault("weeks", {})[week] = record
    _save_shard(season, shard, root)
    return record
