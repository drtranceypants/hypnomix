"""Grid detection: straight 16ths, 8th-note triplets, mixed, bar by bar; timing slot kinds for triplets."""
import unittest
import numpy as np
from hypnomix.core import grid as G
from hypnomix.session.timing import slot_kind


def hits(bars, fracs, start=0, jitter=0.01, seed=0):
    rng = np.random.default_rng(seed)
    return [start * 4 + b * 4 + beat + f + rng.normal(0, jitter) for b in range(bars) for beat in range(4) for f in fracs]


class Detect(unittest.TestCase):
    def test_straight(self):
        g = G.detect(hits(8, [0, 0.25, 0.5, 0.75]))
        self.assertEqual(g.positions(3), G.STRAIGHT); self.assertFalse(g.has_triplets())

    def test_triplets(self):
        g = G.detect(hits(8, [0, 1 / 3, 2 / 3]))
        self.assertEqual(g.positions(3), G.TRIPLET8)
        self.assertAlmostEqual(g.snap(5.34)[0], 5 + 1 / 3, places=6)   # snaps to the triplet, not the 16th
        self.assertEqual(slot_kind(g.snap(5.34)[1]), "triplet")

    def test_a_triplet_section_inside_a_straight_song(self):
        b = hits(8, [0, 0.25, 0.5, 0.75]) + hits(8, [0, 1 / 3, 2 / 3], start=8) + hits(8, [0, 0.25, 0.5, 0.75], start=16)
        g = G.detect(b)
        self.assertEqual(g.positions(2), G.STRAIGHT)
        self.assertEqual(g.positions(12), G.TRIPLET8)
        self.assertEqual(g.positions(21), G.STRAIGHT)
        self.assertTrue(any("triplet" in nm for _, _, nm in g.summary()))

    def test_mixed(self):
        g = G.detect(hits(8, [0, 0.25, 1 / 3, 0.5, 2 / 3, 0.75]))
        self.assertIn(4, g.positions(3)); self.assertIn(3, g.positions(3))


class Kinds(unittest.TestCase):
    def test_kinds_in_twelfths(self):
        self.assertEqual(slot_kind(0), "downbeat"); self.assertEqual(slot_kind(12), "beat")
        self.assertEqual(slot_kind(6), "8th"); self.assertEqual(slot_kind(3), "16th")
        self.assertEqual(slot_kind(8), "triplet"); self.assertEqual(slot_kind(2), "16th triplet")


if __name__ == "__main__":
    unittest.main()
