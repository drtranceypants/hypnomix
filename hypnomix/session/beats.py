"""Shared helpers for the tempo tools (tempomap, loops, tighten, breathe, variations). Not a command.

  track()         beats, bars and the tempo of every bar in a recording played without a click
  warp_render()   stretch audio along a time map (source second -> output second), pitch unchanged:
                  the offline preview of what warp markers or tempo automation will do
  straight_warp() turn an unwarped clip into a warped one that plays exactly the same at the set's tempo
  tempo points    read and write the tempo automation of a set
  finish()        save a NEW set and run the structural check on it
"""
import os, shutil, subprocess, sys, tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import soundfile as sf
import librosa

SR_B = 22050
HOP = 128             # ~6 ms: beat tracking
HOP_FINE = 32         # ~1.5 ms: placing a beat on the start of its hit
SNAP = 0.045          # a beat is moved onto a hit this close to it
START = -63072000     # the time Live gives the first point of every envelope


def load(path):
    y, sr = sf.read(str(path), always_2d=True, dtype="float32")
    return y, sr


def onset_times(mono, sr):
    """Starts of hits (seconds) and their strength, at fine resolution."""
    y = librosa.resample(mono, orig_sr=sr, target_sr=SR_B) if sr != SR_B else mono
    env = librosa.onset.onset_strength(y=y, sr=SR_B, hop_length=HOP_FINE)
    peaks = librosa.onset.onset_detect(onset_envelope=env, sr=SR_B, hop_length=HOP_FINE, backtrack=False, units="frames")
    if not len(peaks):
        return np.zeros(0), np.zeros(0)
    starts = librosa.onset.onset_backtrack(peaks, env)
    return starts * HOP_FINE / SR_B, env[peaks]


