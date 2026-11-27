"""Updates: tell people when a new HypnoMix is out, and install it with one click.

Check   at most once a day (and on demand), ask GitHub for the latest release; cached in ~/.hypnomix/update.json
Get     download this computer's installer from the release into ~/.hypnomix/updates/, then check its SHA-256
        against the release's SHA256SUMS.txt; a mismatch is deleted and never installed
Install Mac: a helper quits the app, swaps the new Hypnomix.app in place of this one and reopens it.
        Windows: a helper runs the new setup silently over this install (settings and songs are untouched) and
        starts HypnoMix again. The page reloads itself when the new version answers.

What the check protects against, and what it does not
  It protects against a damaged or half-finished download, and against a file on GitHub's download servers (the CDN)
  being swapped for a different one: the installer's SHA-256 must match the release's SHA256SUMS.txt, it is checked
  again just before the installer runs, and the helper checks it a third time before the Mac image is opened. It also
  refuses release names, file names and download addresses that are not what the real project publishes (a plain
  version number as the release name; https, on github.com, in that same release's own download folder under
  /drtranceypants/hypnomix/releases/download/; redirects staying on GitHub's own hosts). On a Mac the helper also
  checks that the new app says it is the version the release claimed, so an older app can't be installed under a
  newer release name.
  It does NOT protect against someone who controls the GitHub release itself (the repository, a maintainer account or
  a token): they publish the installer and the checksum file together, so the two agree. Installers are not yet
  signed with a publisher key that this app could check. On a Mac the helper also runs "codesign --verify" on the new
  app, which only shows the bundle is whole and unmodified since it was signed (ad hoc or not): it does not show who
  made it. If that matters to you, download from the website and check the release's published fingerprints yourself.

One installer per platform, the same for everyone (asset_name()): there are no editions. HypnoMix Studio is not inside the
app; it is an add-on fetched from Setup (hypnomix/app/engine_addon.py), so an update swaps the app and leaves the engine
where it is. A release that does not carry this computer's installer is reported plainly (no_download) and nothing is
offered. Install and restart is refused (HTTP 409) while the DAW session has unsaved changes (daw.dirty()), and the Mac
helper waits for the app, the server and the engine to be gone, well past the engine's own stop time, before it swaps
the app.

Only the installed app (the Mac .dmg or the Windows setup) updates itself. A source checkout is told about the new
version and how to update (git pull). Nothing is downloaded or installed without a click; the daily check can be
switched off.

  python -m hypnomix.app.update check            what the app would say
  python -m hypnomix.app.update install FILE     install a downloaded installer now (used by the Windows CI test)
"""
import hashlib, json, os, platform, re, shlex, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from pathlib import Path
from urllib.parse import unquote, urlsplit

from hypnomix.core import paths

REPO = "drtranceypants/hypnomix"
API = os.environ.get("HYPNOMIX_UPDATE_URL") or f"https://api.github.com/repos/{REPO}/releases/latest"
STATE = paths.HOME / "update.json"       # the same home as the rest of HypnoMix: HYPNOMIX_HOME moves these (default ~/.hypnomix)
DIR = paths.HOME / "updates"
TAG = re.compile(r"v?[0-9]{1,6}(?:\.[0-9]{1,6}){0,3}", re.ASCII)  # a release name must be a plain version: ASCII digits and dots only
ASSETS = {"Hypnomix-windows-setup.exe", "Hypnomix-mac-arm64.dmg", "Hypnomix-mac-intel.dmg", "SHA256SUMS.txt"}
RELEASES = f"/{REPO}/releases/"
DAY = 24 * 3600
LOCK = threading.Lock()
JOB = {"status": "idle", "got": 0, "size": 0, "file": "", "error": ""}


# ---------------------------------------------------------------- what is installed
def current():
    # In a source checkout the pyproject.toml beside the package is the truth: an editable install's metadata keeps
    # the version it was installed at, and goes stale after every `git pull`. An installed app has no pyproject there.
    try:
        f = Path(__file__).resolve().parents[2] / "pyproject.toml"
        m = re.search(r'^version = "([^"]+)"', f.read_text(encoding="utf-8"), re.M) if f.exists() else None
        if m and re.search(r'^name = "hypnomix"', f.read_text(encoding="utf-8"), re.M):
            return m.group(1)
    except OSError:
        pass
    try:
        from importlib.metadata import version
        return version("hypnomix")
    except Exception:
        return "0"


