"""The closing round: what the three fix runs left for the last pass, each with a test that fails without the fix.

  help      asking for help does nothing else (no Live, no network, no program) for every command
  loopback  every call to this computer's own ports goes through hypnomix.core.loopback, whatever a proxy variable says
  attach    a listener that is not the engine is not attached to
  preview   a value the Assistant's "Hear it" is trying is put back before any save, however the save arrives
  locks     decisions.json has one lock for every writer, across programs
  reads     the audio tools that read a person's file read it through the checked loader; dehiss never overwrites
  helper    the Mac update helper lets go of its mount folder on every way out, and uses $TMPDIR
  paths     the scan folder reaches a model with the home as "~" and is taken back in that form
  page      the page side of the saving contract, the Hear it card, Enter on a card, the New session path

    python -m unittest tests.test_closing -v
"""
import contextlib
import hashlib
import http.server
import importlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from tests import _isolate

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "hypnomix"
APPJS = PKG / "app"


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------------------
class Help(unittest.TestCase):
    """`hypnomix COMMAND -h` prints the help and exits 0, and does nothing else: it does not ask Live to answer, open a
    connection, start a program or call the network. (`live` used to ping Live before it looked at its arguments.)"""

    def test_every_command_prints_its_help_and_nothing_else_happens(self):
        from hypnomix import cli
        names, skipped = [], []
        for name, (module, _) in cli.COMMANDS.items():          # importing is not acting: it happens before the traps are set
            try:
                importlib.import_module(module)
                names.append(name)
            except ImportError as e:
                skipped.append(f"{name} ({e})")
        self.assertGreaterEqual(len(names), 60, f"too few commands could be imported: {skipped}")
        acted = []

        def trap(what):
            def f(*a, **k):
                acted.append(what)
                raise OSError(f"{what} is not allowed while help is asked for")
            return f

        patches = [mock.patch.object(socket.socket, m, trap("socket." + m)) for m in ("connect", "connect_ex", "sendto", "send", "sendall")]
        patches += [mock.patch.object(subprocess, "Popen", trap("subprocess.Popen")),
                    mock.patch.object(urllib.request, "urlopen", trap("urlopen")),
                    mock.patch.object(os, "system", trap("os.system")),
                    mock.patch.object(os, "popen", trap("os.popen"))]
        bad = []
        with contextlib.ExitStack() as st:
            for p in patches:
                st.enter_context(p)
            for name in names:
                out, err, code = io.StringIO(), io.StringIO(), 0
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    try:
                        cli.main([name, "-h"])
                    except SystemExit as e:
                        code = e.code or 0
                    except BaseException as e:                   # a command that fails here did something other than print help
                        code = f"raised {type(e).__name__}: {e}"
                if code != 0 or not out.getvalue().strip():
                    bad.append((name, code, out.getvalue()[:60], err.getvalue()[:120]))
        self.assertEqual(acted, [], "a command acted while only help was asked for")
        self.assertEqual(bad, [], "a command did not print its help and exit 0")

    def test_live_help_after_a_subcommand_does_nothing_either(self):
        from hypnomix import cli
        from hypnomix.live import osc

        class Boom:
            def __init__(self, *a, **k):
                raise AssertionError("Live() was made")
        subs = ("status", "tracks", "db", "nudge", "send", "pan", "mute", "solo", "devices", "params")
        for sub in subs:
            for flag in ("-h", "--help"):
                out = io.StringIO()
                with mock.patch.object(osc, "Live", Boom), contextlib.redirect_stdout(out):
                    try:
                        cli.main(["live", sub, flag])
                    except SystemExit as e:
                        self.assertEqual(e.code or 0, 0)
                self.assertIn("hypnomix live status", out.getvalue(), f"live {sub} {flag}")

    def test_live_help_does_not_ask_live_to_answer(self):
        from hypnomix import cli
        from hypnomix.live import osc

        class Boom:
            def __init__(self, *a, **k):
                raise AssertionError("Live() was made")
        for flag in ("-h", "--help", "help"):
            out = io.StringIO()
            with mock.patch.object(osc, "Live", Boom), contextlib.redirect_stdout(out):
                try:
                    cli.main(["live", flag])
                except SystemExit as e:
                    self.assertEqual(e.code or 0, 0)
            self.assertIn("hypnomix live status", out.getvalue())


