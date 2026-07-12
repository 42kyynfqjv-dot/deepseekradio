# Town Texture + Event Engines — frozen build contract (2026-07-12)

Owner-approved slate: time/temp drops, traffic on the 8s, the Town Desk
(birthdays/calendar/lost pets), contests, sponsor-owner guests, and the four
event ENGINES the registry gates dark (election night, blizzard, trade
deadline, draft night). Music explicitly skipped.

House rules (hard, all rows): code owns facts, the LLM authors; stdlib-only
leaf modules; orchestrator/live-air wiring belongs to INTEGRATION (do not
edit src/orchestrator.py, schedule.yaml, or deploy/*); atomic tmp+replace
for any state file, under data/town/ or the module's noted home; derive
don't store; seeded determinism (`random.Random(f"...")`, never bare
random/Date.now); tests in the house style (plain python3, PASS/FAIL
counter, exit code, tmp cwd) — see tests/test_sfx.py, tests/test_podcast.py.
Every fictional name invented by a row must be checked against
nameguard._WORLD_TOKENS/_WORLD_PHRASES (no real brands/people, even as
jokes). All numbers a block hands the LLM must be verifiable by the caller —
follow the briefs.desk_sheet/desk_verify pattern (src/league/briefs.py) when
a row's output includes numbers the LLM will speak.

## Row 1 — src/towndesk.py + tests/test_towndesk.py
The small-town service desk. Public API (FROZEN):
- `time_temp(spoken_time: str, forecast_text: str | None, seed: str) -> str`
  — "It's about ten past four on The Frequency — 71 in Halfway." Parses the
  first °F number from spots._real_forecast()-style text (pass-through arg,
  NO network); temp omitted gracefully when unparseable. 4+ seeded phrasing
  templates.
- `birthdays(census: dict, date: str, n: int = 2) -> list[dict]` — residents
  whose STABLE derived birthday (md5(name) -> month/day, uniform, no age)
  falls on `date`; census shape per src/census.py mint().
- `calendar_lines(date: str, n: int = 2) -> list[str]` — seeded picks from a
  curated bank of ~24 recurring Halfway happenings (library book sale, bridge
  appreciation walk, grange pancake supper...), phrased for air.
- `lost_pets(date: str) -> list[str]` — state at data/town/pets.json: 0-2
  seeded lost pets/day (species/name/landmark/quirk banks), and yesterday's
  unfound pets resolve today ("Chester has been found") with seeded chance;
  idempotent per date.
- `town_block(date, census, forecast_text) -> str` — the authoritative TOWN
  DESK prompt block bundling the above for the morning/midday shows, plus
  `wire_lines(...)` -> list[str] of code-built one-liners for news bulletins.

## Row 2 — src/traffic.py + tests/test_traffic.py
Traffic on the 8s. Fictional geography ONLY (the bridge, the roundabout at
Fifth and Pine, Mill Road, Route 9, the impound lot exit — bank of ~12
locations, ~14 causes: goose crossing, plow staging, a mattress in the
eastbound lane...). Public API (FROZEN):
- `incidents(date: str, slot: str) -> list[dict]` — slot in ("am","pm"); 2-4
  seeded incidents with onset/clear minutes derived from (date, slot), so a
  6:40 report and a 7:20 report agree and incidents RESOLVE across the rush.
- `traffic_sheet(date: str, hour: int) -> dict` — the active incidents at
  `hour` with delay minutes (small ints).
- `wire_line(sheet: dict, seed: str) -> str` — code-BUILT bulletin copy with
  personality (guard-true by construction), reporter signed: the reporter
  persona is a module constant `REPORTER = "Merv Plunkett"` (invented).
- `block(sheet: dict) -> str` — authoritative prompt block for drive shows.
- `verify(texts: list[str], sheet: dict) -> bool` — desk_verify-style: every
  small number in an authored read must be a sheet number.

## Row 3 — src/contests.py + tests/test_contests.py
Giveaways. State data/town/contests.json. Public API (FROZEN):
- `todays(date: str, sponsors: list[tuple[str,str]]) -> list[dict]` — 1-2
  seeded contests/day: {"show": daypart_id, "prize": str, "n": int} — prize
  bank mixes station prizes (Center Ice tickets, a Frequency mug that hums)
  with sponsor-tied prizes built from the (name, gag) roster tuples.
- `directive(contest: dict, winner_name: str) -> str` — authoritative
  CONTEST prompt block: announce once, the {n}th caller wins, the winner is
  {winner_name} (desk-assigned), brief celebration, no re-runs this show.
- `record_winner(date, show, prize, winner) -> None` and
  `uncollected(date) -> list[str]` — follow-up lines ("June's mattress
  remains unclaimed") for the Town Desk to feed on later days; winners
  auto-age to collected after a seeded 2-5 days.

## Row 4 — src/statehouse/returns.py + tests/test_statehouse_returns.py
Election Night's returns CLOCK (the engine core; run_election_night itself
is integration's). READ FIRST: src/statehouse/elections.py (generate_cycle,
its reveal machinery), sheets.py election_sheet (cursor/revealed contract),
civicguard.enforce_civic. Public API (FROZEN):
- `build_night(el: dict, window_secs: int, seed: str) -> dict` — assigns
  every precinct a drop offset across the window (early trickle, mid flood,
  stragglers), returns the night plan (pure; el from generate_cycle).
- `reveal_at(plan: dict, el: dict, cursor: int) -> dict` — the revealed dict
  election_sheet expects, monotonic in cursor (reuse elections.py's own
  reveal if it fits; never regress a tally).
- `beat_plan(air_minutes: int) -> list[dict]` — beat descriptors (open /
  board / analyst / call-watch / the-call / wrap) with target cursors,
  matching the registry fragment's segments.
- `facts_at(plan, el, cursor, tracked_id) -> dict` — whatever
  civicguard.enforce_civic needs to hold a beat to the revealed truth.

## Row 5 — src/blizzard.py + tests/test_blizzard.py
Storm Watch core (soft takeover; run_blizzard is integration's). Public API
(FROZEN):
- `is_storm(forecast_text: str | None) -> bool` — snow/blizzard/ice tells in
  a forecast string; None -> False. NO network.
- `storm_sheet(date: str, forecast_text: str) -> dict` — seeded storm facts:
  inches so-far/expected (small ints), wind, plow location rotation (the
  plow bank: where it is, where it is not).
- `closings(date: str, beat: int) -> list[str]` — CUMULATIVE seeded reveals
  from a ~30-entry closings bank (schools, the grange, the impound lot, the
  book sale); beat k's list contains beat k-1's (closings never un-close).
- `block(sheet, closings_list) -> str` + `verify(texts, sheet) -> bool` —
  numbers-verifiable, desk pattern.

## Row 6 — src/league/deadline.py + src/league/draftday.py + tests (one file
tests/test_league_events.py)
READ FIRST: engine.py Gate-2 block (transactions-s{n}.json shape,
news-lines.json), economy.py, players.py mint pools, season.py LEAGUE/_ALL.
- deadline: `day_plan(transactions: list, date: str, window_secs: int,
  seed: str) -> dict` — the date's trades assigned reveal offsets across the
  window; `reveal_at(plan, cursor) -> list` monotonic; `sheet(revealed,
  players, names) -> str` (desk-style, team keys resolved to names);
  `verify(texts, revealed, names) -> bool`. If the date has NO trades, the
  plan still works ("the board is quiet" is a legitimate deadline show).
- draftday: fictional entry draft, OFFSEASON only: `draft_class(season: int)
  -> list` — 32 seeded prospects (players.py name pools, ages 18-19,
  positions balanced) with scouting one-liners; `order(standings) -> list`
  reverse standings; `picks_plan(...)/reveal_at(...)/sheet(...)/verify(...)`
  mirroring deadline. Prospects are NOT added to players-s{n}.json (the
  rollover owns rosters); this is broadcast canon only, recorded to
  data/league/draft-s{n}.json so the booth never contradicts it later.

## Return contract (every row)
StructuredOutput: {summary, files, test_tail}. Tests green via plain
`python3 tests/<file>.py`. Report friction honestly in summary — never
improvise around a frozen signature.