def vkey(v):
    return tuple(int(x) for x in re.findall(r"[0-9]+", str(v).lstrip("v")))[:4]


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
        d = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _assets(s):
    """The cached asset table, only if it has the right shape (the file is just a cache and can be edited by hand)."""
    a = s.get("assets")
    return {k: v for k, v in a.items() if isinstance(k, str) and isinstance(v, dict)} if isinstance(a, dict) else {}


def save(d):
    paths.write_private(STATE, json.dumps(d, indent=1))


# ---------------------------------------------------------------- which addresses are trusted
def _local(u):
    """A local feed for tests: only when HYPNOMIX_UPDATE_URL is set, and only this computer."""
    return bool(os.environ.get("HYPNOMIX_UPDATE_URL")) and u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost")


def _gh_host(h):
    return h in ("github.com", "api.github.com") or h.endswith(".githubusercontent.com")


def _https(u):
    return u.scheme == "https" and not u.username and not u.password and u.port in (None, 443)


def _release_path(path):
    """True if the path stays under /<repo>/releases/ however it is spelled: %-encoded dots and slashes are decoded
    (until nothing changes) before the folder test, and any '.' or '..' part, backslash or ';' refuses it."""
    for _ in range(5):
        d = unquote(path)
        if d == path:
            break
        path = d
    else:
        return False
    return (path.lower().startswith(RELEASES) and "\\" not in path and ";" not in path
            and not any(part in (".", "..") for part in path.split("/")))


def check_url(url, role):
    """Refuse an address that isn't the real project's. role: 'api' (the release list), 'asset' (a file in a release),
    'hop' (where a redirect ended up). Raises RuntimeError with a plain message."""
    u = urlsplit(str(url))
    if _local(u):
        return u
    if not _https(u):
        raise RuntimeError("the update address isn't a secure github.com address, so it was ignored")
    host = (u.hostname or "").lower()
    ok = _gh_host(host) if role in ("api", "hop") else host == "github.com" and _release_path(u.path)
    if not ok:
        raise RuntimeError("the update address isn't the HypnoMix project's release on github.com, so it was ignored")
    return u


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Every redirect is checked before it is followed: https only, and only GitHub's own hosts."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, "hop")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    """http and https only (no file:, ftp: or data:), with the redirect check above. The system's proxy settings are
    used as before, so a computer that must go through a proxy still works; the address checks run on every hop."""
    o = urllib.request.OpenerDirector()
    for h in (urllib.request.ProxyHandler(), urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(), urllib.request.HTTPDefaultErrorHandler(),
              urllib.request.HTTPErrorProcessor(), _Redirects(), urllib.request.UnknownHandler()):
        o.add_handler(h)
    return o


def _open(url, role, headers, timeout):
    check_url(url, role)
    r = _opener().open(urllib.request.Request(url, headers=headers), timeout=timeout)
    check_url(r.geturl(), "hop")
    return r


def _get(url, timeout=20, role="api"):
    with _open(url, role, {"Accept": "application/vnd.github+json", "User-Agent": "hypnomix-app"}, timeout) as r:
        return r.read()


def good_tag(t):
    return bool(t) and isinstance(t, str) and TAG.fullmatch(t) is not None


def _num(tag):
    return tag[1:] if str(tag).startswith("v") else str(tag)


def _clean_assets(rel):
    """Only the installers and checksum file this app knows by name, at addresses that pass check_url and that sit in
    this release's own download folder: .../releases/download/<tag_name>/<name>. A release can't point at another
    version's files (an older installer under a newer name). The tag is rel['tag_name'], already a plain version."""
    out, tag = {}, rel.get("tag_name", "")
    for a in rel.get("assets") or []:
        try:
            name = a["name"]
            if name != os.path.basename(name) or name not in ASSETS:
                continue
            u = check_url(a["browser_download_url"], "asset")
            if not _local(u):
                parts = u.path.split("/")                       # ['', owner, repo, 'releases', 'download', tag, name]
                if "%" in u.path or len(parts) != 7 or parts[4] != "download" or parts[6] != name or \
                        not good_tag(tag) or _num(parts[5]) != _num(tag):
                    continue
            out[name] = dict(url=a["browser_download_url"], size=int(a.get("size", 0) or 0))
        except (KeyError, TypeError, ValueError, RuntimeError, AttributeError):
            continue
    return out


