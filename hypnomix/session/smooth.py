#!/usr/bin/env python3
"""Find and smooth sudden volume jumps on audio clips in an Ableton set's Arrangement.

Reads the saved .als and the audio each clip actually plays (respecting warp markers, clip start,
loops and Clip Gain), then reports three kinds of problem:

  click  a clip starts or stops on a loud sample with no fade (an audible tick)
  cut    one clip ends mid-phrase and the next starts at a noticeably different level (comped vocals),
         or a looped clip jumps in level each time it wraps around
  spike  a short burst far louder than what surrounds it (a pop, a bump, one shouted word). Not flagged: a loud
         consonant that opens a sung phrase (quiet before, singing right after: the "B" of "baby"). A burst that
         is mostly low end (under 150 Hz) inside a phrase is a plosive: it gets at most a 3 dB dip
  step   (only with --steps) a sudden level change inside a clip that lasts. Usually this is the
         music itself (a section change, a loop's own dynamics), so it is off by default

Nothing changes unless you pass --apply. Then it writes a NEW set (the original is never touched):

  clicks -> a short clip fade (--fade-ms, default 5 ms)
  spikes -> a quick dip in track volume over the burst, like riding clip gain by hand
  cuts and steps -> an "ease": the track volume takes --amount of the jump away right at the jump and
                    fades back to normal over --ease-ms, so the change arrives gradually instead of
                    instantly. It scales any existing volume automation, so deliberate rides survive.

Usage:
  hypnomix smooth SET.als [--track NAME ...] [--cut-db 4] [--spike-db 12] [--steps]
  hypnomix smooth SET.als --apply "SET (smoothed).als" [--amount 0.5] [--ease-ms 300]

Close the set in Live before --apply (Live would overwrite the edit on its next save), then open the
new file (in the same folder, so relative sample links still work). Assumes a constant song tempo.
Session View clips are not checked.
"""
import argparse, gzip, math, os, sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix.session import automation as aa  # envelope helpers shared with `hypnomix automation`

BLOCK = 0.01          # analysis block, seconds
SOUNDING_DB = -50.0   # quieter than this counts as silence
CLICK_LIN = 0.01      # a clip edge sample above -40 dBFS with no fade is a click
MAX_LIN = 1.99526     # Live's fader maximum (+6 dB) as a linear gain
SPIKES_PER_MIN = 4.0  # more 9 dB bursts than this per minute on a track means regular hits (drums)
MIN_REGULAR = 4       # ...and at least this many: one or two bursts in a short track are not a beat
                      # (phrase-opening consonants are not counted: they are singing, not hits)
HIT_DB = 9.0
PLOSIVE_HZ = 150.0    # a burst with most of its energy below this is a plosive (B, P), not a pop or bump
PLOSIVE_SHARE = 0.6
PLOSIVE_MAX_DIP = 3.0 # dB: a plosive inside a phrase gets at most this much (a full dip cuts the consonant)

db = lambda p: 10 * np.log10(np.maximum(p, 1e-12))  # power -> dB


# ---------------------------------------------------------------- reading the set
def val(el, path, cast=float, default=None):
    e = el.find(path)
    return cast(e.get("Value")) if e is not None and e.get("Value") is not None else default


def track_on(t):
    sp = t.find("./DeviceChain/Mixer/Speaker/Manual")
    return sp is None or sp.get("Value") == "true"


def audio_tracks(root, names, include_off=False, skipped=None):
    out = []
    for t in root.find(".//Tracks"):
        if t.tag != "AudioTrack":
            continue
        name = t.find("./Name/EffectiveName").get("Value")
        if not include_off and not track_on(t):
            if skipped is not None:
                skipped.append(name)
            continue
        if names and not any(n.lower() == name.lower() or name.lower().startswith(n.lower()) for n in names):
            continue
        out.append((name, t))
    if names and not out:
        sys.exit(f"no audio track matches {names}")
    return out


