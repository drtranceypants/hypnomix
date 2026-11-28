#!/usr/bin/env python3
"""Loops mode: pick the best sections across stems to loop, align their edges, make variations, put them in
Session slots of a new set.

  hypnomix loopset STEMS_DIR [--bpm B] [--downbeat S] [--bars 1 2 4 8] [--top 6] [--variations 4]
                   [--anchor NAME] [--complexity subtle|normal|complex] [--out DIR] [--seed N]
  hypnomix loopset STEMS_DIR --set SET.als --apply NEW.als

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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix loopset", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stems", help="folder of exported stems")
    ap.add_argument("--bpm", type=A.number(20, 400)); ap.add_argument("--downbeat", type=float, help="seconds where bar 1 starts")
    ap.add_argument("--bpb", type=int, default=4, help="beats per bar")
    ap.add_argument("--bars", type=int, nargs="+", default=[1, 2, 4, 8]); ap.add_argument("--top", type=int, default=6)
    ap.add_argument("--variations", type=int, default=4); ap.add_argument("--anchor")
    ap.add_argument("--complexity", choices=sorted(CHANGES), default="normal")
    ap.add_argument("--seed", type=int, default=1); ap.add_argument("--out")
    ap.add_argument("--set", metavar="SET.als"); ap.add_argument("--apply", metavar="NEW.als")
    a = ap.parse_args(argv)
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
