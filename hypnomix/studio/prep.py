#!/usr/bin/env python3
"""Prep raw takes into mix-ready stems: the tedious editing pass an assistant engineer does before
anyone touches a fader. Runs automatically at the start of `hypnomix automix`.

Per stem, in this order (each step only acts where it finds a problem, and every fix is logged with a timestamp):
  format       one sample rate, 24-bit, every stem the same length from the same start (bar 1 stays bar 1)
  dc/rumble    DC offset removed, high-pass at 25 Hz
  declip       clipped peaks rebuilt (cubic reconstruction of flattened waveform tops)
  declick      pops, clicks, digital ticks and mouth clicks: isolated impulses repaired by prediction from both sides
               (drum stems are skipped: a drum hit is a transient on purpose)
  plosives     vocal "p"/"b" thumps: low end removed only for the burst
  breaths      vocal breaths between phrases turned down 8 dB (not removed, so it still sounds human)
  hum/hiss     mains hum notched, steady hiss reduced, only on stems that are noisy
  silence      gaps where nothing plays made truly silent, with fades, so the mix isn't full of 20 noisy floors
  fades        short fade at every edit point and at both ends of the file: no clicks anywhere
  mono         stereo files that are really mono (identical L/R) saved as mono
  gain         gain-staged to about -20 LUFS while playing, peaks below -3 dBFS (--keep-levels to skip)
  names        "01 Kick.wav", "02 Snare.wav" …: mix order (drums, bass, music, vocals)

Usage:
    hypnomix prep STEMS_DIR [--out DIR] [--keep-levels] [--no-breaths] [--no-silence] [--no-noise]
    hypnomix prep STEMS_DIR --plan [SCAN_DIR]     change nothing: every move becomes a finding to review
    hypnomix prep FILE.wav --steps declick,noise  only these steps, on one file (what `fix` runs for approved moves)
"""
from hypnomix.core.paths import out_at
import argparse, re, sys
from pathlib import Path

import numpy as np
from scipy.signal import sosfiltfilt
from scipy.interpolate import CubicSpline

from hypnomix.core import dsp
from hypnomix.core.paths import out as out_dir
from hypnomix.engineer import roles

ORDER = ["kick", "snare", "toms", "hats", "overheads", "drums", "bass", "guitar", "keys", "synth", "brass", "pad",
         "other", "fx", "backing_vocal", "lead_vocal"]
VOCAL = {"lead_vocal", "backing_vocal"}
DRUMS = {"kick", "snare", "toms", "hats", "overheads", "drums"}


def ts(i, sr):
    t = i / sr
    return f"{int(t // 60)}:{t % 60:05.2f}"


# ---------------------------------------------------------------- repairs
def declip(y, sr, log):
    peak = np.max(np.abs(y))
    if peak < 0.5:
        return y
    fixed = 0
    first = None
    for c in range(y.shape[1]):
        x = y[:, c]
        hi_, lo_ = x.max(), x.min()
        hot = ((x >= hi_ - 1e-4) & (hi_ > 0.5)) | ((x <= lo_ + 1e-4) & (lo_ < -0.5))
        if hot.sum() < 3:
            continue
        d = np.diff(np.concatenate([[0], hot.astype(int), [0]]))
        starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        for a, b in zip(starts, ends):
            if b - a < 3 or b - a > int(0.004 * sr):
                continue
            k = 8
            lo, hi = max(0, a - k), min(len(x), b + k)
            xi = np.r_[np.arange(lo, a), np.arange(b, hi)]
            if len(xi) < 6:
                continue
            cs = CubicSpline(xi, x[xi])
            est = cs(np.arange(a, b))
            sign = np.sign(x[a])
            x[a:b] = sign * np.maximum(np.abs(est), np.abs(x[a:b]))   # only ever restores the peak upward
            fixed += 1
            first = a if first is None else min(first, a)
    if fixed:
        log.append(f"declip: rebuilt {fixed} clipped peaks (first at {ts(first, sr)})")
    return y


