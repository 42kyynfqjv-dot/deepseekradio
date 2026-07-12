"""Events registry loader + validator (Track D, component 1).

One human-authored file, `events/registry.yaml` (stdlib `yaml`, read once and
cached like `config.yaml`). Each record is either LITERAL-DATED (`date:` /
`dates:`) or DERIVED (`deriver:` names a pure function in the DERIVERS registry
that yields ISO dates from sim state). A record's `show` block is a daypart
fragment in exactly the `schedule.yaml` vocabulary; the overlay copies it verbatim
into the daypart dict.

This module is a LEAF: stdlib only, no orchestrator import, pure but for the
mtime cache. It owns exactly one job from the design's build order:

    "load+validate registry.yaml, cache on mtime; malformed record rejected;
     literal date/dates resolve; missing file => empty list (no-op)."

Validation is a FROZEN field-set check at load. Per risk #8, a record naming an
unknown `engine` is DROPPED with a log line and never handed to dispatch; the same
drop-with-log fate meets any record that fails the schema. A broken registry
degrades to the evergreen station (fewer/zero events), never to a crash.
"""
from __future__ import annotations

import sys
from datetime import time as dtime
from pathlib import Path

import yaml

# Default location: repo-root data file, resolved against cwd like schedule.yaml
# and config.yaml (the orchestrator's other `_load` targets).
DEFAULT_PATH = Path("events/registry.yaml")

SCHEMA = 1

# ── frozen contract surfaces ────────────────────────────────────────────────
# The dispatch keys the orchestrator's ENGINES table knows how to run. A record
# naming anything else is inert dead weight -> drop it before it can be
# dispatched to a missing function (design "Dispatch"/risk #8). Kept here (not
# imported from the orchestrator) so this stays a leaf module; it is the schema's
# copy of the engine roster, changed only when a real engine ships.
VALID_ENGINES = frozenset({
    "center_ice",       # UNCHANGED — reuses run_center_ice
    "election_night",
    "blizzard",
    "draft",
    "trade_deadline",
})

# The pure derivers in events/derivers.py (design "Auto-derivation contracts").
# A `deriver:` naming anything outside this set can never resolve -> drop.
VALID_DERIVERS = frozenset({
    "playoff_nights",
    "election_nights",
    "draft_day",
    "trade_deadline",
    "blizzard_days",
})

# Frozen top-level field set. Exactly one dating mechanism (date | dates |
# deriver); the rest as annotated in the design's "Record fields (frozen)".
# `meta` is optional at record level (a literal event may carry static meta;
# derivers attach per-date meta downstream).
ALLOWED_FIELDS = frozenset({
    "id", "engine", "date", "dates", "deriver",
    "gate", "window", "priority", "show", "site", "promo", "meta",
})
_DATING_FIELDS = ("date", "dates", "deriver")

# module-level cache: str(path) -> (mtime, records)
_CACHE: dict[str, tuple[float, list[dict]]] = {}


def _log(msg: str) -> None:
    print(f"  !! events registry: {msg}", file=sys.stderr)


def _valid_hhmm(s) -> bool:
    if not isinstance(s, str):
        return False
    try:
        dtime.fromisoformat(s)
        return True
    except ValueError:
        return False


def window_wraps(window) -> bool:
    """True when a window crosses midnight (start > end), e.g. 19:00 -> 01:00.

    Callers (overlay, feed, _current_daypart) treat a wrapping window as
    belonging to the date it STARTED on; validation only needs it to be two
    parseable HH:MM strings, wrap or not."""
    start = dtime.fromisoformat(window[0])
    end = dtime.fromisoformat(window[1])
    return start > end


