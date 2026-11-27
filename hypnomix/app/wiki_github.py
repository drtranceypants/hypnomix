"""Build the repository's GitHub wiki from the same sources as the site's /wiki/ page and the app's Wiki tab.

    python -m hypnomix.app.wiki_github --out DIR [--version 0.4.0] [--date 2026-11-26] [--mapping FILE]

Writes a folder of Markdown pages that a GitHub wiki shows as it is:

    Home.md       the groups of the site's index, in its order, each article on one line with its teaser
    _Sidebar.md   the groups, compact (each one folds shut)
    _Footer.md    one line: this wiki mirrors the site, and the version and date it was built from
    <Page>.md     ONE page per article, guide, doc, skill, command reference and course article the site has

DIR must not exist yet, or be empty (the tool writes new files only; the workflow in .github/workflows/wiki.yml
builds into a fresh folder and copies it into the wiki's own repository). Python's standard library only: like the
website's build it runs without numpy. Nothing here reads the clock, so the same sources give the same bytes: the
version comes from --version (else pyproject.toml, else the installed package) and the date from --date (else the
date of the last commit that changed the wiki's sources, else it is left out).

PAGE NAMES come from the article's id and never from its title, so a link keeps working when a title changes:
"learn-live-mix" is "Learn-live-mix.md", lesson "l3" is "Lesson-3.md". --mapping FILE writes the id -> page list.

CONTENT. An article's HTML is converted to GitHub-flavoured Markdown by the small converter below (headings, paragraphs,
lists and nested lists, tables, code, bold, italic, links, definition lists, details/summary, quotes, images).
Links to other articles become links to their pages; a link to a screen of the app becomes plain text; a picture, a
video or an audio demo points at the site's address (a video or audio as a plain link that says what it is). What the
converter cannot express is kept as readable text and counted: the run prints how many things were simplified, and
what. The guides, docs, skills and subagents are Markdown already: they pass through with their relative links
fixed (to the wiki page, else to the file on GitHub). Every page ends with a line linking to the same article on the site.
"""
import argparse
import collections
import datetime
import html
import json
import posixpath
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hypnomix.app import wiki as W   # noqa: E402
from hypnomix.app import wiki_md     # noqa: E402

SITE = W.SITE
WIKI_URL = SITE + "/wiki/"
REPO_URL = "https://github.com/drtranceypants/hypnomix"
BLOB = wiki_md.REPO                                  # https://github.com/drtranceypants/hypnomix/blob/main/
RAW = "https://raw.githubusercontent.com/drtranceypants/hypnomix/main/"
RESERVED = {"home", "_sidebar", "_footer"}           # the names GitHub gives a meaning to
# "ardour" is the id of the one disclosure article and a part of the ids of its courses; a page name is a title and an address,
# so the word a person reads there is the product's own name (the site's own anchors, which are the ids, stay as they are).
ACRONYMS = {"faq": "FAQ", "daw": "DAW", "ai": "AI", "api": "API", "readme": "README", "md": "MD", "ardour": "HypnoMix-DAW"}
# The tags GitHub keeps in a page (the others are removed, with what is inside them).
HTML_TAGS = frozenset("a abbr b bdo blockquote br caption cite code col colgroup dd del details dfn div dl dt em figcaption figure "
                      "h1 h2 h3 h4 h5 h6 hr i img ins kbd li mark ol p picture pre q rp rt ruby s samp small source span strike "
                      "strong sub summary sup table tbody td tfoot th thead tr tt u ul var video wbr".split())
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")


# ---------------------------------------------------------------- page names
def page_name(aid):
    """The wiki page's file name (without .md), from an article id alone."""
    m = re.fullmatch(r"l(\d+)", aid)
    if m:
        return "Lesson-" + m.group(1)
    parts = [p for p in re.sub(r"[^A-Za-z0-9_-]+", "-", aid).split("-") if p]
    if not parts:
        return "Page"
    parts[0] = ACRONYMS.get(parts[0].lower(), parts[0][:1].upper() + parts[0][1:])
    parts[1:] = [ACRONYMS.get(p.lower(), p) for p in parts[1:]]
    return "-".join(parts)


def page_names(arts):
    """{article id: page name}: unique ignoring case (a wiki's pages are), never "Home", "_Sidebar" or "_Footer"."""
    out, taken = {}, set(RESERVED)
    for a in sorted(arts, key=lambda x: x["id"]):
        base = page_name(a["id"])
        name, n = base, 1
        while name.lower() in taken:
            n += 1
            name = f"{base}-{n}"
        taken.add(name.lower())
        out[a["id"]] = name
    return out


