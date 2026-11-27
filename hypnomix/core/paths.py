"""Where HypnoMix writes things. Override with HYPNOMIX_OUT / HYPNOMIX_HOME."""
import os
import sys
from pathlib import Path

OUT = Path(os.environ.get("HYPNOMIX_OUT", "hypnomix-out")).expanduser()          # reports, captures (relative to cwd)
HOME = Path(os.environ.get("HYPNOMIX_HOME", "~/.hypnomix")).expanduser()          # your profile lives here
PROFILE = HOME / "profile.json"


def out(*parts):
    p = OUT.joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


def out_at(custom, *parts):
    """--out if given (created), else hypnomix-out/<parts>."""
    if custom:
        p = Path(custom).expanduser()
        make_dir(p)
        return p
    return out(*parts)


def _cannot_write(p, why):
    print(f"can't write to '{p}': {why}; choose another place with --out", file=sys.stderr)
    sys.exit(2)


def check_out(custom):
    """Before the slow part of a command: end with one plain sentence and exit code 2 (1 is a failed check in some
    commands) when `--out` (a folder, or a file to be written) cannot be written, instead of a traceback after the
    analysis has run. Creates nothing. No --out given: nothing to check (the default folder is made when needed)."""
    if not custom:
        return
    p = Path(custom).expanduser()
    q = p
    while not q.exists() and q != q.parent:
        q = q.parent
    if q != p and not q.is_dir():
        _cannot_write(p, "part of that path is a file, not a folder")
    if not os.access(q, os.W_OK | (os.X_OK if q.is_dir() else 0)):
        _cannot_write(p, "permission denied")


def make_dir(p):
    """Make the folder (and the ones above it). One it cannot make or write into ends the command with one plain
    sentence and exit code 2, no traceback."""
    p = Path(p)
    check_out(p)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _cannot_write(p, (e.strerror or str(e)).lower())


def _is_home_or_above(d):
    """True for the user's home folder and every folder above it: those are never ours to tighten."""
    try:
        home, d = Path.home().resolve(), Path(d).resolve()
    except (OSError, RuntimeError):
        return False
    return d == home or d in home.parents


def private_dir(d):
    """Make the folder if needed, readable by you alone (0700). Folders that have to be made on the way are 0700 too,
    made from the top down. A folder that already exists and is yours is tightened to 0700; one owned by someone else
    is left as it is, and so is your home folder or anything above it (a mistaken setting never locks you out).
    Everything that reads these folders (the REAPER bridge, the Max devices, the app) runs as you, so nothing else
    needs access. No effect on Windows."""
    d = Path(d).expanduser()
    if not d.is_absolute():
        d = Path.cwd() / d
    for p in reversed([d, *d.parents]):                          # top down, so each made folder gets 0700 itself
        if not p.exists():
            try:
                p.mkdir(mode=0o755 if _is_home_or_above(p) else 0o700)
            except FileExistsError:
                pass
    try:
        if (hasattr(os, "getuid") and d.stat().st_uid == os.getuid() and (d.stat().st_mode & 0o777) != 0o700
                and not _is_home_or_above(d)):
            d.chmod(0o700)
    except OSError:
        pass
    return d


def write_private(path, text, mode=0o600, encoding="utf-8"):
    """Write a small file of HypnoMix's own (state, settings, helper scripts) readable by you alone (default 0600), in
    a folder made private by private_dir(). An existing file with a looser mode is tightened too."""
    p = Path(path).expanduser()
    private_dir(p.parent)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
    finally:
        try:
            os.chmod(p, mode)
        except OSError:
            pass
    return p


def tighten_home():
    """At app start: the HypnoMix home folder (~/.hypnomix) is made 0700 if it exists and is yours. Not done when
    HYPNOMIX_HOME points at your own home folder or above it, so a mistaken setting never locks you out of something."""
    try:
        if HOME.is_dir() and HOME != Path.home() and HOME not in Path.home().parents:
            private_dir(HOME)
    except OSError:
        pass
