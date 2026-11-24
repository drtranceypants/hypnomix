#!/usr/bin/env python3
"""Tighten vocal doubles and harmonies to the lead: the timing of every word, without touching pitch.

How: both vocals are reduced to pitch-independent features (loudness envelope, onset strength, and
consonant energy above 3 kHz), so a harmony a third above still lines up with the lead. A banded DTW
finds the time offset between them every 10 ms; the overdub is then re-timed with WSOLA (overlap-add
that keeps pitch and formants). Offsets are only applied where both are singing, smoothed, and capped.

Usage:
    hypnomix vocalign LEAD.wav DOUBLE.wav [HARMONY.wav …] [--strength 1.0] [--max-ms 150]
                     [--trim-tails] [--level -6] [--out DIR]

  --strength   0–1: how far to move toward the lead (0.7 keeps a little natural looseness)
  --trim-tails fade overdub word-endings that hang past the lead's (the classic stacked-"s" problem)
  --level      set each overdub this many dB under the lead's loudness while both sing (omit to keep levels)
  --engine     auto (Rubber Band if `rubberband` is installed, else WSOLA) | rubberband | wsola
  --mode       tight (default) | gentle: for the Rubber Band engine; use gentle if a part sounds warbly

All files must start at the same point in the song (export them from the same bar).
Writes "<name> (aligned).wav" for each overdub and a VOCALIGN.md with before/after timing.
"""
from hypnomix.core.paths import out_at
import argparse, sys
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.core.paths import out as out_dir

FR_S = 0.01                      # feature frame: 10 ms


def features(y, sr):
    import librosa
    m = librosa.resample(y.mean(axis=1), orig_sr=sr, target_sr=16000)
    hop = int(16000 * FR_S)
    rms = librosa.feature.rms(y=m, frame_length=640, hop_length=hop)[0]
    env = 20 * np.log10(rms + 1e-6)
    onset = librosa.onset.onset_strength(y=m, sr=16000, hop_length=hop)
    S = np.abs(librosa.stft(m, n_fft=640, hop_length=hop)) ** 2
    f = librosa.fft_frequencies(sr=16000, n_fft=640)
    cons = 10 * np.log10(S[f > 3000].sum(axis=0) + 1e-10)
    n = min(len(env), len(onset), len(cons))
    F = np.stack([env[:n], onset[:n] * 3, cons[:n]], axis=1)
    F = (F - np.median(F, axis=0)) / (np.std(F, axis=0) + 1e-6)
    active = env[:n] > np.percentile(env[:n], 95) - 30
    return F, active


def band_dtw(A, B, radius):
    """DTW restricted to |i - j| <= radius. Returns offset[i] = j - i (in frames) along the best path."""
    n = min(len(A), len(B))
    A, B = A[:n], B[:n]
    W = 2 * radius + 1
    ks = np.arange(-radius, radius + 1)
    D = np.full((n, W), np.inf)
    step = np.zeros((n, W), np.int8)                    # 0 diag, 1 from (i-1, j), 2 from (i, j-1)
    pen = 0.15                                          # discourages needless warping
    for i in range(n):
        j = i + ks
        ok = (j >= 0) & (j < n)
        c = np.full(W, np.inf)
        c[ok] = np.abs(A[i] - B[j[ok]]).sum(axis=1)
        if i == 0:
            prev_diag = np.where(ks == 0, 0.0, np.inf)
            prev_up = np.full(W, np.inf)
        else:
            prev_diag = D[i - 1]
            prev_up = np.append(D[i - 1, 1:], np.inf) + pen    # (i-1, j) is k+1 in the previous row
        best = np.minimum(prev_diag, prev_up)
        st = np.where(prev_up < prev_diag, 1, 0).astype(np.int8)
        row = np.empty(W)
        run = np.inf
        for k in range(W):                              # horizontal moves within the row
            h = run + pen
            if h < best[k]:
                row[k] = c[k] + h; st[k] = 2
            else:
                row[k] = c[k] + best[k]
            run = row[k]
        D[i] = row
        step[i] = st
    # backtrack from the end, on the diagonal-most cell
    i, k = n - 1, int(np.argmin(D[n - 1] + np.abs(ks) * 1e-3))
    off = np.zeros(n)
    while i >= 0:
        off[i] = ks[k]
        s = step[i, k]
        if s == 0:
            i -= 1
        elif s == 1:
            i -= 1; k = min(W - 1, k + 1)
        else:
            k -= 1
            if k < 0:
                i -= 1; k = 0
    return off


