# Wending Statehouse Engine — CIVIC-FIDELITY-FIRST Design

Lens: a statehouse reporter could not catch the fake. Real bill-lifecycle stage
names and timing (VT/WY/DE grounding), whip counts that sum to the chamber,
committee calendars, session rhythms, election-night returns that behave like
precinct reporting actually behaves. Architecture mirrors the proven hockey
engine (`docs/designs/hockey-final.md` + `hockey-minimal.md`): small spine +
sidecars, derive-don't-store, date-seeded self-healing `sim_day`, air-gated
publishing, a scoreguard-class truth guard, gates and instant fallback. Canon
is LOCKED per `station/wending-bible.md`; content stays inside
`station/bible.md`'s G/PG guardrail — procedural comedy, never real-world
politics.

## 1. Executive summary

- **`civics.json` is the spine** (mirrors `season.json`): assembly/session
  counters, `sim_through`, approval, seat table, the TRACKED pointer, phase
  machine. Everything heavy lives in sidecars under `data/statehouse/`;
  sidecar missing → module degrades to spine-only lines. Fallback = delete one
  flag file.
- **Derive, don't store.** Members, dockets, committee assignments, and
  election returns are pure deterministic functions of
  `(assembly, session, seed)`; persisted once as insurance, always re-derivable.
  Journal shards pruned to 30 days.
- **1 wall day = 1 legislative calendar day, identity mapping** — same
  unanimous verdict as hockey §5. A long session ≈ 18 wall-weeks (VT rhythm),
  a short budget session ≈ 8 weeks (WY rhythm), one full Assembly cycle ≈ 9
  months — the civic analog of the 8-month hockey season, deliberately
  out of phase with it so Election Night and the Cup never collide.
- **The one-thread rule is code, not convention**: `civics.json["tracked"]`
  holds exactly one marquee bill, one feud, one race, one approval arc.
  Briefs render depth ONLY for tracked threads; the other 59 seats are fully
  simulated in sidecars, surfaced as one-line digests.
- **Whip counts are computed, never sampled at narration time**:
  `whip_count()` is a deterministic function of the 60 minted members' Zipper
  positions, party lines, and grudges — yes+no+undecided+absent ≡ chamber size
  by construction, and `civicguard` verifies every tally the booth utters.
- **Sessions adjourn Wednesday and Saturday nights for the hockey** (canon):
  the calendar never schedules floor votes on Center Ice nights. **Quorum
  fails when it snows** via the station's real Open-Meteo feed, cached and
  ledgered append-only so history never retro-changes.
- **Election Night is a broadcast reveal, not a live roll**: returns are a
  seeded timeline; a `reveal_returns(timeline, cursor)` function — the exact
  G1 reveal-clock pattern — is the ONLY renderer for the booth, the sheets,
  and the website. Precincts are periods, a recount is overtime (same result,
  re-narrated slower), a weather-delayed poll is a rain-out, approval rides
  the night like a streak.
- Steady-state disk **< 800 KB/assembly**; `tick()` fast path < 5 ms, day
  boundary < 60 ms. Nothing has aired yet except the `web/government.html`
  canon page — bootstrap is nearly free, but a canon-diff gate (G6 mirror)
  still guards HB-114 and the ticker facts.

## 2. State schema

All files atomic tmp+replace+`.bak` (the existing `_save` pattern). Sharded
per assembly-session (`-a1s1`); prior assemblies collapse into `records.json`.

### civics.json (the spine, ~4 KB)

```json
{
  "assembly": 1, "session": 1, "sim_through": "2026-07-20",
  "phase": "regular",
  "day": 12, "legislative_day": 9,
  "seats": {
    "house": {"prov": 13, "round": 11, "zmv": 9, "goose": 6,
              "barbara": 5, "grudge": 5, "ind": 2},
    "senate": {"prov": 3, "round": 2, "zmv": 2, "goose": 1, "grudge": 1}
  },
  "approval": {"gov": 52.4, "streak": 2,
               "last_event": "pothole on Route 9 filled (unassisted)"},
  "tracked": {"bill": "HB-131", "feud": "ladder-stores", "race": null,
              "arc": "approval"},
  "last_lines": ["HB-131 reported out of Merging, 7-4, one member circling"],
  "recount_flag": null,
  "v": {"rolled_pending": false, "start": "2026-07-09"}
}
```

