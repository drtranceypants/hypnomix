#!/usr/bin/env python3
"""List and edit arrangement automation in an Ableton .als — always writing to a NEW file.

Live must not have the set open while you write (it would overwrite your edit on save).
Times are in bars (1 = start). Mixer volume is shown/edited in dB; other params in raw values.

  list   SET.als [--track NAME]                     every envelope: track, target, points, range
  show   SET.als TRACK TARGET                       the points of one envelope
  offset SET.als OUT.als TRACK TARGET dB [--from BAR --to BAR]
         shift a volume/send envelope by dB (whole curve or a bar range; inserts edge points)
  dip    SET.als OUT.als TRACK TARGET dB BAR1 BAR2 [--ramp BEATS]
         add a dip of dB between BAR1 and BAR2 to a mixer volume/send (creates the envelope if missing)

TARGET: "Volume", "Pan", "Send A", "Send B", or "<Device>/<Param>" (e.g. "Reverb/DecayTime").
"""
import argparse, gzip, math, re, sys, copy
import xml.etree.ElementTree as ET
from pathlib import Path

BPB = 4  # beats per bar; set from the set's time signature when loaded


def load(p):
    global BPB
    t = ET.ElementTree(ET.fromstring(gzip.open(p).read()))
    n = t.getroot().find(".//TimeSignatures/RemoteableTimeSignature/Numerator")
    if n is not None:
        BPB = int(n.get("Value"))
    return t


def save(tree, src, out):
    out = Path(out)
    if out.resolve() == Path(src).resolve():
        sys.exit("refusing to overwrite the source set — give a new file name")
    data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(tree.getroot(), encoding="utf-8")
    with gzip.open(out, "wb") as f:
        f.write(data)
    print(f"wrote {out}")


def tracks(root):
    ts = list(root.find(".//Tracks"))
    m = root.find(".//MainTrack")
    if m is None:
        m = root.find(".//MasterTrack")
    return ts + [m]


def tname(t):
    n = t.find("./Name/EffectiveName")
    return "Main" if t.tag in ("MainTrack", "MasterTrack") else n.get("Value")


def targets(t):
    """map AutomationTarget id -> (label, param element, is_volume_like)"""
    out = {}
    mx = t.find("./DeviceChain/Mixer")
    for p, lab in (("Volume", "Volume"), ("Pan", "Pan")):
        e = mx.find(f"./{p}")
        if e is not None and e.find("./AutomationTarget") is not None:
            out[e.find("./AutomationTarget").get("Id")] = (lab, e, p == "Volume")
    for i, h in enumerate(mx.findall("./Sends/TrackSendHolder")):
        e = h.find("./Send")
        out[e.find("./AutomationTarget").get("Id")] = (f"Send {chr(65 + i)}", e, True)
    devs = t.find("./DeviceChain/DeviceChain/Devices")
    if devs is not None:
        for d in devs.iter():
            for prm in list(d):
                at = prm.find("./AutomationTarget")
                if at is not None and prm.tag not in ("Volume", "Pan", "Send"):
                    lab = d.find("./UserName")
                    dn = lab.get("Value") if lab is not None and lab.get("Value") else d.tag
                    out.setdefault(at.get("Id"), (f"{dn}/{prm.tag}", prm, False))
    return out


def envelopes(t):
    env_parent = t.find("./AutomationEnvelopes/Envelopes")
    tg = targets(t)
    res = []
    if env_parent is None:
        return res, tg
    for env in env_parent:
        pid = env.find("./EnvelopeTarget/PointeeId").get("Value")
        if pid in tg:
            res.append((tg[pid][0], env, tg[pid]))
    return res, tg


db = lambda v: 20 * math.log10(v) if v > 0 else -math.inf
lin = lambda d: 10 ** (d / 20)
bar = lambda beats: beats / BPB + 1
beats = lambda b: (b - 1) * BPB


def events(env):
    ev = env.find("./Automation/Events")
    return ev, [(float(e.get("Time")), float(e.get("Value")), e) for e in ev if e.get("Value") is not None]


def find_track(root, name):
    hits = [t for t in tracks(root) if tname(t).lower() == name.lower()] or \
           [t for t in tracks(root) if tname(t).lower().startswith(name.lower())]
    if len(hits) != 1:
        sys.exit(f"track {name!r}: {'ambiguous' if hits else 'not found'}; tracks: {[tname(t) for t in tracks(root)]}")
    return hits[0]


def value_at(pts, b):
    """envelope value at beat b (linear between points; Live's default)."""
    prev = None
    for t, v, _ in pts:
        if t > b:
            if prev is None:
                return v
            t0, v0 = prev
            return v0 + (v - v0) * (b - t0) / (t - t0) if t > t0 else v
        prev = (t, v)
    return prev[1]


def next_id(root):
    return max(int(e.get("Id")) for e in root.iter() if e.get("Id", "").isdigit()) + 1


