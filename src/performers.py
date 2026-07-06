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


def _bullet_voices(path: Path) -> dict:
    """Voice map from persona bullets: '**Name** (voice: xx_yyy[, speed: s])'.
    Returns {lowercase name: (voice, speed)}."""
    if not path.exists():
        return {}
    out = {}
    for name, voice, speed in re.findall(
            r"\*\*(.+?)\*\*\s*\(voice:\s*(\w+)(?:,\s*speed:\s*([\d.]+))?\)",
            path.read_text()):
        out[name.lower()] = (voice, float(speed) if speed else 0.97)
    return out


def _guest_voices() -> dict:
    return _bullet_voices(_PERSONAS / "guests.md")


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
                 rolling_summary: str, avoid_lines: list | None = None) -> list[dict]:
    """Generate the dialogue lines for a single beat. `avoid_lines` are
    already-aired texts; near-duplicates of them are dropped (echo guard)."""
    bible = _BIBLE.read_text()
    cast_text = "\n\n".join(_persona(n)[1] for n in daypart["cast"])

    # lore only when the writer explicitly asked for a callback in this beat
    callback = beat.get("callback")
    lore_line = (f"CALLBACK (weave in naturally, exactly once): {callback}"
                 if callback else
                 "No callbacks this beat — do NOT reference any running joke or lore.")
    grounding = beat.get("grounding")
    grounding_line = f"GROUNDING DETAIL (mundane anchor, use it): {grounding}" if grounding else ""
    guest_line = (f"TONIGHT'S GUEST: {beat['_guest']} — use exactly this name as "
                  "the guest's speaker label." if beat.get("_guest") else "")
    if beat.get("no_bit") or daypart.get("absurdity") == "none":
        absurdity_line = ("- NO BIT: zero impossible or absurd elements in this "
                          "beat — sincere, plain radio.")
    elif daypart.get("absurdity") == "optional":
        absurdity_line = ("- At most ONE absurd element, and most beats should "
                          "have none — this show's comedy is human friction, "
                          "not absurdism.")
    else:
        absurdity_line = ("- ABSURDITY BUDGET: exactly ONE impossible or absurd "
                          "element in this beat — never add a second. Roughly one "
                          "exchange in three is completely mundane, plain radio "
                          "(the tea, the weather, the desk, the hour). The "
                          "mundane parts are what make the absurd part land.")
    monologue_line = ("- THIS BEAT IS A MONOLOGUE: one voice runs long; the caps "
                      "below do not apply to them." if beat.get("monologue") else "")
    pol = daypart.get("caller_policy") or {}
    policy_line = ""
    if pol:
        policy_line = (f"- THIS SHOW'S CALL FORMAT (hard): at most "
                       f"{pol.get('per_beat', 1)} caller in this beat; the caller "
                       f"speaks at most {pol.get('max_lines', 3)} times; after the "
                       "host wraps the call in his own words the caller is GONE — "
                       "write NO further dialogue with or about them, the host "
                       "monologues onward alone.")
    if beat.get("scheduled_handoff"):
        handoff_exception = (" (Sole exception: this beat IS a scheduled handoff "
                             "— wrap briefly and throw to the next show.)")
    elif beat.get("ad_throw"):
        handoff_exception = (" (Sole exception: this beat throws to a short ad "
                             "break — briefly, teasing continuation. No goodbyes.)")
    else:
        handoff_exception = ""

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
{guest_line}
{lore_line}
{monologue_line}

STORY SO FAR (this show): {rolling_summary or '(top of the show)'}

Write ~{daypart.get('_target_lines', 8)} spoken lines. Rules:
{absurdity_line}
{policy_line}
- Call-in AND guest-interview segments are DUETS: the caller or guest carries
  at least 40 percent of the lines. The host asks short, sincere questions;
  the CALLER escalates, the host de-escalates. The host never invents
  impossible facts. With co-hosts, the hosts' combined share stays under 60
  percent, split roughly evenly. (If a persona explicitly defines a different
  caller dynamic for a specific bit, the persona wins.)
- No speaker gets more than 2 consecutive lines. Host lines stay short
  (under ~25 words). Exception: when a persona or this beat explicitly
  declares a monologue register, BOTH the consecutive-line cap and the
  short-line guidance are waived for that speaker; callers still stay punchy.
- Let scenes BREATHE: a caller or guest stays on the line for a long,
  winding conversation — follow-ups, tangents. Never rush to the next caller.
- You are ALREADY ON AIR, mid-show, mid-flow. Do NOT re-introduce the show, the
  host, or the segment — UNLESS this beat explicitly calls for a station ID,
  in which case do it once, briefly, in character. No "welcome back", no
  greetings, and NEVER sign off, wrap up, or say goodnight — the show keeps
  rolling after this beat.{handoff_exception}
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
- End every call with the HOST wrapping it in his own words — thank them,
  dismiss them, or note the line went dead. NEVER end a call on a host
  question to the caller.
