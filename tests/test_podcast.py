"""Podcast pipeline: harvest links before the prune, episodes cut on quiet,
feeds are valid RSS, and nothing ever spoils or double-publishes.

Runs against a temp tree with ffmpeg/ffprobe/rclone stubbed — no audio is
actually encoded. All fixture times are frozen synthetic timestamps well in
the past (never wall-clock relative: a fixture straddling the 05:00
broadcast-day boundary would test a situation the schedule can't produce).
Plain python3, PASS/FAIL counters, exit code.
"""
import json
import os
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import podcast as P  # noqa: E402

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def ts(s):
    return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M"))


def wav(name, when):
    p = P.PLAYED / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"RIFFfake")
    os.utime(p, (when, when))
    return p


def fake_run(cmd, **kw):
    class R:
        returncode = 0
        stdout = "1234.5\n"
        stderr = ""
    if cmd[0] == "nice":                      # the encoder: emit a fake mp3
        Path(cmd[-1]).write_bytes(b"ID3fakemp3" * 100)
    return R()


prev = os.getcwd()
with tempfile.TemporaryDirectory() as td:
    os.chdir(td)
    try:
        P.PLAYED = Path("audio_buffer/played")
        P.STAGE = Path("podcast/staging")
        P.STATE = Path("podcast/state.json")
        P.WORK = Path("podcast/work")
        P.WWW = Path("www/podcasts")
        P.ENV = Path("no-such.env")           # local mode
        P.SCOREBOARD = Path("scoreboard.json")
        P._run = fake_run

        # a Night Shift straddling midnight (22:xx + 00:xx -> one episode),
        # a Static Hour, excluded content, and a foreign show
        T = ts("2026-07-10 22:00")
        wav("000000101_night-shift-cant-sleep.wav", T)
        wav("000000102_night-shift-dream-court.wav", T + 60)
        wav("000000103_night-shift-break.wav", T + 90)
        wav("000000104_night-shift-the-quiet-part.wav", T + 120)
        wav("000000105_static-hour-tonights-theory.wav",
            ts("2026-07-11 01:30"))
        wav("000000106_morning-scramble-the-rundown.wav",
            ts("2026-07-11 06:30"))
        wav("000000107_night-shift-dream-court.wav", ts("2026-07-11 00:40"))

        st = P._load_state()
        n = P.harvest(st)
        check(n == 4, f"harvest links only feed-matched, non-marker files "
              f"(got {n})")
        check(not list(P.STAGE.rglob("*break*")), "break marker excluded")
        check(not list(P.STAGE.rglob("*quiet-part*")),
              "non-call Night Shift segment excluded from Dream Court")
        check(not list(P.STAGE.rglob("*scramble*")),
              "shows without a feed never staged")
        check(P.harvest(st) == 0, "harvest is idempotent")

        # broadcast-day rule: 23:50 and 00:30 land on the same episode day
        check(P._bday(ts("2026-07-11 23:50"))
              == P._bday(ts("2026-07-12 00:30")) == "2026-07-11",
              "broadcast-day rule spans midnight")
        dc_days = [d.name for d in sorted((P.STAGE / "dream-court")
                                          .iterdir())]
        check(dc_days == ["2026-07-10"],
              f"pre- and post-midnight files share one episode ({dc_days})")

        # quiet rule: mid-show nothing cuts; 90 min after the last file it does
        r_mid = P.ready(st, ts("2026-07-11 00:41"))
        check(not any(f == "dream-court" for f, _, _ in r_mid),
              "a still-airing show is never cut")
        r_after = {(f, d) for f, d, _ in P.ready(st, ts("2026-07-11 08:00"))}
        check(("dream-court", "2026-07-10") in r_after
              and ("static-hour", "2026-07-10") in r_after,
              f"quiet shows are ready to cut (got {r_after})")

        # scoreboard titling: no scores in a Center Ice episode title
        Path("scoreboard.json").write_text(json.dumps({"days": [
            {"date": "2026-07-10", "games": [
                {"home": "New York Gridlock",
                 "away": "Providence Mild Concern",
                 "score": [5, 4], "air": True, "status": "final"}]}]}))
        t = P._episode_title("center-ice", "2026-07-10")
        check("Providence Mild Concern at New York Gridlock" in t,
              "center-ice title names the matchup")
        check("5" not in t and "4" not in t, "no score spoiler in the title")

        # publish end-to-end (local mode) — everything is long quiet by now
        P.main()
        st = P._load_state()
        eps = st["published"].get("dream-court", {})
        check(list(eps) == ["2026-07-10"], "one dream-court episode")
        e = eps["2026-07-10"]
        check((P.WWW / "dream-court" / "2026-07-10.mp3").exists(),
              "local mode leaves the mp3 on the site tree")
        check(e["url"].endswith("/podcasts/dream-court/2026-07-10.mp3"),
              "local enclosure URL under the site")
        check(not (P.STAGE / "dream-court" / "2026-07-10").exists(),
              "staging cleaned after publish")
        check("static-hour" in st["published"], "static hour published too")

        feed = P.WWW / "dream-court" / "feed.xml"
        check(feed.exists(), "feed.xml written")
        root = ET.parse(feed).getroot()
        ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
        ch = root.find("channel")
        check(ch.find("title").text == "Dream Court", "channel title")
        check(ch.find("itunes:image", ns) is not None, "itunes artwork tag")
        item = ch.find("item")
        guid = item.find("guid")
        check(guid.text == "bestairadio-dream-court-2026-07-10"
              and guid.get("isPermaLink") == "false", "stable non-URL guid")
        enc = item.find("enclosure")
        check(enc.get("type") == "audio/mpeg"
              and int(enc.get("length")) > 0, "enclosure length + type")
        check(item.find("itunes:duration", ns).text == "0:20:34",
              "duration from ffprobe rendered h:mm:ss")

        # second pass: nothing new, nothing double-published
        P.main()
        st2 = P._load_state()
        check(len(st2["published"]["dream-court"]) == 1,
              "no double publish on the next tick")
        # a straggler file for a published day is never re-staged
        wav("000000108_night-shift-dream-court.wav", T + 200)
        check(P.harvest(st2) == 0, "stragglers after the cut are ignored")

        # R2 mode: upload path + local mp3 removed
        P.ENV = Path("podcast.env")
        P.ENV.write_text("MEDIA_REMOTE=r2:frequency-media\n"
                         "MEDIA_BASE=https://media.example.com\n")
        calls = []

        def fake_run2(cmd, **kw):
            calls.append(cmd)
            return fake_run(cmd, **kw)
        P._run = fake_run2
        wav("000000090_night-shift-dream-court.wav", ts("2026-07-08 23:00"))
        P.harvest(st2)
        P._save_state(st2)
        P.main()
        st3 = P._load_state()
        e2 = st3["published"]["dream-court"].get("2026-07-08")
        check(e2 is not None, "R2-mode episode published")
        check(e2["url"] == "https://media.example.com/dream-court/"
                           "2026-07-08.mp3",
              "enclosure points at the media domain")
        check(any(c[0] == "rclone" and c[1] == "copyto" for c in calls),
              "audio uploaded via rclone")
        check(not (P.WORK / "dream-court-2026-07-08.mp3").exists(),
              "local copy removed after upload")

        # retention (local mode): oldest beyond LOCAL_KEEP dropped
        P.ENV = Path("no-such.env")
        st4 = {"published": {"static-hour": {}}}
        for i in range(1, 19):
            d = f"2026-06-{i:02d}"
            (P.WWW / "static-hour").mkdir(parents=True, exist_ok=True)
            (P.WWW / "static-hour" / f"{d}.mp3").write_bytes(b"x")
            st4["published"]["static-hour"][d] = {
                "title": "t", "url": "u", "bytes": 1, "secs": 1,
                "pub": "Mon, 01 Jun 2026 00:00:00 -0000"}
        P._retention("static-hour", st4, {})
        left = st4["published"]["static-hour"]
        check(len(left) == P.LOCAL_KEEP, "retention keeps LOCAL_KEEP")
        check("2026-06-01" not in left and "2026-06-18" in left,
              "oldest dropped, newest kept")
        check(not (P.WWW / "static-hour" / "2026-06-01.mp3").exists(),
              "pruned audio removed from disk")
    finally:
        os.chdir(prev)

print(f"podcast {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