# ── validation ──────────────────────────────────────────────────────────────
def validate_record(rec) -> tuple[bool, str]:
    """Return (ok, reason). `reason` is '' on success, else a short cause used
    for the drop log line. Pure: no I/O, no gate check (the overlay owns gate
    existence, memoized on gate mtimes — a valid record with an unmet gate is
    still a valid record, just inert)."""
    if not isinstance(rec, dict):
        return False, "record is not a mapping"

    extra = set(rec) - ALLOWED_FIELDS
    if extra:
        return False, f"unknown field(s) {sorted(extra)} (frozen field set)"

    rid = rec.get("id")
    if not isinstance(rid, str) or not rid.strip():
        return False, "missing/empty 'id'"

    engine = rec.get("engine")
    if not isinstance(engine, str):
        return False, f"[{rid}] missing 'engine'"
    if engine not in VALID_ENGINES:
        return False, f"[{rid}] unknown engine '{engine}'"

    # exactly one dating mechanism
    present = [f for f in _DATING_FIELDS if f in rec]
    if len(present) != 1:
        return False, (f"[{rid}] needs exactly one of {list(_DATING_FIELDS)}, "
                       f"got {present or 'none'}")
    kind = present[0]
    if kind == "date":
        if not isinstance(rec["date"], str) or not _valid_iso(rec["date"]):
            return False, f"[{rid}] 'date' is not YYYY-MM-DD"
    elif kind == "dates":
        ds = rec["dates"]
        if not isinstance(ds, list) or not ds or not all(
                isinstance(d, str) and _valid_iso(d) for d in ds):
            return False, f"[{rid}] 'dates' must be a non-empty list of YYYY-MM-DD"
    else:  # deriver
        if rec["deriver"] not in VALID_DERIVERS:
            return False, f"[{rid}] unknown deriver '{rec['deriver']}'"

    gate = rec.get("gate", None)
    if gate is not None and (not isinstance(gate, str) or not gate.strip()):
        return False, f"[{rid}] 'gate' must be a path string or null"

    window = rec.get("window")
    if (not isinstance(window, (list, tuple)) or len(window) != 2
            or not all(_valid_hhmm(w) for w in window)):
        return False, f"[{rid}] 'window' must be [HH:MM, HH:MM]"

    prio = rec.get("priority")
    if not isinstance(prio, int) or isinstance(prio, bool):
        return False, f"[{rid}] 'priority' must be an int"

    show = rec.get("show")
    if not isinstance(show, dict) or not isinstance(show.get("show"), str):
        return False, f"[{rid}] 'show' must be a daypart fragment with a 'show' name"

    site = rec.get("site")
    if not isinstance(site, dict) or not isinstance(site.get("name"), str):
        return False, f"[{rid}] 'site' must be a card with a 'name'"

    promo = rec.get("promo")
    if not isinstance(promo, dict):
        return False, f"[{rid}] 'promo' must be a mapping"
    lead = promo.get("lead_days")
    if not isinstance(lead, int) or isinstance(lead, bool) or lead < 0:
        return False, f"[{rid}] 'promo.lead_days' must be a non-negative int"
    copy = promo.get("copy", [])
    if not isinstance(copy, list) or not all(isinstance(c, str) for c in copy):
        return False, f"[{rid}] 'promo.copy' must be a list of strings"

    return True, ""


def _valid_iso(s: str) -> bool:
    parts = s.split("-")
    if len(parts) != 3:
        return False
    try:
        from datetime import date as _d
        _d.fromisoformat(s)
        return True
    except ValueError:
        return False


# ── record helpers ──────────────────────────────────────────────────────────
def dating_kind(rec: dict) -> str:
    """'date' | 'dates' | 'deriver' — which mechanism this (validated) record
    uses. Callers branch literal-vs-derived on this."""
    for f in _DATING_FIELDS:
        if f in rec:
            return f
    return ""


def literal_dates(rec: dict) -> list[str]:
    """Resolve a literal-dated record to its list of ISO dates. Empty for a
    derived record (its dates come from the deriver, not the registry)."""
    if "date" in rec:
        return [rec["date"]]
    if "dates" in rec:
        return list(rec["dates"])
    return []


# ── {..} meta templating ────────────────────────────────────────────────────
class _SafeDict(dict):
    def __missing__(self, key):  # leave unknown placeholders literally intact
        return "{" + key + "}"


def fill_template(text: str, meta: dict | None) -> str:
    """Fill `{name}` placeholders in a site hook / promo line from a deriver's
    `meta`. A placeholder with no matching meta key is left VERBATIM rather than
    raising — a half-filled promo is degraded texture, a KeyError mid-render is a
    dead sweeper. Non-string / malformed templates pass through unchanged."""
    if not isinstance(text, str):
        return text
    try:
        return text.format_map(_SafeDict(meta or {}))
    except (KeyError, IndexError, ValueError):
        return text


# ── load + cache ────────────────────────────────────────────────────────────
def load_registry(path=DEFAULT_PATH) -> list[dict]:
    """Load and validate the registry, returning the list of VALID records.

    - Missing file      -> `[]` (the no-op / evergreen station, design Stage 0).
    - Malformed record  -> dropped with a stderr log line; siblings survive.
    - Cached on mtime   -> a repeat call on an unchanged file returns the SAME
      list object (a dict lookup); the file re-parses only when its mtime moves,
      exactly like `config.yaml`.

    Pure w.r.t. file contents: identical bytes -> identical (cached) output.
    """
    p = Path(path)
    key = str(p)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        _CACHE.pop(key, None)
        return []

    cached = _CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    records = _parse_and_validate(p)
    _CACHE[key] = (mtime, records)
    return records


def _parse_and_validate(p: Path) -> list[dict]:
    try:
        doc = yaml.safe_load(p.read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        _log(f"could not parse {p}: {e} -> treating as empty (evergreen)")
        return []
    if not isinstance(doc, dict):
        _log(f"{p} is not a mapping -> treating as empty (evergreen)")
        return []

    schema = doc.get("schema")
    if schema != SCHEMA:
        _log(f"{p} schema {schema!r} != {SCHEMA} -> loading best-effort")

    raw = doc.get("events", [])
    if not isinstance(raw, list):
        _log(f"{p} 'events' is not a list -> treating as empty (evergreen)")
        return []

    out: list[dict] = []
    seen_ids: set[str] = set()
    for rec in raw:
        ok, reason = validate_record(rec)
        if not ok:
            _log(f"dropped record: {reason}")
            continue
        rid = rec["id"]
        if rid in seen_ids:
            _log(f"dropped record: duplicate id '{rid}'")
            continue
        seen_ids.add(rid)
        out.append(rec)
    return out


def clear_cache() -> None:
    """Drop the mtime cache (tests; also a manual reload hook)."""
    _CACHE.clear()
