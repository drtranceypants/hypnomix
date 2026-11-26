"""Updates: tell people when a new hypnomix is out, and install it with one click.

Check   at most once a day (and on demand), ask GitHub for the latest release; cached in ~/.hypnomix/update.json
Get     download this computer's installer from the release into ~/.hypnomix/updates/, then check its SHA-256
        against the release's SHA256SUMS.txt; a mismatch is deleted and never installed
Install Mac: a helper quits the app, swaps the new Hypnomix.app in place of this one and reopens it.
        Windows: a helper runs the new setup silently over this install (settings and songs are untouched) and
        starts hypnomix again. The page reloads itself when the new version answers.

Only the installed app (the Mac .dmg or the Windows setup) updates itself. A source checkout is told about the new
version and how to update (git pull). Nothing is downloaded or installed without a click; the daily check can be
switched off.

  python -m hypnomix.app.update check            what the app would say
  python -m hypnomix.app.update install FILE     install a downloaded installer now (used by the Windows CI test)
"""
import hashlib, json, os, platform, re, shlex, subprocess, sys, tempfile, threading, time, urllib.request
from pathlib import Path

REPO = "drtranceypants/hypnomix"
API = os.environ.get("HYPNOMIX_UPDATE_URL") or f"https://api.github.com/repos/{REPO}/releases/latest"
STATE = Path("~/.hypnomix/update.json").expanduser()
DIR = Path("~/.hypnomix/updates").expanduser()
DAY = 24 * 3600
LOCK = threading.Lock()
JOB = {"status": "idle", "got": 0, "size": 0, "file": "", "error": ""}


# ---------------------------------------------------------------- what is installed
def current():
    try:
        from importlib.metadata import version
        return version("hypnomix")
    except Exception:
        pass
    for f in (Path(__file__).resolve().parents[2] / "pyproject.toml",):
        m = re.search(r'^version = "([^"]+)"', f.read_text(), re.M) if f.exists() else None
        if m:
            return m.group(1)
    return "0"


def vkey(v):
    return tuple(int(x) if x.isdigit() else 0 for x in re.findall(r"\d+", str(v).lstrip("v")))[:4]


def kind():
    """'mac' or 'windows' for the installed app, '' for a source checkout (no one-click)."""
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin" and "Hypnomix.app" in exe.parts:
        return "mac"
    if sys.platform == "win32" and exe.parent.name.lower() == "python" and (exe.parent.parent / "launcher.pyw").exists():
        return "windows"
    return ""


def asset_name():
    k = kind()
    if k == "windows":
        return "Hypnomix-windows-setup.exe"
    if k == "mac":
        return "Hypnomix-mac-arm64.dmg" if platform.machine() in ("arm64", "aarch64") else "Hypnomix-mac-intel.dmg"
    return ""


def app_root():
    exe = Path(sys.executable).resolve()
    if kind() == "mac":
        return next(p for p in exe.parents if p.suffix == ".app")
    return exe.parent.parent                                     # Windows: the install folder


# ---------------------------------------------------------------- the check
def load():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, indent=1))


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "hypnomix-app"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check(force=False):
    s = load()
    if not force and (not s.get("auto", True) or time.time() - s.get("checked", 0) < DAY):
        return view()
    if force:
        s.pop("skip", None)                                     # asked by hand: show it again even after "Later"
    try:
        rel = json.loads(_get(API))
        assets = {a["name"]: a for a in rel.get("assets", [])}
        s.update(checked=time.time(), error="", latest=rel.get("tag_name", "").lstrip("v"), page=rel.get("html_url", ""),
                 notes=(rel.get("body") or "").split("\n## Security scan")[0].strip()[:4000],
                 published=rel.get("published_at", ""),
                 assets={n: dict(url=a["browser_download_url"], size=a.get("size", 0)) for n, a in assets.items()})
    except Exception as e:
        s.update(checked=time.time(), error=f"couldn't reach GitHub ({type(e).__name__})")
    save(s)
    return view()


def view():
    s = load()
    cur, latest = current(), s.get("latest", "")
    newer = bool(latest) and vkey(latest) > vkey(cur)
    name = asset_name()
    a = (s.get("assets") or {}).get(name) if name else None
    return dict(current=cur, latest=latest, newer=newer, skipped=s.get("skip") == latest, auto=s.get("auto", True),
                kind=kind(), one_click=bool(newer and a), size=(a or {}).get("size", 0), page=s.get("page", ""),
                notes=s.get("notes", ""), published=s.get("published", ""), checked=s.get("checked", 0),
                error=s.get("error", ""), job=dict(JOB))