def clip_info(c, als_dir, tempo):
    fr = c.find(".//SampleRef/FileRef")
    p = fr.find("./Path").get("Value") if fr is not None and fr.find("./Path") is not None else ""
    rel = fr.find("./RelativePath").get("Value") if fr is not None and fr.find("./RelativePath") is not None else ""
    path = Path(p) if p and Path(p).exists() else (als_dir / rel)
    markers = sorted((float(w.get("BeatTime")), float(w.get("SecTime")))     # the clip's own markers only (not
                     for w in c.findall("./WarpMarkers/WarpMarker"))          # SavedWarpMarkersForStretched)
    loop_on = val(c, "./Loop/LoopOn", lambda v: v == "true", False)
    ls, le = val(c, "./Loop/LoopStart"), val(c, "./Loop/LoopEnd")
    fades = c.find("./Fades")
    return dict(
        el=c, name=val(c, "./Name", str, "") or path.stem, path=path,
        start=val(c, "./CurrentStart"), end=val(c, "./CurrentEnd"),
        loop_on=loop_on, ls=ls, le=le, rel=val(c, "./Loop/StartRelative", default=0.0),
        warped=val(c, "./IsWarped", lambda v: v == "true", False), markers=markers,
        gain=val(c, "./SampleVolume", default=1.0),
        fade_in=val(fades, "./FadeInLength", default=0.0) if fades is not None else 0.0,
        fade_out=val(fades, "./FadeOutLength", default=0.0) if fades is not None else 0.0,
        default_in=val(fades, "./IsDefaultFadeIn", lambda v: v == "true", True) if fades is not None else True,
        default_out=val(fades, "./IsDefaultFadeOut", lambda v: v == "true", True) if fades is not None else True,
        disabled=val(c, "./Disabled", lambda v: v == "true", False),
    )


def file_seconds(ci, arr_beats, tempo):
    """Arrangement beats (absolute) -> seconds in the clip's audio file. Vectorised."""
    rel = np.asarray(arr_beats, dtype=float) - ci["start"]
    if not ci["warped"]:
        rel = rel * 60.0 / tempo  # unwarped clips keep loop/start positions in seconds
    if ci["loop_on"] and ci["le"] > ci["ls"]:
        first = ci["ls"] + ci["rel"]
        span = ci["le"] - ci["ls"]
        # play from the start marker to the loop end once, then repeat the loop
        lead = ci["le"] - first
        pos = np.where(rel < lead, first + rel, ci["ls"] + np.mod(rel - lead, span))
    else:
        pos = ci["ls"] + rel
    if ci["warped"] and len(ci["markers"]) >= 2:
        b, s = (np.array(x) for x in zip(*ci["markers"]))
        sec = np.interp(pos, b, s)
        lo_slope = (s[1] - s[0]) / max(1e-9, b[1] - b[0])
        hi_slope = (s[-1] - s[-2]) / max(1e-9, b[-1] - b[-2])
        sec = np.where(pos < b[0], s[0] + (pos - b[0]) * lo_slope, sec)
        sec = np.where(pos > b[-1], s[-1] + (pos - b[-1]) * hi_slope, sec)
        return sec
    if ci["warped"]:
        return pos * 60.0 / tempo
    return pos  # unwarped clips keep loop/start positions in seconds


# ---------------------------------------------------------------- audio
_cache = {}


def load_audio(path):
    if path not in _cache:
        y, sr = sf.read(str(path), always_2d=True, dtype="float32")
        n = len(y) // int(sr * BLOCK)
        k = int(sr * BLOCK)
        power = (y[: n * k] ** 2).mean(axis=1).reshape(n, k).mean(axis=1)
        _cache[path] = (y, sr, power)
    return _cache[path]


