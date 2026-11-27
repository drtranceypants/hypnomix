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
it; every copy of the app then shows the newer articles from the site (it asks the site at most once an hour while
the Wiki is in use, with the ETag of the copy it has, so an unchanged list costs a few hundred bytes; it keeps the last
copy for when it is offline). Turn that off in the tab.
"""
import hashlib
import html as _html
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from hypnomix.core.paths import HOME

HERE = Path(__file__).with_name("wiki")
SITE = "https://hypnomix.bradfieldenterprises.org"
LIVE_URL = SITE + "/wiki/articles.json"
CHECK_EVERY = 3600                     # the website is asked at most this often, while the Wiki is in use (a failed ask is repeated after RETRY_AFTER)
RETRY_AFTER = 600
LIVE_MAX = 20 * 1024 * 1024            # the site's article list is read up to this size
ASSET_MAX = 50 * 1024 * 1024           # and one picture or video fetched from the site up to this
_CACHE, _LIVE = {}, {"checked": 0, "busy": False, "error": None}
_LOCK = threading.Lock()
MAX_TIME = 4102444800                  # 1 Jan 2100: a later "commit time" in the site's file is nonsense, not a reason to prefer it


def _home():
    return HOME


def settings():
    f = _home() / "wiki.json"
    try:
        return {"live": True, **json.loads(f.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return {"live": True}


def write_private(path, data):
    """Write a file only its owner can read (mode 0600), replacing it in one step."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")      # mkstemp makes it 0600
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        from hypnomix.core.atomic import replace as atomic_replace
        atomic_replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save_settings(**kw):
    s = {**settings(), **kw}
    write_private(_home() / "wiki.json", json.dumps(s, indent=1))
    return s


# ---------------------------------------------------------------- how the wiki is organised
# By DAW first, then by how you connect an AI (or don't), then the courses, guides and reference. Groups not listed
# here go just before Reference. An article file names its own group; the Markdown guides and docs are placed here.
DAW_LIVE, DAW_REAPER, DAW_ARDOUR, DAW_OTHER = ("DAW: Ableton Live", "DAW: REAPER", "DAW: HypnoMix DAW", "DAW: any other")
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
    raw = Path(path).read_text(encoding="utf-8")
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


COURSE_ERROR = []          # why the teacher-mode course articles could not be built, if they could not (wiki_build checks)


def local(root=None):
    """Every article: the article files, with the guides placed before the Reference group."""
    root = Path(root) if root else HERE
    files = sorted((root / "articles").glob("*.html"))
    guides = guide_files(root)
    docs = doc_files(root)
    skills = skill_files(root) + agent_files(root)
    cli = Path(__file__).resolve().parents[1] / "cli.py"
    teach = Path(__file__).with_name("teacher.py")              # the teacher-mode courses are articles too
    lessons = sorted(Path(__file__).with_name("lessons").glob("*.py"))
    key = (str(root), tuple((str(f), f.stat().st_mtime) for f in files + guides + docs + skills
                            + [x for x in [cli, teach, *lessons] if x.exists()]))
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
        try:                                  # teacher mode: per DAW the tour, the course contents and a chapter each; the glossary (the real wiki only)
            if root.resolve() != Path(__file__).with_name("wiki").resolve():
                raise LookupError
            from hypnomix.app import teacher
            have = {a["id"] for a in arts}
            arts += [a for a in teacher.wiki_all() if a["id"] not in have]
            COURSE_ERROR.clear()
        except LookupError:
            pass
        except Exception as e:                # the app's wiki must still open, but the site build must not ship without the course
            COURSE_ERROR[:] = [f"{type(e).__name__}: {e}"]
        _CACHE.update(key=key, arts=wiki_md.link_files(organise(arts)))
    return _CACHE["arts"]


