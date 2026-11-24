#!/usr/bin/env python3
"""Split-band de-esser for ONE vocal file: turns down only the "s" band, only on the "s".

How it finds sibilants:
 - Learns where THIS voice's sibilance lives: averages the spectrum of the moments where 4-12 kHz
   outweighs 1-4 kHz and centres the de-ess band on that peak (default 5-10 kHz if none is found).
 - A sibilant is a short burst (10-400 ms) where that band is louder than the 1-4 kHz body of the
   voice AND loud relative to the vocal's own level (within 24 dB of its loud parts), so quiet room
   hiss and breaths are left alone.

How it fixes them:
 - Splits off the sibilant band (zero-phase band-pass) and turns down ONLY that band during each
   event: reduction = amount x how far the band dominates, capped at --max-db. The gain moves smoothly
   (3 ms attack with look-ahead, ~60 ms release), and everywhere else the audio is bit-identical.

Usage: hypnomix deess IN.wav [OUT.wav] [--amount 0.7] [--max-db 8] [--report] [--json OUT.json]
OUT defaults to hypnomix-out/deess/<name> (deess).wav. Never overwrites: refuses if OUT is IN or exists.
--report analyses only and writes nothing.
"""
import argparse, json, sys
from pathlib import Path
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfiltfilt, stft
from scipy.ndimage import uniform_filter1d

HOP_S = 0.002          # detector resolution
MIN_S, MAX_S = 0.010, 0.400
ATTACK_MS, RELEASE_MS = 3.0, 60.0


def mmss(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _mono(y):
    return y if y.ndim == 1 else y.mean(axis=1)


def _bp(x, sr, lo, hi, order=4):
    hi = min(hi, sr * 0.45)
    return sosfiltfilt(butter(order, [lo, hi], "bandpass", fs=sr, output="sos"), x)


def _env_db(x, sr, hop):
    e = uniform_filter1d(x ** 2, max(1, int(0.005 * sr)))
    return 10 * np.log10(np.maximum(e[::hop], 0) + 1e-20)


def find_band(m, sr):
    """Centre the de-ess band on where this voice's sibilant energy peaks."""
    f, _, Z = stft(m, sr, nperseg=1024)
    P = np.abs(Z) ** 2
    hi = P[(f >= 4000) & (f < min(12000, sr * 0.45))].sum(0)
    lo = P[(f >= 1000) & (f < 4000)].sum(0)
    tot = P.sum(0)
    sel = (hi > lo) & (tot > np.percentile(tot, 50))
    if sel.sum() < 3:
        return 5000.0, min(10000.0, sr * 0.45)
    band = (f >= 4000) & (f < min(12000, sr * 0.45))
    spec = P[:, sel].mean(1)
    fp = float(f[band][np.argmax(spec[band])])
    lo_hz = float(np.clip(fp / 1.5, 4000, 7000))
    hi_hz = float(min(max(fp * 1.5, lo_hz * 1.6), 12000, sr * 0.45))
    return lo_hz, hi_hz


def analyse(y, sr):
    """Sibilant events: list of {t, dur, band_hz: [lo, hi], over_db} (over_db = band minus voice body)."""
    m = _mono(np.asarray(y, dtype=np.float64))
    if len(m) < sr * 0.05 or not np.any(m):
        return []
    lo_hz, hi_hz = find_band(m, sr)
    hop = max(1, int(HOP_S * sr))
    hi_db = _env_db(_bp(m, sr, lo_hz, hi_hz), sr, hop)
    body_db = _env_db(_bp(m, sr, 1000, 4000), sr, hop)
    full_db = _env_db(m, sr, hop)
    live = full_db > -90
    if not live.any():
        return []
    voice = np.percentile(full_db[live], 95)
    cand = (hi_db - body_db > 0) & (hi_db > voice - 24)
    # close tiny gaps (< 20 ms)
    gap = int(0.02 / HOP_S)
    d = np.diff(np.concatenate([[0], cand.astype(int), [0]]))
    runs = list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))
    merged = []
    for a, b in runs:
        if merged and a - merged[-1][1] <= gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    ev = []
    for a, b in merged:
        dur = (b - a) * hop / sr
        if MIN_S <= dur <= MAX_S:
            over = float(np.max(hi_db[a:b] - body_db[a:b]))
            ev.append({"t": round(float(a * hop / sr), 4), "dur": round(float(dur), 4),
                       "band_hz": [round(lo_hz), round(hi_hz)], "over_db": round(over, 1)})
    return ev


def reduction_db(e, amount, max_db):
    return float(min(max_db, amount * max(e["over_db"], 0)))


