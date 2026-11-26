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

    def test_main_window_fits_the_buttons(self):
        h = int(re.search(r"@gfx \d+ (\d+)", MAIN).group(1))
        self.assertGreaterEqual(h, 70 + 24 + 9 + 28)


if __name__ == "__main__":
    unittest.main()
