# Narrative Arcs + the Town Census — CONTINUITY-FIDELITY Design

Lens: an arc or a civilian must **never contradict anything that has aired**.
So this design fixes the fact-protection layer first — the state machines that
own the canon and the guard that enforces it — and only then hangs story
mechanics off them. The governing rule, inherited verbatim from the hockey and
statehouse engines: **code owns facts, the LLM authors; aired facts are canon
forever; a guard REPLACES contradictions (never cuts); no correct line is ever
touched.**

## 1. Executive summary

- **Two tiny sidecars, repo-root, siblings of `season.json`/`civics.json`:**
  `arcs.json` (multi-beat storylines with a payoff) and `civilians.json` (the
  persistent town census). Both atomic tmp+replace with a `.bak` copy. Missing
  or corrupt → the station degrades to today's behavior (LLM-free arcs off,
  callers ephemeral). Nothing here can take the air down.
- **Identity is derived, not stored — the biggest continuity win is free.** A
  civilian's *voice* is already a pure function of her name
  (`performers._spare_voice`, md5-stable + gender-pinned). "Maureen" gets the
  same telephone voice on every show, on every day, forever, with **zero new
  state**. The census stores *who exists and what aired about them*, never the
  voice. Gender and neighborhood are likewise re-derivable from the name/id
  seed; we freeze them on air only as belt-and-braces.
- **A facts table per arc + one new guard, not an extension of `continuity.py`
  or `nameguard.py`.** `continuity.py` polices *promises and sign-offs*;
  `nameguard.py` scrubs *real-world hockey*. Arc/census canon is a third,
  orthogonal concern, so it gets its own leaf: **`canonguard.py`**, mirroring
  `civicguard.py` component-for-component (`build_canon_facts` → digest tables;
  `enforce_canon` → walk-and-replace; edit-distance nearest for phantom
  civilian names; neutral in-register templates; prime directive preserved).
- **The guard is SCOPED, so fresh callers stay free.** General call-in mints new
  names every hour; scrubbing every unknown name would be catastrophic. The
  guard only tightens on lines inside a beat the desk flagged as an **arc beat
  or a scheduled follow-up** (`facts["scope"]`), where a specific civilian's
  canon is in play. Everywhere else it is a no-op.
- **The assignment desk is the drip-feed.** The desk already assigns
  guest/sponsor/callback/props authoritatively; it gains two picks — today's
  **arc beat** for this show and today's **due follow-up** — and two prompt
  blocks in the SCOREBOARD register. The returning civilian's name flows into
  the switchboard's caller-mint so a follow-up caller keeps her identity (hence
  her voice) instead of being minted fresh.
- **One LLM pass/day, exactly like today's `arcs.daily_tick`.** The "story
  editor" advances arc stages, schedules beats, promotes due follow-ups, and —
  critically — *summarizes what aired into frozen canon*. It never invents a
  fact that outruns the air: a civilian's problem/outcome is summarized **from
  the aired transcript tail**, then stamped, so the summary can't contradict
  what listeners heard.
- **Box fit:** both sidecars < 200 KB steady-state; the guard is regex +
  edit-distance, ~1 ms/beat; no network in the hot loop.
- Ship order: `store` → `census` → `arcs` (state machine) → `canonguard` →
  desk blocks → integration + migration. A–D are pure and parallelizable.

## 2. State schema

Both files atomic tmp+replace + `.bak` (the `season._save` / statehouse
`save_side` pattern). Lists bounded; append-only ledgers pruned by status, not
by age (a resolved civilian's canon is never deleted — it's demoted to
`dormant` and kept, because it may still be referenced).

### civilians.json (~60–120 KB at a few hundred residents)

