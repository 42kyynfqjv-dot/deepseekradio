# Arcs + Census — FINAL SYNTHESIZED DESIGN

Backbone: **arcs-census-continuity.md** (judge winner, 50/60) adopted verbatim
— per-arc/per-civilian FACTS TABLES protected by a new leaf `canonguard.py`
(scope-gated: only tightens on desk-flagged arc/follow-up beats; ordinary
call-in is a proven pass-through), aired-stamp discipline (payoff facts
spoiler-blocked until their scheduled beat), the assignment desk as the
drip-feed with a CONTINUITY DESK authoritative block, voice/gender/hood
DERIVED never stored (a returning civilian re-enters on the identical voice
by construction), daily story-editor pass reads only the aired tail.

## Grafts (judge-directed)

1. From **desk-minimal**: PROMOTE, don't add — rewrite existing `src/arcs.py`
   into the code-owned state machine (LLM drafts the frozen skeleton ONCE at
   arc birth; code owns scheduling/stage-advance/payoff-firing/retirement
   with a force-air `payoff_on` window); piggyback the orchestrator's
   existing phone-line detection loop for census appearance recording;
   register-routing table derived from existing show contracts (Watcher/
   lore_quarantine gets none).
2. From **empowerment**: the Dream Court clerk — a cheap off-hot-path pass
   capturing `{feeling, tool, verdict}` per case; census schedules a 14–28
   day follow-up that names the ACTUAL tool ("how's that four-count breath
   holding up?"); arc→lore one-way graduation on resolution.
3. Judge fix — **name-pool sustainability**: banks are doubled (done, ~60/
   gender); the desk additionally prefers a RETURNING civilian for ~1 in 4
   minted calls (reuse by design burns no fresh names and IS the census
   payoff); when a gender pool still runs dry, mint "FirstName from the
   {neighborhood}" distinguishers rather than repeating a bare name.

## Build components (fleet — each pure, own tests, repo test style)

| ID | Deliverable |
|----|-------------|
| A | `src/canonguard.py` + tests — the facts-table guard per continuity §guard (replace-never-cut, scope-gated, neutral templates per show register) |
| B | `src/arcs.py` rewrite + `data/arcs/arcs.json` schema + tests — state machine, scheduling, force-air payoff, retirement, lore graduation |
| C | `src/census.py` + `data/arcs/civilians.json` + tests — registry, appearance recording API, follow-up scheduler, returning-caller picks, name sustainability rules |
| D | Dream Court clerk (`census.clerk_pass`) + tests — {feeling, tool, verdict} capture contract (LLM call is injected/mockable), follow-up copy |
| E | Desk/orchestrator wiring + tests — CONTINUITY DESK block, returning-name flow into the switchboard mint, arc-beat flags on beats |
| F | bootstrap (`scripts/migrate_arcs.py`, idempotent, gate `data/arcs/ENABLED`) + integration — main loop |

Gate-off = byte-identical. Verification workflow runs TOMORROW before any
ENABLED flip.
