"""Head Writer — the smart, low-volume tier.

Runs ~once per show. Given the station bible, the daypart, its cast personas, and
the lore digest, it writes a compact segment-by-segment OUTLINE (beats, premises,
punchline targets, guest-of-the-day) that the cheap performers then flesh out.

Because it runs rarely, we can afford a smarter model (deepseek-v4-pro) for a
few cents a day.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import lore
from .openrouter import chat

_BIBLE = Path("station/bible.md")
_PERSONAS = Path("personas")


def _load_personas(cast: list[str]) -> str:
    out = []
    for name in cast:
        p = _PERSONAS / f"{name}.md"
        if p.exists():
            out.append(f"### {name}\n{p.read_text()}")
    return "\n\n".join(out)


def write_outline(daypart: dict, models: dict, lore_state: dict,
                  weekday: str) -> dict:
    """Return an outline dict: {show, beats:[{segment, premise, beat}], guest?}."""
    bible = _BIBLE.read_text()
    personas = _load_personas(daypart["cast"])
    segments = "\n".join(f"- {s}" for s in daypart.get("segments", []))
    guest_line = ("This show features a GUEST from the pool — pick one not in "
                  f"{lore_state.get('guests_seen', [])} and name it."
                  if daypart.get("guest") else "No guest today.")

    system = (
        "You are the head writer for The Frequency, a 24/7 comedy radio station. "
        "You write tight segment outlines that cheap performer models then turn "
        "into dialogue. Be funny, specific, and set up clear punchline targets. "
        "Honor the content guardrail absolutely.\n\n" + bible
    )
    user = f"""Write the outline for this show. Today is {weekday}.

SHOW: {daypart['show']}
ENERGY: {daypart['energy']}
CAST:
{personas}

RECURRING SEGMENTS TO HIT:
{segments}

Write 12-16 beats total: cover each recurring segment at least once, then add
fresh angles on them, one or two fake ad breaks (recurring sponsors from the
bible), and callbacks. The outline must fill a long block of continuous air.
This outline is ONE STRETCH of a show that runs for hours: never write an
outro, wrap-up, or sign-off beat, and no grand cold-open either — every beat
is mid-show. The show never ends; it just keeps rolling.

{guest_line}

STATION LORE (call back to these where natural):
{lore.digest(lore_state)}

Return STRICT JSON:
{{
  "show": "{daypart['show']}",
  "guest": "<guest name or null>",
  "beats": [
    {{"segment": "<segment name>",
      "premise": "<one-line setup>",
      "beat": "<what happens, the turn, the punchline target>"}}
  ],
  "new_jokes": ["<any fresh running joke this show establishes>"],
  "callbacks_used": ["<lore you referenced>"]
}}"""

    raw = chat(models["writer"],
               [{"role": "system", "content": system},
                {"role": "user", "content": user}])
    return _parse_json(raw, daypart)


def _parse_json(raw: str, daypart: dict) -> dict:
    """Best-effort JSON extraction; fall back to raw segments on failure."""
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.split("```", 2)[1].lstrip("json").strip()
    try:
        return json.loads(txt)
    except Exception:
        # Degrade gracefully: one beat per configured segment.
        return {
            "show": daypart["show"],
            "guest": None,
            "beats": [{"segment": s, "premise": s, "beat": s}
                      for s in daypart.get("segments", [])],
            "new_jokes": [],
            "callbacks_used": [],
        }
