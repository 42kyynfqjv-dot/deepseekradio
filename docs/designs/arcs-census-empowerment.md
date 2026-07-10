# Narrative Arcs + the Town Census — LISTENER-EXPERIENCE Design

Lens: design from what a person who tunes in every day actually *feels* — a
serialized story that pays off on a promised night, a caller they recognize
coming back, a Dream Court verdict that closes for real weeks later — then work
backwards to the smallest honest state that makes those feelings inevitable
instead of accidental. Every schema field below is here because a listener can
hear its absence.

## 1. Executive summary

- **Three feelings, three mechanisms.** (a) *Serialized payoff* → arcs become
  code-owned **state machines with a beat schedule and a payoff date**, so "the
  ribbon-cutting is Saturday" said Monday is a promise the code keeps, not a
  thread the model forgets. (b) *A caller I recognize* → the **census**: every
  desk-minted caller who actually airs becomes a persistent civilian (name →
  deterministic gender/voice/neighborhood, running problem, appearance history)
  with **scheduled follow-ups**. (c) *Real closure* → **Dream Court is
  serialized therapy**: each case captures the true feeling + the actual tool +
  the verdict, and a follow-up weeks later references the *specific* tool Vivian
  gave — "how's that four-count breath holding?"
- **The existing `src/arcs.py` is upgraded, not replaced.** Today it is an
  LLM story-editor that free-associates one development per day with no
  schedule and no guaranteed payoff — from the daily-listener seat, arcs drift
  and dissolve. The new design keeps an LLM **arc author** (it invents the
  premise and *plans the whole arc once*), and moves the **spine** — scheduling
  beats onto specific shows/days, advancing stages, firing the payoff,
  retiring, depositing into lore — into deterministic code. Code owns *when and
  whether it pays off*; the model owns *what's funny*.
- **Derive, don't store; assert, don't police.** A civilian's voice is a pure
  function of their name (`performers._spare_voice`, md5-stable) — never
  persisted. An arc's asserted facts are protected the way `continuity` protects
  sign-offs: fed to every relevant prompt as an **authoritative ARC CANON
  block** (SCOREBOARD register) and made **immutable once aired**, with a thin
  `arcguard` whose real job is whitelisting canon names so nameguard can't scrub
  them. We explicitly reject a full contradiction-scrubber (§7).
- **Storage:** two sidecars — `data/arcs/arcs.json`, `data/arcs/civilians.json`
  — atomic tmp+replace+`.bak`, stdlib-only, both bounded < 200 KB. Inline
  `lore_state["arcs"]` migrates in on first load. Everything is gated on
  `data/arcs/ENABLED`; absent → today's behavior verbatim.
- **Boundary with lore is explicit (§8):** `running_jokes`/`callbacks` are
  *stateless, evergreen, un-scheduled* references picked by `pick_callback`;
  arcs are *stateful, scheduled, escalating, dated* and drip-fed through the
  assignment desk on a **separate channel**. An arc **graduates** into
  `recent_callbacks` as a one-line epitaph the day it resolves.
- Cost: daily tick < 20 ms; per-show desk lookup < 1 ms; one cheap Dream-Court
  clerk call per Night Shift (off the hot path, failure = generic follow-up).
- Ship order: census identity → arc state machine → prompt blocks → arcguard →
  Dream-Court clerk → integration+migration. A–E are parallelizable pure
  modules; only F touches live wiring.

## 2. State schema

Both files live under `data/arcs/`, atomic tmp+replace with a `.bak` sidecar
(the `lore.save`/`season._save` discipline). Missing file → module returns the
empty default and every caller degrades to today's behavior.

### data/arcs/arcs.json

