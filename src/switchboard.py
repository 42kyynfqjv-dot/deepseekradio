"""Switchboard — code-owned caller lifecycle.

Scoreguard owns the score, nameguard owns the names; the switchboard owns WHO
IS ON THE LINE. The LLM never guesses call state: every beat's prompt carries
an authoritative SWITCHBOARD line (like SCOREBOARD), and after generation this
module enforces it. Caller lines are identified structurally (the voice-
attacher's phone flag), never by guessing at names.

PRIME RULE — repair toward two-sided coherence, never amputate one side.
The LLM writes calls as coherent two-voice dialogue; dropping only the
caller's lines while airing the host's replies manufactures one-sided phone
theater (the Eugene incident: minutes of the host counseling dead air).
So enforcement works like this:

- A host wrap-tell only ENDS the call if the caller is silent for the rest
  of the beat (full lookahead) — "take care, Eugene" mid-conversation is a
  pleasantry, not a hangup.
- The call's hard terminator is the BUDGET (per-show caller-line cap). At
  ~75% the beat prompt tells the host to land the ending in his own words;
  at 100% code injects the host's wrap and cuts the REST OF THE BEAT — both
  sides — so the ending airs clean and nobody talks to a ghost.
- A caller arriving with no on-air announcement gets the host's greeting
  INJECTED before their first line — announce-before-air is enforced, not
  requested.
- A wrapped caller returning in a later beat is dropped only when isolated
  (a stray line); if the beat carries a real continued conversation the call
  is un-wrapped and keeps counting against the SAME budget — leniency can
  change how a call ends, never whether it ends.
- Pacing is code-owned: the state tracks calls taken and the prompt carries
  the show's call target, so a call-in hour takes a realistic number of
  distinct callers instead of one marathon or none.

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
# call-interaction language: with NO caller live and NO caller speaking this
# beat, any of this is a one-sided PHANTOM CALL (greeting, hanging up on,
# losing, or thanking a caller who never existed)
_PHANTOM = re.compile(r"hang(?:s|ing)? up|hung up|we lost (?:him|her|the "
                      r"caller)|dial tone|\bclick\b|thanks for (?:the|your) "
                      r"call|you'?re on (?:the air|with)|go ahead,? caller",
                      re.I)

DEFAULT_BUDGET = 12          # caller lines per call before code wraps it

# a caller signing themselves off (terminal only if they then stay silent)
_CALLER_BYE = re.compile(r"\bgood ?night\b|\bbye(?:\s+now)?\b|"
                         r"I(?:'ll)? (?:let you go|hang up)|"
                         r"gotta (?:go|run)\b|I can (?:actually )?sleep now",
                         re.I)
# the injected on-air greeting when the LLM forgot to announce a caller
_ANNOUNCE = ["Let's go to the phones — {name}, you're on The Frequency.",
             "The board is lit. {name}, you're on the air — go ahead.",
             "We've got {name} on the line. {name}, go ahead."]


def _caller_name(ln: dict) -> str:
    return str(ln.get("speaker", "")).strip()


def prompt_line(state: dict | None, budget: int = DEFAULT_BUDGET,
                pacing: dict | None = None) -> str:
    """The authoritative call-state block for the beat prompt. `pacing` =
    {"target": calls this show should take, "done": calls taken so far} —
    rendered so the phones neither die after one marathon call nor churn."""
    if state and state.get("status") == "live":
        used = state.get("lines_used", 0)
        line = (f"SWITCHBOARD (authoritative): {state['name']} is ON THE LINE "
                f"({used} caller lines used, budget {budget}). Continue or "
                "wrap THIS call; when the host wraps it in his own words the "
                "caller is GONE — no further lines from or about them.")
        if used >= max(1, int(budget * 0.75)):
            line += (" This call's time is NEARLY SPENT — land the ending "
                     "within the next few lines, in the host's own words, "
                     "warmly. Do not start a new topic with this caller.")
        return line
    gone = f" {state['name']} already hung up and CANNOT return." if state and \
        state.get("name") else ""
    line = ("SWITCHBOARD (authoritative): all lines CLEAR — no caller is on "
            f"the line.{gone} A NEW caller may only join if a host brings "
            "them on air ('you're on...'). NEVER announce, tease, or 'hold "
            "for' an incoming call unless that caller actually speaks in "
            "THIS beat — and announce a call AT MOST ONCE: after 'caller on "
            "line two' the very next thing is the caller, never a second "
            "'hold that thought, there's a call.' You cannot speak TO, hang "
            "up ON, thank, or lose a caller who has not spoken — one-sided "
            "phone theater is forbidden.")
    if pacing and pacing.get("target"):
        done, target = pacing.get("done", 0), pacing["target"]
        if done < target:
            line += (f" PACING: this show takes about {target} calls across "
                     f"its window; {done} taken so far — when it fits "
                     "naturally in THIS beat, announce and bring on the "
                     "next caller.")
        else:
            line += (" PACING: the phones are done for this show — no new "
                     "callers; carry the hour without them.")
    return line


def _wrap_tell(text: str, name: str) -> bool:
    if _WRAP.search(text):
        return True
    first = (name.split() or [""])[0]
    return bool(first and re.search(
        r"\b(?:bye|good ?night|take care),?\s+%s\b" % re.escape(first),
        text, re.I))


def enforce(lines: list[dict], state: dict | None = None,
            budget: int = DEFAULT_BUDGET, host: dict | None = None) -> tuple:
    """Walk the beat's lines against the call state. Returns (new_lines,
    new_state). Never mutates inputs. Rules (see module docstring):
    - a host wrap-tell (or the caller's own goodbye) ends the call ONLY if
      that caller stays silent for the rest of the beat — mid-call
      pleasantries never amputate a living conversation;
    - a call exceeding `budget` TOTAL caller lines gets the host's wrap
      INJECTED and the remainder of the beat cut (both sides): the ending
      airs clean, nobody converses with a ghost;
    - a caller whose first line arrives unannounced gets the host's
      greeting injected before it;
    - a WRAPPED caller speaking again is dropped when isolated, un-wrapped
      (same budget) when the beat carries a real continued conversation;
    - state carries {name, status, lines_used, calls_done} across beats."""
    st = dict(state) if state else {}
    st.setdefault("name", "")
    st.setdefault("status", "clear")
    st.setdefault("lines_used", 0)
    st.setdefault("calls_done", 0)
    # lookahead: is there a caller line at any index > k?
    phone_after = [False] * len(lines)
    seen = False
    for k in range(len(lines) - 1, -1, -1):
        phone_after[k] = seen
        if lines[k].get("phone"):
            seen = True
    # does index k sit inside a continued conversation? (a host line and then
    # another caller line still follow — the LLM wrote a real exchange)
    def _conversing(k):
        host_seen = False
        for j in range(k + 1, len(lines)):
            if not lines[j].get("phone"):
                host_seen = True
            elif host_seen:
                return True
        return False

    def _inject(text):
        h = host or {}
        return {"speaker": h.get("speaker", "Host"),
                "voice": h.get("voice", "am_adam"),
                "speed": h.get("speed", 1.0),
                "text": text, "_enforced": True}

    out = []
    greeted = False
    cut = False
    for k, ln in enumerate(lines):
        if cut:            # budget fired: the call's ending already aired —
            continue       # the rest of this beat is cut, BOTH sides
        text = ln.get("text", "")
        if not ln.get("phone"):
            out.append(ln)
            if _GREET.search(text):
                greeted = True
                if st["status"] != "live":
                    st = {**st, "name": "", "status": "pending",
                          "lines_used": 0}
            if st["status"] == "live" and _wrap_tell(text, st["name"]):
                if not phone_after[k]:   # real hangup: caller stays silent
                    st = {**st, "status": "wrapped"}
                # else: a pleasantry mid-call — the conversation continues
            continue
        # ── a caller line ────────────────────────────────────────────────
        name = _caller_name(ln)
        if st["status"] == "wrapped":
            if name.lower() == st["name"].lower():
                if _conversing(k):
                    # the goodbye was premature — the call ran long. Keep the
                    # conversation two-sided; the budget still binds it.
                    st = {**st, "status": "live"}
                    print(f"  !! switchboard: premature wrap re-opened for "
                          f"{name!r} (call runs long)")
                else:
                    print(f"  !! switchboard: ghost caller line dropped: "
                          f"{text[:50]!r}")
                    continue
            else:                        # a NEW caller after the last call
                if not greeted:
                    out.append(_inject(_ANNOUNCE[
                        _stable_hash(name) % len(_ANNOUNCE)].format(
                            name=name.split()[0] if name else "caller")))
                    greeted = True
                    print(f"  !! switchboard: missing announcement injected "
                          f"for {name!r}")
                st = {**st, "name": name, "status": "live", "lines_used": 0,
                      "calls_done": st["calls_done"] + 1}
        elif st["status"] in ("clear", "pending"):
            if not greeted:
                out.append(_inject(_ANNOUNCE[
                    _stable_hash(name) % len(_ANNOUNCE)].format(
                        name=name.split()[0] if name else "caller")))
                greeted = True
                print(f"  !! switchboard: missing announcement injected "
                      f"for {name!r}")
            st = {**st, "name": name, "status": "live", "lines_used": 0,
                  "calls_done": st["calls_done"] + 1}
        elif st["status"] == "live" and name.lower() != st["name"].lower():
            st = {**st, "name": name, "status": "live", "lines_used": 0,
                  "calls_done": st["calls_done"] + 1}     # caller handoff
        if st["lines_used"] >= budget:
            out.append(_inject(
                f"Thanks for the call, {st['name'].split()[0] or 'friend'} — "
                "we'll leave it right there."))
            print(f"  !! switchboard: budget wrap injected for "
                  f"{st['name']!r}; beat cut")
            st = {**st, "status": "wrapped"}
            cut = True
            continue
        st = {**st, "lines_used": st["lines_used"] + 1}
        out.append(ln)
        # the caller signing off, then silent: that goodbye is terminal
        if (st["status"] == "live" and _CALLER_BYE.search(text)
                and not phone_after[k]):
            st = {**st, "status": "wrapped"}
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

    # PHANTOM CALL: nobody was on the line entering this beat and nobody
    # phones in during it — yet the host greets/hangs up on/thanks a caller.
    # That entire performance is about a person who does not exist: replaced.
    was_live = bool(state and state.get("status") == "live")
    if not was_live and not any(ln.get("phone") for ln in out):
        for k, ln in enumerate(out):
            if not ln.get("_enforced") and _PHANTOM.search(ln.get("text", "")):
                new = dict(ln)
                new["text"] = _TEASE_FIX[_stable_hash(new["text"])
                                         % len(_TEASE_FIX)]
                new["_enforced"] = True
                print(f"  !! switchboard: phantom-call line replaced: "
                      f"{ln['text'][:50]!r}")
                out[k] = new

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
        st = {**st, "name": "", "status": "clear", "lines_used": 0}
    return out, st
