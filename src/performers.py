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
LORE (reference sparingly, at most once): {lore.digest_sample(lore_state)}

Write ~{daypart.get('_target_lines', 8)} spoken lines. Rules:
- Let scenes BREATHE: a caller or guest stays on the line for a long,
  winding conversation — follow-up questions, tangents, escalation. Never
  rush to the next caller or wrap a bit early; the slow build IS the show.
- You are ALREADY ON AIR, mid-show, mid-flow. Do NOT re-introduce the show, the
  host, or the segment. No "welcome back", no "you're listening to", no
  greetings — pick up exactly where the story so far leaves off, as if the
  previous sentence just ended.
- Write like people actually TALK, not like prose: contractions always,
  occasional hesitations (uh, well, look, I mean), false starts, trailing
  thoughts, short reactions ("Right." "No. No no no."). Sparingly — one or two
  per exchange, not every line.
- Plain spoken words ONLY: no markdown, asterisks, stage directions, or emoji.
- The station has NO sound effects, stings, or jingles. Never describe a sound,
  never imitate one (no onomatopoeia: no bang, ding, whoosh), and never react to
  or joke about imaginary sounds. If a bit implies a sound, skip it and carry the
  moment with words alone.
- Punctuation limited to . , ? ! and apostrophes.
- NEVER state a precise clock time ("it's 11:47") — segments can air up to an
  hour after writing. Speak of time loosely: "late night", "this hour",
  "almost morning".
- Give each distinct caller/guest a first-name as the speaker label (never a
  bare "Caller"). Pick ordinary, DIFFERENT names — a fresh name for every new
  caller, never reusing a name from these instructions or from earlier context.
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
        # Never read malformed JSON aloud on air — skip the beat instead.
        return []


# every voice kokoro v1.0 actually ships — anything else must not reach create()
_VALID_VOICES = {"af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica",
                 "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah",
                 "af_sky", "am_adam", "am_echo", "am_eric", "am_fenrir",
                 "am_liam", "am_michael", "am_onyx", "am_puck", "am_santa",
                 "bf_alice", "bf_emma", "bf_isabella", "bf_lily", "bm_daniel",
                 "bm_fable", "bm_george", "bm_lewis"}

# spare voices for callers/guests — none used by the main cast
_EXTRA_VOICES = ["af_heart", "am_eric", "bf_emma", "am_liam", "af_jessica",
                 "bm_daniel", "af_nova", "am_puck", "bf_alice", "am_fenrir",
                 "af_kore", "bf_isabella", "am_echo", "af_river", "bm_fable"]


def _attach_voices(lines: list[dict], daypart: dict) -> list[dict]:
    """Cast speakers get their persona voice; callers/one-offs each get a
    distinct spare voice, stable per speaker name within the segment."""
    voices, speeds = {}, {}
    for name in daypart["cast"]:
        display, text = _persona(name)
        m = re.search(r"^voice:\s*(.+)$", text, re.MULTILINE)
        v = m.group(1).strip() if m else "am_adam"
        ms = re.search(r"^speed:\s*(.+)$", text, re.MULTILINE)
        s = float(ms.group(1)) if ms else 1.0
        voices[display.lower()] = v; speeds[v] = s
        voices[name.lower()] = v
    for ln in lines:
        spk = str(ln.get("speaker", "")).lower()
        cast_v = next((voices[k] for k in voices if k in spk), None)
        if cast_v not in _VALID_VOICES:
            cast_v = None  # e.g. complaints desk "rotates" — fall through to pool
        if cast_v:
            ln["voice"] = cast_v
            ln["speed"] = speeds.get(cast_v, 1.0)
        else:  # caller/guest: deterministic distinct voice per name
            ln["voice"] = _EXTRA_VOICES[hash(spk) % len(_EXTRA_VOICES)]
            ln["speed"] = 0.94 + (hash(spk) % 5) * 0.04  # 0.94-1.10 per caller
    return lines
