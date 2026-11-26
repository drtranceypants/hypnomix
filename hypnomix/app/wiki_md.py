"""The PDF guides (docs/guides/NN-*.md) as wiki articles, so one Markdown file feeds the PDF, the app and the site.

A guide's front matter gives the article its title (title:), subtitle (subtitle:), and optionally its id
(wiki_id:, else the file name without its number) and home page summary (teaser:). The Markdown is the small
subset the guides use (build.py makes the PDFs from the same files): headings, paragraphs, lists, tables,
```bash blocks, > Tip: / > Careful: notes, `code`, **bold**, *italics* and [links](url).
"""
import html
import re
from pathlib import Path

GROUP = "Guides"


def front(text):
    meta = {}
    if text.startswith("---\n") and "\n---\n" in text[4:]:
        head, text = text[4:].split("\n---\n", 1)
        for ln in head.splitlines():
            if ":" in ln:
                k, v = ln.split(":", 1)
                meta[k.strip().lower()] = v.strip()
    return meta, text


def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<i>\1</i>", s)

    def link(m):
        text, url = m.group(1), html.unescape(m.group(2))
        ext = url.startswith(("http://", "https://"))
        return (f'<a href="{html.escape(url, quote=True)}"' + (' target="_blank" rel="noopener"' if ext else "")
                + f">{text}</a>")
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, s)


SHELL = re.compile(r"^\s*(hypnomix|cd|python3?|uv|pip|brew|git|open|macapp/|ollama|opencode|claude|export|mkdir|ls|cp)\b")


def code(lines, lang):
    """A fenced block -> a .term block: shell lines get a $ prompt and their trailing # comment dimmed."""
    shell = lang in ("bash", "sh", "shell", "zsh") or (not lang and lines and all(SHELL.match(x) or not x.strip()
                                                                                    for x in lines))
    out = []
    for ln in lines:
        if shell and ln.strip() and not ln.lstrip().startswith("#"):
            m = re.match(r"^(.*?)(\s+#\s.*)?$", ln)
            cmd, com = m.group(1), m.group(2) or ""
            out.append('<span class="p">$</span> ' + html.escape(cmd, quote=False)
                       + (f'<span class="c">{html.escape(com, quote=False)}</span>' if com else ""))
        elif shell and ln.lstrip().startswith("#"):
            out.append(f'<span class="c">{html.escape(ln, quote=False)}</span>')
        else:
            out.append(html.escape(ln, quote=False))
    label = "terminal" if shell else (lang or "example")
    return f'<div class="term" data-label="{label}"><pre>' + "\n".join(out) + "</pre></div>"


def to_html(text):
    out, lines, i, intro = [], text.split("\n"), 0, True
    LIST = re.compile(r"^\s*([-*]|\d+\.) ")
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            lang, j = ln[3:].strip().lower(), i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append(code(lines[i + 1:j], lang))
            i = j + 1
            continue
        m = re.match(r"^(#{1,4}) (.*)", ln)
        if m:
            lvl, t = len(m.group(1)), m.group(2).strip()
            if lvl > 1:                                   # the guide's own title is the article's title
                intro = False
                out.append(f'<h3 class="sub-h">{inline(t)}</h3>' if lvl == 2 else f"<h4>{inline(t)}</h4>")
            i += 1
            continue
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|\s*$", lines[i + 1]):
            head = [c.strip() for c in ln.strip().strip("|").split("|")]
            rows, j = [], i + 2
            while j < len(lines) and lines[j].startswith("|"):
                rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")])
                j += 1
            t = '<div class="tablewrap"><table>\n  <tr>' + "".join(f"<th>{inline(h)}</th>" for h in head) + "</tr>\n"
            t += "".join("  <tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>\n" for r in rows)
            out.append(t + "</table></div>")
            i = j
            continue
        if ln.startswith(">"):
            buf, j = [], i
            while j < len(lines) and lines[j].startswith(">"):
                buf.append(lines[j][1:].strip())
                j += 1
            first = buf[0].lower() if buf else ""
            cls = "warn-box" if first.startswith(("careful", "**careful", "warning", "**warning")) else "note-box"
            out.append(f'<p class="{cls}">' + inline(" ".join(buf)) + "</p>")
            i = j
            continue
        if LIST.match(ln):
            ordered = bool(re.match(r"^\s*\d+\. ", ln))
            items, j = [], i
            while j < len(lines) and (LIST.match(lines[j]) or (lines[j].startswith("  ") and lines[j].strip())):
                if LIST.match(lines[j]):
                    items.append(LIST.sub("", lines[j], count=1))
                else:
                    items[-1] += " " + lines[j].strip()
                j += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
            i = j
            continue
        if not ln.strip() or ln.strip().startswith("<!--"):
            i += 1
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(```|#{1,4} |\||>)", lines[i]) \
                and not LIST.match(lines[i]) and not lines[i].strip().startswith("<!--"):
            para.append(lines[i].strip())
            i += 1
        cls = ' class="lead"' if intro and not out else ""
        out.append(f"<p{cls}>" + inline(" ".join(para)) + "</p>")
    return "\n".join(out)


def guide_id(path, meta):
    return meta.get("wiki_id") or re.sub(r"^\d+-", "", Path(path).stem)


def article(path):
    """One guide file -> an article dict (the same keys as wiki.parse)."""
    meta, text = front(Path(path).read_text())
    body = to_html(text)
    num = re.match(r"^(\d+)-", Path(path).name)
    pdf = meta.get("file")
    if pdf:
        body += (f'\n<p class="note-box">This guide is also a PDF: <i>hypnomix {html.escape(pdf)}</i>, in '
                 f"<code>docs/guides/pdf/</code> of your hypnomix folder.</p>")
    plain = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
    aid = guide_id(path, meta)
    from hypnomix.app.wiki import SITE
    return {"id": aid, "group": GROUP, "title": meta.get("title", aid), "sub": meta.get("subtitle", ""),
            "no": f"guide {int(num.group(1))}" if num else "", "teaser": meta.get("teaser", ""), "html": body,
            "text": plain, "url": f"{SITE}/wiki/#{aid}", "file": str(Path(path).resolve())}


def commands_article():
    """The command reference (PDF guide 9), built from hypnomix's own command list each time, so it never lags."""
    from hypnomix import cli
    lines = ["Run `hypnomix` for this list, `hypnomix <command> -h` for a command's full options and examples. "
             "Commands that change a Live set or a REAPER project always write a new one next to the original.", ""]
    n = 0
    for group, cmds in cli.GROUPS:
        lines += [f"## {group}", "", "| command | what it does |", "|---|---|"]
        lines += [f"| `{c}` | {d.replace('|', '/')} |" for c, _, d in cmds]
        lines.append("")
        n += len(cmds)
    body = to_html("\n".join(lines))
    plain = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
    from hypnomix.app.wiki import SITE
    return {"id": "commands", "group": "Reference", "title": "Command reference",
            "sub": f"all {n} commands, by group, in one line each", "no": "",
            "teaser": f"All {n} hypnomix commands, by group, in one line each.", "html": body, "text": plain,
            "url": f"{SITE}/wiki/#commands", "file": "", "generated": True}
