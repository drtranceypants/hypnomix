"""The GitHub wiki mirror: hypnomix/app/wiki_github.py builds the pages, .github/workflows/wiki.yml publishes them.

The pages are checked here as files (names, links, tables, bytes); how GitHub draws them cannot be checked offline.
"""
import collections
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hypnomix.app import wiki, wiki_build, wiki_github as G, wiki_md
from tests.test_repo_rules import home_paths_in, names_in

REPO = Path(__file__).resolve().parent.parent
REAL = Path(wiki.__file__).with_name("wiki")
SPECIAL = {"Home.md", "_Sidebar.md", "_Footer.md"}


def real_articles():
    wiki._CACHE.clear()
    return wiki.local(REAL)


def conv(html, pages=None, title=""):
    c = G.Converter(pages if pages is not None else {}, title=title)
    return c.convert(html), c.count


def outside_code(text):
    """The Markdown with fenced blocks and inline code spans taken out."""
    keep, mark = [], None
    for ln in text.split("\n"):
        m = re.match(r"^\s{0,3}(`{3,}|~{3,})", ln)
        if mark is None and m:
            mark = m.group(1)[0]
            continue
        if mark is not None:
            if re.match(r"^\s{0,3}" + re.escape(mark) + r"{3,}\s*$", ln):
                mark = None
            continue
        keep.append(re.sub(r"(`+)[^`]*?\1", "", ln))
    return "\n".join(keep)


def links_in(text):
    return re.findall(r"(?<!\\)\]\(([^)\s]+)\)", outside_code(text))


