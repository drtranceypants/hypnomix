"""Synthetic checks for `hypnomix sections` and `hypnomix match` (no audio files in the repo)."""
import tempfile, unittest
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.ears import match, sections

SR = 44100


def song(bpm=120, bars=8):
    """A B A B, 8 bars each. A: quiet, dark tone; B: loud, bright chord + noise; 2nd B 3 dB down."""
    rng = np.random.default_rng(0)
    beat = 60 / bpm
    bar_s = 4 * beat
    parts = []
    for k, (lab, gain) in enumerate([("A", 0), ("B", 0), ("A", 0), ("B", -3)]):
        n = int(bars * bar_s * SR)
        t = np.arange(n) / SR
        if lab == "A":
            x = 0.05 * np.sin(2 * np.pi * 110 * t) + 0.03 * np.sin(2 * np.pi * 220 * t)
        else:
            x = sum(0.08 * np.sin(2 * np.pi * f * t) for f in (440, 554.4, 659.3, 1760)) + 0.05 * rng.standard_normal(n)
        click = np.zeros(n)
        cl = np.exp(-np.arange(int(0.02 * SR)) / (0.003 * SR)) * rng.standard_normal(int(0.02 * SR))
        for b in range(bars * 4):
            i = int(b * beat * SR)
            click[i:i + len(cl)] += 0.3 * cl[: n - i]
        parts.append((x + click) * dsp.undb(gain))
    y = np.concatenate(parts)
    return np.stack([y, y], axis=1), bar_s


def pinkish(n, rng):
    w = rng.standard_normal(n)
    f = np.fft.rfftfreq(n, 1 / SR)
    W = np.fft.rfft(w) / np.sqrt(np.maximum(f, 20))
    return np.fft.irfft(W, n)


class SectionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        y, cls.bar_s = song()
        cls.path = Path(cls.td.name) / "a b song.wav"
        dsp.save(cls.path, y * 0.8, SR)
        cls.r = sections.analyse(cls.path, bpm=120)

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_boundaries(self):
        starts = [s["start"] for s in self.r["sections"]][1:]
        truth = [8 * self.bar_s, 16 * self.bar_s, 24 * self.bar_s]
        print("\nsections:", [(s["start_mss"], s["label"], s["lufs"]) for s in self.r["sections"]])
        for t in truth:
            self.assertLessEqual(min(abs(s - t) for s in starts), self.bar_s + 0.05, (t, starts))
        self.assertGreaterEqual(len(self.r["sections"]), 4)
        self.assertLessEqual(len(self.r["sections"]), 12)

    def test_grouping_and_quieter_repeat(self):
        secs = self.r["sections"]
        bs = [s for s in secs if abs(s["start"] - 8 * self.bar_s) <= self.bar_s or abs(s["start"] - 24 * self.bar_s) <= self.bar_s]
        self.assertEqual(len(bs), 2)
        self.assertEqual(bs[0]["label"], bs[1]["label"])
        self.assertEqual(bs[0]["role"], "chorus-like")
        hit = [f for f in self.r["findings"] if f["kind"] == "repeat-level" and "2nd" in f["problem"] and "quieter" in f["problem"]]
        print("findings:", [f["problem"] for f in self.r["findings"]])
        self.assertTrue(hit)
        for f in self.r["findings"]:
            self.assertEqual(set(f), {"id", "tool", "kind", "severity", "track", "where", "problem", "fix", "applies"})
            self.assertIn(f["severity"], ("low", "medium", "info"))


class MatchTest(unittest.TestCase):
    def test_low_band_and_width(self):
        rng = np.random.default_rng(1)
        n = 30 * SR
        c, s = pinkish(n, rng), pinkish(n, rng)
        ref = np.stack([c + 0.5 * s, c - 0.5 * s], axis=1)
        ref *= 0.25 / np.max(np.abs(ref))
        mid, side = (ref[:, 0] + ref[:, 1]) / 2, (ref[:, 0] - ref[:, 1]) / 2
        side *= dsp.undb(-6)                               # narrower
        mix = np.stack([mid + side, mid - side], axis=1)
        mix = dsp.filt(mix, dsp.shelf(150, 4.0, SR))       # +4 dB low shelf
        with tempfile.TemporaryDirectory() as td:
            pm, pr = Path(td) / "mix.wav", Path(td) / "ref.wav"
            dsp.save(pm, mix * 0.5, SR)
            dsp.save(pr, ref, SR)
            r = match.analyse(pm, pr)
        print("\nmatch:", [f["problem"] for f in r["findings"]])
        low = [f for f in r["findings"] if f["kind"] in ("band-sub", "band-bass") and "heavier" in f["problem"]]
        self.assertTrue(low)
        d = r["numbers"]["band_gap_db"]["bass"]
        print("bass gap", d, "sub gap", r["numbers"]["band_gap_db"]["sub"])
        self.assertTrue(2.5 < d < 5.0, d)
        w = [f for f in r["findings"] if f["kind"] == "width"]
        self.assertTrue(w and "narrower" in w[0]["problem"])
        for f in r["findings"]:
            self.assertTrue(f["id"].startswith("match-"))
            self.assertEqual(f["applies"], "manual")


if __name__ == "__main__":
    unittest.main()
