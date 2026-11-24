#!/usr/bin/env python3
"""Phase and polarity check for one source recorded more than once: kick in + kick out, snare top +
bottom, DI + amp mic, two mics on an acoustic guitar, overheads vs close mics.

For each file against the first (the reference): time offset (samples and ms), polarity, and how much
fuller the sum gets once fixed (the low end that was cancelling). --apply writes corrected copies.

Usage:
    hypnomix align REFERENCE.wav OTHER.wav [MORE.wav …] [--max-ms 20] [--apply] [--out DIR]
"""
from hypnomix.core.paths import out_at
import argparse
from pathlib import Path

import numpy as np
from scipy.signal import correlate

from hypnomix.core import dsp
from hypnomix.core.paths import out as out_dir


def loudest_window(y, sr, secs=20):
    n = int(secs * sr)
    if len(y) <= n:
        return 0, len(y)
    b = dsp.block_rms_db(y, sr, 1.0)
    k = int(secs)
    i = int(np.argmax(np.convolve(10 ** (b / 10), np.ones(k), "valid")))
    return i * sr, i * sr + n


def offset(ref, other, sr, max_ms):
    a, b = loudest_window(ref, sr)
    r = ref[a:b].mean(axis=1)
    o = other[a:b].mean(axis=1)
    band = dsp.butter(4, [60, 4000], "bandpass", fs=sr, output="sos")
    r, o = dsp.filt(r, band), dsp.filt(o, band)
    m = int(max_ms / 1000 * sr)
    c = correlate(o, r, "full", method="fft")
    mid = len(r) - 1
    seg = c[mid - m: mid + m + 1]
    k = int(np.argmax(np.abs(seg)))
    lag = k - m                                       # other is late by `lag` samples
    pol = 1 if seg[k] > 0 else -1
    peak = abs(seg[k]) / (np.sqrt((r ** 2).sum() * (o ** 2).sum()) + 1e-20)
    return lag, pol, float(peak)


def shift(y, lag):
    if lag > 0:
        return np.vstack([y[lag:], np.zeros((lag, y.shape[1]))])
    if lag < 0:
        return np.vstack([np.zeros((-lag, y.shape[1])), y[:lag]])
    return y


def sum_gain(ref, other, sr):
    """dB of low-end (60-300 Hz) gained in the sum vs. what two in-phase signals would give."""
    s = dsp.filt(dsp.stereo(ref) + dsp.stereo(other), dsp.butter(4, [60, 300], "bandpass", fs=sr, output="sos"))
    return dsp.rms_db(s)


def main():
    ap = argparse.ArgumentParser(prog="hypnomix align", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ref"); ap.add_argument("others", nargs="+")
    ap.add_argument("--max-ms", type=float, default=20); ap.add_argument("--apply", action="store_true"); ap.add_argument("--out")
    a = ap.parse_args()
    ref, sr = dsp.load(a.ref)
    od = out_at(a.out, "align")
    md = [f"# Phase & alignment against {Path(a.ref).name}", "",
          "| file | offset | polarity | similarity | low end in the sum (60–300 Hz) | fix |", "|---|---|---|---|---|---|"]
    for f in a.others:
        y, _ = dsp.load(f, sr)
        n = min(len(y), len(ref))
        y, r = y[:n], ref[:n]
        lag, pol, sim = offset(r, y, sr, a.max_ms)
        fixed = shift(y, lag) * pol
        before, after = sum_gain(r, y, sr), sum_gain(r, fixed, sr)
        fix = []
        if pol < 0:
            fix.append("flip polarity (Utility: Phz-L + Phz-R)")
        if abs(lag) > 1:
            fix.append(f"{'delay' if lag < 0 else 'advance'} by {abs(lag)} samples ({abs(lag) / sr * 1000:.2f} ms)"
                       + (" with Track Delay or by nudging the clip" if True else ""))
        md.append(f"| {Path(f).name} | {lag:+d} smp ({lag / sr * 1000:+.2f} ms) | {'inverted' if pol < 0 else 'normal'} | {sim:.2f} | "
                  f"{after - before:+.1f} dB once fixed | {'; '.join(fix) or 'already aligned'} |")
        if a.apply and fix:
            dsp.save(od / f"{Path(f).stem} (aligned).wav", fixed, sr, 24)
    md += ["", "Similarity under ~0.3 means the two mics hear quite different things (e.g. room vs close); the offset "
           "is then a best guess, so trust your ears. A few dB more low end once fixed is the classic sign that "
           "two mics were fighting."]
    text = "\n".join(md) + "\n"
    (od / "ALIGN.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