def _ar_coeffs(x, p):
    r = np.correlate(x, x, "full")[len(x) - 1: len(x) + p]
    if r[0] <= 0:
        return np.zeros(p)
    from scipy.linalg import solve_toeplitz
    try:
        return solve_toeplitz(r[:p], r[1:p + 1])
    except Exception:
        return np.zeros(p)


def _ar_fill(x, a, b, p=24, ctx=400):
    """Fill x[a:b] by forward prediction from the left and backward from the right, crossfaded."""
    L = b - a
    left = x[max(0, a - ctx):a]
    right = x[b:b + ctx]
    if len(left) < p * 2 or len(right) < p * 2:
        x[a:b] = np.linspace(x[a - 1] if a else 0, x[b] if b < len(x) else 0, L)
        return
    cf = _ar_coeffs(np.concatenate([left, right]), p)
    fwd = list(left[-p:])
    for _ in range(L):
        fwd.append(np.dot(cf, fwd[-1:-p - 1:-1]))
    bwd = list(right[:p][::-1])
    for _ in range(L):
        bwd.append(np.dot(cf, bwd[-1:-p - 1:-1]))
    f = np.array(fwd[p:]); bk = np.array(bwd[p:])[::-1]
    w = np.linspace(0, 1, L)
    fill = f * (1 - w) + bk * w
    lim = 2 * max(np.max(np.abs(left)), np.max(np.abs(right)), 1e-6)
    if not np.all(np.isfinite(fill)) or np.max(np.abs(fill)) > lim:
        # unstable prediction (it can run away on resonant material): cubic through the neighbours instead
        xi = np.r_[np.arange(a - 6, a), np.arange(b, b + 6)]
        fill = CubicSpline(xi, x[xi])(np.arange(a, b))
        fill = np.clip(fill, -lim, lim)
    x[a:b] = fill


def lpc_residual(m, order=16, block=2048):
    """Prediction error of a short-term linear predictor: smooth musical signals are predictable, clicks are not."""
    from scipy.linalg import solve_toeplitz
    from scipy.signal import lfilter
    e = np.zeros_like(m)
    hop = block // 2
    win = np.hanning(block)
    norm = np.zeros_like(m)
    for s0 in range(0, max(1, len(m) - block), hop):
        x = m[s0:s0 + block]
        xw = x * win
        r = np.correlate(xw, xw, "full")[block - 1: block + order]
        if r[0] < 1e-10:
            continue
        try:
            a = solve_toeplitz(r[:order], r[1:order + 1])
        except Exception:
            continue
        res = lfilter(np.concatenate([[1], -a]), [1], x)
        res[:order] = 0
        e[s0:s0 + block] += res * win
        norm[s0:s0 + block] += win
    return e / np.maximum(norm, 1e-3)


def declick(y, sr, log, sensitivity=8.0):
    """Isolated impulses: linear-prediction error far above its local level, short, and not a note onset."""
    m = y.mean(axis=1)
    e = np.abs(lpc_residual(m))
    blk = max(1, int(0.01 * sr))
    k = len(e) // blk
    if k < 3:
        return y
    med = np.median(e[: k * blk].reshape(k, blk), axis=1) / 0.6745       # robust sigma per 10 ms
    from scipy.ndimage import maximum_filter1d
    scale = np.repeat(maximum_filter1d(med, 3), blk)
    scale = np.pad(scale, (0, len(e) - len(scale)), mode="edge") + 1e-7
    cand = np.flatnonzero(e > sensitivity * scale)
    if not len(cand):
        return y
    groups = np.split(cand, np.flatnonzero(np.diff(cand) > int(0.001 * sr)) + 1)
    fixed, first = 0, None
    maxlen = int(0.004 * sr)
    for g in groups:
        a, b = g[0] - 3, g[-1] + 4
        if b - a > maxlen or a < 500 or b > len(m) - 500:
            continue
        # isolation: voiced singing makes a regular pulse in the prediction error (one per vocal-cord cycle);
        # a click is a one-off, much bigger than any other pulse in the surrounding 25 ms
        pk = e[a:b].max()
        w = int(0.0125 * sr)
        around = np.concatenate([e[max(0, a - w):max(0, a - 8)], e[b + 8:b + w]])
        if len(around) and pk < 2.5 * np.max(around):
            continue
        pre = np.sqrt(np.mean(m[a - int(0.02 * sr):a] ** 2) + 1e-12)
        post = np.sqrt(np.mean(m[b + 10:b + 10 + int(0.02 * sr)] ** 2) + 1e-12)
        if post > pre * 2.5:                    # a note starting, not a click
            continue
        for c in range(y.shape[1]):
            _ar_fill(y[:, c], a, b)
        fixed += 1
        first = a if first is None else first
    if fixed:
        log.append(f"declick: repaired {fixed} clicks/pops (first at {ts(first, sr)})")
    return y