`phase` ∈ `regular | interim | budget | campaign | election | canvass | organization`.
Seat counts are the ONLY politics numbers stored in the spine; everything else
derives. Compliance (`oic`) holds no seats — canon — but is a functional
actor: it acts on bills and members daily (Notices of Deficiency, §4), never
"fails to show up."

### data/statehouse/members-a1.json (~35 KB)

```json
{"schema": 1, "assembly": 1,
 "members": {
   "H-07": {"name": "Marguerite Thibodeau", "chamber": "house", "district": 7,
            "party": "round", "zip": -0.35, "discipline": 0.7,
            "maverick": 0.12, "attend": 0.93, "grudges": ["H-22"],
            "role": null, "aired": false},
   "S-03": {"name": "Wallace Pelto", "chamber": "senate", "district": 3,
            "party": "prov", "zip": 0.6, "discipline": 0.8,
            "maverick": 0.05, "attend": 0.97, "role": "pro_tem", "aired": false}
 },
 "officials": {
   "governor":  {"name": "Marty Bouchard", "aired": true},
   "clerk":     {"name": "Gord Pelletier", "aired": true},
   "speaker":   {"pid": "H-30"},
   "pro_tem":   {"pid": "S-03"},
   "pothole_commissioner": {"name": "Bert Demers", "aired": true},
   "barbara":   {"pid": "H-44"}
 },
 "party_lines": {"prov": {"zip": 0.15, "block_bias": 0.35},
                 "round": {"zip": 0.0, "lap_required": true}, "...": {}}}
```

Three scalars carry the whole member model (mirrors `ov/sh/pl`): `zip` ∈
[−1 early, +1 late] on the Zipper axis, `discipline` (P follows party line),
`maverick` (P flips on a coin-of-the-day). `attend` drives quorum. Barbara is
delegate H-44, sits on her own Committee, thinks it's about drainage.

### data/statehouse/bills-a1s1.json (~120 KB, the docket)

```json
{"schema": 1, "assembly": 1, "session": 1,
 "bills": {
   "HB-131": {"title": "An Act Relating to the Numbering of Potholes",
     "topic": "potholes", "sponsor": "H-07", "cosponsors": ["H-12","H-40"],
     "chamber": "house", "stage": "reported", "committee": "transport",
     "zip_valence": 0.4, "salience": 0.8, "tracked": true,
     "history": [["2026-07-09","introduced"],["2026-07-09","referred:transport"],
                 ["2026-07-14","hearing:1"],["2026-07-20","reported:7-4"]],
     "votes": {"cmte:transport": {"yeas": 7, "nays": 4, "absent": 0,
               "method": "roll"}},
     "deficiency": null}
 },
 "counters": {"hb": 158, "sb": 24}}
```

`stage` ∈ the real lifecycle (grounding A.2, exact names):
`drafted → introduced → in_committee → reported → calendared → second_reading
→ third_reading → crossed_over → second_chamber_committee →
second_chamber_floor → conference → enrolled → to_governor → signed →
law | vetoed → override_pending → law | dead`. Terminal `dead` records a
`died:` reason (`no_hearing`, `tabled`, `crossover_missed`, `floor_failed`,
`pocket_veto`). Every stage change appends to `history` with its date —
the reporter-proof paper trail.

### data/statehouse/committees-a1.json (~10 KB)

```json
{"house": {
   "merging":   {"name": "Committee on Merging", "chair": "H-30",
                 "members": ["H-30","H-02","..."], "meets": ["Mon","Thu"]},
   "transport": {"name": "Transportation and the Roundabout", "chair": "H-07",
                 "members": ["..."], "meets": ["Tue","Fri"]},
   "appropriations": {"...": "..."}, "drainage": {"...": "..."},
   "barbara": {"name": "Committee to Formally Address What Barbara Said in 1987",
               "chair": "H-19", "members": ["H-44","..."], "meets": ["Tue"]}},
 "senate": {"finance": {"...": "..."}, "rules": {"...": "..."}}}
```

House: 11 standing committees, members sit on exactly 1 (VT model, and the
comedy wants everyone trapped in one room). Senate: 5, senators sit on 2.
Referral to Merging is where questions go to live forever (canon): Merging's
report hazard is 0.15× baseline.

### data/statehouse/calendar-a1s1.json (~8 KB, immutable once written)

