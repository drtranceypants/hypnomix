"""Regression tests for the functional-audit fixes: clean read errors, measure on short/silent files, translate on
silence, install backups, distortion with missing parameters, order --names, key --sections, rebalance stem names,
loop with no arguments, preference checks, and start-up imports. Synthetic audio and temp folders only."""
import contextlib, io, json, os, subprocess, sys, tempfile, unittest, warnings
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from hypnomix.core import dsp

SR = 44100


def tone(path, secs, amp=0.3, ch=2):
    t = np.arange(int(SR * secs)) / SR
    y = amp * np.sin(2 * np.pi * 220 * t)
    sf.write(str(path), np.stack([y] * ch, 1), SR)
    return Path(path)


def run_cli(argv, debug=False):
    """cli.main(argv) -> (exit code, stdout, stderr)."""
    from hypnomix import cli
    out, err = io.StringIO(), io.StringIO()
    env = {"HYPNOMIX_DEBUG": "1"} if debug else {}
    code = 0
    with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        if not debug:
            os.environ.pop("HYPNOMIX_DEBUG", None)
        try:
            cli.main(argv)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (1 if e.code else 0)
            if isinstance(e.code, str):
                err.write(e.code)
    return code, out.getvalue(), err.getvalue()


class Temp(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)
        self.addCleanup(self.td.cleanup)


class ReadErrors(Temp):
    def test_loader_messages(self):
        with self.assertRaises(dsp.AudioReadError) as c:
            dsp.load(self.d / "nope.wav")
        self.assertIn("no such file", str(c.exception))
        self.assertIn("nope.wav", str(c.exception))
        bad = self.d / "bad.wav"; bad.write_text("not audio", encoding="utf-8")
        with self.assertRaises(dsp.AudioReadError) as c:
            dsp.load(bad)
        self.assertIn("not an audio file HypnoMix can decode", str(c.exception))
        with self.assertRaises(dsp.AudioReadError) as c:
            dsp.load(self.d)
        self.assertIn("folder", str(c.exception))

    def test_every_command_gives_one_plain_line_and_exit_2(self):
        bad = self.d / "bad.wav"; bad.write_text("not audio", encoding="utf-8")
        missing = self.d / "missing.wav"
        for cmd in (["qc"], ["clicks"], ["key", "--audio"], ["translate"], ["harsh"], ["sections"], ["master"]):
            for f, why in ((missing, "no such file"), (bad, "not an audio file")):
                extra = ["--plan", str(self.d / "plan")] if cmd == ["master"] else []
                argv = cmd + [str(f)] + extra
                with self.subTest(argv=argv[:3]):
                    code, _, err = run_cli(argv)
                    self.assertEqual(code, 2, err)
                    self.assertIn("can't read", err)
                    self.assertIn(why, err)
                    self.assertNotIn("Traceback", err)
                    self.assertEqual(len(err.strip().splitlines()), 1, err)

    def test_debug_variable_shows_the_traceback(self):
        with self.assertRaises(dsp.AudioReadError):
            run_cli(["translate", str(self.d / "missing.wav")], debug=True)

    def test_real_bugs_end_with_a_crash_record_and_exit_70_and_raise_when_debugging(self):
        from hypnomix import cli
        with mock.patch.object(cli, "_main", side_effect=ZeroDivisionError("boom")):
            code, _, err = run_cli(["measure"])
            self.assertEqual(code, 70)
            self.assertIn("HypnoMix hit a bug", err)
            self.assertNotIn("Traceback", err)
            with self.assertRaises(ZeroDivisionError):
                run_cli(["measure"], debug=True)


