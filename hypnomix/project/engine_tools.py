"""The engine add-on's small reader programs (hypnomix-ptdump, hypnomix-aafdump): where they are, and running one.

They are built with the HypnoMix Studio engine (GPL, like it) and live next to hypnomix-engine in the engine kit's bin/.
HypnoMix (MIT) only runs them as separate programs and reads the JSON they print. Looked for, in order:

  1. HYPNOMIX_PTDUMP / HYPNOMIX_AAFDUMP: the path of the program
  2. next to the engine program the DAW view uses (hypnomix.app.daw.find_engine)
  3. a developer's engine source build (HYPNOMIX_ENGINE_SRC): build/hypnomix/importers/<name>
  4. on PATH
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ENV = {"hypnomix-ptdump": "HYPNOMIX_PTDUMP", "hypnomix-aafdump": "HYPNOMIX_AAFDUMP"}
TIMEOUT = 300
MAX_JSON = 64 * 1024 * 1024        # what a reader may print; it is stopped as soon as it passes this
MAX_ERR = 64 * 1024                # the part of its error output read back
MAX_ERR_DISK = 8 * 1024 * 1024     # what it may write as error output before it is stopped
MAX_FILE = {"hypnomix-ptdump": 128 << 20, "hypnomix-aafdump": 8 << 30}   # the OS's hard limit on one file it writes


class ToolMissing(SystemExit):
    """The reader is not here: one plain sentence (a SystemExit), never a crash report."""


def find(name):
    env = os.environ.get(ENV.get(name, ""))
    cands = [Path(env).expanduser()] if env else []
    exe = name + ".exe" if os.name == "nt" else name     # a Windows program file ends in .exe
    try:
        from hypnomix.app import daw
        eng = daw.find_engine()
        if eng is not None and eng.name != "engine-dev":
            cands.append(eng.parent / exe)
    except Exception:
        pass
    src = os.environ.get("HYPNOMIX_ENGINE_SRC")
    if src:
        cands.append(Path(src).expanduser() / "build" / "hypnomix" / "importers" / exe)
    w = shutil.which(name)
    if w:
        cands.append(Path(w))
    for c in cands:
        if c.is_file() and os.access(c, os.X_OK):
            return c
    raise ToolMissing(f"this kind of project is read by {name}, which comes with the HypnoMix Studio add-on; the add-on "
                      f"is for Apple-silicon Macs only so far, so it cannot be imported here without it (a developer can set "
                      f"{ENV.get(name, 'its path')} to a reader they built)")


# Resource limits (RLIMIT_FSIZE, set in the reader before it starts) exist on macOS and Linux only. Windows has no
# rlimits and no preexec_fn: there the reader's output and error output are watched as everywhere, the timeout
# stops it as everywhere, and the files in the folder it extracts into (`watch`) are looked at once a second against
# the same one-file limit.
HAVE_RLIMIT = os.name == "posix"


def reader_env(windows=None):
    """The small environment a reader runs with: none of the person's keys or tokens. Windows programs also need
    SYSTEMROOT (and its system folders on PATH) to start at all, and a temporary folder."""
    windows = os.name == "nt" if windows is None else windows
    if not windows:
        return {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/")}
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "USERPROFILE")
           if os.environ.get(k)}
    root = env.get("SYSTEMROOT") or env.get("WINDIR") or r"C:\Windows"
    env["SYSTEMROOT"] = root
    env["PATH"] = os.pathsep.join([root + r"\System32", root])
    return env


def _largest(folder):
    """(size, name) of the largest file directly or further inside `folder`; (0, "") when there is none."""
    best = (0, "")
    try:
        for dirpath, _, files in os.walk(folder):
            for f in files:
                try:
                    best = max(best, (os.stat(os.path.join(dirpath, f)).st_size, f))
                except OSError:
                    pass
    except OSError:
        pass
    return best


def run(name, *args, watch=None):
    """Run a reader and return its JSON. A reader's own error ({"error": ...}) becomes a SystemExit in plain words.
    Its output goes to a temporary file that is watched: past MAX_JSON, or after TIMEOUT seconds, it is stopped.
    `watch`: the folder it writes files into, checked against the one-file limit where the OS cannot enforce it."""
    exe = find(name)
    what = Path(args[0]).name if args else name
    with tempfile.TemporaryFile(mode="w+b") as out, tempfile.TemporaryFile(mode="w+b") as err:
        cap = MAX_FILE.get(name, 128 << 20)

        def limit():                                      # set in the reader before it runs: a hard cap on any
            import resource                               # file it writes (its output, extracted audio); never
            soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)   # above a lower limit already set
            c = cap if hard == resource.RLIM_INFINITY else min(cap, hard)
            if soft != resource.RLIM_INFINITY:
                c = min(c, soft)
            resource.setrlimit(resource.RLIMIT_FSIZE, (c, hard))
        try:
            proc = subprocess.Popen([str(exe), *map(str, args)], stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                    env=reader_env(), preexec_fn=limit if HAVE_RLIMIT else None)
        except (OSError, subprocess.SubprocessError) as e:
            raise SystemExit(f"{name} could not be started ({getattr(e, 'strerror', None) or type(e).__name__})") from e
        t0, why, look = time.monotonic(), None, time.monotonic() + 1.0
        while proc.poll() is None:
            big = (0, "")
            if watch is not None and not HAVE_RLIMIT and time.monotonic() >= look:
                look = time.monotonic() + 1.0
                big = _largest(watch)
            if os.fstat(out.fileno()).st_size > MAX_JSON:
                why = f"{name}: the project is too big to read (more than {MAX_JSON >> 20} MB of data)"
            elif os.fstat(err.fileno()).st_size > MAX_ERR_DISK:
                why = f"{name} wrote more than {MAX_ERR_DISK >> 20} MB of error output on {what}: stopped"
            elif time.monotonic() - t0 > TIMEOUT:
                why = f"{name} took longer than {TIMEOUT} s on {what}: stopped"
            elif big[0] > cap:
                why = f"{name} wrote a file larger than {cap >> 20} MB ({big[1]}) from {what}: stopped"
            if why:
                proc.kill()
                proc.wait()
                raise SystemExit(why)
            time.sleep(0.05)
        big = _largest(watch) if watch is not None and not HAVE_RLIMIT else (0, "")
        if big[0] > cap:                                  # written in its last second, after the last look
            raise SystemExit(f"{name} wrote a file larger than {cap >> 20} MB ({big[1]}) from {what}: stopped")
        if os.fstat(out.fileno()).st_size > MAX_JSON:
            raise SystemExit(f"{name}: the project is too big to read (more than {MAX_JSON >> 20} MB of data)")
        out.seek(0)
        raw = out.read()
        err.seek(max(0, os.fstat(err.fileno()).st_size - MAX_ERR))
        tail_text = err.read().decode("utf-8", "replace")
    try:
        data = json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError as e:
        tail = tail_text.strip().splitlines()[-1:] or [f"exit status {proc.returncode}"]
        raise SystemExit(f"{name} could not read {what}: {tail[0][:300]}") from e
    if isinstance(data, dict) and data.get("error"):
        raise SystemExit(f"{what}: {str(data['error'])[:300]}")
    if proc.returncode != 0:
        raise SystemExit(f"{name} failed on {what} (exit status {proc.returncode})")
    if not isinstance(data, dict):
        raise SystemExit(f"{name} printed something other than a project description for {what}")
    return data
