"""Bugs fixed in the command-line arguments and messages: one plain sentence instead of a hang, a traceback or a report
about a nonsense value; new files instead of overwriting; the words fit the person's DAW. Synthetic inputs only, built
in temp folders; every subprocess gets its own HOME and hypnomix folders."""
import argparse, contextlib, io, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from hypnomix.core import args as A

ROOT = Path(__file__).resolve().parents[1]


def env_for(base):
    base = Path(base)
    e = dict(os.environ)
    for k, sub in (("HOME", "home"), ("HYPNOMIX_HOME", "hx"), ("HYPNOMIX_APP_HOME", "app"), ("HYPNOMIX_USER_HOME", "home")):
        (base / sub).mkdir(exist_ok=True)
        e[k] = str(base / sub)
    e["HYPNOMIX_DISKCARE"] = "off"
    e["PYTHONPATH"] = str(ROOT) + os.pathsep + e.get("PYTHONPATH", "")
    e.pop("HYPNOMIX_OUT", None)
    e.pop("HYPNOMIX_DEBUG", None)
    return e


def hx(base, *args, cwd=None, timeout=240, extra_env=None):
    """Run `hypnomix ...` in a subprocess with isolated folders; (exit code, stdout + stderr)."""
    env = env_for(base)
    env.update(extra_env or {})
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True, env=env,
                       cwd=str(cwd or base), timeout=timeout, encoding="utf-8")
    return r.returncode, r.stdout + r.stderr


def quick(*args):
    """Run a command in this process (for refusals that happen before any work); (exit code, text)."""
    from hypnomix import cli
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with mock.patch.object(sys, "argv", ["hypnomix"] + [str(a) for a in args]), contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        try:
            cli.main([str(a) for a in args])
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            if isinstance(e.code, str):
                err.write(e.code)
    return code, out.getvalue() + err.getvalue()


def song(path, seconds=5.0, sr=44100, stereo=True, level=0.2):
    t = np.arange(int(seconds * sr)) / sr
    y = level * (np.sin(2 * np.pi * 220 * t) + 0.5 * np.sin(2 * np.pi * 660 * t)) * (0.6 + 0.4 * np.sin(2 * np.pi * 1.5 * t) ** 2)
    y = np.stack([y, y * 0.9], axis=1) if stereo else y
    sf.write(str(path), y, sr, subtype="PCM_24")
    return Path(path)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()


# ------------------------------------------------------------------ the shared checks
class SharedChecks(unittest.TestCase):
    def test_number_refuses_text_nan_inf_and_out_of_range(self):
        f = A.number(20, 400)
        self.assertEqual(f("120"), 120.0)
        for bad in ("nan", "inf", "-inf", "abc", "", "19.9", "401", "1e9", "-90"):
            with self.assertRaises(argparse.ArgumentTypeError, msg=bad):
                f(bad)
        self.assertEqual(A.whole(1, 32)("4"), 4)
        for bad in ("0", "33", "2.5", "x", "-4"):
            with self.assertRaises(argparse.ArgumentTypeError, msg=bad):
                A.whole(1, 32)(bad)
        with self.assertRaises(argparse.ArgumentTypeError):
            A.number(above=0)("0")
        self.assertEqual(A.number(above=0)("0.1"), 0.1)

    def test_the_message_says_what_is_expected(self):
        try:
            A.number(20, 400)("nan")
        except argparse.ArgumentTypeError as e:
            self.assertIn("from 20 to 400", str(e))

    def test_check_for_a_value_inside_another_option(self):
        self.assertEqual(A.check("-1.5", "--offset bass", -60, 60), -1.5)
        with self.assertRaises(SystemExit) as cm:
            A.check("abc", "--offset bass", -60, 60)
        self.assertIn("--offset bass", str(cm.exception))


# ------------------------------------------------------------------ handoff
def scan_folder(d, findings, decisions):
    sd = Path(d) / "scan"
    sd.mkdir()
    (sd / "findings.json").write_text(json.dumps(dict(set=str(d), findings=findings)), encoding="utf-8")
    (sd / "scan.json").write_text(json.dumps(dict(set=str(d), mode="folder")), encoding="utf-8")
    (sd / "decisions.json").write_text(json.dumps(decisions), encoding="utf-8")
    return sd


def F(i, track, where, problem="problem", **kw):
    return dict(id=f"t-{i}", tool="t", kind="level", severity="low", track=track, where=where, applies="manual",
                problem=problem, fix="lower it a little", **kw)


