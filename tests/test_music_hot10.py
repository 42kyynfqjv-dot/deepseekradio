"""HALFWAY HOT 10 chart-sim fixtures (docs/designs/music-halfway.md §2/§4):
determinism, movement rules (debuts/bullets/gainer/droppers/recurrent
retirement), derive-once-store history append-only, catalog schema
round-trip, and artist name-bank disjointness against the other three
canon banks (livegame, statehouse, personas/sponsors).

Run directly (no pytest needed): python3 tests/test_music_hot10.py
"""
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.music import hot10

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------- fixtures

def make_catalog(n_tracks=15, n_artists=3, released="2026-01-01",
                  eligible_from=None, bpm=100, seconds=30):
    """A small synthetic catalog fully under test control (real
    data/music/catalog.json is exercised separately, below, for schema +
    disjointness)."""
    artists = {f"a{i:02d}": {"name": f"Artist {i}", "act": "band",
                             "genre": "test", "blurb": "x", "aired": False}
               for i in range(1, n_artists + 1)}
    tracks = {}
    for i in range(1, n_tracks + 1):
        aid = f"a{((i - 1) % n_artists) + 1:02d}"
        tracks[f"t{i:03d}"] = {
            "title": f"Track {i}", "artist": aid, "genre": "test",
            "bpm": bpm, "seconds": seconds, "released": released,
            "wav": f"music/t{i:03d}.wav", "loudness": None, "peak_dbtp": None,
            "vocal": False, "eligible_from": eligible_from or released,
            "aired": False,
        }
    return {"schema": 1, "artists": artists, "tracks": tracks}


CAT = make_catalog()


# ---------------------------------------------------------------- load_catalog

good = hot10.load_catalog(ROOT / "data" / "music")
check(good.get("schema") == 1, "real catalog.json loads, schema 1")
check(isinstance(good.get("artists"), dict) and isinstance(good.get("tracks"), dict),
      "real catalog.json has artists/tracks dicts")

with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    (tdp / "catalog.json").write_text(json.dumps({"schema": 2, "artists": {}, "tracks": {}}))
    try:
        hot10.load_catalog(tdp)
        check(False, "wrong schema version should raise")
    except ValueError:
        check(True, "wrong schema version raises ValueError")

with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    (tdp / "catalog.json").write_text(json.dumps({"schema": 1, "artists": {}}))
    try:
        hot10.load_catalog(tdp)
        check(False, "missing tracks key should raise")
    except ValueError:
        check(True, "missing tracks key raises ValueError")


# ---------------------------------------------------------------- eligible()

cat = make_catalog(n_tracks=3, released="2026-06-01", eligible_from="2026-06-15")
check(hot10.eligible(cat, "2026-05-25") == [], "eligible: nothing before release")
check(hot10.eligible(cat, "2026-06-08") == [], "eligible: released but before eligible_from")
check(hot10.eligible(cat, "2026-06-15") == ["t001", "t002", "t003"],
      "eligible: on eligible_from date, all present")
check(hot10.eligible(cat, "2026-06-15", retired=frozenset(["t002"])) == ["t001", "t003"],
      "eligible: retired tids excluded")
# a track released later than others never appears before its own release
cat2 = make_catalog(n_tracks=1, released="2026-09-01")
check(hot10.eligible(cat2, "2026-08-01") == [], "eligible: future release excluded")
check(hot10.eligible(cat2, "2026-09-01") == ["t001"], "eligible: exact release date included")


# ---------------------------------------------------------------- determinism

seed = "hot10:1:2026-07-10"
s1 = hot10.score_week(CAT, "t001", "2026-07-10", seed)
s2 = hot10.score_week(CAT, "t001", "2026-07-10", seed)
check(s1 == s2, "score_week: same args -> same value")

r1 = hot10.roll_week(None, CAT, "2026-07-10", seed)
r2 = hot10.roll_week(None, CAT, "2026-07-10", seed)
check(r1 == r2, "roll_week: same args -> byte-identical (deep-equal) chart")
check(json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True),
      "roll_week: JSON-serialized output identical too")

