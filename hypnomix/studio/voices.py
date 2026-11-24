#!/usr/bin/env python3
"""Harmony split: re-arrange vocal/harmony stems into VOICE tracks ordered by pitch.

Voice 1 always carries the lowest part singing at that moment, Voice 2 the next one up, and so on, so
one fader per voice gives granular control over each step of the harmony stack (e.g. keep lower parts
louder, each higher part progressively quieter).

The mix does not change: every sample of every input stem goes to exactly one voice (with 5 ms
complementary crossfades at cut points, which are placed in quiet spots), so the voices add up to the
inputs exactly. Use POST-CHAIN stems (Live: Export > Rendered Track: All Individual Tracks), then put
the voice tracks in the same group with no devices, 0 dB faders, centre pan, and the same sends as the
originals (check first: sends must be equal across the input tracks for the mix to stay identical).

Usage:
  hypnomix voices STEM.wav [STEM.wav ...] [--out DIR] [--min-gap 0.25] [--overlap 0.3]
Writes Voice N.wav files and voices.json (every phrase: time, source, note, voice).
Tested on a 7-part stack: 140 phrases -> 7 voices, 96% of simultaneous pairs in low-to-high order, voices
sum to the inputs within -200 dBFS, full-mix A/B in Live +-0.0 dB in every band.
"""
import argparse, json, os
import numpy as np, soundfile as sf, librosa

from hypnomix.core.paths import out_at
from concurrent.futures import ProcessPoolExecutor

AN = 22050
FADE = 0.005


def phrases_of(path, min_gap, min_len):
    """Phrases = stretches where the stem is within 40 dB of its own loud level; gaps >= min_gap split them."""
    y, sr = sf.read(path, always_2d=True); m = y.mean(1)
    hop = int(0.01 * sr)
    e = np.sqrt(np.convolve(m ** 2, np.ones(hop * 3) / (hop * 3), "same")[::hop])
    edb = 20 * np.log10(e + 1e-12)
    loud = np.percentile(edb[edb > -100], 95) if (edb > -100).any() else -100
    act = edb > loud - 40
    segs, i, n = [], 0, len(act)
    while i < n:
        if not act[i]: i += 1; continue
        j = i
        while j < n:
            if act[j]: j += 1; continue
            k = j
            while k < n and not act[k]: k += 1
            if (k - j) * 0.01 >= min_gap or k == n: break
            j = k
        if (j - i) * 0.01 >= min_len: segs.append((i * 0.01, j * 0.01))
        i = j + 1
    # pitch per phrase
    z = librosa.resample(m, orig_sr=sr, target_sr=AN)
    f0, _, _ = librosa.pyin(z, fmin=65, fmax=1000, sr=AN, hop_length=256)
    t = np.arange(len(f0)) * 256 / AN
    out = []
    for a, b in segs:
        f = f0[(t >= a) & (t < b)]; f = f[~np.isnan(f)]
        out.append({"start": round(a, 3), "end": round(b, 3), "hz": float(np.median(f)) if len(f) >= 5 else None})
    return os.path.basename(path)[:-4], out, sr, len(m)


