#!/usr/bin/env python3
"""HypnoMix Studio as an add-on: the engine is fetched once, on a click, and only then.

HypnoMix Studio is HypnoMix's own DAW. Its engine is a separate program under the
GNU General Public License (version 2 or later); HypnoMix itself is MIT and holds none of its code. There is one
HypnoMix app and one installer for everyone: the engine is not inside them. It is published as an archive of its own
for each platform and added from Setup (or with this command), only when you ask.

  hypnomix engine                     what is added, what could be, and where it would go (the same as `status`)
  hypnomix engine status              the same, in words
  hypnomix engine where               the folder the engine lives in (nothing is created)
  hypnomix engine install             report first: what would be fetched, from where, checked against what; changes nothing
  hypnomix engine install --yes       fetch it (https, a size limit and a deadline), check its SHA-256 BEFORE anything is
                                      unpacked, unpack it safely, check the kit (the engine program, the licence text and
                                      the source notice), and move it into place in one step
  hypnomix engine remove              report first: what would be removed
  hypnomix engine remove --yes        remove it (refused while the engine is running)

Where: <HypnoMix home>/engine/<version>/ (the home is ~/.hypnomix, or the folder HYPNOMIX_HOME names). The address and the
SHA-256 come only from hypnomix/app/engine_addon.json, which ships inside this app; nothing in a request, a file on
disk or an environment variable can name another address. The first engine, 0.1.0, is published for Apple-silicon Macs
(mac-arm64) only. Where the manifest names no archive for this computer, the command says "HypnoMix Studio is not available
for <place> yet" and fetches nothing. A failed or interrupted add leaves nothing
half-added and can simply be run again. A newer app may name a newer engine: it says so, and adding it keeps the old one
until the new one has run once, then removes the old one.

Nothing here runs by itself: the app does not add or remove the engine unless you click, and this command does nothing but
report unless you add --yes.
"""
import argparse
import gzip
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import sys
import tarfile
import threading
import time
import unicodedata
import zlib
from pathlib import Path

NAME = "hypnomix-engine"                       # the program, bin/hypnomix-engine inside a kit (also daw.NAME)
MANIFEST = Path(__file__).with_name("engine_addon.json")
NOT_YET = "HypnoMix Studio is not available yet."
WHAT = ("HypnoMix Studio is HypnoMix's own DAW, built on Ardour, a free open-source DAW. It is a download of about 30 MB (about 105 MB once unpacked), fetched once from "
        "the project's release page and checked against a fingerprint before it is used, and it runs only while the DAW "
        "view is open. You can remove it any time.")
LICENCE = ("HypnoMix Studio's engine is a separate program under the GNU General Public License (version 2 or later), "
           "downloaded on its own; HypnoMix itself is MIT.")

# limits (module level so a test can lower them)
DEADLINE_S = 30 * 60                           # the whole fetch
SLACK = 1 << 20                                # the archive may be this much over the size the manifest names, no more
MAX_UNPACKED = 1 << 30                         # the unpacked kit: about 100 MB is normal
MAX_ENTRIES = 20000
RUNFILE = ".running"                           # engine/.running: written while an engine from here runs, so every process can see it
STALE_S = 3600                                 # a half-made folder older than this is from an add that was cut off
MAX_PID = 1 << 31                              # no process id is as large (os.killpg takes a C int)
FIXED_TIME = 1735689600                        # the time every entry of an archive made here carries (2025-01-01 UTC)

# A version, and so the name of a folder this add-on made: digits and dots, then at most a release tag ("0.1.0", "0.2.0-rc1").
# Nothing else in engine/ matches, so remove() and the tidying never touch a file or folder that is not the add-on's.
VERSION = re.compile(r"(?=.{1,40}$)[0-9]+(?:\.[0-9]+)*(?:-(?:rc|alpha|beta|dev|pre)[0-9.]{0,10})?")
SHA = re.compile(r"[0-9a-f]{64}")
PLATFORMS = ("mac-arm64", "mac-intel", "windows-x64", "linux-x64")
_PLACE = {"mac": "the Mac", "windows": "Windows", "linux": "Linux"}
LOCK = threading.Lock()
JOB = {"status": "idle", "got": 0, "size": 0, "error": ""}      # idle | downloading | verifying | unpacking | checking | installing | done | error


