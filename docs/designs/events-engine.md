# Special-Events Engine — DESIGN (Track D)

Generalize the proven Center Ice takeover machinery into a **data-driven events
framework**: one registry of special broadcasts (playoff series nights, Election
Night, draft day, the trade deadline, blizzard emergency coverage) that
auto-derives its dates from sim state, splices itself into the live daypart clock
**and** the website schedule with no hand-editing, and auto-promotes itself
through the sweeper pool days ahead. It **reuses, never replaces** the three
mechanisms that already work: `schedule.yaml` day-gated blocks, `run_center_ice`'s
engine pattern, and `schedule.js`'s `TAKEOVERS` splice. Center Ice keeps
broadcasting exactly as it does tonight — the framework is additive and, with no
registry file present, is a byte-for-byte no-op.

This doc is the schema freeze. Component builders implement the shapes here
exactly; schema friction gets reported, never improvised around (the hockey/
statehouse discipline).

## Exec summary

Three facts about the current machinery drive the whole design:

1. **`schedule.yaml` gates on weekday, not date.** `center_ice` has
   `days: [Wednesday, Saturday]`; `_current_daypart` matches
   `now.strftime("%A") in days`. There is no way to say "this Thursday only." A
   playoff Game 7 that slips to a Thursday, or Election Night on a specific
   2026-11-03, cannot be expressed in the current schema.
2. **The orchestrator loads `schedule.yaml` once, at startup** (`main()`, before
   the `while True`). Editing the file changes nothing until a restart. So a
   date-specific takeover cannot come from editing that file.
3. **Dispatch to a special engine is a hardcoded id branch** —
   `if daypart.get("id") == "center_ice": return run_center_ice(...)`.

The engine solves all three with one pure composition step run at the top of every
main-loop pass: `events.effective_schedule(base, date)` returns the everyday
`schedule.yaml` dayparts **with today's registry-derived event blocks prepended**
(prepended = they win, per the existing "day-gated blocks FIRST" rule). Event
blocks carry a literal `date:` field; `_current_daypart` learns one new clause
(date beats weekday). Dispatch becomes a small table keyed on `dp["engine"]`. The
same active-event list publishes to `/data/takeovers.json`, which `schedule.js`
fetches (no-store) and merges into `TAKEOVERS` — so new events reach the website
with zero JS edits and zero cache-bump. Promo lines flow into the reserve bumper
pool days ahead via the existing `make_imaging.py` render path.

Everything hangs off pure functions with fixture tests; the orchestrator glue is
~40 lines of additive diff, integrated incrementally against frozen schemas.

## Hard-constraint compliance

| Constraint | How this design meets it |
|---|---|
| Live air is sacred | No registry file ⇒ overlay is identity ⇒ schedule.yaml unchanged. Every deriver is exception-isolated (`try/except`, mirrors the statehouse tick); a throwing deriver drops its events, never the loop. New engines ship dark behind a per-event gate. |
| Code owns facts; LLM authors | Every new fact surface feeds an existing guard or a new one built to the same contract. Center Ice → scoreguard/nameguard (unchanged). Election Night → a new **civicguard** whose fact source is `elections.reveal(el, cursor)` — the reveal clock IS the authority, exactly as the scoreboard is. |
| Box fit | Overlay is a stdlib in-memory dict merge, memoized on `(date, registry-mtime, sidecar-mtimes, gate-mtimes)` — recomputed only on change, ~1 ms otherwise. Gate stats are in the key, so arming/clearing a gate re-resolves on the next pass. Derivers read already-published sidecars (`playoffs-s{n}.json`, `calendar-ga{n}.json`, the cached weather feed); no new heavy work. Publisher uses atomic tmp+replace, mirroring `season.export`. |
| Canon / G-PG | Promo copy is curated per event in the register (same PG register as `STATIC_SWEEPERS`); LLM promo lines pass the same imaging brief. |
| Design discipline | Concrete JSON schemas, module signatures, guard contracts, parallel pure-component build order with per-component tests, migration, risks — below. |

## The events registry

One human-authored file, `events/registry.yaml` (stdlib `yaml`, read once and
cached like `config.yaml`). Each record is either **literal-dated** (`date:` /
`dates:`) or **derived** (`deriver:` names a pure function that yields ISO dates
from sim state). A record's `show` block is a *daypart fragment* in exactly the
`schedule.yaml` vocabulary — the overlay copies it verbatim into the daypart dict,
so anything a schedule block can say, an event can say.

