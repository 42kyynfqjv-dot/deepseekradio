"""Continuity desk — the arcs+census wiring the assignment desk hands the show.

Row E of the arcs+census fleet. Scoreguard owns the score, switchboard owns who
is on the line; this leaf owns HOW TONIGHT'S CANON REACHES THE PROMPT and WHICH
BEATS THE CANON GUARD TIGHTENS ON. It is pure string/decision plumbing between
three frozen surfaces — `arcs.next_beat_for_show`, `census.due_follow_ups`,
`canonguard.build_canon_facts` — and the orchestrator's desk block, switchboard
mint, and beat loop.

Three public helpers, all pure (stdlib-only, no I/O, deterministic):

    canon_block(arc_beat, follow_up) -> str
        The authoritative CONTINUITY DESK prompt block (SCOREBOARD register):
        tonight's arc beat + the returning-resident callback. "" when the desk
        assigned neither (so the gate-off path renders byte-identically).

    switchboard_identity(follow_up) -> tuple[str, str | None] | None
        The returning resident's (name, gender) the caller-mint forces so the
        follow-up caller re-enters on her own deterministic `_spare_voice`.
        None when no follow-up is due -> the mint stays today's fresh cast.

    beat_scope(arc_beat, follow_up, lines) -> {"scope", "scope_ids"}
        The BEAT-FLAGGING CONTRACT (facts scope). A beat's lines tighten the
        canon guard ONLY when the assigned arc's cast/title or the returning
        resident's name actually surfaces in THIS beat; every other beat stays
        scope="none" (a proven pass-through, so a fresh caller is never
        scrubbed). Output feeds `canonguard.build_canon_facts(..., scope_ids=,
        scope=)` verbatim.

Frozen input shapes (what arcs.py / census.py hand the desk; this module reads
only these keys, tolerating missing ones):

  arc_beat = arcs.next_beat_for_show(arcs_state, date, show_id)  # or None
    {"arc_id": "arc-roundabout-fern-3",
     "title": "The Roundabout Fern",
     "bid": "b3", "stage": "COMPLICATION", "day": 3,
     "directive": "the town starts leaving it tiny gifts",
     "canon": ["the fern is at the Mile Zero roundabout",
               "its name is Sheila", "Toivo Ostberg is the foreman"],
     "payoff": False,                 # True ONLY on the scheduled payoff beat
     "register": "mundane",
     "cast_ids": ["cv-doreen-2"],     # subject ids for the guard's scope
     "cast_names": ["Doreen", "Toivo Ostberg"],   # proper nouns to trigger on
     "names": ["Sheila"]}             # extra proper nouns (the fern's name)

  follow_up = (census.due_follow_ups(civ_state, date, show_id)[:1] or [None])[0]
    {"cid": "cv-maureen-1", "name": "Maureen", "gender": "f",
     "hood": "the pharmacy-lot blocks",
     "status_line": "her upstairs-neighbor sock ceasefire is holding",
     "question": "how's the sock ceasefire holding?"}

Stdlib-only leaf module: orchestrator imports this, never the reverse.

================================================================================
ORCHESTRATOR PATCH SPEC — exact diff for the 3 insertion points.
Integration (Row F) owns src/orchestrator.py; this module is NOT to edit it.
Every hunk is guarded so the gate-off path (no data/arcs/ENABLED, or the desk
assigning neither pick) is byte-identical to today. Helpers are called exactly
as written below.
================================================================================

--- INSERTION 1 — desk picks + the CONTINUITY DESK block -----------------------
src/orchestrator.py, inside the assignment-desk try (after `daypart["_assign"]
= {...}` closes at ~L367, before its `except`):

     daypart["_assign"] = {
         "guest": _adesk.pick_guest(...),
         "sponsor": _arng.choice(_ros) if _ros else None,
         "callback": _adesk.pick_callback(state, _arng),
         "props": _adesk.prop_candidates(
             state.get("recent_grounding", []), _arng),
     }
+        # --- CONTINUITY DESK (arcs+census) — gated, garnish-safe ---
+        if Path("data/arcs/ENABLED").exists():
+            from . import arcs as _arcs, census as _census
+            from . import continuity_desk as _cdesk
+            _cdate = f"{clock.air_now():%Y-%m-%d}"
+            _arc_beat = _arcs.next_beat_for_show(
+                _arcs.load(), _cdate, daypart["id"])
+            _follow = (_census.due_follow_ups(
+                _census.load(), _cdate, daypart["id"])[:1] or [None])[0]
+            daypart["_assign"]["arc_beat"] = _arc_beat
+            daypart["_assign"]["follow_up"] = _follow
+            daypart["_continuity_desk"] = _cdesk.canon_block(_arc_beat, _follow)

`daypart["_continuity_desk"]` is appended to the outline/performer prompt beside
the existing ASSIGNMENT DESK block (writer surface, Row F). When the gate is off
the key is absent and the prompt is unchanged.

--- INSERTION 2 — returning-resident name into the switchboard mint ------------
src/orchestrator.py `_mint_caller_line` (L253) gains an `identity` param; the
two call sites (L505, L545) pass the follow-up's forced name so the returning
caller re-enters on her own voice:

 def _mint_caller_line(used, seedkey: str, host_speaker: str,
-                      ) -> str:
+                      identity=None) -> str:
     ...docstring...
     try:
+        if identity:                       # a returning resident: pin her name,
+            try: used.add(identity)        # do NOT mint a fresh one (her voice
+            except Exception: pass         # is _spare_voice(name), deterministic)
+            return f" If a NEW caller joins, their name is {identity}."
         from . import assignments as _adesk
         from .performers import _gender_of
         want = {"f": "m", "m": "f"}.get(_gender_of(host_speaker or ""))
         nm = _adesk.next_caller(set(used), random.Random(seedkey), want=want)
         ...

Both call sites resolve the identity from the desk pick (None when gate-off or
no follow-up due, so the fresh-mint path is untouched):

     daypart["_switchboard"] = _switch.prompt_line(call_st) + _mint_caller_line(
         used_names, f"caller:{clock.air_now():%Y-%m-%d}:{daypart['id']}:0",
-        _cast_meta(daypart, 0).get("speaker", ""))
+        _cast_meta(daypart, 0).get("speaker", ""),
+        identity=(lambda fu: fu[0] if fu else None)(
+            continuity_desk.switchboard_identity(
+                daypart.get("_assign", {}).get("follow_up"))))

(identical change at the L545 mint call; `import continuity_desk` at module top.)

--- INSERTION 3 — arc-beat flags on beats: the scoped canon guard -------------
src/orchestrator.py beat loop, immediately AFTER `lines, _wb = _cont.enforce(
lines, handoff=_is_throw)` (L551), matching the _switch/_cont enforce site:

     lines, _wb = _cont.enforce(lines, handoff=_is_throw)
+            _cdk = daypart.get("_assign", {})
+            if daypart.get("_continuity_desk"):     # gate: desk assigned canon
+                try:
+                    from . import canonguard, continuity_desk as _cdesk
+                    _sc = _cdesk.beat_scope(_cdk.get("arc_beat"),
+                                            _cdk.get("follow_up"), lines)
+                    if _sc["scope"] != "none":
+                        _cf = canonguard.build_canon_facts(
+                            arcs.load(), census.load(),
+                            scope_ids=_sc["scope_ids"], scope=_sc["scope"])
+                        lines = canonguard.enforce_canon(lines, _cf)
+                except Exception as e:              # a guard fault never kills air
+                    print(f"  (canon guard skipped: {e})")

`beat_scope` returns scope="none" for every beat that does not surface the
assigned arc/resident, so the guard is a pass-through there and fresh call-in is
untouched — the scope-gating in continuity §guard/risk-1. The census-mint hook
(record the aired caller as a civilian) is Row F's own change to the existing
phone-name loop at L555; it is not one of these three points.
================================================================================
"""
from __future__ import annotations

