"""The lessons of teacher mode (hypnomix/app/lessons): structure, links, banned words, and what is built from them."""
import re
import unittest

from hypnomix.app import teacher as T
from hypnomix.app import teach_audio as TA
from hypnomix.app import wiki

COURSES = ("tour", "101", "az")
# Paid plug-in, tuning, DAW, hardware and distributor brands must never appear in a lesson. The repo itself must not
# name them either, so the list is kept as fingerprints: the first 12 hex digits of the SHA-256 of each name in lower
# case. To add one: python -c "import hashlib; print(hashlib.sha256('the name'.encode()).hexdigest()[:12])"
BANNED = {
          "020570fef6bd", "03a1bc2421ef", "045093b24588", "06178141c7c8", "0657ecb53be7", "0894a3078e28", "0a5951779b8c", "139b09b78a6f",
          "1418dfd3e149", "16a48fe214f6", "19fd691c8d89", "1c5d29d3887a", "1cb1f387c32f", "1d0e1bac0cb6", "1f0da16b89bf", "2075c679cb9c",
          "27edf8739f5d", "282f8f55fc67", "2ae280b7b474", "2ae41ee88269", "2d87360b82e8", "3258c35df927", "32d4d0f2ebbd", "33544f590034",
          "33ad776f0e30", "37e1d3b95593", "445ca6eb84d2", "459d9b16ebab", "503fddae4b19", "507f9328604e", "52d16044f840", "52fdbec241d7", "611d633fc825",
          "6199bca8d588", "63cc98599f0a", "74e9f3d8efbd", "762797e24b69", "7e002cc92f0f", "7fe01e5bce7b", "809edbe5ab7a", "8251d280bd3b",
          "884fa7dd6070", "91b2d88a0f9f", "97f2e3c35fe1", "995ebc0e7186", "9a9043b12497", "a067c68e292e", "a2c7aa6e8f8f", "a8adf040d538",
          "bac24813f291", "badcaa4206aa", "bb2bd7ca4a32", "bdf8c1e06ce1", "be923d31b6c4", "c85f9738f8fa", "d004e3a0139c", "d22c5ede4878",
          "da4fbbb2e268", "dac26a417a27", "dc5a2e46e9ef", "dcdd2ebbe211", "de903fa34df9", "dea7cd279319", "e7f768f23319", "ecee035522c9",
          "ee8d8d5cf476", "f30a32ce3bf6", "f43c7b93298a", "f4d468c19d1a", "fe719c224dcb",
}
BANNED_WORDS = 3            # the longest name, in words


def banned_in(text):
    """The first run of 1 to BANNED_WORDS words in `text` whose fingerprint is on the list, or None."""
    import hashlib
    words = re.findall(r"[a-z0-9][a-z0-9+.'-]*[a-z0-9+]|[a-z0-9]", text.lower())
    for n in range(1, BANNED_WORDS + 1):
        for k in range(len(words) - n + 1):
            run = " ".join(words[k:k + n])
            if hashlib.sha256(run.encode()).hexdigest()[:12] in BANNED:
                return run
    return None


