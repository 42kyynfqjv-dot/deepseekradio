"""Podcast feeds — episode-native shows, cut from the air archive.

The player drains the buffer into audio_buffer/played/ and prunes all but
the last 50 segments; this module harvests those WAVs (hard links, zero
copy) into podcast/staging/ BEFORE the prune, groups them into broadcast-day
episodes per feed, and — once a show has gone quiet — concatenates,
loudness-normalizes, and encodes each episode to mono MP3, uploads it to
object storage (rclone -> R2; zero-egress serving), and rewrites the feed's
RSS. Feeds and artwork stay on the site; only the heavy audio goes remote.

Only episode-shaped shows get feeds — a 24/7 companion station does not
survive the podcast form, but a game night, a night of Dream Court calls,
and one rabbit hole absolutely do:

    center-ice    every broadcast game, pregame to postgame
    dream-court   the night's calls and verdicts (Night Shift call segments)
    static-hour   one night, one rabbit hole

Config: /opt/kaos/podcast.env with MEDIA_REMOTE (rclone dest, e.g.
r2:frequency-media) and MEDIA_BASE (public URL base). Without it, episodes
publish to the local site tree with a keep-last-N retention — the pipeline
works before credentials exist and flips to R2 by config alone.

Filename contract (buffer.next_path): NNNNNNNNN_<daypart>-<segment>.wav —
the sequence number orders the episode, the label routes it to a feed.
Broadcast-day rule: a file stamped before 05:00 belongs to the previous
day's shows (the Night Shift wraps past midnight).

Stdlib-only leaf; ffmpeg/ffprobe/rclone via subprocess. Never touches the
live air path — read-only against played/, and encoding runs nice(1)d so
TTS keeps the CPU.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import xml.sax.saxutils as _sx
from datetime import date as _date, datetime, timedelta
from email.utils import formatdate
from pathlib import Path

PLAYED = Path("audio_buffer/played")
STAGE = Path("podcast/staging")
STATE = Path("podcast/state.json")
WORK = Path("podcast/work")
WWW = Path("/var/www/bestairadio/podcasts")
ENV = Path("/opt/kaos/podcast.env")
SITE = "https://bestairadio.com"

QUIET_MIN = 90          # a show is cut this long after its last aired file
LOCAL_KEEP = 15         # local-mode retention (R2 mode keeps everything)
BITRATE = "64k"
SCOREBOARD = Path("/var/www/bestairadio/data/sports/hockey/scoreboard.json")

_FNAME = re.compile(r"^(\d+)_(.+)\.wav$")
_EXCLUDE = ("-break",)  # the ad-break marker is moved to played/ unplayed

FEEDS = {
    "center-ice": {
        "title": "Center Ice on The Frequency",
        "desc": "Every broadcast game, pregame to postgame call-in. "
                "Bucky Barnes and Sal DiNapoli on the call, live from "
                "the barn. The run for the Boreal Lantern, two nights "
                "a week.",
        "match": lambda label: label.startswith("center-ice-"),
        "category": "Sports",
    },
    "dream-court": {
        "title": "Dream Court",
        "desc": "Vivian Nightshade takes the night's calls — small 3am "
                "worries and bizarre dreams, interpreted with legal "
                "authority. The verdict names the real feeling "
                "underneath. Court is in session when the town can't "
                "sleep.",
        "match": lambda label: label.startswith("night-shift-") and any(
            s in label for s in ("dream-court", "cant-sleep")),
        "category": "Society & Culture",
    },
    "static-hour": {
        "title": "The Static Hour",
        "desc": "One night, one rabbit hole. The Watcher connects the "
                "toasters to the crosswalk buttons to the geese while "
                "the town sleeps. The Numbers punctuate the descent.",
        "match": lambda label: label.startswith("static-hour-"),
        "category": "Comedy",
    },
}


def _env() -> dict:
    cfg = {}
    try:
        for ln in ENV.read_text().splitlines():
            if "=" in ln and not ln.lstrip().startswith("#"):
                k, v = ln.split("=", 1)
                cfg[k.strip()] = v.strip()
    except Exception:
        pass
    return cfg


def _run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"published": {}}


def _save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(STATE)


def _bday(mtime: float) -> str:
    """Broadcast day: before 05:00 belongs to the previous day's shows."""
    dt = datetime.fromtimestamp(mtime)
    d = dt.date() - timedelta(days=1) if dt.hour < 5 else dt.date()
    return d.isoformat()


