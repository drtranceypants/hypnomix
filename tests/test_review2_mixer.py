"""Second review of REAPER's hands-on mixer tools (mixer.py / mixer.lua), against the fake bridge in
test_reaper_mixer: nudge by number, change checks, snapshot help / restore / diff / OUT, loop --revert, take labels,
the 'guide seen' flag, diagnose --whole, and the help saying what was run in REAPER."""
import contextlib
import io
import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from hypnomix.reaper import mixer as MX
from tests.test_reaper_mixer import LUA, FakeBridge, fake_measure, snap

PY = Path(MX.__file__).read_text(encoding="utf-8")
JSFX = Path(MX.__file__).parent / "jsfx"


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


def numbered_bridge(td, names_volumes):
    b = FakeBridge(td)
    master = b.snap["tracks"][0]
    b.snap["tracks"] = [master] + [
        {"index": i, "name": n, "guid": "{%d}" % i, "volume": v, "pan": 0.0, "width": 1.0, "mute": False,
         "phase": False, "solo": 0, "depth": 0, "sends": [], "fx": []} for i, (n, v) in enumerate(names_volumes)]
    return b


class NudgeByNumber(unittest.TestCase):
    """#4: a number is a track index, as the bridge reads it, and the write goes to the track that was read."""
    def test_name_1_at_index_0(self):
        with tempfile.TemporaryDirectory() as td:
            b = numbered_bridge(td, [("1", 1.0), ("x", 0.25)])
            MX.apply_change(b, "nudge 1 +1")
            call = b.calls[-1]
            self.assertEqual(call[0], "set_track")
            self.assertEqual(call[1]["track"], "1")
            self.assertAlmostEqual(call[1]["volume_db"], 20 * math.log10(0.25) + 1)

    def test_all_numeric_names(self):
        with tempfile.TemporaryDirectory() as td:
            b = numbered_bridge(td, [("1", 1.0), ("2", 0.5), ("3", 0.25)])
            MX.apply_change(b, "nudge 2 +1")
            self.assertEqual(b.calls[-1][1]["track"], "2")
            self.assertAlmostEqual(b.calls[-1][1]["volume_db"], 20 * math.log10(0.25) + 1)

    def test_by_name_sends_the_index(self):
        with tempfile.TemporaryDirectory() as td:
            b = FakeBridge(td)
            MX.apply_change(b, "nudge Kick +1")
            self.assertEqual(b.calls[-1][1]["track"], "1")
            MX.apply_change(b, "nudge master -1")
            self.assertEqual(b.calls[-1][1]["track"], "master")

    def test_number_with_no_such_index_is_not_a_name(self):
        with tempfile.TemporaryDirectory() as td:
            b = numbered_bridge(td, [("808", 1.0)])
            with self.assertRaises(MX.ReaperError):
                MX.apply_change(b, "nudge 808 +1")

    def test_nudge_above_plus_12_refused(self):
        with tempfile.TemporaryDirectory() as td:
            b = FakeBridge(td)
            with self.assertRaises(MX.ReaperError):
                MX.apply_change(b, "nudge Drums +13")
            self.assertNotIn("set_track", [c[0] for c in b.calls])


class ChangeChecks(unittest.TestCase):
    """Nit: every change is checked before anything renders: finite numbers, a whole send number, sensible levels."""
    def test_refused(self):
        for bad in ("db Lead nan", "db Lead inf", "db Lead 1e999", "nudge Lead nan", "pan Lead inf",
                    "param Lead ReaComp 0 nan", "paramd Lead ReaComp 0 -inf", "db Lead 400", "db Lead -151",
                    "send Lead x -12", "send Lead 1.5 -12", "send Lead -1 -12", "send Lead 0 40"):
            with self.assertRaises(ValueError, msg=bad):
                MX.parse_change(bad)

    def test_accepted(self):
        for ok in ("db Lead 12", "db Lead -150", "send Lead 0 -12", "send Lead 2 0", "pan Lead -0.3"):
            MX.parse_change(ok)

    def test_bad_send_stops_before_take_a(self):
        with tempfile.TemporaryDirectory() as td:
            b = FakeBridge(td)
            with self.assertRaises(ValueError):
                MX.loop(b, 0, 2, Path(td) / "loop", ab=["send Kick x -12"], measure=fake_measure, log=lambda *_: None)
            self.assertNotIn("render_master", [c[0] for c in b.calls])

    def test_bar_range_whole_numbers(self):
        self.assertEqual(MX.parse_range("1-3", whole=True), (1.0, 3.0))
        self.assertEqual(MX.parse_range("1.5-3.25"), (1.5, 3.25))
        for bad in ("1-", "1-3.7", "-3", "a-b"):
            with self.assertRaises(ValueError, msg=bad):
                MX.parse_range(bad, whole=True)


