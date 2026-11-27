"""Second review of the REAPER work: every doc, wiki article and lesson says the same true thing about what was run in
REAPER 7.86, what `scan` reads, and when the vocal-level check runs; the published teacher ids keep their order."""
import re
import unittest
from pathlib import Path

from hypnomix.app import teacher as T
from tests.teacher_ids import ADDED_SINCE, PINNED, PUBLISHED

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "hypnomix/app/wiki/articles"
LESSONS = ROOT / "hypnomix/app/lessons"


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def flat(text):
    """Line breaks and runs of spaces as one space, so a phrase wrapped over two lines still matches."""
    return re.sub(r"\s+", " ", text)


def owned_texts():
    files = [ROOT / "README.md", ROOT / "AGENTS.md"]
    files += sorted((ROOT / "docs").rglob("*.md"))
    files += sorted(WIKI.glob("*.html"))
    files += sorted(LESSONS.glob("*.py"))
    files += [ROOT / "hypnomix/app/teacher.py", ROOT / "hypnomix/app/teacher.js"]
    return {str(p.relative_to(ROOT)): flat(p.read_text(encoding="utf-8")) for p in files if p.is_file()}


class WhatRanInReaper(unittest.TestCase):
    STALE = ("not yet opened in REAPER", "has not yet been opened in REAPER", "not been opened in REAPER",
             "not opened in REAPER", "Not yet run in REAPER", "not yet run in REAPER", "Untested in REAPER")

    def test_no_text_says_the_reaper_runs_never_happened(self):
        for name, text in owned_texts().items():
            for gone in self.STALE:
                self.assertNotIn(gone, text, name)

    def test_the_full_record_is_the_same_in_the_three_long_places(self):
        for rel in ("docs/REAPER.md", "docs/guides/08-inside-reaper.md", "AGENTS.md"):
            text = flat(read(rel))
            for fact in ("two-track test project", "-1.4 LU", "--revert", "106 points", "-17 dB, 4:1, 15 ms, 250 ms",
                         "Amount 20%", "amount of 73 untouched", "not clicked through by hand", "loaded with no error"):
                self.assertIn(fact, text, (rel, fact))

    def test_what_was_not_checked_is_said(self):
        for rel in ("docs/REAPER.md", "docs/guides/08-inside-reaper.md", "AGENTS.md", "README.md"):
            text = flat(read(rel))
            self.assertIn("Windows", text, rel)
            self.assertRegex(text, r"not (?:been )?(?:clicked through|tried on Windows)|clicking the windows by hand", rel)
            self.assertRegex(text, r"diagnose`? (?:on a project )?with folders|project with folders", rel)
        for rel in ("README.md", "AGENTS.md", "docs/REAPER.md"):
            self.assertIn("ReaGate and ReaLimit settings", flat(read(rel)), rel)

    def test_guide_08_opening_no_longer_claims_everything(self):
        g = flat(read("docs/guides/08-inside-reaper.md"))
        self.assertNotIn("Everything here was checked against REAPER 7.86 itself", g)
        self.assertIn("only opened and captured by screenshot, not clicked through by hand", g)
        self.assertIn("Solo in place with folders and send returns is unchecked in REAPER", g)

    def test_vocallevel_envelopes_say_the_same_everywhere(self):
        for rel in ("README.md", "docs/guides/04-vocal-production.md", "docs/guides/08-inside-reaper.md",
                    "hypnomix/app/wiki/articles/25-chores.html", "hypnomix/app/wiki/articles/26-features.html"):
            text = flat(read(rel))
            self.assertIn("two-track test project", text, rel)
            self.assertRegex(text, r"not (?:been )?(?:run on|judged by ear)", rel)

    def test_wiki_summaries_say_what_ran(self):
        for name in ("18-setup.html", "27-next.html", "28-faq.html"):
            text = flat((WIKI / name).read_text(encoding="utf-8"))
            self.assertIn("two-track test project", text, name)
            self.assertIn("not clicked through by hand", text, name)


class ScanAndTheProbeMenus(unittest.TestCase):
    """`scan` on an .rpp does not read the probe menus, Protect or the song card (scan.py: told_in_live is skipped
    for REAPER); only the app's review of what it heard, Record and review and the mastering chain use them."""

    def test_no_text_says_scan_reads_the_reaper_menus(self):
        guide = flat(read("docs/guides/08-inside-reaper.md"))
        self.assertNotIn("so `scan` reads them (`hypnomix reaper probes cards", guide)
        self.assertIn("`scan` and `fix` on a REAPER project do not read them yet", guide)
        self.assertNotIn("Tuning and harmony use the key instead of guessing", guide)
        ch13 = (LESSONS / "ch13_hypnomix.py").read_text(encoding="utf-8")
        self.assertNotIn("a protected track is never changed without asking again.\"],\n            \"ardour\"", ch13)
        self.assertNotIn("HypnoMix Probe has its own Protect switch: a protected track is never changed", ch13)
        self.assertNotIn("(View → Master track shows the master if it is hidden). They are saved in the project, so `scan` reads them.", ch13)
        self.assertNotIn("or on HypnoMix Main's song card before any vocal tuning", ch13)
        self.assertIn("`scan` and Apply on a REAPER project do not read it yet", ch13)

    def test_agents_and_workflow_say_it_too(self):
        self.assertIn("`scan` on an `.rpp` does not read the probe menus, Protect or the song card", flat(read("AGENTS.md")))
        self.assertIn("`scan` does not read the probe menus, Protect or the song card of a REAPER project",
                      flat(read("docs/WORKFLOW.md")))


