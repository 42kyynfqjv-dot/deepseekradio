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
import time
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
    r"(?:Bureau|Corporation|Corp|Committee|Group|Institute|Company|Office|"
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
    from . import leakguard as _leak
    rows = "\n".join(
        f"- {_leak.clean_public_text(e['name'], 'an unnamed file')} — "
        f"{_leak.clean_public_text(e['dossier'], 'a harmless file')}"
        for e in tonight)
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
    from . import leakguard as _leak
    body = " ".join(ln.get("text", "") for ln in lines
                    if not ln.get("_enforced")
                    and not _leak.has_leak(ln.get("text", "")))
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
    if len(ents) > BANK_CAP:   # the board only holds so many photos — but
        # the SEED files are the permanent collection; only harvested
        # entities compete for the remaining pins
        seeds = [e for e in ents if e.get("seeded") is not False]
        grown = [e for e in ents if e.get("seeded") is False]
        grown.sort(key=lambda e: (e.get("last_night") or "",
                                  e.get("nights", 0)), reverse=True)
        ents[:] = seeds + grown[:max(0, BANK_CAP - len(seeds))]
    return new


# --- the theory clock: one descent per hour, restart-proof -------------------
# A rabbit hole must OWN its hour (owner call): re-entering the show inside
# THEORY_MIN minutes of the current theory's start — buffer refill or service
# restart alike — CONTINUES the same descent (write_outline's continue_theory
# arg); past the hour, a fresh theory begins and the ledger stamps it. The
# ledger doubles as the podcast cutter's episode boundary and title source:
# one theory = one episode.
THEORY_MIN = 60
THEORIES = Path("data/watcher/theories.json")
CHAPTERS = Path("data/watcher/chapters.json")


def _cload() -> list:
    try:
        return json.loads(CHAPTERS.read_text())
    except Exception:
        return []


def closed_chapters(limit: int | None = None) -> list:
    chapters = _cload()
    return chapters[-limit:] if limit else chapters


def _eligible_chapters(date: str, n: int) -> list:
    """A chapter sleeps for three later closures after its last reuse."""
    chapters = _cload()
    current_index = len(chapters)
    eligible = []
    for idx, chapter in enumerate(chapters):
        uses = [j for j in range(idx + 1, len(chapters))
                if chapters[j].get("builds_on") == chapter.get("id")]
        last_use = max(uses, default=idx)
        # current_index is the next episode slot; subtract one because the
        # current slot has not closed yet. Require three completed chapters
        # after the original or most recent reuse.
        if current_index - max(idx, last_use) - 1 >= 3:
            eligible.append(chapter)
    return eligible


def sequel_candidates(date: str, n: int, limit: int = 4) -> list:
    """Return the coinflip-approved, three-chapter-rested sequel files."""
    if _hash(f"watcher-sequel:{date}:t{n}") % 2:
        return []
    return list(reversed(_eligible_chapters(date, n)))[:limit]


def sequel_candidate_ids(date: str, n: int) -> set[str]:
    return {str(c.get("id")) for c in sequel_candidates(date, n)
            if c.get("id")}

def close_chapter(date: str, n: int, frame: str, payoff: str,
                  lines: list[dict], loose_threads: list | None = None,
                  builds_on: str | None = None) -> dict:
    """Persist a completed chapter without changing the live theory clock."""
    from . import leakguard as _leak
    frame = _leak.clean_public_text(
        frame, "an earlier harmless outside-world pattern")
    payoff = _leak.clean_public_text(
        payoff, "the clues fit together in a harmless way")
    body = " ".join(str(ln.get("text", "")) for ln in lines
                    if not ln.get("_enforced")
                    and not _leak.has_leak(ln.get("text", "")))
    threads = [
        _leak.clean_public_text(str(x).strip(), "an ordinary loose thread")
        for x in (loose_threads or []) if str(x).strip()
    ]
    source = " ".join([frame, payoff, *threads, body])
    entities = []
    seen = set()
    for m in _ORG.finditer(source):
        name = m.group(1).strip()
        low = name.lower()
        if low not in seen and not _real_world(name):
            seen.add(low)
            entities.append(name)
    parent = str(builds_on or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}-t\d+", parent):
        parent = None
    chapter = {
        "id": f"{date}-t{n}",
        "date": date,
        "n": n,
        "frame": str(frame or "").strip()[:180],
        "payoff": str(payoff or "").strip()[:260],
        "entities": entities[:12],
        "loose_threads": threads[:4],
        "builds_on": parent,
        "closed_at": time.time(),
    }
    chapters = [c for c in _cload() if c.get("id") != chapter["id"]]
    chapters.append(chapter)
    chapters = chapters[-80:]
    CHAPTERS.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHAPTERS.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(chapters, indent=1))
    tmp.replace(CHAPTERS)
    return chapter


