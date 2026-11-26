#!/usr/bin/env python3
"""Natural pitch correction for vocal takes (note-by-note, like a graphical pitch editor's natural mode).

Reads a monophonic vocal file, finds every sung note, and moves each note's centre toward the right
pitch while leaving everything inside the note (vibrato, scoops, slides, breath) as it was sung.

  target   the nearest semitone in the SONG's tuning (measured from the notes, not assumed A=440).
           Only notes sung near a quarter-tone (ambiguous) use the key, or with --guide the lead
           vocal (the more consonant choice against what the lead sings at that moment).
           Harmonies come out matched to each other because every part is locked to the same grid.
  amount   how far to pull each note (default 0.35: extremely gentle; 1.0 = fully in tune)
  leave    notes already within --tolerance cents are untouched; a note sung halfway between two
           notes that neither the key nor the guide can settle is flagged, not changed
  drift    optional (--drift 0.5): also flatten slow pitch drift inside long notes; vibrato stays
  chord    every correction is checked against the chord the instruments play under the note (--chords
           INSTRUMENTAL.wav, else the --ref mix). A target that clashes with the chord while the other neighbour
           fits it is NOT moved: it is asked about (ASK in the report). Answer with --note-answer 0:15.32=C.
           Applying corrections without a chord source is refused (--no-chord-check to override).

The shift is done by Rubber Band (R3 engine, formants preserved so the voice keeps its character),
then the output is aligned back to the input sample-for-sample so it drops straight into Live. Only the
notes that move are replaced (each +-20 ms, 10 ms crossfades): every other sample is the original take.

Usage:
  hypnomix tune IN.wav OUT.wav --ref MIX.wav [--chords INSTRUMENTAL.wav] [--key "A minor"] [--amount 0.35] [--guide LEAD.wav]
  hypnomix tune IN.wav OUT.wav --ref MIX.wav --chords INSTRUMENTAL.wav --note-answer 0:15.32=C   (your call on an ASK)
  hypnomix tune IN.wav --report-only --ref MIX.wav     (just measure; the report goes to hypnomix-out/tune, numbered if one is there already)
  hypnomix tune IN.wav OUT.wav --ref MIX.wav --scales KEY.json [--answer F#] [--answer "17-24=both"]
           per-section scales from `hypnomix key --sections --json KEY.json` (songs that change key or borrow
           chords); --answer settles the sections the key map was unsure about (unanswered: notes on the disputed
           pitches are left exactly as sung; notes both scales share are tuned)
Writes OUT.wav plus OUT.notes.txt (every note: time, sung, target, cents before/after) and OUT.png.
The pitch track of a take (the slow part, minutes for a long take) is kept in <hypnomix home>/cache/pitch, named by the
audio itself, so a changed take is always tracked again and the same take (the scan, the previews, the fix) only once.
Disk care clears it; HYPNOMIX_NO_CACHE=1 tracks every time.
Needs Rubber Band 3+ (`brew install rubberband` on a Mac; without it tune stops at once with one line that says how to get it
on your system).
"""
import argparse, math, subprocess, sys, tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
import librosa

from hypnomix.studio import chords as CH

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


PITCH_VERSION = 1          # raise it whenever the tracking below changes: older kept results are then ignored
PITCH_KEEP = 300           # tracks kept (about 30 kB a minute of singing each); the least recently used go first
PITCH_STATS = {"hits": 0, "misses": 0}


def _pitch_file(y, sr):
    """Where this audio's pitch track is kept: <hypnomix home>/cache/pitch/pyin-<hash>.npy (beside the other pitch cache,
    so Disk care looks after it), the hash taken of the samples, the sample rate, the analysis settings and the versions
    of librosa and numpy. The key is the audio itself, so a changed take can never return an old answer, and a copy of the
    same audio hits too."""
    import hashlib
    from hypnomix.core.atomic import cache_root
    a = np.ascontiguousarray(y)
    h = hashlib.sha1(a)
    h.update(f"|{a.dtype}|{a.shape}|{sr}|{SR_A}|{HOP}|{FRAME}|librosa {librosa.__version__}|numpy {np.__version__}"
             f"|v{PITCH_VERSION}".encode())
    k = h.hexdigest()
    return cache_root() / "pitch" / f"pyin-{k}.npy"


