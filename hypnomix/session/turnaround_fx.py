#!/usr/bin/env python3
"""Fills engine preview: periodic turnarounds, glitches and fills on a loop, offline.

The reference for the Hypnomix Turnaround device (gen~ does the same live). One fill is planned for the
last few steps of every cycle (4 / 8 / 16 bars), from a seeded random pattern: repeats, rolls, reverse,
tape stop, half time, drop-outs, filter sweeps, gates, bit crush, echo, rearranged steps. Everything
ends exactly at the next downbeat, which is never touched. Constant tempo only.

Usage:
  hypnomix turnaround fx IN.wav --bpm 120 [--downbeat 0.0] [--cycle 4] [--where 8] [--level 1]
                         [--seed 1] [--chance 0.75] [--evolve 1] [--no-grow] [--beats-per-bar 4]
                         [--weights repeat=3,roll=2,crush=0 ...] [--no-keep-lows] [--mix 1]
                         [--humanise-ms 1.5] [--out OUT.wav] [--json PATTERNS.json]

Spec: docs/turnaround-design.md, section 1 (the RNG and the order of rnd() calls are part of it).
"""
import argparse, json, math, sys
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------- constants (spec: Effects table)
EFFECTS = {1: "repeat", 2: "roll", 3: "reverse", 4: "tapestop", 5: "halftime", 6: "drop",
           7: "filter", 8: "gate", 9: "crush", 10: "echo", 11: "rearrange"}
IDS = {v: k for k, v in EFFECTS.items()}
DEFAULT_WEIGHTS = {1: 3, 2: 2, 3: 2, 4: 1, 5: 1, 6: 2, 7: 2, 8: 1, 9: 0, 10: 1, 11: 2}
LENGTHS = (1, 2, 4, 8)          # spec: pattern step 3, candidate segment lengths (steps)
LENGTH_W = (1, 3, 3, 1)
FADE_MS = 3.0                   # spec: click safety, segment fade in/out
RESTART_MS = 2.0                # spec: click safety, repeat restart fade
MAXW = 32                       # spec: grow cap (steps)
MAXLEVEL = 3

_M = 2147483647
_A = 16807


class ParkMiller:
    """spec: Random numbers. s = s * 16807 mod 2147483647 (exact in doubles); rnd() = s / 2147483647."""
    def __init__(self, s):
        self.s = int(s)

    def rnd(self):
        self.s = (self.s * _A) % _M
        return self.s / _M


def seed_state(seed, fill_index, evolve):
    """spec: s0 = 1 + ((seed*7919 + epoch*104729) mod 2147483646); epoch = fill_index // evolve (0: never)."""
    epoch = fill_index // evolve if evolve >= 1 else 0
    return 1 + ((int(seed) * 7919 + epoch * 104729) % 2147483646)


def _weights(weights):
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        for k, v in (weights.items() if hasattr(weights, "items") else enumerate(weights, 1)):
            w[IDS[k] if isinstance(k, str) else int(k)] = float(v)
    return w


# ---------------------------------------------------------------- pattern generator (spec: section 1)
def pattern(seed, fill_index, W, level=1, weights=None, chance=0.75, evolve=1):
    """Segments of one fill, sorted by start (steps 0..W-1 relative to the window start).
    Returns a list of {start, length, effect, name, p}. The order of rnd() calls is part of the spec."""
    w = _weights(weights)
    on = [e for e in sorted(w) if w[e] > 0]
    r = ParkMiller(seed_state(seed, fill_index, evolve))
    for _ in range(3):
        r.rnd()                                            # warm up
    if not (r.rnd() < chance):                             # 1. active?
        return []
    k = 1 + int(math.floor(r.rnd() * level))               # 2. number of effect segments
    if not on:                                             # spec: (nothing enabled -> no fill)
        return []
    segs, pos, prev = [], W, None
    tot = float(sum(LENGTH_W))
    for _j in range(k):                                    # 3. build backwards from the window end
        if pos <= 0:
            break
        x = r.rnd()                                        # length
        c, length = 0.0, LENGTHS[-1]
        for cand, cw in zip(LENGTHS, LENGTH_W):
            c += cw / tot
            if x < c:
                length = cand
                break
        if _j == 0 and W >= 8:
            length = max(length, 2)
        length = min(length, pos)
        cands = [e for e in on if e != prev] or on         # effect, excluding the previous segment's
        t = r.rnd() * sum(w[e] for e in cands)
        c, eff = 0.0, cands[-1]
        for e in cands:
            c += w[e]
            if t < c:
                eff = e
                break
        p = r.rnd()                                        # param
        segs.append({"start": pos - length, "length": length, "effect": eff, "name": EFFECTS[eff], "p": p})
        pos -= length
        if r.rnd() < 0.5 - 0.15 * level:                   # gap
            pos -= 2 if r.rnd() < 0.5 else 4
            pos = max(pos, 0)
        prev = eff
    segs.sort(key=lambda s: s["start"])
    return segs


