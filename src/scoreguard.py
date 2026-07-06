"""Scoreguard — anti-hallucination scoreboard cop for Center Ice.

The game engine rolls the facts; performers at temp 0.9 narrate them, and
they invent goals, flip leads, and hand shutouts to skaters. This walks a
beat's dialogue against the engine's authoritative board and event list:
contradicting lines are REPLACED (never cut — a cut dangles the partner's
reply), forgotten goals are INJECTED as pbp calls, and — the prime
directive — no correct line is ever falsely touched. Stdlib-only leaf
module: performers/orchestrator import this, never the reverse.
"""
from __future__ import annotations

import hashlib
import re

# ---------------------------------------------------------------- normalize

_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
          "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
          "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
          "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
          "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}
_COMPOUND = re.compile(r"\b(" + "|".join(_TENS) + r")[- ](" +
                       "|".join(list(_UNITS)[1:10]) + r")\b")
_WORDNUM = re.compile(r"\b(" + "|".join(_UNITS) + r")\b")


def _norm(text):
    """Matching shadow of a line: lowercase, number words -> digits, every
    score separator ('three to two', '3–2', '3 - 2') collapsed to '3-2'.
    to_pair marks a spelled 'N to N' — that shape is always score talk,
    where a bare digit pair sometimes isn't."""
    t = text.lower()
    t = _COMPOUND.sub(lambda m: str(_TENS[m.group(1)] + _UNITS[m.group(2)]), t)
    t = _WORDNUM.sub(lambda m: str(_UNITS[m.group(1)]), t)
    t = re.sub(r"(\d)\s*(?:to|[-–—])\s*(?:nothing|nil|zip)\b", r"\1-0", t)
    t = re.sub(r"\b(?:nothing|nil|zip)\s*(?:to|[-–—])\s*(\d)", r"0-\1", t)
    to_pair = bool(re.search(r"\d to \d", t))
    t = re.sub(r"(?<=\d)\s+to\s+(?=\d)", "-", t)
    t = re.sub(r"(?<=\d)\s*[–—]\s*(?=\d)", "-", t)
    t = re.sub(r"(?<=\d)\s+-\s+(?=\d)", "-", t)
    return t, to_pair


# ---------------------------------------------------------------- lexicons

_MODAL = re.compile(  # predictions/hypotheticals are legal banter — skip whole line
    r"next (?:week|game|time|saturday|wednesday)|gonna|will win|we'll|\bwould\b|"
    r"\bif |could'?ve|should'?ve|i bet|prediction|imagine|what if")
_GOAL_VERB = re.compile(
    r"\bscores?\b|\bscored\b|\bgoal\b|buries|puts it|nets it|finds the net|"
    r"\btips\b|snipes|lights the lamp|in the net|top shelf|five.?hole")
_BEATS_CAP = re.compile(r"beats [A-Z]")  # needs original case: 'beats Kranz'
_PAIR = re.compile(r"(?<![\d-])(\d{1,2})-(\d{1,2})(?![-\d])")
_PAIR_EXCL = re.compile(r"\d+-for-\d+|\d+-on-\d+|\b1-2 punch\b|\b1-timer\b|"
                        r"50-50|24/7")
_CONTEXT = re.compile(r"score|lead|goal|\bup |\bdown |final|board|it'?s\b|"
                      r"makes? it|that'?s|\bnow\b|even|tie")
# a bare digit pair next to one of these is a real STAT, not a score claim
# (NOT "for" — "4-2 for Montreal" is a score; "0-for-3" is handled by _PAIR_EXCL)
_STAT_CTX = re.compile(r"\bdot\b|face.?off|\bshots?\b|\bsaves?\b|\brecord\b|"
                       r"\bassists?\b|\bblocks?\b|\bhits\b|penalt|power play|"
                       r"faceoffs?|in the circle")
_PAST = re.compile(r"last (?:week|game|time)|back on|that game|saturday|"
                   r"wednesday|earlier")
