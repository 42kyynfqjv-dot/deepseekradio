# The World Spine — Full-Causal Design (Track B)

Design panel entry, 2026-07-10. **Lens: full-causal ambition.** This document
designs the complete causal graph that turns weather, the league, the
statehouse, and the city/sponsors from four parallel simulators into ONE world,
and gives an honest per-edge safety verdict — including the hard case (weather
-postponed games vs the frozen schedule + VERIFIED hash). It is written to the
same discipline as `hockey-final.md` / `statehouse-final.md`: concrete schema,
module signatures, guard + prompt-block contracts, collision rules, phased build
order, risk register. Where an edge cannot be made safe, it is **deferred
explicitly**, never improvised onto live air.

---

## 1. Executive summary

Today four sims run side by side and never touch: `season.py` (league),
`src/statehouse/engine.py` (statehouse), `spots.py` (weather/ads), and an
unbuilt sponsor index. Each already commits its truth to disk — `season.json`,
`civics.json`, `data/league/*`, `data/statehouse/*`, `news-lines.json`. Track B
adds **one new leaf module, `src/world.py`, and one new shared surface,
`world-events.json`**: a day-keyed, append-only bus of **typed, guard-verifiable
events** projected from committed engine state.

The single most important architectural decision, forced by the codebase's own
proven patterns, is that **the bus is a DERIVED PROJECTION with exactly one
writer** (`world.py`), not a free-for-all many-writer log. `world.py` reads each
engine's on-disk state (the same files their site-publishers already read) and
*derives* the day's events, exactly as `season.export()` derives `league.json`.
This buys three things at once: (a) no multi-process write race on a shared
file; (b) the hard-constraint "no engine may import another" holds trivially —
the only coupling is to on-disk JSON schemas, never to Python; (c) idempotent,
self-healing re-derivation (derive-don't-store).

Causality flows in two directions with one timing rule that makes it safe:
**external-input events (weather) are consumed same-day; cross-engine-output
events (a Cup clinch, a bill passing) are consumed the day AFTER they settle and
air.** The next-day rule breaks every intra-tick cycle and gives air-gating for
free — approval reacts to a Cup run the morning after the clinch reaches
listeners, which is also how it works in life.

Phasing is the design. **Phase 1** is read-only texture: every show's prompt
gets a guard-verified WORLD block quoting the other sims' real facts (low risk,
high feel). **Phase 2** is safe causal effects on **code-owned derived state
only** — the sponsor index reacting to weather/bills/Cup runs, and governor
approval reacting to a Lantern run (the brief's named "easy" case). **Phase 3**
is the hard edge: weather-postponed games. Verdict up front: **off-air
postponement is SOLVABLE via a non-hashed overlay sidecar + deterministic
makeup, but is DEFERRED behind its own flag and calibration proof; the AIR
(broadcast) game is NEVER weather-postponed — FORBIDDEN forever**, because it
would simultaneously break the frozen schedule hash, `schedule.yaml`'s day-gated
block, the site takeover, and imaging promos that ran days ahead. Around the
broadcast game, weather stays read-only texture.

---

## 2. `world-events.json` schema

Repo-root, `season.json`'s sibling (like `civics.json`). One writer:
`world.py`. Atomic tmp+replace with `.bak`, the established `_save` discipline.

```json
{
  "schema": 1,
  "updated": "2026-07-10",
  "days": {
    "2026-07-10": [
      {"id": "weather:2026-07-10", "type": "weather", "producer": "world",
       "day": "2026-07-10", "air_at": null,
       "data": {"snowfall": 2.1, "code": 73, "cond": "snow",
                "tmax": 28, "tmin": 19, "wind": 14}},

      {"id": "quorum_fail:house:2026-07-10", "type": "quorum_fail",
       "producer": "statehouse", "day": "2026-07-10", "air_at": 1720651200,
       "data": {"chamber": "house", "reason": "snow"}},

      {"id": "bill_settled:H-041:2026-07-10", "type": "bill_settled",
       "producer": "statehouse", "day": "2026-07-10", "air_at": 1720651200,
       "data": {"bill_id": "H-041", "title": "Pothole Naming Moratorium",
                "stage": "SIGNED", "tally": [31, 20], "tags": ["potholes"]}},

      {"id": "final:mtl-hfx:2026-07-10", "type": "game_final",
       "producer": "league", "day": "2026-07-10", "air_at": 1720658400,
       "data": {"home": "mtl", "away": "hfx", "score": [4, 2],
                "ot": false, "so": false, "air": false}},

      {"id": "cup_run:mtl:s3:round2", "type": "cup_run",
       "producer": "league", "day": "2026-07-10", "air_at": 1720658400,
       "data": {"team": "mtl", "season": 3, "stage": "round2_win",
                "series": "3-1"}},

      {"id": "index:2026-07-10", "type": "index_move", "producer": "world",
       "day": "2026-07-10", "air_at": null,
       "data": {"level": 1042.3, "chg_pct": -1.4,
                "movers": [{"sym": "LADR", "name": "Ted's Ladder Rental",
                            "chg_pct": -6.2, "why": "snow"}]}},

      {"id": "city:goose:2026-07-10", "type": "city_event", "producer": "world",
       "day": "2026-07-10", "air_at": null,
       "data": {"kind": "goose_sighting", "text": "goose holds the pharmacy lot"}}
    ]
  }
}
```

**Invariants.**
- `days` is bounded to the trailing **45** days (same window as league
  catch-up); anything older is canon already living in the producing engine's
  own state and is never re-derived.
- Every event carries a stable `id` = `{type}:{key}:{day}`. Re-derivation is
  idempotent: `world.py` computing a day twice yields byte-identical events.
- `air_at` is `null` for events that are not spoilers (weather, the index, city
  color), or the producing engine's real air timestamp for events that must not
  leak before narration (a game final, a bill outcome, a Cup clinch). Consumers
  and the site respect it exactly like `final_air_at` / `narrated_air` today.
- `type` has **exactly one producer** (see §5, collision rule 1). `producer`
  is recorded for provenance and guard attribution, never for write arbitration
  (there is only one writer).

---

## 3. `world.py` — the single owner

Leaf module. Imports stdlib + `requests` (already a dependency via `spots.py`).
Reads on-disk engine state; imports **no** engine module. The orchestrator/main
loop calls `world.tick()` once per pass, AFTER `season.tick()` and
`statehouse.tick()` have committed their state, so it always projects settled
facts.

```python
SIDE = Path(".")                       # world-events.json at repo root
WORLD = Path("world-events.json")
RETAIN_DAYS = 45

def tick(date: str) -> dict            # derive + persist today's events; returns bundle
def load_bus() -> dict                 # trust rule: live, then .bak, then empty
def events_for(date: str, types=None, aired_only=False) -> list
def weather_fn(date: str) -> dict | None   # the statehouse/league snow hook adapter
def world_block(date: str, show: str, register: str) -> tuple[str, dict]
                                        # -> (prompt text, allow-list payload)

# producers (private, pure projections of committed state):
def _weather_event(date) -> dict | None            # §4
def _league_events(date) -> list                   # game_final / cup_run from season.json + sidecars
def _statehouse_events(date) -> list               # quorum_fail / bill_settled from civics.json + docket
def _index_event(date, prior_events) -> dict        # §7 sponsor index (consumer+producer)
def _city_events(date) -> list                     # goose ticker etc. (seeded, evergreen)
```

**Gate discipline (mirrors the engines).** `world.py` runs read-only and
low-risk by default (weather cache + city color are harmless). The *causal*
consumers that change on-air numbers (index publish, approval-reacts-to-Cup) sit
behind flag files — `data/world/ENABLED` for the index engine, and the approval
edge behind the statehouse's own gate (§6). No VERIFIED hash is needed for the
bus itself because it stores no immutable identity — it is a pure projection;
its correctness is proven by golden re-derivation tests, not a runtime hash.
Fallback for any phase: delete the flag; `world.py` degrades to read-only
texture, and with the flag absent every consumer falls back to its current
pure-canon behavior (statehouse: no snow, weather_fn=None; shows: no WORLD
block).

---

## 4. The weather producer (Phase 0 — the unification)

Today weather is fetched **twice and inconsistently**: `spots._real_forecast()`
hits Open-Meteo for **NYC coords (40.71, -74.01)**, and the statehouse
`weather_fn` defaults to `None` (no snow, ever). Track B's foundation is a
**single Halfway weather fetch, cached day-keyed**, that becomes the one truth
every sim reads.

```python
_HALFWAY = {"lat": 44.26, "lon": -72.58}   # small-state canon coords (VT-model)

def _weather_event(date):
    cached = _cache_get(date)                       # data/world/wx-{date}.json
    if cached: return cached
    raw = _fetch_open_meteo(_HALFWAY)               # snowfall, code, temps, wind
    ev  = _project(raw, date) if raw else None
    if ev: _cache_put(date, ev)                     # atomic; survives API outage
    return ev
```

- **Missing-feed rule** (unchanged from `calendar.is_snowfall`): no feed ⇒ no
  weather event ⇒ **quorum holds, games play, index flat**. Weather is never
  invented. This is already the statehouse contract; Track B extends it verbatim
  to every consumer.
- `spots.py` is rewired to read the cached event instead of its own NYC fetch —
  a pure correctness fix (spot copy is non-authoritative deadpan-absurd, so this
  is the lowest-risk edge in the whole design), and now the weather on air, the
  snow that fails quorum, and the blizzard that tanks Ted's Ladder Rental are
  **the same storm**.
- `world.weather_fn(date)` is the adapter passed into `statehouse.tick(...,
  weather_fn=world.weather_fn)` — it returns exactly the `{snowfall, cond, ...}`
  dict `calendar.is_snowfall` already expects. **This is the moment snow becomes
  live for the statehouse** (today it defaults off). Because it changes engine
  behavior, it ships behind the statehouse gate and is shadow-run first (§8).

---

## 5. Consumer contracts (guard-verified; no engine imports another)

A consumer reads `world.events_for(date, ...)` from the bus file and treats each
event's `data` as an **authoritative code-owned fact** — the same status a
`game_final` already has. Two consumption surfaces:

**(a) Sheets / engine inputs.** Where a consuming engine needs a cross-sim fact
as *input* to its own sim, it takes it through a function parameter, never an
import — exactly the existing `weather_fn` seam:
- `statehouse.sim_day(..., weather_fn)` already consumes the weather event.
- `statehouse.tick` gains an optional `world_fn(date) -> list[events]` (same
  shape as `weather_fn`) so it can read `cup_run` events for the approval edge
  (§6). Default `None` ⇒ current behavior.
- The sponsor index (`world._index_event`) consumes `weather`, `bill_settled`,
  and `cup_run` events as its daily drivers.

**(b) Show prompts.** `world.world_block(date, show, register)` renders the
guard-verified WORLD register block for a given show and returns, alongside the
prompt text, an **allow-list payload** that the show's guard registers — so any
number that appears in the block is code-owned and cannot be contradicted or
hallucinated around. This mirrors `season.context_pairs()` feeding
`scoreguard.build_facts(allow_pairs=...)`, and `civicguard`'s equivalent. See
§9.

The strict rule, from the hard constraints: **a consumer may render a bus event
as texture, or apply it as a delta to its own CODE-OWNED DERIVED state (approval,
index) — but never mutate immutable/hashed/aired state in response.** That
single line is what makes the whole graph safe, and it is what §8's per-edge
verdicts test against.

---

## 6. The causal-edge catalog (safety verdicts + phase)

Notation: **P#** = phase; verdict ∈ {SAFE, EASY, DEFERRED, FORBIDDEN}.

### Weather → …
| Edge | Effect | Verdict | Phase |
|------|--------|---------|-------|
| weather → statehouse quorum | snow ⇒ `floor_open=False`, append `quorum_fail` to the non-hashed `civ["quorum_fails"]` ledger | **SAFE** (already built; ledger is runtime-mutable, excluded from the VERIFIED core) | P0/P1 |
| weather → weather spot (spots.py) | one Halfway storm, twisted into ad copy | **SAFE** (copy non-authoritative) | P0 |
| weather → sponsor index | blizzard depresses ladder/tarp/roundabout symbols; heatwave lifts SoupCo's rival | **EASY** (index is code-owned derived state) | P2 |
| weather → **AIR game** | postpone the broadcast | **FORBIDDEN** (§8.1) — texture only | P1 |
| weather → **off-air game** | postpone + makeup | **DEFERRED** (§8.1) — solvable, unshipped | P3 |

### League → …
| Edge | Effect | Verdict | Phase |
|------|--------|---------|-------|
| league → all shows (texture) | "Center Ice: the Regrets won 4-2" quoted on a government/city show | **SAFE** (already surfaced via `last_result`/`news-lines.json`; bus formalizes it) | P1 |
| **Cup run → governor approval** | a Lantern run bumps approval; an early exit dents it | **EASY** — the brief's named easy case; approval is a mean-reverting clamped scalar with an event-delta table (`_EVENT_DELTA`). Add `cup_run` deltas. No immutable state. Air-gated by the next-day rule | P2 |
| Cup run / trade → sponsor index | civic mood lifts the index; a marquee trade spikes a themed symbol | **EASY** | P2 |
| trade / firing → city texture | `news-lines.json` already carries these; bus re-exposes as `roster_move` | **SAFE** | P1 |

### Statehouse → …
| Edge | Effect | Verdict | Phase |
|------|--------|---------|-------|
| statehouse → all shows (texture) | "quorum failed again; H-041 signed" quoted on Center Ice / city shows | **SAFE** | P1 |
| bill passed → sponsor index | a pothole-funding bill lifts paving-adjacent symbols; a merge-courtesy bill moves the Zipper-themed ones | **EASY** (bill has code-owned `tags`; index maps tag→symbol deltas) | P2 |
| statehouse → league (games) | a bill affecting the arena/schedule | **FORBIDDEN as an effect** — the schedule is immutable/hashed/aired. Texture only ("the arena-lighting bill died in Merging") | P1 |

### City / sponsor index → …
| Edge | Effect | Verdict | Phase |
|------|--------|---------|-------|
| index → all shows | the daily Halfway market report | **SAFE** (new code-owned engine; §7) | P2 |
| goose / city ticker → all shows | seeded evergreen color, disjoint from sponsor/name banks | **SAFE** | P1 |

The index is deliberately the **universal sink**: because it is pure code-owned
derived state with no immutable constraint and low narration stakes, it can
safely react to *every* upstream event, making it the natural place to
concentrate causal ambition without touching anything dangerous.

---

## 7. The sponsor index (`world._index_event`) — consumer AND producer

The Halfway market report (bible §Halfway: "the sponsor stock-index reads as the
Halfway market report") is a new code-owned engine living inside `world.py`. It
is both the bus's biggest **consumer** (reacts to weather/bills/Cup) and a
**producer** (emits `index_move`).

Model (mirrors `_approval_drift` exactly — the pattern is proven):
- Each of the ~40 sponsors (parsed from `station/bible.md`, the single source of
  truth already used by `spots._roster`) gets a symbol and a seeded hidden base.
- Daily: `level += mean_reversion(to 1000) + seeded_gauss(σ) + Σ event_deltas`,
  clamped, series pruned to 30 days. Per-symbol deltas from a **tag→symbol
  map**: `snow → {LADR:-, TARP:-, ROUNDABOUT:-}`, `pothole bill signed →
  {PAVE:+}`, `cup_run → broad small +`, etc.
- Seeds are `index:{date}` / `index:{sym}:{date}` — self-healing, replay-stable,
  never wall-clock, exactly like every other engine.
- Published to the site gated (the index number the site shows never leads the
  show that narrates it); `air_at` optional since it's low-stakes, but the reveal
  seam exists.

This is the cleanest way to honor "full-causal ambition" while obeying every
hard constraint: one engine absorbs the whole graph's downstream pressure and it
is, by construction, incapable of corrupting immutable or aired state.

---

## 8. The hard edge — weather-postponed games (honest analysis)

### 8.1 Why the AIR game is FORBIDDEN

Postponing the broadcast game for weather would, in one move, break **four**
independent frozen systems:
1. **The VERIFIED hash.** `league.engine.sidecar_hash` covers `schedule-s{n}
   .json` bytes. Rewriting the schedule to move a game drifts the hash and
   **silently falls the entire v2 engine back to v1** on the next tick — the
   self-defeating failure the hash comment already warns about for trades.
2. **`schedule.yaml`'s day-gated block** + `schedule.js` TAKEOVER for the
   broadcast night are pinned to the date days ahead (first Center Ice
   2026-07-08 20:00).
3. **The site takeover + imaging promos** auto-ran days before the show (Track
   D machinery).
4. **Aired-facts-canon.** A pregame that already aired asserted "tonight, the
   Regrets at the Apologies" — postponing retroactively contradicts aired canon.

Verdict: **FORBIDDEN forever.** Weather around the broadcast game is **read-only
texture** — the booth says "the Regrets bussed in through a whiteout, the
Half-Dome's tarped, quorum failed downtown" and the game plays (indoor arena;
postponement was always a stretch). This is a Phase-1 edge and it is the
*correct* resolution, not a compromise.

### 8.2 Why off-air postponement is SOLVABLE but DEFERRED

Off-air games have none of problems 2–4 (no show, no promo, no aired pregame).
Only problem 1 remains, and it has a known solution shape, proven by the
codebase itself: **out2/callups/`team` are runtime-mutable state deliberately
EXCLUDED from the hashed core.** So:

- Postponements live in a **new non-hashed sidecar** `postponements-s{n}.json`
  (append-only, day-keyed), *never* in `schedule-s{n}.json`. The hash never
  drifts.
- The tick applies it as a **read-time overlay**: "skip pair X on day D; play it
  on makeup day D′." The immutable schedule is never rewritten — the snow ledger
  pattern (`record_snow_day` appends to a separate ledger, never edits the
  calendar) applied to hockey.
- Makeup day D′ is chosen **deterministically** (`Random(f"makeup:{season}:
  {D}:{hk}-{ak}")` over the pair's next mutually-empty off-air slot), preserving
  the **82-GP invariant as eventually-consistent**: every postponed game gets
  exactly one makeup, so GP still reaches 82 by season end.

**Why deferred, not shipped:** the 82-GP invariant under postponement needs its
own property test and a 50-season calibration run (does every makeup actually
find a slot before the season ends on the 1:1 calendar? edge cases near
sine-die?), exactly the bar Gate 2 set for the economy. The feel-payoff is low
(indoor arenas, rare). So it ships **Phase 3, behind `data/league/
WEATHER-POSTPONE`, off-air only, shadow + canon-diff gated**, or not at all. The
honest recommendation: **build the overlay design, defer the flag** until a
season is asking for it.

---

## 9. Prompt-block contract for shows

`world.world_block(date, show, register)` returns `(text, allow)`:

```
WORLD (authoritative — code owns every fact below; never contradict, never add
numbers of your own):
- Weather: heavy snow, high 28°F. The Half-Dome is tarped.
- Around the Dome: quorum failed today (snow). H-041 (Pothole Naming
  Moratorium) was SIGNED, 31–20.
- Center Ice, last night: the Montreal Apologies beat the Halifax Fog
  Advisories 4–2.
- Halfway market: the index closed down 1.4%; Ted's Ladder Rental off 6.2% on
  the storm.
```

- **Register-aware.** A Center Ice show gets league facts foregrounded and the
  Dome/market as color; a government show gets the inverse; a general show gets
  a balanced digest. Each institution's facts are attributed to that
  institution, so a show narrating two sims never blurs whose truth is whose
  (collision rule 4).
- **`air_at`-gated.** `world_block` filters out any event whose `air_at` is in
  the future — a bill outcome or a game final never leaks into a prompt before
  it has aired on its own show.
- **`allow` payload** feeds each show's existing guard: numeric pairs → the
  scoreguard `allow_pairs` used on any hockey-adjacent show; tallies/margins/
  bill-ids/names → `civicguard`'s allow tables on government/city shows. So a
  score or tally quoted from the WORLD block is whitelisted truth, and a number
  the LLM invents around it is still caught and replaced.
- **Per-show self-guard CI** (mirror hockey G3 / statehouse's per-sheet CI):
  render `world_block`, build the guard facts, run `enforce_scoreboard` /
  `civicguard.enforce` over synthetic booth lines quoting it — **zero
  replacements or the test fails.** The block can never phrase its own truth in a
  way its own guard would flag.

---

## 10. Collision rules

1. **Single producer per type.** Each `type` is owned by exactly one producer
   (`weather`/`index_move`/`city_event`←world; `quorum_fail`/`bill_settled`
   ←statehouse; `game_final`/`cup_run`/`roster_move`←league). No two engines ever
   emit the same type, so the bus can never carry two contradicting values for
   one fact. Enforced trivially by there being one writer.
2. **Consumers never mutate immutable/hashed/aired state** in response to a bus
   event; they render texture or apply deltas to code-owned derived state
   (approval, index) only.
3. **Timing.** External-input events (weather) are consumed **same-day** (weather
   is projected first in the tick, before any engine reads it). Cross-engine
   -output events (Cup, bill) are consumed **the day after they settle and air** —
   this breaks every intra-tick cycle and provides air-gating for free.
4. **Local truth wins for its own sheet.** If two institutions' facts seem to
   disagree (snow "fails quorum" while the indoor game "plays"), there is no
   contradiction — each is legitimately true for its institution. The bus
   *informs*, it never *overrides* an engine's owned facts. A show narrating
   both attributes each to its source.
5. **Idempotency + retention.** Re-derivation for a day is deterministic and
   byte-identical; the bus is bounded to 45 trailing days; older facts are canon
   in their producing engine and never re-derived.
6. **Air-gate precedence.** Where an event's `air_at` and a consumer's own reveal
   clock could disagree, the LATER of the two wins (never reveal early).

---

## 11. Build order (parallelizable, incremental, gated)

- **B0 — spine.** `world.py` skeleton + `world-events.json` schema + weather
  producer (Halfway cache) + `load_bus`/`events_for`/`weather_fn`. Tests: golden
  weather projection, idempotent re-derive, missing-feed fallback (no event),
  bounded retention. *No on-air change.*
- **B1 — unify weather.** Rewire `spots.py` to the cache (correctness). Pass
  `world.weather_fn` into `statehouse.tick` **behind the statehouse gate**;
  shadow-run so snow-quorum is proven before it airs. Add `_league_events` /
  `_statehouse_events` projections.
- **B2 — Phase 1 texture.** `world_block` + allow-list + per-show self-guard CI.
  Wire the WORLD block into the general/city/government show prompts (additive;
  absent block ⇒ unchanged prompt). **Phase 1 ships.**
- **B3 — Phase 2 index.** Sponsor-index engine + `index_move` + tag→symbol map +
  gated site publish, behind `data/world/ENABLED`. Calibrate σ/reversion like
  approval.
- **B4 — Phase 2 approval edge.** `world_fn` into `statehouse.tick`; `cup_run`
  event-deltas in `_approval_drift`'s event table; next-day/post-air consumption.
  Shadow-run.
- **B5 — Phase 3 (deferred).** `postponements-s{n}.json` overlay + deterministic
  makeup + 82-GP property test + 50-season calibration. **Off-air only, behind
  `WEATHER-POSTPONE`, shadow + canon-diff gated. AIR game stays texture.**

Each B-step lands feature-gated with instant fallback (delete the flag / drop
the block). Nothing is a big-bang; the main loop integrates each against the
frozen bus schema the hour it lands.

---

## 12. Risk register

- **Weather API outage** → missing-feed rule: no event ⇒ quorum holds, games
  play, index flat, spots improvise. Already the statehouse contract; extended
  verbatim. Cache survives transient outages.
- **Multi-writer race on the bus** → eliminated by the single-writer projector.
- **Snow-quorum goes live and changes statehouse output** → gated + shadow-run +
  the append-only ledger is already excluded from the VERIFIED hash, so it can
  never drift the gate shut.
- **Air-gate leak via the bus** → `air_at` fields + next-day consumption for
  cross-engine events + `world_block` future-filter + collision rule 6.
- **Bus growth** → 45-day bound, matching league catch-up.
- **Postpone overlay violates 82-GP** → deferred to Phase 3 with its own property
  test + calibration; off-air only; AIR forbidden.
- **Guard drift** (a WORLD number the guard doesn't whitelist gets replaced away)
  → the allow-list payload is derived from the SAME event the block renders, and
  per-show self-guard CI fails the build if the block trips its own guard.
- **Coordinate drift** (Halfway ≠ NYC) → one canon coord constant in `world.py`;
  `spots.py`'s NYC fetch is retired, not duplicated.

---

## 13. What this is NOT

No engine imports another (only on-disk JSON couples them). No immutable, hashed,
or aired state is ever mutated by a causal edge. No number reaches air that code
doesn't own and a guard can't verify. The broadcast game is never postponed. The
world becomes causal without a single big-bang, one gated phase at a time — and
where an edge cannot be made safe, it is deferred with its reasons on the record.
