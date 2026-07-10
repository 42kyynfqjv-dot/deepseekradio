"""League stats fixtures: fold 100 synthetic boxes and hand-check the
aggregate, leaders stable-sort and gp stays consistent, and every numeral
milestones() prints is derivable from the just-folded stats.

Run directly (no pytest needed):  python3 tests/test_league_stats.py
"""
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.league import stats as S

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


# --- fixtures ----------------------------------------------------------
TEAMS = ["mtl", "tbr"]
_NAMES = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
PLAYERS = {"players": {}}
for team in TEAMS:
    for i in range(1, 6):
        PLAYERS["players"][f"{team}-{i:02d}"] = {
            "name": f"{team.upper()}{_NAMES[i - 1]}", "team": team, "pos": "F",
        }
    PLAYERS["players"][f"{team}-22"] = {
        "name": f"{team.upper()}Netminder", "team": team, "pos": "G",
    }


def gen_box(rng, home, away):
    """A small synthetic box conforming to the frozen §2 box shape."""
    h_pool = [f"{home}-{i:02d}" for i in range(1, 6)]
    a_pool = [f"{away}-{i:02d}" for i in range(1, 6)]
    goals = []
    counts = {"h": 0, "a": 0}
    n_goals = rng.randint(0, 6)
    for _ in range(n_goals):
        side = rng.choice(["h", "a"])
        pool = h_pool if side == "h" else a_pool
        scorer = rng.choice(pool)
        rest = [p for p in pool if p != scorer]
        a1 = rng.choice(rest) if rest and rng.random() < 0.9 else None
        rest2 = [p for p in rest if p != a1]
        a2 = rng.choice(rest2) if rest2 and a1 and rng.random() < 0.6 else None
        goals.append({
            "t": side, "period": rng.randint(1, 3),
            "clock": f"{rng.randint(0, 19):d}:{rng.randint(0, 59):02d}",
            "scorer": scorer, "a1": a1, "a2": a2,
            "str": rng.choice(["EV", "PP", "PK"]),
        })
        counts[side] += 1

    ot, so = False, False
    if counts["h"] == counts["a"]:
        # force a decision the way an OT/SO winner would, with no extra
        # goal event -- the documented GWG-friction case.
        if rng.random() < 0.5:
            counts["h"] += 1
        else:
            counts["a"] += 1
        ot = True

    hg, ag = counts["h"], counts["a"]
    shots_h = hg + rng.randint(15, 30)
    shots_a = ag + rng.randint(15, 30)
    return {
        "home": home, "away": away, "final": [hg, ag], "ot": ot, "so": so,
        "goals": goals, "shots": [shots_h, shots_a],
        "goalies": {"h": f"{home}-22", "a": f"{away}-22"},
        "stars": [], "injuries": [],
    }


# --- fold 100 synthetic boxes, hand-check the aggregate -----------------
rng = random.Random(4242)
stats = {"schema": 1, "season": 1, "skaters": {}, "goalies": {}}
boxes = []
for i in range(100):
    home, away = ("mtl", "tbr") if i % 2 == 0 else ("tbr", "mtl")
    boxes.append(gen_box(rng, home, away))

# independent hand-check tally, written without reusing fold_box's code
expect_sk = {}   # pid -> [gp, g, a, pim, gwg, hat]
expect_gl = {}   # pid -> [gp, w, l, otl, sa, sv, so]
for box in boxes:
    hg, ag = box["final"]
    ot = box["ot"]
    shots = box["shots"]
    h_pid, a_pid = box["goalies"]["h"], box["goalies"]["a"]
    for pid, gf, ga, shots_against, won in (
        (h_pid, hg, ag, shots[1], hg > ag),
        (a_pid, ag, hg, shots[0], ag > hg),
    ):
        g = expect_gl.setdefault(pid, [0, 0, 0, 0, 0, 0, 0])
        g[0] += 1
        g[4] += shots_against
        g[5] += max(0, shots_against - ga)
        if won:
            g[1] += 1
        elif ot:
            g[3] += 1
        else:
            g[2] += 1
        if ga == 0:
            g[6] += 1

    seen = set()
    game_goals = {}
    for ev in box["goals"]:
        sc = ev["scorer"]
        sk = expect_sk.setdefault(sc, [0, 0, 0, 0, 0, 0])
        sk[1] += 1
        game_goals[sc] = game_goals.get(sc, 0) + 1
        seen.add(sc)
        for asst in (ev["a1"], ev["a2"]):
            if asst:
                expect_sk.setdefault(asst, [0, 0, 0, 0, 0, 0])[2] += 1
                seen.add(asst)
    for pid in seen:
        expect_sk[pid][0] += 1
    for pid, n in game_goals.items():
        if n >= 3:
            expect_sk[pid][5] += 1

