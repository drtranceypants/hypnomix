"""The test run keeps off the person's own folders, and says what it cannot test.

The name sorts first on purpose: `python -m unittest discover -s tests` imports the test files in alphabetical order and
does not import tests/__init__.py, so this file is what moves the whole run onto temporary folders before any other
test imports hypnomix (hypnomix/core/paths.py reads HYPNOMIX_HOME and HYPNOMIX_OUT when it is first imported)."""
try:
    from tests import _isolate                  # `python -m unittest tests.test_x`, or discover from the repository folder
except ImportError:
    import _isolate                             # discover -s tests, started from another folder

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
CLEAN = ("HYPNOMIX_HOME", "HYPNOMIX_APP_HOME", "HYPNOMIX_USER_HOME", "HYPNOMIX_OUT", _isolate.MARK)


def run_in_clean_environment(code, home):
    """Run `code` in a new Python with none of the isolation variables set and `home` as the home folder."""
    env = {k: v for k, v in os.environ.items() if k not in CLEAN}
    env.update(HOME=str(home), USERPROFILE=str(home))
    return subprocess.run([sys.executable, "-c", code], cwd=str(REPO), env=env, capture_output=True, text=True, timeout=120)


class Isolation(unittest.TestCase):
    def test_this_run_is_isolated(self):
        for name in _isolate.FOLDERS:
            self.assertTrue(os.environ.get(name), name + " is not set")
        self.assertTrue(os.environ.get(_isolate.MARK))
        from hypnomix.core import paths
        self.assertEqual(paths.HOME, Path(os.environ["HYPNOMIX_HOME"]).expanduser())
        self.assertEqual(paths.OUT, Path(os.environ["HYPNOMIX_OUT"]).expanduser())
        self.assertTrue(Path(os.environ["HYPNOMIX_USER_HOME"]).is_dir(), "the user-home folder must exist")

    def test_unset_variables_go_to_a_temporary_folder_and_it_is_removed_afterwards(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t) / "home"
            home.mkdir()
            code = ("import json, os, tempfile, tests\n"
                    "from pathlib import Path\n"
                    "tempfile.mkdtemp()\n"                                    # left behind on purpose: it must go with the rest
                    "from hypnomix.core import paths\n"
                    "names = ('HYPNOMIX_HOME','HYPNOMIX_APP_HOME','HYPNOMIX_USER_HOME','HYPNOMIX_OUT','HOME')\n"
                    "print(json.dumps(dict({n: os.environ[n] for n in names}, home=str(Path.home()), out=str(paths.OUT),"
                    " tmp=tempfile.gettempdir(),"
                    " root=os.environ['HYPNOMIX_TESTS_ROOT'])))\n")
            r = run_in_clean_environment(code, home)
            self.assertEqual(r.returncode, 0, r.stderr)
            got = json.loads(r.stdout.strip().splitlines()[-1])
            root = Path(got["root"])
            got["TMP"] = got["tmp"]
            for name in ("HYPNOMIX_HOME", "HYPNOMIX_APP_HOME", "HYPNOMIX_USER_HOME", "HYPNOMIX_OUT", "HOME", "TMP"):
                self.assertIn(str(root.resolve()), [str(p) for p in [Path(got[name]).resolve(), *Path(got[name]).resolve().parents]],
                              f"{name} = {got[name]} is not inside {root}")
            self.assertNotEqual(Path(got["home"]).resolve(), home.resolve(), "the home folder was not moved")
            self.assertTrue(Path(got["out"]).is_absolute(), "the default output folder must not be ./hypnomix-out")
            self.assertFalse(root.exists(), "the temporary folder is removed when the run ends")
            self.assertEqual(list(home.iterdir()), [], "nothing may be written into the real home folder")

    def test_a_folder_the_person_set_is_kept(self):
        with tempfile.TemporaryDirectory() as t:
            home, mine = Path(t) / "home", Path(t) / "mine"
            home.mkdir()
            mine.mkdir()
            code = "import os, tests; print(os.environ['HYPNOMIX_HOME']); print(os.environ['HOME'])"
            env = {k: v for k, v in os.environ.items() if k not in CLEAN}
            env.update(HOME=str(home), HYPNOMIX_HOME=str(mine), HYPNOMIX_USER_HOME=str(home))
            r = subprocess.run([sys.executable, "-c", code], cwd=str(REPO), env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.split(), [str(mine), str(home)])     # their folder, and HOME left alone

    def test_a_run_writes_nothing_into_the_working_folder_or_home(self):
        """The whole point: a command that writes to its default places lands in the temporary folders."""
        with tempfile.TemporaryDirectory() as t:
            home = Path(t) / "home"
            home.mkdir()
            code = ("import tests\n"
                    "from hypnomix.core import paths\n"
                    "from hypnomix.app import chat, server\n"
                    "paths.out('scan')\n"
                    "paths.write_private(paths.HOME / 'x.json', '{}')\n"
                    "server.work().mkdir(parents=True, exist_ok=True)\n")
            before = set(p.name for p in REPO.iterdir())
            r = run_in_clean_environment(code, home)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(list(home.iterdir()), [])
            self.assertEqual(set(p.name for p in REPO.iterdir()), before, "something appeared in the repository folder")

    def test_the_developers_own_keys_and_addresses_are_taken_out(self):
        """A test that passes only because the developer's GEMINI_API_KEY is set fails everywhere else."""
        with tempfile.TemporaryDirectory() as t:
            home = Path(t) / "home"
            home.mkdir()
            names = ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL", "GITHUB_TOKEN", "HYPNOMIX_ENGINE_URL", "HYPNOMIX_PORT")
            code = ("import os, tests\n"
                    f"print([n for n in {names!r} if n in os.environ])\n")
            env = {k: v for k, v in os.environ.items() if k not in CLEAN}
            env.update(HOME=str(home), **{n: "x" for n in names})
            r = subprocess.run([sys.executable, "-c", code], cwd=str(REPO), env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip().splitlines()[-1], "[]")


class Notice(unittest.TestCase):
    def test_a_missing_extra_is_named(self):
        with mock.patch.object(_isolate.importlib.util, "find_spec", return_value=None):
            lines = _isolate.notice()
        self.assertTrue(any("'assistant' extra" in l and "SKIPPED" in l and ".[assistant]" in l for l in lines), lines)

    def test_a_missing_tool_is_named(self):
        with mock.patch.object(_isolate.shutil, "which", return_value=None):
            lines = _isolate.notice()
        for tool in ("rubberband", "ffmpeg", "node"):
            self.assertTrue(any(l.startswith(f"tests: {tool} is not installed") for l in lines), (tool, lines))

    def test_nothing_is_said_when_everything_is_there(self):
        with mock.patch.object(_isolate.importlib.util, "find_spec", return_value=object()), \
                mock.patch.object(_isolate.shutil, "which", return_value="/usr/bin/x"):
            self.assertEqual(_isolate.notice(), [])


if __name__ == "__main__":
    unittest.main()