def git(*args, cwd=None):
    try:
        r = subprocess.run(["git", *args], cwd=cwd or HERE, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
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


_GIT = {}                                   # what git said: {"top": (HERE, code, root), "hit": (stamp of the wiki's files, when, answer)}
GIT_FOR = 60                                # seconds an answer about the commit time and unpublished files is kept


def checkout():
    """-> (repo root, commit time of the wiki, unpublished changes) when running from a git checkout.
    Three git programs are started to work it out, so the answer is kept for a minute, and dropped at once when one of the
    wiki's files changes (the stamp `local()` took of them) or after a Publish: an edit still shows up straight away."""
    key = _CACHE.get("key")
    hit = _GIT.get("hit")
    if hit and hit[0] == key and time.time() - hit[1] < GIT_FOR:
        return hit[2]
    val = _checkout()
    _GIT["hit"] = (key, time.time(), val)
    return val


def _checkout():
    mine = _GIT.get("top")                  # where the repository is cannot change while this program runs
    if mine and mine[0] == str(HERE):
        code, top = mine[1], mine[2]
    else:
        code, top = git("rev-parse", "--show-toplevel")
        _GIT["top"] = (str(HERE), code, top)
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


# ---------------------------------------------------------------- keeping the articles harmless
# An article's HTML comes from the website's copy (and from the copy kept on this computer), and it is shown inside
# the app's own page, which holds the token that lets the page run things. So every article goes through this
# allow-list on its way to the browser, whichever copy it came from: a tag or attribute not named here is dropped;
# scripts, frames, forms and drawings (svg, math) are removed with everything inside them; and a link or file must
# be http, https, mailto, a relative path or a #fragment. wiki.js repeats the same rules (CLEAN_* there) with
# DOMParser before the HTML goes into the page; a test keeps the two lists the same.
CLEAN_TAGS = ("a abbr article aside audio b blockquote br caption cite code col colgroup dd del details dfn div dl dt em "
              "figcaption figure footer h1 h2 h3 h4 h5 h6 header hr i img ins kbd li mark ol p pre q s samp section small "
              "source span strong sub summary sup table tbody td tfoot th thead tr track u ul var video wbr").split()
CLEAN_DROP = ("script style iframe frame frameset object embed applet param link meta base form input button select option "
              "optgroup textarea label fieldset legend datalist output svg math template noscript title head xmp noembed "
              "noframes plaintext canvas dialog portal map area").split()
CLEAN_ATTRS = {
    "*": "class id title aria-label aria-hidden data-src data-label",
    "a": "href target rel data-jump data-wiki",              # only a link can jump: the app's click handlers never see these elsewhere
    "img": "src alt width height loading",
    "video": "src poster controls loop muted playsinline preload width height",
    "audio": "src controls loop muted preload",
    "source": "src type",
    "track": "src kind srclang label default",
    "td": "colspan rowspan", "th": "colspan rowspan scope", "col": "span", "colgroup": "span",
    "ol": "start reversed", "details": "open",
}
# The class names the wiki's own style sheet (wiki.js) gives a look to. Any other class is dropped, so an article cannot
# borrow the app's own (cmd, primary, tab ...: its buttons and rows) to look or act like part of the app.
CLEAN_CLASSES = ("arrow c demo-cap demo-loops devdemo devloop devpanel extra faq flow frame-paper group groups lead "
                 "no note note-box o p pair paper prose shot shots step steps sub sub-h tablewrap tagline term walkthrough "
                 "warn-box").split()
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_BOOL = {"controls", "loop", "muted", "playsinline", "default", "reversed", "open"}
_A = re.ASCII
_WORD = re.compile(r"[\w.:-]{1,120}", _A)
_VALUE = {                                   # what each attribute may hold (anything else is dropped)
    "id": re.compile(r"s-[\w-]{1,100}", _A),
    "title": re.compile(r".{1,300}", re.S), "alt": re.compile(r".{0,300}", re.S), "aria-label": re.compile(r".{1,300}", re.S),
    "aria-hidden": re.compile(r"true|false"), "data-jump": _WORD, "data-wiki": _WORD, "data-label": re.compile(r".{1,200}", re.S),
    "target": re.compile(r"_blank"), "width": re.compile(r"\d{1,5}(px|%)?"), "height": re.compile(r"\d{1,5}(px|%)?"),
    "loading": re.compile(r"lazy|eager"), "preload": re.compile(r"none|metadata|auto"),
    "type": re.compile(r"[\w.+-]+/[\w.+-]+(; ?codecs=\"?[\w.,+ -]+\"?)?", _A),
    "kind": re.compile(r"subtitles|captions|descriptions|chapters|metadata"), "label": re.compile(r".{1,100}", re.S),
    "srclang": re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?"), "scope": re.compile(r"row|col|rowgroup|colgroup"),
    "colspan": re.compile(r"\d{1,4}"), "rowspan": re.compile(r"\d{1,4}"), "span": re.compile(r"\d{1,4}"), "start": re.compile(r"\d{1,6}"),
}
_URL_ATTRS = ("href", "src", "poster", "data-src")
_URL_OK = ("http", "https", "mailto")


def safe_url(v):
    """-> the link or file name, or None when it is not http, https, mailto, a relative path or a #fragment."""
    v = re.sub(r"[\x00-\x1f\x7f]", "", v or "").strip()
    if not v or len(v) > 2000:
        return None
    probe = re.sub(r"[\s\x00-\x20\x7f-\x9f\u200b-\u200f\u2028\u2029\u2060\ufeff]", "", v).lower()
    if probe.startswith(("//", "\\", "/\\")):                      # another site, by the browser's rules
        return None
    m = re.match(r"([a-z][a-z0-9+.-]*):", probe)
    if m and m.group(1) not in _URL_OK:
        return None
    return v


def _attrs(tag, attrs):
    ok = set(CLEAN_ATTRS["*"].split()) | set(CLEAN_ATTRS.get(tag, "").split())
    out, seen = [], set()
    for k, v in attrs:
        k = (k or "").lower()
        if k not in ok or k in seen:
            continue
        seen.add(k)
        v = (v or "").strip() if k != "alt" else (v or "")
        if k in _BOOL:
            out.append(k)
        elif k in _URL_ATTRS:
            v = safe_url(v)
            if v is not None:
                out.append(f'{k}="{_html.escape(v, quote=True)}"')
        elif k == "class":
            toks = [t for t in v.split() if t in CLEAN_CLASSES]
            if toks:
                out.append(f'class="{" ".join(toks)}"')
        elif k == "rel":
            toks = [t for t in v.lower().split() if t in ("noopener", "noreferrer", "nofollow")]
            if toks:
                out.append(f'rel="{" ".join(toks)}"')
        elif k in _VALUE and _VALUE[k].fullmatch(re.sub(r"[\x00-\x1f\x7f]", " ", v)):
            out.append(f'{k}="{_html.escape(v, quote=True)}"')
    if tag == "a" and any(a == 'target="_blank"' for a in out) and not any(a.startswith("rel=") for a in out):
        out.append('rel="noopener"')                              # a link that opens a new tab never gets the app's window
    return ("" if not out else " " + " ".join(out))


HTML_MAX = 1_000_000                       # an article longer than this is cut (the longest shipped one is about 50 KB)
CLEAN_SECONDS = 10                         # markup that takes longer than this to read is shown as plain words
MAX_DEPTH = 300                            # tags nested deeper than this are not a page, they are an attack


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.open, self.skip = [], [], None
        self.until = time.monotonic() + CLEAN_SECONDS

    def _check(self):
        if time.monotonic() > self.until or len(self.open) > MAX_DEPTH:
            raise ValueError("too much to clean")

    def handle_starttag(self, tag, attrs):
        self._check()
        if self.skip:
            if tag == self.skip[0]:
                self.skip[1] += 1
            return
        if tag in CLEAN_DROP:
            if tag not in _VOID:
                self.skip = [tag, 1]
            return
        if tag not in CLEAN_TAGS:                                  # an unknown tag: its words stay, the tag goes
            return
        self.out.append(f"<{tag}{_attrs(tag, attrs)}>")
        if tag not in _VOID:
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in CLEAN_TAGS and tag not in _VOID and not self.skip:
            self.handle_endtag(tag)
        elif self.skip and tag == self.skip[0] and tag in CLEAN_DROP:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[0]:
                self.skip[1] -= 1
                if not self.skip[1]:
                    self.skip = None
            return
        if tag in CLEAN_TAGS and tag not in _VOID and tag in self.open:
            while self.open:                                       # close what was left open inside it, too
                t = self.open.pop()
                self.out.append(f"</{t}>")
                if t == tag:
                    break

    def handle_data(self, data):
        self._check()
        if not self.skip:
            self.out.append(_html.escape(data, quote=False))

    def finish(self):
        self.close()
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        return "".join(self.out)


def sanitize_html(src):
    """An article's HTML with only the allowed tags and attributes left (see above)."""
    src = src[:HTML_MAX] if isinstance(src, str) else ""
    try:
        c = _Cleaner()
        c.feed(src)
        return c.finish()
    except Exception:                                              # never let odd markup through: keep only its words
        return "<p>" + _html.escape(re.sub(r"<[^>]*>", " ", src[:100000]), quote=False) + "</p>"


_CLEANED = {}                                                      # (length, checksum of the HTML) -> its clean form


def cleaned(src):
    """sanitize_html, remembered: an article is cleaned once however often it is opened."""
    if not isinstance(src, str):
        return ""
    key = (len(src), hashlib.sha1(src.encode("utf-8", "replace")).hexdigest())
    out = _CLEANED.get(key)
    if out is None:
        if len(_CLEANED) >= 300:
            _CLEANED.clear()
        out = _CLEANED[key] = sanitize_html(src)
    return out


def _text(v, n=100000):
    return v[:n] if isinstance(v, str) else ""


def tidy(a):
    """One article from the website's copy, made safe to hold: only known fields, all text, a link that stays on the site."""
    if not isinstance(a, dict):
        return None
    aid = _text(a.get("id"), 200)
    if not aid:
        return None
    url = _text(a.get("url"), 500)
    return {"id": aid, "group": _text(a.get("group"), 200) or "Wiki", "title": _text(a.get("title"), 500) or aid,
            "sub": _text(a.get("sub"), 1000), "no": _text(a.get("no"), 100), "teaser": _text(a.get("teaser"), 5000),
            "html": _text(a.get("html"), HTML_MAX), "text": _text(a.get("text"), 2000000),
            "url": url if url.startswith(SITE + "/") else f"{SITE}/wiki/#{aid}", "generated": bool(a.get("generated"))}


def _int(v, top=None):
    """v as a whole number; 0 when it is not one (text, infinity, nan, a giant) or is above top."""
    try:
        n = int(v or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return n if top is None or abs(n) <= top else 0


# ---------------------------------------------------------------- the live copy on the website
def _live_file():
    return _home() / "wiki-live" / "articles.json"


_PARSED = {}                               # the one parsed copy: {"hit": ((path, inode, mtime, size), value)}


def live():
    """The copy of the website's wiki kept on this computer, or None. Whatever is in the file is checked on the way in.
    The file is a few megabytes: it is read and checked once, and again only when the file itself changes (its path,
    inode, size and modification time are the key; a file written in the last two seconds is never trusted to the key
    alone), not on every request. The answer is shared: nothing may change it."""
    try:
        f = _live_file()
        st = f.stat()
    except Exception:                      # no copy (or anything odd about where it is): the bundled articles show
        return None
    key = (str(f), st.st_ino, st.st_mtime_ns, st.st_size)
    hit = _PARSED.get("hit")               # one read: another request thread may clear it at any moment
    if hit and hit[0] == key:
        return hit[1]
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("articles"), list):
            val = None
        else:
            arts = [t for t in (tidy(a) for a in data["articles"][:2000]) if t]
            assets = [n for n in data["assets"] if isinstance(n, str)] if isinstance(data.get("assets"), list) else []
            val = {"commit_time": _int(data.get("commit_time"), top=MAX_TIME), "articles": arts, "assets": assets}
    except Exception:                      # a damaged or odd file is no copy at all: the bundled articles show
        val = None
    _PARSED.clear()
    if time.time() - st.st_mtime > 2:      # a file still being changed (same size, same clock tick) is read again next time
        _PARSED["hit"] = (key, val)
    return val


def _live_meta_file():
    return _home() / "wiki-live" / "articles.meta.json"


_HEADER_OK = re.compile(r"[\x20-\x7e]{1,300}\Z")


def _live_validators():
    """(ETag, Last-Modified) the website gave with the copy on this computer: used only while that file is still exactly
    the one they were given for (its inode, size and modification time are recorded with them). Anything else (the file gone,
    replaced or edited, the note damaged or deleted) gives nothing, and the next check downloads the whole list again."""
    try:
        m = json.loads(_live_meta_file().read_text(encoding="utf-8"))
        st = _live_file().stat()
        if (m.get("ino"), m.get("size"), m.get("mtime_ns")) != (st.st_ino, st.st_size, st.st_mtime_ns):
            return "", ""
        return tuple(v if isinstance(v, str) and _HEADER_OK.match(v) else "" for v in (m.get("etag"), m.get("last_modified")))
    except (OSError, ValueError, AttributeError, TypeError):
        return "", ""


def _remember_validators(etag, last_modified):
    """Record what the website said about the copy just written (a small private file beside it)."""
    meta = _live_meta_file()
    try:
        if not (etag or last_modified):
            meta.unlink(missing_ok=True)
            return
        st = _live_file().stat()
        write_private(meta, json.dumps({"etag": etag, "last_modified": last_modified, "ino": st.st_ino, "size": st.st_size,
                                        "mtime_ns": st.st_mtime_ns}))
    except OSError:
        pass                                    # the note is only a shortcut: without it the next check downloads in full


def refresh_live(force=False):
    """Ask the website for its articles in the background (at most every CHECK_EVERY seconds, and only while the Wiki is
    in use). The question is conditional: with the ETag / Last-Modified the website gave for the copy on this computer, an
    unchanged list is answered with a few hundred bytes (304) instead of the whole 5 MB, and a changed one comes gzipped."""
    with _LOCK:
        if _LIVE["busy"] or (not force and time.time() - _LIVE["checked"] < CHECK_EVERY) or not settings()["live"]:
            return
        _LIVE["busy"] = True

    def go():
        ok = False
        try:
            etag, since = _live_validators()
            head = {"User-Agent": "hypnomix-app", "Accept-Encoding": "gzip"}
            if etag:
                head["If-None-Match"] = etag
            if since:
                head["If-Modified-Since"] = since
            req = urllib.request.Request(LIVE_URL, headers=head)
            try:
                with urllib.request.urlopen(req, timeout=8) as r:
                    raw = r.read(LIVE_MAX + 1)
                    enc = str(r.headers.get("Content-Encoding") or "").lower()
                    new_etag, new_since = (str(r.headers.get(h) or "") for h in ("ETag", "Last-Modified"))
            except urllib.error.HTTPError as e:
                if e.code != 304 or not (etag or since):
                    raise
                _LIVE["error"] = None                 # not changed: the copy on this computer is the website's
                ok = True
                return
            if len(raw) > LIVE_MAX:
                raise ValueError("the site's wiki is larger than expected")
            if enc == "gzip":                           # read at most LIVE_MAX of it unpacked: a small download cannot unpack to a flood
                import gzip
                import io
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as g:
                    raw = g.read(LIVE_MAX + 1)
                if len(raw) > LIVE_MAX:
                    raise ValueError("the site's wiki is larger than expected")
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("articles"), list):
                raise ValueError("no articles in the site's wiki")
            write_private(_live_file(), raw)
            _remember_validators(*(v if _HEADER_OK.match(v) else "" for v in (new_etag, new_since)))
            _LIVE["error"] = None
            ok = True
        except Exception as e:             # offline, or the site is down: keep what we have
            _LIVE["error"] = f"{type(e).__name__}: {e}"[:200]
        finally:
            # a check that failed is tried again in ten minutes, not after a whole CHECK_EVERY
            _LIVE.update(checked=time.time() - (0 if ok else CHECK_EVERY - RETRY_AFTER), busy=False)

    threading.Thread(target=go, daemon=True).start()