for box in boxes:
    S.fold_box(stats, box)

# gwg is the one field the hand-check doesn't independently derive (it's
# the documented derived-from-chronology field); compare everything else
# field-for-field, then sanity-check gwg on its own.
stats_no_gwg = {pid: arr[:4] + arr[5:] for pid, arr in stats["skaters"].items()}
expect_no_gwg = {pid: arr[:4] + arr[5:] for pid, arr in expect_sk.items()}
check(stats_no_gwg == expect_no_gwg,
      f"skater aggregate (minus gwg) matches hand-check ({stats_no_gwg} vs {expect_no_gwg})")
total_gwg = sum(a[4] for a in stats["skaters"].values())
check(0 <= total_gwg <= len(boxes), "gwg total bounded by number of games")
check(all(a[4] <= a[1] for a in stats["skaters"].values()),
      "gwg never exceeds a player's own goal total")
check(stats["goalies"] == expect_gl,
      f"goalie aggregate matches hand-check ({stats['goalies']} vs {expect_gl})")

# --- gp consistency -------------------------------------------------
# both mtl-22/tbr-22 start in every one of the 100 boxes (alternating
# home/away), so each starts all 100 games.
for pid, arr in stats["goalies"].items():
    check(arr[0] == 100, f"{pid} goalie gp == games started (100), got {arr[0]}")
    check(arr[1] + arr[2] + arr[3] == arr[0], f"{pid} w+l+otl == gp")
for pid, arr in stats["skaters"].items():
    check(arr[0] <= 100, f"{pid} skater gp never exceeds games folded")
    check(arr[0] >= arr[5] * 0, f"{pid} gp non-negative sanity")
    check(arr[1] >= 0 and arr[2] >= 0, f"{pid} g/a non-negative")

# --- leaders: stable-sorted, correct ordering ------------------------
tie_stats = {
    "skaters": {
        "a-01": [10, 5, 5, 0, 0, 0],   # p=10
        "a-02": [10, 6, 4, 0, 0, 0],   # p=10, inserted second
        "a-03": [10, 3, 2, 0, 0, 0],   # p=5
    },
    "goalies": {},
}
tie_players = {"players": {
    "a-01": {"name": "First", "team": "a"},
    "a-02": {"name": "Second", "team": "a"},
    "a-03": {"name": "Third", "team": "a"},
}}
lead = S.leaders(tie_stats, tie_players, key="p", n=3)
check([r["pid"] for r in lead] == ["a-01", "a-02", "a-03"],
      f"points leaders sorted desc, ties keep insertion order: {lead}")
lead2 = S.leaders(tie_stats, tie_players, key="p", n=3)
check(lead == lead2, "leaders() deterministic/repeatable on same stats (stable)")

lead_g = S.leaders(tie_stats, tie_players, key="g", n=2)
check([r["pid"] for r in lead_g] == ["a-02", "a-01"], "goal leaders sorted by g")

# sv% leaders respect the MIN_GP_GOALIE_RATE floor
sv_stats = {"skaters": {}, "goalies": {
    "a-22": [3, 2, 1, 0, 90, 85, 0],     # below floor, excluded
    "a-23": [20, 12, 5, 3, 600, 550, 2],  # qualifies
}}
sv_players = {"players": {
    "a-22": {"name": "Rook", "team": "a"},
    "a-23": {"name": "Vet", "team": "a"},
}}
lead_sv = S.leaders(sv_stats, sv_players, key="sv%", n=5)
check(len(lead_sv) == 1 and lead_sv[0]["pid"] == "a-23",
      f"sv%% leaders exclude sub-floor gp: {lead_sv}")

# --- goalie_form ------------------------------------------------------
form = S.goalie_form(sv_stats, "a-23")
check(abs(form["sv%"] - round(550 / 600, 3)) < 1e-9, "goalie_form sv%% correct")
check(abs(form["gaa"] - round((600 - 550) / 20, 2)) < 1e-9, "goalie_form gaa correct")
check(form["so"] == 2, "goalie_form so correct")
check(S.goalie_form(sv_stats, "nobody") == {"sv%": 0.0, "gaa": 0.0, "so": 0},
      "goalie_form defaults for unknown pid")