class Handoff(Tmp):
    def test_negative_beats_per_bar_and_odd_tempos_are_refused_at_once(self):
        sd = scan_folder(self.d, [F(1, "Vocals", "12.1.00"), F(2, "Bass", "12.1.00")],
                         {"t-1": dict(decision="approve"), "t-2": dict(decision="approve")})
        for args, word in ((["--bpm", "120", "--beats-per-bar", "-4"], "beats-per-bar"), (["--bpm", "120", "--beats-per-bar", "0"], "beats-per-bar"),
                           (["--bpm", "nan"], "bpm"), (["--bpm", "inf"], "bpm"), (["--bpm", "-90"], "bpm"), (["--bpm", "1e9"], "bpm")):
            code, text = hx(self.d, "handoff", sd, *args, timeout=60)         # it used to loop forever, or end in a traceback
            self.assertEqual(code, 2, (args, text))
            self.assertIn(word, text)
            self.assertNotIn("Traceback", text)
        self.assertFalse((sd / "handoff").exists())                            # nothing was written by the refused runs

    def test_the_midi_number_writer_always_ends(self):
        from hypnomix.workflow import handoff as H
        self.assertEqual(H._vlq(-1), b"\x00")
        self.assertEqual(H._vlq(0), b"\x00")
        self.assertEqual(H._vlq(128), b"\x81\x00")
        rows = [dict(item=dict(f=F(1, "x", "1:00.0")), t=-1.0)]
        self.assertTrue(H.midi_bytes(rows, ["1. x"], 120.0).startswith(b"MThd"))

    def test_a_time_the_finding_states_in_its_problem_is_its_position(self):
        from hypnomix.workflow import handoff as H
        f = F(1, "Bass.wav", None, problem="57 clipped peaks (-0.1 dBFS; first at 0:15.0)")
        self.assertEqual(H.finding_positions(f, 96.0, 4), [15.0])
        self.assertEqual(H.finding_positions(F(2, "Bass.wav", "1:05.0", problem="first at 0:15.0"), None, 4), [65.0])   # where wins
        self.assertEqual(H.finding_positions(F(3, "Bass.wav", None, problem="whole take is quiet"), 96.0, 4), [])
        sd = scan_folder(self.d, [f], {"t-1": dict(decision="approve")})
        code, text = hx(self.d, "handoff", sd, "--bpm", "96", "--daw", "reaper")
        self.assertEqual(code, 0, text)
        self.assertIn("1 spot(s) with a position", text)
        md = (sd / "handoff" / "HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("bar 7.1 · 0:15.0", md)
        self.assertNotIn("no position", md)
        self.assertTrue((sd / "handoff" / "markers.csv").exists())

    def test_the_help_says_when_the_marker_files_are_written(self):
        from hypnomix.workflow import handoff as H
        doc = " ".join(H.__doc__.split())
        self.assertNotIn("are written for every scan, too.", doc)
        self.assertIn("whenever at least one item has a position", doc)
        sd = scan_folder(self.d, [F(1, "Vocals", "whole take")], {"t-1": dict(decision="approve")})
        code, text = hx(self.d, "handoff", sd)
        self.assertEqual(code, 0, text)
        self.assertIn("0 spot(s) with a position", text)
        self.assertEqual(sorted(p.name for p in (sd / "handoff").iterdir()), ["HANDOFF.md"])     # only the checklist, as the help says


# ------------------------------------------------------------------ colour --tweak
class ColourTweaks(Tmp):
    IDS = ["colour-1", "colour-2"]

    def test_a_good_tweak_is_read(self):
        from hypnomix.session import colour as C
        self.assertEqual(C.parse_tweaks(["colour-1:amount=0.3", "colour-2: amount=1"], self.IDS),
                         {"colour-1": {"amount": 0.3}, "colour-2": {"amount": 1.0}})
        self.assertEqual(C.parse_tweaks(["colour-1:make it a bit less"], self.IDS), {})      # the person's own note is left alone
        self.assertEqual(C.parse_tweaks(None, self.IDS), {})

    def test_a_wrong_tweak_ends_the_run_with_a_sentence(self):
        from hypnomix.session import colour as C
        for bad in ("garbage", "colour-1:amount=abc", "colour-9:amount=0.2", "colour-1:amount=9", "colour-1:amount=-0.1",
                    "colour-1:amount=nan"):
            with self.assertRaises(SystemExit, msg=bad) as cm:
                C.parse_tweaks([bad], self.IDS)
            self.assertIn(repr(bad), str(cm.exception))

    def test_a_run_with_a_wrong_tweak_writes_no_set(self):
        from tests.test_colour import make_song, make_library
        song_dir = self.d / "song"
        song_dir.mkdir()
        als = make_song(song_dir)
        lib = make_library(self.d)
        for tweak in ("garbage", "colour-1:amount=abc", "colour-9:amount=0.2", "colour-1:amount=9"):
            out = self.d / "N.als"
            code, text = hx(self.d, "colour", als, "--library", lib, "--block", "8", "--no-clips", "--part", "Pad", "--family", "grit", "--max", "1", "--out", self.d / "report",
                            "--apply", out, "--ids", "colour-1", "--tweak", tweak)
            self.assertEqual(code, 1, (tweak, text))
            self.assertIn("--tweak", text)
            self.assertNotIn("wrote", text)
            self.assertFalse(out.exists(), tweak)
            self.assertNotIn("Traceback", text)


# ------------------------------------------------------------------ prefs
class Prefs(Tmp):
    def test_a_misspelt_key_is_refused_and_nothing_is_saved(self):
        for item, hint in (("targets.truepeak=zzz", "targets.true_peak"), ("targets.lufz=-14", "targets.lufs"),
                           ("review.whatever=5", "review."), ("tools.nothing=1", "tools."), ("bogus.key=1", "unknown key")):
            code, text = hx(self.d, "prefs", "set", item)
            self.assertEqual(code, 1, (item, text))
            self.assertIn("not saved", text)
            self.assertIn(hint, text)
        self.assertFalse((self.d / "hx" / "preferences.json").exists())

    def test_good_keys_and_the_free_form_ones_are_kept(self):
        code, text = hx(self.d, "prefs", "set", "targets.true_peak=-2", "tools.plugins=Alpha Verb,Gamma Comp", "review.name=Sam",
                        "taste.profile=off", "protect.notes=a long tail", "cleanup.order=off", "review.teach=off")
        self.assertEqual(code, 0, text)
        got = json.loads((self.d / "hx" / "preferences.json").read_text(encoding="utf-8"))
        self.assertEqual(got["targets"]["true_peak"], -2)
        self.assertEqual(got["tools"]["plugins"], ["Alpha Verb", "Gamma Comp"])
        self.assertEqual(got["review"]["name"], "Sam")
        self.assertNotIn("truepeak", got["targets"])

    def test_one_bad_key_in_a_command_saves_none_of_them(self):
        code, text = hx(self.d, "prefs", "set", "targets.lufs=-16", "targets.lufz=-14")
        self.assertEqual(code, 1, text)
        self.assertFalse((self.d / "hx" / "preferences.json").exists())

    def test_the_help_example_is_a_real_key(self):
        from hypnomix.workflow import prefs as P
        for key in ("targets.lufs", "review.style", "tools.plugins_found", "review.name", "taste.profile"):
            self.assertIn(key, P.known_keys())
        self.assertIn("review.style=batch-low", P.__doc__)
        self.assertNotIn("review.batch_low", P.__doc__)


# ------------------------------------------------------------------ versions
class Versions(Tmp):
    def stems(self, seconds=8.0):
        d = self.d / "dsong"
        d.mkdir()
        song(d / "Lead 1.wav", seconds)
        song(d / "Bass.wav", seconds, level=0.1)
        return d

    def test_a_cut_that_removes_the_whole_song_is_refused_in_a_sentence(self):
        from hypnomix.engineer import versions as V
        with self.assertRaises(V.VersionsError) as cm:
            V.plan_cuts([(0.0, 40.0)], 40.0)
        self.assertIn("whole song", str(cm.exception))
        with self.assertRaises(V.VersionsError):
            V.plan_cuts([(0.0, None)], 40.0)                                  # "0:00-" means to the end
        V.plan_cuts([(0.0, 8.0)], 40.0)                                       # the first bar only: fine

    def test_the_command_ends_without_a_traceback(self):
        d = self.stems()
        for cut in ("0:00-0:08", "0:00-"):
            code, text = hx(self.d, "versions", "--stems", d, "--vocals", "Lead*", "--cut", cut, "--out", self.d / "o")
            self.assertEqual(code, 1, (cut, text))
            self.assertIn("remove the whole song", text)
            self.assertNotIn("Traceback", text)
        self.assertFalse((self.d / "o").exists())

    def test_numbers_are_checked_before_any_work(self):
        d = self.stems()
        for args in (["--bpm", "-90"], ["--bpm", "nan"], ["--fade", "-5"], ["--tv", "inf"], ["--target", "5"]):
            code, text = quick("versions", "--stems", d, "--vocals", "Lead*", "--cut", "0:02-0:04", *args)
            self.assertEqual(code, 2, (args, text))
            self.assertNotIn("Traceback", text)

    def test_a_missing_folder_is_not_called_a_folder_of_stems(self):
        code, text = hx(self.d, "versions", "--stems", self.d / "Song stems X", "--vocals", "Lead*", "--check")
        self.assertEqual(code, 1, text)
        self.assertIn("no such folder", text)
        self.assertNotIn("is not a folder of stems", text)
        f = song(self.d / "a.wav")
        code, text = hx(self.d, "versions", "--stems", f, "--vocals", "Lead*", "--check")
        self.assertIn("is a file, not a folder of stems", text)
        code, text = hx(self.d, "balance", self.d / "nope")
        self.assertIn("no such folder", text)


# ------------------------------------------------------------------ numbers
class NumericOptions(Tmp):
    def test_each_command_refuses_a_nonsense_number_at_once(self):
        wav = song(self.d / "f.wav", 1.0)
        folder = self.d / "stems"
        folder.mkdir()
        cases = [
            ("sections", wav, "--bpm", "1e9"), ("sections", wav, "--bpm", "nan"), ("sections", wav, "--bpm", "-90"),
            ("balance", folder, "--max-move", "-3"), ("balance", folder, "--min-move", "-1"),
            ("balance", folder, "--vocal-over-band", "nan"),
            ("album", wav, wav, "--gap", "-3"), ("album", wav, wav, "--tolerance", "-3"), ("album", wav, wav, "--ceiling", "5"),
            ("album", wav, wav, "--target", "nan"), ("album", wav, wav, "--tilt-amount", "500"),
            ("masking", folder, "--top", "-2"), ("masking", folder, "--top", "0"),
            ("fix", folder, "--list", "--top", "-1"), ("fix", folder, "--list", "--offset", "-1"),
            ("plugins", "--timeout", "0"),
            ("vocallevel", self.d / "x.als", "--heard", folder, "--jump", "-1"),
        ]
        for case in cases:
            code, text = quick(*case)
            self.assertEqual(code, 2, (case, text))
            self.assertNotIn("Traceback", text)
        self.assertFalse((self.d / "hypnomix-out").exists())

    def test_a_bad_offset_is_a_sentence(self):
        from hypnomix.engineer import balance as B
        self.assertEqual(B.parse_offsets("bass=-1.5,hats=-2"), {"bass": -1.5, "hats": -2.0})
        for bad in ("bass=abc", "bass=nan", "bass=900"):
            with self.assertRaises(SystemExit, msg=bad) as cm:
                B.parse_offsets(bad)
            self.assertIn("--offset bass", str(cm.exception))

    def test_a_bad_demo_seed_leaves_no_folder_behind(self):
        out = self.d / "o"
        for seed in ("-5", "abc", "1e3", "99999999999"):
            code, text = quick("demo", "--out", out, "--seed", seed)
            self.assertEqual(code, 2, (seed, text))
            self.assertNotIn("Traceback", text)
        self.assertFalse(out.exists())

    def test_the_numbers_that_were_fine_still_are(self):
        code, text = quick("demo", "--out", self.d / "ok", "--seed", "0")
        self.assertEqual(code, 0, text)
        self.assertTrue(any((self.d / "ok").iterdir()))


# ------------------------------------------------------------------ vocallevel
class VocalLevel(Tmp):
    def test_an_unknown_melody_is_named_with_the_real_tracks(self):
        heard = self.d / "heard"
        heard.mkdir()
        song(heard / "Lead.wav", 2.0, 8000, stereo=False)
        song(heard / "Harm.wav", 2.0, 8000, stereo=False)
        als = self.d / "S.als"
        als.write_bytes(b"x")
        for opt in ("--melody", "--lines-from"):
            code, text = hx(self.d, "vocallevel", als, "--heard", heard, opt, "Nope")
            self.assertEqual(code, 1, text)
            self.assertIn("no track called 'Nope'", text)
            self.assertIn("Harm, Lead", text)
            self.assertNotIn("melody: Nope", text)


# ------------------------------------------------------------------ plugins
class Plugins(Tmp):
    def folder(self):
        d = self.d / "VST3"
        for n in ("Alpha Verb", "Beta Synth", "Gamma Comp"):
            (d / f"{n}.vst3/Contents").mkdir(parents=True, exist_ok=True)
        return d

    def base(self):
        return ["plugins", "--no-system", "--folder", f"vst3={self.folder()}", "--prefs-file", self.d / "p.json"]

    def test_save_with_a_filter_is_refused_and_the_saved_list_is_whole(self):
        code, text = hx(self.d, *self.base(), "--save")
        self.assertEqual(code, 0, text)
        whole = json.loads((self.d / "p.json").read_text(encoding="utf-8"))["tools"]["plugins_found"]
        self.assertEqual(len(whole), 3)
        for flag in (["--only", "Cascadia"], ["--free"]):
            code, text = hx(self.d, *self.base(), "--save", *flag)
            self.assertEqual(code, 1, text)
            self.assertIn("--save keeps the whole list", text)
            self.assertEqual(json.loads((self.d / "p.json").read_text(encoding="utf-8"))["tools"]["plugins_found"], whole)

    def test_json_never_replaces_a_file_and_needs_a_folder(self):
        keep = self.d / "p2.json"
        keep.write_text("precious", encoding="utf-8")
        code, text = hx(self.d, *self.base(), "--json", keep)
        self.assertEqual(code, 1, text)
        self.assertIn("already exists", text)
        self.assertEqual(keep.read_text(encoding="utf-8"), "precious")
        code, text = hx(self.d, *self.base(), "--json", self.d / "nodir" / "x.json")
        self.assertEqual(code, 1, text)
        self.assertIn("does not exist", text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("FileNotFoundError", text)

    def test_the_closing_line_does_not_say_nothing_was_written_when_a_file_is(self):
        new = self.d / "new.json"
        code, text = hx(self.d, *self.base(), "--json", new)
        self.assertEqual(code, 0, text)
        self.assertTrue(new.exists())
        self.assertNotIn("nothing was written", text)
        self.assertIn("only the --json file is written", text)
        code, text = hx(self.d, *self.base())
        self.assertIn("nothing was written", text)                                # without --json the old line stays true
        self.assertFalse((self.d / "p.json").exists())


# ------------------------------------------------------------------ translate and tune say where
class Translate(Tmp):
    def test_it_says_where_the_report_and_the_listening_versions_are(self):
        wav = song(self.d / "Song (master).wav", 3.0)
        out = self.d / "tr"
        code, text = hx(self.d, "translate", wav, "--render", "--out", out)
        self.assertEqual(code, 0, text)
        self.assertIn(f"wrote the report {out / 'Song (master) (translation).md'}", text)
        self.assertIn(f"wrote the four listening versions (mono, phone, earbuds, car) in {out}", text)
        for kind in ("mono", "phone", "earbuds", "car"):
            self.assertTrue((out / f"Song (master) ({kind}).wav").exists(), kind)
        code, text = hx(self.d, "translate", wav)                                # no --render: only the report is claimed
        self.assertIn("wrote the report hypnomix-out", text)
        self.assertNotIn("listening versions", text)


class Tune(Tmp):
    def test_report_only_follows_hypnomix_out_and_leaves_the_folder_alone(self):
        t = np.arange(int(3 * 22050)) / 22050
        sf.write(str(self.d / "Lead.wav"), 0.3 * np.sin(2 * np.pi * 440 * t) * (t % 1 < 0.8), 22050)
        elsewhere = self.d / "elsewhere"
        code, text = hx(self.d, "tune", "Lead.wav", "--key", "A minor", "--report-only", extra_env={"HYPNOMIX_OUT": str(elsewhere)})
        self.assertEqual(code, 0, text)
        self.assertTrue((elsewhere / "tune" / "Lead.notes.txt").exists())
        self.assertFalse((self.d / "reports").exists())
        code, text = hx(self.d, "tune", "Lead.wav", "--key", "A minor", "--report-only")
        self.assertTrue((self.d / "hypnomix-out" / "tune" / "Lead.notes.txt").exists())
        self.assertFalse((self.d / "reports").exists())
        self.assertIn("hypnomix-out", text)


# ------------------------------------------------------------------ master
class Master(Tmp):
    def test_running_it_again_never_replaces_the_earlier_master(self):
        wav = song(self.d / "Song mix.wav", 4.0, level=0.1)
        out = self.d / "m"
        code, text = hx(self.d, "master", wav, "--target", "-14", "--out", out)
        self.assertEqual(code, 0, text)
        first = (out / "Song mix (master).wav").read_bytes()
        code, text = hx(self.d, "master", wav, "--target", "-10", "--out", out)
        self.assertEqual(code, 0, text)
        self.assertEqual((out / "Song mix (master).wav").read_bytes(), first)      # the first one is untouched
        self.assertTrue((out / "Song mix (master 2).wav").exists())
        self.assertTrue((out / "Song mix (master 2).json").exists())
        self.assertTrue((out / "Song mix (master notes).md").exists())
        self.assertTrue((out / "Song mix (master 2 notes).md").exists())
        self.assertNotEqual((out / "Song mix (master 2).wav").read_bytes(), first)
        code, text = hx(self.d, "master", wav, "--out", out)
        self.assertTrue((out / "Song mix (master 3).wav").exists())
        from hypnomix.engineer import master as M
        self.assertIn("never replaces an earlier master", " ".join(M.__doc__.split()))


# ------------------------------------------------------------------ check and diff on projects that are not Live sets
class NotLiveSets(Tmp):
    def files(self):
        rpp = self.d / "Song.rpp"
        rpp.write_text('<REAPER_PROJECT 0.1 "7.27" 1\n>\n', encoding="utf-8")
        ardour = self.d / "Song.ardour"
        ardour.write_text('<?xml version="1.0"?>\n<Session/>\n', encoding="utf-8")
        return rpp, ardour

    def test_check_and_diff_say_what_to_use_instead(self):
        for f in self.files():
            for args in (("check", f), ("check", f, "--against", f), ("diff", f, f), ("check", self.d)):
                code, text = hx(self.d, *args)
                self.assertEqual(code, 1, (args, text))
                self.assertIn("reads Live sets", text)
                self.assertIn("hypnomix scan", text)
                for bad in ("Traceback", "BadGzipFile", "do NOT open this set in Live"):
                    self.assertNotIn(bad, text)

    def test_a_live_only_command_given_a_project_ends_in_one_sentence(self):
        rpp, _ = self.files()
        for cmd in ("audit", "sidechain", "edges", "timing"):
            code, text = hx(self.d, cmd, rpp)
            self.assertIn(code, (1, 2), (cmd, text))
            self.assertNotIn("Traceback", text, cmd)
            self.assertNotIn("BadGzipFile", text, cmd)

    def test_masking_given_a_project_says_it_reads_a_folder_of_stems(self):
        rpp, _ = self.files()
        code, text = hx(self.d, "masking", rpp)
        self.assertEqual(code, 1, text)
        self.assertIn("masking reads a folder of stems", text)
        self.assertNotIn("NotADirectoryError", text)
        code, text = hx(self.d, "masking", self.d / "nope")
        self.assertIn("does not exist", text)


# ------------------------------------------------------------------ install --dry-run and doctor
class Install(Tmp):
    def test_dry_run_does_not_say_it_installed(self):
        from hypnomix import install as I
        scripts = self.d / "User Library" / "Remote Scripts"
        buf = io.StringIO()
        with mock.patch.object(I, "remote_scripts_dir", return_value=scripts), mock.patch.object(I, "live_prefs_dir", return_value=None), \
                contextlib.redirect_stdout(buf):
            I.install(["--dry-run"])
        text = buf.getvalue()
        self.assertNotIn("installed.", text)
        self.assertIn("would install it here", text)
        self.assertIn("dry run", text)
        self.assertFalse(scripts.exists())                                         # nothing was copied
        (scripts / "AbletonOSC").mkdir(parents=True)
        (scripts / "AbletonOSC" / "old.txt").write_text("x", encoding="utf-8")
        buf = io.StringIO()
        with mock.patch.object(I, "remote_scripts_dir", return_value=scripts), mock.patch.object(I, "live_prefs_dir", return_value=None), \
                contextlib.redirect_stdout(buf):
            I.install(["--dry-run"])
        self.assertIn("would move the existing copy to", buf.getvalue())
        self.assertTrue((scripts / "AbletonOSC" / "old.txt").exists())
        self.assertEqual([p.name for p in scripts.iterdir()], ["AbletonOSC"])

    def test_the_command_list_does_not_promise_claude_code_config(self):
        from hypnomix import cli
        text = " ".join(cli.usage().split())
        self.assertNotIn("write Claude Code config", text)
        self.assertIn("install the Live remote script into Live's User Library", text)

    def test_the_app_shows_only_the_script_step(self):
        from hypnomix.app import setup as S
        from hypnomix import install as I

        def fake(argv):
            print("1. Live remote script → /x/AbletonOSC\n   installed. Restart Live.\n2. plug-in parameters: run it\n3. BlackHole\n"
                  "4. Claude Code: open this repo\n\nThen run: hypnomix doctor")
        with mock.patch.object(I, "install", fake), mock.patch.object(S, "live_status", return_value={}):
            log = S.setup_live()["log"]
        self.assertIn("1. Live remote script", log)
        self.assertIn("installed.", log)
        for later in ("2. plug-in", "BlackHole", "Claude Code", "hypnomix doctor"):
            self.assertNotIn(later, log)


class Doctor(Tmp):
    """doctor itself is never run (it pings a running Live); its rows are built from stubs."""

    def rows(self, live_here, scripts_present=False):
        from hypnomix import install as I
        scripts = self.d / "Remote Scripts"
        scripts.mkdir(exist_ok=True)
        with mock.patch.object(I, "uses_live", return_value=live_here), mock.patch.object(I, "remote_scripts_dir", return_value=scripts), \
                mock.patch.object(I, "live_prefs_dir", return_value=None), mock.patch.object(I, "_live_answer", return_value=(False, "no answer")), \
                mock.patch.object(I, "_blackhole", return_value=[]), mock.patch.object(I.shutil, "which", return_value="/x/ffmpeg"), \
                mock.patch.object(I, "_port_open", return_value=False):
            return I.doctor_rows()

    def test_someone_without_live_is_not_told_the_live_parts_are_needed(self):
        rows = {r[1]: r[0] for r in self.rows(False)}
        for name in ("AbletonOSC remote script", "Live via AbletonOSC", "BlackHole (for loop/diagnose)"):
            self.assertEqual(rows[name], "·", name)

    def test_someone_with_live_still_is(self):
        rows = {r[1]: r[0] for r in self.rows(True)}
        for name in ("AbletonOSC remote script", "Live via AbletonOSC", "BlackHole (for loop/diagnose)"):
            self.assertEqual(rows[name], "✗", name)

    def test_the_exit_code_counts_only_what_is_needed(self):
        from hypnomix import install as I
        no_live = self.rows(False)
        live = self.rows(True)
        # Python and ffmpeg are real here; take the packages row out of the question so the test is about Live only
        fixed = lambda rows: [("✓", "Python", ""), ("✓", "Python packages", ""), ("✓", "ffmpeg", "")] + rows[3:]
        self.assertEqual(I.doctor_exit(fixed(no_live)), 0)
        self.assertEqual(I.doctor_exit(fixed(live)), 1)
        self.assertEqual(I.doctor_exit([("✗", "ffmpeg", ""), ("✓", "x", ""), ("✓", "y", ""), ("·", "z", "")]), 1)

    def test_a_computer_with_the_live_library_or_app_is_a_live_computer(self):
        from hypnomix import install as I
        empty_apps = self.d / "Applications"
        empty_apps.mkdir()
        home = self.d / "home"
        home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}), mock.patch.object(I, "LIVE_APP_DIRS", (empty_apps,)):
            self.assertFalse(I.uses_live())
            I.remote_scripts_dir().mkdir(parents=True)
            self.assertTrue(I.uses_live())
        other = self.d / "other"
        (other / "Applications" / "Ableton Live 12.app").mkdir(parents=True)
        with mock.patch.dict(os.environ, {"HOME": str(other), "USERPROFILE": str(other)}), \
                mock.patch.object(I, "LIVE_APP_DIRS", (other / "Applications",)):
            self.assertTrue(I.uses_live())


