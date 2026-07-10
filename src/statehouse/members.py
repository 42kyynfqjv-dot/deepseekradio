"""Statehouse members — mint the 60-seat General Assembly (design freeze,
`docs/designs/statehouse-mirror.md` §2/§3, deltas in
`docs/designs/statehouse-final.md`). Leaf module: pure functions over the
frozen `members-ga{n}.json` shape, stdlib-only, no imports of
`season.py`/`orchestrator.py`/`src/league/*` and no imports of sibling
`src/statehouse/*` modules.

Schema (mirror §2, adopted verbatim plus the delta-1 `attend` scalar and an
additive `discipline` scalar — see friction #2):
    {"schema": 1, "ga": n,
     "members": {"H-03": {"name","chamber","district","party",
                           "zipper","maverick","discipline","attend",
                           "tenure","aired"}, ...},
     "officials": {"governor","clerk","potholes","roundabout": {"name","canon"},
                   "speaker","protem": "<seat-id>",
                   "tenth_chair": {"name": null, "trusted": false}},
     "leaders": {"house": {party: seat-id, ...}, "senate": {...}}}

The closed 7-party canon (`station/wending-bible.md`): six seat-holding
parties plus the seatless Office of Interparty Compliance ("oic", acts via
Notices of Deficiency elsewhere — never minted a member here). The seat
table below is the mirror doc's own worked example, adopted verbatim per
final.md's "Adopted verbatim from statehouse-mirror.md" list (the closed
7-party seat table summing exactly to 51 House / 9 Senate).

FRICTION NOTES (schema/assignment frozen, conforming as written):
  1. `seat_new_assembly` is listed under `election.py` in mirror §3's module
     table, but this task's own component assignment places it in
     `members.py` (closely tied to `mint_assembly`'s `carryover` parameter,
     which is also this module's). Implemented here as assigned; election.py
     (a sibling component) is expected to call it, not duplicate it.
  2. The task's frozen contract for this component asks for "discipline/
     maverick scalars", but mirror §2's own worked JSON example shows only
     `zipper`/`maverick` (no `discipline`). Mirror §3's `member_vote` prose
     ("party_line + zipper alignment + maverick draw") also has no separate
     discipline term. Implemented as an ADDITIVE per-member field (never
     contradicts the frozen shape, just extends it) so `member_vote` has a
     tunable party-adherence knob — needed to hit build-order row B's own
     calibration target ("party-line adherence 78-92%") without which that
     number has no free parameter to calibrate against.
  3. "District names from Halfway canon": the bible's Halfway registry names
     PLACES (the Half-Dome, Mile Zero, the pharmacy lot, Window 4...), not a
     named-district gazetteer, and neither adopted design (`mirror`/`civic`)
     ever names a district — both use plain integers (mirror's own example:
     `"H-03"` -> `district: 3`; `"S-07"` -> `district: 107`). Implemented
     districts as that exact locked numbering convention (house: 1-51,
     identity with the seat's own numeral; senate: 101-109, the seat number
     +100 -- "nine good chairs" get the second-hundred block) rather than
     inventing a separate landmark-name registry canon never specified.
  4. Component rules bar importing `season.py`/`orchestrator.py`/league
     modules; `livegame.py` is technically none of those, and mirror §2
     explicitly says "shared name bank" -- but this task's own component
     line is more specific: "shared style ... but NO collisions with league
     players/officials". Reusing `livegame.FIRST_NAMES`/`LAST_NAMES`
     verbatim (as `src/league/players.py` already does for the hockey
     roster, straight from those exact tuples) only makes a collision
     *unlikely*, not impossible, since the two pools would draw from the
     identical 900-name space. Implemented a same-style, token-disjoint bank
     local to this module (the exact precedent `src/league/economy.py`
     already sets for its own coach/draftee names, friction #4 there) so a
     collision with any currently- or future-minted hockey player, coach, or
     pinned official is impossible by construction, not by odds. Verified in
     the test file: `MEMBER_FIRST`/`MEMBER_LAST` are asserted disjoint from
     `livegame.FIRST_NAMES`/`LAST_NAMES` and from the four pinned officials.
"""
from __future__ import annotations

