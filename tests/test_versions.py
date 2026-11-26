"""`hypnomix versions`: instrumental, a cappella, TV mix and radio edit from exported stems. Synthetic stems only."""
import contextlib, hashlib, io, json, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from hypnomix.core import dsp
from hypnomix.engineer import versions as V

SR = 44100
SECONDS = 16.0                      # 8 bars at 120 bpm: a bar is 2.0 s


def stems(seed=0, seconds=SECONDS):
    """Five stems of one little song, all from 0:00: drums (a click on every beat, a louder one on every bar),
    bass, pad, a lead vocal and a harmony. The vocals come and go so the a cappella is not just the song."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    beat = 0.5
    drums = np.zeros(n)
    for b in range(int(seconds / beat)):
        i = int(b * beat * SR)
        k = int(0.04 * SR)
        drums[i:i + k] += (0.5 if b % 4 == 0 else 0.25) * np.exp(-np.arange(k) / (0.006 * SR)) * rng.standard_normal(k)
    bass = 0.2 * np.sin(2 * np.pi * 55 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.5 * t) ** 2)
    pad = sum(0.04 * np.sin(2 * np.pi * f * t + p) for f, p in ((220, 0), (277, 1), (330, 2)))
    gate = (np.sin(2 * np.pi * 0.25 * t) > -0.4).astype(float)
    lead = 0.15 * np.sin(2 * np.pi * 440 * t) * gate + 0.05 * np.sin(2 * np.pi * 880 * t) * gate
    harm = 0.08 * np.sin(2 * np.pi * 554 * t) * gate
    mk = lambda x, w: np.stack([x * (1 - w), x * (1 + w)], axis=1)
    st = {"Drums": mk(drums, 0.0), "Bass": mk(bass, 0.0), "Pad": mk(pad, 0.3), "Lead Vox": mk(lead, 0.0), "Harm 1": mk(harm, -0.4)}
    tot = sum(st.values())
    g = dsp.undb(-4.0 - dsp.true_peak(tot, SR))                 # the sum peaks at -4 dBTP, so no stem or sum clips
    return {k: v * g for k, v in st.items()}


def write_stems(folder, st):
    folder.mkdir(parents=True, exist_ok=True)
    for k, y in st.items():
        sf.write(str(folder / f"{k}.wav"), y, SR, subtype="PCM_24")
    return folder


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def tree_hashes(folder):
    return {str(p.relative_to(folder)): sha(p) for p in sorted(Path(folder).rglob("*")) if p.is_file()}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with mock.patch.object(sys, "argv", ["hypnomix versions"] + [str(a) for a in argv]), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            V.main()
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            if isinstance(e.code, str):
                err.write(e.code)
    return code, out.getvalue() + err.getvalue()


def load(p):
    y, sr = sf.read(str(p), always_2d=True)
    return y, sr


class Versions(unittest.TestCase):
    """The stems add up to the mix exactly (the mix is the sum, scaled to a normal master level)."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.root = Path(cls.td.name)
        cls.st = stems()
        cls.dir = write_stems(cls.root / "stems", cls.st)
        cls.st = {k: sf.read(str(cls.dir / f"{k}.wav"))[0] for k in cls.st}          # as the files hold them (24-bit)
        tot = sum(cls.st.values())
        cls.tot = tot
        cls.mix = cls.root / "My Song.wav"
        sf.write(str(cls.mix), tot, SR, subtype="PCM_24")                              # the mix is exactly the stems added up
        cls.hashes = tree_hashes(cls.root)
        cls.out = cls.root / "out"
        cls.code, cls.text = run(["--stems", cls.dir, "--vocals", "Lead*,Harm*", "--mix", cls.mix, "--tv", "-6",
                                  "--cut", "0:03.2-0:07.9", "--bpm", "120", "--out", cls.out])
        cls.folder = cls.out / "My Song (versions)"

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_ran_and_inputs_are_untouched(self):
        self.assertEqual(self.code, 0, self.text)
        after = tree_hashes(self.root)
        for k, h in self.hashes.items():
            self.assertEqual(after[k], h, k)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()),
                         sorted(["My Song (instrumental).wav", "My Song (a cappella).wav", "My Song (TV mix).wav",
                                 "My Song (radio edit).wav", "VERSIONS.md", "versions.json"]))
        self.assertEqual([p.name for p in self.out.iterdir()], ["My Song (versions)"])        # no partial left

    def test_null_test_says_the_stems_add_up(self):
        j = json.loads((self.folder / "versions.json").read_text())
        self.assertEqual(j["null"]["verdict"], "add up")
        self.assertLess(j["null"]["residual_db"], -100)          # the mix IS the sum, to 24-bit rounding
        self.assertIn("null test", self.text)

    def test_files_are_24_bit_at_the_stems_rate_and_the_same_length_as_the_stems(self):
        for kind in ("instrumental", "a cappella", "TV mix"):
            p = self.folder / f"My Song ({kind}).wav"
            i = sf.info(str(p))
            self.assertEqual((i.samplerate, i.subtype, i.channels), (SR, "PCM_24", 2), kind)
            self.assertEqual(i.frames, len(self.tot), kind)

    def test_what_is_in_each_file(self):
        voc = self.st["Lead Vox"] + self.st["Harm 1"]
        inst = self.st["Drums"] + self.st["Bass"] + self.st["Pad"]
        for kind, want in (("instrumental", inst), ("a cappella", voc), ("TV mix", inst + voc * dsp.undb(-6))):
            y, _ = load(self.folder / f"My Song ({kind}).wav")
            j = json.loads((self.folder / "versions.json").read_text())
            g = next(v for v in j["versions"] if v["kind"] == kind)["gain_db"]
            ref = want * dsp.undb(g)
            fit = float(np.sum(y * ref) / np.sum(ref * ref))          # the gain in the report is rounded to 0.01 dB
            self.assertAlmostEqual(20 * np.log10(fit), 0.0, delta=0.01, msg=kind)
            self.assertLess(np.abs(y - fit * ref).max(), 3e-7, kind)  # nothing but that gain and 24-bit rounding/dither
        i, _ = load(self.folder / "My Song (instrumental).wav")
        a, _ = load(self.folder / "My Song (a cappella).wav")
        t, _ = load(self.folder / "My Song (TV mix).wav")
        self.assertGreater(dsp.rms_db(i), -60)
        self.assertGreater(dsp.rms_db(a), -60)
        self.assertLess(abs(float(np.corrcoef(i[:, 0], a[:, 0])[0, 1])), 0.2)       # different audio, not two copies

    def test_every_version_is_gain_matched_to_the_mix_with_gain_only(self):
        j = json.loads((self.folder / "versions.json").read_text())
        mix_l = j["mix"]["lufs"]
        for v in j["versions"]:
            if v["kind"] == "radio edit":
                self.assertEqual(v["gain_db"], 0.0)
                continue
            self.assertIn("gain only", v["gain_note"])
            capped = "stops" in v["gain_note"]
            self.assertTrue(abs(v["lufs"] - mix_l) < 0.15 or capped, (v["kind"], v["lufs"], mix_l))
            self.assertLessEqual(v["true_peak"], min(j["mix"]["true_peak"], -1.0) + 0.05)
        md = (self.folder / "VERSIONS.md").read_text(encoding="utf-8")
        self.assertIn("gain only", md)

    def test_radio_edit_is_the_mix_minus_the_cuts_to_the_sample(self):
        j = json.loads((self.folder / "versions.json").read_text())
        cut = j["cuts"][0]
        self.assertTrue(cut["snapped"])
        self.assertAlmostEqual(cut["start"], 4.0, delta=0.06)           # 3.2 s snapped to the bar line at 4.0
        self.assertAlmostEqual(cut["end"], 8.0, delta=0.06)             # 7.9 s snapped to the bar line at 8.0
        m, _ = load(self.mix)
        e, _ = load(self.folder / "My Song (radio edit).wav")
        a, b = int(round(cut["start"] * SR)), int(round(cut["end"] * SR))
        self.assertEqual(len(e), len(m) - (b - a))
        h = int(0.015 * SR) + 2
        self.assertLess(np.abs(e[:a - h] - m[:a - h]).max(), 1e-9)                       # before the join: the mix, untouched
        self.assertLess(np.abs(e[a + h:] - m[b + h:]).max(), 1e-9)                       # after the join: the mix, shifted
        seam = e[a - 2 * h:a + 2 * h]
        self.assertLessEqual(np.abs(np.diff(seam, axis=0)).max(), np.abs(np.diff(m, axis=0)).max())   # no click at the join

    def test_report_has_the_checks_and_the_cut_plan(self):
        md = (self.folder / "VERSIONS.md").read_text(encoding="utf-8")
        for needle in ("Do the stems add up to the mix?", "ADD UP", "Lead Vox.wav", "bar lines found from the audio", "Drums.wav", "release checks",
                       "removed 0:04.0", "you asked for 0:03.20-0:07.90", "What each check found", "My Song (TV mix).wav"):
            self.assertIn(needle, md)
        j = json.loads((self.folder / "versions.json").read_text())
        for v in j["versions"]:
            self.assertIn(v["qc"]["status"], ("PASS", "WARN", "FAIL"))

    def test_second_run_refuses_and_changes_nothing(self):
        before = tree_hashes(self.out)
        code, text = run(["--stems", self.dir, "--vocals", "Lead*", "--mix", self.mix, "--out", self.out])
        self.assertEqual(code, 1)
        self.assertIn("already exists", text)
        self.assertEqual(tree_hashes(self.out), before)