```json
{
  "schema": 1,
  "residents": {
    "cv-maureen-1": {
      "name": "Maureen", "surname": "Kowalczyk",
      "gender": "f", "hood": "the pharmacy-lot blocks",
      "problem": "a sock-drawer ceasefire with her upstairs neighbor",
      "status": "active",
      "first_aired": "2026-06-18", "shows": ["culture_vulture", "night_shift"],
      "appearances": [
        {"date": "2026-06-18", "show": "culture_vulture",
         "outcome": "declared a truce over shared laundry", "aired": true},
        {"date": "2026-07-02", "show": "night_shift",
         "outcome": "the truce is holding but the dryer is not", "aired": true}
      ],
      "facts": [
        {"fid": "f1", "kind": "relationship", "key": "neighbor",
         "value": "upstairs", "aired": "2026-06-18"},
        {"fid": "f2", "kind": "place", "key": "home",
         "value": "the pharmacy-lot blocks", "aired": "2026-06-18"},
        {"fid": "f3", "kind": "outcome", "key": "sock_ceasefire",
         "value": "a truce, holding", "aired": "2026-07-02"}
      ],
      "follow_up": {"due": "2026-07-23", "show": "culture_vulture",
                    "question": "how's the sock ceasefire holding?",
                    "consumed": false},
      "arc_ref": null, "register": "mundane"
    }
  },
  "used_names": ["Maureen", "Ruth", "Al"],
  "roster_by_hood": {"the pharmacy-lot blocks": ["cv-maureen-1"]}
}
```

- `name`/`surname` come from the desk's caller banks (`assignments.CALLERS_*`)
  + a small surname bank; **`gender` and `hood` are derivable** (`_gender_of`,
  `Random("hood:"+id).choice(HOODS)`) and stored only so `canonguard` need not
  import `performers`. Voice is *never* stored — `_spare_voice(name)` owns it.
- `facts[]` is the **append-only canon table** the guard protects. `kind` ∈
  {name, place, relationship, job, quantity, outcome, dream, tool}; `key` is
  the slot (so a later fact with the same `key` but a different `value` is a
  *contradiction*, not an addition); `aired` is the ISO date it reached
  listeners (`null` = scheduled but not yet aired → guard treats as a
  pre-air spoiler if a line asserts it as settled).
- `follow_up` is the "three weeks later" hook: a single pending question keyed
  to a show and a due date. Scheduling state — **stored, not derived.**
- `used_names` is the station-wide no-reuse set, migrated out of
  `station_state["callers_today"]`; the desk excludes every name here when
  minting a *new* caller, so a fresh caller can never collide with a resident.

### arcs.json (~30–80 KB)

```json
{
  "schema": 1,
  "arcs": {
    "arc-roundabout-fern-3": {
      "title": "The Roundabout Fern",
      "premise": "someone left a potted fern in the Mile Zero roundabout; the town adopts it",
      "register": "mundane",
      "stage": "COMPLICATION", "stage_idx": 2,
      "opened": "2026-07-04", "payoff_date": "2026-07-14",
      "cast": {"civilians": ["cv-doreen-2"], "canon": ["the roundabout", "Toivo Ostberg"]},
      "facts": [
        {"fid": "a1", "kind": "place", "key": "location",
         "value": "the Mile Zero roundabout", "aired": "2026-07-04"},
        {"fid": "a2", "kind": "name", "key": "fern_name",
         "value": "Sheila", "aired": "2026-07-06"},
        {"fid": "a3", "kind": "outcome", "key": "payoff",
         "value": "the town votes to make Sheila the roundabout's official tenant",
         "aired": null}
      ],
      "beats": [
        {"bid": "b1", "due": "2026-07-04", "show": "morning_scramble",
         "stage": "SEEDED", "directive": "a fern has appeared in the roundabout; nobody will move it",
         "status": "aired", "aired_date": "2026-07-04"},
        {"bid": "b4", "due": "2026-07-14", "show": "morning_scramble",
         "stage": "PAYOFF", "directive": "the town formally adopts Sheila; Toivo relieved",
         "status": "pending", "aired_date": null}
      ],
      "latest": "Sheila the fern now has a tiny hand-painted sign",
      "status": "active"
    }
  },
  "recent_settings": ["roundabout", "pharmacy lot", "the Sieve"]
}
```

