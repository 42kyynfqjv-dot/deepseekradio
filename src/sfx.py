"""Arena SFX for Center Ice — procedural, IP-clean, radio-disciplined.

Every asset is SYNTHESIZED in-process (numpy) and cached — no sample packs, no
licensing, nothing to deploy. tag_sfx() walks a beat's lines against the
engine's event list and marks WHERE sound belongs (the horn on the goal call,
the whistle on the penalty announcement, a crowd swell under a big save);
tts.synth_segment mixes the tagged assets under the dialogue at line-accurate
offsets. Dialogue is king on radio: everything sits ducked beneath the call.

The continuous arena bed is the one on-disk asset (player.sh ducks it under
whole segments via its existing bed mechanism); build it with
`python -m src.sfx bed /opt/kaos/beds/crowd-center-ice.wav`.

Stdlib+numpy leaf module: tts/orchestrator import this, never the reverse.
"""
from __future__ import annotations

import re

_cache: dict = {}


def _np():
    import numpy as np
    return np


def _shaped_noise(n: int, sr: int, lo: float, hi: float, tilt: float = -3.0,
                  seed: int = 7):
    """Band-limited noise via FFT masking with a dB/octave tilt — the raw
    material of every crowd sound. Deterministic (seeded) so assets are
    stable across processes."""
    np = _np()
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / sr)
    mask = np.zeros_like(f)
    band = (f >= lo) & (f <= hi)
    # smooth band edges (raised cosine over ~1/3 octave) + spectral tilt
    fl, fh = lo * 1.26, hi / 1.26
    mask[band] = 1.0
    rise = (f >= lo) & (f < fl)
    mask[rise] = 0.5 - 0.5 * np.cos(np.pi * (f[rise] - lo) / max(fl - lo, 1))
    fall = (f > fh) & (f <= hi)
    mask[fall] = 0.5 + 0.5 * np.cos(np.pi * (f[fall] - fh) / max(hi - fh, 1))
    with np.errstate(divide="ignore"):
        tiltw = np.where(f > 0, (f / 440.0) ** (tilt / 6.0), 0.0)
    y = np.fft.irfft(X * mask * tiltw, n)
    m = float(np.max(np.abs(y))) or 1.0
    return y / m


def _rms_to(x, db: float):
    np = _np()
    r = float(np.sqrt(np.mean(x ** 2)))
    return x * (10 ** (db / 20) / r) if r > 1e-9 else x


def _env(n: int, sr: int, attack: float, release: float, hold: float = None):
    """Attack/hold/exponential-release envelope."""
    np = _np()
    e = np.ones(n)
    a = min(int(attack * sr), n)
    if a:
        e[:a] = np.linspace(0, 1, a)
    h = n if hold is None else min(a + int(hold * sr), n)
    tail = n - h
    if tail > 0:
        e[h:] = np.exp(-np.arange(tail) / (release * sr))
    return e


def _horn(sr: int, dur: float):
    """Arena air-horn: thick detuned low duo (root + fifth), soft-clipped."""
    np = _np()
    n = int(sr * dur)
    t = np.arange(n) / sr
    x = np.zeros(n)
    for f0 in (146.8, 220.2):                      # D3 + A3
        for det in (0.996, 1.0, 1.005):            # chorus thickness
            f = f0 * det
            for k in (1, 2, 3, 4, 5):              # bright brassy harmonics
                x += np.sin(2 * np.pi * f * k * t + k) / k
    x = np.tanh(x * 0.8)
    x *= _env(n, sr, attack=0.025, release=0.35, hold=dur - 0.5)
    return _rms_to(x, -20.0)


def _crowd(sr: int, dur: float, lo: float, hi: float, attack: float,
           release: float, hold: float, seed: int, flutter: float = 0.25):
    """A crowd gesture: shaped noise with slow amplitude flutter (many voices)."""
    np = _np()
    n = int(sr * dur)
    x = _shaped_noise(n, sr, lo, hi, tilt=-4.0, seed=seed)
    t = np.arange(n) / sr
    x *= 1.0 + flutter * np.sin(2 * np.pi * 5.3 * t) * np.sin(2 * np.pi * 0.7 * t)
    x *= _env(n, sr, attack=attack, release=release, hold=hold)
    return _rms_to(x, -20.0)