def deplosive(y, sr, log, cutoff=150):
    low = sosfiltfilt(dsp.lowpass(cutoff, sr, 2), y, axis=0)
    bl = dsp.block_rms_db(low, sr, 0.02)
    ball = dsp.block_rms_db(y, sr, 0.02)
    act = ball > ball.max() - 40
    if act.sum() < 10:
        return y
    typ = np.median(bl[act])
    hit = act & (bl > typ + 12) & (bl > ball - 6)
    if not hit.any():
        return y
    from scipy.ndimage import binary_dilation, uniform_filter1d
    hit = binary_dilation(hit, iterations=2)
    g = uniform_filter1d(hit.astype(float), 3)
    blk = int(0.02 * sr)
    g = np.pad(np.repeat(g, blk), (0, max(0, len(y) - len(g) * blk)))[: len(y)]
    n = int(np.sum(np.diff(np.concatenate([[0], hit.astype(int)])) == 1))
    log.append(f"plosives: removed the low-frequency thump from {n} bursts (first at {ts(int(np.argmax(hit)) * blk, sr)})")
    return y - low * g[:, None]


def breaths(y, sr, log, reduce_db=8.0):
    import librosa
    m = y.mean(axis=1)
    hop = int(0.01 * sr)
    rms = librosa.feature.rms(y=m, frame_length=hop * 2, hop_length=hop)[0]
    lv = 20 * np.log10(rms + 1e-9)
    flat = librosa.feature.spectral_flatness(y=m, n_fft=hop * 4, hop_length=hop)[0]
    cent = librosa.feature.spectral_centroid(y=m, sr=sr, n_fft=hop * 4, hop_length=hop)[0]
    n = min(len(lv), len(flat), len(cent))
    lv, flat, cent = lv[:n], flat[:n], cent[:n]
    top = np.percentile(lv, 95)
    cand = (lv < top - 14) & (lv > top - 45) & (flat > 0.08) & (cent > 1200)
    d = np.diff(np.concatenate([[0], cand.astype(int), [0]]))
    runs = [(a, b) for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)) if 15 <= b - a <= 90]
    if not runs:
        return y
    g = np.ones(n)
    for a, b in runs:
        g[a:b] = dsp.undb(-reduce_db)
    from scipy.ndimage import uniform_filter1d
    g = uniform_filter1d(g, 2)
    gs = np.interp(np.arange(len(y)), np.arange(n) * hop, g)
    log.append(f"breaths: {len(runs)} breaths turned down {reduce_db:g} dB (first at {ts(runs[0][0] * hop, sr)})")
    return y * gs[:, None]


def floor_is_noise(y, sr):
    """True when the quietest second of the stem is noise (flat spectrum), not a quiet bit of the music."""
    import librosa
    from hypnomix.studio.cleanup import quietest_segment
    q = quietest_segment(y, sr).mean(axis=1)
    if np.max(np.abs(q)) < 1e-6:
        return True                                        # digital silence
    return float(np.median(librosa.feature.spectral_flatness(y=q, n_fft=2048))) > 0.25