# ---------------------------------------------------------------------------------------------------------------------
class Quiet(http.server.BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Quiet.seen.append(self.path)
        out = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_POST = do_GET


class Loopback(unittest.TestCase):
    """Calls to the app's own port never go to the HTTP proxy named in the environment."""

    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        Quiet.seen.clear()
        dead = "http://127.0.0.1:9"                      # a proxy that nothing listens on: a call sent there fails at once
        self.env = mock.patch.dict(os.environ, {"http_proxy": dead, "HTTP_PROXY": dead, "all_proxy": dead, "ALL_PROXY": dead,
                                                "HYPNOMIX_PORT": str(self.port)})
        self.env.start()
        os.environ.pop("no_proxy", None)
        os.environ.pop("NO_PROXY", None)

    def tearDown(self):
        self.env.stop()

    def test_the_probe_calls_the_app_through_loopback(self):
        from hypnomix.app import probe
        self.assertTrue(probe.app_up())                   # (it answered False when a proxy variable diverted the call)
        Quiet.seen.clear()
        self.assertEqual(probe.app_call("/api/probe/x", {"a": 1}), {"ok": True})
        self.assertEqual(Quiet.seen, ["/api/probe/x"])

    def test_the_reaper_panels_call_the_app_through_loopback(self):
        from hypnomix.reaper import align, review
        for mod in (review, align):
            with mock.patch.object(mod, "APP", f"http://127.0.0.1:{self.port}"):
                self.assertEqual(mod.app("/api/x"), {"ok": True}, mod.__name__)
        self.assertEqual(len(Quiet.seen), 2)

    def test_the_proxy_variable_really_would_have_diverted_a_plain_urlopen(self):
        """The checks above are only worth something if an ordinary opener, built from this environment, fails here: it does.
        (A fresh opener: urlopen keeps the first one it built, which may predate this test's proxy variable.)"""
        with self.assertRaises(OSError):
            urllib.request.build_opener().open(f"http://127.0.0.1:{self.port}/x", timeout=3)

    def test_no_call_to_this_computer_uses_a_plain_urlopen(self):
        """Every urlopen in the package is either the loopback one or one of the few that go to the internet on purpose."""
        internet = {"app/wiki.py", "ears/critique.py", "app/update.py", "store/install.py"}
        offenders = []
        for f in PKG.rglob("*.py"):
            rel = f.relative_to(PKG).as_posix()
            if rel.startswith("remote_script/") or rel in internet or rel == "core/loopback.py":
                continue
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                if re.search(r"urllib\.request\.urlopen\(|(?<![\w.])urlopen\(", code) and "loopback.urlopen" not in code:
                    offenders.append(f"{rel}:{n}")
        self.assertEqual(offenders, [])


# ---------------------------------------------------------------------------------------------------------------------
def serve_mcp(name, tools):
    """A stand-in listener on the engine's kind of address: answers initialize with `name` and tools/list with `tools`."""
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            m = req.get("method")
            res = {"protocolVersion": "2025-03-26", "serverInfo": {"name": name, "version": "1"}} if m == "initialize" \
                else {"tools": [{"name": t} for t in tools]} if m == "tools/list" else {}
            out = json.dumps({"jsonrpc": "2.0", "id": req.get("id"), "result": res}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/mcp"


class Attach(unittest.TestCase):
    """The page's attach (GET /api/daw/state, Start) takes a listener only when it is the engine: the same test the
    Assistant makes before it trusts what answers."""

    def run_attach(self, name, tools):
        from hypnomix.app import daw as DW
        srv, url = serve_mcp(name, tools)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        eng = DW.Engine(attach_url=url)
        with mock.patch.object(DW, "find_engine", lambda: None):
            return eng, eng.attach(), url

    def test_the_engine_is_attached(self):
        from hypnomix.app import daw as DW
        eng, st, url = self.run_attach(DW.SERVER_NAME, DW.CORE_TOOLS)
        self.assertEqual((st["mode"], st["state"], st["url"]), ("attached", "attached", url))

    def test_a_stranger_on_the_engines_port_is_left_alone(self):
        from hypnomix.app import daw as DW
        eng, st, url = self.run_attach("some-other-server", DW.CORE_TOOLS)
        self.assertEqual((st["mode"], st["state"], st["connected"]), (None, "stopped", False))
        self.assertIn("left alone", st["error"])
        self.assertFalse(DW.is_engine(url))

    def test_the_right_name_without_the_engines_tools_is_not_enough(self):
        from hypnomix.app import daw as DW
        eng, st, url = self.run_attach(DW.SERVER_NAME, ["hello_world"])
        self.assertEqual((st["mode"], st["connected"]), (None, False))

    def test_the_assistant_and_the_page_use_the_same_name_and_tools(self):
        from hypnomix.app import chat as CH, daw as DW
        self.assertEqual((CH.ENGINE_SERVER_NAME, tuple(CH.ENGINE_CORE_TOOLS)), (DW.SERVER_NAME, tuple(DW.CORE_TOOLS)))

    def test_available_probes_with_the_same_test(self):
        from hypnomix.app import daw as DW
        srv, url = serve_mcp("some-other-server", DW.CORE_TOOLS)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        eng = DW.Engine(attach_url=url)
        with mock.patch.object(DW, "ENGINE", eng), mock.patch.object(DW, "find_engine", lambda: None), \
                mock.patch.dict(DW.STATE, {"daw": False}):
            self.assertFalse(DW.available(probe=True))


# ---------------------------------------------------------------------------------------------------------------------
class Preview(unittest.TestCase):
    """However a save reaches the engine (the page's proxy, a script, the Assistant), a live "Hear it" is put back first."""

    def engine(self):
        from hypnomix.app import daw as DW
        eng = DW.Engine(attach_url="http://127.0.0.1:9/mcp")
        eng.mode, eng.state = "attached", "attached"
        return eng

    def rpc(self, payload):
        from hypnomix.app import chat as CH
        order = []
        eng = self.engine()
        with mock.patch.object(CH, "preview_end", lambda why="", pid=None: order.append(("end", why))), \
                mock.patch("hypnomix.app.daw.post_json", lambda url, p, timeout=0: (order.append(("send", p)) or (200, b'{"jsonrpc":"2.0","id":1,"result":{}}'))):
            eng.rpc(payload)
        return order

    def call(self, name, **args):
        return {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}

    def test_a_save_ends_the_preview_before_it_is_sent(self):
        order = self.rpc(self.call("session_save"))
        self.assertEqual([k for k, _ in order], ["end", "send"])
        self.assertIn("saved", order[0][1])

    def test_a_save_as_a_new_snapshot_that_is_opened_also_ends_it(self):
        order = self.rpc(self.call("session_save", snapshotName="Fixes", switchToSnapshot=True))
        self.assertEqual([k for k, _ in order], ["end", "send"])

    def test_other_calls_leave_a_preview_alone(self):
        for name, args in (("track_set_fader_db", {"id": "1", "db": -2}), ("tracks_list", {}), ("session_get_info", {})):
            order = self.rpc(self.call(name, **args))
            self.assertEqual([k for k, _ in order], ["send"], name)

    def test_the_review_scan_and_the_save_route_end_it(self):
        from hypnomix.app import chat as CH, daw as DW, dawreview as DR
        seen = []
        with mock.patch.object(CH, "preview_end", lambda why="", pid=None: seen.append(why)):
            DW.end_preview("x")
            with mock.patch.object(DR, "_engine", side_effect=RuntimeError("no engine")):
                with self.assertRaises(RuntimeError):
                    DR.start_scan(None)
        self.assertEqual(seen[0], "x")


# ---------------------------------------------------------------------------------------------------------------------
def scan_folder(root, name="Song", ids=("smooth-1", "smooth-2")):
    d = Path(root) / "scan" / name
    (d / "ab").mkdir(parents=True)
    fs = [dict(id=i, n=1, tool="smooth", kind="click", severity="low", track="Vox", where="1.1.00", applies="set",
               problem="a problem", fix="a fix") for i in ids]
    (d / "findings.json").write_text(json.dumps(dict(set="/nowhere/Song.als", notes=[], findings=fs)), encoding="utf-8")
    (d / "scan.json").write_text(json.dumps(dict(set="/nowhere/Song.als", mode="set")), encoding="utf-8")
    return d


class Locks(unittest.TestCase):
    """decisions.json has ONE lock, used by every writer: `fix --decide`, the review page, the app's routes, a re-scan."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name)
        self.d = scan_folder(self.root)

    def entered(self):
        """Replace the lock with a recorder: -> the folders it was taken for."""
        from hypnomix.core import atomic
        taken = []

        @contextlib.contextmanager
        def rec(sd):
            taken.append(Path(sd))
            yield
        return taken, mock.patch.object(atomic, "decisions_lock", rec)

    def test_it_can_be_taken_again_by_the_thread_that_holds_it(self):
        from hypnomix.core import atomic
        done = []

        def go():
            with atomic.decisions_lock(self.d):
                with atomic.decisions_lock(self.d):
                    done.append(1)
        t = threading.Thread(target=go, daemon=True)
        t.start()
        t.join(10)
        self.assertEqual(done, [1], "the lock deadlocked on itself")

    def test_another_program_waits_for_it(self):
        from hypnomix.core import atomic
        code = ("import sys; from pathlib import Path; from hypnomix.workflow import fix; "
                "fix.record(Path(sys.argv[1]), {'smooth-2': {'decision': 'skip'}})")
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        with atomic.decisions_lock(self.d):
            p = subprocess.Popen([sys.executable, "-c", code, str(self.d)], env=env, cwd=str(ROOT),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.addCleanup(lambda: p.poll() is None and p.kill())
            time.sleep(1.5)
            self.assertIsNone(p.poll(), "the other program wrote while the lock was held")
            self.assertFalse((self.d / "decisions.json").exists())
        out, err = p.communicate(timeout=60)
        self.assertEqual(p.returncode, 0, err.decode()[-400:])
        self.assertEqual(json.loads((self.d / "decisions.json").read_text(encoding="utf-8"))["smooth-2"]["decision"], "skip")

    def test_fix_uses_the_shared_lock(self):
        from hypnomix.core import atomic
        from hypnomix.workflow import fix
        self.assertIs(fix.decisions_lock, atomic.decisions_lock)

    def test_the_app_and_the_review_take_it_for_every_write(self):
        from hypnomix.app import server as SV
        from hypnomix.workflow import oversight as O, review as R
        with mock.patch.dict(os.environ, {"HYPNOMIX_APP_HOME": str(self.root)}):
            cases = {
                "review.record": lambda: R.record(self.d, "smooth-1", "approve"),
                "review.record_like": lambda: R.record_like(self.d, "smooth-1", "approve"),
                "server.record_many": lambda: SV.record_many(self.d, ["smooth-1", "smooth-2"], "skip"),
                "server.record_one": lambda: SV.record_one(self.d, "smooth-1", "skip"),
                "server.patch_heard": lambda: ((self.d / "heard.json").write_text(json.dumps({"smooth-1": {"a": "x"}}), encoding="utf-8"), SV.patch_heard(self.d, ["smooth-1"])),
                "server.restore_decisions": lambda: SV.restore_decisions(self.d, fresh=True),
                "server.set_aside_decisions": lambda: SV.set_aside_decisions(self.d),
                "oversight.settle": lambda: O.settle(self.d, "smooth-1", "mine"),
            }
            for what, fn in cases.items():
                (self.d / "decisions.json").write_text(json.dumps({"smooth-1": {"decision": "skip", "conflicts": [{"by": "x", "decision": "approve"}]}}), encoding="utf-8")
                taken, p = self.entered()
                with p:
                    try:
                        fn()
                    except (ValueError, RuntimeError) as e:       # what the writer refuses is its business: it must have locked first
                        pass
                self.assertIn(self.d, taken, f"{what} wrote decisions.json without the lock")

    def test_a_rescan_takes_it_for_its_writes(self):
        from hypnomix.workflow import scan
        (self.d / "decisions.json").write_text(json.dumps({"gone-1": {"decision": "approve"}}), encoding="utf-8")
        old = [dict(id="gone-1", tool="smooth", kind="click", track="Vox", where="1.1.00")]
        new = [dict(id="smooth-1", tool="smooth", kind="click", track="Vox", where="9.1.00")]
        taken, p = self.entered()
        with p:
            scan.carry_decisions(self.d, old, new)
        self.assertIn(self.d, taken)

    def test_the_dawreview_clear_takes_it(self):
        from hypnomix.app import dawreview as DR, server as SV
        (self.d / "decisions.json").write_text(json.dumps({"smooth-1": {"decision": "skip"}}), encoding="utf-8")
        taken, p = self.entered()
        with mock.patch.dict(os.environ, {"HYPNOMIX_APP_HOME": str(self.root)}), p, \
                mock.patch.object(SV, "decisions_ok", lambda d: None):
            code, body = DR.handle_post(SV, "/api/dawreview/decide", dict(dir=str(self.d), id="smooth-1", decision="clear"))
        self.assertEqual(code, 200)
        self.assertIn(self.d, taken)
        self.assertNotIn("smooth-1", json.loads((self.d / "decisions.json").read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------------------------------------------------
def write_wav(path, seconds=2.0, sr=22050, nan=False, f=220.0):
    t = np.arange(int(seconds * sr)) / sr
    y = (0.3 * np.sin(2 * np.pi * f * t)).astype(np.float32)
    if nan:
        y[100:110] = np.nan
    sf.write(str(path), y, sr, subtype="FLOAT")
    return Path(path)


class Reads(unittest.TestCase):
    """The tools that read a person's file read it through the checked loader: a broken file ends in one plain sentence."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name)
        self.bad = write_wav(self.root / "broken.wav", nan=True)

    def raises_one_sentence(self, fn, *a):
        from hypnomix.core import dsp
        with self.assertRaises(dsp.AudioReadError) as cm:
            fn(*a)
        self.assertIn("broken sample", str(cm.exception))

    def test_pitchcheck_spectrogram_reference_sidechain_voices(self):
        from hypnomix.ears import pitchcheck, reference, spectrogram
        from hypnomix.engineer import sidechain
        from hypnomix.studio import voices
        self.raises_one_sentence(pitchcheck.f0, str(self.bad))
        self.raises_one_sentence(spectrogram.render, str(self.bad), self.root)
        self.raises_one_sentence(reference.avg_spectrum, self.bad)
        self.raises_one_sentence(sidechain.load_mono, self.bad)
        self.raises_one_sentence(voices.phrases_of, str(self.bad), 0.5, 0.3)
        self.raises_one_sentence(voices.measure, str(self.bad), 2.0)

    def test_tunes_inner_reads(self):
        from hypnomix.core import dsp
        src = (PKG / "studio" / "tune.py").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"sf\.read\(str\(in_path\)")
        self.assertNotRegex(src, r"sf\.read\(a\.guide")
        self.assertIn("dsp.load(in_path)", src)
        self.assertIn("dsp.load(a.guide)", src)

    def test_no_tool_reads_a_persons_file_with_a_bare_soundfile_read(self):
        """The reads that are left are the tool's own temporary output (tune's pieces) or a rate/length look (sf.info)."""
        for rel in ("ears/pitchcheck.py", "ears/spectrogram.py", "ears/reference.py", "engineer/sidechain.py", "studio/voices.py"):
            self.assertNotIn("sf.read(", (PKG / rel).read_text(encoding="utf-8"), rel)

    def run_dehiss(self, *argv):
        from hypnomix.studio import dehiss
        err = io.StringIO()
        with mock.patch.object(sys, "argv", ["hypnomix dehiss", *argv]), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(err):
            try:
                dehiss.main()
                return 0, err.getvalue()
            except SystemExit as e:
                return e.code, err.getvalue()

    def test_dehiss_never_overwrites(self):
        src = write_wav(self.root / "in.wav")
        out = self.root / "out.wav"
        code, _ = self.run_dehiss(str(src), str(out), "--reduce", "0", "--gate", "0")
        self.assertEqual(code, 0)
        first = out.read_bytes()
        code, err = self.run_dehiss(str(src), str(out), "--reduce", "0", "--gate", "0")
        self.assertIn("already exists", str(code))                    # refused (sys.exit with the sentence), before any work
        self.assertEqual(out.read_bytes(), first)
        code, _ = self.run_dehiss(str(src), str(src))
        self.assertIn("refusing to overwrite the input", str(code))
        self.assertEqual(sf.info(str(src)).frames, int(2.0 * 22050))

    def test_dehiss_default_output_is_not_reused_either(self):
        src = write_wav(self.root / "a unique stem for the default folder.wav")
        code, _ = self.run_dehiss(str(src), "--reduce", "0", "--gate", "0")
        self.assertEqual(code, 0)
        code, _ = self.run_dehiss(str(src), "--reduce", "0", "--gate", "0")
        self.assertIn("already exists", str(code))


# ---------------------------------------------------------------------------------------------------------------------
@_isolate.POSIX_ONLY
class Helper(unittest.TestCase):
    """The Mac update helper, run for real in bash against stand-ins for hdiutil and ditto: its mount folder is let go of
    whichever way it ends, and it lives in $TMPDIR."""

    def setUp(self):
        if not shutil.which("bash"):
            self.skipTest("no bash")
        from hypnomix.app import update as UP
        self.UP = UP
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        r = Path(self.td.name).resolve()
        self.r, self.tmp, self.bin = r, r / "tmp", r / "bin"
        self.tmp.mkdir()
        self.bin.mkdir()
        self.app = r / "Apps" / "Hypnomix.app"
        self.app.mkdir(parents=True)
        self.dmg = r / "x.dmg"
        self.dmg.write_bytes(b"image")
        self.sha = hashlib.sha256(b"image").hexdigest()
        self.log = r / "update.log"
        self.calls = r / "calls.txt"

    def stub(self, name, body):
        f = self.bin / name
        f.write_text("#!/bin/bash\n" + body + "\n", encoding="utf-8")
        f.chmod(0o755)

    def run_helper(self, hdiutil_attach_ok=True, app_in_image=True, ditto_ok=True):
        calls = self.calls
        self.stub("hdiutil", f'''echo "hdiutil $*" >> "{calls}"
if [ "$1" = attach ]; then
  [ "{int(hdiutil_attach_ok)}" = 1 ] || exit 1
  for a in "$@"; do last="$prev"; prev="$a"; done
  while [ $# -gt 0 ]; do [ "$1" = -mountpoint ] && MP="$2"; shift; done
  [ "{int(app_in_image)}" = 1 ] && mkdir -p "$MP/Hypnomix.app"
  echo "$MP" >> "{calls}.mnt"
  exit 0
fi
if [ "$1" = detach ] || [ "$2" = detach ]; then
  for a in "$@"; do P="$a"; done
  rm -rf "$P/Hypnomix.app"; exit 0
fi''')
        self.stub("ditto", f'echo "ditto $*" >> "{calls}"; [ "{int(ditto_ok)}" = 1 ] || exit 1; mkdir -p "$2"')
        helper = self.r / "helper.sh"
        helper.write_text(self.UP.MAC_HELPER, encoding="utf-8")
        env = dict(os.environ, PATH=f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin", TMPDIR=str(self.tmp) + "/", HYPNOMIX_UPDATE_GRACE="1")
        r = subprocess.run(["/bin/bash", str(helper), str(self.app), str(self.dmg), "", "", "", str(self.log), self.sha, "-"],
                           env=env, capture_output=True, text=True, timeout=60, encoding="utf-8")
        text = self.calls.read_text(encoding="utf-8") if self.calls.exists() else ""
        return r.returncode, text

    def leftovers(self):
        return sorted(p.name for p in self.tmp.iterdir())

    def test_a_failed_copy_detaches_and_removes_the_folder(self):
        code, calls = self.run_helper(ditto_ok=False)
        self.assertEqual(code, 1)
        self.assertIn("hdiutil attach", calls)
        self.assertIn("detach", calls)
        self.assertEqual(self.leftovers(), [])

    def test_an_image_without_the_app_detaches_and_removes_the_folder(self):
        code, calls = self.run_helper(app_in_image=False)
        self.assertEqual(code, 1)
        self.assertIn("detach", calls)
        self.assertEqual(self.leftovers(), [])

    def test_a_failed_attach_still_removes_the_folder(self):
        code, calls = self.run_helper(hdiutil_attach_ok=False)
        self.assertEqual(code, 1)
        self.assertNotIn("detach", calls)                          # nothing was mounted: nothing to detach
        self.assertEqual(self.leftovers(), [])

    def test_the_folder_is_made_in_tmpdir(self):
        self.run_helper(ditto_ok=False)
        mnt = Path((self.calls.parent / "calls.txt.mnt").read_text(encoding="utf-8").strip().splitlines()[0])
        self.assertEqual(mnt.parent, self.tmp)
        self.assertTrue(mnt.name.startswith("hypnomix-update."))

    def test_it_traps_every_way_out(self):
        h = self.UP.MAC_HELPER
        self.assertIn("trap unmount EXIT", h)
        self.assertNotIn("mktemp -d /tmp/", h)
        self.assertIn('${TMPDIR:-/tmp}', h)


# ---------------------------------------------------------------------------------------------------------------------
class Paths(unittest.TestCase):
    """The scan folder reaches a model with the home as "~", and comes back in that form."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.home = Path(self.td.name).resolve() / "someone"
        self.home.mkdir()
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home), "HYPNOMIX_USER_HOME": str(self.home),
                                                "HYPNOMIX_APP_HOME": str(self.home / "Documents" / "Hypnomix")})
        self.env.start()
        self.addCleanup(self.env.stop)
        from hypnomix.app import server as SV
        self.SV = SV
        self.d = scan_folder(SV.work())

    def test_scan_dir_takes_the_tilde_form(self):
        short = "~/Documents/Hypnomix/scan/Song"
        self.assertEqual(self.SV.scan_dir(short), self.d.resolve())
        self.assertEqual(self.SV.scan_dir(str(self.d)), self.d.resolve())
        with self.assertRaises(ValueError):
            self.SV.scan_dir("~/Documents")                        # still only the app's own scans

    def test_list_songs_and_read_review_show_the_tilde_and_take_it_back(self):
        from hypnomix.app import chat as CH
        def slashes(text):                  # on Windows the shown form is ~\Documents\..., and JSON text doubles each backslash
            return text.replace("\\\\", "/").replace("\\", "/")
        listed = CH._tool("list_songs", {})
        self.assertIn("~/Documents/Hypnomix/scan/Song", slashes(listed))
        self.assertNotIn(str(self.home), listed)
        self.assertNotIn(json.dumps(str(self.home))[1:-1], listed)          # the folder as JSON writes it (doubled backslashes)
        review = CH._tool("read_review", {"dir": "~/Documents/Hypnomix/scan/Song"})
        self.assertNotIn(str(self.home), review)
        self.assertNotIn(json.dumps(str(self.home))[1:-1], review)
        body = json.loads(review[len(CH.DATA_OPEN):-len(CH.DATA_CLOSE)].strip())
        self.assertEqual(slashes(body["dir"]), "~/Documents/Hypnomix/scan/Song")
        self.assertEqual(body["total"], 2)
        again = CH._tool("read_review", {"dir": body["dir"]})          # the form it was given comes back and works
        self.assertEqual(json.loads(again[len(CH.DATA_OPEN):-len(CH.DATA_CLOSE)].strip())["total"], 2)

    def test_a_windows_home_outside_users_is_shortened_inside_json_text_too(self):
        """JSON text doubles every backslash of a Windows path, so the home folder as it is written there never matched
        the plain one: only a home under C:\\Users was caught, by the loose pattern, and D:\\Profiles\\someone went out whole."""
        from hypnomix.app import daw_assist as DA
        home = "D:\\Profiles\\someone"
        with mock.patch.dict(os.environ, {"HYPNOMIX_USER_HOME": home}):
            shown = DA.home_short(json.dumps({"dir": home + "\\Documents\\Hypnomix\\scan\\Song"}))
        self.assertNotIn("someone", shown)
        self.assertEqual(json.loads(shown)["dir"], "~\\Documents\\Hypnomix\\scan\\Song")

    def test_run_hypnomix_hands_the_command_the_real_folder(self):
        """The shortened form is what the Assistant is shown, and a command is run without a shell: the "~" must be
        expanded before the subprocess sees it (--flag=~/x too), and nothing else is touched."""
        from hypnomix.app import chat as CH
        seen = []
        with mock.patch.object(CH, "run_cli", lambda cmd, args: seen.append((cmd, list(args))) or "ok"), \
                mock.patch.object(CH, "ask_ok", lambda *a, **k: True):          # a write asks first: the person says yes
            CH._tool("run_hypnomix", {"command": "fix", "args": ["~/Documents/Hypnomix/scan/Song", "--decide", "a-1=skip",
                                                                 "--out=~/Documents/Hypnomix/scan/Song", "~5 dB", "~someone"]})
        self.assertEqual(len(seen), 1)
        cmd, args = seen[0]
        real = str(self.home / "Documents" / "Hypnomix" / "scan" / "Song")
        self.assertEqual(cmd, "fix")
        self.assertEqual(Path(args[0]), Path(real))                 # expanduser keeps the separators it was given: "/" or "\\" are the same folder
        self.assertTrue(args[3].startswith("--out="))
        self.assertEqual(Path(args[3].split("=", 1)[1]), Path(real))
        self.assertEqual(args[4:], ["~5 dB", "~someone"])           # only "~" and "~/..." mean the home folder
        self.assertEqual(CH.expand_home(["~", "x~/y"]), [str(self.home), "x~/y"])

    def test_the_web_routes_take_the_tilde_form_too(self):
        d = self.SV.scan_dir("~/Documents/Hypnomix/scan/Song")
        self.assertTrue((d / "findings.json").exists())


# ---------------------------------------------------------------------------------------------------------------------
class Page(unittest.TestCase):
    """The page side of the contract, checked in the files (the repository has no browser; the Hear it card and Enter
    are also run with stand-ins in tests/test_daw_assistant.py)."""

    def js(self, name):
        return read("hypnomix/app/daw/js/" + name)

    def test_the_review_scan_ends_hear_it_and_sends_save_true(self):
        rv = self.js("review.js")
        scan = rv[rv.index("function scan(skipAsk)"):rv.index("/* ── select")]
        self.assertIn("{ save: true }", scan)                                           # never {} : a dirty session is saved on purpose
        self.assertLess(scan.index("HX.endAuditions('scanning')"), scan.index("'/api/dawreview/scan'"))
        self.assertIn("Save and scan", rv)
        self.assertRegex(scan, r"error === 'unsaved'")                                   # a 409 is a sentence, not a raw error

    def test_every_save_the_page_sends_ends_hear_it(self):
        mcp = self.js("mcp.js")
        call = mcp[mcp.index("async call(name, args, opts)"):mcp.index("async connect()")]
        self.assertIn("name === 'session_save'", call)
        self.assertLess(call.index("endAuditions"), call.index("mcp.rpc('tools/call'"))
        app = self.js("app.js")
        save = app[app.index("HX.saveSession = async function"):app.index("HX.on('live', syncSave)")]
        self.assertLess(save.index("endAuditions('saving')"), save.index("'/api/daw/save'"))

    def test_the_hear_it_card_says_plainly_that_it_is_live(self):
        a = self.js("assistant.js")
        self.assertIn("LIVE NOW", a)
        self.assertIn("never saved", a)

    def test_enter_is_not_a_card_key(self):
        app, a = self.js("app.js"), self.js("assistant.js")
        self.assertNotIn("HX.cardKey('Enter')", a)
        self.assertNotRegex(app, r"""e\.key === 'Enter'[^\n]*HX\.cardKey""")
        self.assertRegex(app, r"e\.key === 'Escape' && !e\.repeat && HX\.cardKey")
        self.assertIn("APPROVE_AFTER = 800", a)
        self.assertEqual(a.count("tooSoon(e,"), 2)                                      # the demo card and the real card

    def test_new_session_path_is_split_without_cutting_the_name(self):
        from tests import _jscheck
        runner = _jscheck.need_runner(self)
        app = self.js("app.js")
        fn = app[app.index("HX.splitNewPath = function"):app.index("/* the Mac app's File")]
        prog = "var HX = {};\n" + fn + """
var out = ['~/Music/New Song', 'Song', '/Song', '  ~/Music/A Song/  ', ''].map(function (v) { return HX.splitNewPath(v); });
print(JSON.stringify(out));"""
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "t.js"
            f.write_text(prog, encoding="utf-8")
            r = subprocess.run(runner + [str(f)], capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        got = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(got, [{"folder": "~/Music", "name": "New Song"}, {"folder": ".", "name": "Song"}, {"folder": "/", "name": "Song"},
                               {"folder": "~/Music", "name": "A Song"}, {"folder": ".", "name": ""}])
        self.assertNotIn("v.slice(0, i) || '.'", app)

    def test_the_updater_and_the_quit_ask_about_unsaved_work(self):
        up = read("hypnomix/app/update.py")
        self.assertIn("if unsaved():", up)
        self.assertIn("Save it first", up)
        swift = read("macapp/Hypnomix.swift")
        for word in ("applicationShouldTerminate", "serverIsDirty", "Quit anyway and lose the unsaved changes?"):
            self.assertIn(word, swift)

    def test_the_review_message_points_at_the_save_button(self):
        self.assertIn("press Save in the DAW tab once", read("hypnomix/app/dawreview.py"))


class Parse(unittest.TestCase):
    """The parse check itself: it must notice a broken script, and say what is missing when it cannot run."""

    def test_a_broken_script_is_reported_and_a_good_one_is_not(self):
        from tests import _jscheck
        if _jscheck.engine() is None:
            self.skipTest(_jscheck.MISSING)
        with tempfile.TemporaryDirectory() as td:
            good, bad = Path(td) / "good.js", Path(td) / "bad.js"
            good.write_text("(function () { var a = 1; return a; })();", encoding="utf-8")
            bad.write_text("var a = ;", encoding="utf-8")
            self.assertEqual(_jscheck.parse({"good": good}), [])
            problems = _jscheck.parse({"good": good, "bad": bad})
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("bad:"), problems)

    def test_with_no_engine_it_is_a_named_skip_not_a_pass(self):
        from tests import _jscheck
        with mock.patch.object(_jscheck, "engine", lambda: None):
            with self.assertRaises(_jscheck.Missing) as cm:
                _jscheck.parse({})
        self.assertIn("Node.js", str(cm.exception))
        self.assertIn("osascript", str(cm.exception))

    def test_a_script_runner_is_node_with_print_else_jsc_else_a_named_skip(self):
        from tests import _jscheck
        with mock.patch.object(_jscheck.shutil, "which", lambda n: "/x/node" if n == "node" else None):
            self.assertEqual(_jscheck.runner(), ["/x/node", "--require", str(_jscheck.PRINT_SHIM)])
        self.assertIn("globalThis.print", _jscheck.PRINT_SHIM.read_text(encoding="utf-8"))
        with mock.patch.object(_jscheck.shutil, "which", lambda n: None), mock.patch.object(_jscheck.os.path, "exists", lambda p: False):
            self.assertIsNone(_jscheck.runner())
            with self.assertRaises(unittest.SkipTest) as cm:
                _jscheck.need_runner(self)
        self.assertIn("Node.js", str(cm.exception))
        self.assertIn("JavaScriptCore", str(cm.exception))
        self.assertIn("NOT run", str(cm.exception))

    def test_every_page_script_is_found(self):
        from tests import _jscheck
        with tempfile.TemporaryDirectory() as td:
            found = _jscheck.scripts(td)
        on_disk = {p.name for p in APPJS.glob("*.js")} | {"daw/js/" + p.name for p in (APPJS / "daw" / "js").glob("*.js")}
        self.assertTrue(on_disk <= set(found), on_disk - set(found))


if __name__ == "__main__":
    unittest.main()
