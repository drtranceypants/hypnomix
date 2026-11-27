"""Fixes in the scan and review area: files that cannot be measured, inputs that cannot be read, outputs that were
overwritten, options that were ignored in silence, and the review page that grew with the square of the findings.

Everything is synthesised in a temporary folder; every command runs with its settings and caches in that folder.

    python -m unittest tests.test_fix_scan
"""
import gzip, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
SR = 44100


def env_for(base):
    env = dict(os.environ)
    env.pop("HYPNOMIX_OUT", None)
    env.update(HOME=str(base / "fakehome"), HYPNOMIX_HOME=str(base / "home"), HYPNOMIX_APP_HOME=str(base / "work"),
               HYPNOMIX_USER_HOME=str(base / "fakehome"), HYPNOMIX_DISKCARE="off", PYTHONPATH=str(ROOT))
    return env


def hx(base, *args, cwd=None):
    """Run a hypnomix command with everything it writes inside `base`; (exit code, stdout + stderr)."""
    (base / "fakehome").mkdir(exist_ok=True)
    cwd = Path(cwd) if cwd else base / "cwd"
    cwd.mkdir(exist_ok=True)
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True,
                       env=env_for(base), cwd=str(cwd), encoding="utf-8")
    return r.returncode, r.stdout + r.stderr


def gated(freq, seconds=4.0, rate=0.7, amp=0.4):
    t = np.arange(int(seconds * SR)) / SR
    return amp * np.sin(2 * np.pi * freq * t) * (np.sin(2 * np.pi * rate * t) > 0)


def stems_folder(d, names=("bass", "keys", "vox", "drums")):
    d.mkdir(parents=True, exist_ok=True)
    for n, f in zip(names, (60, 440, 1000, 200)):
        sf.write(str(d / f"{n}.wav"), gated(f, rate=0.5 + f / 2000), SR, subtype="PCM_24")
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.base = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def hx(self, *args, cwd=None):
        return hx(self.base, *args, cwd=cwd)


