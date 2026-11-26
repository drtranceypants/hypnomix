"""`hypnomix preflight`: the sanity of the files before any work. Everything is synthesised in a temporary folder.

    python -m unittest tests.test_preflight
"""
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from hypnomix.session import preflight as PF

SR = 44100
DUR = 8.0
N = int(DUR * SR)
T = np.arange(N) / SR


def run(*args, home=None):
    env = dict(os.environ)
    if home:
        env["HYPNOMIX_HOME"] = str(home)
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


def pulses(shift=0.0, width=0.2, seed=3):
    """The same uneven rhythm in every stem (so their envelopes agree), optionally played `shift` seconds later."""
    rng = np.random.default_rng(seed)
    e = np.zeros(N)
    for h in np.sort(rng.uniform(0.2, DUR - 0.6, 24)):
        i = int((h + shift) * SR)
        w = int(width * SR)
        if 0 <= i < N - w:
            e[i:i + w] += np.exp(-np.arange(w) / SR * 20)
    return e


def tone(f, **kw):
    return np.sin(2 * np.pi * f * T) * pulses(**kw)


def write(folder, name, y, sr=SR, subtype="PCM_24"):
    sf.write(str(Path(folder) / name), y, sr, subtype=subtype)


class Folder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._td.name)
        cls.home = cls.dir / "home"
        d = cls.dir / "stems"
        d.mkdir()
        cls.stems = d
        for n, f in (("Kick", 60), ("Bass", 98), ("Keys", 330), ("Vocal", 440)):
            write(d, f"{n}.wav", tone(f) * 0.5)
        write(d, "Keys 48k.wav", resample_poly(tone(330) * 0.5, 160, 147), 48000)         # another sample rate
        write(d, "Guitar 16.wav", tone(247) * 0.5, subtype="PCM_16")                       # another bit depth
        write(d, "Pad late.wav", tone(196, shift=0.8) * 0.5)                               # plays 0.8 s behind the rest
        write(d, "Short.wav", (tone(262) * 0.5)[:int(5 * SR)])                             # 3 s shorter
        write(d, "Kick copy.wav", tone(60) * 0.5)                                          # the same audio as Kick
        s = tone(523) * 0.3
        write(d, "Fake stereo.wav", np.stack([s, s], 1))
        write(d, "Silent.wav", np.zeros(N))
        write(d, "Quiet.wav", tone(300) * 0.001)                                           # -60 dBFS peak
        write(d, "DC.wav", tone(147) * 0.3 + 0.02)
        write(d, "Clipped.wav", np.clip(tone(110) * 6, -1, 1))
        write(d, "Bad:name?.wav", tone(392) * 0.3)
        write(d, "CON.wav", tone(294) * 0.3)
        write(d, "one side.wav", np.stack([tone(500) * 0.3, np.zeros(N)], 1))
        cls.lossy = shutil.which("ffmpeg") is not None
        if cls.lossy:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(d / "Vocal.wav"), "-b:a", "128k", str(d / "Vocal lossy.mp3")])
        cls.files, cls.findings, cls.notes, cls.kind = PF.analyse(d, progress=False)
        cls.by = {}
        for f in cls.findings:
            cls.by.setdefault(f["kind"], []).append(f)

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def who(self, kind):
        return " ".join(f["problem"] + " " + f["track"] for f in self.by.get(kind, []))

    def test_every_file_is_read(self):
        self.assertEqual(len(self.files), len(list(self.stems.iterdir())))
        self.assertEqual(self.kind, "Folder")

    def test_odd_one_out_sample_rate_and_depth(self):
        self.assertIn("Keys 48k.wav", self.who("mixed-sr"))
        self.assertIn("48000 Hz", self.who("mixed-sr"))
        self.assertIn("Guitar 16.wav", self.who("mixed-bits"))
        for f in self.by["mixed-sr"] + self.by["mixed-bits"]:
            self.assertIn("prep", f["fix"])                                # conversions are prep's own step
            self.assertEqual(f["applies"], "manual")

    def test_lengths_and_starts(self):
        self.assertIn("Short.wav", self.who("length"))
        self.assertIn("3.00 s shorter", self.who("length"))
        self.assertIn("Pad late.wav", self.who("start"))
        self.assertIn("0.80 s", self.who("start"))
        self.assertIn("behind", self.who("start"))
        self.assertNotIn("Kick.wav", self.who("start"))                    # stems that play together are left alone
        self.assertEqual(self.by["start"][0]["severity"], "high")

    def test_duplicates_fake_stereo_one_channel(self):
        self.assertIn("Kick copy.wav", self.who("duplicate"))
        self.assertIn("Kick.wav", self.who("duplicate"))
        self.assertNotIn("Silent.wav", self.who("duplicate"))             # silent files are not "duplicates" of each other
        self.assertIn("Fake stereo.wav", self.who("fake-stereo"))
        self.assertIn("one side.wav", self.who("one-channel"))

    def test_silent_quiet_dc_clipped(self):
        self.assertIn("Silent.wav", self.who("silent"))
        self.assertIn("Quiet.wav", self.who("quiet"))
        self.assertIn("DC.wav", self.who("dc"))
        self.assertIn("Clipped.wav", self.who("clipped"))
        self.assertNotIn("Bass.wav", self.who("clipped"))

    def test_lossy_sources(self):
        if not self.lossy:
            self.skipTest("no ffmpeg to make an mp3")
        self.assertIn("Vocal lossy.mp3", self.who("lossy"))
        self.assertNotIn("Vocal lossy.mp3", self.who("mixed-bits"))

    def test_names_that_will_not_travel(self):
        self.assertIn("Bad:name?.wav", self.who("name-chars"))
        self.assertIn("CON.wav", self.who("name-reserved"))
        self.assertIn("Bad-name-.wav", self.by["name-chars"][0]["fix"])
        self.assertIn("Nothing was renamed", self.by["name-chars"][0]["fix"])

    def test_name_helpers(self):
        self.assertEqual(PF.safe_name('a<b>:"c|d?.wav'), "a-b---c-d-.wav")
        self.assertEqual(PF.safe_name("trailing. .wav"), "trailing.wav")
        self.assertEqual(PF.safe_name("NUL.wav"), "NUL-1.wav")
        self.assertTrue(len(PF.safe_name("x" * 400 + ".wav").encode()) <= 110)
        kinds = [k for k, _ in PF.name_problems(Path("x" * 300 + ".wav"))]
        self.assertIn("long", kinds)
        kinds = [k for k, _ in PF.name_problems(Path("café.wav"))]
        self.assertEqual(kinds, ["accents"])
        self.assertEqual(PF.name_problems(Path("plain name.wav")), [])

    def test_names_differing_only_by_case(self):
        out = PF.check_names([Path("/x/Kick.wav"), Path("/x/kick.WAV".replace("WAV", "wav")), Path("/x/Snare.wav")])
        self.assertEqual([f["kind"] for f in out], ["name-case"])

    def test_severities_and_exit_code(self):
        self.assertTrue(any(f["severity"] == "high" for f in self.findings))
        code, txt = run("preflight", self.stems, "--out", self.dir / "out1", home=self.home)
        self.assertEqual(code, 1)                                           # something high: a script can gate on it
        md = (self.dir / "out1" / "PREFLIGHT.md").read_text()
        self.assertIn("## Every file", md)
        self.assertIn("Nothing was changed, renamed or deleted", md)

    def test_a_clean_folder_passes(self):
        d = self.dir / "clean"
        d.mkdir()
        for n, f in (("Kick", 60), ("Bass", 98), ("Keys", 330)):
            write(d, f"{n}.wav", tone(f) * 0.4)
        code, txt = run("preflight", d, "--out", self.dir / "out2", home=self.home)
        self.assertEqual(code, 0, txt)
        self.assertIn("Nothing to fix", txt)

    def test_nothing_in_the_folder_is_touched(self):
        before = {p.name: p.read_bytes() for p in self.stems.iterdir()}
        PF.analyse(self.stems, progress=False)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.stems.iterdir()})
        self.assertEqual(sorted(p.name for p in self.stems.iterdir()), sorted(before))

    def test_start_check_finds_the_lag(self):
        envs = {}
        for n, kw in (("a", {}), ("b", {}), ("c", dict(shift=0.5))):
            y = tone(200 + len(envs), **kw)
            b = int(PF.HOP * SR)
            k = len(y) // b
            envs[n] = np.sqrt(np.sqrt((y[:k * b].reshape(k, b) ** 2).mean(axis=1)))
        lag = PF.lags(envs)
        self.assertAlmostEqual(abs(lag["c"][0]), 0.5, delta=0.03)
        self.assertLess(abs(lag["a"][0]), 0.05)

    # ---------------------------------------------------------------- repairs found by the independent check
    def test_stems_with_different_rhythms_are_not_called_late(self):
        """Clean stems that all start at bar 1 but play different parts used to be flagged 'high' by a loose match."""
        d = self.dir / "different"
        d.mkdir()
        for k, (n, f) in enumerate((("Kick", 60), ("Bass", 98), ("Keys", 330), ("Lead", 440), ("Pad", 196))):
            write(d, f"{n}.wav", np.sin(2 * np.pi * f * T) * pulses(seed=10 + 7 * k) * 0.5)
        _, findings, _, _ = PF.analyse(d, progress=False)
        self.assertEqual([f for f in findings if f["kind"] == "start"], [])
        code, txt = run("preflight", d, "--out", self.dir / "out_diff", home=self.home)
        self.assertEqual(code, 0, txt)

    def test_a_clear_shift_has_a_near_perfect_match(self):
        n = 400
        rng = np.random.default_rng(5)
        base = np.abs(rng.standard_normal(n)).astype(np.float32) + 0.2
        envs = {"a": base, "b": base.copy(), "c": base.copy(), "late": np.roll(base, 8)}
        lag = PF.lags(envs, 5.0)["late"]
        self.assertAlmostEqual(abs(lag[0]), 8 * PF.HOP, delta=0.05)
        self.assertGreaterEqual(lag[1], 0.9)

    def test_a_steady_rhythm_reports_the_nearest_lag(self):
        """A 1.5 Hz pulse matches every period away: the stem that is 1.00 s late was reported 5.00 s late."""
        d = self.dir / "steady"
        d.mkdir()
        def pulse(shift=0.0):
            ph = ((T - shift) * 1.5) % 1.0
            return np.where(T >= shift, np.exp(-ph * 8), 0.0)
        for n, f in (("Kick", 60), ("Bass", 98), ("Keys", 330)):
            write(d, f"{n}.wav", np.sin(2 * np.pi * f * T) * pulse() * 0.5)
        write(d, "late.wav", np.sin(2 * np.pi * 200 * T) * pulse(1.0) * 0.5)
        _, findings, _, _ = PF.analyse(d, progress=False)
        start = [f for f in findings if f["kind"] == "start" and f["track"] == "late.wav"]
        self.assertEqual(len(start), 1, findings)
        self.assertTrue("1.00 s" in start[0]["problem"] or "0.67 s" in start[0]["problem"], start[0]["problem"])
        self.assertNotIn("5.00 s", start[0]["problem"])
        self.assertIn("whole number of beats", start[0]["problem"])

    def test_a_very_quiet_stereo_file_is_not_called_mono(self):
        d = self.dir / "quietstereo"
        d.mkdir()
        s = tone(300) * 0.0004
        write(d, "quiet.wav", np.stack([s, s * 0.9], 1))
        write(d, "same.wav", np.stack([s, s], 1))
        f = {x["name"]: x for x in (PF.inspect(d / "quiet.wav"), PF.inspect(d / "same.wav"))}
        self.assertFalse(f["quiet.wav"]["fake_stereo"])
        self.assertTrue(f["same.wav"]["fake_stereo"])


    # ---------------------------------------------------------------- the plan
    def test_plan_review_and_fix_use_preps_own_steps(self):
        scan = self.dir / "scan"
        code, txt = run("preflight", self.stems, "--plan", scan, home=self.home)
        self.assertEqual(code, 0, txt)
        data = json.loads((scan / "findings.json").read_text())
        fs = data["findings"]
        self.assertEqual(len(fs), len(self.findings))
        planned = {f["kind"]: f for f in fs if f.get("plan")}
        self.assertEqual({k: v["plan"]["step"] for k, v in planned.items()}, {"dc": "rumble", "clipped": "declip", "fake-stereo": "mono"})
        self.assertTrue(all(f["plan"]["tool"] == "prep" for f in planned.values()))
        self.assertTrue(all(f["applies"] == "manual" for f in fs if not f.get("plan")))
        before = {p.name: p.read_bytes() for p in self.stems.iterdir()}
        ids = [planned["dc"]["id"], planned["fake-stereo"]["id"]]
        code, txt = run("fix", scan, "--decide", ",".join(f"{i}=approve" for i in ids), home=self.home)
        self.assertEqual(code, 0, txt)
        code, txt = run("fix", scan, "--approved", home=self.home)
        self.assertEqual(code, 0, txt)
        made = sorted(p.name for p in (scan / "fixed" / "prep").glob("*.wav"))
        self.assertEqual(made, ["DC (prep).wav", "Fake stereo (prep).wav"])        # only what was approved
        self.assertEqual(sf.info(str(scan / "fixed" / "prep" / "Fake stereo (prep).wav")).channels, 1)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.stems.iterdir()})