class WhenTheyDoNotAddUp(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.st = stems()
        self.dir = write_stems(self.root / "stems", self.st)
        self.tot = sum(sf.read(str(self.dir / f"{k}.wav"))[0] for k in self.st)

    def tearDown(self):
        self.td.cleanup()

    def verdict(self, mix_audio, name="m.wav"):
        p = self.root / name
        sf.write(str(p), mix_audio, SR, subtype="PCM_24")
        code, text = run(["--stems", self.dir, "--vocals", "Lead*,Harm*", "--mix", p, "--check"])
        self.assertEqual(code, 0, text)
        return text

    def test_master_bus_processing(self):
        squashed = np.tanh(self.tot * 4.0) / 4.0 * 3.0                  # a soft clipper after the stems
        text = self.verdict(squashed)
        self.assertRegex(text, r"leftover [\d.]+ dB below the mix: (NOT QUITE|NO|NEARLY)")
        self.assertIn("built from the stems, not carved out of the mix", text)
        self.assertIn("master-bus", text.lower().replace("master bus", "master-bus"))

    def test_a_missing_stem(self):
        text = self.verdict(self.tot - sf.read(str(self.dir / "Pad.wav"))[0])
        self.assertRegex(text, r"below the mix: (NO|NOT QUITE)\n")
        self.assertIn("built from the stems, not carved out of the mix", text)
        self.assertIn("a stem is missing", text)

    def test_level_only(self):
        text = self.verdict(self.tot * 0.4)
        self.assertIn("LEVEL", text)
        self.assertIn("apart from level", text)
        self.assertIn("louder than the mix", text)

    def test_a_different_start_point(self):
        shifted = np.concatenate([np.zeros((int(0.1 * SR), 2)), self.tot])
        text = self.verdict(shifted)
        self.assertIn("The mix runs 0.100 s later than the stems", text)


class Radio(unittest.TestCase):
    def test_apply_cuts_length_and_equal_power(self):
        n = 6 * SR
        y = np.stack([0.5 * np.sin(2 * np.pi * 300 * np.arange(n) / SR)] * 2, axis=1)
        rows = V.plan_cuts([(1.0, 2.5), (4.0, 4.7)], 6.0)
        e = V.apply_cuts(y, SR, rows, 0.03)
        self.assertEqual(len(e), n - int(round(1.5 * SR)) - int(round(0.7 * SR)))
        self.assertLess(np.abs(np.diff(e, axis=0)).max(), 0.5 * 2 * np.pi * 300 / SR * 4)    # no step bigger than the tone allows... times 4
        self.assertLess(np.abs(e).max(), 0.5 * 1.42)               # an equal-power fade of one tone never more than +3 dB
        self.assertLess(np.abs(e[:int(0.9 * SR)] - y[:int(0.9 * SR)]).max(), 1e-12)

    def test_cut_at_the_start_and_end_gets_a_fade_not_a_join(self):
        y = np.ones((4 * SR, 2)) * 0.5
        e = V.apply_cuts(y, SR, V.plan_cuts([(None, 1.0), (3.0, None)], 4.0), 0.03)
        self.assertEqual(len(e), 2 * SR)
        self.assertLess(abs(e[0, 0]), 0.01)
        self.assertLess(abs(e[-1, 0]), 0.01)
        self.assertAlmostEqual(float(e[SR, 0]), 0.5, places=6)

    def test_parse_times_and_cuts(self):
        self.assertEqual(V.parse_time("1:12"), 72.0)
        self.assertEqual(V.parse_time("1:02:03.5"), 3723.5)
        self.assertEqual(V.parse_time("72"), 72.0)
        self.assertEqual(V.parse_cuts(["1:12-1:40", "2:50-"]), [(72.0, 100.0), (170.0, None)])
        self.assertEqual(V.parse_cuts(["0:10-0:20 0:30-0:40"]), [(10.0, 20.0), (30.0, 40.0)])
        for bad in ("1:12", "a-b", "1:99x-2:00", "-"):
            with self.assertRaises(V.VersionsError, msg=bad):
                V.parse_cuts([bad])

    def test_plan_checks(self):
        with self.assertRaises(V.VersionsError):
            V.plan_cuts([(10.0, 5.0)], 60.0)                         # backwards
        with self.assertRaises(V.VersionsError):
            V.plan_cuts([(10.0, 30.0), (20.0, 40.0)], 60.0)          # overlap
        with self.assertRaises(V.VersionsError):
            V.plan_cuts([(70.0, 80.0)], 60.0)                        # past the end
        with self.assertRaises(V.VersionsError):
            V.plan_cuts([(10.0, 20.0), (20.01, 30.0)], 60.0)         # a 10 ms scrap between two cuts: shorter than the crossfade
        bars = np.arange(0, 60, 2.0)
        r = V.plan_cuts([(3.2, 7.9)], 60.0, 120, bars)
        self.assertEqual((r[0]["start"], r[0]["end"], r[0]["snapped"]), (4.0, 8.0, True))
        with self.assertRaises(V.VersionsError):
            V.plan_cuts([(4.1, 4.9)], 60.0, 120, bars)               # both edges snap to the same bar

    def test_no_mix_radio_edit_is_cut_from_the_stems(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            st = stems()
            d = write_stems(root / "stems", st)
            code, text = run(["--stems", d, "--vocals", "Lead*,Harm*", "--cut", "0:04-0:08", "--out", root / "o", "--name", "Song"])
            self.assertEqual(code, 0, text)
            f = root / "o" / "Song (versions)"
            names = sorted(p.name for p in f.iterdir())
            self.assertEqual(names, ["Song (a cappella).wav", "Song (instrumental).wav", "Song (radio edit).wav", "VERSIONS.md", "versions.json"])
            self.assertIn("cut from all the stems added up", (f / "VERSIONS.md").read_text(encoding="utf-8"))
            e = sf.info(str(f / "Song (radio edit).wav"))
            self.assertAlmostEqual(e.frames / SR, SECONDS - 4.0, delta=1 / SR)
            j = json.loads((f / "versions.json").read_text())
            self.assertIsNone(j["null"])
            self.assertTrue(all("no gain change" in v["gain_note"] or "turned down" in v["gain_note"] for v in j["versions"]))


class CheckAndRefusals(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.st = stems(seconds=8)
        self.dir = write_stems(self.root / "stems", self.st)

    def tearDown(self):
        self.td.cleanup()

    def test_check_writes_nothing_and_prints_the_plan(self):
        before = tree_hashes(self.root)
        code, text = run(["--stems", self.dir, "--vocals", "Lead*,Harm*", "--tv", "-6", "--cut", "0:02-0:04", "--check",
                          "--out", self.root / "o"])
        self.assertEqual(code, 0, text)
        self.assertEqual(tree_hashes(self.root), before)
        self.assertFalse((self.root / "o").exists())
        for needle in ("read-only", "would write", "(instrumental).wav", "(a cappella).wav", "(TV mix).wav", "(radio edit).wav",
                       "vocals at -6 dB", "remove 0:02.00 to 0:04.00", "Harm 1.wav, Lead Vox.wav", "Bass.wav, Drums.wav, Pad.wav"):
            self.assertIn(needle, text)

    def test_vocals_are_needed_and_must_match(self):
        code, text = run(["--stems", self.dir, "--vocals", "Nothing*", "--check"])
        self.assertEqual(code, 1)
        self.assertIn("no stem matches", text)
        self.assertIn("Lead Vox.wav", text)
        code, text = run(["--stems", self.dir, "--vocals", "*", "--check"])
        self.assertEqual(code, 1)
        self.assertIn("every stem matches", text)
        code, text = run(["--stems", self.dir, "--vocals", "lead*,Nope*", "--check"])
        self.assertEqual(code, 0)
        self.assertIn("'nope*' matched no stem", text)

    def test_patterns_are_not_case_sensitive_and_match_with_or_without_extension(self):
        code, text = run(["--stems", self.dir, "--vocals", "LEAD VOX, harm 1.wav", "--check"])
        self.assertEqual(code, 0, text)
        self.assertIn("vocal stems (2): Harm 1.wav, Lead Vox.wav", text)

    def test_mismatched_sample_rates_and_too_few_stems(self):
        from scipy.signal import resample_poly
        sf.write(str(self.dir / "Odd.wav"), resample_poly(self.st["Bass"], 160, 147, axis=0), 48000, subtype="PCM_24")
        code, text = run(["--stems", self.dir, "--vocals", "Lead*", "--check"])
        self.assertEqual(code, 1)
        self.assertIn("same sample rate", text)
        lone = write_stems(self.root / "lone", {"Only": self.st["Bass"]})
        code, text = run(["--stems", lone, "--vocals", "Only", "--check"])
        self.assertEqual(code, 1)
        self.assertIn("at least two stems", text)
        code, text = run(["--stems", self.root / "missing", "--vocals", "x", "--check"])
        self.assertEqual(code, 1)
        self.assertIn("no such folder", text)                      # a path that is not there is not "not a folder of stems"
        code, text = run(["--stems", self.dir / "Bass.wav", "--vocals", "x", "--check"])
        self.assertIn("is a file, not a folder of stems", text)

    def test_bad_cut_and_bad_mix_stop_before_writing(self):
        code, text = run(["--stems", self.dir, "--vocals", "Lead*", "--cut", "0:06-0:20", "--out", self.root / "o"])
        self.assertEqual(code, 1)
        self.assertIn("only 0:08", text.replace("0:08.00", "0:08"))
        code, text = run(["--stems", self.dir, "--vocals", "Lead*", "--mix", self.root / "nope.wav", "--out", self.root / "o"])
        self.assertEqual(code, 1)
        self.assertIn("not found", text)
        self.assertFalse((self.root / "o").exists())

    def test_the_mix_in_the_stems_folder_is_not_taken_for_a_stem(self):
        tot = sum(self.st.values())
        sf.write(str(self.dir / "Mix.wav"), tot * 0.5, SR, subtype="PCM_24")
        code, text = run(["--stems", self.dir, "--vocals", "Lead*,Harm*", "--mix", self.dir / "Mix.wav", "--check"])
        self.assertEqual(code, 0, text)
        self.assertIn("other stems (3)", text)

    def test_a_file_that_is_not_audio_gets_a_clean_message(self):
        junk = self.root / "junk.wav"
        junk.write_text("not audio")
        code, text = run(["--stems", self.dir, "--vocals", "Lead*,Harm*", "--mix", junk, "--check"])
        self.assertEqual(code, 1)
        self.assertIn("can't read junk.wav as audio: not an audio file hypnomix can", text)
        self.assertEqual(text.count("as audio"), 1)
        self.assertNotIn(str(self.root), text)
        self.assertNotIn("Traceback", text)

    def test_help_is_the_docstring(self):
        r = subprocess.run([sys.executable, "-m", "hypnomix.cli", "versions", "-h"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("NULL TEST", r.stdout)
        self.assertIn("--vocals", r.stdout)


class BarSnapOnsets(unittest.TestCase):
    """The bar grid is found from the audio to about 30 ms, so a snapped edge is moved onto the nearest hit."""

    @staticmethod
    def hits(first=0.37, every=0.5, seconds=30.0, seed=3):
        rng = np.random.default_rng(seed)
        n = int(seconds * SR)
        x = np.zeros(n)
        k = int(0.06 * SR)
        for j in range(int((seconds - first) / every)):
            i = int((first + j * every) * SR)
            x[i:i + k] += (0.6 if j % 4 == 0 else 0.3) * np.exp(-np.arange(k) / (0.01 * SR)) * rng.standard_normal(k)
        return np.stack([x, x], axis=1)

    def test_an_edge_30_ms_off_lands_on_the_hit(self):
        y = self.hits()
        for off in (-0.03, 0.03, 0.045):
            t = V.refine_to_onset(y, SR, 10.37 + off)
            self.assertAlmostEqual(t, 10.37, delta=0.004, msg=off)

    def test_nothing_to_land_on_leaves_the_edge_alone(self):
        t = np.arange(int(20 * SR)) / SR
        pad = np.stack([0.2 * np.sin(2 * np.pi * 220 * t)] * 2, axis=1)       # a steady tone: no hit anywhere
        self.assertEqual(V.refine_to_onset(pad, SR, 10.0), 10.0)

    def test_a_hit_further_than_50_ms_away_is_not_chased(self):
        y = self.hits(every=2.0)                                               # hits at 0.37, 2.37, ... 10.37
        self.assertEqual(V.refine_to_onset(y, SR, 11.4), 11.4)

    def test_plan_cuts_reports_the_move(self):
        y = self.hits()
        bars = np.arange(0.40, 30, 2.0)                                        # a grid that is 30 ms late
        rows = V.plan_cuts([(10.9, 18.9)], 30.0, 120, bars, refine=lambda t: V.refine_to_onset(y, SR, t))
        self.assertTrue(rows[0]["refined"])
        self.assertAlmostEqual(rows[0]["start"], 10.37, delta=0.004)
        self.assertAlmostEqual(rows[0]["end"], 18.37, delta=0.004)
        plain = V.plan_cuts([(10.9, 18.9)], 30.0, 120, bars)
        self.assertFalse(plain[0]["refined"])
        self.assertAlmostEqual(plain[0]["start"], 10.40, delta=1e-6)

    def test_end_to_end_the_plan_and_report_say_so(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            n = int(30 * SR)
            t = np.arange(n) / SR
            voc = np.stack([0.1 * np.sin(2 * np.pi * 440 * t)] * 2, axis=1)
            (root / "stems").mkdir()
            sf.write(str(root / "stems" / "Drums.wav"), self.hits(), SR, subtype="PCM_24")
            sf.write(str(root / "stems" / "Vox.wav"), voc, SR, subtype="PCM_24")
            code, text = run(["--stems", root / "stems", "--vocals", "Vox", "--cut", "0:11-0:19", "--bpm", "120", "--check"])
            self.assertEqual(code, 0, text)
            self.assertIn("then moved onto the nearest hit", text)
            self.assertIn("remove 0:10.37 to 0:18.37", text)


if __name__ == "__main__":
    unittest.main()
