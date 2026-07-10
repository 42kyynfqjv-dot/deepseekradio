"""The town census — the persistent registry of Halfway's callers.

Every desk-minted caller who actually airs becomes a civilian: a durable
record of who exists and what has aired about them. The biggest continuity
win is free — a civilian's telephone VOICE is a pure function of her name
(`performers._spare_voice`, md5-stable + gender-pinned), so "Maureen"
re-enters on the identical voice on every show, on every day, forever, with
zero stored state. Gender and neighborhood are likewise re-derivable from
the name/id seed; we freeze them on air only as belt-and-braces so a guard
need not import `performers`.

The census stores identity + an append-only FACTS table (the canon a guard
protects) + a single scheduled follow-up. It never invents a fact past the
air: the soft facts (problem, outcome) are summarized from the aired tail by
the once-a-day story editor, so they cannot outrun what listeners heard.

Stdlib-only leaf module: writer/orchestrator import this, never the reverse.
"""
from __future__ import annotations

import json
import os
import random
import re
from datetime import date as _date, timedelta
from pathlib import Path

_PATH = Path("data/arcs/civilians.json")

# Halfway's residential neighborhoods — the empowerment-doc locked bank of 12,
# consistent with wending-bible civic geography (Mile Zero, the pharmacy lot,
# Exit 4 never built, the merge/zipper theme). Twelve is enough that neighbors
# cluster believably and few enough that a daily listener starts to know them.
HOODS = (
    "Old Millwater", "The Exit-4 Flats", "Roundabout North", "Pharmacy Heights",
    "Lower Sieve", "The Merge", "Zipper Row", "Mile-Zero Commons",
    "The Tarpline", "Window-4 Ward", "Cold Storage", "The Provisional Blocks",
)

# follow-up cadence — the "three weeks later" feel (§11 calibration)
_FU_MIN, _FU_MAX = 14, 28
# the desk reuses an existing resident for ~1 in 4 minted calls even with no
# scheduled follow-up due (reuse burns no fresh names and IS the census payoff)
_RETURN_PREF = 0.25
# a resident goes dormant (dropped from the promoter, name still reserved) once
# this long has passed with no pending return and no active-arc membership
_DORMANT_DAYS = 90

_DEFAULT = {"schema": 1, "residents": {}, "used_names": [], "roster_by_hood": {}}


# ------------------------------------------------------------------ IO (atomic)

def load() -> dict:
    """Live file, then .bak, then a fresh default — never silently reset a
    live spine on a read race (the season.json / statehouse discipline)."""
    for p in (_PATH, _PATH.with_suffix(".bak")):
        try:
            if p.exists():
                st = json.loads(p.read_text())
                for k, v in _DEFAULT.items():
                    st.setdefault(k, v if not isinstance(v, (dict, list))
                                  else type(v)())
                return st
        except Exception:
            continue  # corrupt file must never kill the station
    return {"schema": 1, "residents": {}, "used_names": [], "roster_by_hood": {}}


def save(state: dict) -> None:
    """Atomic tmp.<pid> + replace, keeping a .bak of the prior good file."""
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    if _PATH.exists():
        try:
            _PATH.with_suffix(".bak").write_text(_PATH.read_text())
        except Exception:
            pass
    tmp = _PATH.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(_PATH)


# ------------------------------------------------------------ derive-don't-store

def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower()) or "x"


def _derive_gender(name: str):
    """'f'/'m' from the name's given-name token, else None (ambiguous names
    get the full spare-voice pool — deterministic, never a crash)."""
    try:
        from .performers import _gender_of
        return _gender_of(name)
    except Exception:
        return None


def hood_of(cid: str) -> str:
    """A civilian's neighborhood — a pure function of their id, so it never
    drifts between appearances. Derived, frozen at mint only as insurance."""
    return HOODS[random.Random("hood:" + cid).randrange(len(HOODS))]


def voice_of(name: str) -> str:
    """Thin re-export of the derived telephone voice — the whole reason a
    returning caller sounds identical with no stored voice byte."""
    from .performers import _spare_voice
    return _spare_voice(name)


# --------------------------------------------------------------- mint & identity

