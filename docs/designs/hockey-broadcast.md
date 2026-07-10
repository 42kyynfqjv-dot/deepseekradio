# Hockey League Engine — Broadcast-Story-First Design

Design lens: start from every minute of air the station must fill and work backwards
to the minimal sim state that makes that air bulletproof and guard-verifiable.
**The narration sheets are the product.** Everything below exists because a
specific sheet needs it; anything no sheet needs is out.

## 1. Executive summary

The engine is grown, not replaced. `livegame.py`'s calibrated event model already
produces everything a box score contains — we run it in **event mode for every
off-air game** (measured: 0.17ms/game dev, ≤1ms on the box; a full 1,312-game
season with named boxes costs <2s). The new work is (a) a **real 82-game schedule
matrix** on a **league calendar compressed 2 league-days : 1 wall-day**, with
broadcast slots pinned to Wed/Sat; (b) **persistent players** (23+2 rosters, lines,
numbers, ages, per-slot scoring weights tuned to the grounding depth curve);
(c) **exactly-once stat folding** that is deterministic-replayable from the
schedule, so state loss never changes published history; (d) a **sheets module**
that renders every air surface — pregame, intermission around-the-league with
named scorers and *in-progress* out-of-town boards, postgame interview fact
cards, scores desk, website, OT-past-window signal — each sheet carrying its own
guard fact table; (e) economics/coaches/trades/draft/playoffs sized to what the
booth can narrate. `season.py` stays the facade: identical public signatures,
identical `game` dict keys, legacy state shadow-written every tick so fallback is
one config flag. Migration is a retro-attribution pass over the 4 days of already
-recorded slates: known finals get named scorers, aired names stay canon, and the
migrator asserts recomputed standings equal aired standings before it will cut over.

## 2. State schema

All files live under `data/league/`, atomic tmp+replace with `.bak` copy (the
established pattern). `season.json` (legacy) continues to exist — see §8.

**`data/league/meta.json`** (~1KB) — the phase machine and pointers:

```json
{"schema": 1, "season": 1, "phase": "regular",
 "epoch": "2026-07-07", "sim_through_day": 8,
 "cap": {"ceiling": 95500000, "floor": 70670000, "minimum": 775000},
 "trophy": "Boreal Lantern",
 "playoffs": null,
 "broadcast_anchor": {"next_wall": "2026-07-11", "league_day": 10, "team": "nyg"}}
```

**`data/league/schedule.json`** (~90KB, written once per season) — the full
1,312-game matrix. One row per game:

```json
{"id": "s1-0412", "day": 63, "home": "mtl", "away": "hfx",
 "slot": "offair"}            // or "broadcast"
```

Generated deterministically from `f"sched:{season}"`; regenerating from seed
reproduces it bit-for-bit (self-healing).

**`data/league/rosters/{team}.json`** (32 files, ~14KB each, ~450KB total) —
identity + attributes + contracts; rewritten only on transactions/injury changes:

```json
{"team": "mtl", "coach": {"name": "Marcel Thibodeau", "style": "defensive",
   "bias": -0.015, "dev": 0.6, "hired_day": -30, "seat": 0.12},
 "trainer": {"name": "Peg Sorensen", "heal": 0.92},
 "players": [
  {"pid": "mtl-s1-01", "name": "Doug Bouchard", "num": 19, "pos": "C",
   "age": 27, "hand": "L", "home_town": "Trois-Rivieres",
   "slot": "F1", "shoot": 0.86, "play": 0.91, "dfns": 0.55,
   "contract": {"aav": 9800000, "years": 4, "kind": "UFA"},
   "draft": {"season": -6, "round": 1, "pick": 4},
   "status": "active",                       // active|ir|ltir|reserve|prospect
   "injury": null,                            // or {"note":"lower body","day_back": 71}
   "career": {"gp": 402, "g": 168, "a": 231}},
  {"pid": "mtl-s1-21", "name": "Rene Tremblay", "num": 31, "pos": "G",
   "age": 29, "slot": "G1", "save": 0.88, "contract": {"aav": 6100000, "years": 2},
   "career": {"gp": 240, "w": 121, "so": 14}}
 ],
 "lines": {"F1": ["mtl-s1-01","mtl-s1-02","mtl-s1-03"], "F2": ["…"],
           "D1": ["…","…"], "G": ["mtl-s1-21","mtl-s1-22"]}}
```