_MARGIN = re.compile(  # lookarounds keep 'picked up 2 assists' out of scores
    r"(?<!picked )(?<!picks )(?<!pick )(?<!set )"
    r"\b(?:leads?|up|ahead|trails?|down|behind)(?: by | )(\d)(?![-:\d])"
    r"(?! (?:assists?|shots?|saves?|minutes?|seconds?|points?|rounds?|men\b))")
_MARGIN2 = re.compile(r"\b(\d)[- ]goal (?:lead|deficit|cushion|edge|advantage)")
_TIE_AT = re.compile(r"\b(\d) apiece\b|"
                     r"\b(?:tied|knotted|even|level|deadlocked|all square) at (\d)\b")
_TIE_BARE = re.compile(r"\b(?:tied|knotted|deadlocked|all square)\b")
_TIE_SOFT = re.compile(r"\b(?:even|level)\b")  # common words: need score context
_LTVERB = re.compile(r"\b(leads?|ahead|up|trails?|down|behind)\b")
_LEADWORDS = ("lead", "leads", "ahead", "up")
# "up the ice", "behind the net", "down low" are directions, not lead claims
_DIRECTION = re.compile(
    r"\s+(?:the\s+|in\s+|and\s+|to\s+)?(?:net|ice|boards?|goal|glass|wing|"
    r"circle|crease|zone|slot|point|middle|bench|corner|far|near|line|low|"
    r"high|front|play|puck|lane|side|end|blue|red|neutral)\b")
_ACTION = re.compile(
    r"\b(scores?|buries|nets|tips in|snipes|goal (?:by|from)|saves?|stops|"
    r"denied|robs|penalty (?:to|on)|heads to the box|whistled for)\b", re.I)
_SAVE_VERB = re.compile(r"saves?$|stops$|denied$|robs$", re.I)
_CAND = re.compile(r"\b[A-Z][a-zA-Z'’]+(?: [A-Z][a-zA-Z'’]+)?\b")
_NUMWORDS = set(_UNITS) | set(_TENS) | {"nothing", "nil", "zip", "hat"}
_STOPCAP = {"the", "a", "an", "he", "she", "it", "they", "we", "you", "i",
            "and", "but", "what", "that", "this", "these", "those", "there",
            "here", "who", "oh", "hey", "now", "then", "well", "look",
            "right", "no", "yes", "wow", "boy", "man", "folks", "big",
            "great", "nothing", "nobody", "everybody", "somebody", "his",
            "her", "their", "our", "my", "your", "not", "still"}
_FEAT_HT = re.compile(r"hat.?trick")
_FEAT_BR = re.compile(r"\bbrace\b")
_FEAT_ORD = re.compile(r"\b(first|second|third|fourth)(?: goal)? of the "
                       r"(night|game|evening|period|first|second|third)\b")
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_PP = re.compile(r"power.?play|man advantage|5 on 4|five on four|"
                 r"short.?hand|penalty kill|in the box")
_EN = re.compile(r"empty.?net|pulls? the (?:goalie|netminder)|extra attacker|"
                 r"net is empty|goalie'?s (?:out|pulled)")
_INJURY = re.compile(r"helped off|down on the ice|won'?t return|injur|"
                     r"favoring (?:his|her)|day.?to.?day|left the game")
_PLOC = re.compile(r"(?:here in|we're in|early in|midway through|late in) the "
                   r"(first|second|third)\b|\bperiod ([123])\b")
_CLOCK = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_CLOCK_CTX = re.compile(r"of the|left|to go|remaining|into the")
_OTSO = re.compile(r"(?:we're (?:in|headed to)|this is)(?: the| a| an)? "
                   r"(?:overtime|shootout)")
_PNAME = {1: "first", 2: "second", 3: "third", "OT": "overtime"}
_PWORD = {"first": 1, "second": 2, "third": 3}

# replacement texts are engineered to trip no check themselves (idempotence)
_BOARD_FIX = ["Check the board — {home} {h}, {away} {a}.",
              "Scoreboard's right there, {home} {h}, {away} {a}.",
              "Let me be precise, it's {home} {h}, {away} {a}."]
