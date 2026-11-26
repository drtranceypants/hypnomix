#!/usr/bin/env python3
"""Measure a mix: loudness (ffmpeg ebur128 + pyloudnorm), tonal balance, stereo, dynamics, tempo/key.

Usage: hypnomix measure song.wav [more.wav ...] [--out DIR]
Writes one JSON per file and prints a short summary.

A file under about 3 seconds gets every measurement that is possible and a plain note about the rest
(the short-term loudness curve needs 3 s). A silent file is reported as silent. Exit code: 0 when every
file was measured, 1 if a file was silent, 2 if a file could not be read as audio; a batch still measures
the other files first.
"""
from hypnomix.core.paths import out_at
import argparse, json, re, subprocess, sys, warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

BANDS = {  # Hz
    "sub_20_60": (20, 60), "bass_60_250": (60, 250), "lowmid_250_500": (250, 500),
    "mid_500_2k": (500, 2000), "highmid_2k_6k": (2000, 6000), "air_6k_20k": (6000, 20000),
}
KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
SHORT_TERM_S = 3          # the short-term loudness window, seconds


def ffmpeg_ebur128(path):
    """Integrated LUFS, LRA, true peak from ffmpeg's EBU R128 filter."""
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                            "-af", "ebur128=peak=true", "-f", "null", "-"],
                           capture_output=True, text=True)
    except FileNotFoundError:                       # ffmpeg not installed: the pyloudnorm figures still work
        return {"integrated_lufs": None, "lra_lu": None, "true_peak_dbtp": None}
    summary = p.stderr[p.stderr.rfind("Summary:"):]
    grab = lambda pat: (lambda m: float(m.group(1)) if m else None)(re.search(pat, summary))
    return {"integrated_lufs": grab(r"I:\s+(-?[\d.]+) LUFS"),
            "lra_lu": grab(r"LRA:\s+(-?[\d.]+) LU"),
            "true_peak_dbtp": grab(r"Peak:\s+(-?[\d.]+) dBFS")}


def estimate_key(y, sr):
    import librosa
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
    best = max(((np.corrcoef(np.roll(prof, i), chroma)[0, 1], f"{KEYS[i]} {mode}")
                for prof, mode in ((MAJ, "major"), (MIN, "minor")) for i in range(12)))
    return best[1], round(float(best[0]), 3)