def clip_levels(ci, tempo):
    """Level of the clip as heard (incl. Clip Gain) on a 10 ms grid of arrangement time."""
    y, sr, power = load_audio(ci["path"])
    dur_s = (ci["end"] - ci["start"]) * 60.0 / tempo
    n = max(1, int(dur_s / BLOCK))
    t = np.arange(n) * BLOCK
    beats = ci["start"] + t * tempo / 60.0
    idx = np.clip((file_seconds(ci, beats, tempo) / BLOCK).astype(int), 0, len(power) - 1)
    p = power[idx] * ci["gain"] ** 2
    return t, p


def edge_sample(ci, tempo, which):
    y, sr, _ = load_audio(ci["path"])
    beat = ci["start"] if which == "in" else ci["end"]
    s = float(file_seconds(ci, [beat], tempo)[0])
    i = int(round(s * sr))
    i = min(max(i - (1 if which == "out" else 0), 0), len(y) - 1)
    return float(np.abs(y[i]).max()) * ci["gain"], s


def smooth_db(p, secs):
    k = max(1, int(secs / BLOCK))
    return db(np.convolve(p, np.ones(k) / k, mode="same"))


# ---------------------------------------------------------------- detection
def find_steps(ci, tempo, step_db):
    t, p = clip_levels(ci, tempo)
    if len(t) < int(3.0 / BLOCK):
        return []
    L = smooth_db(p, 0.4)
    w0, w1 = int(0.1 / BLOCK), int(1.0 / BLOCK)
    near = int(0.1 / BLOCK)
    cands = []
    for i in range(w1, len(L) - w1):
        before = np.median(L[i - w1: i - w0])
        after = np.median(L[i + w0: i + w1])
        if before < SOUNDING_DB or after < SOUNDING_DB:
            continue  # an entrance from silence or a stop is musical, not a jump
        step = after - before
        if abs(step) < step_db:
            continue
        if abs(L[i + near] - L[i - near]) < 0.6 * abs(step):
            continue  # gradual change (a crescendo), not a sudden one
        cands.append((abs(step), i, step))
    picked = []
    for mag, i, step in sorted(cands, reverse=True):
        if all(abs(i - j) > w1 for _, j, _ in picked):
            picked.append((mag, i, step))
    out = []
    fine = db(p)
    for _, i, step in sorted(picked, key=lambda x: x[1]):
        # place the jump on the sharpest 10 ms change nearby
        lo, hi = max(1, i - near), min(len(fine) - 1, i + near)
        d = np.diff(fine[lo - 1: hi + 1])
        j = lo + int(np.argmax(d * np.sign(step)))
        out.append(dict(beat=ci["start"] + t[j] * tempo / 60.0, size=float(step)))
    return out


def find_spikes(ci, tempo, spike_db):
    """Short bursts well above the surrounding level."""
    t, p = clip_levels(ci, tempo)
    if len(t) < int(3.0 / BLOCK):
        return []
    L = smooth_db(p, 0.05)
    k = int(1.5 / BLOCK)
    # surrounding level: rolling median over +-1.5 s (sounding blocks only)
    Lq = np.where(L > SOUNDING_DB, L, np.nan)
    pad = np.pad(Lq, k, constant_values=np.nan)
    win = np.lib.stride_tricks.sliding_window_view(pad, 2 * k + 1)[:, ::5]
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            M = np.nanmedian(win, axis=1)
    dev = L - M
    hot = (dev >= spike_db) & (M > SOUNDING_DB)
    spikes, i, n = [], 0, len(hot)
    while i < n:
        if not hot[i]:
            i += 1
            continue
        j = i
        while j < n and hot[j]:
            j += 1
        if (j - i) * BLOCK <= 0.4:
            pk = i + int(np.argmax(dev[i:j]))
            b0 = ci["start"] + max(0, i - 2) * BLOCK * tempo / 60
            b1 = ci["start"] + min(n, j + 2) * BLOCK * tempo / 60
            # the start of a sung phrase or word: a gap just before (30-150 ms, 15 dB or more under the
            # surroundings), and singing holds right after (the next 300 ms near the surrounding level). A "B" or "P"
            # opening a word is part of it; a pop or bump mid-phrase has sound right before it
            pre = L[max(0, i - 15):max(0, i - 3)]
            post = L[j:j + 30]
            onset = (len(pre) == 0 or float(np.median(pre)) < max(SOUNDING_DB, M[pk] - 15)) and \
                len(post) >= 10 and float(np.median(post)) >= M[pk] - 12
            spikes.append(dict(beat=ci["start"] + pk * BLOCK * tempo / 60, b0=b0, b1=b1,
                               size=float(dev[pk]), onset=bool(onset), low=low_share(ci, tempo, b0, b1)))
        i = j
    return spikes