RPP = """<REAPER_PROJECT 0.1 "7.27/macOS-arm64" 1764000000
  RIPPLE 0
  TEMPO 100 4 4
  SAMPLERATE 48000 0 0
  RECORD_PATH "Audio" ""
  <TRACK {11111111-1111-1111-1111-111111111111}
    NAME Guitar
    VOLPAN 1 0 -1 -1 1
    MUTESOLO 0 0 0
    IPHASE 0
    ISBUS 0 0
    <ITEM
      POSITION 0
      SNAPOFFS 0
      LENGTH 4
      LOOP 0
      ALLTAKES 0
      FADEIN 1 0 0 1 0 0 0
      FADEOUT 1 0 0 1 0 0 0
      MUTE 0 0
      SEL 0
      NAME gtr
      VOLPAN 1 0 1 -1
      SOFFS 0
      PLAYRATE 1 1 0 -1 0 0.0025
      CHANMODE 0
      <SOURCE WAVE
        FILE "Audio/gtr.wav"
      >
    >
    <ITEM
      POSITION 4
      SNAPOFFS 0
      LENGTH 4
      LOOP 0
      ALLTAKES 0
      FADEIN 1 0 0 1 0 0 0
      FADEOUT 1 0 0 1 0 0 0
      MUTE 0 0
      SEL 0
      NAME gone
      VOLPAN 1 0 1 -1
      SOFFS 0
      PLAYRATE 1 1 0 -1 0 0.0025
      CHANMODE 0
      <SOURCE WAVE
        FILE "Audio/Where: is it?.wav"
      >
    >
  >
  <TRACK {22222222-2222-2222-2222-222222222222}
    NAME Vocal
    VOLPAN 1 0 -1 -1 1
    MUTESOLO 0 0 0
    IPHASE 0
    ISBUS 0 0
    <ITEM
      POSITION 0
      SNAPOFFS 0
      LENGTH 8
      LOOP 0
      ALLTAKES 0
      FADEIN 1 0 0 1 0 0 0
      FADEOUT 1 0 0 1 0 0 0
      MUTE 0 0
      SEL 0
      NAME vox
      VOLPAN 1 0 1 -1
      SOFFS 0
      PLAYRATE 1 1 0 -1 0 0.0025
      CHANMODE 0
      <SOURCE WAVE
        FILE "Audio/vox.mp3"
      >
    >
  >
>
"""


