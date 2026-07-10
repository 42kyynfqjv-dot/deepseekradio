# Design Brief — Full-Fidelity League + Statehouse Simulators

Input pack for the architecture design panel (2026-07-10). Read this whole file
before designing. Grounding numbers live in `docs/sim-grounding/*.md`.

## The bar (owner, verbatim intent)

**NHL-level: a listener could not tell this isn't a real league.** Same bar for
the Wending statehouse: procedurally indistinguishable from a real legislature.
The sim is the product; the shows are its broadcast layer. Code owns every
fact; the LLM only narrates; guards enforce.

## What already exists (read these files)

- `src/season.py` — a **32-team league already structured 2 conf × 2 div × 8**,
  82-game seasons, date-seeded off-air slates (~10 games/night, self-healing
  seeds), standings w/otl/streak/gp, injury out-lists, exactly-once result
  folding (`record_live`), reconciliation sweep, air-gated `export()` to
  `league.json` (the scorebug can never spoil). Teams/arenas/flavor are canon.
- `src/livegame.py` — the live game engine: ONE calibrated piecewise-Poisson
  model (named constants: BASE_EV, STRENGTH_EXP, HOME_EDGE, OT_MULT, PP_MULT,
  SH_MULT, SCORE_FX, EN_LEAD/EN_TRAIL, PEN_RATE, INJ_RATE, SHOT_FACTOR,
  SO_ATTEMPT_P) used at two speeds: the live append-only-log roll for broadcast
  games and `sim_instant()` for off-air slates. Goalie pulls, PP/SH/EN
  strengths, shootouts, injuries all modeled.
- `src/orchestrator.py` `run_center_ice()` — the broadcast driver (pregame /
  period chunks / intermissions / wrap / call-in / handoff beats; scoreguard +
  nameguard on every line; narration-anchored air-gating).
- `src/scoreguard.py`, `src/nameguard.py` — the truth guards. `build_facts`
  consumes `game["rosters"] = {home/away: {skaters: [names], goalie: name}}`,
  refs, tallies. Any roster deepening must keep feeding compatible fact tables.
- `station/bible.md`, `station/wending-bible.md` — station + Wending canon.
  The ~40 sponsors are Halfway's businesses.

## The gaps (what "NHL-level" requires that doesn't exist)

1. **No real schedule.** Slates pair random available teams nightly; no
   season-long 82-game matrix, no home/away balance, no fixed opponent counts,
   no calendar (season runs on wall-clock days, not a league calendar).
2. **No persistent players.** Rosters are 9 seed-derived names re-rolled every
   season; no ages, positions, attributes (team strength is one scalar), no
   careers, no development.
3. **No player stats.** Nothing accumulates: no G/A/P, no goalie SV%/GAA, no
   leaders, no milestones.
4. **No contracts, cap, or roster economics. No coaches/trainers/GMs.**
5. **No trades, draft, call-ups, waivers, retirements.**
6. **No playoffs.** Season hard-rolls over at 82 GP (known bug: rollover not
   air-gated — fix it in the new design).
7. **Off-air games have no box scores** — only finals — so around-the-league
   coverage can't name a scorer or goalie.
8. **Statistical calibration unvalidated** against real NHL distributions.

## Hard constraints (violating any of these fails the design)

- **Live air is sacred.** The station broadcasts 24/7; Center Ice airs Sat
  20:00 (~20h from now). Everything lands feature-gated; cutover is gated on
  the verification suite passing; instant fallback to the current path must
  exist (keep old code paths callable).
- **Preserve the public interface** consumed by the orchestrator/site:
  `tonight_live(date)`, `record_live(date)`, `tick(date)`, `export(path)`,
  `pregame_brief(game)`, `postgame_brief(game, final)`, `context_pairs(game)`,
  and the `game` dict keys the broadcast + guards rely on (rosters shape, refs,
  subplot, arena, attendance, strengths, game_no, rivalry, season). Extend,
  don't break.