# ---------------------------------------------------------------- the HTML, as a tree
class Node:
    __slots__ = ("tag", "attrs", "kids")

    def __init__(self, tag, attrs=None):
        self.tag, self.attrs, self.kids = tag, dict(attrs or {}), []

    def get(self, k):
        return self.attrs.get(k) or ""

    def classes(self):
        return set(self.get("class").split())

    def text(self):
        out = []
        for k in self.kids:
            if isinstance(k, str):
                out.append(k)
            elif k.tag == "br":
                out.append("\n")
            else:
                out.append(k.text())
        return "".join(out)

    def find(self, tag):
        for k in self.kids:
            if isinstance(k, Node):
                if k.tag == tag:
                    return k
                f = k.find(tag)
                if f is not None:
                    return f
        return None


VOID = {"br", "hr", "img", "col", "source", "track", "wbr", "input", "meta", "link", "area", "base", "embed", "param"}
# A start tag of the key closes an open one of the listed tags, looking down the stack only as far as a boundary.
CLOSES = {"li": ({"li"}, {"ul", "ol"}), "dt": ({"dt", "dd"}, {"dl"}), "dd": ({"dt", "dd"}, {"dl"}),
          "tr": ({"tr", "td", "th"}, {"table"}), "td": ({"td", "th"}, {"tr", "table"}), "th": ({"td", "th"}, {"tr", "table"}),
          "thead": ({"thead", "tbody", "tfoot", "tr", "td", "th"}, {"table"}),
          "tbody": ({"thead", "tbody", "tfoot", "tr", "td", "th"}, {"table"})}
CLOSES_P = {"p", "ul", "ol", "dl", "table", "div", "pre", "blockquote", "details", "figure", "h1", "h2", "h3", "h4", "h5", "h6",
            "hr", "section", "article", "aside", "header", "footer"}


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        if tag in CLOSES:
            kinds, boundary = CLOSES[tag]
            for i in range(len(self.stack) - 1, 0, -1):
                t = self.stack[i].tag
                if t in boundary:
                    break
                if t in kinds:
                    del self.stack[i:]
                    break
        if tag in CLOSES_P and self.stack[-1].tag == "p":
            self.stack.pop()
        n = Node(tag, [(k, v if v is not None else "") for k, v in attrs])
        self.stack[-1].kids.append(n)
        if tag not in VOID:
            self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].kids.append(data)


def parse_html(src):
    t = Tree()
    t.feed(src)
    t.close()
    return t.root


def gh_slug(text):
    """GitHub's anchor for a heading: lower case, punctuation gone, spaces to hyphens."""
    t = re.sub(r"\s+", " ", text).strip().lower()
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", t))


# ---------------------------------------------------------------- HTML -> Markdown
INLINE = {"a", "abbr", "b", "strong", "i", "em", "code", "span", "small", "sub", "sup", "kbd", "samp", "var", "mark", "u",
          "ins", "del", "s", "strike", "cite", "q", "dfn", "wbr", "br", "img", "font", "big", "video", "audio", "tt", "time"}
BLOCKS = {"p", "div", "section", "article", "aside", "header", "footer", "main", "figure", "figcaption", "ul", "ol", "li",
          "dl", "dt", "dd", "table", "thead", "tbody", "tfoot", "tr", "pre", "blockquote", "details", "summary", "hr",
          "h1", "h2", "h3", "h4", "h5", "h6", "center", "nav"}
QUIET = {"div", "span", "section", "article", "header", "footer", "aside", "main", "figure", "small", "abbr", "cite", "wbr",
         "mark", "u", "ins", "q", "font", "big", "center", "nav", "time", "tt", "dfn", "samp", "var", "source", "track"}
MARKS = {"b": "**", "strong": "**", "i": "*", "em": "*", "del": "~~", "s": "~~", "strike": "~~"}
WS = r"[ \t\r\n\f]+"                                  # what HTML collapses (a no-break space stays)
LOCAL = re.compile(r"^(?:https?://)?(?:localhost|127\.\d+\.\d+\.\d+|\[::1\]|0\.0\.0\.0)(?::\d+)?(?:/|$)", re.I)


def fence(text, lang=""):
    n = max([3] + [len(m) + 1 for m in re.findall(r"`+", text)])
    return "`" * n + lang + "\n" + text.rstrip("\n") + "\n" + "`" * n


def code_span(text):
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    n = max([0] + [len(m) for m in re.findall(r"`+", text)])
    tick = "`" * (n + 1) if n else "`"
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{tick}{pad}{text}{pad}{tick}"


def url_ok(u):
    return re.sub(r"[ ()<>]", lambda m: "%%%02X" % ord(m.group(0)), u)


def site_url(path):
    return SITE + path if path.startswith("/") else path


