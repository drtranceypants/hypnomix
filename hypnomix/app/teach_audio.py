"""'Hear it' demos for teacher mode: short A/B examples made on the spot, so a lesson can let you hear the thing it explains.

Nothing is shipped: every example is synthesised here with numpy (and hypnomix's own DSP, hypnomix/core/dsp.py) from a few
built-in sources: the lesson drum beat (teacher.beat), a plucked chord pattern, a bass line, a sung-like vowel with vibrato,
bursts of noise for S sounds, and pink noise. Each demo has variants ("a", "b", or named ones) and renders deterministically
(seeded), at most 8 seconds, 44.1 kHz, 16 bit, never clipping. Variants of one demo are level-matched by loudness unless
loudness is the point of the demo (`match="none"`), then they only share one safety gain, so their differences stay true.

Route: GET /api/teach/hear?demo=ID&v=a  → a WAV. Renders are cached in ~/.hypnomix/cache/teach (diskcare tidies it).
"""
import io
import math
import os
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

from hypnomix.core import dsp

SR = 44100
SECONDS = 8.0
BPM = 128                          # 4 bars of 4 beats = 7.5 s
VERSION = 3                        # bump when a demo changes: the cache file names carry it
TARGET_LUFS = -20.0                # where matched variants sit
PEAK = 0.891                       # -1 dBFS: nothing leaves above this


# ---------------------------------------------------------------- sources
def _rng(seed):
    return np.random.default_rng(seed)


def _t(n):
    return np.arange(n) / SR


def _mono(y):
    return y.reshape(-1, 1)


def _st(y):
    y = np.asarray(y)
    if y.ndim == 1:
        y = y[:, None]
    return dsp.stereo(y)


def _fit(y, n):
    y = _st(y)
    return y[:n] if len(y) >= n else np.vstack([y, np.zeros((n - len(y), 2))])


def _env(n, attack=0.005, release=0.05):
    a, r = max(1, int(attack * SR)), max(1, int(release * SR))
    e = np.ones(n)
    a, r = min(a, n // 2), min(r, n // 2)
    e[:a] = np.linspace(0, 1, a)
    e[n - r:] *= np.linspace(1, 0, r)
    return e


def _place(out, x, start, gain=1.0, pan=0.0):
    """Mix mono `x` into stereo `out` at sample `start` (equal-power pan, -1 … 1)."""
    s = int(start)
    if s >= len(out) or s < 0:
        return
    th = (pan + 1) * math.pi / 4
    x = x[: len(out) - s]
    out[s:s + len(x), 0] += x * gain * math.cos(th)
    out[s:s + len(x), 1] += x * gain * math.sin(th)


def pink(n, seed=1):
    """Pink noise (-3 dB per octave), unit-ish level."""
    w = _rng(seed).standard_normal(n)
    f = np.fft.rfft(w)
    k = np.arange(len(f), dtype=float)
    k[0] = 1
    f /= np.sqrt(k)
    y = np.fft.irfft(f, n)
    return y / (np.std(y) + 1e-12)


def kick(dur=0.28, f0=125.0, f1=48.0):
    n = int(dur * SR)
    t = _t(n)
    f = f1 + (f0 - f1) * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t * 11) * _env(n, 0.001, 0.01)


def snare(dur=0.2, seed=2):
    n = int(dur * SR)
    t = _t(n)
    noise = dsp.filt(_mono(_rng(seed).standard_normal(n)), dsp.highpass(1500, SR, 2))[:, 0]
    return (noise * np.exp(-t * 22) * 0.8 + np.sin(2 * np.pi * 190 * t) * np.exp(-t * 28) * 0.6) * _env(n, 0.0005, 0.01)


def hat(dur=0.06, seed=3, open_=False):
    n = int((0.25 if open_ else dur) * SR)
    t = _t(n)
    noise = dsp.filt(_mono(_rng(seed).standard_normal(n)), dsp.highpass(7000, SR, 2))[:, 0]
    return noise * np.exp(-t * (14 if open_ else 70)) * _env(n, 0.0005, 0.005)


