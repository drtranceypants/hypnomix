#!/usr/bin/env python3
"""Analyse a folder of stems rendered from one song: who contributes what, where.

For each stem: integrated LUFS, peak, active time, band energies, and its share of every band
across the whole song. Optionally (--hz 2770) ranks stems by energy at one frequency, which is
the quickest way to find the source of a resonance.
Usage: hypnomix stems "<Song> Project/Stems" [--hz 2770] [--out STEMS_REPORT.md]
"""
import argparse, sys, warnings
from pathlib import Path

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")
BANDS = [("sub", 20, 60), ("bass", 60, 250), ("lowmid", 250, 500), ("mid", 500, 2000), ("highmid", 2000, 6000), ("air", 6000, 20000)]


def analyse(path, hz):
    from hypnomix.core import dsp
    y, sr = dsp.load(path)
    mono = y.mean(axis=1)
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak < 1e-6:
        return None  # silent stem
    try:
        import pyloudnorm as pyln
        lufs = pyln.Meter(sr).integrated_loudness(y)
    except Exception:
        lufs = float("-inf")
    n = 8192; hop = n
    frames = np.lib.stride_tricks.sliding_window_view(mono, n)[::hop] * np.hanning(n) if len(mono) >= n else np.zeros((1, n))
    spec = (np.abs(np.fft.rfft(frames, axis=1)) ** 2).sum(axis=0)
    f = np.fft.rfftfreq(n, 1 / sr)
    bands = {name: float(spec[(f >= lo) & (f < hi)].sum()) for name, lo, hi in BANDS}
    at_hz = float(spec[(f >= hz * 0.985) & (f <= hz * 1.015)].sum()) if hz else None
    rms_blocks = np.sqrt((frames ** 2).mean(axis=1))
    active = float((rms_blocks > 10 ** (-50 / 20)).mean())
    return {"name": path.stem, "lufs": lufs, "peak_db": 20 * np.log10(peak), "active": active,
            "bands": bands, "at_hz": at_hz, "sr": sr, "seconds": len(y) / sr}


def main():
    ap = argparse.ArgumentParser(prog="hypnomix stems", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter); ap.add_argument("folder"); ap.add_argument("--hz", type=float)
    ap.add_argument("--out"); ap.add_argument("--include-groups", action="store_true",
                                               help="Live also renders group tracks; they are skipped by default to avoid double counting")
    a = ap.parse_args()
    files = sorted(p for p in Path(a.folder).iterdir() if p.suffix.lower() in (".wav", ".aif", ".aiff"))
    from hypnomix.core import dsp

    def one(p):                 # a file hypnomix cannot measure is named and left out, as in masking and scan
        try:
            return analyse(p, a.hz)
        except dsp.AudioReadError as e:
            print(f"skipped {p.name}: {str(e).split('as audio: ', 1)[-1]}", file=sys.stderr)
    rows = [r for r in map(one, files) if r]
    skip = lambda r: (not a.include_groups and ("group" in r["name"].lower() or r["name"].isupper())) or any(k in r["name"].lower() for k in ("master", "main"))
    use = [r for r in rows if not skip(r)]
    tot = {b: sum(r["bands"][b] for r in use) or 1 for b, _, _ in BANDS}
    folder = Path(a.folder).resolve()
    title = folder.name if folder.parent.name == "stems" else folder.parent.name  # separate.py output vs Live export
    lines = [f"# Stems report — {title}", "",
             f"{len(rows)} non-silent stems; {len(use)} used for band shares (groups/master excluded to avoid double counting).", "",
             "| Stem | LUFS | Peak dBFS | Active | " + " | ".join(f"{b} %" for b, _, _ in BANDS) + " |",
             "|---|---|---|---|" + "---|" * len(BANDS)]
    for r in sorted(rows, key=lambda r: -r["lufs"] if np.isfinite(r["lufs"]) else 99):
        shares = " | ".join(f"{100 * r['bands'][b] / tot[b]:.0f}" if not skip(r) else "–" for b, _, _ in BANDS)
        lines.append(f"| {r['name']} | {r['lufs']:.1f} | {r['peak_db']:.1f} | {100 * r['active']:.0f}% | {shares} |")
    if a.hz:
        tot_hz = sum(r["at_hz"] for r in use) or 1
        lines += ["", f"## Who owns {a.hz:g} Hz (±1.5%)", "", "| Stem | share |", "|---|---|"]
        for r in sorted(use, key=lambda r: -r["at_hz"])[:8]:
            lines.append(f"| {r['name']} | {100 * r['at_hz'] / tot_hz:.0f}% |")
    text = "\n".join(lines) + "\n"
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