23 active + 5 reserve + 8 prospects = 36 players/team ≈ 1,150 league-wide.

**`data/league/stats.json`** (~120KB, rewritten once per newly-simmed league
day) — the season accumulators, one compact row per player who has appeared,
plus standings:

```json
{"season": 1, "through_day": 8,
 "standings": {"mtl": {"w":2,"l":1,"otl":1,"gp":4,"rw":2,"row":2,"streak":1,
               "gf":14,"ga":11,"pts_hist":[0,2,2,3,5]}, "…": {}},
 "skaters": {"mtl-s1-01": {"gp":4,"g":3,"a":4,"pim":2,"ppg":1,"gwg":1,
             "shots":13,"streak_pts":3}},
 "goalies": {"mtl-s1-21": {"gp":3,"w":2,"sa":88,"sv":81,"so":1}},
 "milestones": [{"day":8,"pid":"dul-s1-04","text":"Larsson's 20th of the season"}]}
```

`pts_hist` (one int per league day) powers "they've won 7 of 10" booth talk and
costs 182 ints/team/season.

**`data/league/box/{day:03d}.json`** (~10KB per league day, ~7 games each) —
the around-the-league product. Per game:

```json
{"id": "s1-0412", "home": "hfx", "away": "dul", "final": [4,2], "ot": false,
 "so": false, "shots": [31,27], "att": 11408,
 "goalies": {"home": "hfx-s1-21", "away": "dul-s1-22"},
 "goals": [{"secs": 512, "period": 1, "clock": "8:32", "team": "away",
            "scorer": "Sven Larsson", "assist": "Curtis Ostberg",
            "strength": "EV", "board": [0,1]}, "…"],
 "stars": ["Sven Larsson", "…", "…"]}
```

**Pruning:** keep the last **14 league days** of full boxes, plus every
tracked-team box all season (the booth references "last Wednesday"), plus a
finals-only ledger appended to `data/league/results-{season}.jsonl`
(~50B/game, 66KB/season, never pruned — it is the deterministic-replay record
and the head-to-head table). Worst-case disk: ~1MB/season. Live broadcast
boxes (fresh entropy, non-replayable) are additionally folded into
`results-*.jsonl` and their boxes retained all season.

**`data/league/news.jsonl`** (ring-pruned to 200 lines) — transactions, coach
firings, milestones, injuries of note, each pre-written as a one-line fact the
booth may read verbatim: `{"day": 41, "kind": "trade", "text": "…", "teams": [...]}`.

**`data/ot_signal.json`**, **`data/league/scoresdesk.json`**,
**`web league.json`** — see §10.

## 3. Module & file breakdown

New modules are stdlib-only, import `livegame` only for the model, and are
**pure** unless named otherwise. `season.py` remains the only stateful facade.

- **`src/leaguecal.py`** — the calendar (pure):
  - `league_day(wall_date: str, epoch: str) -> int`
  - `phase_of(day: int) -> str` — `"regular"|"playoffs"|"offseason"` boundaries
  - `broadcast_slot(wall_date: str) -> int | None` — league day pinned to a Wed/Sat
  - `deadline_day() -> int`, `season_length() -> int` (182)
- **`src/leaguegen.py`** — generation (pure, seeded):
  - `gen_players(season: int, team: str, keep: list[dict]) -> dict` — full shard;
    `keep` = aired-canon players that must survive verbatim
  - `gen_schedule(season: int, anchors: dict[int, str]) -> list[dict]` — the
    26/24/32 matrix, 41H/41A, anchors pin tracked-team games to broadcast days
  - `NAME_BANK: tuple[str, str]` — expanded first/last pools (superset of
    `livegame.FIRST_NAMES/LAST_NAMES`; nameguard unions this)
- **`src/boxscore.py`** — one model, third speed (pure):
  - `sim_box(sched_game, home_shard, away_shard, rng) -> dict` — event-mode
    `livegame._sim_span` with attribute-weighted draws → §2 box shape
  - `retro_box(final: tuple, ot: bool, shards, rng) -> dict` — attribution pass
    for migration: given a known final, generate a consistent scoring summary
  - `snapshot(box, at_secs: int) -> dict` — the in-progress out-of-town board:
    goals with `secs <= at_secs` only
