#!/usr/bin/env python3
"""Find audible distortion in a song and propose a fix for each case. Writes nothing unless told to.

Give it a Live set (.als), audio files (stems, renders, the full mix), or both. Two kinds of source:

In the recordings (the audio files each Arrangement clip plays, only the parts that are heard):
  flat-top   clipped waveforms: runs of identical samples at the file's peak (count, longest, where)
  clicks     crackle and digital clicks (the `hypnomix clicks` detector)
  harmonics  the loud passages of a clean, single source carry far more odd harmonics than its own
             quieter passages (the clean reference): the signature of clipping or saturation
  aliasing   the loud passages carry inharmonic high-frequency energy their quieter passages don't
  true-peak  inter-sample overs (renders and the full mix: --mix)

Caused by effects in the set (read from the device chains, racks included, with the level hitting each
device estimated from the clip audio and every gain change before it):
  drive      Saturator, Dynamic Tube, Overdrive, Amp, Drum Buss, Roar, Redux driven hard
  limiter    a Limiter doing heavy gain reduction, or releasing too fast for bass
  compressor attack/release too fast for bass (it follows the waveform, not the level)
  clipper    Glue Compressor's Soft Clip pushed by its own makeup gain
  eq-boost   extreme EQ Eight / Channel EQ boosts (they also eat headroom for whatever follows)
  stacked    several limiters/clippers in series on one signal path

Confirmation (--post): give Live's stem export ("Export Audio/Video" > individual tracks, from bar 1) and
each audio track's clips are rendered without devices (`hypnomix render`) and compared with its stem:
distortion is level-dependent, so the tool measures how much brighter (or, for bass, how much more
upper-harmonic) the stem gets than the clip audio in the loud passages compared with the quiet ones, plus
any crest-factor loss and new flat tops. EQ changes loud and quiet passages alike, so it cancels out.

Usage:
  hypnomix distortion SET.als [AUDIO ...] [--post STEMS_DIR] [--mix MIX.wav] [--track NAME ...]
                     [--json OUT.json] [--min-severity low|medium|high]
  hypnomix distortion FILE.wav [FILE2.wav ...]            audio only: times instead of bars
  hypnomix distortion SET.als --apply "SET (less distortion).als"   parameter fixes only, in a NEW set

--apply writes only fixes that are pure parameter changes (e.g. Saturator Drive 18 dB -> 8 dB), for
findings at --min-severity or above (default medium), to a new set in the same folder as the original
(samples linked by relative path go offline elsewhere). Parameters under automation are skipped (the
envelope would override the change). Declip, re-recording and new devices are reported, never applied.

From code (the first-pass scan):  from hypnomix.session.distortion import scan
    rep = scan("Song.als", audio=[...], post="Stems/", mix="Mix.wav");  rep.findings, rep.to_dict()
"""
import argparse, json, math, re, sys
from dataclasses import dataclass, field, asdict
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.ndimage import binary_closing
from scipy.signal import resample_poly

from hypnomix.core.dsp import AUDIO_EXT, load
from hypnomix.ears.clicks import find_clicks
from hypnomix.session import automation as aa
from hypnomix.session import smooth as sm

SEV = {"low": 0, "medium": 1, "high": 2}
SEV_NAME = {v: k for k, v in SEV.items()}
BLK = 0.01                 # block size (s) for mapping file time to arrangement time
ASSUMED_PEAK = -6.0        # input peak assumed when the level can't be estimated (MIDI tracks, after plug-ins)
TP_CEILING = -1.0
ADDED_DB = 8.0             # stem vs clip audio: compression and EQ stay under ~6 dB, saturation goes well over          # dBTP a release should stay under (codecs add overs above it)
BASSY = re.compile(r"bass|kick|808|sub\b|cello|upright|tuba", re.I)
VOCALY = re.compile(r"vox|vocal|voice|lead|harmony|choir|bv", re.I)
LIMITERISH = re.compile(r"limit|clip|maxim|loud", re.I)


# ---------------------------------------------------------------- findings
@dataclass
class Finding:
    source: str                 # recording | effects | mix | file
    kind: str                   # flat-top, clicks, harmonics, aliasing, true-peak, drive, limiter, ...
    track: str
    severity: str               # low | medium | high
    cause: str
    fix: str
    where: str = ""             # bar.beat (sets) or m:ss (audio files)
    time_s: float = None
    device: str = ""
    confirmed: bool = None      # True/False after an audio comparison, None if not checked
    evidence: dict = field(default_factory=dict)
    changes: list = field(default_factory=list)   # pure parameter changes: {device, param, from, to, el}

    def to_dict(self):
        d = asdict(self)
        d["changes"] = [{k: v for k, v in c.items() if k not in ("el", "pel")} for c in self.changes]
        return d


@dataclass
class Report:
    findings: list
    notes: list
    set_path: str = None
    tempo: float = None
    tree: object = None

    def to_dict(self):
        return {"set": self.set_path, "tempo": self.tempo, "notes": self.notes,
                "findings": [f.to_dict() for f in self.findings]}


def bump(sev, d):
    return SEV_NAME[min(2, max(0, SEV[sev] + d))]