def track(path, bpb=4, bpm=None, downbeat=None, mult=1.0):
    """Follow the beat of a recording that was played without a click.

    Returns a dict: beats (seconds), down (index of the first bar line in beats), bars (seconds of every
    bar line), bar_bpm (tempo of each bar), bpm (median), lo / hi (slowest and fastest bar), wander_pct,
    snapped (share of beats that sit on a real hit), downbeat_sure (0-1), duration.
    bpm is a hint; mult 2 doubles the beat (half-time was found), 0.5 halves it."""
    y, sr = load(path)
    mono = y.mean(1)
    dur = len(mono) / sr
    yb = librosa.resample(mono, orig_sr=sr, target_sr=SR_B) if sr != SR_B else mono
    env = librosa.onset.onset_strength(y=yb, sr=SR_B, hop_length=HOP, aggregate=np.median)
    if not np.any(env > 0):
        raise ValueError("no hits found: is this file silent?")
    # the tempo may wander: estimate it over time, smooth it, and let the beat tracker follow that curve
    try:
        local = librosa.feature.tempo(onset_envelope=env, sr=SR_B, hop_length=HOP, aggregate=None,
                                      start_bpm=bpm or 110.0, std_bpm=0.5 if bpm else 1.0)
        k = max(3, int(8.0 * SR_B / HOP) | 1)
        from scipy.ndimage import median_filter
        local = median_filter(local, size=k, mode="nearest")
        _, frames = librosa.beat.beat_track(onset_envelope=env, sr=SR_B, hop_length=HOP, bpm=local,
                                            tightness=80, trim=False)
    except Exception:
        _, frames = librosa.beat.beat_track(onset_envelope=env, sr=SR_B, hop_length=HOP,
                                            start_bpm=bpm or 110.0, tightness=80, trim=False)
    beats = np.asarray(frames, dtype=float) * HOP / SR_B
    if len(beats) < 2 * bpb:
        raise ValueError("too few beats found to build a tempo map (is this a rhythmic recording?)")
    if mult >= 2:
        mid = (beats[:-1] + beats[1:]) / 2
        beats = np.sort(np.concatenate([beats, mid]))
    elif mult <= 0.5:
        beats = beats[::2]
    # put each beat on the start of the hit it belongs to (a warp marker belongs on the transient)
    on, strength = onset_times(mono, sr)
    if len(on) and len(beats) > 4:                         # the tracker often starts a beat or two late: count back
        per = float(np.median(np.diff(beats[:5])))
        head = []
        while beats[0] - per * (len(head) + 1) >= on[0] - 0.5 * per and len(head) < 8:
            head.append(beats[0] - per * (len(head) + 1))
        per = float(np.median(np.diff(beats[-5:])))
        tail = []
        while beats[-1] + per * (len(tail) + 1) <= on[-1] + 0.25 * per and len(tail) < 8:
            tail.append(beats[-1] + per * (len(tail) + 1))
        beats = np.concatenate([head[::-1], beats, tail])
    snapped = 0
    on_all = on
    if len(on):
        floor = np.percentile(strength, 40)
        on = on[strength >= floor]
        for i, b in enumerate(beats):
            j = int(np.argmin(np.abs(on - b))) if len(on) else -1
            if j >= 0 and abs(on[j] - b) <= SNAP:
                beats[i] = on[j]
                snapped += 1
        snapped = sum(1 for b in beats if np.abs(on - b).min() < 1e-6 and on_all[0] - 0.2 <= b <= on_all[-1] + 0.2)
        beats = beats[(beats >= on_all[0] - 0.2) & (beats <= on_all[-1] + 0.2)]   # no beats counted into silence
    beats = np.maximum.accumulate(beats)
    keep = np.concatenate([[True], np.diff(beats) > 0.08])
    beats = beats[keep]
    # which beat is "one": the phase with the most low-end (kick) weight, unless told
    S = np.abs(librosa.stft(yb, n_fft=1024, hop_length=HOP))
    low = S[: max(2, int(150 / (SR_B / 1024)))].sum(0)
    fr = np.clip((beats * SR_B / HOP).astype(int), 0, len(low) - 1)
    w = np.array([low[max(0, f - 3): f + 8].max() for f in fr])
    if downbeat is not None:
        down = int(np.argmin(np.abs(beats - downbeat)))
        sure = 1.0
    else:
        score = np.array([w[p::bpb].mean() if len(w[p::bpb]) else 0 for p in range(bpb)])
        down = int(np.argmax(score))
        # kick on 1 and 3 looks the same both ways: a take usually starts on "one", so among the phases that
        # score about as well, take the one whose first beat is the take's first hit
        close = [p for p in range(bpb) if score[p] >= 0.85 * score[down] and p < len(beats)]
        if len(close) > 1 and len(on_all):
            down = min(close, key=lambda p: abs(beats[p] - on_all[0]))
        rest = np.delete(score, down)
        sure = float(np.clip((score[down] - rest.max()) / (score[down] + 1e-9) * 4, 0, 1)) if len(rest) else 1.0
    bars = beats[down::bpb]
    bar_bpm = bpb * 60.0 / np.diff(bars) if len(bars) > 1 else np.zeros(0)
    med = float(np.median(60.0 / np.diff(beats)))
    on_hit = np.array([bool(len(on)) and float(np.abs(on - b).min()) < 1e-6 for b in beats])
    return dict(beats=beats, on_hit=on_hit, down=down % bpb, bars=bars, bar_bpm=bar_bpm, bpm=med, bpb=bpb,
                lo=float(bar_bpm.min()) if len(bar_bpm) else med, hi=float(bar_bpm.max()) if len(bar_bpm) else med,
                wander_pct=float((np.percentile(bar_bpm, 95) - np.percentile(bar_bpm, 5)) / med * 100) if len(bar_bpm) else 0.0,
                snapped=snapped / max(1, len(beats)), downbeat_sure=sure, duration=dur)