```json
{
  "schema": 1,
  "seq": 42,
  "active": [
    {
      "id": "arc-041",
      "title": "The Roundabout Ribbon-Cutting That Won't",
      "premise": "Toivo Ostberg schedules a ribbon-cutting for the Mile Zero roundabout; it is, of course, not done.",
      "register": "civic",
      "cast": ["Toivo Ostberg"],
      "civilians": ["civ-0311"],
      "canon": ["The ribbon-cutting is set for Saturday.", "The ribbon is teal."],
      "stage": 1,
      "started": "2026-07-10",
      "payoff_day": "2026-07-14",
      "status": "active",
      "beats": [
        {"day": "2026-07-10", "show": "morning_scramble", "stage": 0,
         "line": "Toivo's announced a ribbon-cutting for the roundabout — Saturday, and he means it this time.",
         "fact": "The ribbon-cutting is set for Saturday.",
         "payoff": false, "aired": true},
        {"day": "2026-07-11", "show": "night_shift", "stage": 1,
         "line": "The teal ribbon arrived today. The roundabout did not.",
         "fact": "The ribbon is teal.",
         "payoff": false, "aired": false},
        {"day": "2026-07-14", "show": "morning_scramble", "stage": 3,
         "line": "They cut the ribbon anyway. The roundabout is still two weeks out. Everyone applauded.",
         "fact": "The ribbon was cut; the roundabout remains unfinished.",
         "payoff": true, "aired": false}
      ]
    }
  ],
  "resolved": [
    {"id": "arc-039", "title": "The Goose Bylaw",
     "epitaph": "The goose was granted the pharmacy lot in perpetuity; the sign is laminated.",
     "resolved_day": "2026-07-08"}
  ]
}
```

