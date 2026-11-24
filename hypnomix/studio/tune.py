#!/usr/bin/env python3
"""Natural pitch correction for vocal takes (note-by-note, like a graphical pitch editor's natural mode).

Reads a monophonic vocal file, finds every sung note, and moves each note's centre toward the right
pitch while leaving everything inside the note (vibrato, scoops, slides, breath) as it was sung.

  target   the nearest semitone in the SONG's tuning (measured from the notes, not assumed A=440).
           Only notes sung near a quarter-tone (ambiguous) use the key, or with --guide the lead
           vocal (the more consonant choice against what the lead sings at that moment).
           Harmonies come out matched to each other because every part is locked to the same grid.
  amount   how far to pull each note (--amount 0.8 = 80% of the way; 1.0 = fully in tune)
  leave    notes already within --tolerance cents are untouched; a note sung halfway between two
           notes that neither the key nor the guide can settle is flagged, not changed
  drift    optional (--drift 0.5): also flatten slow pitch drift inside long notes; vibrato stays

The shift is done by Rubber Band (R3 engine, formants preserved so the voice keeps its character),
then the output is aligned back to the input sample-for-sample so it drops straight into Live.

Usage:
  hypnomix tune IN.wav OUT.wav --ref MIX.wav [--key "A minor"] [--amount 0.8] [--guide LEAD.wav]
  hypnomix tune IN.wav --report-only --ref MIX.wav     (just measure; the report goes to ./reports/tune)
Writes OUT.wav plus OUT.notes.txt (every note: time, sung, target, cents before/after) and OUT.png.
Needs Rubber Band 3+ (`brew install rubberband`).
"""
import argparse, math, subprocess, sys, tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
import librosa

SR_A = 22050          # analysis sample rate
HOP = 220             # ~10 ms analysis hop at 22.05 kHz
FRAME = 1024
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR = [0, 2, 4, 5, 7, 9, 11]
MINOR = [0, 2, 3, 5, 7, 8, 10]
# Krumhansl-Kessler key profiles
KK_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
CONSONANT = {0, 3, 4, 5, 7, 8, 9}  # semitone intervals that sound settled against the lead


# ---------------------------------------------------------------- analysis
def active_regions(y, sr, floor_db=-50.0, pad=0.3):
    """Stretches where someone is singing (so silence isn't pitch-tracked)."""
    blk = int(sr * 0.05)
    n = len(y) // blk
    rms = np.sqrt((y[: n * blk] ** 2).reshape(n, blk).mean(1) + 1e-12)
    on = 20 * np.log10(rms) > floor_db
    regions, i = [], 0
    while i < n:
        if not on[i]:
            i += 1
            continue
        j = i
        while j < n and on[j]:
            j += 1
        regions.append([max(0.0, i * 0.05 - pad), min(len(y) / sr, j * 0.05 + pad)])
        i = j
    merged = []
    for a, b in regions:
        if merged and a - merged[-1][1] < 0.5:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return merged


def track_pitch(y, sr):
    """f0 in MIDI (float, NaN where unvoiced) on a 10 ms grid over the whole file."""
    ya = librosa.resample(y, orig_sr=sr, target_sr=SR_A) if sr != SR_A else y
    n_frames = 1 + len(ya) // HOP
    midi = np.full(n_frames, np.nan)
    for a, b in active_regions(y, sr):
        i0, i1 = int(a * SR_A), int(b * SR_A)
        seg = ya[i0:i1]
        if len(seg) < FRAME * 2:
            continue
        # pYIN (coarse, 10-cent bins) decides voicing and octave; YIN gives the exact pitch
        f0, voiced, prob = librosa.pyin(seg, fmin=65, fmax=1100, sr=SR_A, frame_length=FRAME,
                                        hop_length=HOP, center=True)
        fine = librosa.yin(seg, fmin=65, fmax=1100, sr=SR_A, frame_length=FRAME, hop_length=HOP, center=True)
        coarse_m = librosa.hz_to_midi(np.nan_to_num(f0, nan=1.0))
        fine_m = librosa.hz_to_midi(np.maximum(fine[: len(f0)], 1.0))
        best = np.where(np.abs(fine_m - coarse_m) < 0.5, fine_m, coarse_m)
        m = np.where(voiced & (prob > 0.3), best, np.nan)
        k0 = i0 // HOP
        k1 = min(n_frames, k0 + len(m))
        midi[k0:k1] = m[: k1 - k0]
    return midi