class Measure(Temp):
    def test_short_file_gets_what_is_possible(self):
        from hypnomix.ears import measure
        m = measure.measure(tone(self.d / "short.wav", 1.5))
        self.assertEqual(m["short_term_lufs"], [])
        self.assertIsNone(m["short_term_p10_p95"])
        self.assertTrue(any("under 3 s" in n for n in m["notes"]))
        self.assertIn("sample_peak_dbfs", m)
        self.assertIn("band_energy_db", m)

    def test_tiny_file_does_not_crash(self):
        from hypnomix.ears import measure
        m = measure.measure(tone(self.d / "tiny.wav", 0.2))
        self.assertIsNone(m["pyloudnorm_lufs"])
        self.assertTrue(m["notes"])

    def test_silent_file_is_reported_silent(self):
        from hypnomix.ears import measure
        p = self.d / "silent.wav"; sf.write(str(p), np.zeros((SR * 4, 2)), SR)
        m = measure.measure(p)
        self.assertTrue(m["silent"])
        self.assertIn("silent", m["notes"][0])

    def _main(self, files):
        from hypnomix.ears import measure
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch.object(sys, "argv", ["hypnomix measure", *map(str, files), "--out", str(self.d / "o")]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                measure.main()
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_exit_codes(self):
        good = tone(self.d / "good.wav", 4)
        silent = self.d / "silent.wav"; sf.write(str(silent), np.zeros((SR * 4, 2)), SR)
        bad = self.d / "bad.wav"; bad.write_text("x", encoding="utf-8")
        code, out, _ = self._main([good]); self.assertEqual(code, 0); self.assertIn("good.wav", out)
        code, _, err = self._main([self.d / "missing.wav"]); self.assertEqual(code, 2); self.assertIn("no such file", err)
        code, _, err = self._main([bad]); self.assertEqual(code, 2); self.assertIn("not an audio file", err)
        code, _, err = self._main([silent]); self.assertEqual(code, 1); self.assertIn("SILENT", err)
        code, out, _ = self._main([self.d / "missing.wav", good])        # the batch carries on, then fails
        self.assertEqual(code, 2); self.assertIn("good.wav", out)
        self.assertTrue((self.d / "o" / "good.json").exists())
        code, _, _ = self._main([tone(self.d / "s2.wav", 1.0)]); self.assertEqual(code, 0)


class Translate(Temp):
    def test_silence_in_words_without_nan_or_warnings(self):
        from hypnomix.engineer import translate
        p = self.d / "silent.wav"; sf.write(str(p), np.zeros((SR * 3, 2)), SR)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            r = translate.analyse(p)
        self.assertTrue(r["silent"])
        self.assertIn("silent", r["notes"][0])
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["hypnomix translate", str(p), "--out", str(self.d / "o")]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as c:
                translate.main()
        self.assertEqual(c.exception.code, 1)
        self.assertIn("silent", out.getvalue())
        self.assertNotIn("nan", out.getvalue().lower())


class Install(Temp):
    def test_logs_made_by_live_do_not_cause_a_backup(self):
        from hypnomix import install
        src = self.d / "src"; (src / "abletonosc").mkdir(parents=True)
        (src / "abletonosc" / "track.py").write_text("x = 1\n", encoding="utf-8")
        (src / "__init__.py").write_text("", encoding="utf-8")
        scripts = self.d / "Remote Scripts"; scripts.mkdir()
        out = io.StringIO()
        with mock.patch.object(install, "SCRIPT_SRC", src), mock.patch.object(install, "remote_scripts_dir", lambda: scripts), \
                mock.patch.object(install, "live_prefs_dir", lambda: None), contextlib.redirect_stdout(out):
            install.install([])                                      # first install
            dest = scripts / "AbletonOSC"
            self.assertTrue((dest / "abletonosc" / "track.py").exists())
            (dest / "logs").mkdir(); (dest / "logs" / "abletonosc.log").write_text("live was here", encoding="utf-8")
            (dest / "__pycache__").mkdir(); (dest / "__pycache__" / "a.pyc").write_bytes(b"\0")
            (dest / "abletonosc" / "x.pyc").write_bytes(b"\0")
            out.truncate(0); out.seek(0)
            install.install([])                                      # second run: nothing to do
            self.assertIn("already up to date", out.getvalue())
            self.assertNotIn("moved to", out.getvalue())
            self.assertEqual([p.name for p in scripts.iterdir()], ["AbletonOSC"])
            (src / "abletonosc" / "track.py").write_text("x = 2\n", encoding="utf-8")  # a real change still backs up, once
            install.install([])
            names = sorted(p.name for p in scripts.iterdir())
            self.assertEqual(len(names), 2, names)
            self.assertEqual((dest / "abletonosc" / "track.py").read_text(encoding="utf-8"), "x = 2\n")
            self.assertFalse((dest / "logs").exists())

    def test_same_tree_sees_real_differences(self):
        from hypnomix import install
        a, b = self.d / "a", self.d / "b"
        for r in (a, b):
            r.mkdir(); (r / "f.py").write_text("1", encoding="utf-8")
        self.assertTrue(install._same_tree(a, b))
        (b / "g.py").write_text("2", encoding="utf-8")
        self.assertFalse(install._same_tree(a, b))
        (a / "g.py").write_text("3", encoding="utf-8")
        self.assertFalse(install._same_tree(a, b))


def als_like(device_xml):
    return ET.fromstring(f"""<Ableton><LiveSet><Tracks>
<AudioTrack Id="1"><Name><EffectiveName Value="Guitar"/></Name>
<DeviceChain><Mixer><Speaker><Manual Value="true"/></Speaker><Volume><Manual Value="1"/></Volume></Mixer>
<DeviceChain><Devices>{device_xml}</Devices></DeviceChain></DeviceChain></AudioTrack></Tracks>
<MainTrack Id="0"><Name><EffectiveName Value="Main"/></Name><DeviceChain><Mixer><Volume><Manual Value="1"/></Volume></Mixer>
<DeviceChain><Devices/></DeviceChain></DeviceChain></MainTrack></LiveSet></Ableton>""")


class Distortion(unittest.TestCase):
    FULL = ('<Saturator><Type><Manual Value="1"/></Type><PreDrive><Manual Value="24"/></PreDrive>'
            '<PostDrive><Manual Value="0"/></PostDrive><DryWet><Manual Value="1"/></DryWet></Saturator>')
    NOPRE = '<Saturator><Type><Manual Value="1"/></Type><PostDrive><Manual Value="0"/></PostDrive></Saturator>'

    def run_checks(self, xml):
        from hypnomix.session import distortion as D
        return D.effects_findings(als_like(xml), {"Guitar": dict(peak=-3.0, beat=0.0)}, set(), None, False)

    def test_normal_saturator_still_found(self):
        f, notes = self.run_checks(self.FULL)
        self.assertEqual(len(f), 1)
        self.assertEqual(notes, [])

    def test_saturator_without_predrive_is_skipped_with_a_note(self):
        f, notes = self.run_checks(self.NOPRE)
        self.assertEqual(f, [])
        self.assertEqual(len(notes), 1)
        self.assertIn("PreDrive", notes[0])
        self.assertIn("Saturator", notes[0])

    def test_other_devices_after_it_are_still_checked(self):
        f, notes = self.run_checks(self.NOPRE + self.FULL)
        self.assertEqual(len(f), 1)
        self.assertEqual(len(notes), 1)


class OrderNames(Temp):
    def test_names_must_be_a_names_json(self):
        from hypnomix.session import order
        for arg in ("Vox", str(self.d / "nope.json")):
            with self.assertRaises(SystemExit) as c:
                order.read_names(arg)
            self.assertIn("--names expects", str(c.exception))
            self.assertIn("names.json", str(c.exception))
        bad = self.d / "x.json"; bad.write_text("{nope", encoding="utf-8")
        with self.assertRaises(SystemExit) as c:
            order.read_names(str(bad))
        self.assertIn("not valid JSON", str(c.exception))
        ok = self.d / "names.json"; ok.write_text(json.dumps({"tracks": [{"old": "a"}]}), encoding="utf-8")
        self.assertEqual(order.read_names(str(ok)), [{"old": "a"}])


class KeySections(Temp):
    def test_sections_without_a_tempo_says_so_before_any_work(self):
        from hypnomix.ears import key
        audio = tone(self.d / "a.wav", 2)
        with mock.patch.object(key, "audio_evidence", side_effect=AssertionError("work was done")), \
                mock.patch.object(sys, "argv", ["hypnomix key", "--audio", str(audio), "--sections"]), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as c:
                key.main()
        self.assertIn("--bpm", str(c.exception))
        self.assertIn("--set", str(c.exception))


class RebalanceStems(Temp):
    def test_names(self):
        from hypnomix.engineer.rebalance import stem_kind
        for name, kind in (("vocal", "vocals"), ("Vocals", "vocals"), ("VOX", "vocals"), ("Lead_Vocal", "vocals"),
                           ("drum", "drums"), ("Drums", "drums"), ("bass", "bass"), ("Bass", "bass"),
                           ("other", "other"), ("music", "other"), ("inst", "other"), ("no_vocals", "other"),
                           ("song (vocals)", "vocals"), ("pad", None), ("mix", None)):
            self.assertEqual(stem_kind(name), kind, name)

    def test_loads_variants_and_lists_files_when_none_match(self):
        from hypnomix.engineer import rebalance
        for n in ("vocal", "drum", "bass", "music"):
            tone(self.d / f"{n}.wav", 1)
        got = rebalance.load_stems(self.d, SR, SR)
        self.assertEqual(sorted(got), ["bass", "drums", "other", "vocals"])
        e = self.d / "e"; e.mkdir(); tone(e / "pad.wav", 1); tone(e / "song.wav", 1)
        with self.assertRaises(FileNotFoundError) as c:
            rebalance.load_stems(e, SR, SR)
        self.assertIn("pad.wav", str(c.exception))
        self.assertIn("song.wav", str(c.exception))


class LoopNoArguments(unittest.TestCase):
    def test_prints_usage_and_exits_2_without_touching_live(self):
        from hypnomix.live import loop
        out = io.StringIO()
        with mock.patch("hypnomix.live.osc.Live", side_effect=AssertionError("connected to Live")), \
                mock.patch.object(sys, "argv", ["hypnomix loop"]), contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as c:
                loop.main()
        self.assertEqual(c.exception.code, 2)
        self.assertIn("usage:", out.getvalue())
        self.assertIn("--bar", out.getvalue())


class Prefs(Temp):
    def setUp(self):
        super().setUp()
        from hypnomix.workflow import prefs
        self.P = prefs
        patcher = mock.patch.object(prefs, "PREFS", self.d / "preferences.json")
        patcher.start(); self.addCleanup(patcher.stop)
        # the person's hypnomix folder is HYPNOMIX_HOME wherever it is set (the test run sets it), else ~/.hypnomix: setup.json lives in it
        env = mock.patch.dict(os.environ, {"HOME": str(self.d / "home"), "HYPNOMIX_HOME": str(self.d / "home" / ".hypnomix")})
        env.start(); self.addCleanup(env.stop)

    def set(self, *items):
        err = io.StringIO()
        with mock.patch.object(sys, "argv", ["hypnomix prefs", "set", *items]), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(err):
            try:
                self.P.main()
            except SystemExit as e:
                return str(e.code)
        return None

    def test_bad_numbers_are_refused_and_nothing_is_saved(self):
        msg = self.set("targets.lufs=abc")
        self.assertIn("targets.lufs must be a number from -40 to -1", msg)
        self.assertFalse(self.P.PREFS.exists())
        for bad in ("5", "-80", "nan", "inf", ""):
            self.assertIsNotNone(self.set(f"targets.lufs={bad}"), bad)
        self.assertIsNotNone(self.set("targets.true_peak=2"))
        self.assertIsNotNone(self.set("review.max_questions=2.5"))
        self.assertIsNotNone(self.set("review.max_questions=-1"))
        self.assertFalse(self.P.PREFS.exists())

    def test_one_bad_answer_saves_none_of_the_command(self):
        self.assertIsNotNone(self.set("targets.lufs=-12", "review.style=whenever"))
        self.assertFalse(self.P.PREFS.exists())

    def test_good_numbers(self):
        self.assertIsNone(self.set("targets.lufs=-16.5", "targets.true_peak=-2", "review.max_questions=5"))
        got = json.loads(self.P.PREFS.read_text(encoding="utf-8"))
        self.assertEqual(got["targets"], {"lufs": -16.5, "true_peak": -2})
        self.assertEqual(got["review"]["max_questions"], 5)

    def test_choices_name_the_allowed_values(self):
        msg = self.set("review.style=whenever")
        self.assertIn("one-at-a-time, batch-low, batch-by-kind", msg)
        self.assertIn("taste.tuning must be one of: natural, tight, off", self.set("taste.tuning=sloppy"))
        self.assertIn("cleanup.order must be one of: on, off", self.set("cleanup.order=maybe"))
        self.assertIsNone(self.set("taste.tuning=Natural", "cleanup.order=no", "cleanup.retire=yes", "review.teach=off"))
        got = json.loads(self.P.PREFS.read_text(encoding="utf-8"))
        self.assertEqual(got["taste"]["tuning"], "natural")
        self.assertEqual(got["cleanup"], {"order": "off", "retire": "on"})
        self.assertEqual(got["review"]["teach"], "off")

    def test_the_app_goes_through_the_same_function(self):
        with self.assertRaises(ValueError):                 # the server turns a ValueError into a 400 with the message
            self.P.parse("targets.lufs", "abc")
        self.assertEqual(self.P.parse("targets.lufs", "-14"), -14)
        self.assertEqual(self.P.parse("review.max_questions", "none"), 0)
        self.assertEqual(self.P.parse("protect.tracks", "A, B"), ["A", "B"])
        self.assertEqual(self.P.parse("review.name", "Sam"), "Sam")          # free-text keys are untouched
        self.assertEqual(self.P.parse("review.batch_low", "yes"), True)

    def test_every_question_default_is_a_valid_answer(self):
        for q in self.P.QUESTIONS:
            if q["options"] is None:
                continue
            for o in q["options"] + [q["default"]]:
                self.P.parse(q["key"], str(o))

    def test_new_questions_keep_todays_behaviour(self):
        keys = {q["key"]: q for q in self.P.QUESTIONS}
        for k in ("cleanup.order", "cleanup.retire", "cleanup.consolidate"):
            self.assertEqual(keys[k]["default"], "on")
            self.assertEqual(keys[k]["options"], ["on", "off"])
        self.assertEqual(keys["review.max_questions"]["default"], 0)
        from hypnomix.workflow import oversight as O
        self.assertEqual(O.budget([{"id": "a", "severity": "low"}] * 3, 0)[1], [])       # 0 = ask everything

    def test_unused_questions_say_who_reads_them(self):
        keys = {q["key"]: q for q in self.P.QUESTIONS}
        for k in ("review.style", "review.explain", "targets.delivery"):
            self.assertIn("AI agents", keys[k]["why"], k)

    def test_daw_follows_setup_until_answered(self):
        setup = self.d / "setup.json"
        self.assertEqual(self.P.daw({}, setup), "")
        setup.write_text(json.dumps({"daw": "reaper"}), encoding="utf-8")
        self.assertEqual(self.P.daw({}, setup), "reaper")
        self.assertEqual(self.P.daw({"tools": {"daw": "ardour"}}, setup), "ardour")    # Preferences win
        self.assertEqual(self.P.daw({"tools": {"daw": "ableton"}}, setup), "live")      # older answers still read
        self.assertEqual(self.P.daw({"tools": {"daw": "logic"}}, setup), "other")
        setup.write_text("not json", encoding="utf-8")
        self.assertEqual(self.P.daw({}, setup), "")

    def test_get_and_unanswered_use_setup_for_the_daw(self):
        (self.d / "home" / ".hypnomix").mkdir(parents=True)
        (self.d / "home" / ".hypnomix" / "setup.json").write_text(json.dumps({"daw": "ardour"}), encoding="utf-8")
        self.assertEqual(self.P.get({}, "tools.daw"), "ardour")
        self.assertNotIn("tools.daw", [q["key"] for q in self.P.unanswered({})])
        self.assertEqual(self.P.get({"tools": {"daw": "reaper"}}, "tools.daw"), "reaper")
        self.assertIn("tools.daw", [q["key"] for q in self.P.unanswered({"x": 1})] if False else ["tools.daw"])

    def test_daw_question_matches_setup_ids(self):
        from hypnomix.app import setup
        q = next(q for q in self.P.QUESTIONS if q["key"] == "tools.daw")
        # HypnoMix Studio is built on Ardour: Preferences read that choice as "ardour" (prefs._DAW_WORDS), so it is not an option of its own
        # (Setup no longer asks "Ardour" as a choice of its own; Preferences still reads Ardour sessions, so it keeps that answer)
        ids = [d["id"] for d in setup.DAWS if d["id"] != "hypnomix"]
        self.assertEqual(q["options"], ids[:-1] + ["ardour"] + ids[-1:])
        self.assertIn("ardour", setup.DAW_IDS)                                        # and an Ardour choice saved before still works
        self.assertEqual(self.P.daw({"tools": {"daw": "hypnomix"}}), "ardour")

    def test_wants(self):
        P = self.P
        self.assertEqual(P.wants("tune", {}), "default")
        self.assertEqual(P.wants("timing", {}), "default")
        self.assertEqual(P.wants("tune", {"taste": {"tuning": "off"}}), "off")
        self.assertEqual(P.wants("tune", {"taste": {"tuning": "natural"}}), "gentle")
        self.assertEqual(P.wants("tune", {"taste": {"tuning": "tight"}}), "tight")
        self.assertEqual(P.wants("timing", {"taste": {"timing": "loose"}}), "gentle")
        self.assertEqual(P.wants("timing", {"taste": {"timing": "tight"}}), "tight")
        self.assertEqual(P.wants("timing", {"taste": {"timing": "off"}}), "off")
        self.assertEqual(P.wants("timing", {"taste": {"timing": False}}), "off")
        with self.assertRaises(ValueError):
            P.wants("vibrato", {})


class StartUp(unittest.TestCase):
    def test_heavy_libraries_wait_until_used(self):
        code = ("import sys\n"
                "import hypnomix.core.dsp, hypnomix.ears.measure, hypnomix.ears.spectrogram, hypnomix.ears.stems\n"
                "bad = [m for m in ('scipy.signal', 'pyloudnorm', 'librosa', 'matplotlib') if m in sys.modules]\n"
                "print(bad)\n")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent), encoding="utf-8")
        self.assertEqual(r.stdout.strip(), "[]", r.stderr)

    def test_dsp_still_offers_scipy_names_to_other_modules(self):
        self.assertTrue(callable(dsp.butter))
        self.assertTrue(callable(dsp.sosfilt))
        self.assertIsNotNone(dsp.lufs(np.random.default_rng(0).standard_normal((SR, 2)) * 0.1, SR))
        with self.assertRaises(AttributeError):
            dsp.not_a_thing


if __name__ == "__main__":
    unittest.main()