- `register` ∈ `{civic, town, nature, listener}` — **never** `office` (the
  station has done breakroom appliances to death) and **never** conspiracy/woo
  (that is the Watcher's quarantined register, §9). Drives which shows may host
  a beat.
- `beats` is the whole plan, authored **once** at arc birth. `stage` is the
  current escalation index; `payoff:true` marks the terminal beat. `aired` flips
  when the beat's show has run that day.
- `canon` is **append-only**: every aired beat's `fact` lands here and is never
  rewritten. This is the arc's factual truth surface (§7).
- `cast` are canon Halfway figures (Toivo, Bert Demers, the goose…) drawn from
  `station/wending-bible.md`; `civilians` are census ids woven in as callers.
- `resolved` keeps the last ~20 arcs as one-line epitaphs (the lore graduation,
  §8), pruned thereafter.

### data/arcs/civilians.json — the census

```json
{
  "schema": 1,
  "civilians": {
    "civ-0311": {
      "name": "Maureen",
      "gender": "f",
      "neighborhood": "Old Millwater",
      "problem": "a sock ceasefire with her husband",
      "first_day": "2026-06-19", "first_show": "night_shift",
      "last_day": "2026-06-26",
      "appearances": [
        {"day": "2026-06-19", "show": "night_shift", "kind": "dream_court",
         "note": "socks migrating to his side of the bed",
         "feeling": "she felt unseen after the move",
         "tool": "name it out loud, then a four-count breath",
         "verdict": "the socks are a truce flag, not a betrayal"},
        {"day": "2026-06-26", "show": "night_shift", "kind": "followup",
         "note": "ceasefire holding, mostly"}
      ],
      "followups": [
        {"day": "2026-07-10", "show": "night_shift", "kind": "dream_court_followup",
         "prompt": "three weeks on: how's the sock ceasefire — and that four-count breath?",
         "done": false}
      ],
      "retired": false
    }
  },
  "by_name": {"maureen": "civ-0311"}
}
```

- **`gender` is stored** (the desk knows it *by construction* at mint — §4 of
  `assignments.py`), but **voice is never stored**: it is
  `performers._spare_voice(name)`, a pure md5-stable function, so Maureen sounds
  like Maureen forever with zero drift and zero bytes. Derive-don't-store.
- **`neighborhood` is derived**, not chosen: `NEIGHBORHOODS[_stable_hash(name)
  % len]` against a small canon bank (§3). Deterministic, so it never changes
  between appearances.
- `problem` is a one-line running problem — optional; enriched opportunistically
  (§5), null-safe. A bare "Maureen from Old Millwater, back again" is already a
  recognition win.
- `appearances` carries the Dream-Court closure fields (`feeling`/`tool`/
  `verdict`) so a follow-up can quote the *actual* tool. `followups` are the
  scheduled returns.
- `by_name` is the lowercase dedup index — the census never mints two Maureens.
- Budget: ~500 active civilians × ~350 B ≈ 175 KB ceiling; cold civilians
  (`last_day` > 90 days, never in an active arc) are pruned to a name-only stub
  so recognition survives but the file stays small.

## 3. Canon neighborhood bank (new, small, locked)

`station/wending-bible.md` fixes Halfway's *civic* geography (Mile Zero, the
pharmacy lot, the Half-Dome) but no residential neighborhoods. The census needs
a fixed, small set so "Old Millwater" means the same place every time. Proposed
locked bank of 12, all consistent with existing canon (measured from Mile Zero,
Exit 4 never built, the goose's lot, the merge/zipper theme):

```
Old Millwater · The Exit-4 Flats · Roundabout North · Pharmacy Heights ·
Lower Sieve · The Merge · Zipper Row · Mile-Zero Commons · The Tarpline ·
Window-4 Ward · Cold Storage · The Provisional Blocks
```

Added to `wending-bible.md` under "Locked canon — Halfway" so shows may
reference them freely. Twelve is enough that neighbors cluster believably and
few that a daily listener starts to *know* them.

## 4. Module & file breakdown

Two new/rewritten stdlib-only leaf modules. Leaf discipline: writer/orchestrator
import them, never the reverse. Both operate on plain dicts + an injected clock
date string (testability; no hidden `datetime.now`).

### src/arcs.py (rewrite — replaces the LLM-only story editor)

```python
MAX_ACTIVE = 3
def load() -> dict                       # arcs.json, or empty default; migrates inline lore["arcs"]
def save(state: dict) -> None            # atomic tmp+replace+.bak
def daily_tick(models, lore_state, census, date, weekday, schedule) -> None
    # 1. mark yesterday's due beats aired (set by the orchestrator post-show);
    # 2. advance stage of each active arc to today's beat;
    # 3. fire+resolve any arc whose payoff beat aired -> move to resolved,
    #    deposit epitaph into lore recent_callbacks (the graduation, §8);
    # 4. if len(active) < MAX_ACTIVE: author ONE new arc (LLM plan, §6),
    #    schedule its beats onto real shows/days (schedule_beats).
def schedule_beats(arc, date, weekday, schedule, rng) -> list   # pure: plan -> dated beats
def beats_for(state, show_id, date) -> list      # today's scheduled beats for THIS show (pure, ~1ms)
def mark_aired(state, show_id, date) -> list      # flip aired, append facts to canon; returns fired facts
def canon_block(state, show_id, date) -> str      # authoritative ARC CANON prompt block (§10)
def digest(state) -> str                          # unchanged signature: woven-texture lines for lore
```

`beats_for` is the **scheduled-beat channel** (intentional, one show owns
today's beat); `digest` remains the **texture channel** (every show may weave a
line, via `lore.digest`). Both coexist — §8.

### src/census.py (new)

```python
def load() -> dict                        # civilians.json or empty default
def save(state: dict) -> None
def _cid(state) -> str                    # next civ-NNNN
def neighborhood(name: str) -> str        # pure: NEIGHBORHOODS[hash % len]
def register_air(state, name, gender, show_id, date, *, kind="caller",
                 note=None, problem=None) -> str
    # find-or-create by lowercase name; append an appearance; return civ id.
    # gender defaults to performers._gender_of(name); neighborhood derived.
def schedule_followup(state, cid, show_id, date, kind, prompt) -> None
def followups_for(state, show_id, date) -> list   # due, un-done, capped 1/show/day (pure)
def mark_followup_done(state, cid, day, show_id) -> None
def census_block(followups) -> str        # authoritative RETURNING CALLER block (§10)
def daily_tick(state, date, schedule, rng) -> None
    # promote each civilian with no pending follow-up + last_day 14-28d ago to
    # ONE scheduled follow-up on a register-compatible talk show; prune cold.
def record_dreamcourt(state, cid, feeling, tool, verdict) -> None  # closure capture (§5)
def voice_of(name) -> str                 # thin re-export of performers._spare_voice (derive)
```

### Changed files (small, additive)

- **`src/assignments.py`** — `writer_block(...)` gains two optional params
  (`arc_beat`, `returning`); the desk assembles `daypart["_assign"]["arc_beat"]`
  and `["returning"]`. ~15-line diff.
- **`src/writer.py`** — `assign_block` also renders the arc-beat + returning-
  caller blocks; `arc_line`'s REGISTER GUARD is untouched (arc beats are woven
  as callbacks, never set `daypart["arc"]`, §9). ~8-line diff.
