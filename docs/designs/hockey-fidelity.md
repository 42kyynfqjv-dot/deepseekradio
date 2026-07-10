# Hockey League Engine — SIM-FIDELITY-FIRST Design

Design lens: **indistinguishability**. Every fact a hockey-literate listener could
check — a scorer's season total, a backup goalie's start count, a trade's cap math,
last Tuesday's Fargo–Regina box score — must exist, be internally consistent, and
survive restarts. Architecture: docs/designs/hockey-fidelity.md.

---

## 1. Executive summary

The league becomes a **deterministic replayable world**: every off-air fact is a pure
function of `(season seed, transaction log, recorded live finals)`, so state can always
be rebuilt and never contradicts what aired. Core bets:

1. **season.json stays the hub and is dual-written** — the v2 engine maintains every
   legacy field byte-compatibly, so fallback is a config flag flip with zero data loss.
2. **One calibrated model, three speeds**: the existing livegame constants drive the
   live roll, an event-mode `sim_game()` for off-air box scores, and a retro
   `expand_final()` that deepens already-published finals into box scores without
   changing them — that's how 4 days of aired canon gets full stats history.
3. **Persistent players with attribute-derived team strength**, generated to reproduce
   the current season-1 scalar strengths, so migrated standings remain statistically
   continuous.
4. **1 wall-day = 1 league game-day** in the regular season (the nightly slates are
   aired canon); compression concentrated in playoffs/offseason → ~1.7 seasons/year.
5. Box scores shard per-day under `data/league/`; the hot tick path touches only
   season.json and stays <100 ms; day-boundary work ≤ 300 ms on 2 vCPU.
6. Rollover moves out of `record_live` into `tick`, air-gated like every other publish.

---

## 2. State schema

All files atomic tmp+replace with `.bak` copy (existing `_save` pattern). Layout:

```
season.json                      # hub (legacy fields + v2 pointers) ~120 KB
data/league/players.json         # every active player + career totals ~500 KB
data/league/retired.json         # collapsed career lines, append-only ~20 KB/season
data/league/staff.json           # coaches/GMs/trainers, 32 teams ~25 KB
data/league/season-<N>/schedule.json    # full 1,312-game matrix ~260 KB
data/league/season-<N>/stats.json       # per-player season stats ~280 KB
data/league/season-<N>/transactions.json  # trades/waivers/firings/signings ~60 KB
data/league/season-<N>/box/<D>.json     # per-league-day box scores ~10 KB/day
data/league/history.json         # season summaries, award winners, champions ~8 KB/season
data/league/ot-signal.json       # OT-past-window flag (§10)
```

**players.json** (~1,320 records: 32×23 active + 32×12 reserve + ~200 prospects):

```json
{"next_id": 1321, "players": {
  "p0417": {
    "name": "Doug Bouchard", "team": "mtl", "pos": "C", "shoots": "L",
    "born": {"s": -23, "d": 141}, "ht": 73, "wt": 194, "num": 19,
    "attrs": {"sk": 71, "sh": 78, "pl": 74, "df": 55, "ph": 60},
    "dev": {"peak": 26.5, "rise": 1.8, "fall": 2.6, "durab": 0.9},
    "slot": "F1", "status": "active",
    "acq": {"how": "seed", "season": 1},
    "career": {"gp": 2, "g": 1, "a": 2, "p": 3, "pim": 0, "so": 0},
    "draft": null
  }}}
```

Goalies use `attrs.gl` instead of `sh/pl`; `born` is league-calendar (season offset,
day) so ages advance with league time, not wall time. `slot` is the depth-chart slot
(F1..F12, D1..D6, G1, G2, R* reserve, P* prospect). ~370 B/player → **~490 KB**, grows
~130 B/player/season of career line; retirees collapse into retired.json.

**season-N/schedule.json** — the real 82-game matrix:

```json
{"season": 2, "games": [
  {"gid": "s2g0007", "day": 3, "home": "reg", "away": "far",
   "final": [4, 2], "ot": false, "so": false, "kind": "off",
   "box": "box/0003.json"},
  {"gid": "s2g0011", "day": 4, "home": "mtl", "away": "hfx",
   "final": null, "ot": false, "so": false, "kind": "air",
   "wall": "2026-07-11"}]}
```

~200 B/game × 1,312 ≈ **260 KB**. Playoff games appended with `kind: "po", series:
"E1-W2R1"` etc.

