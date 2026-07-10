"""League playoffs: seed the 16-team bracket, schedule tonight's playoff
slate, fold results in, and report the champion.

Format (minimal §13 / grounding, frozen): top 3 of each of the 4 divisions
(12) + 2 wild cards per conference (4) = 16 qualifiers. Fixed bracket, no
reseeding after round 1: division winner A1 (the better-seeded of the
conference's two division winners) plays the weaker wild card (WC2); the
other division winner B1 plays the stronger wild card (WC1); the #2 and #3
seeds meet within their own division. Round 2 pairs winners within the same
conference/division bracket group (never a full-conference reseed). Round 3
is the conference final; round 4 is the Cup final (East champ vs West
champ). All rounds best-of-7, home ice 2-2-1-1-1, home ice awarded to
whichever of the two combatants is higher by the tiebreak chain at the
moment the series is formed (recomputed fresh each round — "no reseeding"
governs bracket STRUCTURE, i.e. who plays whom, not which of the two
already-paired teams hosts).

Tiebreak chain (frozen): pts% -> RW -> ROW -> W -> H2H. pts% is derived
from the standings dict's w/otl/gp (points = 2w + otl, matching v1's
loser-point OT/SO allocation); RW/ROW/W read straight off the dict. H2H has
no data source anywhere in the frozen schemas (the standings dict carries
no game log or matchup matrix, and this is a leaf module that may not
import season.py to go get one), so it is wired as an optional callable
hook `h2h(team_a, team_b) -> team_a | team_b | None` — only ever invoked
when pts%/RW/ROW/W are IDENTICAL, and if it returns None (or is omitted)
the chain falls back to alphabetical team code, a deterministic tie-break
of last resort so seeding never depends on dict iteration order.

SCHEMA FRICTION (reported, not improvised around): `seed_bracket`'s only
input per minimal §3 is the flat standings dict (team -> w/l/otl/streak/
gp/rw/row) — it carries no division/conference membership. Division
structure is therefore a private constant duplicated here from season.py's
`LEAGUE` (this module may not import season.py, per the component rules).
It MUST be kept byte-identical to season.py's `LEAGUE` if that ever changes
membership — there is no schema-level mechanism to keep the two in sync.

Bracket dict shape (this module's own state; persisted by the caller at
`data/league/playoffs-s{n}.json` per minimal §13):
  {"conferences": {conf: {"top_div","alt_div","top":[a1,a2,a3],
                          "alt":[b1,b2,b3],"wc1","wc2"}},
   "series": {slot: {"conf","round","slot","higher","lower",
                     "wins":{team:int},"games":[{"home","away","final"}],
                     "winner": str|None}},
   "champion": str|None,
   "_last_played": {slot: "YYYY-MM-DD"}}   # schedule_series's own cadence ledger

Series slots: round 1 = "{conf}-A-1" (top div winner vs weaker wild card),
"{conf}-A-2" (top div #2 vs #3), "{conf}-B-1" (alt div winner vs stronger
wild card), "{conf}-B-2" (alt div #2 vs #3). Round 2 = "{conf}-A" (winner of
A-1 vs winner of A-2), "{conf}-B". Round 3 = "{conf}" (conference final).
Round 4 = "CUP". Later-round series are created lazily, the instant both of
their prerequisite series report a winner — so the two conferences (and the
two division brackets within a conference) advance independently, exactly
like real playoff hockey, with no artificial global "round" gate.
"""
from __future__ import annotations

from datetime import date as _date
from functools import cmp_to_key

# Mirrors season.py's LEAGUE exactly (duplicated; see friction note above).
LEAGUE = {
    "Eastern": {
        "Boreal": ["mtl", "tbr", "hfx", "trr", "gan", "bur", "pmc", "stj"],
        "Gridiron": ["nyg", "yon", "uti", "sch", "alb", "scr", "bal", "rich"],
    },
    "Western": {
        "Prairie": ["ssk", "wpg", "mjm", "reg", "bra", "far", "bis", "dul"],
        "Pacific": ["vic", "kam", "spo", "eug", "bak", "fre", "tuc", "boi"],
    },
}

HOME_PATTERN = "HHAAHAH"  # 2-2-1-1-1, indexed by (game_number - 1)


def _pts(rec: dict) -> int:
    return 2 * rec.get("w", 0) + rec.get("otl", 0)


def _tiebreak_key(team: str, standings: dict) -> tuple:
    rec = standings[team]
    gp = max(rec.get("gp", 0), 1)
    pts_pct = _pts(rec) / (2 * gp)
    return (pts_pct, rec.get("rw", 0), rec.get("row", 0), rec.get("w", 0))


