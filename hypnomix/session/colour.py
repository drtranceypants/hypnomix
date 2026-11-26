#!/usr/bin/env python3
"""Propose new colour (timbre) for a song that sounds the same throughout. Proposals only: nothing is added to your
song unless you ask for it by number.

  hypnomix colour SET.als [--mix MIX.wav] [options]          report + before/after clips, nothing written
  hypnomix colour SET.als --plan [DIR]                       the proposals as findings in a scan folder (review them,
                                                             then `hypnomix fix DIR --approved`)
  hypnomix colour SET.als --apply "SET (colour).als" --ids colour-1,colour-3
                                                             a NEW set: each chosen proposal on a new track

How it decides where colour would help (measured, not heard):
  1. The song is cut into sections on its own bar lines (the same method as `hypnomix sections`; or --block N bars).
  2. Each part (audio track) is measured in every section it plays: its tone (how its energy is spread over six
     bands, in dB), how bright it is, and its texture (notes per bar).
  3. A part "sounds the same" in a section when its tone and texture there are within --static of what it already
     did in an earlier section (the measure is in plain dB: 2.0 means "the six bands are 2 dB apart on average").
     The report lists, for each part, how much it changes from section to section, and which sections repeat it.
  4. A proposal goes where a part repeats itself AND the whole mix repeats too (the section also sounds like an
     earlier one): the first time through is left alone.

Each proposal is a chain of Live's own devices on a COPY of that part, on a new track right after it, in the same
group, with the same devices and sends, SWITCHED OFF, holding only the clips for those bars. Turn it on and (if you
like) turn the original off for those bars. The chain starts from a preset in Live's own library, then sets a few
values by name. Families of colour (--family, repeatable; default: whichever the part's measurements suggest):

  width     chorus and a Utility width: the part opens out (never proposed for bass)
  grit      Saturator: harmonics, more bite
  space     Reverb: a room for tight parts, a hall for sustained ones
  movement  Auto Filter: a slow filter drift
  octave    Shifter: a quiet copy an octave up (or --octave down), mixed in under the part

Options:
  --part NAME        only these parts (repeatable; start of the track name)
  --family F         only these families
  --max N            how many proposals in all (default 3)       --per-part N   at most this many per part (default 1)
  --amount 0-1       how strong (default 0.5; per proposal later with --tweak colour-2:amount=0.3)
  --static DB        how close counts as "the same" (default 2.0 dB; larger = more places qualify)
  --block N          sections of N bars instead of the song's own sections
  --mix MIX.wav      measure the mix from this file instead of summing the tracks
  --library DIR      Live's library folder (the folder that holds "Core Library"); found automatically
  --no-clips         skip the before / after files
  --json OUT.json    the proposals as data

Before / after: for each proposal, four bars of the part as it is, and the same bars through a model of the chain
(A and B, level matched). The model is an approximation written for hypnomix, not Live's device: it shows the
direction, and only Live plays the real thing.

What is not here yet: it writes Live sets only (REAPER and Ardour projects are not written yet: the report works
on any set Live can save). Installed free plug-ins from `hypnomix plugins --save` are NAMED as alternatives to try;
hypnomix does not write a third-party plug-in into a set (their settings are not something it touches), so the chain
itself is Live's. A new instrument doubling a line (from `midi`) is not built yet.

Close the set in Live before --apply. `hypnomix check` runs on the result, and the set is not opened in Live here.
"""
import argparse, copy, gzip, json, os, re, sys, warnings
from hypnomix.core.gz import read_gz
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

SR = 22050
BANDS = [0, 120, 400, 1200, 3000, 6000, 11025]
BAND_NAMES = ["low (under 120 Hz)", "low-mid (120-400)", "mid (400-1.2k)", "upper-mid (1.2-3k)", "presence (3-6k)", "air (over 6k)"]
FAMILIES = ("width", "grit", "space", "movement", "octave")
DRUM_WORDS = ("drum", "kick", "snare", "hat", "perc", "kit", "beat", "clap", "tom", "cymbal")
BASS_WORDS = ("bass", "sub", "808")
LIB_SUB = "Core Library/Devices/Audio Effects"
ACTIVE_DB = -50.0            # a frame counts as playing when it is within this many dB of the part's own loudest


# ---------------------------------------------------------------- measuring
def frames_power(y, n_fft=2048, hop=512):
    import librosa
    S = np.abs(librosa.stft(y.astype(np.float32), n_fft=n_fft, hop_length=hop)) ** 2
    return S, librosa.fft_frequencies(sr=SR, n_fft=n_fft)


def notes_in(y):
    """How many note starts there are: peaks of the spectral flux (in dB of rise, so a steady tone has none) above a
    fixed height, not librosa's normalised detector, which finds a hundred onsets in a held chord."""
    import librosa
    from scipy.signal import find_peaks
    if len(y) < 4096:
        return 0
    env = librosa.onset.onset_strength(y=y.astype(np.float32), sr=SR, hop_length=512)
    pk, _ = find_peaks(env, height=2.0, distance=6)
    return len(pk)