# ------------------------------------------------------------------ names and paths given to ab and fix
class AbAndFixNames(Tmp):
    def scan(self):
        from tests.test_workflow import make_set
        als = make_set(self.d / "Song.als")
        sd = self.d / "scan"
        sd.mkdir()
        f = dict(id="smooth-1", n=1, tool="smooth", kind="click", severity="low", track="Vox", where="1.1.00", problem="p",
                 fix="f", applies="set")
        (sd / "findings.json").write_text(json.dumps(dict(set=str(als), notes=[], findings=[f])), encoding="utf-8")
        (sd / "scan.json").write_text(json.dumps(dict(set=str(als), mode="set", set_mtime=als.stat().st_mtime)), encoding="utf-8")
        (sd / "decisions.json").write_text(json.dumps({"smooth-1": dict(decision="approve")}), encoding="utf-8")
        return sd

    def test_ab_names_a_folder_that_does_not_exist_and_an_id_that_does_not(self):
        code, text = hx(self.d, "ab", self.d / "nonexist")
        self.assertEqual(code, 1, text)
        self.assertIn("no such folder", text)
        self.assertNotIn("could not be read", text)
        sd = self.scan()
        code, text = hx(self.d, "ab", sd, "--ids", "nope-1")
        self.assertEqual(code, 1, text)
        self.assertIn("unknown ids: nope-1", text)                                 # the wording `fix --approve` uses
        self.assertFalse((sd / "ab").exists())

    def test_fix_out_must_be_a_new_set_name_in_the_sets_folder(self):
        sd = self.scan()
        for bad in ("noext", ".als"):
            code, text = hx(self.d, "fix", sd, "--approved", "--dry-run", "--out", bad)
            self.assertEqual(code, 1, (bad, text))
            self.assertIn("written as a new .als", text)
        self.assertEqual(sorted(p.name for p in self.d.iterdir() if p.is_file()), ["Song.als"])     # no file called noext or .als

    def test_a_path_with_dots_is_made_plain_and_a_path_from_where_you_are_is_not_doubled(self):
        sd = self.scan()
        code, text = hx(self.d, "fix", sd, "--approved", "--dry-run", "--out", "a/../b.als")
        self.assertEqual(code, 0, text)
        self.assertIn(str(self.d / "b.als"), text)
        # the form DEMO.md used to print: a path from the folder you stand in, which already names the project's folder
        code, text = hx(self.d, "fix", sd, "--approved", "--dry-run", "--out", f"{self.d.name}/Song (fixed).als", cwd=self.d.parent)
        self.assertEqual(code, 0, text)
        self.assertNotIn("must be in the same folder", text)
        code, text = hx(self.d, "fix", sd, "--approved", "--dry-run", "--out", "sub/x.als")
        self.assertEqual(code, 1, text)
        self.assertIn("must be in the same folder as the original", text)
        self.assertIn("points at", text)                                           # and the path it really worked out is shown


