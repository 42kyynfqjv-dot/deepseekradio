"""Statehouse votes: whip counts and floor-vote resolution as pure functions
of member leans and per-bill seeds. Stdlib-only leaf module -- no imports of
season.py/orchestrator.py/league modules, no storage; every number here is
recomputed on demand from `(ga, bill_id, mid)`.

Schema contract this module consumes (statehouse-mirror.md §2, frozen):
  member dict: {"name","chamber","district","party","zipper","maverick",
                "tenure","aired","attend"} -- `attend` is final.md delta 1's
                grafted per-member attendance scalar in [0.88, 0.98].
  bill dict:   the docket-ga{n}.json per-bill value ("title","sponsor",
                "committee","stage","intro","marquee","history",...).

Friction notes (schema frozen, conforming as written):
  - The §2 docket schema never embeds a bill's own id inside its per-bill
    dict (the id is only the outer `bills` mapping's key, e.g. "HB-7"), yet
    the frozen seed spec is literally `Random(f"vote:{ga}:{bill}:{mid}")`
    and members.py's mandated `goose_price(bill: dict) -> str | None` takes
    only a bill dict. A pure, replayable function cannot seed on an id it
    was never given, so every function below takes an explicit `bill_id`
    string alongside the bill's content dict (the `bill` token in the
    frozen seed string is this id) -- a necessary, minimal deviation from
    the 1-arg `goose_price` signature quoted in the mirror, reported here
    rather than silently improvised.
  - The §2 docket schema also has no `axis` (the bill's Zipper-relevant
    lean), `tags`/`goose_tag`, or `class` ("ordinary"|"override") fields on
    a bill, though members.py's `member_vote` doc explicitly requires
    `bill.axis` and final.md delta 4 requires a goose-tag concept. All three
    are read via `.get(...)` with neutral defaults (axis 0.5, no tags,
    class "ordinary") so this module works standalone against the frozen
    example bill shape; docket.py (a sibling, unbuilt-as-of-this-component)
    is expected to populate them.
  - Chamber is inferred from the sponsor id's letter prefix (`chamber_of`)
    since the bill schema has no explicit chamber field either; a second-
    chamber (post-crossover) vote must pass an explicit `chamber=` override
    to `whip_count`/`floor_result`.
  - **OVERRIDE_THRESHOLD**: the synthesis doc's delta 2 misquoted the bar as
    26/51; the grounding (A.2#15, "two-thirds vote of members elected") and
    the mirror's own §11 calibration ("34/51 + 6/9, succeeds <20% of
    attempts") are the real civics — RESOLVED at integration to the true
    two-thirds-of-elected supermajority. A reporter would catch 26.
  - The frozen 4-bucket invariant (`yea+nay+und+absent == chamber size`) has
    no separate "abstain" slot, but final.md delta 4 says a non-pivotal
    Goose vote is "counted in absent/abstain, never invented" -- i.e. it
    names both buckets as acceptable. Non-goose-tagged bills therefore fold
    the Goose bloc's structural abstention into `absent` (they are not
    physically missing, just off-axis and unpriced); documented rather than
    inventing a 5th bucket the frozen schema doesn't have room for.
"""
from __future__ import annotations

import random

# --- constants (Wending scale: 51 House / 9 Senate; wending-bible.md) ------

CHAMBER_SIZE = {"house": 51, "senate": 9}
QUORUM = {"house": 26, "senate": 5}          # majority of elected (grounding A.5)
OVERRIDE_THRESHOLD = {"house": 34, "senate": 6}   # 2/3 of elected (grounding
                                                  # A.2#15; mirror §11)

# Party zipper priors (statehouse-mirror.md members.py doc, verbatim):
# vang anchors Late (mu=0.88), prov cautious Early (mu=0.25), grudge 0.70,
# barb 0.50. `round` is a uniform bloc (no fixed institutional line -- each
# member's own minted `zipper` carries it) and `goose` is off-axis entirely
# (resolved via GOOSE_TAGGED_YEA_P / goose_price, never party_line).
PARTY_MU = {"prov": 0.25, "vang": 0.88, "grudge": 0.70, "barb": 0.50}

# Goose bloc canon (wending-bible.md): off the Zipper axis, purchasable only
# for goose-relevant considerations; final.md delta 4's three tag classes.
GOOSE_TAGS = frozenset({"lot_paving", "waterfowl", "oaths"})
GOOSE_PRICE_LIST = {
    "lot_paving": "the paving crew stays off the pharmacy lot's gravel apron",
    "waterfowl": "a waterfowl-crossing rider written into the roundabout plans",
    "oaths": "no oath is administered anywhere near the Candidate",
}
GOOSE_TAGGED_YEA_P = 0.75     # once a price is plausibly on the table, the
                              # Goose usually takes the deal