def current():
    """-> (articles, about): the newest of this computer's files and the website's copy. Unpublished
    edits on this computer always win, so you see what you are writing."""
    arts = local()
    top, t_local, dirty = checkout()
    about = {"source": "this computer", "updated": t_local, "unpublished": dirty, "editable": top is not None,
             "live": settings()["live"], "checking": _LIVE["busy"], "error": _LIVE["error"], "site": SITE + "/wiki/"}
    lv = live() if settings()["live"] else None
    if lv and not dirty and lv["commit_time"] > t_local:
        arts = lv["articles"]
        about.update(source="the website", updated=lv["commit_time"])
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
    out["html"] = cleaned(out.get("html"))           # from any copy: the website's, the cached one, or this computer's
    out["editable"] = about["editable"] and about["source"] == "this computer" and not a.get("generated")
    return out


# ---------------------------------------------------------------- media
ASSET_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif",
               "mp4": "video/mp4", "webm": "video/webm", "mp3": "audio/mpeg", "wav": "audio/wav"}


def _kind(name):
    return ASSET_TYPES.get(name.rsplit(".", 1)[-1].lower()) if "." in name else None


def _fetch_asset(name, dest):
    """Fetch one file from the website into dest (at most ASSET_MAX bytes, read in pieces). -> True when kept."""
    req = urllib.request.Request(f"{SITE}/wiki/assets/{name}", headers={"User-Agent": "hypnomix-app"})
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(dest.parent), prefix=dest.name + ".part")     # its own name: two requests can race
    try:
        with urllib.request.urlopen(req, timeout=20) as r, os.fdopen(fd, "wb") as f:
            if _int(r.headers.get("Content-Length")) > ASSET_MAX:
                return False
            total = 0
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > ASSET_MAX:                                   # too big: stop and throw away what came
                    return False
                f.write(chunk)
        os.replace(tmp, dest)
        return True
    except Exception:
        return False
    finally:
        Path(tmp).unlink(missing_ok=True)