def strip_silence(y, sr, log, hold_ms=400, pre_ms=30, post_ms=200, fade_ms=10):
    b = dsp.block_rms_db(y, sr, 0.01)
    floor = np.percentile(b, 10)
    top = np.percentile(b, 99)
    # follow the noise floor only when it really is noise; otherwise remove only what's 50 dB under the part
    thr = max(floor + 8, top - 60) if floor_is_noise(y, sr) else top - 50
    on = b > thr
    from scipy.ndimage import binary_dilation
    keep = binary_dilation(on, structure=np.ones(int((pre_ms + post_ms) / 10) * 2 + 1), iterations=1)
    # only remove gaps longer than hold_ms
    d = np.diff(np.concatenate([[1], keep.astype(int), [1]]))
    gaps = [(a, e) for a, e in zip(np.flatnonzero(d == -1), np.flatnonzero(d == 1)) if e - a >= hold_ms / 10]
    if not gaps:
        return y
    blk = int(0.01 * sr)
    g = np.ones(len(y))
    f = int(fade_ms / 1000 * sr)
    for a, e in gaps:
        s0, s1 = a * blk, min(len(y), e * blk)
        g[s0:s1] = 0
        g[max(0, s0 - f):s0] = np.minimum(g[max(0, s0 - f):s0], np.linspace(1, 0, s0 - max(0, s0 - f)))
        g[s1:s1 + f] = np.minimum(g[s1:s1 + f], np.linspace(0, 1, len(g[s1:s1 + f])))
    total = sum(e - a for a, e in gaps) / 100
    log.append(f"silence: {len(gaps)} gaps ({total:.0f} s) between parts made silent with {fade_ms} ms fades")
    return y * g[:, None]


def edge_fades(y, sr, fin_ms=5, fout_ms=50):
    a, b = int(fin_ms / 1000 * sr), int(fout_ms / 1000 * sr)
    y[:a] *= np.linspace(0, 1, a)[:, None]
    y[-b:] *= np.linspace(1, 0, b)[:, None]
    return y


def denoise(y, sr, log, role):
    from hypnomix.studio.soundcheck import hum
    h, base = hum(y, sr)
    if h > 12:
        for k in range(1, 7):
            if base * k < sr / 2:
                y = dsp.filt(y, dsp.notch(base * k, 35, sr))
        log.append(f"hum: notched {base} Hz and harmonics ({h:.0f} dB above its surroundings)")
    floor = dsp.noise_floor_db(y, sr)
    top = float(np.percentile(dsp.block_rms_db(y, sr, 0.05), 95))
    from hypnomix.studio.cleanup import quietest_segment
    if floor > -62 and 15 < top - floor < 50 and role not in DRUMS and floor_is_noise(y, sr):
        import noisereduce as nr
        prof = quietest_segment(y, sr)
        y = np.stack([nr.reduce_noise(y=y[:, c], sr=sr, y_noise=prof[:, c], stationary=True, prop_decrease=0.5, n_fft=2048)
                      for c in range(y.shape[1])], axis=1)[: len(y)]
        log.append(f"hiss: steady noise reduced 50% (floor was {floor:.0f} dBFS, only {top - floor:.0f} dB under the part)")
    return y


# ---------------------------------------------------------------- the pass
STEPS = ["declip", "rumble", "declick", "plosives", "breaths", "noise", "silence", "mono", "gain"]
STEP_OF = {"hum": "noise", "hiss": "noise"}          # log prefix -> step name, where they differ


