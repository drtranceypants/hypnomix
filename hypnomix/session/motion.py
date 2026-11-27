#!/usr/bin/env python3
"""Keep repetitive sections alive: proposed effect moves (filter sweeps, reverb and delay throws), as options.

The last step before the final mixdown. Loops that repeat for 16 or 32 bars feel static; a DJ keeps them
moving with effects. This finds the repetitive stretches and offers moves on the effects the set ALREADY has
(sends to your reverb and delay returns, filters on Main or on instruments, filter and reverb macros of your
racks), each with a length and depth you can change. Nothing is applied by default: every move is an option.

Moves (the same kinds a DJ-style producer draws by hand):
  riser   into a section: a filter opens (or a DJ filter sweeps up) and a reverb wash builds over N bars,
          then everything snaps back exactly on the section's first downbeat
  dip     inside a repetitive section: a slow low-pass dip down and back up over N bars
  drift   across a long stretch: the filter wanders slowly (a point every 16 bars), never the same twice
  swell   a reverb send stepped up bar by bar, held to the section's end, then back
  throw   a delay send thrown on the last beat of each phrase on one instrument (or the lead vocal)
  outro   the reverb rises through the last section

Your style: `--learn SET.als …` reads the automation you drew in finished songs (which moves you use, how many
bars they last, how deep they go) into ~/.hypnomix/motion-style.json. Proposals then use your lengths and
depths and put your favourite moves first. Without it, gentle defaults are used and the review says so.

Sections come from a bounce of the mix (`--mix`, the same section finder as `hypnomix sections`, on the set's
tempo); without one, 8-bar blocks are used and the review says so.

Safety: only automates controls that exist in the set; never writes into a stretch where that control already
has automation (your moves are intent); writes a NEW set; `hypnomix check` runs on it.

A HypnoMix Studio session (.ardour, or its folder): the filter sweeps (riser, dip, drift) on the filter plug-ins it already
has, written as plug-in automation into the open session (--engine) or a new snapshot (--apply NEW.ardour); throws
and send swells are left to you there (session/motion_ardour.py).

Usage:
  hypnomix motion --learn EXAMPLE.als [EXAMPLE2.als …]                      # learn your moves
  hypnomix motion SET.als --mix MIX.wav [--plan [SCAN_DIR]] [--json OUT.json]  # proposals (review / fix)
  hypnomix motion SET.als --mix MIX.wav --apply NEW.als --ids motion-2,motion-5 [--tweak "motion-2:bars=8,depth=0.5"]
Fine controls per move (in --tweak, or the review note): bars=N (length), depth=0..1 (share of the control's
range; for sends: dB=N), every=N (throws: one per N bars), track=NAME (move it to another track that has the
same kind of control).
"""
import argparse, gzip, json, math, re, sys
from hypnomix.core.gz import read_gz
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

BPB = 4
v = lambda n, p: (n.find(p).get("Value") if n.find(p) is not None else None)
STYLE = Path.home() / ".hypnomix" / "motion-style.json"
DEFAULTS = {  # used when nothing was learned: gentle
    "riser": dict(bars=8, depth=0.4), "dip": dict(bars=8, depth=0.45), "drift": dict(bars=64, depth=0.3),
    "swell": dict(bars=4, dB=4.0), "throw": dict(bars=1, dB=10.0, every=8), "outro": dict(bars=16, dB=6.0),
}
REVERB_DEV = ("Reverb", "Hybrid", "Convolution", "Tail", "Aurora")
DELAY_DEV = ("Delay", "Echo", "FilterDelay", "PingPongDelay", "Cascadia")
FILTER_MACRO = re.compile(r"filter|cutoff|hi ?pass|lo ?pass|low ?pass|high ?pass", re.I)
REVERB_MACRO = re.compile(r"reverb amount|reverb$|verb|dry ?/ ?wet", re.I)   # only in racks named DJ


# ---------------------------------------------------------------- what the set can move
def dev_name(d):
    return v(d, "./UserName") or d.tag


def param_range(p):
    mr = p.find("./MidiControllerRange")
    if mr is None:
        return 0.0, 1.0
    a, b = float(v(mr, "./Min")), float(v(mr, "./Max"))
    return min(a, b), max(a, b)


def target(track, label, p, kind, scale):
    lo, hi = param_range(p)
    at = p.find("./AutomationTarget")
    return dict(track=track, label=label, el=p, pid=at.get("Id"), kind=kind, scale=scale, lo=lo, hi=hi,
                base=float(v(p, "./Manual")))


def track_targets(t, returns):
    """Movable controls on one track: filters, sends to reverb / delay returns, DJ rack macros."""
    out = []
    name = "Main" if t.tag in ("MainTrack", "MasterTrack") else v(t, "./Name/EffectiveName")
    sends = t.findall("./DeviceChain/Mixer/Sends/TrackSendHolder/Send")
    for i, s in enumerate(sends):
        if i < len(returns) and returns[i]["kind"] and s.find("./AutomationTarget") is not None:
            for k in returns[i]["kind"].split("+"):      # a reverb-delay return serves both kinds of move
                out.append(target(name, f"Send {chr(65 + i)} ({returns[i]['name']})", s, k + "-send", "send"))
    devs = t.find("./DeviceChain/DeviceChain/Devices")
    for d in (devs.iter() if devs is not None else []):
        if d.tag == "AutoFilter2":
            dj = d.find("./Filter_DjControl")
            if dj is not None and dj.find("./AutomationTarget") is not None and "dj" in dev_name(d).lower():
                out.append(target(name, f"{dev_name(d)} / DJ filter", dj, "filter", "dj"))
            elif d.find("./Filter_Frequency") is not None:
                out.append(target(name, f"{dev_name(d)} / Frequency", d.find("./Filter_Frequency"), "filter", "log"))
        elif d.tag == "AutoFilter" and d.find("./Cutoff") is not None:
            out.append(target(name, f"{dev_name(d)} / Cutoff", d.find("./Cutoff"), "filter", "lin"))
        elif d.tag.endswith("GroupDevice"):
            for i in range(16):
                m, nm = d.find(f"./MacroControls.{i}"), v(d, f"./MacroDisplayNames.{i}") or ""
                if m is None or m.find("./AutomationTarget") is None or nm.startswith("Macro "):
                    continue
                if FILTER_MACRO.search(nm):
                    out.append(target(name, f"{dev_name(d)} / {nm}", m, "filter", "lin"))
                elif REVERB_MACRO.search(nm) and "dj" in dev_name(d).lower():
                    out.append(target(name, f"{dev_name(d)} / {nm}", m, "reverb-macro", "lin"))
    return out


