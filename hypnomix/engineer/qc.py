#!/usr/bin/env python3
"""Release QC: the checks a mastering engineer runs before a file goes to a distributor.
PASS / WARN / FAIL per check; exit code 1 if anything fails, so it can gate a script.

Usage:
    hypnomix qc master.wav [more.wav …] [--target -14] [--for streaming|cd|vinyl]
"""
import argparse, sys
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix.core import dsp
from hypnomix.engineer.translate import codec_peak


def check(path, target=-14.0, kind="streaming"):
    info = sf.info(str(path))
    y, sr = dsp.load(path)
    res = []
    add = lambda name, status, detail: res.append((name, status, detail))

    bits = {"PCM_16": 16, "PCM_24": 24, "PCM_32": 32, "FLOAT": 32, "DOUBLE": 64}.get(info.subtype, 0)
    if kind == "cd":
        add("Format", "PASS" if (sr == 44100 and bits == 16) else "FAIL", f"{sr} Hz / {info.subtype} (CD needs 44.1 kHz 16-bit)")
    else:
        add("Format", "PASS" if bits >= 16 and sr >= 44100 else "FAIL",
            f"{sr} Hz / {info.subtype}" + (" (24-bit preferred for distributors)" if bits == 16 else ""))
    add("Channels", "PASS" if info.channels == 2 else "WARN", f"{info.channels}")

    dur = len(y) / sr
    add("Duration", "PASS" if dur > 30 else "WARN", f"{int(dur // 60)}:{dur % 60:04.1f}")

    env = np.max(np.abs(y), axis=1)
    on = np.flatnonzero(env > dsp.undb(-60))
    head = on[0] / sr if len(on) else dur
    tail = (len(y) - on[-1]) / sr if len(on) else dur
    add("Leading silence", "PASS" if head < 0.5 else "WARN", f"{head:.2f} s" + (" (trim to < 0.5 s; playlists add their own gaps)" if head >= 0.5 else ""))
    add("Trailing silence", "PASS" if tail < 4 else "WARN", f"{tail:.2f} s")
    last = dsp.db(np.max(np.abs(y[-int(0.05 * sr):])))
    add("Ending", "PASS" if last < -45 else "WARN", f"last 50 ms peak {last:.0f} dBFS" + (" (song is cut off: add a fade)" if last >= -45 else ""))
    first = dsp.db(np.max(np.abs(y[0])))
    add("Start", "PASS" if first < -50 else "WARN", f"first sample at {first:.0f} dBFS" + (" (starts mid-waveform and may click: add a short fade-in)" if first >= -50 else ""))

    dc = np.abs(y.mean(axis=0))
    add("DC offset", "PASS" if dc.max() < 0.001 else "WARN", f"{dsp.db(dc.max()):.0f} dBFS")

    clips = int(np.sum(np.convolve((np.abs(y).max(axis=1) >= 0.9999).astype(int), [1, 1, 1], "valid") == 3))
    add("Clipped runs (3+ full-scale samples)", "PASS" if clips == 0 else "FAIL", str(clips))

    tp = dsp.true_peak(y, sr)
    add("True peak", "PASS" if tp <= -1.0 else "WARN" if tp <= -0.1 else "FAIL", f"{tp:+.2f} dBTP (aim for ≤ -1)")
    L = dsp.lufs(y, sr)
    lim = 1.5 if kind == "streaming" else 4
    add("Loudness", "PASS" if abs(L - target) <= lim else "WARN", f"{L:.1f} LUFS (target {target})")
    st = dsp.block_rms_db(y, sr, 3.0)
    st = st[st > st.max() - 30]
    add("Dynamics (loudness range)", "PASS" if np.ptp(st) > 3 else "WARN", f"{np.ptp(st):.1f} dB short-term spread" +
        (" (very flat: over-limited?)" if np.ptp(st) <= 3 else ""))

    if y.shape[1] == 2:
        c = dsp.correlation(y)
        add("Phase", "PASS" if c > 0.2 else "WARN" if c > 0 else "FAIL", f"L/R correlation {c:+.2f}")
        cl = dsp.correlation(y, sr, 120)
        add("Low end in mono", "PASS" if cl > 0.9 else "WARN" if kind != "vinyl" else "FAIL", f"below 120 Hz {cl:+.2f}")
        lr = dsp.lufs(y[:, :1], sr) - dsp.lufs(y[:, 1:], sr)
        add("L/R balance", "PASS" if abs(lr) < 1 else "WARN", f"{lr:+.1f} dB (L − R)")
    for codec in ("mp3", "aac"):
        p = codec_peak(path, codec)
        if p is not None:
            add(f"{codec.upper()} encode", "PASS" if p < -0.1 else "FAIL", f"peak after encode {p:+.2f} dBTP")
    if kind == "vinyl":
        e, _ = dsp.band_energy(y, sr, [(20, 20000), (8000, 20000)])
        add("Vinyl: top end", "PASS" if 10 * np.log10(e[1] / e[0]) < -14 else "WARN", "bright masters can distort on the inner grooves")
    return res


def main():
    ap = argparse.ArgumentParser(prog="hypnomix qc", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+"); ap.add_argument("--target", type=float, default=-14.0)
    ap.add_argument("--for", dest="kind", choices=["streaming", "cd", "vinyl"], default="streaming")
    a = ap.parse_args()
    bad = 0
    for f in a.files:
        res = check(f, a.target, a.kind)
        fails = sum(s == "FAIL" for _, s, _ in res)
        warns = sum(s == "WARN" for _, s, _ in res)
        bad += fails
        print(f"\n{Path(f).name}: {'FAIL' if fails else 'WARN' if warns else 'PASS'} ({fails} fail, {warns} warn)")
        for name, s, d in res:
            mark = {"PASS": "✓", "WARN": "!", "FAIL": "✗"}[s]
            print(f"  {mark} {name:<38} {d}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
