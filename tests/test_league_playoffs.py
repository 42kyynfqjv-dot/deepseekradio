"""League playoffs fixtures: bracket seeds match a hand-computed 32-team
standings fixture (including a tie resolved by rw), seeded series advance
correctly to completion, champion only fires at 4 wins in the Cup series,
and round-2+ pairings are never reseeded across a whole conference.

Run directly (no pytest needed):  python3 tests/test_league_playoffs.py
"""
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.league import playoffs as P

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


# --- 32-team standings fixture ----------------------------------------------
# Rank-ordered w within each division; gp=82, otl=0 for all except one
# deliberate pts%-tie pair (bra/eug) broken only by rw — that tie sits
# exactly on the Western wild-card boundary (2nd vs 3rd of the remainder
# pool) so the test is meaningful, not cosmetic.
_RANKS = {
    "Boreal":   [("mtl", 60), ("tbr", 55), ("hfx", 50), ("trr", 45),
                 ("gan", 40), ("bur", 35), ("pmc", 30), ("stj", 25)],
    "Gridiron": [("nyg", 58), ("yon", 53), ("uti", 48), ("sch", 43),
                 ("alb", 38), ("scr", 33), ("bal", 28), ("rich", 23)],
    "Prairie":  [("ssk", 56), ("wpg", 51), ("mjm", 46), ("reg", 41),
                 ("bra", 39), ("far", 31), ("bis", 26), ("dul", 21)],
    "Pacific":  [("vic", 54), ("kam", 49), ("spo", 44), ("eug", 39),
                 ("bak", 34), ("fre", 29), ("tuc", 24), ("boi", 19)],
}

STANDINGS = {}
for _dname, _rows in _RANKS.items():
    for team, w in _rows:
        rw, row = w - 5, w - 10
        if team == "bra":       # tied on pts% with eug, loses the tiebreak
            rw, row = 15, 20
        elif team == "eug":
            rw, row = 25, 30
        STANDINGS[team] = {"w": w, "l": 82 - w, "otl": 0, "streak": 0,
                            "gp": 82, "rw": rw, "row": row}

check(len(STANDINGS) == 32, "fixture covers all 32 teams")
check(STANDINGS["bra"]["w"] == STANDINGS["eug"]["w"] == 39,
      "bra/eug pts% tie is genuine (equal w, equal gp/otl)")

BRACKET = P.seed_bracket(STANDINGS)

# --- hand-computed expectations ---------------------------------------------
E, W = BRACKET["conferences"]["Eastern"], BRACKET["conferences"]["Western"]
check(E["top_div"] == "Boreal" and E["alt_div"] == "Gridiron",
      "Eastern: mtl's division outranks nyg's -> Boreal is top_div")
check(E["top"] == ["mtl", "tbr", "hfx"], "Boreal top 3 by w")
check(E["alt"] == ["nyg", "yon", "uti"], "Gridiron top 3 by w")
check(E["wc1"] == "trr" and E["wc2"] == "sch",
      "Eastern wild cards: trr(45) then sch(43)")

check(W["top_div"] == "Prairie" and W["alt_div"] == "Pacific",
      "Western: ssk's division outranks vic's -> Prairie is top_div")
check(W["top"] == ["ssk", "wpg", "mjm"], "Prairie top 3 by w")
check(W["alt"] == ["vic", "kam", "spo"], "Pacific top 3 by w")
check(W["wc1"] == "reg", "Western wc1 = reg(41), clear of any tie")
check(W["wc2"] == "eug",
      "tiebreak: eug(rw=25) beats bra(rw=15) at equal pts% -> eug takes "
      "the wild-card spot bra would otherwise have tied for")

S = BRACKET["series"]
check(len(S) == 8, "8 round-1 series total (4 per conference x 2 conferences)")
check(BRACKET["champion"] is None, "no champion at seed time")

check({S["Eastern-A-1"]["higher"], S["Eastern-A-1"]["lower"]} == {"mtl", "sch"},
      "A1 (mtl) vs weaker wild card (sch)")
check(S["Eastern-A-1"]["higher"] == "mtl", "mtl (higher pts%) hosts vs sch")
check({S["Eastern-A-2"]["higher"], S["Eastern-A-2"]["lower"]} == {"tbr", "hfx"},
      "Eastern #2 vs #3 within top_div (Boreal)")
check({S["Eastern-B-1"]["higher"], S["Eastern-B-1"]["lower"]} == {"nyg", "trr"},
      "B1 (nyg) vs stronger wild card (trr)")
check({S["Eastern-B-2"]["higher"], S["Eastern-B-2"]["lower"]} == {"yon", "uti"},
      "Eastern #2 vs #3 within alt_div (Gridiron)")
check({S["Western-A-1"]["higher"], S["Western-A-1"]["lower"]} == {"ssk", "eug"},
      "Western A1 (ssk) vs weaker wild card (eug, via tiebreak over bra)")
