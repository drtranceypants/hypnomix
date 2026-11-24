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


class Tame(unittest.TestCase):
    def test_only_an_overshadowing_higher_part_comes_down(self):
        lv = {"low": np.array([-20.0, -20.0]), "mid": np.array([-17.0, -20.5]), "high": np.array([-21.0, -25.0])}
        pt = {"low": np.array([220.0, 220.0]), "mid": np.array([277.0, 277.0]), "high": np.array([330.0, 330.0])}
        g, _ = plan(lv, pt, "lowest", "above", 0.0, 0.0, "ladder", 6.0, tolerance=1.5)
        self.assertAlmostEqual(g["mid"][0], -1.5)     # 3 dB over the part below: down to 1.5 dB over it, no further
        self.assertEqual(g["mid"][1], 0.0)            # quieter already: untouched
        self.assertEqual(g["high"][0], 0.0)           # below the (now tamed) mid: untouched
        self.assertEqual(g["low"][0], 0.0)

    def test_within_tolerance_is_left_alone(self):
        lv = {"low": np.array([-20.0]), "high": np.array([-18.6])}       # 1.4 dB over: within 1.5
        pt = {"low": np.array([220.0]), "high": np.array([330.0])}
        g, _ = plan(lv, pt, "lowest", "above", 0.0, 0.0, "ladder", 6.0, tolerance=1.5)
        self.assertEqual(g["high"][0], 0.0)


class UnderTheLead(unittest.TestCase):
    def test_harmonies_sit_a_little_under_the_lead(self):
        lv = {"lead": np.array([-20.0]), "h1": np.array([-19.0]), "h2": np.array([-23.0])}
        pt = {"lead": np.array([262.0]), "h1": np.array([196.0]), "h2": np.array([330.0])}
        g, rows = plan(lv, pt, "lowest", "above", 0.0, 0.0, "ladder", 6.0, tolerance=1.5, lead="lead", lead_margin=1.5)
        self.assertAlmostEqual(g["h1"][0], -2.5)   # 1 dB OVER the lead: down to 1.5 dB under it, no further
        self.assertEqual(g["h2"][0], 0.0)          # already 3 dB under: untouched
        self.assertEqual(g["lead"][0], 0.0)

    def test_reports_harmonies_at_one_level(self):
        lv = {"lead": np.array([-18.0]), "h1": np.array([-21.0]), "h2": np.array([-21.3])}
        pt = {"lead": np.array([262.0]), "h1": np.array([196.0]), "h2": np.array([330.0])}
        _, rows = plan(lv, pt, "lowest", "above", 0.0, 0.0, "ladder", 6.0, tolerance=1.5, lead="lead", lead_margin=1.5)
        self.assertTrue(rows[0]["harmonies_same_level"])


class LearnStyle(unittest.TestCase):
    def test_each_song_counts_once_and_skipped_songs_are_ignored(self):
        from hypnomix.studio import voices as V
        fake = {
            "a": dict(song="a", lead="L", harmonies=["h"], windows=50,
                      lead_margin=dict(p10=1.0, p25=2.0, median=4.0, p75=6.0),
                      higher_minus_lower=dict(p10=-3, median=-1.0, p90=1.0, abs_median=1.2, pairs=40)),
            "b": dict(song="b", lead="L", harmonies=["h"], windows=50,
                      lead_margin=dict(p10=2.0, p25=3.0, median=5.0, p75=7.0),
                      higher_minus_lower=dict(p10=-4, median=-2.0, p90=2.0, abs_median=2.0, pairs=40)),
            "c": dict(song="c", skipped="fewer than two playing vocal tracks"),
        }
        orig = V.song_spacing
        V.song_spacing = lambda sp, win_s=2.0: fake[sp]
        try:
            st = V.learn_style(["a", "b", "c"])
        finally:
            V.song_spacing = orig
        self.assertEqual(st["lead_margin"], 2.5)        # median of the songs' 25th percentiles
        self.assertEqual(st["tolerance"], 1.5)          # median of the songs' 90th percentiles
        self.assertEqual(st["lead_margin_median"], 4.5)


class RootSteps(unittest.TestCase):
    def setUp(self):
        self.pt = {"lead": np.array([392.0]), "root": np.array([196.0]), "mid": np.array([247.0]), "top": np.array([294.0])}

    def run_plan(self, lv):
        g, _ = plan(lv, self.pt, "lowest", "above", 0.0, 0.0, "ladder", 4.0, tolerance=1.0, lead="lead",
                    root_step=4.0, upper_step=5.5)
        return {k: round(float(x[0]), 2) for k, x in g.items()}

    def test_drowning_higher_harmonies_come_down_to_their_steps(self):
        g = self.run_plan({"lead": np.array([-10.0]), "root": np.array([-16.0]), "mid": np.array([-15.0]), "top": np.array([-17.0])})
        self.assertEqual(g["root"], 0.0); self.assertEqual(g["lead"], 0.0)
        self.assertEqual(g["mid"], -4.0)     # 1 dB over the root: down to 4 dB under it (cut capped at 4)
        self.assertEqual(g["top"], -4.0)     # wanted -5.5 under the root (-21.5): 4.5 dB, capped at 4

    def test_already_right_or_close_is_left_alone(self):
        g = self.run_plan({"lead": np.array([-10.0]), "root": np.array([-16.0]), "mid": np.array([-19.5]), "top": np.array([-21.0])})
        self.assertEqual(g["mid"], 0.0)      # 3.5 under: within 1 dB of the 4 dB step
        self.assertEqual(g["top"], 0.0)      # 5 under: within 1 dB of 5.5