def click_track(n, sr, beats, down, bpb, level=0.35):
    """A click at every beat (higher on bar lines), to check a tempo map by ear."""
    out = np.zeros(n, dtype=np.float32)
    L = int(0.03 * sr)
    t = np.arange(L) / sr
    for i, b in enumerate(beats):
        f = 1760.0 if (i - down) % bpb == 0 else 880.0
        tick = (np.sin(2 * np.pi * f * t) * np.exp(-t * 180)).astype(np.float32) * level
        a = int(b * sr)
        if 0 <= a < n:
            out[a:a + L] += tick[: max(0, min(L, n - a))]
    return out


# ---------------------------------------------------------------- stretching along a time map
def warp_render(y, sr, pairs, crisp=True):
    """y (frames x channels) stretched so that source second s plays at output second d for every (s, d)
    in pairs (both increasing). Pitch is unchanged. Uses the `rubberband` program when installed
    (brew install rubberband), otherwise a rougher piecewise phase vocoder."""
    pairs = sorted((float(s), float(d)) for s, d in pairs)
    clean = []
    for s, d in pairs:
        if not clean or (s > clean[-1][0] + 1e-4 and d > clean[-1][1] + 1e-4):
            clean.append((s, d))
    if len(clean) < 2:
        return y.copy()
    src_end, dst_end = len(y) / sr, None
    (s0, d0), (s1, d1) = clean[-2], clean[-1]
    if clean[0][0] > 0:                                   # extend the first and last slopes to the file's edges
        (a0, b0), (a1, b1) = clean[0], clean[1]
        d_at0 = b0 - a0 * (b1 - b0) / (a1 - a0)
        if d_at0 < 0:                                     # the start would fall before zero: shift everything later
            clean = [(s, d - d_at0) for s, d in clean]
            d_at0 = 0.0
            (s0, d0), (s1, d1) = clean[-2], clean[-1]
        clean.insert(0, (0.0, d_at0))
    if clean[-1][0] < src_end:
        clean.append((src_end, d1 + (src_end - s1) * (d1 - d0) / (s1 - s0)))
    lead = clean[0][1]                                    # silence before the audio starts in the output
    dst_end = clean[-1][1] - lead
    y = y[: int(clean[-1][0] * sr)]
    out = None
    if shutil.which("rubberband"):
        with tempfile.TemporaryDirectory() as td:
            fi, fo, fm = os.path.join(td, "i.wav"), os.path.join(td, "o.wav"), os.path.join(td, "m.txt")
            sf.write(fi, y, sr, subtype="FLOAT")
            with open(fm, "w") as f:
                for s, d in clean:
                    f.write(f"{int(round(s * sr))} {int(round((d - lead) * sr))}\n")
            cmd = ["rubberband", "-3", "-q", "-D", f"{dst_end:.6f}", "--timemap", fm]
            if crisp:
                cmd += ["--centre-focus"]
            r = subprocess.run(cmd + [fi, fo], capture_output=True)
            if r.returncode != 0:                         # an older rubberband without that option
                r = subprocess.run(["rubberband", "-q", "-D", f"{dst_end:.6f}", "--timemap", fm, fi, fo], capture_output=True)
            if r.returncode == 0:
                out = sf.read(fo, always_2d=True, dtype="float32")[0]
    if out is None:
        parts = []
        for (a, b), (c, d) in zip(clean[:-1], clean[1:]):
            seg = y[int(a * sr): int(c * sr)]
            want = int(round((d - b) * sr))
            if len(seg) < 64 or want < 64:
                parts.append(np.zeros((max(0, want), y.shape[1]), dtype=np.float32))
                continue
            st = np.stack([librosa.effects.time_stretch(seg[:, ch], rate=len(seg) / want) for ch in range(y.shape[1])], 1)
            st = np.pad(st, ((0, max(0, want - len(st))), (0, 0)))[:want]
            parts.append(st.astype(np.float32))
        out = np.concatenate(parts) if parts else y.copy()
    if lead > 0:
        out = np.concatenate([np.zeros((int(lead * sr), out.shape[1]), dtype=np.float32), out])
    return out


