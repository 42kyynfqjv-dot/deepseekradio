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
    assigned = daypart.get("_assign") or {}
    if wants_guest and assigned.get("guest"):
        guest_line = (f"This show's GUEST is ASSIGNED by the desk: "
                      f"{assigned['guest']} — name them exactly as the pool "
                      f"does; do not choose another. {role_txt}\n\n"
                      "GUEST POOL:\n" + guest_pool)
    elif wants_guest:
        guest_line = ("This show features a GUEST. Choose one from the GUEST "
                      f"POOL below (not already in "
                      f"{lore_state.get('guests_seen', [])[-6:]}), name them "
                      f"exactly as the pool does. {role_txt}\n\nGUEST POOL:\n"
                      + guest_pool)
    else:
        guest_line = "No guest today."

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
    if daypart.get("sponsor") == "none":
        sponsor_txt = ""
    elif assigned.get("sponsor"):
        sponsor_txt = (f" Put ONE sponsor-read beat in the first half: the "
                       f"host reads a short ad for {assigned['sponsor'][0]} "
                       f"— {assigned['sponsor'][1]} — in their own voice, "
                       "slightly annoyed about it. No other sponsor gets a "
                       "host read this show.")
    else:
        sponsor_txt = (" Put one or two SPONSOR-READ beats (a host reads a "
                       "short ad for a recurring bible sponsor, in their own "
                       "voice, slightly annoyed about it) in the FIRST HALF "
                       "of the outline.")
    fresh_txt = (" then add fresh angles on them." if hi > seg_count + 2 else ".")
    beat_shape = (f"Write {lo}-{hi} beats total: cover each recurring segment at "
                  f"least once,{fresh_txt} {open_txt}{sponsor_txt} Soft segment "
                  "boundaries and throws are welcome. This outline is ONE STRETCH "
                  "of a show that keeps rolling: never write an outro, wrap-up, "
                  "sign-off, or cold-open beat — every beat is mid-show.")
    if daypart.get("id") == "static_hour":
        beat_shape = (
            "Give the material for one connected chapter in about six creative "
            "beats. Choose the evidence, callers, escalation, jokes, and landing; "
            "do not label phases or design production bookkeeping — code will "
            "shape and close the six-beat spine. "
            f"{open_txt}{sponsor_txt}")

    system = (
        "You are the head writer for The Frequency, a 24/7 comedy radio station. "
        "You write tight segment outlines that cheap performer models then turn "
        "into dialogue. Be funny, specific, and set up clear punchline targets. "
        "Honor the content guardrail absolutely.\n\n" + bible
    )
    arc = daypart.get("arc")
    if arc and daypart.get("_arc_extra"):
        arc = f"{arc}\n{daypart['_arc_extra']}"
    arc_line = (f"\nSHOW ARC (structure the ENTIRE outline this way):\n{arc}\n" if arc else
                "\nREGISTER GUARD: this is NOT the conspiracy show and NOT a "
                "mystical one. Banned registers: conspiracies (hidden forces, "
                "patterns, signals, surveillance, cover-ups) AND woo (auras, "
                "spirits, energies, omens, vibes-as-facts, anything where an "
                "object, plant, or animal senses/knows/predicts/judges). Those "
                "belong to the late-night arc show only. This show's comedy is "
                "petty, human, and mundane: taste, manners, logistics, grudges, "
                "professionalism, who touched whose stuff. An eccentric host is "
                "eccentric about habits and opinions, never about the "
                "supernatural.\n")
    if continue_theory:
        arc_line += (f"\nIMPORTANT: the show was interrupted mid-theory. Tonight's "
                     f"theory is ALREADY: {continue_theory} — do NOT start a new "
                     "one. Resume it at the depth it had reached and keep "
                     "descending/widening from there. The frame and any named "
                     "organization are fixed; new evidence must come back to "
                     "them, not replace them.\n")
    theory_contract = ""
    if daypart.get("id") == "static_hour":
        theory_contract = """

THEORY CHAPTER CONTRACT (hard for The Static Hour):
- Write one complete chapter around one absurd theory, not a sampler of
  unrelated theories. Choose the frame, evidence, callers, shadow organization,
  escalation, jokes, and wording freely.
- 'theory' is the durable frame; include the central subject and any recurring
  organization or mechanism. 'payoff' is the final landing in one sentence.
- Keep every new object or caller connected to that frame. The station code adds
  the six-act spine, connective links, phase labels, and the final closure beat;
  do not spend effort designing those production mechanics.
- A closed chapter may be sequel material. If you choose to build on one, put
  its exact id in 'builds_on' and do not reopen its solved question unchanged.
"""
    pacing = daypart.get("pacing")
    pacing_line = f"\nPACING (hard rule for this show): {pacing}\n" if pacing else ""
    from .assignments import writer_block
    assign_block = writer_block(None, None, assigned.get("callback"),
                                assigned.get("props") or [])
    continuity_block = daypart.get("_continuity_desk") or ""
    continuity_line = (f"\n{continuity_block}\n" if continuity_block else "")
    extra = daypart.get("_extra_context")
    extra_line = f"\nREAL-WORLD GROUNDING (use it, keep numbers roughly right):\n{extra}\n" if extra else ""
    user = f"""Write the outline for this show. Today is {weekday}.{extra_line}

SHOW: {daypart['show']}
ENERGY: {daypart['energy']}{pacing_line}{arc_line}
CAST:
{personas}

RECURRING SEGMENTS TO HIT:
{segments}

{beat_shape}

Optional creative hints per beat:
Focus on the creative core: segment, premise, and beat. The fields below are
optional hints; do not spend effort balancing them. The assignment desk and
code finalize guest, props, callback count, and pacing after you answer:
- "grounding": an optional mundane physical detail for the beat.
- "callback": an optional lore item to reference, normally null.
- "no_bit" and "monologue": optional register hints; normally false.

{guest_line}

{theory_contract}
{continuity_line}
{daypart.get('_watcher_history') or ''}

{assign_block}

STATION LORE (call back to these where natural):
{lore.digest(lore_state)}

PREMISES ALREADY AIRED RECENTLY — do NOT reuse or lightly reskin any of these:
{chr(10).join('- ' + p for p in lore_state.get('recent_premises', [])[-60:]) or '(none yet)'}

WORN-OUT SUBJECTS & PROPS — these have shown up too often lately and are now
STALE. Do NOT build a beat around them and do NOT use them as grounding; reach
for something genuinely different this show:
{', '.join(lore.overused(lore_state)) or '(none yet)'}

Return STRICT JSON:
{{
  "show": "{daypart['show']}",
  "guest": "<guest name or null>",
  "theory": "<for arc shows: one line naming this outline's single theory; else null>",
  "payoff": "<for arc shows: the one-sentence final landing; else null>",
  "builds_on": "<prior chapter id or null>",
  "loose_threads": ["<optional future seed>", "..."],
  "beats": [
    {{"segment": "<segment name>",
      "premise": "<one-line setup>",
      "beat": "<what happens, the turn, the punchline target>",
      "grounding": "<optional mundane physical detail>",
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
    return _normalize_outline_shape(_parse_json(raw, daypart), daypart)


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
            out["theory"] = (str(out.get("theory")).strip()
                            if out.get("theory") else None)
            out["payoff"] = (str(out.get("payoff")).strip()
                             if out.get("payoff") else None)
            out["builds_on"] = (str(out.get("builds_on")).strip()
                                if out.get("builds_on") else None)
            out["loose_threads"] = [
                str(x).strip() for x in (out.get("loose_threads") or [])
                if str(x).strip()
            ][:4]
            out["beats"] = [{"segment": str(b.get("segment", "segment")),
                             "premise": str(b.get("premise", "")),
                             "beat": str(b.get("beat")),
                             "link": str(b.get("link") or ""),
                             "move": str(b.get("move") or ""),
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
            "theory": None,
            "payoff": None,
            "builds_on": None,
            "loose_threads": [],
            "beats": [{"segment": s, "premise": s, "beat": s}
                      for s in daypart.get("segments", [])],
            "new_jokes": [],
            "callbacks_used": [],
        }


def _normalize_outline_shape(out: dict, daypart: dict) -> dict:
    """Let code own outline shape and assignments; let the model write content."""
    if not isinstance(out, dict):
        out = {}
    beats = [dict(b) for b in (out.get("beats") or [])
             if isinstance(b, dict) and str(b.get("beat") or "").strip()]
    try:
        lo, hi = (int(x) for x in daypart.get("outline_beats", [12, 16]))
        lo, hi = max(1, lo), max(lo, hi)
    except Exception:
        lo, hi = 1, 16
    segments = list(daypart.get("segments") or ["Segment"])
    if len(beats) > hi:
        beats = beats[:hi]
    while len(beats) < lo:
        idx = len(beats)
        segment = segments[idx % len(segments)]
        beats.append({
            "segment": segment,
            "premise": f"a fresh angle on {segment}",
            "beat": f"play the next part of {segment} in this show's register",
        })
    assigned = daypart.get("_assign") or {}
    props = list(assigned.get("props") or [])
    if assigned.get("guest"):
        out["guest"] = assigned["guest"]
    elif str(daypart.get("guest", "never")).lower() not in ("always", "true", "wednesday"):
        out["guest"] = None
    keep_callback = assigned.get("callback")
    callback_seen = 0
    for idx, beat in enumerate(beats):
        beat.setdefault("segment", segments[idx % len(segments)])
        beat.setdefault("premise", beat["segment"])
        beat.setdefault("beat", beat["premise"])
        if props:
            beat["grounding"] = props[idx % len(props)]
        callback = str(beat.get("callback") or "").strip() or None
        if keep_callback:
            callback = callback if callback == keep_callback and not callback_seen else None
        elif callback and callback_seen >= 2:
            callback = None
        if callback:
            callback_seen += 1
        beat["callback"] = callback
        if "quiet part" in str(beat.get("segment", "")).lower():
            beat["no_bit"] = True
    out["beats"] = beats
    return out
