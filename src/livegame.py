"""LiveGame — the broadcast game engine. The game does not exist until rolled.

Four load-bearing rules:
  1. FRESH ENTROPY at roll time (SystemRandom): no seed, no predetermined
     outcome. When the booth calls the first period, the third period does
     not exist yet — not hidden, nonexistent.
  2. The append-only JSONL log (data/livegame-<date>.jsonl) IS the game.
     The past never re-rolls: advance(chunk_id) is idempotent, restarts
     resume exactly where the log ends, a torn tail line is dropped, and
     deeper corruption RAISES loudly — a silent 0-0 reset is the one
     outcome that must be impossible.
  3. Exactly one engine owns a game (flock on a sidecar .lock) and exactly
     one thread touches it (the orchestrator main loop; prefetch threads
     only ever see already-rolled chunk dicts).
  4. Everything is stamped with the AIR time it will be heard (generation
     runs up to ~45 buffered minutes ahead), so the website scorebug can
     tick in listener time and never spoil the broadcast.

sim_instant() runs the same calibrated model over a whole game in one call
for the 30-team off-air slates — one model, two speeds, so the tracked
teams' results are statistically indistinguishable from their peers'.
"""
from __future__ import annotations

import fcntl
import json
import os
import random
import time
from pathlib import Path

DATA = Path("data")

# --- the calibrated rate model (Monte Carlo-verified against NHL envelopes:
#     season point spread 50-116, GF/team/game ~2.5-3.4, PP conversion 20%,
#     SHG ~3.4%/PP, OT decides ~71% of tied games)
BASE_EV = 2.81 / 3600     # goals/sec/team at even strength (rebated so that PP,
                          # empty-net and score-effects land league GF ~3.0)
STRENGTH_EXP = 0.35       # lambda ~ (s_for/s_opp)**0.35 -> extreme H2H win% ~0.76
HOME_EDGE = 1.05          # even-matchup home win% ~53%
PP_MULT = 2.23            # 20.0% conversion per full 2-min minor
SH_MULT = 0.35            # 3.4% shorthanded goals per PP
SCORE_FX = 1.18           # trailing by 1-2 in the third (replaces momentum:
                          # counteracts blowouts and raises regulation ties)
EN_LEAD = 2.0             # leading team shooting at an empty net -- tuned down
                          # from 5.0, see "final calibration pass" below
EN_TRAIL = 1.7            # trailing team at 6-on-5
OT_MULT = 1.4             # 3-on-3 overtime -- tuned down from 2.5, see below
SO_ATTEMPT_P = 0.32       # per shootout attempt
PEN_RATE = 6.0 / 3600     # penalty arrivals (one active at a time)
INJ_RATE = 0.10 / 3600    # ~1 injury every 10 games, skaters only, PG euphemism
SHOT_FACTOR = 10.5        # shots ~ goal rate x10.5 (~30/team/game)

