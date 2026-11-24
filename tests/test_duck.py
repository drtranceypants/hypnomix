"""duck: the threshold fit lands the target depth while singing and lets go in the gaps."""
import unittest
import numpy as np
from hypnomix.engineer import duck as D, sidechain as SC


class Fit(unittest.TestCase):
    def test_three_db_while_singing_none_in_the_gaps(self):
        sr = SC.SR
        t = np.arange(int(12 * sr)) / sr
        sing = (np.floor(t / 1.5) % 2 == 0)                    # 1.5 s phrases, 1.5 s gaps
        trig = 0.3 * np.sin(2 * np.pi * 220 * t) * sing
        act = D.active_mask(trig)
        c, m = D.fit(trig, act, dict(D.NEW), 3.0)
        self.assertAlmostEqual(m["depth"], 3.0, delta=0.4)
        self.assertLess(m["in_gaps"], 0.5)


if __name__ == "__main__":
    unittest.main()
