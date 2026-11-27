#!/usr/bin/env python3
"""What changed between two Live sets, in plain words. Reads both, changes neither.

  hypnomix diff OLD.als NEW.als [--json OUT.json] [--all]

Per track: fader, pan, sends, track on/off; devices added, removed, switched on or off, and every device
parameter whose value changed (Saturator: Drive 18 → 4); clips added or removed, and per clip its gain,
fades, start / end and warp markers; automation envelopes added, removed or with changed points.
Also the tempo and tracks added, removed or renamed.

Use it after any tool writes a new set, to see exactly what it did, and before opening the set in Live.
`hypnomix fix` writes this list into its log. Plug-in internals that Live stores as opaque data are not
compared; --all also lists changes to parameters that are not plain numbers or switches.
Live sets (.als) only: a REAPER project or a HypnoMix DAW session is refused with one sentence (`fix` lists what it changed
there in fix-log.md).
"""
import argparse, json, math, sys
from pathlib import Path

from hypnomix.session import automation as aa

SKIP_TAGS = {"LomId", "LomIdView", "LastPresetRef", "Pointee", "SourceContext", "OverwriteProtectionNumber",
             "LockedScripts", "IsExpanded", "IsFolded", "ShouldShowPresetName", "UserName", "Annotation"}


def gv(el, path):
    e = el.find(path) if el is not None else None
    return e.get("Value") if e is not None else None


