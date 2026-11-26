#!/usr/bin/env python3
"""Build the hypnomix PDF guides from the Markdown files in this folder.

  python docs/guides/build.py            every guide → docs/guides/pdf/*.pdf
  python docs/guides/build.py --html     also keep the HTML next to each PDF

Needs Google Chrome or Chromium (prints the HTML to PDF, headless). No Python packages beyond the standard
library: the Markdown here is a small, known subset (headings, paragraphs, lists, tables, code, quotes).
The command reference (99-commands.md) is generated from hypnomix's own command list each time.
"""
import argparse, html, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "pdf"

CSS = r"""
@page { size: Letter; margin: 0.7in 0.75in 0.8in; }
@page :first { margin: 0; }
:root { --ink:#2b2118; --mute:#6f5f50; --paper:#fbf4e6; --amber:#d9822b; --rust:#b4502f; --teal:#2f7f7a;
        --plum:#6a3f62; --line:#e6d6bb; --code:#f3e7cf; }
* { box-sizing: border-box; }
html, body { background: #fff; }
body { font: 10.5pt/1.5 "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif; color: var(--ink); margin: 0; }
.cover { height: 11in; width: 8.5in; position: relative; overflow: hidden; background: #f6e7c8; page-break-after: always;
         display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
.cover svg.sun { position: absolute; top: -1.6in; left: 50%; transform: translateX(-50%); width: 11in; opacity: .95; }
.cover .stripe { position: absolute; left: 0; right: 0; height: .22in; }
.cover .s1 { bottom: 1.55in; background: var(--amber); } .cover .s2 { bottom: 1.25in; background: var(--rust); }
.cover .s3 { bottom: .95in; background: var(--plum); } .cover .s4 { bottom: .65in; background: var(--teal); }
.cover .card { position: relative; margin-top: 2.6in; background: var(--paper); border: 3px solid var(--ink);
               padding: .45in .6in .4in; width: 5.6in; box-shadow: 10px 10px 0 var(--ink); }
.cover .kicker { letter-spacing: .32em; text-transform: uppercase; font-size: 9pt; color: var(--rust); font-weight: 700; }
.cover h1 { font-family: "Cooper Black", "Cooper Std", Georgia, serif; font-size: 34pt; line-height: 1.05; margin: .14in 0 .12in;
            color: var(--ink); border: 0; padding: 0; }
.cover .sub { color: var(--mute); font-size: 11.5pt; }
.cover .by { margin-top: .22in; font-size: 9pt; letter-spacing: .18em; text-transform: uppercase; color: var(--teal); font-weight: 700; }
.cover .num { position: absolute; bottom: 2.05in; font-family: "Cooper Black", Georgia, serif; font-size: 12pt; color: var(--ink); }
main { padding: 0; }
h1 { font-family: "Cooper Black", "Cooper Std", Georgia, serif; font-weight: normal; font-size: 22pt; color: var(--rust);
     margin: 0 0 .1in; padding-bottom: .06in; border-bottom: 3px solid var(--amber); page-break-before: always; }
main > h1:first-child { page-break-before: avoid; }
h2 { font-family: "Cooper Black", Georgia, serif; font-weight: normal; font-size: 14.5pt; color: var(--teal); margin: .26in 0 .06in;
     page-break-after: avoid; }
h3 { font-size: 11pt; text-transform: uppercase; letter-spacing: .08em; color: var(--plum); margin: .2in 0 .04in; page-break-after: avoid; }
p { margin: .06in 0 .09in; }
a { color: var(--teal); text-decoration: none; }
strong { color: #1d150e; }
ul, ol { margin: .04in 0 .1in; padding-left: .26in; } li { margin: .025in 0; }
code { font: 9pt/1.4 "SF Mono", Menlo, Consolas, monospace; background: var(--code); padding: 0 .04in; border-radius: 3px; }
pre { background: #2b2118; color: #fbecd0; padding: .12in .16in; border-radius: 6px; border-left: 5px solid var(--amber);
      font: 8.6pt/1.45 "SF Mono", Menlo, Consolas, monospace; white-space: pre-wrap; page-break-inside: avoid; margin: .08in 0 .12in; }
pre code { background: none; padding: 0; color: inherit; font: inherit; }
table { border-collapse: collapse; width: 100%; margin: .08in 0 .14in; font-size: 9.2pt; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th { text-align: left; background: var(--ink); color: var(--paper); padding: .05in .08in; font-weight: 600; }
td { padding: .05in .08in; border-bottom: 1px solid var(--line); vertical-align: top; }
tr:nth-child(even) td { background: #f6ecd8; }
blockquote { margin: .1in 0; padding: .08in .14in; border-left: 5px solid var(--teal); background: #eef3ee; color: #23423f; }
blockquote.tip { border-color: var(--amber); background: #fbeed6; color: #5a3a14; }
blockquote.warn { border-color: var(--rust); background: #f8e3da; color: #5e2414; }
.toc { columns: 2; column-gap: .3in; font-size: 9.6pt; margin: .1in 0 .2in; padding: .12in .16in; border: 2px solid var(--ink);
       background: #f6ecd8; }
.toc div { break-inside: avoid; margin: .02in 0; }
.foot { margin-top: .3in; padding-top: .08in; border-top: 1px solid var(--line); color: var(--mute); font-size: 8.5pt; }
"""

