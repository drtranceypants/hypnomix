"""Build the website's /wiki/ from the wiki's source files (the same articles the app's Wiki tab shows).

    python -m hypnomix.app.wiki_build --template SITE/wiki-template.html --out SITE/public/wiki

Writes OUT/index.html (every article on one page: a list to search, one article at a time with JavaScript,
all of them without), OUT/articles.json (what every copy of the app loads to stay current) and OUT/assets/
(the images and videos). The template is the site's own page with <!--WIKI--> where the wiki goes, so the
site keeps its look. Python's standard library only: it runs on the website's computer without installing.

    --page SITE/public/index.html    also refresh the short summaries on another page of the site

On such a page, everything between <!--wiki:ID--> and <!--/wiki:ID--> is replaced by a short summary of the
article ID (its "teaser:" header line, else its first paragraph) and a link to it in the wiki; for the FAQ,
the list of questions. So the home page can point into the wiki without keeping its own copy.
"""
import argparse
import datetime
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hypnomix.app import wiki as W   # noqa: E402

STYLE = """<style>
.wiki{scroll-margin-top:70px;display:grid;grid-template-columns:260px 1fr;gap:2.2rem;align-items:start;max-width:1180px;margin:0 auto;padding:0 1rem 3rem}
.wiki aside{position:sticky;top:4.2rem;max-height:calc(100vh - 5rem);overflow:auto;padding-right:.4rem}
.wiki aside input{width:100%;font:inherit;padding:.5rem .7rem;border:1px solid var(--line,#d9d2c4);background:var(--card,#fff);color:inherit}
.wiki aside h4{margin:1.1rem 0 .3rem;font:600 .72rem var(--futura,Jost,sans-serif);letter-spacing:.2em;text-transform:uppercase;color:var(--sea,#4f7c8a)}
.wiki aside a{display:block;padding:.28rem .55rem;color:inherit;text-decoration:none;font-size:.98rem;line-height:1.35}
.wiki aside a:hover,.wiki aside a.on{background:var(--card,#fff);box-shadow:inset 3px 0 0 var(--wine,#8e3f3f)}
.wiki aside a small{color:var(--wine,#8e3f3f);margin-right:.4rem}.wiki aside .none{opacity:.7;padding:.5rem}
.wiki aside [hidden]{display:none!important}.wiki aside .hit{display:block;font-size:.8rem;opacity:.7}
.wiki .wa{background:var(--card,#fff);padding:1.6rem 1.8rem;box-shadow:0 0 0 1px var(--line,#d9d2c4),5px 7px 0 rgba(59,47,43,.1);margin-bottom:2rem;min-width:0}
.wiki .wa .no{font:600 .74rem var(--futura,Jost,sans-serif);letter-spacing:.2em;text-transform:uppercase;color:var(--wine,#8e3f3f)}
.wiki .wa h2.wt{margin:.2rem 0 .3rem;text-align:left;font-size:clamp(1.4rem,3vw,2.1rem);overflow-wrap:anywhere}.wiki .wa > .sub{text-align:left;margin:0 0 1rem}
.wiki .wa img,.wiki .wa video{max-width:100%;height:auto}.wiki .wa .pair{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
.wiki .wa .steps,.wiki .wa .lead,.wiki .wa .note-box,.wiki .wa .warn-box,.wiki .wa .tablewrap{max-width:none}
.wiki .wa .next{display:flex;justify-content:space-between;gap:1rem;margin-top:1.6rem;font-size:.95rem}
.wiki.js .wa{display:none}.wiki.js .wa.on{display:block}
@media (max-width:820px){.wiki{grid-template-columns:1fr}.wiki aside{position:static;max-height:240px}.wiki .wa .pair{grid-template-columns:1fr}}
</style>"""