def get_or_create_env(root, t, target):
    envs, tg = envelopes(t)
    for lab, env, info in envs:
        if lab.lower() == target.lower():
            return env, info
    # create a new envelope for a mixer target, starting at the current manual value
    pid = [k for k, (lab, e, vl) in tg.items() if lab.lower() == target.lower()]
    if not pid:
        sys.exit(f"no automatable target {target!r} on {tname(t)}; have: {sorted(l for l, *_ in tg.values())[:30]}")
    lab, prm, vl = tg[pid[0]]
    manual = float(prm.find("./Manual").get("Value"))
    parent = t.find("./AutomationEnvelopes/Envelopes")
    nid = next_id(root)
    env = ET.SubElement(parent, "AutomationEnvelope", Id=str(len(parent)))
    et = ET.SubElement(env, "EnvelopeTarget"); ET.SubElement(et, "PointeeId", Value=pid[0])
    au = ET.SubElement(env, "Automation"); evs = ET.SubElement(au, "Events")
    ET.SubElement(evs, "FloatEvent", Id=str(nid), Time="-63072000", Value=repr(manual))
    ET.SubElement(au, "AutomationTransformViewState")
    return env, (lab, prm, vl)


def insert_point(root, env, b, v):
    ev, pts = events(env)
    nid = next_id(root)
    new = ET.Element("FloatEvent", Id=str(nid), Time=repr(float(b)), Value=repr(float(v)))
    idx = sum(1 for t, *_ in pts if t <= b)
    ev.insert(idx, new)


def scale_range(root, env, d_db, b0, b1, ramp=0.0, vol_like=True):
    """multiply (volume/send) values inside [b0,b1] by d_db; ramps of `ramp` beats at the edges."""
    _, pts = events(env)
    edges = [b0 - ramp, b0, b1, b1 + ramp] if ramp else [b0, b1]
    for e in edges:
        if not any(abs(t - e) < 1e-6 for t, *_ in pts):
            insert_point(root, env, e, value_at(pts, e))
            _, pts = events(env)
    for t, v, el in pts:
        if b0 - 1e-6 <= t <= b1 + 1e-6:
            nv = v * lin(d_db) if vol_like else v + d_db
            el.set("Value", repr(nv))


def cmd_list(a):
    r = load(a.set).getroot()
    for t in tracks(r):
        if a.track and not tname(t).lower().startswith(a.track.lower()):
            continue
        envs, _ = envelopes(t)
        for lab, env, (l, prm, vl) in envs:
            _, pts = events(env)
            pts = [p for p in pts if p[0] > -1e6] or pts
            vals = [db(v) if vl else v for _, v, _ in pts]
            unit = " dB" if vl else ""
            print(f"{tname(t)[:28]:<29}{lab[:34]:<35}{len(pts):>4} pts  bars {bar(max(0, pts[0][0])):6.1f}–{bar(pts[-1][0]):6.1f}"
                  f"  {min(vals):7.1f}…{max(vals):6.1f}{unit}")


def cmd_show(a):
    r = load(a.set).getroot()
    t = find_track(r, a.track)
    for lab, env, (l, prm, vl) in envelopes(t)[0]:
        if lab.lower() == a.target.lower():
            for tt, v, _ in events(env)[1]:
                print(f"  bar {'start' if tt < -1e6 else f'{bar(tt):7.2f}'}   {db(v):7.2f} dB" if vl else f"  bar {bar(tt):7.2f}   {v}")
            return
    sys.exit("no such envelope (use `list`)")


def cmd_offset(a):
    tree = load(a.set); r = tree.getroot(); t = find_track(r, a.track)
    env, (lab, prm, vl) = get_or_create_env(r, t, a.target)
    b0 = beats(a.frm) if a.frm else -1e9
    b1 = beats(a.to) if a.to else 1e9
    scale_range(r, env, a.db, b0, b1, 0, vl)
    save(tree, a.set, a.out)


def cmd_dip(a):
    tree = load(a.set); r = tree.getroot(); t = find_track(r, a.track)
    env, (lab, prm, vl) = get_or_create_env(r, t, a.target)
    scale_range(r, env, a.db, beats(a.bar1), beats(a.bar2), a.ramp, vl)
    save(tree, a.set, a.out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = ap.add_subparsers(dest="cmd", required=True)
    p = s.add_parser("list"); p.add_argument("set"); p.add_argument("--track"); p.set_defaults(f=cmd_list)
    p = s.add_parser("show"); p.add_argument("set"); p.add_argument("track"); p.add_argument("target"); p.set_defaults(f=cmd_show)
    p = s.add_parser("offset"); p.add_argument("set"); p.add_argument("out"); p.add_argument("track"); p.add_argument("target")
    p.add_argument("db", type=float); p.add_argument("--from", dest="frm", type=float); p.add_argument("--to", type=float); p.set_defaults(f=cmd_offset)
    p = s.add_parser("dip"); p.add_argument("set"); p.add_argument("out"); p.add_argument("track"); p.add_argument("target")
    p.add_argument("db", type=float); p.add_argument("bar1", type=float); p.add_argument("bar2", type=float)
    p.add_argument("--ramp", type=float, default=1.0, help="ramp length in beats (default 1)"); p.set_defaults(f=cmd_dip)
    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
