# Wending Statehouse Engine — FINAL SYNTHESIZED DESIGN

Synthesis of the two-design panel (2026-07-10). **Backbone:
`statehouse-mirror.md`** — won the civic-fidelity adversary review 47–39
(ironically beating the fidelity-lens design on procedure: civic baked the
wrong passage denominator into its own flagship example, violated the closed
7-party canon with an invented "independent" bucket, and scheduled its worked
sine-die example onto a hockey night). Mirror is adopted verbatim except the
deltas below. Note for the record: the implementability judge in this panel
returned degenerate output and was discarded; the implementability pass below
is the synthesizer's own.

## Adopted verbatim from statehouse-mirror.md

- civics.json as the season.json-shaped spine (seat aggregates, approval +
  streak, phase, TRACKED one-thread pointer, aired ledger); sidecars per
  General Assembly under `data/statehouse/`; derive-don't-store — whip counts
  are pure functions of member leans + per-bill seeds, never stored.
- The closed 7-party seat table (6 seat-holding + seatless OIC acting via
  Notices of Deficiency), summing exactly to 51 House / 9 Senate; hung House
  by construction (no bloc reaches 26 without Roundabout or Goose).
- Daily `sim_day` mirroring the hockey tick: ~1 ms fast path, self-healing
  per-bill seeds, 45-day catch-up chunks, Wed/Sat 18:00 hockey adjournment,
  snow-quorum from the real Open-Meteo feed (append-only snow ledger), ONE
  decisive tracked event per day (the one-thread rule in code), air-gated GA
  rollover (born with the hockey rollover fix).
- Election engine: seeded precinct-returns generator (171 precincts — inside
  the small-state grounding band; pharmacy lot reports first, Halfway dumps
  late) + monotonic `reveal(returns, cursor)` shared by booth, desk, and site;
  waves=periods, recount=overtime re-narrated slower (flip ≈ 1/10),
  rain-outs, approval-as-the-streak. Full-chamber 2-year elections (real
  small-state practice); **incumbent carryover** via `seat_new_assembly` so
  re-elected members keep their identity across Assemblies. First takeover:
  **2026-11-03**.
- `civicguard` (scoreguard-mirrored, replace-never-cut) catching: invented
  tallies, margins, committee outcomes, phantom bill numbers/people,
  premature race calls, pre-air spoilers. Per-sheet self-guard CI.
- MERGED as a terminal-but-not-dead stage (the Committee on Merging: never
  advances, never dies) — canon as a state machine.
- Bootstrap from government.html canon with an empty-canon-diff gate; GA 1 in
  "regular-extended" session (the sine-die resolution is itself pending in
  Merging — permanently moot, which is the joke and the mechanism); 180-day
  retro docket replay is free since nothing has aired.
- ENABLED + VERIFIED gate; overnight shadow dry-run before the first
  government show airs; fallback `rm ENABLED` → shows keep their current
  pure-canon color.

## Deltas (judge-directed grafts and fixes)

1. **Attendance is real** (graft civic's `attend` scalar): every member gets
   `attend ∈ [0.88, 0.98]`; daily seeded presence draws thin the chamber, so
   whip counts gain an **absent** bucket and quorum can fail from a bad flu
   week or a feud, not only snow. Invariant: yea+nay+undecided+absent ≡
   chamber size, enforced by construction and tested.
2. **Passage thresholds are majority of PRESENT-AND-VOTING** for ordinary
   bills (the real rule); the override class needs **two-thirds of members
   elected (34/51 House, 6/9 Senate)** — corrected 2026-07-09; an earlier
   draft misquoted 26/51 and the votes builder caught it. The guard learns
   both denominators.
3. **Introduction clustering**: bill introductions concentrate in the first
   ~3 weeks of a session with a crossover-deadline cutoff; late introductions
   only by leadership exception (seeded, rare, narratable when they happen).
4. **`goose_price()` specified**: the Goose bloc is off the Zipper axis; its
   votes resolve by seeded draw ONLY when a bill carries a goose-relevant tag
   (lot paving, waterfowl, oaths); otherwise the bloc abstains (counted in
   absent/abstain, never invented). Its price list is enumerable canon —
   civicguard can therefore verify any claimed goose deal.
5. **Schema placeholder dates keep off hockey nights** (mirror's moot
   sine-die example sat on a Saturday; moot or not, no date in the schema
   examples lands on Wed/Sat).

## Implementability pass (synthesizer's own, replacing the failed judge)

Six leaf modules (members, docket, votes, calendar, elections, sheets +
civicguard) are pure functions against civics.json/sidecar schemas — the same
component discipline that worked for the hockey engine tonight; per-bill and
per-precinct seeds make every module golden-testable; nothing here exceeds
the hockey engine's proven cost envelope on the box (the docket is ~200
bills/session vs 1,312 games/season). The election reveal clock is the only
latency-sensitive surface and it is a pure function over a pre-generated
returns file. No blocker found.

## Sequencing

Implementation is **Gate-2-era work**: nothing statehouse airs before the
government-show sheets land, and the first Election Night takeover is
2026-11-03 — months of runway. Build after the hockey cutover settles
(target: components this weekend, guard + sheets next week, shadow before
the first data-driven government beat). The hockey engine's verification
harness (calibration pytest, shadow report, canon-diff) is reused wholesale.