# --- milestones: every numeral must be groundable in the folded stats ---
NUM_RE = re.compile(r"\d+")


def groundable_numbers(box, stats):
    """Every number that could legitimately appear: any of the 6/7 flat
    stat fields for any player who touches this box (scorer/a1/a2/goalie)."""
    pool = set()
    pids = set()
    for ev in box.get("goals", []):
        for k in ("scorer", "a1", "a2"):
            if ev.get(k):
                pids.add(ev[k])
    for side in ("h", "a"):
        pid = box.get("goalies", {}).get(side)
        if pid:
            pids.add(pid)
    for pid in pids:
        pool.update(stats.get("skaters", {}).get(pid, []))
        pool.update(stats.get("goalies", {}).get(pid, []))
    return pool


milestone_stats = {"schema": 1, "season": 1, "skaters": {}, "goalies": {}}
mrng = random.Random(99)
all_ok = True
total_lines = 0
for i in range(100):
    home, away = ("mtl", "tbr") if i % 2 == 0 else ("tbr", "mtl")
    box = gen_box(mrng, home, away)
    S.fold_box(milestone_stats, box)
    lines = S.milestones(milestone_stats, PLAYERS, box)
    total_lines += len(lines)
    pool = groundable_numbers(box, milestone_stats)
    for line in lines:
        for tok in NUM_RE.findall(line):
            n = int(tok)
            if n not in pool:
                all_ok = False
                print(f"  FAIL: ungroundable number {n} in {line!r} (pool={pool})")

check(all_ok, "every milestone numeral is derivable from post-fold stats")
check(total_lines >= 0, "milestone generation ran without error")

# Force a guaranteed hat trick + shutout to exercise both milestone paths.
forced_stats = {"schema": 1, "season": 1, "skaters": {}, "goalies": {}}
forced_box = {
    "home": "mtl", "away": "tbr", "final": [3, 0], "ot": False, "so": False,
    "goals": [
        {"t": "h", "period": 1, "clock": "1:00", "scorer": "mtl-01",
         "a1": "mtl-02", "a2": None, "str": "EV"},
        {"t": "h", "period": 2, "clock": "2:00", "scorer": "mtl-01",
         "a1": None, "a2": None, "str": "EV"},
        {"t": "h", "period": 3, "clock": "3:00", "scorer": "mtl-01",
         "a1": "mtl-02", "a2": "mtl-03", "str": "EV"},
    ],
    "shots": [30, 20], "goalies": {"h": "mtl-22", "a": "tbr-22"},
    "stars": [], "injuries": [],
}
S.fold_box(forced_stats, forced_box)
check(forced_stats["skaters"]["mtl-01"][1] == 3, "hat-trick scorer has 3 goals")
check(forced_stats["skaters"]["mtl-01"][5] == 1, "hat-trick counter incremented once")
check(forced_stats["skaters"]["mtl-01"][4] == 1, "gwg credited to the tying-breaking goal")
check(forced_stats["goalies"]["mtl-22"][6] == 1, "shutout counted for the home goalie")
forced_lines = S.milestones(forced_stats, PLAYERS, forced_box)
check(any("hat trick" in ln for ln in forced_lines), f"hat trick line present: {forced_lines}")
check(any("shutout" in ln for ln in forced_lines), f"shutout line present: {forced_lines}")
check(any("1st hat trick" in ln for ln in forced_lines), "hat trick ordinal correct (1st)")
check(any("1st shutout" in ln for ln in forced_lines), "shutout ordinal correct (1st)")

# 10th-goal milestone line
tenth_stats = {"skaters": {"mtl-05": [9, 9, 0, 0, 0, 0]}, "goalies": {}}
tenth_box = {
    "home": "mtl", "away": "tbr", "final": [1, 0], "ot": False, "so": False,
    "goals": [{"t": "h", "period": 1, "clock": "1:00", "scorer": "mtl-05",
               "a1": None, "a2": None, "str": "EV"}],
    "shots": [10, 5], "goalies": {"h": "mtl-22", "a": "tbr-22"},
    "stars": [], "injuries": [],
}
S.fold_box(tenth_stats, tenth_box)
check(tenth_stats["skaters"]["mtl-05"][1] == 10, "10th-goal setup correct")
tenth_lines = S.milestones(tenth_stats, PLAYERS, tenth_box)
check(any("10th of the season" in ln for ln in tenth_lines),
      f"round-number goal milestone fires: {tenth_lines}")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