import random

# --------------------------------------------------------------- the canon

PARTIES = ("prov", "round", "vang", "barb", "grudge", "goose")
PARTY_NAMES = {
    "prov": "The Provisional Party",
    "round": "The Roundabout Party",
    "vang": "The Zipper Merge Vanguard",
    "barb": "The Committee to Formally Address What Barbara Said in 1987",
    "grudge": "The Grudge Preservation Society",
    "goose": "The Goose Party",
    "oic": "The Office of Interparty Compliance",
}

# The closed 7-party seat table (mirror §2's worked example, adopted
# verbatim): 6 seat-holding parties; OIC is seatless (fields no candidates).
DEFAULT_SEATS = {
    "house": {"prov": 14, "round": 9, "vang": 11, "barb": 7, "grudge": 6,
              "goose": 4},
    "senate": {"prov": 3, "vang": 2, "round": 2, "barb": 1, "grudge": 1},
}
HOUSE_SEATS = sum(DEFAULT_SEATS["house"].values())     # 51
SENATE_SEATS = sum(DEFAULT_SEATS["senate"].values())   # 9

# Party-line consumption order for seat->party assignment, taken verbatim
# from the order each seat table is written in mirror §2's own JSON.
HOUSE_PARTY_ORDER = ("prov", "round", "vang", "barb", "grudge", "goose")
SENATE_PARTY_ORDER = ("prov", "vang", "round", "barb", "grudge")

# Party zipper priors (mirror §2 prose): mean position on the Zipper axis
# (0 = merge early, 1 = zipper at the cone). "round" has no fixed line --
# "round uniform (they circle)" -- each member draws their own uniformly.
# "goose" is off-axis entirely; its members carry zipper=None.
ZIP_MU = {"prov": 0.25, "vang": 0.88, "grudge": 0.70, "barb": 0.50}
ZIP_SIGMA = 0.14

# The Goose bloc's enumerable price list (delta 4): a bill only draws a
# goose vote when it carries one of these tags; otherwise the bloc abstains
# (never invented -- civicguard, a sibling component, can verify any claimed
# deal against this exact table).
GOOSE_PRICES = {
    "lot_paving": "repave the pharmacy lot",
    "waterfowl": "a resolution recognizing the Candidate's tenure",
    "oaths": "let the Candidate's designee touch the roundabout plans",
}
GOOSE_DEAL_P = 0.80   # once priced, the deal actually lands this often

# The four canon officials, pinned verbatim from `station/wending-bible.md` /
# `web/government.html` -- never minted, never varied.
CANON_OFFICIALS = {
    "governor": {"name": "Marty Bouchard", "canon": True},
    "clerk": {"name": "Gord Pelletier", "canon": True},
    "potholes": {"name": "Bert Demers", "canon": True},
    "roundabout": {"name": "Toivo Ostberg", "canon": True},
}
# "nine good chairs and a tenth no one trusts" -- flavor seat, never filled,
# never counted toward the 9 real Senate seats.
TENTH_CHAIR = {"name": None, "trusted": False}

# --- the member name bank (friction #4): same style as livegame's, but a
# disjoint token set so a collision with a hockey player/coach/official is
# impossible by construction, never merely improbable.
MEMBER_FIRST = ("Ansel Bev Corrine Deloris Emile Franny Gaston Hedy Ivo "
                "Jocelyn Knute Lorne Mireille Neil Odette Percy Quentin "
                "Rosaire Sigrid Terrence Ulla Vern Wanda Xavier Yolande "
                "Zeke Adele Basil Cosmo Dagny").split()
