"""Read an Ableton Live set (.als) into the shared model (`model.Project`).

Positions are converted from beats to seconds at the set's tempo (a constant tempo, as the rest of HypnoMix
assumes for Live). Rendering is delegated to `hypnomix.session.render.render_track`, the renderer every Live
tool already uses, so a track renders identically through the model and through `hypnomix render`.
"""
import gzip
from hypnomix.core.gz import read_gz
import xml.etree.ElementTree as ET
from pathlib import Path

from hypnomix.project.model import Clip, Device, Project, Take, Track

KIND = {"AudioTrack": "audio", "MidiTrack": "midi", "GroupTrack": "folder", "ReturnTrack": "return"}
NOT_DEVICES = {"On", "LomId", "LomIdView", "IsExpanded", "ParametersListWrapper", "Pointee", "UserName"}


def _v(el, path, cast=str, default=None):
    e = el.find(path) if el is not None else None
    if e is None or e.get("Value") is None:
        return default
    try:
        return cast(e.get("Value"))
    except ValueError:
        return default


def _bool(x):
    return x == "true"


def read(path):
    from hypnomix.session import automation as aa
    from hypnomix.session import smooth as S
    from hypnomix.session.render import render_track

    path = Path(path).expanduser().resolve()
    root = ET.fromstring(read_gz(path))
    from hypnomix.session import liveversion as LV
    LV.warn_read(root)                           # a set from a newer Live: one warning line, never a refusal
    tempo = _v(root, ".//Tempo/Manual", float, 120.0)
    bpb = _v(root, ".//TimeSignatures/RemoteableTimeSignature/Numerator", int, 4)
    spb = 60.0 / tempo
    proj = Project(path=path, daw="live", tempo=tempo, beats_per_bar=bpb, native=root)
    proj.warnings = []
    by_id = {}
    for i, t in enumerate(root.find(".//Tracks")):
        name = _v(t, "./Name/EffectiveName", str, f"Track {i + 1}")
        clips = []
        for c in t.iter("AudioClip"):
            if c.find("./CurrentStart") is None:
                continue
            ci = S.clip_info(c, path.parent, tempo)
            take = Take(name=ci["name"], path=ci["path"], gain=ci["gain"], kind="audio", native=c)
            clips.append(Clip(name=ci["name"], start=ci["start"] * spb, length=(ci["end"] - ci["start"]) * spb,
                              takes=[take], gain=1.0, loop=ci["loop_on"], fade_in=ci["fade_in"] * spb,
                              fade_out=ci["fade_out"] * spb, muted=ci["disabled"],
                              stretch_markers=max(0, len(ci["markers"]) - 2) if ci["warped"] else 0, native=c))
        for c in t.iter("MidiClip"):
            s, e = _v(c, "./CurrentStart", float), _v(c, "./CurrentEnd", float)
            if s is None or e is None:
                continue
            clips.append(Clip(name=_v(c, "./Name", str, ""), start=s * spb, length=(e - s) * spb,
                              takes=[Take(name="", kind="midi", native=c)],
                              muted=_v(c, "./Disabled", _bool, False), native=c))
        devs = []
        chain = t.find("./DeviceChain/DeviceChain/Devices")
        for d in (list(chain) if chain is not None else []):
            label = _v(d, "./UserName", str, "") or _v(d, "./PluginDesc//PlugName", str, "") or d.tag
            devs.append(Device(name=label, kind="Live" if d.tag not in ("PluginDevice", "AuPluginDevice") else "Plug-in",
                               on=_v(d, "./On/Manual", _bool, True), native=d))
        envs = {}
        if t.find("./DeviceChain/Mixer") is not None:
            for lab, env, _ in aa.envelopes(t)[0]:
                ev = env.find("./Automation/Events")
                pts = [(float(e.get("Time")) * spb, float(e.get("Value"))) for e in (ev if ev is not None else [])
                       if e.get("Value") is not None and float(e.get("Time")) > -1e6]
                if pts:
                    envs[lab] = pts
        tr = Track(name=name, index=i, kind=KIND.get(t.tag, "audio"), clips=clips, devices=devs, envelopes=envs,
                   volume=_v(t, "./DeviceChain/Mixer/Volume/Manual", float, 1.0),
                   pan=_v(t, "./DeviceChain/Mixer/Pan/Manual", float, 0.0),
                   muted=not S.track_on(t), solo=_v(t, "./DeviceChain/Mixer/Solo/Manual", _bool, False) or False,
                   native=t)
        tr.group_id = _v(t, "./TrackGroupId", str, "-1")
        by_id[t.get("Id")] = tr
        proj.tracks.append(tr)
    for tr in proj.tracks:
        tr.parent = by_id.get(tr.group_id)

    def renderer(track, N, sr, warn):
        if track.kind != "audio":
            import numpy as np
            return np.zeros(N)
        return render_track(track.native, str(path), spb, N, sr, None, 0, warn)

    proj.renderer = renderer
    return proj