ROLL_CALL_P = 0.30           # civics-grounding.md A.6: 65-75% voice / 25-35% roll
UNDECIDED_BAND = 0.10        # |p_yea-0.5| below this reads "undecided" pre-floor
DEFAULT_ATTEND = 0.93        # defensive fallback only -- real members always
                              # carry `attend` per final.md delta 1
DEFAULT_MAVERICK = 0.08


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _rng(ga: int, bill_id: str, mid: str) -> random.Random:
    """The frozen per-bill-per-member seed. A fresh Random(seed) instance is
    minted on every call (never module-global state) so results are
    order-independent across members and bills and replayable forever from
    nothing but (ga, bill_id, mid)."""
    return random.Random(f"vote:{ga}:{bill_id}:{mid}")


def chamber_of(bill: dict) -> str:
    """Origin chamber, inferred from the sponsor id's chamber-letter prefix
    ('H'/'S') since the §2 docket schema carries no explicit chamber field.
    For a bill being voted in its SECOND chamber (post-crossover), pass an
    explicit `chamber=` to whip_count/floor_result instead of relying on
    this inference."""
    sponsor = str(bill.get("sponsor", "H-00")).upper()
    return "senate" if sponsor.startswith("S") else "house"


def _is_goose_tagged(bill: dict) -> bool:
    tags = bill.get("tags") or ()
    return bool(bill.get("goose_tag")) or any(t in GOOSE_TAGS for t in tags)


def party_line(bill: dict, party: str, ga: int) -> float:
    """p(yea) for a generic member of `party` on `bill` -- the leadership's
    whip direction, before any individual member's zipper alignment or
    maverick jitter. `ga` is accepted per the frozen members.py signature as
    a future cross-Assembly-drift hook; nothing in this component uses it
    yet (documented no-op, not a bug). `round` (uniform) and `goose`
    (off-axis) have no fixed line and return a neutral 0.5 -- their vote is
    decided elsewhere (member's own zipper alignment for round; goose_price
    / GOOSE_TAGGED_YEA_P for goose)."""
    del ga
    mu = PARTY_MU.get(party)
    if mu is None:
        return 0.5
    axis = bill.get("axis", 0.5)
    return _clamp01(1.0 - abs(axis - mu))


def _p_yea(m: dict, bill: dict, ga: int) -> float:
    """Blended lean for one non-goose member: half institutional party
    line, half the member's own zipper-to-bill-axis alignment."""
    party = m.get("party")
    axis = bill.get("axis", 0.5)
    zipper = m.get("zipper")
    if zipper is None:
        zipper = 0.5
    align = 1.0 - abs(zipper - axis)
    pl = party_line(bill, party, ga)
    return _clamp01(0.5 * pl + 0.5 * align)


def member_present(mid: str, m: dict, bill_id: str, ga: int) -> bool:
    """Seeded attendance draw (final.md delta 1). This is the FIRST draw
    consumed from `_rng(ga, bill_id, mid)`, shared identically by
    member_stance and member_vote, so a member absent at whip-count time is
    absent at the gavel too."""
    attend = m.get("attend", DEFAULT_ATTEND)
    return _rng(ga, bill_id, mid).random() < attend


def member_stance(mid: str, m: dict, bill_id: str, bill: dict, ga: int) -> str:
    """Pre-floor whip-count reading for one member: 'yea' | 'nay' | 'und' |
    'absent'. A real whip count is a forecast, not a resolution -- it reads
    the deterministic blended lean without spending the floor's own
    conscience/maverick draw. Goose members structurally abstain
    ('absent') on any bill without a goose tag; on a goose-tagged bill they
    read off GOOSE_TAGGED_YEA_P like any other bloc."""
    is_goose = m.get("party") == "goose"
    if is_goose and not _is_goose_tagged(bill):
        return "absent"
    if not member_present(mid, m, bill_id, ga):
        return "absent"
    p = GOOSE_TAGGED_YEA_P if is_goose else _p_yea(m, bill, ga)
    if abs(p - 0.5) < UNDECIDED_BAND:
        return "und"
    return "yea" if p >= 0.5 else "nay"


def member_vote(mid: str, m: dict, bill_id: str, bill: dict, ga: int) -> str:
    """The actual floor-time resolution for one member: 'yea' | 'nay' |
    'absent' -- no undecided state once the roll is actually called.
    Consumes the same shared attendance draw as member_stance/
    member_present, then a commit draw weighted by the blended lean, with a
    maverick-scaled chance of a lean-blind coin-flip defection."""
    is_goose = m.get("party") == "goose"
    if is_goose and not _is_goose_tagged(bill):
        return "absent"
    rng = _rng(ga, bill_id, mid)
    attend = m.get("attend", DEFAULT_ATTEND)
    if rng.random() >= attend:
        return "absent"
    p = GOOSE_TAGGED_YEA_P if is_goose else _p_yea(m, bill, ga)
    maverick = m.get("maverick", DEFAULT_MAVERICK)
    if rng.random() < maverick:
        return "yea" if rng.random() < 0.5 else "nay"
    return "yea" if rng.random() < p else "nay"