def fill_windows(n_bars, cycle=4, where=8, grow=True, beats_per_bar=4):
    """[(fill_index, first_step, W, level_bump)] in song steps, for every cycle that completes within n_bars.
    spec: grow: at every 2C bars the window doubles and level +1; at every 4C it doubles again (cap 32, level cap 3)."""
    bar_steps = 4 * beats_per_bar
    out = []
    for k in range(int(n_bars) // cycle):
        end_bar = (k + 1) * cycle
        W, bump = where, 0
        if grow:
            if end_bar % (4 * cycle) == 0:
                W, bump = where * 4, 2
            elif end_bar % (2 * cycle) == 0:
                W, bump = where * 2, 1
        W = min(W, MAXW)
        out.append((k, end_bar * bar_steps - W, W, bump))
    return out


# ---------------------------------------------------------------- DSP helpers
def _read(src, pos):
    """src[(n, ch)] at float positions pos (linear interpolation, clamped to the file)."""
    n = len(src)
    pos = np.clip(pos, 0, n - 1)
    i = np.floor(pos).astype(np.int64)
    f = (pos - i)[:, None]
    j = np.minimum(i + 1, n - 1)
    return src[i] * (1 - f) + src[j] * f


def _lowpass_150(x, sr):
    """spec: keep_lows: 2-pole Butterworth low-pass at 150 Hz. Run as a (truncated, 16384-tap) impulse
    response through an FFT, so a whole file is fast; the gen~ port runs the biquad itself (difference ~1e-9)."""
    w0 = 2 * math.pi * 150.0 / sr
    al = math.sin(w0) / (2 * (1 / math.sqrt(2)))
    b0 = (1 - math.cos(w0)) / 2; b1 = 1 - math.cos(w0); b2 = b0
    a0 = 1 + al; a1 = -2 * math.cos(w0); a2 = 1 - al
    b0, b1, b2, a1, a2 = b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0
    h = np.zeros(16384)
    x1 = x2 = y1 = y2 = 0.0
    for i in range(len(h)):
        xi = 1.0 if i == 0 else 0.0
        y = b0 * xi + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        h[i] = y
        x2, x1, y2, y1 = x1, xi, y1, y
    n = len(x)
    nfft = 1 << int(math.ceil(math.log2(n + len(h))))
    H = np.fft.rfft(h, nfft)
    out = np.empty_like(x)
    for c in range(x.shape[1]):
        out[:, c] = np.fft.irfft(np.fft.rfft(x[:, c], nfft) * H, nfft)[:n]
    return out


def _svf(x, sr, f0, f1, mode):
    """spec row 7 (filter): 2-pole (TPT) SVF, Q 0.9, cutoff sweeping exponentially f0 -> f1 over the segment."""
    L = len(x)
    t = np.arange(L) / max(L, 1)
    fc = np.minimum(f0 * (f1 / f0) ** t, 0.45 * sr)
    g = np.tan(math.pi * fc / sr)
    k = 1.0 / 0.9
    a1 = (1.0 / (1.0 + g * (g + k))).tolist()
    gl = g.tolist()
    out = np.empty_like(x)
    for c in range(x.shape[1]):
        ic1 = ic2 = 0.0
        xs = x[:, c].tolist()
        ys = [0.0] * L
        for i in range(L):
            a = a1[i]; gg = gl[i]
            v3 = xs[i] - ic2
            v1 = a * ic1 + gg * a * v3
            v2 = ic2 + gg * a * ic1 + gg * gg * a * v3
            ic1 = 2 * v1 - ic1
            ic2 = 2 * v2 - ic2
            ys[i] = v2 if mode == "lp" else xs[i] - k * v1 - v2
        out[:, c] = ys
    return out


def _fade_env(L, sr):
    """spec: click safety: 3 ms in from dry, 3 ms out to dry (inside the segment). Shape (L, 1)."""
    f = min(int(round(FADE_MS * 1e-3 * sr)), L // 2)
    e = np.ones(L)
    if f > 0:
        e[:f] = np.arange(f) / f
        e[L - f:] = (f - 1 - np.arange(f)) / f
    return e[:, None]


class _Ctx:
    def __init__(self, sr, bpm, bpb, p):
        self.sr = sr
        self.step = sr * 60.0 / bpm / 4.0          # samples per step (16th in 4/4)
        self.bar = int(round(self.step * 4 * bpb))
        self.p = p


# ---------------------------------------------------------------- effects: each returns wet (L, ch)
def _thirds(p):
    return min(2, int(p * 3))


def _repeat(hi, a, L, p, cx, rng2, roll):
    """spec rows 1 and 2 (repeat, roll). Blocks start at the segment start; every restart replays the input
    from the segment start. Restart jumps are shifted by humanise (second RNG stream), 2 ms fades at each jump."""
    sr, st = cx.sr, cx.step
    hum = cx.p["humanise_ms"]
    if roll:
        def size(b):                                        # 1/8 -> 1/16 at 1/2, -> 1/32 at 3/4 of the segment
            return max(1, int(round(st * (2 if b < L / 2 else 1 if b < L * 0.75 else 0.5))))
    else:
        s0 = max(1, int(round(st * (2, 1, 0.5)[_thirds(p)])))   # 1/8, 1/16, 1/32 note by p (thirds)
        size = lambda b: s0
    bounds, b = [0], 0
    while True:
        nb = b + size(b)
        if nb >= L:
            break
        if hum > 0:
            nb += int(round((rng2.rnd() * 2 - 1) * hum * 1e-3 * sr))
            nb = min(max(nb, b + 1), L - 1)
        bounds.append(nb)
        b = nb
    bounds.append(L)
    wet = np.zeros((L, hi.shape[1]))
    r = max(1, int(round(RESTART_MS * 1e-3 * sr)))
    for k in range(len(bounds) - 1):
        b0, b1 = bounds[k], bounds[k + 1]
        m = b1 - b0
        blk = hi[a:a + m].copy()
        if len(blk) < m:
            blk = np.vstack([blk, np.zeros((m - len(blk), hi.shape[1]))])
        env = np.ones(m)
        rr = min(r, m // 2)
        if rr > 0:
            if k > 0:
                env[:rr] = np.arange(rr) / rr
            if k < len(bounds) - 2:
                env[m - rr:] *= (rr - 1 - np.arange(rr)) / rr
        g = 1.0 if roll else 0.92 ** k
        wet[b0:b1] = blk * (env * g)[:, None]
    if roll:
        wet *= (0.8 + 0.2 * np.arange(L) / L)[:, None]      # gain rises 0.8 -> 1.0
    return wet


def _echo(hi, a, L, cx):
    """spec row 10: dry stays; the segment (faded 3 ms) feeds a 3/16 delay, feedback 0.45, LP 4 kHz on the wet.
    Returns (wet, length); the tail rings on past the window until it is below -60 dB or the file ends."""
    n, sr = len(hi), cx.sr
    d = max(1, int(round(3 * cx.step)))
    fb = 0.45
    tail = int(math.ceil(math.log(1e-3) / math.log(fb))) * d
    M = min(L + tail, n - a)
    u = np.zeros((M, hi.shape[1]))
    u[:L] = hi[a:a + L] * _fade_env(L, sr)
    y = np.zeros_like(u)
    for b in range(d, M, d):                                # y[n] = u[n-d] + fb*y[n-d], one block of d at a time
        m = min(d, M - b)
        y[b:b + m] = u[b - d:b - d + m] + fb * y[b - d:b - d + m]
    al = 1.0 - math.exp(-2 * math.pi * 4000.0 / sr)
    h = al * (1 - al) ** np.arange(64)
    for c in range(y.shape[1]):
        y[:, c] = np.convolve(y[:, c], h)[:M]
    return y, M


def _effect(eff, hi, a, L, p, cx, rng2):
    sr, st, bar = cx.sr, cx.step, cx.bar
    n = len(hi)
    t = np.arange(L)
    if eff == 1:
        return _repeat(hi, a, L, p, cx, rng2, False)                        # 1 repeat
    if eff == 2:
        return _repeat(hi, a, L, p, cx, rng2, True)                         # 2 roll
    if eff == 3:                                                            # 3 reverse: a - bar + (L - t)
        return hi[np.clip(a - bar + (L - t), 0, n - 1)]
    if eff == 4:                                                            # 4 tapestop: rate (1 - t/L)**1.5
        rate = (1 - t / L) ** 1.5
        pos = a + np.cumsum(rate) - rate
        return _read(hi, pos)
    if eff == 5:                                                            # 5 halftime: rate 0.5
        return _read(hi, a + 0.5 * t)
    if eff == 6:                                                            # 6 drop: gain 0 (p < .5: last half)
        wet = hi[a:a + L].copy()
        h = L // 2 if p < 0.5 else 0
        wet[h:] = 0.0
        f = min(int(round(FADE_MS * 1e-3 * sr)), h)         # spec: (click safety) the mid-segment drop ramps over 3 ms
        if f > 0:
            wet[h - f:h] *= (1 - (np.arange(f) + 1) / f)[:, None]
        return wet
    if eff == 7:                                                            # 7 filter
        seg = hi[a:a + L]
        return _svf(seg, sr, 18000.0, 400.0, "lp") if p < 0.5 else _svf(seg, sr, 30.0, 1500.0, "hp")
    if eff == 8:                                                            # 8 gate: on first half of each 1/16 (1/32)
        per = st if p < 0.5 else st / 2
        g = ((t % per) < per / 2).astype(float)
        w = max(1, int(round(0.002 * sr)))
        g = np.convolve(g, np.ones(w) / w, "same")                          # 2 ms ramps
        return hi[a:a + L] * g[:, None]
    if eff == 9:                                                            # 9 crush: hold 8th (16th) sample, 8 bit, 50 % wet
        hold = 8 if p < 0.5 else 16
        seg = hi[a:a + L]
        held = seg[(t // hold) * hold]
        return 0.5 * seg + 0.5 * np.round(held * 127.0) / 127.0
    if eff == 11:                                                           # 11 rearrange: a - bar + off*step + t
        off = (-4, -8, 4)[_thirds(p)]
        return hi[np.clip(a - bar + int(round(off * st)) + t, 0, n - 1)]
    raise ValueError(eff)


# ---------------------------------------------------------------- render
def _params(**kw):
    p = dict(cycle=4, where=8, level=1, seed=1, chance=0.75, evolve=1, grow=True, beats_per_bar=4,
             weights=None, keep_lows=True, mix=1.0, humanise_ms=1.5)
    bad = set(kw) - set(p)
    if bad:
        raise TypeError("unknown parameter: " + ", ".join(sorted(bad)))
    p.update(kw)
    return p


def _apply(x2, sr, bpm, downbeat_s, windows, p):
    n = len(x2)
    cx = _Ctx(sr, bpm, p["beats_per_bar"], p)
    db = downbeat_s * sr
    plans = []
    for fi, first, W, bump in windows:
        if int(round(db + (first + W) * cx.step)) > n:     # spec: a window that would run past the file is skipped
            continue
        segs = pattern(p["seed"], fi, W, min(MAXLEVEL, p["level"] + bump), p["weights"], p["chance"], p["evolve"])
        if segs:
            plans.append((fi, first, segs))
    out = x2.copy()
    if not plans:
        return out, []
    if p["keep_lows"]:
        lo = _lowpass_150(x2, sr)
        hi = x2 - lo
    else:
        hi = x2
    mix = p["mix"]
    for fi, first, segs in plans:
        rng2 = ParkMiller(seed_state(p["seed"], fi, p["evolve"]) + 1)      # spec: humanise stream seeded s0 + 1
        for s in segs:
            a = int(round(db + (first + s["start"]) * cx.step))
            L = int(round(db + (first + s["start"] + s["length"]) * cx.step)) - a
            if L < 2:
                continue
            if s["effect"] == 10:
                wet, M = _echo(hi, a, L, cx)
                out[a:a + M] += mix * wet                                  # tail rings on after the window
                continue
            wet = _effect(s["effect"], hi, a, L, s["p"], cx, rng2)
            dry = hi[a:a + L]
            out[a:a + L] += _fade_env(L, sr) * ((wet - dry) * mix)         # = lo + hi + e*(mixed - hi)
    return out, plans


def _shape(x):
    x = np.asarray(x, dtype=np.float64)
    return (x[:, None], True) if x.ndim == 1 else (x, False)


def render(x, sr, bpm, downbeat_s=0.0, **params):
    """Fills for the whole file. x: (n,) or (n, 2) float; returns the same shape and length."""
    p = _params(**params)
    x2, mono = _shape(x)
    bar = sr * 60.0 / bpm * p["beats_per_bar"]
    n_bars = int((len(x2) - downbeat_s * sr) // bar) if len(x2) > downbeat_s * sr else 0
    windows = fill_windows(n_bars, p["cycle"], p["where"], p["grow"], p["beats_per_bar"])
    y, _ = _apply(x2, sr, bpm, downbeat_s, windows, p)
    return y[:, 0] if mono else y


def render_window(x, sr, bpm, fill_index, first_step, W, level_bump=0, downbeat_s=0.0, **params):
    """One fill only (as given by fill_windows), the rest of the file untouched."""
    p = _params(**params)
    x2, mono = _shape(x)
    y, _ = _apply(x2, sr, bpm, downbeat_s, [(fill_index, first_step, W, level_bump)], p)
    return y[:, 0] if mono else y


def plan(n, sr, bpm, downbeat_s=0.0, **params):
    """The fills (window + segments) render() would make for a file of n samples."""
    p = _params(**params)
    bar = sr * 60.0 / bpm * p["beats_per_bar"]
    n_bars = int((n - downbeat_s * sr) // bar) if n > downbeat_s * sr else 0
    out = []
    for fi, first, W, bump in fill_windows(n_bars, p["cycle"], p["where"], p["grow"], p["beats_per_bar"]):
        segs = pattern(p["seed"], fi, W, min(MAXLEVEL, p["level"] + bump), p["weights"], p["chance"], p["evolve"])
        out.append({"fill_index": fi, "first_step": first, "W": W, "level": min(MAXLEVEL, p["level"] + bump), "segments": segs})
    return out


# ---------------------------------------------------------------- CLI
def main():
    import soundfile as sf
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] != "fx":
        print("hypnomix turnaround: unknown subcommand %r (try: fx)" % argv[0], file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(prog="hypnomix turnaround fx", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("infile")
    ap.add_argument("--bpm", type=float, required=True)
    ap.add_argument("--downbeat", type=float, default=0.0, help="seconds to the first downbeat")
    ap.add_argument("--cycle", type=int, default=4, choices=(4, 8, 16))
    ap.add_argument("--where", type=int, default=8, help="window in steps: 4, 8, 16 or 32")
    ap.add_argument("--level", type=int, default=1, choices=(1, 2, 3))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--chance", type=float, default=0.75)
    ap.add_argument("--evolve", type=int, default=1, help="new pattern every N fills; 0 = never")
    ap.add_argument("--no-grow", action="store_true")
    ap.add_argument("--beats-per-bar", type=int, default=4)
    ap.add_argument("--weights", default="", help="e.g. repeat=3,crush=1,echo=0 (0 = off)")
    ap.add_argument("--no-keep-lows", action="store_true")
    ap.add_argument("--mix", type=float, default=1.0)
    ap.add_argument("--humanise-ms", type=float, default=1.5)
    ap.add_argument("--out")
    ap.add_argument("--json")
    a = ap.parse_args(argv[1:])
    wts = {}
    for part in filter(None, a.weights.split(",")):
        k, _, v = part.partition("=")
        k = k.strip()
        if k not in IDS and not k.isdigit():
            ap.error("unknown effect %r (one of: %s)" % (k, ", ".join(IDS)))
        wts[k if k in IDS else int(k)] = float(v)
    x, sr = sf.read(a.infile, dtype="float64", always_2d=False)
    prm = dict(cycle=a.cycle, where=a.where, level=a.level, seed=a.seed, chance=a.chance, evolve=a.evolve,
               grow=not a.no_grow, beats_per_bar=a.beats_per_bar, weights=wts or None,
               keep_lows=not a.no_keep_lows, mix=a.mix, humanise_ms=a.humanise_ms)
    y = render(x, sr, a.bpm, a.downbeat, **prm)
    out = a.out or str(Path(a.infile).with_name(Path(a.infile).stem + " (turnaround).wav"))
    sf.write(out, y, sr, subtype="PCM_24" if sf.info(a.infile).subtype != "FLOAT" else "FLOAT")
    fills = plan(len(y), sr, a.bpm, a.downbeat, **prm)
    if a.json:
        Path(a.json).write_text(json.dumps(fills, indent=1))
    for f in fills:
        print("fill %d  steps %d..%d  %s" % (f["fill_index"], f["first_step"], f["first_step"] + f["W"],
              ", ".join("%s@%d+%d" % (s["name"], s["start"], s["length"]) for s in f["segments"]) or "(none)"))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
