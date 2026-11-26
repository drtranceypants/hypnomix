#!/usr/bin/env python3
"""This bounce against the previous one: what changed, in plain words, with the numbers behind it.

Give it two exports of the same song (the old one first). It lines the two up (if one starts later it finds
by how much, to the sample, and says so), then measures both over the part they share:

  loudness      integrated, and the loudest 10 seconds; true peak
  dynamics      crest (peak minus average level), peak-to-loudness, loudness range
  tone          8 bands from sub to air: which got brighter or darker, by how many dB, at matched loudness
  stereo width  the same 8 bands: side against mid, wider or narrower
  sections      the song's sections (see `hypnomix sections`), loudness of each in both bounces
  where they differ most: the three spots where the two sound least alike once the loudness is matched,
                each as a level-matched A / B pair you can play (the same files the review page plays)

COMPARE.md opens with one line ("B is 1.2 dB louder, 1.5 dB brighter above 8 kHz, a little narrower in the
lows; the 2nd chorus-like section changed most") and then the tables. COMPARE.json holds the same numbers.
Everything is measured, not heard: use the A / B pairs to listen.

It stops politely when the two files are not the same song (very low similarity once aligned; --force compares
anyway), when a file is silent or under two seconds long, or when the sample rates differ (--resample brings B
to A's rate; neither file is changed). Nothing is written but the report folder, and an existing report is
never overwritten.

Usage:
    hypnomix compare OLD.wav NEW.wav [--names "old,new"] [--out DIR] [--bpm N] [--resample] [--force]

    --names     what to call the two bounces in the report (default: the file names)
    --out       the report folder (default hypnomix-out/compare/<old> vs <new>; refuses if it holds a report)
    --bpm       the song's tempo, if the section finder gets it wrong (see `hypnomix sections`)
"""
import argparse, json, sys, tempfile, warnings
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix.core import dsp, paths
from hypnomix.ears import match

warnings.filterwarnings("ignore")

WIN = 6.0                      # seconds per A/B spot (2 before the centre, 4 after: what `hypnomix ab` uses)
PRE, POST = 2.0, 4.0
SIMILAR_MIN = 0.40             # below this the two are not the same song
SIMILAR_CAUTION = 0.65
N_SPOTS = 3
SPOT_MIN = 0.5                 # dB: a spot that differs less than this is not worth an A/B
FFT_N, FFT_HOP = 4096, 2048
BANDS = match.BANDS            # 8 named bands, sub .. air
FINE = [e for _, lo, hi in BANDS for e in [(lo, float(np.sqrt(lo * hi))), (float(np.sqrt(lo * hi)), hi)]]   # each split in two
REGION = ["lows"] * 3 + ["mids"] * 2 + ["highs"] * 3


class CompareError(Exception):
    """Something the person has to fix. The message is plain words."""


def khz(x):
    return f"{x / 1000:g} kHz" if x >= 1000 else f"{x:g} Hz"


def mss(t):
    t = max(0.0, float(t))
    return f"{int(t // 60)}:{int(t % 60):02d}"


# ---------------------------------------------------------------- reading
def read(path, sr=None):
    p = Path(path)
    if not p.is_file():
        raise CompareError(f"{p} not found")
    try:
        y, s = dsp.load(p, sr)
    except Exception as e:
        reason = str(e).split("as audio: ", 1)[-1] if isinstance(e, dsp.AudioReadError) else "not an audio file hypnomix can read"
        raise CompareError(f"can't read {p.name} as audio: {reason}")
    return dsp.stereo(y), s


# ---------------------------------------------------------------- alignment
def _env(m, sr, rate=200):
    h = max(1, int(sr / rate))
    n = len(m) // h
    e = np.sqrt(np.sqrt(np.mean(m[: n * h].reshape(n, h) ** 2, axis=1)))
    return e - e.mean(), h


