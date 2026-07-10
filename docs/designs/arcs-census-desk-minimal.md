# Arcs + Town Census — MINIMAL-DESK-EXTENSION Design

Lens: the smallest extension of the machinery that already ships — the assignment
desk (`src/assignments.py`), the lore store (`src/lore.py`), and the embryonic
`src/arcs.py` — that delivers code-owned multi-week arcs and a persistent town
census. No new subsystem is added where an existing surface can carry the weight.
Every new byte of state is paid for by an **audible serialization**: a scheduled
beat that airs, or a returning caller the listener recognizes.

## 1. Executive summary

- **Two things already exist and are 80% of the work.** (1) `arcs.py` already
  runs a once-per-air-day "story editor" pass and already surfaces through
  `lore.digest()` into every outline. (2) The desk already mints callers with
  deterministic, gender-pinned, collision-free names (`assignments.next_caller`)
  whose Kokoro voice is a pure function of the name (`performers._spare_voice`).
  The design **promotes** both, it does not replace them.
- **Arcs become a code-owned state machine, minted once and frozen.** The LLM is
  demoted from "rewrites every arc every day" to "drafts a new arc's skeleton
  once at birth." Code owns the schedule: escalation beats each carry a **date**
  and a **compatible show**, a **payoff date** that is guaranteed to air, and a
  `stage` cursor advanced deterministically. This satisfies "code owns facts; the
  LLM authors" — the beats are frozen strings the performers dramatize, never
  re-derived, so they cannot drift.
- **The census is the caller lifecycle, extended past midnight.** Today a caller's
  name lives in `station_state.json["callers_today"]`, capped at 40 and wiped
  daily. The census writes the same event to a persistent `civilians.json` record
  and schedules a **follow-up** date. Because a returning civilian keeps her
  **name**, her voice is identical by construction — the census stores it as
  insurance but derives it for free.
- **The desk is the only integration point.** One function
  (`orchestrator._mint_caller_line`) already decides who the next caller is; it
  now asks the census whether a follow-up is due first. One prompt block
  (`assignments.writer_block`) already carries the authoritative callback; arcs
  ride the same authoritative-block pattern. No new hot-loop code, no new guard on
  the critical path.
- **The guard question, answered honestly (§6):** we do **not** build a
  scoreguard-scale per-arc fact table. Arc facts are one-line prose, not tallies;
  a narration guard cannot reliably diff freeform prose for contradiction, and
  does not need to. Contradiction is prevented by **construction** — frozen beats
  surfaced one at a time through the desk's authoritative block, names and
  neighborhoods drawn from registries — backed by a thin `censusguard` that
  corrects only the small **checkable proper-noun class** (a returning civilian's
  neighborhood, real-world-name scrub), reusing `nameguard`'s edit-distance
  machinery.
- **New steady-state disk: < 250 KB.** `arcs.json` holds ≤ 2 active + a few
  resolving arcs (~4 KB). `civilians.json` keeps every *recurring* civilian and a
  pruned tail of one-offs (~200 records × ~400 B ≈ 80 KB). New per-day tick cost:
  stdlib-only, microseconds; the only LLM spend is ~1–3 arc-skeleton mints/week
  plus one optional cheap outcome line per follow-up show — all inside the
  existing once-per-air-day arc block, never the beat loop.
- **Ship order:** census banks+scheduler → arc state machine → censusguard →
  desk/prompt wiring → integration+bootstrap. A–D are independent pure modules.

## 2. Boundary with existing lore (explicit, per the brief)

Three stores, three jobs, one prompt surface:

| Store | Owns | Lifetime | Scheduled? | Guaranteed to pay off? |
|-------|------|----------|-----------|------------------------|
| `lore_state.json` (`lore.py`) | running jokes, feuds, one-off callbacks, `recent_premises`/`recent_grounding` anti-repetition | rolling, bounded | no | no — a joke *might* be called back via the desk's one-callback slot |
| `arcs.json` (`arcs.py`) | multi-week storylines: premise, cast, dated escalation beats, payoff date | born → payoff → retired | **yes** (code owns dates) | **yes** (code force-airs the payoff) |
| `civilians.json` (`census.py`) | persistent people: name→voice/hood, running problem, appearance history, scheduled follow-ups | accretes; recurring kept, one-offs pruned | **yes** (follow-up dates) | follow-up guaranteed if scheduled |

