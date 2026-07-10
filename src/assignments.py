"""Assignment desk — the last operational decisions leave the LLM.

Code is the producer; the model is the writers' room. The desk assigns, per
show: tonight's GUEST (recency-rotated from the pool), the host-read SPONSOR
beat (even rotation, closing the last sponsor-dominance surface), the ONE
designated lore CALLBACK, a set of fresh grounding-PROP candidates, and the
NEXT CALLER's identity (name chosen by code, so the gender-pinned voice is
deterministic by construction and names never repeat or collide). Prompt
blocks are authoritative in the SCOREBOARD/SWITCHBOARD register; the LLM
authors around them.

Stdlib-only leaf module: writer/orchestrator import this, never the reverse.
"""
from __future__ import annotations

import re

# caller first names — disjoint from cast, sponsors' proprietors (Gary, Ted,
# Craig, Kevin, Mildred, Wanda, Marge, Hal, Greg, Todd, Ron, Bernard, Quiet
# Ron...), officials, and the league name bank, so a caller can never collide
# with somebody who exists. Gender known by construction.
CALLERS_F = ("Ruth Carol Judy Elaine Doreen Phyllis Irene Sylvia Lois Bev "
             "Marcia Glenda Faye Roberta Annette Charlene Dot Ida Maxine "
             "Paulette Rhoda Selma Twyla Vera Winnie Yolanda Zelda Carla "
             "Dana Joanne").split()
CALLERS_M = ("Al Marv Sid Ernie Chet Dale Freddy Gene Harv Ike Judd Lyle "
             "Mickey Ned Oscar Phil Ray Sherm Vern Wade Art Bud Cy Dez "
             "Emmett Felix Grover Herm Irv Jasper").split()

# grounding props — mundane physical anchors the writer draws from; the desk
# offers a fresh, unworn dozen per show so beats never re-run the same toaster
PROPS = (
    "a space heater with one working setting", "a laminated seating chart",
    "a jar of pens that all skip", "the studio's second-best stapler",
    "a wall calendar still on March", "a thermos that smells like 1998",
    "an exit sign that hums", "a chair that lists slightly left",
    "a phone cord stretched past usefulness", "a window plant nobody waters",
    "a coffee ring shaped like Ohio", "the label maker with no tape",
    "a drawer of mismatched batteries", "an umbrella drying in the corner",
    "a radiator that knocks twice", "the visitor badge from 2019",
    "a box of donated cassette tapes", "a spider plant named by committee",
    "the vending machine's B4 slot", "a doorstop shaped like a duck",
    "a whiteboard that won't fully erase", "the good scissors, missing again",
    "a parking-validation stamp", "an ice scraper in July",
    "the little bell from the front desk", "a fire-drill map, hand-corrected",
    "a mug of unclaimed keys", "the third-floor window that sticks",
    "a sleeve of paper cups, crushed", "an extension cord coiled wrong",
    "the sign-in clipboard's dead pen", "a snow globe of somewhere else",
    "the break-room fridge's mystery jar", "a carpet tile that doesn't match",
    "an award for perfect attendance", "the elevator inspection certificate",
    "a bag of rubber bands gone brittle", "the lost-and-found sombrero",
    "a desk fan aimed at nobody", "the sticky note that just says 'ask'",
)

_GUEST_RE = re.compile(r"^- \*\*([^*]+)\*\*", re.M)


def next_caller(used: set, rng, want: str | None = None) -> str:
    """The next caller's first name — never a reuse, gender by construction
    (the voice pin becomes deterministic). `want` forces 'f'/'m'."""
    g = want or rng.choice("fm")
    pool = [n for n in (CALLERS_F if g == "f" else CALLERS_M)
            if n not in used and n.lower() not in {u.lower() for u in used}]
    if not pool:
        pool = list(CALLERS_F if g == "f" else CALLERS_M)
    return rng.choice(pool)


def pick_guest(pool_text: str, seen: list, rng) -> str | None:
    """Tonight's guest, rotated by code: never one of the recently seen."""
    names = _GUEST_RE.findall(pool_text or "")
    if not names:
        return None
    recent = {s.lower() for s in (seen or [])[-6:]}
    fresh = [n for n in names if n.lower() not in recent]
    return rng.choice(fresh or names)


def pick_callback(lore_state: dict, rng) -> str | None:
    """The ONE lore item this show may call back — code-designated, so the
    same joke can't get worn thin by model favoritism."""
    pool = []
    for key in ("running_jokes", "feuds", "recent_callbacks"):
        pool.extend(lore_state.get(key, [])[-12:])
    pool = [p for p in dict.fromkeys(pool) if p]
    return rng.choice(pool) if pool else None


def prop_candidates(recent: list, rng, n: int = 10) -> list:
    """A fresh dozen grounding props, excluding recently used ones."""
    worn = {w.lower() for w in (recent or [])}
    fresh = [p for p in PROPS if p.lower() not in worn]
    picks = list(fresh or PROPS)
    rng.shuffle(picks)
    return picks[:n]


def writer_block(guest: str | None, sponsor: tuple | None,
                 callback: str | None, props: list) -> str:
    """The ASSIGNMENT DESK block for the outline writer — authoritative."""
    lines = ["ASSIGNMENT DESK (authoritative — the desk decides, you write):"]
    if guest:
        lines.append(f"- Tonight's guest is ASSIGNED: {guest}. Do not choose "
                     "a different one; write them per the pool description.")
    if sponsor:
        lines.append(f"- The sponsor-read beat's sponsor is ASSIGNED: "
                     f"{sponsor[0]} — {sponsor[1]}. No other sponsor gets a "
                     "host read this show.")
    if callback:
        lines.append(f"- The ONE permitted lore callback is ASSIGNED: "
                     f"\"{callback}\" — exactly one mid-show beat sets its "
                     "callback field to this; every other beat's callback is "
                     "null.")
    if props:
        lines.append("- Draw every beat's grounding from these candidates, "
                     "no repeats: " + "; ".join(props) + ".")
    return "\n".join(lines) if len(lines) > 1 else ""
