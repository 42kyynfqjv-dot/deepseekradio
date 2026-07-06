"""Frequency News — hourly bulletin: real headlines, absurdly mangled.

Pulls a handful of real headlines from RSS, then has the writer model twist them
into the station's 90-second top-of-the-hour news. Real-world input is the
station's staleness defense: the world writes new material every day.
"""
from __future__ import annotations

import random
import re
import xml.etree.ElementTree as ET

import requests

from .openrouter import chat


def fetch_headlines(feeds: list[str], count: int, used: set | None = None) -> list[str]:
    """Grab item titles from RSS feeds; tolerate any feed being down.
    `used` filters out headlines already mangled in the last 24h."""
    titles: list[str] = []
    for url in feeds:
        try:
            r = requests.get(url, timeout=15,
                             headers={"User-Agent": "The Frequency/1.0"})
            r.raise_for_status()
            root = ET.fromstring(r.content)
            for item in root.iter("item"):
                t = item.findtext("title")
                if t:
                    titles.append(re.sub(r"\s+", " ", t).strip())
        except Exception:
            continue  # a dead feed shouldn't kill the bulletin
    if used:
        titles = [t for t in titles if t not in used]
    random.shuffle(titles)
    return titles[:count]


def write_bulletin(headlines: list[str], models: dict, bible: str,
                   coming_up: str = "") -> str:
    """One small writer call -> the anchor's 90-second bulletin script."""
    if not headlines:
        headlines = ["(no news reached the bunker today)"]
    system = (
        "You write Frequency News, the absurd top-of-the-hour 90-second news bulletin "
        "for The Frequency. Take REAL headlines and twist each one sideways — keep the "
        "kernel of the real story but report it like the station's unhinged news "
        "desk would. Clean, PG. HARD RULES: never name any real person — "
        "anonymize to a role ('a senator', 'a pop star', 'a tech CEO'); never "
        "mock real tragedies; skip entirely any headline about death, war, "
        "disaster, or political violence and invent a harmless local story "
        "instead.\n\n" + bible
    )
    user = ("Today's real headlines:\n" +
            "\n".join(f"- {h}" for h in headlines) +
            "\n\nWrite the bulletin as 6-8 short spoken lines for a single news "
            "anchor. The anchor is always named Chip Hanley — no other anchor "
            "names, ever. Report at least ONE story completely straight, no "
            "joke. Never use the same comedic device twice in one bulletin. "
            + (f" Before the tagline, one line pointing at what's on now/next: "
               f"'{coming_up}' continues after the news. " if coming_up else "")
            + "End with a station tagline.")
    return chat(models["writer"],
                [{"role": "system", "content": system},
                 {"role": "user", "content": user}])
