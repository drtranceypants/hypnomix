"""Download, unpack and install store items, and remove exactly what was installed.

The store works on macOS only for now (other systems get a plain message, see check_platform).

Safety rules, all enforced here:
  - downloads are HTTPS only, redirects included, and a redirect to another host never carries a token; a sha256 is
    checked when one is known (the catalogue's, or the digest GitHub publishes for the release asset), and a mismatch
    deletes the download. A download with nothing to check it against is NOT installed until the person confirms,
    in plain words, that it is not verified (NotVerified; --unverified on the command line)
  - limits: a maximum download size (the catalogue's size plus a margin, else DEFAULT_MAX_DOWNLOAD), an overall
    deadline, a free-space check before a big download and before copying, and while unpacking a cap on the entry
    count, on the total unpacked size and on the unpack ratio (a small archive that explodes is refused)
  - nothing from a download is ever run. Archives are unpacked with path checks (no absolute paths, no "..", no
    links that point outside; on a Python without tarfile's data filter a tar with any link is refused, and every
    member is checked before anything is extracted); a .dmg is attached read-only, without opening a window and
    without accepting a licence agreement for you, copied from and detached
  - plug-in bundles (.vst3 .component .clap .lv2 .vst) are copied into ~/Library/Audio/Plug-Ins/<Format>/; samples
    and SFZ content into ~/Music/Hypnomix Library/<Kind>/<Name>/
  - an installer package (.pkg) is never run for you: it is kept (marked as downloaded from the internet, so macOS
    checks it) and opened in Apple's Installer for you to read and run; it installs outside your home folder
  - every file and folder installed is written to a manifest, so uninstall removes exactly that (compared by real
    path: a link in a parent folder, or a plug-in folder itself, is refused) and an update replaces it; anything
    already there that the store did not install is left alone unless you confirm
  - HYPNOMIX_STORE_ROOT=/some/folder puts every target (plug-ins, library, manifest, downloads) under that folder,
    for tests and trying things out
"""
import hashlib
import http.client
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from pathlib import Path

from hypnomix.store import catalogue as C

PLUGIN_DIRS = {".vst3": "VST3", ".component": "Components", ".clap": "CLAP", ".lv2": "LV2", ".vst": "VST"}
FORMAT_OF = {".vst3": "VST3", ".component": "AU", ".clap": "CLAP", ".lv2": "LV2", ".vst": "VST"}
KIND_DIRS = {"drum kit": "Drum Kits", "sample pack": "Sample Packs", "sfz instrument": "SFZ Instruments"}
ARCHIVE_EXT = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.bz2", ".tbz2", ".7z", ".dmg")
JUNK = {"__MACOSX", ".DS_Store", ".fseventsd", ".Trashes", ".background"}
UA = "hypnomix-store"
_lock = threading.RLock()

# limits (module level so a test can lower them)
DEFAULT_MAX_DOWNLOAD = 2 * 10 ** 9      # bytes, when the catalogue and the publisher state no size
DOWNLOAD_MARGIN = 1.5                   # a catalogue size is rough: allow this much over it (+ DOWNLOAD_SLACK)
DOWNLOAD_SLACK = 64 * 10 ** 6
INSTALL_DEADLINE_S = 4 * 3600           # the whole install: download, unpack, copy
MAX_ENTRIES = 100000                    # files and folders in one archive
MAX_UNPACKED = 20 * 10 ** 9             # bytes unpacked from one download, nested archives included
MAX_RATIO = 100                         # unpacked / downloaded; a "zip bomb" is far above this
MIN_UNPACK_ALLOWED = 32 * 10 ** 6       # a tiny archive may still unpack to this much
SPACE_FACTOR = 3                        # download + unpacked copy + installed copy
SPACE_MARGIN = 512 * 10 ** 6


class StoreError(Exception):
    pass


class NotVerified(StoreError):
    """The download has no sha256 to be checked against: it is installed only after a second, explicit confirmation."""
    def __init__(self, name, url="", pkg=False):
        self.name, self.url, self.pkg = name, url, pkg
        host = urllib.parse.urlparse(url).hostname or "its publisher"
        super().__init__(
            f"{name} is NOT VERIFIED: its publisher gives no sha256 fingerprint for this download, so hypnomix cannot "
            f"check that the file is the one the publisher released. It would be fetched over HTTPS from {host}."
            + (" It is an installer package: once you click through Apple's Installer it runs with administrator rights."
               if pkg else "")
            + " Install it only if you trust that address.")


class NeedsConfirm(StoreError):
    """Something the store did not install is already where an item would go."""
    def __init__(self, paths):
        self.paths = [str(p) for p in paths]
        super().__init__("already there, and not installed by the store: " + ", ".join(self.paths)
                         + ". Confirm to replace (the old copy is moved to the store's trash folder, not deleted).")


# ---------------------------------------------------------------- where things go
PLATFORM_NOTE = ("The Store works on macOS only for now: it installs plug-ins into the Mac's Library folder and sounds "
                 "into Music. On this computer it is not available yet, so nothing was installed. Free plug-ins can still "
                 "be downloaded from their publishers' own pages (see the catalogue's homepage links).")


