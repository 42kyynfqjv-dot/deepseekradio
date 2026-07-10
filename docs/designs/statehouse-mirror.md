# Wending Statehouse Engine — MINIMAL-MIRROR-FIRST Design

Lens: the smallest faithful mirror of the proven hockey engine (`season.json`
spine, sidecars, date-seeded `sim_day`, derive-don't-store, air-gated
publishing, one-flag fallback) that passes the civic fidelity bar
(`docs/sim-grounding/civics-grounding.md`). Canon is LOCKED
(`station/wending-bible.md`); every byte of state is paid for by narratable
air.

## 1. Executive summary

- **`civics.json` is the spine, shaped like `season.json`**: small aggregates
  (seat counts, approval, phase, the TRACKED thread), everything heavy in
  per-General-Assembly **sidecars** under `data/statehouse/`. Missing sidecar
  or gate flag → the shows fall back to pure canon color with **zero numbers**
  (nothing civic has aired yet, so fallback is trivially safe forever).
- **Derive, don't store.** Members, the docket, whip counts, committee
  outcomes, and election returns are pure functions of `(ga, seed)`. Whip
  counts are *never stored* — recomputed from member leans on demand. Only two
  things are append-only truth that seeds cannot re-derive: **what aired**
  (the aired ledger) and **real weather** (snow-quorum days). Absent a stored
  record, catch-up assumes clear skies and unaired — self-healing by rule.
- **One axis, seven actors.** Six parties hold the 60 seats; the Office of
  Interparty Compliance holds none (canon: fields no candidates) but acts
  every day through Notices of Deficiency that stall bills — a full functional
  actor, satisfying the owner's no-gag-parties rule without violating its own
  charter. Every member carries one hidden scalar: **zipper lean** ∈ [0,1]
  (0 = merge early, 1 = zipper at the cone). Every vote is a pure function of
  party line, zipper alignment, and a per-bill seeded conscience draw.
- **Calendar = wall clock, identity mapping** (mirrors hockey §5). Sessions
  adjourn by 18:00 Wednesday and Saturday (Center Ice); quorum fails when the
  real Halfway weather feed says snow. Bootstrap joins GA 1 mid-year via the
  most canon-compliant device available: the session **cannot adjourn because
  the sine die resolution is pending in the Committee on Merging**.
- **Election Night is a hockey broadcast**: a seeded precinct-returns
  generator plus a `reveal(returns, cursor)` clock (mirror of hockey graft
  G1) — precinct waves are periods, a recount is overtime, a weather-delayed
  poll is a rain-out. One cursor feeds booth, news desk, and website.
- **The one-thread rule is code**: `civics.json["tracked"]` names exactly one
  marquee bill/race/arc. Only the tracked thread ever gets numeric detail on a
  sheet; `civicguard` strips numbers from everything else.
- Steady-state disk **< 300 KB/GA**; `tick()` fast path ~1 ms, day boundary
  < 50 ms. Rollover (new Assembly seated) is air-gated from day one — the
  hockey bug never gets a chance to exist here.

## 2. State schema

All files atomic tmp+replace with `.bak` (the existing `_save` pattern),
sharded per General Assembly (`-ga1`, `-ga2`); older GAs collapse into
`ledger.json` (Acts passed, election results, one line each).

### civics.json (the spine, beside season.json)

```json
{
  "ga": 1, "session": "regular-extended", "sim_through": "2026-07-12",
  "phase": "session",
  "seats": {
    "house":  {"prov": 14, "round": 9, "vang": 11, "barb": 7, "grudge": 6, "goose": 4},
    "senate": {"prov": 3,  "vang": 2,  "round": 2, "barb": 1, "grudge": 1}
  },
  "approval": {"gov": 46.2, "streak": 3, "series": {"2026-07-12": 46.2}},
  "tracked": {"kind": "bill", "id": "HB-7", "since": "2026-07-10",
              "beat": "committee", "resolved": null},
  "quorum_fails": ["2026-02-11"],
  "aired": {"HB-7:reported": 1789234567.0},
  "last_line": "HB-7 cleared Roads, Holes & Adjacent Depressions, 6 votes to 3",
  "rolled_pending": false
}
```

