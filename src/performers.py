"""Performers — the cheap, high-volume tier.

Given the writer's beat, the cast personas, and a rolling summary, a cheap model
turns each beat into in-character radio dialogue as a list of lines:

    [{"speaker": "Chip", "voice": "am_adam", "text": "..."}, ...]

Each line's voice drives which Kokoro voice speaks it.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from . import lore
from .openrouter import chat

_BIBLE = Path("station/bible.md")
_PERSONAS = Path("personas")


def _persona(name: str) -> tuple[str, str]:
    """Return (front-matter-name, full text) for a persona file."""
    p = _PERSONAS / f"{name}.md"
    text = p.read_text() if p.exists() else name
    m = re.search(r"^name:\s*(.+)$", text, re.MULTILINE)
    display = m.group(1).strip() if m else name
    return display, text


def _time_context() -> str:
    """Coarse station time for the cast — coarse because segments air late."""
    now = datetime.now()
    h = now.hour
    part = ("the middle of the night" if h < 5 else "early morning" if h < 9
            else "mid-morning" if h < 12 else "the afternoon" if h < 17
            else "the evening" if h < 21 else "late night")
    return f"It is {now:%A}, {part}, station time."


def perform_beat(beat: dict, daypart: dict, models: dict, lore_state: dict,
                 rolling_summary: str) -> list[dict]:
    """Generate the dialogue lines for a single beat."""
    bible = _BIBLE.read_text()
    cast_text = "\n\n".join(_persona(n)[1] for n in daypart["cast"])

    system = (
        "You are the performing cast of a radio segment on The Frequency. Turn the beat "
        "into natural, funny, spoken radio dialogue. Stay in character. Do NOT "
        "narrate stage directions — only spoken lines. Honor the content "
        "guardrail absolutely.\n\n" + bible + "\n\nCAST:\n" + cast_text
    )
    user = f"""SHOW: {daypart['show']}
{_time_context()}
SEGMENT: {beat.get('segment')}
PREMISE: {beat.get('premise')}
BEAT TO PLAY: {beat.get('beat')}

STORY SO FAR (this show): {rolling_summary or '(top of the show)'}
LORE: {lore.digest(lore_state, limit=6)}

Write ~{daypart.get('_target_lines', 8)} spoken lines. Rules:
- You are ALREADY ON AIR, mid-show, mid-flow. Do NOT re-introduce the show, the
  host, or the segment. No "welcome back", no "you're listening to", no
  greetings — pick up exactly where the story so far leaves off, as if the
  previous sentence just ended.
- Plain spoken words ONLY: no markdown, asterisks, stage directions, or emoji.
- The station has NO sound effects, stings, or jingles. Never describe a sound,
  never imitate one (no onomatopoeia: no bang, ding, whoosh), and never react to
  or joke about imaginary sounds. If a bit implies a sound, skip it and carry the
  moment with words alone.
- Punctuation limited to . , ? ! and apostrophes.
- NEVER state a precise clock time ("it's 11:47") — segments can air up to an
  hour after writing. Speak of time loosely: "late night", "this hour",
  "almost morning".
- Give each distinct caller/guest a NAME as the speaker (e.g. "Caller Doreen",
  not just "Caller") so they get their own voice.
Return STRICT JSON:
{{"lines": [{{"speaker": "<name>", "text": "<what they say out loud>"}}]}}"""

    raw = chat(models["performer"],
               [{"role": "system", "content": system},
                {"role": "user", "content": user}])
    lines = _parse_lines(raw)
    return _attach_voices(lines, daypart)


_NONSPEAKER = re.compile(r"sfx|sound|effect|narrator|stage|music|jingle|\bfx\b", re.I)


def _parse_lines(raw: str) -> list[dict]:
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.split("```", 2)[1].lstrip("json").strip()
    try:
        lines = json.loads(txt).get("lines", [])
        return [ln for ln in lines
                if not _NONSPEAKER.search(str(ln.get("speaker", "")))]
    except Exception:
        # Degrade: treat each non-empty line as narration by the first speaker.
        return [{"speaker": "Host", "text": ln.strip()}
                for ln in raw.splitlines() if ln.strip()]


# spare voices for callers/guests — none used by the main cast
_EXTRA_VOICES = ["af_heart", "am_eric", "bf_emma", "am_liam", "af_jessica",
                 "bm_daniel", "af_nova", "am_puck", "bf_alice", "am_fenrir",
                 "af_kore", "bf_isabella", "am_echo", "af_river", "bm_fable"]


def _attach_voices(lines: list[dict], daypart: dict) -> list[dict]:
    """Cast speakers get their persona voice; callers/one-offs each get a
    distinct spare voice, stable per speaker name within the segment."""
    voices = {}
    for name in daypart["cast"]:
        display, text = _persona(name)
        m = re.search(r"^voice:\s*(.+)$", text, re.MULTILINE)
        v = m.group(1).strip() if m else "am_adam"
        voices[display.lower()] = v
        voices[name.lower()] = v
    for ln in lines:
        spk = str(ln.get("speaker", "")).lower()
        cast_v = next((voices[k] for k in voices if k in spk), None)
        if cast_v:
            ln["voice"] = cast_v
        else:  # caller/guest: deterministic distinct voice per name
            ln["voice"] = _EXTRA_VOICES[hash(spk) % len(_EXTRA_VOICES)]
    return lines
