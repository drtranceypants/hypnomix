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


class Reaper:
    def __init__(self, timeout=15.0, folder=None):
        self.dir = Path(folder) if folder else bridge_dir()
        self.timeout = timeout

    # ------------------------------------------------------------ lifecycle
    def alive(self, within=4.0):
        f = self.dir / "alive"
        return f.exists() and time.time() - f.stat().st_mtime < within

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
        t0 = time.time()
        while time.time() - t0 < wait:
            if self.alive():
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
        timeout = max(self.timeout, 600.0) if cmd == "render_master" else self.timeout
        while not res.exists():
            if time.time() - t0 > timeout:
                req.unlink(missing_ok=True)
                raise ReaperError(f"REAPER did not answer {cmd} within {timeout:.0f} s (a dialog open?)")
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
        r = self.call("render_master", start=float(start), end=float(end), path=str(path).replace("\\", "/"))
        if not path.exists():
            raise ReaperError("REAPER did not write the render")
        return path