Seat counts are aggregates of the members sidecar (recomputed and asserted at
every save, like standings vs slates). `approval.series` prunes to 30 days.
`aired` maps event-ids → wall timestamps (the `final_air_at` mirror).
`quorum_fails` is the weather truth ledger. If `government.html` canon states
different seat counts, the canon file (§9) wins and this example yields.

### data/statehouse/members-ga1.json (~14 KB)

```json
{
  "schema": 1, "ga": 1,
  "members": {
    "H-03": {"name": "Doreen Vachon", "chamber": "house", "district": 3,
             "party": "round", "zipper": 0.44, "maverick": 0.12,
             "tenure": 3, "aired": false},
    "S-07": {"name": "Earl Thibodeau", "chamber": "senate", "district": 107,
             "party": "prov", "zipper": 0.21, "maverick": 0.05,
             "tenure": 6, "aired": false}
  },
  "officials": {
    "governor":     {"name": "Marty Bouchard",  "canon": true},
    "clerk":        {"name": "Gord Pelletier",  "canon": true},
    "potholes":     {"name": "Bert Demers",     "canon": true},
    "roundabout":   {"name": "Toivo Ostberg",   "canon": true},
    "speaker": "H-19", "protem": "S-02",
    "tenth_chair": {"name": null, "trusted": false}
  },
  "leaders": {"house": {"prov": "H-11", "vang": "H-30"}, "senate": {"prov": "S-02"}}
}
```

60 members × ~150 B. Names mint from the shared `livegame.FIRST_NAMES`/
`LAST_NAMES` bank (canon anchor: shared name-bank); the four canon officials
are pinned verbatim from `government.html`. Party zipper priors: `vang`
μ=0.88 (anchors Late), `prov` μ=0.25 (cautious Early), `grudge` μ=0.70,
`barb` μ=0.50, `round` uniform (they circle), `goose` off-axis (`zipper`
null → per-vote seeded draw, purchasable only for goose considerations).

### data/statehouse/docket-ga1.json (~60 KB at session peak)

```json
{
  "schema": 1, "ga": 1, "next_no": {"H": 41, "S": 12},
  "bills": {
    "HB-7": {
      "title": "An Act Relating to the Numbering of Potholes Prior to Repair",
      "sponsor": "H-03", "cosponsors": ["H-14", "H-22"],
      "committee": "roads", "stage": "REPORTED",
      "intro": "2026-07-01", "marquee": 0.91,
      "history": [["2026-07-01", "INTRODUCED"],
                  ["2026-07-06", "HEARING", "roads"],
                  ["2026-07-10", "REPORTED", "roads", [6, 3]]],
      "deficiency": null
    },
    "SB-3": {"title": "An Act Establishing a Committee to Name the Candidate",
             "sponsor": "S-05", "committee": "merging", "stage": "MERGED",
             "intro": "2026-02-02", "marquee": 0.30,
             "history": [["2026-02-02", "INTRODUCED"],
                         ["2026-02-03", "REFERRED", "merging"]]}
  }
}
```

Stage enum (docket.py owns it, guards quote it):
`INTRODUCED → IN_COMMITTEE → REPORTED → CALENDARED → PASSED_ORIGIN →
IN_SECOND → REPORTED_2 → PASSED_BOTH → CONFERENCE → ENROLLED →
SIGNED | VETOED | OVERRIDDEN | LAW_NO_SIG`; terminal deaths
`DIED_IN_COMMITTEE, MERGED, CROSSOVER_BARRED, FAILED_FLOOR, POCKET`.
`MERGED` = referred to the Committee on Merging: never advances, never dies —
canon's forever-referral, and a flavored slice of the 55–70% committee
mortality budget. Recorded tallies (`[6,3]`, floor roll calls) are stored *in
history at the moment they resolve* — those are the published truth; whip
counts before resolution are derived, never stored.

### data/statehouse/calendar-ga1.json (~6 KB, immutable once written)

