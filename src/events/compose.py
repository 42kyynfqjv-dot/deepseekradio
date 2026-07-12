"""Special-events overlay — registry records -> the live daypart clock.

Track D, build-order component 3 (design "From registry to daypart"). This is
the pure composition step the main loop runs once per pass: it turns the
everyday ``schedule.yaml`` plus today's resolved special events into the
``effective`` schedule the orchestrator selects and hands off against. With no
registry file (Stage 0) it is a byte-for-byte no-op — ``effective_schedule``
returns the base object itself.

    active_events(ctx)          -> the resolved active-event dicts for ctx.today
    effective_schedule(base, ctx) -> base with today's event blocks PREPENDED
    daypart_matches_date(dp, now) -> the wrap-aware date-gate clause (pure)
    same_air(a, b)              -> (id, date) air-slot identity for the wait loop
    engine_of(dp)               -> ENGINES dispatch key (center_ice fallback)
    build_ctx(when)             -> the read-only per-pass ctx snapshot

FILENAME FRICTION (reported, not improvised around): the frozen design and the
already-built siblings ``publish.py``/``promo.py`` import this module as
``events.overlay`` (``from . import overlay``; ``overlay.build_ctx`` /
``overlay.active_events``). This deliverable's frozen filename is
``compose.py``. Integration MUST reconcile the two — either rename this file to
``overlay.py`` or add ``from . import compose as overlay`` in
``events/__init__`` — or ``publish.py``'s ``_resolve_horizon`` silently degrades
to an empty feed. The public surface (function names + signatures) matches what
those siblings call, so an alias is a one-liner.

──────────────────────────────────────────────────────────────────────────────
ORCHESTRATOR PATCH SPEC  (integration owns src/orchestrator.py; do NOT edit it
here). Three touchpoints splice this overlay into the live loop. Everything the
patch needs is a pure helper below, so the diff is additive and reversible.

TOUCHPOINT 1 — ``_current_daypart`` gains ONE backward-compatible clause: an
event block only owns the air on its date (wrap-aware). Insert right after the
existing weekday-gate ``continue`` (orchestrator.py ~line 65):

    from . import events            # events/__init__ re-exports compose
    ...
    for dp in schedule["dayparts"]:
        days = dp.get("days")
        if days and now.strftime("%A") not in days:
            continue
        if not events.daypart_matches_date(dp, now):   # NEW — event blocks only
            continue
        # ── window match below UNCHANGED ──

A dateless daypart returns True from the helper, so every everyday/weekday block
behaves exactly as today; only blocks carrying ``date`` are newly gated.

TOUCHPOINT 2 — ``main()`` composes ``eff`` each pass and selects/hands off on it
(design "main() changes in two places"). Top of the ``while True`` loop:

    schedule = _load("schedule.yaml")          # base, still loaded ONCE
    while True:
        ctx = events.build_ctx(clock.air_now())         # cheap snapshot
        eff = events.effective_schedule(schedule, ctx)  # memoized ~1ms
        dp  = _current_daypart(eff, clock.air_now())    # eff, not schedule
        ...
        run_show(dp, config, eff, live=args.live)       # eff so _next_daypart
                                                        # names event shows
    # run_show's ``schedule`` param is now ``eff``: its internal
    # ``_current_daypart(schedule, ...)`` boundary check (orchestrator.py ~580)
    # and ``_owns_air`` (~868) already read that param, so they see events with
    # no further edit — BUT their ``is daypart`` identity test must become the
    # (id, date) comparator, because a memo miss hands back a fresh dict:
    #     if not events.same_air(_current_daypart(schedule, clock.air_now()), daypart):
    #     def _owns_air(): return events.same_air(
    #             _current_daypart(schedule, clock.air_now()), daypart)

TOUCHPOINT 3 — the bottom-of-loop wait condition (judge fix 2, the THIRD
``_current_daypart`` call site). The base ``schedule`` never contains event
blocks, so the old identity spin ``while _current_daypart(schedule, ...) is dp``
is instantly False on an event night -> the loop never sleeps -> a busy-loop on
the 2-vCPU box. Recompute the memoized ``eff`` each pass and compare by
(id, date), NOT object identity (replace orchestrator.py ~1322):

    while True:
        eff = events.effective_schedule(schedule,
                                        events.build_ctx(clock.air_now()))
        cur = _current_daypart(eff, clock.air_now())
        if not (events.same_air(cur, dp)
                and buffer.buffered_seconds()
                    > config["generation"]["buffer_target_minutes"] * 60 * 0.5):
            break
        time.sleep(60)

DISPATCH — ``run_show``'s hardcoded ``id == "center_ice"`` branch becomes the
ENGINES table (design "Dispatch"). ``engine_of`` keeps the ``center_ice``
fallback so the live sports path is provably identical during migration:

    ENGINES = {
        "center_ice":     run_center_ice,       # UNCHANGED
        "election_night": run_election_night,
        "blizzard":       run_blizzard,
        "draft":          run_draft,
        "trade_deadline": run_trade_deadline,
    }
    def run_show(daypart, config, schedule, live):
        fn = ENGINES.get(events.engine_of(daypart))
        if fn:
            return fn(daypart, config, schedule, live)
        ...                                     # the everyday path, unchanged
──────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from datetime import date as _date, datetime, time as dtime, timedelta

from . import registry as _registry

# The dispatch keys the ENGINES table knows how to run (design "Dispatch").
# Single source of truth: the registry's frozen engine roster.
ENGINE_NAMES = _registry.VALID_ENGINES


# ── ctx access (mirror derivers._field: dict OR object carrier) ──────────────
def _field(ctx, name, default=None):
    if isinstance(ctx, dict):
        return ctx.get(name, default)
    return getattr(ctx, name, default)


# ── time / window helpers ────────────────────────────────────────────────────
def _minutes(hhmm) -> int:
    t = dtime.fromisoformat(str(hhmm))
    return t.hour * 60 + t.minute


def _intervals(window):
    """Half-open minute intervals for a window; a past-midnight window splits
    into two. ``[(start, end)]`` for a same-day window."""
    s, e = _minutes(window[0]), _minutes(window[1])
    if s <= e:
        return [(s, e)]
    return [(s, 1440), (0, e)]


def _windows_overlap(a, b) -> bool:
    """True if two windows share any minute (half-open, so 20-23 and 23-01 do
    NOT overlap). A missing window can't be reasoned about -> no overlap."""
    if not a or not b:
        return False
    ia, ib = _intervals(a), _intervals(b)
    return any(x[0] < y[1] and y[0] < x[1] for x in ia for y in ib)


