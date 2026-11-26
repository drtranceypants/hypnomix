"""The hypnomix wiki: one set of articles for the app's Wiki tab and the website's /wiki/ page.

Source: one file per article in hypnomix/app/wiki/articles/ ("NN-id.html": NN sets the order), an HTML
fragment under a short header, and the images and videos it shows in hypnomix/app/wiki/assets/. The guides
(docs/guides/NN-*.md) are articles too, in the Guides group, read straight from their Markdown (wiki_md.py), so
one file feeds the app and the website:

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


# ---------------------------------------------------------------- how the wiki is organised
# By DAW first, then by how you connect an AI (or don't), then the courses, guides and reference. Groups not listed
# here go just before Reference. An article file names its own group; the Markdown guides and docs are placed here.
DAW_LIVE, DAW_REAPER, DAW_ARDOUR, DAW_OTHER = ("DAW: Ableton Live", "DAW: REAPER", "DAW: Ardour", "DAW: any other")
AI_KEY, AI_AGENT, AI_LOCAL = ("AI: your own API key", "AI: Claude Code, Codex and other agent apps", "AI: free and offline")
GROUP_ORDER = ["Start here", DAW_LIVE, DAW_REAPER, DAW_ARDOUR, DAW_OTHER, AI_KEY, AI_AGENT, "AI: Claude Code skills and subagent", AI_LOCAL,
               "Training", "How-to", "Guides", "Docs", "Reference", "FAQ"]
PLACE = {"inside-live": DAW_LIVE, "live": DAW_LIVE, "reaper": DAW_REAPER, "reaper-doc": DAW_REAPER,
         "agents-doc": AI_AGENT, "claude": AI_AGENT}


DAW_GROUP = {"live": DAW_LIVE, "reaper": DAW_REAPER, "ardour": DAW_ARDOUR, "other": DAW_OTHER}


def organise(arts):
    """Order the groups (GROUP_ORDER), keeping each group's own order. A group not in the list stays with the
    article before it, so a new group lands where its files put it until it is given a place here."""
    rank = {g: i for i, g in enumerate(GROUP_ORDER)}
    keys, last = [], -1
    for a in arts:
        last = rank.get(a["group"], last)
        keys.append(last)
    return [a for _, _, a in sorted(zip(keys, range(len(arts)), arts), key=lambda t: t[:2])]


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


def guides_dir(root=None):
    """The guides' Markdown: docs/guides in a checkout, or the copy bundled with an installed hypnomix."""
    root = Path(root) if root else HERE
    for d in (root.resolve().parents[2] / "docs" / "guides", root / "guides", root / "docs" / "guides"):
        if d.is_dir():
            return d
    return None


def docs_dir(root=None):
    """docs/ in a checkout, or the copy bundled with an installed hypnomix."""
    root = Path(root) if root else HERE
    for d in (root.resolve().parents[2] / "docs", root / "docs"):
        if d.is_dir() and any(d.glob("*.md")):
            return d
    return None


def doc_files(root=None):
    """The files in wiki_md.ROOT_FILES first, then docs/[A-Z]*.md."""
    from hypnomix.app.wiki_md import ROOT_FILES
    root = Path(root) if root else HERE
    d = docs_dir(root)
    repo = root.resolve().parents[2]
    first = [repo / n for n in ROOT_FILES if (repo / n).exists() and (repo / "pyproject.toml").exists()]
    if not first and d is not None:
        first = [d / n for n in ROOT_FILES if (d / n).exists()]               # an installed hypnomix
    rest = sorted(f for f in d.glob("[A-Z]*.md") if f.name not in ROOT_FILES) if d else []
    return first + rest


def skill_files(root=None):
    """The Claude Code skills: skills/*/SKILL.md in a checkout, or the copy bundled with an installed hypnomix."""
    root = Path(root) if root else HERE
    for d in (root.resolve().parents[2] / "skills", root / "skills"):
        if d.is_dir():
            return sorted(d.glob("*/SKILL.md"))
    return []


def agent_files(root=None):
    """The Claude Code subagents: agents/*.md in a checkout, or the copy bundled with an installed hypnomix."""
    root = Path(root) if root else HERE
    for d in (root.resolve().parents[2] / "agents", root / "agents"):
        if d.is_dir():
            return sorted(d.glob("*.md"))
    return []


def guide_files(root=None):
    d = guides_dir(root)
    return sorted(f for f in d.glob("[0-9][0-9]-*.md") if not f.name.startswith("99")) if d else []