def _xcorr_lag(a, b, max_lag, min_overlap):
    """(L, coefficient): the shift L (a[n] ~ b[n + L]) with the highest normalised cross-correlation, searching
    |L| <= max_lag over at least min_overlap samples. The coefficient is 1.0 for the same signal at a different level."""
    from scipy.signal import fftconvolve
    la, lb = len(a), len(b)
    full = fftconvolve(b, a[::-1], mode="full")
    lags = np.arange(la + lb - 1) - (la - 1)
    lo_a, hi_a = np.maximum(0, -lags), np.minimum(la, lb - lags)
    ok = (hi_a - lo_a >= min_overlap) & (np.abs(lags) <= max_lag)
    if not ok.any():
        return 0, 0.0
    ea, eb = np.concatenate([[0], np.cumsum(a * a)]), np.concatenate([[0], np.cumsum(b * b)])
    L, lo, hi = lags[ok], lo_a[ok], hi_a[ok]
    coef = full[ok] / np.sqrt((ea[hi] - ea[lo]) * (eb[hi + L] - eb[lo + L]) + 1e-12)
    k = int(np.argmax(coef))
    return int(L[k]), float(coef[k])


def find_lag(a, b, sr, max_lag_s=60.0):
    """Samples L so that a[n] is b[n + L] (L > 0: b starts later; L < 0: a starts later), and how sure it is (0 when it
    could only be judged from the loudness shape, to about 5 ms). Coarse from the whole waveform at a low sample rate
    (it is the whole song that has to match, so a repeated chorus cannot fool it); from the loudness envelopes when
    the waveforms do not match (a different phase response); then refined to the sample around the loudest part."""
    from scipy.signal import fftconvolve, resample_poly
    ma, mb = a.sum(axis=1), b.sum(axis=1)
    short = min(len(ma), len(mb))
    f = max(1, sr // 8000)
    da, db_ = resample_poly(ma, 1, f), resample_poly(mb, 1, f)
    max_lag = int(max_lag_s * sr / f)
    min_ov = int(max(2 * sr / f, 0.5 * short / f))
    lag, coef = _xcorr_lag(da, db_, max_lag, min_ov)
    coarse, tol = lag * f, 2 * f
    if coef < 0.15:                                          # the waveforms do not line up: use the loudness shape
        ea, h = _env(ma, sr)
        eb, _ = _env(mb, sr)
        if len(ea) < 4 or len(eb) < 4:
            return 0, 0.0
        lag, _ = _xcorr_lag(ea, eb, int(max_lag_s * sr / h), int(0.5 * min(len(ea), len(eb))))
        coarse, tol = lag * h, 2 * h
    # refine on the full-rate waveform: a 4 s stretch of a at its loudest, looked for in b near the coarse answer
    m, N = int(0.02 * sr) + tol, int(4 * sr)
    lo, hi = max(0, -coarse + m), min(len(ma) - N, len(mb) - N - coarse - m)
    if hi > lo:
        blk = int(0.5 * sr)
        nb = len(ma) // blk
        pw = (ma[: nb * blk] ** 2).reshape(nb, blk).sum(axis=1)
        cand = np.arange(lo // blk, max(lo // blk + 1, hi // blk))
        cand = cand[(cand * blk >= lo) & (cand * blk <= hi)]
        if len(cand):
            a0 = int(cand[int(np.argmax(pw[cand]))] * blk)
            seg = ma[a0:a0 + N]
            win = mb[a0 + coarse - m:a0 + coarse + N + m]
            c = fftconvolve(win, seg[::-1], mode="valid")                  # len 2m+1; index j: offset j - m
            en = np.concatenate([[0], np.cumsum(win ** 2)])
            loc = np.sqrt(np.maximum(en[N:N + 2 * m + 1] - en[:2 * m + 1], 1e-20)) * np.sqrt(float(np.sum(seg ** 2)) + 1e-20)
            nc = c / loc
            j = int(np.argmax(nc))
            if nc[j] >= 0.2:
                return coarse + (j - m), float(nc[j])
    return coarse, 0.0


def align(a, b, sr):
    """Trim the one that starts earlier. Returns (a, b, lag_samples, note)."""
    lag, conf = find_lag(a, b, sr)
    if lag > 0:
        b = b[lag:]
    elif lag < 0:
        a = a[-lag:]
    n = min(len(a), len(b))
    return a[:n], b[:n], lag, conf


# ---------------------------------------------------------------- measuring
def frame_bands(x, sr, edges, n=FFT_N, hop=FFT_HOP):
    """Power per frame in each band: (frames, bands), for a 1-D signal."""
    if len(x) < n:
        x = np.pad(x, (0, n - len(x)))
    f = np.fft.rfftfreq(n, 1 / sr)
    M = np.stack([((f >= lo) & (f < hi)).astype(float) for lo, hi in edges], axis=1)
    win = np.hanning(n)
    starts = np.arange(0, len(x) - n + 1, hop)
    out = np.empty((len(starts), len(edges)))
    for i in range(0, len(starts), 256):
        idx = starts[i:i + 256]
        fr = x[idx[:, None] + np.arange(n)[None, :]] * win
        out[i:i + 256] = (np.abs(np.fft.rfft(fr, axis=1)) ** 2) @ M
    return out / n


def to_db(p, floor_rel=1e-7):
    tot = p.sum(axis=-1, keepdims=True)
    return 10 * np.log10(p + floor_rel * tot + 1e-20)


def true_peak(y, sr, chunk_s=20.0, pad=2048):
    """dBTP like `dsp.true_peak` (4x oversampling), but one stretch at a time, so a long song does not need a copy of
    itself four times over in memory. Each stretch is read with a little extra either side and only its own part counts,
    so the filter's edges never make a peak."""
    from scipy.signal import resample_poly
    if sr >= 176400:
        return dsp.true_peak(y, sr)
    n, c = len(y), int(chunk_s * sr)
    best = 0.0
    for a in range(0, n, c):
        lo, hi = max(0, a - pad), min(n, a + c + pad)
        up = resample_poly(y[lo:hi], 4, 1, axis=0)
        best = max(best, float(np.max(np.abs(up[(a - lo) * 4:(min(n, a + c) - lo) * 4]))))
    return float(20 * np.log10(max(best, 1e-12)))


class Take:
    """One bounce, aligned and trimmed, with the per-frame band powers measured once."""

    def __init__(self, y, sr):
        self.y, self.sr = y, sr
        mid, side = (y[:, 0] + y[:, 1]) / 2, (y[:, 0] - y[:, 1]) / 2
        Pm, Ps = frame_bands(mid, sr, FINE), frame_bands(side, sr, FINE)
        self.Pm, self.Ps = Pm, Ps                        # (frames, 16)
        self.P = Pm + Ps
        self.t = (np.arange(len(Pm)) * FFT_HOP + FFT_N / 2) / sr

    def coarse(self, P):
        return P.reshape(P.shape[0], 8, 2).sum(axis=2) if P.ndim == 2 else P.reshape(8, 2).sum(axis=1)

    def numbers(self):
        y, sr = self.y, self.sr
        L, tp = dsp.lufs(y, sr), true_peak(y, sr)
        loud = match.loudest(y, sr, 10.0)
        tot = self.coarse(self.P).sum(axis=0)
        wm, ws = self.coarse(self.Pm).sum(axis=0), self.coarse(self.Ps).sum(axis=0)
        mid, side = (y[:, 0] + y[:, 1]) / 2, (y[:, 0] - y[:, 1]) / 2
        return dict(
            lufs=round(L, 2), loudest_10s_lufs=round(dsp.lufs(loud, sr), 2), true_peak=round(tp, 2),
            crest_db=round(dsp.sample_peak(y) - dsp.rms_db(y), 2), plr_db=round(tp - L, 2),
            lra_lu=round(match.short_term_lra(y, sr), 2),
            bands_db={n: round(float(v), 2) for (n, _, _), v in zip(BANDS, 10 * np.log10(tot / tot.sum() + 1e-20))},
            width_db={n: round(float(v), 2) for (n, _, _), v in zip(BANDS, 10 * np.log10((ws + 1e-9 * (wm + ws) + 1e-20) / (wm + 1e-9 * (wm + ws) + 1e-20)))},
            width_overall_db=round(max(-90.0, dsp.rms_db(side) - dsp.rms_db(mid)), 2),
            correlation=round(float(dsp.correlation(y)), 3))


def similarity(ta, tb):
    """0..1: how alike the two songs' loudness curves are over time, band by band (level and overall tone ignored).
    The middle band wins, so one band that was heavily edited does not make the same song look like another."""
    step = max(1, int(0.2 * ta.sr / FFT_HOP))             # about 5 frames a second is plenty
    A, B = to_db(ta.P[::step]), to_db(tb.P[::step])
    A, B = A - A.mean(axis=0), B - B.mean(axis=0)
    d = np.sqrt((A ** 2).sum(axis=0) * (B ** 2).sum(axis=0))
    r = np.where(d > 1e-9, (A * B).sum(axis=0) / np.maximum(d, 1e-9), 0.0)
    return float(np.median(r))


def sections_of(y, sr, bpm):
    """[(start, end, label, role, repeat)] for the aligned A, from `hypnomix sections`; equal slices when it fails."""
    note = None
    try:
        from hypnomix.ears import sections as S
        with tempfile.TemporaryDirectory(prefix="hypnomix-work-") as td:
            p = Path(td) / "a.wav"
            sf.write(str(p), y.astype(np.float32), sr, subtype="FLOAT")
            r = S.analyse(p, bpm)
        secs = [dict(start=s["start"], end=s["end"], label=s["label"], role=s.get("role", ""), repeat=s["repeat"])
                for s in r["sections"] if s["end"] - s["start"] >= 1.0]
        if len(secs) >= 2:
            if r.get("even_split"):
                note = "no clear section changes were found, so the song is cut into equal slices"
                for s in secs:
                    s.update(label="", role="", repeat=1)
            return secs, note
        note = "the section finder found fewer than two sections"
    except Exception as e:
        note = f"the section check failed ({type(e).__name__}: {str(e)[:80]}), so the song is cut into equal slices"
    dur = len(y) / sr
    k = int(max(2, min(8, dur // 10)))
    cuts = np.linspace(0, dur, k + 1)
    return [dict(start=float(a), end=float(b), label="", role="", repeat=1) for a, b in zip(cuts[:-1], cuts[1:])], note


def section_name(s, secs):
    if s["role"] == "chorus-like":
        return f"the {_ord(s['repeat'])} chorus-like section"
    if s["label"] and sum(1 for x in secs if x["label"] == s["label"]) > 1:
        return f"the {_ord(s['repeat'])} {s['label']} section"
    if s["label"] and s["start"] < 1.0 and s["role"] == "intro":
        return "the intro"
    return f"the section at {mss(s['start'])}"


def _ord(n):
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


TONE_UP = [("has", "more sub bass (under 60 Hz)"), ("has", "more bass (60-120 Hz)"), ("has", "more upper bass (120-250 Hz)"),
           ("has", "more body (250-500 Hz)"), ("has", "more midrange (500 Hz - 2 kHz)"), ("has", "more bite (2-4 kHz)"),
           ("is", "brighter at 4-8 kHz"), ("is", "brighter above 8 kHz")]
TONE_DOWN = [("has", "less sub bass (under 60 Hz)"), ("has", "less bass (60-120 Hz)"), ("has", "less upper bass (120-250 Hz)"),
             ("has", "less body (250-500 Hz)"), ("has", "less midrange (500 Hz - 2 kHz)"), ("has", "less bite (2-4 kHz)"),
             ("is", "darker at 4-8 kHz"), ("is", "darker above 8 kHz")]


def tone_phrase(i, d):
    """'1.5 dB brighter above 8 kHz' / '1.2 dB more bass (60-120 Hz)'."""
    return f"{abs(d):.1f} dB {(TONE_UP if d > 0 else TONE_DOWN)[i][1]}"


def tone_sentence(name, i, d):
    return f"{name} {(TONE_UP if d > 0 else TONE_DOWN)[i][0]} {tone_phrase(i, d)}"


def spots(ta, tb, secs):
    """Scores for every 6 s window (hop 3 s): how differently the two sound once loudness is matched. Returns
    (list of dicts best first, per-section mean score list)."""
    sr, n = ta.sr, len(ta.y)
    win = min(WIN, n / sr)
    hop = 3.0
    starts = np.arange(0, max(1e-9, n / sr - win) + 1e-9, hop)
    if len(starts) == 0:
        starts = np.array([0.0])
    rows = []
    for t0 in starts:
        a, b = int(t0 * sr), int((t0 + win) * sr)
        la, lb = dsp.lufs(ta.y[a:b], sr), dsp.lufs(tb.y[a:b], sr)
        if la < -55 or lb < -55:
            continue
        m = (ta.t >= t0) & (ta.t < t0 + win)
        if m.sum() < 2:
            continue
        da, db_ = to_db(ta.P[m].sum(axis=0)), to_db(tb.P[m].sum(axis=0))
        diff = db_ - da
        dev_band = diff - diff.mean()
        rows.append(dict(start=float(t0), end=float(t0 + win), dL=lb - la, bands=dev_band, tone=float(np.sqrt(np.mean(dev_band ** 2)))))
    if not rows:
        return [], []
    med = float(np.median([r["dL"] for r in rows]))
    for r in rows:
        r["level"] = r["dL"] - med
        r["score"] = float(np.sqrt(r["tone"] ** 2 + r["level"] ** 2))
        coarse = r["bands"].reshape(8, 2).mean(axis=1)
        i = int(np.argmax(np.abs(coarse)))
        r["band"], r["band_db"] = i, float(coarse[i])
    best = []
    for r in sorted(rows, key=lambda r: -r["score"]):
        if r["score"] < SPOT_MIN:
            break
        if all(abs(r["start"] - q["start"]) >= win for q in best):
            best.append(r)
        if len(best) == N_SPOTS:
            break
    per_section = []
    for s in secs:
        sc = [r["score"] for r in rows if s["start"] <= (r["start"] + r["end"]) / 2 < s["end"]]
        per_section.append(float(np.mean(sc)) if sc else 0.0)
    return best, per_section


# ---------------------------------------------------------------- the words
def word_diff(d, same=0.3):
    return "the same" if abs(d) < same else f"{abs(d):.1f} dB {'higher' if d > 0 else 'lower'}"


def summary_line(A, B, nm, per_sec, secs, identical):
    """One line: 'new is 1.2 dB louder, 1.5 dB brighter above 8 kHz, a little narrower in the lows; the 2nd chorus-like
    section changed most.'"""
    if identical:
        return f"{nm[1]} and {nm[0]} hold the same audio: nothing changed."
    dl = B["lufs"] - A["lufs"]
    parts = [f"{nm[1]} is about as loud as {nm[0]}" if abs(dl) < 0.3 else f"{nm[1]} is {abs(dl):.1f} dB {'louder' if dl > 0 else 'quieter'}"]
    d = [B["bands_db"][n] - A["bands_db"][n] for n, _, _ in BANDS]
    i = int(np.argmax(np.abs(d)))
    if abs(d[i]) >= 0.8:
        parts.append(tone_phrase(i, d[i]))
    w = [B["width_db"][n] - A["width_db"][n] for n, _, _ in BANDS]
    j = int(np.argmax(np.abs(w)))
    if abs(w[j]) >= 1.0:
        q = "a little " if abs(w[j]) < 2.5 else "much " if abs(w[j]) > 5 else ""
        parts.append(f"{q}{'narrower' if w[j] < 0 else 'wider'} in the {REGION[j]}")
    s = ", ".join(parts)
    if per_sec and max(per_sec) >= 1.0 and len(secs) > 1:
        s += f"; {section_name(secs[int(np.argmax(per_sec))], secs)} changed most"
    return s + "."


def wcell(v):
    return "mono" if v < -80 else f"{v:.1f}"


def table(rows, head):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def build_report(nm, A, B, lag_s, conf, sim, notes, secs, sec_rows, spot_rows, total_s, lens, resampled, line):
    a, b = nm
    L = [f"# Compare: {a} against {b}", "", line, ""]
    L += ["## What was compared", ""]
    if abs(lag_s) < 0.0005:
        L.append("- The two start together (no offset).")
    else:
        later = b if lag_s > 0 else a
        L.append(f"- **{later} starts {abs(lag_s):.3f} s later** than the other. The two were lined up first"
                 + (" (to the sample, from the waveform)." if conf else " (from the loudness shape, to about 5 ms)."))
    L.append(f"- Compared over {mss(total_s)} ({total_s:.1f} s), the part both share."
             + ("" if abs(lens[0] - lens[1]) < 0.05 else f" After lining up, {a if lens[0] > lens[1] else b} runs {abs(lens[0] - lens[1]):.1f} s longer; the extra is not compared."))
    L.append(f"- Similarity {sim:.2f} (1.00 = the same song, mixed alike)"
             + ("; only partly alike: the arrangement may have changed, so read the section rows with care." if sim < SIMILAR_CAUTION else "."))
    if resampled:
        L.append(f"- {b} was resampled to {resampled} Hz to match {a}.")
    for n in notes:
        L.append(f"- {n}")
    L += ["", "## Loudness and peaks", ""]
    rows = []
    for lab, k, unit in (("Integrated loudness", "lufs", "LUFS"), ("Loudest 10 seconds", "loudest_10s_lufs", "LUFS"),
                         ("True peak", "true_peak", "dBTP")):
        d = B[k] - A[k]
        rows.append((lab, f"{A[k]:.1f} {unit}", f"{B[k]:.1f} {unit}", f"{d:+.1f} dB"))
    L += [table(rows, ["", a, b, "change"]), ""]
    L += ["## Dynamics", "",
          "Crest is the gap between the loudest peak and the average level; peak-to-loudness is the true peak minus the loudness; "
          "loudness range is how far the level moves from quiet to loud. Smaller numbers mean squashed.", ""]
    rows = [(lab, f"{A[k]:.1f} dB", f"{B[k]:.1f} dB", f"{B[k] - A[k]:+.1f} dB") for lab, k in
            (("Crest", "crest_db"), ("Peak-to-loudness", "plr_db"), ("Loudness range", "lra_lu"))]
    L += [table(rows, ["", a, b, "change"]), ""]
    L += ["## Tone by band", "",
          "Each band's share of the song's energy, in dB of the whole (so loudness itself does not matter). "
          "More in one band means a little less in the others.", ""]
    rows = []
    for i, (n, lo, hi) in enumerate(BANDS):
        d = B["bands_db"][n] - A["bands_db"][n]
        rows.append((f"{n} ({khz(lo)}-{khz(hi)})", f"{A['bands_db'][n]:.1f}", f"{B['bands_db'][n]:.1f}", f"{d:+.1f} dB",
                     "" if abs(d) < 0.5 else (TONE_UP if d > 0 else TONE_DOWN)[i][1]))
    L += [table(rows, ["band", a, b, "change", "in words"]), ""]
    L += ["## Stereo width by band", "", "Side signal against mid signal in each band (0 dB = as much side as mid; lower = narrower).", ""]
    rows = []
    for i, (n, lo, hi) in enumerate(BANDS):
        d = B["width_db"][n] - A["width_db"][n]
        rows.append((f"{n} ({khz(lo)}-{khz(hi)})", wcell(A['width_db'][n]), wcell(B['width_db'][n]), f"{d:+.1f} dB",
                     "" if abs(d) < 1.0 else ("wider" if d > 0 else "narrower")))
    rows.append(("whole song", wcell(A['width_overall_db']), wcell(B['width_overall_db']), f"{B['width_overall_db'] - A['width_overall_db']:+.1f} dB", ""))
    L += [table(rows, ["band", a, b, "change", "in words"]), "",
          f"Left/right correlation: {A['correlation']:+.2f} against {B['correlation']:+.2f}.", ""]
    L += ["## Loudness by section", ""]
    if sec_rows:
        L += [table(sec_rows, ["time", "section", a, b, "change", "how different they sound"]), ""]
    else:
        L += ["No sections could be measured.", ""]
    L += ["## Where they differ most", ""]
    if spot_rows:
        L += [f"Each pair is level-matched (B is turned up or down up to 3 dB so you hear tone and balance, not loudness). "
              f"In the files, **A (now) is {a}** and **B (fixed) is {b}**. They are in `ab/` next to this report, and "
              "`ab/ab.json` is the same list `hypnomix review` reads.", ""]
        for r in spot_rows:
            L.append(f"{r['n']}. **{r['at']}** ({r['section']}): {r['note']}  \n   `ab/{r['a']}` and `ab/{r['b']}`")
        L.append("")
    else:
        L += ["No stretch of the song differs by more than a fraction of a dB once loudness is matched"
              + (": the two differ by level alone." if abs(B['lufs'] - A['lufs']) >= 0.3 else "."), ""]
    L += ["## What to do with this", "",
          "These are measurements, not listening. Play each A / B pair, then trust your ears over the numbers. "
          "Nothing was changed in either file.", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- the whole job
def compare(path_a, path_b, names=None, out=None, bpm=None, resample=False, force=False, log=print):
    if out:                                   # refuse an existing report folder before any measuring
        od = Path(out).expanduser()
        if (od / "COMPARE.md").exists() or (od / "ab" / "ab.json").exists():
            raise CompareError(f"{od} already holds a comparison. Nothing was written: choose another --out.")
    else:
        base = paths.OUT / "compare" / f"{Path(path_a).stem} vs {Path(path_b).stem}"
        od, k = base, 1
        while (od / "COMPARE.md").exists():
            k += 1
            od = base.with_name(base.name + f" {k}")
    ya, sra = read(path_a)
    yb, srb = read(path_b)
    resampled = None
    if resample and srb != sra:
        import math
        from scipy.signal import resample_poly
        g = math.gcd(int(sra), int(srb))
        yb, resampled, srb = resample_poly(yb, sra // g, srb // g, axis=0), sra, sra
    if sra != srb:
        raise CompareError(f"{Path(path_a).name} is {sra} Hz and {Path(path_b).name} is {srb} Hz. They can't be compared "
                           f"as they are: run again with --resample to bring the second to {sra} Hz (neither file is changed).")
    for p, y in ((path_a, ya), (path_b, yb)):
        if len(y) < 2 * sra:
            raise CompareError(f"{Path(p).name} is under two seconds long: too short to compare.")
        if dsp.sample_peak(y) < -80:
            raise CompareError(f"{Path(p).name} is silent: nothing to compare.")
    if names:
        nm = [x.strip() for x in names.split(",")]
        if len(nm) != 2 or not all(nm):
            raise CompareError('--names takes two names separated by a comma, like --names "old,new"')
    else:
        nm = [Path(path_a).stem, Path(path_b).stem]
        if nm[0] == nm[1]:
            nm = ["A", "B"]
    n0 = (len(ya) / sra, len(yb) / sra)
    log("lining the two up …")
    ya, yb, lag, conf = align(ya, yb, sra)
    if len(ya) < 2 * sra:
        raise CompareError("after lining the two up less than two seconds are shared: they are probably not the same song.")
    identical = bool(np.array_equal(ya, yb))
    lens = (n0[0] - max(0, -lag) / sra, n0[1] - max(0, lag) / sra)
    log("measuring both …")
    ta, tb = Take(ya, sra), Take(yb, sra)
    sim = similarity(ta, tb)
    if sim < SIMILAR_MIN and not force:
        raise CompareError(f"these do not look like the same song (similarity {sim:.2f} after lining them up; the same song "
                           f"mixed two ways is usually above 0.8). Check you gave the old and new bounce of one song. "
                           "To compare them anyway, add --force.")
    A, B = ta.numbers(), tb.numbers()
    notes = []
    if sim < SIMILAR_MIN:
        notes.append(f"**Forced:** the two do not look like the same song (similarity {sim:.2f}); the comparison may mean little.")
    log("finding the sections …")
    secs, snote = sections_of(ya, sra, bpm)
    if snote:
        notes.append(snote[0].upper() + snote[1:] + ".")
    log("looking for where they differ most …")
    best, per_sec = spots(ta, tb, secs)
    sec_rows = []
    for k, s in enumerate(secs):
        a0, b0 = int(s["start"] * sra), int(s["end"] * sra)
        la, lb = dsp.lufs(ya[a0:b0], sra), dsp.lufs(yb[a0:b0], sra)
        lab = (s["label"] + (f" ({s['role']})" if s["role"] else "")) if s["label"] else "slice"
        sec_rows.append((f"{mss(s['start'])}-{mss(s['end'])}", lab, f"{la:.1f}", f"{lb:.1f}", f"{lb - la:+.1f} dB",
                         "about the same" if per_sec[k] < 0.5 else "a little different" if per_sec[k] < 1.5 else "different" if per_sec[k] < 3 else "very different"))
    line = summary_line(A, B, nm, per_sec, secs, identical)

    od.mkdir(parents=True, exist_ok=True)

    from hypnomix.workflow import ab
    adir = od / "ab"
    manifest, spot_rows = {}, []
    if best:
        adir.mkdir(exist_ok=True)
    for n, r in enumerate(best, 1):
        fid = f"spot-{n}"
        k = next((i for i, s in enumerate(secs) if s["start"] <= (r["start"] + r["end"]) / 2 < s["end"]), 0)
        where = section_name(secs[k], secs)
        bits = []
        if abs(r["level"]) >= 0.5:
            bits.append(f"{nm[1]} is {abs(r['level']):.1f} dB {'louder' if r['level'] > 0 else 'quieter'} here than it is over the whole song")
        if abs(r["band_db"]) >= 1.0:
            bits.append(tone_sentence(nm[1], r["band"], r["band_db"]))
        what = "; ".join(bits) if bits else "a small difference in balance"
        row = ab.write_pair(adir, fid, ab.cut(ya, sra, r["start"] + PRE, PRE, POST), ab.cut(yb, sra, r["start"] + PRE, PRE, POST),
                            sra, f"{mss(r['start'])}-{mss(r['end'])}: {what}")
        row.update(at=f"{mss(r['start'])}-{mss(r['end'])}", start_s=round(r["start"], 2), end_s=round(r["end"], 2),
                   score_db=round(r["score"], 2))
        manifest[fid] = row
        spot_rows.append(dict(n=n, at=row["at"], section=where, note=f"{what}. For the A / B, {nm[1]} is turned {row['matched_db']:+.1f} dB to match.",
                              a=row["a"], b=row["b"]))
    if manifest:
        (adir / "ab.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    text = build_report(nm, A, B, lag / sra, conf, sim, notes, secs, sec_rows, spot_rows, len(ya) / sra, lens, resampled, line)
    (od / "COMPARE.md").write_text(text, encoding="utf-8")
    (od / "COMPARE.json").write_text(json.dumps(dict(
        names=nm, files=[str(path_a), str(path_b)], summary=line, offset_s=round(lag / sra, 4), similarity=round(sim, 3),
        compared_s=round(len(ya) / sra, 2), a=A, b=B, sections=[dict(s, a_lufs=float(r[2]), b_lufs=float(r[3])) for s, r in zip(secs, sec_rows)],
        spots=[dict(manifest[f"spot-{r['n']}"], section=r["section"]) for r in spot_rows]), indent=1), encoding="utf-8")
    return dict(folder=od, line=line, text=text, offset_s=lag / sra, similarity=sim, A=A, B=B, spots=spot_rows, sections=sec_rows)


def main():
    from hypnomix.core import args as A
    ap = argparse.ArgumentParser(prog="hypnomix compare", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old"); ap.add_argument("new")
    ap.add_argument("--names", help='two names for the report, like "old,new"')
    ap.add_argument("--out", help="report folder (default hypnomix-out/compare/<old> vs <new>)")
    ap.add_argument("--bpm", type=A.number(20, 400), help="the song's tempo, if the section finder gets it wrong (20 to 400)")
    ap.add_argument("--resample", action="store_true", help="bring the second file to the first's sample rate")
    ap.add_argument("--force", action="store_true", help="compare even if the two do not look like the same song")
    a = ap.parse_args()
    paths.check_out(a.out)                    # an unwritable --out ends here, not after the measuring
    try:
        r = compare(a.old, a.new, a.names, a.out, a.bpm, a.resample, a.force, log=lambda s: print(s, file=sys.stderr))
    except CompareError as e:
        sys.exit(f"hypnomix compare: {e}")
    print(r["text"])
    print(f"report: {r['folder'] / 'COMPARE.md'}", file=sys.stderr)


if __name__ == "__main__":
    main()