**The bridge is one-directional and explicit:** when an arc **resolves**, its
`resolution` string is appended to `lore_state["recent_callbacks"]` — the arc
"enters lore" (the brief's exact language) and can thereafter be referenced ad hoc
like any callback, while the arc itself is retired from `arcs.json`. Nothing flows
the other way: a running joke never becomes an arc automatically. The prompt
surface is unchanged — `lore.digest()` still emits the arc digest block
(§5), it just sources it from `arcs.load()` instead of `lore_state["arcs"]`.

## 3. State schemas

Both files are repo-root/cwd-relative siblings of `season.json`/`lore_state.json`,
written with the established atomic tmp+replace+`.bak` discipline
(`statehouse.engine.save_side`). Readers trust live file, then `.bak`, then a
fresh default — never silently reset a live spine.

### 3.1 arcs.json (~4 KB)

```json
{
  "schema": 1,
  "next_id": 8,
  "recent_settings": ["the pharmacy lot", "the roundabout", "Lower Wending"],
  "arcs": [
    {
      "id": "arc-0007",
      "title": "The Sock Ceasefire",
      "premise": "Maureen and her downstairs neighbor wage a passive-aggressive war over a shared laundry line",
      "setting": "Lower Wending",
      "register": "mundane",
      "cast": ["civ-0031"],
      "born": "2026-07-02",
      "payoff_on": "2026-07-23",
      "stage": 1,
      "beats": [
        {"on": "2026-07-02", "show": null,         "latest": "Maureen mentions the laundry-line thing for the first time", "aired": true},
        {"on": "2026-07-09", "show": "night_shift", "latest": "the neighbor has started counting the clothespins",          "aired": false},
        {"on": "2026-07-16", "show": null,          "latest": "a laminated note appears on the line",                        "aired": false},
        {"on": "2026-07-23", "show": null,          "latest": "PAYOFF: they split the line down the middle with tape — an accidental truce", "aired": false}
      ],
      "status": "active",
      "resolution": null
    }
  ]
}
```

- **Code owns:** `stage`, every `beats[i].on` and `payoff_on`, `status`, the
  variety guard `recent_settings`. `stage` advances when `date >= beats[stage].on`;
  `payoff_on == beats[-1].on` and is force-aired if the window slips (§4.2).
- **LLM authors once, then frozen:** `title`, `premise`, `setting`, each beat's
  one-line `latest`. Minted by `mint_arc` at birth (§4.1) and never rewritten — so
  a beat is a fact the moment it exists. `register ∈ {mundane, dream, civic,
  seasonal}` routes the arc to compatible shows (§4.3).
- `cast` links civilian ids (may be empty). `beats[i].show` is an optional pin;
  `null` means "any register-compatible show." `aired` flips when the beat is
  actually surfaced on air, so a restart never re-airs or skips a beat.

### 3.2 civilians.json (~80 KB ceiling)

```json
{
  "schema": 1,
  "next_id": 32,
  "by_name": {"maureen": "civ-0031"},
  "followups": [["2026-07-23", "civ-0031"]],
  "civ": {
    "civ-0031": {
      "name": "Maureen",
      "g": "f",
      "voice": "af_kore",
      "hood": "Lower Wending",
      "problem": "the sock ceasefire — a laundry-line war with the downstairs neighbor",
      "origin_show": "night_shift",
      "register": "dream",
      "first_aired": "2026-06-11",
      "last_aired": "2026-07-02",
      "shows": ["night_shift", "night_shift"],
      "appearances": 2,
      "last_outcome": "agreed to try one week of alternating laundry days",
      "arc": "arc-0007",
      "followup_on": "2026-07-23",
      "followup_hook": "how's the sock ceasefire holding?",
      "status": "recurring",
      "dream": {
        "premise": "a courtroom made entirely of unmatched socks",
        "feeling_named": "she feels unseen by a neighbor she can't confront",
        "tool_given": "write the grievance down for morning-you, then let it rest",
        "verdict": "case dismissed; the socks were never the defendant",
        "followup_on": "2026-07-23"
      }
    }
  }
}
```

- **Derive-don't-store honored, with cheap insurance:** `voice` is exactly
  `performers._spare_voice(name)` and `g` is `_gender_of(name)` — both re-derivable
  from `name` — but stored so the website can render a caller and so a future
  `_spare_voice` change can't silently re-voice a canon person (the guard reads the
  stored value).