**season-N/stats.json** — per-player season lines (skater and goalie shapes):

```json
{"p0417": {"gp": 2, "g": 1, "a": 2, "p": 3, "pim": 0, "sog": 7, "plus": 1,
           "ppg": 0, "shg": 0, "gwg": 0, "hat": 0, "streak_p": 2},
 "p0425": {"gp": 2, "gs": 2, "w": 1, "l": 1, "otl": 0, "sa": 61, "sv": 55,
           "so": 0, "toi": 7200}}
```

~200 B × 1,320 ≈ **280 KB**, rewritten once per league-day.

**box/<day>.json** — every off-air game's full box score (the fidelity centerpiece):

```json
{"day": 3, "games": [{"gid": "s2g0007",
  "final": [4, 2], "ot": false, "so": false, "shots": [31, 26],
  "goals": [{"p": 1, "clock": "7:41", "team": "reg", "scorer": "p0812",
             "a1": "p0815", "a2": null, "strength": "EV", "board": [1, 0]}],
  "pens": [{"p": 2, "clock": "3:12", "team": "far", "player": "p0904",
            "call": "hooking"}],
  "goalies": {"reg": {"id": "p0830", "sa": 26, "ga": 2},
              "far": {"id": "p0921", "sa": 31, "ga": 4}},
  "stars": ["p0812", "p0830", "p0904"], "att": 10412,
  "start_off": 1800}]}
```

~1.3 KB/game × ~8 games ≈ **10 KB/day, ~1.8 MB/season**. `start_off` staggers virtual
puck drops for in-progress around-the-league reads (§10).

**Pruning story**: current + previous season keep full box shards. Older seasons: box
shards deleted (they are deterministically reconstructable from seeds + transaction
log — self-healing archive), keeping stats.json, schedule.json finals, transactions,
history.json forever. Steady-state disk: **< 8 MB** for hot state, +~700 KB per
archived season. Nothing here strains 4 GB.

**season.json v2 additions** (legacy keys untouched): `"v2": {"enabled": true,
"league_day": 37, "season_epoch": "2026-07-05", "phase": "regular",
"po_bracket": {...}, "pending_air": null}` plus per-team extended standings
`{"rw": 3, "row": 4, "gf": 12, "ga": 9, "home": [2,0,1], "b2b_flag": false}`.

---

## 3. Module & file breakdown

All stdlib-only, pure functions against fixed schemas unless noted.

**`src/league/gen.py`** — creation (pure given rng):
```python
def gen_player(rng, pos: str, age_days: int, tier: float) -> dict
def gen_full_roster(rng, team_key: str, target_strength: float,
                    pinned: dict | None) -> list[dict]   # pinned = aired 9 names
def gen_staff(rng, team_key: str) -> dict                # coach/GM/trainer
def gen_prospect_class(rng, season: int, n: int = 224) -> list[dict]
```

**`src/league/sched.py`** — schedule matrix:
```python
def build_schedule(teams: dict, season: int, played_prefix: list[dict],
                   rng) -> list[dict]     # exact 26/24/32 buckets, 41H/41A
def slate_for_day(schedule: list[dict], day: int) -> list[dict]
def validate_schedule(schedule) -> list[str]   # empty == legal
```

**`src/league/boxgen.py`** — the second and third speeds of the one model:
```python
def sim_game(meta: dict, rosters: dict, mods: dict, rng) -> dict   # full box score
def expand_final(meta: dict, final: tuple, rosters: dict, rng) -> dict
    # retro: deepens a published final WITHOUT changing score/ot/so
def harvest_live_log(log: dict, id_map: dict) -> dict   # aired log -> box score
```
`sim_game` wraps `livegame._sim_span` in event mode with weighted attribution;
`expand_final` runs rejection-free conditional generation: draws goal times from the
calibrated period-split distribution, attributions from roster weights, shots from
`SHOT_FACTOR` noise conditioned on GA.

**`src/league/attr.py`** — attribution math shared with livegame:
```python
def scoring_weights(roster: list[dict]) -> tuple[list[str], list[float]]
def draw_scorer(rng, names, weights, out: list) -> str
def draw_assists(rng, names, pweights, scorer, out) -> tuple[str|None, str|None]
    # P(0)=.10, P(1)=.30, P(2)=.60  -> league A:G = 1.50
def team_strength(roster: list[dict], staff: dict) -> float   # replaces scalar
def age_curve(attrs: dict, dev: dict, age_days: int) -> dict  # season-boundary aging
```

