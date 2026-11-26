"""Disk care: the app clears out the bulky files hypnomix leaves behind, so the disk doesn't fill up.

While the app is open it looks once an hour. It cleans when a week has passed since the last clean, or straight
away when the disk is nearly full (under 8% free, counted as at most 50 GB and at least 20 GB, so a big disk is not
"nearly full" with 70 GB left); then it uses shorter ages too. Nothing to set up: it's on by default and can be
switched off, previewed and run by hand from the "free" button in the app's header.

It tells you (a macOS notification) only when it freed more than 1 GB, when the disk got fuller than at its last
notice (ok -> low -> critical), or once a day while it stays low: never every hour. HYPNOMIX_DISKCARE=off in the
environment keeps the hourly look from starting at all (test and preview copies of the app use it).

What it removes, and only that:
  cache     ~/.hypnomix/cache/render and renders: rendered audio kept to speed up a re-run, idle 7 days;
            cache/teach (the Teacher tab's audio examples, made again on demand), idle 14 days
            (1 when the disk is nearly full; the pitch cache only then, idle 14 days)
  scans     audio inside hypnomix scan folders (the app's own, and any folder in "watch") once the whole scan
            has been idle 14 days: A/B clips and renders. Findings, decisions and reports stay, so the review
            still opens; "Make A/B clips" builds the clips again
  out       audio in hypnomix-out folders (the app's own and in watched folders), idle 14 days
  bounces   the app's master bounces older than 30 days; the newest 5 always stay
  wavs      only if you switch it on: WAV / AIFF files at the top of Desktop and Downloads, older than 30 days.
            They are moved to ~/.hypnomix/holding, not deleted, and deleted from there 14 days later
            ("Restore" puts the last batch back)

A folder in "watch" must exist inside your home folder, and not be the home folder itself, the top of the disk,
Library, or all of Music, Desktop or Documents (a folder inside those is fine): the settings refuse it and say why.
A folder saved earlier that no longer qualifies (a project folder on an external drive, say) is not cleaned any more,
but it is still READ, so the audio its projects use stays protected. The settings list it as "not cleaned" and why.

Never removed: an audio file any Live, REAPER or Ardour project on this computer uses (projects under Music,
Documents, Desktop and the watched folders are read for this), a file named "final" or "master", anything
changed in the last hour, and anything while a job is running.

  python -m hypnomix.app.diskcare            what it would remove now (changes nothing)
  python -m hypnomix.app.diskcare --run      clean now
"""
import json, os, re, shutil, subprocess, sys, threading, time
from datetime import datetime
from pathlib import Path

from hypnomix.core.paths import write_private

DAY = 86400
GB = 1e9
LOCK = threading.Lock()
AUDIO = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a", ".ogg", ".npy", ".mov", ".mp4"}
LOOSE = {".wav", ".aif", ".aiff"}
PROTECT = re.compile(r"final|master", re.I)
ACTIVE_S = 3600
SKIP_DIRS = {".git", "node_modules", "Library", "Backup", "__pycache__", ".venv", "AppData"}
RUNNING = {"busy": False}


# ---------------------------------------------------------------- where things are (read at call time, for tests)
def user_home():
    return Path(os.environ.get("HYPNOMIX_USER_HOME", "~")).expanduser()


def hx_home():
    return Path(os.environ.get("HYPNOMIX_HOME", "~/.hypnomix")).expanduser()


def app_home():
    return Path(os.environ.get("HYPNOMIX_APP_HOME", "~/Documents/Hypnomix")).expanduser()


def state_file():
    return hx_home() / "diskcare.json"


def holding():
    return hx_home() / "holding"


def load():
    try:
        return json.loads(state_file().read_text())
    except (OSError, ValueError):
        return {}


def save(s):
    write_private(state_file(), json.dumps(s, indent=1))         # mode 0600, in the 0700 hypnomix folder


def _same(a, b):
    try:
        return os.path.samefile(a, b)                            # by identity, so case and symlinks can't dodge it
    except OSError:
        return False