class AddonError(Exception):
    """Said to the person in one plain sentence; nothing was changed (or what was started was undone)."""


# ---------------------------------------------------------------- the manifest (shipped inside the app)
def manifest():
    """The shipped manifest: {"engine": version, "platforms": {key: {"url", "sha256", "size"}}}, each platform only when
    its entry is whole (an https address, a SHA-256, a size). A damaged file gives an engine of "" and no platforms."""
    try:
        d = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"engine": "", "platforms": {}}
    if not isinstance(d, dict):
        return {"engine": "", "platforms": {}}
    ver = d.get("engine")
    ver = ver if isinstance(ver, str) and VERSION.fullmatch(ver) else ""
    out = {}
    plats = d.get("platforms") if isinstance(d.get("platforms"), dict) else {}
    for key, e in plats.items():
        if not (ver and isinstance(key, str) and isinstance(e, dict)):
            continue
        url, sha, size = e.get("url"), e.get("sha256"), e.get("size")
        if not (isinstance(url, str) and _https(url) and isinstance(sha, str) and SHA.fullmatch(sha.lower())
                and isinstance(size, int) and not isinstance(size, bool) and size > 0):
            continue
        out[key] = {"url": url, "sha256": sha.lower(), "size": size}
    return {"engine": ver, "platforms": out}


def _https(url):
    from urllib.parse import urlsplit
    try:
        u = urlsplit(url)
        return u.scheme == "https" and bool(u.hostname) and not u.username and not u.password and not u.fragment
    except ValueError:
        return False


def platform_key():
    """mac-arm64, mac-intel, windows-x64 or linux-x64 for this computer, or "" for any other."""
    m = platform.machine().lower()
    if sys.platform == "darwin":
        return "mac-arm64" if m in ("arm64", "aarch64") else "mac-intel" if m in ("x86_64", "amd64") else ""
    if sys.platform == "win32":
        return "windows-x64" if m in ("amd64", "x86_64") else ""
    if sys.platform.startswith("linux"):
        return "linux-x64" if m in ("x86_64", "amd64") else ""
    return ""


def _place(key=None):
    key = platform_key() if key is None else key
    return _PLACE.get(key.split("-")[0], "this computer") if key else "this computer"


def entry():
    """The archive for this computer in the shipped manifest, or None (no address published for it)."""
    return manifest()["platforms"].get(platform_key())


def unavailable_message():
    """Why nothing can be added here, in one plain sentence."""
    plats = manifest()["platforms"]
    if not plats:
        return NOT_YET + ("" if platform_key().startswith("mac") else f" It is being made for the Mac first, so it is not yet for {_place()}.")
    key = platform_key()
    if key.startswith("mac") and any(k.startswith("mac") for k in plats):     # the other kind of Mac has one: say which has not
        return f"HypnoMix Studio is not available for {'Intel Macs' if key == 'mac-intel' else 'Apple-silicon Macs'} yet."
    return f"HypnoMix Studio is not available for {_place()} yet."


# ---------------------------------------------------------------- where it lives
def home():
    return Path(os.environ.get("HYPNOMIX_HOME") or "~/.hypnomix").expanduser()      # read now, so HYPNOMIX_HOME moves it


def root():
    return home() / "engine"


def program(ver):
    return root() / ver / "bin" / NAME


def _vkey(v):
    return tuple(int(x) for x in re.findall(r"[0-9]+", v))


def installed_versions():
    """The versions on this computer (each a folder with its program), newest first."""
    out = []
    try:
        for p in root().iterdir():
            if VERSION.fullmatch(p.name) and p.is_dir() and not p.is_symlink() and _runnable(program(p.name)):
                out.append(p.name)
    except OSError:
        pass
    return sorted(out, key=lambda v: (_vkey(v), v), reverse=True)


def _runnable(p):
    return p.is_file() and os.access(p, os.X_OK)


def find():
    """The engine program this app uses from the add-on: the version the manifest names, else the newest other one on
    disk (kept until the new one has run once), or None."""
    cur = manifest()["engine"]
    have = installed_versions()
    order = ([cur] if cur in have else []) + [v for v in have if v != cur]
    return program(order[0]) if order else None