- **`src/rosterops.py`** — roster churn (pure transforms on a shard):
  - `roll_injuries(shard, day, events, rng) -> shard` — log-normal durations per
    grounding buckets; IR/LTIR status; `day_back`
  - `dress(shard, day, rng) -> lineup` — 18 skaters + starter (60/22 rotation) + backup;
    emergency call-ups from reserve when <12F/<6D/<2G healthy
- **`src/frontoffice.py`** — economics & people (pure):
  - `coach_hazard(team_stats, coach, day, rng) -> bool` (fire?), `hire_coach(rng)`
  - `gen_trades(state_view, day, rng) -> list[trade]` — needs-based, deadline spike
  - `run_draft(state_view, rng) -> list[pick]`, `offseason(state_view, rng)` —
    aging, retirements, re-signings, cap compliance
- **`src/playoffs.py`** (pure): `seed_bracket(standings) -> bracket`,
  `series_state(bracket, results) -> dict`, `next_playoff_games(bracket, day) -> list`
- **`src/sheets.py`** — the product (pure renderers, one per air surface):
  - `pregame(game, view) -> str`, `intermission(game, view, at_secs) -> str`,
  - `postgame_cards(game, final, view) -> str` (interview fact cards),
  - `scores_desk(view, now) -> dict`, `website(view, now) -> dict`,
  - `guard_pairs(view, at_secs) -> list[tuple]` — every legally-mentionable pair
- **`src/season.py`** (changed, stateful) — facade: same seven public functions,
  a `_V2` gate, the v2 tick, shadow-write of legacy `season.json`, migration
  entry point `migrate_v2()`. Internally holds `_load2()/_save2()` per file.
- **`src/livegame.py`** (minimally changed) — `_draw_skater` honors an optional
  `roster["weights"]` list (parallel to `skaters`); absent → old behavior. No
  other change: the live engine is untouched otherwise.

## 4. Interface preservation

- **`tonight_live(date)`** — same signature; returns the same dict with every
  existing key (`game_no, date, rivalry, season, home, away, home_key, away_key,
  arena, recorded, rosters, returning, strength_home, strength_away, refs,
  subplot, attendance`). `rosters` keeps the exact guard shape —
  `{home/away: {skaters: [18 names], goalie: name}}` — ordered lines-first so
  the existing "first 3 are stars" heuristic degrades gracefully; adds NEW keys
  only: `rosters["home"]["weights"]`, `numbers`, `lines`, `scratches`,
  `goalie_backup`. `strength_home/away` still floats in [0.30,0.70] (now derived
  from roster quality + coach bias, not a bare hash). Game selection comes from
  `schedule.json`'s broadcast slot instead of ad-hoc pairing; `rivalry` is true
  on the 3 scheduled mtl–nyg meetings (pinned to broadcast slots).
- **`record_live(date)`** — same; folds the final into v2 standings *and* player
  stats (from the live log's events), appends to `results-*.jsonl`, writes the
  live box, shadow-writes legacy. **Rollover logic removed from here** (§8 bug fix).
- **`tick(date)`** — same; §6.
- **`export(path)`** — same signature, same air-gating discipline (narrated
  `air_at` reveals; `_display_league` un-apply preserved), payload extended (§10).
- **`pregame_brief/postgame_brief/context_pairs`** — same signatures; internally
  delegate to `sheets.py`. `context_pairs` now returns the union of: last
  broadcast final, all *prefix boards* of tonight's slate boxes (so an
  in-progress out-of-town score is always a legal pair), and yesterday's finals.
- **Guard fact shapes** — `build_facts` consumes `game["rosters"]`, refs,
  tallies unchanged. New surnames enter `names_ok` automatically via rosters.
  The one required orchestrator edit: `pool_ok` unions `leaguegen.NAME_BANK`
  (one line, gated) so nameguard never scrubs a league name from a sheet.
- **Old path**: every v1 function body is preserved intact behind the gate
  (`if not _V2: return _v1_tonight_live(...)`).

## 5. League calendar mapping

**Choice: 2 league days per wall-clock day** (`league_day = 2*(wall - epoch) [+1
for the evening half]`), broadcast games pinned to the *evening* league day of
Wednesday and Saturday.