def chapter_block(date: str, n: int, limit: int = 4) -> str:
    """Offer optional sequel material only after the three-chapter jail."""
    prior = sequel_candidates(date, n, limit=limit)
    if not prior:
        return ""
    rows = []
    from . import leakguard as _leak
    for c in prior:
        frame = _leak.clean_public_text(
            c.get("frame", ""), "an earlier harmless pattern")
        payoff = _leak.clean_public_text(
            c.get("payoff", ""), "the earlier chapter reached a harmless end")
        row = (f"- {c.get('id')}: FRAME — {frame}; "
               f"CLOSED PAYOFF — {payoff}")
        if c.get("entities"):
            files = [
                _leak.clean_public_text(x, "an unnamed file")
                for x in c["entities"][:6]
            ]
            row += "; FILES — " + ", ".join(files)
        if c.get("loose_threads"):
            threads = [
                _leak.clean_public_text(x, "an ordinary loose thread")
                for x in c["loose_threads"][:3]
            ]
            row += "; OPTIONAL LOOSE THREADS — " + "; ".join(threads)
        rows.append(row)
    return (
        "\nCLOSED WATCHER CHAPTERS (optional sequel material; the desk's "
        "sequel coinflip came up heads):\n"
        + "\n".join(rows)
        + "\nYou may build on AT MOST ONE prior chapter, or start fresh. "
        "If you build on one, use its files or a loose thread as evidence for "
        "a NEW chapter and set builds_on to that exact chapter id. Do not undo "
        "or merely repeat a prior payoff; every chapter still gets its own "
        "conclusion.\n"
    )


def current_entry(date: str, now: float) -> dict | None:
    """Return the active chapter record, if this hour already has one."""
    led = _tload()
    tonight = [e for e in led if e.get("date") == date]
    if not tonight:
        return None
    last = tonight[-1]
    return (last if now - last.get("started", 0) < THEORY_MIN * 60
            else None)


def spine_block(entry: dict | None) -> str:
    """Prompt block for the current chapter's durable frame and landing."""
    if not entry:
        return ""
    from . import leakguard as _leak
    frame = _leak.clean_public_text(
        entry.get("frame") or entry.get("subject") or "",
        "an invented outside-world pattern")
    if not frame:
        return ""
    payoff = _leak.clean_public_text(
        entry.get("payoff") or "",
        "gather the clues into one harmless, absurd conclusion")
    return (
        "\nWATCHER THEORY SPINE (authoritative chapter frame):\n"
        f"- FRAME: {frame}\n"
        f"- LANDING: {payoff}\n"
        "- Every new object, caller, and organization is evidence for this frame. "
        "Connect it with a because, which means, or so that sentence. Do not "
        "silently replace the frame with a new subject.\n"
        "- The chapter must close by explaining how the named clues fit together. "
        "A later chapter may reopen this universe, but this one gets an ending.\n"
    )


def _tload() -> list:
    try:
        return json.loads(THEORIES.read_text())
    except Exception:
        return []


def current_theory(date: str, now: float) -> tuple:
    """(subject_to_continue | None, ordinal_for_tonight). The ordinal names
    the episode (t1, t2, ...) whether we continue or begin."""
    active = current_entry(date, now)
    if active:
        from . import leakguard as _leak
        subject = _leak.clean_public_text(
            active.get("subject") or active.get("frame") or "",
            "an invented outside-world pattern")
        return subject or None, active.get("n", 1)
    led = _tload()
    tonight = [e for e in led if e.get("date") == date]
    if tonight:
        return None, tonight[-1].get("n", 1) + 1
    return None, 1


def begin_theory(date: str, n: int, subject: str, now: float,
                 *, frame: str | None = None,
                 payoff: str | None = None) -> None:
    from . import leakguard as _leak
    led = _tload()
    raw_frame = _leak.clean_public_text(
        str(frame or subject or "").strip(),
        "an invented outside-world pattern")
    if _real_world(raw_frame):
        # The frame becomes a public podcast title and a prompt anchor. Do not
        # persist a real-world name into either surface.
        raw_frame = "an invented outside-world pattern"
        subject = ""
    else:
        subject = str(subject or raw_frame).strip()
    landing = _leak.clean_public_text(
        str(payoff or "").strip(),
        "gather the clues into one harmless, absurd conclusion")
    led.append({"date": date, "n": n, "subject": subject[:90],
                "frame": raw_frame[:180], "payoff": landing[:240],
                "started": now})
    del led[:-80]
    THEORIES.parent.mkdir(parents=True, exist_ok=True)
    tmp = THEORIES.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(led, indent=1))
    tmp.replace(THEORIES)


def theory_subject(date: str, n: int) -> str | None:
    """The ledger's subject for episode (date, n) — the podcast titles from
    this; None if the ledger never saw it."""
    for e in reversed(_tload()):
        if e.get("date") == date and e.get("n") == n:
            return e.get("subject") or None
    return None