def drums(bars=4, bpm=BPM, seed=7, jitter_ms=0.0, flat=False, jseed=11):
    """The lesson's drum beat (teacher.beat) played on synthesised drums -> stereo. `jitter_ms` moves each hit by a random
    amount (a looser player); `flat` makes every hit the same strength (a rigid machine)."""
    from hypnomix.app.teacher import beat
    n = int(bars * 4 * 60 / bpm * SR) + int(0.4 * SR)
    out = np.zeros((n, 2))
    jr = _rng(jseed)
    for pitch, start, _, vel in beat(bars, seed=seed):
        v = 1.0 if flat else vel / 127.0
        s = start * 60 / bpm * SR + (jr.normal(0, jitter_ms) / 1000 * SR if jitter_ms else 0)
        if pitch == 36:
            _place(out, kick(), s, 0.9 * v)
        elif pitch == 38:
            _place(out, snare(), s, 0.7 * v, 0.05)
        else:
            _place(out, hat(seed=int(start * 8) + 3), s, 0.28 * v, 0.25)
    return out


@lru_cache(maxsize=256)
def pluck(freq, dur=0.9, seed=5, bright=0.55):
    """A plucked string (Karplus-Strong) at `freq`."""
    n = int(dur * SR)
    p = max(2, int(round(SR / freq)))
    buf = (_rng(seed + int(freq)).uniform(-1, 1, p)) * 1.0
    out = np.empty(n)
    k = 0
    decay = 0.996 - 0.0005 * (freq / 440)
    for i in range(n):
        out[i] = buf[k]
        nxt = (buf[k] + buf[(k + 1) % p]) * 0.5 * decay if bright < 1 else buf[k]
        buf[k] = nxt
        k = (k + 1) % p
    out = out * _env(n, 0.001, 0.05)
    out.setflags(write=False)                       # shared through the cache
    return out


_CHORDS = [(220.00, 261.63, 329.63), (174.61, 220.00, 261.63), (130.81, 164.81, 196.00), (196.00, 246.94, 293.66)]   # Am F C G
_ROOTS = [55.00, 43.65, 65.41, 49.00]


def chords(bars=4, bpm=BPM, seed=5):
    """A plucked chord pattern (Am F C G, one chord per bar, an eighth-note arpeggio) -> stereo."""
    n = int(bars * 4 * 60 / bpm * SR) + int(0.8 * SR)
    out = np.zeros((n, 2))
    step = 60 / bpm / 2
    for b in range(bars):
        ch = _CHORDS[b % 4]
        for i in range(8):
            f = ch[[0, 1, 2, 1, 0, 1, 2, 1][i]]
            _place(out, pluck(f, 0.7, seed + i), (b * 8 + i) * step * SR, 0.3, -0.3 + 0.1 * (i % 5))
    return out


def pad(bars=4, bpm=BPM):
    """A sustained synth-like pad on the same chords (detuned saws, softened) -> stereo."""
    n = int(bars * 4 * 60 / bpm * SR) + int(0.4 * SR)
    t = _t(n)
    out = np.zeros((n, 2))
    for b in range(bars):
        s, e = int(b * 4 * 60 / bpm * SR), int((b + 1) * 4 * 60 / bpm * SR) + int(0.2 * SR)
        e = min(e, n)
        seg = np.zeros((e - s, 2))
        for f in _CHORDS[b % 4]:
            for side, det in ((0, 0.997), (1, 1.003)):
                tt = t[: e - s]
                w = sum(np.sin(2 * np.pi * f * det * h * tt) / h for h in range(1, 7))
                seg[:, side] += w * 0.07
        seg *= _env(len(seg), 0.05, 0.15)[:, None]
        out[s:e] += seg
    return out


def bass(bars=4, bpm=BPM, sustained=False):
    """A bass line on the chord roots (sine and harmonics) -> mono-in-stereo."""
    n = int(bars * 4 * 60 / bpm * SR) + int(0.4 * SR)
    out = np.zeros((n, 2))
    beat_s = 60 / bpm
    for b in range(bars):
        f = _ROOTS[b % 4]
        hits = [0, 1.5, 2, 3] if not sustained else [0]
        for h in hits:
            length = (0.8 if not sustained else 3.9) * beat_s if not sustained else 3.95 * beat_s
            m = int(length * SR)
            tt = _t(m)
            x = (np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(2 * np.pi * 2 * f * tt) + 0.12 * np.sin(2 * np.pi * 3 * f * tt)) * _env(m, 0.005, 0.04)
            _place(out, x, (b * 4 + h) * beat_s * SR, 0.45)
    return out


_VOWEL_A = ((700, 1.0), (1220, 0.55), (2600, 0.25))        # the formants of a sung "ah": (Hz, strength)


