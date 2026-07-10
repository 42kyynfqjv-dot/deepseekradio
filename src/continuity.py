"""Continuity — promises the hosts make, the code keeps.

Two on-air lies this kills: a host says "we'll be right back after this" and
no break follows (fixed by FULFILLING the promise — the orchestrator queues a
real break marker, and the player guarantees a break marker always yields
spots or a bumper, never silence); and a host drifts into a sign-off while
minutes remain in the show (fixed by neutral-replacing the line — only the
code-scheduled handoff beat may say goodbye). The prompt side is handled by
the SHOW CLOCK line (air-time minutes remaining) fed to every beat.

Stdlib-only leaf module: orchestrator imports this, never the reverse.
"""
from __future__ import annotations

import hashlib
import re

_BREAK_PROMISE = re.compile(
    r"(?:we'?ll be )?right back after|after (?:this|these|the break)|"
    r"when we come back|don'?t go anywhere|stay with us.{0,20}break|"
    r"back in a (?:minute|moment|flash)|quick break|short break|"
    r"pay (?:some|a few) bills", re.I)
_SIGNOFF = re.compile(
    r"that'?s (?:our|the|all the) show|that'?s all for (?:tonight|today|us)|"
    r"sign(?:ing)? off|we'?re done for the (?:night|day)|"
    r"good ?night,? everybody|good ?night,? (?:halfway|wending)|"
    r"see you (?:tomorrow|next time|next week)|thanks for (?:listening|"
    r"joining us) tonight", re.I)

_NEUTRAL = ["Plenty more ahead this hour, so stay close.",
            "And we roll on — lots still to get to.",
            "More to come on this one, don't drift far."]


def _stable_hash(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


def enforce(lines: list[dict], *, handoff: bool = False) -> tuple:
    """Walk a beat's lines. Returns (new_lines, wants_break). Premature
    sign-offs are REPLACED (never cut — a cut dangles the co-host's reply);
    the handoff beat is exempt (goodbyes are its job). A break promise
    anywhere sets wants_break so the caller queues a REAL break marker right
    after this segment — the promise is kept, not policed. Inputs unmutated."""
    out = []
    wants_break = False
    for ln in lines:
        text = ln.get("text", "")
        if _BREAK_PROMISE.search(text):
            wants_break = True
        if not handoff and _SIGNOFF.search(text):
            new = dict(ln)
            new["text"] = _NEUTRAL[_stable_hash(text) % len(_NEUTRAL)]
            new["_enforced"] = True
            print(f"  !! continuity: premature sign-off replaced: {text[:50]!r}")
            out.append(new)
            continue
        out.append(ln)
    return out, wants_break


def show_clock_line(minutes_left: float) -> str:
    """The SHOW CLOCK prompt block — the air-time truth about how much show
    remains, so nobody wraps early and nobody rushes a handoff."""
    m = max(0, int(minutes_left))
    if m >= 12:
        return (f"SHOW CLOCK (authoritative): about {m} minutes of this show "
                "remain. Do NOT sign off, wrap up, or tease the handoff — "
                "the show keeps rolling.")
    return (f"SHOW CLOCK (authoritative): about {m} minutes remain — the "
            "scheduled handoff is coming soon, but ONLY the handoff beat "
            "says goodbye; until then, keep the show fully alive.")
