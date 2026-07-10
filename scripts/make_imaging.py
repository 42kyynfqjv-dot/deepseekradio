"""One-shot station imaging package: produced sweepers with beds and FX.

Writer generates the copy; Kokoro voices it; ffmpeg produces it — voice with
a touch of echo over a music bed, faded in and out. Output lands in the
reserve pool as bumper_id_*.wav so the player uses them at show boundaries
and during droughts. Run once on the box (or re-run to refresh the package).
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.openrouter import chat  # noqa: E402
from src import tts  # noqa: E402

RESERVE = Path("/opt/kaos/reserve")
BEDS = Path("/opt/kaos/beds")
VOICES = ["am_onyx", "bm_george", "af_nicole", "am_michael", "af_bella"]

BRIEF = """Write 10 DIFFERENT station imaging sweepers for The Frequency,
108.1 FM, call sign WFRQ — a 24/7 absurdist comedy radio station. Each is
ONE OR TWO short spoken sentences a big announcer voice would say between
shows. Mix of: station idents ("You're locked to The Frequency"), wry
promises ("Real headlines, wronged hourly"), show cross-promos (The Morning
Scramble, Center Ice hockey Wednesdays and Saturdays, The Static Hour
overnight, Best Of at bestairadio dot com), and deadpan absurd taglines.
Never sultry, PG, no clock times.
Return STRICT JSON: {"sweepers": ["<line>", ...]}"""

# Curated evergreen window-dressing — rendered every run so the bumper pool has
# reliable variety even if the LLM batch is thin or the model is down. Same
# register as BRIEF: idents, show cross-promos, deadpan taglines, PG, no clock
# times. Add more here anytime.
STATIC_SWEEPERS = [
    "You're locked to The Frequency. One-oh-eight point one, WFRQ, and we're not sure who's in charge either.",
    "This is The Frequency. If you can hear this, the antenna held.",
    "The Frequency — broadcasting twenty-four hours a day, from somewhere we'd rather not specify.",
    "You're on The Frequency. Management thanks you, whoever management is.",
    "WFRQ, one-oh-eight point one. The last station on the dial. Possibly the last station.",
    "Real headlines. Wronged hourly. The Frequency.",
    "The news, delivered accurately, then explained incorrectly. This is The Frequency.",
    "We report the weather with a bowl of water and total confidence. The Frequency.",
    "Mornings belong to The Morning Scramble — one adult, two problems, and a tribunal. On The Frequency.",
    "Reginald reviews a doorknob. Cosima disagrees. That's Refined Palate, on The Frequency.",
    "Bring your grievance to The Complaints Department, where it's escalated to someone who does not exist.",
    "Forty years of radio, training its own replacement, live and against its will. The Handover, on The Frequency.",
    "Center Ice — live hockey Wednesdays and Saturdays, from a league that shouldn't exist. Only on The Frequency.",
    "Can't sleep? Vivian's up too. The Night Shift, overnight on The Frequency.",
    "The Static Hour. The Watcher has a theory, and the theory has you in it. Late nights on The Frequency.",
    "One quiet hour, one quote, no bit. Dawn Patrol, first light on The Frequency.",
    "Missed it? Of course you did. The Best Of, at bestairadio dot com.",
    "The Frequency. We're pending review, and so is everything else.",
    "Now broadcasting from Halfway, capital of Wending — the fifty-first state, admitted by clerical error.",
    "Win big on The Frequency. The grand prize remains a single double-A battery.",
    "Visit The Frequency Gift Shop. One mug. Not for sale. Viewing by appointment.",
    "The Frequency salutes the goose running for Governor. We have questions. He has a platform.",
    "Sponsored, allegedly, by Gary's Discount Teeth. The teeth are fine. The discount is the concern.",
    "The Void is now hiring. Great benefits. No ceiling, no floor. Heard here on The Frequency.",
    "The Frequency. All the voices are artificial. All the grudges are real.",
    "If a bit couldn't air on daytime family radio, it doesn't air here. We checked. Twice. The Frequency.",
    "Stay tuned to The Frequency, where the schedule is a suggestion and the goose is a candidate.",
    "You've found The Frequency. We admire your commitment to finding out what's next.",
    "Twenty-four hours a day, zero humans, one mug. You're listening to The Frequency.",
    "The Frequency: it's soup out there. Bundle up. We don't fully know what that means either.",
    "The following is a test of the Wending Emergency Alert System. That was it. That was the entire test. Everything is fine, provisionally. This concludes the test.",
]


def main() -> int:
    models = {"id": "deepseek/deepseek-v4-flash", "temperature": 0.8,
              "max_tokens": 900, "price_in": 0.09, "price_out": 0.18}
    llm = []
    try:
        raw = chat(models, [{"role": "user", "content": BRIEF}])
        t = raw.strip()
        if t.startswith("```"):
            t = t.split("```", 2)[1].lstrip("json").strip()
        llm = json.loads(t).get("sweepers", [])[:10]
    except Exception as e:
        print(f"  (LLM sweepers skipped: {e})")
    # curated evergreen lines first, then the fresh LLM batch
    lines = STATIC_SWEEPERS + [str(s) for s in llm if str(s).strip()]

    cfg = {"tts": {"sample_rate": 24000, "default_voice": "am_onyx"}}
    beds = sorted(BEDS.glob("*.wav"))
    made = 0
    for i, line in enumerate(lines):
        voice = VOICES[i % len(VOICES)]
        dry = RESERVE / f".imaging_dry_{i}.wav"
        out = RESERVE / f"bumper_id_{i:02d}.wav"
        seg = tts.synth_segment(
            [{"speaker": "Announcer", "voice": voice, "speed": 0.96,
              "text": line}], dry, cfg)
        if not seg:
            continue
        bed = random.choice(beds)
        # voice up front with a hint of echo; bed ducked underneath; tails out
        cmd = ["ffmpeg", "-v", "error", "-y",
               "-i", str(dry), "-i", str(bed),
               "-filter_complex",
               "[0:a]aecho=0.7:0.5:60:0.25,adelay=1200|1200,"
               "apad=pad_dur=2.2[v];"
               "[1:a]volume=0.32,afade=t=in:d=1.2[b];"
               "[b][v]amix=inputs=2:duration=shortest:dropout_transition=0,"
               "afade=t=out:st=6:d=2.5,alimiter=limit=0.9,"
               "atrim=0:8.5[mix]",
               "-map", "[mix]", "-ar", "24000", "-ac", "1", str(out)]
        if subprocess.run(cmd, timeout=120).returncode == 0:
            made += 1
            print(f"  ♪ {out.name}: {line}")
        dry.unlink(missing_ok=True)
    print(f"imaging package: {made} produced sweepers in {RESERVE}")
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())
