"""Windows and Linux portability: what a computer with another default text encoding, another folder layout or another
file manager must still get right. There is no Windows machine behind this file: Windows is simulated (a legacy default
encoding in a child process, patched platform names, ntpath-style paths), and each test says which part that is.

The legacy default encoding: a child Python run with LC_ALL=C, PYTHONUTF8=0 and PYTHONCOERCECLOCALE=0 opens files in
ASCII and prints in ASCII, which fails on every arrow and accent the way cp1252 fails on the arrow and CJK letters (and
silently writes cp1252 bytes for accents, which the tests read back as UTF-8).
"""
import ast
import contextlib
import errno
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "hypnomix"


def legacy_env(extra=None):
    """The environment of a computer whose default text encoding is not UTF-8."""
    env = dict(os.environ)
    env.update(LC_ALL="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0", PYTHONIOENCODING="cp1252", PYTHONPATH=str(ROOT))
    env.update(extra or {})
    return env


def run_legacy(code=None, args=None, env=None, timeout=240):
    cmd = [sys.executable, "-c", code] if code else [sys.executable, "-m", "hypnomix.cli", *args]
    return subprocess.run(cmd, capture_output=True, env=env or legacy_env(), timeout=timeout, cwd=str(ROOT))


def tone(path, seconds=1.0, sr=44100, freq=220.0, amp=0.3):
    t = np.arange(int(seconds * sr)) / sr
    sf.write(str(path), (amp * np.sin(2 * np.pi * freq * t)).astype("float32"), sr, subtype="PCM_16")


# ---------------------------------------------------------------- the class of bug: a source walk
def _atomic_aliases(tree):
    """Names that stand for hypnomix.core.atomic in a module (its write_text(path, text) is not Path.write_text)."""
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "hypnomix.core":
            names |= {a.asname or a.name for a in n.names if a.name == "atomic"}
        if isinstance(n, ast.Import):
            names |= {a.asname for a in n.names if a.name == "hypnomix.core.atomic" and a.asname}
    return names | {"atomic"}


def _kw(call, name):
    return any(k.arg == name for k in call.keywords)


def _mode(call, pos):
    """The mode of an open-like call: a string, "dynamic" (not a literal) or "r" (the default)."""
    m = "r"
    if len(call.args) > pos:
        a = call.args[pos]
        if not (isinstance(a, ast.Constant) and isinstance(a.value, str)):
            return "dynamic"
        m = a.value
    for k in call.keywords:
        if k.arg == "mode":
            if not (isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)):
                return "dynamic"
            m = k.value.value
    return m


MODE_LIKE = set("rwxa+bt")


