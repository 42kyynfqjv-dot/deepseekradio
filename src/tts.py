"""Kokoro TTS — synthesize dialogue lines to a single audio segment.

Self-hosted, ~$0. On the box you install `kokoro-onnx` + the voice model (see
deploy/README.md). Import is lazy so the orchestrator's --dry-run works without
Kokoro installed.
"""
from __future__ import annotations

import wave
from pathlib import Path

_kokoro = None


def _engine(sample_rate: int):
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro  # lazy: only needed in --live
        _kokoro = Kokoro("kokoro/kokoro.onnx", "kokoro/voices.bin")
    return _kokoro


def synth_segment(lines: list[dict], out_path: Path, cfg: dict) -> Path:
    """Render a list of {speaker, voice, text} lines into one WAV file."""
    import numpy as np

    sr = cfg["tts"]["sample_rate"]
    kokoro = _engine(sr)
    chunks = []
    for ln in lines:
        text = ln.get("text", "").strip()
        if not text:
            continue
        voice = ln.get("voice", cfg["tts"]["default_voice"])
        samples, _ = kokoro.create(text, voice=voice, speed=1.0, lang="en-us")
        chunks.append(samples)
        chunks.append(np.zeros(int(sr * 0.35)))  # beat of silence between lines

    audio = np.concatenate(chunks) if chunks else np.zeros(sr)
    audio = (audio * 32767).astype("<i2")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(audio.tobytes())
    return out_path
