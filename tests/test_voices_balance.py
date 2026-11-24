"""Harmony balance: only what the person chose, only downwards, nothing without an anchor."""
import unittest
import numpy as np
from hypnomix.studio.voices import plan

NAN = float("nan")


def parts():
    # one window, three parts: low (A3), mid (C#4), high (E4), all at -20 dB
    lv = {"low": np.array([-20.0]), "mid": np.array([-20.0]), "high": np.array([-20.0])}
    pt = {"low": np.array([220.0]), "mid": np.array([277.2]), "high": np.array([329.6])}
    return lv, pt


class Balance(unittest.TestCase):
    def test_ladder_above_the_lowest(self):
        g, _ = plan(*parts(), "lowest", "above", 1.5, 0, "ladder")
        self.assertEqual([round(g[n][0], 1) for n in ("low", "mid", "high")], [0.0, -1.5, -3.0])

    def test_flat_above(self):
        g, _ = plan(*parts(), "lowest", "above", 3, 0, "flat")
        self.assertEqual([round(g[n][0], 1) for n in ("low", "mid", "high")], [0.0, -3.0, -3.0])

    def test_anchor_in_the_middle_both_sides(self):
        g, _ = plan(*parts(), "mid", "both", 1, 4.5, "ladder")
        self.assertEqual([round(g[n][0], 1) for n in ("low", "mid", "high")], [-4.5, 0.0, -1.0])

    def test_only_turns_down_and_respects_max_cut(self):
        lv, pt = parts()
        lv["high"] = np.array([-30.0])                       # already well under the anchor
        g, _ = plan(lv, pt, "lowest", "above", 6, 0, "ladder", max_cut=4)
        self.assertEqual(round(g["high"][0], 1), 0.0)
        self.assertEqual(round(g["mid"][0], 1), -4.0)        # wanted -6, capped at 4

    def test_windows_without_the_anchor_are_left_alone(self):
        lv, pt = parts()
        lv["mid"] = np.array([NAN])
        g, rows = plan(lv, pt, "mid", "above", 3, 0)
        self.assertTrue(all(g[n][0] == 0 for n in g))
        self.assertEqual(rows, [])

    def test_zero_step_changes_nothing(self):
        g, _ = plan(*parts(), "lowest", "above", 0, 0)
        self.assertTrue(all(g[n][0] == 0 for n in g))


if __name__ == "__main__":
    unittest.main()