class Project(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._td.name)
        cls.home = cls.dir / "home"
        (cls.dir / "Audio").mkdir()
        write(cls.dir / "Audio", "gtr.wav", tone(247) * 0.4)              # 44.1 kHz in a 48 kHz project
        cls.mp3 = shutil.which("ffmpeg") is not None
        if cls.mp3:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(cls.dir / "Audio" / "gtr.wav"), "-b:a", "128k",
                            str(cls.dir / "Audio" / "vox.mp3")])
        cls.rpp = cls.dir / "Song.rpp"
        cls.rpp.write_text(RPP)

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def test_missing_lossy_rate_and_name_in_a_project(self):
        files, findings, notes, kind = PF.analyse(self.rpp, progress=False)
        self.assertEqual(kind, "REAPER project")
        by = {f["kind"]: f for f in findings}
        self.assertIn("missing", by)
        self.assertEqual(by["missing"]["severity"], "high")
        self.assertIn("Guitar", by["missing"]["problem"])                  # which track needs it
        self.assertIn("project-rate", by)
        self.assertIn("48000", by["project-rate"]["problem"])
        self.assertIn("name-chars", by)
        self.assertIn("media list", by["name-chars"]["fix"])               # in a project: rename where the links follow
        self.assertNotIn("length", by)                                       # clips of a project are placed, not compared
        if self.mp3:
            self.assertIn("lossy", by)
        self.assertTrue(any("not compared" in n for n in notes))

    def test_project_untouched_and_exit_code(self):
        before = self.rpp.read_bytes()
        code, txt = run("preflight", self.rpp, "--out", self.dir / "o", home=self.home)
        self.assertEqual(code, 1)
        self.assertIn("is used by Guitar and is not there", txt)
        self.assertEqual(before, self.rpp.read_bytes())

    def test_plan_for_a_project(self):
        scan = self.dir / "scanp"
        code, txt = run("preflight", self.rpp, "--plan", scan, home=self.home)
        self.assertEqual(code, 0, txt)
        data = json.loads((scan / "findings.json").read_text())
        self.assertTrue(any(f["kind"] == "missing" for f in data["findings"]))
        self.assertIn("preflight", (scan / "REVIEW.md").read_text())

    def test_a_live_set_is_read_the_same_way(self):
        sys.path.insert(0, str(Path(__file__).parent))
        from tests.test_workflow import make_set
        als = make_set(self.dir / "Song.als")
        files, findings, notes, kind = PF.analyse(als, progress=False)
        self.assertEqual(kind, "Live set")
        self.assertEqual(len([f for f in findings if f["kind"] == "missing"]), 1)     # counted once, however it is found

    def test_bad_input(self):
        code, txt = run("preflight", self.dir / "nope", home=self.home)
        self.assertNotEqual(code, 0)
        empty = self.dir / "empty"
        empty.mkdir()
        code, txt = run("preflight", empty, home=self.home)
        self.assertNotEqual(code, 0)
        self.assertIn("no audio files", txt)

    def test_a_broken_project_is_one_plain_line(self):
        junk = self.dir / "junk.rpp"
        junk.write_text("junk\n")
        code, txt = run("preflight", junk, "--out", self.dir / "oj", home=self.home)
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", txt)
        self.assertIn("junk.rpp", txt)
        self.assertIn("REAPER project", txt)
        als = self.dir / "junk.als"
        als.write_text("hello\n")
        code, txt = run("preflight", als, "--out", self.dir / "oj2", home=self.home)
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", txt)
        self.assertIn("junk.als", txt)
        self.assertEqual(len([l for l in txt.strip().splitlines() if l.strip()]), 1, txt)


if __name__ == "__main__":
    unittest.main()
