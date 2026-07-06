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
    import random

    import numpy as np

    sr = cfg["tts"]["sample_rate"]
    kokoro = _engine(sr)
    chunks = []
    prev_speaker = None
    for ln in lines:
        text = clean_for_speech(ln.get("text", "").strip())
        if not text:
            continue
        voice = ln.get("voice", cfg["tts"]["default_voice"])
        # character pace with slight per-line jitter so delivery isn't metronomic
        speed = ln.get("speed", 1.0) * random.uniform(0.98, 1.03)
        samples, _ = kokoro.create(text, voice=voice, speed=speed, lang="en-us")
        chunks.append(samples)
        # conversational rhythm: quick continuation, longer on speaker change
        spk = ln.get("speaker")
        base = 0.5 if spk != prev_speaker else 0.22
        chunks.append(np.zeros(int(sr * random.uniform(base * 0.7, base * 1.4))))
        prev_speaker = spk

    audio = np.concatenate(chunks) if chunks else np.zeros(sr)
    audio = (audio * 32767).astype("<i2")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(audio.tobytes())
    return out_path
