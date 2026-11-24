"""devices: the threshold fit lands the target reduction; attack/release suggestions follow the part and tempo."""
import unittest
import numpy as np
from hypnomix.engineer import devices as D, sidechain as SC


class Devices(unittest.TestCase):
    def test_fit_lands_the_target(self):
        sr = SC.SR
        t = np.arange(int(10 * sr)) / sr
        x = 0.3 * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.5 * t))   # a swelling part
        act, noise, phrase = D.active(x)
        c = dict(D.NEW_COMP)
        c = D.fit_threshold(x, act, c, 4.0)
        _, m = D.measure_comp(x, act, c)
        self.assertAlmostEqual(m["median"], 4.0, delta=0.5)

    def test_times_follow_the_part(self):
        att, rel = D.times_for("drums", 120.0, None)
        self.assertGreaterEqual(att, 5); self.assertLessEqual(rel, 150)
        att, rel = D.times_for("bass", 120.0, 41.0)          # low E: release at least two cycles (49 ms)
        self.assertGreaterEqual(rel, 2000 / 41.0)


if __name__ == "__main__":
    unittest.main()