def offset_curve(lead, over, sr, max_ms, strength):
    FA, actA = features(lead, sr)
    FB, actB = features(over, sr)
    R = int(max_ms / 1000 / FR_S)
    off = band_dtw(FA, FB, R)
    n = len(off)
    both = actA[:n] & actB[:n]
    from scipy.ndimage import median_filter, uniform_filter1d
    off = median_filter(off, 7)
    # only trust offsets where both sing; elsewhere interpolate between trusted regions
    idx = np.flatnonzero(both)
    if len(idx) < 10:
        return np.zeros(n), both, off
    off = np.interp(np.arange(n), idx, off[idx])
    off = uniform_filter1d(off, 5)
    # cap the slope so the stretch stays between 0.6x and 1.6x (natural-sounding)
    for i in range(1, n):
        off[i] = np.clip(off[i], off[i - 1] - 0.4, off[i - 1] + 0.6)
    return off * strength, both, off


def wsola_warp(x, sr, offset_s, frame=1024, hop=256, search=128):
    """y[t] ≈ x[t + offset(t)], pitch preserved. offset_s: callable/array of seconds per output sample frame."""
    n = len(x)
    win = np.hanning(frame)
    out = np.zeros((n + frame, x.shape[1]))
    norm = np.zeros(n + frame)
    xp = np.pad(x, ((frame + search, frame + search), (0, 0)))
    base = frame + search
    prev_in = None
    mono = xp.mean(axis=1)
    for t in range(0, n, hop):
        want = int(np.clip(t + int(round(offset_s(t) * sr)), -frame, n))   # stay inside the (padded) file
        if prev_in is not None:
            nat = prev_in + hop
            if abs(want - nat) <= 1:
                pos = nat
            else:
                # pick the position near `want` whose frame best continues the previous one
                ref = mono[base + nat: base + nat + frame]
                seg = mono[base + want - search: base + want + search + frame]
                if len(ref) == frame and len(seg) >= frame:      # near the end there may be nothing to search
                    c = np.correlate(seg, ref, "valid")
                    pos = want - search + int(np.argmax(c))
                else:
                    pos = want
        else:
            pos = want
        pos = int(np.clip(pos, -frame, n))
        out[t:t + frame] += xp[base + pos: base + pos + frame] * win[:, None]
        norm[t:t + frame] += win
        prev_in = pos
    norm[norm < 1e-3] = 1
    return (out / norm[:, None])[:n]


def trim_tails(lead, over, sr, fade_ms=40):
    """Fade the overdub where it keeps sounding after the lead has stopped (or starts before it)."""
    bl = dsp.block_rms_db(lead, sr, 0.01)
    bo = dsp.block_rms_db(over, sr, 0.01)
    k = min(len(bl), len(bo))
    lead_on = bl[:k] > bl.max() - 35
    over_on = bo[:k] > bo.max() - 35
    keep = lead_on.copy()
    from scipy.ndimage import binary_dilation, uniform_filter1d
    keep = binary_dilation(keep, iterations=3)          # 30 ms grace around the lead
    g = np.where(over_on & ~keep, 0.0, 1.0)
    g = uniform_filter1d(g, max(1, int(fade_ms / 10)))
    gs = np.repeat(g, int(0.01 * sr))
    gs = np.pad(gs, (0, max(0, len(over) - len(gs))), constant_values=1)[: len(over)]
    trimmed = float(np.mean(g < 0.5) / max(1e-9, np.mean(over_on))) if over_on.any() else 0
    return over * gs[:, None], trimmed


def residual_ms(lead, over, sr, max_ms):
    FA, aA = features(lead, sr)
    FB, aB = features(over, sr)
    off = band_dtw(FA, FB, int(max_ms / 1000 / FR_S))
    both = aA[:len(off)] & aB[:len(off)]
    if not both.any():
        return 0.0, 0.0
    a = np.abs(off[both]) * FR_S * 1000
    return float(np.median(a)), float(np.percentile(a, 95))


