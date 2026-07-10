"""Chartguard — anti-hallucination cop for the HALFWAY HOT 10 (design §6).

Scoreguard-mirrored (`src/scoreguard.py`, `src/statehouse/civicguard.py`):
`hot10.py` rolls the facts; a performer narrates them at temp 0.9 and will
invent a #1, flip a debut, misquote weeks-on-chart, or misname an act.
`build_chart_facts` digests one already-rolled chart week into lookup
tables; `enforce_chart` walks a beat's lines against them. Contradicting
lines are REPLACED (never cut — a cut dangles the partner's reply) with a
neutral line in the countdown register; phantom act names anchored to a
chart claim are corrected in place; and — the prime directive — no correct
line is ever falsely touched. Stdlib-only leaf module: performers/
orchestrator import this, never the reverse. No imports of `hot10.py` or
any sibling `src/music/*` module (a separate leaf component, mirroring
civicguard's own "no cross-import of siblings" discipline) — this module
only needs to agree with `hot10.py`'s week-record *shape*.

Catches (§6):
  1. invented current rank / position           -> the real rank, grounded
  2. invented last-week position                -> the real LW, grounded
  3. invented weeks-on-chart                     -> the real count
  4. invented peak                               -> the real peak
  5. invented debut / Hot Shot Debut claims      -> the real debut/hot-shot
  6. invented Greatest Gainer claims             -> the real gainer
  7. invented bullet claims                      -> grounded restatement
  8. invented up/down movement                   -> the real LW->rank move
  9. invented "holds steady"                     -> the real rank
  10. invented drop-off-the-chart / farewell     -> "still on the board"
  11. phantom act names near a chart claim       -> nearest real act/title

**Air-gating (§6, "aired facts are canon forever"):** this module has no
special-case code for an "aired" week because it doesn't need one — the
read-only guarantee lives in `hot10.chart()`'s derive-once-store contract
(a week, once rolled, is returned unchanged forever). Facts for ANY week,
aired or not, are built the same way: from whatever `chart` dict the caller
hands in. As long as callers always source that dict from `hot10.chart()`
(never a fresh `roll_week()` call for a week that already aired), an aired
week's facts can never drift, and this guard enforces the same immutable
truth every time it's asked.

**Subject resolution (mirrors civicguard's `last_bill`):** a countdown line
names one track/artist at a time ("Sustain holds at number one"); the
walker tracks the LAST act mentioned (this line, else carried over from an
earlier line) as the subject of any claim that follows. This is a
deliberate simplification — no position-anchored per-claim resolution like
scoreguard's goalie/scorer matching — and is only as safe as the register
it's built for: one countdown position narrated at a time.
"""
from __future__ import annotations

import hashlib
import re

# ---------------------------------------------------------------- build_chart_facts

