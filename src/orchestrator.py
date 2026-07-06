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
import json
import re
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
_STATION_STATE = Path("station_state.json")
# beats that are structurally banned: the show never opens or closes itself
_BANNED_SEGMENT = re.compile(r"\b(intro|outro|monolog|open(ing)?|sign.?off|wrap|goodbye|farewell)\b", re.I)


def _sstate() -> dict:
    try:
        return json.loads(_STATION_STATE.read_text())
    except Exception:
        return {}


def _sstate_save(d: dict) -> None:
    tmp = _STATION_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d))
    tmp.replace(_STATION_STATE)


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


def _minutes_left(daypart: dict, now=None) -> float:
    """Minutes until this daypart's window closes."""
    now = now or _now()
    end = dtime.fromisoformat(daypart["window"][1])
    mins_now = now.hour * 60 + now.minute
    mins_end = end.hour * 60 + end.minute
    left = mins_end - mins_now
    if left <= 0:
        left += 24 * 60  # window wraps past midnight
    return float(left)


def _next_daypart(schedule: dict, daypart: dict) -> dict:
    dps = schedule["dayparts"]
    i = next((k for k, d in enumerate(dps) if d is daypart), 0)
    return dps[(i + 1) % len(dps)]


def _throw_beat(daypart: dict, nxt: dict) -> dict:
    """The one sanctioned wrap: the host hands the air to the next show."""
    cast = ", ".join(n.replace("_", " ") for n in nxt.get("cast", []))
    return {"segment": "Handoff",
            "premise": f"the show is ending; {nxt['show']} is next",
            "scheduled_handoff": True,
            "beat": (f"THIS IS A SCHEDULED HANDOFF BEAT — the one place a "
                     f"wrap-up is allowed. In character, briefly land the "
                     f"current thread, then throw to what's next on The "
                     f"Frequency: {nxt['show']} (host cast: {cast}). Tease it "
                     "warmly or wryly in one or two lines, hand over the air, "
                     "done. No long goodbyes."),
            "grounding": "the clock on the studio wall", "callback": None}


def _throttle(config: dict, live: bool):
    """Block while the buffer is comfortably ahead of playback."""
    if not live:
        return
    target = config["generation"]["buffer_target_minutes"] * 60
    while buffer.buffered_seconds() > target:
        time.sleep(30)


def _emit(lines: list[dict], label: str, config: dict, live: bool, fx=None):
    """Print the dialogue; in live mode also synthesize into the buffer."""
    for ln in lines:
        print(f"  [{ln.get('speaker')}] {ln.get('text')}")
    if live and lines:
        from .tts import synth_segment
        out = buffer.next_path(label)
        if synth_segment(lines, out, config, fx=fx) is None:
            return
        print(f"  ♪ {out.name}  (buffer: {buffer.buffered_seconds()/60:.1f} min)")


def _news_bulletin(config: dict, live: bool, daypart: dict | None = None):
    """Frequency News — real headlines, mangled. Cooldown survives restarts."""
    ncfg = config.get("news", {})
    if not ncfg.get("enabled") or (daypart and daypart.get("news", True) is False):
        return
    st = _sstate()
    if time.time() - st.get("last_news", 0) < 55 * 60:
        print("  (news skipped: bulletin aired within the hour)")
        return
    from .news import fetch_headlines, write_bulletin
    used = {h for h, ts in st.get("used_headlines", [])
            if time.time() - ts < 24 * 3600}
    heads = fetch_headlines(ncfg["feeds"], ncfg.get("headlines_per_bulletin", 4),
                            used=used)
    coming = daypart["show"] if daypart else ""
    script = write_bulletin(heads, config["models"],
                            Path("station/bible.md").read_text(),
                            coming_up=coming)
    lines = [{"speaker": "Frequency News", "voice": NEWS_VOICE, "text": ln.strip()}
             for ln in script.splitlines() if ln.strip()]
    print("\n--- Frequency News ---")
    _emit(lines, "news", config, live)
    st["last_news"] = time.time()
    st["used_headlines"] = ([[h, ts] for h, ts in st.get("used_headlines", [])
                             if time.time() - ts < 24 * 3600]
                            + [[h, time.time()] for h in heads])
    _sstate_save(st)