def window_features(S, freqs, a, b, loud_ref, density_bars, y_seg):
    """Tone, brightness and texture of frames a..b of the power spectrogram S (None when the part is not playing)."""
    if b - a < 2:
        return None
    seg = S[:, a:b]
    tot = seg.sum(axis=0)
    db = 10 * np.log10(tot + 1e-12)
    act = db > loud_ref + ACTIVE_DB
    if act.mean() < 0.25:
        return None
    sp = seg[:, act].sum(axis=1) + 1e-12
    shares = []
    for lo, hi in zip(BANDS[:-1], BANDS[1:]):
        m = (freqs >= lo) & (freqs < hi)
        shares.append(float(np.clip(10 * np.log10(sp[m].sum() / sp.sum() + 1e-12), -40, 0)))
    cent = float((freqs * sp).sum() / sp.sum())
    return dict(bands=shares, centroid=round(cent), density=round(notes_in(y_seg) / max(1e-9, density_bars), 2),
                level_db=round(float(10 * np.log10(sp.sum() / max(1, act.sum()) / 2048 + 1e-12)), 1),
                active=round(float(act.mean()), 2))


def change(f1, f2):
    """How different two measurements of the same part are: tone (mean dB apart over the six bands), texture
    (octaves of difference in notes per bar), and the two together as one number of dB-equivalents."""
    tone = float(np.mean(np.abs(np.array(f1["bands"]) - np.array(f2["bands"]))))
    tex = abs(float(np.log2((f1["density"] + 0.25) / (f2["density"] + 0.25))))
    return dict(tone=round(tone, 2), texture=round(tex, 2), total=round(tone + 3.0 * tex, 2))


def sections_of(mix, nbars, spb, block=None):
    """[(first bar, last bar + 1, label)] on the set's own bar lines. Uses the sections method; --block N cuts
    every N bars instead."""
    if block:
        b = list(range(0, nbars, block)) + [nbars]
        if len(b) > 2 and b[-1] - b[-2] < block // 2:
            b.pop(-2)
        return [(x, y, chr(65 + i % 26)) for i, (x, y) in enumerate(zip(b[:-1], b[1:]))], "fixed blocks"
    from hypnomix.ears import sections as S
    bars = np.arange(nbars) * 4 * spb
    if nbars < 8:
        return [(0, nbars, "A")], "too short to cut"
    F = S.bar_features(mix, SR, bars)
    bounds = S.segment(F)
    labels = S.group(F, bounds)
    return [(int(a), int(b), labels[i]) for i, (a, b) in enumerate(zip(bounds[:-1], bounds[1:]))], "the song's own sections"


def measure_parts(parts, mix, secs, spb):
    """{name: [features or None per section]} and the mix's own per section."""
    out = {}
    jobs = list(parts.items()) + [("\0mix", mix)]
    for name, y in jobs:
        S, fr = frames_power(y)
        hop_s = 512 / SR
        db = 10 * np.log10(S.sum(axis=0) + 1e-12)
        ref = float(np.percentile(db, 99)) if len(db) else -100.0
        row = []
        for a, b, _ in secs:
            t0, t1 = a * 4 * spb, b * 4 * spb
            fa, fb = int(t0 / hop_s), min(S.shape[1], int(t1 / hop_s))
            row.append(window_features(S, fr, fa, fb, ref, b - a, y[int(t0 * SR):int(t1 * SR)]))
        out[name] = row
    mixrow = out.pop("\0mix")
    return out, mixrow


def sameness(rows, static):
    """For each part: how much it changes between sections, and for each section the closest EARLIER section."""
    res = {}
    for name, row in rows.items():
        play = [i for i, f in enumerate(row) if f]
        pairs = [change(row[i], row[j])["total"] for k, i in enumerate(play) for j in play[:k]]
        near = {}
        for k, i in enumerate(play):
            if k == 0:
                continue
            best = min(((change(row[i], row[j]), j) for j in play[:k]), key=lambda x: x[0]["total"])
            near[i] = dict(best[0], like=best[1])
        res[name] = dict(plays=play, mean_change=round(float(np.mean(pairs)), 2) if pairs else None, near=near,
                         static=bool(pairs) and float(np.mean(pairs)) < static)
    return res


# ---------------------------------------------------------------- choosing a family
def role_of(name, tr):
    n = name.lower()
    if any(w in n for w in DRUM_WORDS):
        return "drums"
    if any(w in n for w in BASS_WORDS) or tr["centroid"] < 200:
        return "bass"
    return "tonal" if tr["density"] <= 3.0 else "busy"


