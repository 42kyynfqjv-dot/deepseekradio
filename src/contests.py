"""Contests — the station's giveaways, as a code-owned fact source.

The desk (code) decides WHAT is given away, on WHICH show, and WHICH caller
wins; the LLM only performs the bit. One or two seeded contests exist per
broadcast day, drawn from a station prize bank (Center Ice tickets, a
Frequency mug that hums) mixed with sponsor-tied prizes built from the live
(name, gag) roster the Continuity Department already rotates on air.

`directive()` is the authoritative CONTEST block the show writer must obey:
announce once, the Nth caller wins, the winner is desk-assigned by name, keep
it brief, never re-run it. The winning caller number is the ONLY number the
block hands the writer, so it is trivially verifiable (desk pattern).

Winners are recorded to data/town/contests.json (atomic tmp+replace) and age
themselves out: each prize is "unclaimed" for a seeded 2-5 days, during which
`uncollected()` feeds the Town Desk a follow-up one-liner ("June's mattress
remains unclaimed") on later days, then it quietly counts as collected.

Stdlib-only leaf module: the Town Desk / orchestrator import this, never the
reverse. Seeded determinism throughout (random.Random on stable strings; no
bare random, no wall-clock). Every invented prize noun is station/townscape
vocabulary, checked to collide with none of nameguard._WORLD_TOKENS /
_WORLD_PHRASES.
"""
from __future__ import annotations

import datetime
import json
import os
import random
from pathlib import Path

PATH = Path("data/town/contests.json")

# Daypart ids (schedule.yaml) that plausibly run a live call-in giveaway. The
# late-night insomnia (night_shift) and conspiracy (static_hour) hours are
# deliberately left out — a caller-number contest is not their register.
SHOWS = [
    "center_ice", "morning_scramble", "refined_palate",
    "complaints_department", "the_handover", "culture_vulture", "dawn_patrol",
]

# Station-owned prizes — evergreen, digit-free (so the directive's only number
# stays the winning caller), and free of any real brand/person token.
_STATION_PRIZES = [
    "a pair of Center Ice tickets",
    "a Frequency mug that hums",
    "a Frequency tote nobody can fold back up",
    "the good parking spot outside the station for a week",
    "a Frequency ballcap, one size too confident",
    "a signed Bucky Merle cocktail napkin",
    "naming rights to a pothole on Fifth for a month",
    "a Frequency hoodie in the one color left",
    "a Frequency travel mug that keeps things exactly room temperature",
    "a station tour that runs long",
    "a lifetime supply of Frequency bumper stickers",
    "front-row seats to the next Complaints Department taping",
]

# Sponsor-tied prizes, built from a live (name, gag) roster tuple. Name-first
# so the sponsor gets the read; the possessive form is what yields the
# "June's mattress" follow-up flavor downstream.
_SPONSOR_PRIZES = [
    lambda name, gag: f"a gift card to {name}",
    lambda name, gag: f"a {name} gift basket",
    lambda name, gag: f"the grand prize from {name}",
    lambda name, gag: f"a year's worth of {name}",
    lambda name, gag: f"a {name} swag bag",
    lambda name, gag: f"a {name} prize pack",
]

# Winning-caller numbers — small, air-friendly, all odd/round classics.
_CALLER_NS = [3, 4, 5, 7, 9, 11, 13]

_ARTICLES = ("a pair of ", "the grand prize from ", "a year's worth of ",
             "an ", "a ", "the ")


# --------------------------------------------------------------- today's slate

def todays(date: str, sponsors: list[tuple[str, str]]) -> list[dict]:
    """The 1-2 seeded contests for `date`. Each: {"show": daypart_id,
    "prize": str, "n": int}. Pure and deterministic in (date, sponsors):
    same day, same sponsor roster -> same giveaways, so a 6 AM promo and the
    show itself agree on the prize and the winning caller number."""
    rng = random.Random(f"contests:{date}")
    k = rng.choice([1, 1, 2])                       # usually one, sometimes two
    shows = rng.sample(SHOWS, k)
    out = []
    for show in shows:
        if sponsors and rng.random() < 0.5:
            name, gag = rng.choice(list(sponsors))
            prize = rng.choice(_SPONSOR_PRIZES)(name, gag)
        else:
            prize = rng.choice(_STATION_PRIZES)
        out.append({"show": show, "prize": prize, "n": rng.choice(_CALLER_NS)})
    return out


