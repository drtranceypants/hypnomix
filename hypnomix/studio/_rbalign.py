"""Rubber Band alignment engine for `hypnomix vocalign` (used when the `rubberband` CLI is installed).

Pitch-independent features (MFCC 1-13 + spectral flux + energy, 5.8 ms frames), banded DTW in overlapping
30 s chunks, corrections only where both parts sing, then each PHRASE of the overdub (cut at its silent gaps)
is re-timed separately with Rubber Band R3 and a time map. Per-phrase processing matters: one long time map
drifts by 100+ ms. Modes: "tight" (default, stretch 0.6-1.6x) or "gentle" (~250 ms smoothing, 0.85-1.18x
while singing, bigger moves only in gaps: less warble, less tightening).
Measured on a 5-part harmony stack: mean word-start error 32-48 ms -> 23-29 ms (tight).
"""
import subprocess, tempfile, os
import numpy as np, soundfile as sf, librosa
from scipy.ndimage import median_filter

HOP = 256


def feats(y, sr):
    m = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=14, hop_length=HOP, n_fft=1024)[1:]
    S = np.abs(librosa.stft(y, n_fft=1024, hop_length=HOP))
    flux = np.r_[0, np.maximum(0, np.diff(np.log1p(S), axis=1)).sum(0)]
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=HOP)[0]
    e = 20 * np.log10(rms + 1e-9)
    F = np.vstack([m, 3 * flux[None] / (flux.std() + 1e-9), e[None] / 6])
    F = (F - F.mean(1, keepdims=True)) / (F.std(1, keepdims=True) + 1e-9)
    return F, e


def raw_offsets(g, d, sr, maxms):
    """DTW offsets (frames) per dub frame; NaN where the two parts aren't both singing."""
    Fg, eg = feats(g, sr); Fd, ed = feats(d, sr)
    n = min(Fg.shape[1], Fd.shape[1]); Fg, Fd, eg, ed = Fg[:, :n], Fd[:, :n], eg[:n], ed[:n]
    band = int(maxms / 1000 * sr / HOP)
    # banded DTW (cost matrix only inside the band) via librosa with global constraint
    C = librosa.sequence.dtw(X=Fd, Y=Fg, metric="cosine", global_constraints=True,
                             band_rad=min(0.5, (band + 2) / n), backtrack=True)[1][::-1]
    off = np.full(n, np.nan)
    for i, j in C:              # dub frame i -> guide frame j
        off[i] = j - i if np.isnan(off[i]) else (off[i] + (j - i)) / 2
    gate = -45
    both = (ed > gate) & (eg > gate)
    off[~both] = np.nan
    off = np.clip(off, -band, band)
    return off, both


def offsets(g, d, sr, maxms, chunk_s=30.0, overlap_s=5.0):
    """Whole-file offsets, computed in overlapping chunks (full-song DTW would need GBs), stitched with
    a crossfade in each overlap, then median-smoothed; gaps interpolated, file edges pinned to 0."""
    n = min(len(g), len(d)) // HOP + 1
    off = np.full(n, np.nan); both = np.zeros(n, bool); w = np.zeros(n)
    cs, hs = int(chunk_s * sr), int((chunk_s - overlap_s) * sr)
    for s0 in range(0, min(len(g), len(d)), hs):
        G, D = g[s0:s0 + cs], d[s0:s0 + cs]
        if len(G) < sr or np.abs(D).max() < 1e-4 or np.abs(G).max() < 1e-4:
            continue
        o, b = raw_offsets(G, D, sr, maxms)
        f0 = s0 // HOP; m = len(o)
        ramp = np.minimum(1, np.minimum(np.arange(m) + 1, m - np.arange(m)) / (overlap_s * sr / HOP))
        seg = slice(f0, f0 + m); m = len(off[seg]); o, b, ramp = o[:m], b[:m], ramp[:m]
        ok = ~np.isnan(o)
        cur = np.nan_to_num(off[seg]) * w[seg]
        neww = w[seg] + ramp * ok
        val = np.where(ok, (cur + np.nan_to_num(o) * ramp) / np.maximum(neww, 1e-9), off[seg])
        off[seg] = np.where(neww > 0, val, np.nan); w[seg] = neww; both[seg] |= b
    off[~both] = np.nan
    # smooth the valid parts
    v = ~np.isnan(off)
    if v.sum() < 10:
        return np.zeros(n), both
    sm = off.copy(); sm[v] = median_filter(off[v], size=9)
    if MODE == "gentle":
        # smooth the correction curve (~250 ms) so the speed changes gently -> less warble, less tightening
        from scipy.ndimage import gaussian_filter1d
        sm[v] = gaussian_filter1d(sm[v], sigma=0.12 * sr / HOP)
    # interpolate across gaps, pin edges to 0
    idx = np.arange(n); xs = np.r_[0, idx[v], n - 1]; ys = np.r_[0, sm[v], 0]
    return np.interp(idx, xs, ys), both