def gain_curve(n, sr, events, amount, max_db):
    """Per-sample gain (linear) for the high band: 1.0 exactly outside events and their release tails."""
    step = max(1, int(0.001 * sr))                        # 1 ms control rate
    k = n // step + 2
    tgt = np.zeros(k)
    la = int(np.ceil(ATTACK_MS))                          # look-ahead so the "s" onset is caught
    for e in events:
        a = max(0, int(e["t"] * 1000) - la); b = min(k, int((e["t"] + e["dur"]) * 1000) + 1)
        tgt[a:b] = np.minimum(tgt[a:b], -reduction_db(e, amount, max_db))
    up, dn = 1 - np.exp(-1 / ATTACK_MS), 1 - np.exp(-1 / RELEASE_MS)
    g = np.empty(k); cur = 0.0
    for i, t in enumerate(tgt):
        cur += (dn if t > cur else up) * (t - cur)          # going down = attack, coming back = release
        if t == 0 and cur > -0.001:
            cur = 0.0
        g[i] = cur
    gs = np.interp(np.arange(n), np.arange(k) * step, g)
    lin = 10 ** (gs / 20)
    lin[gs == 0] = 1.0
    return lin


def process(y, sr, events, amount=0.7, max_db=8.0):
    """Turn down only the sibilant band during `events`; untouched samples stay bit-identical."""
    y = np.asarray(y, dtype=np.float64)
    if not events or amount <= 0 or max_db <= 0:
        return y.copy()
    lo_hz, hi_hz = events[0]["band_hz"]
    g = gain_curve(len(y), sr, events, amount, max_db)
    idx = np.flatnonzero(g < 1.0)
    out = y.copy()
    if not len(idx):
        return out
    hp = _bp(y, sr, lo_hz, hi_hz) if y.ndim == 1 else np.stack(
        [_bp(y[:, c], sr, lo_hz, hi_hz) for c in range(y.shape[1])], axis=1)
    gg = g[idx] if y.ndim == 1 else g[idx][:, None]
    out[idx] = y[idx] + hp[idx] * (gg - 1.0)
    return out


def summary(events, amount, max_db, name):
    red = [reduction_db(e, amount, max_db) for e in events]
    lines = [f"deess: {name}"]
    if not events:
        lines.append("  no sibilant bursts found - nothing to do.")
        return lines, red
    lo, hi = events[0]["band_hz"]
    lines.append(f"  {len(events)} sibilants, band {lo}-{hi} Hz (learned from this voice)")
    lines.append(f"  reduction: average {np.mean(red):.1f} dB, max {max(red):.1f} dB (cap {max_db:g} dB)")
    worst = sorted(range(len(events)), key=lambda i: -events[i]["over_db"])[:5]
    lines.append("  worst:")
    for i in worst:
        e = events[i]
        lines.append(f"    {mmss(e['t'])}  ({e['t']:.2f}s, {e['dur'] * 1000:.0f} ms)  band {e['over_db']:+.1f} dB over the voice -> -{red[i]:.1f} dB")
    lines.append("  what to listen for: 's', 'sh', 't' should sound softer but still clear; if they turn into"
                 " a lisp ('th'), lower --amount or --max-db; if they still sting, raise --amount.")
    return lines, red


def finding(events, red, name):
    if not events:
        return []
    worst = max(events, key=lambda e: e["over_db"])
    sev = "medium" if (len(events) >= 10 or max(red) >= 6) else "low"
    return [{"id": "deess-1", "kind": "sibilance", "severity": sev, "track": name, "where": mmss(worst["t"]),
             "problem": f"{len(events)} harsh sibilants (worst at {mmss(worst['t'])}, band {worst['over_db']:+.1f} dB over the voice)",
             "fix": f"split-band de-ess {events[0]['band_hz'][0]}-{events[0]['band_hz'][1]} Hz, average -{np.mean(red):.1f} dB on the 's' only"}]


def main():
    ap = argparse.ArgumentParser(prog="hypnomix deess", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inp"); ap.add_argument("out", nargs="?")
    ap.add_argument("--amount", type=float, default=0.7, help="0-1, how hard to de-ess (default 0.7)")
    ap.add_argument("--max-db", type=float, default=8.0, help="most the band is ever turned down (default 8)")
    ap.add_argument("--report", action="store_true", help="analyse only, write nothing")
    ap.add_argument("--json", help="write findings + events to this file")
    a = ap.parse_args()
    amount = float(np.clip(a.amount, 0, 1))
    inp = Path(a.inp)
    y, sr = sf.read(str(inp), always_2d=True, dtype="float64")
    events = analyse(y, sr)
    lines, red = summary(events, amount, a.max_db, inp.name)
    print("\n".join(lines))
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps({"tool": "deess", "file": str(inp), "findings": finding(events, red, inp.name),
                                            "events": events}, indent=2))
    if a.report:
        return
    from hypnomix.core.paths import out_at
    dest = Path(a.out) if a.out else out_at(None, "deess") / f"{inp.stem} (deess).wav"
    if dest.resolve() == inp.resolve():
        sys.exit("deess: refusing to overwrite the input file")
    if dest.exists():
        sys.exit(f"deess: {dest} already exists - refusing to overwrite")
    dest.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dest), process(y, sr, events, amount, a.max_db).astype(np.float32), sr, subtype="FLOAT")
    print(dest)


if __name__ == "__main__":
    main()
