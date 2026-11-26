"""Small, dependency-light DSP toolkit used by the engineer and studio tools.

Everything works on float64 arrays shaped (samples, channels). No GPL code: filters are RBJ
cookbook biquads, dynamics are feed-forward designs written here, loudness is pyloudnorm (MIT).
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import soundfile as sf

AUDIO_EXT = (".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".m4a")

# scipy.signal and pyloudnorm take most of a second to import, and every command (even `-h`) loads this module,
# so they are imported on first use. `dsp.butter`, `dsp.sosfilt` etc. still work for other modules (see __getattr__).
_LAZY = {"sosfilt": "scipy.signal", "butter": "scipy.signal", "resample_poly": "scipy.signal",
         "fftconvolve": "scipy.signal", "iirnotch": "scipy.signal", "tf2sos": "scipy.signal",
         "minimum_filter1d": "scipy.ndimage", "uniform_filter1d": "scipy.ndimage", "pyln": "pyloudnorm"}


def _sig():
    import scipy.signal
    return scipy.signal


def _ndi():
    import scipy.ndimage
    return scipy.ndimage


def _pyln():
    import pyloudnorm
    return pyloudnorm


def __getattr__(name):
    mod = _LAZY.get(name)
    if mod is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    m = importlib.import_module(mod)
    return m if name == "pyln" else getattr(m, name)


class AudioReadError(Exception):
    """A file could not be read as audio. The message is plain words fit to print as they are."""


# ---------------------------------------------------------------- I/O
MAX_CHANNELS = 5                       # the loudness meter (ITU-R BS.1770 weights) reads mono up to five channels


def broken_samples(y):
    """(how many samples are NaN or infinite, the frame of the first one or None). Cheap when there are none."""
    if np.isfinite(y).all():
        return 0, None
    bad = ~np.isfinite(y)
    return int(bad.sum()), int(np.flatnonzero(bad.any(axis=1) if bad.ndim > 1 else bad)[0])


FFMPEG_TIMEOUT = 1800                # a decode that takes longer than 30 minutes is stopped


def load(path, sr=None):
    """Read audio as float64 (n, ch). Resamples to `sr` if given. Falls back to ffmpeg for mp3/m4a.

    A file HypnoMix cannot measure ends in an AudioReadError with one plain sentence (the commands print it, exit 2):
    no audio in it, more than five channels, or NaN / infinite samples (a plug-in that blew up while exporting).
    A tool that must REPORT such a file instead of refusing it (scan, preflight) reads it with read() and looks itself."""
    y, file_sr = read(path)
    path = Path(path)
    if not len(y):
        raise AudioReadError(f"can't read '{path}' as audio: it has no audio in it (zero length); export it again")
    if y.shape[1] > MAX_CHANNELS:
        raise AudioReadError(f"can't read '{path}' as audio: it has {y.shape[1]} channels and HypnoMix reads up to "
                             f"{MAX_CHANNELS}; export it as stereo or mono")
    n, first = broken_samples(y)
    if n:
        t = first / file_sr
        raise AudioReadError(f"can't read '{path}' as audio: it contains {n} broken sample{'s' if n != 1 else ''} "
                             f"(NaN or infinite, the first at {int(t // 60)}:{t % 60:05.2f}); export it again "
                             "from your DAW")
    if sr and sr != file_sr:
        g = math.gcd(int(sr), int(file_sr))
        y = _sig().resample_poly(y, sr // g, file_sr // g, axis=0)
        file_sr = sr
    return y, int(file_sr)


def read(path):
    """The file as it is, float64 (n, ch) and its sample rate, with no checks on what is inside (see load)."""
    path = Path(path)
    if not path.exists():
        raise AudioReadError(f"can't read '{path}' as audio: no such file")
    if path.is_dir():
        raise AudioReadError(f"can't read '{path}' as audio: it is a folder, not a file")
    try:
        y, file_sr = sf.read(str(path), always_2d=True, dtype="float64")
    except Exception as first:
        import shutil, subprocess, tempfile
        if shutil.which("ffmpeg") is None:
            raise AudioReadError(f"can't read '{path}' as audio: not a format the built-in reader opens, "
                                 f"and ffmpeg (needed for the rest, such as mp3 and m4a) is not installed") from first
        with tempfile.TemporaryDirectory(prefix="hypnomix-work-") as td:
            tmp = Path(td) / "x.wav"
            try:
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-c:a", "pcm_f32le", str(tmp)],
                               check=True, capture_output=True, timeout=FFMPEG_TIMEOUT)
                y, file_sr = sf.read(str(tmp), always_2d=True, dtype="float64")
            except subprocess.TimeoutExpired as e:
                raise AudioReadError(f"can't read '{path}' as audio: decoding it took longer than "
                                     f"{FFMPEG_TIMEOUT // 60} minutes, so it was stopped") from e
            except Exception as e:
                raise AudioReadError(f"can't read '{path}' as audio: not an audio file HypnoMix can decode") from e
    return y, int(file_sr)


def save(path, y, sr, bits=24, dither=None):
    """Write audio. dither: None keeps the long-standing behaviour (TPDF on 16-bit, none on 24-bit);
    'tpdf', 'shaped' or 'off' choose it explicitly for any fixed-point export (16 or 24 bit)."""
    path = Path(path)
    if not np.all(np.isfinite(y)):
        bad = int(np.sum(~np.isfinite(y)))
        import sys
        print(f"warning: {bad} invalid samples (NaN/inf) zeroed while saving {path.name}", file=sys.stderr)
        y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
    path.parent.mkdir(parents=True, exist_ok=True)
    sub = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}[bits]
    if dither is not None and bits in (16, 24):
        y = quantise(y, bits, dither)
    elif bits == 16:
        y = dither_tpdf(y, 16)
    sf.write(str(path), np.clip(y, -1, 1) if bits != 32 else y, sr, subtype=sub)
    return path


def dither_tpdf(y, bits):
    lsb = 1.0 / (2 ** (bits - 1))
    rng = np.random.default_rng(0)
    return y + (rng.random(y.shape) - rng.random(y.shape)) * lsb


def quantise(y, bits, kind="tpdf", seed=None):
    """Round to `bits` (16 or 24) with dither, so the rounding error becomes a steady, signal-free hiss instead of
    distortion on quiet fades and reverb tails.

    kind: 'tpdf'   triangular dither of ±1 LSB, flat spectrum (the standard choice);
          'shaped' the same dither inside a first-order error-feedback loop: the noise is pushed up toward the top
                   octave, where hearing is least sensitive (about 3 dB less noise below 5 kHz at 44.1 kHz, more above);
          'off'    plain rounding (only for files that will be processed again at higher resolution).
    Returns floats sitting exactly on the target grid; the change is a few LSBs at most."""
    lsb = 1.0 / (2 ** (bits - 1))
    rng = np.random.default_rng(seed)
    x = np.asarray(y, float) / lsb
    if kind == "off":
        q = np.round(x)
    elif kind == "tpdf":
        q = np.round(x + rng.random(x.shape) - rng.random(x.shape))
    elif kind == "shaped":
        # error feedback with E(z) = 1 - z^-1, computed in closed form: the running sum of the output is the
        # dithered rounding of the running sum of the input, so q = diff(round(cumsum(x) + d)).
        dc = np.round(x.mean(axis=0, keepdims=True))          # keep the running sum small (precision)
        d = rng.random(x.shape) - rng.random(x.shape)
        S = np.round(np.cumsum(x - dc, axis=0) + d)
        q = np.diff(S, axis=0, prepend=np.zeros((1,) + x.shape[1:])) + dc
    else:
        raise ValueError(f"unknown dither {kind!r} (tpdf, shaped, off)")
    return np.clip(q, -(2 ** (bits - 1)), 2 ** (bits - 1) - 1) * lsb


def stereo(y):
    return np.repeat(y, 2, axis=1) if y.shape[1] == 1 else y[:, :2]


def db(x):
    return 20 * np.log10(np.maximum(np.abs(x), 1e-12))


def undb(d):
    return 10 ** (np.asarray(d) / 20)


# ---------------------------------------------------------------- metering
def lufs(y, sr):
    if len(y) < int(0.4 * sr):
        return -70.0
    v = _pyln().Meter(sr).integrated_loudness(y)
    return float(v) if np.isfinite(v) else -70.0


def true_peak(y, sr, chunk_s=20.0, pad=2048):
    """dBTP via 4x oversampling (ITU-R BS.1770 style), one stretch of `chunk_s` seconds at a time, so a long song does
    not need a copy of itself four times over in memory (3.3 GB for one master before). Each stretch is read with `pad`
    samples of extra either side and only its own part counts, so the filter's edges never make a peak: the answer is
    the whole-file one (the 4x filter reaches ten samples)."""
    if sr >= 176400 or len(y) <= int(chunk_s * sr) + 2 * pad:
        up = _sig().resample_poly(y, 4, 1, axis=0) if sr < 176400 else y
        return float(db(np.max(np.abs(up))))
    n, c = len(y), int(chunk_s * sr)
    best = 0.0
    for a in range(0, n, c):
        lo, hi = max(0, a - pad), min(n, a + c + pad)
        up = _sig().resample_poly(y[lo:hi], 4, 1, axis=0)
        best = max(best, float(np.max(np.abs(up[(a - lo) * 4:(min(n, a + c) - lo) * 4]))))
    return float(db(best))


def sample_peak(y):
    return float(db(np.max(np.abs(y))))


def rms_db(y):
    return float(10 * np.log10(np.mean(y ** 2) + 1e-20))


def block_rms_db(y, sr, block_s=0.05):
    n = max(1, int(block_s * sr))
    m = np.mean(y ** 2, axis=1) if y.ndim == 2 else y ** 2
    k = len(m) // n
    if k == 0:
        return np.array([10 * np.log10(m.mean() + 1e-20)])
    return 10 * np.log10(m[: k * n].reshape(k, n).mean(axis=1) + 1e-20)


def active_lufs(y, sr, rel_db=35, floor_db=-90):
    """Loudness only where the part is playing (skips the silence between phrases). Gated relative to
    the part's own loudest moments, so a quietly recorded clip is measured as well as a hot one.
    Returns -70.0 for silence."""
    n = int(0.4 * sr)
    if len(y) < n:
        y = np.pad(y, ((0, n - len(y)), (0, 0)))
    b = block_rms_db(y, sr, 0.4)
    if b.max() < floor_db:
        return -70.0
    keep = np.flatnonzero(b > b.max() - rel_db)
    seg = np.concatenate([y[i * n:(i + 1) * n] for i in keep])
    if len(seg) < n:
        seg = np.tile(seg, (int(np.ceil(n / max(1, len(seg)))) + 1, 1))[:n]
    v = _pyln().Meter(sr).integrated_loudness(seg)
    if not np.isfinite(v) or v < -70:                     # below the BS.1770 absolute gate: fall back to RMS
        v = rms_db(seg) - 0.7
    return float(v)


def noise_floor_db(y, sr):
    """10th percentile of 50 ms block RMS: what's left between the notes."""
    return float(np.percentile(block_rms_db(y, sr, 0.05), 10))


