"""Bad inputs to the newest CLI commands (`import`, `reaper snapshot` / `restore` / `diff`, `reaper loop`, and
`vocallevel`) end in one plain sentence on stderr and a non-zero exit code, never a Python traceback.

Every subprocess runs with its own temporary HOME, HYPNOMIX_HOME, HYPNOMIX_APP_HOME and HYPNOMIX_REAPER_DIR,
HYPNOMIX_DISKCARE=off, tiny text fixtures (a few bytes each), and never starts REAPER, Live or an engine. The REAPER
cases also check that the bridge folder is never created, confirming each refusal happens before contacting REAPER.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BAD_TOKENS = (
    "Traceback",
    'File "',
    "FileNotFoundError",
    "IsADirectoryError",
    "NotADirectoryError",
    "JSONDecodeError",
    "ValueError:",
    "KeyError:",
    "TypeError:",
    "AttributeError:",
    "OSError:",
    "RuntimeError:",
)


def env_for(base):
    base = Path(base)
    env = dict(os.environ)
    for key, sub in (
        ("HOME", "home"),
        ("USERPROFILE", "home"),
        ("HYPNOMIX_HOME", "hx"),
        ("HYPNOMIX_APP_HOME", "app"),
        ("HYPNOMIX_USER_HOME", "home"),
    ):
        (base / sub).mkdir(exist_ok=True)
        env[key] = str(base / sub)
    env["HYPNOMIX_DISKCARE"] = "off"
    env["HYPNOMIX_REAPER_DIR"] = str(base / "reaper-bridge")
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.pop("HYPNOMIX_OUT", None)
    env.pop("HYPNOMIX_DEBUG", None)
    return env


def run_cli(base, *args):
    """Run `hypnomix ...` in an isolated subprocess; -> (returncode, stdout, stderr)."""
    r = subprocess.run(
        [sys.executable, "-m", "hypnomix.cli", *[str(a) for a in args]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env_for(base),
        cwd=str(base),
        timeout=60,
    )
    return r.returncode, r.stdout, r.stderr


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.d = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def assert_one_sentence_error(self, args, expect=None, check_no_reaper=False):
        rc, out, err = run_cli(self.d, *args)
        self.assertIn(rc, (1, 2), (args, rc, out, err))
        self.assertEqual(out, "", (args, out, err))
        lines = [line for line in err.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, (args, err))
        for bad in BAD_TOKENS:
            self.assertNotIn(bad, err, (args, bad, err))
        if expect is not None:
            self.assertIn(expect, lines[0], (args, err))
        if check_no_reaper:
            self.assertFalse((self.d / "reaper-bridge").exists(), (args, "contacted REAPER bridge"))
        return rc, lines[0]


class ImportErrors(Base):
    def _minimal_rpp(self, name="Song.rpp"):
        p = self.d / name
        p.write_text('<REAPER_PROJECT 0.1 "7.86" 1\n>\n', encoding="utf-8")
        return p

    def test_missing_path(self):
        out = self.d / "imported"
        self.assert_one_sentence_error(("import", self.d / "missing.rpp", out), expect="no such project")
        self.assertFalse(out.exists())

    def test_folder_where_file_is_expected(self):
        folder = self.d / "not_a_file"
        folder.mkdir()
        out_reaper = self.d / "out_reaper"
        self.assert_one_sentence_error(
            ("import", folder, out_reaper, "--from", "reaper"),
            expect="a folder",
        )
        self.assertFalse(out_reaper.exists())
        out_live = self.d / "out_live"
        self.assert_one_sentence_error(
            ("import", folder, out_live, "--from", "live"),
            expect="a folder",
        )
        self.assertFalse(out_live.exists())
        out_bare = self.d / "out_bare"
        self.assert_one_sentence_error(
            ("import", folder, out_bare),
            expect="not a project this can import",
        )
        self.assertFalse(out_bare.exists())

    def test_unsupported_file_type(self):
        txt = self.d / "notes.txt"
        txt.write_text("plain text, not a project\n", encoding="utf-8")
        out = self.d / "out_txt"
        self.assert_one_sentence_error(("import", txt, out), expect="not a project this can import")
        self.assertFalse(out.exists())

    def test_existing_output_folder_is_refused_and_untouched(self):
        rpp = self._minimal_rpp()
        existing = self.d / "existing_session"
        existing.mkdir()
        keep = existing / "keep.txt"
        keep.write_text("keep", encoding="utf-8")
        self.assert_one_sentence_error(("import", rpp, existing), expect="already exists")
        self.assertEqual(keep.read_text(encoding="utf-8"), "keep")

    def test_existing_file_as_output_folder_is_refused_and_untouched(self):
        rpp = self._minimal_rpp()
        existing_file = self.d / "already_a_file"
        existing_file.write_text("keep", encoding="utf-8")
        self.assert_one_sentence_error(("import", rpp, existing_file), expect="is a file, not a folder")
        self.assertEqual(existing_file.read_text(encoding="utf-8"), "keep")


class ReaperSnapshotErrors(Base):
    def _valid_snap(self, name="good.json"):
        p = self.d / name
        p.write_text('{"tracks": []}\n', encoding="utf-8")
        return p

    def _bad_json(self, name="broken.json"):
        p = self.d / name
        p.write_text("not json {{{\n", encoding="utf-8")
        return p

    def test_snapshot_existing_output_file_is_refused_before_reaper(self):
        existing = self.d / "mix.json"
        existing.write_text("keep", encoding="utf-8")
        self.assert_one_sentence_error(
            ("reaper", "snapshot", existing),
            expect="already exists",
            check_no_reaper=True,
        )
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep")

    def test_snapshot_existing_output_folder_is_refused_before_reaper(self):
        existing_dir = self.d / "mix_dir"
        existing_dir.mkdir()
        self.assert_one_sentence_error(
            ("reaper", "snapshot", existing_dir),
            expect="already exists",
            check_no_reaper=True,
        )

    def test_snapshot_restore_missing_file_before_reaper(self):
        self.assert_one_sentence_error(
            ("reaper", "snapshot", "restore", self.d / "missing.json"),
            expect="no such file",
            check_no_reaper=True,
        )

    def test_snapshot_restore_non_json_file_before_reaper(self):
        bad = self._bad_json()
        self.assert_one_sentence_error(
            ("reaper", "snapshot", "restore", bad),
            expect="not a readable snapshot",
            check_no_reaper=True,
        )

    def test_snapshot_restore_json_without_tracks_before_reaper(self):
        empty_obj = self.d / "empty.json"
        empty_obj.write_text("{}\n", encoding="utf-8")
        self.assert_one_sentence_error(
            ("reaper", "snapshot", "restore", empty_obj),
            expect="no mixer snapshot",
            check_no_reaper=True,
        )

    def test_snapshot_diff_missing_file_before_reaper(self):
        good = self._valid_snap()
        self.assert_one_sentence_error(
            ("reaper", "snapshot", "diff", self.d / "missing.json", good),
            expect="no such file",
            check_no_reaper=True,
        )
        self.assert_one_sentence_error(
            ("reaper", "snapshot", "diff", good, self.d / "missing.json"),
            expect="no such file",
            check_no_reaper=True,
        )

    def test_snapshot_diff_non_json_file_before_reaper(self):
        good = self._valid_snap()
        bad = self._bad_json()
        self.assert_one_sentence_error(
            ("reaper", "snapshot", "diff", bad, good),
            expect="not a readable snapshot",
            check_no_reaper=True,
        )
        self.assert_one_sentence_error(
            ("reaper", "snapshot", "diff", good, bad),
            expect="not a readable snapshot",
            check_no_reaper=True,
        )


class ReaperLoopErrors(Base):
    def test_bars_given_as_text_refused_before_reaper(self):
        for bad in ("abc", "a-b", "one-four", "1.5-3.5"):
            self.assert_one_sentence_error(
                ("reaper", "loop", "--bars", bad),
                expect="whole numbers",
                check_no_reaper=True,
            )

    def test_secs_start_after_or_equal_to_end_refused_before_reaper(self):
        for bad in ("80-60", "60-60"):
            self.assert_one_sentence_error(
                ("reaper", "loop", "--secs", bad),
                expect="end comes after the start",
                check_no_reaper=True,
            )


class VocalLevelErrors(Base):
    def test_missing_project(self):
        for name in ("missing.rpp", "missing.als"):
            self.assert_one_sentence_error(("vocallevel", self.d / name), expect="no such file")

    def test_folder_that_is_not_a_session(self):
        folder = self.d / "plain_folder"
        folder.mkdir()
        self.assert_one_sentence_error(("vocallevel", folder), expect="is a folder")

    def test_apply_to_existing_rpp_is_refused_and_untouched(self):
        src = self.d / "Song.rpp"
        src.write_text('<REAPER_PROJECT 0.1 "7.86" 1\n>\n', encoding="utf-8")
        existing = self.d / "existing.rpp"
        existing.write_text("keep", encoding="utf-8")
        self.assert_one_sentence_error(("vocallevel", src, "--apply", existing), expect="already exists")
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep")

    def test_apply_to_existing_als_is_refused_and_untouched(self):
        src = self.d / "Song.als"
        src.write_bytes(b"placeholder")
        heard = self.d / "heard"
        heard.mkdir()
        existing = self.d / "existing.als"
        existing.write_text("keep", encoding="utf-8")
        self.assert_one_sentence_error(
            ("vocallevel", src, "--heard", heard, "--apply", existing),
            expect="already exists",
        )
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep")

    def test_apply_same_path_as_source_is_refused_and_untouched(self):
        src = self.d / "Song.rpp"
        body = '<REAPER_PROJECT 0.1 "7.86" 1\n>\n'
        src.write_text(body, encoding="utf-8")
        self.assert_one_sentence_error(
            ("vocallevel", src, "--apply", src),
            expect="refusing to overwrite the original",
        )
        self.assertEqual(src.read_text(encoding="utf-8"), body)


if __name__ == "__main__":
    unittest.main()