def check_watch(x):
    """A folder the person asks Disk care to look in. It deletes old audio by rule inside these, so it must be an
    existing folder inside your home folder, and not one that holds everything. Returns the real path; raises
    ValueError saying why not, and what to do instead."""
    x = str(x).strip()
    p = Path(x).expanduser()
    if not p.is_absolute():
        raise ValueError(f"'{x}' isn't a full folder path. Give the whole path, like ~/Music/Projects.")
    if not p.is_dir():
        raise ValueError(f"'{x}' isn't a folder that exists. Check the spelling, or leave it out.")
    p, home = p.resolve(), user_home().resolve()
    if p.parent == p:
        raise ValueError("The top of the disk can't be watched: Disk care deletes old audio inside watched folders. "
                         "Pick the folder your projects are in, for example a folder inside Music.")
    if _same(p, home):
        raise ValueError("Your whole home folder can't be watched: Disk care deletes old audio inside watched folders. "
                         "Pick the folder your projects are in, for example a folder inside Music.")
    if not any(_same(a, home) for a in p.parents):
        raise ValueError(f"'{x}' is outside your home folder. Disk care only watches folders inside it; "
                         "for projects elsewhere, run the cleanup from that folder yourself.")
    lib = home / "Library"
    if any(_same(a, lib) for a in (p, *p.parents)):
        raise ValueError("The Library folder holds other apps' files and can't be watched. "
                         "Pick the folder your projects are in, for example a folder inside Music.")
    for name in ("Music", "Desktop", "Documents"):
        if _same(p, home / name):
            raise ValueError(f"All of {name} can't be watched, because Disk care deletes old audio inside watched folders. "
                             f"Pick the folder your projects are in: a folder inside {name} is fine.")
    return p


def settings(body):
    s = load()
    watch = None
    if "watch" in body:                                          # checked first: a refused folder changes nothing
        w = body["watch"]
        if not isinstance(w, (str, list, tuple)):
            raise ValueError("The watched folders must be a list of folders, one per line.")
        w = w.splitlines() if isinstance(w, str) else list(w)
        watch = [str(check_watch(x)) for x in w if str(x).strip()]
    if "auto" in body:
        s["auto"] = bool(body["auto"])
    if "wavs" in body:
        s["wavs"] = bool(body["wavs"])
    if watch is not None:
        s["watch"] = watch
    save(s)
    return view()


def _saved():
    w = load().get("watch", [])
    return [x for x in w if isinstance(x, str) and x.strip()] if isinstance(w, list) else []


def watched():
    """The watched folders that may be CLEANED: those that still pass check_watch. An old or hand-edited list can't
    widen what is deleted."""
    out = []
    for x in _saved():
        try:
            out.append(check_watch(x))
        except (ValueError, TypeError, OSError):
            pass
    return out


def refused():
    """Saved watch entries that no longer pass check_watch (saved by an older version, or edited by hand): [(folder,
    why)]. They are not cleaned, but see read_only()."""
    out = []
    for x in _saved():
        try:
            check_watch(x)
        except (ValueError, TypeError, OSError) as e:
            out.append((x, str(e)))
    return out


def read_only():
    """Folders only READ, never cleaned, for the 'used by a project' guard: every saved entry that is an existing
    folder, whether or not it may be cleaned (a project on an external drive still protects the audio it uses).
    Never the top of the disk, the home folder or Library: reading those whole would be slow and isn't what anyone
    saved a project folder for."""
    home, out = user_home().resolve(), []
    for x in _saved():
        try:
            p = Path(x).expanduser()
            if not p.is_absolute() or not p.is_dir():
                continue
            r = p.resolve()
            if r.parent == r or _same(r, home) or any(_same(a, home / "Library") for a in (r, *r.parents)):
                continue
            out.append(p)
        except (OSError, ValueError, RuntimeError):
            pass
    return out


# ---------------------------------------------------------------- disk space
def space():
    u = shutil.disk_usage(str(user_home()))
    return u.free, u.total


def level(free=None, total=None):
    if free is None:
        free, total = space()
    if free < max(8 * GB, min(0.03 * total, 20 * GB)):
        return "critical"
    if free < max(20 * GB, min(0.08 * total, 50 * GB)):
        return "low"
    return "ok"


# ---------------------------------------------------------------- helpers
def newest(p: Path):
    try:
        t = p.stat().st_mtime
    except OSError:
        return time.time()
    if p.is_dir():                                   # a folder is as old as its newest file (listing it changes its own time)
        t = 0
        for root, _, files in os.walk(p):
            for f in files:
                try:
                    t = max(t, os.lstat(os.path.join(root, f)).st_mtime)
                except OSError:
                    pass
        if not t:
            t = p.stat().st_mtime
    return t


