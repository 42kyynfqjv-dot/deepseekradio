# The World Spine — Texture-First Design (Track B)

Design panel, 2026-07-10. **Lens: texture-first incremental.** Phase 1 is
read-only cross-reference shipping THIS WEEK — shows and sheets citing other
sims' *real* facts. Causal effects come strictly later, and only where
provably safe. This is the *smallest* bus that delivers the one-world feel.

This doc follows the established discipline (exec summary, JSON schema, module
signatures, consumer + guard contracts, per-edge safety verdicts, collision
rules, prompt-block contract, build order, risks). It obeys every hard
constraint in `docs/big-swings-brief.md`.

## Executive summary

Today weather, the league, the statehouse, and the city run as four parallel
universes that never speak. The one-world feel costs almost nothing if we stop
inventing new truth and instead **re-publish truth that is already canon**.

The spine is a single stdlib-only leaf module, `src/worldspine.py`, plus one
append-only day-keyed file, `world-events.json`. It is a *bus*, but in phase 1
it is populated by **projection, not push**: once per main-loop pass a single
producer reads each sim's already-public, already-air-gated artifact
(`league.json`, the weather cache, the sponsor roster, and — when it ships —
`civics-public.json`), derives typed events, and appends any new ones. No
engine emits into the bus; no engine imports another; `worldspine.py` imports
no engine. It is a leaf exactly like `scoreguard.py`.

The prime safety invariant: **the bus never reads pre-air state. It only
re-publishes facts a sim has already made public.** Air-gating is enforced
*upstream* by each producing sim (the reveal clock, `final_air_at`, the
air-gated sheets); the bus inherits air-safety for free and cannot spoil.

Consumers get three products from `worldspine.digest()`: **wire lines**
(code-authored verbatim copy the orchestrator drops in like today's Sports
Desk — numbers safe because the LLM never re-authors them), a **prompt block**
(qualitative cross-facts + a register instruction, the SCOREBOARD pattern), and
**guard facts** (structured pairs/names merged into the destination show's
*existing* guard whitelist). No new guard is invented; the bus feeds the ones
we have.

Phase 1 lights up three live surfaces — **weather ↔ league ↔ city** — because
those are the only sims currently on air. Statehouse is Gate-2-era and dark;
its producer and consumer contracts are written here but dormant until its show
ships. Phase 2 adds exactly one causal edge to start — **a Cup run nudging the
Governor's approval** — the edge the brief itself names as easy, because it
touches only a soft, mutable, clamped, self-healing scalar and no immutable
hashed state. The genuinely hard edge (weather postponing a hash-frozen game)
is analyzed and **explicitly deferred** with the reason.

## world-events.json schema

Repo-root, `season.json`'s sibling. Day-keyed, append-only within a day,
window-pruned like `slates`. Atomic tmp+replace+`.bak` (the established
pattern). Read live-then-`.bak`; a missing file is an empty bus, never an
error.

```json
{
  "schema": 1,
  "cursor": {"weather": "2026-07-10", "league": "2026-07-09",
             "city": "2026-07-10", "statehouse": ""},
  "days": {
    "2026-07-09": [
      {
        "id": "league.final:2026-07-09:mtl-nyg",
        "type": "league.final",
        "producer": "league",
        "public": true,
        "air_at": 1752100000.0,
        "subject": "mtl",
        "payload": {
          "home": "Montreal Apologies", "away": "New York Gridlock",
          "home_key": "mtl", "away_key": "nyg",
          "score": [4, 2], "ot": false, "so": false,
          "winner": "Montreal Apologies", "tracked": true},
        "wire": "Around the league: the Apologies took the Gridlock 4-2.",
        "prompt": "the Apologies beat the Gridlock last night",
        "guard": {"score_pairs": [[4, 2]]},
        "tags": ["hockey", "result", "tracked"]
      },
      {
        "id": "weather.day:2026-07-09",
        "type": "weather.day", "producer": "weather",
        "public": true, "air_at": 0, "subject": "halfway",
        "payload": {"tempF": 81, "code": 3, "snow": false, "windmph": 7,
                    "high": 84, "low": 68, "rain_pct": 20},
        "wire": null,
        "prompt": "warm and hazy, light wind, no rain to speak of",
        "guard": {}, "tags": ["weather"]
      },
      {
        "id": "civic.quorum_fail:2026-07-09",
        "type": "civic.quorum_fail", "producer": "statehouse",
        "public": true, "air_at": 0, "subject": "half-dome",
        "payload": {"cause": "snow"},
        "wire": "The Half-Dome lost quorum to the weather again.",
        "prompt": "the statehouse couldn't make quorum in the snow",
        "guard": {}, "tags": ["civic", "snow"]
      }
    ]
  }
}
```

