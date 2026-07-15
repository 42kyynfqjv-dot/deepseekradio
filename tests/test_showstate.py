"""Daily show continuity ledger checks."""
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import showstate as S


PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL:", msg)


with tempfile.TemporaryDirectory() as tmp:
    old_root = S.ROOT
    S.ROOT = Path(tmp)
    try:
        dp = {"id": "culture_vulture", "window": ["19:00", "22:00"]}
        outline = {"beats": [{"segment": "Interview", "premise": "the guest"}]}
        state = S.begin(dp, "culture_vulture:2026-07-16", outline,
                        frame="the guest's one note", payoff="the note lands",
                        guest="The one-note jazz musician")
        state = S.update(
            dp, state,
            beat={"_outline_beat": 1, "_part": 0, "segment": "Interview",
                  "premise": "the guest demonstrates the note"},
            lines=[{"speaker": "Cosima", "text": "It points back to the form."}],
            next_beat=0, next_part=1)
        prompt = S.prompt_block(state)
        check("the guest's one note" in prompt and "demonstrates the note" in prompt,
              "compact prompt block preserves frame and completed beat")
        check((S.ROOT / S.air_date(dp) / "culture_vulture.json").exists(),
              "state is written to a daily per-show file")
        S.finish(dp, state, True)
        check(S.load(dp).get("completed") is True,
              "completed show state survives a same-day restart")

        S.save(dp, {"marker": "old"}, date="2026-07-15")
        S.cleanup("2026-07-16")
        check(not (S.ROOT / "2026-07-15").exists(),
              "old daily show ledgers are cleaned up")
    finally:
        S.ROOT = old_root

print(f"showstate {PASS} passed, {FAIL} failed")
raise SystemExit(1 if FAIL else 0)
