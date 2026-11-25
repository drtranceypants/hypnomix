"""Presets, protected areas and sync points for `hypnomix vocalign`.

  presets        named starting points (every option can still be set on top of one)
  protect        time ranges where a part is never moved: the original audio stays sample for sample there, and the
                 move fades out in the 300 ms before the range and back in after it
  sync points    moments that must line up exactly with the guide. `62.4` finds the matching onsets of guide and part
                 near 62.4 s; `62.40=62.31` says the guide's moment at 62.40 s is the part's moment at 62.31 s.
                 A sync point overrides the gentleness: the part moves the whole way there (still within the cap).

Times are seconds from the start of the files (or of the song, for a Live set), or m:ss.xx.
All plans use the convention of vocalign: per 10 ms frame t, the output plays the part's audio from t + o[t]
(o > 0: the part was late and is pulled earlier).
"""
import re

import numpy as np

FR_S = 0.01

# Every preset only sets defaults: an option given on the command line wins.
PRESETS = {
    "gentle-stack": dict(desc="the default for a stack: only clearly-off words move, everything else 10%",
                         stack_strength=0.1, fix_strength=0.8, fix_over_ms=30.0, grid=0.3, cap_ms=60.0),
    "natural-double": dict(desc="a double that should still sound like two takes: 70% toward the guide, smooth speed changes",
                           to_lead=True, strength=0.7, mode="gentle", max_ms=80.0),
    "tight-pop": dict(desc="modern pop/R&B stacks: doubles land on the guide, tails trimmed, gentle pitch match",
                      to_lead=True, strength=1.0, mode="tight", max_ms=120.0, trim_tails=True, pitch=0.35, vibrato=0.3),
    "loose-folk": dict(desc="folk/country/indie: only the worst words, half way; no grid pull",
                       stack_strength=0.05, fix_strength=0.5, fix_over_ms=45.0, grid=0.0, cap_ms=40.0),
    "rap-doubles": dict(desc="rap doubles and ad-lib stacks: consonants on top of each other, tails trimmed",
                        to_lead=True, strength=1.0, mode="tight", max_ms=150.0, trim_tails=True),
}


def apply_preset(args, name, defaults):
    """Fill every option the user did NOT give (still equal to its default) from the preset."""
    if not name:
        return args
    if name not in PRESETS:
        raise SystemExit(f"unknown preset {name!r}: one of {', '.join(PRESETS)}")
    for k, v in PRESETS[name].items():
        if k == "desc":
            continue
        if getattr(args, k, None) == defaults.get(k):
            setattr(args, k, v)
    return args


def seconds(s):
    """'62.4', '1:02.4' or '0:01:02.4' -> seconds."""
    s = str(s).strip()
    parts = s.split(":")
    try:
        v = 0.0
        for p in parts:
            v = v * 60 + float(p)
        return v
    except ValueError:
        raise SystemExit(f"not a time: {s!r} (use seconds like 62.4 or m:ss like 1:02.4)")


def ranges(items):
    """['62-70.5', '1:30-1:41'] -> [(62.0, 70.5), (90.0, 101.0)] (sorted, merged)."""
    out = []
    for it in items or ():
        for one in str(it).split(","):
            one = one.strip()
            if not one:
                continue
            m = re.match(r"^\s*([0-9:.]+)\s*-\s*([0-9:.]+)\s*$", one)
            if not m:
                raise SystemExit(f"not a range: {one!r} (use start-end, e.g. 62-70.5 or 1:02-1:10.5)")
            a, b = seconds(m.group(1)), seconds(m.group(2))
            if b <= a:
                raise SystemExit(f"range {one!r} ends before it starts")
            out.append((a, b))
    out.sort()
    merged = []
    for a, b in out:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def syncs(items):
    """['62.4', '70.10=70.02'] -> [(62.4, None), (70.10, 70.02)]: (guide time, part time or None = find it)."""
    out = []
    for it in items or ():
        for one in str(it).split(","):
            one = one.strip()
            if not one:
                continue
            if "=" in one:
                g, p = one.split("=", 1)
                out.append((seconds(g), seconds(p)))
            else:
                out.append((seconds(one), None))
    return sorted(out, key=lambda x: x[0])


def protect_plan(o, rngs, ramp_s=0.3):
    """Zero the move inside each protected range; fade it out before and back in after (in the part's gaps,
    usually). Returns the new plan and a 0/1 mask of the protected frames (for the sample-exact splice)."""
    o = np.asarray(o, float).copy()
    n = len(o)
    mask = np.zeros(n, bool)
    R = max(1, int(ramp_s / FR_S))
    for a, b in rngs:
        i0, i1 = max(0, int(a / FR_S)), min(n, int(np.ceil(b / FR_S)))
        if i1 <= 0 or i0 >= n:
            continue
        mask[i0:i1] = True
        o[i0:i1] = 0.0
        r0 = max(0, i0 - R)
        if i0 > r0:
            o[r0:i0] *= np.linspace(1, 0, i0 - r0)
        r1 = min(n, i1 + R)
        if r1 > i1:
            o[i1:r1] *= np.linspace(0, 1, r1 - i1)
    return o, mask


