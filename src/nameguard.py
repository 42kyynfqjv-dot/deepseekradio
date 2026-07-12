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


# ------------------------------------------------------------- news guard
# Real-world COMPANIES and brands (the discount-grocer incident): the news
# desk twists real headlines sideways, and a twisted story that still NAMES
# the company is legal exposure, not a joke. Same curation philosophy as the
# hockey lists — distinctive names only; common words that double as brands
# (apple, target, shell, subway, delta, visa, ford, sprint, marvel, gap,
# oracle, meta) are OMITTED so the fiction keeps its vocabulary. The prompt
# rule anonymizes to a role; this is the backstop.
_BRANDS_1 = {
    "aldi", "aldi's", "aldis", "walmart", "costco", "kroger", "walgreens",
    "safeway",
    "mcdonald's", "mcdonalds", "starbucks", "chipotle", "wendy's", "wendys",
    "dunkin", "coca-cola", "pepsi", "nestle", "nike", "adidas", "ikea",
    "lego", "netflix", "spotify", "tiktok", "instagram", "facebook",
    "youtube", "google", "amazon", "microsoft", "openai", "iphone",
    "android", "samsung", "sony", "nintendo", "tesla", "toyota", "honda",
    "hyundai", "boeing", "airbus", "pfizer", "moderna", "fedex", "airbnb",
    "uber", "lyft", "doordash", "disney", "pixar", "verizon", "comcast",
    "t-mobile", "at&t", "exxon", "chevron", "walgreen's",
}
_BRAND_PHRASES = ("taco bell", "burger king", "home depot", "general motors",
                  "trader joe's", "dollar general", "whole foods")

# Real PEOPLE — the names a model reaches for in conspiracies, gossip, and
# riffs. Same curation: distinctive tokens only; common words and common
# names (swift, gates, drake, jones, harris, vance, adele) appear only
# inside unambiguous phrases. The station's universe has its own famous
# people; the real ones never ride along.
_PEOPLE_1 = {
    "musk", "elon", "bezos", "zuckerberg", "oprah", "beyonce", "beyoncé",
    "rihanna", "kanye", "kardashian", "lebron", "messi", "ronaldo",
    "ohtani", "trump", "biden", "obama", "putin", "zelensky", "netanyahu",
    "macron", "trudeau", "epstein", "soros", "rothschild", "rothschilds",
    "kissinger", "altman", "desantis", "kamala", "markle", "eminem",
    "timberlake", "bieber", "mrbeast", "pewdiepie", "rogan", "scorsese",
    "spielberg", "tarantino", "kardashians", "hanks", "keanu", "zendaya",
}
_PEOPLE_PHRASES = ("taylor swift", "bill gates", "lady gaga", "pope francis",
                   "pope leo", "king charles", "prince harry",
                   "tucker carlson", "alex jones", "joe rogan",
                   "warren buffett", "steve jobs")

_WORLD_TOKENS = _BRANDS_1 | _PEOPLE_1
_WORLD_PHRASES = _BRAND_PHRASES + _PEOPLE_PHRASES

# On-air deflections for any show (PG, register-neutral, trip nothing)
_WORLD_SAFE = [
    "We don't do real names on this frequency. The pattern is what matters.",
    "No names. Names are how they find you.",
    "Let's keep the outside world outside. Where were we.",
    "This town has enough characters of its own. Back to it.",
]

_NEWS_SAFE = [
    "In local news: the bridge is still humming in D. Officials call that normal.",
    "Closer to home, the pothole on Fifth has been upgraded to a landmark.",
    "And the crosswalk button at Fifth and Pine remains, officials insist, a real button.",
    "Elsewhere: a Halfway resident reports her mailbox is fine. Developing.",
]


def enforce_world(lines, *, extra_ok=frozenset(), style="show"):
    """The station-wide real-world entity cop: any line naming a real
    company, brand, or famous person is REPLACED (never cut) — a local news
    brief in the bulletin, an in-character deflection anywhere else. Word-
    boundary matches on curated distinctive names, so 'googled it' never
    trips on 'google' and the fiction keeps its words. `extra_ok` lets the
    fiction keep a colliding name it legitimately owns (collisions always
    favour the fiction, same rule as the hockey lists)."""
    allow = {w.lower() for w in extra_ok}
    pool = _NEWS_SAFE if style == "news" else _WORLD_SAFE
    out = []
    for ln in lines:
        text = ln.get("text", "")
        low = text.lower()
        hit = None
        for ph in _WORLD_PHRASES:
            if ph not in allow and re.search(
                    r"\b" + re.escape(ph) + r"\b", low):
                hit = ph
                break
        if not hit:
            for tok in re.findall(r"[a-z][a-z&'’.-]*[a-z']", low):
                if tok in _WORLD_TOKENS and tok not in allow:
                    hit = tok
                    break
        if hit:
            print(f"  !! nameguard(world): real entity {hit!r} scrubbed: "
                  f"{text[:60]!r}")
            new = dict(ln)
            new["text"] = pool[_stable_hash(text) % len(pool)]
            new["_enforced"] = True
            out.append(new)
        else:
            out.append(ln)
    return out


def enforce_news(lines):
    """The bulletin's entity cop — brands AND people, news-brief flavored."""
    return enforce_world(lines, style="news")


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