- Callers arrive like PHONE CALLS, never like people in the room: before a new
  caller's first real line, either the host takes the call ("line two, you're
  on", "we've got a caller") or the caller self-identifies ("yeah hi,
  first-time caller, long-time listener" — plus their name, a NEW one). When a call ends, it ends like a call — the
  host thanks them or the line just goes, and the host reacts.
Return STRICT JSON:
{{"lines": [{{"speaker": "<name>", "text": "<what they say out loud>"}}]}}"""

    raw = chat(models["performer"],
               [{"role": "system", "content": system},
                {"role": "user", "content": user}])
    lines = _parse_lines(raw)
    if "polish" in models and lines:
        lines = _polish(lines, daypart, models, beat)
    lines = _echo_guard(lines, avoid_lines or [])
    lines = _attach_voices(lines, daypart, guest=beat.get("_guest"))
    return _enforce_caller_policy(lines, daypart)


def _echo_guard(lines: list[dict], avoid: list) -> list[dict]:
    """Models restate the tail they're told to continue from; restarts then
    air the same material twice. Drop any line ~identical to aired text."""
    if not avoid:
        return lines
    from difflib import SequenceMatcher
    out = []
    for ln in lines:
        txt = ln.get("text", "")
        if any(SequenceMatcher(None, txt.lower(), a.lower()).ratio() > 0.75
               for a in avoid if a):
            continue
        out.append(ln)
    return out


_SELF_ID = re.compile(r"\b(hi|hey|hello|this is|calling|caller|first.?time|"
                      r"long.?time|line|you're on|am i on)\b", re.I)

_TAKE_LINES = ["We've got a caller. Go ahead, you're on.",
               "Line two. You're on the air.",
               "Hold that thought, there's a call. Go ahead.",
               "The lines are lit. Caller, you're on."]

_CLOSE_LINES = ["Thank you, {name}. That's everything we need.",
                "{name}, you've done your part. The line goes quiet.",
                "That's enough, {name}. Some things shouldn't be said on an open line.",
                "And {name} is gone. But what {name} saw stays with us."]


def _enforce_caller_policy(lines, daypart):
    """Code-level caller discipline (prompt rules leak at temp 0.9):
    cap callers per beat, cap their lines (then they're 'gone'), and make
    sure every call is announced — by the host or by the caller."""
    pol = daypart.get("caller_policy") or {}
    if not pol or not lines:
        return lines
    per_beat = int(pol.get("per_beat", 1))
    max_lines = int(pol.get("max_lines", 3))
    host_voice = next(((ln.get("voice"), ln.get("speed", 1.0), ln.get("speaker"))
                       for ln in lines if not ln.get("phone")), None)
    out, seen, counts = [], [], {}
    # a take-line with no caller in the beat is an invitation to a ghost
    if not any(ln.get("phone") for ln in lines):
        lines = [ln for ln in lines
                 if not re.search(r"\b(go ahead|you're on(?: the air)?)\b",
                                  ln.get("text", ""), re.I)
                 or ln.get("phone")]
    for ln in lines:
        if not ln.get("phone"):
            out.append(ln)
            continue
        spk = ln.get("speaker")
        if spk not in seen:
            if len(seen) >= per_beat:
                # a second caller means the rest of the script is THEIR
                # conversation — cut the beat here rather than ghost-reply
                break
            seen.append(spk)
            # announce the call if neither side did
            if host_voice and not _SELF_ID.search(ln.get("text", "")):
                v, s, hname = host_voice
                out.append({"speaker": hname, "voice": v, "speed": s,
                            "text": _TAKE_LINES[_stable_hash(spk) % len(_TAKE_LINES)]})
        counts[spk] = counts.get(spk, 0) + 1
        # answer-allowance: a direct host question always gets its reply
        prev_host_q = bool(out and not out[-1].get("phone")
                           and out[-1].get("text", "").rstrip().endswith("?"))
        if counts[spk] > max_lines and not (prev_host_q and
                                            counts[spk] <= max_lines + 2):
            # over cap: ritual close, then TRUNCATE the beat — everything after
            # this point was written as dialogue with a caller we just removed,
            # and one-sided dialogue is how the host stops making sense
            if host_voice:
                v, s, hname = host_voice
                words = [w for w in (spk or "caller").split()
                         if w.lower() not in ("the", "a", "an", "caller")]
                first = (words[0] if words else "caller").title()
                tmpl = _CLOSE_LINES[_stable_hash(spk) % len(_CLOSE_LINES)]
                out.append({"speaker": hname, "voice": v, "speed": s,
                            "text": tmpl.format(name=first)})
            break
        out.append(ln)
    return out


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
    except Exception as e:
        # Never read malformed JSON aloud on air — skip the beat instead,
        # but LOUDLY: five silent empty beats sounded like a dead station.
        print(f"  !! beat parse failed ({e}); raw head: {txt[:120]!r}")
        return []


def _polish(lines: list[dict], daypart: dict, models: dict,
            beat: dict | None = None) -> list[dict]:
    """Script-doctor: a cheap, low-temp mechanical edit pass. Deterministic
    backstop for the prompt rules — never adds jokes, only removes tells."""
    beat = beat or {}
    cast_names = [_persona(n)[0] for n in daypart["cast"]]
    monologue_show = (any("OWN THIS HOUR" in _persona(n)[1] for n in daypart["cast"])
                      or bool(daypart.get("solo")) or bool(beat.get("monologue")))
    user = (
        "You are a radio script editor. Edit ONLY mechanically — do not add "
        "jokes, do not change anyone's style. Apply exactly these rules:\n"
        "1. Delete narrated sound effects, stage directions, onomatopoeia.\n"
        "2. Delete precise clock times.\n"
        + ("3. Leave host monologues intact — this format runs long on "
           "purpose; only trim CALLER runs longer than 3 lines.\n"
           if monologue_show else
           "3. If a speaker has more than 2 consecutive lines, merge or trim to 2.\n")
        + ("4. This beat is played straight: cut ANY impossible/absurd element.\n"
           if beat.get("no_bit") or daypart.get("absurdity") == "none"
           else "4. If the scene has more than one impossible/absurd element, keep "
                "the first and cut the rest.\n")
        + ("5. Delete mid-show greetings, welcome-backs, sign-offs, goodnights, "
           "and any line that introduces the show or comments on the show itself "
           "(EXCEPT this beat's scheduled throw — to the next show or to an ad "
           "break — keep it).\n"
           if beat.get("scheduled_handoff") or beat.get("ad_throw") else
           "5. Delete mid-show greetings, welcome-backs, sign-offs, goodnights, "
           "and any line that introduces the show or comments on the show itself.\n")
        + "6. Delete any line advancing a conspiracy or claim about real "
        "people, real brands, real tragedies, health/medicine, or politics — "
        "invented-absurd targets only.\n"
        + "7. Keep speaker labels consistent; the show's cast is: "
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


def _attach_voices(lines: list[dict], daypart: dict,
                   guest: str | None = None) -> list[dict]:
    """Cast speakers get their persona voice; rotating-desk employees and pool
    guests get their bullet voices (full-band, in studio); callers get a
    stable spare voice + phone tag for the TTS treatment."""
    voices, speeds = {}, {}
    named = {}  # name -> (voice, speed) for desk employees + guest pool
    for name in daypart["cast"]:
        display, text = _persona(name)
        m = re.search(r"^voice:\s*(.+)$", text, re.MULTILINE)
        v = m.group(1).strip() if m else "am_adam"
        ms = re.search(r"^speed:\s*(.+)$", text, re.MULTILINE)
        s = float(ms.group(1)) if ms else 1.0
        if v in _VALID_VOICES:
            voices[display.lower()] = v
            speeds[v] = s
            voices[name.lower()] = v
        else:  # "rotates": resolve employees from the persona's own bullets
            named.update(_bullet_voices(_PERSONAS / f"{name}.md"))
    named.update(_guest_voices())
    for ln in lines:
        spk = str(ln.get("speaker", "")).lower()
        # word-boundary match so "Kai" never matches "Kaitlyn from Duluth"
        cast_v = next((v for k, v in voices.items()
                       if re.search(r"\b" + re.escape(k) + r"\b", spk)), None)
        named_hit = None
        if not cast_v:
            named_hit = next((vs for k, vs in named.items()
                              if k in spk or spk in k or
                              any(w in spk.split() for w in k.split() if len(w) > 3)),
                             None)
        if cast_v:
            ln["voice"] = cast_v
            ln["speed"] = speeds.get(cast_v, 1.0)
        elif named_hit and named_hit[0] in _VALID_VOICES:
            v, s = named_hit
            if v in voices.values():  # never share a voice with a live co-host
                v = _EXTRA_VOICES[_stable_hash(spk) % len(_EXTRA_VOICES)]
            ln["voice"] = v
            ln["speed"] = s
        else:  # caller: stable distinct voice + telephone treatment
            h = _stable_hash(spk)
            ln["voice"] = _EXTRA_VOICES[h % len(_EXTRA_VOICES)]
            ln["speed"] = 0.94 + (h % 5) * 0.04  # 0.94-1.10 per caller
            ln["phone"] = True
    return lines
