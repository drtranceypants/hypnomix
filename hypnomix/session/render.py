#!/usr/bin/env python3
"""Render audio tracks straight from a Live set (.als) to full-length WAVs from bar 1, without opening Live:
clip gain, clip fades and straight-line warps (offset + tempo stretch) baked in; no faders or effects.

Use it to get clean stems for `hypnomix prep` / `automix`, or to re-render after replacing source files
(for example with de-hissed versions).

Usage:
    hypnomix render SET.als [--group "Vocals"] [--tracks "Lead" "Double"] [--out DIR]
                   [--sources DIR] [--tighten 35] [--sr 44100]

  --group     only the audio tracks inside this group (default: every audio track)
  --sources   folder of replacement files named like the originals (<original name>.wav), used when present
  --tighten   auto-fade each clip where it is this many dB below its own peak (silences the hiss before and
              after the performance inside each clip; 35 is a good start for vocals)

Limits: warped clips are rendered from their first and last warp markers (a straight-line stretch); clips
with several warp markers that bend the timing will drift between markers. Unwarped clips are exact.
Output is 32-bit float, so nothing clips.
"""
import argparse, gzip, re, sys
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from hypnomix.core.paths import out_at


def v(n, p):
    e = n.find(p) if n is not None else None
    return e.get("Value") if e is not None else None


def clip_source(c, als, sources):
    fr = c.find("./SampleRef/FileRef")
    path = v(fr, "./Path") or ""
    rel = v(fr, "./RelativePath") or ""
    cand = Path(path) if path and Path(path).exists() else (Path(als).parent / rel)
    if sources:
        alt = Path(sources) / (Path(path or rel).stem + ".wav")
        if alt.exists():
            return alt
    return cand


def render_track(t, als, spb, N, SR, sources, tighten, warn):
    y = np.zeros(N)
    name = v(t, "./Name/EffectiveName")
    for c in t.findall(".//ArrangerAutomation/Events/AudioClip"):
        if v(c, "./Disabled") == "true":
            continue
        s, e, ls = float(v(c, "./CurrentStart")), float(v(c, "./CurrentEnd")), float(v(c, "./Loop/LoopStart"))
        src = clip_source(c, als, sources)
        if not src.exists():
            warn.append(f"{name}: missing file {src.name}")
            continue
        a, sr = sf.read(str(src), always_2d=True)
        a = a.mean(1)
        if v(c, "./IsWarped") == "true":
            m = [(float(w.get("SecTime")), float(w.get("BeatTime"))) for w in c.find("./WarpMarkers")]
            if len(m) > 2:
                warn.append(f"{name}: a clip has {len(m)} warp markers; rendered as a straight stretch")
            (s0, b0), (s1, b1) = m[0], m[-1]
            slope = (s1 - s0) / (b1 - b0) if b1 != b0 else spb
            src0 = s0 + (ls - b0) * slope
            srclen = (e - s) * slope
        else:
            slope, src0, srclen = spb, ls, (e - s) * spb
        seg = a[max(0, int(src0 * sr)): int((src0 + srclen) * sr)]
        if src0 < 0:
            seg = np.concatenate([np.zeros(int(-src0 * sr)), seg])
        ratio = Fraction(spb / slope * SR / sr).limit_denominator(2000)
        if ratio != 1:
            seg = resample_poly(seg, ratio.numerator, ratio.denominator)
        seg = seg * float(v(c, "./SampleVolume") or 1)
        fi = float(v(c, "./Fades/FadeInLength") or 0) * spb * SR       # Live stores clip fades in beats
        fo = float(v(c, "./Fades/FadeOutLength") or 0) * spb * SR
        seg = seg[: int((e - s) * spb * SR)].copy()
        if tighten and len(seg) > SR // 10:
            env = np.sqrt(np.maximum(np.convolve(seg ** 2, np.ones(441) / 441, "same"), 0))
            edb = 20 * np.log10(env + 1e-12)
            on = np.flatnonzero(edb > edb.max() - tighten)
            if len(on):
                a0, f0 = max(0, on[0] - int(0.06 * SR)), int(0.04 * SR)
                b0, f1 = min(len(seg), on[-1] + int(0.12 * SR)), int(0.15 * SR)
                m = np.zeros(len(seg))
                m[a0:b0] = 1
                r0 = slice(max(0, a0 - f0), a0); m[r0] = np.linspace(0, 1, r0.stop - r0.start)
                r1 = slice(b0, min(len(seg), b0 + f1)); m[r1] = np.linspace(1, 0, r1.stop - r1.start)
                seg = seg * m
        if fi >= 1:
            k = min(int(fi), len(seg)); seg[:k] *= np.linspace(0, 1, k)
        if fo >= 1:
            k = min(int(fo), len(seg)); seg[len(seg) - k:] *= np.linspace(1, 0, k)
        i = int(round(s * spb * SR))
        L = min(len(seg), N - i)
        if L > 0:
            y[i:i + L] += seg[:L]
    return y


def main():
    ap = argparse.ArgumentParser(prog="hypnomix render", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als"); ap.add_argument("--group"); ap.add_argument("--tracks", nargs="*")
    ap.add_argument("--out"); ap.add_argument("--sources"); ap.add_argument("--tighten", type=float, default=0)
    ap.add_argument("--sr", type=int, default=44100)
    a = ap.parse_args()
    r = ET.fromstring(gzip.open(a.als).read())
    tempo = float(v(r, ".//Tempo/Manual"))
    spb = 60 / tempo
    tr = list(r.find(".//Tracks"))
    pick = [t for t in tr if t.tag == "AudioTrack"]
    if a.group:
        gids = [t.get("Id") for t in tr if t.tag == "GroupTrack" and v(t, "./Name/EffectiveName") == a.group]
        if not gids:
            sys.exit(f"no group {a.group!r}; groups: {[v(t, './Name/EffectiveName') for t in tr if t.tag == 'GroupTrack']}")
        pick = [t for t in pick if v(t, "./TrackGroupId") == gids[0]]
    if a.tracks:
        want = {x.lower() for x in a.tracks}
        pick = [t for t in pick if v(t, "./Name/EffectiveName").lower() in want]
    ends = [float(v(c, "./CurrentEnd")) for t in pick for c in t.iter("AudioClip")]
    if not ends:
        sys.exit("no audio clips on the chosen tracks")
    N = int((max(ends) + 8) * spb * a.sr)
    od = out_at(a.out, "render", Path(a.als).stem)
    warn = []
    for t in pick:
        n = v(t, "./Name/EffectiveName")
        y = render_track(t, a.als, spb, N, a.sr, a.sources, a.tighten, warn)
        if not np.any(y):
            continue
        safe = re.sub(r'[\\/:*?"<>|]', "-", n)
        sf.write(str(od / f"{safe}.wav"), y.astype(np.float32), a.sr, subtype="FLOAT")
        print(f"{n:<30} peak {20 * np.log10(np.abs(y).max() + 1e-9):6.1f} dBFS")
    for w_ in sorted(set(warn)):
        print("  !", w_, file=sys.stderr)
    print(f"→ {od}")


if __name__ == "__main__":
    main()