```json
{
  "schema": 1, "ga": 1, "convened": "2026-01-12",
  "sessions": [{"kind": "regular", "start": "2026-01-12",
                "crossover": "2026-03-20", "sine_die": "2026-09-26",
                "note": "sine die resolution pending in Merging"}],
  "committee_days": ["Mon", "Wed", "Fri"], "floor_days": ["Tue", "Thu", "Sat"],
  "hockey_adjourn": ["Wed", "Sat"],
  "election": {"date": "2026-11-03", "cycle": 2026,
               "races": ["house-all", "senate-all", "potholes"]}
}
```

### data/statehouse/election-2026.json (~90 KB, written once at generation)

```json
{
  "schema": 1, "cycle": 2026, "turnout": 0.44, "precincts": 171,
  "races": {
    "H-03": {"cands": [{"name": "Doreen Vachon", "party": "round", "inc": true},
                       {"name": "Lucille Marchand", "party": "vang"}],
             "final": [1642, 1598], "margin_pct": 1.36, "recount": false,
             "precincts": [{"id": "H03-1", "wave": 1, "votes": [598, 414]},
                           {"id": "H03-2", "wave": 2, "votes": [521, 588]},
                           {"id": "H03-3", "wave": 3, "votes": [523, 596],
                            "rainout": false, "provisional": 41}]}
  },
  "waves": {"1": [0, 2700], "2": [2700, 7200], "3": [7200, 12600]},
  "broadcast_anchor": null
}
```

Fully derived from `f"cycle:{cycle}"`; persisted once as insurance against
code drift (the schedule-file precedent). `broadcast_anchor` is stamped with
the wall time the Election Night show starts — the reveal cursor's zero.

### data/statehouse/potholes.json (~3 KB) and news-lines.json

```json
{"registry": {"pth-01": {"name": "Gerald", "mile": 3.2, "filled": null},
              "pth-02": {"name": "The Big One", "mile": 0.1, "filled": "2026-07-08"}},
 "commissioner_note": "filling them is erasure"}
```

Named potholes are the approval engine's event source (a filled pothole is a
goal; canon). `news-lines.json` mirrors the hockey scores-desk wire.

Gates: `data/statehouse/ENABLED` + `VERIFIED` (hash over sidecars, G4
mirror). Total steady-state: ~180 KB in-session, ~280 KB in an election cycle.

## 3. Module breakdown — `src/statehouse/`

Stdlib-only leaf modules, pure functions against §2 schemas, no imports from
`orchestrator.py`; `civics.py` is the facade (the `season.py` mirror) and the
only writer of `civics.json`.

**calendar.py** (~60 lines)
```python
def build_calendar(ga: int, convened: str) -> dict          # -> calendar-ga{n} body
def day_kind(cal: dict, date: str) -> str    # floor|committee|quiet|election|canvass
def phase(cal: dict, date: str) -> str       # session|interim|campaign|election
def hockey_adjourned(date: str) -> bool      # Wed/Sat — mirrors is_air_night()
```

**members.py** (~160 lines)
```python
def mint_assembly(ga: int, canon: dict, carryover: dict | None = None) -> dict
    # 51 House + 9 Senate from the shared name bank; canon officials pinned;
    # carryover = re-elected incumbents keep name/id across GAs (aired names are canon)
def member_vote(m: dict, bill: dict, ga: int) -> bool
    # PURE: party_line(bill.axis, m.party) + zipper alignment + maverick draw
    # seeded random.Random(f"vote:{ga}:{bill_id}:{mid}") — recomputable forever
def party_line(bill: dict, party: str, ga: int) -> float    # p(yea) in [0,1]
def goose_price(bill: dict) -> str | None    # the goose bloc's demand, if pivotal
```

**docket.py** (~220 lines)
```python
def introduce_day(dk, members, cal, ga, date) -> list[dict]      # 0-3 new bills
def committee_day(dk, members, cal, ga, date, snowed: bool) -> list[dict]
    # hearings, REPORTED votes (stored tallies), Merging referrals, deficiency
    # notices (OIC acts here), crossover-bar sweep on the crossover date
def bill_title(rng, committee: str) -> str          # template bank, G/PG, canon-toned
def pick_tracked(dk, ga, date) -> str | None        # highest marquee unresolved bill
def stage_verbs(stage: str) -> list[str]            # guard vocabulary per stage
```

