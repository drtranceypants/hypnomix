"""Review fixes in the REAPER bridge's Lua (bridge.lua, ui.lua), checked in the source (no Lua runs here)."""
import re
import unittest
from pathlib import Path

REAPER = Path(__file__).resolve().parent.parent / "hypnomix" / "reaper"
BRIDGE = (REAPER / "bridge.lua").read_text(encoding="utf-8")
UI = (REAPER / "ui.lua").read_text(encoding="utf-8")


def body(src, start):
    """The text of the function that starts with `start`, up to the next top-level `end`."""
    i = src.index(start)
    j = src.index("\nend", i)
    return src[i:j]


class GmemAppCount(unittest.TestCase):          # 7
    def test_first_pass_clears_the_old_app_count(self):
        poll = body(BRIDGE, "local function jsfx_poll()")
        self.assertRegex(poll, r"if beat_n == 1 then reaper\.gmem_write\(3, 0\) end")
        self.assertLess(poll.index("beat_n = beat_n + 1"), poll.index("gmem_write(3, 0)"))

    def test_atexit_clears_the_app_count(self):
        i = BRIDGE.index("reaper.atexit(")
        tail = BRIDGE[i:BRIDGE.index("end)", i)]
        self.assertIn("reaper.gmem_write(3, 0)", tail)
        self.assertIn("attached", tail)


class SoftUiLoad(unittest.TestCase):            # 8
    def test_no_hard_error_on_ui_load(self):
        self.assertNotIn('error("ui.lua: "', BRIDGE)
        self.assertRegex(BRIDGE, r'if not ui_ok then probes\.err = "ui\.lua: " \.\. tostring\(U\); U = nil end')

    def test_probes_defined_before_ui_load(self):
        self.assertLess(BRIDGE.index("local probes ="), BRIDGE.index("pcall(dofile, UI_HERE"))

    def test_sev_table_guarded(self):
        self.assertIn("local SEV = U and {", BRIDGE)

    def test_panel_commands_guarded(self):
        for fn in ("function C.panel_open(a)", "function C.panel_guide()"):
            first = body(BRIDGE, fn).split("\n")[1]
            self.assertIn("if not U then return { open = false, err = probes.err or probes.last_err } end", first, fn)

    def test_draw_and_jsfx_guide_skip_without_ui(self):
        self.assertIn("if panel.open and U then", BRIDGE)
        poll = body(BRIDGE, "local function jsfx_poll()")
        self.assertLess(poll.index("if not U then return end"), poll.index("U.seen"))


class WrapLongWord(unittest.TestCase):          # 9
    def test_single_word_is_cut_not_dropped(self):
        wrap = body(UI, "function U.wrap(")
        self.assertNotIn('lines[max_lines] = lines[max_lines]:gsub("%s*%S*$", "")', wrap)
        self.assertIn('if last:find("%s") then', wrap)
        self.assertIn('last = cut(last, w, " …")', wrap)
        cut = body(UI, "local function cut(")
        self.assertIn("gfx.measurestr(word .. tail)", cut)
        self.assertIn("utf8.offset", cut)


class ReviewHeading(unittest.TestCase):         # 10
    def test_separator_only_with_a_location(self):
        draw = body(BRIDGE, "local function panel_draw()")
        m = re.search(r"local head = (.+?)\n\s*U\.wrap\(head", draw, re.S)
        self.assertIsNotNone(m)
        expr = m.group(1)
        self.assertNotIn('st.track .. "  ·  " .. (st.where', expr)
        self.assertIn('((st.where or "") ~= "") and ("  ·  " .. st.where) or ""', expr)


class GuideDropsDrag(unittest.TestCase):        # 11
    def test_guide_start_and_open_drop_the_drag(self):
        self.assertIn("panel.drag = nil; U.tour_start()", body(BRIDGE, "function C.panel_guide()"))
        self.assertIn("U.tour_on = false; panel.drag = nil", body(BRIDGE, "function C.panel_open(a)"))

    def test_drag_cleared_while_guide_on(self):
        draw = body(BRIDGE, "local function align_draw()")
        block = draw[draw.index("if not U.tour_on then"):draw.index("local r = U.tour(")]
        self.assertRegex(block, r"else\s+panel\.drag = nil")


class ReviewWindowTitle(unittest.TestCase):
    """The review window's title bar says what its header, its guide and the lessons say: "HypnoMix Review" (so it is not
    confused with the main "HypnoMix" panel). Nothing finds the window by its title."""
    def test_title_matches_the_header(self):
        self.assertIn('gfx.init("HypnoMix Review", PW, PH)', BRIDGE)
        self.assertIn('U.header("HypnoMix Review"', BRIDGE)
        self.assertIn('gfx.init("HypnoMix Align", AW, AH)', BRIDGE)

    def test_nothing_looks_the_window_up_by_title(self):
        for f in REAPER.glob("*.lua"):
            self.assertNotIn("JS_Window_Find", f.read_text(encoding="utf-8"), f.name)


if __name__ == "__main__":
    unittest.main()