def frame_time(k):
    return k * HOP / SR_A


def segment_notes(midi, min_s=0.12, split=0.7):
    """Split voiced stretches into notes. A new note starts only when the (smoothed) pitch moves more
    than `split` semitones from the current note and stays there for min_s, so vibrato and scoops
    that cross a semitone boundary don't chop a note up."""
    notes = []
    voiced = ~np.isnan(midi)
    k, n = 0, len(midi)
    min_k = max(2, int(min_s / (HOP / SR_A)))
    while k < n:
        if not voiced[k]:
            k += 1
            continue
        j = k
        while j < n and voiced[j]:
            j += 1
        run = midi[k:j]
        if len(run) >= min_k:
            sm = _median(run, 11)
            starts = [0]
            ref = float(np.median(sm[:min_k]))
            i = min_k
            while i < len(sm):
                if abs(sm[i] - ref) > split:
                    win = sm[i:i + min_k]
                    if len(win) == min_k and np.all(np.abs(win - ref) > split * 0.8):
                        starts.append(i)
                        ref = float(np.median(win))
                        i += min_k
                        continue
                # follow slow movement of the current note
                ref = 0.98 * ref + 0.02 * sm[i]
                i += 1
            starts.append(len(sm))
            for a, b in zip(starts[:-1], starts[1:]):
                if b - a >= min_k:
                    notes.append(dict(k0=k + a, k1=k + b))
        k = j
    for nt in notes:
        body = midi[nt["k0"]:nt["k1"]]
        L = len(body)
        core = body[int(L * 0.2): max(int(L * 0.2) + 1, int(L * 0.85))]  # skip the scoop in and the fall off
        nt["centre"] = float(np.nanmedian(core))
        nt["t0"], nt["t1"] = frame_time(nt["k0"]), frame_time(nt["k1"])
    return notes


def _median(x, w):
    from scipy.ndimage import median_filter
    return median_filter(x, size=w, mode="nearest")


def estimate_tuning(notes):
    """Song tuning offset in cents from A=440, from where the sung notes cluster."""
    if not notes:
        return 0.0
    dev = np.array([(n["centre"] - round(n["centre"])) for n in notes])
    w = np.array([n["t1"] - n["t0"] for n in notes])
    # circular mean so +0.49 and -0.49 average correctly
    ang = 2 * np.pi * dev
    mean = math.atan2((np.sin(ang) * w).sum(), (np.cos(ang) * w).sum()) / (2 * np.pi)
    return float(mean * 100)


def estimate_key(notes, tuning_c):
    hist = np.zeros(12)
    for n in notes:
        pc = int(round(n["centre"] - tuning_c / 100)) % 12
        hist[pc] += n["t1"] - n["t0"]
    best = None
    for root in range(12):
        for mode, prof in (("major", KK_MAJ), ("minor", KK_MIN)):
            r = np.corrcoef(hist, np.roll(prof, root))[0, 1]
            if best is None or r > best[0]:
                best = (r, root, mode)
    return best[1], best[2], best[0]


def from_reference(path):
    """Tuning (cents from A=440) and key from the song's mix or instrumental."""
    y, sr = librosa.load(path, sr=SR_A, mono=True)
    tuning_c = float(librosa.estimate_tuning(y=y, sr=sr, resolution=0.01) * 100)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, tuning=tuning_c / 100, hop_length=2048)
    hist = chroma.sum(1)
    best = None
    for root in range(12):
        for mode, prof in (("major", KK_MAJ), ("minor", KK_MIN)):
            r = np.corrcoef(hist, np.roll(prof, root))[0, 1]
            if best is None or r > best[0]:
                best = (r, root, mode)
    return tuning_c, (best[1], best[2]), best[0]


def parse_key(s):
    parts = s.replace("♯", "#").replace("♭", "b").split()
    name = parts[0].capitalize()
    flats = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
    name = flats.get(name, name)
    if name not in NOTE_NAMES:
        sys.exit(f"unknown key {s!r}; use e.g. 'A minor' or 'Eb major'")
    mode = parts[1].lower() if len(parts) > 1 else "major"
    if mode not in ("major", "minor"):
        sys.exit("key mode must be major or minor")
    return NOTE_NAMES.index(name), mode


def note_name(m):
    m = int(round(m))
    return f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"


