"""Serialized station arcs — a code-owned state machine with guaranteed payoffs.

Promoted (per the arcs+census design) from an LLM-only story editor into a
deterministic state machine: the model authors a frozen SKELETON ONCE at arc
birth (title/premise/register + a chain of dated escalation beats ending in a
PAYOFF), and code owns everything a listener actually experiences —
scheduling beats onto register-compatible shows/dates, advancing the stage
cursor, FORCE-AIRING the payoff inside its `payoff_on` window if a show slips,
retiring the arc, and graduating it one-way into lore on resolution.

Two clocks, exactly like the hockey/statehouse engines: a deterministic
scheduling clock (code, every air-day) and a narration clock (the LLM author,
only at arc birth). No arc fact is ever born in a show beat — a beat's `fact`
is frozen the moment the skeleton is minted, and only STAMPED with an aired
date once its show actually runs (`mark_aired`), so a summary can never outrun
the air. The payoff fact carries `aired: null` until it fires, so canonguard
can spoiler-block any line that asserts the resolution early.

State lives in `data/arcs/arcs.json` (atomic tmp+replace+.bak). Missing or
corrupt -> the empty default -> the station degrades to today's behavior.

BACKWARD COMPATIBILITY: `daily_tick`/`digest` keep their names and transparently
accept the LEGACY inline `lore_state` (arcs as a list) so nothing breaks before
the orchestrator is rewired — a legacy-shaped state runs the original once-a-day
LLM story-editor tick verbatim (gate-off is byte-identical).

Stdlib-only leaf module: writer/orchestrator/lore import this, never the reverse.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date as _Date, timedelta
from pathlib import Path

from .openrouter import chat

# ---------------------------------------------------------------- constants

MAX_ACTIVE = 2

# The escalation ladder. A skeleton need not use every rung; its beat list is
# the plan, each beat tagged with a stage, the final beat always PAYOFF.
STAGES = ("SEEDED", "RISING", "COMPLICATION", "CRISIS", "PAYOFF", "LORE")

# Arc registers. `mundane`/`civic` are town texture; `dreamcourt` is Vivian's
# Night Shift; `conspiracy` (the Watcher's, quarantined) and `sports` (Center
# Ice's own engine) exist for completeness but the routing table never places a
# town arc on those shows.
REGISTERS = ("mundane", "conspiracy", "dreamcourt", "civic", "sports")

# Register-routing table DERIVED from the show contracts in schedule.yaml — not
# new policy. The Watcher (lore_quarantine) and Dawn Patrol (ambient, sponsor:
# none) host no arcs; Center Ice runs its own live-sports machine; Night Shift
# owns the dreamcourt register. Everything else is daytime talk that carries the
# writer's anti-conspiracy REGISTER GUARD, i.e. mundane/civic only.
REGISTER_OK = {
    "morning_scramble":      {"mundane", "civic"},
    "refined_palate":        {"mundane", "civic"},
    "complaints_department": {"mundane", "civic"},
    "the_handover":          {"mundane", "civic"},
    "culture_vulture":       {"mundane", "civic"},
    "night_shift":           {"mundane", "dreamcourt"},
    "static_hour":           set(),   # lore_quarantine — points OUTWARD
    "center_ice":            set(),   # its own sports engine
    "dawn_patrol":           set(),   # ambient palate-cleanser
}

_PATH = Path("data/arcs/arcs.json")

_DEFAULT = {"schema": 1, "seq": 0, "arcs": {}, "recent_settings": []}

# code-only fallback premises (a bad/absent model reply never blocks a slot);
# each is a frozen mini-skeleton the state machine can schedule immediately.
_FALLBACK = [
    {"title": "The Roundabout That Won't", "register": "civic",
     "setting": "the Mile Zero roundabout",
     "premise": "a ribbon-cutting is announced for a roundabout that is, of course, not finished",
     "beats": [
         {"stage": "SEEDED", "directive": "a ribbon-cutting is announced for the roundabout — and they mean it this time",
          "fact": "a ribbon-cutting is set for the Mile Zero roundabout"},
         {"stage": "RISING", "directive": "the teal ribbon arrives; the roundabout does not",
          "fact": "the ribbon is teal"},
         {"stage": "PAYOFF", "directive": "PAYOFF: they cut the ribbon anyway; the roundabout is still two weeks out; everyone applauds",
          "fact": "the ribbon was cut; the roundabout remains unfinished"}]},
    {"title": "The Pharmacy-Lot Goose", "register": "mundane",
     "setting": "the pharmacy lot",
     "premise": "a goose has claimed the pharmacy parking lot and the town negotiates terms",
     "beats": [
         {"stage": "SEEDED", "directive": "a goose has claimed the pharmacy lot and will not be moved",
          "fact": "a goose has claimed the pharmacy lot"},
         {"stage": "RISING", "directive": "someone leaves the goose a folding chair; it accepts",
          "fact": "the goose has accepted a folding chair"},
         {"stage": "PAYOFF", "directive": "PAYOFF: the lot is granted to the goose in perpetuity; the sign is laminated",
          "fact": "the goose was granted the pharmacy lot in perpetuity"}]},
    {"title": "The Sock Ceasefire", "register": "mundane",
     "setting": "the half-duplex row",
     "premise": "two neighbors wage a passive-aggressive war over a shared laundry line",
     "beats": [
         {"stage": "SEEDED", "directive": "a laundry-line grievance surfaces for the first time",
          "fact": "there is a laundry-line dispute on the half-duplex row"},
         {"stage": "RISING", "directive": "a laminated note appears on the line",
          "fact": "a laminated note has appeared on the line"},
         {"stage": "PAYOFF", "directive": "PAYOFF: they split the line down the middle with tape — an accidental truce",
          "fact": "the line was split with tape; an accidental truce holds"}]},
]

_AUTHOR = """You are the story editor for The Frequency, a 24/7 comedy radio
station. Draft ONE new SERIALIZED ARC: a slow-burning, petty, G/PG-rated
storyline that develops across several days and PAYS OFF. NEVER conspiracies,
never paranormal, no real people or brands, and NEVER the office interior
(no coffee machines, printers, thermostats, breakroom appliances).

