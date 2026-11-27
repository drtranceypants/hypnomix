"""DAW mode: the engine supervisor (with a stand-in engine that prints the READY line), the app's /mcp proxy, the
DAW view's files, and the Assistant using the engine's own tools (reads at once, changes only after Approve)."""
import json, os, signal, subprocess, sys, tempfile, textwrap, threading, time, types, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from hypnomix.app import daw as DW

FAKE = textwrap.dedent('''\
    #!{python}
    # A stand-in for hypnomix-engine: an MCP surface on a free port, the READY line, and a record of each call.
    import json, os, sys, http.server
    args, opts = [], {{"new": False, "port": 4820}}
    it = iter(sys.argv[1:])
    for a in it:                       # the real engine's options: --port N, --new, -b BACKEND, then DIR [SNAPSHOT]
        if a == "--":                  # (getopt: everything after it is a name, never an option)
            args += list(it)
        elif a == "--port": opts["port"] = int(next(it))
        elif a == "--new": opts["new"] = True
        elif a == "-b": opts["backend"] = next(it)
        elif a == "--parent-pid": opts["parent_pid"] = int(next(it))
        elif a in ("--output-device", "--input-device", "-d"): opts[a.strip("-")] = next(it)
        else: args.append(a)
    opts["dir"], opts["snapshot"] = (args + [None, None])[:2]
    mode = os.environ.get("HYPNOMIX_FAKE_ENGINE_MODE")
    bad = os.environ.get("HYPNOMIX_FAKE_ENGINE_BAD")       # a session folder it refuses to load
    if bad and bad in (opts["dir"] or ""):
        print("HYPNOMIX-ENGINE ERROR session cannot be loaded: " + opts["dir"], flush=True)
        sys.exit(1)
    pids = os.environ.get("HYPNOMIX_FAKE_ENGINE_PIDS")
    if pids:                           # one line per engine started: the test counts the ones still alive
        with open(pids, "a") as f:
            f.write("%d\\n" % os.getpid())
    if opts.get("parent_pid") and not os.environ.get("HYPNOMIX_FAKE_ENGINE_NO_PARENT"):   # like the real engine: stop when the app that started it is gone
        import threading as _t, time as _time
        def _watch():
            while True:
                _time.sleep(0.1)
                try:
                    os.kill(opts["parent_pid"], 0)
                except OSError:
                    os._exit(0)
        _t.Thread(target=_watch, daemon=True).start()
    if mode == "die":                  # the audio engine halted
        print("loading...", flush=True)
        sys.exit(3)
    if mode == "error":
        print("HYPNOMIX-ENGINE ERROR session not found: x", flush=True)
        sys.exit(1)
    if mode == "noaudio" and opts.get("backend") != "None (Dummy)":   # no audio device would start (the real words)
        print('HYPNOMIX-ENGINE ERROR cannot start the audio engine (backend "CoreAudio")', flush=True)
        sys.exit(1)
    if mode == "hang" and opts.get("backend") != "None (Dummy)":      # an audio device that never answers
        import time
        time.sleep(600)
    log = os.environ.get("HYPNOMIX_FAKE_ENGINE_CALLS")
    TOOLS = [
        {{"name": "session_get_info", "title": "Session Info", "description": "Return basic session info.",
         "inputSchema": {{"type": "object", "properties": {{}}, "additionalProperties": False}}}},
        {{"name": "track_get_info", "title": "Track Info", "description": "Return one track's info.",
         "inputSchema": {{"type": "object", "properties": {{"id": {{"type": "string"}}}}, "required": ["id"]}}}},
        {{"name": "tracks_list", "title": "List Tracks", "description": "List tracks.",
         "inputSchema": {{"type": "object", "properties": {{"includeHidden": {{"type": "boolean"}}}}}}}},
        {{"name": "track_set_fader_db", "title": "Set Fader (dB)", "description": "Set a track's fader in dB.",
         "inputSchema": {{"type": "object", "properties": {{"id": {{"type": "string"}}, "db": {{"type": "number"}}}},
                         "required": ["id", "db"]}}}},
        {{"name": "transport/play", "title": "Play", "description": "Start the transport.",
         "inputSchema": {{"type": "object", "properties": {{}}}}}},
    ]
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if "id" not in req:                      # a notification
                self.send_response(202); self.send_header("Content-Length", "0"); self.end_headers(); return
            m, p = req["method"], req.get("params") or {{}}
            if m == "initialize":
                res = {{"protocolVersion": "2025-03-26", "serverInfo": {{"name": "ardour-mcp-http", "version": "1"}}}}
            elif m == "tools/list":
                res = {{"tools": TOOLS}}
            elif m == "tools/call":
                if log:
                    with open(log, "a") as f:
                        f.write(json.dumps(p) + "\\n")
                if p["name"] == "session_get_info":
                    res = {{"structuredContent": {{"sessionName": "Song", "argv": opts, "cwd": os.getcwd(),
                                                   "envkeys": sorted(os.environ)}}}}
                elif p["name"] == "will_fail":
                    res = {{"isError": True, "content": [{{"type": "text", "text": "no"}}]}}
                else:
                    res = {{"structuredContent": {{"ok": True, "called": p["name"], "arguments": p.get("arguments")}}}}
            else:
                out = json.dumps({{"jsonrpc": "2.0", "id": req["id"], "error": {{"code": -32601, "message": "no such method"}}}}).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out); return
            out = json.dumps({{"jsonrpc": "2.0", "id": req["id"], "result": res}}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", opts["port"] if "--port" in sys.argv else 0), H)
    print("engine log line", flush=True)
    if mode == "lookalike_first":      # log lines that only CONTAIN the markers, before the real READY (a track or file name)
        print("warning: track named HYPNOMIX-ENGINE ERROR boom is silent", flush=True)
        print("warning: file x HYPNOMIX-ENGINE READY port=8977 ws=0 is not a line", flush=True)
    if mode == "bytes_first":          # a stray non-UTF-8 byte in a log line before READY
        sys.stdout.buffer.write(b"warning: cannot open caf\\xe9.wav\\n"); sys.stdout.flush()
    print('HYPNOMIX-ENGINE READY port=%d ws=0 backend="%s"' % (srv.server_address[1], opts.get("backend", "CoreAudio")), flush=True)
    if mode == "bytes_after":
        sys.stdout.buffer.write(b"warning: cannot open caf\\xe9.wav\\n"); sys.stdout.flush()
    if mode == "spoof":                # text of other files and tracks: READY / ERROR inside a line, a whole READY line on
        import time as _time           # stderr, a whole READY line for another port (not the one it was given)
        _time.sleep(0.3)
        print("warning: cannot read file HYPNOMIX-ENGINE READY port=8977 (x.wav)", flush=True)
        print("HYPNOMIX-ENGINE READY port=8977 ws=0", flush=True)
        print("not an error: HYPNOMIX-ENGINE ERROR boom", flush=True)
        print("HYPNOMIX-ENGINE ERROR late and ignored", flush=True)
        print("HYPNOMIX-ENGINE READY port=8977", file=sys.stderr, flush=True)
    if mode == "quit":                 # it ends by itself, exit status 0, without being asked
        import threading, time
        threading.Thread(target=lambda: (time.sleep(0.6), os._exit(0)), daemon=True).start()
    srv.serve_forever()
''')


_ISO = []


def setUpModule():
    """Whatever the suite was started with, an engine started here must not write the real daw.json ("last session")."""
    _ISO.append(tempfile.TemporaryDirectory())
    _ISO.append(mock.patch.dict(os.environ, {"HYPNOMIX_HOME": _ISO[0].name}))
    _ISO[1].start()


def tearDownModule():
    _ISO[1].stop()
    _ISO[0].cleanup()


def make_fake(folder):
    f = Path(folder) / "hypnomix-engine"
    f.write_text(FAKE.format(python=sys.executable))
    f.chmod(0o755)
    return f


def with_session(eng, folder):
    """The real engine needs a session to run (Start with none waits for New / Open): give the engine one."""
    d = Path(folder) / "Song"
    d.mkdir(exist_ok=True)
    (d / "Song.ardour").write_text("<Session/>")
    eng.session = str(d / "Song.ardour")
    return eng


