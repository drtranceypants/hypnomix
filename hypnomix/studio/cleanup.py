#!/usr/bin/env python3
"""Rescue a rough demo or a noisy recording: DC, rumble, mains hum, steady background noise
(fans, hiss, room tone), and the silence at the start and end. Conservative by default.

Usage:
    hypnomix cleanup take.wav [more.wav …] [--strength 0.6] [--no-hum] [--no-noise] [--keep-ends] [--out DIR]

  --strength  0–1 noise reduction amount (0.6 is subtle; above 0.8 artifacts — "underwater" sounds — appear)
Noise reduction uses the `noisereduce` library (MIT) with a noise profile learned from the quietest part of
the file, so it only removes what is there when nobody is playing.
"""
from hypnomix.core.paths import out_at
import argparse, sys
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.core.paths import out as out_dir
from hypnomix.studio.soundcheck import hum


def quietest_segment(y, sr, secs=1.0):
    b = dsp.block_rms_db(y, sr, 0.1)
    k = max(1, int(secs / 0.1))
    if len(b) <= k:
        return y
    i = int(np.argmin(np.convolve(b, np.ones(k), "valid")))
    return y[int(i * 0.1 * sr): int((i + k) * 0.1 * sr)]


def clean(y, sr, strength=0.6, do_hum=True, do_noise=True, trim=True):
    log = []
    y = y - y.mean(axis=0)
    y = dsp.filt(y, dsp.highpass(30, sr, 2))
    log.append("removed DC offset and rumble below 30 Hz")
    if do_hum:
        h, base = hum(y, sr)
        if h > 10:
            for k in range(1, 7):
                if base * k < sr / 2:
                    y = dsp.filt(y, dsp.notch(base * k, 35, sr))
            log.append(f"notched {base} Hz mains hum and 5 harmonics (it was {h:.0f} dB above its surroundings)")
    if do_noise and strength > 0:
        floor0 = dsp.noise_floor_db(y, sr)
        try:
            import noisereduce as nr
        except ImportError:
            sys.exit("noise reduction needs noisereduce: uv pip install noisereduce  (or pass --no-noise)")
        prof = quietest_segment(y, sr)
        n_fft = 2048                      # the library smooths over 50 ms and needs a hop (n_fft / 4) no longer than that,
        while n_fft > 256 and n_fft > 0.2 * sr:     # so a low sample rate (8 kHz) gets a shorter window
            n_fft //= 2
        out = np.stack([nr.reduce_noise(y=y[:, c], sr=sr, y_noise=prof[:, c], stationary=True,
                                        prop_decrease=float(np.clip(strength, 0, 1)), n_fft=n_fft)
                        for c in range(y.shape[1])], axis=1)
        y = out[: len(y)]
        log.append(f"noise reduction at {int(strength * 100)}%: floor {floor0:.0f} → {dsp.noise_floor_db(y, sr):.0f} dBFS")
    if trim:
        env = np.max(np.abs(y), axis=1)
        on = np.flatnonzero(env > dsp.undb(-50))
        if len(on):
            a = max(0, on[0] - int(0.05 * sr))
            b = min(len(y), on[-1] + int(0.3 * sr))
            y = y[a:b].copy()
            f_in, f_out = int(0.005 * sr), int(0.05 * sr)
            y[:f_in] *= np.linspace(0, 1, f_in)[:, None]
            y[-f_out:] *= np.linspace(1, 0, f_out)[:, None]
            log.append(f"trimmed {a / sr:.2f} s of lead-in silence, added a 5 ms fade-in and 50 ms fade-out")
    return y, log


def main():
    ap = argparse.ArgumentParser(prog="hypnomix cleanup", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+"); ap.add_argument("--strength", type=float, default=0.6)
    ap.add_argument("--no-hum", action="store_true"); ap.add_argument("--no-noise", action="store_true")
    ap.add_argument("--keep-ends", action="store_true"); ap.add_argument("--out")
    a = ap.parse_args()
    od = out_at(a.out, "cleanup")
    for f in a.files:
        y, sr = dsp.load(f)
        z, log = clean(y, sr, a.strength, not a.no_hum, not a.no_noise, not a.keep_ends)
        p = dsp.save(od / f"{Path(f).stem} (clean).wav", z, sr, 24)
        print(f"{Path(f).name} → {p}")
        for x in log:
            print(f"  • {x}")


if __name__ == "__main__":
    main()
