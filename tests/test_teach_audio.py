"""Teacher mode's 'Hear it' demos (hypnomix/app/teach_audio.py): every demo renders, short, quiet enough, the same every time."""
import io
import os
import tempfile
import unittest
import wave
from unittest import mock

import numpy as np

from hypnomix.app import teach_audio as TA
from hypnomix.app import teacher as T


def pcm(b):
    w = wave.open(io.BytesIO(b))
    return w, np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, w.getnchannels()) / 32768.0


_RENDERED = {}


def rendered(demo):
    """All variants of a demo as WAV bytes, rendered once for the whole file (the demos are deterministic)."""
    if demo not in _RENDERED:
        _RENDERED[demo] = {k: TA.render(demo, k) for k, _ in TA.DEMOS[demo]["variants"]}
    return _RENDERED[demo]


class Demos(unittest.TestCase):
    def test_every_demo_renders_to_a_clean_short_wav(self):
        self.assertGreaterEqual(len(TA.DEMOS), 22)
        for demo, d in TA.DEMOS.items():
            self.assertGreaterEqual(len(d["variants"]), 2, demo)
            self.assertTrue(d["listen"] and d["title"], demo)
            ys = TA.render_all(demo)
            self.assertEqual(sorted(ys), sorted(k for k, _ in d["variants"]), demo)
            for v in ys:
                w, y = pcm(rendered(demo)[v])
                self.assertEqual((w.getframerate(), w.getsampwidth(), w.getnchannels()), (44100, 2, 2), (demo, v))
                self.assertLessEqual(len(y) / 44100, 8.001, (demo, v))
                self.assertGreater(len(y) / 44100, 1.0, (demo, v))
                self.assertLess(np.max(np.abs(y)), 0.95, (demo, v))         # nothing near full scale: never clips
                self.assertGreater(np.max(np.abs(y)), 0.01, (demo, v))      # and it isn't silent

    def test_the_same_bytes_every_time(self):
        for demo, d in TA.DEMOS.items():
            v = d["variants"][0][0]
            self.assertEqual(TA.render(demo, v), rendered(demo)[v], demo)

    def test_a_differs_from_b(self):
        for demo, d in TA.DEMOS.items():
            keys = [k for k, _ in d["variants"]]
            self.assertEqual(len(set(rendered(demo).values())), len(keys), demo)

    def test_pairs_are_level_matched_unless_loudness_is_the_point(self):
        from hypnomix.core import dsp
        for demo, d in TA.DEMOS.items():
            L = [dsp.lufs(y, TA.SR) for y in TA.render_all(demo).values()]
            if d["match"] == "loudness":
                self.assertLess(max(L) - min(L), 0.6, (demo, L))
        # the demos where loudness is the point really do differ
        L = {k: dsp.lufs(y, TA.SR) for k, y in TA.render_all("loudness-bias").items()}
        self.assertAlmostEqual(L["b"] - L["a"], 2.0, delta=0.3)
        self.assertAlmostEqual(L["c"], L["a"], delta=0.3)               # the tone change is matched to the original
        p = {k: dsp.lufs(y, TA.SR) for k, y in TA.render_all("polarity").items()}
        self.assertLess(p["b"], p["a"] - 10)                            # flipped: the two mics cancel

    def test_the_cache_is_where_diskcare_looks(self):
        from hypnomix.app import diskcare
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HYPNOMIX_HOME": td}):
            first = TA.wav("sine-pitch", "f1k")
            self.assertTrue((diskcare.hx_home() / "cache" / "teach").is_dir())
            self.assertTrue(list((diskcare.hx_home() / "cache" / "teach").glob("sine-pitch-*.wav")))
            self.assertEqual(TA.wav("sine-pitch", "f1k"), first)         # from the cache this time
            with self.assertRaises(KeyError):
                TA.wav("sine-pitch", "nope")
            with self.assertRaises(KeyError):
                TA.wav("no-such-demo", "a")

    def test_lessons_only_use_demos_that_exist(self):
        for ch in T.CHAPTERS:
            for s in ch["steps"]:
                for h in s.get("hear", []):
                    self.assertIn(h if isinstance(h, str) else h["demo"], TA.DEMOS, s["id"])


if __name__ == "__main__":
    unittest.main()