# a different seed produces a different chart (sanity: not a constant stub)
r3 = hot10.roll_week(None, CAT, "2026-07-10", "hot10:1:2026-07-17-different")
check(r1 != r3, "roll_week: different seed -> different chart (not hardcoded)")


# ---------------------------------------------------------------- chart shape

week = "2026-07-10"
rec = hot10.roll_week(None, CAT, week, f"hot10:1:{week}")
check(len(rec["chart"]) == min(hot10.CHART_SIZE, len(hot10.eligible(CAT, week))),
      "chart: exactly CHART_SIZE rows (or fewer if pool smaller)")
ranks = [r["rank"] for r in rec["chart"]]
check(ranks == sorted(ranks) and ranks == list(range(1, len(ranks) + 1)),
      "chart: rank is 1..N contiguous")
pts = [r["pts"] for r in rec["chart"]]
check(pts == sorted(pts, reverse=True), "chart: sorted by pts descending")
check(all(r["debut"] and r["last"] == 0 for r in rec["chart"]),
      "chart: first-ever week, every row is a debut with last=0")
check(rec["hot_shot"] is None, "chart: hot_shot None on a season's very first week")


# ---------------------------------------------------------------- movement rules

def two_week_chart(cat, week1, week2, seed1, seed2):
    w1 = hot10.roll_week(None, cat, week1, seed1)
    w2 = hot10.roll_week(w1, cat, week2, seed2)
    return w1, w2


w1, w2 = two_week_chart(CAT, "2026-07-10", "2026-07-17",
                         "hot10:1:2026-07-10", "hot10:1:2026-07-17")
by_tid_w1 = {r["tid"]: r for r in w1["chart"]}
prev_week_str = hot10._prev_week("2026-07-17")

# bullet is exactly "non-debut AND pts > pts at prev week" (recomputed
# independently via score_week, not read back off w1/w2's own bookkeeping)
for r in w2["chart"]:
    tid = r["tid"]
    if r["debut"]:
        continue
    prev_pts = hot10.score_week(CAT, tid, prev_week_str, "hot10:1:2026-07-17")
    expect_bullet = r["pts"] > prev_pts
    check(r["bullet"] == expect_bullet,
          f"bullet correctness for {tid}: pts={r['pts']} prev={prev_pts} bullet={r['bullet']}")

# debut rows: not present in week1's chart, last=0, weeks=1, peak==rank
debuts_w2 = [r for r in w2["chart"] if r["debut"]]
for r in debuts_w2:
    check(r["tid"] not in by_tid_w1, f"debut {r['tid']} was not on prior chart")
    check(r["last"] == 0, f"debut {r['tid']} last=0")
    check(r["weeks"] == 1, f"debut {r['tid']} weeks=1")
    check(r["peak"] == r["rank"], f"debut {r['tid']} peak==rank on first appearance")

# hot_shot: highest-ranked (min rank number) debut, or None if no debuts
if debuts_w2:
    expect_hs = min(debuts_w2, key=lambda r: r["rank"])["tid"]
    check(w2["hot_shot"] == expect_hs, "hot_shot: highest-ranked debut")
else:
    check(w2["hot_shot"] is None, "hot_shot: None with no debuts")

# continuing (non-debut) rows carry weeks+1, correct last/peak bookkeeping
w2_tids = {r["tid"] for r in w2["chart"]}
for r in w2["chart"]:
    if r["debut"]:
        continue
    prevrow = by_tid_w1[r["tid"]]
    check(r["weeks"] == prevrow["weeks"] + 1, f"{r['tid']} weeks increments")
    check(r["last"] == prevrow["rank"], f"{r['tid']} last == prior week's rank")
    check(r["peak"] == min(r["rank"], prevrow["peak"]), f"{r['tid']} peak is running min")

# droppers: exactly prior-week tids absent from this week
expect_droppers = sorted(t for t in by_tid_w1 if t not in w2_tids)
check(sorted(w2["droppers"]) == expect_droppers, "droppers: prior chart minus this week")

