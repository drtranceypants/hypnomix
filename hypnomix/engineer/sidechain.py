#!/usr/bin/env python3
"""Make sidechain compression sound good: measure what each sidechained Compressor or Glue Compressor
in a Live set actually does to the music, and suggest settings that duck cleanly and in time.

For every Compressor and Glue Compressor with its sidechain on, it simulates the compressor driven by the trigger track
and measures, hit by hit:

  depth        how far the target is turned down (dB)
  recovery     how much of that has come back by the next hit (100% = fully back in time)
  back at      when the gain is 90% back, against the gap to the next hit
  consistency  how much the depth varies between hits (a steady groove wants a steady duck)
  low end      a release (or attack) shorter than about two cycles of the target's lowest note
               bends the waveform and sounds like distortion or clicks on bass

Then it searches for settings that hit a style:

  clarity     (default for drum triggers) 2-4 dB, back before the next hit: kick and bass stop
              fighting without audible pumping
  pump        6-10 dB with the release timed so the level comes back right at the next hit
  vocal-duck  (default for returns fed by a vocal) about 3 dB while the singer sings, ~10 ms attack,
              200-400 ms release: delays and reverbs get out of the way, then bloom in the gaps

Usage:
  hypnomix sidechain SET.als [--stems DIR] [--style clarity|pump|vocal-duck] [--out DIR]
  hypnomix sidechain SET.als --apply "SET (sidechain).als"       # write the suggestions to a new set
  hypnomix sidechain SET.als --glue-to-compressor --apply "SET (compressor).als"
                     # swap sidechained Glue Compressors for Live's Compressor (same routing, lookahead on)
  hypnomix sidechain --trigger kick.wav --target bass.wav --bpm 92 [--style ...]   # any two files

Trigger audio: audio tracks are rendered straight from the set. MIDI tracks (drum racks, synths) need
their audio: export them (File > Export Audio/Video > All Individual Tracks) into a folder and pass
--stems DIR; files are matched by track name. The sidechain listens after the trigger's effects
(Post FX), which is what an individual-track export gives you.

Outputs (hypnomix-out/sidechain/<set>/): a gain-reduction plot per compressor (current vs suggested,
on the beat grid) and, when the target's audio is available, before/after previews of the target.

The compressor model is an approximation of Live's Compressor (Peak/RMS detector, knee, attack,
release, lookahead, sidechain gain and EQ) and Glue Compressor (its menu values for attack, release and
ratio, Range, a soft knee; its Auto release is modelled as a fixed 300 ms). Check the result by ear. Close the set in Live before
--apply; the new set is written next to the original so its samples stay linked.
"""
import argparse, gzip, math, re, sys
from hypnomix.core.gz import read_gz
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from hypnomix.core import dsp
from hypnomix.core.paths import out_at

SR = 22050          # analysis rate: ducking lives in the low end and the envelope, not in the air band
BLOCK = 16          # gain-computer block (0.7 ms at 22.05 kHz)
# Live stores the S/C EQ type as an index. Read from how Live's own presets use it: 3 = low-pass
# ("Kick Reducer" at 115 Hz), 5 = high-pass (47 presets at 80-370 Hz, gain unused), 1 = band-pass
# ("De-esser" at 6 kHz); 0 and 4 carry real gains (shelf / bell). 2 and 6 are guesses.
SC_EQ_TYPES = ["low shelf", "band-pass", "high shelf", "low-pass", "bell", "high-pass", "notch"]
LOWPASS, BANDPASS, HIGHPASS = 3, 1, 5
LOOKAHEAD_MS = [0.0, 1.0, 10.0]
# Glue Compressor menus (stored as positions): attack ms, release ms (None = Auto), ratio
GLUE_ATTACK = [0.01, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0]
GLUE_RELEASE = [100.0, 200.0, 400.0, 600.0, 800.0, 1200.0, None]
GLUE_RATIO = [2.0, 4.0, 10.0]
GLUE_AUTO_MS = 300.0      # Auto release is program-dependent; modelled as a fixed 300 ms
MODELS = ["Peak", "RMS", "Expand"]
STYLES = {
    #             depth dB, ratio, knee, model, attack ms, lookahead index
    "clarity":    dict(depth=3.0, ratio=4.0, knee=6.0, model=0, attack=1.0, lookahead=1),
    "pump":       dict(depth=8.0, ratio=6.0, knee=3.0, model=0, attack=1.0, lookahead=1),
    "vocal-duck": dict(depth=3.0, ratio=3.0, knee=6.0, model=1, attack=10.0, lookahead=0),
}


# ---------------------------------------------------------------- reading the set
def v(e, path, default=None):
    x = e.find(path) if e is not None else None
    return x.get("Value") if x is not None and x.get("Value") is not None else default


def manual(d, name, cast=float, default=None):
    x = d.find(f"./{name}/Manual")
    return cast(x.get("Value")) if x is not None else default


def track_name(t):
    if t.tag in ("MainTrack", "MasterTrack"):
        return "Main"
    return v(t, "./Name/EffectiveName", "?")


def all_tracks(root):
    ts = list(root.find(".//Tracks"))
    m = root.find(".//MainTrack")
    if m is None:
        m = root.find(".//MasterTrack")
    return ts + ([m] if m is not None else [])


def read_compressor(d):
    sc = d.find("./SideChain")
    scgain = float(v(sc, "./Volume/Manual", 1.0))
    return dict(
        on=manual(d, "On", lambda s: s == "true", True),
        sc_on=v(sc, "./OnOff/Manual") == "true",
        source_target=v(sc, ".//RoutedInput//Target", ""),
        source_name=v(sc, ".//RoutedInput//UpperDisplayString", ""),
        source_tap=v(sc, ".//RoutedInput//LowerDisplayString", ""),
        sc_gain_db=20 * math.log10(max(scgain, 1e-9)),
        threshold_db=20 * math.log10(max(manual(d, "Threshold", default=0.1), 1e-9)),
        ratio=manual(d, "Ratio", default=4.0),
        attack=manual(d, "Attack", default=2.0),
        release=manual(d, "Release", default=50.0),
        knee=manual(d, "Knee", default=6.0),
        model=int(manual(d, "Model", default=0)),
        lookahead=int(manual(d, "LookAhead", default=0)),
        dry_wet=manual(d, "DryWet", default=1.0),
        eq_on=manual(d, "SideChainEq_On", lambda s: s == "true", False),
        eq_mode=int(manual(d, "SideChainEq_Mode", default=0)),
        eq_freq=manual(d, "SideChainEq_Freq", default=100.0),
        eq_q=manual(d, "SideChainEq_Q", default=0.707),
        eq_gain=manual(d, "SideChainEq_Gain", default=0.0),
    )


