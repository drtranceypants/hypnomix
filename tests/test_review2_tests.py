"""Second review of reaper-parity-031, finding 23 and the small items the other fixes left outside their files:
the REAPER tests open every text file as UTF-8 and run every class when run directly; a scan never reads an
earlier scan's vocallevel.json; a "(BROKEN, do not open)" or "(FAILED check)" rename and `reaper probes insert`
never replace an earlier file; Live's `loop` cleans a take's label for its file name as REAPER's does; and the
docs say what the fixes changed."""
import ast
import json
import re
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def reaper_tests():
    names = [*TESTS.glob("test_reaper*.py"), *TESTS.glob("test_review_fixes*.py"), *TESTS.glob("test_review2*.py"),
             TESTS / "test_vocallevel_reaper.py"]
    return sorted(set(names))


class TestFiles(unittest.TestCase):
    def test_every_text_open_names_its_encoding(self):
        bad = []
        for f in reaper_tests():
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if not isinstance(n, ast.Call):
                    continue
                name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                kws = {k.arg for k in n.keywords}
                if name in ("read_text", "write_text") and "encoding" not in kws:
                    bad.append(f"{f.name}:{n.lineno} {name}")
                if name == "open" and "encoding" not in kws:
                    mode = n.args[1].value if len(n.args) > 1 and isinstance(n.args[1], ast.Constant) else "r"
                    if "b" not in str(mode):
                        bad.append(f"{f.name}:{n.lineno} open")
        self.assertEqual(bad, [], "bridge.lua and other files hold non-ASCII text: name encoding='utf-8'")

    def test_the_main_guard_comes_after_every_class(self):
        for f in reaper_tests():
            tree = ast.parse(f.read_text(encoding="utf-8"))
            guard = next((n.lineno for n in tree.body if isinstance(n, ast.If) and "__main__" in ast.unparse(n.test)),
                         None)
            if guard is None:
                continue
            last = max((n.lineno for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))), default=0)
            self.assertGreater(guard, last, f"{f.name}: run directly, the classes after the guard are skipped")


class ScanReadsOnlyItsOwnVocallevel(unittest.TestCase):
    """vocallevel never overwrites its --json, so the scan deletes the earlier scan's file first: otherwise the
    check refuses, and the scan reads the old findings as new."""
    def test_unlinked_before_the_check_runs(self):
        for rel in ("hypnomix/workflow/scan.py", "hypnomix/workflow/scan_project.py"):
            src = (ROOT / rel).read_text(encoding="utf-8")
            m = re.search(r'j = od / "raw" / "vocallevel\.json"\n(.*?)hx\(\*args\)', src, re.S)
            self.assertIsNotNone(m, rel)
            self.assertIn("j.unlink(missing_ok=True)", m.group(1), rel)


class RenamesNeverReplace(unittest.TestCase):
    FILES = ("hypnomix/workflow/handoff.py", "hypnomix/engineer/masking.py", "hypnomix/studio/alignset_rpp.py",
             "hypnomix/workflow/fix_project.py", "hypnomix/workflow/vocallevel_project.py")

    def test_every_broken_name_is_a_free_one(self):
        for rel in self.FILES:
            lines = [ln for ln in (ROOT / rel).read_text(encoding="utf-8").splitlines()
                     if "with_name(" in ln and ("(BROKEN, do not open)" in ln or "(FAILED check)" in ln)]
            self.assertTrue(lines, rel)
            for ln in lines:
                self.assertIn("free_name(", ln, f"{rel}: {ln.strip()}")

    def test_probes_insert_twice_keeps_the_first(self):
        from hypnomix.reaper import probes
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "Song.rpp"
            src.write_text('<REAPER_PROJECT 0.1 "7.86/macOS-arm64" 1\n  TEMPO 120 4 4\n'
                           '  <TRACK {0D7A5C2E-1111-4222-8333-944455556666}\n    NAME "Lead"\n  >\n>\n',
                           encoding="utf-8")
            first, _ = probes.insert(src)
            kept = first.read_bytes()
            second, _ = probes.insert(src)
            self.assertEqual(first.name, "Song (probes).rpp")
            self.assertEqual(second.name, "Song (probes) 2.rpp")
            self.assertEqual(first.read_bytes(), kept)
            other = Path(td) / "mine.rpp"
            other.write_text("keep", encoding="utf-8")
            with self.assertRaises(SystemExit):                # an --out the person names is never replaced
                probes.insert(src, other)
            self.assertEqual(other.read_text(encoding="utf-8"), "keep")


