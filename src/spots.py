"""The Continuity Department — ads, weather, and traffic as a living rotation.

SQLite-backed spot inventory (station.db). The writer periodically produces
fresh ad copy for the station's recurring sponsors, weather grounded in a REAL
forecast (Open-Meteo, free) then twisted, and evergreen traffic absurdism.
Each spot is rendered once to spots/<id>.wav; the streamer plays the
least-recently-aired live spot roughly every 15 minutes and this module
retires spots as they age or wear out.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

import requests

from .openrouter import chat

DB = Path("station.db")
SPOT_DIR = Path("spots")

# rotation policy: (min_live, regenerate_batch, max_age_seconds, max_plays)
POLICY = {
    # bigger live ad pool + earlier retirement: more sponsors on air at once,
    # less copy fatigue per spot
    "ad":      (16, 4, 72 * 3600, 24),
    "weather": (2, 2, 2.5 * 3600, 8),
    "traffic": (2, 2, 8 * 3600, 12),
}

_SPOT_VOICES = ["am_adam", "af_sarah", "bm_george", "af_nicole", "am_onyx",
                "bm_lewis", "af_bella", "am_michael"]


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS spots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        script TEXT NOT NULL,
        voice TEXT NOT NULL,
        wav TEXT NOT NULL,
        created REAL NOT NULL,
        plays INTEGER DEFAULT 0,
        last_played REAL DEFAULT 0,
        retired INTEGER DEFAULT 0)""")
    return con


def _real_forecast() -> str:
    """Real numbers from Open-Meteo (free, keyless) for the writer to twist."""
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": 40.71, "longitude": -74.01,
                    "current": "temperature_2m,weather_code,wind_speed_10m",
                    "daily": "temperature_2m_max,temperature_2m_min,"
                             "precipitation_probability_max",
                    "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
                    "timezone": "America/New_York", "forecast_days": 2},
            timeout=15)
        r.raise_for_status()
        d = r.json()
        cur, daily = d.get("current", {}), d.get("daily", {})
        return (f"now {cur.get('temperature_2m')}F wind {cur.get('wind_speed_10m')}mph "
                f"code {cur.get('weather_code')}; today high {daily.get('temperature_2m_max', ['?'])[0]}F "
                f"low {daily.get('temperature_2m_min', ['?'])[0]}F "
                f"rain {daily.get('precipitation_probability_max', ['?'])[0]} percent; "
                f"tomorrow high {daily.get('temperature_2m_max', ['?', '?'])[1]}F")
    except Exception:
        return "(no forecast data — improvise gently, no numbers)"


_BRIEFS = {
    "ad": """Write {n} DIFFERENT 15-25 second radio ads for The Frequency's recurring
fictional sponsors. Use the SPONSOR ROSTER from the station bible: each ad a
DIFFERENT sponsor, chosen at random from the roster — do not favor the first
few. Honor each sponsor's ONE core gag; never invent a new gag for an old
sponsor. You may invent at most ONE brand-new equally absurd clean sponsor per
batch. Each ad: single announcer, 4-6 short spoken lines, deadpan, PG, ends
with the sponsor name. Fresh copy every time — no recycled taglines.""",
    "weather": """Write {n} DIFFERENT 15-20 second Frequency weather spots. Here is the REAL
current forecast: {forecast}. Keep the real numbers roughly right (temperature,
rain chance) so the forecast is genuinely useful, but deliver it in the
station's deadpan-absurd register (the radar is a bowl of water, etc). Single
announcer, 4-6 short lines each. Never state clock times.""",
    "traffic": """Write {n} DIFFERENT 15-20 second Frequency traffic spots. Evergreen (no
real roads, no times of day): a goose situation, a spilled truck of something
absurd, the roundabout, the one beautiful empty road nobody can find. Single
announcer, 4-6 short lines each, deadpan, PG.""",
}


def _generate(kind: str, n: int, models: dict, bible: str) -> list[dict]:
    brief = _BRIEFS[kind].format(n=n, forecast=_real_forecast() if kind == "weather" else "")
    user = brief + """

Return STRICT JSON: {"spots": [{"lines": ["<spoken line>", ...]}, ...]}"""
    raw = chat(models["writer"],
               [{"role": "system", "content":
                 "You write short produced radio spots for The Frequency. Honor the "
                 "content guardrail absolutely.\n\n" + bible},
                {"role": "user", "content": user}])
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.split("```", 2)[1].lstrip("json").strip()
    try:
        return json.loads(txt).get("spots", [])[:n]
    except Exception:
        return []


def refresh(config: dict, models: dict, bible: str) -> None:
    """Retire worn-out spots; render fresh ones to keep each pool topped up.
    Called from the orchestrator loop (cheap: writer-only, a few times a day)."""
    con = _db()
    now = time.time()
    try:
        for kind, (min_live, batch, max_age, max_plays) in POLICY.items():
            con.execute(
                "UPDATE spots SET retired=1 WHERE kind=? AND retired=0 "
                "AND (created < ? OR plays >= ?)",
                (kind, now - max_age, max_plays))
            live = con.execute(
                "SELECT COUNT(*) FROM spots WHERE kind=? AND retired=0",
                (kind,)).fetchone()[0]
            con.commit()
            if live >= min_live:
                continue
            for spot in _generate(kind, batch, models, bible):
                lines = [str(x) for x in spot.get("lines", []) if str(x).strip()]
                if not lines:
                    continue
                h = int(hashlib.md5(lines[0].encode()).hexdigest(), 16)
                voice = _SPOT_VOICES[h % len(_SPOT_VOICES)]
                cur = con.execute(
                    "INSERT INTO spots (kind, script, voice, wav, created) "
                    "VALUES (?,?,?,?,?)",
                    (kind, json.dumps(lines), voice, "", now))
                sid = cur.lastrowid
                wav = SPOT_DIR / f"{kind}_{sid}.wav"
                from .tts import synth_segment
                synth_segment([{"speaker": "spot", "voice": voice, "text": t}
                               for t in lines], wav, config)
                con.execute("UPDATE spots SET wav=? WHERE id=?", (str(wav), sid))
                con.commit()
                print(f"  ✦ new {kind} spot #{sid} ({voice})")
    finally:
        con.close()
