"""The Watcher's private canon: seeded, growing, capped, and quarantined —
and structurally incapable of canonizing a real company.

Run directly (no pytest needed):  python3 tests/test_watcherlore.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import watcherlore as W

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def L(text):
    return {"speaker": "The Watcher", "voice": "am_onyx", "text": text}


prev = os.getcwd()
with tempfile.TemporaryDirectory() as td:
    os.chdir(td)
    try:
        st = W.load()
        check(len(st["entities"]) == len(W.SEED), "seed bank loads")
        blk = W.prompt_block(st, "2026-07-12")
        check(blk.count("— ") >= W.PER_NIGHT and "PRIVATE" in blk.upper()
              or "private canon" in blk, "prompt block carries dossiers")
        check(blk == W.prompt_block(st, "2026-07-12"),
              "rotation is stable within a night")
        surfaced = [e["name"] for e in st["entities"] if e["name"] in blk]
        check(len(surfaced) == W.PER_NIGHT, "exactly PER_NIGHT files surface")
        check("Never contradict" in blk, "the no-contradiction rule rides")

        # resurfacing bumps the dossier once per night
        lines = [L("The Pigeon Bureau moved the benches again last week."),
                 L("I have photos. The pigeon bureau always collects them.")]
        W.harvest(lines, st, "2026-07-12")
        pb = next(e for e in st["entities"] if e["name"] == "The Pigeon Bureau")
        check(pb["nights"] == 1 and pb["last_night"] == "2026-07-12",
              "resurfaced file bumped once")
        W.harvest(lines, st, "2026-07-12")
        check(pb["nights"] == 1, "same-night mentions never double-bump")
        W.harvest(lines, st, "2026-07-13")
        check(pb["nights"] == 2, "a new night bumps again")

        # new inventions are canonized (capped per night)
        inv = [L("It traces back to the Marmot Syndicate. All of it."),
               L("The Marmot Syndicate owns the Drizzle Institute outright."),
               L("And behind both? The Left Sock Authority.")]
        n = W.harvest(inv, st, "2026-07-13")
        names = {e["name"] for e in st["entities"]}
        check(n == W.HARVEST_PER_NIGHT, f"harvest capped per night (got {n})")
        check("The Marmot Syndicate" in names, "new file opened")
        ms = next(e for e in st["entities"]
                  if e["name"] == "The Marmot Syndicate")
        check("traces back" in ms["dossier"], "dossier keeps the first line")
        check(W.harvest(inv, st, "2026-07-13") == 0,
              "re-harvest never duplicates")

        # a real company can never be canonized
        real = [L("Wake up — the Tesla Group runs the chargers."),
                L("It was the General Motors Committee all along.")]
        before = len(st["entities"])
        check(W.harvest(real, st, "2026-07-14") == 0
              and len(st["entities"]) == before,
              "real-world names are never canonized")
        # scrubbed lines never feed the canon
        scrubbed = [dict(L("The Vulture Commission has files."),
                         _enforced=True)]
        check(W.harvest(scrubbed, st, "2026-07-14") == 0,
              "guard-replaced lines never feed the canon")

        # the board only holds so many photos
        for i in range(30):
            st["entities"].append({"name": f"The Filler Bureau {i}",
                                   "dossier": "thin", "first_night": "",
                                   "last_night": "", "nights": 0,
                                   "seeded": False})
        W.harvest([L("The corkboard breathes tonight.")], st, "2026-07-15")
        check(len(st["entities"]) <= W.BANK_CAP, "bank capped")
        kept = {e["name"] for e in st["entities"]}
        check("The Pigeon Bureau" in kept and "The Marmot Syndicate" in kept,
              "active files survive the prune")

        W.save(st)
        st2 = W.load()
        check({e["name"] for e in st2["entities"]} == kept,
              "state round-trips")
    finally:
        os.chdir(prev)


# --- the theory clock: one descent per hour, restart-proof ------------------
with tempfile.TemporaryDirectory() as td2:
    os.chdir(td2)
    try:
        T0 = 1_000_000.0
        cont, n = W.current_theory("2026-07-12", T0)
        check(cont is None and n == 1, "fresh night starts at t1")
        W.begin_theory("2026-07-12", 1, "the streetlights blink in a pattern",
                       T0, frame="the Streetlight Ledger is steering Tuesday",
                       payoff="the blinking is how Tuesday files its reports")
        entry = W.current_entry("2026-07-12", T0 + 30 * 60)
        check(entry["frame"] == "the Streetlight Ledger is steering Tuesday",
              "active theory keeps its durable frame")
        check("the blinking is how Tuesday files its reports" in W.spine_block(entry),
              "active theory carries its chapter landing")
        cont, n = W.current_theory("2026-07-12", T0 + 30 * 60)
        check(cont == "the streetlights blink in a pattern" and n == 1,
              "re-entry inside the hour continues the SAME theory")
        cont, n = W.current_theory("2026-07-12", T0 + 61 * 60)
        check(cont is None and n == 2, "past the hour a fresh theory begins")
        W.begin_theory("2026-07-12", 2, "the lids click three times", T0 + 61 * 60)
        cont, n = W.current_theory("2026-07-13", T0 + 62 * 60)
        check(cont is None and n == 1, "a new broadcast day resets to t1")
        check(W.theory_subject("2026-07-12", 2) == "the lids click three times",
              "ledger answers the podcast title lookup")
        check(W.theory_subject("2026-07-12", 9) is None, "unknown file is None")
    finally:
        os.chdir(prev)

# --- closed chapters wait three later episodes before sequel reuse ------------
with tempfile.TemporaryDirectory() as td3:
    os.chdir(td3)
    try:
        for n in range(1, 5):
            W.close_chapter(
                "2026-07-12", n,
                f"the Pen Bureau chapter {n}",
                f"the pen case closes for chapter {n}",
                [L("The Pen Bureau files another harmless report.")],
                loose_threads=["find the next stamp"],
            )
        block = ""
        candidate_episode = None
        for episode in range(5, 40):
            block = W.chapter_block("2026-07-13", episode)
            if block:
                candidate_episode = episode
                break
        check(block and candidate_episode and "2026-07-12-t1" in block,
              "a past chapter becomes eligible after three later closures")
        check("CLOSED PAYOFF" in block and "OPTIONAL LOOSE THREADS" in block,
              "eligible sequel carries closure and optional threads")
        W.close_chapter(
            "2026-07-13", candidate_episode, "a fresh chapter", "a new ending",
            [], builds_on="2026-07-12-t1")
        jailed = W._eligible_chapters("2026-07-14", candidate_episode + 1)
        check(not any(c.get("id") == "2026-07-12-t1" for c in jailed),
              "a reused theory is jailed again after its sequel")
    finally:
        os.chdir(prev)

print(f"watcherlore {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