**Field contract.**

- `id` — stable, deterministic: `type + day + subject`. Re-projection is
  idempotent; append dedupes on `id`. (Same-day revisions bump nothing; a
  corrected fact is a new id or an in-place payload replace under the same id —
  see collision rules.)
- `type` — dotted `producer.kind`. The typed vocabulary is closed and
  single-owner (see catalog). Adding a type is a design change, not an
  improvisation (mirrors the hockey schema-freeze rule).
- `producer` — the *one* sim that owns this type. No two producers ever write
  the same type.
- `public` / `air_at` — air-gate metadata. In phase-1 projection every event is
  observed *from an already-public artifact*, so `public: true` and `air_at` is
  the observation time (weather/city, always-public, use `0`). `air_at` earns
  its keep only if a later phase switches a producer to *push* pre-air events;
  consumers already filter `air_at > now`, so that path stays safe by
  construction.
- `subject` — the entity the fact is about (team key, `halfway`, a bill id).
  Lets a consumer request "events about mtl" without parsing payloads.
- `payload` — the code-owned structured facts (numbers, names). Authoritative.
- `wire` — optional code-authored verbatim line for a wire-copy slot, or null.
- `prompt` — optional qualitative phrasing for a prompt block (no hard numbers
  unless the destination guard can verify them).
- `guard` — structured facts to merge into the destination show's existing
  guard whitelist (`score_pairs` → `scoreguard.allow_pairs`; later
  `tallies`/`bill_ids` → `civicguard`).
- `tags` — free-text selectors for relevance filtering.

`cursor` records the last projected day per producer for idempotent chunked
catch-up. `days` is pruned to a trailing 30 days on save (the `slates` rule);
aired cross-facts inside the window are canon.

## Module: `src/worldspine.py` (leaf, stdlib-only)

Imports nothing from `season`, `league.*`, `statehouse.*`, `spots`,
`orchestrator`. Those modules import *it*. It reads data files (JSON), never
engine code — reading a sibling's JSON is the established cross-process pattern
(the scorebug publisher, the site), not a code dependency.

```python
SIDE = Path("world-events.json")
FLAG = Path("data/world/ENABLED")          # gate; absent => dormant

def load() -> dict                          # live-then-.bak, else empty bus
def save(bus: dict) -> None                 # atomic tmp+replace+.bak, prune 30d
def on() -> bool                            # FLAG.exists(); loud-off otherwise

# --- producer side (ONE call site: the main-loop tick) ---
def project(day: str) -> None
    """Read each sim's public artifact, derive typed events for `day`,
    append new ones (dedupe by id), advance per-producer cursor. Chunked
    catch-up (45 days/pass, the engine bound). Exception-isolated per
    producer: a bad weather read never blocks league projection. Idempotent
    and deterministic — ids are pure functions of (type, day, subject)."""

# --- consumer side (called by shows/sheets) ---
def digest(day: str, *, show: str, want: set[str] | None = None,
           now: float | None = None) -> dict
    """-> {"wire": [str, ...], "prompt": str, "guard": {...}}
    Reads events with air_at <= now, filters by relevance for `show`
    (tag/subject allowlist per show, so Center Ice sees civic color but
    not its own scores echoed back), and assembles the three products.
    Empty/degraded on any failure — a show with no digest behaves exactly
    as today."""
```

`project()` is the *only* writer. `digest()` is pure-read. Fallback is total:
if `FLAG` is absent or anything throws, `digest()` returns empty and every show
renders byte-identically to today. This is the `rm ENABLED` discipline —
texture is additive and instantly revocable.

### Producers (phase 1: the three live surfaces)

Each producer is a pure function `derive(day) -> list[event]` over one public
artifact. It reads a *projection*, never raw pre-air state.

- **`weather`** — reads a day-keyed weather cache `data/world/weather-{day}.json`
  written once per show window by a thin wrapper around `spots._real_forecast`
  (the forecast is already fetched once per window; we cache the parsed numbers
  instead of re-hitting the network — box-fit + network discipline). Missing
  cache → **no event** (the "missing feed => quorum holds" rule: never invent
  weather). Emits `weather.day` and, when `snow`, `weather.snow`.