class Converter:
    """One article's HTML -> Markdown. `pages` maps article ids to page names; `count` collects what was simplified."""

    def __init__(self, pages, title="", count=None):
        self.pages = pages
        self.count = count if count is not None else collections.Counter()
        self.cell = False
        self.slugs = {}                      # heading id -> GitHub anchor
        self.shift = 0
        self.title = title

    def note(self, what):
        self.count[what] += 1

    # -- headings first, so a link can point forward
    def prepare(self, root):
        heads, seen = [], collections.Counter()
        if self.title:
            seen[gh_slug(self.title)] += 1

        def walk(n):
            for k in n.kids:
                if isinstance(k, Node):
                    if re.fullmatch(r"h[1-6]", k.tag):
                        heads.append(k)
                    walk(k)
        walk(root)
        if heads:
            self.shift = 2 - min(int(h.tag[1]) for h in heads)
        for h in heads:
            s = gh_slug(h.text())
            n = seen[s]
            seen[s] += 1
            if h.get("id"):
                self.slugs[h.get("id")] = s if not n else f"{s}-{n}"

    # -- blocks
    def convert(self, src):
        root = parse_html(src)
        self.prepare(root)
        return self.join(self.blocks(root.kids)).strip() + "\n"

    @staticmethod
    def is_list(b):
        return bool(re.match(r"(?:[-*+]|\d+\.) ", b))

    def join(self, blocks):
        out = []
        for b in blocks:
            if out and self.is_list(out[-1]) and (self.is_list(b) or b.startswith(("```", "    "))):
                out.append("<!-- -->")                 # two lists in a row would run together
            out.append(b)
        return "\n\n".join(out)

    def inline_node(self, k):
        """Text and inline tags go into the paragraph being built; so does an unknown tag that holds only inline things."""
        if isinstance(k, str):
            return True
        if k.tag in ("video", "audio"):
            return False                                    # a player is a line of its own
        if k.tag in INLINE:
            return True
        return k.tag not in BLOCKS and not any(isinstance(x, Node) and not self.inline_node(x) for x in k.kids)

    def blocks(self, kids):
        out, buf = [], []

        def flush():
            s = self.inline(buf).strip(" \n")
            buf.clear()
            if s:
                out.append(self.line_start(s))
        for k in kids:
            if self.inline_node(k):
                buf.append(k)
            else:
                flush()
                out.extend(self.block(k))
        flush()
        return out

    @staticmethod
    def line_start(s):
        """A paragraph that starts like Markdown syntax is escaped, so it stays a paragraph."""
        m = re.match(r"(\d+)([.)])(?:\s|$)", s)
        if m:                                      # a backslash before a digit is not an escape: escape the dot or bracket
            return m.group(1) + "\\" + s[len(m.group(1)):]
        if re.match(r"(?:[#>+-])(?:\s|$)|^(?:-{3,}|={3,}|_{3,})", s):
            return "\\" + s
        return s

    def block(self, n):
        t, cls = n.tag, n.classes()
        if re.fullmatch(r"h[1-6]", t):
            lvl = min(6, max(2, int(t[1]) + self.shift))
            s = " ".join(self.inline(n.kids).split())
            return ["#" * lvl + " " + s] if s else []
        if t in ("ul", "ol"):
            return self.list_block(n)
        if t == "dl":
            return self.dl(n)
        if t == "table":
            return self.table(n)
        if t == "pre":
            return [self.code_block(n.text(), "")]
        if t == "hr":
            return ["---"]
        if t in ("video", "audio"):
            s = self.media(n)
            return [s] if s else []
        if t == "blockquote":
            return self.quote(self.blocks(n.kids))
        if t == "details":
            return self.details(n)
        if t == "figcaption":
            s = self.inline(n.kids).strip(" \n")
            return [("*" + s + "*") if s and "*" not in s[:1] else s] if s else []
        if "flow" in cls:
            steps = [k for k in n.kids if isinstance(k, Node) and "step" in k.classes()]
            if steps:                                   # boxes joined by arrows: "**Record** (soundcheck · takes) → ..."
                parts = []
                for st in steps:
                    lab = [k for k in st.kids if isinstance(k, Node) and k.tag in ("b", "strong")]
                    rest = [k for k in st.kids if k not in lab]
                    s1, s2 = " ".join(self.inline(lab).split()), " ".join(self.inline(rest).split())
                    parts.append(s1 + (f" ({s2})" if s2 and s1 else s2))
                return [" → ".join(p for p in parts if p)]
        if "term" in cls:
            pre = n.find("pre")
            text = (pre or n).text()
            label = n.get("data-label").lower()
            return [self.code_block(text, "bash" if label in ("terminal", "shell") else "")]
        if cls & {"note-box", "warn-box"}:
            inner = self.blocks(n.kids)
            if "warn-box" in cls and inner and not re.match(r"\W*(careful|warning|caution|note)\b", inner[0], re.I):
                inner[0] = "**Careful.** " + inner[0]
            return self.quote(inner)
        if t not in BLOCKS:
            if t not in QUIET and t not in ("#root",):
                self.note(f"tag <{t}> shown as its text")
        return self.blocks(n.kids)

    def code_block(self, text, lang):
        text = text.replace("\r", "")
        if self.cell:
            self.note("code block inside a table cell")
            return "<br>".join(code_span(x) for x in text.split("\n") if x.strip())
        return fence(text, lang)

    def quote(self, blocks):
        if not blocks:
            return []
        body = self.join(blocks)
        return ["\n".join(("> " + ln) if ln else ">" for ln in body.split("\n"))]

    def details(self, n):
        summ = next((k for k in n.kids if isinstance(k, Node) and k.tag == "summary"), None)
        rest = [k for k in n.kids if k is not summ]
        title = " ".join((summ.text() if summ else "Details").split()) or "Details"
        body = self.join(self.blocks(rest))
        if self.cell:
            self.note("details inside a table cell")
            return ["**" + html.escape(title, quote=False) + "** " + body.replace("\n", "<br>")]
        head = "<details open>" if n.get("open") or "open" in n.attrs else "<details>"
        return [f"{head}\n<summary>{html.escape(title, quote=False)}</summary>\n\n{body}\n\n</details>" if body
                else f"{head}\n<summary>{html.escape(title, quote=False)}</summary>\n</details>"]

    @staticmethod
    def indent(text, width, first=""):
        pad = " " * width
        lines = text.split("\n")
        return "\n".join([first + lines[0]] + [(pad + ln) if ln.strip() else "" for ln in lines[1:]])

    def item(self, blocks, marker):
        if not blocks:
            return marker.rstrip()
        parts = [blocks[0]]
        for b in blocks[1:]:
            parts.append(("\n" if (self.is_list(b) or self.is_list(parts[-1])) and not self.cell else "\n\n") + b)
        return self.indent("".join(parts), len(marker), marker)

    def list_block(self, n):
        items = [k for k in n.kids if isinstance(k, Node) and k.tag == "li"]
        stray = [k for k in n.kids if not (isinstance(k, Node) and k.tag == "li") and (isinstance(k, Node) or k.strip())]
        if stray:
            self.note("text inside a list but outside an item")
        if self.cell:
            return ["<br>".join("• " + " ".join(self.inline(li.kids).split()) for li in items)] if items else []
        ordered = n.tag == "ol"
        try:
            start = int(n.get("start") or 1)
        except ValueError:
            start = 1
        out = []
        for i, li in enumerate(items):
            marker = f"{start + i}. " if ordered else "- "
            out.append(self.item(self.blocks(li.kids), marker))
        return ["\n".join(out)] if out else []

    def dl(self, n):
        items, cur = [], None
        for k in n.kids:
            if not isinstance(k, Node):
                continue
            if k.tag == "dt":
                cur = {"term": " ".join(self.inline(k.kids).split()), "defs": []}
                items.append(cur)
            elif k.tag == "dd":
                if cur is None:
                    cur = {"term": "", "defs": []}
                    items.append(cur)
                cur["defs"].append(self.blocks(k.kids))
        out = []
        for it in items:
            blocks = [b for d in it["defs"] for b in d]
            term = it["term"]
            if term and blocks and not self.is_list(blocks[0]) and not blocks[0].startswith("```"):
                blocks[0] = f"**{term.rstrip(':')}**: " + blocks[0]
            elif term:
                blocks = [f"**{term}**"] + blocks
            if self.cell:
                out.append("<br>".join(blocks))
            else:
                out.append(self.item(blocks, "- "))
        return ["<br>".join(out)] if self.cell else (["\n".join(out)] if out else [])

    def table(self, n):
        if self.cell:
            self.note("table inside a table cell (kept as its words)")
            return [" ".join(self.inline([n.text()]).split())]
        rows = []

        def collect(node):
            for k in node.kids:
                if isinstance(k, Node):
                    if k.tag == "tr":
                        rows.append(k)
                    elif k.tag in ("thead", "tbody", "tfoot"):
                        collect(k)
        collect(n)
        if not rows:
            return self.blocks(n.kids)
        grid, held, width = [], {}, 0
        for r, tr in enumerate(rows):
            line, col = [], 0
            for c in [k for k in tr.kids if isinstance(k, Node) and k.tag in ("td", "th")]:
                while held.get((r, col)):
                    line.append(("", None))
                    col += 1
                self.cell = True
                text = self.cell_text(c)
                self.cell = False
                try:
                    span = max(1, min(int(c.get("colspan") or 1), 50))
                    rspan = max(1, min(int(c.get("rowspan") or 1), 50))
                except ValueError:
                    span = rspan = 1
                line.append((text, c.tag == "th"))
                if span > 1:
                    self.note("table cell spanning columns (the extra columns are left empty)")
                if rspan > 1:
                    self.note("table cell spanning rows (the rows below are left empty there)")
                for j in range(span - 1):
                    line.append(("", None))
                for rr in range(1, rspan):
                    for j in range(span):
                        held[(r + rr, col + j)] = True
                col += span
            while held.get((r, col)):
                line.append(("", None))
                col += 1
            grid.append(line)
            width = max(width, len(line))
        for line in grid:
            line.extend([("", None)] * (width - len(line)))
        first = grid[0] if grid else []
        head = first if any(h for _, h in first) and all(h for _, h in first if h is not None) else None
        if head is not None:
            grid = grid[1:]
        else:
            head = [("", None)] * width
        fmt = lambda cells: "| " + " | ".join(t if t else " " for t, _ in cells) + " |"          # noqa: E731
        lines = [fmt(head), "| " + " | ".join("---" for _ in range(width)) + " |"] + [fmt(r) for r in grid]
        return ["\n".join(lines)]

    def cell_text(self, c):
        blocks = self.blocks(c.kids)
        if len(blocks) > 1:
            self.note("several paragraphs or blocks inside a table cell (joined with line breaks)")
        return "<br>".join(b.replace("\n", "<br>") for b in blocks).strip()

    # -- inline
    @staticmethod
    def esc(s):
        s = s.replace("\\", "\\\\")
        s = re.sub(r"([*`\[\]<~$])", r"\\\1", s)
        s = re.sub(r"(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])", r"\\_", s)
        s = re.sub(r"&(?=#?\w+;)", r"\\&", s)
        s = re.sub(r"(?<![\w])#(?=\d)", r"\\#", s)
        s = re.sub(r"(?<![\w])@(?=\w)", r"\\@", s)
        return s

    def inline(self, kids):
        out = []
        for k in kids:
            if isinstance(k, str):
                s = re.sub(WS, " ", k)
                s = self.esc(s)
                out.append(s.replace("|", "\\|") if self.cell else s)
            else:
                out.append(self.inline_tag(k))
        s = "".join(out)
        return re.sub(r" {2,}", " ", s)

    def wrap(self, mark, inner):
        core = inner.strip(" \n")
        if not core:
            return inner
        lead = inner[:len(inner) - len(inner.lstrip(" \n"))]
        trail = inner[len(inner.rstrip(" \n")):]
        return f"{lead}{mark}{core}{mark}{trail}"

    def inline_tag(self, n):
        t = n.tag
        if t == "br":
            return "<br>"
        if t == "code":
            s = n.text().replace("|", "\\|") if self.cell else n.text()
            return code_span(s)
        if t in MARKS:
            inner = self.inline(n.kids)
            if not inner.strip(" \n"):
                return inner
            return self.wrap(MARKS[t], inner)
        if t in ("kbd",):
            return code_span(n.text())
        if t in ("sub", "sup"):
            return f"<{t}>{html.escape(n.text(), quote=False)}</{t}>"
        if t == "span" and "extra" in n.classes():                  # the small "new" after a command's name
            s = " ".join(n.text().split())
            return f"<sup>{html.escape(s, quote=False)}</sup>" if s else ""
        if t == "a":
            return self.link(n)
        if t == "img":
            return self.image(n)
        if t in ("video", "audio"):
            return self.media(n)
        if t not in QUIET and t not in ("span", "mark", "u", "ins", "q", "cite", "small"):
            self.note(f"tag <{t}> shown as its text")
        return self.inline(n.kids)

    def image(self, n):
        src = n.get("src") or n.get("data-src")
        if not src:
            self.note("picture without an address (kept as its description)")
            return self.esc(n.get("alt"))
        alt = re.sub(r"[\[\]\n]", " ", n.get("alt")).strip()
        return f"![{alt}]({url_ok(site_url(src))})"

    def media(self, n):
        kind = "Video" if n.tag == "video" else "Audio"
        src = n.get("src") or n.get("data-src")
        if not src:
            s = n.find("source")
            src = (s.get("src") or s.get("data-src")) if s is not None else ""
        if not src:
            self.note(f"{kind.lower()} without an address (left out)")
            return ""
        label = n.get("aria-label") or n.get("data-label") or posixpath.basename(src.split("?")[0])
        return f"[{kind}: {self.esc(label)}]({url_ok(site_url(src))})"

    def target(self, a):
        """-> (url or None, why not)"""
        j, href = a.get("data-wiki"), a.get("href").strip()
        if j:
            if j in self.pages:
                return self.pages[j], ""
            return None, "link to an article that is not in the wiki"
        j = a.get("data-jump")
        if j:
            return self.heading(j)
        if not href or href == "#":
            return None, "link that goes nowhere"
        if href.startswith("#"):
            key = href[1:]
            if key in self.pages:
                return self.pages[key], ""
            return self.heading(key)
        if LOCAL.match(href) or re.match(r"(?i)(app|hypnomix|javascript|data|file):", href):
            return None, "link to a screen of the app"
        m = re.match(r"/wiki/#([\w-]+)$", href)
        if m:
            return self.pages[m.group(1)] if m.group(1) in self.pages else None, "link to an article that is not in the wiki"
        if href.startswith(("http://", "https://", "mailto:")):
            return href, ""
        if href.startswith("/"):
            return SITE + href, ""
        return None, "link that cannot be followed from the wiki"

    def heading(self, key):
        if key in self.slugs:
            return "#" + self.slugs[key], ""
        return None, "link to a place on the page that is not there"

    def link(self, a):
        inner = self.inline(a.kids).strip(" \n")
        url, why = self.target(a)
        if url is None:
            if why:
                self.note(why + " (kept as its words)")
            return inner
        return f"[{inner or self.esc(url)}]({url_ok(url)})"