def new_id(name: str, existing: dict) -> str:
    """"cv-<slug>-<n>" — never collides with an id already in `existing`."""
    base = "cv-" + _slug(name)
    n = 1
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def mint(name: str, date: str, show: str, existing: dict) -> dict:
    """An identity-only record for a newly-aired caller. Gender and hood are
    DERIVED (frozen here only so a guard need not import performers); the
    voice is never stored — `voice_of(name)` owns it. Soft facts (problem,
    outcome) are filled by the daily story-editor pass from the aired tail,
    so they can't outrun the air."""
    cid = new_id(name, existing)
    rec = {
        "id": cid,
        "name": name,
        "gender": _derive_gender(name),
        "hood": hood_of(cid),
        "problem": None,
        "status": "active",
        "first_aired": date,
        "shows": [show],
        "appearances": [{"date": date, "show": show, "outcome": None,
                         "aired": True}],
        "facts": [],
        "follow_up": None,
        "arc_ref": None,
        "register": "mundane",
    }
    return rec


def record_appearance(rec: dict, date: str, show: str, outcome: str) -> None:
    """Stamp an aired appearance (a returning follow-up caller just gets a new
    stamp on the existing record — never a fresh mint, so her voice holds)."""
    rec["appearances"].append({"date": date, "show": show,
                               "outcome": outcome, "aired": True})
    if show not in rec["shows"]:
        rec["shows"].append(show)
    if rec.get("status") == "dormant":
        rec["status"] = "active"   # a return revives, without any name reuse


def add_fact(rec: dict, kind: str, key: str, value: str,
             date: str | None) -> None:
    """Append-only canon. A fact keyed (kind,key) is a SLOT: a new value for
    an existing slot is a contradiction, never a second row. Aired canon is
    immutable; an unaired placeholder (aired=None) freezes to the aired value
    when its beat airs. `date`=None means scheduled-but-not-yet-aired."""
    for f in rec["facts"]:
        if f["kind"] == kind and f["key"] == key:
            if f["value"] == value:
                if f.get("aired") is None and date is not None:
                    f["aired"] = date          # the placeholder just aired
            elif f.get("aired") is None:
                f["value"], f["aired"] = value, date   # freeze from the air
            # else: aired canon — never rewritten
            return
    fid = f"f{len(rec['facts']) + 1}"
    rec["facts"].append({"fid": fid, "kind": kind, "key": key,
                         "value": value, "aired": date})


# ------------------------------------------------------------- follow-up channel

def _iso_add(date: str, days: int) -> str:
    return (_date.fromisoformat(date) + timedelta(days=days)).isoformat()


def schedule_follow_up(rec: dict, date: str, rng) -> None:
    """Book the "three weeks later" check-in: due 14-28d out, keyed to the
    record's home show, question templated over the running problem. Never
    stacks a second pending follow-up on top of an unconsumed one."""
    fu = rec.get("follow_up")
    if fu and not fu.get("consumed"):
        return
    due = _iso_add(date, rng.randint(_FU_MIN, _FU_MAX))
    prob = rec.get("problem")
    question = (f"how's {prob} holding?" if prob else "how've you been?")
    rec["follow_up"] = {"due": due, "show": rec["shows"][-1],
                        "question": question, "consumed": False}


def consume_follow_up(rec: dict) -> None:
    """Mark the pending follow-up spent once its beat airs, so the resident
    isn't re-summoned the next day."""
    if rec.get("follow_up"):
        rec["follow_up"]["consumed"] = True


def due_follow_ups(civ: dict, date: str, show: str) -> list[dict]:
    """Every active resident with an unconsumed follow-up due on/before `date`
    whose show pin matches (or is unset). Sorted by due date; the desk caps
    one per show per day by taking the head."""
    out = []
    for rec in civ.get("residents", {}).values():
        if rec.get("status") != "active":
            continue
        fu = rec.get("follow_up")
        if not fu or fu.get("consumed"):
            continue
        if fu["due"] > date:
            continue
        if fu.get("show") and fu["show"] != show:
            continue
        out.append(rec)
    out.sort(key=lambda r: r["follow_up"]["due"])
    return out


# ------------------------------------------------- returning-caller desk contract