def check(force=False):
    s = load()
    if not force and (not s.get("auto", True) or time.time() - s.get("checked", 0) < DAY):
        return view()
    if force:
        s.pop("skip", None)                                     # asked by hand: show it again even after "Later"
    try:
        rel = json.loads(_get(API))
        tag = rel.get("tag_name", "")
        if not good_tag(tag) or rel.get("draft") or rel.get("prerelease"):
            s.update(checked=time.time(), error="the newest release has a name HypnoMix doesn't recognise, so it was ignored",
                     latest="", assets={})
            save(s)
            return view()
        try:
            page = str(check_url(rel.get("html_url", ""), "asset").geturl()) if rel.get("html_url") else ""
        except RuntimeError:
            page = ""                                           # shown as a link: only ever a real release page
        s.update(checked=time.time(), error="", latest=tag.lstrip("v"), page=page,
                 notes=(rel.get("body") or "").split("\n## Security scan")[0].strip()[:4000],
                 published=rel.get("published_at", ""), assets=_clean_assets(rel))
    except Exception as e:
        s.update(checked=time.time(), error=f"couldn't reach GitHub ({type(e).__name__})")
    save(s)
    return view()


def view():
    s = load()
    cur, latest = current(), s.get("latest", "")
    if not good_tag(latest):                                    # an old or edited state file: ignore it
        latest = ""
    newer = bool(latest) and vkey(latest) > vkey(cur)
    name = asset_name()
    a = _assets(s).get(name) if name else None
    try:                                                        # the link is shown on the page: only a real release page
        page = str(check_url(s["page"], "asset").geturl()) if s.get("page") else ""
    except (RuntimeError, ValueError, TypeError, KeyError):
        page = ""
    size = a.get("size", 0) if a else 0
    # an installed app on a release that carries no installer for this computer: said plainly, and nothing is offered
    no_download = bool(newer and name and not a)
    return dict(current=cur, latest=latest, newer=newer, skipped=s.get("skip") == latest, auto=bool(s.get("auto", True)),
                kind=kind(), no_download=no_download,
                one_click=bool(newer and a), size=size if isinstance(size, int) else 0, page=page,
                notes=str(s.get("notes", "")), published=str(s.get("published", "")), checked=s.get("checked", 0),
                error=str(s.get("error", "")), job=dict(JOB))


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
        paths.tighten_home()
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
        latest = s.get("latest", "")
        if not good_tag(latest) or name not in ASSETS or name != os.path.basename(name):
            raise RuntimeError("the release isn't one HypnoMix recognises, so nothing was downloaded")
        if vkey(latest) <= vkey(current()):
            raise RuntimeError("that isn't a newer version than the one you have, so nothing was downloaded")
        have = _assets(s)                                       # checked again here: the state file is only a cache
        ok = _clean_assets({"tag_name": latest, "assets": [dict(name=n, browser_download_url=v.get("url"), size=v.get("size", 0))
                                                           for n, v in have.items() if n in (name, "SHA256SUMS.txt")]})
        if name not in ok or "SHA256SUMS.txt" not in ok:
            raise RuntimeError("the release has no installer or checksum list at a trusted address")
        a = ok[name]
        sums = _get(ok["SHA256SUMS.txt"]["url"], 60, "asset").decode()
        want = next((ln.split()[0] for ln in sums.splitlines() if ln.split()[-1:] == [name]), "")
        if not re.fullmatch(r"[0-9a-f]{64}", want):
            raise RuntimeError("the release has no checksum for this file")
        paths.private_dir(DIR)
        dest, part = DIR / f"{latest}-{name}", DIR / f"{latest}-{name}.part"
        if dest.exists() and _sha(dest) == want:
            JOB.update(status="ready", file=str(dest), sha=want, got=dest.stat().st_size, size=dest.stat().st_size)
            return
        with _open(a["url"], "asset", {"User-Agent": "hypnomix-app"}, 60) as r, open(part, "wb") as f:
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
            if old != dest and old.name != "update.log" and not old.name.startswith("update-helper"):
                old.unlink(missing_ok=True)
        JOB.update(status="ready", file=str(dest), sha=want)
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
APP="$1"; DMG="$2"; APP_PID="$3"; SERVER_PID="$4"; ENGINE_PID="$5"; LOG="$6"; SHA="$7"; VER="$8"
exec >>"$LOG" 2>&1
echo "== $(date) update $APP from $DMG"
case "$APP" in */Hypnomix.app) ;; *) echo "not an app path: $APP"; exit 1 ;; esac
[ -d "$APP" ] && [ -f "$DMG" ] || { echo "missing app or dmg"; exit 1; }
GOT=$(/usr/bin/shasum -a 256 "$DMG" | cut -d' ' -f1)
[ -n "$SHA" ] && [ "$GOT" = "$SHA" ] || { echo "the image is not the file that was checked; nothing was installed"; exit 1; }
# The disk image is opened in a folder of its own (in $TMPDIR, as everything else of this app is). Whatever way the helper
# ends (a failed check, a failed copy, a kill), that folder is let go: the image is detached and the folder removed.
MNT=$(mktemp -d "${TMPDIR:-/tmp}/hypnomix-update.XXXXXX") || { echo "could not make a temporary folder"; exit 1; }
MOUNTED=0
unmount() {
  if [ "$MOUNTED" = 1 ]; then hdiutil detach -quiet "$MNT" 2>/dev/null || hdiutil detach -force -quiet "$MNT" 2>/dev/null; MOUNTED=0; fi
  rmdir "$MNT" 2>/dev/null
}
trap unmount EXIT
hdiutil attach -nobrowse -readonly -mountpoint "$MNT" "$DMG" && MOUNTED=1 || exit 1
[ -d "$MNT/Hypnomix.app" ] || { echo "no Hypnomix.app in the image"; exit 1; }
NEW="$APP.updating"
/bin/rm -rf "$NEW"
ditto "$MNT/Hypnomix.app" "$NEW" || exit 1
unmount
# Integrity check only, NOT publisher verification: this shows the copied bundle is whole and unchanged since it was
# signed (ad hoc or with a certificate). It does not show who signed it. If it fails, the old app stays untouched.
/usr/bin/codesign --verify --deep --strict "$NEW" || { echo "the new app failed the signature integrity check; the old app was left in place"; /bin/rm -rf "$NEW"; exit 1; }
# The new app must also say it is the version the release claimed (a plain number compare, "1.2.0" equals "1.2"), so
# an older app can't be installed under a newer release name. Again the old app is left in place if it differs.
# "-" means a file you named yourself on the command line: there is no release claim to compare with.
norm() { echo "$1" | /usr/bin/sed -E 's/^v//; s/(\.0+)+$//'; }
GOTVER=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$NEW/Contents/Info.plist" 2>/dev/null)
[ "$VER" = "-" ] || { [ -n "$VER" ] && [ -n "$GOTVER" ] && [ "$(norm "$GOTVER")" = "$(norm "$VER")" ]; } || { echo "the new app says it is version '$GOTVER', not '$VER'; the old app was left in place"; /bin/rm -rf "$NEW"; exit 1; }
# stop-begin
# The app stops its audio engine itself when it quits (up to about 15 s: 8 s for it to end, then 5 s after a kill), so
# the helper waits for the app, the server AND the engine to be gone before it touches the bundle, and for much longer
# than that. Only after the wait does it kill what is left, the engine's whole process group included, so no engine
# is left running from a bundle that is about to be moved or holding the sound card.
GRACE="${HYPNOMIX_UPDATE_GRACE:-45}"
for p in "$APP_PID" "$SERVER_PID"; do [ -n "$p" ] && kill "$p" 2>/dev/null; done
alive() { for p in "$APP_PID" "$SERVER_PID" "$ENGINE_PID"; do [ -n "$p" ] && kill -0 "$p" 2>/dev/null && return 0; done; return 1; }
n=0; while alive && [ "$n" -lt $((GRACE * 4)) ]; do sleep 0.25; n=$((n + 1)); done
alive && echo "still running after ${GRACE}s: stopping it now"
for p in "$APP_PID" "$SERVER_PID"; do [ -n "$p" ] && kill -9 "$p" 2>/dev/null; done
if [ -n "$ENGINE_PID" ] && kill -0 "$ENGINE_PID" 2>/dev/null; then kill -9 -- "-$ENGINE_PID" 2>/dev/null; kill -9 "$ENGINE_PID" 2>/dev/null; fi
# stop-end
OLD="$APP.old"
/bin/rm -rf "$OLD"
mv "$APP" "$OLD" && mv "$NEW" "$APP" || { echo "swap failed"; [ -d "$OLD" ] && [ ! -d "$APP" ] && mv "$OLD" "$APP"; exit 1; }
/bin/rm -rf "$OLD"
echo "swapped; opening"
if [ -n "$HYPNOMIX_PORT" ]; then    # a test copy: reopen it the same way, beside the real one
  open -n --env HYPNOMIX_PORT="$HYPNOMIX_PORT" --env HOME="$HOME" --env HYPNOMIX_UPDATE_URL="$HYPNOMIX_UPDATE_URL" "$APP"
