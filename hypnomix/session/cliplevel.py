#!/usr/bin/env python3
"""Lower harmonies sitting too low: propose raising single clips to match the rest of their track.

Clip gain is often set by hand clip by clip, and a few clips of a lower harmony end up well under the others,
so the bottom of the stack thins out there. For each LOWER harmony track (the lower half of the harmony parts
by pitch; never the lead), every clip's sung level (with the track's fader) is compared with the track's other
clips. A clip more than --under dB (4) under their median is proposed for a clip-gain raise:

  - only up to the track's usual level (the median of its other clips), at most --max-raise dB (6)
  - never closer to the lead than --lead-margin dB (1.5) where both sing, so the harmony rules still hold
  - only an OPTION: nothing is raised unless it is approved

Usage:
  hypnomix cliplevel SET.als [--names names.json] [--renders DIR] [--json OUT.json]
  hypnomix cliplevel SET.als --apply NEW.als --ids cliplevel-1,cliplevel-3
Renders come from DIR if given (the scan's vocal renders), otherwise the vocal tracks are rendered (no Live).
"""
import argparse, gzip, json, math, re, subprocess, sys, tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

v = lambda n, p: (n.find(p).get("Value") if n.find(p) is not None else None)
LANE = "./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events/AudioClip"
MAX_CLIP_GAIN = 15.85        # +24 dB, Live's clip gain ceiling
safe = lambda n: re.sub(r'[\\/:*?"<>|]', "-", n)


def hx(*args):
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def vocal_roles(names_json):
    rows = json.loads(Path(names_json).read_text())["tracks"]
    lab = lambda r: str(r.get("final") or r.get("label") or "")
    lead = next((r["old"] for r in rows if lab(r).startswith("Lead Vocal") and r.get("on", True)), None)
    harm = [r["old"] for r in rows if r.get("kind") == "Audio" and r.get("on", True) and float(r.get("confidence") or 0) >= 0.5
            and re.match(r"(Harmony|Backing Vocal|Vocal)\b", lab(r)) and r["old"] != lead]
    return lead, harm


