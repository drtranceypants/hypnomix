"""Synthetic tests for hypnomix deess and breaths (no audio files needed)."""
import unittest
import numpy as np
from scipy.signal import butter, sosfiltfilt

from hypnomix.studio import deess, breaths

SR = 44100


def band_db(x, lo, hi):
    y = sosfiltfilt(butter(6, [lo, hi], "bandpass", fs=SR, output="sos"), x)
    return 10 * np.log10(np.mean(y ** 2) + 1e-20)


def vowel(n, f0=180, seed=0):
    t = np.arange(n) / SR
    x = sum((0.5 / k) * np.sin(2 * np.pi * f0 * k * t + k) for k in range(1, 20) if f0 * k < 3500)
    return 0.3 * x / np.max(np.abs(x))


class DeessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(1)
        n = 4 * SR
        x = vowel(n)
        noise = sosfiltfilt(butter(4, [6000, 8000], "bandpass", fs=SR, output="sos"), rng.standard_normal(n))
        noise *= 0.25 / np.max(np.abs(noise))
        cls.times = [0.8, 2.0, 3.2]
        cls.dur = 0.12
        for t in cls.times:
            a, b = int(t * SR), int((t + cls.dur) * SR)
            x[a:b] += noise[a:b]
        cls.x = x
        cls.events = deess.analyse(x, SR)
        cls.y = deess.process(x, SR, cls.events, amount=1.0, max_db=8)

    def test_detects_sibilants_at_right_times(self):
        self.assertEqual(len(self.events), 3, self.events)
        for e, t in zip(self.events, self.times):
            self.assertAlmostEqual(e["t"], t, delta=0.015)
            self.assertAlmostEqual(e["dur"], self.dur, delta=0.03)
            lo, hi = e["band_hz"]
            self.assertTrue(lo <= 7000 <= hi, e)

    def test_high_band_reduced(self):
        for t in self.times:
            a, b = int((t + 0.01) * SR), int((t + self.dur - 0.01) * SR)
            drop = band_db(self.x[a:b], 5000, 10000) - band_db(self.y[a:b], 5000, 10000)
            print(f"\n  deess drop at {t}s: {drop:.2f} dB")
            self.assertTrue(6.0 <= drop <= 9.0, drop)

    def test_elsewhere_unchanged(self):
        for a_s, b_s in [(0.1, 0.7), (1.2, 1.9), (2.4, 3.1), (3.5, 3.9)]:
            a, b = int(a_s * SR), int(b_s * SR)
            d = 10 * np.log10(np.mean(self.y[a:b] ** 2) / np.mean(self.x[a:b] ** 2))
            self.assertLess(abs(d), 0.1)
        self.assertTrue(np.array_equal(self.y[: int(0.7 * SR)], self.x[: int(0.7 * SR)]))

    def test_no_sibilants_in_plain_vowel(self):
        self.assertEqual(deess.analyse(vowel(2 * SR), SR), [])


class BreathsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(2)
        ph = int(1.0 * SR); br = int(0.4 * SR)
        breath = sosfiltfilt(butter(2, 900, "highpass", fs=SR, output="sos"), rng.standard_normal(br))
        breath *= 10 ** (-25 / 20) * 0.3 / np.sqrt(np.mean(breath ** 2))   # ~25 dB under the phrase
        cls.x = np.concatenate([vowel(ph), breath, vowel(ph, 200), breath[::-1], vowel(ph, 160)])
        cls.bt = [1.0, 2.4]
        cls.events = breaths.analyse(cls.x, SR)
        cls.y = breaths.process(cls.x, SR, cls.events, reduce_db=8)

    def test_detects_breaths(self):
        self.assertEqual(len(self.events), 2, self.events)
        for e, t in zip(self.events, self.bt):
            self.assertAlmostEqual(e["t"], t, delta=0.04)
            self.assertAlmostEqual(e["dur"], 0.4, delta=0.08)

    def test_breaths_reduced(self):
        for t in self.bt:
            a, b = int((t + 0.06) * SR), int((t + 0.34) * SR)
            drop = 10 * np.log10(np.mean(self.x[a:b] ** 2) / np.mean(self.y[a:b] ** 2))
            print(f"\n  breath drop at {t}s: {drop:.2f} dB")
            self.assertAlmostEqual(drop, 8.0, delta=0.5)

    def test_phrases_unchanged(self):
        for a_s, b_s in [(0.0, 0.95), (1.45, 2.35), (2.85, 3.8)]:
            a, b = int(a_s * SR), int(b_s * SR)
            self.assertTrue(np.array_equal(self.y[a:b], self.x[a:b]))


if __name__ == "__main__":
    unittest.main()
