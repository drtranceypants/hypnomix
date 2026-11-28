#!/usr/bin/env python3
"""Loops mode: pick the best sections across stems to loop, align their edges, make variations, put them in
Session slots of a new set.

  hypnomix loopset STEMS_DIR [--bpm B] [--downbeat S] [--bars 1 2 4 8] [--top 6] [--variations 4]
                   [--anchor NAME] [--complexity subtle|normal|complex] [--out DIR] [--seed N]
  hypnomix loopset STEMS_DIR --set SET.als --apply NEW.als
  hypnomix loopset --takes SET.als [--tracks "a,b"] [--per-track 6] [--bars 2,4,8] [--variations 3] [--combos 16]
                   [--seed N] [--out DIR] [--apply NEW.als]

STEMS_DIR holds the stems exported from the song (WAV/AIFF/FLAC, "export all individual tracks" in Live), all
starting at the song's bar 1. The tempo and the first bar line come from the drum stem (the stem named drums,
kick, snare ...; else the sum of all stems) unless you give --bpm / --downbeat. The tempo used is printed.

Every window of 1, 2, 4 and 8 bars (--bars) that starts on a bar line is scored:

  seam      how well the end leads back into the start, on every stem (spectrum match of what follows the
            window with the window's first beat, and level match), weighted by how loud the stem is
  section   steady energy, few silent stems, bars that repeat the same pattern

Windows where most stems are silent are skipped. The best --top are kept, not overlapping each other, from
different sections first. For each pick the stems share the same edges (the first downbeat lands on the
clip start, no hit of the next bar sticks to the end: see `hypnomix loopedges`) and every stem is cut.

Variations (--variations, default 4) are made on the anchor stem only (--anchor, default the drums); the other
stems stay as they are. Odd numbers are slice changes on 16 slices a bar (copy a slice to another step, reverse
one, repeat the start of one 2-4 times, dip the volume of one), even numbers are a fill on the loop's last bar.
--complexity sets how many changes a bar gets (subtle 1-2, normal 2-4, complex 4-8) and how big the fills are.
The first downbeat slice is never touched. Same --seed, same variations.

Output: "<rank> <section> <bars>b/<stem>.wav", ".../variations/<stem> v<n> <kind>.wav", LOOPSET.md and
loopset.json. With --set and --apply a NEW set is written: for each stem that matches a track by name, a new
track "<track> loops" right after it whose Session slots hold the picks (one scene row per rank) and the
anchor's variations in the rows below, warped to the set's tempo, looping, named. The original set is never
changed. Add scenes in Live first if the set has fewer rows than needed. Close the set before --apply.

Takes mode (--takes SET.als): for a Live set with long takes recorded to a click on many audio tracks (main lane and
Live 12 take lanes; disabled clips and clips under 8 bars are skipped). Each take clip is rendered as Live plays it
and cut on the set's bar lines (constant tempo assumed; a warning is printed when the set has tempo automation).
Per track, the best bar-aligned windows (--bars, default 2,4,8) over all its takes are picked (--per-track, from
different takes and song positions first, near-silent windows dropped), edge-aligned, and given --variations
variations. Then --combos combinations are built: one loop (original or variation) per instrument, all the same
length, about one slot in four left silent, chosen for the best agreement of pitch content (12-bin chroma) and
not reusing the same loops while others are free; the same --seed gives the same combos. Output: one folder per
track, LOOPSET.md, loopset.json (default folder: next to the set, "<set> loopset"). With --apply NEW.als a new
set gets a "<track> loops" track per instrument and scenes (the set's empty rows at the end are reused, the
rest appended): "Combo 1".."Combo N", then "Pick r" (every instrument's rank-r loop) and "Pick r v1".. (their variations). The original is never changed.
"""
import argparse, copy, json, math, re, sys, tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix.core import args as A
from hypnomix.session import beats as B
from hypnomix.session import loopedges as LE
from hypnomix.session import turnaround_fx as TX
from hypnomix.session import loops as LP
from hypnomix.session.variations import DRUM_WORDS

EXTS = (".wav", ".aif", ".aiff", ".flac")
SILENT = 1e-3              # a stem quieter than this (RMS, about -60 dBFS) counts as silent
XFADE_MS = 2.0
CHANGES = {"subtle": (1, 2), "normal": (2, 4), "complex": (4, 8)}      # slice changes per bar
FILL_LEVEL = {"subtle": 1, "normal": 2, "complex": 3}
SLICES = 16
PAD_S = 0.25               # context kept around a window when finding its edges
HEAD_S = 0.08
TAIL_S = 0.05
BANDS = 24


def clean(s):
    return re.sub(r'[\\/:*?"<>|]', "-", s).strip()


# ---------------------------------------------------------------- reading
def load_stems(folder):
    files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in EXTS and not p.name.startswith("."))
    if not files:
        sys.exit(f"no audio stems (WAV/AIFF/FLAC) in {folder}")
    stems, sr = {}, None
    for p in files:
        y, r = sf.read(str(p), always_2d=True, dtype="float32")
        if sr is None:
            sr = r
        elif r != sr:
            sys.exit(f"{p.name} is {r} Hz but the others are {sr} Hz: export all stems at one sample rate")
        name = p.stem
        while name in stems:
            name += "_"
        stems[name] = y
    n = max(len(y) for y in stems.values())
    for k, y in stems.items():
        if len(y) < n:
            stems[k] = np.pad(y, ((0, n - len(y)), (0, 0)))
    return stems, sr


def rms(x):
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0


def is_drum(name):
    return any(w in name.lower() for w in DRUM_WORDS)


def pick_drums(stems):
    d = [k for k in stems if is_drum(k)]
    return max(d, key=lambda k: rms(stems[k])) if d else None


def find_stem(stems, name):
    low = name.lower()
    for k in stems:
        if k.lower() == low:
            return k
    hit = [k for k in stems if low in k.lower()]
    return hit[0] if len(hit) == 1 else None


def grid(stems, sr, bpm, downbeat, bpb, drums):
    """(bpm, first bar line in seconds, how it was found)."""
    if bpm is not None and downbeat is not None:
        return float(bpm), float(downbeat), "given"
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "grid.wav"
        y = stems[drums] if drums else sum(y.mean(1) for y in stems.values()).reshape(-1, 1)
        if not drums:
            y = y / max(1e-9, float(np.abs(y).max()))
        sf.write(str(f), y, sr, subtype="FLOAT")
        try:
            m = B.track(f, bpb=bpb, bpm=bpm, downbeat=downbeat)
        except ValueError as e:
            sys.exit(f"could not follow the beat ({e}): give --bpm and --downbeat")
    how = "from the " + (f"drum stem {drums!r}" if drums else "sum of the stems")
    b = float(bpm) if bpm is not None else float(m["bpm"])
    d = float(downbeat) if downbeat is not None else float(m["bars"][0]) if len(m["bars"]) else 0.0
    return b, d, how