# ---------------------------------------------------------------- preflight
class PreflightFixes(Base):
    def test_a_constant_level_file_does_not_crash_the_start_check(self):
        """A file at one exact level has float-rounding 'variation' of ~1e-8: it used to survive the filter and end the
        whole run in 'min() arg is an empty sequence'."""
        d = self.base / "stems"
        d.mkdir()
        sf.write(str(d / "dc.wav"), np.full(5 * SR, 0.5), SR)
        sf.write(str(d / "mono.wav"), gated(220, 5, 0.7), SR)
        sf.write(str(d / "stereo.wav"), np.stack([gated(330, 5, 0.9)] * 2, 1), SR)
        code, out = self.hx("preflight", d, "--out", self.base / "o")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Traceback", out)
        self.assertTrue((self.base / "o" / "PREFLIGHT.md").exists())
        self.assertIn("DC offset", out)                      # the constant file is still said to be a steady offset
        code, out = self.hx("preflight", d, "--plan", self.base / "scan")
        self.assertEqual(code, 0, out)

    def test_lags_ignores_a_constant_envelope(self):
        from hypnomix.session import preflight as PF
        t = np.arange(400)
        envs = {"flat": np.full(400, 0.3, dtype=np.float32), "a": (np.sin(t / 9.0) + 1.5).astype(np.float32),
                "b": (np.sin(t / 7.0) + 1.5).astype(np.float32)}
        out = PF.lags(envs)
        self.assertNotIn("flat", out)

    def test_nan_samples_are_a_high_finding_and_the_numbers_stay_finite(self):
        from hypnomix.session import preflight as PF
        d = stems_folder(self.base / "stems")
        y = gated(300, 6)
        y[1000:1010] = np.nan
        sf.write(str(d / "broken.wav"), y.astype("float32"), SR, subtype="FLOAT")
        files, findings, _, _ = PF.analyse(d, progress=False)
        hit = [f for f in findings if f["kind"] == "non-finite"]
        self.assertEqual([f["track"] for f in hit], ["broken.wav"])
        self.assertEqual(hit[0]["severity"], "high")
        self.assertIn("10 invalid samples", hit[0]["problem"])
        row = next(f for f in files if f["name"] == "broken.wav")
        self.assertTrue(np.isfinite(row["peak_db"]))
        code, out = self.hx("preflight", d, "--out", self.base / "o")
        self.assertEqual(code, 1, out)                       # high: the exit code gates a script
        self.assertNotIn("nan dBFS", out)

    def test_zero_length_and_six_channel_files_are_findings_not_a_crash(self):
        from hypnomix.session import preflight as PF
        d = stems_folder(self.base / "stems")
        sf.write(str(d / "empty.wav"), np.zeros((0, 1)), SR)
        sf.write(str(d / "surround.wav"), np.random.default_rng(1).normal(0, 0.1, (2 * SR, 6)).astype("float32"), SR)
        _, findings, _, _ = PF.analyse(d, progress=False)
        kinds = {(f["kind"], f["track"]) for f in findings}
        self.assertIn(("channels", "surround.wav"), kinds)
        self.assertIn(("silent", "empty.wav"), kinds)
        self.assertNotIn(("length", "empty.wav"), kinds)     # an empty file is empty, not "4 s shorter"

    def test_a_second_run_never_overwrites_the_first_report(self):
        d = stems_folder(self.base / "stems")
        code, out = self.hx("preflight", d)
        self.assertEqual(code, 0, out)
        first = self.base / "cwd" / "hypnomix-out" / "preflight" / "stems" / "PREFLIGHT.md"
        self.assertTrue(first.exists())
        before = first.read_text(encoding="utf-8")
        e = stems_folder(self.base / "other stems", names=("a", "b", "c"))
        code, out = self.hx("preflight", e)
        self.assertEqual(code, 0, out)
        self.assertEqual(first.read_text(encoding="utf-8"), before)          # the first report is untouched
        self.assertTrue((self.base / "cwd" / "hypnomix-out" / "preflight" / "other stems" / "PREFLIGHT.md").exists())
        code, out = self.hx("preflight", d)                  # the same source again: a numbered folder
        self.assertEqual(code, 0, out)
        self.assertEqual(first.read_text(encoding="utf-8"), before)
        self.assertTrue((self.base / "cwd" / "hypnomix-out" / "preflight" / "stems (2)" / "PREFLIGHT.md").exists())

    def test_an_out_folder_that_holds_a_report_is_refused(self):
        d = stems_folder(self.base / "stems")
        o = self.base / "o"
        self.assertEqual(self.hx("preflight", d, "--out", o)[0], 0)
        before = (o / "PREFLIGHT.md").read_text(encoding="utf-8")
        code, out = self.hx("preflight", d, "--out", o)
        self.assertEqual(code, 2, out)
        self.assertEqual(len([l for l in out.strip().splitlines() if l.strip()]), 1, out)
        self.assertIn("nothing is overwritten", out)
        self.assertEqual((o / "PREFLIGHT.md").read_text(encoding="utf-8"), before)


# ---------------------------------------------------------------- scan: files that cannot be measured
class FilesThatCannotBeMeasured(Base):
    def folder(self):
        d = stems_folder(self.base / "zf")
        sf.write(str(d / "empty.wav"), np.zeros((0, 1)), SR)
        sf.write(str(d / "surround51.wav"), np.random.default_rng(2).normal(0, 0.1, (2 * SR, 6)).astype("float32"), SR)
        y = gated(300, 6)
        y[1000:1010] = np.nan
        sf.write(str(d / "nanonly.wav"), y.astype("float32"), SR, subtype="FLOAT")
        return d

    def test_one_bad_file_does_not_disable_the_stems_group(self):
        d = self.folder()
        code, out = self.hx("scan", d, "--out", self.base / "s")
        self.assertEqual(code, 0, out)
        self.assertNotIn("did NOT run", out)
        findings = json.loads((self.base / "s" / "findings.json").read_text(encoding="utf-8"))["findings"]
        by = {(f["track"], f["kind"]) for f in findings}
        self.assertIn(("empty.wav", "empty"), by)
        self.assertIn(("surround51.wav", "channels"), by)
        self.assertIn(("nanonly.wav", "non-finite"), by)
        stems = json.loads((self.base / "s" / "stems.json").read_text(encoding="utf-8"))
        self.assertTrue(any("empty.wav" in n and "left out" in n for n in stems["notes"]), stems["notes"])
        self.assertTrue(any("nanonly.wav" in n and "left out" in n for n in stems["notes"]), stems["notes"])
        high = [f for f in findings if f["kind"] == "non-finite"]
        self.assertEqual(high[0]["severity"], "high")

    def test_the_recordings_facts_are_valid_json(self):
        d = self.folder()
        self.assertEqual(self.hx("scan", d, "--out", self.base / "s")[0], 0)
        text = (self.base / "s" / "raw" / "recordings.json").read_text(encoding="utf-8")
        self.assertNotIn("NaN", text)
        json.loads(text)                                     # strict readers refuse a bare NaN

    def test_load_stems_skips_what_it_is_told_to_skip(self):
        from hypnomix.engineer import masking as M
        d = self.folder()
        bad = []
        stems, sr = M.load_stems(d, skipped=bad)
        self.assertEqual(sorted(n for n, _ in stems), ["bass", "drums", "keys", "vox"])
        self.assertLessEqual({"empty.wav", "nanonly.wav"}, {n for n, _ in bad})      # (a six-channel file too, where the loader refuses it)