def build_chart_facts(chart: dict, catalog: dict, *, extra_ok=()) -> dict:
    """Digest one already-rolled `hot10.py` week-record + the catalog into
    the lookup tables `enforce_chart` walks. `extra_ok` is host/persona
    names the caller wants exempted from the phantom-act-name fixer (mirrors
    nameguard's `extra_ok`) — e.g. the countdown's own host, so "Vivian
    holds up the request line" is never mistaken for a phantom act."""
    rows = chart.get("chart", [])
    rank_of, last_of, peak_of = {}, {}, {}
    weeks_of, bullet_of, debut_of, pts_of = {}, {}, {}, {}
    for r in rows:
        tid = r["tid"]
        rank_of[tid] = r["rank"]
        last_of[tid] = r["last"]
        peak_of[tid] = r["peak"]
        weeks_of[tid] = r["weeks"]
        bullet_of[tid] = r["bullet"]
        debut_of[tid] = r["debut"]
        pts_of[tid] = r["pts"]

    title_of, artist_of = {}, {}
    title_to_tid, artist_to_tid = {}, {}
    for tid, tr in catalog.get("tracks", {}).items():
        title = tr.get("title", "")
        aname = catalog.get("artists", {}).get(tr.get("artist"), {}).get("name", "")
        title_of[tid] = title
        artist_of[tid] = aname
        if title:
            title_to_tid[title.lower()] = tid
        if aname:
            artist_to_tid.setdefault(aname.lower(), tid)

    names_ok = {w.lower() for w in extra_ok}
    full_names = set()
    for title in title_of.values():
        if title:
            names_ok.add(title.lower())
            full_names.add(title)
    for aid, adef in catalog.get("artists", {}).items():
        aname = adef.get("name", "")
        if not aname:
            continue
        names_ok.add(aname.lower())
        full_names.add(aname)
        # Word-splitting a multi-word name into individually exempt tokens
        # is only safe for a genuine solo/personal act (e.g. "Merrill" or
        # "Sackville" alone still means Merrill Sackville) -- band/duo/trio
        # names commonly share ordinary English words ("The", "Season",
        # "Window", "Trio"...), and exempting those words globally would
        # let an invented act sharing any single word with a real one
        # ("The Wobblers" sharing "The" with "The Merge") dodge correction.
        if adef.get("act") == "solo":
            names_ok.update(w.lower() for w in aname.split())

    facts = {
        "week": chart.get("week"),
        "rank_of": rank_of, "last_of": last_of, "peak_of": peak_of,
        "weeks_of": weeks_of, "bullet_of": bullet_of, "debut_of": debut_of,
        "pts_of": pts_of,
        "title_of": title_of, "artist_of": artist_of,
        "title_to_tid": title_to_tid, "artist_to_tid": artist_to_tid,
        "names_ok": names_ok, "full_names": full_names,
        "hot_shot": chart.get("hot_shot"), "gainer": chart.get("gainer"),
        "droppers": set(chart.get("droppers", [])),
        "retired": set(chart.get("retired", [])),
    }
    facts["_mention_re"] = _mention_pattern(facts)
    return facts


def _mention_pattern(facts):
    names = sorted(set(facts["title_to_tid"]) | set(facts["artist_to_tid"]),
                   key=len, reverse=True)
    if not names:
        return None
    return re.compile("|".join(re.escape(n) for n in names), re.I)


def _mentions(text, facts):
    """[(pos, tid), ...] for every catalog title/artist named on the line,
    in order of appearance.

    `artist_to_tid` necessarily maps an artist name to just ONE of that
    artist's (possibly several) tracks — an arbitrary pick (see
    `build_chart_facts`). Every `narrate()`/`sheets.py` line names a track as
    "{title} — {artist}", so the artist mention immediately trails the
    title mention on nearly every real line. If that artist has more than
    one track, a bare `artist_to_tid` lookup would silently swap the
    already-resolved specific track for the artist's arbitrary other one,
    and since "last mention wins" for subject binding, a true claim about
    the just-named title would then get checked against the WRONG track's
    facts. When an artist mention's name matches the artist of the tid
    immediately preceding it, treat it as attributive (still the same
    track just named) rather than a new, ambiguous subject."""
    pat = facts.get("_mention_re")
    if not pat:
        return []
    out = []
    last_tid = None
    for m in pat.finditer(text):
        low = m.group(0).lower()
        tid = facts["title_to_tid"].get(low)
        if tid is None:
            tid = facts["artist_to_tid"].get(low)
            if (tid is not None and last_tid is not None and
                    facts["artist_of"].get(last_tid, "").lower() == low):
                tid = last_tid
        if tid:
            out.append((m.start(), tid))
            last_tid = tid
    return out


# ---------------------------------------------------------------- lexicons

_MODAL = re.compile(   # predictions/hypotheticals pass whole (mirror scoreguard)
    r"next (?:week|show|time)|gonna|will (?:be|climb|debut|drop|hold)|\bwould\b|"
    r"\bif |could'?ve|should'?ve|i bet|prediction|imagine|what if|my guess|"
    r"i (?:think|bet) it(?:'ll| will)")

# Broadcast copy says "number four," not "number 4" -- word numbers are
# normalized to digits before any claim regex runs (mirror scoreguard's
# _norm). Capped at twenty: chart positions run 1-10, weeks-on-chart tops
# out at the hard retirement ceiling (16), peak is 1-10.
_UNITS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
          "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
          "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
          "twenty": 20}
_WORDNUM = re.compile(r"\b(" + "|".join(_UNITS) + r")\b")


def _normalize_numbers(text: str) -> str:
    return _WORDNUM.sub(lambda m: str(_UNITS[m.group(1)]), text.lower())


