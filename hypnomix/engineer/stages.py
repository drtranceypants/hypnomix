"""Optional mastering stages used by `hypnomix master` (all off unless asked for). Free DSP written here.

  stabilize    dynamic EQ toward a tonal target (`hypnomix tonal`): per band a slow gain that only moves when the
               band leaves the target range, with max cut / boost and a speed
  dyneq        manual dynamic EQ bands: a bell that turns down only while its band is above a threshold
  harsh        finds sustained 2-6 kHz build-ups relative to the neighbouring bands and turns down only those moments
  width_bands  mid/side width per frequency range (e.g. narrower lows, wider highs); mono content is never touched
  clipper      for the limiter modes: 'punch' (oversampled hard clip of the tallest transients before the limiter, so
               the limiter does at most N dB) and 'loud' (soft clip into the limiter: denser, louder, more colour)

The spectral stages share one engine: a short-time Fourier transform with square-root Hann windows at 75 % overlap.
With every gain at 0 dB it reconstructs the input to rounding error, so a stage that finds nothing changes nothing.
Every stage returns (audio, report) where report holds numbers for the notes and a plain-words line.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.signal import resample_poly

from hypnomix.core import dsp

N_FFT, HOP = 2048, 512


# ---------------------------------------------------------------- STFT engine
class Spectral:
    """Chunked STFT with perfect reconstruction (sqrt-Hann, hop N/4). Memory stays small on whole songs."""

    def __init__(self, y, sr, n=N_FFT, hop=HOP, chunk=1024):
        self.y = dsp.stereo(np.asarray(y, float)) if y.ndim == 2 else np.asarray(y, float)[:, None]
        self.sr, self.n, self.hop, self.chunk = sr, n, hop, chunk
        self.len = len(self.y)
        pad_end = n + (-(self.len + n) % hop)
        self.yp = np.pad(self.y, ((n, pad_end), (0, 0)))
        self.F = (len(self.yp) - n) // hop + 1
        self.win = np.sqrt(0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / n))
        self.f = np.fft.rfftfreq(n, 1 / sr)
        self.fps = sr / hop
        self.times = (np.arange(self.F) * hop + n / 2 - n) / sr          # centre of each frame, s

    def _frames(self, a, b):
        idx = (np.arange(a, b) * self.hop)[:, None] + np.arange(self.n)[None, :]
        fr = self.yp[idx] * self.win[None, :, None]                      # (frames, n, ch)
        return np.fft.rfft(fr, axis=1)

    def band_db(self, W):
        """Band level per frame (RMS dBFS of the band-limited signal): W is (bins, bands) of power weights."""
        out = np.empty((self.F, W.shape[1]))
        for a in range(0, self.F, self.chunk):
            b = min(self.F, a + self.chunk)
            X = self._frames(a, b)
            P = (np.abs(X) ** 2).mean(axis=2)                            # channels averaged
            out[a:b] = 10 * np.log10(4 / self.n ** 2 * (P @ W) + 1e-20)
        return out

    def apply(self, fn):
        """fn(a, b, X) -> X' for frames a..b (X shaped frames, bins, ch). Returns the resynthesised audio."""
        ch = self.y.shape[1]
        out = np.zeros_like(self.yp)
        q = self.n // self.hop
        for a in range(0, self.F, self.chunk):
            b = min(self.F, a + self.chunk)
            X = fn(a, b, self._frames(a, b))
            fr = np.fft.irfft(X, n=self.n, axis=1) * self.win[None, :, None]
            for j in range(q):
                seg = fr[:, j * self.hop:(j + 1) * self.hop, :].reshape(-1, ch)
                s0 = (a + j) * self.hop
                out[s0:s0 + len(seg)] += seg
        norm = (self.win ** 2).sum() / self.hop                         # = 2 for sqrt-Hann at hop n/4
        return out[self.n:self.n + self.len] / norm