def propose(set_path, names_json=None, renders=None, under=4.0, max_raise=6.0, lead_margin=1.5):
    from hypnomix.core import dsp, pitch
    set_path = Path(set_path)
    root = ET.fromstring(gzip.open(set_path).read())
    tempo = float(v(root, ".//Tempo/Manual"))
    spb = 60.0 / tempo
    if names_json is None:
        nd = Path(tempfile.mkdtemp())
        hx("name", set_path, "--out", nd)
        names_json = nd / "names.json"
    lead, harm = vocal_roles(names_json)
    if len(harm) < 2:
        return [], dict(note="fewer than two harmony tracks: nothing to compare")
    rd = Path(renders) if renders else Path(tempfile.mkdtemp())
    need = [n for n in harm + ([lead] if lead else []) if not (rd / f"{safe(n)}.wav").exists()]
    if need:
        hx("render", set_path, "--tracks", *need, "--out", rd)
    tracks = {v(t, "./Name/EffectiveName"): t for t in root.find(".//Tracks") if t.tag == "AudioTrack"}
    # which harmonies are the lower ones: median pitch over the track
    med = {}
    for n in harm:
        f = rd / f"{safe(n)}.wav"
        if f.exists():
            _, f0, _ = pitch.track(str(f), fmin=65, fmax=1000)
            ok = f0[np.isfinite(f0)]
            med[n] = float(np.median(ok)) if len(ok) else None
    ranked = sorted([n for n in med if med[n]], key=lambda n: med[n])
    lower = ranked[: max(1, len(ranked) // 2)]
    lead_audio = dsp.load(rd / f"{safe(lead)}.wav")[0] if lead and (rd / f"{safe(lead)}.wav").exists() else None
    fader = lambda t: 20 * math.log10(max(1e-6, float(v(t, "./DeviceChain/Mixer/Volume/Manual"))))
    out = []
    for n in lower:
        t = tracks.get(n)
        f = rd / f"{safe(n)}.wav"
        if t is None or not f.exists():
            continue
        y, sr = dsp.load(f)
        clips = []
        for c in t.findall(LANE):
            if v(c, "./Disabled") == "true":
                continue
            a, b = float(v(c, "./CurrentStart")), float(v(c, "./CurrentEnd"))
            seg = y[int(a * spb * sr):int(b * spb * sr)]
            if len(seg) < sr:
                continue
            lvl = dsp.active_lufs(seg, sr)
            if lvl <= -60:
                continue
            clips.append(dict(el=c, a=a, b=b, level=lvl + fader(t)))
        if len(clips) < 3:
            continue
        for k, cl in enumerate(clips):
            others = [x["level"] for j, x in enumerate(clips) if j != k]
            typical = float(np.median(others))
            gap = typical - cl["level"]
            if gap <= under:
                continue
            raise_db = min(gap, max_raise)
            note = ""
            if lead_audio is not None:
                ls = lead_audio[int(cl["a"] * spb * sr):int(cl["b"] * spb * sr)]
                ll = dsp.active_lufs(ls, sr) if len(ls) >= sr else -70.0
                if ll > -60:
                    ll += fader(tracks[lead]) if lead in tracks else 0.0
                    room = (ll - lead_margin) - cl["level"]
                    if room < raise_db:
                        raise_db, note = max(0.0, room), f" (held to {lead_margin:g} dB under the lead there)"
            if raise_db < 1.0:
                continue
            sv = float(v(cl["el"], "./SampleVolume") or 1.0)
            if 20 * math.log10(max(sv, 1e-6)) <= -10:      # turned down this far by hand: probably on purpose
                note += (f"; you set this clip's gain to {20 * math.log10(max(sv, 1e-6)):.0f} dB yourself, which looks "
                         "deliberate: ask before raising it")
            out.append(dict(track=n, clip=cl["el"].get("Id"), a=cl["a"], b=cl["b"], level=round(cl["level"], 1),
                            typical=round(typical, 1), raise_db=round(raise_db, 1), note=note,
                            new_gain=min(MAX_CLIP_GAIN, sv * 10 ** (raise_db / 20))))
    return out, dict(lower=lower, lead=lead)


def where(beat):
    return f"{int(beat // 4) + 1}.{int(beat % 4) + 1}"


def findings(props):
    return [dict(id=f"cliplevel-{i}", tool="cliplevel", kind="clip-too-low", severity="low", track=p["track"],
                 where=f"bar {where(p['a'])}",
                 problem=(f"this clip of a lower harmony sits {p['typical'] - p['level']:.1f} dB under the track's other "
                          f"clips (it {p['level']:+.1f}, they {p['typical']:+.1f}, as heard with the fader): the bottom of "
                          "the stack thins out here"),
                 fix=f"raise this clip's gain {p['raise_db']:+.1f} dB, to match the rest of the track{p['note']}. An option, "
                     "never applied unless approved; the harmony spacing rules still hold afterwards",
                 applies="set", clip=p["clip"], raise_db=p["raise_db"])
            for i, p in enumerate(props, 1)]


def main():
    ap = argparse.ArgumentParser(prog="hypnomix cliplevel", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("als"); ap.add_argument("--names"); ap.add_argument("--renders"); ap.add_argument("--json")
    ap.add_argument("--under", type=float, default=4.0); ap.add_argument("--max-raise", type=float, default=6.0)
    ap.add_argument("--lead-margin", type=float, default=1.5)
    ap.add_argument("--apply", metavar="NEW.als"); ap.add_argument("--ids")
    a = ap.parse_args()
    src = Path(a.als)
    props, meta = propose(src, a.names, a.renders, a.under, a.max_raise, a.lead_margin)
    fs = findings(props)
    print(f"{src.name}: lower harmonies {', '.join(meta.get('lower', [])) or '-'}; {len(fs)} clip(s) sitting too low")
    for f in fs:
        print(f"  {f['id']:<13} {f['track']:<22} {f['where']:<8} {f['fix'].split('. An option')[0]}")
    if a.json:
        Path(a.json).write_text(json.dumps({"tool": "cliplevel", "set": str(src), "findings": fs}, indent=1))
    if a.apply:
        if Path(a.apply).resolve() == src.resolve():
            sys.exit("refusing to overwrite the set; give a new file name")
        if Path(a.apply).resolve().parent != src.resolve().parent:
            sys.exit(f"write the new set in the same folder as the original ({src.resolve().parent})")
        want = {x.strip() for x in (a.ids or "").split(",") if x.strip()}
        if not want:
            sys.exit("say which clips: --ids cliplevel-1,… (none is raised by default)")
        root = ET.fromstring(gzip.open(src).read())
        tracks = {v(t, "./Name/EffectiveName"): t for t in root.find(".//Tracks") if t.tag == "AudioTrack"}
        done = 0
        for f, p in zip(fs, props):
            if f["id"] not in want:
                continue
            c = next((x for x in tracks[p["track"]].findall(LANE) if x.get("Id") == p["clip"]), None)
            if c is not None and c.find("./SampleVolume") is not None:
                c.find("./SampleVolume").set("Value", repr(p["new_gain"]))
                done += 1
        data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")
        with gzip.open(a.apply, "wb") as fh:
            fh.write(data)
        print(f"wrote {a.apply}: {done} clip(s) raised")


if __name__ == "__main__":
    main()