# ---------------------------------------------------------------- Markdown that is Markdown already
def split_fences(text):
    """Yield (is_code, line) so links are only fixed outside fenced blocks."""
    mark = None
    for ln in text.split("\n"):
        m = re.match(r"^\s{0,3}(`{3,}|~{3,})", ln)
        if mark is None and m:
            mark = m.group(1)[0] * 3
            yield True, ln
        elif mark is not None:
            yield True, ln
            if re.match(r"^\s{0,3}" + re.escape(mark[0]) + "{3,}\\s*$", ln):
                mark = None
        else:
            yield False, ln


class Passthrough:
    def __init__(self, a, pages, by_src, count):
        self.a, self.pages, self.by_src, self.count = a, pages, by_src, count
        self.dir = posixpath.dirname(a.get("src", ""))

    def fix_target(self, url):
        if not url or url.startswith(("#", "http://", "https://", "mailto:", "//")) or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", url):
            return url
        path, _, frag = url.partition("#")
        full = posixpath.normpath(posixpath.join(self.dir, path))
        if full.startswith("..") or not path:
            self.count["relative link that leaves the repository (kept as written)"] += 1
            return url
        frag = "#" + frag if frag else ""
        if full in self.by_src and self.by_src[full] in self.pages:
            self.count["relative link changed to a wiki page"] += 1
            return self.pages[self.by_src[full]] + frag
        self.count["relative link changed to the file on GitHub"] += 1
        if full.lower().endswith(IMAGE_EXT):
            return RAW + full
        return BLOB + full + frag

    def line(self, ln):
        parts = re.split(r"(`+[^`]*`+)", ln)          # code spans are left alone, except a lone file name
        out = []
        for i, p in enumerate(parts):
            if i % 2:
                if ln.lstrip().startswith("|") and re.search(r"(?<!\\)\|", p):       # a pipe in code splits a table's cell
                    p = re.sub(r"(?<!\\)\|", r"\\|", p)
                    self.count["pipe inside code in a table row escaped"] += 1
                m = re.fullmatch(r"`([^`\s]+)`", p)
                prev = parts[i - 1] if i else ""
                if m and m.group(1) in self.by_src and self.by_src[m.group(1)] in self.pages \
                        and not prev.endswith("[") and not (i + 1 < len(parts) and parts[i + 1].startswith("](")):
                    self.count["file name changed to a link to its wiki page"] += 1
                    out.append(f"[{p}]({self.pages[self.by_src[m.group(1)]]})")
                else:
                    out.append(p)
                continue
            p = re.sub(r"(\]\()([^)\s]+)((?:\s+\"[^\"]*\")?\))", lambda m: m.group(1) + self.fix_target(m.group(2)) + m.group(3), p)
            p = re.sub(r"^(\s{0,3}\[[^\]]+\]:\s*)(\S+)", lambda m: m.group(1) + self.fix_target(m.group(2)), p)
            p = re.sub(r'((?:src|href)=")([^"]+)(")', lambda m: m.group(1) + self.fix_target(m.group(2)) + m.group(3), p)
            p = self.escape_unknown_tags(p)
            out.append(p)
        return "".join(out)

    def escape_unknown_tags(self, p):
        """GitHub removes a tag it does not know, with the words inside it: "<Title> - <Artist>" would read " - ". Written
        with a backslash, the text shows as written. Tags it keeps, comments and <https://...> and <name@host> links stay."""
        def one(m):
            if m.group(1).lower() in HTML_TAGS:
                return m.group(0)
            self.count["text written like a tag escaped, so GitHub keeps it"] += 1
            return "\\" + m.group(0)
        return re.sub(r"(?<!\\)<([A-Za-z][A-Za-z0-9-]*)(?=[\s>/])(?![^<>\n]*@)", one, p)

    def body(self, text, title):
        meta, text = wiki_md.front(text)
        lines, done = [], False
        for code, ln in split_fences(text):
            if code:
                lines.append(ln)
                continue
            if not done and re.match(r"^# \S", ln):
                done = True
                h = re.sub(r"[`*_]", "", ln[2:]).strip().lower()
                if h == re.sub(r"\s*\(readme\)$", "", title.lower()) or h == title.lower():
                    continue                                   # the page's own title says it
                ln = "#" + ln                                  # a different first heading stays, one level down
            lines.append(self.line(ln))
        return "\n".join(lines).strip() + "\n"