def _whistle(sr: int):
    """Referee pea-whistle: bright tone with a fast trill."""
    np = _np()
    n = int(sr * 0.85)
    t = np.arange(n) / sr
    trill = 1.0 + 0.02 * np.sign(np.sin(2 * np.pi * 28 * t))
    x = np.sin(2 * np.pi * 2870 * trill * t)
    x += 0.35 * np.sin(2 * np.pi * 2 * 2870 * trill * t)
    x *= _env(n, sr, attack=0.008, release=0.10, hold=0.55)
    return _rms_to(x, -20.0)  # house level; relative gain applied at mix


def _organ(sr: int):
    """Original four-note rally arpeggio — square-ish organ voice. Composed
    here (a trivial ascending phrase), no borrowed melody."""
    np = _np()
    notes = [(220.0, 0.18), (277.2, 0.18), (329.6, 0.18), (440.0, 0.46)]
    chunks = []
    for f0, dur in notes:
        n = int(sr * dur)
        t = np.arange(n) / sr
        x = np.zeros(n)
        for k in (1, 3, 5, 7):                    # odd harmonics = organ reed
            x += np.sin(2 * np.pi * f0 * k * t) / k
        x += 0.5 * np.sin(2 * np.pi * f0 * 2 * t)  # octave coupler
        x *= _env(n, sr, attack=0.01, release=0.06, hold=dur - 0.08)
        chunks.append(x)
    x = np.concatenate(chunks)
    return _rms_to(x, -20.0)


def _boards(sr: int):
    """A body into the boards: low knock + glass rattle burst."""
    np = _np()
    n = int(sr * 0.5)
    t = np.arange(n) / sr
    knock = np.sin(2 * np.pi * 82 * t) * np.exp(-t / 0.07)
    rattle = _shaped_noise(n, sr, 900, 5200, tilt=-2.0, seed=11)
    rattle *= np.exp(-t / 0.05)
    return _rms_to(knock + 0.7 * rattle, -20.0)


_RECIPES = {
    "goal_horn":   lambda sr: _horn(sr, 2.6),
    "period_horn": lambda sr: _horn(sr, 3.2),
    "crowd_roar":  lambda sr: _crowd(sr, 6.5, 150, 3200, 0.12, 2.1, 1.3, seed=3),
    "crowd_ooh":   lambda sr: _crowd(sr, 2.3, 240, 1400, 0.07, 0.55, 0.25, seed=5),
    "whistle":     lambda sr: _whistle(sr),
    "organ_riff":  lambda sr: _organ(sr),
    "boards":      lambda sr: _boards(sr),
}

# mix gain per asset, dB RELATIVE to dialogue house level (-20 dBFS RMS);
# every asset is leveled to house RMS first. Radio discipline: the call stays
# out front; the building sits behind it. Conservative on purpose — a horn
# that buries the call is worse than a distant one.
GAIN_DB = {"goal_horn": -5.0, "period_horn": -5.0, "crowd_roar": -8.0,
           "crowd_ooh": -12.0, "whistle": -12.0, "organ_riff": -14.0,
           "boards": -12.0}


def asset(name: str, sr: int):
    """Synthesized-on-demand, cached for the process lifetime."""
    key = (name, sr)
    if key not in _cache:
        _cache[key] = _RECIPES[name](sr).astype("float64")
    return _cache[key]