check({S["Western-A-2"]["higher"], S["Western-A-2"]["lower"]} == {"wpg", "mjm"},
      "Western #2 vs #3 within top_div (Prairie)")
check({S["Western-B-1"]["higher"], S["Western-B-1"]["lower"]} == {"vic", "reg"},
      "Western B1 (vic) vs stronger wild card (reg)")
check({S["Western-B-2"]["higher"], S["Western-B-2"]["lower"]} == {"kam", "spo"},
      "Western #2 vs #3 within alt_div (Pacific)")

# --- champion only fires at 4 wins ------------------------------------------
b2 = P.seed_bracket(STANDINGS)
sid = "Eastern-A-1"
hi, lo = b2["series"][sid]["higher"], b2["series"][sid]["lower"]
for _ in range(3):
    P.fold_playoff(b2, {"home": hi, "away": lo, "final": [3, 1]})
check(b2["series"][sid]["winner"] is None,
      "series undecided at 3 wins (best-of-7 needs 4)")
check(b2["champion"] is None, "no champion while round 1 is still live")
P.fold_playoff(b2, {"home": hi, "away": lo, "final": [3, 1]})
check(b2["series"][sid]["winner"] == hi, "4th win closes the series")
check(b2["series"][sid]["wins"][hi] == 4 and b2["series"][sid]["wins"][lo] == 0,
      "win tally is exactly 4-0 here (every folded game had the same winner)")
check(b2["champion"] is None,
      "one round-1 series closing does not crown a champion")


# --- full seeded run: advance to a champion, no reseeding -------------------
def _find_series(bracket, home, away):
    for s in bracket["series"].values():
        if s["winner"] is None and {s["higher"], s["lower"]} == {home, away}:
            return s
    return None


def _drive(bracket, seed, higher_win_p, tracked=("mtl", "nyg"), max_days=500):
    """Walk the calendar, folding a seeded, winner-consistent box for every
    game schedule_series names, until a champion emerges or the budget
    runs out. Returns games played, or None if it never converged."""
    rng = random.Random(seed)
    d = date(2027, 1, 12)  # a Wednesday
    games_played = 0
    for _ in range(max_days):
        slate = P.schedule_series(bracket, d.isoformat(), tracked)
        for g in slate:
            s = _find_series(bracket, g["home"], g["away"])
            if s is None:
                continue
            higher_wins = rng.random() < higher_win_p
            winner = s["higher"] if higher_wins else s["lower"]
            if winner == g["home"]:
                hs = rng.randint(2, 6)
                as_ = rng.randint(0, hs - 1)
            else:
                as_ = rng.randint(2, 6)
                hs = rng.randint(0, as_ - 1)
            P.fold_playoff(bracket, {"home": g["home"], "away": g["away"],
                                      "final": [hs, as_]})
            games_played += 1
        if P.champion(bracket) is not None:
            return games_played
        d += timedelta(days=1)
    return None


b3 = P.seed_bracket(STANDINGS)
r1_sets = {sid: frozenset([s["higher"], s["lower"]])
           for sid, s in b3["series"].items()}
n_games = _drive(b3, seed="det-run-1", higher_win_p=0.85)
check(n_games is not None, "a champion is reached within the day budget")
check(P.champion(b3) is not None, "champion() returns the Cup winner")

for sid, teams in r1_sets.items():
    check({b3["series"][sid]["higher"], b3["series"][sid]["lower"]} == teams,
          f"round-1 series {sid} untouched after the run (participants fixed)")

for sid, s in b3["series"].items():
    if s["winner"] is not None:
        check(s["wins"][s["winner"]] == 4, f"{sid}: winner has exactly 4 wins")
        check(max(s["wins"].values()) <= 4 and sum(s["wins"].values()) <= 7,
              f"{sid}: best-of-7 never overruns (wins={s['wins']})")

# Round-2 pairs must be exactly {winner(A-1), winner(A-2)} / {winner(B-1),
# winner(B-2)} per conference -- never a full-conference reseed across all
# four round-1 winners.
for conf in ("Eastern", "Western"):
    a1w = b3["series"][f"{conf}-A-1"]["winner"]
    a2w = b3["series"][f"{conf}-A-2"]["winner"]
    b1w = b3["series"][f"{conf}-B-1"]["winner"]
    b2w = b3["series"][f"{conf}-B-2"]["winner"]
    r2a = b3["series"].get(f"{conf}-A")
    r2b = b3["series"].get(f"{conf}-B")
    if r2a is not None:
        check({r2a["higher"], r2a["lower"]} == {a1w, a2w},
              f"{conf}-A round-2 pairing is exactly the A-bracket's two winners")
    if r2b is not None:
        check({r2b["higher"], r2b["lower"]} == {b1w, b2w},
              f"{conf}-B round-2 pairing is exactly the B-bracket's two winners")