# ------------------------------------------------------------- the directive

def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def directive(contest: dict, winner_name: str) -> str:
    """The authoritative CONTEST block. The show writer AUTHORS the bit; this
    is the only truth. The winning caller number `n` is the single number
    handed over, and it is the answer itself — nothing else numeric may air."""
    n = contest["n"]
    prize = contest["prize"]
    return "\n".join([
        "CONTEST (authoritative — run this giveaway EXACTLY once this show):",
        f"- The prize is {prize}.",
        "- Announce the contest ONE time, near the top, then take calls.",
        f"- The {_ordinal(n)} caller wins — that caller is {winner_name}, "
        "already on the line (desk-assigned; do not re-cast the winner).",
        f"- Put {winner_name} on air, confirm the win, keep the celebration "
        "to a line or two, then move on.",
        "- Do NOT re-announce, re-run, or hold a second draw later this show — "
        "one winner, done.",
        f"- The ONLY number you may say is {n} (the winning caller). Invent no "
        "phone numbers, no odds, no dollar values.",
    ])


# ------------------------------------------------------------- winner state

def _load() -> dict:
    try:
        s = json.loads(PATH.read_text())
        if isinstance(s, dict) and isinstance(s.get("winners"), list):
            return s
    except (FileNotFoundError, ValueError):
        pass
    return {"winners": []}


def _save(state: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(PATH)


def _d(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s)


def record_winner(date: str, show: str, prize: str, winner: str) -> None:
    """Log a giveaway winner. Idempotent per (date, show, winner, prize) —
    re-recording the same win is a no-op, so a re-aired or re-run tick never
    doubles a follow-up. The uncollected window is seeded 2-5 days here and
    frozen into the record. Records aged well past their window are pruned so
    the state file stays bounded."""
    state = _load()
    winners = state["winners"]
    dup = any(w["date"] == date and w["show"] == show
              and w["winner"] == winner and w["prize"] == prize
              for w in winners)
    if not dup:
        days = random.Random(
            f"collect:{date}:{show}:{winner}").randint(2, 5)
        winners.append({"date": date, "show": show, "prize": prize,
                        "winner": winner, "days": days})
    today = _d(date)
    state["winners"] = [
        w for w in winners if (today - _d(w["date"])).days <= 14]
    _save(state)


_FOLLOWUP_TEMPLATES = [
    lambda w, p: f"{w}'s {p} remains unclaimed.",
    lambda w, p: f"Still no sign of {w} down at the station to claim the {p}.",
    lambda w, p: f"{w} still hasn't come by for the {p}.",
    lambda w, p: f"That {p} {w} won? Still sitting here at the front desk.",
]


def _bare_prize(prize: str) -> str:
    low = prize.lower()
    for art in _ARTICLES:
        if low.startswith(art):
            return prize[len(art):]
    return prize


def uncollected(date: str) -> list[str]:
    """Seeded follow-up one-liners for prizes still unclaimed on `date` —
    for the Town Desk to sprinkle on later days. A win is unclaimed on the
    days strictly between the win and win+`days`, then it silently ages to
    collected (derived, never stored). Deterministic per (date, winner)."""
    today = _d(date)
    out = []
    for w in _load()["winners"]:
        delta = (today - _d(w["date"])).days
        if 0 < delta < w["days"]:
            tmpl = random.Random(
                f"followup:{date}:{w['date']}:{w['winner']}").choice(
                    _FOLLOWUP_TEMPLATES)
            out.append(tmpl(w["winner"], _bare_prize(w["prize"])))
    return out