def track_pitch(y, sr):
    """f0 in MIDI (float, NaN where unvoiced) on a 10 ms grid over the whole file.

    pYIN's Viterbi pass is the slow part of a vocal scan (about 80 s for five minutes of singing), and a scan, the
    previews after it and the fix after those all ask for the same take. The answer is kept on disk (see _pitch_file),
    written whole and renamed, at most PITCH_KEEP tracks; HYPNOMIX_NO_CACHE=1 measures every time."""
    import os
    f = None
    if not os.environ.get("HYPNOMIX_NO_CACHE"):
        try:
            f = _pitch_file(y, sr)
            if f.exists():
                midi = np.load(f)
                if midi.ndim == 1 and midi.dtype == np.float64:
                    PITCH_STATS["hits"] += 1
                    os.utime(f)                       # recently used: kept longest when the cache is trimmed
                    return midi
        except Exception:                             # unreadable (an old crash mid-write): measure again below
            pass
    midi = _track_pitch(y, sr)
    if f is not None:
        PITCH_STATS["misses"] += 1
        try:
            import threading
            from hypnomix.core.atomic import replace as atomic_replace
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_name(f"{f.stem}.{os.getpid()}.{threading.get_ident()}.tmp.npy")
            np.save(tmp, midi)
            atomic_replace(tmp, f)
            files = sorted((p for p in f.parent.glob("pyin-*.npy") if ".tmp." not in p.name), key=lambda p: p.stat().st_mtime)
            for old in files[: max(0, len(files) - PITCH_KEEP)]:
                old.unlink()
        except Exception:
            pass                                      # a cache that cannot be written is just a cache
    return midi


def _track_pitch(y, sr):
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


PC = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8,
      "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11}


def _pc(name):
    k = name.strip().replace("♯", "#").replace("♭", "b").upper()
    if k not in PC:
        sys.exit(f"unknown note {name!r} in --answer (use e.g. F, F#, Bb or 'both')")
    return PC[k]


def load_scales(path, answers=()):
    """Per-section scales from `hypnomix key --sections --json`: [(t0, t1, pitch-class set, label)], open questions.

    A section the key tool was sure about uses its scale. An unsure one (two scales that differ by one note) uses
    the person's answer: `--answer F#` (every section disputing F#), `--answer "17-24=F"` (one section) or
    `=both` (accept either note there). Unanswered unsure sections accept both notes and are listed as open.
    """
    import json
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    secs = d.get("sections")
    if not secs or "t0" not in secs[0]:
        sys.exit(f"{path}: no section times; make it with `hypnomix key --set SET --audio MIX --sections --json`")
    by_bars, every = {}, []
    for ans in answers:
        bars, _, note = ans.rpartition("=")
        (by_bars.__setitem__(bars.strip(), note.strip()) if bars else every.append(note.strip()))
    out, open_q = [], []
    uns = [sec for sec in secs if sec.get("unsure") and sec.get("disputed")]
    for bars, note in by_bars.items():
        sec = next((x for x in uns if x["bars"] == bars), None)
        if sec is None:
            sys.exit(f"--answer {bars}={note}: no key question for bars {bars} "
                     f"(questions: {', '.join(x['bars'] for x in uns) or 'none'})")
    for note in every:
        if note.lower() != "both" and not any(_pc(note) in {_pc(x) for d in sec_["disputed"] for x in d.split(",")}
                                              for sec_ in uns):
            q = sorted({f"{x['disputed'][0]} or {x['disputed'][1]}" for x in uns})
            sys.exit(f"--answer {note}: no key question is about that note (questions: {'; '.join(q) or 'none'})")
    for sec in secs:
        r, hold = sec["root"], ()
        base = {(r + st) % 12 for st in MAJOR}
        label = sec["scale"]
        dis = sec.get("disputed")
        if sec.get("unsure") and dis:
            mine, other = ({_pc(x) for x in dis[0].split(",")}, {_pc(x) for x in dis[1].split(",")})
            union = base | other
            hit = lambda x: x.lower() != "both" and (_pc(x) in mine or _pc(x) in other)
            ans = by_bars.get(sec["bars"])
            if ans is None:
                ans = next((x for x in every if x.lower() == "both" or hit(x)), None)
            if ans is None:   # unsure and unanswered: tune only notes common to both scales, leave the rest as sung
                pcs, hold, label = union - mine - other, mine | other, f"{dis[0]} or {dis[1]} (UNANSWERED: {dis[0]} and {dis[1]} left as sung)"
                open_q.append(f"bars {sec['bars']}: {dis[0]} or {dis[1]}?")
            elif ans.lower() == "both":
                pcs, label = union, f"{label} + {dis[1]} (both, as answered)"
            elif _pc(ans) in other:
                pcs, label = (union - mine), f"{sec['runner_up']} ({dis[1]}, as answered)"
            elif _pc(ans) in mine:
                pcs, label = base, f"{label} ({dis[0]}, as answered)"
            else:
                sys.exit(f"--answer {ans!r} for bars {sec['bars']}: the question there is {dis[0]} or {dis[1]}")
        else:
            pcs = base
        out.append((float(sec["t0"]), float(sec["t1"]), frozenset(pcs), f"bars {sec['bars']}: {label}", frozenset(hold)))
    return out, open_q


