#!/usr/bin/env python3
"""Tighten vocal doubles and harmonies to the lead: the timing of every word, without touching pitch.

How: both vocals are reduced to pitch-independent features (loudness envelope, onset strength, and
consonant energy above 3 kHz), so a harmony a third above still lines up with the lead. A banded DTW
finds the time offset between them every 10 ms; the overdub is then re-timed with WSOLA (overlap-add
that keeps pitch and formants). Offsets are only applied where both are singing, smoothed, and capped.

Usage:
    hypnomix vocalign LEAD.wav DOUBLE.wav [HARMONY.wav …] --to-average | --to-lead [--lead NAME]
                     [--strength 1.0] [--max-ms 150] [--trim-tails] [--level -6] [--out DIR]

  --to-average every part is nudged toward the group's average timing, the first file too (the gentle stack mode:
               --stack-strength, --fix-strength, --fix-over-ms, --cap-ms)
  --to-lead    the parts follow the lead, which is never moved (--strength, --max-ms); --lead NAME says which file
               is the lead when it is not the first one
               With 2+ parts one of the two is needed: a flag, or your saved answer (`hypnomix prefs set
               harmony.reference=average` or `=lead`). Nothing is assumed. One part alone follows its guide.
  --strength   0–1: how far to move toward the lead (0.7 keeps a little natural looseness)
  --trim-tails fade overdub word-endings that hang past the lead's (the classic stacked-"s" problem)
  --level      set each overdub this many dB under the lead's loudness while both sing (omit to keep levels)
  --engine     auto (Rubber Band if `rubberband` is installed, else WSOLA) | rubberband | wsola
  --mode       tight (default) | gentle: for the Rubber Band engine; use gentle if a part sounds warbly

All files must start at the same point in the song (export them from the same bar).
Writes "<name> (aligned).wav" for each overdub and a VOCALIGN.md with before/after timing.

Also (docs/ALIGN.md):
  --preset NAME        gentle-stack, natural-double, tight-pop, loose-folk, rap-doubles (--list-presets)
  --protect A-B        never move anything here (sample for sample); --sync T or G=P: line up exactly here
  --pitch 0.35         pitch matching: doubles toward the guide's notes, harmonies keep their interval; the chord
                       under every note is checked first (--chords INSTRUMENTAL.wav or --ref MIX.wav); --vibrato
  --formant / --transpose SEMIS (or "PART.wav=SEMIS")   wider stacks, other characters; --formant-at A-B
  --no-timing          pitch / formant only
In a Live set, `hypnomix alignset` does the same and writes the timing as warp markers on the clips.
"""
from hypnomix.core.paths import out_at
import argparse, sys
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.core import args as _cli_args
from hypnomix.studio import alignopts as AO
from hypnomix.core.paths import out as out_dir

FR_S = 0.01                      # feature frame: 10 ms


def features(y, sr):
    import librosa
    m = librosa.resample(y.mean(axis=1), orig_sr=sr, target_sr=16000)
    hop = int(16000 * FR_S)
    rms = librosa.feature.rms(y=m, frame_length=640, hop_length=hop)[0]
    env = 20 * np.log10(rms + 1e-6)
    onset = librosa.onset.onset_strength(y=m, sr=16000, hop_length=hop)
    S = np.abs(librosa.stft(m, n_fft=640, hop_length=hop)) ** 2
    f = librosa.fft_frequencies(sr=16000, n_fft=640)
    cons = 10 * np.log10(S[f > 3000].sum(axis=0) + 1e-10)
    n = min(len(env), len(onset), len(cons))
    F = np.stack([env[:n], onset[:n] * 3, cons[:n]], axis=1)
    F = (F - np.median(F, axis=0)) / (np.std(F, axis=0) + 1e-6)
    active = env[:n] > np.percentile(env[:n], 95) - 30
    return F, active


def band_dtw(A, B, radius):
    """DTW restricted to |i - j| <= radius. Returns offset[i] = j - i (in frames) along the best path."""
    n = min(len(A), len(B))
    A, B = A[:n], B[:n]
    W = 2 * radius + 1
    ks = np.arange(-radius, radius + 1)
    D = np.full((n, W), np.inf)
    step = np.zeros((n, W), np.int8)                    # 0 diag, 1 from (i-1, j), 2 from (i, j-1)
    pen = 0.15                                          # discourages needless warping
    for i in range(n):
        j = i + ks
        ok = (j >= 0) & (j < n)
        c = np.full(W, np.inf)
        c[ok] = np.abs(A[i] - B[j[ok]]).sum(axis=1)
        if i == 0:
            prev_diag = np.where(ks == 0, 0.0, np.inf)
            prev_up = np.full(W, np.inf)
        else:
            prev_diag = D[i - 1]
            prev_up = np.append(D[i - 1, 1:], np.inf) + pen    # (i-1, j) is k+1 in the previous row
        best = np.minimum(prev_diag, prev_up)
        st = np.where(prev_up < prev_diag, 1, 0).astype(np.int8)
        row = np.empty(W)
        run = np.inf
        for k in range(W):                              # horizontal moves within the row
            h = run + pen
            if h < best[k]:
                row[k] = c[k] + h; st[k] = 2
            else:
                row[k] = c[k] + best[k]
            run = row[k]
        D[i] = row
        step[i] = st
    # backtrack from the end, on the diagonal-most cell
    i, k = n - 1, int(np.argmin(D[n - 1] + np.abs(ks) * 1e-3))
    off = np.zeros(n)
    while i >= 0:
        off[i] = ks[k]
        s = step[i, k]
        if s == 0:
            i -= 1
        elif s == 1:
            i -= 1; k = min(W - 1, k + 1)
        else:
            k -= 1
            if k < 0:
                i -= 1; k = 0
    return off


