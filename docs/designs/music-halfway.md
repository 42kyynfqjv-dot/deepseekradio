# Music + the Halfway Hot 10 — Design (Track C)

Lens (inherited from the hockey doc): smallest schema, fewest moving parts, every
component shippable and testable in isolation, fallback trivially safe, generation
OFF-box, and — the load-bearing new axis for this track — **nothing airs on the
monetized stream that we might ever have to retract.** Aired facts are canon
forever, so the licensing verdict governs the whole design, not just a footnote.

## 1. Feasibility verdict (from the research)

Two research findings pull in opposite directions and the tie-break is the brief's
hard constraint that output be *safe for a public monetized stream*:

- **Best quality-per-effort with vocals** is ACE-Step 1.5 (MIT, low VRAM, fast).
- **Best license/provenance for monetized broadcast** is Stable Audio Open **1.0** —
  but it is **instrumental/SFX only, no singing, ever.**

The vocal-capable models (ACE-Step, YuE) carry undisclosed "internet-mined" training
data whose fact pattern is *exactly* what Sony is litigating against Suno/Udio, with a
pivotal fair-use summary-judgment ruling expected **summer 2026** (a July hearing).
MusicGen is a hard no on license grounds alone (weights are CC-BY-NC 4.0 — commercial
broadcast is forbidden regardless of data cleanliness). A station whose aired facts
are permanent canon cannot build a music identity on audio it may have to pull.

**Verdict: ship the instrumental path. Vocals are deferred, not designed-in.**

- **Primary broadcast catalog = Stable Audio Open 1.0, instrumental.** Clean
  provenance (CC0/CC-BY Freesound + FMA training data), commercial use licensed by
  default under the Stability Community License's **$1M/yr revenue cap** (a small
  station qualifies with enormous headroom), output ownership granted. Obligations we
  accept: display "Powered by Stability AI" on the about page, register commercial use
  once, and re-check the revenue threshold annually. **Not** Stable Audio 3.0 — its
  AudioSparx training data is under active suit (*Anders v. Stability AI*, Dec 2025).
- **Vocals are carried by fiction, not by sung audio.** This is a feature, not a
  concession: Halfway's musicians are *instrumental acts* (a one-note jazz recluse, a
  surf band that only goes in circles, an ambient duo scoring tarp season). Where a
  track "has a hook," the hook is a real instrumental phrase; where it "has words,"
  the words live in the chart copy and the host's narration, never in a vocal stem.
  The deadpan universe absorbs this perfectly — nobody in Halfway can finish anything,
  least of all a lyric.
- **A vocal slot is reserved in the schema behind a flag** (`catalog.tracks[*].vocal`,
  default false) so that *if* Sony v. Suno/Udio resolves in a way that clears an
  Apache-licensed model (ACE-Step/YuE) for commercial air, we can drop vocal masters
  into existing plumbing without a reshape. We design the door; we do not walk
  through it now.

### Hardware plan (generation is OFF-box)

The 2 vCPU / 4 GB box **never runs a diffusion model** — same discipline as hockey
sims and Kokoro voice-minting. Generation runs once, on a dev machine:

- **GPU need:** Stable Audio Open 1.0/1.5 wants **~12 GB VRAM** (a single consumer
  card — RTX 3060 12 GB, 4070, or better). No card handy → rent one cloud-GPU hour;
  the whole catalog is one afternoon's batch. CPU-only is impractical for diffusion
  and not supported here.
- **Economics:** effectively **one-time**. ~$0 on an owned GPU; a few dollars of cloud
  time otherwise. Ongoing cost is a small batch of new tracks per chart "season" to
  feed debuts — cheap, batched, off-box. No per-generation royalty (unlike Suno/Udio
  SaaS), no monthly spend, mirroring the Kokoro "$4 once, $0/mo" pattern.
- **The box only plays delivered WAVs.** The generation scripts refuse to run if they
  detect the box environment (guard in §3), so this invariant can't rot.

## 2. Catalog design (Halfway artists as city canon)

A dedicated **artist name bank, disjoint from every existing bank** (verified against
`livegame.FIRST_NAMES`/`LAST_NAMES`, the ~40 sponsors, `personas/`, and the statehouse
officials). Place-references to locked Wending canon (Mile Zero, Exit 4, Tarp Season,
the Sieve) are deliberate in-universe flavor and are *places*, not name-bank entries,
so they don't collide. Personal names of solo acts avoid all four banks entirely.

Fourteen acts, all instrumental, each one a small Halfway joke:

| id | Act | Genre | The gag |
|----|-----|-------|---------|
| a01 | Merrill Sackville | one-note jazz | The recluse finally records: one sustained note, an album's worth |
| a02 | The Mile Zero Roundabouts | surf-rock | Every track just goes around; no bridge, ever |
| a03 | Tarp Season | ambient/drone | Scores the Half-Dome open to the winter sky |
| a04 | Fixture Twelve | synthwave | Flickers on the downbeat, under a maintenance ticket |
| a05 | The Merge | math-rock | Two riffs in two lanes resolving to one, late |
| a06 | Window Four | lounge/bossa | Closes at 4:30 sharp, mid-phrase |
| a07 | Quorum | post-rock | Only records on days it doesn't snow |
| a08 | The Halyard | slowcore | Everything played at half-mast |
| a09 | Provisional Wave | synthpop (inst.) | Never finishes a chorus; it's still pending |
| a10 | Exit 4 | post-rock | An offramp that was never built, in six movements |
| a11 | Odette Vanterpool Trio | chamber jazz | Plays the Boreal Lantern; unbearably tasteful |
| a12 | The Pharmacy Lot | smooth jazz | The goose's backing band; the only tight act in the state |
| a13 | Half-Duplex | folk duo | Two players feuding over a shared driveway of a song |
| a14 | Percival Ashgrove | library music | Faceless production cues for a public-access channel |

Additional fresh names available for expansion (all bank-checked): Lonnie Prewitt,
Delphine Marlowe, Hollis Quint, Cass Underhill, Winnie Calloway, Silas Yarrow, Roman
Ferro, Marguerite Deschamps.

### catalog.json (source of truth, off-box authored, deployed read-only to box)

```json
{
  "schema": 1,
  "artists": {
    "a01": {"name": "Merrill Sackville", "act": "solo", "genre": "one-note jazz",
            "blurb": "Recorded in one take because there is only one note.",
            "aired": true}
  },
  "tracks": {
    "t001": {"title": "Sustain", "artist": "a01", "genre": "one-note jazz",
             "bpm": 72, "seconds": 44, "released": "2026-06-15",
             "wav": "music/t001.wav", "loudness": -16.0, "peak_dbtp": -1.6,
             "vocal": false, "eligible_from": "2026-07-10", "aired": true}
  }
}
```