# --- final calibration pass (SO share + shutout rate, the two former
# calibrate_league.py WARN rows -- now hard PASS/FAIL bands there): moved
# BASE_EV 2.60->2.81/3600, EN_LEAD 5.0->2.0, OT_MULT 2.5->1.4. Combined
# with players.py's STR_LO/STR_HI narrowing (that file's own comment),
# 10-season measurement (seeds 900-909, `calibrate_league.py --seasons
# 10`) landed all 13 bands PASS, including the two newly-hard ones:
#   SO share of ALL games   6.4%  -> 10.7%  (band 9-12%)
#   shutout rate            ~11%  -> 8.65%  (band 6-9%)
#   goals/game (unmoved band, drifted up within it) -> 6.46 (band 5.7-6.5)
#   max win streak (STR_LO/STR_HI, not a livegame.py constant) 18 -> 13
# Lever-by-lever findings, so a future pass doesn't re-derive them:
#   - OT_MULT down is a clean, isolated SO-share lever: OT-reached share
#     (set entirely by regulation-tie rate) does not move at all as
#     OT_MULT changes -- only the OT-reached/SO split does. Swept 2.5 ->
#     1.4 (SO share 6.0% -> ~10.2% in isolation) with OT-reached pinned at
#     19.2% throughout.
#   - shutout rate has NO clean single-constant lever. Diagnostic sampling
#     (scratch script, not checked in) found only ~0.4% of games reach
#     shutout via the 0-0-after-regulation-decided-in-OT/SO channel (so
#     OT_MULT is provably ~orthogonal to shutout, confirmed empirically:
#     shutout rate read bit-identical across the whole OT_MULT sweep) --
#     the other ~99.6% are regulation shutouts, and of THOSE, ~71% are
#     3+-goal-margin blowouts a trailing team's goalie-pull window (fires
#     only at a 1- or 2-goal deficit) never reaches. STRENGTH_EXP and
#     SCORE_FX were both tried as levers and rejected: STRENGTH_EXP barely
#     moves shutout rate (0.1044 -> 0.1011 over a 0.35 -> 0.20 sweep) while
#     blowing the points-spread floor band almost immediately (0.30 already
#     reads floor 63.67 against a 62 cap); SCORE_FX gives a real shutout
#     reduction but inflates OT-reached share fast (1.18->1.6 alone already
#     breaks the 24% OT-reached cap) and is a strictly worse use of
#     goals/game budget than BASE_EV at matched cost (measured head to
#     head). BASE_EV alone is the single most efficient shutout lever
#     (raising the whole-game scoring floor lowers every team's P(0 goals)
#     Poisson-style) but tops out around shutout 0.092 right as goals/game
#     crosses its 6.5 cap -- insufficient alone. EN_LEAD down frees
#     goals/game headroom for a further BASE_EV raise at ~zero shutout
#     cost of its own, because it only touches the LEADING team's bonus
#     rate into an already-pulled net, never the trailing (shutout-risk)
#     team's own scoring chance -- confirmed empirically (EN_LEAD 5.0->1.0
#     alone: goals/game -0.19, shutout rate -0.002, i.e. nearly free).
#     Traded off against the (untracked, no calibrate_league.py band)
#     empty-net-goal-share sub-target (grounding ~7% of all goals): that
#     figure was already under-target pre-change (~3.6% measured at the
#     old EN_LEAD=5.0) and is now further under (~1.5% at EN_LEAD=2.0) --
#     flagged for a future pass, not fixed here.

PERIOD_SECS = 1200
REG_SECS = 3600
OT_SECS = 300
EN_WINDOW = 180           # micro-step the last 3 minutes of regulation

# --- league color pools (season.py builds rosters from these)
FIRST_NAMES = ("Doug Marty Gilles Pete Anders Toivo Brick Lars Chuck Remy Sven "
               "Gord Wally Jean-Guy Boone Alexei Dmitri Cliff Norm Tug Moose "
               "Stanislav Bert Olaf Petr Randy Curtis Yvon Merle Stu").split()
LAST_NAMES = ("Bouchard Larsson Petrenko Gustafsson Tremblay Kowalski O'Rourke "
              "Vachon Lindqvist Dubois Sorensen Mackenzie Novak Fitzpatrick "
              "Berube Halloran Jurgens Pelletier Sopel Grimsby Thibodeau Vrana "
              "Ostberg Callahan Demers Sikora Brandt Leclair Mulligan Ruud").split()
PENALTIES = ["tripping", "hooking", "interference", "delay of game",
             "too many men on the ice", "high-sticking", "holding",
             "excessive apologizing", "slashing", "unsportsmanlike conduct",
             "embellishment", "arguing with the zamboni"]
INJURY_NOTES = ["day-to-day, lower body", "day-to-day, upper body",
                "questionable, general body", "day-to-day, morale"]
REFS = ["Referee Don Pelkey", "Referee Marcel Aube", "Referee Sandy Kowalchuk",
        "Referee Wes Trudel", "Referee Pat Onions", "Referee Gil Ferland"]
SUBPLOTS = ["the zamboni is making a new sound and the driver is defensive",
            "the puck went missing during warmups; the backup puck feels off",
            "the organist is in a mood and it's affecting the tempo",
            "someone in row F brought an enormous sign nobody can read",
            "the mascot is on thin ice, disciplinarily speaking",
            "the concession stand changed the nacho cheese and people know"]