# ---------------------------------------------------------------- the pages
def plain(s):
    return " ".join(html.unescape(s or "").split())


def esc_text(s):
    return Converter.esc(plain(s))


def site_link(a):
    return a.get("url") or f"{WIKI_URL}#{a['id']}"


def page_text(a, pages, by_src, count, fixed):
    """One article's Markdown page."""
    here = collections.Counter()
    head = [f"# {esc_text(a['title'])}"]
    kicker = " · ".join(x for x in (plain(a.get("no")), plain(a.get("sub"))) if x)
    if kicker:
        head.append("*" + esc_text(kicker) + "*" if "*" not in kicker else esc_text(kicker))
    src, f = a.get("src") or "", a.get("file") or ""
    if src.endswith(".md") and f and Path(f).is_file() and not a.get("generated"):
        text = Path(f).read_text(encoding="utf-8")
        body = Passthrough(a, pages, by_src, fixed).body(text, a["title"])
        if a["id"].startswith("agent-"):
            m, _ = wiki_md.front(text)
            tools = m.get("tools", "")
            note = "A subagent: Claude Code starts it for one job and it reports back." \
                   + (f" Tools it may use: **{tools}**." if tools else "")
            body = "> " + note + "\n\n" + body
    else:
        conv = Converter(pages, title=a["title"], count=here)
        body = conv.convert(a["html"])
    count.update(here)
    tail = f"---\n\nThe same article on the site: [{site_link(a)}]({site_link(a)})\n"
    return "\n\n".join(head) + "\n\n" + body.rstrip() + "\n\n" + tail, sum(here.values())