# NOTE: "#" must NOT sit behind a \b like "number"/"no." do -- \b only fires
# at a word/non-word transition, and "#" is itself a non-word character, so
# "\b#" can never match when "#" is preceded by whitespace (the overwhelming
# real case: "sitting at #9", "debuts at #4"). Each alternative carries its
# own boundary instead of sharing one in front of the whole group.
_RANK_CLAIM = re.compile(r"(?:\bnumber|\bno\.?|#)\s*(\d{1,2})\b", re.I)
_SKIP_WINDOW = re.compile(
    r"\bfrom\s*$|\bpeak(?:ed|s)?\s+(?:of|at)\s*$|\blast week\b.{0,10}$|"
    r"\bweeks?\s*$")
_LAST_CLAIM = re.compile(
    r"\blast week\b[^.]{0,30}?(?:\bnumber|\bno\.?|#)\s*(\d{1,2})\b", re.I)
_FROM_CLAIM = re.compile(
    r"\b(?:up|down|climbing|falling)\s+from\s+(?:number|no\.?|#)?\s*(\d{1,2})\b",
    re.I)
_WEEKS_CLAIM = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+weeks?\s+(?:on the (?:chart|countdown)|"
    r"now|running|and counting)\b", re.I)
_WEEKS_CLAIM2 = re.compile(r"\bits\s+(\d{1,2})(?:st|nd|rd|th)\s+week\b", re.I)
_PEAK_CLAIM = re.compile(
    r"\bpeak(?:ed|s)?\s+(?:of|at)\s+(?:number|no\.?|#)?\s*(\d{1,2})\b", re.I)
_DEBUT_NUM = re.compile(
    r"\b(?:debuts?|enters?(?: the chart)?)\s+(?:at\s+)?(?:\bnumber|\bno\.?|#)\s*"
    r"(\d{1,2})\b", re.I)
_DEBUT_BARE = re.compile(
    r"\b(?:debuts?|brand[- ]new entry|new entry)\b", re.I)
_HOTSHOT_CLAIM = re.compile(r"\bhot shot debut\b", re.I)
_GAINER_CLAIM = re.compile(r"\bgreatest gainer\b", re.I)
_BULLET_CLAIM = re.compile(r"\bwith a bullet\b|\bbullet\b", re.I)
_UP_CLAIM = re.compile(
    r"\b(?:climbs?|climbing|jumps?|jumping|rises?|rising|moving up|"
    r"moves? up)\b", re.I)
_DOWN_CLAIM = re.compile(
    r"\b(?:falls?|falling|slides?|sliding|slips?|slipping)\b"
    r"(?!\s+off\s+(?:the\s+)?(?:chart|countdown))", re.I)
_DROPOFF_CLAIM = re.compile(
    r"\bdrops? off (?:the )?(?:chart|countdown)\b|"
    r"\bfalls? off (?:the )?(?:chart|countdown)\b|"
    r"\bsays? goodbye\b|\bwaves? goodbye\b|"
    r"\bexits? the (?:chart|countdown)\b", re.I)
_HOLD_CLAIM = re.compile(r"\bhold(?:s|ing)?\s+(?:steady\s+)?at\b", re.I)

# Phantom-act-name anchor: a Title-Case run immediately before a chart verb —
# the exact register a countdown line uses ("Sustain holds at number one",
# "The Roundabouts climb to number four"). Anchored so free-form banter
# naming a host/caller is never scanned.
_ACT_SUBJECT = re.compile(
    r"\b([A-Z][a-zA-Z'’.]+(?:\s+[A-Z][a-zA-Z'’.]+){0,4})"
    r"\s+(?:holds?|debuts?|climbs?|climbing|jumps?|falls?|falling|slides?|"
    r"slips?|peaks?|peaked|enters?|exits?|returns?)\b")

_HOLD_FIX = ["Checking the board, that's holding at number {rank}.",
             "The board still has it at number {rank}.",
             "No move to report — number {rank}, same as it was."]
_MOVE_FIX = ["Checking the board, {who} moves from number {last} to number {rank}.",
             "The real move: {who} goes number {last} to number {rank}.",
             "That's number {last} to number {rank} on the board for {who}."]
_HOTSHOT_FIX = ["This week's Hot Shot Debut is {who}.",
                "The Hot Shot Debut honors go to {who} this week."]