def supported():
    """The store installs on macOS (or anywhere when HYPNOMIX_STORE_ROOT points it at a test folder)."""
    return sys.platform == "darwin" or root() is not None


def check_platform():
    if not supported():
        raise StoreError(PLATFORM_NOTE)


def root():
    r = os.environ.get("HYPNOMIX_STORE_ROOT")
    return Path(r).expanduser() if r else None


def home():
    return root() or Path.home()


def plugins_dir():
    return home() / "Library" / "Audio" / "Plug-Ins"


def library_dir():
    return home() / "Music" / "Hypnomix Library"


def state_dir():
    if root():
        return root() / ".hypnomix" / "store"
    return Path(os.environ.get("HYPNOMIX_HOME") or "~/.hypnomix").expanduser() / "store"   # follows HYPNOMIX_HOME


def manifest_path():
    return state_dir() / "manifest.json"


def target_for_bundle(bundle):
    return plugins_dir() / PLUGIN_DIRS[bundle.suffix.lower()] / bundle.name


def target_for_content(item):
    name = item["name"]
    if not C.safe_part(name):                              # never a path of its own ("..", "a/b"): the catalogue is checked
        raise StoreError(f"{name!r} is not usable as a folder name")  # when loaded, and this guards the use itself
    return library_dir() / KIND_DIRS[item["kind"]] / name


def _real(p):
    return os.path.realpath(str(p))


def _inside_targets(p):
    """True only for a path the store itself would have installed: one item exactly inside a plug-in format folder
    (VST3, Components, ...), a content kind folder (Drum Kits, ...), or a kept installer's own folder. Compared by REAL
    path, so a link in a parent folder cannot lead elsewhere, and the format or kind folder itself (or anything above
    it) is never accepted: removing it would take every other plug-in with it."""
    p = Path(os.path.abspath(str(p)))                      # no ".." left, so the name below is the real last part
    if p.name in ("", ".", ".."):
        return False
    parent = _real(p.parent)
    ok = {_real(plugins_dir() / d) for d in PLUGIN_DIRS.values()} | {_real(library_dir() / d) for d in KIND_DIRS.values()}
    if parent in ok:
        return True
    inst = _real(state_dir() / "installers")               # installers/<id>/<package>
    return os.path.dirname(parent) == inst and os.path.basename(parent) not in ("", ".", "..")


# ---------------------------------------------------------------- manifest
def manifest():
    from hypnomix.core import atomic
    m = atomic.load_json(manifest_path(), None, warn=False)          # a cut-off manifest falls back to its backup
    return m if isinstance(m, dict) and isinstance(m.get("items"), dict) else {"items": {}}


def _save_manifest(m):
    from hypnomix.core import atomic
    atomic.write_json(manifest_path(), m, indent=2)                  # whole or not at all, the last good one kept


def owner_of(path, m=None):
    path = str(path)
    for iid, e in (m or manifest())["items"].items():
        if path in e.get("paths", []):
            return iid
    return None


# ---------------------------------------------------------------- network
def _origin(url):
    u = urllib.parse.urlparse(url)
    return (u.scheme, (u.hostname or "").lower(), u.port or 443)


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme != "https":
            raise StoreError(f"refused a redirect to a non-HTTPS address: {newurl}")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and _origin(newurl) != _origin(req.full_url):
            for h in ("Authorization", "Cookie", "Proxy-Authorization"):      # a token belongs to the origin it was sent to
                new.headers.pop(h, None)
                new.headers.pop(h.capitalize(), None)
                new.unredirected_hdrs.pop(h, None)
                new.unredirected_hdrs.pop(h.capitalize(), None)
        return new


_opener = urllib.request.build_opener(_HttpsOnly())