import re

# The block header — SCOREBOARD/authoritative register, matching every sibling
# desk block ("ASSIGNMENT DESK (authoritative ...)", "SWITCHBOARD (authoritative
# ...)"). Kept as a module constant so the guard round-trip test can anchor it.
HEADER = "CONTINUITY DESK (authoritative — canon, do not contradict):"

SCOPE_NONE = "none"
SCOPE_ARC = "arc"
SCOPE_FOLLOWUP = "followup"

# trigger-token stopwords: an arc title's structural words must never be what
# tightens the guard (a beat that merely says "the" is not an arc beat)
_STOP = {"the", "a", "an", "and", "of", "to", "in", "on", "at", "for", "with",
         "that", "this", "won", "wont", "will", "its", "it", "is", "are", "was",
         "who", "how", "when", "why", "day", "night", "story", "town"}


def _sig_words(text: str) -> list[str]:
    """Significant lowercase words of a title/phrase — its trigger fingerprint.
    len>3 (so 'fern'/'sock' count, 'the'/'won' don't) and not a stopword."""
    return [w for w in re.findall(r"[a-z']+", (text or "").lower())
            if len(w) > 3 and w not in _STOP]


def _name_tokens(name: str) -> list[str]:
    """Proper-noun tokens to trigger on — every word of a display name len>2
    ('Toivo', 'Ostberg', 'Doreen'), so either half of a full name fires."""
    return [w for w in re.findall(r"[A-Za-z']+", name or "")
            if len(w) > 2 and w.lower() not in _STOP]


