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
import re
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
    "psa":     (3, 2, 7 * 24 * 3600, 30),   # civic wallpaper: slow rotation
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
        retired INTEGER DEFAULT 0,
        tag TEXT DEFAULT '')""")
    if "tag" not in {r[1] for r in con.execute("PRAGMA table_info(spots)")}:
        con.execute("ALTER TABLE spots ADD COLUMN tag TEXT DEFAULT ''")
    con.commit()
    return con


# ------------------------------------------------------------ sponsor roster
# Parse the sponsor roster straight from the bible so it stays the single
# source of truth. Roster lines look like:  "  - *Name* — one core gag"
# (single-asterisk italic; the bold `**cast**` bullets never match).
_ROSTER_RE = re.compile(r"^\s*-\s*\*([^*]+)\*\s*[—-]+\s*(.+?)\s*$")


def _roster(bible: str) -> list[tuple[str, str]]:
    return [(m.group(1).strip(), m.group(2).strip())
            for line in bible.splitlines()
            if (m := _ROSTER_RE.match(line))]


def _pick_sponsors(con, roster: list[tuple[str, str]], n: int) -> list[tuple[str, str]]:
    """Least-recently-used rotation: the n sponsors whose last spot is oldest
    (never-aired sponsors, last=0, come first). Stable sort keeps roster order
    on ties, so the whole roster cycles evenly and none dominates."""
    used = dict(con.execute(
        "SELECT tag, MAX(created) FROM spots WHERE tag != '' GROUP BY tag").fetchall())
    # primary key = recency (LRU); tie-break = stable hash so a cold rotation
    # (no history yet) spreads across the roster instead of favoring the top few.
    def _key(s):
        return (used.get(s[0], 0.0),
                int(hashlib.md5(s[0].encode()).hexdigest(), 16))
    return sorted(roster, key=_key)[:n]


def _real_forecast(coords: dict | None = None) -> str:
    """Real numbers from Open-Meteo (free, keyless) for the writer to twist.
    Defaults to Halfway's canon coordinates (world-spine §2) so Wesley, the
    weather spots, and the world spine all report the SAME city's sky."""
    from .world import HALFWAY_LATLON            # canon Halfway coord
    c = coords or HALFWAY_LATLON
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": c["lat"], "longitude": c["lon"],
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
    "weather": """Write {n} DIFFERENT 15-20 second Frequency weather spots. Here is the REAL
current forecast: {forecast}. Keep the real numbers roughly right (temperature,
rain chance) so the forecast is genuinely useful, but deliver it in the
station's deadpan-absurd register (the radar is a bowl of water, etc). Single
announcer, 4-6 short lines each. Never state clock times.""",
    "traffic": """Write {n} DIFFERENT 15-20 second Frequency traffic spots. Evergreen (no
real roads, no times of day): a goose situation, a spilled truck of something
absurd, the roundabout, the one beautiful empty road nobody can find. Single
announcer, 4-6 short lines each, deadpan, PG.""",
    "psa": """Write {n} DIFFERENT 15-20 second PUBLIC SERVICE ANNOUNCEMENTS from the
State of Wending or its agencies — formal PSA cadence, deadpan, PG, evergreen
(no dates, no clock times). Draw on Wending canon: the provisional 51st state,
the Office of Interparty Compliance (check your ink), the roundabout at Mile
Zero ("about two weeks out"), goose awareness in the pharmacy lot, merge
courtesy (the state takes NO position on early versus late), Half-Dome tarp
season. Single announcer, 4-6 short lines, each ending "A message from
<the agency>".""",
}


def _generate(kind: str, n: int, models: dict, bible: str, con) -> list[dict]:
    picks: list[tuple[str, str]] = []
    if kind == "ad":
        # code picks the sponsors (LRU rotation) so none dominates — the writer
        # only writes the copy for the ones it's handed, one ad per sponsor.
        picks = _pick_sponsors(con, _roster(bible), n)
        if not picks:
            return []
        spec = "\n".join(f"{i + 1}. {name} — {gag}"
                         for i, (name, gag) in enumerate(picks))
        brief = (f"Write {len(picks)} DIFFERENT 15-25 second radio ads for The "
                 f"Frequency, ONE ad for EACH of these specific sponsors, IN THIS "
                 f"ORDER. Honor each sponsor's ONE core gag exactly as given — never "
                 f"invent a new gag, and do NOT invent any new sponsor. Each ad: "
                 f"single announcer, 4-6 short spoken lines, deadpan, PG, ending on "
                 f"the sponsor's name. Fresh copy, no recycled taglines.\n\n"
                 f"SPONSORS (one ad each, in order):\n{spec}")
    else:
        brief = _BRIEFS[kind].format(
            n=n, forecast=_real_forecast() if kind == "weather" else "")
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
        spots = json.loads(txt).get("spots", [])[:n]
    except Exception:
        return []
    for i, sp in enumerate(spots):     # tag each ad with the sponsor it's for
        if isinstance(sp, dict) and i < len(picks):
            sp["_tag"] = picks[i][0]
    return spots


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
            for spot in _generate(kind, batch, models, bible, con):
                lines = [str(x) for x in spot.get("lines", []) if str(x).strip()]
                if not lines:
                    continue
                h = int(hashlib.md5(lines[0].encode()).hexdigest(), 16)
                voice = _SPOT_VOICES[h % len(_SPOT_VOICES)]
                cur = con.execute(
                    "INSERT INTO spots (kind, script, voice, wav, created, tag) "
                    "VALUES (?,?,?,?,?,?)",
                    (kind, json.dumps(lines), voice, "", now, spot.get("_tag", "")))
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