# gainer: the single largest positive week-over-week point gain among
# continuing (non-debut) tracks, or None if nobody gained
gains = []
for r in w2["chart"]:
    if r["debut"]:
        continue
    prev_pts = hot10.score_week(CAT, r["tid"], prev_week_str, "hot10:1:2026-07-17")
    gains.append((r["tid"], r["pts"] - prev_pts))
if gains:
    best_tid, best_gain = max(gains, key=lambda x: x[1])
    expect_gainer = best_tid if best_gain > 0 else None
else:
    expect_gainer = None
check(w2["gainer"] == expect_gainer, f"gainer: correct greatest-gainer tid (got {w2['gainer']!r})")

# history: append-only, this week's pts appended after last week's for every
# charted continuing track; bounded by HISTORY_TAIL
for tid in w2_tids:
    hist = w2["history"][tid]
    row = next(r for r in w2["chart"] if r["tid"] == tid)
    check(hist[-1] == row["pts"], f"history tail for {tid} ends with this week's pts")
    if tid in by_tid_w1:
        prior_hist = w1["history"].get(tid, [])
        check(hist[:-1] == (prior_hist)[-(hot10.HISTORY_TAIL - 1):] or
              hist[:-1] == prior_hist,
              f"history for {tid} extends (not replaces) prior tail")


# ---------------------------------------------------------------- recurrent retirement

def synth_prev(rows):
    """A hand-built prior week-record: only the fields roll_week reads
    (tid/rank/weeks/peak) need to be real."""
    chart_rows = []
    for tid, rank, weeks in rows:
        chart_rows.append({"tid": tid, "rank": rank, "last": rank, "peak": rank,
                            "weeks": weeks, "pts": 1000, "bullet": False, "debut": False})
    return {"schema": 1, "week": "2026-07-03", "season": 1, "chart": chart_rows,
            "hot_shot": None, "droppers": [], "gainer": None, "retired": [],
            "retired_ever": [], "history": {t: [1000] for t, _, _ in rows}}


rcat = make_catalog(n_tracks=15, released="2026-01-01")

# Rule A: weeks>=8 and rank>=6 retires; weeks=7 (one short) does not
prev = synth_prev([("t001", 6, 8), ("t002", 6, 7), ("t003", 5, 8)])
out = hot10.roll_week(prev, rcat, "2026-07-10", "hot10:1:2026-07-10")
check("t001" in out["retired"], "retire rule A: weeks=8,rank=6 retires")
check("t002" not in out["retired"], "retire rule A: weeks=7,rank=6 does not retire")
check("t003" not in out["retired"], "retire rule A: weeks=8,rank=5 (front half) does not retire")

# Rule B: weeks>=12 and rank>=3 retires; weeks=11 does not
prev = synth_prev([("t001", 3, 12), ("t002", 3, 11), ("t003", 2, 12)])
out = hot10.roll_week(prev, rcat, "2026-07-10", "hot10:1:2026-07-10")
check("t001" in out["retired"], "retire rule B: weeks=12,rank=3 retires")
check("t002" not in out["retired"], "retire rule B: weeks=11,rank=3 does not retire")
check("t003" not in out["retired"], "retire rule B: weeks=12,rank=2 (top) does not retire")

# Rule C: weeks>=16 regardless of rank
prev = synth_prev([("t001", 1, 16), ("t002", 1, 15)])
out = hot10.roll_week(prev, rcat, "2026-07-10", "hot10:1:2026-07-10")
check("t001" in out["retired"], "retire rule C: weeks=16 retires even at rank 1")
check("t002" not in out["retired"], "retire rule C: weeks=15 does not retire")

# a retired track is also this week's dropper (matches the doc's own worked
# example, t002 appearing in both droppers and retired the same week) and
# never re-enters (retired_ever carries forward, eligible() excludes it)
prev = synth_prev([("t001", 6, 8)])
out = hot10.roll_week(prev, rcat, "2026-07-10", "hot10:1:2026-07-10")
check("t001" in out["droppers"], "retiree is also this week's dropper")
check("t001" in out["retired_ever"], "retiree tracked in retired_ever")
elig = hot10.eligible(rcat, "2026-08-01", retired=frozenset(out["retired_ever"]))
check("t001" not in elig, "retired track excluded from future eligible pools")