class VocalLevelInTheScan(unittest.TestCase):
    """scan_project.g_vocals runs vocallevel only when there are two or more vocal tracks."""

    def test_the_docs_name_the_condition(self):
        self.assertIn("when the project has two or more vocal tracks", flat(read("docs/guides/04-vocal-production.md")))
        self.assertIn("(`vocallevel`, when the project has two or more vocal tracks)", read("docs/guides/08-inside-reaper.md"))
        self.assertIn("two or more vocal tracks", flat(read("hypnomix/app/wiki/articles/25-chores.html")))


class WikiCoversTheNewGroups(unittest.TestCase):
    def test_devices_and_structure_in_the_wiki(self):
        chores = flat((WIKI / "25-chores.html").read_text(encoding="utf-8"))
        feats = flat((WIKI / "26-features.html").read_text(encoding="utf-8"))
        for text, name in ((chores, "25-chores"), (feats, "26-features")):
            self.assertIn("ReaComp", text, name)
            self.assertIn("ReaGate and ReaLimit are listed, not judged", text, name)
            self.assertIn("<code>structure</code>", text, name)

    def test_agents_lists_the_new_reaper_commands(self):
        a = read("AGENTS.md")
        self.assertIn("`hypnomix reaper start|status|tracks|fx|params|snapshot|loop|diagnose`", a)
        self.assertIn("`structure` group", a)
        self.assertIn("`devices` group", a)


class Naming(unittest.TestCase):
    def test_reaper_effects_have_the_new_name(self):
        for rel in ("docs/REAPER.md", "docs/guides/08-inside-reaper.md", "docs/ROADMAP.md",
                    "hypnomix/app/wiki/articles/28-faq.html"):
            self.assertNotRegex(read(rel), r"Hypno[m]ix (?:Probe|Main)", rel)     # the old casing, spelt so this file has none


class SmallWording(unittest.TestCase):
    def test_protect_chip_is_a_toggle(self):
        self.assertIn("Click a chip: Protect switches on and off, the others open a menu.",
                      flat(read("docs/guides/08-inside-reaper.md")))
        self.assertNotIn("Click a chip for its menu", flat(read("docs/guides/08-inside-reaper.md")))
        self.assertIn("Click a chip: Protect switches on and off, the others open a menu.",
                      (LESSONS / "ch13_hypnomix.py").read_text(encoding="utf-8"))

    def test_guide_seen_wording_covers_main(self):
        ch13 = (LESSONS / "ch13_hypnomix.py").read_text(encoding="utf-8")
        self.assertIn("(a plug-in that has already shown it stays quiet)", ch13)
        self.assertNotIn("(a probe that has already shown it stays quiet)", ch13)

    def test_reaeq_spectrum_step_is_plain(self):
        t = (LESSONS / "ch08_mix_a.py").read_text(encoding="utf-8")
        self.assertNotIn("(ReaEQ can show one behind its curve)", t)
        self.assertIn("ReaEQ draws the spectrum of the part it sits on behind its curve", t)


class PublishedTeacherIds(unittest.TestCase):
    """The 0.3.1 lists stay as published; additions are listed apart, so an accidental change still fails."""

    def test_pinned_is_published_plus_the_listed_additions(self):
        self.assertEqual(set(PINNED), set(PUBLISHED))
        for key, chapters in PINNED.items():
            added = ADDED_SINCE.get(key, {})
            pub = dict(PUBLISHED[key])
            self.assertEqual([c for c, _ in chapters], [c for c, _ in PUBLISHED[key]], key)
            for chap, ids in chapters:
                extra = set(added.get(chap, ()))
                self.assertFalse(extra & set(pub[chap]), (key, chap))          # an addition is a new id
                self.assertEqual(tuple(i for i in ids if i not in extra), pub[chap], (key, chap))
                self.assertEqual(set(ids) - set(pub[chap]), extra, (key, chap))

    def test_published_ids_keep_their_order_in_todays_courses(self):
        for key, chapters in PUBLISHED.items():
            level, daw = key.split("/")
            got = {c["id"]: [s["id"] for s in c["steps"]] for c in T.steps(daw, level)}
            for chap, ids in chapters:
                now = got[chap]
                self.assertEqual([i for i in now if i in set(ids)], list(ids), (key, chap))
                extra = set(now) - set(ids)
                self.assertEqual(extra, set(ADDED_SINCE.get(key, {}).get(chap, ())), (key, chap))

    def test_published_lists_match_the_0_3_1_file(self):
        """A fixed copy of two published lists, so PUBLISHED itself cannot be edited to fit."""
        self.assertEqual(dict(PUBLISHED["101/reaper"])["mix"],
                         ('balance', 'eq', 'comp', 'deess', 'reverb', 'delay', 'groups', 'automation', 'mix-check'))
        self.assertEqual(dict(PUBLISHED["tour/reaper"])["hypnomix"],
                         ('hm-loop', 'hm-connect-reaper', 'hm-devices-reaper', 'hm-scan', 'hm-ab', 'hm-apply',
                          'hm-tracking', 'hm-mixing', 'hm-master', 'hm-export', 'hm-ai'))


if __name__ == "__main__":
    unittest.main()