def _under_root(prog):
    r, q = os.path.realpath(root()), os.path.realpath(str(prog))
    return q.startswith(r + os.sep)


def mark_running(prog, pid):
    """The app started the engine at prog (process pid): write engine/.running, so the command line and the Assistant,
    which are other processes, can see it runs. Only for an engine inside the add-on folder. Never raises."""
    try:
        if not _under_root(prog):
            return
        f = root() / RUNFILE
        tmp = f.with_name(RUNFILE + f".{secrets.token_hex(3)}")
        tmp.write_text(json.dumps(dict(pid=int(pid), program=str(prog), app=os.getpid(), started=time.time())), encoding="utf-8")
        os.replace(tmp, f)
    except Exception:
        pass


def clear_running(pid):
    """The engine process pid has ended: remove engine/.running when it is the one named there. Never raises."""
    try:
        f = root() / RUNFILE
        if _marked_pid() == pid:
            f.unlink()
    except Exception:
        pass


def _marked_pid():
    try:
        d = json.loads((root() / RUNFILE).read_text(encoding="utf-8"))
        pid = d.get("pid") if isinstance(d, dict) else None
        # a process id is a small number: a forged or damaged marker with a huge one would raise OverflowError in os.killpg
        return pid if isinstance(pid, int) and not isinstance(pid, bool) and 1 < pid < MAX_PID else 0
    except (OSError, ValueError):
        return 0


def _alive(pid):
    """Is anything of the process group pid (the engine starts its own) still there? A pid that is gone, or was never a
    group of its own, is not."""
    if not pid:
        return False
    if os.name == "nt":
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return bool(ok) and code.value == 259                                # STILL_ACTIVE
        except Exception:
            return False
    try:
        os.killpg(pid, 0)                                                        # signal 0 only asks
        return True
    except PermissionError:
        return True
    except (OSError, OverflowError, ValueError):
        return False


def running():
    """Is an engine from the add-on running now, started by this app process or by another (a stale marker, left by an
    engine that is gone, does not count)? Then it must not be removed or replaced."""
    try:
        from hypnomix.app import daw
        e = daw.ENGINE
        if e.mode == "engine" and e.proc is not None and e.proc.poll() is None:
            return True
    except Exception:
        pass
    return _alive(_marked_pid())


def _recorded(ver):
    """The SHA-256 of the archive the folder for ver was made from (its ADDON.json), or "" when nothing says."""
    try:
        d = json.loads((root() / ver / "ADDON.json").read_text(encoding="utf-8"))
        sha = d.get("sha256") if isinstance(d, dict) else ""
        return sha if isinstance(sha, str) and SHA.fullmatch(sha) else ""
    except (OSError, ValueError):
        return ""


def _stale(ver, e):
    """Was the folder for ver made from a different archive than the manifest now names for the same version (a rebuilt
    kit published under the same version string)? A folder with no record is left alone."""
    rec = _recorded(ver)
    return bool(e) and bool(rec) and rec != e["sha256"]


def _size_text(n):
    return f"{n / 1e6:.0f} MB" if n else "expected to be about 100 MB"


def state():
    """Everything a page or a command says about the add-on."""
    m, key = manifest(), platform_key()
    e = m["platforms"].get(key)
    have = installed_versions()
    cur = m["engine"]
    f = find()
    current = bool(cur) and cur in have and not _stale(cur, e)
    rebuilt = bool(cur) and cur in have and not current
    needs_update = bool(e) and bool(have) and not current
    job = dict(JOB)
    if e and current:
        msg = f"HypnoMix Studio {cur} is added."
    elif e and rebuilt:
        msg = (f"A rebuilt HypnoMix Studio {cur} has been published: the one added is not the file this version of HypnoMix names. "
               "Add it to replace the old one.")
    elif e and needs_update:
        msg = (f"This version of HypnoMix works with HypnoMix Studio engine {cur}, and {have[0]} is what is added now. "
               "Add the new one: the old one is kept until the new one has run once.")
    elif e:
        msg = "HypnoMix Studio is not added yet: it is fetched once, on your click, from the project's release page."
    elif have:
        msg = f"HypnoMix Studio {have[0]} is added."
    else:
        msg = unavailable_message()
    return dict(available=bool(e), platform=key, version=cur, installed=have[0] if have else "", versions=have, current=current,
                needs_update=needs_update, size=e["size"] if e else 0, size_text=_size_text(e["size"] if e else 0),
                where=str(root() / cur) if cur else str(root()), program=str(f) if f else "", running=running(),
                message=msg, what=WHAT, licence=LICENCE, job=job, busy=job["status"] in _BUSY)