def settings(body):
    s = load()
    if "auto" in body:
        s["auto"] = bool(body["auto"])
    if body.get("skip"):
        s["skip"] = s.get("latest", "")
    save(s)
    return view()


def prune():
    """Installers already installed (this version or older) are deleted: they are 150-250 MB each."""
    cur = vkey(current())
    for f in DIR.glob("*-Hypnomix-*"):
        if vkey(f.name.split("-Hypnomix-")[0]) <= cur:
            f.unlink(missing_ok=True)


def check_in_background():
    """At app start: remove installed installers, then a quiet daily check that never slows the page down."""
    def run():
        try:
            prune()
        except OSError:
            pass
        check(False)
    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------- download and verify
def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _download():
    s, name = load(), asset_name()
    try:
        a = s["assets"][name]
        sums = _get(s["assets"]["SHA256SUMS.txt"]["url"], 60).decode()
        want = next((ln.split()[0] for ln in sums.splitlines() if ln.split()[-1:] == [name]), "")
        if not re.fullmatch(r"[0-9a-f]{64}", want):
            raise RuntimeError("the release has no checksum for this file")
        DIR.mkdir(parents=True, exist_ok=True)
        dest, part = DIR / f"{s['latest']}-{name}", DIR / f"{s['latest']}-{name}.part"
        if dest.exists() and _sha(dest) == want:
            JOB.update(status="ready", file=str(dest), got=dest.stat().st_size, size=dest.stat().st_size)
            return
        req = urllib.request.Request(a["url"], headers={"User-Agent": "hypnomix-app"})
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
            JOB["size"] = int(r.headers.get("Content-Length") or a.get("size") or 0)
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
                JOB["got"] += len(b)
        JOB["status"] = "verifying"
        got = _sha(part)
        if got != want:
            part.unlink(missing_ok=True)
            raise RuntimeError("the download didn't match the release's checksum, so it was deleted. Try again later")
        part.replace(dest)
        for old in DIR.glob("*"):                               # keep only this one
            if old != dest:
                old.unlink(missing_ok=True)
        JOB.update(status="ready", file=str(dest))
    except Exception as e:
        JOB.update(status="error", error=str(e) if isinstance(e, RuntimeError) else f"download failed: {e}")


def download():
    with LOCK:
        v = view()
        if not v["one_click"]:
            raise ValueError("no update to download here")
        if JOB["status"] in ("downloading", "verifying"):
            return view()
        JOB.update(status="downloading", got=0, size=v["size"], file="", error="")
        threading.Thread(target=_download, daemon=True).start()
    return view()


# ---------------------------------------------------------------- install
MAC_HELPER = r'''#!/bin/bash
# hypnomix update helper: quit the app, put the new Hypnomix.app in place of the old one, open it again.
APP="$1"; DMG="$2"; APP_PID="$3"; SERVER_PID="$4"; LOG="$5"
exec >>"$LOG" 2>&1
echo "== $(date) update $APP from $DMG"
case "$APP" in */Hypnomix.app) ;; *) echo "not an app path: $APP"; exit 1 ;; esac
[ -d "$APP" ] && [ -f "$DMG" ] || { echo "missing app or dmg"; exit 1; }
MNT=$(mktemp -d /tmp/hypnomix-update.XXXXXX)
hdiutil attach -nobrowse -readonly -mountpoint "$MNT" "$DMG" || exit 1
[ -d "$MNT/Hypnomix.app" ] || { echo "no Hypnomix.app in the image"; hdiutil detach -quiet "$MNT"; exit 1; }
NEW="$APP.updating"
/bin/rm -rf "$NEW"
ditto "$MNT/Hypnomix.app" "$NEW" || { hdiutil detach -quiet "$MNT"; exit 1; }
hdiutil detach -quiet "$MNT"; rmdir "$MNT" 2>/dev/null
for p in "$APP_PID" "$SERVER_PID"; do [ -n "$p" ] && kill "$p" 2>/dev/null; done
for i in $(seq 1 40); do kill -0 "$APP_PID" 2>/dev/null || kill -0 "$SERVER_PID" 2>/dev/null || break; sleep 0.25; done
for p in "$APP_PID" "$SERVER_PID"; do [ -n "$p" ] && kill -9 "$p" 2>/dev/null; done
OLD="$APP.old"
/bin/rm -rf "$OLD"
mv "$APP" "$OLD" && mv "$NEW" "$APP" || { echo "swap failed"; [ -d "$OLD" ] && [ ! -d "$APP" ] && mv "$OLD" "$APP"; exit 1; }
/bin/rm -rf "$OLD"
echo "swapped; opening"
if [ -n "$HYPNOMIX_PORT" ]; then    # a test copy: reopen it the same way, beside the real one
  open -n --env HYPNOMIX_PORT="$HYPNOMIX_PORT" --env HOME="$HOME" --env HYPNOMIX_UPDATE_URL="$HYPNOMIX_UPDATE_URL" "$APP"
else open "$APP"; fi
'''