def _weekday(iso: str) -> str:
    return _date.fromisoformat(iso).strftime("%A")


# ── the date-gate matching clause (pure; _current_daypart calls this) ────────
def daypart_matches_date(dp, now: datetime) -> bool:
    """Wrap-aware date gate for an event block (design's ``_current_daypart``
    clause). A daypart with no ``date`` returns True — every weekday/everyday
    block behaves exactly as before. A dated block belongs to the date it
    STARTED on: a same-day window matches only ``date == today``; a window that
    wraps past midnight matches ``date == today`` in the evening half AND
    ``date == yesterday`` in the small-hours tail, so Election Night
    (``2026-11-03``, ``19:00->01:00``) is not yanked off air at 00:00 on 11-04.
    """
    d = dp.get("date")
    if d is None:
        return True
    start = dtime.fromisoformat(dp["window"][0])
    end = dtime.fromisoformat(dp["window"][1])
    today = now.strftime("%Y-%m-%d")
    if start <= end:                              # same-day window
        return d == today
    yest = (now.date() - timedelta(days=1)).isoformat()
    pre = now.time() >= start and d == today      # this evening
    post = now.time() < end and d == yest         # the small hours
    return pre or post


# ── air-slot identity for the wait loop (judge fix 2) ────────────────────────
def same_air(a, b) -> bool:
    """Two daypart dicts name the same AIR slot iff their (id, date) match.
    Replaces the ``is daypart`` identity checks, which break when the overlay's
    memo hands back a fresh dict. For everyday dayparts both dates are ``None``,
    collapsing to a plain id match."""
    if a is None or b is None:
        return a is b
    return (a.get("id"), a.get("date")) == (b.get("id"), b.get("date"))


