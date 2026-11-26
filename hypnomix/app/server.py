#!/usr/bin/env python3
"""The hypnomix app: the whole first pass in a window, no terminal and no AI needed.

  hypnomix app                 start it and open it in your browser (http://127.0.0.1:8791)
  hypnomix app --no-open       just start it (the Mac app and the Max for Live device use this)

What you can do in it:
  first pass    choose a Live set, REAPER project, Ardour session (or a folder of recordings from any DAW), optionally a bounce of the mix and
                the key; it runs every check, builds the before / after clips and shows the review
  review        the fixes you can hear first, each with one player and A / B buttons, and Approve / Skip / Change with the mouse or
                the keyboard (j k a s c b space [ ] ?); decisions are saved as you act, a card at a time; the clips you played are
                remembered; "Approve all low" and "the N like this" list what they would record before they record it
  apply         says what it will do (including any on-by-default steps), writes only what you approved into ONE new
                file next to the original (.als, .rpp or .ardour), then shows what was applied, what was not and why
  preferences   the questions asked once: targets, protected tracks, what is deliberate
  tools         run any hypnomix command with a form, and read its report
  wiki          lessons, how-to guides, every command and the FAQ, offline and searchable: the same articles as the
                website's /wiki/ (source: hypnomix/app/wiki/articles/; Edit and Publish in a git checkout)
  assistant     chat with an AI (your own key: Claude, OpenAI, Gemini, OpenRouter, Groq, Mistral, or a free model
                in Ollama on this computer) that runs hypnomix for you; anything that writes a set waits for your
                click. Needs `pip install "hypnomix[assistant]"`
  Live          with the Max for Live device (`hypnomix device`) loaded in your set, "Show in Live" jumps Live
                to the finding: the track is selected, the playhead and the loop brace move to the spot, and
                the clip opens. The device also steps through the open questions from inside Live.

It is a small web server on this computer only (127.0.0.1). Nothing is sent anywhere. Songs you scan are kept
in ~/Documents/Hypnomix (change with --home or HYPNOMIX_APP_HOME). Everything it does is a hypnomix command
you could also type; the log shows each one.
"""
import argparse, json, os, re, secrets, shlex, shutil, signal, socket, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

TOKEN = secrets.token_urlsafe(18)
LOCK = threading.Lock()
JOB = {"id": 0, "status": "idle", "log": [], "title": "", "kind": "", "dir": "", "step": "", "stopped": False,
       "files": [], "reason": "", "out": "", "t0": 0.0, "step_at": 0.0, "walls": {}, "expect": 0, "prior": {}}
LIVE = {"seq": 0, "cmd": None, "seen": 0.0, "dir": "", "cursor": -1}
PROBE = {"hub": None, "error": ""}    # the probe hub (UDP from HypnomixProbe devices in Live)
AB = {"id": "", "state": "A", "since": 0.0, "last": 0.0, "match": True, "acc": {}, "skip": 0.6}
MAX_BODY = 1_000_000                   # the largest request body taken (the biggest real one is a few kilobytes)
IDLE_SECONDS = 60                      # a connection that sends nothing for this long is closed (nothing here streams)
READ_SECONDS = 30                      # once a request starts, all of it (head and body) must arrive within this, however slowly it drips
HIDDEN = {"app", "install"}            # not offered in the Tools tab (install asks questions; app is this)


def work():
    p = Path(os.environ.get("HYPNOMIX_APP_HOME", "~/Documents/Hypnomix")).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe(name):
    return re.sub(r'[\\/:*?"<>|]', "-", name).strip() or "song"


def need(body, *keys):
    """The request must carry each of these as non-empty text: or a plain sentence (a 400), never a Python KeyError."""
    for k in keys:
        v = body.get(k)
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"this request needs \"{k}\" (text), and it was missing or empty")
    return [body[k] for k in keys] if len(keys) > 1 else body[keys[0]]


WRONG_KIND = "one of the fields in this request is the wrong kind (for example a list or a number where text belongs); nothing was changed"


def whole(v, what, lo=None, hi=None):
    """A whole number from a request or a query, or a plain sentence."""
    try:
        if isinstance(v, bool) or (isinstance(v, float) and v != int(v)):
            raise ValueError
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a whole number")
    if (lo is not None and n < lo) or (hi is not None and n > hi):
        if hi is None:
            raise ValueError(f"{what} must be a whole number, {lo} or more")
        if lo is None:
            raise ValueError(f"{what} must be a whole number, {hi} or less")
        raise ValueError(f"{what} must be a whole number between {lo} and {hi}")
    return n


# ---------------------------------------------------------------- jobs
def cli_env():
    """The environment for a command the app starts: it runs THIS copy of hypnomix (the app's own commands run from the
    work folder, where a different installed copy could otherwise be found first)."""
    env = dict(os.environ)
    root = Path(__file__).resolve().parents[2]
    if (root / "hypnomix" / "cli.py").is_file():
        env["PYTHONPATH"] = str(root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def popen_job(argv):
    """A command of its own: in its own process group (POSIX session / Windows process group), so Stop can end
    the command and everything it started."""
    kw = dict(cwd=str(work()), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=cli_env())
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    return subprocess.Popen([sys.executable, "-u", "-m", "hypnomix.cli", *argv], **kw)


def kill_tree(p, wait=3.0):
    """End a job's command and every process it started (a scan starts renderers, a fix starts the tools)."""
    if p is None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        return
    try:
        os.killpg(p.pid, signal.SIGTERM)                       # the group was started by popen_job: its id is the child's
    except (ProcessLookupError, PermissionError, OSError):
        return

    def hard():
        time.sleep(wait)
        try:
            os.killpg(p.pid, signal.SIGKILL)                   # whatever ignored the polite request
        except (ProcessLookupError, PermissionError, OSError):
            pass
    threading.Thread(target=hard, daemon=True).start()


def stop_job():
    """Stop the running job: everything it started, and the temporary sets a stopped fix leaves behind."""
    if JOB["status"] != "running":
        return False
    JOB["stopped"] = True
    kill_tree(JOB.get("proc"))
    return True


def fix_leftovers(scan_d, started):
    """Remove the temporary "(fix step N)" sets a stopped fix left next to the original (only ones made by that run)."""
    removed = []
    try:
        meta = json.loads((Path(scan_d) / "findings.json").read_text())
        src = Path(meta.get("set") or "")
        rx = re.compile(re.escape(src.stem) + r" \(fix step \d+(?:\.\d+)?\)(?: full)?\.als$")
        for f in (src.parent.iterdir() if src.name else []):
            if rx.match(f.name) and f.is_file() and f.stat().st_mtime >= started - 2:
                f.unlink()
                removed.append(f.name)
    except (OSError, ValueError):
        pass
    return removed


def listing(dirs):
    """{path: mtime} of the files directly inside each folder (what a job may create)."""
    out = {}
    for d in dirs:
        try:
            for f in Path(d).iterdir():
                if f.is_file() and not f.name.startswith("."):
                    out[str(f)] = f.stat().st_mtime
        except OSError:
            pass
    return out


def job_reason(log):
    """Why a job stopped, in the command's own words: the FAILED list `fix` prints, else the last lines it said."""
    lines = [x for x in log if x.strip()]
    while lines and re.match(r"^\(.*: exit code \d+\)$", lines[-1].strip()):
        lines.pop()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith("FAILED (not done)"):
            items = []
            for x in lines[i + 1:]:
                if not x.startswith("- "):
                    break
                items.append(x[2:].strip())
            if items:
                return "; ".join(items)[:600]
    tail = []
    for x in reversed(lines):
        if x.startswith("$ hypnomix"):
            break
        tail.append(x.strip())
        if len(tail) >= 3:
            break
    return " ".join(reversed(tail))[:600]


def run_job(kind, title, steps, sdir="", watch=()):
    """steps: [(label, argv, must_succeed)]; argv may also be a function (called in the job; it may return more steps
    to run next). One job at a time. `watch`: folders whose new or changed files are listed when the job ends."""
    with LOCK:
        if JOB["status"] == "running":
            raise RuntimeError("something is already running: wait for it to finish")
        JOB.update(id=JOB["id"] + 1, status="running", log=[], title=title, kind=kind, dir=str(sdir), step="",
                   stopped=False, files=[], reason="", out="", t0=time.time(), step_at=time.time(), walls={}, expect=0, prior={})
        JOB.pop("proc", None)
    started = time.time()
    before = listing(watch)

    def go():
        ok = True
        queue = list(steps)
        while queue:
            label, act, must = queue.pop(0)
            if JOB["stopped"]:
                break
            JOB["step"] = label
            JOB["step_at"] = time.time()
            if callable(act):
                try:
                    more = act()
                    queue[0:0] = more or []
                except Exception as e:                  # a step of our own that could not be done
                    JOB["log"].append(f"{label}: could not be done ({e})")
                    if must:
                        ok = False
                        break
                JOB["walls"][label] = time.time() - JOB["step_at"]
                continue
            JOB["log"].append(f"$ hypnomix {' '.join(shlex.quote(a) for a in act)}")
            try:
                p = popen_job(act)
                JOB["proc"] = p
                for line in p.stdout:
                    JOB["log"].append(line.rstrip("\n"))
                    if len(JOB["log"]) > 4000:
                        del JOB["log"][:1000]
                code = p.wait()
            except Exception as e:                      # the interpreter could not start the command
                JOB["log"].append(f"could not run: {e}")
                code = 1
            JOB["walls"][label] = time.time() - JOB["step_at"]
            if code != 0:
                JOB["log"].append(f"({label}: exit code {code})")
                if must:
                    ok = False
                    break
        if JOB["stopped"]:
            ok = False
            JOB["log"].append("Stopped by you.")
            if kind == "fix" and sdir:
                for n in fix_leftovers(sdir, started):
                    JOB["log"].append(f"removed the temporary set it left behind: {n}")
        JOB.pop("proc", None)
        after = listing(watch)
        JOB["files"] = sorted(f for f, m in after.items() if before.get(f) != m)
        JOB["reason"] = "" if ok else ("Stopped by you." if JOB["stopped"] else job_reason(JOB["log"]))
        JOB["status"] = "done" if ok else "failed"

    threading.Thread(target=go, daemon=True).start()
    return JOB["id"]


# ---------------------------------------------------------------- scans and reviews
SET_KINDS = {".als": "als", ".rpp": "rpp", ".ardour": "ardour"}
SUFFIX = {"als": ".als", "rpp": ".rpp", "ardour": ".ardour", "folder": ""}
NO_UNDO = {"rpp": "REAPER projects", "ardour": "Ardour sessions", "folder": "folders of recordings"}


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def when_of(p):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(Path(p).stat().st_mtime))


def source_kind(source, mode=""):
    """What a scan is of: 'als' (a Live set), 'rpp' (REAPER), 'ardour' (Ardour) or 'folder' (recordings from any DAW)."""
    m = {"set": "als", "reaper": "rpp", "ardour": "ardour", "folder": "folder", "file": "folder"}.get(mode or "")
    return m or SET_KINDS.get(Path(str(source)).suffix.lower(), "folder")


def norm_decisions(dec):
    """decisions.json entries as {decision, note, ...}: an older file kept plain strings."""
    return {k: (v if isinstance(v, dict) else {"decision": str(v)}) for k, v in dec.items()} if isinstance(dec, dict) else {}


def inspect_scan(d):
    """A scan folder as it is, without raising: {data, dec, damage}. A file that cannot be read is reported, not hidden."""
    d = Path(d)
    out = dict(data=None, dec={}, damage=None)
    try:
        data = json.loads((d / "findings.json").read_text())
        if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
            raise ValueError("not a list of findings")
        out["data"] = data
    except (OSError, ValueError) as e:
        out["damage"] = dict(file="findings.json", backup=False, message=f"the scan's findings file cannot be read ({e})")
        return out
    p = d / "decisions.json"
    if p.exists():
        try:
            dec = json.loads(p.read_text())
            if not isinstance(dec, dict):
                raise ValueError("not a list of decisions")
            out["dec"] = norm_decisions(dec)
        except (OSError, ValueError) as e:
            bak = read_json(d / "decisions.json.bak")
            out["damage"] = dict(file="decisions.json", backup=isinstance(bak, dict), size=p.stat().st_size, when=when_of(p),
                                 backup_when=when_of(d / "decisions.json.bak") if isinstance(bak, dict) else "",
                                 message=f"this song's decisions file is damaged ({e})")
    return out


