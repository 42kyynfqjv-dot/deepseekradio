"""Statehouse members fixtures: the 60-seat mint, the closed 7-party seat
table, per-member zipper/discipline/maverick/attend scalars, the goose
bloc's off-axis pricing, and incumbent carryover across Assemblies.

Run directly (no pytest needed):  python3 tests/test_statehouse_members.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import livegame
from src.statehouse import members as mem

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


# --- name bank: same style, zero token overlap (friction #4) ---------------

check(set(mem.MEMBER_FIRST).isdisjoint(livegame.FIRST_NAMES),
      "member first names disjoint from livegame's")
check(set(mem.MEMBER_LAST).isdisjoint(livegame.LAST_NAMES),
      "member last names disjoint from livegame's")

_official_names = {o["name"] for o in mem.CANON_OFFICIALS.values()}
check(_official_names == {"Marty Bouchard", "Gord Pelletier", "Bert Demers",
                           "Toivo Ostberg"}, "canon officials pinned verbatim")
check(all(n.split()[0] not in mem.MEMBER_FIRST and n.split()[1] not in mem.MEMBER_LAST
          for n in _official_names), "official name tokens absent from member bank")

# --- the mint ----------------------------------------------------------------

ga1 = mem.mint_assembly(1, {})
ga1_again = mem.mint_assembly(1, {})

check(ga1 == ga1_again, "mint_assembly is deterministic per (ga, canon)")

house = {sid: m for sid, m in ga1["members"].items() if m["chamber"] == "house"}
senate = {sid: m for sid, m in ga1["members"].items() if m["chamber"] == "senate"}

check(len(house) == 51, f"51 House members minted (got {len(house)})")
check(len(senate) == 9, f"9 Senate members minted (got {len(senate)})")
check(len(ga1["members"]) == 60, "60 members total")

# --- seat sums / party table exact -------------------------------------------

agg = mem.seat_table(ga1)
check(agg == mem.DEFAULT_SEATS, f"party table exact: {agg}")
check(sum(agg["house"].values()) == 51, "house seat sum == 51")
check(sum(agg["senate"].values()) == 9, "senate seat sum == 9")
check("oic" not in agg["house"] and "oic" not in agg["senate"],
      "OIC holds no seats (seatless canon)")
check(set(agg["house"]) <= set(mem.PARTIES) and set(agg["senate"]) <= set(mem.PARTIES),
      "every seated party is in the closed 7")

# hung House: no single bloc reaches a 26-seat majority alone
check(max(agg["house"].values()) < 26,
      "hung House: no single party bloc reaches 26 alone")

# --- per-member scalars -------------------------------------------------------

for sid, m in ga1["members"].items():
    check(0.88 <= m["attend"] <= 0.98, f"{sid} attend in [0.88, 0.98] (got {m['attend']})")
    check(0.0 <= m["maverick"] <= 1.0, f"{sid} maverick in [0,1]")
    check(0.0 <= m["discipline"] <= 1.0, f"{sid} discipline in [0,1]")
    if m["party"] == "goose":
        check(m["zipper"] is None, f"{sid} goose member has no zipper (off-axis)")
    else:
        check(m["zipper"] is not None and 0.0 <= m["zipper"] <= 1.0,
              f"{sid} zipper in [0,1] ({m['zipper']})")
    check(m["aired"] is False, f"{sid} starts unaired")
    check(m["tenure"] >= 1, f"{sid} has a plausible tenure")

# districts: house identity-numbered 1-51, senate 100+seat (mirror's own
# "S-07" -> district 107 example)
house_districts = sorted(m["district"] for m in house.values())
check(house_districts == list(range(1, 52)), "house districts are exactly 1..51")
senate_districts = sorted(m["district"] for m in senate.values())
check(senate_districts == list(range(101, 110)), "senate districts are exactly 101..109")

# names: unique within the assembly, none colliding with pinned officials
all_names = [m["name"] for m in ga1["members"].values()]
check(len(set(all_names)) == 60, "60 unique member names, zero collisions")
check(_official_names.isdisjoint(all_names), "no member shares a pinned official's name")

# --- officials / leaders -------------------------------------------------------

o = ga1["officials"]
check(o["governor"] == {"name": "Marty Bouchard", "canon": True}, "governor pinned")
check(o["clerk"] == {"name": "Gord Pelletier", "canon": True}, "clerk pinned")
check(o["potholes"] == {"name": "Bert Demers", "canon": True}, "potholes commissioner pinned")
check(o["roundabout"] == {"name": "Toivo Ostberg", "canon": True}, "roundabout foreman pinned")
check(o["tenth_chair"] == {"name": None, "trusted": False},
      "tenth chair: nine good chairs and a tenth no one trusts")
check(o["speaker"] in house, "speaker is a real House seat")
check(o["protem"] in senate, "president pro tem is a real Senate seat")

for chamber, ids in (("house", house), ("senate", senate)):
    for party, sid in ga1["leaders"][chamber].items():
        check(sid in ids and ids[sid]["party"] == party,
              f"{chamber} leader for {party} ({sid}) actually holds that seat for that party")

# --- bad seat table raises ---------------------------------------------------

try:
    mem.mint_assembly(1, {"seats": {"house": {"prov": 50}, "senate": mem.DEFAULT_SEATS["senate"]}})
    check(False, "malformed house seat table should raise")
except ValueError:
    check(True, "malformed house seat table raises ValueError")

try:
    mem.mint_assembly(1, {"seats": {"house": mem.DEFAULT_SEATS["house"],
                                     "senate": {"oic": 9}}})
    check(False, "OIC-seated table should raise")
except ValueError:
    check(True, "OIC given seats raises ValueError (seatless canon)")

# --- determinism across a different ga (different seed, different mint) -----

ga2_fresh = mem.mint_assembly(2, {})
check(ga2_fresh != ga1, "a different GA (no carryover) mints a different assembly")
check(mem.seat_table(ga2_fresh) == mem.DEFAULT_SEATS, "GA2 fresh mint still seat-exact")

# --- party_line / goose_price / member_vote -----------------------------------

bill_neutral = {"id": "HB-1", "axis": 0.5}
bill_late = {"id": "HB-2", "axis": 0.9}
for party in mem.PARTIES:
    if party == "oic":
        continue
    p = mem.party_line(bill_neutral, party, 1)
    check(0.0 <= p <= 1.0, f"party_line({party}) bounded [0,1]")

check(mem.party_line(bill_late, "vang", 1) > mem.party_line(bill_neutral, "vang", 1),
      "the Late-anchored Vanguard likes a late-leaning bill more than a neutral one")
check(mem.party_line(bill_late, "prov", 1) < mem.party_line(bill_neutral, "prov", 1),
      "cautious-Early Provisional likes a late-leaning bill less than a neutral one")
check(mem.party_line(bill_neutral, "round", 1) == 0.5, "Roundabout has no unified party line")
check(mem.party_line(bill_neutral, "goose", 1) == 0.5, "goose party_line is a neutral placeholder (off-axis)")

check(mem.goose_price({"tags": []}) is None, "no goose price without a goose-relevant tag")
check(mem.goose_price({"tags": ["lot_paving"]}) == mem.GOOSE_PRICES["lot_paving"],
      "goose price is the enumerable canon lookup")
check(mem.goose_price({"tags": ["waterfowl", "lot_paving"]}) == mem.GOOSE_PRICES["waterfowl"],
      "first matching tag wins, deterministically")

some_house_member = house[sorted(house)[0]]
v1 = mem.member_vote(some_house_member, bill_neutral, 1)
v2 = mem.member_vote(some_house_member, bill_neutral, 1)
check(isinstance(v1, bool), "member_vote returns a bool")
check(v1 == v2, "member_vote is deterministic for identical (m, bill, ga)")

goose_member = next(m for m in house.values() if m["party"] == "goose")
check(mem.member_vote(goose_member, {"id": "HB-3", "tags": []}, 1) is False,
      "un-priced goose member never invents a yes")

# --- seat_new_assembly: incumbent carryover -----------------------------------

winner_sid = sorted(house)[0]
incumbent = house[winner_sid]
loser_sid = sorted(house)[1]

el = {"races": {
    winner_sid: {"cands": [{"name": incumbent["name"], "party": incumbent["party"], "inc": True},
                            {"name": "Challenger One", "party": "grudge"}],
                 "final": [1600, 1400]},
    loser_sid: {"cands": [{"name": house[loser_sid]["name"], "party": house[loser_sid]["party"], "inc": True},
                           {"name": "Challenger Two", "party": "barb"}],
                "final": [1200, 1800]},
}}

carry = mem.seat_new_assembly(el, ga1)
check(winner_sid in carry, "re-elected incumbent shows up in carryover")
check(carry[winner_sid]["name"] == incumbent["name"], "carryover keeps the incumbent's name")
check(carry[winner_sid]["tenure"] == incumbent["tenure"], "carryover records prior tenure (mint bumps it)")
check(loser_sid not in carry, "a seat won by a challenger is absent from carryover")

ga2_carry = mem.mint_assembly(2, {}, carryover=carry)
check(mem.seat_table(ga2_carry) == mem.DEFAULT_SEATS,
      "seat sums stay exact even with carryover applied")
carried_member = next(m for m in ga2_carry["members"].values()
                       if m["name"] == incumbent["name"])
check(carried_member["tenure"] == incumbent["tenure"] + 1,
      "carried-over member's tenure increments in the new Assembly")
check(carried_member["aired"] is False, "carried-over member resets unaired for the new term")

print(f"\nstatehouse members {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