MEMBER_LAST = ("Beaulieu Charbonneau Dagenais Eriksson Falk Girouard "
               "Hjalmar Isaksen Janvier Lindgren Moreau Nadeau Ouimet "
               "Provencher Renkonen Solheim Trepanier Uusitalo Villeneuve "
               "Wojcik Ackerman Beauregard Chagnon Desrosiers Ekholm Frigon "
               "Gauvreau Hebert Imbeault Jodoin").split()


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _assert_seats(seats: dict) -> None:
    house, senate = seats.get("house", {}), seats.get("senate", {})
    if set(house) - set(PARTIES) or set(senate) - set(PARTIES):
        raise ValueError("seat table names a party outside the closed 7")
    if "oic" in house or "oic" in senate:
        raise ValueError("OIC is seatless by canon -- it may never hold a seat")
    if sum(house.values()) != HOUSE_SEATS:
        raise ValueError(f"house seats sum {sum(house.values())} != {HOUSE_SEATS}")
    if sum(senate.values()) != SENATE_SEATS:
        raise ValueError(f"senate seats sum {sum(senate.values())} != {SENATE_SEATS}")


def seat_table(body: dict) -> dict:
    """Recompute the {house,senate: {party: n}} aggregate from a minted
    members-file body -- the mirror-doc invariant ("seat counts are
    aggregates of the members sidecar, recomputed and asserted at every
    save"). Pure; does not touch `body`."""
    out = {"house": {}, "senate": {}}
    for m in body["members"].values():
        chamber, party = m["chamber"], m["party"]
        out[chamber][party] = out[chamber].get(party, 0) + 1
    return out


# ------------------------------------------------------------------ minting

def _draw_zipper(rng: random.Random, party: str) -> float | None:
    if party == "goose":
        return None
    if party == "round":
        return round(rng.uniform(0.0, 1.0), 3)
    return round(_clamp01(rng.gauss(ZIP_MU[party], ZIP_SIGMA)), 3)


def _mint_name(rng: random.Random, used: set) -> str:
    while True:
        name = f"{rng.choice(MEMBER_FIRST)} {rng.choice(MEMBER_LAST)}"
        if name not in used:
            used.add(name)
            return name


def _mint_member(rng: random.Random, used_names: set, party: str,
                  chamber: str, district: int) -> dict:
    return {
        "name": _mint_name(rng, used_names),
        "chamber": chamber,
        "district": district,
        "party": party,
        "zipper": _draw_zipper(rng, party),
        "maverick": round(rng.uniform(0.03, 0.20), 3),
        "discipline": round(rng.uniform(0.55, 0.92), 3),
        "attend": round(rng.uniform(0.88, 0.98), 3),          # delta 1
        "tenure": rng.randint(1, 8),
        "aired": False,
    }


def _carry_member(prev: dict, rng: random.Random, party: str, chamber: str,
                   district: int) -> dict:
    """A re-elected incumbent seated fresh: identity (name, tenure) and
    disposition (zipper/maverick/discipline) persist; only the seat
    bookkeeping (chamber/district/party/aired) is refreshed for the new
    Assembly (party can change if `seat_new_assembly` recorded a party
    switch on re-election)."""
    m = {
        "name": prev["name"],
        "chamber": chamber,
        "district": district,
        "party": party,
        "zipper": prev.get("zipper") if party != "goose" else None,
        "maverick": prev.get("maverick", round(rng.uniform(0.03, 0.20), 3)),
        "discipline": prev.get("discipline", round(rng.uniform(0.55, 0.92), 3)),
        "attend": round(rng.uniform(0.88, 0.98), 3),           # re-rolled per GA
        "tenure": prev.get("tenure", 0) + 1,
        "aired": False,
    }
    if party == "round" and prev.get("zipper") is None:
        m["zipper"] = round(rng.uniform(0.0, 1.0), 3)
    if party != "goose" and m["zipper"] is None:
        m["zipper"] = _draw_zipper(rng, party)
    return m