def low_share(ci, tempo, b0, b1, hz=PLOSIVE_HZ):
    """Share of a burst's energy below `hz` (a plosive's thump is almost all low end)."""
    y, sr, _ = load_audio(ci["path"])
    s0, s1 = file_seconds(ci, [b0, b1], tempo)
    seg = y[max(0, int(s0 * sr)):max(0, int(s1 * sr))].mean(axis=1)
    if len(seg) < 64:
        return 0.0
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
    f = np.fft.rfftfreq(len(seg), 1 / sr)
    tot = float(spec.sum())
    return float(spec[f < hz].sum() / tot) if tot > 0 else 0.0


def loop_wraps(ci, tempo):
    """Clicks where a looped clip jumps from its loop end back to its loop start.

    Level differences at the seam are left alone: a loop that builds toward its end is musical."""
    if not ci["loop_on"] or ci["le"] <= ci["ls"]:
        return []
    first = ci["ls"] + ci["rel"]
    lead, span = ci["le"] - first, ci["le"] - ci["ls"]
    if not ci["warped"]:
        lead, span = lead * tempo / 60, span * tempo / 60
    if ci["start"] + lead >= ci["end"] - 1e-6:
        return []  # the clip never reaches its loop end
    y, sr, _ = load_audio(ci["path"])
    pos_end = ci["le"] if not ci["warped"] else None
    sec = file_seconds(ci, [ci["start"] + lead - 1e-6, ci["start"] + lead + 1e-6], tempo)
    i0 = min(max(int(round(sec[0] * sr)) - 1, 0), len(y) - 1)
    i1 = min(max(int(round(sec[1] * sr)), 0), len(y) - 1)
    jump = float(np.abs(y[i0] - y[i1]).max()) * ci["gain"]
    if jump < 2 * CLICK_LIN:
        return []
    out, b = [], ci["start"] + lead
    while b < ci["end"] - 1e-6:
        out.append(dict(beat=b, size=20 * math.log10(jump)))
        b += span
    return out


def edge_level(ci, tempo, which, secs=0.3):
    t, p = clip_levels(ci, tempo)
    k = max(1, int(secs / BLOCK))
    seg = p[:k] if which == "in" else p[-k:]
    loud = seg[db(seg) > SOUNDING_DB]
    return float(db(loud.mean())) if len(loud) else -math.inf


def typical(ci, tempo):
    """Median level of a clip while it is sounding."""
    _, p = clip_levels(ci, tempo)
    L = db(p)
    L = L[L > SOUNDING_DB]
    return float(np.median(L)) if len(L) else -math.inf


def seamless(a, b, tempo):
    """b continues a's audio exactly (a clip that was split): no click and no jump."""
    if a["path"] != b["path"] or abs(b["start"] - a["end"]) > 1e-3:
        return False
    sa = float(file_seconds(a, [a["end"]], tempo)[0])
    sb = float(file_seconds(b, [b["start"]], tempo)[0])
    return abs(sa - sb) < 0.002 and abs(a["gain"] - b["gain"]) < 1e-3


