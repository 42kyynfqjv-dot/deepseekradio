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

from . import buffer, clock, events, lore
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
        if not events.daypart_matches_date(dp, now):
            continue  # event blocks own the air only on their date (wrap-aware)
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
    from .nameguard import enforce_news
    lines = enforce_news(lines)   # real brands never survive to air
    # radio furniture: the legal ID + this hour's billboard sponsor lead the
    # bulletin — code-picked (date+hour seeded) so the LLM never chooses
    try:
        from .spots import _roster
        import random as _rnd
        roster = _roster(bible)
        if roster:
            name, gag = _rnd.Random(f"billboard:{clock.air_now():%Y-%m-%d-%H}"
                                    ).choice(roster)
            _temp = ""
            try:  # radio says time-and-temperature or it isn't radio
                from . import towndesk as _td0
                from .world_consumers import _real_forecast as _rf0
                _tv = _td0._parse_temp(_rf0())
                if _tv is not None:
                    _temp = f" {_tv} degrees in Halfway."
            except Exception:
                pass
            lines.insert(0, {"speaker": "Station ID", "voice": NEWS_VOICE,
                             "text": f"W-F-R-Q, one oh eight point one, Halfway "
                                     f"— it's about {clock.spoken_air_time()}."
                                     f"{_temp} "
                                     f"This is The Frequency. This hour is "
                                     f"brought to you by {name} — {gag}."})
    except Exception:
        pass
    try:  # the Sports Desk rides every bulletin: Donna Marsh reads a WRITTEN
        # desk authored from an authoritative sheet and verified against it
        # line by line — if the draft strays by one number or one team, the
        # whole read falls back to code-built wire copy. Never a keys-and-
        # semicolons ticker sprint again.
        from datetime import date as _d, timedelta as _td
        from .league import engine as _lge, briefs as _lgb
        from . import season as _sn
        y = (_d.fromisoformat(f"{clock.air_now():%Y-%m-%d}")
             - _td(days=1)).isoformat()
        sst = _sn._load()
        season_n = sst["season"]
        shard = _lge.load_side(f"box/{y}.json")
        pl = _lge.load_side(f"players-s{season_n}.json")
        games = list(shard.get("games", [])) if shard else []
        bg = sst.get("games", {}).get(y)
        if bg and bg.get("recorded") and bg.get("final"):
            # the BROADCAST game folds via the live log, never the day shard
            # — without this, the desk skips our own result
            games.insert(0, {"home": bg["home_key"], "away": bg["away_key"],
                             "final": bg["final"], "ot": bg.get("ot", False),
                             "so": bg.get("so", False), "goals": []})
        if games and pl:
            desk_lines = None
            try:
                sched = _lge.load_side(f"schedule-s{season_n}.json") or {}
                stt = _lge.load_side(f"stats-s{season_n}.json")
                sheet = _lgb.desk_sheet(y, games, pl, _sn._ALL,
                                        first=tuple(_sn.TRACKED),
                                        sched_days=sched.get("days"),
                                        stats=stt)
                from .news import write_sports_desk
                script = write_sports_desk(_lgb.desk_block(sheet),
                                           config["models"], bible)
                texts = [re.sub(r"^\**\s*Donna(?:\s+Marsh)?\s*:?\**\s*", "",
                                t).strip("* ").strip()
                         for t in script.splitlines()]
                texts = [t for t in texts if t]
                if texts and _lgb.desk_verify(texts, sheet,
                                              list(_sn._ALL.values())):
                    from .performers import _spare_voice
                    dv = _spare_voice("Donna Marsh")
                    desk_lines = [{"speaker": "Donna Marsh", "voice": dv,
                                   "speed": 0.96, "text": t} for t in texts]
                else:
                    print("  !! sports desk: draft failed verify — wire copy")
            except Exception as e:
                print(f"  (sports desk writer skipped: {e})")
            if desk_lines:
                lines.extend(desk_lines)
            else:
                desk = _lgb.scores_desk(y, games, pl, n=3,
                                        first=tuple(_sn.TRACKED),
                                        names=_sn._ALL)
                lines.append({"speaker": "Frequency Sports",
                              "voice": NEWS_VOICE, "speed": 0.96,
                              "text": "Sports desk. " + desk})
    except Exception as e:
        print(f"  (sports desk skipped: {e})")
    try:  # the Town Desk wire + drive-time traffic ride the bulletin —
        # code-built copy, guard-true by construction
        from . import census as _cen3, towndesk as _td2, traffic as _tf2
        _d3 = f"{clock.air_now():%Y-%m-%d}"
        _fc3 = None
        try:
            from .world_consumers import _real_forecast as _rf2
            _fc3 = _rf2()
        except Exception:
            pass
        _wl = _td2.wire_lines(_d3, _cen3.load(), _fc3)
        if _wl:
            import random as _r3
            lines.append({"speaker": "Frequency News", "voice": NEWS_VOICE,
                          "speed": 0.97,
                          "text": _r3.Random(
                              f"townwire:{_d3}:{clock.air_now():%H}"
                          ).choice(_wl)})
        _sh3 = _tf2.traffic_sheet(_d3, clock.air_now().hour)
        if _sh3.get("incidents"):
            from .performers import _spare_voice as _sv2
            lines.append({"speaker": _tf2.REPORTER,
                          "voice": _sv2(_tf2.REPORTER), "speed": 0.97,
                          "text": _tf2.wire_line(
                              _sh3, f"{_d3}:{clock.air_now():%H}")})
    except Exception as e:
        print(f"  (town/traffic wire skipped: {e})")
    try:  # the Dome Desk rides every bulletin once the statehouse gate
        # arms — code-built wire copy off today's civics.json + docket,
        # guard-safe by construction exactly like the Sports Desk above
        from .statehouse import engine as _sheng, sheets as _shsh
        _civ = _sheng.load_civics()
        _ga = _civ.get("ga", 1)
        if _sheng.statehouse_on(_ga):
            _dk = _sheng.load_side(f"docket-ga{_ga}.json")
            _sim_date = _civ.get("sim_through")
            if _dk and _sim_date:
                _desk = _shsh.dome_desk(_civ, _dk, _sim_date)
                if _desk and not _desk.startswith("No Dome wire"):
                    lines.append({"speaker": "Frequency Statehouse",
                                  "voice": NEWS_VOICE,
                                  "text": "From the Half-Dome. " + _desk})
    except Exception as e:
        print(f"  (dome desk skipped: {e})")
    try:  # world desk: one code-authored around-Wending wire line (gated)
        from .world_consumers import news_world_line
        _wl = news_world_line(f"{clock.air_now():%Y-%m-%d}")
        if _wl:
            lines.append({"speaker": "Frequency World", "voice": NEWS_VOICE,
                          "text": "Around Wending. " + _wl})
    except Exception as e:
        print(f"  (world desk skipped: {e})")
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