- **Code owns:** `name`, `g`, `voice`, `hood`, `problem`, all dates, `appearances`,
  `status`, `followup_hook` (a template over `problem`). These are minted from code
  banks (§4.4), never parsed from dialogue.
- **Optional LLM enrichment (guarded, §4.5):** `last_outcome` and the whole `dream`
  sub-record. Both default to the code-owned `problem` phrase if the enrichment
  call never runs — the census is fully functional without an LLM ever touching it.
- **Indexes:** `by_name` lets a re-minted name rejoin its record instead of forking
  a duplicate; `followups` is a sorted due-queue so `due_followup` is O(1) at the
  head.
- **Pruning (every recurring byte is paid for by a scheduled return):** a record
  with `status == "recurring"` is kept while it has a future `followup_on`. When a
  follow-up airs and no new one is scheduled, the record is demoted to `"one-off"`.
  One-offs are pruned to the most-recent ~200 (`by_name` entries pruned in
  lockstep). Nothing recurring survives without an audible return on the books.

## 4. Module signatures

All new modules are stdlib-only leaf modules: `writer`/`orchestrator` import them,
never the reverse (the invariant every leaf in `src/` states in its docstring).

### 4.1 src/arcs.py (rewrite — same public surface, new internals)

```python
MAX_ACTIVE = 2
REGISTERS  = ("mundane", "dream", "civic", "seasonal")

def load() -> dict                       # arcs.json, live→.bak→default
def save(state: dict) -> None            # atomic tmp+replace+.bak

def daily_tick(models: dict, date: str, census: dict,
               lore_state: dict) -> None
    # THE state machine, once per air-day (replaces today's LLM-rewrite tick):
    #  1. advance every active arc's `stage` while date >= beats[stage].on;
    #  2. an arc whose final beat has `aired` -> status "resolved", append its
    #     `resolution` to lore_state["recent_callbacks"] (enters lore), retire;
    #  3. an arc past payoff_on whose payoff never aired -> flag force_payoff
    #     (next compatible show must surface it, §4.2);
    #  4. if fewer than MAX_ACTIVE active -> mint_arc() one new arc in a setting
    #     absent from recent_settings.
    # Pure given (date, census, lore_state); the only LLM call is mint_arc.

def mint_arc(models, date, census, avoid_settings) -> dict
    # ONE constrained LLM draft -> the frozen skeleton (title/premise/setting/
    # register/3-6 dated beats incl. a PAYOFF beat). Validated & clamped; on any
    # failure returns a code-only fallback arc from a built-in premise bank, so a
    # bad model reply never blocks the station.

def surface(state, show_id, date, register_ok) -> dict | None
    # the ONE arc beat this show may weave today: the active arc whose current
    # beat is due, register-compatible with show_id, and unaired (force_payoff
    # arcs jump the queue). Marks nothing — the orchestrator flips `aired` after
    # the beat emits, so a crash mid-beat re-surfaces it.

def digest(state) -> str                 # UNCHANGED prompt text (§5)
```

### 4.2 Payoff guarantee

`payoff_on` is code-owned. `daily_tick` step 3: if `date > payoff_on` and the
payoff beat is still `aired == false`, the arc is marked `force_payoff`.
`surface()` returns a `force_payoff` arc to the **next** register-compatible show
regardless of the per-beat `on` date, and the orchestrator's normal aired-flip
retires it. An arc therefore cannot silently die unpaid — the worst case is a
payoff a day or two late, aired on the first show that fits its register.

