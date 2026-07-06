"""Performers — the cheap, high-volume tier.

Given the writer's beat, the cast personas, and the actual last lines aired, a
cheap model turns each beat into in-character radio dialogue as a list of lines:

    [{"speaker": "Chip", "voice": "am_adam", "text": "..."}, ...]

Each line's voice drives which Kokoro voice speaks it. Non-cast speakers are
tagged phone=True so TTS gives them the telephone treatment. A script-doctor
pass (cheap model, mechanical edits only) backstops the prompt rules.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

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


def _guest_voices() -> dict:
    """Voice map from the guest pool file: '**Name** (voice: xx_yyy)'."""
    p = _PERSONAS / "guests.md"
    if not p.exists():
        return {}
    return {name.lower(): voice for name, voice in
            re.findall(r"\*\*(.+?)\*\*\s*\(voice:\s*(\w+)\)", p.read_text())}


def _stable_hash(s: str) -> int:
    """hash() is salted per-process; md5 keeps caller voices stable forever."""
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


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

    # lore only when the writer explicitly asked for a callback in this beat
    callback = beat.get("callback")
    lore_line = (f"CALLBACK (weave in naturally, exactly once): {callback}"
                 if callback else
                 "No callbacks this beat — do NOT reference any running joke or lore.")
    grounding = beat.get("grounding")
    grounding_line = f"GROUNDING DETAIL (mundane anchor, use it): {grounding}" if grounding else ""

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
{grounding_line}
{lore_line}

STORY SO FAR (this show): {rolling_summary or '(top of the show)'}

Write ~{daypart.get('_target_lines', 8)} spoken lines. Rules:
- ABSURDITY BUDGET: exactly ONE impossible or absurd element in this beat —
  never add a second. Roughly one exchange in three is completely mundane,
  plain radio (the tea, the weather, the desk, the hour). The mundane parts
  are what make the absurd part land.
- Call-in segments are DUETS: the caller carries at least 40 percent of the
  lines. The host asks short, sincere questions; the CALLER escalates, the
  host de-escalates. The host never invents impossible facts. (If a persona
  explicitly defines a different caller dynamic, the persona wins.)
- No speaker gets more than 2 consecutive lines, and host lines stay short
  (under ~25 words). Radio is turn-taking, not monologue. (Exception: if a
  persona explicitly defines a monologue register, the persona wins.)
- Let scenes BREATHE: a caller or guest stays on the line for a long,
  winding conversation — follow-ups, tangents. Never rush to the next caller.
- You are ALREADY ON AIR, mid-show, mid-flow. Do NOT re-introduce the show, the
  host, or the segment — UNLESS this beat explicitly calls for a station ID,
  in which case do it once, briefly, in character. No "welcome back", no
  greetings, and NEVER sign off, wrap up, or say goodnight — the show keeps
  rolling after this beat.
- Never define or explain a recurring bit, and never comment on the show
  itself or its "world" — no "classic segment", no "you've really built
  something here". The bit just happens.
- Write like people actually TALK: contractions always, occasional hesitations
  (uh, well, look), false starts, short reactions ("Right." "No. No no no.").
  Sparingly — one or two per exchange, not every line.
- Plain spoken words ONLY: no markdown, asterisks, stage directions, or emoji.
- The station has NO sound effects, stings, or jingles. Never describe a sound,
  never imitate one (no onomatopoeia), never react to imaginary sounds.
- Punctuation limited to . , ? ! and apostrophes.
- NEVER state a precise clock time — speak of time loosely ("late night",
  "this hour", "almost morning").
- Give each distinct caller/guest a first-name as the speaker label (never a
  bare "Caller"). Pick ordinary, DIFFERENT names — a fresh name for every new
  caller, never reusing a name from these instructions or earlier context.
Return STRICT JSON:
{{"lines": [{{"speaker": "<name>", "text": "<what they say out loud>"}}]}}"""

    raw = chat(models["performer"],
               [{"role": "system", "content": system},
                {"role": "user", "content": user}])
    lines = _parse_lines(raw)
    if "polish" in models and lines:
        lines = _polish(lines, daypart, models)
    return _attach_voices(lines, daypart)


_NONSPEAKER = re.compile(r"sfx|sound|effect|narrator|stage|music|jingle|\bfx\b", re.I)


def _sanitize_text(t: str) -> str:
    """Belt-and-suspenders: kill stage directions at parse time too."""
    t = re.sub(r"\*[^*]{1,80}\*", " ", t)
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _parse_lines(raw: str) -> list[dict]:
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.split("```", 2)[1].lstrip("json").strip()
    try:
        lines = json.loads(txt).get("lines", [])
        out = []
        for ln in lines:
            if _NONSPEAKER.search(str(ln.get("speaker", ""))):
                continue
            ln["text"] = _sanitize_text(str(ln.get("text", "")))
            # normalize mangled speaker labels ("Vivian Night8hade")
            ln["speaker"] = re.sub(r"[^A-Za-z' .-]", "", str(ln.get("speaker", ""))).strip()
            if ln["text"] and ln["speaker"]:
                out.append(ln)
        return out
    except Exception:
        # Never read malformed JSON aloud on air — skip the beat instead.
        return []