class LiveLoopLabel(unittest.TestCase):
    def test_label_cleaned_for_the_file_only(self):
        from hypnomix.live import loop as L

        class Rec:
            def wait(self):
                pass

        def record(secs, wav, *a):
            Path(wav).write_bytes(b"")
            return Rec()

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(L, "record", side_effect=record), \
                mock.patch.object(L, "trim_silence", return_value=1.0), \
                mock.patch.object(L, "measure", return_value={}), \
                mock.patch.object(L, "audio_metrics", return_value={"integrated_lufs": -14.0}):
            folder = Path(td) / "takes"
            folder.mkdir()
            a = Namespace(no_play=True, secs=1.0, device=None, channels=2, bar=1, bars=1)
            w1, _ = L.take(None, a, folder, "a/b")
            w2, _ = L.take(None, a, folder, "../../escape")
            self.assertEqual(w1.name, "01-a-b.wav")
            self.assertEqual(w2.name, "02-escape.wav")
            self.assertEqual(w2.parent, folder)
            self.assertEqual(json.loads(w1.with_suffix(".json").read_text(encoding="utf-8"))["label"], "a/b")


class DocsSayWhatChanged(unittest.TestCase):
    def read(self, rel):
        return re.sub(r"\s+", " ", (ROOT / rel).read_text(encoding="utf-8"))

    def test_guide_08(self):
        g = self.read("docs/guides/08-inside-reaper.md")
        self.assertIn("stopping `hypnomix reaper review` (or closing the panel) leaves the whole project on A", g)
        self.assertIn("space plays and stops, and Esc closes the guide when it is showing, otherwise the panel", g)
        self.assertIn("`snapshot diff` works on two takes' `.json` too", g)
        self.assertIn("`--revert` (only together with `--ab`)", g)
        self.assertNotIn("and closing the panel leaves the whole project on A", g)

    def test_lesson(self):
        from hypnomix.app.lessons import ch13_hypnomix
        text = (ROOT / "hypnomix/app/lessons/ch13_hypnomix.py").read_text(encoding="utf-8")
        self.assertIn("stopping `hypnomix reaper review` (or closing the panel)", text)
        self.assertTrue(ch13_hypnomix)

    def test_vocallevel_refusals(self):
        for rel in ("docs/REAPER.md", "docs/guides/04-vocal-production.md",
                    "hypnomix/app/wiki/articles/26-features.html"):
            t = self.read(rel)
            self.assertIn("the original under any spelling of its name", t, rel)
            self.assertIn("left exactly as they are", t, rel)
            self.assertIn("above +6 dB", t, rel)
        self.assertIn("above +6 dB", self.read("hypnomix/app/wiki/articles/25-chores.html"))

    def test_vocallevel_help_says_what_ran(self):
        doc = self.read("hypnomix/workflow/vocallevel_project.py")
        self.assertNotIn("has not been opened in REAPER yet", doc)
        self.assertIn("opened in REAPER 7.86 on a two-track test project and read back (106 points", doc)

    def test_reacomp_mix_and_master(self):
        for rel in ("docs/REAPER.md", "hypnomix/app/wiki/articles/25-chores.html",
                    "hypnomix/app/wiki/articles/26-features.html"):
            t = self.read(rel)
            self.assertIn("parallel compression", t, rel)
            self.assertIn("Wet at 0", t, rel)
            self.assertRegex(t, r"(?i)(master track's plug-ins|plug-ins on the master track) are not read", rel)

    def test_bridge_and_panels(self):
        t = self.read("docs/REAPER.md")
        self.assertIn("a `busy` file next to `alive`", t)
        self.assertIn("a second `hypnomix reaper start` replaces the running bridge", t)
        self.assertIn("WIDTH (L/R) and LOW END (<120 Hz)", t)

    def test_cli_help(self):
        t = self.read("hypnomix/reaper/cli.py")
        self.assertIn("An existing OUT.json is refused", t)
        self.assertIn("--revert (only with --ab)", t)
        self.assertIn("within -150 to +12 dB", t)

    def test_probe_protect_step_is_true(self):
        t = (ROOT / "hypnomix/reaper/jsfx/hypnomix_probe.jsfx").read_text(encoding="utf-8")
        self.assertNotIn("no change to this track is applied without asking you again", t)
        self.assertIn("Scan and fix on a REAPER project do not read it yet: set protect.tracks in Preferences", t)

    def test_probe_comment_casing(self):
        self.assertNotIn("the Hypnomix Probe / Main JSFX", (ROOT / "hypnomix/app/probe.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
