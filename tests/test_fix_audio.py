"""Audio robustness: a file with broken samples, no samples or too many channels, a low sample rate, and an output
folder that cannot be written all end in ONE plain sentence and exit code 2 (never a traceback, never a half-written or
silent result reported as fine). Inputs are built in temp folders; nothing here needs audio files in the repo."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix import cli
from hypnomix.core import dsp, paths
from hypnomix.session import distortion as D

ROOT = Path(__file__).resolve().parent.parent
SR = 44100


def tone(sr=SR, seconds=3.0):
    t = np.arange(int(seconds * sr)) / sr
    return (np.sin(2 * np.pi * 220 * t) * 0.3).astype("float32")


class Base(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="hx-fix-audio-"))
        self.addCleanup(lambda: (self.chmod_all(self.td), shutil.rmtree(self.td, ignore_errors=True)))
        for d in ("fakehome", "home", "work"):
            (self.td / d).mkdir()

    @staticmethod
    def chmod_all(top):
        for root, dirs, _ in os.walk(top):
            for d in dirs:
                try:
                    os.chmod(os.path.join(root, d), 0o755)
                except OSError:
                    pass

    def hx(self, *args):
        env = dict(os.environ, HOME=str(self.td / "fakehome"), HYPNOMIX_HOME=str(self.td / "home"),
                   HYPNOMIX_APP_HOME=str(self.td / "work"), HYPNOMIX_USER_HOME=str(self.td / "fakehome"),
                   HYPNOMIX_DISKCARE="off", PYTHONPATH=str(ROOT))
        env.pop("HYPNOMIX_DEBUG", None)
        env.pop("HYPNOMIX_OUT", None)
        r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True,
                           cwd=str(self.td), env=env)
        return r.returncode, r.stdout, r.stderr

    def wav(self, name, y, sr=SR, subtype="FLOAT"):
        p = self.td / name
        sf.write(str(p), y, sr, subtype=subtype)
        return p

    def assert_one_sentence(self, rc, err, *words):
        self.assertEqual(rc, 2, err)
        self.assertNotIn("Traceback", err)
        lines = [l for l in err.strip().splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, err)
        for w in words:
            self.assertIn(w, err)


class Loader(Base):
    def test_nan_and_inf_are_refused_with_a_count_and_a_time(self):
        y = tone(); y[SR] = np.nan; y[SR + 1] = np.inf
        p = self.wav("bad.wav", y)
        with self.assertRaises(dsp.AudioReadError) as cm:
            dsp.load(p)
        msg = str(cm.exception)
        self.assertIn("2 broken samples", msg)
        self.assertIn("0:01.00", msg)
        self.assertIn("export it again", msg)
        y2 = tone(); y2[5] = -np.inf
        with self.assertRaises(dsp.AudioReadError) as cm:
            dsp.load(self.wav("one.wav", y2))
        self.assertIn("1 broken sample ", str(cm.exception))          # singular

    def test_nan_is_refused_before_resampling_spreads_it(self):
        y = tone(); y[100] = np.nan
        with self.assertRaises(dsp.AudioReadError):
            dsp.load(self.wav("bad.wav", y), 22050)

    def test_no_samples_and_too_many_channels(self):
        with self.assertRaises(dsp.AudioReadError) as cm:
            dsp.load(self.wav("empty.wav", np.zeros((0, 1), "float32")))
        self.assertIn("no audio in it", str(cm.exception))
        six = np.stack([tone()] * 6, axis=1)
        with self.assertRaises(dsp.AudioReadError) as cm:
            dsp.load(self.wav("six.wav", six))
        self.assertIn("6 channels", str(cm.exception))
        self.assertIn("up to 5", str(cm.exception))

    def test_a_good_file_and_five_channels_still_load(self):
        y, sr = dsp.load(self.wav("ok.wav", np.stack([tone(), tone() * 0.5], axis=1)))
        self.assertEqual((y.shape[1], sr), (2, SR))
        y5, _ = dsp.load(self.wav("five.wav", np.stack([tone()] * 5, axis=1)))
        self.assertEqual(y5.shape[1], 5)
        self.assertTrue(np.isfinite(dsp.lufs(y5, SR)))

    def test_read_leaves_the_judging_to_the_caller(self):
        y = tone(); y[10] = np.nan
        raw, _ = dsp.read(self.wav("bad.wav", y))
        self.assertEqual(dsp.broken_samples(raw), (1, 10))
        self.assertEqual(dsp.broken_samples(np.zeros((4, 2))), (0, None))


class Commands(Base):
    def setUp(self):
        super().setUp()
        y = tone(); y[1000:1010] = np.nan
        self.nan = self.wav("nan.wav", y)
        yi = tone(); yi[1000] = np.inf
        self.inf = self.wav("inf.wav", yi)
        self.empty = self.wav("empty.wav", np.zeros((0, 1), "float32"))
        self.six = self.wav("six.wav", np.stack([tone()] * 6, axis=1))

    def test_cleanup_refuses_one_inf_sample_and_writes_nothing(self):
        out = self.td / "c"
        rc, _, err = self.hx("cleanup", self.inf, "--out", out)
        self.assert_one_sentence(rc, err, "broken sample", "inf.wav")
        self.assertEqual(list(out.glob("*.wav")), [])

    def test_the_single_file_commands_refuse_nan(self):
        for cmd in ("measure", "qc", "harsh", "translate", "sections"):
            extra = ("--out", self.td / f"o-{cmd}") if cmd != "qc" else ()
            rc, out, err = self.hx(cmd, self.nan, *extra)
            self.assertEqual(rc, 2, (cmd, err))
            self.assertNotIn("Traceback", err, cmd)
            self.assertIn("10 broken samples", err, cmd)
            self.assertNotIn("nan", out.lower(), cmd)         # no table of "+nan dBTP" lines

    def test_release_refuses_before_writing_anything(self):
        out = self.td / "rel"
        rc, _, err = self.hx("release", self.nan, "--title", "T", "--artist", "A", "--out", out)
        self.assert_one_sentence(rc, err, "broken samples")
        self.assertFalse(out.exists() and any(out.iterdir()))

    def test_no_samples_and_six_channels_are_refused_not_crashed(self):
        for f, word in ((self.empty, "no audio in it"), (self.six, "6 channels")):
            for cmd in ("qc", "measure"):
                args = (cmd, f) if cmd == "qc" else (cmd, f, "--out", self.td / "m")
                rc, _, err = self.hx(*args)
                self.assertEqual(rc, 2, (cmd, f.name, err))
                self.assertNotIn("Traceback", err)
                self.assertIn(word, err)
        rc, _, err = self.hx("release", self.six, "--title", "T", "--artist", "A", "--out", self.td / "r6")
        self.assert_one_sentence(rc, err, "6 channels")
        rc, out, err = self.hx("sections", self.empty, "--out", self.td / "se")
        self.assert_one_sentence(rc, err, "no audio in it")
        self.assertEqual(out.strip(), "")                       # nothing printed before the refusal

    def test_a_stem_folder_with_an_empty_or_six_channel_file_names_it_and_goes_on(self):
        folder = self.td / "stems"
        folder.mkdir()
        for n in ("bass", "keys", "vox", "drums"):
            sf.write(str(folder / f"{n}.wav"), np.stack([tone(), tone()], axis=1), SR)
        shutil.copy(self.empty, folder / "empty.wav")
        shutil.copy(self.six, folder / "six.wav")
        for cmd in (("masking", folder), ("balance", folder), ("stems", folder, "--out", self.td / "st.md")):
            rc, _, err = self.hx(*cmd)
            self.assertEqual(rc, 0, (cmd[0], err))
            self.assertNotIn("Traceback", err)
            self.assertIn("skipped empty.wav: it has no audio in it", err, cmd[0])
            self.assertIn("skipped six.wav: it has 6 channels", err, cmd[0])
        self.assertIn("| bass |", (self.td / "st.md").read_text())
        self.assertNotIn("| six |", (self.td / "st.md").read_text())          # no table row of invented numbers
        os.remove(folder / "bass.wav"); os.remove(folder / "keys.wav"); os.remove(folder / "vox.wav")
        rc, _, err = self.hx("masking", folder)                             # one usable stem left: nothing to compare
        self.assertEqual(rc, 1, err)
        self.assertIn("need at least two", err)
        self.assertIn("skipped six.wav", err)

    def test_the_tools_that_read_a_file_themselves_refuse_a_broken_one(self):
        for cmd in ("dehiss", "deess", "breaths"):
            out = self.td / f"{cmd}.wav"
            rc, o, err = self.hx(cmd, self.inf, out)
            self.assert_one_sentence(rc, err, "broken sample", "inf.wav")
            self.assertFalse(out.exists(), cmd)
        for cmd, args in (("clicks", (self.nan,)), ("punch", (self.nan, self.nan))):
            rc, _, err = self.hx(cmd, *args)
            self.assert_one_sentence(rc, err, "10 broken samples")
        rc, _, err = self.hx("dehiss", self.six, self.td / "six-out.wav")
        self.assert_one_sentence(rc, err, "6 channels")
        rc, _, err = self.hx("dehiss", self.nan, self.td / "p.wav", "--profile", self.inf)    # the noise sample too
        self.assertEqual(rc, 2, err)

    def test_dehiss_on_a_good_file_still_writes(self):
        good = self.wav("good.wav", np.stack([tone(), tone() * 0.5], axis=1))
        rc, out, err = self.hx("dehiss", good, self.td / "d.wav")
        self.assertEqual(rc, 0, err)
        y, _ = sf.read(str(self.td / "d.wav"))
        self.assertTrue(np.isfinite(y).all())

    def test_release_leaves_no_folder_behind_when_the_master_is_refused(self):
        out = self.td / "made-by-release"
        for f in (self.nan, self.empty, self.six):
            rc, _, err = self.hx("release", f, "--title", "T", "--artist", "A", "--out", out)
            self.assertEqual(rc, 2, err)
            self.assertFalse(out.exists(), f.name)                 # not even an empty --out

    def test_cleanup_works_at_a_low_sample_rate(self):
        rng = np.random.default_rng(4)
        y = (tone(8000, 4.0) + rng.standard_normal(32000).astype("float32") * 0.01)
        p = self.wav("low.wav", np.stack([y, y], axis=1), 8000)
        out = self.td / "low-out"
        rc, _, err = self.hx("cleanup", p, "--out", out)
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(list(out.glob("*.wav"))), 1)


@unittest.skipIf(sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0), "needs a folder this user cannot write")
class UnwritableOut(Base):
    def setUp(self):
        super().setUp()
        self.ro = self.td / "ro"
        self.ro.mkdir()
        os.chmod(self.ro, 0o555)
        self.song = self.wav("song.wav", np.stack([tone(), tone() * 0.8], axis=1))
        self.stems = self.td / "stems"
        self.stems.mkdir()
        for n in ("bass", "keys", "vox", "drums"):
            sf.write(str(self.stems / f"{n}.wav"), np.stack([tone(), tone()], axis=1), SR)

    def check(self, rc, out, err, target):
        self.assertEqual(rc, 2, err)
        self.assertNotIn("Traceback", err)
        self.assertIn("can't write to", err)
        self.assertIn(str(target), err)
        self.assertIn("--out", err)                             # what to do next

    def test_each_command_ends_in_one_sentence_before_any_work(self):
        for cmd in ("measure", "harsh", "translate", "sections", "compare", "preflight", "masking", "balance", "release", "scan"):
            target = self.ro / cmd
            args = {"compare": (self.song, self.song), "preflight": (self.stems,), "masking": (self.stems,),
                    "balance": (self.stems, "--render"), "scan": (self.stems,),
                    "release": (self.song, "--title", "T", "--artist", "A")}.get(cmd, (self.song,))
            rc, out, err = self.hx(cmd, *args, "--out", target)
            self.check(rc, out, err, target)
            if cmd == "sections":
                self.assertNotIn("Findings", out)               # the analysis was not run and printed first
            self.assertFalse(target.exists(), cmd)

    def test_dehiss_deess_breaths_name_the_output_that_cannot_be_written(self):
        target = self.ro / "d.wav"
        for cmd in ("dehiss", "deess", "breaths"):
            rc, out, err = self.hx(cmd, self.song, target)
            self.check(rc, out, err, target)
            self.assertNotIn("as audio", err, cmd)                  # not "can't read ... as audio: no such file"
            self.assertNotIn("sibilant", out, cmd)                  # refused before the analysis, not after

    def test_demo_and_album(self):
        rc, out, err = self.hx("demo", "--out", self.ro / "d")
        self.check(rc, out, err, self.ro / "d")
        other = self.wav("other.wav", np.stack([tone(), tone()], axis=1))
        rc, out, err = self.hx("album", self.song, other, "--out", self.ro / "a")
        self.check(rc, out, err, self.ro / "a")
        self.assertNotIn("measuring", err)                      # before the 19 seconds of analysis

    def test_check_out_unit(self):
        paths.check_out(None)                                   # nothing asked for, nothing to check
        paths.check_out(self.td / "new" / "deeper")             # can be made under a writable folder
        with self.assertRaises(SystemExit) as cm:
            paths.check_out(self.ro / "x" / "y")
        self.assertEqual(cm.exception.code, 2)
        blocker = self.td / "afile"
        blocker.write_text("x")
        with self.assertRaises(SystemExit):
            paths.out_at(str(blocker / "sub"))                  # a path through a file, not a folder

    def test_a_late_permission_error_is_still_one_sentence(self):
        msg = cli._audio_read_message(PermissionError(13, "Permission denied", str(self.ro / "late.md")))
        self.assertIn("can't write to", msg)
        self.assertIn("--out", msg)
        unreadable = self.td / "locked.wav"
        unreadable.write_bytes(b"x")
        os.chmod(unreadable, 0)
        try:
            msg = cli._audio_read_message(PermissionError(13, "Permission denied", str(unreadable)))
        finally:
            os.chmod(unreadable, 0o644)
        self.assertIn("can't read", msg)                        # an unreadable INPUT is not blamed on --out
        self.assertIsNone(cli._audio_read_message(KeyError("x")))


class Distortion(unittest.TestCase):
    def test_block_peaks_fit_any_sample_rate(self):
        rng = np.random.default_rng(1)
        for sr in (8000, 11025, 22050, 44100, 48000):
            y = rng.standard_normal((int(sr * 3.337), 2)) * 0.1
            nblk = int(np.ceil(len(y) / (sr * D.BLK)))
            pk = D.block_peaks(y, sr, nblk)               # used to fail with "negative dimensions" at 22,050 Hz
            self.assertEqual(len(pk), nblk)
            m = np.abs(y).max(axis=1)
            for i in (0, 1, nblk // 2, nblk - 1):
                a = int(np.floor(i * sr * D.BLK + 1e-6))
                b = len(m) if i == nblk - 1 else int(np.floor((i + 1) * sr * D.BLK + 1e-6))
                self.assertEqual(pk[i], m[a:b].max(), (sr, i))


if __name__ == "__main__":
    unittest.main()
