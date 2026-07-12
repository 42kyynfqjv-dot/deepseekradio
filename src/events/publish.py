"""events.publish — the website takeover feed.

Publishes ``/data/takeovers.json``: date-keyed takeover rows for every
active-or-upcoming special event inside a 14-day horizon, in the exact shape
``schedule.js``'s ``F.TAKEOVERS`` entries already have — **except** keyed on
``date`` (ISO) instead of ``days`` (weekday). The recurring Wed/Sat Center Ice
block stays hardcoded in the JS; this feed *adds* date-specific pre-empts.

Atomic tmp+replace, best-effort, exception-isolated — mirrors ``season.export``.
Stage 0 (no registry / no resolvable events) writes an empty feed, so the site
is a provable no-op: ``schedule.js`` concats nothing.

Pure core (``build_feed``, ``event_row``) is fixture-tested; ``publish_takeovers``
is the thin I/O shell. Sibling modules (``overlay``/``registry``/``derivers``)
are resolved lazily and defensively so this file stands alone during migration.
"""
import json
import os
import time
from datetime import date, datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except Exception:                       # pragma: no cover - stdlib since 3.9
    ZoneInfo = None

SCHEMA = 1
DEFAULT_PATH = "/var/www/bestairadio/data/takeovers.json"
HORIZON_DAYS = 14
STATION_TZ = "America/New_York"

# the row keys the feed emits — the F.TAKEOVERS shape, date-keyed
ROW_KEYS = ("date", "start", "end", "name", "hook", "who")


def station_today(now=None):
    """Station-time (America/New_York) ISO date — the server-side twin of
    ``schedule.js``'s ``F.todayISO``. NEVER a UTC date: at 19:00-23:59 ET a UTC
    date already reports tomorrow and would mis-gate an evening takeover."""
    ts = time.time() if now is None else now
    if ZoneInfo is not None:
        return datetime.fromtimestamp(ts, ZoneInfo(STATION_TZ)).date().isoformat()
    # last-resort fallback (no tz db): local time
    return datetime.fromtimestamp(ts).date().isoformat()


def _hour(hhmm):
    """'20:00' -> 20, '01:30' -> 1. Integer station hour; minutes dropped to
    match the existing integer-hour ``inWin`` logic on the site."""
    return int(str(hhmm).split(":")[0])


def _fill(text, meta):
    """Fill ``{...}`` templates from a derived-date meta dict; on any missing
    key leave the string verbatim (never crash the feed on a template gap)."""
    try:
        return str(text).format(**(meta or {}))
    except (KeyError, IndexError, ValueError):
        return str(text)


def event_row(ev):
    """Map one ``active_events``-shape event dict to a date-keyed feed row.

    ``window`` -> ``start``/``end`` hours; a window that wraps past midnight
    (end <= start, e.g. ``["19:00","01:00"]``) yields ``end = start-relative +
    24`` (``19``/``25``), matching the site's ``end > 24`` wrap convention."""
    w = ev.get("window") or ["0:00", "0:00"]
    start = _hour(w[0])
    end = _hour(w[1])
    if end <= start:                    # wraps past midnight
        end += 24
    site = ev.get("site") or {}
    meta = ev.get("meta") or {}
    return {
        "date": ev["date"],
        "start": start,
        "end": end,
        "name": _fill(site.get("name", ev.get("id", "")), meta),
        "hook": _fill(site.get("hook", ""), meta),
        "who": _fill(site.get("who", ""), meta),
    }


def build_feed(events, today, horizon_days=HORIZON_DAYS, now=None):
    """Pure: ``active_events``-shape dicts -> the feed dict.

    Keeps rows whose ``date`` is in ``[today, today+horizon_days]`` (active or
    upcoming, never past — a stale row can't resurrect a finished event), dedupes
    on ``(date, start, name)``, and sorts by ``(date, start, name)`` for a stable
    byte-for-byte feed. ``generated`` is a unix stamp the loader may honor."""
    hi = (date.fromisoformat(today) + timedelta(days=horizon_days)).isoformat()
    rows, seen = [], set()
    for ev in events or []:
        d = ev.get("date")
        if not d or d < today or d > hi:
            continue
        row = event_row(ev)
        key = (row["date"], row["start"], row["name"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    rows.sort(key=lambda r: (r["date"], r["start"], r["name"]))
    return {
        "schema": SCHEMA,
        "generated": int(now if now is not None else time.time()),
        "takeovers": rows,
    }


def _resolve_horizon(today, horizon_days):
    """Resolve registry events across ``[today, today+horizon_days]`` via the
    overlay. Best-effort — returns ``[]`` if the sibling modules aren't present
    or throw (Stage 0 / a broken registry degrades to an empty feed, never an
    exception). The orchestrator glue row owns the real ``build_ctx`` wiring."""
    try:
        from . import overlay
    except Exception:
        return []
    out = []
    d0 = date.fromisoformat(today)
    for i in range(horizon_days + 1):
        di = (d0 + timedelta(days=i)).isoformat()
        try:
            ctx = overlay.build_ctx(di) if hasattr(overlay, "build_ctx") else di
            out.extend(overlay.active_events(ctx) or [])
        except Exception:
            continue
    return out


def publish_takeovers(path=DEFAULT_PATH, events=None, today=None,
                      horizon_days=HORIZON_DAYS, now=None):
    """Atomically write the takeover feed. Best-effort: returns ``True`` on a
    successful write, ``False`` on a no-op or any failure (missing web dir, a
    resolver error) — it NEVER raises, so a bad feed can never take down the
    30-min publisher pass.

    ``events`` may be injected (the resolved active-or-upcoming list); when
    ``None`` it is resolved from the registry/overlay. A missing parent dir is a
    silent no-op (the box may run without the web root mounted)."""
    try:
        if today is None:
            today = station_today(now)
        if events is None:
            events = _resolve_horizon(today, horizon_days)
        feed = build_feed(events, today, horizon_days, now)
        parent = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(parent):
            return False                # missing web dir -> silent no-op
        tmp = "%s.tmp.%d" % (path, os.getpid())
        try:
            with open(tmp, "w") as fh:
                json.dump(feed, fh, indent=2)
            os.replace(tmp, path)       # the single atomic mutation of the feed
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
        return True
    except Exception:
        return False
