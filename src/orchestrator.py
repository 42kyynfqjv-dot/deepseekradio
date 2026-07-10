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
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dtime
from pathlib import Path

import yaml

from . import buffer, clock, lore
from . import switchboard as _switch
from . import continuity as _cont
from .openrouter import METER
from .performers import perform_beat, _persona
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
    """Day-gated blocks (days: [Wednesday, ...]) are listed FIRST and win over
    the everyday block sharing their window; on off days they don't exist."""
    t = now.time()
    for dp in schedule["dayparts"]:
        days = dp.get("days")
        if days and now.strftime("%A") not in days:
            continue
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
    """Whoever owns the air one minute after this window closes — respects
    day gating, so the handoff names the right show on game nights."""
    from datetime import timedelta
    end = dtime.fromisoformat(daypart["window"][1])
    probe = clock.air_now().replace(hour=end.hour, minute=end.minute,
                                    second=0) + timedelta(minutes=1)
    if end <= clock.air_now().time():   # window closes after midnight
        probe += timedelta(days=1)
    nxt = _current_daypart(schedule, probe)
    return nxt if nxt is not daypart else schedule["dayparts"][0]


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
    bible = Path("station/bible.md").read_text()
    script = write_bulletin(heads, config["models"], bible, coming_up=coming)
    lines = [{"speaker": "Frequency News", "voice": NEWS_VOICE, "text": ln.strip()}
             for ln in script.splitlines() if ln.strip()]
    # radio furniture: the legal ID + this hour's billboard sponsor lead the
    # bulletin — code-picked (date+hour seeded) so the LLM never chooses
    try:
        from .spots import _roster
        import random as _rnd
        roster = _roster(bible)
        if roster:
            name, gag = _rnd.Random(f"billboard:{clock.air_now():%Y-%m-%d-%H}"
                                    ).choice(roster)
            lines.insert(0, {"speaker": "Station ID", "voice": NEWS_VOICE,
                             "text": f"W-F-R-Q, one oh eight point one, Halfway "
                                     f"— it's about {clock.spoken_air_time()}. "
                                     f"This is The Frequency. This hour is "
                                     f"brought to you by {name} — {gag}."})
    except Exception:
        pass
    try:  # the Sports Desk rides every bulletin: last night in the league,
        # named scorers, straight off the box shards — wire copy, guard-true
        from datetime import date as _d, timedelta as _td
        from .league import engine as _lge, briefs as _lgb
        from . import season as _sn
        y = (_d.fromisoformat(f"{clock.air_now():%Y-%m-%d}")
             - _td(days=1)).isoformat()
        shard = _lge.load_side(f"box/{y}.json")
        pl = _lge.load_side(f"players-s{_sn._load()['season']}.json")
        if shard and pl and shard.get("games"):
            desk = _lgb.scores_desk(y, shard["games"], pl, n=4)
            if desk:
                lines.append({"speaker": "Frequency Sports",
                              "voice": NEWS_VOICE,
                              "text": "Sports desk. " + desk})
    except Exception as e:
        print(f"  (sports desk skipped: {e})")
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
    if daypart.get("id") == "center_ice":   # live sports is its own machine
        return run_center_ice(daypart, config, schedule, live)
    models = config["models"]
    state = lore.load()
    weekday = clock.air_now().strftime("%A")  # the day it will AIR
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
            # a genuine show change: the incoming host OPENS the hour — introduces
            # themselves and the show, and (if taking the air from another show)
            # thanks that host by name for the handoff. The prior show's lines are
            # NEVER fed in — only the fact of who to thank crosses the boundary, so
            # the new host opens fresh instead of continuing the last show.
            prev_dp = next((d for d in schedule.get("dayparts", [])
                            if d["id"] == tail.get("dp")), None)
            handed_over = (prev_dp and tail.get("dp") != daypart["id"]
                           and time.time() - tail.get("ts", 0) < 25 * 60)
            if handed_over and prev_dp.get("cast"):
                pv = _persona(prev_dp["cast"][0])[0]
                thanks = (f"You are just taking the air from {pv} on "
                          f"{prev_dp.get('show')}. Open with ONE warm, in-character "
                          f"line thanking {pv} for the handoff, then ")
            else:
                thanks = "You are just coming on the air. "
            daypart["_target_lines"] = 6
            opener = {"segment": "Open", "premise": "top of the hour — the show opens",
                      "beat": thanks + "introduce yourself and your show, "
                              f"{daypart['show']}, and set the hour in motion — a real "
                              "radio open, warm and brief, IN THIS SHOW'S OWN REGISTER "
                              "AND ENERGY. A greeting is welcome here. No callers in "
                              "this beat.",
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

    daypart.pop("_arc_extra", None)

    st = _sstate()
    # serialized station arcs advance once per air-day (story editor pass)
    if st.get("arcs_day") != f"{clock.air_now():%Y-%m-%d}":
        try:
            from . import arcs
            arcs.daily_tick(models, state)
            lore.save(state)
            st["arcs_day"] = f"{clock.air_now():%Y-%m-%d}"
            _sstate_save(st)
        except Exception as e:  # storylines are garnish, never a blocker
            print(f"  (arc tick skipped: {e})")
    opened_key = f"{daypart['id']}:{clock.air_now():%Y-%m-%d}"
    first_of_window = st.get("opened") != opened_key
    if daypart.get("id") == "morning_scramble" and first_of_window:
        try:  # Wesley's REAL forecast: fetched ONCE per show window (network
            # call must never sit in the hot re-outline loop), persists on the
            # shared daypart dict for the rest of the window
            from .spots import _real_forecast
            daypart["_extra_context"] = (
                "Wesley's forecast uses TODAY'S REAL weather (keep the numbers "
                "roughly right; the delivery is all his): " + _real_forecast())
        except Exception:
            pass
    try:  # the assignment desk: code picks guest/sponsor/callback/props —
        # the writer authors around assignments instead of operating choices
        from . import assignments as _adesk
        from .spots import _roster as _sroster
        _arng = random.Random(f"assign:{clock.air_now():%Y-%m-%d}:{daypart['id']}")
        _bible = Path("station/bible.md").read_text()
        _gp = Path("personas/guests.md")
        _ros = _sroster(_bible)
        daypart["_assign"] = {
            "guest": _adesk.pick_guest(_gp.read_text() if _gp.exists() else "",
                                       state.get("guests_seen", []), _arng),
            "sponsor": _arng.choice(_ros) if _ros else None,
            "callback": _adesk.pick_callback(state, _arng),
            "props": _adesk.prop_candidates(
                state.get("recent_grounding", []), _arng),
        }
    except Exception as e:
        print(f"  (assignment desk skipped: {e})")
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
    # persist premises AND grounding props IMMEDIATELY so anti-repetition
    # (including the worn-out-subject ban) survives restarts
    lore.remember(state,
                  premises=[b.get("premise") for b in outline["beats"]
                            if b.get("premise")],
                  grounding=[b.get("grounding") for b in outline["beats"]
                             if b.get("grounding")])
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

    # the guest is sent off ONCE, on their final beat — never mid-interview,
    # so the host can't say goodbye and then re-engage the same guest
    _gidx = [j for j, gb in enumerate(beats) if gb.get("_guest")]
    if _gidx:
        beats[_gidx[-1]]["_guest_last"] = True

    day_key = f"{clock.air_now():%Y-%m-%d}"
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
            if beats[i].get("_guest"):
                ctx += ("\nSCENE BREAK: any previous CALLER is gone — but "
                        f"tonight's guest ({beats[i]['_guest']}) is STILL in the "
                        "studio, mid-interview; keep them present and speaking, and "
                        "do NOT thank, wrap, or say goodbye to the guest here.")
            else:
                ctx += ("\nSCENE BREAK: the previous caller/guest hung up and is "
                        "GONE — do not mention them. Open on the NEW beat with a "
                        "new caller if the beat needs one.")
        return ctx.strip()

    def _tail_texts(prev_lines):
        """The lines the next beat is told to continue from — and must never
        restate ('And now traffic' airing twice in a row)."""
        return [l.get("text", "") for l in prev_lines[-8:]]

    # prefetch: next beat's dialogue generates while current beat synthesizes
    with ThreadPoolExecutor(max_workers=1) as pool:
        call_st = None      # the switchboard: code owns who is on the line
        daypart["_switchboard"] = _switch.prompt_line(call_st)
        fut = pool.submit(perform_beat, beats[0], daypart, models, state,
                          _context(0, opener_lines),
                          _tail_texts(opener_lines)) if beats else None
        threw = False
        parts_since_break = 0
        for i, beat in enumerate(beats):
            # near the window's end ON AIR: throw to the next show instead of
            # starting another beat the boundary would cut off. Wall time is
            # wrong here — this beat airs buffered_seconds from now, so a
            # wall-clock check teases a handoff and then keeps generating.
            if not threw and _minutes_left(daypart, clock.air_now()) < 7:
                nxt = _next_daypart(schedule, daypart)
                print(f"\n--- Handoff -> {nxt['show']} ---")
                daypart["_target_lines"] = 6
                prev = lines if i else opener_lines
                lines = perform_beat(_throw_beat(daypart, nxt), daypart,
                                     models, state, _context(i, prev),
                                     _tail_texts(prev))
                _emit(lines, f"{daypart['id']}-handoff", config, live, fx=fx)
                # the sign-off is TERMINAL: mark the window handed off so the main
                # loop won't re-invoke this show and ramble past the goodbye. The
                # next show's first audio triggers the station bumper on show-change.
                if live:
                    hs = _sstate(); hs["handed_off"] = opened_key; _sstate_save(hs)
                break
            # never generate past the daypart's AIR boundary — the next show
            # owns everything that would air after it
            if _current_daypart(schedule, clock.air_now()) is not daypart:
                print("  (daypart ended — handing over to the next show)")
                break
            _throttle(config, live)
            lines = fut.result()
            _pol = (daypart.get("caller_policy") or {}).get("max_lines")
            lines, call_st = _switch.enforce(
                lines, call_st,
                budget=3 * _pol if _pol else _switch.DEFAULT_BUDGET,
                host=_cast_meta(daypart, 0))
            daypart["_switchboard"] = _switch.prompt_line(call_st)
            try:  # the desk mints the next caller: name+voice deterministic
                from . import assignments as _adesk
                _nm = _adesk.next_caller(
                    used_names, random.Random(
                        f"caller:{clock.air_now():%Y-%m-%d}:{daypart['id']}:{i}"))
                daypart["_switchboard"] += (f" If a NEW caller joins, their "
                                            f"name is {_nm}.")
            except Exception:
                pass
            _is_throw = bool(beat.get("scheduled_handoff") or beat.get("ad_throw"))
            lines, _wb = _cont.enforce(lines, handoff=_is_throw)
            daypart["_show_clock"] = _cont.show_clock_line(
                _minutes_left(daypart, clock.air_now()))
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
                                  state, _context(i + 1, lines),
                                  _tail_texts(lines))
            print(f"\n--- {beat.get('segment')} ---")
            _emit(lines, f"{daypart['id']}-{beat.get('segment', 'seg')}", config, live, fx=fx)
            if _wb and live and not _is_throw:
                _break_marker(daypart)   # a promised break is a KEPT break
            if lines:  # keep the tail fresh so any restart resumes mid-thought
                _save_tail(daypart, lines)
            parts_since_break += 1
            # host-announced ad break at a per-show, real-radio cadence
            # (ad_interval_min in schedule.yaml; ~2.2 min of air per part).
            # Default ~10 min; the Static Hour runs sparse (~22). The host
            # throws to it knowingly; the player turns the marker into spots
            # (and always backs it with a bumper if no spot is ready). Not near
            # a handoff, not on ad-free shows.
            _ad_parts = max(3, round(daypart.get("ad_interval_min", 10) / 2.2))
            if (parts_since_break >= _ad_parts and daypart.get("sponsor") != "none"
                    and _minutes_left(daypart, clock.air_now()) > 12):
                try:
                    target = daypart["_target_lines"]
                    daypart["_target_lines"] = 4
                    throw = {"segment": "Ad Throw", "ad_throw": True,
                             "premise": "throwing to a short break",
                             "beat": ("In one or two lines, in character, throw "
                                      "to a short break — tease what's coming "
                                      "after, no goodbyes."),
                             "grounding": "", "callback": None,
                             "_part": 0, "_guest": beat.get("_guest")}
                    tl = perform_beat(throw, daypart, models, state,
                                      _context(i + 1, lines) if i + 1 < len(beats)
                                      else "", _tail_texts(lines))
                    _emit(tl, f"{daypart['id']}-adthrow", config, live, fx=fx)
                    daypart["_target_lines"] = target
                    if live:
                        _break_marker(daypart)
                    parts_since_break = 0
                except Exception as e:  # a failed throw must not stop the show
                    print(f"  (ad throw skipped: {e})")
                    daypart["_target_lines"] = target

    if daypart.get("arc"):
        st = _sstate()
        if (st.get("hole") or {}).get("dp") == daypart["id"]:
            st["hole"]["finished"] = True
            _sstate_save(st)
    # persist any new lore the writer established (max 2 new jokes per show
    # so no single bit can flood the lore pool)
    # quarantined shows (the Watcher) must NEVER seed shared lore — their
    # conspiracies resurface as daytime callbacks. Other arc shows (Center
    # Ice) SHOULD: the whole station gets to care about the Apologies.
    arc_quarantine = bool(daypart.get("lore_quarantine"))
    lore.remember(state,
                  jokes=([] if arc_quarantine else (outline.get("new_jokes") or [])[:2]),
                  guest=outline.get("guest"),
                  callbacks=([] if arc_quarantine else outline.get("callbacks_used")))
    lore.save(state)
    print(f"\n  cost so far this run: {METER.summary()}")


