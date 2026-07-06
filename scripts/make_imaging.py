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


def main() -> int:
    models = {"id": "deepseek/deepseek-v4-flash", "temperature": 0.8,
              "max_tokens": 900, "price_in": 0.09, "price_out": 0.18}
    raw = chat(models, [{"role": "user", "content": BRIEF}])
    t = raw.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1].lstrip("json").strip()
    sweepers = json.loads(t)["sweepers"][:10]

    cfg = {"tts": {"sample_rate": 24000, "default_voice": "am_onyx"}}
    beds = sorted(BEDS.glob("*.wav"))
    made = 0
    for i, line in enumerate(sweepers):
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