def offset_curve(lead, over, sr, max_ms, strength):
    FA, actA = features(lead, sr)
    FB, actB = features(over, sr)
    R = int(max_ms / 1000 / FR_S)
    off = band_dtw(FA, FB, R)
    n = len(off)
    both = actA[:n] & actB[:n]
    from scipy.ndimage import median_filter, uniform_filter1d
    off = median_filter(off, 7)
    # only trust offsets where both sing; elsewhere interpolate between trusted regions
    idx = np.flatnonzero(both)
    if len(idx) < 10:
        return np.zeros(n), both, off
    off = np.interp(np.arange(n), idx, off[idx])
    off = uniform_filter1d(off, 5)
    # cap the slope so the stretch stays between 0.6x and 1.6x (natural-sounding)
    for i in range(1, n):
        off[i] = np.clip(off[i], off[i - 1] - 0.4, off[i - 1] + 0.6)
    return off * strength, both, off


def wsola_warp(x, sr, offset_s, frame=1024, hop=256, search=128):
    """y[t] ≈ x[t + offset(t)], pitch preserved. offset_s: callable/array of seconds per output sample frame."""
    n = len(x)
    win = np.hanning(frame)
    out = np.zeros((n + frame, x.shape[1]))
    norm = np.zeros(n + frame)
    xp = np.pad(x, ((frame + search, frame + search), (0, 0)))
    base = frame + search
    prev_in = None
    mono = xp.mean(axis=1)
    for t in range(0, n, hop):
        want = int(np.clip(t + int(round(offset_s(t) * sr)), -frame, n))   # stay inside the (padded) file
        if prev_in is not None:
            nat = prev_in + hop
            if abs(want - nat) <= 1:
                pos = nat
            else:
                # pick the position near `want` whose frame best continues the previous one
                ref = mono[base + nat: base + nat + frame]
                seg = mono[base + want - search: base + want + search + frame]
                if len(ref) == frame and len(seg) >= frame:      # near the end there may be nothing to search
                    c = np.correlate(seg, ref, "valid")
                    pos = want - search + int(np.argmax(c))
                else:
                    pos = want
        else:
            pos = want
        pos = int(np.clip(pos, -frame, n))
        out[t:t + frame] += xp[base + pos: base + pos + frame] * win[:, None]
        norm[t:t + frame] += win
        prev_in = pos
    norm[norm < 1e-3] = 1
    return (out / norm[:, None])[:n]


def trim_tails(lead, over, sr, fade_ms=40):
    """Fade the overdub where it keeps sounding after the lead has stopped (or starts before it)."""
    bl = dsp.block_rms_db(lead, sr, 0.01)
    bo = dsp.block_rms_db(over, sr, 0.01)
    k = min(len(bl), len(bo))
    lead_on = bl[:k] > bl.max() - 35
    over_on = bo[:k] > bo.max() - 35
    keep = lead_on.copy()
    from scipy.ndimage import binary_dilation, uniform_filter1d
    keep = binary_dilation(keep, iterations=3)          # 30 ms grace around the lead
    g = np.where(over_on & ~keep, 0.0, 1.0)
    g = uniform_filter1d(g, max(1, int(fade_ms / 10)))
    gs = np.repeat(g, int(0.01 * sr))
    gs = np.pad(gs, (0, max(0, len(over) - len(gs))), constant_values=1)[: len(over)]
    trimmed = float(np.mean(g < 0.5) / max(1e-9, np.mean(over_on))) if over_on.any() else 0
    return over * gs[:, None], trimmed


def residual_ms(lead, over, sr, max_ms):
    FA, aA = features(lead, sr)
    FB, aB = features(over, sr)
    off = band_dtw(FA, FB, int(max_ms / 1000 / FR_S))
    both = aA[:len(off)] & aB[:len(off)]
    if not both.any():
        return 0.0, 0.0
    a = np.abs(off[both]) * FR_S * 1000
    return float(np.median(a)), float(np.percentile(a, 95))


class RefusedAlign(Exception):
    pass


def only_open(y, sr, protect):
    """y with the protected ranges silenced: the before/after checks then measure only where moves were allowed."""
    if not protect:
        return y
    y = y.copy()
    for a_, b_ in protect:
        y[max(0, int(a_ * sr)):max(0, int(b_ * sr))] = 0
    return y


