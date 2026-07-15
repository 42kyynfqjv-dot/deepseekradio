"""Regression checks for continuity and code-owned caller identity.

Run directly: python3 tests/test_prompt_contracts.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import orchestrator as O
from src import performers as P
from src import writer as W


PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


daypart = {
    "id": "static_hour",
    "show": "The Static Hour",
    "energy": "quiet",
    "cast": ["watcher"],
    "segments": ["Theory"],
    "outline_beats": [1, 1],
    "caller_policy": {"per_beat": 1, "max_lines": 3},
    "_continuity_desk": (
        "CONTINUITY DESK (authoritative): ARC BEAT Sock Ledger; "
        "CALLBACK: the shadow organization is still the Sock Ledger."
    ),
}


writer_prompts = []
old_writer_chat = W.chat


def fake_writer_chat(model, messages):
    writer_prompts.append(messages[-1]["content"])
    return json.dumps({
        "beats": [{
            "segment": "Theory", "premise": "the pen evidence",
            "beat": "the pen evidence points to the Sock Ledger",
            "link": "the pen is evidence for the same Sock Ledger frame",
            "move": "DEEPER", "grounding": "a jar of pens",
        }],
        "theory": "the Sock Ledger tracks every pen",
        "payoff": "the pens were filing reports for the Sock Ledger",
    })


W.chat = fake_writer_chat
try:
    W.write_outline(daypart, {"writer": {}, "performer": {}}, W.lore.load(), "Monday")
finally:
    W.chat = old_writer_chat

check(writer_prompts and "CONTINUITY DESK" in writer_prompts[0],
      "writer receives the authoritative continuity desk")


generic_shape = W._normalize_outline_shape({
    "guest": "model-picked guest",
    "beats": [
        {"segment": "A", "premise": "one", "beat": "one",
         "callback": "desk callback"},
        {"segment": "B", "premise": "two", "beat": "two",
         "callback": "unassigned lore"},
        {"segment": "A", "premise": "three", "beat": "three",
         "callback": "another lore"},
        {"segment": "B", "premise": "four", "beat": "four"},
    ],
}, {
    "id": "ordinary_show", "segments": ["A", "B"],
    "outline_beats": [2, 3], "guest": "never",
    "_assign": {"guest": "Assigned Guest", "props": ["a brass key"],
                "callback": "desk callback"},
})
check(len(generic_shape["beats"]) == 3,
      "ordinary shows keep their configured beat range, not six Watcher acts")
check(generic_shape["guest"] == "Assigned Guest",
      "code-owned guest assignment overrides model selection")
check(all(b.get("grounding") == "a brass key"
         for b in generic_shape["beats"]),
      "code-owned props are applied without asking the model to balance them")
check(sum(bool(b.get("callback")) for b in generic_shape["beats"]) <= 1,
      "code-owned callback assignment prevents callback sprawl")



performer_prompts = []
old_performer_chat = P.chat


def fake_performer_chat(model, messages):
    performer_prompts.append(messages[-1]["content"])
    return json.dumps({"lines": [
        {"speaker": "The Watcher", "text": "The pen points to the ledger."},
        {"speaker": "Random Caller", "text": "The clue is on the line."},
        {"speaker": "The Watcher", "text": "That is evidence for the same frame."},
    ]})


P.chat = fake_performer_chat
try:
    lines = P.perform_beat(
        {"segment": "Theory", "premise": "the premise", "beat": "the beat",
         "_outline_beat": 2, "_outline_beats": 6, "_part": 0,
         "_part_number": 1, "_parts_total": 3},
        daypart, {"performer": {}}, {}, "the earlier pen clue",
        caller_identity="Miriam")
finally:
    P.chat = old_performer_chat

prompt = performer_prompts[0] if performer_prompts else ""
check("CONTINUITY DESK" in prompt,
      "performer receives the authoritative continuity desk")
check("UNHINGED IS DELIVERY, NOT TOPIC CONTROL" in prompt,
      "Watcher prompt keeps creative intensity subordinate to topic continuity")
check("outline beat 2 of 6" in prompt and "part 1 of 3" in prompt,
      "performer receives the outline beat and part coordinates")
check(any(ln.get("speaker") == "Miriam" and ln.get("phone") for ln in lines),
      "code-owned caller identity survives generation and gets phone treatment")
check(not any(ln.get("speaker") == "Random Caller" for ln in lines),
      "model caller label cannot leak onto the air")
used = {"Darla"}
caller = O._caller_identity(used, "prompt-contract", "The Watcher")
check(caller and caller not in used,
      "caller identity selection does not reserve a name before it airs")
check(O._call_budget(daypart) == 3,
      "per-beat caller policy keeps the total budget bounded")
night_daypart = {"id": "night_shift", "show": "The Night Shift",
                 "energy": "warm", "cast": ["vivian"],
                 "segments": ["Dream Court"],
                 "caller_policy": {"per_beat": 1, "max_lines": 3}}
night_prompts = []
old_pchat = P.chat
def fake_night_chat(model, messages):
    night_prompts.append(messages[-1]["content"])
    return json.dumps({"lines": [
        {"speaker": "Vivian Nightshade", "text": "Vivian feels a wave of concern."},
        {"speaker": "Ruth", "text": "I feel forgotten."},
        {"speaker": "Vivian Nightshade", "text": "The host thinks about the dream."},
    ]})
P.chat = fake_night_chat
try:
    night_lines = P.perform_beat(
        {"segment": "Dream Court", "premise": "dream", "beat": "case"},
        night_daypart, {"performer": {}}, {}, "")
finally:
    P.chat = old_pchat
night_prompt = night_prompts[0] if night_prompts else ""
check("NIGHT SHIFT SPOKEN-RADIO CONTRACT" in night_prompt,
      "Night Shift prompt requires direct spoken dialogue")
check(any(ln.get("_register_guard") for ln in night_lines),
      "Night Shift narration is repaired after generation")
check(any(ln.get("phone") and ln.get("text") == "I feel forgotten."
          for ln in night_lines),
      "callers can still state their own feelings")

culture_daypart = {"id": "culture_vulture", "guest_role": "persistent",
                   "cast": ["cosima"]}
guest_beat = {"_guest": "The one-note jazz musician", "_guest_entry": True}
guest_lines = P._attach_voices([
    {"speaker": "Cosima Vale", "text": "We have been considering the form."},
    {"speaker": "Cosima Vale", "text": "Compose your own."},
    {"speaker": "Kosta", "text": "I have one note for you."},
    {"speaker": "Cosima Vale", "text": "And there is more to say about it."},
], culture_daypart, guest=guest_beat["_guest"])
guest_lines = P._enforce_guest_handoff(guest_lines, culture_daypart, guest_beat)
invite_at = next(i for i, ln in enumerate(guest_lines)
                 if ln.get("text") == "Compose your own.")
check(guest_lines[invite_at + 1].get("speaker") == "The one-note jazz musician",
      "persistent Culture Vulture guests answer immediately after an invitation")

caller_close = P._enforce_caller_policy([
    {"speaker": "The Watcher", "voice": "am_adam", "speed": 1.0,
     "text": "Tell us what you saw."},
    {"speaker": "Miriam", "phone": True, "voice": "af_bella",
     "speed": 1.0, "text": "The pen was waiting by the radio."},
], daypart)
last_phone = max(i for i, ln in enumerate(caller_close) if ln.get("phone"))
check(any((not ln.get("phone")) and i > last_phone and
          P._CALL_CLOSE.search(ln.get("text", ""))
          for i, ln in enumerate(caller_close)),
      "every accepted caller gets a code-owned host close")

overnight = {"id": "night_shift", "window": ["22:00", "02:00"]}
from datetime import datetime
check(O._air_show_key(overnight, datetime(2026, 7, 14, 1)) ==
      "night_shift:2026-07-13",
      "overnight shows keep one show-day key across midnight")

news_lines = [
    {"_news_desk": "news", "text": "headline"},
    {"_news_desk": "town", "text": "town wire"},
    {"_news_desk": "world", "text": "world wire"},
    {"_news_desk": "sports", "text": "sports wire"},
    {"_news_desk": "id", "text": "station id"},
]
bound_news = O._bound_news_lines(news_lines, hour=0, max_lines=3)
check(len(bound_news) == 3 and
      all(ln.get("_news_desk") in ("news", "town", "sports", "id")
          for ln in bound_news),
      "hourly news is capped and rotates one secondary desk")

watcher_shape = O._normalize_watcher_outline({
    "theory": "fresh frame",
    "payoff": "fresh landing",
    "builds_on": "not-approved",
    "beats": [
        {"segment": "Theory", "premise": "pens", "beat": "pens",
         "callback": "pen file"},
        {"segment": "Theory", "premise": "radios", "beat": "radios",
         "callback": "radio file"},
    ],
}, {"id": "static_hour", "segments": ["Theory"]},
    active_frame="the Sock Ledger",
    active_payoff="the Ledger filed the reports",
    allowed_parents={"approved-id"})
check(len(watcher_shape["beats"]) == 6,
      "only the Watcher receives the fixed six-act chapter spine")
check([b["move"] for b in watcher_shape["beats"]] ==
      ["OPENING", "DEEPER", "WIDER", "DEEPER", "CONVERGENCE", "PAYOFF"],
      "Watcher phases are code-owned and ordered toward closure")
check(watcher_shape["theory"] == "the Sock Ledger" and
      watcher_shape["payoff"] == "the Ledger filed the reports",
      "active Watcher frame and payoff cannot be silently replaced")
check(watcher_shape["builds_on"] is None and
      sum(bool(b.get("callback")) for b in watcher_shape["beats"]) <= 2,
      "unapproved parent and callback sprawl are removed by code")
print(f"prompt contracts {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
