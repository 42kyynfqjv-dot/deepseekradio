"""Audio buffer accounting.

The orchestrator writes WAV segments into audio_buffer/incoming/ with a global
sequence prefix; the streamer (deploy/player.sh) consumes them oldest-first and
moves them to audio_buffer/played/. Generation is throttled so the buffer stays
near the configured target instead of racing days ahead.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path("audio_buffer")
INCOMING = ROOT / "incoming"
PLAYED = ROOT / "played"

_SAMPLE_RATE = 24000  # mono s16le — matches config tts.sample_rate
_BYTES_PER_SEC = _SAMPLE_RATE * 2


def ensure_dirs() -> None:
    INCOMING.mkdir(parents=True, exist_ok=True)
    PLAYED.mkdir(parents=True, exist_ok=True)


def buffered_seconds() -> float:
    """Approximate queued audio from file sizes (WAV header is negligible)."""
    return sum(f.stat().st_size for f in INCOMING.glob("*.wav")) / _BYTES_PER_SEC


def next_path(label: str) -> Path:
    """Next sequenced output path, e.g. incoming/000000042_scramble.wav."""
    ensure_dirs()
    seqs = [int(m.group(1)) for d in (INCOMING, PLAYED) for f in d.glob("*.wav")
            if (m := re.match(r"(\d{9})_", f.name))]
    seq = max(seqs, default=0) + 1
    safe = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40]
    return INCOMING / f"{seq:09d}_{safe}.wav"