Justification, worked backwards from air:

- The current league already plays every wall-clock day and listeners have heard
  4 days of it; a 1:1 map would make a season run ~6 months — drafts, trades and
  careers would be annual events a daily listener barely lives through. 2:1
  gives: regular season 182 league days = **91 wall days (~13 weeks)**, playoffs
  ~9 league weeks = **~4.5 wall weeks**, offseason (draft, free agency) compressed
  to **~5 wall days** of dense news. A full league year ≈ **4 months** — ~3 cycles
  a year of Cup runs, deadline drama, and draft nights *on air*, while a single
  week still feels like a real hockey week.
- Tracked teams play ~3.2 games per league week = ~6.4 per wall week, of which
  exactly 2 are broadcast — precisely a real radio affiliate airing select games.
  Off-air tracked games get full boxes, so the pregame can honestly recap
  "since Wednesday, the Apologies played twice."
- Slate size per wall day: 1,312/91 ≈ **14.4 games** (~7.2/league day) — the same
  order as today's ~10/night; the scores desk stays readable.
- Calendar texture per grounding, expressed in league days: holiday break days
  157–162 (≈Dec 24–26 ×2), staggered 8-league-day byes, trade deadline on the
  league day mapping to "first Friday of March" (day ~122), no games on the two
  league days before playoffs. Back-to-backs emerge naturally (~12 sets/team) from
  matrix packing and apply the −6% fatigue multiplier in `sim_box`.
- The mapping is pure arithmetic off `meta.epoch` — deterministic, no stored clock.

Anchor constraint: `gen_schedule` receives `{league_day: team}` for every Wed/Sat
evening slot in the season (alternating mtl/nyg; the 3 head-to-heads placed on
rivalry-cadenced slots) and places those fixtures first, then fills the matrix
around them. Feasibility is trivial (≈26 pinned fixtures of 82×2).

## 6. The nightly tick algorithm

`tick(air_date)` every main-loop pass:

1. `today = leaguecal.league_day(air_date)` (evening half). If
   `meta.sim_through_day >= today`: skip to step 7. Steady state hits this branch
   on all but the first pass after a boundary — **cost ~2ms** (one small JSON read).
2. For each pending league day `d` (capped at **20 per tick** to bound catch-up;
   remaining days complete on subsequent passes seconds later):
   a. `dress` both lineups for each scheduled game (injury returns, goalie
      rotation, call-ups) — pure, seeded `f"dress:{season}:{d}:{game_id}"`.
   b. For every non-broadcast game: `sim_box(...)` with rng seeded
      `f"box:{season}:{game_id}"` — deterministic, self-healing. Broadcast-slot
      games are **skipped** (the live engine owns them; `record_live` folds them).
   c. Fold each box exactly once into `stats.json` accumulators + standings
      (+`results-*.jsonl` append); run milestone detection against thresholds.
   d. `roll_injuries` per team from box injury events + off-ice log-normal draws.
   e. Windowed events: trade generation (rate shaped to deadline), coach-hazard
      check (λ≈5.5/season, concentrated days 40–120), waiver/call-up bookkeeping
      → `news.jsonl`.
   f. Phase machine: at day 182 seed the bracket; in playoffs schedule next
      series games; after the Cup final's **broadcast final has aired**, run
      offseason (draft, aging, retirements, re-signings) and roll `season`.
3. Write `box/{d}.json`, rewrite `stats.json`, touched roster shards, `meta.json`.
4. Prune boxes (>14 days, non-tracked), news ring.
5. Shadow-write legacy `season.json` (standings mirrored into the v1 shape).
6. `_reconcile(air_date)` — unchanged sweep of live logs.
7. `export()` + `scoresdesk.json` + `ot_signal` refresh (air-gated as today).

**Cost on 2 vCPU:** measured event-mode sim = 0.17ms/game on dev; assume 4×
slower on the box → 0.7ms. One league day = 7.2 games ≈ 5ms sim + ~15ms JSON
rewrite (stats 120KB + shards) + folding ≈ **~25ms/league day**; a normal day
boundary sims 2 league days ≈ **50ms**. Worst catch-up (box down a week → 14
league days) = one tick of ~350ms, well under the sub-second budget; the 20-day
cap makes even a month-long outage a 3-pass, <1s-each recovery. Full-season
verification sims (§11) run 1,312 games ≈ 1–2s — offline only.