**`src/league/stats.py`**:
```python
def fold_box(stats: dict, box: dict) -> list[dict]   # returns milestone events
def leaders(stats: dict, players: dict, cat: str, n: int = 10) -> list[dict]
def milestones_watch(stats, players, team_key) -> list[str]  # "2 shy of 30 goals"
```

**`src/league/roster.py`** — lineup legality and churn:
```python
def dress(players, team_key, out_list, rng) -> dict   # 12F/6D/2G, legacy rosters shape
def injury_roll(rng, box: dict, players) -> list[dict]      # log-normal durations
def process_returns(out_list, league_day) -> tuple[list, list]
def callups_needed(players, team_key, out_list) -> list[dict]  # <12F/<6D/<2G triggers
def goalie_rotation(stats, team_key, league_day, b2b: bool, rng) -> str  # 60/22 split
```

**`src/league/econ.py`** — contracts/cap (§12):
```python
def cap_table(players, contracts, team_key, season) -> dict
def validate_trade(proposal, players, contracts, season) -> str | None
def propose_trades(state, league_day, rng) -> list[dict]
def coach_hazard(staff, standings, expectations, league_day, rng) -> list[dict]
def offseason(state, rng) -> dict   # RFA/UFA/arbitration/draft signing sweep
```

**`src/league/playoffs.py`**:
```python
def seed_bracket(standings_ext: dict) -> dict     # 3/div + 2 WC, fixed bracket
def series_slate(bracket, day) -> list[dict]
def advance(bracket, results) -> dict
```

**`src/league/engine.py`** — the impure shell (owns file IO):
```python
def league_tick(air_date: str) -> None       # called from season.tick under gate
def tonight_game(air_date: str) -> dict      # schedule-aware broadcast game
def record_final(air_date: str, log: dict) -> str | None
def rollover_if_due(air_date: str) -> str | None   # air-gated (§8)
```

**`src/league/sheets.py`** — every booth feed (§10). **`scripts/migrate_league_v2.py`**,
**`scripts/verify_league.py`** (§11), **`scripts/calibrate.py`**.

**Changed modules**: `src/season.py` becomes a facade (§4, §8); `src/livegame.py` gets
three additive changes: weighted `_draw_skater` when `rosters[side]["weights"]`
present, optional second assist (`assist2` key, additive), and per-goalie save
tracking in state (`sa` per side). Constants untouched. `FIRST_NAMES`/`LAST_NAMES`
pools extended in place (never edited) so nameguard's `pool_ok` covers all new names.

---

## 4. Interface preservation

Every public function keeps its exact signature; `season.py` dispatches on the gate:

- **`tonight_live(date)`** → v2 path calls `engine.tonight_game`, which reads the real
  schedule instead of inventing a matchup. Returned game dict keeps every legacy key:
  `game_no, date, rivalry, season, home, away, home_key, away_key, arena, recorded,
  rosters, returning, strength_home, strength_away, refs, subplot, attendance`.
  `strength_*` now comes from `attr.team_strength` (same [0.30, 0.70] range → livegame
  needs no change). `rosters` keeps the exact guard-consumed shape
  `{home/away: {skaters: [18 names], goalie: name}}` — skaters ordered L1-first so the
  legacy star-trio draw degrades gracefully — plus **additive** keys: `weights`,
  `pweights`, `goalie_backup`, `lines` (dict of names), `scratches`, `ids` (name→pid).
- **`record_live(date)`** → identical fold into legacy standings fields **plus** stat
  folding via `boxgen.harvest_live_log` and schedule final write. The rollover branch
  is removed under v2 (§8). Idempotency key unchanged (`games[date]["recorded"]`).
- **`tick(date)`** → same signature; v2 adds `engine.league_tick` before `export()`.
- **`export(path)`** → same league.json superset: legacy `divisions/broadcast/around`
  fields byte-shape-identical; new keys (`leaders`, `phase`, `bracket`, `box_index`)
  appended. Air-gating logic (narrated_air / final_air_at) untouched.
- **`pregame_brief(game)` / `postgame_brief(game, final)` / `context_pairs(game)`** →
  same signatures, generated by `sheets.py`. `context_pairs` grows to include the
  in-progress around-the-league partial scores (§10) so scoreguard's `allow_pairs`
  keeps every legitimately mentionable pair.