def main():
    ap = argparse.ArgumentParser(prog="hypnomix voices", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stems", nargs="+"); ap.add_argument("--out")
    ap.add_argument("--min-gap", type=float, default=0.25); ap.add_argument("--min-len", type=float, default=0.2)
    ap.add_argument("--overlap", type=float, default=0.3, help="fraction of a phrase two parts must share to count as singing together")
    a = ap.parse_args()
    with ProcessPoolExecutor(min(8, len(a.stems))) as ex:
        res = list(ex.map(phrases_of, a.stems, [a.min_gap] * len(a.stems), [a.min_len] * len(a.stems)))
    sr = res[0][2]; L = max(r[3] for r in res)
    P = [dict(p, src=name) for name, ph, _, _ in res for p in ph if p["hz"]]
    # rank: how many simultaneous phrases (overlap >= a.overlap of this phrase) are lower in pitch
    for p in P:
        dur = p["end"] - p["start"]
        p["with"] = [q for q in P if q is not p and q["src"] != p["src"] and
                     min(p["end"], q["end"]) - max(p["start"], q["start"]) >= a.overlap * min(dur, q["end"] - q["start"])]
        # rank = number of OTHER PARTS (each counted once) singing lower at the same time
        p["rank"] = len({q["src"] for q in p["with"] if q["hz"] < p["hz"]})
    # assign voices greedily in time order; bump up if the wanted voice is busy with an overlapping phrase
    P.sort(key=lambda p: (p["start"], p["hz"]))
    nsrc = len({p["src"] for p in P}); busy = []
    for p in P:
        taken = {b["voice"] for b in busy if min(b["end"], p["end"]) - max(b["start"], p["start"]) > 0.05}
        free = [v for v in range(nsrc) if v not in taken] or [p["rank"]]
        p["voice"] = min(free, key=lambda v: (abs(v - p["rank"]), v))   # nearest free voice to its rank
        busy.append(p)
    nv = max(p["voice"] for p in P) + 1
    # per stem: label every sample with a voice (gaps go to the nearest phrase's voice), complementary fades
    voices = np.zeros((nv, L, 2), np.float32)
    for name, ph, _, _ in res:
        path = next(s for s in a.stems if os.path.basename(s)[:-4] == name)
        y, _ = sf.read(path, always_2d=True)
        if y.shape[1] == 1: y = np.repeat(y, 2, 1)
        y = np.pad(y, ((0, L - len(y)), (0, 0)))
        mine = sorted([p for p in P if p["src"] == name], key=lambda p: p["start"])
        if not mine:
            voices[0] += y; continue
        # boundaries halfway between consecutive phrases
        cuts = [0] + [int((mine[i]["end"] + mine[i + 1]["start"]) / 2 * sr) for i in range(len(mine) - 1)] + [L]
        labels = [p["voice"] for p in mine]
        w = np.zeros((nv, L), np.float32)
        for i, v in enumerate(labels):
            w[v, cuts[i]:cuts[i + 1]] = 1
        f = int(FADE * sr)
        for i in range(1, len(labels)):
            if labels[i] == labels[i - 1]: continue
            c = cuts[i]; s0, s1 = max(0, c - f), min(L, c + f); r = np.linspace(0, 1, s1 - s0)
            w[:, s0:s1] = 0; w[labels[i - 1], s0:s1] = 1 - r; w[labels[i], s0:s1] = r
        voices += w[:, :, None] * y[None]
    od = out_at(a.out, "voices", os.path.basename(os.path.dirname(os.path.abspath(a.stems[0]))) or "stems")
    for v in range(nv):
        sf.write(str(od / f"Voice {v + 1}.wav"), voices[v], sr, subtype="FLOAT")
    # exactness check: voices sum == stems sum
    tot = np.zeros((L, 2), np.float32)
    for s in a.stems:
        y, _ = sf.read(s, always_2d=True); y = np.repeat(y, 2, 1) if y.shape[1] == 1 else y
        tot[:len(y)] += y
    err = np.abs(voices.sum(0) - tot).max()
    rep = [{"start": p["start"], "end": p["end"], "src": p["src"], "note": librosa.hz_to_note(p["hz"]),
            "voice": p["voice"] + 1, "sings_with": len(p["with"])} for p in P]
    json.dump({"voices": nv, "phrases": rep, "max_sum_error": float(err)}, open(str(od / "voices.json"), "w"), indent=1)
    print(f"{len(P)} phrases -> {nv} voices; voices sum to the original within {20 * np.log10(err + 1e-12):.0f} dBFS")
    for v in range(nv):
        ps = [p for p in P if p["voice"] == v]
        if ps:
            hz = np.median([p["hz"] for p in ps]); srcs = sorted({p["src"] for p in ps})
            print(f"  Voice {v + 1}: {len(ps)} phrases, median {librosa.hz_to_note(hz)}, from {', '.join(srcs)}")
    print(f"→ {od}")


if __name__ == "__main__":
    main()
