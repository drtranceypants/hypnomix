"""Review fixes in the REAPER docs and lessons: the chain tag's casing, the guide's 'seen' wording, Mac title bar."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAIN = (ROOT / "hypnomix/reaper/masterchain.lua").read_text(encoding="utf-8")
REAPER_MD = (ROOT / "docs/REAPER.md").read_text(encoding="utf-8")
GUIDE = (ROOT / "docs/guides/08-inside-reaper.md").read_text(encoding="utf-8")
LESSONS = ROOT / "hypnomix/app/lessons"


def ours(renamed, tag):
    """masterchain.lua's ours(): the first #TAG bytes, lower-cased, against the lower-cased tag."""
    b, t = renamed.encode(), tag.encode()
    return b[:len(t)].lower() == t.lower()


class ChainTag(unittest.TestCase):
    def test_tag_is_HypnoMix(self):
        m = re.search(r'local TAG = "([^"]*)"', CHAIN)
        self.assertEqual(m.group(1), "HypnoMix · ")

    def test_old_chains_are_still_ours(self):
        self.assertIn("renamed(tr, i):sub(1, #TAG):lower() == TAG:lower()", CHAIN)
        tag = "HypnoMix · "
        self.assertTrue(ours("HypnoMix · Tone", tag))
        self.assertTrue(ours("Hypnomix · Tone", tag))       # built before the rename
        self.assertFalse(ours("ReaEQ (Cockos)", tag))
        self.assertFalse(ours("HypnoMix Tone", tag))

    def test_no_old_casing_in_visible_chain_text(self):
        for line in CHAIN.splitlines():
            code = line.split("--", 1)[0]
            self.assertNotRegex(code, r'"Hypno[m]ix', line)       # the old casing, spelt so this file has none


class Wording(unittest.TestCase):
    def test_lessons_use_new_tag(self):
        text = "".join(p.read_text(encoding="utf-8") for p in LESSONS.glob("*.py"))
        self.assertNotIn("Hypnomix · ", text)
        self.assertIn("HypnoMix · ", text)

    def test_guide_seen_depends_on_bridge(self):
        ch13 = (LESSONS / "ch13_hypnomix.py").read_text(encoding="utf-8")
        self.assertNotIn("the first time each one is opened on your computer", ch13)
        self.assertIn("Without the bridge, Probe and", ch13)
        self.assertIn("shown once per computer while the bridge runs", REAPER_MD)

    def test_mac_title_bar(self):
        for name in ("ch02_digital_steps.py", "ch11_trouble_steps.py"):
            text = (LESSONS / name).read_text(encoding="utf-8")
            for m in re.finditer(r"right-hand end of (?:its|the) menu bar", text):
                self.assertIn("on a Mac, in the title bar", text[m.end():m.end() + 60], name)

    def test_reaper_md_does_not_overclaim_or_underclaim(self):
        self.assertNotIn("Every fact below was measured", REAPER_MD)
        self.assertIn("unless a row or section says otherwise", REAPER_MD)
        for gone in ("not yet run in REAPER", "Not yet run in REAPER", "has not been opened in REAPER",
                     "not opened in REAPER"):
            self.assertNotIn(gone, REAPER_MD)
        self.assertIn("(-17 dB, 4:1, 15 ms, 250 ms)", REAPER_MD)
        self.assertIn("106 points", REAPER_MD)
        self.assertNotIn("Hypnomix Main", REAPER_MD)
        self.assertNotIn("Hypnomix Main", GUIDE)


if __name__ == "__main__":
    unittest.main()
