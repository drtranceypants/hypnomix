#!/usr/bin/env python3
"""Find clicks and crackle: samples where the waveform jumps far more than the local signal predicts
(second-difference spikes against the local level). Prints the count and the worst times.
Run it on renders and processed files (hard clip edges, gates that chatter, bad splices).

Usage: hypnomix clicks FILE.wav [FILE2.wav ...] [--from S --to S]
"""
import argparse

import numpy as np
import soundfile as sf
from scipy.ndimage import uniform_filter1d


def find_clicks(y, sr, ratio=12.0, floor=0.01):
    d2 = np.abs(np.diff(y, 2))
    loc = np.sqrt(np.maximum(uniform_filter1d(d2 ** 2, int(0.01 * sr)), 0)) + 1e-6
    hits = np.flatnonzero((d2 / loc > ratio) & (d2 > floor))
    ev = []
    for h in hits:                                   # merge hits within 5 ms
        if not ev or h - ev[-1][0] > sr * 0.005:
            ev.append([h, d2[h]])
        elif d2[h] > ev[-1][1]:
            ev[-1][1] = d2[h]
    return sorted(ev, key=lambda e: -e[1])


def main():
    ap = argparse.ArgumentParser(prog="hypnomix clicks", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+"); ap.add_argument("--from", dest="fr", type=float, default=0)
    ap.add_argument("--to", type=float)
    a = ap.parse_args()
    for f in a.files:
        y, sr = sf.read(f, always_2d=True)
        y = y.mean(1)[int(a.fr * sr): int(a.to * sr) if a.to else None]
        ev = find_clicks(y, sr)
        print(f"{f.split('/')[-1]}: {len(ev)} clicks; worst at", [f"{a.fr + e[0] / sr:.2f}s" for e in ev[:8]])


if __name__ == "__main__":
    main()
