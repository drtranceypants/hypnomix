"""The hypnomix wiki: one set of articles for the app's Wiki tab and the website's /wiki/ page.

Source: one file per article in hypnomix/app/wiki/articles/ ("NN-id.html": NN sets the order), an HTML
fragment under a short header, and the images and videos it shows in hypnomix/app/wiki/assets/:

    <!--
    title: The first pass
    sub: scan · hear · decide · apply
    teaser: (optional) the short summary the home page shows; else the first paragraph
    no: lesson 3
    group: Training
    -->
    <p>...</p>

Edit a file (or press Edit in the app's Wiki tab), then Publish (or commit and push). A job on the website's
computer builds the site's /wiki/ page from the pushed files (`python -m hypnomix.app.wiki_build`) and deploys
it; every copy of the app then shows the newer articles from the site (it asks the site at most every
10 minutes while the Wiki is open, and keeps the last copy for when it is offline). Turn that off in the tab.
"""
import json
import mimetypes
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from hypnomix.core.paths import HOME

HERE = Path(__file__).with_name("wiki")
SITE = "https://hypnomix.bradfieldenterprises.org"
LIVE_URL = SITE + "/wiki/articles.json"
CHECK_EVERY = 600
_CACHE, _LIVE = {}, {"checked": 0, "busy": False, "error": None}
_LOCK = threading.Lock()


def _home():
    return HOME


def settings():
    f = _home() / "wiki.json"
    try:
        return {"live": True, **json.loads(f.read_text())}
    except (OSError, ValueError):
        return {"live": True}


def save_settings(**kw):
    s = {**settings(), **kw}
    _home().mkdir(parents=True, exist_ok=True)
    (_home() / "wiki.json").write_text(json.dumps(s, indent=1))
    return s


# ---------------------------------------------------------------- the source files
HEAD = re.compile(r"\A\s*<!--(.*?)-->\s*", re.S)


def parse(path):
    """One article file -> dict (id, group, title, sub, no, html, text, file)."""
    raw = Path(path).read_text()
    meta, body = {}, raw
    m = HEAD.match(raw)
    if m:
        body = raw[m.end():]
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip()
    aid = re.sub(r"^\d+-", "", Path(path).stem)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return {"id": aid, "group": meta.get("group", "Wiki"), "title": meta.get("title", aid), "sub": meta.get("sub", ""),
            "no": meta.get("no", ""), "teaser": meta.get("teaser", ""), "html": body.strip(), "text": text, "url": f"{SITE}/wiki/#{aid}",
            "file": str(Path(path).resolve())}


def local(root=None):
    root = Path(root) if root else HERE
    files = sorted((root / "articles").glob("*.html"))
    key = (str(root), tuple((f.name, f.stat().st_mtime) for f in files))
    if _CACHE.get("key") != key:
        _CACHE.update(key=key, arts=[parse(f) for f in files])
    return _CACHE["arts"]


def git(*args, cwd=None):
    try:
        r = subprocess.run(["git", *args], cwd=cwd or HERE, capture_output=True, text=True, timeout=20)
        return r.returncode, (r.stdout + r.stderr).rstrip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def checkout():
    """-> (repo root, commit time of the wiki, unpublished changes) when running from a git checkout."""
    code, top = git("rev-parse", "--show-toplevel")
    top = top.strip()
    if code:
        return None, 0, []
    _, t = git("log", "-1", "--format=%ct", "--", str(HERE))
    t = t.strip()
    _, st = git("status", "--porcelain", "--", str(HERE))
    return Path(top), int(t) if t.isdigit() else 0, [ln[3:].split(" -> ")[-1] for ln in st.splitlines() if ln.strip()]


# ---------------------------------------------------------------- the live copy on the website
def _live_file():
    return _home() / "wiki-live" / "articles.json"


def live():
    try:
        return json.loads(_live_file().read_text())
    except (OSError, ValueError):
        return None


