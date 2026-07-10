# Hockey League Engine — FINAL SYNTHESIZED DESIGN

Synthesis of the three-panel design round (2026-07-10). **Backbone:
`hockey-minimal.md`** — unanimous winner across all three adversarial judges
(live-air-safety, fidelity, implementability) — **adopted verbatim except where
this document states a delta.** Grafts come from `hockey-broadcast.md` and
`hockey-fidelity.md` where every judge said to steal them. This document is the
schema freeze: component builders implement EXACTLY the shapes referenced here;
if a schema doesn't fit, report the friction — never improvise a field.

## Adopted verbatim from hockey-minimal.md

- §2 state schema (season.json spine + per-season sidecars under `data/league/`,
  derive-don't-store, box shards pruned to 21 days, `by` birth-offset ages,
  3-scalar attribute model `ov/sh/pl` + slot).
- §3 module breakdown (`src/league/` package: calendar, schedule, players,
  boxscore, stats, economy, playoffs, briefs; ~25-line livegame diff).
- §4 interface preservation (18-skater rosters L1-first; additive keys only).
- §5 calendar: **1 wall-day = 1 league-day identity mapping** (unanimous across
  judges; the 2:1 alternative measurably violates the grounding cadence), with
  the **Crossover Series** (mtl–nyg meet 8×, 4H/4A) reconciling the NHL matrix
  with the aired `_RIVALRY_EVERY = 7` cadence.
- §6 tick algorithm (fast path <50 ms never opening sidecars; day boundary
  60–100 ms; per-game seeds `slate2:{season}:{d}:{hk}-{ak}`; catch-up chunked
  45 days/pass; export throttled to the 30s publisher cadence).
- §7 migration (re-derive aired 9 names from their original seed as the
  protected core; remainder-schedule; retro box-fill; stats agree with every
  aired number).
- §8 gate + fallback + **rollover air-gated phase machine (ships in BOTH modes
  as the bug fix)**.
- §10 broadcast contract (pregame LINES/INJURY/LEADERS/MILESTONE blocks,
  postgame QUOTE GROUNDING, scores desk via news-lines.json, website additive
  keys, ot-signal.json).
- §11 calibration knobs + `calibrate_league.py` envelopes; §12 economics model;
  §13 playoff format + trophy shortlist; §14 risk register.

## Grafts (judge-directed)

**G1 — In-progress around-the-league (reveal clock).** Replaces minimal §10's
"yesterday's finals only" desk — the one fidelity gap all judges flagged. Each
off-air game in tonight's slate gets a seeded virtual puck drop
`start_off = Random(f"drop:{season}:{d}:{hk}-{ak}").randint(0, 5400)` (0–90 min
stagger). One pure function

```python
def reveal(box: dict, start_off: int, cursor: int) -> dict
    # cursor = seconds since OUR broadcast's pregame aired (shared clock).
    # -> {"status": "final"|"live"|"upcoming", "score": [h,a],
    #     "period": 1|2|3|"OT", "clock": "mm:ss", "scorers_so_far": [...]}
```

