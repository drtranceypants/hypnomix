#!/usr/bin/env python3
"""Compare the pitch and level of two Live captures of the same bars (e.g. a track and its processed copy,
each soloed). Prints the median pitch difference (cents, frame-aligned) and the loudness difference (LU).
Usage: hypnomix pitchcheck A.wav B.wav   (run after any re-render: expect ~0 cents, ~0 LU)"""
import sys, soundfile as sf, numpy as np, librosa, pyloudnorm as pl
def f0(p):
    y, sr = sf.read(p, always_2d=True); m = y.mean(1)
    z = librosa.resample(m, orig_sr=sr, target_sr=22050)
    f, _, _ = librosa.pyin(z, fmin=70, fmax=800, sr=22050, hop_length=256)
    return f, pl.Meter(sr).integrated_loudness(y)
def main():
    fa, la = f0(sys.argv[1]); fb, lb = f0(sys.argv[2]); n = min(len(fa), len(fb))
    ok = ~np.isnan(fa[:n]) & ~np.isnan(fb[:n]); d = 1200 * np.log2(fb[:n][ok] / fa[:n][ok]); d = d[abs(d) < 300]
    print(f"B vs A: pitch {np.median(d):+.1f} cents (frames {len(d)}, within 15c: {np.mean(abs(d) < 15):.0%}), loudness {lb - la:+.2f} LU")


if __name__ == "__main__":
    main()
