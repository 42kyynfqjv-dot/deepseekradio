# NHL Statistical & Structural Grounding (32-Team League Simulator)

*Baseline seasons: 2022-23 through 2025-26, with forward-looking CBA/schedule changes noted where they diverge (2026-27+).*

---

## 1. Team/Game-Level Statistical Distributions

### Scoring
- League combined goals/game: **6.0–6.3** across the last three seasons (6.1+ for three straight seasons — the only such stretch in 30 years). Per-team average ≈ **3.0–3.15 goals/game** (range across 32 teams roughly 2.4–3.6). — [NHL.com quarter-mark report](https://www.nhl.com/news/numbers-at-quarter-mark-of-2024-25-nhl-season), [media.nhl.com PDF](https://media.nhl.com/site/asset/public/ext/nhl%20stats/2024-25%20Regular%20Season/QuarterMark_20242025_112024.pdf)
- Even-strength share of goals: **~77–78%** (2024-25 quarter mark: 77.6%, highest in 51 seasons). Remainder: PP ~19–20%, SH ~1%, EN ~7%.
- Empty-net goals: **~7.0–7.1% of all goals** (~1 in 14), adding **~0.15–0.20 EN goals/game** league-wide; average goalie-pull timing when trailing by one is **~2:10 remaining** (up from ~1:15 a decade ago). — [Daily Faceoff](https://www.dailyfaceoff.com/news/how-empty-net-goals-have-changed-the-nhl)
- Scoring by period: **P1 ≈ 30%, P2 ≈ 35%, P3 ≈ 35%** of regulation goals; third-period bump driven by empty-net situations and desperation offense. — [DRatings](https://www.dratings.com/a-breakdown-of-nhl-goal-scoring-by-period/), [Sound of Hockey](https://soundofhockey.com/2024/08/01/the-long-change-effect-nhl-scoring-trends-for-the-2023-24-season/)

### Shots, Special Teams, Penalties
- Shots per team per game: **~29–31** league average (individual teams range ~25.5–33+). — [StatMuse](https://www.statmuse.com/nhl/ask?q=nhl+team+stats+shots+per+game+2024-2025)
- League PP%: **~19–21%**; league PK%: **~79–81%**. Top team PP% typically ~27–30%, bottom ~14–16%; top PK% ~85%, bottom ~74–76%.
- Power-play opportunities per team per game: 2022-23 season average 3.07/team; 2023-24 running ~3.57/team (points-of-emphasis on obstruction). Target **~3.0–3.6 PP opportunities/team/game** (roughly 6–7 total power plays/game combined), and correspondingly **~3–4 minor penalties/team/game**. — [Yahoo Sports/NHL](https://ca.sports.yahoo.com/news/nhls-power-play-increase-could-shift-competitive-balance-155320256.html)

### Overtime/Shootout
- % of games reaching OT: **~20.5%** in 2024-25 (historically 20–24%). — [ESPN](https://www.espn.com/nhl/story/_/id/47210375/nhl-2025-26-games-shootout-theories-trends-stats-standings)
- Of OT games, roughly half resolve in 3-on-3 OT and half go to shootout; shootout share of ALL games runs **~9–12%**.
- Home-ice edge in OT/SO: home teams win **~6.5–6.8% more** OT/SO games than road teams over recent seasons; in shootouts specifically, home teams won 162 of 317 (≈51.1%) over 3.5 seasons. — [Sound of Hockey](https://soundofhockey.com/2025/02/02/is-there-really-a-home-ice-advantage-in-the-nhl/)

### Home Ice / Win Rates
- Home team points percentage: **.585** vs. road **.524** in 2023-24 (≈5.5% average boost 2021-22 through 2023-24); 2024-25 showed a larger regulation-win gap (+9.9%). Translates to **home win% ≈ 53–55%** of all decisions. — [Sound of Hockey](https://soundofhockey.com/2025/02/02/is-there-really-a-home-ice-advantage-in-the-nhl/)

### Trailing/Leading Dynamics
- Team leading after 2 periods earns ≥1 point **>93%** of the time; wins in regulation **~79.9–82%** of the time (long-run average since 2007-08: 82.06%). — [Yahoo Sports Puck Daddy](https://sports.yahoo.com/blogs/nhl-puck-daddy/how-safe-are-those-nhl-points-when-leading-into-third-period-192353293.html)
- Corollary: team trailing after 2 gets no point ~80% of the time (wins outright only ~13–18%, counting comebacks and OT/SO steals).

### Shutouts
- Individual goalie shutout leaders run **6–8/season** (2023-24: four goalies tied at 6; 2024-25: Hellebuyck led with 8). League-wide shutout games total **~90–110/season** out of ~1,312 games, i.e. **shutout rate ≈ 7–8% of games**. — [FOX Sports](https://www.foxsports.com/nhl/stats?category=goaltending&sort=sho&season=2024&seasonType=reg&sortOrder=desc)

### Streaks
- Longest single-season win streak: **8–17 games** (2023-24 Vegas hit 17; 2024-25 top streak only 8). Design target: most seasons produce a max win streak of **6–10 games**, with **12+ games** rare (≤1-in-5-seasons); 17 is the all-time record. — [NHL Records](https://records.nhl.com/records/team-records/winning-streaks/longest-win-streak-one-season)
- Longest losing streak: historical record **18 games** (2003-04 Penguins, 2020-21 Sabres). Typical season worst-team streak: **6–10 games**, 14+ rare-outlier. — [Wikipedia](https://en.wikipedia.org/wiki/List_of_NHL_longest_losing_streaks)

### Standings Spread (2024-25 actuals as calibration)
- Presidents' Trophy: Winnipeg Jets, **116 points** (55-22-4, .707 pts%), 5 clear of 2nd (Washington, 111 pts). — [Daily Faceoff](https://www.dailyfaceoff.com/news/winnipeg-jets-win-2024-25-nhl-presidents-trophy-first-time-franchise-history)
- Last place: San Jose Sharks, **52 points** (20-50-12, .317 pts%), 9-pt margin over 31st.
- Playoff cutline (last wild card): historically clusters **~92–96 points** (2024-25 West 2nd wild card, St. Louis, clinched at 96).
- Points percentage distribution across 32 teams: roughly normal-ish with fat tails — top team **.700–.720**, cutline **.560–.590**, bottom **.300–.340**; league mean pinned at **.500** by construction (loser-point OT/SO allocation raises total points issued above 2×games).

---

## 2. Player-Level Distributions

### Scoring Leaders
- **Art Ross (points):** 2023-24 Nikita Kucherov 144 pts (44G-100A, 81 GP) [hockey-reference.com/awards/ross.html]; 2024-25 Kucherov 121 pts (37G-84A, 78 GP), 5 clear of MacKinnon [nhl.com/lightning]. Norm-band: **100–145 pts** for the league leader in an 82-game season; repeat winners rare (only 3 in 25 yrs: Jagr, McDavid, Kucherov).
- **Rocket Richard (goals):** 2023-24 Auston Matthews 69G (3rd Richard); 2024-25 Leon Draisaitl 52G — only 50-goal scorer that season [dailyfaceoff.com]. League-leader band: **50–70 goals**; a 60+ season happens roughly half the time, 65+ is a "big" year, only 1-2 players clear 50 most seasons.
- **100-point players/season:** 2023-24 had 9 (highest count since 2005-06) — Kucherov 144, McDavid 132, MacKinnon 140, Matthews 107, Draisaitl 106, Pastrnak 110, Rantanen ~106-107, Pettersson 102, Panarin [thehockeynews.com; records.nhl.com]. 2024-25 had fewer (~6–7, Kucherov 121 leading, MacKinnon ~116). Target band: **5–10 players/season**, clustering 6–9 in the current high-cap, high-pace era.
- **40-goal scorers:** typically **8–14 players/season**. **30-goal scorers:** typically **40–55**. **20-goal scorers:** typically **110–135** (roughly one per team's top-2 lines plus a chunk of top-pairing/PP defensemen). — cross-checked via [hockey-reference.com/leagues/NHL_2024_leaders.html], NHL.com, StatMuse.
- **Typical team leading scorer:** 70–95 pts for a good top-6 forward on a competitive team; bottom-feeder team's leading scorer as low as 55–65 pts. League-wide span roughly **55–144 pts**, median ~75–80.

### Defense / Norris-Level
- 2023-24 Quinn Hughes 92 pts (17G-75A) [bleacherreport.com]; 2024-25 Cale Makar 92 pts (30G-62A, 80 GP) [nhl.com/avalanche]. Norris-tier defensemen: **75–95 pts**. Median full-time defenseman (40+ GP): **20–30 pts**; typical top-pairing #1 D on a mid-tier team: **40–55 pts**; depth/3rd-pairing D: **10–20 pts**.

### Goaltending
- League averages: 2023-24 SV% ≈ **.903–.905**; 2024-25 ≈ **.900–.902** (slight YoY dip, a known modern trend as scoring rate ticks up). League GAA typically **2.90–3.10** (inverse of SV% at ~30-31 shots against/game). — [statmuse.com]
- **Vezina-level:** 2023-24 Connor Hellebuyck: 37W, 2.39 GAA, .921 SV%, 5 SO [russianmachineneverbreaks.com]; 2024-25 Hellebuyck career-best 47W, 8 SO, **.925 SV%**, **2.00 GAA** [espn.com]. Vezina-caliber band: **.920–.930 SV%, 2.00–2.40 GAA**, typically 55–65 starts.
- **Starter workload:** true #1 goalies play **55–65 GP/season** (e.g., Montembeault 60 GP/.901/2.82; Skinner 59 GP 2023-24). **Backup workload:** typically **18–27 starts/season** (Stolarz 27, Woll 25, Brossoit 23, Wedgewood 18, 2023-24). Healthy tandem split roughly **60/22 GP** starter/backup (82 total). — [dknetwork.draftkings.com; thehockeynews.com]

### Roster Depth Curve (23-man roster)
- Forwards: L1 **65–95 pts (0.80–1.15 PPG)**; L2 **45–65 pts (0.55–0.80 PPG)**; L3 **25–40 pts (0.30–0.50 PPG)**; L4 (grinders) **8–20 pts (0.10–0.25 PPG)**, often heavier on PK/hits/blocks than scoring.
- Defense pairings: Pair 1 **35–55 pts** (offensive #1) down to **25–35** (defensive #1); Pair 2 **20–35 pts**; Pair 3 (PK specialists) **8–18 pts**.

### Other Rate Stats
- **Assist:goal ratio:** modern NHL runs **~1.45–1.55 assists per goal** league-wide (stable long-run constant); elite playmakers (Kucherov 2023-24: 44G/100A = 2.27) run well above the league mean.
- **Hat tricks league-wide/season:** 2023-24: **115** (Matthews led with 6) [hockey-reference.com]; 2024-25: **77** (Rantanen led with 3) [statmuse.com]. Roughly **0.06–0.09 hat tricks per game league-wide** (1,312 games/season), ~1–3 per team/season; top scorer typically **3–6/season**.
- **4+ point games/season:** rare — league leader typically only 3–4 in a full season (Kucherov led 2023-24). League-wide total roughly **15–25/season**, concentrated among the top-10 scorers.

---

## 3. Injuries & Roster Churn

### Man-Games Lost (MGL) per Team per Season
- Median team: **~200 MGL/season**; heavily right-skewed (a few teams reach 3x median in bad-luck years). 2023-24 high end: Montreal ~390 MGL (down from 599 in 2021-22 and 600 in 2022-23 — a multi-year outlier franchise). — [x.com/EricEngels](https://x.com/EricEngels/status/1840203516331114716)
- "Most distinct players who missed games" framing: San Jose led the league with 54 skaters/goalies missing ≥1 game in 2023-24 and 50 in 2024-25. — [StatMuse 2023-24](https://www.statmuse.com/nhl/ask/nhl-most-man-games-lost-to-injury-2023-2024-season), [StatMuse 2024-25](https://www.statmuse.com/nhl/ask/nhl-most-man-games-lost-to-injury-2024-2025-season), [RotoWire](https://www.rotowire.com/hockey/article/nhl-most-injured-teams-2024-25-93844)
- Peer-reviewed epidemiology: ice hockey overall injury incidence **5.93–15.6 per 1000 athlete-exposures**, roughly even upper- vs lower-body split, plus a distinct head/concussion category. — [PMC11611472](https://pmc.ncbi.nlm.nih.gov/articles/PMC11611472/)
- Working target, 32-team league, 82 GP: league-wide total **~6,000–6,400 MGL**, i.e., **~190–200 mean/team**, **stdev ≈ 80–100**, range roughly **60 (healthiest) to 500+ (worst-luck outlier)**.

### Injury Type → Duration Distribution (generator buckets)
| Bucket | Typical parlance | Days/games missed | Share of injury events (approx) |
|---|---|---|---|
| Day-to-day | "day-to-day" | 3–7 days (~1–4 games) | ~45–55% |
| Week-to-week | "week-to-week" | 3–6 weeks (~10–20 games) | ~25–30% |
| IR stint (standard) | placed on IR | min. 7 days mandatory before return-eligible | subset of week-to-week+ |
| LTIR / season-ending | placed on LTIR | min. 10 games AND 24 days; many run 2–6+ months | ~10–15% of events, but consumes majority of total MGL |
| Concussion | "upper body"/protocol | mean **20.9 ± 12.2 days** (n=22 study) vs **20.5 ± 14.9 days** lower-body in matched cohort (r=0.91, avg gap 0.73 days) — concussions are NOT systematically longer than comparable soft-tissue injuries | [PMC6602365](https://pmc.ncbi.nlm.nih.gov/articles/PMC6602365/) |
| Non-injured baseline | — | mean 12.1 ± 4.9 days (healthy-scratch/roster days) | same study |

Practical generator: sample injury duration from a **log-normal**, median ~7 days, heavy tail to 180+ days (LTIR/season-ending). Roughly **50% of events resolve ≤7 days, 30% resolve 8–30 days, 15% resolve 31–90 days, 5% exceed 90 days** (season-enders).

### Concussion / IR / LTIR Rules (engine gating)
- **IR (standard):** player physically unable to play for a minimum of **7 days**; roster spot opens but doesn't count toward the 23-man active roster; no cap relief. — [Wikipedia](https://en.wikipedia.org/wiki/Injured_reserve_list)
- **Concussion protocol:** 7-day IR-equivalent hold; if not cleared by day 7, formally moves to standard IR. — [NHL Hockey Ops Guidelines](https://www.nhl.com/info/hockey-operations-guidelines)
- **LTIR:** must be out **≥10 NHL games AND ≥24 calendar days**; unlocks cap relief = replacement-player cost. Post-2025-CBA reform (2025-26+): relief for a same-season-return player capped at prior season's league-average salary (**~$3.82M for 2025-26**); full dollar-for-dollar relief only if out for the entire remaining season; post-April-1 injuries can no longer bank cap space for playoff activation; playoffs require full cap compliance. — [Puckpedia LTIR](https://puckpedia.com/salary-cap/LTIR), [NHL Rumors cap explainer](https://nhlrumors.com/nhl-salary-cap-explained-aav-ltir-and-the-new-104m-era/2026/07/08/), [CBC](https://www.cbc.ca/sports/hockey/nhl/nhl-ltir-cap-circumvention-1.7347176)

### Roster Limits, Call-Ups, Emergency Recalls
- Active roster: min 20, max **23** (pre-trade-deadline); dressed-for-game roster is **20** (typically 12F/6D/2G, splits vary).
- Emergency recall trigger: fewer than **12 healthy forwards, 6 healthy defensemen, or 2 healthy goaltenders**. — [Puckpedia 22 Rules](https://puckpedia.com/22rules)
- Post-trade-deadline recalls: capped at **5 non-emergency recalls/team** from deadline to season end (raised from 4 in latest CBA); emergency recalls beyond that don't count against the cap once the injured player is reactivated and the recall is returned. — [The Hockey News](https://thehockeynews.com/news/news/how-do-recalls-work-after-the-nhl-trade-deadline)
- Conditioning loan: max **6 days or 3 AHL games**.

### Waiver Basics
- Regular recall: no waiver-clock consequence.
- Emergency recall: player returnable without waivers only until **10 games** played on that recall.
- Waiver-exemption windows (skaters): signed at 18 → exempt **5 yrs or 160 NHL GP** (whichever first); 19 → **4 yrs/160 GP**; scales down with signing age; 25+ → essentially **1 yr/1 GP**. Goalies signed at 18: exempt **6 yrs or 80 GP**, also scaling down.
- Once exemption is used, must clear waivers (24-hr claim window) to go to AHL; clearing status resets after **10 games or 30 days** on the active roster since last clearing. — [dkpittsburghsports waiver primer](https://www.dkpittsburghsports.com/2018/09/29/nhl-waiver-faq-calculator-tlh), [CBA School Art. 13](https://flamesnation.ca/news/cba-school-article-13-waivers)

### Trade Volume
- 2022-23: **238 distinct players moved** via trade (recent-era benchmark).
- 2025-26: 61 more players traded than 2023-24 — second-highest player-movement season ever, implying 2023-24 sat ~175–180 players moved.
- 2024-25 trade-deadline week (deadline **March 7, 2025**): **45 trades**, **143 assets**, **$168.96M** in cap hits moved in one week. — [NHL.com trade tracker](https://www.nhl.com/news/2024-25-nhl-trades)
- Working targets: **full-season trade count ≈ 60–100 discrete transactions** league-wide, with a spike on deadline day itself (historically **15–25 trades on deadline day**), plus the 45-trade deadline-week figure as the broader window.

### Coach Firings (In-Season)
- 2023-24: 7 teams fired their head coach mid-season. 2024-25: sources diverge — 4 clearly mid-season, a broader tracker (incl. tail-end firings) reached 8. — [Daily Faceoff](https://www.dailyfaceoff.com/news/how-well-every-mid-season-nhl-coaching-change-worked-2024-25), [Stadium Rant](https://www.stadiumrant.com/nhl-head-coaches-fired-this-season-reaches-8/)
- Working target: **4–8 in-season/near-season coaching changes/year** across 32 teams (~13–25% of teams), with **4–7** the strict mid-season subset.

---

## 4. Contracts, Salary Cap, Draft, Aging

### Salary Cap Trajectory (2025 CBA extension, NHL/NHLPA announced)
| Season | Ceiling | Floor | YoY ceiling increase |
|---|---|---|---|
| 2024-25 | $88.0M | $65.0M | — |
| 2025-26 | $95.5M | $70.6M | +$7.5M |
| 2026-27 | $104.0M | $76.9M | +$8.5M |

Cap floor consistently **~74% of ceiling** across all three seasons (65/88, 70.6/95.5, 76.9/104 all ≈ 0.739–0.740) — use **floor = 0.74 × ceiling** as a stable generator rule. 2027-28+ subject to minor revenue-based adjustment; project future ceilings at **+7–9%/yr** until superseded. — [NHL.com](https://www.nhl.com/news/nhl-nhlpa-announce-team-payroll-ranges-for-next-3-seasons), [Puckpedia](https://puckpedia.com/salary-cap/2025-cba)

### League Minimum Salary
- 2023-24 through 2025-26: **$775,000/yr flat**. New CBA step schedule 2026-27→2029-30: **$850K → $900K → $950K → $1.0M**. — [Puckpedia](https://puckpedia.com/salary-cap/2025-cba)

### Max Contract Length & Structure
- Old CBA: 8 yrs re-sign / 7 yrs UFA-to-new-team. **New CBA (effective 2026-27): 7 yrs re-sign / 6 yrs external UFA.**
- Max cap hit for any single player: **20% of that season's ceiling** (e.g., $17.6M in 2024-25).
- New CBA variance rule: adjacent-year salary swing capped at **20% of first-year salary**; lowest year of a contract must be **≥71% of the highest year** (curbs extreme front/back-loading). — [ESPN](https://www.espn.com/nhl/story/_/id/45732725/nhl-nhlpa-cba-new-rules-salary-cap-trades-ebugs-84-games), [Puckpedia](https://puckpedia.com/salary-cap/answers/maximum-cap-hit)

### Entry-Level Contract (ELC)
- Length by signing age: **18–21 → 3 yrs; 22–23 → 2 yrs; 24 → 1 yr** (24+ typically signs a standard contract, not ELC).
- Max base ("Paragraph 1") salary: **$975,000/yr** for 2025 draft class, rising to **$1,000,000/yr** for 2026 class.
- Signing bonus cap: **≤10%** of Paragraph 1 salary (≤$97,500 on a max ELC).
- Performance bonuses: "A" bonuses up to **$1.0M**, "B" bonuses (2022+ draftees) up to an additional **$2.5M** — total ceiling ~$3.5M/yr on top of base.
- **Slide rule:** an 18/19-year-old signee playing <10 NHL games in a season has that contract year "slide" forward. — [Eliteprospects](https://www.eliteprospects.com/page/nhl-entry-level-contract-how-rookie-deals-work), [Puckpedia](https://puckpedia.com/salary-cap/entry-level-performance-bonuses)

### RFA vs UFA Eligibility
- **RFA (Group 2):** signed ≥1 NHL contract, **under 27**, **<7 accrued NHL seasons**. Team must tender a Qualifying Offer by ~June 25 or player becomes UFA July 1.
- **UFA:** age **27+ OR 7+ accrued seasons**, whichever first.
- **Accrued season:** player 18–19 who plays **≥10 professional games**, or player 20+ who plays **≥1 professional game**, in that season. — [Puckpedia RFA/QO](https://puckpedia.com/salary-cap/restricted-free-agents-rfa-qualifying-offers), [Puckpedia Group 6](https://puckpedia.com/group6)

### Arbitration
- Eligibility by signing age + accrued seasons: 18–20 → **4 seasons** (≥10 GP/season); 21 → **3**; 22–23 → **2**; 24+ → **1**.
- Either team or player can file (early-mid July window). Award binding **unless it exceeds a walk-away threshold (~$4.85M for 2025)**, above which the team may reject and the player becomes UFA. — [Sound of Hockey](https://soundofhockey.com/2025/07/09/understanding-the-arbitration-process-what-it-means-for-kaapo-kakko-and-the-kraken/)

### Roster Cap-Hit Distribution (typical contender, ~$88–95M cap)
- Top-line/franchise forward: $9–12M ≈ **10–13% of cap**. Top forward line (3 players) combined: **22–28%**.
- Top D-pairing (2 players): **14–20%** (elite #1 D alone can be $9–11M, ~10–12%).
- Starting goalie: **$8–10M ≈ 9–11%** (Bobrovsky ~11%, Vasilevskiy ~9.5–10%, Hellebuyck/Sorokin ~8.5–9%) — goalies systematically underpaid relative to skater cap share. Backup goalie: $1–2.5M ≈ **1–3%**.
- Bottom-6 forwards/3rd-pairing D: often near minimum-to-$2M, individually 1–2% of cap.
- Full-roster shape (23-man, ~50 cap-counted contracts incl. LTIR/bonuses): top 6–8 contracts consume **~55–65% of total cap**, remaining 35–45% spread over 14–16 depth players near minimum. — [Spotrac](https://www.spotrac.com/nhl/rankings/player/_/year/2025/position/g/sort/cap_total), [The Hockey Writers](https://thehockeywriters.substack.com/p/goalies-remain-undervalued-salary-cap-trends)

### NHL Draft Structure
- **7 rounds**, 32 picks/round = up to 224 selections, minus forfeitures/trades.
- Draft Lottery: only the **16 non-playoff teams** participate for positions **1–16** (Round 1).
- Drop rule: a team can fall a max of **10 spots** from its actual standing via lottery (only top-11-worst teams eligible to jump to 1st overall).
- Twice-in-5-years cap: a franchise may move up via lottery **only twice in any 5-year window** (rule started 2022).
- 2026 lottery example (bottom-16, worst-to-least-bad): Sharks 18.5%, Blackhawks 13.5%, Predators 11.5%, Flyers 9.5%, Bruins 8.5%, Kraken 7.5%, Sabres 6.5%, Ducks 6.0%, Penguins 5.0%, Islanders 3.5%, Rangers 3.0%, Red Wings 2.5%, Blue Jackets 2.0%, Utah 1.5%, Canucks 0.5%, Flames 0.5%. — [Tankathon](https://www.tankathon.com/nhl/pick_odds), [ESPN](https://www.espn.com/nhl/story/_/id/37555787/how-nhl-draft-lottery-works-chances-odds-top-teams-percentages)

### Aging Curves
- Forwards: peak **~24–27** (some models cite 27–28); decline accelerates after 25–27, steeper than defensemen post-peak. Median retirement age ~31.
- Defensemen: peak **~26–29** (later than forwards); decline more gradual/flat post-peak. Median retirement ~32.
- Goalies: peak later, commonly **~28–30**; late-20s rookie starters not rare; sustain performance into mid-to-late 30s more than skaters.
- NHL debut age: mean **20.6 ± 2.1 yrs**; bulk cluster **18–23**; rare outliers debut late-20s (esp. goalies, European imports).
- League standing average age: **~27.6 yrs** (Dec 2024 snapshot).
- Retirement: bulk of departures **32–36**; "early decline" markers sometimes cited at 28-30 but actual roster exit skews 32–36; long veteran tail to **38–42**. — [PMC relative-age study](https://pmc.ncbi.nlm.nih.gov/articles/PMC4035396/), [SFU FPCA Aging Curves paper](https://www.sfu.ca/~tswartz/papers/aging.pdf), [Hockey-Graphs](https://hockey-graphs.com/2017/03/23/a-new-look-at-aging-curves-for-nhl-skaters-part-1/)

---

## 5. Schedule, Season Structure & Playoffs

### Regular-Season Schedule Matrix (82 games, effective through 2025-26; 84-game format begins 2026-27)
| Opponent bucket | Teams faced | Games each | Total |
|---|---|---|---|
| Division rivals (5 of 7) | 5 | 4 games (2H/2A) | 20 |
| Division rivals (remaining 2 of 7) | 2 | 3 games | 6 |
| **Division subtotal** | 7 | — | **26** |
| Same-conference, non-division | 8 | 3 games | 24 |
| Other conference (all) | 16 | 2 games (1H/1A) | 32 |
| **Total** | 31 | — | **82** (41H/41A) |

- 4 divisions of 8 (2/conference): Atlantic, Metropolitan (East); Central, Pacific (West).
- Starting 2026-27: divisional games rise to 4 vs. all 7 rivals (28 games), season expands to **84 games**. — [nhltraderumorstalk.com](https://nhltraderumorstalk.com/nhl-2026-27-season-84-games-schedule-start-date-key-dates)

### Season Calendar (2025-26, representative)
| Milestone | Date |
|---|---|
| Opening night | Tue Oct 7, 2025 |
| Winter Classic | Jan 2, 2026 |
| Olympic break (2026 is an Olympic year, replaces All-Star Game) | No games **Feb 5–25, 2026** (~20 days) |
| Trade deadline | **Fri Mar 6, 2026, 3:00 p.m. ET** |
| Regular-season finale | Thu Apr 16, 2026 (1,312 games league-wide) |
| Draft lottery (2026) | May 5 |
| Playoffs | mid-April–mid/late June |
| Stanley Cup Final | starts ~first week of June (2025: Jun 4–17, 6 games) |
| Entry Draft (2026) | Round 1 Jun 26, Rounds 2–7 Jun 27, Buffalo |
| Free agency opens | **July 1, 12:00 p.m. ET** |

In non-Olympic years: standard **4–5 day All-Star break** (late Jan/early Feb) plus a **4-day bye week** per team (staggered Nov–Feb). — [2025-26 NHL Key Dates](https://media.nhl.com/site/asset/public/ext/2025-26/2025-26KeyDates.pdf), [2026 Draft Lottery](https://www.nhl.com/news/2026-nhl-draft-lottery-set-for-may-5)

### Cadence & Back-to-Backs
- 82 games over ~26 weeks ≈ **3.1 games/week/team** average; typical week is 3 games, occasionally 2 (near breaks) or 4 (compressed stretches).
- Back-to-backs: league average ≈ **12–13 sets/team/season**; range **~7 (best geography) to 16 (congested market)**; NHL has been reducing these year-over-year via schedule software (down from ~16–20/team a decade ago).
- Fatigue effect: teams average **~1.08 pts/game** in game 1 of a back-to-back, **~1.01 pts/game** in game 2, vs **~1.13 pts/game** in non-B2B games (~10% dip on the second night). — [StatMuse](https://www.statmuse.com/nhl/ask/schedule-of-nhl-teams-playing-back-to-back-games), [ESPN](https://www.espn.com/nhl/story/_/id/39512201/how-nhl-players-teams-deal-grind-back-back-games)
- Christmas break: **Dec 24–26**, no games league-wide. Bye week: one **~4-day** in-season bye per team, scheduled individually Nov–Feb.

### Standings Points System
- Win (any way): **2 points**. OT/SO loss: **1 point**. Regulation loss: **0 points**. No ties since 2005-06. Max points in 82 GP: **164**.
- **ROW** (Regulation + OT Wins, excludes SO wins) used for tiebreaking/wild-card proxy.
- **Tiebreaker order:** (1) fewer GP / superior points%, (2) greater Regulation Wins (RW), (3) greater ROW, (4) greater total Wins, (5) head-to-head points in season series. — [NHL.com Tie-Breaking Procedure](https://www.nhl.com/info/standings-info/tie-breaking-procedure)

### Playoff Format (16 teams, 4 rounds, all best-of-7)
- Qualification per conference (8 teams): top 3 in each of 2 divisions (12 teams total) + 2 wild cards/conference (4 teams) = 16.
- Seeding (fixed, no reseeding after Round 1): division winner with better conference record (A1) plays weaker wild card (WC2); other division winner (B1) plays stronger wild card (WC1); #2 seed plays #3 seed within division.
- Round 1: division-based matchups. Round 2: winners within same conference/division bracket meet (no full-conference reseeding). Round 3: one team per conference advances. Round 4: East champ vs West champ.
- All rounds best-of-7; home-ice format **2-2-1-1-1** (higher seed hosts G1,2,5,7); home ice awarded strictly by regular-season points%/standing. — [NHL.com Playoff Format](https://www.nhl.com/info/standings-info/playoff-format)

### Postseason Calendar
- Playoffs begin mid-April (~2–3 days after finale). Round 1 ~2 weeks; Round 2 ~2 weeks; Conference Finals ~1.5–2 weeks; Stanley Cup Final starts first week of June, played over ~2 weeks with games every 2–3 nights (2025: 6 games, 13 days). Total playoff window: **~9–10 weeks**.

### Draft & Free Agency Sequence
- Draft lottery: early May, **before** playoffs conclude (2026: May 5).
- Entry Draft: last week of June, immediately after the Cup Final — Round 1 one night, Rounds 2–7 the next day. 7 rounds, 32 picks/round (224 total, net of trades/forfeits).
- Free agency opens **July 1, 12:00 p.m. ET**; RFA qualifying-offer deadline ~Jun 25–27 just prior. — [ESPN 2026 draft order](https://www.espn.com/nhl/story/_/id/48686497/nhl-draft-2026-order-picks-lottery-top-prospects), [Central Oregon Daily](https://www.centraloregondaily.com/sports/when-is-nhl-free-agency-opening-date-and-top-free-agents/article_26dce59d-8e5c-568f-8f2a-e303d848a565.html)

---

## Noted Numeric Uncertainties (kept as ranges, not resolved to a single figure)

- **Coach firings 2024-25:** sources diverge 4 (strict mid-season) vs 8 (broad "fired this season" tracker); use 4–8 as the working band.
- **Goalie SV%/GAA year-to-year:** 2023-24 (.903–.905) vs 2024-25 (.900–.902) reflect a modest, real dip as league scoring rises — not a data error; treat .899–.906 as the current-era band.
- **Trade count 2023-24 baseline:** inferred (~175–180 players moved) from the 2025-26-minus-61 comparison rather than directly reported; flagged as derived, not primary-sourced.

---

## SIMULATOR TARGETS (Consolidated)

### Game & Season Scoring
| Metric | Target |
|---|---|
| Combined goals/game (league mean) | **6.1** |
| Team goals/game (mean, SD) | **3.05 ± 0.4**; most games 3–8 total goals |
| Shots/team/game (mean, range) | **30**; single-game 22–40; team-season averages 26–33 |
| Even-strength share of goals | **77–78%** |
| Empty-net goal rate | **0.17 EN goals/game league-wide (~7% of all goals)**; goalie-pull trigger ~2:00 remaining trailing by 1 |
| Period scoring split | **P1 30% / P2 35% / P3 35%** of regulation goals |
| Shutout rate | **7.5% of games**; top individual goalie **6–9 SO/season** |

### Special Teams
| Metric | Target |
|---|---|
| League PP% (mean, team range) | **20%** (14–29%) |
| League PK% (mean, team range) | **80%** (74–86%) |
| PP opportunities/team/game | **3.3** (range 1–7 in a single game) |
| Minor penalties/team/game | **3.3** |

### Overtime / Home Ice / Game Flow
| Metric | Target |
|---|---|
| OT rate | **21%** of games (~50% resolve in 3v3, ~50% in shootout → SO decides ~10–11% of all games) |
| Home win% (all decisions) | **54%** |
| Home OT/SO win% edge | **+6–7%** over road |
| Leading-after-2 outcome | 82% win in regulation, 13% lose in OT/SO, 5% blown lead in regulation |
| Trailing-after-2 outcome | ~18–20% earn any point; ~13% win outright |
| Back-to-back fatigue penalty | ~4–8% points-percentage dip on game 2 of a B2B |

### Streaks & Standings
| Metric | Target |
|---|---|
| Max win streak/season | Typical 6–10 games; 12+ rare (≤1-in-5 seasons); 17 absolute ceiling |
| Max loss streak/season | Typical 6–10 games; 14+ rare; 18 absolute ceiling |
| Top-team points (82 GP) | **112–120 pts (.68–.73 pts%)** |
| Playoff cutline points | **92–97 pts (.56–.59 pts%)** |
| Last-place points | **50–58 pts (.30–.35 pts%)** |
| League mean pts% / spread | **.500 pinned**, bell-shaped, SD **~.08–.10 pts%** |

### Individual Scoring
| Metric | Target |
|---|---|
| Art Ross winner (points) | **118–148 pts** (mean ~128) |
| Rocket Richard winner (goals) | **48–70 G** (mean ~58); 0–2 players clear 50G/season |
| 100-point scorers/season | **5–10 players** (mean ~7–8) |
| 40-goal scorers/season | **8–14** |
| 30-goal scorers/season | **40–55** |
| 20-goal scorers/season | **110–135** |
| Team leading scorer | **55–95 pts**, median ~75–80 |
| Norris-level D | **80–95 pts** |
| Median full-time D | **20–30 pts**; 3rd-pair D **10–20 pts** |
| Assist:goal ratio | **1.45–1.55 : 1** league-wide (top playmakers 2.0–2.3:1) |
| Hat tricks/season (league) | **75–120** (~0.06–0.09/game); top scorer **3–6/season** |
| 4+ point games/season (league) | **15–25 total**; top scorer max **3–4/season** |

### Goaltending
| Metric | Target |
|---|---|
| League SV% / GAA | **.899–.906** / **2.90–3.10** |
| Vezina-tier SV% / GAA | **.920–.930** / **2.00–2.40** |
| Starter GP | **55–65** |
| Backup GP | **18–27** (tandem split ~60/22) |

### Roster Depth (PPG by line/pair)
| Slot | PPG target |
|---|---|
| Forward L1 | 0.80–1.15 |
| Forward L2 | 0.55–0.80 |
| Forward L3 | 0.30–0.50 |
| Forward L4 | 0.10–0.25 |
| D Pair 1 | 0.30–0.65 |
| D Pair 2 | 0.20–0.40 |
| D Pair 3 | 0.08–0.20 |

### Injuries & Roster Churn
| Metric | Target |
|---|---|
| Man-games lost/team/season | mean **195**, SD **85**, floor ~50, ceiling ~500; league total **6,000–6,400** |
| Injury events/team/season | **25–35** discrete events |
| Injury duration distribution | 50% ≤7 days, 30% 8–30 days, 15% 31–90 days, 5% 90+ days (log-normal, median 7 days) |
| Concussion duration | mean **21 days**, SD ~12–15 (statistically ≈ lower-body soft-tissue duration — do not hard-code as uniquely long) |
| IR threshold | ≥7 days projected |
| LTIR threshold | ≥10 games AND ≥24 days; cap relief per post-2025-CBA rules (partial ~$3.82M league-avg-salary cap if same-season return, full relief only if out for season, no post-April-1 cap banking for playoff activation) |
| Active roster | hard cap **23** (pre-deadline), floor **20**; dressed exactly **20**/game |
| Emergency recall trigger | <12 healthy F, <6 healthy D, or <2 healthy G |
| Post-deadline recall cap | **5 non-emergency recalls/team** |
| Conditioning loan cap | **6 days / 3 AHL games** |
| Waiver exemption (skater) | 18 → 5yr/160GP; 19 → 4yr/160GP; 25+ → 1yr/1GP |
| Waiver exemption (goalie) | 18 → 6yr/80GP (scales down with age) |
| Waiver-clear reset window | 10 games or 30 days on active roster |
| Trade volume | **60–100 discrete transactions/season** league-wide; deadline-day spike **15–25**; deadline-week aggregate ~45 trades/~140+ assets; YoY variance ±30% |
| Coach firings | **4–8 in-season changes/year** (~13–25% of teams); model ~Poisson(λ≈5.5), concentrated Nov–Feb |

### Contracts, Cap, Draft, Aging
| Metric | Target |
|---|---|
| Cap ceiling | 2024-25 $88.0M; 2025-26 $95.5M; 2026-27 $104.0M; project **+7–9%/yr** thereafter |
| Cap floor | **0.74 × ceiling** |
| League minimum salary | **$775,000** flat through 2025-26; then $850K→$900K→$950K→$1.0M for 2026-27→2029-30 |
| Max single-player cap hit | **20% of season ceiling** |
| Max contract term | **7 yrs re-sign / 6 yrs external UFA** (2026-27 CBA on); use 8/7 pre-2026-27 |
| Contract salary variance | adjacent-year change ≤20% of yr-1 salary; contract-low year ≥71% of contract-high year |
| ELC length | 18–21 → 3 yrs; 22–23 → 2 yrs; 24 → 1 yr |
| ELC max base salary | $975K (2025 class) → $1.0M (2026+ class); signing bonus ≤10% of base; performance bonus ≤$1.0M "A" + $2.5M "B" |
| RFA/UFA switch | RFA if age <27 AND accrued seasons <7; else UFA. Accrued season = ≥10 GP (age 18–19) or ≥1 GP (age 20+) |
| Arbitration eligibility | 18–20→4 seasons; 21→3; 22–23→2; 24+→1; walk-away threshold ≈$4.85M (2025 baseline, scale with cap) |
| Draft structure | 7 rounds × 32 picks; lottery pool = 16 non-playoff teams; max lottery jump 10 spots; lottery-jump cap 2x/5 years; top odds ≈18.5%, decaying to 0.5% |
| Roster cap-shape | top forward ≈10–13%; top forward line ≈22–28%; top D-pair ≈14–20%; starting goalie ≈9–11%; backup goalie ≈1–3%; top 6–8 contracts ≈55–65% of cap; remaining 14–16 spots share 35–45% |
| Aging curve | Forward peak 24–28 (center ~27); D peak 26–29; goalie peak 28–30; debut age 20.6±2.1 (range 18–23 typical); retirement median 31 (F)/32 (D), bulk 32–36, veteran tail 38–42; league avg age ≈27.6 |

### Schedule & Playoffs
| Metric | Target |
|---|---|
| Schedule composition (82 GP) | 26 division (5×4 + 2×3) + 24 same-conf non-division (8×3) + 32 other-conf (16×2); 41H/41A exactly |
| Season span | ~178–182 active-play days across a ~197-day calendar window (Oct–mid-Apr) |
| Weekly cadence | mean 3.0–3.2 games/week/team; min 2, max 4 (except break weeks = 0) |
| Back-to-backs/team/season | **10–16 sets** (league mean ~12); ~4–8% pts% penalty on B2B game 2 |
| Bye week | exactly 1/team, 4 consecutive days, individually scheduled mid-Nov to late-Feb |
| Holiday break | 0 games league-wide **Dec 24–26** |
| All-Star/Olympic break | non-Olympic: 4–5 days late Jan/early Feb; Olympic years: ~18–20 days early-to-late Feb |
| Trade deadline | first Friday of March, 3:00 p.m. ET |
| Points system | win=2 (any way), OT/SO loss=1, regulation loss=0; max 164 pts/82 GP; no ties |
| Tiebreak order | (1) pts% if GP differs, (2) RW, (3) ROW, (4) total W, (5) head-to-head pts |
| Playoff qualifiers | top 3/division ×4 (12) + 2 wild cards/conference ×2 (4) = 16; fixed bracket, no reseeding after Rd 1 |
| Series format | best-of-7 all rounds; 2-2-1-1-1 home-ice, higher seed hosts G1/2/5/7 |
| Playoff calendar | Rd1 starts 2–3 days post-finale; total span 9–10 weeks; Final (if 6–7 games) spans 13–16 days |
| Offseason sequence | Draft lottery (early May, pre-playoffs-end) → Cup Final ends (~mid/late June) → Entry Draft (Rd1 one night, Rd2–7 next AM, last week June) → RFA QO deadline (~Jun 25–27) → Free agency opens July 1, 12:00 p.m. ET |
| Forward-compat flag | parameterize division-game count so it flips from 4/3 split (26 total, 82 GP) to flat 4-vs-all-7 (28 total, 84 GP) for seasons tagged 2026-27+ |