def band_energy(y, sr, edges, n=8192):
    m = y.mean(axis=1) if y.ndim == 2 else y
    if len(m) < n:
        m = np.pad(m, (0, n - len(m)))
    fr = np.lib.stride_tricks.sliding_window_view(m, n)[:: n // 2] * np.hanning(n)
    P = (np.abs(np.fft.rfft(fr, axis=1)) ** 2).mean(axis=0)
    f = np.fft.rfftfreq(n, 1 / sr)
    return np.array([P[(f >= lo) & (f < hi)].sum() for lo, hi in edges]), (f, P)


THIRD_OCT = [(c / 2 ** (1 / 6), c * 2 ** (1 / 6)) for c in 1000 * 2 ** (np.arange(-17, 14) / 3)]   # 20 Hz … 20 kHz


# ---------------------------------------------------------------- filters (RBJ cookbook)
def _biquad(b, a):
    b, a = np.asarray(b, float), np.asarray(a, float)
    return np.concatenate([b / a[0], a / a[0]])[None, :]


def peaking(f0, gain_db, q, sr):
    A, w = 10 ** (gain_db / 40), 2 * math.pi * f0 / sr
    al = math.sin(w) / (2 * q)
    return _biquad([1 + al * A, -2 * math.cos(w), 1 - al * A], [1 + al / A, -2 * math.cos(w), 1 - al / A])


def shelf(f0, gain_db, sr, high=False, s=1.0):
    A, w = 10 ** (gain_db / 40), 2 * math.pi * f0 / sr
    al = math.sin(w) / 2 * math.sqrt((A + 1 / A) * (1 / s - 1) + 2)
    c, sq = math.cos(w), 2 * math.sqrt(A) * al
    if high:
        b = [A * ((A + 1) + (A - 1) * c + sq), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - sq)]
        a = [(A + 1) - (A - 1) * c + sq, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - sq]
    else:
        b = [A * ((A + 1) - (A - 1) * c + sq), 2 * A * ((A - 1) - (A + 1) * c), A * ((A + 1) - (A - 1) * c - sq)]
        a = [(A + 1) + (A - 1) * c + sq, -2 * ((A - 1) + (A + 1) * c), (A + 1) + (A - 1) * c - sq]
    return _biquad(b, a)