def summary(a, limit=330):
    """The article's teaser: its "teaser:" header, else its first real paragraph, cut at a sentence (as the site does,
    but read from the text of the paragraph, so a word in bold is not cut off from the comma after it)."""
    if a.get("teaser"):
        return plain(a["teaser"])
    paras = []

    def walk(n):
        for k in n.kids:
            if isinstance(k, Node):
                if k.tag == "p":
                    paras.append(plain(k.text()))
                else:
                    walk(k)
    walk(parse_html(a.get("html") or ""))
    t = next((p for p in paras if len(p) > 40), paras[0] if paras else plain(a.get("sub")))
    if len(t) > limit:
        cut = _sentence_end(t, limit)
        t = t[:cut + 1] if cut > 80 else t[:limit].rsplit(" ", 1)[0] + "…"
    elif t.endswith(":"):                          # a paragraph that introduces a list is not a teaser: keep the sentences before it
        cut = _sentence_end(t, len(t))
        if cut > 40:
            t = t[:cut + 1]
    return t


_ABBREV = re.compile(r"(?:^|[\s(])(?:Dr|Mr|Mrs|Ms|Prof|St|vs|etc|e\.g|i\.e)\.$")


def _sentence_end(t, limit):
    """The index of the last '.' or '?' that ends a sentence before `limit` (-1 if none): "Dr. " and "e.g. " do not."""
    best = -1
    for m in re.finditer(r"[.?] ", t[:limit]):
        if not _ABBREV.search(t[:m.start() + 1]):
            best = m.start()
    return best


