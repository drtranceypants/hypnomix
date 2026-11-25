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
