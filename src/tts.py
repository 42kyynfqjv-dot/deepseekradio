"""Kokoro TTS — synthesize dialogue lines to a single audio segment.

Self-hosted, ~$0. On the box you install `kokoro-onnx` + the voice model (see
deploy/README.md). Import is lazy so the orchestrator's --dry-run works without
Kokoro installed.
"""
from __future__ import annotations

import re
import wave
from pathlib import Path


def clean_for_speech(text: str) -> str:
    """Strip typography the models write but a voice should never read aloud."""
    t = text
    t = re.sub(r"[*_~`#]+", "", t)                  # markdown emphasis/headers
    t = t.replace("\u2026", ", ").replace("...", ", ")  # ellipses -> beat
    t = re.sub(r"[\u2014\u2013]", ", ", t)          # em/en dashes -> beat
    t = t.replace("\u2018", "'").replace("\u2019", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", t)      # stage directions in brackets
    t = re.sub(r"[^\w\s.,?!'\"-]", " ", t)          # anything else exotic (emoji etc.)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t

_kokoro = None


def _engine(sample_rate: int):
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro  # lazy: only needed in --live
        _kokoro = Kokoro("kokoro/kokoro.onnx", "kokoro/voices.bin")
    return _kokoro


def synth_segment(lines: list[dict], out_path: Path, cfg: dict) -> Path:
    """Render a list of {speaker, voice, text} lines into one WAV file."""
    import os
    import random

    import numpy as np

    sr = cfg["tts"]["sample_rate"]
    kokoro = _engine(sr)
    # pre-clean: only lines with actual speakable content survive
    spoken = []
    for ln in lines:
        text = clean_for_speech(ln.get("text", "").strip())
        if text and re.search(r"[A-Za-z0-9]", text):
            spoken.append((ln.get("voice", cfg["tts"]["default_voice"]),
                           ln.get("speed", 1.0), ln.get("speaker"), text))
    chunks = []
    for i, (voice, speed, spk, text) in enumerate(spoken):
        try:
            # character pace with slight per-line jitter so delivery isn't metronomic
            samples, _ = kokoro.create(text, voice=voice,
                                       speed=speed * random.uniform(0.98, 1.03),
                                       lang="en-us")
        except Exception:
            continue  # one unspeakable line must not void the segment
        chunks.append(samples)
        # conversational rhythm: gap reflects the UPCOMING transition
        if i + 1 < len(spoken):
            base = 0.5 if spoken[i + 1][2] != spk else 0.22
            chunks.append(np.zeros(int(sr * random.uniform(base * 0.7, base * 1.4))))

    audio = np.concatenate(chunks) if chunks else np.zeros(sr)
    audio = np.clip(audio, -1.0, 1.0)          # saturate, never wrap
    audio = (audio * 32767).astype("<i2")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # temp + atomic rename so the streamer can never play a half-written file
    tmp = out_path.with_name(out_path.name + ".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(audio.tobytes())
    os.replace(tmp, out_path)
    return out_path