# ---------------------------------------------------------------- targets
def choose_targets(notes, tuning_c, key, guide_midi, a):
    root, mode = key
    scale = {(root + s) % 12 for s in (MAJOR if mode == "major" else MINOR)}
    off = tuning_c / 100
    for n in notes:
        c = n["centre"] - off                     # in a 440-based grid
        lo, hi = math.floor(c), math.ceil(c)
        frac = c - lo
        if lo == hi:
            cand = [lo]
        elif 0.4 <= frac <= 0.6:                  # near a quarter-tone: genuinely ambiguous
            cand = [lo, hi]
        else:
            cand = [round(c)]
        pick = cand[0]
        why = "nearest"
        if len(cand) == 2:
            g = None
            if guide_midi is not None:
                seg = guide_midi[n["k0"]:n["k1"]]
                if np.isfinite(seg).sum() > 3:
                    g = float(np.nanmedian(seg)) - off
            if g is not None:
                good = [x for x in cand if int(round(abs(x - g))) % 12 in CONSONANT]
                if len(good) == 1:
                    pick, why = good[0], "fits the lead"
            if why == "nearest":
                inscale = [x for x in cand if x % 12 in scale]
                if len(inscale) == 1:
                    pick, why = inscale[0], "in key"
                else:
                    pick, why = round(c), "nearest"
        n["target"] = pick + off
        n["why"] = why
        n["cents"] = (n["centre"] - n["target"]) * 100
        n["out_of_key"] = (pick % 12) not in scale
        if abs(n["cents"]) < a.tolerance:
            n["action"] = "ok"
        elif (len(cand) == 2 and why == "nearest") or abs(n["cents"]) > a.max:
            n["action"] = "flag"   # halfway between two notes and nothing says which was meant
        else:
            n["action"] = "fix"
        n["shift"] = -n["cents"] / 100 * a.amount if n["action"] == "fix" else 0.0
    return notes


