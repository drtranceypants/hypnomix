"""Song projects from any supported DAW, as one model (see `model.py`).

    from hypnomix import project
    p = project.load("Song.rpp")      # or "Song.als", "Song.ardour" (or the Ardour session folder)
    for t in p.audio_tracks():
        y = p.render(t)               # mono float, from 0 s

Supported: REAPER (.rpp), Ardour (.ardour) and Ableton Live (.als).
"""
from pathlib import Path

SUFFIXES = {".rpp": "reaper", ".als": "live", ".ardour": "ardour"}
NAMES = {"reaper": "REAPER", "live": "Live", "ardour": "Ardour"}


def ardour_session(path):
    """An Ardour session folder -> its .ardour file (None when the folder is not one)."""
    p = Path(path)
    if not p.is_dir():
        return None
    own = p / f"{p.name}.ardour"
    if own.exists():
        return own
    found = sorted(x for x in p.glob("*.ardour"))
    return found[0] if len(found) == 1 else None


def daw_of(path):
    if ardour_session(path) is not None:
        return "ardour"
    return SUFFIXES.get(Path(path).suffix.lower())


def load(path):
    kind = daw_of(path)
    if kind == "reaper":
        from hypnomix.project import reaper
        return reaper.read(path)
    if kind == "ardour":
        from hypnomix.project import ardour
        return ardour.read(ardour_session(path) or path)
    if kind == "live":
        from hypnomix.project import als
        return als.read(path)
    raise SystemExit(f"{Path(path).name}: not a project hypnomix can read (use a .rpp, .ardour or .als)")