- **Aired facts are canon.** Season 1 is 4 days old (game_no 1-2 aired,
  standings cited on air, tracked-team roster names narrated: e.g. Doug
  Bouchard, Rene Tremblay for mtl). Migration must PRESERVE current standings
  and extend the aired 9-name rosters into full rosters — never replace an
  aired name. (Migration is otherwise nearly free — exploit that.)
- **Box fit:** 2 vCPU / 4GB shared with Kokoro TTS. `tick()` runs every
  main-loop pass and must stay sub-second in steady state; catch-up after
  downtime must be bounded. State is JSON on disk (atomic tmp+replace,
  .bak copy pattern already established — keep it). Mind state-file growth:
  full box scores for ~1,312 games/season need a sharding/pruning story.
- **Determinism where the current engine is deterministic:** off-air results
  stay date-seeded and self-healing (state loss must not change history that
  was already published). Live broadcast games stay fresh-entropy.
- **stdlib-only** (the repo has requests+yaml+numpy-via-kokoro; engine modules
  today import only stdlib — keep it that way).
- **LLM never in the sim loop.** All facts from code; narration reads sheets.

## Required scope (the design must cover all of it)

**League engine:** persistent players (identity, age, position, attributes,
development/aging per grounding curves) · 23-man rosters + 2 goalies with
lines/pairings · real 82-game schedule matrix + league calendar (define how the
league calendar maps to wall-clock: the current season runs games every day —
decide and justify a calendar compression) · season stats + leaders +
milestones · contracts + salary cap + roster economics · coaches & trainers
(hire/fire, measurable effect on development/performance) · injuries with
realistic type/duration + IR + call-ups from a reserve pool · trades (logic +
deadline) · draft + prospects · playoffs (real format per grounding, bracket,
Cup — propose 5 trophy names w/ rationale; owner rejected "Apology Cup") ·
air-gated rollover · box scores for every off-air game (scorers/goalies/shots)
sized for around-the-league narration.

**Broadcast layer contract:** define exactly what sheets/feeds the following
consume: pregame show, intermission report (around-the-league with named
scorers), postgame interviews (coach/player quotes must be groundable in the
box score), scores-desk segments on other shows, the website league page, and
an OT-past-window signal the scheduler/site can read.

**City world-state layer (Halfway):** a shared registry both sims + shows read
(places, businesses=sponsors, civic actors, the goose, weather via existing
Open-Meteo fetch, a date-seeded city event ticker) + the **sponsor stock-index**
(absurd but internally consistent daily market report over the ~40 sponsors).
Define file/module boundaries (e.g. `src/world.py`, `world.json`).

**Statehouse engine (design after hockey, mirroring it):** per
`station/wending-bible.md` engine anchors — `civics.json`, 60 seats w/ hidden
leans, bill lifecycle per civics grounding, committee/floor calendar,
whip-count math, approval drift, elections with precinct returns engine
("called like a hockey game"), TRACKED one-thread rule, truth guard, air-gated
publishing, sessions adjourn on Center Ice nights, shared name-bank.

## Judging criteria (designs are scored on these)

1. Fidelity-bar coverage (would a hockey-literate listener ever catch it?)
2. Live-air safety: incrementality, feature gates, migration continuity,
   fallback path, rollover air-gating fixed.
3. Implementability tonight: clean parallel component boundaries (pure
   functions against a fixed schema), each testable in isolation.
4. Box fit + state-size story + tick() cost.
5. Narratability: every sim fact reachable as a booth sheet; guards can verify
   every claim the LLM might make from it.
6. Simplicity per unit of fidelity — no speculative machinery.

## Explicitly out of scope tonight

Ops dashboard (deferred by owner) · Rust port of the deterministic core (note
it as a future option per owner preference; box lacks toolchain and the
timeline forbids it) · listener-facing call-in ingestion (separate track).