### 4.3 Register routing (respects each show's guard)

`register_ok(show_id) -> set[str]` is a static table keyed by daypart id, derived
from the existing show contracts, not new policy:

| show | accepts registers | why |
|------|-------------------|-----|
| morning_scramble, complaints_department, the_handover, culture_vulture, refined_palate | mundane, civic, seasonal | these run the writer's **anti-conspiracy REGISTER GUARD** (`writer.py` `arc_line` else-branch): petty, human, mundane — exactly the mundane/civic/seasonal arc registers |
| night_shift | dream, mundane, seasonal | Dream Court is the `dream` register's only home |
| static_hour (Watcher) | **∅** | `lore_quarantine: true` — points OUTWARD, never shares lore; census/arcs skip it entirely (mirrors its existing lore exclusion) |
| center_ice | **∅** for town arcs | its own live-sports machine; the census still *records* its call-in fans (§4.6) but town arcs never intrude |
| dawn_patrol | ∅ | ambient idents, `sponsor: none` |

A `civic` arc surfaces as *town texture* on daytime talk (a Pothole-Commissioner
subplot), never on the Watcher. This is the "cross-show beats respect each show's
register" constraint, enforced by the table + the writer guard the show already
carries.

### 4.4 src/census.py (new leaf)

```python
HOODS    = (...)   # Halfway/Wending registry: "Lower Wending", "the pharmacy lot",
                   #  "Mile Zero", "the roundabout district", "Window 4 queue", ...
PROBLEMS = (...)   # ~40 mundane running problems, hood-flavored, disjoint from PROPS
DREAM_TOOLS = (...)# real, usable closure tools (Vivian's register): slow-breath
                   #  counts, "write it for morning-you", name five things you see...

def load() -> dict / save(state) -> None            # civilians.json discipline

def caller_assignment(state, show_id, date, used, rng, host_g) -> tuple[str, str|None]
    # THE desk router. If due_followup(state, show_id, date) -> a RETURNING
    # civilian: returns (clause naming them + their frozen problem/outcome/hook,
    # civ_id). Else a FRESH contrast-cast mint (opposite gender to host, exactly
    # today's behavior): returns (clause, None). `used` excludes both today's
    # names AND every stored civilian name (via by_name) so a fresh mint never
    # collides with a canon person.

def due_followup(state, show_id, date, rng) -> dict | None
    # head of `followups` whose date <= today AND register-compatible with
    # show_id; None otherwise.

def record_appearance(state, name, show_id, date) -> str
    # promote a newly-AIRED caller to a civilian record (or bump an existing one:
    # append show, ++appearances, set last_aired). Seeded P(followup | show)
    # schedules a return (Night Shift / Complaints richest; Center Ice fans thin).
    # Returns civ id.

def mint_civilian(state, rng, *, g, show_id, hood=None, problem=None) -> dict
def enrich_outcome(state, civ_id, aired_lines, models) -> None   # OPTIONAL (§4.5)
def digest(state, show_id, date) -> str                          # returning texture
```

### 4.5 Outcome enrichment (optional, bounded, fails safe)

`last_outcome` and the `dream` sub-record are the *only* fields an LLM may write to
a census record, and only via `enrich_outcome`: one cheap `models["performer"]`
call at the end of a follow-up-eligible show, summarizing the caller's resolution
in a single G/PG line, validated (length + content-guardrail regex) before it is
frozen. If the call is skipped, fails, or is disabled, `followup_hook` falls back
to `f"how's {problem} holding?"` over the **code-owned** `problem` phrase — which
already delivers the brief's "how's the sock ceasefire holding?" verbatim without
any dialogue parsing. Enrichment is enhancement, never a dependency.

### 4.6 Where a caller becomes a civilian

The orchestrator already walks each beat's emitted lines for new phone speakers
(`run_show`: `for ln in lines: if ln.get("phone") and spk...`, and the identical
loop in `run_center_ice`). That exact hook calls `census.record_appearance(...)`.
Most callers are one-offs (small `P(followup)`); only the register-rich shows
routinely schedule returns. No new pass over the dialogue — we piggyback the loop
that already exists.

