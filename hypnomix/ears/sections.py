#!/usr/bin/env python3
"""Find the song's sections from the audio alone and check the arc: does the second chorus lift,
does a repeat drop away, is the whole song one flat level?

How it works: the beat grid is tracked (or taken from --bpm), grouped into 4-beat bars, and each bar
gets a feature vector (loudness, brightness, timbre, chroma). A novelty curve on the bar
self-similarity matrix finds where the music changes; boundaries land on bar lines, 4-12 sections.
Sections that sound alike get the same letter (A, B, C...). The loudest letter that repeats is
marked "chorus-like" - a guess from the audio, never more than that.

For each section it prints start-end, bars, label, loudness (LUFS), sample peak and brightness
(spectral centroid), then findings in plain words: repeats that drop or jump in level, the loudest
section, a flat arc. With --vocal (a vocal stem that starts at the same point as the mix) it also
reports vocal-to-band balance per section (vocal LUFS minus the rest of the mix) and flags sections
more than 2 dB off the song's median - the vocal getting buried in the big chorus, or poking out of
a sparse verse.

Read-only: writes SECTIONS.md (and --json) into the report folder.

Usage:
    hypnomix sections MIX.wav [--bpm N] [--vocal VOCAL.wav] [--json OUT.json] [--out DIR]
"""
from hypnomix.core.paths import out_at, check_out
import argparse, json, sys, warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
import librosa  # noqa: E402
from scipy.cluster.hierarchy import linkage, fcluster  # noqa: E402
from scipy.signal import find_peaks  # noqa: E402

from hypnomix.core import dsp  # noqa: E402

FEAT_SR = 22050
HOP = 512


def mss(t):
    t = max(0.0, float(t))
    return f"{int(t // 60)}:{int(t % 60):02d}"


def ordinal(n):
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def bar_grid(mono, sr, bpm=None):
    """Bar start times (s), 4 beats per bar. With --bpm the grid is fixed from the first strong onset."""
    dur = len(mono) / sr
    if bpm:
        if not (isinstance(bpm, (int, float)) and 20 <= bpm <= 400):   # nan, inf and 1e9 made a grid of billions of beats
            raise ValueError(f"the tempo {bpm} is not a number from 20 to 400")
        onset = librosa.onset.onset_strength(y=mono, sr=sr, hop_length=HOP)
        ot = librosa.frames_to_time(np.arange(len(onset)), sr=sr, hop_length=HOP)
        beat = 60.0 / bpm
        # phase: the offset within one beat where onsets line up best
        phases = np.linspace(0, beat, 48, endpoint=False)
        score = [onset[np.clip(np.round((np.arange(p, dur, beat)) * sr / HOP).astype(int), 0, len(onset) - 1)].sum()
                 for p in phases]
        p0 = phases[int(np.argmax(score))]
        # first beat on that grid after the music starts (downbeat is assumed to be the first strong onset)
        e = dsp.block_rms_db(mono, sr, 0.05)                  # music starts where the level first comes up
        first = 0.05 * int(np.argmax(e > e.max() - 40))
        start = p0 + beat * max(0, int(np.floor((first - p0) / beat + 0.25)))
        beats = np.arange(start, dur, beat)
    else:
        _, bf = librosa.beat.beat_track(y=mono, sr=sr, hop_length=HOP, units="frames")
        beats = librosa.frames_to_time(bf, sr=sr, hop_length=HOP)
        if len(beats) < 16:   # no usable beat: fall back to 2 s "bars"
            return np.arange(0, dur, 2.0), None
        bpm = 60.0 / np.median(np.diff(beats))
    bars = beats[::4]
    if len(bars) and bars[0] > 0.5:
        bars = np.concatenate([[0.0], bars])
    else:
        bars = np.concatenate([[0.0], bars[1:]]) if len(bars) else np.array([0.0])
    return bars, float(bpm)