def _smooth(g, fps, attack_ms, release_ms):
    """Attack/release on frame-rate dB gains (any sign): attack when the gain moves away from 0 dB."""
    g = np.asarray(g, float)
    aa = math.exp(-1 / max(1e-6, attack_ms / 1000 * fps))
    ar = math.exp(-1 / max(1e-6, release_ms / 1000 * fps))
    out = np.empty_like(g)
    s = np.zeros(g.shape[1:])
    for i in range(len(g)):
        x = g[i]
        away = np.abs(x) > np.abs(s)
        c = np.where(away, aa, ar)
        s = c * s + (1 - c) * x
        out[i] = s
    return out


def _bell_power(f, f0, q):
    """Power response of a constant-peak band-pass at f0 (1 at f0): the band a dynamic bell listens to and moves."""
    ff = np.maximum(f, 1e-3)
    return 1 / (1 + q ** 2 * (ff / f0 - f0 / ff) ** 2)


def _interp_matrix(f, centres):
    """(bands, bins) weights so gains at band centres become a smooth gain curve (linear in log-frequency)."""
    lf = np.log2(np.maximum(f, 1.0))
    lc = np.log2(np.asarray(centres, float))
    M = np.zeros((len(centres), len(f)))
    for i in range(len(centres)):
        e = np.zeros(len(centres))
        e[i] = 1
        M[i] = np.interp(lf, lc, e)
    return M


def _rect(f, lo, hi):
    return ((f >= lo) & (f < hi)).astype(float)


def _active(level_db, below=30.0):
    """Frames where the music is playing: within `below` dB of the loud part (95th percentile)."""
    return level_db > np.percentile(level_db, 95) - below


# ---------------------------------------------------------------- parsing
def parse_dyneq(spec):
    """'freq:thresh:ratio:q[:range],…' -> list of dicts. thresh is the band's RMS level in dBFS."""
    bands = []
    for part in [p for p in str(spec).split(",") if p.strip()]:
        v = [x.strip() for x in part.split(":")]
        if len(v) < 2:
            raise ValueError(f"dyneq band {part!r}: need at least freq:thresh (freq:thresh:ratio:q[:range])")
        f0 = float(v[0].lower().replace("k", "")) * (1000 if "k" in v[0].lower() else 1)
        bands.append(dict(freq=f0, thresh=float(v[1]), ratio=float(v[2]) if len(v) > 2 and v[2] else 2.0,
                          q=float(v[3]) if len(v) > 3 and v[3] else 1.5, range=float(v[4]) if len(v) > 4 and v[4] else 6.0))
    return bands


def parse_width_bands(spec):
    """'lo:hi:amount,…' -> list of dicts (amount = side level, 1 = unchanged, 0 = mono, 1.2 = 20 % wider)."""
    out = []
    for part in [p for p in str(spec).split(",") if p.strip()]:
        v = [x.strip() for x in part.split(":")]
        if len(v) != 3:
            raise ValueError(f"width band {part!r}: use lo:hi:amount, e.g. 4000:16000:1.2")
        hz = lambda s: float(s.lower().replace("k", "")) * (1000 if "k" in s.lower() else 1)
        out.append(dict(lo=hz(v[0]), hi=hz(v[1]), amount=float(v[2])))
    return out