class SnapshotCli(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.td)

    def tearDown(self):
        os.chdir(self.cwd)

    def test_help_writes_no_file_and_needs_no_bridge(self):
        for h in ("-h", "--help"):
            b = FakeBridge(self.td)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                MX.main_snapshot([h], r=b)
            self.assertIn("hypnomix reaper snapshot", buf.getvalue())
            self.assertEqual(b.calls, [])
            self.assertFalse(Path(self.td, h).exists())

    def test_other_option_refused(self):
        with self.assertRaises(SystemExit) as e:
            MX.main_snapshot(["--out"], r=FakeBridge(self.td))
        self.assertIn("unknown option --out", str(e.exception.code))
        self.assertFalse(Path(self.td, "--out").exists())

    def test_existing_out_untouched(self):
        out = Path(self.td) / "s.json"
        out.write_text("precious", encoding="utf-8")
        b = FakeBridge(self.td)
        with self.assertRaises(SystemExit) as e:
            MX.main_snapshot([str(out)], r=b)
        self.assertIn("already exists", str(e.exception.code))
        self.assertEqual(out.read_text(encoding="utf-8"), "precious")
        self.assertEqual(b.calls, [])                    # REAPER not even asked

    def test_out_into_missing_folder_is_made(self):
        out = Path(self.td) / "sub" / "deeper" / "x.json"
        with quiet():
            MX.main_snapshot([str(out)], r=FakeBridge(self.td))
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["tracks"][0]["name"], "MASTER")

    def test_default_name_never_replaces(self):
        p = Path(self.td) / "reaper-mix.json"
        p.write_text("precious", encoding="utf-8")
        self.assertEqual(MX._free(p).name, "reaper-mix-2.json")
        self.assertEqual(p.read_text(encoding="utf-8"), "precious")

    def test_missing_and_non_json_files_are_one_sentence(self):
        bad = Path(self.td) / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        nosnap = Path(self.td) / "other.json"
        nosnap.write_text('{"a": 1}', encoding="utf-8")
        good = Path(self.td) / "good.json"
        good.write_text(json.dumps(snap()), encoding="utf-8")
        for argv, words in ((["restore", "missing.json"], "no such file"),
                            (["restore", str(bad)], "not a readable snapshot"),
                            (["restore", str(nosnap)], "no mixer snapshot"),
                            (["diff", "missing.json", str(good)], "no such file"),
                            (["diff", str(good), str(bad)], "not a readable snapshot")):
            b = FakeBridge(self.td)
            with self.assertRaises(SystemExit, msg=argv) as e:
                MX.main_snapshot(argv, r=b)
            self.assertIsInstance(e.exception.code, str, argv)
            self.assertIn(words, e.exception.code, argv)
            self.assertNotIn("mixer_restore", [c[0] for c in b.calls])

    def test_empty_snapshot_not_restored(self):
        empty = Path(self.td) / "empty.json"
        empty.write_text('{"tracks": []}', encoding="utf-8")
        b = FakeBridge(self.td)
        with self.assertRaises(SystemExit) as e:
            MX.main_snapshot(["restore", str(empty)], r=b)
        self.assertIn("nothing to restore", e.exception.code)
        self.assertEqual(b.calls, [])