def vowel(f0, dur, vib_cents=22.0, vib_hz=5.5, seed=9, attack=0.04, release=0.12):
    """A sung-like tone: a harmonic series shaped by vowel formants, with a little vibrato -> mono array."""
    n = int(dur * SR)
    t = _t(n)
    r = _rng(seed)
    onset = np.clip((t - 0.15) / 0.3, 0, 1)                         # the vibrato grows in, as a real voice's does
    cents = vib_cents * onset * np.sin(2 * np.pi * vib_hz * t + r.uniform(0, 6.28)) + r.normal(0, 1.5, n).cumsum() * 0.02
    f = f0 * 2 ** (cents / 1200)
    ph = 2 * np.pi * np.cumsum(f) / SR
    out = np.zeros(n)
    for h in range(1, int(min(SR / 2.2, 5000) / f0) + 1):
        hz = h * f0
        gain = sum(s * math.exp(-0.5 * ((hz - c) / (c * 0.18)) ** 2) for c, s in _VOWEL_A) + 0.02
        out += gain / h ** 0.5 * np.sin(h * ph)
    return out / (np.max(np.abs(out)) + 1e-9) * 0.6 * _env(n, attack, release)


def sung_phrase(notes=((220.0, 0.5), (247.0, 0.5), (261.6, 0.5), (220.0, 1.2)), gap=0.45, seed=9):
    """Short sung notes with gaps between them (so a reverb or a delay tail has somewhere to be heard) -> stereo, ~6 s."""
    n = int(SECONDS * SR)
    out = np.zeros((n, 2))
    t = 0.25
    for i, (f, d) in enumerate(notes):
        _place(out, vowel(f, d, seed=seed + i), t * SR, 0.9)
        t += d + gap
    return out


def sibilants(seed=4, gain=1.0):
    """A burst of noise like an S: bright, short."""
    n = int(0.13 * SR)
    x = dsp.filt(_mono(_rng(seed).standard_normal(n)), dsp.butter(4, [5200, 9500], "bandpass", fs=SR, output="sos"))[:, 0]
    return x * _env(n, 0.012, 0.03) * 0.8 * gain


def music(seed=5):
    """The 'same music' the band, EQ and saturation demos use: drums, bass and a plucked chord pattern -> stereo, 7.5 s."""
    n = int(4 * 4 * 60 / BPM * SR)
    return _fit(drums(seed=7)[:n] * 0.9 + bass()[:n] * 0.9 + chords(seed=seed)[:n] * 1.2, n)


# ---------------------------------------------------------------- helpers for the demos
def _bp(y, lo, hi, order=4):
    hi = min(hi, SR * 0.45)
    return dsp.filt(y, dsp.butter(order, [lo, hi], "bandpass", fs=SR, output="sos"))


def _bell(y, f0, gain, q=1.0):
    return dsp.filt(y, dsp.peaking(f0, gain, q, SR))


def _reverb(y, decay, predelay=0.0, wet=0.3, damp=6000):
    ir = dsp.reverb_ir(SR, decay, predelay, damp, seed=3)
    w = dsp.convolve(y, ir)
    return _fit(y, len(y)) * (1 - wet * 0.5) + w * wet * 3.2


def _delay(y, ms, feedback=0.35, wet=0.4, repeats=6, filt_hz=5000):
    y = _st(y)
    d = int(ms / 1000 * SR)
    tail = np.zeros_like(y)
    cur = y
    for i in range(1, repeats + 1):
        cur = dsp.filt(cur, dsp.lowpass(filt_hz, SR, 1)) * feedback if i > 1 else cur
        if i * d >= len(y):
            break
        tail[i * d:] += cur[: len(y) - i * d] * (1.0 if i == 1 else 1.0)
    return y + tail * wet


def _lufs(y):
    v = dsp.lufs(y, SR)
    return v if v > -69 else dsp.rms_db(y) - 3


def _gain_to(y, target):
    return y * dsp.undb(target - _lufs(y))


# ---------------------------------------------------------------- the demos
# Each builder returns {variant: stereo array}. `match`: "loudness" (variants are level-matched) or "none".
def _freq_bands():
    m = music()
    edges = {"sub": (20, 60), "bass": (60, 250), "lowmid": (250, 500), "mid": (500, 2000), "presence": (2000, 6000), "air": (6000, 16000)}
    return {k: _bp(m, lo, hi) for k, (lo, hi) in edges.items()}


def _sine_pitch():
    n = int(3.0 * SR)
    t = _t(n)
    out = {}
    for k, f in (("f100", 100.0), ("f1k", 1000.0), ("f10k", 10000.0)):
        out[k] = _st(np.sin(2 * np.pi * f * t) * 0.25 * _env(n, 0.05, 0.1))
    return out


