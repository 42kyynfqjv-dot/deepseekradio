"""Statehouse docket — bill lifecycle engine (design freeze,
`docs/designs/statehouse-mirror.md` §2/§3, deltas in
`docs/designs/statehouse-final.md`). Leaf module: pure functions over the
frozen `docket-ga{n}.json` shape, stdlib-only, no imports of
`season.py`/`orchestrator.py`/`src/league/*`, and no imports of sibling
`src/statehouse/*` modules ("zero interdependency beyond §2 schemas" —
mirror §10). `members`/`cal` are consumed here only as the plain dicts the
frozen sidecars describe.

Stage enum (mirror §2, restated verbatim — `src/statehouse/civicguard.py`'s
`STAGE_WORDS` already committed to these exact literal names, so this module
matches them rather than inventing new ones):
    INTRODUCED -> IN_COMMITTEE -> REPORTED -> CALENDARED -> PASSED_ORIGIN ->
    IN_SECOND -> REPORTED_2 -> PASSED_BOTH -> CONFERENCE -> ENROLLED ->
    SIGNED | VETOED | OVERRIDDEN | LAW_NO_SIG
Terminal deaths: DIED_IN_COMMITTEE, CROSSOVER_BARRED, FAILED_FLOOR, POCKET.
MERGED is terminal-but-NOT-dead (final.md delta, "Committee on Merging:
never advances, never dies" — canon as a state machine): `is_terminal`
returns True for it, `is_dead` returns False.

FRICTION NOTES (frozen contract, conformed to as given):
  1. Mirror §3's module table splits the pipeline: docket.py owns
     INTRODUCED..REPORTED (+ the crossover-bar sweep, Merging referrals, OIC
     deficiency notices); a sibling `floor.py`/`votes.py` owns CALENDARED..
     governor action. This task's own brief, however, hands docket.py the
     *full* stage enum through enacted/vetoed/MERGED and asks this module's
     test file to calibrate "<5% floor failure" — a number that can't be
     tested anywhere if floor resolution exists nowhere reachable from here.
     A sibling `src/statehouse/votes.py` already exists in this repo
     (independently built, also a self-contained leaf module — it duplicates
     rather than imports member/bill mechanics, same discipline as this
     module) and implements the *real* whip_count/floor_result math off
     member zipper/party leans. Per "zero interdependency," this module does
     not import it. Instead: (a) this module populates the `axis`, `tags`,
     and `class` fields votes.py's own docstring says it expects docket.py
     to populate ("docket.py — is expected to populate them") on every bill
     it mints, so the two modules' output/input shapes already agree; (b) a
     small self-contained stand-in, `floor_and_beyond_day`, advances
     CALENDARED bills through governor action using its own tuned hazards
     (never votes.py's), so this component's own calibration target is
     testable today. `floor_and_beyond_day` is explicitly a stand-in to be
     retired in favor of real `votes.floor_result` calls once the
     integration facade (civics.py) wires the two leaf modules together.
  2. The mirror's own `introduce_day` comment sketches "0-3 new bills"/day;
     hit literally, 3 weeks of clustering tops out at ~54 bills, well under
     the §11 target band (Regular 130-190 / Budget 45-80). This module
     widens the peak-window draw (0-6/day) and keeps a lower-rate trickle
     from the end of clustering to the crossover deadline (delta 3: bills
     "concentrate" in the first ~3 weeks, not "only" appear there) to land
     inside the real volume band; the *shape* (front-loaded, hard crossover
     cutoff, rare seeded post-crossover leadership exception) matches the
     delta exactly.
"""
from __future__ import annotations

import random
from datetime import date as _date, timedelta as _timedelta

# ---------------------------------------------------------------- stage enum