def stale_info(data, meta):
    """The source is a file saved after the scan was made (fix would refuse it), from scan.json's recorded modification time."""
    src = Path(str((data or {}).get("set") or meta.get("set") or ""))
    kind = source_kind(src, meta.get("mode", ""))
    if not src.name or kind == "folder":
        return None
    try:
        now = src.stat().st_mtime
    except OSError:
        return dict(missing=True, newer=False)
    was = meta.get("set_mtime")
    return dict(missing=False, newer=bool(was and now > was + 1), was=was, now=now)


def default_on(findings, dec):
    return [f for f in findings if f.get("default") == "approve" and f.get("applies") not in ("info", "answer") and f["id"] not in dec]


def stamp(*paths):
    """What a cache is keyed on: the modification time and size of each file (None for a file that is not there)."""
    out = []
    for p in paths:
        try:
            st = Path(p).stat()
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


_SCAN_CACHE = {}          # scan folder -> (stamp of its files, what was worked out from them)


def scan_summary(d):
    """What the Songs list needs from one scan folder, read again only when findings.json, decisions.json, scan.json or
    fix-log.md changed: the page asks every second, and each ask used to parse every scan's results."""
    d = Path(d)
    key = stamp(d / "findings.json", d / "decisions.json", d / "decisions.json.bak", d / "scan.json", d / "fix-log.md")
    hit = _SCAN_CACHE.get(str(d))
    if hit and hit[0] == key:
        return hit[1]
    f = d / "findings.json"
    meta = read_json(d / "scan.json", {})
    ins = inspect_scan(d) if f.exists() else dict(data=None, dec={}, damage=None)
    data = ins["data"] or {}
    source = data.get("set") or meta.get("set") or ""
    act = [x for x in data.get("findings", []) if isinstance(x, dict) and x.get("applies") not in ("info", "answer")]
    dec = ins["dec"]
    kind = source_kind(source, meta.get("mode", ""))
    row = dict(source=source, kind=kind, findings=len(act),
               source_name=(Path(source).name if kind == "folder" else Path(source).stem) if source else d.name,
               parent=str(Path(source).parent) if source else "",
               decided=sum(1 for x in act if x["id"] in dec),
               approved=sum(1 for x in act if dec.get(x["id"], {}).get("decision") == "approve"),
               on_default=len(default_on(act, dec)),
               when=when_of(f if f.exists() else d), applied=(d / "fix-log.md").exists(),
               damaged=(ins["damage"] or {}).get("file", ""), can_restore=bool((ins["damage"] or {}).get("backup")),
               incomplete=not f.exists(), meta=meta, data_set=data.get("set"))
    _SCAN_CACHE[str(d)] = (key, row)
    return row


def scans():
    out = []
    root = work() / "scan"
    if not root.is_dir():
        return out
    seen = set()
    for d in sorted(root.iterdir(), key=lambda p: -p.stat().st_mtime):
        if not d.is_dir():
            continue
        c = scan_summary(d)
        if c["incomplete"] and not c["meta"]:
            continue                                    # not a scan folder at all
        seen.add(str(d))
        source, meta = c["source"], c["meta"]
        st = stale_info({"set": c["data_set"]}, meta)       # the song itself is looked at every time: it may have been saved
        row = dict(dir=str(d), name=d.name, source=source, kind=c["kind"], findings=c["findings"], source_name=c["source_name"],
                   parent=c["parent"], decided=c["decided"], approved=c["approved"], on_default=c["on_default"], when=c["when"],
                   applied=c["applied"], damaged=c["damaged"], can_restore=c["can_restore"], incomplete=c["incomplete"],
                   running=JOB["status"] == "running" and JOB["dir"] == str(d),
                   stale=bool(st and st.get("newer")), source_missing=bool(st and st.get("missing")),
                   can_rescan=bool(source) and Path(source).exists())
        out.append(row)
    for k in [k for k in _SCAN_CACHE if k not in seen]:
        _SCAN_CACHE.pop(k, None)                        # a scan folder that is gone
    names = {}
    for r in out:
        names.setdefault(r["source_name"].lower(), set()).add(r["source"])
    for r in out:
        r["same_name"] = len(names[r["source_name"].lower()]) > 1      # the card then says which folder the song is in
    return out


_HELP = {}


def command_help(cmd):
    """`hypnomix CMD -h`, run once per command for as long as the app runs (it starts a Python process: about a second)."""
    if cmd not in _HELP:
        r = subprocess.run([sys.executable, "-m", "hypnomix.cli", cmd, "-h"], capture_output=True, text=True, env=cli_env())
        _HELP[cmd] = (r.stdout + r.stderr)[-12000:]
    return _HELP[cmd]


_COMMANDS = []


def command_list():
    """Every command the Tools tab offers: the same for as long as the app runs, so the page is sent it once, not every second."""
    if not _COMMANDS:
        from hypnomix import cli
        _COMMANDS.extend(dict(group=g, name=n, about=d) for g, cmds in cli.GROUPS for n, _, d in cmds if n not in HIDDEN)
    return _COMMANDS


def commands_rev():
    import hashlib
    return hashlib.sha1(json.dumps(command_list(), sort_keys=True).encode()).hexdigest()[:10]


def scan_dir(raw):
    """Only folders inside the app's own scan folder are ever read or written."""
    d = Path(raw).resolve()
    root = (work() / "scan").resolve()
    if root not in d.parents or not (d / "findings.json").exists():
        raise ValueError("not one of this app's scans")
    return d


def scan_slot(src):
    """(folder, reused): the folder that already holds a scan of this very path (a re-scan), else a new one named for the
    song: 'Song', then 'Song (2)', 'Song (3)' when that name is taken by a different source."""
    root = work() / "scan"
    root.mkdir(parents=True, exist_ok=True)
    want = str(Path(src).resolve())
    best = None
    for d in root.iterdir():
        if not d.is_dir():
            continue
        was = (read_json(d / "scan.json", {}) or {}).get("set") or (read_json(d / "findings.json", {}) or {}).get("set") or ""
        try:
            same = bool(was) and str(Path(was).resolve()) == want
        except (OSError, ValueError):
            same = False
        if same and (best is None or d.stat().st_mtime > best.stat().st_mtime):
            best = d
    if best is not None:
        return best, True
    base = safe(src.name if src.is_dir() else src.stem)
    cand, n = root / base, 1
    while cand.exists():
        n += 1
        cand = root / f"{base} ({n})"
    return cand, False


def free_out(source, kind):
    """The new file's name next to the original: 'Song (fixed).als', or 'Song (fixed 2).als' ... the first that is free."""
    suf, src, n = SUFFIX.get(kind, ""), Path(str(source)), 1
    while True:
        name = f"{src.stem} (fixed{'' if n == 1 else ' ' + str(n)}){suf}"
        if not (src.parent / name).exists():
            return name
        n += 1


def clean_out(raw, kind, source):
    """The name typed for the new file, with the right ending for this kind of project, and no folders in it."""
    suf = SUFFIX.get(kind, "")
    if not str(raw or "").strip():
        return free_out(source, kind)
    name = safe(str(raw)).strip(" .")
    more = True
    while more:                                      # "Song.rpp.als" and "Song.als" are both just "Song" with the right ending added
        more = False
        for end in (".als", ".rpp", ".ardour"):
            if name.lower().endswith(end):
                name, more = name[:-len(end)].strip(" ."), True
    return (name + suf) if name else free_out(source, kind)


def archive_name(source):
    """The name `fix` will give the full copy it writes before removing switched-off tracks."""
    try:
        from hypnomix.session.tidy import archive_path
        return archive_path(Path(source)).name
    except Exception:
        return re.sub(r" \([^()]*\)$", "", Path(source).stem) + " (archive, all takes).als"


ARDOUR_OPS = ("fade", "cut", "dip", "mixer")        # what fix writes into an Ardour session (workflow/fix_ardour.py)


def applies_here(kind, f):
    """How `fix` treats this finding for this kind of project, where that differs from what the finding says: an Ardour
    session takes fades, cuts, spikes and mixer moves only (the rest stays by hand), and tuning is refused outright."""
    a = f.get("applies")
    if kind == "ardour":
        if a == "set" and (f.get("edit") or {}).get("op") not in ARDOUR_OPS:
            return "manual"
        if a == "audio" and f.get("tool") == "tune":
            return "blocked"
    return a


def apply_plan(findings, dec):
    """What `fix --approved` will do with these decisions: the same rule it follows (an explicit approve, or a finding that
    is on by default and has no decision of yours; amount 0 applies nothing; by-hand items are only listed)."""
    auto, defaults, manual, zero, blocked, defmanual = [], [], [], [], [], []
    for f in findings:
        if f.get("applies") in ("info", "answer"):
            continue
        ap = f.get("applies_here") or f.get("applies")
        e = dec.get(f["id"]) or {}
        d = e.get("decision")
        if d == "approve":
            how = "approved"
        elif not d and f.get("default") == "approve" and f["id"] not in dec:
            how = "default"
        else:
            continue
        if e.get("amount") == 0:
            zero.append(f)
        elif ap == "blocked":
            blocked.append(f)
        elif ap == "manual":
            (defmanual if how == "default" else manual).append(f)
        else:
            auto.append(f)
            if how == "default":
                defaults.append(f)
    return dict(auto=auto, defaults=defaults, manual=manual, zero=zero, blocked=blocked, defmanual=defmanual)


def writes_set(f):
    return f.get("applies") == "set" or (f.get("applies") == "audio" and f.get("tool") in ("tune", "voices"))


_SET_GRID = {}


def set_grid(source):
    """(tempo, beats per bar) of a set, or (None, 4). Reading a big set means unzipping and parsing the whole file, and the
    review is asked for twice a second by the Live device, so the answer is kept by (path, modification time)."""
    try:
        key = (str(source), Path(source).stat().st_mtime_ns)
    except OSError:
        return None, 4
    if key not in _SET_GRID:
        try:
            from hypnomix.session import automation as aa, beats as B
            tree = aa.load(source)
            grid = (B.set_tempo(tree.getroot()), aa.BPB)
        except Exception:
            grid = (None, 4)
        for k in [k for k in _SET_GRID if k[0] == key[0]]:
            _SET_GRID.pop(k)                        # an older version of the same file
        if len(_SET_GRID) > 16:
            _SET_GRID.clear()
        _SET_GRID[key] = grid
    return _SET_GRID[key]


def locate(f, tempo, bpb):
    """Where a finding is in the Arrangement, in beats: (start, end) or None. Reads the finding's `where`."""
    w = str(f.get("where") or "")
    m = re.search(r"bars?\s+(\d+)\s*(?:-|to|–)\s*(\d+)", w)
    if m:
        return (int(m[1]) - 1) * bpb, int(m[2]) * bpb
    m = re.search(r"(?<![\d:])(\d+)\.(\d+(?:\.\d+)?)", w)
    if m:
        b = (int(m[1]) - 1) * bpb + max(0.0, float(m[2]) - 1)
        return max(0.0, b - 1), b + 3
    m = re.search(r"bars?\s+(\d+)", w)
    if m:
        return (int(m[1]) - 1) * bpb, int(m[1]) * bpb
    m = re.search(r"(\d+):(\d\d(?:\.\d+)?)", w)
    if m and tempo:
        b = (int(m[1]) * 60 + float(m[2])) * tempo / 60.0
        return max(0.0, b - 1), b + 3
    return None


_RPP_GRID = {}


def rpp_grid(path):
    """(tempo, beats per bar) of a REAPER project, cached by its modification time (asked twice a second)."""
    key = (str(path), Path(path).stat().st_mtime)
    if key not in _RPP_GRID:
        from hypnomix.project import load as _load_project
        p = _load_project(path)
        _RPP_GRID.clear()
        _RPP_GRID[key] = (p.tempo, p.beats_per_bar)
    return _RPP_GRID[key]


PLACEHOLDER_PAYLOAD = dict(is_set=False, mode="folder", kind="folder", suffix="", findings=[], decisions={}, ab={}, prefs=[],
                           broken=[], fix_log="", last_run=None, suggested_out="", archive_name="", oversight={}, ab_live=None,
                           blind=[], stale=None, handoff=[], can_rescan=False, heard={})


_LIGHT = {}               # scan folder -> (stamp of its files, the song it is of, that song's stamp, the light payload)