```json
{"schema": 1, "convene": "2026-07-09", "crossover": "2026-09-21",
 "sine_die": "2026-11-11",
 "days": {"2026-07-21": {"kind": "floor", "house_calendar": ["HB-131","HB-118"],
                          "senate_calendar": ["SB-104"]},
          "2026-07-22": {"kind": "committee"},
          "2026-07-25": {"kind": "adjourned", "why": "center_ice"}},
 "snow_ledger": {"2026-12-03": {"code": 73, "quorum_failed": ["house"]}}}
```

`snow_ledger` is append-only: once a snow day is observed and recorded, it is
canon even if the weather API later disagrees — quorum history never
retro-changes.

### data/statehouse/journal-a1s1.json (~6 KB/day equivalent, pruned 30 days)

```json
{"2026-07-20": {"lines": [
    "HB-131 reported out of Transportation, 7-4 on the roll",
    "SB-104 referred to Merging, where it will remain",
    "Compliance issues Notice of Deficiency: HB-122 filed in blue ink"],
  "whips": {"HB-131": {"yes": 24, "no": 17, "undecided": 8, "absent": 2}},
  "aired": []}}
```

The journal is the news wire AND the air-gating ledger: a line moves into
`aired` (with a timestamp) when a show's script is generated quoting it; the
website reveals only aired lines plus stage facts older than 24 h (§7).

### data/statehouse/elections-a1.json (written at campaign phase, ~90 KB peak)

```json
{"cycle": 1, "election_date": "2027-01-12",
 "races": {"H-07": {"district": 7, "inc": "H-07", "chal_party": "grudge",
                    "chal": "Ruth Aho", "lean": 0.08, "tracked": false},
           "pothole_commissioner": {"inc": "Bert Demers", "chal": "...",
                                    "lean": -0.02, "tracked": true}},
 "precincts": {"7": [{"id": "7-A", "size": 412, "class": "rural", "off": 0.05},
                     {"id": "7-C", "size": 1930, "class": "halfway", "off": -0.1}]},
 "returns": null, "called": {}, "recounts": []}
```

114 precincts statewide (VT-style town precincts, small-state 150–400 band's
low end for a 60-seat state; and yes, 114). Precinct `1-A` is the pharmacy
lot — the only non-pending ground in the state — always first to report.
`lean` is the hidden per-cycle race lean, the analog of `_strength()`.

### data/statehouse/records.json (append-only, never pruned)

```json
{"assemblies": {"0": {"note": "pre-broadcast history",
   "acts": {"HB-114": {"title": "An Act Making Appropriations for the Completion of the Roundabout at Mile Zero",
            "outcome": "signed", "effect": "the roundabout is still two weeks out"}},
   "lore": ["pharmacy-lot precinct tied; recount held; still tied; filed as pending",
            "Compliance rejected its own registration (blue ink)"]}},
 "acts": {}, "election_history": {}}
```

Pruning story: journal 30 days; bills/calendar kept current + previous
session; older assemblies collapse to `records.json`. Steady state ~800 KB.

## 3. Module breakdown — `src/statehouse/` package

Stdlib-only leaf modules, pure functions against §2 schemas, no imports from
`season.py`/`orchestrator.py`. `members.py` may import `livegame` for the
shared name bank (canon: shares the invented name-bank).

**src/statehouse/calendar.py** (~90 lines)
```python
def build_calendar(assembly: int, session: int, convene: str) -> dict
    # full session calendar; NEVER schedules floor votes Wed/Sat (center_ice);
    # crossover at ~60% of session; sine_die fixed at build time
def day_kind(cal: dict, date: str, wx: dict | None) -> str
    # "floor"|"committee"|"adjourned"|"snow"|"interim"|"election"|...
def legislative_day(cal: dict, date: str) -> int
def phase_of(cal: dict, elections: dict | None, date: str) -> str
```

**src/statehouse/members.py** (~200 lines)
```python
def mint_assembly(assembly: int, canon: dict) -> dict       # members file body
def mint_member(rng, chamber: str, district: int, party: str) -> dict
def stance(m: dict, bill: dict, party_lines: dict, date: str) -> str
    # "yes"|"no"|"undecided" — deterministic: zip·zip_valence + party line ·
    # discipline + maverick coin seeded f"stance:{bill_id}:{m_id}:{date}"
    # + grudge override (never votes with a grudge target's bill)
def whip_count(members: dict, bill: dict, chamber: str, date: str) -> dict
    # {"yes","no","undecided","absent"} — sums to chamber size ALWAYS
def quorum(members: dict, chamber: str, date: str, wx: dict | None) -> dict
    # {"present": n, "needed": 26|5, "ok": bool} — snow slashes attend hard
def zipper_read(members: dict, bill: dict) -> str   # booth color: the axis math
```

