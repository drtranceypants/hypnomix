#!/usr/bin/env python3
"""Compare a mix with a reference track and list what to try - proposals, not processing.

Both tracks are compared at matched loudness, using the loudest ~45 s of each (the part that
decides how a track "sounds"). It measures:
  - energy in 8 named bands (sub, bass, upper bass, low-mid, mid, upper-mid, presence, air),
    each relative to the track's own total, so overall level does not matter; the gap per band is then
    taken against the median gap, so one heavy band is not also reported as every other band being light;
  - loudness range (LRA-style, from 3 s short-term loudness), crest factor (peak minus RMS);
  - stereo width (side energy relative to mid) and low-end mono-ness (L/R correlation below 150 Hz);
  - integrated loudness and true peak (whole file).

Each meaningful gap (band > 1.5 dB, width > 2 dB, crest > 2 dB, ...) becomes a finding with one
concrete, modest move. Moves are capped at 3 dB; when the gap is bigger, the finding says one move
should not close it and points at the arrangement or the source instead.

How this differs from `hypnomix reference`: that command runs an optional matching engine and reads
off what it changed; `match` needs no extra dependency, measures both tracks directly, and emits
findings (ids match-N) for the scan -> review workflow. Nothing is written but the report.

Usage:
    hypnomix match MIX.wav REFERENCE.wav [--json OUT.json] [--out DIR]
"""
from hypnomix.core.paths import out_at
import argparse, json, sys, warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
from hypnomix.core import dsp  # noqa: E402

BANDS = [("sub", 20, 60), ("bass", 60, 120), ("upper bass", 120, 250), ("low-mid", 250, 500),
         ("mid", 500, 2000), ("upper-mid", 2000, 4000), ("presence", 4000, 8000), ("air", 8000, 20000)]
MOVE = {  # band -> (filter, freq, where to try it)
    "sub": ("low shelf", 60, "the kick/bass or the mix bus"),
    "bass": ("low shelf", 100, "the bass group, or check the kick/bass balance"),
    "upper bass": ("bell", 180, "bass, guitars or keys"),
    "low-mid": ("bell", 350, "guitars, keys and pads (the usual mud)"),
    "mid": ("bell", 1000, "the instruments carrying the midrange"),
    "upper-mid": ("bell", 3000, "guitars, synths or the vocal bite"),
    "presence": ("bell", 6000, "the vocal and cymbals"),
    "air": ("high shelf", 10000, "the mix bus or the vocal"),
}
WINDOW_S = 45.0


def loudest(y, sr, win=WINDOW_S):
    """The loudest `win` seconds (by 1 s RMS), or the whole track if shorter."""
    n = int(win * sr)
    if len(y) <= n:
        return y
    b = dsp.block_rms_db(y, sr, 1.0)
    p = 10 ** (b / 10)
    k = int(win)
    s = np.convolve(p, np.ones(k), "valid")
    i = int(np.argmax(s))
    return y[i * sr:i * sr + n]


def short_term_lra(y, sr):
    n, hop = 3 * sr, sr
    if len(y) < n:
        return 0.0
    vals = []
    for i in range(0, len(y) - n + 1, hop):
        v = dsp.rms_db(y[i:i + n]) - 0.7
        if v > -70:
            vals.append(v)
    vals = np.array(vals)
    if len(vals) < 3:
        return 0.0
    vals = vals[vals > 10 * np.log10(np.mean(10 ** (vals / 10))) - 20]
    return float(np.percentile(vals, 95) - np.percentile(vals, 10))