def size(p: Path):
    if p.is_file():
        return p.stat().st_size
    n = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                n += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return n


def idle_days(p):
    return (time.time() - newest(p)) / DAY


def listdir(d: Path, blocked):
    try:
        return list(d.iterdir())
    except PermissionError:
        blocked.add(str(d))
        return []
    except OSError:
        return []


def walk(root: Path, blocked, depth=6):
    """os.walk that skips hidden and heavy folders, notes folders the OS won't let us read, and stops at depth."""
    base = len(root.parts)

    def err(e):
        if isinstance(e, PermissionError):
            blocked.add(str(e.filename))

    for dirpath, dirnames, files in os.walk(root, onerror=err):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS
                       and len(Path(dirpath).parts) - base < depth]
        yield Path(dirpath), dirnames, files


REF_PAT = {".als": re.compile(rb'<(?:Path|RelativePath|Name) Value="([^"]+)"'),
           ".rpp": re.compile(rb'FILE "([^"]+)"'),
           ".ardour": re.compile(rb'(?:origin|name)="([^"]+)"')}


def project_refs(blocked):
    """Names of every audio file a Live (.als), REAPER (.rpp) or Ardour (.ardour) project here points at.
    Each project's list is cached by its size and time, so only changed projects are read again."""
    cf = hx_home() / "cache" / "diskcare-refs.json"
    try:
        cache = json.loads(cf.read_text())
    except (OSError, ValueError):
        cache = {}
    fresh, names = {}, set()
    roots = [user_home() / n for n in ("Music", "Documents", "Desktop")] + read_only()
    for root in roots:
        if not root.is_dir():
            continue
        for d, _, files in walk(root, blocked, depth=8):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext not in REF_PAT:
                    continue
                p = str(d / f)
                if p in fresh:
                    continue
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                key = f"{st.st_size}:{st.st_mtime}"
                hit = cache.get(p)
                if hit and hit[0] == key:
                    refs = hit[1]
                else:
                    try:
                        if ext == ".als":
                            from hypnomix.core.gz import read_gz       # capped: a small crafted file can unpack to gigabytes
                            data = read_gz(p)
                        else:
                            with open(p, "rb") as fh:
                                data = fh.read()
                    except ValueError:                                 # unpacks past the cap: not read, and listed as not readable
                        blocked.add(p)
                        continue
                    except Exception:
                        continue
                    refs = sorted({os.path.basename(m.group(1).decode("utf-8", "replace").replace("\\", "/")).lower()
                                   for m in REF_PAT[ext].finditer(data)
                                   if os.path.splitext(m.group(1))[1].lower().decode() in AUDIO})
                fresh[p] = [key, refs]
                names.update(refs)
    try:
        cf.parent.mkdir(parents=True, exist_ok=True)
        cf.write_text(json.dumps(fresh))
    except OSError:
        pass
    return names


def scan_folders(blocked):
    """hypnomix scan folders: the app's own (scan/*) and any folder with findings.json or scan.log under watch."""
    out = []
    root = app_home() / "scan"
    if root.is_dir():
        out += [d for d in listdir(root, blocked) if d.is_dir()]
    for w in watched():
        for d, dirnames, files in walk(w, blocked, depth=6):
            if "findings.json" in files or "scan.log" in files:
                out.append(d)
                dirnames[:] = []
    return out


def out_folders(blocked):
    found = [app_home() / "hypnomix-out"]
    for w in watched():
        for d, dirnames, _ in walk(w, blocked, depth=5):
            if d.name == "hypnomix-out":
                found.append(d)
                dirnames[:] = []
    return [d for d in found if d.is_dir()]