**src/statehouse/bills.py** (~230 lines)
```python
STAGES = [...]                                       # §2 lifecycle, exact order
def mint_docket(assembly, session, members, rng) -> dict
    # sponsor caps 7/member (WY rule); topics from the LOCKED topic bank;
    # budget session gates non-budget intros behind a 2/3 vote event
def hazard(bill: dict, cal: dict, date: str) -> dict[str, float]
    # per-stage daily transition probabilities, calibrated to §11; crossover
    # and sine_die walls kill non-exempt bills exactly as VT/DE rules do
def advance(bill, members, committees, cal, date, wx) -> list[dict]
    # seeded f"bill:{assembly}:{session}:{bill_id}:{date}" — per-bill seeds,
    # order-independent, self-healing; returns journal events incl. votes
def governor_action(bill, approval, rng) -> dict     # sign/veto/no-signature; 5-day window
def compliance_sweep(bills, members, date) -> list[dict]
    # daily seeded Notice-of-Deficiency: bumps a bill back one stage or
    # freezes it 1-3 days ("resubmit in black ink") — Compliance as ACTOR
```

**src/statehouse/committees.py** (~120 lines)
```python
def mint_committees(assembly: int, members: dict, rng) -> dict
def week_calendar(committees, bills, cal, date) -> dict
    # which committee hears which bill today; chairs can starve a bill
def committee_action(cmte, bill, members, date) -> dict | None
    # hearing / markup / report ("ought to pass", "as amended",
    # "without recommendation") / table — with a recorded cmte roll call
```

**src/statehouse/approval.py** (~70 lines)
```python
def drift(civ: dict, events: list[dict], date: str) -> dict
    # mean-reverting walk seeded f"appr:{assembly}:{date}": ±0.0-0.8/day,
    # event kicks: pothole filled +1.5, botched filing −2.0, veto override
    # against him −3.0, snow-quorum week −1.0; clamped [18, 74]; streak =
    # consecutive days of same-sign movement (rides broadcasts like a streak)
```

**src/statehouse/elections.py** (~280 lines) — §6.

**src/statehouse/briefs.py** (~200 lines) — §7 broadcast contract.

**src/civicguard.py** (~250 lines, sibling of `scoreguard.py`) — §8.

**src/statehouse/engine.py** (the facade, ~200 lines — the `season.py` mirror)
```python
def tick(date: str) -> None            # fast path + day boundary, §4
def sim_day(civ, sidecars, date) -> list[dict]
def today_sheet(date: str) -> str      # government-show writer's sheet
def election_sheet(date: str, cursor: int) -> dict
def record_air(date: str, lines: list[str], air_at: float) -> None
    # marks journal lines aired — the gate the website reveal reads
def export(path: str = "/var/www/bestairadio/data/statehouse.json") -> None
def context_facts(date: str) -> dict   # civicguard fact table for tonight
```

## 4. The daily `sim_day` algorithm

`tick(date)` every main-loop pass, mirroring hockey §6:

1. **Fast path** (~1 ms): load `civics.json`; if `sim_through == date` →
   throttled `export()` (30 s), return. Sidecars not opened.