FIT = {   # how well each family suits each kind of part (0 = never)
    "bass":  dict(width=0.0, grit=1.0, space=0.1, movement=0.5, octave=0.7),
    "drums": dict(width=0.4, grit=1.0, space=0.8, movement=0.3, octave=0.0),
    "tonal": dict(width=0.9, grit=0.5, space=0.8, movement=1.0, octave=0.7),
    "busy":  dict(width=0.8, grit=0.7, space=0.7, movement=0.5, octave=0.4),
}
WHY = {
    "width": "it plays {d:g} notes a bar and sits narrow in the middle of the mix, so a chorus and some width give it room beside the others",
    "grit": "its top end is dark ({c} Hz brightness): a little saturation adds harmonics so it cuts through where it repeats",
    "space": "it is {kind}: a reverb gives the repeat a different distance from the listener",
    "movement": "it sustains ({d:g} notes a bar), so a slow filter drift keeps it from sounding frozen across the repeat",
    "octave": "it is tonal ({d:g} notes a bar): a quiet copy an octave away changes its weight without changing the notes",
}


def pick_family(name, tr, allowed, used):
    """The best family for this part that is allowed, preferring ones not used yet in this report."""
    role = role_of(name, tr)
    best, best_s = None, 0.0
    for f in allowed:
        s = FIT[role][f] * (0.55 if f in used else 1.0)
        if f == "grit" and tr["centroid"] < 2500:
            s += 0.15
        if f == "movement" and tr["density"] <= 2.0:
            s += 0.1
        if s > best_s:
            best, best_s = f, s
    return best, role


def why(family, name, tr, role):
    kind = "tight and busy (a room)" if tr["density"] > 3 else "sustained (a hall)"
    return WHY[family].format(d=tr["density"], c=tr["centroid"], kind=kind)


# ---------------------------------------------------------------- the chains (Live's own devices, from its library)
def recipe(family, tr, role, amount, octave="auto"):
    """[dict(tag, preset, label, set={parameter: value}, say)] in order. Parameter names are Live's own element names."""
    a = float(np.clip(amount, 0.0, 1.0))
    if family == "grit":
        drive = 4 + 10 * a
        return [dict(tag="Saturator", preset="Saturator/Basic Soft", label="Saturator",
                     set=dict(PreDrive=round(drive, 1), PostDrive=round(-0.55 * drive, 1), DryWet=round(0.3 + 0.4 * a, 2)),
                     say=f"drive {drive:.0f} dB, {int((0.3 + 0.4 * a) * 100)}% wet")]
    if family == "width":
        wet, wd = 0.25 + 0.4 * a, 1 + 0.8 * a
        return [dict(tag="Chorus2", preset="Chorus-Ensemble/Chorus Classic", label="Chorus-Ensemble",
                     set=dict(DryWet=round(wet, 2), Width=0.9), say=f"{int(wet * 100)}% wet"),
                dict(tag="StereoGain", preset="Utility/Bass Mono", label="Utility",
                     set=dict(StereoWidth=round(wd, 2), BassMono=True, BassMonoFrequency=150.0),
                     say=f"width {int(wd * 100)}%, bass kept in the middle under 150 Hz")]
    if family == "space":
        k = 0.15 + 0.6 * a
        hall = tr["density"] <= 3.0
        base = ("Reverb/Hall/Medium Hall", "a medium hall") if hall else ("Reverb/Room/Ambience Medium", "a medium room")
        return [dict(tag="Reverb", preset=base[0], label="Reverb",
                     set=dict(MixDiffuse=round(1.0 * k, 3), MixReflect=round(1.6 * k, 3), MixDirect=1.0),
                     say=f"{base[1]}, wet level {int(k * 100)}% of the preset's")]
    if family == "movement":
        return [dict(tag="AutoFilter2", preset="Auto Filter/Move & Color", label="Auto Filter",
                     set=dict(DryWet=round(0.35 + 0.4 * a, 2), Lfo_Amount=round(0.2 + 0.4 * a, 2)),
                     say=f"a slow filter drift, {int((0.35 + 0.4 * a) * 100)}% wet")]
    up = octave == "up" or (octave == "auto" and tr["centroid"] < 2500)
    return [dict(tag="Shifter", preset="Shifter/Stereo Vibrato", label="Shifter",
                 set=dict(Global_ShifterMode=0, Pitch_Coarse=12.0 if up else -12.0, Pitch_Fine=0.0, Lfo_Amount=0.0,
                          Lfo_AmountPitch=0.0, EnvelopeFollower_AmountHz=0.0, EnvelopeFollower_AmountPitch=0.0,
                          Delay_On=False, Delay_Feedback=0.0, Global_Wide=False,
                          Global_DryWet=round(0.15 + 0.3 * a, 2)),
                 say=f"a copy an octave {'up' if up else 'down'}, {int((0.15 + 0.3 * a) * 100)}% wet")]


def alternatives(family, prefs):
    """Names of installed free plug-ins (from `hypnomix plugins --save`) that suit this family of colour."""
    from hypnomix.session import plugins as P
    use = {"space": "space", "grit": "grit", "movement": "movement", "width": "movement"}.get(family)
    return [n for n, u in P.installed_with_use(prefs, use)] if use else []