# ---------------------------------------------------------------- the plan
def plan(lvl=None):
    """What would go now: (rule, action, path, bytes) and the folders the OS wouldn't let us read."""
    lvl = lvl or level()
    low = lvl != "ok"
    s = load()
    blocked = set()
    items = []
    refs = None

    def used(p):
        nonlocal refs
        if refs is None:
            refs = project_refs(blocked)
        return p.name.lower() in refs

    # cache
    cache = hx_home() / "cache"
    for name, age in (("render", 1 if low else 7), ("renders", 1 if low else 7), ("pitch", 14 if low else None),
                      ("teach", 1 if low else 14)):
        d = cache / name
        if age is None or not d.is_dir():
            continue
        for e in listdir(d, blocked):
            if idle_days(e) > age:
                items.append(("cache", "delete", e, size(e)))

    # scans: audio only, whole scan idle
    sage = 7 if low else 14
    for sd in scan_folders(blocked):
        if idle_days(sd) <= sage:
            continue
        for d, _, files in walk(sd, blocked, depth=6):
            for f in files:
                p = d / f
                if p.suffix.lower() in AUDIO and not used(p):
                    items.append(("scans", "delete", p, p.stat().st_size))

    # hypnomix-out audio
    for od in out_folders(blocked):
        for d, _, files in walk(od, blocked, depth=8):
            for f in files:
                p = d / f
                if p.suffix.lower() in AUDIO and idle_days(p) > sage and not used(p):
                    items.append(("out", "delete", p, p.stat().st_size))

    # bounces: older than 30 days, newest 5 stay
    bd = app_home() / "bounces"
    if bd.is_dir():
        bs = sorted((p for p in listdir(bd, blocked) if p.suffix.lower() in AUDIO), key=lambda p: -p.stat().st_mtime)
        for p in bs[5:]:
            if idle_days(p) > (14 if low else 30) and not used(p):
                items.append(("bounces", "delete", p, p.stat().st_size))

    # loose WAVs (switched on by the person)
    if s.get("wavs"):
        for d in (user_home() / "Desktop", user_home() / "Downloads"):
            for p in listdir(d, blocked):
                if (p.is_file() and p.suffix.lower() in LOOSE and not PROTECT.search(p.name)
                        and idle_days(p) > (14 if low else 30) and not used(p)):
                    items.append(("wavs", "hold", p, p.stat().st_size))

    # the holding area's batches past their 14 days
    keep = 0 if lvl == "critical" else 3 if low else 14
    if holding().is_dir():
        for b in listdir(holding(), blocked):
            if b.is_dir() and (time.time() - b.stat().st_mtime) / DAY > keep:
                items.append(("holding", "delete", b, size(b)))

    now = time.time()
    items = [i for i in items if now - newest(i[2]) > ACTIVE_S]
    return items, sorted(blocked)


def summary(items):
    by = {}
    for rule, action, p, n in items:
        r = by.setdefault(rule, {"rule": rule, "bytes": 0, "count": 0, "top": []})
        r["bytes"] += n
        r["count"] += 1
        r["top"].append((n, str(p)))
    for r in by.values():
        r["top"] = [{"path": p, "bytes": n} for n, p in sorted(r["top"], reverse=True)[:8]]
    return list(by.values())


# ---------------------------------------------------------------- doing it
def run(reason="by hand", job_running=lambda: False):
    with LOCK:
        if RUNNING["busy"]:
            return view()
        RUNNING["busy"] = True
    try:
        if job_running():
            return view()
        free0, total = space()
        lvl = level(free0, total)
        items, blocked = plan(lvl)
        batch = holding() / datetime.now().strftime("%Y-%m-%d_%H%M%S")
        manifest, freed, done = [], 0, 0
        for rule, action, p, n in items:
            try:
                if action == "hold":
                    batch.mkdir(parents=True, exist_ok=True)
                    dest = batch / p.name
                    shutil.move(str(p), str(dest))
                    manifest.append({"from": str(p), "to": str(dest)})
                elif p.is_dir():
                    shutil.rmtree(p)
                    freed += n
                else:
                    p.unlink()
                    freed += n
                done += 1
            except OSError:
                pass
        if manifest:
            (batch / "manifest.json").write_text(json.dumps(manifest, indent=1))
        free1, _ = space()
        s = load()
        s["last"] = dict(when=time.time(), reason=reason, level=lvl, freed=freed, held=sum(i[3] for i in items if i[1] == "hold"),
                         count=done, free_before=free0, free_after=free1, rules=summary(items), blocked=blocked)
        s["last_full"] = time.time()
        save(s)
        lvl1 = level(free1, total)
        if reason != "by hand" and should_notify(s, freed, lvl1):
            notify(f"Freed {freed / GB:.1f} GB. {free1 / GB:.0f} GB free." if lvl1 == "ok"
                   else f"Freed {freed / GB:.1f} GB, but only {free1 / GB:.0f} GB is free." if freed > GB
                   else f"Only {free1 / GB:.0f} GB is free: nothing of hypnomix's was old enough to clear.")
            s["notified"] = dict(when=time.time(), level=lvl1)
            save(s)
        return view()
    finally:
        RUNNING["busy"] = False