- `register` ∈ {mundane, conspiracy, dreamcourt, civic, sports} — the hard
  boundary against the anti-conspiracy guard (§5). The desk assigns a beat
  **only to a register-compatible show** (a mundane arc never lands on the
  Watcher; a conspiracy arc never lands on the daytime shows whose writer
  prompt bans that register).
- `stage`/`stage_idx` drive the state machine (§4). `facts[]` and its
  aired-stamp discipline are identical to the census — the arc's `payoff`
  fact is the spoiler tripwire.
- `beats[]` are pre-scheduled to a **show + date**. A beat fires only when that
  show actually airs on/after `due`; a preempted beat reschedules forward
  (never fires early), so an arc can slip but never skip its own payoff.
- `latest` is the single line `lore.digest` weaves in — the ONLY bridge from
  arcs into the free-text lore digest (§6 boundary).

## 3. Module & file breakdown

All new modules stdlib-only leaf modules under `src/`, pure functions against
the §2 schemas. `writer`/`orchestrator`/`performers` import them; they import
nothing upward (the established leaf rule — mirrors `assignments`, `switchboard`,
`civicguard`).

**src/store.py** (~50 lines) — the shared sidecar IO both files use.
```python
def load(path: Path, default: dict) -> dict          # live file, then .bak, then default
def save(path: Path, obj: dict) -> None              # atomic tmp.<pid> + replace + .bak
```
Lifted verbatim from `statehouse.engine.load_side/save_side` (never re-solves a
solved problem); `season.json`'s "never silently reset a live spine on a read
race" rule applies.

**src/census.py** (~180 lines) — the registry, pure and seeded.
```python
HOODS = (...)  # Halfway canon: pharmacy-lot blocks, Mile Zero fringe, the Sieve
               # side, Window-4 row, the U-Haul lot, half-duplex row, ...
def new_id(name: str, existing: dict) -> str             # "cv-<slug>-<n>", never collides
def mint(name: str, date: str, show: str, existing: dict) -> dict
    # identity-only record: derives gender (_gender_of), hood (seeded), voice NOT stored
def record_appearance(rec: dict, date: str, show: str, outcome: str) -> None  # aired stamp
def add_fact(rec: dict, kind, key, value, date: str | None) -> None  # append-only, no dup key/value
def schedule_follow_up(rec: dict, date: str, rng) -> None   # due = date + rng(14,28)d, keyed to show/register
def due_follow_ups(civ: dict, date: str, show: str) -> list[dict]   # unconsumed, due, register-matched
def digest_for_guard(civ: dict, ids: list[str]) -> dict     # -> the fact tables canonguard walks
```

**src/arcs.py** (extended, ~+140 lines) — the state machine. Keeps the existing
`daily_tick`/`digest` names so `lore.py`/`orchestrator` need no rename.
```python
STAGES = ("SEEDED", "RISING", "COMPLICATION", "CRISIS", "PAYOFF", "LORE")
def advance(arc: dict, date: str) -> None                 # stage_idx += 1 when a stage's beat aired
def schedule_beats(arc: dict, schedule: dict, rng) -> None  # place remaining stages on register-OK shows/dates
def next_beat(arc: dict, date: str, show: str) -> dict | None   # today's beat for this show, if any
def mark_aired(arc: dict, bid: str, date: str, aired_text: str) -> None  # freeze facts referenced this beat
def gate_payoff(arc: dict, date: str, show: str) -> bool  # PAYOFF fires ONLY on its scheduled show/date
def daily_tick(models, arcs_state, civ_state, schedule) -> None  # the once-a-day story-editor pass (§4)
def digest(arcs_state) -> str                             # unchanged contract: the weave-in lines
def new_arc(...) -> dict                                  # SEEDED arc from an LLM proposal, register-tagged
```

**src/canonguard.py** (~230 lines) — the guard, mirroring `civicguard.py`.
```python
def build_canon_facts(arcs_state, civ_state, *, scope_ids, scope="none") -> dict
def enforce_canon(lines, facts) -> list[dict]            # walk + REPLACE; input never mutated
```