SUN = """<svg class="sun" viewBox="0 0 1000 700" xmlns="http://www.w3.org/2000/svg">
<g transform="translate(500,520)">{rays}</g>
<circle cx="500" cy="520" r="190" fill="#d9822b"/><circle cx="500" cy="520" r="150" fill="#e9a64a"/>
<circle cx="500" cy="520" r="110" fill="#f2c46d"/></svg>"""


def sun():
    cols = ["#b4502f", "#6a3f62", "#2f7f7a", "#d9822b"]
    rays = []
    for i in range(36):
        a0, a1 = i * 10, i * 10 + 5
        rays.append(f'<path d="M0 0 L{_p(a0)} L{_p(a1)} Z" fill="{cols[i % 4]}" opacity=".85"/>')
    return SUN.format(rays="".join(rays))


def _p(deg, r=900):
    import math
    t = math.radians(deg - 90)
    return f"{r * math.cos(t):.1f} {r * math.sin(t):.1f}"


# ---------------------------------------------------------------- tiny Markdown
def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def md(text):
    out, lines, i = [], text.split("\n"), 0
    toc = []
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre><code>" + html.escape("\n".join(lines[i + 1:j])) + "</code></pre>")
            i = j + 1; continue
        m = re.match(r"^(#{1,3}) (.*)", ln)
        if m:
            lvl, t = len(m.group(1)), m.group(2)
            anchor = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
            if lvl <= 2:
                toc.append((lvl, t, anchor))
            out.append(f'<h{lvl} id="{anchor}">{inline(t)}</h{lvl}>'); i += 1; continue
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|\s*$", lines[i + 1]):
            head = [c.strip() for c in ln.strip().strip("|").split("|")]
            rows, j = [], i + 2
            while j < len(lines) and lines[j].startswith("|"):
                rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")]); j += 1
            t = "<table><tr>" + "".join(f"<th>{inline(h)}</th>" for h in head) + "</tr>"
            t += "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows) + "</table>"
            out.append(t); i = j; continue
        if ln.startswith(">"):
            j, buf = i, []
            while j < len(lines) and lines[j].startswith(">"):
                buf.append(lines[j][1:].strip()); j += 1
            cls = ""
            if buf and buf[0].lower().startswith(("tip:", "**tip")):
                cls = ' class="tip"'
            elif buf and buf[0].lower().startswith(("careful:", "**careful", "warning:", "**warning")):
                cls = ' class="warn"'
            out.append(f"<blockquote{cls}>" + inline(" ".join(buf)) + "</blockquote>"); i = j; continue
        if re.match(r"^\s*([-*]|\d+\.) ", ln):
            ordered = bool(re.match(r"^\s*\d+\. ", ln))
            items, j = [], i
            while j < len(lines) and (re.match(r"^\s*([-*]|\d+\.) ", lines[j]) or (lines[j].startswith("  ") and lines[j].strip())):
                if re.match(r"^\s*([-*]|\d+\.) ", lines[j]):
                    items.append(re.sub(r"^\s*([-*]|\d+\.) ", "", lines[j]))
                else:
                    items[-1] += " " + lines[j].strip()
                j += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>"); i = j; continue
        if ln.strip() == "<!--toc-->":
            out.append(ln.strip()); i += 1; continue
        if not ln.strip():
            i += 1; continue
        j, buf = i, []
        while j < len(lines) and lines[j].strip() and not re.match(r"^(#|```|\||>|\s*([-*]|\d+\.) )", lines[j]):
            buf.append(lines[j].strip()); j += 1
        out.append("<p>" + inline(" ".join(buf)) + "</p>"); i = j
    return "\n".join(out), toc