def whip_count(bill_id: str, bill: dict, members: dict, ga: int,
               chamber: str | None = None) -> dict:
    """{'yea','nay','und','absent'} headcount across `chamber`'s membership
    -- the session_brief predictive snapshot (statehouse-mirror.md §7).
    Pure in (bill_id, bill, members, ga, chamber). `members` may be the full
    60-member sidecar mapping or a chamber-only slice; members whose
    `chamber` doesn't match are simply skipped. Invariant (tested):
    yea+nay+und+absent == the count of `chamber`-members actually present in
    `members` -- which equals CHAMBER_SIZE[chamber] whenever the caller
    supplies the full canon-sized sidecar."""
    ch = chamber or chamber_of(bill)
    counts = {"yea": 0, "nay": 0, "und": 0, "absent": 0}
    for mid, m in members.items():
        if m.get("chamber") != ch:
            continue
        counts[member_stance(mid, m, bill_id, bill, ga)] += 1
    return counts


def quorum_ok(chamber: str, present: int) -> bool:
    """majority-of-elected quorum test (grounding A.5): 26/51 House, 5/9
    Senate."""
    return present >= QUORUM[chamber]


def vote_type(bill_id: str, ga: int) -> str:
    """Seeded voice/roll-call split (civics-grounding.md A.6): 'roll' with
    probability ROLL_CALL_P (0.30), else 'voice'. Voice votes still resolve
    a real pass/fail internally (floor_result needs one to decide passage);
    it is the broadcast layer's job (briefs.py/civicguard, not this module)
    to withhold the numeric tally on a voice vote."""
    return "roll" if random.Random(
        f"vote:{ga}:{bill_id}:__TYPE__").random() < ROLL_CALL_P else "voice"


def floor_result(bill_id: str, bill: dict, members: dict, ga: int,
                  chamber: str | None = None) -> dict:
    """The actual floor-vote resolution for one bill in `chamber`.

    Returns {'chamber','vote_type','quorum','yea','nay','und','absent',
    'passed','threshold'}. `und` is always 0 here (no undecided state once
    the roll is called) -- kept in the dict so the same 4-bucket invariant
    (yea+nay+und+absent == CHAMBER_SIZE[chamber]) holds for both whip_count
    and floor_result.

    Quorum gates the vote: below QUORUM[chamber] present, no vote occurs
    (quorum=False, passed=False) -- "the call of the House reached eleven
    members and a snowplow," except here the cause is attendance, not
    weather (final.md delta 1).

    Passage: majority of PRESENT-AND-VOTING (yea > nay) for ordinary bills;
    the 'override' bill class instead needs OVERRIDE_THRESHOLD[chamber] yea
    votes out of the full elected membership, regardless of who's absent
    (see the module docstring for the frozen-doc contradiction this
    literally implements: OVERRIDE_THRESHOLD == QUORUM, not a 2/3
    supermajority)."""
    ch = chamber or chamber_of(bill)
    votes = {mid: member_vote(mid, m, bill_id, bill, ga)
             for mid, m in members.items() if m.get("chamber") == ch}
    yea = sum(1 for v in votes.values() if v == "yea")
    nay = sum(1 for v in votes.values() if v == "nay")
    absent = sum(1 for v in votes.values() if v == "absent")
    present = yea + nay
    is_quorum = quorum_ok(ch, present)
    is_override = bill.get("class") == "override"
    if not is_quorum:
        passed = False
    elif is_override:
        passed = yea >= OVERRIDE_THRESHOLD[ch]
    else:
        passed = yea > nay
    return {
        "chamber": ch,
        "vote_type": vote_type(bill_id, ga),
        "quorum": is_quorum,
        "yea": yea, "nay": nay, "und": 0, "absent": absent,
        "passed": passed,
        "threshold": "elected" if is_override else "present-and-voting",
    }


def goose_price(bill_id: str, bill: dict) -> str | None:
    """The Goose bloc's demand for its vote on a goose-tagged bill -- an
    enumerable, canon price list (GOOSE_PRICE_LIST) so civicguard can verify
    any on-air claimed deal. Returns None for any bill without a goose tag
    (the bloc abstains and has nothing to sell). Seeded on `bill_id` alone:
    the same bill always demands the same price, independent of Assembly or
    which member/day evaluates it. (Deviates from the mirror's exact 1-arg
    `goose_price(bill) -> str | None` signature -- see the module docstring
    friction note on why `bill_id` must be threaded in explicitly.)"""
    tags = [t for t in (bill.get("tags") or ()) if t in GOOSE_TAGS]
    if bill.get("goose_tag") and not tags:
        tags = list(GOOSE_TAGS)
    if not tags:
        return None
    rng = random.Random(f"goose:{bill_id}")
    return GOOSE_PRICE_LIST[rng.choice(sorted(tags))]
