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
                  weekday: str, first_of_window: bool = True,
                  continue_theory: str | None = None) -> dict:
    """Return an outline dict: {show, beats:[{segment, premise, beat}], guest?}."""
    bible = _BIBLE.read_text()
    personas = _load_personas(daypart["cast"])
    segments = "\n".join(f"- {s}" for s in daypart.get("segments", []))
    guest_pool = (_PERSONAS / "guests.md").read_text() if (_PERSONAS / "guests.md").exists() else ""
    policy = str(daypart.get("guest", "never")).lower()
    wants_guest = (policy in ("always", "true") or
                   (policy == "wednesday" and weekday == "Wednesday"))
    role = daypart.get("guest_role", "cameo")
    role_txt = {"host": "The guest IS today's sole host — they man the phones for "
                        "the entire show; write every beat for them.",
                "persistent": "Weave the guest into nearly every beat — they are in "
                              "studio for the full show and never leave.",
                "cameo": "Weave them into 2-3 beats."}[role if role in
                                                       ("host", "persistent") else "cameo"]
    guest_line = (("This show features a GUEST. Choose one from the GUEST POOL below "
                   f"(not already in {lore_state.get('guests_seen', [])[-6:]}), name them "
                   f"exactly as the pool does. {role_txt}\n\nGUEST POOL:\n" + guest_pool)
                  if wants_guest else "No guest today.")

    lo, hi = daypart.get("outline_beats", [12, 16])
    seg_count = len(daypart.get("segments", []))
    open_txt = ('The FIRST beat must open with the host naturally identifying '
                'themselves and the show in one or two in-character lines '
                '("I\'m X, this is Y, on The Frequency") before flowing into the '
                'beat — this is the ONLY beat that may do this.'
                if first_of_window else
                'The show has ALREADY been on air for a while: do NOT include any '
                'self-identification or show-open beat — the first beat continues '
                'mid-flow straight into a segment.')
    sponsor_txt = ("" if daypart.get("sponsor") == "none" else
                   " Put one or two SPONSOR-READ beats (a host reads a short ad "
                   "for a recurring bible sponsor, in their own voice, slightly "
                   "annoyed about it) in the FIRST HALF of the outline.")
    fresh_txt = (" then add fresh angles on them." if hi > seg_count + 2 else ".")
    beat_shape = (f"Write {lo}-{hi} beats total: cover each recurring segment at "
                  f"least once,{fresh_txt} {open_txt}{sponsor_txt} Soft segment "
                  "boundaries and throws are welcome. This outline is ONE STRETCH "
                  "of a show that keeps rolling: never write an outro, wrap-up, "
                  "sign-off, or cold-open beat — every beat is mid-show.")

    system = (
        "You are the head writer for The Frequency, a 24/7 comedy radio station. "
        "You write tight segment outlines that cheap performer models then turn "
        "into dialogue. Be funny, specific, and set up clear punchline targets. "
        "Honor the content guardrail absolutely.\n\n" + bible
    )
    arc = daypart.get("arc")
    arc_line = (f"\nSHOW ARC (structure the ENTIRE outline this way):\n{arc}\n" if arc else
                "\nREGISTER GUARD: this is NOT the conspiracy show. No paranormal, "
                "no prophecy or prediction bits, no 'the object KNOWS things', no "
                "hidden forces, patterns, signals, or cover-ups — that register "
                "belongs to the late-night arc show only. This show's comedy is "
                "petty, human, and mundane: taste, manners, logistics, grudges, "
                "professionalism, who touched whose stuff.\n")
    if continue_theory:
        arc_line += (f"\nIMPORTANT: the show was interrupted mid-theory. Tonight's "
                     f"theory is ALREADY: {continue_theory} — do NOT start a new "
                     "one. Resume it at the depth it had reached and keep "
                     "descending/widening from there.\n")
    user = f"""Write the outline for this show. Today is {weekday}.

SHOW: {daypart['show']}
ENERGY: {daypart['energy']}{arc_line}
CAST:
{personas}

RECURRING SEGMENTS TO HIT:
{segments}

{beat_shape}

Per beat also supply:
- "grounding": one mundane physical detail to anchor the beat (the mug, rain
  on the window, a squeaky chair).
- "callback": normally null. For AT MOST 2 beats in the whole outline, name
  one lore item to reference. Every other beat must not touch lore.
- "no_bit": normally false. Set true for sincerely straight beats (a wind-down,
  an ident, a quiet moment) — zero absurdity in those.
- "monologue": normally false. Set true when one voice should run long (a
  declared solo register, a rating defense, a guest performing their craft).

{guest_line}

STATION LORE (call back to these where natural):
{lore.digest(lore_state)}

PREMISES ALREADY AIRED RECENTLY — do NOT reuse or lightly reskin any of these:
{chr(10).join('- ' + p for p in lore_state.get('recent_premises', [])[-60:]) or '(none yet)'}

Return STRICT JSON:
{{
  "show": "{daypart['show']}",
  "guest": "<guest name or null>",
  "theory": "<for arc shows: one line naming this outline's single theory; else null>",
  "beats": [
    {{"segment": "<segment name>",
      "premise": "<one-line setup>",
      "beat": "<what happens, the turn, the punchline target>",
      "grounding": "<one mundane physical detail>",
      "callback": null, "no_bit": false, "monologue": false}}
  ],
  "new_jokes": ["<any fresh running joke this show establishes>"],
  "callbacks_used": ["<lore you referenced>"]
}}"""

    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": user}]
    try:
        raw = chat(models["writer"], msgs)
    except Exception as e:
        print(f"  (writer failed: {e} — trying backup model)")
        try:  # backup: the polish model writes a serviceable outline
            raw = chat(dict(models.get("polish", models["performer"]),
                            max_tokens=2500), msgs)
        except Exception as e2:
            # nothing may take the station down: outline from the segments
            print(f"  (backup writer failed too, segment fallback: {e2})")
            raw = ""
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
                             "callback": (str(b["callback"]) if b.get("callback") else None),
                             "no_bit": bool(b.get("no_bit")),
                             "monologue": bool(b.get("monologue"))}
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
