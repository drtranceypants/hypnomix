"""The take files under a track's clips, and pointing clips at a processed copy of a take.

Used where a fix has to change the AUDIO of a vocal (pitch correction): the take's source file is processed into a
new file of the same length (Samples/Tuned/…), and in a NEW set the comp clips that play that take are pointed at
it. The comp itself stays as it was: every clip's position, edges, fades, warp markers, gain and envelopes are
untouched, so the vocal still plays the person's own comp natively in Live. No rendered copy of the track is made.
"""
import os
from pathlib import Path

from hypnomix.session.render import clip_source, v

LANE = "./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events"


def find_track(root, name):
    return next((t for t in root.find(".//Tracks") if t.tag == "AudioTrack" and v(t, "./Name/EffectiveName") == name), None)


def track_sources(root, name, als):
    """{source file: [clips]} for the enabled arrangement clips of track `name`."""
    t = find_track(root, name)
    lane = t.find(LANE) if t is not None else None
    out = {}
    for c in (list(lane) if lane is not None else []):
        if c.tag != "AudioClip" or v(c, "./Disabled") == "true":
            continue
        out.setdefault(Path(clip_source(c, als, None)).resolve(), []).append(c)
    return out


def _set(el, path, val):
    n = el.find(path)
    if n is not None:
        n.set("Value", str(val))


def repoint(clips, new_file, project_dir):
    """Point these clips at `new_file` (same length and rate as the take it replaces)."""
    new_file = Path(new_file).resolve()
    for c in clips:
        fr = c.find("./SampleRef/FileRef")
        if fr is None:
            continue
        _set(fr, "./Path", str(new_file))
        try:
            rel = os.path.relpath(new_file, Path(project_dir).resolve())
        except ValueError:
            rel = str(new_file)
        _set(fr, "./RelativePath", rel.replace(os.sep, "/"))
        _set(fr, "./OriginalFileSize", new_file.stat().st_size)
        _set(fr, "./OriginalCrc", 0)
        _set(c, "./SampleRef/LastModDate", int(new_file.stat().st_mtime))
    return len(clips)


def song_spans(clip, tempo, step_s=0.25):
    """[(song_t0, song_t1, src_t0, src_t1)] in seconds: where this arrangement clip plays which part of its take.
    Warped clips follow their warp markers (cut into `step_s` pieces); unwarped clips map one to one."""
    import numpy as np
    bps = tempo / 60.0
    f = lambda path, d=0.0: float(v(clip, path) or d)
    cs, ce, ls, sr_ = f("./CurrentStart"), f("./CurrentEnd"), f("./Loop/LoopStart"), f("./Loop/StartRelative")
    if v(clip, "./IsWarped") != "true":
        r0 = ls + sr_
        return [(cs / bps, ce / bps, r0, r0 + (ce - cs) / bps)]
    wm = sorted((float(m.get("BeatTime")), float(m.get("SecTime"))) for m in clip.iter("WarpMarker"))
    if len(wm) < 2:
        r0 = (ls + sr_) / bps
        return [(cs / bps, ce / bps, r0, r0 + (ce - cs) / bps)]
    mb, ms = np.array([b for b, _ in wm]), np.array([x for _, x in wm])

    def src(beat_in_clip):
        b = ls + sr_ + beat_in_clip
        if b < mb[0]:
            return ms[0] + (b - mb[0]) * (ms[1] - ms[0]) / (mb[1] - mb[0])
        if b > mb[-1]:
            return ms[-1] + (b - mb[-1]) * (ms[-1] - ms[-2]) / (mb[-1] - mb[-2])
        return float(np.interp(b, mb, ms))
    out, t = [], cs / bps
    while t < ce / bps - 1e-6:
        t1 = min(ce / bps, t + step_s)
        out.append((t, t1, src(t * bps - cs), src(t1 * bps - cs)))
        t = t1
    return out
