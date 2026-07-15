"""Guard generated radio text against prompt and implementation leakage.

This is deliberately narrow: ordinary in-universe words such as "system" or
"model" remain allowed. The guard only trips on language that exposes prompt
roles, model plumbing, credentials, or instruction hijacking.
"""
from __future__ import annotations

import hashlib
import re

_META_PATTERNS = (
    re.compile(r"\b(?:system|developer|hidden|secret)\s+"
               r"(?:prompt|message|instructions?|rules?)\b", re.I),
    re.compile(r"\b(?:reveal|show|print|repeat|quote|read)\s+"
               r"(?:the\s+)?(?:system|developer|hidden|secret)\s+"
               r"(?:prompt|message|instructions?|rules?)\b", re.I),
    re.compile(r"\b(?:ignore|disregard|override|forget)\s+"
               r"(?:all\s+)?(?:the\s+)?(?:previous|prior|above|these)?\s*"
               r"(?:instructions?|rules?|prompt)\b", re.I),
    re.compile(r"\b(?:as an|i am an?)\s+"
               r"(?:ai|a language model|an? llm|assistant)\b", re.I),
    re.compile(r"\b(?:openrouter|api[\s_-]*key|bearer\s+token|"
               r"authorization\s+header|environment\s+variable|secret\s+token)\b",
               re.I),
    re.compile(r"\b(?:prompt|system|developer|assistant|user)\s+"
               r"(?:says?|message|role)\b", re.I),
    re.compile(r"\b(?:temperature|presence_penalty|frequency_penalty|"
               r"repetition_penalty|max_tokens)\s*[:=]", re.I),
    re.compile(r"\b(?:json|yaml)\s+(?:schema|output|object)\b", re.I),
    re.compile(r"\b(?:i was told|my instructions are|the prompt says|"
               r"the system says|follow these instructions)\b", re.I),
    re.compile(r"\x60\x60\x60|(?:^|\s)[{[]\s*[\"']?(?:speaker|text|lines)[\"']?\s*[:}]",
               re.I),
)

_META_SPEAKER = re.compile(
    r"^(?:system|developer|assistant|user|openrouter|llm|"
    r"language\s+model|ai)(?:\s+(?:message|voice|caller|line))?$", re.I)

_SAFE_CALLER = (
    "That's all I can say about what I saw. The rest is only a hunch.",
    "The line is getting strange. I should leave it there.",
    "I may have connected two things that should stay separate.",
)
_SAFE_HOST = (
    "Let's keep the line to what you actually saw. Back to the evidence.",
    "That's enough of that. We will stay with the harmless part.",
    "The details are getting ahead of us. Back to the thread.",
)


def has_leak(text: str) -> bool:
    text = str(text or "")
    return any(pattern.search(text) for pattern in _META_PATTERNS)


def _safe_line(text: str, phone: bool) -> str:
    pool = _SAFE_CALLER if phone else _SAFE_HOST
    key = int(hashlib.md5(str(text).encode()).hexdigest(), 16)
    return pool[key % len(pool)]


def sanitize_text(text: str, *, phone: bool = False) -> tuple[str, bool]:
    text = str(text or "").strip()
    if not has_leak(text):
        return text, False
    return _safe_line(text, phone), True


def clean_public_text(text: str, fallback: str) -> str:
    """Return text safe for persisted chapter/canon metadata."""
    clean, leaked = sanitize_text(text, phone=False)
    return fallback if leaked else clean


def is_meta_speaker(speaker: str) -> bool:
    return bool(_META_SPEAKER.fullmatch(str(speaker or "").strip()))


def sanitize_speakers(lines: list[dict],
                      cast_names: list[str] | tuple[str, ...] = ()) -> list[dict]:
    """Prevent meta-role labels from becoming voices or caller identities."""
    cast = {str(name).strip().lower() for name in cast_names}
    out = []
    for line in lines:
        speaker = str(line.get("speaker", "")).strip()
        if speaker.lower() in cast or not is_meta_speaker(speaker):
            out.append(line)
            continue
        new = dict(line)
        new["speaker"] = "Caller"
        new["_enforced"] = True
        new["_leakguard"] = True
        out.append(new)
    return out


def sanitize_lines(lines: list[dict]) -> list[dict]:
    """Replace meta leakage while preserving the line's speaker/phone shape."""
    out = []
    for line in lines:
        text, leaked = sanitize_text(line.get("text", ""),
                                     phone=bool(line.get("phone")))
        if not leaked:
            out.append(line)
            continue
        new = dict(line)
        new["text"] = text
        new["_enforced"] = True
        new["_leakguard"] = True
        out.append(new)
    return out
