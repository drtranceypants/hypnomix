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

Warped clips are stretched WITHOUT changing pitch, like Live's warp modes (Rubber Band R3 when the
`rubberband` CLI is installed, `brew install rubberband`; otherwise a phase vocoder). Resampling instead
would detune them: a 3% tempo difference is 55 cents. Verified against Live 12 captures: 0 cents, +-0.05 LU.
Every clip edge gets Live's default ~3 ms fade so cuts don't click.

Clips are played like Live: from the start marker, and looped clips wrap from loop end to loop start
(missing this put whole phrases in the wrong place on sets that use looped vocal clips).

Limits: warped clips are rendered from their first and last warp markers (a straight-line stretch); clips
with several warp markers that bend the timing will drift between markers. Unwarped clips are exact.
Output is 32-bit float, so nothing clips. Write re-renders to a NEW folder: Live caches audio by file
path and keeps playing the old audio if you overwrite a file it has loaded.
"""
import argparse, gzip, os, re, shutil, subprocess, sys, tempfile
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


_STRETCH = {}


def stretched(src, k, SR):
    """Whole source file (mono) time-stretched by factor k (output = k x input length), pitch unchanged, at SR."""
    key = (str(src), round(k, 6), SR)
    if key in _STRETCH:
        return _STRETCH[key]
    from hypnomix.core import dsp
    a, sr = dsp.load(src)                  # falls back to ffmpeg for formats soundfile can't read (some .aif loops)
    a = a.mean(1)
    if abs(k - 1) >= 1e-5:
        if shutil.which("rubberband"):
            with tempfile.TemporaryDirectory() as td:
                fi, fo = os.path.join(td, "i.wav"), os.path.join(td, "o.wav")
                sf.write(fi, a.astype(np.float32), sr, subtype="FLOAT")
                subprocess.run(["rubberband", "-3", "-q", "-t", f"{k:.8f}", fi, fo], check=True, capture_output=True)
                a = sf.read(fo, always_2d=True)[0].mean(1)
        else:
            import librosa
            a = librosa.effects.time_stretch(a.astype(np.float32), rate=1 / k)
    if sr != SR:
        ratio = Fraction(SR / sr).limit_denominator(2000)
        a = resample_poly(a, ratio.numerator, ratio.denominator)   # sample-rate change only: pitch-neutral
    _STRETCH[key] = a
    return a


def render_track(t, als, spb, N, SR, sources, tighten, warn):
    y = np.zeros(N)
    name = v(t, "./Name/EffectiveName")
    for c in t.findall(".//ArrangerAutomation/Events/AudioClip"):
        if v(c, "./Disabled") == "true":
            continue
        s, e = float(v(c, "./CurrentStart")), float(v(c, "./CurrentEnd"))
        ls, le = float(v(c, "./Loop/LoopStart")), float(v(c, "./Loop/LoopEnd"))
        start_rel = float(v(c, "./Loop/StartRelative") or 0)       # start marker, relative to the loop start
        loop_on = v(c, "./Loop/LoopOn") == "true"
        src = clip_source(c, als, sources)
        if not src.exists():
            warn.append(f"{name}: missing file {src.name}")
            continue
        if v(c, "./IsWarped") == "true":
            m = [(float(w.get("SecTime")), float(w.get("BeatTime"))) for w in c.find("./WarpMarkers")]
            if len(m) > 2:
                warn.append(f"{name}: a clip has {len(m)} warp markers; rendered as a straight stretch")
            (s0, b0), (s1, b1) = m[0], m[-1]
            slope = (s1 - s0) / (b1 - b0) if b1 != b0 else spb
            to_sec = lambda b, s0=s0, b0=b0, slope=slope: s0 + (b - b0) * slope   # clip beats -> source seconds
            per_beat = 1.0                                     # loop/start values are in beats
        else:
            slope = spb
            to_sec = lambda x: x
            per_beat = 1 / spb                                 # unwarped: loop/start values are in seconds
        k = spb / slope                          # how much longer the clip plays than it was recorded
        try:
            a = stretched(src, k, SR)            # pitch-preserving stretch of the whole source
        except Exception as e_:                  # a file nothing can decode: leave this clip out, say so
            if warn is not None:
                warn.append(f"could not read {Path(src).name} ({type(e_).__name__}): clip left out of the render")
            continue
        clip_len = int((e - s) * spb * SR)
        # play it like Live: start at the start marker; a looped clip wraps from loop end back to loop start
        need = (e - s) * per_beat
        pos = ls + start_rel
        parts = []
        while need > 1e-9 and len(parts) < 10000:
            stop = le if (loop_on and le > pos) else pos + need
            take = min(need, stop - pos)
            i0, i1 = int(round(to_sec(pos) * k * SR)), int(round(to_sec(pos + take) * k * SR))
            piece = a[max(0, i0):max(0, i1)]
            if i0 < 0:
                piece = np.concatenate([np.zeros(min(-i0, i1 - i0)), piece])
            parts.append(piece)
            need -= take
            pos = ls if loop_on else pos + take
        seg = np.concatenate(parts) if parts else np.zeros(0)
        seg = np.pad(seg, (0, max(0, clip_len - len(seg))))[:clip_len]
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
        fi, fo = max(fi, 0.003 * SR), max(fo, 0.003 * SR)           # Live's default ~3 ms edge fades
        kk = min(int(fi), len(seg)); seg[:kk] *= np.linspace(0, 1, kk)
        kk = min(int(fo), len(seg)); seg[len(seg) - kk:] *= np.linspace(1, 0, kk)
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
