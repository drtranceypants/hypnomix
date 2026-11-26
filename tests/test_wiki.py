"""The app's Wiki: the sync copies the site's sections safely, and the server hands out articles and media."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hypnomix.app import wiki, wiki_sync

HOME = """<html><body><nav><a href="#install">Install</a></nav>
<section id="install" class="reveal"><h2 class="shimmer">Install</h2><p class="sub">fifteen minutes</p>
<svg class="orn"><use href="#orn"/></svg><script>alert(1)</script>
<p onclick="x()">Run it, then read <a href="#local">the local AI part</a>, <a href="/training/#l3">lesson 3</a>
or <a href="https://ollama.com/download">Ollama</a>.</p>
<div class="term" data-label="setup"><button class="copy">copy</button><pre><span class="p">$</span> hypnomix app</pre></div>
<img src="/assets/training/shot.png" alt="a shot" style="color:red"><iframe src="https://x"></iframe></section>
<section id="local"><h2>Run your own AI</h2><p>Offline.</p></section></body></html>"""
TRAINING = """<html><body><section id="loop"><h2>The loop</h2><p>Six steps.</p></section>
<section id="l3"><span class="lesson-no">lesson 3</span><h2>The first pass</h2><p class="sub">scan · hear</p>
<figure class="shot"><video src="/assets/training/clip.mp4" poster="/assets/training/shot.png"></video></figure>
<details><summary>More</summary><p>Inside &amp; safe.</p></details></section></body></html>"""


class WikiTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.site = Path(self._td.name) / "site"
        (self.site / "training").mkdir(parents=True)
        (self.site / "assets" / "training").mkdir(parents=True)
        (self.site / "index.html").write_text(HOME)
        (self.site / "training" / "index.html").write_text(TRAINING)
        (self.site / "assets" / "training" / "shot.png").write_bytes(b"PNG")
        (self.site / "assets" / "training" / "clip.mp4").write_bytes(bytes(range(100)))
        self.out = Path(self._td.name) / "wiki"
        articles = [("training", "loop", "Training"), ("training", "l3", "Training"), ("home", "install", "Start here"),
                    ("home", "local", "How-to"), ("home", "gone", "How-to")]
        with mock.patch.object(wiki_sync, "ARTICLES", articles), \
                mock.patch.object(sys, "argv", ["x", "--from", str(self.site), "--out", str(self.out)]):
            wiki_sync.main()
        self.data = json.loads((self.out / "articles.json").read_text())
        self.by = {a["id"]: a for a in self.data["articles"]}

    def tearDown(self):
        self._td.cleanup()

    def test_sync_articles(self):
        self.assertEqual([a["id"] for a in self.data["articles"]], ["loop", "l3", "install", "local"])  # gone: skipped
        l3 = self.by["l3"]
        self.assertEqual((l3["title"], l3["sub"], l3["no"], l3["group"]), ("The first pass", "scan · hear", "lesson 3", "Training"))
        self.assertIn('<video src="/wiki/assets/clip.mp4" poster="/wiki/assets/shot.png" controls>', l3["html"])
        self.assertIn("Inside &amp; safe.", l3["html"])
        self.assertEqual(sorted(p.name for p in (self.out / "assets").iterdir()), ["clip.mp4", "shot.png"])

    def test_sync_cleans_and_links(self):
        h = self.by["install"]["html"]
        for bad in ("<script", "alert", "onclick", "<svg", "<button", "style=", "<iframe", "<h2"):
            self.assertNotIn(bad, h)
        self.assertNotIn("fifteen minutes", h)                   # the subtitle is kept apart, not twice
        self.assertIn('<a data-wiki="local" href="#">', h)       # a section in the Wiki stays in the Wiki
        self.assertIn('<a data-wiki="l3" href="#">', h)          # across pages too
        self.assertIn('<a target="_blank" rel="noopener" href="https://ollama.com/download">', h)
        self.assertIn('<div class="term" data-label="setup"><pre><span class="p">$</span> hypnomix app</pre></div>', h)
        self.assertIn('<img src="/wiki/assets/shot.png" alt="a shot">', h)

    def test_server(self):
        with mock.patch.object(wiki, "HERE", self.out):
            wiki._CACHE.clear()
            code, body, _ = wiki.handle_get("/api/wiki", {})
            idx = json.loads(body)
            self.assertEqual(code, 200)
            self.assertEqual([a["id"] for a in idx["articles"]], ["loop", "l3", "install", "local"])
            self.assertNotIn("html", idx["articles"][0])
            code, body, _ = wiki.handle_get("/api/wiki/article", {"id": "l3"})
            self.assertEqual(json.loads(body)["title"], "The first pass")
            self.assertEqual(wiki.handle_get("/api/wiki/article", {"id": "nope"})[0], 404)
            code, body, ctype, head = wiki.handle_get("/wiki/assets/clip.mp4", {}, {"Range": "bytes=10-19"})
            self.assertEqual((code, body, ctype, head["Content-Range"]), (206, bytes(range(10, 20)), "video/mp4", "bytes 10-19/100"))
            self.assertEqual(wiki.handle_get("/wiki/assets/clip.mp4", {}, {"Range": "bytes=-5"})[1], bytes(range(95, 100)))
            self.assertEqual(wiki.handle_get("/wiki/assets/clip.mp4", {}, {"Range": "bytes=200-"})[0], 416)
            self.assertEqual(wiki.handle_get("/wiki/assets/..%2Farticles.json", {})[0], 404)
            self.assertIsNone(wiki.handle_get("/api/other", {}))

    def test_shipped_wiki_is_complete(self):
        """The copy committed with the app: every article present and every image or video it uses is there."""
        d = json.loads((wiki.HERE / "articles.json").read_text())
        self.assertEqual(len(d["articles"]), len(wiki_sync.ARTICLES))
        import re
        used = {m for a in d["articles"] for m in re.findall(r'/wiki/assets/([^"]+)"', a["html"])}
        self.assertTrue(used)
        self.assertEqual(used, {p.name for p in (wiki.HERE / "assets").iterdir()})


if __name__ == "__main__":
    unittest.main()