def home_text(arts, pages, version, date):
    out = ["# HypnoMix wiki", "",
           f"This wiki is a copy of [the wiki on the HypnoMix site]({WIKI_URL}), which is also the Wiki tab of the app. "
           f"{len(arts)} pages, in the site's order, each with the start of what it says.", ""]
    group = None
    for a in arts:
        if a["group"] != group:
            group = a["group"]
            out += ["", f"## {esc_text(group)}", ""]
        t = summary(a)
        out.append(f"- [{esc_text(a['title'])}]({pages[a['id']]})" + (f": {esc_text(t)}" if t else ""))
    return "\n".join(out).replace("\n\n\n", "\n\n").strip() + "\n"


def sidebar_text(arts, pages):
    out = [f"**[Home](Home)** · [the site's wiki]({WIKI_URL})", ""]
    groups = []
    for a in arts:
        if not groups or groups[-1][0] != a["group"]:
            groups.append((a["group"], []))
        groups[-1][1].append(a)
    for g, items in groups:
        out.append(f"<details><summary><b>{html.escape(g, quote=False)}</b></summary>")
        out.append("")
        for a in items:
            m = re.match(r"lesson\s*(\d+)$", a.get("no") or "", re.I)
            label = (f"{m.group(1)}. " if m else "") + a["title"]
            out.append(f"- [{esc_text(label)}]({pages[a['id']]})")
        out += ["", "</details>", ""]
    return "\n".join(out).rstrip() + "\n"