# ── dispatch key ─────────────────────────────────────────────────────────────
def engine_of(dp) -> str | None:
    """The ENGINES dispatch key for a daypart. Event blocks carry ``engine``
    verbatim; the static ``schedule.yaml`` ``center_ice`` block carries only its
    ``id`` — the retained ``id == 'center_ice'`` migration fallback keeps the
    live sports path provably identical."""
    eng = dp.get("engine")
    if eng:
        return eng
    if dp.get("id") == "center_ice":
        return "center_ice"
    return None


# ── active-event resolution (pure over ctx) ──────────────────────────────────
def _gate_open(gate, gate_stats) -> bool:
    """A record arms iff its gate is null (always) or the gate PATH exists.
    Existence is read from ``ctx.gate_stats`` (``(path, mtime-or-None)`` pairs)
    so gate presence is part of the memo key — arming/clearing re-resolves on
    the next pass."""
    if not gate:
        return True
    stats = dict(gate_stats or ())
    return stats.get(gate) is not None


def _collect_dates(rec, ctx, derivers):
    """(date, window_override, meta) triples this record claims. A derived
    record calls its (exception-isolated) deriver; a literal record yields its
    own dates carrying any record-level ``meta``."""
    kind = _registry.dating_kind(rec)
    out = []
    if kind == "deriver":
        fn = (derivers or {}).get(rec.get("deriver"))
        if fn is None:
            return out
        try:
            emitted = fn(ctx) or []
        except Exception:
            return out
        for dd in emitted:
            if not isinstance(dd, dict):
                continue
            out.append((dd.get("date"), dd.get("window"), dd.get("meta") or {}))
    else:
        base_meta = dict(rec.get("meta") or {})
        for d in _registry.literal_dates(rec):
            out.append((d, None, dict(base_meta)))
    return out


def _resolve(cand):
    """Single winner per window overlap: highest ``priority`` first, ``id`` as
    the tie-break (the ordering ``promo``/``feed`` also assume). A lower or
    duplicate event overlapping an already-kept window is dropped, so two events
    clashing on one window resolve to one, and a deriver that emits the same
    date twice (two tracked teams, one night) yields one broadcast."""
    ordered = sorted(cand, key=lambda e: (-e["priority"], e["id"]))
    winners = []
    for e in ordered:
        if any(_windows_overlap(e["window"], w["window"]) for w in winners):
            continue
        winners.append(e)
    return winners


def active_events(ctx) -> list:
    """Resolve every registry record against ``ctx.today``: literal dates equal
    to today, plus every deriver-emitted date equal to today, each passing its
    gate. Returns the winners highest-priority first, one per window overlap, as
    ``{"id","engine","date","window","priority","show","site","promo","meta"}``
    — the exact shape ``promo.render_promos`` and ``publish.build_feed``
    consume."""
    today = _field(ctx, "today")
    if not today:
        return []
    records = _field(ctx, "records")
    if records is None:
        try:
            records = _registry.load_registry()
        except Exception:
            records = []
    derivers = _field(ctx, "derivers")
    if derivers is None:
        derivers = _load_derivers()
    gate_stats = _field(ctx, "gate_stats")

    cand = []
    for rec in records or []:
        if not _gate_open(rec.get("gate"), gate_stats):
            continue
        seen = set()
        for d, win, meta in _collect_dates(rec, ctx, derivers):
            if d != today or d in seen:
                continue
            seen.add(d)
            window = list(win) if win else (
                list(rec["window"]) if rec.get("window") else None)
            cand.append({
                "id": rec["id"],
                "engine": rec["engine"],
                "date": d,
                "window": window,
                "priority": rec.get("priority", 0),
                "show": rec.get("show") or {},
                "site": rec.get("site") or {},
                "promo": rec.get("promo") or {"lead_days": 0, "copy": []},
                "meta": meta,
            })
    return _resolve(cand)


