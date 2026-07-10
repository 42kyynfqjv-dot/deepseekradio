"""Dream Court clerk — serialized-therapy capture for The Night Shift.

Vivian's Dream Court closes every case in three moves (personas/vivian.md):
name the true FEELING under the absurd dream, hand the caller one real usable
TOOL, deliver a playful-but-final VERDICT. This module runs ONCE per Night
Shift, OFF the hot path, and captures {dreamer, feeling, tool, verdict} from
the aired lines so the census can schedule a 14-28 day follow-up that names
the ACTUAL tool ("how's that four-count breath holding up?").

Design (arcs-census-final.md graft #2 / empowerment.md §5):
- The LLM call is INJECTED as `llm_fn` (mockable). It is never imported here,
  so this stays a pure stdlib leaf: orchestrator/census import it, never the
  reverse.
- A CODE-OWNED fallback (a regex extractor over the aired judge lines) runs
  when `llm_fn` is None, raises, or returns unusable JSON — so the dreamer is
  ALWAYS captured; only the tool may come back None (recognition preserved,
  specificity lost), exactly the garnish-never-a-blocker posture.
- Every captured string passes a G/PG guard before it is stored or spoken.
"""
from __future__ import annotations

import hashlib
import json
import re

# ------------------------------------------------------------------ G/PG guard

# Captured text is authored by a temp-0.9 model and then SPOKEN and STORED as
# canon, so it gets the same content-guardrail discipline as every sibling
# guard: profanity is REPLACED (never cut) with a mild equivalent, control
# junk is stripped, length is clamped. A field that is empty/junk after the
# pass is dropped to None (the follow-up degrades to a generic check-in).
_SOFTEN = [
    (re.compile(r"\bf+u+c+k+(?:ing|ed|er|s)?\b", re.I), "freaking"),
    (re.compile(r"\bs+h+i+t+(?:ty|s|ted)?\b", re.I), "mess"),
    (re.compile(r"\b(?:god ?)?damn(?:ed|it)?\b", re.I), "darn"),
    (re.compile(r"\bass(?:hole|holes)?\b", re.I), "jerk"),
    (re.compile(r"\bbitch(?:es|ing|y)?\b", re.I), "grump"),
    (re.compile(r"\bhell\b", re.I), "heck"),
    (re.compile(r"\bcrap(?:py|s)?\b", re.I), "junk"),
    (re.compile(r"\bbastards?\b", re.I), "so-and-so"),
    (re.compile(r"\bpiss(?:ed|ing|es)?\b", re.I), "annoyed"),
]
# a field carrying any of these reads adult/violent no matter how it's phrased:
# it can't be softened into G/PG, so the whole field is rejected to None.
_REJECT = re.compile(
    r"\b(?:sex|sexual|naked|nude|porn|orgasm|suicide|kill (?:myself|himself|"
    r"herself|yourself)|self.?harm|rape|slur|n-word|c-word)\b", re.I)
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS = re.compile(r"\s+")
_MAXLEN = 160


def gpg_clean(text) -> str | None:
    """Return a G/PG-safe version of `text`, or None if it can't be salvaged.

    Profanity is softened in place (replace, never cut); adult/violent content
    rejects the whole field; whitespace is normalized and length clamped."""
    if not text or not isinstance(text, str):
        return None
    t = _CTRL.sub(" ", text)
    t = _WS.sub(" ", t).strip().strip('"“”‘’ ')
    if not t:
        return None
    if _REJECT.search(t):
        return None
    for pat, repl in _SOFTEN:
        t = pat.sub(repl, t)
    t = _WS.sub(" ", t).strip()
    if len(t) > _MAXLEN:
        # clamp on a word boundary so we never store a truncated word
        t = t[:_MAXLEN].rsplit(" ", 1)[0].rstrip(",;:- ") or t[:_MAXLEN]
    return t or None


# ------------------------------------------------------------ tool lexicon

