"""Head Writer — the smart, low-volume tier.

Runs ~once per show. Given the station bible, the daypart, its cast personas, and
the lore digest, it writes a compact segment-by-segment OUTLINE (beats, premises,
punchline targets, guest-of-the-day) that the cheap performers then flesh out.

Because it runs rarely, we can afford a smarter model (deepseek-v4-pro) for a
few cents a day.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import lore
from .openrouter import chat

_BIBLE = Path("station/bible.md")
_PERSONAS = Path("personas")


def _load_personas(cast: list[str]) -> str:
    out = []
    for name in cast:
        p = _PERSONAS / f"{name}.md"
        if p.exists():
            out.append(f"### {name}\n{p.read_text()}")
    return "\n\n".join(out)


def write_outline(daypart: dict, models: dict, lore_state: dict,
                  weekday: str) -> dict:
    """Return an outline dict: {show, beats:[{segment, premise, beat}], guest?}."""
    bible = _BIBLE.read_text()
    personas = _load_personas(daypart["cast"])
    segments = "\n".join(f"- {s}" for s in daypart.get("segments", []))
    guest_pool = (_PERSONAS / "guests.md").read_text() if (_PERSONAS / "guests.md").exists() else ""
    policy = str(daypart.get("guest", "never")).lower()
    wants_guest = (policy in ("always", "true") or
                   (policy == "wednesday" and weekday == "Wednesday"))
    guest_line = (("This show features a GUEST. Choose one from the GUEST POOL below "
                   f"(not already in {lore_state.get('guests_seen', [])[-6:]}), name them "
                   "exactly as the pool does, and weave them into 2-3 beats.\n\nGUEST POOL:\n"
                   + guest_pool)
                  if wants_guest else "No guest today.")

    system = (
        "You are the head writer for The Frequency, a 24/7 comedy radio station. "
        "You write tight segment outlines that cheap performer models then turn "
        "into dialogue. Be funny, specific, and set up clear punchline targets. "
        "Honor the content guardrail absolutely.\n\n" + bible
    )
    user = f"""Write the outline for this show. Today is {weekday}.

SHOW: {daypart['show']}
ENERGY: {daypart['energy']}
CAST:
{personas}

RECURRING SEGMENTS TO HIT:
{segments}

Write 12-16 beats total: cover each recurring segment at least once, then add
fresh angles on them. The FIRST beat must open with the host naturally
identifying themselves and the show in one or two in-character lines ("I'm X,
this is Y, on The Frequency") before flowing into the beat — this is the ONLY
beat that may do this; no other beat re-introduces anything. Put one or two SPONSOR-READ beats (a host reads a short
ad for a recurring bible sponsor, in their own voice, slightly annoyed about
it) in the FIRST HALF of the outline. Soft segment boundaries and throws
("after this, X") are welcome. The outline must fill a long block of
continuous air. This outline is ONE STRETCH of a show that runs for hours:
never write an outro, wrap-up, sign-off, or cold-open beat — every beat is
mid-show. The show never ends; it just keeps rolling.

Per beat also supply:
- "grounding": one mundane physical detail to anchor the beat (the mug, rain
  on the window, a squeaky chair) — the beat's ONE absurd element must float
  on ordinary radio.
- "callback": normally null. For AT MOST 2 beats in the whole outline, name
  one lore item to reference. Every other beat must not touch lore.

{guest_line}

STATION LORE (call back to these where natural):
{lore.digest(lore_state)}

PREMISES ALREADY AIRED RECENTLY — do NOT reuse or lightly reskin any of these:
{chr(10).join('- ' + p for p in lore_state.get('recent_premises', [])[-60:]) or '(none yet)'}

Return STRICT JSON:
{{
  "show": "{daypart['show']}",
  "guest": "<guest name or null>",
  "beats": [
    {{"segment": "<segment name>",
      "premise": "<one-line setup>",
      "beat": "<what happens, the turn, the punchline target>",
      "grounding": "<one mundane physical detail>",
      "callback": null}}
  ],
  "new_jokes": ["<any fresh running joke this show establishes>"],
  "callbacks_used": ["<lore you referenced>"]
}}"""

    raw = chat(models["writer"],
               [{"role": "system", "content": system},
                {"role": "user", "content": user}])
    return _parse_json(raw, daypart)


def _parse_json(raw: str, daypart: dict) -> dict:
    """Best-effort JSON extraction; fall back to raw segments on failure."""
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.split("```", 2)[1].lstrip("json").strip()
    try:
        out = json.loads(txt)
        beats = out.get("beats")
        if (isinstance(beats, list) and beats and
                all(isinstance(b, dict) and b.get("beat") for b in beats)):
            out["beats"] = [{"segment": str(b.get("segment", "segment")),
                             "premise": str(b.get("premise", "")),
                             "beat": str(b.get("beat")),
                             "grounding": str(b.get("grounding") or ""),
                             "callback": (str(b["callback"]) if b.get("callback") else None)}
                            for b in beats]
            return out
        raise ValueError("bad outline shape")
    except Exception:
        # Degrade gracefully: one beat per configured segment.
        return {
            "show": daypart["show"],
            "guest": None,
            "beats": [{"segment": s, "premise": s, "beat": s}
                      for s in daypart.get("segments", [])],
            "new_jokes": [],
            "callbacks_used": [],
        }