def _save_tail(daypart, lines):
    """Persist the last aired lines so a restart resumes mid-thought."""
    if not lines:
        return
    st = _sstate()
    st["tail"] = {"dp": daypart["id"], "ts": time.time(),
                  "lines": [{"speaker": ln.get("speaker"), "text": ln.get("text")}
                            for ln in lines[-6:]]}
    _sstate_save(st)


def _break_marker(daypart):
    """Queue a marker the player turns into an ad break (0.4s of silence)."""
    import wave as _w
    out = buffer.next_path(f"{daypart['id']}-break")
    tmp = out.with_name(out.name + ".part")
    with _w.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * 9600)
    tmp.replace(out)


_OPENER_OBJECTS = ["the mug", "the window", "the chair", "a pen that stopped working",
                   "the wall clock", "the carpet", "a ceiling tile", "the thermos",
                   "the notepad", "the microphone stand"]


def _tail_context(lines):
    tail = "\n".join(f"{ln.get('speaker')}: {ln.get('text')}" for ln in lines[-6:])
    return ("LAST LINES SPOKEN ON AIR (continue directly from these):\n" + tail
            if tail else "")


def run_show(daypart, config, schedule, live: bool):
    models = config["models"]
    state = lore.load()
    weekday = _now().strftime("%A")
    fx = daypart.get("id") if daypart.get("id") == "static_hour" else None

    print(f"\n{'='*70}\n  {daypart['show']}  ({daypart['window'][0]}-{daypart['window'][1]})"
          f"  —  {weekday}\n{'='*70}")

    # quick open — UNLESS this show aired within the last 15 min (a restart),
    # in which case resume mid-thought from the persisted tail: no opener loop
    opener_lines = []
    st0 = _sstate()
    tail = st0.get("tail") or {}
    if tail.get("dp") == daypart["id"] and time.time() - tail.get("ts", 0) < 15 * 60:
        opener_lines = tail.get("lines", [])
        print("  (recent tail found — skipping opener, resuming mid-thought)")
    else:
        try:
            import random as _r
            avoid = st0.get("last_open_obj")
            obj = _r.choice([o for o in _OPENER_OBJECTS if o != avoid])
            st0["last_open_obj"] = obj
            _sstate_save(st0)
            daypart["_target_lines"] = 6
            opener = {"segment": "Open", "premise": "mid-show, mid-thought",
                      "beat": f"resume mid-thought about {obj}, IN THIS "
                              "SHOW'S OWN REGISTER AND ENERGY. No greetings, no "
                              "welcome-backs, no teases, no running jokes, and NO "
                              "callers in this beat — just the host(s), mid-show.",
                      "no_bit": False}
            opener_lines = perform_beat(opener, daypart, models, state, "")
            _emit(opener_lines, f"{daypart['id']}-open", config, live, fx=fx)
            _save_tail(daypart, opener_lines)
        except Exception as e:
            print(f"  (opener skipped: {e})")

    try:
        _news_bulletin(config, live, daypart)
    except Exception as e:  # news must never kill the show
        print(f"  (news skipped: {e})")

    st = _sstate()
    opened_key = f"{daypart['id']}:{_now():%Y-%m-%d}"
    first_of_window = st.get("opened") != opened_key
    # bridge the outline latency: while the writer thinks (~1-3 min), a second
    # short beat generates and airs so a cold start never goes quiet
    with ThreadPoolExecutor(max_workers=1) as wpool:
        outline_fut = wpool.submit(write_outline, daypart, models, state,
                                   weekday, first_of_window)
        try:
            daypart["_target_lines"] = 10
            bridge = {"segment": "Bridge",
                      "premise": "carrying the moment while the show gathers itself",
                      "beat": "continue from AFTER the last thing said — the NEXT "
                              "thought, one small development forward, in this "
                              "show's own register. Do NOT restate, rephrase, or "
                              "summarize any line already spoken. No callers, no "
                              "greetings, no wrap."}
            _emit(perform_beat(bridge, daypart, models, state,
                               _tail_context(opener_lines),
                               avoid_lines=[l.get("text", "") for l in opener_lines]),
                  f"{daypart['id']}-bridge", config, live, fx=fx)
        except Exception as e:
            print(f"  (bridge skipped: {e})")
        outline = outline_fut.result()
    st["opened"] = opened_key
    _sstate_save(st)
    if outline.get("guest"):
        print(f"  GUEST: {outline['guest']}\n")
    # drop structurally banned beats — the prompt ban demonstrably fails at temp 0.9
    outline["beats"] = [b for b in outline.get("beats", [])
                        if not _BANNED_SEGMENT.search(str(b.get("segment", "")))]
    # persist premises IMMEDIATELY so anti-repetition survives restarts
    lore.remember(state, premises=[b.get("premise") for b in outline["beats"]
                                   if b.get("premise")])
    lore.save(state)

    daypart["_target_lines"] = daypart.get(
        "lines_per_beat", config["generation"].get("lines_per_beat", 22))
    parts = daypart.get("parts_per_beat",
                        config["generation"].get("parts_per_beat", 3))
    # each outline beat becomes N chained parts of one continuous scene
    beats = []
    for b in outline.get("beats", []):
        arc_show = bool(daypart.get("arc"))
        for pi in range(parts):
            bb = dict(b)
            bb["_part"] = pi
            bb["_guest"] = outline.get("guest")
            if pi > 0:
                bb["grounding"] = ""  # props don't repeat across parts
                if arc_show:
                    job = ("COMPLICATE it: introduce exactly one new wrinkle, "
                           "detail, or implication that moves the idea FORWARD"
                           if pi < parts - 1 else
                           "DRIVE to this beat's payoff — the layer lands, "
                           "fully formed, ready for the next layer")
                    bb["beat"] = (f"{b.get('beat')} (CONTINUE part {pi+1} of "
                                  f"{parts} of this same beat — and ADVANCE it. "
                                  f"Your job in this part: {job}. NEVER re-describe "
                                  "or re-open the scene; never reuse imagery, "
                                  "props, or phrases from the lines already "
                                  "spoken — reference them in passing at most, "
                                  "then move FORWARD.)")
                elif len(daypart.get("cast", [])) > 1:
                    # multi-host shows: the same disagreement DEEPENS across
                    # parts — that sustained bicker is the show
                    job = ("DIG IN: stay on the exact subject already in "
                           "dispute and go a layer deeper — each host defends "
                           "THEIR position with one new concrete argument, "
                           "example, or petty piece of evidence; nobody "
                           "concedes, nobody changes the subject"
                           if pi < parts - 1 else
                           "LAST WORD: the same argument reaches its pettiest, "
                           "most specific point and someone wins on a "
                           "technicality — you may gently land the bit now")
                    bb["beat"] = (f"{b.get('beat')} (CONTINUE this same ongoing scene, "
                                  f"part {pi+1} of {parts}: same characters and callers "
                                  f"still present, the SAME disagreement still live. {job}. "
                                  "Keep the absurdity at the level it already reached — "
                                  "escalate the argument, never the premise. Never "
                                  "re-describe the scene or repeat imagery already used.)")
                else:
                    bb["beat"] = (f"{b.get('beat')} (CONTINUE this same ongoing scene, "
                                  f"part {pi+1} of {parts}: same characters and callers still "
                                  "present. Develop the conversation naturally — follow-ups, "
                                  "small turns, warmth. Keep the absurdity at the level it "
                                  "already reached; do NOT escalate further. Never re-describe "
                                  "the scene or repeat imagery already used. The host stays "
                                  "grounded and sincere no matter how odd the caller gets"
                                  + ("" if pi < parts - 1 else ". You may gently land the bit now"))
            beats.append(bb)

    day_key = f"{_now():%Y-%m-%d}"
    if st.get("callers_day") != day_key:
        st["callers_day"], st["callers_today"] = day_key, []
    used_names = set(st.get("callers_today", []))

    def _context(i, prev_lines):
        """True continuity: outline recap + the actual last lines spoken,
        plus a hard scene break whenever a NEW outline beat starts."""
        recap = "" if i == 0 else f"{beats[i-1].get('segment')}: {beats[i-1].get('beat')}\n"
        tail = "\n".join(f"{ln.get('speaker')}: {ln.get('text')}"
                          for ln in prev_lines[-6:])
        ctx = recap + ("LAST LINES SPOKEN ON AIR (continue directly from these):\n"
                       + tail if tail else "")
        if used_names:
            ctx += ("\nCaller names already used today anywhere on the station "
                    "(do NOT reuse any): " + ", ".join(sorted(used_names)))
        if i > 0 and beats[i].get("_part", 0) == 0:
            if (daypart.get("guest_role") in ("host", "persistent")
                    and beats[i].get("_guest")):
                ctx += ("\nSCENE BREAK: any previous CALLER is gone — but "
                        f"tonight's guest ({beats[i]['_guest']}) is STILL in the "
                        "studio; keep them present and speaking.")
            else:
                ctx += ("\nSCENE BREAK: the previous caller/guest hung up and is "
                        "GONE — do not mention them. Open on the NEW beat with a "
                        "new caller if the beat needs one.")
        return ctx.strip()

    # prefetch: next beat's dialogue generates while current beat synthesizes
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(perform_beat, beats[0], daypart, models, state,
                          _context(0, opener_lines),
                          [l.get("text", "") for l in opener_lines]) if beats else None
        threw = False
        for i, beat in enumerate(beats):
            # near the window's end: throw to the next show instead of
            # starting another beat the boundary would cut off
            if not threw and _minutes_left(daypart) < 7:
                nxt = _next_daypart(schedule, daypart)
                print(f"\n--- Handoff -> {nxt['show']} ---")
                daypart["_target_lines"] = 6
                lines = perform_beat(_throw_beat(daypart, nxt), daypart,
                                     models, state, _context(i, lines if i else opener_lines))
                _emit(lines, f"{daypart['id']}-handoff", config, live, fx=fx)
                break
            # never generate past the daypart boundary — the next show owns it
            if _current_daypart(schedule, _now()) is not daypart:
                print("  (daypart ended — handing over to the next show)")
                break
            _throttle(config, live)
            lines = fut.result()
            new_names = False
            for ln in lines:  # track caller names for the no-reuse blacklist
                spk = str(ln.get("speaker", ""))
                if ln.get("phone") and spk:
                    first = spk.split()[0]
                    if first not in used_names:
                        used_names.add(first)
                        new_names = True
            if new_names:  # persist across restarts, capped, day-scoped
                st["callers_today"] = sorted(used_names)[-40:]
                _sstate_save(st)
            if i + 1 < len(beats):
                fut = pool.submit(perform_beat, beats[i + 1], daypart, models,
                                  state, _context(i + 1, lines))
            print(f"\n--- {beat.get('segment')} ---")
            _emit(lines, f"{daypart['id']}-{beat.get('segment', 'seg')}", config, live, fx=fx)
            if lines:  # keep the tail fresh so any restart resumes mid-thought
                _save_tail(daypart, lines)

    if daypart.get("arc"):
        st = _sstate()
        if (st.get("hole") or {}).get("dp") == daypart["id"]:
            st["hole"]["finished"] = True
            _sstate_save(st)
    # persist any new lore the writer established (max 2 new jokes per show
    # so no single bit can flood the lore pool)
    # the arc show's conspiracies must NEVER enter shared lore — they resurface
    # as callbacks/running jokes in daytime shows and conspiracy-code them
    arc_quarantine = bool(daypart.get("arc"))
    lore.remember(state,
                  jokes=([] if arc_quarantine else (outline.get("new_jokes") or [])[:2]),
                  guest=outline.get("guest"),
                  callbacks=([] if arc_quarantine else outline.get("callbacks_used")))
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
            st = _sstate()
            if args.live and time.time() - st.get("last_spots", 0) > 30 * 60:
                from . import spots
                spots.refresh(config, config["models"],
                              Path("station/bible.md").read_text())
                st["last_spots"] = time.time()
                _sstate_save(st)
        except Exception as e:
            print(f"  (spot refresh skipped: {e})")
        try:
            run_show(dp, config, schedule, live=args.live)
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