def bar_features(mono, sr, bars, raw=False):
    """Per-bar features, each column scaled to unit spread. With raw=True also returns the unscaled rows
    (loudness/6 dB, centroid in octaves, MFCC/10, chroma*2) so a real change can be told from noise."""
    S = np.abs(librosa.stft(mono, n_fft=2048, hop_length=HOP))
    rms = librosa.feature.rms(S=S)[0]
    cent = librosa.feature.spectral_centroid(S=S, sr=sr)[0]
    mfcc = librosa.feature.mfcc(S=librosa.power_to_db(librosa.feature.melspectrogram(S=S ** 2, sr=sr)), n_mfcc=13)
    chroma = librosa.feature.chroma_stft(S=S ** 2, sr=sr)
    edges = np.append(bars, len(mono) / sr)
    fr = np.clip(librosa.time_to_frames(edges, sr=sr, hop_length=HOP), 0, S.shape[1])
    rows = []
    for a, b in zip(fr[:-1], fr[1:]):
        b = max(b, a + 1)
        sl = slice(a, b)
        rows.append(np.concatenate([
            [20 * np.log10(np.mean(rms[sl]) + 1e-9) / 6.0, np.log2(np.mean(cent[sl]) + 1.0)],
            mfcc[1:, sl].mean(axis=1) / 10.0,
            chroma[:, sl].mean(axis=1) * 2.0,
        ]))
    R = np.array(rows)
    sd = R.std(axis=0)
    F = (R - R.mean(axis=0)) / np.where(sd > 1e-9, sd, 1.0)
    return (F, R) if raw else F


def segment(F, kmin=4, kmax=12):
    """Boundaries (bar indices, including 0 and len) from a checkerboard novelty on the bar SSM."""
    return segment_found(F, kmin, kmax)[0]


# a change counts as real when the average bar on each side of it differs by at least this much in the
# unscaled features (0.6 = about 3.6 dB of loudness, or a comparable shift in brightness or tone colour).
# A song that never changes differs by 0.05-0.2 there; a loud/quiet section change by 5 or more.
MIN_CHANGE = 0.6


def block_change(R, p, k=4):
    """How far apart the bars just before and just after bar p are, in unscaled feature units."""
    k = max(1, min(k, p, len(R) - p))
    return float(np.linalg.norm(R[p - k:p].mean(axis=0) - R[p:p + k].mean(axis=0)))


