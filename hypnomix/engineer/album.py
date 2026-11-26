#!/usr/bin/env python3
"""An EP or album as a whole: how the songs sit next to each other. Report first; nothing is changed.

`qc` checks one file, `tonal` builds one target. This puts the songs side by side and says, in plain words,
which one sits apart in level, which is brighter, darker or boomier than the rest and by how much, what the gap
between each pair of songs could be, and (if you ask) a couple of orders to try. The report is ALBUM.md.

Usage:
    hypnomix album SONG1.wav SONG2.wav ... [--order a,b,c] [--target LUFS] [--plan [SCAN_DIR]] [--out DIR]
    hypnomix album FOLDER                      every audio file in the folder, in name order

Per song it measures: integrated loudness, the loudest section (the highest short-term loudness, 3 s windows),
true peak, the tonal curve in 8 bands against the median of the OTHER songs, stereo width (side against mid),
silence at the head and tail and how the song ends and starts, key and tempo.

Across the album, in plain words:
  level     which songs sit apart. A quiet ballad is allowed to be quieter, so two readings are taken: the whole
            song and its loudest section. --reading both (default) calls a song apart only when BOTH are outside
            --tolerance (2 LU); a song that is lower only as a whole (quiet verses) is shown, not touched.
            --reading whole | loudest uses just one. --target LUFS compares the whole-song reading with a fixed
            figure (the loudest section then follows at the album's usual distance above it); --anchor SONG
            matches the others to that song; --keep-quiet a,b leaves songs you want quieter alone.
  tone      which songs are brighter, darker, boomier, thinner or boxier than the rest, band by band, and by
            how many dB (more than --tone-tolerance, 1.5 dB).
  width     songs clearly wider or narrower than the rest (more than --width-tolerance, 3 dB).
  gaps      for each transition in --order (default: the order given), a gap suggested from how the first song's
            tail decays and how the next one starts: --gap-style tight|normal|roomy, or --gap SECONDS for one
            figure. --head sets the lead-in each song keeps (0.1 s), --last-tail the end of the last song (2 s).
  orders    --suggest-order lists one or two orders (by energy arc, and by key relation) as OPTIONS. They are
            never applied.

Proposals (a gain trim, a gentle tonal tilt, trimmed or padded silence) are only listed in ALBUM.md until you add
--plan: then each becomes a finding in a scan folder, you approve them one by one (`hypnomix review`, `ab` to
hear each one level-matched), and `hypnomix fix DIR --approved` writes the approved ones into NEW files in
DIR/fixed/. Nothing is applied by this report. Tilt: --tilt-amount 50 (percent of the gap closed), --max-tilt-db 2.
A raise stops at --ceiling (-1 dBTP): what is left needs a limiter (`master`). Several approved moves on one song
are chained: the file with the highest step number is the finished one.

What `fix` and `ab` run for an approved move (you will not need these by hand):
    hypnomix album --render gain SONG.wav --db -1.5 --out DIR
    hypnomix album --render tilt SONG.wav --tilt low:-1.0,high:+0.8 --out DIR      (level kept, true peak safe)
    hypnomix album --render ends SONG.wav --head 0.1 --tail 2.0 --out DIR          (only silence is touched)

Measured, not heard: the gaps and the order are a taste call. Listen to each transition before you decide.
"""
import argparse, itertools, json, math, os, re, sys, warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
from hypnomix.core import dsp  # noqa: E402
from hypnomix.core.paths import out_at  # noqa: E402

SILENCE = 10 ** (-60 / 20)                      # the same "silence" as `qc`: under -60 dBFS
LOW_SHELF_HZ, HIGH_SHELF_HZ = 160.0, 5000.0
GROUPS = {"sub": (0, 1), "low": (1, 3), "lowmid": (3, 4), "mid": (4, 5), "uppermid": (5, 6), "high": (6, 8)}   # indexes into tonal.EIGHT
BASE_GAP = {"abrupt": 2.0, "short": 1.8, "ring-out": 1.5, "long fade": 1.0}
STYLE = {"tight": 0.7, "normal": 1.0, "roomy": 1.4}
KEY_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


# ---------------------------------------------------------------- measuring
def short_term(y, sr, win=3.0, hop=1.0):
    """Short-term loudness (LUFS) of every `win` s window, `hop` s apart. A song under `win` gives one value."""
    import pyloudnorm as pyln
    meter = pyln.Meter(sr)
    n, h = int(win * sr), int(hop * sr)
    if len(y) <= n:
        v = dsp.lufs(y, sr)
        return [v]
    out = []
    for i in range(0, len(y) - n + 1, h):
        v = meter.integrated_loudness(y[i:i + n])
        out.append(float(v) if np.isfinite(v) else -70.0)
    return out