def analyse(root, als_dir, names, step_db, cut_db, spike_db, explicit, include_off=False):
    tempo = float(root.find(".//Tempo/Manual").get("Value"))
    issues, notes = [], {"default_fade_edges": 0, "missing": set(), "clips": 0, "regular": set(), "off": [], "onsets": {}}
    for tname, t in audio_tracks(root, names, include_off, notes["off"]):
        ev = t.find("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events")
        if ev is None:
            continue
        clips = [clip_info(c, als_dir, tempo) for c in ev.findall("AudioClip")]
        clips = sorted([c for c in clips if not c["disabled"]], key=lambda c: c["start"])
        ok = []
        for c in clips:
            if c["path"].exists():
                ok.append(c)
            else:
                notes["missing"].add(str(c["path"]))
        notes["clips"] += len(ok)
        track_spikes = []
        for k, c in enumerate(ok):
            prev = ok[k - 1] if k else None
            nxt = ok[k + 1] if k + 1 < len(ok) else None
            joined_in = prev is not None and seamless(prev, c, tempo)
            joined_out = nxt is not None and seamless(c, nxt, tempo)
            for which, joined in (("in", joined_in), ("out", joined_out)):
                if joined:
                    continue
                amp, _ = edge_sample(c, tempo, which)
                if amp < CLICK_LIN:
                    continue
                length = c["fade_in"] if which == "in" else c["fade_out"]
                is_default = c["default_in"] if which == "in" else c["default_out"]
                if length > 0:
                    continue
                if is_default and not explicit:
                    notes["default_fade_edges"] += 1
                    continue
                issues.append(dict(kind="click", track=tname, t=t, clip=c, edge=which,
                                   beat=c["start"] if which == "in" else c["end"],
                                   size=20 * math.log10(amp)))
            replay = nxt is not None and nxt["path"] == c["path"] and \
                float(file_seconds(nxt, [nxt["start"]], tempo)[0]) <= float(file_seconds(c, [c["end"]], tempo)[0])
            if nxt is not None and not joined_out and not replay and nxt["start"] - c["end"] < 0.05:
                la, lb = edge_level(c, tempo, "out"), edge_level(nxt, tempo, "in")
                mid = la >= typical(c, tempo) - 6 and lb >= typical(nxt, tempo) - 6
                if mid and la > SOUNDING_DB and lb > SOUNDING_DB and abs(lb - la) >= cut_db:
                    issues.append(dict(kind="cut", track=tname, t=t, clip=nxt, prev=c,
                                       beat=nxt["start"], size=lb - la))
            for w in loop_wraps(c, tempo):
                issues.append(dict(kind="click", track=tname, t=t, clip=c, edge="loop",
                                   beat=w["beat"], size=w["size"]))
            for sp in find_spikes(c, tempo, min(spike_db, HIT_DB)):
                track_spikes.append(dict(kind="spike", track=tname, t=t, clip=c, beat=sp["beat"],
                                         b0=sp["b0"], b1=sp["b1"], size=sp["size"], onset=sp["onset"],
                                         plosive=sp["low"] >= PLOSIVE_SHARE))
            if step_db:
                for s in find_steps(c, tempo, step_db):
                    issues.append(dict(kind="step", track=tname, t=t, clip=c, beat=s["beat"], size=s["size"]))
        minutes = sum(c["end"] - c["start"] for c in ok) * 60 / tempo / 60
        # regular hits: count only bursts mid-phrase. The consonants that open sung phrases are singing, not a beat
        # (counting them made vocal and harmony tracks look like drums, so they were never checked for spikes)
        hits = sum(1 for sp in track_spikes if not sp["onset"])
        if hits >= MIN_REGULAR and minutes > 0 and hits / minutes > SPIKES_PER_MIN:
            notes["regular"].add(tname)  # regular hits: the instrument (drums, plucks), not a problem
        else:
            big = [sp for sp in track_spikes if sp["size"] >= spike_db]
            starts = [sp for sp in big if sp["onset"]]          # phrase-opening consonants: part of the singing
            if starts:
                notes["onsets"][tname] = len(starts)
            issues += [sp for sp in big if not sp["onset"]]
    issues.sort(key=lambda i: (i["track"], i["beat"]))
    return tempo, issues, notes


