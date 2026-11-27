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


# gzip writes under hypnomix/ that are NOT a Live set (so need no version check), as {"relative/path.py": "why"}.
# Every other gzip write must call the Live version guard in the same function.
NOT_SETS = {
    "app/server.py": "gzip_body() compresses an HTTP answer for a browser that accepts it; no set is written",
    "app/engine_addon.py": "pack() writes a tar.gz of an engine kit for the add-on; no Live set is involved",
    "app/wiki.py": "go() only unpacks a downloaded answer (GzipFile on bytes it read); no set is written",
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

    def test_every_gzip_write_of_a_set_calls_the_version_guard(self):
        """Greps the whole package: a function that gzips a new .als must call the Live version check in the same
        function (guard_write, guard_write_text, check_write, check_text or check_file). A write that is not a set
        goes on NOT_SETS with its reason. Reading a set needs no check (it only warns)."""
        import ast
        root = Path(LV.__file__).resolve().parents[1]
        guards = ("guard_write", "guard_write_text", "check_write", "check_text", "check_file")

        def gzip_name(n):
            return isinstance(n, ast.Name) and n.id in ("gzip", "_gz", "gz")

        def writes(call):
            f = call.func
            if not (isinstance(f, ast.Attribute) and gzip_name(f.value)):
                return False
            if f.attr in ("compress", "GzipFile"):
                return True
            if f.attr == "open":
                mode = call.args[1] if len(call.args) > 1 else next((k.value for k in call.keywords if k.arg == "mode"), None)
                if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
                    return any(c in mode.value for c in "wax")
                return mode is not None                 # a mode held in a variable cannot be read here: guard it
            return False

        found = {}
        for py in sorted(root.rglob("*.py")):
            rel = str(py.relative_to(root))
            text = py.read_text()
            if "gzip" not in text:
                continue
            tree = ast.parse(text)
            self.assertNotRegex(text, r"import gzip as (?!_gz\b)", f"{rel}: import gzip under its own name so the guard test can see it")
            self.assertNotRegex(text, r"from gzip import", f"{rel}: use `import gzip` so the guard test can see the write")
            parent = {id(c): n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}

            def enclosing(node):
                while id(node) in parent:
                    node = parent[id(node)]
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        return node
                return tree                             # a write at module level: the whole file must hold the guard

            for call in [c for c in ast.walk(tree) if isinstance(c, ast.Call) and writes(c)]:
                fn = enclosing(call)
                guarded = any(isinstance(c, ast.Call) and getattr(c.func, "attr", "") in guards for c in ast.walk(fn))
                found.setdefault(rel, []).append((getattr(fn, "name", "<module>"), guarded))
        for rel, fns in found.items():
            if rel in NOT_SETS:
                continue
            for name, guarded in fns:
                self.assertTrue(guarded, f"{rel}: {name}() gzips a set without calling the Live version guard "
                                         f"(add LV.guard_write(root) before the write, or list the file in NOT_SETS with a reason)")
        self.assertTrue({"session/automation.py", "workflow/fix.py", "workflow/oversight.py", "workflow/abset.py"} <= set(found))
        self.assertEqual(set(NOT_SETS) - set(found), set(), "a listed file no longer writes gzip")

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


class EveryWriterRefuses(Tmp):
    """The tools that write a set with their own code, not through automation.save: a Live 13 set is refused, and
    --force-live-version (or the environment variable) lets it through, also in the tools `fix` runs."""

    def tree13(self):
        x = set_xml(HEADERS["13"]).replace(b"<Tracks/>", b"<Tracks/><Tempo><Manual Value=\"120\"/></Tempo>")
        return ET.ElementTree(ET.fromstring(x))

    def test_abset_save_refuses_and_writes_nothing(self):
        from hypnomix.workflow import abset
        with self.assertRaises(SystemExit) as cm:
            abset.save(self.tree13(), self.td / "out.als")
        self.assertIn("saved by Live 13.0.2", str(cm.exception))
        self.assertFalse((self.td / "out.als").exists())
        with mock.patch.dict(os.environ, {LV.ENV_FORCE: "1"}):
            abset.save(self.tree13(), self.td / "forced.als")
        self.assertTrue((self.td / "forced.als").exists())

    def test_rename_and_blend_refuse(self):
        from hypnomix.session import names
        from hypnomix.workflow import oversight
        src = write_set(self.td / "s13.als", "13")
        with self.assertRaises(SystemExit):
            names.rename_set(src, self.td / "renamed.als", {})
        self.assertFalse((self.td / "renamed.als").exists())
        with self.assertRaises(SystemExit):
            oversight.blend(src, src, self.td / "blend.als", 0.5)
        self.assertFalse((self.td / "blend.als").exists())

    def test_a_tool_command_refuses_then_takes_the_flag_and_fix_passes_it_on(self):
        import subprocess, sys
        from hypnomix.workflow import fix
        x = set_xml(HEADERS["13"]).replace(b"<Tracks/>", b"<Tracks/><Tempo><Manual Value=\"120\"/></Tempo>")
        src = self.td / "s13.als"
        with gzip.open(src, "wb") as f:
            f.write(x)
        base = [sys.executable, "-m", "hypnomix.cli", "unroll", str(src), "--track", "X"]
        r = subprocess.run(base + ["--apply", str(self.td / "a.als")], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("saved by Live 13.0.2", r.stdout + r.stderr)
        self.assertFalse((self.td / "a.als").exists())
        r = subprocess.run(base + ["--apply", str(self.td / "b.als"), "--force-live-version"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.td / "b.als").exists())
        # `fix` runs its tools as child processes: its own flag reaches them through the environment
        code, out = fix.hx("unroll", src, "--track", "X", "--apply", self.td / "c.als")
        self.assertNotEqual(code, 0)
        self.assertIn("saved by Live 13.0.2", out)
        LV.allow()
        code, out = fix.hx("unroll", src, "--track", "X", "--apply", self.td / "d.als")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.td / "d.als").exists())

    def test_every_set_writing_command_lists_the_flag_in_its_help(self):
        import subprocess, sys
        for cmd in ("fix", "unroll", "tidy", "order", "edges", "cliplevel", "motion", "borrow", "duck", "devices",
                    "sidechain", "name", "vocallevel", "abset", "smooth", "timing", "masking", "distortion", "voices",
                    "tempomap", "breathe", "loops", "tighten", "colour", "alignset", "variations"):
            r = subprocess.run([sys.executable, "-m", "hypnomix.cli", cmd, "--help"], capture_output=True, text=True)
            self.assertIn("--force-live-version", r.stdout, f"hypnomix {cmd} --help does not list the flag")


if __name__ == "__main__":
    unittest.main()
