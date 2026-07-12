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
    """Station time for the cast — AIR time, so what they say about the clock
    is true when the listener hears it, not when it was written."""
    from .clock import air_now, spoken_air_time
    now = air_now()
    h = now.hour
    part = ("the middle of the night" if h < 5 else "early morning" if h < 9
            else "mid-morning" if h < 12 else "the afternoon" if h < 17
            else "the evening" if h < 21 else "late night")
    at = spoken_air_time(now)   # reuse: one buffer glob per line, not two
    return (f"It is {now:%A}, {part}, station time. AIR CLOCK: when these "
            f"lines reach listeners it will be about {at} — accurate to a "
            "couple of minutes, never claim better. A spoken time check is "
            "welcome radio furniture (at most one per beat), always hedged "
            f"and rounded: 'about {at}', 'coming up on the half hour' — "
            "never a precise-to-the-minute claim.")


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
    # callers/guests are invented HERE, not by the writer — so the worn-out
    # subjects have to be banned at performance time too, or every caller keeps
    # phoning in about the same toaster/cat/clock
    from . import lore
    _worn = lore.overused(lore_state)
    worn_line = (("WORN-OUT — these subjects/props have aired too much lately; do "
                  "NOT have a caller, guest, or host bring any of them up, and pick "
                  "a fresh concrete thing instead: " + ", ".join(_worn))
                 if _worn else "")
    if not beat.get("_guest"):
        guest_line = ""
    elif beat.get("_guest_last"):
        guest_line = (f"TONIGHT'S GUEST: {beat['_guest']} — use exactly this name as "
                      "the guest's speaker label. This is the guest's FINAL beat: the "
                      "host may warmly thank and send them off ONCE, at the very end — "
                      "not before.")
    else:
        guest_line = (f"TONIGHT'S GUEST: {beat['_guest']} — use exactly this name as "
                      "the guest's speaker label. The guest is MID-INTERVIEW and STAYS: "
                      "do NOT thank them for coming, wrap up, dismiss them, or say any "
                      "goodbye to the guest — the conversation continues past this beat.")
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
    if daypart.get("arc") == "live sports broadcast":
        register_line = (
            "- TEAM NAMES ARE STREET NAMES, NOT PUNCHLINES (hard): never "
            "build a bit on a team's name — no apologizing jokes for the "
            "Apologies, no honking for the Honkers, no gridlock puns for the "
            "Gridlock. At MOST one light name-touch per broadcast; the comedy "
            "lives in the hockey, the callers, and the booth.\n"
            "- FICTIONAL LEAGUE ONLY (hard rule): this is an entirely invented "
            "hockey league. NEVER name a real-world team (Canadiens, Bruins, "
            "Maple Leafs, and the like), a real player past or present, the NHL, "
            "the Stanley Cup, or any real league, arena, trophy, or broadcaster "
            "— not even in comparison, nostalgia, or a caller's aside. Every name "
            "you speak must be one already given to you in the beat or roster, or "
            "one you plainly invent. If you catch yourself reaching for a real "
            "hockey name, invent a fictional one instead.")
    else:
        register_line = ("" if daypart.get("arc") else
                     "- NOT the conspiracy show, NOT a mystical one: no paranormal, "
                     "prophecy, hidden patterns, cover-ups, auras, spirits, "
                     "energies, omens, or anything where an object, plant, or "
                     "animal senses/knows/predicts things — even as a bit. The "
                     "comedy here is petty human friction over mundane things. If "
                     "the beat or context contains such material, play it DOWN, "
                     "never build on it.")
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
{worn_line}
{monologue_line}

STORY SO FAR (this show): {rolling_summary or '(top of the show)'}

