"""Main loop: schedule -> writer -> performers -> (TTS -> buffer -> stream).

    python -m src.orchestrator            # dry-run: print dialogue, no audio
    python -m src.orchestrator --once     # run exactly one show block, then stop
    python -m src.orchestrator --live     # 24/7: synth to audio_buffer, paced

In --live mode this runs forever: it generates the current daypart's show
beat-by-beat, throttling whenever the buffer is more than
`generation.buffer_target_minutes` ahead of playback. The streamer
(deploy/player.sh) drains the buffer into Icecast independently.
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dtime
from pathlib import Path

import yaml

from . import buffer, lore
from .openrouter import METER
from .performers import perform_beat
from .writer import write_outline

NEWS_VOICE = "am_onyx"  # deep male anchor; news runs hourly so this weighs a lot


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


def _throttle(config: dict, live: bool):
    """Block while the buffer is comfortably ahead of playback."""
    if not live:
        return
    target = config["generation"]["buffer_target_minutes"] * 60
    while buffer.buffered_seconds() > target:
        time.sleep(30)


def _emit(lines: list[dict], label: str, config: dict, live: bool):
    """Print the dialogue; in live mode also synthesize into the buffer."""
    for ln in lines:
        print(f"  [{ln.get('speaker')}] {ln.get('text')}")
    if live and lines:
        from .tts import synth_segment
        out = buffer.next_path(label)
        synth_segment(lines, out, config)
        print(f"  ♪ {out.name}  (buffer: {buffer.buffered_seconds()/60:.1f} min)")


def _news_bulletin(config: dict, live: bool):
    """Frequency News at the top of the show — real headlines, mangled."""
    ncfg = config.get("news", {})
    if not ncfg.get("enabled"):
        return
    from .news import fetch_headlines, write_bulletin
    heads = fetch_headlines(ncfg["feeds"], ncfg.get("headlines_per_bulletin", 4))
    script = write_bulletin(heads, config["models"], Path("station/bible.md").read_text())
    lines = [{"speaker": "Frequency News", "voice": NEWS_VOICE, "text": ln.strip()}
             for ln in script.splitlines() if ln.strip()]
    print("\n--- Frequency News ---")
    _emit(lines, "news", config, live)


def run_show(daypart, config, live: bool):
    models = config["models"]
    state = lore.load()
    weekday = _now().strftime("%A")

    print(f"\n{'='*70}\n  {daypart['show']}  ({daypart['window'][0]}-{daypart['window'][1]})"
          f"  —  {weekday}\n{'='*70}")

    # quick open: a short beat first, so a cold start puts a voice on air fast
    opener_lines = []
    try:
        daypart["_target_lines"] = 6
        opener = {"segment": "Open", "premise": "settling back in mid-show",
                  "beat": "a brief, in-character beat of welcome-back chatter; "
                          "tease that more of the show is ahead"}
        opener_lines = perform_beat(opener, daypart, models, state, "")
        _emit(opener_lines, f"{daypart['id']}-open", config, live)
    except Exception as e:
        print(f"  (opener skipped: {e})")

    try:
        _news_bulletin(config, live)
    except Exception as e:  # news must never kill the show
        print(f"  (news skipped: {e})")

    outline = write_outline(daypart, models, state, weekday)
    if outline.get("guest"):
        print(f"  GUEST: {outline['guest']}\n")

    daypart["_target_lines"] = config["generation"].get("lines_per_beat", 22)
    parts = config["generation"].get("parts_per_beat", 3)
    # each outline beat becomes N chained parts of one continuous scene
    beats = []
    for b in outline.get("beats", []):
        for pi in range(parts):
            bb = dict(b)
            if pi > 0:
                bb["beat"] = (f"{b.get('beat')} (CONTINUE this same ongoing scene, "
                              f"part {pi+1} of {parts}: same characters and callers still "
                              "present. Develop the conversation naturally — follow-ups, "
                              "small turns, warmth. Keep the absurdity at the level it "
                              "already reached; do NOT escalate further. The host stays "
                              "grounded and sincere no matter how odd the caller gets"
                              + ("" if pi < parts - 1 else ". You may gently land the bit now"))
            beats.append(bb)

    def _context(i, prev_lines):
        """True continuity: outline recap + the actual last lines spoken."""
        recap = "" if i == 0 else f"{beats[i-1].get('segment')}: {beats[i-1].get('beat')}\n"
        tail = "\n".join(f"{ln.get('speaker')}: {ln.get('text')}"
                          for ln in prev_lines[-6:])
        return (recap + ("LAST LINES SPOKEN ON AIR (continue directly from these):\n"
                         + tail if tail else "")).strip()

    # prefetch: next beat's dialogue generates while current beat synthesizes
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(perform_beat, beats[0], daypart, models, state,
                          _context(0, opener_lines)) if beats else None
        for i, beat in enumerate(beats):
            _throttle(config, live)
            lines = fut.result()
            if i + 1 < len(beats):
                fut = pool.submit(perform_beat, beats[i + 1], daypart, models,
                                  state, _context(i + 1, lines))
            print(f"\n--- {beat.get('segment')} ---")
            _emit(lines, f"{daypart['id']}-{beat.get('segment', 'seg')}", config, live)

    # persist any new lore the writer established
    lore.remember(state,
                  jokes=outline.get("new_jokes"),
                  guest=outline.get("guest"),
                  callbacks=outline.get("callbacks_used"))
    lore.save(state)
    print(f"\n  cost so far this run: {METER.summary()}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="synth into the stream buffer")
    ap.add_argument("--once", action="store_true", help="run one show block then exit")
    args = ap.parse_args(argv)

    config = _load("config.yaml")
    schedule = _load("schedule.yaml")
    buffer.ensure_dirs()

    while True:
        dp = _current_daypart(schedule, _now())
        try:
            run_show(dp, config, live=args.live)
        except Exception as e:  # a bad show must not kill the station
            print(f"!! show crashed, continuing: {e}")
            time.sleep(60)
        if args.once:
            return
        # wait until the buffer needs more, or the daypart changes
        while (_current_daypart(schedule, _now()) is dp
               and buffer.buffered_seconds() >
               config["generation"]["buffer_target_minutes"] * 60 * 0.5):
            time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