def strings(x):
    """Every string inside a lesson (nested lists, dicts, tuples)."""
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            if k not in ("fx", "action"):
                yield from strings(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from strings(v)


def all_steps():
    return [(ch, s) for ch in T.CHAPTERS for s in ch["steps"]]


class Structure(unittest.TestCase):
    def test_thirteen_chapters_in_the_planned_order(self):
        self.assertEqual([c["id"] for c in T.CHAPTERS],
                         ["sound", "digital", "gear", "words", "song", "record", "editing", "mix", "master", "release",
                          "trouble", "cheats", "hypnomix"])

    def test_ids_are_unique(self):
        ids = [s["id"] for _, s in all_steps()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len({c["id"] for c in T.CHAPTERS}), len(T.CHAPTERS))

    def test_every_step_is_complete(self):
        for ch, s in all_steps():
            self.assertTrue(s["title"] and s["say"], s["id"])
            self.assertTrue(set(s.get("daws", T.ALL)) <= set(T.DAWS), s["id"])
            for d in (s.get("how") or {}):
                self.assertIn(d, s.get("daws", T.ALL), f"{s['id']}: how for {d}, which the step doesn't teach")
            for row in s.get("settings") or []:
                self.assertEqual(len(row), 3, s["id"])
            for row in s.get("terms") or []:
                self.assertEqual(len(row), 2, s["id"])
            for lv in s.get("levels", ()):
                self.assertIn(lv, T.LEVELS, s["id"])
            if s.get("mistakes"):
                self.assertLessEqual(len(s["mistakes"]), 5, s["id"])
            if s.get("try"):
                self.assertTrue(s["try"]["do"] and s["try"]["success"], s["id"])

    def test_quizzes(self):
        n = 0
        for _, s in all_steps():
            for q in s.get("quiz") or []:
                n += 1
                self.assertTrue(q["q"] and q["why"], s["id"])
                self.assertGreaterEqual(len(q["options"]), 2, s["id"])
                self.assertIn(q["answer"], range(len(q["options"])), f"{s['id']}: answer out of range")
                self.assertEqual(len(set(q["options"])), len(q["options"]), s["id"])
            self.assertLessEqual(len(s.get("quiz") or []), 3, s["id"])
        self.assertGreater(n, 100)

    def test_more_points_at_things_that_exist(self):
        from hypnomix import cli
        step_ids = {s["id"] for _, s in all_steps()}
        wiki_ids = {a["id"] for a in wiki.local()}
        for _, s in all_steps():
            for m in s.get("more") or []:
                if m.startswith("step:"):
                    self.assertIn(m[5:], step_ids, f"{s['id']}: more {m}")
                elif m.startswith("hypnomix "):
                    self.assertIn(m.split()[1], cli.COMMANDS, f"{s['id']}: more {m}")
                else:
                    self.assertIn(m, wiki_ids, f"{s['id']}: more {m}")

    def test_commands_named_in_the_text_exist(self):
        from hypnomix import cli
        for _, s in all_steps():
            for t in strings({k: v for k, v in s.items() if k not in ("id", "more")}):
                for c in re.findall(r"`hypnomix ([a-z][a-z0-9-]*)", t):
                    self.assertIn(c, cli.COMMANDS, f"{s['id']}: `hypnomix {c}`")

    def test_hear_demos_exist(self):
        for _, s in all_steps():
            for h in s.get("hear") or []:
                self.assertIn(h if isinstance(h, str) else h["demo"], TA.DEMOS, s["id"])

    def test_no_paid_products_are_named(self):
        for ch, s in all_steps():
            self.assertIsNone(banned_in(" ".join(strings(s))), f"{s['id']} names a paid product")

    def test_the_fingerprints_still_catch_a_name(self):
        import hashlib
        probe = "zz made-up brand"                                    # proves the matcher works without naming anything real
        BANNED.add(hashlib.sha256(probe.encode()).hexdigest()[:12])
        try:
            self.assertEqual(banned_in("Put the ZZ Made-Up Brand, on the vocal."), probe)
            self.assertIsNone(banned_in("Put a compressor on the vocal."))
        finally:
            BANNED.discard(hashlib.sha256(probe.encode()).hexdigest()[:12])

    def test_plain_spelling_and_no_leftovers(self):
        for _, s in all_steps():
            blob = " ".join(strings(s))
            for bad in ("TODO", "FIXME", "lorem", "—"):                    # no placeholders and no em dashes
                self.assertNotIn(bad, blob, s["id"])


class Courses(unittest.TestCase):
    def test_three_courses_build_for_three_daws(self):
        self.assertEqual(list(T.LEVELS), ["tour", "101", "az"])
        for d in T.DAWS:
            n = {lv: T.count(d, lv) for lv in COURSES}
            self.assertGreater(n["az"], n["101"], d)
            self.assertGreater(n["101"], n["tour"], d)
            for lv in COURSES:
                for c in T.steps(d, lv):
                    self.assertTrue(c["steps"], (d, lv, c["id"]))
        self.assertGreaterEqual(T.count("live", "az"), 140)

    def test_az_has_every_chapter_for_every_daw(self):
        for d in T.DAWS:
            self.assertEqual([c["id"] for c in T.steps(d, "az")], [c["id"] for c in T.CHAPTERS], d)

    def test_every_step_is_taught_to_the_daws_it_names(self):
        for d in T.DAWS:
            ids = {s["id"] for c in T.steps(d, "az") for s in c["steps"]}
            want = {s["id"] for _, s in all_steps() if d in s.get("daws", T.ALL)}
            self.assertEqual(ids, want, d)

    def test_hear_is_expanded_for_the_page(self):
        s = next(s for c in T.steps("live", "az") for s in c["steps"] if s["id"] == "mix-lowcuts")
        h = s["hear"][0]
        self.assertEqual(h["demo"], "low-cut")
        self.assertEqual([v["v"] for v in h["variants"]], ["a", "b"])
        self.assertTrue(h["listen"])


class Glossary(unittest.TestCase):
    def test_a_to_z_with_links(self):
        g = T.glossary()
        names = [x["term"].lower() for x in g]
        self.assertGreater(len(g), 400)
        self.assertEqual(len(set(names)), len(names))
        keys = [re.sub(r"[^a-z0-9 ]", "", n) for n in names]
        self.assertEqual(keys, sorted(keys))
        step_ids = {s["id"] for _, s in all_steps()}
        for x in g:
            self.assertTrue(x["entries"], x["term"])
            for e in x["entries"]:
                self.assertTrue(e["meaning"])
                if e["step"]:
                    self.assertIn(e["step"], step_ids)
        self.assertIn("compressor", names)
        self.assertLess(len(T.glossary("ardour")), len(g))

    def test_route(self):
        code, r = T.handle_get("/api/teach/glossary", {"daw": "live"})[:2]
        self.assertEqual(code, 200)
        self.assertTrue(r["terms"])


class WikiArticles(unittest.TestCase):
    def test_per_chapter_articles_in_the_daw_groups(self):
        arts = {a["id"]: a for a in T.wiki_all()}
        for d, g in T.WIKI_GROUP.items():
            self.assertEqual(arts[f"learn-{d}"]["group"], g)
            self.assertEqual(arts[f"tour-{d}"]["group"], g)
            for ch in T.steps(d, "az"):
                a = arts[f"learn-{d}-{ch['id']}"]
                self.assertEqual(a["group"], g)
                self.assertIn(f'data-wiki="learn-{d}-{ch["id"]}"', arts[f"learn-{d}"]["html"])     # the contents page links to it
                self.assertLess(len(a["html"]), 260000, a["id"])                                   # lean
        self.assertEqual(len(arts), 3 * (2 + len(T.CHAPTERS)) + 1)
        self.assertEqual(arts["glossary"]["group"], "Reference")
        self.assertIn("Compressor", arts["glossary"]["text"])

    def test_the_real_wiki_has_them_and_ids_stay_unique(self):
        arts = wiki.local()
        ids = [a["id"] for a in arts]
        self.assertEqual(len(ids), len(set(ids)))
        for want in ("learn-live", "learn-reaper-mix", "learn-ardour-sound", "tour-live", "glossary"):
            self.assertIn(want, ids)
        by = {a["id"]: a for a in arts}
        for a in arts:
            for target in re.findall(r'data-wiki="([^"]+)"', a["html"]):
                if a["id"].startswith(("learn-", "tour-")) or a["id"] == "glossary":
                    self.assertIn(target, by, f"{a['id']} links to a missing article {target}")

    def test_lesson_text_survives_in_the_chapter_articles(self):
        a = next(x for x in T.wiki_all() if x["id"] == "learn-live-mix")
        self.assertIn("EQ Eight", a["text"])
        self.assertIn("Check yourself", a["text"])
        self.assertIn("Try it", a["text"])


class AssistantNote(unittest.TestCase):
    def test_the_note_stays_small_and_never_carries_the_course(self):
        from unittest import mock
        for lv in ("tour", "101", "az"):
            with mock.patch.object(T, "choice", return_value=("live", lv, "key")):
                note = T.assistant_note()
            self.assertTrue(note)
            self.assertLess(len(note), 1200, lv)
            self.assertNotIn("EQ Eight", note)


class NoNumpy(unittest.TestCase):
    def test_the_course_articles_build_on_plain_python(self):
        """The website's wiki is built on a machine with no numpy: the course articles must not need it."""
        import subprocess, sys
        code = ("import sys\n"
                "class Block:\n"
                "    def find_spec(self, name, path=None, target=None):\n"
                "        if name.split('.')[0] in ('numpy', 'scipy', 'soundfile', 'librosa'):\n"
                "            raise ModuleNotFoundError(name)\n"
                "sys.meta_path.insert(0, Block())\n"
                "from hypnomix.app import wiki\n"
                "arts = wiki.local()\n"
                "arts = arts['articles'] if isinstance(arts, dict) else arts\n"
                "ids = [a['id'] for a in arts]\n"
                "assert not wiki.COURSE_ERROR, wiki.COURSE_ERROR\n"
                "assert 'glossary' in ids and 'learn-live-mix' in ids and 'tour-reaper' in ids, len(ids)\n"
                "print(len(ids))\n")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertGreater(int(r.stdout.strip() or 0), 100)


HONESTY = "HypnoMix DAW is not released yet. Until it is, everything written here for it is written for Ardour 8 or 9, the free DAW it is built on, and has not yet been tried in either."


def texts(x, skip=("id", "more", "daws", "levels", "fx", "action", "app", "kind")):
    """The words a person reads in a lesson: every string except ids, links to other lessons, DAW keys and actions."""
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            if k not in skip:
                yield from texts(v, skip)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from texts(v, skip)


class Naming(unittest.TestCase):
    """The owner's naming decisions: HypnoMix in prose, `hypnomix ...` only as a command, HypnoMix DAW for the third DAW,
    and Ardour named only in the honesty line of each HypnoMix DAW course's first step."""

    def test_the_third_daw_is_called_hypnomix_daw(self):
        self.assertEqual(T.DAWS, {"live": "Ableton Live", "reaper": "REAPER", "ardour": "HypnoMix DAW"})
        self.assertEqual(T.WIKI_GROUP["ardour"], "DAW: HypnoMix DAW")

    def test_ardour_is_named_only_in_the_honesty_line(self):
        for ch, s in all_steps():
            for t in texts(s):
                self.assertNotIn("Ardour", t.replace(HONESTY, ""), s["id"])
        for lv in COURSES:
            for ch in T.steps("ardour", lv):
                for s in ch["steps"]:
                    for t in texts(s):
                        self.assertNotIn("Ardour", t.replace(HONESTY, ""), (lv, s["id"]))
        for lv in COURSES:
            self.assertNotIn("Ardour", T.wiki_article("ardour", lv)["text"].replace(HONESTY, ""))

    def test_the_generated_wiki_never_names_ardour_or_says_the_honesty_line(self):
        """The wiki says it once, in its HypnoMix DAW article (id "ardour", not generated here); the generated articles link to it."""
        arts = T.wiki_all()
        self.assertFalse([a["id"] for a in arts if a["id"] == "ardour"])
        for a in arts:
            for field in ("title", "sub", "html", "text"):
                self.assertNotIn("Ardour", a[field], a["id"])
                self.assertNotIn("not released yet", a[field], a["id"])
        self.assertIn('data-wiki="ardour"', T.wiki_article("ardour", "tour")["html"])
        self.assertIn('data-wiki="ardour"', T.wiki_article("ardour", "az")["html"])
        self.assertEqual(T.wiki_article("ardour", "tour")["title"], "Guided tour: HypnoMix DAW")
        self.assertNotIn(HONESTY, T.steps("ardour", "az", honesty=False)[0]["steps"][0]["how"])

    def test_titles_do_not_say_the_name_twice(self):
        for lv in COURSES:
            for ch in T.steps("ardour", lv):
                self.assertNotIn("HypnoMix in HypnoMix", ch["title"])
                for s in ch["steps"]:
                    self.assertNotIn("HypnoMix with HypnoMix", s["title"])

    def test_the_honesty_line_opens_each_hypnomix_daw_course_and_nowhere_else(self):
        for lv, first in (("tour", "hm-loop"), ("101", "daw"), ("az", "snd-what-is-sound")):
            steps = [s for ch in T.steps("ardour", lv) for s in ch["steps"]]
            self.assertEqual(steps[0]["id"], first)
            self.assertEqual(steps[0]["how"][0], HONESTY, lv)
            self.assertEqual(T.HONESTY, HONESTY)
            for s in steps[1:]:
                self.assertNotIn("not released yet", " ".join(s["how"] + s["say"]), (lv, s["id"]))
        for d in ("live", "reaper"):
            for ch, s in all_steps():
                for t in texts(s):
                    self.assertNotIn("not released yet", t)

    def test_the_product_is_spelled_hypnomix_capital_m_in_prose(self):
        """A bare lower-case "hypnomix" may stay only in a command, a path, a file or a name another program looks up."""
        keep = re.compile(r"`[^`]*`|~/\.hypnomix|hypnomix[/.\-_][A-Za-z0-9_/.\-]*[A-Za-z0-9_/]|.hypnomix: |\(hypnomix devices\)|type Hypnomix in|Effects/hypnomix|JS \u2192 hypnomix")
        for ch, s in all_steps():
            for t in texts(s):
                left = keep.sub("", t)
                self.assertIsNone(re.search(r"\bhypnomix\b", left), f"{s['id']}: {t[:90]}")
                self.assertIsNone(re.search(r"\bHypnomix\b(?! ?(Main|Probe|Align|panel|device|Master)|\*\*|:| \u2192)", left.replace("**Hypnomix**", "")),
                                  f"{s['id']}: {t[:90]}")

    def test_setup_choice_hypnomix_gets_the_hypnomix_daw_lessons(self):
        from unittest import mock
        with mock.patch("hypnomix.app.setup.load", return_value={"daw": "hypnomix", "teach_level": "az"}):
            self.assertEqual(T.choice()[0], "ardour")
            st = T.state()
        self.assertEqual((st["daw"], st["daws"]["ardour"]), ("ardour", "HypnoMix DAW"))
        self.assertTrue(st["chapters"])


if __name__ == "__main__":
    unittest.main()