## 7. Migration plan from the live season-1 state

Everything aired is canon; everything else is free. The 4-day-old state gives us
more than standings — `st["slates"]` still holds **every off-air final** (season
is younger than the 30-day prune) and `data/livegame-*.jsonl` holds the two
aired games' full event logs (14-day retention). So we migrate *facts*, not
just tallies:

1. **Freeze canon** (read-only pass): legacy standings table, slate results per
   date, aired game logs (games 1–2: scorers, assists, goalies, penalties,
   finals), the 9 aired roster names per tracked team, out-lists, `last_result`.
2. **Epoch & pre-canon window**: set `epoch` so that today maps to league day
   `K = 2 × (days since season start)` (≈8). Generate the season-1 schedule with
   broadcast anchors; then **overwrite days 1..K's fixtures with the actual
   historical pairings** from the frozen slates (the matrix generator treats
   them as already-consumed matchups and balances the remaining 174 days —
   home/away and opponent counts stay exact).
3. **Rosters**: `gen_players(1, team, keep=aired_names)` — for mtl/nyg the 9
   aired names become the top-line skaters and starting goalie (identities,
   numbers, ages minted around them; e.g. Doug Bouchard stays Doug Bouchard,
   now C, #19, F1); 30 non-tracked teams mint fresh 36-man shards. Any player
   named in an aired injury/out-list keeps that status with a duration drawn
   per grounding.
4. **Retro-attribution**: for every pre-canon game, `retro_box(known_final, …)`
   generates a named scoring summary consistent with the recorded score (rng
   seeded off the game id — rerunnable). Aired tracked games use the **actual
   live-log events verbatim** instead. Fold all of it → `stats.json`,
   `results-1.jsonl`. Players now have 4 days of season stats that agree with
   the standings a listener heard.
5. **Verify before arming** (the migrator refuses to set the gate otherwise):
   recomputed standings **==** legacy `season.json` table field-for-field; every
   aired name present and in the same team's shard; tracked GP == legacy GP;
   schedule matrix property-checks pass; `build_facts` on a synthetic game from
   the new state produces a superset of the old `names_ok`.
6. Write `data/league/*`, leave `season.json` untouched (it is the fallback),
   print a diffable migration report. Idempotent: re-running from the same
   inputs reproduces identical files.

## 8. Feature gate + cutover + instant fallback

- **Gate:** `config.yaml → sim: {league_v2: false}` read once per call in
  `season.py`. Every public function branches at the top; v1 bodies are kept
  whole. `livegame` weight support keys off the game dict (`"weights" in
  roster`), so v1 games never touch new code.
- **Shadow mode (tonight → Saturday):** with the gate off, `tick()` additionally
  runs the v2 tick in *shadow* (writes `data/league/*`, never `season.json`,
  never the website). A `scripts/shadow_diff.py` cron compares v2 standings vs
  v1 hourly; any mismatch is loud in logs.
- **Cutover (Saturday ~10:00, ten hours before air):** run `python -m src.season
  migrate` → verification suite (§9/§11 fast tier) must pass → flip
  `league_v2: true` → restart loop → eyeball `pregame_brief` output for
  Saturday's game + website payload. Ten daytime hours of non-broadcast shows
  exercise scores-desk sheets before the puck drops.
- **Instant fallback:** flip the flag back and restart (<30s). Because v2
  shadow-writes the legacy `season.json` shape every tick while live, v1 resumes
  with current standings — no state surgery. Live game logs are engine-agnostic
  (same chunk shapes), so a mid-broadcast fallback resumes the same game.
- **Rollover air-gating (bug fix, both paths):** season increment moves out of
  `record_live` into the tick phase machine, which advances only when (a) the
  deciding game's `final_air_at` has passed, and (b) no live log for today is
  unfinished. The "that's the season" reveal becomes a sheet line, not a state
  side-effect. v1's hard rollover branch is disabled behind the same gate
  check so fallback can't re-trigger it mid-air.

## 9. Phased build order for TONIGHT

P0 is serial (~1h); P1 components are **pure functions against the frozen §2
schemas** — fully parallelizable across sessions/agents; P2–P4 serialize again.

**P0 — freeze contracts (serial):** commit this doc's JSON shapes as
`tests/fixtures/schema_*.json`; implement `leaguecal.py`
(`league_day/phase_of/broadcast_slot/deadline_day`). *Test:* table-driven
wall→day cases incl. epoch edges, DST-free date math.

**P1 — parallel pure components:**
- **A. `leaguegen.gen_schedule(season, anchors) -> list[dict]`** — *Test:*
  property suite: every team exactly 82, 41H/41A, division 5×4+2×3, conf 8×3,
  cross 16×2; anchors honored; ≤1 game/team/day; B2B count 7–16; deterministic
  across two calls.
- **B. `leaguegen.gen_players(season, team, keep) -> shard`** — *Test:* schema
  validation; `keep` names survive verbatim in top slots; age distribution mean
  ≈27.6; cap-shape of minted contracts within §12 bands; unique numbers.
- **C. `boxscore.sim_box / retro_box / snapshot`** — *Test:* 5,000-game Monte
  Carlo asserting §11 game-level envelopes; `retro_box` final always equals the
  requested final; `snapshot(box, 3600)` == full regulation goals; every scorer
  drawn from the dressed 18.
- **D. `rosterops.roll_injuries / dress`** — *Test:* 32-team×182-day rollout →
  MGL mean 195±40, duration bucket shares per grounding; dress always yields
  12F/6D/2G or an emergency call-up event; goalie split 55–65/18–27.
- **E. `frontoffice.*`** — *Test:* 20-season rollout → 4–8 firings/season,
  60–100 trades with deadline spike 15–25, cap compliance invariant after every
  transaction, offseason keeps 23-man legality.
- **F. `playoffs.*`** — *Test:* seeding matches grounding format on fixture
  standings; bracket never reseeds; 2-2-1-1-1 home pattern; series terminate.
- **G. `sheets.*`** — *Test:* golden-file sheets from a fixture state; a
  guard-compat test runs `build_facts`+`enforce_scoreboard` over each sheet's
  own text — **a sheet that trips its own guard fails CI**.
- **H. `boxscore` calibration harness** `scripts/calibrate_league.py` (§11).

**P2 — facade integration (serial):** v2 branches in `season.py` (tick loop,
tonight_live from schedule, record_live stat folding, shadow legacy write,
export). *Test:* end-to-end fixture season fast-forwarded 200 wall days in
tmpdir; interface snapshot test asserts `tonight_live` keys ⊇ v1 keys.

**P3 — migration (serial):** `migrate_v2()` + verification suite per §7. *Test:*
run against a copy of the production `season.json`+logs pulled from the box.

**P4 — shadow run overnight, cutover Saturday morning (§8).**

## 10. Broadcast-layer contract

Every surface is a **code-rendered sheet with its own fact table**; the LLM
never sees raw state.

- **Pregame (15 min)** — `sheets.pregame`: matchup + records + last-5 shapes
  (`pts_hist`); storyline block (streaks ≥3, milestone watch within 2, coach on
  hot seat, deadline countdown); **lineups**: line combos with numbers,
  scratches, injured w/ timeline; **starting-goalie confirmation** as its own
  labeled beat (season W-L, SV%, GAA to 3/2 decimals from integer sa/sv);
  tonight's around-the-league slate (opponents only, no outcomes — they haven't
  "happened" in air time); standings tables. Guard: facts as today, `allow_pairs`
  from `sheets.guard_pairs(view, 0)`.