NUMBERS_EVERY_MIN = 110   # the Static Hour ritual airs ~every 2h, not per beat


def _numbers_own(daypart) -> bool:
    """Does the NEXT Static Hour beat own the numbers ritual? Code-owned
    cadence off station_state — survives restarts, spans rabbit holes."""
    if daypart.get("id") != "static_hour":
        return False
    return time.time() - _sstate().get("last_numbers", 0) \
        >= NUMBERS_EVERY_MIN * 60


def _numbers_note(daypart, own: bool) -> None:
    if daypart.get("id") != "static_hour":
        return
    daypart["_numbers"] = (
        "\nTHE NUMBERS (authoritative): this beat CLOSES with the ritual — "
        "one short cryptic number sequence, read once, never explained; "
        "then the hour rolls on." if own else
        "\nTHE NUMBERS (authoritative): NOT this beat. Do not read, tease, "
        "or announce the numbers ritual — the theory carries the hour.")


def _call_budget(daypart) -> int:
    """Caller-line budget per call, honest to the show's format (Dream Court
    is one long call; the Static Hour is quick sightings)."""
    pol = daypart.get("caller_policy") or {}
    if pol.get("budget"):
        return pol["budget"]
    if pol.get("max_lines"):
        return 3 * pol["max_lines"]
    return _switch.DEFAULT_BUDGET


def _call_pacing(daypart, call_st) -> dict | None:
    """Code-owned call cadence: per_hour x window hours = the show's target,
    so a call-in hour takes a realistic number of DISTINCT callers."""
    pol = daypart.get("caller_policy") or {}
    per_hour = pol.get("per_hour")
    if not per_hour:
        return None
    try:
        s = dtime.fromisoformat(daypart["window"][0])
        e = dtime.fromisoformat(daypart["window"][1])
        dur = ((e.hour * 60 + e.minute) - (s.hour * 60 + s.minute)) % (24 * 60)
    except Exception:
        dur = 60
    return {"target": max(1, round(per_hour * dur / 60)),
            "done": (call_st or {}).get("calls_done", 0)}