def set_targets(root):
    returns = []
    for t in root.find(".//Tracks"):
        if t.tag != "ReturnTrack":
            continue
        tags = " ".join(dev_name(d) + " " + d.tag for d in t.find("./DeviceChain/DeviceChain/Devices"))
        tags += " " + (v(t, "./Name/EffectiveName") or "")
        kinds = [k for k, devs in (("delay", DELAY_DEV), ("reverb", REVERB_DEV)) if any(x in tags for x in devs)]
        returns.append(dict(name=v(t, "./Name/EffectiveName"), kind="+".join(kinds) or None, el=t))
    tracks = [t for t in root.find(".//Tracks") if t.tag in ("AudioTrack", "MidiTrack", "GroupTrack")]
    main = root.find(".//MainTrack")
    if main is None:
        main = root.find(".//MasterTrack")
    out = {}
    for r in returns:
        if r["kind"] and "reverb" in r["kind"]:
            vol = r["el"].find("./DeviceChain/Mixer/Volume")
            tg = target(r["name"], f"{r['name']} / return level", vol, "reverb-return", "send")
            out[r["name"]] = dict(el=r["el"], on=True, targets=[tg], is_return=True)
    for t in tracks + [main]:
        nm = "Main" if t is main else v(t, "./Name/EffectiveName")
        out[nm] = dict(el=t, on=v(t, "./DeviceChain/Mixer/Speaker/Manual") != "false",
                       targets=track_targets(t, returns if t is not main else []))
    return out, returns


def automated_span(root, t_el, pid):
    """Beats (lo, hi) of existing automation on this control, or None."""
    for env in t_el.findall("./AutomationEnvelopes/Envelopes/AutomationEnvelope"):
        if v(env, "./EnvelopeTarget/PointeeId") == pid:
            ts = [float(e.get("Time")) for e in env.findall(".//Events/*") if float(e.get("Time", "-1e9")) > -1e6]
            return (min(ts), max(ts)) if ts else None
    return None


MAIN_LANE = ("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events/AudioClip",
             "./DeviceChain/MainSequencer/ClipTimeable/ArrangerAutomation/Events/MidiClip")