# ---------------------------------------------------------------- dynamic EQ (manual bands)
def dyneq(y, sr, bands, attack_ms=10.0, release_ms=150.0, knee_db=3.0, amount=1.0):
    """Each band: a bell at freq/q that turns down by (level - thresh) × (1 - 1/ratio), at most `range` dB,
    only while the band's level is above thresh. Below the threshold the audio passes untouched."""
    sp = Spectral(y, sr)
    W = np.stack([_bell_power(sp.f, b["freq"], b["q"]) for b in bands], axis=1)
    lvl = sp.band_db(W)
    gr = np.zeros_like(lvl)
    for i, b in enumerate(bands):
        over = lvl[:, i] - b["thresh"]
        slope = 1 - 1 / max(b["ratio"], 1.0)
        g = np.where(over <= -knee_db / 2, 0.0, np.where(over >= knee_db / 2, -over * slope,
                     -((over + knee_db / 2) ** 2) / (2 * knee_db) * slope))
        gr[:, i] = np.maximum(g, -b["range"]) * amount
    gr = _smooth(gr, sp.fps, attack_ms, release_ms)
    S = W.T                                                         # gain shape per band = its listening band
    out = sp.apply(lambda a, b_, X: X * dsp.undb(gr[a:b_] @ S)[:, :, None])
    rep = []
    for i, b in enumerate(bands):
        act = gr[:, i] < -0.1
        rep.append(dict(freq=b["freq"], thresh=b["thresh"], ratio=b["ratio"], q=b["q"], range=b["range"],
                        pct_active=round(float(act.mean() * 100), 1),
                        avg_cut_db=round(float(-gr[act, i].mean()) if act.any() else 0.0, 2),
                        max_cut_db=round(max(0.0, float(-gr[:, i].min())), 2),
                        level_p95_db=round(float(np.percentile(lvl[:, i], 95)), 1)))
    return out, dict(bands=rep, gain_db=gr, times=sp.times)


# ---------------------------------------------------------------- tonal stabilizer
def stabilize(y, sr, target, kind="eight", max_cut=3.0, max_boost=2.0, speed_s=2.0, window_s=3.0,
              strength=1.0, toward="edge", amount=1.0):
    """Per band, a slow gain that moves the band toward the tonal target only while it is outside the range.

    The band's short-term level (over `window_s`) is lined up the same way the target is (250 Hz-4 kHz average);
    inside the range the gain rests at 0 dB. Outside, it moves `strength` of the way to the range edge (or the
    average), within -max_cut … +max_boost dB, with a time constant of `speed_s` seconds."""
    from hypnomix.ears import tonal
    bands = target[kind]
    sp = Spectral(y, sr)
    W = np.stack([_rect(sp.f, b["lo_hz"], min(b["hi_hz"], sr / 2)) for b in bands], axis=1)
    lvl = sp.band_db(W)
    from scipy.ndimage import uniform_filter1d
    P = uniform_filter1d(10 ** (lvl / 10), max(1, int(window_s * sp.fps)), axis=0, mode="nearest")
    L = 10 * np.log10(P + 1e-20)
    centres = np.array([b["centre_hz"] for b in bands])
    rel = np.stack([tonal.normalise(row, centres) for row in L])
    lo = np.array([b["low_db"] for b in bands])
    hi = np.array([b["high_db"] for b in bands])
    mean = np.array([b["mean_db"] for b in bands])
    goal_hi = mean if toward == "mean" else hi
    goal_lo = mean if toward == "mean" else lo
    want = np.where(rel > hi, -(rel - goal_hi), np.where(rel < lo, goal_lo - rel, 0.0)) * strength
    want = np.clip(want, -max_cut, max_boost) * amount
    total = 10 * np.log10(P.sum(axis=1) + 1e-20)
    want[~_active(total)] = 0.0                                     # silence and fades are left alone
    # the speed: a symmetric one-pole with time constant speed_s
    g = _smooth(want, sp.fps, speed_s * 1000, speed_s * 1000)
    M = _interp_matrix(sp.f, centres)
    out = sp.apply(lambda a, b_, X: X * dsp.undb(g[a:b_] @ M)[:, :, None])
    rep = []
    for i, b in enumerate(bands):
        act = np.abs(g[:, i]) > 0.1
        rep.append(dict(band=b["name"], pct_active=round(float(act.mean() * 100), 1),
                        avg_db=round(float(g[act, i].mean()) if act.any() else 0.0, 2),
                        min_db=round(float(g[:, i].min()), 2), max_db=round(float(g[:, i].max()), 2)))
    return out, dict(bands=rep, gain_db=g, times=sp.times)


# ---------------------------------------------------------------- harshness
HARSH_CENTRES = [float(c) for c in 1000 * 2 ** (np.arange(-3, 14) / 3)]   # 500 Hz … 20 kHz, 1/3-octave grid


