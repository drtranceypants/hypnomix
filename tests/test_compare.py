"""`hypnomix compare`: this bounce against the previous one. Synthetic songs only; no audio files in the repo."""
import contextlib, hashlib, io, json, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from hypnomix.core import dsp
from hypnomix.ears import compare

SR = 44100


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def song(seed=1, bars=4, bpm=120, hiss=0.01):
    """A B A B: quiet dark parts and loud bright chord parts, a click on every beat, a little stereo spread and a
    broadband hiss so every band has something in it."""
    rng = np.random.default_rng(seed)
    beat = 60 / bpm
    parts = []
    for lab in ("A", "B", "A", "B"):
        n = int(bars * 4 * beat * SR)
        t = np.arange(n) / SR
        if lab == "A":
            x = 0.05 * np.sin(2 * np.pi * 110 * t) + 0.03 * np.sin(2 * np.pi * 220 * t)
        else:
            x = sum(0.08 * np.sin(2 * np.pi * f * t) for f in (440, 554.4, 659.3, 1760, 3520)) + 0.04 * rng.standard_normal(n)
        for b in range(bars * 4):
            i = int(b * beat * SR)
            k = min(int(0.02 * SR), n - i)
            x[i:i + k] += 0.3 * np.exp(-np.arange(k) / (0.003 * SR)) * rng.standard_normal(k)
        parts.append(x)
    x = np.concatenate(parts)
    h = hiss * rng.standard_normal((len(x), 2))
    side = 0.02 * np.sin(2 * np.pi * 300 * np.arange(len(x)) / SR) * np.concatenate([np.zeros(len(x) // 2), np.ones(len(x) - len(x) // 2)])
    return np.stack([x + side, x - side], axis=1) + h


def put(path, y, sr=SR, sub="PCM_24"):
    sf.write(str(path), y, sr, subtype=sub)
    return path


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with mock.patch.object(sys, "argv", ["hypnomix compare"] + [str(a) for a in argv]), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            compare.main()
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            if isinstance(e.code, str):
                err.write(e.code)
    return code, out.getvalue() + err.getvalue()


class Changed(unittest.TestCase):
    """B = A, 2.5 s + 17 samples late, 1.2 dB louder, a brighter top end, and one stretch (the 3rd section) low-passed."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.root = Path(cls.td.name)
        a = song()
        cls.dur = len(a) / SR
        b = dsp.EQ().add("highshelf", 8000, 4.0).apply(a, SR)
        lo, hi = int(16 * SR), int(24 * SR)
        b[lo:hi] = dsp.lowpass(1200, SR) is not None and dsp.filt(b[lo:hi], dsp.lowpass(1200, SR, 4))
        b = b * dsp.undb(1.2)
        cls.delay = int(2.5 * SR) + 17
        b = np.concatenate([np.zeros((cls.delay, 2)), b])
        cls.a, cls.b = put(cls.root / "old.wav", a), put(cls.root / "new.wav", b)
        cls.before = (sha(cls.a), sha(cls.b))
        cls.out = cls.root / "cmp"
        cls.code, cls.text = run([cls.a, cls.b, "--names", "old,new", "--out", cls.out, "--bpm", "120"])
        cls.report = (cls.out / "COMPARE.md").read_text(encoding="utf-8") if (cls.out / "COMPARE.md").exists() else ""
        cls.js = json.loads((cls.out / "COMPARE.json").read_text()) if (cls.out / "COMPARE.json").exists() else {}

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_ran_and_inputs_are_untouched(self):
        self.assertEqual(self.code, 0, self.text)
        self.assertEqual((sha(self.a), sha(self.b)), self.before)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["cmp", "new.wav", "old.wav"])
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["COMPARE.json", "COMPARE.md", "ab"])

    def test_offset_is_found_to_the_sample(self):
        self.assertAlmostEqual(self.js["offset_s"] * SR, self.delay, delta=1)
        self.assertIn("**new starts 2.500 s later**", self.report)
        self.assertIn("to the sample", self.report)

    def test_the_summary_line_comes_first_and_says_the_big_things(self):
        body = [l for l in self.report.splitlines() if l.strip()]
        self.assertEqual(body[0], "# Compare: old against new")
        line = body[1]
        self.assertEqual(line, self.js["summary"])
        self.assertRegex(line, r"^new is \d\.\d dB louder")
        self.assertIn("the 2nd A section changed most", line)          # the low-passed stretch is the song's 3rd section
        self.assertIn("brighter above 8 kHz", line)
        self.assertTrue(line.endswith("."))

    def test_the_numbers_behind_it(self):
        A, B = self.js["a"], self.js["b"]
        self.assertGreater(B["lufs"] - A["lufs"], 1.2)                        # +1.2 dB of gain, and the shelf adds some more
        self.assertLess(B["lufs"] - A["lufs"], 4.0)
        self.assertGreater(B["bands_db"]["air"] - A["bands_db"]["air"], 1.5)
        for key in ("lufs", "loudest_10s_lufs", "true_peak", "crest_db", "plr_db", "lra_lu", "bands_db", "width_db"):
            self.assertIn(key, A)
        self.assertEqual(len(A["bands_db"]), 8)
        for needle in ("## Loudness and peaks", "## Dynamics", "## Tone by band", "## Stereo width by band",
                       "## Loudness by section", "## Where they differ most", "Integrated loudness", "True peak", "Crest"):
            self.assertIn(needle, self.report)

    def test_sections_are_listed_with_both_loudnesses(self):
        secs = self.js["sections"]
        self.assertGreaterEqual(len(secs), 2)
        self.assertLess(secs[0]["start"], 0.5)
        for s in secs:
            self.assertIn("a_lufs", s)
            self.assertIn("b_lufs", s)

    def test_the_spots_are_level_matched_pairs_where_the_change_is(self):
        ab = json.loads((self.out / "ab" / "ab.json").read_text())
        self.assertEqual(sorted(ab), ["spot-1", "spot-2", "spot-3"])
        top = ab["spot-1"]
        self.assertGreater(min(top["end_s"], 24) - max(top["start_s"], 16), 3.0)      # overlaps the low-passed stretch
        for k, row in ab.items():
            fa, fb = self.out / "ab" / row["a"], self.out / "ab" / row["b"]
            self.assertEqual(fa.name, f"{k} A (now).wav")
            ya, sra = sf.read(str(fa))
            yb, srb = sf.read(str(fb))
            self.assertEqual((sra, srb, len(ya)), (SR, SR, len(yb)))
            self.assertAlmostEqual(len(ya) / SR, 6.0, delta=0.05)
            self.assertEqual(sf.info(str(fa)).subtype, "PCM_24")
            self.assertLessEqual(abs(row["matched_db"]), 3.0)
            self.assertLess(abs(dsp.rms_db(ya) - dsp.rms_db(yb)), 3.5)
        starts = sorted(r["start_s"] for r in ab.values())
        self.assertTrue(all(b - a >= 5.9 for a, b in zip(starts, starts[1:])))        # three different stretches
        self.assertIn("ab/spot-1 A (now).wav", self.report)

    def test_refuses_to_write_over_a_report(self):
        code, text = run([self.a, self.b, "--out", self.out])
        self.assertEqual(code, 1)
        self.assertIn("already holds a comparison", text)
        self.assertEqual((sha(self.a), sha(self.b)), self.before)

    def test_an_existing_report_is_refused_before_any_audio_is_read(self):
        with mock.patch.object(compare, "read", side_effect=AssertionError("audio was read before the --out check")):
            code, text = run([self.a, self.b, "--out", self.out])
        self.assertEqual(code, 1)
        self.assertIn("already holds a comparison", text)


class Refusals(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.a = put(self.root / "a.wav", song(1, bars=2))

    def tearDown(self):
        self.td.cleanup()

    def test_different_songs_are_refused_and_force_compares_anyway(self):
        rng = np.random.default_rng(7)
        t = np.arange(len(sf.read(str(self.a))[0])) / SR
        other = np.zeros((len(t), 2))
        for i in range(0, len(t) - SR // 4, SR // 4):                        # a different rhythm and notes
            if rng.random() < 0.6:
                f = float(rng.choice([150, 330, 700, 1500, 3000]))
                k = SR // 5
                other[i:i + k] += (0.2 * np.sin(2 * np.pi * f * np.arange(k) / SR) * np.exp(-np.arange(k) / (0.08 * SR)))[:, None]
        b = put(self.root / "b.wav", other + 0.002 * rng.standard_normal(other.shape))
        code, text = run([self.a, b, "--out", self.root / "o1"])
        self.assertEqual(code, 1)
        self.assertIn("do not look like the same song", text)
        self.assertIn("--force", text)
        self.assertFalse((self.root / "o1").exists())
        code, text = run([self.a, b, "--force", "--out", self.root / "o2"])
        self.assertEqual(code, 0, text)
        self.assertIn("Forced", (self.root / "o2" / "COMPARE.md").read_text(encoding="utf-8"))

    def test_sample_rates_differ(self):
        from scipy.signal import resample_poly
        y = sf.read(str(self.a))[0]
        b = put(self.root / "b48.wav", resample_poly(y, 160, 147, axis=0), 48000)
        before = (sha(self.a), sha(b))
        code, text = run([self.a, b, "--out", self.root / "o1"])
        self.assertEqual(code, 1)
        self.assertIn("44100 Hz", text)
        self.assertIn("48000 Hz", text)
        self.assertIn("--resample", text)
        self.assertFalse((self.root / "o1").exists())
        code, text = run([self.a, b, "--resample", "--out", self.root / "o2"])
        self.assertEqual(code, 0, text)
        md = (self.root / "o2" / "COMPARE.md").read_text(encoding="utf-8")
        self.assertIn("resampled to 44100 Hz", md)
        self.assertIn("similarity 1.0", md.lower().replace("similarity 1.0", "similarity 1.0"))
        self.assertEqual((sha(self.a), sha(b)), before)

    def test_silent_short_and_missing(self):
        sil = put(self.root / "s.wav", np.zeros((SR * 5, 2)))
        code, text = run([self.a, sil, "--out", self.root / "o"])
        self.assertEqual(code, 1)
        self.assertIn("silent", text)
        short = put(self.root / "short.wav", song(1, bars=2)[:SR])
        code, text = run([self.a, short, "--out", self.root / "o"])
        self.assertEqual(code, 1)
        self.assertIn("too short", text)
        code, text = run([self.a, self.root / "nope.wav", "--out", self.root / "o"])
        self.assertEqual(code, 1)
        self.assertIn("not found", text)
        junk = self.root / "junk.wav"
        junk.write_text("not audio")
        code, text = run([self.a, junk, "--out", self.root / "o"])
        self.assertEqual(code, 1)
        self.assertIn("can't read", text)
        self.assertFalse((self.root / "o").exists())

    def test_a_file_that_is_not_audio_gets_a_clean_message(self):
        junk = self.root / "junk.wav"
        junk.write_text("not audio")
        code, text = run([self.a, junk, "--out", self.root / "o"])
        self.assertEqual(code, 1)
        self.assertIn("can't read junk.wav as audio: not an audio file HypnoMix can", text)
        self.assertEqual(text.count("as audio"), 1)               # not the library's message wrapped in ours
        self.assertNotIn(str(self.root), text)                    # no path cut off mid-way
        self.assertNotIn("Traceback", text)

    def test_names_need_two(self):
        code, text = run([self.a, self.a, "--names", "just one", "--out", self.root / "o"])
        self.assertEqual(code, 1)
        self.assertIn("--names", text)

    def test_the_same_file_twice_says_nothing_changed(self):
        code, text = run([self.a, self.a, "--out", self.root / "o"])
        self.assertEqual(code, 0, text)
        md = (self.root / "o" / "COMPARE.md").read_text(encoding="utf-8")
        self.assertIn("hold the same audio", md)
        self.assertFalse((self.root / "o" / "ab").exists())          # nothing differs: no pairs


class Helpers(unittest.TestCase):
    def test_find_lag_both_directions_and_on_a_level_change(self):
        a = song(2, bars=2)
        pad = np.zeros((SR + 5, 2))
        b = np.concatenate([pad, a * 0.5])
        lag, conf = compare.find_lag(a, b, SR)
        self.assertEqual(lag, SR + 5)
        self.assertGreater(conf, 0.5)
        lag, _ = compare.find_lag(b, a, SR)
        self.assertEqual(lag, -(SR + 5))
        self.assertEqual(compare.find_lag(a, a, SR)[0], 0)

    def test_summary_words(self):
        bands = {n: 0.0 for n, _, _ in compare.BANDS}
        A = dict(lufs=-14.0, bands_db=dict(bands), width_db={n: -6.0 for n in bands})
        B = dict(lufs=-14.1, bands_db=dict(bands, sub=1.4), width_db={n: -6.0 for n in bands} | {"bass": -8.0})
        line = compare.summary_line(A, B, ["old", "new"], [], [], False)
        self.assertEqual(line, "new is about as loud as old, 1.4 dB more sub bass (under 60 Hz), a little narrower in the lows.")
        B["lufs"] = -12.8
        B["bands_db"] = dict(bands, air=-2.0)
        self.assertTrue(compare.summary_line(A, B, ["old", "new"], [], [], False).startswith("new is 1.2 dB louder, 2.0 dB darker above 8 kHz"))
        self.assertIn("hold the same audio", compare.summary_line(A, B, ["old", "new"], [], [], True))

    def test_help_is_the_docstring(self):
        r = subprocess.run([sys.executable, "-m", "hypnomix.cli", "compare", "-h"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("This bounce against the previous one", r.stdout)
        self.assertIn("--resample", r.stdout)


if __name__ == "__main__":
    unittest.main()
