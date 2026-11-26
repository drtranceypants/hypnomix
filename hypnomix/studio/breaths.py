#!/usr/bin/env python3
"""Breath control for ONE vocal file: breaths between phrases are turned down, not removed.

How it finds breaths (same rules as the breath step inside `hypnomix prep`):
 - 10 ms frames; a breath is 150-900 ms of sound that is 14-45 dB below the vocal's loud parts and clearly
   above the room, with no pitch (a sung note repeats itself, air does not) and airier than this voice's own
   singing. Short air (under a quarter second) straight after a sung sound is the end of a word and is left alone. Brightness is
   judged against the file itself, so dark microphones and dark voices work too.
How it fixes them:
 - Each breath is turned down by --reduce dB with short (~15 ms) fades in and out inside the breath,
   so it still sounds human. Everything outside the breaths is bit-identical.

Usage: hypnomix breaths IN.wav [OUT.wav] [--reduce 8] [--report] [--json OUT.json]
OUT defaults to hypnomix-out/breaths/<name> (breaths).wav. Never overwrites: refuses if OUT is IN or exists.
--report analyses only and writes nothing.
"""
# numpy/scipy only; returns the events. (`hypnomix prep` has an older breath step with fixed thresholds.)
import argparse, json, sys
from pathlib import Path
import numpy as np, soundfile as sf
from scipy.signal import stft
from scipy.ndimage import uniform_filter1d

FADE_S = 0.015


def mmss(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _features(m, sr, hop):
    """Per 10 ms frame: level (dB), how periodic the sound is (0-1; a sung note is high, air is low), and how
    much of the frame's energy sits in the upper part of THIS voice's own band (its "airiness").

    Everything is measured inside the band the voice actually occupies. Measured over the whole spectrum,
    noisiness comes out as zero on real recordings (the empty top of the spectrum swamps it), and a fixed
    brightness threshold misses dark microphones and dark voices."""
    n_fft = hop * 4
    f, _, Z = stft(m, sr, nperseg=n_fft, noverlap=n_fft - hop, boundary="even", padded=True)
    P = np.abs(Z) ** 2 + 1e-20
    lv = 10 * np.log10(P[f >= 80].sum(0))
    loud = lv > np.percentile(lv, 90)
    spec = 10 * np.log10(P[:, loud].mean(1) if loud.any() else P.mean(1))
    band = (f >= 150) & (spec > spec[f >= 150].max() - 40)            # where the voice has energy
    if band.sum() < 8:
        band = (f >= 150) & (f <= 8000)
    Pb = P[band]
    cum = np.cumsum(10 ** (spec[band] / 10)); split = np.searchsorted(cum, cum[-1] * 0.85)   # top 15% of the voice's energy
    split = int(np.clip(split, 1, band.sum() - 1))
    air = 10 * np.log10(Pb[split:].sum(0) / Pb[:split].sum(0))
    # periodicity: the strongest autocorrelation peak for a pitch between 70 and 500 Hz
    r = np.fft.irfft(P * (f >= 80)[:, None], axis=0)
    lo, hi = int(sr / 500), min(int(sr / 70), r.shape[0] // 2 - 1)
    per = r[lo:hi].max(0) / (r[0] + 1e-20)
    return lv, per, air


def analyse(y, sr):
    """Breath events: list of {t, dur, level_db} (level_db = breath RMS relative to the loud parts)."""
    y = np.asarray(y, dtype=np.float64)
    m = y if y.ndim == 1 else y.mean(axis=1)
    hop = int(0.01 * sr)
    if len(m) < hop * 20 or not np.any(m):
        return []
    lv, per, air = _features(m, sr, hop)
    top = np.percentile(lv, 95)
    # the room: the level of the long silences (over a second). A take with no long silence has no room rule.
    q = np.diff(np.concatenate([[0], (lv < top - 14).astype(int), [0]]))
    long = [lv[a + 20:b - 20] for a, b in zip(np.flatnonzero(q == 1), np.flatnonzero(q == -1)) if b - a > 100]
    floor = float(np.percentile(np.concatenate(long), 25)) if long else -np.inf
    voiced = (lv > top - 12) & (per > 0.6)
    if voiced.sum() < 20:
        return []
    air_voice = np.median(air[voiced])
    # quieter than the singing but clearly above the room, not a pitched sound, and airier than the voice itself
    cand = (lv < top - 14) & (lv > max(top - 45, floor + 6)) & (per < 0.45) & (air > air_voice + 3)
    cand = uniform_filter1d(cand.astype(float), 5) > 0.5                      # bridge and trim 1-2 frame flickers
    d = np.diff(np.concatenate([[0], cand.astype(int), [0]]))
    ev = []
    for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
        if 15 <= b - a <= 90:
            if b - a < 25 and voiced[max(0, a - 8):a].any():   # short air straight after a sung sound: the end of a word ("s", "f")
                continue
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
    from hypnomix.core import dsp, paths
    if a.out and not a.report:
        paths.check_out(a.out)
    y, sr = dsp.load(inp)
    events = analyse(y, sr)
    print("\n".join(summary(events, a.reduce, inp.name)))
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps({"tool": "breaths", "file": str(inp),
                                            "findings": finding(events, a.reduce, inp.name), "events": events}, indent=2), encoding="utf-8")
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