def scale_at(scales, t, default):
    for t0, t1, pcs, *_ in scales or ():
        if t0 <= t < t1:
            return pcs
    return default


def hold_at(scales, t):
    """Pitch classes left exactly as sung at time t (the disputed notes of an unanswered section)."""
    for t0, t1, _, _, hold in scales or ():
        if t0 <= t < t1:
            return hold
    return frozenset()


def note_name(m):
    m = int(round(m))
    return f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"


# ---------------------------------------------------------------- targets
def choose_targets(notes, tuning_c, key, guide_midi, a):
    root, mode = key
    whole = {(root + s) % 12 for s in (MAJOR if mode == "major" else MINOR)}
    off = tuning_c / 100
    for n in notes:
        scale = scale_at(getattr(a, "_scales", None), n["t0"], whole)   # the section's scale, if mapped
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
        if (pick % 12) in hold_at(getattr(a, "_scales", None), n["t0"]):
            n["action"] = "hold"   # the key there is unsure and unanswered, and this is the disputed note
        elif abs(n["cents"]) < a.tolerance:
            n["action"] = "ok"
        elif (len(cand) == 2 and why == "nearest") or abs(n["cents"]) > a.max:
            n["action"] = "flag"   # halfway between two notes and nothing says which was meant
        else:
            n["action"] = "fix"
        # the chord under the note: a target that clashes with it while the other neighbour fits is asked about
        ch = getattr(a, "_chords", None)
        n["chord"], n["suggest"] = [], None
        if ch is not None and n["action"] in ("fix", "flag"):
            other = pick + (1 if c > pick else -1) if abs(c - pick) > 1e-6 else None
            v, pcs, sug = CH.verdict(pick, other, ch, n["t0"], n["t1"])
            n["chord"] = pcs
            if n["action"] == "fix" and v == "ask":
                n["action"], n["suggest"] = "ask", sug + off
            elif n["action"] == "fix" and v == "colour":
                n["colour"] = True
            elif n["action"] == "flag" and pcs:
                fits = [x for x in (math.floor(c), math.ceil(c)) if x % 12 in pcs]
                if len(set(fits)) == 1:
                    n["suggest"] = fits[0] + off
        # the person's answer for this note wins (it may be further than --max: they decided)
        ans = next((pc for t, pc in getattr(a, "_note_answers", []) if abs(t - n["t0"]) <= 0.06), None)
        if ans is not None:
            best = min((m for m in range(int(c) - 2, int(c) + 3) if m % 12 == ans), key=lambda m: abs(m - c))
            n["target"], n["why"] = best + off, "your answer"
            n["cents"] = (n["centre"] - n["target"]) * 100
            n["action"] = "fix" if abs(n["cents"]) >= 1 else "ok"
        n["shift"] = -n["cents"] / 100 * a.amount if n["action"] == "fix" else 0.0
    return notes


