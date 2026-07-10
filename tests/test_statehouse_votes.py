"""Statehouse votes fixtures: whip-count/floor-vote invariants, quorum,
passage thresholds (ordinary vs override), Goose-bloc abstention/pricing,
voice/roll split, and determinism.

Run directly (no pytest needed):  python3 tests/test_statehouse_votes.py
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.statehouse import votes

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


# --- synthetic chamber, matching civics.json's canon seat split exactly ----
# house: prov14 round9 vang11 barb7 grudge6 goose4 = 51
# senate: prov3 vang2 round2 barb1 grudge1 = 9

HOUSE_SPLIT = {"prov": 14, "round": 9, "vang": 11, "barb": 7, "grudge": 6, "goose": 4}
SENATE_SPLIT = {"prov": 3, "vang": 2, "round": 2, "barb": 1, "grudge": 1}


def mint_chamber(chamber, split, seed):
    rng = random.Random(seed)
    mu = votes.PARTY_MU
    members = {}
    d = 1
    for party, n in split.items():
        for _ in range(n):
            if party == "goose":
                zipper = None
            elif party == "round":
                zipper = rng.random()
            else:
                zipper = votes._clamp01(mu[party] + rng.uniform(-0.08, 0.08))
            mid = f"{chamber[0].upper()}-{d:02d}"
            members[mid] = {
                "name": f"Member {mid}", "chamber": chamber, "district": d,
                "party": party, "zipper": zipper,
                "maverick": round(rng.uniform(0.03, 0.12), 3),
                "tenure": rng.randint(1, 10), "aired": False,
                "attend": round(rng.uniform(0.88, 0.98), 3),
            }
            d += 1
    return members


def full_assembly(seed=1):
    m = mint_chamber("house", HOUSE_SPLIT, f"{seed}-house")
    m.update(mint_chamber("senate", SENATE_SPLIT, f"{seed}-senate"))
    return m


ORDINARY = {"sponsor": "H-03", "title": "An Act Relating to Roundabout Signage",
            "axis": 0.5}
OVERRIDE_BILL = {"sponsor": "H-03", "title": "An Act Overriding the Veto",
                  "class": "override", "axis": 0.5}
GOOSE_BILL = {"sponsor": "H-14", "title": "An Act Concerning Waterfowl Crossings",
              "tags": ["waterfowl"], "axis": 0.5}
NON_GOOSE_BILL = {"sponsor": "H-14", "title": "An Act on the Merits of Fruit Baskets",
                  "axis": 0.5}

members = full_assembly()

# --- invariant: whip_count buckets sum to chamber size ---------------------
for ga in (1, 2, 3):
    for bill_id, bill, ch, size in (
        ("HB-7", ORDINARY, "house", 51),
        ("SB-3", ORDINARY, "senate", 9),
    ):
        wc = votes.whip_count(bill_id, bill, members, ga, chamber=ch)
        total = wc["yea"] + wc["nay"] + wc["und"] + wc["absent"]
        check(total == size, f"whip_count({bill_id},ga={ga},{ch}) sums to {size} (got {total})")
        check(set(wc) == {"yea", "nay", "und", "absent"}, "whip_count bucket keys exact")

# --- invariant: floor_result buckets sum to chamber size, und always 0 -----
for bill_id in ("HB-7", "HB-8", "HB-9", "SB-1", "SB-2"):
    ch = votes.chamber_of(ORDINARY) if bill_id.startswith("H") else "senate"
    fr = votes.floor_result(bill_id, ORDINARY, members, 1, chamber=ch)
    total = fr["yea"] + fr["nay"] + fr["und"] + fr["absent"]
    check(total == votes.CHAMBER_SIZE[ch], f"floor_result({bill_id}) sums to chamber size")
    check(fr["und"] == 0, f"floor_result({bill_id}) has no undecided bucket")

# --- chamber inference -------------------------------------------------------
check(votes.chamber_of({"sponsor": "H-03"}) == "house", "H- sponsor -> house")
check(votes.chamber_of({"sponsor": "S-07"}) == "senate", "S- sponsor -> senate")
check(votes.chamber_of({}) == "house", "missing sponsor defaults sanely")

# --- passage: ordinary bill, majority of present-and-voting -----------------
# fabricate a lopsided result by hand-rolling a small chamber where every
# member's lean is pinned hard toward yea (axis matches party mu exactly,
# zipper pinned to mu, no maverick noise)
def pinned_chamber(n, party, mu, chamber="house"):
    members = {}
    for i in range(n):
        mid = f"{chamber[0].upper()}-{i:02d}"
        members[mid] = {"name": mid, "chamber": chamber, "district": i,
                         "party": party, "zipper": mu, "maverick": 0.0,
                         "tenure": 1, "aired": False, "attend": 0.99}
    return members

yea_bill = {"sponsor": "H-00", "axis": votes.PARTY_MU["vang"]}
yea_chamber = pinned_chamber(51, "vang", votes.PARTY_MU["vang"])
fr_yes = votes.floor_result("HB-100", yea_bill, yea_chamber, 1, chamber="house")
check(fr_yes["quorum"], "pinned-yea chamber holds quorum")
check(fr_yes["yea"] > fr_yes["nay"], "pinned-yea chamber votes overwhelmingly yea")
check(fr_yes["passed"] is True, "ordinary bill passes on present-and-voting majority")
check(fr_yes["threshold"] == "present-and-voting", "ordinary bill uses present-and-voting")

nay_bill = {"sponsor": "H-00", "axis": votes.PARTY_MU["prov"]}
nay_chamber = pinned_chamber(51, "vang", votes.PARTY_MU["vang"])  # vang loathes a prov-axis bill
fr_no = votes.floor_result("HB-101", nay_bill, nay_chamber, 1, chamber="house")
check(fr_no["passed"] is False, "ordinary bill fails when present-and-voting majority is nay")

# --- passage: override class needs OVERRIDE_THRESHOLD yea out of elected ----
# a small (27-seat) fully-pinned-yea chamber: comfortably clears its own
# present-and-voting majority, and (since 27 > OVERRIDE_THRESHOLD["house"]=26)
# also clears the override bar -- isolates that "threshold" is read out as
# "elected", distinct from the ordinary present-and-voting path above.
tiny_present_chamber = pinned_chamber(27, "vang", votes.PARTY_MU["vang"])
fr_ov_fail = votes.floor_result("HB-102", dict(yea_bill, **{"class": "override"}),
                                 tiny_present_chamber, 1, chamber="house")
check(fr_ov_fail["threshold"] == "elected", "override bill uses elected-count threshold")
check(fr_ov_fail["quorum"], "27-of-27-present chamber still holds quorum")
# 27 pinned yea-leaning members with attend=0.99 will mostly show up and vote
# yea, comfortably clearing OVERRIDE_THRESHOLD["house"]=26 -- confirm the
# threshold is actually being read from OVERRIDE_THRESHOLD, not just parroting
# the ordinary present-and-voting majority test:
check(fr_ov_fail["yea"] >= votes.OVERRIDE_THRESHOLD["house"] or not fr_ov_fail["passed"],
      "override never passes below OVERRIDE_THRESHOLD yea votes")

full_override_chamber = pinned_chamber(51, "vang", votes.PARTY_MU["vang"])
fr_ov_pass = votes.floor_result("HB-103", dict(yea_bill, **{"class": "override"}),
                                 full_override_chamber, 1, chamber="house")
check(fr_ov_pass["yea"] >= votes.OVERRIDE_THRESHOLD["house"], "full pinned chamber clears override threshold")
check(fr_ov_pass["passed"] is True, "override passes once yea >= OVERRIDE_THRESHOLD")

# a chamber with a comfortable present-and-voting majority (>50%) but not
# enough absolute yea votes to hit OVERRIDE_THRESHOLD must fail as an override
half_present = {}
half_present.update({k: v for i, (k, v) in enumerate(pinned_chamber(51, "vang", votes.PARTY_MU["vang"]).items())})
# knock most members' attendance to 0 so few show up, but the few who do all vote yea
for i, (mid, m) in enumerate(half_present.items()):
    m["attend"] = 0.99 if i < 10 else 0.0   # only 10 of 51 ever show
fr_ov_low_turnout = votes.floor_result("HB-104", dict(yea_bill, **{"class": "override"}),
                                        half_present, 1, chamber="house")
check(fr_ov_low_turnout["quorum"] is False or fr_ov_low_turnout["yea"] < votes.OVERRIDE_THRESHOLD["house"],
      "sparse-attendance override cannot reach the elected threshold")
check(fr_ov_low_turnout["passed"] is False, "override fails without enough absolute yea votes")

# --- quorum can fail purely from attendance (delta 1) -----------------------
ghost_chamber = pinned_chamber(51, "vang", votes.PARTY_MU["vang"])
for m in ghost_chamber.values():
    m["attend"] = 0.0   # nobody ever shows
fr_ghost = votes.floor_result("HB-105", yea_bill, ghost_chamber, 1, chamber="house")
check(fr_ghost["quorum"] is False, "0-attendance chamber fails quorum")
check(fr_ghost["absent"] == 51, "0-attendance chamber: everyone absent")
check(fr_ghost["passed"] is False, "no vote occurs (passed=False) without quorum")

check(votes.quorum_ok("house", 26) is True, "26/51 exactly meets house quorum")
check(votes.quorum_ok("house", 25) is False, "25/51 misses house quorum")
check(votes.quorum_ok("senate", 5) is True, "5/9 exactly meets senate quorum")
check(votes.quorum_ok("senate", 4) is False, "4/9 misses senate quorum")

# --- Goose bloc: abstains on non-tagged bills, participates on tagged ones --
goose_members = {mid: m for mid, m in members.items() if m["party"] == "goose"}
check(len(goose_members) == 4, "fixture mints the canon 4 Goose House seats")

all_absent_untagged = True
for bill_id in [f"HB-{200+i}" for i in range(30)]:
    for mid, m in goose_members.items():
        stance = votes.member_stance(mid, m, bill_id, NON_GOOSE_BILL, 1)
        vote = votes.member_vote(mid, m, bill_id, NON_GOOSE_BILL, 1)
        if stance != "absent" or vote != "absent":
            all_absent_untagged = False
check(all_absent_untagged, "Goose bloc abstains (absent) on every non-goose-tagged bill")

some_participate_tagged = False
for bill_id in [f"HB-{300+i}" for i in range(30)]:
    for mid, m in goose_members.items():
        if votes.member_vote(mid, m, bill_id, GOOSE_BILL, 1) != "absent":
            some_participate_tagged = True
check(some_participate_tagged, "Goose bloc actually votes on at least some goose-tagged bills")

# --- goose_price: enumerable, deterministic, gated by tag -------------------
check(votes.goose_price("HB-1", NON_GOOSE_BILL) is None, "no price on an untagged bill")
p1 = votes.goose_price("HB-2", GOOSE_BILL)
check(p1 in votes.GOOSE_PRICE_LIST.values(), "tagged bill's price is on the canon list")
p2 = votes.goose_price("HB-2", GOOSE_BILL)
check(p1 == p2, "goose_price is deterministic for the same bill id")
p3 = votes.goose_price("HB-999-different", GOOSE_BILL)
# not asserting inequality (small list, collisions are fine) but must still be valid
check(p3 in votes.GOOSE_PRICE_LIST.values(), "a different bill id still yields a canon price")
flag_only = {"sponsor": "H-01", "goose_tag": True, "axis": 0.5}
check(votes.goose_price("HB-3", flag_only) in votes.GOOSE_PRICE_LIST.values(),
      "bare goose_tag=True (no specific tag) still yields a canon price")

# --- determinism / self-healing: replay + member-order independence --------
wc1 = votes.whip_count("HB-7", ORDINARY, members, 5, chamber="house")
wc2 = votes.whip_count("HB-7", ORDINARY, members, 5, chamber="house")
check(wc1 == wc2, "whip_count is deterministic across repeated calls")

shuffled = dict(reversed(list(members.items())))
wc3 = votes.whip_count("HB-7", ORDINARY, shuffled, 5, chamber="house")
check(wc1 == wc3, "whip_count is independent of members-dict iteration order")

fr1 = votes.floor_result("HB-7", ORDINARY, members, 5, chamber="house")
fr2 = votes.floor_result("HB-7", ORDINARY, members, 5, chamber="house")
check(fr1 == fr2, "floor_result is deterministic across repeated calls")

different_ga = votes.floor_result("HB-7", ORDINARY, members, 6, chamber="house")
check(different_ga != fr1, "a different GA reseeds the vote (independent draw)")

# a stance's presence agrees with the eventual vote's presence (shared draw)
agree = True
for bill_id in [f"HB-{400+i}" for i in range(20)]:
    for mid, m in members.items():
        st = votes.member_stance(mid, m, bill_id, ORDINARY, 1)
        vo = votes.member_vote(mid, m, bill_id, ORDINARY, 1)
        if (st == "absent") != (vo == "absent"):
            agree = False
check(agree, "member_stance and member_vote agree on who is absent (shared draw)")

# --- voice/roll split lands near the grounding band (65-75% voice) ---------
rolls = sum(1 for i in range(4000) if votes.vote_type(f"HB-{i}", 1) == "roll")
frac = rolls / 4000
check(0.20 <= frac <= 0.40, f"roll-call fraction near 30% band (got {frac:.3f})")

# --- party-line adherence: a bill matching a party's mu draws mostly yea ---
adherent_bill = {"sponsor": "H-00", "axis": votes.PARTY_MU["prov"]}
prov_yes = 0
prov_total = 0
for bill_id in [f"HB-{500+i}" for i in range(200)]:
    for mid, m in members.items():
        if m["party"] != "prov":
            continue
        v = votes.member_vote(mid, m, bill_id, adherent_bill, 1)
        if v in ("yea", "nay"):
            prov_total += 1
            if v == "yea":
                prov_yes += 1
adherence = prov_yes / prov_total
check(adherence >= 0.70, f"prov adherence to an on-axis bill is high (got {adherence:.3f})")

# --- party_line itself: neutral parties, matched-axis anchors ---------------
check(votes.party_line({"axis": 0.5}, "round", 1) == 0.5, "round has no fixed line")
check(votes.party_line({"axis": 0.5}, "goose", 1) == 0.5, "goose has no fixed line")
check(votes.party_line({"axis": votes.PARTY_MU["vang"]}, "vang", 1) == 1.0,
      "party_line is 1.0 when the bill's axis exactly matches the party mu")
check(votes.party_line({"axis": 1.0 - votes.PARTY_MU["vang"]}, "vang", 1) < 1.0,
      "party_line drops off the further the bill drifts from the party mu")

print(f"\nstatehouse votes {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
