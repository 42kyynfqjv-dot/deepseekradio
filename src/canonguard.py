"""Canonguard — the scope-gated facts-table cop for arcs + the town census.

`civicguard.py`-mirrored (`src/statehouse/civicguard.py`, itself scoreguard-
mirrored): the arc/civilian records own the canon; performers narrate it at
temp 0.9 and will move a resident to the wrong neighborhood, rename the
adopted roundabout fern, contradict a settled outcome, leak a conspiracy
register into a mundane arc, or spoil a payoff before its beat airs. This
walks a beat's dialogue against the in-scope fact tables and REPLACES a
contradicting line (never cuts — a cut dangles the partner's reply) with an
in-register neutral, and — the prime directive — never falsely touches a
correct line.

The one thing this guard adds over its siblings is **scope-gating**. General
call-in mints a fresh name every hour; scrubbing every unknown name would be
catastrophic. So `build_canon_facts` is handed the *specific* arc/civilian
ids the desk flagged for this beat (`scope="arc"`/`"followup"`); everywhere
else `scope="none"` and `enforce_canon` is a proven byte-identical
pass-through. Stdlib-only leaf module: performers/orchestrator import this,
never the reverse; it imports no sibling engine (it only agrees with the
frozen §2 record shapes of `arcs.json`/`civilians.json`).

Catches (mirror continuity §5):
  1. phantom in-scope civilian name -> nearest scoped real name (edit-distance,
     near-miss only, so a genuinely new walk-on is never renamed)
  2. contradicted canon fact        -> in-register neutral ("not how X tells it")
  3. neighborhood/geography flip     -> neutral (keep folks in the right hood)
  4. register violation (woo/consp.) -> neutral in the correct register
  5. pre-air spoiler (aired: null)   -> "nothing's been decided on that yet"

Schema-friction notes (frozen contract, conformed to as given):
  - `HOODS` is restated here (leaf modules restate shared vocabulary rather
    than cross-import `census.py`, exactly as civicguard restates STAGE_WORDS)
    so the geography catch agrees with the census's own hood enum. A resident's
    stored `hood` (belt-and-braces per continuity §2, derivable but frozen on
    air) is treated as a normal `place/hood` fact so it flows the same walk.
  - Contradiction detection is **keyed value-phrase matching around the subject
    mention** (continuity §5, catch 2): enumerable value kinds (hood, up/down
    relationships) use mutually-exclusive VALUE FAMILIES; `name` facts use a
    naming-context capture; `quantity` facts reuse a number-adjacent-to-key
    match (the "tally-pair machinery" analogue). Open-ended kinds (free-text
    outcomes) are protected by the aired-stamp spoiler catch, not by guessing a
    contradiction — the prime directive forbids touching a line we can't prove
    wrong.
  - The pre-air spoiler catch fires only on a `aired: null` fact asserted as
    *settled* (a resolution marker present) with real content-token overlap;
    a legal beat that merely advances the story toward its payoff carries no
    settled marker and passes whole. Modal/hypothetical lines pass first, so a
    host may always speculate ("the town might finally adopt it").
"""
from __future__ import annotations

import hashlib
import re

# ---------------------------------------------------------------- canon vocab

# Restated from census.py's HOODS (see friction note) — the geography catch's
# mutually-exclusive neighborhood family. Halfway/wending-bible flavored.
HOODS = (
    "the pharmacy-lot blocks", "the Mile Zero fringe", "the Sieve side",
    "Window-4 row", "the U-Haul lot", "half-duplex row",
    "the roundabout blocks", "the old cannery row",
)
_HOODS_LC = frozenset(h.lower() for h in HOODS)

# mutually-exclusive value families for the contradiction catch (catch 2/3):
# a fact whose value is in a family conflicts with any *other* member asserted
# on the line while the canon value itself is absent.
_FAMILIES = (
    frozenset({"upstairs", "downstairs", "next door", "across the hall",
               "down the hall", "down the block"}),
)

_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
          "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
          "eleven": 11, "twelve": 12}
_NUMWORD_RE = "|".join(_UNITS)

