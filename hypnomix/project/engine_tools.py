"""The engine add-on's small reader programs (hypnomix-ptdump, hypnomix-aafdump): where they are, and running one.

They are built with the HypnoMix DAW engine (GPL, like it) and live next to hypnomix-engine in the engine kit's bin/.
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
    try:
        from hypnomix.app import daw
        eng = daw.find_engine()
        if eng is not None and eng.name != "engine-dev":
            cands.append(eng.parent / name)
    except Exception:
        pass
    src = os.environ.get("HYPNOMIX_ENGINE_SRC")
    if src:
        cands.append(Path(src).expanduser() / "build" / "hypnomix" / "importers" / name)
    w = shutil.which(name)
    if w:
        cands.append(Path(w))
    for c in cands:
        if c.is_file() and os.access(c, os.X_OK):
            return c
    raise ToolMissing(f"this kind of project is read by {name}, which comes with the HypnoMix DAW add-on; the add-on "
                      f"is not available yet, so it cannot be imported here until then (a developer can set "
                      f"{ENV.get(name, 'its path')} to a reader they built)")


def run(name, *args):
    """Run a reader and return its JSON. A reader's own error ({"error": ...}) becomes a SystemExit in plain words.
    Its output goes to a temporary file that is watched: past MAX_JSON, or after TIMEOUT seconds, it is stopped."""
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
                                    env={"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/")},
                                    preexec_fn=limit if os.name == "posix" else None)
        except (OSError, subprocess.SubprocessError) as e:
            raise SystemExit(f"{name} could not be started ({getattr(e, 'strerror', None) or type(e).__name__})") from e
        t0, why = time.monotonic(), None
        while proc.poll() is None:
            if os.fstat(out.fileno()).st_size > MAX_JSON:
                why = f"{name}: the project is too big to read (more than {MAX_JSON >> 20} MB of data)"
            elif os.fstat(err.fileno()).st_size > MAX_ERR_DISK:
                why = f"{name} wrote more than {MAX_ERR_DISK >> 20} MB of error output on {what}: stopped"
            elif time.monotonic() - t0 > TIMEOUT:
                why = f"{name} took longer than {TIMEOUT} s on {what}: stopped"
            if why:
                proc.kill()
                proc.wait()
                raise SystemExit(why)
            time.sleep(0.05)
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