def read_glue(d):
    sc = d.find("./SideChain")
    eq = d.find("./SideChainEq")
    pick = lambda table, i: table[min(max(int(i), 0), len(table) - 1)]
    rel_i = int(manual(d, "Release", default=2))
    return dict(
        kind="glue",
        on=manual(d, "On", lambda s: s == "true", True),
        sc_on=v(sc, "./OnOff/Manual") == "true",
        source_target=v(sc, ".//RoutedInput//Target", ""),
        source_name=v(sc, ".//RoutedInput//UpperDisplayString", ""),
        source_tap=v(sc, ".//RoutedInput//LowerDisplayString", ""),
        sc_gain_db=20 * math.log10(max(float(v(sc, "./Volume/Manual", 1.0)), 1e-9)),
        threshold_db=manual(d, "Threshold", default=-10.0),            # Glue stores dB directly
        ratio=pick(GLUE_RATIO, manual(d, "Ratio", default=1)),
        attack=pick(GLUE_ATTACK, manual(d, "Attack", default=2)),
        release=pick(GLUE_RELEASE, rel_i) or GLUE_AUTO_MS,
        auto_release=pick(GLUE_RELEASE, rel_i) is None,
        range_db=manual(d, "Range", default=70.0),
        knee=4.0, model=0, lookahead=0,
        dry_wet=manual(d, "DryWet", default=1.0),
        eq_on=v(eq, "./On/Manual") == "true",
        eq_mode=int(float(v(eq, "./Mode/Manual", 5))),
        eq_freq=float(v(eq, "./Freq/Manual", 200)),
        eq_q=float(v(eq, "./Q/Manual", 0.707)),
        eq_gain=float(v(eq, "./Gain/Manual", 0)),
    )


def find_sidechains(root):
    """Every Compressor and Glue Compressor with its sidechain on, with the track that hosts it."""
    ids = {t.get("Id"): t for t in all_tracks(root) if t.get("Id")}
    out, off = [], []
    for t in all_tracks(root):
        host = track_name(t)
        devs = [(d, read_compressor(d)) for d in t.iter("Compressor2")] + \
               [(d, read_glue(d)) for d in t.iter("GlueCompressor")]
        for d, c in devs:
            if not c["sc_on"]:
                continue
            c.setdefault("kind", "compressor")
            m = re.search(r"Track\.(\d+)", c["source_target"])
            c.update(el=d, host=host, host_tag=t.tag, host_el=t,
                     source_el=ids.get(m.group(1)) if m else None)
            if c["source_el"] is not None:
                c["source_name"] = track_name(c["source_el"])     # the stored label can be stale
            (out if c["on"] else off).append(c)
    return out, off


# ---------------------------------------------------------------- audio
def load_mono(path):
    y, sr = sf.read(str(path), always_2d=True, dtype="float64")
    return to_sr(y.mean(axis=1), sr)


