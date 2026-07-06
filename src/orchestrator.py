"""Main loop: schedule -> writer -> performers -> (TTS -> stream).

    python -m src.orchestrator            # dry-run: print dialogue, no audio, no cost
    python -m src.orchestrator --once     # run exactly one show block, then stop
    python -m src.orchestrator --live     # synth with Kokoro + push to Icecast

The dry-run is the cheapest way to judge whether the writing is funny before you
spend a cent on TTS or a box.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, time as dtime
from pathlib import Path

import yaml

from . import lore
from .openrouter import METER
from .performers import perform_beat
from .writer import write_outline


def _load(path): return yaml.safe_load(Path(path).read_text())


def _now():  # isolated for testing / faking
    return datetime.now()


def _current_daypart(schedule: dict, now: datetime) -> dict:
    t = now.time()
    for dp in schedule["dayparts"]:
        start = dtime.fromisoformat(dp["window"][0])
        end = dtime.fromisoformat(dp["window"][1])
        # handle windows that wrap past midnight (e.g. 22:00 -> 01:00)
        if start <= end:
            if start <= t < end:
                return dp
        else:
            if t >= start or t < end:
                return dp
    return schedule["dayparts"][0]


def run_show(daypart, config, schedule, live: bool):
    models = config["models"]
    state = lore.load()
    weekday = _now().strftime("%A")

    print(f"\n{'='*70}\n  {daypart['show']}  ({daypart['window'][0]}-{daypart['window'][1]})"
          f"  —  {weekday}\n{'='*70}")

    outline = write_outline(daypart, models, state, weekday)
    if outline.get("guest"):
        print(f"  GUEST: {outline['guest']}\n")

    rolling = ""
    for beat in outline.get("beats", []):
        lines = perform_beat(beat, daypart, models, state, rolling)
        print(f"\n--- {beat.get('segment')} ---")
        for ln in lines:
            print(f"  [{ln.get('speaker')}] {ln.get('text')}")
        # cheap rolling summary: last beat's premise keeps continuity tight
        rolling = f"{beat.get('segment')}: {beat.get('beat')}"

        if live:
            from .tts import synth_segment
            out = Path("audio_buffer") / f"{daypart['id']}_{beat.get('segment','seg')}.wav"
            synth_segment(lines, out, config)
            print(f"  ♪ syntheszed -> {out}")
            # deploy/ pushes audio_buffer/*.wav to Icecast via liquidsoap/ffmpeg.

    # persist any new lore the writer established
    lore.remember(state,
                  jokes=outline.get("new_jokes"),
                  guest=outline.get("guest"),
                  callbacks=outline.get("callbacks_used"))
    lore.save(state)

    print(f"\n  cost this show: {METER.summary()}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="synth + stream audio")
    ap.add_argument("--once", action="store_true", help="run one block then exit")
    args = ap.parse_args(argv)

    config = _load("config.yaml")
    schedule = _load("schedule.yaml")

    dp = _current_daypart(schedule, _now())
    run_show(dp, config, schedule, live=args.live)

    if args.once:
        return
    print("\n(--once not set: in production the loop would continue into the next "
          "block and keep the buffer 45 min ahead. Wire the sleep/buffer here.)")


if __name__ == "__main__":
    sys.exit(main())