# ---------------------------------------------------------------- the model used for the "B" clip
def _stereo(y):
    return np.stack([y, y], axis=1).astype(np.float32)


def _mod_delay(y, centre_ms, depth_ms, rate, phase, sr=SR):
    n = np.arange(len(y))
    d = (centre_ms + depth_ms * np.sin(2 * np.pi * rate * n / sr + phase)) * sr / 1000.0
    pos = np.clip(n - d, 0, len(y) - 1)
    i = pos.astype(int)
    f = pos - i
    j = np.minimum(i + 1, len(y) - 1)
    return y[i] * (1 - f) + y[j] * f


def preview_model(y, family, steps, tr, sr=SR):
    """An approximation of the chain, mono in, stereo out. Not Live's own algorithms."""
    from scipy.signal import fftconvolve, lfilter, butter
    s = {k: v for st in steps for k, v in st["set"].items()}
    if family == "grit":
        g = 10 ** (s["PreDrive"] / 20)
        wet = np.tanh(g * y) / np.tanh(g) * 10 ** (s["PostDrive"] / 20 + (s["PreDrive"] / 20) * 0.35)
        w = s["DryWet"]
        return _stereo((1 - w) * y + w * wet)
    if family == "width":
        w, wd = s["DryWet"], s["StereoWidth"]
        L = _mod_delay(y, 11.0, 3.0, 0.8, 0.0, sr)
        R = _mod_delay(y, 11.0, 3.0, 0.8, np.pi, sr)
        mid = y * (1 - w * 0.5)
        l, r = mid + w * 0.8 * L, mid + w * 0.8 * R
        m, side = (l + r) / 2, (l - r) / 2 * wd
        return np.stack([m + side, m - side], axis=1).astype(np.float32)
    if family == "space":
        rt = 1.8 if tr["density"] <= 3.0 else 0.7
        n = int(rt * sr)
        t = np.arange(n) / sr
        out = []
        for seed in (1, 2):
            rng = np.random.default_rng(seed)
            ir = rng.standard_normal(n) * np.exp(-6.9 * t / rt)
            ir[: int(0.012 * sr)] *= 0.1
            wet = fftconvolve(y, ir / np.sqrt(np.sum(ir ** 2) + 1e-9))[: len(y)]
            out.append(y + wet * s["MixDiffuse"] * 2.2)
        return np.stack(out, axis=1).astype(np.float32)
    if family == "movement":
        w, depth = s["DryWet"], s["Lfo_Amount"]
        out = np.zeros_like(y)
        blk, zi = 256, None
        for i in range(0, len(y), blk):
            c = 900 * 2 ** (depth * 2.5 * np.sin(2 * np.pi * 0.35 * i / sr))
            b, a_ = butter(2, min(0.45, c / (sr / 2)))
            if zi is None:
                zi = np.zeros(max(len(a_), len(b)) - 1)
            out[i:i + blk], zi = lfilter(b, a_, y[i:i + blk], zi=zi)
        return _stereo((1 - w) * y + w * out * 1.2)
    import librosa
    sh = librosa.effects.pitch_shift(y.astype(np.float32), sr=sr, n_steps=s["Pitch_Coarse"])
    return _stereo(y + s["Global_DryWet"] * 2.0 * sh)


# ---------------------------------------------------------------- Live's library and the set
def find_library(arg=None):
    """The 'Audio Effects' folder of Live's Core Library, or None."""
    import glob
    for c in ([arg] if arg else [os.environ.get("HYPNOMIX_LIVE_LIBRARY")]):
        if c:
            p = Path(c)
            for q in (p, p / LIB_SUB, p / "Devices/Audio Effects", p / "Audio Effects"):
                if (q / "Saturator").exists() or (q / "Reverb").exists():
                    return q
            return None                      # a folder that was named but holds no library: say so, don't guess
    hits = glob.glob(f"/Applications/Ableton Live*/Contents/App-Resources/{LIB_SUB}") + \
        glob.glob(f"C:/ProgramData/Ableton/Live*/Resources/{LIB_SUB}")
    return Path(sorted(hits)[-1]) if hits else None


def load_preset(lib, rel):
    f = Path(lib) / (rel + ".adv") if lib else None
    if not f or not f.exists():
        return None
    return ET.fromstring(read_gz(f))[0]


def template_for(step, lib, root):
    """(device element, where it came from) or (None, why not)."""
    d = load_preset(lib, step["preset"])
    if d is not None and d.tag == step["tag"]:
        return d, f"Live's library preset '{step['preset']}'"
    for e in root.iter(step["tag"]):                 # the set already holds one: copy it as the starting point
        if e.find("./On/Manual") is not None:
            return copy.deepcopy(e), "a device of this kind already in the set"
    return None, (f"Live's library was not found (pass --library)" if lib is None else
                  f"preset '{step['preset']}' is not in Live's library")