def even_cut(n, kmin, keep=()):
    b = sorted(set([0, n] + [int(x) for x in keep]))
    while len(b) - 1 < kmin:
        i = int(np.argmax(np.diff(b)))
        if b[i + 1] - b[i] < 2:
            break
        b.insert(i + 1, (b[i] + b[i + 1]) // 2)
    return b


def segment_found(F, kmin=4, kmax=12, raw=None):
    """(boundaries, found): found is False when no clear change was heard and the song was cut evenly.
    raw: the unscaled bar features from bar_features(raw=True); with them a change must be big in real units
    (not just big after every column was stretched to the same spread), so a flat song is not split."""
    n = len(F)
    if n < 2 * kmin:
        return (list(range(0, n, max(1, n // max(1, n // 2)))) + [n] if n > 1 else [0, n]), False
    D = np.linalg.norm(F[:, None] - F[None], axis=2)
    S = -D
    L = 4 if n >= 24 else 2
    g = np.outer(np.r_[-np.ones(L), np.ones(L)], np.r_[-np.ones(L), np.ones(L)])
    nov = np.zeros(n)
    for i in range(L, n - L + 1):
        nov[i] = (S[i - L:i + L, i - L:i + L] * g).sum()   # S = -distance: within-block high, across low
    nov = np.maximum(nov, 0)
    peaks, _ = find_peaks(nov, distance=4)
    peaks = peaks[(peaks >= 2) & (peaks <= n - 2)]
    if raw is not None:
        peaks = np.array([p for p in peaks if block_change(raw, int(p)) >= MIN_CHANGE], dtype=int)
    if not len(peaks):
        # nothing in the audio changes clearly: cut evenly and say so
        return even_cut(n, kmin), False
    order = peaks[np.argsort(nov[peaks])[::-1]]
    thr = 0.3 * nov[order[0]]
    keep = [p for p in order if nov[p] >= thr][: kmax - 1]
    if len(keep) < kmin - 1:
        keep = list(order[: kmin - 1])
        if len(keep) < kmin - 1:   # too few change points: split the longest sections evenly on bars
            return even_cut(n, kmin, keep), bool(keep)   # real change points were found: say so
    return sorted(set([0, n] + [int(p) for p in keep])), True


def group(F, bounds):
    """Letter per section by timbre/harmony similarity (loudness left out so a quieter repeat still matches)."""
    V = np.array([F[a:b, 1:].mean(axis=0) for a, b in zip(bounds[:-1], bounds[1:])])
    if len(V) < 2:
        return ["A"] * len(V)
    Z = linkage(V, "average")
    d = np.linalg.norm(V[:, None] - V[None], axis=2)
    cut = 0.45 * d.max()
    ids = fcluster(Z, cut, "distance")
    seen, out = {}, []
    for i in ids:
        if i not in seen:
            seen[i] = chr(ord("A") + len(seen))
        out.append(seen[i])
    return out


def analyse(path, bpm=None, vocal=None):
    y, sr = dsp.load(path)
    y = dsp.stereo(y)
    mono = librosa.resample(y.mean(axis=1), orig_sr=sr, target_sr=FEAT_SR) if sr != FEAT_SR else y.mean(axis=1)
    bars, bpm_used = bar_grid(mono, FEAT_SR, bpm)
    F, R = bar_features(mono, FEAT_SR, bars, raw=True)
    bounds, found = segment_found(F, raw=R)
    labels = group(F, bounds)
    dur = len(y) / sr
    edges = np.append(bars, dur)
    v = None
    if vocal:
        v, vsr = dsp.load(vocal, sr)
        v = dsp.stereo(v)
        v = np.pad(v, ((0, max(0, len(y) - len(v))), (0, 0)))[: len(y)]
    secs, count = [], {}
    for i, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
        t0, t1 = float(edges[a]), float(edges[b])
        seg = y[int(t0 * sr):int(t1 * sr)]
        count[labels[i]] = count.get(labels[i], 0) + 1
        m = seg.mean(axis=1)
        spec = np.abs(np.fft.rfft(m[: min(len(m), 2 ** 20)]))
        f = np.fft.rfftfreq(min(len(m), 2 ** 20), 1 / sr)
        s = {"n": i + 1, "start": round(t0, 2), "end": round(t1, 2), "start_mss": mss(t0), "end_mss": mss(t1),
             "bars": int(b - a), "label": labels[i], "repeat": count[labels[i]],
             "lufs": round(dsp.lufs(seg, sr), 1), "peak_dbfs": round(dsp.sample_peak(seg), 1),
             "brightness_hz": round(float((f * spec ** 2).sum() / ((spec ** 2).sum() + 1e-20)))}
        if v is not None:
            vs = v[int(t0 * sr):int(t1 * sr)]
            vl, rl = dsp.active_lufs(vs, sr), dsp.active_lufs(seg - vs, sr)
            s["vocal_lufs"], s["band_lufs"] = round(vl, 1), round(rl, 1)
            s["vocal_minus_band_db"] = round(vl - rl, 1) if vl > -60 else None
        secs.append(s)
    totals = {}
    for s in secs:
        totals.setdefault(s["label"], []).append(s)
    repeated = {k: g for k, g in totals.items() if len(g) > 1}
    chorus = max(repeated, key=lambda k: np.mean([s["lufs"] for s in repeated[k]])) if repeated else None
    for s in secs:
        s["role"] = "chorus-like" if s["label"] == chorus else ("intro" if s["n"] == 1 and s["label"] not in repeated else "")
    findings = []

    def add(kind, sev, where, problem, fix, applies="manual"):
        findings.append({"id": f"sections-{len(findings) + 1}", "tool": "sections", "kind": kind, "severity": sev,
                         "track": "mix", "where": where, "problem": problem, "fix": fix, "applies": applies})

    for k, g in ({} if not found else repeated).items():   # letters of an even split mean nothing
        for s in g[1:]:
            d = s["lufs"] - g[0]["lufs"]
            if abs(d) >= 1.5:
                word = "quieter" if d < 0 else "louder"
                tag = " (chorus-like)" if k == chorus else ""
                fix = ("check the automation, arrangement or bus compression on that pass; a repeat that drops "
                       "usually loses lift - match it to the 1st or make the drop deliberate"
                       if d < 0 else "fine if the build is intended; otherwise check rides and bus levels on that pass")
                add("repeat-level", "medium" if abs(d) > 2 else "low", s["start_mss"],
                    f"the {ordinal(s['repeat'])} {k} section{tag} is {abs(d):.1f} LU {word} than the 1st", fix)
    lufs = np.array([s["lufs"] for s in secs])
    if len(secs) > 1:
        lab_l = {k: max(x["lufs"] for x in g) for k, g in totals.items()}
        ranked = sorted(lab_l, key=lab_l.get, reverse=True)
        if len(ranked) > 1 and lab_l[ranked[0]] - lab_l[ranked[1]] >= 3:
            top = max((s for s in secs if s["label"] == ranked[0]), key=lambda s: s["lufs"])
            add("loudest-section", "info", top["start_mss"],
                f"section {ranked[0]} is the loudest by {lab_l[ranked[0]] - lab_l[ranked[1]]:.1f} LU",
                "a strong lift; make sure it is the section you want to hit hardest", "info")
        spread = lufs.max() - lufs.min()
        if spread < 2:
            add("flat-arc", "medium" if spread < 1.2 else "low", secs[int(np.argmax(lufs))]["start_mss"],
                f"the loudest section is only {spread:.1f} LU above the quietest (flat arc)",
                "pull verses or intro down 1-2 dB, or thin their arrangement, so the big sections lift")
    if v is not None:
        bal = [s.get("vocal_minus_band_db") for s in secs if s.get("vocal_minus_band_db") is not None]
        if len(bal) >= 2:
            med = float(np.median(bal))
            for s in secs:
                d = s.get("vocal_minus_band_db")
                if d is not None and abs(d - med) > 2:
                    what = "lower" if d < med else "higher"
                    add("vocal-balance", "medium" if abs(d - med) > 3 else "low", s["start_mss"],
                        f"in section {s['label']} ({s['start_mss']}) the vocal sits {abs(d - med):.1f} dB {what} against "
                        f"the band than the song's median ({d:+.1f} vs {med:+.1f} dB)",
                        f"ride the vocal {'up' if d < med else 'down'} about {min(3, abs(d - med)):.1f} dB there, "
                        f"or {'thin' if d < med else 'fill'} the band in that section")
    return {"file": str(path), "bpm": round(bpm_used, 1) if bpm_used else None, "sections": secs, "findings": findings,
            "even_split": not found,
            "note": None if found else "no clear section changes found; split evenly"}


EVEN_NOTE = ("No clear section changes found; split evenly. The blocks below are equal slices of the song, "
             "not real sections, so read the levels but not the labels.")


def table(r):
    voc = any("vocal_minus_band_db" in s for s in r["sections"])
    head = "| # | time | bars | label | LUFS | peak dBFS | brightness Hz |" + (" vocal-band dB |" if voc else "")
    rows = [head, "|" + "---|" * (head.count("|") - 1)]
    for s in r["sections"]:
        lab = s["label"] + (f" ({s['role']})" if s["role"] else "")
        row = (f"| {s['n']} | {s['start_mss']}-{s['end_mss']} | {s['bars']} | {lab} | {s['lufs']} | "
               f"{s['peak_dbfs']} | {s['brightness_hz']} |")
        if voc:
            vb = s.get("vocal_minus_band_db")
            row += f" {vb:+.1f} |" if vb is not None else " - |"
        rows.append(row)
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser(prog="hypnomix sections", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mix")
    from hypnomix.core import args as A
    ap.add_argument("--bpm", type=A.number(20, 400), help="tempo, if beat tracking gets it wrong (20 to 400)")
    ap.add_argument("--vocal", help="vocal stem that starts at the same point as the mix")
    ap.add_argument("--json", help="write the sections + findings here")
    ap.add_argument("--out", help="report folder (default hypnomix-out/sections/<name>/)")
    a = ap.parse_args()
    check_out(a.out)                                  # an unwritable --out ends here, not after the analysis
    r = analyse(a.mix, a.bpm, a.vocal)
    name = Path(a.mix).stem
    t = table(r)
    lines = [f"- [{f['severity']}] {f['where']}: {f['problem']} - {f['fix']}" for f in r["findings"]] or ["- nothing stands out"]
    head = f"{Path(a.mix).name}: {len(r['sections'])} sections, {r['bpm']} BPM"
    if r.get("even_split"):
        head += f"\n\n{EVEN_NOTE}"
    print(f"{head}\n\n{t}\n\nFindings:\n" + "\n".join(lines))
    outdir = out_at(a.out, "sections", name)
    md = (f"# Sections: {name}\n\nTempo {r['bpm']} BPM. Labels are guesses from the audio: same letter = sounds alike; "
          f"\"chorus-like\" = loudest repeated group.\n\n" + (EVEN_NOTE + "\n\n" if r.get("even_split") else "") + f"{t}\n\n## Findings\n\n" + "\n".join(lines) + "\n")
    (outdir / "SECTIONS.md").write_text(md, encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps(r, indent=2), encoding="utf-8")
    print(f"\nreport: {outdir / 'SECTIONS.md'}", file=sys.stderr)


if __name__ == "__main__":
    main()
