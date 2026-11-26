"""Start menu entry for the Windows install: start the hypnomix app (if it is not running) and open it.

    pythonw launcher.pyw          start it, then open http://127.0.0.1:8791 in the default browser
    pythonw launcher.pyw --stop   stop it (the "Quit hypnomix" entry, and the uninstaller)
    pythonw launcher.pyw --quiet  start it without opening a browser tab (after an update: the open tab reloads itself)

The server runs with python.exe in a hidden console, so the programs it calls (ffmpeg) share that console
instead of flashing windows of their own. Its pid is kept in %LOCALAPPDATA%\\Hypnomix\\server.pid."""
import os, subprocess, sys, time, urllib.request, webbrowser
from pathlib import Path

PORT = 8791
URL = f"http://127.0.0.1:{PORT}/"
HERE = Path(__file__).resolve().parent                  # the install folder
PY = HERE / "python" / "python.exe"
STATE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Hypnomix"
PID = STATE / "server.pid"
LOG = STATE / "server.log"


def up():
    try:
        with urllib.request.urlopen(URL + "api/state", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def message(text):
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, text, "hypnomix", 0x40)


def stop():
    if PID.exists():
        pid = PID.read_text().strip()
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        PID.unlink(missing_ok=True)


def start(show=True):
    if up():
        if show:
            webbrowser.open(URL)
        return
    STATE.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PATH"] = str(HERE / "bin") + os.pathsep + env.get("PATH", "")      # the bundled ffmpeg first
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    log = open(LOG, "w", encoding="utf-8")
    p = subprocess.Popen([str(PY), "-m", "hypnomix.cli", "app", "--no-open", "--port", str(PORT)],
                         cwd=str(STATE), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                         creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    PID.write_text(str(p.pid))
    for _ in range(240):                                 # the first start compiles a little: up to a minute
        if up():
            if show:
                webbrowser.open(URL)
            return
        if p.poll() is not None:
            break
        time.sleep(0.25)
    message(f"hypnomix did not start. What it said is in\n{LOG}\n\nIf another program uses port {PORT}, close it and try again.")


if __name__ == "__main__":
    stop() if "--stop" in sys.argv else start(show="--quiet" not in sys.argv)