def build_device(root, step, tpl, dev_id, label):
    """A new device element from the template: fresh ids, the recipe's values, named so it can be found."""
    d = copy.deepcopy(tpl)
    npi = root.find(".//NextPointeeId")
    nid = int(npi.get("Value"))
    for e in d.iter():
        if e.tag in ("AutomationTarget", "ModulationTarget", "Pointee") and e.get("Id") is not None:
            e.set("Id", str(nid))
            nid += 1
    npi.set("Value", str(nid))
    d.set("Id", str(dev_id))
    missing = []
    for k, val in step["set"].items():
        m = d.find(f"./{k}/Manual")
        if m is None:
            missing.append(k)
            continue
        m.set("Value", ("true" if val else "false") if isinstance(val, bool) else repr(float(val)))
    on = d.find("./On/Manual")
    if on is not None:
        on.set("Value", "true")
    un = d.find("./UserName")
    if un is not None:
        un.set("Value", label)
    pr = d.find("./LastPresetRef/Value")
    if pr is not None:
        for c in list(pr):
            pr.remove(c)
    return d, missing


def add_chain(root, track, steps, lib, label):
    """Append the chain to the track's devices. Returns (ok, notes)."""
    devs = track.find("./DeviceChain/DeviceChain/Devices")
    if devs is None:
        return False, ["the track has no device chain to add to"]
    ids = [int(d.get("Id")) for d in devs if (d.get("Id") or "").isdigit()]
    nxt = (max(ids) + 1) if ids else 0
    notes, built = [], []
    for st in steps:
        tpl, src = template_for(st, lib, root)
        if tpl is None:
            return False, [f"{st['label']}: {src}"]
        d, missing = build_device(root, st, tpl, nxt, label)
        if missing:
            return False, [f"{st['label']}: this version of Live's device has no {', '.join(missing)}: not written"]
        built.append(d)
        notes.append(f"{st['label']}: from {src}")
        nxt += 1
    for d in built:
        devs.append(d)
    return True, notes


def bar_window_clips(plays, tempo, a_beat, b_beat):
    """New clips (deep copies, trimmed) for the part's plays inside [a_beat, b_beat)."""
    from hypnomix.session import variations as V
    out = []
    for p in plays:
        s, e = max(p["start"], a_beat), min(p["start"] + p["len"], b_beat)
        if e - s < 1e-6:
            continue
        k = (p["f1"] - p["f0"]) / p["len"]
        g0, g1 = p["f0"] + (s - p["start"]) * k, p["f0"] + (e - p["start"]) * k
        q = dict(p, len=e - s)
        out.append(V.new_clip(q, g0, g1, s, tempo))
    return out


# ---------------------------------------------------------------- proposals
def render_parts(root, src, tempo, only=()):
    from hypnomix.session import render as R, beats as B
    spb = 60.0 / tempo
    end, _ = R.song_end(root)
    N = int((end + 4) * spb * SR)
    parts, warn = {}, []
    for t in root.find(".//Tracks"):
        if t.tag != "AudioTrack" or R.v(t, "./DeviceChain/Mixer/Speaker/Manual") == "false":
            continue
        name = R.v(t, "./Name/EffectiveName")
        if not B.clips_of(t):
            continue
        y = R.render_track(t, str(src), spb, N, SR, None, 0, warn)
        if y is not None and np.any(np.abs(y) > 1e-5):
            parts[name] = y.astype(np.float32)
    return parts, warn, spb, N


def propose(parts, mix, spb, N, a):
    nbars = int(N / SR / (4 * spb))
    secs, how = sections_of(mix, nbars, spb, a.block)
    rows, mixrow = measure_parts(parts, mix, secs, spb)
    same = sameness(rows, a.static)
    mixnear = {}
    for i, f in enumerate(mixrow):
        if f and i:
            prior = [(change(f, mixrow[j]), j) for j in range(i) if mixrow[j]]
            if prior:
                c, j = min(prior, key=lambda x: x[0]["total"])
                mixnear[i] = dict(c, like=j)
    cands = []
    for name, info in same.items():
        for i, nr in info["near"].items():
            if nr["total"] < a.static and secs[i][1] - secs[i][0] >= 2:
                mr = mixnear.get(i)
                score = nr["total"] + 0.5 * (mr["total"] if mr else a.static)
                cands.append(dict(part=name, section=i, near=nr, mixnear=mr, score=score))
    cands.sort(key=lambda c: (c["score"], c["part"], c["section"]))
    props, used_parts, used_fam = [], {}, set()
    allowed = [f for f in (a.family or FAMILIES)]
    for c in cands:
        if len(props) >= a.max:
            break
        if used_parts.get(c["part"], 0) >= a.per_part:
            continue
        if a.part and not any(c["part"].lower().startswith(x.lower()) for x in a.part):
            continue
        tr = rows[c["part"]][c["section"]]
        fam, role = pick_family(c["part"], tr, allowed, used_fam)
        if not fam:
            continue
        used_parts[c["part"]] = used_parts.get(c["part"], 0) + 1
        used_fam.add(fam)
        s0, s1, lab = secs[c["section"]]
        like = secs[c["near"]["like"]]
        props.append(dict(c, family=fam, role=role, bar0=s0 + 1, bar1=s1, label=lab, traits=tr,
                          like_bars=(like[0] + 1, like[1]), amount=a.amount, octave=a.octave))
    for n, p in enumerate(props, 1):
        p["id"] = f"colour-{n}"
    return props, secs, rows, same, mixrow, how