_NEUTRAL = ["Chance goes wide, no change on the board.",
            "Puck's rolling around the boards, nothing doing.",
            "Play swings back the other way."]
_INJ_GOAL = ("{scorer} puts it home at {clock} of the {pname}, "
             "{ap}and it's {home} {h}, {away} {a}.")
_INJ_PEN = "{player} heads to the box — {call} — at {clock} of the {pname}."


def _stable_hash(s):
    """hash() is salted per-process; md5 keeps template rotation stable."""
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


def _mmss(t):
    m, s = t.split(":")
    return int(m) * 60 + int(s)


def _surname(full):
    return full.split()[-1]


def _find(boards, ptr, pred):
    """First board index >= ptr satisfying pred (forgiving-forward search)."""
    for j in range(ptr, len(boards)):
        if pred(boards[j]):
            return j
    return None


def _team_hits(norm, facts):
    """Sorted [(pos, side)] for every home/away token found on the line."""
    hits = []
    for side in ("home", "away"):
        for tk in facts[side + "_tokens"]:
            hits += [(m.start(), side)
                     for m in re.finditer(r"\b%s\b" % re.escape(tk), norm)]
    return sorted(hits)


def _nearest_surname(norm, pos, facts):
    """Feat subject: the roster surname closest to the claim on the line."""
    best = None
    for sur in facts["surnames"]:
        for m in re.finditer(r"\b%s\b" % re.escape(sur), norm):
            d = abs(m.start() - pos)
            if best is None or d < best[0]:
                best = (d, sur)
    return best[1] if best else None


def _credited(text, vm, cands):
    """Save credit: the name after 'by', else the name just before the verb.
    None means an unnamed subject ('nothing stops him') — no goalie check."""
    if text[vm.end():vm.end() + 4].strip().startswith("by"):
        after = [(p, n) for n, p in cands if p > vm.end()]
        if after:
            return min(after)[1]
    before = [(p, n) for n, p in cands if p < vm.start()]
    return max(before)[1] if before else None


# city words that are also ordinary English and would false-trigger attribution
_CITY_STOP = {"new", "los", "san", "saint", "st", "bay", "long", "dry", "mild",
              "firm", "fine", "third", "second", "first", "loose", "spare",
              "broken", "the", "of", "moose", "jaw"}


def _attr_tokens(name):
    """Team tokens safe for lead/trail attribution: the nickname (last word,
    always distinctive) plus any city word >=4 chars that isn't common English."""
    words = [w.lower() for w in name.split() if w.lower() != "the"]
    toks = {words[-1]} if words else set()
    toks |= {w for w in words if len(w) >= 4 and w not in _CITY_STOP}
    return toks


def _add_name(names_ok, surnames, full):
    names_ok.add(full.lower())
    names_ok.update(w.lower() for w in full.split())
    surnames.add(_surname(full).lower())