### 4.7 Changed existing modules (small, surgical)

- **`orchestrator._mint_caller_line`** — instead of always calling
  `assignments.next_caller`, calls `census.caller_assignment(...)`. Returns the
  same shape of string it does today (a clause appended to the SWITCHBOARD block),
  so the beat prompt format is byte-identical when no follow-up is due.
- **`orchestrator.run_show` phone loop** — one added call to
  `census.record_appearance`; and after a returning-civilian beat, one guarded
  `census.enrich_outcome`.
- **`orchestrator`'s arc-tick block** (the existing
  `if st.get("arcs_day") != today: arcs.daily_tick(...)`) — new signature
  `arcs.daily_tick(models, date, census_state, state)` and a `census.save` beside
  `lore.save`. Still wrapped in the existing `try/except` that treats storylines as
  "garnish, never a blocker."
- **`lore.digest` / `lore.overused`** — source arcs from `arcs.load()` (sidecar)
  rather than `lore_state["arcs"]`; the emitted digest string and the arc-word
  staleness exemption are unchanged.

## 5. Desk & writer prompt-block contracts

Everything the LLM sees is an **authoritative block** in the established
SCOREBOARD/SWITCHBOARD register — the desk decides, the model authors around it.

**Arc block** (via the unchanged `arcs.digest`, appended by `lore.digest`, so the
outline and performer prompts are unmodified):

```
ONGOING STATION STORYLINES (weave in naturally, a line or two, when it fits):
- The Sock Ceasefire (day 2 of 4): the neighbor has started counting the clothespins
```

Only the arc `surface()` returns for this show/date is shown; a beat pinned to
another show is invisible here, so a show physically cannot pull an arc ahead of
its schedule or into the wrong register.

