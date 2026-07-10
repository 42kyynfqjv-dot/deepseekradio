# Big Swings Brief — Four Tracks (2026-07-10)

Owner-approved slate: (A) narrative arcs + town census, (B) world spine,
(C) music + Halfway Hot 10, (D) special-events engine. This file is the
shared constraint contract for every design panel; violating a hard
constraint fails a design.

## Hard constraints (all tracks — proven tonight, non-negotiable)

- **Live air is sacred.** The station broadcasts 24/7. Everything lands
  feature-gated + incrementally; instant fallback; never a big-bang on air.
- **Code owns facts; the LLM authors.** Any new fact surface gets a guard or
  feeds an existing one (scoreguard/nameguard/switchboard/continuity/
  civicguard + the assignment desk). Prompt blocks are authoritative
  (SCOREBOARD register). Deterministic seeds; derive-don't-store where
  possible; aired facts are canon forever.
- **Box fit:** 2 vCPU/4GB shared with Kokoro. Engines stdlib-only, atomic
  tmp+replace+.bak sidecars, fast-path ticks ~1ms, chunked catch-up.
  Anything heavy (e.g. music generation) happens OFF-box; the box only plays
  files.
- **Canon:** station/bible.md, station/wending-bible.md, the league in
  season.py, personas/. The ~40 sponsors are Halfway's businesses. G/PG.
- Design docs follow the established discipline: exec summary, concrete JSON
  schemas, module signatures, prompt-block and guard contracts, build order
  of parallelizable pure components w/ per-component tests, calibration where
  applicable, migration/bootstrap, risk register. The hockey/statehouse docs
  in docs/designs/ are the pattern.

## Track A — Narrative arcs + the town census (one design)

Multi-week, code-owned STORY ARCS: each arc a state machine (premise, cast,
beats scheduled across specific shows/days, escalation stages, a payoff
date), drip-fed through the assignment desk so writers author around
assigned beats; arcs age, resolve, and enter lore. Boundary with existing
lore (running_jokes/callbacks) must be explicit. THE CENSUS: persistent
civilians — every desk-minted caller becomes a registry record (id, name →
deterministic gender/voice, neighborhood from Halfway canon, running
problem, appearance history, last outcome) with scheduled FOLLOW-UPS
("Maureen, three weeks later: how's the sock ceasefire holding?"); Dream
Court becomes serialized therapy (bizarre premises, real closure, real
tools — the owner's explicit register). Civilians appear in arcs. Guard
question to answer: how are an arc's asserted facts protected from
contradiction (extend continuity/nameguard vs. a facts table per arc)?
Storage: arcs.json + civilians.json sidecars. Cross-show beats must respect
each show's register (the anti-conspiracy guard etc.).

## Track B — The world spine (causal cross-sim events)

One world: weather (real Open-Meteo), the league, the statehouse, the city/
sponsors stop being parallel and start being CAUSAL. Design an append-only,
day-keyed WORLD EVENT BUS (world-events.json) with typed events produced by
each engine (snowstorm, quorum failure, game postponed?, bill passed, trade,
cup run, goose sighting, sponsor-index move) and consumed as GUARD-VERIFIED
facts by other engines' sheets and by show prompts. PHASING IS THE DESIGN:
phase 1 = read-only texture (shows/sheets reference other sims' real facts —
low risk, high feel); phase 2 = causal effects with an honest analysis of
which are safe (approval reacting to a Cup run: easy) vs. which touch
immutable state (weather-postponed games vs. the frozen schedule + VERIFIED
hash: hard — solve or defer explicitly). Collision rules when two engines
would contradict. No engine may import another; the bus is the only surface.

## Track C — Music + the Halfway Hot 10

RESEARCH FIRST (this track starts with a feasibility verdict): open
music-generation models (MusicGen variants, Stable Audio Open, YuE,
ACE-Step, others) — output quality for 30-90s songs w/ vocals vs
instrumental, generation cost on consumer hardware (CPU-only? single GPU?),
license terms of models AND outputs (must be safe for a public monetized
stream), and one-time-batch vs ongoing generation economics. THEN design:
a fictional local-music catalog (artists as city canon — genres, names
disjoint from existing banks, the one-note jazz musician finally records),
an OFF-box generation pipeline producing a WAV catalog the box just plays,
a code-owned HALFWAY HOT 10 chart sim (weekly movement, seeded, debuts/
droppers, narratable like standings), and airplay integration (overnight
music blocks? a chart show? upgraded beds) that respects the talk-first
format. If research says quality isn't there, say so and design the best
degraded version (e.g. instrumental-only beds + fictional chart narration).

## Track D — Special-events engine

Generalize the proven takeover machinery (schedule.yaml day-gated blocks +
schedule.js TAKEOVERS + run_center_ice's pattern) into an EVENTS framework:
an events registry (data-driven: date/window/cast/engine hooks/promo copy)
that (1) auto-derives events from sim state — playoff series nights from the
league bracket, Election Night 2026-11-03 from civics, a draft-day special,
trade-deadline show, blizzard emergency coverage from real weather; (2)
feeds the website schedule dynamically (takeovers from a published feed
rather than hardcoded JS); (3) auto-promos upcoming events through the
imaging/sweeper system days ahead. Must reuse, not replace, what exists.