def harsh_detect(y, sr, lo=2000.0, hi=6000.0, thresh_db=6.0, min_s=0.25, smooth_s=0.3):
    """Sustained build-ups in lo…hi. Each 2/3-octave band (centred on the 1/3-octave grid) is compared with the
    bands an octave below and above (their average in dB: the local slope of the spectrum), and that difference is
    judged against the song's own usual value, so a song that is simply bright is not 'harsh' everywhere (that is
    a tone choice, for EQ or `tonal`). Only loud moments count: the mix within 15 dB of its loud part and the band
    above its own median level. Returns (dB over the threshold, frames × bands; info)."""
    from scipy.ndimage import uniform_filter1d
    sp = Spectral(y, sr)
    cs = np.array(HARSH_CENTRES)
    W = np.stack([_rect(sp.f, c / 2 ** (1 / 6), min(c * 2 ** (1 / 6), sr / 2)) for c in cs], axis=1)
    P = 10 ** (sp.band_db(W) / 10)
    P = uniform_filter1d(P, max(1, int(smooth_s * sp.fps)), axis=0)
    total = 10 * np.log10(P.sum(axis=1) + 1e-20)
    loud = total > np.percentile(total, 95) - 15
    sel = [i for i, c in enumerate(cs) if lo <= c <= hi and i - 5 >= 0 and i + 6 <= len(cs)]
    ex = np.zeros((sp.F, len(sel)))
    lv = lambda a, b: 10 * np.log10(P[:, a:b].mean(axis=1) + 1e-20)
    for j, i in enumerate(sel):
        band = lv(i - 1, i + 2)
        e = band - 0.5 * (lv(i - 5, i - 2) + lv(i + 3, i + 6))
        act = loud & (band > np.median(band))
        base = np.median(e[act]) if act.any() else 0.0
        ex[:, j] = np.where(act, e - base - thresh_db, 0.0)
    over = np.maximum(ex, 0.0)
    keep = np.zeros_like(over, bool)                     # sustained: only runs longer than min_s count
    need = max(1, int(min_s * sp.fps))
    for j in range(over.shape[1]):
        d = np.diff(np.concatenate([[0], (over[:, j] > 0).astype(int), [0]]))
        for s0, e0 in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
            if e0 - s0 >= need:
                keep[s0:e0, j] = True
    over = np.where(keep, over, 0.0)
    return over, dict(sp=sp, centres=cs[sel], times=sp.times, thresh=thresh_db)


def harsh_events(over, info, merge_s=0.3):
    """Time ranges with the band, peak excess and length, loudest first."""
    t = info["times"]
    any_on = over.max(axis=1) > 0
    d = np.diff(np.concatenate([[0], any_on.astype(int), [0]]))
    ev = []
    for s, e in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
        if ev and t[s] - ev[-1]["end_s"] < merge_s:
            ev[-1]["end_s"] = float(t[e - 1])
            ev[-1]["_rng"].append((s, e))
            continue
        ev.append(dict(start_s=float(t[s]), end_s=float(t[e - 1]), _rng=[(s, e)]))
    for x in ev:
        seg = np.concatenate([over[s:e] for s, e in x.pop("_rng")])
        j = int(np.argmax(seg.max(axis=0)))
        x.update(freq_hz=round(float(info["centres"][j])), peak_db=round(float(seg.max()), 1),
                 above_usual_db=round(float(seg.max()) + info.get("thresh", 0.0), 1),
                 length_s=round(x["end_s"] - x["start_s"] + 1 / info["sp"].fps, 2))
        x["start_s"], x["end_s"] = round(x["start_s"], 2), round(x["end_s"], 2)
    return sorted(ev, key=lambda x: -x["peak_db"])