**Returning-caller clause** (appended to the SWITCHBOARD block by
`caller_assignment`, mirroring today's `_mint_caller_line` "If a NEW caller
joins, their name is X."):

```
SWITCHBOARD (authoritative): ... If a caller joins, it is MAUREEN calling BACK
(same person, same voice) — from Lower Wending; last time: agreed to try one week
of alternating laundry days. Ask how the sock ceasefire is holding. Do not invent
a different name, neighborhood, or backstory for her.
```

Because the name is `Maureen`, `_attach_voices` re-derives `af_kore` and the phone
tag automatically — no special path in TTS. The clause is authoritative like the
scoreboard; the guard (§6) is the backstop, not the first line of defense.

**Dream Court follow-up** (Night Shift only) additionally surfaces the frozen
`dream.tool_given`, so Vivian can ask whether the tool worked — serialized therapy
with real closure, the owner's explicit register, delivered from a code-owned
record.

## 6. Guard contract (the brief's central question)

> *How are an arc's asserted facts protected from contradiction — extend
> continuity/nameguard, or a facts table per arc?*

**Answer: neither a scoreguard-scale numeric guard nor nothing — a thin
`censusguard` over the checkable proper-noun class, backed by construction.**

Rationale, stated plainly: arc/civilian facts are **one-line prose** ("they split
the line with tape"), not tallies or margins. A narration guard that tried to
detect semantic contradiction of freeform prose would be unreliable in both
directions (false scrubs of correct lines violate every guard's prime directive;
missed contradictions give false confidence). `scoreguard`/`civicguard` work
because they check *numbers and enum stages* against a table — arcs have neither.
So the protection is layered by what is actually checkable:

1. **Construction (primary).** The desk surfaces exactly **one frozen beat** at a
   time through the authoritative block; a payoff string that hasn't reached its
   date is *not in the prompt*, so it cannot be narrated early. Names come from the
   collision-free desk bank; neighborhoods from the Halfway registry; voices are
   pure functions of names. There is nothing for the model to invent because the
   record supplies every proper noun.
2. **`censusguard.enforce` (backstop, new leaf, mirrors `nameguard`).** For a beat
   assigned a returning civilian or an arc with a `setting`, it corrects only:
   - a **neighborhood** token that contradicts the record's `hood` → nearest canon
     Halfway hood by edit-distance (`civicguard._nearest`), or a neutral deflection
     if none is close;
   - real-world names on civilian-facing shows → reuse `nameguard.enforce_names`
     with the census record's name in `extra_ok`.
   It never touches a line that is merely *developing* the frozen fact — the prime
   directive from every sibling guard (a correct line is never touched).
3. **Continuity/switchboard (already shipped).** A returning civilian is still a
   caller: `switchboard.enforce` owns her on-air lifecycle (wrap, budget, no
   resurrection) exactly as today, and `continuity.enforce` still blocks premature
   sign-offs. No change needed there.

```python
# src/censusguard.py
def build_census_facts(civ: dict | None, arc: dict | None) -> dict
    # -> {"name", "hood", "hoods_ok": HOODS, "name_ok": {name}}  (frozen)
def enforce(lines: list[dict], facts: dict) -> list[dict]
    # neighborhood correction + real-world scrub; new list, inputs unmutated
```

Why not a per-arc facts table: it would store the same one-line beats we already
freeze in `arcs.json` and could only "check" them by string-matching the very
strings the performers are told to paraphrase — catching nothing and scrubbing
paraphrase. The frozen beat *is* the facts table; the desk's authoritative block
*is* its enforcement. We spend the guard budget only where a token is genuinely
checkable against a registry.

## 7. Build order (parallelizable pure components + tests)

Each row is a pure module against the §3 schemas; A–D have zero interdependency
beyond those schemas. E integrates. Mirrors `hockey-minimal.md` §9 discipline.

| # | Component | Deliverable | Test strategy |
|---|-----------|-------------|---------------|
| A | `census.py` core | `mint_civilian`, `record_appearance`, `due_followup`, `caller_assignment`, banks, prune | Seeded golden: same seed → same name/hood/voice; `record_appearance` twice on one name → one record, appearances==2, `by_name` stable; `caller_assignment` returns a fresh contrast-cast name when no follow-up due, the exact returning civilian when one is; prune keeps all recurring, caps one-offs at 200; voice equals `performers._spare_voice(name)` for 1k names. |
| B | `arcs.py` state machine | `daily_tick`, `surface`, `mint_arc` (LLM mocked), `digest` | Given a frozen skeleton: `stage` advances on/after each `beats[i].on`, never before; a resolved arc appends its `resolution` to a passed lore dict exactly once and retires; a `payoff_on`-passed unaired arc force-surfaces on the next compatible show; `< MAX_ACTIVE` triggers exactly one mint in a setting outside `recent_settings`; `digest` byte-matches today's format. |
| C | `censusguard.py` | `build_census_facts`, `enforce` | Wrong-neighborhood line → corrected to record hood; correct/paraphrase line → untouched (prime directive, 50 hand-written correct lines → 0 scrubs); real-world name on a civilian show → scrubbed; census name in `extra_ok` → never scrubbed. |
| D | Desk/prompt wiring | `caller_assignment` clause, arc block routing, `register_ok` table | Golden-string tests: returning clause names person+hood+outcome+hook and forbids reinvention; no-follow-up path emits today's exact `_mint_caller_line` string; `register_ok(static_hour) == ∅`, `night_shift` accepts `dream`; a `dream` arc never surfaces on a daytime show. |
| E | Integration + bootstrap | orchestrator hooks, `lore.py` sidecar sourcing, `scripts/migrate_arcs.py`, gate | Offline dry-run on a copied state dir: migrate lore arcs → tick 30 synthetic days → assert every arc reaches payoff or retires, civilians accrete and prune under budget, no exception escapes the arc/census try-blocks, prompt strings render. Fallback test: delete `arcs.json` → orchestrator falls back to the legacy LLM tick with zero errors. |

## 8. Bootstrap & migration

- **`civilians.json`: born empty.** Callers were ephemeral (`callers_today`, wiped
  daily) — there is nothing to back-fill and nothing lost. The census accretes from
  tonight's first aired caller. Missing file → `census.load()` returns the empty
  default; `caller_assignment` degrades to today's always-fresh mint. **No gate
  needed** — the census is purely additive and self-bootstrapping.
- **`arcs.json`: migrated from `lore_state["arcs"]`.** Today's arcs carry only
  `{title, premise, day, max_days, latest, status}` — no schedule. One idempotent
  script, **`scripts/migrate_arcs.py`**, wraps each *active* arc into the §3.1
  schema: synthesize `beats` by spreading the remaining `max_days - day` days from
  today to `today + (max_days - day)`, freeze the current `latest` as the current
  beat, mark it `aired`, put a `PAYOFF:` beat on the last day, infer `register`
  from setting keywords (default `mundane`), `cast: []`. Write `arcs.json`; leave
  `lore_state["arcs"]` in place (harmless — `lore.digest` now reads the sidecar).
- **Feature gate + instant fallback.** `lore.digest`/`arcs.daily_tick` prefer
  `arcs.json` when it parses; if it is absent or corrupt they fall back to the
  legacy in-`lore_state` LLM path (kept in the tree one release for safety). Rollback
  is `rm arcs.json` — the station reverts to today's behavior with zero repair, the
  census keeps working independently. Both new files use `.bak` sidecars; any parse
  failure is a loud print + degrade, never a crash (matching the existing
  `(arc tick skipped: ...)` posture).

## 9. Risk register

| # | Risk | Mitigation |
|---|------|-----------|
| 1 | Follow-up lands on the wrong show/register (Maureen calls the sports show) | `register_ok` table + `due_followup` register filter; `static_hour`/`center_ice`/`dawn_patrol` accept ∅ town follow-ups; Watcher quarantine preserved exactly. |
| 2 | Voice drift if `_spare_voice` changes | `voice` stored in the record; `censusguard`/site read the stored value; name is unchanged so the derivation also matches. |
| 3 | Fresh mint collides with a stored civilian name | `caller_assignment` unions `by_name` into the desk's `used` exclusion set; `by_name` reverse index reunites a re-minted name with its record instead of forking. |
| 4 | Census unbounded growth | Recurring kept only while a future follow-up is scheduled; one-offs pruned to last ~200; every recurring byte paid for by a booked audible return. |
| 5 | Arc never pays off (degenerate skeleton) | Code owns `payoff_on`; `force_payoff` guarantees the payoff airs on the next compatible show; `mint_arc` failure → code-only fallback arc from a premise bank. |
| 6 | Cross-show contradiction of a frozen arc/civilian fact | Construction (one frozen beat via authoritative block) + `censusguard` proper-noun correction; residual prose-paraphrase contradiction accepted as low-probability, low-stakes (a one-line town subplot, not a score). |
| 7 | Two arcs collide on one setting/civilian | `recent_settings` variety guard at mint; a civilian belongs to ≤ 1 active arc (`arc` field); `MAX_ACTIVE = 2`. |
| 8 | Content-guardrail breach in an LLM-authored beat/outcome | `mint_arc` and `enrich_outcome` validate against the G/PG regex before freezing; the frozen string is then immutable, so it can't drift into a breach later. |
| 9 | Live-air safety | All new work inside the existing once-per-air-day arc block and the existing phone-loop, all `try/except`-wrapped as "garnish, never a blocker"; atomic writes; missing sidecar → degrade to today's behavior. |
| 10 | Restart re-airs or skips a beat | `beats[i].aired` flipped only after emit; `surface()` re-returns an unaired due beat after a crash; `arcs_day` guard already prevents a double daily tick. |

## 10. What this deliberately does not build

No new engine, no world-event bus (Track B), no per-arc numeric guard, no dialogue
NLP to extract outcomes, no new hot-loop code, no schedule.yaml changes, no new
prompt format. The whole feature is: promote `arcs.py` to a state machine, persist
the caller the desk already mints, and route both through the one desk function and
one prompt block that already exist. That is the minimal desk extension that turns
tonight's callers into next month's returning cast.