**floor.py** (~180 lines)
```python
def quorum(members, date, weather: dict | None) -> tuple[bool, str]
    # False + "snow" when feed shows snowfall; missing feed => quorum holds
def whip_count(bill, members, ga) -> dict     # {"yea": 27, "nay": 19, "und": 5} pure
def floor_day(dk, members, cal, ga, date, snowed) -> list[dict]
    # second/third readings for CALENDARED bills; voice vs roll call (70/30);
    # tallies stored into history; veto/override checks in governor window
def veto_action(bill, civ, ga, date) -> str | None   # sign|veto|law_no_sig
```

**approval.py** (~80 lines)
```python
def drift(civ, ga: int, date: str, events: list[dict]) -> float
    # mean-reverting to 46, seeded daily ±0.8, event deltas (pothole +2.5,
    # quorum fail -1.5, veto override -4, session milestone ±2); clamp [25, 71]
def streak(series: dict) -> int               # consecutive up/down days — THE streak
def pothole_day(reg, ga, date) -> list[dict]  # seeded fill/discovery events
```

**election.py** (~260 lines)
```python
def generate_cycle(cycle: int, members, ga: int) -> dict     # election-{cycle} body
    # hidden per-seat lean = base + party swing (±2-6) + noise; turnout 0.35-0.50;
    # 171 precincts in 3 waves; rainouts from nothing (seeded 0-2 per cycle);
    # recount races where margin <= 0.5% or <= 12 votes
def reveal(el: dict, cursor: int) -> dict
    # THE ONLY renderer of returns. cursor = seconds since broadcast_anchor.
    # -> {"pct_in": 61, "races": {"H-03": {"tally": [1121, 1002], "wave": 2,
    #     "status": "too-early|leaning|called|recount|rainout", ...}}}
    # Monotonic: tallies never decrease, status never regresses (G1 tests).
def call_state(race: dict, revealed_tally, precincts_out) -> str
    # trailing max-possible-remaining < margin, grounded AP logic; never call
    # inside the recount threshold
def recount_script(race: dict, cycle: int) -> list[dict]
    # OVERTIME: same result re-narrated slower with ceremony; flips ~1 in 10
def seat_new_assembly(el: dict, members) -> dict             # -> carryover for mint
```

**briefs.py** (~200 lines) — the broadcast contract (§7).

**src/civicguard.py** (~150 lines, sibling of `scoreguard.py`) — §8.

**civics.py** (facade, ~250 lines)
```python
def tick(date: str) -> None            # §4; called every main-loop pass
def session_brief(date: str) -> str    # pregame-analog sheet
def gavel_recap(date: str) -> str      # postgame-analog sheet
def record_aired(event_ids: list[str], air_at: float) -> None   # orchestrator stamps
def export(path: str = ".../statehouse.json") -> None           # air-gated
```

## 4. The daily `sim_day` algorithm

`tick(date)` mirrors hockey §6 exactly: **fast path** (~1 ms) when
`sim_through == date` — `civics.json` only, sidecars never opened, throttled
`export()`. On a day boundary, for each missing day `d` (catch-up chunked 45
days/pass):

1. **Load sidecars once** (members 14 KB + docket 60 KB + calendar 6 KB).
2. **Weather gate.** Read the station's cached Halfway weather (the real
   Open-Meteo feed the shows already twist). Snowfall today → `snowed=True`,
   append to `quorum_fails`. For *past* days in catch-up, `snowed = d in
   quorum_fails` — weather is live entropy; no record means clear. Quorum
   never blocks committee work ("committees meet in the basement").
3. **Committee calendar** (`committee_day`): seeded
   `Random(f"cmte:{ga}:{d}")` picks 2–5 bills for hearings; per-bill advance
   draws use `Random(f"bill:{ga}:{bill_id}:{d}")` so the docket is
   order-independent and self-healing bill by bill. Calibrated hazards (§11)
   move bills through stages; the crossover date bars unpassed origin-chamber
   bills; OIC issues a Notice of Deficiency to ~6% of active bills (freezes
   them 3–10 days — the antagonist is mechanical, not narrated-only).