def _feed_of(label: str) -> str | None:
    if any(x in label for x in _EXCLUDE):
        return None
    for key, f in FEEDS.items():
        if f["match"](label):
            return key
    return None


# ── harvest: played/ -> staging/<feed>/<bday>/ (hard links, idempotent) ─────
def harvest(state: dict) -> int:
    linked = 0
    if not PLAYED.is_dir():
        return 0
    for p in sorted(PLAYED.glob("*.wav")):
        m = _FNAME.match(p.name)
        if not m:
            continue
        feed = _feed_of(m.group(2))
        if not feed:
            continue
        bday = _bday(p.stat().st_mtime)
        if bday in state["published"].get(feed, {}):
            continue                    # a late straggler after the cut
        dst = STAGE / feed / bday / p.name
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(p, dst)
        except OSError:
            import shutil
            shutil.copy2(p, dst)
        linked += 1
    return linked


# ── cut: a staged (feed, bday) is ready once the show has gone quiet ────────
def ready(state: dict, now: float | None = None) -> list:
    now = now or time.time()
    out = []
    if not STAGE.is_dir():
        return out
    for feed_dir in sorted(STAGE.iterdir()):
        if not feed_dir.is_dir() or feed_dir.name not in FEEDS:
            continue
        for day_dir in sorted(feed_dir.iterdir()):
            if not day_dir.is_dir():
                continue
            files = sorted(day_dir.glob("*.wav"))
            if not files:
                continue
            if day_dir.name in state["published"].get(feed_dir.name, {}):
                continue
            newest = max(f.stat().st_mtime for f in files)
            if now - newest >= QUIET_MIN * 60:
                out.append((feed_dir.name, day_dir.name, files))
    return out


def _episode_title(feed: str, bday: str) -> str:
    nice = datetime.fromisoformat(bday).strftime("%A, %B %-d, %Y")
    if feed == "center-ice":
        try:  # name the matchup (never the score — no spoilers in a title)
            sb = json.loads(SCOREBOARD.read_text())
            for day in sb.get("days", []):
                if day.get("date") != bday:
                    continue
                for g in day.get("games", []):
                    if g.get("air"):
                        return (f"{g['away']} at {g['home']} — {nice}")
        except Exception:
            pass
        return f"Center Ice — {nice}"
    if feed == "dream-court":
        return f"Dream Court — {nice}"
    return f"The Static Hour — {nice}"


def _encode(files: list, mp3: Path, title: str, feed: str,
            bday: str) -> float | None:
    """Concat -> loudnorm -> mono MP3. Returns duration seconds, or None."""
    WORK.mkdir(parents=True, exist_ok=True)
    lst = WORK / "concat.txt"
    lst.write_text("".join(f"file '{f.resolve()}'\n" for f in files))
    r = _run(["nice", "-n", "10", "ffmpeg", "-y", "-v", "error",
              "-f", "concat", "-safe", "0", "-i", str(lst),
              "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
              "-ar", "24000", "-ac", "1", "-b:a", BITRATE,
              "-metadata", f"title={title}",
              "-metadata", "artist=The Frequency",
              "-metadata", f"album={FEEDS[feed]['title']}",
              "-metadata", f"date={bday}",
              str(mp3)])
    if r.returncode != 0:
        print(f"  !! podcast encode failed ({feed} {bday}): "
              f"{r.stderr.strip()[:200]}")
        return None
    pr = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", str(mp3)])
    try:
        return float(pr.stdout.strip())
    except Exception:
        return 0.0