def light_files(d):
    d = Path(d)
    return stamp(d / "findings.json", d / "decisions.json", d / "scan.json", d / "ab" / "ab.json", d / "ab_live.json")


def review_payload(d, light=False):
    """light: only what the Live device needs (it asks twice a second): no oversight extras, no fix log. The light one is
    kept until one of the files it was made from (or the song itself) changes, and must be treated as read-only."""
    from hypnomix.workflow import prefs as P
    fkey = light_files(d) if light else None          # taken before the files are read: a save in between is seen next time
    if light:
        hit = _LIGHT.get(str(d))
        if hit and hit[0] == fkey and hit[2] == stamp(hit[1] or "/nonexistent")[0]:
            return hit[3]
    ins = inspect_scan(d)
    meta = read_json(Path(d) / "scan.json", {}) or {}
    data, dec = ins["data"], ins["dec"]
    if data is None:                               # the findings file itself is damaged: say so, never a raw error
        src = meta.get("set", "")
        return dict(PLACEHOLDER_PAYLOAD, dir=str(d), name=Path(d).name, source=src, damaged=ins["damage"],
                    can_rescan=bool(src) and Path(src).exists(), kind=source_kind(src, meta.get("mode", "")))
    ab = read_json(Path(d) / "ab" / "ab.json", {}) or {}
    source = data.get("set", "")
    rpp_ = str(source).lower().endswith(".rpp")              # a REAPER project jumps and A/Bs like a Live set
    is_set = str(source).lower().endswith(".als") or rpp_
    kind = source_kind(source, meta.get("mode", ""))
    if rpp_ and Path(source).exists():
        try:
            tempo, bpb = rpp_grid(source)
        except Exception:                                  # a project that cannot be read now still has its review
            tempo, bpb = None, 4
    else:
        tempo, bpb = set_grid(source) if is_set and Path(source).exists() else (None, 4)
    for f in data["findings"]:
        span = locate(f, tempo, bpb) if is_set else None
        if span and f.get("track") not in (None, "", "mix"):
            f["jump"] = dict(track=f["track"], start=round(span[0], 3), end=round(span[1], 3))
        elif is_set and f.get("track") not in (None, "", "mix"):
            f["jump"] = dict(track=f["track"])
        f["on_by_default"] = f.get("default") == "approve"
        f["applies_here"] = applies_here(source_kind(source, meta.get("mode", "")), f)
        if isinstance(f.get("retire"), list):
            f["retire_n"] = len(f["retire"])
    if light:
        out = dict(dir=str(d), name=Path(d).name, source=source, is_set=is_set, findings=data["findings"], decisions=dec, ab=ab,
                   ab_live=ab_spec(d))
        if len(_LIGHT) > 16:
            _LIGHT.pop(next(iter(_LIGHT)))
        _LIGHT[str(d)] = (fkey, source, stamp(source or "/nonexistent")[0], out)
        return out
    notes = data.get("notes", [])
    full = (Path(d) / "fix-log.md").read_text() if (Path(d) / "fix-log.md").exists() else ""
    st = stale_info(data, meta)
    needs_archive = kind == "als" and any(f.get("kind") == "retire-off" for f in data["findings"])
    return dict(dir=str(d), name=Path(d).name, source=source, is_set=is_set, kind=kind, suffix=SUFFIX[kind],
                mode=meta.get("mode", "set" if is_set else "folder"),
                findings=data["findings"], decisions=dec, ab=ab, prefs=P.summary(P.load()), damaged=ins["damage"],
                broken=[n for n in notes if "failed" in n or n.startswith("WARNING") or "did NOT run" in n],
                fix_log=full[-6000:], last_run=parse_fix_log(full),
                suggested_out=free_out(source, kind) if kind != "folder" and source else "",
                archive_name=archive_name(source) if needs_archive and Path(source).exists() else "",
                stale=st, can_rescan=bool(source) and Path(source).exists(),
                handoff=sorted(x.name for x in (Path(d) / "handoff").glob("*") if x.is_file()) if (Path(d) / "handoff").is_dir() else [],
                oversight=ov_payload(d, data["findings"]), ab_live=ab_spec(d), blind=read_json(Path(d) / "blind.json", []),
                heard=heard_of(d))


def ov_payload(d, findings):
    try:
        from hypnomix.workflow import review as R
        return R.oversight_payload(d, findings)
    except Exception as e:                     # the review still works without the extras
        return {"error": str(e)}


def actionable(d):
    p = review_payload(d, light=True)                  # kept between calls: the device asks twice a second
    return [f for f in p["findings"] if f.get("applies") not in ("info", "answer")], p["decisions"]


def decisions_ok(d):
    """Refuse (plainly) to record anything while the decisions file is damaged: it would be lost or make it worse."""
    dmg = inspect_scan(d)["damage"]
    if dmg and dmg["file"] == "decisions.json":
        raise RuntimeError("this song's decisions file is damaged, so nothing can be saved until it is restored or started "
                           "again (open the song: the page says how)")
    if dmg:
        raise RuntimeError("this scan's findings file is damaged: re-scan the song")


def restore_decisions(d, fresh=False):
    """Put decisions.json.bak back (or start a new empty decisions file). The damaged file is kept next to it, never deleted."""
    d = Path(d)
    cur, bak = d / "decisions.json", d / "decisions.json.bak"
    b = None if fresh else read_json(bak)
    if not fresh and not isinstance(b, dict):
        raise RuntimeError("there is no readable backup of the decisions (decisions.json.bak): start the decisions again instead")
    kept = ""
    if cur.exists():
        n, kept_p = 1, d / "decisions.damaged.json"
        while kept_p.exists():
            n += 1
            kept_p = d / f"decisions.damaged {n}.json"
        shutil.copyfile(cur, kept_p)
        kept = kept_p.name
    if fresh:
        cur.write_text("{}")
        return dict(restored=False, kept=kept)
    shutil.copyfile(bak, cur)
    return dict(restored=True, kept=kept, decisions=len(b))


# ---- the fix log, and what happened when it ran
def log_group(title):
    t = title.lower()
    if "failed" in t:
        return "failed"
    if re.search(r"not applied|skipped|by hand|left alone|refus|not done|could not|not written", t):
        return "not_applied"
    if "default" in t:
        return "default"
    return "applied"


def parse_fix_log(text):
    """The last '## fix run' of fix-log.md as text grouped under its own headings. It does not depend on what the
    headings say: unknown ones count as 'applied', and any line saying FAILED is marked."""
    parts = re.split(r"(?m)^## fix run ", text or "")
    if len(parts) < 2:
        return None
    head, _, rest = parts[-1].partition("\n")
    secs, cur, intro, hist = [], None, [], ""
    for line in rest.split("\n"):
        if line.startswith("history:"):
            hist = line
            continue
        m = re.match(r"^###\s+(.*)$", line)
        if m:
            cur = dict(title=m[1].strip(), lines=[])
            secs.append(cur)
            continue
        if line.strip().startswith("```"):
            continue
        (cur["lines"] if cur else intro).append(line)
    for s in secs:
        while s["lines"] and not s["lines"][-1].strip():
            s["lines"].pop()
        while s["lines"] and not s["lines"][0].strip():
            s["lines"].pop(0)
        s["group"] = log_group(s["title"])
        s["lines"] = [dict(t=x, bad="FAILED" in x or s["group"] == "failed") for x in s["lines"]]
    return dict(when=head.strip(), intro=[x for x in intro if x.strip()], sections=secs, history=hist, raw=rest)


def hist_entries(d, h, kind, source):
    """History versions as the page shows them, each with whether it can be undone and what that would write."""
    from hypnomix.workflow import history as H
    d = Path(d)
    meta = read_json(d / "scan.json", {}) or {}
    rows = []
    for v in reversed(h.get("versions", [])):
        snap = v.get("input_snapshot")
        wrote = bool(v.get("output"))
        can = kind == "als" and wrote and bool(snap) and (d / "history" / snap).exists()
        if can:
            orig = Path(meta.get("set") or v.get("input") or source)
            name, why = H.free_name(orig.with_name(f"{orig.stem} (back to v{v['n']} input).als")).name, ""
        elif kind != "als":
            name = ""
            why = (f"hypnomix keeps no snapshot of {NO_UNDO.get(kind, 'this')} to go back to, so there is no Undo button here. "
                   "Your original was never changed: keep using it, or open it again; the new file is a separate copy.")
        elif not wrote:
            name = ""
            why = "this run wrote no new set, so there is nothing to undo. Your original set was never changed."
        else:
            name = ""
            why = "this run kept no copy of its set, so it cannot be undone from here. Your original set was never changed."
        rows.append(dict(n=v.get("n"), at=v.get("at", ""), kind=v.get("kind", ""),
                         output=Path(v["output"]).name if v.get("output") else "", input=Path(v["input"]).name if v.get("input") else "",
                         approved=[a.get("id") for a in v.get("approved", [])], changes=v.get("changes"),
                         failed=v.get("failed") or [], can_undo=can, undo_name=name, why_not=why))
    return rows


def has_position(where):
    """True when a finding's `where` names a place in the song (a bar, a time), not a count such as "1 clip(s)"."""
    try:
        from hypnomix.workflow import handoff as H
        return bool(H.positions(str(where or ""), 120))
    except Exception:
        return False


def fix_result(d):
    """What the last apply did, for the result page: new files, what was applied and what was not (and why), where to listen."""
    d = Path(d)
    ins = inspect_scan(d)
    data = ins["data"] or {}
    meta = read_json(d / "scan.json", {}) or {}
    source = data.get("set", "")
    kind = source_kind(source, meta.get("mode", ""))
    text = (d / "fix-log.md").read_text() if (d / "fix-log.md").exists() else ""
    run = parse_fix_log(text)
    h = read_json(d / "history" / "history.json", {"versions": []}) or {"versions": []}
    v = h["versions"][-1] if h.get("versions") else None
    mine = JOB["dir"] == str(d) and JOB["kind"] == "fix"
    status = JOB["status"] if mine else ("done" if run else "idle")
    job_log = "\n".join(JOB["log"]) if mine else ""
    files, seen = [], set()

    def add(p, what):
        p = Path(p)
        if str(p) not in seen and p.exists():
            seen.add(str(p))
            files.append(dict(name=p.name, path=str(p), folder=str(p.parent), what=what))
    NEW, ARCH = "The new project: your original is untouched", "A full copy of the set as it was, kept before tracks were removed"
    if mine and status != "running":
        for f in JOB["files"]:
            nm = Path(f).name
            add(f, ARCH if "(archive" in nm else NEW if kind != "folder" and nm.lower().endswith(SUFFIX[kind]) else "A repaired copy")
    if v and v.get("output") and (not mine or status != "failed" or JOB["files"]):
        add(v["output"], NEW)
    for m in re.finditer(r"archived the full set as (.+?\.als)", ((run or {}).get("raw", "") + "\n" + job_log)):
        add(Path(source).parent / m[1].strip(), ARCH)
    by_id = {f["id"]: f for f in data.get("findings", [])}
    body = "\n".join(l["t"] for s in (run or {}).get("sections", []) if s["group"] in ("not_applied", "failed") for l in s["lines"])
    left = {i for i in by_id if re.search(r"(?m)^[-*] " + re.escape(i) + r"[\s:@]", body)}
    ids = [a["id"] for a in (v or {}).get("approved", [])] if v else []
    applied = [by_id[i] for i in ids if i in by_id and i not in left and by_id[i].get("applies") not in ("manual", "info")]
    listen = [dict(id=f["id"], track=f.get("track") or "", where=f.get("where") or "", tool=f.get("tool", ""),
                   what=str(f.get("fix") or "").split("\n")[0][:140]) for f in applied if has_position(f.get("where"))]   # a spot to listen at
    default_ids = []
    m = re.search(r"on by default[^:\n]*:\s*(.+)", job_log)
    if m:
        default_ids = [x.strip() for x in m[1].split(",") if x.strip() in by_id]
    last = hist_entries(d, h, kind, source)[0] if v else None
    nothing = status == "done" and not files
    note = next((x.strip() for x in job_log.split("\n") if re.search(r"no set changes|nothing to apply|nothing approved", x, re.I)), "")
    return dict(wrote_nothing=nothing, note=note, dir=str(d), name=d.name, status=status, ok=status != "failed" and bool(run or v), stopped=bool(mine and JOB["stopped"]),
                reason=JOB["reason"] if mine and status == "failed" else "", tail=JOB["log"][-12:] if mine and status == "failed" else [],
                kind=kind, run=run, files=files, listen=listen, default_ids=default_ids,
                applied=[dict(id=f["id"], track=f.get("track") or "", where=f.get("where") or "") for f in applied],
                undo=last, handoff=sorted(x.name for x in (d / "handoff").glob("*") if x.is_file()) if (d / "handoff").is_dir() else [])