def finding(p, prefs, lib_ok):
    nr, mn = p["near"], p["mixnear"]
    chain = recipe(p["family"], p["traits"], p["role"], p["amount"], p["octave"])
    alt = alternatives(p["family"], prefs)
    mixtxt = (f"; the whole mix there is also within {mn['total']:.1f} dB of bars {p['like_bars'][0]}-{p['like_bars'][1]}"
              if mn and mn["like"] is not None else "")
    return dict(
        id=p["id"], tool="colour", kind=f"colour-{p['family']}", severity="info", track=p["part"],
        where=f"bars {p['bar0']}-{p['bar1']}", applies="set",
        problem=(f"{p['part']} in bars {p['bar0']}-{p['bar1']} sounds like it did in bars {p['like_bars'][0]}-{p['like_bars'][1]}: "
                 f"tone {nr['tone']:.1f} dB apart, texture {nr['texture']:.2f} octaves apart (measured){mixtxt}"),
        fix=(f"{p['family']}: " + "; ".join(f"{c['label']} ({c['say']})" for c in chain) +
             f", on a new switched-off track '{p['part']} (colour: {p['family']})' holding only those bars. "
             f"Why this family: {why(p['family'], p['part'], p['traits'], p['role'])}. An option, not a fix: turn it on and "
             f"listen" + (f". Free plug-ins you have that suit this: {', '.join(alt)} (add by hand; hypnomix does not write a "
                          "plug-in into a set)" if alt else "")),
        colour=dict(part=p["part"], family=p["family"], bar0=p["bar0"], bar1=p["bar1"], amount=p["amount"],
                    role=p["role"], traits=p["traits"], chain=[{k: c[k] for k in ("tag", "preset", "label", "set", "say")} for c in chain]),
        writable=lib_ok)


# ---------------------------------------------------------------- output
def md_report(src, how, secs, rows, same, props, fs, a, lines_warn):
    md = [f"# Colour: {src.name}", "",
          "Where a part repeats itself and the mix repeats with it, and what colour could be tried there. Measured, not heard:",
          f"'same' means within {a.static:g} dB-equivalents of the part's own earlier section (tone: mean dB apart over six bands; "
          "texture: octaves of difference in notes per bar, counted three-fold).", "",
          f"Sections ({how}): " + ", ".join(f"{lab} bars {x + 1}-{y}" for x, y, lab in secs), "",
          "## How much each part changes from section to section", "",
          "| part | plays in | mean change | verdict |", "|---|---|---|---|"]
    for name, info in sorted(same.items(), key=lambda kv: (kv[1]["mean_change"] is None, kv[1]["mean_change"] or 0)):
        mc = info["mean_change"]
        md.append(f"| {name} | {len(info['plays'])} of {len(secs)} sections | {'-' if mc is None else f'{mc:.1f} dB'} | "
                  + ("plays one section: nothing to compare" if mc is None else
                     ("sounds the same throughout" if info["static"] else "changes")) + " |")
    md += ["", "## Proposals", ""]
    if not fs:
        md.append("none: no part repeats itself closely enough (try a larger --static, or --block 8).")
    for f, p in zip(fs, props):
        md += [f"### {f['id']}: {p['part']}, bars {p['bar0']}-{p['bar1']}: {p['family']}", "", f"- Why here: {f['problem']}",
               f"- The chain: {f['fix']}"]
        if not f["writable"]:
            md.append("- Cannot be written into a set from here: Live's library was not found (pass --library). The report and clips still work.")
        md.append("")
    md += lines_warn
    return "\n".join(md) + "\n"


def write_pairs(od, props, fs, parts, spb, a, manifest):
    from hypnomix.workflow import ab as AB
    import soundfile as sf
    od = Path(od)
    od.mkdir(parents=True, exist_ok=True)
    for p, f in zip(props, fs):
        y = parts[p["part"]]
        t0, t1 = (p["bar0"] - 1) * 4 * spb, p["bar1"] * 4 * spb
        seg = y[int(t0 * SR):int(t1 * SR)]
        if len(seg) < SR:
            manifest[p["id"]] = dict(note="no preview: too little audio in these bars")
            continue
        win = int(min(len(seg), 4 * 4 * spb * SR))                      # the loudest four bars of the section
        hop = max(1, int(4 * spb * SR))
        starts = range(0, max(1, len(seg) - win + 1), hop)
        s0 = max(starts, key=lambda s: float(np.sum(seg[s:s + win] ** 2)))
        a_ = seg[s0:s0 + win]
        chain = [dict(set=c["set"]) for c in f["colour"]["chain"]]
        b_ = preview_model(a_, p["family"], chain, p["traits"])
        manifest[p["id"]] = AB.write_pair(od, p["id"], _stereo(a_), b_, SR,
                                          "the part alone through a model of the chain (an approximation: only Live plays the real devices)")


