#!/usr/bin/env python3
"""Breath control for ONE vocal file: breaths between phrases are turned down, not removed.

How it finds breaths (same rules as the breath step inside `hypnomix prep`):
 - 10 ms frames; a breath is 150-900 ms of sound that is 14-45 dB below the vocal's loud parts,
   noise-like (spectral flatness > 0.08) and airy (spectral centroid > 1200 Hz).
How it fixes them:
 - Each breath is turned down by --reduce dB with short (~15 ms) fades in and out inside the breath,
   so it still sounds human. Everything outside the breaths is bit-identical.

Usage: hypnomix breaths IN.wav [OUT.wav] [--reduce 8] [--report] [--json OUT.json]
OUT defaults to hypnomix-out/breaths/<name> (breaths).wav. Never overwrites: refuses if OUT is IN or exists.
--report analyses only and writes nothing.
"""
# Detection is copied from hypnomix/studio/prep.py `breaths` (that one needs librosa and returns audio
# only); here it is rewritten with numpy/scipy and returns the events.
import argparse, json, sys
from pathlib import Path
import numpy as np, soundfile as sf
from scipy.signal import stft
from scipy.ndimage import uniform_filter1d

FADE_S = 0.015


def mmss(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _features(m, sr, hop):
    n_fft = hop * 4
    f, _, Z = stft(m, sr, nperseg=n_fft, noverlap=n_fft - hop, boundary="even", padded=True)
    P = np.abs(Z) ** 2 + 1e-20
    flat = np.exp(np.mean(np.log(P), 0)) / np.mean(P, 0)
    mag = np.abs(Z)
    cent = (f[:, None] * mag).sum(0) / (mag.sum(0) + 1e-12)
    e = uniform_filter1d(m ** 2, hop * 2)
    lv = 10 * np.log10(e[::hop] + 1e-18)
    n = min(len(lv), len(flat), len(cent))
    return lv[:n], flat[:n], cent[:n]


def analyse(y, sr):
    """Breath events: list of {t, dur, level_db} (level_db = breath RMS relative to the loud parts)."""
    y = np.asarray(y, dtype=np.float64)
    m = y if y.ndim == 1 else y.mean(axis=1)
    hop = int(0.01 * sr)
    if len(m) < hop * 20 or not np.any(m):
        return []
    lv, flat, cent = _features(m, sr, hop)
    top = np.percentile(lv, 95)
    cand = (lv < top - 14) & (lv > top - 45) & (flat > 0.08) & (cent > 1200)
    d = np.diff(np.concatenate([[0], cand.astype(int), [0]]))
    ev = []
    for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
        if 15 <= b - a <= 90:
            lvl = 10 * np.log10(np.mean(10 ** (lv[a:b] / 10))) - top
            ev.append({"t": round(a * hop / sr, 3), "dur": round((b - a) * hop / sr, 3), "level_db": round(float(lvl), 1)})
    return ev


def process(y, sr, events, reduce_db=8.0):
    """Turn each breath down by reduce_db with short fades inside it; everything else bit-identical."""
    y = np.asarray(y, dtype=np.float64)
    out = y.copy()
    if not events or reduce_db <= 0:
        return out
    floor = 10 ** (-reduce_db / 20)
    for e in events:
        a = int(round(e["t"] * sr)); b = min(len(y), int(round((e["t"] + e["dur"]) * sr)))
        if b <= a:
            continue
        n = b - a
        fl = min(int(FADE_S * sr), n // 2)
        g = np.full(n, floor)
        if fl:
            down = 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, fl))           # raised-cosine 1 -> 0
            g[:fl] = floor + (1 - floor) * down
            g[-fl:] = g[:fl][::-1]
        out[a:b] = y[a:b] * (g if y.ndim == 1 else g[:, None])
    return out


def summary(events, reduce_db, name):
    lines = [f"breaths: {name}"]
    if not events:
        lines.append("  no breaths found between phrases - nothing to do.")
        return lines
    lines.append(f"  {len(events)} breaths, each turned down {reduce_db:g} dB (not removed)")
    lines.append(f"  breath level: average {np.mean([e['level_db'] for e in events]):.1f} dB, loudest"
                 f" {max(e['level_db'] for e in events):.1f} dB vs the vocal's loud parts")
    lines.append("  loudest:")
    for e in sorted(events, key=lambda e: -e["level_db"])[:5]:
        lines.append(f"    {mmss(e['t'])}  ({e['t']:.2f}s, {e['dur'] * 1000:.0f} ms)  {e['level_db']:.1f} dB")
    lines.append("  what to listen for: breaths should sit behind the voice but still be there; if a word's"
                 " start or end got quieter it was mistaken for a breath - lower --reduce or skip that file.")
    return lines


def finding(events, reduce_db, name):
    if not events:
        return []
    loud = max(events, key=lambda e: e["level_db"])
    sev = "medium" if loud["level_db"] > -20 else "low"
    return [{"id": "breaths-1", "kind": "breaths", "severity": sev, "track": name, "where": mmss(loud["t"]),
             "problem": f"{len(events)} breaths between phrases (loudest {loud['level_db']:.1f} dB at {mmss(loud['t'])})",
             "fix": f"turn breaths down {reduce_db:g} dB with short fades (not removed)"}]


def main():
    ap = argparse.ArgumentParser(prog="hypnomix breaths", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inp"); ap.add_argument("out", nargs="?")
    ap.add_argument("--reduce", type=float, default=8.0, help="dB to turn each breath down (default 8)")
    ap.add_argument("--report", action="store_true", help="analyse only, write nothing")
    ap.add_argument("--json", help="write findings + events to this file")
    a = ap.parse_args()
    inp = Path(a.inp)
    y, sr = sf.read(str(inp), always_2d=True, dtype="float64")
    events = analyse(y, sr)
    print("\n".join(summary(events, a.reduce, inp.name)))
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps({"tool": "breaths", "file": str(inp),
                                            "findings": finding(events, a.reduce, inp.name), "events": events}, indent=2))
    if a.report:
        return
    from hypnomix.core.paths import out_at
    dest = Path(a.out) if a.out else out_at(None, "breaths") / f"{inp.stem} (breaths).wav"
    if dest.resolve() == inp.resolve():
        sys.exit("breaths: refusing to overwrite the input file")
    if dest.exists():
        sys.exit(f"breaths: {dest} already exists - refusing to overwrite")
    dest.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dest), process(y, sr, events, a.reduce).astype(np.float32), sr, subtype="FLOAT")
    print(dest)


if __name__ == "__main__":
    main()
