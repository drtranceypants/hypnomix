"""Pitch tracking: active segment framing, yin tracking on sine + silence, npz cache, median_between."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from hypnomix.core import pitch

SR = 44100


def write_sine_and_silence(path, freq=220.0, tone_s=1.0, silence_s=1.0, sr=SR):
    t = np.arange(int(tone_s * sr)) / sr
    tone = 0.5 * np.sin(2 * np.pi * freq * t)
    silence = np.zeros(int(silence_s * sr))
    y = np.concatenate([tone, silence]).astype(np.float32)
    sf.write(str(path), y, sr)


class ActiveSegments(unittest.TestCase):
    def test_all_silent_returns_empty(self):
        self.assertEqual(pitch.active_segments(np.full(100, -np.inf), floor_db=35.0, hop_s=0.01), [])

    def test_one_loud_stretch_padded_and_clipped_to_bounds(self):
        db = np.full(20, -80.0)
        db[2:5] = -10.0
        self.assertEqual(pitch.active_segments(db, floor_db=35.0, hop_s=0.01, pad_s=0.05), [(0, 10)])

        db = np.full(20, -80.0)
        db[16:19] = -10.0
        self.assertEqual(pitch.active_segments(db, floor_db=35.0, hop_s=0.01, pad_s=0.05), [(11, 20)])

    def test_gap_merges_below_merge_s_and_splits_above(self):
        db_short = np.full(80, -80.0)
        db_short[10:20] = -10.0
        db_short[25:35] = -10.0
        self.assertEqual(
            pitch.active_segments(db_short, floor_db=35.0, hop_s=0.01, pad_s=0.02, merge_s=0.10),
            [(8, 37)],
        )

        db_long = np.full(80, -80.0)
        db_long[10:20] = -10.0
        db_long[40:50] = -10.0
        self.assertEqual(
            pitch.active_segments(db_long, floor_db=35.0, hop_s=0.01, pad_s=0.02, merge_s=0.10),
            [(8, 22), (38, 52)],
        )


class TrackAndCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.wav = self.root / "tone.wav"
        write_sine_and_silence(self.wav)
        self.cache_dir = self.root / "cache"
        p = mock.patch.object(pitch, "cache_dir", lambda: self.cache_dir)
        p.start()
        self.addCleanup(p.stop)

    def test_track_sine_then_silence(self):
        times, f0, level_db = pitch.track(self.wav)
        self.assertEqual(len(times), len(f0))
        self.assertEqual(len(times), len(level_db))
        self.assertTrue(np.all(np.diff(times) > 0))

        sine_f0 = f0[times < 1.0]
        sine_valid = sine_f0[np.isfinite(sine_f0)]
        self.assertGreater(len(sine_valid), len(sine_f0) // 2)
        self.assertAlmostEqual(float(np.median(sine_valid)), 220.0, delta=220.0 * 0.02)

        silent_f0 = f0[times >= 1.1]
        self.assertGreater(len(silent_f0), 0)
        self.assertTrue(np.all(np.isnan(silent_f0)))

    def test_cache_reuses_single_npz_and_respects_cache_false(self):
        nocache = self.root / "nocache"
        nocache.mkdir()
        with mock.patch.object(pitch, "cache_dir", lambda: nocache):
            pitch.track(self.wav, cache=False)
        self.assertEqual(list(nocache.iterdir()), [])

        t1, f0_1, db1 = pitch.track(self.wav)
        self.assertEqual(len(list(self.cache_dir.glob("*.npz"))), 1)

        with mock.patch.object(sf, "read", side_effect=AssertionError("expected cache hit")):
            t2, f0_2, db2 = pitch.track(self.wav)
        self.assertEqual(len(list(self.cache_dir.glob("*.npz"))), 1)
        self.assertTrue(np.array_equal(t1, t2))
        self.assertTrue(np.array_equal(f0_1, f0_2, equal_nan=True))
        self.assertTrue(np.array_equal(db1, db2))

    def test_median_between_sine_and_silence(self):
        m_sine = pitch.median_between(self.wav, 0.1, 0.9)
        self.assertIsNotNone(m_sine)
        self.assertAlmostEqual(m_sine, 220.0, delta=220.0 * 0.02)
        self.assertIsNone(pitch.median_between(self.wav, 1.1, 1.9))


if __name__ == "__main__":
    unittest.main()