# conspiracy/woo lexicon — banned when the in-scope arc's register is anything
# grounded (mundane/civic/sports/dreamcourt); the writer's prompt-level ban
# slips at temp 0.9, so this backstops it at the line level (catch 4).
_CONSPIRACY_WORDS = (
    "conspiracy", "cover-up", "coverup", "deep state", "chemtrail",
    "false flag", "lizard people", "new world order", "illuminati",
    "they don't want you to know", "psyop", "crisis actor", "microchip",
    "mind control", "the government is hiding", "government cover",
    "faked the", "controlled by", "wake up sheeple",
)

# resolution markers — a settled outcome (catch 5 only fires when one is present)
_SETTLED = re.compile(
    r"\b(?:voted|votes|decided|decides|official|officially|adopted|adopts|"
    r"finalized|finalised|resolved|ruled|settled|the verdict|it'?s decided|"
    r"made it official|done deal|wraps up|won the|it'?s a wrap)\b")

_MODAL = re.compile(  # predictions/hypotheticals pass whole (mirror scoreguard)
    r"next (?:week|show|time|month)|gonna|will (?:be|vote|adopt|win|finally)|"
    r"\bwould\b|\bif |could'?ve|should'?ve|might(?: finally)?|maybe|i bet|"
    r"prediction|imagine|what if|one day|someday|hopefully|planning to")

_NAMING = re.compile(
    r"\b(?:named|renamed|christened|dubbed|goes by|going by|call it|"
    r"calling it|call her|call him|call the)\b[^.,;]{0,24}?\b([A-Z][a-z]{2,})\b")

# name-role anchors for the phantom-name rename (catch 1) — tight, so ordinary
# capitalized words are never scanned.
_POSSESSIVE = re.compile(r"\b([A-Z][a-z]{2,})'s\b")
_ADDRESS = re.compile(
    r"\b(?:caller|resident|our friend|welcome back,?|back with us,?|"
    r"here'?s|hey|hi|hello)\s+([A-Z][a-z]{2,})\b")
_RENAME_MAX = 2  # only rename a near-miss (a phantom spelling of a known name)

_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "by",
         "for", "with", "her", "his", "its", "their", "our", "town", "that",
         "this", "make", "makes", "made", "into", "over", "now", "it", "is",
         "was", "be", "as", "up", "out", "off", "new", "one", "still"}

# ---------------------------------------------------------------- templates
# in-register neutral banks; register falls back to "mundane". Each is written
# to trip no catch itself (idempotence): no names not in canon, no numbers,
# no register lexicon, no settled markers.

_CONTRA = {
    "mundane": ["That's not how {name} tells it — let's not put words in anyone's mouth.",
                "Careful now — that's not the story {name} gave us.",
                "Let's keep {name}'s story straight; that isn't how it went."],
    "dreamcourt": ["The docket says otherwise — let's honor what {name} actually brought us.",
                   "That's not the case {name} laid before the court.",
                   "We hold to {name}'s own account here."],
    "civic": ["The record doesn't read that way for {name}.",
              "That's not what's on file for {name}.",
              "Let's stick to {name}'s account as it stands."],
}
_GEO = {
    "mundane": ["That's not {name}'s corner of Halfway — let's not move folks around.",
                "{name} hasn't moved neighborhoods on us.",
                "Let's keep {name} in the right part of town."],
}
_SPOILER = {
    "mundane": ["Nothing's been decided on that yet.",
                "That story hasn't landed yet — let's not get ahead of it.",
                "No word on how that one turns out just yet."],
    "dreamcourt": ["The court hasn't ruled on that yet.",
                   "No verdict's been handed down there yet.",
                   "That case is still open — no ruling to read."],
    "civic": ["Nothing official on that yet.",
              "No decision's been announced there just yet.",
              "That's still pending — no result to give."],
}
_REGISTER = {
    "mundane": ["Let's keep it grounded — that's not this street's kind of story.",
                "We'll steer clear of that flavor here; back to the real block.",
                "That's not the register for this one — both feet on the pavement."],
}


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
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _nearest(token, pool):
    best, bd = None, None
    for cand in pool:
        d = _edit_distance(token, cand)
        if bd is None or d < bd:
            best, bd = cand, d
    return best, (bd if bd is not None else 1 << 30)


def _has_word(low, phrase):
    """Word/phrase presence with no-adjacent-letter boundaries (handles the
    multi-word hood/relationship values as well as single tokens)."""
    return re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])",
                     low) is not None


def _to_int(tok):
    tok = tok.lower()
    if tok.isdigit():
        return int(tok)
    return _UNITS.get(tok)


