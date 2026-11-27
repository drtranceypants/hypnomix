"""Song projects from any supported DAW, as one model (see `model.py`).

    from hypnomix import project
    p = project.load("Song.rpp")      # or "Song.als", "Song.ardour" (or the Ardour session folder)
    for t in p.audio_tracks():
        y = p.render(t)               # mono float, from 0 s

Supported: REAPER (.rpp), Ardour (.ardour) and Ableton Live (.als).
"""
from pathlib import Path

SUFFIXES = {".rpp": "reaper", ".als": "live", ".ardour": "ardour"}
NAMES = {"reaper": "REAPER", "live": "Live", "ardour": "HypnoMix DAW"}


def ardour_session(path):
    """An Ardour session folder -> its .ardour file (None when the folder is not one): the one named like the folder, or the
    only one, or, with several snapshots and none named like the folder (a renamed session), the newest
    (`ardour_alternatives` lists the others so a command can say which one it took)."""
    p = Path(path)
    if not p.is_dir():
        return None
    own = p / f"{p.name}.ardour"
    if own.exists():
        return own
    found = sorted(x for x in p.glob("*.ardour") if x.is_file() and not x.name.startswith("."))
    if len(found) > 1:
        return max(found, key=lambda x: (x.stat().st_mtime, x.name))
    return found[0] if found else None


def ardour_alternatives(path):
    """The other .ardour files in a session folder when `ardour_session` had to choose between several, else []."""
    p = Path(path)
    if not p.is_dir() or (p / f"{p.name}.ardour").exists():
        return []
    found = sorted(x for x in p.glob("*.ardour") if x.is_file() and not x.name.startswith("."))
    chosen = ardour_session(p)
    return [x for x in found if x != chosen] if len(found) > 1 else []


def daw_of(path):
    if ardour_session(path) is not None:
        return "ardour"
    return SUFFIXES.get(Path(path).suffix.lower())


class ProjectReadError(ValueError):
    """A file that is not (or no longer) a project of the kind its name says. `str(e)` is one plain sentence that starts
    with "not a readable ..." (the command line prints it after the file name, `e.name`, and exits with code 2, no traceback)."""

    def __init__(self, name, kind):
        what = {"reaper": "a REAPER project", "ardour": "a HypnoMix DAW session", "live": "a Live set"}.get(kind, "a project")
        app = NAMES.get(kind, "its program")
        super().__init__(f"not a readable {what[2:]}: the file is empty, damaged or another kind of file; open it in "
                         f"{app} to check it, or give another")
        self.name = name


def unreadable_errors():
    """What a reader raises for a damaged or wrong file (not for a missing file or a permission problem)."""
    import gzip, zlib
    return (ValueError, SyntaxError, EOFError, zlib.error, gzip.BadGzipFile)


def load(path):
    kind = daw_of(path)
    if kind is None:
        raise SystemExit(f"{Path(path).name}: not a project HypnoMix can read (use a .rpp, .ardour or .als)")
    try:
        if kind == "reaper":
            from hypnomix.project import reaper
            return reaper.read(path)
        if kind == "ardour":
            from hypnomix.project import ardour
            return ardour.read(ardour_session(path) or path)
        from hypnomix.project import als
        return als.read(path)
    except unreadable_errors() as e:
        if isinstance(e, ProjectReadError):
            raise
        raise ProjectReadError(Path(path).name, kind) from e
