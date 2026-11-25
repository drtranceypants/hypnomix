"""Song projects from any supported DAW, as one model (see `model.py`).

    from hypnomix import project
    p = project.load("Song.rpp")      # or "Song.als"
    for t in p.audio_tracks():
        y = p.render(t)               # mono float, from 0 s

Supported: REAPER (.rpp) and Ableton Live (.als).
"""
from pathlib import Path

SUFFIXES = {".rpp": "reaper", ".als": "live"}


def daw_of(path):
    return SUFFIXES.get(Path(path).suffix.lower())


def load(path):
    kind = daw_of(path)
    if kind == "reaper":
        from hypnomix.project import reaper
        return reaper.read(path)
    if kind == "live":
        from hypnomix.project import als
        return als.read(path)
    raise SystemExit(f"{Path(path).name}: not a project hypnomix can read (use a .rpp or .als)")
