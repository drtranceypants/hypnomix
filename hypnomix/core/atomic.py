"""Files that are never left half written, and the one place caches live.

A scan folder holds the person's decisions: a crash in the middle of a plain `write_text` leaves a cut-off
decisions.json, and the song then disappears from the app. These helpers write the new text to a temporary file
in the same folder, flush it to disk, and only then swap it in (`os.replace` is all-or-nothing). The version that
was there before is kept next to it as "<name>.bak".

    write_json(path, data)          decisions.json, findings.json, scan.json
    write_text(path, text)          any other small file
    append_text(path, text)         a log (fix-log.md): the old text plus the new, swapped in whole
    load_json(path, default)        reads it; if the file is cut off, falls back to the .bak with a warning

    cache_root()                    where caches live: <hypnomix home>/cache (HYPNOMIX_HOME decides the home)
"""
import json
import os
import shutil
import sys
import threading
from pathlib import Path

BAK = ".bak"


def _tmp(p):
    return p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")


def _sync_dir(folder):
    try:                                    # make the rename itself survive a power cut (POSIX; ignored elsewhere)
        fd = os.open(str(folder), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _drop(p):
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass


def _parses(p):
    try:
        json.loads(Path(p).read_text(encoding="utf-8"))
        return True
    except (OSError, ValueError):
        return False


def write_text(path, text, backup=True, only_if_json=False):
    """Write `text` to `path` whole or not at all. The file that was there is kept as "<name>.bak" (when
    `only_if_json`, only if it still parses as JSON, so a cut-off file never replaces a good backup)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp(p)
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if backup and p.is_file() and p.stat().st_size and (not only_if_json or _parses(p)):
            bak = p.with_name(p.name + BAK)
            btmp = _tmp(bak)
            try:
                shutil.copyfile(p, btmp)
                os.replace(btmp, bak)
            finally:
                _drop(btmp)
        os.replace(tmp, p)
        _sync_dir(p.parent)
    finally:
        _drop(tmp)
    return p


def write_json(path, data, indent=1, **kw):
    """`json.dumps` into `write_text`, keeping the last good version as "<name>.bak"."""
    return write_text(path, json.dumps(data, indent=indent, **kw), only_if_json=True)


def append_text(path, text):
    """Add `text` to the end of a log: the old text plus the new is swapped in whole (nothing is cut off)."""
    p = Path(path)
    old = p.read_text(encoding="utf-8") if p.is_file() else ""
    return write_text(p, old + text, backup=False)


def load_json(path, default=None, warn=True):
    """The parsed file; `default` if there is none. A file that cannot be read (cut off by a crash) falls back to
    its "<name>.bak" with a warning on stderr; with no usable backup the bad file is kept as "<name>.corrupt",
    a warning says so, and `default` is returned so the tool can still run."""
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        why = f"{p.name} could not be read ({e.__class__.__name__})"
    bak = p.with_name(p.name + BAK)
    try:
        d = json.loads(bak.read_text(encoding="utf-8"))
        if warn:
            print(f"warning: {why}; using the previous copy {bak.name}", file=sys.stderr)
        return d
    except (OSError, ValueError):
        pass
    try:
        shutil.copyfile(p, p.with_name(p.name + ".corrupt"))
    except OSError:
        pass
    if warn:
        print(f"warning: {why} and there is no usable backup; the broken file is kept as {p.name}.corrupt",
              file=sys.stderr)
    return default


def cache_root():
    """<hypnomix home>/cache. The home is HYPNOMIX_HOME when it is set (read now, so a test or a second
    instance can set it after import), else the same default as hypnomix.core.paths."""
    env = os.environ.get("HYPNOMIX_HOME")
    if env:
        home = Path(env).expanduser()
    else:
        from hypnomix.core import paths
        home = paths.HOME
    return home / "cache"