def numbers(y, sr, whole):
    y = dsp.stereo(y)
    seg = loudest(y, sr)
    seg = seg * dsp.undb(-23 - dsp.lufs(seg, sr))     # matched loudness
    E, _ = dsp.band_energy(seg, sr, [(lo, hi) for _, lo, hi in BANDS])
    rel = 10 * np.log10(E / E.sum() + 1e-20)
    mid, side = (seg[:, 0] + seg[:, 1]) / 2, (seg[:, 0] - seg[:, 1]) / 2
    return {
        "bands_db": {name: round(float(v), 2) for (name, _, _), v in zip(BANDS, rel)},
        "lra_lu": round(short_term_lra(seg, sr), 1),
        "crest_db": round(dsp.sample_peak(seg) - dsp.rms_db(seg), 1),
        "width_side_mid_db": round(dsp.rms_db(side) - dsp.rms_db(mid), 1),
        "low_corr_150": round(dsp.correlation(seg, sr, below=150), 2),
        "integrated_lufs": round(dsp.lufs(whole, sr), 1),
        "true_peak_dbtp": round(dsp.true_peak(whole, sr), 1),
        "window_s": round(len(seg) / sr, 1),
    }


def analyse(mix_path, ref_path):
    y, sr = dsp.load(mix_path)
    r, _ = dsp.load(ref_path, sr)
    y, r = dsp.stereo(y), dsp.stereo(r)
    M, R = numbers(y, sr, y), numbers(r, sr, r)
    findings = []

    def add(kind, sev, problem, fix, where="loudest section"):
        findings.append({"id": f"match-{len(findings) + 1}", "tool": "match", "kind": kind, "severity": sev,
                         "track": "mix", "where": where, "problem": problem, "fix": fix, "applies": "manual"})

    raw = {k: M["bands_db"][k] - R["bands_db"][k] for k in M["bands_db"]}
    off = float(np.median(list(raw.values())))   # one band boosted shifts every share; judge each band against the rest
    for name, lo, hi in BANDS:
        d = raw[name] - off
        if abs(d) <= 1.5:
            continue
        kind_f, f0, target = MOVE[name]
        move = min(3.0, round(abs(d) * 0.66, 1))
        verb = "cut" if d > 0 else "boost"
        word = "heavier" if d > 0 else "lighter"
        k = lambda x: f"{x / 1000:g}k" if x >= 1000 else str(x)
        rng = f"{k(lo)}-{k(hi)} Hz"
        fix = f"try a {move:.1f} dB {kind_f} {verb} at {f0 if f0 < 1000 else f'{f0 // 1000}k'} Hz on {target}"
        if abs(d) > 4.5:
            fix += (f"; the gap is {abs(d):.1f} dB, more than one move should close - check the arrangement or the "
                    "source sounds, then re-measure")
        add(f"band-{name.replace(' ', '-')}", "medium" if abs(d) > 3 else "low",
            f"your mix is {abs(d):.1f} dB {word} than the reference in the {name} ({rng}), against its other bands",
            fix, where=name)
    dw = M["width_side_mid_db"] - R["width_side_mid_db"]
    if abs(dw) > 2:
        word = "narrower" if dw < 0 else "wider"
        fix = (f"widen gently: pan doubles and pads further out, or raise the side signal up to {min(3, abs(dw) * 0.66):.1f} dB "
               "on the mix bus (check mono afterwards)" if dw < 0 else
               f"narrow gently: bring wide pads/reverbs in, or lower the side signal up to {min(3, abs(dw) * 0.66):.1f} dB "
               "on the mix bus")
        if abs(dw) > 4.5:
            fix += f"; the gap is {abs(dw):.1f} dB, too big for one bus move - fix it in the panning"
        add("width", "medium" if abs(dw) > 3 else "low",
            f"your mix is {abs(dw):.1f} dB {word} than the reference (side vs mid: {M['width_side_mid_db']:+.1f} vs "
            f"{R['width_side_mid_db']:+.1f} dB)", fix)
    if M["low_corr_150"] < 0.8 and R["low_corr_150"] - M["low_corr_150"] > 0.1:
        add("low-mono", "medium", f"your low end is less mono than the reference (correlation below 150 Hz "
            f"{M['low_corr_150']:.2f} vs {R['low_corr_150']:.2f})",
            "make the bass and kick mono below about 120 Hz, or check for a wide low synth or stereo bass reverb")
    dc = M["crest_db"] - R["crest_db"]
    if abs(dc) > 2:
        if dc > 0:
            fix = (f"your peaks stick out more: try 1-2 dB more gain reduction on the drum or mix bus compressor, "
                   f"or a little peak limiting (aim to close at most 3 dB of the {dc:.1f} dB)")
        else:
            fix = "your mix is more squashed: back off bus compression or limiting by 1-2 dB of gain reduction"
        add("crest", "medium" if abs(dc) > 4 else "low",
            f"crest factor is {abs(dc):.1f} dB {'higher' if dc > 0 else 'lower'} than the reference "
            f"({M['crest_db']} vs {R['crest_db']} dB)", fix)
    dl = M["lra_lu"] - R["lra_lu"]
    if abs(dl) > 3:
        add("loudness-range", "low",
            f"loudness range in the loudest section is {abs(dl):.1f} LU {'wider' if dl > 0 else 'narrower'} than the "
            f"reference ({M['lra_lu']} vs {R['lra_lu']} LU)",
            "ride the quiet passages up a little" if dl > 0 else "let the dynamics breathe: less bus compression or fewer rides")
    di = M["integrated_lufs"] - R["integrated_lufs"]
    if abs(di) > 2:
        add("loudness", "info" if abs(di) < 4 else "low",
            f"integrated loudness is {abs(di):.1f} LU {'above' if di > 0 else 'below'} the reference "
            f"({M['integrated_lufs']} vs {R['integrated_lufs']} LUFS)",
            "loudness is a mastering decision; compare by ear at matched level first", where="whole song")
    if M["true_peak_dbtp"] > -1.0:
        add("true-peak", "low", f"true peak is {M['true_peak_dbtp']} dBTP (reference {R['true_peak_dbtp']})",
            "leave at least 1 dB of true-peak headroom for lossy encoding", where="whole song")
    nums = {"mix": M, "reference": R, "band_gap_db": {k: round(v - off, 2) for k, v in raw.items()}}
    return {"mix": str(mix_path), "reference": str(ref_path), "numbers": nums, "findings": findings}


