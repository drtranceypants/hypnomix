#!/usr/bin/env python3
"""Render a mix overview PNG: mel spectrogram, short-term loudness, and average spectrum.

Usage: hypnomix spectrogram song.wav [...] [--out DIR]
"""
from hypnomix.core.paths import out_at
import argparse, warnings
from pathlib import Path

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")


def render(path, outdir):
    # the plotting libraries take seconds to load, so they load here and not when `hypnomix spectrogram -h` runs
    import librosa, librosa.display
    import pyloudnorm as pyln
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    data, sr = sf.read(str(path), always_2d=True)
    mono = data.mean(axis=1).astype(np.float32)
    y = librosa.resample(mono, orig_sr=sr, target_sr=22050); sr2 = 22050

    fig, ax = plt.subplots(3, 1, figsize=(16, 11), gridspec_kw={"height_ratios": [3, 1, 1.4]})
    S = librosa.feature.melspectrogram(y=y, sr=sr2, n_mels=160, fmax=11025)
    img = librosa.display.specshow(librosa.power_to_db(S, ref=np.max), sr=sr2, x_axis="time",
                                   y_axis="mel", fmax=11025, ax=ax[0], cmap="magma")
    fig.colorbar(img, ax=ax[0], format="%+.0f dB")
    ax[0].set_title(f"{Path(path).stem} — mel spectrogram")

    meter = pyln.Meter(sr); win = 3 * sr
    t, st = [], []
    for i in range(0, max(1, len(data) - win), sr // 2):
        v = meter.integrated_loudness(data[i:i + win])
        t.append(i / sr); st.append(v if np.isfinite(v) else np.nan)
    ax[1].plot(t, st, lw=1.2); ax[1].set_ylabel("short-term LUFS"); ax[1].grid(alpha=.3)
    ax[1].set_xlim(0, len(mono) / sr)

    spec = np.abs(librosa.stft(mono, n_fft=8192, hop_length=4096)).mean(axis=1)
    f = librosa.fft_frequencies(sr=sr, n_fft=8192)
    ax[2].semilogx(f[1:], 20 * np.log10(spec[1:] + 1e-9)); ax[2].set_xlim(20, 20000)
    ax[2].set_xlabel("Hz"); ax[2].set_ylabel("avg dB"); ax[2].grid(alpha=.3, which="both")
    fig.tight_layout()
    out = outdir / (Path(path).stem + ".png"); fig.savefig(out, dpi=110); plt.close(fig)
    return out


def main():
    ap = argparse.ArgumentParser(prog="hypnomix spectrogram", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter); ap.add_argument("files", nargs="+")
    ap.add_argument("--out"); a = ap.parse_args()
    from hypnomix.core.paths import out
    outdir = out_at(a.out, "spectrograms"); outdir.mkdir(parents=True, exist_ok=True)
    for f in a.files:
        print(render(f, outdir))


if __name__ == "__main__":
    main()