def _mint_chamber(chamber: str, party_counts: dict, party_order: tuple,
                   ga: int, carry_by_party: dict, used_names: set) -> dict:
    prefix = "H" if chamber == "house" else "S"
    n = sum(party_counts.values())
    ids = [f"{prefix}-{i:02d}" for i in range(1, n + 1)]

    # Deterministic per-GA shuffle: which seat slot (and therefore which
    # district number) falls to which party this Assembly.
    shuffle_rng = random.Random(f"seats:{chamber}:{ga}")
    shuffled = list(ids)
    shuffle_rng.shuffle(shuffled)

    result: dict = {}
    idx = 0
    for party in party_order:
        cnt = party_counts.get(party, 0)
        candidates = carry_by_party.get(party, [])
        for i in range(cnt):
            sid = shuffled[idx]
            idx += 1
            num = int(sid.split("-")[1])
            district = num if chamber == "house" else 100 + num
            member_rng = random.Random(f"member:{ga}:{sid}")
            if i < len(candidates):
                result[sid] = _carry_member(candidates[i], member_rng, party,
                                             chamber, district)
                used_names.add(result[sid]["name"])
            else:
                result[sid] = _mint_member(member_rng, used_names, party,
                                            chamber, district)
    return result


def _pick_leader(members: dict, ids: list) -> str:
    """Deterministic tie-break: highest tenure, then lowest seat id."""
    return sorted(ids, key=lambda sid: (-members[sid]["tenure"], sid))[0]


def _build_leaders(members: dict) -> dict:
    leaders: dict = {"house": {}, "senate": {}}
    for chamber in ("house", "senate"):
        by_party: dict = {}
        for sid, m in members.items():
            if m["chamber"] == chamber:
                by_party.setdefault(m["party"], []).append(sid)
        for party, ids in by_party.items():
            leaders[chamber][party] = _pick_leader(members, ids)
    return leaders


def _build_officials(overrides: dict | None, members: dict) -> dict:
    officials = {k: dict(v) for k, v in CANON_OFFICIALS.items()}
    if overrides:
        for k, v in overrides.items():
            if k in officials:
                officials[k] = dict(v)

    house_ids = sorted([sid for sid, m in members.items()
                         if m["chamber"] == "house"])
    senate_ids = sorted([sid for sid, m in members.items()
                          if m["chamber"] == "senate"])
    officials["speaker"] = _pick_leader(members, house_ids)
    officials["protem"] = _pick_leader(members, senate_ids)
    officials["tenth_chair"] = dict(TENTH_CHAIR)
    return officials


def mint_assembly(ga: int, canon: dict | None = None,
                   carryover: dict | None = None) -> dict:
    """Build the whole `members-ga{n}.json` body: 51 House + 9 Senate,
    minted from the closed 7-party seat table (`canon.get("seats")`,
    defaulting to the mirror-doc worked example), canon officials pinned,
    and re-elected incumbents (`carryover`, mirror §6's `seat_new_assembly`
    output) keeping their name/tenure across Assemblies. Deterministic per
    `ga` -- every rng draw is seeded off `ga` and the seat id, so the same
    `(ga, canon, carryover)` always mints byte-identical output."""
    canon = canon or {}
    carryover = carryover or {}
    seats = canon.get("seats", DEFAULT_SEATS)
    _assert_seats(seats)

    used_names: set = {o["name"] for o in CANON_OFFICIALS.values()}
    for c in carryover.values():
        used_names.add(c["name"])

    house_carry: dict = {}
    for sid in sorted(k for k in carryover if k.startswith("H-")):
        house_carry.setdefault(carryover[sid]["party"], []).append(carryover[sid])
    senate_carry: dict = {}
    for sid in sorted(k for k in carryover if k.startswith("S-")):
        senate_carry.setdefault(carryover[sid]["party"], []).append(carryover[sid])

    members: dict = {}
    members.update(_mint_chamber("house", seats["house"], HOUSE_PARTY_ORDER,
                                  ga, house_carry, used_names))
    members.update(_mint_chamber("senate", seats["senate"], SENATE_PARTY_ORDER,
                                  ga, senate_carry, used_names))

    officials = _build_officials(canon.get("officials"), members)
    leaders = _build_leaders(members)

    return {"schema": 1, "ga": ga, "members": members,
            "officials": officials, "leaders": leaders}


# ------------------------------------------------------------------ voting