4. **Floor day** (`floor_day`): if quorum holds, CALENDARED bills get
   readings; passage tallies computed via `member_vote` over all present
   members, stored into `history` at resolution. Wednesday/Saturday floor
   work must complete by the 18:00 adjournment — bills that miss the gavel
   carry to the next floor day ("the House stands adjourned for the hockey").
5. **Approval drift**: `pothole_day` events + legislative events feed
   `drift()`; series appended, pruned to 30 days; streak recomputed.
6. **Tracked thread** (one-thread rule, TRACKED in code): if
   `tracked.resolved`, `pick_tracked` promotes the highest-`marquee`
   unresolved bill (election phase: the closest-lean race; interim: the
   approval arc). **At most one decisive tracked event per day** — if the
   seeded schedule would resolve the tracked bill and a marquee committee
   vote on the same day, the committee vote slides a day. Fifty-nine other
   seats stay deep in code, light on air.
7. **Phase transitions, air-gated**: sine die → `interim`; 6 weeks before
   election → `campaign`; election day → generate/load the cycle file;
   canvass complete → `rolled_pending=true`; the new Assembly seats
   (`mint_assembly` with carryover) **only when every election event-id in
   the tracked races has an `aired` stamp in the past** — the hockey rollover
   fix, born air-gated.
8. Save dirty files (atomic + .bak), throttled `export()`.

Cost: a docket sweep is a few hundred seeded draws — well under 50 ms/day;
a 45-day catch-up ≈ 1 s. Kokoro undisturbed.

## 5. Session calendar

**1 wall day = 1 civic day, identity** — same justification as hockey §5:
the shows air in listener time and "last Wednesday at the Dome" must mean
last Wednesday. Real small-state rhythm (grounding A.1), Wending-flavored:

- **GA = 2 wall years**, numbered. Odd wall years: **Regular Session**,
  convenes 2nd Monday of January, sine die mid-May (~18 legislative weeks,
  VT-model). Even years: **Budget Session**, 2nd Monday of February, 20
  floor days (WY-model; non-budget bills need a 2/3 introduction vote —
  a volume throttle and a running bit). Special sessions: governor's call,
  0–2/GA, single subject.
- **Weekly texture**: committee days Mon/Wed/Fri, floor days Tue/Thu/Sat;
  **Wednesday and Saturday the Half-Dome empties by 18:00 for Center Ice**
  (canon; `hockey_adjourned()` reads the same Wed/Sat constant the hockey
  engine uses — one clock, two institutions). Sunday: quiet.