STAGE_ORDER = (
    "INTRODUCED", "IN_COMMITTEE", "REPORTED", "CALENDARED", "PASSED_ORIGIN",
    "IN_SECOND", "REPORTED_2", "PASSED_BOTH", "CONFERENCE", "ENROLLED",
)
ENACTED_STAGES = frozenset({"SIGNED", "OVERRIDDEN", "LAW_NO_SIG"})
DEAD_STAGES = frozenset({
    "DIED_IN_COMMITTEE", "CROSSOVER_BARRED", "FAILED_FLOOR", "POCKET", "VETOED",
})
MERGED_STAGE = "MERGED"
TERMINAL_STAGES = ENACTED_STAGES | DEAD_STAGES | {MERGED_STAGE}
ALL_STAGES = frozenset(STAGE_ORDER) | TERMINAL_STAGES


def is_terminal(stage: str) -> bool:
    """True once a bill will never move again — enacted, dead, or MERGED."""
    return stage in TERMINAL_STAGES


def is_dead(stage: str) -> bool:
    """MERGED is terminal but NOT dead (final.md delta: the Committee on
    Merging never advances a bill and never kills it either)."""
    return stage in DEAD_STAGES


def is_enacted(stage: str) -> bool:
    return stage in ENACTED_STAGES


# Restated verbatim from `civicguard.STAGE_WORDS`/`sheets.py` (leaf modules
# restate shared vocabulary rather than cross-import — the precedent
# `calendar.py` already sets for the Wed/Sat constant) so this module's own
# `stage_verbs()` can never contradict the guard vocabulary already shipped.
_STAGE_WORDS = {
    "INTRODUCED": "introduced",
    "IN_COMMITTEE": "in committee",
    "REPORTED": "reported out of committee",
    "CALENDARED": "calendared for floor action",
    "PASSED_ORIGIN": "passed its chamber of origin",
    "IN_SECOND": "in its second chamber",
    "REPORTED_2": "reported out of committee in its second chamber",
    "PASSED_BOTH": "passed both chambers",
    "CONFERENCE": "in conference committee",
    "ENROLLED": "enrolled, awaiting the Governor",
    "SIGNED": "signed into law",
    "VETOED": "vetoed",
    "OVERRIDDEN": "enacted over a veto",
    "LAW_NO_SIG": "law without the Governor's signature",
    "DIED_IN_COMMITTEE": "died in committee",
    "MERGED": "referred to the Committee on Merging",
    "CROSSOVER_BARRED": "barred at the crossover deadline",
    "FAILED_FLOOR": "failed on the floor",
    "POCKET": "died by pocket veto",
}
_STAGE_SYNONYMS = {
    "IN_COMMITTEE": ["awaiting a hearing", "referred to committee"],
    "REPORTED": ["cleared committee", "ordered to the calendar"],
    "CALENDARED": ["placed on the calendar"],
    "MERGED": ["still pending in Merging", "in Merging, permanently"],
    "DIED_IN_COMMITTEE": ["never came out of committee"],
}


def stage_verbs(stage: str) -> list[str]:
    """Guard vocabulary for `stage`: the canonical phrase first (matching
    `civicguard.STAGE_WORDS` exactly), then any narratable synonyms."""
    if stage not in _STAGE_WORDS:
        return []
    return [_STAGE_WORDS[stage], *_STAGE_SYNONYMS.get(stage, [])]


# --------------------------------------------------------------- committees

# Canon-toned standing-committee bank (civics-grounding.md A.3 jurisdictions,
# Wending-flavored names). "merging" is a REFERRAL FATE, never an original
# intro assignment (a bill only lands there via the MERGED committee-day
# outcome, re-referred from its real committee — mirror §2's own SB-3
# example: `committee` flips to "merging" via a logged REFERRED event, it is
# never a bill's first assignment).
COMMITTEES = {
    "roads": "Roads, Holes & Adjacent Depressions",
    "merging": "Committee on Merging",
    "judiciary": "Judiciary",
    "finance": "Ways, Means & Overdue Invoices",
    "education": "Education & Enrichment",
    "health": "Health, Human Services & Waiting Rooms",
    "natural": "Natural Resources & the Pharmacy Lot",
    "govops": "Government Operations & Paperwork",
    "transport": "Transportation & the Roundabout",
    "agriculture": "Agriculture & Goose Considerations",
    "commerce": "Commerce & Corporations",
    "local": "Local Government",
}
_REFERRABLE = tuple(k for k in COMMITTEES if k != "merging")