def _eq_boost():
    m = music()
    out = {"flat": m}
    for k, f in (("b250", 250), ("b1k", 1000), ("b3k", 3000), ("b8k", 8000)):
        out[k] = _bell(m, f, 9.0, 1.2)
    return out


def _low_cut():
    n = int(6.0 * SR)
    voice = np.zeros((n, 2))
    for i, (f, s, d) in enumerate(((196.0, 0.3, 1.3), (220.0, 1.8, 1.3), (247.0, 3.3, 1.3), (196.0, 4.6, 1.2))):
        _place(voice, vowel(f, d, seed=20 + i), s * SR, 0.9)
    r = _rng(31)
    rumble = dsp.filt(_mono(r.standard_normal(n)), dsp.lowpass(70, SR, 4))[:, 0]
    rumble = rumble / (np.std(rumble) + 1e-9) * 0.12 * (1 + 0.5 * np.sin(2 * np.pi * 0.7 * _t(n)))
    raw = voice + _st(rumble) * 1.0
    return {"a": raw, "b": dsp.filt(raw, dsp.highpass(110, SR, 2))}


def _comp_attack():
    d = drums(seed=7)[: int(7.5 * SR)] * 1.0 + bass()[: int(7.5 * SR)] * 0.0
    out = {}
    for k, att in (("a", 30.0), ("b", 1.0)):
        y, _ = dsp.compress(d, SR, threshold_db=-24, ratio=6.0, attack_ms=att, release_ms=90, knee_db=3)
        out[k] = y
    return out


def _pumping():
    m = pad()[: int(7.5 * SR)] * 1.0 + drums(seed=7)[: int(7.5 * SR)] * 1.2 + bass()[: int(7.5 * SR)] * 0.5
    g, _ = dsp.compress(m, SR, threshold_db=-14, ratio=1.8, attack_ms=30, release_ms=150, knee_db=6)
    h, _ = dsp.compress(m, SR, threshold_db=-40, ratio=12.0, attack_ms=1.0, release_ms=450, knee_db=2)
    return {"a": g, "b": h}


def _limiter_clip():
    m = music() * dsp.undb(12)
    soft, _ = dsp.limit(m, SR, ceiling_dbtp=-1.0, lookahead_ms=5.0, release_ms=80.0)
    hard = np.clip(m, -PEAK, PEAK)
    return {"a": hard, "b": soft}


def _reverb_length():
    p = sung_phrase()
    return {"a": _reverb(p, 0.45, 0.0, 0.35), "b": _reverb(p, 2.8, 0.0, 0.35)}


def _predelay():
    p = sung_phrase(((246.9, 0.35), (261.6, 0.35), (293.7, 0.35), (246.9, 0.9)), gap=0.3)
    return {"a": _reverb(p, 1.6, 0.0, 0.45), "b": _reverb(p, 1.6, 45.0, 0.45)}


def _delay_kinds():
    p = sung_phrase(((293.7, 0.22), (329.6, 0.22), (293.7, 0.22), (246.9, 0.6)), gap=0.85)
    beat_ms = 60000 / 100
    return {"a": _delay(p, 100, 0.0, 0.5, repeats=1), "b": _delay(p, beat_ms * 0.75, 0.5, 0.5, repeats=5)}


def _saturation():
    m = music()
    return {"a": m, "b": dsp.saturate(m * 1.6, drive_db=12.0, mix=1.0)}


def _mono_wide():
    p = pad()[: int(7.5 * SR)] * 1.5
    c = chords()[: int(7.5 * SR)]
    # widen the chord pattern: the left and right copies are delayed a little differently (as two mics, or a stereo effect would)
    d = int(0.011 * SR)
    wide = np.zeros_like(c)
    wide[:, 0] = c[:, 0] + np.roll(c[:, 1], d) * 0.5
    wide[:, 1] = c[:, 1] + np.roll(c[:, 0], 2 * d) * 0.5
    src = p + wide + drums(seed=7)[: int(7.5 * SR)] * 0.8
    mono = np.repeat(((src[:, 0] + src[:, 1]) / 2)[:, None], 2, axis=1)
    return {"a": mono, "b": src}


