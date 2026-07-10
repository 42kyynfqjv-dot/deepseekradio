# World Spine — FINAL SYNTHESIZED DESIGN

Backbone: **world-spine-full-causal.md** (safety-judge winner) — one new leaf
`src/world.py`, single-writer DERIVED PROJECTION (reads each engine's
committed public artifacts, never pre-air state; no engine imports another),
day-keyed append-only `world-events.json` (45-day bound), the timing rule
(external inputs same-day; cross-engine outputs consumed the day AFTER they
settle and air), the sponsor index as the universal code-owned sink, and the
permanent verdict: **the broadcast game is FORBIDDEN from weather
postponement forever**; off-air postponement stays DEFERRED behind its own
future flag.

## Scope of THIS build: texture-first's phase 1 + one dark causal edge

Ship the citation layer only: weather/league/city events projected onto the
bus; `digest()` returns the three products (code-authored WIRE lines like the
Sports Desk; a SCOREBOARD-register PROMPT block; GUARD facts merged into the
destination show's existing allowlists). Consumers wired this build: a
world/around-town line available to news bulletins, the morning-show prompt
block, and a dormant statehouse-sheet contract. The ONE causal edge (Cup run
→ Governor approval via the existing clamped `_EVENT_DELTA` path) is built
+ tested but ships DARK behind `data/world/CAUSAL-ENABLED`.

## Judge-mandated fixes baked in

1. **Strictly append-only**: corrections are new events with a `supersedes`
   id — never in-place mutation (aired facts are canon forever).
2. **Halfway gets real coordinates**: `spots._real_forecast` currently
   fetches New York (40.71, -74.01). Canon decision (owner may override):
   Halfway sits at **44.98 N, -73.45 W** — northern border country,
   snow-plausible, Boreal-consistent. One constant `HALFWAY_LATLON` in
   `src/world.py`, consumed by the weather producer AND passed into
   `_real_forecast` so Wesley, the weather spots, and the spine all report
   the SAME city's sky.
3. **The statehouse `weather_fn` is dead code in production today** — first
   live wiring of real-weather→quorum is a behavior change that gets its own
   flag (`data/world/WEATHER-QUORUM`) and a shadow note; NOT flipped in this
   build.

## Build components (fleet — pure, own tests, repo style)

| ID | Deliverable |
|----|-------------|
| A | `src/world.py` + `data/world/world-events.json` schema + tests — producers (weather via HALFWAY_LATLON, league from league.json/box shards, city from sponsor roster + seeded index), append-only w/ supersedes, 45-day prune |
| B | `digest()` three-product consumer API + tests — wire lines, prompt block, guard-facts merge contracts (per full-causal §consumer-contracts) |
| C | The dark causal edge (Cup→approval) + `CAUSAL-ENABLED` gate + tests proving gate-off inertness |
| D | Consumer wiring + tests — news-bulletin world line (sports-desk pattern), morning-show prompt block, `_real_forecast` coords param + spots/Wesley switch to Halfway |

Gate: `data/world/ENABLED` for the projection+texture layer. Verification
workflow runs TOMORROW before any flip.
