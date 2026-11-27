"""Read an AAF file into the import model (hypnomix.project.importer).

AAF is what many DAWs and video editors can export for moving a project elsewhere (look for File > Export > AAF, or
Project / Timeline as AAF). It is read by the engine's AAF reader (hypnomix-aafdump, which comes with the HypnoMix
DAW add-on, for Apple-silicon Macs only so far; without it this cannot run). Audio embedded in the AAF is extracted;
audio it only points to is looked for next to the AAF (keep the exported media folder beside it).

What is carried: tracks (name, order, fader, pan, mute, solo where the AAF has them), clips (position, start in the
file, length, clip gain, gain envelope, fades as straight fades, muted clips) and markers. AAF has no tempo or
plug-ins: the session is at 120 BPM (audio sits at its exact time), and the report says so.
"""
import tempfile
from pathlib import Path

from hypnomix.project import engine_tools

def product(name):
    """The program that wrote the AAF, as the file names it (read from the file, never from a list here)."""
    return (name or "").strip() or "an AAF export"


def _value(g, default=1.0):
    return float(g["value"]) if isinstance(g, dict) and "value" in g else default


def read(path, media_dir=None):
    """`media_dir`: where audio embedded in the AAF is extracted to (a temporary folder by default; the writer copies
    it into the session, so it can go afterwards)."""
    path = Path(path).expanduser().resolve()
    media = Path(media_dir) if media_dir else Path(tempfile.mkdtemp(prefix="hypnomix-aaf-"))
    media.mkdir(parents=True, exist_ok=True)
    data = engine_tools.run("hypnomix-aafdump", path, media, watch=media)
    rate = int(data.get("rate") or 48000)
    daw = product(data.get("product"))
    from hypnomix.project.importer import Budget
    budget = Budget(path.name)
    tracks, not_carried, shapes, empty = [], [], 0, 0
    for t in data.get("tracks", []):
        budget.add(tracks=1)
        name = t.get("name") or f"Audio {t.get('number', len(tracks) + 1)}"
        tr = dict(name=name, kind="audio", volume=_value(t.get("gain")), muted=bool(t.get("mute")),
                  solo=bool(t.get("solo")), regions=[], midi=[], notes=[])
        pan = t.get("pan")
        if isinstance(pan, dict) and "value" in pan:
            tr["pan"] = max(-1.0, min(1.0, float(pan["value"]) * 2 - 1))
        elif isinstance(pan, dict):
            tr["notes"].append("pan automation (not carried; the pan is centred)")
        if isinstance(t.get("gain"), dict) and "points" in t["gain"]:
            tr["notes"].append("fader automation (not carried)")
        for c in t.get("clips", []):
            length = c.get("length", 0) / rate
            if length <= 0:
                empty += 1
                continue
            budget.add(regions=1)
            files = [f for f in c.get("files", [])]
            reg = dict(name=c.get("name") or (files[0].get("name") if files else "") or "clip",
                       position=c.get("position", 0) / rate, start=c.get("offset", 0) / rate, length=length,
                       muted=bool(c.get("mute")), gain=_value(c.get("gain")))
            # one entry per channel: entries of one file are that file's channels; different files, one per channel
            by_path = {}
            for f in files:
                by_path.setdefault(f.get("path"), []).append(int(f.get("channel") or 0))
            if len(by_path) > 1:                          # one entry per file: each file's own channel, or all of it
                reg["files"] = [Path(f["path"]) if f.get("path") else None for f in files]
                reg["file_channels"] = [int(f.get("channel") or 0) - 1 if f.get("channel") else None for f in files]
            else:
                x, chans = next(iter(by_path.items())) if by_path else (None, [])
                reg["file"] = Path(x) if x else None
                if chans and all(chans):
                    reg["channels"] = [ch - 1 for ch in chans]      # AAF counts channels from 1 (0 = all of them)
            env = c.get("envelope")
            if isinstance(env, dict) and env.get("points"):
                reg["envelope"] = [(float(x) * length, float(v)) for x, v in env["points"]]
            elif isinstance(c.get("gain"), dict) and c["gain"].get("points"):
                reg["envelope"] = [(float(x) * length, float(v)) for x, v in c["gain"]["points"]]
                reg["gain"] = 1.0
            for k in ("fade_in", "fade_out"):
                if c.get(k):
                    reg[k] = c[k]["length"] / rate
                    shapes += c[k].get("shape") not in ("linear", "none", None)
            tr["regions"].append(reg)
        tracks.append(tr)
    if empty:
        not_carried.append(f"{empty} clip(s) of zero length: not carried")
    if shapes:
        not_carried.append(f"{shapes} fade(s) with a curved shape: written as straight fades of the same length")
    not_carried += ["tempo and meter: an AAF has none (the session is at 120 BPM 4/4; audio sits at its exact time)",
                    "plug-ins, sends, buses and MIDI: an AAF carries audio clips only",
                    f"the timecode the {daw} timeline starts at: the first clip time is counted from the timeline's start"]
    markers = [dict(name=m.get("name") or "marker", time=m.get("start", 0) / rate,
                    end=(m["start"] + m["length"]) / rate if m.get("length") else None) for m in data.get("markers", [])]
    return dict(name=data.get("name") or path.stem, source=path, daw=f"{daw} (AAF)", rate=rate, bpm=120.0, tempo=[],
                num=4, den=4, markers=markers, tracks=tracks, not_carried=not_carried, warnings=[], media_dir=media,
                tempo_assumed=True, roots=[media])