_GAINER_FIX = ["This week's Greatest Gainer is {who}.",
               "The Greatest Gainer award goes to {who} this week."]
_DROPOFF_FIX = ["Checking the board, {who} is still right there at number {rank}.",
                "Nothing dropping there — {who} holds at number {rank}."]
_NEUTRAL = ["Checking the board, nothing more to correct there.",
            "That's not what the board says — moving to the next spot.",
            "Let's keep the countdown moving."]


def _stable_hash(s):
    """hash() is salted per-process; md5 keeps template rotation stable."""
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


def _edit_distance(a, b):
    a, b = a.lower(), b.lower()
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _nearest(token, pool):
    best, bd = None, None
    for cand in pool:
        d = _edit_distance(token, cand)
        if bd is None or d < bd:
            best, bd = cand, d
    return best


# ---------------------------------------------------------------- fix helpers

def _fix_phantom_acts(text, facts, exempt):
    """Correct a Title-Case act name anchored right before a chart verb, if
    it names no real title/artist. `exempt` (lowercased words) protects the
    line's own speaker + any caller-supplied extra_ok names.

    A real catalog title can itself contain an internal Title-Case run that
    happens to land right before a chart verb ("Two Lanes, Late Merge holds
    at number five" anchors on "Late Merge holds", "The Boreal Lantern, Late
    Set holds..." anchors on "Late Set holds") because the comma breaks the
    greedy word-run the anchor regex builds from the *start* of the title.
    Without this guard the fixer "corrects" a substring of a true name into
    an unrelated one, violating the prime directive that a correct line is
    never touched. Known mention spans (title/artist matches already found
    in this exact text) are computed first and any anchor match that
    overlaps one is left alone."""
    changed = [False]
    pat = facts.get("_mention_re")
    covered = [(m.start(), m.end()) for m in pat.finditer(text)] if pat else []

    def _overlaps(s, e):
        return any(s < ce and cs < e for cs, ce in covered)

    def repl(m):
        name = m.group(1)
        low = name.lower()
        if low in facts["title_to_tid"] or low in facts["artist_to_tid"]:
            return m.group(0)
        if _overlaps(m.start(1), m.end(1)):
            return m.group(0)
        if low in exempt or any(w in exempt for w in low.split()):
            return m.group(0)
        if not facts["full_names"]:
            return m.group(0)
        changed[0] = True
        nearest = _nearest(name, facts["full_names"])
        return m.group(0).replace(name, nearest, 1)

    return _ACT_SUBJECT.sub(repl, text), changed[0]


def _who(facts, tid):
    title = facts["title_of"].get(tid, tid)
    artist = facts["artist_of"].get(tid, "")
    return f"{title} — {artist}" if artist else title


def _fix(kind, tid, facts, seed_text):
    h = _stable_hash(seed_text)
    rank = facts["rank_of"].get(tid)
    last = facts["last_of"].get(tid)

    if kind == "hotshot":
        target = facts.get("hot_shot")
        if target:
            return _HOTSHOT_FIX[h % len(_HOTSHOT_FIX)].format(who=_who(facts, target))
        return _NEUTRAL[h % len(_NEUTRAL)]
    if kind == "gainer":
        target = facts.get("gainer")
        if target:
            return _GAINER_FIX[h % len(_GAINER_FIX)].format(who=_who(facts, target))
        return _NEUTRAL[h % len(_NEUTRAL)]
    if kind == "move":
        if rank is not None and last:
            return _MOVE_FIX[h % len(_MOVE_FIX)].format(
                who=_who(facts, tid), last=last, rank=rank)
        return _NEUTRAL[h % len(_NEUTRAL)]
    if kind == "dropoff":
        if rank is not None:
            return _DROPOFF_FIX[h % len(_DROPOFF_FIX)].format(
                who=_who(facts, tid), rank=rank)
        return _NEUTRAL[h % len(_NEUTRAL)]
    # rank / hold / peak / weeks / last / debut / bullet -> grounded restatement
    if rank is not None:
        return _HOLD_FIX[h % len(_HOLD_FIX)].format(rank=rank)
    return _NEUTRAL[h % len(_NEUTRAL)]


# ---------------------------------------------------------------- the walk