Draw the setting from the wider world: the surrounding TOWN, the natural/
seasonal world, listeners' lives, or civic absurdity. It must be tonally and
topically distinct from these recently-used settings: {avoid}.

Return STRICT JSON — a COMPLETE plan, 3-6 beats, escalating to a PAYOFF:
{{"title":"...","premise":"...","register":"mundane|civic|dreamcourt",
  "setting":"<where in the world>","cast":{{"civilians":[],"canon":[]}},
  "lifespan_days":5,
  "beats":[{{"stage":"SEEDED","directive":"<one on-air development>","fact":"<the one durable fact this beat asserts>"}},
           ...last beat's stage is PAYOFF]}}"""


# ---------------------------------------------------------------- utilities

def _stable_hash(s: str) -> int:
    """hash() is salted per-process; md5 keeps id/routing rotation stable."""
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


def _d(s: str) -> _Date:
    return _Date.fromisoformat(s)


def _iso(d: _Date) -> str:
    return d.isoformat()


def _add_days(iso: str, n: int) -> str:
    return _iso(_d(iso) + timedelta(days=n))


def _is_legacy(state: dict) -> bool:
    """A legacy inline lore_state carries arcs as a LIST (or none) and no
    schema; the new sidecar carries arcs as a DICT under a schema."""
    if "schema" in state:
        return False
    return not isinstance(state.get("arcs"), dict)


def register_ok(show_id: str) -> set:
    """Registers a given show may host (empty set => hosts no arcs)."""
    return set(REGISTER_OK.get(show_id, set()))


def shows_for_register(register: str, schedule=None) -> list:
    """Eligible show ids for a register, in a stable canonical order. If a
    `schedule` (parsed schedule.yaml dayparts) is given, restrict to shows it
    actually defines."""
    shows = [s for s, regs in REGISTER_OK.items() if register in regs]
    if schedule is not None:
        defined = {b.get("id") for b in _dayparts(schedule)}
        shows = [s for s in shows if s in defined]
    return sorted(shows)


def _dayparts(schedule) -> list:
    if isinstance(schedule, dict):
        return schedule.get("dayparts", [])
    return list(schedule or [])


# ---------------------------------------------------------------- store IO

def load(path: Path = _PATH) -> dict:
    """Live file, then .bak, then the empty default — never silently reset a
    live spine on a read race (the season._save / statehouse.save_side rule)."""
    for p in (Path(path), Path(str(path) + ".bak")):
        try:
            if p.exists():
                state = json.loads(p.read_text())
                if isinstance(state, dict) and isinstance(state.get("arcs"), dict):
                    for k, v in _DEFAULT.items():
                        state.setdefault(k, v if not isinstance(v, (dict, list))
                                         else type(v)())
                    return state
        except Exception:
            pass  # corrupt file must never take the air down
    return {"schema": 1, "seq": 0, "arcs": {}, "recent_settings": []}


def save(state: dict, path: Path = _PATH) -> None:
    """Atomic tmp+replace, keeping a .bak of the prior good file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(state, indent=2))
    if p.exists():
        try:
            Path(str(p) + ".bak").write_text(p.read_text())
        except Exception:
            pass
    tmp.replace(p)


# ---------------------------------------------------------------- arc birth

def _clean_beats(raw) -> list:
    """Validate/normalize an author's beat list -> frozen beat plans. The last
    beat is forced to stage PAYOFF; every beat carries a directive + a fact."""
    beats = []
    for b in (raw or []):
        if not isinstance(b, dict):
            continue
        directive = (b.get("directive") or b.get("line") or "").strip()
        if not directive:
            continue
        stage = b.get("stage")
        stage = stage if stage in STAGES else "RISING"
        fact = (b.get("fact") or directive).strip()
        beats.append({"stage": stage, "directive": directive, "fact": fact})
    if len(beats) < 2:
        return []
    beats[0]["stage"] = "SEEDED"
    beats[-1]["stage"] = "PAYOFF"
    return beats


def new_arc(skeleton: dict, date: str, seq: int, schedule=None, rng=None) -> dict:
    """Build a SEEDED arc dict from a frozen author skeleton. Assigns an id from
    `seq`, freezes the beat strings, pre-seeds the facts table (payoff fact
    stamped `aired: null`), and schedules the beat chain onto register-
    compatible shows/dates. Returns the arc (does not mutate any state dict)."""
    beats = _clean_beats(skeleton.get("beats"))
    if not beats:
        raise ValueError("skeleton has too few valid beats")
    register = skeleton.get("register")
    if register not in REGISTERS or not shows_for_register(register, schedule):
        register = "mundane"
    lifespan = skeleton.get("lifespan_days")
    try:
        lifespan = int(lifespan)
    except (TypeError, ValueError):
        lifespan = len(beats)
    lifespan = max(3, min(6, lifespan))

    arc_id = f"arc-{seq:04d}"
    arc = {
        "id": arc_id,
        "title": (skeleton.get("title") or "Untitled Arc").strip(),
        "premise": (skeleton.get("premise") or "").strip(),
        "setting": (skeleton.get("setting") or "").strip(),
        "register": register,
        "cast": _norm_cast(skeleton.get("cast")),
        "stage": "SEEDED",
        "stage_idx": 0,
        "opened": date,
        "payoff_on": _add_days(date, lifespan),
        "status": "active",
        "force_payoff": False,
        "graduated": False,
        "latest": "",
        "beats": [],
        "facts": [],
    }
    for i, b in enumerate(beats):
        bid = f"b{i + 1}"
        arc["beats"].append({
            "bid": bid, "stage": b["stage"], "directive": b["directive"],
            "fact": b["fact"], "due": None, "show": None,
            "status": "pending", "aired_date": None,
        })
        arc["facts"].append({
            "fid": bid, "kind": "payoff" if b["stage"] == "PAYOFF" else "beat",
            "key": bid, "value": b["fact"], "aired": None,
        })
    schedule_beats(arc, schedule, rng)
    return arc


def _norm_cast(cast) -> dict:
    if isinstance(cast, dict):
        civ = [c for c in cast.get("civilians", []) if isinstance(c, str)]
        canon = [c for c in cast.get("canon", []) if isinstance(c, str)]
        return {"civilians": civ, "canon": canon}
    if isinstance(cast, list):
        return {"civilians": [], "canon": [c for c in cast if isinstance(c, str)]}
    return {"civilians": [], "canon": []}


def schedule_beats(arc: dict, schedule=None, rng=None) -> None:
    """Place every not-yet-aired beat on a register-compatible show + date.
    Deterministic given the arc id: beats spread evenly from `opened` to
    `payoff_on` (the payoff beat lands exactly on `payoff_on`), each assigned to
    a register-compatible show rotated by the arc seed for variety. Already-aired
    beats are left untouched (a reschedule after a slip never re-airs a beat)."""
    pend = [b for b in arc["beats"] if b["status"] != "aired"]
    if not pend:
        return
    eligible = shows_for_register(arc["register"], schedule) or ["morning_scramble"]
    opened, payoff_on = arc["opened"], arc["payoff_on"]
    span = max(1, (_d(payoff_on) - _d(opened)).days)
    n = len(pend)
    seed = _stable_hash(arc["id"])
    # the earliest still-pending beat starts no earlier than today's opened date
    for i, b in enumerate(pend):
        if b is pend[-1] and b["stage"] == "PAYOFF":
            b["due"] = payoff_on
        else:
            off = 0 if n == 1 else round(i * span / n)
            b["due"] = _add_days(opened, min(off, span))
        b["show"] = eligible[(seed + i) % len(eligible)]


# ---------------------------------------------------------------- transitions

def advance(arc: dict, date: str) -> None:
    """Move the stage cursor forward over every leading beat that has aired.
    `stage` tracks the current (first not-yet-aired) beat; once the payoff beat
    airs the cursor runs off the end and `stage` becomes LORE."""
    beats = arc["beats"]
    idx = arc.get("stage_idx", 0)
    while idx < len(beats) and beats[idx]["status"] == "aired":
        idx += 1
    arc["stage_idx"] = idx
    arc["stage"] = beats[idx]["stage"] if idx < len(beats) else "LORE"


def _payoff_beat(arc: dict) -> dict | None:
    for b in reversed(arc["beats"]):
        if b["stage"] == "PAYOFF":
            return b
    return arc["beats"][-1] if arc["beats"] else None


def next_beat(arc: dict, date: str, show: str) -> dict | None:
    """The one beat THIS show may weave for THIS arc today, or None. Normal
    case: the current-stage beat, if it is pinned to `show`, is due (<= date),
    register-compatible, and unaired. A `force_payoff` arc jumps the queue — its
    payoff beat surfaces on the next register-compatible show regardless of the
    per-beat date, so a slipped arc pays off late but never skips."""
    if arc.get("status") not in ("active",):
        return None
    if arc["register"] not in register_ok(show):
        return None
    if arc.get("force_payoff"):
        pb = _payoff_beat(arc)
        if pb and pb["status"] != "aired" and _prior_aired(arc, pb):
            return pb
        return None
    idx = arc.get("stage_idx", 0)
    if idx >= len(arc["beats"]):
        return None
    b = arc["beats"][idx]
    if b["status"] != "aired" and b.get("show") == show and b.get("due") \
            and b["due"] <= date:
        return b
    return None


def surface(state: dict, show_id: str, date: str) -> dict | None:
    """Across all active arcs, the ONE {"arc","beat"} this show may carry today
    (first by arc id for determinism), or None. The orchestrator flips the
    beat's `aired` AFTER it emits (via `mark_aired`), so a crash mid-beat
    re-surfaces it rather than skipping it."""
    for aid in sorted(state.get("arcs", {})):
        arc = state["arcs"][aid]
        b = next_beat(arc, date, show_id)
        if b is not None:
            return {"arc": arc, "beat": b}
    return None


def next_beat_for_show(state: dict, date: str, show_id: str) -> dict | None:
    """The continuity desk's frozen arc-beat shape (continuity_desk contract):
    surface()'s {"arc","beat"} flattened into the prompt/guard fields. The
    desk reads these keys tolerantly; canon = the durable facts aired so far
    (this beat's own fact stays out until it airs — spoiler discipline)."""
    hit = surface(state, show_id, date)
    if hit is None:
        return None
    arc, b = hit["arc"], hit["beat"]
    cast = _norm_cast(arc.get("cast"))
    aired_facts = [x.get("fact") for x in arc.get("beats", [])
                   if x.get("status") == "aired" and x.get("fact")]
    try:
        idx = arc["beats"].index(b)
    except ValueError:
        idx = arc.get("stage_idx", 0)
    return {"arc_id": arc.get("id"), "title": arc.get("title", ""),
            "bid": b.get("bid") or f"b{idx + 1}",
            "stage": b.get("stage", ""), "day": b.get("due") or date,
            "directive": b.get("directive", ""),
            "canon": aired_facts,
            "payoff": bool(b.get("stage") == "PAYOFF" or arc.get("force_payoff")),
            "register": arc.get("register", "mundane"),
            "cast_ids": list(cast.get("civilians", [])),
            "cast_names": list(cast.get("canon", [])),
            "names": [n for n in (arc.get("names") or []) if isinstance(n, str)]}


def _prior_aired(arc: dict, beat: dict) -> bool:
    """Every beat before `beat` in the plan has aired (payoff anti-skip)."""
    for b in arc["beats"]:
        if b is beat:
            return True
        if b["status"] != "aired":
            return False
    return True


def gate_payoff(arc: dict, date: str, show: str) -> bool:
    """True only when the arc's PAYOFF beat may fire on this show/date: all
    prior stages have aired AND either (it is on/after `payoff_on` on the
    payoff beat's own show) OR the arc is in its force-air window — both require
    the show's register to accept the arc. Until this returns true the payoff
    fact stays `aired: null` and canonguard treats an early resolution as a
    pre-air spoiler."""
    pb = _payoff_beat(arc)
    if pb is None or pb["status"] == "aired":
        return False
    if arc["register"] not in register_ok(show):
        return False
    if not _prior_aired(arc, pb):
        return False
    if arc.get("force_payoff"):
        return True
    return date >= arc["payoff_on"] and pb.get("show") == show \
        and (pb.get("due") or arc["payoff_on"]) <= date


def mark_aired(arc: dict, bid: str, date: str, aired_text: str = "") -> None:
    """Freeze a beat's fact as aired canon. Flips the beat to `aired` with an
    aired_date, stamps the matching facts-table row with `date` (append-only:
    the value is never rewritten, only its aired date filled), and updates the
    arc's one-line `latest`. Idempotent for a given bid."""
    for b in arc["beats"]:
        if b["bid"] == bid:
            if b["status"] != "aired":
                b["status"] = "aired"
                b["aired_date"] = date
            for f in arc["facts"]:
                if f["key"] == bid and f["aired"] is None:
                    f["aired"] = date
            arc["latest"] = (aired_text or b["directive"]).strip()
            return


def _epitaph(arc: dict) -> str:
    pb = _payoff_beat(arc)
    if pb and pb.get("fact"):
        return pb["fact"].strip()
    return arc.get("latest") or arc.get("title", "an arc")


# ---------------------------------------------------------------- daily tick

def daily_tick(models: dict, arcs_state: dict, civ_state: dict | None = None,
               schedule=None, *, date: str | None = None,
               author_fn=None, lore_state: dict | None = None,
               rng=None) -> None:
    """The once-per-air-day story-editor pass.

    New (sidecar) state -> the deterministic state machine (see module docstring).
    Legacy (inline lore_state, arcs-as-list) -> the original LLM story-editor
    tick, verbatim, so gate-off is byte-identical.

    The state machine, in order:
      1. advance each active arc's stage over beats that aired since last tick;
      2. an arc whose PAYOFF beat aired -> graduate its epitaph one-way into lore
         (recent_callbacks), demote to `resolving`; a `resolving` arc that has
         lingered a day -> `retired` (canon kept, dropped from the digest);
      3. FORCE-AIR window: an arc past `payoff_on` whose payoff never aired is
         flagged `force_payoff` (next compatible show must surface it);
      4. reschedule preempted (still-pending, past-due) beats forward;
      5. if active arcs < MAX_ACTIVE, author ONE new arc via `author_fn`
         (LLM-drafted frozen skeleton; falls back to a code-only premise on any
         failure) in a setting absent from recent_settings.

    `author_fn(models, date, avoid_settings) -> skeleton dict` is injected for
    tests; it defaults to the real LLM author. Every fact write is stamped only
    from beats already flipped aired by the orchestrator, so it never outruns
    the air. Deterministic given (date, state); no datetime.now in the machine.
    """
    if _is_legacy(arcs_state):
        _legacy_daily_tick(models, arcs_state)
        return

    if date is None:
        date = _today()
    lore_state = lore_state if lore_state is not None else civ_state \
        if _looks_like_lore(civ_state) else None

    arcs = arcs_state.setdefault("arcs", {})

    for arc in arcs.values():
        if arc.get("status") == "retired":
            continue
        advance(arc, date)
        pb = _payoff_beat(arc)
        payoff_aired = bool(pb) and pb["status"] == "aired"

        if arc["status"] == "active" and payoff_aired:
            arc["status"] = "resolving"
            arc["stage"] = "LORE"
            arc["resolved_on"] = date
            arc["force_payoff"] = False
            if not arc.get("graduated"):
                _graduate(arc, lore_state)
        elif arc["status"] == "resolving" and arc.get("resolved_on", date) < date:
            arc["status"] = "retired"

        # force-air window: past payoff_on and the payoff never fired
        if arc["status"] == "active" and not payoff_aired \
                and date > arc["payoff_on"] and _prior_aired(arc, pb):
            arc["force_payoff"] = True

        # reschedule any still-pending, past-due beat forward onto today
        if arc["status"] == "active" and not arc.get("force_payoff"):
            _reschedule_slips(arc, date)

    # seed replacements up to MAX_ACTIVE
    active = [a for a in arcs.values() if a.get("status") == "active"]
    if len(active) < MAX_ACTIVE:
        avoid = list(arcs_state.get("recent_settings", []))[-15:]
        fn = author_fn or _default_author
        try:
            skeleton = fn(models, date, avoid)
            arcs_state["seq"] = int(arcs_state.get("seq", 0)) + 1
            arc = new_arc(skeleton, date, arcs_state["seq"], schedule, rng)
        except Exception:
            arcs_state["seq"] = int(arcs_state.get("seq", 0)) + 1
            fb = _fallback_skeleton(arcs_state["seq"], avoid)
            arc = new_arc(fb, date, arcs_state["seq"], schedule, rng)
        arcs[arc["id"]] = arc
        setting = arc.get("setting") or arc.get("title")
        if setting:
            rs = arcs_state.setdefault("recent_settings", [])
            rs.append(setting)
            arcs_state["recent_settings"] = rs[-40:]


def _reschedule_slips(arc: dict, date: str) -> None:
    """A non-payoff beat that is past due but never aired (its show was
    preempted) rolls forward to today so it surfaces on the next run — slips,
    never skips, never fires early."""
    idx = arc.get("stage_idx", 0)
    if idx >= len(arc["beats"]):
        return
    b = arc["beats"][idx]
    if b["stage"] == "PAYOFF":
        return
    if b["status"] != "aired" and b.get("due") and b["due"] < date:
        b["due"] = date


def _graduate(arc: dict, lore_state: dict | None) -> None:
    """One-way arc -> lore door: on resolution the payoff becomes an evergreen
    callback the desk may reference ad hoc. Nothing flows back."""
    arc["graduated"] = True
    epitaph = _epitaph(arc)
    if lore_state is None or not epitaph:
        return
    cb = lore_state.setdefault("recent_callbacks", [])
    if epitaph not in cb:
        cb.append(epitaph)
        lore_state["recent_callbacks"] = cb[-60:]


def _looks_like_lore(obj) -> bool:
    return isinstance(obj, dict) and (
        "recent_callbacks" in obj or "running_jokes" in obj)


def _today() -> str:
    try:
        from . import clock
        return f"{clock.air_now():%Y-%m-%d}"
    except Exception:
        return _iso(_Date.today())


def _fallback_skeleton(seq: int, avoid) -> dict:
    avoid_l = {(a or "").lower() for a in (avoid or [])}
    order = sorted(range(len(_FALLBACK)),
                   key=lambda i: (_FALLBACK[i]["setting"].lower() in avoid_l,
                                  (seq + i) % len(_FALLBACK)))
    return dict(_FALLBACK[order[0]], lifespan_days=len(_FALLBACK[order[0]]["beats"]) + 2)


def _default_author(models: dict, date: str, avoid) -> dict:
    """The real LLM author: one constrained draft -> a frozen skeleton."""
    raw = chat(models["writer"],
               [{"role": "system",
                 "content": _AUTHOR.format(avoid="; ".join(avoid) or "(none yet)")},
                {"role": "user",
                 "content": f"Today is {date}. Draft one new arc now."}])
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.split("```", 2)[1].lstrip("json").strip()
    return json.loads(txt)


# ---------------------------------------------------------------- digest

def digest(arcs_state: dict) -> str:
    """The 'ONGOING STATION STORYLINES' lines shows weave in (unchanged
    contract). Legacy list-shaped arcs render byte-identically to the original;
    the new sidecar renders active + one-day-lingering (resolving) arcs."""
    if _is_legacy(arcs_state):
        return _legacy_digest(arcs_state)
    lines = []
    for aid in sorted(arcs_state.get("arcs", {})):
        a = arcs_state["arcs"][aid]
        if a.get("status") not in ("active", "resolving"):
            continue
        latest = (a.get("latest") or "").strip()
        if not latest:
            continue
        if a.get("status") == "resolving" or a.get("stage") == "LORE":
            tag = "PAYS OFF TODAY"
        elif a.get("force_payoff"):
            tag = "PAYS OFF TODAY"
        else:
            tag = f"stage {a.get('stage', 'RISING').lower()}"
        lines.append(f"- {a['title']} ({tag}): {latest}")
    return ("ONGOING STATION STORYLINES (weave in naturally, a line or two, "
            "when it fits):\n" + "\n".join(lines)) if lines else ""


# ---------------------------------------------------------------- legacy path
# The original LLM-only story editor, preserved verbatim so a legacy inline
# lore_state (arcs as a list) behaves EXACTLY as before this rewrite — the
# gate-off byte-identical guarantee.

_LEGACY_EDITOR = """You are the story editor for The Frequency, a 24/7 comedy radio
station. You manage the station's SERIALIZED ARCS: slow-burning, petty,
G/PG-rated storylines that develop once per day across different shows and
eventually pay off. NEVER conspiracies, never paranormal, no real people or
brands.

SETTING VARIETY IS MANDATORY. Arcs must range across the station's whole
world, NOT the office. Draw from: the surrounding TOWN (a Pothole
Commissioner race, a roundabout that's forever two weeks from done, a goose
that has claimed the pharmacy parking lot), the NATURAL/SEASONAL world (an
unseasonable warm spell, a very committed local raccoon, the migration of
the lawn-chair people), LISTENERS' lives out in the world, and civic absurdity
(a bake sale that keeps escalating, a library fine dispute, a beloved statue).
AVOID the office-interior rut entirely: NO coffee machines, printers, paper
jams, thermostats, breakroom appliances, ceiling tiles, or office plants — the
station has done those to death. If an existing arc is set in the office, wind
it DOWN and start its replacement somewhere in the outside world.

Rules:
- Advance each ACTIVE arc by exactly ONE development: a small, concrete turn
  that any host could mention in one or two lines. Build toward the ending.
- An arc reaching its final day gets a satisfying, mundane payoff and status
  "done".
- If fewer than {max_active} arcs remain active, start ONE new arc (day 1,
  3-6 day lifespan) in a DIFFERENT setting from any recent arc (see variety
  above) and tonally distinct from the others.
- "latest" is the one-line summary a host would actually say on air today.

Return STRICT JSON:
{{"arcs": [{{"title": "...", "premise": "...", "day": 2, "max_days": 4,
"latest": "<today's one-line development>", "status": "active|done"}}]}}"""


def _legacy_daily_tick(models: dict, lore_state: dict) -> None:
    active = [a for a in lore_state.get("arcs", []) if a.get("status") == "active"]
    user = ("Current arcs:\n" +
            (json.dumps(active, indent=1) if active else "(none yet)") +
            "\n\nAdvance them one day. Recently used premises to avoid: " +
            "; ".join(lore_state.get("recent_premises", [])[-15:]))
    raw = chat(models["writer"],
               [{"role": "system", "content": _LEGACY_EDITOR.format(max_active=MAX_ACTIVE)},
                {"role": "user", "content": user}])
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.split("```", 2)[1].lstrip("json").strip()
    arcs = json.loads(txt).get("arcs", [])
    keep = [a for a in arcs
            if isinstance(a, dict) and a.get("title") and a.get("latest")]
    lore_state["arcs"] = [a for a in keep if a.get("status") == "active"][:MAX_ACTIVE] \
        + [a for a in keep if a.get("status") == "done"][:1]


def _legacy_digest(lore_state: dict) -> str:
    lines = []
    for a in lore_state.get("arcs", []):
        tag = "PAYS OFF TODAY" if a.get("status") == "done" else \
              f"day {a.get('day', '?')} of {a.get('max_days', '?')}"
        lines.append(f"- {a['title']} ({tag}): {a['latest']}")
    return ("ONGOING STATION STORYLINES (weave in naturally, a line or two, "
            "when it fits):\n" + "\n".join(lines)) if lines else ""
