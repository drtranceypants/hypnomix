"""The wiki: one set of article files for the app's Wiki tab and the website's /wiki/ page."""
import json
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hypnomix.app import wiki, wiki_build, wiki_md

ART = """<!--
title: The first pass
sub: scan · hear
no: lesson 3
group: Training
-->
<p>Run it &amp; read <a data-wiki="l4" href="#">the next one</a>.</p>
<div class="term" data-label="go"><pre><span class="p">$</span> hypnomix app</pre></div>
<figure class="shot"><video src="/wiki/assets/clip.mp4" controls></video></figure>
"""
ART2 = """<!--
title: Decide faster
group: Training
-->
<p>Second.</p>
"""
GUIDE = """---
title: Vocal Things
subtitle: doubles that sit
wiki_id: vocals-guide
teaser: Short.
---

# Vocal Things

Tight stacks are **expensive**, see [the site](https://example.com).

<!--toc-->

## Three ways in

| you have | use |
|---|---|
| files | `hypnomix vocalign` |

```bash
hypnomix vocalign "Lead.wav" "Double.wav"   # align the double
```

> Tip: under ~10 ms reads as one voice.

> Careful: the device is new.

- one
- two
  continued
"""
TEMPLATE = "<html><head><title>t</title></head><body><nav>site</nav><main><!--WIKI--></main></body></html>"


class WikiTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.src = self.root / "wiki"
        (self.src / "articles").mkdir(parents=True)
        (self.src / "assets").mkdir()
        (self.src / "articles" / "01-l3.html").write_text(ART)
        (self.src / "articles" / "02-l4.html").write_text(ART2)
        (self.src / "assets" / "clip.mp4").write_bytes(bytes(range(100)))
        self.home = self.root / "home"
        self.p = [mock.patch.object(wiki, "HERE", self.src), mock.patch.object(wiki, "HOME", self.home),
                  mock.patch.object(wiki, "checkout", lambda: (None, 100, []))]
        for x in self.p:
            x.start()
        wiki._CACHE.clear()
        wiki._LIVE.update(checked=time.time(), busy=False, error=None)      # no network in tests

    def tearDown(self):
        for x in self.p:
            x.stop()
        self._td.cleanup()

    def test_source_files(self):
        arts = wiki.local()
        self.assertEqual([a["id"] for a in arts], ["l3", "l4", "commands"])
        a = arts[0]
        self.assertEqual((a["title"], a["sub"], a["no"], a["group"]), ("The first pass", "scan · hear", "lesson 3", "Training"))
        self.assertTrue(a["html"].startswith("<p>Run it"))
        self.assertIn("Run it & read the next one", a["text"])
        self.assertEqual(a["url"], wiki.SITE + "/wiki/#l3")
        self.assertEqual(arts[1]["sub"], "")

    def test_server_and_media(self):
        code, body, _ = wiki.handle_get("/api/wiki", {})
        idx = json.loads(body)
        self.assertEqual([a["id"] for a in idx["articles"]], ["l3", "l4", "commands"])
        self.assertEqual(idx["about"]["source"], "this computer")
        self.assertNotIn("html", idx["articles"][0])
        a = json.loads(wiki.handle_get("/api/wiki/article", {"id": "l3"})[1])
        self.assertNotIn("file", a)
        self.assertEqual(wiki.handle_get("/api/wiki/article", {"id": "nope"})[0], 404)
        code, body, ctype, head = wiki.handle_get("/wiki/assets/clip.mp4", {}, {"Range": "bytes=10-19"})
        self.assertEqual((code, body, ctype, head["Content-Range"]), (206, bytes(range(10, 20)), "video/mp4", "bytes 10-19/100"))
        self.assertEqual(wiki.handle_get("/wiki/assets/clip.mp4", {}, {"Range": "bytes=-5"})[1], bytes(range(95, 100)))
        self.assertEqual(wiki.handle_get("/wiki/assets/clip.mp4", {}, {"Range": "bytes=200-"})[0], 416)
        self.assertEqual(wiki.handle_get("/wiki/assets/..%2Fx", {})[0], 404)
        self.assertIsNone(wiki.handle_get("/api/other", {}))

    def test_newer_site_copy_wins_unless_you_are_editing(self):
        live = {"commit_time": 200, "articles": [dict(wiki.local()[0], title="From the site")], "assets": []}
        (self.home / "wiki-live").mkdir(parents=True)
        (self.home / "wiki-live" / "articles.json").write_text(json.dumps(live))
        arts, about = wiki.current()
        self.assertEqual((arts[0]["title"], about["source"]), ("From the site", "the website"))
        with mock.patch.object(wiki, "checkout", lambda: (Path("/x"), 100, ["a.html"])):    # unpublished edits
            arts, about = wiki.current()
            self.assertEqual((arts[0]["title"], about["source"]), ("The first pass", "this computer"))
        with mock.patch.object(wiki, "checkout", lambda: (None, 300, [])):                 # this copy is newer
            self.assertEqual(wiki.current()[1]["source"], "this computer")
        wiki.save_settings(live=False)                                                     # switched off
        self.assertEqual(wiki.current()[1]["source"], "this computer")

    def test_build_site(self):
        out = self.root / "site" / "wiki"
        tpl = self.root / "tpl.html"
        tpl.write_text(TEMPLATE)
        with mock.patch.object(sys, "argv", ["x", "--template", str(tpl), "--out", str(out), "--src", str(self.src)]):
            wiki_build.main()
        page = (out / "index.html").read_text()
        self.assertIn("<nav>site</nav><main>", page)
        self.assertIn('<article class="wa" id="l3"><div class="no">lesson 3</div><h2 class="wt">The first pass</h2>', page)
        self.assertIn('<a href="#l4">the next one</a>', page)            # links between articles stay on the page
        self.assertIn('<div class="term" data-label="go"><button class="copy">copy</button><pre>', page)
        self.assertIn('<a href="#l3">← The first pass</a>', page)
        data = json.loads((out / "articles.json").read_text())
        self.assertEqual([a["id"] for a in data["articles"]], ["l3", "l4", "commands"])
        self.assertEqual(data["assets"], ["clip.mp4"])
        self.assertNotIn("file", data["articles"][0])
        self.assertEqual((out / "assets" / "clip.mp4").read_bytes(), bytes(range(100)))

    def test_home_page_summaries(self):
        arts = wiki.local()
        arts[0]["teaser"] = "Short & sweet."
        page = self.root / "home.html"
        page.write_text("<p>top</p><!--wiki:l3-->OLD COPY<!--/wiki:l3--><!--wiki:gone-->keep<!--/wiki:gone--><p>end</p>")
        changed, missing = wiki_build.refresh_page(page, arts)
        s = page.read_text()
        self.assertTrue(changed)
        self.assertEqual(missing, ["gone"])
        self.assertNotIn("OLD COPY", s)
        self.assertIn("<!--wiki:l3--><div class=\"prose paper wiki-teaser\"><p>Short &amp; sweet.</p>", s)
        self.assertIn('<a href="/wiki/#l3">Read “The first pass” in the wiki →</a>', s)
        self.assertIn("<!--wiki:gone-->keep<!--/wiki:gone--><p>end</p>", s)
        self.assertEqual(wiki_build.refresh_page(page, arts), (False, ["gone"]))     # run again: nothing changes
        arts[0]["teaser"] = ""
        self.assertTrue(wiki_build.summary(arts[0]).startswith("Run it & read the next one"))
        faq = {"id": "faq", "title": "FAQ", "html": "<details><summary>Is it free?</summary><div><p>Yes.</p></div></details>"}
        self.assertEqual(wiki_build.faq_items(faq), [("Is it free?", "Yes.")])
        self.assertIn('"name": "Is it free?"', wiki_build.faq_jsonld([faq]))

    def test_guides_are_articles(self):
        gdir = self.src / "guides"
        gdir.mkdir()
        (gdir / "03-vocal-things.md").write_text(GUIDE)
        (gdir / "99-commands.md").write_text("---\ntitle: Commands\n---\n# Commands\n")   # generated: left out
        wiki._CACHE.clear()
        arts = wiki.local()
        self.assertEqual([a["id"] for a in arts], ["l3", "l4", "vocals-guide", "commands"])
        g = arts[2]
        self.assertEqual((g["group"], g["title"], g["sub"], g["no"], g["teaser"]),
                         ("Guides", "Vocal Things", "doubles that sit", "guide 3", "Short."))
        h = g["html"]
        self.assertNotIn("<h1", h)
        self.assertIn('<p class="lead">Tight stacks are <b>expensive</b>, see <a href="https://example.com" '
                      'target="_blank" rel="noopener">the site</a>.</p>', h)
        self.assertIn('<h3 class="sub-h" id="s-three-ways-in">Three ways in</h3>', h)
        self.assertIn("<td><code>hypnomix vocalign</code></td>", h)
        self.assertIn('<span class="p">$</span> hypnomix vocalign "Lead.wav" "Double.wav"'
                      '<span class="c">   # align the double</span>', h)
        self.assertIn('<p class="note-box">Tip: under ~10 ms reads as one voice.</p>', h)
        self.assertIn('<p class="warn-box">Careful: the device is new.</p>', h)
        self.assertIn("<ul><li>one</li><li>two continued</li></ul>", h)
        self.assertNotIn("also a PDF", h)
        (self.src / "articles" / "03-vocals-guide.html").write_text("<!--\ntitle: Mine\n-->\n<p>x</p>")
        wiki._CACHE.clear()
        self.assertEqual([a["title"] for a in wiki.local() if a["id"] == "vocals-guide"], ["Mine"])  # a file wins

    def test_command_reference_comes_from_the_code(self):
        from hypnomix import cli
        c = wiki_md.commands_article()
        names = [n for _, cmds in cli.GROUPS for n, _, _ in cmds]
        self.assertEqual((c["id"], c["group"], c.get("generated")), ("commands", "Reference", True))
        self.assertIn(f"all {len(names)} commands", c["sub"])
        for n in names:
            self.assertIn(f"<td><code>{n}</code></td>", c["html"])
        self.assertIn("commands", [a["id"] for a in wiki.local()])
        self.assertFalse(wiki.article("commands")["editable"])          # nothing to edit: change the code instead

    def test_docs_are_articles(self):
        ddir = self.src / "docs"
        (ddir / "guides").mkdir(parents=True)
        (ddir / "LIVE.md").write_text("# Working inside Live\n\nThe probe. See `docs/guides/03-x.md`.\n\n---\n\n## Limits\n\n- one\n    more\n")
        (ddir / "guides" / "03-x.md").write_text("---\ntitle: X guide\n---\n# X\n\nBody.\n")
        (self.src / "articles" / "05-live.html").write_text("<!--\ntitle: Taken\n-->\n<p>x</p>")
        wiki._CACHE.clear()
        arts = wiki.local()
        self.assertEqual([a["id"] for a in arts], ["l3", "l4", "live", "x", "live-doc", "commands"])
        d = next(a for a in arts if a["id"] == "live-doc")                 # id taken by an article: -doc
        self.assertEqual((d["group"], d["title"], d["no"]), ("Docs", "Working inside Live", "docs/LIVE.md"))
        self.assertIn('<a data-wiki="x" href="#"><code>docs/guides/03-x.md</code></a>', d["html"])   # linked
        self.assertIn("<hr>", d["html"])
        self.assertIn("<ul><li>one more</li></ul>", d["html"])

    def test_section_links_scroll_within_the_article(self):
        h = wiki_md.to_html("# T\n\n1. [The workflow, at a glance](#1-the-workflow-at-a-glance)\n\n## 1. The workflow, at a glance\n\nText.\n")
        self.assertIn('<a href="#" data-jump="s-1-the-workflow-at-a-glance">The workflow, at a glance</a>', h)
        self.assertIn('<h3 class="sub-h" id="s-1-the-workflow-at-a-glance">1. The workflow, at a glance</h3>', h)

    def test_skills_are_articles(self):
        sk = self.src / "skills" / "mix-engineer"
        sk.mkdir(parents=True)
        (sk / "SKILL.md").write_text("---\nname: mix-engineer\ndescription: Turn stems into a song. Use when someone hands over stems.\n---\n\n# Mix engineer\n\nSteps. Read `docs/LIVE.md`.\n")
        wiki._CACHE.clear()
        k = next(a for a in wiki.local() if a["id"] == "skill-mix-engineer")
        self.assertEqual((k["group"], k["title"], k["no"], k["src"]),
                         ("AI: Claude Code skills and subagent", "Mix engineer", "skills/mix-engineer/SKILL.md", "skills/mix-engineer/SKILL.md"))
        self.assertEqual(k["sub"], "Turn stems into a song. Use when someone hands over stems.")
        self.assertEqual(k["teaser"], k["sub"])
        self.assertEqual(k["url"], wiki.SITE + "/wiki/#skill-mix-engineer")
        self.assertIn("<p class=\"lead\">Steps.", k["html"])
        ag = self.src / "agents"
        ag.mkdir()
        (ag / "hypnomix-scanner.md").write_text("---\nname: hypnomix-scanner\ndescription: Runs one scan group.\ntools: Bash, Read\n---\n\nYou run one part.\n")
        wiki._CACHE.clear()
        arts = wiki.local()
        self.assertEqual([a["id"] for a in arts if a["group"] == "AI: Claude Code skills and subagent"], ["skill-mix-engineer", "agent-hypnomix-scanner"])
        g = arts[[a["id"] for a in arts].index("agent-hypnomix-scanner")]
        self.assertEqual((g["title"], g["sub"], g["src"]), ("Subagent: hypnomix-scanner", "Runs one scan group.", "agents/hypnomix-scanner.md"))
        self.assertIn("Tools it may use: <b>Bash, Read</b>", g["html"])

    def test_links_between_files(self):
        arts = [{"id": "app-doc", "src": "docs/APP.md", "html": ""},
                {"id": "readme", "src": "README.md",
                 "html": '<p><a href="docs/APP.md">the app</a>, <a href="GUIDE.md#x">guide</a>, <code>docs/APP.md</code>, '
                         '<a href="https://example.com/a.md">web</a></p>'}]
        h = wiki_md.link_files(arts)[1]["html"]
        self.assertIn('<a data-wiki="app-doc" href="#">the app</a>', h)
        self.assertIn(f'<a href="{wiki_md.REPO}GUIDE.md#x" target="_blank" rel="noopener">guide</a>', h)
        self.assertIn('<a data-wiki="app-doc" href="#"><code>docs/APP.md</code></a>', h)
        self.assertIn('<a href="https://example.com/a.md">web</a>', h)

    def test_every_doc_ships_with_the_app(self):
        """Each docs/*.md is listed in pyproject.toml, so an installed hypnomix has the same wiki."""
        root = Path(wiki.__file__).resolve().parents[2]
        toml = (root / "pyproject.toml").read_text()
        self.assertIn('"skills" = "hypnomix/app/wiki/skills"', toml)
        self.assertIn('"agents" = "hypnomix/app/wiki/agents"', toml)
        for n in wiki_md.ROOT_FILES:
            self.assertIn(f'"{n}" = "hypnomix/app/wiki/docs/{n}"', toml)
        for f in sorted((root / "docs").glob("[A-Z]*.md")):
            self.assertIn(f'"docs/{f.name}" = "hypnomix/app/wiki/docs/{f.name}"', toml,
                          f"add docs/{f.name} to [tool.hatch.build.targets.wheel.force-include]")

    def test_every_command_has_an_article(self):
        """Keep the wiki current: a new command needs a hand-written article (a guide, a doc, README...) that
        shows how to use it, not only its line in the generated command reference."""
        import re
        from hypnomix import cli
        wiki._CACHE.clear()
        with mock.patch.object(wiki, "HERE", Path(wiki.__file__).with_name("wiki")):
            text = " ".join(a["html"] for a in wiki.local() if not a.get("generated"))
        missing = [n for _, cmds in cli.GROUPS for n, _, _ in cmds
                   if not re.search(r"hypnomix " + re.escape(n) + r"\b|<code>" + re.escape(n) + r"</code>", text)]
        self.assertEqual(missing, [], "document these commands in docs/guides/, docs/ or README.md")

    def test_every_top_level_document_is_in_the_wiki(self):
        root = Path(wiki.__file__).resolve().parents[2]
        self.assertEqual(sorted(f.name for f in root.glob("*.md")), sorted(wiki_md.ROOT_FILES),
                         "add the new file to wiki_md.ROOT_FILES and to pyproject.toml's force-include")

    def test_whole_articles_on_other_pages(self):
        page = self.root / "home.html"
        page.write_text("<section id=\"l3\"><h2>x</h2><!--wiki-full:l3-->OLD<!--/wiki-full:l3--><div class=\"demo\">keep</div></section>")
        changed, missing = wiki_build.refresh_page(page, wiki.local())
        s = page.read_text()
        self.assertTrue(changed)
        self.assertNotIn("OLD", s)
        self.assertIn('<a href="/wiki/#l4">the next one</a>', s)                         # wiki links go to the wiki
        self.assertIn('<div class="term" data-label="go"><button class="copy">copy</button><pre>', s)
        self.assertIn('<!--/wiki-full:l3--><div class="demo">keep</div>', s)             # the rest stays
        self.assertEqual(wiki_build.refresh_page(page, wiki.local())[0], False)

    def test_command_count_on_other_pages(self):
        page = self.root / "home.html"
        page.write_text("<p>all <!--wiki:commands-count-->83<!--/wiki:commands-count--> commands</p>")
        arts = wiki.local()
        n = re.search(r"all (\d+) commands", next(a for a in arts if a["id"] == "commands")["sub"]).group(1)
        wiki_build.refresh_page(page, arts)
        self.assertIn(f"all <!--wiki:commands-count-->{n}<!--/wiki:commands-count--> commands", page.read_text())

    def test_shipped_wiki_is_complete(self):
        """The wiki that ships with the app: every image or video an article uses is there, and nothing extra."""
        import re
        real = Path(wiki.__file__).with_name("wiki")
        arts = [wiki.parse(f) for f in sorted((real / "articles").glob("*.html"))]
        guides = [wiki_md.article(f) for f in wiki.guide_files(real)]
        self.assertGreaterEqual(len(guides), 8)
        self.assertIn("reaper", [g["id"] for g in guides])               # guide 8 keeps the REAPER article's id
        arts += guides
        self.assertGreaterEqual(len(arts), 20)
        self.assertEqual(len({a["id"] for a in arts}), len(arts))
        used = {m for a in arts for m in re.findall(r'/wiki/assets/([^"]+)"', a["html"])}
        self.assertEqual(used, {p.name for p in (real / "assets").iterdir()})
        from hypnomix.app import teacher
        ids = {a["id"] for a in arts} | {a["id"] for a in teacher.wiki_all()}          # the teacher-mode articles are generated
        for a in arts:
            for target in re.findall(r'data-wiki="([^"]+)"', a["html"]):
                self.assertIn(target, ids, f"{a['id']} links to a missing article {target}")