# constants match the doc's own numbers (§4), pinned so a silent drift trips
check((hot10.RETIRE_A_WEEKS, hot10.RETIRE_A_RANK) == (8, 6), "doc constant: rule A (8, rank>=6)")
check((hot10.RETIRE_B_WEEKS, hot10.RETIRE_B_RANK) == (12, 3), "doc constant: rule B (12, rank>=3)")
check(hot10.RETIRE_C_WEEKS == 16, "doc constant: rule C (16 regardless)")
check(hot10.CHART_SIZE == 10, "doc constant: chart is 10 slots")


# ---------------------------------------------------------------- deltas/narrate

d = hot10.deltas(w2)
check(set(d["debuts"]) == {r["tid"] for r in w2["chart"] if r["debut"]}, "deltas: debuts set")
check(set(d["bullets"]) == {r["tid"] for r in w2["chart"] if r["bullet"]}, "deltas: bullets set")
check(d["hot_shot"] == w2["hot_shot"], "deltas: hot_shot passthrough")
check(d["gainer"] == w2["gainer"], "deltas: gainer passthrough")
check(d["droppers"] == w2["droppers"], "deltas: droppers passthrough")

lines = hot10.narrate(w2, CAT)
check(lines[0].startswith("HOT 10 — WEEK OF 2026-07-17"), "narrate: authoritative header")
check(lines[0].endswith("do not change any number):"), "narrate: do-not-alter register")
check(len(lines) >= 1 + len(w2["chart"]), "narrate: one line per charted row plus header")
if w2.get("hot_shot"):
    check(any("HOT SHOT DEBUT:" in ln for ln in lines), "narrate: hot shot debut line present")
if w2.get("droppers"):
    check(any(ln.startswith("DROPPED OUT:") for ln in lines), "narrate: dropped-out line present")


# ---------------------------------------------------------------- derive-once-store / history append-only

with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    week_a, week_b = "2026-07-10", "2026-07-17"
    rec_a = hot10.chart(week_a, CAT, tdp)
    rec_b = hot10.chart(week_b, CAT, tdp)
    check(rec_a["week"] == week_a and rec_b["week"] == week_b,
          "chart(): stores each week under its own key")

    # aired week is read-only canon: re-requesting returns the EXACT stored
    # record, unaffected by a mutated catalog or changed scoring constants
    mutated_cat = json.loads(json.dumps(CAT))
    mutated_cat["tracks"]["t001"]["title"] = "RETRO-EDITED TITLE"
    orig_spin_w = hot10.SPIN_W
    hot10.SPIN_W = 999.0
    try:
        rec_a_again = hot10.chart(week_a, mutated_cat, tdp)
    finally:
        hot10.SPIN_W = orig_spin_w
    check(rec_a_again == rec_a,
          "chart(): stored week never re-derived, even with a changed catalog/constants")

    # shard file itself: week_a's stored bytes are untouched after week_b lands
    shard = json.loads((tdp / "hot10-s1.json").read_text())
    check(shard["weeks"][week_a] == rec_a, "shard: week_a entry intact after week_b append")
    check(set(shard["weeks"]) == {week_a, week_b}, "shard: both weeks present, none dropped")

    # missing/lost shard re-derives deterministically from the same seed
    (tdp / "hot10-s1.json").unlink()
    rec_a_rederived = hot10.chart(week_a, CAT, tdp)
    check(rec_a_rederived == rec_a, "chart(): lost shard re-derives byte-identical week")

    # gap backfill: request week 3 directly on a fresh root; week 2 gets
    # silently derived first so week 3's `prev`/history is correct
    with tempfile.TemporaryDirectory() as td2:
        tdp2 = Path(td2)
        week_c = "2026-07-24"
        rec_c = hot10.chart(week_c, CAT, tdp2)
        shard2 = json.loads((tdp2 / "hot10-s1.json").read_text())
        check({week_a, week_b, week_c} <= set(shard2["weeks"]),
              "chart(): gap backfill computes intermediate weeks too")
        rec_b_direct = hot10.chart(week_b, CAT, tdp)
        check(rec_c["chart"] and rec_b_direct["chart"], "sanity: both weeks produced rows")
        # history for a track continuing into week_c reflects week_a AND
        # week_b's points, in order (append-only, never rewritten)
        continuing = [r["tid"] for r in rec_c["chart"] if not r["debut"]
                      and r["tid"] in {x["tid"] for x in rec_b_direct["chart"]}]
        for tid in continuing[:3]:
            hist = rec_c["history"][tid]
            check(len(hist) >= 1, f"history present for continuing {tid}")