def _open(url, headers=None, timeout=30):
    if urllib.parse.urlparse(url).scheme != "https":
        raise StoreError(f"only HTTPS downloads are allowed: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    return _opener.open(req, timeout=timeout)


def _github(path):
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    tok = os.environ.get("HYPNOMIX_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = "Bearer " + tok
    try:
        with _open("https://api.github.com" + path, h) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 403 and e.headers.get("X-RateLimit-Remaining") == "0":
            raise StoreError("GitHub's limit of 60 look-ups an hour is used up; try again later "
                             "(or set GITHUB_TOKEN for a higher limit)")
        raise StoreError(f"GitHub said {e.code} for {path}")
    except urllib.error.URLError as e:
        raise StoreError(f"could not reach GitHub: {e.reason}")


_resolved = {}


def resolve(item, fresh=False):
    """Where the newest download is -> dict(version, url, filename, size, sha256, published) or dict(page=url)."""
    s = item["source"]
    if s["type"] == "page":
        return {"page": item["homepage"], "version": "", "note": s.get("note", "")}
    hint = C.size_bytes(item)
    if s["type"] == "url":
        fn = C.url_filename(s["url"])
        if not C.safe_part(fn):
            raise StoreError(f"{item['name']}: the download's file name {fn!r} is not a plain file name; refused")
        return {"version": s["version"], "url": s["url"], "filename": fn, "size": None, "size_hint": hint,
                "sha256": s.get("sha256"), "published": ""}
    key = (item["id"], s["repo"], s.get("tag"), s["asset"])
    hit = _resolved.get(key)
    if hit and not fresh and time.time() - hit[0] < 600:
        return hit[1]
    rel = _github(f"/repos/{s['repo']}/releases/" + (f"tags/{urllib.parse.quote(s['tag'])}" if s.get("tag") else "latest"))
    pat = re.compile(s["asset"])
    assets = [a for a in rel.get("assets", []) if pat.search(a["name"])]
    if not assets:
        raise StoreError(f"{item['name']}: no download in {s['repo']} release {rel.get('tag_name')} matches "
                         f"{s['asset']} (the publisher may have renamed it; the catalogue needs updating)")
    a = assets[0]
    if not C.safe_part(a["name"]):
        raise StoreError(f"{item['name']}: the release file's name {a['name']!r} is not a plain file name; refused")
    dig = a.get("digest") or ""
    published = dig.split(":", 1)[1].lower() if dig.startswith("sha256:") else None
    pinned = s.get("sha256")
    if pinned and published and published != pinned.lower():
        raise StoreError(f"{item['name']}: GitHub's fingerprint for {a['name']} is not the one pinned in the catalogue "
                         "(the release was changed); nothing was downloaded")
    out = {"version": a["name"] if s.get("tag") else rel.get("tag_name", ""), "url": a["browser_download_url"],
           "filename": a["name"], "size": a.get("size"), "size_hint": hint,
           "published": a.get("updated_at") or rel.get("published_at", ""),
           "sha256": pinned or published, "release": rel.get("html_url")}
    _resolved[key] = (time.time(), out)
    return out


def _gb(n):
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def download_cap(size=None, hint=0):
    """The most bytes a download may be: the publisher's exact size plus 10%, else the catalogue's rough size with a
    margin, else DEFAULT_MAX_DOWNLOAD."""
    if size:
        return int(size * 1.1) + 16 * 10 ** 6
    if hint:
        return int(hint * DOWNLOAD_MARGIN) + DOWNLOAD_SLACK
    return DEFAULT_MAX_DOWNLOAD


def free_bytes(path):
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(str(p)).free


def check_space(need, *where):
    """Refuse, before downloading or copying, when the disk that holds any of these folders has less than need free."""
    for w in where:
        free = free_bytes(w)
        if free < need:
            raise StoreError(f"this needs about {_gb(need)} free on the disk that holds {w}, and only {_gb(free)} is "
                             "free. Free some space (or remove something you do not need) and try again.")


def _stop_check(deadline, cancel):
    if cancel and cancel():
        raise StoreError("cancelled: nothing was installed")
    if deadline and time.monotonic() > deadline:
        raise StoreError("this took longer than the store allows (the whole install must finish within "
                         f"{INSTALL_DEADLINE_S // 3600} hours): stopped, nothing was installed")


def download(url, dest, sha256=None, size=None, progress=None, max_bytes=None, deadline=None, cancel=None):
    """Stream url into dest over HTTPS. Checks the sha256 when given -> the sha256 of what was downloaded.
    max_bytes: refuse a download bigger than this (default DEFAULT_MAX_DOWNLOAD); deadline: a time.monotonic() value
    after which it stops; cancel: a function that returns True to stop."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    cap = max_bytes or DEFAULT_MAX_DOWNLOAD
    deadline = deadline or time.monotonic() + INSTALL_DEADLINE_S
    h = hashlib.sha256()
    got = 0
    try:
        with _open(url, timeout=60) as r, open(part, "wb") as f:
            if urllib.parse.urlparse(r.geturl()).scheme != "https":
                raise StoreError("the download ended on a non-HTTPS address")
            try:
                clen = int(r.headers.get("Content-Length") or 0)
            except ValueError:
                clen = 0
            if clen > cap:
                raise StoreError(f"the download says it is {_gb(clen)}, more than the {_gb(cap)} this item is allowed: refused")
            total = clen or size or 0
            while True:
                _stop_check(deadline, cancel)
                chunk = (getattr(r, "read1", None) or r.read)(1 << 18)     # read1: returns what has arrived, so a slow drip
                if not chunk:                                              # cannot hold the deadline and Cancel back
                    break
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if got > cap:
                    raise StoreError(f"the download went past the {_gb(cap)} this item is allowed: stopped and deleted it")
                if progress:
                    progress("download", got, total)
        if total and got != total:
            raise StoreError(f"the download stopped early ({got} of {total} bytes)")
        digest = h.hexdigest()
        if sha256 and digest != sha256.lower():
            raise StoreError(f"the download's sha256 is {digest}, but the publisher says {sha256}: deleted it, "
                             "nothing was installed")
        os.replace(part, dest)
        return digest
    except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
        raise StoreError(f"download failed: {getattr(e, 'reason', e)}")
    finally:
        if part.exists():
            part.unlink()


# ---------------------------------------------------------------- unpacking (nothing is ever run)
def _safe_name(name):
    p = Path(name)
    return not (name.startswith("/") or name.startswith("\\") or ".." in p.parts or re.match(r"^[A-Za-z]:", name))


def _safe_link(name, target):
    if target.startswith("/"):
        return False
    joined = os.path.normpath(os.path.join(os.path.dirname(name), target))
    return not (joined.startswith("..") or os.path.isabs(joined))


def archive_kind(name):
    n = name.lower()
    for ext in sorted(ARCHIVE_EXT, key=len, reverse=True):
        if n.endswith(ext):
            return ext
    return None


class Budget:
    """What one download may unpack to, counted over the archive and any archives found inside it: the number of
    entries, the total bytes, and the ratio of bytes to the size of what was downloaded. Also carries the deadline
    and the cancel check, so a long unpack can be stopped."""
    def __init__(self, archive_bytes, deadline=None, cancel=None, max_bytes=None, max_entries=None):
        self.max_bytes = max_bytes or min(MAX_UNPACKED, max(MIN_UNPACK_ALLOWED, MAX_RATIO * int(archive_bytes or 0)))
        self.max_entries = max_entries or MAX_ENTRIES
        self.bytes = self.entries = 0
        self.deadline, self.cancel = deadline, cancel

    def add(self, nbytes=0, entries=0):
        self.bytes += nbytes
        self.entries += entries
        if self.entries > self.max_entries:
            raise StoreError(f"refused: the download holds more than {self.max_entries} files and folders")
        if self.bytes > self.max_bytes:
            raise StoreError(f"refused: the download would unpack to more than {_gb(self.max_bytes)} "
                             "(far larger than what was downloaded, or past the store's limit)")

    def left(self):
        return max(self.max_bytes - self.bytes, 0)

    def check(self):
        _stop_check(self.deadline, self.cancel)


def _tree_size(p):
    """Bytes and entry count under p (links counted, never followed)."""
    n = c = 0
    for dirpath, dirs, files in os.walk(p):
        c += len(dirs) + len(files)
        for f in files:
            try:
                n += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return n, c


def _has_data_filter():
    """tarfile's safe extraction filter (Python 3.12, and the security releases of 3.8 to 3.11)."""
    return hasattr(tarfile, "data_filter")


def unpack(src, dest, budget=None):
    """Unpack an archive or disk image into dest, refusing anything that would land outside it or that unpacks to
    far more than was downloaded (see Budget)."""
    src, dest = Path(src), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    budget = budget or Budget(src.stat().st_size)
    try:
        _unpack(src, dest, budget)
    except (tarfile.TarError, zipfile.BadZipFile, EOFError, zlib.error, OSError) as e:
        raise StoreError(f"could not unpack {src.name}: {e}")
    _check_links(dest)
    return dest


def _unpack(src, dest, budget):
    kind = archive_kind(src.name)
    if kind == ".zip":
        with zipfile.ZipFile(src) as z:
            infos = z.infolist()
            budget.add(sum(i.file_size for i in infos), len(infos))
            for i in infos:
                if not _safe_name(i.filename):
                    raise StoreError(f"refused: the archive has an unsafe path {i.filename!r}")
                if stat.S_ISLNK(i.external_attr >> 16) and not _safe_link(i.filename, z.read(i).decode("utf-8", "replace")):
                    raise StoreError(f"refused: the archive has a link pointing outside it ({i.filename})")
            if sys.platform == "darwin" and shutil.which("ditto"):
                _run_limited(["ditto", "-x", "-k", str(src), str(dest)], "unzipping", dest, budget)   # keeps links and permissions
            else:
                for i in infos:
                    out = z.extract(i, dest)
                    mode = (i.external_attr >> 16) & 0o777
                    if mode and not i.is_dir():
                        os.chmod(out, mode)
    elif kind in (".tar", ".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.bz2", ".tbz2"):
        with tarfile.open(src) as t:
            members = t.getmembers()
            budget.add(sum(m.size for m in members if m.isfile()), len(members))
            for m in members:                              # every member is checked before anything is extracted
                if not _safe_name(m.name) or m.isdev() or m.isfifo():
                    raise StoreError(f"refused: the archive has an unsafe entry {m.name!r}")
                if m.issym() and not _safe_link(m.name, m.linkname) or m.islnk() and not _safe_name(m.linkname):
                    raise StoreError(f"refused: the archive has a link pointing outside it ({m.name})")
            if _has_data_filter():
                t.extractall(dest, filter="data")
            else:
                # no safe-extraction filter in this Python: a chain of links (a/l -> .., m -> a/l/..) passes the
                # per-entry checks and would write outside dest while extracting, so refuse any link, and extract
                # member by member with every target resolved first and the setuid/setgid bits dropped
                if any(m.issym() or m.islnk() for m in members):
                    raise StoreError("this archive contains links, and this Python cannot unpack those safely: "
                                     "update Python (3.12 or a recent 3.11) or use the app's built-in Python")
                real = os.path.realpath(dest)
                for m in members:
                    tgt = os.path.realpath(os.path.join(dest, m.name))
                    if tgt != real and not tgt.startswith(real + os.sep):
                        raise StoreError(f"refused: the archive has an unsafe entry {m.name!r}")
                for m in members:
                    budget.check()
                    m.mode &= 0o777
                    t.extract(m, dest)
    elif kind == ".7z":
        tar = shutil.which("bsdtar") or ("/usr/bin/tar" if sys.platform == "darwin" else None)
        if not tar:
            raise StoreError("unpacking .7z needs bsdtar (built into macOS)")
        names = _run([tar, "-tf", str(src)], "listing the archive").splitlines()
        budget.add(0, len(names))
        bad = [n for n in names if not _safe_name(n)]
        if bad:
            raise StoreError(f"refused: the archive has unsafe paths {bad[:3]}")
        _run_limited([tar, "-xf", str(src), "-C", str(dest)], "unpacking", dest, budget)
        for p in dest.rglob("*"):
            if p.is_symlink() and not _safe_link(str(p.relative_to(dest)), os.readlink(p)):
                raise StoreError(f"refused: the archive has a link pointing outside it ({p.name})")
    elif kind == ".dmg":
        _dmg_copy(src, dest, budget)
    else:
        raise StoreError(f"don't know how to unpack {src.name}")


def _check_links(dest):
    """Every link that was unpacked must resolve inside dest. The per-entry checks above are lexical, so a chain of
    links (a/l1 -> .., l2 -> a/l1/..) can still climb out, and a disk image's contents are not checked at all:
    resolve each link for real and refuse the whole download if one points outside."""
    real = os.path.realpath(dest)
    for dirpath, dirs, files in os.walk(dest):                  # links are listed, never followed
        for n in dirs + files:
            p = os.path.join(dirpath, n)
            if os.path.islink(p):
                rp = os.path.realpath(p)
                if rp != real and not rp.startswith(real + os.sep):
                    raise StoreError(f"refused: the download has a link pointing outside it "
                                     f"({os.path.relpath(p, dest)} -> {os.readlink(p)})")


def _run(cmd, what, timeout=900, stdin=subprocess.DEVNULL):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, stdin=stdin)
    if r.returncode:
        raise StoreError(f"{what} failed: {(r.stderr or r.stdout).strip()[-400:]}")
    return r.stdout


def _run_limited(cmd, what, watch, budget, timeout=900):
    """Run an unpacking command, and kill it when what it writes under `watch` passes the budget, when the deadline
    passes, or when the person cancels (a hostile archive can claim small sizes and still expand without end). The
    writing is looked at about once a second, so a fast unpack can land before the first look: the check after it is the
    backstop (and the free-space check before the download bounds the damage)."""
    start = last_look = time.monotonic()
    with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        try:
            while p.poll() is None:
                time.sleep(0.2)
                budget.check()
                if time.monotonic() - start > timeout:
                    raise StoreError(f"{what} took too long and was stopped")
                if time.monotonic() - last_look >= 1.0:           # look at what has been written about once a second
                    last_look = time.monotonic()
                    n, c = _tree_size(watch)
                    if n > budget.max_bytes or c > budget.max_entries:
                        raise StoreError("refused: the archive is unpacking to far more than the store allows "
                                         f"(over {_gb(budget.max_bytes)} or {budget.max_entries} files); stopped")
        except BaseException:
            p.kill()
            p.wait()
            raise
        if p.returncode:
            out.seek(0)
            raise StoreError(f"{what} failed: {out.read().strip()[-400:]}")
    n, c = _tree_size(watch)                                  # a fast unpack ends before the first look
    if n > budget.max_bytes or c > budget.max_entries:
        raise StoreError("refused: the archive unpacked to far more than the store allows "
                         f"(over {_gb(budget.max_bytes)} or {budget.max_entries} files)")


def _dmg_copy(src, dest, budget=None):
    if sys.platform != "darwin":
        raise StoreError("disk images (.dmg) can only be opened on a Mac")
    mnt = Path(tempfile.mkdtemp(prefix="hypnomix-store-mnt-"))
    try:
        # read-only, no Finder window, nothing opened; stdin closed so a licence agreement is never accepted for you
        r = subprocess.run(["hdiutil", "attach", "-readonly", "-nobrowse", "-noautoopen", "-mountpoint", str(mnt), str(src)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, stdin=subprocess.DEVNULL)
        if r.returncode:
            msg = (r.stderr or r.stdout).strip()
            if "agreement" in msg.lower() or "license" in msg.lower():
                raise StoreError("this disk image shows a licence agreement first: open it yourself to read and accept it")
            raise StoreError(f"could not open the disk image: {msg[-300:]}")
        try:
            if budget:                                         # the image's contents are counted before any copy
                n, c = _tree_size(mnt)
                budget.add(n, c)
            for p in mnt.iterdir():
                if p.name in JUNK or p.is_symlink():          # the "Applications" shortcut and Finder's files
                    continue
                if p.is_dir():
                    _copy_tree(p, dest / p.name)
                else:
                    shutil.copy2(p, dest / p.name)
        finally:
            d = subprocess.run(["hdiutil", "detach", str(mnt)], capture_output=True, timeout=120)
            if d.returncode:
                subprocess.run(["hdiutil", "detach", "-force", str(mnt)], capture_output=True, timeout=120)
    finally:
        try:
            mnt.rmdir()
        except OSError:
            pass


def _copy_tree(a, b):
    """Copy a bundle or folder, keeping its links as links (never following them)."""
    if sys.platform == "darwin" and shutil.which("ditto"):
        _run(["ditto", str(a), str(b)], "copying")
    else:
        shutil.copytree(a, b, symlinks=True)


def find(top):
    """-> dict(bundles, pkgs, archives, apps) found under top. Links are never followed; bundles not entered."""
    found = {"bundles": [], "pkgs": [], "archives": [], "apps": []}
    for dirpath, dirs, files in os.walk(top):
        keep = []
        for d in sorted(dirs):
            p = Path(dirpath) / d
            ext = p.suffix.lower()
            if d in JUNK or p.is_symlink():
                continue
            if ext in PLUGIN_DIRS:
                found["bundles"].append(p)
            elif ext in (".pkg", ".mpkg"):
                found["pkgs"].append(p)
            elif ext == ".app":
                found["apps"].append(p)
            else:
                keep.append(d)
        dirs[:] = keep
        for f in sorted(files):
            p = Path(dirpath) / f
            if f in JUNK or p.is_symlink():
                continue
            if p.suffix.lower() in (".pkg", ".mpkg"):
                found["pkgs"].append(p)
            elif archive_kind(f):
                found["archives"].append(p)
    return found


def archs(bundle):
    """The CPU architectures of a bundle's binary (read with lipo, never run) -> e.g. ['x86_64', 'arm64'] or []."""
    if sys.platform != "darwin" or not shutil.which("lipo"):
        return []
    cands = sorted((bundle / "Contents" / "MacOS").glob("*")) if (bundle / "Contents" / "MacOS").is_dir() else []
    cands += sorted(bundle.glob("*.dylib")) + sorted(bundle.glob("*.so"))
    for c in cands:
        if c.is_file() and not c.is_symlink():
            r = subprocess.run(["lipo", "-archs", str(c)], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode == 0:
                return r.stdout.split()
    return []


# ---------------------------------------------------------------- install / uninstall
def _work(item_id):
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", str(item_id)):            # an id is a path part here
        raise StoreError(f"{item_id!r} is not a valid item id")
    w = state_dir() / "work" / f"{item_id}-{int(time.time() * 1000)}"
    w.mkdir(parents=True, exist_ok=True)
    return w


def _say(progress, phase, a=0, b=0):
    if progress:
        progress(phase, a, b)


def install(item, confirm_overwrite=False, progress=None, archive=None, info=None, open_pkg=None,
            confirm_unverified=False, cancel=None):
    """Install (or update) one catalogue item -> the manifest entry.

    archive/info: an already-downloaded file and its resolve() info (tests; the download is skipped).
    Raises NeedsConfirm when something the store did not install is in the way, and NotVerified when there is no
    sha256 to check the download against (until confirm_unverified is True: the person said so, knowing).
    cancel: a function that returns True to stop (checked while downloading and unpacking)."""
    if item["method"] == "page" or item["source"]["type"] == "page":
        raise StoreError(f"{item['name']} can't be downloaded by the store: open {item['homepage']} and get it there")
    check_platform()
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", str(item["id"])):
        raise StoreError(f"{item['id']!r} is not a valid item id")
    with _lock:
        info = info or resolve(item, fresh=True)
        if not info.get("sha256") and not confirm_unverified:
            raise NotVerified(item["name"], info.get("url", ""), item["method"] == "pkg")
        deadline = time.monotonic() + INSTALL_DEADLINE_S
        est = info.get("size") or info.get("size_hint") or C.size_bytes(item)
        if archive is None:
            check_space(SPACE_FACTOR * est + SPACE_MARGIN, state_dir())
        work = _work(item["id"])
        try:
            if archive is None:
                fname = info["filename"]
                if not C.safe_part(fname):
                    raise StoreError(f"the download's file name {fname!r} is not a plain file name; refused")
                _say(progress, "download", 0, info.get("size") or 0)
                archive = work / fname
                if os.path.realpath(archive.parent) != os.path.realpath(work):
                    raise StoreError("refused: the download would be written outside the store's work folder")
                sha = download(info["url"], archive, info.get("sha256"), info.get("size"), progress,
                               max_bytes=download_cap(info.get("size"), info.get("size_hint") or C.size_bytes(item)),
                               deadline=deadline, cancel=cancel)
            else:
                archive = Path(archive)
                sha = hashlib.sha256(archive.read_bytes()).hexdigest()
                if info.get("sha256") and sha != info["sha256"].lower():
                    raise StoreError("sha256 does not match: nothing was installed")
            _stop_check(deadline, cancel)
            _say(progress, "unpack")
            budget = Budget(archive.stat().st_size, deadline, cancel)
            if item["method"] == "content":
                entry = _install_content(item, archive, work, confirm_overwrite, budget)
            else:
                entry = _install_plugins(item, archive, work, confirm_overwrite, open_pkg, progress, budget)
            entry.update(id=item["id"], name=item["name"], kind=item["kind"], version=info.get("version", ""),
                         url=info.get("url", ""), sha256=sha, sha256_checked=bool(info.get("sha256")),
                         licence=item["licence"], installed=time.strftime("%Y-%m-%d %H:%M"))
            m = manifest()
            taken = set(entry.get("paths", []))
            for oid, oe in m["items"].items():          # a confirmed replace took these from another item: it no
                if oid != item["id"] and taken & set(oe.get("paths", [])):   # longer owns them (else its uninstall
                    oe["paths"] = [p for p in oe["paths"] if p not in taken]  # would delete this item's copy)
            m["items"][item["id"]] = entry
            _save_manifest(m)
            _say(progress, "done")
            return entry
        finally:
            shutil.rmtree(work, ignore_errors=True)


def _unpack_all(archive, work, want, budget=None):
    """Unpack, then unpack archives found inside (two levels deep) until want(found) is satisfied. One budget
    covers the whole download, nested archives included."""
    budget = budget or Budget(Path(archive).stat().st_size)
    top = unpack(archive, work / "unpacked", budget)
    dirs, done = [top], set()

    def scan():
        f = {"bundles": [], "pkgs": [], "archives": [], "apps": []}
        for d in dirs:
            for k, v in find(d).items():
                f[k] += v
        f["archives"] = [a for a in f["archives"] if a not in done]
        return f

    found = scan()
    for _ in range(2):
        if want(found) or not found["archives"]:
            break
        for a in found["archives"]:
            d = work / f"nested{len(dirs)}"
            unpack(a, d, budget)
            dirs.append(d)
            done.add(a)
        found = scan()
    return top, found


def _conflicts(item_id, targets, m):
    return [t for t in targets if (t.exists() or t.is_symlink()) and owner_of(t, m) != item_id]


def _place(pairs, item_id, confirm_overwrite):
    """Copy each (source, target) into place. The item's own old copies are replaced; anything else in the way
    needs confirm_overwrite and is moved to the store's trash folder. All or nothing."""
    m = manifest()
    clash = _conflicts(item_id, [t for _, t in pairs], m)
    if clash and not confirm_overwrite:
        raise NeedsConfirm(clash)
    need = sum(_tree_size(src)[0] if src.is_dir() else src.stat().st_size for src, _ in pairs)
    check_space(need + SPACE_MARGIN // 2, *{t.parent for _, t in pairs})
    trash = state_dir() / "trash" / time.strftime("%Y%m%d-%H%M%S")
    done, moved = [], []
    try:
        for src, tgt in pairs:
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tmp = tgt.with_name(".hypnomix-new-" + tgt.name)
            if tmp.exists():
                shutil.rmtree(tmp) if tmp.is_dir() else tmp.unlink()
            _copy_tree(src, tmp) if src.is_dir() else shutil.copy2(src, tmp)
            if tgt.exists() or tgt.is_symlink():
                trash.mkdir(parents=True, exist_ok=True)
                old = trash / f"{len(moved)}-{tgt.name}"
                shutil.move(str(tgt), str(old))
                moved.append((old, tgt))
            os.replace(tmp, tgt)
            done.append(tgt)
    except Exception:
        for t in done:
            shutil.rmtree(t, ignore_errors=True) if t.is_dir() else t.unlink()
        for old, tgt in moved:
            shutil.move(str(old), str(tgt))
        raise
    # the item's own old copies are not kept; anything else that was in the way stays in the trash folder
    for old, tgt in moved:
        if owner_of(tgt, m) == item_id:
            shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink()
    kept = [str(old) for old, tgt in moved if old.exists()]
    old_paths = set(m["items"].get(item_id, {}).get("paths", []))
    for p in old_paths - {str(t) for t in done}:                 # an update dropped a bundle: remove the old one
        _remove(Path(p))
    return [str(t) for t in done], kept


def _install_plugins(item, archive, work, confirm_overwrite, open_pkg, progress, budget=None):
    top, found = _unpack_all(archive, work, lambda f: bool(f["bundles"]), budget)
    if found["bundles"]:
        pairs, seen = [], set()
        for b in found["bundles"]:
            t = target_for_bundle(b)
            if t not in seen:
                seen.add(t)
                pairs.append((b, t))
        _say(progress, "install", 0, len(pairs))
        paths, kept = _place(pairs, item["id"], confirm_overwrite)
        return {"method": "bundles", "paths": paths, "replaced_kept_in": kept,
                "formats": sorted({FORMAT_OF[Path(p).suffix.lower()] for p in paths}),
                "archs": {Path(p).name: archs(Path(p)) for p in paths}}
    if found["pkgs"]:
        pkg = found["pkgs"][0]
        keep = state_dir() / "installers" / item["id"] / pkg.name
        if keep.exists():
            shutil.rmtree(keep) if keep.is_dir() else keep.unlink()
        keep.parent.mkdir(parents=True, exist_ok=True)
        _copy_tree(pkg, keep) if pkg.is_dir() else shutil.copy2(pkg, keep)
        quarantined = _quarantine(keep)
        opened = _open_pkg(keep) if open_pkg is None else open_pkg(keep)
        return {"method": "pkg", "paths": [], "installer": str(keep), "opened": bool(opened), "quarantined": quarantined,
                "note": "The publisher ships this as an installer package, so hypnomix does not install it: "
                        + ("it is open in Apple's Installer for you to read and run." if opened else
                           "open the installer yourself (Show installer) to read and run it.")
                        + " An installer package puts files outside your home folder and asks for your password: read it first."
                        + " Remove it later with the publisher's instructions."}
    raise StoreError("found no plug-in (.vst3, .component, .clap, .lv2) or installer in the download"
                     + (f"; it has an app ({found['apps'][0].name}) instead" if found["apps"] else ""))


def _quarantine(p):
    """Mark a kept installer as downloaded from the internet (the flag Safari and Chrome set), so that macOS checks it
    (Gatekeeper) when it is opened. Only ever adds the flag. -> True when it was set."""
    if sys.platform != "darwin" or not shutil.which("xattr"):
        return False
    flag = "0081;%x;hypnomix;" % int(time.time())
    return subprocess.run(["xattr", "-r", "-w", "com.apple.quarantine", flag, str(p)], capture_output=True,
                          stdin=subprocess.DEVNULL).returncode == 0


def _open_pkg(pkg):
    """Show the installer package to the person in Apple's Installer (they read and run it). Never `installer`."""
    if os.environ.get("HYPNOMIX_STORE_NO_OPEN") or sys.platform != "darwin":
        return False
    return subprocess.run(["open", "-b", "com.apple.installer", str(pkg)], capture_output=True).returncode == 0


def _install_content(item, archive, work, confirm_overwrite, budget=None):
    top, found = _unpack_all(archive, work, lambda f: True, budget)
    kids = [p for p in top.iterdir() if p.name not in JUNK]
    src = kids[0] if len(kids) == 1 and kids[0].is_dir() else top
    tgt = target_for_content(item)
    paths, kept = _place([(src, tgt)], item["id"], confirm_overwrite)
    sfz = sorted(str(p.relative_to(tgt)) for p in tgt.rglob("*.sfz"))
    return {"method": "content", "paths": paths, "replaced_kept_in": kept, "sfz": sfz[:200], "sfz_count": len(sfz)}


def _remove(p):
    p = Path(os.path.abspath(str(p)))
    if not _inside_targets(p):
        raise StoreError(f"refused to remove {p}: it is not something the store installs, or it is outside the store's folders")
    if p.is_symlink() or p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)


def uninstall(item_id):
    """Remove exactly what the manifest says this item installed -> the paths removed."""
    with _lock:
        m = manifest()
        e = m["items"].get(item_id)
        if not e:
            raise StoreError(f"{item_id} was not installed by the store")
        todo = [Path(p) for p in e.get("paths", [])] + ([Path(e["installer"])] if e.get("installer") else [])
        for p in todo:                                       # every path is checked before the first one is removed
            if (p.exists() or p.is_symlink()) and not _inside_targets(p):
                raise StoreError(f"refused to remove {p}: it is not something the store installs, or it is outside the "
                                 "store's folders. Nothing was removed.")
        gone = []
        for p in todo:
            if p.exists() or p.is_symlink():
                _remove(p)
                if str(p) in e.get("paths", []):
                    gone.append(str(p))
        del m["items"][item_id]
        _save_manifest(m)
        return gone


def status(items=None):
    """Installed state for every catalogue item (no network)."""
    m = manifest()
    out = {}
    for it in items or C.items():
        e = m["items"].get(it["id"])
        if not e:
            out[it["id"]] = {"installed": False}
            continue
        missing = [p for p in e.get("paths", []) if not Path(p).exists()]
        out[it["id"]] = {"installed": True, "version": e.get("version"), "method": e.get("method"), "paths": e.get("paths", []),
                         "missing": missing, "installer": e.get("installer"),
                         "installer_missing": bool(e.get("installer")) and not Path(e["installer"]).exists(),
                         "verified": bool(e.get("sha256_checked")), "archs": e.get("archs", {}),
                         "when": e.get("installed"), "note": e.get("note", ""), "sfz_count": e.get("sfz_count")}
    return out


def check_update(item):
    """-> dict(installed, latest, update) for an installed item (asks GitHub; url items compare the catalogue)."""
    e = manifest()["items"].get(item["id"])
    info = resolve(item)
    latest = info.get("version", "")
    return {"installed": e and e.get("version"), "latest": latest, "update": bool(e and latest and latest != e.get("version"))}