def highpass(f0, sr, order=2):
    return _sig().butter(order, f0, "highpass", fs=sr, output="sos")


def lowpass(f0, sr, order=2):
    return _sig().butter(order, min(f0, sr * 0.45), "lowpass", fs=sr, output="sos")


def notch(f0, q, sr):
    b, a = _sig().iirnotch(f0, q, fs=sr)
    return _sig().tf2sos(b, a)


def filt(y, sos):
    return _sig().sosfilt(sos, y, axis=0)


class EQ:
    """A list of bands, written so it reads like an EQ Eight in your notes and can be rebuilt in Live."""
    def __init__(self):
        self.bands = []

    def add(self, kind, freq, gain=0.0, q=0.71, why=""):
        self.bands.append(dict(kind=kind, freq=round(float(freq), 1), gain=round(float(gain), 2), q=round(float(q), 2), why=why))
        return self

    def sos(self, sr):
        out = []
        for b in self.bands:
            k = b["kind"]
            if k == "highpass":
                out.append(highpass(b["freq"], sr, 2 if b["q"] <= 0.75 else 4))
            elif k == "lowpass":
                out.append(lowpass(b["freq"], sr))
            elif k == "bell":
                out.append(peaking(b["freq"], b["gain"], b["q"], sr))
            elif k == "lowshelf":
                out.append(shelf(b["freq"], b["gain"], sr, high=False))
            elif k == "highshelf":
                out.append(shelf(b["freq"], b["gain"], sr, high=True))
            elif k == "notch":
                out.append(notch(b["freq"], b["q"], sr))
        return np.vstack(out) if out else None

    def apply(self, y, sr):
        s = self.sos(sr)
        return filt(y, s) if s is not None else y