def restore():
    """Put the newest holding batch back where its files came from."""
    bs = sorted(b for b in holding().iterdir() if (b / "manifest.json").exists()) if holding().is_dir() else []
    back = 0
    if bs:
        b = bs[-1]
        for m in json.loads((b / "manifest.json").read_text()):
            src, dst = Path(m["to"]), Path(m["from"])
            if src.exists() and not dst.exists():
                shutil.move(str(src), str(dst))
                back += 1
        shutil.rmtree(b, ignore_errors=True)
    v = view()
    v["restored"] = back
    return v


RANK = {"ok": 0, "low": 1, "critical": 2}


def should_notify(s, freed, lvl):
    """Tell the person only when it matters: more than 1 GB freed, the disk fuller than at the last notice, or once
    a day while it stays low. Never every hour for the same news."""
    if freed > GB:
        return True
    if lvl == "ok":
        return False
    last = s.get("notified") if isinstance(s.get("notified"), dict) else {}
    if RANK.get(lvl, 0) > RANK.get(last.get("level"), 0):
        return True
    return time.time() - float(last.get("when") or 0) > DAY


def notify(msg):
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "hypnomix"'], capture_output=True)


def view():
    s = load()
    free, total = space()
    held = [b for b in holding().iterdir() if b.is_dir()] if holding().is_dir() else []
    return dict(free=free, total=total, level=level(free, total), auto=s.get("auto", True), wavs=s.get("wavs", False),
                watch=_saved(), refused=[dict(folder=f, why=w) for f, w in refused()], last=s.get("last"), busy=RUNNING["busy"],
                holding=dict(batches=len(held), bytes=sum(size(b) for b in held)))


def preview():
    items, blocked = plan()
    return dict(view(), plan=summary(items), total=sum(i[3] for i in items if i[1] == "delete"),
                held=sum(i[3] for i in items if i[1] == "hold"), blocked=blocked)


# ---------------------------------------------------------------- the hourly look while the app is open
def due():
    s = load()
    if not s.get("auto", True):
        return False
    return level() != "ok" or time.time() - s.get("last_full", 0) > 7 * DAY


def start_in_background(job_running=lambda: False, first=120, every=3600):
    if os.environ.get("HYPNOMIX_DISKCARE", "").lower() in ("off", "0", "no", "false"):
        return                                                      # test and preview copies of the app
    def loop():
        time.sleep(first)
        while True:
            try:
                if due():
                    run("automatic", job_running)
            except Exception:
                pass
            time.sleep(every)

    threading.Thread(target=loop, daemon=True, name="diskcare").start()


# ---------------------------------------------------------------- the app's routes
def handle_get(path, q):
    if path == "/diskcare.js":
        return 200, (Path(__file__).with_name("diskcare.js")).read_bytes(), "text/javascript; charset=utf-8"
    if path == "/api/diskcare/state":
        return 200, view()
    return None


def handle_post(path, body, job_running=lambda: False):
    if path == "/api/diskcare/preview":
        return 200, preview()
    if path == "/api/diskcare/run":
        return 200, run("by hand", job_running)
    if path == "/api/diskcare/settings":
        try:
            return 200, settings(body)
        except ValueError as e:                                  # a folder that can't be watched: say why
            return 400, {"error": str(e)}
    if path == "/api/diskcare/restore":
        return 200, restore()
    return None


def main():
    import argparse
    ap = argparse.ArgumentParser(prog="python -m hypnomix.app.diskcare", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="clean now (default: only show what would go)")
    a = ap.parse_args()
    r = run() if a.run else preview()
    print(f"{r['free'] / GB:.0f} GB free ({r['level']})")
    for rule in (r["last"]["rules"] if a.run else r["plan"]):
        print(f"  {rule['rule']:8} {rule['bytes'] / GB:6.2f} GB  {rule['count']} items")
        for t in rule["top"][:3]:
            print(f"             {t['path']}")
    if a.run:
        print(f"freed {r['last']['freed'] / GB:.2f} GB")
    elif r.get("blocked"):
        print("not read (the app has no access to them, or a project file is too big to open: "
              "give access to the folders if that is it):", ", ".join(r["blocked"]))


if __name__ == "__main__":
    main()
