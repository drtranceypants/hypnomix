"""Copy the website's training, how-to and FAQ articles into the app's Wiki tab, so the two always match.

    python -m hypnomix.app.wiki_sync                       # from the live site
    python -m hypnomix.app.wiki_sync --from SITE/public    # from a local copy of the site (index.html, training/)

Each <section> of the site's training page and the how-to sections of its home page become one article in
hypnomix/app/wiki/articles.json. The HTML is cleaned to a small set of safe tags and attributes, links between
sections become links between articles, and every image and video the articles use is copied into
hypnomix/app/wiki/assets/ so the Wiki works offline. Run it after the site changes, then commit the result.
"""
import argparse
import datetime
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

SITE = "https://hypnomix.bradfieldenterprises.org"
HERE = Path(__file__).with_name("wiki")

# (page, section id, group). Order here is the order in the Wiki.
ARTICLES = [("training", "loop", "Training")] + [("training", f"l{i}", "Training") for i in range(1, 16)] + [
    ("home", "what", "Start here"), ("home", "app", "Start here"), ("home", "requirements", "Start here"),
    ("home", "install", "Start here"),
    ("home", "use", "How-to"), ("home", "agents", "How-to"), ("home", "local", "How-to"), ("home", "plugins", "How-to"),
    ("home", "chores", "Reference"), ("home", "features", "Reference"), ("home", "faq", "FAQ"),
]
PAGES = {"home": "/", "training": "/training/"}

KEEP = {"p", "b", "strong", "i", "em", "code", "pre", "span", "a", "ul", "ol", "li", "h3", "h4", "h5", "figure",
        "figcaption", "img", "video", "source", "table", "thead", "tbody", "tr", "td", "th", "details", "summary",
        "div", "br", "kbd", "blockquote", "dl", "dt", "dd", "small", "sup", "sub", "hr", "h2"}
DROP = {"script", "style", "svg", "button", "form", "input", "select", "textarea", "iframe", "noscript", "nav"}
VOID = {"img", "br", "hr", "source"}
ATTRS = {"class", "href", "src", "alt", "title", "poster", "controls", "muted", "playsinline", "preload", "width",
         "height", "loading", "id", "data-label", "open", "colspan", "rowspan", "type", "start"}