else open "$APP"; fi
'''

WIN_HELPER = r'''# HypnoMix update helper: run the new setup silently over this install, then start HypnoMix again.
param([string]$Setup, [string]$App, [string]$Log, [string]$Sha)
Start-Transcript -Path $Log -Append | Out-Null
if (-not $Sha -or (Get-FileHash -Algorithm SHA256 -LiteralPath $Setup).Hash.ToLower() -ne $Sha.ToLower()) {
  Write-Host "the setup is not the file that was checked; nothing was installed"
  Stop-Transcript | Out-Null
  exit 1
}
Start-Sleep -Seconds 1
$p = Start-Process -FilePath $Setup -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=`"$App`"" -Wait -PassThru
Write-Host "setup exit $($p.ExitCode)"
if (Test-Path "$App\python\pythonw.exe") {
  Start-Process -FilePath "$App\python\pythonw.exe" -ArgumentList "`"$App\launcher.pyw`"", "--quiet" -WorkingDirectory $App
}
Stop-Transcript | Out-Null
'''


class Unsaved(Exception):
    """The DAW session has changes that were not saved: the install is refused (HTTP 409), nothing is closed."""


def unsaved():
    """True while the open DAW session has unsaved changes. The server keeps that flag (daw.dirty(): any changing engine
    call since the last save, from the page or the Assistant, or the engine's own unsaved flag for a change a command
    made straight in the engine). An app that has no such function, or no session, or no
    engine, has nothing to lose; a function that fails is read as 'nothing to lose' too, so a fault in the optional DAW
    side can never stop an update for good (the person can still quit the app and download the new one)."""
    try:
        from hypnomix.app import daw
        f = getattr(daw, "dirty", None)
        return bool(f()) if callable(f) else False
    except Exception:
        return False


def engine_pid():
    """The process id of the engine this server started (its own process group), as text, or '' when there is none
    (not DAW mode, a window it only attached to). The Mac helper waits for it to be gone before it swaps the app."""
    try:
        from hypnomix.app import daw
        e = getattr(daw, "ENGINE", None)
        p = getattr(e, "proc", None) if e is not None and getattr(e, "mode", None) == "engine" else None
        return str(int(p.pid)) if p is not None and p.poll() is None else ""
    except Exception:
        return ""


def install(path=None):
    """Start the helper and return; the helper stops this server, so the page waits for the new version.
    The staged file is hashed again here against the SHA-256 the download was checked with, and the helper checks it
    once more before it opens or runs it. With no path it is the downloaded update (and must be a newer version);
    with a path (the command line) the file is hashed now, because there is no earlier check to compare with."""
    k = kind()
    if not k:
        raise ValueError("only the installed app updates itself; in a source checkout run: git pull && uv pip install -e .")
    if unsaved():
        raise Unsaved("Your DAW session has changes that are not saved, and installing the update closes it. Save it first "
                      "(Save in the Studio tab, or ⌘S there), then install the update.")
    f = Path(path or JOB.get("file") or "")
    if not f.is_file():
        raise ValueError("download the update first")
    ver = "-"
    if path:
        want = _sha(f)
    else:
        want, v = JOB.get("sha", ""), view()
        if not v["newer"] or f.resolve() != (DIR / f"{v['latest']}-{asset_name()}").resolve():
            raise ValueError("that file isn't the update for a newer version: check for updates and download it again")
        if not re.fullmatch(r"[0-9a-f]{64}", want or ""):
            raise ValueError("download the update first")
        ver = v["latest"]
    if _sha(f) != want:
        f.unlink(missing_ok=True)
        JOB.update(status="error", error="the downloaded file changed after it was checked, so it was deleted. Download it again")
        raise RuntimeError(JOB["error"])
    paths.private_dir(DIR)
    log = DIR / "update.log"
    if k == "mac":
        helper = DIR / "update-helper.sh"
        paths.write_private(helper, MAC_HELPER, 0o700)
        app = app_root()
        if not os.access(app.parent, os.W_OK):
            raise ValueError(f"can't write to {app.parent}: download the new version from the website instead")
        parent = subprocess.run(["ps", "-p", str(os.getppid()), "-o", "comm="], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
        app_pid = str(os.getppid()) if parent.endswith("/Hypnomix") or parent == "Hypnomix" else ""   # only the app's window
        subprocess.Popen(["/bin/bash", str(helper), str(app), str(f), app_pid, str(os.getpid()), engine_pid(), str(log), want, ver],
                         start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        helper = DIR / "update-helper.ps1"
        paths.write_private(helper, WIN_HELPER, 0o600, encoding="utf-8")
        cmd = (f'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{helper}" '
               f'-Setup "{f}" -App "{app_root()}" -Log "{log}" -Sha "{want}"')
        # started through WMI so it isn't a child of this server: the setup stops the server's whole process tree
        ps = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=" +
              "'" + cmd.replace("'", "''") + "'}; exit $r.ReturnValue")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, encoding="utf-8", errors="replace",
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
    except Unsaved as e:
        return 409, {"error": str(e), "dirty": True}
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