is the ONLY renderer of off-air progress, used by the intermission sheet, the
scores desk, AND `export()`'s `around` rows — one clock, no cross-feed
contradictions. Every revealed partial pair registers in `allow_pairs`.
Intermission 1 airs mostly in-progress snapshots ("Dial Tones lead 3–1, Larsson
has two, midway through the second"); postgame airs finals. Export's cursor is
wall-anchored to the same pregame air timestamp, so the site and the booth
agree. Tests: reveal monotonicity (score never decreases as cursor grows;
status never regresses), final==box final at cursor≥end, and cross-surface
equality (sheet vs export at equal cursors).

**G2 — Overnight shadow mode + shadow_diff.** Before cutover, every main-loop
pass runs the v2 tick against `data/league-shadow/` (a copy), wrapped in
`try/except` (exception-isolated, budget-capped, writes NOTHING shared, never
season.json, never the site). `scripts/shadow_diff.py` recomputes v2 standings
vs live v1 season.json and appends to a log; cutover requires a clean multi-hour
shadow run with zero standings diffs and zero exceptions.

**G3 — Per-sheet self-guard CI.** Every `briefs.py` sheet test renders the
sheet, builds its facts, and runs `enforce_scoreboard` + `enforce_names` over
synthetic booth lines quoting it: **zero replacements or the test fails.**

**G4 — The migrator refuses to arm.** `scripts/verify_league.py` writes
`data/league/VERIFIED` (a hash over the sidecars) only when every check passes;
`season._v2_on()` requires ENABLED + VERIFIED + hash match. A human cannot
skip the gate at 2am.

**G5 — KS live-vs-slate parity test.** 2,000 games via `sim_box` vs 2,000 via
the chunked live path at identical strengths; two-sample KS on goal totals and
margins must not reject (α=0.01) — tracked teams stay statistically identical
to their peers.

**G6 — Canon-diff artifact.** Migration emits `data/league/canon-diff.txt`
listing every divergence from aired canon (roster names, standings, finals).
Cutover requires the file to be EMPTY, and verify_league re-checks it.

## Judge-mandated fixes to the backbone

- **Coach-firing calibration band tightens to 4–8 per season** (grounding), not
  2–9. λ stays ≈5.5.
- **Crossover Series arithmetic gets its own property test**: every team
  exactly 82 GP / 41H / 41A, tracked pair exactly 8 meetings, the five donor
  buckets each short exactly one game, the other 30 teams on the exact NHL
  matrix.
- **`develop()` is intentionally dormant** until the economy gate: a test
  asserts the regular-season tick never mutates player attributes.
- **Integration is not a big-bang tier**: the main loop (me) integrates each
  component the hour it lands, against the frozen schemas, so schema friction
  surfaces immediately instead of at 5am.

## Gates & scope

- **Gate 1 — `data/league/ENABLED` (+VERIFIED), target Saturday < 20:00:**
  schedule, players (minting/dress/strength/injuries), boxscore, stats, briefs
  (incl. reveal clock), migration, shadow-verified cutover. Economy/playoff
  modules ship dark: their state files don't exist, their code paths are never
  entered.
- **Gate 2 — `data/league/ECON-ENABLED`, target Sunday+ after the full
  50-season calibration passes:** economy.run_day (trades, coach firings,
  cap), coaches populated into `game["coaches"]` (which auto-activates the
  already-shipped presser beat), trainers, develop() wiring at rollover,
  playoffs machinery (bracket is months away on the 1:1 calendar). Tracked-team
  trades additionally require `allow_tracked_trades` (owner flag): aired names
  are canon and stay put by default.

## Component contract (tonight's parallel build)

| ID | Deliverable (new files only) | Builder | Notes |
|----|------------------------------|---------|-------|
| A | `src/league/calendar.py` + `src/league/schedule.py` + `tests/test_league_schedule.py` | agent | minimal §3/§5/§9-A + Crossover property test |
| B | `src/league/players.py` + `tests/test_league_players.py` | agent | minimal §3/§9-B. Strength solve: **bisection on a global tier-scale multiplier** per team (algorithm mandated) to hit v1 scalar ±0.01 |
| C | `src/league/boxscore.py` + `tests/test_league_boxscore.py` | agent | minimal §3/§9-C + G5 parity test; consumes the livegame diff (built by main loop) via `roster["weights"]`/`assist2` |
| D | `src/league/stats.py` + `tests/test_league_stats.py` | agent | minimal §3/§9-D |
| E | `src/league/briefs.py` + `tests/test_league_briefs.py` | agent | minimal §10 + G1 reveal + G3 self-guard CI |
| G | `src/league/economy.py`, `src/league/playoffs.py` + tests | agent ×2 | minimal §12/§13 + 4–8 firing band; ships dark |
| F | livegame diff, season.py facade/gate, tick v2 loop, migration, verify, shadow, export additions | **main loop (me)** | incremental integration |

Component rules: stdlib-only, pure functions, no imports from season.py or
orchestrator.py (leaf modules; `boxscore.py` may import `livegame`), every
public function exactly as signed in minimal §3, tests runnable as plain
`python3 tests/<file>.py` following the repo's fixture style (PASS/FAIL
counter, exit code).

## Trophy

**DECIDED (owner, 2026-07-09): the championship trophy is THE BOREAL
LANTERN.** Canon everywhere: the playoffs are "the run for the Lantern," the
champion "lifts the Lantern." (Shortlist for the record: Halfway Cup, Long
Winter Cup, Thibodeau Trophy, Frequency Cup, Boreal Lantern.)