# ---------------------------------------------------------------- scan: inputs and options
class ScanInputs(Base):
    def assertOneLine(self, out):
        self.assertNotIn("Traceback", out)
        self.assertEqual(len([l for l in out.strip().splitlines() if l.strip()]), 1, out)

    def test_unreadable_inputs_end_in_one_sentence_and_make_no_scan_folder(self):
        stems = stems_folder(self.base / "stems")
        (self.base / "Bad.rpp").write_text("not xml\n", encoding="utf-8")
        (self.base / "Bad.ardour").write_text("not xml\n", encoding="utf-8")
        (self.base / "Junk.als").write_text("junk\n", encoding="utf-8")
        (self.base / "Song.ptx").write_text("x\n", encoding="utf-8")
        shutil.copy(stems / "bass.wav", self.base / "Keys.wav")
        for name, word in (("Bad.rpp", "REAPER project"), ("Bad.ardour", "HypnoMix DAW session"), ("Junk.als", "Live set"),
                           ("Song.ptx", "not something scan can read"), ("Keys.wav", "not something scan can read")):
            code, out = self.hx("scan", self.base / name)
            self.assertNotEqual(code, 0, out)
            self.assertOneLine(out)
            self.assertIn(name, out)
            self.assertIn(word, out)
        self.assertFalse((self.base / "cwd" / "hypnomix-out").exists())      # nothing half-made
        code, out = self.hx("project", self.base / "Bad.rpp")
        self.assertNotEqual(code, 0)
        self.assertOneLine(out)

    def test_merge_needs_a_scan_folder(self):
        code, out = self.hx("scan", "--merge", self.base / "typo" / "folder")
        self.assertNotEqual(code, 0)
        self.assertOneLine(out)
        self.assertFalse((self.base / "typo").exists())
        (self.base / "emptyd").mkdir()
        code, out = self.hx("scan", "--merge", self.base / "emptyd")
        self.assertNotEqual(code, 0)
        self.assertEqual(list((self.base / "emptyd").iterdir()), [])

    def test_since_on_a_folder_is_refused_and_says_why(self):
        d = stems_folder(self.base / "stems")
        code, out = self.hx("scan", d, "--since", self.base / "x", "--out", self.base / "s2")
        self.assertNotEqual(code, 0)
        self.assertIn("--since is for a Live set", out)
        self.assertIn("a folder of recordings", out)
        self.assertFalse((self.base / "s2").exists())

    def test_options_a_folder_cannot_use_are_said_and_not_recorded(self):
        d = stems_folder(self.base / "stems")
        mix = self.base / "mix.wav"
        sf.write(str(mix), gated(220), SR)
        code, out = self.hx("scan", d, "--mix", mix, "--key", "A minor", "--deep", "--out", self.base / "s")
        self.assertEqual(code, 0, out)
        self.assertIn("--mix, --key, --deep are not used for a folder of recordings", out)
        review = (self.base / "s" / "REVIEW.md").read_text(encoding="utf-8")
        self.assertIn("--mix, --key, --deep were given but are not used", review)
        info = json.loads((self.base / "s" / "scan.json").read_text(encoding="utf-8"))
        self.assertIsNone(info["mix"])
        self.assertIsNone(info["key"])

    def test_the_footer_of_a_folder_scan_does_not_talk_about_live(self):
        d = stems_folder(self.base / "stems")
        sf.write(str(d / "hot.wav"), np.clip(gated(110) * 6, -1, 1), SR)
        self.assertEqual(self.hx("scan", d, "--out", self.base / "s")[0], 0)
        review = (self.base / "s" / "REVIEW.md").read_text(encoding="utf-8")
        self.assertNotIn("Close the set in Live", review)
        self.assertNotIn("(fixed).als", review)
        self.assertIn("repaired COPY", review)

    def test_fix_says_when_out_is_not_used_for_a_folder_scan(self):
        d = stems_folder(self.base / "stems")
        sf.write(str(d / "hot.wav"), np.clip(gated(110) * 6, -1, 1), SR)
        s = self.base / "s"
        self.assertEqual(self.hx("scan", d, "--out", s)[0], 0)
        findings = json.loads((s / "findings.json").read_text(encoding="utf-8"))["findings"]
        manual = [f for f in findings if f.get("applies") == "manual"]
        self.assertTrue(manual, findings)
        code, out = self.hx("fix", s, "--approve", manual[0]["id"], "--out", "Stems (fixed).als")
        self.assertIn("--out is not used", out)

    def test_a_plan_never_merges_into_the_scan_of_another_source(self):
        from hypnomix.workflow import plan as P
        a = stems_folder(self.base / "stems a")
        b = stems_folder(self.base / "stems b", names=("one", "two", "three"))
        s = self.base / "scan"
        self.assertEqual(self.hx("scan", a, "--out", s)[0], 0)
        before = (s / "findings.json").read_text(encoding="utf-8")
        code, out = self.hx("preflight", b, "--plan", s)
        self.assertEqual(code, 0, out)
        self.assertEqual((s / "findings.json").read_text(encoding="utf-8"), before)          # the earlier scan is untouched
        self.assertIn("different source", out)
        self.assertTrue((self.base / "scan (2)" / "preflight.json").exists())
        info = json.loads((s / "scan.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(info["set"]).name, "stems a")
        # the same source again goes into the same folder, as a re-scan does
        code, out = self.hx("preflight", a, "--plan", s)
        self.assertEqual(code, 0, out)
        self.assertTrue((s / "preflight.json").exists())


# ---------------------------------------------------------------- Live sets
class LiveSets(Base):
    def make(self):
        from tests.test_workflow import make_set
        d = self.base / "live"
        d.mkdir()
        als = make_set(d / "Song.als")
        t = np.arange(8 * SR) / SR
        y = 0.3 * np.sin(2 * np.pi * 220 * t) * ((t % 2) < 1) + np.random.default_rng(3).normal(0, 0.004, len(t))
        sf.write(str(d / "missing.wav"), y.astype("float32"), SR, subtype="PCM_24")
        return als

    def test_a_live_scan_measures_the_files_the_set_plays(self):
        als = self.make()
        code, out = self.hx("scan", als, "--only", "recordings", "--out", self.base / "s")
        self.assertEqual(code, 0, out)
        d = json.loads((self.base / "s" / "recordings.json").read_text(encoding="utf-8"))
        self.assertTrue(any(f["kind"] == "noise" and f["track"] == "missing.wav" for f in d["findings"]), d)

    def test_an_audio_only_set_does_not_report_a_failed_key_map(self):
        als = self.make()
        code, out = self.hx("scan", als, "--only", "vocals", "--key", "A minor", "--out", self.base / "s")
        self.assertEqual(code, 0, out)
        self.assertNotIn("did NOT run", out)
        notes = json.loads((self.base / "s" / "vocals.json").read_text(encoding="utf-8"))["notes"]
        self.assertFalse(any("confirm it" in n for n in notes), notes)       # the key was given
        code, out = self.hx("scan", als, "--only", "vocals", "--out", self.base / "s2")
        self.assertNotIn("did NOT run", out)
        notes = json.loads((self.base / "s2" / "vocals.json").read_text(encoding="utf-8"))["notes"]
        self.assertTrue(any("key map: not made" in n for n in notes), notes)


# ---------------------------------------------------------------- the low end: roles by name, and drums that are late
class LowEnd(unittest.TestCase):
    def test_a_track_called_drums_is_drums_whatever_it_sounds_like(self):
        from hypnomix.workflow import scan as SC
        role = {"Bass": {"label": "Bass"}, "Drums": {"label": "Bass"}, "7-Audio": {"label": "Kick"}, "Pad": {"label": "Pad"}}
        bass, drums = SC.low_end_tracks(["Bass", "Drums", "7-Audio", "Pad"], role)
        self.assertEqual(bass, ["Bass"])
        self.assertEqual(drums, ["Drums", "7-Audio"])        # a default name falls back to the sound-based label

    def test_a_late_drum_hit_does_not_drag_an_on_grid_bass(self):
        from hypnomix.session import timing as T
        spb = 0.5
        rng = np.random.default_rng(0)
        beats = [float(b) for b in range(64)]
        bass = [dict(beat=b + rng.normal(0, 0.002) / spb, strength=1.0, track="Bass") for b in beats]
        late = [rng.normal(0, 0.002) for _ in beats]
        late[50] = 0.055                                     # one drum hit 55 ms late
        drums = [dict(beat=b + s / spb, strength=1.0, track="Drums") for b, s in zip(beats, late)]
        _, issues = T.judge([("Bass", None, bass), ("Drums", None, drums)], spb, {}, False, (), {"Bass"}, {"Drums"})
        self.assertEqual([i["track"] for i in issues], ["Drums"])            # the drums are the late part; the bass is fine

    def test_a_bass_that_is_off_a_steady_drum_is_still_found(self):
        from hypnomix.session import timing as T
        spb = 0.5
        rng = np.random.default_rng(1)
        beats = [float(b) for b in range(64)]
        bass = [dict(beat=b + rng.normal(0, 0.002) / spb, strength=1.0, track="Bass") for b in beats]
        bass[50]["beat"] += 0.05 / spb                       # one bass hit 50 ms late
        drums = [dict(beat=b + rng.normal(0, 0.002) / spb, strength=1.0, track="Drums") for b in beats]
        _, issues = T.judge([("Bass", None, bass), ("Drums", None, drums)], spb, {}, False, (), {"Bass"}, {"Drums"})
        self.assertIn(("Bass", True), [(i["track"], i["lock"]) for i in issues])


# ---------------------------------------------------------------- Ardour
class ArdourFixes(Base):
    def session(self, name="Song"):
        from tests import test_ardour as TA
        d = self.base / name
        af = d / "interchange" / "Song" / "audiofiles"
        af.mkdir(parents=True)
        for n, y in (("lead", np.linspace(0, 1, 3 * TA.SR, endpoint=False)), ("comp", np.full(3 * TA.SR, 0.1)),
                     ("gtr-L", np.full(TA.SR, 0.2)), ("gtr-R", np.full(TA.SR, 0.6))):
            sf.write(str(af / f"{n}.wav"), y, TA.SR, subtype="FLOAT")
        text = TA.SESSION.replace('<Controllable name="mute" value="1"/>', '<Controllable name="mute" value="0"/>').replace(
            'scale-amplitude="1" fade-in-active="0" fade-out-active="0" type="audio" source-0="12" source-1="13"/>',
            'scale-amplitude="1" fade-in-active="1" fade-out-active="1" type="audio" source-0="12" source-1="13">'
            '<FadeIn default="yes"/><FadeOut default="yes"/></Region>')
        (d / "Song.ardour").write_text(text, encoding="utf-8")
        return d

    def test_ardours_own_default_fades_are_fades(self):
        d = self.session()
        code, out = self.hx("scan", d, "--only", "clips", "--out", self.base / "s")
        self.assertEqual(code, 0, out)
        found = json.loads((self.base / "s" / "clips.json").read_text(encoding="utf-8"))["findings"]
        self.assertFalse(any("gtr.1" in f["problem"] for f in found), found)       # default fades on both ends
        self.assertTrue(any("comp.1" in f["problem"] for f in found), found)       # a region with fades switched off still is

    def test_a_renamed_session_with_two_snapshots_is_read_from_the_newest(self):
        from hypnomix import project as PJ
        d = self.session()
        newer = d / "Song (fixed).ardour"
        shutil.copy(d / "Song.ardour", newer)
        os.utime(newer, (newer.stat().st_atime, newer.stat().st_mtime + 100))
        r = self.base / "Renamed"
        shutil.move(str(d), str(r))
        self.assertEqual(PJ.daw_of(r), "ardour")
        self.assertEqual(PJ.ardour_session(r).name, "Song (fixed).ardour")
        self.assertEqual([x.name for x in PJ.ardour_alternatives(r)], ["Song.ardour"])
        code, out = self.hx("scan", r, "--only", "files", "--out", self.base / "s")
        self.assertEqual(code, 0, out)
        self.assertNotIn("no audio files", out)
        self.assertIn("scanning the newest, Song (fixed).ardour", out)

    def test_since_on_an_ardour_session_says_an_ardour(self):
        d = self.session()
        code, out = self.hx("scan", d, "--since", self.base / "x")
        self.assertNotEqual(code, 0)
        self.assertIn("a HypnoMix DAW project", out)


# ---------------------------------------------------------------- the review page
class ReviewPage(Base):
    def findings(self, n):
        import random
        rnd = random.Random(1)
        return [dict(id=f"smooth-{i + 1}", n=i + 1, tool="smooth", kind="click", severity=rnd.choice(["low", "medium", "high"]),
                     track=f"T{i % 7}", where="1.1.1", problem=f"click of {rnd.uniform(1, 12):.1f} dB", fix="x",
                     applies="set", protected=(i % 11 == 0)) for i in range(n)]

    def scan_folder(self, n):
        sd = self.base / f"scan{n}"
        sd.mkdir()
        (sd / "findings.json").write_text(json.dumps(dict(set="/x/Song.als", notes=[], findings=self.findings(n))), encoding="utf-8")
        (sd / "scan.json").write_text(json.dumps(dict(set="/x/Song.als")), encoding="utf-8")
        return sd

    def test_the_runs_expand_to_exactly_the_like_map(self):
        from hypnomix.workflow import review as RV
        fs = self.findings(300) + [dict(id="mask-1", tool="masking", kind="masking", severity="low", track="A", where="",
                                        problem="no number here", fix="", applies="manual"),
                                   dict(id="mask-2", tool="masking", kind="masking", severity="low", track="B", where="",
                                        problem="no number here", fix="", applies="manual")]
        role_of = {f"T{i}": ("bass" if i < 3 else "keys") for i in range(7)}
        like = RV.like_map(fs, role_of)
        runs, order = RV.like_runs(like, fs, role_of)
        self.assertEqual(sorted(order), sorted(set(order)))
        for fid, ids in like.items():
            got = [order[j] for k in range(0, len(runs[fid]), 2) for j in range(runs[fid][k], runs[fid][k + 1] + 1)]
            self.assertEqual(sorted(got), sorted(ids), fid)

    def test_the_page_grows_with_the_findings_not_with_their_square(self):
        from hypnomix.workflow import review as RV
        small, big = self.scan_folder(250), self.scan_folder(1000)
        a = RV.build(small).stat().st_size
        b = RV.build(big).stat().st_size
        self.assertLess(b, 6 * a, (a, b))                    # 4x the findings: about 4x the size, was 15x

    def test_the_page_script_reads_the_ranges_like_the_lists(self):
        """The saved page script, run as it ships, lists the same findings like this one as the full map did."""
        import re
        from tests import _jscheck
        runner = _jscheck.need_runner(self)
        from hypnomix.workflow import review as RV
        fs = self.findings(120)
        role_of = {}
        like = RV.like_map(fs, role_of)
        runs, order = RV.like_runs(like, fs, role_of)
        fn = re.search(r"function ovLikeIds\(.*?\n}\n", RV.OVERSIGHT_JS, re.S).group(0)
        dec = {"smooth-3": {"decision": "skip"}}
        probe = fs[5]["id"]
        script = (fn + "var ov = " + json.dumps(dict(like_runs=runs, like_order=order)) + "; var dec = " + json.dumps(dec)
                  + "; print(JSON.stringify(ovLikeIds(ov, dec, " + json.dumps(probe) + ")));")
        f = self.base / "probe.js"
        f.write_text(script, encoding="utf-8")
        r = subprocess.run(runner + [str(f)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, "the page script did not run: " + r.stderr[:300])      # an engine that is here and fails is a failure, not a skip
        got = json.loads(r.stdout.strip().splitlines()[-1])
        want = [x for x in like[probe] if x != "smooth-3"]
        self.assertEqual(sorted(got), sorted(want))


# ---------------------------------------------------------------- automix never overwrites
class AutomixOutputs(Base):
    def test_a_second_run_gets_a_new_folder_and_an_out_that_holds_one_is_refused(self):
        stems = stems_folder(self.base / "stems")
        common = ["automix", stems, "--name", "Night", "--no-prep", "--no-master"]
        code, out = self.hx(*common)
        self.assertEqual(code, 0, out)
        first = self.base / "cwd" / "hypnomix-out" / "automix" / "Night" / "Night (automix).wav"
        self.assertTrue(first.exists())
        before = first.read_bytes()
        code, out = self.hx(*common)
        self.assertEqual(code, 0, out)
        self.assertEqual(first.read_bytes(), before)
        self.assertTrue((self.base / "cwd" / "hypnomix-out" / "automix" / "Night (2)" / "Night (automix).wav").exists())
        o = self.base / "o"
        self.assertEqual(self.hx(*common, "--out", o)[0], 0)
        code, out = self.hx(*common, "--out", o)
        self.assertEqual(code, 2, out)
        self.assertIn("nothing is overwritten", out)

    def test_an_out_folder_with_earlier_notes_is_refused_whatever_the_name(self):
        stems = stems_folder(self.base / "stems")
        o = self.base / "o"
        args = ["automix", stems, "--no-prep", "--no-master", "--out", o]
        self.assertEqual(self.hx(*args, "--name", "ND")[0], 0)
        notes = (o / "MIX NOTES.md").read_bytes()
        recipe = (o / "recipe.json").read_bytes()
        code, out = self.hx(*args, "--name", "ND2", "--target", "-10")
        self.assertEqual(code, 2, out)
        self.assertIn("nothing is overwritten", out)
        self.assertEqual((o / "MIX NOTES.md").read_bytes(), notes)
        self.assertEqual((o / "recipe.json").read_bytes(), recipe)
        self.assertFalse((o / "ND2 (automix).wav").exists())


# ---------------------------------------------------------------- the key map under --key
class KeyMapUnderKey(unittest.TestCase):
    def run_key_map(self, has_notes, **given):
        from types import SimpleNamespace
        from unittest import mock
        from hypnomix.workflow import scan as SC
        a = SimpleNamespace(ref=given.get("ref"), key=given.get("key"))
        calls = []
        with tempfile.TemporaryDirectory() as td, mock.patch.object(SC, "set_has_notes", return_value=has_notes), \
                mock.patch.object(SC, "hx", side_effect=lambda *x: (calls.append(x) or (1, "no key"))):
            od = Path(td)
            (od / "raw").mkdir()
            j, res = SC.key_map("set.als", od, a)
        return calls, res

    def test_a_set_with_midi_notes_still_gets_its_key_map_when_the_key_is_given(self):
        calls, _ = self.run_key_map(True, key="A minor")
        self.assertEqual(len(calls), 1)                  # fix --key sections reads raw/key.json from this
        self.assertEqual(calls[0][0], "key")

    def test_an_audio_only_set_with_a_given_key_makes_no_map_and_says_nothing(self):
        calls, res = self.run_key_map(False, key="A minor")
        self.assertEqual(calls, [])
        self.assertEqual(res["notes"], [])

    def test_an_audio_only_set_without_a_key_says_the_map_was_not_made(self):
        calls, res = self.run_key_map(False)
        self.assertEqual(calls, [])
        self.assertTrue(any("key map: not made" in n for n in res["notes"]), res)

    def test_a_reference_is_enough_to_make_the_map(self):
        calls, _ = self.run_key_map(False, ref="ref.wav", key="A minor")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
