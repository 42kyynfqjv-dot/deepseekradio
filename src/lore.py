"""Persistent station memory: running jokes, feuds, guest history.

A tiny JSON store. The writer reads a digest before outlining a show and appends
new threads afterward; performers get the digest in their context so callbacks
land across shows and days.
"""
from __future__ import annotations

import json
from pathlib import Path

_PATH = Path("lore_state.json")

_DEFAULT = {
    "running_jokes": [],   # e.g. "Chip insists cereal is a soup"
    "feuds": [],           # e.g. "Hank vs Kai over the clip button"
    "guests_seen": [],     # guest ids already used, for variety
    "recent_callbacks": [],  # rolling list of recently-referenced bits
}


def load() -> dict:
    if _PATH.exists():
        return json.loads(_PATH.read_text())
    return dict(_DEFAULT)


def save(state: dict) -> None:
    _PATH.write_text(json.dumps(state, indent=2))


def digest(state: dict, limit: int = 12) -> str:
    """A short human-readable digest to drop into a prompt."""
    lines = []
    if state["running_jokes"]:
        lines.append("Running jokes: " + "; ".join(state["running_jokes"][-limit:]))
    if state["feuds"]:
        lines.append("Ongoing feuds: " + "; ".join(state["feuds"][-limit:]))
    if state["recent_callbacks"]:
        lines.append("Recent callbacks: " + "; ".join(state["recent_callbacks"][-limit:]))
    return "\n".join(lines) if lines else "(no lore yet — this is a fresh station)"


def remember(state: dict, *, jokes=None, feuds=None, guest=None, callbacks=None):
    """Append new threads, de-duplicating, keeping lists bounded."""
    for key, new in (("running_jokes", jokes), ("feuds", feuds),
                     ("recent_callbacks", callbacks)):
        if not new:
            continue
        for item in new:
            if item and item not in state[key]:
                state[key].append(item)
        state[key] = state[key][-40:]
    if guest and guest not in state["guests_seen"]:
        state["guests_seen"].append(guest)
    return state