# ---------------------------------------------------------------- season boundary

check(hot10._season_of("2026-07-10") == 1, "season 1 starts on SEASON0_START")
late_week = hot10._Date.fromisoformat(hot10.SEASON0_START)
late_week = (late_week.replace(year=late_week.year + 1)).isoformat()
check(hot10._season_of(late_week) >= 2, "season rolls over after WEEKS_PER_SEASON weeks")


# ================================================================
# catalog.json — schema + name-bank disjointness (component A)
# ================================================================

CATALOG = hot10.load_catalog(ROOT / "data" / "music")
artists = CATALOG["artists"]
tracks = CATALOG["tracks"]

check(CATALOG["schema"] == 1, "catalog: schema == 1")
check(40 <= len(tracks) <= 60, f"catalog: 40-60 tracks total (got {len(tracks)})")
check(len(artists) == 14, f"catalog: 14 acts (got {len(artists)})")

ARTIST_KEYS = {"name", "act", "genre", "blurb", "aired"}
for aid, a in artists.items():
    check(ARTIST_KEYS <= set(a.keys()), f"artist {aid}: has all required keys")
    check(isinstance(a["name"], str) and a["name"], f"artist {aid}: non-empty name")

TRACK_KEYS = {"title", "artist", "genre", "bpm", "seconds", "released", "wav",
              "loudness", "peak_dbtp", "vocal", "eligible_from", "aired"}
per_artist_count = {}
for tid, t in tracks.items():
    check(TRACK_KEYS <= set(t.keys()), f"track {tid}: has all required keys")
    check(t["artist"] in artists, f"track {tid}: artist {t['artist']!r} exists")
    check(t["vocal"] is False, f"track {tid}: vocal flag is False (shipping default, §1/§2)")
    check(0 < t["seconds"] <= 47, f"track {tid}: seconds <=47 (Stable Audio Open's hard cap)")
    check(t["wav"] == f"music/{tid}.wav", f"track {tid}: wav path matches its tid")
    check(t["eligible_from"] >= t["released"],
          f"track {tid}: eligible_from not before released")
    hot10._Date.fromisoformat(t["released"])   # raises if malformed
    hot10._Date.fromisoformat(t["eligible_from"])
    check(True, f"track {tid}: released/eligible_from are ISO-parseable dates")
    per_artist_count[t["artist"]] = per_artist_count.get(t["artist"], 0) + 1

# §2's "2-5 each" is the general guideline; act a10 (Exit 4) is documented
# in the very same table with an explicit gag overriding it -- "An offramp
# that was never built, in SIX movements" -- so 6 is canon for that one act,
# not a data bug. The specific table entry wins over the general rule.
SIX_MOVEMENT_EXCEPTIONS = {aid for aid, a in artists.items()
                           if "six movements" in a.get("blurb", "").lower()}
check(SIX_MOVEMENT_EXCEPTIONS, "fixture: the six-movements gag act is present in catalog")
for aid in artists:
    n = per_artist_count.get(aid, 0)
    lo, hi = 2, (6 if aid in SIX_MOVEMENT_EXCEPTIONS else 5)
    check(lo <= n <= hi, f"artist {aid}: {lo}-{hi} tracks (got {n}, §2)")

# tids/titles unique
check(len(set(tracks)) == len(tracks), "catalog: track ids unique")
titles = [t["title"] for t in tracks.values()]
check(len(set(titles)) == len(titles), "catalog: track titles unique")


# --------------------------------------------- name-bank disjointness

def _bank_tokens_from_split(src_text, varname):
    m = re.search(varname + r"\s*=\s*\(([^)]*)\)", src_text, re.S)
    parts = re.findall(r'"([^"]*)"', m.group(1))
    return " ".join(parts).split()