# ------------------------------------------------------------------ the install steps in the docs
class InstallDocs(unittest.TestCase):
    def test_the_source_install_activates_the_environment(self):
        for rel in ("README.md", "docs/guides/01-getting-started.md"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            i = text.index("uv venv && uv pip install -e .")
            tail = text[i:i + 400]
            self.assertIn("source .venv/bin/activate", tail, rel)
            self.assertLess(tail.index("source .venv/bin/activate"), tail.index("hypnomix install"), rel)
        self.assertIn("rubberband", (ROOT / "README.md").read_text(encoding="utf-8").split("**From source**")[1][:900])


class DemoText(Tmp):
    def test_the_apply_command_printed_for_a_reaper_demo_works_from_where_it_is_run(self):
        out = self.d / "o"
        code, text = quick("demo", "--kind", "reaper", "--out", out)
        self.assertEqual(code, 0, text)
        md = next(out.rglob("DEMO.md")).read_text(encoding="utf-8")
        line = next(x for x in md.splitlines() if "--approved" in x)
        self.assertIn('--out "Hypnomix Demo Song (fixed).rpp"', line)                # a bare name: `fix` puts it by the project
        self.assertNotIn(str(out), line)
        scan = next(x for x in md.splitlines() if x.startswith("hypnomix scan"))
        self.assertIn(str((out / "Hypnomix Demo Song" / "Hypnomix Demo Song.rpp").resolve()), scan)


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------------------------------ the checker's second round
class MoreNumericOptions(Tmp):
    def test_every_tempo_and_loudness_option_is_checked_before_any_work(self):
        wav = song(self.d / "f.wav", 1.0)
        folder = self.d / "stems"
        folder.mkdir()
        cases = [
            ("compare", wav, wav, "--bpm", "1e9"), ("compare", wav, wav, "--bpm", "nan"), ("compare", wav, wav, "--bpm", "5"),
            ("key", "--audio", wav, "--bpm", "1e9"), ("key", "--audio", wav, "--bars", "-3"),
            ("midi", wav, "--bpm", "nan"), ("takes", folder, "--bpm", "0"), ("voices", folder, "--bpm", "inf"),
            ("loops", wav, "--bpm", "-80"), ("tempomap", wav, "--bpm", "1e9"), ("sidechain", "--bpm", "nan"),
            ("vocalign", wav, "--bpm", "1e9"),
            ("master", wav, "--target", "nan"), ("master", wav, "--target", "5"), ("master", wav, "--ceiling", "5"),
            ("master", wav, "--match", "2"), ("master", wav, "--warmth", "-1"),
            ("automix", folder, "--target", "nan"), ("automix", folder, "--target", "5"),
            ("qc", wav, "--target", "nan"), ("qc", wav, "--target", "5"),
            ("release", wav, "--target", "nan"), ("chain", "master", wav, "--target", "nan"),
            ("rebalance", folder, "--ceiling", "nan"),
            ("harsh", wav, "--top", "-1"), ("harsh", wav, "--top", "0"),
        ]
        for case in cases:
            code, text = quick(*case)
            self.assertEqual(code, 2, (case, text))
            self.assertIn("is not a", text, case)
            self.assertNotIn("Traceback", text)
        self.assertFalse((self.d / "hypnomix-out").exists())

    def test_the_section_finder_refuses_a_tempo_that_would_hang_it(self):
        from hypnomix.ears import sections as S
        y = np.zeros(22050, dtype="float32")
        for bad in (1e9, float("nan"), float("inf"), 5, -90):
            with self.assertRaises(ValueError, msg=str(bad)):
                S.bar_grid(y, 22050, bad)

    def test_a_good_tempo_and_target_still_run(self):
        wav = song(self.d / "f.wav", 4.0, level=0.1)
        code, text = hx(self.d, "master", wav, "--target", "-14", "--ceiling", "-1", "--match", "0.5", "--out", self.d / "m")
        self.assertEqual(code, 0, text)
        code, text = hx(self.d, "qc", wav, "--target", "-16")
        self.assertIn(code, (0, 1), text)
        self.assertNotIn("Traceback", text)

    def test_a_whole_number_bound_is_written_as_a_whole_number(self):
        code, text = quick("demo", "--out", self.d / "o", "--seed", "-5")
        self.assertEqual(code, 2)
        self.assertIn("a whole number from 0 to 4294967295", text)
        self.assertNotIn("e+", text)
        self.assertEqual(A._n(0.5), "0.5")
        self.assertEqual(A._n(400.0), "400")


class MissingLiveSets(Tmp):
    def test_a_typo_or_a_folder_is_not_an_error_in_the_set(self):
        folder = self.d / "Project folder"
        folder.mkdir()
        for args, want in ((("audit", self.d / "nope.als"), "no such file"), (("audit", folder), "is a folder"),
                           (("refs", self.d / "nope.als"), "no such file"), (("tidy", folder), "is a folder"),
                           (("check", self.d / "nope.als"), "no such file"), (("check", self.d / "nope.als", "--against", self.d / "x.als"), "no such file"),
                           (("diff", self.d / "nope.als", self.d / "also.als"), "no such file")):
            code, text = hx(self.d, *args)
            self.assertIn(code, (1, 2), (args, text))
            self.assertIn(want, text, args)
            for bad in ("Traceback", "FileNotFoundError", "IsADirectoryError", "gzip", "do NOT open this set"):
                self.assertNotIn(bad, text, (args, bad))

    def test_check_function_names_the_missing_file_instead_of_calling_it_gzip(self):
        from hypnomix.session import check as C
        err, warn, facts = C.check(str(self.d / "nope.als"))
        self.assertEqual(len(err), 1)
        self.assertIn("no such file", err[0])
        self.assertNotIn("gzip", err[0])
        (self.d / "dir").mkdir()
        err, _, _ = C.check(str(self.d / "dir"))
        self.assertIn("folder", err[0])

    def test_a_folder_opened_with_permission_denied_is_still_a_folder(self):
        """Windows answers "permission denied" (errno 13), not IsADirectoryError, when a folder is opened as a file."""
        from hypnomix.session import check as C
        (self.d / "dir").mkdir()
        denied = PermissionError(13, "Permission denied", str(self.d / "dir"))
        with mock.patch.object(C, "read_gz", side_effect=denied):
            err, _, _ = C.check(str(self.d / "dir"))
        self.assertIn("folder", err[0])
        self.assertNotIn("gzip", err[0])
        with mock.patch.object(C, "read_gz", side_effect=PermissionError(13, "Permission denied", str(self.d / "x.als"))):
            err, _, _ = C.check(str(self.d / "x.als"))                       # a file that is really refused keeps its own words
        self.assertIn("gzip", err[0])

    def test_a_real_set_still_checks(self):
        from hypnomix.core import gz
        p = self.d / "Song.als"
        import gzip
        with gzip.open(p, "wb") as f:
            f.write(b'<Ableton MajorVersion="5" MinorVersion="11.0_1" Creator="x"><LiveSet><NextPointeeId Value="5"/><Tracks/></LiveSet></Ableton>')
        code, text = hx(self.d, "check", p)
        self.assertNotIn("no such file", text)
        self.assertNotIn("Traceback", text)


class RerunsNeverReplace(Tmp):
    def test_translate_numbers_a_second_run_and_keeps_the_first(self):
        wav = song(self.d / "Song (master).wav", 3.0)
        out = self.d / "tr"
        code, text = hx(self.d, "translate", wav, "--render", "--out", out)
        self.assertEqual(code, 0, text)
        before = {p.name: p.read_bytes() for p in out.iterdir()}
        self.assertEqual(len(before), 5)
        code, text = hx(self.d, "translate", wav, "--render", "--out", out)
        self.assertEqual(code, 0, text)
        for name, data in before.items():
            self.assertEqual((out / name).read_bytes(), data, name)           # the first run is untouched
        for new in ("Song (master) (translation 2).md", "Song (master) (phone 2).wav", "Song (master) (mono 2).wav",
                    "Song (master) (earbuds 2).wav", "Song (master) (car 2).wav"):
            self.assertTrue((out / new).exists(), new)
        self.assertIn(f"wrote the report {out / 'Song (master) (translation 2).md'}", text)
        self.assertIn("numbered 2", text)
        code, text = hx(self.d, "translate", wav, "--render", "--out", out)
        self.assertTrue((out / "Song (master) (translation 3).md").exists())

    def test_translate_default_folder_is_numbered_too(self):
        wav = song(self.d / "Song.wav", 3.0)
        for n in (1, 2):
            code, text = hx(self.d, "translate", wav)
            self.assertEqual(code, 0, text)
        folder = self.d / "hypnomix-out" / "translate"
        self.assertEqual(sorted(p.name for p in folder.glob("*.md")), ["Song (translation 2).md", "Song (translation).md"])

    def test_next_run_creates_nothing(self):
        from hypnomix.engineer import translate as T
        self.assertEqual(T.next_run("x/Song.wav", str(self.d / "never"), True, True), 1)
        self.assertFalse((self.d / "never").exists())

    def test_tune_report_only_numbers_a_second_report(self):
        t = np.arange(int(3 * 22050)) / 22050
        sf.write(str(self.d / "Lead.wav"), 0.3 * np.sin(2 * np.pi * 440 * t) * (t % 1 < 0.8), 22050)
        folder = self.d / "hypnomix-out" / "tune"
        code, text = hx(self.d, "tune", "Lead.wav", "--key", "A minor", "--report-only")
        self.assertEqual(code, 0, text)
        first = (folder / "Lead.notes.txt").read_text(encoding="utf-8")
        code, text = hx(self.d, "tune", "Lead.wav", "--key", "A minor", "--report-only", "--tuning", "10")
        self.assertEqual(code, 0, text)
        self.assertEqual((folder / "Lead.notes.txt").read_text(encoding="utf-8"), first)
        self.assertTrue((folder / "Lead 2.notes.txt").exists())
        self.assertIn("Lead 2.notes.txt", text)