def _family_of(value_lc):
    if value_lc in _HOODS_LC:
        return _HOODS_LC
    for fam in _FAMILIES:
        if value_lc in fam:
            return fam
    return None


def _content_tokens(value):
    return [w for w in re.findall(r"[a-z]{3,}", value.lower()) if w not in _STOP]


def _banned_words(register):
    if register in (None, "conspiracy"):
        return ()
    return _CONSPIRACY_WORDS


# ---------------------------------------------------------------- build

def _split_facts(facts, sid):
    """-> (aired, pending): lists of (kind, key, value). A fact with a truthy
    `aired` date is settled canon (contradiction surface); `aired: null` is a
    scheduled-but-unaired fact (the spoiler tripwire)."""
    aired, pending = [], []
    for f in facts or ():
        rec = (f.get("kind"), f.get("key"), f.get("value"))
        (aired if f.get("aired") else pending).append(rec)
    return aired, pending


def _add_name(names_ok, full_names, name, surname=None):
    if name:
        names_ok.add(name.lower())
        full_names.add(name)
    if surname:
        names_ok.add(surname.lower())


def _title_tokens(title):
    return {w.lower() for w in re.findall(r"[A-Za-z]{4,}", title or "")
            if w.lower() not in _STOP}


def build_canon_facts(arcs_state, civ_state, *, scope_ids=(), scope="none"):
    """Digest the arcs/civilians **in scope for this beat** into the lookup
    tables `enforce_canon` walks. `arcs_state`/`civ_state` are the frozen §2
    `arcs.json`/`civilians.json` dicts; `scope_ids` are the arc/civilian ids
    the desk flagged; `scope` ∈ {"arc","followup","none"}. `scope="none"`
    yields a table `enforce_canon` treats as a pure pass-through — the fresh
    call-in guarantee (continuity §5, risk 1)."""
    arcs = (arcs_state or {}).get("arcs", {})
    residents = (civ_state or {}).get("residents", {})
    subjects = {}
    names_ok, full_names = set(), set()
    register = None

    for sid in scope_ids or ():
        if sid in residents:
            rec = residents[sid]
            disp = rec.get("name") or sid
            reg = rec.get("register") or "mundane"
            aired, pending = _split_facts(rec.get("facts", []), sid)
            hood = rec.get("hood")
            if hood:
                aired.append(("place", "hood", hood))
            toks = set()
            for part in (rec.get("name"), rec.get("surname")):
                if part and len(part) >= 3:
                    toks.add(part.lower())
            _add_name(names_ok, full_names, rec.get("name"), rec.get("surname"))
            subjects[sid] = {"display": disp, "tokens": toks, "register": reg,
                             "aired": aired, "pending": pending, "hood": hood}
        elif sid in arcs:
            arc = arcs[sid]
            disp = arc.get("title") or sid
            reg = arc.get("register") or "mundane"
            register = register or reg
            aired, pending = _split_facts(arc.get("facts", []), sid)
            toks = _title_tokens(arc.get("title", ""))
            cast = arc.get("cast", {})
            for cid in cast.get("civilians", []) or ():
                if cid in residents:
                    nm = residents[cid].get("name")
                    _add_name(names_ok, full_names, nm,
                              residents[cid].get("surname"))
                    if nm:
                        toks.add(nm.lower())
            for canon in cast.get("canon", []) or ():
                names_ok.add(canon.lower())
                for w in canon.split():
                    if len(w) >= 3 and w.lower() not in _STOP:
                        toks.add(w.lower())
                if " " in canon:
                    full_names.add(canon)
            for kind, key, val in aired + pending:
                if kind == "name" and isinstance(val, str):
                    toks.add(val.lower())
                    full_names.add(val)
                    names_ok.add(val.lower())
            subjects[sid] = {"display": disp, "tokens": toks, "register": reg,
                             "aired": aired, "pending": pending, "hood": None}

    if register is None:
        for s in subjects.values():
            register = s["register"]
            break

    return {"scope": scope, "names_ok": names_ok, "full_names": full_names,
            "subjects": subjects, "register": register,
            "banned_register_words": _banned_words(register)}


# ---------------------------------------------------------------- catches

def _mentions(low, tokens):
    return any(len(t) >= 3 and _has_word(low, t) for t in tokens)