def to_sr(y, sr):
    if sr == SR:
        return y
    g = math.gcd(int(sr), SR)
    return resample_poly(y, SR // g, int(sr) // g)


def norm(s):
    s = re.sub(r"^\d+[-\s]+", "", s.lower())
    return re.sub(r"[^a-z0-9]+", "", s)


def from_stems(stems, name):
    if not stems:
        return None
    want = norm(name)
    files = [p for p in Path(stems).iterdir() if p.suffix.lower() in (".wav", ".aif", ".aiff", ".flac")]
    exact = [p for p in files if norm(p.stem) == want]
    ends = [p for p in files if norm(p.stem).endswith(want)]   # "Song 2-Slackjaw Kit.wav"
    hit = exact or ends
    return hit[0] if len(hit) == 1 else None


def track_audio(t, als, root, stems, cache, use=None):
    """(mono audio at SR, where it came from) for a track, or (None, reason)."""
    name = track_name(t)
    if name in cache:
        return cache[name]
    p = (use or {}).get(name.lower()) or from_stems(stems, name)
    if p:
        res = (load_mono(p), f"file {Path(p).name}")
    elif t.tag == "AudioTrack":
        y = render_audio([t], als, root)
        res = (y, "rendered from the set (before its effects)") if y is not None else (None, "no audio clips")
    elif t.tag == "GroupTrack":
        kids = group_members(root, t)
        midi = [track_name(k) for k in kids if k.tag == "MidiTrack"]
        audio = [k for k in kids if k.tag == "AudioTrack" and track_on(k)]
        if midi:
            res = (None, f"a group with MIDI tracks ({', '.join(midi[:3])}): export it and pass --stems")
        elif not audio:
            res = (None, "a group with no playing audio tracks")
        else:
            y = render_audio(audio, als, root)
            res = (y, f"its {len(audio)} playing audio tracks rendered and summed (before effects)")
    else:
        kind = {"MidiTrack": "a MIDI track", "GroupTrack": "a group", "ReturnTrack": "a return"}.get(t.tag, t.tag)
        res = (None, f"{kind}: export it and pass --stems")
    cache[name] = res
    return res


def track_on(t):
    sp = t.find("./DeviceChain/Mixer/Speaker/Manual")
    return sp is None or sp.get("Value") == "true"


def group_members(root, g):
    """Every track inside group g, nested groups included (their own tracks, not the group itself)."""
    gid, out = g.get("Id"), []
    for t in root.find(".//Tracks"):
        if v(t, "./TrackGroupId") == gid:
            out += group_members(root, t) if t.tag == "GroupTrack" else [t]
    return out


def render_audio(tracks, als, root):
    from hypnomix.session.render import render_track
    spb = 60 / float(v(root, ".//Tempo/Manual"))
    ends = [float(v(c, "./CurrentEnd")) for t in tracks for c in t.iter("AudioClip")]
    if not ends:
        return None
    n = int((max(ends) + 4) * spb * SR)
    y = np.zeros(n)
    for t in tracks:
        y += render_track(t, als, spb, n, SR, None, 0, [])
    return y


# ---------------------------------------------------------------- compressor model
def sc_filter(x, c):
    if c.get("hp_hz") or c.get("lp_hz"):              # REAPER's ReaComp: a high-pass and a low-pass on the detector
        if c.get("hp_hz"):
            x = dsp.filt(x, dsp.highpass(min(c["hp_hz"], SR * 0.45), SR, order=2))
        if c.get("lp_hz") and c["lp_hz"] < SR * 0.45:
            x = dsp.filt(x, dsp.lowpass(c["lp_hz"], SR, order=2))
        if not c.get("eq_on"):
            return x
    if not c.get("eq_on"):
        return x
    f, q, g, mode = c["eq_freq"], max(c["eq_q"], 0.1), c["eq_gain"], c["eq_mode"]
    f = min(f, SR * 0.45)
    if mode == LOWPASS:
        return dsp.filt(x, dsp.lowpass(f, SR, order=2))
    if mode == BANDPASS:
        bw = f / q
        return dsp.filt(dsp.filt(x, dsp.highpass(max(10, f - bw / 2), SR, 2)), dsp.lowpass(f + bw / 2, SR, 2))
    if mode == HIGHPASS:
        return dsp.filt(x, dsp.highpass(f, SR, order=2))
    if mode == 6:
        return dsp.filt(x, dsp.notch(f, q, SR))
    if mode == 4:
        return dsp.filt(x, dsp.peaking(f, g, q, SR))
    return dsp.filt(x, dsp.shelf(f, g, SR, high=(mode == 2)))


def detector(trig, c):
    """Sidechain level in dB per sample (after S/C gain and EQ)."""
    x = sc_filter(trig, c) * dsp.undb(c.get("sc_gain_db", 0.0))
    if c["model"] == 1:
        from scipy.ndimage import uniform_filter1d
        p = uniform_filter1d(x ** 2, max(1, int(c.get("rms_ms", 10.0) / 1000 * SR)))   # Live: 10 ms
        lvl = 10 * np.log10(np.maximum(p, 0) + 1e-20)
    else:
        lvl = 20 * np.log10(np.abs(x) + 1e-10)
    la_ms = c["lookahead_ms"] if c.get("lookahead_ms") is not None else LOOKAHEAD_MS[min(max(c["lookahead"], 0), 2)]
    la = int(la_ms / 1000 * SR)
    if la:
        lvl = np.concatenate([lvl[la:], np.full(la, lvl[-1])])
    return lvl


def gain_reduction(lvl, c):
    """Gain reduction (dB, <= 0) per sample for detector levels `lvl` and settings `c`."""
    over = lvl - c["threshold_db"]
    k = max(c["knee"], 1e-6)
    slope = 1 - 1 / max(c["ratio"], 1.0)
    gr = np.where(over <= -k / 2, 0.0,
                  np.where(over >= k / 2, -over * slope, -((over + k / 2) ** 2) / (2 * k) * slope))
    if c.get("range_db") is not None:
        gr = np.maximum(gr, -float(c["range_db"]))   # Glue's Range caps the reduction
    return dsp._smooth_db(gr, SR, max(c["attack"], 0.01), max(c["release"], 1.0), BLOCK)


# ---------------------------------------------------------------- hits and metrics
def find_hits(trig):
    """Onsets of the trigger: sharp rises of its 5 ms level."""
    hop = int(0.005 * SR)
    n = len(trig) // hop
    e = 10 * np.log10(np.maximum((trig[: n * hop] ** 2).reshape(n, hop).mean(axis=1), 1e-20))
    top = np.percentile(e, 99.5)
    rise = e[4:] - e[:-4]
    cand = np.flatnonzero((rise > 9) & (e[4:] > top - 30)) + 4
    hits, last = [], -10 ** 9
    for i in cand:
        if i - last > int(0.09 / 0.005):
            base = e[i - 4]
            j = i - 4 + int(np.argmax(e[i - 4:i + 1] > base + 3))   # where the rise starts
            hits.append(max(0, j - 1) * hop)
            last = i
    return np.array(hits, dtype=int), e, hop


def decay_ms(env_db, hop, hits):
    """Median time for the trigger to fall 20 dB below each hit's peak: how long a hit lasts."""
    out = []
    for h in hits[:400]:
        i = h // hop
        i += int(np.argmax(env_db[i:i + 8]))           # from the hit's peak, not its onset
        seg = env_db[i:i + int(1.0 / 0.005)]
        if len(seg) < 3:
            continue
        below = np.flatnonzero(seg < seg[0] - 20)
        out.append((below[0] if len(below) else len(seg)) * 5.0)
    return float(np.median(out)) if out else 150.0


def measure(gr, hits, active=None):
    """Per-hit depth, recovery at the next hit and the time to be 90% back."""
    depth, rec, back, gaps = [], [], [], []
    for a, b in zip(hits[:-1], hits[1:]):
        gap = b - a
        if gap < int(0.08 * SR) or gap > int(2.5 * SR):
            continue
        if active is not None and not active[a]:
            continue
        seg = gr[a:b]
        dmin = float(seg.min())
        if dmin > -0.2:
            depth.append(0.0); rec.append(1.0); back.append(0.0); gaps.append(gap / SR * 1000)
            continue
        im = int(np.argmin(seg))
        end = float(gr[max(a, b - int(0.003 * SR))])
        after = np.flatnonzero(seg[im:] > 0.1 * dmin)
        depth.append(-dmin)
        rec.append(1 - end / dmin)
        back.append(((im + after[0]) if len(after) else gap) / SR * 1000)
        gaps.append(gap / SR * 1000)
    if not depth:
        return None
    d, r, bk, g = map(np.array, (depth, rec, back, gaps))
    main = g >= 0.6 * np.median(g)       # the main pulse: a flam or double kick can't recover in between
    # depth on the main hits (upper quartile): ghost notes and soft hits shouldn't hide what the kicks do
    return dict(n=len(d), depth=float(np.percentile(d, 75)), spread=float(np.percentile(d, 90) - np.percentile(d, 10)),
                recovery=float(np.median(r[main])), back_ms=float(np.median(bk[main])),
                gap_ms=float(np.median(g[main])), late=float(np.mean(r[main] < 0.9)))


def phrase_measure(gr, trig_active):
    """For vocal triggers: average reduction while singing, and how fast it lets go in the gaps."""
    sing = gr[trig_active]
    gaps = []
    edges = np.flatnonzero(np.diff(trig_active.astype(int)) == -1)
    for e in edges:
        w = gr[e:e + int(0.5 * SR)]
        if len(w) == int(0.5 * SR) and not trig_active[e:e + len(w)].any():
            gaps.append(float(w[-1]))
    return dict(depth=float(-np.median(sing)) if len(sing) else 0.0,
                in_gaps=float(-np.median(gaps)) if gaps else 0.0, n=len(gaps))


def lowest_note(y):
    """Lowest strong frequency (Hz) of the target, for the low-end distortion check."""
    if y is None:
        return None
    loud = y[np.abs(y) > np.abs(y).max() * 0.05]
    if len(loud) < SR:
        return None
    seg = loud[: SR * 60]
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    f = np.fft.rfftfreq(len(seg), 1 / SR)
    band = (f > 28) & (f < 400)
    if not band.any():
        return None
    s = spec[band]
    peaks = np.flatnonzero(s > s.max() * 0.3)
    return float(f[band][peaks[0]]) if len(peaks) else None


# ---------------------------------------------------------------- search
def excerpt(trig, hits, secs=40):
    """The densest `secs` of the trigger (speeds up the search)."""
    n = int(secs * SR)
    if len(trig) <= n or len(hits) < 4:
        return 0, len(trig)
    best, start = -1, 0
    for i in range(0, len(trig) - n, int(SR * 2)):
        k = int(((hits >= i) & (hits < i + n)).sum())
        if k > best:
            best, start = k, i
    return start, start + n


def fit_threshold(lvl, hits, c, target, metric):
    lo, hi = float(np.percentile(lvl, 50)) - 20, float(lvl.max()) + 1
    for _ in range(14):
        c["threshold_db"] = (lo + hi) / 2
        m = metric(gain_reduction(lvl, c), hits)
        d = m["depth"] if m else 0.0
        if d > target:
            lo = c["threshold_db"]
        else:
            hi = c["threshold_db"]
    c["threshold_db"] = (lo + hi) / 2
    return c


def suggest(trig, hits, cur, style, decay, f0, gap_ms, beat_ms, is_vocal, active):
    """Search settings for `style`. Returns (settings, notes)."""
    s = dict(STYLES[style])
    c = dict(cur)
    glue = cur.get("kind") == "glue"
    snap = lambda x, table: min((t for t in table if t is not None), key=lambda t: abs(math.log(t / x)))
    if glue:
        # Glue: no lookahead, menu values only, fixed soft knee and detector
        c.update(attack=snap(s["attack"], GLUE_ATTACK), auto_release=False)
        c["ratio"] = {"clarity": 4.0, "pump": 4.0 if cur["ratio"] < 10 else 10.0, "vocal-duck": 2.0}[style]
    else:
        c.update(model=s["model"], knee=s["knee"], attack=s["attack"], lookahead=s["lookahead"])
        c["ratio"] = min(cur["ratio"], 6.0 if style == "clarity" else 10.0) \
            if cur["ratio"] >= 2 and style != "vocal-duck" and not cur.get("fresh") else s["ratio"]
    notes = []
    # release >= two cycles of the target's lowest note; unknown target: assume a 40 Hz bass (50 ms)
    floor = max(30.0, 2000.0 / f0) if f0 else 50.0
    a, b = excerpt(trig, hits)
    seg_hits = hits[(hits >= a) & (hits < b)] - a
    lvl = detector(trig[a:b], c)

    if style == "vocal-duck":
        metric = lambda gr, _h: {"depth": phrase_measure(gr, active)["depth"]}
        c["release"] = float(np.clip(0.35 * beat_ms, 200, 400))
        if glue:
            c["release"] = snap(c["release"], GLUE_RELEASE)
        fit_threshold(detector(trig, c), hits, c, s["depth"], metric)
        return c, notes

    deadline = (0.9 if style == "pump" else 0.6) * gap_ms
    deadline = max(deadline, floor * 1.5)
    metric = lambda gr, h: measure(gr, h)
    best = None
    rels = [r for r in GLUE_RELEASE if r is not None and r >= floor] if glue else \
        np.geomspace(max(floor, 15), 2000, 18)
    for rel in rels:
        c["release"] = float(rel)
        fit_threshold(lvl, seg_hits, c, s["depth"], metric)
        m = measure(gain_reduction(lvl, c), seg_hits)
        if m is None:
            continue
        if m["back_ms"] <= deadline and m["recovery"] >= (0.9 if style == "clarity" else 0.85):
            best = (dict(c), m)                      # keep the longest release that still makes it
        elif best is not None:
            break
    if best is None:
        c["release"] = float(rels[0]) if glue and len(rels) else float(max(floor, 15))
        fit_threshold(lvl, seg_hits, c, s["depth"], metric)
        if glue and (not f0 or 2000.0 / f0 <= GLUE_RELEASE[0]):
            notes.append("the hits come faster than the Glue's shortest release (0.1 s) can recover from; it "
                         "uses 0.1 s, so a little ducking carries over (the regular Compressor can go shorter)")
        else:
            why = f"two cycles of the target's {f0:.0f} Hz low end" if f0 else \
                "50 ms (two cycles of a 40 Hz bass; the target's audio wasn't available to check)"
            notes.append(f"for the level to be back well before the next hit (within 60% of the gap) the "
                         f"release would have to be under {why}; this uses the shortest safe release "
                         f"({c['release']:.0f} ms), so the recovery runs a little later in the gap")
        return c, notes
    return best[0], notes


# ---------------------------------------------------------------- explaining
def describe(c, rel=None):
    if c.get("kind") == "glue":
        return describe_glue(c, rel)
    return describe_comp(c, rel)


def eq_text(c):
    if not c.get("eq_on"):
        return "off"
    t = SC_EQ_TYPES[c["eq_mode"]] if 0 <= c["eq_mode"] < len(SC_EQ_TYPES) else f"type {c['eq_mode']}"
    return f"{t} {c['eq_freq']:.0f} Hz" + (f" {c['eq_gain']:+.1f} dB" if c["eq_mode"] in (0, 2, 4) else "")


def threshold_text(c, rel):
    if rel is None:
        return f"threshold {c['threshold_db']:.1f} dB"
    where = "the main hits' peaks on the input meter"
    return (f"threshold about {-rel:.0f} dB below {where}" if rel < -0.5 else
            f"threshold about {rel:.0f} dB above {where} (the knee does the work)" if rel > 0.5
            else f"threshold at {where}")


def describe_glue(c, rel=None):
    r = "Auto" if c.get("auto_release") else (f"{c['release'] / 1000:g} s")
    rng = "" if c.get("range_db", 70) >= 69 else f", range {c['range_db']:.0f} dB"
    return (f"Glue: {threshold_text(c, rel)}, ratio {c['ratio']:g}, attack {c['attack']:g} ms, release {r}"
            f"{rng}, S/C EQ {eq_text(c)}")


def describe_comp(c, rel=None):
    return (f"{threshold_text(c, rel)}, ratio {c['ratio']:.1f}:1, attack {c['attack']:.2g} ms, "
            f"release {c['release']:.0f} ms, knee {c['knee']:.0f} dB, {MODELS[min(c['model'], 2)]}, "
            f"lookahead {LOOKAHEAD_MS[min(c['lookahead'], 2)]:g} ms, S/C EQ {eq_text(c)}")


def verdict(m, style, f0, c, decay, exact=True):
    """Plain-English problems with the current settings."""
    out = []
    if not exact:
        m = dict(m) if m else m
    if m is None:
        return ["the trigger never pushes the compressor past its threshold: no ducking happens"]
    if exact and m["depth"] < 0.5:
        out.append(f"barely ducks ({m['depth']:.1f} dB): the threshold is above the trigger, or the S/C EQ "
                   "removes what should trigger it")
    lo, hi = {"clarity": (2, 4.5), "pump": (6, 10), "vocal-duck": (2, 4.5)}[style]
    if exact and m["depth"] > hi + 1.5:
        out.append(f"ducks {m['depth']:.1f} dB, deep for {style} ({lo}-{hi} dB): the target drops out "
                   "on every hit")
    if m["recovery"] < 0.85:
        out.append(f"only {m['recovery'] * 100:.0f}% back by the next hit (release too long for "
                   f"{m['gap_ms']:.0f} ms between hits): the target never returns to full level and the "
                   "ducks pile up")
    if m["spread"] > 3:
        out.append(f"depth varies by {m['spread']:.1f} dB between hits: the groove pumps unevenly "
                   "(uneven hits, or other drums triggering it)")
    if c.get("auto_release"):
        out.append("release is on Auto: it lengthens as the compression goes on, so recovery between hits "
                   f"is modelled at about {GLUE_AUTO_MS:.0f} ms; a fixed release gives a steadier groove")
    if f0 and c["release"] < 2000 / f0:
        out.append(f"release {c['release']:.0f} ms is under two cycles of the target's {f0:.0f} Hz low end "
                   f"({2000 / f0:.0f} ms): bends the waveform, sounds like distortion on the bass")
    if c["attack"] < 0.1 and m["depth"] > 4 and LOOKAHEAD_MS[min(c["lookahead"], 2)] == 0:
        out.append(f"{c['attack']:.2g} ms attack with no lookahead and {m['depth']:.0f} dB of reduction "
                   "slams the level down within a few samples: an audible click on every hit")
    if c.get("eq_on") and c["eq_mode"] == HIGHPASS and c["eq_freq"] > 60 and decay < 300:
        out.append(f"the S/C EQ high-passes the drum trigger at {c['eq_freq']:.0f} Hz: the kick's body is "
                   "filtered out of what should trigger the ducking (a low-pass is usual for kick triggers)")
    return out


# ---------------------------------------------------------------- outputs
def plot(path, trig, gr_cur, gr_new, hits, beat_ms, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    if len(hits) > 8:
        a = int(hits[len(hits) // 3]) - int(0.05 * SR)
    else:
        a = 0
    n = int(min(4 * 4 * beat_ms / 1000, 12) * SR)
    sl = slice(max(0, a), max(0, a) + n)
    t = np.arange(sl.stop - sl.start) / SR
    fig, ax = plt.subplots(2, 1, figsize=(11, 5), sharex=True, gridspec_kw=dict(height_ratios=[1, 2]))
    from scipy.ndimage import uniform_filter1d
    env = 10 * np.log10(uniform_filter1d(trig[sl] ** 2, int(0.005 * SR)) + 1e-12)
    ax[0].plot(t, env, lw=0.8, color="0.35")
    ax[0].set_ylim(max(-70, env.max() - 50), env.max() + 3); ax[0].set_ylabel("trigger dB\n(as heard)")
    ax[1].plot(t, gr_cur[sl], label="current", color="tab:red", lw=1.2)
    if gr_new is not None:
        ax[1].plot(t, gr_new[sl], label="suggested", color="tab:blue", lw=1.2)
    ax[1].set_ylabel("gain reduction dB"); ax[1].set_xlabel("seconds"); ax[1].legend(loc="lower right")
    for x in np.arange(0, t[-1], beat_ms / 1000):
        for axx in ax:
            axx.axvline(x, color="0.85", lw=0.6, zorder=0)
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def previews(od, stem, target, gr_cur, gr_new, hits, wet_cur, wet_new):
    a = int(hits[len(hits) // 3]) if len(hits) > 8 else 0
    n = min(len(target) - a, int(12 * SR))
    if n <= SR:
        return []
    seg = target[a:a + n]
    outs = []
    takes = [("1-dry", None, 1), ("2-current", gr_cur, wet_cur), ("3-suggested", gr_new, wet_new)]
    if gr_cur is None:
        takes = [takes[0], ("2-suggested", gr_new, wet_new)]
    for tag, gr, wet in takes:
        y = seg if gr is None else seg * (1 - wet + wet * dsp.undb(gr[a:a + n]))
        p = od / f"{stem} {tag}.wav"
        sf.write(str(p), (y / max(1e-9, np.abs(seg).max()) * 0.5).astype(np.float32), SR, subtype="FLOAT")
        outs.append(p.name)
    return outs


# ---------------------------------------------------------------- apply
def set_manual(d, name, value):
    x = d.find(f"./{name}/Manual")
    if x is not None:
        x.set("Value", value)


def write_glue(d, c):
    idx = lambda x, table: str(min(range(len(table)), key=lambda i: abs(math.log((table[i] or 1e9) / x))))
    set_manual(d, "Threshold", repr(float(np.clip(c["threshold_db"], -40, 0))))
    set_manual(d, "Ratio", idx(c["ratio"], GLUE_RATIO))
    set_manual(d, "Attack", idx(c["attack"], GLUE_ATTACK))
    set_manual(d, "Release", "6" if c.get("auto_release") else idx(c["release"], GLUE_RELEASE))
    eq = d.find("./SideChainEq")
    if eq is not None:
        for k, val in (("On", "true" if c.get("eq_on") else "false"), ("Mode", str(int(c["eq_mode"]))),
                       ("Freq", repr(float(c["eq_freq"])))):
            x = eq.find(f"./{k}/Manual")
            if x is not None:
                x.set("Value", val)


def write_settings(d, c):
    if c.get("kind") == "glue":
        return write_glue(d, c)
    set_manual(d, "Threshold", repr(10 ** (c["threshold_db"] / 20)))
    set_manual(d, "Ratio", repr(float(c["ratio"])))
    set_manual(d, "Attack", repr(float(c["attack"])))
    set_manual(d, "Release", repr(float(c["release"])))
    set_manual(d, "Knee", repr(float(c["knee"])))
    set_manual(d, "Model", str(int(c["model"])))
    set_manual(d, "LookAhead", str(int(c["lookahead"])))
    set_manual(d, "SideChainEq_On", "true" if c.get("eq_on") else "false")
    set_manual(d, "SideChainEq_Mode", str(int(c["eq_mode"])))
    set_manual(d, "SideChainEq_Freq", repr(float(c["eq_freq"])))


# ---------------------------------------------------------------- Glue -> Compressor
COMP_TEMPLATE = ("Core Library/Devices/Audio Effects/Compressor/Basic Peak Compressor.adv")


def find_template():
    import glob
    hits = glob.glob(f"/Applications/Ableton Live*/Contents/App-Resources/{COMP_TEMPLATE}") + \
        glob.glob(f"C:/ProgramData/Ableton/Live*/Resources/{COMP_TEMPLATE}")
    if not hits:
        sys.exit("couldn't find Live's 'Basic Peak Compressor' preset to build a Compressor from")
    return ET.fromstring(read_gz(sorted(hits)[-1])).find(".//Compressor2")


def as_compressor(g):
    """A Glue's settings expressed for Live's Compressor, with lookahead (the reason to switch)."""
    c = dict(g)
    c.update(kind="compressor", model=0, knee=6.0, lookahead=1, range_db=None, auto_release=False,
             attack=max(g["attack"], 1.0))
    return c


def glue_to_compressor(root, chain_parent, glue_el, c, makeup_db):
    """Replace a Glue Compressor element with a Compressor that has the same sidechain routing."""
    tpl = ET.fromstring(ET.tostring(find_template()))
    nxt = root.find(".//NextPointeeId")
    nid = int(nxt.get("Value"))
    for e in tpl.iter():
        if e.tag in ("AutomationTarget", "ModulationTarget", "Pointee") and e.get("Id") is not None:
            e.set("Id", str(nid)); nid += 1
    nxt.set("Value", str(nid))
    tpl.set("Id", glue_el.get("Id", "0"))
    tpl.find("./SideChain").clear()
    for ch in glue_el.find("./SideChain"):                       # same layout in both devices
        tpl.find("./SideChain").append(ET.fromstring(ET.tostring(ch)))
    set_manual(tpl, "On", glue_el.find("./On/Manual").get("Value"))
    set_manual(tpl, "Gain", repr(float(makeup_db)))
    set_manual(tpl, "DryWet", repr(float(c.get("dry_wet", 1.0))))
    set_manual(tpl, "SideChainEq_Q", repr(float(c.get("eq_q", 0.707))))
    set_manual(tpl, "SideChainEq_Gain", repr(float(c.get("eq_gain", 0.0))))
    write_settings(tpl, c)
    kids = list(chain_parent)
    i = kids.index(glue_el)
    chain_parent.remove(glue_el)
    chain_parent.insert(i, tpl)
    return tpl


def parent_of(root, el):
    for p in root.iter():
        for ch in p:
            if ch is el:
                return p
    return None


# ---------------------------------------------------------------- main
def analyse(c, trig, target, beat_ms, style, exact=True):
    """exact: the audio is the sidechain tap itself, so absolute levels (threshold, depth) can be trusted.
    Otherwise only timing is judged, at the style's depth, and the threshold is given relative to the hits."""
    heard = sc_filter(trig, c)                      # what the compressor hears (after its S/C EQ)
    hits, env, hop = find_hits(heard)
    sounding = 20 * np.log10(np.abs(heard) + 1e-9) > -45
    from scipy.ndimage import maximum_filter1d
    tact = maximum_filter1d(sounding, int(0.15 * SR))
    gaps = np.diff(hits) / SR * 1000 if len(hits) > 2 else np.array([beat_ms])
    gap_ms = float(np.median(gaps[(gaps > 80) & (gaps < 2500)])) if len(gaps) else beat_ms
    decay = decay_ms(env, hop, hits)
    hits_per_min = len(hits) / max(1e-9, len(trig) / SR / 60)
    is_vocal = decay > 300 or hits_per_min < 20
    if not is_vocal and not c.get("eq_on"):
        # a whole kit triggers on snare and hats too; judge the hits on its low end, like a low-pass would
        low = dsp.filt(trig, dsp.lowpass(150, SR, 2))
        h2, e2, _ = find_hits(low)
        if len(h2) >= 8:
            hits, env = h2, e2
            gaps = np.diff(hits) / SR * 1000
            gap_ms = float(np.median(gaps[(gaps > 80) & (gaps < 2500)])) if len(gaps) else beat_ms
            decay = decay_ms(env, hop, hits)
    if style == "auto":
        style = "vocal-duck" if is_vocal else "clarity"
    f0 = lowest_note(target) if target is not None else None

    # current settings, with the trigger kit's other drums: a full drum bus wants a low-pass S/C EQ
    new_eq = None
    if not is_vocal and not c.get("eq_on"):
        hi = dsp.filt(trig, dsp.highpass(300, SR, 2))
        if np.sqrt(np.mean(hi ** 2)) > 0.5 * np.sqrt(np.mean(trig ** 2)):
            new_eq = dict(eq_on=True, eq_mode=LOWPASS, eq_freq=150.0)

    lvl_cur = detector(trig, c)
    c_eval = dict(c)
    if not exact and style != "vocal-duck":
        # unknown absolute level: judge the current attack/release at the style's depth instead
        fit_threshold(lvl_cur, hits, c_eval, STYLES[style]["depth"], lambda gr, h: measure(gr, h))
    gr_cur = gain_reduction(lvl_cur, c_eval)
    if style == "vocal-duck":
        m_cur = phrase_measure(gr_cur, tact)
    else:
        m_cur = measure(gr_cur, hits)
    cur_for_search = dict(c, **(new_eq or {}))
    sug, notes = suggest(trig, hits, cur_for_search, style, decay, f0, gap_ms, beat_ms, is_vocal, tact)
    if style != "vocal-duck":                        # timing was chosen on an excerpt; level on the whole song
        fit_threshold(detector(trig, sug), hits, sug, STYLES[style]["depth"], lambda gr, h: measure(gr, h))
    lvl_new = detector(trig, sug)
    gr_new = gain_reduction(lvl_new, sug)
    m_new = phrase_measure(gr_new, tact) if style == "vocal-duck" else measure(gr_new, hits)
    w = int(0.08 * SR)                 # a low-passed kick peaks tens of ms after its onset
    peaks = [lvl_new[h:h + w].max() for h in hits[:600] if h + w < len(lvl_new)]
    rel = sug["threshold_db"] - float(np.percentile(peaks, 75)) if peaks else None   # vs the main hits
    return dict(style=style, hits=hits, gap_ms=gap_ms, decay=decay, f0=f0, gr_cur=gr_cur, gr_new=gr_new,
                m_cur=m_cur, m_new=m_new, sug=sug, notes=notes, new_eq=new_eq, is_vocal=is_vocal,
                rel_threshold=rel, exact=exact, heard=heard)


def fmt_m(m, style):
    if m is None:
        return "no ducking"
    if style == "vocal-duck":
        return f"{m['depth']:.1f} dB while singing, {m['in_gaps']:.1f} dB left 0.5 s into the gaps"
    return (f"{m['depth']:.1f} dB on the main hits (spread {m['spread']:.1f}), {m['recovery'] * 100:.0f}% back by the "
            f"next hit, 90% back after {m['back_ms']:.0f} ms of a {m['gap_ms']:.0f} ms gap")


def main():
    ap = argparse.ArgumentParser(prog="hypnomix sidechain", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    from hypnomix.session import liveversion as LV; LV.add_force_flag(ap)
    ap.add_argument("als", nargs="?")
    ap.add_argument("--stems", help="folder of exported tracks (for MIDI triggers and targets)")
    ap.add_argument("--style", default="auto", choices=["auto", *STYLES])
    ap.add_argument("--host", help="only compressors on tracks whose name contains this")
    ap.add_argument("--use", action="append", default=[], metavar="TRACK=FILE",
                    help="audio file for a track (e.g. a stem from `hypnomix separate`); repeatable")
    ap.add_argument("--trigger"); ap.add_argument("--target"); ap.add_argument("--bpm", type=float)
    ap.add_argument("--out")
    ap.add_argument("--apply", metavar="OUT.als", help="write the suggestions to this new set")
    ap.add_argument("--glue-to-compressor", action="store_true",
                    help="with --apply: replace each sidechained Glue Compressor with Live's Compressor (same "
                         "routing, lookahead on), tuned like any other Compressor")
    a = ap.parse_args()

    if a.trigger:
        if not a.bpm:
            sys.exit("--bpm is needed with --trigger")
        trig = load_mono(a.trigger)
        target = load_mono(a.target) if a.target else None
        c = dict(threshold_db=-20.0, ratio=4.0, attack=1.0, release=100.0, knee=6.0, model=0, lookahead=1,
                 eq_on=False, eq_mode=LOWPASS, eq_freq=150.0, eq_q=0.707, eq_gain=0.0, sc_gain_db=0.0, dry_wet=1.0,
                 fresh=True)
        r = analyse(c, trig, target, 60000 / a.bpm, a.style)
        od = out_at(a.out, "sidechain", Path(a.trigger).stem)
        print(f"trigger {Path(a.trigger).name}: {len(r['hits'])} hits, {r['gap_ms']:.0f} ms apart, "
              f"each lasts ~{r['decay']:.0f} ms" + (f"; target low end ~{r['f0']:.0f} Hz" if r["f0"] else ""))
        print(f"style {r['style']}\nsuggested: {describe(r['sug'])}\n  -> {fmt_m(r['m_new'], r['style'])}")
        plot(od / "gain-reduction.png", r["heard"], r["gr_new"], None, r["hits"], 60000 / a.bpm, "suggested")
        if target is not None:
            previews(od, "target", target, None, r["gr_new"], r["hits"], 1, 1)
        print(f"plot and previews in {od}")
        return

    if not a.als:
        ap.error("give a set (.als), or --trigger/--target files")
    src = Path(a.als)
    if a.apply and Path(a.apply).resolve().parent != src.resolve().parent:
        sys.exit(f"write the new set in the same folder as the original ({src.resolve().parent}): "
                 "samples linked by relative path go offline elsewhere")
    tree = ET.ElementTree(ET.fromstring(read_gz(src)))
    root = tree.getroot()
    tempo = float(v(root, ".//Tempo/Manual"))
    beat_ms = 60000 / tempo
    comps, off = find_sidechains(root)
    if a.host:
        comps = [c for c in comps if a.host.lower() in c["host"].lower()]
    print(f"{src.name}: {tempo:g} BPM (a beat is {beat_ms:.0f} ms); {len(comps)} sidechained compressor(s)\n")
    od = out_at(a.out, "sidechain", src.stem)
    cache, changed = {}, 0
    use = {}
    for u in a.use:
        if "=" not in u:
            sys.exit(f"--use wants TRACK=FILE, got {u!r}")
        k_, f_ = u.split("=", 1)
        if not Path(f_).exists():
            sys.exit(f"--use: no file {f_}")
        use[k_.strip().lower()] = Path(f_)
    if a.glue_to_compressor and not a.apply:
        sys.exit("--glue-to-compressor needs --apply OUT.als (it writes a new set)")
    for k, c in enumerate(comps, 1):
        if a.glue_to_compressor and c.get("kind") == "glue":
            glue_c = c
            c = dict(as_compressor(c), glue_el=c["el"], glue_makeup=manual(c["el"], "Makeup", default=0.0))
            print(f"[{k}] {c['host']}  <- {c['source_name']} ({c['source_tap']})  Glue -> Compressor")
            print(f"    was: {describe(glue_c)}")
        else:
            print(f"[{k}] {c['host']}  <- {c['source_name']} ({c['source_tap']})")
        if c.get("glue_el") is None:
            print(f"    now: {describe(c)}" + (f", dry/wet {c['dry_wet'] * 100:.0f}%" if c["dry_wet"] < 0.999 else ""))
        if c["source_el"] is None:
            print("    trigger track not found in the set\n")
            continue
        if c["source_el"] is c["host_el"]:
            print("    - the compressor listens to its own track's output: that is ordinary compression with "
                  "extra latency, not ducking. Probably a leftover; point its sidechain at the trigger track.\n")
            continue
        trig, how = track_audio(c["source_el"], src, root, a.stems, cache, use)
        if trig is None:
            print(f"    trigger audio: {how}")
            if c.get("glue_el") is not None:
                parent = parent_of(root, c["glue_el"])
                glue_to_compressor(root, parent, c["glue_el"], c, c["glue_makeup"])
                changed += 1
                print(f"    switched to Compressor with the Glue's own settings plus lookahead: {describe(c)}")
                print("    (tune its release once the trigger is exported: run this again on the new set)")
            print()
            continue
        target, thow = track_audio(c["host_el"], src, root, a.stems, cache, use) \
            if c["host_tag"] != "MainTrack" else (None, "main")
        if how.startswith("file") and "pre" in c["source_tap"].lower():
            how += " (the sidechain listens Pre FX; an export is Post FX, so levels may differ)"
        post = "post" in c["source_tap"].lower()
        # trust absolute levels only when the audio IS the tap: an individual-track export (Post FX), or a
        # single audio track rendered from the set when the sidechain listens Pre FX
        exact = (how.startswith("file") and post and c["source_name"].lower() not in use) or \
                (how.startswith("rendered") and not post)
        r = analyse(c, trig, target, beat_ms, a.style, exact)
        print(f"    trigger: {how}; {len(r['hits'])} hits, usually {r['gap_ms']:.0f} ms apart, each lasts "
              f"~{r['decay']:.0f} ms" + (f"; target low end ~{r['f0']:.0f} Hz" if r["f0"] else ""))
        print(f"    style {r['style']}")
        if exact:
            print(f"    now does: {fmt_m(r['m_cur'], r['style'])}")
        else:
            print("    (this audio isn't the sidechain's own tap, so its level can't be trusted: depth isn't "
                  "judged, and the threshold is given relative to the hits)")
            if r["style"] != "vocal-duck":
                print(f"    your attack/release at {STYLES[r['style']]['depth']:g} dB of ducking: "
                      f"{fmt_m(r['m_cur'], r['style'])}")
        if r["style"] != "vocal-duck":
            for p in verdict(r["m_cur"], r["style"], r["f0"], c, r["decay"], exact):
                print(f"      - {p}")
        print(f"    suggest: {describe(r['sug'], None if exact else r['rel_threshold'])}")
        print(f"      -> {fmt_m(r['m_new'], r['style'])}")
        for n in r["notes"]:
            print(f"      ({n})")
        if r["new_eq"] and not c.get("eq_on"):
            print("      (S/C EQ low-pass 150 Hz: the trigger has a lot of snare/hats, which shouldn't duck it)")
        stem = re.sub(r"[^\w\- ]+", "", f"{k} {c['host']}")[:60]
        plot(od / f"{stem}.png", r["heard"], r["gr_cur"], r["gr_new"], r["hits"], beat_ms,
             f"{c['host']} <- {c['source_name']}: current (red) vs suggested (blue)")
        if target is not None and len(r["hits"]) > 8:
            previews(od, stem, target, r["gr_cur"], r["gr_new"], r["hits"], c["dry_wet"], c["dry_wet"])
            print(f"    previews: target {thow}")
        print()
        if a.apply:
            sug = dict(r["sug"])
            if not exact:
                sug["threshold_db"] = c["threshold_db"]
                print("    (--apply keeps your threshold here: set it by ear so the meter shows the suggested depth)")
            if c.get("glue_el") is not None:
                glue_to_compressor(root, parent_of(root, c["glue_el"]), c["glue_el"], sug, c["glue_makeup"])
                print("    switched to Compressor (same sidechain routing, makeup and dry/wet carried over)")
            else:
                write_settings(c["el"], sug)
            changed += 1
    for c in off:
        name = "Glue Compressor" if c.get("kind") == "glue" else "Compressor"
        print(f"(switched off: {name} on {c['host']} <- {c['source_name']})")
    print(f"\nplots{' and previews' if any(True for _ in od.glob('*.wav')) else ''} in {od}")
    if a.apply:
        if not changed:
            print("nothing analysed, so nothing written")
            return
        data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")
        out = Path(a.apply)
        if out.resolve() == src.resolve():
            sys.exit("refusing to overwrite the source set")
        from hypnomix.session import liveversion as LV
        LV.guard_write(root)                # refuses a set saved by a Live newer than the newest tested
        with gzip.open(out, "wb") as f:
            f.write(data)
        print(f"wrote {out} ({changed} compressor(s) changed). Close the original in Live, then open this one.")


if __name__ == "__main__":
    main()