class Organised(unittest.TestCase):
    """The wiki is organised by DAW, then by how you connect an AI, then courses, guides and reference."""
    def test_groups_in_order_and_placed(self):
        from hypnomix.app import wiki as W
        arts = W.local()
        groups = list(dict.fromkeys(a["group"] for a in arts))
        known = [g for g in W.GROUP_ORDER if g in groups]
        self.assertEqual([g for g in groups if g in W.GROUP_ORDER], known)          # each group once, in order
        self.assertEqual(groups[0], "Start here")
        by = {a["id"]: a["group"] for a in arts}
        self.assertEqual(by["reaper"], W.DAW_REAPER)
        self.assertEqual(by["inside-live"], W.DAW_LIVE)
        self.assertEqual(by["ardour"], W.DAW_ARDOUR)
        self.assertEqual(by["other-daws"], W.DAW_OTHER)
        self.assertEqual(by["assistant"], W.AI_KEY)
        self.assertEqual(by["agents"], W.AI_AGENT)
        self.assertEqual(by["local"], W.AI_LOCAL)
        self.assertEqual(by["agents-doc"], W.AI_AGENT)

    def test_unknown_group_stays_with_the_article_before_it(self):
        from hypnomix.app import wiki as W
        arts = [dict(id="t", group="Training"), dict(id="x", group="Something new"), dict(id="s", group="Start here")]
        self.assertEqual([a["id"] for a in W.organise(arts)], ["s", "t", "x"])


if __name__ == "__main__":
    unittest.main()