def build_facts(game, prior_events, chunk, *, mode, pbp, allow_pairs=(),
                final=None, shots=None, period=None,
                clock_lo=None, clock_hi=None):
    """Digest engine truth into the lookup tables enforce_scoreboard walks.
    chunk=None means a frozen board (pregame/intermission/postgame)."""
    events = list(chunk["events"]) if chunk else []
    goals = [e for e in events if e.get("type") == "goal"]
    if chunk:
        boards = [tuple(chunk["board_in"])] + [tuple(g["board"]) for g in goals]
    else:
        pg = [e for e in prior_events if e.get("type") == "goal"]
        boards = [tuple(final) if final else
                  tuple(pg[-1]["board"]) if pg else (0, 0)]

    tallies, period_tallies = {}, {}
    for e in list(prior_events) + events:
        if e.get("type") != "goal":
            continue
        s = _surname(e["scorer"]).lower()
        tallies[s] = tallies.get(s, 0) + 1
        k = (s, e.get("period"))
        period_tallies[k] = period_tallies.get(k, 0) + 1

    names_ok, surnames, goalies = set(), set(), set()
    for side in ("home", "away"):
        r = game.get("rosters", {}).get(side, {})
        for n in r.get("skaters", []):
            _add_name(names_ok, surnames, n)
        if r.get("goalie"):
            _add_name(names_ok, surnames, r["goalie"])
            goalies.update({r["goalie"].lower(), _surname(r["goalie"]).lower()})
    for ref in game.get("refs", []):  # refs get names_ok but never feat credit
        names_ok.add(ref.lower())
        names_ok.update(w.lower() for w in ref.split())
        names_ok.add(" ".join(ref.split()[1:]).lower())
    names_ok.add(pbp["speaker"].lower())
    names_ok.update(w.lower() for w in pbp["speaker"].split())
    home_full = {w for w in game["home"].lower().split() if w != "the"}
    away_full = {w for w in game["away"].lower().split() if w != "the"}
    names_ok |= home_full | away_full
    # ATTRIBUTION tokens are narrower: bare common city words like "new",
    # "long", "bay" must never register a phantom team hit ("new energy... up
    # the ice" is not a lead claim). Nickname (last word) is always distinctive.
    home_tokens = _attr_tokens(game["home"])
    away_tokens = _attr_tokens(game["away"])

    def _has(evs, typ):
        return any(e.get("type") == typ for e in evs)

    return {
        "mode": mode, "boards": boards, "goals": goals, "events": events,
        "team_words": home_full | away_full,
        "pp": bool(chunk and chunk.get("pp_span")),
        "en": bool(chunk and chunk.get("en_span")),
        "chunk_penalty": _has(events, "penalty"),
        "has_penalty": _has(events, "penalty") or _has(prior_events, "penalty"),
        "has_injury": _has(events, "injury") or _has(prior_events, "injury"),
        "has_pull": _has(events, "pull"),
        "names_ok": names_ok, "surnames": surnames, "goalies": goalies,
        "tallies": tallies, "period_tallies": period_tallies,
        "home": game["home"], "away": game["away"],
        "home_tokens": home_tokens, "away_tokens": away_tokens,
        "allow_pairs": {tuple(sorted(p)) for p in allow_pairs},
        "final": tuple(final) if final else None, "period": period,
        "clock_lo": _mmss(clock_lo) if clock_lo else None,
        "clock_hi": _mmss(clock_hi) if clock_hi else None,
        "pbp": dict(pbp), "shots": tuple(shots) if shots else None,
    }