def _cmp(a: str, b: str, standings: dict, h2h) -> int:
    """-1 if a ranks ahead of b, +1 if behind, 0 only if truly inseparable
    (never happens once the alphabetical last-resort fires)."""
    ka, kb = _tiebreak_key(a, standings), _tiebreak_key(b, standings)
    if ka != kb:
        return -1 if ka > kb else 1
    if h2h is not None:
        res = h2h(a, b)
        if res == a:
            return -1
        if res == b:
            return 1
    if a != b:
        return -1 if a < b else 1
    return 0


def _rank(teams: list, standings: dict, h2h) -> list:
    return sorted(teams, key=cmp_to_key(lambda a, b: _cmp(a, b, standings, h2h)))


def _make_series(a: str, b: str, standings: dict, h2h, conf: str, rnd: int,
                  slot: str) -> dict:
    higher, lower = (a, b) if _cmp(a, b, standings, h2h) <= 0 else (b, a)
    return {"conf": conf, "round": rnd, "slot": slot,
            "higher": higher, "lower": lower,
            "wins": {higher: 0, lower: 0}, "games": [], "winner": None}


def seed_bracket(standings: dict, h2h=None) -> dict:
    """Seed the 16-team playoff bracket from the standings dict.

    `standings` is `season.json["league"]`: team -> {w,l,otl,streak,gp,rw,
    row}. `h2h` is the optional tiebreak-of-last-resort callable (see module
    docstring) — omit it and ties fall back to alphabetical team code.

    -> {"conferences": {...}, "series": {...round-1 4 series/conf...},
        "champion": None}
    """
    conferences = {}
    for cname, divs in LEAGUE.items():
        div_names = list(divs.keys())
        top3, remainder = {}, []
        for dname in div_names:
            ranked = _rank(list(divs[dname]), standings, h2h)
            top3[dname] = ranked[:3]
            remainder.extend(ranked[3:])
        d_a, d_b = div_names
        top_div, alt_div = (
            (d_a, d_b) if _cmp(top3[d_a][0], top3[d_b][0], standings, h2h) <= 0
            else (d_b, d_a)
        )
        wc1, wc2 = _rank(remainder, standings, h2h)[:2]
        conferences[cname] = {
            "top_div": top_div, "alt_div": alt_div,
            "top": top3[top_div], "alt": top3[alt_div],
            "wc1": wc1, "wc2": wc2,
        }

    series = {}
    for cname, c in conferences.items():
        a1, a2, a3 = c["top"]
        b1, b2, b3 = c["alt"]
        series[f"{cname}-A-1"] = _make_series(a1, c["wc2"], standings, h2h,
                                               cname, 1, f"{cname}-A-1")
        series[f"{cname}-A-2"] = _make_series(a2, a3, standings, h2h,
                                               cname, 1, f"{cname}-A-2")
        series[f"{cname}-B-1"] = _make_series(b1, c["wc1"], standings, h2h,
                                               cname, 1, f"{cname}-B-1")
        series[f"{cname}-B-2"] = _make_series(b2, b3, standings, h2h,
                                               cname, 1, f"{cname}-B-2")

    return {"conferences": conferences, "series": series, "champion": None}


def _active_series(bracket: dict):
    return {sid: s for sid, s in bracket["series"].items() if s["winner"] is None}


def _game_home_away(s: dict, game_no: int) -> tuple:
    pat = HOME_PATTERN[min(game_no, 7) - 1]
    return (s["higher"], s["lower"]) if pat == "H" else (s["lower"], s["higher"])


