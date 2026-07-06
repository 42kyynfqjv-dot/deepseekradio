# KAOS-FM — "The Frequency"

A 24/7 AI radio station. A rotating cast of characters host shows, riff on
pre-written bits, and bring on guests — generated continuously and streamed out
as audio, unattended, for a few dollars a month.

## The idea

Real radio runs on **dayparts**: the same slot has the same energy every day,
but the cast and bits rotate so it never goes stale. KAOS-FM does the same, with
AI hosts.

## Architecture — two tiers

The trick that keeps it cheap *and* good: split **inventing** from **performing**.

```
  ┌─────────────┐   writes the bits    ┌──────────────┐   riff the dialogue   ┌────────┐
  │ HEAD WRITER │ ───(rarely, smart)──▶│  PERFORMERS  │ ──(constantly, cheap)▶│  TTS   │──▶ stream
  │  V4 Pro     │   segment outlines   │ Mistral-24B  │   spoken lines        │ Kokoro │
  └─────────────┘                      └──────────────┘                       └────────┘
        │                                                                          │
        └── station bible + lore (persistent memory) ◀── lore updates ────────────┘
```

- **Head Writer** (`deepseek/deepseek-v4-pro`) runs ~once per show. It writes the
  skeleton: today's bit premises, beats, guest of the day, callbacks. Low volume,
  so the smarter model costs pennies.
- **Performers** (`mistralai/mistral-small-24b-instruct-2501`) run continuously,
  turning each beat into in-character dialogue. High volume, cheap model.
- **TTS** is self-hosted **Kokoro** — $0, runs on the box.
- **Lore** is a persistent file so running jokes, feuds, and guests carry across
  shows and days.

## Cost (live OpenRouter pricing, "Sharp" tier)

| Line item | Model | ~Monthly |
|---|---|---|
| Performers | mistral-small-24b ($0.05/$0.08 per M) | ~$2.42 |
| Head Writer | deepseek-v4-pro ($0.435/$0.87 per M, once/show) | ~$1.17 |
| TTS | Kokoro (self-hosted) | $0 |
| **LLM total** | | **~$3.6** |
| Server | Netcup VPS | ~$15 |

Levers: swap performers to `inclusionai/ling-2.6-flash` ($0.01/$0.03) to drop the
LLM bill under $1, or up to `qwen/qwen3-235b-a22b-2507` for more polish (~$4.8).

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
src/lore.py            persistent running-joke / feud / guest memory
deploy/                Icecast config + systemd units
```

## Running

```bash
cp .env.example .env      # add OPENROUTER_API_KEY
pip install -r requirements.txt
python -m src.orchestrator        # dry-run: prints dialogue, no audio
python -m src.orchestrator --live # full: TTS + stream to Icecast
```

See `deploy/README.md` for the box setup (Kokoro, Icecast, systemd).

## Status

Scaffold. The schedule, personas, and two-tier loop are wired; Kokoro + Icecast
get hooked up once the Netcup box is provisioned.