# ── event block + overlay ────────────────────────────────────────────────────
def _event_block(ev, today) -> dict:
    """An event's ``show`` fragment (verbatim, in ``schedule.yaml`` vocabulary)
    plus the overlay's own keys. A normal daypart dict with one new key,
    ``date`` — the wrap-aware gate above keys on it."""
    blk = dict(ev.get("show") or {})
    blk["id"] = ev["id"]
    blk["engine"] = ev["engine"]
    if ev.get("window"):
        blk["window"] = list(ev["window"])
    blk["date"] = today
    blk["_event"] = True
    blk["_meta"] = ev.get("meta") or {}
    return blk


def _shadowed(dp, blocks, weekday) -> bool:
    """A static day-gated block is a double-book if an event block runs the SAME
    engine on the SAME window and the static block is active on today's weekday
    (design's dedupe: a playoff night on the exact Wed/Sat ``center_ice`` slot).
    Equal-window keeps coverage provably identical when the static is dropped —
    the prepended event covers precisely the same minutes."""
    days = dp.get("days")
    if not days or weekday not in days:
        return False
    dp_engine = dp.get("engine") or dp.get("id")
    dp_win = dp.get("window")
    if dp_win is None:
        return False
    dp_win = list(dp_win)
    for b in blocks:
        if b.get("engine") == dp_engine and b.get("window") == dp_win:
            return True
    return False


# memo: (id(base), today, registry_mtime, sidecar_mtimes, gate_stats) -> eff
_MEMO: dict = {}
_MEMO_ORDER: list = []
_MEMO_CAP = 16


def _memo_key(base, ctx):
    return (
        id(base),
        _field(ctx, "today"),
        _field(ctx, "registry_mtime"),
        tuple(_field(ctx, "sidecar_mtimes") or ()),
        tuple(_field(ctx, "gate_stats") or ()),
    )


def clear_cache() -> None:
    """Drop the overlay memo (tests; also a manual reload hook)."""
    _MEMO.clear()
    _MEMO_ORDER.clear()


def _compose(base, ctx) -> dict:
    try:
        evs = active_events(ctx)
    except Exception:
        evs = []
    if not evs:
        return base                               # identity — eff IS base
    today = _field(ctx, "today")
    blocks = [_event_block(ev, today) for ev in evs]
    weekday = _weekday(today) if today else ""
    kept = [dp for dp in base.get("dayparts", [])
            if not _shadowed(dp, blocks, weekday)]
    eff = dict(base)
    eff["dayparts"] = blocks + kept               # prepended -> they win
    return eff


def effective_schedule(base: dict, ctx) -> dict:
    """``base`` = the parsed ``schedule.yaml``. Returns a schedule dict whose
    ``dayparts`` are ``[today's active event blocks] + base['dayparts']`` —
    event blocks are date-gated and prepended, so each wins its window on its
    date exactly as a day-gated block wins its weekday.

    Pure: identical inputs -> identical output. Memoized on
    ``(id(base), date, registry_mtime, sidecar_mtimes, gate_stats)`` — steady
    state is a dict lookup (~microseconds). Because the gate mtimes are IN the
    key, creating OR clearing a gate file changes the key and the overlay
    re-resolves on the very next pass (the league engine's instant-fallback
    guarantee). With no active event the base object is returned unchanged, so
    ``eff is base`` and every downstream path is byte-for-byte the old station.
    """
    key = _memo_key(base, ctx)
    hit = _MEMO.get(key)
    if hit is not None:
        return hit
    result = _compose(base, ctx)
    _MEMO[key] = result
    _MEMO_ORDER.append(key)
    if len(_MEMO_ORDER) > _MEMO_CAP:
        _MEMO.pop(_MEMO_ORDER.pop(0), None)
    return result


# ── per-pass ctx snapshot (best-effort; never raises) ────────────────────────
def _load_derivers():
    try:
        from . import derivers as _dv
        return dict(_dv.DERIVERS)
    except Exception:
        return {}


def _mtime(path):
    try:
        from pathlib import Path
        return Path(path).stat().st_mtime
    except OSError:
        return None


def _to_iso(when) -> str:
    if when is None:
        return datetime.now().strftime("%Y-%m-%d")
    if isinstance(when, str):
        return when[:10]
    if isinstance(when, datetime):
        return when.strftime("%Y-%m-%d")
    if isinstance(when, _date):
        return when.isoformat()
    return str(when)[:10]


