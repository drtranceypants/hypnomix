"""Mastering stages on synthetic audio: dynamic EQ, multiband width, limiter modes, dither, rebalance, tonal targets."""
import json, os, tempfile, unittest
from pathlib import Path

import numpy as np

SR = 44100
_patch = None


def setUpModule():
    """No ffmpeg round trips in these tests (the codec-safe ceiling has its own path in master)."""
    global _patch
    from unittest import mock
    from hypnomix.engineer import master
    _patch = mock.patch.object(master, "codec_worst", lambda *a, **k: None)
    _patch.start()


def tearDownModule():
    _patch.stop()


def tone(f, secs, amp=0.5, sr=SR):
    t = np.arange(int(secs * sr)) / sr
    return np.sin(2 * np.pi * f * t) * amp


def band_rms(y, f0, sr=SR, q=4.0):
    from hypnomix.core import dsp
    from scipy.signal import butter, sosfilt
    sos = butter(4, [f0 / 1.2, f0 * 1.2], "bandpass", fs=sr, output="sos")
    return dsp.rms_db(sosfilt(sos, y, axis=0))


class TestSpectralEngine(unittest.TestCase):
    def test_identity(self):
        from hypnomix.engineer import stages
        y = np.random.default_rng(1).standard_normal((SR * 2 + 77, 2)) * 0.2
        out = stages.Spectral(y, SR).apply(lambda a, b, X: X)
        self.assertLess(np.max(np.abs(out - y)), 1e-12)


class TestDynEQ(unittest.TestCase):
    def test_only_acts_above_threshold(self):
        from hypnomix.core import dsp
        from hypnomix.engineer import stages
        # 1 kHz tone: 2 s quiet (-30 dBFS RMS), 2 s loud (-9 dBFS RMS), plus quiet 5 kHz content that must pass
        quiet, loud = tone(1000, 2, 0.045), tone(1000, 2, 0.5)
        x = np.concatenate([quiet, loud]) + tone(5000, 4, 0.05)
        y = np.stack([x, x], axis=1)
        out, rep = stages.dyneq(y, SR, [dict(freq=1000, thresh=-20, ratio=4, q=2, range=12)])
        q0, q1 = slice(int(0.3 * SR), int(1.7 * SR)), slice(int(2.5 * SR), int(3.8 * SR))
        self.assertLess(np.max(np.abs(out[q0] - y[q0])), 1e-3)          # below threshold: untouched
        cut = band_rms(y[q1], 1000) - band_rms(out[q1], 1000)
        self.assertGreater(cut, 5)                                       # (−9 − −20) × 0.75 ≈ 8 dB
        self.assertLess(cut, 12.5)
        self.assertLess(abs(band_rms(y[q1], 5000) - band_rms(out[q1], 5000)), 0.5)   # other band left alone
        self.assertGreater(rep["bands"][0]["pct_active"], 30)

    def test_parse(self):
        from hypnomix.engineer import stages
        b = stages.parse_dyneq("180:-24:2:1.5,3k:-30:3:2:4")
        self.assertEqual(b[1]["freq"], 3000)
        self.assertEqual(b[1]["range"], 4)
        with self.assertRaises(ValueError):
            stages.parse_dyneq("180")