def onset_lag_at(ref, x, sr, centres_s, win_s=1.0, max_ms=150):
    """Median |lag| (ms) of onset envelopes in short windows centred on given times (the words that were fixed)."""
    import librosa
    from scipy.signal import correlate
    hop = 128
    mono = lambda y: (y.mean(1) if y.ndim > 1 else y).astype(np.float32)
    ea = librosa.onset.onset_strength(y=mono(ref), sr=sr, hop_length=hop)
    eb = librosa.onset.onset_strength(y=mono(x), sr=sr, hop_length=hop)
    fps = sr / hop; W = int(win_s * fps); M = int(max_ms / 1000 * fps)
    lags = []
    for c_ in centres_s:
        s0 = max(0, int(c_ * fps) - W // 2)
        a, b = ea[s0:s0 + W], eb[s0:s0 + W]
        if len(a) < W or a.std() < 1e-3 or b.std() < 1e-3:
            continue
        cc = correlate(b - b.mean(), a - a.mean(), mode="full")[W - 1 - M: W + M]
        lags.append(abs(np.argmax(cc) - M) / fps * 1000)
    return float(np.median(lags)) if lags else None


def onset_lag_ms(lead, x, sr, win_s=2.0, max_ms=150):
    """Independent timing check: median |lag| (ms) of onset-strength envelopes, cross-correlated per window
    where both parts have onsets. Not the DTW the aligner uses, so a wrong plan can't grade itself."""
    import librosa
    from scipy.signal import correlate
    hop = 128
    mono = lambda y: (y.mean(1) if y.ndim > 1 else y).astype(np.float32)
    ea = librosa.onset.onset_strength(y=mono(lead), sr=sr, hop_length=hop)
    eb = librosa.onset.onset_strength(y=mono(x), sr=sr, hop_length=hop)
    fps = sr / hop; W = int(win_s * fps); M = int(max_ms / 1000 * fps)
    lags = []
    for s0 in range(0, min(len(ea), len(eb)) - W, W):
        a, b = ea[s0:s0 + W], eb[s0:s0 + W]
        if a.std() < 1e-3 or b.std() < 1e-3:
            continue
        c = correlate(b - b.mean(), a - a.mean(), mode="full")[W - 1 - M: W + M]
        lags.append(abs(np.argmax(c) - M) / fps * 1000)
    return float(np.median(lags)) if lags else 0.0


def onset_env(y, sr, n=None):
    """Onset strength in 10 ms frames (16 kHz, hop 160), as the stack mode and sync points use it."""
    import librosa
    o = librosa.onset.onset_strength(y=librosa.resample((y.mean(1) if y.ndim > 1 else y).astype(np.float32),
                                                        orig_sr=sr, target_sr=16000), sr=16000, hop_length=160)
    if n is not None:
        o = np.pad(o[:n], (0, max(0, n - len(o))))
    return o / (o.max() + 1e-9)


def align(lead_path, over_path, strength=1.0, max_ms=150, trim=False, level=None, outdir=None, engine="auto", mode="tight",
          protect=(), sync=(), plan_only=False):
    lead, sr = dsp.load(lead_path)
    over, _ = dsp.load(over_path, sr)
    n = max(len(lead), len(over))
    lead = np.pad(lead, ((0, n - len(lead)), (0, 0)))
    over = np.pad(over, ((0, n - len(over)), (0, 0)))
    before = residual_ms(lead, over, sr, max_ms)
    import shutil
    notes = []
    # one plan for both engines: the offset curve on the lead's timeline (y[t] = x[t + off(t)])
    off, both, raw = offset_curve(lead, over, sr, max_ms, strength)
    from hypnomix.studio import alignopts as AO
    synced, pmask = [], np.zeros(len(off), bool)
    if sync:
        off, synced = AO.sync_plan(off, sync, lead, over, sr, max_ms / 1000 / FR_S)
        notes.append("sync points: " + ", ".join(f"{g:.2f} s " + (f"({ms:+d} ms)" if ms is not None else "(nothing to match there)")
                                                 for g, ms in synced))
    if protect:
        off, pmask = AO.protect_plan(off, protect)
        notes.append(f"{len(protect)} protected area(s) left exactly as sung")
    t_frames = np.arange(len(off)) * FR_S
    candidates = []
    if engine in ("rubberband", "auto") and shutil.which("rubberband"):
        from hypnomix.studio import _rbalign as RB
        RB.MODE = mode; RB.SING_LIMITS, RB.GAP_LIMITS = RB.LIMITS[mode]
        # Rubber Band's map goes the other way (harmony time -> lead time): invert the curve onto the
        # harmony's own timeline and flip its sign. (Its own DTW plan drifted 60-80 ms on harmonies that
        # sing other notes; this plan is the one the WSOLA engine already gets right.)
        dub_t = t_frames + off * FR_S
        grid = np.arange(len(over) // RB.HOP + 1) * RB.HOP / sr
        off_rb = np.interp(grid, dub_t, -off * FR_S) * sr / RB.HOP
        cand = RB.stretch_phrases(over.mean(1).astype(np.float32), off_rb, sr, audio=over)
        candidates.append((f"Rubber Band engine, {mode}", cand))
    if engine in ("wsola", "auto") or not candidates:
        fn = lambda t: float(np.interp(t / sr, t_frames, off * FR_S))
        candidates.append(("WSOLA engine", wsola_warp(over, sr, fn)))
    # check every result with an independent measure, keep the best, refuse anything not tighter than the input
    L_, O_ = only_open(lead, sr, protect), only_open(over, sr, protect)
    ref = onset_lag_ms(L_, O_, sr)
    scored = [(onset_lag_ms(L_, only_open(c, sr, protect), sr), name, c) for name, c in candidates]
    best = min(scored, key=lambda x: x[0])
    for sc, name, _ in scored:
        notes.append(f"{name}: independent check {ref:.0f} → {sc:.0f} ms")
    if best[0] >= ref - 1.0:
        raise RefusedAlign(f"{Path(over_path).name}: no engine made it tighter (independent check {ref:.0f} ms before, "
                           f"best {best[0]:.0f} ms after); nothing written")
    out = best[2]
    notes.append(f"kept: {best[1]}")
    if pmask.any():
        out = AO.splice_protected(over, out, pmask, sr)
    if trim:
        out, frac = trim_tails(lead, out, sr)
        notes.append(f"tails trimmed on {frac * 100:.0f}% of its sung time")
    if level is not None:
        la, lo = dsp.active_lufs(lead, sr), dsp.active_lufs(out, sr)
        g = (la + level) - lo
        out *= dsp.undb(g)
        notes.append(f"level {g:+.1f} dB → {level:+g} dB under the lead")
    after = residual_ms(lead, out, sr, max_ms)
    od = out_at(outdir, "vocalign")
    path = dsp.save(od / f"{Path(over_path).stem} (aligned).wav", out, sr, 24)
    moved = float(np.mean(np.abs(off[both]) * FR_S * 1000 > 5)) if both.any() else 0
    return dict(file=Path(over_path).name, before=before, after=after, moved=moved, notes=notes, out=path,
                max_shift=float(np.max(np.abs(off)) * FR_S * 1000), plan=off, src=str(over_path))


def grid_lag(env, n, bpm, max_ms=60.0, grid=None):
    """Per bar: how many 10 ms frames the stack's onsets sit late (+) or early (-) against the song's own grid
    (straight 8ths/16ths, or triplets where the song uses them: detected from these onsets unless given),
    smoothed over ~5 bars. Gaussian score around each grid line, searched within +-max_ms."""
    from scipy.signal import find_peaks
    spb = 60 / bpm
    W = int(4 * spb / FR_S)
    M = int(max_ms / 1000 / FR_S)
    if grid is None:
        from hypnomix.core import grid as G
        pk, pr = find_peaks(env, height=env.max() * 0.15 if env.max() > 0 else 1, distance=5)
        grid = G.detect(pk * FR_S / spb, pr["peak_heights"], 4)
    lags = []
    for s0 in range(0, n - W, W):
        seg = env[s0:s0 + W]
        if seg.sum() < 1e-3:
            lags.append(np.nan); continue
        bar = s0 // W
        lines = np.array(sorted({p for p in grid.positions(bar)} | {12})) / 12      # in-beat fractions
        k = np.arange(s0, s0 + W)
        best, bl = -1.0, 0
        for L in range(-M, M + 1):
            fr = ((k - L) * FR_S / spb) % 1.0
            d = np.min(np.abs(fr[:, None] - lines[None, :]), axis=1) * spb / FR_S     # frames to the nearest line
            sc = float((seg * np.exp(-0.5 * (d / 1.5) ** 2)).sum())
            if sc > best:
                best, bl = sc, L
        lags.append(bl)
    lags = np.array(lags, float)
    if not np.isfinite(lags).any():
        return np.zeros(n)
    idx = np.flatnonzero(np.isfinite(lags))
    lags = np.interp(np.arange(len(lags)), idx, lags[idx])
    from scipy.ndimage import uniform_filter1d
    lags = uniform_filter1d(lags, 5, mode="nearest")
    centres = np.arange(len(lags)) * W + W / 2
    return np.interp(np.arange(n), centres, lags)


def sharing_mask(envs, n, thr=0.6, win_s=2.0, max_ms=150.0):
    """{part: 0..1 per 10 ms frame}: 1 where the part sings the same words at the same time as another part
    (its onset envelope correlates >= thr with another part's within +-max_ms, per window), smoothed."""
    from scipy.ndimage import uniform_filter1d
    W, M = int(win_s / FR_S), int(max_ms / 1000 / FR_S)
    names = list(envs)
    out = {p_: np.zeros(n) for p_ in names}
    for s0 in range(0, n - W + 1, W):
        segs = {p_: envs[p_][s0:s0 + W] for p_ in names}
        for p_ in names:
            a = segs[p_]
            if a.std() < 1e-6:
                continue
            a = (a - a.mean()) / (a.std() * len(a))
            best = 0.0
            for q in names:
                if q == p_ or segs[q].std() < 1e-6:
                    continue
                b = (segs[q] - segs[q].mean()) / segs[q].std()
                c = np.correlate(np.pad(b, M), a, mode="valid")          # lags -M..M
                best = max(best, float(c.max()))
            if best >= thr:
                out[p_][s0:s0 + W] = 1.0
    return {p_: uniform_filter1d(m, int(0.5 / FR_S), mode="nearest") for p_, m in out.items()}   # 500 ms edges


def keep_original_where_still(orig, warped, o, sr, still=0.05, fade_s=0.01):
    """WSOLA changes audio slightly even at zero offset: wherever the move is under ~0.5 ms, keep the original
    sample for sample (10 ms crossfades at the edges)."""
    from scipy.ndimage import uniform_filter1d
    moving = (np.abs(o) >= still).astype(float)
    m = np.repeat(moving, int(round(FR_S * sr)))[:len(orig)]
    m = np.pad(m, (0, max(0, len(orig) - len(m))))
    m = uniform_filter1d(m, max(1, int(fade_s * sr)), mode="nearest")
    return orig * (1 - m[:, None]) + warped * m[:, None], float(moving.mean())


def words_of(env, sung, min_s=0.12):
    """[(start, end)] word spans in 10 ms frames: from each onset to the next (or to where the singing stops)."""
    import librosa
    on = librosa.onset.onset_detect(onset_envelope=env, sr=16000, hop_length=160, backtrack=True, units="frames")
    on = [int(x) for x in on if x < len(sung) and sung[min(len(sung) - 1, int(x) + 2)]]
    spans = []
    for i, a in enumerate(on):
        b = on[i + 1] if i + 1 < len(on) else len(sung)
        e = a
        while e < b and e < len(sung) and sung[e]:
            e += 1
        if e - a >= max(1, int(min_s / FR_S)):
            spans.append((a, e))
        elif spans and a - spans[-1][1] < 3:
            spans[-1] = (spans[-1][0], e)             # a fragment glued to the word before
    return spans


def word_errors(env_p, env_others, spans, max_ms=150.0, pad=5):
    """Per word: how many 10 ms frames it sits late (+) or early (-) against the other parts singing then, from
    cross-correlating its onsets with theirs (sub-frame by parabolic peak). NaN where there's nothing to compare."""
    M = int(max_ms / 1000 / FR_S)
    out = []
    for a, b in spans:
        s0, s1 = max(0, a - pad), min(len(env_p), b + pad)
        x, y = env_p[s0:s1], env_others[max(0, s0 - M):s1 + M]
        if len(x) < 4 or x.std() < 1e-6 or y.std() < 1e-6 or len(y) < len(x) + 2 * M:
            out.append(np.nan); continue
        c = np.correlate(y - y.mean(), x - x.mean(), mode="valid")       # index k: x placed at y[k], k=M means no lag
        k = int(np.argmax(c))
        frac = 0.0
        if 0 < k < len(c) - 1:
            d = c[k - 1] - 2 * c[k] + c[k + 1]
            frac = 0.5 * (c[k - 1] - c[k + 1]) / d if d != 0 else 0.0
        if k <= 1 or k >= len(c) - 2:                                     # the best match is at the search edge:
            out.append(np.nan); continue                                  # a false match, not a timing reading
        out.append(float(M - (k + frac)))                                 # + = this word is late
    return out


def word_plan(rel, spans, share, fix_over, fix_strength, gentle, cap, errs=None):
    """Per word: its median timing error against the group (frames, + = late), and the move it gets: words
    further off than `fix_over` move fix_strength of the way, all others only `gentle` of the way. Words not
    sung together with another part get nothing. Returns (move curve in frames, [(a, b, err, move)])."""
    n = len(rel)
    pts, words = [], []
    for a, b in spans:
        if share[a:b].mean() < 0.5:
            continue
        err = float(np.median(rel[a:b])) if errs is None else errs[spans.index((a, b))]
        if not np.isfinite(err):
            continue
        k = fix_strength if abs(err) > fix_over else gentle
        mv = float(np.clip(err * k, -cap, cap))
        words.append((a, b, err, mv))
        pts += [(a, mv), (b - 1, mv)]
    if not pts:
        return np.zeros(n), words
    o = np.full(n, np.nan)
    for a, b, _, mv in words:
        o[a:b] = mv                                   # the whole word moves as one: no stretching inside it
    idx = np.flatnonzero(np.isfinite(o))
    o = np.interp(np.arange(n), idx, o[idx])          # the change happens in the gaps between words
    first, last = words[0][0], words[-1][1]
    o[:first] = np.interp(np.arange(first), [0, first], [0, o[first]]) if first > 0 else o[:first]
    o[last:] = np.interp(np.arange(last, n), [last, n - 1], [o[last - 1], 0]) if last < n else o[last:]
    return o, words


def stack_align(paths, outdir=None, strength=0.1, grid=0.3, bpm=None, max_ms=60.0, same_words=0.6,
                fix_over_ms=30.0, fix_strength=0.8, protect=(), sync=()):
    """Gentle group alignment: nobody is forced onto one lead. Each part moves `strength` of the way toward the
    group's average timing (the mean over the parts singing at that moment, 250 ms smoothed; the first part is
    only a ruler and moves too), and with --bpm the whole stack is pulled `grid` of the way toward the 8th-note
    grid (phrase by phrase, ~5-bar smoothing). Capped at max_ms, pitch untouched (WSOLA). Every part is checked
    independently afterwards and kept only if it ends up closer to the others than before."""
    import librosa
    from scipy.ndimage import uniform_filter1d
    audio = {}
    sr = None
    for p_ in paths:
        y, sr_ = dsp.load(p_, sr)
        sr = sr or sr_
        audio[p_] = y
    n_s = max(len(y) for y in audio.values())
    audio = {k: np.pad(y, ((0, n_s - len(y)), (0, 0))) for k, y in audio.items()}
    ref = paths[0]
    _, act_ref = features(audio[ref], sr)
    offs, acts = {ref: None}, {ref: act_ref}
    for p_ in paths[1:]:
        off, both, _ = offset_curve(audio[ref], audio[p_], sr, 150, 1.0)   # part[t + off] ~ ruler[t]
        offs[p_], acts[p_] = off, both
    n = min([len(act_ref)] + [len(o) for o in offs.values() if o is not None])
    offs[ref] = np.zeros(n)
    envs = {}
    for p_ in paths:                     # onset envelopes in 10 ms frames (16 kHz, hop 160)
        o = librosa.onset.onset_strength(y=librosa.resample(audio[p_].mean(1).astype(np.float32), orig_sr=sr,
                                                              target_sr=16000), sr=16000, hop_length=160)[:n]
        envs[p_] = np.pad(o, (0, n - len(o)))
    # only parts singing the same words at the same time are nudged together; a part on its own line is left alone
    share = sharing_mask(envs, n, same_words) if same_words > 0 else {p_: np.ones(n) for p_ in paths}
    O = np.stack([offs[p_][:n] for p_ in paths])
    A = np.stack([acts[p_][:n] * (share[p_] > 0.5) for p_ in paths]).astype(float)
    cnt = A.sum(0)
    mean = uniform_filter1d(np.where(cnt > 0, (O * A).sum(0) / np.maximum(cnt, 1), 0.0), 25)
    gshift = np.zeros(n)
    if grid > 0 and bpm:
        env = np.zeros(n)
        for p_ in paths:
            env += envs[p_] / (envs[p_].max() + 1e-9)
        gshift = grid_lag(env, n, bpm)
    cap = max_ms / 1000 / FR_S
    t_frames = np.arange(n) * FR_S
    group = lambda skip: np.sum([audio[q].mean(1) for q in paths if q != skip], axis=0)[:, None]
    od = out_at(outdir, "vocalign")
    rows, worst = [], []
    # words further off than the song's own looseness (and at least fix_over_ms) are the ones to fix
    all_err, plans = [], {}
    for p_ in paths:
        rel = O[paths.index(p_)] - mean
        spans = words_of(envs[p_], acts[p_][:n])
        others_env = np.sum([envs[q] / (envs[q].max() + 1e-9) * share[q] for q in paths if q != p_], axis=0)
        errs = word_errors(envs[p_] / (envs[p_].max() + 1e-9), others_env, spans)
        plans[p_] = (rel, spans, errs)
        all_err += [abs(e) for (a, b_), e in zip(spans, errs) if np.isfinite(e) and share[p_][a:b_].mean() >= 0.5]
    loose = 2.5 * float(np.median(all_err)) if all_err else 0.0
    fix_over = max(fix_over_ms / 1000 / FR_S, loose)
    plans_out = {}
    for p_ in paths:
        rel, spans, errs = plans[p_]
        o, words = word_plan(rel, spans, share[p_], fix_over, fix_strength, strength, cap, errs)
        o = np.clip(o + grid * gshift * (np.abs(o) > 0), -cap, cap)
        from hypnomix.studio import alignopts as AO
        pmask = np.zeros(n, bool)
        if sync:     # the first part is the guide: it holds still there, the others land exactly on it
            pts = [(g, g) for g, _ in sync] if p_ == ref else sync
            o, _ = AO.sync_plan(o, pts, audio[ref], audio[p_], sr, cap)
        if protect:
            o, pmask = AO.protect_plan(o, protect)
        plans_out[p_] = o
        for a, b_, err, mv in words:
            if abs(err) > fix_over and not any(x0 <= a * FR_S < x1 for x0, x1 in protect):
                worst.append(dict(part=Path(p_).name, at_s=round(a * FR_S, 2), err_ms=round(err * FR_S * 1000),
                                  move_ms=round(mv * FR_S * 1000)))
        fn = lambda t, o=o: float(np.interp(t / sr, t_frames, o * FR_S))
        out, moved_frac = keep_original_where_still(audio[p_], wsola_warp(audio[p_], sr, fn)[:len(audio[p_])], o, sr)
        out = AO.splice_protected(audio[p_], out, pmask, sr)
        others = group(p_)
        others_o = only_open(others, sr, protect)
        before, after = onset_lag_ms(others_o, only_open(audio[p_], sr, protect), sr), onset_lag_ms(others_o, only_open(out, sr, protect), sr)
        sung = acts[p_][:n]
        sung_ = acts[p_][:n]
        shared_pct = round(100 * float((share[p_][sung_] > 0.5).mean())) if sung_.any() else 0
        row = dict(file=Path(p_).name, before_ms=round(before), after_ms=round(after), shared_pct=shared_pct,
                   median_move_ms=round(float(np.median(np.abs(o[sung])) * FR_S * 1000), 1) if sung.any() else 0.0,
                   max_move_ms=round(float(np.abs(o).max() * FR_S * 1000), 1))
        fixed_at = [(a + b_) / 2 * FR_S for a, b_, err, mv in words if abs(err) > fix_over
                    and not any(x0 <= (a + b_) / 2 * FR_S < x1 for x0, x1 in protect)]
        lb = onset_lag_at(others, audio[p_], sr, fixed_at) if fixed_at else None
        la = onset_lag_at(others, out, sr, fixed_at) if fixed_at else None
        if lb is not None:
            row["fixed_words_before_ms"], row["fixed_words_after_ms"] = round(lb), round(la)
        better_where_fixed = lb is not None and la is not None and la <= lb - 3.0 and after <= before + 2.0
        worse_where_fixed = lb is not None and la is not None and la > lb + 1.0
        if moved_frac == 0:
            row["kept"] = False
            row["note"] = "never shares words with another part at the same time: left as it was"
        elif worse_where_fixed or (not better_where_fixed and after > before - 1.0):
            row["kept"] = False
            row["note"] = ("the words it fixed did not measure closer to the others: left as it was" if lb is not None
                           else "not measurably closer to the others: left as it was")
        else:
            row["kept"] = True
            row["out"] = str(dsp.save(od / f"{Path(p_).stem} (stack aligned).wav", out, sr, 24))
        rows.append(row)
    worst.sort(key=lambda w: -abs(w["err_ms"]))
    for r, p_ in zip(rows, paths):
        r["src"], r["plan"] = str(p_), plans_out.get(p_)
    return rows, dict(grid_offset_ms=round(float(np.median(gshift)) * FR_S * 1000, 1), grid=grid, strength=strength,
                      fix_over_ms=round(fix_over * FR_S * 1000), worst=worst)


def build_parser():
    ap = argparse.ArgumentParser(prog="hypnomix vocalign", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lead"); ap.add_argument("overdubs", nargs="+")
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--max-ms", type=float, default=150)
    ap.add_argument("--trim-tails", action="store_true")
    ap.add_argument("--level", type=float)
    ap.add_argument("--out")
    ap.add_argument("--engine", choices=["auto", "rubberband", "wsola"], default="auto")
    AO.add_reference_flags(ap)
    ap.add_argument("--stack-strength", type=float, default=0.1,
                    help="stack mode: how far every word that is NOT clearly off moves toward the group (very gentle: 0.1)")
    ap.add_argument("--fix-over-ms", type=float, default=30.0,
                    help="stack mode: a word further off the group than this (or the song's own looseness, if more) is fixed")
    ap.add_argument("--fix-strength", type=float, default=0.8, help="stack mode: how far those words move (0.8)")
    ap.add_argument("--grid", type=float, default=0.3, help="stack mode: share of the stack's lag to the 8th-note grid (needs --bpm)")
    ap.add_argument("--bpm", type=_cli_args.number(20, 400), help="stack mode: the song's tempo, for the grid pull (20 to 400)")
    ap.add_argument("--cap-ms", type=float, default=60.0, help="stack mode: never move anything more than this")
    ap.add_argument("--same-words", type=float, default=0.6,
                    help="stack mode: only nudge parts singing the same words at the same time (onset correlation "
                         "threshold, 0-1; 0 = every part)")
    ap.add_argument("--mode", choices=["tight", "gentle"], default="tight",
                    help="Rubber Band engine: tight (closest timing) or gentle (smoother speed changes, less warble)")
    g = ap.add_argument_group("presets, protected areas and sync points")
    g.add_argument("--preset", help="a starting point: " + ", ".join(AO.PRESETS) + " (options you give still win; "
                   "--list-presets says what each sets)")
    g.add_argument("--list-presets", action="store_true", help="show the presets and exit")
    g.add_argument("--protect", action="append", metavar="START-END",
                   help="never move anything here (seconds or m:ss, e.g. 62-70.5 or 1:02-1:10.5; repeat or comma-separate)")
    g.add_argument("--sync", action="append", metavar="T or G=P",
                   help="line up exactly here: T = the onsets of guide and part near T seconds; G=P = the guide's "
                        "moment G is the part's moment P (repeat or comma-separate)")
    g.add_argument("--no-timing", action="store_true", help="skip the timing step (pitch / formant only)")
    g = ap.add_argument_group("pitch matching (off unless --pitch is given)")
    g.add_argument("--pitch", type=float, default=0.0,
                   help="0-1: how far each note moves toward the guide's (doubles) or toward its interval to the guide "
                        "(harmonies). 0.35 is gentle; 0 = off")
    g.add_argument("--vibrato", type=float, default=0.0, help="0-1: doubles also take on this share of the guide's vibrato and inflection")
    g.add_argument("--pitch-tolerance", type=float, default=20.0, help="cents: notes closer than this are left alone (20)")
    g.add_argument("--pitch-max", type=float, default=25.0, help="cents: never move a note more than this (25)")
    g.add_argument("--pitch-only", choices=["all", "doubles", "harmonies"], default="all", help="which parts' notes to match")
    g.add_argument("--chords", metavar="INSTRUMENTAL.wav", help="the song without vocals, from the same start: the chord under "
                   "every note is checked before it moves")
    g.add_argument("--ref", metavar="MIX.wav", help="the mix, for the chord check when there's no --chords")
    g.add_argument("--no-chord-check", action="store_true", help="match pitch without checking the chord (not recommended)")
    g = ap.add_argument_group("formant and transpose")
    g.add_argument("--formant", action="append", metavar="SEMIS or PART=SEMIS",
                   help="formant shift in semitones, pitch unchanged (+0.3: a slightly smaller, brighter voice); "
                        "for every part, or one part by file name: \"Double L.wav=0.4\"")
    g.add_argument("--transpose", action="append", metavar="SEMIS or PART=SEMIS", help="move the pitch, formants kept")
    g.add_argument("--formant-at", action="append", metavar="START-END", help="only shift formant / transpose inside these ranges")
    return ap


def per_part(items, name):
    """--formant 0.3 --formant "Double L.wav=0.5" -> the value for one part (by file name or stem), else the global one."""
    val, glob = None, 0.0
    for it in items or ():
        if "=" in it:
            k, v = it.rsplit("=", 1)
            if k.strip() in (name, Path(name).stem):
                val = float(v)
        else:
            glob = float(it)
    return glob if val is None else val


_last_plans = {}      # part path -> the move it got (10 ms frames, + = pulled earlier), for alignset's warp markers


def timing_stage(a, od):
    """The timing step. Returns (report lines, {part path: written path or None})."""
    outs = {}
    _last_plans.clear()
    ref = getattr(a, "_reference", None) or ("average" if len(a.overdubs) >= 2 and not a.to_lead else "lead")
    if ref == "average":
        rows, meta = stack_align([a.lead] + a.overdubs, a.out, a.stack_strength, a.grid if a.bpm else 0.0, a.bpm, a.cap_ms,
                                 a.same_words, a.fix_over_ms, a.fix_strength, a._protect, a._sync)
        for r in rows:
            outs[r["src"]] = r.get("out")
            if r.get("out"):
                _last_plans[r["src"]] = r["plan"]
        md = [f"# Gentle stack alignment ({len(rows)} parts)", "",
              f"Word by word: a word more than {meta['fix_over_ms']} ms off the group (the song's own looseness or "
              f"{a.fix_over_ms:g} ms, whichever is more) moved {a.fix_strength:.0%} of the way; every other word only "
              f"{a.stack_strength:.0%}"
              + (f"; the whole stack {a.grid:.0%} of the way toward the 8th-note grid at {a.bpm:g} BPM (it sat "
                 f"{meta['grid_offset_ms']:+.0f} ms off it)" if a.bpm else " (no --bpm: no grid pull)")
              + f"; never more than {a.cap_ms:g} ms. Checked independently: distance from the other parts.", "",
              f"Only where a part sings the same words at the same time as another (--same-words {a.same_words:g}); "
              "everywhere else, and wherever nothing moves, the original audio is kept sample for sample.", "",
              "| part | sings shared words | before | after | median move | biggest move | result |",
              "|---|---|---|---|---|---|---|"]
        for r in rows:
            fw = (f" (its fixed words {r['fixed_words_before_ms']} → {r['fixed_words_after_ms']} ms)"
                  if r.get("fixed_words_before_ms") is not None else "")
            md.append(f"| {r['file']} | {r['shared_pct']}% | {r['before_ms']} ms | {r['after_ms']} ms | {r['median_move_ms']} ms | "
                      f"{r['max_move_ms']} ms | {('written' if r['kept'] else r['note']) + fw} |")
        if meta["worst"]:
            ws = sorted(meta["worst"], key=lambda w: w["at_s"])
            areas, cur = [], [ws[0]]
            for w in ws[1:]:
                if w["at_s"] - cur[-1]["at_s"] <= 2.0:
                    cur.append(w)
                else:
                    areas.append(cur); cur = [w]
            areas.append(cur)
            mmss = lambda t: f"{int(t // 60)}:{t % 60:04.1f}"
            md += ["", "Problem areas (words out of time with each other):", ""]
            for ar in sorted(areas, key=lambda g: -max(abs(w["err_ms"]) for w in g)):
                who = {}
                for w in ar:
                    who.setdefault(w["part"], []).append(w["err_ms"])
                desc = ", ".join(f"{k} {'late' if np.median(v) > 0 else 'early'} ({abs(int(np.median(v)))} ms)" for k, v in who.items())
                md.append(f"- {mmss(ar[0]['at_s'])}–{mmss(ar[-1]['at_s'] + 0.3)}: {len(ar)} word(s): {desc}")
            md += ["", "Worst words (the ones fixed), most off first:", "",
                   "| part | at | off the group | moved |", "|---|---|---|---|"]
            md += [f"| {w['part']} | {int(w['at_s'] // 60)}:{w['at_s'] % 60:05.2f} | {w['err_ms']:+d} ms | {-w['move_ms']:+d} ms |"
                   for w in meta["worst"][:20]]
        else:
            md += ["", "No word was clearly off the group: only the gentle nudge was applied."]
        md += ["", *[f"- `{r['out']}`" for r in rows if r.get("out")]]
        return md, outs
    rows, refused = [], []
    for o in a.overdubs:
        print(f"aligning {Path(o).name} to {Path(a.lead).name} …", file=sys.stderr)
        try:
            rows.append(align(a.lead, o, a.strength, a.max_ms, a.trim_tails, a.level, od, a.engine, a.mode,
                              a._protect, a._sync))
            outs[o] = str(rows[-1]["out"])
            _last_plans[o] = rows[-1]["plan"]
        except RefusedAlign as e:
            refused.append(str(e))
            outs[o] = None
            print(f"REFUSED {e}", file=sys.stderr)
    md = [f"# Vocal alignment to {Path(a.lead).name}", "",
          "Timing difference from the lead while both sing (median / worst 5%):", "",
          "| overdub | before | after | frames moved >5 ms | biggest shift | notes |", "|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['file']} | {r['before'][0]:.0f} / {r['before'][1]:.0f} ms | {r['after'][0]:.0f} / {r['after'][1]:.0f} ms | "
                  f"{r['moved'] * 100:.0f}% | {r['max_shift']:.0f} ms | {'; '.join(r['notes'])} |")
    md += ["", "Under ~10 ms reads as one voice; 20–40 ms as a natural double; above that, flams and smeared consonants.",
           "If something sounds robotic, rerun with --strength 0.7.", "", *[f"- `{r['out']}`" for r in rows]]
    if refused:
        md += ["", "Refused (the result would not have been tighter than the take; the take is fine as it is, or "
                   "needs a hand):", "", *[f"- {x}" for x in refused]]
    return md, outs


def pitch_and_formant(a, od, outs):
    """After timing: pitch matching against the guide, then formant / transpose. Writes one final file per part."""
    import soundfile as sf
    from hypnomix.studio import pitchmatch as PM, formant as FM, chords as CH
    want_pitch = a.pitch > 0 or a.vibrato > 0
    if not (want_pitch or a.formant or a.transpose):
        return []
    md = ["", "## Pitch and formant", ""]
    chords = None
    if want_pitch and not a.no_chord_check:
        if a.chords:
            chords = CH.load(a.chords); md.append(f"Chord check: {Path(a.chords).name}.")
        elif a.ref:
            chords = CH.chroma(a.ref); md.append(f"Chord check: the mix {Path(a.ref).name} (an instrumental is surer).")
        else:
            sys.exit("refusing to match pitch without checking the chord under each note: pass --chords INSTRUMENTAL.wav "
                     "(the song without vocals) or --ref MIX.wav, or --no-chord-check")
    franges = AO.ranges(a.formant_at)
    guide, gsr = dsp.load(outs.get(a.lead) or a.lead)     # in stack mode the guide may have been nudged too
    if want_pitch:
        md += [f"Pitch: notes more than {a.pitch_tolerance:g} cents off the guide (or off their interval to it) moved "
               f"{a.pitch:.0%} of the way, never more than {a.pitch_max:g} cents"
               + (f"; doubles also take {a.vibrato:.0%} of the guide's vibrato" if a.vibrato else "") + ".", "",
               "| part | notes matched | median off before | left alone | flagged (halfway to another note) | asked (chord) | file |",
               "|---|---|---|---|---|---|---|"]
    rows = []
    for part in a.overdubs:
        src = outs.get(part) or part
        y, sr = dsp.load(src, gsr)
        stage = []
        if want_pitch:
            g = guide
            if len(g) < len(y):
                g = np.pad(g, ((0, len(y) - len(g)), (0, 0)))
            curve, notes = PM.plan(g[:len(y)], y, sr, a.pitch, a.vibrato, a.pitch_tolerance, a.pitch_max, chords,
                                   a._protect, a.pitch_only)
            by, med = PM.summary(notes)
            tmp = od / f".{Path(part).stem}.pitch.wav"
            inp = tmp.with_suffix(".in.wav")
            sf.write(str(inp), y, sr, subtype="FLOAT")        # exactly the audio that was analysed
            res = PM.apply(inp, tmp, curve, notes, sr, len(y), y.shape[1])
            if res is not None:
                y = res if res.ndim > 1 else res[:, None]
                stage.append(f"pitch {a.pitch:g}")
            asks = [r for r in notes if r["action"] == "ask"]
            rows.append((Path(part).name, by, med, asks))
            for t in (tmp, tmp.with_suffix(".in.wav")):
                if t.exists():
                    t.unlink()
        f, tr = per_part(a.formant, Path(part).name), per_part(a.transpose, Path(part).name)
        if abs(f) > 1e-4 or abs(tr) > 1e-4:
            before = y
            y = FM.shift(y, sr, f, tr, franges)
            if a._protect:                                     # protected areas stay exactly as sung here too
                pm = np.zeros(int(len(y) / sr / FR_S) + 1, bool)
                for x0, x1 in a._protect:
                    pm[int(x0 / FR_S):int(np.ceil(x1 / FR_S))] = True
                y = AO.splice_protected(before, y, pm, sr)      # `before` is already the take there, untouched
            if abs(f) > 1e-4:
                stage.append(f"formant {f:+g}")
            if abs(tr) > 1e-4:
                stage.append(f"transpose {tr:+g}")
        if stage:
            timing = "aligned, " if outs.get(part) else ""
            path = dsp.save(od / f"{Path(part).stem} ({timing}{', '.join(stage)}).wav", y, sr, 24)
            outs[part] = str(path)
    for name, by, med, asks in rows:
        fixed = by.get("fix", 0)
        md.append(f"| {name} | {fixed} | {med:.0f} c | {by.get('ok', 0)} | {by.get('flag', 0)} | {len(asks)} | |")
    for name, by, med, asks in rows:
        for r in asks:
            md.append(f"- ASK {name} at {int(r['t0'] // 60)}:{r['t0'] % 60:05.2f}: matching it would clash with the chord "
                      f"({r.get('chord', '?')}); the chord suggests {r.get('suggest')}. Left as sung.")
    md += ["", "Final files (timing, then pitch, then formant):", ""] + [f"- `{v}`" for v in outs.values() if v]
    return md


def name_lead(a):
    """--lead NAME: the named file becomes the lead (the first file takes its place among the parts)."""
    name = getattr(a, "lead_name", None)
    if not name:
        return
    files = [a.lead] + list(a.overdubs)
    hit = [f for f in files if name in (f, Path(f).name, Path(f).stem)] or \
          [f for f in files if Path(f).stem.lower().startswith(name.lower())]
    if len(hit) != 1:
        sys.exit(f"--lead {name!r} is " + ("not one of the files" if not hit else "more than one of the files")
                 + ": give the file name of one part (" + ", ".join(Path(f).name for f in files) + ")")
    a.lead, a.overdubs = hit[0], [f for f in files if f != hit[0]]


def main():
    if "--list-presets" in sys.argv:
        print("\n".join(AO.describe(k) for k in AO.PRESETS))
        return
    ap = build_parser()
    defaults = {k: ap.get_default(k) for k in vars(ap.parse_args(["x", "y"]))}
    a = ap.parse_args()
    if a.list_presets:
        print("\n".join(AO.describe(k) for k in AO.PRESETS))
        return
    AO.apply_preset(a, a.preset, defaults)
    if not a.no_timing:
        AO.reference(a, len(a.overdubs))              # the person's choice; a stack with none ends here, in one sentence
        name_lead(a)
    a._protect, a._sync = AO.ranges(a.protect), AO.syncs(a.sync)
    od = out_at(a.out, "vocalign")
    md, outs = (["# Vocal alignment", "", "Timing step skipped (--no-timing)."], {}) if a.no_timing else timing_stage(a, od)
    if AO.reference_line(a):
        md[1:1] = ["", AO.reference_line(a)]
    if a.preset:
        md[1:1] = ["", f"Preset: {AO.describe(a.preset)}"]
    if a._protect:
        md += ["", "Protected (left exactly as sung): " + ", ".join(f"{x:.2f}-{y:.2f} s" for x, y in a._protect)]
    md += pitch_and_formant(a, od, outs)
    (od / "VOCALIGN.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