# Goose-tag affinity (final.md delta 4: "lot paving, waterfowl, oaths") —
# which substantive committees can plausibly produce a goose-relevant bill.
_GOOSE_AFFINITY = {
    "roads": "lot_paving", "transport": "lot_paving",
    "natural": "waterfowl", "agriculture": "waterfowl",
    "judiciary": "oaths", "govops": "oaths",
}
_P_GOOSE_TAG = 0.05

_TITLE_BANK = {
    "roads": [
        "An Act Relating to the Numbering of Potholes Prior to Repair",
        "An Act Concerning the Depth Classification of Roadway Depressions",
        "An Act to Establish a Study Committee on the Roundabout's Ninth Year",
        "An Act Relating to Snowplow Right-of-Way at Mile Zero",
    ],
    "merging": [
        "An Act Establishing a Committee to Name the Candidate",
        "An Act Concerning the Merger of Adjacent Traffic Lanes",
    ],
    "judiciary": [
        "An Act Relating to the Admissibility of Laminated Documents",
        "An Act Concerning Oaths Sworn Upon Incomplete Plans",
        "An Act to Clarify the Statute of Limitations on Filed-in-Error Forms",
    ],
    "finance": [
        "An Act Relating to the Overdue Invoice Amnesty Program",
        "An Act Concerning the Fiscal Note on Fiscal Notes",
        "An Act to Appropriate Funds for a Ninth Chair Nobody Trusts",
    ],
    "education": [
        "An Act Relating to Field Trips to the Half-Dome Rotunda",
        "An Act Concerning Civics Curriculum on Provisional Statehood",
    ],
    "health": [
        "An Act Relating to Waiting Room Seating Standards",
        "An Act Concerning the Licensing of Bread-Adjacent Remedies",
    ],
    "natural": [
        "An Act Relating to the Pharmacy Lot Drainage Easement",
        "An Act Concerning Waterfowl Crossing Signage Statewide",
        "An Act to Designate the Goose a Protected Civic Institution",
    ],
    "govops": [
        "An Act Relating to Ink Color on Filed Statehood Forms",
        "An Act Concerning the Committee on Merging's Own Bylaws",
        "An Act to Require Oaths Be Sworn Away From the Pharmacy Lot",
    ],
    "transport": [
        "An Act Relating to the Roundabout Completion Timeline",
        "An Act Concerning Lane Merge Signage at Mile Zero",
    ],
    "agriculture": [
        "An Act Relating to the Candidate's Grazing Rights",
        "An Act Concerning Fruit Basket Distribution as a Civic Instrument",
    ],
    "commerce": [
        "An Act Relating to Ladder Rental Licensing Disputes",
        "An Act Concerning the Provisional Party U-Haul's Parking Status",
    ],
    "local": [
        "An Act Relating to Window 4's Posted Hours",
        "An Act Concerning Fixture 12's Maintenance Ticket",
    ],
}


def bill_title(rng: random.Random, committee: str) -> str:
    """A canon-toned, G/PG title for a bill referred to `committee`."""
    bank = _TITLE_BANK.get(committee) or _TITLE_BANK["local"]
    return rng.choice(bank)


# --------------------------------------------------------------- helpers

_WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _weekday_name(date: str) -> str:
    return _WEEKDAY_NAMES[_date.fromisoformat(date).weekday()]


def _is_committee_day(cal: dict, date: str) -> bool:
    return _weekday_name(date) in cal.get("committee_days", ("Mon", "Wed", "Fri"))