def footer_text(version, date):
    built = ", ".join(x for x in ((f"version {version}" if version else ""), (f"sources dated {date}" if date else "")) if x)
    return (f"This wiki mirrors [the wiki on the HypnoMix site]({WIKI_URL}) and is rebuilt from the repository "
            f"automatically: edit the sources there, not these pages (a page or image added by hand here is deleted by the next build)." + (f" Built from {built}." if built else "") + "\n")


def build_pages(arts, version="", date=""):
    """-> ({file name: text}, report). Pure: the same articles give the same text."""
    pages = page_names(arts)
    by_src = {a["src"]: a["id"] for a in arts if a.get("src")}
    count, fixed, files, simplified = collections.Counter(), collections.Counter(), {}, {}
    for a in arts:
        text, n = page_text(a, pages, by_src, count, fixed)
        files[pages[a["id"]] + ".md"] = text
        if n:
            simplified[a["id"]] = n
    files["Home.md"] = home_text(arts, pages, version, date)
    files["_Sidebar.md"] = sidebar_text(arts, pages)
    files["_Footer.md"] = footer_text(version, date)
    report = {"pages": len(arts), "files": len(files), "simplified": sum(count.values()),
              "kinds": dict(sorted(count.items())), "by_article": simplified, "links_fixed": dict(sorted(fixed.items())),
              "names": pages}
    return files, report


# ---------------------------------------------------------------- version and date
def package_version(root=None):
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    f = root / "pyproject.toml"
    try:
        if f.is_file():
            s = f.read_text(encoding="utf-8")
            m = re.search(r'^version = "([^"]+)"', s, re.M)
            if m and re.search(r'^name = "hypnomix"', s, re.M):
                return m.group(1)
    except OSError:
        pass
    try:
        from importlib.metadata import version
        return version("hypnomix")
    except Exception:
        return ""


def source_date(src):
    """The date of the last commit that changed the wiki's sources (UTC), or "" outside git. Never the clock."""
    from hypnomix.app import wiki_build
    try:
        t, _ = wiki_build.commit_time(src)
    except Exception:
        return ""
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d") if t else ""


# ---------------------------------------------------------------- the command
def write_all(out, files):
    out = Path(out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise SystemExit(f"{out} is not empty: give a folder that does not exist yet (this tool writes new files only)")
    out.mkdir(parents=True, exist_ok=True)
    for name in sorted(files):
        (out / name).write_bytes(files[name].encode("utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m hypnomix.app.wiki_github", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="the folder to write the wiki's pages into (new, or empty)")
    ap.add_argument("--src", default=str(W.HERE), help="the wiki source (default: this HypnoMix's)")
    ap.add_argument("--version", default=None, help="the version the footer names (default: pyproject.toml)")
    ap.add_argument("--date", default=None, help="the date the footer names, YYYY-MM-DD (default: the last commit that changed the sources)")
    ap.add_argument("--mapping", default=None, help="also write the article id -> page name list to this JSON file")
    a = ap.parse_args(argv)
    src = Path(a.src)
    arts = W.local(src)
    if not arts:
        sys.exit(f"no articles in {src / 'articles'}")
    if W.COURSE_ERROR:
        sys.exit(f"the teacher-mode course articles could not be built ({W.COURSE_ERROR[0]}): not building the wiki")
    if "commands" not in {x["id"] for x in arts}:
        sys.exit("the command reference could not be built from hypnomix/cli.py: not building the wiki")
    version = a.version if a.version is not None else package_version()
    date = a.date if a.date is not None else source_date(src)
    files, report = build_pages(arts, version, date)
    write_all(a.out, files)
    if a.mapping:
        Path(a.mapping).write_text(json.dumps(report["names"], indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{report['pages']} pages (+ Home, _Sidebar, _Footer) -> {a.out}")
    print(f"simplified: {report['simplified']}" + ("" if not report["kinds"] else " ("
          + "; ".join(f"{n} x {k}" for k, n in report["kinds"].items()) + ")"))
    if report["links_fixed"]:
        print("links fixed in the Markdown pages: " + "; ".join(f"{n} x {k}" for k, n in report["links_fixed"].items()))


if __name__ == "__main__":
    main()
