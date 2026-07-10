# NHL Broadcast Rundown & Presentation Grounding (Radio-First)

*Grounding document for simulator engine designers and implementers.*

## 1. Pregame Show Timing

- **Radio standard**: 15 minutes on-air before puck drop is the baseline pregame across most team radio networks (e.g., Capitals, Blue Jackets radio pages). [nhl.com/capitals/multimedia/caps-radio](https://www.nhl.com/capitals/multimedia/caps-radio)
- **Extended team pregame shows** (e.g., "Caps GameDay") add a full pre-show hour of interviews/lineup notes ahead of the on-air 15-min segment.
- **National TV pregame**: ABC/ESPN runs 20 minutes for primetime games, 30 minutes for non-primetime; ESPN's digital-only "The Drop" is a fixed 30-minute show. [en.wikipedia.org/wiki/NHL_on_ABC](https://en.wikipedia.org/wiki/NHL_on_ABC)
- **TNT "NHL on TNT Face Off"**: 30 minutes standard, expanding to 90 minutes for marquee/on-location broadcasts (season openers, playoffs). Format = host (Liam McHugh) + rotating 3-4 person analyst panel. [en.wikipedia.org/wiki/NHL_on_TNT](https://en.wikipedia.org/wiki/NHL_on_TNT)
- **Typical 15-30 min radio/TV pregame content blocks**:
  - Storylines/matchup framing: ~4-6 min
  - Lineups, scratches, projected line combos: ~3-5 min
  - Starting goalie confirmation: short standalone beat (~30-60 sec), delivered as breaking info once confirmed by team ~60 min pregame (goalie warmups begin ~20 min before puck drop, giving broadcasts a hard confirmation point)
  - Ice-level reporter hit(s): 1-2 hits of ~60-90 sec each, typically pre-warmups and just before puck drop
  - Sponsor billboard/open: 15-30 sec cold open + branded segment tags throughout

## 2. In-Game Radio Play-by-Play Conventions

- **Two-person booth roles**: play-by-play announcer carries ~70-80% of talk time describing puck location/action continuously (radio requires far more verbal density than TV, since there's no picture); color analyst fills stoppages, whistles, TV timeouts, and between-play analysis (strategy, injury notes, historical stats). [en.wikipedia.org/wiki/Color_commentator](https://en.wikipedia.org/wiki/Color_commentator)
- **Time-and-score discipline**: industry guidance treats "give the time and score" as a top must-do habit — restate score every 60-90 seconds of live action, minimum, and always immediately after: a goal, a penalty call, a commercial-break return, a period start, and every booth re-entry after a break in play. [sportscasterlife.com/habits-of-highly-successful-announcers](https://www.sportscasterlife.com/habits-of-highly-successful-announcers/)
- **Out-of-town scoreboard cut-ins**: delivered at natural stoppages — end of period, TV timeouts (~2/period), goal-horn lulls — typically 1-2 score-update reads per period, expanding on playoff-race-relevant nights.
- **Penalty announcement (radio call)**: play-by-play calls the penalty in real time ("[Player] goes to the box for [infraction], two minutes"), then color analyst adds context (good/bad call, effect on the PK). PA/arena wording mirrors organized-hockey standard: *"[Team] penalty to number [#], [Name], two minutes for [infraction], at [time]."* [PAHL Announcements Guide PDF](https://cdn3.sportngin.com/attachments/document/34c7-3018306/PAHL2024AnnouncementsGuide.pdf)
- **"Last minute of play" call**: standard across hockey levels — PA/broadcast flags the 60-second mark of each period ("One minute remaining in the period") as one of only a small handful of announcements permitted during live play (goals, penalties, 1-minute warning). [PAHL guide](https://cdn3.sportngin.com/attachments/document/34c7-3018306/PAHL2024AnnouncementsGuide.pdf)
- **Economy of language**: professional standard is zero filler ("uh," "um," "you know"), tight sentence construction, description-first/opinion-second ordering. [americansportscastersonline.com radio tips](http://www.americansportscastersonline.com/radiosportscastingtips.html)

## 3. Intermission Structure

- **Length**: NHL rulebook mandates 18 minutes intermission for regular-season games league-wide; primetime/TV-featured games commonly run 17 minutes to fit broadcast windows. [hockeybydesign.com](https://hockeybydesign.com/2026/03/how-long-is-a-hockey-intermission/) / [thestadiumsguide.com/nhl-intermissions](https://www.thestadiumsguide.com/nhl/nhl-intermissions/)
- **Typical 17-18 min apportionment** (broadcast convention, TV and radio-adapted):
  - Period recap/highlights: ~3-4 min
  - Studio/booth panel discussion (2-3 talking heads or booth analyst): ~4-5 min
  - Around-the-league scoreboard update: ~1-2 min
  - Walk-off/between-periods soundbite (TV) or reporter update (radio): ~1-2 min
  - Sponsor billboards/ad inventory: multiple :15-:30 reads totaling ~5-7 min of the break
  - Ice resurfacing (Zamboni) occupies the physical 15-17 min ice-clean window the broadcast break is built around

## 4. Postgame Structure

- **Standard postgame broadcast window**: 30 minutes after the final horn (per team radio network broadcast-length descriptions). [nhl.com/capitals radio programming](https://www.nhl.com/capitals/multimedia/caps-radio)
- **Typical sequence** (radio and TV both):
  1. Final horn call + immediate score/game recap (30-60 sec)
  2. Player walk-off/tunnel interview (1 per team typically, ~60-90 sec each)
  3. Coach postgame press conference — broadcast airs clipped highlights, not the full presser (full pressers run 5-10 min at the podium; broadcast uses 1-2 soundbites of ~15-30 sec each)
  4. **Three stars selection and announcement**: chosen by home-team media/PR staff (not the league), announced over arena PA immediately following the game (typically within 1-3 min of final horn), 3rd star through 1st star order, each named star briefly acknowledged on ice/scoreboard. [Three stars (ice hockey) - Wikipedia](https://en.wikipedia.org/wiki/Three_stars_(ice_hockey)) / [NHL Records - Three Stars](https://records.nhl.com/awards/three-stars)
  5. Final broadcast-team wrap/analysis (2-4 min)
  6. Next-game promo/tune-in tag (15-30 sec)

## 5. Arena Presentation Conventions

- **Goal horn**: near-universal, sounds immediately on goal light, paired with a goal song (custom per arena, ~130-140 BPM target tempo for "pump up" effect per sound-design convention). [dashershockey.com arena anthems](https://dashershockey.com/arena-anthems-music-that-defines-the-live-hockey-experience/)
- **Organ/live music role**: historically full-game organist (Chicago's "Barton" organ dates to 1929); modern arenas mostly replaced continuous organ with DJ/soundboard, but many teams reintroduced organ stings in the last decade as a nostalgia/atmosphere layer — used for goal-horn stinger tags, whistle-stoppage filler, and prompting sing-along/chant cues (call-and-response riff, crowd responds "charge!" etc.). [dashershockey.com organ history](https://dashershockey.com/the-mighty-organ-a-history-of-arena-organs-in-hockey/)
- **Crowd-swell/music-cue events**:
  - Power play start: hype music dips to a low-key "building" bed (deliberately kept low/quiet so PA/organ can build tension), swelling as PP clock nears expiration
  - Breakaway: spontaneous crowd noise cue/organ sting, no set music — arena ops watch play live and cue an audible rise
  - Fight: instant full-volume crowd-hype track cue, arena horn/sting, often no PA announcement (organic crowd reaction is the "programming")
  - Milestone announcement (100th goal, franchise record, etc.): scoreboard graphic + PA special announcement + hype-track sting, timed to a stoppage
  - Post-goal celebration window: full-song goal anthem plays ~10-20 sec before ducking under PA goal-announcement voice-over
- **PA announcer duties/wording**:
  - Goal: *"[Team] goal scored by number [#], [Player Name], assisted by number [#], [Player], and number [#], [Player]."* (or "...unassisted") — standard structure across amateur/college guides mirrors NHL usage. [PAHL/MVCHA scripts](https://media.hometeamsonline.com/photos/hockey/MISSISSIPPIVALLEYCLU/MVCHA_ANNOUNCERS_SCRIPT_AND_DUTIES.pdf)
  - Penalty: *"[Team] penalty to number [#], [Player Name], [duration] minutes for [infraction]. Time of penalty: [game clock]."*
  - One-minute-of-period warning: *"One minute remaining in the period."* — one of the only permitted live-play interjections alongside goals/penalties.
  - Attendance: read once per game, at first intermission or postgame — *"Tonight's attendance: [number]."*
  - Three stars: read in reverse order (3rd → 1st) immediately postgame, each with a brief pause for arena reaction/spotlight.

## Notes on Sourcing & Uncertainty

- Intermission length has two reported figures: 18 min (NHL rulebook, regular season) vs. 17 min (primetime/TV-featured). Both are real and used in different broadcast contexts — 18 min is the default target; 17 min applies specifically to TV-featured/primetime games. Keep both as valid states rather than resolving to one number.
- TV pregame length varies by network/slot (20 min ABC/ESPN primetime, 30 min ABC/ESPN non-primetime and TNT standard, 90 min TNT marquee) — these are genuinely distinct conventions, not conflicting measurements of the same thing.

---

## SIMULATOR TARGETS

| Element | Target value | Notes / conditions |
|---|---|---|
| Pregame runtime (radio) | 15 min | Baseline broadcast standard |
| Pregame runtime (TV primetime) | 20 min | ABC/ESPN |
| Pregame runtime (TV standard) | 30 min | ABC/ESPN non-primetime; TNT standard; digital-only shows (e.g. "The Drop") |
| Pregame runtime (TV marquee) | 90 min | TNT season openers/playoffs/on-location |
| Pregame: storylines/matchup framing | 30-40% of window (~4-6 min of 15) | |
| Pregame: lineups/scratches/line combos | 20-30% of window (~3-5 min of 15) | |
| Pregame: goalie confirmation | <60 sec discrete beat | Confirmed by team ~60 min pregame; warmups start ~20 min before puck drop |
| Pregame: reporter hits | 1-2 hits, 60-90 sec each | Pre-warmups and pre-puck-drop |
| Pregame: cold open/sponsor billboard | 15-30 sec | Plus branded tags throughout |
| Play-by-play talk-time split | ~70-80% PBP / ~20-30% color | Radio requires continuous description |
| Score/time restate cadence | Every 60-90 sec of live action | Plus mandatory restate after every goal, penalty, break return, period start |
| Out-of-town scoreboard cut-ins | 1-2 per period | At TV timeouts/period breaks; more on playoff-race nights |
| "Last minute" PA call | Exactly once per period, at 0:60 mark | One of only ~3 permitted live-play interjections (goal, penalty, 1-min warning) |
| TV timeouts | 2 per period | Additional score-restate/scoreboard-cutin anchor points |
| Intermission length (default) | 18 min | NHL rulebook, regular season |
| Intermission length (TV-featured/primetime) | 17 min | To fit broadcast windows |
| Intermission: recap/highlights | ~20% (~3-4 min of 18) | |
| Intermission: studio/panel discussion | ~25% (~4-5 min of 18) | |
| Intermission: scoreboard update | ~10% (~1-2 min of 18) | |
| Intermission: walk-off soundbite/reporter update | ~10% (~1-2 min of 18) | |
| Intermission: sponsor inventory | ~35% (~5-7 min of 18) | Multiple :15-:30 reads |
| Postgame runtime | 30 min | Standard team radio network window |
| Postgame: horn call + recap | 30-60 sec | Immediately after final horn |
| Postgame: player interviews | 1-2 per team, 60-90 sec each | Walk-off/tunnel |
| Postgame: coach soundbites | 1-2 clips, 15-30 sec each | Clipped from a 5-10 min full presser |
| Three stars announcement timing | Within 1-3 min of final horn | 3rd → 1st order; home-broadcast/media selected, not league-officiated |
| Postgame: broadcast wrap/analysis | 2-4 min | |
| Postgame: next-game promo | 15-30 sec | |
| Attendance announcement | Exactly once per game | At first intermission or postgame |
| Goal horn/anthem trigger | Instant on-goal | 10-20 sec of full song before ducking for PA goal call |
| Goal-horn/hype track tempo | 130-140 BPM | Target tempo for "pump up" effect |
| PA goal call template | `"[Team] goal scored by number [#], [Player Name], assisted by number [#], [Player], and number [#], [Player]."` (or "...unassisted") | Fixed string template with slots |
| PA penalty call template | `"[Team] penalty to number [#], [Player Name], [duration] minutes for [infraction]. Time of penalty: [game clock]."` | Fixed string template with slots |
| PA one-minute warning template | `"One minute remaining in the period."` | Fired once per period at 0:60 |
| PA attendance template | `"Tonight's attendance: [number]."` | Once per game |