def returning_pick(civ: dict, date: str, show: str, rng) -> dict | None:
    """The desk's returning-caller decision for this show. A due follow-up is
    always preferred (a booked, guaranteed check-in). Failing that, the desk
    brings back an existing resident for ~1 in 4 minted calls — reuse burns
    no fresh name and IS the payoff — else returns None (mint fresh).

    Returns a pick dict {id, name, hood, question, followup} or None. When
    `followup` is set the beat is a CHECK-IN (ask the question); otherwise it
    is a warm spontaneous return on the same identity/voice."""
    due = due_follow_ups(civ, date, show)
    if due:
        rec = due[0]
        return {"id": rec["id"], "name": rec["name"], "hood": rec["hood"],
                "question": rec["follow_up"]["question"], "followup": True}
    # spontaneous reuse — a seeded 1-in-4 preference
    if rng.random() >= _RETURN_PREF:
        return None
    pool = [r for r in civ.get("residents", {}).values()
            if r.get("status") == "active"]
    if not pool:
        return None
    rec = pool[rng.randrange(len(pool))]
    return {"id": rec["id"], "name": rec["name"], "hood": rec["hood"],
            "question": None, "followup": False}


# --------------------------------------------------------- name sustainability

def _active_names(civ: dict) -> set:
    return {r["name"].split(" from ")[0].lower()
            for r in civ.get("residents", {}).values()
            if r.get("status") == "active"}


def new_caller_name(civ: dict, rng, want: str | None = None) -> str:
    """A fresh-caller name that can NEVER collide with a resident (the collision
    that would silently merge two people into one voice). Banks minus
    `used_names` minus active-civilian names. When a gender pool runs dry,
    mint a "FirstName from the {neighborhood}" distinguisher rather than
    repeating a bare name — reuse-by-design already recycles the rest."""
    try:
        from .assignments import CALLERS_F, CALLERS_M
    except Exception:
        CALLERS_F, CALLERS_M = (), ()
    g = want or rng.choice("fm")
    bank = CALLERS_F if g == "f" else CALLERS_M
    taken = {u.lower() for u in civ.get("used_names", [])} | _active_names(civ)
    fresh = [n for n in bank if n.lower() not in taken]
    if fresh:
        return rng.choice(fresh)
    # pool exhausted: distinguish by neighborhood instead of a bare repeat
    base = rng.choice(list(bank)) if bank else "Pat"
    for hood in sorted(HOODS, key=lambda h: rng.random()):
        cand = f"{base} from {hood}"
        if cand.lower() not in {u.lower() for u in civ.get("used_names", [])}:
            return cand
    return f"{base} from {rng.choice(HOODS)}"


# ------------------------------------------------------------- pruning / dormancy

def prune(civ: dict, date: str) -> None:
    """Bound growth WITHOUT ever reusing a name. A resident with no pending
    return, no active-arc membership, and a cold trail (>90d) is demoted to
    'dormant' — dropped from the follow-up promoter and returning picks, but
    the record and its reserved name are KEPT forever (canon persists; a
    dormant civilian may still be referenced, and can revive on a new call)."""
    for rec in civ.get("residents", {}).values():
        if rec.get("status") != "active":
            continue
        fu = rec.get("follow_up")
        if (fu and not fu.get("consumed")) or rec.get("arc_ref"):
            continue
        apps = rec.get("appearances") or []
        last = apps[-1]["date"] if apps else rec.get("first_aired", date)
        if (_date.fromisoformat(date) - _date.fromisoformat(last)).days > \
                _DORMANT_DAYS:
            rec["status"] = "dormant"


# ------------------------------------------------------------ guard interface

def digest_for_guard(civ: dict, ids: list[str]) -> dict:
    """The scoped fact tables `canonguard.enforce_canon` walks — only the
    residents in scope for this beat, so a genuinely new walk-on is never
    renamed into a resident."""
    residents = civ.get("residents", {})
    names_ok, full_names, fact_by_key, aired_keys, hoods = \
        set(), set(), {}, set(), {}
    for cid in ids:
        rec = residents.get(cid)
        if not rec:
            continue
        nm = rec["name"]
        names_ok.add(nm.lower())
        names_ok.update(w.lower() for w in nm.split())
        full_names.add(nm)
        hoods[cid] = rec.get("hood")
        for f in rec.get("facts", []):
            k = (cid, f["kind"], f["key"])
            fact_by_key[k] = f["value"]
            if f.get("aired"):
                aired_keys.add(k)
    return {"names_ok": names_ok, "full_names": full_names,
            "fact_by_key": fact_by_key, "aired_keys": aired_keys,
            "hoods": hoods}