- **Intermission around-the-league (1–2 min/period)** — `sheets.intermission
  (game, view, at_secs=tracked game elapsed)`: for 3–4 slate games,
  `snapshot(box, at_secs)` yields honest *in-progress* boards with **named
  scorers**: "In Duluth, Larsson has two — Dial Tones 3, Regrets 1, midway
  through the second." Finals never leak early because reveal is clocked to the
  tracked game. Guard: every snapshot prefix pair is in `allow_pairs`; scorer
  surnames are added to `names_ok` for that beat only.
- **Postgame interviews** — `sheets.postgame_cards`: per interviewee (1 player
  per team + both coaches) a fact card — tonight's line (G-A, shots, the goal
  clock/strength), season totals, streak, one team context fact, and an explicit
  "may reference ONLY these" header. Coach card adds special-teams counts and
  the standings delta. Guard: postgame mode facts + card-scoped tallies, so a
  quote can't invent a stat the box doesn't hold.
- **Scores desk (other shows)** — `data/league/scoresdesk.json`, air-gated like
  `export()`: `{"updated", "last_night": [finals w/ one named star each],
  "tonight": [slate], "standings_lines": [3 code-written sentences],
  "leaders": {"points": [top5 name/team/P], "goals": [...], "sv": [...]},
  "news": [top 3 news lines]}` — any show reads it verbatim; scoreguard
  `allow_pairs` ships inside the file.