def track_name(c):
    """The new track's name, from a finding's `colour` dict."""
    return f"{c['part']} (colour: {c['family']} {c['bar0']}-{c['bar1']})"


def apply_to_set(root, src, props, fs, ids, tempo, lib, tweaks=None):
    from hypnomix.session import variations as V, beats as B
    from hypnomix.session import automation as aa
    bpb = aa.BPB
    added, notes = [], []
    for p, f in zip(props, fs):
        if p["id"] not in ids:
            continue
        t = next(x for x in root.find(".//Tracks") if x.tag == "AudioTrack" and x.find("./Name/EffectiveName").get("Value") == p["part"])
        amount = (tweaks or {}).get(p["id"], {}).get("amount", p["amount"])
        steps = recipe(p["family"], p["traits"], p["role"], amount, p["octave"])
        name = track_name(p)
        clips = bar_window_clips(V.plays(t, Path(src).parent, tempo, bpb), tempo, (p["bar0"] - 1) * bpb, p["bar1"] * bpb)
        if not clips:
            notes.append(f"{p['id']}: no clip of {p['part']} plays in bars {p['bar0']}-{p['bar1']}: skipped")
            continue
        new, ev = V.clone_track(root, t, name)
        ok, n = add_chain(root, new, steps, lib, f"colour: {p['family']}")
        if not ok:
            root.find(".//Tracks").remove(new)
            notes.append(f"{p['id']}: not written: " + "; ".join(n))
            continue
        for i, c in enumerate(sorted(clips, key=lambda c: float(c.get("Time")))):
            c.set("Id", str(i))
            ev.append(c)
        added.append(name)
        notes.append(f"{p['id']}: {name!r}: {len(clips)} clip(s), " + "; ".join(n) + "; switched off")
    return added, notes