- **`src/orchestrator.py`** — the existing `arcs.daily_tick` call is extended to
  also run `census.daily_tick`; the assignment-desk block adds `arc_beat`/
  `returning`; a post-show `census.register_air` + `arcs.mark_aired` pass; a
  Night-Shift Dream-Court clerk hook. ~40-line diff, all inside existing
  try/except garnish guards.
- **`src/lore.py`** — `digest` already calls `arcs.digest`; now reads from
  `arcs.load()` when `lore_state["arcs"]` is empty (migration transparency).
  `overused` already exempts arc words — unchanged.

## 5. Dream Court as serialized therapy (the closure loop)

The daily-listener payoff that no other station has: a bizarre dream, a real
tool, and — *weeks later* — a check-in that remembers the tool. Three code
touchpoints:

1. **Capture.** Vivian's Dream Court runs on `night_shift`. After the Night
   Shift airs, a single cheap **case-clerk** pass (`dreamcourt.clerk(lines,
   models)`) reads the aired Dream-Court lines and extracts strict JSON:
   `{dreamer, feeling, tool, verdict}` (the three closure moves in
   `personas/vivian.md`). It runs **once, off the hot path**, wrapped in the
   garnish try/except: failure → we still register the dreamer, just without the
   tool string. `census.record_dreamcourt` writes those fields onto the
   dreamer's latest appearance.
2. **Schedule.** `census.daily_tick` promotes a captured dreamer to a
   `dream_court_followup` 14–28 days out, pinned to `night_shift`, with a prompt
   that *names the tool*: "three weeks on: how's that four-count breath — and
   the sock ceasefire?"
3. **Pay off.** On that night the desk hands Vivian a **RETURNING CALLER**
   block (§10). The desk mints the returning caller's name = the stored `name`,
   so `_spare_voice` reproduces the exact voice. Vivian doesn't diagnose fresh;
   she *checks in* — and the closure lands because the tool was real. This is
   the register the owner asked for: "bizarre premises, real closure, real
   tools," now **serialized**.

Fresh (non-follow-up) Dream Court cases need no scheduling — the clerk captures,
`register_air` records, the follow-up scheduler does the rest next cycle.

## 6. The arc author (LLM plans once; code owns the spine)

When `daily_tick` finds a free arc slot it calls the arc author (the writer-tier
model, once). The system prompt is the current `_EDITOR` variety mandate
(town/nature/civic/listener, **never** office, **never** conspiracy/woo)
extended to demand a **full plan**, not a single development:

```
Return STRICT JSON — a COMPLETE arc plan, 4–6 beats, that escalates and PAYS OFF:
{"title","premise","register":"civic|town|nature|listener",
 "cast":["canon Halfway names only, or []"],
 "beats":[{"stage":0,"line":"<one on-air line>","fact":"<the one durable fact this beat asserts>"},
          ... last beat is the payoff],
 "lifespan_days": 4}
```

Code then owns everything the listener actually experiences:

- **`schedule_beats`** maps stages onto real dates and shows: beat 0 → today;
  remaining beats spread across `lifespan_days`, each assigned to a
  **register-compatible show that runs that day** (civic/town → any daytime
  talk show; nature → Morning Scramble/Handover; listener → Night Shift), the
  payoff beat pinned to a high-traffic morning/drive slot for maximum audience.
  Center Ice and the Static Hour are excluded (§9). Deterministic given the arc
  seed, so a restart re-derives the identical schedule.
- **Stage advance, payoff, retirement, graduation** are pure code (§4). The LLM
  cannot forget to pay off, cannot let an arc run forever, cannot resurrect a
  resolved one — those are state-machine transitions, not model choices.

If the author call fails, `daily_tick` simply doesn't open a new arc that day —
never a blocker (garnish discipline).

## 7. Guard contract — how an arc's facts resist contradiction

The brief's explicit question. Answer, in priority order:

1. **Assertion over policing (the `continuity` pattern).** Every relevant prompt
   receives an **ARC CANON block** in the authoritative SCOREBOARD register:
   the active arc's `canon` facts + tonight's scheduled beat `line`/`fact`. The
   writer and performers author *within* asserted truth, the same way they
   author within the SCOREBOARD and SWITCHBOARD lines. This is where 95% of the
   protection comes from and it costs one prompt block.
2. **Immutability.** Once a beat airs, `mark_aired` appends its `fact` to
   `canon` and it is **never rewritten**. Payoff facts are terminal. Aired arc
   facts are canon forever — the hard-constraint rule, applied per-arc.
3. **`arcguard` = a name whitelist, not a contradiction scrubber.** The *real*
   failure mode isn't the LLM asserting "the ribbon is now red" (rare, low-
   stakes for petty town texture) — it's **nameguard scrubbing "Toivo Ostberg"
   or "Maureen" as a phantom real person**. So `arcguard.enforce(lines, arc_state,
   census_state)` feeds every active-arc `cast` name + every referenced
   civilian `name` into nameguard's `extra_ok` whitelist, exactly as
   `run_center_ice` feeds `pool_ok`. That is its whole job. `assignments.py`'s
   caller banks are *already* disjoint from cast/sponsors/officials, so a census
   civilian can never collide with a canon figure.
4. **Explicitly rejected: a semantic contradiction-scrubber.** Detecting
   "the ribbon is teal" vs "the ribbon was always red" needs antonym/entailment
   reasoning that regex can't do and an LLM judge would do expensively and
   unreliably, for a class of error that is (a) rare under assertion and (b)
   G/PG-harmless when it slips. Cost/benefit says assert + immutably record, and
   spend the guard budget on the name whitelist that has a real failure mode.
   This is the honest minimal answer to the brief's "facts table per arc vs
   extend nameguard" question: **a tiny facts list (`canon`) fed as authority,
   plus a nameguard whitelist extension — not a new policing guard.**

## 8. Boundary with existing lore (explicit)

| | `running_jokes` / `recent_callbacks` | **Arcs** | **Census civilians** |
|---|---|---|---|
| State | stateless strings | state machine (stage, schedule, payoff_day) | persistent record (id, history) |
| Scheduling | none — evergreen | dated beats on named shows | dated follow-ups on named shows |
| Payoff | never | guaranteed terminal beat | scheduled check-in |
| Prompt channel | `pick_callback` → ONE per show | `beats_for` → the owning show; `digest` texture | `followups_for` → returning-caller block |
| Lifecycle | rolling trim | born → escalate → resolve → **graduate** | born on air → follow-ups → prune cold |

The one explicit crossing: when an arc resolves, its epitaph is deposited into
`lore.recent_callbacks` (via `lore.remember(callbacks=[epitaph])`) so it becomes
evergreen, `pick_callback`-eligible lore *after* it stops being a live arc. Arcs
graduate into jokes; jokes never become arcs. `pick_callback` and `beats_for`
never contend — separate channels, one authoritative block each.