def prep_stem(name, y, sr, role, opts):
    """opts["steps"]: a set of step names to run and nothing else (the approved moves of a plan); None = all."""
    only = opts.get("steps")
    on = lambda s: only is None or s in only
    log = []
    if on("declip"):
        y = declip(y, sr, log)                 # first: any filtering would round off the flat tops it looks for
    if on("rumble"):
        dc = float(np.max(np.abs(y.mean(axis=0))))
        y = y - y.mean(axis=0)
        y = dsp.filt(y, dsp.highpass(25, sr, 2))
        if dc > 0.003:
            log.append(f"rumble: DC offset of {dc * 100:.1f}% of full scale removed, high-pass at 25 Hz")
    if role not in DRUMS and on("declick"):
        y = declick(y, sr, log)
    if role in VOCAL:
        if on("plosives"):
            y = deplosive(y, sr, log)
        if opts.get("breaths", True) and on("breaths"):
            y = breaths(y, sr, log)
    if opts.get("noise", True) and on("noise"):
        y = denoise(y, sr, log, role)
    if opts.get("silence", True) and role not in ("pad", "fx") and on("silence"):
        y = strip_silence(y, sr, log)
    y = edge_fades(y, sr)
    if on("mono") and y.shape[1] == 2 and np.allclose(y[:, 0], y[:, 1], atol=1e-4):
        y = y[:, :1]
        log.append("mono: left and right were identical, saved as a mono file")
    if not opts.get("keep_levels") and on("gain"):
        L = dsp.active_lufs(y, sr)
        g = -20 - L
        pk = dsp.sample_peak(y) + g
        if pk > -3:
            g -= pk + 3
        y = y * dsp.undb(g)
        log.append(f"gain: {g:+.1f} dB (≈ -20 LUFS while playing, peaks ≤ -3 dBFS)")
    return y, log


def prep(folder, outdir=None, **opts):
    files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in dsp.AUDIO_EXT and not p.name.startswith("."))
    if not files:
        sys.exit(f"no audio in {folder}")
    rates = [dsp.sf.info(str(p)).samplerate if p.suffix.lower() not in (".mp3", ".m4a") else 44100 for p in files]
    sr = max(set(rates), key=rates.count)
    loaded = []
    for p in files:
        y, _ = dsp.load(p, sr)
        if np.max(np.abs(y)) < 1e-5:
            print(f"  skipping silent {p.name}", file=sys.stderr)
            continue
        loaded.append((p.stem, y))
    n = max(len(y) for _, y in loaded)
    od = out_at(outdir, "prep", Path(folder).resolve().name)
    od.mkdir(parents=True, exist_ok=True)
    roles_of = roles.classify_all(loaded, sr)
    order = sorted(loaded, key=lambda t: (ORDER.index(roles_of[t[0]][0]), t[0].lower()))
    report = [f"# Prep report: {Path(folder).name}", "",
              f"{len(order)} stems → {sr} Hz, 24-bit, all {n / sr:.1f} s from the same start.", ""]
    out = []
    for i, (nm, y) in enumerate(order, 1):
        role, how = roles_of[nm]
        print(f"  prepping {nm} ({role}) …", file=sys.stderr)
        y = np.pad(y, ((0, n - len(y)), (0, 0)))
        z, log = prep_stem(nm, y, sr, role, opts)
        clean = re.sub(r"^\d+[\s_\-.]*", "", nm).strip() or nm
        path = dsp.save(od / f"{i:02d} {clean}.wav", z, sr, 24)
        out.append(path)
        report += [f"## {path.name}  ({role.replace('_', ' ')}, by {how})", *([f"- {x}" for x in log] or ["- nothing to fix"]), ""]
    (od / "PREP REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return od, out, "\n".join(report)


WHY = {
    "declip": ("high", "flattened waveform tops are rebuilt by curve-fitting across them. A repair, not a cure: "
                       "re-record if you can. Listen for dull or 'soft' peaks."),
    "rumble": ("low", "DC offset and energy under 25 Hz eat headroom and cause clicks at edits. Inaudible when it works."),
    "declick": ("medium", "isolated clicks and pops are replaced by predicting the waveform from both sides. "
                          "Listen that consonants and pick attacks are still crisp."),
    "plosives": ("medium", "the low thump of 'p' and 'b' is removed only during each burst. Listen that the word "
                           "still has its weight."),
    "breaths": ("low", "breaths between phrases are turned down, not removed, so it still sounds like a person. "
                       "Skip this if the breaths are part of the performance."),
    "noise": ("medium", "steady hum or hiss is reduced, only because this file measured noisy. Listen for dulled "
                        "highs or a 'watery' sound in quiet moments."),
    "silence": ("low", "gaps where nothing plays are made silent with short fades, so the mix isn't a stack of noise "
                       "floors. Listen that no tail or quiet entry is cut off."),
    "mono": ("low", "left and right are identical, so the file is saved as mono. No audible change."),
    "gain": ("low", "the level is set for mixing (about -20 LUFS while playing). Changes loudness only."),
}


def plan(folder, plan_dir=None, **opts):
    """Every move `prep` would make on this folder, as findings in a scan folder. Writes no audio."""
    import time
    from hypnomix.workflow import plan as P
    t0 = time.time()
    files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in dsp.AUDIO_EXT and not p.name.startswith("."))
    if not files:
        sys.exit(f"no audio in {folder}")
    loaded = []
    for p in files:
        y, sr = dsp.load(p)
        if np.max(np.abs(y)) >= 1e-5:
            loaded.append((p, y, sr))
    roles_of = roles.classify_all([(p.stem, y) for p, y, _ in loaded], loaded[0][2])
    findings, notes = [], []
    for p, y, sr in loaded:
        role, how = roles_of[p.stem]
        print(f"  planning {p.name} ({role}) …", file=sys.stderr)
        _, log = prep_stem(p.stem, y, sr, role, opts)
        for line in log:
            key, _, text_ = line.partition(": ")
            step = STEP_OF.get(key, key)
            sev, why = WHY.get(step, ("low", ""))
            findings.append(dict(kind=step, severity=sev, track=p.name, problem=f"{text_} ({role.replace('_', ' ')}, by {how})",
                                 fix=why, plan=dict(tool="prep", file=str(p.resolve()), step=step)))
    notes.append(f"prep plan: {len(loaded)} files; approved steps are applied per file into fixed/prep/ "
                 "(same length and start as the original)")
    return P.write(P.scan_dir(plan_dir, folder), "prep", folder, findings, notes, time.time() - t0)