# ---------------------------------------------------------------- fixes
def set_fade(ci, edge, beats_len):
    f = ci["el"].find("./Fades")
    tag = "FadeInLength" if edge == "in" else "FadeOutLength"
    cur = float(f.find(f"./{tag}").get("Value"))
    if cur < beats_len:
        f.find(f"./{tag}").set("Value", repr(beats_len))
        f.find("./IsDefaultFadeIn" if edge == "in" else "./IsDefaultFadeOut").set("Value", "false")


def ease(root, track, beat, size_db, amount, ease_beats, pre_beats):
    """Scale the track's volume so a jump of size_db at `beat` arrives over ease_beats."""
    env, _ = aa.get_or_create_env(root, track, "Volume")
    offset = -size_db * amount
    t0, t1, t2 = beat - pre_beats, beat, beat + ease_beats

    def factor(b):
        if b <= t0 or b >= t2:
            return 1.0
        if b <= t1:
            return aa.lin(offset * (b - t0) / (t1 - t0))
        return aa.lin(offset * (t2 - b) / (t2 - t1))

    _, pts = aa.events(env)
    base = {b: aa.value_at(pts, b) for b in (t0, t1, t2)}
    for _, v, el in pts:
        b = float(el.get("Time"))
        if t0 < b < t2:
            el.set("Value", repr(min(MAX_LIN, v * factor(b))))
    for b in (t0, t1, t2):
        _, pts = aa.events(env)
        hit = [el for tm, _, el in pts if abs(tm - b) < 1e-6]
        if hit:
            hit[0].set("Value", repr(min(MAX_LIN, base[b] * factor(b))))
        else:
            aa.insert_point(root, env, b, min(MAX_LIN, base[b] * factor(b)))


def apply(root, issues, tempo, a):
    fade_beats = a.fade_ms / 1000 * tempo / 60
    ease_beats = a.ease_ms / 1000 * tempo / 60
    pre_beats = 0.01 * tempo / 60
    done = []
    for i in issues:
        if i["kind"] == "click":
            if i["edge"] != "loop":
                set_fade(i["clip"], i["edge"], fade_beats)
                done.append(i)
        elif i["kind"] == "spike":
            env, _ = aa.get_or_create_env(root, i["t"], "Volume")
            ramp = 0.02 * tempo / 60
            dip = i["size"] * a.amount
            if i.get("plosive"):
                dip = min(dip, PLOSIVE_MAX_DIP)          # gentle: a deep dip cuts the consonant itself
            aa.scale_range(root, env, -dip, i["b0"], i["b1"], ramp=ramp)
            done.append(i)
        elif i["kind"] == "cut":
            if i.get("prev") is not None:
                set_fade(i["prev"], "out", fade_beats)
                set_fade(i["clip"], "in", fade_beats)
            ease(root, i["t"], i["beat"], i["size"], a.amount, ease_beats, pre_beats)
            done.append(i)
        elif i["kind"] == "step":
            ease(root, i["t"], i["beat"], i["size"], a.amount, ease_beats, pre_beats)
            done.append(i)
    return done


# ---------------------------------------------------------------- report
def grouped(issues, tempo):
    """Group issues that come from the same spot in the same audio (copies of a clip or loop)."""
    groups = {}
    for i in issues:
        c = i["clip"]
        pos = round(float(file_seconds(c, [i["beat"]], tempo)[0]), 2)
        key = (i["track"], i["kind"], str(c["path"]), pos, round(i["size"]))
        groups.setdefault(key, []).append(i)
    return sorted(groups.values(), key=lambda g: (g[0]["track"], g[0]["beat"]))