# "tight" (default; preferred by ear on a real harmony stack): word starts land closest to the guide.
# "gentle": smoother, smaller speed changes while singing -- use if a part sounds warbly.
MODE = "tight"
LIMITS = {"tight": ((0.6, 1.6), (0.6, 1.6)), "gentle": ((0.85, 1.18), (0.5, 2.0))}
SING_LIMITS, GAP_LIMITS = LIMITS[MODE]


def stretch(seg, off_frames, sr, sung=None):
    """Rubber Band one phrase with a time map (dub sample -> dub sample + offset).
    Keyframes every 2048 samples (denser maps or a "0 0" line make Rubber Band ignore the map);
    local stretch limited to 0.6x..1.6x; the phrase keeps its exact length."""
    n = len(off_frames); step = 8
    if n < 4 * step or np.abs(off_frames).max() < 1:
        return seg
    src = np.arange(step, n - step, step) * HOP; tgt = (src + off_frames[step:n - step:step] * HOP).astype(float)
    for i in range(1, len(tgt)):
        dt = src[i] - src[i - 1]
        fr = min(len(sung) - 1, src[i] // HOP) if sung is not None else None
        lo, hi = SING_LIMITS if (sung is None or sung[fr]) else GAP_LIMITS
        tgt[i] = min(max(tgt[i], tgt[i - 1] + lo * dt), tgt[i - 1] + hi * dt)
    tgt = np.clip(tgt, 1, len(seg) - 1)
    keep = np.r_[True, np.diff(tgt) > 0]
    src, tgt = src[keep].astype(int), np.round(tgt[keep]).astype(int)
    with tempfile.TemporaryDirectory() as td:
        fi, fo, fm = [os.path.join(td, x) for x in ("in.wav", "out.wav", "map.txt")]
        sf.write(fi, seg.astype(np.float32), sr, subtype="FLOAT")
        np.savetxt(fm, np.c_[src, tgt], fmt="%d")
        subprocess.run(["rubberband", "-3", "-q", "-M", fm, "-D", f"{len(seg) / sr:.6f}", fi, fo],
                       check=True, capture_output=True)
        Y, _ = sf.read(fo)
    if seg.ndim == 1:
        Y = Y.mean(1) if Y.ndim > 1 else Y
        return np.pad(Y, (0, max(0, len(seg) - len(Y))))[: len(seg)]
    Y = Y if Y.ndim > 1 else Y[:, None]
    return np.pad(Y, ((0, max(0, len(seg) - len(Y))), (0, 0)))[: len(seg)]


def stretch_phrases(D, off, sr, min_gap_s=0.25, gate_db=-50, audio=None):
    """Cut the dub at its silent gaps (>= min_gap_s), stretch each phrase on its own and rejoin.
    Long single-pass time maps drift by 100+ ms in Rubber Band; per-phrase processing resets every gap."""
    rms = librosa.feature.rms(y=D, frame_length=1024, hop_length=HOP)[0]
    quiet = 20 * np.log10(rms + 1e-9) < gate_db
    cuts, run = [0], 0
    for i, q in enumerate(quiet):
        run = run + 1 if q else 0
        if run == int(min_gap_s * sr / HOP):
            cuts.append(i - run // 2)
    cuts.append(len(quiet))
    X = D if audio is None else audio          # audio to stretch (mono or stereo); D (mono) finds the gaps
    Y = X.copy()
    for a, b in zip(cuts[:-1], cuts[1:]):
        s0, s1 = a * HOP, min(len(D), b * HOP)
        if s1 - s0 < sr // 4 or np.abs(D[s0:s1]).max() < 1e-4:
            continue
        Y[s0:s1] = stretch(X[s0:s1], off[a:b], sr, sung=~quiet[a:b])
    return Y


def align_rb(lead, over, sr, max_ms=120, strength=1.0, mode="tight"):
    """lead, over: (n, ch) arrays at sr. Returns the re-timed overdub (same shape) and the offsets (frames)."""
    global MODE, SING_LIMITS, GAP_LIMITS
    MODE = mode; SING_LIMITS, GAP_LIMITS = LIMITS[mode]
    g = lead.mean(1).astype(np.float32); d = over.mean(1).astype(np.float32)
    off, both = offsets(g, d, sr, max_ms)
    off = off * strength
    return stretch_phrases(d, off, sr, audio=over), off, both