- ~40–60 tracks across the 14 acts (2–5 each), each a **discrete instrumental** ≤47 s
  (Stable Audio Open 1.0's hard stereo cap) — long enough for a countdown hook and a
  loopable bed, short enough to batch fast and to respect a talk-first clock.
- `loudness`/`peak_dbtp` are written by the mastering pass (§3), not by hand — the
  chart never *needs* them, but the airplay layer does.
- `eligible_from` is the earliest chart week a track may debut, letting the batch
  seed future debuts without them all landing at once.
- `vocal` is the reserved flag from §1 — always `false` in the shipping catalog.

## 3. Generation pipeline (OFF-box → house WAVs)

Three scripts under `scripts/`, run on the dev machine, plus one deploy. All pure
batch, idempotent, re-runnable. **The box runs none of them.**

**`scripts/music_generate.py`** (dev GPU only) — reads a `music_spec.yaml` (artists,
tracks, per-track text prompts + seeds), loads Stable Audio Open **1.0** via
`diffusers`, generates each track to a 44.1 kHz stereo master under `masters/`.
Deterministic per-track seed so a re-run reproduces the catalog. First lines:

```python
if Path("/opt/kaos").exists():          # never generate on the box
    raise SystemExit("generation is OFF-box only; run on the dev machine")
```

Prompts are style-only (genre, instrumentation, mood, bpm) — no artist/style names of
real musicians, keeping the provenance story clean end to end.

**`scripts/music_master.py`** (stdlib + ffmpeg, no GPU) — the loudness + format pass:

- Measure/normalize each master to **integrated −16 LUFS, true-peak ≤ −1.5 dBTP**
  with ffmpeg `loudnorm` (a CPU trap *on the box* per player.sh's own note, but fine
  off-box in batch). This sits a hair below the talk level so instrumental beds and
  hooks don't shove the speech-tuned broadcast chain (§5).
- Downmix + resample to the **house WAV spec the box already speaks: 24000 Hz, mono,
  s16le PCM WAV** (matches `buffer.py _SAMPLE_RATE = 24000` and every `player.sh`
  ffmpeg `-ar 24000 -ac 1`). Trim silence; write `music/<id>.wav`.
- For tracks tagged as bed-capable, also render a seamless **loop** version to
  `beds/music/<id>.wav`.
- Write measured `loudness`/`peak_dbtp` back into `catalog.json`. 44.1 k stereo
  masters are archived off-box; the box gets only house-format files.

**`scripts/music_deploy.sh`** — rsync `music/`, `beds/music/`, and `catalog.json` to
the box: `/opt/kaos/music/`, `/opt/kaos/beds/music/`, `/opt/kaos/app/`. Atomic
(stage to a tmp dir, then move). This is the *only* thing that touches the box, and it
only adds files the streamer plays — never code on the air path.

Batch: 40–60 clips × a few seconds–minutes each on a 12 GB card = one session. A
future "new debuts" batch reuses the same three scripts against an extended spec.

## 4. The code-owned HALFWAY HOT 10 (chart sim)

Mirrors `src/league/stats.py`: code owns every number, the LLM narrates, a guard
verifies. Pure functions of `(catalog, week, seed)` — **derive-don't-store**; a lost
chart file re-derives from the seed, exactly like off-air hockey box scores.

New package `src/music/` (stdlib-only):

```python
# src/music/catalog.py
def load(root: Path) -> dict                      # parse+validate catalog.json
def eligible(catalog: dict, week: str) -> list[str]   # tids released & not retired

# src/music/chart.py  (the stats.py analogue)
def score_week(catalog, tid, week, seed) -> int   # blended points, deterministic
def roll_week(prev: dict, catalog: dict, week: str, seed: str) -> dict  # new chart
def deltas(chart: dict) -> dict                   # debuts/droppers/bullet/mover/...
def narrate(chart: dict) -> list[str]             # SCOREBOARD-register fact lines
```

### hot10-s{n}.json (chart state; per-season shard, pruned like box scores)

```json
{
  "schema": 1, "week": "2026-07-10", "season": 1,
  "chart": [
    {"tid": "t007", "rank": 1, "last": 2, "peak": 1, "weeks": 6,
     "pts": 9820, "bullet": true, "debut": false}
  ],
  "hot_shot": "t011",
  "droppers": ["t002"],
  "gainer": "t007",
  "retired": ["t002"],
  "history": {"t007": [4100, 5200, 6800, 8100, 9010, 9820]}
}
```

`chart` is exactly 10 rows sorted by `pts` desc. `history` keeps a short tail per live
track for the "biggest jump" and trajectory copy; retired tids drop out.

### Weekly movement rules (honoring the researched conventions)

**Cadence.** One chart per week, **Friday-dated** (the Billboard Fri→Thu tracking
window). The countdown airs the following weekend (§5). Wall week = chart week, 1:1,
identity mapping — same choice, and same justification, as the hockey calendar: zero
translation layer, date-seeding stays honest.

**Blended score (streams-dominant, faithful to Billboard's weighting).** For each
eligible track, `score_week` derives three seeded components from a hidden per-track
**heat** trajectory (a life-cycle curve: rises after `released`, peaks, decays, times
its own `intrinsic quality` q∈[0,1] fixed per track from the seed):

```
pts = round( SPIN_W * spins       # airplay, audience-weighted — dominant
           + STREAM_W * streams    # dominant
           + SALES_W * sales )     # down-weighted (mirror the "divisor 10" era)
```

with `STREAM_W ≈ SPIN_W ≫ SALES_W` so sales are materially the smallest lever, per
the research. Everything is a pure function of `(tid, week, seed)` — no dependency on
real play logs (the chart self-heals against state loss). *Optional later:* nudge
`spins` by the box's actual overnight play counts to make airplay feel connected;
primary path stays synthetic and deterministic.

**Rank & bullet.** Sort by `pts`, take the top 10. `bullet=True` for any title with a
positive week-over-week point gain (upward momentum — the Billboard bullet), computed
against `history`. The single greatest point-gainer is flagged `gainer` (the "Greatest
Gainer" award), distinct from the bullet set.

**Hot Shot Debut.** `hot_shot` = the highest-ranked track that was *not* on last
week's chart. Its row carries `debut=True`, `last=0`.

**Droppers.** Tracks on last week's chart but off this week's → `droppers`, narrated
as farewells (the AT40 convention).

**Recurrent retirement (rank+tenure pairs, scaled to a 10-slot chart on a fast
clock).** A track retires to "gold" (removed from `eligible`, cannot re-enter) when it
meets *any* threshold — mirroring Billboard's tiered recurrent rules, not a single
"X weeks and out":

- `weeks ≥ 8` and `rank ≥ 6` (fell to the back half after two months), or
- `weeks ≥ 12` and `rank ≥ 3`, or
- `weeks ≥ 16` regardless of rank.

Retirement forces turnover and keeps debut slots open — the numbers are constants at
the top of `chart.py`, tuned by the §8 calibration, not magic.

**Determinism & narratability.** `seed = f"hot10:{season}:{week}"`. The full season's
chart is reproducible from the catalog + seed alone. Every countdown fact — rank, last
week, peak, weeks-on, debut/bullet, biggest jump, longest-charting survivor — is a
field or a pure `deltas()`/`narrate()` output, never a number the host computes.

## 5. Airplay integration (talk-first, never a format change)

The station is talk 24/7 and stays that way. Music enters through exactly three doors,
each additive and each with an instant fallback:

**(a) A weekly countdown show — "The Halfway Hot 10" — as a TAKEOVER** (the proven
Center Ice / Election Night machinery, reused not replaced). One ~1-hour block, once a
week, **Sunday evening** (the bible's "lighter, looser" day; deliberately clear of the
Wed/Sat hockey windows). Counts **#10 → #1** straight from the code-owned chart, AT40
style: minimal talk, quick turnover, each position introduced with a hook of the
track, and the *deltas are the content* — the dropper callout, the biggest jump, the
longest-charting survivor, the Hot Shot Debut, one "dedication"-style narrative
interstitial per half. Structural ad breaks (like Center Ice), not the every-4-parts
cadence. Host: reuse an existing warm voice rather than sprawl a new persona — Vivian
(late-night companion) fits a Sunday-night countdown; owner may instead mint a
dedicated countdown persona. `orchestrator.run_hot10()` builds the beats from the
chart, mirroring `run_center_ice()`.

**(b) Upgraded beds.** The Stable Audio instrumental loops replace/augment the
synthesized `sfx.py` beds. Extend `player.sh` `bed_for()` with additive cases
(`*halfway-hot-10* → beds/music/*`, plus optional per-show music beds); missing beds
degrade gracefully exactly as today. This is the only strictly-required `player.sh`
change and it is one `case` arm.

**(c) Optional overnight jukebox.** A low-rotation music filler that feeds full tracks
into the reserve pool (or a dedicated `music-queue`) in the small hours *between*
existing overnight talk shows — music exists without displacing a single talk slot.
Ships behind its own flag, last; not needed for the countdown to launch.

### player.sh / schedule touchpoints

- **schedule.yaml:** add a day-gated `halfway_hot_10` block (Sunday window, cast,
  `ad_cadence: structural`, `news: false`) — same shape as `center_ice`.
- **web/schedule.js:** append one entry to `F.TAKEOVERS` (`days:["Sunday"]`, window,
  hook, who). The now/next readout, `web/index.html`, and `center-ice.html` are
  already takeover-aware and splice it in automatically.
- **orchestrator.py:** add `run_hot10(daypart, config, schedule)` beside
  `run_center_ice` (dispatch already branches by daypart id at line ~256).
- **player.sh:** the additive `bed_for()` arm; the countdown's segment WAVs are
  pre-mixed at production time (host VO + hook), so the streamer plays them as ordinary
  segments — no play-path change. `/opt/kaos/music/` holds full tracks for the
  optional jukebox only.
- **Instant fallback:** remove the takeover entry (schedule reverts to the base
  lineup, exactly like pulling Center Ice); delete the beds (graceful degrade). The
  chart engine and catalog sit inert on disk, harming nothing.

## 6. Guard & prompt contracts (chart facts are code-owned)

- **`src/music/chartguard.py`** — the `scoreguard` analogue. `enforce_chart(lines,
  chart) -> lines`: scans the host's narration and **replaces any quoted rank,
  position, weeks-on-chart, peak, or move that disagrees with the code-owned chart.**
  The LLM adds color and jokes; it can never invent a #1, a debut, or a jump.
- **SCOREBOARD-register prompt block.** `narrate(chart)` emits the authoritative facts
  in the same "do-not-alter" register the hockey booth uses:
  `HOT 10 — WEEK OF 2026-07-10 (authoritative, do not change any number):`
  `1. Sustain — Merrill Sackville (LW 2, 6 wks, peak 1) ▲bullet · Greatest Gainer` …
  plus explicit `HOT SHOT DEBUT`, `DROPPED OUT`, `BIGGEST JUMP`, `LONGEST ON CHART`
  lines. The host narrates *around* this block, never over it.
- **Names.** Artist and track titles from the catalog feed a `pool_ok` (via
  `nameguard` or a small `chartguard` pool) so the host can't misname an act — same
  mechanism that keeps player surnames honest.
- **Air-gating (aired = canon forever).** The website chart page and any "now playing"
  never surface a chart week that hasn't aired on the countdown — mirroring hockey
  `export()` air-gating. Once a week airs, its #1 is permanent lore; the chart engine
  may never retro-edit an aired week (the guard treats aired weeks as read-only, like
  stored slates being canon over seeds).
- **G/PG.** Instrumental audio is inherently clean; catalog blurbs and host copy
  inherit the station guardrail. No lyric surface means no lyric-content risk — a quiet
  bonus of the instrumental path.

## 7. Build order + risk register

Every component is a pure module against the §2/§4 schemas; A–C have no
interdependency beyond those schemas, D is the off-box batch, E–F integrate.

| # | Component | Deliverable | Test strategy |
|---|-----------|-------------|---------------|
| A | `catalog.py` | load/validate, `eligible` | Schema round-trip; names disjoint from all four banks (automated set-difference test); `eligible` honors `released`/`retired`/`eligible_from`. |
| B | `chart.py` | `score_week`, `roll_week`, `deltas`, `narrate` | Seeded golden chart for a fixed week; determinism (same seed → byte-identical chart); calibration (§8). |
| C | `chartguard.py` + prompt block | `enforce_chart`, SCOREBOARD render | Round-trip: run `enforce_chart` on narration quoting each row → zero surviving invented facts; golden render of the block. |
| D | `music_generate/master/deploy` | the WAV catalog | One-time batch on dev GPU; master pass asserts 24 kHz/mono/s16le + −16 LUFS/−1.5 dBTP; box-guard refuses to generate on `/opt/kaos`. |
| E | `run_hot10()` + schedule/JS + web air-gate | the countdown takeover | Beat-builder golden test; takeover splices into `F.effective`; air-gated chart never shows an unaired week. |
| F | beds upgrade + optional jukebox | `bed_for()` arm, music queue | Bed ducks under dialogue on the real chain; jukebox behind its own flag; fallback = remove takeover/beds. |

### Calibration (§8, referenced above)

`scripts/calibrate_chart.py --weeks 104` sims two seasons of weekly rolls and asserts
the turnover envelopes so the numbers stay believable and the chart never stagnates:
**#1 changes every 2–5 weeks; a debut most weeks (≥0.7 debuts/wk); average tenure at
retirement 8–14 weeks; no track charts >16 weeks; bullets 3–6 of the 10 rows in a
typical week; every act reaches the chart at least once per season.** Output is a
pass/fail table; a pytest (`tests/test_chart_calibration.py`) re-proves it on any
constant change — same drift-protection discipline as the hockey calibration.

### Risk register

| # | Risk | Mitigation |
|---|------|------------|
| 1 | Vocal-model licensing never clears (or Sony ruling is adverse) | Instrumental is the *shipping* default, not a fallback; vocals gated behind `vocal` flag, never aired until legal is unambiguous. Aired-forever canon protected. |
| 2 | Stability Community License $1M revenue cap crossed | Add "Powered by Stability AI" to the about page now; register commercial use; monitor sponsor revenue annually; tiny station has vast headroom, and enterprise license or model-switch is the ceiling remedy. |
| 3 | Instrumental coherence weak at ≤47 s | Over-generate, curate the best, reject the rest; loop short beds; batch is cheap to re-run. |
| 4 | Loudness pumps under the speech-tuned broadcast chain | Pre-normalize to −16 LUFS/−1.5 dBTP off-box (below talk level); verify a bed under the real `CHAIN` before deploy. |
| 5 | Chart stagnates / a track squats forever | Recurrent-retirement thresholds + release cadence tuned by §8 calibration; pytest guards the envelopes. |
| 6 | Music erodes the talk-first identity | Music confined to beds + one weekly countdown + optional overnight; never displaces a talk show; instant fallback = drop the takeover, like pulling Center Ice. |
| 7 | Host invents a chart fact on air | `chartguard.enforce_chart` mandatory on every countdown line; SCOREBOARD-register prompt; C's round-trip test gates the takeover going live. |
| 8 | Box drifts into running the model | Generation scripts hard-refuse on `/opt/kaos`; deploy only ships WAVs + catalog; the box's only music code is one additive `bed_for()` arm. |
| 9 | Retro-edit of an aired chart week | Guard treats aired weeks as read-only; air-gated site never shows unaired weeks; aired #1 is permanent lore. |
```
