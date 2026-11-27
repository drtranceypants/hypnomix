"""Python side of the REAPER bridge: request files in, JSON answers out (see bridge.lua).

    from hypnomix.reaper.client import Reaper
    r = Reaper()                      # Reaper.start() first if the bridge is not running
    r.ping()
    fx = r.add_fx("master", "ReaEQ (Cockos)")["fx"]
    r.set_shown("master", fx, "Freq-Band 1", 90)     # by the value the plug-in shows (Hz, dB, ms...)

The bridge folder is ~/.hypnomix/reaper-bridge (HYPNOMIX_REAPER_DIR overrides it).
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

BRIDGE = Path(__file__).with_name("bridge.lua")


class ReaperError(RuntimeError):
    pass


# How long one command may hold REAPER (and so the bridge) at most: a render runs inside the call. The same limits
# are the answer timeouts in Reaper.call, and a `busy` file older than its command's limit (plus a minute) is taken to
# be left over from a REAPER that closed in the middle of a command.
LONG = {"render_master": 600.0, "mixer_solo_render": 600.0, "mixer_snapshot": 120.0, "mixer_restore": 120.0}
BUSY_GRACE = 60.0


def bridge_dir():
    d = Path(os.environ.get("HYPNOMIX_REAPER_DIR") or Path.home() / ".hypnomix" / "reaper-bridge")
    d.mkdir(parents=True, exist_ok=True)
    return d


def reaper_executable():
    """REAPER's program file, or None."""
    env = os.environ.get("HYPNOMIX_REAPER")
    cands = [env] if env else []
    sysname = platform.system()
    if sysname == "Darwin":
        cands += ["/Applications/REAPER.app/Contents/MacOS/REAPER", "/Applications/REAPER64.app/Contents/MacOS/REAPER",
                  str(Path.home() / "Applications/REAPER.app/Contents/MacOS/REAPER")]
    elif sysname == "Windows":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
            cands.append(str(Path(base) / "REAPER (x64)" / "reaper.exe"))
            cands.append(str(Path(base) / "REAPER" / "reaper.exe"))
    else:
        cands += [shutil.which("reaper") or "", str(Path.home() / "opt/REAPER/reaper")]
    return next((c for c in cands if c and Path(c).exists()), None)


def reaper_running():
    """True when a REAPER process is running, False when none is, None when this computer cannot tell (no pgrep or
    tasklist, or one that failed). Used so a `busy` file left by a REAPER that crashed in the middle of a render is not
    taken for a bridge that is still working."""
    try:
        if platform.system() == "Windows":
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq reaper.exe", "/NH"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=5)
            if r.returncode != 0:
                return None
            return "reaper.exe" in r.stdout.lower()
        seen_none = False
        for name in ("REAPER", "reaper"):
            r = subprocess.run(["pgrep", "-x", name], capture_output=True, timeout=5)
            if r.returncode == 0:
                return True
            if r.returncode != 1:                           # 2, 3: pgrep itself failed (a sandbox, no process service)
                return None
            seen_none = True
        return False if seen_none else None
    except (OSError, subprocess.SubprocessError):
        return None


def pid_running(pid):
    """True when process `pid` is running (and, where this can be read, is a REAPER), False when it is not, None when
    this computer cannot tell."""
    if not pid or pid <= 0:
        return None
    try:
        if platform.system() == "Windows":
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=5)
            if r.returncode != 0:
                return None
            return "reaper" in r.stdout.lower()
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            pass                                            # it exists, owned by someone else
        r = subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return "reaper" in r.stdout.lower()             # the id was reused by another program: not our REAPER
        if r.returncode == 1:
            return False                                    # it ended between the two checks
        return True
    except (OSError, subprocess.SubprocessError):
        return None


