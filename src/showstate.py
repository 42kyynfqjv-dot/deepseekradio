"""Daily, per-show continuity snapshots.

The generator may be restarted while a show is buffered ahead of air. This
ledger keeps the compact narrative state that should survive that restart;
it deliberately does not retain a full transcript or let model text control
the station state machine.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

from . import clock
from . import leakguard as _leak

ROOT = Path("data/runtime/shows")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def air_date(daypart: dict, now: datetime | None = None) -> str:
    """Use the window's opening date, so an overnight show has one day key."""
    now = now or clock.air_now()
    start = dtime.fromisoformat(daypart["window"][0])
    end = dtime.fromisoformat(daypart["window"][1])
    if start > end and now.time() < end:
        now -= timedelta(days=1)
    return f"{now:%Y-%m-%d}"


def _path(daypart: dict, date: str | None = None) -> Path:
    date = date or air_date(daypart)
    return ROOT / date / f"{daypart['id']}.json"


def cleanup(keep_date: str | None = None) -> None:
    """Remove prior air dates; stale state must never become today's canon."""
    keep_date = keep_date or f"{clock.air_now():%Y-%m-%d}"
    if not ROOT.exists():
        return
    for child in ROOT.iterdir():
        if child.is_dir() and _DATE.fullmatch(child.name) and child.name != keep_date:
            shutil.rmtree(child, ignore_errors=True)


def load(daypart: dict, date: str | None = None) -> dict:
    date = date or air_date(daypart)
    cleanup(date)
    try:
        state = json.loads(_path(daypart, date).read_text())
        if state.get("date") == date and state.get("show") == daypart["id"]:
            return state
    except Exception:
        pass
    return {}


def save(daypart: dict, state: dict, date: str | None = None) -> None:
    date = date or air_date(daypart)
    path = _path(daypart, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = dict(state)
    state.update({"date": date, "show": daypart["id"], "updated": time.time()})
    tmp = path.with_suffix(f".tmp.{__import__('os').getpid()}")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    tmp.replace(path)


def begin(daypart: dict, key: str, outline: dict, *, frame: str = "",
          payoff: str = "", guest: str | None = None) -> dict:
    state = load(daypart)
    if state.get("key") == key and state.get("outline") and not state.get("completed"):
        return state
    state = {
        "key": key,
        "outline": outline,
        "next_beat": 0,
        "next_part": 0,
        "frame": str(frame or "")[:220],
        "payoff": str(payoff or "")[:280],
        "guest": str(guest or "")[:180],
        "open_threads": [str(x)[:220] for x in (outline.get("loose_threads") or [])[:4]],
        "completed_beats": [],
        "last_lines": [],
        "last_summary": "",
        "completed": False,
    }
    save(daypart, state)
    return state


def update(daypart: dict, state: dict, *, beat: dict, lines: list[dict],
           next_beat: int, next_part: int) -> dict:
    """Record one generated part using bounded, code-owned fields."""
    state = dict(state or {})
    text_lines = [str(ln.get("text") or "").strip() for ln in lines
                  if str(ln.get("text") or "").strip()]
    entry = {
        "beat": int(beat.get("_outline_beat", 0) or 0),
        "segment": str(beat.get("segment") or "")[:100],
        "premise": str(beat.get("premise") or "")[:220],
        "part": int(beat.get("_part", 0) or 0),
        "link": str(beat.get("_theory_link") or beat.get("link") or "")[:240],
        "last_line": text_lines[-1][:220] if text_lines else "",
    }
    history = [x for x in state.get("completed_beats", [])
               if x.get("beat") != entry["beat"]]
    history.append(entry)
    state["completed_beats"] = history[-8:]
    state["last_lines"] = [
        {"speaker": str(ln.get("speaker") or "Radio")[:80],
         "text": _leak.clean_public_text(str(ln.get("text") or ""), "")[:220]}
        for ln in lines[-6:] if str(ln.get("text") or "").strip()
    ]
    state["last_summary"] = (
        f"{entry['segment']}: {entry['premise']} Latest: "
        f"{entry['last_line']}"[:520])
    state["next_beat"] = int(next_beat)
    state["next_part"] = int(next_part)
    save(daypart, state)
    return state


def finish(daypart: dict, state: dict, completed: bool) -> None:
    state = dict(state or {})
    state["completed"] = bool(completed)
    save(daypart, state)


def prompt_block(state: dict) -> str:
    """Render a small continuity block; never feed the full ledger to DeepSeek."""
    if not state or state.get("completed"):
        return ""
    frame = _leak.clean_public_text(str(state.get("frame") or ""), "")[:220]
    payoff = _leak.clean_public_text(str(state.get("payoff") or ""), "")[:280]
    rows = []
    for item in state.get("completed_beats", [])[-5:]:
        rows.append("- beat {beat} / part {part}: {segment} — {premise}; link: {link}; last: {last_line}"
                    .format(**{k: _leak.clean_public_text(str(item.get(k) or ""), "")[:220]
                               for k in ("beat", "part", "segment", "premise", "link", "last_line")}))
    lines = "\n".join(
        f"{_leak.clean_public_text(str(x.get('speaker') or 'Radio'), 'Radio')}: "
        f"{_leak.clean_public_text(str(x.get('text') or ''), '')}"
        for x in state.get("last_lines", [])[-4:])
    threads = ", ".join(_leak.clean_public_text(str(x), "")[:180]
                          for x in state.get("open_threads", [])[:3])
    return ("SHOW CONTINUITY LEDGER (code-owned, current air window):\n"
            f"FRAME: {frame}\nLANDING: {payoff}\n"
            f"OPEN THREADS: {threads or 'none listed'}\n"
            "COMPLETED MATERIAL:\n" + ("\n".join(rows) or "- none yet") +
            "\nLATEST LINES:\n" + (lines or "- none yet") +
            "\nTreat this as the starting point. Continue from it; do not restart, "
            "contradict the frame, or recite the ledger.")