# ---------------------------------------------------------------- what the review page records
DEC_LOCK = threading.RLock()           # one change to a scan's decisions at a time (a click, a batch, the Live device, "heard")
TASTE_TOOLS = ("tune", "voices", "motion", "colour", "borrow", "variations")     # taste calls: always decided one at a time
TIDY_TOOLS = ("order", "tidy")                                                  # reorder, remove, merge: structure, not sound
TIDY_KINDS = ("track-order", "retire-off", "consolidate", "vocal-stack")


def write_json_atomic(path, obj):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1))
    os.replace(tmp, path)


def heard_of(d):
    """{finding id: ["a", "b"]}: which of its A / B clips the person has played (heard.json in the scan folder)."""
    h = read_json(Path(d) / "heard.json", {})
    out = {}
    for fid, v in (h.items() if isinstance(h, dict) else []):
        if isinstance(v, dict):
            out[fid] = sorted(k for k in v if k in ("a", "b"))
    return out


def patch_heard(d, ids):
    """Copy what was heard into the decision entries of these findings, so decisions.json says it with the decision. A decision
    written by the shared writer carries only its own fields: this puts `heard` back after every write."""
    d = Path(d)
    heard = heard_of(d)
    if not heard:
        return                                             # nothing was played in this scan: nothing to copy, and no file to read again
    cur = d / "decisions.json"
    try:
        dec = json.loads(cur.read_text())
    except (OSError, ValueError):
        return
    if not isinstance(dec, dict):
        return
    changed = False
    for fid in ids:
        e, h = dec.get(fid), heard.get(fid)
        if isinstance(e, dict) and h and e.get("heard") != h:
            e["heard"] = h
            changed = True
    if changed:
        write_json_atomic(cur, dec)


def mark_heard(d, fid, which):
    """The person played this finding's A or B clip. Kept in heard.json (a finding with no decision yet has no entry in
    decisions.json, and an entry without a decision would turn off an on-by-default step), and copied into the decision."""
    which = str(which).lower()
    if which not in ("a", "b"):
        raise ValueError('which must be "a" or "b"')
    d = Path(d)
    with DEC_LOCK:
        if fid not in {f.get("id") for f in (inspect_scan(d)["data"] or {}).get("findings", [])}:
            raise ValueError(f"unknown id: {fid}")
        h = read_json(d / "heard.json", {})
        h = h if isinstance(h, dict) else {}
        e = h.setdefault(fid, {})
        if which not in e:
            e[which] = time.strftime("%Y-%m-%d %H:%M")
            write_json_atomic(d / "heard.json", h)
        patch_heard(d, [fid])
        return {"heard": sorted(k for k in e if k in ("a", "b"))}


def record_one(d, fid, decision, note="", amount=None, by=None, via=None):
    """One decision, through the shared writer (workflow/review.py), then what was heard put back beside it."""
    from hypnomix.workflow import review as R
    with DEC_LOCK:
        e = R.record(d, fid, decision, note, amount=amount, by=by, via=via)
        h = heard_of(d).get(fid)
        if h:
            patch_heard(d, [fid])
        return dict(e, heard=h) if h else e


def record_many(d, ids, decision, note="", amount=None, by=None, via=None):
    """The same decision for several findings in ONE write (a request and a file write, not one for each). Every id is checked
    first: one that is not in the scan stops the whole batch with nothing recorded."""
    from hypnomix.workflow import oversight as O
    d = Path(d)
    if decision not in O.DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(O.DECISIONS)}")
    if not isinstance(ids, list) or not all(isinstance(i, str) and i for i in ids):
        raise ValueError("ids must be a list of finding ids")
    if amount is not None:
        amount = whole(amount, "amount", 0, 100)
    with DEC_LOCK:
        known = {f.get("id") for f in (inspect_scan(d)["data"] or {}).get("findings", [])}
        bad = [i for i in ids if i not in known]
        if bad:
            raise ValueError("unknown id: " + ", ".join(bad[:5]))
        cur = d / "decisions.json"
        dec = json.loads(cur.read_text()) if cur.exists() else {}
        heard = heard_of(d)
        out = {}
        for fid in dict.fromkeys(ids):
            old = dec.get(fid) if isinstance(dec.get(fid), dict) else {}
            e = O.entry(decision, note, amount, by=by or None, via=via)
            if old.get("conflicts"):                      # a conflict stays visible until it is settled (the shared writer does the same)
                e["conflicts"] = old["conflicts"]
            if heard.get(fid):
                e["heard"] = heard[fid]
            dec[fid] = e
            out[fid] = e
        write_json_atomic(cur, dec)
    return out


def preview_row(f, ab, heard, dec=None):
    """One finding as the confirm lists show it: what it is, where, and whether it has a preview and was played."""
    fid = f.get("id")
    pv = bool((ab.get(fid) or {}).get("a")) if isinstance(ab, dict) else False
    return dict(id=fid, track=f.get("track") or f.get("tool") or "", where=f.get("where") or "", tool=f.get("tool") or "",
                kind=f.get("kind") or "", severity=f.get("severity") or "", fix=str(f.get("fix") or "").split("\n")[0][:160],
                problem=str(f.get("problem") or "")[:160], preview=pv, heard=bool(heard.get(fid)))


def is_taste_call(f):
    """A finding that is a matter of taste: the tools that always ask, or anything the finding itself marks as taste."""
    return (f.get("tool") in TASTE_TOOLS or bool(f.get("taste")) or str(f.get("kind") or "") == "taste"
            or str(f.get("applies") or "") == "answer")


def low_candidates(findings, dec):
    """(what "Approve all low" may approve, what it leaves out and why). It never takes a taste call (tuning, harmony balance,
    motion, colour, borrowed moves, variations), a tidy step (reordering, removing or merging tracks: on by default or not), a
    protected track, a by-hand item, or anything already decided."""
    from hypnomix.workflow import oversight as O
    ok, out = [], dict(taste=0, tidy=0, protected=0, by_hand=0)
    for f in findings:
        ap = f.get("applies_here") or f.get("applies")
        if f.get("severity") != "low" or ap in ("info", "answer", None) or O.decision_of(dec, f.get("id")):
            continue
        if f.get("default") == "approve" or f.get("tool") in TIDY_TOOLS or f.get("kind") in TIDY_KINDS:
            out["tidy"] += 1
        elif is_taste_call(f):
            out["taste"] += 1
        elif f.get("protected"):
            out["protected"] += 1
        elif ap in ("manual", "blocked"):
            out["by_hand"] += 1
        else:
            ok.append(f)
    return ok, out


def listing_of(rows):
    return dict(items=rows, n=len(rows), with_preview=sum(1 for r in rows if r["preview"]), heard=sum(1 for r in rows if r["heard"]))


def decide_low(d, ids=None, dry_run=True, by=None):
    """The list "Approve all low" would approve (dry_run), or approve exactly the ids from that list that are still allowed."""
    p = review_payload(d, light=True)
    ok, left_out = low_candidates(p["findings"], p["decisions"])
    heard = heard_of(d)
    rows = [preview_row(f, p["ab"], heard) for f in ok]
    if dry_run:
        return dict(listing_of(rows), left_out=left_out)
    if ids is not None and (not isinstance(ids, list) or not all(isinstance(i, str) for i in ids)):
        raise ValueError("ids must be a list of finding ids (text)")
    allowed = {r["id"] for r in rows}
    chosen = [i for i in (ids or []) if i in allowed]
    refused = [i for i in (ids or []) if i not in allowed]
    entries = record_many(d, chosen, "approve", "batch: all low (the list was shown first)", by=by, via="bulk-low") if chosen else {}
    return dict(ids=chosen, refused=refused, entries=entries)


def like_rows(d, fid):
    """The findings `decide-like` would record for this example (the example itself, if undecided, and the undecided ones like
    it): the same matching `fix --decide-like` and the shared writer use, listed without recording anything."""
    from hypnomix.workflow import oversight as O
    p = review_payload(d, light=True)
    by_id = {f["id"]: f for f in p["findings"]}
    if fid not in by_id:
        raise ValueError(f"unknown id: {fid}")
    dec = p["decisions"]
    matched = O.like(p["findings"], dec, by_id[fid], band=0.5, role_of=O.roles(d))
    todo = ([by_id[fid]] if not O.decision_of(dec, fid) else []) + matched
    heard = heard_of(d)
    return dict(listing_of([preview_row(f, p["ab"], heard) for f in todo]), includes_example=not O.decision_of(dec, fid))


# ---------------------------------------------------------------- how far a running job has got
GROUP_DONE = re.compile(r"^\s{2}([a-z][\w-]*)\s+(\d+)\s+findings\s+\((\d+)\s*s\)")
FIX_DONE = re.compile(r"^([a-z][\w-]*)\s+(ok|FAILED|REFUSED|nothing to apply)\b")
SCAN_WORKERS = 4                                                  # scan's default --jobs


def scan_groups(log):
    """(the groups a scan says it will run, {group: seconds it took} for those finished), from the scan's own output."""
    groups, done = None, {}
    for line in log:
        if line.startswith("scanning ") and " → " in line:
            part = line.rpartition(" → ")[0].rsplit(": ", 1)[-1]
            groups = [g.strip() for g in part.split(",") if g.strip() and g.strip() != "nothing changed"]
        m = GROUP_DONE.match(line)
        if m:
            done[m[1]] = int(m[3])
    return groups, done


def prior_times(d):
    """What the last scan of this folder took, to estimate this one: {groups: {name: seconds}, wall, ab_wall}. From scan.json's
    group_seconds if the scan wrote them, else from what this app kept (app-scan.json), else from the per-group result
    files that are still there from the last scan. Empty for a first scan."""
    d = Path(d)
    out = dict(groups={}, wall=None, ab_wall=None)
    kept = (read_json(d / "app-scan.json", {}) or {}).get("times") or {}
    gs = (read_json(d / "scan.json", {}) or {}).get("group_seconds")
    if isinstance(gs, dict) and gs:
        out["groups"] = {k: float(v) for k, v in gs.items() if isinstance(v, (int, float))}
    elif isinstance(kept.get("groups"), dict):
        out["groups"] = {k: float(v) for k, v in kept["groups"].items() if isinstance(v, (int, float))}
    else:
        for f in d.glob("*.json"):
            j = read_json(f, None)
            if isinstance(j, dict) and j.get("group") == f.stem and isinstance(j.get("seconds"), (int, float)):
                out["groups"][f.stem] = float(j["seconds"])
    for k in ("wall", "ab_wall"):
        if isinstance(kept.get(k), (int, float)):
            out[k] = float(kept[k])
    out["names"] = kept.get("names") if isinstance(kept.get("names"), list) else None
    return out


def scan_eta(groups, prior, elapsed):
    """(seconds left, seconds the whole scan took last time) or (None, None) when there is nothing honest to base it on: a group
    that has never run here has no past time, so no estimate is made."""
    last = prior.get("groups") or {}
    if not groups or any(g not in last for g in groups):
        return None, None
    secs = [last[g] for g in groups]
    total = max(max(secs), sum(secs) / max(1, min(SCAN_WORKERS, len(groups))))
    if prior.get("wall") and prior.get("names") and set(prior["names"]) == set(groups):
        total = prior["wall"]
    return max(0.0, total - elapsed), total