def _mint_caller_line(used, seedkey: str, host_speaker: str,
                      identity=None) -> str:
    """The desk's next-caller assignment, CONTRAST-CAST: default the caller
    to the opposite gender of the host, so caller and host can never blur
    into one voice through the telephone bandpass (the Maureen incident).
    A returning RESIDENT (census follow-up) pins her own name instead — her
    voice is _spare_voice(name), deterministic, so she sounds like herself."""
    try:
        if identity:
            try:
                used.add(identity)
            except Exception:
                pass
            return f" If a NEW caller joins, their name is {identity}."
        from . import assignments as _adesk
        from .performers import _gender_of
        want = {"f": "m", "m": "f"}.get(_gender_of(host_speaker or ""))
        nm = _adesk.next_caller(set(used), random.Random(seedkey), want=want)
        try:
            used.add(nm)        # minted names never repeat within the day
        except Exception:
            pass
        return f" If a NEW caller joins, their name is {nm}."
    except Exception:
        return ""


_EVENT_ENGINES = {"election_night", "blizzard", "trade_deadline", "draft"}


def _event_anchor(path: Path, date: str) -> float:
    """Write-once listener epoch per event date — a restart mid-event must
    resume the night's reveal clock, never rewind it (the air-anchor rule)."""
    try:
        a = json.loads(path.read_text())
        if a.get("date") == date:
            return float(a["t0"])
    except Exception:
        pass
    t0 = time.time()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"date": date, "t0": t0}))
        tmp.replace(path)
    except Exception:
        pass
    return t0


def _event_window_secs(daypart) -> int:
    try:
        s = dtime.fromisoformat(daypart["window"][0])
        e = dtime.fromisoformat(daypart["window"][1])
        return ((((e.hour - s.hour) * 60 + (e.minute - s.minute))
                 % (24 * 60)) or 240) * 60
    except Exception:
        return 4 * 3600


def _event_sheet(daypart):
    """(authoritative block, guard extras) for tonight's event engine — one
    sheet per show invocation; the reveal clock ticks underneath, so each
    re-entry sees more of the night and a restart resumes mid-count."""
    eng = daypart.get("engine")
    date = f"{clock.air_now():%Y-%m-%d}"
    wsecs = _event_window_secs(daypart)
    extras: dict = {}
    if eng == "election_night":
        from .statehouse import elections as _els, returns as _ret, \
            sheets as _shs
        members = json.loads(
            Path("data/statehouse/members-ga1.json").read_text())
        civ = None
        try:
            civ = json.loads(Path("data/statehouse/civics.json").read_text())
        except Exception:
            pass
        el = _els.generate_cycle(int(date[:4]), members, 1)
        plan = _ret.build_night(el, wsecs, f"night:{date}")
        t0 = _event_anchor(Path("data/statehouse/election-anchor.json"), date)
        cur = max(0, int(time.time() - t0))
        revealed = _ret.reveal_at(plan, el, cur)
        tracked = (el.get("tracked") or el.get("tracked_id")
                   or (sorted(el.get("races", {})) or [None])[0])
        extras["_civic_facts"] = _ret.facts_at(plan, el, cur, tracked)
        return _shs.election_sheet(cur, revealed, tracked, None, civ), extras
    if eng == "blizzard":
        from . import blizzard as _bz
        from .world_consumers import _real_forecast as _rf
        sheet = _bz.storm_sheet(date, _rf())
        st = _sstate()
        k = f"blizzard_beat:{date}"
        beat = int(st.get(k, 0))
        st[k] = beat + 1
        _sstate_save(st)
        extras["_event_verify"] = ("blizzard", sheet)
        return _bz.block(sheet, _bz.closings(date, beat)), extras
    if eng == "trade_deadline":
        from . import season as _sn
        from .league import deadline as _dl, engine as _lge
        n = _sn._load()["season"]
        tx = (_lge.load_side(f"transactions-s{n}.json") or {}).get("tx", [])
        pl = _lge.load_side(f"players-s{n}.json") or {}
        plan = _dl.day_plan(tx, date, wsecs, f"s{n}")
        t0 = _event_anchor(Path("data/league/deadline-anchor.json"), date)
        rev = _dl.reveal_at(plan, max(0, int(time.time() - t0)))
        extras["_event_verify"] = ("deadline", (rev, _sn._ALL))
        return _dl.sheet(rev, pl, _sn._ALL), extras
    if eng == "draft":
        from . import season as _sn
        from .league import draftday as _dd
        sst = _sn._load()
        rec = _dd.record(sst["season"], sst["league"])
        plan = _dd.picks_plan(rec.get("class", []), rec.get("order", []),
                              wsecs, f"s{sst['season']}")
        t0 = _event_anchor(Path("data/league/draft-anchor.json"), date)
        rev = _dd.reveal_at(plan, max(0, int(time.time() - t0)))
        extras["_event_verify"] = ("draft", (rev, _sn._ALL))
        return _dd.sheet(rev, _sn._ALL), extras
    raise RuntimeError(f"unknown event engine {eng!r}")