_BUSY = ("downloading", "verifying", "unpacking", "checking", "installing")


def brief():
    """What the DAW view needs: is there an engine from the add-on, and is a newer one wanted."""
    try:
        s = state()
        return dict(available=s["available"], installed=s["installed"], version=s["version"], current=s["current"],
                    needs_update=s["needs_update"], message=s["message"] if s["needs_update"] or s["available"] else "")
    except Exception:
        return dict(available=False, installed="", version="", current=False, needs_update=False, message="")


# ---------------------------------------------------------------- the kit check (the same as packaging/mac/check_kit.sh)
GPL_TEXT = re.compile(r"GNU GENERAL PUBLIC LICENSE")
NOTICE_TESTS = (re.compile(r"general public licen[sc]e", re.I),
                re.compile(r"version 2|v2|gpl-?2|2 or later", re.I),
                re.compile(r"source", re.I),
                re.compile(r"https?://|will be published with the first release that includes the engine", re.I),
                re.compile(r"(version|commit|revision|built from)[^A-Za-z0-9\n]+[A-Za-z0-9._-]*[0-9a-f.]{4,}", re.I))
HOME_PATH = re.compile(rb"/Users/(?!Shared/)[A-Za-z0-9._-]+/")
NO_LICENCE = "the engine kit has no licence text: COPYING (the GNU General Public License) must be at the top of the kit"
NO_NOTICE = ("the engine kit has no source notice: SOURCE.txt must say the licence (GNU General Public License, version 2 or "
             "later), that the source is available and where or when it is published, and the version or commit it was built from")


def _builder_strings():
    out = []
    h = str(Path.home())
    if h and h != "/":
        out.append(h.encode())
    try:
        import getpass
        u = getpass.getuser()
        if len(u) >= 5:
            out.append(re.compile(rb"(?<![A-Za-z0-9_])" + re.escape(u.encode()) + rb"(?![A-Za-z0-9_])"))
    except Exception:
        pass
    return out


def _files(kit):
    for dirpath, dirs, files in os.walk(kit):
        for n in sorted(dirs) + sorted(files):
            yield Path(dirpath) / n


def _has(path, pat, overlap=512):
    """Does the file contain the pattern (bytes or compiled), read in chunks."""
    rx = re.compile(re.escape(pat)) if isinstance(pat, bytes) else pat
    tail = b""
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                return False
            if rx.search(tail + b):
                return True
            tail = (tail + b)[-overlap:]


def kit_problems(kit, builder=False):
    """What is wrong with an engine kit folder, one plain sentence each (an empty list: it is fit). The same checks as
    packaging/mac/check_kit.sh: the engine program (bin/ and lib/), COPYING with the GNU General Public License, SOURCE.txt
    with the notice, no symbolic links, and no home path of the person who built it inside any file. With builder=True
    this computer's own home path and login name are looked for too (that is the builder's check, made before an archive is
    written; on the computer that adds the engine they say nothing)."""
    kit, bad = Path(kit), []
    if not kit.is_dir() or kit.is_symlink():
        return [f"no engine kit folder: {kit.name}"]
    for rel in ("bin/" + NAME, "lib/" + NAME):
        p = kit / rel
        if not (p.is_file() and not p.is_symlink() and os.access(p, os.X_OK)):
            return [f"this is not a HypnoMix Studio engine kit (no {rel})"]
    try:
        lic = kit / "COPYING"
        if lic.is_symlink() or not lic.is_file() or lic.stat().st_size == 0 or not GPL_TEXT.search(lic.read_text(encoding="utf-8", errors="ignore")):
            bad.append(NO_LICENCE)
        src = kit / "SOURCE.txt"
        text = src.read_text(encoding="utf-8", errors="ignore") if src.is_file() and not src.is_symlink() else ""
        if not text.strip() or not all(t.search(text) for t in NOTICE_TESTS):
            bad.append(NO_NOTICE)
        odd = sorted({p.relative_to(kit).as_posix() for p in _files(kit)
                      if any(unicodedata.category(ch) in ("Cc", "Cf") for ch in p.name)})
        if odd:                                                   # a name that can hide itself or rewrite a line the person reads
            bad.append("the engine kit has a file name with a control or invisible character in it: "
                       + ", ".join(repr(o) for o in odd[:3]) + (" and more" if len(odd) > 3 else ""))
        links = [p for p in _files(kit) if p.is_symlink()]
        if links:
            bad.append("the engine kit has symbolic links (a link could point out of the folder it is added to)")
        pats = [HOME_PATH] + (_builder_strings() if builder else [])
        hits = sorted({str(p.relative_to(kit)) for p in _files(kit) if p.is_file() and not p.is_symlink()
                       and any(_has(p, q) for q in pats)})
        if hits:
            bad.append("the engine kit has the builder's home path or login name inside it (a public download must not): "
                       + ", ".join(hits[:5]) + (" and more" if len(hits) > 5 else ""))
    except OSError as e:
        bad.append(f"the engine kit could not be read ({e.strerror or e})")
    return bad


