"""`sections` must find real section changes, and say so when it cannot (synthetic audio only)."""
import tempfile, unittest
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.ears import sections

SR = 44100


def build(plan, bpm=120, seed=0):
    """plan: [(kind, bars)] with kind 'q' (quiet dark tone) or 'l' (loud bright chord + noise)."""
    rng = np.random.default_rng(seed)
    beat = 60 / bpm
    parts = []
    for kind, bars in plan:
        n = int(bars * 4 * beat * SR)
        t = np.arange(n) / SR
        if kind in ("q", "m", "s"):   # q quiet; m/s the same tone louder by 6 / 3 dB
            x = (0.05 * np.sin(2 * np.pi * 110 * t) + 0.03 * np.sin(2 * np.pi * 220 * t)) * {"q": 1, "m": 2, "s": 1.41}[kind]
        else:
            x = sum(0.08 * np.sin(2 * np.pi * f * t) for f in (440, 554.4, 659.3, 1760)) + 0.05 * rng.standard_normal(n)
        click = np.zeros(n)
        cl = np.exp(-np.arange(int(0.02 * SR)) / (0.003 * SR)) * rng.standard_normal(int(0.02 * SR))
        for b in range(bars * 4):
            i = int(b * beat * SR)
            click[i:i + len(cl)] += 0.3 * cl[: n - i]
        parts.append(x + click)
    y = np.concatenate(parts) * 0.8
    return np.stack([y, y], axis=1)


class Boundaries(unittest.TestCase):
    def run_plan(self, plan):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "s.wav"
            dsp.save(p, build(plan), SR)
            return sections.analyse(p, bpm=120)

    def test_uneven_sections_are_found(self):
        r = self.run_plan([("q", 8), ("l", 4), ("q", 8), ("l", 4)])
        self.assertFalse(r["even_split"])
        self.assertEqual([s["bars"] for s in r["sections"]], [8, 4, 8, 4])

    def test_other_lengths(self):
        r = self.run_plan([("q", 6), ("l", 10), ("q", 4), ("l", 6), ("q", 6)])
        self.assertFalse(r["even_split"])
        self.assertEqual([s["bars"] for s in r["sections"]], [6, 10, 4, 6, 6])

    def test_audit_layout_quiet_loud(self):
        """the audit's own layout: 8 quiet, 4 loud, 8 quiet, 4 loud (one third loud, about 12 dB louder)"""
        r = self.run_plan([("q", 8), ("l", 4), ("q", 8), ("l", 4)])
        self.assertEqual([s["bars"] for s in r["sections"]], [8, 4, 8, 4])
        self.assertGreater(r["sections"][1]["lufs"] - r["sections"][0]["lufs"], 6)

    def test_milder_contrast_is_found(self):
        r = self.run_plan([("q", 8), ("m", 4), ("q", 8), ("m", 4)])   # only 6 dB louder, same tone
        self.assertFalse(r["even_split"])
        self.assertEqual([s["bars"] for s in r["sections"]], [8, 4, 8, 4])

    def test_flat_loud_song_is_not_split(self):
        r = self.run_plan([("l", 24)])
        self.assertTrue(r["even_split"])

    def test_no_change_says_so(self):
        r = self.run_plan([("q", 24)])
        self.assertTrue(r["even_split"])
        self.assertIn("split evenly", r["note"])
        self.assertTrue(any(w in sections.EVEN_NOTE for w in ("split evenly",)))


if __name__ == "__main__":
    unittest.main()