- **Website league page** — `export()` payload gains `leaders`, `boxes`
  (yesterday, pruned view), `schedule_next7`, `playoffs` bracket when live,
  `news`; existing keys unchanged, same listener-time gating.
- **OT-past-window signal** — `data/ot_signal.json`, written by the live path
  every advance: `{"date", "state": "none|ot_likely|past_window", "period",
  "board", "updated"}`; scheduler/site poll it to stretch the window or swap
  the follow-on show.

## 11. Statistical calibration plan

Constants live in two named blocks: `livegame.py` (game model — untouched) and
`leaguegen.py` (attribute/weight model — new). The weight model maps roster
slots to draw weights: goals distribute over the 18 dressed skaters ∝
`shoot × TOI(slot)` with TOI factors (F1 1.00, F2 0.72, F3 0.45, F4 0.20,
D1 0.38, D2 0.24, D3 0.12) — targeting the grounding depth curve (L1 0.80–1.15
PPG … D3 0.08–0.20); assists drawn 1.5 per goal, playmaking-weighted.

- **Harness:** `scripts/calibrate_league.py --seasons N --seed S` sims N full
  seasons headless (~2s each) and prints every consolidated grounding target
  vs. observed, with pass/fail envelopes: team GF 3.05±0.4, OT 21%, SO ~10–11%,
  home win 54%, shutouts 7.5%, EN ~7% of goals, Art Ross 118–148, 100-pt count
  5–10, 40-goal 8–14, 30-goal 40–55, 20-goal 110–135, A:G 1.45–1.55, hat tricks
  75–120/season, SV% .899–.906, starter GP 55–65, top team 112–120 pts, cutline
  92–97, cellar 50–58, max streak envelope, MGL 195±85.
- **Verification tiers:** *fast* (CI + cutover blocker): 5 seasons, wide
  envelopes, ~15s. *Nightly:* 100 seasons, tight envelopes, run via cron on the
  dev machine, drift alarms into logs. Tuning iterates only `leaguegen`
  constants; the live game model's already-verified envelopes are asserted, not
  retuned — one model, never forked.
- **Live-vs-slate parity test:** 2,000 games through `sim_box` vs 2,000 through
  the chunked live path with identical strengths — distributions must be
  statistically indistinguishable (KS test on goals/shots), preserving the
  "tracked teams look like their peers" invariant.

## 12. Coaches / trainers / economics model

Sized to narratability: every mechanism must produce a sheet line and a
groundable consequence, nothing more.

- **Coach:** `{name, style, bias, dev, seat, hired_day}`. `bias` ∈ [−0.02,+0.02]
  shifts effective team strength (defensive coaches −GF/−GA via a paired
  multiplier in `sim_box`); `dev` scales prospect/young-player attribute growth
  at season roll. `seat` (hot-seat 0–1) recomputed weekly from pts% vs.
  preseason expectation (strength percentile); firing draw calibrated to λ≈5.5
  league-wide/season, days 40–120. Firing → news line, interim coach minted,
  small honeymoon bump (+0.01 for 10 league days) — the classic narratable
  "new-coach bounce."
- **Trainer:** `{name, heal}` ∈ [0.85,1.15] multiplies injury durations —
  measurable in MGL, mentionable in injury beats.
- **Cap mechanics:** ceiling $95.5M season 1, +8%/season; floor = 0.74×ceiling;
  league minimum $775K; max hit 20% of ceiling. Contracts `{aav, years, kind}`;
  ELC for prospects (3yr, $975K). Cap invariant (Σ active AAV ≤ ceiling; ≥ floor)
  is a tick assertion; LTIR relief = replacement AAV while status=ltir. **Not
  modeled** (no air surface, per lens): bonus overages, variance rules,
  arbitration hearings, waiver claim priority — the vocabulary appears in news
  lines, the ledger stays simple.