# ---------------------------------------------------------------- scoring
def _spec(x, sr):
    """24 log-spaced band levels (dB) of a short stretch, centred; None when it is silent."""
    if len(x) < 64 or rms(x) < 1e-5:
        return None
    S = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1.0 / sr)
    edges = np.geomspace(60, min(16000, sr / 2 - 1), BANDS + 1)
    v = np.array([S[(f >= a) & (f < b)].sum() if ((f >= a) & (f < b)).any() else 0.0 for a, b in zip(edges[:-1], edges[1:])])
    v = 20 * np.log10(v + 1e-6)
    return v - v.mean()


def _corr(a, b):
    if a is None and b is None:
        return 1.0
    if a is None or b is None:
        return 0.0
    d = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / d) if d > 1e-9 else 1.0


def analyse(stems, sr, bpm, down, bpb):
    """Per bar line and stem: the spectrum of the first 80 ms and the level of the last 50 ms before it;
    per bar: pattern vector, level, which stems play."""
    n = len(next(iter(stems.values())))
    bar = 60.0 / bpm * bpb
    nbars = int((n / sr - down) // bar)
    line = lambda j: int(round((down + j * bar) * sr))
    hs, ts = int(HEAD_S * sr), int(TAIL_S * sr)
    names = list(stems)
    mono = {k: y.mean(1) for k, y in stems.items()}
    head = {k: [_spec(mono[k][line(j): line(j) + hs], sr) if line(j) + hs <= n else None for j in range(nbars + 1)] for k in names}
    tail = {k: [rms(mono[k][max(0, line(j) - ts): line(j)]) for j in range(nbars + 1)] for k in names}
    bar_rms = {k: np.array([rms(mono[k][line(j): line(j + 1)]) for j in range(nbars)]) for k in names}
    total = {k: rms(mono[k]) for k in names}
    mix = sum(mono.values())
    beats = down + np.arange(nbars * bpb + 1) * 60.0 / bpm
    P, level, _ = LP.bar_patterns(mix, sr, beats, 0, bpb)
    lab = LP.grooves(P) if len(P) else []
    return dict(n=n, bar=bar, nbars=nbars, line=line, head=head, tail=tail, bar_rms=bar_rms, total=total,
                P=P, level=level, lab=lab, names=names)


def score_windows(an, sizes):
    names = an["names"]
    w = {k: (an["total"][k] if an["total"][k] >= SILENT else 0.0) for k in names}
    ws = sum(w.values())
    if ws <= 0:
        return []
    w = {k: v / ws for k, v in w.items()}
    ever = [k for k in names if (an["bar_rms"][k] >= SILENT).any()]
    P, level, nb = an["P"], an["level"], an["nbars"]
    loud = level > (np.median(level) - 18) if len(level) else np.zeros(0, bool)
    out = []
    db = lambda v: 20 * math.log10(v + 1e-6)
    for L in sizes:
        for i in range(0, nb - L + 1):
            if not loud[i: i + L].all():
                continue
            act = [k for k in ever if (an["bar_rms"][k][i: i + L] >= SILENT).mean() >= 0.5]
            if not ever or len(act) * 2 < len(ever):
                continue                                  # most stems are silent here
            if i + L < nb:
                seam_c = sum(w[k] * max(0.0, _corr(an["head"][k][i], an["head"][k][i + L])) for k in names)
                seam_l = sum(w[k] * math.exp(-abs(db(an["tail"][k][i + L]) - db(an["tail"][k][i])) / 6.0) for k in names)
            else:
                seam_c = seam_l = 0.5                     # the song ends here: nothing follows to compare
            seam = 0.5 * seam_c + 0.5 * seam_l
            body = P[i: i + L]
            if L == 1:
                nbr = [float(P[i] @ P[j]) for j in (i - 1, i + 1) if 0 <= j < len(P)]
                alike = float(np.mean(nbr)) if nbr else 1.0
            else:
                alike = float(np.mean([body[a] @ body[b] for a in range(L) for b in range(a + 1, L)]))
            stable = math.exp(-float(np.std(level[i: i + L])) / 3.0) if L > 1 else 1.0
            active = len(act) / len(ever)
            quality = 0.35 * max(0.0, alike) + 0.3 * stable + 0.35 * active
            g = max(set(an["lab"][i: i + L]), key=an["lab"][i: i + L].count)
            out.append(dict(bar=i + 1, bars=L, seam=round(seam, 3), seam_corr=round(seam_c, 3), seam_level=round(seam_l, 3),
                            alike=round(alike, 3), stable=round(stable, 3), active=round(active, 3),
                            quality=round(quality, 3), score=round(0.4 * seam + 0.6 * quality, 3),
                            section="ABCDEFGHIJKLMNOPQRSTUVWXYZ"[g % 26]))
    return out


def choose(cands, top):
    """The best, not overlapping, different sections first. Returns them ranked by score."""
    cands = sorted(cands, key=lambda c: (-c["score"], c["bar"], -c["bars"]))
    picked, per = [], {}
    for cap in (1, 2, 99):
        for c in cands:
            if len(picked) >= top:
                break
            key = c["section"]
            if c in picked or per.get(key, 0) >= cap:
                continue
            if any(c["bar"] < p["bar"] + p["bars"] and p["bar"] < c["bar"] + c["bars"] for p in picked):
                continue
            picked.append(c)
            per[key] = per.get(key, 0) + 1
    picked.sort(key=lambda c: (-c["score"], c["bar"]))
    for r, c in enumerate(picked, 1):
        c["rank"] = r
    return picked


# ---------------------------------------------------------------- edges and cuts
def cut_pick(stems, sr, an, c, anchor_ref=None):
    """Align the stems of one pick on shared bounds and cut each. Adds new_start/new_end/flags to c."""
    a_s = an["line"](c["bar"] - 1) / sr
    b_s = an["line"](c["bar"] - 1 + c["bars"]) / sr
    o = max(0.0, a_s - PAD_S)
    i0, i1 = int(o * sr), min(an["n"], int((b_s + PAD_S) * sr))
    local = {k: (y[i0:i1], sr) for k, y in stems.items()}
    ref = anchor_ref if anchor_ref in stems and an["total"][anchor_ref] >= SILENT else None
    g = LE.align_group(local, a_s - o, b_s - o, ref=ref)
    flags = list(g["reference"]["flags"])
    cuts = {}
    for k, (y, _) in local.items():
        cuts[k] = LE.cut_audio(y, sr, g["new_start"], g["new_end"])
        if an["total"][k] >= SILENT:
            flags += [f"{k}:{f}" for f in g["stems"][k]["flags"] if f not in g["reference"]["flags"]]
    c.update(start_s=round(g["new_start"] + o, 5), end_s=round(g["new_end"] + o, 5), ref=g["ref"], flags=flags,
             offsets_ms={k: (None if v["offset_ms"] is None else round(v["offset_ms"], 2)) for k, v in g["stems"].items()
                         if an["total"][k] >= SILENT},
             length_ms=round((g["new_end"] - g["new_start"]) * 1000, 2),
             length_off_ms=round(g["reference"]["length_diff_ms"], 2))
    return cuts


# ---------------------------------------------------------------- variations
def _put(out, orig, a, b, new, sr):
    """Write `new` over out[a:b], crossfading 2 ms with the original at both joins."""
    f = min(int(round(sr * XFADE_MS / 1000.0)), (b - a) // 2)
    m = np.ones(b - a)
    if f > 0:
        m[:f] = np.linspace(0, 1, f)
        m[-f:] = np.minimum(m[-f:], np.linspace(1, 0, f))
    out[a:b] = orig[a:b] * (1 - m)[:, None] + new * m[:, None]


def mutate(y, sr, bars, seed, complexity="normal"):
    """Slice changes on 16 slices a bar. y: (n, ch). Returns (new audio, [ops]). The first slice never changes."""
    lo, hi = CHANGES[complexity]
    rng = np.random.default_rng(seed)
    n = len(y)
    ns = SLICES * bars
    bound = [int(round(i * n / ns)) for i in range(ns + 1)]
    out = np.array(y, dtype=np.float32, copy=True)
    ops = []
    for bar in range(bars):
        free = [s for s in range(bar * SLICES, (bar + 1) * SLICES) if s != 0]
        k = min(int(rng.integers(lo, hi + 1)), len(free))
        for s in sorted(rng.choice(free, size=k, replace=False).tolist()):
            a, b = bound[s], bound[s + 1]
            if b - a < 8:
                continue
            kind = ["rearrange", "reverse", "density", "volume"][int(rng.integers(0, 4))]
            if kind == "rearrange":
                src = int(rng.choice([j for j in range(ns) if j != s]))
                seg = y[bound[src]: bound[src + 1]]
                seg = seg[: b - a] if len(seg) >= b - a else np.pad(seg, ((0, b - a - len(seg)), (0, 0)))
                op = dict(slice=s, kind=kind, source=src)
            elif kind == "reverse":
                seg = y[a:b][::-1]
                op = dict(slice=s, kind=kind)
            elif kind == "density":
                d = int(rng.integers(2, 5))
                part = np.array(y[a: a + max(2, (b - a) // d)], copy=True)
                f = min(len(part) // 2, int(sr * 0.001))
                if f > 0:
                    part[:f] *= np.linspace(0, 1, f)[:, None]
                    part[-f:] *= np.linspace(1, 0, f)[:, None]
                seg = np.tile(part, (d + 1, 1))[: b - a]
                op = dict(slice=s, kind=kind, repeats=d)
            else:
                g = float(rng.uniform(0.2, 0.5))
                seg = y[a:b] * g
                op = dict(slice=s, kind=kind, gain=round(g, 3))
            _put(out, y, a, b, seg, sr)
            ops.append(op)
    return out, ops


def fill(y, sr, bars, bpb, bpm_eff, n, seed, complexity):
    """A fill on the loop's last bar (turnaround_fx), n = the variation number."""
    pad = np.zeros((int(2 * sr), y.shape[1]), dtype=np.float32)
    x = np.concatenate([y, pad]).astype(np.float64)
    r = TX.render_window(x, sr, bpm_eff, n, (bars - 1) * 4 * bpb, 4 * bpb, 0, 0.0,
                         level=FILL_LEVEL[complexity], seed=seed, beats_per_bar=bpb)
    return np.asarray(r[: len(y)], dtype=np.float32)


def make_variations(y, sr, c, bpb, count, seed, complexity):
    """[(n, kind, audio, info)] for one pick's anchor cut."""
    bpm_eff = c["bars"] * bpb * 60.0 / (len(y) / sr)
    out = []
    for v in range(1, count + 1):
        s = seed * 1000 + c["rank"] * 50 + v
        if v % 2:
            a, ops = mutate(y, sr, c["bars"], s, complexity)
            out.append((v, "slices", a, dict(ops=ops)))
        else:
            out.append((v, "fill", fill(y, sr, c["bars"], bpb, bpm_eff, v, s, complexity),
                        dict(level=FILL_LEVEL[complexity], fill_index=v)))
    return out


# ---------------------------------------------------------------- writing a set
def _norm(name):
    return re.sub(r"^\s*\d+\s*[-_. ]\s*", "", name).strip().lower()


def _file_ref(clip, f, sr_frames):
    fr = clip.find("./SampleRef/FileRef")
    B.set_val(fr, "./Path", str(f))
    rel = fr.find("./RelativePath")
    if rel is not None:
        rel.set("Value", str(f))
    B.set_val(fr, "./OriginalFileSize", str(f.stat().st_size))
    B.set_val(fr, "./OriginalCrc", "0")
    B.set_val(clip, "./SampleRef/DefaultDuration", str(sr_frames[0]))
    B.set_val(clip, "./SampleRef/DefaultSampleRate", str(sr_frames[1]))
    B.set_val(clip, "./SampleRef/LastModDate", str(int(f.stat().st_mtime)))


def session_clip(template, f, name, beats, warp_mode):
    """A looping Session clip that plays the whole file `f` over `beats` beats at the set's tempo."""
    info = sf.info(str(f))
    clip = copy.deepcopy(template)
    clip.set("Id", "0"); clip.set("Time", "0")
    _file_ref(clip, f, (info.frames, info.samplerate))
    for par in list(clip.iter()):                           # a template's envelopes point at its own track
        for e in list(par):
            if e.tag == "ClipEnvelope":
                par.remove(e)
    clip.find("./IsWarped").set("Value", "true")
    B.set_val(clip, "./WarpMode", str(warp_mode))
    B.set_markers(clip, [(0.0, 0.0), (info.frames / info.samplerate, float(beats))])
    B.set_region(clip, 0.0, float(beats), loop=True)
    clip.find("./CurrentStart").set("Value", "0")
    clip.find("./CurrentEnd").set("Value", repr(float(beats)))
    B.set_val(clip, "./Name", name)
    B.set_val(clip, "./SampleVolume", 1.0)
    for tag in ("FadeInLength", "FadeOutLength"):
        B.set_val(clip, f"./Fades/{tag}", 0.0)
    return clip


def apply_set(src, dst, plan, bpb, notes):
    """plan = {stem: [(row, file, name, beats)]}. Returns True when the new set was written."""
    from hypnomix.session import automation as aa, variations as V
    tree = aa.load(src); root = tree.getroot()
    tempo = B.set_tempo(root)
    tracks = [t for t in root.find(".//Tracks") if t.tag == "AudioTrack"]
    by_name = {}
    for t in tracks:
        by_name.setdefault(t.find("./Name/EffectiveName").get("Value").strip().lower(), t)
        by_name.setdefault(_norm(t.find("./Name/EffectiveName").get("Value")), t)
    added, placed, missed = [], 0, 0
    for stem, items in plan.items():
        t = by_name.get(stem.strip().lower()) or by_name.get(_norm(stem))
        if t is None:
            notes.append(f"{stem}: no audio track of that name in the set, skipped")
            continue
        tpl = (B.clips_of(t) or t.findall("./DeviceChain/MainSequencer/ClipSlotList/ClipSlot/ClipSlot/Value/AudioClip"))
        if not tpl:
            notes.append(f"{stem}: track {t.find('./Name/EffectiveName').get('Value')!r} has no clip to copy settings from, skipped")
            continue
        tname = t.find("./Name/EffectiveName").get("Value")
        new, ev = V.clone_track(root, t, f"{tname} loops")
        sp = new.find("./DeviceChain/Mixer/Speaker/Manual")
        if sp is not None:
            sp.set("Value", "true")
        env = new.find("./AutomationEnvelopes/Envelopes")
        if env is not None:
            for e in list(env):
                env.remove(e)
        slots = [s.find("./ClipSlot/Value") for s in new.findall("./DeviceChain/MainSequencer/ClipSlotList/ClipSlot")]
        wm = 0 if is_drum(stem) else 6
        for row, f, name, beats in items:
            if row >= len(slots) or slots[row] is None:
                missed += 1
                continue
            slots[row].append(session_clip(tpl[0], f, name, beats, wm))
            placed += 1
        added.append(f"{tname} loops")
    if not added:
        notes.append("no stem matched a track: nothing to write")
        return False
    if missed:
        notes.append(f"{missed} clips did not fit: the new tracks have only as many scene rows as the set has; "
                     "add scenes in Live, save, and run again")
    notes.append(f"{placed} clips placed on {len(added)} new track(s); they play at the set's tempo ({tempo:g} BPM)")
    return B.finish(tree, src, dst, added=added)


# ---------------------------------------------------------------- takes mode
# `hypnomix loopset --takes SET.als`: long takes recorded to a click, on many tracks. Every take clip is rendered on
# its own (as Live plays it) on the set's bar grid, so no beat tracking is needed.
TAKE_MIN_BARS = 8          # shorter clips are not takes
TAKE_SR = 44100
SKIP_SLOT = 0.25           # share of instrument slots left silent in a combo
COMBO_SAMPLES = 300


def _tv(n, p):
    e = n.find(p) if n is not None else None
    return e.get("Value") if e is not None else None


def set_bpb(root):
    """Beats (quarter notes) per bar of the set's first scene; 4 when it can't be read."""
    sc = root.find(".//Scenes/Scene/TimeSignatureId")
    tid = sc.get("Value") if sc is not None else None
    for ts in root.iter("RemoteableTimeSignature"):
        if tid is not None and ts.get("Id") == tid:
            try:
                return max(1, int(round(int(_tv(ts, "./Numerator")) * 4 / int(_tv(ts, "./Denominator")))))
            except (TypeError, ValueError):
                break
    return 4


def gather_takes(root, als, bpb, warn):
    """{track Id: dict(name, el, takes)}: every enabled audio clip of at least 8 bars on the track's main lane
    and in its take lanes, oldest position first. A take = dict(n, s, e, el, src, lane)."""
    from hypnomix.session import render as R
    out = {}
    for t in root.find(".//Tracks"):
        if t.tag != "AudioTrack":
            continue
        name = _tv(t, "./Name/EffectiveName") or t.get("Id")
        found = [(c, "main") for c in t.findall("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events/AudioClip")]
        for li, lane in enumerate(t.findall(".//TakeLanes/TakeLanes/TakeLane"), 1):
            found += [(c, f"lane {li}") for c in lane.findall("./ClipAutomation/Events/AudioClip")]
        takes, seen = [], set()
        for c, lane in found:
            if _tv(c, "./Disabled") == "true":
                continue
            s, e = float(_tv(c, "./CurrentStart")), float(_tv(c, "./CurrentEnd"))
            if (e - s) / bpb < TAKE_MIN_BARS:
                continue
            src = R.clip_source(c, als, None)
            if not src.exists():
                warn.append(f"{name}: missing file {src.name}")
                continue
            key = (str(src), round(s, 3), round(e, 3), _tv(c, "./Loop/StartRelative"))
            if key in seen:
                continue
            seen.add(key)
            takes.append(dict(s=s, e=e, el=c, src=src, lane=lane))
        takes.sort(key=lambda x: (x["s"], x["e"]))
        for i, tk in enumerate(takes, 1):
            tk["n"] = i
        out[t.get("Id")] = dict(name=name, el=t, takes=takes)
    return out


def render_take(tk, spb, warn):
    """One take clip, mono float32 (n, 1), starting at its CurrentStart beat."""
    from hypnomix.session import render as R
    c = tk["el"]
    s, e = tk["s"], tk["e"]
    ls, le = float(_tv(c, "./Loop/LoopStart")), float(_tv(c, "./Loop/LoopEnd"))
    rel = float(_tv(c, "./Loop/StartRelative") or 0)
    loop_on = _tv(c, "./Loop/LoopOn") == "true"
    ck = R.cache_key(c, tk["src"], spb, TAKE_SR, 0, e - s, ls, le, rel, loop_on) if R.cache_enabled(None) else None
    seg = R.cache_get(ck)
    if seg is None:
        seg = R.clip_audio(c, tk["src"], spb, TAKE_SR, 0, warn, s, e, ls, le, rel, loop_on)
        if seg is None:
            return None
        seg = seg.astype(np.float32)
        if ck:
            R.cache_put(ck, seg)
    return np.asarray(seg, dtype=np.float32).reshape(-1, 1)


def chroma(y, sr):
    """12-bin chroma of a loop, mean over time, centred (so correlations are pitch-class profiles)."""
    m = np.asarray(y, dtype=np.float32).mean(1) if np.ndim(y) > 1 else np.asarray(y, dtype=np.float32)
    try:
        import librosa
        v = librosa.feature.chroma_stft(y=m, sr=sr, n_fft=4096, hop_length=2048).mean(1)
    except Exception:                                    # no librosa: fold FFT bins onto 12 pitch classes
        S = np.abs(np.fft.rfft(m[: 1 << 20] * np.hanning(min(len(m), 1 << 20)))) ** 2
        f = np.fft.rfftfreq(min(len(m), 1 << 20), 1.0 / sr)
        ok = (f > 55) & (f < 5000)
        pc = np.round(12 * np.log2(f[ok] / 440.0)).astype(int) % 12
        v = np.bincount(pc, weights=S[ok], minlength=12)
    v = np.asarray(v, dtype=float)
    return v - v.mean()


def chroma_corr(a, b):
    d = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / d) if d > 1e-9 else 0.0


def choose_takes(cands, top, sizes):
    """Best windows of one track, pooled over its takes: different takes and song positions first, none
    overlapping inside a take, window sizes spread. Ranked by score."""
    cands = sorted(cands, key=lambda c: (-c["score"], c["abs_bar"], -c["bars"]))
    size_cap = max(1, math.ceil(top / max(1, len(sizes))))
    picked = []
    for take_cap, pos_excl, scap in ((1, True, size_cap), (2, True, size_cap), (2, False, size_cap), (99, False, 99)):
        for c in cands:
            if len(picked) >= top:
                break
            if c in picked or sum(p["take"] == c["take"] for p in picked) >= take_cap or \
                    sum(p["bars"] == c["bars"] for p in picked) >= scap:
                continue
            clash = False
            for p in picked:
                if (p["take"] == c["take"] or pos_excl) and c["abs_bar"] < p["abs_bar"] + p["bars"] and p["abs_bar"] < c["abs_bar"] + c["bars"]:
                    clash = True
                    break
            if not clash:
                picked.append(c)
    picked.sort(key=lambda c: (-c["score"], c["abs_bar"]))
    for r, c in enumerate(picked, 1):
        c["rank"] = r
    return picked


def build_combos(tracks, n, seed, log=print):
    """tracks = [{name, loops: [{id, parent, bars, chroma}]}]. n combos: one loop per instrument (some left out),
    all the same bar length, harmony (mean pairwise chroma correlation) high, loops and song positions not
    reused while others are free, no two combos the same. Deterministic for a seed."""
    rng = np.random.default_rng(seed)
    cover = {}
    for ti, t in enumerate(tracks):
        for L in {l["bars"] for l in t["loops"]}:
            cover.setdefault(L, []).append(ti)
    need = 2 if len(tracks) >= 2 else 1
    lengths = sorted(L for L, ts in cover.items() if len(ts) >= need)
    if not lengths:
        return []
    usage, seen, combos = {}, set(), []
    for k in range(n):
        w = np.array([len(cover[L]) for L in lengths], float)
        L = lengths[int(rng.choice(len(lengths), p=w / w.sum()))]
        best = None
        for _ in range(COMBO_SAMPLES):
            slots = []
            for t in tracks:
                pool = [l for l in t["loops"] if l["bars"] == L]
                slots.append(None if (not pool or rng.random() < SKIP_SLOT) else pool[int(rng.integers(len(pool)))])
            have = [i for i, s_ in enumerate(slots) if s_]
            if len(have) < need:
                free = [i for i, t in enumerate(tracks) if i not in have and any(l["bars"] == L for l in t["loops"])]
                rng.shuffle(free)
                for i in free[: need - len(have)]:
                    pool = [l for l in tracks[i]["loops"] if l["bars"] == L]
                    slots[i] = pool[int(rng.integers(len(pool)))]
                have = [i for i, s_ in enumerate(slots) if s_]
            key = tuple(s_["id"] if s_ else None for s_ in slots)
            if key in seen or len(have) < need:
                continue
            ch = [slots[i]["chroma"] for i in have]
            pairs = [chroma_corr(ch[a], ch[b]) for a in range(len(ch)) for b in range(a + 1, len(ch))]
            harm = float(np.mean(pairs)) if pairs else 0.0
            reuse = float(np.mean([usage.get(slots[i]["parent"], 0) for i in have]))
            sc = harm - 0.15 * reuse + 0.02 * len(have)
            if best is None or sc > best[0]:
                best = (sc, slots, key, harm)
        if best is None:
            log(f"only {len(combos)} distinct combos exist with these loops (asked for {n})")
            break
        _, slots, key, harm = best
        seen.add(key)
        for s_ in slots:
            if s_:
                usage[s_["parent"]] = usage.get(s_["parent"], 0) + 1
        combos.append(dict(n=len(combos) + 1, bars=L, harmony=round(harm, 3),
                           slots={t["name"]: (s_["id"] if s_ else None) for t, s_ in zip(tracks, slots)}))
    return combos


def run_takes(als, tracks=None, per_track=6, bars=(2, 4, 8), variations=3, combos=16, seed=1, out=None,
              complexity="normal", log=print):
    """Everything but the set. Returns (result dict, out dir)."""
    from hypnomix.session import automation as aa, render as R
    import time
    t0 = time.time()
    als = Path(als)
    tree = aa.load(als)
    root = tree.getroot()
    warn = []
    tempo = B.set_tempo(root)
    spb = 60.0 / tempo
    bpb = set_bpb(root)
    if B.tempo_points(root):
        warn.append("the set has tempo automation: the loops are cut on a constant-tempo grid and may be off where the tempo moves")
    sizes = sorted(set(int(b) for b in bars))
    got = gather_takes(root, als, bpb, warn)
    if tracks:
        want = {x.strip().lower() for x in tracks}
        got = {i: g for i, g in got.items() if g["name"].strip().lower() in want}
        for x in want - {g["name"].strip().lower() for g in got.values()}:
            warn.append(f"--tracks: no audio track named {x!r}")
    got = {i: g for i, g in got.items() if g["takes"]}
    if not got:
        sys.exit("no audio track with a take of at least 8 bars (enabled clips on the main lane or in take lanes)")
    from hypnomix.core.paths import out_at
    od = out_at(out, "loopset", als.stem)
    log(f"{len(got)} tracks, tempo {tempo:g} BPM, {bpb} beats a bar")
    res_tracks = []
    for ti, (tid, g) in enumerate(got.items()):
        tt = time.time()
        cands, audio = [], {}
        for tk in g["takes"]:
            y = render_take(tk, spb, warn)
            if y is None or len(y) < TAKE_SR:
                continue
            first = int(math.ceil(tk["s"] / bpb - 1e-9))
            down = (first * bpb - tk["s"]) * spb
            an = analyse({"x": y}, TAKE_SR, tempo, down, bpb)
            audio[tk["n"]] = (y, an, first)
            br = an["bar_rms"]["x"]
            for c in score_windows(an, [L for L in sizes if L <= an["nbars"]]):
                i = c["bar"] - 1
                c.update(take=tk["n"], local_bar=c["bar"], abs_bar=first + c["bar"],
                         rms=float(np.sqrt(np.mean(br[i: i + c["bars"]] ** 2))))
                cands.append(c)
        if cands:
            med = float(np.median([c["rms"] for c in cands]))
            cands = [c for c in cands if c["rms"] >= SILENT and c["rms"] >= 0.2 * med]     # drop near-silent windows
        picks = choose_takes(cands, per_track, sizes)
        R._STRETCH.clear()
        tdir = clean(g["name"])
        (od / tdir).mkdir(parents=True, exist_ok=True)
        loops = []
        for c in picks:
            y, an, first = audio[c["take"]]
            cuts = cut_pick({"x": y}, TAKE_SR, an, c)
            c["bar"] = c["abs_bar"]
            cy = cuts["x"]
            base = f"take{c['take']} bar {c['abs_bar']} x{c['bars']}"
            f = od / tdir / (clean(f"{c['rank']:02d} {base}") + ".wav")
            sf.write(str(f), cy, TAKE_SR, subtype="PCM_24")
            c["files"] = {g["name"]: str(f)}
            ch = chroma(cy, TAKE_SR)
            loops.append(dict(id=f"{tid}:{c['rank']}", parent=f"{tid}:{c['rank']}", track=g["name"], rank=c["rank"],
                              take=c["take"], bars=c["bars"], bar=c["abs_bar"], kind="pick", name=base, file=str(f),
                              chroma=ch, score=c["score"]))
            c["variations"] = []
            if variations > 0:
                (od / tdir / "variations").mkdir(exist_ok=True)
                for v, kind, vy, info in make_variations(cy, TAKE_SR, c, bpb, variations, seed * 131 + ti, complexity):
                    vf = od / tdir / "variations" / (clean(f"{c['rank']:02d} {base} v{v} {kind}") + ".wav")
                    sf.write(str(vf), vy, TAKE_SR, subtype="PCM_24")
                    c["variations"].append(dict(n=v, kind=kind, file=str(vf)))
                    loops.append(dict(id=f"{tid}:{c['rank']}v{v}", parent=f"{tid}:{c['rank']}", track=g["name"],
                                      rank=c["rank"], take=c["take"], bars=c["bars"], bar=c["abs_bar"], kind=f"v{v} {kind}",
                                      name=f"{base} v{v} {kind}", file=str(vf), chroma=chroma(vy, TAKE_SR), score=c["score"]))
        del audio
        log(f"{g['name']}: {len(g['takes'])} takes, {len(cands)} candidate windows, {len(picks)} picks ({time.time() - tt:.0f} s)")
        res_tracks.append(dict(id=tid, name=g["name"], takes=len(g["takes"]), picks=picks, loops=loops))
    cb = build_combos([dict(name=t["name"], loops=t["loops"]) for t in res_tracks], combos, seed, log)
    for t in res_tracks:
        for l in t["loops"]:
            l["chroma"] = [round(float(x), 4) for x in l["chroma"]]
    res = dict(set=str(als), tempo=tempo, bpb=bpb, sample_rate=TAKE_SR, seed=seed, bars=sizes, tracks=res_tracks,
               combos=cb, warnings=sorted(set(warn)), seconds=round(time.time() - t0, 1))
    for t in res["tracks"]:
        for c in t["picks"]:
            for k in ("files",):
                c.pop(k, None)
    write_takes_report(od, res)
    return res, od


def write_takes_report(od, res):
    md = [f"# Loop set from takes: {Path(res['set']).name}", "",
          f"{res['tempo']:g} BPM, {res['bpb']} beats a bar, seed {res['seed']}, window sizes {res['bars']} bars. "
          "Measured, not heard: play each one and trust your ears over the score.", ""]
    for t in res["tracks"]:
        md += [f"## {t['name']} ({t['takes']} takes)", "", "| rank | take | song bar | bars | score | seam | flags | variations |",
               "|---|---|---|---|---|---|---|---|"]
        for c in t["picks"]:
            v = ", ".join(f"v{x['n']} {x['kind']}" for x in c["variations"]) or "-"
            md.append(f"| {c['rank']} | {c['take']} | {c['abs_bar']} | {c['bars']} | {c['score']:.2f} | {c['seam']:.2f} | "
                      f"{', '.join(c['flags']) or '-'} | {v} |")
        md.append("")
    names = {l["id"]: f"{l['track']} {l['name']}" for t in res["tracks"] for l in t["loops"]}
    md += ["## Combos", "", "Each combo plays one loop per instrument, all the same length; harmony = how well the loops' pitch "
           "content agrees (1 is best).", ""]
    for c in res["combos"]:
        parts = ", ".join(f"{k}: {names[v]}" for k, v in c["slots"].items() if v)
        md.append(f"- Combo {c['n']} ({c['bars']} bars, harmony {c['harmony']:.2f}): {parts}")
    if res["warnings"]:
        md += ["", "## Warnings", ""] + [f"- {w}" for w in res["warnings"]]
    (od / "LOOPSET.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (od / "loopset.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


def _trailing_empty(root):
    """How many scenes at the end of the set are empty (no name, no clip on any track)."""
    scenes = list(root.find(".//Scenes"))
    lists = [l for l in root.iter("ClipSlotList") if len(l)]
    n = 0
    for i in range(len(scenes) - 1, -1, -1):
        if _tv(scenes[i], "./Name") or any(i < len(l) and l[i].find("./ClipSlot/Value/AudioClip") is not None or
                                           i < len(l) and l[i].find("./ClipSlot/Value/MidiClip") is not None for l in lists):
            break
        n += 1
    return n


def _grow_scenes(root, total):
    """Make the set have `total` scenes and every clip slot list one slot per scene. Returns the old scene count."""
    scenes = root.find(".//Scenes")
    old = len(scenes)
    tpl = scenes[0]
    nxt = max(int(s.get("Id")) for s in scenes) + 1
    for i in range(old, total):
        sc = copy.deepcopy(tpl)
        sc.set("Id", str(nxt)); nxt += 1
        B.set_val(sc, "./Name", "")
        B.set_val(sc, "./Annotation", "")
        scenes.append(sc)
    lists = [l for l in root.iter("ClipSlotList") if len(l)]
    for lst in lists:
        while len(lst) < total:
            slot = copy.deepcopy(lst[-1])
            slot.set("Id", str(len(lst)))
            for val in slot.findall("./ClipSlot/Value"):
                for ch in list(val):
                    val.remove(ch)
            lst.append(slot)
    return old


def apply_takes(src, dst, res, notes):
    """New set: a "<track> loops" track per instrument and new scenes: one row per combo, then each instrument's
    picks and variations. The source set is never touched."""
    from hypnomix.session import automation as aa, variations as V
    tree = aa.load(src); root = tree.getroot()
    tracks = {t.get("Id"): t for t in root.find(".//Tracks") if t.tag == "AudioTrack"}
    bpb = res["bpb"]
    order = [t for t in res["tracks"] if t["id"] in tracks]
    by_id = {l["id"]: l for t in order for l in t["loops"]}
    rows = [(f"Combo {c['n']}", {k: by_id[v] for k, v in c["slots"].items() if v}) for c in res["combos"]]
    ranks = sorted({l["rank"] for t in order for l in t["loops"]})
    for r in ranks:                                  # shared rows: every instrument's rank-r pick, then its variations
        for kind in ["pick"] + sorted({l["kind"].split()[0] for t in order for l in t["loops"] if l["rank"] == r and l["kind"] != "pick"},
                                      key=lambda x: int(x[1:])):
            items = {t["name"]: l for t in order for l in t["loops"]
                     if l["rank"] == r and (l["kind"] == "pick" if kind == "pick" else l["kind"].split()[0] == kind)}
            if items:
                rows.append((f"Pick {r}" + ("" if kind == "pick" else f" {kind}"), items))
    added, new_of, tpl_of = [], {}, {}
    for t in order:
        el = tracks[t["id"]]
        tpl = B.clips_of(el) or el.findall(".//TakeLanes//AudioClip") or \
            el.findall("./DeviceChain/MainSequencer/ClipSlotList/ClipSlot/ClipSlot/Value/AudioClip")
        if not tpl:
            notes.append(f"{t['name']}: no clip to copy settings from, skipped")
            continue
        tpl_of[t["name"]] = tpl[0]
        new, _ = V.clone_track(root, el, f"{t['name']} loops")
        sp = new.find("./DeviceChain/Mixer/Speaker/Manual")
        if sp is not None:
            sp.set("Value", "true")
        env = new.find("./AutomationEnvelopes/Envelopes")
        if env is not None:
            for e in list(env):
                env.remove(e)
        new_of[t["name"]] = new
        added.append(f"{t['name']} loops")
    if not added:
        notes.append("no track could be used: nothing to write")
        return False
    n_sc = len(root.find(".//Scenes"))
    free = _trailing_empty(root)
    old = n_sc - min(free, len(rows))                 # reuse the set's empty rows at the end, append only the shortfall
    _grow_scenes(root, old + len(rows))
    scenes = list(root.find(".//Scenes"))
    for r, (label, items) in enumerate(rows):
        B.set_val(scenes[old + r], "./Name", label)
    placed = 0
    for r, (label, items) in enumerate(rows):
        for tname, l in items.items():
            if tname not in new_of:
                continue
            slots = [s.find("./ClipSlot/Value") for s in new_of[tname].findall("./DeviceChain/MainSequencer/ClipSlotList/ClipSlot")]
            slots[old + r].append(session_clip(tpl_of[tname], Path(l["file"]), l["name"], l["bars"] * bpb, 6))
            placed += 1
    notes.append(f"{len(rows)} rows used from scene {old + 1} ({n_sc - old} empty ones reused, {len(scenes) - n_sc} added): "
                 f"{len(res['combos'])} combos, then Pick 1.. with their variations; {placed} clips on {len(added)} new track(s), warped at the set's tempo ({res['tempo']:g} BPM)")
    return B.finish(tree, src, dst, added=added)


# ---------------------------------------------------------------- main
def run(stems_dir, bpm=None, downbeat=None, bars=(1, 2, 4, 8), top=6, variations=4, anchor=None,
        complexity="normal", out=None, seed=1, bpb=4, log=print):
    """Everything but the set. Returns (result dict, out dir)."""
    stems, sr = load_stems(stems_dir)
    drums = pick_drums(stems)
    if anchor:
        k = find_stem(stems, anchor)
        if k is None:
            sys.exit(f"no stem named {anchor!r}: " + ", ".join(stems))
        anchor = k
    else:
        anchor = drums or max(stems, key=lambda k: rms(stems[k]))
    bpm_, down, how = grid(stems, sr, bpm, downbeat, bpb, drums)
    bar = 60.0 / bpm_ * bpb
    if down >= bar:                                       # bar 1 is the first bar line from the start of the stems
        down -= bar * int(down // bar)
    log(f"{len(stems)} stems at {sr} Hz; tempo used: {bpm_:.2f} BPM, first bar line at {down:.3f} s ({how}); anchor: {anchor}")
    an = analyse(stems, sr, bpm_, down, bpb)
    cands = score_windows(an, sorted(set(bars)))
    picks = choose(cands, top)
    if not picks:
        sys.exit("no loop candidates: too few full bars, or the stems are mostly silent. Check the tempo "
                 "(--bpm, --downbeat) and the window sizes (--bars).")
    from hypnomix.core.paths import out_at
    od = out_at(out, "loopset", Path(stems_dir).name)
    files = {}
    for c in picks:
        cuts = cut_pick(stems, sr, an, c, anchor)
        folder = clean(f"{c['rank']:02d} {c['section']} {c['bars']}b")
        (od / folder).mkdir(parents=True, exist_ok=True)
        c["folder"], c["files"] = folder, {}
        for k, y in cuts.items():
            p = od / folder / (clean(k) + ".wav")
            sf.write(str(p), y, sr, subtype="PCM_24")
            c["files"][k] = str(p)
        c["variations"] = []
        if variations > 0:
            (od / folder / "variations").mkdir(exist_ok=True)
            for v, kind, y, info in make_variations(cuts[anchor], sr, c, bpb, variations, seed, complexity):
                p = od / folder / "variations" / (clean(f"{anchor} v{v} {kind}") + ".wav")
                sf.write(str(p), y, sr, subtype="PCM_24")
                c["variations"].append(dict(n=v, kind=kind, file=str(p), **info))
        files[c["rank"]] = c
    res = dict(stems_dir=str(stems_dir), sample_rate=sr, bpm=round(bpm_, 3), downbeat=round(down, 4), bpb=bpb,
               grid=how, anchor=anchor, complexity=complexity, seed=seed, stems=list(stems), picks=picks)
    write_report(od, res)
    return res, od


def write_report(od, res):
    md = [f"# Loop set: {Path(res['stems_dir']).name}", "",
          f"Tempo used {res['bpm']:.2f} BPM, first bar line at {res['downbeat']:.3f} s ({res['grid']}). "
          f"Anchor stem: {res['anchor']}; variations {res['complexity']}, seed {res['seed']}.",
          "Measured, not heard: play each one and trust your ears over the score.", "",
          "| rank | bars | start bar | section | score | seam | quality | flags | variations |",
          "|---|---|---|---|---|---|---|---|---|"]
    for c in res["picks"]:
        v = ", ".join(f"v{x['n']} {x['kind']}" for x in c["variations"]) or "-"
        md.append(f"| {c['rank']} | {c['bars']} | {c['bar']} | {c['section']} | {c['score']:.2f} | {c['seam']:.2f} | "
                  f"{c['quality']:.2f} | {', '.join(c['flags']) or '-'} | {v} |")
    md += ["", "Flags: `no_transient` = no attack near a bar line, the bar line is kept; `length_off` = the cut is more than "
           "25 ms off the grid length (Live stretches it); `tail_rings` = the end rings loudly."]
    (od / "LOOPSET.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (od / "loopset.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


def _bars_arg(vals, default):
    out = []
    for x in (vals or default):
        out += [int(p) for p in str(x).split(",") if p.strip()]
    return sorted(set(out))


def main_takes(a):
    if not Path(a.takes).is_file():
        sys.exit(f"no such set: {a.takes}")
    if a.apply and Path(a.apply).exists():
        sys.exit(f"{Path(a.apply).name} already exists: nothing is ever overwritten, give a new name")
    out = a.out or str(Path(a.takes).parent / f"{Path(a.takes).stem} loopset")
    tracks = [x for x in (a.tracks or "").split(",") if x.strip()] or None
    res, od = run_takes(a.takes, tracks, a.per_track, _bars_arg(a.bars, ["2,4,8"]),
                        3 if a.variations is None else a.variations, a.combos, a.seed, out, a.complexity)
    for t in res["tracks"]:
        print(f"{t['name']:<22} {t['takes']:>3} takes  " + ", ".join(f"t{c['take']} bar {c['abs_bar']} x{c['bars']}" for c in t["picks"]))
    print(f"{len(res['combos'])} combos; {res['seconds']:.0f} s")
    for w in res["warnings"]:
        print("  !", w)
    print(f"\n→ {od}")
    if a.apply:
        notes = []
        ok = apply_takes(Path(a.takes), Path(a.apply), res, notes)
        for n in notes:
            print(" ", n)
        if not ok:
            sys.exit(1)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix loopset", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stems", nargs="?", help="folder of exported stems")
    ap.add_argument("--bpm", type=A.number(20, 400)); ap.add_argument("--downbeat", type=float, help="seconds where bar 1 starts")
    ap.add_argument("--bpb", type=int, default=4, help="beats per bar")
    ap.add_argument("--bars", nargs="+", default=None, help="window sizes in bars (stems: 1 2 4 8; takes: 2,4,8)")
    ap.add_argument("--top", type=int, default=6)
    ap.add_argument("--variations", type=int, default=None, help="variations per loop (stems: 4, takes: 3)"); ap.add_argument("--anchor")
    ap.add_argument("--complexity", choices=sorted(CHANGES), default="normal")
    ap.add_argument("--seed", type=int, default=1); ap.add_argument("--out")
    ap.add_argument("--set", metavar="SET.als"); ap.add_argument("--apply", metavar="NEW.als")
    ap.add_argument("--takes", metavar="SET.als", help="takes mode: loops from the long take clips of a Live set")
    ap.add_argument("--tracks", help='takes mode: only these tracks, "name,name"')
    ap.add_argument("--per-track", type=int, default=6, help="takes mode: loops per track")
    ap.add_argument("--combos", type=int, default=16, help="takes mode: combinations of instruments")
    a = ap.parse_args(argv)
    if a.takes:
        return main_takes(a)
    if not a.stems:
        ap.error("give a folder of stems, or --takes SET.als")
    a.bars = _bars_arg(a.bars, ["1", "2", "4", "8"])
    a.variations = 4 if a.variations is None else a.variations
    if bool(a.set) != bool(a.apply):
        sys.exit("--set SET.als and --apply NEW.als go together")
    if not Path(a.stems).is_dir():
        sys.exit(f"{a.stems} is not a folder of stems")
    if a.apply:
        if not Path(a.set).is_file():
            sys.exit(f"no such set: {a.set}")
        if Path(a.apply).exists():
            sys.exit(f"{Path(a.apply).name} already exists: nothing is ever overwritten, give a new name")
    res, od = run(a.stems, a.bpm, a.downbeat, a.bars, a.top, a.variations, a.anchor, a.complexity, a.out, a.seed, a.bpb)
    print(f"\n{'rank':>4} {'bars':>4} {'start bar':>9} {'section':>7} {'score':>6} {'seam':>5} {'quality':>7}  flags")
    for c in res["picks"]:
        print(f"{c['rank']:>4} {c['bars']:>4} {c['bar']:>9} {c['section']:>7} {c['score']:>6.2f} {c['seam']:>5.2f} "
              f"{c['quality']:>7.2f}  {', '.join(c['flags']) or '-'}")
    print(f"\n→ {od}")
    if not a.apply:
        return 0
    P = len(res["picks"])
    plan = {}
    for c in res["picks"]:
        for k, f in c["files"].items():
            plan.setdefault(k, []).append((c["rank"] - 1, Path(f), f"Loop {c['rank']} {c['section']} {c['bars']} bars",
                                           c["bars"] * res["bpb"]))
        for v in c["variations"]:
            plan.setdefault(res["anchor"], []).append((P + (c["rank"] - 1) * max(1, len(c["variations"])) + v["n"] - 1,
                                                       Path(v["file"]), f"Loop {c['rank']} v{v['n']} {v['kind']}", c["bars"] * res["bpb"]))
    notes = []
    ok = apply_set(Path(a.set), Path(a.apply), plan, res["bpb"], notes)
    for n in notes:
        print(" ", n)
    if not ok:
        sys.exit(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
