"""`hypnomix demo`: the demo song is deterministic, has the six labelled problems where it says, and the project it writes loads.

    python -m unittest tests.test_demo
"""
import hashlib, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix import project
from hypnomix.core import dsp
from hypnomix.project import rpp
from hypnomix.studio import demo as D

SR = D.SR


def digest(a):
    return hashlib.sha1(np.ascontiguousarray(a).tobytes()).hexdigest()


def run(*args):
    env = dict(os.environ)
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


def freq_near(x, f0, sr=SR, cents=90):
    """The strongest frequency within `cents` of f0, by a zero-padded FFT with parabolic interpolation."""
    n = 1 << 17
    w = x * np.hanning(len(x))
    sp = np.abs(np.fft.rfft(w, n))
    fr = np.fft.rfftfreq(n, 1 / sr)
    lo, hi = f0 * 2 ** (-cents / 1200), f0 * 2 ** (cents / 1200)
    sel = np.flatnonzero((fr >= lo) & (fr <= hi))
    k = sel[np.argmax(sp[sel])]
    a, b, c = np.log(sp[k - 1] + 1e-12), np.log(sp[k] + 1e-12), np.log(sp[k + 1] + 1e-12)
    return fr[k] + 0.5 * (a - c) / (a - 2 * b + c) * (fr[1] - fr[0])


