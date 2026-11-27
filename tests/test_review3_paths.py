"""Review 3, project paths and writes: a missing or folder project path gives one sentence (exit 2), not a crash
report; a failed write leaves no partial file; a file that appears between the check and the write is never replaced."""
import contextlib
import errno
import gzip
import io
import json
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from hypnomix import cli
from hypnomix.project import rpp
from hypnomix.session import vocallevel as VL

RPP = '<REAPER_PROJECT 0.1 "7.0" 1700000000\n  TEMPO 120 4 4\n  <TRACK\n    NAME "Lead"\n  >\n>\n'


def run_cli(argv):
    """(exit code, stderr) of hypnomix.cli.main(argv)."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        try:
            cli.main(argv)
            code = 0
        except SystemExit as e:
            code = e.code
    return code, err.getvalue()


class MissingProject(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)
        self.missing = str(self.d / "none.rpp")
        self.folder = self.d / "dir.rpp"
        self.folder.mkdir()
        self.findings = self.d / "F.json"
        self.findings.write_text(json.dumps({"findings": [{"id": "mask-1", "tool": "masking", "eq": {"a": 1}}]}),
                                 encoding="utf-8")

    def tearDown(self):
        self.td.cleanup()

    def commands(self, p):
        return {
            "masking": ["masking", p, "--findings", str(self.findings), "--ids", "mask-1", "--apply", str(self.d / "z.rpp")],
            "alignset": ["alignset", p, "--guide", "A", "--parts", "B", "--out", str(self.d / "OUT"), "--apply"],
            "probes insert": ["reaper", "probes", "insert", p],
            "probes cards": ["reaper", "probes", "cards", p],
        }

    def test_missing_rpp_is_one_sentence(self):
        for name, argv in self.commands(self.missing).items():
            with self.subTest(name):
                code, err = run_cli(argv)
                self.assertEqual(code, 2, err)
                self.assertIn("no such file: ", err)
                self.assertIn("none.rpp; check the name and the folder, then try again.", err)
                self.assertNotIn("bug", err)

    def test_folder_named_rpp_is_one_sentence(self):
        for name, argv in self.commands(str(self.folder)).items():
            with self.subTest(name):
                code, err = run_cli(argv)
                self.assertEqual(code, 2, err)
                self.assertIn("dir.rpp is a folder, not a project file; give the .rpp file itself.", err)
                self.assertNotIn("bug", err)

    def test_folder_named_rpp_is_one_sentence_where_a_folder_opens_with_permission_denied(self):
        """Windows opens a folder with "permission denied" (PermissionError), not IsADirectoryError: read here the way
        Windows answers, the same sentence (on the CI's Windows runners it said "can't write to ...")."""
        real = Path.read_bytes

        def read_bytes(p):
            if p.is_dir():
                raise PermissionError(errno.EACCES, "Permission denied", str(p))
            return real(p)
        for name, argv in self.commands(str(self.folder)).items():
            with self.subTest(name), mock.patch.object(Path, "read_bytes", read_bytes):
                code, err = run_cli(argv)
                self.assertEqual(code, 2, err)
                self.assertIn("dir.rpp is a folder, not a project file; give the .rpp file itself.", err)
                self.assertNotIn("can't write", err)

    def test_vocallevel_missing_and_folder(self):
        code, err = run_cli(["vocallevel", self.missing])
        self.assertEqual(code, f"no such file: {self.missing}; check the name and the folder, then try again.")
        code, err = run_cli(["vocallevel", str(self.folder)])
        self.assertEqual(code, f"{self.folder} is a folder, not a project file; give the .rpp file itself.")

    def test_ardour_session_folder_still_passes_the_check(self):
        song = self.d / "Song"
        song.mkdir()
        (song / "Song.ardour").write_text("<Session/>", encoding="utf-8")
        VL.check_paths(Namespace(als=str(song), apply=None, json=None))       # no SystemExit
        VL.check_paths(Namespace(als=str(song / "Song.ardour"), apply=None, json=None))

    def test_mapper_suffixes_only(self):
        m = cli._audio_read_message
        self.assertEqual(m(FileNotFoundError(errno.ENOENT, "No such file", "a/B.RPP-BAK")),
                         "no such file: a/B.RPP-BAK; check the name and the folder, then try again.")
        self.assertEqual(m(IsADirectoryError(errno.EISDIR, "Is a directory", "a/S.ardour")),
                         "a/S.ardour is a folder, not a project file; give the .ardour file itself.")
        self.assertIsNone(m(FileNotFoundError(errno.ENOENT, "No such file", "/x/model.onnx")))   # still a bug report
        self.assertIsNone(m(FileNotFoundError(errno.ENOENT, "No such file")))

    def test_read_only_message_names_no_option(self):
        msg = cli._audio_read_message(PermissionError(errno.EACCES, "Permission denied", "ro/New.rpp"))
        self.assertEqual(msg, "can't write to 'ro/New.rpp': permission denied; choose another place")


class _Failing:
    """A file whose write puts half the data down, then fails like a full disk (or Ctrl-C)."""

    def __init__(self, f, exc):
        self.f, self.exc = f, exc

    def write(self, data):
        self.f.write(data[: len(data) // 2])
        self.f.flush()
        raise self.exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.f.close()


class Writes(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)
        self.root = rpp.parse(RPP)

    def tearDown(self):
        self.td.cleanup()

    def failing_open(self, exc):
        real = open
        return lambda path, mode="r", **kw: _Failing(real(path, mode, **kw), exc)

    def test_rpp_save_failed_write_leaves_nothing(self):
        out = self.d / "New.rpp"
        for exc in (OSError(errno.ENOSPC, "No space left on device"), KeyboardInterrupt()):
            with self.subTest(type(exc).__name__):
                with mock.patch("hypnomix.project.rpp.open", self.failing_open(exc), create=True):
                    with self.assertRaises(type(exc)):
                        rpp.save(self.root, out)
                self.assertFalse(out.exists())
        self.assertEqual(rpp.save(self.root, out), out)                       # the name is free for the retry
        self.assertTrue(out.read_bytes().startswith(b"<REAPER_PROJECT"))

    def test_rpp_save_never_replaces_a_file_that_appears(self):
        out = self.d / "New.rpp"
        theirs = b"someone else's project\n"

        def check_passes_then_file_appears(o, src=None):
            Path(o).write_bytes(theirs)
            return Path(o)
        with mock.patch.object(rpp, "check_new", check_passes_then_file_appears):
            with self.assertRaises(SystemExit) as cm:
                rpp.save(self.root, out)
        self.assertIn("already exists", str(cm.exception.code))
        self.assertEqual(out.read_bytes(), theirs)

    def test_write_new_text_failed_write_leaves_nothing(self):
        out = self.d / "levels.json"
        with mock.patch("hypnomix.session.vocallevel.open", self.failing_open(OSError(errno.ENOSPC, "full")), create=True):
            with self.assertRaises(OSError):
                VL.write_new_text(out, "{}" * 100)
        self.assertFalse(out.exists())
        VL.write_new_text(out, "{}")
        self.assertEqual(out.read_text(encoding="utf-8"), "{}")

    def test_gzip_apply_failed_write_leaves_nothing(self):
        out = self.d / "New.als"
        f = gzip.open(out, "xb")
        with mock.patch.object(f, "write", side_effect=OSError(errno.ENOSPC, "full")):
            with self.assertRaises(OSError):
                VL._write_or_remove(f, out, b"<Ableton/>")
        self.assertFalse(out.exists())

    def test_gzip_apply_path_uses_the_cleanup(self):
        src = Path(VL.__file__).read_text(encoding="utf-8")
        self.assertIn('f = gzip.open(a.apply, "xb")', src)
        self.assertIn("_write_or_remove(f, a.apply, x.encode())", src)


if __name__ == "__main__":
    unittest.main()