def prep_file(path, steps, outdir):
    """Run only `steps` on one file and save `<name> (prep).wav` in outdir. Used for approved plan moves."""
    path = Path(path)
    y, sr = dsp.load(path)
    role, _ = roles.classify_all([(path.stem, y)], sr)[path.stem]
    z, log = prep_stem(path.stem, y, sr, role, dict(steps=set(steps)))
    od = Path(outdir)
    od.mkdir(parents=True, exist_ok=True)
    dest, k = od / f"{path.stem} (prep).wav", 1
    while dest.exists():
        k += 1
        dest = od / f"{path.stem} (prep {k}).wav"
    dsp.save(dest, z, sr, 24)
    return dest, log


def main():
    ap = argparse.ArgumentParser(prog="hypnomix prep", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder"); ap.add_argument("--out")
    ap.add_argument("--keep-levels", action="store_true"); ap.add_argument("--no-breaths", action="store_true")
    ap.add_argument("--no-silence", action="store_true"); ap.add_argument("--no-noise", action="store_true")
    ap.add_argument("--plan", nargs="?", const=True, metavar="SCAN_DIR",
                    help="change nothing: list every move as a finding for review (hypnomix review / fix)")
    ap.add_argument("--steps", help=f"with a single FILE: run only these steps ({', '.join(STEPS)})")
    a = ap.parse_args()
    if a.plan:
        plan(a.folder, a.plan, keep_levels=a.keep_levels, breaths=not a.no_breaths, silence=not a.no_silence,
             noise=not a.no_noise)
        return
    if Path(a.folder).is_file():
        steps = [s.strip() for s in (a.steps or "").split(",") if s.strip()]
        bad = [s for s in steps if s not in STEPS]
        if not steps or bad:
            sys.exit(f"a single file needs --steps from: {', '.join(STEPS)}" + (f" (unknown: {', '.join(bad)})" if bad else ""))
        dest, log = prep_file(a.folder, steps, a.out or out_at(None, "prep", Path(a.folder).stem))
        print("\n".join(f"- {x}" for x in log) or "- nothing to fix with those steps")
        print(f"→ {dest}")
        return
    od, files, text = prep(a.folder, a.out, keep_levels=a.keep_levels, breaths=not a.no_breaths,
                           silence=not a.no_silence, noise=not a.no_noise)
    print(text)
    print(f"→ {od}")


if __name__ == "__main__":
    main()