def _active_session(cal: dict, date: str) -> dict | None:
    """The `cal["sessions"]` entry covering `date`, or None (interim/quiet).
    A session lacking an explicit end (GA 1's permanently-pending sine die)
    is treated as open-ended from its `start`."""
    for s in cal.get("sessions", []):
        if date < s.get("start", ""):
            continue
        if date <= s.get("sine_die", "9999-12-31") or s.get("sine_die_pending"):
            return s
    return None


def _sponsor_counts(dk: dict) -> dict:
    counts: dict = {}
    for b in dk["bills"].values():
        counts[b["sponsor"]] = counts.get(b["sponsor"], 0) + 1
    return counts


def _member_pool(members: dict, chamber: str) -> list:
    pool = sorted(mid for mid, m in (members or {}).get("members", {}).items()
                  if m.get("chamber") == chamber)
    if pool:
        return pool
    # self-healing fallback: a caller testing docket.py in isolation, with no
    # real members sidecar, still gets a usable synthetic sponsor pool.
    prefix = "H" if chamber == "house" else "S"
    hi = 51 if chamber == "house" else 9
    return [f"{prefix}-{i:02d}" for i in range(1, hi + 1)]


def _pick_sponsor(dk: dict, members: dict, chamber: str, rng: random.Random,
                   cap: int) -> str:
    pool = _member_pool(members, chamber)
    counts = _sponsor_counts(dk)
    under_cap = [mid for mid in pool if counts.get(mid, 0) < cap]
    return rng.choice(under_cap or pool)


def empty_docket(ga: int) -> dict:
    """A fresh, empty `docket-ga{n}.json` body (mirror §2 schema) — a small
    convenience constructor for callers/tests wiring up a new Assembly."""
    return {"schema": 1, "ga": ga, "next_no": {"H": 1, "S": 1}, "bills": {}}


# ------------------------------------------------------------ introduction

_SPONSOR_CAP = 4          # grounding A.7's WY-style cap knob
_CLUSTER_DAYS = 21        # "the first ~3 weeks of a session" (delta 3)
_LATE_EXCEPTION_P = 0.02
# A bill introduced with only a handful of committee days left before
# crossover is doomed from birth (near-certain CROSSOVER_BARRED) — that is
# not what the "55-70% die in committee" grounding number is modeling
# (mostly no-hearing/no-report inaction), so the ORGANIC intro window closes
# this many days before crossover; anything closer to the deadline (through
# crossover itself) is exception-only, same rare seeded leadership-exception
# path (delta 3: "late introductions only by leadership exception").
_LATE_WINDOW_DAYS = 18            # Regular Session (crossover ~day 67)
_LATE_WINDOW_DAYS_BUDGET = 6      # Budget Session's crossover is only ~day 30
_HI_PEAK_REGULAR, _HI_TRICKLE_REGULAR = 11, 5
_HI_PEAK_BUDGET, _HI_TRICKLE_BUDGET = 9, 5