def anchors_of(text):
    seen, out = collections.Counter(), set()
    for ln in outside_code(text).split("\n"):
        m = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", ln)
        if m:
            t = re.sub(r"[`*_]|\\", "", re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", m.group(1)))
            s = G.gh_slug(t)
            n = seen[s]
            seen[s] += 1
            out.add(s if not n else f"{s}-{n}")
    return out


class Built(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.arts = real_articles()
        cls.files, cls.report = G.build_pages(cls.arts, "9.9.9", "2001-02-03")
        cls.names = cls.report["names"]

    def pages(self):
        return {k: v for k, v in self.files.items() if k not in SPECIAL}


class Mirror(Built):
    def test_the_site_build_and_the_wiki_have_the_same_articles_one_page_each(self):
        tpl = Path(tempfile.mkdtemp()) / "t.html"
        tpl.write_text("<html><!--WIKI--></html>", encoding="utf-8")
        out = tpl.parent / "site"
        with mock.patch.object(sys, "argv", ["wiki_build", "--template", str(tpl), "--out", str(out)]), \
                contextlib.redirect_stdout(io.StringIO()):
            wiki_build.main()
        site = [a["id"] for a in json.loads((out / "articles.json").read_text(encoding="utf-8"))["articles"]]
        self.assertGreater(len(site), 100)
        self.assertEqual(sorted(site), sorted(self.names), "an article has no wiki page, or a page has no article")
        self.assertEqual(sorted(self.pages()), sorted(n + ".md" for n in self.names.values()))
        self.assertEqual(len(self.pages()), len(site), "one page per article, no more")
        self.assertEqual(sorted(self.files), sorted(self.pages().keys() | SPECIAL))

    def test_the_home_page_and_the_teasers_do_not_repeat_the_disclosure(self):
        """The old name is said once per surface, in the page about HypnoMix Studio: not in the front door's teaser for it."""
        home = self.files["Home.md"]
        line = next(ln for ln in home.split("\n") if "(HypnoMix-DAW)" in ln)
        self.assertNotIn("Ar" + "dour", line)

    def test_no_page_name_says_ardour(self):
        """A page's file name is its title and its address on GitHub: the old name stays out of both (the ids stay as they are)."""
        self.assertEqual([k for k in self.files if "ardour" in k.lower()], [])
        self.assertEqual([n for n in self.names.values() if "ardour" in n.lower()], [])
        self.assertEqual(self.names["ardour"], "HypnoMix-DAW")
        self.assertEqual(self.names["learn-ardour-mix"], "Learn-HypnoMix-DAW-mix")
        self.assertEqual(self.names["tour-ardour"], "Tour-HypnoMix-DAW")
        links = [t for text in self.files.values() for t in re.findall(r"\]\(([\w-]+)(?:#[^)]*)?\)", text)]
        self.assertEqual(sorted({t for t in links if "ardour" in t.lower()}), [])
        self.assertEqual(G.page_name("ardour"), "HypnoMix-DAW")

    def test_it_has_a_page_for_each_kind_the_site_has(self):
        ids = set(self.names)
        for want in ("what", "l3", "faq", "commands", "glossary", "getting-started", "readme", "contributing",
                     "skill-first-pass", "learn-live", "tour-reaper", "learn-ardour-mix"):
            self.assertIn(want, ids)

    def test_the_site_order_and_groups_are_the_home_pages(self):
        home = self.files["Home.md"]
        heads = re.findall(r"(?m)^## (.+)$", home)
        groups = []
        for a in self.arts:
            if not groups or groups[-1] != a["group"]:
                groups.append(a["group"])
        self.assertEqual(heads, [G.esc_text(g) for g in groups])
        order = [self.names[a["id"]] for a in self.arts]
        self.assertEqual(re.findall(r"(?m)^- \[[^\n]*?\]\(([\w-]+)\)", home), order)

    def test_no_two_pages_share_a_name_and_every_name_is_one_github_accepts(self):
        low = [n.lower() for n in self.names.values()] + ["home", "_sidebar", "_footer"]
        self.assertEqual(len(low), len(set(low)), "two pages share a name (a wiki's pages are not case sensitive)")
        for n in self.names.values():
            self.assertRegex(n, r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
            self.assertNotIn(n.lower(), ("home", "_sidebar", "_footer"))

    def test_a_page_name_comes_from_the_id_and_never_from_the_title(self):
        arts = [dict(a, title=a["title"] + " renamed") for a in self.arts]
        self.assertEqual(G.page_names(arts), self.names)
        self.assertEqual(G.page_names(list(reversed(self.arts))), self.names)
        fewer = [a for a in self.arts if a["id"] != "faq"]
        self.assertEqual(G.page_names(fewer), {k: v for k, v in self.names.items() if k != "faq"})
        self.assertEqual(G.page_name("l3"), "Lesson-3")
        self.assertEqual(G.page_name("learn-live-mix"), "Learn-live-mix")

    def test_a_reserved_or_clashing_id_gets_another_name(self):
        arts = [{"id": i} for i in ("home", "sidebar", "_footer", "Foo", "foo", "l3", "lesson-3")]
        names = G.page_names(arts)
        low = [v.lower() for v in names.values()]
        self.assertEqual(len(set(low)), len(low))
        self.assertNotIn("home", low)
        self.assertNotIn("_footer", low)
        self.assertEqual(G.page_names(arts), names)
        self.assertEqual(G.page_name("a b/c:d?"), "A-b-c-d")

    def test_every_internal_link_goes_to_a_page_and_a_place_that_exist(self):
        have = {n[:-3]: anchors_of(t) for n, t in self.files.items()}
        bad = []
        for name, text in self.files.items():
            here = name[:-3]
            for target in links_in(text):
                if re.match(r"(?i)(https?:|mailto:)", target):
                    continue
                page, _, frag = target.partition("#")
                page = page or here
                if page not in have or (frag and frag not in have[page]):
                    bad.append((name, target))
        self.assertEqual(bad, [])

    def test_there_are_links_between_pages_and_none_to_the_apps_own_page_ids(self):
        n = sum(1 for t in self.files.values() for x in links_in(t) if x in self.names.values())
        self.assertGreater(n, 1000)
        for name, text in self.files.items():
            self.assertNotIn("data-wiki", text, name)
            self.assertNotIn("](#)", text, name)

    def test_home_and_the_sidebar_list_every_page_once(self):
        for special in ("Home.md", "_Sidebar.md"):
            c = collections.Counter(x for x in links_in(self.files[special]) if x in self.names.values())
            self.assertEqual(sorted(c), sorted(self.names.values()), special)
            self.assertEqual([k for k, n in c.items() if n != 1], [], special)

    def test_home_gives_each_article_one_line_with_its_teaser(self):
        home = self.files["Home.md"]
        lines = [ln for ln in home.split("\n") if ln.startswith("- [")]
        self.assertEqual(len(lines), len(self.arts))
        for a, ln in zip(self.arts, lines):
            self.assertIn(f"({self.names[a['id']]})", ln)
            self.assertTrue(len(ln) > len(self.names[a["id"]]) + 8, ln)       # a teaser follows the link
        faq = next(a for a in self.arts if a["id"] == "faq")
        self.assertEqual(G.summary({"teaser": "Short & sweet."}), "Short & sweet.")
        self.assertTrue(G.summary(faq))

    def test_the_footer_is_one_line_with_the_site_the_version_and_the_date(self):
        f = self.files["_Footer.md"]
        self.assertEqual(f.count("\n"), 1)
        self.assertIn(G.WIKI_URL, f)
        self.assertIn("9.9.9", f)
        self.assertIn("2001-02-03", f)
        self.assertIn("added by hand here is deleted by the next build", f)
        bare = G.footer_text("", "")
        self.assertEqual(bare.count("\n"), 1)
        self.assertNotIn("Built from", bare)
        self.assertNotRegex(bare, r"\d{4}-\d\d-\d\d")

    def test_every_page_ends_with_a_link_to_the_same_article_on_the_site(self):
        for a in self.arts:
            text = self.files[self.names[a["id"]] + ".md"]
            last = text.rstrip("\n").split("\n")[-1]
            self.assertIn(f"{G.WIKI_URL}#{a['id']}", last, a["id"])
            self.assertTrue(text.startswith("# "), a["id"])

    def test_the_sidebar_is_compact_and_folds_each_group(self):
        s = self.files["_Sidebar.md"]
        self.assertEqual(s.count("<details>"), s.count("</details>"))
        self.assertEqual(s.count("<details>"), len({a["group"] for a in self.arts}))
        self.assertTrue(s.startswith("**[Home](Home)**"))
        self.assertIn("[3. The first pass](Lesson-3)", s)

    def test_the_converter_simplifies_next_to_nothing_in_the_real_wiki(self):
        """Today it simplifies nothing. A few spanning cells or a stray tag in a new article are said in the build's
        report and are fine; a converter that starts to lose a lot is not."""
        self.assertLess(self.report["simplified"], 25, self.report["kinds"])
        self.assertGreater(sum(self.report["links_fixed"].values()), 20)

    def test_tables_keep_every_row_the_width_of_its_header(self):
        bad, tables = [], 0
        for name, text in self.files.items():
            lines = outside_code_lines(text)
            for i, ln in enumerate(lines):
                if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\| ?:?-{3,}", lines[i + 1]):
                    tables += 1
                    n = len(re.findall(r"(?<!\\)\|", ln))
                    j = i + 1
                    while j < len(lines) and lines[j].startswith("|"):
                        if len(re.findall(r"(?<!\\)\|", lines[j])) != n:
                            bad.append((name, j + 1))
                        j += 1
        self.assertGreater(tables, 100)
        self.assertEqual(bad, [])

    def test_converted_pages_hold_no_raw_html_beyond_what_github_draws(self):
        md = {self.names[a["id"]] + ".md" for a in self.arts
              if (a.get("src") or "").endswith(".md") and a.get("file") and not a.get("generated")}
        bad = []
        for name, text in self.pages().items():
            if name in md:
                continue
            for tag in re.findall(r"(?<!\\)<(/?[A-Za-z!][\w-]*)", outside_code(text)):
                if tag.lstrip("/").lower() not in ("details", "summary", "br", "sup", "sub", "!--"):
                    bad.append((name, tag))
        self.assertEqual(bad, [])

    def test_no_picture_or_media_points_at_the_page_itself(self):
        for name, text in self.files.items():
            for src in re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", text):
                self.assertTrue(src.startswith("https://"), (name, src))
            for src in re.findall(r"\[(?:Video|Audio): [^\]]*\]\(([^)\s]+)\)", text):
                self.assertTrue(src.startswith("https://"), (name, src))
        self.assertIn("[Video: ", self.files["Lesson-3.md"])
        self.assertIn(f"![", self.files["App.md"])


def outside_code_lines(text):
    return outside_code(text).split("\n")


class Clean(Built):
    def test_no_page_names_a_fingerprinted_product_or_a_home_folder(self):
        for name, text in self.files.items():
            self.assertEqual(names_in(text), set(), name)
            self.assertEqual(home_paths_in(text), [], name)

    def test_the_same_input_gives_the_same_bytes(self):
        again, report = G.build_pages(real_articles(), "9.9.9", "2001-02-03")
        self.assertEqual(again, self.files)
        self.assertEqual(report["names"], self.names)
        with tempfile.TemporaryDirectory() as t:
            a, b = Path(t) / "a", Path(t) / "b"
            for d in (a, b):
                with contextlib.redirect_stdout(io.StringIO()):
                    G.main(["--out", str(d), "--version", "9.9.9", "--date", "2001-02-03"])
            names = sorted(p.name for p in a.iterdir())
            self.assertEqual(names, sorted(p.name for p in b.iterdir()))
            self.assertEqual(names, sorted(self.files))
            for n in names:
                self.assertEqual((a / n).read_bytes(), (b / n).read_bytes(), n)
                self.assertEqual((a / n).read_bytes(), self.files[n].encode("utf-8"), n)
                self.assertNotIn(b"\r", (a / n).read_bytes())

    def test_the_footer_never_reads_the_clock(self):
        with mock.patch("time.time", side_effect=AssertionError("clock")), \
                mock.patch.object(G.datetime, "datetime", wraps=G.datetime.datetime) as d:
            d.now.side_effect = AssertionError("clock")
            d.utcnow.side_effect = AssertionError("clock")
            files, _ = G.build_pages(self.arts, "1.2.3", "2020-01-02")
        self.assertIn("2020-01-02", files["_Footer.md"])

    def test_the_command_refuses_a_folder_that_is_not_empty_and_says_so_in_a_sentence(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "x.md").write_text("x", encoding="utf-8")
            with self.assertRaises(SystemExit) as e:
                G.main(["--out", t])
            self.assertIn("not empty", str(e.exception))
            self.assertEqual(sorted(os.listdir(t)), ["x.md"])

    def test_the_command_reports_what_it_simplified_and_writes_the_mapping(self):
        with tempfile.TemporaryDirectory() as t:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                G.main(["--out", str(Path(t) / "w"), "--mapping", str(Path(t) / "map.json"), "--version", "1", "--date", "2000-01-01"])
            self.assertIn("simplified: 0", out.getvalue())
            self.assertIn("pages (+ Home, _Sidebar, _Footer)", out.getvalue())
            m = json.loads((Path(t) / "map.json").read_text(encoding="utf-8"))
            self.assertEqual(m, self.names)

    def test_it_builds_without_numpy(self):
        """The website's wiki is built on a machine with no numpy; so is this one (and the workflow's)."""
        code = ("import sys\n"
                "class Block:\n"
                "    def find_spec(self, name, path=None, target=None):\n"
                "        if name.split('.')[0] in ('numpy', 'scipy', 'soundfile', 'librosa'):\n"
                "            raise ModuleNotFoundError(name)\n"
                "sys.meta_path.insert(0, Block())\n"
                "from hypnomix.app import wiki_github as G\n"
                "G.main(sys.argv[1:])\n"
                "assert not any(m.split('.')[0] in ('numpy', 'scipy', 'soundfile', 'librosa') for m in sys.modules)\n")
        with tempfile.TemporaryDirectory() as t:
            r = subprocess.run([sys.executable, "-c", code, "--out", str(Path(t) / "w"), "--version", "9.9.9", "--date", "2001-02-03"],
                               capture_output=True, text=True, encoding="utf-8", timeout=300, cwd=str(REPO))
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            made = {p.name: p.read_bytes() for p in (Path(t) / "w").iterdir()}
        self.assertEqual(sorted(made), sorted(self.files))
        self.assertEqual(made["Home.md"], self.files["Home.md"].encode("utf-8"))

    def test_a_wiki_without_its_command_reference_or_course_is_not_built(self):
        with tempfile.TemporaryDirectory() as t:
            with mock.patch.object(wiki, "COURSE_ERROR", ["ValueError: boom"]), self.assertRaises(SystemExit) as e:
                G.main(["--out", str(Path(t) / "w")])
            self.assertIn("course", str(e.exception))
            some = [a for a in self.arts if a["id"] != "commands"]
            with mock.patch.object(wiki, "local", return_value=some), self.assertRaises(SystemExit) as e:
                G.main(["--out", str(Path(t) / "w")])
            self.assertIn("command reference", str(e.exception))
            self.assertFalse((Path(t) / "w").exists())


class Converter(unittest.TestCase):
    def test_paragraphs_emphasis_and_links(self):
        md, n = conv('<p>One <b>bold</b>, <i>italic</i> and <strong>strong</strong> '
                     '<a href="https://example.org/a b">a link</a>.</p><p>Two</p>')
        self.assertEqual(md, "One **bold**, *italic* and **strong** [a link](https://example.org/a%20b).\n\nTwo\n")
        self.assertEqual(sum(n.values()), 0)

    def test_spaces_stay_outside_the_marks_and_empty_marks_vanish(self):
        self.assertEqual(conv("<p>a<b> b </b>c<i></i>d</p>")[0], "a **b** cd\n")

    def test_tables(self):
        md, n = conv('<div class="tablewrap"><table><tr><th>a</th><th>b | c</th></tr>'
                     '<tr><td>1</td><td><code>x|y</code> and more</td></tr><tr><td>3</td><td></td></tr></table></div>')
        self.assertEqual(md, "| a | b \\| c |\n| --- | --- |\n| 1 | `x\\|y` and more |\n| 3 |   |\n")
        self.assertEqual(sum(n.values()), 0)

    def test_a_table_without_a_header_row_gets_an_empty_one(self):
        md, _ = conv("<table><tr><td>1</td><td>2</td></tr></table>")
        self.assertEqual(md, "|   |   |\n| --- | --- |\n| 1 | 2 |\n")

    def test_table_cells_with_lists_paragraphs_spans_and_short_rows(self):
        md, n = conv('<table><thead><tr><th>k</th><th>v</th><th>w</th></tr></thead><tbody>'
                     '<tr><td colspan="2">wide</td><td>x</td></tr>'
                     '<tr><td rowspan="2">tall</td><td><ul><li>one</li><li>two</li></ul></td><td><p>p1</p><p>p2</p></td></tr>'
                     '<tr><td>below</td><td>z</td></tr><tr><td>short</td></tr></tbody></table>')
        rows = md.strip().split("\n")
        self.assertEqual({r.count("|") for r in rows}, {4})                    # every row has three cells
        self.assertIn("| wide |   | x |", md)
        self.assertIn("• one<br>• two", md)
        self.assertIn("p1<br>p2", md)
        self.assertIn("|   | below | z |", md)                                   # the row under a tall cell keeps its place
        self.assertEqual(sum(n.values()), 3)                                     # colspan, rowspan, several blocks: said, not hidden
        self.assertTrue(any("columns" in k for k in n) and any("rows" in k for k in n))

    def test_a_table_inside_a_table_keeps_its_words_and_says_so(self):
        md, n = conv("<table><tr><th>a</th></tr><tr><td><table><tr><td>in</td></tr></table></td></tr></table>")
        self.assertIn("| in |", md)
        self.assertEqual(sum(n.values()), 1)

    def test_lists_and_nested_lists(self):
        md, _ = conv("<ul><li>a<ul><li>b<ol><li>c</li><li>d</li></ol></li></ul></li><li>e</li></ul>")
        self.assertEqual(md, "- a\n  - b\n    1. c\n    2. d\n- e\n")

    def test_an_ordered_list_keeps_its_start_and_an_item_can_hold_paragraphs_and_code(self):
        md, _ = conv('<ol start="3"><li><p>first</p><p>second</p></li><li>x<pre>a\nb</pre></li></ol>')
        self.assertEqual(md, "3. first\n\n   second\n4. x\n\n   ```\n   a\n   b\n   ```\n")

    def test_two_lists_in_a_row_do_not_run_together(self):
        md, _ = conv("<ul><li>a</li></ul><ul><li>b</li></ul>")
        self.assertEqual(md, "- a\n\n<!-- -->\n\n- b\n")

    def test_items_without_closing_tags(self):
        md, _ = conv("<ul><li>a<li>b<ul><li>c</ul><li>d</ul><dl><dt>t<dd>d</dl>")
        self.assertEqual(md, "- a\n- b\n  - c\n- d\n\n<!-- -->\n\n- **t**: d\n")

    def test_code_with_angle_brackets_and_markdown_characters(self):
        md, _ = conv("<p>Run <code>hypnomix &lt;command&gt; -h</code> and <code>a `b` c</code> or <code>`</code></p>"
                     "<pre>if a &lt; b &amp;&amp; c &gt; d:\n    print('*x*')\n```\nend</pre>"
                     '<div class="term" data-label="terminal"><pre><span class="p">$</span> hypnomix app <span class="c"># opens</span></pre></div>')
        self.assertIn("`hypnomix <command> -h`", md)
        self.assertIn("``a `b` c``", md)
        self.assertIn("`` ` ``", md)
        self.assertIn("````\nif a < b && c > d:\n    print('*x*')\n```\nend\n````", md)
        self.assertIn("```bash\n$ hypnomix app # opens\n```", md)

    def test_text_that_looks_like_markdown_is_escaped(self):
        md, _ = conv("<p>*star* _under_ [x] a<span>b</span> ~3 $5 #12 @name 1_000 snake_case &amp;amp; &lt;tag&gt; \\ back</p>")
        self.assertIn("\\*star\\* \\_under\\_ \\[x\\] ab \\~3 \\$5 \\#12 \\@name 1_000 snake_case \\&amp; \\<tag> \\\\ back", md)
        for start in ("# not a heading", "> not a quote", "- not a list", "+ x", "--- x"):
            self.assertTrue(conv(f"<p>{start.replace('>', '&gt;')}</p>")[0].startswith("\\"), start)
        self.assertTrue(conv("<p>1. not a list</p>")[0].startswith("1\\. not a list"))      # a backslash before a digit shows

    def test_entities_and_non_ascii_survive(self):
        md, _ = conv("<p>caf&eacute; &mdash; &copy; &#8594; 日本語 ñ 🎉 &nbsp;x</p>")
        self.assertEqual(md, "café — © → 日本語 ñ 🎉 \u00a0x\n")
        self.assertEqual(md.encode("utf-8").decode("utf-8"), md)

    def test_headings_are_shifted_so_the_page_title_is_the_only_h1(self):
        md, _ = conv("<h3>One</h3><p>x</p><h4>Two</h4><h3>One</h3>", title="Title")
        self.assertEqual(md, "## One\n\nx\n\n### Two\n\n## One\n")
        self.assertTrue(conv("<h2>A</h2>")[0].startswith("## A"))
        self.assertTrue(conv("<h1>A</h1><h2>B</h2>")[0].startswith("## A\n\n### B"))

    def test_a_jump_link_points_at_the_headings_github_anchor(self):
        md, n = conv('<h3 id="s-a">Setup: step 1</h3><p><a href="#" data-jump="s-a">back</a> '
                     '<a href="#" data-jump="s-b">forward</a></p><h3 id="s-b">Setup: step 1</h3>', title="Setup step 1")
        self.assertIn("[back](#setup-step-1-1)", md)                     # the page title took the first one
        self.assertIn("forward", md)
        self.assertIn("[forward](#setup-step-1-2)", md)
        md, n = conv('<p><a href="#" data-jump="s-missing">x</a></p>')
        self.assertEqual(md, "x\n")
        self.assertEqual(sum(n.values()), 1)

    def test_links_between_articles_and_to_screens_of_the_app(self):
        pages = {"l4": "Lesson-4", "faq": "FAQ"}
        md, n = conv('<p><a data-wiki="l4" href="#">next</a> <a href="#faq">faq</a> <a href="/wiki/#l4">l4</a> '
                     '<a data-wiki="gone" href="#">gone</a> <a href="http://127.0.0.1:8791/#review">the Review screen</a> '
                     '<a href="http://localhost:8791/">here</a> <a href="#">nowhere</a> <a href="/download/">dl</a> '
                     '<a href="mailto:a@b.org">mail</a> <a href="https://example.org/x(1)">p</a></p>', pages)
        self.assertEqual(md, "[next](Lesson-4) [faq](FAQ) [l4](Lesson-4) gone the Review screen here nowhere "
                             "[dl](https://hypnomix.bradfieldenterprises.org/download/) [mail](mailto:a@b.org) "
                             "[p](https://example.org/x%281%29)\n")
        self.assertEqual(sum(n.values()), 4)
        self.assertEqual(len(n), 3)

    def test_pictures_video_and_audio_point_at_the_site(self):
        md, n = conv('<figure><img src="/wiki/assets/a.png" alt="A [shot]"><figcaption>Cap</figcaption></figure>'
                     '<video src="/wiki/assets/v.mp4" controls aria-label="The demo"></video>'
                     '<video data-src="/assets/x/w.mp4" poster="/p.jpg"></video>'
                     '<audio controls><source src="/wiki/assets/s.mp3" type="audio/mpeg"></audio>'
                     '<video controls></video><img alt="no source">')
        s = "https://hypnomix.bradfieldenterprises.org"
        self.assertIn(f"![A shot]({s}/wiki/assets/a.png)", md)
        self.assertIn("*Cap*", md)
        self.assertIn(f"[Video: The demo]({s}/wiki/assets/v.mp4)", md)
        self.assertIn(f"[Video: w.mp4]({s}/assets/x/w.mp4)", md)
        self.assertIn(f"[Audio: s.mp3]({s}/wiki/assets/s.mp3)", md)
        self.assertEqual(sum(n.values()), 2)                                  # a video and a picture with no address

    def test_definition_lists_details_and_quotes(self):
        md, _ = conv("<dl><dt>Term:</dt><dd>one</dd><dt>Two</dt><dd><p>a</p><p>b</p></dd></dl>"
                     "<details open><summary>Why <b>so</b>?</summary><p>Because.</p><ul><li>x</li></ul></details>"
                     "<blockquote><p>quoted</p><p>twice</p></blockquote>"
                     '<p class="warn-box">Check it</p><div class="note-box"><p>Nb</p></div>')
        self.assertIn("- **Term**: one\n- **Two**: a\n\n  b\n", md)
        self.assertIn("<details open>\n<summary>Why so?</summary>\n\nBecause.\n\n- x\n\n</details>", md)
        self.assertIn("> quoted\n>\n> twice", md)
        self.assertIn("> **Careful.** Check it", md)
        self.assertIn("> Nb", md)

    def test_unknown_markup_keeps_its_words_and_is_counted(self):
        md, n = conv("<p>a <blink>b</blink> c</p><marquee><p>d</p></marquee><ruby>e</ruby>")
        self.assertEqual(md, "a b c\n\nd\n\ne\n")
        self.assertEqual(sum(n.values()), 3)
        self.assertTrue(all("shown as its text" in k for k in n))

    def test_a_workflow_diagram_reads_as_a_line(self):
        md, _ = conv('<div class="flow"><div class="step"><b>Scan</b><span>read only</span></div><span class="arrow">→</span>'
                     '<div class="step"><b>Fix</b><span>new files</span></div></div>')
        self.assertEqual(md, "**Scan** (read only) → **Fix** (new files)\n")

    def test_a_small_label_after_a_name_is_set_up_and_not_glued(self):
        md, _ = conv('<dl><dt><code>app</code><span class="extra">new</span></dt><dd>Window.</dd></dl>')
        self.assertEqual(md, "- **`app`<sup>new</sup>**: Window.\n")

    def test_garbage_does_not_stop_it(self):
        md, _ = conv("<p>a</b></div><ul><li>x</p><table><tr><td>1<th>2</table><details></details><dl><dd>orphan</dl>")
        self.assertIn("a", md)
        self.assertIn("orphan", md)


class Passthrough(unittest.TestCase):
    def make(self, text, src="docs/GUIDE-X.md", title="Title", ids=None):
        pages = {"live": "Live", "readme": "README"}
        by_src = {"docs/LIVE.md": "live", "README.md": "readme"}
        fixed = collections.Counter()
        a = {"src": src, "id": "x"}
        return G.Passthrough(a, pages, by_src, fixed).body(text, title), fixed

    def test_front_matter_and_the_pages_own_title_go_and_a_different_first_heading_stays_one_level_down(self):
        md, _ = self.make("---\ntitle: Title\n---\n\n# Title\n\nBody\n\n# Other\n")
        self.assertEqual(md, "Body\n\n# Other\n")
        md, _ = self.make("# Welcome\n\nBody\n")
        self.assertEqual(md, "## Welcome\n\nBody\n")
        md, _ = self.make("# hypnomix\n\nBody\n", title="hypnomix (README)")
        self.assertEqual(md, "Body\n")

    def test_relative_links_go_to_the_wiki_or_to_github_and_the_rest_is_left_alone(self):
        md, fixed = self.make("[a](LIVE.md#x) [b](../README.md) [c](other.md) [d](#here) [e](https://x.org/y) "
                              "![i](shot.png) <img src=\"pic.jpg\"> [f](../../outside.md)\n\n[ref]: LIVE.md\n", src="docs/X.md")
        self.assertIn("[a](Live#x)", md)
        self.assertIn("[b](README)", md)
        self.assertIn(f"[c]({G.BLOB}docs/other.md)", md)
        self.assertIn("[d](#here) [e](https://x.org/y)", md)
        self.assertIn(f"![i]({G.RAW}docs/shot.png)", md)
        self.assertIn(f'src="{G.RAW}docs/pic.jpg"', md)
        self.assertIn("[f](../../outside.md)", md)
        self.assertIn("[ref]: Live", md)
        self.assertGreaterEqual(sum(fixed.values()), 6)

    def test_code_is_not_touched_except_a_lone_file_name_that_has_a_page(self):
        md, _ = self.make("```\n[a](LIVE.md)\n```\n\nSee `docs/LIVE.md` and `[a](LIVE.md)` and [`docs/LIVE.md`](docs/LIVE.md).\n", src="README.md")
        self.assertIn("```\n[a](LIVE.md)\n```", md)
        self.assertIn("See [`docs/LIVE.md`](Live) and `[a](LIVE.md)` and [`docs/LIVE.md`](Live).", md)

    def test_a_pipe_in_code_inside_a_table_row_is_escaped_so_the_cell_stays_whole(self):
        md, fixed = self.make("| a | b |\n|---|---|\n| `x|y` | `z` |\n\nProse `p|q`.\n")
        self.assertIn("| `x\\|y` | `z` |", md)
        self.assertIn("Prose `p|q`.", md)
        self.assertEqual(fixed["pipe inside code in a table row escaped"], 1)
        md, _ = self.make("| `x\\|y` | z |\n")
        self.assertIn("`x\\|y`", md)
        self.assertNotIn("\\\\|", md)

    def test_text_written_like_a_tag_that_github_would_remove_is_escaped(self):
        md, fixed = self.make('Name it "<Artist> - <Title> (24-bit).wav", `<Keep> in code`, <kbd>Ctrl</kbd>, <br>, '
                              '<https://x.org/y>, <me@x.org>, <details>, <!-- c --> and a < b.\n')
        self.assertIn('"\\<Artist> - \\<Title> (24-bit).wav"', md)
        self.assertIn("`<Keep> in code`", md)
        for kept in ("<kbd>Ctrl</kbd>", "<br>", "<https://x.org/y>", "<me@x.org>", "<details>", "<!-- c -->", "a < b."):
            self.assertIn(kept, md)
        self.assertEqual(fixed["text written like a tag escaped, so GitHub keeps it"], 2)

    def test_the_real_pages_have_no_unknown_tag_outside_code(self):
        files, _ = G.build_pages(real_articles())
        bad = {}
        for name, text in files.items():
            for code, ln in G.split_fences(text):
                if code:
                    continue
                ln = re.sub(r"(`+)[^`]*\1", "", ln)
                for t in re.findall(r"(?<!\\)<([A-Za-z][A-Za-z0-9-]*)(?=[\s>/])(?![^<>\n]*@)", ln):
                    if t.lower() not in G.HTML_TAGS:
                        bad.setdefault(name, set()).add(t)
        self.assertEqual(bad, {})
        self.assertIn("\\<Artist> - \\<Title>", files["Mastering.md"])

    def test_a_paragraph_that_starts_like_a_numbered_list_is_escaped_so_no_stray_backslash_shows(self):
        self.assertEqual(G.Converter.line_start("1. one"), "1\\. one")
        self.assertEqual(G.Converter.line_start("12) x"), "12\\) x")
        self.assertEqual(G.Converter.line_start("- x"), "\\- x")
        self.assertEqual(G.Converter.line_start("2026 was"), "2026 was")

    def test_agents_and_skills_become_pages_from_their_files(self):
        arts = real_articles()
        files, _ = G.build_pages(arts)
        agent = files["Agent-hypnomix-scanner.md"]
        self.assertIn("> A subagent: Claude Code starts it for one job", agent)
        self.assertNotIn("\ntools: ", agent)
        skill = files["Skill-first-pass.md"]
        self.assertNotIn("\nname: first-pass", skill)
        self.assertEqual(skill.count("\n# "), 0)                                # the one H1 is the page title


class Teasers(unittest.TestCase):
    def art(self, html):
        return {"html": html, "sub": "", "id": "t"}

    def test_a_title_like_Dr_is_not_the_end_of_a_sentence(self):
        a = self.art("<p>" + "A tool that does a great many useful things for people who mix. " * 3 + "It was built by Dr. Quill, "
                     + "who tried every one of them for years and kept the ones that helped. " * 2 + "</p>")
        t = G.summary(a)
        self.assertFalse(t.rstrip("…").endswith("Dr."), t)
        self.assertTrue(t.endswith("."), t)

    def test_a_paragraph_that_ends_with_a_colon_is_cut_before_it(self):
        t = G.summary(self.art("<p>It does the whole job in one pass, with nothing paid. Five ways in, one engine:</p>"))
        self.assertEqual(t, "It does the whole job in one pass, with nothing paid.")
        self.assertEqual(G.summary(self.art("<p>Only a lead-in, with no sentence before it:</p>")), "Only a lead-in, with no sentence before it:")

    def test_no_teaser_on_the_home_page_ends_mid_sentence(self):
        files, _ = G.build_pages(real_articles())
        for ln in files["Home.md"].split("\n"):
            if ln.startswith("- ["):
                self.assertNotRegex(ln.rstrip(), r"(?:\bDr\.|:)$", ln)


class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (REPO / ".github" / "workflows" / "wiki.yml").read_text(encoding="utf-8")
        cls.y = parse_yaml(cls.text)
        cls.job = cls.y["jobs"]["mirror"]
        cls.steps = cls.job["steps"]
        cls.script = "\n".join(s.get("run", "") for s in cls.steps)

    def test_it_runs_on_a_push_to_main_that_touches_the_sources_and_by_hand(self):
        on = self.y["on"]
        self.assertEqual(on["push"]["branches"], ["main"])
        self.assertIn("workflow_dispatch", on)
        paths = on["push"]["paths"]
        for want in ("hypnomix/app/wiki/**", "hypnomix/app/wiki*.py", "hypnomix/app/teacher.py", "hypnomix/app/teach_audio.py",
                     "hypnomix/app/lessons/**", "docs/**", "hypnomix/cli.py", "README.md"):
            self.assertIn(want, paths)
        for n in wiki_md.ROOT_FILES:
            self.assertIn(n, paths, f"{n} is a wiki source")
        self.assertIn("skills/**", paths)
        self.assertIn("agents/**", paths)

    def test_every_file_the_wiki_is_built_from_is_watched(self):
        paths = self.y["on"]["push"]["paths"]
        rx = [re.compile("^" + re.escape(p).replace(r"\*\*", ".*").replace(r"\*", "[^/]*") + "$") for p in paths]
        files = {a["file"] for a in real_articles() if a.get("file")}
        files |= {str(REPO / "hypnomix" / "app" / n) for n in ("wiki.py", "wiki_build.py", "wiki_md.py", "wiki_github.py",
                                                              "teacher.py", "teach_audio.py")}
        files |= {str(p) for p in (REPO / "hypnomix" / "app" / "lessons").glob("*.py")}
        files.add(str(REPO / "hypnomix" / "cli.py"))
        self.assertGreater(len(files), 60)
        unwatched = sorted(os.path.relpath(f, REPO) for f in files
                           if not any(r.match(os.path.relpath(f, REPO).replace(os.sep, "/")) for r in rx))
        self.assertEqual(unwatched, [])

    def test_least_permissions_and_a_concurrency_group(self):
        self.assertEqual(self.y["permissions"], {})
        self.assertEqual(self.job["permissions"], {"contents": "write"})
        self.assertEqual(self.y["concurrency"]["cancel-in-progress"], "false")
        # a run from another branch has a group of its own, so it can't replace a pending run from main
        self.assertEqual(self.y["concurrency"]["group"], "wiki-${{ github.ref == 'refs/heads/main' && 'main' || github.run_id }}")
        # only this repository's own main publishes: a fork's push would fail with the wiki-is-not-set-up error
        self.assertEqual(self.job["if"], "github.repository == 'drtranceypants/hypnomix' && github.ref == 'refs/heads/main'")
        self.assertNotIn("pull_request", self.y["on"])

    def test_the_footer_date_does_not_depend_on_a_shallow_clone(self):
        first = [s for s in self.steps if s.get("uses", "").startswith("actions/checkout")][0]
        self.assertEqual(first["with"]["fetch-depth"], "0")

    def test_the_header_says_a_page_added_by_hand_is_deleted(self):
        head = self.text.split("\nname: wiki")[0]
        self.assertIn("added by hand", head)
        self.assertIn("image", head)

    def test_every_action_is_pinned_to_a_commit(self):
        uses = [s["uses"] for s in self.steps if "uses" in s]
        self.assertGreaterEqual(len(uses), 2)
        for u in uses:
            self.assertRegex(u, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$", u)
            self.assertRegex(next(s for s in self.text.split("\n") if u in s), r"# v\d+\.\d+\.\d+$")
        known = {m for f in (REPO / ".github" / "workflows").glob("*.yml") if f.name != "wiki.yml"
                 for m in re.findall(r"uses: ([\w.-]+/[\w.-]+@[0-9a-f]{40})", f.read_text(encoding="utf-8"))}
        # a pin written from memory cannot be checked offline: every action here is one the other workflows already use
        self.assertEqual([u for u in uses if u not in known], [])
        self.assertIn("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", known, "the same checkout pin as the other workflows")
        self.assertIn("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", uses)

    def test_it_builds_the_pages_checks_out_the_wiki_repository_and_pushes_only_a_change(self):
        out = [s for s in self.steps if s.get("uses", "").startswith("actions/checkout")]
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["with"]["persist-credentials"], "false")
        self.assertEqual(out[1]["with"]["repository"], "${{ github.repository }}.wiki")
        self.assertFalse(any(s.get("uses", "").startswith("actions/setup-python@") for s in self.steps))   # stdlib only
        self.assertIn("python3 -m hypnomix.app.wiki_github --out", self.script)
        self.assertIn("-not -name .git -exec rm -rf {} +", self.script)              # pages that no longer exist go, nothing else stays
        self.assertIn("git diff --cached --quiet", self.script)
        self.assertIn("git push origin HEAD", self.script)
        self.assertIn("github-actions[bot]", self.script)
        self.assertRegex(self.script, r'git commit -m "[^"]*\$\{short\}"')
        self.assertIn("rev-parse --short=7 HEAD", self.script)
        self.assertLess(self.script.index("git diff --cached --quiet"), self.script.index("git commit"))
        self.assertNotIn("${{", self.script, "nothing from the event is written into a script")

    def test_a_wiki_that_was_never_set_up_stops_with_what_to_click(self):
        first = self.steps[0]
        self.assertIn("ls-remote --exit-code", first["run"])
        self.assertIn(".wiki.git", first["run"])
        self.assertIn("exit 1", first["run"])
        for words in ("Settings", "Wikis", "Create the first page", "Run workflow"):
            self.assertIn(words, first["run"] + self.text.split("name: wiki")[0])
        self.assertIn("::error", first["run"])
        self.assertEqual(first["env"]["GH_TOKEN"], "${{ github.token }}")
        self.assertNotIn("${{", first["run"])
        names = [s.get("name") or s.get("uses") for s in self.steps]
        self.assertLess(names.index(first["name"]), names.index(out_uses(self.steps)))

    def test_the_parser_used_here_reads_yaml_the_way_other_parsers_do(self):
        y = parse_yaml("a: 1\nb:\n  - x\n  - 'y z'   # c\n  - k: v\n    l: [1, \"2\"]\nc: |\n  line one\n    line two\n\n  last\nd: {}\non: true\n")
        self.assertEqual(y, {"a": "1", "b": ["x", "y z", {"k": "v", "l": ["1", "2"]}], "c": "line one\n  line two\n\nlast\n", "d": {}, "on": "true"})
        self.assertEqual(parse_yaml("k:\n- a\n- b\n"), {"k": ["a", "b"]})


def out_uses(steps):
    return [s.get("name") or s.get("uses") for s in steps if s.get("uses", "").startswith("actions/checkout")][0]


# ---------------------------------------------------------------- a small YAML reader (the subset a workflow uses)
def parse_yaml(text):
    lines = text.split("\n")
    pos = [0]

    def indent(ln):
        return len(ln) - len(ln.lstrip(" "))

    def skip():
        while pos[0] < len(lines) and (not lines[pos[0]].strip() or lines[pos[0]].lstrip().startswith("#")):
            pos[0] += 1

    def scalar(v):
        v = v.strip()
        q = re.match(r"""^(["'])(.*?)\1(?:\s+#.*)?$""", v)
        if q:
            return q.group(2)
        if v.startswith("["):
            inner = v[1:v.rindex("]")].strip()
            return [scalar(x) for x in re.findall(r"""("[^"]*"|'[^']*'|[^,\s][^,]*)""", inner)] if inner else []
        if v == "{}":
            return {}
        return re.sub(r"\s+#.*$", "", v)

    def is_map(content):
        return re.match(r"""^(?:[^\s:#'"\[{-][^:]*?|"[^"]+"|'[^']+'):(?:\s|$)""", content) is not None

    def block(cur):
        skip()
        return seq(cur) if lines[pos[0]].lstrip().startswith("- ") else mapping(cur)

    def seq(cur):
        out = []
        while True:
            skip()
            if pos[0] >= len(lines) or indent(lines[pos[0]]) != cur or not lines[pos[0]].lstrip().startswith("- "):
                return out
            content = lines[pos[0]].lstrip()[2:]
            if is_map(content):
                lines[pos[0]] = " " * (cur + 2) + content
                out.append(mapping(cur + 2))
            else:
                out.append(scalar(content))
                pos[0] += 1

    def mapping(cur):
        out = {}
        while True:
            skip()
            if pos[0] >= len(lines) or indent(lines[pos[0]]) != cur:
                return out
            ln = lines[pos[0]].strip()
            m = re.match(r"""^("[^"]+"|'[^']+'|[^:]+?):(?:\s+(.*))?$""", ln)
            if not m:
                raise ValueError("cannot read: " + ln)
            key, val = m.group(1).strip("\"'"), (m.group(2) or "").strip()
            pos[0] += 1
            if re.match(r"^[|>][+-]?$", val):
                body, first = [], None
                while pos[0] < len(lines) and (not lines[pos[0]].strip() or indent(lines[pos[0]]) > cur):
                    if lines[pos[0]].strip() and first is None:
                        first = indent(lines[pos[0]])
                    body.append(lines[pos[0]])
                    pos[0] += 1
                while body and not body[-1].strip():
                    body.pop()
                out[key] = "\n".join(b[first:] if b.strip() else "" for b in body) + "\n"
            elif val and not val.startswith("#"):
                out[key] = scalar(val)
            else:
                skip()
                if pos[0] < len(lines) and (indent(lines[pos[0]]) > cur or
                                            (indent(lines[pos[0]]) == cur and lines[pos[0]].lstrip().startswith("- "))):
                    out[key] = block(indent(lines[pos[0]]))
                else:
                    out[key] = None

    return block(0)


class Docs(unittest.TestCase):
    def read(self, rel):
        return " ".join((REPO / rel).read_text(encoding="utf-8").split())

    def test_the_wiki_article_says_where_the_wiki_lives(self):
        text = self.read("docs/APP.md")
        self.assertIn("GitHub wiki", text)
        self.assertIn("wiki_github", text)
        self.assertIn(".github/workflows/wiki.yml", text)
        self.assertIn("Create the first page", text)

    def test_contributing_says_how_the_three_copies_stay_in_step(self):
        text = self.read("CONTRIBUTING.md")
        self.assertIn("three copies", text)
        for word in ("Wiki tab", "/wiki/", "GitHub wiki", "wiki.yml"):
            self.assertIn(word, text)

    def test_the_agent_rule_names_the_github_wiki(self):
        text = self.read("AGENTS.md")
        self.assertIn("Keep the wiki current", text)
        self.assertIn("GitHub wiki", text)
        self.assertIn("never edit it by hand", text)


if __name__ == "__main__":
    unittest.main()