def _load_sidecars():
    """Best-effort read of the sidecars the derivers consume. Any missing or
    unreadable feed degrades to ``None`` (the deriver then emits nothing — never
    invents a game/election/storm). Returns (sidecars-dict, mtimes-dict).

    Integration (the orchestrator-glue row) may refine the exact sidecar wiring;
    the FROZEN contract is the ctx field NAMES the derivers read and the memo
    fields below — not the plumbing here."""
    side, mt = {}, {}

    def _grab(name, loader, path_for_mtime=None):
        try:
            side[name] = loader()
        except Exception:
            side[name] = None
        if path_for_mtime:
            m = _mtime(path_for_mtime)
            if m is not None:
                mt[path_for_mtime] = m

    season_no = None
    try:
        from .. import season as _season
        season_no = _season._load().get("season")
    except Exception:
        season_no = None
    try:
        from ..season import TRACKED as _TRACKED
        tracked = sorted(_TRACKED)
        arenas = {k: v.get("arena") for k, v in _TRACKED.items()
                  if isinstance(v, dict) and v.get("arena")}
    except Exception:
        tracked, arenas = [], {}

    try:
        from ..league import engine as _lge
        if season_no is not None:
            _grab("bracket", lambda: _lge.load_side(f"playoffs-s{season_no}.json"),
                  f"data/league/playoffs-s{season_no}.json")
            _grab("schedule", lambda: _lge.load_side(f"schedule-s{season_no}.json"),
                  f"data/league/schedule-s{season_no}.json")
    except Exception:
        pass

    try:
        from ..statehouse import engine as _sheng
        civ = _sheng.load_civics()
        ga = civ.get("ga")
        if ga is not None:
            _grab("calendar", lambda: _sheng.load_side(f"calendar-ga{ga}.json"),
                  f"data/statehouse/calendar-ga{ga}.json")
    except Exception:
        pass

    side.setdefault("weather", None)              # no persistent weather cache
    return side, mt, tracked, arenas


def build_ctx(when=None) -> dict:
    """Assemble the read-only per-pass ctx snapshot the overlay + derivers read.
    ``when`` may be a datetime (orchestrator: ``clock.air_now()``) or an ISO
    date string (``publish._resolve_horizon``). NEVER raises — a broken sidecar
    degrades to ``None`` and the station stays evergreen (design risk #1).

    Carries the derivers' fields (``today``, ``horizon``, ``bracket``,
    ``calendar``, ``weather``, ``schedule``, ``tracked``, ``arenas``) plus the
    resolution/memo fields the overlay needs (``records``, ``derivers``,
    ``registry_mtime``, ``sidecar_mtimes``, ``gate_stats``)."""
    today = _to_iso(when)
    try:
        records = _registry.load_registry()
    except Exception:
        records = []
    derivers = _load_derivers()

    max_lead = 0
    for r in records:
        try:
            max_lead = max(max_lead, int((r.get("promo") or {}).get("lead_days", 0)))
        except Exception:
            pass
    try:
        horizon = (_date.fromisoformat(today) + timedelta(days=max_lead)).isoformat()
    except ValueError:
        horizon = today

    try:
        side, sidecar_mt, tracked, arenas = _load_sidecars()
    except Exception:
        side, sidecar_mt, tracked, arenas = {}, {}, [], {}

    gate_stats = tuple(sorted(
        (g, _mtime(g)) for g in {r.get("gate") for r in records if r.get("gate")}))
    try:
        registry_mtime = _mtime(str(_registry.DEFAULT_PATH))
    except Exception:
        registry_mtime = None

    return {
        "today": today,
        "horizon": horizon,
        "tracked": tracked,
        "arenas": arenas,
        "bracket": side.get("bracket"),
        "calendar": side.get("calendar"),
        "weather": side.get("weather"),
        "schedule": side.get("schedule"),
        "records": records,
        "derivers": derivers,
        "registry_mtime": registry_mtime,
        "sidecar_mtimes": tuple(sorted(sidecar_mt.items())),
        "gate_stats": gate_stats,
    }