def _polarity():
    n = int(6.0 * SR)
    src = np.zeros((n, 2))
    for i, (f, s) in enumerate(((220.0, 0.2), (261.6, 1.7), (329.6, 3.1), (220.0, 4.4))):
        _place(src, vowel(f, 1.3, seed=40 + i), s * SR, 0.8)
    mic1 = src[:, 0]
    mic2 = dsp.filt(_mono(mic1), dsp.lowpass(9000, SR, 1))[:, 0] * 0.92          # a second mic hears nearly the same thing
    a = _st((mic1 + mic2) * 0.5)
    b = _st((mic1 - mic2) * 0.5)
    return {"a": a, "b": b}


def _bit_depth():
    c = chords(seed=8)[: int(6.0 * SR)] * 0.9
    c = dsp.filt(c, dsp.lowpass(9000, SR, 1))
    q = 2 ** 5
    lowbit = np.round(c * q) / q
    # aliasing: drop to a low sample rate by taking every 6th sample with no filter, then hold each sample
    k = 6
    held = np.repeat(c[::k], k, axis=0)[: len(c)]
    return {"clean": c, "lowbit": lowbit, "alias": held}


def _noise_floor():
    p = sung_phrase(((220.0, 0.6), (261.6, 0.6), (247.0, 0.6), (220.0, 1.4)), gap=0.5)
    r = _rng(77)
    hiss = dsp.filt(_mono(r.standard_normal(len(p))), dsp.highpass(300, SR, 1))
    hiss = _st(hiss) * dsp.undb(-62) * 1.0
    good = p * 0.5 + hiss                                                            # recorded at a healthy level
    quiet = p * 0.5 * dsp.undb(-30) + hiss                                           # recorded 30 dB too low, same noise
    return {"a": good, "b": quiet * dsp.undb(30)}                                    # ... then turned up


def _fade_click():
    n = int(6.0 * SR)
    seg = int(0.5 * SR)
    r = _rng(5)
    base = []
    t = _t(seg)
    for f in (110.0, 146.8, 123.5, 98.0):
        base.append((np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * 2 * f * t) + 0.25 * np.sin(2 * np.pi * 3 * f * t)) * 0.4)
    hard, soft = [], []
    cf = int(0.008 * SR)
    ph = 0.0
    for i in range(12):
        f = (110.0, 146.8, 123.5, 98.0)[i % 4]
        tt = _t(seg) + r.uniform(0, 1)                                              # each clip starts at some other phase
        x = (np.sin(2 * np.pi * f * tt) + 0.5 * np.sin(2 * np.pi * 2 * f * tt) + 0.25 * np.sin(2 * np.pi * 3 * f * tt)) * 0.4
        hard.append(x)
        y = x.copy()
        y[:cf] *= np.linspace(0, 1, cf)
        y[-cf:] *= np.linspace(1, 0, cf)
        soft.append(y)
    a = np.concatenate(hard)[:n]
    b = np.concatenate(soft)[:n]
    return {"a": _st(a), "b": _st(b)}


def _interval_tune():
    n = int(5.0 * SR)
    root = 220.0
    third = root * 2 ** (4 / 12)
    out = {}
    for k, cents in (("a", 0.0), ("b", 30.0)):
        y = np.zeros((n, 2))
        _place(y, vowel(root, 4.5, vib_cents=4, seed=60), 0.2 * SR, 0.8, -0.2)
        _place(y, vowel(third * 2 ** (cents / 1200), 4.5, vib_cents=4, seed=61), 0.2 * SR, 0.8, 0.2)
        out[k] = y
    return out


def _timing_feel():
    out = {}
    n = int(7.5 * SR)
    for k, jit, flat in (("tight", 4.0, False), ("loose", 26.0, False), ("grid", 0.0, True)):
        d = drums(seed=7, jitter_ms=jit, flat=flat, jseed=21)[:n]
        g = np.zeros((n, 2))
        step = 60 / BPM / 2
        jr = _rng(23)
        for b in range(4):
            for i in range(8):
                f = _CHORDS[b % 4][[0, 1, 2, 1, 0, 1, 2, 1][i]]
                s = ((b * 8 + i) * step * SR) + (jr.normal(0, jit) / 1000 * SR if jit else 0)
                _place(g, pluck(f, 0.5, 5 + i), max(0, s), 0.25 * (1.0 if flat else 0.7 + 0.3 * jr.random()), -0.2)
        out[k] = d + g
    return out


def _loudness_bias():
    m = music()
    bright = _bell(dsp.filt(m, dsp.shelf(4000, 3.0, SR, high=True)), 3000, 2.0, 0.8)
    return {"a": m, "b": m * dsp.undb(2.0), "c": _gain_to(bright, _lufs(m))}


