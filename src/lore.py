"""Persistent station memory: running jokes, feuds, guest history.

A tiny JSON store. The writer reads a digest before outlining a show and appends
new threads afterward; performers get the digest in their context so callbacks
land across shows and days.
"""
from __future__ import annotations

import json
import random
import re
from difflib import SequenceMatcher
from pathlib import Path

_PATH = Path("lore_state.json")

_STOP = {"the", "a", "an", "and", "of", "to", "in", "on", "is", "as", "its",
         "it", "for", "with", "that", "this", "by", "are", "was", "now", "one",
         "who", "has", "had", "not", "but", "over", "into", "about", "their",
         "they", "them", "from", "when", "what", "some", "than", "then"}


def _sig(s: str) -> set:
    """Significant words of a lore line — its 'subject' fingerprint."""
    return {w for w in re.findall(r"[a-z']+", s.lower())
            if len(w) > 3 and w not in _STOP}


def _distinct(items, cap: int) -> list:
    """Most-recent items, dropping any whose SUBJECT already appeared (>=2
    shared significant words) — so one topic (the coffee machine) can never
    occupy the whole digest and saturate every show."""
    kept, sigs = [], []
    for it in reversed(items):
        s = _sig(it)
        if s and any(len(s & prev) >= 2 for prev in sigs):
            continue
        kept.append(it)
        sigs.append(s)
        if len(kept) >= cap:
            break
    return list(reversed(kept))


def _near(a: str, b: str) -> bool:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.6

_DEFAULT = {
    "running_jokes": [],   # e.g. "Chip insists cereal is a soup"
    "feuds": [],           # e.g. "Hank vs Kai over the clip button"
    "guests_seen": [],     # guest ids already used, for variety
    "recent_callbacks": [],  # rolling list of recently-referenced bits
    "recent_premises": [],   # premises already aired, so the writer stops reusing them
}


def load() -> dict:
    try:
        if _PATH.exists():
            state = json.loads(_PATH.read_text())
            for k, v in _DEFAULT.items():
                state.setdefault(k, list(v))
            return state
    except Exception:
        pass  # corrupt file must not kill the station
    return {k: list(v) for k, v in _DEFAULT.items()}


def save(state: dict) -> None:
    tmp = _PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(_PATH)


def digest(state: dict, limit: int = 12) -> str:
    """A short human-readable digest to drop into a prompt."""
    lines = []
    # cap to distinct SUBJECTS, not just the last N — otherwise five near-dup
    # entries about one topic crowd out everything else in every show's prompt
    jokes = _distinct(state["running_jokes"], 6)
    callbacks = _distinct(state["recent_callbacks"], 6)
    if jokes:
        lines.append("Running jokes: " + "; ".join(jokes))
    if state["feuds"]:
        lines.append("Ongoing feuds: " + "; ".join(state["feuds"][-limit:]))
    if callbacks:
        lines.append("Recent callbacks: " + "; ".join(callbacks))
    if state.get("arcs"):
        from . import arcs as _arcs
        d = _arcs.digest(state)
        if d:
            lines.append(d)
    return "\n".join(lines) if lines else "(no lore yet — this is a fresh station)"


def digest_sample(state: dict, k: int = 2) -> str:
    """A small RANDOM sample of lore for performer prompts — rotating references
    instead of the same three items saturating every beat."""
    pool = ([f"running joke: {j}" for j in state.get("running_jokes", [])] +
            [f"feud: {f}" for f in state.get("feuds", [])] +
            [f"callback: {c}" for c in state.get("recent_callbacks", [])])
    if not pool:
        return "(no lore yet)"
    return "; ".join(random.sample(pool, min(k, len(pool))))


def remember(state: dict, *, jokes=None, feuds=None, guest=None, callbacks=None,
             premises=None):
    """Append new threads, de-duplicating, keeping lists bounded."""
    for key, new in (("running_jokes", jokes), ("feuds", feuds),
                     ("recent_callbacks", callbacks), ("recent_premises", premises)):
        if not new:
            continue
        for item in new:
            # skip near-duplicates, not just exact ones — otherwise one subject
            # ("coffee machine standoff" / "The Great Office Coffee Machine
            # Standoff" / "coffee machine clean me light") balloons into many
            # slots and dominates the lore digest
            if item and not any(_near(item, x) for x in state[key]):
                state[key].append(item)
        # premises need a longer tail (same-evening repetition guard);
        # other lore stays tight so digests remain current
        state[key] = state[key][-200 if key == "recent_premises" else -60:]
    if guest and guest not in state["guests_seen"]:
        state["guests_seen"].append(guest)
    return state