def _event_guard(lines, ev, daypart):
    """Hold an event beat to its sheet: a failing beat airs one neutral
    holding line instead of unverified facts."""
    kind, payload = ev
    texts = [ln.get("text", "") for ln in lines]
    if kind == "blizzard":
        from . import blizzard as _bz
        ok = _bz.verify(texts, payload)
    elif kind == "deadline":
        from .league import deadline as _dl
        ok = _dl.verify(texts, *payload)
    elif kind == "draft":
        from .league import draftday as _dd
        ok = _dd.verify(texts, *payload)
    else:
        return lines
    if ok:
        return lines
    meta = _cast_meta(daypart, 0)
    print(f"  !! event guard ({kind}): beat failed sheet verify — held")
    return [{"speaker": meta.get("speaker", "Host"),
             "voice": meta.get("voice", "am_adam"),
             "speed": meta.get("speed", 1.0), "_enforced": True,
             "text": "We're confirming details at the desk — stay with us, "
                     "more in a moment."}]


def _run_event_show(daypart, config, schedule, live: bool):
    """Sheet-driven event engines: code computes the moment's authoritative
    sheet (reveal clocks under it), the everyday show machinery performs it,
    and per-beat guards hold every number to the sheet."""
    dp2 = dict(daypart)
    dp2.pop("engine", None)             # falls to run_show's everyday path
    try:
        block, extras = _event_sheet(daypart)
    except Exception as e:
        print(f"  !! event sheet failed ({daypart.get('engine')}): {e} — "
              "bumpers cover the window")
        time.sleep(60)
        return
    dp2["_event_block"] = ("TONIGHT'S DESK SHEET (authoritative — the "
                           "ONLY facts that exist):\n" + block)
    dp2.update(extras)
    return run_show(dp2, config, schedule, live)


