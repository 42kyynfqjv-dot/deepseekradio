"""Nameguard — keeps Center Ice narration inside its invented league.

The scoreguard validates names only when they're anchored to an action verb
(scores/saves/penalty), leaving booth banter, storylines and the call-in show
free so invented callers and colour anecdotes read naturally. This is the
complementary guard for those free-form lines.

It walks every line for out-of-universe hockey references — real-world team
nicknames, real players past or present, real leagues, trophies and
broadcasters — and REPLACES any offending line (never cuts — a cut dangles the
partner's reply) with a safe, in-universe deflection. Collisions resolve in
favour of the fiction: any token in tonight's roster or the league's own
invented name pools is never touched, so an in-universe surname that happens to
coincide with a real one stays on the air.

The lists below are curated toward the distinctive, well-known names a model is
most likely to reach for; common-word nicknames and common surnames are omitted
to keep false positives near zero. The prompt rule is the first line of
defence; this is the backstop. Extend the sets as needed.

Stdlib-only leaf module: performers/orchestrator import this, never the reverse.
"""
from __future__ import annotations

import hashlib
import re

# --------------------------------------------------------------- denylists
# Real team NICKNAMES — only the unambiguous ones. Common English words that
# double as nicknames (kings, stars, wild, jets, ducks, sharks, blues, flames,
# panthers, rangers, devils, caps, bolts, preds, sens, avs, canes) are OMITTED:
# the fiction may name a team that way and "the three stars" is core vocabulary.
_TEAMS_1 = {
    "canadiens", "habs", "bruins", "canucks", "oilers", "flyers", "penguins",
    "blackhawks", "sabres", "senators", "predators", "hurricanes", "avalanche",
    "lightning", "islanders", "nordiques", "mooseheads",
}
# Multi-word real teams / leagues / trophies / broadcasters — matched as phrases.
_PHRASES = (
    "national hockey league", "maple leafs", "red wings", "blue jackets",
    "golden knights", "mighty ducks", "stanley cup", "hockey night in canada",
    "hart trophy", "vezina trophy", "conn smythe", "art ross", "calder trophy",
    "presidents' trophy", "presidents trophy",
)
# Bare league / media / entity tokens.
_ENTITY_1 = {
    "nhl", "khl", "ahl", "sportsnet", "bettman", "gretzky",
}
# Distinctive real PLAYER surnames (past & present). Curated to the ones a model
# reaches for — omit common-word / common-surname collisions (price, roy, moore,
# richard, anderson, evans, savard, robinson, weber, byron, dvorak, armia) that
# could be a legitimately invented caller or ref.
_PLAYERS = {
    # all-time greats
    "gretzky", "lemieux", "crosby", "ovechkin", "mcdavid", "matthews",
    "mackinnon", "draisaitl", "orr", "howe", "messier", "sakic", "lidstrom",
    "yzerman", "bourque", "jagr", "datsyuk", "malkin", "bergeron", "marchand",
    "pastrnak", "mcavoy", "kucherov", "vasilevskiy", "makar", "rantanen",
    "huberdeau", "barzal", "panarin", "shesterkin", "hellebuyck", "bobrovsky",
    "tavares", "marner", "nylander", "reinhart", "eichel", "karlsson",
    "doughty", "kopitar", "gaudreau", "tkachuk", "bedard", "celebrini",
    "michkov", "kane", "toews", "kessel", "stamkos", "hedman",
    # modern-era stars
    "suzuki", "caufield", "slafkovsky", "hutson", "demidov", "dach", "newhook",
    "guhle", "montembeault", "kotkaniemi", "galchenyuk", "xhekaj", "kovacevic",
    "pacioretty", "koivu", "kovalev", "gionta", "plekanec", "desharnais",
    "markov", "gallagher", "subban", "gorton", "hughes",
    # franchise legends
    "beliveau", "lafleur", "cournoyer", "geoffrion", "dryden", "plante",
    "harvey", "lemaire", "savard", "gainey", "robinson", "carbonneau",
    "damphousse", "recchi",
}

# Everything checked as a bounded single token, minus what the fiction owns.
_DENY_TOKENS = _TEAMS_1 | _ENTITY_1 | _PLAYERS

# Safe, in-universe replacements — trip no scoreguard/nameguard check themselves.
_SAFE = [
    "Let's keep it to our own league tonight.",
    "We'll stick to the barns we know here on Center Ice.",
    "Back to the game right in front of us.",
    "That's a story for another rink — eyes on this one.",
]


def _stable_hash(s: str) -> int:
    """hash() is salted per-process; md5 keeps template rotation stable."""
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


def _allow_set(facts, extra_ok):
    """Everything the fiction legitimately owns, lowercased: tonight's roster,
    refs, hosts, team words (all already in names_ok) plus the caller's own
    name if the line context supplied one, plus the invented name pools."""
    ok = set(facts.get("names_ok", ())) if facts else set()
    ok |= set(facts.get("team_words", ())) if facts else set()
    ok |= {w.lower() for w in extra_ok}
    return ok


def enforce_names(lines, facts=None, *, extra_ok=frozenset()):
    """Walk lines; REPLACE any line naming a real-world hockey entity with a
    safe in-universe line. Returns a new list; input dicts are never mutated.
    A hit is ignored when the token is something the fiction owns (roster, ref,
    host, team word, or invented pool name) — collisions favour the fiction."""
    allow = _allow_set(facts, extra_ok)
    out = []
    for ln in lines:
        text = ln.get("text", "")
        low = text.lower()
        hit = None
        for ph in _PHRASES:
            if re.search(r"\b" + re.escape(ph) + r"\b", low) and ph not in allow:
                hit = ph
                break
        if not hit:
            for tok in re.findall(r"[a-z][a-z'’]+", low):
                if tok in _DENY_TOKENS and tok not in allow:
                    hit = tok
                    break
        if hit:
            print(f"  !! nameguard: real-world entity {hit!r} scrubbed: {text[:60]!r}")
            new = dict(ln)
            new["text"] = _SAFE[_stable_hash(text) % len(_SAFE)]
            new["_enforced"] = True
            out.append(new)
        else:
            out.append(ln)
    return out