def job_progress():
    """How far the running job has got, only from what its commands print: groups finished and the ones still running (with an
    estimate from the last scan's own times when there is one), steps of a preview or an apply. Never a percentage."""
    if JOB["status"] != "running":
        return None
    now = time.time()
    step, elapsed = JOB.get("step") or "", max(0.0, now - (JOB.get("step_at") or now))
    out = dict(kind="other", step=step, elapsed=round(elapsed), since_start=round(max(0.0, now - (JOB.get("t0") or now))))
    log = list(JOB["log"])
    if step.startswith("Scanning"):
        groups, done = scan_groups(log)
        prior = JOB.get("prior") or {}
        pending = [g for g in (groups or []) if g not in done]
        eta, last_total = scan_eta(groups, prior, elapsed) if groups else (None, None)
        out.update(kind="scan", done=len(done), total=len(groups) if groups is not None else None, pending=pending,
                   last={g: prior.get("groups", {}).get(g) for g in pending if g in (prior.get("groups") or {})},
                   eta=None if eta is None else round(eta), last_total=None if last_total is None else round(last_total),
                   over=bool(eta is not None and elapsed > (last_total or 0)))
    elif step.startswith("Building before"):
        prior = JOB.get("prior") or {}
        n = sum(1 for x in log if x.startswith("rendering "))
        left = None if not prior.get("ab_wall") else max(0.0, prior["ab_wall"] - elapsed)
        out.update(kind="ab", done=n, total=None, eta=None if left is None else round(left),
                   last_total=None if not prior.get("ab_wall") else round(prior["ab_wall"]),
                   over=bool(prior.get("ab_wall") and elapsed > prior["ab_wall"]))
    elif step.startswith("Applying"):
        n = sum(1 for x in log if FIX_DONE.match(x))
        out.update(kind="fix", done=n, total=JOB.get("expect") or None)
    return out


def save_times(d):
    """After a scan (and its previews): keep what each group and the whole run took in app-scan.json, for the next estimate."""
    d = Path(d)
    p = d / "app-scan.json"
    cur = read_json(p, {}) or {}
    times = dict(cur.get("times") or {})
    walls = JOB.get("walls") or {}
    scan_wall = next((v for k, v in walls.items() if k.startswith("Scanning")), None)
    groups, done = scan_groups(JOB["log"])
    if scan_wall is not None and groups:                     # a scan that found nothing to re-run says nothing about how long one takes
        if done:
            times["groups"] = {**(times.get("groups") or {}), **done}          # a re-scan that re-ran a few groups keeps the rest
        times["wall"] = round(scan_wall, 1)
        times["names"] = groups
    ab_wall = next((v for k, v in walls.items() if k.startswith("Building before")), None)
    if ab_wall is not None and not any(x.startswith("(Building before / after clips: exit code") for x in JOB["log"]):
        times["ab_wall"] = round(ab_wall, 1)
    cur["times"] = times
    write_json_atomic(p, cur)


# ---------------------------------------------------------------- the Live device link
def live_send(cmd):
    LIVE["seq"] += 1
    LIVE["cmd"] = cmd
    return LIVE["seq"]


def live_current():
    """The finding the Live device is looking at (for its display), or a short status."""
    if not LIVE["dir"]:
        return dict(text="Open a review in the hypnomix app first.", n=0, of=0)
    try:
        d = scan_dir(LIVE["dir"])
        act, dec = actionable(d)
        payload = {f["id"]: f for f in review_payload(d, light=True)["findings"]}
    except Exception:
        return dict(text="That review is no longer there.", n=0, of=0)
    left = sum(1 for f in act if f["id"] not in dec)
    if not act:
        return dict(text="Nothing to review in this scan.", n=0, of=0, left=0)
    i = max(0, min(len(act) - 1, LIVE["cursor"]))
    f = payload[act[i]["id"]]
    return dict(n=i + 1, of=len(act), left=left, id=f["id"], track=f.get("track") or f.get("tool"), where=f.get("where") or "",
                severity=f.get("severity"), problem=f.get("problem", ""), fix=str(f.get("fix", "")).split("\n")[0][:240],
                decision=dec.get(f["id"], {}).get("decision", ""), jump=f.get("jump"), song=d.name,
                ab=ab_spec(d, f["id"]), match=AB["match"])


def live_step(delta, undecided=False):
    d = scan_dir(LIVE["dir"])
    act, dec = actionable(d)
    if not act:
        return
    i = LIVE["cursor"]
    for _ in range(len(act)):
        i = (i + delta) % len(act)
        if not undecided or act[i]["id"] not in dec:
            break
    LIVE["cursor"] = i
    cur = live_current()
    if cur.get("jump"):
        live_send(dict(type="jump", **cur["jump"]))


# ---------------------------------------------------------------- probe and in-Live A/B
def ab_spec(d, fid=None):
    f = Path(d) / "ab_live.json"
    if not f.exists():
        return None
    spec = json.loads(f.read_text())
    if fid is None:
        return spec
    it = spec.get("items", {}).get(fid)
    if not it or not it.get("parts"):
        return None
    return dict(set=Path(spec["set"]).name, parts=it["parts"])


def ab_set_state(fid, state, match=None):
    if fid != AB["id"] or state != AB["state"]:
        AB.update(id=fid, state=state, since=time.time(), last=0.0)
    if match is not None:
        AB["match"] = bool(match)


def ab_gain():
    """Loudness of A and B on Main while each plays (measured before the probe's own gain); B is matched to A."""
    hub = PROBE["hub"]
    if not hub or not AB["id"]:
        return 0.0, None
    rows = hub.last_main(max(AB["since"] + AB["skip"], AB["last"]))       # skip the moment of switching
    acc = AB["acc"].setdefault(f"{AB['id']}|{AB['state']}", [0.0, 0])
    for r in rows:
        v = r[5]
        acc[0] += v[0] ** 2 + v[1] ** 2
        acc[1] += 1
        AB["last"] = r[0] + 1e-6
    a, b = AB["acc"].get(f"{AB['id']}|A"), AB["acc"].get(f"{AB['id']}|B")
    if not (a and b and a[1] >= 30 and b[1] >= 30 and a[0] > 0 and b[0] > 0):
        return 0.0, None
    import math
    diff = 10 * math.log10((a[0] / a[1]) / (b[0] / b[1]))          # A minus B, in dB
    diff = max(-12.0, min(12.0, diff))
    return (diff if AB["state"] == "B" and AB["match"] else 0.0), round(diff, 2)


def blind_record(d, body):
    f = Path(d) / "blind.json"
    rows = json.loads(f.read_text()) if f.exists() else []
    rows.append(dict(id=body["id"], chose=body["chose"], x=body.get("x", ""), at=time.strftime("%Y-%m-%d %H:%M"),
                     listens=body.get("listens", 0)))
    f.write_text(json.dumps(rows, indent=1))
    mine = [r for r in rows if r["id"] == body["id"]]
    return dict(n=len(mine), b=sum(1 for r in mine if r["chose"] == "B"))


def cards_file():
    return work() / "cards.json"


def card_save(sig, chords=None, params=None):
    f = cards_file()
    allc = json.loads(f.read_text()) if f.exists() else {}
    c = allc.setdefault(sig, {})
    if chords is not None:
        c["chords"] = chords
    if params:
        c["params"] = params
    c["updated"] = time.strftime("%Y-%m-%d %H:%M")
    f.write_text(json.dumps(allc, indent=1))
    return c


MASTER = {"path": "", "song": ""}


def master_record(body, render=None):
    """Main's Record and review: start → a file to record into (and the probes start listening); stop → the review.
    `render(path)` writes the recording first (REAPER renders what played, after the capture is closed, so the
    render's own meter readings are not in it); Live's device has already recorded it."""
    hub = PROBE["hub"]
    if body.get("state") == "start":
        if JOB["status"] == "running":
            raise RuntimeError("the app is busy: wait for the current job")
        d = work() / "bounces"
        d.mkdir(parents=True, exist_ok=True)
        MASTER["path"] = str(d / f"master-{time.strftime('%Y%m%d-%H%M%S')}.wav")
        if hub:
            hub.begin("master")
        return {"path": MASTER["path"]}
    path = bounce_file(body["path"]) if body.get("path") else MASTER["path"]     # a path from outside must be our own recording
    if not path:
        d = work() / "bounces"
        d.mkdir(parents=True, exist_ok=True)
        path = str(d / f"master-{time.strftime('%Y%m%d-%H%M%S')}.wav")
    cap = hub.end(work() / "captures", "master") if hub and hub.capture is not None else None
    if render:
        render(path)
    MASTER["path"] = ""
    sig = body.get("sig") or "song"
    name = safe(f"Pre-export {time.strftime('%Y-%m-%d %H%M')}")
    d = work() / "scan" / name
    pr = body.get("params") or {}
    steps = []
    if cap:
        steps.append(("Reading what the probes heard, and the recorded master", ["probe", "report", str(cap), "--out", str(d), "--mix", path], True))
    flags = []
    if isinstance(pr.get("target"), (int, float)):
        flags += ["--target", str(pr["target"])]
    if isinstance(pr.get("ceiling"), (int, float)):
        flags += ["--ceiling", str(pr["ceiling"])]
    if pr.get("mode") in ("clean", "punch", "loud"):
        flags += ["--limiter-mode", pr["mode"]]
    if isinstance(pr.get("amount"), (int, float)):
        flags += ["--amount", str(pr["amount"])]
    steps.append(("Release checks on the recorded master", ["qc", path] + (["--target", str(pr["target"])] if "--target" in flags else []), False))
    steps.append(("How it translates (mono, phone, earbuds, car, codecs)", ["translate", path], False))
    steps.append(("Mastering moves, as proposals", ["master", path, "--plan", str(d)] + flags, False))
    run_job("probe", "Review before export", steps, d)
    return {"job": JOB["id"], "dir": str(d)}


def reaper_record(ev, r):
    """REAPER's Record and review (Hypnomix Main's button, through the bridge): the same review as Live's device."""
    if ev.get("ev") == "start":
        return master_record({"state": "start"})
    card = PROBE["hub"].song_card() if PROBE["hub"] else {}
    start, end = float(ev["start"]), float(ev["end"])
    if end - start < 1.0:
        raise RuntimeError("less than a second was played")
    return master_record({"state": "stop", "sig": card.get("sig") or "song", "params": card.get("song") or {}},
                         render=lambda path: r.render_master(start, end, path))


def start_probe_hub():
    try:
        from hypnomix.app.probe import Hub
        h = Hub()
        h.on_record = reaper_record
        PROBE["hub"] = h.start()
        PROBE["error"] = ""
    except Exception as e:                    # the port is taken (another app, or `hypnomix probe listen`)
        PROBE["error"] = f"UDP port 8792 is in use ({e}); close the other program using it: it is tried again every few seconds"
    PROBE["tried"] = time.time()


def probe_hub():
    """The hub, starting it again (at most every 5 s) if the port was taken when the app started."""
    if PROBE["hub"] is None and time.time() - PROBE.get("tried", 0) > 5:
        start_probe_hub()
    return PROBE["hub"]


# ---------------------------------------------------------------- native file dialogs, and the file manager
def bounce_file(raw):
    """The recording named in a request: a .wav that is already in this app's own bounces folder, or ValueError."""
    root = (work() / "bounces").resolve()
    try:
        f = Path(str(raw)).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        raise ValueError("not a recording this app made: use the path the app gave when the recording started")
    if f.suffix.lower() != ".wav" or root not in f.parents or not f.is_file():
        raise ValueError("not a recording this app made: use the path the app gave when the recording started")
    return str(f)


class PickUnavailable(RuntimeError):
    """The file chooser could not be shown: the page tells the person to type or paste the path instead."""


PICK_KINDS = ("set", "song", "audio", "folder")
_TK = r"""
import sys
try:
    import tkinter
    from tkinter import filedialog
except Exception as e:
    sys.stderr.write("tkinter is not installed (%s)" % e)
    sys.exit(3)
kind = sys.argv[1]
try:
    root = tkinter.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    if kind == "folder":
        p = filedialog.askdirectory(title="Choose a folder of recordings or stems")
    elif kind == "audio":
        p = filedialog.askopenfilename(title="Choose an audio file", filetypes=[("Audio", "*.wav *.aif *.aiff *.flac *.mp3 *.m4a"), ("All files", "*.*")])
    elif kind == "set":
        p = filedialog.askopenfilename(title="Choose a Live set", filetypes=[("Live set", "*.als")])
    else:
        p = filedialog.askopenfilename(title="Choose a Live set, REAPER project or Ardour session",
                                       filetypes=[("Live set, REAPER project or Ardour session", "*.als *.rpp *.ardour"), ("All files", "*.*")])
except Exception as e:
    sys.stderr.write("no window could be opened (%s)" % e)
    sys.exit(4)
sys.stdout.write(p or "")
"""