class TestWidthBands(unittest.TestCase):
    def test_mono_untouched_side_scaled(self):
        from hypnomix.engineer import stages
        m = np.random.default_rng(2).standard_normal(SR * 2) * 0.2
        mono = np.stack([m, m], axis=1)
        out, _ = stages.width_bands(mono, SR, [dict(lo=200, hi=2000, amount=0.0), dict(lo=5000, hi=16000, amount=1.5)])
        self.assertLess(np.max(np.abs(out - mono)), 1e-12)
        s = tone(8000, 2, 0.2)
        st = np.stack([m * 0.1 + s, m * 0.1 - s], axis=1)              # side content at 8 kHz
        out, _ = stages.width_bands(st, SR, [dict(lo=5000, hi=16000, amount=1.5)])
        side_in = (st[:, 0] - st[:, 1]) / 2
        side_out = (out[:, 0] - out[:, 1]) / 2
        mid = slice(SR // 2, SR + SR // 2)
        self.assertAlmostEqual(np.std(side_out[mid]) / np.std(side_in[mid]), 1.5, delta=0.05)


class TestLimiterModes(unittest.TestCase):
    def test_modes_respect_ceiling_and_report(self):
        from hypnomix.core import dsp
        from hypnomix.engineer import master as M
        rng = np.random.default_rng(3)
        n = SR * 8
        t = np.arange(n) / SR
        kick = np.sin(2 * np.pi * 60 * t) * np.exp(-(t % 0.5) * 14)
        y = np.stack([kick * 0.7, kick * 0.7], axis=1) + rng.standard_normal((n, 2)) * 0.03
        for mode in ("clean", "punch", "loud"):
            out, before, after, log = M.master(y, SR, -11, -1.0, glue_gr=0, opts=dict(limiter_mode=mode))
            self.assertLessEqual(dsp.true_peak(out, SR), -0.95, mode)
            self.assertLess(abs(after["lufs"] - -11), 0.5, mode)
            steps = [s for s, _, _ in log]
            self.assertIn("Loudness vs damage", steps)
            if mode != "clean":
                self.assertIn("Clipper", steps)
                self.assertGreater(after["settings"]["tradeoff"]["samples_clipped"], 0)

    def test_codec_loop_cannot_run_away(self):
        """Encodes that get worse as the ceiling drops: keep the better attempt, never go 3 dB under the ceiling."""
        from unittest import mock
        from hypnomix.engineer import master as M
        vals = iter([0.8, 1.6, 2.4, 3.0, 3.5])
        y = np.random.default_rng(9).standard_normal((SR * 3, 2)) * 0.1
        with mock.patch.object(M, "codec_worst", lambda *a, **k: next(vals)):
            out, before, after, log = M.master(y, SR, -10, -1.0, glue_gr=0, opts=dict(limiter_mode="punch"))
        used = after["settings"]["limiter"]["ceiling_dbtp"]
        self.assertGreaterEqual(used, -4.0)
        self.assertEqual(used, -1.0)                      # the first attempt measured best
        self.assertTrue(any("kept" in t for s_, t, _ in log if s_ == "Codec-safe ceiling"))

    def test_amount_zero_is_bypass(self):
        from hypnomix.engineer import master as M
        y = np.random.default_rng(4).standard_normal((SR * 3, 2)) * 0.05
        out, before, after, log = M.master(y, SR, -9, -1.0, warmth=0.5, width=1.4,
                                           opts=dict(amount=0, harsh=True, dyneq="1000:-40:4:1"))
        self.assertEqual(out.shape, y.shape)
        self.assertLess(np.max(np.abs(out - y)), 1e-9)


class TestDither(unittest.TestCase):
    def test_lsbs_only(self):
        from hypnomix.core import dsp
        y = np.stack([tone(440, 1, 0.3), tone(550, 1, 0.3)], axis=1)
        for bits in (16, 24):
            lsb = 1 / 2 ** (bits - 1)
            plain = dsp.quantise(y, bits, "off")
            for kind in ("tpdf", "shaped"):
                q = dsp.quantise(y, bits, kind, seed=1)
                self.assertTrue(np.allclose(q / lsb, np.round(q / lsb)), (bits, kind))   # on the grid
                self.assertLessEqual(np.max(np.abs(q - y)) / lsb, 3.01, (bits, kind))
                self.assertGreater(np.mean(q != plain), 0.1, (bits, kind))               # it does something
        # shaped: less noise at low frequencies than flat TPDF
        z = np.zeros((SR, 1)) + 0.1
        e_t = dsp.quantise(z, 16, "tpdf", 1) - z
        e_s = dsp.quantise(z, 16, "shaped", 1) - z
        lo = lambda e: np.abs(np.fft.rfft(e[:, 0]))[:int(len(e) * 2000 / SR)].mean()
        self.assertLess(lo(e_s), lo(e_t))

    def test_save_dither_option(self):
        import soundfile as sf
        from hypnomix.core import dsp
        y = np.stack([tone(440, 0.5, 0.3)] * 2, axis=1)
        with tempfile.TemporaryDirectory() as td:
            p = dsp.save(Path(td) / "a.wav", y, SR, 24, dither="tpdf")
            z, _ = sf.read(str(p), always_2d=True)
            self.assertLess(np.max(np.abs(z - y)), 3 / 2 ** 23)


class TestRebalance(unittest.TestCase):
    def fake_separator(self, mix):
        """Not a real separation: three filtered parts plus leftovers, so the stems do NOT sum to the mix."""
        from hypnomix.core import dsp
        lo = dsp.filt(mix, dsp.lowpass(150, SR, 2))
        hi = dsp.filt(mix, dsp.highpass(4000, SR, 2))
        mid = dsp.filt(mix, dsp.highpass(300, SR, 2)) * 0.7
        return dict(bass=lo, drums=hi, vocals=mid, other=mix * 0.1)

    def test_identity_when_gains_zero(self):
        from hypnomix.engineer import rebalance as R
        mix = np.random.default_rng(5).standard_normal((SR * 2, 2)) * 0.1
        stems = self.fake_separator(mix)
        out, rep = R.rebalance(mix, stems, {}, sr=SR)
        self.assertLess(np.max(np.abs(out - mix)), 1e-12)
        self.assertTrue(rep["identity_error_db"] is None or rep["identity_error_db"] < -200)
        out, rep = R.rebalance(mix, stems, {"bass": 3.0}, sr=SR)
        self.assertGreater(np.max(np.abs(out - mix)), 1e-3)

    def test_true_peak_safe(self):
        from hypnomix.core import dsp
        from hypnomix.engineer import rebalance as R
        mix = np.stack([tone(100, 2, 0.8)] * 2, axis=1)
        stems = dict(bass=mix.copy(), drums=mix * 0, vocals=mix * 0, other=mix * 0)
        for safety in ("gain", "limit"):
            out, rep = R.rebalance(mix, stems, {"bass": 6.0}, ceiling=-1.0, safety=safety, sr=SR)
            self.assertLessEqual(dsp.true_peak(out, SR), -0.99)


class TestTonal(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        os.environ["HYPNOMIX_HOME"] = self.td.name
        import importlib
        from hypnomix.core import paths
        importlib.reload(paths)
        from hypnomix.ears import tonal
        importlib.reload(tonal)
        self.tonal = tonal

    def tearDown(self):
        os.environ.pop("HYPNOMIX_HOME", None)
        import importlib
        from hypnomix.core import paths
        importlib.reload(paths)
        self.td.cleanup()

    def pink(self, seed, tilt=0.0, secs=6):
        from hypnomix.core import dsp
        x = np.random.default_rng(seed).standard_normal((SR * secs, 2))
        y = dsp.filt(x, dsp.lowpass(4000, SR, 1)) * 0.3
        if tilt:
            y = dsp.EQ().add("highshelf", 4000, tilt).apply(y, SR)
        return y

    def test_build_and_check(self):
        T = self.tonal
        m = {f"s{i}": T.measure(self.pink(i), SR) for i in range(3)}
        t = T.build(list(m), name="unit", measured=m)
        p = T.save_target(t)
        self.assertTrue(p.exists() and str(p).startswith(self.td.name))
        t2 = T.load_target("unit")
        self.assertEqual(len(t2["third"]), 30)
        self.assertEqual(len(T.target_bands("unit")), 8)
        for b in t2["eight"]:
            self.assertLessEqual(b["low_db"], b["mean_db"] - 0.99)
            self.assertGreaterEqual(b["high_db"], b["mean_db"] + 0.99)
        _, inside = T.check(T.measure(self.pink(9), SR), t2)
        bright = T.measure(self.pink(10, tilt=8.0), SR)
        res, out = T.check(bright, t2)
        self.assertLessEqual(len(inside), 1)
        self.assertTrue(any(f["eq"]["gain"] < 0 and f["eq"]["freq"] >= 2500 for f in out), out)
        self.assertTrue(all(abs(f["eq"]["gain"]) <= 3.0 for f in out))
        _, half = T.check(bright, t2, amount=50)
        self.assertTrue(all(abs(f["eq"]["gain"]) <= 1.5 for f in half))

    def test_stabilize_moves_only_outside(self):
        from hypnomix.engineer import stages
        T = self.tonal
        m = {f"s{i}": T.measure(self.pink(i), SR) for i in range(3)}
        t = T.build(list(m), name="unit", measured=m)
        y = self.pink(20)
        out, rep = stages.stabilize(y, SR, t)
        self.assertLess(max(abs(b["min_db"]) + abs(b["max_db"]) for b in rep["bands"]), 0.6)
        bright = self.pink(21, tilt=8.0)
        out, rep = stages.stabilize(bright, SR, t, max_cut=3.0, speed_s=0.5)
        air = [b for b in rep["bands"] if b["band"] in ("presence", "air")]
        self.assertTrue(any(b["min_db"] < -1.0 for b in air), rep["bands"])
        self.assertTrue(all(b["min_db"] >= -3.01 for b in rep["bands"]))


class TestHarsh(unittest.TestCase):
    def test_finds_buildup_and_cuts_only_there(self):
        from hypnomix.engineer import stages
        rng = np.random.default_rng(7)
        n = SR * 6
        x = rng.standard_normal(n) * 0.1
        burst = np.zeros(n)
        a, b = int(3.0 * SR), int(4.0 * SR)
        burst[a:b] = tone(3150, 1.0, 0.25)
        y = np.stack([x + burst, x + burst], axis=1)
        out, rep = stages.harsh(y, SR)
        self.assertTrue(rep["events"])
        e = rep["events"][0]
        self.assertTrue(2.8 <= e["start_s"] <= 3.3 and 3.7 <= e["end_s"] <= 4.3, e)
        self.assertLess(band_rms(out[a + SR // 4:b - SR // 4], 3150), band_rms(y[a + SR // 4:b - SR // 4], 3150) - 1)
        q = slice(int(0.5 * SR), int(2.0 * SR))
        self.assertLess(np.max(np.abs(out[q] - y[q])), 1e-3)


class TestPlanStages(unittest.TestCase):
    def test_new_stages_are_findings(self):
        from hypnomix.engineer import master as M
        from hypnomix.workflow import plan as P
        y = np.random.default_rng(8).standard_normal((SR * 3, 2)) * 0.05
        _, _, _, log = M.master(y, SR, -14, -1, opts=dict(harsh=True, dyneq="1000:-40:2:1", width_bands="5000:16000:1.2",
                                                         limiter_mode="punch", dither="shaped"))
        fs = P.stage_findings(log, M.KEYS, "master", "x.wav", dict(target=-14, opts={}))
        kinds = {f["kind"] for f in fs}
        for k in ("harsh", "dyneq", "widthbands", "limiter", "dither"):
            self.assertIn(k, kinds)
        self.assertTrue(all(f["plan"]["key"] == f["kind"] for f in fs))


if __name__ == "__main__":
    unittest.main()