# ---------------------------------------------------------------- shift curve + render
def shift_curve(midi, notes, a, ramp_s=0.03):
    """Semitone shift per analysis frame: constant inside a note, ramped between notes."""
    n = len(midi)
    curve = np.full(n, np.nan)
    for nt in notes:
        curve[nt["k0"]:nt["k1"]] = nt["shift"]
        if a.drift > 0 and nt["action"] == "fix" and nt["t1"] - nt["t0"] > 0.4:
            body = midi[nt["k0"]:nt["k1"]]
            slow = _median(np.nan_to_num(body, nan=nt["centre"]), int(0.3 / (HOP / SR_A)) | 1)
            curve[nt["k0"]:nt["k1"]] += -(slow - nt["centre"]) * a.drift
    # fill gaps by linear interpolation (unvoiced bits glide from one correction to the next)
    idx = np.arange(n)
    have = np.isfinite(curve)
    if not have.any():
        return np.zeros(n)
    curve = np.interp(idx, idx[have], curve[have])
    # soften steps at note edges
    w = max(1, int(ramp_s / (HOP / SR_A)))
    kernel = np.ones(w) / w
    return np.convolve(np.pad(curve, (w // 2, w - 1 - w // 2), mode="edge"), kernel, mode="valid")


def render(in_path, out_path, curve, sr, n_samples, channels):
    """Shift each sung phrase separately (Rubber Band's pitch-map mode drifts over long files),
    line each phrase up with the original sample-for-sample, and splice it back in."""
    from concurrent.futures import ThreadPoolExecutor
    src, _ = sf.read(str(in_path), dtype="float32", always_2d=True)
    mono = src.mean(1)
    peak = float(np.abs(src).max()) or 1.0
    scale = 0.9 / peak                      # Rubber Band writes fixed-point: keep float overs intact
    out = src.copy()
    regions = active_regions(mono, sr, pad=0.4)
    work = []
    for a, b in regions:
        i0, i1 = int(a * sr), min(len(src), int(b * sr))
        k0, k1 = int(a * SR_A / HOP), min(len(curve), int(b * SR_A / HOP) + 1)
        seg_curve = curve[k0:k1]
        if not len(seg_curve) or np.max(np.abs(seg_curve)) < 1e-4:
            continue                        # nothing to change in this phrase
        work.append((i0, i1, k0, seg_curve))

    def one(job):
        i0, i1, k0, seg_curve = job
        with tempfile.TemporaryDirectory() as td:
            seg_in, seg_out, pm = Path(td) / "in.wav", Path(td) / "out.wav", Path(td) / "pm.txt"
            sf.write(str(seg_in), src[i0:i1] * scale, sr, subtype="FLOAT")
            frames = ((k0 + np.arange(len(seg_curve))) * HOP / SR_A * sr).astype(int) - i0
            with open(pm, "w") as f:
                for fr, sh in zip(frames, seg_curve):
                    if fr >= 0:
                        f.write(f"{fr} {sh:.5f}\n")
            r = subprocess.run(["rubberband", "-3", "-F", "-q", "--pitchmap", str(pm), str(seg_in), str(seg_out)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(r.stderr[-300:])
            y, _ = sf.read(str(seg_out), dtype="float32", always_2d=True)
        return i0, i1, y / scale, lag_env(src[i0:i1].mean(1), y.mean(1) / scale, sr)

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(one, work))
    # Rubber Band's latency is the same for every phrase: one robust value for all of them
    lags = [lag for *_, lag in results]
    latency = int(round(np.median(lags))) if lags else 0
    for i0, i1, y_raw, _ in results:
        n = i1 - i0
        idx = np.arange(n) + latency
        ok = (idx >= 0) & (idx < len(y_raw))
        y = np.zeros((n, y_raw.shape[1]), np.float32)
        y[ok] = y_raw[idx[ok]]
        if n > 0:
            fade = min(int(0.02 * sr), n // 4)
            w = np.ones(n, np.float32)
            w[:fade] = np.linspace(0, 1, fade)
            w[n - fade:] = np.linspace(1, 0, fade)
            out[i0:i1] = out[i0:i1] * (1 - w[:, None]) + y[:n] * w[:, None]
    info = sf.info(str(in_path))
    sf.write(str(out_path), out if channels > 1 else out[:, 0], sr, subtype=info.subtype)
    spread = float(np.median([abs(l - latency) for l in lags])) if lags else 0.0
    return (latency, spread, len(lags)), out


def envelope(x, sr, smooth_s=0.002):
    """Loudness shape over time: unchanged by pitch shifting, so safe to align on."""
    from scipy.ndimage import uniform_filter1d
    e = uniform_filter1d(np.abs(x), max(1, int(smooth_s * sr)))
    return e - uniform_filter1d(e, int(0.05 * sr))     # keep the syllable shapes, drop slow level


def lag_env(ref, y, sr, max_s=0.25):
    """Samples by which y is late against ref, from envelope cross-correlation."""
    from scipy.signal import correlate
    er, ey = envelope(ref, sr), envelope(y, sr)
    m = int(max_s * sr)
    ey = np.pad(ey, (m, m))
    if len(er) < 256 or np.abs(er).max() < 1e-6:
        return 0.0
    cc = correlate(ey, er, mode="valid", method="fft")
    return float(int(np.argmax(cc)) - m)


# ---------------------------------------------------------------- report
def verify(out_mono, sr, notes):
    midi2 = track_pitch(out_mono, sr)
    for nt in notes:
        body = midi2[nt["k0"]:nt["k1"]]
        L = len(body)
        core = body[int(L * 0.2): max(int(L * 0.2) + 1, int(L * 0.85))]
        nt["after"] = float((np.nanmedian(core) - nt["target"]) * 100) if np.isfinite(core).sum() else float("nan")
    return midi2


def summarise(notes, key="cents"):
    v = np.array([abs(n[key]) for n in notes if np.isfinite(n.get(key, np.nan))])
    if not len(v):
        return "no notes"
    return f"median {np.median(v):.0f} cents off, {100 * (v <= 15).mean():.0f}% within ±15 cents"


def write_report(path, notes, tuning_c, key, keysrc, a, lag=None):
    lines = [f"tuning: A4 = {440 * 2 ** (tuning_c / 1200):.1f} Hz ({tuning_c:+.0f} cents)",
             f"key: {NOTE_NAMES[key[0]]} {key[1]} ({keysrc})",
             f"amount {a.amount:g}, tolerance {a.tolerance:g} cents, max {a.max:g} cents, drift {a.drift:g}",
             f"before: {summarise(notes)}"]
    if any("after" in n for n in notes):
        lines.append(f"after:  {summarise(notes, 'after')}")
    if lag is not None:
        lines.append(f"timing: {lag}")
    lines.append("")
    lines.append(f"{'time':>8}  {'len':>5}  {'sung':>5} -> {'target':<6} {'cents':>6}  {'after':>6}  action")
    for n in notes:
        aft = f"{n['after']:+6.0f}" if np.isfinite(n.get("after", np.nan)) else "     -"
        why = "" if n["why"] == "nearest" else f" ({n['why']})"
        act = {"ok": "ok", "fix": f"moved {n['shift'] * 100:+.0f}",
               "flag": "FLAG: between two notes, left alone"}[n["action"]]
        if n.get("out_of_key"):
            act += " [out of key]"
        lines.append(f"{_mmss(n['t0']):>8}  {n['t1'] - n['t0']:5.2f}  {note_name(n['centre']):>5} -> "
                     f"{note_name(n['target']):<6} {n['cents']:+6.0f}  {aft}  {act}{why}")
    Path(path).write_text("\n".join(lines) + "\n")
    return lines[:6]


def write_json(path, a, notes, tuning_c, key, keysrc):
    import json
    cents = np.array([abs(n["cents"]) for n in notes])
    med = float(np.median(cents)) if len(cents) else 0.0
    within = float((cents <= 15).mean() * 100) if len(cents) else 100.0
    nfix = sum(n["action"] == "fix" for n in notes)
    flags = [n for n in notes if n["action"] == "flag"]
    sev = "high" if med >= 25 else "medium" if med >= 15 else "low"
    summary = dict(
        id="tune-" + Path(a.input).stem, tool="tune", kind="pitch", severity=sev, track=Path(a.input).stem,
        where="whole take", problem=f"median {med:.0f} cents off, {within:.0f}% of notes within ±15 cents",
        fix=f"tune {nfix} notes ({a.amount:.0%} of the way), {len(flags)} ambiguous notes flagged for your ear",
        applies="audio", input=str(a.input))
    Path(path).write_text(json.dumps({
        "tool": "tune", "input": str(a.input), "tuning_cents": round(tuning_c, 1),
        "key": f"{NOTE_NAMES[key[0]]} {key[1]}", "key_source": keysrc, "findings": [summary],
        "flagged": [dict(time=_mmss(n["t0"]), sung=note_name(n["centre"]), cents=round(n["cents"])) for n in flags],
    }, indent=1))


def _mmss(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"


def plot(path, midi, midi2, notes, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    voiced = [n for n in notes]
    if not voiced:
        return
    # show the stretch with the most corrected notes, up to 30 s
    fixes = [n for n in notes if n["action"] == "fix"] or notes
    t_mid = np.median([n["t0"] for n in fixes])
    t0, t1 = max(0, t_mid - 15), t_mid + 15
    t = np.arange(len(midi)) * HOP / SR_A
    sel = (t >= t0) & (t <= t1)
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(t[sel], midi[sel], color="#b0b0b0", lw=1.2, label="sung")
    if midi2 is not None:
        t2 = np.arange(len(midi2)) * HOP / SR_A
        s2 = (t2 >= t0) & (t2 <= t1)
        ax.plot(t2[s2], midi2[s2], color="#d0602a", lw=1.2, label="corrected")
    for n in notes:
        if n["t1"] < t0 or n["t0"] > t1:
            continue
        ax.hlines(n["target"], n["t0"], n["t1"], color="#2a6fd0", lw=2, alpha=0.6)
        if n["action"] == "flag":
            ax.text(n["t0"], n["centre"] + 0.4, "flag", color="red", fontsize=8)
    lo = np.nanmin(midi[sel]) if np.isfinite(midi[sel]).any() else 50
    hi = np.nanmax(midi[sel]) if np.isfinite(midi[sel]).any() else 80
    ticks = range(int(lo) - 1, int(hi) + 2)
    ax.set_yticks(list(ticks))
    ax.set_yticklabels([note_name(m) for m in ticks], fontsize=7)
    ax.grid(axis="y", alpha=0.25)
    ax.set_xlabel("seconds")
    ax.set_title(f"{title}: blue = target note, grey = sung, orange = corrected")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(prog="hypnomix tune", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output", nargs="?")
    ap.add_argument("--report-only", action="store_true", help="measure and report; write no audio")
    ap.add_argument("--key", help='song key, e.g. "A minor" (default: estimated from the notes)')
    ap.add_argument("--guide", help="lead vocal file: settles ambiguous harmony notes toward a consonant interval")
    ap.add_argument("--amount", type=float, default=0.8, help="how far to pull each note, 0-1 (default 0.8)")
    ap.add_argument("--tolerance", type=float, default=10.0, help="leave notes within this many cents (10)")
    ap.add_argument("--max", type=float, default=60.0, help="never move a note more than this many cents (60)")
    ap.add_argument("--drift", type=float, default=0.0, help="also flatten slow drift inside notes, 0-1 (0)")
    ap.add_argument("--tuning", type=float, help="song tuning in cents from A=440 (default: measured)")
    ap.add_argument("--ref", help="the song's mix or instrumental: measure tuning and key from it (recommended)")
    ap.add_argument("--json", metavar="OUT.json", help="also write a summary + the notes as JSON")
    a = ap.parse_args()
    if not a.report_only and not a.output:
        sys.exit("give an OUT.wav, or --report-only")
    if a.output and Path(a.output).resolve() == Path(a.input).resolve():
        sys.exit("refusing to overwrite the input; give a new file name")
    if not 0 < a.amount <= 1:
        sys.exit("--amount must be between 0 and 1")

    y2, sr = sf.read(a.input, dtype="float32", always_2d=True)
    y = y2.mean(1)
    print(f"{Path(a.input).name}: {len(y) / sr:.1f} s, tracking pitch…")
    midi = track_pitch(y, sr)
    notes = segment_notes(midi)
    if not notes:
        sys.exit("no sung notes found (is this a monophonic vocal?)")
    ref_tuning = ref_key = None
    if a.ref:
        print("measuring tuning and key from the reference…")
        ref_tuning, ref_key, ref_fit = from_reference(a.ref)
    if a.tuning is not None:
        tuning_c = a.tuning
    elif ref_tuning is not None:
        tuning_c = ref_tuning
    else:
        tuning_c = estimate_tuning(notes)
        print("note: tuning measured from the singer; --ref MIX.wav is more reliable")
    if a.key:
        key, keysrc = parse_key(a.key), "given"
    elif ref_key is not None:
        key, keysrc = ref_key, f"from the reference, fit {ref_fit:.2f}; confirm with --key"
    else:
        r, m, conf = estimate_key(notes, tuning_c)
        key, keysrc = (r, m), f"estimated from the vocal, fit {conf:.2f}; confirm with --key"
    guide = None
    if a.guide:
        g, gsr = sf.read(a.guide, dtype="float32", always_2d=True)
        if gsr != sr:
            sys.exit("the guide must have the same sample rate as the input")
        print("tracking the guide…")
        guide = track_pitch(g.mean(1), gsr)
    choose_targets(notes, tuning_c, key, guide, a)

    if a.output:
        out_path = Path(a.output)
        report_path = Path(str(out_path.with_suffix("")) + ".notes.txt")
    else:  # report-only: never write next to the source take
        Path("reports/tune").mkdir(parents=True, exist_ok=True)
        out_path = Path("reports/tune") / Path(a.input).stem
        report_path = Path(str(out_path) + ".notes.txt")
    if a.json:
        write_json(a.json, a, notes, tuning_c, key, keysrc)
    if a.report_only:
        head = write_report(report_path, notes, tuning_c, key, keysrc, a)
        print("\n".join(head))
        nfix = sum(n["action"] == "fix" for n in notes)
        nflag = sum(n["action"] == "flag" for n in notes)
        print(f"{len(notes)} notes: {nfix} would move, {nflag} flagged. Report: {report_path}")
        return

    curve = shift_curve(midi, notes, a)
    print("shifting with Rubber Band…")
    lags, out = render(a.input, out_path, curve, sr, len(y), y2.shape[1])
    lag = f"{lags[2]} phrases, Rubber Band latency {lags[0]} samples (removed from all), " \
          f"per-phrase estimates within {lags[1]:.0f} samples of it"
    print("checking the result…")
    midi2 = verify(out.mean(1), sr, notes)
    head = write_report(report_path, notes, tuning_c, key, keysrc, a, lag)
    plot(str(out_path.with_suffix(".png")), midi, midi2, notes, out_path.stem)
    print("\n".join(head))
    nfix = sum(n["action"] == "fix" for n in notes)
    nflag = sum(n["action"] == "flag" for n in notes)
    print(f"{len(notes)} notes: {nfix} moved, {nflag} flagged (left alone).")
    print(f"wrote {out_path}, {report_path.name}, {out_path.with_suffix('.png').name}")


if __name__ == "__main__":
    main()
