"""Regression tests: a timing nudge must not move the rest of the clip; one lead rule everywhere."""
import unittest
import numpy as np
from hypnomix.session import timing as T
from hypnomix.engineer.roles import choose_lead


class _El:
    """Just enough of a clip's <WarpMarkers> element for add_marker / restore."""
    def __init__(self, markers):
        self.kids = [self._m(i, s, b) for i, (b, s) in enumerate(markers)]

    @staticmethod
    def _m(i, s, b):
        class M(dict):
            def get(self, k, d=None): return dict.get(self, k, d)
            def set(self, k, v): self[k] = v
        return M(Id=str(i), SecTime=repr(s), BeatTime=repr(b))

    def find(self, _): return self
    def findall(self, _): return list(self.kids)
    def __iter__(self): return iter(self.kids)
    def __len__(self): return len(self.kids)
    def makeelement(self, tag, attrs): return self._m(attrs["Id"], float(attrs["SecTime"]), float(attrs["BeatTime"]))
    def insert(self, i, e): self.kids.insert(i, e)
    def remove(self, e): self.kids.remove(e)
    def append(self, e): self.kids.append(e)


def clip(markers):
    return dict(el=_El(markers), markers=list(markers), warped=True, start=0.0, end=400.0, ls=0.0, rel=0.0,
                loop_on=False)


class TimingDrift(unittest.TestCase):
    def test_nudge_past_last_marker_keeps_the_rest_of_the_clip(self):
        tempo = 120.0
        ci = clip([(0.0, 0.0), (0.03125, 0.015625)])       # Live's usual 2 markers near the start
        hits = [dict(sec=s, clip=ci) for s in (10.0, 10.5, 11.0)]
        issue = dict(hit=hits[1], move=0.02)
        before = list(ci["markers"])
        done, skipped = T.apply([issue], [("t", None, hits)], tempo, 1.0)
        self.assertEqual(len(done), 1, skipped)
        grid = np.arange(11.0, 300.0, 0.01)
        old = dict(ci); old["markers"] = before
        dev = np.abs(T.file_to_arr(ci, grid, tempo) - T.file_to_arr(old, grid, tempo)).max() * 60 / tempo * 1000
        self.assertLess(dev, 0.5, "audio after the nudged hit moved")


class Lead(unittest.TestCase):
    def test_clear_vowel_lead_wins(self):
        self.assertEqual(choose_lead([("a", 18, 30), ("b", 14, 90)]), "a")

    def test_close_vowels_fall_back_to_singing_time(self):
        # Ashes to Dust remix: cleaned copies 14.8 / 15.8 / 15.2; the lead (12) sings longest
        self.assertEqual(choose_lead([("12", 14.8, 45.3), ("13", 15.8, 34.9), ("14", 15.2, 31.6)]), "12")


if __name__ == "__main__":
    unittest.main()
