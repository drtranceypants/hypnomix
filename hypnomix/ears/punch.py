#!/usr/bin/env python3
"""Compare how two (or more) takes of the same bars handle transients, at matched loudness.

Use it for limiter/clipper/compressor A/Bs, where LUFS and crest barely move but the drums do.
  punch dB      : median over drum hits of (peak in first 10 ms) − (RMS of the next 10–80 ms). Higher = snappier
  pump LU       : std-dev of 400 ms momentary loudness after removing the 3 s trend. Higher = more gain riding/pumping
  >10k dB       : share of energy above 10 kHz. Rises when clipping adds harmonics
  hits          : drum onsets found (same bars should give similar counts)
Every file is first normalised to the loudness of the first one.

Usage: hypnomix punch A.wav B.wav [C.wav ...]
"""
import sys, warnings
import numpy as np, soundfile as sf, pyloudnorm as pyln, librosa
from scipy.signal import butter, sosfilt
from scipy.ndimage import uniform_filter1d

warnings.filterwarnings("ignore")


def stats(y, sr, ref_lufs=None):
    meter = pyln.Meter(sr)
    L = meter.integrated_loudness(y)
    if ref_lufs is not None:
        y = y * 10 ** ((ref_lufs - L) / 20)
    m = y.mean(axis=1)
    # drum hits: onsets in the low band (kick/snare body), 30–8000 Hz broadband peak
    low = sosfilt(butter(4, [40, 250], "bandpass", fs=sr, output="sos"), m)
    on = librosa.onset.onset_detect(y=low, sr=sr, units="samples", backtrack=True, hop_length=256)
    p10, w80 = int(0.010 * sr), int(0.080 * sr)
    pk = []
    for o in on:
        a, b = m[o:o + p10], m[o + p10:o + w80]
        if len(b) < w80 - p10:
            continue
        pk.append(20 * np.log10(np.abs(a).max() + 1e-9) - 20 * np.log10(np.sqrt((b ** 2).mean()) + 1e-9))
    # momentary loudness (400 ms, 100 ms hop) wobble around the 3 s trend
    hop, win = int(0.1 * sr), int(0.4 * sr)
    mom = np.array([meter.integrated_loudness(y[i:i + win]) if i + win <= len(y) else np.nan
                    for i in range(0, len(y) - win, hop)])
    mom = mom[np.isfinite(mom) & (mom > -50)]
    pump = float(np.std(mom - uniform_filter1d(mom, 30))) if len(mom) > 40 else float("nan")
    S = np.abs(np.fft.rfft(m * np.hanning(len(m)))) ** 2
    f = np.fft.rfftfreq(len(m), 1 / sr)
    hf = 10 * np.log10(S[f > 10000].sum() / S[f > 20].sum())
    return dict(lufs=L, punch=float(np.median(pk)) if pk else float("nan"), pump=pump, hf=hf, hits=len(pk))


def main(files):
    ref = None
    rows = []
    for f in files:
        from hypnomix.core import dsp
        y, sr = dsp.load(f)
        s = stats(y, sr, ref)
        if ref is None:
            ref = s["lufs"]
        rows.append((f, s))
    b = rows[0][1]
    print(f"{'take':<46}{'LUFS':>7}{'punch dB':>10}{'pump LU':>9}{'>10k dB':>9}{'hits':>6}")
    for f, s in rows:
        d = "" if s is b else f"   Δ punch {s['punch'] - b['punch']:+.2f}  Δ pump {s['pump'] - b['pump']:+.3f}  Δ >10k {s['hf'] - b['hf']:+.2f}"
        print(f"{f.split('/')[-1][:45]:<46}{s['lufs']:>7.1f}{s['punch']:>10.2f}{s['pump']:>9.3f}{s['hf']:>9.2f}{s['hits']:>6}{d}")
    print("(all files compared at the loudness of the first)")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1:])