def _sidechain():
    n = int(7.5 * SR)
    b = bass(sustained=True)[:n] * 1.0
    k = np.zeros((n, 2))
    for beat in range(16):
        _place(k, kick(), beat * 60 / BPM * SR, 1.0)
    k = k[:n]
    ducked, _ = dsp.compress(b, SR, threshold_db=-28, ratio=10.0, attack_ms=1.0, release_ms=140, knee_db=2, sidechain=k)
    return {"a": b * 0.9 + k * 0.9, "b": ducked * 0.9 + k * 0.9}


def _deess():
    n = int(6.0 * SR)
    p = np.zeros((n, 2))
    t = 0.2
    for i, f in enumerate((220.0, 247.0, 261.6, 247.0)):
        _place(p, vowel(f, 0.5, seed=80 + i), t * SR, 0.8)
        _place(p, sibilants(seed=90 + i, gain=1.4), (t + 0.5) * SR, 0.8)
        t += 1.35
    out, _ = dsp.deess(p, SR, freq=6500, threshold_db=-34, ratio=6, max_gr_db=10)
    return {"a": p, "b": out}


def _kick_bass():
    n = int(7.5 * SR)
    k = np.zeros((n, 2))
    for beat in range(16):
        _place(k, kick(0.3, 100.0, 55.0), beat * 60 / BPM * SR, 1.0)
    b = bass(sustained=False)[:n]
    b2 = np.zeros((n, 2))
    for beat in range(16):
        m = int(0.4 * SR)
        tt = _t(m)
        x = np.sin(2 * np.pi * 55.0 * tt) * _env(m, 0.005, 0.05)
        _place(b2, x, (beat * 60 / BPM + 0.0) * SR, 0.9)
    fight = k[:n] * 0.8 + b2 * 0.9
    fixed = k[:n] * 0.8 + _bell(b2, 55.0, -9.0, 1.4) * 0.9
    fixed = dsp.filt(fixed, dsp.peaking(55.0, 0.0, 1.0, SR)) if False else fixed
    # the fix: a cut in the bass where the kick lives, and a little of the bass's upper harmonics so it still reads
    return {"a": fight, "b": fixed}