- **Guard fact shapes**: `build_facts` reads `rosters.skaters` (list of full-name
  strings), `rosters.goalie`, `refs`, and event dicts with
  `type/team/scorer/assist/period/clock/board/strength` — all preserved. `assist2` is
  a new optional key the guards ignore; sheets render it. Nameguard's pool check keeps
  passing because all generated names draw from the (extended) livegame pools.

---

## 5. League calendar mapping

**Regular season: 1 wall-day = 1 league game-day.** This is forced by canon: four
days of nightly ~10-game slates have already aired and been exported. It is also the
*highest-fidelity* choice: per-team cadence lands at ~3.4 games/week (real: 3.0–3.2),
nightly slate sizes (2–14 games, mean 8) match real NHL nights, and back-to-backs
arise naturally from the schedule matrix (target 10–16 sets/team — the generator
enforces it). 1,312 games / ~8 per night = 164 game nights; add a 3-day holiday break
and a 4-day midseason break (both narratable events) → **171-day regular season**.

**Playoffs: compressed 2:1.** Each series plays nightly (real: every 2 days), one rest
day between rounds → R1 ≤ 8 days, R2/R3 ≤ 8, Final ≤ 8, +3 rest days ≈ **≤ 35 days**.
Justification: compression belongs where slate density can't betray it — playoff
nights have 1–8 games league-wide, so nightly series games read as "dense playoff
hockey," and the tracked team still lands ~2 broadcast games/week.

**Offseason: 10 wall days**, fixed script: D1 lottery, D3 draft (7×32), D5 RFA
qualifying, D6 free agency opens, D8–10 camp/preseason notes. Awards announced D1–D2.

**Total league year ≈ 216 wall days → ~1.7 seasons per wall year.** Careers accrue
fast enough that a 10-season veteran exists after ~6 years of station history, without
the per-night texture ever deviating from real rhythms. The league runs a virtual
calendar (`league_day` 0..215, displayed as an "Oct 1"-anchored fictional date on the
website); the booth speaks in "game N of 82" and weekdays, which stay wall-true.
Broadcast nights remain wall Wed/Sat; the schedule generator pins tracked-team home
or away games onto those wall dates (`kind: "air"`), off-air tracked games elsewhere.

---

## 6. The nightly tick algorithm

`tick(air_date)` every main-loop pass. Steady state (league day already simmed): load
season.json (~120 KB, ≈3 ms parse), no-op checks, `export()` (~40 KB write) —
**< 60 ms**. At a league-day boundary (first tick after local midnight), run the
pipeline for day D:

1. **Returns & aging ticks** — decrement out-list, emit "activated from IR" items;
   (~1 ms).
2. **Lineups** — for each team playing: `dress()` (call-ups if <12F/<6D/<2G, goalie
   rotation honoring the 60/22 starter/backup split and B2B fatigue); ~8 teams×2,
   pure list ops (~5 ms).
3. **Sim the slate** — `sim_game()` per off-air game, seeded
   `random.Random(f"box:{season}:{day}:{hk}:{ak}")`. Event-mode `_sim_span` costs
   ~2–4 ms/game in CPython (measured envelope: ~300 rate segments + ~25 events);
   8 games ≈ **25–35 ms**.
4. **Fold** — `fold_box` into stats.json + extended standings (rw/row/gf/ga/streaks);
   milestone detection (career thresholds, hat tricks, shutouts); (~10 ms).
5. **Injuries** — `injury_roll` per game (log-normal, median 7 days: 50% ≤7d, 30%
   8–30d, 15% 31–90d, 5% 90+; 25–35 events/team/season calibrated) → out-list with
   IR/LTIR tagging; (~2 ms).
6. **Transactions** — date-seeded: `propose_trades` (hazard shaped to land 60–100
   trades/season with a 15–25 deadline-day spike at league-day ~124),
   `coach_hazard` (Poisson λ≈5.5/season, concentrated days 40–130), waiver moves;
   each validated against cap + roster rules; (~5 ms).
7. **Phase transitions** — day 171: seed bracket; playoff days: `series_slate` +
   advance; day 206+: offseason script; rollover check (§8).
