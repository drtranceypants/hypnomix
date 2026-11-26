"""The mastering chain on REAPER's Hypnomix Main: the buttons, the bridge hook and the chain script agree.
(The chain itself is verified in REAPER: Lua cannot run here.)"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "hypnomix" / "reaper"
MAIN = (ROOT / "jsfx" / "hypnomix_main.jsfx").read_text()
CHAIN = (ROOT / "masterchain.lua").read_text()
BRIDGE = (ROOT / "bridge.lua").read_text()


class Chain(unittest.TestCase):
    def test_buttons_and_bridge_use_the_same_shared_memory(self):
        # Main counts presses in gmem[11..13]; the chain script reads them and answers in 14..16
        self.assertIn("gmem[11 + mc_i] += 1", MAIN)
        for k in ("gmem[14]", "gmem[15]", "gmem[16]"):
            self.assertIn(k, MAIN)
        self.assertRegex(CHAIN, r"GM_BUILD, GM_MATCH, GM_SAVE, GM_STATE, GM_A, GM_B = 11, 12, 13, 14, 15, 16")
        # record and review keeps 8..10; the probes' slots start at 64
        self.assertIn("GM_PRESS, GM_STATE, GM_SECS = 8, 9, 10", BRIDGE)

    def test_every_state_has_words_on_main(self):
        codes = {int(v) for v in re.findall(r"= (\d+)", CHAIN.split("local S = {")[1].split("}")[0])}
        shown = {int(x) for x in re.findall(r"mc_state == (\d+)", MAIN)}
        self.assertEqual(codes - shown - {0}, set())              # 0 (idle) is the closing default

    def test_bridge_loads_the_chain_and_polls_it(self):
        self.assertIn('dofile(HERE .. "masterchain.lua")', BRIDGE)
        self.assertIn("pcall(MC.poll)", BRIDGE)
        self.assertLess(BRIDGE.index("local function rec_poll"), BRIDGE.index("masterchain.lua"))
        for c in ("chain_build", "chain_save", "chain_match", "chain_state"):
            self.assertIn(f"function C.{c}", CHAIN)

    def test_only_reapers_own_plugins_in_the_stock_chain(self):
        for name in re.findall(r'"((?:Rea\w+ \(Cockos\))|(?:JS: [^"]+))"', CHAIN):
            self.assertTrue(name.endswith("(Cockos)") or name.startswith("JS: "), name)
        self.assertIn('TAG = "Hypnomix · "', CHAIN)

    def test_template_menu_opens_from_a_real_window_a_few_passes_later(self):
        """On macOS a menu from a 0x0 window opened in the same pass closed by itself, so Build (with templates) could
        not be used from the button (measured in REAPER 7.86): a 1x1 window at the mouse, the menu from menu_poll."""
        self.assertNotIn('gfx.init("", 0, 0', CHAIN)
        self.assertIn('gfx.init("Hypnomix", 1, 1, 0, x, y)', CHAIN)
        self.assertIn("if menu then menu_poll() end", CHAIN)
        self.assertIn("if m.passes < 3 then return end", CHAIN)

    def test_waiting_for_an_answer_is_not_no_answer(self):
        """Before every dialog or menu the script says ASKING, so Main does not claim the bridge is gone."""
        for before in ('reaper.MB("Replace', 'reaper.GetUserInputs("Save', "menu = { list = list"):
            i = CHAIN.index(before)
            self.assertIn("say(S.ASKING)", CHAIN[i - 160:i + 120], before)
        from hypnomix.reaper.cli import STATES
        self.assertIn("waiting", STATES[14])

    def test_match_stops_only_playback_it_started(self):
        self.assertIn("local started = reaper.GetPlayState() & 1 == 0", CHAIN)
        self.assertEqual(CHAIN.count("reaper.OnStopButton()"), 3)       # on target / silent / cancelled
        self.assertEqual(CHAIN.count("started then reaper.OnStopButton()"), 2)
        self.assertIn("if match.started and reaper.GetPlayState() & 1 == 1 then reaper.OnStopButton() end", CHAIN)

    def test_main_window_fits_the_buttons(self):
        h = int(re.search(r"@gfx \d+ (\d+)", MAIN).group(1))
        self.assertGreaterEqual(h, 70 + 24 + 9 + 28)


if __name__ == "__main__":
    unittest.main()