# Real, usable closure tools in Vivian's register (personas/vivian.md). Each
# entry: (detector, canonical phrase). The canonical phrase is what a follow-up
# NAMES, so it is written to read naturally after "how's ...".
_TOOL_PATTERNS = [
    (re.compile(r"four[- ]count breath|count(?:ing)? (?:to|of) four|"
                r"breathe?\w* (?:in|out)?\s*(?:for|to)\s*(?:a\s*)?(?:count of\s*)?four",
                re.I), "a four-count breath"),
    (re.compile(r"box breath", re.I), "box breathing"),
    (re.compile(r"slow[- ]breath|slow(?:ing)? (?:down |your )?(?:the )?breath",
                re.I), "the slow-breath count"),
    (re.compile(r"write (?:it|the worry|the grievance|them|that)\s+down|"
                r"write (?:it|that|them) (?:down )?for morning|"
                r"morning[- ]you", re.I), "writing it down for morning-you"),
    (re.compile(r"name five things|five things you can (?:see|name)|"
                r"5 things you can see", re.I), "the five-things-you-can-see trick"),
    (re.compile(r"one (?:small|tiny) (?:next )?step|smallest next step|"
                r"single next step", re.I), "that one small next step"),
    (re.compile(r"let (?:it|that|the thing|the whole thing) (?:rest|go|be)|"
                r"permission to (?:let|rest)|leave it (?:for|till) morning",
                re.I), "permission to let it rest"),
    (re.compile(r"glass of water|drink (?:a|some) water", re.I),
     "the glass of water"),
    (re.compile(r"feet (?:flat )?on the floor|both feet on the",
                re.I), "feet on the floor"),
]


def _match_tool(text: str) -> str | None:
    """The first canonical tool phrase whose detector fires in `text`."""
    for pat, phrase in _TOOL_PATTERNS:
        if pat.search(text):
            return phrase
    return None


# --------------------------------------------------------- fallback extractor

_FEELING = re.compile(
    r"(?:what you(?:'?re| are) (?:really )?(?:feeling|carrying)|"
    r"the (?:real |true )?feeling (?:here|underneath|under it)|"
    r"what this (?:dream )?is really about|"
    r"underneath (?:it|the dream|all of it)|"
    r"the thing you(?:'?re| are) (?:actually |really )?carrying|"
    r"you (?:actually |really )?feel)\b", re.I)
_VERDICT = re.compile(
    r"\b(?:the )?(?:dream )?court (?:finds|rules|dismisses)|"
    r"case (?:dismissed|closed)|i (?:hereby )?rule|the verdict is|"
    r"this court finds|i find (?:in favor|for)|court is adjourned", re.I)
_SENT = re.compile(r"[^.!?]*[.!?]|[^.!?]+$")


def _first_name(speaker) -> str:
    return str(speaker or "").strip().split()[0] if speaker else ""


def _dreamer_of(lines) -> str | None:
    """The dreamer = the first phone caller on the line (structural, never a
    guess at names — the voice-attacher's phone flag owns caller identity)."""
    for ln in lines:
        if ln.get("phone"):
            nm = _first_name(ln.get("speaker"))
            if nm:
                return nm
    return None


def _sentence_with(text: str, pat: re.Pattern) -> str | None:
    for m in _SENT.finditer(text):
        s = m.group().strip()
        if s and pat.search(s):
            return s
    return None


def fallback_capture(lines) -> dict | None:
    """Code-owned capture — a pure regex scan of the JUDGE'S (non-phone) lines
    for the three closure moves. No network, fully deterministic. Returns a
    dict with the dreamer always set (if one called) and any move it could
    not find left None. None only when there is no dreamer at all."""
    dreamer = _dreamer_of(lines)
    if not dreamer:
        return None
    judge = " ".join(ln.get("text", "") for ln in lines if not ln.get("phone"))
    feeling = _sentence_with(judge, _FEELING)
    verdict = _sentence_with(judge, _VERDICT)
    tool = _match_tool(judge)
    return {
        "dreamer": dreamer,
        "feeling": gpg_clean(feeling),
        "tool": gpg_clean(tool),
        "verdict": gpg_clean(verdict),
    }


# ----------------------------------------------------------------- LLM path

_CLERK_SYS = (
    "You are the case clerk for Dream Court on The Frequency's overnight show. "
    "You read the aired transcript of ONE dream case and record it. The judge "
    "(Vivian) closes every case in three moves: she names the true FEELING "
    "under the absurd dream, hands the caller one real usable TOOL (a breath "
    "count, writing the worry down for morning-you, naming five things you can "
    "see, one small step, permission to let a thing rest), and delivers a "
    "VERDICT. Extract exactly those, quoting the tool as concretely as the "
    "judge gave it. Keep every field short, G/PG, and faithful to what aired "
    "— invent nothing. Return STRICT JSON and nothing else:\n"
    '{"dreamer": "<caller first name>", "feeling": "<one plain clause>", '
    '"tool": "<the concrete tool, or null>", "verdict": "<one line, or null>"}')


def _transcript(lines) -> str:
    out = []
    for ln in lines:
        who = str(ln.get("speaker", "")).strip() or "Host"
        tag = " (caller)" if ln.get("phone") else ""
        txt = str(ln.get("text", "")).strip()
        if txt:
            out.append(f"{who}{tag}: {txt}")
    return "\n".join(out)