def align(lead_path, over_path, strength=1.0, max_ms=150, trim=False, level=None, outdir=None, engine="auto", mode="tight"):
    lead, sr = dsp.load(lead_path)
    over, _ = dsp.load(over_path, sr)
    n = max(len(lead), len(over))
    lead = np.pad(lead, ((0, n - len(lead)), (0, 0)))
    over = np.pad(over, ((0, n - len(over)), (0, 0)))
    before = residual_ms(lead, over, sr, max_ms)
    import shutil
    notes = []
    if engine == "rubberband" or (engine == "auto" and shutil.which("rubberband")):
        from hypnomix.studio._rbalign import align_rb, HOP
        out, off_rb, both_rb = align_rb(lead, over, sr, min(max_ms, 120), strength, mode)
        # report in this module's 10 ms frames
        k = max(1, int(round(FR_S * sr / HOP)))
        off = off_rb[::k] * HOP / sr / FR_S; both = both_rb[::k]
        notes.append(f"Rubber Band engine, {mode}")
    else:
        off, both, raw = offset_curve(lead, over, sr, max_ms, strength)
        t_frames = np.arange(len(off)) * FR_S
        fn = lambda t: float(np.interp(t / sr, t_frames, off * FR_S))
        out = wsola_warp(over, sr, fn)
        notes.append("WSOLA engine (install `rubberband` for the cleaner, tighter engine)")
    if trim:
        out, frac = trim_tails(lead, out, sr)
        notes.append(f"tails trimmed on {frac * 100:.0f}% of its sung time")
    if level is not None:
        la, lo = dsp.active_lufs(lead, sr), dsp.active_lufs(out, sr)
        g = (la + level) - lo
        out *= dsp.undb(g)
        notes.append(f"level {g:+.1f} dB → {level:+g} dB under the lead")
    after = residual_ms(lead, out, sr, max_ms)
    od = out_at(outdir, "vocalign")
    path = dsp.save(od / f"{Path(over_path).stem} (aligned).wav", out, sr, 24)
    moved = float(np.mean(np.abs(off[both]) * FR_S * 1000 > 5)) if both.any() else 0
    return dict(file=Path(over_path).name, before=before, after=after, moved=moved, notes=notes, out=path,
                max_shift=float(np.max(np.abs(off)) * FR_S * 1000))


def main():
    ap = argparse.ArgumentParser(prog="hypnomix vocalign", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lead"); ap.add_argument("overdubs", nargs="+")
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--max-ms", type=float, default=150)
    ap.add_argument("--trim-tails", action="store_true")
    ap.add_argument("--level", type=float)
    ap.add_argument("--out")
    ap.add_argument("--engine", choices=["auto", "rubberband", "wsola"], default="auto")
    ap.add_argument("--mode", choices=["tight", "gentle"], default="tight",
                    help="Rubber Band engine: tight (closest timing) or gentle (smoother speed changes, less warble)")
    a = ap.parse_args()
    od = out_at(a.out, "vocalign")
    rows = []
    for o in a.overdubs:
        print(f"aligning {Path(o).name} to {Path(a.lead).name} …", file=sys.stderr)
        rows.append(align(a.lead, o, a.strength, a.max_ms, a.trim_tails, a.level, od, a.engine, a.mode))
    md = [f"# Vocal alignment to {Path(a.lead).name}", "",
          "Timing difference from the lead while both sing (median / worst 5%):", "",
          "| overdub | before | after | frames moved >5 ms | biggest shift | notes |", "|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['file']} | {r['before'][0]:.0f} / {r['before'][1]:.0f} ms | {r['after'][0]:.0f} / {r['after'][1]:.0f} ms | "
                  f"{r['moved'] * 100:.0f}% | {r['max_shift']:.0f} ms | {'; '.join(r['notes'])} |")
    md += ["", "Under ~10 ms reads as one voice; 20–40 ms as a natural double; above that, flams and smeared consonants.",
           "If something sounds robotic, rerun with --strength 0.7.", "", *[f"- `{r['out']}`" for r in rows]]
    (od / "VOCALIGN.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