Write ~{daypart.get('_target_lines', 8)} spoken lines. Rules:
{absurdity_line}
{register_line}
{policy_line}
{daypart.get('_switchboard') or ''}
{daypart.get('_show_clock') or ''}
{daypart.get('_numbers') or ''}
{daypart.get('_watcher_canon') or ''}
{daypart.get('_contest') or ''}
- OUTSIDE WORLD (hard): never name real people, companies, brands, or
  products — this universe has its own celebrities, businesses, and
  conspiracies. Anonymize any real-world reference to a role ('a billionaire',
  'a streaming service', 'a very famous singer').
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
- Caller listening-history VARIETY (hard): "long-time listener" is worn out
  and effectively banned. If a caller mentions how they listen at all, make
  it specific and varied — first-timer, just flipped over from the game,
  only listens during storms, hate-listens, their nephew leaves it on, heard
  it in a cab. Most callers skip the resume and open mid-business.
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
- NEVER state a precise clock time of DAY — speak of time loosely ("late
  night", "this hour", "almost morning"). A GAME clock in a sports
  broadcast ("14:32 of the second period") is fine and correct.
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
- Callers are MEMBERS OF THE LISTENING PUBLIC — ordinary people phoning in from
  their own homes and lives in the outside world. A caller does NOT work at the
  station, is NOT the host's coworker, and has no desk, office, work order, or
  inside knowledge of the building. Their complaints and stories are about
  THEIR world (a neighbor, a toaster, a parking spot, a rude pigeon), never
  about the station's offices, staff, or equipment.
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
    """Models restate the tail they're told to continue from ("And now
    traffic" airs twice in a row). Drop any line ~identical to aired text,
    and dedupe near-identical repeats within the batch itself."""
    from difflib import SequenceMatcher

    def _dupe(a: str, b: str) -> bool:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.75

    out = []
    for ln in lines:
        if ln.get("_enforced"):     # code-authored fact lines are never echoes
            out.append(ln)
            continue
        txt = ln.get("text", "")
        if any(_dupe(txt, a) for a in avoid if a):
            continue
        if out and _dupe(txt, out[-1].get("text", "")):
            continue  # same thought twice back-to-back inside one beat
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
        + ("2. Hedged, rounded time checks ('about 9:30') are correct — keep "
           "them. Delete UNhedged precise-to-the-minute clock times OF DAY; "
           "GAME clocks in the sports broadcast ('14:32 of the second "
           "period') are correct — keep them and never alter scores, "
           "scorers, or game facts.\n"
           if daypart.get("id") == "center_ice" else
           "2. Hedged, rounded time checks ('about 8:25', 'coming up on ten') "
           "are correct — keep them. Delete UNhedged precise-to-the-minute "
           "clock times.\n")
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
# minted premium host voices (KVoiceWalk -> injected into voices.bin, not stock)
_VALID_VOICES |= {"hank_v2", "sal_v2", "kai_v2", "wesley_v2", "bucky_v2",
                  "reginald_v2", "watcher_v2"}

# spare voices for callers/guests — kept disjoint from every cast voice
# (cast uses: af_bella, af_sarah, af_jessica, af_river, af_sky, af_nicole,
#  am_adam, am_michael, am_puck, am_fenrir, bm_george, bm_lewis)
_EXTRA_VOICES = ["af_heart", "am_eric", "bf_emma", "am_liam", "bm_daniel",
                 "af_nova", "bf_alice", "am_onyx", "af_kore", "bf_isabella",
                 "am_echo", "bf_lily", "bm_fable", "af_alloy", "af_aoede"]

# gender-pinned spare pools: a caller/guest voice should match the apparent
# gender of the name (kokoro prefix af_/bf_ = female, am_/bm_ = male). Unknown
# or ambiguous names fall back to the full pool — no regression, just no misgendered
# callers (e.g. "Darla" no longer lands on a male voice).
_EXTRA_F = [v for v in _EXTRA_VOICES if v[:2] in ("af", "bf")]
_EXTRA_M = [v for v in _EXTRA_VOICES if v[:2] in ("am", "bm")]

_FEMALE_NAMES = frozenset((
    "mary patricia jennifer linda elizabeth barbara susan jessica sarah karen "
    "nancy lisa betty margaret sandra ashley kimberly emily donna michelle carol "
    "amanda dorothy melissa deborah stephanie rebecca sharon laura cynthia amy "
    "angela shirley anna brenda pamela emma nicole helen samantha katherine "
    "christine rachel carolyn janet catherine maria heather diane ruth julie "
    "olivia joyce virginia victoria lauren christina joan evelyn judith megan "
    "andrea cheryl hannah jacqueline martha gloria teresa ann sara madison "
    "frances kathryn janice abigail alice judy sophia grace denise amber doris "
    "marilyn danielle beverly isabella diana natalie brittany charlotte marie "
    "kayla lori darla wanda marge mildred vivian roz peach dawn cosima gladys "
    "ethel bernadette nadine lorraine wendy bonnie tammy rhonda gail colleen "
    "bertha agnes edna mabel opal vera della cora nora eleanor"
).split())

_MALE_NAMES = frozenset((
    "james robert john michael david william richard joseph thomas charles "
    "christopher daniel matthew anthony mark donald steven paul andrew joshua "
    "kenneth kevin brian george timothy ronald edward jason jeffrey jacob gary "
    "nicholas eric jonathan stephen larry justin scott brandon frank benjamin "
    "gregory samuel raymond patrick alexander jack dennis jerry tyler aaron "
    "henry douglas peter adam nathan zachary walter kyle harold carl jeremy "
    "gerald keith roger arthur lawrence christian albert joe ethan austin willie "
    "billy bruce wayne ralph roy eugene louis philip bobby johnny bradley doug "
    "marty gord wally yvon norm stu merle bucky sal hank kai wesley reginald gil "
    "bernard ted craig todd greg ron hal pete stanley cliff chuck lars sven "
    "boone moose vern earl floyd herb marv orville roscoe guy gilles anders "
    "toivo remy petr randy curtis bert olaf"
).split())


# the assignment desk's caller banks are gendered by construction — one truth
# shared with the voice pin, so a desk-assigned caller can never mis-voice
from .assignments import CALLERS_F as _DESK_F, CALLERS_M as _DESK_M
_FEMALE_NAMES = frozenset(_FEMALE_NAMES) | {n.lower() for n in _DESK_F}
_MALE_NAMES = frozenset(_MALE_NAMES) | {n.lower() for n in _DESK_M}


def _gender_of(speaker: str):
    """'f'/'m' from the first recognizable given name in the label, else None."""
    for tok in re.findall(r"[a-z]+", speaker.lower()):
        if tok in _FEMALE_NAMES:
            return "f"
        if tok in _MALE_NAMES:
            return "m"
    return None


def _spare_voice(speaker: str) -> str:
    """A stable spare voice, gender-pinned to the name when we can tell."""
    g = _gender_of(speaker)
    pool = _EXTRA_F if g == "f" else _EXTRA_M if g == "m" else _EXTRA_VOICES
    return pool[_stable_hash(speaker) % len(pool)]


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
                v = _spare_voice(spk)
            ln["voice"] = v
            ln["speed"] = s
        else:  # caller: stable distinct voice (gender-pinned) + telephone treatment
            h = _stable_hash(spk)
            ln["voice"] = _spare_voice(spk)
            ln["speed"] = 0.94 + (h % 5) * 0.04  # 0.94-1.10 per caller
            # rink-side interviews are IN THE BUILDING: full-band voice, no
            # phone bandpass (the beat sets _no_phone on the daypart copy)
            if not daypart.get("_no_phone"):
                ln["phone"] = True
    return lines