def party_line(bill: dict, party: str, ga: int) -> float:
    """p(yea) in [0,1] for `party`'s baseline read of `bill`, pure and
    seed-free: how closely the bill's `axis` (0=early-merge flavored,
    1=late-merge flavored; defaults neutral 0.5 if absent) lines up with the
    party's fixed Zipper prior. "round" has no unified line (individual
    zipper decides in `member_vote`); "goose" is off-axis (`goose_price`/
    `member_vote` decide instead). `ga` is accepted for forward-compatibility
    (a future Assembly could drift party priors) but unused today -- no
    grounding target calls for it yet."""
    del ga
    axis = bill.get("axis", 0.5)
    if party in ("round", "goose"):
        return 0.5
    mu = ZIP_MU.get(party)
    if mu is None:
        raise ValueError(f"unknown seat-holding party {party!r}")
    return _clamp01(1.0 - abs(mu - axis))


def goose_price(bill: dict) -> str | None:
    """The Goose bloc's demand if this bill is goose-pivotal, else None --
    a pure enumerable lookup (delta 4), never a random draw. `civicguard`
    can verify any claimed deal against this exact table."""
    for tag in bill.get("tags", ()):
        if tag in GOOSE_PRICES:
            return GOOSE_PRICES[tag]
    return None


def member_vote(m: dict, bill: dict, ga: int) -> bool:
    """PURE and deterministic: seeded `Random(f"vote:{ga}:{bill_id}:{mid}")`
    so it is recomputable forever from member leans + the bill id alone,
    never stored. Goose members resolve via `goose_price` (a seeded draw
    ONLY when the bill is goose-priced, per delta 4 -- callers must not
    invoke this for an un-priced goose member; the correct read there is
    "abstain", which this bool-returning function cannot itself express).
    Everyone else: `party_line` blended with the member's own zipper
    alignment by `discipline`, then a seeded maverick draw that can flip the
    whole read on a given bill -- the "conscience draw" mirror §3 names."""
    bill_id = bill.get("id", bill.get("bill_id", "?"))
    mid = m.get("id") or m.get("name", "?")
    rng = random.Random(f"vote:{ga}:{bill_id}:{mid}")

    if m["party"] == "goose":
        price = goose_price(bill)
        if price is None:
            return False
        return rng.random() < GOOSE_DEAL_P

    axis = bill.get("axis", 0.5)
    p_party = party_line(bill, m["party"], ga)
    p_individual = _clamp01(1.0 - abs((m.get("zipper") or 0.5) - axis))
    discipline = m.get("discipline", 0.75)
    p = p_individual if m["party"] == "round" else (
        discipline * p_party + (1.0 - discipline) * p_individual)

    flip = rng.random() < m.get("maverick", 0.0)
    roll = rng.random()
    p_used = (1.0 - p) if flip else p
    return roll < p_used


# ---------------------------------------------------------------- elections

def seat_new_assembly(el: dict, members: dict) -> dict:
    """Incumbent carryover (mirror §6): from a resolved election body
    (`election-{cycle}.json`'s shape -- `el["races"][seat_id]` with
    `cands`/`final`) and the outgoing Assembly's members-file body, return
    the `carryover` dict `mint_assembly` expects: one entry per seat where
    the WINNING candidate is the sitting incumbent, so they keep their
    name/tenure into the new Assembly. Seats won by a challenger are simply
    absent from the result -- `mint_assembly` mints them fresh. Pure: reads
    both inputs, mutates neither."""
    prev = members.get("members", {})
    carryover: dict = {}
    for sid, race in el.get("races", {}).items():
        cands = race.get("cands", [])
        final = race.get("final", [])
        if not cands or not final:
            continue
        winner = cands[max(range(len(final)), key=lambda i: final[i])]
        incumbent = prev.get(sid)
        if winner.get("inc") and incumbent is not None and \
                incumbent.get("name") == winner.get("name"):
            carryover[sid] = {"name": incumbent["name"],
                               "party": winner.get("party", incumbent["party"]),
                               "zipper": incumbent.get("zipper"),
                               "maverick": incumbent.get("maverick"),
                               "discipline": incumbent.get("discipline"),
                               "tenure": incumbent.get("tenure", 0)}
    return carryover