def activity(t_el, tempo, nbars):
    """Bars (1-based) where this track has an enabled clip on its main lane (comp take lanes don't play)."""
    on = np.zeros(nbars + 2, bool)
    for c in [c for path in MAIN_LANE for c in t_el.findall(path)]:
        if c.find("./CurrentStart") is None or v(c, "./Disabled") == "true":
            continue
        a, b = float(v(c, "./CurrentStart")), float(v(c, "./CurrentEnd"))
        on[max(1, int(a // BPB) + 1):min(nbars + 1, int(math.ceil(b / BPB)) + 1)] = True
    return on


# ---------------------------------------------------------------- values
def to_value(tg, frac):
    """A position 0..1 in the control's range -> its value (log for frequencies)."""
    lo, hi = tg["lo"], tg["hi"]
    if tg["scale"] == "log":
        return float(math.exp(math.log(max(lo, 1e-3)) + frac * (math.log(hi) - math.log(max(lo, 1e-3)))))
    return lo + frac * (hi - lo)


def to_frac(tg, val):
    lo, hi = tg["lo"], tg["hi"]
    if tg["scale"] == "log":
        return (math.log(max(val, 1e-3)) - math.log(max(lo, 1e-3))) / (math.log(hi) - math.log(max(lo, 1e-3)))
    return (val - lo) / (hi - lo) if hi > lo else 0.0


def send_db(tg, base, d_db):
    """base raised by d_db; a send that is off or very low starts from -20 dB, so the move is audible."""
    return float(min(tg["hi"], max(tg["lo"], max(base, 10 ** (-20 / 20)) * 10 ** (d_db / 20))))


# ---------------------------------------------------------------- the moves (pure: points in beats)
def points(move, tg, a, b, p):
    """[(beat, value)] for one move between beats a and b (b = the section boundary for risers)."""
    base = tg["base"]
    eps = 1 / 64
    if move == "riser":
        L = p["bars"] * BPB
        if tg["scale"] == "dj":                       # DJ filter: sweep the high-pass up, snap back on the one
            return [(b - L, base), (b - eps, min(1.0, base + p["depth"])), (b, base)]
        if tg["kind"] == "filter":                    # low-pass: start closed, open up to where it sits
            f0 = max(0.0, to_frac(tg, base) - p["depth"])
            return [(b - L, to_value(tg, f0)), (b - eps, base), (b, base)]
        return [(b - L, base), (b - eps, send_db(tg, base, p.get("dB", 8.0))), (b, base)]   # reverb wash
    if move == "dip":
        L = p["bars"] * BPB
        s = a + max(0.0, ((b - a) - L) / 2) // BPB * BPB
        if tg["scale"] == "dj":
            low = max(-1.0, base - p["depth"])
        else:
            low = to_value(tg, max(0.0, to_frac(tg, base) - p["depth"]))
        return [(s, base), (s + 0.4 * L, low), (s + 0.6 * L, low), (s + L, base)]
    if move == "drift":
        shape = [0.0, 0.55, 0.2, 0.85, 0.35, 0.65, 0.1, 0.0]
        step = 16 * BPB
        n = max(2, int((b - a) // step) + 1)
        out = []
        for i in range(n):
            f = shape[i % len(shape)] if i < n - 1 else 0.0
            x = base - f * p["depth"] if tg["scale"] == "dj" else to_value(tg, max(0.0, to_frac(tg, base) - f * p["depth"]))
            out.append((a + i * step, x))
        return out
    if move == "swell":                               # bar-by-bar steps through the second half, back at the end
        steps = int(max(1, min(p["bars"], (b - a) // BPB // 2)))
        s0 = b - (steps + 1) * BPB
        out, prev = [(s0, base)], base
        for i in range(1, steps + 1):
            nxt = send_db(tg, base, p["dB"] * i / steps)
            out += [(s0 + i * BPB - eps, prev), (s0 + i * BPB, nxt)]
            prev = nxt
        return out + [(b - eps, prev), (b, base)]
    if move == "throw":
        out, every = [], int(p.get("every", 8)) * BPB
        t = a + every
        while t <= b + 1e-6:
            hi = send_db(tg, base, p["dB"])
            out += [(t - 1 - eps, base), (t - 1, hi), (t - eps, hi), (t, base)]     # the phrase's last beat
            t += every
        return out
    if move == "gate":
        return gate_points(tg, a, b, p)
    if move == "dropout":
        return dropout_points(tg, a, b, p)
    if move == "outro":
        return [(a, base), (b, send_db(tg, base, p["dB"]) if tg["scale"] == "send" else
                            to_value(tg, min(1.0, to_frac(tg, base) + p.get("depth", 0.5))))]
    raise ValueError(move)


# ---------------------------------------------------------------- transitions: stutter, gate, drop-out
DRUMS = re.compile(r"drum|kit|perc|kick|snare|hat|loop|beat", re.I)
BASS = re.compile(r"bass|sub|808", re.I)
MELODIC = re.compile(r"key|piano|guitar|gtr|synth|pad|chord|organ|pluck|lead|arp|string", re.I)
GATES = {"16ths": [1, 0] * 8, "8ths": [1, 1, 0, 0] * 4, "dotted": [1, 0, 0] * 5 + [1], "triplet-ish": [1, 1, 0] * 5 + [1]}


def lane(t_el):
    path = MAIN_LANE[0] if t_el.tag == "AudioTrack" else MAIN_LANE[1]
    return t_el.find(path.rsplit("/", 1)[0]), path.rsplit("/", 1)[1]


def role_of(nm, info, labels):
    lab = (labels or {}).get(nm, "")
    if lab:
        return "drums" if re.match(r"(Drums|Kick|Snare|Hats|Perc)", lab) else "bass" if lab.startswith("Bass") else \
            "melodic" if re.match(r"(Keys|Guitar|Synth|Pad|Piano|Organ|Strings|Lead\b|Pluck)", lab) else \
            "vocal" if re.match(r"(Lead Vocal|Harmony|Vocal)", lab) else ""
    if any(d.tag == "DrumGroupDevice" for d in info["el"].iter()) or DRUMS.search(nm):
        return "drums"
    return "bass" if BASS.search(nm) else "melodic" if MELODIC.search(nm) else ""


def volume_target(nm, info):
    vol = info["el"].find("./DeviceChain/Mixer/Volume")
    return target(nm, "Volume", vol, "volume", "send")


def gate_points(tg, a, b, p):
    """A rhythmic chop over the last `bars` bars before b: on/off steps from a pattern (16 per bar)."""
    pat = GATES.get(str(p.get("pattern", "16ths")), GATES["16ths"])
    low = tg["base"] * 10 ** (-abs(p.get("dB", 24.0)) / 20)
    eps, step = 1 / 64, BPB / 16
    s0 = b - p.get("bars", 1) * BPB
    out, prev, t = [(s0, tg["base"])], tg["base"], s0
    k = 0
    while t < b - 1e-9:
        val = tg["base"] if pat[k % len(pat)] else low
        if val != prev:
            out += [(t - eps, prev), (t, val)]
            prev = val
        t += step; k += 1
    return out + [(b - eps, prev), (b, tg["base"])]


def dropout_points(tg, a, b, p):
    beats = p.get("beats", 1.0)
    eps = 1 / 64
    return [(b - beats - eps, tg["base"]), (b - beats, tg["lo"]), (b - eps, tg["lo"]), (b, tg["base"])]


def content_at(c, x):
    """Clip-content beat that plays at arrangement beat x (start marker, loop wrap)."""
    cs = float(v(c, "./CurrentStart"))
    ls, le = float(v(c, "./Loop/LoopStart")), float(v(c, "./Loop/LoopEnd"))
    rel = float(v(c, "./Loop/StartRelative") or 0)
    if v(c, "./Loop/LoopOn") == "true":
        L = max(1e-6, le - ls)
        return ls + ((rel + (x - cs)) % L)
    return ls + (x - cs)


def set_loop(c, start, end, on=False, rel=0.0):
    lp = c.find("./Loop")
    for tag, val in (("LoopStart", start), ("LoopEnd", end), ("StartRelative", rel), ("OutMarker", end),
                     ("HiddenLoopStart", start), ("HiddenLoopEnd", end)):
        if lp.find(f"./{tag}") is not None:
            lp.find(f"./{tag}").set("Value", repr(float(start if tag == "HiddenLoopStart" else val)))
    lp.find("./LoopOn").set("Value", "true" if on else "false")


def stutter(t_el, b, p):
    """Replace the last `beats` beats before b with a roll: the slice at its start repeated in 1/8s, then 1/16s.
    The clip before and after plays exactly as it did. Returns an error string or None."""
    import copy
    if t_el.tag == "AudioTrack" and t_el.findall(".//TakeLanes//AudioClip"):
        return "comped from take lanes (would lose the takes): do it by hand"
    parent, tag = lane(t_el)
    beats = float(p.get("beats", 2.0))
    t0 = b - beats
    c = next((x for x in parent.findall(tag) if v(x, "./Disabled") != "true"
              and float(v(x, "./CurrentStart")) <= t0 + 1e-6 and float(v(x, "./CurrentEnd")) >= b - 1e-6), None)
    if c is None:
        return "no single clip plays through those beats"
    if tag == "AudioClip" and v(c, "./IsWarped") != "true":
        return "the clip isn't warped (its slices wouldn't stay in time)"
    cs, ce = float(v(c, "./CurrentStart")), float(v(c, "./CurrentEnd"))
    src = content_at(c, t0)
    plan = [(t0 + k * 0.5, 0.5) for k in range(int(beats - 1) * 2)] + [(b - 1 + k * 0.25, 0.25) for k in range(4)]
    ids = [int(x.get("Id")) for x in parent.findall(tag)]
    nid = max(ids) + 1
    pieces = []
    if t0 - cs > 1e-6:
        head = copy.deepcopy(c); head.find("./CurrentEnd").set("Value", repr(t0)); pieces.append(head)
    for st, ln in plan:
        sl = copy.deepcopy(c); sl.set("Id", str(nid)); nid += 1
        sl.find("./CurrentStart").set("Value", repr(st)); sl.find("./CurrentEnd").set("Value", repr(st + ln))
        sl.set("Time", repr(float(st)))
        set_loop(sl, src, src + ln, on=False)
        f = sl.find("./Fades")
        if f is not None:                                   # tiny fades: no clicks at the cuts
            for k_, val in (("FadeInLength", 0.01), ("FadeOutLength", min(0.03, ln / 4)),
                            ("IsDefaultFadeIn", "false"), ("IsDefaultFadeOut", "false")):
                if f.find(f"./{k_}") is not None:
                    f.find(f"./{k_}").set("Value", val if isinstance(val, str) else repr(val))
        nm = sl.find("./Name")
        if nm is not None:
            nm.set("Value", (nm.get("Value") or "") + " (stutter)")
        pieces.append(sl)
    if ce - b > 1e-6:
        tail = copy.deepcopy(c); tail.set("Id", str(nid))
        tail.find("./CurrentStart").set("Value", repr(b)); tail.set("Time", repr(float(b)))
        if v(c, "./Loop/LoopOn") == "true":
            ls, le = float(v(c, "./Loop/LoopStart")), float(v(c, "./Loop/LoopEnd"))
            rel = (float(v(c, "./Loop/StartRelative") or 0) + (b - cs)) % max(1e-6, le - ls)
            tail.find("./Loop/StartRelative").set("Value", repr(rel))
        else:
            ls_new = content_at(c, b)
            tail.find("./Loop/LoopStart").set("Value", repr(ls_new))
            if tail.find("./Loop/HiddenLoopStart") is not None:
                tail.find("./Loop/HiddenLoopStart").set("Value", repr(ls_new))
        pieces.append(tail)
    idx = list(parent).index(c)
    parent.remove(c)
    for k_, pc in enumerate(pieces):
        parent.insert(idx + k_, pc)
    return None


# ---------------------------------------------------------------- your style
def segments(pts, lo, hi):
    """Split an envelope wherever it comes back to rest (its first value): one move per segment."""
    pts = sorted((t, x) for t, x in pts if t > -1e6)
    if len(pts) < 3:
        return [pts]
    rng = (hi - lo) or 1.0
    rest = pts[0][1]
    at_rest = [abs(x - rest) < 0.05 * rng for _, x in pts]
    out, start = [], 0
    for i in range(1, len(pts)):
        if at_rest[i] and not at_rest[i - 1] and (i + 1 == len(pts) or at_rest[i + 1]):   # came back and stayed
            seg = pts[start:i + 1]
            j = max(k for k in range(start, i) if at_rest[k]) if any(at_rest[start:i]) else start
            out.append(pts[j:i + 1] if len(pts[j:i + 1]) >= 2 else seg)
            start = i
    if start < len(pts) - 1:
        tail = pts[start:]
        while len(tail) > 2 and abs(tail[1][1] - rest) < 0.05 * rng:   # skip a held rest at the start only
            tail = tail[1:]
        out.append(tail)
    return [sg for sg in out if len(sg) >= 2]


def classify_envelope(pts, lo, hi, song_beats):
    """Which move a drawn envelope (or one segment of it) is: length (bars) and depth (share of range)."""
    pts = sorted((t, x) for t, x in pts if t > -1e6)
    if len(pts) < 2:
        return None
    rng = (hi - lo) or 1.0
    if lo < 0 < hi:
        rng = max(-lo, hi)              # a bipolar control (DJ filter): depth is a share of one side
    vals = np.array([x for _, x in pts]); ts = np.array([t for t, _ in pts])
    span_bars = (ts[-1] - ts[0]) / BPB
    depth = float((vals.max() - vals.min()) / rng)
    if depth < 0.03:
        return None
    for i in range(1, len(pts)):                     # a snap back (within 2 beats) right after a build: riser
        if ts[i] - ts[i - 1] <= 2.0 and abs(vals[i] - vals[0]) < 0.1 * rng and abs(vals[i - 1] - vals[0]) > 0.15 * rng:
            j = i - 1
            while j > 0 and (vals[j - 1] - vals[0]) * (vals[i - 1] - vals[0]) >= 0 and abs(vals[j - 1] - vals[0]) < abs(vals[j] - vals[0]) + 1e-9:
                j -= 1
            return dict(move="riser", bars=round(max(1.0, (ts[i - 1] - ts[j]) / BPB), 1), depth=round(abs(vals[i - 1] - vals[0]) / rng, 2))
    steps = sum(1 for i in range(1, len(pts)) if abs(ts[i] - ts[i - 1]) < 0.01 and abs(vals[i] - vals[i - 1]) > 0.02 * rng)
    if steps >= 3:
        return dict(move="swell", bars=round(span_bars, 1), depth=round(depth, 2))
    if len(pts) >= 4 and span_bars >= 32:
        return dict(move="drift", bars=round(span_bars, 1), depth=round(depth, 2))
    mid = vals[1:-1]
    if len(mid) and abs(vals[-1] - vals[0]) < 0.1 * rng and (np.abs(mid - vals[0]) > 0.15 * rng).any():
        down = (mid - vals[0]).min() < -(mid - vals[0]).max()
        return dict(move="dip" if down else "swell", bars=round(span_bars, 1), depth=round(depth, 2))
    if ts[-1] > 0.85 * song_beats and vals[-1] > vals[0]:
        return dict(move="outro", bars=round(span_bars, 1), depth=round(depth, 2))
    return dict(move="ramp", bars=round(span_bars, 1), depth=round(depth, 2))


def learn(paths):
    found = []
    for path in paths:
        root = ET.fromstring(read_gz(path))
        song = max([float(v(c, "./CurrentEnd")) for t in root.find(".//Tracks") for path in MAIN_LANE
                    for c in t.findall(path) if v(t, "./DeviceChain/Mixer/Speaker/Manual") != "false"
                    and v(c, "./Disabled") != "true"] + [1.0])
        tg_all, _ = set_targets(root)
        for nm, info in tg_all.items():
            by_pid = {tg["pid"]: tg for tg in info["targets"]}
            for env in info["el"].findall("./AutomationEnvelopes/Envelopes/AutomationEnvelope"):
                tg = by_pid.get(v(env, "./EnvelopeTarget/PointeeId"))
                if tg is None:
                    continue
                pts = [(float(e.get("Time")), float(e.get("Value"))) for e in env.findall(".//Events/FloatEvent")]
                for seg in segments(pts, tg["lo"], tg["hi"]):
                    c = classify_envelope(seg, tg["lo"], tg["hi"], song)
                    if c:
                        found.append(dict(c, target=tg["kind"], on_main=nm == "Main", song=Path(path).stem,
                                          bar=round(seg[0][0] / BPB + 1, 1)))
        for t in root.find(".//Tracks"):           # the reverb / delay returns' own level (a section swell)
            if t.tag != "ReturnTrack":
                continue
            vol = t.find("./DeviceChain/Mixer/Volume")
            pid = vol.find("./AutomationTarget").get("Id")
            for env in t.findall("./AutomationEnvelopes/Envelopes/AutomationEnvelope"):
                if v(env, "./EnvelopeTarget/PointeeId") != pid:
                    continue
                pts = [(float(e.get("Time")), float(e.get("Value"))) for e in env.findall(".//Events/FloatEvent")]
                for seg in segments(pts, 0.0, 2.0):
                    c = classify_envelope(seg, 0.0, 2.0, song)
                    if c:
                        found.append(dict(c, target="return-level", on_main=False, song=Path(path).stem,
                                          bar=round(seg[0][0] / BPB + 1, 1)))
    style = {"examples": found, "moves": {}}
    for mv in DEFAULTS:
        xs = [f for f in found if f["move"] == mv]
        if xs:
            style["moves"][mv] = dict(count=len(xs), bars=float(np.median([f["bars"] for f in xs])),
                                      depth=float(np.median([f["depth"] for f in xs])),
                                      on_main=sum(f["on_main"] for f in xs))
    return style


def params_for(move, style):
    p = dict(DEFAULTS[move])
    m = (style or {}).get("moves", {}).get(move)
    if m:
        if move in ("riser", "dip", "outro"):
            p["bars"] = int(min(16, max(2, round(m["bars"])))) if move != "outro" else int(max(4, round(m["bars"])))
        if move in ("riser", "dip", "drift"):
            p["depth"] = float(min(0.9, max(0.1, m["depth"])))
    return p


# ---------------------------------------------------------------- sections
def sections_from(mix, tempo, nbars):
    if mix:
        from hypnomix.ears import sections as S
        r = S.analyse(mix, bpm=tempo)
        bar_s = BPB * 60 / tempo
        out = []
        for s in r["sections"]:
            a, b = int(round(s["start"] / bar_s)) + 1, int(round(s["end"] / bar_s)) + 1
            if b - a >= 4:
                out.append(dict(a=a, b=b, label=s["label"], repeat=s["repeat"], role=s.get("role", ""), lufs=s.get("lufs")))
        return out, "from the mix"
    return ([dict(a=a, b=min(nbars + 1, a + 8), label="?", repeat=1, role="") for a in range(1, nbars + 1, 8)],
            "8-bar blocks (no --mix: give a bounce for real sections)")


# ---------------------------------------------------------------- proposals
def propose(root, mix=None, style=None, labels=None):
    tempo = float(root.find(".//Tempo/Manual").get("Value"))
    ends = [float(v(c, "./CurrentEnd")) for c in list(root.iter("AudioClip")) + list(root.iter("MidiClip"))
            if c.find("./CurrentEnd") is not None]
    nbars = int(math.ceil(max(ends + [BPB]) / BPB))
    secs, how = sections_from(mix, tempo, nbars)
    T, returns = set_targets(root)
    act = {nm: (np.ones(nbars + 2, bool) if info.get("is_return") else activity(info["el"], tempo, nbars))
           for nm, info in T.items() if nm != "Main"}
    for nm, info in T.items():                     # a group plays where any of its tracks plays
        if nm != "Main" and info["el"].tag == "GroupTrack":
            gid = info["el"].get("Id")
            for nm2, i2 in T.items():
                if nm2 != "Main" and not i2.get("is_return") and v(i2["el"], "./TrackGroupId") == gid:
                    act[nm] = act[nm] | act[nm2]
    plays = lambda nm, a, b: nm == "Main" or (T[nm]["on"] and act[nm][a:b].mean() > 0.6)
    learned = bool(style and style.get("moves"))
    fav = sorted(DEFAULTS, key=lambda m: -((style or {}).get("moves", {}).get(m, {}).get("count", 0)))
    out = []

    def free(tg, a_beat, b_beat):
        span = automated_span(root, T[tg["track"]]["el"], tg["pid"])
        return span is None or span[1] < a_beat - BPB or span[0] > b_beat + BPB

    def pick(kinds, a, b, prefer_main=False, avoid=()):
        cands = []
        for nm, info in T.items():
            if nm in avoid or not plays(nm, a, b):
                continue
            for tg in info["targets"]:
                if tg["kind"] in kinds and free(tg, (a - 1) * BPB, (b - 1) * BPB):
                    cands.append(tg)
        cands.sort(key=lambda tg: (0 if (tg["track"] == "Main") == prefer_main else 1, tg["track"]))
        return cands

    def add(move, tg, a, b, why, alts):
        p = params_for(move, style)
        out.append(dict(move=move, tg=tg, a=a, b=b, p=p, why=why, alts=[x["track"] + ": " + x["label"] for x in alts[:4]]))

    used = set()
    for i, s in enumerate(secs):
        repetitive = s["repeat"] >= 2 or (s["b"] - s["a"]) >= 12     # a repeat, or loops going round for 12+ bars
        nxt = secs[i + 1] if i + 1 < len(secs) else None
        lifts = nxt is not None and s.get("lufs") is not None and nxt.get("lufs") is not None and nxt["lufs"] - s["lufs"] >= 1.5
        # riser into a big, repeated or louder section
        if nxt and (nxt["role"] == "chorus-like" or nxt["repeat"] >= 2 or lifts):
            L = params_for("riser", style)["bars"]
            a0 = max(s["a"], nxt["a"] - L)
            c = pick(("filter",), a0, nxt["a"], prefer_main=bool((style or {}).get("moves", {}).get("riser", {}).get("on_main")))
            if c:
                add("riser", c[0], a0, nxt["a"], f"into the {nxt['label']} section at bar {nxt['a']}", c[1:])
        if not repetitive:
            continue
        what = f"{'repeat ' + str(s['repeat']) + ' of ' if s['repeat'] >= 2 else ''}section {s['label']} (bars {s['a']}–{s['b'] - 1})"
        c = [tg for tg in pick(("filter",), s["a"], s["b"]) if tg["track"] != "Main" and (tg["track"], "dip") not in used]
        if c and (s["b"] - s["a"]) >= 8:
            add("dip", c[0], s["a"], s["b"], f"{what}: the same loop again, a slow low-pass dip moves it", c[1:])
            used.add((c[0]["track"], "dip"))
        c = pick(("delay-send",), s["a"], s["b"], avoid=("Main",))
        vox = [tg for tg in c if re.search(r"lead|vocal|vox", tg["track"], re.I)]
        c = vox + [tg for tg in c if tg not in vox]
        if c:
            add("throw", c[0], s["a"], s["b"], f"{what}: delay throws at the phrase ends", c[1:])
        c = [tg for tg in pick(("reverb-return", "reverb-send"), s["a"], s["b"], avoid=("Main",))
             if tg["kind"] == "reverb-return" or (tg["track"], "swell") not in used]
        c.sort(key=lambda tg: 0 if tg["kind"] == "reverb-return" else 1)
        if c and (s["b"] - s["a"]) >= 8:
            add("swell", c[0], s["a"], s["b"], f"{what}: a reverb swell lifts the second half", c[1:])
            used.add((c[0]["track"], "swell"))
    # transitions (into each section) and turnarounds (the end of each 8-bar phrase inside long sections)
    roles = {nm: role_of(nm, info, labels) for nm, info in T.items() if nm != "Main" and not info.get("is_return")}
    def vol_free(nm, a_b, b_b):
        tg = volume_target(nm, T[nm])
        span = automated_span(root, T[nm]["el"], tg["pid"])
        return tg if span is None or span[1] < a_b - BPB or span[0] > b_b + BPB else None

    def first_of(role, a, b):
        for nm, r in roles.items():
            if r == role and plays(nm, a, b):
                yield nm

    spots = []
    for i, s in enumerate(secs[1:], 1):
        spots.append(("transition", s["a"], secs[i - 1], s))
    for s in secs:
        for bar in range(s["a"] + 8, s["b"] - 3, 8):
            spots.append(("turnaround", bar, s, s))
    cycle = ["stutter", "gate", "dropout"]
    for k, (kind, bar, before, after) in enumerate(sorted(spots, key=lambda x: x[1])):
        b_beat = (bar - 1) * BPB
        choices = [cycle[k % 3]] if kind == "turnaround" else ["stutter", "dropout", "gate"]
        for mv in choices:
            if mv == "stutter":
                nm = next((x for x in first_of("drums", bar - 1, bar)), None)
                if nm:
                    out.append(dict(move="stutter", tg=dict(track=nm, label="clips", pid="", kind="clips", scale=""),
                                    a=bar - 1, b=bar, p=dict(beats=2.0),
                                    why=f"{kind} into bar {bar}: a drum roll (the last 2 beats re-triggered, 1/8 then 1/16)",
                                    alts=[]))
            elif mv == "dropout" and (kind == "transition" or k % 2 == 0):
                for role in ("drums", "bass"):
                    nm = next((x for x in first_of(role, bar - 1, bar)), None)
                    tg = vol_free(nm, b_beat - BPB, b_beat) if nm else None
                    if tg:
                        out.append(dict(move="dropout", tg=tg, a=bar - 1, b=bar, p=dict(beats=1.0),
                                        why=f"{kind} into bar {bar}: {role} drop out for the last beat, then hit the one",
                                        alts=[]))
            elif mv == "gate":
                nm = next((x for x in first_of("melodic", bar - 1, bar)), None)
                tg = vol_free(nm, b_beat - BPB, b_beat) if nm else None
                if tg:
                    out.append(dict(move="gate", tg=tg, a=bar - 1, b=bar, p=dict(bars=1, pattern="16ths", dB=24.0),
                                    why=f"{kind} into bar {bar}: a rhythmic gate chop on {nm} for the last bar",
                                    alts=[]))
    long = [s for s in secs if (s["b"] - s["a"]) >= 32]
    for s in long[:2]:
        c = [tg for tg in pick(("filter",), s["a"], s["b"]) if tg["track"] != "Main"]
        if c:
            add("drift", c[0], s["a"], s["b"], f"bars {s['a']}–{s['b'] - 1}: {s['b'] - s['a']} bars without a change; "
                                               "a slow filter drift keeps it moving", c[1:])
    if secs:
        last = secs[-1]
        c = pick(("reverb-macro", "reverb-return", "reverb-send"), last["a"], last["b"], prefer_main=True)
        order_ = {"reverb-macro": 0, "reverb-return": 1, "reverb-send": 2}
        c.sort(key=lambda tg: order_[tg["kind"]])
        if c:
            add("outro", c[0], last["a"], last["b"], f"the last section (bars {last['a']}–{last['b'] - 1})", c[1:])
    rank = {m: i for i, m in enumerate(fav + ["stutter", "dropout", "gate"])}
    out.sort(key=lambda m: (m["a"], rank.get(m["move"], 99)))
    return out, dict(tempo=tempo, sections=secs, how=how, learned=learned, nbars=nbars,
                     returns=[r for r in returns if r["kind"]])


WORDS = {"riser": "riser", "dip": "low-pass dip", "drift": "slow filter drift", "swell": "reverb swell",
         "throw": "delay throws", "outro": "outro reverb rise", "stutter": "stutter roll", "gate": "gate chop",
         "dropout": "drop-out"}


def describe(m):
    p = m["p"]
    if m["move"] == "stutter":
        return f"stutter roll on {m['tg']['track']}: the last {p['beats']:g} beats re-trigger (1/8s, then 1/16s)"
    if m["move"] == "gate":
        return f"gate chop on {m['tg']['track']} (volume): {p['pattern']} for {p['bars']:g} bar, off = -{p['dB']:g} dB"
    if m["move"] == "dropout":
        return f"drop-out on {m['tg']['track']} (volume): silent for the last {p['beats']:g} beat"
    if m["move"] in ("swell", "throw", "outro") and m["tg"]["scale"] == "send":
        size = f"+{p['dB']:g} dB on the send" + (f", one every {p['every']} bars" if m["move"] == "throw" else "")
    else:
        size = f"depth {p.get('depth', 0.5):.0%} of the control's range"
    length = "" if m["move"] in ("throw", "outro", "drift") else f"{p['bars']} bars, "
    return f"{WORDS[m['move']]} on {m['tg']['track']} ({m['tg']['label']}): {length}{size}"


def findings(moves, meta):
    out = []
    for n, m in enumerate(moves, 1):
        opts = {"stutter": "beats=1|2|4", "gate": "bars=1|2, pattern=16ths|8ths|dotted|triplet-ish, dB=N",
                "dropout": "beats=0.5|1|2"}.get(m["move"])
        if opts is None:
            opts = "bars=N, " + ("dB=N" if m["tg"]["scale"] == "send" else "depth=0.1–0.9") + \
                   (", every=N" if m["move"] == "throw" else "")
        opts = "change it in the note: " + opts + (f"; or another track: {'; '.join(m['alts'])}" if m["alts"] else "")
        out.append(dict(id=f"motion-{n}", tool="motion", kind=f"motion-{m['move']}", severity="low",
                        track=m["tg"]["track"],
                        where=(f"end of bar {m['a']}" if m["move"] in ("stutter", "gate", "dropout") else f"bars {m['a']}–{m['b'] - 1}"),
                        problem=m["why"] + ("" if meta["learned"] else " (gentle defaults: `hypnomix motion --learn` "
                                                                       "your finished songs to use your own moves)"),
                        fix=f"{describe(m)}. An option, not a fix: {opts}",
                        applies="set", move=dict(move=m["move"], track=m["tg"]["track"], pid=m["tg"]["pid"],
                                                 label=m["tg"]["label"], a=m["a"], b=m["b"], p=m["p"])))
    return out


# ---------------------------------------------------------------- writing
def next_id(root):
    return max(int(e.get("Id")) for e in root.iter() if (e.get("Id") or "").isdigit()) + 1


def write_move(root, T, mv):
    info = T.get(mv["track"])
    if info is None:
        return f"{mv['track']}: track not found"
    if mv["move"] == "stutter":
        return stutter(info["el"], (mv["b"] - 1) * BPB, mv["p"])
    if mv["move"] in ("gate", "dropout"):
        tg = volume_target(mv["track"], info)
        mv = dict(mv, pid=tg["pid"])
        info = dict(info, targets=info["targets"] + [tg])
    tg = next((x for x in info.get("targets", []) if x["pid"] == mv["pid"]), None)
    if tg is None:
        return f"{mv['track']}: control {mv['label']} not found"
    a, b = (mv["a"] - 1) * BPB, (mv["b"] - 1) * BPB
    pts = points(mv["move"], tg, a, b, mv["p"])
    lo_b, hi_b = min(t for t, _ in pts), max(t for t, _ in pts)
    span = automated_span(root, info["el"], tg["pid"])
    if span and not (span[1] < lo_b - BPB or span[0] > hi_b + BPB):
        return f"{mv['track']}: {tg['label']} already has your automation there; left alone"
    parent = info["el"].find("./AutomationEnvelopes/Envelopes")
    env = next((e for e in parent.findall("./AutomationEnvelope") if v(e, "./EnvelopeTarget/PointeeId") == tg["pid"]), None)
    if env is None:
        env = ET.SubElement(parent, "AutomationEnvelope", Id=str(len(parent)))
        et = ET.SubElement(env, "EnvelopeTarget"); ET.SubElement(et, "PointeeId", Value=tg["pid"])
        au = ET.SubElement(env, "Automation"); ET.SubElement(au, "Events")
        ET.SubElement(au, "AutomationTransformViewState")
        ET.SubElement(env.find("./Automation/Events"), "FloatEvent", Id=str(next_id(root)), Time="-63072000",
                      Value=repr(tg["base"]))
    ev = env.find("./Automation/Events")
    for t, x in pts:
        x = float(min(tg["hi"], max(tg["lo"], x)))
        new = ET.Element("FloatEvent", Id=str(next_id(root)), Time=repr(float(t)), Value=repr(x))
        idx = sum(1 for e in ev if float(e.get("Time")) <= t)
        ev.insert(idx, new)
    return None


def parse_tweaks(items):
    out = {}
    for it in items or []:
        fid, _, kv = it.partition(":")
        out[fid.strip()] = {k.strip(): (v_.strip()) for k, _, v_ in (x.partition("=") for x in kv.replace(" ", ",").split(",") if "=" in x)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix motion", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    from hypnomix.session import liveversion as LV; LV.add_force_flag(ap)
    ap.add_argument("als", nargs="?"); ap.add_argument("--mix")
    ap.add_argument("--learn", nargs="+", metavar="EXAMPLE.als", help="learn your moves from finished songs")
    ap.add_argument("--style", default=str(STYLE), help="style file (default ~/.hypnomix/motion-style.json)")
    ap.add_argument("--names", help="names.json from `hypnomix name` (which tracks are drums, bass, keys…)")
    ap.add_argument("--json"); ap.add_argument("--plan", nargs="?", const=True, help="write the proposals into a scan folder")
    ap.add_argument("--apply", metavar="NEW.als"); ap.add_argument("--ids")
    ap.add_argument("--tweak", action="append", help='"motion-2:bars=8,depth=0.5" (repeatable)')
    ap.add_argument("--engine", nargs="?", const="", metavar="URL",
                    help="HypnoMix Studio: write the chosen moves into the open HypnoMix engine (it must have this very "
                         "session open; one undo step a control; save in HypnoMix Studio to keep it)")
    a = ap.parse_args(argv)
    if a.learn:
        st = learn(a.learn)
        Path(a.style).parent.mkdir(parents=True, exist_ok=True)
        Path(a.style).write_text(json.dumps(st, indent=1), encoding="utf-8")
        print(f"learned {len(st['examples'])} moves from {len(a.learn)} set(s) → {a.style}")
        for mv, m in st["moves"].items():
            print(f"  {WORDS.get(mv, mv):<20} {m['count']:2d}×, typically {m['bars']:g} bars, depth {m['depth']:.0%}"
                  + (f", {m['on_main']} on Main" if m["on_main"] else ""))
        if not a.als:
            return
    if not a.als:
        sys.exit("give a set (or --learn examples)")
    from hypnomix.session import tempo_ardour as TA
    if TA.is_session(a.als):
        from hypnomix.session import motion_ardour as MA
        rc = MA.main(a)
        if rc:
            sys.exit(rc)                      # (the command line ignores what main returns)
        return rc
    src = Path(a.als)
    style = json.loads(Path(a.style).read_text(encoding="utf-8", errors="replace")) if Path(a.style).exists() else None
    root = ET.fromstring(read_gz(src))
    labels = None
    if a.names and Path(a.names).exists():
        labels = {r["old"]: (r.get("final") or r.get("label") or "") for r in json.loads(Path(a.names).read_text(encoding="utf-8", errors="replace"))["tracks"]
                  if float(r.get("confidence") or 0) >= 0.5}
    moves, meta = propose(root, a.mix, style, labels)
    fs = findings(moves, meta)
    print(f"{src.name}: {meta['tempo']:g} BPM, {len(meta['sections'])} sections ({meta['how']}); returns used: "
          + (", ".join(f"{r['name']} ({r['kind']})" for r in meta["returns"]) or "none")
          + ("" if meta["learned"] else "; gentle defaults (nothing learned yet)"))
    for f in fs:
        print(f"  {f['id']:<10} {f['where']:<14} {f['fix'].split('. An option')[0]}")
    if not fs:
        print("  no moves to offer (no filters, reverb or delay sends to move, or no repetitive sections)")
    if a.json:
        Path(a.json).write_text(json.dumps({"tool": "motion", "set": str(src), "findings": fs, "meta":
                                            {k: meta[k] for k in ("tempo", "sections", "how", "learned")}}, indent=1, default=str), encoding="utf-8")
    if a.plan:
        from hypnomix.workflow import plan as PL
        od = PL.scan_dir(a.plan if isinstance(a.plan, str) else None, src, " (motion)")
        if a.names and Path(a.names).exists():                    # fix re-checks with the same track roles
            (Path(od) / "raw" / "names").mkdir(parents=True, exist_ok=True)
            (Path(od) / "raw" / "names" / "names.json").write_text(Path(a.names).read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        PL.write(od, "motion", src, fs, [f"motion: sections {meta['how']}"] +
                 ([] if meta["learned"] else ["motion: nothing learned yet (`hypnomix motion --learn SONG.als`)"]) +
                 ["motion: every move is an OPTION (none is applied by default); fine controls go in the decision note, "
                  "e.g. --decide motion-3=approve --note \"bars=6 depth=0.3\""])
        sj = Path(od) / "scan.json"
        info = json.loads(sj.read_text(encoding="utf-8")) if sj.exists() else {}
        info.update(mode="set", mix=a.mix, motion_style=a.style)
        sj.write_text(json.dumps(info, indent=1), encoding="utf-8")
    if a.apply:
        if Path(a.apply).resolve() == src.resolve():
            sys.exit("refusing to overwrite the set; give a new file name")
        if Path(a.apply).resolve().parent != src.resolve().parent:
            sys.exit(f"write the new set in the same folder as the original ({src.resolve().parent})")
        want = {x.strip() for x in (a.ids or "").split(",") if x.strip()}
        if not want:
            sys.exit("say which moves: --ids motion-2,motion-5 (every move is an option; none is applied by default)")
        tw = parse_tweaks(a.tweak)
        T, _ = set_targets(root)
        done, skipped = 0, []
        for f in fs:
            if f["id"] not in want:
                continue
            mv = dict(f["move"]); p = dict(mv["p"])
            for k, val in tw.get(f["id"], {}).items():
                if k == "track":
                    alt = next((tg for tg in T.get(val, {}).get("targets", []) if tg["kind"] in
                                {x["kind"] for x in T[mv["track"]]["targets"] if x["pid"] == mv["pid"]}), None)
                    if alt is None:
                        skipped.append(f"{f['id']}: {val} has no control of that kind"); continue
                    mv.update(track=val, pid=alt["pid"], label=alt["label"])
                elif k == "pattern":
                    p[k] = val
                else:
                    p[k] = float(val)
            mv["p"] = p
            err = write_move(root, T, mv)
            if err:
                skipped.append(f"{f['id']}: {err}")
            else:
                done += 1
        data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")
        from hypnomix.session import liveversion as LV
        LV.guard_write(root)                # refuses a set saved by a Live newer than the newest tested
        with gzip.open(a.apply, "wb") as fh:
            fh.write(data)
        print(f"wrote {a.apply}: {done} move(s) written as automation" + ("".join(f"\n  skipped {s}" for s in skipped)))


if __name__ == "__main__":
    main()