- **`league`** — reads `league.json` (the site artifact `export()` already
  publishes with *all* air-gating applied: `broadcast.played` only after the
  horn airs, `around` rows reveal-clocked, `last_result` already aired). Emits
  `league.final` from `last_result`/`broadcast`, `league.around` from `around`,
  `league.streak`/`league.trade`/`league.injury` from the enriched rows and
  `news-lines.json`. Because it reads the air-gated public file, it *cannot*
  surface a score before its final horn.
- **`city`** — reads the sponsor roster (`spots._roster` over the bible) and the
  date+hour billboard pick. Emits `city.billboard` (this hour's sponsor) and
  `city.sponsor` texture. There is **no numeric sponsor index yet** — the bible's
  "Halfway market report" is aspirational; the numeric series is future
  Track-C-adjacent work. City is texture-only until it exists.

### Producer/consumer, dormant: statehouse

Statehouse is Gate-2-era, has no `ENABLED`, no show, no public projection. Its
bus contract is **specified now, wired the day its show ships**:

- It gains a `civics-public.json` air-gated projection — the exact analogue of
  `league.json` — written by the government show's publisher with the same
  never-spoil discipline (`civicguard` already exists for this). `worldspine`'s
  `statehouse` producer reads *that* file, never `civics.json`'s raw approval.
- Types: `civic.quorum_fail`, `civic.bill_passed`, `civic.approval_move`,
  `civic.veto_override`, `civic.election_called`.
- Until `civics-public.json` exists, the producer emits nothing and every civic
  consumer contract is inert. No dependency on the unfinished engine.

## Consumer contracts (guard-verified; no engine imports another)

Every consumer calls `worldspine.digest(day, show=...)` and receives the three
products. It never imports the producing engine. Smallest-first:

1. **The World Desk (extends the existing Sports Desk).**
   `orchestrator._news_bulletin` already appends code-authored wire copy from
   the league box shards ("Sports desk. …"). Generalize it: append
   `digest(...)["wire"]` — weather one-liner, around-the-league finals, a civic
   quorum note when relevant. **Contract:** wire lines are dropped in verbatim
   as produced segments (`speaker: "The Frequency"`, NEWS_VOICE); the LLM never
   re-authors them, so their numbers need no guard. This is the pattern that
   already ships; the bus just widens the feed from one sim to four.

2. **The booth pregame WORLD block (Center Ice).** `season.pregame_brief`
   already carries a HISTORY line and around-the-league finals into the booth,
   and `context_pairs()` already feeds `scoreguard.allow_pairs`. Add a WORLD
   block to the pregame prompt from `digest(day, show="center-ice")["prompt"]`
   — real Halfway weather ("cold night, wind off the lake"), a civic note ("the
   Dome lost quorum to the snow"). **Contract:** the block is qualitative;
   `digest(...)["guard"]["score_pairs"]` merges into the existing `allow_pairs`
   for any cross-game score the booth cites — the same seam `context_pairs`
   already uses. No new guard.

3. **Morning/daytime shows prompt texture.** `run_show` already injects
   Wesley's real forecast. Add the WORLD block so any show may reference last
   night's game, the weather, the roundabout, in *its own register*.
   **Contract:** the SCOREBOARD-style register instruction (below) forbids
   inventing numbers; qualitative only, with wire copy for anything numeric.

4. **Statehouse sheets (dormant).** `sheets.session_brief`/`gavel_recap`/
   `dome_desk` gain an optional `world` param carrying
   `digest(day, show="statehouse")` so the Dome desk can say "approval ticked up
   on the Apologies' run" as color. **Contract:** `civicguard` guards civic
   numbers; hockey cross-facts arrive as verbatim wire or guard-verified pairs;
   the sheet authors qualitatively around them. Inert until the government show
   airs.

**The invariant, stated for CI:** a script asserts (a) `worldspine.py` imports
no engine module, (b) no producing engine imports `worldspine`'s *producers*
(they may import the shared leaf for `digest`), and (c) the only writer of
`world-events.json` is `worldspine.project`. The bus is the sole cross-surface.

## Causal-edge catalog (per-edge safety verdict + phase)

Phase 1 edges are **citations** — zero state mutation, pure texture. Phase 2
edges mutate state and each carries an explicit verdict.

| ID | Edge | Kind | Verdict | Phase |
|----|------|------|---------|-------|
| E1 | weather → booth/show color | cite | **Safe** — weather already flows to Wesley; extend to any show | 1 |
| E2 | weather → statehouse quorum | *internal, exists* | **Safe** — `calendar.record_snow_day` already does this; bus only lets *other* shows cite it | 1 (cite) |
| E3 | league result → morning/city color | cite | **Safe** — already-aired fact; qualitative | 1 |
| E4 | league streak → statehouse "approval rides the streak" | cite | **Safe** — canon (Election Night bible); color only in phase 1 | 1 |
| E5 | city sponsors → booth/ads | cite | **Safe** — sponsor roster already cited | 1 |
| E6 | any result → World Desk wire | cite | **Safe** — generalizes the shipped Sports Desk | 1 |
| **C1** | **Cup run / hot streak → Governor approval** | **mutate** | **Safe, easy** — feeds only the soft, mean-reverting, clamped, self-healing `approval` scalar via the existing `_EVENT_DELTA` mechanism | **2** |
| C2 | weather → game postponed | mutate | **HARD — DEFER** (see below) | — |
| C3 | statehouse bill → sponsor index | mutate | **Deferred** — no numeric index sim exists yet; texture-only until Track C builds it | — |
| C4 | league trade/injury → cross-show desk | cite | **Safe** — already near-exists via `news-lines.json` | 1 |

### C1 in detail — the one causal edge we ship (phase 2)

`statehouse.engine._approval_drift` already accepts event deltas from
`_EVENT_DELTA` (pothole, quorum_fail, override, session_milestone). Add a
`hockey_run` delta sourced from the bus:
`_advance` reads `worldspine.digest(day, show="statehouse", want={"league"})`,
detects a tracked-team win streak ≥ N or a playoff/Cup-run tag, and appends a
small clamped delta. **Why safe:** (1) approval is soft, mean-reverting to 46,
clamped [25,71], and self-healing from seeds — a wrong day heals; (2) no
immutable or hashed state is touched (not the calendar, not member identity,
not the aired ledger); (3) determinism is preserved because the causal input is
fetched *by day* from the append-only bus, never wall-clock; (4) the resulting
approval is published only through the air-gated civic sheets, so no spoiler.
Ships behind its own sub-flag `data/world/CAUSAL-APPROVAL`, dark until a
backtest confirms the drift envelope stays inside the calibrated band.

### C2 in detail — the hard edge, deferred with reason

Weather postponing a game **cannot** ship safely in this design's scope. The
schedule sidecar is immutable and covered by `league.engine.sidecar_hash`
(VERIFIED). Rewriting `schedule-s{n}.json` to move a game drifts the hash and
silently falls the whole v2 engine to v1 (the engine's own docstring warns of
exactly this class of self-defeating mutation). Worse, a postponed *broadcast*
game collides with the live-rolled game the booth is narrating. The only safe
route is a **separate `postponements.json` overlay** that the reveal/standings
layer consults *without* mutating the hashed schedule — a make-up-date remap —
and even that must preserve the 82-GP invariant and the `AIR`-tagged row. That
is its own design. **Verdict: deferred, not attempted here.** Snow stays a
statehouse-only cause (quorum) and a texture cause everywhere else; it does not
touch the frozen hockey schedule.

## Collision rules

1. **Single-producer-per-type.** Each event type has exactly one owning sim.
   Weather owns `weather.*`, league owns `league.*`, statehouse owns `civic.*`,
   city owns `city.*`. Two producers can never write the same fact, so
   producer-vs-producer contradiction is impossible *by construction*.
2. **Read-only phase 1.** Consumers cannot mutate producing state, so no
   cross-engine write contradiction exists in phase 1.
3. **Air-gate precedence.** An event is invisible until `air_at <= now`. The
   bus only ever ingests already-public projections, so this is belt-and-braces;
   a consumer can never cite a fact before its origin sim aired it.
4. **Latest-air-eligible wins.** If a fact is corrected within a day (rare),
   `project()` replaces the payload in place under the same `id`; consumers read
   the current payload. No stacking of contradictory same-`id` events.
5. **Causal edges are soft-only (phase 2 invariant).** A causal edge may feed
   *only* a soft, mutable, clamped, self-healing scalar (approval; a future
   sentiment index) — never immutable/hashed state (schedule, member identity,
   aired ledger). Enforced by a per-edge allowlist; C2's rejection is this rule
   in action.
6. **Deterministic causal input.** A phase-2 causal input must be a function of
   already-canon bus facts keyed *by day* (never wall-clock), so replay against
   the same bus reproduces the same mutation — the self-healing seed discipline.

## Prompt-block contract for shows

The bus mirrors the authoritative-register pattern (the SCOREBOARD register).
`digest()` yields, for injection into a show's prompt:

```
AROUND WENDING TODAY (all real and already aired — reference in THIS show's
own register; do NOT restate as a bulletin, do NOT invent or change any number,
do NOT contradict): {prompt}. You MAY color the weather delivery (the numbers
are roughly right); you may NOT invent scores, tallies, or margins — any hard
number you need has already been read for you on the wire.
```

Rules:
- **Numbers travel as wire copy, not prompt text.** Anything numeric (a final,
  a tally, a margin) is delivered as a code-authored `wire` line the orchestrator
  drops in verbatim — exactly like today's Sports Desk and billboard ID. The LLM
  authors *around* it, never re-derives it.
- **Prompt text is qualitative.** "The Apologies won last night," "the Dome lost
  quorum to the snow," "warm and hazy" — no digits the destination guard can't
  verify.
- **Guard facts back the block.** Any cross-game score a booth might legitimately
  cite is merged into that show's existing whitelist
  (`scoreguard.allow_pairs`/`civicguard`) via `digest(...)["guard"]`, the seam
  `context_pairs` already uses.
- **Per-sheet self-guard CI (mirror G3).** Each new prompt block gets a test:
  render the block, synthesize booth/host lines quoting it, run the destination
  guard (`enforce_scoreboard`/`civicguard`) — **zero replacements or the test
  fails.** The bus cannot introduce a fact its show's guard would flag.

## Build order (parallelizable, incremental, gated)

Each step lands behind `data/world/ENABLED`; with the flag off, every show is
byte-identical to today.

0. **`worldspine.py` core + schema + tests.** `load`/`save`/`on`, the event
   shape, id determinism, 30-day prune, empty-bus fallback. Pure; golden tests
   from fixtures. No consumer wired yet.
1. **Projection readers (parallel, one per surface).** `weather` (+ the
   `data/world/weather-{day}.json` cache wrapper), `league` (over `league.json`),
   `city` (over the roster/billboard). Each a pure `derive(day)`; each
   independently testable; `project()` composes them, exception-isolated.
2. **World Desk** — extend `_news_bulletin` to append `digest(...)["wire"]`.
   Smallest, highest-feel, lowest-risk (verbatim copy, the shipped pattern).
3. **Booth + show WORLD block** — inject `digest(...)["prompt"]` into
   `pregame_brief` and `run_show`; merge `["guard"]` into `allow_pairs`.
4. **Self-guard CI (G3-style)** for both new blocks. Gate cutover on green.
5. **Statehouse join** — the day the government show ships: add
   `civics-public.json`, turn on the `statehouse` producer, wire the sheet
   consumer. Contract already written; no engine change beyond publishing its
   own air-gated projection.
6. **Phase 2 C1** — `hockey_run` approval delta behind `CAUSAL-APPROVAL`, with a
   backtest against the calibrated approval band before the flag flips.

## Risk register

- **Bus becomes a second source of truth that drifts.** *Mitigation:*
  projection-from-public-artifacts + single-producer-per-type + never reading
  pre-air state. The bus is a denormalized *cache* of facts each sim already
  owns; it holds no authority.
- **Air-gate leak (spoiler).** *Mitigation:* the bus reads only already-air-gated
  public projections (`league.json`, `civics-public.json`); a test asserts no
  projected event predates its origin's air stamp. Weather/city are inherently
  public.
- **LLM invents a cross-number.** *Mitigation:* numbers only via verbatim wire
  copy or destination-guard-verified `guard` facts; the G3-style self-guard CI
  fails the build if any block admits an unguarded number.
- **Determinism break in a phase-2 causal edge.** *Mitigation:* causal inputs
  keyed by day from the append-only ledger, seeded; C1's delta replays
  identically. Rule 6.
- **Coupling regression.** *Mitigation:* CI asserts `worldspine` imports no
  engine, no engine imports a producer, and `project` is the sole writer.
- **Box-fit.** *Mitigation:* projection is a handful of JSON reads per pass,
  throttled to the 30s publisher cadence; stdlib-only; atomic writes; catch-up
  chunked 45 days. The weather cache removes per-pass network calls.
- **Statehouse dependency on unfinished work.** *Mitigation:* the civic producer
  and consumer are dormant behind the absence of `civics-public.json`; nothing
  in phase 1 needs the statehouse engine to be on air.
- **Over-reach into causal too early.** *Mitigation:* phase 1 is provably
  read-only (consumers cannot mutate); phase 2 ships exactly one soft-scalar
  edge behind its own flag; the hard edge (C2) is deferred in writing, not
  quietly attempted.
```