8. **Persist & publish** — write box/<D>.json, stats.json, schedule.json,
   season.json (~700 KB total JSON dump ≈ 60–90 ms), then `export()` + leaders.json.

**Day-boundary total: ≤ 300 ms** on one core — invisible next to Kokoro. **Catch-up**
after downtime is capped at 20 league-days per tick pass (≈ 6 s worst case), looping
across passes until current; determinism guarantees the result is identical to having
never been down.

---

## 7. Migration plan from the live season-1 state

Run by `scripts/migrate_league_v2.py` (idempotent; writes v2 shards, never edits
legacy fields). Aired canon preserved by construction:

1. **Standings**: copied verbatim — v2 extended fields (gf/ga/rw/row) are *derived*:
   slates (all ≤30 days old, so complete) give every final; RW vs ROW for OT-flagged
   wins is assigned by date-seeded coin (grounding: ~50/50 OT/SO), which contradicts
   nothing aired (broadcast games retain their exact `ot`/`so` flags from the log).
2. **Rosters**: for each team, `gen_full_roster(..., pinned=_roster(key, 1))` — the
   aired/derivable 9 names are **pinned**: skaters 1–3 (the star trio the draw
   favored) become L1, skaters 4–8 fill L2 and pair 1, the goalie becomes G1. 14 more
   players generated around them, attribute-tuned so `attr.team_strength` reproduces
   `_strength(key, 1)` within ±0.01 — standings trajectories stay continuous. Doug
   Bouchard and Rene Tremblay keep their names, get ages, contracts, and careers.
3. **Schedule retrofit**: `build_schedule(played_prefix=…)` takes every game already
   in `slates` + `games` as a fixed prefix (~40 games) and fills the remaining matrix
   to exact bucket counts; any prefix pair already over its bucket borrows from an
   adjacent bucket, keeping 82 GP/team and 41H/41A (±1 tolerated, logged).
4. **Retro box scores**: broadcast games 1–2 harvested from their livegame logs (real
   aired scorers get real credit); every off-air final expanded via `expand_final`
   (seeded, final-preserving). Stats.json now shows a complete, checkable 4-day
   history — the aired world gains depth, loses nothing.
5. **Staff, contracts, prospects** generated fresh (none aired). Arena names for the
   30 non-tracked teams ship as a curated canon table in `engine.py` (tracked arenas
   unchanged).
6. Verification suite (§11) runs against the migrated state before the gate flips;
   the migrator prints a canon-diff report (must be empty: standings, aired names,
   game finals).

---

## 8. Feature gate + cutover + instant fallback

- **Gate**: `config.yaml → league_v2: true`, read per-call in `season.py` (no restart
  needed). Off → the untouched legacy code paths (kept as `_legacy_*` functions) run
  exactly as today.
- **Dual-write**: with the gate ON, the v2 engine still maintains every legacy field
  of season.json (league table, slates as `[hk,ak,hg,ag,ot]` derived from the real
  schedule, games dict, out lists as name-keyed entries). Therefore **fallback =
  flip the flag**; the legacy engine resumes from a season.json it fully understands,
  mid-season, no data surgery. v2 shards go quiescent but keep their state for
  re-enable (re-enable runs a reconcile that replays any legacy-only days
  deterministically).
- **Cutover sequence (before Saturday 20:00)**: (1) deploy code, gate OFF — zero
  behavior change; (2) run migrator on the box against live state (seconds); (3) run
  `verify_league.py` (canon-diff + invariants + fast calibration); (4) flip gate ON
  during a non-Center-Ice daypart; (5) watch two tick cycles + one export; (6) Saturday
  airs on v2. Any failure at any step: flag OFF, ship as-is Saturday.
- **Rollover air-gating (bug fix, both modes)**: season end is decided in `tick`, not
  `record_live`. Condition: all games final AND (no livegame log for a current game
  whose `final_air_at` is unset or in the future). Same rule gates playoff-round
  advancement lines and the championship announcement into `export`. The legacy
  rollover branch in `record_live` is deleted under v2; under legacy mode it gains the
  same air-check (3-line patch) so the known bug is fixed even on fallback.

---

## 9. Phased build order for TONIGHT

Every component is a pure function against the §2 schemas — independently buildable
and testable in parallel. Order = dependency tiers:

**Tier 0 (schema freeze, 30 min, blocking)**: check in `docs/designs/schema-v2.md` +
`tests/fixtures/` (one hand-written players.json/schedule.json/box fixture).

