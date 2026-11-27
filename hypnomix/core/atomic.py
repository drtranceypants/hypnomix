"""Files that are never left half written, and the one place caches live.

A scan folder holds the person's decisions: a crash in the middle of a plain `write_text` leaves a cut-off
decisions.json, and the song then disappears from the app. These helpers write the new text to a temporary file
in the same folder, flush it to disk, and only then swap it in (`os.replace` is all-or-nothing). The version that
was there before is kept next to it as "<name>.bak".

    replace(src, dst)               os.replace that tries again for a moment on Windows when another program holds dst open
    write_json(path, data)          decisions.json, findings.json, scan.json
    write_text(path, text)          any other small file
    append_text(path, text)         a log (fix-log.md): the old text plus the new, swapped in whole
    load_json(path, default)        reads it; if the file is cut off, falls back to the .bak with a warning
    decisions_lock(folder)          one writer of a scan folder's decisions.json at a time, across programs
                                    (every read-then-write of that file happens inside it; it can be nested)

    cache_root()                    where caches live: <HypnoMix home>/cache (HYPNOMIX_HOME decides the home)
"""
import contextlib
import errno
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

BAK = ".bak"
RETRIES = 6                 # Windows only: about a third of a second in all (0.01 s, doubling)


def _windows():
    return sys.platform == "win32"


def replace(src, dst):
    """`os.replace`, and on Windows a few quick tries again when the target is held open for a moment by another program (a
    reader, a virus scanner, a search indexer). Still refused after that: PermissionError whose text says what to do."""
    delay = 0.01
    for n in range(RETRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            if not _windows():
                raise
            if n == RETRIES - 1:
                raise PermissionError(errno.EACCES, "it is open in another program; close it and try again", str(dst)) from e
            time.sleep(delay)
            delay *= 2


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
                replace(btmp, bak)
            finally:
                _drop(btmp)
        replace(tmp, p)
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


_DEC_GUARD = threading.Lock()
_DEC_LOCKS = {}             # folder -> (RLock, [depth]): a thread that holds the lock may take it again


@contextlib.contextmanager
def decisions_lock(sd):
    """One writer of a scan folder's decisions.json at a time: the app's threads, `hypnomix fix --decide` in another
    program, an agent beside the review page. Every read-then-write of that file (and the whole-file writes of a
    re-scan or a restore) happens inside it. It can be taken again by the thread that holds it (the app's record
    functions call each other). If the folder cannot hold the lock file, the threads of this program are still kept
    in line and the write itself says what is wrong with the folder."""
    folder = Path(sd)
    key = str(folder.resolve())             # one lock for every spelling of the folder (a link, a relative path)
    with _DEC_GUARD:
        lock, depth = _DEC_LOCKS.setdefault(key, (threading.RLock(), [0]))
    with lock:
        if depth[0]:
            depth[0] += 1
            try:
                yield
            finally:
                depth[0] -= 1
            return
        fh = None
        try:
            fh = open(folder / "decisions.json.lock", "a+", encoding="utf-8")
            try:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_EX)
            except ImportError:                       # Windows
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        except OSError:
            if fh is not None:
                fh.close()
            fh = None
        depth[0] = 1
        try:
            yield
        finally:
            depth[0] = 0
            if fh is not None:
                fh.close()                            # closing the file releases the lock


def cache_root():
    """<HypnoMix home>/cache. The home is HYPNOMIX_HOME when it is set (read now, so a test or a second
    instance can set it after import), else the same default as hypnomix.core.paths."""
    env = os.environ.get("HYPNOMIX_HOME")
    if env:
        home = Path(env).expanduser()
    else:
        from hypnomix.core import paths
        home = paths.HOME
    return home / "cache"