def crowd_bed(sr: int, seconds: float = 88.0):
    """Loopable arena ambience for the player's bed mechanism: distant crowd
    wash with slow swells, crossfaded end-to-start so it loops clean."""
    np = _np()
    n = int(sr * seconds)
    x = _shaped_noise(n, sr, 170, 2600, tilt=-5.0, seed=19)
    t = np.arange(n) / sr
    x *= 1.0 + 0.18 * np.sin(2 * np.pi * 0.061 * t) \
             + 0.10 * np.sin(2 * np.pi * 0.017 * t + 1.3)
    xf = min(int(sr * 2.0), n // 2)        # loop-clean crossfade, short-safe
    if xf > 0:
        ramp = np.linspace(0, 1, xf)
        x[:xf] = x[:xf] * ramp + x[-xf:] * (1 - ramp)
        x = x[:n - xf]
    return _rms_to(x, -20.0)


# ---------------------------------------------------------------- tagging

_SAVE_RE = re.compile(r"\b(save|saves|robbed|robs|denied|denies|stops|stopped|"
                      r"gloves? it|off the post|off the bar|off the iron|"
                      r"big stop|what a stop)\b", re.I)
_HIT_RE = re.compile(r"\b(into the boards|along the boards|big hit|"
                     r"levels? him|crunch(ed|ing)?)\b", re.I)
_FINAL_RE = re.compile(r"\b(final horn|that's the game|it'?s over|"
                       r"the horn sounds)\b", re.I)

_PERIOD_OPEN = re.compile(r"^(p[123]c1|ot)$")


def _tokens(name: str) -> list[str]:
    return [w for w in name.lower().split() if len(w) > 2]


def tag_sfx(lines: list[dict], events: list[dict], label: str) -> list[dict]:
    """Mark lines with the arena sounds they earn. Returns NEW dicts (inputs
    never mutated). Budgeted: every goal horns and every penalty whistles
    (they're facts), but at most 2 crowd swells and 1 hit per beat (texture,
    not wallpaper). Callers on the phone never get arena sound."""
    out = [dict(ln) for ln in lines]
    goals = [e for e in events if e.get("type") == "goal"]
    pens = [e for e in events if e.get("type") == "penalty"]
    so_scores = [e for e in events if e.get("type") == "so" and e.get("scored")]
    gi = pi = 0
    oohs = hits = 0
    opened = False
    for ln in out:
        if ln.get("phone"):
            continue
        text = ln.get("text", "")
        low = text.lower()
        cues = []
        # period/OT open: organ + a settling crowd swell on the first line
        if not opened and _PERIOD_OPEN.match(label or ""):
            cues.append(("organ_riff", "start"))
            opened = True
        # goal calls, in event order — horn + roar as the call lands
        if gi < len(goals) and any(re.search(r"\b%s\b" % re.escape(w), low)
                                   for w in _tokens(goals[gi]["scorer"])) \
                and re.search(r"\b(scores?|goal|buries|puts it|nets|tips|"
                              r"snipes|home|lamp|in the net)\b", low):
            cues.append(("goal_horn", "end"))
            cues.append(("crowd_roar", "end"))
            gi += 1
        elif so_scores and re.search(r"\bscores?\b", low) and label == "so":
            cues.append(("crowd_roar", "end"))
            so_scores.pop(0)
        # penalty announcements — whistle leads the line
        elif pi < len(pens) and (
                any(re.search(r"\b%s\b" % re.escape(w), low)
                    for w in _tokens(pens[pi]["player"]))
                or pens[pi]["call"].lower() in low) \
                and re.search(r"\b(penalty|minutes|box|whistled|call)\b", low):
            cues.append(("whistle", "start"))
            pi += 1
        elif _FINAL_RE.search(low) and label in ("wrap", "scramble"):
            # only the beats that actually contain the horn — an interview
            # reminiscing "that's the game right there" must not re-horn
            cues.append(("period_horn", "end"))
            cues.append(("crowd_roar", "end"))
        elif _SAVE_RE.search(low) and oohs < 2:
            cues.append(("crowd_ooh", "end"))
            oohs += 1
        elif _HIT_RE.search(low) and hits < 1:
            cues.append(("boards", "start"))
            hits += 1
        if cues:
            ln["sfx"] = cues
    return out


def mix_overlays(audio, line_spans: list[tuple[int, int, dict]], sr: int):
    """Mix each tagged line's assets into the finished dialogue track.
    `line_spans` = [(start_sample, end_sample, line_dict)]. 'start' cues lead
    the line by 200ms; 'end' cues land 250ms before the line ends, so the
    horn erupts as the call peaks. Everything clips-safe: the caller applies
    the final np.clip."""
    for start, end, ln in line_spans:
        for name, where in ln.get("sfx", ()):
            a = asset(name, sr) * (10 ** (GAIN_DB[name] / 20))
            at = max(0, (start - int(0.2 * sr)) if where == "start"
                     else (end - int(0.25 * sr)))
            seg = a[: max(0, len(audio) - at)]
            audio[at:at + len(seg)] += seg
    return audio


if __name__ == "__main__":
    import sys
    import wave as _w
    if len(sys.argv) >= 3 and sys.argv[1] == "bed":
        sr = 24000
        x = crowd_bed(sr)
        np = _np()
        pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
        with _w.open(sys.argv[2], "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())
        print(f"wrote {sys.argv[2]} ({len(x)/sr:.1f}s crowd bed)")
    else:
        print("usage: python -m src.sfx bed <out.wav>")
