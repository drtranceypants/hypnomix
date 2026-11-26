"""Tested Live versions: a tool that writes a NEW set refuses one saved by a Live newer than the newest tested.

Synthetic sets only, with the header (Creator, MinorVersion) of Live 10, 11, 12 and a made-up Live 13.
Run from the repo root:  python -m unittest tests.test_liveversion -v
"""
import contextlib, gzip, io, os, shutil, tempfile, unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from hypnomix.session import liveversion as LV
from hypnomix.session import automation as aa

HEADERS = {
    "10": 'MajorVersion="4" MinorVersion="10.1.30" Creator="Ableton Live 10.1.30"',
    "11": 'MajorVersion="5" MinorVersion="11.0_11300" Creator="Ableton Live 11.3.13"',
    "12": 'MajorVersion="5" MinorVersion="12.0_12049" Creator="Ableton Live 12.0.5"',
    "12.4": 'MajorVersion="5" MinorVersion="12.0_12049" Creator="Ableton Live 12.4"',
    "13": 'MajorVersion="5" MinorVersion="13.0_13001" Creator="Ableton Live 13.0.2"',
    "minor-only": 'MajorVersion="5" MinorVersion="13.1_13100"',
    "none": 'MajorVersion="5"',
    "odd": 'MajorVersion="5" Creator="Some Other DAW 99" MinorVersion="x"',
}


# writers of their own sets that do not call the check yet (see the hand-over note); this list may only shrink
NOT_GUARDED_YET = {
    "engineer/duck.py", "engineer/devices.py", "engineer/sidechain.py", "session/motion.py", "session/unroll.py",
    "session/tidy.py", "session/names.py", "session/vocallevel.py", "session/order.py", "session/cliplevel.py",
    "session/edges.py", "session/borrow.py", "workflow/abset.py", "workflow/oversight.py", "workflow/fix.py",
}


def set_xml(header):
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<Ableton {header}><LiveSet><Tracks/>'
            '<MainTrack><DeviceChain><Mixer/></DeviceChain></MainTrack></LiveSet></Ableton>').encode()


def write_set(path, key):
    with gzip.open(path, "wb") as f:
        f.write(set_xml(HEADERS[key]))
    return path


class Tmp(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, True)
        env = {k: v for k, v in os.environ.items() if k != LV.ENV_FORCE}
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start(); self.addCleanup(p.stop)
        f = mock.patch.object(LV, "FORCE", False)
        f.start(); self.addCleanup(f.stop)
        w = mock.patch.object(LV, "_warned", set())
        w.start(); self.addCleanup(w.stop)


class Reading(Tmp):
    def test_the_version_comes_from_creator_then_minor_version(self):
        parsed = {k: LV.read_header(write_set(self.td / f"{k}.als", k)) for k in HEADERS}
        self.assertEqual(parsed["10"][:3], (10, 1, 30))
        self.assertEqual(parsed["11"][:3], (11, 3, 13))
        self.assertEqual(parsed["12"][:3], (12, 0, 5))
        self.assertEqual(parsed["12.4"][:3], (12, 4, 0))
        self.assertEqual(parsed["13"][3], "13.0.2")
        self.assertEqual(parsed["minor-only"][:2], (13, 1))
        self.assertIsNone(parsed["none"])
        self.assertIsNone(LV.read_header(self.td / "missing.als"))
        (self.td / "junk.als").write_bytes(b"not a set")
        self.assertIsNone(LV.read_header(self.td / "junk.als"))

    def test_the_tested_list_is_live_11_and_12(self):
        self.assertEqual(LV.TESTED_MAJORS, (11, 12))
        self.assertFalse(LV.is_newer(LV.parse("Ableton Live 12.9")))
        self.assertTrue(LV.is_newer(LV.parse("Ableton Live 13.0")))
        self.assertFalse(LV.is_newer(None))

    def test_version_of_reads_an_element_or_a_tree(self):
        root = ET.fromstring(set_xml(HEADERS["13"]))
        self.assertEqual(LV.version_of(root)[0], 13)
        self.assertEqual(LV.version_of(ET.ElementTree(root))[0], 13)