- **Trades:** buyer/seller identities from standings position after day 60;
  value bands from (attributes, age, aav); generator emits 60–100/season with
  the deadline-day spike. Tracked-team trades are **embargoed one broadcast**:
  the news line airs ("sources say…") before the roster shard changes, so no
  aired lineup ever contradicts a transaction.
- **Draft & offseason:** 7 rounds ledgered, round 1 narrated pick-by-pick as an
  offseason special sheet; lottery per grounding odds over the 16 non-playoff
  teams (max 10-spot fall). Aging at season roll per grounding curves (F peak
  24–27, D 26–29, G 28–30; decay draws), retirements 32+ hazard, re-sign/UFA
  pass keeps every team 23-legal and cap-legal or forces a corrective trade.

## 13. Playoffs + trophy

Format straight from grounding: top 3 per division + 2 wild cards per
conference = 16; fixed bracket, no reseeding; all rounds best-of-7, 2-2-1-1-1
with home ice by points%; tiebreaks pts% → RW → ROW → W → head-to-head (from
`results-*.jsonl`). Playoff league days run series games every other league day
(one wall day ≈ one game per live series — nightly playoff scores desk). If a
tracked team is alive, Wed/Sat broadcasts are its games (schedule anchors
continue); if both are out, the broadcast carries a **featured series** game on
the live engine — same interface, `arena` = the neutral call ("on the road"),
and the pregame sheet frames it as national coverage. Non-broadcast playoff
games sim through `sim_box` with an OT-until-decided loop (no shootouts).
The Cup final's deciding game, if off-air, reveals per the standard air-gated
export; rollover waits per §8.

**Trophy shortlist** (owner rejected "Apology Cup"):
1. **The Boreal Lantern** — northern light carried through the long winter;
   "skating the Lantern" sounds instantly traditional on radio.
2. **The Halfway Cup** — the station's town; every team in this league is
   halfway to somewhere, which is the whole league's voice.
3. **The Long Winter Trophy** — names the shared condition the league exists to
   get its towns through; earns gravity without a person attached.
4. **The Last Horn** — the final horn of the year; broadcast-native, and the
   call writes itself ("they've sounded the Last Horn").
5. **The Overtime Kettle** — domestic-absurdist like the team names; a kettle
   that is always just about to boil is this league's emotional register.

## 14. Risk register

1. **Cutover breaks Saturday's broadcast** → gate + shadow-run overnight +
   10:00 cutover with 10h of daytime shows exercising sheets + one-flag
   fallback that resumes from shadow-written legacy state.
2. **Migration contradicts an aired fact** → migrator hard-asserts standings
   equality and aired-name presence and refuses to arm the gate on any diff;
   report is human-reviewed before the flag flips.
3. **Stat drift out of grounding envelopes** (e.g., an unairable 190-point
   scorer) → nightly 100-season harness with alarms; hard clamp in `sim_box`
   weight draws; envelopes are CI-blocking at cutover.
4. **Nameguard/scoreguard scrub or miss new-league names** → `NAME_BANK`
   unioned into `pool_ok`; sheet-self-guard CI test (every sheet must pass its
   own fact table); snapshot pairs pre-registered in `allow_pairs`.
5. **tick() catch-up spike after downtime** → 20-league-day per-pass cap;
   measured 25ms/league-day budget; worst month-long gap recovers in 3 sub-second
   passes.
6. **Determinism break** (state loss changes published history) → all off-air
   sims seeded off `(season, game_id)`; stats are pure folds of schedule-replay
   + `results-*.jsonl` (live games persisted, never re-rolled); a
   `scripts/replay_verify.py` recomputes stats from scratch and diffs.
7. **State-file growth/corruption** → per-file tmp+replace+.bak; box pruning to
   14 days + tracked; append-only results ledger 66KB/season; schema version
   field for forward migrations.
8. **Trade/firing generator produces a narrated absurdity** (star traded for
   nothing; coach fired the day after a win streak) → generators emit only from
   template-constrained, value-band-checked moves; every transaction line is
   code-written prose (LLM embellishes but the fact is fixed); tracked-team
   embargo prevents mid-air roster contradictions.