SCRIPT = """<script>
(function(){
  const box = document.querySelector('.wiki'); if (!box) return; box.classList.add('js');
  const arts = [...box.querySelectorAll('.wa')], links = [...box.querySelectorAll('aside .wlist a')];
  function show(){ const id = decodeURIComponent(location.hash.slice(1)); const a = arts.find(x => x.id === id) || arts[0];
    arts.forEach(x => x.classList.toggle('on', x === a)); links.forEach(l => l.classList.toggle('on', l.getAttribute('href') === '#' + a.id));
    return id && a.id === id; }
  const jump = () => box.scrollIntoView({block: 'start', behavior: 'instant'});
  window.addEventListener('hashchange', () => { if (show()) jump(); });
  if (show()) { if (document.readyState === 'complete') setTimeout(jump, 50); else window.addEventListener('load', () => setTimeout(jump, 50)); }
  const q = document.getElementById('wq'), none = box.querySelector('aside .none');
  q.addEventListener('input', () => { const w = q.value.toLowerCase().trim().split(/\\s+/).filter(Boolean); let n = 0;
    links.forEach(l => { const a = arts.find(x => '#' + x.id === l.getAttribute('href'));
      const ok = !w.length || w.every(t => a.textContent.toLowerCase().includes(t)); l.hidden = !ok; if (ok) n++; });
    box.querySelectorAll('aside h4').forEach(h => { let e = h.nextElementSibling, any = false;
      while (e && e.tagName === 'A') { if (!e.hidden) any = true; e = e.nextElementSibling; } h.hidden = !any; });
    none.hidden = n > 0; });
  q.addEventListener('keydown', e => { if (e.key === 'Enter') { const l = links.find(x => !x.hidden); if (l) location.hash = l.getAttribute('href'); } });
})();
</script>"""


def esc(s):
    return html.escape(s or "", quote=True)


def page(arts, built):
    nav, out, group = [], [], None
    for a in arts:
        if a["group"] != group:
            group = a["group"]
            nav.append(f"<h4>{esc(group)}</h4>")
        n = re.sub(r"^lesson\s*", "", a["no"], flags=re.I)
        nav.append(f'<a href="#{esc(a["id"])}">{f"<small>{esc(n)}</small>" if n else ""}{esc(a["title"])}</a>')
    for i, a in enumerate(arts):
        prev, nxt = (arts[i - 1] if i else None), (arts[i + 1] if i + 1 < len(arts) else None)
        body = re.sub(r'(<div class="term"[^>]*>)', r'\1<button class="copy">copy</button>', a["html"])
        body = re.sub(r'<a data-wiki="([^"]+)" href="#">', r'<a href="#\1">', body)
        out.append(f'<article class="wa" id="{esc(a["id"])}">'
                   + (f'<div class="no">{esc(a["no"])}</div>' if a["no"] else "")
                   + f'<h2 class="wt">{esc(a["title"])}</h2>' + (f'<p class="sub">{esc(a["sub"])}</p>' if a["sub"] else "")
                   + body + '<div class="next">'
                   + (f'<a href="#{esc(prev["id"])}">← {esc(prev["title"])}</a>' if prev else "<span></span>")
                   + (f'<a href="#{esc(nxt["id"])}">{esc(nxt["title"])} →</a>' if nxt else "")
                   + "</div></article>")
    return (STYLE + '\n<div class="wiki"><aside><input type="search" id="wq" placeholder="Search the wiki" '
            'aria-label="Search the wiki"><div class="wlist" role="navigation" aria-label="Wiki articles">' + "".join(nav)
            + '<div class="none" hidden>Nothing matches. Try fewer words.</div></div></aside><div>'
            + "\n".join(out) + f'<p class="sub" style="text-align:left">Updated {esc(built)} · the same articles are in '
            'the hypnomix app\'s Wiki tab.</p></div></div>\n' + SCRIPT + faq_jsonld(arts))


def plain(h):
    t = re.sub(r"<[^>]+>", " ", h)
    t = html.unescape(re.sub(r"\s+", " ", t)).strip()
    return t


def summary(a, limit=330):
    """The article's teaser: its "teaser:" header, else its first real paragraph, cut at a sentence."""
    if a.get("teaser"):
        return a["teaser"]
    paras = [plain(p) for p in re.findall(r"<p(?: [^>]*)?>(.*?)</p>", a["html"], re.S)]
    t = next((p for p in paras if len(p) > 40), paras[0] if paras else a.get("sub", ""))
    if len(t) > limit:
        cut = max(t.rfind(". ", 0, limit), t.rfind("? ", 0, limit))
        t = t[:cut + 1] if cut > 80 else t[:limit].rsplit(" ", 1)[0] + "…"
    return t


def faq_items(a):
    """[(question, answer text)] from the FAQ article's <details>."""
    return [(plain(q), plain(ans)) for q, ans in
            re.findall(r"<details>\s*<summary>(.*?)</summary>(.*?)</details>", a["html"], re.S)]


