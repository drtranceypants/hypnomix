#!/usr/bin/env python3
"""Ask Matchering what it would change to make a mix sound like a reference, then show it as numbers.

Matchering's output is not meant to be the master. It is a measuring stick: the difference between
your bounce and the matched copy tells you which mastering moves (loudness, tilt, width) close the gap.

Usage:
    hypnomix reference mix.wav reference.wav [--out DIR] [--keep]

Writes <out>/<mix> vs <ref>.md (and the matched WAV with --keep). Prints the same table.
"""
from hypnomix.core.paths import out_at
import argparse, sys, warnings
from pathlib import Path

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")
from hypnomix.ears.measure import measure  # noqa: E402

# 1/3-octave-ish bands for the EQ curve Matchering applied
EQ_BANDS = [(20, 40), (40, 60), (60, 100), (100, 160), (160, 250), (250, 400), (400, 630), (630, 1000),
            (1000, 1600), (1600, 2500), (2500, 4000), (4000, 6300), (6300, 10000), (10000, 16000), (16000, 20000)]


def avg_spectrum(path, n=8192):
    from hypnomix.core import dsp
    y, sr = dsp.load(path)                    # the checked loader: a broken file ends in one sentence
    mono = y.mean(axis=1)
    frames = np.lib.stride_tricks.sliding_window_view(mono, n)[::n] * np.hanning(n)
    spec = (np.abs(np.fft.rfft(frames, axis=1)) ** 2).mean(axis=0)
    return np.fft.rfftfreq(n, 1 / sr), spec


def eq_curve(before, after):
    """dB change per band after loudness-normalising both, i.e. the tonal shape of the EQ."""
    f, a = avg_spectrum(before)
    _, b = avg_spectrum(after)
    a, b = a / a.sum(), b / b.sum()
    return [(lo, hi, 10 * np.log10(b[(f >= lo) & (f < hi)].sum() / (a[(f >= lo) & (f < hi)].sum() + 1e-20) + 1e-20))
            for lo, hi in EQ_BANDS]


def row(name, a, b, unit="", fmt="{:+.1f}"):
    if a is None or b is None:
        return None
    return f"| {name} | {a} | {b} | {fmt.format(b - a)}{unit} |"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mix"); ap.add_argument("reference")
    ap.add_argument("--out")
    ap.add_argument("--keep", action="store_true", help="keep the matched WAV next to the report")
    a = ap.parse_args()

    try:
        import matchering as mg
    except ImportError:
        from hypnomix.extras import hint
        sys.exit(f"reference matching: {hint('reference')}")
    mg.log(lambda *_: None)
    mix, ref = Path(a.mix), Path(a.reference)
    from hypnomix.core.paths import out as _o
    out = out_at(a.out, "match"); out.mkdir(parents=True, exist_ok=True)
    stem = f"{mix.stem} vs {ref.stem}"
    matched = out / f"{stem} (matched).wav"
    print(f"matching {mix.name} → {ref.name} …", file=sys.stderr)
    mg.process(target=str(mix), reference=str(ref), results=[mg.pcm24(str(matched))])

    m_mix, m_match, m_ref = measure(mix), measure(matched), measure(ref)
    g = lambda m, k: m.get(k)
    lines = [f"# {mix.stem} matched to {ref.stem}", "",
             "What Matchering changed to make the mix sound like the reference.", "",
             "| | Mix | Matched | Change |", "|---|---|---|---|"]
    rows = [
        row("Integrated LUFS", m_mix["ffmpeg"]["integrated_lufs"], m_match["ffmpeg"]["integrated_lufs"], " LU"),
        row("True peak dBTP", m_mix["ffmpeg"]["true_peak_dbtp"], m_match["ffmpeg"]["true_peak_dbtp"], " dB"),
        row("LRA", m_mix["ffmpeg"]["lra_lu"], m_match["ffmpeg"]["lra_lu"], " LU"),
        row("Crest factor dB", g(m_mix, "crest_factor_db"), g(m_match, "crest_factor_db"), " dB"),
        row("Spectral centroid Hz", g(m_mix, "spectral_centroid_hz"), g(m_match, "spectral_centroid_hz"), " Hz", "{:+.0f}"),
        row("Side/mid dB (width)", g(m_mix, "stereo_side_to_mid_db"), g(m_match, "stereo_side_to_mid_db"), " dB"),
        row("L/R correlation", g(m_mix, "lr_correlation"), g(m_match, "lr_correlation"), "", "{:+.3f}"),
    ]
    for band in m_mix["band_energy_db"]:
        rows.append(row(f"Band {band} (share dB)", m_mix["band_energy_db"][band], m_match["band_energy_db"][band], " dB"))
    lines += [r for r in rows if r]
    lines += ["", "## EQ shape Matchering applied (loudness removed)", "", "| Band Hz | Change dB |", "|---|---|"]
    for lo, hi, d in eq_curve(mix, matched):
        bar = ("+" if d > 0 else "−") * min(12, int(round(abs(d) * 2)))
        lines.append(f"| {lo}–{hi} | {d:+.1f} {bar} |")
    lines += ["", f"Reference for context: {m_ref['ffmpeg']['integrated_lufs']} LUFS, "
              f"{m_ref['ffmpeg']['true_peak_dbtp']} dBTP, LRA {m_ref['ffmpeg']['lra_lu']}, "
              f"side/mid {m_ref.get('stereo_side_to_mid_db')} dB."]
    text = "\n".join(lines) + "\n"
    (out / f"{stem}.md").write_text(text, encoding="utf-8")
    if not a.keep:
        matched.unlink()
    print(text)


if __name__ == "__main__":
    main()