**Tier 1 (parallel, no cross-deps)**:
- `gen.py` — `gen_player/gen_full_roster/gen_staff`. Tests: attribute distributions
  vs depth-curve targets (L1 PPG 0.80–1.15 … L4 0.10–0.25 via expected-points
  formula), pinned names always survive, strength reproduction ±0.01, 10k-player name
  uniqueness per team.
- `sched.py` — `build_schedule`. Tests: exact bucket counts (26/24/32), 41H/41A,
  prefix respected, B2B sets/team ∈ [10,16], no team 3 games in 3 nights, tracked
  `kind:"air"` games land on wall Wed/Sat, breaks empty.
- `attr.py` — weights/draws/aging. Tests: A:G ratio 1.45–1.55 over 100k draws; aging
  monotone rise-then-fall with peaks F 24–28 / D 26–29 / G 28–30.
- `econ.py` validators (`cap_table`, `validate_trade`). Tests: ceiling/floor/20%-max
  rules; crafted illegal trades all rejected with reasons.
- `playoffs.py`. Tests: 2024-25-shaped standings fixture seeds the exact real bracket
  shape; advance() over scripted results; no reseeding after R1.
- `sheets.py` templates (consume fixtures). Tests: golden-file sheets; every number in
  a sheet traceable to a fixture field (regex audit — the guardability test).
- **Owner-facing**: trophy shortlist + arena canon table (curation, not code).
- `scoreguard`/`nameguard` **compat tests**: run existing guard test corpus against a
  v2-shaped game dict — must pass unmodified.
- livegame additive patch (weighted draws, assist2, per-side SA) behind
  `"weights" in rosters` — existing livegame tests must pass with legacy rosters.

**Tier 2 (needs tier 1)**:
- `boxgen.py` — `sim_game/expand_final/harvest_live_log`. Tests: 10k sims hit §11
  envelopes; `expand_final` never alters final/ot/so (property test over random
  finals); harvest of a real recorded log reproduces its goal list exactly.
- `stats.py` — fold/leaders/milestones. Tests: fold idempotence (same gid twice =
  once), totals equal box sums, milestone firing at exact thresholds.
- `roster.py` — dress/injuries/callups. Tests: lineup always legal (12F/6D/2G) even
  under 8 simultaneous injuries; injury duration histogram matches the 50/30/15/5
  buckets; MGL/season mean ~195 SD ~85 over 100 simulated team-seasons.

**Tier 3 (integration, single-threaded)**: `engine.py` tick pipeline; `season.py`
facade + dual-write; migrator; `verify_league.py`; end-to-end test: migrate a copied
live-state fixture → tick 30 days → run full verification → flip gate off → legacy
tick still works on the resulting season.json.

**Tier 4**: `calibrate.py` full-season Monte Carlo (§11) and constant tuning.

Test strategy: pure-function unit tests (no disk), fixtures shared, plus one
`test_determinism.py` that runs the day pipeline twice from the same state and
asserts byte-identical shards.

---

## 10. Broadcast-layer contract

All sheets produced by `sheets.py`; every number in every sheet comes from a state
file, so scoreguard/nameguard can verify any claim. Feeds:

- **Pregame** — `pregame_brief(game)` (same signature): matchup + records + streaks;
  full line combos and D pairs; scratches and injury report with expected returns;
  confirmed starting goalies **with season lines** ("Vachon, 12-6-2, .911, 2.71");
  head-to-head season series; milestone watch ("Bouchard sits at 29 goals");
  division/wild-card standings; around-the-league slate with each game's storyline
  hook; last-meeting note. No outcome language (unchanged contract).
- **Intermission around-the-league (NAMED scorers)** — `intermission_sheet(date,
  air_secs)`: each off-air game gets a virtual clock = `air_secs - start_off`; the
  sheet reveals only box events with `secs ≤ virtual clock`: "In Regina it's 2–1
  Reasonable Doubts midway through the second — Vasseur with both." Because box
  scores are simmed at day start but *revealed* on a staggered schedule, games appear
  in progress all evening and finish at realistic times. All partial pairs are pushed
  into `context_pairs` so scoreguard allows them; scores-desk and website use the
  identical reveal function — one clock, no contradictions.