def harsh(y, sr, lo=2000.0, hi=6000.0, thresh_db=6.0, depth=0.7, max_cut=4.0, attack_ms=20.0, release_ms=200.0,
          min_s=0.25, amount=1.0):
    """Turn down only the harsh moments: cut = depth × (excess over threshold), at most max_cut dB, as a
    2/3-octave bell on the band that built up."""
    over, info = harsh_detect(y, sr, lo, hi, thresh_db, min_s)
    sp = info["sp"]
    g = -np.minimum(over * depth, max_cut) * amount
    g = _smooth(g, sp.fps, attack_ms, release_ms)
    S = np.stack([_bell_power(sp.f, c, 2.1) for c in info["centres"]], axis=0)
    out = sp.apply(lambda a, b_, X: X * dsp.undb(np.maximum(g[a:b_] @ S, -max_cut))[:, :, None])
    ev = harsh_events(over, info)
    act = g.min(axis=1) < -0.1
    return out, dict(events=ev, pct_active=round(float(act.mean() * 100), 1),
                     max_cut_db=round(max(0.0, float(-g.min())) if g.size else 0.0, 2),
                     avg_cut_db=round(float(-g.min(axis=1)[act].mean()) if act.any() else 0.0, 2))


# ---------------------------------------------------------------- multiband width
def width_bands(y, sr, bands, xfade_oct=1 / 6, amount=1.0):
    """Side level per frequency range. Bands crossfade over `xfade_oct` octaves at their edges. Only the side
    (L-R) signal is scaled, so anything mono (L = R) comes out exactly as it went in."""
    y = dsp.stereo(y)
    sp = Spectral(y, sr)
    lf = np.log2(np.maximum(sp.f, 1.0))
    w = np.ones_like(sp.f)
    for b in bands:
        a = 1 + (b["amount"] - 1) * amount
        lo, hi = np.log2(max(b["lo"], 1.0)), np.log2(b["hi"])
        h = xfade_oct / 2
        ramp = np.clip((lf - (lo - h)) / (2 * h), 0, 1) * np.clip(((hi + h) - lf) / (2 * h), 0, 1)
        w = w * (1 + (a - 1) * ramp)

    def fn(a_, b_, X):
        M, S = (X[:, :, 0] + X[:, :, 1]) / 2, (X[:, :, 0] - X[:, :, 1]) / 2 * w[None, :]
        return np.stack([M + S, M - S], axis=2)
    out = sp.apply(fn)
    return out, dict(bands=[dict(b, applied=round(1 + (b["amount"] - 1) * amount, 3)) for b in bands])


# ---------------------------------------------------------------- clippers (limiter modes)
def _os_map(x, fn, factor=4, chunk_s=10.0, sr=44100):
    """Apply a sample-wise curve at `factor`× oversampling, in chunks (keeps memory small on whole songs)."""
    n, pad = int(chunk_s * sr), 256
    out = np.empty_like(x)
    for a in range(0, len(x), n):
        b = min(len(x), a + n)
        lo, hi = max(0, a - pad), min(len(x), b + pad)
        up = resample_poly(x[lo:hi], factor, 1, axis=0)
        dn = resample_poly(fn(up), 1, factor, axis=0)
        out[a:b] = dn[a - lo:a - lo + (b - a)]
    return out


def clipper(x, sr, thr_db, mode="punch", knee_db=None):
    """Oversampled clipper. punch: a narrow knee (1.5 dB) into thr_db, so only the tallest samples of a transient are
    shaved and the corners stay rounded (a pure hard clip, and a 1 dB knee driven hard, left measurable clicks on a real mix).
    loud: a wide knee (3 dB) from thr_db - knee_db, rounding smoothly into thr_db (denser, more harmonics).
    Returns (audio, samples_clipped): samples that went past the start of the knee."""
    t = float(dsp.undb(thr_db))
    knee_db = (1.5 if mode == "punch" else 3.0) if knee_db is None else knee_db
    k = t * float(dsp.undb(-knee_db))

    def fn(u):
        a = np.abs(u)
        soft = k + (t - k) * np.tanh((a - k) / (t - k))
        return np.where(a > k, np.sign(u) * soft, u)
    n_clip = int(np.sum(np.max(np.abs(x), axis=1) > k))
    return _os_map(x, fn, sr=sr), n_clip


def crest_db(y):
    return float(dsp.sample_peak(y) - dsp.rms_db(y))