def _parse(raw) -> dict | None:
    if not raw or not isinstance(raw, str):
        return None
    txt = raw.strip()
    if txt.startswith("```"):
        # tolerate ```json ... ``` fences, exactly like arcs.daily_tick
        parts = txt.split("```")
        txt = parts[1] if len(parts) > 1 else txt
        txt = txt.lstrip("json").strip()
    try:
        obj = json.loads(txt)
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def clerk_pass(lines, *, llm_fn=None) -> dict | None:
    """Capture one Dream Court case as {dreamer, feeling, tool, verdict}.

    `lines` are the aired Night Shift beat lines (speaker/text, phone flag on
    caller lines). `llm_fn(messages) -> str` is injected and mockable — the
    production wiring passes `lambda m: openrouter.chat(models["writer"], m)`;
    a test passes a lambda returning canned JSON. When `llm_fn` is None, or it
    raises, or its reply is unusable, a CODE-OWNED regex fallback runs so the
    dreamer is still captured.

    Returns the capture dict, or None if the beat has no dream case (no caller
    on the line). Every string field is G/PG-cleaned; an unsalvageable field
    comes back None. `dreamer` always mirrors the actual caller on the line —
    the model can never rename the dreamer."""
    caller = _dreamer_of(lines)
    if not caller:
        return None  # no case aired this beat

    cap = None
    if llm_fn is not None:
        try:
            raw = llm_fn([{"role": "system", "content": _CLERK_SYS},
                          {"role": "user", "content": _transcript(lines)}])
            obj = _parse(raw)
            if obj is not None:
                cap = {
                    "dreamer": caller,  # structural identity wins, never the model's
                    "feeling": gpg_clean(obj.get("feeling")),
                    "tool": gpg_clean(obj.get("tool")),
                    "verdict": gpg_clean(obj.get("verdict")),
                }
        except Exception as e:  # noqa: BLE001 — off hot path, degrade to fallback
            print(f"  (dream-court clerk llm failed, using fallback: {e})")

    if cap is None:
        cap = fallback_capture(lines)
    return cap


# --------------------------------------------------------- follow-up copy

# Rotated by stable hash of the tool so a given case renders the same line on
# every replay (the scoreguard template-rotation discipline).
_WITH_TOOL = [
    "three weeks on — how's {tool} holding up?",
    "you still keeping up with {tool}?",
    "how's {tool} been treating you since?",
    "has {tool} stuck — or did it slide?",
]
_WITH_BOTH = [
    "three weeks on — how's the {problem}, and is {tool} still holding up?",
    "how's the {problem} these days — and did {tool} stick?",
    "checking in: the {problem}, and {tool} — both still holding?",
]
_GENERIC = [
    "how've you been since your night in Dream Court?",
    "three weeks on — how's that dream sitting with you now?",
    "checking in from Dream Court — how are you holding up?",
]
_ARTICLE = re.compile(r"^(?:a|an|the)\s+", re.I)


def _stable_hash(s: str) -> int:
    """hash() is salted per-process; md5 keeps template rotation stable."""
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


def _toolphrase(tool: str) -> str:
    """Make a stored tool read naturally after 'how's ...': strip a leading
    article and point at it — 'a four-count breath' -> 'that four-count
    breath' (so 'how's that four-count breath holding up?')."""
    base = _ARTICLE.sub("", tool).strip()
    return f"that {base}" if base else tool


def follow_up_copy(capture, *, problem=None, rng=None) -> str:
    """The 14-28 day check-in line the census schedules — it NAMES the actual
    tool the judge handed the caller. `capture` is a clerk_pass dict (or None).
    Optional `problem` (the census running problem) is woven alongside the
    tool. Falls back to a warm generic check-in when no tool was captured, so
    recognition always survives even if specificity was lost."""
    tool = (capture or {}).get("tool")
    prob = gpg_clean(problem) if problem else None
    if tool:
        toolp = _toolphrase(gpg_clean(tool) or tool)
        if prob:
            bank, key = _WITH_BOTH, tool + "|" + prob
            return bank[_stable_hash(key) % len(bank)].format(
                tool=toolp, problem=prob)
        bank = _WITH_TOOL
        return bank[_stable_hash(tool) % len(bank)].format(tool=toolp)
    # no tool — generic warmth (optionally still naming the problem)
    if prob:
        return f"how's the {prob} holding up since your night in Dream Court?"
    key = (capture or {}).get("dreamer") or "generic"
    return _GENERIC[_stable_hash(key) % len(_GENERIC)]
