#!/usr/bin/env python3
"""Pick the best take, and build a comp list: which take to use for each section.

Each take is scored on what an engineer listens for when comping:
  clipping       full-scale samples (a hard fail for that section)
  noise          noise floor between phrases, hum
  pitch          (vocals and single-note instruments) median distance from the nearest semitone, in cents
  timing         (with --bpm) how far note onsets land from the 1/16 grid, in ms
  energy         consistency of level (a take that fades out or jumps around scores lower)

Usage:
    hypnomix takes take1.wav take2.wav … [--bpm 92] [--start-beat 0] [--section-bars 4] [--no-pitch] [--out DIR]

All takes must start at the same point (export them from the same bar). --start-beat is the beat (0 = bar 1)
at which the files start, so the grid lines up. Use --no-pitch for drums, strummed chords and pads.
"""
from hypnomix.core.paths import out_at
from hypnomix.core import args as A
import argparse, sys
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.core.paths import out as out_dir


def pitch_track(y, sr):
    import librosa
    m = librosa.resample(y.mean(axis=1), orig_sr=sr, target_sr=16000)
    f0, voiced, _ = librosa.pyin(m, fmin=65, fmax=1100, sr=16000, frame_length=1024, hop_length=160)
    cents = np.full(len(f0), np.nan)
    ok = voiced & np.isfinite(f0)
    midi = 69 + 12 * np.log2(f0[ok] / 440)
    cents[ok] = (midi - np.round(midi)) * 100
    return cents, 0.01                                     # one value per 10 ms


def onsets(y, sr):
    import librosa
    m = y.mean(axis=1)
    return librosa.onset.onset_detect(y=m, sr=sr, units="time", backtrack=False)


def take_metrics(y, sr, bpm, start_beat, do_pitch):
    out = dict(clips_at=np.flatnonzero(np.abs(y).max(axis=1) >= 0.999) / sr,
               floor=dsp.noise_floor_db(y, sr), peak=dsp.sample_peak(y))
    from hypnomix.studio.soundcheck import hum
    out["hum"] = hum(y, sr)[0]
    out["level"] = dsp.block_rms_db(y, sr, 0.5)
    if do_pitch:
        out["cents"], out["cents_dt"] = pitch_track(y, sr)
    if bpm:
        on = onsets(y, sr)
        grid = 60 / bpm / 4
        pos = on / grid + start_beat * 4
        out["onsets"] = on
        out["timing_ms"] = np.abs(pos - np.round(pos)) * grid * 1000
    return out


def section_scores(m, t0, t1, sr):
    """Lower is better. Each component is roughly 'how noticeable is the problem'."""
    s, why = 0.0, []
    nclip = int(np.sum((m["clips_at"] >= t0) & (m["clips_at"] < t1)))
    if nclip:
        s += 100; why.append(f"{nclip} clipped samples")
    if "cents" in m:
        i0, i1 = int(t0 / m["cents_dt"]), int(t1 / m["cents_dt"])
        c = m["cents"][i0:i1]
        c = c[np.isfinite(c)]
        if len(c) > 20:
            v = float(np.median(np.abs(c)))
            s += max(0, v - 8) * 0.6
            if v > 20:
                why.append(f"pitch {v:.0f}¢ off")
        else:
            s += 5                                          # hardly any sung/played notes here
            why.append("mostly silent")
    if "timing_ms" in m:
        k = (m["onsets"] >= t0) & (m["onsets"] < t1)
        if k.sum() >= 3:
            v = float(np.median(m["timing_ms"][k]))
            s += max(0, v - 10) * 0.4
            if v > 25:
                why.append(f"timing {v:.0f} ms off grid")
    lv = m["level"][int(t0 / 0.5): int(t1 / 0.5)]
    lv = lv[lv > lv.max() - 30] if len(lv) else lv
    if len(lv) > 3:
        s += max(0, float(np.std(lv)) - 4) * 0.5
    return s, why


def main():
    ap = argparse.ArgumentParser(prog="hypnomix takes", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("takes", nargs="+")
    ap.add_argument("--bpm", type=A.number(20, 400)); ap.add_argument("--start-beat", type=float, default=0)
    ap.add_argument("--section-bars", type=int, default=4); ap.add_argument("--beats-per-bar", type=int, default=4)
    ap.add_argument("--no-pitch", action="store_true"); ap.add_argument("--out")
    a = ap.parse_args()
    if len(a.takes) < 2:
        sys.exit("give at least two takes")
    sr, data = None, []
    for f in a.takes:
        y, s = dsp.load(f, sr)
        sr = sr or s
        data.append((Path(f).stem, y))
    n = max(len(y) for _, y in data)
    data = [(k, np.pad(y, ((0, n - len(y)), (0, 0)))) for k, y in data]
    print(f"analysing {len(data)} takes …", file=sys.stderr)
    mets = [take_metrics(y, sr, a.bpm, a.start_beat, not a.no_pitch) for _, y in data]

    sec = (a.section_bars * a.beats_per_bar * 60 / a.bpm) if a.bpm else 10.0
    edges = np.arange(0, n / sr, sec)
    comp, overall = [], np.zeros(len(data))
    for t0 in edges:
        t1 = min(t0 + sec, n / sr)
        sc = [section_scores(m, t0, t1, sr) for m in mets]
        vals = np.array([s for s, _ in sc])
        overall += vals
        best = int(np.argmin(vals))
        if all("mostly silent" in w for _, w in sc):
            continue
        comp.append((t0, t1, best, sc))

    lab = (lambda t: f"bar {t / (a.beats_per_bar * 60 / a.bpm) + 1:.0f}") if a.bpm else (lambda t: f"{int(t // 60)}:{t % 60:04.1f}")
    md = ["# Takes report", "", "| take | clipped | noise floor | hum | " + ("pitch (median ¢) | " if not a.no_pitch else "") +
          ("timing (median ms) | " if a.bpm else "") + "score (lower = better) |",
          "|---|---|---|---|" + ("---|" if not a.no_pitch else "") + ("---|" if a.bpm else "") + "---|"]
    for (k, _), m, sc in zip(data, mets, overall):
        row = f"| {k} | {len(m['clips_at'])} | {m['floor']:.0f} dBFS | {m['hum']:.0f} dB | "
        if "cents" in m:
            c = m["cents"][np.isfinite(m["cents"])]
            row += f"{np.median(np.abs(c)):.0f} | " if len(c) else "– | "
        if "timing_ms" in m:
            row += f"{np.median(m['timing_ms']):.0f} | " if len(m["timing_ms"]) else "– | "
        md.append(row + f"{sc:.0f} |")
    best = int(np.argmin(overall))
    md += ["", f"**Best whole take: {data[best][0]}**", "", "## Comp list (best take per section)", "",
           "| from | to | use | why not the others |", "|---|---|---|---|"]
    for t0, t1, b, sc in comp:
        others = "; ".join(f"{data[i][0]}: {', '.join(w)}" for i, (_, w) in enumerate(sc) if i != b and w)
        md.append(f"| {lab(t0)} | {lab(t1)} | {data[b][0]} | {others} |")
    md += ["", "In Live 12: put the takes in take lanes on one track, then swipe each section from the take listed here. "
           "The numbers find problems; your ears pick the performance. A slightly pitchy take with feeling often wins."]
    text = "\n".join(md) + "\n"
    od = out_at(a.out, "takes")
    (od / "TAKES.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