# ---------------------------------------------------------------- set helpers
def main_track(root):
    m = root.find(".//MainTrack")
    return m if m is not None else root.find(".//MasterTrack")


def set_tempo(root):
    return float(main_track(root).find("./DeviceChain/Mixer/Tempo/Manual").get("Value"))


def tempo_env(root, create=False):
    """The tempo automation envelope of the set (or None)."""
    m = main_track(root)
    tid = m.find("./DeviceChain/Mixer/Tempo/AutomationTarget").get("Id")
    parent = m.find("./AutomationEnvelopes/Envelopes")
    for env in parent:
        if env.find("./EnvelopeTarget/PointeeId").get("Value") == tid:
            return env
    if not create:
        return None
    ids = [int(e.get("Id")) for e in parent if (e.get("Id") or "").isdigit()]
    env = ET.SubElement(parent, "AutomationEnvelope", Id=str(max(ids + [-1]) + 1))
    et = ET.SubElement(env, "EnvelopeTarget")
    ET.SubElement(et, "PointeeId", Value=tid)
    au = ET.SubElement(env, "Automation")
    ET.SubElement(au, "Events")
    tv = ET.SubElement(au, "AutomationTransformViewState")
    ET.SubElement(tv, "IsTransformPending", Value="false")
    ET.SubElement(tv, "TimeAndValueTransforms")
    return env


def tempo_points(root):
    """[(beat, bpm)] of the set's tempo automation, without the far-left starting point. Empty = constant."""
    env = tempo_env(root)
    if env is None:
        return []
    return [(float(e.get("Time")), float(e.get("Value"))) for e in env.find("./Automation/Events")
            if float(e.get("Time")) > START / 2]


def write_tempo_points(root, pts):
    """Replace the set's tempo automation with pts [(beat, bpm)], in order. Two points on the same beat
    make a step."""
    env = tempo_env(root, create=True)
    ev = env.find("./Automation/Events")
    for e in list(ev):
        ev.remove(e)
    base = max((int(e.get("Id")) for e in root.iter("FloatEvent") if (e.get("Id") or "").isdigit()), default=0) + 1
    ET.SubElement(ev, "FloatEvent", Id=str(base), Time=str(START), Value=repr(float(pts[0][1])))
    for n, (b, v) in enumerate(pts, 1):
        if not 20.0 <= v <= 999.0:
            raise ValueError(f"tempo {v:.1f} BPM is outside what Live allows (20-999)")
        ET.SubElement(ev, "FloatEvent", Id=str(base + n), Time=repr(float(b)), Value=repr(float(v)))


def beat_seconds(pts, base, beats):
    """Seconds (from beat 0) at which each of `beats` is reached, for tempo points [(beat, bpm)]: linear
    between points, a step where two share a beat, the first value before the first point. `base` BPM is
    used when there are no points."""
    beats = np.asarray(beats, dtype=float)
    if not pts:
        return beats * 60.0 / base
    hi = max(pts[-1][0], float(beats.max()) if len(beats) else 0.0) + 1.0
    P = [(min(0.0, pts[0][0], float(beats.min()) if len(beats) else 0.0) - 1.0, pts[0][1])] + list(pts) + [(hi, pts[-1][1])]

    def span(a, va, b, vb):
        if b <= a:
            return 0.0
        if abs(vb - va) < 1e-9:
            return (b - a) * 60.0 / va
        return 60.0 * (b - a) / (vb - va) * float(np.log(vb / va))   # tempo linear in beats

    T = [0.0]
    for (a, va), (b, vb) in zip(P[:-1], P[1:]):
        T.append(T[-1] + span(a, va, b, vb))
    pb = [b for b, _ in P]

    def at(x):
        i = max(0, min(len(P) - 2, int(np.searchsorted(pb, x, "right")) - 1))
        (a, va), (b, vb) = P[i], P[i + 1]
        vx = va if b <= a else va + (vb - va) * (x - a) / (b - a)
        return T[i] + span(a, va, x, vx)

    zero = at(0.0)
    return np.array([at(float(x)) - zero for x in beats])