class Sections(HTMLParser):
    """Raw HTML of every top-level <section id=...> on a page."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out, self.cur, self.depth, self.buf = {}, None, 0, []

    def _raw(self):
        return self.get_starttag_text() or ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.cur is None:
            if tag == "section" and a.get("id"):
                self.cur, self.depth, self.buf = a["id"], 1, []
            return
        if tag == "section":
            self.depth += 1
        self.buf.append(self._raw())

    def handle_startendtag(self, tag, attrs):
        if self.cur is not None:
            self.buf.append(self._raw())

    def handle_endtag(self, tag):
        if self.cur is None:
            return
        if tag == "section":
            self.depth -= 1
            if self.depth == 0:
                self.out[self.cur] = "".join(self.buf)
                self.cur = None
                return
        self.buf.append(f"</{tag}>")

    def handle_data(self, d):
        if self.cur is not None:
            self.buf.append(d)

    def handle_entityref(self, n):
        if self.cur is not None:
            self.buf.append(f"&{n};")

    def handle_charref(self, n):
        if self.cur is not None:
            self.buf.append(f"&#{n};")


class Clean(HTMLParser):
    """Keep safe tags and attributes; rewrite links and media; collect the title, subtitle and plain text."""

    def __init__(self, page, ids, assets):
        super().__init__(convert_charrefs=True)
        self.page, self.ids, self.assets = page, ids, assets
        self.out, self.text, self.skip, self.open = [], [], 0, []
        self.title, self.sub, self.no = "", "", ""
        self.grab = None                       # "title" | "sub" | "no" while inside those elements
        self.grab_depth = 0

    def link(self, href):
        """-> (href, wiki article id or None). Links to a section that is in the Wiki stay in the Wiki."""
        if href.startswith(("mailto:", "tel:")):
            return href, None
        full = urllib.parse.urlparse(urllib.parse.urljoin(SITE + PAGES[self.page], href))
        if full.netloc == urllib.parse.urlparse(SITE).netloc:
            if full.fragment in self.ids:
                return "#", full.fragment
            if full.path.rstrip("/") == "/training" and not full.fragment:
                return "#", "loop"
        return urllib.parse.urlunparse(full), None

    def media(self, src):
        full = urllib.parse.urljoin(SITE + PAGES[self.page], src)
        if urllib.parse.urlparse(full).netloc != urllib.parse.urlparse(SITE).netloc:
            return full
        name = Path(urllib.parse.urlparse(full).path).name
        self.assets[name] = urllib.parse.urlparse(full).path
        return f"/wiki/assets/{name}"

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if self.skip:
            if tag not in VOID:
                self.skip += 1
            return
        if tag in DROP or "orn" in cls.split():
            if tag not in VOID:
                self.skip = 1
            return
        if self.grab:
            self.grab_depth += 1
            return
        if tag == "h2" and not self.title:
            self.grab, self.grab_depth = "title", 1
            return
        if tag == "p" and "sub" in cls.split() and not self.sub and not "".join(self.out).strip():
            self.grab, self.grab_depth = "sub", 1
            return
        if tag == "span" and "lesson-no" in cls.split():
            self.grab, self.grab_depth = "no", 1
            return
        if tag not in KEEP:
            return
        keep = {}
        for k, v in attrs:
            if k not in ATTRS:
                continue
            v = "" if v is None else v
            if k in ("src", "poster"):
                v = self.media(v)
            if k == "href":
                v, target = self.link(v)
                if target:
                    keep["data-wiki"] = target
                elif v.startswith("http"):
                    keep["target"], keep["rel"] = "_blank", "noopener"
            if k == "class":
                v = " ".join(c for c in v.split() if c not in ("reveal", "shimmer"))
                if not v:
                    continue
            keep[k] = v
        if tag == "h2":
            tag = "h3"
        if tag == "video":
            keep.setdefault("controls", "")
        at = "".join(f' {k}="{html.escape(v, quote=True)}"' if v != "" else f" {k}" for k, v in keep.items())
        self.out.append(f"<{tag}{at}>")
        if tag not in VOID:
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        """<x/>: nothing inside it, so it never opens a skip or a grab."""
        if self.skip or self.grab or tag in DROP:
            return
        n = len(self.open)
        self.handle_starttag(tag, attrs)
        if len(self.open) > n:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.skip:
            if tag not in VOID:
                self.skip -= 1
            return
        if self.grab:
            self.grab_depth -= 1
            if self.grab_depth == 0:
                self.grab = None
            return
        if tag == "h2":
            tag = "h3"
        if tag in VOID or tag not in KEEP or tag not in self.open:
            return
        while self.open:
            t = self.open.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, d):
        if self.skip:
            return
        if self.grab:
            setattr(self, self.grab, (getattr(self, self.grab) + d))
            return
        self.out.append(html.escape(d, quote=False))
        self.text.append(d)

    def result(self):
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        body = re.sub(r"\n\s*\n+", "\n", "".join(self.out)).strip()
        text = re.sub(r"\s+", " ", " ".join(self.text)).strip()
        norm = lambda s: re.sub(r"\s+", " ", s).strip()
        return norm(self.title), norm(self.sub), norm(self.no), body, text


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "hypnomix-wiki-sync"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def page_html(src, page):
    if src:
        p = Path(src) / ("index.html" if page == "home" else "training/index.html")
        return p.read_text()
    return fetch(SITE + PAGES[page]).decode("utf-8")


def main():
    ap = argparse.ArgumentParser(prog="python -m hypnomix.app.wiki_sync", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="src", metavar="SITE_DIR", help="a local copy of the site (default: the live site)")
    ap.add_argument("--out", default=str(HERE), help="where articles.json and assets/ go (default: the app's wiki)")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "assets").mkdir(parents=True, exist_ok=True)
    pages = {}
    for page in PAGES:
        sp = Sections()
        sp.feed(page_html(a.src, page))
        pages[page] = sp.out
    ids = {sid for page, sid, _ in ARTICLES}
    assets, arts, missing = {}, [], []
    for page, sid, group in ARTICLES:
        raw = pages[page].get(sid)
        if raw is None:
            missing.append(f"{page}#{sid}")
            continue
        c = Clean(page, ids, assets)
        c.feed(raw)
        title, sub, no, body, text = c.result()
        arts.append({"id": sid, "group": group, "title": title or sid, "sub": sub, "no": no, "html": body,
                     "text": text, "url": SITE + PAGES[page] + "#" + sid})
    got = 0
    for name, path in sorted(assets.items()):
        dest = out / "assets" / name
        data = (Path(a.src) / path.lstrip("/")).read_bytes() if a.src else fetch(SITE + path)
        if not dest.exists() or dest.read_bytes() != data:
            dest.write_bytes(data)
            got += 1
    for old in (out / "assets").iterdir():
        if old.name not in assets:
            old.unlink()
    (out / "articles.json").write_text(json.dumps({
        "source": SITE, "synced": datetime.date.today().isoformat(), "articles": arts}, indent=1, ensure_ascii=False))
    print(f"{len(arts)} articles, {len(assets)} images and videos ({got} new or changed) → {out}")
    if missing:
        print("not on the site (left out): " + ", ".join(missing), file=sys.stderr)


if __name__ == "__main__":
    main()