def schedule_series(bracket: dict, date: str, tracked) -> list:
    """Tonight's playoff slate.

    `tracked` — iterable/set of team codes whose EVERY playoff game airs
    live (once a tracked team is in, every one of its games is a broadcast,
    unlike the 2x/week regular season) — those series are pinned to Wed/Sat
    with the documented +-1 day of slip if that cadence has stalled.
    Off-air series (neither combatant tracked) run every 2 days. Cadence is
    tracked in `bracket["_last_played"]` (this call's own side effect —
    `schedule_series` both returns tonight's slate and advances that
    ledger, mirroring `fold_playoff`'s in-place-mutation contract).

    -> [{"home","away","playoff": {"round","game","series":[h_wins,a_wins]}}]
    """
    d = _date.fromisoformat(date)
    last_played = bracket.setdefault("_last_played", {})
    tracked = set(tracked or ())
    slate = []
    for sid, s in _active_series(bracket).items():
        is_tracked = bool({s["higher"], s["lower"]} & tracked)
        last = last_played.get(sid)
        gap = None if last is None else (d - _date.fromisoformat(last)).days
        wd = d.weekday()  # Mon=0 .. Sun=6; Wed=2, Sat=5
        on_target = wd in (2, 5)
        on_slip = wd in (1, 3, 4, 6)  # +-1 day of Wed/Sat
        if is_tracked:
            # Even game 1 waits for an air night — a tracked team's every
            # playoff game is a broadcast, none pre-empt the Wed/Sat slot.
            # The +-1 slip is a genuine-stall escape hatch only (gap>=5 is
            # already a full missed cycle — Wed/Sat gaps are naturally 3-4)
            # so normal cadence never touches a non-Wed/Sat day.
            due = on_target if last is None else (
                (gap >= 2 and on_target) or (gap >= 5 and on_slip))
        else:
            due = True if last is None else gap >= 2
        if not due:
            continue
        game_no = len(s["games"]) + 1
        home, away = _game_home_away(s, game_no)
        slate.append({
            "home": home, "away": away,
            "playoff": {"round": s["round"], "game": game_no,
                        "series": [s["wins"][home], s["wins"][away]]},
        })
        last_played[sid] = date
    return slate


def _try_build(bracket: dict, slot: str, feeder_a: str, feeder_b: str,
                rnd: int, conf: str) -> None:
    if slot in bracket["series"]:
        return
    sa, sb = bracket["series"].get(feeder_a), bracket["series"].get(feeder_b)
    if sa is None or sb is None or sa["winner"] is None or sb["winner"] is None:
        return
    # Home ice for the new round is recomputed from the two winners'
    # standing — but no live standings dict is available this deep
    # (fold_playoff never receives one), so we build a synthetic
    # comparison dict: a team that was the higher seed in its own prior
    # series stays higher. See `_synthetic_rank`.
    winner_a, winner_b = sa["winner"], sb["winner"]
    synthetic = {winner_a: _synthetic_rank(sa, winner_a),
                 winner_b: _synthetic_rank(sb, winner_b)}
    bracket["series"][slot] = _make_series(winner_a, winner_b, synthetic,
                                            None, conf, rnd, slot)


def _synthetic_rank(s: dict, team: str) -> dict:
    # Placeholder rec so _tiebreak_key can compare two prior-round survivors
    # without a live standings dict: a team that was the higher seed in its
    # own series ranks ahead of one that was the lower seed. Ties (both
    # "higher" survivors, or both "lower") resolve alphabetically via _cmp's
    # last resort, which is acceptable — no listener-audible fact depends on
    # which of two co-equal survivors technically hosts game 1.
    was_higher = team == s["higher"]
    return {"w": 1 if was_higher else 0, "otl": 0, "gp": 1, "rw": 0, "row": 0}


def fold_playoff(bracket: dict, box: dict) -> None:
    """Fold one completed playoff game's box into its series, in place.

    `box` is a single game's box (boxscore.py shape: home/away/final/...).
    Finds the active series whose {higher, lower} matches {home, away},
    records the game, credits the win, and — the instant 4 wins land —
    marks that series' winner and lazily builds whichever next-round
    series just became playable (see module docstring on lazy creation).
    A series at 4 wins is final; best-of-7 never plays a 5th deciding game
    on either side. `champion` becomes non-None only once the CUP series
    itself reaches 4 wins for one side.
    """
    home, away = box["home"], box["away"]
    fh, fa = box["final"]
    winner = home if fh > fa else away
    for s in _active_series(bracket).values():
        if {s["higher"], s["lower"]} == {home, away}:
            s["games"].append({"home": home, "away": away, "final": [fh, fa]})
            s["wins"][winner] += 1
            if s["wins"][winner] == 4:
                s["winner"] = winner
            break

    for cname in LEAGUE:
        _try_build(bracket, f"{cname}-A", f"{cname}-A-1", f"{cname}-A-2", 2, cname)
        _try_build(bracket, f"{cname}-B", f"{cname}-B-1", f"{cname}-B-2", 2, cname)
        _try_build(bracket, cname, f"{cname}-A", f"{cname}-B", 3, cname)
    _try_build(bracket, "CUP", "Eastern", "Western", 4, "CUP")

    cup = bracket["series"].get("CUP")
    if cup is not None and cup["winner"] is not None:
        bracket["champion"] = cup["winner"]


def champion(bracket: dict) -> str | None:
    """The Cup winner, or None until the CUP series reaches 4 wins."""
    return bracket.get("champion")