def introduce_day(dk: dict, members: dict, cal: dict, ga: int,
                   date: str) -> list[dict]:
    """New bills filed on `date` (mirror §3 signature). Clusters in the
    first ~3 weeks of session with a hard crossover-deadline cutoff; late
    introductions in the exception window (see `_LATE_WINDOW_DAYS`) or past
    crossover only via a rare seeded leadership exception (delta 3).
    Mutates `dk` in place (inserts bills, advances `next_no`) and returns
    the list of newly introduced bill dicts. No-op outside any active
    session window or on a quiet Sunday."""
    if _date.fromisoformat(date).weekday() == 6:      # Sunday: quiet, always
        return []
    sess = _active_session(cal, date)
    if sess is None:
        return []
    start, crossover = sess["start"], sess.get("crossover", "9999-12-31")
    is_budget = sess.get("kind") == "budget"
    rng = random.Random(f"intro:{ga}:{date}")

    late_days = _LATE_WINDOW_DAYS_BUDGET if is_budget else _LATE_WINDOW_DAYS
    late_window_start = (_date.fromisoformat(crossover) -
                          _timedelta(days=late_days)).isoformat()
    if date >= late_window_start:
        if rng.random() >= _LATE_EXCEPTION_P:
            return []
        n = 1
    else:
        day_idx = (_date.fromisoformat(date) - _date.fromisoformat(start)).days
        if is_budget:
            hi = _HI_PEAK_BUDGET if day_idx < 10 else _HI_TRICKLE_BUDGET
        else:
            hi = _HI_PEAK_REGULAR if day_idx < _CLUSTER_DAYS else _HI_TRICKLE_REGULAR
        n = rng.randint(0, hi)

    house_pool = _member_pool(members, "house")
    senate_pool = _member_pool(members, "senate")
    new_bills = []
    for _ in range(n):
        # weighted by chamber size (51:9), not a flat coin flip — otherwise
        # the 9-seat Senate would file as many bills as the 51-seat House
        # and blow through the per-sponsor cap almost immediately.
        chamber = rng.choices(["house", "senate"],
                               weights=[len(house_pool), len(senate_pool)])[0]
        prefix = "H" if chamber == "house" else "S"
        no = dk["next_no"][prefix]
        dk["next_no"][prefix] = no + 1
        bill_id = f"{prefix}B-{no}"

        sponsor = _pick_sponsor(dk, members, chamber, rng, _SPONSOR_CAP)
        pool = _member_pool(members, chamber)
        co_pool = [m for m in pool if m != sponsor]
        n_co = rng.choice([0, 0, 0, 1, 1, 2])
        cosponsors = sorted(rng.sample(co_pool, min(n_co, len(co_pool)))) \
            if co_pool else []

        committee = rng.choice(_REFERRABLE)
        title = bill_title(random.Random(f"title:{ga}:{bill_id}"), committee)
        marquee = round(random.Random(f"marquee:{ga}:{bill_id}").random(), 3)
        axis = round(random.Random(f"axis:{ga}:{bill_id}").random(), 3)

        tags: list[str] = []
        goose_tag = _GOOSE_AFFINITY.get(committee)
        if goose_tag and rng.random() < _P_GOOSE_TAG:
            tags = [goose_tag]

        dk["bills"][bill_id] = {
            "title": title, "sponsor": sponsor, "cosponsors": cosponsors,
            "committee": committee, "stage": "IN_COMMITTEE",
            "intro": date, "marquee": marquee,
            "history": [[date, "INTRODUCED"]],
            "deficiency": None,
            # additive fields votes.py's own docstring says docket.py is
            # expected to populate (see module FRICTION NOTES #1):
            "axis": axis, "tags": tags, "class": "ordinary",
        }
        new_bills.append(dk["bills"][bill_id])
    return new_bills


# --------------------------------------------------------------- committee

_P_HEARING = 0.35
_P_RESOLVE = 0.16         # per committee-day chance an IN_COMMITTEE bill resolves
_W_REPORT, _W_DIE, _W_MERGE = 0.42, 0.38, 0.20   # sums to 1.0
_OIC_RATE = 0.06          # final.md delta: OIC flags ~6% of active bills