def _asset_path(name):
    p = HERE / "assets" / name
    if p.is_file():
        return p
    c = _home() / "wiki-live" / "assets" / name
    if c.is_file():
        return c
    lv = live()
    if lv and name in lv["assets"] and settings()["live"] and _kind(name):     # only kinds the app would show
        return c if _fetch_asset(name, c) else None
    return None


def asset(name, rng=None):
    """-> (code, body, type, extra headers). Videos need byte ranges to play in Safari and the Mac app.
    Only pictures, video and sound are served as what they are; anything else is a download (never a page)."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name or ""):
        return 404, b'{"error":"not found"}', "application/json", None
    p = _asset_path(name)
    if p is None:
        return 404, b'{"error":"not found"}', "application/json", None
    ctype = _kind(p.name)
    data = p.read_bytes()
    n = len(data)
    head = {"Accept-Ranges": "bytes"}
    if ctype is None:
        ctype = "application/octet-stream"
        head["Content-Disposition"] = "attachment"
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
    _GIT.pop("hit", None)                                  # what git says about the files now, not a minute ago
    top, _, dirty = checkout()
    if top is None:
        return 400, {"error": "this copy of HypnoMix is not a git checkout: edit the wiki in your HypnoMix folder"}
    if not dirty:
        return 200, {"done": "nothing to publish"}
    paths = sources(top)
    for args in (("add", "-A", "--", *paths),
                 ("commit", "-q", "-m", "wiki: " + (message.strip() or "update articles"), "--", *paths),
                 ("pull", "-q", "--rebase", "--autostash"), ("push", "-q")):
        code, out = git(*args, cwd=top)
        _GIT.pop("hit", None)                              # the commit changed what git says about these files
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