def _cast_meta(daypart, idx=0):
    """(speaker/voice/speed) for a cast member — for code-authored lines."""
    from .performers import _persona
    display, text = _persona(daypart["cast"][idx])
    m = re.search(r"^voice:\s*(.+)$", text, re.M)
    ms = re.search(r"^speed:\s*(.+)$", text, re.M)
    return {"speaker": display,
            "voice": m.group(1).strip() if m else "am_adam",
            "speed": float(ms.group(1)) if ms else 1.0}


def run_center_ice(daypart, config, schedule, live: bool):
    """Center Ice, fully live: the engine rolls the game in lockstep with
    generation (advance on THIS thread; the prefetch pool only ever writes
    dialogue for already-rolled facts), every emitted line is fact-checked
    against the code-owned board, and the game ALWAYS reaches a recorded
    final — the try/finally and the season tick's reconciliation sweep make
    that true through crashes, restarts, and short windows."""
    from . import livegame, season
    from .scoreguard import build_facts, enforce_scoreboard
    from .nameguard import enforce_names
    from .sfx import tag_sfx

    # the league's invented name pools: any of these is in-universe and must
    # never be scrubbed as a "real" name, even off tonight's roster
    pool_ok = frozenset(w.lower()
                        for w in livegame.FIRST_NAMES + livegame.LAST_NAMES)

    models = config["models"]
    state = lore.load()
    date = f"{clock.air_now():%Y-%m-%d}"
    weekday = clock.air_now().strftime("%A")
    game = season.tonight_live(date)
    hn, an = game["home"], game["away"]
    print(f"\n{'='*70}\n  {daypart['show']} LIVE — the {an} at the {hn}, "
          f"{weekday} {date}\n{'='*70}")
    try:
        eng = livegame.LiveGame(game)
    except RuntimeError as e:
        print(f"  !! center ice locked out: {e}")
        time.sleep(30)
        return
    pbp = _cast_meta(daypart, 0)
    allow = season.context_pairs(game)
    t_open = time.time()      # the reveal clock's broadcast anchor (G1)
    try:  # publish the anchor so the WEBSITE reveals other games on the SAME
        # clock as the booth — the site must never show a final the desk is
        # still calling as in-progress
        from .league import engine as _lge0
        _lge0.save_side("air-anchor.json", {"date": date, "t0": t_open})
    except Exception:
        pass
    lines_target = int(daypart.get("lines_per_beat", 22))
    parts_per = max(1, int(daypart.get("parts_per_beat", 2)))
    slot_cost = parts_per * 2.1 + 0.5        # air-min per chunk incl. breaks
    aired: list = eng.narrated_events()      # events already written to air

    def _ev_text(e):
        team = hn if e["team"] == "home" else an
        if e["type"] == "goal":
            a = f" (assist {e['assist']})" if e.get("assist") else " (unassisted)"
            tag = {"PP": " on the POWER PLAY", "SH": " SHORTHANDED",
                   "EN": " into an EMPTY NET"}.get(e["strength"], "")
            return (f"GOAL {team}: {e['scorer']}{a}{tag} at {e['clock']} — "
                    f"the board becomes {hn} {e['board'][0]}, {an} {e['board'][1]}")
        if e["type"] == "penalty":
            return (f"PENALTY {team}: {e['player']}, 2 minutes, {e['call']}, "
                    f"at {e['clock']}")
        if e["type"] == "injury":
            return (f"INJURY {team}: {e['player']} leaves the game, listed "
                    f"{e['note']} — keep it light and PG, hockey euphemism")
        if e["type"] == "pull":
            return f"{team} PULL THE GOALIE — empty net, extra attacker on"
        if e["type"] == "return":
            return f"{team} goalie is back in the net"
        if e["type"] == "so":
            return (f"SHOOTOUT round {e['round']}: {e['player']} ({team}) "
                    f"{'SCORES' if e['scored'] else 'is STOPPED'}")
        return ""

    def _facts(part_events, board_in, *, mode="live", period=None, lo=None,
               hi=None, pp=False, en=False, final=None, shots=None,
               allow_extra=()):
        chunk = ({"board_in": list(board_in), "events": part_events,
                  "pp_span": pp, "en_span": en} if mode == "live" else None)
        return build_facts(game, list(aired), chunk, mode=mode, pbp=pbp,
                           allow_pairs=list(allow) + list(allow_extra),
                           final=final, shots=shots,
                           period=period, clock_lo=lo, clock_hi=hi)

    def _beat(seg, premise, text, facts, *, label, lines=None, events=(),
              mark=(), brk=False, part=0, interview=False):
        return {"beat": {"segment": seg, "premise": premise, "beat": text,
                         "grounding": "", "callback": None, "no_bit": False,
                         "monologue": False, "_part": part},
                "facts": facts, "label": label,
                "lines": lines or lines_target, "interview": interview,
                "events": list(events), "mark": list(mark), "brk": brk}

    def _board_txt(b):
        return f"{hn} {b[0]}, {an} {b[1]}"

    def _chunk_beats(ch, brk_after=False):
        """One rolled chunk -> parts_per scene parts, each auditing its own
        slice of events (so an unnarrated goal is injected exactly once).
        A GENERATOR: each part's fact table is built only when it's up, so
        its tallies include every earlier part's goals."""
        f0, t0 = ch["from"], ch["to"]
        period = livegame._period_of(f0)
        pname = {1: "first period", 2: "second period",
                 3: "third period"}.get(period, "overtime")
        timed = [e for e in ch["events"] if "secs" in e]
        so_evs = [e for e in ch["events"] if e["type"] == "so"]
        base = livegame.REG_SECS if period == "OT" else (period - 1) * livegame.PERIOD_SECS
        bounds = [f0 + (t0 - f0) * i / parts_per for i in range(parts_per + 1)]
        board = list(ch["board_in"])
        for pi in range(parts_per):
            lo_s, hi_s = bounds[pi], bounds[pi + 1]
            sl = [e for e in timed
                  if lo_s <= e["secs"] < hi_s or (pi == parts_per - 1
                                                  and e["secs"] >= hi_s)]
            if pi == parts_per - 1:
                sl += so_evs
            goals = [e for e in sl if e["type"] == "goal"]
            end_board = list(goals[-1]["board"]) if goals else list(board)
            if so_evs and pi == parts_per - 1:
                end_board = list(ch["board"])
            lo_rel = max(0, int(lo_s) - base)
            hi_rel = min(int(hi_s) - base,
                         livegame.OT_SECS if period == "OT" else livegame.PERIOD_SECS)
            evtx = "\n".join(_ev_text(e) for e in sl) or (
                "No goals, no penalties in this stretch — carry it on saves, "
                "chances, posts, and the booth.")
            cont = ("" if pi == 0 else
                    f" (CONTINUE the same live broadcast, part {pi+1} of "
                    f"{parts_per} — same flow, never re-describe or reset the "
                    "scene, never repeat a call already made.)")
            text = (
                f"LIVE play-by-play, the {pname}, covering roughly "
                f"{lo_rel//60}:{lo_rel%60:02d}-{hi_rel//60}:{hi_rel%60:02d} "
                f"elapsed.{cont}\nSCOREBOARD entering this stretch "
                f"(authoritative, never contradict): {_board_txt(board)}.\n"
                f"EVENTS IN THIS STRETCH (call ALL of them, in order, as they "
                f"happen — add saves, rushes, and near-misses between them, "
                f"but NO other goals, penalties, or injuries):\n{evtx}\n"
                f"The stretch ends with the board {_board_txt(end_board)}. "
                "You do NOT know anything past this stretch.")
            marks = [ch["chunk"]] if pi == parts_per - 1 else []
            yield _beat(
                f"{pname.title()}" if period != "OT" else "Overtime",
                f"live game, {pname}", text,
                _facts(sl, board, period=(None if so_evs and pi == parts_per - 1
                                          else period),
                       lo=f"{lo_rel//60}:{lo_rel%60:02d}",
                       hi=f"{hi_rel//60}:{hi_rel%60:02d}",
                       pp=ch["pp_span"], en=ch["en_span"]),
                label=str(ch["chunk"]).lower(), events=sl, mark=marks,
                brk=(brk_after and pi == parts_per - 1), part=pi)
            board = end_board

    def _air_left():
        return _minutes_left(daypart, clock.air_now())

    def _owns_air():
        return _current_daypart(schedule, clock.air_now()) is daypart

    wpool = ThreadPoolExecutor(max_workers=1)

    def plan():
        """Yields beat descriptors one at a time — runs on the MAIN thread
        between beats, which is where every engine roll happens."""
        did_game = eng.final is None
        # phase 0: pregame (fresh), rejoin (mid-game restart), or neither.
        # gate on the OPENED marker (not _order) so a restart after the pregame
        # aired but before the first chunk rolled never replays the open.
        if eng.final is None and not eng.opened and not eng._order:
            pre = season.pregame_brief(game)
            f = _facts([], [0, 0], mode="neutral")
            for pi in range(parts_per):
                cont = ("Open the broadcast: set the matchup, the records, "
                        "the goalies, the officials, tonight's storylines. "
                        "Warm professional sports energy."
                        if pi == 0 else
                        f"(CONTINUE the pregame, part {pi+1} of {parts_per} — "
                        "develop the storylines and the booth color subplot, "
                        "never re-open the show.)")
                yield _beat("Pregame", "pregame at the rink",
                            f"{pre}\n{cont}", f, label="pregame", part=pi,
                            brk=(pi == parts_per - 1))
        elif eng.final is None:
            backlog = eng.unnarrated()
            evs = [e for c in backlog for e in c["events"]]
            s = eng.state()
            board_in = (list(backlog[0]["board_in"]) if backlog
                        else list(s["board"]))
            evtx = ("\n".join(_ev_text(e) for e in evs) if evs else
                    "(nothing new since the last call)")
            f = _facts(evs, board_in,
                       pp=any(c["pp_span"] for c in backlog),
                       en=any(c["en_span"] for c in backlog))
            pos = ("overtime" if s["period"] == "OT"
                   else f"period {s['period']}")
            yield _beat(
                "Rejoin", "back to live coverage",
                "REJOIN THE LIVE BROADCAST mid-game (brief technical hiccup — "
                "do NOT dwell on it, one wry line at most). SCOREBOARD "
                f"(authoritative): {_board_txt(s['board'])}, {s['clock']} "
                f"elapsed of {pos}. FIRST catch the listener up on what just "
                f"happened:\n{evtx}\nThen settle back into live coverage.",
                f, label="rejoin", lines=14, events=evs,
                mark=[c["chunk"] for c in backlog])

        # phase 1: the game, rolled chunk by chunk at the pace the air allows
        chunk_no = {}
        while eng.final is None:
            s = eng.state()
            air_left = _air_left()
            rem_min = (livegame.REG_SECS - min(s["secs"],
                                               livegame.REG_SECS)) / 60.0
            slots = max(1, int((air_left - 10) // slot_cost))
            # NHL-real: you never abandon a game in the third period or OT —
            # it SPILLS past the window and the next show starts late (the
            # buffer covers the gap; the site shows the game still live).
            in_late = s["secs"] >= 2 * livegame.PERIOD_SECS
            cramped = (not in_late) and (not _owns_air() or air_left < 14
                       or (s["secs"] < livegame.REG_SECS
                           and rem_min / slots > 10))
            if cramped:
                ch = eng.finish_now()
                evs = ch["events"]
                fin = eng.final
                text = (
                    "UP AGAINST THE CLOCK — compress the rest of this game "
                    "into one urgent, honest stretch of play-by-play. Call "
                    "every event below in order, quickly:\n"
                    + ("\n".join(_ev_text(e) for e in evs) if evs else
                       "(no further scoring)") + "\n"
                    f"THE FINAL HORN SOUNDS: {hn} {fin['h']}, {an} {fin['a']}"
                    f"{' in overtime' if fin['ot'] else ''}"
                    f"{' in a shootout' if fin['so'] else ''}.")
                yield _beat("To the Horn", "racing the clock", text,
                            _facts(evs, ch["board_in"], pp=ch["pp_span"],
                                   en=ch["en_span"]),
                            label="scramble", lines=16, events=evs,
                            mark=[ch["chunk"]])
                break
            if s["secs"] >= livegame.REG_SECS:      # tied after regulation
                ch = eng.advance("OT", livegame.REG_SECS + livegame.OT_SECS)
                for b in _chunk_beats(ch):
                    yield b
                continue
            period = s["secs"] // livegame.PERIOD_SECS + 1
            period_end = period * livegame.PERIOD_SECS
            chunk_min = min(max(rem_min / slots, 4.0), 10.0)
            to = min(period_end, s["secs"] + int(chunk_min * 60))
            n = chunk_no.get(period, 0) + 1
            chunk_no[period] = n
            ch = eng.advance(f"P{period}C{n}", to)
            ends_period = ch["to"] >= period_end and period < 3
            for b in _chunk_beats(ch, brk_after=(n == 2 or ends_period)):
                yield b
            if ends_period and eng.final is None:
                bd = eng.state()["board"]
                # a real intermission: report -> scores desk -> walk-off guest
                pgoals = [e for e in aired if e.get("type") == "goal"
                          and e.get("period") == period]
                recap = ("\n".join(_ev_text(e) for e in pgoals)
                         or "No goals this period — carry it on chances and saves.")
                # v2: the reveal-clock around-the-league — other games appear
                # IN PROGRESS at this point of our broadcast, scorers named;
                # every revealed pair joins the guard whitelist. v1: finals,
                # sliced per period so the desk never repeats itself.
                desk, desk_pairs = "", []
                try:
                    from .league import engine as _lge, briefs as _lgb
                    if _lge.v2_on(game["season"]):
                        boxes = (_lge.load_side(f"box/{date}.json")
                                 or {}).get("games", [])
                        pl2 = _lge.load_side(f"players-s{game['season']}.json")
                        st2 = _lge.load_side(f"stats-s{game['season']}.json")
                        sheet = _lgb.intermission_sheet(
                            date, int(time.time() - t_open), boxes,
                            st2 or {}, pl2 or {})
                        rows = sheet.get("around", [])[:5]
                        bits = []
                        for r in rows:
                            s = r.get("score") or [0, 0]
                            tag = (" final" if r.get("status") == "final" else
                                   f" ({r.get('period','')} {r.get('clock','')})"
                                   if r.get("status") == "live" else " upcoming")
                            who = (" — " + ", ".join(r["scorers"])
                                   if r.get("scorers") else "")
                            bits.append(f"{r['away']} {s[1]}, {r['home']} "
                                        f"{s[0]}{tag}{who}")
                            desk_pairs.append((s[0], s[1]))
                        desk = "; ".join(bits)
                        if sheet.get("race_note"):
                            desk += f". {sheet['race_note']}"
                except Exception as e:
                    print(f"  (v2 intermission sheet unavailable: {e})")
                if not desk:
                    slate = season.slate_scores(date)
                    lo_i = (period - 1) * 4
                    desk = "; ".join(slate[lo_i:lo_i + 4] or slate[:4])
                f = _facts([], bd, mode="neutral", allow_extra=desk_pairs)
                color = (f"the booth color subplot develops: {game['subplot']}"
                         if period == 1 else
                         "Sal delivers one magnificent unverifiable statistic")
                yield _beat(
                    f"Intermission {period}", "the intermission report",
                    f"INTERMISSION {period} REPORT. SCOREBOARD (authoritative, "
                    f"the game is PAUSED at exactly this): {_board_txt(bd)}.\n"
                    f"First, recap THIS period — these are the ONLY goals:\n"
                    f"{recap}\nThen the AROUND THE LEAGUE scores desk — tonight's "
                    "results, authoritative, read three or four of them "
                    f"naturally: {desk or '(no other games tonight)'}.\n"
                    f"Then {color}. You do NOT know anything about the rest of "
                    "this game.",
                    f, label=f"int{period}", part=0)
                if parts_per > 1:
                    star = (pgoals[-1]["scorer"] if pgoals else
                            game["rosters"]["home"]["skaters"][period % 3])
                    team = (game[pgoals[-1]["team"]] if pgoals
                            else game["home"])
                    yield _beat(
                        f"Intermission {period}", "the walk-off interview",
                        f"INTERMISSION {period}, RINK-SIDE. SCOREBOARD "
                        f"(authoritative): {_board_txt(bd)}. The booth throws "
                        f"down to rink-side reporter Donna Marsh, standing with "
                        f"{star} of the {team}. She asks three or four short "
                        f"questions about THIS period only; {star} answers in "
                        "warm hockey-cliche deadpan (pucks in deep, one shift "
                        "at a time) with ONE oddly specific human detail. Then "
                        "back up to the booth. You do NOT know anything about "
                        "the rest of the game.",
                        f, label=f"int{period}", part=1, lines=14,
                        interview=True)

        # the horn: fold the result NOW (site display is air-gated), then wrap
        fin = eng.final
        res = season.record_live(date)
        if res:
            lore.remember(state, callbacks=[res])
            lore.save(state)
            print(f"  {res}")
        if did_game:
            dp2 = dict(daypart)
            dp2["arc"] = season.postgame_brief(game, fin)
            dp2["segments"] = ["Callers React — delighted, devastated, weirdly neutral",
                               "The Re-Argument — the booth relitigates one moment",
                               "Standings Talk — what tonight means",
                               "Looking Ahead — next broadcast"]
            outline_fut = wpool.submit(write_outline, dp2, models, state,
                                       weekday, False)
            how = (" IN OVERTIME" if fin["ot"] else
                   " IN A SHOOTOUT" if fin["so"] else "")
            pf = _facts([], None, mode="postgame",
                        final=[fin["h"], fin["a"]], shots=fin["shots"])
            yield _beat(
                "Final Horn", "the final horn",
                f"THE FINAL HORN. FINAL (authoritative): {hn} {fin['h']}, "
                f"{an} {fin['a']}{how}. Shots: {hn} {fin['shots'][0]}, {an} "
                f"{fin['shots'][1]}. Wrap the game and the subplot "
                f"({game['subplot']}), what it means for the standings — then "
                "tease the three stars and that the phone lines are opening.",
                pf, label="wrap", brk=True)
            stars = fin.get("stars") or []
            if len(stars) >= 3:
                yield _beat(
                    "Three Stars", "three stars and the walk-off",
                    "POSTGAME AT THE GLASS. FINAL (authoritative, never "
                    f"contradict): {hn} {fin['h']}, {an} {fin['a']}{how}.\n"
                    "First the PA-style three-stars announcement, read in "
                    f"REVERSE order — third star: {stars[2]}; second star: "
                    f"{stars[1]}; FIRST star: {stars[0]}.\nThen rink-side "
                    f"reporter Donna Marsh grabs the first star, {stars[0]}, "
                    "for the walk-off interview: three or four short "
                    "questions about tonight; answers in warm hockey-cliche "
                    "deadpan with ONE oddly specific human detail. Back to "
                    "the booth to tease the phone lines.",
                    pf, label="stars", lines=16, interview=True)
            if game.get("coaches"):     # arrives with the league engine
                wside = "home" if fin["h"] > fin["a"] else "away"
                yield _beat(
                    "Coach's Corner", "the winning coach presser",
                    f"POSTGAME PRESSER. FINAL (authoritative): {hn} {fin['h']}, "
                    f"{an} {fin['a']}{how}. Winning head coach "
                    f"{game['coaches'][wside]} takes four or five questions — "
                    "measured, cliche-armored, quietly petty about one thing. "
                    "Donna Marsh asks the last question. Then back to the booth.",
                    pf, label="presser", lines=14, interview=True)
            try:
                outline = outline_fut.result(timeout=240)
            except Exception as e:
                print(f"  (postgame outline failed: {e})")
                outline = {"beats": [{"segment": s2, "premise": s2, "beat": s2}
                                     for s2 in dp2["segments"]]}
        else:  # re-entry after the game already ended: straight to the phones
            dp2 = dict(daypart)
            dp2["arc"] = season.postgame_brief(game, fin)
            dp2["segments"] = ["Callers React", "Standings Talk", "Looking Ahead"]
            outline_fut = wpool.submit(write_outline, dp2, models, state,
                                       weekday, False)
            pf0 = _facts([], None, mode="postgame",
                         final=[fin["h"], fin["a"]], shots=fin["shots"])
            # ONE-TIME outage return: a goose chewed a feeder line and took us
            # off air. Owns its own sentinel so it airs exactly once, ever.
            goose = ""
            _ret = Path("data/.outage_return")
            if not _ret.exists():
                goose = ("WE JUST CAME BACK FROM AN UNPLANNED OUTAGE — a goose "
                         "chewed clean through a feeder wire and knocked us off "
                         "the air for a bit. OPEN with a brief, warm, in-character "
                         "'we're back — a goose got the wire, of all things — and "
                         "we are glad to be here' (one or two lines, own it with a "
                         "laugh, do NOT dwell), THEN go to the phones. ")
                try:
                    _ret.parent.mkdir(exist_ok=True)
                    _ret.write_text("1")
                except Exception:
                    pass
            # a code-built bridge covers the writer's 1-3 min latency
            yield _beat("Phones", "the lines stay lit",
                        goose + "The postgame call-in continues. FINAL "
                        f"(authoritative, never contradict): {hn} {fin['h']}, "
                        f"{an} {fin['a']}. One caller, one strong opinion, the "
                        "booth pushes back.",
                        pf0, label="callin-bridge", lines=14)
            try:
                outline = outline_fut.result(timeout=240)
            except Exception as e:
                print(f"  (postgame outline failed: {e})")
                outline = {"beats": [{"segment": s2, "premise": s2, "beat": s2}
                                     for s2 in dp2["segments"]]}
        outline["beats"] = [b for b in outline.get("beats", [])
                            if not _BANNED_SEGMENT.search(str(b.get("segment", "")))]
        lore.remember(state, premises=[b.get("premise") for b in
                                       outline["beats"] if b.get("premise")])
        lore.save(state)
        pf = _facts([], None, mode="postgame",
                    final=[fin["h"], fin["a"]], shots=fin["shots"])
        threw_break = False
        for bi, b in enumerate(outline.get("beats", [])):
            for pi in range(parts_per):
                if _air_left() < 9 or not _owns_air():
                    break
                bb = dict(b)
                bb["_part"] = pi
                if pi > 0:
                    bb["beat"] = (f"{b.get('beat')} (CONTINUE this same scene, "
                                  f"part {pi+1} of {parts_per} — same callers, "
                                  "same argument, one layer deeper.)")
                yield {"beat": bb, "facts": pf, "label": f"callin{bi}",
                       "lines": lines_target, "events": [], "mark": [],
                       "brk": (not threw_break and bi == 1 and
                               pi == parts_per - 1 and _air_left() > 14)}
                if bi == 1 and pi == parts_per - 1:
                    threw_break = True
            if _air_left() < 9 or not _owns_air():
                break

        # handoff
        nxt = _next_daypart(schedule, daypart)
        print(f"\n--- Handoff -> {nxt['show']} ---")
        hb = _throw_beat(daypart, nxt)
        yield {"beat": hb, "facts": pf, "label": "handoff", "lines": 6,
               "events": [], "mark": [], "brk": False}

    # --- driver: roll on this thread, write dialogue in the pool, guard, emit
    last_lines: list = []
    ci_call = [None]        # switchboard state for the call-in beats
    ci_used: set = set()    # desk-minted caller names used this broadcast
    completed = False
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            def _submit(bi):
                dp = dict(daypart)
                dp["_target_lines"] = bi["lines"]
                dp["_switchboard"] = _switch.prompt_line(ci_call[0])
                try:
                    from . import assignments as _adesk
                    _nm = _adesk.next_caller(ci_used, random.Random(
                        f"cic:{date}:{bi['label']}:{len(ci_used)}"))
                    ci_used.add(_nm)
                    dp["_switchboard"] += (f" If a NEW caller joins, their "
                                           f"name is {_nm}.")
                except Exception:
                    pass
                dp["_show_clock"] = _cont.show_clock_line(_air_left())
                if bi.get("interview"):     # rink-side guests: no phone FX
                    dp["_no_phone"] = True
                # sports register, not the mundane/anti-conspiracy guard that
                # arc-less dayparts get — the scoreguard, not the prompt, owns
                # factual truth here
                dp["arc"] = "live sports broadcast"
                return pool.submit(perform_beat, bi["beat"], dp, models, state,
                                   _tail_context(last_lines),
                                   [ln.get("text", "") for ln in last_lines[-8:]])
            gen = plan()
            bi = next(gen, None)
            fut = _submit(bi) if bi else None
            while bi:
                _throttle(config, live)
                raw = fut.result()
                lines = enforce_scoreboard(raw, bi["facts"]) if bi["facts"] else raw
                lines = enforce_names(lines, bi["facts"], extra_ok=pool_ok)
                lines = tag_sfx(lines, bi["events"], bi["label"])  # arena sound
                lines, ci_call[0] = _switch.enforce(lines, ci_call[0], host=pbp)
                lines, _wb = _cont.enforce(lines,
                                           handoff=(bi["label"] == "handoff"))
                aired.extend(bi["events"])
                if lines:
                    last_lines = lines
                nxt = next(gen, None)       # main thread: engine rolls here
                fut = _submit(nxt) if nxt else None
                print(f"\n--- {bi['beat'].get('segment')} ---")
                _emit(lines, f"center-ice-{bi['label']}", config, live)
                if lines:
                    _save_tail(daypart, lines)
                for cid in bi["mark"]:
                    eng.mark_narrated(cid)
                # air-time markers: the open has aired (no restart replay), and
                # the final horn has been ANNOUNCED (scorebug may reveal it)
                if bi["label"] == "pregame":
                    eng.mark_opened()
                if bi["label"] in ("wrap", "scramble"):
                    eng.mark_final_narrated()
                if bi["brk"] and live:
                    _break_marker(daypart)
                elif _wb and live:
                    _break_marker(daypart)   # promised on air -> kept on air
                bi = nxt
        completed = True
    finally:
        try:
            wpool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        try:
            window_gone = (not _owns_air()) or _air_left() < 11
            if eng.final is None and (completed or window_gone):
                print("  !! finishing the game to the horn (window closed)")
                eng.finish_now()
            elif eng.final is None:
                # a transient mid-game failure with air left: leave the log
                # non-final so the next run rejoins and continues — never
                # collapse a live game to a fabricated final
                print("  (center ice interrupted mid-game — will resume)")
            if eng.final is not None:
                res = season.record_live(date)
                if res:
                    lore.remember(state, callbacks=[res])
                    lore.save(state)
                    print(f"  {res}")
            season.export()
        except Exception as e:
            print(f"  !! center-ice finalize failed: {e}")
        eng.close()
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
        # write for the show that owns the AIR slot this content will land in
        dp = _current_daypart(schedule, clock.air_now())
        try:  # league plays every night whether we broadcast or not
            from . import season
            season.tick(f"{clock.air_now():%Y-%m-%d}")
        except Exception:
            pass
        try:  # pre-cutover soak: v2 runs silently against a shadow copy
            if Path("data/league/SHADOW").exists():
                from .league.engine import shadow_tick
                shadow_tick(f"{clock.air_now():%Y-%m-%d}")
        except Exception:
            pass
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
        # if this window already signed off, don't ramble past the handoff —
        # idle until the next show owns the air (the buffer + bumper cover it)
        if _sstate().get("handed_off") == f"{dp['id']}:{clock.air_now():%Y-%m-%d}":
            if args.once:
                return
            time.sleep(30)
            continue
        try:
            run_show(dp, config, schedule, live=args.live)
        except Exception as e:  # a bad show must not kill the station
            print(f"!! show crashed, continuing: {e}")
            time.sleep(60)
        if args.once:
            return
        # wait until the buffer needs more, or the AIR daypart changes
        while (_current_daypart(schedule, clock.air_now()) is dp
               and buffer.buffered_seconds() >
               config["generation"]["buffer_target_minutes"] * 60 * 0.5):
            time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