def _check(text, facts, subject):
    """-> (kind, tid) | None. Checks run most-specific-first; a claim only
    fires when a concrete `subject` is bound — an unbindable claim is left
    alone (the safe default; mirrors civicguard's "feat w/o subject kept").

    Title/artist mentions are blanked out before any numeric claim is
    scanned: a title can itself contain a number ("Maintenance Ticket #12",
    "Two Lanes, Late Merge") and that number belongs to the name, not to a
    chart claim about it — blank first, normalize word-numbers second, so
    neither reading can leak into the other."""
    if not subject:
        return None
    masked = text
    pat = facts.get("_mention_re")
    if pat:
        masked = pat.sub(lambda m: " " * len(m.group()), masked)
    low = _normalize_numbers(masked)

    m = _DEBUT_NUM.search(low)
    if m:
        n = int(m.group(1))
        if not facts["debut_of"].get(subject) or facts["rank_of"].get(subject) != n:
            return "debut", subject
    elif _DEBUT_BARE.search(low):
        if not facts["debut_of"].get(subject):
            return "debut", subject

    if _HOTSHOT_CLAIM.search(low) and subject != facts["hot_shot"]:
        return "hotshot", subject

    if _GAINER_CLAIM.search(low) and subject != facts["gainer"]:
        return "gainer", subject

    m = _PEAK_CLAIM.search(low)
    if m and facts["peak_of"].get(subject) != int(m.group(1)):
        return "peak", subject

    m = _WEEKS_CLAIM.search(low) or _WEEKS_CLAIM2.search(low)
    if m and facts["weeks_of"].get(subject) != int(m.group(1)):
        return "weeks", subject

    m = _LAST_CLAIM.search(low) or _FROM_CLAIM.search(low)
    if m and facts["last_of"].get(subject) != int(m.group(1)):
        return "last", subject

    if _DROPOFF_CLAIM.search(low) and subject not in facts["droppers"]:
        return "dropoff", subject

    if _HOLD_CLAIM.search(low):
        rank = facts["rank_of"].get(subject)
        if rank is None or rank != facts["last_of"].get(subject):
            return "hold", subject

    if _BULLET_CLAIM.search(low) and not facts["bullet_of"].get(subject):
        return "bullet", subject

    if _UP_CLAIM.search(low):
        rank, last = facts["rank_of"].get(subject), facts["last_of"].get(subject)
        if facts["debut_of"].get(subject) or rank is None or not last or rank >= last:
            return "move", subject

    if _DOWN_CLAIM.search(low):
        rank, last = facts["rank_of"].get(subject), facts["last_of"].get(subject)
        if facts["debut_of"].get(subject) or rank is None or not last or rank <= last:
            return "move", subject

    for m in _RANK_CLAIM.finditer(low):
        window = low[max(0, m.start() - 20):m.start()]
        if _SKIP_WINDOW.search(window):
            continue
        if facts["rank_of"].get(subject) != int(m.group(1)):
            return "rank", subject

    return None


def enforce_chart(lines, facts, *, extra_ok=frozenset()):
    """Walk `lines` (scoreguard-shaped `{"text": ..., ...}` dicts) against
    `facts`. Violating lines are REPLACED (never cut) with a neutral/grounded
    line in the countdown register; phantom act names anchored to a chart
    claim are corrected in place. Returns a new list; input dicts are never
    mutated (the prime directive: a correct line is never touched)."""
    allow_extra = {w.lower() for w in extra_ok} | facts.get("names_ok", set())
    out = []
    last_subject = None
    for ln in lines:
        text = ln.get("text", "")
        low0 = text.lower()
        if _MODAL.search(low0):    # predictions/hypotheticals pass whole
            out.append(ln)
            continue

        speaker = (ln.get("speaker") or "").lower()
        exempt = allow_extra | {speaker} | set(speaker.split())
        fixed, changed = _fix_phantom_acts(text, facts, exempt)

        mentions = _mentions(fixed, facts)
        if mentions:
            last_subject = mentions[-1][1]
        subject = last_subject

        kind = _check(fixed, facts, subject)
        if kind:
            k, tid = kind
            new = dict(ln)
            new["text"] = _fix(k, tid, facts, text)
            new["_enforced"] = True
            out.append(new)
        elif changed:
            new = dict(ln)
            new["text"] = fixed
            new["_enforced"] = True
            out.append(new)
        else:
            out.append(ln)
    return out