# ---------------------------------------------------------------- adding it
def _tidy_staging(older_than=STALE_S):
    """Remove half-made folders (.incoming-*, .old-*) left by an add that was cut off. They are only ever made here."""
    try:
        entries = list(root().iterdir())
    except OSError:
        return
    for p in entries:
        try:
            if p.name.startswith((".incoming-", ".old-")) and (older_than is None or time.time() - p.stat().st_mtime > older_than):
                _rm(p)
        except OSError:
            pass


def _rm(p):
    p = Path(p)
    if p.is_symlink() or p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p, ignore_errors=True)


def _free(need, where):
    from hypnomix.store import install as I
    try:
        I.check_space(need, where)
    except I.StoreError as e:
        raise AddonError(str(e))


def install(progress=None, cancel=None):
    """Add HypnoMix Studio for this computer -> state(). AddonError (one plain sentence) when it cannot be added; then
    nothing is half-added and it can be run again. Needs the shipped manifest to name an archive for this platform; an
    engine already added and whole is left as it is."""
    if not LOCK.acquire(blocking=False):
        raise AddonError("HypnoMix Studio is being added or removed right now: wait for it to finish.")
    try:
        _install(progress, cancel)
    except BaseException as e:
        JOB.update(status="error", error=str(e) if isinstance(e, AddonError) else f"adding HypnoMix Studio failed: {e}")
        raise
    finally:
        LOCK.release()
    return state()


def _install(progress, cancel):
    from hypnomix.core import paths
    from hypnomix.store import install as I
    m, e = manifest(), entry()
    JOB.update(status="downloading", got=0, size=e["size"] if e else 0, error="")
    if not e:
        raise AddonError(unavailable_message())
    ver, final = m["engine"], root() / m["engine"]
    if not kit_problems(final) and _runnable(program(ver)) and not _stale(ver, e):
        JOB.update(status="done")                                   # already there, whole and the file the manifest names: nothing to fetch
        return
    if (final.exists() or final.is_symlink()) and running():
        raise AddonError("HypnoMix Studio is running: close the DAW view (or stop the engine there) first, then add it again.")
    paths.private_dir(root())
    _tidy_staging()
    _free(e["size"] * 3 + (256 << 20), root())
    stage = root() / f".incoming-{secrets.token_hex(4)}"
    deadline = time.monotonic() + DEADLINE_S
    try:
        stage.mkdir(mode=0o700)
        arc = stage / "engine.tar.gz"                               # the name picks the unpacker: a tar, whatever the server calls it

        def tick(what, got, total):
            JOB.update(got=got, size=total or e["size"])
            if progress:
                progress(what, got, total or e["size"])

        try:
            digest = I.download(e["url"], arc, None, e["size"], tick, e["size"] + SLACK, deadline, cancel)
        except I.StoreError as ex:
            raise AddonError(f"{ex}")
        JOB.update(status="verifying")
        if digest != e["sha256"]:                                   # BEFORE anything is unpacked
            _rm(arc)
            raise AddonError("The download is not the file the project published (its SHA-256 fingerprint does not match), "
                             "so it was deleted and nothing was added. Try again later.")
        JOB.update(status="unpacking")
        kit = stage / "kit"
        try:
            I.unpack(arc, kit, I.Budget(arc.stat().st_size, deadline, cancel, MAX_UNPACKED, MAX_ENTRIES))
        except I.StoreError as ex:
            raise AddonError(f"The engine archive was refused: {ex}")
        except (KeyError, ValueError, EOFError, tarfile.TarError, zlib.error) as ex:    # a damaged archive that passed the fingerprint
            raise AddonError(f"The engine archive was refused: it is damaged and could not be unpacked ({type(ex).__name__}).")
        _rm(arc)
        JOB.update(status="checking")
        why = kit_problems(kit)
        if why:
            raise AddonError("The engine archive is not a complete kit, so nothing was added: " + "; ".join(why))
        (kit / "ADDON.json").write_text(json.dumps(dict(engine=ver, sha256=e["sha256"], platform=platform_key(),
                                                        added=time.strftime("%Y-%m-%d %H:%M")), indent=1), encoding="utf-8")
        JOB.update(status="installing")
        _swap(kit, final)
        JOB.update(status="done")
    finally:
        _rm(stage)