class Song(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.takes = D.levels(D.make(7))

    def test_forty_seconds_and_every_part(self):
        self.assertAlmostEqual(D.DUR, 40.0)
        for k in ("Drums", "Bass", "Keys", "Lead Vocal", "Harmony", "Keys take 1", "Keys take 2", "Lead Vocal take 1", "Lead Vocal take 2"):
            self.assertEqual(len(self.takes[k]), D.N, k)
            self.assertTrue(np.isfinite(self.takes[k]).all(), k)
            self.assertGreater(np.abs(self.takes[k]).max(), 0.05, k)

    def test_deterministic_and_seeded(self):
        again = D.levels(D.make(7))
        for k in self.takes:
            self.assertEqual(digest(self.takes[k]), digest(again[k]), k)
        other = D.levels(D.make(8))
        self.assertNotEqual(digest(self.takes["Drums"]), digest(other["Drums"]))

    def test_problem_1_a_click_at_the_keys_cut(self):
        k = self.takes["Keys"]
        i = int(D.CUT_KEYS * D.SR)
        jump = abs(k[i] - k[i - 1])
        typical = np.median(np.abs(np.diff(k[i - 4000:i - 200])))
        self.assertGreater(jump, 6 * typical)                       # a step the notes themselves never make

    def test_problem_2_a_level_jump_at_the_lead_cut(self):
        l1, l2 = self.takes["Lead Vocal take 1"], self.takes["Lead Vocal take 2"]
        i = int(D.CUT_LEAD * D.SR)
        w = int(0.4 * D.SR)
        before = dsp.rms_db(self.takes["Lead Vocal"][i - w - 500:i - 500])
        after = dsp.rms_db(self.takes["Lead Vocal"][i + 500:i + w + 500])
        self.assertAlmostEqual(after - before, D.LEAD_JUMP_DB, delta=2.0)
        self.assertGreater(np.abs(self.takes["Lead Vocal"][i - w:i + w]).max(), 0.05)       # it is sounding there

    def test_problem_3_hiss_in_the_pauses_of_the_harmony(self):
        pause = self.takes["Harmony"][int(0.5 * SR):int(4.0 * SR)]                 # before the first note: only the hiss
        self.assertAlmostEqual(dsp.rms_db(pause), D.HISS_DB, delta=1.5)
        for k in ("Drums", "Keys", "Lead Vocal"):                                   # and nothing else carries it
            self.assertLess(dsp.rms_db(self.takes[k][int(0.1 * SR):int(0.3 * SR)]), -80 if k == "Lead Vocal" else 0)

    def test_problem_4_clipped_bass(self):
        b = self.takes["Bass"]
        top = np.abs(b) >= 0.9999
        runs = int((np.diff(np.concatenate([[0], top.view(np.int8), [0]])) == 1).sum())
        self.assertGreaterEqual(runs, 5)
        first = np.flatnonzero(top)[0] / SR
        self.assertGreaterEqual(first, D.HOT_BARS[0] * D.BAR)       # only in the hot bars
        self.assertLess(np.flatnonzero(top)[-1] / SR, (D.HOT_BARS[1] + 1) * D.BAR)
        for k in ("Drums", "Keys", "Harmony", "Lead Vocal"):
            self.assertLess(np.abs(self.takes[k]).max(), 0.99, k)  # nothing else is clipped

    def cents(self, which, start, midi):
        """How far, in cents, the note that starts at `start` is from equal temperament (FFT of 0.6 s of its middle)."""
        a = int((start + 0.25) * SR)
        seg = self.takes[which][a:a + int(0.6 * SR)]
        return 1200 * np.log2(freq_near(seg, D.hz(midi)) / D.hz(midi))

    def long_note_after(self, t):
        return next((st, m) for st, ln, m in D.melody() if st >= t and ln > 1.0)

    def test_problem_5_the_harmony_drifts_sharp(self):
        """The same kind of note early and late: the harmony's pitch against equal temperament, the lead's beside it."""
        st0, m0 = self.long_note_after(5.0)
        st1, m1 = self.long_note_after(34.0)
        up = lambda m: D.SCALE_ALL[D.SCALE_ALL.index(m) + 2]                        # the harmony sings a diatonic third above
        self.assertLess(abs(self.cents("Harmony", st0, up(m0))), 22)
        self.assertGreater(self.cents("Harmony", st1, up(m1)), 25)
        self.assertGreater(st1, D.DRIFT_FROM)
        self.assertLess(abs(self.cents("Lead Vocal", st1, m1)), 22)                # the lead stays in tune where the harmony does not

    def test_problem_6_the_drums_fall_behind(self):
        d = self.takes["Drums"]
        def kick_at(bar):
            a = int(bar * D.BAR * SR)
            seg = np.abs(d[a - int(0.02 * SR):a + int(0.15 * SR)])
            return (np.argmax(seg > 0.5 * seg.max()) - int(0.02 * SR)) / SR
        on_time = kick_at(3)
        late = kick_at(D.LATE_BARS[-1])
        self.assertLess(abs(on_time), 0.02)
        self.assertGreater(late - on_time, 0.04)                    # about 65 ms by bar 14

    def test_the_problems_are_listed(self):
        p = D.problems()
        self.assertEqual([x["n"] for x in p], [1, 2, 3, 4, 5, 6])
        for x in p:
            self.assertTrue(x["what"] and x["where"] and x["found_by"] and x["fix"])


class Written(unittest.TestCase):
    _made = {}

    def setUp(self):
        """Writing the demo makes the song each time (a few seconds): make it once for the whole class."""
        from unittest import mock
        real = D.make

        def cached(seed=7):
            if seed not in Written._made:
                Written._made[seed] = real(seed)
            return Written._made[seed]
        p = mock.patch.object(D, "make", cached)
        p.start()
        self.addCleanup(p.stop)

    def test_folder_kind(self):
        with tempfile.TemporaryDirectory() as td:
            path, folder = D.write_demo(td, "folder")
            self.assertEqual(path, folder)
            names = sorted(p.name for p in folder.iterdir())
            self.assertEqual(names, ["Bass.wav", "DEMO.md", "Drums.wav", "Harmony.wav", "Keys.wav", "Lead Vocal.wav", "demo.json"])
            for n in ("Bass.wav", "Drums.wav", "Harmony.wav", "Keys.wav", "Lead Vocal.wav"):
                info = sf.info(str(folder / n))
                self.assertEqual((info.samplerate, info.channels, info.subtype), (44100, 1, "PCM_24"))
                self.assertAlmostEqual(info.duration, 40.0, delta=0.01)
            md = (folder / "DEMO.md").read_text()
            for n in "123456":
                self.assertIn(f"| {n} |", md)
            self.assertIn("hypnomix scan", md)
            self.assertEqual(json.loads((folder / "demo.json").read_text())["kind"], "folder")
            path2, folder2 = D.write_demo(td, "folder")               # never reuses or overwrites a folder
            self.assertNotEqual(folder, folder2)
            self.assertTrue(folder.exists() and folder2.exists())

    def test_reaper_kind_loads_and_round_trips(self):
        with tempfile.TemporaryDirectory() as td:
            path, folder = D.write_demo(td, "reaper")
            self.assertEqual(path.suffix, ".rpp")
            text = path.read_text()
            self.assertEqual(rpp.dumps(rpp.load(path)), text)                      # the parser gives back exactly what was written
            p = project.load(path)
            self.assertEqual((p.daw, p.tempo, p.beats_per_bar, p.sample_rate), ("reaper", 96.0, 4, 44100))
            self.assertEqual([t.name for t in p.tracks], ["Drums", "Bass", "Keys", "Lead Vocal", "Harmony"])
            self.assertEqual(p.missing(), [])                                      # every item finds its file
            self.assertAlmostEqual(p.end(), D.DUR, delta=0.1)
            keys = p.track("Keys")
            self.assertEqual([c.takes[0].path.name for c in keys.clips], ["Keys take 1.wav", "Keys take 2.wav"])
            self.assertAlmostEqual(keys.clips[1].start, D.CUT_KEYS)
            self.assertEqual(keys.clips[1].fade_in, 0.0)                           # the click is the missing fade
            self.assertAlmostEqual(keys.clips[1].takes[0].offset, D.CUT_KEYS)      # the second take plays from where it was cut in
            lead = p.track("Lead Vocal")
            self.assertAlmostEqual(lead.clips[1].start, D.CUT_LEAD)
            self.assertGreater(lead.clips[1].fade_in, 0.0)                         # that cut has fades: its problem is the level
            self.assertTrue((folder / "Audio" / "Harmony.wav").exists())
            self.assertGreater(len(p.render(keys)), 0)                             # and it renders

    def test_the_command(self):
        with tempfile.TemporaryDirectory() as td:
            code, txt = run("demo", "--out", td, "--kind", "reaper")
            self.assertEqual(code, 0, txt)
            self.assertIn("hypnomix scan", txt)
            self.assertIn(".rpp", txt)
            self.assertTrue(list(Path(td).glob("*/*.rpp")))
            code, txt = run("demo", "-h")
            self.assertEqual(code, 0)
            self.assertIn("Live", txt)                                              # says why there is no Live kind

    def test_preflight_and_scan_clean_start(self):
        """The demo is a project the other tools can open: preflight reads it, and its only finding is the bass clipping."""
        from hypnomix.session import preflight as PF
        with tempfile.TemporaryDirectory() as td:
            path, _ = D.write_demo(td, "reaper")
            files, findings, notes, kind = PF.analyse(path, progress=False)
            self.assertEqual(kind, "REAPER project")
            self.assertEqual([f["kind"] for f in findings], ["clipped"])
            self.assertEqual(findings[0]["track"], "Bass.wav")


if __name__ == "__main__":
    unittest.main()
