"""Trade Deadline — the reveal CLOCK over an already-decided transaction log.

Gate-2's economy engine (economy.py, folded by engine.py's day loop) decides
every trade of the season AHEAD of time and persists them to
`data/league/transactions-s{n}.json` (`{"tx": [ {type,from,to,out,in,note,
day,date}, ... ]}`). This module is the broadcast layer for the ONE calendar
day those trades land on: it takes the day's already-known trades and answers
"what would a listener plausibly know right now", replaying them against a
shared wall clock so the deadline show unfolds live even though the board was
settled in code hours earlier — the same story as briefs.reveal for off-air
games, applied to transactions instead of goals.

Leaf module: stdlib only, no season/orchestrator/engine import, no fact
invented that isn't already sitting in the transaction the caller handed us.
Code decides the moves; these functions only phrase and time them.

Frozen row contract (docs/designs/town-texture-and-engines.md, Row 6):
  day_plan(transactions, date, window_secs, seed) -> dict
  reveal_at(plan, cursor) -> list           (monotonic in cursor)
  sheet(revealed, players, names) -> str     (desk-style, keys -> names)
  verify(texts, revealed, names) -> bool     (desk_verify-style guard)

The quiet day is a first-class case: a deadline with zero trades still yields
a working plan, and "the board is quiet" is a legitimate deadline show.
"""
from __future__ import annotations

import random
import re

# team-nickname words too common to key a violation on by themselves (mirrors
# briefs._TEAM_STOP) -- these are last-word nicknames of league clubs that
# double as ordinary English and would otherwise trip verify() constantly.
_TEAM_STOP = {"static", "stories", "moose", "regrets", "delays", "errors",
              "yawns", "advice", "doubt", "doubts", "concern", "charts",
              "voices", "gravel", "keys", "heats", "alerts", "handshakes",
              "opinions", "thermostats", "sirens", "umbrellas", "honkers"}


def _plook(players: dict) -> dict:
    """Normalize either the whole minted body {"players": {...}} or an already
    unwrapped {pid: {...}} map (mirrors briefs._plook / stats._lookup)."""
    if isinstance(players, dict) and isinstance(players.get("players"), dict):
        return players["players"]
    return players or {}


def _trade_key(t: dict) -> tuple:
    """A stable, content-derived sort key so a plan is reproducible byte-for-
    byte from the same transaction list regardless of dict iteration order."""
    return (str(t.get("from", "")), str(t.get("to", "")),
            tuple(t.get("out", []) or []), tuple(t.get("in", []) or []),
            str(t.get("note", "")))


def day_plan(transactions: list, date: str, window_secs: int,
             seed: str) -> dict:
    """Assign every trade on `date` a seeded reveal offset across a
    `window_secs`-second broadcast window. `transactions` is the flat tx list
    (e.g. `transactions-s{n}.json["tx"]`); only `type=="trade"` rows dated
    `date` are the deadline's content. Offsets scatter across the window
    (early trickle to late flurry) and the reveal list is sorted by offset so
    reveal_at is monotonic by construction.

    Returns {"date", "window_secs", "quiet": bool, "reveals": [{"offset",
    "trade"}, ...]}. Zero trades -> quiet plan, still valid."""
    win = max(0, int(window_secs))
    trades = [t for t in transactions
              if t.get("type") == "trade" and t.get("date") == date]
    rng = random.Random(f"deadline:{seed}:{date}")
    scored = []
    for t in sorted(trades, key=_trade_key):
        off = rng.randint(0, win - 1) if win > 0 else 0
        scored.append((off, t))
    scored.sort(key=lambda x: (x[0], _trade_key(x[1])))
    reveals = [{"offset": off, "trade": t} for off, t in scored]
    return {"date": date, "window_secs": win, "quiet": not reveals,
            "reveals": reveals}


def reveal_at(plan: dict, cursor: int) -> list:
    """The trades a listener could plausibly know at `cursor` seconds into
    the window: every reveal whose offset <= cursor, in reveal order. Because
    the plan's reveals are offset-sorted, the returned prefix only grows as
    cursor grows -- monotonic, never a trade un-revealed."""
    return [r["trade"] for r in plan.get("reveals", []) if r["offset"] <= cursor]


def sheet(revealed: list, players: dict, names: dict) -> str:
    """The authoritative TRADE DEADLINE facts block handed to the desk writer:
    every revealed move with team KEYS resolved to on-air names and player
    IDs resolved through the players sidecar. This is the only truth; verify()
    holds the read to it. The quiet board is spelled out explicitly so the
    anchor has something true to say when nothing has moved."""
    plook = _plook(players)
    names = names or {}
    ln = ["TRADE DEADLINE SHEET (authoritative — the ONLY moves that exist):"]
    if not revealed:
        ln.append("- the board is quiet: not a single trade has crossed the "
                  "wire so far.")
        return "\n".join(ln)

    def pname(pid):
        return plook.get(pid, {}).get("name", pid)

    for t in revealed:
        frm = names.get(t.get("from"), t.get("from", "?"))
        to = names.get(t.get("to"), t.get("to", "?"))
        outs = [pname(p) for p in (t.get("out") or [])]
        ins = [pname(p) for p in (t.get("in") or [])]
        out_txt = ", ".join(outs) if outs else "future considerations"
        in_txt = ", ".join(ins) if ins else "future considerations"
        note = t.get("note")
        tail = f" ({note})" if note else ""
        ln.append(f"- {frm} send {out_txt} to {to} in exchange for "
                  f"{in_txt}{tail}")
    return "\n".join(ln)


def verify(texts: list, revealed: list, names: dict) -> bool:
    """Nothing airs that isn't on the board: every league team named in the
    read must be a party to a revealed trade. One strike -> the caller falls
    back to code-built wire copy. This is the deadline analog of
    briefs.desk_verify's team-name branch; it is exactly what stops the anchor
    inventing a trade on a quiet board (no revealed teams -> any team mention
    is a violation).

    Player names are NOT checked here: the reveal carries pids, not names, and
    this signature (frozen) has no players dict to resolve them -- team
    provenance is the guard this layer can enforce honestly."""
    names = names or {}
    body = " " + " ".join(texts).lower() + " "
    allowed = set()
    for t in revealed:
        for k in (t.get("from"), t.get("to")):
            nm = names.get(k, k)
            if nm:
                allowed.add(str(nm).lower())
                allowed.add(str(nm).split()[-1].lower().strip("()"))
    for k, nm in names.items():
        if not nm:
            continue
        full = str(nm).lower()
        nick = full.split()[-1].strip("()")
        for probe in {full, nick} - _TEAM_STOP:
            if not probe:
                continue
            if re.search(rf"\b{re.escape(probe)}\b", body) and probe not in allowed:
                return False
    return True
