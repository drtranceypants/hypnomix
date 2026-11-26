"""`hypnomix release`: the delivery folder. Synthetic audio and a synthetic cover only (ffmpeg makes the picture)."""
import contextlib, hashlib, io, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from hypnomix.core import dsp
from hypnomix.engineer import release

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
SR = 44100


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def master_audio(seconds=8.0, peak_db=-1.5, seed=0, sr=SR):
    """A little song-shaped signal: chords plus a bit of noise, a fade in and a fade out, scaled to a true peak."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sr)) / sr
    x = sum(0.2 * np.sin(2 * np.pi * f * t) for f in (220, 277.2, 330, 440, 880)) + 0.03 * rng.standard_normal(len(t))
    x *= np.clip(np.minimum(t / 0.3, (t[-1] - t) / 1.0), 0, 1)
    y = np.stack([x, 0.9 * np.roll(x, 2)], axis=1)
    return y * dsp.undb(peak_db - dsp.true_peak(y, sr))


def cover(path, size=3000, h=None, fmt="jpg"):
    h = h or size
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=0x884422:s={size}x{h}",
                    "-frames:v", "1", str(path)], check=True)
    return path


def run(argv):
    """Run `hypnomix release` in-process: (exit code, everything printed)."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with mock.patch.object(sys, "argv", ["hypnomix release"] + [str(a) for a in argv]), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            release.main()
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            if isinstance(e.code, str):
                err.write(e.code)
    return code, out.getvalue() + err.getvalue()


def probe(path, entries="stream=codec_name,sample_rate,bits_per_raw_sample,bits_per_sample,channels:format_tags"):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def tags(path):
    t = probe(path, "format_tags")["format"].get("tags", {})
    return {k.lower(): v for k, v in t.items()}