def main():
    ap = argparse.ArgumentParser(prog="hypnomix colour", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als")
    ap.add_argument("--part", action="append", default=[])
    ap.add_argument("--family", action="append", choices=FAMILIES, default=[])
    ap.add_argument("--max", type=int, default=3)
    ap.add_argument("--per-part", type=int, default=1, dest="per_part")
    ap.add_argument("--amount", type=float, default=0.5)
    ap.add_argument("--static", type=float, default=2.0)
    ap.add_argument("--block", type=int)
    ap.add_argument("--octave", choices=("auto", "up", "down"), default="auto")
    ap.add_argument("--mix")
    ap.add_argument("--library")
    ap.add_argument("--no-clips", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--json")
    ap.add_argument("--plan", nargs="?", const=True)
    ap.add_argument("--apply", metavar="NEW.als")
    ap.add_argument("--ids")
    ap.add_argument("--tweak", action="append", default=[], help='"colour-2:amount=0.3" (repeatable)')
    ap.add_argument("--prefs-file", help=argparse.SUPPRESS)
    from hypnomix.session import liveversion as LV; LV.add_force_flag(ap)
    a = ap.parse_args()
    if not 0 <= a.amount <= 1:
        sys.exit("--amount is between 0 and 1")
    from hypnomix.session import automation as aa, beats as B
    from hypnomix.core.paths import out_at
    from hypnomix.workflow import prefs as PF
    src = Path(a.als)
    if src.suffix.lower() != ".als":
        sys.exit("colour writes Live sets (.als) for now. REAPER and Ardour projects are not written yet; "
                 "the proposals themselves could be, ask for them to be added.")
    tree = aa.load(src)
    root = tree.getroot()
    tempo = B.set_tempo(root)
    if B.tempo_points(root):
        sys.exit("this set has tempo automation: colour needs a constant tempo (bars are measured on the grid)")
    parts, warn, spb, N = render_parts(root, src, tempo)
    if len(parts) < 1:
        sys.exit("no audio track plays in this set")
    if a.mix:
        import soundfile as sf
        import librosa
        m, msr = sf.read(a.mix, dtype="float32", always_2d=True)
        mix = librosa.resample(m.mean(axis=1), orig_sr=msr, target_sr=SR) if msr != SR else m.mean(axis=1)
        mix = np.pad(mix, (0, max(0, N - len(mix))))[:N]
    else:
        mix = np.sum([y[:N] for y in parts.values()], axis=0)
    props, secs, rows, same, mixrow, how = propose(parts, mix, spb, N, a)
    prefs = PF.load(a.prefs_file)
    lib = find_library(a.library)
    tw = {}
    for it in a.tweak:
        fid, _, kv = it.partition(":")
        for pair in kv.replace(" ", ",").split(","):
            k, _, x = pair.partition("=")
            if k.strip() == "amount":
                try:
                    tw[fid.strip()] = {"amount": float(np.clip(float(x), 0, 1))}
                except ValueError:
                    pass
    for p in props:
        p["amount"] = tw.get(p["id"], {}).get("amount", p["amount"])
    fs = [finding(p, prefs, lib is not None) for p in props]

    print(f"{src.name}: {tempo:g} BPM, {len(parts)} parts, {len(secs)} sections ({how})\n")
    print(f"{'part':<24} {'plays':>9} {'changes by':>11}  verdict")
    for name, info in sorted(same.items(), key=lambda kv: (kv[1]["mean_change"] is None, kv[1]["mean_change"] or 0)):
        mc = info["mean_change"]
        print(f"{name[:24]:<24} {len(info['plays']):>3}/{len(secs):<5} {'-' if mc is None else f'{mc:.1f} dB':>11}  "
              + ("one section only" if mc is None else ("sounds the same throughout" if info["static"] else "changes")))
    print()
    if not fs:
        print(f"no proposals: no part repeats an earlier section within {a.static:g} dB (try --static {a.static + 1.5:g} or --block 8)")
    for f in fs:
        print(f"  {f['id']:<9} {f['track'][:22]:<22} {f['where']:<14} {f['kind'].split('-', 1)[1]:<9} {f['fix'].split(', on a new')[0].split(': ', 1)[1]}")
    if fs and lib is None:
        print("\nLive's library was not found: the proposals cannot be written into a set (pass --library DIR).")
    if lib is not None and fs:
        print(f"\nchains start from Live's own library presets ({lib})")

    od = out_at(a.out, "colour", src.stem)
    manifest = {}
    if not a.no_clips and fs:
        write_pairs(od / "clips", props, fs, parts, spb, a, manifest)
        print(f"\nbefore / after clips: {od / 'clips'}")
    (od / "COLOUR.md").write_text(md_report(src, how, secs, rows, same, props, fs, a, [f"Not heard: {len(warn)} problem(s) rendering the tracks" if warn else ""]))
    doc = dict(tool="colour", set=str(src), tempo=tempo, sections=[dict(bars=[x + 1, y], label=lab) for x, y, lab in secs],
               parts={n: dict(mean_change=i["mean_change"], static=i["static"], plays=i["plays"]) for n, i in same.items()},
               findings=fs, ab=manifest)
    (od / "colour.json").write_text(json.dumps(doc, indent=1, default=str))
    if a.json:
        Path(a.json).write_text(json.dumps(doc, indent=1, default=str))
    print(f"\n{len(fs)} proposal(s) → {od}")

    if a.plan:
        from hypnomix.workflow import plan as PL
        sd = PL.scan_dir(a.plan if isinstance(a.plan, str) else None, src, " (colour)")
        PL.write(sd, "colour", src, fs, ["colour: every proposal is an OPTION on a new switched-off track",
                                         f"colour: sections from {how}"])
        sj = Path(sd) / "scan.json"
        info = json.loads(sj.read_text()) if sj.exists() else {}
        info.update(mode="set", mix=a.mix, colour_args=colour_args(a))
        sj.write_text(json.dumps(info, indent=1))
        if manifest:
            (Path(sd) / "ab").mkdir(exist_ok=True)
            import shutil
            for f in (od / "clips").glob("*.wav"):
                shutil.copyfile(f, Path(sd) / "ab" / f.name)
            (Path(sd) / "ab" / "ab.json").write_text(json.dumps(manifest, indent=1))

    if a.apply:
        out = Path(a.apply)
        if out.resolve() == src.resolve():
            sys.exit("refusing to overwrite the set; give a new file name")
        want = {x.strip() for x in (a.ids or "").split(",") if x.strip()}
        if not want:
            sys.exit("say which proposals: --ids colour-1,colour-3 (none is added by default)")
        unknown = want - {p["id"] for p in props}
        if unknown:
            sys.exit(f"no such proposal: {', '.join(sorted(unknown))} (this run's are {', '.join(p['id'] for p in props) or 'none'})")
        if lib is None and not any(True for _ in root.iter("Saturator")):
            print("note: Live's library was not found; only devices already in the set can be copied", file=sys.stderr)
        added, notes = apply_to_set(root, src, props, fs, want, tempo, lib, tw)
        for n in notes:
            print("  " + n)
        if not added:
            sys.exit("nothing was added")
        ok = B.finish(tree, src, out, added=added)
        print(f"wrote {out.name}: {len(added)} new switched-off track(s)" if ok else "")
        if not ok:
            sys.exit(1)


def colour_args(a):
    """The options a later run must repeat to find the same proposals again (fix re-finds them by position)."""
    out = []
    for x in a.part:
        out += ["--part", x]
    for x in a.family:
        out += ["--family", x]
    out += ["--max", str(a.max), "--per-part", str(a.per_part), "--amount", str(a.amount), "--static", str(a.static),
            "--octave", a.octave]
    if a.block:
        out += ["--block", str(a.block)]
    if a.library:
        out += ["--library", a.library]
    return out


if __name__ == "__main__":
    main()
