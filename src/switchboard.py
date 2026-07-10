"""Switchboard — code-owned caller lifecycle.

Scoreguard owns the score, nameguard owns the names; the switchboard owns WHO
IS ON THE LINE. The LLM never guesses call state: every beat's prompt carries
an authoritative SWITCHBOARD line (like SCOREBOARD), and after generation this
module enforces it — once the host wraps a call, that caller's later lines are
DROPPED (they hung up); a call that overruns its budget gets the host's wrap
line INJECTED (the scoreguard injection pattern) and the overflow dropped; a
wrapped caller cannot be resurrected in a later beat without a fresh on-air
greeting. Caller lines are identified structurally (the voice-attacher's phone
flag), never by guessing at names.

Stdlib-only leaf module: orchestrator imports this, never the reverse.
"""
from __future__ import annotations

import hashlib
import re


def _stable_hash(s: str) -> int:
    """hash() is salted per-process; md5 keeps template rotation stable."""
    return int(hashlib.md5(s.encode()).hexdigest(), 16)

# host-side wrap tells: the moment one of these lands, the call is OVER
_WRAP = re.compile(
    r"thanks for (?:the|your) call|thank you for calling|appreciate the call|"
    r"we'?ll let you go|gotta let you go|take care out there|"
    r"she'?s gone|he'?s gone|line(?:'s| is) clear|off the line", re.I)
# a fresh caller being brought on air (permits a new call to start)
_GREET = re.compile(r"\byou're on\b|\bgo ahead\b|\bcaller\b.{0,30}\bline\b|"
                    r"\bline (?:one|two|three|four|\d)\b", re.I)
# a call TEASE: announcing/holding for a caller. Legit only if the caller
# actually speaks later in the same beat — otherwise it's a stall loop
# ("hold that thought, there's a call!" ... no call ... repeat next beat)
_TEASE = re.compile(r"call(?:er)? on line|got a call(?:er)?\b|"
                    r"there'?s a call\b|hold (?:that|the) thought|"
                    r"caller (?:waiting|on hold)|take this call", re.I)
_TEASE_FIX = ["Anyway — where were we.",
              "But let's stay with this a moment longer.",
              "More on that in a bit — back to it."]

DEFAULT_BUDGET = 12          # caller lines per call before code wraps it


def _caller_name(ln: dict) -> str:
    return str(ln.get("speaker", "")).strip()


def prompt_line(state: dict | None, budget: int = DEFAULT_BUDGET) -> str:
    """The authoritative call-state block for the beat prompt."""
    if state and state.get("status") == "live":
        used = state.get("lines_used", 0)
        return (f"SWITCHBOARD (authoritative): {state['name']} is ON THE LINE "
                f"({used} caller lines used, budget {budget}). Continue or "
                "wrap THIS call; when the host wraps it in his own words the "
                "caller is GONE — no further lines from or about them.")
    gone = f" {state['name']} already hung up and CANNOT return." if state and \
        state.get("name") else ""
    return ("SWITCHBOARD (authoritative): all lines CLEAR — no caller is on "
            f"the line.{gone} A NEW caller may only join if a host brings "
            "them on air ('you're on...'). NEVER announce, tease, or 'hold "
            "for' an incoming call unless that caller actually speaks in "
            "THIS beat — and announce a call AT MOST ONCE: after 'caller on "
            "line two' the very next thing is the caller, never a second "
            "'hold that thought, there's a call.'")