class Writing(Tmp):
    def tree(self, key):
        return ET.ElementTree(ET.fromstring(set_xml(HEADERS[key])))

    def test_live_11_and_12_and_older_pass_silently(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for key in ("10", "11", "12", "12.4"):
                self.assertIsNotNone(LV.check_write(self.tree(key).getroot()), key)
        self.assertEqual(err.getvalue(), "")

    def test_a_newer_major_version_is_refused_in_plain_words(self):
        with self.assertRaises(LV.NewerLive) as cm:
            LV.check_write(self.tree("13").getroot())
        msg = str(cm.exception)
        for text in ("saved by Live 13.0.2", "tested up to Live 12", "will not write a new set from it",
                     "HYPNOMIX_FORCE_LIVE_VERSION=1", "the format may have changed", "Reading and scanning still work"):
            self.assertIn(text, msg)
        with self.assertRaises(LV.NewerLive):                        # a version only the MinorVersion gives
            LV.check_write(self.tree("minor-only").getroot())

    def test_the_environment_variable_and_the_module_flag_let_it_through(self):
        root = self.tree("13").getroot()
        with mock.patch.dict(os.environ, {LV.ENV_FORCE: "1"}):
            self.assertEqual(LV.check_write(root)[0], 13)
        with mock.patch.dict(os.environ, {LV.ENV_FORCE: "0"}), self.assertRaises(LV.NewerLive):
            LV.check_write(root)
        with mock.patch.object(LV, "FORCE", True):
            self.assertEqual(LV.check_write(root)[0], 13)
        self.assertEqual(LV.check_write(root, force=True)[0], 13)
        with mock.patch.dict(os.environ, {LV.ENV_FORCE: "1"}), self.assertRaises(LV.NewerLive):
            LV.check_write(root, force=False)

    def test_a_version_that_cannot_be_read_is_one_warning_not_a_refusal(self):
        for key in ("none", "odd"):
            err = io.StringIO()
            with mock.patch.object(LV, "_warned", set()), contextlib.redirect_stderr(err):
                self.assertIsNone(LV.check_write(self.tree(key).getroot()))
                self.assertIsNone(LV.check_write(self.tree(key).getroot()))        # asked twice, said once
            lines = err.getvalue().strip().splitlines()
            self.assertEqual(len(lines), 1, key)
            self.assertIn("could not read which version of Live", lines[0])

    def test_check_file_reads_only_the_header(self):
        self.assertIsNotNone(LV.check_file(write_set(self.td / "a.als", "12")))
        with self.assertRaises(LV.NewerLive):
            LV.check_file(write_set(self.td / "b.als", "13"))

    def test_the_common_save_path_refuses_and_writes_nothing(self):
        src, out = write_set(self.td / "src.als", "13"), self.td / "out.als"
        tree = aa.load(src)
        with self.assertRaises(SystemExit) as cm:
            aa.save(tree, src, out)
        self.assertIn("saved by Live 13.0.2", str(cm.exception))
        self.assertFalse(out.exists())
        with mock.patch.dict(os.environ, {LV.ENV_FORCE: "1"}), contextlib.redirect_stdout(io.StringIO()):
            aa.save(tree, src, out)
        self.assertTrue(out.exists())
        for key in ("11", "12"):
            s, o = write_set(self.td / f"s{key}.als", key), self.td / f"o{key}.als"
            with contextlib.redirect_stdout(io.StringIO()):
                aa.save(aa.load(s), s, o)
            self.assertTrue(o.exists(), key)

    def test_a_set_held_as_text_is_checked_from_its_header(self):
        for key in ("11", "12", "12.4"):
            self.assertIsNotNone(LV.check_text(set_xml(HEADERS[key]).decode()), key)
        with self.assertRaises(LV.NewerLive):
            LV.check_text(set_xml(HEADERS["13"]).decode())
        with self.assertRaises(SystemExit) as cm:
            LV.guard_write_text(set_xml(HEADERS["13"]).decode())
        self.assertIn("saved by Live 13.0.2", str(cm.exception))
        self.assertEqual(LV.check_text(set_xml(HEADERS["13"]).decode(), force=True)[0], 13)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(LV.check_text("not a set"))                  # unreadable: a warning, not a refusal

    def test_every_writer_of_a_set_is_guarded_or_on_the_known_list(self):
        """A tool that gzips a new .als must call the version check. NOT_GUARDED_YET are the writers that do not yet:
        the list may only shrink (a writer that has the guard must come off it)."""
        import re
        root = Path(LV.__file__).resolve().parents[1]
        found = {}
        for py in sorted(root.rglob("*.py")):
            text = py.read_text()
            if re.search(r'gzip\.open\([^)]*,\s*["\']wb["\']\)|_gz\.open\([^)]*,\s*["\']wb["\']\)', text):
                found[str(py.relative_to(root))] = "liveversion" in text
        for rel, guarded in found.items():
            if rel in NOT_GUARDED_YET:
                self.assertFalse(guarded, f"{rel} is guarded now: take it off NOT_GUARDED_YET")
            else:
                self.assertTrue(guarded, f"{rel} writes a set without the Live version check")
        self.assertTrue({"session/automation.py"} <= set(found))
        self.assertLessEqual(NOT_GUARDED_YET - set(found), set(), "a listed writer no longer writes sets")

    def test_the_flag_on_a_command_sets_the_allowance(self):
        import argparse
        ap = argparse.ArgumentParser()
        LV.add_force_flag(ap)
        self.assertFalse(ap.parse_args([]).force_live_version)
        self.assertFalse(LV.forced())
        self.assertTrue(ap.parse_args(["--force-live-version"]).force_live_version)
        self.assertTrue(LV.forced())
        self.assertEqual(os.environ[LV.ENV_FORCE], "1")                  # tools this run starts see it too

    def test_the_offset_command_takes_the_flag(self):
        import subprocess, sys
        r = subprocess.run([sys.executable, "-m", "hypnomix.session.automation", "offset", "-h"],
                           capture_output=True, text=True)
        self.assertIn("--force-live-version", r.stdout)


class ReadingNewerSets(Tmp):
    def test_reading_warns_once_and_never_refuses(self):
        newer = write_set(self.td / "n.als", "13")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(LV.warn_read(newer)[0], 13)
            self.assertEqual(LV.warn_read(ET.fromstring(set_xml(HEADERS["13"])))[0], 13)       # the same set again
            LV.warn_read(write_set(self.td / "o.als", "12"))
            LV.warn_read(write_set(self.td / "u.als", "none"))
            LV.warn_read(self.td / "missing.als")
        lines = err.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1)
        for text in ("saved by Live 13.0.2", "tested up to Live 12", "Reading and scanning work"):
            self.assertIn(text, lines[0])

    def test_project_read_of_a_newer_set_warns_and_reads(self):
        from hypnomix.project import als as ALS
        p = write_set(self.td / "n.als", "13")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            proj = ALS.read(p)
        self.assertEqual(proj.daw, "live")
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1)
        self.assertIn("Live 13.0.2", err.getvalue())

    def test_scan_warns_about_a_newer_set_and_goes_on(self):
        import subprocess, sys
        p = write_set(self.td / "n.als", "13")
        r = subprocess.run([sys.executable, "-m", "hypnomix.cli", "scan", str(p), "--quick", "--out", str(self.td / "scan")],
                           capture_output=True, text=True, env=dict(os.environ, HYPNOMIX_HOME=str(self.td / "home")))
        self.assertEqual(r.stderr.count("saved by Live 13.0.2"), 1, r.stderr[-800:])
        self.assertIn("scanning n.als", r.stdout)


if __name__ == "__main__":
    unittest.main()
