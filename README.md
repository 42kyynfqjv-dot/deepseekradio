# The Frequency

A 24/7 AI radio station. A rotating cast of characters host shows, riff on
pre-written bits, take "calls," and bring on guests — generated continuously and
streamed out as audio, unattended, around the clock.

**Live at [bestairadio.com](https://bestairadio.com).**

## The idea

Real radio runs on **dayparts**: the same slot has the same energy every day,
but the cast and bits rotate so it never goes stale. The Frequency does the same
with AI hosts — a morning-drive show, an afternoon culture hour, a late-night
insomniac companion, an overnight conspiracy call-in, and more, each with its own
cast, register, and recurring segments.

The whole thing is set in **Wending** — a fictional 51st state near Canada,
admitted by clerical error and "pending review" ever since. The station, its
town (Halfway), its local government, and its sports league are all invented,
evergreen, and apolitical — the comedy is bureaucratic absurdity, never real
people or events.

## Architecture — two tiers

The trick that keeps it cheap *and* good: split **inventing** from **performing**.

```
  ┌─────────────┐   writes the bits    ┌──────────────┐   riff the dialogue   ┌────────┐
  │ HEAD WRITER │ ───(rarely, smart)──▶│  PERFORMERS  │ ──(constantly, cheap)▶│  TTS   │──▶ stream
  │  V4-Flash   │   segment outlines   │   V4-Flash   │   spoken lines        │ Kokoro │
  └─────────────┘                      └──────────────┘                       └────────┘
        │                                                                          │
        └── station bible + lore (persistent memory) ◀── lore updates ────────────┘
```

- **Head Writer** runs ~once per show. It writes the skeleton: today's bit
  premises, beats, guest of the day, callbacks — and honors an anti-repetition
  memory so subjects and props don't turn into a rut. Low volume.
- **Performers** run continuously, turning each beat into in-character dialogue,
  inventing callers and guests on the fly. High volume.
- Both tiers currently run `deepseek/deepseek-v4-flash` (cheap enough for the
  firehose, smart enough for the outlines); the split is architectural, so either
  tier can be swapped independently in `config.yaml`.
- **TTS** is self-hosted **Kokoro**, on CPU — $0 per line. Several male host
  voices are bespoke, minted offline with KVoiceWalk and injected into the voice
  bank (Kokoro never shipped a good male voice; these are ours).
- **Lore** is a persistent file so running jokes, feuds, guests, and multi-day
  storylines carry across shows and days.

## Live sports

`Center Ice` is a twice-weekly hockey broadcast of a fully simulated league — a
deterministic, date-seeded season engine (standings, rosters, a running score)
called play-by-play in real time, with a truth-guard so the booth never
contradicts the actual game state. Scores surface on the website's Sports page.

## Cost

Roughly **$20–25/mo** in LLM tokens at 24/7 volume, plus a **€20/mo** Hetzner box
(2→8 vCPU, no GPU; Kokoro runs on CPU). TTS is $0. Cheaper model tiers are
pre-scoped in `config.yaml` comments (e.g. `ling-2.6-flash` drops the LLM bill
under $5/mo) if the token bill needs trimming.

## Layout

```
config.yaml            models, budgets, tuning knobs
schedule.yaml          the 24h daypart clock → which show/personas load when
station/bible.md       station identity, lore rules, content guardrails
personas/*.md          the cast (one file per character) + guest pool
src/openrouter.py      thin OpenRouter client
src/writer.py          head writer — generates a show's segment outline
src/performers.py      performer loop — turns beats into dialogue
src/tts.py             Kokoro synthesis → audio buffer
src/orchestrator.py    main loop: schedule → writer → performers → tts → stream
src/lore.py            persistent running-joke / feud / guest / anti-repeat memory
src/arcs.py            multi-day serialized storylines with payoffs
src/news.py            in-character news bulletins
src/spots.py           ads / weather / traffic rotation
src/season.py          simulated sports league (standings, schedule, rosters)
src/livegame.py        live game engine — play-by-play state for Center Ice
src/scoreguard.py      truth-guard so the booth never misstates the game
src/clock.py           air-time / daypart clock
src/buffer.py          audio buffer + now-playing plumbing
deploy/                Caddy + Icecast config + systemd units
web/                   the public site (player, Sports, Local Government, Best Of)
```

## Running

```bash
cp .env.example .env      # add OPENROUTER_API_KEY
pip install -r requirements.txt
python -m src.orchestrator        # dry-run: prints dialogue, no audio
python -m src.orchestrator --live # full: TTS + stream to Icecast
```

See `deploy/README.md` for the box setup (Kokoro, Icecast, Caddy, systemd).

## Status

**Live in production**, streaming 24/7 since July 2026 on a Hetzner box behind
Caddy + Icecast + Cloudflare. Show generation, the two-tier loop, persistent
lore, live sports, the news desk, ad rotation, and the public website are all
running unattended.