cup = b3["series"].get("CUP")
if cup is not None:
    east_final_w = b3["series"].get("Eastern", {}).get("winner")
    west_final_w = b3["series"].get("Western", {}).get("winner")
    check({cup["higher"], cup["lower"]} == {east_final_w, west_final_w},
          "CUP final is exactly {East champ, West champ}, no reseeding")
    check(P.champion(b3) == cup["winner"], "champion() == CUP series winner")

# a second, closer seeded run (higher seed barely favored) to exercise
# upsets through the same machinery
b4 = P.seed_bracket(STANDINGS)
n2 = _drive(b4, seed="det-run-2", higher_win_p=0.52)
check(n2 is not None, "closer seeded run also reaches a champion")
check(P.champion(b4) is not None, "champion set on the upset-prone run too")


# --- schedule_series: tracked pinned to Wed/Sat, off-air every >=2 days ----
b5 = P.seed_bracket(STANDINGS)
tracked_sid = next(sid for sid, s in b5["series"].items()
                    if {s["higher"], s["lower"]} & {"mtl", "nyg"})
off_sid = next(sid for sid, s in b5["series"].items()
               if not ({s["higher"], s["lower"]} & {"mtl", "nyg"}))

d0 = date(2027, 1, 12)  # a Wednesday
tracked_weekdays, off_day_indices = [], []
for i in range(20):
    day = (d0 + timedelta(days=i)).isoformat()
    slate = P.schedule_series(b5, day, ("mtl", "nyg"))
    tracked_s = b5["series"].get(tracked_sid)
    off_s = b5["series"].get(off_sid)
    for g in slate:
        if tracked_s is not None and {g["home"], g["away"]} == \
                {tracked_s["higher"], tracked_s["lower"]}:
            tracked_weekdays.append((d0 + timedelta(days=i)).weekday())
        if off_s is not None and {g["home"], g["away"]} == \
                {off_s["higher"], off_s["lower"]}:
            off_day_indices.append(i)
        # neutral, non-deciding result: keep both series alive across the
        # whole sampling window
        P.fold_playoff(b5, {"home": g["home"], "away": g["away"],
                             "final": [1, 0]})

check(len(tracked_weekdays) >= 2, "tracked series gets multiple games sampled")
check(all(wd in (2, 5) for wd in tracked_weekdays),
      "every tracked-series game lands on Wed(2) or Sat(5)")
check(len(off_day_indices) >= 2, "off-air series gets multiple games sampled")
if len(off_day_indices) > 1:
    gaps = [b - a for a, b in zip(off_day_indices, off_day_indices[1:])]
    check(all(g >= 2 for g in gaps), "off-air series games land >=2 days apart")

# playoff dict shape matches the frozen additive-key contract
b6 = P.seed_bracket(STANDINGS)
day6 = date(2027, 1, 13).isoformat()  # a Wednesday
slate6 = P.schedule_series(b6, day6, ("mtl", "nyg"))
check(len(slate6) > 0, "opening Wednesday produces a playoff slate")
for g in slate6:
    check(set(g.keys()) == {"home", "away", "playoff"},
          "game descriptor has exactly home/away/playoff")
    check(set(g["playoff"].keys()) == {"round", "game", "series"},
          "playoff sub-dict has exactly round/game/series")
    check(g["playoff"]["round"] == 1 and g["playoff"]["game"] == 1,
          "first night of round 1 is game 1")
    check(g["playoff"]["series"] == [0, 0], "0-0 entering game 1")

# --- h2h hook: only consulted on an exact chain tie -------------------------
# In the main fixture, bra/eug tie on pts%% but rw already separates them --
# resolved by rw, h2h never needed. To exercise the hook itself, force a
# FULL tie (pts%%, rw, row, w all equal) between exactly one pair and check
# h2h is consulted for that pair and nobody else.
TIE_STANDINGS = {k: dict(v) for k, v in STANDINGS.items()}
TIE_STANDINGS["eug"]["rw"] = TIE_STANDINGS["bra"]["rw"]
TIE_STANDINGS["eug"]["row"] = TIE_STANDINGS["bra"]["row"]

calls = []


def _h2h(a, b):
    calls.append((a, b))
    return a  # always prefer the first arg


P.seed_bracket(TIE_STANDINGS, h2h=_h2h)
check(len(calls) >= 1,
      "the one fully-tied pair (bra/eug, pts%%/rw/row/w all equal) does "
      "consult h2h")
check(all({a, b} == {"bra", "eug"} for a, b in calls),
      "h2h is NEVER consulted for any of the other, unambiguous comparisons "
      "made while building the bracket -- only the bra/eug full tie is")

print(f"\nleague-playoffs {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