```yaml
# events/registry.yaml  — schema: 1
schema: 1
events:
  - id: playoff_night              # daypart id when active (stable per engine)
    engine: center_ice             # dispatch key (see ENGINES table)
    deriver: playoff_nights        # pure fn: (ctx) -> [{"date","meta"}...]
    gate: "data/league/ECON-ENABLED"   # path that must exist to arm; null = always
    window: ["20:00", "23:00"]     # may be overridden per-derived-date via meta
    priority: 50                   # higher wins if two events claim one window
    show:                          # a schedule.yaml daypart fragment, verbatim
      show: "Center Ice — Playoffs"
      cast: [bucky, sal]
      news: false
      parts_per_beat: 2
      lines_per_beat: 22
      ad_cadence: structural
      energy: "playoff hockey; every shift is the season"
      segments: [ ... ]            # optional; engine may build its own
    site:                          # what the website takeover card shows
      name: "Center Ice — Playoffs"
      hook: "Win or go home. Live from {arena}."   # {..} filled from meta
      who: "BUCKY · SAL"
    promo:
      lead_days: 4                 # start airing promos this many days ahead
      copy:                        # curated PG lines; {..} filled from meta
        - "Center Ice, {round}, Game {game}: {away} at {home}. Live {weekday} night on The Frequency."
        - "The run for the Boreal Lantern continues. Center Ice, {weekday}, only here."

  - id: election_night
    engine: election_night
    dates: ["2026-11-03"]          # literal; also emitted by the election deriver
    gate: "data/statehouse/ELECTION-ENABLED"
    window: ["19:00", "01:00"]     # pre-empts Culture Vulture + Night Shift
    priority: 90
    show:
      show: "Election Night"
      cast: [vivian, cosima]       # the desk anchors; guest analysts from pool
      news: false                  # you don't cut away from a live count
      parts_per_beat: 2
      lines_per_beat: 20
      energy: "live returns desk; AP-style calls, precinct by precinct"
    site: { name: "Election Night", hook: "Live returns from all 171 precincts.", who: "THE RETURNS DESK" }
    promo: { lead_days: 7, copy: ["Wending votes. Live returns Tuesday night, all 171 precincts, on The Frequency."] }

  - id: blizzard
    engine: blizzard
    deriver: blizzard_days         # real weather; same-day only, no promo lead
    gate: null
    window: ["06:00", "10:00"]     # rides the Morning Scramble slot
    priority: 40
    show: { show: "Storm Watch", cast: [wesley], news: true, energy: "calm emergency service; closings, the plow, the goose" }
    site: { name: "Storm Watch", hook: "Halfway digs out. Closings and the plow, live.", who: "WESLEY" }
    promo: { lead_days: 0, copy: [] }
```

**Record fields (frozen):**