def db(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return 20 * math.log10(x) if x > 0 else -math.inf


def fmt_db(x):
    d = db(x)
    return "?" if d is None else ("-inf dB" if d == -math.inf else f"{d:+.1f} dB")


def num(x):
    try:
        f = float(x)
        return f"{f:.4g}"
    except (TypeError, ValueError):
        return str(x)


def where(beat, bpb):
    beat = max(0.0, float(beat))
    return f"{int(beat // bpb) + 1}.{int(beat % bpb) + 1}.{int(round((beat % 1) * 100)):02d}"


def device_name(d):
    u = gv(d, "./UserName")
    return u if u else d.tag


def device_params(d):
    """{parameter name: value} for the device's own controls (Manual values), nested ones as A/B."""
    out = {}

    def walk(el, prefix, depth):
        for c in el:
            if c.tag in SKIP_TAGS or c.tag == "Devices":   # nested racks are compared as their own devices
                continue
            m = c.find("./Manual")
            if m is not None and m.get("Value") is not None:
                out[prefix + c.tag] = m.get("Value")
            elif depth < 3 and len(c):
                walk(c, prefix + c.tag + "/", depth + 1)
    walk(d, "", 0)
    return out


def devices(t):
    devs = t.find("./DeviceChain/DeviceChain/Devices")
    return list(devs) if devs is not None else []


def clip_rows(t):
    rows = {}
    for c in t.findall(".//ArrangerAutomation/Events/AudioClip") + t.findall(".//ArrangerAutomation/Events/MidiClip"):
        key = (c.get("Id"), gv(c, "./Name") or "")
        rows[key] = c
    return rows


def envelope_points(t):
    """{target label: (points, is volume-like)}; switches and enums are kept as text."""
    out = {}
    parent = t.find("./AutomationEnvelopes/Envelopes")
    if parent is None:
        return out
    tg = aa.targets(t)
    for env in parent:
        pid = gv(env, "./EnvelopeTarget/PointeeId")
        lab, _, vol_like = tg.get(pid, (f"control {pid}", None, False))
        ev = env.find("./Automation/Events")
        pts = []
        for e in (ev if ev is not None else []):
            if e.get("Value") is None or e.get("Time") is None or float(e.get("Time")) < -1e6:
                continue
            try:
                val = round(float(e.get("Value")), 6)
            except ValueError:
                val, vol_like = e.get("Value"), False
            pts.append((round(float(e.get("Time")), 4), val))
        out[lab] = (pts, vol_like)
    return out


def diff(old, new, show_all=False):
    """List of {track, what, before, after, where} dicts, in track order."""
    ta, tb = aa.load(old), aa.load(new)
    bpb = aa.BPB
    ra, rb = ta.getroot(), tb.getroot()
    out = []
    add = lambda track, what, before="", after="", where_="": out.append(
        dict(track=track, what=what, before=before, after=after, where=where_))

    tempo_a, tempo_b = gv(ra, ".//Tempo/Manual"), gv(rb, ".//Tempo/Manual")
    if tempo_a != tempo_b:
        add("(song)", "tempo", num(tempo_a), num(tempo_b))
    spb = 60.0 / float(tempo_b or 120)

    A = {t.get("Id") or aa.tname(t): t for t in aa.tracks(ra) if t is not None}
    B = {t.get("Id") or aa.tname(t): t for t in aa.tracks(rb) if t is not None}
    oa = [k for k in A if k in B]; ob = [k for k in B if k in A]
    if oa != ob:
        moved = [aa.tname(B[k]) for i, k in enumerate(ob) if oa.index(k) != i]
        add("(song)", "track order changed", f"{len(moved)} tracks in a new place",
            ", ".join(aa.tname(B[k]) for k in ob)[:600])
    for k in A:
        if k not in B:
            add(aa.tname(A[k]), "track removed")
    for k, t1 in B.items():
        name = aa.tname(t1)
        if k not in A:
            add(name, "track added")
            continue
        t0 = A[k]
        if aa.tname(t0) != name:
            add(name, "renamed", aa.tname(t0), name)
        # mixer
        mx0, mx1 = t0.find("./DeviceChain/Mixer"), t1.find("./DeviceChain/Mixer")
        if mx0 is not None and mx1 is not None:
            v0, v1 = gv(mx0, "./Volume/Manual"), gv(mx1, "./Volume/Manual")
            if v0 != v1:
                add(name, "fader", fmt_db(v0), fmt_db(v1))
            p0, p1 = gv(mx0, "./Pan/Manual"), gv(mx1, "./Pan/Manual")
            if p0 != p1:
                add(name, "pan", num(p0), num(p1))
            s0, s1 = gv(mx0, "./Speaker/Manual"), gv(mx1, "./Speaker/Manual")
            if s0 != s1:
                add(name, "track switched " + ("on" if s1 == "true" else "off"))
            for i, (h0, h1) in enumerate(zip(mx0.findall("./Sends/TrackSendHolder"), mx1.findall("./Sends/TrackSendHolder"))):
                a_, b_ = gv(h0, "./Send/Manual"), gv(h1, "./Send/Manual")
                if a_ != b_:
                    add(name, f"send {chr(65 + i)}", fmt_db(a_), fmt_db(b_))
        # devices
        d0 = {d.get("Id"): d for d in devices(t0)}
        d1 = {d.get("Id"): d for d in devices(t1)}
        order0, order1 = [device_name(d) for d in devices(t0)], [device_name(d) for d in devices(t1)]
        for i, d in d0.items():
            if i not in d1:
                add(name, f"device removed: {device_name(d)}")
        for i, d in d1.items():
            if i not in d0:
                add(name, f"device added: {device_name(d)}")
                continue
            if d.tag != d0[i].tag:
                add(name, "device replaced", device_name(d0[i]), device_name(d))
                continue
            on0, on1 = gv(d0[i], "./On/Manual"), gv(d, "./On/Manual")
            if on0 != on1:
                add(name, f"{device_name(d)} switched " + ("on" if on1 == "true" else "off"))
            pa, pb = device_params(d0[i]), device_params(d)
            for prm in pb:
                if prm == "On" or prm not in pa or pa[prm] == pb[prm]:
                    continue
                try:
                    if abs(float(pa[prm]) - float(pb[prm])) < 1e-9:       # 4 and 4.0 are the same value
                        continue
                except ValueError:
                    pass
                plain = all(x.lstrip("-").replace(".", "", 1).replace("e-", "", 1).isdigit() or x in ("true", "false")
                            for x in (pa[prm], pb[prm]))
                if plain or show_all:
                    add(name, f"{device_name(d)}: {prm}", num(pa[prm]), num(pb[prm]))
        if order0 != order1 and sorted(order0) == sorted(order1):
            add(name, "device order", " → ".join(order0), " → ".join(order1))
        # clips
        c0, c1 = clip_rows(t0), clip_rows(t1)
        for key, c in c0.items():
            if key not in c1:
                add(name, f"clip removed: {key[1] or 'clip'}", where_=where(gv(c, "./CurrentStart") or 0, bpb))
        for key, c in c1.items():
            w = where(gv(c, "./CurrentStart") or 0, bpb)
            label = key[1] or "clip"
            if key not in c0:
                add(name, f"clip added: {label}", where_=w)
                continue
            o = c0[key]
            for lab, path, f in (("clip start", "./CurrentStart", lambda x: where(x, bpb)),
                                 ("clip end", "./CurrentEnd", lambda x: where(x, bpb)),
                                 ("clip gain", "./SampleVolume", fmt_db),
                                 ("fade in", "./Fades/FadeInLength", lambda x: f"{float(x) * spb * 1000:.0f} ms"),
                                 ("fade out", "./Fades/FadeOutLength", lambda x: f"{float(x) * spb * 1000:.0f} ms"),
                                 ("clip switched off", "./Disabled", str), ("warp", "./IsWarped", str),
                                 ("loop", "./Loop/LoopOn", str)):
                a_, b_ = gv(o, path), gv(c, path)
                try:
                    same = abs(float(a_) - float(b_)) < 1e-9          # 96 and 96.0 are the same value
                except (TypeError, ValueError):
                    same = a_ == b_
                if not same and a_ is not None and b_ is not None:
                    add(name, f"{lab} ({label})", f(a_), f(b_), w)
            if c.tag == "MidiClip":                          # notes moved (timing fixes on MIDI)
                n0 = [float(e.get("Time")) for e in o.iter("MidiNoteEvent")]
                n1 = [float(e.get("Time")) for e in c.iter("MidiNoteEvent")]
                moved = [b_ - a_ for a_, b_ in zip(n0, n1) if abs(b_ - a_) > 1e-9]
                if moved or len(n0) != len(n1):
                    add(name, f"notes moved ({label})", f"{len(n0)} notes",
                        f"{len(moved)} moved, by {min(moved) * spb * 1000:+.0f} to {max(moved) * spb * 1000:+.0f} ms"
                        if moved else f"{len(n1)} notes", w)
            w0 = [(w_.get("SecTime"), w_.get("BeatTime")) for w_ in o.findall("./WarpMarkers/WarpMarker")]
            w1 = [(w_.get("SecTime"), w_.get("BeatTime")) for w_ in c.findall("./WarpMarkers/WarpMarker")]
            if w0 != w1:
                shift = ""
                if len(w0) == len(w1):
                    mv = max(abs(float(a_[0]) - float(b_[0])) for a_, b_ in zip(w0, w1)) * 1000
                    shift = f", largest move {mv:.0f} ms"
                add(name, f"warp markers ({label})", f"{len(w0)} markers", f"{len(w1)} markers{shift}", w)
        # automation
        e0, e1 = envelope_points(t0), envelope_points(t1)
        for lab in e0:
            if lab not in e1:
                add(name, f"automation removed: {lab}")
        for lab, (pts, vol_like) in e1.items():
            if lab not in e0:
                add(name, f"automation added: {lab}", "", f"{len(pts)} points",
                    where(pts[0][0], bpb) if pts else "")
                continue
            old_pts = e0[lab][0]
            if old_pts == pts:
                continue
            changed = sorted(p[0] for p in set(pts) ^ set(old_pts))
            lo, hi = changed[0], changed[-1]
            new_only = [p for p in pts if p not in set(old_pts)]
            extra = ""
            if vol_like and new_only:
                lowest = min(v for _, v in new_only)
                extra = f", lowest new point {fmt_db(lowest)}"
            add(name, f"automation changed: {lab}", f"{len(old_pts)} points",
                f"{len(pts)} points{extra}", f"{where(lo, bpb)}–{where(hi, bpb)}")
    return out


def text(rows):
    if not rows:
        return "no differences found in tracks, devices, clips or automation"
    L, cur = [], None
    for r in rows:
        if r["track"] != cur:
            cur = r["track"]
            L.append(f"\n{cur}")
        ba = f": {r['before']} → {r['after']}" if (r["before"] or r["after"]) else ""
        at = f"  @ {r['where']}" if r["where"] else ""
        L.append(f"  {r['what']}{ba}{at}")
    return "\n".join(L).strip()


def main():
    ap = argparse.ArgumentParser(prog="hypnomix diff", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old"); ap.add_argument("new")
    ap.add_argument("--json", metavar="OUT.json")
    ap.add_argument("--all", action="store_true", help="also list parameters that are not plain numbers or switches")
    a = ap.parse_args()
    from hypnomix.core import args as A
    A.live_set_only(a.old, "diff")
    A.live_set_only(a.new, "diff")
    rows = diff(a.old, a.new, a.all)
    if a.json:
        Path(a.json).write_text(json.dumps(dict(old=str(a.old), new=str(a.new), changes=rows), indent=1), encoding="utf-8")
    print(f"{Path(a.old).name} → {Path(a.new).name}: {len(rows)} change(s)\n")
    print(text(rows))


if __name__ == "__main__":
    main()