class Reaper:
    def __init__(self, timeout=15.0, folder=None):
        self.dir = Path(folder) if folder else bridge_dir()
        self.timeout = timeout

    # ------------------------------------------------------------ lifecycle
    def busy(self):
        """(request id, command) the bridge is running now, or None. The bridge writes `busy` before each command and
        removes it after, so a long command (a render) does not look like a bridge that stopped."""
        f = self.dir / "busy"
        try:
            age = time.time() - f.stat().st_mtime
            lines = f.read_bytes().decode("utf-8", errors="replace").splitlines()
        except OSError:
            return None
        rid = lines[0].strip() if lines else ""
        cmd = lines[1].strip() if len(lines) > 1 else ""
        token = lines[2].strip() if len(lines) > 2 else ""
        pid = int(lines[3]) if len(lines) > 3 and lines[3].strip().isdigit() else 0
        if age >= LONG.get(cmd, BUSY_GRACE) + BUSY_GRACE:
            return None                                     # left over: REAPER closed during that command
        a_token, _ = self._alive_stamp()
        if token and a_token and token != a_token:
            return None                                     # written by an earlier bridge, not the one beating now
        if pid_running(pid) is False:
            return None                                     # the REAPER that wrote it is gone (crashed or quit)
        return rid, cmd

    def _alive_stamp(self):
        """(token, REAPER process id) from the `alive` file; ("", 0) for an old bridge or no file."""
        try:
            lines = (self.dir / "alive").read_bytes().decode("utf-8", errors="replace").splitlines()
        except OSError:
            return "", 0
        token = lines[1].strip() if len(lines) > 1 else ""
        pid = int(lines[2]) if len(lines) > 2 and lines[2].strip().isdigit() else 0
        return token, pid

    def fresh(self, within=4.0):
        """The bridge wrote `alive` within the last few seconds: certainly running."""
        try:
            return time.time() - (self.dir / "alive").stat().st_mtime < within
        except OSError:
            return False

    def last_error(self, since):
        """The bridge's own last error (last-error.txt), if it was written after `since`; else None."""
        f = self.dir / "last-error.txt"
        try:
            if f.stat().st_mtime < since:
                return None
            lines = f.read_bytes().decode("utf-8", errors="replace").splitlines()
        except OSError:
            return None
        return " ".join(x.strip() for x in lines[1:] if x.strip()) or None

    def alive(self, within=4.0):
        f = self.dir / "alive"
        try:
            if time.time() - f.stat().st_mtime < within:
                return True
        except OSError:
            return False                                    # no alive file: the bridge ended (or never started)
        b_pid = self._busy_pid()
        if self.busy() is None:
            return False
        if b_pid:                                           # its REAPER is known and still running (busy() checked)
            return True
        return reaper_running() is not False                # an older bridge, or Windows: any REAPER at all
                                                            # (unless REAPER itself is gone: it crashed mid-command)

    def _busy_pid(self):
        try:
            lines = (self.dir / "busy").read_bytes().decode("utf-8", errors="replace").splitlines()
        except OSError:
            return 0
        return int(lines[3]) if len(lines) > 3 and lines[3].strip().isdigit() else 0

    def start(self, wait=30.0):
        """Run the bridge inside REAPER (starting REAPER if it is closed). Nothing is installed."""
        if self.alive():
            return True
        for f in list(self.dir.glob("res-*.json")) + list(self.dir.glob("req-*.txt")):
            f.unlink(missing_ok=True)                       # answers nobody waited for, requests nobody read
        exe = reaper_executable()
        if not exe:
            raise ReaperError("REAPER was not found (set HYPNOMIX_REAPER to its program file)")
        boot = self.dir / "start-bridge.lua"
        lua_dir = str(self.dir).replace("\\", "/").replace('"', '\\"')
        lua_bridge = str(BRIDGE).replace("\\", "/").replace('"', '\\"')
        boot.write_bytes(f'HYPNOMIX_DIR = "{lua_dir}"\ndofile("{lua_bridge}")\n'.encode("utf-8", "surrogateescape"))      # UTF-8 bytes, plain \n, on every system; a folder name this computer could not decode keeps its own bytes
        subprocess.Popen([exe, "-nosplash", str(boot)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        (self.dir / "busy").unlink(missing_ok=True)        # whatever it was, no REAPER is working on it now
        t0 = time.time()
        while time.time() - t0 < wait:
            if self.alive():                                # `busy` is gone, so only a fresh beat counts: the new bridge
                return True
            time.sleep(0.25)
        raise ReaperError("the bridge did not start: is a dialog open in REAPER? (answer it, then try again)")

    def stop(self):
        if self.alive():
            self.call("quit")

    # ------------------------------------------------------------ requests
    def call(self, cmd, **args):
        if not self.alive():
            raise ReaperError("the REAPER bridge is not running: `hypnomix reaper start`")
        rid = uuid.uuid4().hex[:12]
        body = cmd + "\n" + "".join(f"{k}={v}\n" for k, v in args.items() if v is not None)
        if any("\n" in str(v) for v in args.values() if v is not None):
            raise ValueError("bridge values are one line each")
        tmp, req = self.dir / f"req-{rid}.tmp", self.dir / f"req-{rid}.txt"
        tmp.write_bytes(body.encode("utf-8"))               # a track named with an accent or a CJK letter reaches REAPER intact
        tmp.rename(req)
        res = self.dir / f"res-{rid}.json"
        t0 = time.time()
        timeout = max(self.timeout, LONG.get(cmd, 0.0))
        deadline, look = t0 + timeout, t0 + 0.5
        while not res.exists():
            now = time.time()
            # twice a second by the clock, and once more before giving up: another caller's command still running?
            # (not every so many sleeps: on a slow or busy computer a 20 ms sleep can last far longer)
            if now >= look or now > deadline:
                look = now + 0.5
                b = self.busy()
                if b and b[0] != rid and pid_running(self._busy_pid()) is not False:   # not one whose REAPER is gone
                    try:
                        b_start = (self.dir / "busy").stat().st_mtime
                    except OSError:
                        b_start = time.time()
                    # ours waits its turn, its own time still to come; never past the other command's own limit
                    cap = b_start + LONG.get(b[1], BUSY_GRACE) + timeout
                    deadline = max(deadline, min(time.time() + timeout, cap))
            if time.time() > deadline:
                req.unlink(missing_ok=True)
                why = self.last_error(t0)
                raise ReaperError(f"REAPER did not answer {cmd} within {time.time() - t0:.0f} s "
                                  + (f"(the bridge says: {why})" if why else "(a dialog open?)"))
            time.sleep(0.02)
        d = json.loads(res.read_bytes().decode("utf-8", errors="replace"))
        res.unlink()
        if not d.get("ok"):
            raise ReaperError(f"{cmd}: {d.get('error')}")
        return d.get("result")

    # ------------------------------------------------------------ helpers
    def ping(self):
        return self.call("ping")

    def tracks(self):
        return self.call("tracks") or []

    def installed(self, filter=""):
        return self.call("fx_installed", filter=filter) or []

    def add_fx(self, track, name):
        return self.call("add_fx", track=track, name=name)

    def params(self, track, fx):
        return self.call("fx_params", track=track, fx=fx) or []

    def set_norm(self, track, fx, param, value):
        return self.call("set_param", track=track, fx=fx, param=param, value=value)

    def set_shown(self, track, fx, param, value):
        """Set a parameter by the number the plug-in shows (Hz, dB, ms, ratio...)."""
        return self.call("set_param", track=track, fx=fx, param=param, shown=value)

    def named(self, track, fx, key, value=None):
        if value is None:
            return self.call("get_named", track=track, fx=fx, key=key)
        return self.call("set_named", track=track, fx=fx, key=key, value=value)

    def enable(self, track, fx, on=True):
        return self.call("fx_enable", track=track, fx=fx, on=1 if on else 0)

    def set_track(self, track, volume_db=None, pan=None, mute=None):
        return self.call("set_track", track=track, volume_db=volume_db, pan=pan, mute=mute)

    def pins(self, track, fx, output, pin, mask):
        return self.call("set_pins", track=track, fx=fx, output=1 if output else 0, pin=pin, mask=mask)

    def fx_list(self, track):
        return self.call("fx_list", track=track) or []

    def remove_fx(self, track, fx):
        return self.call("remove_fx", track=track, fx=fx)

    def new_tab(self):
        return self.call("new_tab")

    def close_tab(self):
        return self.call("close_tab")

    def add_track(self, name=None, file=None, pos=0.0):
        return self.call("add_track", name=name, file=file, pos=pos)

    def transport(self, go=None, at=None):
        return self.call("transport", go=go, at=at)

    def render_master(self, start, end, path):
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)                     # so exists() below means this render wrote it
        r = self.call("render_master", start=float(start), end=float(end), path=str(path).replace("\\", "/"))
        if not path.exists():
            raise ReaperError("REAPER did not write the render")
        return path
