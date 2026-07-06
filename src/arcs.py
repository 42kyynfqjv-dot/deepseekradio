"""Serialized station arcs — multi-day storylines with actual payoffs.

Once a day a small "story editor" pass advances every active arc by one
development and retires arcs that have reached their ending. Shows see the
arcs through the lore digest and weave them in like any callback, so a
storyline started on Monday's Scramble can pay off on Thursday's Night Shift.

Arcs live in lore_state["arcs"]: {title, premise, day, max_days, latest,
developments: [...], status}.
"""
from __future__ import annotations

import json

from .openrouter import chat

MAX_ACTIVE = 2

_EDITOR = """You are the story editor for The Frequency, a 24/7 comedy radio
station. You manage the station's SERIALIZED ARCS: slow-burning, petty,
G/PG-rated storylines that develop once per day across different shows and
eventually pay off. Arcs are about small things treated seriously (a missing
mug, an election for Pothole Commissioner, a feud over the thermostat, a
bake sale that keeps escalating). NEVER conspiracies, never paranormal, no
real people or brands.

Rules:
- Advance each ACTIVE arc by exactly ONE development: a small, concrete turn
  that any host could mention in one or two lines. Build toward the ending.
- An arc reaching its final day gets a satisfying, mundane payoff and status
  "done".
- If fewer than {max_active} arcs remain active, start ONE new arc (day 1,
  3-6 day lifespan) that is tonally DIFFERENT from the others.
- "latest" is the one-line summary a host would actually say on air today.

Return STRICT JSON:
{{"arcs": [{{"title": "...", "premise": "...", "day": 2, "max_days": 4,
"latest": "<today's one-line development>", "status": "active|done"}}]}}"""


def daily_tick(models: dict, lore_state: dict) -> None:
    """Advance the station's serialized storylines by one day."""
    active = [a for a in lore_state.get("arcs", []) if a.get("status") == "active"]
    user = ("Current arcs:\n" +
            (json.dumps(active, indent=1) if active else "(none yet)") +
            "\n\nAdvance them one day. Recently used premises to avoid: " +
            "; ".join(lore_state.get("recent_premises", [])[-15:]))
    raw = chat(models["writer"],
               [{"role": "system", "content": _EDITOR.format(max_active=MAX_ACTIVE)},
                {"role": "user", "content": user}])
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.split("```", 2)[1].lstrip("json").strip()
    arcs = json.loads(txt).get("arcs", [])
    keep = [a for a in arcs
            if isinstance(a, dict) and a.get("title") and a.get("latest")]
    # done arcs linger one day (their payoff airs), then fall off
    lore_state["arcs"] = [a for a in keep if a.get("status") == "active"][:MAX_ACTIVE] \
        + [a for a in keep if a.get("status") == "done"][:1]


def digest(lore_state: dict) -> str:
    """The arc lines shows should weave in today."""
    lines = []
    for a in lore_state.get("arcs", []):
        tag = "PAYS OFF TODAY" if a.get("status") == "done" else \
              f"day {a.get('day', '?')} of {a.get('max_days', '?')}"
        lines.append(f"- {a['title']} ({tag}): {a['latest']}")
    return ("ONGOING STATION STORYLINES (weave in naturally, a line or two, "
            "when it fits):\n" + "\n".join(lines)) if lines else ""