def local_lag(env_guide, env_part, t, win_s=0.5, max_ms=150.0):
    """Frames the part is late (+) against the guide around time t, from their onset envelopes (10 ms frames).
    None when there is nothing to compare there."""
    W, M = int(win_s / FR_S), int(max_ms / 1000 / FR_S)
    c = int(t / FR_S)
    s0, s1 = max(0, c - W // 2), min(len(env_part), c + W // 2)
    x = env_part[s0:s1]
    y = env_guide[max(0, s0 - M):s1 + M]
    if len(x) < 4 or x.std() < 1e-6 or y.std() < 1e-6 or len(y) < len(x) + 2 * M:
        return None
    cc = np.correlate(y - y.mean(), x - x.mean(), mode="valid")
    k = int(np.argmax(cc))
    if k <= 1 or k >= len(cc) - 2:
        return None
    d = cc[k - 1] - 2 * cc[k] + cc[k + 1]
    frac = 0.5 * (cc[k - 1] - cc[k + 1]) / d if d != 0 else 0.0     # sub-frame: parabola through the peak
    return float(M - (k + frac))


def _shape(x, sr):
    """Loudness shape at 1 kHz: rectified, smoothed over 8 ms (no waveform ripple left, so the pitch can't fool it),
    slow level removed (80 ms), so syllable attacks dominate."""
    from scipy.ndimage import uniform_filter1d
    e = uniform_filter1d(np.abs(x).astype(np.float64), max(1, int(0.008 * sr)))
    e = e[(np.arange(int(len(e) * 1000 / sr)) * sr / 1000).astype(int)]      # 1 kHz (already smooth: no aliasing)
    e = np.log(np.maximum(e, 0) + 1e-4)
    return e - uniform_filter1d(e, 80)


def precise_lag(guide_y, part_y, sr, t, win_s=0.6, max_ms=150.0):
    """Seconds the part is late (+) against the guide around time t, to a fraction of a millisecond: their loudness
    shapes (pitch-independent, so a harmony works too) cross-correlated over +-win_s/2. None if either is silent."""
    mono = lambda y: (y.mean(1) if y.ndim > 1 else y)
    M = int(max_ms)                                   # 1 kHz: one step per ms
    i0, i1 = max(0, int((t - win_s / 2) * sr)), int((t + win_s / 2) * sr)
    j0, j1 = max(0, i0 - int(max_ms / 1000 * sr)), i1 + int(max_ms / 1000 * sr)
    g, p = mono(guide_y)[i0:i1], mono(part_y)[j0:j1]
    if len(g) < sr * 0.1 or np.abs(g).max() < 1e-4 or np.abs(p).max() < 1e-4:
        return None
    eg, ep = _shape(g, sr), _shape(p, sr)
    pre = (i0 - j0) * 1000 // int(sr)                 # where the guide window starts inside the part's
    c = np.correlate(ep - ep.mean(), eg - eg.mean(), mode="valid")
    lo, hi = max(0, pre - M), min(len(c), pre + M + 1)
    if hi - lo < 3:
        return None
    k = lo + int(np.argmax(c[lo:hi]))
    if k <= lo or k >= hi - 1:
        return None                                   # best at the edge of the search: not a real match
    d = c[k - 1] - 2 * c[k] + c[k + 1]
    frac = 0.5 * (c[k - 1] - c[k + 1]) / d if d != 0 else 0.0
    return (k + frac - pre) / 1000.0


def sync_plan(o, points, guide_y, part_y, sr, cap_frames, width_s=0.15):
    """Force the plan at each sync point: o there = how late the part is at that moment (measured, or given as a
    pair), blended in over +-width_s. Returns (plan, [(guide_t, set_ms or None)])."""
    o = np.asarray(o, float).copy()
    n = len(o)
    done = []
    k = np.arange(n)
    for g, p in points:
        lag_s = (p - g) if p is not None else precise_lag(guide_y, part_y, sr, g)
        if lag_s is None:
            done.append((g, None))
            continue
        lag = float(np.clip(lag_s / FR_S, -cap_frames, cap_frames))
        w = np.exp(-0.5 * ((k - g / FR_S) / (width_s / FR_S)) ** 2)
        w[w < 1e-3] = 0
        o = o * (1 - w) + lag * w
        done.append((g, round(lag * FR_S * 1000)))
    return o, done


def splice_protected(orig, out, mask, sr, fade_s=0.01):
    """Inside protected frames the output is the original audio sample for sample (10 ms crossfades outside)."""
    if not mask.any():
        return out
    from scipy.ndimage import uniform_filter1d
    hard = np.repeat(mask.astype(float), int(round(FR_S * sr)))[:len(orig)]
    hard = np.pad(hard, (0, max(0, len(orig) - len(hard))))
    m = np.maximum(hard, np.clip(uniform_filter1d(hard, max(1, int(2 * fade_s * sr)), mode="nearest") * 2, 0, 1))
    return out * (1 - m[:, None]) + orig * m[:, None]


def describe(name):
    p = PRESETS[name]
    keys = ", ".join(f"{k.replace('_', '-')} {v}" for k, v in p.items() if k != "desc")
    return f"{name}: {p['desc']} ({keys})"
