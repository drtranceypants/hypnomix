#!/usr/bin/env python3
"""Find the frequency fights between stems: where two parts play at the same time, in the same
band, at similar levels. That is what makes a mix sound crowded or muddy even when every stem
sounds fine soloed.

For each pair it reports the band, how often they collide while both play, and which one should
give way (the less important part, by role), with a concrete cut you can make in EQ Eight.

Usage:
    hypnomix masking STEMS_DIR [--top 12] [--out REPORT.md]
"""
import argparse, itertools, sys
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.engineer import roles

# critical-band-ish analysis bands (Hz)
BANDS = [(40, 80), (80, 160), (160, 315), (315, 630), (630, 1250), (1250, 2500), (2500, 5000), (5000, 10000), (10000, 16000)]
BAND_NAMES = ["40–80 Hz (sub/kick)", "80–160 Hz (bass body)", "160–315 Hz (warmth/mud)", "315–630 Hz (boxiness)",
              "630–1.25k (honk)", "1.25–2.5k (presence)", "2.5–5k (bite/intelligibility)", "5–10k (sizzle/sibilance)",
              "10–16k (air)"]


def band_frames(y, sr, hop_s=0.25, n=4096):
    """Energy per band per frame, dB. Shape (frames, bands)."""
    m = y.mean(axis=1)
    hop = int(hop_s * sr)
    if len(m) < n:
        m = np.pad(m, (0, n - len(m)))
    fr = np.lib.stride_tricks.sliding_window_view(m, n)[::hop] * np.hanning(n)
    P = np.abs(np.fft.rfft(fr, axis=1)) ** 2
    f = np.fft.rfftfreq(n, 1 / sr)
    E = np.stack([P[:, (f >= lo) & (f < hi)].sum(axis=1) for lo, hi in BANDS], axis=1)
    return 10 * np.log10(E + 1e-20)


def load_stems(folder, sr=None):
    files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in dsp.AUDIO_EXT and not p.name.startswith("."))
    stems = []
    for p in files:
        y, s = dsp.load(p, sr)
        sr = sr or s
        if np.max(np.abs(y)) < 1e-5:
            continue
        stems.append((p.stem, y))
    n = max(len(y) for _, y in stems)
    return [(name, np.pad(y, ((0, n - len(y)), (0, 0)))) for name, y in stems], sr


def analyse(stems, sr, role_of=None):
    """stems: [(name, y)] already at their mix levels. Returns a list of collisions, worst first."""
    role_of = role_of or {n: r for n, (r, _) in roles.classify_all(stems, sr).items()}
    frames = {n: band_frames(y, sr) for n, y in stems}
    k = min(len(v) for v in frames.values())
    frames = {n: v[:k] for n, v in frames.items()}
    total = 10 * np.log10(sum(10 ** (v / 10) for v in frames.values()) + 1e-20)   # mix energy per band/frame
    out = []
    for a, b in itertools.combinations(frames, 2):
        A, B = frames[a], frames[b]
        # "significant": the stem carries a real share of the mix in that band (within 10 dB of the total)
        sigA, sigB = A > total - 10, B > total - 10
        close = np.abs(A - B) < 6
        both = sigA & sigB
        hit = both & close
        ownA = 10 * np.log10((10 ** (A / 10)).sum(axis=0) / (10 ** (A / 10)).sum() + 1e-20)   # band share of each stem
        ownB = 10 * np.log10((10 ** (B / 10)).sum(axis=0) / (10 ** (B / 10)).sum() + 1e-20)
        for j in range(len(BANDS)):
            if ownA[j] < -20 or ownB[j] < -20:              # a part with almost nothing in this band can't be masking in it
                continue
            playing = (A[:, j] > total[:, j] - 25) & (B[:, j] > total[:, j] - 25)
            if playing.sum() < 8:
                continue
            frac = hit[:, j].sum() / playing.sum()
            if frac < 0.25:
                continue
            pa, pb = roles.preset(role_of[a])["prio"], roles.preset(role_of[b])["prio"]
            low = {"kick", "bass", "drums"}
            if j <= 1 and (role_of[a] in low) != (role_of[b] in low):   # below 160 Hz the low end always wins
                pa, pb = (1, 0) if role_of[a] in low else (0, 1)
            if pa == pb:                                    # tie: the louder part in that band keeps it
                pa, pb = np.median(A[:, j]), np.median(B[:, j])
            keep, give = (a, b) if pa >= pb else (b, a)
            secs = hit[:, j].sum() * 0.25
            out.append(dict(a=a, b=b, band=j, band_name=BAND_NAMES[j], frac=round(float(frac), 2), seconds=round(secs, 1),
                            keep=keep, give=give, center=float(np.sqrt(BANDS[j][0] * BANDS[j][1])),
                            score=float(frac * secs * (1 + 0.15 * (6 - j if j < 6 else 0)))))
    out.sort(key=lambda d: -d["score"])
    return out, role_of


def advice(c):
    lo, hi = BANDS[c["band"]]
    cut = 2.0 if c["frac"] < 0.5 else 3.0
    q = 1.4 if c["band"] >= 2 else 1.0
    if c["band"] <= 1:
        extra = "or sidechain-duck it 2–4 dB from the other (classic kick ↔ bass fix)"
    elif c["band"] in (5, 6):
        extra = "or use a dynamic EQ band keyed from the other, so the cut only happens when both play"
    else:
        extra = "or pan them apart if both are mono"
    return (f"cut **{c['give']}** {cut:.0f} dB at {c['center']:.0f} Hz (bell, Q {q}) so **{c['keep']}** owns "
            f"{lo}–{hi} Hz; {extra}")


def report(collisions, role_of, top=12):
    lines = ["# Masking report", "", "Stems and the role each was given (name first, then sound):", ""]
    lines += [f"- {n}: {r}" for n, r in role_of.items()]
    lines += ["", f"## Top {min(top, len(collisions))} frequency fights", "",
              "| # | stems | band | collide while both play | fix |", "|---|---|---|---|---|"]
    for i, c in enumerate(collisions[:top], 1):
        lines.append(f"| {i} | {c['a']} ↔ {c['b']} | {c['band_name']} | {int(100 * c['frac'])}% ({c['seconds']} s) | {advice(c)} |")
    if not collisions:
        lines.append("| – | no significant collisions | | | |")
    lines += ["", "Read it like an engineer: fix the top two or three, then listen again. Small cuts (2–3 dB) on the "
              "less important part usually beat boosting the important one."]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(prog="hypnomix masking", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder"); ap.add_argument("--top", type=int, default=12); ap.add_argument("--out")
    a = ap.parse_args()
    stems, sr = load_stems(a.folder)
    if len(stems) < 2:
        sys.exit("need at least two non-silent stems")
    col, role_of = analyse(stems, sr)
    text = report(col, role_of, a.top)
    if a.out:
        Path(a.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