def where(beat, bpb=None):
    bpb = bpb or aa.BPB
    bar = int(beat // bpb) + 1
    return f"{bar}.{beat % bpb + 1:.2f}"


def describe(i, a):
    if i["kind"] == "click":
        if i["edge"] == "loop":
            return (f"loop seam jumps {i['size']:.0f} dBFS (clicks each time it repeats)",
                    "not automatic: move the loop end to a quiet point in Live")
        return (f"clip {'starts' if i['edge'] == 'in' else 'ends'} on a {i['size']:.0f} dBFS sample, no fade",
                f"{a.fade_ms:g} ms fade")
    if i["kind"] == "spike":
        if i.get("plosive"):
            return (f"{i['size']:.1f} dB plosive thump (mostly under {PLOSIVE_HZ:g} Hz) inside a phrase",
                    f"gentle dip {-min(i['size'] * a.amount, PLOSIVE_MAX_DIP):+.1f} dB over the burst; if it still "
                    "thumps, a high-pass around 80-100 Hz on the vocal is the better fix")
        return (f"{i['size']:.1f} dB burst above its surroundings",
                f"dip {-i['size'] * a.amount:+.1f} dB over the burst")
    word = "louder" if i["size"] > 0 else "quieter"
    what = ("loop restarts" if i.get("loop") else "next clip is") if i["kind"] == "cut" else "level jumps"
    fix = f"ease {-i['size'] * a.amount:+.1f} dB over {a.ease_ms:g} ms"
    if i["kind"] == "cut" and not i.get("loop"):
        fix += f" + {a.fade_ms:g} ms fades"
    return f"{what} {abs(i['size']):.1f} dB {word}", fix


def write_json(path, src, tempo, issues, notes, a):
    """One finding per distinct problem (copies of the same audio share one finding and list all ids)."""
    import json
    out = []
    for group in grouped(issues, tempo):
        i = group[0]
        prob, fix = describe(i, a)
        size = abs(i["size"])
        if i["kind"] == "spike":
            sev = "high" if size >= 18 else "medium"
        elif i["kind"] == "cut":
            sev = "medium" if size >= 8 else "low"
        elif i["kind"] == "click":
            sev = "low" if i.get("edge") == "loop" else "medium"
        else:
            sev = "low"
        manual = i["kind"] == "click" and i.get("edge") == "loop"
        out.append(dict(id=i["id"], ids=[g["id"] for g in group], tool="smooth", kind=i["kind"],
                        severity=sev, track=i["track"], where=where(i["beat"]),
                        also_at=[where(g["beat"]) for g in group[1:]], problem=prob, fix=fix,
                        applies="set" if not manual else "manual"))
    Path(path).write_text(json.dumps({"tool": "smooth", "set": str(src), "tempo": tempo,
                                      "findings": out, "notes": {k: (sorted(v) if isinstance(v, set) else v)
                                                                 for k, v in notes.items()}},
                                     indent=1, default=str), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(prog="hypnomix smooth", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    from hypnomix.session import liveversion as LV; LV.add_force_flag(ap)
    ap.add_argument("als")
    ap.add_argument("--track", action="append", default=[], help="only these audio tracks (repeatable)")
    ap.add_argument("--spike-db", type=float, default=12.0, help="smallest burst above its surroundings (dB)")
    ap.add_argument("--steps", action="store_true", help="also flag lasting level changes inside clips")
    ap.add_argument("--step-db", type=float, default=6.0, help="smallest in-clip step with --steps (dB)")
    ap.add_argument("--cut-db", type=float, default=4.0, help="smallest level change at a cut to flag (dB)")
    ap.add_argument("--only", choices=["click", "cut", "spike", "step"], action="append", help="limit to these kinds")
    ap.add_argument("--explicit-fades", action="store_true",
                    help="also fix edges that rely on Live's automatic 4 ms edge fade")
    ap.add_argument("--include-off", action="store_true", help="also check tracks that are switched off")
    ap.add_argument("--apply", metavar="OUT.als", help="write the fixes to this new set")
    ap.add_argument("--amount", type=float, default=0.5, help="share of each jump to ease away (0-1)")
    ap.add_argument("--ease-ms", type=float, default=300.0, help="how long the eased jump takes")
    ap.add_argument("--fade-ms", type=float, default=5.0, help="clip fade length for clicks and cuts")
    ap.add_argument("--json", metavar="OUT.json", help="also write the findings as JSON (each with an id)")
    ap.add_argument("--ids", help="with --apply: only fix these finding ids (comma-separated, from --json)")
    a = ap.parse_args()
    if not 0 < a.amount <= 1:
        sys.exit("--amount must be between 0 and 1")

    src = Path(a.als)
    tree = aa.load(src)
    root = tree.getroot()
    tempo, issues, notes = analyse(root, src.parent, a.track, a.step_db if a.steps else 0, a.cut_db,
                                    a.spike_db, a.explicit_fades, a.include_off)
    if a.only:
        issues = [i for i in issues if i["kind"] in a.only]
    for n, i in enumerate(issues, 1):
        i["id"] = f"smooth-{n}"
    if a.json:
        write_json(a.json, src, tempo, issues, notes, a)

    print(f"{src.name}: {notes['clips']} arrangement audio clips checked, tempo {tempo:g} BPM\n")
    if issues:
        w = max(len(i["track"]) for i in issues)
        print(f"{'bar.beat':>9}  {'track':<{w}}  {'kind':<5}  problem / fix")
        for group in grouped(issues, tempo):
            i = group[0]
            prob, fix = describe(i, a)
            more = ""
            if len(group) > 1:
                bars = ", ".join(where(g["beat"]).split(".")[0] for g in group[1:6])
                more = f"  (same audio again at bars {bars}{', ...' if len(group) > 6 else ''})"
            print(f"{where(i['beat']):>9}  {i['track']:<{w}}  {i['kind']:<5}  {prob}  ->  {fix}{more}")
        counts = {k: sum(1 for i in issues if i["kind"] == k) for k in ("click", "cut", "spike", "step")}
        print(f"\n{len(issues)} found ({len(grouped(issues, tempo))} distinct): {counts['click']} clicks, {counts['cut']} cuts, "
              f"{counts['spike']} spikes" + (f", {counts['step']} steps" if a.steps else ""))
    else:
        print("No sudden jumps found.")
    if notes["default_fade_edges"]:
        print(f"{notes['default_fade_edges']} clip edges start or stop on sound but use Live's automatic 4 ms "
              "edge fade (Settings > Record, Warp & Launch > Create Fades on Clip Edges); "
              "--explicit-fades gives them their own fades.")
    if notes["off"]:
        print(f"skipped {len(notes['off'])} switched-off tracks (--include-off checks them): "
              + ", ".join(notes["off"]))
    if notes["regular"]:
        print("spikes not flagged on tracks with regular hits (drums, plucks): "
              + ", ".join(sorted(notes["regular"])))
    if notes["onsets"]:
        print("not flagged: loud consonants that open a sung phrase (a \"B\" or \"P\" after a breath is part of the "
              "word; dipping it cuts the word): " + ", ".join(f"{k} ({n})" for k, n in sorted(notes["onsets"].items())))
    for m in sorted(notes["missing"]):
        print(f"skipped (audio file not found): {m}")

    if a.apply:
        if not os.environ.get("HYPNOMIX_ALLOW_TMP_SET") and Path(a.apply).resolve().parent != src.resolve().parent:
            sys.exit("write the new set in the same folder as the original "
                     f"({src.resolve().parent}): samples linked by relative path go offline elsewhere")
        if not issues:
            print("Nothing to apply.")
            return
        if a.ids:
            want = {x.strip() for x in a.ids.split(",") if x.strip()}
            issues = [i for i in issues if i["id"] in want]
            if not issues:
                sys.exit("none of those ids were found (same options as the scan?)")
        done = apply(root, issues, tempo, a)
        aa.save(tree, src, a.apply)
        print(f"applied {len(done)} fixes. Close the original set in Live before opening the new one.")


if __name__ == "__main__":
    main()