- **Snow-quorum**: the real weather feed. A snow day on a floor day is a
  narratable event ("the call of the House reached eleven members and a
  snowplow"); on a committee day it's color. January–March sessions will
  fail quorum a lot. That is the joke, and it is calibrated reality both.
- **Interim** (mid-May → January): interim study committees meet weekly
  (seeded topics), the roundabout and pothole ledgers keep drifting approval,
  campaign phase opens 6 weeks before any November election. The state never
  goes silent; it just goes slower, which for Wending is a rounding error.
- **Bootstrap exception (GA 1, 2026)**: convened retroactively 2026-01-12;
  currently in **regular-extended** session because the sine die resolution
  is pending in the Committee on Merging (pure canon — the closed loop that
  founded the state now runs its legislature). Scheduled sine die
  2026-09-26; Election Night 2026-11-03; GA 2 convenes 2027-01-11 on the
  proper rhythm.

## 6. Election engine

**Cycles**: even Novembers — all 51 House + all 9 Senate seats (2-year
terms). Governor: 2028, then every 4. **Pothole Commissioner: every
November** (canon: perennially up for reelection) — odd years get a small
Election Night too. First takeover broadcast: **Tuesday 2026-11-03**.

**Generator** (`generate_cycle`, seed `f"cycle:{cycle}"`): each seat's hidden
per-cycle lean = minted base lean + party swing (±2–6 pts, grounding B.10) +
seat noise. Turnout drawn 35–50% (midterm band), ~2,900 voters/district, 171
precincts in 3 waves (rural fast / mid / Halfway's slow central-count dumps —
grounding B.3/B.4). Calibration targets a *distribution*, not a script:
~70% comfortable races, 20–25% single digits, **3–8 races inside 3 points**,
0–2 automatic recounts (margin ≤ 0.5% or ≤ 12 votes — "the Clerk counts the
last dozen personally"), 0–2 weather-delayed precincts (rain-outs, resolved
next day "under review").

**Broadcast mapping** (canon, called by Bucky Merle & Sal Tarantella):

| Hockey | Election Night |
|---|---|
| Period 1/2/3 | Reporting waves 1/2/3 (0–45 min, 45–120, 120–210) |
| Live scorebug | `reveal(el, cursor)` — one monotonic clock for booth, desk, site |
| Goal horn | A race called (`call_state`: trailing max-remaining < margin) |
| Overtime | **Recount**: `recount_script` re-narrates the same result slower, with ceremony; flips ~1 in 10 (grounding B.8) |
| Rain-out / delay | Weather-delayed precinct; provisional ballots "under review" |
| The streak | Governor approval rides the night: a filled pothole is a goal, a botched filing a penalty (approval event feed runs during the show) |

The tracked race (one-thread rule) gets wire-to-wire numeric coverage; other
races surface only as calls ("the Vanguard holds District 30") — status
words, no invented tallies, and every revealed tally registers in the guard's
allow-list. `rolled_pending` arms at canvass; the new Assembly seats only
after the tracked race's call has an aired stamp (§4.7).

## 7. Broadcast contract

All sheets are code-owned strings/dicts from `briefs.py`; the LLM narrates,
`civicguard` verifies. Every number a host may say enters the sheet first.

- **`session_brief(date)`** (pregame analog, for the government shows):
  `TRACKED:` block — bill id, title, stage in stage-enum words, sponsor,
  committee, **whip count** (`27 yea, 19 nay, 5 undecided — the Roundabout
  bloc has not completed its lap`), next scheduled action; `TODAY AT THE
  DOME:` committee calendar (bill titles + stage words only, no numbers);
  `APPROVAL:` today's value + streak; `WEATHER RULE:` quorum status;
  `AROUND THE DOME:` 2–3 one-line beats (deficiency notices, Merging
  referrals, pothole news). Explicit instruction: unresolved votes have no
  outcome yet; never predict a tally.
- **`gavel_recap(date)`** (postgame analog): resolved outcomes with stored
  tallies ("HB-7 passed the House 29–20, roll call; the Goose delegation
  voted yea after securing a bread-adjacent amendment"), veto/override
  status, approval move. Emitting this sheet returns the event-ids;
  the orchestrator stamps `record_aired(ids, air_at)` when the audio ships —
  the `final_air_at` mirror.
- **News desk** — `dome_desk(date)` writes 3–5 wire lines to
  `data/statehouse/news-lines.json`; Frequency News and the morning shows
  read it exactly like the hockey scores desk.
- **Election Night takeover** — `election_sheet(cursor)` renders
  `reveal()` output per broadcast beat: pct-in, tracked-race tally, new
  calls since last beat, recount/rain-out ceremonies, the approval streak
  overlay. The site's election view is wall-anchored to the same
  `broadcast_anchor`, so booth and page never disagree (G1 mirror, with the
  same monotonicity tests).
- **Website statehouse page** — `export()` → `.../statehouse.json`:
  seat map by party, approval series (aired values only), tracked bill
  status **as of its last aired event**, session calendar, election reveal
  when live. Air-gating: an event without an `aired` stamp in the past does
  not export — the page can never spoil the gavel recap, exactly as the
  scorebug cannot spoil the horn.
- **Truth-guard fact tables** — `build_civic_facts(civ, dk, members, date)`
  produces: `names_ok` (members + officials + candidates), `bill_ids` (the
  docket's real ids), `stage_ok[bill_id]` (allowed stage verbs),
  `allow_tallies` (every stored tally + today's whip count + revealed
  election numbers + today's approval), `tracked_id`. Shape and lifecycle
  mirror `scoreguard.build_facts`; per-sheet self-guard CI (G3): every
  briefs test renders the sheet, builds facts, runs the guard over synthetic
  host lines quoting it — zero replacements or the test fails.

## 8. Guards — what `civicguard` must catch

Code owns every number; the LLM can never invent a tally, margin, or
committee outcome. `enforce_civics(text, facts)`:

1. **Invented tallies**: any `\b(\d+)[–-](\d+)\b` or "N yea/nay/votes"
   pattern not in `allow_tallies` → replaced with the grounded tally if the
   bill is identifiable, else with stage words ("on a voice vote").
2. **Invented margins/percentages** (election + approval): `\d+(\.\d+)?%`
   and "by N votes" validated against revealed returns and today's approval;
   unknown → replaced with the tracked race's real revealed figure or "too
   early to call".
3. **Invented committee outcomes**: stage-verb check — "passed committee",
   "died", "signed", "vetoed" must match `stage_ok[bill_id]`; a bill in
   `MERGED` can only ever be "still in the Committee on Merging".
4. **Phantom bills**: `[HS]B-\d+` not in `bill_ids` → nearest real id
   (edit-distance, the `_nearest_surname` pattern).
5. **Phantom people**: names outside `names_ok` → nearest member/official
   (nameguard integration; the shared name bank keeps `pool_ok` valid).
6. **Seat-count and quorum inventions**: "31 seats", "quorum of N" checked
   against `seats` and the 26/51, 5/9 constants.
7. **One-thread enforcement**: numeric detail attached to a non-tracked
   bill/race id → numbers stripped to stage/status words. Off-tracked depth
   stays in code.
8. **Result-before-air**: any resolved outcome whose event-id lacks an aired
   stamp older than now → the guard replaces it with the pre-resolution
   framing (the display-league un-apply, in prose).

## 9. Migration / bootstrap

Nothing has aired **except `government.html` canon**. One idempotent script,
`scripts/bootstrap_statehouse.py`, gate OFF:

1. **Canon extraction**: parse `government.html` + `station/wending-bible.md`
   into `data/statehouse/canon.json` (officials, party roster, seat counts
   if stated, registry places). Emits `canon-diff.txt` (G6 mirror) listing
   any divergence between minted state and canon; **cutover requires it
   empty**.
2. `build_calendar(1, "2026-01-12")` — the regular-extended session (§5),
   sine die 2026-09-26, election 2026-11-03.
3. `mint_assembly(1, canon)` — 60 members, canon officials pinned, seat
   split per canon (else §2's designed hung House: no bloc reaches 26
   without the Roundabout or the Goose — the canon "hung House" lever).
4. **Retro docket**: replay `sim_day` from 2026-01-12 to today with the gate
   off (pure seeds, ~180 days ≈ 4 s) — a lived-in docket: ~110 bills, ~30
   already dead in committee, a dozen in Merging, 14 Acts signed, approval
   series with history. No `aired` stamps exist, so *nothing is
   spoiler-gated and nothing can contradict air* — the retro fill is free.
5. `pick_tracked` selects HB-7-class marquee bill for the first show arc.
6. `scripts/verify_statehouse.py`: seat sums == civics.json aggregates ==
   canon; every history tally consistent with member counts; calendar
   invariants (Wed/Sat adjournment, crossover < sine die); guard round-trip
   on all sheets; canon-diff empty → writes `VERIFIED`.
7. `touch data/statehouse/ENABLED`. Fallback forever: `rm ENABLED` — shows
   revert to canon color with no numbers; sidecars stay warm.
8. Overnight **shadow mode** (G2 mirror) before the first government show:
   tick runs against `data/statehouse-shadow/` for a day, exception-isolated,
   zero writes to shared state.

## 10. Build order (parallelizable pure components, tests first-class)

| # | Component | Deliverable | Test strategy |
|---|---|---|---|
| A | `calendar.py` | build/day_kind/phase | Property: Wed/Sat always adjourned, crossover/sine-die ordering, GA-2 rhythm matches §5 dates |
| B | `members.py` | mint/member_vote/party_line | Golden seeds: canon officials pinned, seat sums exact; 10k `member_vote` draws → party-line adherence 78–92%, goose bloc pivotal-purchase behavior |
| C | `docket.py` + `floor.py` | lifecycle + votes | 50-session Monte Carlo vs §11 envelopes; per-bill seed order-independence (shuffle days, same docket); tallies ≤ present members; crossover sweep property |
| D | `approval.py` | drift/streak/potholes | 10k-day series: mean 44–48, band [25,71] never violated, streak math, event deltas visible |
| E | `election.py` | generate/reveal/call/recount | Reveal monotonicity + status-no-regress; call_state never calls inside recount threshold; cycle envelopes (§11); cross-surface equality sheet-vs-export at equal cursors |
| F | `briefs.py` + `civicguard.py` | sheets + guard | G3 self-guard CI per sheet; adversarial corpus: 40 lines with invented tallies/margins/stages → 100% caught; zero false replacements on clean lines |
| G | Integration (main loop) | `civics.py` facade, tick, bootstrap, verify, shadow, export | Offline dry-run: bootstrap → tick 60 synthetic days → invariants; fast-path < 50 ms; air-gate test: resolved-unaired event absent from export |

A–F are leaf modules with zero interdependency beyond §2 schemas —
parallelize now; F needs B/C/E shapes only. Integration is incremental,
component-by-component (hockey-final rule), never big-bang on live air.

## 11. Calibration (vs `civics-grounding.md`, Wending scale: 51H/9S)

`scripts/calibrate_statehouse.py --sessions 50`, a slow-marked pytest:

- **Bill volume**: Regular Session 130–190 introduced (sponsor cap 4/member;
  WY-scaled); Budget Session 45–80 with the 2/3 intro gate.
- **Committee mortality 55–70%** of introduced (of which 15–25 points via
  Merging referral — flavored, not extra); no hearing within the first 40%
  of session strongly predicts death.
- **Floor failure < 5%** of bills reaching third reading (leadership
  calendars only what passes — `floor_day` filters by whip count ≥ 48%).
- **Enactment 22–28%** → 30–50 Acts/Regular Session; voice/roll-call 70/30;
  conference on < 10% of enacted; veto < 5% of transmitted; override needs
  34/51 + 6/9, succeeds < 20% of attempts.
- **Quorum**: 26/51 House, 5/9 Senate; winter floor-day snow-failure rate is
  whatever Halfway's real winter delivers (observed, not tuned).
- **Session length**: ~18 legislative weeks regular / 20 floor days budget.
- **Election**: turnout 35–50%; 3–8 races within 3 pts, 0–2 recounts
  (≤ 0.5% or ≤ 12 votes, flip ≤ 10%), reveal sigmoid ~10%/55%/90% at
  +1h/+2h/+3.5h with Halfway central-count dumps of 3–12 points; cross-cycle
  party swings ±2–6.
- **Approval**: mean 44–48, σ(daily) ≤ 1.2 excluding events, streak
  distribution geometric-ish (p(≥5) ≈ 8–15%).

Envelope failures gate the ENABLED flag exactly as hockey's smoke
calibration gates cutover.

## 12. Risk register

| # | Risk | Mitigation |
|---|---|---|
| 1 | Contradicting `government.html` canon (the only aired surface) | canon.json extraction + canon-diff.txt must be empty; verify re-checks; VERIFIED hash gate (G4) — a human can't skip it at 2am |
| 2 | Guard misses invented civic numbers (richer surface than scores) | strict allow-list + replace-with-grounded, 8 catch classes (§8), per-sheet self-guard CI, adversarial corpus in tests |
| 3 | One-thread drift: shows wander into untracked numeric detail | tracked-id enforced by guard (numbers stripped to stage words); sheets structurally give only the tracked thread numbers |
| 4 | Weather feed outage breaks determinism or blocks the session | quorum defaults to *holds* on missing feed; snow days persisted in `quorum_fails` (live entropy is append-only truth); catch-up reads the ledger, never the feed |
| 5 | Election Night generator too flat or too chaotic on the first-ever takeover | distribution envelopes (§11) in CI; reveal monotonicity tests; dry-run a full synthetic broadcast (sheet-vs-export) before November; recount ceremony is scripted structure, seeded content |
| 6 | Scope creep past the mirror (lobbyists, budgets, courts) | every feature must map to an existing hockey mechanism or be gated dark like economy/playoffs; civics.json schema frozen by this doc — schema friction is reported, never improvised |
