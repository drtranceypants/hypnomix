"""Temporary folders: one way to make them, so none is ever left behind and all can be found.

A command that renders a whole set (`devices`, `duck`, `cliplevel`, `tidy`, `alignset`) needs somewhere to put the
audio for a moment. That place used to be the system temp folder, under a name like "tmpwack_btj", and nothing ever
removed it: a 60-track, five-minute set left about 3 GB behind on every run. Now:

    with tmp.workdir("render") as rd:      # a folder that is removed when the block ends, even on an error or Ctrl-C
        ...

  * The name starts with "hypnomix-" (hypnomix-render-k3j2h1g0), so a person can find it, and Disk care can tell it
    from someone else's folder. A folder inside it called .hypnomix-tmp says who made it and when.
  * A big one (the default) is made under the HypnoMix home, in cache/tmp, because the system temp folder is often
    on the small start-up disk. A small one (`big=False`) goes in the system temp folder.
  * It is removed when the block ends: normally, on an error, on Ctrl-C and on "kill" (SIGTERM). If the computer
    loses power or the process is killed outright, the folder stays: Disk care removes the ones older than a day.
  * When a command is about to write more than about 1 GB there, it says so first, in one plain line on stderr:
    how much, where, and how much room is left.

`own_folders()` lists the folders made this way (for Disk care); `looks_like_old_render()` recognises, by name and
content only, the folders older versions left behind. That is a guess, so Disk care only OFFERS those.
"""
import contextlib
import os
import re
import shutil
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path

PREFIX = "hypnomix-"
KINDS = ("render", "work", "tidy", "alignset", "ab")          # what comes after the prefix: hypnomix-<kind>-<8 random>
MARKER = ".hypnomix-tmp"
BIG_BYTES = 1_000_000_000                                      # more than this: say so before writing it
SUFFIX = r"[A-Za-z0-9_]{8}"                                    # what tempfile.mkdtemp adds
OWN = re.compile(r"^hypnomix-(?:%s)-%s$" % ("|".join(KINDS), SUFFIX))
OLD_RENDER = re.compile(r"^tmp%s$" % SUFFIX)                  # tempfile.mkdtemp() with no prefix: older versions
OLD_TIDY = re.compile(r"^tidy-%s$" % SUFFIX)                  # older tidy


def base_dir():
    """Where big temporary folders go: <HypnoMix home>/cache/tmp (HYPNOMIX_HOME read now, like the other caches)."""
    from hypnomix.core.atomic import cache_root
    return cache_root() / "tmp"


def system_dir():
    return Path(tempfile.gettempdir())


def _free(p):
    try:
        q = Path(p)
        while not q.exists() and q != q.parent:
            q = q.parent
        return shutil.disk_usage(str(q)).free
    except OSError:
        return None


def gb(n):
    return f"{n / 1e9:.1f} GB" if n >= 1e8 else f"{n / 1e6:.0f} MB"


def announce(nbytes, where, what="temporary audio", out=None):
    """One plain line when `nbytes` is over about 1 GB: how much, where, that it is removed afterwards, and the room
    left. Returns the line (also when nothing is printed, it returns None)."""
    if not nbytes or nbytes <= BIG_BYTES:
        return None
    free = _free(where)
    line = (f"HypnoMix: about {gb(nbytes)} of {what} will be written to {where} and removed when this command ends"
            + (f" ({gb(free)} free there)" if free is not None else "") + ".")
    print(line, file=out or sys.stderr, flush=True)
    return line


def render_bytes(root, n_tracks, sr=44100):
    """About how many bytes `hypnomix render` writes for n_tracks audio tracks of this set (32-bit float, mono, from bar 1
    to the end of the song and 8 beats more). 0 when it cannot tell."""
    try:
        from hypnomix.session import render as R
        tempo = float(R.v(root, ".//Tempo/Manual"))
        end, _ = R.song_end(root)
        return int(n_tracks * (end + 8) * (60.0 / tempo) * sr * 4)
    except Exception:
        return 0


def make(kind="work", big=False, parent=None):
    """A new empty folder named hypnomix-<kind>-XXXXXXXX with the marker inside. The caller removes it (see `remove`);
    most callers want `workdir`. A big one that cannot be made under the HypnoMix home goes in the system temp folder."""
    assert kind in KINDS, kind
    where = Path(parent) if parent else None
    if where is None and big:
        where = base_dir()
    if where is not None:
        try:
            from hypnomix.core.paths import private_dir
            private_dir(where)
        except OSError:
            where = None
    try:
        p = Path(tempfile.mkdtemp(prefix=f"{PREFIX}{kind}-", dir=str(where) if where else None))
    except OSError:
        p = Path(tempfile.mkdtemp(prefix=f"{PREFIX}{kind}-"))
    try:
        (p / MARKER).write_text(f"made by HypnoMix (pid {os.getpid()}) at {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
                                encoding="utf-8")
    except OSError:
        pass
    return p