2. **Day boundary**, per missing day `d` in `(sim_through, date]` (catch-up
   chunked 45 days/pass):
   a. Load sidecars once per pass (~350 KB total parse).
   b. **Weather**: read `wx-cache.json` (fetched once daily from the same
      Open-Meteo endpoint `spots.py` uses; snow = WMO codes 71–77/85/86 or
      snowfall > 0). Fetch failure → seeded climatology fallback
      `Random(f"wx:{d}")` with monthly snow priors; whatever is used is
      appended to `snow_ledger` and becomes immutable truth.
   c. **Calendar**: `day_kind(cal, d, wx)`. `center_ice` (Wed/Sat) → floor
      adjourned by canon; `snow` during session → `quorum()` per chamber,
      failures journaled ("the House mustered 19 of the 26 required; the
      Speaker glared at the parking lot").
   d. **Committees**: `week_calendar()` then `committee_action()` per
      scheduled bill — hearings, markups, reports with real recorded
      committee roll calls stored in `bill["votes"]`.
   e. **Bills**: for every live bill, `advance()` with per-bill seeds —
      stage transitions honor the calendar (no floor stages on
      committee/adjourned/snow days), crossover and sine-die walls, voice
      vs roll-call selection (~70/30, roll mandatory for revenue and
      overrides), floor votes computed FROM `whip_count()` — the whip math
      and the vote result can never disagree because the vote IS the whip
      count with undecideds broken by the same seeded stance coins.
   f. **Compliance sweep** (seeded `f"oic:{assembly}:{d}"`): 0–2 Notices of
      Deficiency/day.
   g. **Approval**: `approval.drift()` folds the day's events.
   h. **Tracked-thread maintenance**: if the tracked bill dies or becomes
      law, `pick_tracked()` promotes the highest-salience live bill —
      exactly one, always (the one-thread rule enforced in code). Same for
      the tracked race in campaign phase.
   i. **Journal**: write the day's lines + tonight's whip snapshot; prune
      > 30 days.
3. **Phase transitions, air-gated**: sine die → `interim`; election-day
   returns complete → `canvass`; new assembly seats only when
   `rolled_pending` AND the Election Night broadcast's final call has
   `air_at` in the past (the hockey rollover fix, inherited on day one).
4. Save dirty files (atomic + .bak), `export()`.

Cost: ~160 live bills × a dict of hazard draws ≈ 15–40 ms/day boundary;
catch-up after a month ≈ 1.5 s. Self-healing: per-bill, per-stance,
per-precinct seeds mean any lost sidecar re-derives to the identical state —
except the append-only ledgers (journal `aired`, `snow_ledger`, `records`),
which are the small irreplaceable core, backed up by `.bak`.

## 5. Session calendar

Real small-state rhythm on the identity wall-clock mapping:

- **Assembly n, Session 1 (long, VT-shaped)**: convenes a Thursday, runs
  ~18 wall-weeks (~126 days). Committee-heavy weeks 1–6, crossover at
  day ~75 (week 11 — VT's mid-March analog), floor-heavy weeks 12–17,
  end-of-session crunch, **sine die on a Tuesday** (never a game night).
- **Interim** ~45 days: interim joint committees (WY model) generate news
  lines; 0–1 special session slots (governor's call, single subject).
- **Session 2 (short/budget, WY-shaped)**: ~8 weeks (~56 days); non-budget
  bills need the 2/3 introduction gate; crossover at day ~34.
- **Campaign** ~35 days; **Election Night: a Tuesday** (the real first-Tuesday
  rhythm, and Tuesday never collides with Center Ice Wed/Sat); **canvass**
  3–10 days (recounts live here); **organization** ~14 days (Speaker/Pro Tem
  elections — themselves whip-count beats). Full cycle ≈ 9 months.
- **Wed/Sat: the Half-Dome empties for the hockey** (canon, hard rule):
  `build_calendar` marks every Wed/Sat `adjourned:center_ice`; no floor
  vote, hearing, or veto deadline ever lands there. The statehouse shows
  air the OTHER nights, and their sheets can wink at it ("the House stands
  adjourned; the Regrets are in town").
- **Quorum fails when it snows** (canon): snow day + session day →
  `attend` multiplied by 0.55 house / 0.65 senate; below 26/51 or 5/9 the
  chamber does no business, calendared bills slip a day, and the journal
  says so. December–February analog gets 4–9 snow-quorum failures/session
  (§11), each one a free news beat.

## 6. Election engine

**Cycles.** Every assembly ends with a general: all 51 House seats, a
staggered Senate class (3 of 9), the Pothole Commissioner (Bert Demers,
perennially — canon), and every fourth cycle the Governor. Specials fill
vacancies mid-assembly as one-thread undercards.

**Race model.** Hidden per-cycle `lean` per race (the `_strength` analog,
seeded `f"lean:{assembly}:{race}"`), cross-cycle swing generator ±2–6 pts
statewide (grounding B.10) plus district noise ±3–12. Goose Party candidates
run everywhere the docket had goose considerations; the Candidate cannot
consent and does not campaign, which polls surprisingly well.

**Returns generator** (all pure, all seeded):
```python
def build_returns(elections: dict, assembly: int) -> dict
    # per precinct: final tallies (turnout 40-50% general, pharmacy lot 96%),
    # seeded f"returns:{assembly}:{race}:{precinct}"; plus a DROP TIMELINE:
    # cursor-offset ordering — rural precincts 0-35% of the window, mid-size
    # 35-80% (the mirage window), Halfway central-count dumps 80-97% as
    # discrete 3-12 point steps, provisional tail asymptotes at 97-99%
    # ("under review" — pending, forever, like everything here)
def reveal_returns(returns: dict, race: str, cursor: int) -> dict
    # THE ONLY RENDERER (G1 pattern): {"pct_reporting", "tally": {...},
    #  "margin", "leader", "period": 1|2|3|"OT", "callable": bool,
    #  "outstanding": ["Halfway 7-C"], "status"}
    # monotone: pct never decreases, tallies only grow, status never regresses
def call_race(rev: dict, priors: dict) -> str | None
    # trailing candidate's max remaining votes < margin, gated by precinct
    # lean priors (bellwether logic), AND suppressed if projected final
    # margin ≤ 0.5% (the AP recount rule — never call into a recount)
def run_recount(returns: dict, race: str, rng) -> dict
    # margin ≤ 0.5% → automatic; shifts tens of votes; flips leader with
    # p=0.08; the BROADCAST treatment is overtime: the same numbers
    # re-narrated slower, with more ceremony (canon)
```

**Hockey mapping (canon, exact):** period 1 = rural drops (fast, skews
whoever runs up in-person turnout that cycle — the mirage direction is a
seeded per-cycle coin), period 2 = the volatile middle, period 3 = the
Halfway dumps that swing margins in single steps, **recount = OT**, a
weather-delayed precinct = **rain-out** (its drop moves to a makeup slot next
day; the booth treats it exactly like a postponed game), provisional ballots
= "under review," and **the Governor's approval rides the night like a
streak** — a filled pothole is a goal, a botched filing a penalty; the
intermission stat line is his approval tick. Bucky Merle & Sal Tarantella
call it; landslides get called minutes after the pharmacy lot reports, close
races hold "too early to call" for hours, and the pharmacy-lot precinct
itself once tied and went to a recount that is still, officially, pending
(records.json lore, already on the ticker).

## 7. Broadcast contract

All sheets are code-built strings/dicts from sidecars; the LLM narrates,
guards verify. Every number a show may utter appears in a fact table first.

- **`today_sheet(date)`** — the government shows' writer's sheet:
  `TRACKED BILL:` (number, title, exact stage name, today's history line,
  the whip: "24 yes, 17 no, 8 undecided, 2 absent — 26 passes it"),
  `ZIPPER READ:` (axis math in words), `COMMITTEE CALENDAR:` (today's
  hearings), `APPROVAL:` ("Bouchard at 52, up 2 on the pothole"),
  `AROUND THE DOME:` (3 one-line digests — the other 59 seats, light on
  air), `FEUD:` (tracked feud beat), plus the standing instruction block:
  *outcomes that have not happened do not exist; you never predict a vote
  result, only the whip count.*
- **News desk lines** — `data/statehouse/news-lines.json`, same shape as the
  league's news wire: 2–4 clean headlines/day for Frequency News and the
  morning shows ("HB-131 survives crossover; Merging still merging").
- **Election Night takeover** — `election_sheet(date, cursor)` per beat:
  the reveal snapshot for the tracked race + undercards, `CALLABLE:` flags
  (the booth may only "call it" when `call_race()` has), period framing,
  rain-out/recount status, the approval streak line. The cursor is
  wall-anchored to the takeover's first air timestamp — booth, sheets, and
  website share one clock, no cross-feed contradictions (G1 discipline).
- **Website statehouse page** — `export()` writes `statehouse.json`:
  seat table, tracked bill status, approval, aired journal lines only,
  election-night reveal at the same cursor. Air-gated exactly like
  `league.json`: **the page never spoils what hasn't been narrated on air**
  (journal lines gate on `aired`; election reveals gate on the takeover's
  air clock; stage facts older than 24 h are fair game as public record).
- **Truth-guard fact tables** — `context_facts(date)` returns the civicguard
  input: `bills` (id → stage, last action, votes), `whips` (today's
  snapshot), `tallies_ok` (every legal pair: whip pairs, vote yeas/nays,
  committee rolls, revealed precinct tallies/margins/percent-reporting),
  `names_ok` (members + officials + candidates on today's sheets),
  `approval` (today's value ±1), `called` (races legally callable),
  `stages` (id → allowed stage vocabulary).

## 8. Guards — the civicguard spec

`src/civicguard.py`, a leaf sibling of `scoreguard.py`, same prime directive:
contradicting lines are REPLACED (never cut), missing mandatory facts are
INJECTED, and no correct line is ever falsely touched. Reuses scoreguard's
`_norm` (number-words → digits, "24 to 17" → "24-17") and the modal skip
(predictions/hypotheticals are legal banter).

What it must catch:

1. **Invented tallies.** Any digit pair in vote context ("passed 31-19",
   "the committee went 7 to 4") must appear in `tallies_ok`; a whip quote
   must match today's snapshot AND its components must sum to the chamber
   (51/9) or committee size — a tally that doesn't add up is replaced with
   the fact-table tally.
2. **Invented margins.** "up by 12", "a 3-point lead", "62% reporting" in
   election context must match the reveal at the current cursor (±1 on
   percentages); premature precision about outstanding precincts is
   replaced with the sheet's `outstanding` phrasing.
3. **Invented committee/floor outcomes.** Outcome verbs bound to a bill
   token (`reported`, `tabled`, `killed`, `passed`, `signed`, `vetoed`,
   `overridden`, `died in committee`) must match the bill's stage table; a
   bill may never be narrated at a stage ahead of code, and a stage the
   code says happened tonight is INJECTED if the beat forgot it.
4. **Premature calls.** "We can call District 7" with no `call_race()`
   verdict → replaced with "still too early to call District 7."
5. **Phantom bill numbers and people.** `HB-\d+`/`SB-\d+` tokens must exist
   in the docket; names resolve against `names_ok` via nameguard's
   `_nearest_surname` machinery (shared name bank keeps `pool_ok` valid).
6. **Approval drift.** Any "approval at N" must match today ±1.
7. **Sum invariants as a hard test, not just runtime**: per-sheet self-guard
   CI (G3 mirror) — every briefs test renders the sheet, builds facts, runs
   `enforce_civics` over synthetic booth lines quoting it: zero
   replacements or the test fails; plus a fuzzer that mutates one digit in
   each quoted tally and asserts exactly that line gets replaced.

## 9. Migration / bootstrap

Nothing has aired except the `web/government.html` canon page — so this is a
bootstrap, not a migration, but the canon still gates (G4/G6 mirrors):

1. `scripts/bootstrap_civics.py` (idempotent, gate OFF): extract
   `canon.json` from `station/wending-bible.md` + `government.html` facts:
   HB-114 signed into law (seeded into `records.json` assembly 0 as the
   roundabout appropriation — the roundabout is still two weeks out);
   the pharmacy-lot precinct's tied-recount lore; Compliance's blue-ink
   self-rejection; officials Bouchard/Pelletier/Demers; 51+9 seats; the
   seven parties; motto and mode.
2. Mint Assembly 1: members (name bank), seat split per §2 — **no majority
   anywhere**; the Goose Party's 6 House seats decide bills, sold only for
   goose-related considerations; the Roundabout Party is the swing bloc.
   Seat numbers are bootstrap-seeded, not canon-locked — verify only checks
   totals (51/9) and that all six seat-holding parties hold seats.
3. Mint committees, Session 1 calendar (convene aligned to the government
   shows' launch date), docket (~200 bills incl. HB-115+ continuing the
   canon numbering past HB-114).
4. `scripts/verify_civics.py`: canon-diff artifact
   (`data/statehouse/canon-diff.txt`) MUST be empty — every government.html
   fact present and uncontradicted; whip sums; calendar invariants (no
   floor business Wed/Sat, crossover < sine die); calibration smoke
   (§11, 5 sessions, wide bands); dry-run `tick` over 60 synthetic days on
   a copied state dir; golden `today_sheet` render + civicguard round-trip.
   Writes `data/statehouse/VERIFIED` (sidecar hash).
5. Gate: `engine._on()` requires `data/statehouse/ENABLED` + VERIFIED +
   hash match. Fallback: delete ENABLED — the government shows fall back to
   pure-canon color (the bible) with no sim numbers, which is exactly what
   they'd air today. Election engine ships dark behind
   `ELECTION-ENABLED` (Gate 2), months away, like the playoff modules.

## 10. Build order (parallelizable pure components)

| # | Component | Deliverable | Test strategy |
|---|-----------|-------------|---------------|
| A | `calendar.py` | build/day_kind/phase | property: no floor Wed/Sat over 20 seeded sessions; crossover/sine-die ordering; snow ledger append-only |
| B | `members.py` | mint/stance/whip/quorum | golden mint (officials pinned); whip sums ≡ 51/9 over 10k seeded bills; stance determinism; quorum bands under snow |
| C | `bills.py` + `committees.py` | docket/hazard/advance/actions | 50-session Monte Carlo vs §11 envelopes; per-bill seed self-heal (delete sidecar → identical re-derive); crossover wall kills exactly the non-exempt |
| D | `approval.py` | drift | 10k-day walk stays in [18,74], event kicks visible, streak math |
| E | `elections.py` | returns/reveal/call/recount | reveal monotonicity; tallies sum to turnout; call never precedes mathematical elimination; recount flips ≈8%; sigmoid shape vs B.3 |
| F | `briefs.py` + `civicguard.py` | sheets + guard | G3 self-guard CI; digit-mutation fuzzer; golden renders |
| G | `engine.py` + bootstrap + verify + export | integration | main loop integrates each component the hour it lands against these frozen schemas (hockey-final rule); offline 60-day dry-run |

A–F have zero interdependency beyond this document's schemas. Rust note: the
returns generator and hazard model are bounded, stable, deterministic — Rust
candidates per owner preference — but v1 ships Python to share `livegame`
name-bank and the guard ecosystem; revisit post-Gate-2.

## 11. Calibration — `scripts/calibrate_civics.py --sessions 50`

Envelopes from `docs/sim-grounding/civics-grounding.md`, scaled to 60 seats:

- Long session: **170–230 introduced**, short/budget **80–140** (2/3 intro
  gate visible in volume); assembly total 260–360.
- **Committee death 55–70%** of introduced (dominant mortality, weighted to
  bills with no hearing in the first 40% of session); Merging's in-tray
  monotonically grows (canon: still merging).
- Floor failure **< 5%** of calendared bills; enactment **22–30%** long,
  **40–55%** short; voice/roll split **65–75 / 25–35**; conference on
  **< 10%** of enacted; veto **< 5%** of transmitted, override success
  **< 20%** of attempts at the true 2/3-of-elected bar (34/51 + 6/9).
- Whip invariant: every emitted whip/vote sums to chamber size — hard
  assert, any violation fails the run.
- Session length: long 120–132 days, short 52–60; snow-quorum failures 4–9
  per winter session; special sessions 0–2/assembly.
- Approval: mean 44–54, min > 18, max < 74, 2–5 streaks of length ≥ 4 per
  session.
- Elections: turnout 40–50% (pharmacy lot 94–98%); reveal curve hits
  ~10%/+1h, ~55%/+2h, ~90%/+4h scaled to the takeover window; mirage 1–4
  pts typical, ≤ 10 cap; recounts in 3–8% of races, flips ≤ 10% of
  recounts; landslide calls < 15 min, close calls > 2 h.
- Shipped as `tests/test_civics_calibration.py` (slow-marked) so constant
  drift re-proves the envelopes; smoke subset (5 sessions) gates Gate 1,
  full run gates Gate 2.

## 12. Risk register

| # | Risk | Mitigation |
|---|------|------------|
| 1 | Real-politics drift (a bill reads as a real-world issue) | Topic bank is closed and canon-locked (potholes, merging, geese, drainage, ladders, ink); civicguard carries a banned-term list; G/PG guardrail wins over any premise; owner review of the topic bank before Gate 1 |
| 2 | Civic numbers in prose evade the guard (wordier than scores) | civicguard reuses scoreguard's proven `_norm`; restricted tally vocabulary mandated in sheets; G3 self-guard CI + digit-mutation fuzzer before anything airs |
| 3 | Election Night takeover is a new live format under pressure | Reveal-cursor architecture is the already-proven G1 pattern; full synthetic night dry-run required by verify; recount = re-narration, never a re-sim; Gate 2 is months out |
| 4 | Weather feed outage flips quorum history | Daily cache + append-only `snow_ledger` (observed weather is immutable); seeded climatology fallback; quorum never recomputed retroactively |
| 5 | One-thread rule erodes (booth wanders across 60 seats) | `tracked` pointer is code-owned; sheets expose depth only for tracked threads; `names_ok` limited to the sheet's names, so off-thread members literally can't be quoted |
| 6 | Canon contradiction (HB-114, ticker facts, party mechanics) | `canon.json` + empty `canon-diff.txt` required by verify; VERIFIED hash gate (a human can't skip it at 2am); bible regressions fail CI |