livegame_src = (ROOT / "src" / "livegame.py").read_text()
LIVEGAME_FIRST = _bank_tokens_from_split(livegame_src, "FIRST_NAMES")
LIVEGAME_LAST = _bank_tokens_from_split(livegame_src, "LAST_NAMES")

members_src = (ROOT / "src" / "statehouse" / "members.py").read_text()
MEMBER_FIRST = _bank_tokens_from_split(members_src, "MEMBER_FIRST")
MEMBER_LAST = _bank_tokens_from_split(members_src, "MEMBER_LAST")

elections_src = (ROOT / "src" / "statehouse" / "elections.py").read_text()
m = re.search(r"_FIRST\s*=\s*\(([^)]*)\)", elections_src, re.S)
ELECTIONS_FIRST = re.findall(r'"([^"]*)"', m.group(1))
m = re.search(r"_LAST\s*=\s*\(([^)]*)\)", elections_src, re.S)
ELECTIONS_LAST = re.findall(r'"([^"]*)"', m.group(1))

PERSONAS = [p.stem for p in (ROOT / "personas").glob("*.md")]

bible_text = (ROOT / "station" / "bible.md").read_text()
SPONSOR_NAMES = re.findall(r"^\s*-\s*\*([^*]+)\*\s*—", bible_text, re.M)
check(len(SPONSOR_NAMES) >= 35, f"fixture: sponsor roster parsed (~40, got {len(SPONSOR_NAMES)})")

FIRST_BANK_TOKENS = {w.lower() for w in LIVEGAME_FIRST + MEMBER_FIRST + ELECTIONS_FIRST}
LAST_BANK_TOKENS = {w.lower() for w in LIVEGAME_LAST + MEMBER_LAST + ELECTIONS_LAST}
ALL_NAME_TOKENS = FIRST_BANK_TOKENS | LAST_BANK_TOKENS
PERSONA_TOKENS = {p.lower() for p in PERSONAS}
SPONSOR_FULL = {s.lower() for s in SPONSOR_NAMES}

ARTIST_NAMES = [a["name"] for a in artists.values()]

# 1. No artist/act name exactly equals a persona name or a sponsor name.
for name in ARTIST_NAMES:
    check(name.lower() not in PERSONA_TOKENS, f"artist {name!r}: not a persona name")
    check(name.lower() not in SPONSOR_FULL, f"artist {name!r}: not a sponsor name")

# 2. No artist name is a literal (first-bank-token, last-bank-token) pair
#    that livegame/statehouse code could actually generate — i.e. both
#    halves of a two-word act name simultaneously sitting in a FIRST bank
#    and a LAST bank (the real collision risk: a random hockey player or
#    statehouse member minted with the exact same full name).
for name in ARTIST_NAMES:
    toks = name.replace("The ", "").split()
    if len(toks) == 2:
        first, last = toks[0].lower(), toks[1].lower()
        collision = first in FIRST_BANK_TOKENS and last in LAST_BANK_TOKENS
        check(not collision,
              f"artist {name!r}: first+last not both in a generator's name pool "
              f"(no exact collision is producible)")

# 3. Solo acts' personal names avoid all four banks *entirely*, token by
#    token (design §2: "Personal names of solo acts avoid all four banks
#    entirely" — the strictest bar, since these are named individuals).
SOLO_ACT_IDS = [aid for aid, a in artists.items() if a.get("act") == "solo"]
check(len(SOLO_ACT_IDS) >= 2, "fixture: at least the two documented solo acts present")
for aid in SOLO_ACT_IDS:
    name = artists[aid]["name"]
    for tok in name.split():
        low = tok.lower()
        check(low not in ALL_NAME_TOKENS,
              f"solo act {name!r}: token {tok!r} absent from livegame/statehouse name banks")
        check(low not in PERSONA_TOKENS, f"solo act {name!r}: token {tok!r} not a persona")
        check(not any(low in s.lower().split() for s in SPONSOR_NAMES),
              f"solo act {name!r}: token {tok!r} not a sponsor-name word")

print(f"\nmusic_hot10 {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