def _polish(lines: list[dict], daypart: dict, models: dict) -> list[dict]:
    """Script-doctor: a cheap, low-temp mechanical edit pass. Deterministic
    backstop for the prompt rules — never adds jokes, only removes tells."""
    cast_names = [_persona(n)[0] for n in daypart["cast"]]
    monologue_show = any("OWN THIS HOUR" in _persona(n)[1] or "monologue" in _persona(n)[1]
                         for n in daypart["cast"])
    user = (
        "You are a radio script editor. Edit ONLY mechanically — do not add "
        "jokes, do not change anyone's style. Apply exactly these rules:\n"
        "1. Delete narrated sound effects, stage directions, onomatopoeia.\n"
        "2. Delete precise clock times.\n"
        + ("3. Leave host monologues intact — this show's format is "
           "monologue-driven; only trim CALLER runs longer than 3 lines.\n"
           if monologue_show else
           "3. If a speaker has more than 2 consecutive lines, merge or trim to 2.\n")
        + "4. If the scene has more than one impossible/absurd element, keep the "
        "first and cut the rest.\n"
        "5. Delete mid-show greetings, welcome-backs, sign-offs, goodnights, "
        "and any line that introduces the show or comments on the show itself.\n"
        "6. Keep speaker labels consistent; the show's cast is: "
        + ", ".join(cast_names) + ". Leave caller names as they are.\n"
        "Return the SAME JSON schema, edited:\n"
        + json.dumps({"lines": lines})
    )
    try:
        raw = chat(models["polish"], [{"role": "user", "content": user}])
        polished = _parse_lines(raw)
        # sanity: an edit pass that nukes the scene is a failed edit pass
        if polished and len(polished) >= max(3, len(lines) // 2):
            return polished
    except Exception:
        pass
    return lines


# every voice kokoro v1.0 actually ships — anything else must not reach create()
_VALID_VOICES = {"af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica",
                 "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah",
                 "af_sky", "am_adam", "am_echo", "am_eric", "am_fenrir",
                 "am_liam", "am_michael", "am_onyx", "am_puck", "am_santa",
                 "bf_alice", "bf_emma", "bf_isabella", "bf_lily", "bm_daniel",
                 "bm_fable", "bm_george", "bm_lewis"}

# spare voices for callers/guests — kept disjoint from every cast voice
# (cast uses: af_bella, af_sarah, af_jessica, af_river, af_sky, af_nicole,
#  am_adam, am_michael, am_puck, am_onyx, bm_george, bm_lewis)
_EXTRA_VOICES = ["af_heart", "am_eric", "bf_emma", "am_liam", "bm_daniel",
                 "af_nova", "bf_alice", "am_fenrir", "af_kore", "bf_isabella",
                 "am_echo", "bf_lily", "bm_fable", "af_alloy", "af_aoede"]


def _attach_voices(lines: list[dict], daypart: dict) -> list[dict]:
    """Cast speakers get their persona voice; guests get their pool voice;
    callers get a stable spare voice + phone tag for the TTS treatment."""
    voices, speeds = {}, {}
    for name in daypart["cast"]:
        display, text = _persona(name)
        m = re.search(r"^voice:\s*(.+)$", text, re.MULTILINE)
        v = m.group(1).strip() if m else "am_adam"
        ms = re.search(r"^speed:\s*(.+)$", text, re.MULTILINE)
        s = float(ms.group(1)) if ms else 1.0
        voices[display.lower()] = v
        speeds[v] = s
        voices[name.lower()] = v
    guests = _guest_voices()
    for ln in lines:
        spk = str(ln.get("speaker", "")).lower()
        # word-boundary match so "Kai" never matches "Kaitlyn from Duluth"
        cast_v = next((v for k, v in voices.items()
                       if re.search(r"\b" + re.escape(k) + r"\b", spk)), None)
        if cast_v not in _VALID_VOICES:
            cast_v = None  # e.g. complaints desk "rotates" — fall to pool
        guest_v = next((v for k, v in guests.items()
                        if k in spk or spk in k), None) if not cast_v else None
        if cast_v:
            ln["voice"] = cast_v
            ln["speed"] = speeds.get(cast_v, 1.0)
        elif guest_v in _VALID_VOICES:
            ln["voice"] = guest_v
            ln["speed"] = 0.97
        else:  # caller: stable distinct voice + telephone treatment
            h = _stable_hash(spk)
            ln["voice"] = _EXTRA_VOICES[h % len(_EXTRA_VOICES)]
            ln["speed"] = 0.94 + (h % 5) * 0.04  # 0.94-1.10 per caller
            ln["phone"] = True
    return lines
