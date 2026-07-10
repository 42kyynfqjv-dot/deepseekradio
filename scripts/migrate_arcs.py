#!/usr/bin/env python3
"""Bootstrap the arcs+census sidecars from today's live lore_state.

Row F of docs/designs/arcs-census-final.md (backbone: arcs-census-continuity.md
§9 "Bootstrap / migration"). Births `data/arcs/arcs.json` +
`data/arcs/civilians.json` from `lore_state`'s existing arcs (and reserves
caller names out of `station_state["callers_today"]`), then writes
`data/arcs/canon-diff-arcs.txt` — a from-scratch, honest report of every
AIRED-stamped fact the new sidecars would assert that the source never proved
aired. A clean migration produces that file EMPTY (cutover requires empty),
because this script lifts only structure — titles, premises, the current
`latest` weave-in line, and a forward-scheduled PAYOFF beat — and stamps NO
fact, beat, or appearance as already-aired. Canon starts clean and only grows
from aired-forward facts (the continuity-fidelity guarantee: we never assert a
"fact" about a past call/beat we didn't record).

GATE OFF THE WHOLE TIME. This script writes the two sidecars and the diff and
NOTHING else — it NEVER creates `data/arcs/ENABLED`, and it NEVER writes
`lore_state.json` / `station_state.json` (read-only). With the gate absent the
orchestrator skips the desk's two picks and runs canonguard in scope="none"
(pass-through), so behavior stays byte-identical; rollback is `rm` the sidecars.
Mirrors scripts/migrate_league_v2.py's gate/canon-diff discipline verbatim.

Idempotent: re-running is ADDITIVE and PRESERVING. An arc already present in
`arcs.json` (keyed by a stable title slug) is left exactly as it is (dates and
all), so a second run — even on a later day — never re-derives, duplicates, or
drifts it; only arcs new to the sidecar are lifted. `used_names` is unioned and
de-duplicated; existing census residents are untouched.

Runnable from the repo root or /opt/kaos/app — every path is cwd-relative,
exactly like season.py's `_PATH`. All paths are also injectable (root/
lore_path/station_path) so the test harness can run the whole thing in a temp
dir with synthetic state.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import date as _date, timedelta
from pathlib import Path

# Frozen from src/arcs.py (component B) — the state-machine stage ladder.
STAGES = ("SEEDED", "RISING", "COMPLICATION", "CRISIS", "PAYOFF", "LORE")

DEFAULT_ROOT = "data/arcs"
DEFAULT_LORE = "lore_state.json"
DEFAULT_STATION = "station_state.json"

# Legacy arcs are mundane by construction (arcs._EDITOR forbids conspiracy /
# paranormal / sports registers); we only ever *narrow* to civic when the
# premise is plainly civic. We never mint conspiracy/dreamcourt/sports from a
# legacy arc — that would invent a register the arc never aired in.
_CIVIC_RE = re.compile(
    r"\b(election|ballot|council|commissioner|statehouse|assembly|mayor|"
    r"zoning|ordinance|permit|referendum|precinct|caucus|petition)\b", re.I)


# ----------------------------------------------------------------- sidecar IO

def _p(root: Path, name: str) -> Path:
    return root / name


def _load_side(root: Path, name: str, default: dict) -> dict:
    """Sidecar read, the established trust rule: live file, then `.bak`, then a
    fresh default (NEVER silently resets a live spine on a read race)."""
    for cand in (_p(root, name), _p(root, name).with_suffix(".bak")):
        try:
            if cand.exists():
                return json.loads(cand.read_text())
        except Exception:
            continue
    return json.loads(json.dumps(default))  # deep copy of the default


def _save_side(root: Path, name: str, obj: dict) -> None:
    """Atomic tmp+replace with a `.bak` copy — statehouse.save_side discipline."""
    root.mkdir(parents=True, exist_ok=True)
    p = _p(root, name)
    tmp = p.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(obj, indent=2))
    if p.exists():
        try:
            shutil.copy2(p, p.with_suffix(".bak"))
        except Exception:
            pass
    tmp.replace(p)


# ----------------------------------------------------------------- derivation

def _slug(title: str) -> str:
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return "-".join(words[:5]) or "arc"


def arc_id(title: str, taken: set) -> str:
    """Stable, collision-free id derived from the title so a re-run maps the
    same source arc to the same key (idempotency by construction)."""
    base = f"arc-{_slug(title)}"
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def _stage_for(day: int, max_days: int) -> tuple[str, int]:
    """Map a legacy arc's day/max_days progress onto the pre-payoff ladder
    (SEEDED..CRISIS). An active arc has NOT paid off, so it is never lifted at
    PAYOFF/LORE — the payoff is a forward-scheduled, unaired beat."""
    md = max(1, int(max_days or 1))
    d = max(1, int(day or 1))
    ratio = (d - 1) / md if md else 0.0
    idx = min(3, max(0, int(ratio * 4)))  # 0=SEEDED .. 3=CRISIS
    return STAGES[idx], idx


def _register_for(arc: dict) -> str:
    blob = f"{arc.get('title', '')} {arc.get('premise', '')} {arc.get('latest', '')}"
    return "civic" if _CIVIC_RE.search(blob) else "mundane"


def migrate_arc(arc: dict, today: str, taken: set) -> dict:
    """Lift ONE legacy arc into the arcs.json schema (design-doc §2 field names,
    ALIGNED to the shipped `src/arcs.py` state machine's actual field name
    `payoff_on` — component B's real consumer, not the older `payoff_date`
    label in the frozen doc's illustrative example — so a migrated arc never
    KeyErrors the first time `daily_tick`/`gate_payoff` reads it post-cutover).
    Writes NO aired-stamped fact/beat: facts[] is empty, the only beat is a
    pending, forward-scheduled PAYOFF on the next Scramble. Everything
    code-owned (dates/stage/register/id/force_payoff/graduated); the
    LLM-authored `latest`/`title`/`premise` are preserved verbatim as free
    text, never promoted into the guarded fact table (that would assert a
    canon slot the arc never aired)."""
    title = arc.get("title", "")
    aid = arc_id(title, taken)
    stage, stage_idx = _stage_for(arc.get("day", 1), arc.get("max_days", 1))
    remaining = max(1, int(arc.get("max_days", 1)) - int(arc.get("day", 1)))
    payoff_on = (_date.fromisoformat(today) + timedelta(days=remaining)).isoformat()
    directive = f"wind \"{title}\" to its mundane payoff"
    return {
        "id": aid,
        "title": title,
        "premise": arc.get("premise", ""),
        "setting": "",  # never invented — the legacy arc never recorded one
        "register": _register_for(arc),
        "stage": stage,
        "stage_idx": stage_idx,
        # honest: the arc *entered the sidecar* today. We do not fabricate a
        # past open date we never recorded; its remaining lifespan is preserved
        # via payoff_on so the state machine resumes at the right pace.
        "opened": today,
        "payoff_on": payoff_on,
        "cast": {"civilians": [], "canon": []},
        "status": "active",
        "force_payoff": False,
        "graduated": False,
        "facts": [],  # <- no invented aired canon (the whole point of the diff)
        "beats": [
            {"bid": "b-payoff", "due": payoff_on, "show": "morning_scramble",
             "stage": "PAYOFF", "directive": directive, "fact": directive,
             "status": "pending", "aired_date": None},
        ],
        "latest": arc.get("latest", ""),
    }


def _reserved_names(station: dict) -> list[str]:
    """Caller names to reserve (best-effort) so a fresh mint post-cutover can
    never collide with somebody who has already called. Past callers weren't
    persisted as records, so they are name-reserved, never resurrected."""
    out = list(station.get("callers_today", []) or [])
    return [n for n in out if isinstance(n, str) and n.strip()]


# ------------------------------------------------------------------ canon-diff

def compute_canon_diff(arcs_state: dict, civ_state: dict) -> list[str]:
    """A from-scratch, honest divergence report (mirrors migrate_league_v2's
    canon-diff G6). Walks the ACTUAL written sidecar content and lists every
    place it asserts something as already-AIRED — which, for a fidelity
    migration that invents no past, MUST be nothing. Not forced empty: if a
    future edit ever stamped a fact/beat/appearance aired, this reports it
    instead of hiding it. Cutover requires the file empty."""
    diffs: list[str] = []
    for aid, arc in arcs_state.get("arcs", {}).items():
        for f in arc.get("facts", []):
            if f.get("aired") is not None:
                diffs.append(f"arc {aid}: fact {f.get('fid', '?')} stamped "
                             f"aired={f.get('aired')!r} (migration invents no aired canon)")
        for b in arc.get("beats", []):
            if b.get("status") == "aired" or b.get("aired_date") is not None:
                diffs.append(f"arc {aid}: beat {b.get('bid', '?')} stamped aired "
                             f"(status={b.get('status')!r}, aired_date={b.get('aired_date')!r})")
        # structure sanity — a lifted arc must carry a guaranteed forward payoff
        if not any(b.get("stage") == "PAYOFF" for b in arc.get("beats", [])):
            diffs.append(f"arc {aid}: no PAYOFF beat scheduled (payoff not guaranteed)")
    for cid, rec in civ_state.get("residents", {}).items():
        for f in rec.get("facts", []):
            if f.get("aired") is not None:
                diffs.append(f"civilian {cid}: fact {f.get('fid', '?')} stamped "
                             f"aired={f.get('aired')!r} (past calls not recorded — none resurrected)")
        for ap in rec.get("appearances", []):
            if ap.get("aired"):
                diffs.append(f"civilian {cid}: appearance {ap.get('date')!r} stamped aired")
    return diffs


# ------------------------------------------------------------------- main

_ARCS_DEFAULT = {"schema": 1, "seq": 0, "arcs": {}, "recent_settings": []}
_CIV_DEFAULT = {"schema": 1, "residents": {}, "used_names": [], "roster_by_hood": {}}


def migrate(*, root: str | Path = DEFAULT_ROOT,
            lore_path: str | Path = DEFAULT_LORE,
            station_path: str | Path = DEFAULT_STATION,
            today: str | None = None) -> dict:
    """Run the whole migration. Returns a result dict. Never raises on a
    normal 'nothing to do' state; genuine bugs still raise. GATE UNTOUCHED —
    this never creates `<root>/ENABLED`."""
    root = Path(root)
    today = today or f"{_date.today():%Y-%m-%d}"

    lore_p, station_p = Path(lore_path), Path(station_path)
    lore = {}
    if lore_p.exists():
        try:
            lore = json.loads(lore_p.read_text())
        except Exception:
            lore = {}
    station = {}
    if station_p.exists():
        try:
            station = json.loads(station_p.read_text())
        except Exception:
            station = {}

    # PRESERVE existing sidecars (idempotency): read live -> .bak -> default.
    arcs_state = _load_side(root, "arcs.json", _ARCS_DEFAULT)
    civ_state = _load_side(root, "civilians.json", _CIV_DEFAULT)
    arcs_state.setdefault("schema", 1)
    arcs_state.setdefault("seq", 0)
    arcs_state.setdefault("arcs", {})
    arcs_state.setdefault("recent_settings", [])
    civ_state.setdefault("schema", 1)
    civ_state.setdefault("residents", {})
    civ_state.setdefault("used_names", [])
    civ_state.setdefault("roster_by_hood", {})

    taken = set(arcs_state["arcs"].keys())
    existing_titles = {a.get("title") for a in arcs_state["arcs"].values()}

    # 1. Arcs — lift only ACTIVE legacy arcs new to the sidecar. Done arcs are
    # transient (the legacy tick lingers them one air-day then drops them);
    # lifting a paid-off arc as a fresh scheduled arc would fabricate a future
    # payoff for a story that already ended, so they are deliberately skipped.
    lifted, skipped_done, already = 0, 0, 0
    for arc in lore.get("arcs", []):
        if not isinstance(arc, dict) or not arc.get("title"):
            continue
        if arc.get("status") == "done":
            skipped_done += 1
            continue
        if arc.get("title") in existing_titles:
            already += 1
            continue
        rec = migrate_arc(arc, today, taken)
        aid = arc_id(arc["title"], taken)
        taken.add(aid)
        existing_titles.add(arc["title"])
        arcs_state["arcs"][aid] = rec
        lifted += 1

    # recent_settings: carry forward the writer's variety-avoidance memory
    # (NOT canon — just "don't reuse this premise"). De-duped, bounded.
    for prem in lore.get("recent_premises", [])[-15:]:
        if prem and prem not in arcs_state["recent_settings"]:
            arcs_state["recent_settings"].append(prem)
    arcs_state["recent_settings"] = arcs_state["recent_settings"][-30:]

    # 2. Census — born with residents empty (past callers were ephemeral;
    # nothing to resurrect). Reserve caller names so a post-cutover fresh mint
    # can't collide with somebody who has already been on air.
    reserved = _reserved_names(station)
    merged = list(dict.fromkeys(list(civ_state["used_names"]) + reserved))
    civ_state["used_names"] = merged

    _save_side(root, "arcs.json", arcs_state)
    _save_side(root, "civilians.json", civ_state)

    # 3. Canon-diff — honest, from-scratch, over the ACTUAL written content.
    diffs = compute_canon_diff(arcs_state, civ_state)
    diff_path = root / "canon-diff-arcs.txt"
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.write_text("\n".join(diffs) + ("\n" if diffs else ""))

    running_jokes = len(lore.get("running_jokes", []) or [])

    return {
        "ok": not diffs,
        "today": today,
        "root": str(root),
        "arcs_lifted": lifted,
        "arcs_already_present": already,
        "done_arcs_skipped": skipped_done,
        "names_reserved": len(reserved),
        "used_names_total": len(merged),
        "running_jokes_left_in_lore": running_jokes,
        "gate_present": (root / "ENABLED").exists(),
        "canon_diff": diffs,
        "canon_diff_path": str(diff_path),
        "arcs_state": arcs_state,
        "civ_state": civ_state,
    }


def _print_summary(res: dict) -> None:
    print(f"migrate_arcs: {res['today']} -> {res['root']}")
    print(f"  arcs lifted:            {res['arcs_lifted']}")
    print(f"  arcs already present:   {res['arcs_already_present']}")
    print(f"  done arcs skipped:      {res['done_arcs_skipped']} "
          f"(transient one-day payoff lingerers — left to the legacy path)")
    print(f"  caller names reserved:  {res['names_reserved']} "
          f"(used_names now {res['used_names_total']})")
    print(f"  running jokes:          {res['running_jokes_left_in_lore']} "
          f"left in lore untouched (arc->joke is a one-way door; jokes never "
          f"become arcs)")
    print(f"  ENABLED gate present:   {res['gate_present']} "
          f"(must be False — this script never arms the gate)")
    print(f"  canon-diff -> {res['canon_diff_path']} "
          f"({len(res['canon_diff'])} divergence(s))")
    if res["canon_diff"]:
        for line in res["canon_diff"]:
            print(f"    !! {line}")
    else:
        print("    (empty — clean migration, no aired canon invented)")


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ROOT
    result = migrate(root=root)
    _print_summary(result)
    # A non-empty canon-diff means the migration invented aired canon — a bug,
    # since by construction it cannot. Signal it loudly for CI/cutover.
    sys.exit(0 if result["ok"] else 1)