- **Postgame interviews** — `postgame_brief(game, final)` (same signature) grows a
  QUOTE-FACTS block: per-interviewee groundable facts only (tonight's line from the
  box, season totals after folding, streak/milestone flags, coach's record segment),
  plus explicit "may reference / must not invent" framing. Guards run in postgame
  mode with finals in `allow_pairs`.
- **Scores desk (other shows)** — `scores_desk(now)` → `data/league/scoresdesk.json`:
  yesterday's finals with one named star each, tonight's in-progress partials (same
  reveal clock), standings movers, one transaction line. Air-gated: broadcast-game
  entries obey `final_air_at` exactly as league.json does.
- **Website league page** — league.json (superset, §4) + `leaders.json` (top-10
  G/A/P, goalie SV%/GAA/SO, rookie leaders) + `box_index` linking per-day box shards
  copied under the web data dir; playoff bracket object during phase "po".
- **OT-past-window signal** — `data/league/ot-signal.json`:
  `{"date": "2026-07-11", "live": true, "period": "OT", "past_window": true,
  "written_at": 169…}`; written by the orchestrator when the live game is undecided
  and remaining air window < a period chunk; cleared on final. Scheduler reads it to
  hold the next show's start; the site shows "OVERTIME — coverage continuing."

---

## 11. Statistical calibration plan

Constants live in one dict (`league/constants.py: CAL`), seeded from livegame's
proven values plus new attribution knobs (scoring-weight Zipf exponent, assist split,
injury hazard, goalie quality spread). Verification is *automated and gating*:

1. **`scripts/calibrate.py --seasons 20`**: headless full seasons (26,240 games ×
   ~3 ms ≈ 80 s + folding ≈ 2 min total). Emits a scorecard of every SIMULATOR
   TARGETS row from `docs/sim-grounding/hockey-grounding.md`.
2. **Hard assertions (fail = no cutover)**: league GF/game 6.1 ± 0.15; team pts%
   spread (top .68–.73, cutline .56–.59, floor .30–.35, SD .08–.10); OT rate
   19–23%, SO share 9–12%; home win 53–55%; shutout rate 6.5–8.5%; Art Ross winner
   ∈ [118,148] in ≥ 16/20 seasons; 100-pt scorers 5–10; 40-goal 8–14; 30-goal 40–55;
   20-goal 110–135; A:G 1.45–1.55; goalie league SV% .899–.906; Vezina-tier winner
   .920–.930; starter GP 55–65 / backup 18–27; hat tricks 75–120; MGL mean
   165–225; trades 60–100; coach firings 2–9; max win streak ≤ 12 in ≥ 16/20 seasons.
3. **Tuning loop**: the two coupled knobs most likely to miss are the star-weight
   exponent (drives leader bands) and goalie spread (drives SV% tails). calibrate.py
   supports `--sweep knob lo hi n` to grid-tune; everything else inherits livegame's
   already-verified game-level behavior, so game-level targets should pass untouched.
4. **Continuous**: `verify_league.py` (fast mode, 3 seasons ≈ 20 s) runs in CI/tests
   and as the cutover gate; the nightly tick also asserts cheap invariants (points =
   2W+OTL, GP sums even, stats totals = box sums) and refuses to publish on violation
   (loud log, previous export stands).

---

## 12. Coaches / trainers / economics model

**Staff** (staff.json): per team a head coach, GM, trainer, drawn from the shared
name-bank. Coach: `{"style": {"off": +0.02..-0.02 def tilt, "pp": ±0.15 on PP_MULT,
"pk": ±}, "dev": 0.9–1.1, "tenure_days": n, "seat": 0..1}`. Effects are **small and
measurable**: `attr.team_strength` adds the coach tilt; PP/PK multipliers shade
special-teams conversion (keeps team PP% inside 14–29%); `dev` multiplies young
players' rise slope at season boundaries. Trainer: injury-duration multiplier
0.92–1.08 and return-variance. **Firing model**: seat heat = f(points pace vs
preseason expectation, streaks, tenure); date-seeded hazard calibrated to 4–8
in-season firings/league/season, concentrated league-days 40–130; replacement coach
generated (interim flag), narratable transaction line emitted. Hiring effects: small
honeymoon tilt (+0.01 for 10 games) — real, checkable, tiny.

**Contracts** (in players.json: `"contract": {"aav": 6.5, "yrs_left": 3, "type":
"std", "signed_s": 1, "ntc": false}`): cap ceiling **$95.5 M** season 1-2 (grounding
2025-26), growing +8%/season; floor 0.74×ceiling; league minimum $775 K; max single
hit 20% of ceiling; ELCs for draftees (3 yr, $975 K base). Roster cap-shape enforced
at generation: top 6–8 contracts 55–65% of cap, goalie ~9–11%/1–3%. **Mechanics
actually simulated**: cap compliance on every trade/call-up (`validate_trade` /
`cap_table`), IR/LTIR relief per grounding thresholds (≥10 games AND ≥24 days),
deadline logic, offseason: RFA (age <27 and <7 accrued) qualifying offers, simple
arbitration (comparable-based award, walk-away at $4.85 M scaled), UFA market where
cap-space teams bid seeded-deterministically, retirements (median 31 F/32 D, veteran
tail to 40) feeding retired.json and freeing cap. Explicitly simplified: no-trade
lists are a boolean, bonuses are cosmetic — invisible on radio, noted for later.

---

## 13. Playoffs + trophy

**Format (per grounding, exact)**: 16 qualifiers — top 3 per division (×4) + 2 wild
cards per conference; fixed bracket, no reseeding; all rounds best-of-7; home ice
2-2-1-1-1 by regular-season standing; A1–WC2, B1–WC1, 2–3 within division; East champ
vs West champ in the Final. Tiebreak order: pts% → RW → ROW → W → head-to-head (all
now tracked in extended standings). Off-air series simmed nightly per §5; tracked-team
games (or the designated marquee series if both tracked teams are out) air Wed/Sat as
Center Ice playoff broadcasts — `tonight_game` reads the bracket. Every playoff box
score is kept forever (history.json references). Conn-Smythe-equivalent, scoring-title
and goalie awards resolve on offseason D1 from stats.json — all listener-checkable.

**Trophy shortlist** (owner rejected "Apology Cup"):
1. **The Halvorsen Cup** — named for a fictional league founder, the Stanley pattern:
   instantly reads as real hockey lineage and gives history segments a person to cite.
2. **The Long Winter Cup** — evokes the league's northern geography (Thunder Bay to
   Saskatoon); "surviving the long winter" writes its own playoff copy.