**Changed modules (small, additive diffs):**
- `src/assignments.py`: `pick_arc_beat(...)`, `pick_follow_up(...)`, and a
  `canon_block(arc_beat, follow_up)` writer block (§7). `next_caller` gains an
  `identity` path so a follow-up reuses the resident's name (§7).
- `src/writer.py`: threads `daypart["_assign"]["arc_beat"]` /
  `["follow_up"]` into the outline prompt via `canon_block` — no structural
  change, one more block alongside `writer_block`.
- `src/orchestrator.py`: the desk block gains the two picks; `canonguard.enforce_canon`
  runs in the beat loop right after `_switch.enforce`/`_cont.enforce`
  (same pattern, same place); a **census-mint hook** after each aired beat; the
  arc daily-tick call now reads/writes the sidecars instead of `lore_state`.
- `src/lore.py`: `digest` keeps calling `arcs.digest` (unchanged), but arcs
  state comes from `arcs.json`, not `lore_state["arcs"]` (§9 migration).

## 4. The state machine + the daily story-editor pass

Two clocks, exactly like the engines: a **deterministic scheduling clock** (code,
every day) and a **narration clock** (LLM, once/day). No arc fact is ever born
in a show beat — only summarized *from* one after it airs.

**`arcs.daily_tick(models, arcs, civ, schedule)`** — runs once per air-day
(gated on `station_state["arcs_day"]`, exactly as today):

1. **Freeze what aired.** For every beat that aired since the last tick (status
   flipped by the mint hook, §8), the editor reads the beat's aired transcript
   tail and writes/normalizes the arc's referenced `facts` with today's date —
   *summarize, never invent past the air*. A civilian named in the beat gets
   `record_appearance` + `add_fact` the same way. **This is the only writer of
   `aired`-stamped facts.**
