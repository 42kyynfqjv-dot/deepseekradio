"""Kokoro TTS — synthesize dialogue lines to a single audio segment.

Self-hosted, ~$0. On the box you install `kokoro-onnx` + the voice model (see
deploy/README.md). Import is lazy so the orchestrator's --dry-run works without
Kokoro installed.

Audio treatment (audit roadmap I1/I3/I4):
- every line is RMS-normalized to a house level before it enters the buffer
- callers get a telephone bandpass; The Static Hour gets a shortwave treatment
- gaps are room tone (never digital black), every edge is faded
"""
from __future__ import annotations

import re
import wave
from pathlib import Path


def clean_for_speech(text: str) -> str:
    """Strip typography the models write but a voice should never read aloud."""
    t = text
    t = re.sub(r"\*[^*]{1,80}\*", " ", t)           # *stage directions* FIRST
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", t)     # bracketed directions
    t = re.sub(r"(\d)\s*%", r"\1 percent", t)       # symbols -> words
    t = re.sub(r"\$(\d[\d,.]*)", r"\1 dollars", t)
    t = t.replace("&", " and ")
    t = re.sub(r"[*_~`#]+", "", t)                  # leftover markdown
    t = t.replace("…", ". ").replace("...", ". ")  # ellipsis = full-stop beat
    t = re.sub(r"[—–]", ", ", t)          # em/en dashes -> beat
    t = t.replace("‘", "'").replace("’", "'")
    t = t.replace("“", '"').replace("”", '"')
    t = re.sub(r"[^\w\s.,?!'\"-]", " ", t)          # anything else exotic
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


_kokoro = None
_filters = {}


def _patch_phonemizer():
    """phonemizer's module-level phonemize() builds a NEW espeak backend per
    call, and every backend init copies libespeak-ng.so (~10MB) into a fresh
    tmpdir that is only cleaned at process exit. At ~100 lines/hour that
    filled the 1.9G tmpfs twice in one night and silenced the station.
    Cache one backend per language for the life of the process."""
    import phonemizer
    from phonemizer.backend import EspeakBackend

    backends = {}

    def cached_phonemize(text, language="en-us", preserve_punctuation=True,
                         with_stress=True, **kw):
        b = backends.get(language)
        if b is None:
            b = EspeakBackend(language,
                              preserve_punctuation=preserve_punctuation,
                              with_stress=with_stress)
            backends[language] = b
        out = b.phonemize([text] if isinstance(text, str) else list(text), strip=True)
        return out[0] if isinstance(text, str) and out else out

    phonemizer.phonemize = cached_phonemize
    try:  # the tokenizer holds its own module ref
        import kokoro_onnx.tokenizer as _tok
        _tok.phonemizer.phonemize = cached_phonemize
    except Exception:
        pass


def _engine(sample_rate: int):
    global _kokoro
    if _kokoro is None:
        _patch_phonemizer()
        from kokoro_onnx import Kokoro  # lazy: only needed in --live
        _kokoro = Kokoro("kokoro/kokoro.onnx", "kokoro/voices.bin")
    return _kokoro


def _sos(kind: str, sr: int):
    """Cached scipy filters for the phone / shortwave treatments."""
    if kind not in _filters:
        from scipy.signal import butter
        if kind == "phone":
            _filters[kind] = butter(4, [300, 3400], btype="band", fs=sr, output="sos")
        else:  # shortwave: narrower + darker
            _filters[kind] = butter(4, [300, 3300], btype="band", fs=sr, output="sos")
    return _filters[kind]


def _voice_fx(samples, kind: str, sr: int):
    """Telephone-band callers / shortwave Watcher. Masks TTS artifacts too."""
    import numpy as np
    from scipy.signal import sosfilt

    x = sosfilt(_sos(kind, sr), samples)
    x = np.tanh(x * 2.2) / 2.2          # mild soft saturation
    return x * (0.7 if kind == "phone" else 0.8)


def _level(samples, target_db: float = -20.0, peak_db: float = -3.0):
    """RMS-normalize a line to house level with a peak guard (no clip later)."""
    import numpy as np

    rms = float(np.sqrt(np.mean(samples ** 2)))
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if rms < 1e-6 or peak < 1e-6:
        return samples
    gain = min((10 ** (target_db / 20)) / rms, (10 ** (peak_db / 20)) / peak)
    return samples * gain


def _room_tone(n: int, sr: int, db: float = -58.0):
    """Brown-ish noise floor: silence that sounds like a room, not a file."""
    import numpy as np

    n = max(int(n), 2)
    w = np.random.default_rng().standard_normal(n)
    b = np.cumsum(w)
    b -= np.linspace(b[0], b[-1], n)             # detrend so it loops clean
    m = float(np.max(np.abs(b))) or 1.0
    return (b / m) * (10 ** (db / 20))


def _fade(x, sr: int, ms_in: float = 5, ms_out: float = 5):
    import numpy as np

    fi, fo = int(sr * ms_in / 1000), int(sr * ms_out / 1000)
    if fi and len(x) > fi:
        x[:fi] *= np.linspace(0, 1, fi)
    if fo and len(x) > fo:
        x[-fo:] *= np.linspace(1, 0, fo)
    return x


def synth_segment(lines: list[dict], out_path: Path, cfg: dict,
                  fx: str | None = None) -> Path:
    """Render a list of {speaker, voice, text} lines into one WAV file."""
    import os
    import random

    import numpy as np

    sr = cfg["tts"]["sample_rate"]
    kokoro = _engine(sr)
    spoken = []
    for ln in lines:
        text = clean_for_speech(ln.get("text", "").strip())
        if text and re.search(r"[A-Za-z0-9]", text):
            spoken.append((ln.get("voice", cfg["tts"]["default_voice"]),
                           ln.get("speed", 1.0), ln.get("speaker"),
                           bool(ln.get("phone")), text))
    chunks = []
    for i, (voice, speed, spk, phone, text) in enumerate(spoken):
        try:
            samples, _ = kokoro.create(text, voice=voice,
                                       speed=speed * random.uniform(0.98, 1.03),
                                       lang="en-us")
        except Exception as e:
            print(f"  !! tts line failed ({type(e).__name__}: {e})")
            continue  # one unspeakable line must not void the segment
        samples = np.asarray(samples, dtype=np.float64)
        if phone:
            samples = _voice_fx(samples, "phone", sr)
        elif fx == "static_hour":
            samples = _voice_fx(samples, "shortwave", sr)
        samples = _fade(_level(samples), sr)
        chunks.append(samples)
        # conversational rhythm: gap reflects the UPCOMING transition;
        # questions get answered quicker
        if i + 1 < len(spoken):
            base = 0.5 if spoken[i + 1][2] != spk else 0.22
            if text.rstrip().endswith("?"):
                base = min(base, 0.3)
            gap = int(sr * random.uniform(base * 0.7, base * 1.4))
            chunks.append(_room_tone(gap, sr))

    if not chunks:
        # a segment with zero synthesized lines is a husk — never queue it
        print("  !! synthesis produced NOTHING for this segment — dropped")
        return None
    audio = np.concatenate(chunks)
    audio = audio + _room_tone(len(audio), sr, db=-63.0)   # continuous floor
    # raised-cosine edges on the whole segment so joins never click
    edge = int(sr * 0.03)
    if len(audio) > 2 * edge:
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, edge))
        audio[:edge] *= ramp
        audio[-edge:] *= ramp[::-1]
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