def measure(path):
    import librosa
    from hypnomix.core import dsp
    data, sr = dsp.load(path)                       # raises AudioReadError with a plain message
    data = data.astype(np.float32)
    mono = data.mean(axis=1)
    out = {"file": str(path), "sr": sr, "channels": data.shape[1],
           "duration_s": round(len(mono) / sr, 2)}
    notes = []
    if len(mono) == 0 or float(np.max(np.abs(data))) < 1e-9:
        out["silent"] = True
        out["notes"] = ["the file is silent (every sample is zero), so there is nothing to measure"]
        return out
    out["ffmpeg"] = ffmpeg_ebur128(path)

    import pyloudnorm as pyln
    meter = pyln.Meter(sr)
    if len(data) >= int(0.4 * sr):                  # one 400 ms block is the least the loudness meter can read
        out["pyloudnorm_lufs"] = round(float(meter.integrated_loudness(data)), 2)
    else:
        out["pyloudnorm_lufs"] = None
        notes.append("the file is under 0.4 s, too short for a loudness reading")
    # short-term loudness curve (3 s windows, 1 s hop) -> section dynamics
    win, hop = SHORT_TERM_S * sr, sr
    st = []
    if len(data) >= win:
        for i in range(0, max(1, len(data) - win), hop):
            v = meter.integrated_loudness(data[i:i + win])
            st.append(round(float(v), 1) if np.isfinite(v) else -70.0)
    else:
        notes.append(f"the file is under {SHORT_TERM_S} s, so there is no short-term loudness curve "
                     f"(short_term_lufs is empty)")
    st_arr = np.array([v for v in st if v > -60])
    out["short_term_lufs"] = st
    if len(st_arr):
        out["short_term_p10_p95"] = [round(float(np.percentile(st_arr, 10)), 1),
                                     round(float(np.percentile(st_arr, 95)), 1)]
    else:
        out["short_term_p10_p95"] = None
        if len(data) >= win:
            notes.append("every 3 s stretch is below -60 LUFS, so no short-term spread is given")

    peak = float(np.max(np.abs(data))) or 1e-9
    rms = float(np.sqrt(np.mean(mono ** 2))) or 1e-9
    out["sample_peak_dbfs"] = round(20 * np.log10(peak), 2)
    out["crest_factor_db"] = round(20 * np.log10(peak / rms), 2)

    # tonal balance: share of energy per band (dB relative to total)
    spec = np.abs(librosa.stft(mono, n_fft=8192, hop_length=4096)) ** 2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=8192)
    total = spec.sum() + 1e-12
    out["band_energy_db"] = {k: round(float(10 * np.log10(spec[(freqs >= lo) & (freqs < hi)].sum() / total + 1e-12)), 2)
                             for k, (lo, hi) in BANDS.items()}
    out["spectral_centroid_hz"] = round(float(librosa.feature.spectral_centroid(S=spec, sr=sr).mean()), 1)
    out["rolloff_85_hz"] = round(float(librosa.feature.spectral_rolloff(S=spec, sr=sr, roll_percent=0.85).mean()), 1)

    if data.shape[1] >= 2:
        L, R = data[:, 0], data[:, 1]
        mid, side = (L + R) / 2, (L - R) / 2
        out["stereo_side_to_mid_db"] = round(float(10 * np.log10((side ** 2).mean() / ((mid ** 2).mean() + 1e-12) + 1e-12)), 2)
        out["lr_correlation"] = round(float(np.corrcoef(L, R)[0, 1]), 3)
        # low-end mono check: correlation below 150 Hz
        from scipy.signal import butter, sosfilt
        sos = butter(4, 150, "lowpass", fs=sr, output="sos")
        out["lr_correlation_below_150hz"] = round(float(np.corrcoef(sosfilt(sos, L), sosfilt(sos, R))[0, 1]), 3)

    try:
        y22 = librosa.resample(mono, orig_sr=sr, target_sr=22050)
        tempo, _ = librosa.beat.beat_track(y=y22, sr=22050)
        out["tempo_bpm_est"] = round(float(np.atleast_1d(tempo)[0]), 1)
        out["key_est"], out["key_confidence"] = estimate_key(y22, 22050)
    except Exception:                               # very short or odd audio: keep what was measured
        out["tempo_bpm_est"] = out["key_est"] = out["key_confidence"] = None
        notes.append("tempo and key could not be estimated from this little audio")
    if notes:
        out["notes"] = notes
    return out


def _fmt(v, unit=""):
    return "n/a" if v is None else f"{v}{unit}"


def main():
    ap = argparse.ArgumentParser(prog="hypnomix measure", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out")
    a = ap.parse_args()
    outdir = out_at(a.out, "measure"); outdir.mkdir(parents=True, exist_ok=True)
    unreadable = silent = 0
    for f in a.files:
        try:
            m = measure(Path(f))
        except Exception as e:  # keep going over a batch, but remember it failed
            if type(e).__name__ == "AudioReadError":
                print(f"FAIL {e}", file=sys.stderr)
            else:
                print(f"FAIL {f}: {type(e).__name__}: {e}", file=sys.stderr)
            unreadable += 1
            continue
        (outdir / (Path(f).stem + ".json")).write_text(json.dumps(m, indent=2))
        if m.get("silent"):
            silent += 1
            print(f"{Path(f).name}: SILENT: every sample is zero, so there is nothing to measure", file=sys.stderr)
            continue
        fm = m["ffmpeg"]
        print(f"{Path(f).name}: {_fmt(fm['integrated_lufs'])} LUFS (pyln {_fmt(m['pyloudnorm_lufs'])}), "
              f"TP {_fmt(fm['true_peak_dbtp'])} dBTP, LRA {_fmt(fm['lra_lu'])} LU, crest {m['crest_factor_db']} dB, "
              f"{_fmt(m['tempo_bpm_est'])} BPM, {_fmt(m['key_est'])}")
        for n in m.get("notes", []):
            print(f"  note: {n}")
    if unreadable:
        sys.exit(2)
    if silent:
        sys.exit(1)


if __name__ == "__main__":
    main()
