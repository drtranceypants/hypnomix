"""The wiki: one set of article files for the app's Wiki tab and the website's /wiki/ page."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hypnomix.app import wiki, wiki_build

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
        self.assertEqual([a["id"] for a in arts], ["l3", "l4"])
        a = arts[0]
        self.assertEqual((a["title"], a["sub"], a["no"], a["group"]), ("The first pass", "scan · hear", "lesson 3", "Training"))
        self.assertTrue(a["html"].startswith("<p>Run it"))
        self.assertIn("Run it & read the next one", a["text"])
        self.assertEqual(a["url"], wiki.SITE + "/wiki/#l3")
        self.assertEqual(arts[1]["sub"], "")

    def test_server_and_media(self):
        code, body, _ = wiki.handle_get("/api/wiki", {})
        idx = json.loads(body)
        self.assertEqual([a["id"] for a in idx["articles"]], ["l3", "l4"])
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
        self.assertEqual([a["id"] for a in data["articles"]], ["l3", "l4"])
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

    def test_shipped_wiki_is_complete(self):
        """The wiki that ships with the app: every image or video an article uses is there, and nothing extra."""
        import re
        real = Path(wiki.__file__).with_name("wiki")
        arts = [wiki.parse(f) for f in sorted((real / "articles").glob("*.html"))]
        self.assertGreaterEqual(len(arts), 20)
        self.assertEqual(len({a["id"] for a in arts}), len(arts))
        used = {m for a in arts for m in re.findall(r'/wiki/assets/([^"]+)"', a["html"])}
        self.assertEqual(used, {p.name for p in (real / "assets").iterdir()})
        ids = {a["id"] for a in arts}
        for a in arts:
            for target in re.findall(r'data-wiki="([^"]+)"', a["html"]):
                self.assertIn(target, ids, f"{a['id']} links to a missing article {target}")


if __name__ == "__main__":
    unittest.main()