def run_show(daypart, config, schedule, live: bool):
    eng_key = events.engine_of(daypart)
    if eng_key == "center_ice":             # live sports is its own machine
        return run_center_ice(daypart, config, schedule, live)
    if eng_key in _EVENT_ENGINES:
        return _run_event_show(daypart, config, schedule, live)
    if eng_key:
        # an event engine we haven't built yet must NEVER free-associate its
        # way onto air — bumpers cover the window until the engine exists
        print(f"  (event engine '{eng_key}' not built — skipping generation)")
        time.sleep(60)
        return
    models = config["models"]
    state = lore.load()
    weekday = clock.air_now().strftime("%A")  # the day it will AIR
    fx = daypart.get("id") if daypart.get("id") == "static_hour" else None
    # _extra_context is rebuilt EVERY invocation (appenders below would
    # otherwise stack copies on the shared daypart dict); an event engine's
    # sheet, stashed by _run_event_show, survives the reset
    daypart["_extra_context"] = daypart.pop("_event_block", "")
    _daynote = {
        "Monday": "MONDAY (hard): the town is low-energy and mildly late; "
                  "the hosts feel it — bits land tired, never manic.",
        "Friday": "FRIDAY (hard): Feud Friday — the week's petty on-air "
                  "grudges get RESOLVED or doubled down on; callbacks to "
                  "the week's grievances are prime material.",
        "Saturday": "SATURDAY: weekend air — looser, longer stories, no "
                    "commute urgency; errands, the market, the game.",
        "Sunday": "SUNDAY: the slowest air of the week — reflective, "
                  "gentle; everything gets room to breathe.",
    }.get(weekday)
    if _daynote:
        daypart["_extra_context"] += "\n" + _daynote

    print(f"\n{'='*70}\n  {daypart['show']}  ({daypart['window'][0]}-{daypart['window'][1]})"
          f"  —  {weekday}\n{'='*70}")

    # the Watcher's theory clock: one descent per hour, code-enforced. A
    # re-entry inside the hour (buffer refill OR restart) CONTINUES the
    # same theory; the ordinal rides every emit label (-tN-) so the podcast
    # cutter can cut one episode per theory.
    _theory_cont, _theory_n = None, None
    if daypart.get("id") == "static_hour":
        try:
            from . import watcherlore as _wl0
            _anow = clock.air_now()
            _bd = (_anow - __import__("datetime").timedelta(days=1)
                   if _anow.hour < 5 else _anow).strftime("%Y-%m-%d")
            _theory_cont, _theory_n = _wl0.current_theory(_bd, time.time())
            if _theory_cont:
                print(f"  (theory clock: continuing t{_theory_n} — "
                      f"{_theory_cont[:50]!r})")
        except Exception as e:
            print(f"  (theory clock skipped: {e})")
    _lbl = (f"{daypart['id']}-t{_theory_n}" if _theory_n
            else daypart["id"])

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
            from .nameguard import enforce_world as _ew
            opener_lines = _ew(opener_lines)
            _emit(opener_lines, f"{_lbl}-open", config, live, fx=fx)
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
            daypart["_extra_context"] += (
                "\nWesley's forecast uses TODAY'S REAL weather (keep the "
                "numbers roughly right; the delivery is all his): "
                + _real_forecast())
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
        # roughly one guest day in three, the guest IS a sponsor's owner —
        # the ads talk back. Owner name derives from the shop when it wears
        # one ("Gary's Discount Teeth" -> Gary), else a stable minted first
        # name; the writer gets the whole premise as the pool description.
        _guest = _adesk.pick_guest(_gp.read_text() if _gp.exists() else "",
                                   state.get("guests_seen", []), _arng)
        if _guest and _ros and _arng.random() < 0.33:
            _sname, _sgag = _arng.choice(_ros)
            _m = re.match(r"([A-Z][a-z]+)'s\b", _sname)
            _owner = _m.group(1) if _m else _adesk.next_caller(
                set(), random.Random(f"owner:{_sname}")).split()[0]
            _guest = (f"{_owner}, the owner of {_sname} — {_sgag} — on air to "
                      f"defend the business: sincerely proud, mildly "
                      f"defensive about the reviews, ready to take "
                      f"'customer questions'")
        daypart["_assign"] = {
            "guest": _guest,
            "sponsor": _arng.choice(_ros) if _ros else None,
            "callback": _adesk.pick_callback(state, _arng),
            "props": _adesk.prop_candidates(
                state.get("recent_grounding", []), _arng),
        }
        try:  # the giveaway desk: code picks the show, prize, and winner
            from . import contests as _ct
            _cd = f"{clock.air_now():%Y-%m-%d}"
            for _c in _ct.todays(_cd, _ros):
                if _c["show"] != daypart["id"]:
                    continue
                if any(w.get("date") == _cd and w.get("show") == daypart["id"]
                       for w in _ct._load().get("winners", [])):
                    break               # this show's giveaway already ran
                _cwin = _adesk.next_caller(
                    set(_sstate().get("callers_today", [])),
                    random.Random(f"contest:{_cd}:{daypart['id']}"))
                daypart["_contest"] = _ct.directive(_c, _cwin)
                daypart["_contest_meta"] = {"date": _cd,
                                            "show": daypart["id"],
                                            "prize": _c["prize"],
                                            "winner": _cwin}
                print(f"  contest desk: {_c['prize']!r} -> {_cwin}")
                break
        except Exception as e:
            print(f"  (contest desk skipped: {e})")
        # --- CONTINUITY DESK (arcs+census) — gated, garnish-safe ---
        if Path("data/arcs/ENABLED").exists():
            from . import arcs as _arcs, census as _census
            from . import continuity_desk as _cdesk
            _cdate = f"{clock.air_now():%Y-%m-%d}"
            _arc_beat = _arcs.next_beat_for_show(
                _arcs.load(), _cdate, daypart["id"])
            _follow = (_census.due_follow_ups(
                _census.load(), _cdate, daypart["id"])[:1] or [None])[0]
            daypart["_assign"]["arc_beat"] = _arc_beat
            daypart["_assign"]["follow_up"] = _follow
            daypart["_continuity_desk"] = _cdesk.canon_block(_arc_beat, _follow)
    except Exception as e:
        print(f"  (assignment desk skipped: {e})")
    try:  # world spine: the morning show reads today's real cross-sim texture
        if daypart.get("id") == "morning_scramble":
            from .world_consumers import morning_block
            _wb, _wb_allow = morning_block(f"{clock.air_now():%Y-%m-%d}")
            if _wb:
                daypart["_extra_context"] = (daypart.get("_extra_context", "")
                                             + "\n\n" + _wb)
    except Exception as e:
        print(f"  (world block skipped: {e})")
    try:  # Town Desk + traffic: the small-town service furniture
        _tdate = f"{clock.air_now():%Y-%m-%d}"
        if daypart.get("id") in ("morning_scramble", "refined_palate"):
            from . import census as _cen2, contests as _ct2, towndesk as _td
            _fct = None
            try:
                from .world_consumers import _real_forecast as _rf1
                _fct = _rf1()
            except Exception:
                pass
            _tb = _td.town_block(_tdate, _cen2.load(), _fct)
            _unc = _ct2.uncollected(_tdate)
            if _unc:
                _tb += "\n- prize desk: " + " ".join(_unc[:2])
            daypart["_extra_context"] = ((daypart.get("_extra_context") or "")
                                         + "\n" + _tb)
        if daypart.get("id") in ("morning_scramble", "the_handover"):
            from . import traffic as _tf
            _shf = _tf.traffic_sheet(_tdate, clock.air_now().hour)
            if _shf.get("incidents"):
                daypart["_extra_context"] = (
                    (daypart.get("_extra_context") or "")
                    + "\n" + _tf.block(_shf))
    except Exception as e:
        print(f"  (town desk skipped: {e})")
    # bridge the outline latency: while the writer thinks (~1-3 min), a second
    # short beat generates and airs so a cold start never goes quiet
    with ThreadPoolExecutor(max_workers=1) as wpool:
        outline_fut = wpool.submit(write_outline, daypart, models, state,
                                   weekday, first_of_window, _theory_cont)
        try:
            daypart["_target_lines"] = 10
            bridge = {"segment": "Bridge",
                      "premise": "carrying the moment while the show gathers itself",
                      "beat": "continue from AFTER the last thing said — the NEXT "
                              "thought, one small development forward, in this "
                              "show's own register. Do NOT restate, rephrase, or "
                              "summarize any line already spoken. No callers, no "
                              "greetings, no wrap."}
            from .nameguard import enforce_world as _ewb
            _emit(_ewb(perform_beat(bridge, daypart, models, state,
                                    _tail_context(opener_lines),
                                    avoid_lines=[l.get("text", "")
                                                 for l in opener_lines])),
                  f"{_lbl}-bridge", config, live, fx=fx)
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
    if _theory_n and not _theory_cont and outline.get("beats"):
        try:  # a fresh descent begins: stamp the ledger with its subject
            from . import watcherlore as _wl1
            b0 = outline["beats"][0]
            _subj = str(b0.get("premise") or b0.get("segment") or
                        "tonight's theory").strip()
            _wl1.begin_theory(_bd, _theory_n, _subj, time.time())
            print(f"  (theory clock: t{_theory_n} opened — {_subj[:50]!r})")
        except Exception as e:
            print(f"  (theory ledger skipped: {e})")
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
        _fu_id = None
        try:
            from . import continuity_desk as _cdesk0
            _fu = (daypart.get("_assign") or {}).get("follow_up")
            _fu_id = (_cdesk0.switchboard_identity(_fu) or [None])[0]
        except Exception:
            _fu_id = None
        daypart["_switchboard"] = _switch.prompt_line(
            call_st, _call_budget(daypart),
            _call_pacing(daypart, call_st)) + _mint_caller_line(
            used_names, f"caller:{clock.air_now():%Y-%m-%d}:{daypart['id']}:0",
            _cast_meta(daypart, 0).get("speaker", ""), identity=_fu_id)
        numbers_pending = _numbers_own(daypart)
        _numbers_note(daypart, numbers_pending)
        _wcanon = None
        if daypart.get("id") == "static_hour":
            try:  # his private corkboard: recurring files, quarantined
                from . import watcherlore as _wl
                _wcanon = _wl.load()
                daypart["_watcher_canon"] = _wl.prompt_block(
                    _wcanon, f"{clock.air_now():%Y-%m-%d}")
            except Exception as e:
                print(f"  (watcher canon skipped: {e})")
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
                from .nameguard import enforce_world as _ewh
                lines = _ewh(lines, extra_ok=used_names)
                _emit(lines, f"{_lbl}-handoff", config, live, fx=fx)
                # the sign-off is TERMINAL: mark the window handed off so the main
                # loop won't re-invoke this show and ramble past the goodbye. The
                # next show's first audio triggers the station bumper on show-change.
                if live:
                    hs = _sstate(); hs["handed_off"] = opened_key; _sstate_save(hs)
                break
            # never generate past the daypart's AIR boundary — the next show
            # owns everything that would air after it
            if not events.same_air(_current_daypart(schedule, clock.air_now()),
                                   daypart):
                print("  (daypart ended — handing over to the next show)")
                break
            _throttle(config, live)
            lines = fut.result()
            lines, call_st = _switch.enforce(
                lines, call_st, budget=_call_budget(daypart),
                host=_cast_meta(daypart, 0))
            from .nameguard import enforce_world as _ew
            # the Watcher's conspiracies, the gossip riffs, all of it: real
            # people and companies never ride along (callers stay whitelisted)
            lines = _ew(lines, extra_ok=used_names)
            if daypart.get("_event_verify"):
                try:  # event beats never air numbers their sheet doesn't hold
                    lines = _event_guard(lines, daypart["_event_verify"],
                                         daypart)
                except Exception as e:
                    print(f"  (event guard skipped: {e})")
            if daypart.get("_civic_facts"):
                try:  # election night: the returns clock is the only truth
                    from .statehouse.civicguard import enforce_civic
                    lines = enforce_civic(lines, daypart["_civic_facts"])
                except Exception as e:
                    print(f"  (civic guard skipped: {e})")
            _cm = daypart.get("_contest_meta")
            if _cm and any(ln.get("phone") and str(ln.get("speaker", ""))
                           .split()[:1] == [_cm["winner"].split()[0]]
                           for ln in lines):
                try:  # the winner has aired: record it, retire the directive
                    from . import contests as _ct3
                    _ct3.record_winner(_cm["date"], _cm["show"],
                                       _cm["prize"], _cm["winner"])
                    print(f"  contest: {_cm['winner']} won {_cm['prize']!r}")
                except Exception as e:
                    print(f"  (contest record skipped: {e})")
                daypart.pop("_contest", None)
                daypart.pop("_contest_meta", None)
            daypart["_switchboard"] = _switch.prompt_line(
                call_st, _call_budget(daypart),
                _call_pacing(daypart, call_st)) + \
                _mint_caller_line(
                    used_names,
                    f"caller:{clock.air_now():%Y-%m-%d}:{daypart['id']}:{i}",
                    _cast_meta(daypart, 0).get("speaker", ""),
                    # the returning resident stays pinned until the show's
                    # FIRST call actually happens, then the desk rotates
                    identity=_fu_id
                    if not (call_st or {}).get("calls_done") else None)
            _is_throw = bool(beat.get("scheduled_handoff") or beat.get("ad_throw"))
            lines, _wb = _cont.enforce(lines, handoff=_is_throw)
            if daypart.get("id") == "static_hour":
                lines, _did_numbers = _cont.numbers_guard(
                    lines, allowed=numbers_pending)
                if _did_numbers:   # the ritual aired: stamp the cadence clock
                    _ns = _sstate()
                    _ns["last_numbers"] = time.time()
                    _sstate_save(_ns)
                numbers_pending = _numbers_own(daypart)
                _numbers_note(daypart, numbers_pending)   # for the NEXT beat
                if _wcanon is not None:
                    try:  # canonize tonight's inventions, bump resurfaced files
                        from . import watcherlore as _wl
                        _wl.harvest(lines, _wcanon,
                                    f"{clock.air_now():%Y-%m-%d}")
                        _wl.save(_wcanon)
                    except Exception as e:
                        print(f"  (watcher canon skipped: {e})")
            if daypart.get("_continuity_desk"):   # scoped canon guard (gated)
                try:
                    from . import canonguard as _cang, arcs as _arcs2, \
                        census as _census2, continuity_desk as _cdesk2
                    _cdk = daypart.get("_assign", {})
                    _sc = _cdesk2.beat_scope(_cdk.get("arc_beat"),
                                             _cdk.get("follow_up"), lines)
                    if _sc["scope"] != "none":
                        _cf = _cang.build_canon_facts(
                            _arcs2.load(), _census2.load(),
                            scope_ids=_sc["scope_ids"], scope=_sc["scope"])
                        lines = _cang.enforce_canon(lines, _cf)
                except Exception as e:
                    print(f"  (canon guard skipped: {e})")
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
            try:  # census: aired callers become residents of Halfway (gated)
                if Path("data/arcs/ENABLED").exists():
                    from . import census as _cen
                    _cd = f"{clock.air_now():%Y-%m-%d}"
                    civ = _cen.load()
                    changed = False
                    for ln in lines:
                        spk = str(ln.get("speaker", "")).strip()
                        if ln.get("phone") and spk:
                            rec = civ.get("civilians", {}).get(
                                _cen.new_id(spk, civ)) or _cen.mint(
                                spk, _cd, daypart["id"], civ)
                            _cen.record_appearance(rec, _cd, daypart["id"], "")
                            changed = True
                    if changed:
                        _cen.save(civ)
            except Exception as e:
                print(f"  (census record skipped: {e})")
            if i + 1 < len(beats):
                fut = pool.submit(perform_beat, beats[i + 1], daypart, models,
                                  state, _context(i + 1, lines),
                                  _tail_texts(lines))
            print(f"\n--- {beat.get('segment')} ---")
            _emit(lines, f"{_lbl}-{beat.get('segment', 'seg')}", config, live, fx=fx)
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
                    from .nameguard import enforce_world as _ewt
                    tl = _ewt(tl, extra_ok=used_names)
                    _emit(tl, f"{_lbl}-adthrow", config, live, fx=fx)
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
        # still calling as in-progress. `lag` = the buffer between generation
        # and air at anchor time: the booth's reveal choices EMBED in audio
        # that airs `lag` seconds later, so the site's cursor must trail by it.
        # The anchor is the LISTENER's show-open epoch: a restart mid-show
        # must not rewrite it, or the whole out-of-town board rewinds.
        from .league import engine as _lge0
        _prev = _lge0.load_side("air-anchor.json")
        if not (_prev and _prev.get("date") == date):
            _lge0.save_side("air-anchor.json",
                            {"date": date, "t0": t_open,
                             "lag": buffer.buffered_seconds()})
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
        return events.same_air(_current_daypart(schedule, clock.air_now()),
                               daypart)

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
                dp["_switchboard"] = _switch.prompt_line(
                    ci_call[0], _call_budget(daypart),
                    _call_pacing(daypart, ci_call[0])) + \
                    _mint_caller_line(
                        ci_used, f"cic:{date}:{bi['label']}:{len(ci_used)}",
                        pbp.get("speaker", ""))
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
                from .nameguard import enforce_world as _ew
                lines = _ew(lines, extra_ok=pool_ok)
                lines = tag_sfx(lines, bi["events"], bi["label"])  # arena sound
                lines, ci_call[0] = _switch.enforce(
                    lines, ci_call[0], budget=_call_budget(daypart), host=pbp)
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
        # write for the show that owns the AIR slot this content will land in.
        # `eff` = the base schedule with today's special-event blocks overlaid
        # (memoized; with no active event it IS the base object, a pure no-op)
        eff = events.effective_schedule(schedule,
                                        events.build_ctx(clock.air_now()))
        dp = _current_daypart(eff, clock.air_now())
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
        try:  # world spine: project today's cross-sim events onto the bus
            from . import world as _world
            if _world.on():
                _world.tick(f"{clock.air_now():%Y-%m-%d}")
        except Exception:
            pass
        try:  # the statehouse simulates daily once bootstrapped — dark soak;
            # nothing airs until its gate arms AND the shows are wired
            if Path("data/statehouse/civics.json").exists():
                from .statehouse import engine as _sheng, publish as _shpub
                _sheng.tick(1, f"{clock.air_now():%Y-%m-%d}")
                _shpub.export()   # best-effort, internally air-gated
        except Exception as e:
            print(f"  (statehouse tick skipped: {e})")
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
        try:  # events: site takeover feed + lead-window promos, same cadence
            st = _sstate()
            if args.live and time.time() - st.get("last_events", 0) > 30 * 60:
                from datetime import timedelta as _td
                from .events import promo as _evpromo, publish as _evpub
                _evpub.publish_takeovers()
                upcoming, _seen = [], set()
                for k in range(8):   # promos need the lead window, not just today
                    for ev in events.active_events(
                            events.build_ctx(clock.air_now() + _td(days=k))):
                        if (ev.get("id"), ev.get("date")) not in _seen:
                            _seen.add((ev.get("id"), ev.get("date")))
                            upcoming.append(ev)
                _evpromo.render_promos(upcoming, f"{clock.air_now():%Y-%m-%d}")
                _evpromo.purge_expired(f"{clock.air_now():%Y-%m-%d}")
                st["last_events"] = time.time()
                _sstate_save(st)
        except Exception as e:
            print(f"  (events hook skipped: {e})")
        # if this window already signed off, don't ramble past the handoff —
        # idle until the next show owns the air (the buffer + bumper cover it)
        if _sstate().get("handed_off") == f"{dp['id']}:{clock.air_now():%Y-%m-%d}":
            if args.once:
                return
            time.sleep(30)
            continue
        try:
            run_show(dp, config, eff, live=args.live)
        except Exception as e:  # a bad show must not kill the station
            print(f"!! show crashed, continuing: {e}")
            time.sleep(60)
        if args.once:
            return
        # wait until the buffer needs more, or the AIR daypart changes.
        # Recompute the overlay each pass and compare by (id, date) — a memo
        # miss hands back a fresh dict, so object identity would busy-loop
        while True:
            eff = events.effective_schedule(schedule,
                                            events.build_ctx(clock.air_now()))
            cur = _current_daypart(eff, clock.air_now())
            if not (events.same_air(cur, dp)
                    and buffer.buffered_seconds() >
                    config["generation"]["buffer_target_minutes"] * 60 * 0.5):
                break
            time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