# ---------------------------------------------------------------- dynamics
def _smooth_db(target_db, sr, attack_ms, release_ms, block):
    """Attack/release smoothing of a gain-reduction curve (dB, <= 0) at block rate, then back to samples."""
    n = len(target_db)
    k = max(1, n // block)
    t = target_db[: k * block].reshape(k, block).min(axis=1)
    if k * block < n:
        t = np.append(t, target_db[k * block:].min())
    fs_b = sr / block
    a_att = math.exp(-1 / max(1e-6, attack_ms / 1000 * fs_b))
    a_rel = math.exp(-1 / max(1e-6, release_ms / 1000 * fs_b))
    g = np.empty_like(t)
    s = 0.0
    if t.dtype == np.float64:
        # the same arithmetic on plain Python floats (IEEE doubles, the same operations in the same order, so the
        # same bits), without numpy's per-element cost: several times faster. Other dtypes keep the loop below
        # (numpy scalars of a narrower type round at every step, so they must not be widened).
        out = []
        add = out.append
        pa, pr = ((1 - a_att) * t).tolist(), ((1 - a_rel) * t).tolist()        # the products that do not depend on s
        for x, ya, yr in zip(t.tolist(), pa, pr):
            s = a_att * s + ya if x < s else a_rel * s + yr
            add(s)
        g[:] = out
    else:
        for i, x in enumerate(t):                   # block-rate loop: ~1k iterations per second of audio
            s = a_att * s + (1 - a_att) * x if x < s else a_rel * s + (1 - a_rel) * x
            g[i] = s
    xs = (np.arange(len(g)) + 0.5) * block
    return np.interp(np.arange(n), xs, g)


def compress(y, sr, threshold_db=-18, ratio=3.0, attack_ms=10, release_ms=120, knee_db=6, makeup_db=0.0,
             sidechain=None, detector="peak", block=32):
    """Feed-forward compressor, stereo-linked. Returns (out, gain_reduction_db_curve)."""
    sc = y if sidechain is None else sidechain
    if detector == "rms":
        # running averages drift slightly negative over millions of samples of silence: clamp before the log
        lvl = 10 * np.log10(np.maximum(_ndi().uniform_filter1d(np.max(sc ** 2, axis=1), int(0.01 * sr) or 1), 0) + 1e-20)
    else:
        lvl = db(np.max(np.abs(sc), axis=1))
    over = lvl - threshold_db
    gr = np.where(over <= -knee_db / 2, 0.0,
                  np.where(over >= knee_db / 2, -(over) * (1 - 1 / ratio),
                           -((over + knee_db / 2) ** 2) / (2 * max(knee_db, 1e-6)) * (1 - 1 / ratio)))
    g = _smooth_db(gr, sr, attack_ms, release_ms, block)
    return y * undb(g + makeup_db)[:, None], g


def threshold_for_gr(y, sr, target_gr_db, ratio, attack_ms=10, release_ms=120, knee_db=6, detector="peak"):
    """Find the threshold that gives about `target_gr_db` of average gain reduction while the stem plays."""
    lvl = db(np.max(np.abs(y), axis=1))
    active = lvl > lvl.max() - 40
    lo, hi = lvl.max() - 40, lvl.max()
    for _ in range(14):
        mid = (lo + hi) / 2
        _, g = compress(y, sr, mid, ratio, attack_ms, release_ms, knee_db, detector=detector, block=256)
        avg = -np.mean(g[active]) if active.any() else 0
        if avg > target_gr_db:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def limit(y, sr, ceiling_dbtp=-1.0, lookahead_ms=5.0, release_ms=80.0):
    """Look-ahead brickwall limiter on true peaks (4x oversampled detection). Returns (out, gr_db)."""
    L = max(1, int(lookahead_ms / 1000 * sr))
    ceil = undb(ceiling_dbtp - 0.15)                               # small margin for inter-sample peaks
    up = np.max(np.abs(_sig().resample_poly(y, 4, 1, axis=0)), axis=1)
    pk = up[: (len(up) // 4) * 4].reshape(-1, 4).max(axis=1)
    pk = np.pad(pk, (0, len(y) - len(pk)), mode="edge") if len(pk) < len(y) else pk[: len(y)]
    pk = np.maximum(pk, np.max(np.abs(y), axis=1))
    req = db(np.minimum(1.0, ceil / np.maximum(pk, 1e-12)))      # dB gain needed per sample (<= 0)
    # h[k] = min(req[k … k+L]): forward-looking hold, so the gain is already down when the peak arrives
    h = _ndi().minimum_filter1d(req, size=L + 1, origin=-(L // 2) if L > 1 else 0, mode="nearest")
    # release: gain may rise by at most r dB per sample  ->  g[n] = min_k (h[k] + r (n-k))
    r = 20 * math.log10(math.e) / max(1, release_ms / 1000 * sr) * 1.0
    idx = np.arange(len(h))
    g = r * idx + np.minimum.accumulate(h - r * idx)
    g = np.minimum(g, 0.0)
    # trailing average over L+1 samples keeps g <= req (every window value is <= req at its end)
    c = np.cumsum(np.concatenate([[0.0], g]))
    lo = np.maximum(0, idx - L)
    g = (c[idx + 1] - c[lo]) / (idx + 1 - lo)
    out = y * undb(g)[:, None]
    # safety: anything still over the ceiling (rare inter-sample case) is trimmed by a final gain step
    tp = true_peak(out, sr)
    if tp > ceiling_dbtp:
        out *= undb(ceiling_dbtp - tp - 0.02)
    return out, g


def deess(y, sr, freq=6500, threshold_db=-30, ratio=4, max_gr_db=8):
    """Split-band de-esser: compresses only the band above `freq`, triggered by 5–10 kHz energy.

    The high band is split off with a zero-phase filter, so `y - hp` really is the rest of the sound and turning
    `hp` down can only turn the S band down. (With an ordinary filter the two halves are out of phase around the
    crossover and the "de-essed" band came out up to 3-4 dB LOUDER.)"""
    from scipy.signal import sosfiltfilt
    hp = sosfiltfilt(highpass(freq * 0.75, sr, 4), y, axis=0)
    sc = filt(y, _sig().butter(4, [freq * 0.8, min(freq * 1.6, sr * 0.45)], "bandpass", fs=sr, output="sos"))
    _, g = compress(hp, sr, threshold_db, ratio, 1, 60, 4, sidechain=sc, block=16)
    g = np.maximum(g, -max_gr_db)
    return (y - hp) + hp * undb(g)[:, None], g


def saturate(y, drive_db=3.0, mix=1.0):
    """tanh soft saturation, level-compensated. Adds harmonics that help small speakers hear bass."""
    d = undb(drive_db)
    wet = np.tanh(y * d) / np.tanh(d)
    return y * (1 - mix) + wet * mix


# ---------------------------------------------------------------- space
def reverb_ir(sr, decay_s=1.8, predelay_ms=20, damp_hz=6000, seed=1):
    """Stereo algorithmic-style IR: decorrelated noise, exponential decay, darker as it decays."""
    n = int(sr * decay_s * 1.2)
    rng = np.random.default_rng(seed)
    t = np.arange(n) / sr
    env = np.exp(-6.9 * t / decay_s)                                # -60 dB at decay_s
    ir = rng.standard_normal((n, 2)) * env[:, None]
    ir = filt(ir, lowpass(damp_hz, sr, 1))
    ir = filt(ir, highpass(180, sr, 2))
    ir[: int(0.004 * sr)] *= np.linspace(0, 1, int(0.004 * sr))[:, None]
    ir = np.concatenate([np.zeros((int(predelay_ms / 1000 * sr), 2)), ir])
    return ir / np.sqrt((ir ** 2).sum(axis=0, keepdims=True))


def convolve(y, ir):
    y = stereo(y)
    out = np.stack([_sig().fftconvolve(y[:, c], ir[:, c])[: len(y)] for c in range(2)], axis=1)
    return out


# ---------------------------------------------------------------- stereo
def pan(y, p):
    """Equal-power pan of mono (or balance of stereo), p in -1 … 1."""
    th = (p + 1) * math.pi / 4
    if y.shape[1] == 1:
        return np.hstack([y * math.cos(th), y * math.sin(th)])
    gl, gr = math.cos(th) * math.sqrt(2), math.sin(th) * math.sqrt(2)
    return np.hstack([y[:, :1] * min(1, gl), y[:, 1:2] * min(1, gr)])


def mono_below(y, sr, freq=120):
    """Make everything below `freq` mono (tight, centred low end that survives vinyl, clubs and phones)."""
    if y.shape[1] < 2:
        return y
    from scipy.signal import sosfiltfilt
    lp = sosfiltfilt(lowpass(freq, sr, 2), y, axis=0)          # zero-phase, so the cancellation is exact
    side_lo = (lp[:, 0] - lp[:, 1]) / 2
    out = y.copy()
    out[:, 0] -= side_lo
    out[:, 1] += side_lo
    return out


def width(y, amount=1.0):
    if y.shape[1] < 2:
        return y
    m, s = (y[:, 0] + y[:, 1]) / 2, (y[:, 0] - y[:, 1]) / 2 * amount
    return np.stack([m + s, m - s], axis=1)


def correlation(y, sr=None, below=None):
    if y.shape[1] < 2:
        return 1.0
    if below and sr:
        y = filt(y, lowpass(below, sr, 4))
    a, b = y[:, 0], y[:, 1]
    if np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return 1.0
    return float(np.corrcoef(a, b)[0, 1])


# ---------------------------------------------------------------- matching EQ
def matching_fir(src, ref, sr, max_db=3.0, smooth_oct=1 / 2, ntaps=4097):
    """Linear-phase FIR that nudges src's tonal balance toward ref's (loudness removed, moves capped)."""
    from scipy.signal import firwin2
    _, (f, Ps) = band_energy(src, sr, [(20, 20000)])
    _, (_, Pr) = band_energy(ref, sr, [(20, 20000)])
    band = (f > 20) & (f < 20000)
    Ps, Pr = Ps / Ps[band].sum(), Pr / Pr[band].sum()
    diff = 10 * np.log10((Pr + 1e-20) / (Ps + 1e-20))
    # smooth on a log-frequency axis
    lf = np.log2(np.maximum(f, 1))
    sm = np.zeros_like(diff)
    for i in np.flatnonzero(band):
        w = np.abs(lf - lf[i]) <= smooth_oct / 2
        sm[i] = np.mean(diff[w & band])
    sm = np.clip(sm - np.median(sm[(f > 200) & (f < 5000)]), -max_db, max_db)
    sm[~band] = sm[band][0] * (f[~band] < 20) + sm[band][-1] * (f[~band] >= 20000)
    pts = np.unique(np.concatenate([[0], np.geomspace(20, sr / 2 * 0.999, 200), [sr / 2]]))
    gains = undb(np.interp(pts, f, sm))
    return firwin2(ntaps, pts, gains, fs=sr), (f, sm)


def apply_fir(y, h):
    d = (len(h) - 1) // 2
    return np.stack([_sig().fftconvolve(y[:, c], h)[d:d + len(y)] for c in range(y.shape[1])], axis=1)
