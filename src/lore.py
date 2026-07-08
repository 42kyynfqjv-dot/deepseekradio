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

# Words that are structural (station mechanics, cast, generic time) — a beat
# recurring around ANY of these is normal, so they must never count toward the
# "worn-out subject" ban or the writer would be told to stop saying "caller".
_MECH = {
    # show machinery
    "caller", "callers", "call", "calls", "calling", "guest", "guests",
    "listener", "listeners", "host", "hosts", "show", "shows", "studio",
    "station", "segment", "beat", "beats", "music", "sign", "signs", "signoff",
    "reads", "read", "asks", "ask", "final", "live", "break", "line", "lines",
    "radio", "frequency", "tonight", "today", "tomorrow", "name", "names",
    "bit", "bits", "voice", "voices", "microphone", "clip", "phone",
    # generic time / vague nouns that say nothing about the topic
    "time", "week", "weeks", "weekday", "hour", "hours", "night", "morning",
    "evening", "afternoon", "moment", "moments", "thing", "things", "stuff",
    "story", "stories", "idea", "ideas", "topic", "point", "part", "parts",
    # cast + standing joke-characters (recurring by design, not a rut)
    "hank", "steele", "dawn", "bucky", "merle", "kai", "vivian", "nightshade",
    "roz", "delgado", "peach", "cosima", "vale", "wesley", "watcher", "sal",
    "tarantella", "reginald", "ashcroft", "gareth", "cocharacter",
    # generic verbs / numbers that are actions, not subjects — banning them
    # tells the writer nothing useful about which TOPIC is stale
    "complains", "complain", "complaint", "complaints", "performs", "perform",
    "demonstrates", "demonstrate", "reacts", "insists", "argues", "explains",
    "wind", "five", "four", "three", "seven", "minutes", "minute",
    "day", "days", "daily", "kind", "sort", "way", "ways",
}


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
    "recent_grounding": [],  # grounding props already used, so they stop recurring
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


def overused(state: dict, min_count: int = 5, cap: int = 12) -> list:
    """Subjects/props that have recurred so often across recent shows they've
    become a rut (the user's "toasters and cats keep coming up"). Counts
    significant words across premises, jokes, callbacks and grounding props,
    drops station-mechanics/cast words and anything belonging to a LIVE arc
    (arcs are supposed to recur), and returns the words at or above min_count.
    Fed to the writer as a hard 'pick something fresh instead' ban."""
    from collections import Counter
    pool = (state.get("recent_premises", [])[-80:]
            + state.get("recent_grounding", [])[-80:]
            + state.get("running_jokes", [])
            + state.get("recent_callbacks", []))
    # words that belong to an active storyline must stay allowed
    arc_words = set()
    for a in state.get("arcs", []):
        arc_words |= _sig(f"{a.get('title', '')} {a.get('latest', '')} "
                          f"{a.get('premise', '')}")
    # own tokenizer at len>=3 (not _sig's len>3) so short but real props —
    # cat, mug, pen, owl — are caught too; _MECH/_STOP still strip the noise
    counts = Counter()
    for line in pool:
        seen = set()
        for w in re.findall(r"[a-z']+", (line or "").lower()):
            if len(w) < 3 or w in _STOP or w in _MECH or w in arc_words:
                continue
            # singularize a trailing plural so cat/cats count as one subject
            root = w[:-1] if w.endswith("s") and w[:-1] not in _STOP and len(w) > 3 else w
            if root in _MECH or root in arc_words:
                continue
            if root not in seen:            # count each subject once per line
                seen.add(root)
                counts[root] += 1
    worn = [w for w, n in counts.most_common() if n >= min_count]
    return worn[:cap]


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
             premises=None, grounding=None):
    """Append new threads, de-duplicating, keeping lists bounded."""
    # grounding props: keep every distinct one (exact-dedup only — near-dedup
    # would collapse "the mug"/"the chair" and defeat the overuse counter)
    if grounding:
        for g in grounding:
            g = (g or "").strip()
            if g:
                state["recent_grounding"].append(g)
        state["recent_grounding"] = state["recent_grounding"][-200:]
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