def mmss(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"


def dbv(x):
    return 20 * math.log10(max(abs(x), 1e-12))


# ---------------------------------------------------------------- audio detectors (pure functions)
def flat_tops(y, min_run=3, near_db=1.0, min_peak=0.25):
    """Clipped crests: runs of >= min_run identical samples within near_db of the channel's peak.
    Natural crests curve (neighbouring samples differ); clipped ones are flat. Returns
    [(sample, run_length)] sorted by sample, one per flattened crest."""
    y = np.atleast_2d(y.T).T if y.ndim == 1 else y
    out = []
    for c in range(y.shape[1]):
        x = y[:, c]
        pk = float(np.abs(x).max()) if len(x) else 0.0
        if pk < min_peak:
            continue
        hot = np.abs(x) >= pk * 10 ** (-near_db / 20)
        same = np.zeros(len(x), bool)
        same[1:] = np.abs(np.diff(x)) <= pk * 2e-7
        flat = hot & same & np.r_[False, hot[:-1]]
        d = np.diff(np.r_[0, flat.astype(np.int8), 0])
        s, e = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        keep = (e - s + 1) >= min_run
        out += [(int(a - 1), int(b - a + 1)) for a, b in zip(s[keep], e[keep])]
    out.sort()
    merged = []
    for a, n in out:                       # same crest seen on both channels
        if merged and a - merged[-1][0] < 3:
            merged[-1] = (merged[-1][0], max(n, merged[-1][1]))
        else:
            merged.append((a, n))
    return merged


def passages(times, gap=0.5):
    """Group event times (s) into passages: [(start, end, count)]."""
    out = []
    for t in sorted(times):
        if out and t - out[-1][1] <= gap:
            out[-1][1] = t; out[-1][2] += 1
        else:
            out.append([t, t, 1])
    return [tuple(p) for p in out]


def true_peak_blocks(y, sr, block=0.1, chunk=10.0):
    """dBTP of every `block` seconds via 4x oversampling (chunked to keep memory flat)."""
    y = y if y.ndim == 2 else y[:, None]
    bs, cs = int(block * sr), int(chunk * sr) // int(block * sr) * int(block * sr)
    res, pad = [], 64
    for i in range(0, len(y), cs):
        seg = y[max(0, i - pad): i + cs + pad]
        up = np.abs(resample_poly(seg, 4, 1, axis=0)).max(axis=1)
        up = up[(i - max(0, i - pad)) * 4:][: min(cs, len(y) - i) * 4]
        n = len(up) // (bs * 4)
        if n:
            res.append(up[: n * bs * 4].reshape(n, bs * 4).max(axis=1))
    tp = np.concatenate(res) if res else np.zeros(0)
    return 20 * np.log10(np.maximum(tp, 1e-12))


def _to_rate(x, sr, target=22050):
    if sr == target:
        return x
    r = Fraction(target, sr).limit_denominator(1000)
    return resample_poly(x, r.numerator, r.denominator)


def harmonic_frames(x, sr, n=2048, hop=1024):
    """Per voiced frame of a mono signal: time, level dB, THD dB, odd-minus-even harmonic dB,
    inharmonic-to-harmonic ratio 4-10 kHz dB. Frames that aren't clearly periodic are dropped."""
    x = _to_rate(np.asarray(x, float), sr)
    sr = 22050
    if len(x) < n * 4:
        return None
    nf = 1 + (len(x) - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(nf)[:, None]
    fr = x[idx] * np.hanning(n)
    lvl = 10 * np.log10(np.mean(fr ** 2, axis=1) + 1e-14)
    snd = lvl > lvl.max() - 45
    fr, lvl, t = fr[snd], lvl[snd], (np.flatnonzero(snd) * hop + n / 2) / sr
    nfft = 4 * n
    X = np.abs(np.fft.rfft(fr, nfft, axis=1))
    ac = np.fft.irfft(X ** 2, nfft, axis=1)[:, :n]
    ac /= ac[:, :1] + 1e-14
    lo, hi = int(sr / 1000), int(sr / 70)
    lag = lo + np.argmax(ac[:, lo:hi], axis=1)
    per = ac[np.arange(len(lag)), lag]
    voiced = per > 0.85
    rows = []
    hz = sr / nfft
    for k in np.flatnonzero(voiced):
        L = lag[k]
        a, b, c = ac[k, L - 1], ac[k, L], ac[k, min(L + 1, n - 1)]
        dl = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0
        f0 = sr / (L + float(np.clip(dl, -1, 1)))
        if not 60 < f0 < 1100:
            continue
        spec = X[k]
        h = []
        for m in range(1, 16):
            f = m * f0
            if f > 9500:
                break
            i0, i1 = int(f * 0.98 / hz), int(f * 1.02 / hz) + 1
            h.append(spec[i0:i1].max() ** 2 if i1 > i0 else 0.0)
        if len(h) < 6 or h[0] <= 0:
            continue
        h = np.array(h)
        thd = 10 * np.log10(h[5:].sum() / h[:3].sum() + 1e-14)   # upper harmonics (6th+) over the first three
        odd = h[2::2].sum(); even = h[1::2].sum()
        oe = 10 * np.log10((odd + 1e-14) / (even + 1e-14))
        band = spec[int(4000 / hz): int(10000 / hz)] ** 2
        fb = np.arange(int(4000 / hz), int(10000 / hz)) * hz
        dist = np.abs(fb / f0 - np.round(fb / f0)) * f0      # Hz from the nearest harmonic
        on = dist < max(2 * hz, 0.03 * f0)
        inh = 10 * np.log10((band[~on].sum() + 1e-14) / (band[on].sum() + 1e-14)) if on.any() else 0.0
        rows.append((t[k], lvl[k], thd, oe, inh))
    if not rows:
        return None
    r = np.array(rows)
    return dict(t=r[:, 0], lvl=r[:, 1], thd=r[:, 2], oe=r[:, 3], inh=r[:, 4],
                voiced_share=float(voiced.mean()), sounding=int(snd.sum()))


def harmonic_excess(hf):
    """Compare a source's loudest voiced frames with its own quieter ones (the clean reference)."""
    if hf is None or len(hf["t"]) < 60 or hf["voiced_share"] < 0.15:
        return None
    lv = hf["lvl"]
    p20, p50, p80 = np.percentile(lv, [20, 50, 80])
    loud, ref = lv >= p80, (lv >= p20) & (lv <= p50)
    if loud.sum() < 20 or ref.sum() < 20 or np.median(lv[loud]) - np.median(lv[ref]) < 6:
        return None
    m = lambda k, sel: float(np.median(hf[k][sel]))
    ex = dict(thd=m("thd", loud) - m("thd", ref), odd=m("oe", loud) - m("oe", ref),
              inh=m("inh", loud) - m("inh", ref), contrast=float(np.median(lv[loud]) - np.median(lv[ref])),
              frames=int(len(lv)))
    score = hf["thd"] - m("thd", ref) + hf["oe"] - m("oe", ref)
    worst = np.argsort(-np.where(loud, score, -np.inf))[:3]
    ex["worst_s"] = [float(hf["t"][i]) for i in worst if loud[i]]
    return ex


def harmonic_finding(ex):
    """(kind, severity, cause) from harmonic_excess, or None."""
    if ex is None:
        return None
    # Calibrated on ~130 real vocal takes: natural singing gets brighter when louder, so only the extreme
    # tail (both measures far above what clean takes show) is reported, and only as "possible".
    if ex["odd"] >= 7 and ex["thd"] >= 7:
        sev = "medium" if ex["odd"] >= 10 and ex["thd"] >= 10 else "low"
        return ("harmonics", sev, f"possible saturation: loud passages carry {ex['thd']:+.1f} dB more upper harmonics "
                f"(6th and up) than the same source's quieter passages, mostly odd ({ex['odd']:+.1f} dB odd over even)")
    if ex["inh"] >= 8:
        return ("aliasing", "medium" if ex["inh"] >= 12 else "low",
                f"loud passages carry {ex['inh']:+.1f} dB more inharmonic energy at 4-10 kHz than quieter ones "
                "(aliasing from digital clipping or a non-oversampled shaper)")
    return None


def audio_checks(y, sr, label, *, is_mix=False, harmonics=True, heard=None):
    """Every recording/render detector on one file. `heard`: optional bool per 10 ms block; events outside
    it are ignored (the parts of a take no clip plays). Returns [(kind, severity, cause, fix, times_s, evidence)]."""
    out = []
    mono = y.mean(axis=1)
    keep = (lambda t: True) if heard is None else (lambda t: bool(heard[min(len(heard) - 1, int(t / BLK))]))
    ft = [e for e in flat_tops(y) if keep(e[0] / sr)]
    ft_times = [a / sr for a, _ in ft]
    if ft:
        longest = max(n for _, n in ft) / sr * 1000
        ps = passages(ft_times)
        n = len(ft)
        sev = "high" if n >= 50 or (n >= 5 and longest >= 1.0) else "medium" if n >= 5 or longest >= 2.0 else "low"
        lvl = dbv(np.abs(y).max())
        cause = (f"{len(ft)} flattened peaks in {len(ps)} passages at {lvl:.1f} dBFS (longest {longest:.2f} ms)")
        if is_mix:
            fix = ("the bounce clipped: lower the master before the last limiter, or set its ceiling to "
                   f"{TP_CEILING:g} dBTP and re-export at 24-bit or 32-bit float")
        elif longest > 4:
            fix = "too long to rebuild: re-record the passage (or comp it from another take)"
        else:
            fix = ("declip the source with `hypnomix prep` (cubic rebuild of the flat tops)"
                   + ("; if it's the whole performance, re-record with the input gain 6 dB lower" if n >= 50 else ""))
        worst = sorted(ps, key=lambda p: -p[2])[:3]
        out.append(("flat-top", sev, cause, fix, [p[0] for p in worst],
                    dict(count=len(ft), passages=len(ps), longest_ms=round(longest, 2))))
    if not is_mix:
        ev = [e for e in find_clicks(mono, sr) if keep(e[0] / sr)]
        ftset = np.array(ft_times)
        ev = [e for e in ev if not len(ftset) or np.abs(ftset - e[0] / sr).min() > 0.003]
        if ev:
            sev = "medium" if len(ev) >= 20 else "low"
            out.append(("clicks", sev, f"{len(ev)} clicks/crackle (waveform jumps far beyond the local signal)",
                        "declick with `hypnomix prep`; clicks at clip edges: `hypnomix smooth` adds fades",
                        [e[0] / sr for e in ev[:3]], dict(count=len(ev))))
    pk = float(np.abs(y).max())
    if pk > 0.7 and (is_mix or label == "file"):
        tp = true_peak_blocks(y, sr)
        over = tp > TP_CEILING
        if over.any():
            mx = float(tp.max())
            sev = "high" if mx > 0.5 else "medium" if mx > 0 else "low"
            ps = passages(list(np.flatnonzero(over) * 0.1), gap=1.0)
            out.append(("true-peak", sev,
                        f"inter-sample peaks up to {mx:+.2f} dBTP in {len(ps)} passages "
                        f"({int((tp > 0).sum())} x 0.1 s blocks over 0 dBTP); streaming codecs clip these",
                        f"bring the final limiter ceiling down {mx - TP_CEILING:.1f} dB (to {TP_CEILING:g} dBTP)",
                        [p[0] for p in sorted(ps, key=lambda p: -p[2])[:3]],
                        dict(max_dbtp=round(mx, 2), blocks_over_0=int((tp > 0).sum()))))
    if harmonics and not is_mix:
        hf = harmonic_frames(mono, sr)
        if hf is not None and heard is not None:
            sel = np.array([keep(t) for t in hf["t"]], bool)
            hf = dict(hf, **{k: hf[k][sel] for k in ("t", "lvl", "thd", "oe", "inh")})
        ex = harmonic_excess(hf)
        h = harmonic_finding(ex)
        if h:
            kind, sev, cause = h
            if ft:
                cause += " (consistent with the flat tops above)"
                sev = bump(sev, 1)
            fix = ("declip with `hypnomix prep` if it's clipping; if it was recorded through a hot preamp or "
                   "pedal, re-record with less gain" if kind == "harmonics" else
                   "re-render/re-record the passage; use oversampling (Hi-Quality) on any shaper that made it")
            out.append((kind, sev, cause, fix, ex["worst_s"], {k: round(v, 2) if isinstance(v, float) else v
                                                              for k, v in ex.items() if k != "worst_s"}))
    return out


# ---------------------------------------------------------------- set helpers
def tname(t):
    return "Main" if t.tag in ("MainTrack", "MasterTrack") else t.find("./Name/EffectiveName").get("Value")


def pointees(root):
    return {p.get("Value") for p in root.iter("PointeeId")}


class Param:
    def __init__(self, d, name):
        self.e = d.find(f"./{name}")
        self.m = self.e.find("./Manual") if self.e is not None else None
        self.name = name

    @property
    def ok(self):
        return self.m is not None

    @property
    def v(self):
        s = self.m.get("Value")
        return {"true": 1.0, "false": 0.0}.get(s, None) if s in ("true", "false") else float(s)

    def automated(self, pts):
        at = self.e.find("./AutomationTarget") if self.e is not None else None
        return at is not None and at.get("Id") in pts


def pv(d, name, default=0.0):
    p = Param(d, name)
    return p.v if p.ok else default


STOCK = {"Compressor2": "Compressor", "StereoGain": "Utility", "Eq8": "EQ Eight", "GlueCompressor": "Glue Compressor",
         "DrumBuss": "Drum Buss", "Redux2": "Redux", "ChannelEq": "Channel EQ", "Tube": "Dynamic Tube",
         "MultibandDynamics": "Multiband Dynamics", "AudioEffectGroupDevice": "Audio Effect Rack",
         "InstrumentGroupDevice": "Instrument Rack", "DrumGroupDevice": "Drum Rack"}
PLUGIN = ("AuPluginDevice", "PluginDevice", "Vst3PluginDevice", "VstPluginDevice")


def dlabel(d):
    from hypnomix.session.audit import dev_name
    if d.tag in PLUGIN:
        return dev_name(d)
    base = STOCK.get(d.tag, d.tag)
    un = d.find("./UserName")
    un = un.get("Value") if un is not None else ""
    return f"{un} ({base})" if un and un != base else base


def is_on(d):
    p = Param(d, "On")
    return not p.ok or p.v > 0


def change(dev, p, to, fmt):
    return dict(device=dev, param=p.name, **{"from": round(p.v, 4), "to": round(to, 4)}, shown=fmt, el=p.m, pel=p.e)


# ---------------------------------------------------------------- effects: gain-staging walk
GLUE_RATIO = {0: 2.0, 1: 4.0, 2: 10.0}
GLUE_ATT = {0: 0.01, 1: 0.1, 2: 0.3, 3: 1, 4: 3, 5: 10, 6: 30}


class Stage:
    """Running estimate of the peak level (dBFS) through one chain."""

    def __init__(self, peak, assumed, ctx):
        self.peak, self.assumed, self.ctx = peak, assumed, ctx
        self.boosts = []           # explicit gains before the current device: (label, dB)
        self.utility = None        # last Utility before the current device: (label, Param)


def lvl_text(s):
    return f"~{s.peak:+.1f} dBFS peak" + (" (assumed)" if s.assumed else "") if s.peak is not None else "unknown level"


def boosts_text(s):
    b = [f"{g:+.1f} dB from {n}" for n, g in s.boosts if g >= 1]
    return f", including {', '.join(b)}" if b else ""


def devices_of(chain_el):
    return list(chain_el) if chain_el is not None else []


def branch_devices(d):
    out = []
    br = d.find("./Branches")
    for b in (list(br) if br is not None else []):
        for p in ("./DeviceChain/AudioToAudioDeviceChain/Devices", "./DeviceChain/MidiToAudioDeviceChain/Devices"):
            e = b.find(p)
            if e is not None:
                out.append(e)
                break
    return out


def walk_chain(devs, s, add, path_stages):
    """Walk devices in order, updating the level estimate s and calling add(...) for each finding."""
    ctx = s.ctx
    for d in devs:
        if not is_on(d):
            continue
        lab = dlabel(d)
        tag = d.tag
        inner = branch_devices(d)
        if inner:                                          # rack: each branch gets the rack's input
            outs, branch_stages = [], []
            for b in inner:                                # branches run in parallel, not in series
                bs = Stage(s.peak, s.assumed, ctx); bs.boosts = list(s.boosts); bs.utility = s.utility
                mine = []
                walk_chain(list(b), bs, add, mine)
                outs.append(bs.peak); branch_stages.append([(tr, x if " (in " in x else f"{x} (in {lab})") for tr, x in mine])
            path_stages += max(branch_stages, key=len, default=[])
            if tag != "AudioEffectGroupDevice":          # instruments/drums: output level unknown
                s.peak, s.assumed = ASSUMED_PEAK, True
            elif outs and all(o is not None for o in outs):
                s.peak = 10 * math.log10(sum(10 ** (o / 10) for o in outs) / len(outs)) if len(outs) > 1 else outs[0]
            continue
        if tag in PLUGIN:
            if LIMITERISH.search(lab):
                path_stages.append((ctx["track"], lab))
            s.assumed = True                               # a plug-in can change the level any amount
            continue
        if s.peak is None:
            s.peak, s.assumed = ASSUMED_PEAK, True
        wet = 1.0
        if tag == "StereoGain":
            g = Param(d, "Gain")
            if g.ok and g.v > 0:
                gdb = dbv(g.v)
                s.peak += gdb
                if gdb:
                    s.boosts.append((lab, gdb))
                s.utility = (lab, g)
            continue
        if tag == "Saturator":
            pre, typ, post = Param(d, "PreDrive"), int(pv(d, "Type")), pv(d, "PostDrive")
            wet = pv(d, "DryWet", 1)
            hard = typ in (3, 5)
            if pv(d, "PostClip") or typ == 5:
                path_stages.append((ctx["track"], lab + (" clip" if pv(d, "PostClip") else " digital clip")))
            into = s.peak + pre.v
            target = 1.0 if hard else 6.0
            excess = into - target
            if excess >= 3:
                sev = "high" if excess >= 9 else "medium"
                new = max(-36.0, round((pre.v - excess) * 2) / 2)
                add("drive", sev, lab, wet, s,
                    f"{lab} is driven to {into:+.1f} dB ({lvl_text(s)} in{boosts_text(s)} plus {pre.v:+.1f} dB Drive) "
                    f"into a {'hard' if hard else 'soft'} curve: heavy clipping",
                    f"{lab} Drive {pre.v:.1f} dB -> {new:.1f} dB (then check its output level)",
                    [change(lab, pre, new, f"Drive {pre.v:.1f} -> {new:.1f} dB")])
            s.peak = min(into, 0.0) + post
            s.boosts = []                                  # it clamped: earlier boosts are spent
            continue
        if tag == "Tube":
            pre, post = Param(d, "PreDrive"), pv(d, "PostDrive")
            wet = pv(d, "DryWet", 1)
            into = s.peak + pre.v
            if into >= 6:
                sev = "high" if into >= 12 else "medium"
                new = round((pre.v - (into - 0)) * 2) / 2
                add("drive", sev, lab, wet, s,
                    f"{lab} is driven to {into:+.1f} dB ({lvl_text(s)} in{boosts_text(s)} plus {pre.v:+.1f} dB Drive)",
                    f"{lab} Drive {pre.v:.1f} dB -> {new:.1f} dB", [change(lab, pre, new, f"Drive {pre.v:.1f} -> {new:.1f} dB")])
            s.peak = min(into, 0.0) + post
            s.boosts = []                                  # it clamped: earlier boosts are spent
            continue
        if tag == "Overdrive":
            dr = Param(d, "Drive"); wet = pv(d, "DryWet", 100) / 100
            if dr.v >= 60:
                sev = "high" if dr.v >= 85 else "medium"
                add("drive", sev, lab, wet, s, f"{lab} Drive at {dr.v:.0f}% ({wet * 100:.0f}% wet), {lvl_text(s)} in",
                    f"{lab} Drive {dr.v:.0f}% -> 40%", [change(lab, dr, 40.0, f"Drive {dr.v:.0f}% -> 40%")])
            continue
        if tag == "Amp":
            g = Param(d, "Gain"); wet = pv(d, "DryWet", 1)
            hot = s.peak > -3 and not s.assumed
            if g.v >= 6.5 or (hot and g.v >= 5):
                sev = "high" if g.v >= 8 else "medium"
                fix = f"{lab} Gain {g.v:.1f} -> 4.0"
                if hot:
                    fix += f", and lower the input {s.peak + 9:.0f} dB with a Utility before the amp"
                add("drive", sev, lab, wet, s, f"{lab} Gain {g.v:.1f}/10 with {lvl_text(s)} going in{boosts_text(s)}",
                    fix, [change(lab, g, 4.0, f"Gain {g.v:.1f} -> 4.0")])
            continue
        if tag == "DrumBuss":
            dr, cr = Param(d, "DriveAmount"), Param(d, "CrunchAmount"); wet = pv(d, "DryWet", 1)
            trim = dbv(pv(d, "InputTrim", 1))
            worst = max(dr.v, cr.v if cr.ok else 0)
            if worst >= 0.6:
                p = dr if dr.v >= (cr.v if cr.ok else 0) else cr
                add("drive", "high" if worst >= 0.85 else "medium", lab, wet, s,
                    f"{lab} {p.name.replace('Amount', '')} at {p.v * 100:.0f}% (input trim {trim:+.1f} dB)",
                    f"{lab} {p.name.replace('Amount', '')} {p.v * 100:.0f}% -> 30%",
                    [change(lab, p, 0.3, f"{p.name} {p.v * 100:.0f}% -> 30%")])
            s.peak += trim + dbv(pv(d, "OutputGain", 1))
            continue
        if tag == "Roar":
            ig = Param(d, "Input_InputGain")
            amts = [Param(d, f"Stage{i}_Shaper_Amount") for i in (1, 2, 3)]
            amts = [a for i, a in zip((1, 2, 3), amts) if a.ok and pv(d, f"Stage{i}_On", 1) and pv(d, f"Stage{i}_Shaper_On", 1)]
            mx = max((a.v for a in amts), default=0)
            igdb = dbv(ig.v) if ig.ok else 0
            if mx >= 0.6 or (igdb >= 6 and mx >= 0.3):
                ch = [change(lab, ig, 1.0, f"Input {igdb:+.1f} -> 0 dB")] if igdb >= 6 else \
                     [change(lab, a, 0.4, f"{a.name} {a.v * 100:.0f}% -> 40%") for a in amts if a.v >= 0.6]
                add("drive", "high" if mx >= 0.85 else "medium", lab, 1, s,
                    f"{lab} shaper amount {mx * 100:.0f}% with input {igdb:+.1f} dB ({lvl_text(s)} in)",
                    "; ".join(f"{lab} {c['shown']}" for c in ch), ch)
            continue
        if tag == "Redux2":
            bd, sr_ = Param(d, "BitDepth"), Param(d, "SampleRate")
            if (bd.ok and bd.v <= 8) or (sr_.ok and sr_.v <= 11025):
                ch = []
                if bd.ok and bd.v <= 8:
                    ch.append(change(lab, bd, 16.0, f"Bit Depth {bd.v:.0f} -> 16"))
                if sr_.ok and sr_.v <= 11025:
                    ch.append(change(lab, sr_, 40000.0, f"Sample Rate {sr_.v:.0f} -> 40000 Hz"))
                add("aliasing", "low", lab, pv(d, "DryWet", 1), s,
                    f"{lab} at {bd.v:.0f} bits / {sr_.v:.0f} Hz: bit-crushing and aliasing (fine if intended)",
                    "; ".join(f"{lab} {c['shown']}" for c in ch), ch)
            continue
        if tag == "Limiter":
            g, ce = Param(d, "Gain"), Param(d, "Ceiling")
            rel, auto = pv(d, "Release", 300), pv(d, "AutoRelease", 1)
            path_stages.append((ctx["track"], lab))
            into = s.peak + g.v
            gr = into - ce.v
            main = ctx["main"]
            target, med, high = (5, 8, 12) if main else (3, 6, 10)
            if gr >= med:
                sev = "high" if gr >= high else "medium"
                cut = gr - target
                ch, fix = [], []
                if g.v > 0:
                    newg = max(0.0, round((g.v - cut) * 2) / 2)
                    ch.append(change(lab, g, newg, f"Gain {g.v:.1f} -> {newg:.1f} dB"))
                    fix.append(f"{lab} Gain {g.v:.1f} dB -> {newg:.1f} dB")
                    cut -= g.v - newg
                if cut >= 0.5:
                    if s.utility:
                        ul, up = s.utility
                        nl = 10 ** ((dbv(up.v) - cut) / 20)
                        ch.append(change(ul, up, nl, f"Gain {dbv(up.v):+.1f} -> {dbv(nl):+.1f} dB"))
                        fix.append(f"{ul} Gain {dbv(up.v):+.1f} dB -> {dbv(nl):+.1f} dB")
                    else:
                        fix.append(f"lower the input {cut:.1f} dB (a Utility before the {lab})")
                add("limiter", sev, lab, 1, s,
                    f"{lab} takes ~{gr:.1f} dB off the peaks ({lvl_text(s)} in{boosts_text(s)}, Gain {g.v:+.1f}, "
                    f"Ceiling {ce.v:.1f}): flattened transients and audible clipping",
                    "; ".join(fix), ch)
            if not auto and rel < 30 and ctx["bassy"] and gr >= 2:
                rp = Param(d, "Release")
                add("limiter", "medium", lab, 1, s,
                    f"{lab} releases in {rel:.0f} ms on a bass-heavy source: it follows the waveform (low-end distortion)",
                    f"{lab} Release {rel:.0f} ms -> 100 ms", [change(lab, rp, 100.0, f"Release {rel:.0f} -> 100 ms")])
            s.peak = min(into, ce.v)
            s.boosts = []                                  # it clamped: earlier boosts are spent
            continue
        if tag == "Compressor2":
            thr = dbv(pv(d, "Threshold", 1)); ratio = pv(d, "Ratio", 1); model = int(pv(d, "Model"))
            at, rl = Param(d, "Attack"), Param(d, "Release")
            autorel = pv(d, "AutoReleaseControlOnOff", 0)
            wet = pv(d, "DryWet", 1)
            gr = max(0.0, s.peak - thr) * (1 - 1 / ratio) if ratio > 1 and model != 2 else 0.0
            if model == 1:
                gr *= 0.6                                  # RMS detection reacts less to peaks
            if ctx["bassy"] and gr >= 3 and not autorel and (at.v < 3 and rl.v < 40):
                sev = "high" if rl.v < 15 and gr >= 8 else "medium"
                ch = [change(lab, rl, 100.0, f"Release {rl.v:.0f} -> 100 ms")]
                fx = [f"{lab} Release {rl.v:.0f} ms -> 100 ms"]
                if at.v < 1:
                    ch.append(change(lab, at, 10.0, f"Attack {at.v:.2f} -> 10 ms")); fx.append(f"Attack {at.v:.2f} ms -> 10 ms")
                add("compressor", sev, lab, wet, s,
                    f"{lab} attack {at.v:.2f} ms / release {rl.v:.0f} ms with ~{gr:.0f} dB gain reduction on a "
                    "bass-heavy source: faster than one bass cycle, so it reshapes the waveform (distortion)",
                    ", ".join(fx), ch)
            s.peak = s.peak - gr + pv(d, "Gain", 0)
            mk = pv(d, "Gain", 0)
            if mk >= 1:
                s.boosts.append((lab + " makeup", mk))
            continue
        if tag == "GlueCompressor":
            thr = pv(d, "Threshold", 0); ratio = GLUE_RATIO.get(int(pv(d, "Ratio")), 4.0)
            mk = Param(d, "Makeup"); clip = pv(d, "PeakClipIn", 0)
            gr = max(0.0, s.peak - thr) * (1 - 1 / ratio)
            out = s.peak - gr + mk.v
            if clip:
                path_stages.append((ctx["track"], lab + " soft clip"))
                if out >= 3:
                    sev = "high" if out >= 8 else "medium"
                    new = max(0.0, round((mk.v - out) * 2) / 2)
                    add("clipper", sev, lab, pv(d, "DryWet", 1), s,
                        f"{lab} Soft Clip is hit {out:+.1f} dB over full scale ({lvl_text(s)} in, ~{gr:.0f} dB "
                        f"reduction, {mk.v:+.1f} dB makeup)",
                        f"{lab} Makeup {mk.v:.1f} dB -> {new:.1f} dB", [change(lab, mk, new, f"Makeup {mk.v:.1f} -> {new:.1f} dB")])
                out = min(out, 0.0)
            s.peak = out
            if mk.v >= 1:
                s.boosts.append((lab + " makeup", mk.v))
            continue
        if tag == "Eq8":
            from hypnomix.session.audit import TYPES
            big, hits = 0.0, []
            for i in range(8):
                b = d.find(f"./Bands.{i}/ParameterA")
                if b is None or pv(b, "IsOn", 0) < 1:
                    continue
                mode = TYPES.get(int(pv(b, "Mode", 3)), "?")
                g = Param(b, "Gain")
                if mode not in ("Bell", "LowShelf", "HighShelf") or not g.ok:
                    continue
                if g.v >= 9:
                    g.name = f"Band {i + 1} Gain"
                    hits.append((i + 1, mode, pv(b, "Freq"), pv(b, "Q", 0.71), g))
                big = max(big, g.v)
            if hits:
                mx = max(h[4].v for h in hits)
                desc = ", ".join(f"band {n} {m} {f:.0f} Hz {g.v:+.1f} dB (Q {q:.2f})" for n, m, f, q, g in hits)
                add("eq-boost", "high" if mx >= 12 else "medium", lab, 1, s,
                    f"{lab} {desc}: extreme boost{'s' if len(hits) > 1 else ''} eat headroom and push everything after harder",
                    "; ".join(f"{lab} band {n} {g.v:+.1f} dB -> +6.0 dB" for n, m, f, q, g in hits) + " (cut elsewhere instead)",
                    [change(lab, g, 6.0, f"band {n} {g.v:+.1f} -> +6.0 dB") for n, m, f, q, g in hits])
            if big >= 6:
                s.peak += big * 0.5; s.boosts.append((lab + " boost", big * 0.5))
            gg = Param(d, "GlobalGain")
            if gg.ok:
                s.peak += gg.v
            continue
        if tag == "ChannelEq":
            hits = [g for g in (Param(d, n) for n in ("LowShelfGain", "MidGain", "HighShelfGain")) if g.ok and g.v >= 2.818]
            if hits:
                nm = lambda g: g.name.replace("Gain", "").replace("Shelf", " shelf")
                add("eq-boost", "high" if max(g.v for g in hits) >= 3.98 else "medium", lab, 1, s,
                    f"{lab} " + ", ".join(f"{nm(g)} {dbv(g.v):+.1f} dB" for g in hits) +
                    ": extreme boosts eat headroom for whatever follows",
                    "; ".join(f"{lab} {nm(g)} {dbv(g.v):+.1f} dB -> +6.0 dB" for g in hits),
                    [change(lab, g, 2.0, f"{nm(g)} {dbv(g.v):+.1f} -> +6.0 dB") for g in hits])
            s.peak += dbv(pv(d, "Gain", 1))
            continue


def mixer_db(t):
    v = t.find("./DeviceChain/Mixer/Volume/Manual")
    return dbv(float(v.get("Value"))) if v is not None and float(v.get("Value")) > 0 else -99.0


def effects_findings(root, track_info, pts, names, include_off):
    """track_info: name -> dict(peak, beat, bassy) from the clip audio. Returns (findings, notes)."""
    tracks = [t for t in root.find(".//Tracks")]
    main = root.find(".//MainTrack")
    if main is None:
        main = root.find(".//MasterTrack")
    by_id = {t.get("Id"): t for t in tracks}
    parent = {t.get("Id"): sm.val(t, "./TrackGroupId", str, "-1") for t in tracks}
    findings, notes = [], []
    out_peak, stages_of = {}, {}

    def chain_of(t):
        return devices_of(t.find("./DeviceChain/DeviceChain/Devices"))

    def run(t):
        key = id(t)
        if key in out_peak:
            return out_peak[key]
        nm = tname(t)
        ismain = t is main
        info = track_info.get(nm, {})
        if t.tag == "AudioTrack" and info.get("peak") is not None:
            peak, assumed = info["peak"], False
        elif t.tag == "GroupTrack" or ismain:
            kids = [k for k in tracks if (parent[k.get("Id")] == t.get("Id")) if not ismain] if not ismain else \
                   [k for k in tracks if parent[k.get("Id")] == "-1" and k.tag != "ReturnTrack"]
            ps = [run(k) for k in kids if sm.track_on(k)]
            known = [p for p, a in ps if p is not None]
            peak = 10 * math.log10(sum(10 ** (p / 10) for p in known)) if known else None
            assumed = not known or any(a for _, a in ps)
        else:
            peak, assumed = None, True
        ctx = dict(track=nm, main=ismain, bassy=info.get("bassy", bool(BASSY.search(nm))))
        s = Stage(peak, assumed, ctx)
        path = []
        on = sm.track_on(t) or ismain

        def add(kind, sev, dev, wet, st, cause, fix, ch):
            if not on or (names and not ismain and not any(n.lower() in nm.lower() for n in names)):
                return
            if wet < 0.35:
                sev = bump(sev, -1); cause += f" (only {wet * 100:.0f}% wet)"
            if st.assumed:
                sev = bump(sev, -1)
            f = Finding("effects", kind, nm, sev, cause, fix, device=dev, changes=ch,
                        evidence=dict(level_assumed=st.assumed))
            if info.get("beat") is not None and t.tag == "AudioTrack":
                f.where = sm.where(info["beat"]); f.evidence["hottest"] = "loudest clip passage"
            findings.append(f)

        walk_chain(chain_of(t), s, add, path)
        stages_of[key] = path
        p = s.peak
        res = (p + mixer_db(t) if p is not None else None, s.assumed)
        out_peak[key] = res
        return res

    for t in tracks:
        run(t)
    run(main)
    # stacked limiters/clippers along each track -> groups -> Main path
    seen = set()
    for t in tracks:
        if t.tag in ("GroupTrack", "ReturnTrack") or not sm.track_on(t):
            continue
        st, cur = list(stages_of.get(id(t), [])), t
        while parent.get(cur.get("Id"), "-1") != "-1" and parent[cur.get("Id")] in by_id:
            cur = by_id[parent[cur.get("Id")]]
            st += stages_of.get(id(cur), [])
        st += stages_of.get(id(main), [])
        if len(st) >= 2 and tuple(st) not in seen:
            if names and not any(n.lower() in tname(t).lower() for n in names):
                continue
            seen.add(tuple(st))
            sev = "medium" if len(st) >= 4 else "low"     # 2-3 is common by design (factory drum kits)
            chain = " -> ".join(f"{d} on {tr}" for tr, d in st)
            findings.append(Finding("effects", "stacked", tname(t), sev,
                                    f"{len(st)} limiters/clippers in series: {chain}. Each one flattens what the last "
                                    "one let through, and the distortion adds up",
                                    "keep one final limiter on Main; on the others back off the gain until they "
                                    "only catch the odd peak (or switch them off and compare)"))
    merged = {}
    for f in findings:                        # identical devices (copies inside racks): one finding
        k = (f.track, f.kind, f.device, f.cause)
        if k in merged:
            merged[k].changes += f.changes
            merged[k].evidence["copies"] = merged[k].evidence.get("copies", 1) + 1
        else:
            merged[k] = f
    for f in merged.values():
        if f.evidence.get("copies"):
            f.cause += f" ({f.evidence['copies']} identical copies)"
    return list(merged.values()), notes


# ---------------------------------------------------------------- recordings in a set
def file_blocks(ci, tempo, nblk):
    """Arrangement beat for each 10 ms block of the clip's file that is heard (first play), as a dict."""
    dur = (ci["end"] - ci["start"]) * 60 / tempo
    tt = np.arange(0, dur, BLK)
    beats = ci["start"] + tt * tempo / 60
    secs = sm.file_seconds(ci, beats, tempo)
    blk = np.floor(secs / BLK).astype(int)
    ok = (blk >= 0) & (blk < nblk)
    return blk[ok], beats[ok]


def beat_near(beat_of, t, reach=100):
    """Arrangement beat of file time t (s): the nearest heard block within `reach` blocks."""
    i = min(len(beat_of) - 1, int(t / BLK))
    lo, hi = max(0, i - reach), min(len(beat_of), i + reach + 1)
    w = np.flatnonzero(~np.isnan(beat_of[lo:hi]))
    if not len(w):
        return None
    j = lo + w[np.argmin(np.abs(lo + w - i))]
    return float(beat_of[j])


def merge_takes(tn, kind, rows):
    """One finding per track and kind: the worst take leads, the others are listed."""
    rows = sorted(rows, key=lambda r: (-SEV[r[0]], -r[4].get("count", 0)))
    sev, cause, fix, bts, evd, path = rows[0]
    total = sum(r[4].get("count", 1) for r in rows)
    if len(rows) > 1:
        cause = f"{len(rows)} takes affected ({total} in all); worst {path.name}: {cause}"
    also = [sm.where(b) for b in bts[1:]] + [sm.where(r[3][0]) for r in rows[1:] if r[3]]
    ev = dict(evd, file=str(path), takes=[str(r[5]) for r in rows], total=total)
    if also:
        ev["also_at"] = also[:8] + (["..."] if len(also) > 8 else [])
    return Finding("recording", kind, tn, sev, cause, fix, where=sm.where(bts[0]) if bts else "", evidence=ev)


def recording_findings(root, als_dir, tempo, names, include_off, harmonics=True, log=print):
    """Detectors on every source file, keeping only events in the parts that are heard. Also returns
    per-track level info for the gain-staging walk."""
    findings, info, notes = [], {}, []
    skipped = []
    for tn, t in sm.audio_tracks(root, None, include_off, skipped):
        ev = t.find("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events")
        clips = [sm.clip_info(c, als_dir, tempo) for c in (ev.findall("AudioClip") if ev is not None else [])]
        clips = sorted([c for c in clips if not c["disabled"]], key=lambda c: c["start"])
        miss = [c for c in clips if not c["path"].exists()]
        for c in miss:
            notes.append(f"{tn}: audio file not found: {c['path']}")
        clips = [c for c in clips if c["path"].exists()]
        if not clips:
            continue
        check = not names or any(n.lower() == tn.lower() or tn.lower().startswith(n.lower()) for n in names)
        best = (-200.0, None)
        lows, per = [], {}
        for path in dict.fromkeys(c["path"] for c in clips):
            try:
                y, sr = load(path)
            except Exception as e:                          # noqa: BLE001 (any unreadable file is skipped)
                notes.append(f"{tn}: couldn't read {path.name} ({type(e).__name__}); not checked")
                continue
            if not len(y):
                continue
            nblk = int(np.ceil(len(y) / (sr * BLK)))
            beat_of = np.full(nblk, np.nan)
            gain_of = np.zeros(nblk)
            for c in [c for c in clips if c["path"] == path]:
                b, bt = file_blocks(c, tempo, nblk)
                new = np.isnan(beat_of[b])
                beat_of[b[new]] = bt[new]
                gain_of[b] = np.maximum(gain_of[b], c["gain"])
            heard = ~np.isnan(beat_of)
            if not heard.any():
                continue
            k = int(sr * BLK)
            pad = np.zeros((nblk * k - len(y), y.shape[1]))
            pk = np.abs(np.vstack([y, pad])).max(axis=1).reshape(nblk, k).max(axis=1) * gain_of
            i = int(np.argmax(np.where(heard, pk, 0)))
            if pk[i] > 0 and dbv(pk[i]) > best[0]:
                best = (dbv(pk[i]), float(beat_of[i]))
            m = y.mean(axis=1)
            spec = np.abs(np.fft.rfft(m[: sr * 60])) ** 2 if len(m) else np.zeros(1)
            fq = np.fft.rfftfreq(min(len(m), sr * 60), 1 / sr)
            lows.append(spec[fq < 120].sum() / (spec.sum() + 1e-12))
            if not check:
                continue
            heard = binary_closing(heard, np.ones(21, bool)) | heard     # stretched clips skip blocks
            for kind, sev, cause, fix, times, evd in audio_checks(y, sr, "recording", harmonics=harmonics, heard=heard):
                bts = [b for b in (beat_near(beat_of, tm) for tm in times) if b is not None]
                per.setdefault(kind, []).append((sev, cause, fix, bts, evd, path))
        for kind, rows in per.items():
            findings.append(merge_takes(tn, kind, rows))
        info[tn] = dict(peak=best[0] if best[1] is not None else None, beat=best[1],
                        bassy=bool(BASSY.search(tn)) or (not VOCALY.search(tn) and bool(lows) and float(np.median(lows)) > 0.5))
        log(f"  checked {tn}")
    if skipped:
        notes.append("switched-off tracks not checked: " + ", ".join(skipped))
    return findings, info, notes


# ---------------------------------------------------------------- confirmation against stems
def stem_map(paths):
    files = []
    for p in paths or []:
        p = Path(p)
        files += sorted(x for x in p.iterdir() if x.suffix.lower() in AUDIO_EXT) if p.is_dir() else [p]
    return files


def match_stem(name, files):
    low = name.lower()
    for f in files:
        st = f.stem.lower()
        if st == low or re.sub(r"^\d+-", "", st) == low or re.sub(r"^\d+-", "", st) == re.sub(r"^\d+-", "", low):
            if re.sub(r"^\d+-", "", low) in ("audio", "midi", "group") and st != low:
                continue                                    # Live's default names: only an exact match counts
            return f
    return None


def _align(pre, post, sr):
    """Shift post to line up with pre: coarse (10 ms envelopes, +-2 s), then sample-exact around the loudest
    second. Returns (pre, post) trimmed to the same length."""
    n = min(len(pre), len(post))
    pre, post = pre[:n], post[:n]
    e = int(0.01 * sr)
    m = n // e
    sh = 0
    if m > 400:
        a = np.sqrt((pre[: m * e] ** 2).reshape(m, e).mean(1)); b = np.sqrt((post[: m * e] ** 2).reshape(m, e).mean(1))
        a, b = a - a.mean(), b - b.mean()
        cc = [float(np.dot(a[max(0, -L): m - max(0, L)], b[max(0, L): m - max(0, -L)])) for L in range(-200, 201)]
        sh = (int(np.argmax(cc)) - 200) * e
    k = int(np.argmax(np.abs(pre)))
    w = slice(max(0, k - sr // 2), min(n, k + sr // 2))
    r = int(0.012 * sr)
    seg = pre[w]
    best, fine = -np.inf, 0
    if len(seg) > 4 * r:
        for L in range(sh - r, sh + r + 1, 1):
            lo, hi = w.start + L, w.stop + L
            if lo < 0 or hi > n:
                continue
            v = float(np.dot(seg, post[lo:hi]))
            if v > best:
                best, fine = v, L
        sh = fine
    if sh > 0:
        post = post[sh:]; pre = pre[: len(post)]
    elif sh < 0:
        pre = pre[-sh:]; post = post[: len(pre)]
    return pre, post, sh


def compare(pre, post, sr, nfft=4096):
    """How much of the stem (post) in its loud passages is NOT explained by the clip audio (pre) through a
    linear path (EQ, delay, gain riding): new frequency content, i.e. distortion. The linear path H(f) is
    fitted on the quiet passages; each block also gets its own gain (so compression doesn't count).
    Returns dB figures: added = loud-block residual minus quiet-block residual (level-dependent part)."""
    pre, post, sh = _align(np.asarray(pre, float), np.asarray(post, float), sr)
    hop = nfft // 2
    nb = (min(len(pre), len(post)) - nfft) // hop
    if nb < 60:
        return None
    idx = np.arange(nfft)[None, :] + hop * np.arange(nb)[:, None]
    w = np.hanning(nfft)
    A = np.fft.rfft(pre[idx] * w, axis=1); B = np.fft.rfft(post[idx] * w, axis=1)
    fq = np.fft.rfftfreq(nfft, 1 / sr)
    band = (fq >= 80) & (fq <= min(12000, sr / 2 * 0.9))
    A, B = A[:, band], B[:, band]
    pa, pb = (np.abs(A) ** 2).sum(1), (np.abs(B) ** 2).sum(1)
    lv = 10 * np.log10(pa + 1e-20)
    snd = (lv > lv.max() - 40) & (pb > pb.max() * 1e-5)
    if snd.sum() < 40:
        return None
    p30, p60, p85 = np.percentile(lv[snd], [30, 60, 85])
    loud, quiet = snd & (lv >= p85), snd & (lv >= p30) & (lv <= p60)
    if loud.sum() < 10 or quiet.sum() < 10:
        return None
    H = (B[quiet] * np.conj(A[quiet])).sum(0) / ((np.abs(A[quiet]) ** 2).sum(0) + 1e-20)
    Y = A * H
    g = (B * np.conj(Y)).sum(1) / ((np.abs(Y) ** 2).sum(1) + 1e-20)
    res = (np.abs(B - g[:, None] * Y) ** 2).sum(1) / (pb + 1e-20)
    rdb = 10 * np.log10(res + 1e-12)
    added = float(np.median(rdb[loud]) - np.median(rdb[quiet]))
    pk_a = np.abs(pre[idx]).max(1); pk_b = np.abs(post[idx]).max(1)
    crest = lambda pk, p: 20 * np.log10((pk + 1e-12) / np.sqrt(p / (nfft * 0.375) + 1e-20))
    cd = float(np.median(crest(pk_a, pa)[loud]) - np.median(crest(pk_b, pb)[loud]))
    worst = int(np.argmax(np.where(loud, rdb, -np.inf)))
    return dict(added_db=round(added, 2), residual_loud_db=round(float(np.median(rdb[loud])), 1),
                residual_quiet_db=round(float(np.median(rdb[quiet])), 1), crest_loss_db=round(cd, 2),
                flat_pre=len(flat_tops(pre[:, None])), flat_post=len(flat_tops(post[:, None])),
                worst_s=(worst * hop + nfft / 2 + max(0, -sh)) / sr, offset_samples=int(sh))


def measured_fix(chain):
    """Fix for distortion measured in a stem that the chain check didn't predict: the likeliest stock
    culprit gets a specific change, otherwise bypass-and-compare."""
    for d in chain:
        lab = dlabel(d)
        if d.tag == "Saturator":
            p = Param(d, "PreDrive")
            return f"{lab} Drive {p.v:.1f} dB -> {p.v - 6:.1f} dB", [change(lab, p, p.v - 6, f"Drive {p.v:.1f} -> {p.v - 6:.1f} dB")]
        if d.tag == "Compressor2" and pv(d, "Release", 100) < 60 and not pv(d, "AutoReleaseControlOnOff", 0):
            p = Param(d, "Release")
            return (f"{lab} Release {p.v:.0f} ms -> 100 ms (a fast release follows the waveform on sustained notes)",
                    [change(lab, p, 100.0, f"Release {p.v:.0f} -> 100 ms")])
    names = ", ".join(dlabel(d) for d in chain)
    return ("a device in the chain is doing it" + (f" ({names})" if names else "") +
            ": bypass them one at a time and compare, or lower the clip gain before them"), []


def confirm(root, als, tempo, findings, post_files, names, include_off, log=print):
    from hypnomix.session.render import render_track
    spb = 60 / tempo
    added, notes = [], []
    for tn, t in sm.audio_tracks(root, None, include_off):
        if names and not any(n.lower() == tn.lower() or tn.lower().startswith(n.lower()) for n in names):
            continue
        f = match_stem(tn, post_files)
        if f is None:
            continue
        post, sr = sf.read(str(f), always_2d=True, dtype="float64")
        post = post.mean(1)
        warn = []
        pre = render_track(t, als, spb, len(post), sr, None, 0, warn)
        if not np.any(pre):
            continue
        c = compare(pre, post, sr)
        if c is None:
            continue
        mine = [x for x in findings if x.track == tn and x.source == "effects" and x.kind != "stacked"]
        if c["residual_quiet_db"] > -10:
            log(f"  {tn}: {f.name} isn't explained by the clip audio (time/pitch effects?): not compared")
            notes.append(f"{tn}: stem {f.name} can't be compared with the clip audio (its effects change time or "
                         "pitch, or it isn't this track's export)")
            continue
        log(f"  compared {tn} with {f.name}: added {c['added_db']:+.1f} dB, crest loss {c['crest_loss_db']:+.1f} dB, "
            f"flat tops {c['flat_pre']} -> {c['flat_post']}")
        new_flat = c["flat_post"] > c["flat_pre"] + 10
        yes = c["added_db"] >= ADDED_DB or c["crest_loss_db"] >= 4 or new_flat
        for x in mine:
            x.confirmed = bool(yes)
            x.evidence["vs_stem"] = dict(c, stem=f.name)
            if yes:
                x.where = sm.where(c["worst_s"] * tempo / 60)
            elif x.severity != "low":
                x.severity = bump(x.severity, -1); x.cause += " (not measurable in the stem export)"
        if yes and not mine:
            sev = "high" if c["added_db"] >= 15 or c["crest_loss_db"] >= 8 else "medium"
            what = []
            if c["added_db"] >= ADDED_DB:
                what.append(f"in loud passages {c['added_db']:.1f} dB more of the stem is new content (harmonics) "
                            "than in quiet passages")
            if c["crest_loss_db"] >= 4:
                what.append(f"peaks {c['crest_loss_db']:.1f} dB flatter")
            if new_flat:
                what.append(f"{c['flat_post']} flat tops (the clip audio has {c['flat_pre']})")
            chain = [d for d in devices_of(t.find("./DeviceChain/DeviceChain/Devices")) if is_on(d)]
            fix, ch = measured_fix(chain)
            added.append(Finding("effects", "measured", tn, sev,
                                 f"the stem distorts where the clip audio doesn't: {'; '.join(what)}", fix,
                                 where=sm.where(c["worst_s"] * tempo / 60), confirmed=True,
                                 evidence=dict(c, stem=f.name), changes=ch))
        if new_flat and c["added_db"] < ADDED_DB and c["crest_loss_db"] < 4:
            notes.append(f"{tn}: the stem has {c['flat_post']} flat tops the clip audio doesn't: a clipper in the "
                         "chain, or it was exported over 0 dBFS at fixed point (export at 32-bit float to check)")
    return added, notes


# ---------------------------------------------------------------- top level
def scan(als=None, audio=(), *, post=None, mix=None, tracks=None, include_off=False, harmonics=True,
         min_severity="low", log=None):
    """Find distortion. Returns a Report; nothing is written. `post` = stem files/folders (Live's export),
    `mix` = full-mix bounce of this set (true peak + clipping; tied to a Limiter on Main for the fix)."""
    log = log or (lambda *a, **k: None)
    findings, notes = [], []
    rep = Report(findings, notes)
    if als:
        src = Path(als)
        tree = aa.load(src)
        root = tree.getroot()
        tempo = float(root.find(".//Tempo/Manual").get("Value"))
        rep.set_path, rep.tempo, rep.tree = str(src), tempo, tree
        log(f"{src.name}: {tempo:g} BPM. Checking the recordings...")
        rf, info, n1 = recording_findings(root, src.parent, tempo, tracks, include_off, harmonics, log)
        findings += rf; notes += n1
        log("Reading device chains...")
        ef, n2 = effects_findings(root, info, pointees(root), tracks, include_off)
        findings += ef; notes += n2
        pf = stem_map([post] if isinstance(post, (str, Path)) else post)
        if pf:
            log("Comparing clip audio with the stem export...")
            ad, n3 = confirm(root, src, tempo, findings, pf, tracks, include_off, log)
            findings += ad; notes += n3
            mf = match_stem("Main", pf)
            if mf is not None and mix is None:
                mix = mf
        if mix:
            findings += mix_findings(mix, root)
    else:
        if mix:
            findings += mix_findings(mix, None)
    for a in audio or ():
        for f in stem_map([a]):
            y, sr = sf.read(str(f), always_2d=True, dtype="float64")
            log(f"Checking {f.name}...")
            for kind, sev, cause, fix, times, evd in audio_checks(y, sr, "file", harmonics=harmonics):
                findings.append(Finding("file", kind, f.name, sev, cause, fix,
                                        where=mmss(times[0]) if times else "", time_s=times[0] if times else None,
                                        evidence=dict(evd, also_at=[mmss(x) for x in times[1:]])))
    findings[:] = [f for f in findings if SEV[f.severity] >= SEV[min_severity]]
    findings.sort(key=lambda f: (-SEV[f.severity], f.track, f.where))
    return rep


def mix_findings(mix, root):
    y, sr = sf.read(str(mix), always_2d=True, dtype="float64")
    out = []
    lim = None
    if root is not None:
        m = root.find(".//MainTrack")
        if m is None:
            m = root.find(".//MasterTrack")
        devs = [d for d in devices_of(m.find("./DeviceChain/DeviceChain/Devices")) if is_on(d)]
        if devs and devs[-1].tag == "Limiter":
            lim = devs[-1]
    for kind, sev, cause, fix, times, evd in audio_checks(y, sr, "mix", is_mix=True):
        f = Finding("mix", kind, "Main", sev, f"{Path(mix).name}: {cause}", fix,
                    where=mmss(times[0]) if times else "", time_s=times[0] if times else None,
                    evidence=dict(evd, also_at=[mmss(x) for x in times[1:]]))
        if kind == "true-peak" and lim is not None:
            ce = Param(lim, "Ceiling")
            new = round((ce.v - (evd["max_dbtp"] - TP_CEILING)) * 10) / 10
            f.device = dlabel(lim)
            f.fix = f"Main {dlabel(lim)} Ceiling {ce.v:.1f} dB -> {new:.1f} dB, then re-export"
            f.changes = [change(dlabel(lim), ce, new, f"Ceiling {ce.v:.1f} -> {new:.1f} dB")]
        out.append(f)
    return out


def apply(rep, out_path, min_severity="medium"):
    """Write every pure parameter change at min_severity or above to a NEW set. Returns (done, skipped)."""
    if rep.tree is None:
        raise ValueError("no set loaded")
    src = Path(rep.set_path)
    if Path(out_path).resolve().parent != src.resolve().parent:
        raise ValueError(f"write the new set in the same folder as the original ({src.resolve().parent}): "
                         "samples linked by relative path go offline elsewhere")
    pts = pointees(rep.tree.getroot())
    done, skipped, seen = [], [], set()
    for f in rep.findings:
        if SEV[f.severity] < SEV[min_severity]:
            continue
        for c in f.changes:
            el = c["el"]
            if id(el) in seen:
                continue
            seen.add(id(el))
            at = c["pel"].find("./AutomationTarget")
            if at is not None and at.get("Id") in pts:
                skipped.append((f, c, "automated"))
                continue
            el.set("Value", repr(float(c["to"])))
            done.append((f, c))
    if done:
        aa.save(rep.tree, src, out_path)
    return done, skipped


# ---------------------------------------------------------------- CLI
def print_report(rep):
    if rep.set_path:
        print(f"\n{Path(rep.set_path).name}: {len(rep.findings)} findings\n")
    if not rep.findings:
        print("No audible distortion found.")
    for f in rep.findings:
        conf = {True: "  [confirmed in stem]", False: "  [not measurable in stem]"}.get(f.confirmed, "")
        loc = f.where if f.where.count(":") else (f"bar {f.where}" if f.where else "")
        head = f"{f.severity.upper():<6} {f.track}" + (f" / {f.device}" if f.device else "")
        print(f"{head}  {loc}  [{f.source} {f.kind}]{conf}")
        print(f"       cause: {f.cause}")
        also = f.evidence.get("also_at")
        if also:
            print(f"       also at: {', '.join(also)}")
        print(f"       fix:   {f.fix}" + ("  (--apply)" if f.changes else ""))
    for n in rep.notes:
        print(f"note: {n}")


def main():
    ap = argparse.ArgumentParser(prog="hypnomix distortion", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="a .als and/or audio files or folders")
    ap.add_argument("--post", action="append", default=[], help="stem export (folder or files) to confirm effect findings")
    ap.add_argument("--mix", help="full-mix bounce of this set: true peak and clipping")
    ap.add_argument("--track", action="append", default=[], help="only these tracks (repeatable)")
    ap.add_argument("--include-off", action="store_true", help="also check switched-off tracks")
    ap.add_argument("--no-harmonics", action="store_true", help="skip the (slower) harmonic analysis")
    ap.add_argument("--min-severity", choices=list(SEV), default="low", help="hide findings below this")
    ap.add_argument("--json", metavar="OUT.json", help="also write the report as JSON")
    ap.add_argument("--apply", metavar="OUT.als", help="write the parameter fixes to this NEW set")
    ap.add_argument("--apply-severity", choices=list(SEV), default="medium", help="smallest severity --apply fixes")
    a = ap.parse_args()
    als = [x for x in a.inputs if x.lower().endswith(".als")]
    audio = [x for x in a.inputs if not x.lower().endswith(".als")]
    if len(als) > 1:
        sys.exit("give one .als at a time")
    if a.apply and not als:
        sys.exit("--apply needs a .als")
    rep = scan(als[0] if als else None, audio, post=a.post, mix=a.mix, tracks=a.track, include_off=a.include_off,
               harmonics=not a.no_harmonics, min_severity=a.min_severity, log=lambda *x: print(*x, file=sys.stderr))
    print_report(rep)
    if a.json:
        Path(a.json).write_text(json.dumps(rep.to_dict(), indent=2, default=float))
        print(f"→ {a.json}")
    if a.apply:
        try:
            done, skipped = apply(rep, a.apply, a.apply_severity)
        except ValueError as e:
            sys.exit(str(e))
        for f, c, why in skipped:
            print(f"not applied ({why}): {f.track} {c['device']} {c['shown']}")
        if not done:
            print("Nothing to apply (no parameter fixes at that severity).")
            return
        for f, c in done:
            print(f"applied: {f.track} {c['device']} {c['shown']}")
        print(f"{len(done)} parameter changes written to {a.apply}; the original set is untouched.")


if __name__ == "__main__":
    main()