## 9. Cross-show register discipline

- **Register match is enforced at scheduling time**, not at air time: a
  `civic`/`town`/`nature`/`listener` arc beat is only ever assigned to a show
  whose register accepts it. Because beats are woven as *callbacks* (a line or
  two) and **never** set `daypart["arc"]`, the writer's existing anti-conspiracy
  REGISTER GUARD stays armed on non-arc shows — an arc beat that reads mundane
  passes it trivially (the arc author is forbidden conspiracy/woo).
- **The Static Hour (Watcher) is excluded** from both channels: `lore_quarantine`
  already keeps his theories out of shared lore; `schedule_beats` never assigns
  a beat there and `beats_for` skips quarantined shows. His conspiracies resurface
  as daytime callbacks exactly as today.
- **Center Ice is excluded** — it is sports-only, code-owned by `run_center_ice`;
  arc/census channels are not wired into it. (A future league-arc would ride the
  world-event bus of Track B, not this system.)
- **Dream-Court follow-ups pin to `night_shift`** (Vivian owns the register);
  general census follow-ups route to any daytime talk show with a compatible
  register, capped one per show per day so no show becomes a reunion special.

## 10. Prompt-block contracts (authoritative, SCOREBOARD register)

All blocks are code-built strings, appended to `daypart["_assign"]` and rendered
by `writer.assign_block` / passed to performers — same path as the existing
desk blocks.

**ARC CANON block** — `arcs.canon_block(state, show_id, date)`:
```
STATION ARC (authoritative — the desk owns this storyline, weave it in a line
or two, do NOT contradict):
- TONIGHT'S BEAT (this show carries it): "The teal ribbon arrived today. The
  roundabout did not." Land this on air, in character, naturally.
- ALREADY TRUE (canon, never contradict): The ribbon-cutting is set for
  Saturday. The ribbon is teal.
```

**RETURNING CALLER block** — `census.census_block(followups)`:
```
RETURNING CALLER (the desk brings them back — this is a CHECK-IN, not a new
problem): Maureen, from Old Millwater, called three weeks ago about a sock
ceasefire with her husband; you gave her a four-count breath. Bring her back
warmly, ask how the ceasefire — and the breathing — are holding, and give her
real, gentle closure. Her name is Maureen; do not rename her.
```

The desk mints the returning caller's on-air name = the stored `name`, so
`performers._spare_voice` reproduces the exact voice (deterministic by
construction, the §4 caller-mint guarantee). Failure of any block → the block is
simply omitted; the show proceeds as today.

## 11. Build order (parallelizable pure components, each tested)

Mirrors the hockey table: A–E are pure modules with zero interdependency beyond
these schemas; F is the only integration step.

| # | Component | Deliverable | Test strategy |
|---|---|---|---|
| A | `census` identity | `neighborhood`, `register_air`, `_cid`, dedup | Seeded golden: same name → same id/gender/neighborhood/voice across calls; "Maureen" twice → one record, two appearances; `_gender_of` fallthrough for ambiguous names → full-pool voice, no crash. |
| B | `arcs` state machine | `schedule_beats`, `daily_tick`, `mark_aired`, `beats_for`, retire+graduate | Property tests over a fake clock: every arc reaches exactly one `payoff:true` beat within `lifespan_days`; no beat on excluded shows; resolved arcs deposit exactly one epitaph; `active` never exceeds `MAX_ACTIVE`; canon is append-only (aired fact never removed). |
| C | prompt blocks | `canon_block`, `census_block`, `writer.assign_block` extension | Golden-render tests; **guard round-trip**: run `enforce_scoreboard`/`enforce_names` on lines quoting each block → zero scrubs once whitelisted. |
| D | `arcguard` | name-whitelist feed into nameguard `extra_ok` | Canon cast ("Toivo Ostberg") + civilian ("Maureen") in a line survive `enforce_names`; a genuine phantom real name still scrubbed. |
| E | Dream-Court clerk | `dreamcourt.clerk`, `record_dreamcourt` | Parse tests on synthetic Night-Shift transcripts → correct `{feeling,tool,verdict}`; malformed/empty → returns None, dreamer still registered. |
| F | Integration | orchestrator wiring, migration, gate | Offline dry-run over a copied state dir: 30 synthetic air-days → arcs born/pay off/graduate, civilians accrue + get follow-ups, files < 200 KB, daily tick < 20 ms, gate-off path byte-identical to today. |