def set_val(el, path, value):
    e = el.find(path)
    if e is not None:
        e.set("Value", value if isinstance(value, str) else repr(float(value)))
    return e is not None


def set_markers(clip, pairs):
    """Replace a clip's warp markers with [(seconds, beats)]."""
    wm = clip.find("./WarpMarkers")
    for w in list(wm):
        wm.remove(w)
    for n, (s, b) in enumerate(sorted(pairs)):
        ET.SubElement(wm, "WarpMarker", Id=str(n), SecTime=repr(float(s)), BeatTime=repr(float(b)))


def set_region(clip, first, last, loop=False):
    """The part of the clip that plays: from `first` to `last` (beats when warped, seconds when not)."""
    for tag, v in (("LoopStart", first), ("LoopEnd", last), ("OutMarker", last), ("HiddenLoopStart", first),
                   ("HiddenLoopEnd", last), ("StartRelative", 0.0)):
        set_val(clip, f"./Loop/{tag}", v)
    set_val(clip, "./Loop/LoopOn", "true" if loop else "false")


def straight_warp(clip, tempo, drums=False):
    """Turn warp ON for an unwarped clip so that it plays exactly as before at `tempo` and follows any
    tempo change from now on. Returns False if it was already warped."""
    if clip.find("./IsWarped").get("Value") == "true":
        return False
    k = tempo / 60.0                                  # seconds -> beats
    for tag in ("LoopStart", "LoopEnd", "OutMarker", "HiddenLoopStart", "HiddenLoopEnd", "StartRelative"):
        e = clip.find(f"./Loop/{tag}")
        if e is not None:
            e.set("Value", repr(float(e.get("Value")) * k))
    set_markers(clip, [(0.0, 0.0), (0.03125 / k, 0.03125)])
    clip.find("./IsWarped").set("Value", "true")
    set_val(clip, "./WarpMode", "0" if drums else "6")   # Beats for drums; Complex Pro for everything else
    return True


def clips_of(track):
    ev = track.find("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events")
    return list(ev.findall("AudioClip")) if ev is not None else []


def finish(tree, src, out, added=()):
    """Save as a NEW set next to the original and check its structure. Returns True when it is sound.
    `added`: names of tracks this change adds on purpose (everything else must be the same tracks in order)."""
    from hypnomix.session import automation as aa, check
    src, out = Path(src), Path(out)
    if out.resolve().parent != src.resolve().parent:
        sys.exit(f"write the new set in the same folder as the original ({src.resolve().parent})")
    if out.exists():
        sys.exit(f"{out.name} already exists: nothing is ever overwritten, give a new name")
    aa.save(tree, src, out)
    if added:
        err, warn, _ = check.check(out)
        names = lambda r: [(t.tag, t.find("./Name/EffectiveName").get("Value")) for t in r.find(".//Tracks")]
        was, now, left = names(check.load_root(src)[0]), names(tree.getroot()), list(added)
        rest = []
        for x in now:
            if x[1] in left and (len(rest) >= len(was) or was[len(rest)] != x):
                left.remove(x[1])
            else:
                rest.append(x)
        if rest != was or left:
            err.append("the track list changed beyond the tracks that were added")
    else:
        err, warn, _ = check.check(out, against=src)
    for e in err:
        print(f"  ERROR   {e}")
    if err:
        bad = out.with_name(out.stem + " (BROKEN, do not open).als")
        out.rename(bad)
        print(f"the structural check failed: renamed to {bad.name}. Keep the original and report this.")
        return False
    print("structure OK. Only Live can confirm it opens: keep the original until it has. "
          "Close the original in Live before opening the new set.")
    return True