DEMOS = {
    "freq-bands": dict(title="The frequency map, band by band", build=_freq_bands, match="loudness",
                       variants=[("sub", "Sub (20-60 Hz)"), ("bass", "Bass (60-250 Hz)"), ("lowmid", "Low-mid (250-500 Hz)"),
                                 ("mid", "Mid (500 Hz-2 kHz)"), ("presence", "Presence (2-6 kHz)"), ("air", "Air (6-16 kHz)")],
                       listen="The same music through one band at a time, each set to the same loudness. Notice which band carries the thump, the body, the words and the sparkle."),
    "sine-pitch": dict(title="A sine at three pitches", build=_sine_pitch, match="loudness",
                       variants=[("f100", "100 Hz"), ("f1k", "1 kHz"), ("f10k", "10 kHz")],
                       listen="Low is a deep hum, 1 kHz the middle of the range, 10 kHz a thin whistle. Keep your volume low: the high one can seem sharper than it is."),
    "eq-boost": dict(title="An EQ boost at four frequencies", build=_eq_boost, match="loudness",
                     variants=[("flat", "No EQ"), ("b250", "+9 dB at 250 Hz"), ("b1k", "+9 dB at 1 kHz"), ("b3k", "+9 dB at 3 kHz"), ("b8k", "+9 dB at 8 kHz")],
                     listen="Same music, same loudness: 250 Hz makes it boxy and thick, 1 kHz nasal, 3 kHz sharp and forward, 8 kHz bright and hissy. A real boost is far smaller."),
    "low-cut": dict(title="A low cut on a voice", build=_low_cut, match="loudness",
                    variants=[("a", "Without the low cut"), ("b", "Low cut at 110 Hz")],
                    listen="Listen to the slow rumble under the voice in A. In B it's gone and the voice is clearer, with almost nothing lost."),
    "comp-attack": dict(title="Compression: a slow and a fast attack", build=_comp_attack, match="loudness",
                        variants=[("a", "Slow attack (30 ms)"), ("b", "Fast attack (1 ms)")],
                        listen="With the slow attack the start of each kick and snare gets through and the drums keep their punch. The fast attack grabs it and the hits go soft and flat."),
    "pumping": dict(title="Gentle compression and over-compression", build=_pumping, match="loudness",
                    variants=[("a", "Gentle"), ("b", "Over-compressed")],
                    listen="In B the chords dip every time the drums hit and swell back after: that is pumping. A is steadier and still holds together."),
    "limiter-clip": dict(title="A limiter against hard clipping", build=_limiter_clip, match="loudness",
                         variants=[("a", "Hard clipping"), ("b", "A limiter")],
                         listen="Both are pushed hard on purpose so the difference is easy to hear. The clipped one sounds fuzzy and buzzy on the hits; the limiter is smoother, though pushed this far it is working hard and starts to pump. A real master asks for far less."),
    "reverb-length": dict(title="A short and a long reverb", build=_reverb_length, match="loudness",
                          variants=[("a", "Short (0.45 s)"), ("b", "Long (2.8 s)")],
                          listen="The short reverb makes a small room: close and clear. The long one makes a hall, and the notes wash into each other."),
    "predelay": dict(title="Pre-delay off and on", build=_predelay, match="loudness",
                     variants=[("a", "No pre-delay"), ("b", "45 ms pre-delay")],
                     listen="With none the reverb sits on top of each note and the voice sounds further away. With a little pre-delay the note comes first, then the space: clearer and closer."),
    "delay-kinds": dict(title="A slap delay and a tempo-synced delay", build=_delay_kinds, match="loudness",
                        variants=[("a", "Slap (100 ms)"), ("b", "Tempo-synced (dotted eighth at 100 BPM)")],
                        listen="The slap is one quick echo that thickens the voice. The synced delay is set to a dotted eighth at 100 BPM (450 ms) and repeats a few times: in a song at that tempo the echoes would fall in the beat's own rhythm."),
    "saturation": dict(title="Clean and saturated", build=_saturation, match="loudness",
                       variants=[("a", "Clean"), ("b", "Saturated")],
                       listen="At the same loudness, the saturated one is thicker and has more bite, because it has added harmonics. Too much turns into fuzz."),
    "mono-wide": dict(title="Mono against wide", build=_mono_wide, match="loudness",
                      variants=[("a", "Mono"), ("b", "Wide stereo")],
                      listen="In mono the sound sits in the middle and is narrow. Wide spreads the chords across your speakers. A mix should still work in mono."),
    "polarity": dict(title="Two mics: adding and cancelling", build=_polarity, match="none",
                     variants=[("a", "In polarity"), ("b", "One mic flipped")],
                     listen="Two mics on one voice. In A they add up and it sounds full. Flip one and B goes thin and quiet, because the mics cancel each other. Loudness is not matched on purpose."),
    "bit-depth": dict(title="Low bit depth and aliasing", build=_bit_depth, match="loudness",
                      variants=[("clean", "Clean"), ("lowbit", "Low bit depth (6 bit)"), ("alias", "Aliasing (low sample rate)")],
                      listen="Low bit depth adds a gritty noise that follows the notes. Aliasing adds false, ringing tones that were never played. Both are what you avoid with 24 bit and a good sample rate."),
    "noise-floor": dict(title="A quiet recording turned up", build=_noise_floor, match="none",
                        variants=[("a", "Recorded at a healthy level"), ("b", "Recorded too quietly, then turned up")],
                        listen="Both end up as loud as each other. In B the hiss that was always there came up with the voice. Record at a good level and you never need to."),
    "fade-click": dict(title="A cut that clicks, and one with a fade", build=_fade_click, match="none",
                       variants=[("a", "Cut with no fade"), ("b", "The same cut, 8 ms fade")],
                       listen="Listen for the little tick at each join in A. In B the same joins have a tiny fade and the ticks are gone."),
    "interval-tune": dict(title="An interval in tune and 30 cents out", build=_interval_tune, match="loudness",
                          variants=[("a", "In tune (a major third)"), ("b", "The top note 30 cents sharp")],
                          listen="In A the two notes sit together and sound settled. In B the top note is 30 cents sharp: the pair rubs, sounds rough and out of tune. 30 cents is less than a third of a semitone."),
    "timing-feel": dict(title="Tight, loose and rigidly on the grid", build=_timing_feel, match="loudness",
                        variants=[("tight", "Tight"), ("loose", "Loose"), ("grid", "Rigidly on the grid")],
                        listen="Tight is human and steady. Loose drifts and starts to sound careless. The grid is perfect and machine-like: every hit the same strength, exactly on time."),
    "loudness-bias": dict(title="Louder sounds better", build=_loudness_bias, match="none",
                          variants=[("a", "The original"), ("b", "The same, 2 dB louder"), ("c", "A brighter version, level-matched to the original")],
                          listen="B nearly always feels better, though it is only louder. C is a real change, judged fairly because it is the same loudness as A. Always match levels before you compare."),
    "sidechain": dict(title="A bass ducking under the kick", build=_sidechain, match="loudness",
                      variants=[("a", "No ducking"), ("b", "Ducked under the kick")],
                      listen="In A the bass and the kick pile up and the kick gets lost. In B the bass dips every time the kick hits, so the kick is clear and the mix pumps in time. This duck is exaggerated so you can hear it: for clarity in a real mix, 2 to 4 dB of ducking is plenty."),
    "deess": dict(title="De-essing", build=_deess, match="loudness",
                  variants=[("a", "With harsh S sounds"), ("b", "De-essed")],
                  listen="Listen to the hiss after each note in A. In B the S sounds are turned down, and the voice itself is untouched."),
    "kick-bass": dict(title="Bass and kick fighting, and with a cut", build=_kick_bass, match="loudness",
                      variants=[("a", "Fighting"), ("b", "A cut in the bass")],
                      listen="Both sit on the same low note, so in A they smear into one boom. In B a cut in the bass leaves the kick room to thump."),
}