def _arc_triggers(arc_beat: dict) -> set[str]:
    """The lowercase tokens whose presence in a beat marks it an arc beat:
    the title's significant words + every cast/extra proper noun."""
    trig: set[str] = set(_sig_words(arc_beat.get("title", "")))
    for nm in (list(arc_beat.get("cast_names") or [])
               + list(arc_beat.get("names") or [])):
        trig.update(w.lower() for w in _name_tokens(nm))
    return {t for t in trig if t}


def _mentions(text_lc: str, tokens) -> bool:
    """True if any token appears as a whole word (word-boundary), so 'fern'
    does not fire on 'fernando' and 'Al' does not fire on 'always'."""
    for tok in tokens:
        if tok and re.search(r"\b" + re.escape(tok.lower()) + r"\b", text_lc):
            return True
    return False


# ------------------------------------------------------------------ the block

def _arc_bullet(arc_beat: dict) -> str:
    title = arc_beat.get("title", "the arc")
    day = arc_beat.get("day")
    day_txt = f", day {day}" if day else ""
    directive = (arc_beat.get("directive") or "").strip().rstrip(".")
    canon = [c.strip().rstrip(".") for c in (arc_beat.get("canon") or []) if c]
    canon_txt = ("; ".join(canon) + "." ) if canon else ""
    close = ("TONIGHT the story pays off — land the ending, in character."
             if arc_beat.get("payoff") else "Do NOT resolve the story tonight.")
    parts = [f'- ARC BEAT (weave into exactly one mid-show beat): "{title}"'
             f'{day_txt} — TONIGHT\'S development: {directive}.']
    if canon_txt:
        parts.append(f"  Canon you must honor: {canon_txt}")
    parts.append(f"  {close}")
    return "\n".join(parts)


def _returning_bullet(follow_up: dict) -> str:
    name = str(follow_up.get("name", "")).strip()
    hood = (follow_up.get("hood") or "").strip()
    status = (follow_up.get("status_line") or "").strip().rstrip(".")
    question = (follow_up.get("question") or "").strip()
    if question and not question.endswith(("?", ".")):
        question += "?"
    where = []
    if hood:
        where.append(f"from {hood}")
    if status:
        where.append(status)
    where_txt = f" ({'; '.join(where)})" if where else ""
    ask = f" and asks: {question}" if question else ""
    return (f"- CALL BACK a real resident: {name.upper()} returns tonight"
            f"{where_txt}. The host greets them as a returning caller{ask} "
            "Keep every stated fact consistent with the above; invent nothing "
            "that contradicts it.")


def canon_block(arc_beat: dict | None, follow_up: dict | None) -> str:
    """The CONTINUITY DESK authoritative prompt block. Empty string when the
    desk assigned neither pick — so the gate-off prompt is byte-identical."""
    bullets = []
    if arc_beat:
        bullets.append(_arc_bullet(arc_beat))
    if follow_up and follow_up.get("name"):
        bullets.append(_returning_bullet(follow_up))
    if not bullets:
        return ""
    return HEADER + "\n" + "\n".join(bullets)


# ----------------------------------------------------------- switchboard mint

def switchboard_identity(follow_up: dict | None):
    """The returning resident's (name, gender) the caller-mint must force so
    she re-enters on her own deterministic voice. None -> today's fresh cast."""
    if not follow_up or not str(follow_up.get("name", "")).strip():
        return None
    return (str(follow_up["name"]).strip(), follow_up.get("gender"))


# --------------------------------------------------------- beat-flag contract

def beat_scope(arc_beat: dict | None, follow_up: dict | None,
               lines: list[dict]) -> dict:
    """Decide the canon guard's scope for THIS beat. A beat tightens only when
    the assigned resident's name (-> 'followup') or the arc's title/cast proper
    nouns (-> 'arc') actually surface in its lines; otherwise 'none' (a
    pass-through). scope_ids are the subject ids canonguard should load — the
    resident's cid and/or the arc id + its cast ids, deduped. Pure; never
    mutates inputs."""
    text_lc = " ".join(str(ln.get("text", "")) for ln in (lines or [])).lower()
    scope = SCOPE_NONE
    ids: list[str] = []

    fu_name = str((follow_up or {}).get("name", "")).strip()
    if fu_name and _mentions(text_lc, [fu_name]):
        scope = SCOPE_FOLLOWUP          # a returning resident outranks the arc
        cid = (follow_up or {}).get("cid")
        if cid:
            ids.append(cid)

    if arc_beat and _mentions(text_lc, _arc_triggers(arc_beat)):
        if scope == SCOPE_NONE:
            scope = SCOPE_ARC
        arc_id = arc_beat.get("arc_id")
        if arc_id:
            ids.append(arc_id)
        ids.extend(c for c in (arc_beat.get("cast_ids") or []) if c)

    ids = [i for i in dict.fromkeys(ids) if i]   # order-stable dedupe
    return {"scope": scope, "scope_ids": ids}