def committee_day(dk: dict, members: dict, cal: dict, ga: int, date: str,
                   snowed: bool = False) -> list[dict]:
    """One committee day's hearings/report votes/Merging referrals/OIC
    deficiency notices + the crossover-bar sweep (mirror §3 signature).
    `snowed` never gates committee work ("committees meet in the basement",
    mirror §4.2 — quorum/snow only ever blocks the *floor*) so it is
    accepted for signature parity and unused. No-op on a non-committee day
    (self-healing: safe to call on any date). Per-bill draws are seeded
    `Random(f"bill:{ga}:{bill_id}:{date}")` — order-independent across bills
    and replayable forever from nothing but (ga, bill_id, date)."""
    del snowed
    if not _is_committee_day(cal, date):
        return []
    sess = _active_session(cal, date)
    crossover = sess.get("crossover") if sess else None

    events = []
    for bid in sorted(dk["bills"]):
        bill = dk["bills"][bid]
        if bill["intro"] > date or bill["stage"] != "IN_COMMITTEE":
            continue
        rng = random.Random(f"bill:{ga}:{bid}:{date}")
        changed = False

        defc = bill.get("deficiency")
        if defc and date < defc.get("until", ""):
            continue                          # frozen by an open notice
        if defc and date >= defc.get("until", ""):
            bill["deficiency"] = None

        if crossover and date >= crossover:
            bill["stage"] = "CROSSOVER_BARRED"
            bill["history"].append([date, "CROSSOVER_BARRED"])
            events.append(bill)
            continue

        if rng.random() < _OIC_RATE:
            hold = rng.randint(3, 10)
            until = (_date.fromisoformat(date) + _timedelta(days=hold)).isoformat()
            bill["deficiency"] = {"since": date, "until": until}
            bill["history"].append([date, "DEFICIENCY", until])
            events.append(bill)
            continue

        if rng.random() < _P_HEARING:
            bill["history"].append([date, "HEARING", bill["committee"]])
            changed = True

        if rng.random() < _P_RESOLVE:
            roll = rng.random()
            if roll < _W_REPORT:
                size = rng.randint(7, 11)
                yea = rng.randint(size // 2 + 1, size)
                nay = size - yea
                bill["stage"] = "REPORTED"
                bill["history"].append(
                    [date, "REPORTED", bill["committee"], [yea, nay]])
            elif roll < _W_REPORT + _W_DIE:
                bill["stage"] = "DIED_IN_COMMITTEE"
                bill["history"].append([date, "DIED_IN_COMMITTEE"])
            else:
                bill["committee"] = "merging"
                bill["stage"] = "MERGED"
                bill["history"].append([date, "REFERRED", "merging"])
            changed = True

        if changed:
            events.append(bill)
    return events


def pick_tracked(dk: dict, ga: int, date: str) -> str | None:
    """The highest-`marquee` unresolved bill introduced on/before `date`, or
    None if every bill has reached a terminal stage (mirror §3 signature;
    the one-thread rule's promotion source)."""
    del ga
    best_id, best_marquee = None, -1.0
    for bid, b in dk["bills"].items():
        if b["intro"] > date or is_terminal(b["stage"]):
            continue
        if b["marquee"] > best_marquee:
            best_id, best_marquee = bid, b["marquee"]
    return best_id


# ------------------------------------------------- floor-and-beyond stand-in

# See module FRICTION NOTES #1: this is a self-contained calibration
# stand-in, not mirror §3's real floor.py/votes.py (which already exists as
# a sibling and should replace this once the integration facade lands).
_P_FLOOR_FAIL = 0.02      # target: <5% of bills reaching third reading
_P_FAIL_2ND = 0.02
_P_CONFERENCE = 0.06      # target: conference on <10% of enacted bills
_P_VETO = 0.04            # target: veto <5% of transmitted bills
_P_LAW_NO_SIG = 0.03
_P_OVERRIDE_ATTEMPT = 0.5
_P_OVERRIDE_SUCCESS = 0.15  # target: override succeeds <20% of attempts


def _present_count(members: dict, chamber: str, ga: int, date: str) -> int:
    roster = {mid: m for mid, m in (members or {}).get("members", {}).items()
              if m.get("chamber") == chamber}
    if not roster:
        size = 51 if chamber == "house" else 9
        return max(int(size * 0.93), size // 2 + 1)
    present = 0
    for mid, m in roster.items():
        attend = m.get("attend", 0.93)
        if random.Random(f"attend:{ga}:{date}:{mid}").random() < attend:
            present += 1
    return present


def floor_and_beyond_day(dk: dict, members: dict, ga: int, date: str,
                          floor_open: bool = True) -> list[dict]:
    """FRICTION STAND-IN (see module docstring #1): advances CALENDARED..
    governor-action bills so the full lifecycle and the <5%-floor-failure
    calibration target are testable from this component alone.
    `floor_open=False` (hockey adjournment, snow, non-floor day) withholds
    floor-vote resolution for the day; the governor/conference clock is not
    a floor vote and keeps running regardless."""
    events = []
    for bid in sorted(dk["bills"]):
        bill = dk["bills"][bid]
        stage = bill["stage"]
        if is_terminal(stage) or stage in ("INTRODUCED", "IN_COMMITTEE"):
            continue
        rng = random.Random(f"floor:{ga}:{bid}:{date}")
        origin = "house" if bid.startswith("H") else "senate"
        second = "senate" if origin == "house" else "house"
        changed = False

        if stage == "REPORTED" and floor_open:
            bill["stage"] = "CALENDARED"
            bill["history"].append([date, "CALENDARED"])
            changed = True

        elif stage == "CALENDARED" and floor_open:
            present = max(_present_count(members, origin, ga, date), 1)
            if rng.random() < _P_FLOOR_FAIL:
                yea = present // 2
            else:
                yea = present // 2 + 1
            yea = min(yea, present)
            nay = present - yea
            if yea > nay:
                bill["stage"] = "PASSED_ORIGIN"
                bill["history"].append([date, "PASSED_ORIGIN", [yea, nay]])
            else:
                bill["stage"] = "FAILED_FLOOR"
                bill["history"].append([date, "FAILED_FLOOR", [yea, nay]])
            changed = True

        elif stage == "PASSED_ORIGIN":
            bill["stage"] = "IN_SECOND"
            bill["history"].append([date, "CROSSED"])
            changed = True

        elif stage == "IN_SECOND" and floor_open and rng.random() < 0.4:
            present = max(_present_count(members, second, ga, date), 1)
            if rng.random() < _P_FAIL_2ND:
                yea = present // 2
            else:
                yea = present // 2 + 1
            yea = min(yea, present)
            nay = present - yea
            if yea > nay:
                bill["stage"] = "REPORTED_2"
                bill["history"].append([date, "REPORTED_2", [yea, nay]])
            else:
                bill["stage"] = "FAILED_FLOOR"
                bill["history"].append([date, "FAILED_FLOOR", [yea, nay]])
            changed = True

        elif stage == "REPORTED_2" and floor_open:
            if rng.random() < _P_CONFERENCE:
                bill["stage"] = "CONFERENCE"
                bill["history"].append([date, "CONFERENCE"])
            else:
                bill["stage"] = "PASSED_BOTH"
                bill["history"].append([date, "PASSED_BOTH"])
            changed = True

        elif stage == "CONFERENCE" and rng.random() < 0.4:
            bill["stage"] = "PASSED_BOTH"
            bill["history"].append([date, "PASSED_BOTH"])
            changed = True

        elif stage == "PASSED_BOTH":
            bill["stage"] = "ENROLLED"
            bill["history"].append([date, "ENROLLED"])
            changed = True

        elif stage == "ENROLLED" and rng.random() < 0.6:
            roll = rng.random()
            if roll < _P_VETO:
                if (rng.random() < _P_OVERRIDE_ATTEMPT
                        and rng.random() < _P_OVERRIDE_SUCCESS):
                    bill["stage"] = "OVERRIDDEN"
                    bill["history"].append([date, "VETOED"])
                    bill["history"].append([date, "OVERRIDDEN"])
                else:
                    bill["stage"] = "VETOED"
                    bill["history"].append([date, "VETOED"])
            elif roll < _P_VETO + _P_LAW_NO_SIG:
                bill["stage"] = "LAW_NO_SIG"
                bill["history"].append([date, "LAW_NO_SIG"])
            else:
                bill["stage"] = "SIGNED"
                bill["history"].append([date, "SIGNED"])
            changed = True

        if changed:
            events.append(bill)
    return events