A `tests/test_arcs.py` + `tests/test_census.py` fake the clock (inject `date`)
so a whole month simulates in milliseconds — no `datetime.now` anywhere in the
pure modules.

## 12. Migration + bootstrap

1. **Inline arcs → arcs.json.** `arcs.load()` detects a non-empty
   `lore_state["arcs"]` and no `arcs.json`; it wraps each legacy arc as an
   `active` entry with `beats: []` and `status:"active"`, so old arcs finish out
   as texture-only (no retro schedule) and the *next* authored arc is the first
   fully-scheduled one. One-time, idempotent, inside `load()`.
2. **civilians.json seeds empty.** Optionally back-fill from
   `station_state.json`'s `callers_today` history as name-only stubs so a few
   recent callers are already "recognized" on day one — nice-to-have, not
   required; default is a clean start.
3. **Neighborhood bank** appended to `station/wending-bible.md` (§3) — the only
   canon file touched, additive.
4. **Gate:** `data/arcs/ENABLED` flag + sidecars parse. Absent or corrupt →
   loud print, `arcs.digest` falls back to the legacy inline behavior and the
   census/scheduled-beat/follow-up channels are simply not wired. **Instant
   fallback = delete one flag file**; live air never depended on any of it.
5. **Cutover:** land modules + tests with gate off (live paths untouched); run
   the offline 30-day dry-run; `touch data/arcs/ENABLED`; watch one manual
   `daily_tick` + one Night Shift to eyeball a captured Dream-Court case. No
   big-bang: the first listener-visible change is one woven arc line.

## 13. Risk register

| # | Risk | Mitigation |
|---|---|---|
| 1 | Model ignores a scheduled arc beat (no payoff airs) | Assertion, not guarantee — accept; the beat is re-asserted on its owning show, and the *fact* still enters canon on `mark_aired` so the story stays coherent even if a night is thin. Arcs are garnish; a missed line never crashes a show. |
| 2 | Fact contradiction on air | §7: authoritative canon block + immutability; residual G/PG-harmless slips accepted rather than paying for a semantic scrubber. |
| 3 | Census bloat | Cap ~500 active; prune civilians cold >90 d and not in an active arc to name-only stubs; `by_name` keeps dedup O(1). |
| 4 | Follow-up pile-up (reunion special) | `followups_for` caps 1/show/day; `daily_tick` promotes at most one follow-up per civilian and spaces them 14–28 d. |
| 5 | Nameguard scrubs a canon civilian/cast name | `arcguard` whitelist (D) feeds every active name into `extra_ok`; caller banks are pre-disjoint from canon figures. |
| 6 | Voice drift on a returning caller | Voice is derived, never stored — `_spare_voice(name)` is md5-stable; the desk mints the returning name = stored name, so the pin is reproduced exactly. |
| 7 | Dream-Court clerk failure loses the tool | Off-hot-path, try/except; failure → dreamer still registered, follow-up falls back to a generic "how've you been" prompt (recognition preserved, specificity lost). |
| 8 | Arc author drifts into office/conspiracy register | Reuse the existing `_EDITOR` variety+register mandate verbatim; `register` is validated on ingest (unknown → arc dropped); scheduling only ever routes to register-compatible, non-quarantined shows. |
| 9 | Restart mid-arc | Everything derives from arcs.json (schedule authored once, persisted) + seeds; `mark_aired` is idempotent on `(show,date)`; a restart re-reads state and continues — no replay, no double-payoff. |
```