def _contradiction(low, text, subj):
    """-> "contradiction" | "geography" | None for the subject's aired facts."""
    for kind, key, value in subj["aired"]:
        if isinstance(value, str):
            v = value.lower()
            fam = _family_of(v)
            if fam and not _has_word(low, v):
                for alt in fam:
                    if alt != v and _has_word(low, alt):
                        return "geography" if key == "hood" else "contradiction"
            if kind == "name":
                m = _NAMING.search(text)
                if m and m.group(1).lower() != v and \
                        m.group(1).lower() not in {x.lower() for x in ()} and \
                        not _has_word(low, v):
                    return "contradiction"
        if kind == "quantity":
            canon_n = _to_int(str(value))
            if canon_n is None:
                continue
            pat = r"\b(\d+|" + _NUMWORD_RE + r")\s+" + re.escape(str(key)) + r"\b"
            for m in re.finditer(pat, low):
                n = _to_int(m.group(1))
                if n is not None and n != canon_n:
                    return "contradiction"
    return None


def _spoiler(low, subj):
    """A `aired: null` fact asserted as settled (marker present + real content
    overlap) is a pre-air spoiler."""
    if not _SETTLED.search(low):
        return False
    for kind, key, value in subj["pending"]:
        if not isinstance(value, str):
            continue
        toks = _content_tokens(value)
        if not toks:
            continue
        hit = sum(1 for t in toks if _has_word(low, t))
        if hit >= min(2, len(toks)):
            return True
    return False


def _fix_phantom_names(text, facts):
    """Rename a phantom near-miss of an in-scope name to the real name. Only a
    small-edit-distance miss is touched, so a genuinely new walk-on (far from
    every scoped name) is never renamed into a resident (continuity risk 1)."""
    if not facts["full_names"]:
        return text, False
    changed = [False]

    def repl(m):
        tok = m.group(1)
        if tok.lower() in facts["names_ok"]:
            return m.group(0)
        best, dist = _nearest(tok, facts["full_names"])
        if best is not None and 0 < dist <= _RENAME_MAX:
            changed[0] = True
            return m.group(0)[:m.start(1) - m.start(0)] + best + \
                m.group(0)[m.end(1) - m.start(0):]
        return m.group(0)

    for pat in (_POSSESSIVE, _ADDRESS):
        text = pat.sub(repl, text)
    return text, changed[0]


def _classify(text, low, facts):
    """-> (category, display_name, register) | None."""
    for subj in facts["subjects"].values():
        if not _mentions(low, subj["tokens"]):
            continue
        if _spoiler(low, subj):
            return "spoiler", subj["display"], subj["register"]
        cat = _contradiction(low, text, subj)
        if cat:
            return cat, subj["display"], subj["register"]
    banned = facts["banned_register_words"]
    if banned:
        for w in banned:
            if w in low:
                return "register", None, facts["register"]
    return None


_BANKS = {"contradiction": _CONTRA, "geography": _GEO,
          "spoiler": _SPOILER, "register": _REGISTER}


def _template(cat, register, text, name):
    banks = _BANKS[cat]
    bank = banks.get(register) or banks["mundane"]
    return bank[_stable_hash(text) % len(bank)].format(name=name or "our caller")


def enforce_canon(lines, facts):
    """Walk `lines` (scoreguard-shaped `{"text": ...}` dicts) against `facts`.
    When `scope == "none"` this is a byte-identical pass-through. In scope,
    a contradicting/spoiling/register-leaking line is REPLACED (never cut) with
    an in-register neutral and a phantom near-name is corrected in place;
    `_enforced` is stamped. Returns a new list; input dicts are never mutated
    (the prime directive: a correct line is never touched)."""
    if facts.get("scope", "none") == "none":
        return list(lines)

    out = []
    for ln in lines:
        text = ln.get("text", "")
        low = text.lower()
        if _MODAL.search(low):     # predictions/hypotheticals pass whole
            out.append(ln)
            continue

        fixed, changed = _fix_phantom_names(text, facts)
        kind = _classify(fixed, fixed.lower(), facts)
        if kind:
            cat, name, register = kind
            new = dict(ln)
            new["text"] = _template(cat, register, text, name)
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


# task/final.md Row A names the entry point `enforce`; continuity §3 names it
# `enforce_canon`. Expose both so either caller binds.
enforce = enforce_canon
