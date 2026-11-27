"""Review fixes in the REAPER JSFX (HypnoMix Probe / Main and their shared UI include)."""
import re
import unittest
from pathlib import Path

JSFX = Path(__file__).resolve().parent.parent / "hypnomix" / "reaper" / "jsfx"


def _read(name):
    return (JSFX / name).read_text(encoding="utf-8")


def _function(src, name):
    m = re.search(r"function %s\(.*?\n\);" % re.escape(name), src, re.S)
    if not m:
        m = re.search(r"function %s\(.*?\);\s*$" % re.escape(name), src, re.M)
    assert m, name
    return m.group(0)


class JsfxReviewFixes(unittest.TestCase):
    def setUp(self):
        self.ui = _read("hypnomix_ui.jsfx-inc")
        self.main = _read("hypnomix_main.jsfx")
        self.probe = _read("hypnomix_probe.jsfx")

    def test_stepper_snaps_only_changed_values(self):
        body = _function(self.ui, "ui_stepper")
        self.assertIn("nv != v ? nv = max(lo, min(hi, floor(nv / step + 0.5) * step));", body)
        # no unconditional snap left
        self.assertNotRegex(body, r"\n\s*nv = max\(lo")

    def test_wheel_cleared_every_frame(self):
        line = next(l for l in self.ui.splitlines() if l.startswith("function ui_end("))
        self.assertIn("mouse_wheel = 0", line)

    def test_app_on_rejects_stale_count(self):
        body = _function(self.ui, "ui_links")
        self.assertIn("c >= gmem[3]", body)

    def test_init_state_reset_once(self):
        init = self.ui.split("\n@init", 1)[1].split("function", 1)[0]
        self.assertIn("!ui_inited ?", init)
        guarded = init.split("!ui_inited ?", 1)[1]
        for name in ("ui_tour_on = 0", "ui_tour_i = 0", "ui_armed = 0", "ui_was = 0"):
            self.assertIn(name, guarded)
            self.assertNotIn(name, init.split("!ui_inited ?", 1)[0])
        self.assertIn("gfx_ext_retina = 1", init.split("!ui_inited ?", 1)[0])

    def test_genre_menu_escapes_ampersand(self):
        menu = re.search(r'gfx_showmenu\("not set\|pop[^"]*"\)', self.main).group(0)
        self.assertIn("r&&b / soul", menu)
        self.assertNotRegex(menu, r"r&b")

    def test_probe_app_status_needs_slot(self):
        self.assertIn('ui_app && slot >= 0 ? "app hears this track"', self.probe)

    def test_visible_name_spelling(self):
        for src in (self.ui, self.main, self.probe):
            code = "\n".join(l.split("//", 1)[0] for l in src.splitlines())   # comments may name older copies
            for s in re.findall(r'"([^"]*)"', code):
                self.assertNotIn("Hypnomix", s)


if __name__ == "__main__":
    unittest.main()