def _period_of(secs: float):
    return "OT" if secs >= REG_SECS else min(int(secs // PERIOD_SECS), 2) + 1


def _clock_of(secs: float) -> str:
    """Elapsed time within the current period/OT, mm:ss."""
    base = REG_SECS if secs >= REG_SECS else int(secs // PERIOD_SECS) * PERIOD_SECS
    e = int(secs) - base
    return f"{e // 60}:{e % 60:02d}"


def _new_state() -> dict:
    return {"secs": 0.0, "board": [0, 0], "pen": None,
            "goalie_in": [True, True], "shots": [0.0, 0.0],
            "out": [[], []], "inj_count": 0}


def _rates(state: dict, s_h: float, s_a: float) -> tuple[float, float]:
    """Both teams' goals/sec under the current state. Pure."""
    secs, (h, a) = state["secs"], state["board"]
    ot = secs >= REG_SECS
    p3 = not ot and secs >= 2 * PERIOD_SECS
    pen = state["pen"]
    out = []
    for i, (sf, so) in enumerate(((s_h, s_a), (s_a, s_h))):
        lam = BASE_EV * (sf / so) ** STRENGTH_EXP
        if i == 0:
            lam *= HOME_EDGE
        if ot:
            lam *= OT_MULT
        if pen is not None:
            lam *= SH_MULT if pen["side"] == i else PP_MULT
        diff = (h - a) if i == 0 else (a - h)
        if p3 and -2 <= diff <= -1:
            lam *= SCORE_FX
        if not state["goalie_in"][1 - i]:   # shooting at an empty net
            lam *= EN_LEAD
        if not state["goalie_in"][i]:       # own net empty: extra attacker
            lam *= EN_TRAIL
        out.append(lam)
    return out[0], out[1]


def _update_pulls(state: dict, events: list | None) -> None:
    """Pull/return goalies from explicit state — re-evaluated every micro-step
    in the final minutes so an empty-net call can never contradict the game."""
    secs = state["secs"]
    left = REG_SECS - secs
    h, a = state["board"]
    for i, diff in enumerate((h - a, a - h)):
        want_out = (secs < REG_SECS and
                    ((diff == -1 and left <= 120) or (diff == -2 and left <= 180)))
        if state["goalie_in"][i] == (not want_out):
            continue
        state["goalie_in"][i] = not want_out
        if events is not None and secs < REG_SECS:
            events.append({"type": "pull" if want_out else "return",
                           "team": "home" if i == 0 else "away",
                           "period": _period_of(secs), "clock": _clock_of(secs),
                           "secs": int(secs)})


def _draw_skater(rng, roster: dict, out: list) -> str:
    """Stars score more; injured players never reappear in any draw.
    v2 rosters carry per-skater draw weights (parallel to `skaters`) tuned to
    the real scoring depth curve; legacy rosters keep the exact legacy draw."""
    if "weights" in roster:
        return _draw_weighted(rng, roster, out, "weights")
    active = [s for s in roster["skaters"] if s not in out]
    if not active:
        return roster["goalie"]
    stars = [s for s in active[:3]]
    return rng.choice(stars + stars + active)


def _draw_weighted(rng, roster: dict, out, key: str,
                   exclude: set | None = None) -> str | None:
    ex = set(out) | (exclude or set())
    pool = [(s, w) for s, w in zip(roster["skaters"], roster[key])
            if s not in ex]
    if not pool:
        return roster["goalie"] if exclude is None else None
    names, ws = zip(*pool)
    return rng.choices(names, weights=ws, k=1)[0]


def _sim_span(state: dict, rng, to_secs: float, s_h: float, s_a: float,
              rosters: dict | None, events: list | None) -> None:
    """Advance to absolute game-second `to_secs`, emitting events. Piecewise-
    constant rates between state boundaries; sudden death past regulation.
    With rosters=None (instant mode) no names are drawn and injuries are off."""
    while state["secs"] < to_secs:
        secs = state["secs"]
        ot = secs >= REG_SECS
        if ot and state["board"][0] != state["board"][1]:
            break               # sudden death already decided
        _update_pulls(state, events)
        period_end = REG_SECS + OT_SECS if ot else (int(secs // PERIOD_SECS) + 1) * PERIOD_SECS
        seg_end = min(to_secs, period_end)
        if state["pen"] is not None:
            seg_end = min(seg_end, state["pen"]["expires"])
        if not ot:
            if secs < REG_SECS - EN_WINDOW:
                seg_end = min(seg_end, REG_SECS - EN_WINDOW)
            else:               # empty-net territory: re-check pulls every <=15s
                seg_end = min(seg_end, secs + 15)
        lh, la = _rates(state, s_h, s_a)
        lp = PEN_RATE if (state["pen"] is None and not ot) else 0.0
        li = (INJ_RATE if (rosters is not None and not ot
                           and state["inj_count"] < 1) else 0.0)
        total = lh + la + lp + li
        dt = rng.expovariate(total) if total > 0 else float("inf")
        span = min(dt, seg_end - secs)
        state["shots"][0] += lh * SHOT_FACTOR * span
        state["shots"][1] += la * SHOT_FACTOR * span
        if dt > seg_end - secs:
            state["secs"] = seg_end
            if state["pen"] is not None and seg_end >= state["pen"]["expires"]:
                state["pen"] = None
            continue
        state["secs"] = secs + dt
        pick = rng.random() * total
        if pick < lh + la:
            side = 0 if pick < lh else 1
            team = "home" if side == 0 else "away"
            state["board"][side] += 1
            pen = state["pen"]
            if events is not None and rosters is not None:
                r = rosters[team]
                scorer = _draw_skater(rng, r, state["out"][side])
                assist2 = None
                if "pweights" in r:
                    # v2: real assist chain — P(a1)=.90, P(a2|a1)=.65 lands the
                    # calibrated ~1.49 A:G; playmaker-weighted picks
                    assist = None
                    if rng.random() < 0.90:
                        assist = _draw_weighted(rng, r, state["out"][side],
                                                "pweights", exclude={scorer})
                        if assist and rng.random() < 0.65:
                            assist2 = _draw_weighted(
                                rng, r, state["out"][side], "pweights",
                                exclude={scorer, assist})
                else:      # legacy path: byte-identical draw order
                    assist = rng.choice([None] + [s for s in r["skaters"]
                                                  if s != scorer and s not in state["out"][side]])
                strength = ("SH" if pen and pen["side"] == side else
                            "PP" if pen and pen["side"] != side else
                            "EN" if not state["goalie_in"][1 - side] else "EV")
                events.append({"type": "goal", "team": team, "scorer": scorer,
                               "assist": assist, "assist2": assist2,
                               "period": _period_of(state["secs"]),
                               "clock": _clock_of(state["secs"]),
                               "secs": int(state["secs"]), "strength": strength,
                               "net_empty": not state["goalie_in"][1 - side],
                               "board": list(state["board"])})
            if pen is not None and pen["side"] != side:
                state["pen"] = None     # a power-play goal ends the minor
            _update_pulls(state, events)
        elif pick < lh + la + lp:
            side = 0 if rng.random() < 0.5 else 1
            state["pen"] = {"side": side, "expires": state["secs"] + 120}
            if events is not None and rosters is not None:
                team = "home" if side == 0 else "away"
                events.append({"type": "penalty", "team": team,
                               "player": _draw_skater(rng, rosters[team],
                                                      state["out"][side]),
                               "call": rng.choice(PENALTIES),
                               "period": _period_of(state["secs"]),
                               "clock": _clock_of(state["secs"]),
                               "secs": int(state["secs"])})
        else:
            side = 0 if rng.random() < 0.5 else 1
            team = "home" if side == 0 else "away"
            skaters = [s for s in rosters[team]["skaters"]
                       if s not in state["out"][side]]
            player = rng.choice(skaters) if skaters else None
            state["inj_count"] += 1
            if player:
                state["out"][side].append(player)
                if events is not None:
                    events.append({"type": "injury", "team": team, "player": player,
                                   "note": rng.choice(INJURY_NOTES),
                                   "period": _period_of(state["secs"]),
                                   "clock": _clock_of(state["secs"]),
                                   "secs": int(state["secs"])})


def _sim_shootout(rng, rosters: dict | None, events: list | None) -> int:
    """3 rounds then sudden death; returns the winning side (0 home, 1 away)."""
    scored = [0, 0]
    rnd = 0
    while True:
        rnd += 1
        got = []
        for side in (0, 1):
            hit = rng.random() < SO_ATTEMPT_P
            got.append(hit)
            if events is not None and rosters is not None:
                team = "home" if side == 0 else "away"
                shooters = rosters[team]["skaters"]
                events.append({"type": "so", "team": team,
                               "player": shooters[(rnd - 1) % len(shooters)],
                               "scored": hit, "round": rnd})
        scored[0] += got[0]
        scored[1] += got[1]
        if rnd >= 3 and scored[0] != scored[1]:
            return 0 if scored[0] > scored[1] else 1
        if rnd > 20:            # a coin must eventually land
            return 0 if rng.random() < 0.5 else 1


def sim_instant(s_h: float, s_a: float, rng: random.Random) -> tuple[int, int, bool, bool]:
    """A whole game in one call — same model as the live engine, no
    persistence, no names. Deterministic given rng (off-air slates stay
    date-seeded: nobody hears them unfold, and seeds self-heal)."""
    state = _new_state()
    _sim_span(state, rng, REG_SECS, s_h, s_a, None, None)
    h, a = state["board"]
    if h != a:
        return h, a, False, False
    _sim_span(state, rng, REG_SECS + OT_SECS, s_h, s_a, None, None)
    h, a = state["board"]
    if h != a:
        return h, a, True, False
    winner = _sim_shootout(rng, None, None)
    return (h + 1, a, False, True) if winner == 0 else (h, a + 1, False, True)


# --- the persistent live engine

def log_path(date: str) -> Path:
    return DATA / f"livegame-{date}.jsonl"


def read_log(date: str) -> dict | None:
    """Lock-free reader for export/publish/record paths. Returns
    {game, chunks, order, narrated, final, final_air_at} or None. Tolerates
    a torn last line; raises on deeper corruption (never a silent reset)."""
    p = log_path(date)
    if not p.exists():
        return None
    lines = p.read_text().splitlines()
    parsed = []
    for i, raw in enumerate(lines):
        try:
            parsed.append(json.loads(raw))
        except Exception:
            if i == len(lines) - 1:
                break           # torn tail from a mid-write crash: drop it
            raise ValueError(f"livegame log {p} corrupt at line {i + 1}")
    if not parsed:
        return None
    for i, ln in enumerate(parsed):
        if ln.get("seq") != i:
            raise ValueError(f"livegame log {p} seq gap at line {i + 1}")
    if parsed[0].get("type") != "game":
        raise ValueError(f"livegame log {p} missing game header")
    out = {"game": parsed[0]["game"], "chunks": {}, "order": [],
           "narrated": set(), "narrated_air": {}, "opened": False,
           "final": None, "final_air_at": None, "seq": parsed[-1]["seq"]}
    for ln in parsed[1:]:
        if ln["type"] == "chunk":
            out["chunks"][ln["chunk"]] = ln
            out["order"].append(ln["chunk"])
        elif ln["type"] == "narrated":
            out["narrated"].add(ln["chunk"])
            # air time is stamped at NARRATION, not roll — the scorebug reveals
            # a chunk only once this moment passes, so it can never spoil
            out["narrated_air"][ln["chunk"]] = ln.get("air_at")
            if ln["chunk"] == "@final":
                out["final_air_at"] = ln.get("air_at")
        elif ln["type"] == "opened":
            out["opened"] = True
        elif ln["type"] == "final":
            out["final"] = ln["final"]
    return out


def _air_at() -> float:
    """The wall moment this content will be HEARD: now + queued audio."""
    try:
        from . import buffer
        return time.time() + buffer.buffered_seconds()
    except Exception:
        return time.time()


class LiveGame:
    """One broadcast game. Open holds an exclusive flock for the object's
    lifetime; all mutation must come from a single thread."""

    def __init__(self, game: dict):
        DATA.mkdir(parents=True, exist_ok=True)
        self.date = game["date"]
        self.path = log_path(self.date)
        self._lockfd = os.open(str(self.path) + ".lock",
                               os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(self._lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self._lockfd)
            raise RuntimeError(f"another engine owns the {self.date} game")
        self._rng = random.SystemRandom()   # fresh entropy: rule 1
        self._sanitize()
        log = read_log(self.date)
        if log is None:
            self.game = game
            self._chunks, self._order = {}, []
            self._narrated: set = set()
            self._narrated_air: dict = {}
            self.opened = False
            self.final = None
            self._state = _new_state()
            self._seq = -1
            self._append({"type": "game", "game": game})
        else:
            self.game = log["game"]
            self._chunks, self._order = log["chunks"], log["order"]
            self._narrated = log["narrated"]
            self._narrated_air = log["narrated_air"]
            self.opened = log["opened"]
            self.final = log["final"]
            self._seq = log["seq"]
            self._state = (json.loads(json.dumps(self._chunks[self._order[-1]]["state"]))
                           if self._order else _new_state())

    # -- log plumbing

    def _sanitize(self) -> None:
        """Physically drop a torn tail line left by a mid-write crash — we
        hold the lock, and appending after garbage would poison the log."""
        if not self.path.exists():
            return
        txt = self.path.read_text()
        lines = txt.splitlines()
        keep = []
        for i, raw in enumerate(lines):
            try:
                json.loads(raw)
                keep.append(raw)
            except Exception:
                if i == len(lines) - 1:
                    break       # torn tail: truncate it away
                raise ValueError(f"livegame log {self.path} corrupt at line {i + 1}")
        fixed = "".join(ln + "\n" for ln in keep)
        if fixed != txt:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(fixed)
            os.replace(tmp, self.path)

    def _append(self, rec: dict) -> None:
        # verify the on-disk tail seq still matches ours: a second writer or
        # an external truncation must crash us, never interleave (rule 3)
        if self.path.exists():
            tail = self.path.read_text().splitlines()
            disk_seq = -1
            for raw in reversed(tail):
                try:
                    disk_seq = json.loads(raw)["seq"]
                    break
                except Exception:
                    continue
            if disk_seq != self._seq:
                raise RuntimeError(f"livegame log {self.path} moved underneath us "
                                   f"(disk seq {disk_seq}, ours {self._seq})")
        self._seq += 1
        rec = {"seq": self._seq, **rec}
        fd = os.open(str(self.path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (json.dumps(rec) + "\n").encode())
            os.fsync(fd)
        finally:
            os.close(fd)

    def close(self) -> None:
        try:
            fcntl.flock(self._lockfd, fcntl.LOCK_UN)
            os.close(self._lockfd)
        except Exception:
            pass

    # -- read side

    def state(self) -> dict:
        s = self._state
        secs = s["secs"]
        return {"secs": int(secs), "period": _period_of(secs),
                "clock": _clock_of(secs), "board": list(s["board"]),
                "pen": s["pen"], "en": not all(s["goalie_in"]),
                "shots": [int(s["shots"][0]), int(s["shots"][1])],
                "out": [list(s["out"][0]), list(s["out"][1])],
                "final": self.final}

    def chunk(self, chunk_id: str) -> dict | None:
        return self._chunks.get(chunk_id)

    def unnarrated(self) -> list[dict]:
        """Chunks rolled (and possibly published) but never aired — a restart
        or an empty beat must re-NARRATE them from the log, never re-roll."""
        return [self._chunks[c] for c in self._order if c not in self._narrated]

    def narrated_events(self) -> list[dict]:
        """Every event that has already been written to air, in roll order —
        the fact base a resumed broadcast builds its tallies on."""
        return [e for c in self._order if c in self._narrated
                for e in self._chunks[c]["events"]]

    def mark_narrated(self, chunk_id: str) -> None:
        if chunk_id in self._narrated or chunk_id not in self._chunks:
            return
        air = _air_at()   # stamped now: this chunk airs buffered_seconds from now
        self._append({"type": "narrated", "chunk": chunk_id, "air_at": air})
        self._narrated.add(chunk_id)
        self._narrated_air[chunk_id] = air

    def mark_final_narrated(self) -> None:
        """The final horn has been ANNOUNCED on air — the scorebug may reveal
        the final once this air moment passes (not the roll-time stamp)."""
        if "@final" in self._narrated_air:
            return
        air = _air_at()
        self._append({"type": "narrated", "chunk": "@final", "air_at": air})
        self._narrated_air["@final"] = air

    def mark_opened(self) -> None:
        """The pregame open has aired — a restart must not replay it."""
        if self.opened:
            return
        self._append({"type": "opened"})
        self.opened = True

    # -- the roll

    def _strengths(self) -> tuple[float, float]:
        return self.game["strength_home"], self.game["strength_away"]

    def advance(self, chunk_id: str, to_secs: int) -> dict:
        """Roll the game forward to `to_secs` (absolute game seconds).
        Idempotent per chunk_id: the past never re-rolls (rule 2)."""
        if chunk_id in self._chunks:
            return self._chunks[chunk_id]
        if self.final is not None:
            raise RuntimeError("game is final; nothing left to roll")
        s_h, s_a = self._strengths()
        rosters = self.game["rosters"]
        events: list = []
        board_in = list(self._state["board"])
        from_secs = int(self._state["secs"])
        pp_span = self._state["pen"] is not None
        en_span = not all(self._state["goalie_in"])
        _sim_span(self._state, self._rng, float(to_secs), s_h, s_a, rosters, events)
        pp_span = pp_span or any(e["type"] == "penalty" for e in events)
        en_span = en_span or any(e["type"] == "pull" for e in events)
        h, a = self._state["board"]
        so = False
        if to_secs > REG_SECS and self._state["secs"] >= REG_SECS + OT_SECS and h == a:
            winner = _sim_shootout(self._rng, rosters, events)
            if winner == 0:
                self._state["board"][0] += 1
            else:
                self._state["board"][1] += 1
            h, a = self._state["board"]
            so = True
        air = _air_at()
        n = max(len(events), 1)
        for i, e in enumerate(events):
            e["air_at"] = air + (i + 1) / (n + 1) * 250
        chunk = {"type": "chunk", "chunk": chunk_id, "from": from_secs,
                 "to": int(self._state["secs"]), "events": events,
                 "board_in": board_in, "board": [h, a],
                 "pp_span": pp_span, "en_span": en_span,
                 "state": json.loads(json.dumps(self._state)), "air_at": air}
        self._append(chunk)
        self._chunks[chunk_id] = chunk
        self._order.append(chunk_id)
        decided = (self._state["secs"] >= REG_SECS and h != a)
        if decided and (to_secs >= REG_SECS or self._state["secs"] >= REG_SECS):
            self._finalize(so)
        return chunk

    def finish_now(self, chunk_id: str = "FINISH") -> dict:
        """Roll everything that remains — regulation, OT, shootout — into one
        chunk. The one honest way to end a game the air window cut short.
        advance() to the OT horn covers every case: a decided regulation game
        stops at 3600, a tied one plays sudden death, a scoreless OT ends in
        the shootout. No-ops gracefully if the game is already final."""
        if chunk_id in self._chunks:
            return self._chunks[chunk_id]
        if self.final is not None:
            return self._chunks[self._order[-1]] if self._order else {
                "type": "chunk", "chunk": chunk_id, "events": [],
                "board_in": self._state["board"], "board": self._state["board"],
                "pp_span": False, "en_span": False}
        return self.advance(chunk_id, REG_SECS + OT_SECS)

    def _finalize(self, so: bool) -> None:
        h, a = self._state["board"]
        ot = self._state["secs"] > REG_SECS and not so
        # three stars: top scorers by tally then recency, plus the winning goalie
        tally: dict = {}
        order = []
        for cid in self._order:
            for e in self._chunks[cid]["events"]:
                if e["type"] == "goal":
                    tally[e["scorer"]] = tally.get(e["scorer"], 0) + 1
                    order.append(e["scorer"])
        stars = sorted(dict.fromkeys(reversed(order)),
                       key=lambda p: -tally[p])[:2]
        win_side = "home" if h > a else "away"
        goalie = self.game["rosters"][win_side]["goalie"]
        if goalie not in stars:
            stars.append(goalie)
        for s in self.game["rosters"][win_side]["skaters"]:
            if len(stars) >= 3:
                break
            if s not in stars:
                stars.append(s)
        self.final = {"h": h, "a": a, "ot": ot, "so": so, "stars": stars[:3],
                      "shots": [int(self._state["shots"][0]),
                                int(self._state["shots"][1])],
                      "out": [list(self._state["out"][0]),
                              list(self._state["out"][1])]}
        self._append({"type": "final", "final": self.final, "air_at": _air_at()})