2. **Advance stages.** Any arc whose current-stage beat aired → `advance`. An
   arc reaching `PAYOFF` whose payoff beat aired → `stage="LORE"`, `status`
   demoted after one lingering day (its payoff line stays in the digest a day,
   then falls off — today's behavior preserved).
3. **Schedule the next beats.** `schedule_beats` places each not-yet-aired stage
   on the next eligible **register-compatible** show/date from `schedule.yaml`.
   Preempted beats (a Center Ice night ate the Scramble) roll forward.
4. **Promote due follow-ups.** `census.due_follow_ups(civ, date, show)` for
   each show tomorrow → mark them as candidate picks the desk will see.
5. **Seed replacements.** If active arcs < `MAX_ACTIVE` (2), the editor proposes
   ONE new arc (LLM, the existing `_EDITOR` prompt, hardened to emit a
   `register` and a `cast` of *existing* civilian ids where it wants a returning
   face). `new_arc` tags it SEEDED and schedules its beat chain.

The LLM proposes *structure and flavor*; code owns *when a fact is real*. Seeds
are `Random(f"arc:{arc_id}:{date}")` / `Random(f"fu:{cid}:{date}")` — replay-safe.

**Payoff gating (the anti-spoiler spine).** `gate_payoff` returns true only when
`today == beat.due_show` and the arc has passed through every prior stage. Until
then the `payoff` fact carries `aired: null`, and `canonguard` treats any line
asserting the resolution as a **pre-air spoiler** and neutralizes it (§5, catch
5) — the same discipline as civicguard's result-before-air and the hockey
engine's air-gated final.

## 5. Guard contract — `canonguard.py`

**Answering the brief's explicit question** ("extend continuity/nameguard vs. a
facts table per arc?"): **a facts table per arc AND per civilian, protected by a
dedicated new guard.** Rationale: `continuity.py` and `nameguard.py` own
unrelated concerns and share no fact surface with arcs; folding canon into them
would entangle three regex regimes and three replacement registers. `canonguard`
mirrors `civicguard` — the proven shape — and stays a pure leaf.

`build_canon_facts(arcs, civ, *, scope_ids, scope)` digests only the arcs and
civilians **in scope for this beat** into lookup tables:

```
{ "scope": "arc" | "followup" | "none",
  "names_ok": {resident + cast names, lowercased},   # collisions favour the fiction
  "full_names": {display names for edit-distance nearest},
  "fact_by_key": {(subject_id, kind, key): value},   # the canon slots
  "aired_keys": {(subject_id, kind, key) that have an aired date},
  "hoods": {resident_id: hood},
  "register": "mundane" | ...,                        # the in-scope arc's register
  "banned_register_words": {conspiracy/woo lexicon} if register != that show's } 
```

`enforce_canon(lines, facts)` — walk every line; **when `scope == "none"` it is a
pure pass-through** (fresh call-in is untouched). In scope, catches, each a
REPLACE with an in-register neutral (never a cut — a cut dangles the partner's
reply), prime directive intact (a correct line is never touched):

1. **Phantom in-scope civilian name** → nearest real name by edit-distance
   (`civicguard._nearest`), *only* against the scoped `full_names` — never the
   whole census, so a genuinely new walk-on isn't renamed into a resident.
2. **Contradicted canon fact** — a line asserting `(subject, kind, key) = X`
   where the table holds `Y ≠ X` (Maureen's neighbor is *upstairs*, not "her
   sister"; the fern is at *the roundabout*, not "the library") → neutral
   ("That's not how Maureen tells it — let's not put words in her mouth.").
   Detection: keyed value-phrase match around the subject mention; numeric
   `quantity` facts reuse the tally-pair machinery.
3. **Neighborhood/geography contradiction** — a resident pinned to one hood
   placed in another; Halfway geography is wending-bible canon → neutral.
4. **Register violation** — an in-scope arc beat leaking a banned register
   (conspiracy/woo words in a `mundane` arc, or vice-versa) → neutral in the
   *correct* register. Backstops the writer's prompt-level register guard at the
   line level, where it demonstrably slips at temp 0.9.
5. **Pre-air spoiler** — a line stating a fact whose slot is still `aired: null`
   (the arc's unannounced payoff, a follow-up outcome not yet reached) as though
   settled → "Nothing's been decided on that yet." Modal/hypothetical lines
   (`_MODAL`, reused from civicguard) pass whole — a host *may* speculate.

Templates are register-keyed (mundane/dreamcourt/civic each get their own
neutral bank) so a replacement never sounds like it wandered in from another
show. `_enforced` is stamped, matching every sibling guard.

## 6. Boundary with existing lore (explicit, per the brief)

- **arcs.json is authoritative for arcs; `lore_state` never stores arc facts.**
  The only bridge is `arcs.digest()` → the "ONGOING STATION STORYLINES" block
  the outline prompt already carries. `lore.overused()` already exempts arc
  words from the staleness ban — that stays.
- **running_jokes / recent_callbacks stay one-off.** A callback is a single
  reference the desk may assign once (`pick_callback`); an **arc** is a
  code-scheduled *chain* of beats with a payoff date and a guarded fact table.
  They never merge: an arc's payoff *may* graduate into a running joke on
  `stage=LORE` (the editor emits it as a `new_joke`), which is the one-way door
  from arc → lore. Nothing flows the other way.
- **Civilians are canon; guests are not.** The guest pool (`personas/guests.md`)
  is a fixed bit-cast the writer draws from; civilians are *emergent* residents
  the desk mints. A civilian never becomes a guest and vice-versa; the census
  guard never touches guest names (they're in `names_ok` via the persona path).

## 7. Assignment-desk + writer prompt contracts

The desk (run in `orchestrator.run_show`) gains two picks, both authoritative:

```python
_assign["arc_beat"]  = arcs.next_beat_for_show(arcs_state, date, daypart["id"])
_assign["follow_up"] = census.due_follow_ups(civ_state, date, daypart["id"])[:1]
```

`assignments.canon_block(arc_beat, follow_up) -> str` (SCOREBOARD register):

```
CONTINUITY DESK (authoritative — canon, do not contradict):
- ARC BEAT (weave into exactly one mid-show beat): "The Roundabout Fern",
  day 3 — TONIGHT'S development: the town starts leaving it tiny gifts.
  Canon you must honor: the fern is at the Mile Zero roundabout; its name is
  Sheila; Toivo Ostberg is the foreman. Do NOT resolve the story tonight.
- CALL BACK a real resident: MAUREEN returns tonight (from the pharmacy-lot
  blocks; her upstairs-neighbor sock ceasefire is holding). The host greets
  her as a returning caller and asks: how's the sock ceasefire holding? Keep
  every stated fact consistent with the above; invent nothing that contradicts it.
```

Wiring for the returning caller's **identity + voice**: when `_assign["follow_up"]`
is set, `orchestrator._mint_caller_line` uses the resident's *name* instead of
minting a fresh one (`assignments.next_caller(..., identity="Maureen")`). Because
`performers._spare_voice("Maureen")` is deterministic, Maureen re-enters on the
exact voice she left on — continuity with **no stored voice, no new code path in
TTS.** The follow-up's `consumed` flag is set once the beat airs so she isn't
re-summoned the next day.

The desk's *new*-caller mint (`_mint_caller_line`) now excludes
`civ_state["used_names"]`, so a fresh caller can never be born with a resident's
name (the collision that would silently merge two people into one voice).

## 8. The census-mint hook (orchestrator)

After each show beat airs, in the existing caller-name tracking loop
(`for ln in lines: if ln.get("phone")...`):

```python
for ln in lines:
    if ln.get("phone") and (nm := ln.get("speaker","").split()[:1]):
        first = nm[0]
        if first not in civ_used and not _is_followup_speaker(first):
            rec = census.mint(first, date, daypart["id"], civ_state["residents"])
            civ_state["residents"][rec["id"]] = rec        # identity-only; facts come at the daily tick
            civ_state["used_names"].append(first)
```

Only **identity** is written here (name → derived gender/hood; voice derived on
demand). The *soft* facts (problem, outcome) are filled by the next daily
story-editor pass from the aired tail, so they can't outrun the air. A returning
follow-up caller matches an existing record and just gets a new `appearance`
stamped. `civilians.json` is saved with the same atomic discipline as
`lore.save`. This hook replaces the ad-hoc `station_state["callers_today"]`
blacklist — one source of truth for who has ever called.

## 9. Bootstrap / migration

Idempotent, gate-off, one script `scripts/migrate_census.py`:

1. **Arcs:** lift any live `lore_state["arcs"]` into `arcs.json` — each becomes
   a `mundane`-register arc, `stage` mapped from its `day/max_days` ratio onto
   the STAGES ladder, existing `latest` preserved, a payoff beat scheduled on
   the next Scramble. `lore_state["arcs"]` is then emptied; `arcs.digest` reads
   the sidecar. If the sidecar is absent the code path is today's behavior.
2. **Census:** seed `civilians.json` empty except `used_names`, copied from the
   union of `station_state["callers_today"]` across recent days (best-effort —
   past callers weren't persisted as records, so they're name-reserved but not
   resurrected; new callers accrue from cutover forward). No back-fill of
   transcripts — canon starts clean and only grows from aired-forward facts,
   which is exactly the fidelity guarantee (we never assert a "fact" about a
   past call we didn't record).
3. **Gate:** a `data/arcs/ENABLED` flag (checked once/show); absent → desk skips
   the two picks and the guard runs in `scope="none"` (pass-through). Instant
   fallback is `rm` the flag; both sidecars stay warm on disk.
4. **Verify:** `scripts/verify_census.py` — round-trips a synthetic arc + two
   civilians through `build_canon_facts`/`enforce_canon` asserting (a) zero
   replacements on a fully-consistent beat, (b) each catch fires on a crafted
   violation, (c) `scope="none"` is a byte-identity pass-through over 500 lines
   of ordinary call-in, (d) a scheduled payoff beat is spoiler-blocked before
   its date and passes on it.

## 10. Build order (pure components, per-component tests)

| # | Component | Deliverable | Test strategy |
|---|-----------|-------------|---------------|
| A | `store.py` | `load`/`save` | tmp+replace+.bak round-trip; corrupt live file falls back to `.bak`; concurrent-read never sees a partial. |
| B | `census.py` | mint, derive, follow-ups, `digest_for_guard` | Seeded golden: same name → same hood/gender across runs; `new_id` never collides; `due_follow_ups` respects register+date; voice-derivation parity with `performers._spare_voice`. |
| C | `arcs.py` state machine | `advance`, `schedule_beats`, `gate_payoff`, `mark_aired` | Property tests: stages advance only on aired beats; a payoff never schedules before all prior stages; preempted beat rolls forward, never fires early; `daily_tick` idempotent for a given (date, seed). |
| D | `canonguard.py` | `build_canon_facts`, `enforce_canon` | Table-driven: one crafted line per catch (1–5) → exactly one replacement; a consistent beat → zero; `scope="none"` → identity; edit-distance renames only within scoped names; prime-directive fuzz (1k correct lines, zero touches). |
| E | desk blocks + writer thread | `pick_arc_beat`, `pick_follow_up`, `canon_block`, follow-up identity mint | Golden prompt-render; returning caller keeps name→voice; new-caller mint excludes `used_names`. |
| F | integration + migration | orchestrator wiring, mint hook, `daily_tick` on sidecars, migrate/verify scripts | Offline dry-run on a copied state dir: mint 20 callers over 10 synthetic days → 3 due follow-ups fire on the right shows; one arc runs SEEDED→PAYOFF with the payoff spoiler-blocked until its date; sidecars under size budget; guard adds < 2 ms/beat. |

A–D have no interdependency beyond §2 schemas. F needs A–E.

## 11. Calibration (light)

- **Follow-up cadence:** `rng(14, 28)` days keeps the "three weeks later" feel;
  cap **one due follow-up per show per day** so a night never turns into a
  reunion special. Target ≈ 1 returning civilian every 2–3 shows once the
  census warms (≈ 30+ residents); a pytest asserts the promoter never exceeds
  the cap and never promotes a `consumed`/`dormant` record.
- **Arc load:** `MAX_ACTIVE = 2` (unchanged), 3–6 day lifespans, ≤ 1 beat per
  show per day, ≤ 1 arc payoff per day station-wide (the one-thread discipline
  from wending canon, applied to arcs).
- **Guard false-positive budget:** the prime-directive fuzz test (D) is the
  calibration gate — any change to the catch regexes re-proves zero touches on
  1k known-good lines before it can land.

## 12. Risk register

| # | Risk | Mitigation |
|---|------|-----------|
| 1 | Guard scrubs a legitimate fresh caller | Guard is scope-gated; `scope="none"` (all non-arc/non-follow-up beats) is a proven pass-through; phantom-name rename is confined to scoped `full_names`. |
| 2 | LLM-summarized problem/outcome is wrong and freezes as canon | Summaries are written **from the aired tail only**, after the beat airs — they can restate but not contradict what listeners heard; `aired: null` facts are spoiler-blocked until their beat fires. |
| 3 | Two people merged into one voice via a name collision | `used_names` is the single source of truth; new-caller mint excludes it; follow-ups match by id, not by re-minting. |
| 4 | An arc never reaches its payoff (show preempted) | Beats reschedule forward on register-compatible shows; payoff gated to its scheduled show/date but slippable — slips, never skips. |
| 5 | Register bleed (mundane arc on the Watcher, or conspiracy on daytime) | Arc `register` gates which shows the desk assigns a beat to; `canonguard` catch 4 backstops leaks at the line level. |
| 6 | Sidecar corruption / partial write | store.py atomic tmp+replace+.bak; any parse failure → default → today's behavior; gate `rm` reverts instantly, sidecars kept warm. |
| 7 | Census unbounded growth | Records demote to `dormant` (never deleted — canon persists) but drop out of the follow-up promoter; steady-state < 200 KB at hundreds of residents; digest only ever loads scoped ids. |
| 8 | Daily editor pass fails (network) | Wrapped exactly like today's `arcs.daily_tick` — "storylines are garnish, never a blocker"; the deterministic scheduling clock (beats, follow-ups) runs regardless; only new-fact summarization waits for the next successful pass. |
```
