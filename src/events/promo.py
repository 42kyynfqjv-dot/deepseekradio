r"""Auto-promo through the sweeper system  (events-engine.md §Auto-promo).

For every upcoming registry event inside its promo lead window, render its
curated PG promo lines into the reserve pool as ``promo_{id}_{date}_{i}.wav``
— the same tts+ffmpeg path ``scripts/make_imaging.py`` uses for evergreen
bumpers — so the player prefers them at show boundaries in the days ahead and
drops them once the event has passed. Pure selection + I/O render, stdlib only.

Two entry points run on the box on the existing 30-min ``last_spots`` hook:

    render_promos(registry_events, date)   # mint in-window promos (idempotent)
    purge_expired(date)                     # delete promos whose event is past

``registry_events`` is the resolved active/upcoming event list overlay.py's
``active_events`` publishes: each item is
``{"id","date","window","priority","show","site","promo","meta"}`` where
``promo == {"lead_days": int, "copy": [str,...]}`` and ``meta`` fills the
``{..}`` templates in each copy line.

Idempotence (judge fix 5): a promo keyed ``(event_id, date, i)`` is rendered
exactly once. render_promos SKIPS any key already in ``reserve/promos.json`` OR
whose ``promo_{id}_{date}_{i}.wav`` file already exists on disk, so the 30-min
loop never re-synths an existing line (wasted TTS on the shared box, and a race
against the player's mid-read glob). The line's ``meta`` is captured at first
render and locked forever — a corrected fact gets a NEW registry id, never a
silent re-synth ("aired facts are canon forever").

Concurrency cap: at most **2** in-window events promote at once (``_promotable``),
ranked ``(-priority, id)`` — the same tie-break ``active_events`` uses. A 3rd
in-window event waits deterministically for a slot (a promoted event's date
arrives, or a higher one expires); nothing already rendered is un-rendered.
Pool growth is bounded to ``2 x len(copy)`` promo lines airing at once.

Reactive events (``lead_days: 0`` — blizzard) never promote: no lead time, and a
storm promo mid-storm is noise.

── player.sh patch spec (integration owns player.sh; do NOT edit it here) ──
The player already picks a reserve bumper at show boundaries with
``ls "$RESERVE"/bumper*.wav | shuf -n1``. To prefer an in-window promo, add ONE
helper and swap the two ``bumper*.wav`` picks (lines ~124 and ~133) for it:

    # prefer a promo whose event is still upcoming (embedded date >= today),
    # else fall back to an evergreen bumper exactly as before
    pick_reserve() {
      local today p d
      today=$(date +%F)
      for p in $(ls "$RESERVE"/promo_*.wav 2>/dev/null | shuf); do
        d=$(basename "$p" | sed -E 's/^promo_.*_([0-9]{4}-[0-9]{2}-[0-9]{2})_[0-9]+\.wav$/\1/')
        [ "$d" \> "$today" ] || [ "$d" = "$today" ] && { echo "$p"; return; }
      done
      ls "$RESERVE"/bumper*.wav 2>/dev/null | shuf -n1
    }
    # then:  b=$(pick_reserve)   # was: b=$(ls "$RESERVE"/bumper*.wav | shuf -n1)

The general shuffle-rotation at line ~151 (``ls "$RESERVE"/*.wav``) is left as-is:
promos already sit in that pool as extra variety, indistinguishable in tone from
STATIC_SWEEPERS if they ever air outside their window. Hard expiry (deleting a
past event's promos so a Game-7 line can't air after Game 7) is owned by
``purge_expired`` on the box, NOT the player — the player's date check is only a
best-effort preference.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
from datetime import date as _Date, timedelta
from pathlib import Path

RESERVE = Path("/opt/kaos/reserve")
BEDS = Path("/opt/kaos/beds")
SIDECAR = "promos.json"
VOICES = ["am_onyx", "bm_george", "af_nicole", "am_michael", "af_bella"]


# ── helpers ─────────────────────────────────────────────────────────────────
def _parse(d) -> _Date:
    """Accept an ISO 'YYYY-MM-DD' string or a date; return a date."""
    if isinstance(d, _Date):
        return d
    return _Date.fromisoformat(str(d))


def _load(path: Path) -> dict:
    """Read the promos sidecar; {'promos': []} if absent or unreadable."""
    try:
        state = json.loads(Path(path).read_text())
        if isinstance(state, dict) and isinstance(state.get("promos"), list):
            return state
    except (OSError, ValueError):
        pass
    return {"promos": []}


def _atomic_write(path: Path, obj: dict) -> None:
    """tmp+replace, mirroring season.export's single atomic mutation."""
    path = Path(path)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(obj, indent=2))
    tmp.replace(path)


