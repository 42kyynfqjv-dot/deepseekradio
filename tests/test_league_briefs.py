"""League briefs fixtures: the reveal clock never regresses and agrees with
itself across the intermission sheet, every sheet renders its four/QUOTE-
GROUNDING blocks from the facts handed to it, and (G3) booth-style lines
quoting every sheet pass BOTH scoreguard and nameguard with zero
replacements.

Run directly (no pytest needed):  python3 tests/test_league_briefs.py
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.league import briefs as B
from src.scoreguard import build_facts, enforce_scoreboard
from src.nameguard import enforce_names
from src.livegame import FIRST_NAMES, LAST_NAMES

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


POOL = frozenset(w.lower() for w in FIRST_NAMES + LAST_NAMES)


def L(text):
    return {"speaker": "Walt Fontaine", "voice": "am_onyx", "speed": 0.97,
            "text": text}


# ============================================================ fixtures ====
# A synthetic v2 world: two full dressed rosters (dress()'s frozen shape --
# 18 skaters + goalie + backup, parallel `ids`), a players sidecar body, a
# stats sidecar, an out2 injury table, and boxes for "tonight's" broadcast
# game plus one "other" completed game the intermission/scores desk narrate.

def _names(rng, n):
    used, out = set(), []
    while len(out) < n:
        nm = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        if nm not in used:
            used.add(nm)
            out.append(nm)
    return out


_RNG = random.Random("briefs-fixture")
_HOME_NAMES = _names(_RNG, 20)   # 18 skaters + G1 + G2
_AWAY_NAMES = _names(_RNG, 20)
_SLOTS = (["F1"] * 3 + ["F2"] * 3 + ["F3"] * 3 + ["F4"] * 3
          + ["D1"] * 2 + ["D2"] * 2 + ["D3"] * 2)


def _mkteam(key, names):
    skaters = names[:18]
    ids = [f"{key}-{i:02d}" for i in range(1, 19)]
    goalie, backup = names[18], names[19]
    g_id, b_id = f"{key}-g1", f"{key}-g2"
    roster = {"skaters": skaters, "goalie": goalie, "ids": ids,
              "weights": [1.0] * 18, "backup": backup}
    plook = {}
    for pid, nm, slot in zip(ids, skaters, _SLOTS):
        plook[pid] = {"name": nm, "team": key,
                      "pos": "D" if slot[0] == "D" else "F", "slot": slot}
    plook[g_id] = {"name": goalie, "team": key, "pos": "G", "slot": "G1"}
    plook[b_id] = {"name": backup, "team": key, "pos": "G", "slot": "G2"}
    return roster, plook, g_id, b_id


HOME_R, HOME_PL, HOME_GID, HOME_BID = _mkteam("mtl", _HOME_NAMES)
AWAY_R, AWAY_PL, AWAY_GID, AWAY_BID = _mkteam("nyg", _AWAY_NAMES)
PLAYERS = {"players": {**HOME_PL, **AWAY_PL}}

GAME = {
    "game_no": 12, "date": "2026-07-11", "season": 1, "rivalry": False,
    "home": "Montreal Apologies", "away": "New York Gridlock",
    "home_key": "mtl", "away_key": "nyg", "arena": "the Pardon Centre",
    "rosters": {"home": HOME_R, "away": AWAY_R},
    "refs": ["Referee Ada Cole", "Referee Bo Iyer"],
}
PBP = {"speaker": "Walt Fontaine", "voice": "am_onyx", "speed": 0.97}

S1, S2, S3 = HOME_R["ids"][0], HOME_R["ids"][1], AWAY_R["ids"][0]
STATS = {
    "skaters": {
        S1: [40, 22, 18, 10, 5, 2],   # 40 pts -- league leader
        S2: [40, 18, 10, 4, 2, 0],    # 18 g -- 2 short of a 20-goal milestone
        S3: [38, 15, 12, 6, 1, 0],
    },
    "goalies": {
        HOME_GID: [30, 18, 8, 3, 900, 830, 3],
        AWAY_GID: [28, 14, 10, 2, 850, 770, 1],
    },
}
OUT2 = {
    HOME_R["ids"][17]: {"until": "2026-07-19", "note": "week-to-week, lower body",
                        "games": 3, "ir": True},
}

BOX_TONIGHT = {
    "home": GAME["home"], "away": GAME["away"], "final": [3, 1],
    "ot": False, "so": False,
    "goals": [
        {"t": "h", "period": 1, "clock": "5:00", "scorer": S1,
         "a1": HOME_R["ids"][2], "a2": None, "str": "EV"},
        {"t": "a", "period": 2, "clock": "10:15", "scorer": S3,
         "a1": None, "a2": None, "str": "PP"},
        {"t": "h", "period": 2, "clock": "14:40", "scorer": S1,
         "a1": HOME_R["ids"][2], "a2": HOME_R["ids"][3], "str": "EV"},
        {"t": "h", "period": 3, "clock": "18:00", "scorer": HOME_R["ids"][4],
         "a1": None, "a2": None, "str": "EN"},
    ],
    "shots": [30, 24], "goalies": {"h": HOME_GID, "a": AWAY_GID},
    "stars": [HOME_PL[S1]["name"], HOME_R["goalie"], AWAY_PL[S3]["name"]],
    "injuries": [],
}
FINAL = {"h": 3, "a": 1, "ot": False, "so": False,
         "stars": BOX_TONIGHT["stars"], "shots": BOX_TONIGHT["shots"],
         "out": [[], []]}

BOX_OTHER = {
    "home": GAME["home"], "away": GAME["away"], "final": [2, 1],
    "ot": False, "so": False,
    "goals": [
        {"t": "h", "period": 1, "clock": "8:00", "scorer": S2,
         "a1": None, "a2": None, "str": "EV"},
        {"t": "h", "period": 2, "clock": "9:30", "scorer": S2,
         "a1": None, "a2": None, "str": "EV"},
        {"t": "a", "period": 3, "clock": "2:00", "scorer": S3,
         "a1": None, "a2": None, "str": "EV"},
    ],
    "shots": [28, 22], "goalies": {"h": HOME_GID, "a": AWAY_GID},
    "stars": [HOME_PL[S2]["name"], HOME_R["goalie"], AWAY_PL[S3]["name"]],
    "injuries": [],
}
BOXES = [BOX_OTHER]


# ======================================================= reveal() unit ====
BOX_R = {
    "home": "tbr", "away": "hfx", "final": [3, 1], "ot": False, "so": False,
    "goals": [
        {"t": "h", "period": 1, "clock": "5:00", "scorer": "tbr-01",
         "a1": "tbr-02", "a2": None, "str": "EV"},
        {"t": "a", "period": 1, "clock": "15:30", "scorer": "hfx-01",
         "a1": None, "a2": None, "str": "PP"},
        {"t": "h", "period": 2, "clock": "10:00", "scorer": "tbr-03",
         "a1": "tbr-01", "a2": "tbr-02", "str": "EV"},
        {"t": "h", "period": 3, "clock": "18:45", "scorer": "tbr-01",
         "a1": None, "a2": None, "str": "EN"},
    ],
    "shots": [31, 27], "goalies": {"h": "tbr-22", "a": "hfx-22"},
    "stars": ["tbr-01", "tbr-22", "hfx-01"], "injuries": [],
}
START = 600

r0 = B.reveal(BOX_R, START, 0)
check(r0["status"] == "upcoming" and r0["score"] == [0, 0],
      f"reveal upcoming before puck drop, got {r0}")

rmid = B.reveal(BOX_R, START, START + 1800)
check(rmid["status"] == "live", f"reveal live mid-game, got {rmid}")
check(rmid["score"] == [2, 1], f"reveal live score matches goals-so-far, got {rmid}")
check(rmid["period"] == 2 and rmid["clock"] == "10:00",
      f"reveal live period/clock, got {rmid}")

rend = B.reveal(BOX_R, START, START + 100000)
check(rend["status"] == "final" and rend["score"] == BOX_R["final"],
      f"reveal final equals box final, got {rend}")

RANK = {"upcoming": 0, "live": 1, "final": 2}
prev_score, prev_rank, mono_ok = [0, 0], 0, True
for t in range(0, 6000, 37):
    r = B.reveal(BOX_R, START, t)
    rank = RANK[r["status"]]
    if (rank < prev_rank or r["score"][0] < prev_score[0]
            or r["score"][1] < prev_score[1]):
        mono_ok = False
        print(f"  !! regression at t={t}: {r}")
    prev_rank, prev_score = rank, r["score"]
check(mono_ok, "reveal monotonic: status/score never regress as cursor grows")

BOX_OT = dict(BOX_R, ot=True, so=False, final=[4, 3],
              goals=BOX_R["goals"] + [{"t": "h", "period": "OT", "clock": "2:15",
                                       "scorer": "tbr-01", "a1": None,
                                       "a2": None, "str": "EV"}])
r_ot = B.reveal(BOX_OT, START, START + 100000)
check(r_ot["status"] == "final" and r_ot["score"] == [4, 3],
      f"reveal OT final equals box final, got {r_ot}")
check(r_ot["period"] == "OT", f"reveal OT final period tagged OT, got {r_ot}")

BOX_SO = {"home": "tbr", "away": "hfx", "final": [2, 1], "ot": False, "so": True,
          "goals": [
              {"t": "h", "period": 1, "clock": "5:00", "scorer": "tbr-01",
               "a1": None, "a2": None, "str": "EV"},
              {"t": "a", "period": 2, "clock": "10:00", "scorer": "hfx-01",
               "a1": None, "a2": None, "str": "EV"},
          ]}
r_so_mid = B.reveal(BOX_SO, 0, B.REG_SECS + B.OT_SECS + 1)
check(r_so_mid["status"] == "live" and r_so_mid["score"] == [1, 1],
      f"reveal stays live+tied through the shootout window, got {r_so_mid}")
r_so_final = B.reveal(BOX_SO, 0, B.REG_SECS + B.OT_SECS + B.SO_SECS + 1)
check(r_so_final["status"] == "final" and r_so_final["score"] == [2, 1],
      f"reveal SO final adds the shootout winner beyond the live tally, got {r_so_final}")


# ================================================= intermission_sheet ====
so_off = B._start_off("2026-07-10", GAME["home"], GAME["away"])

sheet_early = B.intermission_sheet("2026-07-10", 0, BOXES, STATS, PLAYERS)
expect_early = B.reveal(BOX_OTHER, so_off, 0)
check(sheet_early["around"][0]["status"] == expect_early["status"]
      and sheet_early["around"][0]["score"] == expect_early["score"],
      "intermission around-row cross-checks reveal() directly at the same cursor")

sheet = B.intermission_sheet("2026-07-10", 20000, BOXES, STATS, PLAYERS)
check(set(sheet) == {"around", "leaders", "race_note"}, "intermission sheet keys")
check(len(sheet["around"]) == 1, "one around row per box")
row = sheet["around"][0]
check(row["status"] == "final", f"far-future cursor reveals final, got {row}")
check(row["score"] == [2, 1], f"around row score matches box final, got {row}")
check(f"{HOME_PL[S2]['name']} twice" in row["scorers"],
      f"around row names a repeat scorer, got {row['scorers']}")
check(sheet["leaders"][0]["name"] == HOME_PL[S1]["name"],
      "intermission leaders sorted desc by points")
check(HOME_PL[S1]["name"] in sheet["race_note"], "race note names the scoring leader")


# ======================================================== scores_desk ====
desk_txt = B.scores_desk("2026-07-10", BOXES, PLAYERS, n=5)
check("Last night in the league" in desk_txt, "scores_desk lede present")
check(f"{HOME_PL[S2]['name']} twice" in desk_txt,
      "scores_desk names the repeat scorer with a count")
check(GAME["home"] in desk_txt and GAME["away"] in desk_txt,
      "scores_desk names both teams")

desk_empty = B.scores_desk("2026-07-10", BOXES, PLAYERS, n=0)
check(desk_empty.startswith("No other league games"), "scores_desk n=0 empty")


# ======================================================= pregame_blocks ====
pre_txt = B.pregame_blocks(GAME, PLAYERS, STATS, OUT2)
check("LINES:" in pre_txt, "pregame has LINES block")
check("INJURY REPORT:" in pre_txt, "pregame has INJURY REPORT block")
check("LEADERS:" in pre_txt, "pregame has LEADERS block")
check("MILESTONE WATCH:" in pre_txt, "pregame has MILESTONE WATCH block")
check(HOME_PL[HOME_R["ids"][17]]["name"] in pre_txt,
      "pregame injury report names the injured player")
check(HOME_PL[S1]["name"] in pre_txt, "pregame leaders names the points leader")
check(HOME_PL[S2]["name"] in pre_txt,
      "pregame milestone watch names the near-threshold skater")
check(GAME["home"] in pre_txt and GAME["away"] in pre_txt,
      "pregame lines block names both teams")


# =============================================== postgame_quote_grounding ====
post_txt = B.postgame_quote_grounding(GAME, FINAL, BOX_TONIGHT, STATS)
check("QUOTE GROUNDING:" in post_txt, "postgame has QUOTE GROUNDING label")
check("Goals:" in post_txt and HOME_PL[S1]["name"] in post_txt,
      "postgame goal list names a scorer")
check("Saves:" in post_txt and HOME_R["goalie"] in post_txt,
      "postgame save counts name a goalie")
check("Season lines:" in post_txt and HOME_PL[S1]["name"] in post_txt,
      "postgame season line names a star")
check(f"{HOME_R['goalie']} is" in post_txt,
      "postgame season line grounds the winning goalie's record")


# ============================================================== G3 CI ====
# Booth-style lines quoting each sheet must trip neither guard. Structural
# labels ("LINES:", "INJURY REPORT:", ...) are formatting for the brief,
# not dialogue -- stripped before quoting, exactly as season.py's existing
# pregame_brief phrases injuries ("back in the lineup") rather than reading
# its own headers aloud.
_LABELS = ("LINES:", "INJURY REPORT:", "LEADERS:", "MILESTONE WATCH:",
           "QUOTE GROUNDING:", "Goals:", "Saves:", "Season lines:")


def _strip_label(line):
    s = line.strip()
    for pfx in _LABELS:
        if s.startswith(pfx):
            return s[len(pfx):].strip()
    return s


def _lines_from(text):
    out = []
    for raw in text.split("\n"):
        content = _strip_label(raw)
        if not content:
            continue
        for clause in content.split(";"):
            clause = clause.strip()
            if clause:
                out.append(L(clause))
    return out


def _guard_clean(name, lines, facts):
    out1 = enforce_scoreboard(lines, facts)
    out2 = enforce_names(out1, facts, extra_ok=POOL)
    bad = [o for o in out2 if o.get("_enforced")]
    check(not bad, f"G3 {name} triggers zero guard replacements (bad={bad})")


facts_pre = build_facts(GAME, [], None, mode="neutral", pbp=PBP, period=None)
_guard_clean("pregame_blocks", _lines_from(pre_txt), facts_pre)

facts_post = build_facts(GAME, [], None, mode="postgame", pbp=PBP,
                          final=(3, 1), period=None)
_guard_clean("postgame_quote_grounding", _lines_from(post_txt), facts_post)

facts_other = build_facts(GAME, [], None, mode="neutral", pbp=PBP,
                          final=tuple(BOX_OTHER["final"]), period=None)
_guard_clean("scores_desk", _lines_from(desk_txt), facts_other)


def _render_row(row):
    tag = " (OT)" if row.get("ot") else ""
    tail = f" — {', '.join(row['scorers'])}" if row["scorers"] else ""
    return f"{row['away']} {row['score'][1]}, {row['home']} {row['score'][0]}{tag}{tail}"


inter_lines = [L(_render_row(row)), L(sheet["race_note"])]
_guard_clean("intermission_sheet", inter_lines, facts_other)


print(f"\nleague_briefs {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