def teaser(a):
    link = f'/wiki/#{esc(a["id"])}'
    if a["id"] == "faq":
        qs = faq_items(a)
        items = "".join(f'<li><a href="{link}">{esc(q)}</a></li>' for q, _ in qs)
        return (f'<div class="prose paper wiki-teaser"><ul>{items}</ul><p class="more"><a href="{link}">'
                f'All {len(qs)} answers in the wiki →</a></p></div>')
    return (f'<div class="prose paper wiki-teaser"><p>{esc(summary(a))}</p><p class="more"><a href="{link}">'
            f'Read “{esc(a["title"])}” in the wiki →</a></p></div>')


def refresh_page(path, arts):
    """Rewrite every <!--wiki:ID-->…<!--/wiki:ID--> region of a page. -> (changed, ids not in the wiki)."""
    p = Path(path)
    s = p.read_text()
    by = {a["id"]: a for a in arts}
    missing = []

    def sub(m):
        aid = m.group(1)
        if aid not in by:
            missing.append(aid)
            return m.group(0)
        return f"<!--wiki:{aid}-->{teaser(by[aid])}<!--/wiki:{aid}-->"

    new = re.sub(r"<!--wiki:([\w-]+)-->.*?<!--/wiki:\1-->", sub, s, flags=re.S)
    if new != s:
        p.write_text(new)
    return new != s, missing


def faq_jsonld(arts):
    a = next((x for x in arts if x["id"] == "faq"), None)
    if not a:
        return ""
    qs = [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": ans}} for q, ans in faq_items(a)]
    data = json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": qs}, ensure_ascii=False)
    return '<script type="application/ld+json">' + data.replace("</", "<\\/") + "</script>"


def commit_time(root):
    """The last commit that changed the wiki: its articles or the guides' Markdown."""
    paths = [str(root)]
    g = W.guides_dir(root)
    if g is not None:
        paths.append(str(g / "[0-9][0-9]-*.md"))
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%ct %h", "--", *paths], cwd=root,
                           capture_output=True, text=True, timeout=20)
        t, sha = r.stdout.split()
        return int(t), sha
    except Exception:
        return 0, ""


def main():
    ap = argparse.ArgumentParser(prog="python -m hypnomix.app.wiki_build", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", required=True, help="the site's page with <!--WIKI--> where the wiki goes")
    ap.add_argument("--out", required=True, help="the site's /wiki/ folder")
    ap.add_argument("--src", default=str(W.HERE), help="the wiki source (default: this hypnomix's)")
    ap.add_argument("--page", action="append", default=[], help="another page whose <!--wiki:ID--> summaries to refresh")
    a = ap.parse_args()
    src, out = Path(a.src), Path(a.out)
    arts = W.local(src)
    if not arts:
        sys.exit(f"no articles in {src / 'articles'}")
    tpl = Path(a.template).read_text()
    if "<!--WIKI-->" not in tpl:
        sys.exit("the template has no <!--WIKI--> marker")
    t, sha = commit_time(src)
    built = datetime.datetime.fromtimestamp(t or datetime.datetime.now().timestamp()).strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(tpl.replace("<!--WIKI-->", page(arts, built)))
    assets = sorted(p.name for p in (src / "assets").iterdir() if p.is_file())
    (out / "assets").mkdir(exist_ok=True)
    for name in assets:
        s, d = src / "assets" / name, out / "assets" / name
        if not d.exists() or d.read_bytes() != s.read_bytes():
            shutil.copyfile(s, d)
    for old in (out / "assets").iterdir():
        if old.name not in assets:
            old.unlink()
    (out / "articles.json").write_text(json.dumps({
        "commit_time": t, "commit": sha, "built": built, "assets": assets,
        "articles": [{k: v for k, v in x.items() if k != "file"} for x in arts]}, ensure_ascii=False))
    print(f"{len(arts)} articles, {len(assets)} images and videos → {out} (source {sha or 'not in git'})")
    for pg in a.page:
        changed, missing = refresh_page(pg, arts)
        print(f"{pg}: summaries {'updated' if changed else 'already current'}"
              + (f"; not in the wiki: {', '.join(missing)}" if missing else ""))


if __name__ == "__main__":
    main()
