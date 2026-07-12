"""The Watcher's private canon — recurring conspiracies only he remembers.

The Static Hour runs lore_quarantine: his theories never enter shared
station lore, and that stays true. But quarantine cut both ways — every
rabbit hole started from nothing, so no shadowy organization could ever
resurface. This file is his corkboard: a small bank of recurring entities
(seeded below, grown from his own aired inventions) that rotates into his
prompt each night. The rest of the station never reads it; the morning crew
will never treat the Pigeon Bureau as real.

Growth is code-owned and guarded: after each aired beat, organization-shaped
proper names ("the Something Bureau/Corp/Committee/...") are harvested into
the bank — screened against nameguard's real-world lists so a real company
can never be canonized — and mentions of existing entities bump their
dossier. The bank is capped; the least-recently-surfaced files fall off the
board. Stdlib-only leaf; orchestrator imports this, never the reverse.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

PATH = Path("data/watcher/canon.json")
BANK_CAP = 24
PER_NIGHT = 3          # dossiers surfaced in a night's prompt
HARVEST_PER_NIGHT = 2  # new entities canonized per night, max

SEED = [
    ("The Pigeon Bureau",
     "keeps the pigeons fed and the ledgers sealed; every park bench faces "
     "the same way for a reason"),
    ("Blinker Consolidated",
     "manufactures every turn signal in the county; profits spike when "
     "nobody signals"),
    ("The Tuesday Committee",
     "decides what happens on Tuesdays; has never once met on a Tuesday"),
    ("Substation 9",
     "the hum changed in March; the moths noticed first"),
    ("Hum Industrial",
     "sells white-noise machines and owns the silence they replace"),
    ("The Corkboard Underwriters",
     "insures conspiracy boards against sudden moments of clarity"),
    ("Geese Logistics LLC",
     "the geese don't work for them — it's worse, they subcontract"),
    ("Crosswalk Dynamics",
     "installs the buttons; the buttons are real, the wiring is a "
     "philosophy"),
    ("The Mattress Concern",
     "thirty-seven stores, zero recorded customers, always open"),
    ("The Bureau of Standard Measures",
     "shortened the inch in 1998 and nothing has measured honest since"),
]

_ORG = re.compile(
    r"\b((?:[Tt]he\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\s+"
    r"(?:Bureau|Corporation|Corp|Committee|Group|Institute|Company|"
    r"Consortium|Initiative|Division|Syndicate|Authority|Agency|Board|"
    r"Commission|Foundation|Concern|Collective|Cooperative))\b")


def _hash(s: str) -> int:
    import hashlib
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


def load() -> dict:
    try:
        return json.loads(PATH.read_text())
    except Exception:
        return {"entities": [
            {"name": n, "dossier": d, "first_night": "", "last_night": "",
             "nights": 0} for n, d in SEED]}


def save(state: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(PATH)


def _real_world(name: str) -> bool:
    """A candidate that touches nameguard's real-entity lists is NEVER
    canonized — the Watcher's files must not contain a real company."""
    from .nameguard import _WORLD_PHRASES, _WORLD_TOKENS
    low = name.lower()
    if any(re.search(r"\b" + re.escape(p) + r"\b", low)
           for p in _WORLD_PHRASES):
        return True
    return any(t in _WORLD_TOKENS for t in re.findall(r"[a-z&'’.-]+", low))


def prompt_block(state: dict, date: str) -> str:
    """Tonight's rotation of dossiers, seeded by date — stable within a
    night, fresh across nights. Never contradicting a dossier is the rule;
    resurfacing one is an invitation, not an order."""
    ents = state.get("entities", [])
    if not ents:
        return ""
    rng_order = sorted(ents, key=lambda e: _hash(f"watcher:{date}:{e['name']}"))
    tonight = rng_order[:PER_NIGHT]
    rows = "\n".join(f"- {e['name']} — {e['dossier']}" for e in tonight)
    return ("\nTHE WATCHER'S FILES (private canon — only he remembers; "
            "the rest of the station has never heard of these): \n" + rows +
            "\nIf tonight's theory brushes one of these, let it RESURFACE "
            "naturally — an old file reopened, deeper than before. Never "
            "contradict a dossier. Inventing NEW organizations is allowed "
            "and encouraged; the memorable ones join the files.")


def harvest(lines: list, state: dict, date: str) -> int:
    """Walk aired lines: bump dossiers that resurfaced, canonize up to
    HARVEST_PER_NIGHT new organization-shaped inventions. Returns new count."""
    ents = state.setdefault("entities", [])
    by_low = {e["name"].lower().removeprefix("the ").strip(): e
              for e in ents}
    body = " ".join(ln.get("text", "") for ln in lines
                    if not ln.get("_enforced"))
    for key, e in by_low.items():
        if re.search(r"\b" + re.escape(key) + r"\b", body, re.I):
            if e["last_night"] != date:
                e["nights"] = e.get("nights", 0) + 1
                e["last_night"] = date
            if not e.get("first_night"):
                e["first_night"] = date
    added_tonight = sum(1 for e in ents if e.get("first_night") == date
                        and e.get("seeded") is False)
    new = 0
    for m in _ORG.finditer(body):
        name = m.group(1).strip()
        low = name.lower().removeprefix("the ").strip()
        if low in by_low or _real_world(name) or len(low) < 6:
            continue
        if added_tonight + new >= HARVEST_PER_NIGHT:
            break
        sent = next((s.strip() for s in re.split(r"(?<=[.!?])\s+", body)
                     if name in s), "")[:110]
        ents.append({"name": name if name[0].isupper() else name.title(),
                     "dossier": sent or "a new file, still thin",
                     "first_night": date, "last_night": date, "nights": 1,
                     "seeded": False})
        by_low[low] = ents[-1]
        print(f"  watcher canon: new file opened on {name!r}")
        new += 1
    if len(ents) > BANK_CAP:   # the board only holds so many photos
        ents.sort(key=lambda e: (e.get("last_night") or "", e.get("nights", 0)),
                  reverse=True)
        del ents[BANK_CAP:]
    return new