- `id` (str) — becomes the daypart `id`. Load-bearing: the orchestrator keys
  `opened`/`handed_off`/`tail` state on `id:date`, so an event's id must be stable
  across the derived dates it fires on (all playoff nights share `playoff_night`;
  Center Ice's own tail/handoff logic is unaffected).
- `engine` (str) — dispatch key into `ENGINES` (below). `center_ice` reuses the
  existing `run_center_ice` untouched.
- `date` / `dates` / `deriver` — exactly one dating mechanism. `deriver` names a
  key in the `DERIVERS` registry.
- `gate` (path|null) — event is inert unless the path exists (the dark-ship
  lever, mirroring `data/league/ENABLED`).
- `window`, `priority`, `show`, `site`, `promo` — as annotated.
- `meta` (per derived date) — the deriver attaches a dict (`round`, `game`,
  `home`, `away`, `arena`, `weekday`, …) that fills `{...}` templates in `site`
  and `promo`, and may override `window`.

## Auto-derivation contracts

Every deriver is a **pure stdlib function** `(ctx) -> list[DerivedDate]` where
`ctx` is a read-only snapshot the engine assembles once per pass and
`DerivedDate = {"date": "YYYY-MM-DD", "window"?: [...], "meta": {...}}`. Derivers
**import nothing from the orchestrator**; they read sidecars the sims already
publish. `ctx` carries: `today` (ISO), `horizon` (today + max lead_days), the
loaded `season.json`/bracket/calendar/weather sidecars (or `None` if absent), and
`tracked` team codes.

```python
# events/derivers.py  — leaf module, stdlib only, no orchestrator import
def playoff_nights(ctx) -> list[dict]
def election_nights(ctx) -> list[dict]
def draft_day(ctx) -> list[dict]
def trade_deadline(ctx) -> list[dict]
def blizzard_days(ctx) -> list[dict]

DERIVERS = {"playoff_nights": playoff_nights, ...}
```

**1. Playoff series nights (`playoff_nights`).** Reads
`data/league/playoffs-s{n}.json` (the bracket) via the shape `playoffs.py`
persists. For each date in `[today, horizon]` it calls the *pure*
`playoffs.schedule_series(copy(bracket), date, tracked)` against a **deep copy**
(never the real `_last_played` ledger — that mutation belongs to the live tick,
not a look-ahead), emitting a date for any slate row whose `{home, away}`
intersects `tracked`. Meta = `{round, game, home, away, arena, series: [h_wins,
a_wins]}`. `schedule_series` already pins tracked series to Wed/Sat with a ±1
slip, so most emitted dates coincide with the static `center_ice` block (the
overlay dedupes — see below); the *new* value is the slip nights (Tue/Thu/Fri/Sun)
and elimination/Game-7 nights the promo system can name. The bracket is the
single source; no playoff schedule is stored in the registry.

**2. Election Night (`election_nights`).** Reads `calendar-ga{n}.json`
(`calendar.build_calendar`), returns `[{"date": cal["election"]["date"], "meta":
{"cycle": cal["election"]["cycle"], "races": cal["election"]["races"]}}]` when
`date_kind == "election"`. The literal `dates: ["2026-11-03"]` is
belt-and-suspenders (fires even if the statehouse sidecar is missing); the deriver
generalizes to every future cycle (`_election_day(year)`) — 2028, 2030 need no
edit. Canvass day (election+1) can be a second, lower-priority derived event.

**3. Draft day (`draft_day`) & 4. Trade deadline (`trade_deadline`).** Fixed
offsets into the league calendar phase (`league.calendar.phase` → `offseason`
draft window; a deadline date the economy calendar exposes). Both emit a single
date with meta naming the tracked teams' picks/needs, both gated behind
`ECON-ENABLED` (dark until Gate 2) — the simplest derivers, proof that "add an
event = add a registry record + a ~10-line pure deriver."

**5. Blizzard mode (`blizzard_days`).** Reads the **same cached Open-Meteo feed**
the statehouse snow-quorum uses (`calendar.is_snowfall(weather)`), returns
`[{"date": today}]` on a snow day. **Uniquely same-day**: weather isn't known 4
days out, so `lead_days: 0` and no promo — `promo.lead_days: 0` is how a record
declares itself reactive vs. look-ahead. Blizzard also demonstrates a *soft*
takeover: it rides an existing slot (Morning Scramble) with a different
cast/energy rather than claiming a fresh window.

## From registry to daypart — solving "loaded once at startup"

The orchestrator's `main()` loads `schedule.yaml` once and never again. The honest
fix is **not** to reload the file (it never changes) but to *compose* the live
schedule from two inputs each pass:

```python
# events/overlay.py — pure, stdlib only
def effective_schedule(base: dict, ctx) -> dict:
    """base = the parsed schedule.yaml. Returns a NEW schedule dict whose
    'dayparts' list is [today's active event blocks] + base['dayparts'].
    Event blocks are date-gated and prepended, so they win their window on
    their date exactly as day-gated blocks win theirs (the existing rule).
    Pure: same inputs -> identical output; memoized on
    (date, registry_mtime, sidecar_mtimes, gate_stats), where gate_stats is
    ((path, st_mtime-or-None) for every gate named in the registry) — so
    creating OR clearing a gate file changes the key and the overlay
    re-resolves on the very next pass (arm/disarm within one pass, the same
    instant-fallback guarantee the league engine has)."""

def active_events(ctx) -> list[dict]:
    """Resolve every registry record against ctx.today: literal dates that
    equal today, plus every deriver's emitted dates that equal today, each
    passing its gate. Returns [{"id","engine","date","window","priority",
    "show","site","promo","meta"}...], highest priority first, one winner
    per (window-overlap) via priority then id."""
```

An **event block** is the record's `show` fragment plus
`{"id", "engine", "window", "date": today, "_event": True, "_meta": meta}`. It is a
normal daypart dict with one new key: `date`.

`main()` changes in **two** places — both the top-of-loop selection **and** the
wait-condition at the bottom must move off the base `schedule` onto the per-pass
`eff`, or the wait loop busy-spins on event nights:

```python
schedule = _load("schedule.yaml")          # base, still loaded once
...
while True:
    ctx = events.build_ctx(clock.air_now())         # cheap snapshot
    eff = events.effective_schedule(schedule, ctx)  # memoized ~1ms
    dp  = _current_daypart(eff, clock.air_now())
    ...
    run_show(dp, config, eff, live=args.live)   # eff, not schedule, so
                                                # _next_daypart names events
    ...
    # wait until the buffer needs more, or the AIR daypart changes.
    # The base schedule NEVER contains event blocks, so the old
    #   while _current_daypart(schedule, ...) is dp and buffer...:
    # is instantly False on an event night (dp came from eff, a different
    # list) -> the loop never sleeps -> busy-loop on the 2-vCPU box.
    # Fix: recompute eff each pass (memoized ~1ms) and compare by (id, date),
    # not object identity.
    while True:
        eff = events.effective_schedule(schedule, events.build_ctx(clock.air_now()))
        cur = _current_daypart(eff, clock.air_now())
        if not (cur.get("id") == dp.get("id")
                and cur.get("date") == dp.get("date")
                and buffer.buffered_seconds()
                    > config["generation"]["buffer_target_minutes"] * 60 * 0.5):
            break
        time.sleep(60)
```

Comparing `(id, date)` is correct whether or not the memo hands back the same list
object: inside one `(date, mtimes, gates)` key the ids match and the loop sleeps;
when the date rolls or a registry/gate mtime changes, `eff` regenerates, `(id,
date)` differs, and the loop exits to re-plan. For non-event dayparts both
`date`s are `None`, collapsing to today's plain id match.

`_current_daypart` gains **one** backward-compatible clause, and it must be
**wrap-aware**. The naive rule "`date == today`" is a FATAL bug for a wrapping
window: Election Night `date: 2026-11-03`, `window: ["19:00","01:00"]` would stop
matching at 00:00 on 11-04 (`today` rolled to 11-04) and yank the broadcast an
hour early. The rule instead is: **a wrapping window belongs to the date it
STARTED on** — match `date == today` for the pre-midnight half, `date ==
yesterday` for the post-midnight tail:

```python
from datetime import timedelta   # (already imported locally in _next_daypart)
for dp in schedule["dayparts"]:
    days = dp.get("days")
    if days and now.strftime("%A") not in days:
        continue
    start = dtime.fromisoformat(dp["window"][0])
    end   = dtime.fromisoformat(dp["window"][1])
    d = dp.get("date")                        # NEW: event blocks only
    if d is not None:
        today = now.strftime("%Y-%m-%d")
        if start <= end:                      # same-day window
            if d != today:
                continue
        else:                                 # wraps past midnight
            yest = (now.date() - timedelta(days=1)).isoformat()
            pre  = now.time() >= start and d == today   # this evening
            post = now.time() <  end   and d == yest    # the small hours
            if not (pre or post):
                continue
    # ── window match below is UNCHANGED (start<=end vs. wrap branch) ──
    if start <= end:
        if start <= now.time() < end:
            return dp
    else:
        if now.time() >= start or now.time() < end:
            return dp
```

At 00:00 on 11-04 the block matches via `post` (`now < 01:00` **and**
`2026-11-03 == yesterday`); at 19:30 on 11-03 via `pre`; at 01:30 on 11-04 both
`pre` and `post` are false, so it has correctly signed off. Non-wrapping dated
blocks still require `date == today`. Blocks without `date` behave exactly as
today. Because event blocks are prepended and date-gated, on any date with no
active event `eff` is `schedule` with nothing prepended → identical behavior. The
`center_ice` weekday block still lives in `schedule.yaml` untouched; a playoff
deriver that emits *the same* Wed/Sat date produces a block the overlay **dedupes
against** the static one (same `engine` + overlapping window on the same date ⇒
keep the higher-priority/event one, drop the duplicate) so the game never
double-books.

**Dispatch** stops being a hardcoded id branch and becomes a table:

```python
ENGINES = {
    "center_ice":     run_center_ice,       # UNCHANGED
    "election_night": run_election_night,   # new (Track D deliverable)
    "blizzard":       run_blizzard,         # new (thin: Wesley + closings sheet)
    "draft":          run_draft,            # new (thin)
    "trade_deadline": run_trade_deadline,   # new (thin)
}
def run_show(daypart, config, schedule, live):
    fn = ENGINES.get(daypart.get("engine"))
    if fn:
        return fn(daypart, config, schedule, live)
    ...                                     # the everyday path, unchanged
```

Keeping `run_center_ice` behind `engine: center_ice` (with the old
`id == "center_ice"` check retained as a fallback during migration) means the live
sports path is provably identical. `_next_daypart`/`_minutes_left` already operate
on whatever schedule dict they're handed, so passing `eff` instead of `schedule`
into `run_show` makes handoffs name event shows correctly with no further change.

## The site feed — dynamic takeovers

Today `schedule.js` hardcodes `F.TAKEOVERS` and the site only updates on a code
edit + a `?v=N` cache bump. We move the **data** out of the code and keep the
**logic** in place.

**Publisher.** `events.publish_takeovers(path="/var/www/bestairadio/data/takeovers.json")`
runs on the same cadence and atomicity as `season.export` (tmp+replace,
best-effort, exception-isolated). It emits every active-or-upcoming event within a
14-day horizon as a takeover row in the exact shape `F.TAKEOVERS` entries already
have — **except** keyed on **`date`** (ISO), not `days` (weekday):

```json
{ "schema": 1, "generated": 1730600000,
  "takeovers": [
    { "date": "2026-11-03", "start": 19, "end": 25,
      "name": "Election Night", "hook": "Live returns from all 171 precincts.",
      "who": "THE RETURNS DESK" },
    { "date": "2026-06-11", "start": 20, "end": 23,
      "name": "Center Ice — Playoffs", "hook": "Game 7. Live from the Ice Barn.",
      "who": "BUCKY · SAL" }
  ] }
```

`start`/`end` come from `window` (hours; `end>24` for past-midnight, matching the
existing `inWin` wrap logic). The **recurring** Wed/Sat Center Ice stays in
`F.TAKEOVERS` as today (weekday-keyed) — the feed *adds* date-specific pre-empts;
it doesn't replace the evergreen block.

**schedule.js diff.** Three functions read `t.days` (`activeTakeover`,
`effective`'s per-takeover guard, and indirectly `currentShow`); on a date-keyed
row `t.days` is `undefined` and `.indexOf`/`.map` **throws**, blanking the entire
schedule. So every `t.days` access is guarded and gains the date branch via one
helper. A takeover is live for `day` when
`t.days ? t.days.indexOf(day)!==-1 : t.date === F.todayISO()`:

```js
// station-time ISO date. NEVER new Date().toISOString(): that is UTC and, at
// 19:00-23:59 ET, already reports TOMORROW — mis-gating Election Night. en-CA
// renders YYYY-MM-DD; STATION_TZ matches parts()/stationDay() (the file's
// other helpers), so this stays on station time like everything else here.
F.todayISO = function () {
  return new Intl.DateTimeFormat("en-CA", {timeZone: STATION_TZ,
    year:"numeric", month:"2-digit", day:"2-digit"}).format(new Date());
};
function onDay(t, day){
  return t.days ? t.days.indexOf(day) !== -1 : t.date === F.todayISO();
}
// activeTakeover:  if (onDay(t, day) && F.inWin(h, t)) return t;
// effective guard: if (!onDay(t, day)) return;   // replaces t.days.indexOf===-1
```

`effective`'s splice already tolerates `end>24` wraps (its `segEnd`
pre-midnight extent), so a `19-25` Election Night row splices like any other;
only the `.days` guards needed the `onDay` swap. A tiny loader fetches the feed
and concatenates date-keyed rows into `TAKEOVERS`, dropping past ones so a stale
feed can't resurrect an event:

```js
F.loadTakeovers = function () {
  fetch("/data/takeovers.json", {cache:"no-store"}).then(r=>r.json())
   .then(j => { F.TAKEOVERS = F.TAKEOVERS.concat(
       (j.takeovers||[]).filter(t => t.date >= F.todayISO())); render(); })
   .catch(()=>{});   // feed down -> evergreen lineup still renders
};
```

**index.html render fix.** The grid badge at `render()` does
`s.days.map(d => d.slice(0,3)…)` — `undefined` on a date-keyed row →
`TypeError` → blank schedule (the same failure, in the render layer). The badge
branches on which key the row carries, showing the **date** for date-keyed
events:

```js
const badge = !s._takeover ? "" : `<span style="${BADGE}">${
    s.days ? s.days.map(d => d.slice(0,3).toUpperCase()).join(" · ")
           : new Intl.DateTimeFormat("en-US", {timeZone:"America/New_York",
               month:"short", day:"numeric"}).format(new Date(s.date+"T12:00"))
             .toUpperCase()}</span>`;   // weekday row -> "WED · SAT"; dated -> "NOV 3"
```

(`+"T12:00"` parses the ISO date at local noon so the rendered month/day never
slips across the viewer's timezone.)

**Cache-bust convention (honest).** `takeovers.json` is served **no-store**, like
`now.json`/`league.json` (Caddy serves JSON uncached; only static assets get the
4h Cloudflare cache). A *new event* needs **no `?v=N` bump** — it appears the
moment the publisher writes the file. `?v=N` on `schedule.js?v=N` bumps **only**
when the *code* changes (this one-time diff) — after that the mechanism is
code-frozen and all future events are pure data: the website gains events
without ever touching JS again.

## Auto-promo through the sweeper system

`make_imaging.py` already renders sweeper copy → Kokoro → ffmpeg → `bumper_id_*.wav`
in `/opt/kaos/reserve`, which the player pulls at show boundaries and droughts.
The events engine reuses that render path for **event-specific, time-boxed**
promos.

`events.render_promos(reserve=Path("/opt/kaos/reserve"))` runs on the box on the
spot-refresh cadence (the existing 30-min `last_spots` hook in `main`). For every
event whose `today` falls within `[event.date - lead_days, event.date)`:

1. Fill each `promo.copy` template from `meta` (`{round}`, `{game}`, `{home}`,
   `{weekday}`, …) — curated PG lines, same register as `STATIC_SWEEPERS`.
2. Render via the **same** `tts.synth_segment` + ffmpeg bed pipeline as
   `make_imaging.main`, into `promo_{event_id}_{date}_{i}.wav` (a distinct prefix
   so they're identifiable).
3. Write a sidecar `reserve/promos.json` listing each promo's `{file, event_id,
   expires: event.date}`. **The player prefers `promo_*` files in their lead
   window and deletes them once `expires` passes** — so a Game-7 promo can't air
   after Game 7, and a snowed-out event's promos self-purge. (Player change: one
   glob + one date check when choosing a reserve file; falls back to
   `bumper_id_*` exactly as now.)

Reactive events (`lead_days: 0`, blizzard) render **no** promo — there's no lead
time and a storm promo mid-storm is noise. LLM-authored variants are optional: the
same `chat()` call `make_imaging` uses can expand a curated line into two, passing
the identical brief so tone/PG hold. The curated `copy` is always rendered so the
promo pool is never empty even if the model is down (the `STATIC_SWEEPERS`
discipline).

**Idempotence.** `render_promos` runs every 30 min via the `last_spots` hook. Without
a check it would re-render (re-synth, re-run ffmpeg) the **same** lines every pass —
wasted CPU on the shared box, and a race against the player's `promo_*` glob mid-read.
Idempotence keys on `(event_id, date, i)` — already in the
`promo_{event_id}_{date}_{i}.wav` filename — tracked in `reserve/promos.json` itself
(no separate sidecar):

```python
def render_promos(reserve, active, sidecar="promos.json"):
    state = _load(reserve / sidecar)               # {"promos": []} if absent
    done  = {(p["event_id"], p["date"], p["i"]) for p in state["promos"]}
    for ev in _promotable(active, today):           # see cap, below
        for i, tmpl in enumerate(ev["promo"]["copy"]):
            key = (ev["id"], ev["date"], i)
            if key in done:
                continue                            # already rendered — skip, no re-synth
            line = tmpl.format(**ev["meta"])        # meta AS CAPTURED THIS FIRST RENDER
            # ...synth_segment + ffmpeg bed, write promo_{ev['id']}_{ev['date']}_{i}.wav...
            state["promos"].append({"file": ..., "event_id": ev["id"], "date": ev["date"],
                                     "i": i, "line": line, "expires": ev["date"]})
    _atomic_write(reserve / sidecar, state)         # tmp+replace, mirrors season.export
```

A promo, once rendered, is **never** re-rendered or re-filled from a later pass's
`meta`, even if the deriver's meta for that date changes underneath it (a bracket
reseed, a corrected arena) — the first-rendered line is locked in, matching the
brief's "aired facts are canon forever" rule. A wrong fact gets a new registry record
(new `id`), never a silent re-synth.

**Max-2-events cap.** Lead windows can overlap — a playoff slip night 4 days out and a
trade-deadline show 6 days out both "in window" the same evening. Unbounded promotion
would let `promo_*` outgrow `bumper_id_*` in the pool and uncap per-pass TTS cost.
`_promotable(active, today)` filters to open-window events (same `priority` then `id`
tie-break `active_events` already defines) and returns **at most the top 2**:

```python
def _promotable(active, today):
    inwin = [e for e in active
             if e["promo"]["lead_days"] > 0
             and _date(e["date"]) - timedelta(days=e["promo"]["lead_days"]) <= today < _date(e["date"])]
    inwin.sort(key=lambda e: (-e["priority"], e["id"]))
    return inwin[:2]
```

A 3rd+ event in-window simply waits for a slot (a promoted event's date arrives, or a
higher one expires). Idempotence means nothing already rendered is ever un-rendered
when an event drops out of the top-2; it just stops gaining *new* lines. Pool size is
bounded to at most `2 × len(copy)` event lines airing at once, regardless of how many
events the registry ever schedules concurrently.

## Guard & continuity interactions

Each engine sets the **right fact register** on its daypart before performing,
exactly as `run_center_ice` sets `dp["arc"] = "live sports broadcast"` to select
the sports register over the mundane/anti-conspiracy guard.

- **Center Ice (unchanged):** scoreguard (`enforce_scoreboard`) + nameguard
  (`enforce_names`) own factual truth; the reveal clock feeds `allow_pairs`.
  Nothing about this path changes.
- **Election Night — new civicguard.** The fact authority is
  `elections.reveal(el, cursor)` (cursor = seconds since `broadcast_anchor`), the
  precinct-level analogue of the hockey reveal clock. `run_election_night` builds a
  per-beat fact block from `reveal` (each race's `tally`, `status`, `precincts_out`)
  and runs an `enforce_civic` guard — built to the **G3 self-guard CI contract**:
  the sheet's own test renders it, builds its facts, runs the guard over synthetic
  booth lines quoting it, and requires **zero replacements**. Calls are
  monotone-safe by construction (the reveal docstring's algebra), so the booth can
  never "un-call" a race — the same property that makes the scorebug safe. The
  website's returns page and the booth both call `reveal` at the same cursor
  (shared-clock), so they never disagree, mirroring `air-anchor.json` for hockey.
- **Blizzard / draft / deadline (thin engines):** these are mostly the *everyday*
  performer path with a curated facts sheet (closings list; draft board; deadline
  trades) and the ordinary continuity guard. They set no special `arc`; they inherit
  scoreguard-free, nameguard-on behavior. Draft/deadline facts come from the league
  economy sidecars (guard-verified pairs), never invented by the LLM.
- **Continuity & handoff (unchanged).** Event dayparts flow through the same
  `_save_tail` / `_throw_beat` / `_next_daypart` machinery. Because the overlay
  feeds `eff` (with events) into `_next_daypart`, a handoff *from* Night Shift *to*
  Election Night, or *out of* Election Night at 1am, names the right show
  automatically. The `handed_off`/`opened` sentinels key on `id:date`, and event ids
  are stable per date, so restart-resume and "don't ramble past the sign-off" work
  unchanged.

## Build order — parallel pure components + tests

Each row is stdlib-only, pure where marked, and tested as plain
`python3 tests/<file>.py` (PASS/FAIL counter, exit code) in the repo fixture style.
Rows 1–5 are independent and parallelizable; row 6 is the incremental glue the main
loop owns.

| # | Component (new files) | Pure? | Test asserts |
|---|---|---|---|
| 1 | `events/registry.py` — load+validate `registry.yaml`, cache on mtime | yes | malformed record rejected; literal `date`/`dates` resolve; missing file ⇒ empty list (no-op) |
| 2 | `events/derivers.py` — the five derivers + `DERIVERS` | yes | vs fixtures: bracket→tracked slip-night dates (deep-copy, ledger untouched); election deriver→2026-11-03 & 2028; blizzard→snow-day only; gate absent ⇒ no emit |
| 3 | `events/overlay.py` — `active_events`, `effective_schedule` | yes | no active event ⇒ `eff == base`; event block prepended & date-gated; playoff Wed/Sat dedupes against static `center_ice`; priority breaks two-event window clash |
| 4 | `events/feed.py` — `publish_takeovers` (atomic) | mostly | feed shape matches `TAKEOVERS` row (date-keyed); horizon filter; tmp+replace; missing web dir ⇒ silent no-op |
| 5 | `events/promo.py` + `render_promos` | fn pure; render I/O | in-window selection; template fill from meta; `expires` sidecar; `lead_days:0` ⇒ no promo; idempotent — 2nd call on unchanged state renders nothing new; cap — 3 in-window events ⇒ only top-2 by priority promoted |
| 5b | `src/schedule_js.test` (node, existing pattern) | — | date-branch `activeTakeover`/`effective`; feed concat; feed-down ⇒ evergreen renders |
| 6 | orchestrator glue: `build_ctx`, in-loop `effective_schedule`, `_current_daypart` date clause, `ENGINES` table | glue | integration: Center Ice night byte-identical; a synthetic election-date pass selects `run_election_night` |
| 7 | `run_election_night` + `enforce_civic` + `tests/test_civicguard.py` | engine | G3 self-guard: zero replacements over synthetic lines; reveal monotonicity honored |

New engines (`run_election_night` first, the thin ones after) follow
`run_center_ice`'s exact structure: a `plan()` generator rolling reveal cursors on
the main thread, a prefetch pool writing dialogue for already-revealed facts, a
guard on every emitted line, and a `try/finally` that always lands the show.

## Migration — Center Ice keeps working, exactly

Staged, each stage independently shippable and reversible:

- **Stage 0 (no-op).** Land components 1–4 with **no** `registry.yaml` present.
  `effective_schedule` returns `base` unchanged; `active_events` is empty;
  `publish_takeovers` writes an empty feed; `schedule.js` concats nothing. The
  station is provably unchanged; `center_ice` stays a weekday block in
  `schedule.yaml`, dispatch still hits `run_center_ice` via the retained
  `id == "center_ice"` fallback.
- **Stage 1 (site-only).** Ship `registry.yaml` with `election_night` +
  `playoff_night`, publish `takeovers.json`, but **do not** wire the overlay into
  `main()` yet. The website shows upcoming events (read-only, zero air risk)
  while the on-air path stays 100% the old code — the "phase 1 = read-only
  texture" pattern from the Track B brief, applied here.
- **Stage 2 (on-air, gated).** Wire `effective_schedule` into `main()` and the
  `ENGINES` table. Playoff nights go live first — lowest risk, since a playoff
  Center Ice is the *same engine* on a *different date*. Election Night stays
  behind `ELECTION-ENABLED` (absent) so its engine never runs until soaked.
- **Stage 3 (Election Night).** Arm `ELECTION-ENABLED` only after
  `run_election_night` + `enforce_civic` pass the G3 self-guard CI and a shadow
  soak against a generated 2026 cycle. First live count: 2026-11-03.

At every stage, removing `registry.yaml` (or clearing a gate) instantly reverts to
the evergreen station — the same instant-fallback guarantee the league engine has.

## Risk register

1. **Overlay in the hot loop.** *Risk:* recomputing the schedule every pass adds
   latency or, worse, a deriver exception kills the loop. *Mitigation:* memoize on
   `(date, registry_mtime, sidecar_mtimes, gate_mtimes)` so steady-state is a dict
   lookup; gate mtimes are in the key so arming/clearing a gate re-resolves on the
   very next pass instead of waiting out a stale memo. Wrap the whole
   `build_ctx`/`effective_schedule` in `try/except` returning `base` on any failure
   (identical to the `statehouse tick skipped` pattern). A broken registry degrades
   to the evergreen station, never to silence.
2. **Date vs weekday collision / double-booking.** *Risk:* a derived playoff date
   equals a static Wed/Sat and the game runs twice, or two events claim one window.
   *Mitigation:* overlay dedupes by `(engine, overlapping-window, date)` keeping the
   higher priority; a per-window single-winner resolution by `priority` then `id`;
   property test in component 3.
3. **`_last_played` mutation via look-ahead.** *Risk:* `schedule_series` mutates the
   bracket's cadence ledger; a deriver calling it for horizon dates would corrupt the
   real schedule. *Mitigation:* derivers operate on `copy.deepcopy(bracket)` and are
   forbidden (by test) from writing any sidecar — they are strictly read-only.
4. **Weather deriver same-day only.** *Risk:* a blizzard takeover appears with no
   promo and mid-show, surprising listeners. *Accepted & designed:* `lead_days: 0`
   marks reactive events; blizzard is a *soft* slot-rider (Morning Scramble energy
   shifts, not a jarring format break) and the site card updates the moment the feed
   publishes. Missing weather feed ⇒ no blizzard (never invents weather, matching
   `is_snowfall`).
5. **Election Night is a brand-new engine.** *Risk:* the highest-novelty surface, a
   6-hour live count, on a fixed immovable date. *Mitigation:* it ships dark behind
   `ELECTION-ENABLED`; the civicguard meets the G3 zero-replacement CI bar; the
   reveal clock is already built and monotone-proven; a shadow soak runs against a
   generated cycle for weeks before arming. If it isn't ready by 2026-11-03, the gate
   stays closed and Night Shift/Culture Vulture run normally — no half-built engine
   touches air.
6. **Feed staleness at the CDN.** *Risk:* Cloudflare caches `takeovers.json` and an
   event shows late/lingers. *Mitigation:* the data feeds are already served
   no-store (the `now.json`/`league.json` convention); the publisher stamps
   `generated` and the loader filters `date >= today`, so a stale row can't resurrect
   a past event.
7. **Promo files outliving their event.** *Risk:* a Game-7 promo airs after Game 7,
   or a cancelled event's promos persist. *Mitigation:* the `expires` sidecar; the
   player purges `promo_*` past expiry and prefers them only in-window; on any doubt
   they're just extra bumpers, indistinguishable in tone from `STATIC_SWEEPERS`.
8. **Schema drift between registry and engines.** *Risk:* an event's `show` fragment
   names a cast/segment an engine doesn't expect. *Mitigation:* `registry.py`
   validates each record against a frozen field set at load; unknown `engine` ⇒ the
   event is dropped with a log line, never dispatched to a missing function.
9. **Promo flood / re-synth churn.** *Risk:* the 30-min `render_promos` pass either
   re-renders the same lines forever (wasted TTS cycles, files rewritten under the
   player) or, with overlapping lead windows, floods `reserve/` and crowds out
   `bumper_id_*` variety. *Mitigation:* rendering is idempotent, keyed on
   `(event_id, date, i)` in `reserve/promos.json` — a line renders exactly once, meta
   locked at first render (aired facts are canon forever); concurrent promotion caps
   at the top 2 in-window events by `priority` then `id`.
```