def _publish_audio(mp3: Path, feed: str, bday: str, cfg: dict) -> str | None:
    """Upload (R2 mode) or place locally. Returns the public URL, or None."""
    remote = cfg.get("MEDIA_REMOTE")
    base = cfg.get("MEDIA_BASE") or f"{SITE}/podcasts"
    key = f"{feed}/{bday}.mp3"
    if remote:
        r = _run(["rclone", "copyto", str(mp3), f"{remote}/{key}"])
        if r.returncode != 0:
            print(f"  !! podcast upload failed ({key}): "
                  f"{r.stderr.strip()[:200]} — retrying next tick")
            return None
        mp3.unlink(missing_ok=True)     # audio lives remote; box disk stays flat
        return f"{base}/{key}"
    dst = WWW / key
    dst.parent.mkdir(parents=True, exist_ok=True)
    mp3.replace(dst)
    return f"{base}/{key}"


def _dur_hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def write_rss(feed: str, state: dict) -> None:
    f = FEEDS[feed]
    eps = state["published"].get(feed, {})
    items = []
    for bday in sorted(eps, reverse=True):
        e = eps[bday]
        items.append(f"""  <item>
   <title>{_sx.escape(e['title'])}</title>
   <description>{_sx.escape(f['desc'])}</description>
   <guid isPermaLink="false">bestairadio-{feed}-{bday}</guid>
   <pubDate>{e['pub']}</pubDate>
   <enclosure url="{_sx.escape(e['url'])}" length="{e['bytes']}" type="audio/mpeg"/>
   <itunes:duration>{_dur_hms(e['secs'])}</itunes:duration>
  </item>""")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
 <channel>
  <title>{_sx.escape(f['title'])}</title>
  <link>{SITE}</link>
  <description>{_sx.escape(f['desc'])}</description>
  <language>en-us</language>
  <atom:link href="{SITE}/podcasts/{feed}/feed.xml" rel="self" type="application/rss+xml"/>
  <itunes:author>The Frequency</itunes:author>
  <itunes:explicit>false</itunes:explicit>
  <itunes:image href="{SITE}/podcasts/art/{feed}.png"/>
  <itunes:category text="{_sx.escape(f['category'])}"/>
  <itunes:owner><itunes:name>The Frequency</itunes:name></itunes:owner>
{chr(10).join(items)}
 </channel>
</rss>
"""
    out = WWW / feed / "feed.xml"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(xml)
    tmp.replace(out)


def _retention(feed: str, state: dict, cfg: dict) -> None:
    """Local mode only: keep the newest LOCAL_KEEP episodes on disk (the
    feed drops them too, so clients never see a dead enclosure)."""
    if cfg.get("MEDIA_REMOTE"):
        return
    eps = state["published"].get(feed, {})
    for bday in sorted(eps)[:-LOCAL_KEEP]:
        (WWW / feed / f"{bday}.mp3").unlink(missing_ok=True)
        del eps[bday]


def main() -> None:
    cfg = _env()
    state = _load_state()
    n = harvest(state)
    if n:
        print(f"  podcast: staged {n} new segment(s)")
    for feed, bday, files in ready(state):
        title = _episode_title(feed, bday)
        mp3 = WORK / f"{feed}-{bday}.mp3"
        secs = _encode(files, mp3, title, feed, bday)
        if secs is None:
            continue
        size = mp3.stat().st_size
        url = _publish_audio(mp3, feed, bday, cfg)
        if not url:
            continue                    # upload hiccup: retry next tick
        state["published"].setdefault(feed, {})[bday] = {
            "title": title, "url": url, "bytes": size, "secs": secs,
            "pub": formatdate(time.time())}
        _retention(feed, state, cfg)
        write_rss(feed, state)
        _save_state(state)
        import shutil
        shutil.rmtree(STAGE / feed / bday, ignore_errors=True)
        print(f"  podcast: published {feed} {bday} "
              f"({_dur_hms(secs)}, {size // 1024 // 1024}MB)")
    _save_state(state)


if __name__ == "__main__":
    main()