def enforce(lines: list[dict], state: dict | None = None,
            budget: int = DEFAULT_BUDGET, host: dict | None = None) -> tuple:
    """Walk the beat's lines against the call state. Returns (new_lines,
    new_state). Never mutates inputs. Rules:
    - a caller line (phone flag) after the host's wrap is a ghost: dropped;
    - a WRAPPED/absent caller speaking again without a fresh on-air greeting
      is dropped (no resurrections);
    - a live call exceeding `budget` caller lines gets the host wrap INJECTED
      (host dict = {speaker, voice, speed}) and the overflow dropped."""
    st = dict(state) if state else {"name": "", "status": "clear",
                                    "lines_used": 0}
    out = []
    greeted = False
    injected = False
    for ln in lines:
        text = ln.get("text", "")
        if not ln.get("phone"):
            out.append(ln)
            if _GREET.search(text):
                greeted = True
                if st["status"] != "live":
                    st = {"name": "", "status": "pending", "lines_used": 0}
            if st["status"] == "live" and (_WRAP.search(text) or re.search(
                    r"\b(?:bye|good ?night|take care),?\s+%s\b"
                    % re.escape(st["name"].split()[0] or "\x00"), text, re.I)
                    if st["name"] else _WRAP.search(text)):
                st["status"] = "wrapped"
            continue
        # a caller line
        name = _caller_name(ln)
        if st["status"] == "wrapped":
            if name.lower() == st["name"].lower() or not greeted:
                print(f"  !! switchboard: ghost caller line dropped: "
                      f"{text[:50]!r}")
                continue
            st = {"name": name, "status": "live", "lines_used": 0}  # new call
        elif st["status"] in ("clear", "pending"):
            if st["status"] == "clear" and not greeted:
                # no greeting anywhere before this? tolerate mid-scene pickup
                greeted = True
            st = {"name": name, "status": "live", "lines_used": 0}
        elif st["status"] == "live" and name.lower() != st["name"].lower():
            st = {"name": name, "status": "live", "lines_used": 0}  # handoff
        if st["lines_used"] >= budget:
            if not injected and host:
                out.append({"speaker": host.get("speaker", "Host"),
                            "voice": host.get("voice", "am_adam"),
                            "speed": host.get("speed", 1.0),
                            "text": f"Thanks for the call, "
                                    f"{st['name'].split()[0] or 'friend'} — "
                                    "we'll leave it right there.",
                            "_enforced": True})
                injected = True
                print(f"  !! switchboard: budget wrap injected for "
                      f"{st['name']!r}")
            st["status"] = "wrapped"
            continue
        st["lines_used"] += 1
        out.append(ln)
    # Announcement discipline. Two failure modes, one pass:
    # (a) the STUTTER — "caller on line two" ... "hold that thought, there's
    #     a caller" ... then the caller: a call is announced AT MOST ONCE, so
    #     within the run-up to each call only the announcement closest to the
    #     caller survives; earlier duplicates are replaced.
    # (b) the STALL — a tease after the last caller line with no caller ever
    #     arriving: replaced (the caller talks or the tease never aired).
    def _announce(ln):
        t = ln.get("text", "")
        return (not ln.get("phone") and not ln.get("_enforced")
                and (_TEASE.search(t) or _GREET.search(t)))

    last_phone = max((k for k, ln in enumerate(out) if ln.get("phone")),
                     default=-1)
    run: list = []
    for k in range(len(out)):
        if out[k].get("phone"):
            for j in run[:-1]:          # (a) dedupe: keep only the last
                new = dict(out[j])
                new["text"] = _TEASE_FIX[_stable_hash(new["text"])
                                         % len(_TEASE_FIX)]
                new["_enforced"] = True
                print(f"  !! switchboard: duplicate call announcement "
                      f"replaced: {out[j]['text'][:50]!r}")
                out[j] = new
            run = []
        elif _announce(out[k]):
            run.append(k)
    for k in run:                        # (b) trailing, undelivered
        if k > last_phone and _TEASE.search(out[k].get("text", "")):
            new = dict(out[k])
            new["text"] = _TEASE_FIX[_stable_hash(new["text"])
                                     % len(_TEASE_FIX)]
            new["_enforced"] = True
            print(f"  !! switchboard: undelivered call tease replaced: "
                  f"{out[k]['text'][:50]!r}")
            out[k] = new
    if st.get("status") == "pending":
        st = {"name": "", "status": "clear", "lines_used": 0}
    return out, st