def table(r):
    M, R = r["numbers"]["mix"], r["numbers"]["reference"]
    rows = ["| measure | mix | reference | diff |", "|---|---|---|---|"]
    for k in M["bands_db"]:
        rows.append(f"| {k} (dB of total) | {M['bands_db'][k]:.1f} | {R['bands_db'][k]:.1f} | "
                    f"{M['bands_db'][k] - R['bands_db'][k]:+.1f} |")
    for k, lab in [("width_side_mid_db", "width side/mid dB"), ("low_corr_150", "correlation <150 Hz"),
                   ("crest_db", "crest dB"), ("lra_lu", "loudness range LU"), ("integrated_lufs", "integrated LUFS"),
                   ("true_peak_dbtp", "true peak dBTP")]:
        rows.append(f"| {lab} | {M[k]} | {R[k]} | {M[k] - R[k]:+.2f} |")
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser(prog="hypnomix match", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mix")
    ap.add_argument("reference")
    ap.add_argument("--json", help="write numbers + findings here")
    ap.add_argument("--out", help="report folder (default hypnomix-out/match/<mix> vs <ref>/)")
    a = ap.parse_args()
    r = analyse(a.mix, a.reference)
    t = table(r)
    lines = [f"- [{f['severity']}] {f['where']}: {f['problem']} - {f['fix']}" for f in r["findings"]] or \
            ["- no gap big enough to act on"]
    print(f"{Path(a.mix).name} vs {Path(a.reference).name}\n\n{t}\n\nProposals:\n" + "\n".join(lines))
    outdir = out_at(a.out, "match", f"{Path(a.mix).stem} vs {Path(a.reference).stem}")
    (outdir / "MATCH.md").write_text(f"# Match: {Path(a.mix).name} vs {Path(a.reference).name}\n\n"
                                     f"Loudest ~{int(WINDOW_S)} s of each, at matched loudness.\n\n{t}\n\n"
                                     "## Proposals\n\n" + "\n".join(lines) + "\n")
    if a.json:
        Path(a.json).write_text(json.dumps(r, indent=2))
    print(f"\nreport: {outdir / 'MATCH.md'}", file=sys.stderr)


if __name__ == "__main__":
    main()