def page(meta, body, toc, num):
    t = "".join(f'<div>{"&nbsp;&nbsp;&nbsp;" if l == 2 else ""}<a href="#{a}">{inline(x)}</a></div>' for l, x, a in toc if l == 2)
    body = body.replace("<!--toc-->", f'<div class="toc">{t}</div>', 1)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(meta['title'])}</title>
<style>{CSS}</style></head><body>
<section class="cover">{sun()}<div class="stripe s1"></div><div class="stripe s2"></div><div class="stripe s3"></div>
<div class="stripe s4"></div><div class="card"><div class="kicker">hypnomix · guide {num}</div><h1>{html.escape(meta['title'])}</h1>
<div class="sub">{inline(meta.get('subtitle', ''))}</div><div class="by">made by Dr. Trance</div></div></section>
<main>{body}<div class="foot">hypnomix: free and open source · github.com/drtranceypants/hypnomix · Every command has
<code>hypnomix &lt;command&gt; -h</code> for its full options.</div></main></body></html>"""


def front(text):
    meta = {}
    if text.startswith("---\n"):
        head, text = text[4:].split("\n---\n", 1)
        for ln in head.splitlines():
            if ":" in ln:
                k, v = ln.split(":", 1)
                meta[k.strip()] = v.strip()
    return meta, text


def commands_md():
    sys.path.insert(0, str(HERE.parents[1]))
    from hypnomix import cli
    out = ["---", "title: Command Reference", "subtitle: Every hypnomix command, by group, in one line each", "file: 8 - Command Reference", "---", "",
           "# Every command", "", "Run `hypnomix` for this list, `hypnomix <command> -h` for a command's full options and "
           "examples. Commands that change a Live set always write a new set next to the original.", ""]
    for group, cmds in cli.GROUPS:
        out += [f"## {group}", "", "| command | what it does |", "|---|---|"]
        out += [f"| `{n}` | {d} |" for n, _, d in cmds]
        out.append("")
    return "\n".join(out)


def chrome():
    for c in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium",
              shutil.which("google-chrome") or "", shutil.which("chromium") or "", shutil.which("chrome") or ""):
        if c and Path(c).exists():
            return c
    sys.exit("needs Google Chrome or Chromium to print the PDFs")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", action="store_true")
    ap.add_argument("only", nargs="*", help="guide file names to build (default: all)")
    a = ap.parse_args()
    (HERE / "99-commands.md").write_text(commands_md())
    OUT.mkdir(exist_ok=True)
    exe = chrome()
    srcs = sorted(p for p in HERE.glob("[0-9][0-9]-*.md") if not a.only or p.name in a.only or p.stem in a.only)
    for src in srcs:
        meta, text = front(src.read_text())
        body, toc = md(text)
        num = src.name[:2]
        doc = page(meta, body, toc, "ref" if num == "99" else str(int(num)))
        name = src.stem
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / f"{name}.html"
            h.write_text(doc)
            pdf = OUT / f"hypnomix {meta.get('file', name[3:].replace('-', ' '))}.pdf"
            pdf.unlink(missing_ok=True)
            pr = subprocess.Popen([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--no-margins",
                                   f"--user-data-dir={td}/profile", f"--print-to-pdf={pdf}", h.as_uri()],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            # Chrome sometimes keeps running after printing: stop it once the PDF is complete
            t0, last = time.time(), -1
            while pr.poll() is None and time.time() - t0 < 120:
                time.sleep(0.5)
                size = pdf.stat().st_size if pdf.exists() else -1
                if size > 0 and size == last:
                    pr.terminate()
                    break
                last = size
            if pr.poll() is None:
                pr.kill()
            pr.wait()
            if not pdf.exists():
                sys.exit(f"Chrome did not write {pdf.name}: {(pr.stderr.read() or '')[-400:]}")
            if a.html:
                shutil.copy(h, OUT / f"{name}.html")
        print(f"wrote {pdf.relative_to(HERE.parents[1])}")


if __name__ == "__main__":
    main()
