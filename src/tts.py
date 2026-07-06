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


_ONES = ("zero one two three four five six seven eight nine ten eleven twelve "
         "thirteen fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty",
         6: "sixty", 7: "seventy", 8: "eighty", 9: "ninety"}


def _two_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    t, o = divmod(n, 10)
    return _TENS[t] + (f" {_ONES[o]}" if o else "")


def _spoken_year(m: re.Match) -> str:
    """espeak reads '1998' as 'nineteen hundred and ninety-eight' — say years
    the way people do: nineteen ninety-eight, twenty twenty-six, two thousand."""
    y = int(m.group())
    hi, lo = divmod(y, 100)
    if lo == 0:
        return "two thousand" if hi == 20 else f"{_two_words(hi)} hundred"
    if hi == 20 and lo < 10:
        return f"two thousand {_ONES[lo]}"
    return f"{_two_words(hi)} {'oh ' + _ONES[lo] if lo < 10 else _two_words(lo)}"


_ORD_ONES = {1: "first", 2: "second", 3: "third", 5: "fifth", 8: "eighth",
             9: "ninth", 12: "twelfth"}


def _ordinal_words(n: int) -> str:
    """1st -> first ... 99th -> ninety ninth (espeak mangles digit ordinals)."""
    if n in _ORD_ONES:
        return _ORD_ONES[n]
    if n < 20:
        return _ONES[n] + "th"
    t, o = divmod(n, 10)
    if o == 0:
        return _TENS[t][:-1] + "ieth"          # twenty -> twentieth
    return f"{_TENS[t]} {_ordinal_words(o)}"


def _spoken_time(m: re.Match) -> str:
    """7:00 -> seven o'clock, 7:05 -> seven oh five, 11:47 -> eleven forty seven."""
    h, mm = int(m.group(1)), int(m.group(2))
    h12 = h % 12 or 12
    if mm == 0:
        return f"{_two_words(h12)} o'clock"
    if mm < 10:
        return f"{_two_words(h12)} oh {_ONES[mm]}"
    return f"{_two_words(h12)} {_two_words(mm)}"


def _spoken_digits(m: re.Match) -> str:
    """Phone-style digit runs: 555-0142 -> five five five, zero one four two."""
    return ", ".join(" ".join(_ONES[int(d)] for d in part)
                     for part in m.group().split("-"))


# written-for-the-eye -> said-out-loud (word-boundary, case-sensitive on purpose)
_ABBREV = [
    (re.compile(r"\bMr\.(?=\s)"), "Mister"),
    (re.compile(r"\bMrs\.(?=\s)"), "Missus"),
    (re.compile(r"\bMs\.(?=\s)"), "Miz"),
    (re.compile(r"\bDr\.(?=\s+[A-Z])"), "Doctor"),
    (re.compile(r"\bProf\.(?=\s+[A-Z])"), "Professor"),
    (re.compile(r"\bSgt\.(?=\s+[A-Z])"), "Sergeant"),
    (re.compile(r"\bCapt\.(?=\s+[A-Z])"), "Captain"),
    (re.compile(r"\bLt\.(?=\s+[A-Z])"), "Lieutenant"),
    (re.compile(r"\bSt\.(?=\s+[A-Z])"), "Saint"),        # St. Mary
    (re.compile(r"(?<=[a-z] )St\.?(?=[\s,.!?]|$)"), "Street"),  # Main St.
    (re.compile(r"\bAve\.?(?=[\s,.!?]|$)"), "Avenue"),
    (re.compile(r"\bBlvd\.?(?=[\s,.!?]|$)"), "Boulevard"),
    (re.compile(r"\bRd\.(?=[\s,.!?]|$)"), "Road"),
    (re.compile(r"\betc\.?(?=[\s,.!?]|$)"), "et cetera"),
    (re.compile(r"\bvs\.?(?=\s)"), "versus"),
    (re.compile(r"\bapprox\.(?=\s)"), "approximately"),
    (re.compile(r"\bNo\.(?=\s*\d)"), "number"),
    (re.compile(r"\bmph\b"), "miles an hour"),
]


def clean_for_speech(text: str) -> str:
    """Rewrite text written for READERS into text said by a SPEAKER, then strip
    typography. Models will always produce eye-formats (1998, 7:30, Dr., 24/7,
    .com, 0.4) — assume every one of them, and normalize here, in one place."""
    t = text
    t = re.sub(r"\*[^*]{1,80}\*", " ", t)           # *stage directions* FIRST
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", t)     # bracketed directions
    for pat, rep in _ABBREV:                        # Dr. / Mr. / Main St. / mph
        t = pat.sub(rep, t)
    t = re.sub(r"(\d),(\d{3})\b", r"\1\2", t)       # 12,000 -> 12000
    t = re.sub(r"(\d)\s*°\s*F\b", r"\1 degrees fahrenheit", t)
    t = re.sub(r"(\d)\s*°\s*C\b", r"\1 degrees celsius", t)
    t = re.sub(r"(\d)\s*°", r"\1 degrees", t)
    t = re.sub(r"(\d)\s*%", r"\1 percent", t)       # symbols -> words
    t = re.sub(r"\$(\d[\d.]*)", r"\1 dollars", t)
    t = re.sub(r"\b24/7\b", "twenty-four seven", t)
    t = re.sub(r"#(\d)", r"number \1", t)
    t = re.sub(r"\.(com|net|org|fm|io|gov)\b", r" dot \1", t)
    # am/pm BEFORE clock digits turn into words (needs the digit to anchor,
    # so "I am" can never match)
    t = re.sub(r"(\d)\s*[aA]\.?[mM]\.?(?=[\s,.!?]|$)", r"\1 ay em", t)
    t = re.sub(r"(\d)\s*[pP]\.?[mM]\.?(?=[\s,.!?]|$)", r"\1 pee em", t)
    t = re.sub(r"\b(\d{1,2}):([0-5]\d)\b", _spoken_time, t)     # clock times
    t = re.sub(r"\b\d{3}-(?:\d{3}-)?\d{4}\b", _spoken_digits, t)  # phone shapes
    t = re.sub(r"(\d)\s*-\s*(\d)", r"\1 to \2", t)  # 5-10 -> 5 to 10 (ranges)
    t = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b",
               lambda m: _ordinal_words(int(m.group(1))), t)    # 3rd -> third
    t = re.sub(r"(\d)\.(\d+)", lambda m: m.group(1) + " point " +
               " ".join(_ONES[int(d)] for d in m.group(2)), t)  # 0.4 decimals
    t = re.sub(r"(?<![\d-])(1[89]\d{2}|20\d{2})(?!\d)", _spoken_year, t)  # years
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
        # questions get answered quicker, and every few exchanges someone
        # lets a line LAND before replying — the air is what makes it radio
        if i + 1 < len(spoken):
            if spoken[i + 1][2] != spk:
                base = 0.62
                if (not text.rstrip().endswith("?")
                        and random.random() < 0.18):
                    base = random.uniform(1.0, 1.5)   # a beat: let it land
            else:
                base = 0.28
            if text.rstrip().endswith("?"):
                base = min(base, 0.35)
            gap = int(sr * random.uniform(base * 0.75, base * 1.3))
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