def parse_note_answers(items):
    """["0:15.32=C", "75.3=F#"] -> [(seconds, pitch class)]"""
    out = []
    for it in items:
        t, _, nm = it.partition("=")
        nm = nm.strip().replace("Db", "C#").replace("Eb", "D#").replace("Gb", "F#").replace("Ab", "G#").replace("Bb", "A#")
        if nm not in NOTE_NAMES:
            sys.exit(f"--note-answer {it}: the note must be a name like C or F#")
        mm, _, ss = t.strip().rpartition(":")
        out.append(((int(mm) * 60 if mm else 0) + float(ss), NOTE_NAMES.index(nm)))
    return out


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


def merge_spans(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def crossfade_in(out, new, i0, i1, sr, fade_s=0.01):
    """Replace out[i0:i1] with new[i0:i1], with `fade_s` crossfades at both ends."""
    n = i1 - i0
    if n <= 0:
        return
    fade = min(int(fade_s * sr), n // 4)
    w = np.ones(n, np.float32)
    if fade:
        w[:fade] = np.linspace(0, 1, fade)
        w[n - fade:] = np.linspace(1, 0, fade)
    out[i0:i1] = out[i0:i1] * (1 - w[:, None]) + new[i0:i1] * w[:, None]


def render(in_path, out_path, curve, sr, n_samples, channels, keep=(), moved=None, pad_s=0.02):
    """Shift each sung phrase separately (Rubber Band's pitch-map mode drifts over long files) and line it up
    with the original sample-for-sample. Only the notes that move are spliced in (each note +-pad_s, 10 ms
    crossfades); everything else, notes left alone included, stays the original audio bit for bit.
    `moved`: [(t0, t1)] of the moved notes (None: the whole phrase, the old behaviour)."""
    from concurrent.futures import ThreadPoolExecutor
    from hypnomix.core.tools import need_rubberband
    need_rubberband("tune")
    from hypnomix.core import dsp
    src = dsp.load(in_path)[0].astype(np.float32)          # the checked loader: a broken file ends in one sentence
    mono = src.mean(1)
    peak = float(np.abs(src).max()) or 1.0
    scale = 0.9 / peak                      # Rubber Band writes fixed-point: keep float overs intact
    out = src.copy()
    shifted = src.copy()
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
        with tempfile.TemporaryDirectory(prefix="hypnomix-work-") as td:
            seg_in, seg_out, pm = Path(td) / "in.wav", Path(td) / "out.wav", Path(td) / "pm.txt"
            sf.write(str(seg_in), src[i0:i1] * scale, sr, subtype="FLOAT")
            frames = ((k0 + np.arange(len(seg_curve))) * HOP / SR_A * sr).astype(int) - i0
            with open(pm, "w", encoding="utf-8") as f:
                for fr, sh in zip(frames, seg_curve):
                    if fr >= 0:
                        f.write(f"{fr} {sh:.5f}\n")
            r = subprocess.run(["rubberband", "-3", "-F", "-q", "--pitchmap", str(pm), str(seg_in), str(seg_out)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
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
            shifted[i0:i1] = shifted[i0:i1] * (1 - w[:, None]) + y[:n] * w[:, None]
    if moved is None:
        out = shifted
    else:                                   # the moved notes only; the rest stays exactly as sung
        for t0, t1 in merge_spans([(t0 - pad_s, t1 + pad_s) for t0, t1 in moved]):
            crossfade_in(out, shifted, max(0, int(t0 * sr)), min(len(src), int(t1 * sr)), sr)
    for t0, t1 in keep:                     # held notes: the original audio, sample for sample, 10 ms crossfades
        i0, i1 = max(0, int(t0 * sr)), min(len(src), int(t1 * sr))
        n = i1 - i0
        if n <= 0:
            continue
        fade = min(int(0.01 * sr), n // 4)
        w = np.ones(n, np.float32)
        if fade:
            w[:fade] = np.linspace(0, 1, fade)
            w[n - fade:] = np.linspace(1, 0, fade)
        out[i0:i1] = out[i0:i1] * (1 - w[:, None]) + src[i0:i1] * w[:, None]
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
             f"key: {NOTE_NAMES[key[0]]} {key[1]} ({keysrc})"
             + ("".join(f"\n  {lab}" for _, _, _, lab, _ in a._scales) if getattr(a, "_scales", None) else "")
             + (f"\n  OPEN QUESTIONS (the disputed notes are left as sung there until answered): {'; '.join(a._open)}"
                if getattr(a, "_open", None) else ""),
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
               "flag": "FLAG: between two notes, left alone",
               "hold": "HOLD: disputed note, key unsure here, left as sung",
               "ask": "ASK: target clashes with the chord, left as sung"}[n["action"]]
        if n.get("out_of_key") and n["action"] != "hold":
            act += " [out of key]"
        if n.get("chord"):
            act += f" [chord {CH.name(n['chord'])}]"
        if n.get("colour"):
            act += " [not a chord tone: passing note?]"
        if n.get("suggest") is not None:
            act += f" -> chord suggests {NOTE_NAMES[int(round(n['suggest'])) % 12]}: --note-answer {_mmss(n['t0'])}=" \
                   f"{NOTE_NAMES[int(round(n['suggest'])) % 12]}"
        lines.append(f"{_mmss(n['t0']):>8}  {n['t1'] - n['t0']:5.2f}  {note_name(n['centre']):>5} -> "
                     f"{note_name(n['target']):<6} {n['cents']:+6.0f}  {aft}  {act}{why}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines[:6]


def write_json(path, a, notes, tuning_c, key, keysrc):
    import json
    cents = np.array([abs(n["cents"]) for n in notes])
    med = float(np.median(cents)) if len(cents) else 0.0
    within = float((cents <= 15).mean() * 100) if len(cents) else 100.0
    nfix = sum(n["action"] == "fix" for n in notes)
    flags = [n for n in notes if n["action"] == "flag"]
    asks = [n for n in notes if n["action"] == "ask"]
    sev = "high" if med >= 25 else "medium" if med >= 15 else "low"
    summary = dict(
        id="tune-" + Path(a.input).stem, tool="tune", kind="pitch", severity=sev, track=Path(a.input).stem,
        where="whole take", problem=f"median {med:.0f} cents off, {within:.0f}% of notes within ±15 cents",
        fix=f"tune {nfix} notes ({a.amount:.0%} of the way), {len(flags)} ambiguous notes flagged for your ear"
            + (f", {sum(n['action'] == 'hold' for n in notes)} left as sung where the key is unsure (answer the key "
               "question to tune them)" if any(n["action"] == "hold" for n in notes) else "")
            + (f", {len(asks)} notes ASKED: the nearest note clashes with the chord underneath (your call)" if asks else ""),
        applies="audio", input=str(a.input))
    Path(path).write_text(json.dumps({
        "tool": "tune", "input": str(a.input), "tuning_cents": round(tuning_c, 1),
        "key": f"{NOTE_NAMES[key[0]]} {key[1]}", "key_source": keysrc, "findings": [summary],
        "scales": [lab for _, _, _, lab, _ in (getattr(a, "_scales", None) or [])], "open_questions": getattr(a, "_open", []),
        "flagged": [dict(time=_mmss(n["t0"]), sung=note_name(n["centre"]), cents=round(n["cents"]),
                         chord=CH.name(n.get("chord")), suggest=NOTE_NAMES[int(round(n["suggest"])) % 12] if n.get("suggest") is not None else None)
                    for n in flags],
        "asked": [dict(time=_mmss(n["t0"]), sung=note_name(n["centre"]), cents=round(n["cents"]),
                       nearest=note_name(n["target"]), chord=CH.name(n["chord"]),
                       suggest=NOTE_NAMES[int(round(n["suggest"])) % 12]) for n in asks],
        "chord_check": getattr(a, "_chord_src", "off"),
    }, indent=1), encoding="utf-8")


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
    ap.add_argument("--scales", metavar="KEY.json", help="per-section scales from `hypnomix key --sections --json` "
                    "(songs that change key or borrow chords); --key is then only the fallback")
    ap.add_argument("--answer", action="append", default=[], metavar="NOTE|BARS=NOTE|both",
                    help="the person's answer to a key QUESTION, e.g. F#, \"17-24=F\" or both (repeatable)")
    ap.add_argument("--guide", help="lead vocal file: settles ambiguous harmony notes toward a consonant interval")
    ap.add_argument("--amount", type=float, default=0.35,
                    help="how far to pull each note, 0-1 (default 0.35: extremely gentle, a nudge not a fix)")
    ap.add_argument("--tolerance", type=float, default=20.0, help="leave notes within this many cents (20)")
    ap.add_argument("--whole-phrases", action="store_true",
                    help="send whole phrases through the shifter (old behaviour); default replaces only moved notes")
    ap.add_argument("--max", type=float, default=25.0, help="never move a note more than this many cents (25: no note becomes another)")
    ap.add_argument("--drift", type=float, default=0.0, help="also flatten slow drift inside notes, 0-1 (0)")
    ap.add_argument("--tuning", type=float, help="song tuning in cents from A=440 (default: measured)")
    ap.add_argument("--ref", help="the song's mix or instrumental: measure tuning and key from it (recommended)")
    ap.add_argument("--json", metavar="OUT.json", help="also write a summary + the notes as JSON")
    ap.add_argument("--chords", metavar="INSTRUMENTAL.wav", help="the song without vocals, sample-aligned with the input "
                    "(or a .npz from `fix`): every correction is checked against the chord under the note (default: the --ref mix)")
    ap.add_argument("--no-chord-check", action="store_true", help="skip the chord check (not recommended)")
    ap.add_argument("--note-answer", action="append", default=[], metavar="TIME=NOTE",
                    help='your call on an ASK or FLAG note, e.g. "0:15.32=C" (repeatable)')
    a = ap.parse_args()
    if not a.report_only and not a.output:
        sys.exit("give an OUT.wav, or --report-only")
    if a.output and Path(a.output).resolve() == Path(a.input).resolve():
        sys.exit("refusing to overwrite the input; give a new file name")
    if not 0 < a.amount <= 1:
        sys.exit("--amount must be between 0 and 1")
    if not a.report_only:
        from hypnomix.core.tools import need_rubberband
        need_rubberband("tune")                 # before the slow part: one plain sentence, not a traceback
    from hypnomix.core import dsp
    y2, sr = dsp.load(a.input)
    y2 = y2.astype("float32")
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
    a._scales, a._open = None, []
    if a.scales:
        a._scales, a._open = load_scales(a.scales, a.answer)
        import json as _j
        kj = _j.loads(Path(a.scales).read_text(encoding="utf-8", errors="replace"))
    if a.key:
        key, keysrc = parse_key(a.key), "given"
    elif a.scales and kj.get("key"):
        key, keysrc = parse_key(kj["key"]), "whole-song key from the section map (used outside mapped sections)"
    elif ref_key is not None:
        key, keysrc = ref_key, f"from the reference, fit {ref_fit:.2f}; confirm with --key"
    else:
        r, m, conf = estimate_key(notes, tuning_c)
        key, keysrc = (r, m), f"estimated from the vocal, fit {conf:.2f}; confirm with --key"
    guide = None
    if a.guide:
        g, gsr = dsp.load(a.guide)
        g = g.astype(np.float32)
        if gsr != sr:
            sys.exit("the guide must have the same sample rate as the input")
        print("tracking the guide…")
        guide = track_pitch(g.mean(1), gsr)
    a._note_answers = parse_note_answers(a.note_answer)
    a._chords, a._chord_src = None, "off"
    if not a.no_chord_check:
        if a.chords:
            a._chords, a._chord_src = CH.load(a.chords), f"instrumental {Path(a.chords).name}"
        elif a.ref:
            a._chords, a._chord_src = CH.chroma(a.ref), "the --ref mix (vocals included; --chords INSTRUMENTAL.wav is surer)"
        elif a.output:
            sys.exit("refusing to correct notes without checking the chord under them: pass --chords INSTRUMENTAL.wav "
                     "(the song without vocals) or --ref MIX.wav, or --no-chord-check")
        else:
            print("note: no --chords or --ref, so the chord under each note is not checked")
    if a._chords is not None:
        print(f"chord check: {a._chord_src}")
    choose_targets(notes, tuning_c, key, guide, a)

    if a.output:
        out_path = Path(a.output)
        report_path = Path(str(out_path.with_suffix("")) + ".notes.txt")
    elif a.json:  # report-only with --json: the note report goes next to the JSON
        out_path = Path(a.json).with_suffix("")
        report_path = Path(str(out_path) + ".notes.txt")
    else:  # report-only: never write next to the source take
        from hypnomix.core.paths import out as out_dir          # hypnomix-out/tune, or where HYPNOMIX_OUT says
        out_path = out_dir("tune") / Path(a.input).stem
        k = 2                                                   # a second run never replaces the first one's report
        while Path(str(out_path) + ".notes.txt").exists():
            out_path = out_dir("tune") / f"{Path(a.input).stem} {k}"
            k += 1
        report_path = Path(str(out_path) + ".notes.txt")
    if a.json:
        write_json(a.json, a, notes, tuning_c, key, keysrc)
    if a.report_only:
        head = write_report(report_path, notes, tuning_c, key, keysrc, a)
        print("\n".join(head))
        nfix = sum(n["action"] == "fix" for n in notes)
        nflag = sum(n["action"] == "flag" for n in notes)
        nhold = sum(n["action"] == "hold" for n in notes)
        nask = sum(n["action"] == "ask" for n in notes)
        print(f"{len(notes)} notes: {nfix} would move, {nflag} flagged" + (f", {nhold} held (disputed note, key unsure)" if nhold else "")
              + (f", {nask} ASKED (nearest note clashes with the chord)" if nask else "")
              + f". Report: {report_path}")
        return

    curve = shift_curve(midi, notes, a)
    print("shifting with Rubber Band…")
    keep = [(nt["t0"] - 0.01, nt["t1"] + 0.01) for nt in notes if nt["action"] in ("hold", "ask")]
    moved = [(nt["t0"], nt["t1"]) for nt in notes if nt["action"] == "fix" and abs(nt["shift"]) > 1e-4]
    lags, out = render(a.input, out_path, curve, sr, len(y), y2.shape[1], keep,
                       moved=None if a.whole_phrases else moved)
    untouched = float(np.mean(np.all(out == y2, axis=1))) if out.shape == y2.shape else float("nan")
    lag = f"{lags[2]} phrases, Rubber Band latency {lags[0]} samples (removed from all), " \
          f"per-phrase estimates within {lags[1]:.0f} samples of it"
    print("checking the result…")
    midi2 = verify(out.mean(1), sr, notes)
    head = write_report(report_path, notes, tuning_c, key, keysrc, a, lag)
    plot(str(out_path.with_suffix(".png")), midi, midi2, notes, out_path.stem)
    print("\n".join(head))
    nfix = sum(n["action"] == "fix" for n in notes)
    nflag = sum(n["action"] == "flag" for n in notes)
    nhold = sum(n["action"] == "hold" for n in notes)
    nask = sum(n["action"] == "ask" for n in notes)
    print(f"{len(notes)} notes: {nfix} moved, {nflag} flagged (left alone)"
          + (f", {nhold} held as sung (disputed note where the key is unsure)" if nhold else "")
          + (f", {nask} ASKED and left as sung (the nearest note clashes with the chord; answer with --note-answer)" if nask else "") + ".")
    print(f"{untouched:.0%} of the take is the original audio, bit for bit"
          + (" (--whole-phrases: every phrase with a moved note went through the shifter)" if a.whole_phrases
             else " (only moved notes are replaced)"))
    print(f"wrote {out_path}, {report_path.name}, {out_path.with_suffix('.png').name}")


if __name__ == "__main__":
    main()