def pick(kind):
    """The path the person chose in the system's own chooser, or "" if they cancelled. Raises PickUnavailable (with
    the words to show) when there is no chooser to show: nothing fails silently."""
    if kind not in PICK_KINDS:
        raise ValueError("kind must be one of: " + ", ".join(PICK_KINDS))
    if sys.platform == "darwin":
        script = {"set": 'POSIX path of (choose file with prompt "Choose a Live set" of type {"als"})',
                  "song": 'POSIX path of (choose file with prompt "Choose a Live set, REAPER project or Ardour session" of type {"als","rpp","ardour"})',
                  "audio": 'POSIX path of (choose file with prompt "Choose an audio file" of type {"wav","aif","aiff","flac","mp3","m4a"})',
                  "folder": 'POSIX path of (choose folder with prompt "Choose a folder of recordings or stems")'}[kind]
        try:
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        except OSError as e:
            raise PickUnavailable(f"the file chooser could not be opened ({e}): type or paste the path in the Path box instead")
        if r.returncode == 0:
            return r.stdout.strip()
        if "-128" in r.stderr:                       # the person pressed Cancel
            return ""
        raise PickUnavailable(f"macOS did not open its file chooser ({r.stderr.strip()[:160]}): type or paste the path in the Path box instead")
    try:                                             # Windows and Linux: the standard library's own chooser, in a process of its own
        r = subprocess.run([sys.executable, "-c", _TK, kind], capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise PickUnavailable(f"the file chooser could not be opened ({e}): type or paste the path in the Path box instead")
    if r.returncode != 0:
        raise PickUnavailable(f"the file chooser is not available here ({r.stderr.strip()[:160] or 'it did not start'}): "
                              "type or paste the path in the Path box instead")
    return r.stdout.strip()


def is_windows():
    return os.name == "nt"


def reveal(path):
    """Show a file or folder in the system's file manager. -> (shown, plain words)."""
    t = Path(str(path)).expanduser()
    if not t.exists():
        return False, f"that is not there any more: {t}"
    try:
        if sys.platform == "darwin":
            ok = subprocess.run(["open", "-R", str(t)], capture_output=True).returncode == 0
        elif is_windows():
            subprocess.Popen(["explorer", str(t)] if t.is_dir() else ["explorer", f"/select,{t}"])   # explorer's own exit code is not meaningful
            ok = True
        else:
            opener = shutil.which("xdg-open")
            if not opener:
                return False, f"there is no file manager to open here (xdg-open is not installed). It is in: {t if t.is_dir() else t.parent}"
            subprocess.Popen([opener, str(t if t.is_dir() else t.parent)])    # the folder, never the file itself (that would run it)
            ok = True
    except OSError as e:
        return False, f"the file manager could not be opened ({e}). It is in: {t if t.is_dir() else t.parent}"
    return ok, "" if ok else f"the file manager did not open. It is in: {t if t.is_dir() else t.parent}"


# ---------------------------------------------------------------- starting the commands the pages ask for
SCAN_OPTS = ("mix", "ref", "key", "like", "backing")


def set_aside_decisions(d):
    """A re-scan of a project that cannot carry decisions over (only a Live set can): the old answers are kept in a file
    of their own, because their ids would now mean different findings."""
    d = Path(d)
    cur = d / "decisions.json"
    if not cur.exists():
        return []
    n, dest = 1, d / "decisions before re-scan.json"
    while dest.exists():
        n += 1
        dest = d / f"decisions before re-scan {n}.json"
    cur.rename(dest)
    return [f"Your earlier decisions were kept as {dest.name}: this kind of project cannot carry them into a new scan, "
            "and the same id can mean a different finding now."]


def scan_steps(src, d, opts, reused):
    """The job steps for a scan of src into d. A re-scan of a Live set carries the decisions over by what each finding is
    (scan --since); other kinds of project start with fresh decisions and the old ones kept aside."""
    argv = ["scan", str(src), "--out", str(d)]
    since = (reused and src.is_file() and src.suffix.lower() == ".als" and (d / "findings.json").exists()
             and inspect_scan(d)["damage"] is None)            # a damaged results or decisions file cannot be carried over
    if since:
        argv += ["--since", str(d)]
    for k in SCAN_OPTS:
        if opts.get(k):
            argv += [f"--{k}", str(opts[k])]
    if opts.get("deep"):
        argv.append("--deep")
    steps = []

    def remember():
        d.mkdir(parents=True, exist_ok=True)
        JOB["prior"] = prior_times(d)                   # what the last scan of this folder took: the estimate for this one
        old_times = (read_json(d / "app-scan.json", {}) or {}).get("times")
        kept = dict({k: opts.get(k) for k in SCAN_OPTS + ("deep", "devices")}, source=str(src))
        if old_times:
            kept["times"] = old_times
        write_json_atomic(d / "app-scan.json", kept)
        if reused and not since:
            for line in set_aside_decisions(d):
                JOB["log"].append(line)
    steps.append(("Getting ready", remember, True))
    steps.append(("Scanning (changes nothing)" if not since else "Scanning again, keeping your decisions (changes nothing)", argv, True))
    steps.append(("Keeping the times", lambda: save_times(d), False))
    steps.append(("Building before / after clips", ["ab", str(d)], False))
    steps.append(("Keeping the times of the clips", lambda: save_times(d), False))
    if opts.get("devices") and src.suffix.lower() == ".als":
        steps.append(("A copy of the set with the hypnomix devices on every track", ["probe", "insert", str(src)], False))
    return steps


def start_scan(body, title="First pass", folder=None):
    """Scan a Live set, REAPER project, Ardour session or folder. The same path always goes back to its own scan folder
    (that is a re-scan); a different path never shares one, even with the same name."""
    src = Path(need(body, "source")).expanduser()
    if not src.exists():
        raise ValueError(f"not found: {src}")
    src = src.resolve()
    if src.is_file() and src.suffix.lower() not in SET_KINDS:
        raise ValueError(f"{src.name} is not a Live set (.als), a REAPER project (.rpp) or an Ardour session (.ardour): "
                         "choose one of those, or a folder of recordings")
    for k in SCAN_OPTS:
        if body.get(k) is not None and not isinstance(body[k], str):
            raise ValueError(f"{k} must be text")
    if JOB["status"] == "running":
        raise RuntimeError("something is already running: wait for it to finish")
    d, reused = (Path(folder), True) if folder else scan_slot(src)         # Re-scan on a song's card goes into that song's own folder
    jid = run_job("scan", f"{title}: {src.name}", scan_steps(src, d, body, reused), d)
    return {"job": jid, "dir": str(d), "reused": reused, "carries_decisions": bool(reused and src.suffix.lower() == ".als")}


def rescan_body(d):
    """The options a scan folder was made with, from what the app kept and what the scan recorded."""
    meta = read_json(Path(d) / "scan.json", {}) or {}
    kept = read_json(Path(d) / "app-scan.json", {}) or {}
    src = kept.get("source") or meta.get("set") or (read_json(Path(d) / "findings.json", {}) or {}).get("set") or ""
    if not src:
        raise ValueError("this scan does not say which song it was made from, so it cannot be repeated: choose the song again on the Songs tab")
    body = {k: (kept.get(k) or meta.get(k)) for k in SCAN_OPTS}
    body.update(source=src, deep=bool(kept.get("deep")), devices=bool(kept.get("devices")))
    return body


def own_scan_dir(raw):
    """A folder inside the app's own scan folder (it may be damaged or unfinished: that is when a re-scan is wanted)."""
    d = Path(raw).resolve()
    if (work() / "scan").resolve() not in d.parents or not d.is_dir():
        raise ValueError("not one of this app's scans")
    return d


def start_fix(body):
    d = scan_dir(need(body, "dir"))
    decisions_ok(d)
    p = review_payload(d)
    plan = apply_plan(p["findings"], p["decisions"])
    if plan["blocked"]:
        raise RuntimeError("Tuning is not written into an Ardour session yet, so fix would stop: turn off " + ", ".join(f["id"] for f in plan["blocked"])
                           + " first (the other fixes can go ahead).")
    if not plan["auto"]:
        by_hand = len(plan["manual"])
        raise RuntimeError("Nothing here can be applied automatically" + (
            f": the {by_hand} approved item(s) are by hand. Make the handoff list instead (a checklist and a marker at each spot)."
            if by_hand else ": nothing is approved yet, and nothing is on by default."))
    for k in ("key", "out"):
        if body.get(k) is not None and not isinstance(body[k], str):
            raise ValueError(f"{k} must be text")
    kind, src = p["kind"], Path(p["source"])
    argv = ["fix", str(d), "--approved"]
    out = ""
    if kind != "folder":
        name = clean_out(body.get("out") or p["suggested_out"], kind, src)
        target = src.parent / name
        if any(writes_set(f) for f in plan["auto"]) and (target.exists() or target == src):
            raise RuntimeError(f"{name} already exists next to the original: choose a new name (nothing is ever overwritten)")
        out = str(target)
        argv += ["--out", out]
    if body.get("key"):
        argv += ["--key", body["key"]]
    for flag in ("allow_protected", "stale_ok"):
        if body.get(flag):
            argv.append("--" + flag.replace("_", "-"))
    watch = ([src.parent] if kind != "folder" else []) + [d / "fixed"]
    jid = run_job("fix", f"Applying approved fixes: {d.name}", [("Applying only what you approved", argv, True)], d, watch)
    JOB["out"] = out
    JOB["expect"] = len({f.get("tool") for f in plan["auto"]})        # the tools that will each print a line when they finish
    return {"job": jid, "out": out}


def demo_available():
    from hypnomix import cli
    return "demo" in cli.COMMANDS


def start_demo():
    """A short demo song with planted problems, made in the app's own folder, then scanned."""
    if not demo_available():
        raise ValueError("this version of hypnomix has no demo song")
    if JOB["status"] == "running":
        raise RuntimeError("something is already running: wait for it to finish")
    root = work() / "demo"
    out, n = root, 1
    while out.exists():
        n += 1
        out = work() / f"demo {n}"

    def after():
        names = [m[1] for line in reversed(JOB["log"]) for m in [re.search(r"(\S.*\.(?:als|rpp|ardour))\s*$", line.strip())] if m]
        found = next((Path(x) for x in names if Path(x).exists()), None)
        if found is None:
            found = next(iter(sorted(out.glob("*.als")) + sorted(out.glob("*.rpp"))), None)
        if found is None:
            raise RuntimeError("the demo did not leave a song I can scan")
        found = found.resolve()
        d, reused = scan_slot(found)
        JOB["dir"] = str(d)
        JOB["title"] = f"First pass: {found.name} (demo)"
        return scan_steps(found, d, {}, reused)
    jid = run_job("scan", "Try it on a demo song", [("Making a short demo song with planted problems", ["demo", "--out", str(out)], True),
                                                    ("Choosing the song to scan", after, True)], out)
    return {"job": jid}


def start_handoff(body):
    d = scan_dir(need(body, "dir"))
    decisions_ok(d)
    ins = inspect_scan(d)
    src = Path((ins["data"] or {}).get("set") or "")
    kind = source_kind(src, (read_json(d / "scan.json", {}) or {}).get("mode", ""))
    watch = [d / "handoff"] + ([src.parent] if kind != "folder" and src.name else [])
    jid = run_job("handoff", f"Handoff list: {d.name}",
                  [("Making the handoff list (your project is not changed)", ["handoff", str(d)], True)], d, watch)
    return {"job": jid}


def start_undo(body):
    d = scan_dir(need(body, "dir"))
    n = whole(body.get("n"), "n", 1, 100000)
    ins = inspect_scan(d)
    src = (ins["data"] or {}).get("set", "")
    kind = source_kind(src, (read_json(d / "scan.json", {}) or {}).get("mode", ""))
    h = read_json(d / "history" / "history.json", {"versions": []}) or {"versions": []}
    row = next((r for r in hist_entries(d, h, kind, src) if r["n"] == n), None)
    if row is None:
        raise ValueError(f"there is no version {n} in this song's history")
    if not row["can_undo"]:
        raise RuntimeError(row["why_not"] or "that version cannot be undone")
    jid = run_job("undo", f"Undo version {n}: {d.name}", [(f"Writing {row['undo_name']}: a new set equal to what version {n} started from",
                                                          ["history", str(d), "--undo", str(n)], True)], d, [Path(src).parent])
    return {"job": jid, "writes": row["undo_name"]}


# ---------------------------------------------------------------- http
def security_headers(nonce=None):
    """On every response: the page cannot be framed, nothing it loads can run unless it is ours, nothing is sniffed."""
    site = "https://hypnomix.bradfieldenterprises.org"
    csp = "; ".join([
        "default-src 'self'", "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'", "form-action 'self'",
        "connect-src 'self'", f"img-src 'self' data: {site}", f"media-src 'self' blob: {site}",
        "style-src 'self' 'unsafe-inline'", "script-src 'self'" + (f" 'nonce-{nonce}'" if nonce else ""),
        "script-src-attr 'none'"])             # no inline handlers (onclick=...) anywhere in the app: listeners only
    return {"X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Cross-Origin-Resource-Policy": "same-origin", "Content-Security-Policy": csp}


def make_handler(port):
    from hypnomix.app.ui import PAGE
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        timeout = IDLE_SECONDS
        _timer = _nonce = None

        def handle_one_request(self):
            """Wait up to IDLE_SECONDS for a request to begin; once it has, READ_SECONDS to receive all of it (a client
            that sends one byte a minute holds nothing for long). The clock stops when the request has been read, so a
            slow answer (a file dialog, a job starting) is never cut."""
            try:
                if not self.rfile.peek(1):                      # the client hung up, or sent nothing for IDLE_SECONDS
                    self.close_connection = True
                    return
                self._timer = threading.Timer(READ_SECONDS, self._give_up)
                self._timer.daemon = True
                self._timer.start()
                super().handle_one_request()
            except (OSError, ValueError):                       # a reset, or the clock ran out mid-request
                self.close_connection = True
            finally:
                self._disarm()

        def _give_up(self):
            try:
                self.connection.shutdown(socket.SHUT_RDWR)      # whatever is blocked reading the request wakes up and ends
            except OSError:
                pass

        def _disarm(self):
            t, self._timer = self._timer, None
            if t:
                t.cancel()

        def end_headers(self):
            for k, v in security_headers(self._nonce).items():     # on everything: pages, data, refusals and the library's own error pages
                self.send_header(k, v)
            self._nonce = None
            super().end_headers()

        def send(self, code, body, ctype="application/json", extra=None, nonce=None, close=False):
            if not isinstance(body, (bytes, bytearray)):
                body = json.dumps(body, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._nonce = nonce
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            if close:                         # an early refusal: the request body was not read, so end the connection
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            self.wfile.write(body)

        def local(self, page=False):
            """Is this a request from this computer's own browser tab, or a client that sends no browser headers?
            A browser says where a request came from (Sec-Fetch-Site): from another website it may only open the page."""
            host = (self.headers.get("Host") or "").split(":")[0]
            o = self.headers.get("Origin")
            if host not in ("127.0.0.1", "localhost") or not (o is None or o in origins):
                return False
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                return bool(page) and self.headers.get("Sec-Fetch-Mode") == "navigate" \
                    and self.headers.get("Sec-Fetch-Dest") in (None, "document")
            return True

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            self._disarm()                                       # a GET has no body: the request has arrived
            if not self.local(page=u.path == "/"):
                return self.send(403, {"error": "this computer only"}, close=True)
            try:
                if u.path == "/":
                    nonce = secrets.token_urlsafe(16)               # the page's one inline script carries this; nothing else may run
                    html = PAGE.replace("__TOKEN__", TOKEN).replace("<script>", f'<script nonce="{nonce}">')
                    return self.send(200, html.encode(), "text/html; charset=utf-8", nonce=nonce)
                if u.path == "/api/state":
                    from hypnomix.workflow import prefs as P
                    pr = P.load()
                    return self.send(200, dict(
                        scans=scans(), prefs=P.summary(pr), unanswered=len(P.unanswered(pr)), home=str(work()),
                        job={k: JOB[k] for k in ("id", "status", "title", "kind", "dir", "step", "stopped")},
                        live=time.time() - LIVE["seen"] < 3.0, mac=sys.platform == "darwin", platform=sys.platform,
                        demo=demo_available(), commands_rev=commands_rev()))
                if u.path == "/api/commands":            # sent once: /api/state says (commands_rev) when it changes
                    return self.send(200, dict(rev=commands_rev(), commands=command_list()))
                if u.path == "/api/job":
                    since = whole(q.get("since", 0), "since", 0)
                    extra = {}
                    if JOB["kind"] == "handoff" and JOB["status"] == "done" and JOB["dir"]:
                        t = Path(JOB["dir"]) / "handoff" / "HANDOFF.md"
                        extra["text"] = t.read_text(errors="replace")[:30000] if t.is_file() else ""
                    return self.send(200, dict(id=JOB["id"], status=JOB["status"], title=JOB["title"], kind=JOB["kind"],
                                               dir=JOB["dir"], step=JOB["step"], total=len(JOB["log"]), log=JOB["log"][since:],
                                               stopped=JOB["stopped"], files=[dict(name=Path(f).name, path=f, folder=str(Path(f).parent)) for f in JOB["files"]],
                                               reason=JOB["reason"], out=JOB["out"], progress=job_progress(), **extra))
                if u.path == "/api/review":
                    d = scan_dir(need(q, "dir"))
                    if LIVE["dir"] != str(d):
                        LIVE.update(dir=str(d), cursor=-1)
                    return self.send(200, review_payload(d))
                if u.path == "/api/fix/result":
                    return self.send(200, fix_result(scan_dir(need(q, "dir"))))
                if u.path == "/api/history":            # every apply of this song, fed by `hypnomix history DIR --json`
                    d = scan_dir(need(q, "dir"))
                    ins = inspect_scan(d)
                    src = (ins["data"] or {}).get("set", "")
                    kind = source_kind(src, (read_json(d / "scan.json", {}) or {}).get("mode", ""))
                    note = ""
                    try:
                        r = subprocess.run([sys.executable, "-m", "hypnomix.cli", "history", str(d), "--json"], cwd=str(work()),
                                           capture_output=True, text=True, timeout=60, env=cli_env())
                        h = json.loads(r.stdout)
                    except (OSError, ValueError, subprocess.TimeoutExpired):
                        h = read_json(d / "history" / "history.json", {"versions": []}) or {"versions": []}
                        note = "The history command did not answer, so this is read straight from the saved history file."
                    return self.send(200, dict(entries=hist_entries(d, h, kind, src), kind=kind, note=note))
                if u.path == "/api/prefs":
                    from hypnomix.workflow import prefs as P
                    pr = P.load()
                    return self.send(200, [dict(q_, value=P.get(pr, q_["key"])) for q_ in P.QUESTIONS])
                if u.path == "/api/help":
                    from hypnomix import cli
                    if q.get("cmd") not in cli.COMMANDS or q["cmd"] in HIDDEN:
                        return self.send(404, {"error": "unknown command"})
                    return self.send(200, {"help": command_help(q["cmd"])})
                if u.path.startswith("/api/master/chain"):  # HypnomixMain's mastering chain templates
                    from hypnomix.app import masterchain as MC
                    r = MC.handle_get(u.path, q)
                    if r:
                        return self.send(*r)
                if u.path.startswith("/api/align/"):       # the Align device (hypnomix aligndevice)
                    from hypnomix.app import align as AL
                    r = AL.handle_get(u.path, q)
                    if r:
                        return self.send(*r)
                if u.path in ("/wiki.js", "/api/wiki", "/api/wiki/article") or u.path.startswith("/wiki/assets/"):
                    from hypnomix.app import wiki as WK             # the Wiki tab: the site's articles, offline
                    r = WK.handle_get(u.path, q, self.headers)
                    if r:
                        return self.send(*r)
                if u.path in ("/diskcare.js", "/api/diskcare/state"):   # disk care: old renders and caches cleared
                    from hypnomix.app import diskcare as DC
                    r = DC.handle_get(u.path, q)
                    if r:
                        return self.send(*r)
                if u.path in ("/update.js", "/api/update/state"):  # updates: a new version is out, one-click install
                    from hypnomix.app import update as UP
                    r = UP.handle_get(u.path, q)
                    if r:
                        return self.send(*r)
                if u.path in ("/setup.js", "/api/setup/state", "/api/setup/extras"):    # the guided setup (first run, the Setup button)
                    from hypnomix.app import setup as SU
                    r = SU.handle_get(u.path, q)
                    if r:
                        return self.send(*r)
                if u.path == "/teacher.js" or u.path.startswith("/api/teach/"):   # the Teacher tab (teacher mode)
                    from hypnomix.app import teacher as TE
                    r = TE.handle_get(u.path, q)
                    if r:
                        return self.send(*r)
                if u.path == "/review.js":                # the review screen's own script (keyboard, one player per card, batches)
                    return self.send(200, Path(__file__).with_name("review.js").read_bytes(), "text/javascript; charset=utf-8")
                if u.path.startswith("/api/chat/") or u.path == "/chat.js":   # the Assistant tab
                    from hypnomix.app import chat as CH
                    r = CH.handle_get(u.path, q)
                    if r:
                        return self.send(*r)
                if u.path == "/api/live/poll":            # the Max for Live device asks a few times a second
                    LIVE["seen"] = time.time()
                    since = whole(q.get("since", -1), "since", -1)
                    cmd = LIVE["cmd"] if LIVE["seq"] > since >= 0 else None
                    return self.send(200, dict(seq=LIVE["seq"], cmd=cmd, current=live_current()))
                if u.path == "/api/probe/status":
                    hub = probe_hub()
                    return self.send(200, dict(tracks=hub.status() if hub else [], error=PROBE["error"],
                                               recording=bool(hub and hub.capture is not None)))
                if u.path == "/api/probe/cmd":            # each probe asks twice a second: its gain (A/B loudness match)
                    g, diff = ab_gain() if q.get("main") == "1" else (0.0, None)
                    return self.send(200, dict(gain_db=round(g, 2), ab_diff=diff))
                if u.path == "/api/probe/card":
                    f = cards_file()
                    return self.send(200, (json.loads(f.read_text()) if f.exists() else {}).get(q.get("sig", ""), {}))
                if u.path == "/api/probe/song":            # what the devices say right now (song card + track roles)
                    return self.send(200, PROBE["hub"].song_card() if PROBE["hub"] else {})
                if u.path == "/audio":
                    d = scan_dir(need(q, "dir"))
                    f = d / "ab" / Path(unquote(need(q, "f"))).name
                    if not (f.is_file() and f.suffix == ".wav"):
                        return self.send(404, {"error": "no such clip"})
                    data = f.read_bytes()
                    rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
                    if rng:                                # browsers ask for parts of an audio file
                        a = int(rng[1]) if rng[1] else 0
                        b = min(int(rng[2]) if rng[2] else len(data) - 1, len(data) - 1)
                        return self.send(206, data[a:b + 1], "audio/wav",
                                         {"Content-Range": f"bytes {a}-{b}/{len(data)}", "Accept-Ranges": "bytes"})
                    return self.send(200, data, "audio/wav", {"Accept-Ranges": "bytes"})
                self.send(404, {"error": "not found"})
            except RuntimeError as e:
                self.send(409, {"error": str(e)})
            except KeyError as e:                         # a field the request did not carry: say so, not the Python word for it
                self.send(400, {"error": f"this request is missing {e.args[0] if e.args else 'something it needs'}"})
            except ValueError as e:
                self.send(400, {"error": str(e)})
            except (TypeError, AttributeError):           # a field of the wrong kind (a list where text belongs): a sentence, not a dropped connection
                self.send(400, {"error": WRONG_KIND})

        def do_POST(self):
            u = urlparse(self.path)
            if not self.local():
                return self.send(403, {"error": "this computer only"}, close=True)
            cl = self.headers.get("Content-Length")
            cl = "0" if cl is None else cl.strip()                 # no header: no body; a blank one is not a number
            if self.headers.get("Transfer-Encoding"):
                return self.send(400, {"error": "bad request: send the body with a Content-Length (chunked bodies are not taken)"}, close=True)
            if cl.startswith("-") and cl[1:].isascii() and cl[1:].isdigit():
                return self.send(400, {"error": "bad request: Content-Length is negative"}, close=True)
            if not (cl.isascii() and cl.isdigit()):
                return self.send(400, {"error": "bad request: Content-Length is not a number"}, close=True)
            n = int(cl) if len(cl) < 19 else MAX_BODY + 1
            if n > MAX_BODY:
                return self.send(413, {"error": f"that request is too large (the limit is {MAX_BODY // 1000} KB)"}, close=True)
            raw = self.rfile.read(n) if n else b""
            self._disarm()                                       # the whole request has arrived (or the clock ended it: below)
            if len(raw) < n:
                return self.send(400, {"error": "bad request: the body ended early"}, close=True)
            try:
                body = json.loads(raw or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("not an object")
            except ValueError:
                return self.send(400, {"error": "bad request"})
            try:
                # the device (inside Live) may step through findings and record decisions; nothing is applied by these
                if u.path == "/api/live/step":
                    live_step(whole(body.get("delta", 1), "delta", -1000, 1000), bool(body.get("undecided")))
                    return self.send(200, live_current())
                if u.path == "/api/live/decide":
                    cur = live_current()
                    if cur.get("id"):
                        decisions_ok(scan_dir(LIVE["dir"]))
                        record_one(scan_dir(LIVE["dir"]), cur["id"], need(body, "decision"), "from the Live device")
                    return self.send(200, live_current())
                if u.path.startswith("/api/master/chain"):
                    from hypnomix.app import masterchain as MC
                    r = MC.handle_post(u.path, body)
                    if r:
                        return self.send(*r)
                if u.path.startswith("/api/align/"):       # the Align device: always writes a NEW set, never overwrites
                    from hypnomix.app import align as AL
                    if u.path == "/api/align/run":
                        parts = body.get("parts")
                        if not isinstance(body.get("guide"), str) or not isinstance(parts, list) or not all(isinstance(x, str) for x in parts):
                            raise ValueError("guide is a track name and parts is a list of track names")
                    r = AL.handle_post(u.path, body)
                    if r:
                        return self.send(*r)
                if u.path == "/api/ab/state":            # the device switched A / B (or loudness matching)
                    ab_set_state(need(body, "id"), str(body.get("state", "A")), body.get("match"))
                    g, diff = ab_gain()
                    return self.send(200, dict(state=AB["state"], match=AB["match"], diff=diff))
                if u.path == "/api/ab/blind":
                    need(body, "id", "chose")
                    return self.send(200, blind_record(scan_dir(LIVE["dir"]), body))
                if u.path == "/api/probe/card":
                    return self.send(200, card_save(need(body, "sig"), body.get("chords"), body.get("params")))
                if u.path == "/api/master/record":
                    return self.send(200, master_record(body))
                if u.path == "/api/probe/start":
                    if not probe_hub():
                        return self.send(409, {"error": "the probe receiver is not running: " + PROBE["error"]})
                    PROBE["hub"].begin(body.get("label", ""))
                    return self.send(200, {"recording": True})
                if u.path == "/api/probe/stop":
                    hub = PROBE["hub"]
                    if not hub:
                        return self.send(409, {"error": "the probe receiver is not running, so nothing is being recorded: "
                                                        + (PROBE["error"] or "start the app's receiver first")})
                    if hub.capture is None:
                        return self.send(409, {"error": "nothing is being recorded: press Record first"})
                    f = hub.end(work() / "captures", str(body.get("song", "")))
                    return self.send(200, {"capture": str(f)})
                if self.headers.get("X-Hypnomix") != TOKEN:
                    return self.send(403, {"error": "open the app's own page to do this"})
                if u.path.startswith("/api/wiki/"):        # the Wiki tab: edit, publish, live copy on or off
                    from hypnomix.app import wiki as WK
                    r = WK.handle_post(u.path, body)
                    if r:
                        return self.send(*r)
                if u.path.startswith("/api/diskcare/"):    # disk care: preview, clean now, settings, restore
                    from hypnomix.app import diskcare as DC
                    r = DC.handle_post(u.path, body, lambda: JOB["status"] == "running")
                    if r:
                        return self.send(*r)
                if u.path.startswith("/api/update/"):      # check now, download (checksum-verified), install
                    from hypnomix.app import update as UP
                    r = UP.handle_post(u.path, body)
                    if r:
                        return self.send(*r)
                if u.path.startswith("/api/teach/"):       # the Teacher tab: progress, and hands-on steps (with an OK)
                    from hypnomix.app import teacher as TE
                    r = TE.handle_post(u.path, body)
                    if r:
                        return self.send(*r)
                if u.path.startswith("/api/setup/"):       # the guided setup: save a key and test it, Live, the command
                    from hypnomix.app import setup as SU
                    r = SU.handle_post(u.path, body)
                    if r:
                        return self.send(*r)
                if u.path.startswith("/api/chat/"):        # the Assistant tab (needs the page's token, like the rest)
                    from hypnomix.app import chat as CH
                    r = CH.handle_post(u.path, body)
                    if r:
                        return self.send(*r)
                if u.path == "/api/pick":
                    return self.send(200, {"path": pick(need(body, "kind"))})
                if u.path == "/api/decide":
                    # one finding: {id, decision, note?, amount?}; several in ONE request and ONE write: {ids: [...], decision, note?, amount?}
                    d = scan_dir(need(body, "dir"))
                    dec_ = need(body, "decision")
                    amt = body.get("amount")
                    decisions_ok(d)
                    if "ids" in body:
                        out = record_many(d, body["ids"], dec_, str(body.get("note") or ""), amount=amt, by=body.get("by") or None,
                                          via=str(body["via"])[:40] if body.get("via") else None)
                        return self.send(200, {"ids": list(out), "entries": out})
                    fid = need(body, "id")
                    e = record_one(d, fid, dec_, str(body.get("note") or ""), amount=None if amt is None else whole(amt, "amount", 0, 100),
                                   by=body.get("by") or None)
                    return self.send(200, {"entry": e})
                if u.path == "/api/decide-like":
                    # dry_run: list what it WOULD record (with a preview / played flag for each) and record nothing
                    d = scan_dir(need(body, "dir"))
                    fid, dec_ = need(body, "id", "decision")
                    decisions_ok(d)
                    if body.get("dry_run"):
                        return self.send(200, like_rows(d, fid))
                    from hypnomix.workflow import review as R
                    with DEC_LOCK:
                        ids = R.record_like(d, fid, dec_, amount=body.get("amount"), by=body.get("by") or None)
                        patch_heard(d, ids)
                    ins = inspect_scan(d)["dec"]
                    return self.send(200, {"ids": ids, "entries": {i: ins[i] for i in ids if i in ins}})
                if u.path == "/api/decide-low":
                    # "Approve all low": dry_run lists what it would approve (never a taste call, a tidy step, a protected or by-hand item)
                    d = scan_dir(need(body, "dir"))
                    decisions_ok(d)
                    return self.send(200, decide_low(d, body.get("ids"), dry_run=bool(body.get("dry_run", not body.get("ids"))),
                                                     by=body.get("by") or None))
                if u.path == "/api/heard":
                    d = scan_dir(need(body, "dir"))
                    return self.send(200, mark_heard(d, need(body, "id"), body.get("which", "")))
                if u.path == "/api/note":
                    from hypnomix.workflow import oversight as O
                    d = scan_dir(need(body, "dir"))
                    fid, text = need(body, "id", "text")
                    decisions_ok(d)
                    O.add_note(d, fid, text, body.get("at") or None, body.get("by") or None)
                    return self.send(200, {})
                if u.path == "/api/restore-decisions":      # a damaged decisions file: the backup back, or a new empty one (the damaged one is kept)
                    d = scan_dir(need(body, "dir"))
                    dmg = inspect_scan(d)["damage"]
                    if not dmg or dmg["file"] != "decisions.json":
                        raise ValueError("this song's decisions file is not damaged")
                    return self.send(200, restore_decisions(d, fresh=bool(body.get("fresh"))))
                if u.path == "/api/prefs":
                    from hypnomix.workflow import prefs as P
                    pr = P.load()
                    keys = {q_["key"] for q_ in P.QUESTIONS}
                    for k, v in body.items():
                        if k in keys:
                            P.put(pr, k, P.parse(k, str(v)))
                    P.save(pr)
                    return self.send(200, {"saved": True})
                if u.path == "/api/scan":
                    return self.send(200, start_scan(body))
                if u.path == "/api/rescan":              # the same song again; a Live set keeps its decisions (scan --since)
                    d = own_scan_dir(need(body, "dir"))
                    return self.send(200, start_scan(rescan_body(d), "Re-scan", folder=d))
                if u.path == "/api/fix":
                    return self.send(200, start_fix(body))
                if u.path == "/api/handoff":
                    return self.send(200, start_handoff(body))
                if u.path == "/api/undo":
                    return self.send(200, start_undo(body))
                if u.path == "/api/demo":
                    return self.send(200, start_demo())
                if u.path == "/api/ab/build":
                    d = scan_dir(need(body, "dir"))
                    argv = ["abset", str(d)] + (["--key", str(body["key"])] if body.get("key") else [])
                    run_job("abset", f"A/B set for Live: {d.name}", [("Building every fix as a switch (changes nothing)", argv, True)], d)
                    return self.send(200, {"job": JOB["id"]})
                if u.path == "/api/probe/report":
                    cap = Path(need(body, "capture"))
                    d = work() / "scan" / safe((str(body.get("name") or "") or cap.stem) + " (live)")
                    argv = ["probe", "report", str(cap), "--out", str(d)] + (["--set", body["set"]] if body.get("set") else [])
                    run_job("probe", f"Live check: {d.name}", [("Reading what the probes heard", argv, True)], d)
                    return self.send(200, {"job": JOB["id"], "dir": str(d)})
                if u.path == "/api/tool":
                    from hypnomix import cli
                    if not isinstance(body.get("cmd"), str) or body["cmd"] not in cli.COMMANDS or body["cmd"] in HIDDEN:
                        return self.send(400, {"error": "unknown command"})
                    try:
                        argv = [body["cmd"]] + shlex.split(str(body.get("args", "")))
                    except ValueError:
                        return self.send(400, {"error": "the options have a quote that is never closed"})
                    run_job("tool", f"hypnomix {body['cmd']}", [(body["cmd"], argv, True)])
                    return self.send(200, {"job": JOB["id"]})
                if u.path == "/api/stop":
                    return self.send(200, {"stopped": stop_job()})       # the command and everything it started
                if u.path == "/api/reveal":
                    ok, why = reveal(need(body, "path"))
                    return self.send(200, {"shown": ok, "message": why})
                if u.path == "/api/live/jump":
                    d = scan_dir(need(body, "dir"))
                    f = next((x for x in review_payload(d, light=True)["findings"] if x["id"] == need(body, "id")), None)
                    if not f or not f.get("jump"):
                        return self.send(400, {"error": "this finding has no place in the set to jump to"})
                    act, _ = actionable(d)
                    LIVE.update(dir=str(d), cursor=next((i for i, x in enumerate(act) if x["id"] == f["id"]), LIVE["cursor"]))
                    live_send(dict(type="jump", **f["jump"]))
                    return self.send(200, {"sent": True, "device": time.time() - LIVE["seen"] < 3.0})
                self.send(404, {"error": "not found"})
            except RuntimeError as e:
                self.send(409, {"error": str(e)})
            except KeyError as e:
                self.send(400, {"error": f"this request is missing {e.args[0] if e.args else 'something it needs'}"})
            except ValueError as e:
                self.send(400, {"error": str(e)})

            except (TypeError, AttributeError):
                self.send(400, {"error": WRONG_KIND})

    return H


def main():
    ap = argparse.ArgumentParser(prog="hypnomix app", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--no-open", action="store_true", help="do not open the browser")
    ap.add_argument("--home", help="where scans are kept (default ~/Documents/Hypnomix)")
    a = ap.parse_args()
    if a.home:
        os.environ["HYPNOMIX_APP_HOME"] = a.home
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(a.port))
    except OSError:
        sys.exit(f"port {a.port} is in use: is the hypnomix app already running? (http://127.0.0.1:{a.port})")
    start_probe_hub()
    from hypnomix.app import update as UP
    UP.check_in_background()                  # at most once a day, and only if it's switched on
    from hypnomix.app import diskcare as DC
    DC.start_in_background(lambda: JOB["status"] == "running")   # hourly look; cleans weekly or when the disk is nearly full
    url = f"http://127.0.0.1:{a.port}/"
    print(f"hypnomix app: {url}   (this computer only; Ctrl-C to stop)\nsongs are kept in {work()}", flush=True)
    if not a.no_open:
        import webbrowser
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