def local(root=None):
    """Every article: the article files, with the guides placed before the Reference group."""
    root = Path(root) if root else HERE
    files = sorted((root / "articles").glob("*.html"))
    guides = guide_files(root)
    docs = doc_files(root)
    skills = skill_files(root) + agent_files(root)
    cli = Path(__file__).resolve().parents[1] / "cli.py"
    teach = Path(__file__).with_name("teacher.py")              # the teacher-mode courses are articles too
    key = (str(root), tuple((str(f), f.stat().st_mtime) for f in files + guides + docs + skills
                            + [x for x in (cli, teach) if x.exists()]))
    if _CACHE.get("key") != key:
        from hypnomix.app import wiki_md
        arts = [parse(f) for f in files]
        ids = {a["id"] for a in arts}
        gs = [g for g in (wiki_md.article(f) for f in guides) if g["id"] not in ids]   # an article file wins
        taken = ids | {g["id"] for g in gs}
        ds = []
        for f in docs:
            d = wiki_md.doc_article(f, taken)
            taken.add(d["id"])
            ds.append(d)
        sk = []
        for f in skills:
            k = (wiki_md.skill_article if f.name == "SKILL.md" else wiki_md.agent_article)(f, taken)
            taken.add(k["id"])
            sk.append(k)
        for a in gs + ds:                                   # the Markdown guides and docs under their DAW / AI group
            if a["id"] in PLACE:
                a["group"] = PLACE[a["id"]]
        at = next((i for i, a in enumerate(arts) if a["group"] in ("Reference", "FAQ")), len(arts))
        arts = arts[:at] + gs + ds + sk + arts[at:]
        if "commands" not in {a["id"] for a in arts}:            # the command reference, from the code itself
            try:
                cmd = wiki_md.commands_article()
                at = next((i for i, a in enumerate(arts) if a["group"] == "FAQ"), len(arts))
                arts = arts[:at] + [cmd] + arts[at:]
            except Exception:                                      # never let it take the wiki down
                pass
        try:                                  # teacher mode's courses, one per DAW and level (the real wiki only)
            if root.resolve() != Path(__file__).with_name("wiki").resolve():
                raise LookupError
            from hypnomix.app import teacher
            have = {a["id"] for a in arts}
            arts += [a for a in (teacher.wiki_article(d, lv) for d in teacher.DAWS for lv in ("101", "tour"))
                     if a["id"] not in have]
        except Exception:
            pass
        _CACHE.update(key=key, arts=wiki_md.link_files(organise(arts)))
    return _CACHE["arts"]


def git(*args, cwd=None):
    try:
        r = subprocess.run(["git", *args], cwd=cwd or HERE, capture_output=True, text=True, timeout=20)
        return r.returncode, (r.stdout + r.stderr).rstrip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def sources(top):
    """The paths in the repo that make up the wiki: the wiki folder and the guides' Markdown."""
    out = [str(HERE.resolve().relative_to(Path(top).resolve()))]
    g = guides_dir()
    if g is not None and str(g.resolve()).startswith(str(Path(top).resolve())):
        out.append(str(g.resolve().relative_to(Path(top).resolve())) + "/[0-9][0-9]-*.md")
    d = docs_dir()
    if d is not None and str(d.resolve()).startswith(str(Path(top).resolve())):
        out.append(str(d.resolve().relative_to(Path(top).resolve())) + "/[A-Z]*.md")
        from hypnomix.app.wiki_md import ROOT_FILES
        out += [n for n in ROOT_FILES if (Path(top) / n).exists()]
    if (Path(top) / "skills").is_dir():
        out.append("skills/*/SKILL.md")
    if (Path(top) / "agents").is_dir():
        out.append("agents/*.md")
    return out


def checkout():
    """-> (repo root, commit time of the wiki, unpublished changes) when running from a git checkout."""
    code, top = git("rev-parse", "--show-toplevel")
    top = top.strip()
    if code:
        return None, 0, []
    paths = sources(top)
    cli = Path(__file__).resolve().parents[1] / "cli.py"     # the command reference is built from it: counts for
    dated = paths + ([str(cli.relative_to(Path(top).resolve()))]    # "which copy is newer", never for Publish
                     if str(cli).startswith(str(Path(top).resolve())) else [])
    _, t = git("log", "-1", "--format=%ct", "--", *dated, cwd=top)
    t = t.strip()
    _, st = git("status", "--porcelain", "--", *paths, cwd=top)
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
    try:                                       # the DAW chosen in Setup: the Wiki puts its pages first
        from hypnomix.app import setup as SU
        about["daw"] = SU.load().get("daw", "")
    except Exception:
        about["daw"] = ""
    return {"about": about, "articles": [{k: a.get(k, "") for k in ("id", "group", "title", "sub", "no", "text", "url")}
                                         for a in arts]}


def article(aid):
    arts, about = current()
    a = next((a for a in arts if a["id"] == aid), None)
    if a is None:
        return None
    out = {k: v for k, v in a.items() if k != "file"}
    out["editable"] = about["editable"] and about["source"] == "this computer" and not a.get("generated")
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
    a = next((a for a in local() if a["id"] == aid), None)   # a guide opens its Markdown file
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
    paths = sources(top)
    for args in (("add", "-A", "--", *paths),
                 ("commit", "-q", "-m", "wiki: " + (message.strip() or "update articles"), "--", *paths),
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
