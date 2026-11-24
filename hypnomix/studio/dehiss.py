#!/usr/bin/env python3
"""Free de-hiss for a single track: a spectral de-noiser plus a smart gate.

Two stages, both gentle by default:
 1. Spectral reduction: learn the hiss spectrum from the track's quietest moments, then turn down only
    the STFT bins that sit near hiss level. Gain per bin is a soft curve (no hard on/off), smoothed over
    time and frequency to avoid "musical noise" (watery chirps). Reduction is capped (--reduce, dB) so the
    instrument itself is never carved out.
 2. Smart fades (expander/gate): where the whole track drops to hiss level, fade down by --gate dB with
    a short fade-in before each note (--attack ms, look-ahead so attacks aren't cut) and a slow fade-out
    after it (--release ms) so reverb-like tails decay naturally.

Usage: hypnomix dehiss IN.wav [OUT.wav] [--reduce 12] [--gate 18] [--attack 20] [--release 150]
       [--profile NOISE.wav] [--report]
OUT defaults to hypnomix-out/dehiss/<name> (dehiss).wav. Use --gate 0 on parts that must keep their room tone.
Digital silence (exact zeros, e.g. gaps between clips in a render) is ignored when learning the hiss.
"""
import argparse, json
import numpy as np, soundfile as sf
from scipy.ndimage import uniform_filter1d, maximum_filter1d, uniform_filter
from scipy.signal import stft, istft

N_FFT, HOP = 2048, 512


def learn_noise(mag, frame_db, pct=10):
    """Median spectrum of the quietest frames (ignoring digital silence)."""
    live = frame_db > -120
    if live.sum() < 10:
        return None, None
    thr = np.percentile(frame_db[live], pct)
    sel = live & (frame_db <= thr)
    return np.median(mag[:, sel], axis=1), thr


def spectral(x, sr, reduce_db, noise=None, sens=2.0):
    f, t, Z = stft(x, sr, nperseg=N_FFT, noverlap=N_FFT - HOP)
    mag = np.abs(Z)
    fdb = 10 * np.log10((mag ** 2).mean(0) + 1e-20)
    if noise is None:
        noise, _ = learn_noise(mag, fdb)
    if noise is None:
        return x, None
    # soft mask: 1 well above the hiss, falls to the floor at the hiss level
    snr = mag / (noise[:, None] * sens + 1e-12)
    floor = 10 ** (-reduce_db / 20)
    g = np.clip((snr - 1) / 2, 0, 1)          # 0 at hiss*sens, 1 at 3x that
    g = floor + (1 - floor) * g
    g = uniform_filter(g, size=(3, 5))          # smooth across 3 bins x 5 frames -> no chirps
    y = istft(Z * g, sr, nperseg=N_FFT, noverlap=N_FFT - HOP)[1][: len(x)]
    return np.pad(y, (0, len(x) - len(y))), noise


def gate(x, sr, depth_db, attack_ms, release_ms, open_above_db):
    """Look-ahead expander: full level when the track is open_above_db over the hiss, else -depth."""
    w = int(0.01 * sr)
    env = np.sqrt(np.maximum(uniform_filter1d(x ** 2, w), 0))   # running means drift below 0 over long silence
    env_db = 20 * np.log10(env + 1e-12)
    live = env_db > -120
    if live.sum() < sr:
        return x, None
    hiss_db = np.percentile(env_db[live], 10)
    open_ = (env_db > hiss_db + open_above_db).astype(float)
    a = int(attack_ms / 1000 * sr)
    open_ = maximum_filter1d(open_, size=2 * a + 1)             # look-ahead: open before the note
    floor = 10 ** (-depth_db / 20)
    target = floor + (1 - floor) * open_
    # smooth: fast up (attack), slow down (release) -> one-pole per direction, vectorised in blocks
    up, dn = 1 - np.exp(-1 / max(1, a)), 1 - np.exp(-1 / max(1, int(release_ms / 1000 * sr)))
    g = np.empty_like(target); v = target[0]
    step = 64                                                   # per-block update keeps it fast in Python
    for i in range(0, len(target), step):
        tgt = target[i:i + step].max()
        k = up if tgt > v else dn
        v = v + (1 - (1 - k) ** step) * (tgt - v)
        g[i:i + step] = v
    g = uniform_filter1d(g, step * 2)
    return x * g, hiss_db


def main():
    ap = argparse.ArgumentParser(prog="hypnomix dehiss", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inp"); ap.add_argument("out", nargs="?")
    ap.add_argument("--reduce", type=float, default=12); ap.add_argument("--gate", type=float, default=18)
    ap.add_argument("--attack", type=float, default=20); ap.add_argument("--release", type=float, default=150)
    ap.add_argument("--open", type=float, default=10, help="dB over hiss at which the gate opens")
    ap.add_argument("--profile"); ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    x, sr = sf.read(a.inp, always_2d=True)
    noise = None
    if a.profile:
        p, _ = sf.read(a.profile, always_2d=True)
        _, _, Zp = stft(p.mean(1), sr, nperseg=N_FFT, noverlap=N_FFT - HOP); noise = np.median(np.abs(Zp), axis=1)
    out = np.zeros_like(x); info = {}
    for c in range(x.shape[1]):
        y = x[:, c]
        if a.reduce > 0:
            y, _ = spectral(y, sr, a.reduce, noise)
        if a.gate > 0:
            y, h = gate(y, sr, a.gate, a.attack, a.release, a.open)
            info["hiss_db"] = None if h is None else round(float(h), 1)
        out[:, c] = y
    from pathlib import Path
    from hypnomix.core.paths import out as out_dir
    dest = Path(a.out) if a.out else out_dir("dehiss") / f"{Path(a.inp).stem} (dehiss).wav"
    dest.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dest), out.astype(np.float32), sr, subtype="FLOAT")
    print(dest)
    if a.report:
        def q(z):
            e = 20 * np.log10(np.sqrt(np.maximum(uniform_filter1d(z.mean(1) ** 2, int(0.05 * sr)), 0)) + 1e-12)
            e = e[e > -120]; return round(float(np.percentile(e, 10)), 1), round(float(np.percentile(e, 95)), 1)
        info.update({"in_floor_loud": q(x), "out_floor_loud": q(out)})
        print(json.dumps(info))


if __name__ == "__main__":
    main()