class TakeFiles(unittest.TestCase):
    """#14: a loop take's .json restores and diffs like a snapshot."""
    def test_restore_from_take(self):
        with tempfile.TemporaryDirectory() as td:
            b = FakeBridge(td)
            (Path(td) / "loop").mkdir()
            wav, _ = MX.take(b, 0, 2, Path(td) / "loop", "t1", measure=fake_measure)
            with quiet():
                res = MX.main_snapshot(["restore", str(wav.with_suffix(".json"))], r=b)
            self.assertEqual(res["changed"], 3)
            self.assertIn("track\t{K}\t1\tKick", b.restored)
            self.assertIn("info\tD_VOL\t0.5", b.restored)

    def test_take_with_mix_error(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "01-t.json"
            p.write_text(json.dumps({"label": "t", "metrics": {}, "mix_error": "bridge timed out"}), encoding="utf-8")
            with self.assertRaises(SystemExit) as e:
                MX.main_snapshot(["restore", str(p)], r=FakeBridge(td))
            self.assertIn("no mixer snapshot", e.exception.code)
            self.assertIn("bridge timed out", e.exception.code)

    def test_diff_of_two_takes(self):
        with tempfile.TemporaryDirectory() as td:
            b = FakeBridge(td)
            (Path(td) / "loop").mkdir()
            w1, _ = MX.take(b, 0, 2, Path(td) / "loop", "a", measure=fake_measure)
            b.snap["tracks"][1]["mute"] = True
            w2, _ = MX.take(b, 0, 2, Path(td) / "loop", "b", measure=fake_measure)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                MX.main_snapshot(["diff", str(w1.with_suffix(".json")), str(w2.with_suffix(".json"))])
            self.assertEqual(buf.getvalue().strip(), "Drums: muted")


class Labels(unittest.TestCase):
    """#19: the label is cleaned for the file name only; takes number on and never replace each other."""
    def test_slash_label_twice(self):
        with tempfile.TemporaryDirectory() as td:
            b = FakeBridge(td)
            folder = Path(td) / "loop2"
            folder.mkdir()
            MX.take(b, 0, 2, folder, "a/b", measure=fake_measure)
            MX.take(b, 0, 2, folder, "a/b", measure=fake_measure)
            self.assertEqual(sorted(f.name for f in folder.glob("*.wav")), ["01-a-b.wav", "02-a-b.wav"])
            self.assertEqual(json.loads((folder / "01-a-b.json").read_text(encoding="utf-8"))["label"], "a/b")

    def test_no_escape_and_no_windows_illegal(self):
        self.assertEqual(MX.file_label("../../escape"), "escape")
        self.assertEqual(MX.file_label('a:b*c?"d<e>f|g'), "a-b-c-d-e-f-g")
        self.assertEqual(MX.file_label("vox +1 é"), "vox +1 é")
        self.assertEqual(MX.file_label("/.."), "take")


class Revert(unittest.TestCase):
    """#18: --revert on its own is refused with the usage line, before anything changes."""
    def test_revert_needs_ab(self):
        b = FakeBridge(tempfile.mkdtemp())
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            MX.main_loop(["--secs", "1-3", "--set", "db Kick -3", "--revert"], r=b)
        self.assertIn("--revert only works together with --ab", err.getvalue())
        self.assertEqual(b.calls, [])


class GuideSeen(unittest.TestCase):
    """#21: the plug-ins' 'guide seen' flag is not a mixer value: not in a snapshot, a diff or a restore."""
    def test_lua_skips_it(self):
        self.assertIn('lp:find("guide seen", 1, true)', LUA)
        for f in ("hypnomix_probe.jsfx", "hypnomix_main.jsfx"):
            text = (JSFX / f).read_text(encoding="utf-8")
            lines = [ln for ln in text.splitlines() if ln.startswith("slider") and ":guide=" in ln]
            self.assertEqual(len(lines), 1, f)
            self.assertIn("guide seen", lines[0].lower(), f)

    def _two(self):
        def s(v):
            d = snap()
            d["tracks"][3]["fx"].append({"index": 1, "name": "JS: HypnoMix Probe", "guid": "{P}", "on": True,
                                         "params": [{"i": 4, "name": "guide seen (the walkthrough in this window)",
                                                     "value": v}]})
            return d
        return s(0.0), s(1.0)

    def test_diff_and_restore_skip_it(self):
        a, b = self._two()
        self.assertEqual(MX.diff(a, b), [])
        text = MX.flatten(a)
        self.assertIn("fx\t{P}\t1\tJS: HypnoMix Probe", text)
        self.assertNotIn("param\t4\t", text)

    def test_other_plugins_keep_a_guide_param(self):
        a, b = self._two()
        for d in (a, b):
            d["tracks"][3]["fx"][-1]["name"] = "JS: Someone Else"
        self.assertEqual(len(MX.diff(a, b)), 1)


class Diagnose(unittest.TestCase):
    def test_whole_missing(self):
        b = FakeBridge(tempfile.mkdtemp())
        with self.assertRaises(SystemExit) as e:
            MX.main_diagnose(["--whole", "missing.wav"], r=b)
        self.assertIn("no such file", e.exception.code)
        self.assertEqual(b.calls, [])

    def test_whole_not_audio(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.wav"
            p.write_text("not audio", encoding="utf-8")
            with self.assertRaises(ValueError):
                MX.diagnose(FakeBridge(td), Path(td) / "dx", whole=str(p), log=lambda *_: None)


class Honesty(unittest.TestCase):
    """#13: the help of loop / diagnose and the mixer.lua header say what was run in REAPER, and what was not."""
    def test_no_stale_untested_text(self):
        for text in (PY, LUA):
            self.assertNotIn("Not yet run in REAPER", text)
            self.assertNotIn("Untested in REAPER when written", text)

    def test_help_says_what_ran(self):
        doc = " ".join(MX.__doc__.split())
        for words in ("REAPER 7.86", "two-track test project", "2026-11-26", "never on a real song",
                      "nothing judged by ear", "Not checked: Windows", "diagnose with folders"):
            self.assertIn(words, doc)
        lua = " ".join(LUA.split())
        for words in ("REAPER 7.86", "two-track test project", "never on a real song", "Not checked: Windows"):
            self.assertIn(words, lua)


if __name__ == "__main__":
    unittest.main()