def _swap(kit, final):
    """Put the checked kit at final in one step. A kit already there (a second add, or a damaged one) is moved aside first
    and put back if the new one cannot be placed."""
    if final.exists() or final.is_symlink():
        old = final.with_name(f".old-{secrets.token_hex(4)}")
        os.replace(final, old)
        try:
            os.replace(kit, final)
        except OSError:
            os.replace(old, final)
            raise
        _rm(old)
    else:
        os.replace(kit, final)


def start_install():
    """The app's click: add it in the background -> state() with the job running. Nothing when one is already running."""
    if JOB["status"] in _BUSY:
        return state()
    if not entry():
        raise AddonError(unavailable_message())
    JOB.update(status="downloading", got=0, size=entry()["size"], error="")

    def run():
        try:
            install()
        except Exception:
            pass                                                    # the page reads the job's error
    threading.Thread(target=run, daemon=True).start()
    return state()


# ---------------------------------------------------------------- removing it, and tidying old versions
def remove():
    """Remove every engine this add-on put on the computer -> state(). Refused, with one sentence, while the engine runs."""
    if not LOCK.acquire(blocking=False):
        raise AddonError("HypnoMix Studio is being added right now: wait for it to finish.")
    try:
        if running():                                               # from any process: the app's own, or the marker another process left
            raise AddonError("HypnoMix Studio is running: close the DAW view (or stop the engine there) first, then remove it.")
        try:
            entries = list(root().iterdir())
        except OSError:
            entries = []
        for p in entries:
            if VERSION.fullmatch(p.name) or p.name.startswith((".incoming-", ".old-", RUNFILE)):
                _rm(p)
        try:
            root().rmdir()                                          # only when nothing else is in it
        except OSError:
            pass
        JOB.update(status="idle", got=0, size=0, error="")
    finally:
        LOCK.release()
    return state()


def note_ran(prog):
    """The engine at prog reached READY. When it is the version this app names, the older versions are removed: they were
    kept only until the new one had run once. Returns the versions removed. Never raises."""
    try:
        r, q = os.path.realpath(root()), os.path.realpath(str(prog))
        if not q.startswith(r + os.sep):
            return []
        ver = Path(q[len(r) + 1:]).parts[0]
        if not VERSION.fullmatch(ver):
            return []
        gone = []
        if ver == manifest()["engine"]:
            for p in root().iterdir():
                if p.name != ver and VERSION.fullmatch(p.name) and p.is_dir() and not p.is_symlink():
                    _rm(p)
                    gone.append(p.name)
        return gone
    except Exception:
        return []