def wait(cond, timeout=15):
    t = time.time()
    while time.time() - t < timeout:
        if cond():
            return True
        time.sleep(0.05)
    return False


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class Supervisor(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.bin = make_fake(self.td.name)
        self.eng = with_session(DW.Engine(binary=self.bin, attach_url="http://127.0.0.1:9/mcp"), self.td.name)

    def tearDown(self):
        self.eng.stop()
        self.td.cleanup()

    def test_start_ready_call_stop(self):
        st = self.eng.start()
        self.assertEqual((st["state"], st["mode"], st["connected"]), ("running", "engine", True))
        self.assertTrue(st["url"].startswith("http://127.0.0.1:") and st["url"].endswith("/mcp"))
        self.assertIn("engine log line", st["log"])
        pid = st["pid"]
        self.assertTrue(alive(pid))
        argv = self.eng.call("tools/call", {"name": "session_get_info", "arguments": {}})["structuredContent"]["argv"]
        self.assertEqual((argv["dir"], argv["new"], argv["port"]), (str(Path(self.td.name) / "Song"), False, st["port"]))   # on the port it was given
        self.assertEqual(argv["parent_pid"], os.getpid())     # the engine stops by itself if the app dies
        self.assertNotEqual(st["port"], 4820)                                               # never the window's port
        self.assertEqual(len(self.eng.tools()), 5)
        st = self.eng.stop()
        self.assertEqual((st["state"], st["connected"], st["pid"]), ("stopped", False, None))
        self.assertTrue(wait(lambda: not alive(pid), 5))
        code, raw = self.eng.rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(code, 503)
        self.assertIn("not running", json.loads(raw)["error"]["message"])

    def test_open_and_new_session(self):
        sess = Path(self.td.name) / "Song"
        sess.mkdir(exist_ok=True)
        (sess / "Song.ardour").write_text("<Session/>")
        self.eng.open(sess)                                       # a folder opens its own snapshot
        info = self.eng.call("tools/call", {"name": "session_get_info", "arguments": {}})["structuredContent"]
        self.assertEqual((info["argv"]["dir"], info["argv"]["snapshot"], info["argv"]["new"]), (str(sess), "Song", False))
        self.assertEqual(self.eng.status()["session"], str(sess / "Song.ardour"))
        with self.assertRaises(ValueError):
            self.eng.open(Path(self.td.name) / "nothing.ardour")
        self.eng.new_session(self.td.name, "New Song")
        info = self.eng.call("tools/call", {"name": "session_get_info", "arguments": {}})["structuredContent"]
        self.assertEqual((info["argv"]["dir"], info["argv"]["snapshot"], info["argv"]["new"]),
                         (str(Path(self.td.name) / "New Song"), "New Song", True))
        with self.assertRaises(ValueError):
            self.eng.new_session(self.td.name, "Song")            # already there: never over an existing session
        with self.assertRaises(ValueError):
            self.eng.new_session(self.td.name, "a/b")

    def test_restarts_after_a_crash_on_the_same_session(self):
        sess = Path(self.td.name) / "Song.ardour"
        sess.write_text("<Session/>")
        pid = self.eng.start(session=sess)["pid"]
        os.kill(pid, signal.SIGKILL)
        self.assertTrue(wait(lambda: self.eng.status()["pid"] not in (None, pid) and self.eng.state == "running"))
        st = self.eng.status()
        self.assertEqual(st["restarts"], 1)
        self.assertIn("exit code", "\n".join(st["log"]))
        info = self.eng.call("tools/call", {"name": "session_get_info", "arguments": {}})["structuredContent"]
        self.assertEqual((info["argv"]["dir"], info["argv"]["snapshot"]), (self.td.name, "Song"))

    def test_gives_up_when_it_keeps_crashing(self):
        with mock.patch.dict(os.environ, {"HYPNOMIX_FAKE_ENGINE_MODE": "die"}):
            self.eng.start(wait=False)
            self.assertTrue(wait(lambda: self.eng.state == "failed"))
        st = self.eng.status()
        self.assertEqual(st["restarts"], DW.MAX_RESTARTS)
        self.assertIn("not started again", st["error"])
        self.assertFalse(st["connected"])

    def test_an_error_line_is_reported_not_retried(self):
        with mock.patch.dict(os.environ, {"HYPNOMIX_FAKE_ENGINE_MODE": "error", "HYPNOMIX_ENGINE_ARGS": '-b "None (Dummy)"'}):
            st = self.eng.start()
        self.assertEqual((st["state"], st["restarts"]), ("failed", 0))
        self.assertEqual(st["error"], "session not found: x")
        self.assertIn('--port', st["log"][0])
        self.assertIn("'None (Dummy)'", st["log"][0])                 # the extra arguments, kept whole

    def test_with_no_session_it_waits_for_new_or_open(self):
        eng = DW.Engine(binary=self.bin, attach_url="http://127.0.0.1:9/mcp")
        st = eng.start()
        self.assertEqual((st["state"], st["mode"], st["pid"], st["connected"]), ("stopped", None, None, False))
        self.assertIn("File → New Session", st["error"])
        sess = Path(self.td.name) / "Song" / "Song.ardour"
        with mock.patch.dict(os.environ, {"HYPNOMIX_HOME": self.td.name}):
            self.assertIsNone(DW.last_session())
            eng.start(session=sess)
            try:
                self.assertEqual(DW.last_session(), sess)          # the next start of the app opens it again
            finally:
                eng.stop()
            (Path(self.td.name) / "daw.json").write_text(json.dumps({"last": str(Path(self.td.name) / "gone.ardour")}))
            self.assertIsNone(DW.last_session())                   # moved or deleted since: nothing

    def test_a_new_session_once_made_is_opened_on_a_restart(self):
        made = Path(self.td.name) / "Made"
        st = self.eng.new_session(self.td.name, "Made")
        self.assertEqual(st["new"], [self.td.name, "Made"])          # the stand-in makes no files: still "new"
        made.mkdir()
        (made / "Made.ardour").write_text("<Session/>")            # as the real engine does on --new
        st = self.eng.restart()                                     # (a crash restart reads READY the same way)
        self.assertEqual((st["session"], st["new"]), (str(made / "Made.ardour"), None))   # opened, never made again
        argv = self.eng.call("tools/call", {"name": "session_get_info", "arguments": {}})["structuredContent"]["argv"]
        self.assertEqual(argv["new"], True)                         # that start was still the --new one ...
        st = self.eng.restart()
        argv = self.eng.call("tools/call", {"name": "session_get_info", "arguments": {}})["structuredContent"]["argv"]
        self.assertEqual((argv["new"], argv["dir"], argv["snapshot"]), (False, str(made), "Made"))   # ... this one opens it

    def test_no_audio_device_falls_back_to_dummy_and_says_so(self):
        with mock.patch.dict(os.environ, {"HYPNOMIX_FAKE_ENGINE_MODE": "noaudio"}):
            os.environ.pop("HYPNOMIX_ENGINE_ARGS", None)
            st = self.eng.start()
            self.assertEqual((st["state"], st["connected"], st["dummy"], st["backend"]), ("running", True, True, "None (Dummy)"))
            self.assertIn("without sound", st["notice"])
            self.assertIn("press Restart", st["notice"])
            self.assertEqual((st["restarts"], st["error"]), (0, ""))          # not a crash, and not an error
            argv = self.eng.call("tools/call", {"name": "session_get_info", "arguments": {}})["structuredContent"]["argv"]
            self.assertEqual(argv["backend"], "None (Dummy)")
            self.assertIn("Dummy backend", "\n".join(st["log"]))
            st = self.eng.restart()                                        # Restart tries the device first again
            self.assertEqual((st["state"], st["dummy"]), ("running", True))
            self.assertEqual(sum("cannot start the audio engine" in l for l in self.eng.log), 2)

    def test_a_device_that_never_answers_falls_back_to_dummy(self):
        with mock.patch.dict(os.environ, {"HYPNOMIX_FAKE_ENGINE_MODE": "hang"}), mock.patch.object(DW, "READY_TIMEOUT", 1.5):
            os.environ.pop("HYPNOMIX_ENGINE_ARGS", None)
            st = self.eng.start()
            self.assertEqual((st["state"], st["dummy"], st["backend"], st["restarts"]), ("running", True, "None (Dummy)", 0))
            self.assertIn("did not answer", st["notice"])
            time.sleep(0.5)
            self.assertEqual(self.eng.status()["state"], "running")      # the killed one is not taken for a crash

    def test_the_default_output_and_no_input_are_passed_on_a_mac(self):
        with mock.patch.object(DW.sys, "platform", "darwin"), mock.patch.object(DW, "default_output", lambda: "Speakers"):
            self.assertEqual(DW.audio_args([]), ["--output-device", "Speakers", "--input-device", "None"])
            self.assertEqual(DW.audio_args(["--input-device", "Mic"]), ["--output-device", "Speakers"])
            self.assertEqual(DW.audio_args(["--output-device=X"]), ["--input-device", "None"])
            self.assertEqual(DW.audio_args(["-b", "None (Dummy)"]), [])
            self.assertEqual(DW.audio_args(["-d", "Interface"]), [])
        with mock.patch.object(DW.sys, "platform", "darwin"), mock.patch.object(DW, "default_output", lambda: ""):
            self.assertEqual(DW.audio_args([]), ["--input-device", "None"])
        with mock.patch.object(DW.sys, "platform", "linux"):
            self.assertEqual(DW.audio_args([]), [])

    def test_a_chosen_device_that_fails_falls_back_without_it(self):
        with mock.patch.dict(os.environ, {"HYPNOMIX_FAKE_ENGINE_MODE": "noaudio", "HYPNOMIX_ENGINE_ARGS": "--output-device Gone -V"}):
            st = self.eng.start()
            argv = self.eng.call("tools/call", {"name": "session_get_info", "arguments": {}})["structuredContent"]["argv"]
        self.assertEqual((st["state"], st["dummy"], argv["backend"]), ("running", True, "None (Dummy)"))
        self.assertNotIn("output-device", argv)                           # the Dummy backend has no devices
        self.assertEqual(DW.without_devices(["-d", "A", "--input-device=B", "--output-device", "C", "-V"]), ["-V"])

    def test_a_chosen_backend_that_fails_is_not_swapped_for_dummy(self):
        with mock.patch.dict(os.environ, {"HYPNOMIX_FAKE_ENGINE_MODE": "noaudio", "HYPNOMIX_ENGINE_ARGS": "-b CoreAudio"}):
            st = self.eng.start()
        self.assertEqual((st["state"], st["dummy"], st["notice"]), ("failed", False, ""))
        self.assertIn("cannot start the audio engine", st["error"])

    def test_a_working_device_says_its_backend(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("HYPNOMIX_ENGINE_ARGS", None)
            st = self.eng.start()
        self.assertEqual((st["backend"], st["dummy"], st["notice"]), ("CoreAudio", False, ""))

    def test_start_on_a_session_folder(self):
        sess = Path(self.td.name) / "Song"
        sess.mkdir(exist_ok=True)
        (sess / "Song.ardour").write_text("<Session/>")
        self.eng.start(session=sess)                              # `hypnomix app --daw --session DIR`, /api/daw/start
        info = self.eng.call("tools/call", {"name": "session_get_info", "arguments": {}})["structuredContent"]
        self.assertEqual((info["argv"]["dir"], info["argv"]["snapshot"]), (str(sess), "Song"))
        with self.assertRaises(ValueError):
            self.eng.start(session=Path(self.td.name) / "nothing")

    def test_a_stop_while_a_crash_is_handled_wins(self):
        self.eng.start()
        gen = self.eng._gen
        self.eng.stop()
        st = self.eng.start(wait=False, _restart_gen=gen)        # the watcher's restart, arriving after the stop
        self.assertEqual((st["state"], st["pid"]), ("stopped", None))

    def test_exiting_by_itself_is_said_and_keeps_the_session(self):
        # exit 0 without the app asking: "stopped unexpectedly", the session kept for Start, no restart loop
        sess = Path(self.td.name) / "Song.ardour"
        sess.write_text("<Session/>")
        with mock.patch.dict(os.environ, {"HYPNOMIX_FAKE_ENGINE_MODE": "quit"}):
            st = self.eng.start(session=sess)
            self.assertEqual(st["state"], "running")
            self.assertTrue(wait(lambda: self.eng.state == "exited"))
        time.sleep(0.4)
        st = self.eng.status()
        self.assertEqual((st["state"], st["connected"], st["pid"], st["restarts"]), ("exited", False, None, 0))
        self.assertEqual(st["session"], str(sess))                          # kept: Start opens it again
        self.assertIn("stopped unexpectedly", st["error"])
        self.assertIn("Start", st["error"])
        st = self.eng.start()                                               # Start (no arguments) = the same session
        self.assertEqual(st["state"], "running")
        info = self.eng.call("tools/call", {"name": "session_get_info", "arguments": {}})["structuredContent"]
        self.assertEqual((info["argv"]["dir"], info["argv"]["snapshot"]), (self.td.name, "Song"))

    def test_the_view_keeps_the_session_when_the_engine_goes(self):
        # app.js: an engine that went away is shown with Start; the mock song is loaded only when you ask for it
        js = (DW.ROOT / "js" / "app.js").read_text()
        watch = js[js.index("async function watchEngine"):js.index("setInterval(watchEngine")]
        self.assertNotIn("loadMock", watch)
        self.assertIn("engineLost(st)", watch)
        lost = js[js.index("function engineLost"):js.index("HX.engineLostShown")]
        self.assertNotIn("loadMock", lost)
        self.assertIn("'Start'", lost)
        self.assertIn("exited: 'Engine stopped unexpectedly'", js)
        self.assertIn("if (HX.engineLost && HX.api.inApp) return startAgain();", js)

    def test_a_stop_leaves_nothing_of_its_group(self):
        # a launcher script that ends on SIGTERM while the engine it started hangs on: stop ends the engine too
        launcher = Path(self.td.name) / "launch.sh"
        hung = Path(self.td.name) / "hung.pid"
        launcher.write_text(f"#!/bin/sh\n/bin/sh -c 'trap \"\" TERM; echo $$ > {hung}; while :; do sleep 1; done' &\n"
                            f"exec {self.bin} \"$@\"\n")
        launcher.chmod(0o755)
        eng = with_session(DW.Engine(binary=launcher, attach_url="http://127.0.0.1:9/mcp"), self.td.name)
        try:
            eng.start()
            self.assertTrue(wait(lambda: hung.exists() and hung.read_text().strip()))
            pid = int(hung.read_text())
            self.assertTrue(alive(pid))
            eng.stop(timeout=3)
            self.assertTrue(wait(lambda: not alive(pid), 5))
        finally:
            eng.stop()

    def test_a_stop_is_not_a_crash(self):
        self.eng.start()
        self.eng.stop()
        time.sleep(0.5)
        self.assertEqual((self.eng.state, self.eng.restarts), ("stopped", []))


class Isolation(unittest.TestCase):
    def test_an_engine_started_here_cannot_write_the_real_last_session(self):
        # Engine.start() keeps the open session in daw.json ("last"): the module's setUp has pointed HYPNOMIX_HOME at a
        # folder of its own, so `python -m unittest` bare never replaces the person's pointer.
        self.assertEqual(DW.conf_path().parent.resolve(), Path(_ISO[0].name).resolve())
        with tempfile.TemporaryDirectory() as td:
            eng = with_session(DW.Engine(binary=make_fake(td), attach_url="http://127.0.0.1:9/mcp"), td)
            try:
                eng.start()
                self.assertEqual(DW.last_session(), Path(eng.session))
            finally:
                eng.stop()
        self.assertEqual(DW.conf_path().parent.resolve(), Path(_ISO[0].name).resolve())


class Hardening(unittest.TestCase):
    """The supervisor under attack and under accident: two requests at once, odd bytes, text that looks like the engine's
    own words, a hung start, the environment it is given, names that look like options."""
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.bin = make_fake(self.td.name)
        self.pids = Path(self.td.name) / "pids.txt"
        self.env = mock.patch.dict(os.environ, {"HYPNOMIX_FAKE_ENGINE_PIDS": str(self.pids)})
        self.env.start()
        os.environ.pop("HYPNOMIX_ENGINE_ARGS", None)
        self.eng = with_session(DW.Engine(binary=self.bin, attach_url="http://127.0.0.1:9/mcp"), self.td.name)

    def tearDown(self):
        self.eng.stop()
        self.env.stop()
        self.td.cleanup()

    def started(self):
        return [int(x) for x in self.pids.read_text().split()] if self.pids.exists() else []

    def info(self):
        return self.eng.call("tools/call", {"name": "session_get_info", "arguments": {}})["structuredContent"]

    # -- one engine at a time
    def test_overlapping_restarts_never_leave_a_second_engine(self):
        self.eng.start()
        for _ in range(3):
            res = []

            def go():
                try:
                    res.append(self.eng.restart()["state"])
                except DW.Busy as e:
                    res.append(str(e))
            ts = [threading.Thread(target=go) for _ in range(3)]
            [t.start() for t in ts]
            [t.join(60) for t in ts]
            self.assertTrue(any(r == "running" for r in res), res)
            self.assertTrue(wait(lambda: self.eng.state == "running"))
            time.sleep(0.3)
            self.assertEqual([p for p in self.started() if alive(p)], [self.eng.status()["pid"]])
        self.eng.stop()
        self.assertTrue(wait(lambda: not any(alive(p) for p in self.started()), 5))

    def test_a_request_during_a_transition_is_told_to_wait(self):
        self.eng.start()
        with self.eng._transition():                        # stands for a restart in the middle of its work
            for f in (self.eng.restart, self.eng.stop, lambda: self.eng.open(self.eng.session),
                      lambda: self.eng.new_session(self.td.name, "Other"), self.eng.start):
                with self.assertRaises(DW.Busy):
                    f()
        self.assertEqual(self.eng.status()["state"], "running")        # none of them touched it
        self.assertEqual(len(self.started()), 1)

    def test_a_stop_never_forgets_a_newer_process(self):
        self.eng.start()
        fresh = types.SimpleNamespace(pid=1, poll=lambda: None)
        real = DW.Engine._signal

        def signalled(p, sig):
            real(p, sig)
            self.eng.proc = fresh                            # another start took its place while this one was ending
        with mock.patch.object(DW.Engine, "_signal", staticmethod(signalled)), self.eng._transition():
            self.eng._stop()
        self.assertIs(self.eng.proc, fresh)                  # only the process that was signalled is let go
        self.eng.proc = None

    # -- what it prints
    def test_a_stray_byte_after_ready_does_not_end_the_watching(self):
        with mock.patch.dict(os.environ, {"HYPNOMIX_FAKE_ENGINE_MODE": "bytes_after"}):
            pid = self.eng.start()["pid"]
            time.sleep(0.5)
            self.assertIn("caf", "\n".join(self.eng.log))                  # the line is kept, the byte replaced
            os.kill(pid, signal.SIGKILL)
            self.assertTrue(wait(lambda: self.eng.status()["restarts"] == 1 and self.eng.state == "running"))
        self.assertNotIn(pid, [self.eng.status()["pid"]])

    def test_a_stray_byte_before_ready_does_not_stop_ready(self):
        t = time.time()
        with mock.patch.dict(os.environ, {"HYPNOMIX_FAKE_ENGINE_MODE": "bytes_first"}):
            st = self.eng.start()
        self.assertEqual(st["state"], "running")
        self.assertLess(time.time() - t, 20)

    def test_ready_and_error_count_only_as_the_engines_own_line_for_its_own_port(self):
        with mock.patch.dict(os.environ, {"HYPNOMIX_FAKE_ENGINE_MODE": "spoof"}):
            st = self.eng.start()
            port = st["port"]
            time.sleep(0.9)                                  # the stand-in prints its look-alikes after READY
        st = self.eng.status()
        self.assertEqual((st["state"], st["port"]), ("running", port))
        self.assertEqual(st["url"], f"http://127.0.0.1:{port}/mcp")
        self.assertEqual(self.eng._failed, "")
        self.assertIn("HYPNOMIX-ENGINE READY port=8977", "\n".join(st["log"]))   # kept in the log, believed by no one

    def test_look_alike_lines_before_ready_are_not_the_engines_ready_or_error(self):
        # the case where the anchoring does the work: while it is still starting, text that only CONTAINS the markers
        self.assertIsNone(DW.ERROR.match("x HYPNOMIX-ENGINE ERROR y"))
        self.assertIsNone(DW.READY.match("x HYPNOMIX-ENGINE READY port=8977 ws=0"))
        with mock.patch.dict(os.environ, {"HYPNOMIX_FAKE_ENGINE_MODE": "lookalike_first"}):
            st = self.eng.start()
            self.assertEqual((st["state"], self.eng._failed), ("running", ""))
            self.assertNotEqual(st["port"], 8977)
            os.kill(st["pid"], signal.SIGKILL)                   # a crash is restarted, not reported as "failed"
            self.assertTrue(wait(lambda: self.eng.status()["restarts"] == 1 and self.eng.state == "running"))
        self.assertEqual(self.eng._failed, "")
        self.assertIn("track named HYPNOMIX-ENGINE ERROR boom", "\n".join(self.eng.log))

    def test_ready_for_another_port_is_not_believed_even_as_the_first_line(self):
        self.assertIsNone(DW.READY.match("warning: x HYPNOMIX-ENGINE READY port=1 y"))
        self.assertIsNone(DW.ERROR.match("warning: x HYPNOMIX-ENGINE ERROR y"))
        self.assertEqual(DW.READY.match('HYPNOMIX-ENGINE READY port=4821 ws=0 backend="CoreAudio"').group(1), "4821")
        self.eng._want = 5000
        self.eng.state, self.eng._gen = "starting", 7
        proc = types.SimpleNamespace(stdout=iter(["HYPNOMIX-ENGINE READY port=8977 ws=0\n"]), wait=lambda: 0)
        self.eng._read(proc, 7)
        self.assertNotEqual(self.eng.port, 8977)

    # -- starting, and not starting
    def test_a_start_with_another_session_while_running_changes_nothing(self):
        other = Path(self.td.name) / "Other" / "Other.ardour"
        other.parent.mkdir()
        other.write_text("<Session/>")
        pid = self.eng.start()["pid"]
        mine = self.eng.session
        with self.assertRaises(RuntimeError):
            self.eng.start(session=other)
        self.assertEqual(self.eng.start(session=mine)["pid"], pid)       # the same one: a plain "already running"
        self.assertEqual(self.eng.status()["session"], mine)
        os.kill(pid, signal.SIGKILL)
        self.assertTrue(wait(lambda: self.eng.status()["restarts"] == 1 and self.eng.state == "running"))
        self.assertEqual((self.info()["argv"]["dir"], self.info()["argv"]["snapshot"]), (str(Path(mine).parent), "Song"))

    def test_a_start_that_hangs_on_a_chosen_backend_is_stopped_and_said(self):
        with mock.patch.dict(os.environ, {"HYPNOMIX_FAKE_ENGINE_MODE": "hang", "HYPNOMIX_ENGINE_ARGS": "-b CoreAudio"}), \
                mock.patch.object(DW, "READY_TIMEOUT", 1.0):
            st = self.eng.start()
            pid = self.started()[0]
        self.assertEqual((st["state"], st["connected"], st["pid"]), ("failed", False, None))
        self.assertIn("not ready within", st["error"])
        self.assertTrue(wait(lambda: not alive(pid), 5))
        time.sleep(0.3)
        self.assertEqual((self.eng.state, self.eng.restarts), ("failed", []))     # and it is not taken for a crash

    def test_the_engine_gets_a_minimal_environment_and_the_sessions_folder(self):
        extra = {"GEMINI_API_KEY": "k", "ANTHROPIC_API_KEY": "k", "GITHUB_TOKEN": "t", "HYPNOMIX_GITHUB_TOKEN": "t",
                 "MY_SECRET": "s", "SOME_PASSWORD": "p", "CLAUDE_CODE_MESSAGING_TOKEN": "t", "RANDOM_THING": "x"}
        with mock.patch.dict(os.environ, extra):
            self.eng.start()
            keys, cwd = self.info()["envkeys"], self.info()["cwd"]
        for k in extra:
            self.assertNotIn(k, keys)
        self.assertIn("HYPNOMIX_HOME", keys)                         # what isolates a test copy still goes through
        self.assertIn("PATH", keys)
        self.assertEqual(os.path.realpath(cwd), os.path.realpath(str(Path(self.eng.session).parent)))
        self.assertNotEqual(os.path.realpath(cwd), os.path.realpath(os.getcwd()))

    def test_relative_session_paths_are_made_absolute_before_the_engine_starts_in_their_folder(self):
        old = os.getcwd()
        try:
            os.chdir(self.td.name)
            eng = DW.Engine(binary=self.bin, attach_url="http://127.0.0.1:9/mcp")
            self.assertTrue(eng.start(session="Song/Song.ardour")["state"] == "running")
            try:
                i = eng.call("tools/call", {"name": "session_get_info", "arguments": {}})["structuredContent"]
                want = str(Path(self.td.name).absolute() / "Song")
                self.assertEqual(i["argv"]["dir"], want)
                self.assertTrue(os.path.isabs(eng.session))
                self.assertEqual(os.path.realpath(i["cwd"]), os.path.realpath(want))
                self.assertTrue(Path(i["argv"]["dir"]).is_dir())      # found from where the engine starts
            finally:
                eng.stop()
            self.assertTrue(os.path.isabs(DW.Engine.check_new("Rel", "Fresh")[0]))
            eng = DW.Engine(binary=self.bin, attach_url="http://127.0.0.1:9/mcp")
            (Path(self.td.name) / "Rel").mkdir()
            try:
                self.assertEqual(eng.new_session("Rel", "Fresh")["state"], "running")
                i = eng.call("tools/call", {"name": "session_get_info", "arguments": {}})["structuredContent"]
                self.assertEqual(i["argv"]["dir"], str(Path(self.td.name).absolute() / "Rel" / "Fresh"))
                self.assertEqual(os.path.realpath(i["cwd"]), os.path.realpath(str(Path(self.td.name) / "Rel")))
            finally:
                eng.stop()
        finally:
            os.chdir(old)

    # -- names
    def test_option_like_and_odd_names_are_refused(self):
        for bad in ("--save-on-exit", "-b", "--help", ".hidden", "..", ".", "a/b", "a\x01b", "", "x" * 201):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.eng.new_session(self.td.name, bad)
        self.assertEqual(self.started(), [])                         # none of them reached the engine

    def test_a_session_the_engine_refuses_leaves_the_open_one_open(self):
        bad = Path(self.td.name) / "Broken" / "Broken.ardour"
        bad.parent.mkdir()
        bad.write_text("<Session/>")
        self.eng.start()
        mine = self.eng.session
        with mock.patch.dict(os.environ, {"HYPNOMIX_FAKE_ENGINE_BAD": "Broken"}):
            st = self.eng.open(bad)
        self.assertEqual((st["state"], st["session"]), ("running", mine))
        self.assertIn("Could not open Broken.ardour", st["notice"])
        self.assertIn("Song.ardour is open again", st["notice"])
        self.assertEqual(self.info()["argv"]["snapshot"], "Song")
        self.assertEqual(len([p for p in self.started() if alive(p)]), 1)

    def test_a_session_called_like_an_option_is_still_a_name(self):
        odd = Path(self.td.name) / "-b.ardour"
        odd.write_text("<Session/>")
        self.eng.open(odd)
        argv = self.info()["argv"]
        self.assertEqual((argv["dir"], argv["snapshot"], argv.get("backend")), (self.td.name, "-b", None))

    def test_a_new_session_goes_after_the_double_dash(self):
        self.eng.new_session(self.td.name, "Fresh")
        self.assertIn("--new -- ", " ".join(self.eng.log[:1]))

    def test_names_too_long_for_the_disk_are_a_sentence_not_a_dropped_connection(self):
        long = "/tmp/" + "a" * 300 + ".ardour"
        with self.assertRaises(ValueError):
            DW.snapshot(long)
        with self.assertRaises(ValueError):
            DW.snapshot("/tmp/" + "a" * 300 + "/")
        with self.assertRaises(ValueError):
            self.eng.new_session("/tmp/" + "a" * 300, "x")
        with self.assertRaises(ValueError):
            self.eng.new_session(self.td.name, "a" * 300)

    def test_a_loopback_call_never_uses_the_proxy(self):
        self.eng.start()
        seen = []

        class Proxy(__import__("http.server").server.BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append(self.path)
                self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"{}")

            def log_message(self, *a):
                pass
        px = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
        threading.Thread(target=px.serve_forever, daemon=True).start()
        try:
            env = {"http_proxy": f"http://127.0.0.1:{px.server_address[1]}", "HTTP_PROXY": f"http://127.0.0.1:{px.server_address[1]}",
                   "no_proxy": "", "NO_PROXY": ""}
            with mock.patch.dict(os.environ, env):
                code, raw = DW.post_json(self.eng.url(), {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
                self.assertEqual(code, 200)
                self.assertIn("tools", json.loads(raw)["result"])    # the engine answered, not the proxy
                self.assertFalse(DW.answers("http://127.0.0.1:9/mcp"))      # and nothing is "found" through it
                code, _ = self.eng.rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
                self.assertEqual(code, 200)
        finally:
            px.shutdown()
        self.assertEqual(seen, [])
        with self.assertRaises(ValueError):                           # and no other computer is called
            DW.post_json("http://example.invalid/mcp", {})

    def test_the_source_tree_is_never_guessed(self):
        with mock.patch.dict(os.environ, {"HYPNOMIX_ENGINE": "", "HYPNOMIX_ENGINE_SRC": ""}), mock.patch.object(DW, "_conf", lambda: {}):
            self.assertFalse([c for c in DW.candidates() if "engine-dev" in c.name or "hypnomix-daw" in str(c)])
        with mock.patch.dict(os.environ, {"HYPNOMIX_ENGINE_SRC": "/some/checkout"}):
            self.assertIn(Path("/some/checkout/hypnomix/engine/engine-dev"), DW.candidates())


class Unsaved(unittest.TestCase):
    """Dirty tracking for every call that goes through the app, Save, and the 409 that protects unsaved work."""
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.calls = Path(self.td.name) / "calls.jsonl"
        self.env = mock.patch.dict(os.environ, {"HYPNOMIX_FAKE_ENGINE_CALLS": str(self.calls)})
        self.env.start()
        os.environ.pop("HYPNOMIX_ENGINE_ARGS", None)
        self.eng = with_session(DW.Engine(binary=make_fake(self.td.name), attach_url="http://127.0.0.1:9/mcp"), self.td.name)
        self.patch = mock.patch.object(DW, "ENGINE", self.eng)
        self.patch.start()
        self.eng.start()

    def tearDown(self):
        self.patch.stop()
        self.eng.stop()
        self.env.stop()
        self.td.cleanup()

    def tool(self, name, **args):
        return self.eng.rpc({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": name, "arguments": args}})

    def test_only_a_change_makes_the_session_unsaved(self):
        self.assertFalse(self.eng.status()["dirty"])
        for name in ("session_get_info", "tracks_list", "track_get_info", "meters_get", "transport_play", "export_status"):
            self.tool(name)
        self.eng.rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.eng.rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertFalse(self.eng.dirty)
        self.tool("track_set_fader_db", id="1", db=-3)
        self.assertTrue(self.eng.status()["dirty"])
        self.assertTrue(DW.dirty())

    def test_a_crash_that_loses_changes_says_so_until_the_next_save(self):
        self.tool("track_set_fader_db", id="1", db=-3)
        self.assertTrue(self.eng.dirty)
        os.kill(self.eng.status()["pid"], signal.SIGKILL)
        self.assertTrue(wait(lambda: self.eng.status()["restarts"] == 1 and self.eng.state == "running"))
        st = self.eng.status()
        self.assertFalse(st["dirty"])                                # the new engine has the file's state
        self.assertEqual(st["notice"], DW.LOST_NOTICE)               # ...and the person is told what was lost
        self.assertIn("lost", st["notice"])
        self.tool("track_set_fader_db", id="1", db=-2)
        self.assertEqual(self.eng.status()["notice"], DW.LOST_NOTICE)    # an edit does not make it go away
        self.eng.save()
        self.assertEqual(self.eng.status()["notice"], "")

    def test_a_crash_with_nothing_unsaved_adds_no_notice(self):
        os.kill(self.eng.status()["pid"], signal.SIGKILL)
        self.assertTrue(wait(lambda: self.eng.status()["restarts"] == 1 and self.eng.state == "running"))
        self.assertEqual(self.eng.status()["notice"], "")

    def test_a_tool_nobody_listed_counts_as_a_change(self):
        self.tool("some_new_tool_next_year")
        self.assertTrue(self.eng.dirty)

    def test_a_save_clears_it_and_a_failed_change_does_not_set_it(self):
        self.tool("will_fail")                                       # the engine said no: nothing changed
        self.assertFalse(self.eng.dirty)
        self.tool("track_set_mute", id="1", mute=True)
        self.assertTrue(self.eng.dirty)
        self.tool("session_save")
        self.assertFalse(self.eng.dirty)
        self.tool("track_set_mute", id="1", mute=False)
        self.tool("session_save", snapshotName="Take 2", switchToSnapshot=False)    # another snapshot: this one is still unsaved
        self.assertTrue(self.eng.dirty)
        self.tool("session_quick_snapshot", switchToSnapshot=False)
        self.assertTrue(self.eng.dirty)
        self.eng.save()
        self.assertFalse(self.eng.dirty)

    def test_a_batch_is_read_in_order_and_an_edit_during_a_save_stays_unsaved(self):
        change = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "track_set_pan", "arguments": {}}}
        save = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "session_save", "arguments": {}}}
        ok = json.dumps([{"jsonrpc": "2.0", "id": 1, "result": {}}, {"jsonrpc": "2.0", "id": 2, "result": {}}]).encode()
        self.eng._track([change, save], self.eng._edits, 200, ok)
        self.assertFalse(self.eng.dirty)                              # saved after the change
        self.eng._track([save, change], self.eng._edits, 200, ok)
        self.assertTrue(self.eng.dirty)                               # changed after the save
        self.eng.dirty = False
        n = self.eng._edits
        self.eng._edits += 1                                          # another edit came in while the save was running
        self.eng.dirty = True
        self.eng._track([save], n, 200, ok)
        self.assertTrue(self.eng.dirty)                               # the save did not see it: still unsaved
        both = json.dumps([{"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "no"}},
                           {"jsonrpc": "2.0", "id": 2, "result": {"isError": True}}]).encode()
        self.eng.dirty = False
        self.eng._track([change, save], self.eng._edits, 200, both)
        self.assertFalse(self.eng.dirty)                              # both refused: nothing changed
        self.eng._track([change], self.eng._edits, None, None)        # no answer (a timeout): it may have got there
        self.assertTrue(self.eng.dirty)

    def test_a_new_or_reopened_session_starts_clean_and_stop_forgets(self):
        self.tool("track_set_fader_db", id="1", db=-1)
        self.assertTrue(self.eng.dirty)
        self.eng.stop()
        self.assertFalse(self.eng.dirty)
        self.eng.start()
        self.tool("track_set_fader_db", id="1", db=-1)
        self.eng.restart()
        self.assertFalse(self.eng.status()["dirty"])
        self.tool("track_set_fader_db", id="1", db=-1)
        self.eng.new_session(self.td.name, "Fresh")
        self.assertFalse(self.eng.dirty)

    def test_the_routes_that_would_lose_work_say_unsaved(self):
        sess = Path(self.td.name) / "Other" / "Other.ardour"
        sess.parent.mkdir()
        sess.write_text("<Session/>")
        routes = [("/api/daw/stop", {}), ("/api/daw/restart", {}), ("/api/daw/open", {"path": str(sess)}),
                  ("/api/daw/new", {"folder": self.td.name, "name": "Fresh"})]
        self.tool("track_set_fader_db", id="1", db=-3)
        pid = self.eng.status()["pid"]
        for path, body in routes:
            self.assertEqual(DW.handle_post(path, body), (409, {"error": "unsaved", "dirty": True}), path)
            self.assertEqual(self.eng.status()["pid"], pid)           # nothing was touched
            self.assertTrue(self.eng.dirty)
        self.assertEqual(DW.handle_post("/api/daw/stop", {"discard": "yes"})[0], 409)        # only a real true counts
        code, st = DW.handle_post("/api/daw/restart", {"discard": True})                     # go on without saving
        self.assertEqual((code, st["state"]), (200, "running"))
        self.assertNotEqual(st["pid"], pid)
        self.assertFalse(self.eng.dirty)
        self.assertEqual(DW.handle_post("/api/daw/stop", {})[0], 200)                         # nothing unsaved: just does it

    def test_save_first_then_go_on(self):
        self.tool("track_set_fader_db", id="1", db=-3)
        code, st = DW.handle_post("/api/daw/restart", {"save": True})
        self.assertEqual((code, st["state"]), (200, "running"))
        saves = [c["name"] for c in map(json.loads, self.calls.read_text().splitlines()) if c["name"] == "session_save"]
        self.assertEqual(saves, ["session_save"])
        self.assertFalse(self.eng.dirty)

    def test_a_save_that_fails_stops_nothing(self):
        self.tool("track_set_fader_db", id="1", db=-3)
        pid = self.eng.status()["pid"]
        with mock.patch.object(DW.Engine, "save", side_effect=RuntimeError("disk full")):
            code, body = DW.handle_post("/api/daw/stop", {"save": True})
        self.assertEqual(code, 409)
        self.assertIn("disk full", body["error"])
        self.assertTrue(body["dirty"])
        self.assertEqual(self.eng.status()["pid"], pid)

    def test_save_route_and_the_state(self):
        self.assertEqual(DW.handle_get("/api/daw/state", {}, "t")[1]["dirty"], False)
        self.tool("track_set_fader_db", id="1", db=-3)
        st = DW.handle_get("/api/daw/state", {}, "t")[1]
        self.assertEqual((st["dirty"], st["available"]), (True, True))
        self.assertEqual(DW.handle_post("/api/daw/save", {}), (200, {"ok": True, "dirty": False}))
        self.assertFalse(DW.handle_get("/api/daw/state", {}, "t")[1]["dirty"])
        self.eng.stop()
        with self.assertRaises(RuntimeError):
            DW.handle_post("/api/daw/save", {})                       # nothing to save: said, not pretended

    def test_the_assistants_calls_count_too(self):
        self.eng.call("tools/call", {"name": "track_set_pan", "arguments": {"id": "1", "pan": 0.2}})   # as daw_assist / dawreview do
        self.assertTrue(self.eng.dirty)

    def test_a_window_we_did_not_start_is_never_blocked(self):
        self.eng.mode = "attached"
        self.eng.dirty = True
        self.assertFalse(DW.dirty())                                  # it is theirs: stop only lets go
        self.eng.mode = "engine"


class AppQuits(unittest.TestCase):
    """An app that is told to quit takes the engine with it, whether or not it was started with --daw, and an engine
    whose app is gone ends by itself (the stand-in honours --parent-pid, as the real one does)."""
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.bin = make_fake(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def test_the_engine_follows_its_app_away(self):
        sleeper = subprocess.Popen(["sleep", "60"])
        p = subprocess.Popen([str(self.bin), "--parent-pid", str(sleeper.pid)], stdout=subprocess.PIPE, text=True)
        try:
            while "READY" not in p.stdout.readline():
                pass
            sleeper.kill()
            sleeper.wait()
            self.assertTrue(wait(lambda: p.poll() is not None, 10))
        finally:
            p.kill(); sleeper.kill(); p.wait(); sleeper.wait(); p.stdout.close()

    def free_port(self):
        import socket
        for port in range(8900, 8930):
            with socket.socket() as so:
                try:
                    so.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    continue
        self.skipTest("no free port in 8900-8929")

    def test_an_app_without_daw_stops_an_engine_started_from_its_tab(self):
        import re as _re, urllib.request as _u
        port, probe = self.free_port(), None
        sess = Path(self.td.name) / "Song" / "Song.ardour"
        sess.parent.mkdir()
        sess.write_text("<Session/>")
        env = dict(os.environ, HYPNOMIX_FAKE_ENGINE_NO_PARENT="1",      # (so only the app's own shutdown can end it)
                   HYPNOMIX_ENGINE=str(self.bin), HYPNOMIX_PORT=str(port), HYPNOMIX_PROBE_PORT=str(port + 1000 if port + 1000 < 65000 else port - 1))
        app = subprocess.Popen([sys.executable, "-m", "hypnomix.cli", "app", "--port", str(port), "--no-open", "--home", self.td.name],
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(Path(__file__).resolve().parents[1]))
        pid = None
        try:
            base = f"http://127.0.0.1:{port}"
            html = None
            for _ in range(100):
                try:
                    html = _u.urlopen(base + "/", timeout=2).read().decode()
                    break
                except OSError:
                    time.sleep(0.2)
            self.assertTrue(html, "the app did not come up")
            tok = _re.search(r'"([A-Za-z0-9_-]{16,})"', html[html.index("TOKEN") - 5:] if "TOKEN" in html else html).group(1) if False else None
            tok = _re.search(r"HX_TOKEN\s*=\s*\"([^\"]+)\"|const TOKEN\s*=\s*\"([^\"]+)\"|TOKEN = '([^']+)'", html)
            tok = next(g for g in tok.groups() if g) if tok else None
            self.assertTrue(tok, "no token in the page")
            req = _u.Request(base + "/api/daw/start", data=json.dumps({"session": str(sess)}).encode(),
                             headers={"Content-Type": "application/json", "X-Hypnomix": tok}, method="POST")
            pid = json.loads(_u.urlopen(req, timeout=60).read())["pid"]
            self.assertTrue(pid and alive(pid))
            app.send_signal(signal.SIGTERM)
            app.wait(20)
            self.assertTrue(wait(lambda: not alive(pid), 10), "the engine outlived its app")
        finally:
            if app.poll() is None:
                app.kill()
            app.wait()
            app.stdout.close()
            if pid and alive(pid):
                os.kill(pid, signal.SIGKILL)


class TestBuildApp(unittest.TestCase):
    """A test build whose bundle carries the engine kit (found for one more version): its window's File → New Session / Open
    Session go through the DAW view to the supervisor. The installer no longer carries the engine."""
    def test_the_window_and_the_view_are_wired(self):
        root = Path(__file__).resolve().parents[1]
        swift = (root / "macapp" / "Hypnomix.swift").read_text()
        for word in ('"New Session…"', '"Open Session…"', "HX.menuSession", "Resources/engine/bin/hypnomix-engine",
                     "JSONSerialization", "makeSignalSource(signal: SIGTERM"):
            self.assertIn(word, swift)
        js = (DW.ROOT / "js" / "app.js").read_text()
        self.assertIn("HX.menuSession = async function (req)", js)
        self.assertIn("'/api/daw/new' : '/api/daw/open'", js)
        self.assertIn("'To ' + what + ', the engine closes '", js)      # asks before closing an open session (HX.guardedPost: Save / Don't save / Cancel)
        sh = (root / "packaging" / "mac" / "build_dmg.sh").read_text()
        for word in ("--app-only)", 'codesign --verify --deep --strict "$app"', "Hypnomix-$version-mac-$arch.dmg"):
            self.assertIn(word, sh)
        self.assertNotIn("--daw)", sh)                                  # the engine is not put inside the installer's app


class Attach(unittest.TestCase):
    """No engine program yet: use a HypnoMix window that is already running (here: the stand-in, started by hand)."""
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.p = subprocess.Popen([str(make_fake(self.td.name))], stdout=subprocess.PIPE, text=True)
        line = ""
        while "READY" not in line:
            line = self.p.stdout.readline()
        self.url = f"http://127.0.0.1:{line.split('port=')[1].split()[0]}/mcp"
        self.patch = mock.patch.object(DW, "find_engine", lambda: None)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.p.kill()
        self.p.wait()
        self.p.stdout.close()
        self.td.cleanup()

    def test_attaches_and_never_stops_the_window(self):
        eng = DW.Engine(attach_url=self.url)
        st = eng.start()
        self.assertEqual((st["state"], st["mode"], st["url"], st["pid"]), ("attached", "attached", self.url, None))
        self.assertEqual(len(eng.tools()), 5)
        with self.assertRaises(RuntimeError):
            eng.restart()
        sess = Path(self.td.name) / "S.ardour"
        sess.write_text("<Session/>")
        with self.assertRaises(RuntimeError):
            eng.open(sess)                                       # opening is done in that window
        eng.stop()
        self.assertIsNone(self.p.poll())                         # the window keeps running
        self.assertEqual(eng.status()["state"], "stopped")

    def test_nothing_to_attach_to(self):
        eng = DW.Engine(attach_url="http://127.0.0.1:9/mcp")
        st = eng.start()
        self.assertEqual((st["state"], st["connected"]), ("stopped", False))
        self.assertIn("MCPHttp", st["error"])

    def test_finds_the_engine_program(self):
        self.patch.stop()
        try:
            with mock.patch.dict(os.environ, {"HYPNOMIX_ENGINE": str(Path(self.td.name) / "hypnomix-engine")}):
                self.assertEqual(DW.find_engine(), Path(self.td.name) / "hypnomix-engine")
            with mock.patch.object(DW.sys, "executable", "/A/Hypnomix.app/Contents/Resources/python/bin/python3"):
                self.assertIn(Path("/A/Hypnomix.app/Contents/Resources/engine/bin/hypnomix-engine"), DW.candidates())   # in the bundle
                self.assertNotIn(Path("/A/Hypnomix.app/Contents/MacOS/hypnomix-engine"), DW.candidates())   # only the bundle's one place
            app = Path(self.td.name).resolve() / "Hypnomix.app" / "Contents"             # the full download's bundle
            py = app / "Resources" / "python" / "bin" / "python3"
            kit = app / "Resources" / "engine" / "bin" / "hypnomix-engine"
            with mock.patch.object(DW.sys, "executable", str(py)), mock.patch.dict(os.environ, {"HYPNOMIX_ENGINE": ""}), \
                    mock.patch.object(DW, "_conf", lambda: {}):
                self.assertIn(kit, DW.candidates())                                    # a test build's kit is still looked for
                self.assertIsNone(DW.find_engine())                                    # an app without it (or the add-on) has none
                kit.parent.mkdir(parents=True)
                kit.write_text("#!/bin/sh\n")
                kit.chmod(0o755)
                self.assertEqual(DW.find_engine(), kit)
            dev = Path(self.td.name) / "tree" / "hypnomix" / "engine" / "engine-dev"     # a source build
            dev.parent.mkdir(parents=True)
            dev.write_text("#!/bin/sh\n")
            dev.chmod(0o755)
            with mock.patch.object(DW, "candidates", lambda: [dev]):
                self.assertIsNone(DW.find_engine())                    # the script alone: not built yet
                built = Path(self.td.name) / "tree" / "build" / "hypnomix" / "engine" / "hypnomix-engine"
                built.parent.mkdir(parents=True)
                built.write_text("")
                self.assertEqual(DW.find_engine(), dev)
        finally:
            self.patch.start()


def call(base, path, body=None, headers=None, raw=None):
    h = dict(headers or {})
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if data is not None:
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(base + path, data=data, headers=h, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


class Proxy(unittest.TestCase):
    """The app server: POST /mcp to the engine (localhost, the page's token), the DAW view, the engine routes."""
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        os.environ["HYPNOMIX_APP_HOME"] = cls.td.name
        from hypnomix.app import server as S
        cls.S = S
        cls.eng = with_session(DW.Engine(binary=make_fake(cls.td.name), attach_url="http://127.0.0.1:9/mcp"), cls.td.name)
        cls.patch = mock.patch.object(DW, "ENGINE", cls.eng)
        cls.patch.start()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(0))
        port = cls.srv.server_address[1]
        cls.srv.RequestHandlerClass = S.make_handler(port)
        cls.base = f"http://127.0.0.1:{port}"
        cls.tok = {"X-Hypnomix": S.TOKEN}
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.eng.stop()
        cls.patch.stop()
        cls.srv.shutdown()
        cls.td.cleanup()
        os.environ.pop("HYPNOMIX_APP_HOME", None)

    def rpc(self, method, params=None, headers=None, rid=1):
        body = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            body["params"] = params
        return call(self.base, "/mcp", body, dict(self.tok, **(headers or {})))

    def test_1_no_engine_yet(self):
        self.eng.stop()
        code, raw, _ = self.rpc("tools/list")
        self.assertEqual(code, 503)
        self.assertEqual(json.loads(raw)["error"]["code"], -32000)

    def test_2_forwards_with_the_token_only(self):
        code, raw, _ = call(self.base, "/api/daw/start", {}, self.tok)
        self.assertEqual((code, json.loads(raw)["state"]), (200, "running"))
        code, raw, _ = self.rpc("tools/list")
        self.assertEqual(code, 200)
        self.assertEqual(len(json.loads(raw)["result"]["tools"]), 5)
        code, raw, _ = self.rpc("tools/call", {"name": "track_set_fader_db", "arguments": {"id": "1", "db": -3}}, rid=7)
        self.assertEqual(json.loads(raw), {"jsonrpc": "2.0", "id": 7, "result": {"structuredContent": {
            "ok": True, "called": "track_set_fader_db", "arguments": {"id": "1", "db": -3}}}})
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        self.assertEqual(call(self.base, "/mcp", body)[0], 403)                                     # no token
        self.assertEqual(call(self.base, "/mcp", body, dict(self.tok, Origin="http://evil.example"))[0], 403)
        self.assertEqual(call(self.base, "/mcp", body, dict(self.tok, Host="evil.example"))[0], 403)
        self.assertEqual(call(self.base, "/mcp", body, dict(self.tok, **{"Content-Type": "text/plain"}))[0], 415)
        code, raw, _ = call(self.base, "/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"}, self.tok)
        self.assertEqual((code, raw), (202, b""))
        self.assertEqual(json.loads(self.rpc("nope")[1])["error"]["code"], -32601)                  # errors pass through

    def test_3_engine_routes_need_the_token(self):
        self.assertEqual(call(self.base, "/api/daw/stop", {})[0], 403)
        code, raw, _ = call(self.base, "/api/daw/state")
        st = json.loads(raw)
        self.assertIn(st["state"], ("running", "stopped"))
        self.assertIn("daw_mode", st)
        code, raw, _ = call(self.base, "/api/daw/open", {"path": "/nowhere/x.ardour"}, self.tok)
        self.assertEqual(code, 400)

    def test_4_the_daw_view(self):
        code, page, h = call(self.base, "/daw/")
        self.assertEqual(code, 200)
        self.assertIn(self.S.TOKEN.encode(), page)
        self.assertNotIn(b"__TOKEN__", page)
        for f in ("js/mcp.js", "js/assistant.js", "js/app.js", "js/regions.js", "css/app.css"):
            self.assertEqual(call(self.base, "/daw/" + f)[0], 200, f)
        self.assertEqual(call(self.base, "/daw/js/../../server.py")[0], 404)
        self.assertEqual(call(self.base, "/daw/%2e%2e/server.py")[0], 404)
        self.assertEqual(call(self.base, "/daw/")[0], 200)
        code, page, _ = call(self.base, "/")
        self.assertIn(b"data-daw", page)                              # the DAW tab next to Songs, Assistant, Wiki
        self.assertIn(b"const DAW_MODE = false", page)
        from hypnomix.app import setup as SU
        with mock.patch.dict(DW.STATE, {"daw": True}), mock.patch.object(SU, "is_done", lambda: True):
            self.assertIn(b"const DAW_MODE = true", call(self.base, "/")[1])
        with mock.patch.dict(DW.STATE, {"daw": True}), mock.patch.object(SU, "is_done", lambda: False):
            self.assertIn(b"const DAW_MODE = false", call(self.base, "/")[1])      # a first launch shows the guided setup


    def test_5_the_page_is_served_only_at_its_own_address(self):
        import http.client
        port = self.srv.server_address[1]
        for path in ("/daw", "/daw/index.html"):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", path)
            r = c.getresponse()
            body = r.read()
            self.assertEqual((r.status, r.getheader("Location")), (302, "/daw/"), path)   # the assets are relative to /daw/
            self.assertNotIn(b"__TOKEN__", body)
            c.close()
        self.assertEqual(call(self.base, "/daw/css/app.css")[0], 200)

    def test_6_names_too_long_or_like_options_are_a_400_not_a_dropped_connection(self):
        for path, body in (("/api/daw/open", {"path": "/tmp/" + "a" * 300 + ".ardour"}),
                           ("/api/daw/open", {"path": "/tmp/" + "a" * 300 + "/"}),
                           ("/api/daw/new", {"folder": "/tmp", "name": "a" * 300}),
                           ("/api/daw/new", {"folder": "/tmp/" + "a" * 300, "name": "x"}),
                           ("/api/daw/new", {"folder": "/tmp", "name": "--help"}),
                           ("/api/daw/start", {"session": "/tmp/" + "a" * 300 + ".ardour"})):
            code, raw, _ = call(self.base, path, body, self.tok)
            self.assertEqual(code, 400, (path, body, raw))
            self.assertIn("error", json.loads(raw))

    def test_7_unsaved_work_over_http(self):
        call(self.base, "/api/daw/restart", {"discard": True}, self.tok)         # (test_2 left a change in the engine)
        self.assertFalse(json.loads(call(self.base, "/api/daw/state")[1])["dirty"])
        self.rpc("tools/call", {"name": "tracks_list", "arguments": {}})                        # a read changes nothing
        self.assertFalse(json.loads(call(self.base, "/api/daw/state")[1])["dirty"])
        self.rpc("tools/call", {"name": "track_set_fader_db", "arguments": {"id": "1", "db": -3}})   # from the page
        self.assertTrue(json.loads(call(self.base, "/api/daw/state")[1])["dirty"])
        pid = json.loads(call(self.base, "/api/daw/state")[1])["pid"]
        for path, body in (("/api/daw/restart", {}), ("/api/daw/stop", {}), ("/api/daw/new", {"folder": self.td.name, "name": "Fresh"})):
            code, raw, _ = call(self.base, path, body, self.tok)
            self.assertEqual((code, json.loads(raw)), (409, {"error": "unsaved", "dirty": True}), path)
        self.assertEqual(json.loads(call(self.base, "/api/daw/state")[1])["pid"], pid)        # nothing was stopped
        self.assertEqual(call(self.base, "/api/daw/save", {})[0], 403)                          # the token, as for every POST
        code, raw, _ = call(self.base, "/api/daw/save", {}, self.tok)
        self.assertEqual((code, json.loads(raw)), (200, {"ok": True, "dirty": False}))
        self.assertFalse(json.loads(call(self.base, "/api/daw/state")[1])["dirty"])
        self.rpc("tools/call", {"name": "track_set_fader_db", "arguments": {"id": "1", "db": -4}})
        code, raw, _ = call(self.base, "/api/daw/restart", {"discard": True}, self.tok)       # "Don't save"
        self.assertEqual((code, json.loads(raw)["state"]), (200, "running"))
        self.assertFalse(json.loads(call(self.base, "/api/daw/state")[1])["dirty"])
        self.rpc("tools/call", {"name": "session_save", "arguments": {}})   # saved by the page itself
        self.assertFalse(json.loads(call(self.base, "/api/daw/state")[1])["dirty"])


class Upload(unittest.TestCase):
    """A file dropped on the DAW view: POST /api/daw/upload saves it (with the page's token) in a temp folder for
    session_import_audio; only audio files, only under that folder; the import gets minutes, not seconds."""
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        os.environ["HYPNOMIX_APP_HOME"] = cls.td.name
        cls.up = Path(cls.td.name) / "uploads"
        cls.env = mock.patch.dict(os.environ, {"HYPNOMIX_DAW_UPLOADS": str(cls.up)})
        cls.env.start()
        from hypnomix.app import server as S
        cls.S = S
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(0))
        port = cls.srv.server_address[1]
        cls.srv.RequestHandlerClass = S.make_handler(port)
        cls.base = f"http://127.0.0.1:{port}"
        cls.tok = {"X-Hypnomix": S.TOKEN, "Content-Type": "application/octet-stream"}
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.env.stop()
        cls.td.cleanup()
        os.environ.pop("HYPNOMIX_APP_HOME", None)

    def test_saves_an_audio_file(self):
        data = b"RIFF" + bytes(range(256)) * 40
        code, raw, _ = call(self.base, "/api/daw/upload?name=Lead%20Vox.wav", headers=self.tok, raw=data)
        self.assertEqual(code, 200, raw)
        r = json.loads(raw)
        f = Path(r["path"])
        self.assertEqual((f.name, f.read_bytes(), r["bytes"]), ("Lead Vox.wav", data, len(data)))
        self.assertEqual(f.parent.parent, self.up)                    # its own folder, so the name (the track's) is kept

    def test_refuses(self):
        self.assertEqual(call(self.base, "/api/daw/upload?name=a.wav", headers={"Content-Type": "application/octet-stream"}, raw=b"x")[0], 403)
        self.assertEqual(call(self.base, "/api/daw/upload?name=notes.txt", headers=self.tok, raw=b"x")[0], 400)
        self.assertEqual(call(self.base, "/api/daw/upload?name=.wav", headers=self.tok, raw=b"x")[0], 400)
        code, raw, _ = call(self.base, "/api/daw/upload?name=..%2F..%2Fevil.wav", headers=self.tok, raw=b"RIFF")
        self.assertEqual(code, 200)
        self.assertEqual(Path(json.loads(raw)["path"]).parent.parent, self.up)   # a path in the name is only a name

    def test_a_stalled_upload_leaves_nothing_behind(self):
        class Stalls:
            n = 0

            def read(self, k):
                self.n += 1
                if self.n > 1:
                    raise TimeoutError("timed out")                 # what the server's socket timeout gives
                return b"x" * 1000
        before = set(self.up.iterdir()) if self.up.exists() else set()
        with self.assertRaises(TimeoutError):
            DW.save_upload(Stalls(), 3 << 20, "stall.wav")
        self.assertEqual(set(self.up.iterdir()), before)
        short = __import__("io").BytesIO(b"x" * 10)
        with self.assertRaises(ValueError):
            DW.save_upload(short, 100, "short.wav")
        self.assertEqual(set(self.up.iterdir()), before)

    def test_no_room_is_said_before_a_byte_is_written(self):
        before = set(self.up.iterdir()) if self.up.exists() else set()
        with mock.patch.object(DW.shutil, "disk_usage", lambda p: types.SimpleNamespace(free=1000, total=1, used=1)):
            with self.assertRaises(ValueError) as cm:
                DW.save_upload(__import__("io").BytesIO(b"x" * 10), 10, "a.wav")
        self.assertIn("free space", str(cm.exception))
        self.assertEqual(set(self.up.iterdir()), before)

    def test_uploads_follow_the_apps_work_folder(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HYPNOMIX_APP_HOME": home}):
            os.environ.pop("HYPNOMIX_DAW_UPLOADS")
            self.assertEqual(DW.upload_dir(), Path(home) / "daw-uploads")
            r = DW.save_upload(__import__("io").BytesIO(b"RIFF"), 4, "a.wav")
            self.assertTrue(Path(r["path"]).is_file())
            self.assertEqual(Path(r["path"]).parent.parent, Path(home) / "daw-uploads")
            if os.name != "nt":
                self.assertEqual((Path(home) / "daw-uploads").stat().st_mode & 0o077, 0)   # nobody else's to read

    def test_old_uploads_are_tidied_and_import_gets_time(self):
        self.up.mkdir(parents=True, exist_ok=True)
        old = self.up / "0123456789ab"                                # a folder this app made (12 hex digits)
        old.mkdir(exist_ok=True)
        (old / "x.wav").write_bytes(b"x")
        mine = [old]
        others = [self.up / "Music", self.up / "notes.txt", self.up / "0123456789abc", self.up / "abc"]   # not made by the app
        others[0].mkdir(exist_ok=True)
        (others[0] / "keep.wav").write_bytes(b"x")
        others[1].write_text("x")
        others[2].mkdir(exist_ok=True)
        others[3].mkdir(exist_ok=True)
        for q in mine + others:
            os.utime(q, (time.time() - 2 * 86400,) * 2)
        call(self.base, "/api/daw/upload?name=b.flac", headers=self.tok, raw=b"fLaC")
        self.assertFalse(old.exists())
        self.assertTrue(all(q.exists() for q in others), "only folders the app made are ever removed")
        self.assertGreater(DW.rpc_timeout(b'{"method":"tools/call","params":{"name":"session_import_audio"}}'), 60)
        self.assertEqual(DW.rpc_timeout(b'{"method":"tools/list"}'), DW.RPC_TIMEOUT)


class Bridge(unittest.TestCase):
    """The Assistant offers the engine's tools; reads run at once, changes wait for Approve, and go to the engine."""
    def setUp(self):
        from hypnomix.app import chat as CH
        self.CH = CH
        self.td = tempfile.TemporaryDirectory()
        self.calls = Path(self.td.name) / "calls.jsonl"
        self.env = mock.patch.dict(os.environ, {"HYPNOMIX_APP_HOME": self.td.name, "HYPNOMIX_FAKE_ENGINE_CALLS": str(self.calls)})
        self.env.start()
        self.eng = with_session(DW.Engine(binary=make_fake(self.td.name), attach_url="http://127.0.0.1:9/mcp"), self.td.name)
        self.p = [mock.patch.object(DW, "ENGINE", self.eng), mock.patch.object(CH, "CONF", Path(self.td.name) / "ai.json")]
        for p in self.p:
            p.start()
        CH.CHAT.update(items=[], history=[], provider=None, busy=False, pending=None, stop=False, daw_tools={})

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.eng.stop()
        self.env.stop()
        self.td.cleanup()

    def engine_calls(self):
        return [json.loads(x) for x in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def test_no_engine_no_tools(self):
        self.assertEqual(self.CH.engine_tools(), [])
        self.assertEqual(self.CH._daw_note(), "")

    def test_tools_are_named_and_sorted_into_reads_and_changes(self):
        self.eng.start()
        tools = {t["name"]: t for t in self.CH.engine_tools()}
        self.assertEqual(set(tools), {"daw_session_overview", "daw_session_get_info", "daw_track_get_info",
                                      "daw_tracks_list", "daw_track_set_fader_db", "daw_transport_play", "daw_more_tools"})
        self.assertEqual(tools["daw_transport_play"]["engine"], "transport/play")       # the engine's own name is called
        self.assertEqual({n for n, t in tools.items() if t["read_only"]},
                         {"daw_session_overview", "daw_session_get_info", "daw_track_get_info", "daw_tracks_list",
                          "daw_more_tools"})
        self.assertFalse(self.CH.daw_read_only({"name": "x_set", "annotations": {"readOnlyHint": True}}))   # not listed: asks
        self.assertFalse(self.CH.daw_read_only({"name": "track_get_info", "annotations": {"readOnlyHint": False}}))
        a = self.CH.anthropic_tools(list(tools.values()))
        fader = next(t for t in a if t["name"] == "daw_track_set_fader_db")
        self.assertNotIn("strict", fader)
        self.assertEqual(fader["input_schema"]["required"], ["id", "db"])
        self.assertTrue(next(t for t in a if t["name"] == "list_songs")["strict"])     # hypnomix's own stay strict
        o = self.CH.openai_tools(list(tools.values()))
        self.assertIn("daw_tracks_list", [t["function"]["name"] for t in o])

    @unittest.skipUnless(__import__("importlib").util.find_spec("openai"), 'MISSING EXTRA: uv pip install -e ".[assistant]" (the Assistant tests are skipped without it)')
    def test_reads_run_changes_wait_for_approve(self):
        CH = self.CH
        self.eng.start()
        n = {"i": 0}
        seen = {}

        class Fake:
            def __init__(self, **k):
                self.chat = types.SimpleNamespace(completions=self)

            def create(self, model, tools, messages):
                n["i"] += 1
                seen.setdefault("tools", [t["function"]["name"] for t in tools])
                seen.setdefault("system", messages[0]["content"])
                call = lambda i, name, a: types.SimpleNamespace(id=i, function=types.SimpleNamespace(name=name, arguments=json.dumps(a)))
                if n["i"] == 1:
                    m = types.SimpleNamespace(content="Reading the track.", tool_calls=[call("c1", "daw_track_get_info", {"id": "7"})])
                elif n["i"] == 2:
                    assert '"called":"track_get_info"' in messages[-1]["content"], messages[-1]
                    m = types.SimpleNamespace(content="Lower it 2 dB?", tool_calls=[
                        call("c2", "daw_track_set_fader_db", {"id": "7", "db": -2.0})])
                elif n["i"] == 3:
                    seen["after_approve"] = messages[-1]["content"]
                    m = types.SimpleNamespace(content="And again?", tool_calls=[
                        call("c3", "daw_track_set_fader_db", {"id": "7", "db": -4.0})])
                else:
                    seen["after_cancel"] = messages[-1]["content"]
                    m = types.SimpleNamespace(content="Left it there.", tool_calls=None)
                return types.SimpleNamespace(choices=[types.SimpleNamespace(message=m)])

        done = []

        def answer_next(ok):
            self.assertTrue(wait(lambda: (CH.state()["pending"] or {}).get("id") not in (None, *done), 10))
            pend = CH.state()["pending"]
            done.append(pend["id"])
            self.assertEqual(pend["what"], "daw")
            ask = next(i for i in CH.state()["items"] if i.get("id") == pend["id"])
            self.assertEqual((ask["tool"], ask["title"]), ("track_set_fader_db", "Change a fader"))
            self.assertEqual(len([c for c in self.engine_calls() if c["name"] == "track_set_fader_db"]),
                             0 if ok else 1)                        # nothing reached the engine before the click
            CH.answer(pend["id"], ok, digest=pend.get("digest"))        # as the page does: the digest of the call it showed

        CH.update_settings({"provider": "ollama", "model": "m"})
        with mock.patch("openai.OpenAI", Fake):
            CH.send("the vocal is too loud")
            answer_next(True)
            answer_next(False)
            self.assertTrue(wait(lambda: not CH.state()["busy"], 10))
        self.assertIn("daw_track_set_fader_db", seen["tools"])
        self.assertIn("list_songs", seen["tools"])
        self.assertIn("HypnoMix DAW is open", seen["system"])
        self.assertIn('"called":"track_set_fader_db"', seen["after_approve"])
        self.assertIn("cancelled", seen["after_cancel"])
        sent = [c for c in self.engine_calls() if c["name"] == "track_set_fader_db"]
        self.assertEqual(sent, [{"name": "track_set_fader_db", "arguments": {"id": "7", "db": -2.0}}])   # only the approved one
        self.assertEqual([c["name"] for c in self.engine_calls()][:1], ["track_get_info"])           # the read ran unasked
        asks = [(i["what"], i.get("answer")) for i in CH.state()["items"] if i["kind"] == "ask"]
        self.assertEqual(asks, [("daw", "ran"), ("daw", "declined")])
        self.assertIn("engine: track_get_info", " ".join(i["text"] for i in CH.state()["items"] if i["kind"] == "tool"))


class ViewRules(unittest.TestCase):
    """What the DAW view's scripts promise (there is no JavaScript runner in the test suite: these check the code
    paths are there; the browser test of the release checks them on the engine)."""
    def js(self, name):
        return (DW.ROOT / "js" / name).read_text()

    def test_the_scan_sends_save_true_only_after_save_and_scan(self):
        rv = self.js("review.js")
        scan = rv[rv.index("function scan(skipAsk)"):rv.index("/* ── select")]
        self.assertIn("api.post('/api/dawreview/scan', { save: true })", scan)
        self.assertLess(scan.index("if (!skipAsk)"), scan.index("api.post('/api/dawreview/scan'"))   # asked first
        self.assertNotIn("/api/dawreview/scan', {})", rv)

    def test_edits_wait_while_an_export_runs(self):
        st = self.js("store.js")
        self.assertIn("HX.EXPORT_WAIT = 'An export is running: edits wait until it finishes'", st)
        commit = st[st.index("HX.commit = function"):st.index("HX.edit = function")]
        self.assertIn("if (HX.refuseEdit(ops)) return Promise.resolve();", commit)      # before history or the engine
        self.assertLess(commit.index("refuseEdit"), commit.index("S.history.push"))
        refuse = st[st.index("HX.refuseEdit = function"):st.index("/* throttled live sends")]
        self.assertIn("HX.setLocal(o, o.before)", refuse)                                # the local change is put back
        self.assertIn("HX.exportBusy()", st[st.index("HX.editBlocked = function"):st.index("HX.refuseEdit")])
        for f in ("HX.undo = () => serial", "HX.redo = () => serial"):
            self.assertIn("if (HX.editBlocked())", st[st.index(f):st.index(f) + 200])
        live = st[st.index("HX.live = function"):st.index("/* commit = record")]
        self.assertIn("if (HX.editBlocked()) return;", live)                             # no sends while dragging
        lv = self.js("live.js")
        for f in ("L.addPlugin = async function", "L.removePlugin = async function"):
            self.assertIn("HX.editBlocked()", lv[lv.index(f):lv.index(f) + 600])
        self.assertIn("if (HX.editBlocked()) throw", self.js("regions.js"))             # import too

    def test_adding_or_removing_a_plugin_is_one_undo_step(self):
        lv = self.js("live.js")
        add = lv[lv.index("L.addPlugin = async function"):lv.index("L.removePlugin = async function")]
        rem = lv[lv.index("L.removePlugin = async function"):lv.index("L.movePlugin = async function")]
        self.assertIn("param: 'plugChain'", add)
        self.assertIn("before: null, after: spec", add)
        self.assertIn("before: spec, after: null", rem)
        self.assertLess(rem.index("plugSpec(t, d)"), rem.index("'plugin_remove'"))      # values read before it goes
        put = lv[lv.index("async function plugPut"):lv.index("async function plugTake")]
        self.assertIn("'plugin_add_by_unique_id'", put)
        self.assertIn("position: spec.index", put)                                       # back at the same place
        self.assertIn("'plugin_set_parameter_by_index_value'", put)                      # with its values
        take = lv[lv.index("async function plugTake"):lv.index("async function plugReread")]
        self.assertIn("!== spec.name) throw", take)                                     # only the one that was added
        self.assertIn("if (op.param === 'plugChain') return L.sendPlugChain(op, value);", lv)
        self.assertIn("HX.opHandlers.plugChain = { storeOwned: true", lv)               # not a region op, no engine undo

    def test_the_remove_confirm_stays_armed(self):
        dv = self.js("devices.js")
        self.assertIn("HX.REMOVE_ARM_MS = 4000;", dv)
        self.assertIn("'pointerleave'", dv)
        self.assertIn("if (removeArm.key === ak && Date.now() < removeArm.until) show(true);", dv)   # survives a refresh

    def test_the_refresh_reads_regions_cheaply(self):
        lv = self.js("live.js")
        ref = lv[lv.index("L.refresh = async function"):lv.index("function applyOrder")]
        self.assertIn("await L.refreshRegionsCheap(g)", ref)
        cheap = lv[lv.index("L.refreshRegionsCheap = async function"):lv.index("function applyOrder")]
        self.assertIn("'track_get_regions'", cheap)
        self.assertIn("HX.refreshRegions(changed)", cheap)                               # only tracks that differ
        self.assertIn("REGION_INFO_PER_TICK", cheap)
        self.assertIn("HX.readRegionInfo(c)", cheap)                                     # fades and gain, a few a tick
        self.assertIn("HX.editBusy()", cheap)                                            # never under an edit


class Security(unittest.TestCase):
    """The DAW view and its routes follow the app's rules: a CSP nonce on the page, no inline handlers, the token
    on every POST, fields checked."""
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.env = mock.patch.dict(os.environ, {"HYPNOMIX_APP_HOME": cls.td.name})
        cls.env.start()
        from hypnomix.app import server as S
        cls.S = S
        cls.eng = with_session(DW.Engine(binary=make_fake(cls.td.name), attach_url="http://127.0.0.1:9/mcp"), cls.td.name)
        cls.patch = mock.patch.object(DW, "ENGINE", cls.eng)
        cls.patch.start()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(0))
        port = cls.srv.server_address[1]
        cls.srv.RequestHandlerClass = S.make_handler(port)
        cls.base = f"http://127.0.0.1:{port}"
        cls.tok = {"X-Hypnomix": S.TOKEN}
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.eng.stop()
        cls.patch.stop()
        cls.srv.shutdown()
        cls.env.stop()
        cls.td.cleanup()

    def test_the_daw_page_has_a_nonce_and_no_inline_handlers(self):
        import re
        code, page, h = call(self.base, "/daw/")
        self.assertEqual(code, 200)
        csp = h["Content-Security-Policy"]
        m = re.search(r"'nonce-([^']+)'", csp)
        self.assertTrue(m, csp)
        self.assertIn("script-src-attr 'none'", csp)
        inline = re.findall(rb"<script(?![^>]*\bsrc=)([^>]*)>", page)
        self.assertGreaterEqual(len(inline), 2)
        self.assertTrue(all(f'nonce="{m.group(1)}"'.encode() in a for a in inline), inline)
        self.assertNotEqual(m.group(1), re.search(r"'nonce-([^']+)'", call(self.base, "/daw/")[2]["Content-Security-Policy"]).group(1))
        self.assertIsNone(re.search(rb"<[^>]+\son[a-z]+\s*=", page))
        for f in sorted((DW.ROOT / "js").glob("*.js")):                   # no handler attributes written by script
            self.assertIsNone(re.search(r"""['"<]\s*\w*\s+on[a-z]+=["']""", f.read_text()), f.name)
        for path in ("/daw/js/app.js", "/api/daw/state"):
            hh = call(self.base, path)[2]
            self.assertEqual(hh["X-Frame-Options"], "DENY")
            self.assertEqual(hh["X-Content-Type-Options"], "nosniff")

    def test_post_routes_need_the_token_and_check_fields(self):
        for path in ("/api/daw/start", "/api/daw/stop", "/api/daw/restart", "/api/daw/save", "/api/daw/open", "/api/daw/new", "/api/daw/meta",
                     "/api/dawreview/scan", "/api/dawreview/decide", "/api/dawreview/apply", "/api/dawreview/ab",
                     "/api/store/install", "/api/store/uninstall"):
            self.assertEqual(call(self.base, path, {})[0], 403, path)
        self.assertEqual(call(self.base, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[0], 403)
        self.assertEqual(call(self.base, "/api/daw/upload?name=a.wav", raw=b"RIFF",
                              headers={"Content-Type": "application/octet-stream"})[0], 403)
        bad = [("/api/daw/open", {"path": ["x"]}), ("/api/daw/open", {}), ("/api/daw/new", {"folder": "/tmp", "name": 3}),
               ("/api/daw/start", {"session": {"a": 1}}),
               ("/api/dawreview/decide", {"dir": 5, "id": "x", "decision": "approve"}),
               ("/api/dawreview/apply", {}), ("/api/dawreview/ab", {"dir": ""})]
        for path, body in bad:
            code, raw, _ = call(self.base, path, body, self.tok)
            self.assertEqual(code, 400, (path, body, raw))
            self.assertIn("error", json.loads(raw))

    def test_mcp_takes_only_json_rpc(self):
        for body in (b"[]", b"5", b'{"method": "tools/list"}', b'{"jsonrpc": "2.0", "id": 1, "method": 7}',
                     b'{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"arguments": {}}}',
                     b'{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "x", "arguments": []}}',
                     b"not json"):
            code, raw, _ = call(self.base, "/mcp", headers=self.tok, raw=body)
            self.assertEqual(code, 400, body)
        self.assertEqual(DW.check_rpc(b'{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'), "")
        self.assertEqual(DW.check_rpc(b'[{"jsonrpc": "2.0", "method": "notifications/initialized"}]'), "")

    def test_upload_checks_before_reading(self):
        import http.client
        port = self.srv.server_address[1]
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.putrequest("POST", "/api/daw/upload?name=a.wav")
        c.putheader("X-Hypnomix", self.S.TOKEN)
        c.putheader("Host", f"127.0.0.1:{port}")
        c.putheader("Content-Length", str(DW.UPLOAD_MAX + 1))
        c.endheaders()
        r = c.getresponse()
        self.assertEqual(r.status, 413)                                     # refused without a byte sent
        c.close()
        self.assertEqual(call(self.base, "/api/daw/upload?name=a.exe", headers=dict(self.tok, **{"Content-Type": "application/octet-stream"}), raw=b"x")[0], 400)

    def test_daw_config_follows_hypnomix_home(self):
        with tempfile.TemporaryDirectory() as h:
            with mock.patch.dict(os.environ, {"HYPNOMIX_HOME": h}):
                self.assertEqual(DW.conf_path(), Path(h) / "daw.json")
                (Path(h) / "daw.json").write_text(json.dumps({"args": "-b X"}))
                with mock.patch.dict(os.environ, {"HYPNOMIX_ENGINE_ARGS": ""}):
                    os.environ.pop("HYPNOMIX_ENGINE_ARGS")
                    self.assertEqual(DW.extra_args(), ["-b", "X"])


if __name__ == "__main__":
    unittest.main()