# ---------------------------------------------------------------- rendering
def _match(variants, how):
    """Level-match the variants by loudness (or leave their levels alone), then one shared safety gain keeps every peak
    under -1 dBFS. The same gain on all of them, so a difference you hear is the demo's, not the safety's."""
    ys = {k: _st(np.nan_to_num(v)) for k, v in variants.items()}
    if how == "loudness":
        ys = {k: _gain_to(v, TARGET_LUFS) for k, v in ys.items()}
    peak = max(float(np.max(np.abs(v))) for v in ys.values())
    ref = peak
    if how == "none":                                         # keep levels: put the loudest variant at a comfortable level
        lead = max(_lufs(v) for v in ys.values())
        g = dsp.undb(TARGET_LUFS - lead)
        ys = {k: v * g for k, v in ys.items()}
        ref = peak * g
    if ref > PEAK:
        s = PEAK / ref
        ys = {k: v * s for k, v in ys.items()}
    return ys


def _seconds_ok(y):
    return y[: int(SECONDS * SR)]


def render_all(demo):
    """Every variant of a demo as 16-bit stereo arrays -> {variant: float array}."""
    d = DEMOS[demo]
    ys = _match(d["build"](), d["match"])
    return {k: _seconds_ok(v) for k, v in ys.items()}


def to_wav(y):
    """Float stereo (-1 … 1) -> the bytes of a 16-bit 44.1 kHz WAV."""
    pcm = np.round(np.clip(y, -1, 1) * 32767).astype("<i2")
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return b.getvalue()


def render(demo, variant):
    """One variant as WAV bytes. Deterministic: the same bytes every time."""
    if demo not in DEMOS:
        raise KeyError(demo)
    keys = [k for k, _ in DEMOS[demo]["variants"]]
    if variant not in keys:
        raise KeyError(variant)
    return to_wav(render_all(demo)[variant])


def cache_dir():
    """~/.hypnomix/cache/teach, read at call time like diskcare does (hypnomix/app/diskcare.py tidies it)."""
    return Path(os.environ.get("HYPNOMIX_HOME", "~/.hypnomix")).expanduser() / "cache" / "teach"


def wav(demo, variant):
    """The WAV for a demo's variant, from the cache when it is there (all variants of a demo are written together, so they
    stay level-matched with each other)."""
    keys = [k for k, _ in DEMOS[demo]["variants"]]
    if variant not in keys:
        raise KeyError(variant)
    d = cache_dir()
    f = d / f"{demo}-{variant}-v{VERSION}.wav"
    try:
        return f.read_bytes()
    except OSError:
        pass
    ys = render_all(demo)
    out = None
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        d = None
    for k, v in ys.items():
        b = to_wav(v)
        if k == variant:
            out = b
        if d is not None:
            try:
                (d / f"{demo}-{k}-v{VERSION}.wav").write_bytes(b)
            except OSError:
                pass
    return out


def catalog(demo, listen=None):
    """What the lesson page needs to show a demo: its title, the line on what to listen for, and one button per variant."""
    d = DEMOS[demo]
    return dict(demo=demo, title=d["title"], listen=listen or d["listen"], variants=[dict(v=k, label=l) for k, l in d["variants"]])