def remove(path):
    """Remove a folder made by `make` (never raises; a file still held open on Windows is tried again by Disk care)."""
    if path:
        shutil.rmtree(str(path), ignore_errors=True)


@contextlib.contextmanager
def terminate_cleans():
    """While the block runs, "kill PID" (SIGTERM) ends the program the ordinary way, so `finally` blocks run. Only from
    the main thread, and only when nobody has set their own handler."""
    mine = False
    try:
        if (threading.current_thread() is threading.main_thread() and hasattr(signal, "SIGTERM")
                and signal.getsignal(signal.SIGTERM) == signal.SIG_DFL):
            signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(143))
            mine = True
    except (ValueError, OSError):
        mine = False
    try:
        yield
    finally:
        if mine:
            try:
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
            except (ValueError, OSError):
                pass


@contextlib.contextmanager
def workdir(kind="render", big=True, expect_bytes=0, what="temporary audio"):
    """A temporary folder for the length of the block, removed afterwards whatever happens. `expect_bytes` is what the
    block is about to write there: over about 1 GB it is announced on stderr first."""
    p = make(kind, big=big)
    try:
        with terminate_cleans():
            announce(expect_bytes, p, what)
            yield p
    finally:
        remove(p)


_SCOPES = threading.local()


@contextlib.contextmanager
def scope():
    """For a long function that makes its scratch folder part-way down (`scratch`) and has many ways out: wrap the CALL
    in `with scope():`; every folder `scratch` made inside is removed when the block ends, an error, `sys.exit`, Ctrl-C
    and "kill" included."""
    made = []
    stack = getattr(_SCOPES, "stack", None)
    if stack is None:
        stack = _SCOPES.stack = []
    stack.append(made)
    try:
        with terminate_cleans():
            yield made
    finally:
        stack.pop()
        for p in made:
            remove(p)


def scratch(kind="work", big=True, expect_bytes=0, what="temporary audio"):
    """`make` + the 1 GB announcement, removed when the enclosing `scope()` ends (when there is none: when the program
    ends normally)."""
    p = make(kind, big=big)
    stack = getattr(_SCOPES, "stack", None)
    if stack:
        stack[-1].append(p)
    else:
        import atexit
        atexit.register(remove, p)
    announce(expect_bytes, p, what)
    return p


# ---------------------------------------------------------------- finding them again (Disk care)
def _plain_dir(p):
    try:
        return p.is_dir() and not p.is_symlink() and not os.path.ismount(str(p))
    except OSError:
        return False


def _mine(p):
    try:
        return not hasattr(os, "getuid") or p.lstat().st_uid == os.getuid()
    except OSError:
        return False


def own_folders():
    """Every folder made by `make` that is still there: under <home>/cache/tmp and in the system temp folder. Only names
    of the form hypnomix-<kind>-XXXXXXXX that are real folders (not links, not mount points) owned by you."""
    found, seen = [], set()
    for d in (base_dir(), system_dir()):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            p = d / n
            if OWN.match(n) and _plain_dir(p) and _mine(p) and str(p) not in seen:
                seen.add(str(p))
                found.append(p)
    return found


def looks_like_old_render(p):
    """True for a folder in the system temp folder that has the name and the content of what older versions of
    devices, duck, cliplevel and tidy left: a random "tmpXXXXXXXX" (or "tidy-XXXXXXXX") holding only .wav files, plus at
    most a names.json; or, from duck and cliplevel run without --names, a folder holding nothing but a small
    names.json. NOT proof that HypnoMix made it (another program can leave the same), so it is only ever offered
    to the person, never removed on its own."""
    p = Path(p)
    if not (OLD_RENDER.match(p.name) or OLD_TIDY.match(p.name)):
        return False
    if not (_plain_dir(p) and _mine(p)):
        return False
    try:
        names = os.listdir(p)
    except OSError:
        return False
    wavs = 0
    for n in names:
        q = p / n
        if n == "names.json" and q.is_file() and not q.is_symlink():
            continue
        if n.lower().endswith(".wav") and q.is_file() and not q.is_symlink():
            wavs += 1
            continue
        return False
    if wavs > 0:
        return True
    try:                                                   # names.json alone: only a small one (a few KB of track names)
        return names == ["names.json"] and (p / "names.json").stat().st_size < 1_000_000
    except OSError:
        return False


def old_render_folders():
    """The unprefixed folders in the system temp folder that look_like_old_render accepts."""
    d = system_dir()
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    return [d / n for n in names if (OLD_RENDER.match(n) or OLD_TIDY.match(n)) and looks_like_old_render(d / n)]