def _promotable(active, today: _Date) -> list:
    """In-window events (today in [date - lead_days, date)), lead_days > 0,
    highest priority first (id tie-break), capped at the top 2. The 3rd+ waits."""
    inwin = []
    for e in active:
        promo = e.get("promo") or {}
        lead = promo.get("lead_days", 0)
        if lead <= 0:
            continue
        d = _parse(e["date"])
        if d - timedelta(days=lead) <= today < d:
            inwin.append(e)
    inwin.sort(key=lambda e: (-e.get("priority", 0), e["id"]))
    return inwin[:2]


def _default_render_fn(line: str, out_path: Path) -> bool:
    """The make_imaging tts+ffmpeg path: Kokoro voice + ducked bed, echo, fades.
    Mirrors scripts/make_imaging.main so promos match the evergreen sweeper tone.
    Injected (mockable) so tests never synth. Returns True on a produced file."""
    from src import tts  # local import: leaf module, no synth at import time

    out_path = Path(out_path)
    reserve = out_path.parent
    cfg = {"tts": {"sample_rate": 24000, "default_voice": "am_onyx"}}
    voice = VOICES[abs(hash(out_path.name)) % len(VOICES)]
    dry = reserve / f".{out_path.stem}_dry.wav"
    try:
        seg = tts.synth_segment(
            [{"speaker": "Announcer", "voice": voice, "speed": 0.96,
              "text": line}], dry, cfg)
        if not seg:
            return False
        beds = sorted(BEDS.glob("*.wav"))
        if not beds:
            return False
        bed = random.choice(beds)
        cmd = ["ffmpeg", "-v", "error", "-y",
               "-i", str(dry), "-i", str(bed),
               "-filter_complex",
               "[0:a]aecho=0.7:0.5:60:0.25,adelay=1200|1200,"
               "apad=pad_dur=2.2[v];"
               "[1:a]volume=0.32,afade=t=in:d=1.2[b];"
               "[b][v]amix=inputs=2:duration=shortest:dropout_transition=0,"
               "afade=t=out:st=6:d=2.5,alimiter=limit=0.9,"
               "atrim=0:8.5[mix]",
               "-map", "[mix]", "-ar", "24000", "-ac", "1", str(out_path)]
        return subprocess.run(cmd, timeout=120).returncode == 0
    except Exception:
        return False
    finally:
        dry.unlink(missing_ok=True)


# ── entry points ────────────────────────────────────────────────────────────
def render_promos(registry_events, date, *, reserve=RESERVE,
                  render_fn=None, sidecar=SIDECAR) -> dict:
    """Mint in-window promos into ``reserve`` as promo_{id}_{date}_{i}.wav.

    Idempotent: skips any (event_id, date, i) already in the sidecar or whose
    file already exists (judge fix 5). Caps concurrent promotion at 2 events.
    ``render_fn(line, out_path) -> bool`` is injected (defaults to the make_imaging
    tts+ffmpeg path); tests pass a mock so no synthesis happens. Returns
    ``{"rendered": [<new promo record>...], "state": <full sidecar dict>}``."""
    if render_fn is None:
        render_fn = _default_render_fn
    reserve = Path(reserve)
    today = _parse(date)
    sc = reserve / sidecar
    state = _load(sc)
    done = {(p["event_id"], p["date"], p["i"]) for p in state["promos"]}
    rendered = []
    for ev in _promotable(registry_events, today):
        copy = (ev.get("promo") or {}).get("copy") or []
        meta = ev.get("meta") or {}
        for i, tmpl in enumerate(copy):
            key = (ev["id"], ev["date"], i)
            out = reserve / f"promo_{ev['id']}_{ev['date']}_{i}.wav"
            if key in done or out.exists():
                continue                    # already rendered — never re-synth
            try:
                line = tmpl.format(**meta)  # meta captured at FIRST render
            except (KeyError, IndexError):
                line = tmpl                 # missing key: air the raw template
            if not render_fn(line, out):
                continue                    # render failed: retry next pass
            rec = {"file": out.name, "event_id": ev["id"], "date": ev["date"],
                   "i": i, "line": line, "expires": ev["date"]}
            state["promos"].append(rec)
            done.add(key)
            rendered.append(rec)
    _atomic_write(sc, state)
    return {"rendered": rendered, "state": state}


def purge_expired(date, *, reserve=RESERVE, sidecar=SIDECAR) -> list:
    """Delete every promo whose event date is strictly before ``date`` (its
    expiry has passed) and drop it from the sidecar. Idempotent; returns the
    list of purged records. So a Game-7 promo can't survive past Game 7 and a
    snowed-out event's promos self-clean."""
    reserve = Path(reserve)
    today = _parse(date)
    sc = reserve / sidecar
    state = _load(sc)
    kept, purged = [], []
    for p in state["promos"]:
        if _parse(p["expires"]) < today:
            (reserve / p["file"]).unlink(missing_ok=True)
            purged.append(p)
        else:
            kept.append(p)
    state["promos"] = kept
    _atomic_write(sc, state)
    return purged