# ---------------------------------------------------------------- making an archive (the owner's side; nothing is uploaded)
def pack(kit, out):
    """Write the kit as one .tar.gz, the same bytes for the same kit: sorted entries, one fixed time, no owners, plain
    modes, no file name or time in the gzip header. The kit is checked first, the builder's own home path and login
    name included. -> dict(path, size, sha256, entries). AddonError when the kit is not fit."""
    kit, out = Path(kit), Path(out)
    why = kit_problems(kit, builder=True)
    if why:
        raise AddonError("; ".join(why))
    if out.exists():
        raise AddonError(f"{out} already exists: it is never overwritten")
    items = sorted(p.relative_to(kit).as_posix() for p in _files(kit))
    part = out.with_name(out.name + ".part")
    try:
        with open(part, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
                with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as t:
                    for rel in items:
                        p = kit / rel
                        ti = tarfile.TarInfo(rel)
                        ti.mtime, ti.uid, ti.gid, ti.uname, ti.gname = FIXED_TIME, 0, 0, "", ""
                        if p.is_dir():
                            ti.type, ti.mode = tarfile.DIRTYPE, 0o755
                            t.addfile(ti)
                        else:
                            ti.type, ti.size = tarfile.REGTYPE, p.stat().st_size
                            ti.mode = 0o755 if p.stat().st_mode & 0o111 else 0o644
                            with open(p, "rb") as f:
                                t.addfile(ti, f)
        h = hashlib.sha256()
        with open(part, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        os.replace(part, out)
    finally:
        if part.exists():
            part.unlink()
    return dict(path=str(out), size=out.stat().st_size, sha256=h.hexdigest(), entries=len(items))


# ---------------------------------------------------------------- the command
def _parser():
    ap = argparse.ArgumentParser(prog="hypnomix engine", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False)
    ap.add_argument("action", nargs="?", default="status", choices=["status", "install", "remove", "where"])
    ap.add_argument("--yes", action="store_true", help="really do it (install or remove); without it the command only reports")
    return ap


def _report(s):
    print(s["message"])
    print(f"  platform:   {s['platform'] or 'not one HypnoMix Studio is made for'}")
    print(f"  engine:     {s['version'] or 'none named'}   added: {', '.join(s['versions']) or 'none'}")
    print(f"  where:      {s['where']}")
    if s["running"]:
        print("  running:    yes (it cannot be removed or replaced until the DAW view is closed)")
    if s["available"]:
        print(f"  size:       {s['size_text']} (fetched once; checked against a SHA-256 fingerprint before it is used)")
    print(f"  {LICENCE}")


def main():
    a = _parser().parse_args()
    s = state()
    if a.action == "status":
        _report(s)
        print("Nothing was downloaded or changed.")
        return
    if a.action == "where":
        print(s["where"])
        return
    if a.action == "install":
        if not s["available"]:
            sys.exit(s["message"])
        if s["current"] and not a.yes:
            print(f"HypnoMix Studio {s['version']} is already added in {s['where']}. Nothing to do.")
            return
        e = entry()
        if not a.yes:
            from urllib.parse import urlsplit
            u = urlsplit(e["url"])
            print(f"Would add HypnoMix Studio {s['version']} ({s['size_text']}):")
            print(f"  fetch      https://{u.hostname}{u.path}")
            print(f"  check      SHA-256 {e['sha256']}")
            print(f"  into       {s['where']}")
            print(f"  {LICENCE}")
            print("Nothing was downloaded or changed. Run it again with --yes to add it.")
            return
        last = [-10]

        def say(what, got, total):
            pct = int(100 * got / total) if total else 0
            if pct >= last[0] + 10:
                last[0] = pct
                print(f"  downloading… {pct}%", flush=True)
        try:
            install(progress=say)
        except AddonError as ex:
            sys.exit(str(ex))
        print(f"HypnoMix Studio {s['version']} is added in {s['where']}.")
        return
    if not s["versions"]:                                           # remove
        print("HypnoMix Studio is not added: nothing to remove.")
        return
    if not a.yes:
        print(f"Would remove HypnoMix Studio ({', '.join(s['versions'])}) from {root()}."
              + (" The engine is running right now, so it would be refused: close the DAW view in the app first."
                 if s["running"] else " Close the DAW view in the app first: it is refused while the engine runs."))
        print("Nothing was changed. Run it again with --yes to remove it.")
        return
    try:
        remove()
    except AddonError as ex:
        sys.exit(str(ex))
    print("HypnoMix Studio is removed.")


if __name__ == "__main__":
    main()