WIN_HELPER = r'''# hypnomix update helper: run the new setup silently over this install, then start hypnomix again.
param([string]$Setup, [string]$App, [string]$Log)
Start-Transcript -Path $Log -Append | Out-Null
Start-Sleep -Seconds 1
$p = Start-Process -FilePath $Setup -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=`"$App`"" -Wait -PassThru
Write-Host "setup exit $($p.ExitCode)"
if (Test-Path "$App\python\pythonw.exe") {
  Start-Process -FilePath "$App\python\pythonw.exe" -ArgumentList "`"$App\launcher.pyw`"", "--quiet" -WorkingDirectory $App
}
Stop-Transcript | Out-Null
'''


def install(path=None):
    """Start the helper and return; the helper stops this server, so the page waits for the new version."""
    k = kind()
    f = Path(path or JOB.get("file") or "")
    if not k:
        raise ValueError("only the installed app updates itself; in a source checkout run: git pull && uv pip install -e .")
    if not f.exists():
        raise ValueError("download the update first")
    DIR.mkdir(parents=True, exist_ok=True)
    log = DIR / "update.log"
    if k == "mac":
        helper = DIR / "update-helper.sh"
        helper.write_text(MAC_HELPER)
        helper.chmod(0o755)
        app = app_root()
        if not os.access(app.parent, os.W_OK):
            raise ValueError(f"can't write to {app.parent}: download the new version from the website instead")
        parent = subprocess.run(["ps", "-p", str(os.getppid()), "-o", "comm="], capture_output=True, text=True).stdout.strip()
        app_pid = str(os.getppid()) if parent.endswith("/Hypnomix") or parent == "Hypnomix" else ""   # only the app's window
        subprocess.Popen(["/bin/bash", str(helper), str(app), str(f), app_pid, str(os.getpid()), str(log)],
                         start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        helper = DIR / "update-helper.ps1"
        helper.write_text(WIN_HELPER, encoding="utf-8")
        cmd = (f'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{helper}" '
               f'-Setup "{f}" -App "{app_root()}" -Log "{log}"')
        # started through WMI so it isn't a child of this server: the setup stops the server's whole process tree
        ps = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=" +
              "'" + cmd.replace("'", "''") + "'}; exit $r.ReturnValue")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode:
            raise RuntimeError(f"couldn't start the updater ({r.returncode}): {r.stderr.strip()[:300]}")
    JOB["status"] = "installing"
    return view()


# ---------------------------------------------------------------- the server's routes
def handle_get(path, q):
    if path == "/api/update/state":
        return 200, view()
    if path == "/update.js":
        return 200, Path(__file__).with_name("update.js").read_bytes(), "text/javascript; charset=utf-8"
    return None


def handle_post(path, body):
    try:
        if path == "/api/update/check":
            return 200, check(True)
        if path == "/api/update/settings":
            return 200, settings(body)
        if path == "/api/update/download":
            return 200, download()
        if path == "/api/update/install":
            return 200, install()
    except ValueError as e:
        return 400, {"error": str(e)}
    except RuntimeError as e:
        return 500, {"error": str(e)}
    return None


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["check"]:
        print(json.dumps(check(True), indent=1))
    elif a[:1] == ["install"] and len(a) == 2:
        print(json.dumps(install(a[1]), indent=1))
    else:
        print(__doc__)