def ends(y, sr):
    """Silence at the head and tail, and how the song stops and starts (all measured, none of it a verdict)."""
    peak = np.max(np.abs(y), axis=1)
    on = np.flatnonzero(peak > SILENCE)
    if not len(on):
        return dict(head_s=len(y) / sr, tail_s=0.0, tail_kind="silent", decay_s=0.0, start_kind="silent",
                    start_rel_db=None, loud_db=None)
    head, tail = on[0] / sr, (len(y) - 1 - on[-1]) / sr
    blk = max(1, int(0.05 * sr))
    env = dsp.block_rms_db(y, sr, 0.05)
    audible = env[env > -60]
    loud_db = float(np.percentile(audible, 90)) if len(audible) else -60.0
    strong = np.flatnonzero(env > loud_db - 6)
    last_strong_t = (strong[-1] + 1) * blk / sr if len(strong) else on[-1] / sr
    decay = max(0.0, on[-1] / sr - last_strong_t)
    last = y[max(0, on[-1] + 1 - blk):on[-1] + 1]                     # the 50 ms that end at the last audible sample
    final_level = float(10 * np.log10(np.mean(last ** 2) + 1e-20))
    if decay < 0.3 and final_level > loud_db - 25:
        kind = "abrupt"
    elif decay < 1.0:
        kind = "short"
    elif decay < 3.0:
        kind = "ring-out"
    else:
        kind = "long fade"
    i0 = int(head * sr)
    first = env[min(len(env) - 1, i0 // blk): min(len(env), i0 // blk + 20)]      # the first second of sound
    rel = float(np.mean(first) - loud_db) if len(first) else 0.0
    start = "full" if rel >= -6 else "soft" if rel <= -15 else "medium"
    return dict(head_s=round(float(head), 3), tail_s=round(float(tail), 3), tail_kind=kind,
                decay_s=round(float(decay), 2), start_kind=start, start_rel_db=round(rel, 1), loud_db=round(loud_db, 1))


def detect_key(path):
    """(name, sure, runner_up) the way `hypnomix key --audio` decides it; (None, False, None) when it cannot."""
    try:
        from hypnomix.ears import key as K
        pc, bass, final = K.audio_evidence(str(path))
        total = K.key_scores(pc)
        tonic = K.tonic_vote(bass, final)
        if tonic.sum() > 0:
            tn = tonic / tonic.sum()
            for i in range(24):
                total[i] += 1.5 * tn[i % 12]
        order = np.argsort(-total)
        best, second = int(order[0]), int(order[1])
        span = total[order[0]] - np.median(total) + 1e-9
        margin = float((total[best] - total[second]) / span)
        return K.kname(best), margin >= 0.12, K.kname(second)
    except Exception:
        return None, False, None


def detect_tempo(path):
    try:
        import librosa
        y, _ = librosa.load(str(path), sr=22050, mono=True)
        t, _ = librosa.beat.beat_track(y=y, sr=22050)
        return round(float(np.atleast_1d(t)[0]), 1)
    except Exception:
        return None


def analyse(path, quick=False):
    """Everything the report says about one song, as plain numbers."""
    from hypnomix.ears import tonal
    path = Path(path)
    y, sr = dsp.load(path)
    if not len(y) or float(np.max(np.abs(y))) < 1e-6:
        raise ValueError("the file is silent")
    y = dsp.stereo(y) if y.shape[1] >= 2 else y
    st = short_term(y, sr)
    whole = dsp.lufs(y, sr)
    mono = y.shape[1] == 1
    if mono:
        width = None
    else:
        mid, side = (y[:, 0] + y[:, 1]) / 2, (y[:, 0] - y[:, 1]) / 2
        width = float(10 * np.log10((side ** 2).mean() / ((mid ** 2).mean() + 1e-12) + 1e-12))
    key, sure, runner = (None, False, None) if quick else detect_key(path)
    return dict(name=path.stem, file=str(path.resolve()), sr=int(sr), channels=int(y.shape[1]),
                duration_s=round(len(y) / sr, 2), whole_lufs=round(whole, 2), loudest_lufs=round(max(st), 2),
                true_peak=round(dsp.true_peak(y, sr), 2), curve=[round(float(v), 2) for v in tonal.measure(y, sr)["eight"]],
                width_db=None if width is None else round(width, 1), mono=mono, **ends(y, sr),
                key=key, key_sure=bool(sure), key_runner_up=runner, tempo=None if quick else detect_tempo(path))


# ---------------------------------------------------------------- words about two songs
def key_pos(name):
    """Place on the circle of fifths, a minor key sharing the place of its relative major."""
    if not name:
        return None
    root, mode = name.split()
    r = KEY_NAMES.index(root)
    if mode == "minor":
        r = (r + 3) % 12
    return (r * 7) % 12


def key_distance(a, b):
    pa, pb = key_pos(a), key_pos(b)
    if pa is None or pb is None:
        return None
    d = abs(pa - pb)
    return min(d, 12 - d)


def key_words(d):
    return {0: "the same key, or its relative", 1: "a fifth apart: close"}.get(d, "two steps round the circle of fifths: it works" if d == 2
                                                                                  else "far apart: an obvious change of key")


def tempo_words(a, b):
    if not a or not b:
        return None
    r = b / a
    if abs(r - 1) <= 0.03:
        return "the same pace"
    if abs(r - 2) <= 0.06 or abs(r - 0.5) <= 0.03:
        return f"{a:g} then {b:g} BPM: half or double time (the tempo finder confuses the two, so check by ear)"
    return f"{a:g} then {b:g} BPM ({(r - 1) * 100:+.0f}%)"


def median_of_others(vals, i):
    rest = [v for j, v in enumerate(vals) if j != i and v is not None]
    return float(np.median(rest)) if rest else None


def fmt_t(s):
    return f"{s:.1f} s" if s < 100 else f"{int(s // 60)}:{s % 60:04.1f}"


def short_name(s, n=26):
    return s if len(s) <= n else s[:n - 1] + "…"


# ---------------------------------------------------------------- comparing
def compare(songs, o):
    """Level, tone and width of every song against the others (or the anchor / the target)."""
    n = len(songs)
    anchor = next((i for i, s in enumerate(songs) if s["name"] == o["anchor"]), None) if o.get("anchor") else None
    wh = [s["whole_lufs"] for s in songs]
    lo = [s["loudest_lufs"] for s in songs]
    lift = float(np.median([l - w for l, w in zip(lo, wh)]))          # how far above its whole a loudest section usually sits
    rows = []
    quiet = {q.lower() for q in o.get("keep_quiet", [])}
    for i, s in enumerate(songs):
        if anchor is not None:
            ref_w, ref_l, how = wh[anchor], lo[anchor], f"the anchor, {songs[anchor]['name']}"
        elif o.get("target") is not None:
            ref_w, ref_l, how = o["target"], o["target"] + lift, f"the {o['target']:g} LUFS target"
        elif n == 2:
            # the "median of the others" would be the other song itself: both would jump the whole gap and swap places
            ref_w, ref_l, how = float(np.mean(wh)), float(np.mean(lo)), "the midpoint of the two songs"
        else:
            ref_w, ref_l, how = median_of_others(wh, i), median_of_others(lo, i), "the median of the other songs"
        dw, dl = wh[i] - ref_w, lo[i] - ref_l
        tol, reading = o["tolerance"], o["reading"]
        if how.startswith("the midpoint"):
            tol = tol / 2                    # each song is half the gap from the midpoint: the same test on the whole gap
        off_w, off_l = abs(dw) > tol, abs(dl) > tol
        if anchor == i:
            state = "anchor"
        elif reading == "whole":
            state = "apart" if off_w else "in line"
        elif reading == "loudest":
            state = "apart" if off_l else "in line"
        else:
            both = off_w and off_l and (dw > 0) == (dl > 0)
            state = "apart" if both else "whole only" if off_w and not off_l else "loudest only" if off_l and not off_w else "in line"
        if s["name"].lower() in quiet:
            state = "kept quiet" if state not in ("in line", "anchor") else state
        rows.append(dict(name=s["name"], ref_whole=ref_w, ref_loudest=ref_l, ref_how=how, d_whole=dw, d_loudest=dl,
                         state=state))
    # tone, band by band, against the median of the other songs (or the anchor's curve)
    curves = np.array([s["curve"] for s in songs])
    from hypnomix.ears import tonal
    bands = [b[0] for b in tonal.EIGHT]
    for i, r in enumerate(rows):
        if anchor is not None:
            ref = curves[anchor]
        elif n > 1:
            ref = np.median(np.delete(curves, i, axis=0), axis=0)
        else:
            ref = curves[i]
        dev = curves[i] - ref
        grp = {k: group_dev(dev[a:b]) for k, (a, b) in GROUPS.items()}
        r["dev"] = [round(float(v), 1) for v in dev]
        r["groups"] = {k: round(v, 1) for k, v in grp.items()}
        r["tone_words"] = tone_words(grp, o["tone_tolerance"])
    ws = [s["width_db"] for s in songs]
    for i, r in enumerate(rows):
        ref = ws[anchor] if anchor is not None else median_of_others(ws, i)
        r["width_dev"] = None if ws[i] is None or ref is None else round(ws[i] - ref, 1)
        r["width_words"] = ("mono" if songs[i]["mono"] else
                            "" if r["width_dev"] is None or abs(r["width_dev"]) <= o["width_tolerance"] else
                            f"{'wider' if r['width_dev'] > 0 else 'narrower'} than the others by {abs(r['width_dev']):.1f} dB")
    return dict(rows=rows, bands=bands, lift=lift, anchor=anchor)


def group_dev(vals):
    """One number for a group of bands: the band that is furthest from the others, so a boost that starts at
    6 kHz is not half-hidden by the 4 to 8 kHz band (a mean would dilute it)."""
    vals = np.asarray(vals, dtype=float)
    return float(vals[int(np.argmax(np.abs(vals)))])


def tone_words(grp, tol):
    out = []
    sub = grp.get("sub", 0.0)
    if abs(sub) > 2 * tol:                       # the sub is the shakiest band: it needs a bigger gap to count
        out.append(("sub", f"{'more' if sub > 0 else 'less'} sub-bass (under 60 Hz) by {abs(sub):.1f} dB"))
    for key, up, down in (("low", "boomier", "thinner in the low end"), ("lowmid", "boxier (more low-mid)", "less low-mid body"),
                          ("uppermid", "more forward in the upper mids", "softer in the upper mids"),
                          ("mid", "more midrange (500 Hz to 2 kHz)", "scooped in the mids"),
                          ("high", "brighter", "darker")):
        v = grp[key]
        if abs(v) > tol:
            out.append((key, f"{up if v > 0 else down} by {abs(v):.1f} dB"))
    return out


# ---------------------------------------------------------------- transitions
def gap_for(a, b, o):
    """Suggested silence between the last sound of `a` and the first of `b`, with the reasons in words."""
    if o.get("gap") is not None:
        return float(o["gap"]), ["fixed by --gap"]
    why = []
    g = BASE_GAP.get(a["tail_kind"], 1.8)
    tail_txt = {"abrupt": f"{a['name']} stops abruptly, so it needs room to land",
                "short": f"{a['name']} ends with a short fade ({a['decay_s']:g} s)",
                "ring-out": f"{a['name']} rings out for about {a['decay_s']:g} s, which already carries part of the gap",
                "long fade": f"{a['name']} fades for about {a['decay_s']:g} s, so little silence is needed on top"}.get(a["tail_kind"], "")
    if tail_txt:
        why.append(tail_txt)
    if b["start_kind"] == "full":
        g += 0.3
        why.append(f"{b['name']} starts at full strength: a little more room before it")
    elif b["start_kind"] == "soft":
        g = max(0.5, g - 0.3)
        why.append(f"{b['name']} starts softly and comes in on its own")
    step = b["loudest_lufs"] - a["loudest_lufs"]
    if step <= -4:
        g += 0.3
        why.append(f"{b['name']} is {abs(step):.1f} LU quieter at its loudest: a breath to settle")
    d = key_distance(a["key"], b["key"])
    if d is not None and d >= 4:
        g += 0.2
        why.append("the keys are far apart: a clean break helps")
    g *= STYLE[o["gap_style"]]
    return round(max(0.4, g) * 10) / 10, why


def transitions(songs, order, o):
    rows = []
    for k in range(len(order) - 1):
        a, b = songs[order[k]], songs[order[k + 1]]
        gap, why = gap_for(a, b, o)
        have = a["tail_s"] + b["head_s"]
        step = b["loudest_lufs"] - a["loudest_lufs"]
        rows.append(dict(a=a["name"], b=b["name"], gap=gap, have=round(have, 2), why=why, level_step=round(step, 1),
                         key=key_words(key_distance(a["key"], b["key"])) if key_distance(a["key"], b["key"]) is not None else None,
                         tempo=tempo_words(a["tempo"], b["tempo"])))
    return rows


# ---------------------------------------------------------------- order options
def energy(songs):
    """One number per song: how much it pushes. Loudest section, tempo and brightness, each as z-scores."""
    def z(v):
        v = np.array([x if x is not None else np.nan for x in v], float)
        if np.all(np.isnan(v)):
            return np.zeros(len(v))
        m, s = np.nanmean(v), np.nanstd(v)
        out = (v - m) / s if s > 1e-9 else np.zeros(len(v))
        return np.nan_to_num(out)
    bright = [float(np.mean(s["curve"][6:8])) for s in songs]
    return z([s["loudest_lufs"] for s in songs]) + 0.5 * z([s["tempo"] for s in songs]) + 0.5 * z(bright)


def arc_profile(n):
    xs = np.linspace(0, 1, n) if n > 1 else np.array([0.0])
    return np.where(xs <= 0.65, 0.55 + 0.45 * xs / 0.65, 1.0 - 0.8 * (xs - 0.65) / 0.35)


def energy_ranks(songs):
    e = energy(songs)
    n = len(songs)
    ranks = np.empty(n)
    ranks[np.argsort(e)] = np.linspace(0, 1, n) if n > 1 else [0.5]
    return e, ranks


def suggest_orders(songs):
    """Up to two orderings as options: by energy arc, and by key relation (the arc breaks ties)."""
    from scipy.optimize import linear_sum_assignment
    n = len(songs)
    if n < 3:
        return []
    e, ranks = energy_ranks(songs)
    prof = arc_profile(n)
    cost = np.abs(ranks[:, None] - prof[None, :])
    rows, cols = linear_sum_assignment(cost)
    by_arc = [int(r) for r in rows[np.argsort(cols)]]
    out = [dict(label="by energy arc", order=by_arc,
                why="opens fairly strong, builds to the peak about two thirds in, and settles toward the end; "
                    "energy = loudest section, tempo and brightness")]
    if all(s["key"] for s in songs):
        D = np.zeros((n, n))
        for i in range(n):
            for j in range(n):
                D[i, j] = key_distance(songs[i]["key"], songs[j]["key"]) or 0
        def total(p):
            return sum(D[p[k], p[k + 1]] for k in range(n - 1)) + 0.5 * sum(abs(ranks[p[k]] - prof[k]) for k in range(n))
        if n <= 8:
            best = min(itertools.permutations(range(n)), key=total)
        else:
            best, bt = None, 1e9
            for s0 in range(n):
                p, left = [s0], set(range(n)) - {s0}
                while left:
                    nxt = min(left, key=lambda j: D[p[-1], j] + 0.5 * abs(ranks[j] - prof[len(p)]))
                    p.append(nxt); left.discard(nxt)
                if total(p) < bt:
                    best, bt = p, total(p)
        best = [int(x) for x in best]
        if best != by_arc:
            out.append(dict(label="by key relation", order=best,
                            why="neighbouring songs as close in key as possible (the circle of fifths), "
                                "with the energy arc as the tie-break"))
    return out


def step_summary(songs, order):
    d = [key_distance(songs[order[k]]["key"], songs[order[k + 1]]["key"]) for k in range(len(order) - 1)]
    d = [x for x in d if x is not None]
    return (f"{sum(1 for x in d if x >= 3)} far key change(s) out of {len(d)}" if d else "keys not measured")


# ---------------------------------------------------------------- proposals
def level_gain(row, song, o):
    """The trim in dB for a song that sits apart (None when it should be left alone) and the note on it."""
    if row["state"] != "apart":
        return None, ""
    reading = o["reading"]
    if reading == "whole":
        gap = -row["d_whole"]
    elif reading == "loudest":
        gap = -row["d_loudest"]
    else:
        gap = -row["d_whole"] if abs(row["d_whole"]) < abs(row["d_loudest"]) else -row["d_loudest"]
    note = ""
    if gap > 0:
        room = o["ceiling"] - song["true_peak"]
        if gap > room:
            note = (f"limited to {max(room, 0):+.1f} dB so the true peak stays at {o['ceiling']:g} dBTP; "
                    "the rest needs a limiter (`hypnomix master`)")
            gap = max(room, 0.0)
    gap = round(gap * 10) / 10
    return (gap if abs(gap) >= 0.2 else None), note


def tilt_for(row, o):
    """(low dB, high dB) for a gentle tilt, or None. A fraction (--tilt-amount) of the gap, never past --max-tilt-db."""
    tol, amt, cap = o["tone_tolerance"], o["tilt_amount"] / 100.0, o["max_tilt_db"]
    out = {}
    for key in ("low", "high"):
        v = row["groups"][key]
        if abs(v) > tol:
            out[key] = round(float(np.clip(-v * amt, -cap, cap)) * 10) / 10
    out = {k: v for k, v in out.items() if abs(v) >= 0.1}
    return out or None


def ends_targets(songs, order, trans, o):
    """Per song (by position): the head and tail silence this order suggests."""
    res = {}
    for k, i in enumerate(order):
        s = songs[i]
        head = o["head"]
        tail = o["last_tail"] if k == len(order) - 1 else max(0.2, trans[k]["gap"] - o["head"])
        res[i] = (round(head, 2), round(tail, 2))
    return res


def proposals(songs, cmp, order, trans, o):
    """Everything the album would change, as findings with the command `fix` and `ab` run for each."""
    out = []
    targets = ends_targets(songs, order, trans, o)
    for i, s in enumerate(songs):
        row = cmp["rows"][i]
        src = s["file"]
        gain, note = level_gain(row, s, o)
        if gain is not None:
            why_ = {"both": "both the whole song and its loudest section are outside the tolerance; the smaller gap is used",
                    "whole": "the whole-song loudness is outside the tolerance",
                    "loudest": "the loudest section is outside the tolerance"}[o["reading"]]
            out.append(dict(kind="gain", severity="medium" if abs(gain) >= 3 else "low", track=Path(src).name,
                            problem=f"level: {row['d_whole']:+.1f} LU as a whole and {row['d_loudest']:+.1f} LU at its loudest against "
                                    f"{row['ref_how']} ({why_})",
                            fix=("" if o.get("anchor") or o.get("target") is not None else
                                 "Only if you want it to match the others (a song that is meant to be quieter or louder can stay): ")
                                + f"{'raise' if gain > 0 else 'lower'} the song by {abs(gain):.1f} dB into a new file"
                                + (f" ({note})" if note else "") + ". Listen: the new level next to its neighbours, "
                                "at the same volume on your speakers.",
                            applies="audio", run=["album", "--render", "gain", src, "--db", f"{gain:+.1f}", "--out", "{out}"],
                            album=dict(move="gain", db=gain)))
        tilt = tilt_for(row, o)
        if tilt and row["state"] != "anchor":
            arg = ",".join(f"{k}:{v:+.1f}" for k, v in tilt.items())
            parts = []
            if "low" in tilt:
                parts.append(f"low shelf {tilt['low']:+.1f} dB at {LOW_SHELF_HZ:g} Hz")
            if "high" in tilt:
                parts.append(f"high shelf {tilt['high']:+.1f} dB at {HIGH_SHELF_HZ / 1000:g} kHz")
            out.append(dict(kind="tilt", severity="low", track=Path(src).name,
                            problem=f"tone against {'the anchor' if cmp['anchor'] is not None else 'the other songs'}: " + "; ".join(w for k_, w in row["tone_words"] if k_ in ("low", "high")),
                            fix=f"a gentle tilt, {o['tilt_amount']:g}% of the gap and at most {o['max_tilt_db']:g} dB: " + ", ".join(parts)
                                + ", loudness kept, into a new file. Listen: the same song next to its neighbours, "
                                  "and whether it still sounds like itself.",
                            applies="audio", run=["album", "--render", "tilt", src, "--tilt", arg, "--out", "{out}"],
                            album=dict(move="tilt", tilt=tilt)))
        head_t, tail_t = targets[i]
        dh, dt = head_t - s["head_s"], tail_t - s["tail_s"]
        tol = o["gap_tolerance"]
        if abs(dh) >= tol or abs(dt) >= tol:
            bits, args = [], ["album", "--render", "ends", src]
            if abs(dh) >= tol:
                bits.append(f"head {s['head_s']:.2f} s → {head_t:.2f} s")
                args += ["--head", f"{head_t:.2f}"]
            if abs(dt) >= tol:
                bits.append(f"tail {s['tail_s']:.2f} s → {tail_t:.2f} s")
                args += ["--tail", f"{tail_t:.2f}"]
            out.append(dict(kind="ends", severity="low", track=Path(src).name,
                            problem="silence: " + ", ".join(bits) + " (for the suggested gaps in this order)",
                            fix="trim or pad silence only, into a new file (nothing above -60 dBFS is cut). Listen: the join "
                                "with the song before and after.",
                            applies="audio", run=args + ["--out", "{out}"], album=dict(move="ends", head=head_t, tail=tail_t)))
    return out


# ---------------------------------------------------------------- the report
def table(rows, head):
    L = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    L += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return L


def report(songs, order, cmp, trans, orders, props, o, notes):
    n = len(songs)
    L = [f"# Album check: {n} songs", "",
         "Measured, not heard: every number below is a measurement. Nothing was changed. The proposals are options; "
         "your ears decide.", ""]
    if notes:
        L += [f"- {x}" for x in notes] + [""]
    L += ["## The songs, in this order", ""]
    rows = []
    for k, i in enumerate(order, 1):
        s = songs[i]
        rows.append([k, s["name"], fmt_t(s["duration_s"]), f"{s['whole_lufs']:.1f}", f"{s['loudest_lufs']:.1f}", f"{s['true_peak']:+.1f}",
                     "mono" if s["mono"] else f"{s['width_db']:+.1f}", f"{s['head_s']:.2f} s", f"{s['tail_s']:.2f} s ({s['tail_kind']})",
                     s["key"] + ("" if s["key_sure"] else "?") if s["key"] else "-", f"{s['tempo']:g}" if s["tempo"] else "-"])
    L += table(rows, ["#", "song", "length", "LUFS (whole)", "LUFS (loudest section)", "true peak dBTP", "width (side−mid dB)",
                      "head silence", "tail silence", "key", "BPM"])
    L += ["", "A `?` after a key means the key finder was not sure (the runner-up is close). Tempo is an estimate "
          "and can come out as half or double.", ""]

    L += ["## Level", ""]
    rd = {"both": "both readings: the whole song and its loudest section (the highest short-term loudness, 3 s windows). "
                  f"A song counts as apart only when BOTH are more than {o['tolerance']:g} LU away, in the same direction, "
                  "so a quiet ballad or quiet verses are shown but left alone",
          "whole": "the whole song only (integrated loudness)", "loudest": "the loudest section only"}[o["reading"]]
    L += [f"Reading used: {rd}.", ""]
    for k, i in enumerate(order):
        s, r = songs[i], cmp["rows"][i]
        head = f"- **{s['name']}**: {s['whole_lufs']:.1f} LUFS whole ({r['d_whole']:+.1f} against {r['ref_how']}), {s['loudest_lufs']:.1f} at its loudest ({r['d_loudest']:+.1f})."
        if r["state"] == "apart":
            g, note = level_gain(r, s, o)
            word = "quieter" if r["d_loudest"] < 0 or r["d_whole"] < 0 else "louder"
            head += f" **Sits apart: {word}.**" + (f" Proposal{'' if o.get('anchor') or o.get('target') is not None else ' (only if you want it to match the others; a song meant to be quieter can stay)'}: {'raise' if g > 0 else 'lower'} {abs(g):.1f} dB" + (f" ({note})" if note else "") + "." if g else " The gap is small once true peak is respected: left alone.")
        elif r["state"] == "whole only":
            head += (f" {'Quieter' if r['d_whole'] < 0 else 'Louder'} as a whole, but its loudest section is in line: "
                     + ("quiet passages inside the song (verses, a soft intro), which is what dynamics sound like. Left alone."
                        if r["d_whole"] < 0 else "it stays near its top level more of the time. Left alone."))
        elif r["state"] == "loudest only":
            head += (f" In line as a whole, but its loudest section is {abs(r['d_loudest']):.1f} LU "
                     f"{'under' if r['d_loudest'] < 0 else 'over'} the others': one big (or one timid) moment. Left alone.")
        elif r["state"] == "kept quiet":
            head += " You asked to keep it as it is (--keep-quiet): no move proposed."
        elif r["state"] == "anchor":
            head += " The anchor: the others are matched to it."
        else:
            head += " In line."
        L.append(head)
    if n == 2:
        L += ["", "_With 2 songs each is measured against the midpoint of the two, so each proposal moves half the gap and "
              "the two meet in the middle (a song never swaps places with the other). `--anchor SONG` keeps one as it is "
              "and moves only the other._"]
    elif n == 3:
        L += ["", "_With 3 songs the median of the others is just their midpoint, so one odd song pulls the rest; "
              "`--anchor SONG` says which one is the standard._"]

    L += ["", "## Tone (8 bands, against the median of the other songs)", "",
          "Each curve is lined up on its own 250 Hz to 4 kHz level first, so only shape counts. Plus means more of that "
          "band than the others.", ""]
    rows = [[songs[i]["name"]] + [f"{v:+.1f}" for v in cmp["rows"][i]["dev"]] for i in order]
    L += table(rows, ["song"] + cmp["bands"]) + [""]
    any_tone = False
    for i in order:
        r = cmp["rows"][i]
        if r["tone_words"]:
            any_tone = True
            L.append(f"- **{songs[i]['name']}**: " + "; ".join(w for _, w in r["tone_words"]) + ".")
    if not any_tone:
        L.append(f"- No song is more than {o['tone_tolerance']:g} dB away from the others in any band from 60 Hz up "
                 f"(the sub-bass needs {2 * o['tone_tolerance']:g} dB to count).")
    L += ["", "## Stereo width", ""]
    any_w = False
    for i in order:
        w = cmp["rows"][i]["width_words"]
        if w:
            any_w = True
            L.append(f"- **{songs[i]['name']}**: {w}.")
    if not any_w:
        L.append(f"- All the songs are within {o['width_tolerance']:g} dB of each other.")

    L += ["", "## Between the songs", ""]
    if not trans:
        L.append("One song: nothing to join.")
    for t in trans:
        L.append(f"**{t['a']}** → **{t['b']}**: suggested gap about **{t['gap']:.1f} s** (now {t['have']:.2f} s of silence between them).")
        for w in t["why"]:
            L.append(f"  - {w}")
        bits = [f"loudest section {t['level_step']:+.1f} LU"]
        if t["key"]:
            bits.append("keys " + t["key"])
        if t["tempo"]:
            bits.append(t["tempo"])
        L.append("  - " + "; ".join(bits))
    L += ["", f"The first song keeps {o['head']:g} s of lead-in; the last ends with {o['last_tail']:g} s. The gap sits at the end of "
          "the first song of each pair (a short lead-in on the next).", ""]

    if o.get("suggest_order"):
        L += ["## Order options (never applied)", ""]
        if not orders:
            L.append("Fewer than three songs, or nothing to suggest.")
        for opt in orders:
            same = opt["order"] == order
            L.append(f"- **{opt['label']}**{' (this is the order you gave)' if same else ''}: " + " → ".join(songs[i]["name"] for i in opt["order"]))
            L.append(f"  - {opt['why']}; {step_summary(songs, opt['order'])}")
        L += ["", f"Your order: {step_summary(songs, order)}. To compare, run again with `--order` and the option's names.", ""]

    L += ["## What could change", ""]
    if not props:
        L.append("Nothing is proposed: the songs sit together within the tolerances.")
    for p in props:
        L.append(f"- **{p['track']}** ({p['kind']}): {p['problem']}. Proposal: {p['fix']}")
    if props:
        L += ["", "Nothing here is applied. `--plan` turns these into findings for the normal review "
              "(`hypnomix review`, `hypnomix ab`, then `hypnomix fix DIR --approved`, into new files)."]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- applying one approved move (what fix runs)
def parse_tilt(text):
    out = {}
    for part in (text or "").split(","):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        k = k.strip().lower()
        if k not in ("low", "high"):
            raise SystemExit(f"--tilt: unknown band {k!r} (low, high)")
        out[k] = float(v)
    if not out:
        raise SystemExit("--tilt needs low:DB and/or high:DB, for example low:-1.0,high:+0.8")
    return out


def _bits_of(path):
    import soundfile as sf
    sub = sf.info(str(path)).subtype
    return {"PCM_16": 16, "PCM_24": 24}.get(sub, 24 if sub.startswith("PCM") or sub in ("FLOAT", "DOUBLE") else 24), sub


def render(kind, src, out_dir, db=None, tilt=None, head=None, tail=None, ceiling=-1.0):
    """Apply one approved move to a copy of the song. Moves on the same song chain, in the order they run:
    the next one starts from the file the last one wrote. Returns the new path (or the earlier one, if this
    move was already applied in this folder)."""
    import soundfile as sf
    src = Path(src).resolve()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    side = out_dir / ".album-steps.json"
    steps = json.loads(side.read_text()) if side.exists() else {}
    st = steps.get(str(src), {"latest": str(src), "done": []})
    if kind in st["done"]:
        print(f"{kind}: already applied to {src.name} in this folder: {st['latest']}")
        return Path(st["latest"])
    cur = Path(st["latest"])
    y, sr = dsp.load(cur)
    bits, sub = _bits_of(src)
    before = dict(lufs=dsp.lufs(y, sr), tp=dsp.true_peak(y, sr))
    if kind == "gain":
        z = y * dsp.undb(float(db))
        what = f"gain {float(db):+.1f} dB"
    elif kind == "tilt":
        t = dict(tilt)
        z = y
        if "low" in t:
            z = dsp.filt(z, dsp.shelf(LOW_SHELF_HZ, t["low"], sr, high=False))
        if "high" in t:
            z = dsp.filt(z, dsp.shelf(HIGH_SHELF_HZ, t["high"], sr, high=True))
        keep = dsp.lufs(y, sr) - dsp.lufs(z, sr)                   # the tilt changes the tone, not the level
        keep = float(np.clip(keep, -2.0, 2.0))
        z = z * dsp.undb(keep)
        tp = dsp.true_peak(z, sr)
        if tp > ceiling and tp > before["tp"]:                      # never past the ceiling because of the tilt
            z = z * dsp.undb(max(ceiling, before["tp"]) - tp)
        what = "tilt " + ", ".join(f"{k} {v:+.1f} dB" for k, v in t.items()) + f" (level kept, {keep:+.2f} dB make-up)"
    elif kind == "ends":
        peak = np.max(np.abs(y), axis=1)
        on = np.flatnonzero(peak > SILENCE)
        if not len(on):
            raise SystemExit(f"{src.name} is silent: nothing to trim or pad")
        z = y
        notes = []
        if tail is not None:                                        # tail first, so the head's indexes stay put
            have = len(y) - 1 - on[-1]
            want = int(round(float(tail) * sr))
            z = z[:on[-1] + 1 + want] if want < have else np.concatenate([z, np.zeros((want - have, z.shape[1]))])
            notes.append(f"tail {have / sr:.2f} → {want / sr:.2f} s")
        if head is not None:
            have = on[0]
            want = int(round(float(head) * sr))
            z = z[have - want:] if want < have else np.concatenate([np.zeros((want - have, z.shape[1])), z])
            notes.append(f"head {have / sr:.2f} → {want / sr:.2f} s")
        what = "silence " + ", ".join(notes)
    else:
        raise SystemExit(f"unknown move {kind!r} (gain, tilt, ends)")
    done = st["done"] + [kind]
    dest = out_dir / f"{src.stem} (album {'+'.join(done)}).wav"
    n = 1
    while dest.exists():
        n += 1
        dest = out_dir / f"{src.stem} (album {'+'.join(done)} {n}).wav"
    if kind == "ends":
        sf.write(str(dest), np.clip(z, -1, 1), sr, subtype=sub if sub.startswith("PCM") or sub in ("FLOAT", "DOUBLE") else "PCM_24")
    else:
        dsp.save(dest, z, sr, bits if bits in (16, 24) else 24)       # 16-bit gets the usual TPDF dither
    after = dict(lufs=dsp.lufs(z, sr), tp=dsp.true_peak(z, sr))
    steps[str(src)] = {"latest": str(dest), "done": done}
    side.write_text(json.dumps(steps, indent=1))
    print(f"{what}: {src.name} → {dest.name}\n  integrated {before['lufs']:.1f} → {after['lufs']:.1f} LUFS, "
          f"true peak {before['tp']:+.1f} → {after['tp']:+.1f} dBTP")
    return dest


# ---------------------------------------------------------------- command line
def resolve_files(args):
    files = []
    for a in args:
        p = Path(a).expanduser()
        if p.is_dir():
            files += sorted(x for x in p.iterdir() if x.suffix.lower() in dsp.AUDIO_EXT and not x.name.startswith("."))
        elif p.exists():
            files.append(p)
        else:
            raise SystemExit(f"not found: {a}")
    seen, out = set(), []
    for f in files:
        r = f.resolve()
        if r not in seen:
            seen.add(r)
            out.append(f)
    return out


def resolve_order(spec, songs):
    names = [s["name"] for s in songs]
    low = [n.lower() for n in names]
    order = []
    for tok in [t.strip() for t in spec.split(",") if t.strip()]:
        if tok.lower() in low:
            i = low.index(tok.lower())
        elif tok.isdigit() and 1 <= int(tok) <= len(songs):
            i = int(tok) - 1
        else:
            hits = [k for k, n in enumerate(low) if n.startswith(tok.lower())]
            if len(hits) != 1:
                raise SystemExit(f"--order: {tok!r} matches {'no song' if not hits else 'several songs'}. The songs are: {', '.join(names)}")
            i = hits[0]
        order.append(i)
    if len(set(order)) != len(order):
        raise SystemExit("--order names a song twice")
    missing = [names[i] for i in range(len(songs)) if i not in order]
    if missing:
        raise SystemExit(f"--order leaves out: {', '.join(missing)} (name every song, or leave --order off)")
    return order


def build_parser():
    ap = argparse.ArgumentParser(prog="hypnomix album", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="the songs (or one folder)")
    ap.add_argument("--order", help="song names (or numbers) in playing order, comma-separated; default: the order given")
    ap.add_argument("--target", type=float, help="whole-song loudness (LUFS) to compare with, instead of the other songs")
    ap.add_argument("--anchor", help="match the others to this song (its name)")
    ap.add_argument("--keep-quiet", default="", help="songs that are meant to be quieter (comma-separated): shown, never touched")
    ap.add_argument("--reading", choices=["both", "whole", "loudest"], default="both",
                    help="which loudness reading calls a song apart (default both)")
    ap.add_argument("--tolerance", type=float, default=2.0, help="level: LU a song may differ before it counts as apart (2)")
    ap.add_argument("--tone-tolerance", type=float, default=1.5, help="tone: dB a band group may differ (1.5)")
    ap.add_argument("--width-tolerance", type=float, default=3.0, help="stereo width: dB (3)")
    ap.add_argument("--tilt-amount", type=float, default=50.0, help="tonal tilt: percent of the gap to close (50)")
    ap.add_argument("--max-tilt-db", type=float, default=2.0, help="tonal tilt: the most any shelf moves (2 dB)")
    ap.add_argument("--ceiling", type=float, default=-1.0, help="true-peak ceiling for a raise, dBTP (-1)")
    ap.add_argument("--gap", type=float, help="one gap in seconds for every transition, instead of suggesting each")
    ap.add_argument("--gap-style", choices=list(STYLE), default="normal", help="tight, normal or roomy gaps")
    ap.add_argument("--head", type=float, help="lead-in each song keeps, seconds (0.1)")
    ap.add_argument("--last-tail", type=float, default=2.0, help="silence after the last song, seconds (2)")
    ap.add_argument("--gap-tolerance", type=float, default=0.3, help="silence moves smaller than this are not proposed (0.3 s)")
    ap.add_argument("--suggest-order", action="store_true", help="list one or two orders to try, as options")
    ap.add_argument("--quick", action="store_true", help="skip key and tempo (the slow part; no key-based order then)")
    ap.add_argument("--plan", nargs="?", const=True, metavar="SCAN_DIR",
                    help="turn the proposals into findings in a scan folder for review (nothing is written to the songs)")
    ap.add_argument("--out", help="where ALBUM.md goes (default hypnomix-out/album; with --plan, the scan folder)")
    ap.add_argument("--render", choices=["gain", "tilt", "ends"], help=argparse.SUPPRESS)
    ap.add_argument("--db", type=float, help=argparse.SUPPRESS)
    ap.add_argument("--tilt", help=argparse.SUPPRESS)
    ap.add_argument("--tail", type=float, help=argparse.SUPPRESS)
    return ap


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.render:
        if len(a.files) != 1:
            sys.exit("--render takes one song")
        if not a.out:
            sys.exit("--render needs --out DIR")
        if a.render == "gain" and a.db is None:
            sys.exit("--render gain needs --db")
        render(a.render, a.files[0], a.out, db=a.db, tilt=parse_tilt(a.tilt) if a.render == "tilt" else None,
               head=a.head if a.render == "ends" else None,
               tail=a.tail if a.render == "ends" else None, ceiling=a.ceiling)
        return
    files = resolve_files(a.files)
    if len(files) < 2:
        sys.exit("an album needs at least two songs: hypnomix album SONG1.wav SONG2.wav ...")
    songs, notes = [], []
    for f in files:
        print(f"measuring {f.name} …", file=sys.stderr)
        try:
            songs.append(analyse(f, quick=a.quick))
        except Exception as e:
            sys.exit(f"{f.name}: {e}")
    names = [s["name"] for s in songs]
    if len(set(n.lower() for n in names)) != len(names):
        sys.exit("two songs share a name; rename one so they can be told apart")
    if a.anchor:
        low = [n.lower() for n in names]
        if a.anchor.lower() not in low:
            sys.exit(f"--anchor: no song called {a.anchor!r}. The songs are: {', '.join(names)}")
        a.anchor = names[low.index(a.anchor.lower())]
    order = resolve_order(a.order, songs) if a.order else list(range(len(songs)))
    o = dict(anchor=a.anchor, target=a.target, keep_quiet=[x.strip() for x in a.keep_quiet.split(",") if x.strip()],
             reading=a.reading, tolerance=a.tolerance, tone_tolerance=a.tone_tolerance, width_tolerance=a.width_tolerance,
             tilt_amount=a.tilt_amount, max_tilt_db=a.max_tilt_db, ceiling=a.ceiling, gap=a.gap, gap_style=a.gap_style,
             head=0.1 if a.head is None else a.head, last_tail=a.last_tail, gap_tolerance=a.gap_tolerance, suggest_order=a.suggest_order)
    rates = sorted({s["sr"] for s in songs})
    if len(rates) > 1:
        notes.append("the songs have different sample rates (" + ", ".join(map(str, rates)) + " Hz): `hypnomix preflight` lists which; "
                     "an album needs one rate")
    if a.quick:
        notes.append("--quick: key and tempo were not measured")
    if a.target is not None and a.anchor:
        sys.exit("give --target or --anchor, not both")
    cmp = compare(songs, o)
    trans = transitions(songs, order, o)
    orders = suggest_orders(songs) if a.suggest_order else []
    props = proposals(songs, cmp, order, trans, o)
    text = report(songs, order, cmp, trans, orders, props, o, notes)
    plan = a.plan
    if plan:
        from hypnomix.workflow import plan as P
        common = os.path.commonpath([str(Path(s["file"]).parent) for s in songs])
        od = P.scan_dir(plan if isinstance(plan, str) else a.out, common, " album")
    else:
        od = out_at(a.out, "album")
    od.mkdir(parents=True, exist_ok=True)
    (od / "ALBUM.md").write_text(text)
    raw = od / "raw"
    raw.mkdir(exist_ok=True)
    (raw / "album.json").write_text(json.dumps(dict(songs=songs, order=[songs[i]["name"] for i in order], compare=cmp,
                                                    transitions=trans, orders=orders, options=o), indent=1, default=float))
    print(text)
    if plan:
        from hypnomix.workflow import plan as P
        sum_ = (f"album plan: {len(songs)} songs in this order: " + " → ".join(songs[i]["name"] for i in order)
                + ". Each move is applied to a copy by `fix --approved` into fixed/; several approved moves on one song chain, "
                  "and the highest step is the finished file. Full report: ALBUM.md")
        P.write(od, "album", common, props, [sum_])
    else:
        print(f"report: {od / 'ALBUM.md'}")
        if props:
            print(f"{len(props)} proposal(s) listed; add --plan to turn them into findings for review (nothing is applied).")


if __name__ == "__main__":
    main()