def text_calls_without_encoding(path):
    """[(line, what)] for every text-mode open, read_text, write_text, os.fdopen, temporary file and text-mode
    subprocess call in the file that does not say which encoding it means."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    atomic = _atomic_aliases(tree)
    hits = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f, what = n.func, None
        if isinstance(f, ast.Name) and f.id == "open":
            m = _mode(n, 1)
            what = "open" if m == "dynamic" or "b" not in m else None
        elif isinstance(f, ast.Attribute):
            recv = f.value.id if isinstance(f.value, ast.Name) else ""
            if f.attr in ("read_text", "write_text") and recv not in atomic:
                what = f.attr
            elif f.attr == "fdopen" and recv == "os":
                m = _mode(n, 1)
                what = "os.fdopen" if m == "dynamic" or "b" not in m else None
            elif f.attr in ("TemporaryFile", "NamedTemporaryFile", "SpooledTemporaryFile") and recv == "tempfile":
                m = _mode(n, 0 if f.attr != "SpooledTemporaryFile" else 1) if f.attr == "TemporaryFile" else _mode(n, 0)
                what = "tempfile" if m == "dynamic" or "b" not in m and m != "w+b" else None
            elif f.attr == "open" and recv in ("", "p", "path", "f", "fp", "target", "src", "dst", "out", "tmp") \
                    and (not n.args or (isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)
                                        and set(n.args[0].value) <= MODE_LIKE)):
                m = _mode(n, 0)
                what = "Path.open" if m == "dynamic" or "b" not in m else None
        if what and not _kw(n, "encoding"):
            hits.append((n.lineno, what))
        for k in n.keywords:                  # subprocess: a text pipe decodes with the system's code page unless told
            if k.arg in ("text", "universal_newlines") and isinstance(k.value, ast.Constant) and k.value.value is True \
                    and not _kw(n, "encoding"):
                hits.append((n.lineno, "text=True"))
    return hits


class NoImplicitEncoding(unittest.TestCase):
    """Every text file hypnomix reads or writes, and every text pipe it reads, names its encoding. On Windows the
    default is the system's code page, which cannot hold an arrow, and silently writes accents the wrong way."""

    def sources(self):
        for p in sorted(PKG.rglob("*.py")):
            if "remote_script" in p.parts:        # AbletonOSC runs inside Live, on Live's own Python
                continue
            yield p
        launcher = ROOT / "packaging" / "windows" / "launcher.pyw"
        if launcher.exists():
            yield launcher

    def test_every_text_open_and_pipe_names_its_encoding(self):
        bad = [f"{p.relative_to(ROOT)}:{line}: {what}" for p in self.sources() for line, what in text_calls_without_encoding(p)]
        self.assertEqual(bad, [], "text-mode calls with no encoding (add encoding=\"utf-8\"):\n" + "\n".join(bad))

    def test_the_tests_name_their_encoding_too(self):
        """The same rule for tests/: a test that reads a UTF-8 page with the system's code page raised on Windows (cp1252
        has no byte 0x9d) or compared mojibake, and one that wrote a fixture that way gave the product a file it could not read."""
        bad = [f"{p.relative_to(ROOT)}:{line}: {what}" for p in sorted((ROOT / "tests").glob("*.py"))
               for line, what in text_calls_without_encoding(p)]
        self.assertEqual(bad, [], "text-mode calls with no encoding (add encoding=\"utf-8\"):\n" + "\n".join(bad))

    def test_the_walk_sees_what_it_should(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "m.py"
            f.write_text("import subprocess, os, tempfile\nfrom pathlib import Path\n"
                         "a = open('x')\nb = open('x', 'rb')\nc = open('x', 'w', encoding='utf-8')\n"
                         "d = Path('x').read_text()\ne = Path('x').write_text('t')\nsubprocess.run(['x'], text=True)\n"
                         "g = os.fdopen(1, 'w')\nh = Path('x').open('w')\ni = tempfile.TemporaryFile('w+')\n"
                         "from hypnomix.core import atomic\natomic.write_text('x', 'y')\n", encoding="utf-8")
            self.assertEqual(sorted(w for _, w in text_calls_without_encoding(f)),
                             sorted(["open", "read_text", "write_text", "text=True", "os.fdopen", "Path.open", "tempfile"]))


def newline_on_write_text(path):
    """[line] for every Path.write_text(..., newline=...): that argument came in Python 3.10, and on 3.9 the call
    raises TypeError (the REAPER snapshot restore did, on the 3.9 runners)."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    atomic = _atomic_aliases(tree)
    return [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "write_text" and not (isinstance(n.func.value, ast.Name) and n.func.value.id in atomic)
            and _kw(n, "newline")]


class Python39Calls(unittest.TestCase):
    def test_no_write_text_with_newline(self):
        files = sorted(PKG.rglob("*.py")) + sorted((ROOT / "tests").glob("*.py"))
        bad = [f"{p.relative_to(ROOT)}:{line}" for p in files for line in newline_on_write_text(p)]
        self.assertEqual(bad, [], "Path.write_text(newline=...) needs Python 3.10; open(path, 'w', encoding='utf-8', "
                                  "newline=...) works on 3.9:\n" + "\n".join(bad))

    def test_the_walk_finds_it(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "m.py"
            f.write_text("from pathlib import Path\nPath('x').write_text('t', encoding='utf-8', newline='\\n')\n"
                         "Path('x').write_text('t', encoding='utf-8')\n", encoding="utf-8")
            self.assertEqual(newline_on_write_text(f), [2])


# ---------------------------------------------------------------- bugs 1, 2, 6: text written and read under a legacy encoding
class LegacyEncodingRun(unittest.TestCase):
    """Run in a child whose default encoding is ASCII (what a Windows code page does to an arrow)."""

    def test_the_wiki_articles_and_guides_read(self):
        r = run_legacy("from hypnomix.app import wiki; print(len(wiki.local()))")
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-400:])
        self.assertGreater(int(r.stdout.decode().strip()), 20)
        r = run_legacy("from hypnomix.app import wiki_md, wiki\n"
                       "import json\n"
                       "x = wiki.local()\n"
                       "print(sum(1 for a in x if a.get('title')))")
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-400:])

    def test_reports_with_arrows_are_written_as_utf8(self):
        with tempfile.TemporaryDirectory() as td:
            stems = Path(td) / "stems"
            stems.mkdir()
            tone(stems / "Keys.wav", 2.0)
            tone(stems / "Bass.wav", 2.0, freq=80)
            for cmd in (["prep", str(stems), "--out", str(Path(td) / "prep")],
                        ["automix", str(stems), "--out", str(Path(td) / "automix")]):
                r = run_legacy(args=cmd)
                self.assertEqual(r.returncode, 0, f"{cmd[0]}: " + r.stderr.decode("utf-8", "replace")[-500:])
            md = [p for p in (Path(td) / "prep").rglob("*.md")] + [p for p in (Path(td) / "automix").rglob("*.md")]
            self.assertTrue(md)
            self.assertTrue(any("\u2192" in p.read_text(encoding="utf-8") for p in md), "no arrow written")   # and every one is valid UTF-8
            r = run_legacy(args=["master", str(stems / "Keys.wav"), "--out", str(Path(td) / "master")])
            self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-500:])

    def test_a_folder_of_names_outside_the_code_page_is_preflighted(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "Zo\u00eb \u65e5\u672c"
            d.mkdir()
            tone(d / "\u0411\u0430\u0441 \u65e5\u672c.wav")
            r = run_legacy(args=["preflight", str(d), "--out", str(Path(td) / "pf")])
            self.assertIn(r.returncode, (0, 1), r.stderr.decode("utf-8", "replace")[-500:])     # a verdict, never a traceback
            self.assertNotIn(b"Traceback", r.stderr)
            reports = list((Path(td) / "pf").rglob("*.md")) + list((Path(td) / "pf").rglob("*.json"))
            for p in reports:
                p.read_bytes().decode("utf-8")                      # every file it wrote is valid UTF-8

    def test_the_device_scripts_are_utf8(self):
        code = (
            "import sys\nfrom pathlib import Path\nfrom hypnomix.app import device as D, aligndevice as AD, probe as P\n"
            "blank = {'patcher': {'boxes': [{'box': {'id': 'obj-1', 'maxclass': 'newobj', 'text': 'plugin~'}},"
            "{'box': {'id': 'obj-2', 'maxclass': 'newobj', 'text': 'plugout~'}},"
            "{'box': {'id': 'obj-6', 'maxclass': 'live.comment', 'text': 'Build your Audio Effect here'}}],"
            "'lines': [{'patchline': {'destination': ['obj-2', 0], 'source': ['obj-1', 0]}}],"
            "'openinpresentation': 0, 'devicewidth': 0.0}}\n"
            "td = Path(sys.argv[1]); tpl = td / 'Max Audio Effect.amxd'\n"
            "D.write_amxd(tpl, b'ampf\\x04\\x00\\x00\\x00aaaameta\\x04\\x00\\x00\\x00\\x00\\x00\\x00\\x00', blank)\n"
            "D.build(td / 'd', tpl); AD.build(td / 'a', tpl); P.build(td / 'p', tpl)\n")
        with tempfile.TemporaryDirectory() as td:
            r = run_legacy(code.replace("sys.argv[1]", repr(td)))
            self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-500:])
            scripts = [Path(td) / "d" / "hypnomix_device.js", Path(td) / "a" / "hypnomix_align.js",
                       Path(td) / "p" / "hypnomix_probe.js", Path(td) / "p" / "hypnomix_master.js"]
            for s in scripts:
                self.assertTrue(s.stat().st_size > 1000, s.name)                 # not the half-made 0-byte file
                s.read_bytes().decode("utf-8")                                   # Max reads these as UTF-8
            self.assertIn("\u00b7".encode("utf-8"), scripts[0].read_bytes())     # the middle dot is two bytes, not one cp1252 byte

    def test_the_bridge_sends_utf8(self):
        code = (
            "import os, sys, threading, time, json\nfrom pathlib import Path\nfrom unittest import mock\n"
            "from hypnomix.reaper import client as C\n"
            "d = Path(sys.argv[1]); (d / 'alive').write_text('x')\n"
            "def bridge():\n"
            "    for _ in range(400):\n"
            "        for f in d.glob('req-*.txt'):\n"
            "            (d / 'seen.bin').write_bytes(f.read_bytes())\n"
            "            (d / f.name.replace('req-', 'res-').replace('.txt', '.json')).write_bytes(b'{\"ok\": true, \"result\": 1}')\n"
            "            f.unlink(); return\n"
            "        time.sleep(0.01)\n"
            "threading.Thread(target=bridge, daemon=True).start()\n"
            "r = C.Reaper(folder=d, timeout=5)\n"
            "r.call('track_info', track='Zo\\u00eb \\u58f0 Vox')\n"
            "# starting the bridge writes the Lua boot file in the person's folder (made by the test, which runs in UTF-8: a\n"
            "# child whose language setting is ASCII, as on Linux, sees the accent as bytes it cannot decode)\n"
            "boot = Path(os.environ['HYPNOMIX_TEST_BOOT'])\n"
            "q = C.Reaper(folder=boot, timeout=1)\n"
            "answers = iter([False, True, True])\n"
            "with mock.patch.object(C.Reaper, 'alive', lambda self, within=4.0: next(answers, True)), "
            "mock.patch.object(C, 'reaper_executable', return_value='reaper'), mock.patch.object(C.subprocess, 'Popen'):\n"
            "    q.start(wait=2)\n")
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "Jos\u00e9").mkdir()
            r = run_legacy(code.replace("sys.argv[1]", repr(td)), env=legacy_env({"HYPNOMIX_TEST_BOOT": str(Path(td) / "Jos\u00e9")}))
            self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-500:])
            self.assertEqual((Path(td) / "seen.bin").read_bytes(), "track_info\ntrack=Zo\u00eb \u58f0 Vox\n".encode("utf-8"))
            lua = (Path(td) / "Jos\u00e9" / "start-bridge.lua").read_bytes()
            self.assertIn("Jos\u00e9".encode("utf-8"), lua)
            self.assertNotIn(b"\r", lua)

    def test_a_command_prints_arrows_to_a_narrow_console(self):
        """The CLI itself says UTF-8 on its own stdout, whatever the console was set to (the report line has an arrow)."""
        r = run_legacy(args=["doctor", "-h"])
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-300:])
        self.assertIn("\u00b7".encode("utf-8"), r.stdout)


class StdoutIsMadeUtf8(unittest.TestCase):
    def stream(self, enc, errors="strict", fail_first=False):
        calls = []

        class S:
            def reconfigure(self, **kw):
                calls.append(kw)
                if fail_first and len(calls) == 1:
                    raise ValueError("cannot")
        s = S()
        s.encoding, s.errors = enc, errors
        return s, calls

    def test_a_cp1252_stream_is_reconfigured_everywhere_not_only_on_windows(self):
        from hypnomix import cli
        s, calls = self.stream("cp1252")
        e, ecalls = self.stream("utf-8", "strict")
        with mock.patch.object(sys, "stdout", s), mock.patch.object(sys, "stderr", e):
            cli._utf8_output()
        self.assertEqual(calls, [dict(encoding="utf-8", errors="replace")])
        self.assertEqual(ecalls, [dict(encoding="utf-8", errors="replace")])      # UTF-8 already, but an unprintable character would still raise

    def test_a_stream_that_will_not_change_encoding_still_gets_a_safe_fallback(self):
        from hypnomix import cli
        s, calls = self.stream("cp1252", fail_first=True)
        with mock.patch.object(sys, "stdout", s), mock.patch.object(sys, "stderr", None):
            cli._utf8_output()                                       # no console at all (pythonw) is fine too
        self.assertEqual(calls, [dict(encoding="utf-8", errors="replace"), dict(errors="replace")])

    def test_utf8_streams_that_already_replace_are_left_alone(self):
        from hypnomix import cli
        s, calls = self.stream("utf-8", "replace")
        with mock.patch.object(sys, "stdout", s), mock.patch.object(sys, "stderr", s):
            cli._utf8_output()
        self.assertEqual(calls, [])


# ---------------------------------------------------------------- bug 3: the app and its commands
class AppReadsItsCommands(unittest.TestCase):
    def test_a_command_started_by_the_app_is_read_as_utf8_and_given_utf8(self):
        code = ("from hypnomix.app import server as S\n"
                "p = S.popen_job(['doctor', '-h'])\n"
                "out = p.stdout.read(); p.wait()\n"
                "print('\\u2717' in out, '\\u00e2' in out)\n")
        r = run_legacy(code)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-500:])
        self.assertEqual(r.stdout.decode().split(), ["True", "False"])      # the cross arrives whole, not as "\u00e2\u0153\u2014"

    def test_the_environment_of_a_command_says_utf8(self):
        from hypnomix.app import server as S
        env = S.cli_env()
        self.assertEqual((env["PYTHONIOENCODING"], env["PYTHONUTF8"]), ("utf-8", "1"))

    def test_a_reader_that_fails_stops_the_command(self):
        from hypnomix.app import server as S

        class Out:
            def __iter__(self):
                raise OSError("the pipe broke")

        class Proc:
            pid = 12345
            stdout = Out()
            waited = []

            def wait(self, timeout=None):
                self.waited.append(timeout)
                return 0

        proc, killed = Proc(), []
        with mock.patch.object(S, "popen_job", return_value=proc), mock.patch.object(S, "kill_tree", side_effect=killed.append):
            S.run_job("test", "t", [("step", ["doctor"], True)])
            for _ in range(200):
                if S.JOB["status"] != "running":
                    break
                time.sleep(0.02)
        self.assertEqual(killed, [proc])                          # the command was ended, not left running with nobody reading it
        self.assertEqual(S.JOB["status"], "failed")
        self.assertTrue(any("could not run" in x for x in S.JOB["log"]))


# ---------------------------------------------------------------- bug 5 and 10: where Live keeps things
class LiveFolders(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.home = Path(self.td.name) / "home"
        self.home.mkdir()
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        self.env.start()
        os.environ.pop("APPDATA", None)               # restored by the patch when the test ends

    def tearDown(self):
        self.env.stop()
        self.td.cleanup()

    def system(self, name):
        """This operating system is `name`, and the system's own answer for the Documents folder is "none" unless a test gives one
        (a real Windows would answer with the account's own Documents folder, not this test's home)."""
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch("hypnomix.install.platform.system", return_value=name))
        stack.enter_context(mock.patch("hypnomix.install._windows_documents", return_value=None))
        return stack

    def test_the_user_library_follows_the_operating_system(self):
        from hypnomix import install as I
        with self.system("Darwin"):
            self.assertEqual(I.user_library(), self.home / "Music/Ableton/User Library")
            self.assertEqual(I.remote_scripts_dir(), self.home / "Music/Ableton/User Library/Remote Scripts")
        with self.system("Windows"), mock.patch.object(I, "_windows_documents", return_value=None):
            self.assertEqual(I.user_library(), self.home / "Documents/Ableton/User Library")
        with self.system("Linux"):
            self.assertEqual(I.user_library(), self.home / "Documents/Ableton/User Library")

    def test_a_moved_documents_folder_on_windows_is_followed(self):
        from hypnomix import install as I
        moved = Path(self.td.name) / "OneDrive" / "Documents"
        with self.system("Windows"), mock.patch.object(I, "_windows_documents", return_value=moved):
            self.assertEqual(I.user_library(), moved / "Ableton/User Library")
            self.assertEqual(I.documents_dir(), moved)
        with self.system("Linux"), mock.patch.object(I, "_windows_documents", return_value=moved):
            self.assertEqual(I.documents_dir(), self.home / "Documents")      # the lookup is Windows only

    def test_the_known_folder_lookup_never_raises_off_windows(self):
        from hypnomix import install as I
        got = I._windows_documents()                              # never raises
        if sys.platform == "win32":
            self.assertTrue(got is None or isinstance(got, Path), got)      # a real Windows may answer with the account's folder
        else:
            self.assertIsNone(got)                                          # no ctypes.windll here: a plain None, so the fallback is used

    def test_messages_name_the_folder_as_the_person_sees_it(self):
        from hypnomix import install as I
        with self.system("Darwin"):
            self.assertEqual(I.user_library_words(), "~/Music/Ableton/User Library")
        with self.system("Windows"), mock.patch.object(I, "_windows_documents", return_value=None):
            self.assertEqual(I.user_library_words(), "~/Documents/Ableton/User Library")

    def build_template(self):
        from hypnomix.app import device as D
        blank = {"patcher": {"boxes": [{"box": {"id": "obj-1", "maxclass": "newobj", "text": "plugin~"}},
                                       {"box": {"id": "obj-2", "maxclass": "newobj", "text": "plugout~"}},
                                       {"box": {"id": "obj-6", "maxclass": "live.comment", "text": "Build your Audio Effect here"}}],
                             "lines": [{"patchline": {"destination": ["obj-2", 0], "source": ["obj-1", 0]}}],
                             "openinpresentation": 0, "devicewidth": 0.0}}
        tpl = Path(self.td.name) / "Max Audio Effect.amxd"
        D.write_amxd(tpl, b"ampf\x04\x00\x00\x00aaaameta\x04\x00\x00\x00\x00\x00\x00\x00", blank)
        return tpl

    def test_the_device_commands_write_into_the_library_of_this_system(self):
        from hypnomix.app import device as D, aligndevice as AD, probe as P
        tpl = self.build_template()
        lib = self.home / "Documents/Ableton/User Library"
        lib.mkdir(parents=True)
        for mod, argv, leaf, files in ((D, ["device"], "Hypnomix", ["Hypnomix.amxd"]),
                                       (AD, ["aligndevice"], "Hypnomix Align", ["Hypnomix Align.amxd"]),
                                       (P, ["probe", "device"], "Hypnomix", ["HypnomixProbe.amxd", "HypnomixMain.amxd"])):
            with self.system("Windows"), mock.patch.object(sys, "argv", argv + ["--template", str(tpl)]), \
                    contextlib.redirect_stdout(io.StringIO()):
                mod.main()
            where = lib / "Presets/Audio Effects/Max Audio Effect" / leaf
            for f in files:
                self.assertTrue((where / f).exists(), f"{mod.__name__}: {where / f}")

    def test_no_library_says_where_to_look_in_this_systems_words(self):
        from hypnomix.app import device as D
        tpl = self.build_template()
        with self.system("Windows"), mock.patch.object(sys, "argv", ["device", "--template", str(tpl)]), \
                self.assertRaises(SystemExit) as cm:
            D.main()
        self.assertIn("~/Documents/Ableton/User Library", str(cm.exception.code))
        self.assertNotIn("Music/Ableton", str(cm.exception.code))

    def test_probe_insert_finds_the_devices_in_the_library_of_this_system(self):
        from hypnomix.app import probe as P
        from hypnomix import install as I
        with self.system("Windows"), mock.patch.object(I, "_windows_documents", return_value=None):
            self.assertEqual(P.library_dir(), self.home / "Documents/Ableton/User Library")
            with self.assertRaises(FileNotFoundError) as cm:
                P.device_element("HypnomixProbe")
            self.assertIn("Documents", str(cm.exception))

    def test_options_txt_goes_beside_preferences_cfg_on_windows(self):
        from hypnomix import install as I
        prefs = self.home / "AppData/Roaming/Ableton/Live 12.1.5/Preferences"
        prefs.mkdir(parents=True)
        (prefs / "Preferences.cfg").write_text("x", encoding="utf-8")
        older = self.home / "AppData/Roaming/Ableton/Live 11.3.2/Preferences"
        older.mkdir(parents=True)
        (older / "Preferences.cfg").write_text("x", encoding="utf-8")
        with self.system("Windows"):
            self.assertEqual(I.live_prefs_dir(), prefs)
            scripts = self.home / "scripts"
            existing = "-_CustomLine=1\n# na\u00efve ".encode("utf-8") + b"\xe9\n"               # a byte that is not UTF-8
            (prefs / "Options.txt").write_bytes(existing)
            with mock.patch.object(I, "remote_scripts_dir", return_value=scripts), contextlib.redirect_stdout(io.StringIO()):
                I.install(["--plugin-params"])
            data = (prefs / "Options.txt").read_bytes()
            self.assertTrue(data.startswith(existing), "the person's own lines must come back byte for byte")
            self.assertIn(b"PluginAutoPopulateThreshold", data)
            self.assertFalse((prefs.parent / "Options.txt").exists())          # not one folder too high

    def test_a_windows_style_options_txt_keeps_its_line_ends(self):
        from hypnomix import install as I
        prefs = self.home / "AppData/Roaming/Ableton/Live 12.1.5/Preferences"
        prefs.mkdir(parents=True)
        (prefs / "Preferences.cfg").write_text("x", encoding="utf-8")
        existing = b"-_CustomLine=1\r\n-_Other=2\r\n"                       # what Notepad writes
        (prefs / "Options.txt").write_bytes(existing)
        with self.system("Windows"), mock.patch.object(I, "remote_scripts_dir", return_value=self.home / "scripts"), \
                contextlib.redirect_stdout(io.StringIO()):
            I.install(["--plugin-params"])
        data = (prefs / "Options.txt").read_bytes()
        self.assertTrue(data.startswith(existing), data)
        self.assertTrue(data.endswith(b"\r\n") and data.count(b"\n") == data.count(b"\r\n"), data)     # the new line ends like the others

    def test_a_new_options_txt_on_windows_gets_windows_line_ends(self):
        from hypnomix import install as I

        class WindowsOs:                                     # the real os module, except that it says it is Windows (patching os.name itself would break pathlib here)
            name = "nt"
            def __getattr__(self, attr):
                return getattr(os, attr)

        prefs = self.home / "AppData/Roaming/Ableton/Live 12.1.5/Preferences"
        prefs.mkdir(parents=True)
        (prefs / "Preferences.cfg").write_text("x", encoding="utf-8")
        self.assertFalse((prefs / "Options.txt").exists())
        with self.system("Windows"), mock.patch.object(I, "os", WindowsOs()), \
                mock.patch.object(I, "remote_scripts_dir", return_value=self.home / "scripts"), contextlib.redirect_stdout(io.StringIO()):
            I.install(["--plugin-params"])
        data = (prefs / "Options.txt").read_bytes()
        self.assertIn(b"PluginAutoPopulateThreshold", data)
        self.assertTrue(data.endswith(b"\r\n") and data.count(b"\n") == data.count(b"\r\n"), data)    # a new file: the system's own line end

    def test_a_mac_keeps_its_preferences_folder(self):
        from hypnomix import install as I
        prefs = self.home / "Library/Preferences/Ableton/Live 12.0"
        prefs.mkdir(parents=True)
        (prefs / "Preferences.cfg").write_text("x", encoding="utf-8")
        with self.system("Darwin"):
            self.assertEqual(I.live_prefs_dir(), prefs)

    def test_a_redirected_appdata_is_used(self):
        from hypnomix import install as I
        roaming = Path(self.td.name) / "elsewhere"
        prefs = roaming / "Ableton/Live 12.0/Preferences"
        prefs.mkdir(parents=True)
        (prefs / "Preferences.cfg").write_text("x", encoding="utf-8")
        with self.system("Windows"), mock.patch.dict(os.environ, {"APPDATA": str(roaming)}):
            self.assertEqual(I.live_prefs_dir(), prefs)


# ---------------------------------------------------------------- bug 7: Rubber Band missing
class RubberBandMissing(unittest.TestCase):
    def test_tune_ends_in_one_plain_sentence(self):
        from hypnomix import cli
        err = io.StringIO()
        with mock.patch("hypnomix.core.tools.shutil.which", return_value=None), mock.patch("hypnomix.core.tools.platform.system", return_value="Darwin"), \
                contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            cli.main(["tune", "in.wav", "out.wav", "--no-chord-check"])
        self.assertEqual(cm.exception.code, 2)
        text = err.getvalue().strip()
        self.assertEqual(len(text.splitlines()), 1)
        self.assertIn("Rubber Band", text)
        self.assertIn("brew install rubberband", text)
        self.assertNotIn("Traceback", text)

    def test_the_words_fit_the_operating_system(self):
        from hypnomix.core import tools
        for system, want, unwanted in (("Darwin", "brew install rubberband", "apt"), ("Linux", "apt install rubberband-cli", "brew"),
                                       ("Windows", "breakfastquay.com/rubberband", "brew")):
            with mock.patch("hypnomix.core.tools.platform.system", return_value=system):
                text = tools.rubberband_how()
            self.assertIn(want, text)
            self.assertNotIn(unwanted, text)

    def test_report_only_needs_no_rubberband(self):
        from hypnomix.core import tools
        with mock.patch.object(tools, "rubberband_path", return_value=None):
            with self.assertRaises(tools.MissingToolError):
                tools.need_rubberband("tune")

    def test_formant_and_the_tune_render_say_it_too(self):
        from hypnomix.core import tools
        from hypnomix.studio import formant, tune
        with mock.patch.object(tools, "rubberband_path", return_value=None):
            with self.assertRaises(tools.MissingToolError) as cm:
                formant._rb(np.zeros((100, 1), "float32"), 44100, 1.0, True)
            self.assertIn("formant", str(cm.exception))
            with self.assertRaises(tools.MissingToolError):
                tune.render("none.wav", "out.wav", np.zeros(4), 44100, 100, 1)

    def test_doctor_lists_it_as_optional(self):
        from hypnomix import install as I
        with mock.patch("hypnomix.core.tools.shutil.which", return_value=None), mock.patch.object(I, "_live_answer", return_value=(False, "x")), \
                mock.patch.object(I, "_port_open", return_value=False), mock.patch.object(I, "_blackhole", return_value=[]):
            rows = [r for r in I.doctor_rows() if "Rubber Band" in r[1]]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "\u00b7")                      # optional: it never fails the check
        self.assertIn("not found", rows[0][2])


# ---------------------------------------------------------------- bug 8: the Windows command
class WindowsCommand(unittest.TestCase):
    def test_every_line_ends_in_cr_lf_once(self):
        from hypnomix.app import setup as SU
        text = SU.windows_shim_text(r"C:\Users\Ann\AppData\Local\hypnomix\python.exe", r"C:\Users\Ann\AppData\Local\hypnomix\bin")
        raw = text.encode("utf-8")
        self.assertTrue(raw.endswith(b"\r\n"))
        self.assertNotIn(b"\r\r", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertNotIn("chcp", text)                              # an all-ASCII command changes nothing about the code page
        self.assertIn("made by the hypnomix app's setup", text)

    def test_a_folder_with_accents_runs_under_utf8_and_puts_the_code_page_back(self):
        from hypnomix.app import setup as SU
        text = SU.windows_shim_text("C:\\Users\\<you>\\caf\u00e9\\python.exe", None)
        lines = text.split("\r\n")
        self.assertLess(next(i for i, l in enumerate(lines) if "chcp 65001" in l), next(i for i, l in enumerate(lines) if "hypnomix.cli" in l))
        self.assertTrue(any("exit /b %HYPNOMIX_RC%" in l for l in lines))
        self.assertTrue(any(l.startswith("chcp %HYPNOMIX_CP%") for l in lines))
        text.encode("utf-8")

    def test_make_cli_writes_bytes_without_doubled_returns(self):
        from hypnomix.app import setup as SU
        with tempfile.TemporaryDirectory() as td:
            shim = Path(td) / "bin" / "hypnomix.cmd"
            # sys.platform says win32 for the whole block, and Python 3.12 and later then asks the Windows API from shutil.which
            # (a module that exists only on Windows): the lookup of "hypnomix" on the PATH is not what this test is about
            with mock.patch.object(sys, "platform", "win32"), mock.patch.object(SU, "shim_path", return_value=shim), \
                    mock.patch.object(SU, "agent_dir", return_value=Path(td) / "agent"), mock.patch.object(SU, "_bin_dir", return_value=None), \
                    mock.patch.object(SU, "copy_skills", return_value=([], [])), mock.patch.object(SU.shutil, "which", return_value=None):
                SU.make_cli()
            data = shim.read_bytes()
            self.assertIn(b"hypnomix.cli %*\r\n", data)
            self.assertNotIn(b"\r\r", data)


# ---------------------------------------------------------------- a folder name this computer cannot decode (Linux, a bare "C" language setting)
class UndecodableFolderName(unittest.TestCase):
    """Python holds a file name's bytes it cannot decode as lone surrogate characters. The test makes one by hand (no Linux
    here: a Mac refuses such a name on disk), so nothing touches the disk but the folder the test made."""
    HELD = "Jos" + "".join(chr(0xDC00 + b) for b in "\u00e9".encode("utf-8"))        # "Jos" + the two bytes of an e with an acute accent

    def test_the_boot_file_keeps_the_bytes_of_the_folders_name(self):
        from hypnomix.reaper import client as C
        with tempfile.TemporaryDirectory() as td:
            r = C.Reaper(timeout=1, folder=Path(td))
            r.dir = Path(td) / self.HELD
            written = {}
            answers = iter([False, True, True])
            with mock.patch.object(C.Reaper, "alive", lambda self, within=4.0: next(answers, True)), \
                    mock.patch.object(C, "reaper_executable", return_value="reaper"), mock.patch.object(C.subprocess, "Popen"), \
                    mock.patch.object(Path, "write_bytes", lambda self, data: written.update({self.name: data})), \
                    mock.patch.object(Path, "glob", lambda self, pattern: iter(())):
                r.start(wait=2)
        self.assertIn("Jos\u00e9".encode("utf-8"), written["start-bridge.lua"])      # the folder's own bytes, not a traceback
        self.assertNotIn(b"\r", written["start-bridge.lua"])


# ---------------------------------------------------------------- Python 3.9: no Claude library
class ClaudeLibraryOnPython39(unittest.TestCase):
    """Anthropic's library needs Python 3.10 or newer, so on 3.9 the Assistant has the OpenAI-compatible providers only.
    Python 3.9 is simulated: sys.version_info is patched for the length of each test."""
    OLD = (3, 9, 25, "final", 0)

    def test_the_extra_does_not_ask_for_it_on_39(self):
        import re
        toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        line = next(l for l in toml.splitlines() if l.startswith("assistant ="))
        self.assertRegex(line, r"anthropic>=[\d.]+; python_version >= '3\.10'")      # the marker that lets pip install the rest on 3.9
        self.assertIn("openai", line)
        self.assertEqual(re.findall(r"requires-python = \"(.*?)\"", toml), [">=3.9"])

    def test_the_tests_get_an_empty_stand_in_module_only_where_the_library_cannot_be(self):
        from tests import _isolate
        with mock.patch.dict(sys.modules), mock.patch.object(sys, "version_info", self.OLD), \
                mock.patch.object(_isolate.importlib.util, "find_spec", return_value=None):
            sys.modules.pop("anthropic", None)
            self.assertTrue(_isolate.stand_in_for_claude_library())
            with mock.patch("anthropic.Anthropic", lambda **k: "fake"):
                import anthropic
                self.assertEqual(anthropic.Anthropic(), "fake")
            with self.assertRaises(RuntimeError):
                sys.modules["anthropic"].Anthropic()
        with mock.patch.dict(sys.modules, {"anthropic": object()}), mock.patch.object(sys, "version_info", (3, 12, 1, "final", 0)):
            self.assertFalse(_isolate.stand_in_for_claude_library())             # a Python that can have it never gets a stand-in

    def test_the_assistant_says_why_claude_is_missing_on_39(self):
        from hypnomix.app import chat as CH
        e = ImportError("No module named 'anthropic'", name="anthropic")
        with mock.patch.object(sys, "version_info", self.OLD):
            said = CH._friendly(e, "Claude")
        self.assertIn("Python 3.10 or newer", said)
        self.assertIn("Python 3.9", said)
        self.assertNotIn("uv pip install", said)                                  # that would not bring it
        with mock.patch.object(sys, "version_info", (3, 12, 1, "final", 0)):
            self.assertIn("uv pip install", CH._friendly(e, "Claude"))
        with mock.patch.object(sys, "version_info", self.OLD):
            self.assertIn("uv pip install", CH._friendly(ImportError("x", name="openai"), "Ollama"))   # the other library: as before


# ---------------------------------------------------------------- bug 9: the port
class PortIsHeldExclusively(unittest.TestCase):
    def test_the_servers_refuse_a_port_that_is_in_use(self):
        from hypnomix.core.serve import LocalServer
        from http.server import BaseHTTPRequestHandler
        a = LocalServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        try:
            with self.assertRaises(OSError):
                LocalServer(("127.0.0.1", a.server_address[1]), BaseHTTPRequestHandler)
        finally:
            a.server_close()

    def test_windows_does_not_reuse_the_address(self):
        from http.server import BaseHTTPRequestHandler
        from hypnomix.core import serve
        with mock.patch.object(serve, "_windows", return_value=True):
            s = serve.LocalServer(("127.0.0.1", 0), BaseHTTPRequestHandler, bind_and_activate=False)
            try:
                self.assertFalse(s.allow_reuse_address)
            finally:
                s.socket.close()
        self.assertNotIn("EXCLUSIVEADDRUSE", (PKG / "core" / "serve.py").read_text(encoding="utf-8"))

    def test_the_others_keep_the_address_reuse_that_makes_a_restart_work(self):
        from http.server import BaseHTTPRequestHandler
        from hypnomix.core import serve
        with mock.patch.object(serve, "_windows", return_value=False):          # a real Windows says True here, and is right to
            s = serve.LocalServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        try:
            self.assertTrue(s.allow_reuse_address)
        finally:
            s.server_close()

    def test_the_server_does_not_ask_the_resolver_for_a_name_before_it_listens(self):
        import socket
        from http.server import BaseHTTPRequestHandler
        from hypnomix.core import serve
        self.assertIn("server_bind", vars(serve.LocalServer))               # its own, not HTTPServer's (which looks the name up)
        with mock.patch.object(socket, "getfqdn", side_effect=AssertionError("asked the resolver")):
            s = serve.LocalServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        try:
            self.assertEqual(s.server_port, s.server_address[1])
        finally:
            s.server_close()

    def test_the_app_and_the_review_page_use_it(self):
        self.assertIn("LocalServer(", (PKG / "app" / "server.py").read_text(encoding="utf-8"))
        self.assertIn("LocalServer(", (PKG / "workflow" / "review.py").read_text(encoding="utf-8"))

    def test_the_review_page_on_a_busy_port_says_so_in_one_sentence(self):
        from hypnomix.workflow import review
        busy = socket.socket()
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        try:
            with self.assertRaises(SystemExit) as cm:
                review.serve(Path(tempfile.gettempdir()), busy.getsockname()[1])
            self.assertIn("is in use", str(cm.exception))
        finally:
            busy.close()


# ---------------------------------------------------------------- bug 11: atomic writes on Windows
class AtomicRetries(unittest.TestCase):
    def test_a_target_held_open_for_a_moment_is_retried_on_windows(self):
        from hypnomix.core import atomic
        real, calls = os.replace, []

        def flaky(src, dst):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(errno.EACCES, "in use")
            return real(src, dst)
        with tempfile.TemporaryDirectory() as td, mock.patch.object(atomic, "_windows", return_value=True), \
                mock.patch.object(atomic.os, "replace", flaky), mock.patch.object(atomic.time, "sleep") as nap:
            p = Path(td) / "decisions.json"
            atomic.write_json(p, {"a": 1})
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"a": 1})
            self.assertEqual(len(calls), 3)
            self.assertEqual(nap.call_count, 2)
            self.assertFalse(list(Path(td).glob(".*.tmp")))          # no half-written leftovers

    def test_still_open_after_the_tries_ends_in_a_plain_sentence_and_the_old_file_stays(self):
        from hypnomix.core import atomic
        with tempfile.TemporaryDirectory() as td, mock.patch.object(atomic, "_windows", return_value=True), \
                mock.patch.object(atomic.os, "replace", side_effect=PermissionError(errno.EACCES, "in use")), mock.patch.object(atomic.time, "sleep"):
            p = Path(td) / "state.json"
            p.write_text('{"keep": 1}', encoding="utf-8")
            with self.assertRaises(PermissionError) as cm:
                atomic.write_text(p, '{"new": 2}', backup=False)
            self.assertIn("open in another program", str(cm.exception.strerror))
            self.assertEqual(Path(cm.exception.filename).name, "state.json")
            self.assertEqual(p.read_text(encoding="utf-8"), '{"keep": 1}')
            self.assertFalse(list(Path(td).glob(".*.tmp")))

    def test_elsewhere_there_is_no_retry(self):
        from hypnomix.core import atomic
        calls = []
        with tempfile.TemporaryDirectory() as td, mock.patch.object(atomic, "_windows", return_value=False), \
                mock.patch.object(atomic.os, "replace", side_effect=lambda *a: calls.append(1) or (_ for _ in ()).throw(PermissionError("no"))):
            with self.assertRaises(PermissionError):
                atomic.write_text(Path(td) / "x.txt", "t", backup=False)
        self.assertEqual(len(calls), 1)

    def test_the_other_writers_of_shared_files_use_it(self):
        for rel in ("app/server.py", "app/chat.py", "app/wiki.py", "app/masterchain.py", "core/pitch.py"):
            self.assertIn("atomic import replace", (PKG / rel).read_text(encoding="utf-8"), rel)


# ---------------------------------------------------------------- bug 12: projects saved on Windows
class WindowsProjectPaths(unittest.TestCase):
    def project(self, td, file_line, record='"Audio" ""'):
        d = Path(td) / "proj"
        (d / "Audio").mkdir(parents=True)
        tone(d / "Audio" / "Drums.wav")
        (d / "Song.rpp").write_text(
            '<REAPER_PROJECT 0.1 "7.27/win64" 1764000000\n  TEMPO 100 4 4\n  SAMPLERATE 44100 0 0\n  RECORD_PATH ' + record + '\n'
            '  <TRACK {11111111-1111-1111-1111-111111111111}\n    NAME Drums\n    VOLPAN 1 0 -1 -1 1\n    MUTESOLO 0 0 0\n'
            '    <ITEM\n      POSITION 0\n      LENGTH 1\n      LOOP 0\n      SOFFS 0\n      PLAYRATE 1 1 0 -1 0 0.0025\n'
            '      <SOURCE WAVE\n        FILE "' + file_line + '"\n      >\n    >\n  >\n>\n', encoding="utf-8")
        return d

    def test_backslash_paths_are_found_on_a_mac_or_linux(self):
        from hypnomix import project
        for line in ("Audio\\Drums.wav", "C:\\Users\\Ann\\Music\\Audio\\Drums.wav", "Audio/Drums.wav", "..\\proj\\Audio\\Drums.wav"):
            with tempfile.TemporaryDirectory() as td:
                d = self.project(td, line)
                p = project.load(d / "Song.rpp")
                self.assertEqual(p.missing(), [], line)

    def test_a_file_that_is_really_gone_is_still_reported_with_a_readable_path(self):
        from hypnomix.project import reaper
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            got = reaper.resolve("Audio\\Gone.wav", d)
            self.assertEqual(got, d / "Audio" / "Gone.wav")
            self.assertEqual(got.parts[-2:], ("Audio", "Gone.wav"))          # two names, not one name with a backslash in it
            drive = reaper.resolve("C:\\Users\\Ann\\Gone.wav", d)
            self.assertFalse(drive.exists())
            self.assertEqual(drive.name, "Gone.wav")


# ---------------------------------------------------------------- bug 13: plug-in folders
class PlugInFolders(unittest.TestCase):
    def test_each_system_looks_where_its_plugins_are(self):
        from hypnomix.session import plugrender as PR
        home = Path("/home/ann")
        vst3, au = PR.plugin_folders("darwin", home)
        self.assertEqual(vst3[0], home / "Library/Audio/Plug-Ins/VST3")             # the person's own folder first, as before
        self.assertIn(Path("/Library/Audio/Plug-Ins/VST3"), vst3)
        self.assertEqual(au[0], home / "Library/Audio/Plug-Ins/Components")
        with mock.patch.dict(os.environ, {"COMMONPROGRAMFILES": "D:/Common Files", "LOCALAPPDATA": "D:/Local"}):
            vst3, au = PR.plugin_folders("win32", home)
        self.assertEqual(vst3[0], Path("D:/Common Files") / "VST3")
        self.assertEqual(au, [])
        vst3, au = PR.plugin_folders("linux", home)
        self.assertIn(home / ".vst3", vst3)
        self.assertEqual(au, [])
        self.assertFalse(any("Library/Audio" in str(p) for p in vst3))

    def test_not_installed_names_the_folders_it_looked_in(self):
        from hypnomix.session import plugrender as PR
        info = dict(kind="vst3", name="Some EQ", codes=(None, None, None), buffer=b"")
        with tempfile.TemporaryDirectory() as td, mock.patch.object(PR, "VST3_DIRS", [Path(td) / "Common Files" / "VST3"]), \
                mock.patch.object(PR, "AU_DIRS", []):
            r = PR.prepare(info, do_probe=False)
            self.assertFalse(r["ok"])
            self.assertIn("Common Files", r["error"])
            self.assertNotIn("/Library", r["error"])
            r = PR.prepare(dict(info, kind="au"), do_probe=False)
            self.assertIn("Mac only", r["error"])

    def test_a_plugin_in_a_makers_folder_is_found_on_windows(self):
        from hypnomix.session import plugrender as PR
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "Maker" / "Some EQ.vst3").mkdir(parents=True)
            with mock.patch.object(PR, "VST3_DIRS", [Path(td)]), mock.patch.object(sys, "platform", "win32"):
                found = PR.find_vst3("Some EQ")
            self.assertEqual(found[0].name, "Some EQ.vst3")


# ---------------------------------------------------------------- bugs 14 and 15: opening things
class OpeningThings(unittest.TestCase):
    def setUp(self):
        from hypnomix.app import align
        self.align = align
        self.td = tempfile.TemporaryDirectory()
        self.als = Path(self.td.name) / "Song (aligned).als"
        self.als.write_text("x", encoding="utf-8")
        self.old = align.ALIGN["result"]
        align.ALIGN["result"] = {"out_set": str(self.als)}

    def tearDown(self):
        self.align.ALIGN["result"] = self.old
        self.td.cleanup()

    def test_windows_opens_the_set_with_the_program_registered_for_it(self):
        started = []
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(os, "startfile", started.append, create=True):
            code, body = self.align.handle_post("/api/align/open", {})
        self.assertEqual((code, body), (200, {"opened": str(self.als)}))
        self.assertEqual(started, [str(self.als)])

    def test_linux_uses_xdg_open(self):
        with mock.patch.object(sys, "platform", "linux"), mock.patch.object(self.align.shutil, "which", return_value="/usr/bin/xdg-open"), \
                mock.patch.object(self.align.subprocess, "Popen") as popen:
            code, body = self.align.handle_post("/api/align/open", {})
        self.assertEqual(code, 200)
        self.assertEqual(popen.call_args[0][0], ["/usr/bin/xdg-open", str(self.als)])

    def test_when_nothing_can_open_it_the_answer_says_so_instead_of_opened(self):
        with mock.patch.object(sys, "platform", "linux"), mock.patch.object(self.align.shutil, "which", return_value=None):
            code, body = self.align.handle_post("/api/align/open", {})
        self.assertEqual(code, 400)
        self.assertNotIn("opened", body)
        self.assertIn("open", body["error"])
        self.assertIn(str(self.als), body["error"])
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(os, "startfile", side_effect=OSError("no program"), create=True):
            code, body = self.align.handle_post("/api/align/open", {})
        self.assertEqual(code, 400)

    def test_the_mac_still_uses_open(self):
        with mock.patch.object(sys, "platform", "darwin"), mock.patch.object(self.align.subprocess, "run") as run:
            run.return_value.returncode = 0
            code, body = self.align.handle_post("/api/align/open", {})
        self.assertEqual(code, 200)
        self.assertEqual(run.call_args[0][0], ["open", str(self.als)])

    def test_show_in_folder_on_windows_quotes_the_path_alone(self):
        from hypnomix.app import server as S
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "My Songs" / "a b.wav"
            f.parent.mkdir()
            f.write_bytes(b"x")
            self.assertEqual(S.explorer_command(f), f'explorer /select,"{f}"')
            self.assertEqual(S.explorer_command(f.parent), ["explorer", str(f.parent)])
            with mock.patch.object(S, "is_windows", return_value=True), mock.patch.object(sys, "platform", "win32"), \
                    mock.patch.object(S.subprocess, "Popen") as popen:
                ok, why = S.reveal(f)
            self.assertTrue(ok, why)
            self.assertEqual(popen.call_args[0][0], f'explorer /select,"{f}"')


# ---------------------------------------------------------------- the A/B scratch copy without link rights
class ScratchCopyWithoutLinks(unittest.TestCase):
    def test_a_system_that_allows_no_links_still_gets_the_scan_copy(self):
        from hypnomix.workflow import abset
        with tempfile.TemporaryDirectory() as td:
            sd = Path(td) / "scan"
            (sd / "raw" / "names").mkdir(parents=True)
            (sd / "raw" / "names" / "names.json").write_text('{"tracks": []}', encoding="utf-8")
            (sd / "findings.json").write_text("{}", encoding="utf-8")
            with mock.patch.object(abset.os, "symlink", side_effect=OSError(1314, "A required privilege is not held")), \
                    mock.patch.object(abset.os, "link", side_effect=OSError(1, "no hard links either")):
                tmp = abset.scratch_scan(sd)
            try:
                self.assertEqual((tmp / "raw" / "names" / "names.json").read_text(encoding="utf-8"), '{"tracks": []}')
                self.assertFalse((tmp / "raw").is_symlink())
            finally:
                shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
