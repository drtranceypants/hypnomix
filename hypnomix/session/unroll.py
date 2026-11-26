#!/usr/bin/env python3
"""Unroll looped Arrangement clips into back-to-back copies, one per loop pass, so each pass can be edited
(a timing nudge, a gain change) on its own.

Each copy plays exactly the audio (or notes) that pass played: the start marker and a partial first pass are
kept, a partial last pass is trimmed, warp markers, warp mode, gain and clip envelopes are copied, the outer fades
are kept and the seams between copies have no fades (so they join seamlessly), and every copy gets a new id.
A clip whose loop region is longer than what it plays (loop on, but it never wraps) becomes one copy with loop off.

Note: once unrolled, editing "the loop" in Live no longer changes every pass: each copy is its own clip.

Usage:  hypnomix unroll SET.als --track NAME [--track …] --apply NEW.als [--at BAR]   (only the clip playing at BAR)
"""
import argparse, copy, gzip, sys
from hypnomix.core.gz import read_gz
import xml.etree.ElementTree as ET
from pathlib import Path

v = lambda n, p: (n.find(p).get("Value") if n.find(p) is not None else None)
AUDIO = "./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events"
MIDI = "./DeviceChain/MainSequencer/ClipTimeable/ArrangerAutomation/Events"


def _set(el, path, val):
    e = el.find(path)
    if e is not None:
        e.set("Value", val if isinstance(val, str) else repr(float(val)))


def passes(c, tempo):
    """[(arrangement start, arrangement end, content start, content end)] for a looped clip. Content positions are
    in the clip's own units (beats; seconds for an unwarped audio clip)."""
    cs, ce = float(v(c, "./CurrentStart")), float(v(c, "./CurrentEnd"))
    ls, le = float(v(c, "./Loop/LoopStart")), float(v(c, "./Loop/LoopEnd"))
    rel = float(v(c, "./Loop/StartRelative") or 0)
    per = 1.0 if (c.tag == "MidiClip" or v(c, "./IsWarped") == "true") else 60.0 / tempo   # content units per beat
    L = le - ls
    if L <= 0:
        return [(cs, ce, ls + rel, ls + rel + (ce - cs) * per)]
    out, x, pos = [], cs, ls + rel
    while x < ce - 1e-9 and len(out) < 10000:
        avail = le - pos                                   # content left before the loop wraps
        dur = min((ce - x), avail / per)
        out.append((x, x + dur, pos, pos + dur * per))
        x += dur
        pos = ls
    return out


def unroll_clip(events, c, tempo):
    """Replace looped clip `c` (inside `events`) with its passes. Returns the new clip elements."""
    ps = passes(c, tempo)
    ids = [int(x.get("Id")) for x in events if (x.get("Id") or "").isdigit()]
    nid = max(ids + [-1]) + 1
    new = []
    for k, (a, b, c0, c1) in enumerate(ps):
        x = copy.deepcopy(c)
        x.set("Id", str(c.get("Id")) if k == 0 else str(nid + k - 1))
        _set(x, "./CurrentStart", a); _set(x, "./CurrentEnd", b)
        x.set("Time", repr(float(a)))                     # Live keeps a clip's Time equal to its start
        for tag, val in (("LoopStart", c0), ("LoopEnd", c1), ("StartRelative", 0.0), ("OutMarker", c1),
                         ("HiddenLoopStart", c0), ("HiddenLoopEnd", c1)):
            _set(x, f"./Loop/{tag}", val)
        _set(x, "./Loop/LoopOn", "false")
        f = x.find("./Fades")
        if f is not None and len(ps) > 1:
            if k > 0:                                      # seams join without fades
                _set(f, "./FadeInLength", 0.0); _set(f, "./IsDefaultFadeIn", "false")
            if k < len(ps) - 1:
                _set(f, "./FadeOutLength", 0.0); _set(f, "./IsDefaultFadeOut", "false")
        new.append(x)
    i = list(events).index(c)
    events.remove(c)
    for k, x in enumerate(new):
        events.insert(i + k, x)
    return new


def looped_clips(t):
    lane = t.find(AUDIO) if t.tag == "AudioTrack" else t.find(MIDI)
    tag = "AudioClip" if t.tag == "AudioTrack" else "MidiClip"
    return lane, [c for c in (lane.findall(tag) if lane is not None else []) if v(c, "./Loop/LoopOn") == "true"
                  and v(c, "./Disabled") != "true"]


def main():
    ap = argparse.ArgumentParser(prog="hypnomix unroll", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    from hypnomix.session import liveversion as LV; LV.add_force_flag(ap)
    ap.add_argument("als"); ap.add_argument("--track", action="append", required=True)
    ap.add_argument("--at", type=float, help="only the clip playing at this bar"); ap.add_argument("--apply", required=True)
    a = ap.parse_args()
    src = Path(a.als)
    if Path(a.apply).resolve() == src.resolve():
        sys.exit("refusing to overwrite the set; give a new file name")
    if Path(a.apply).resolve().parent != src.resolve().parent:
        sys.exit(f"write the new set in the same folder as the original ({src.resolve().parent})")
    root = ET.fromstring(read_gz(src))
    tempo = float(v(root, ".//Tempo/Manual"))
    n = 0
    for t in root.find(".//Tracks"):
        if v(t, "./Name/EffectiveName") not in a.track:
            continue
        lane, cl = looped_clips(t)
        for c in cl:
            if a.at is not None:
                b = (a.at - 1) * 4
                if not (float(v(c, "./CurrentStart")) <= b < float(v(c, "./CurrentEnd"))):
                    continue
            k = len(unroll_clip(lane, c, tempo))
            print(f"{v(t, './Name/EffectiveName')}: a looped clip at bar {float(v(c, './CurrentStart')) / 4 + 1:g} -> {k} copies")
            n += 1
    data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")
    from hypnomix.session import liveversion as LV
    LV.guard_write(root)                # refuses a set saved by a Live newer than the newest tested
    with gzip.open(a.apply, "wb") as fh:
        fh.write(data)
    print(f"wrote {a.apply}: {n} clip(s) unrolled (editing the loop in Live no longer changes every pass)")


if __name__ == "__main__":
    main()