3. **The Wending Cup** — quietly stitches the station's two universes together; civic
   crossover jokes for free, still plausible as a place-named trophy.
4. **The Fresh Sheet** — hockey slang for clean ice; playful in exactly the register
   of the team names while staying 100% hockey-native.
5. **The Milepost Cup** — a highway marker for a league of highway towns; fits
   Halfway's roadside cosmology and shortens well ("raising the Milepost").

---

## 14. Risk register

1. **Migration contradicts an aired fact** → migrator emits a canon-diff (standings,
   names, finals) that must be empty; cutover blocked otherwise; aired names pinned
   structurally, never generated over.
2. **Guards break on v2 game dicts** → rosters shape kept byte-compatible; guard test
   corpus re-run against v2 fixtures in Tier 1; new keys strictly additive.
3. **Day-boundary tick exceeds budget on the box** → measured cost budget per stage,
   20-day catch-up cap, stage timings logged; worst case the slate sim defers one
   pass (slates are start-of-day, hours before any sheet needs them).
4. **Leader-band calibration misses** (too many/few 100-pt seasons) → dedicated sweep
   knobs isolated from game-level constants; hard-gated by calibrate.py before
   cutover; fallback ships the old path, not a miscalibrated league.
5. **State-file corruption/partial write** → existing tmp+replace+.bak everywhere;
   shards carry `{"season", "day", "hash_prev"}` headers; determinism means any shard
   is reconstructable by replay (`scripts/rebuild.py --from-seeds`).
6. **Around-the-league reveal contradicts the website/scorebug** → one shared reveal
   function (single virtual clock) used by sheets, scores desk, and export; partial
   pairs always registered in `context_pairs`.
7. **Rollover/playoff transition spoils on air** (the known bug, generalized) → all
   phase transitions decided in tick behind the same `final_air_at` gate as scores;
   regression test simulates an unaired final at season end and asserts no rollover.
8. **Dual-write drift makes fallback unsafe** → `test_dualwrite.py` ticks v2 30 days,
   flips the gate, runs the legacy engine 5 days, asserts no exception and coherent
   standings; drift check (legacy fields recomputed from v2 state) runs inside
   verify_league.py.