def refresh_live(force=False):
    """Ask the website for its articles in the background (at most every CHECK_EVERY seconds)."""
    with _LOCK:
        if _LIVE["busy"] or (not force and time.time() - _LIVE["checked"] < CHECK_EVERY) or not settings()["live"]:
            return
        _LIVE["busy"] = True

    def go():
        try:
            req = urllib.request.Request(LIVE_URL, headers={"User-Agent": "hypnomix-app"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode("utf-8"))
            if not isinstance(data.get("articles"), list):
                raise ValueError("no articles in the site's wiki")
            _live_file().parent.mkdir(parents=True, exist_ok=True)
            _live_file().write_text(json.dumps(data))
            _LIVE["error"] = None
        except Exception as e:             # offline, or the site is down: keep what we have
            _LIVE["error"] = f"{type(e).__name__}: {e}"[:200]
        finally:
            _LIVE.update(checked=time.time(), busy=False)

    threading.Thread(target=go, daemon=True).start()


def current():
    """-> (articles, about): the newest of this computer's files and the website's copy. Unpublished
    edits on this computer always win, so you see what you are writing."""
    arts = local()
    top, t_local, dirty = checkout()
    about = {"source": "this computer", "updated": t_local, "unpublished": dirty, "editable": top is not None,
             "live": settings()["live"], "checking": _LIVE["busy"], "error": _LIVE["error"], "site": SITE + "/wiki/"}
    lv = live() if settings()["live"] else None
    if lv and not dirty and int(lv.get("commit_time") or 0) > t_local:
        arts = lv["articles"]
        about.update(source="the website", updated=int(lv.get("commit_time") or 0))
    return arts, about


def index():
    if settings()["live"]:
        refresh_live()
    arts, about = current()
    return {"about": about, "articles": [{k: a.get(k, "") for k in ("id", "group", "title", "sub", "no", "text", "url")}
                                         for a in arts]}


def article(aid):
    arts, about = current()
    a = next((a for a in arts if a["id"] == aid), None)
    if a is None:
        return None
    out = {k: v for k, v in a.items() if k != "file"}
    out["editable"] = about["editable"] and about["source"] == "this computer"
    return out


# ---------------------------------------------------------------- media
def _asset_path(name):
    p = HERE / "assets" / name
    if p.is_file():
        return p
    c = _home() / "wiki-live" / "assets" / name
    if c.is_file():
        return c
    lv = live()
    if lv and name in (lv.get("assets") or []) and settings()["live"]:
        try:
            req = urllib.request.Request(f"{SITE}/wiki/assets/{name}", headers={"User-Agent": "hypnomix-app"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read()
            c.parent.mkdir(parents=True, exist_ok=True)
            c.write_bytes(data)
            return c
        except Exception:
            return None
    return None


def asset(name, rng=None):
    """-> (code, body, type, extra headers). Videos need byte ranges to play in Safari and the Mac app."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name or ""):
        return 404, b'{"error":"not found"}', "application/json", None
    p = _asset_path(name)
    if p is None:
        return 404, b'{"error":"not found"}', "application/json", None
    ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    data = p.read_bytes()
    n = len(data)
    head = {"Accept-Ranges": "bytes"}
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", (rng or "").strip())
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            a = int(m.group(1))
            b = min(int(m.group(2)) if m.group(2) else n - 1, n - 1)
        else:
            a, b = max(0, n - int(m.group(2))), n - 1
        if a > b or a >= n:
            return 416, b"", ctype, {"Content-Range": f"bytes */{n}"}
        head["Content-Range"] = f"bytes {a}-{b}/{n}"
        return 206, data[a:b + 1], ctype, head
    return 200, data, ctype, head


# ---------------------------------------------------------------- edit and publish (a git checkout only)
def edit(aid):
    a = next((a for a in local() if a["id"] == aid), None)
    if a is None:
        return 404, {"error": "no such article"}
    subprocess.run(["open", "-t", a["file"]])          # the default text editor
    return 200, {"file": a["file"]}


def publish(message=""):
    """Commit the wiki's changed files (nothing else) and push them. The website rebuilds from the push."""
    top, _, dirty = checkout()
    if top is None:
        return 400, {"error": "this copy of hypnomix is not a git checkout: edit the wiki in your hypnomix folder"}
    if not dirty:
        return 200, {"done": "nothing to publish"}
    rel = str(HERE.resolve().relative_to(top.resolve()))
    for args in (("add", "-A", "--", rel),
                 ("commit", "-q", "-m", "wiki: " + (message.strip() or "update articles"), "--", rel),
                 ("pull", "-q", "--rebase", "--autostash"), ("push", "-q")):
        code, out = git(*args, cwd=top)
        if code:
            return 500, {"error": f"git {args[0]} failed: {out[-400:]}"}
    _, sha = git("rev-parse", "--short", "HEAD", cwd=top)
    return 200, {"done": f"published {len(dirty)} file(s) as {sha}; the website updates within about 10 minutes"}


# ---------------------------------------------------------------- the server's routes
def handle_get(path, q, headers=None):
    """-> (code, body, type[, extra headers]) for the Wiki's paths, else None."""
    if path == "/wiki.js":
        return 200, HERE.with_name("wiki.js").read_bytes(), "text/javascript; charset=utf-8"
    if path == "/api/wiki":
        return 200, json.dumps(index()).encode(), "application/json"
    if path == "/api/wiki/article":
        a = article(q.get("id", ""))
        if a is None:
            return 404, b'{"error":"no such article"}', "application/json"
        return 200, json.dumps(a).encode(), "application/json"
    if path.startswith("/wiki/assets/"):
        return asset(path.rsplit("/", 1)[1], (headers or {}).get("Range"))
    return None


def handle_post(path, body):
    if path == "/api/wiki/edit":
        return edit(str(body.get("id", "")))
    if path == "/api/wiki/publish":
        return publish(str(body.get("message", "")))
    if path == "/api/wiki/settings":
        s = save_settings(live=bool(body.get("live", True)))
        if s["live"]:
            refresh_live(force=True)
        return 200, s
    if path == "/api/wiki/check":
        refresh_live(force=True)
        return 200, {"checking": True}
    return None