@unittest.skipUnless(HAVE_FFMPEG, "needs ffmpeg and ffprobe")
class Package(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.root = Path(cls.td.name)
        cls.master = cls.root / "my master.wav"
        sf.write(str(cls.master), master_audio(), SR, subtype="PCM_24")
        cls.art = cover(cls.root / "cover.jpg")
        cls.before = sha(cls.master)
        cls.art_before = sha(cls.art)
        cls.out = cls.root / "out"
        cls.args = ["--title", "Hello / World", "--artist", "The Band", "--album", "First Album", "--track", "3",
                    "--year", "2026", "--genre", "Rock", "--isrc", "us-rc1-76-07839", "--art", cls.art]
        cls.code, cls.text = run([cls.master, *cls.args, "--formats", "wav24,wav16,mp3,aac,flac", "--out", cls.out])
        cls.folder = cls.out / "The Band - Hello - World"

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_wrote_the_folder_and_exit_zero(self):
        self.assertEqual(self.code, 0, self.text)
        names = sorted(p.name for p in self.folder.iterdir())
        self.assertEqual(names, sorted(["The Band - Hello - World (24-bit).wav", "The Band - Hello - World (16-bit).wav",
                                        "The Band - Hello - World.mp3", "The Band - Hello - World.m4a",
                                        "The Band - Hello - World.flac", "cover.jpg", "release.json", "RELEASE.md"]))
        self.assertEqual([p.name for p in self.out.iterdir()], ["The Band - Hello - World"])   # no partial left behind

    def test_master_and_cover_are_untouched_and_the_24_bit_is_the_master(self):
        self.assertEqual(sha(self.master), self.before)
        self.assertEqual(sha(self.art), self.art_before)
        self.assertEqual(sha(self.folder / "The Band - Hello - World (24-bit).wav"), self.before)   # never re-processed
        self.assertEqual(sha(self.folder / "cover.jpg"), self.art_before)

    def test_sample_rates_and_bit_depths(self):
        w24 = probe(self.folder / "The Band - Hello - World (24-bit).wav")["streams"][0]
        w16 = probe(self.folder / "The Band - Hello - World (16-bit).wav")["streams"][0]
        fl = probe(self.folder / "The Band - Hello - World.flac")["streams"][0]
        self.assertEqual((w24["codec_name"], int(w24["sample_rate"])), ("pcm_s24le", 44100))
        self.assertEqual((w16["codec_name"], int(w16["sample_rate"])), ("pcm_s16le", 44100))
        self.assertEqual((fl["codec_name"], fl["bits_per_raw_sample"]), ("flac", "24"))
        mp3 = next(s for s in probe(self.folder / "The Band - Hello - World.mp3")["streams"] if s["codec_name"] == "mp3")
        self.assertEqual(int(mp3["sample_rate"]), 44100)
        br = probe(self.folder / "The Band - Hello - World.mp3", "format=bit_rate")["format"]["bit_rate"]
        self.assertGreater(int(br), 300000)

    def test_16_bit_is_dithered_and_close_to_the_master(self):
        a, _ = dsp.load(self.folder / "The Band - Hello - World (24-bit).wav")
        b, _ = dsp.load(self.folder / "The Band - Hello - World (16-bit).wav")
        self.assertEqual(a.shape, b.shape)
        self.assertLess(np.abs(a - b).max(), 3.0 / 32768)                 # a few 16-bit steps at most
        self.assertGreater(np.abs(a - b).max(), 0.5 / 32768)              # and not the same numbers: it was rounded
        steps = np.unique(np.round(b[:2000] * 32768, 6) % 1.0)
        self.assertTrue(np.all(steps == 0))                               # on the 16-bit grid

    def test_tags_and_cover_are_in_the_lossy_files_and_flac(self):
        for ext, isrc_key in (("mp3", "tsrc"), ("flac", "isrc"), ("m4a", None)):
            p = self.folder / f"The Band - Hello - World.{ext}"
            t = tags(p)
            self.assertEqual(t["title"], "Hello / World", ext)            # the tag keeps the real title; only the file name is made safe
            self.assertEqual(t["artist"], "The Band")
            self.assertEqual(t["album"], "First Album")
            self.assertEqual(t["genre"], "Rock")
            self.assertEqual(t["date"], "2026")
            self.assertEqual(t["track"], "3")
            if isrc_key:
                self.assertEqual(t[isrc_key], "USRC17607839")
            streams = probe(p, "stream=codec_name:stream_disposition=attached_pic")["streams"]
            pics = [s for s in streams if s["codec_name"] in ("mjpeg", "png")]
            self.assertEqual(len(pics), 1, ext)
            self.assertEqual(pics[0]["disposition"]["attached_pic"], 1)

    def test_release_json_and_report(self):
        j = json.loads((self.folder / "release.json").read_text(encoding="utf-8"))
        self.assertEqual((j["title"], j["artist"], j["isrc"], j["year"]), ("Hello / World", "The Band", "USRC17607839", "2026"))
        self.assertEqual(j["master"]["sha256"], self.before)
        self.assertEqual([f["format"] for f in j["files"]], ["wav24", "wav16", "mp3", "aac", "flac"])
        md = (self.folder / "RELEASE.md").read_text(encoding="utf-8")
        for needle in ("LUFS", "dBTP", "after decoding", "The Band - Hello - World.mp3", "release checks"):
            self.assertIn(needle, md)
        lossy = [f for f in j["files"] if f["lossy"]]
        self.assertEqual(len(lossy), 2)
        for f in lossy:
            self.assertIn("true_peak_decoded", f)
            self.assertLess(f["true_peak_decoded"], 0.0)
            self.assertIsNone(f["advice"])
        self.assertIn("fine, with headroom", md)

    def test_second_run_refuses_to_overwrite(self):
        code, text = run([self.master, *self.args, "--out", self.out])
        self.assertEqual(code, 1)
        self.assertIn("already exists", text)
        self.assertEqual(sha(self.folder / "The Band - Hello - World (24-bit).wav"), self.before)

    def test_meta_json_from_a_previous_release_and_command_line_wins(self):
        out2 = self.root / "out2"
        code, text = run([self.master, "--meta", self.folder / "release.json", "--title", "Other", "--formats", "wav24,mp3",
                          "--out", out2])
        self.assertEqual(code, 0, text)
        f = out2 / "The Band - Other"
        self.assertTrue((f / "The Band - Other.mp3").exists())
        t = tags(f / "The Band - Other.mp3")
        self.assertEqual((t["title"], t["album"], t["tsrc"]), ("Other", "First Album", "USRC17607839"))
        self.assertEqual(len(probe(f / "The Band - Other.mp3", "stream=codec_name")["streams"]), 2)   # the cover came from the json too


@unittest.skipUnless(HAVE_FFMPEG, "needs ffmpeg and ffprobe")
class CheckForm(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.master = self.root / "m.wav"
        sf.write(str(self.master), master_audio(6), SR, subtype="PCM_24")
        self.art = cover(self.root / "c.png")
        self.out = self.root / "out"

    def tearDown(self):
        self.td.cleanup()

    def tree(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))

    def test_check_writes_nothing_and_lists_what_would_be_written(self):
        before, h = self.tree(), sha(self.master)
        code, text = run([self.master, "--title", "T", "--artist", "A", "--isrc", "USRC17607839", "--art", self.art,
                          "--check", "--out", self.out, "--formats", "wav24,wav16,mp3,aac,flac"])
        self.assertEqual(code, 0, text)
        self.assertEqual(self.tree(), before)                      # not even the output folder
        self.assertEqual(sha(self.master), h)
        for needle in ("A - T (24-bit).wav", "A - T (16-bit).wav", "A - T.mp3", "A - T.m4a", "A - T.flac", "release.json",
                       "RELEASE.md", "PNG", "3000 x 3000", "US-RC1-76-07839",
                       "True peak", "Ready to write"):
            self.assertIn(needle, text)

    def test_check_flags_a_bad_isrc_and_a_small_cover(self):
        small = cover(self.root / "small.jpg", 1400)
        code, text = run([self.master, "--title", "T", "--artist", "A", "--isrc", "US-RC1-76-0783", "--art", small, "--check"])
        self.assertEqual(code, 1)
        self.assertIn("is not an ISRC", text)
        self.assertIn("at least 3000 px", text)
        self.assertIn("Not ready", text)

    def test_check_flags_a_cover_that_is_not_square(self):
        wide = cover(self.root / "wide.jpg", 3200, 3000)
        code, text = run([self.master, "--title", "T", "--artist", "A", "--art", wide, "--check"])
        self.assertEqual(code, 1)
        self.assertIn("must be square", text)

    def test_check_fails_on_a_failing_master(self):
        y = master_audio(6, peak_db=0.5)                          # over full scale: clipped runs and a true peak over 0
        y = np.clip(y, -1, 1)
        bad = self.root / "clipped.wav"
        sf.write(str(bad), y, SR, subtype="PCM_24")
        code, text = run([bad, "--title", "T", "--artist", "A", "--check"])
        self.assertEqual(code, 1)
        self.assertIn("✗", text)

    def test_check_says_when_the_folder_exists(self):
        (self.out / "A - T").mkdir(parents=True)
        code, text = run([self.master, "--title", "T", "--artist", "A", "--check", "--out", self.out])
        self.assertEqual(code, 1)
        self.assertIn("ALREADY EXISTS", text)


@unittest.skipUnless(HAVE_FFMPEG, "needs ffmpeg and ffprobe")
class CoverWarningsAreWritten(unittest.TestCase):
    """What --check says about the cover, the written package says too."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.master = self.root / "m.wav"
        sf.write(str(self.master), master_audio(4), SR, subtype="PCM_24")

    def tearDown(self):
        self.td.cleanup()

    def test_a_small_cover_is_written_with_a_warning_everywhere(self):
        small = cover(self.root / "small.jpg", 1000)
        code, text = run([self.master, "--title", "T", "--artist", "A", "--art", small, "--out", self.root / "o", "--formats", "wav24"])
        self.assertEqual(code, 0, text)
        self.assertIn("! cover", text)
        self.assertIn("at least 3000 px", text)
        folder = self.root / "o" / "A - T"
        md = (folder / "RELEASE.md").read_text(encoding="utf-8")
        self.assertIn("Check the cover before you upload", md)
        self.assertIn("at least 3000 px", md)
        j = json.loads((folder / "release.json").read_text(encoding="utf-8"))
        self.assertTrue(any("Cover size" in w for w in j["cover_warnings"]))
        self.assertEqual(sha(folder / "cover.jpg"), sha(small))                # still copied as it is

    def test_a_cover_that_is_not_square_is_written_with_a_warning(self):
        wide = cover(self.root / "wide.jpg", 3200, 3000)
        code, text = run([self.master, "--title", "T", "--artist", "A", "--art", wide, "--out", self.root / "o", "--formats", "wav24"])
        self.assertEqual(code, 0, text)
        self.assertIn("must be square", text)
        self.assertIn("must be square", (self.root / "o" / "A - T" / "RELEASE.md").read_text(encoding="utf-8"))

    def test_a_good_cover_has_no_warning(self):
        good = cover(self.root / "good.jpg", 3000)
        code, text = run([self.master, "--title", "T", "--artist", "A", "--art", good, "--out", self.root / "o", "--formats", "wav24"])
        self.assertEqual(code, 0, text)
        self.assertNotIn("! cover", text)
        folder = self.root / "o" / "A - T"
        self.assertEqual(json.loads((folder / "release.json").read_text(encoding="utf-8"))["cover_warnings"], [])
        self.assertNotIn("Check the cover", (folder / "RELEASE.md").read_text(encoding="utf-8"))

    def test_a_cover_whose_name_starts_with_a_dash_works(self):
        cover(self.root / "-cov.jpg", 3000)
        here = os.getcwd()
        os.chdir(self.root)
        try:
            self.assertIsNotNone(release.probe_image(Path("./-cov.jpg")))
            code, text = run(["m.wav", "--title", "T", "--artist", "A", "--art", "./-cov.jpg", "--check"])
            self.assertEqual(code, 0, text)
            self.assertIn("3000 x 3000", text)
            code, text = run(["m.wav", "--title", "T", "--artist", "A", "--art", "./-cov.jpg", "--out", "o", "--formats", "mp3"])
            self.assertEqual(code, 0, text)
            self.assertIn("attached_pic", json.dumps(probe(self.root / "o" / "A - T" / "A - T.mp3", "stream_disposition")))
        finally:
            os.chdir(here)


@unittest.skipUnless(HAVE_FFMPEG, "needs ffmpeg and ffprobe")
class Refusals(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.master = self.root / "m.wav"
        sf.write(str(self.master), master_audio(5), SR, subtype="PCM_24")
        self.out = self.root / "out"

    def tearDown(self):
        self.td.cleanup()

    def test_needs_title_and_artist(self):
        code, text = run([self.master, "--title", "T", "--out", self.out])
        self.assertEqual(code, 1)
        self.assertIn("--artist", text)
        self.assertFalse(self.out.exists())

    def test_bad_isrc_stops_before_anything_is_written(self):
        code, text = run([self.master, "--title", "T", "--artist", "A", "--isrc", "nope", "--out", self.out])
        self.assertEqual(code, 1)
        self.assertIn("not an ISRC", text)
        self.assertFalse(self.out.exists())

    def test_unknown_format(self):
        code, text = run([self.master, "--title", "T", "--artist", "A", "--formats", "wav24,ogg", "--out", self.out])
        self.assertEqual(code, 1)
        self.assertIn("unknown format", text)

    def test_a_lossy_master_is_refused(self):
        mp3 = self.root / "m.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(self.master), str(mp3)], check=True)
        code, text = run([mp3, "--title", "T", "--artist", "A", "--out", self.out])
        self.assertEqual(code, 1)
        self.assertIn("lossy", text)

    def test_a_cover_that_cannot_be_embedded_is_refused_and_leaves_nothing(self):
        gif = self.root / "c.gif"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1",
                        str(gif)], check=True)
        code, text = run([self.master, "--title", "T", "--artist", "A", "--art", gif, "--out", self.out])
        self.assertEqual(code, 1)
        self.assertIn("JPEG or PNG", text)
        self.assertFalse(self.out.exists())

    def test_missing_master(self):
        code, text = run([self.root / "nope.wav", "--title", "T", "--artist", "A", "--out", self.out])
        self.assertEqual(code, 1)
        self.assertIn("not found", text)


@unittest.skipUnless(HAVE_FFMPEG, "needs ffmpeg and ffprobe")
class OtherMasters(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def test_96k_master_gives_44k_16_bit_and_44k_lossy(self):
        m = self.root / "m96.wav"
        sf.write(str(m), master_audio(5, sr=96000), 96000, subtype="PCM_24")
        code, text = run([m, "--title", "T", "--artist", "A", "--out", self.root / "o"])
        self.assertEqual(code, 0, text)
        f = self.root / "o" / "A - T"
        self.assertEqual(int(probe(f / "A - T (24-bit).wav")["streams"][0]["sample_rate"]), 96000)
        self.assertEqual(sha(f / "A - T (24-bit).wav"), sha(m))
        self.assertEqual(int(probe(f / "A - T (16-bit).wav")["streams"][0]["sample_rate"]), 44100)
        self.assertEqual(int(probe(f / "A - T.mp3")["streams"][0]["sample_rate"]), 44100)
        self.assertIn("resampled from 96000 Hz", (f / "RELEASE.md").read_text(encoding="utf-8"))

    def test_16_bit_master_is_widened_exactly_and_the_16_bit_file_is_a_copy(self):
        m = self.root / "m16.wav"
        sf.write(str(m), master_audio(5), SR, subtype="PCM_16")
        code, text = run([m, "--title", "T", "--artist", "A", "--formats", "wav24,wav16", "--out", self.root / "o"])
        self.assertEqual(code, 0, text)
        f = self.root / "o" / "A - T"
        a, _ = dsp.load(m)
        b, _ = dsp.load(f / "A - T (24-bit).wav")
        self.assertEqual(probe(f / "A - T (24-bit).wav")["streams"][0]["codec_name"], "pcm_s24le")
        self.assertTrue(np.array_equal(a, b))
        self.assertEqual(sha(f / "A - T (16-bit).wav"), sha(m))

    def test_a_hot_master_is_reported_not_fixed(self):
        rng = np.random.default_rng(1)
        t = np.arange(SR * 6) / SR
        x = 0.5 * np.sign(np.sin(2 * np.pi * 220 * t)) + 0.4 * np.sign(np.sin(2 * np.pi * 331 * t)) + 0.1 * rng.standard_normal(len(t))
        x = x / np.abs(x).max() * 0.999
        m = self.root / "hot.wav"
        sf.write(str(m), np.stack([x, 0.9 * x], 1), SR, subtype="PCM_24")
        code, text = run([m, "--title", "T", "--artist", "A", "--formats", "wav24,mp3", "--out", self.root / "o"])
        self.assertEqual(code, 0, text)
        f = self.root / "o" / "A - T"
        j = json.loads((f / "release.json").read_text())
        mp3 = next(r for r in j["files"] if r["format"] == "mp3")
        self.assertGreater(mp3["true_peak_decoded"], 0.0)
        self.assertIn("overshoots 0 dBTP by", mp3["advice"])
        self.assertIn("lower", mp3["advice"])
        self.assertEqual(mp3["qc"]["status"], "FAIL")
        md = (f / "RELEASE.md").read_text(encoding="utf-8")
        self.assertIn("Nothing was done to the audio to hide this", md)
        self.assertEqual(sha(f / "A - T (24-bit).wav"), sha(m))           # the audio was not changed to hide it
        self.assertIn("overshoots", text)


class Helpers(unittest.TestCase):
    def test_isrc(self):
        self.assertEqual(release.normalise_isrc("us-rc1-76-07839"), "USRC17607839")
        self.assertEqual(release.normalise_isrc(" GBAYE 6800011 "), "GBAYE6800011")
        for bad in ("USRC1760783", "US-RC1-76-078390", "1SRC17607839", "", None, "USRC1760783A"):
            self.assertIsNone(release.normalise_isrc(bad), bad)

    def test_advice_names_the_overshoot_and_how_much_lower(self):
        a = release.lossy_advice(0.72, -0.1)
        self.assertIn("0.72 dB", a)
        self.assertIn("0.9 dB lower", a)
        self.assertIn("was not changed", a)
        self.assertIsNone(release.lossy_advice(-1.0, -1.0))
        self.assertIn("no headroom", release.lossy_advice(-0.05, -0.2))

    def test_safe_name(self):
        self.assertEqual(release.safe_name('AC/DC: "Back" in Black?'), "AC-DC- -Back- in Black-")
        self.assertEqual(release.safe_name("  ..  "), "untitled")
        self.assertEqual(release.safe_name("Café – Ünï"), "Café – Ünï")

    def test_formats(self):
        self.assertEqual(release.parse_formats("wav24, mp3,mp3"), ["wav24", "mp3"])
        with self.assertRaises(release.ReleaseError):
            release.parse_formats("wav24,wma")


if __name__ == "__main__":
    unittest.main()