def enforce_scoreboard(lines, facts):
    """Walk the lines in order against the facts. Violating lines are
    replaced (never cut), uncalled required events are injected. Returns a
    new list; input dicts are never mutated."""
    boards, goals = facts["boards"], facts["goals"]
    out, adv_pos = [], {}   # adv_pos: goal idx -> out position that first needed it
    ptr, last_scorer = 0, None

    def advance(j):
        nonlocal ptr
        for gi in range(ptr, j):
            adv_pos.setdefault(gi, len(out))
        ptr = max(ptr, j)

    def board_ok(pred):
        j = _find(boards, ptr, pred)
        if j is not None:
            advance(j)
        return j is not None

    def check(text, norm, to_pair):  # -> "board" | "neutral" | None
        hits = _team_hits(norm, facts)
        # 3. pair claims (unordered — announcers say leader-first)
        blanked = _PAIR_EXCL.sub(lambda m: " " * len(m.group()), norm)
        for m in _PAIR.finditer(blanked):
            x, y = int(m.group(1)), int(m.group(2))
            if x > 9 or y > 9:
                continue
            if tuple(sorted((x, y))) in facts["allow_pairs"]:
                reach = any(tuple(sorted(b)) == tuple(sorted((x, y)))
                            for b in boards[ptr:])
                if not hits or (_PAST.search(norm) and not reach):
                    continue  # other-game context: legal, and never advances
            if board_ok(lambda b: tuple(sorted(b)) == tuple(sorted((x, y)))):
                continue
            # a small pair matching no board is a hallucinated score. Keep it
            # ONLY in clearly-stat context (faceoff dot, shots, record); every
            # other unmatched pair in a hockey call is replaced with the true
            # board — the prime directive is that no false score airs.
            window = blanked[max(0, m.start() - 40):m.end() + 40]
            if _STAT_CTX.search(window):
                print(f"  !! scoreguard: pair {x}-{y} kept as stat: {text[:60]!r}")
                continue
            return "board"
        # 4. margins, ties, scoreless, shutout
        for m in list(_MARGIN.finditer(norm)) + list(_MARGIN2.finditer(norm)):
            n = int(m.group(1))
            if not board_ok(lambda b: abs(b[0] - b[1]) == n):
                return "board"
        ats = list(_TIE_AT.finditer(norm))
        for m in ats:
            n = int(m.group(1) or m.group(2))
            if not board_ok(lambda b: b[0] == b[1] == n):
                return "board"
        if not ats and (_TIE_BARE.search(norm) or
                        (_TIE_SOFT.search(norm) and _CONTEXT.search(norm))):
            if not board_ok(lambda b: b[0] == b[1]):
                return "board"
        if "scoreless" in norm and not board_ok(lambda b: b == (0, 0)):
            return "board"
        if re.search(r"shut.?out", norm):
            h, a = boards[ptr]
            side = hits[0][1] if hits else None
            if not (a == 0 if side == "home" else h == 0 if side == "away"
                    else 0 in (h, a)):
                return "board"
        # 5. team attribution: sign of the pointer board must match the name
        if hits and (re.search(r"\d", norm) or _CONTEXT.search(norm)):
            for vm in _LTVERB.finditer(norm):
                if vm.group(1) in ("up", "down", "behind", "ahead") and \
                        _DIRECTION.match(norm[vm.end():]):
                    continue                     # directional, not a lead claim
                before = [s for p, s in hits if p < vm.start()]
                if not before:
                    continue
                h, a = boards[ptr]
                diff = h - a if before[-1] == "home" else a - h
                lead = vm.group(1) in _LEADWORDS
                if (diff <= 0) if lead else (diff >= 0):
                    return "board"
        # 6. entities — verb-anchored only, so banter names are never scanned
        for vm in _ACTION.finditer(text):
            lo, hi = max(0, vm.start() - 50), vm.end() + 50
            cands = []
            for cm in _CAND.finditer(text[lo:hi]):
                words = [w for w in cm.group().split()
                         if w.lower() not in _STOPCAP
                         and w.lower() not in _NUMWORDS
                         and w.lower() not in facts["team_words"]]
                if words:
                    cands.append((" ".join(words).lower(), lo + cm.start()))
            for name, _ in cands:
                if name not in facts["names_ok"] and \
                        name.split()[-1] not in facts["names_ok"]:
                    return "neutral"
            if _SAVE_VERB.match(vm.group(1).split()[0]):
                cred = _credited(text, vm, cands)
                if cred and cred not in facts["goalies"] and \
                        cred.split()[-1] not in facts["goalies"]:
                    return "neutral"
        # 7. feats vs actual tallies through end of beat
        feats = [(m.start(), 3, "game", True) for m in _FEAT_HT.finditer(norm)]
        feats += [(m.start(), 2, "game", False) for m in _FEAT_BR.finditer(norm)]
        for m in _FEAT_ORD.finditer(norm):
            scope = m.group(2)
            if scope in ("night", "game", "evening"):
                feats.append((m.start(), _ORD[m.group(1)], "game", False))
            else:
                p = facts["period"] if scope == "period" else _PWORD[scope]
                if p is not None:
                    feats.append((m.start(), _ORD[m.group(1)], ("period", p), False))
        for pos, n, scope, at_least in feats:
            subj = _nearest_surname(norm, pos, facts) or last_scorer
            if subj is None:
                print(f"  !! scoreguard: feat w/o subject kept: {text[:60]!r}")
                continue
            have = (facts["tallies"].get(subj, 0) if scope == "game"
                    else facts["period_tallies"].get((subj, scope[1]), 0))
            if (have < n) if at_least else (have != n):
                return "neutral"
        # 8. state claims need a matching engine flag or logged event
        if _PP.search(norm) and not (facts["pp"] or facts["chunk_penalty"]) \
                and not (_PAST.search(norm) and facts["has_penalty"]):
            return "neutral"
        if _EN.search(norm) and not (facts["en"] or facts["has_pull"]):
            return "neutral"
        if _INJURY.search(norm) and not facts["has_injury"]:
            return "neutral"
        # 9. locators (disabled for pregame/intermission/postgame)
        if facts["period"] is not None:
            for m in _PLOC.finditer(norm):
                named = _PWORD.get(m.group(1)) or int(m.group(2) or 0)
                if named != facts["period"]:
                    return "neutral"
            lo, hi = facts["clock_lo"], facts["clock_hi"]
            if lo is not None and hi is not None:
                for m in _CLOCK.finditer(norm):
                    w0 = max(0, m.start() - 25)
                    win = norm[w0:m.end() + 25]
                    marks = [(min(abs(w0 + c.start() - m.start()),
                                  abs(w0 + c.start() - m.end())), c.group())
                             for c in _CLOCK_CTX.finditer(win)]
                    if not marks:
                        continue
                    t = int(m.group(1)) * 60 + int(m.group(2))
                    rem = min(marks)[1] in ("left", "to go", "remaining")
                    if not lo <= (1200 - t if rem else t) <= hi:
                        return "neutral"
            if _OTSO.search(norm) and facts["period"] not in ("OT", "SO"):
                return "neutral"
        return None

    for ln in lines:
        text = ln.get("text", "")
        norm, to_pair = _norm(text)
        if _MODAL.search(norm):     # 1. predictions/hypotheticals pass whole
            out.append(ln)
            continue
        if _GOAL_VERB.search(norm) or _BEATS_CAP.search(text):  # 2. goal call?
            for gi in range(ptr, len(goals)):
                toks = [w for w in goals[gi]["scorer"].lower().split() if len(w) > 2]
                if any(re.search(r"\b%s\b" % re.escape(w), norm) for w in toks):
                    advance(gi + 1)
                    last_scorer = _surname(goals[gi]["scorer"]).lower()
                    break
        kind = check(text, norm, to_pair)
        if kind:
            tpl = _BOARD_FIX if kind == "board" else _NEUTRAL
            h, a = boards[ptr]
            new = dict(ln)
            new["text"] = tpl[_stable_hash(text) % len(tpl)].format(
                home=facts["home"], away=facts["away"], h=h, a=a)
            new["_enforced"] = True
            out.append(new)
        else:
            out.append(ln)

    # 11. required-event audit — postgame already aired, nothing to enforce
    if facts["mode"] != "postgame":
        low = [o.get("text", "").lower() for o in out]

        def seen(pat):
            return any(re.search(pat, t) for t in low)

        inj = []
        for gi, g in enumerate(goals):
            toks = [w for w in g["scorer"].lower().split() if len(w) > 2]
            if any(seen(r"\b%s\b" % re.escape(w)) for w in toks):
                continue
            h, a = g["board"]
            inj.append((adv_pos.get(gi, len(out)), _INJ_GOAL.format(
                scorer=g["scorer"], clock=g["clock"],
                pname=_PNAME.get(g["period"], "period"),
                ap=f"from {g['assist']}, " if g.get("assist") else "",
                home=facts["home"], away=facts["away"], h=h, a=a)))
        for e in facts["events"]:
            if e.get("type") != "penalty":
                continue
            if seen(r"\b%s\b" % re.escape(_surname(e["player"]).lower())) or \
                    seen(re.escape(e["call"].lower())):
                continue
            inj.append((len(out), _INJ_PEN.format(
                player=e["player"], call=e["call"], clock=e["clock"],
                pname=_PNAME.get(e["period"], "period"))))
        pbp = facts["pbp"]
        for k, (pos, txt) in enumerate(sorted(inj, key=lambda x: x[0])):
            out.insert(pos + k, {"speaker": pbp["speaker"], "voice": pbp["voice"],
                                 "speed": pbp["speed"], "text": txt,
                                 "_enforced": True})
    return out
