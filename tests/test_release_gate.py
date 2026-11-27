"""Findings of the 0.3.0 release gate, one test each: the download wording, what the fix help says about a vocal-level
finding, the roadmap and the other pages, the Assistant's key and home-folder privacy, the audio route, over-long names,
the device routes' token, the packaging scripts, and the shared Assistant state between test modules."""
import http.client
import json
import os
import re
import subprocess
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from tests import _isolate

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "hypnomix-out", "node_modules", "__pycache__", ".venv", "dist", "build"}
TEXT_SUFFIXES = {".md", ".py", ".js", ".html", ".yml", ".yaml", ".sh", ".txt", ".json", ".toml", ".swift"}


def repo_text_files():
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix in TEXT_SUFFIXES and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS):
            yield p


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def flat(text):
    return " ".join(text.split())


# ================================================================ DOCS
class OneDownloadToday(unittest.TestCase):
    """There is one app and one installer for everyone; HypnoMix Studio is an add-on, not a second download, and it is not
    available yet. Nothing in the repository says otherwise."""
    CLAIMS = re.compile(r"\btwo downloads\b|download page (asks|offers the same)|offers the same (choice|two)"
                        r"|choose (the )?Hypnomix Assistant|(page|setup) offers? two\b|\bboth downloads\b|offer two:", re.I)

    def test_no_file_in_the_repository_claims_a_second_download_is_on_offer(self):
        for p in repo_text_files():
            if p.relative_to(ROOT).parts[0] == "tests":                 # the tests quote the old wording to forbid it
                continue
            for m in self.CLAIMS.finditer(flat(p.read_text(encoding="utf-8", errors="replace"))):
                self.fail(f"{p.relative_to(ROOT)}: {m.group(0)!r} says or implies a second download")

    def test_the_first_sentences_say_there_is_one_download_and_the_daw_is_an_add_on(self):
        a = flat(read("hypnomix/app/wiki/articles/20-install.html"))
        self.assertRegex(a, r"One download\.</b> The download page has one installer for each computer, the same for everyone")
        self.assertRegex(a, r"add-on you add from the app's Setup only if you want it")
        g = flat(read("docs/guides/09-setup-and-ai.md"))
        self.assertIn("It is an **add-on**, not a second download", g)
        self.assertIn("Add HypnoMix Studio", g)
        s = flat(read("hypnomix/app/setup.py"))
        self.assertIn("There is one app and one installer for everyone", s)
        self.assertIn("Add HypnoMix Studio", read("hypnomix/app/setup.js"))
        self.assertIn("One download for everyone", read("README.md"))
        self.assertIn("one app and one installer", flat(read("packaging/README.md")))


class VocalLevelByHand(unittest.TestCase):
    def test_the_fix_help_and_the_workflow_say_a_fresh_scan_marks_it_by_hand(self):
        from hypnomix.workflow import fix
        doc = flat(fix.__doc__)
        wf = flat(read("docs/WORKFLOW.md"))
        for t in (doc, wf):
            self.assertIn("A vocal-level move is a \"by hand\" finding in a fresh scan", t)
            self.assertIn("writes nothing for it and exits 0", t)
            self.assertIn("older version", t)
            self.assertNotIn("(a vocal-level move, a kind", t)          # the old sentence: FAILED and exit 1 for a fresh scan
        for rel in ("README.md", "hypnomix/app/wiki/articles/25-chores.html", "hypnomix/app/wiki/articles/26-features.html"):
            self.assertIn("approving one in the review writes nothing by itself", flat(read(rel)), rel)

    def test_the_behaviour_the_help_describes(self):
        """A vocal-level finding in a fresh scan has applies='manual'; only an old one (no 'applies') has no step."""
        from hypnomix.workflow import fix
        self.assertIn("fix does not write vocal-level moves", fix.no_step(dict(tool="vocallevel", applies=None)))
        self.assertIn('tool="vocallevel", applies="manual"', read("hypnomix/session/vocallevel.py"))


class RoadmapAndPages(unittest.TestCase):
    def test_the_roadmap_leads_with_what_is_new_and_lists_what_was_built(self):
        t = read("docs/ROADMAP.md")
        self.assertLess(t.index("## New in 0.4.0"), t.index("## New in 0.3.1"))
        self.assertLess(t.index("## New in 0.3.1"), t.index("## New in 0.3.0"))
        self.assertLess(t.index("## New in 0.3.0"), t.index("## Checked where"))
        newest = t[t.index("## New in 0.4.0"):t.index("## New in 0.3.1")]
        self.assertEqual(len(re.findall(r"^\d+\. \*\*", newest, re.M)), 6)
        for word in ("`import`", "REAPER 7.86", "--engine --ids", "MPE", "controller", "not available yet", "Windows",
                     "no longer tested"):
            self.assertIn(word, flat(newest), word)
        s031 = t[t.index("## New in 0.3.1"):t.index("## New in 0.3.0")]
        self.assertEqual(len(re.findall(r"^\d+\. \*\*", s031, re.M)), 6)
        for word in ("add-on", "Reporting a problem", "guided tour", "69", "MPE", "GitHub too", "has not run yet"):
            self.assertIn(word, flat(s031), word)
        self.assertNotIn("MPE checks in the scan", s031)
        new = t[t.index("## New in 0.3.0"):t.index("## Checked where")]
        self.assertEqual(len(re.findall(r"^\d+\. \*\*", new, re.M)), 10)
        self.assertIn("One download today", new)                        # what 0.3.0 itself said: the add-on is 0.3.1's
        self.assertNotIn("add-on", new)
        built = t[t.index("## (a) Built"):t.index("### Why the review is the product")]
        for word in ("`store`", "`als2ardour`", "`chain master --ardour`", "DAW mode, for Apple-silicon Macs first"):
            self.assertIn(word, built)
        self.assertNotIn("`chain` (Live and REAPER)", built)
        checked = flat(t[t.index("## Checked where"):t.index("## (a) Built")])
        for word in ("DAW mode", "the Store", "`als2ardour`", "`import`", "`chain --ardour`"):
            self.assertIn(word, checked)
        self.assertNotRegex(t, r"\| Ardour \|[^\n]*\| planned \|")
        self.assertNotIn("through its Lua scripting and OSC", t)

    def test_store_check_is_offline_and_read_only_in_the_agents_file(self):
        a = flat(read("AGENTS.md"))
        m = re.search(r"`store install`, `store uninstall`[^.]*use the internet", a)
        self.assertTrue(m, "the sentence about the commands that use the internet")
        self.assertNotIn("store check", m.group(0))
        self.assertRegex(a, r"`store check` is offline and read-only")

    def test_the_stretch_program_is_needed_for_tune_and_only_two_options_of_vocalign(self):
        for rel in ("README.md", "AGENTS.md"):
            t = flat(read(rel))
            self.assertNotRegex(t, r"Rubber Band 3\+ \(for `tune` and `vocalign`;", rel)
            self.assertRegex(t, r"`vocalign`'s formant and transpose options", rel)

    def test_the_tests_workflow_is_described_by_what_it_does(self):
        a = flat(read("AGENTS.md"))
        self.assertNotIn("has not run yet", a)
        self.assertIn("runs the suite on macOS and Windows (Python 3.9 and 3.12)", a)

    def test_the_demo_lines_say_the_reaper_project_has_the_full_loop(self):
        r = flat(read("README.md"))
        self.assertIn("The REAPER project (`demo --kind reaper`) is the one that gives the full loop", r)
        self.assertIn("`--kind reaper`, the one with the full scan, hear, apply loop", r)
        self.assertIn("gives the full loop", flat(read("hypnomix/app/wiki/articles/25-chores.html")))

    def test_the_guide_says_the_daw_is_added_from_setup_and_not_a_download(self):
        g = flat(read("docs/guides/09-setup-and-ai.md"))
        self.assertNotIn("it will be offered there once it is released", g)
        self.assertNotIn("the download page will offer it", g)
        self.assertIn("not a second download", g)

    def test_the_roadmap_gives_the_app_and_the_standalone_page_their_own_thresholds(self):
        r = flat(read("docs/ROADMAP.md"))
        self.assertIn("in the app, a review of more than 150 cards", r)
        self.assertIn("the standalone review page does the same above 300 findings", r)
        self.assertNotIn("a review over 300 findings builds its cards", r)

    def test_doctor_is_not_described_as_always_checking_live(self):
        for rel in ("README.md", "hypnomix/app/wiki/articles/25-chores.html"):
            self.assertIn("(if you use Live) Live, AbletonOSC", flat(read(rel)), rel)


# ================================================================ SECURITY
class ConnectScrubsTheKey(unittest.TestCase):
    """POST /api/setup/connect: a provider that repeats the key in its error must not get it back to the page."""
    KEY = "sk-SECOND-ABCDEFGH12345678zz"

    def setUp(self):
        from hypnomix.app import chat as CH
        self.CH = CH
        self.d = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(CH, "CONF", Path(self.d.name) / "ai.json")
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.d.cleanup()

    def connect(self, err):
        from hypnomix.app import setup as SU
        with mock.patch.object(self.CH, "list_models", side_effect=err):
            return SU.connect({"provider": "openai", "key": self.KEY, "model": ""})

    def test_an_error_that_repeats_the_key_is_masked(self):
        for err in (RuntimeError(f"Error code: 400 - Incorrect API key provided: {self.KEY}."),
                    ValueError(f"the provider said {self.KEY} is wrong")):
            code, r = self.connect(err)
            self.assertEqual((code, r["ok"]), (400, False))
            self.assertNotIn(self.KEY, json.dumps(r), type(err).__name__)
            self.assertIn("…78zz", r["error"], "the masked form the Assistant shows")

    def test_the_key_is_masked_even_when_it_was_not_saved_first(self):
        """The typed key goes through the same scrub even if the saved keys do not list it (a short-lived save)."""
        from hypnomix.app import setup as SU
        with mock.patch.object(self.CH, "list_models", side_effect=RuntimeError(f"bad key {self.KEY}")), \
                mock.patch.object(self.CH, "saved_keys", return_value=[]):
            code, r = SU.connect({"provider": "openai", "key": self.KEY, "model": ""})
        self.assertNotIn(self.KEY, json.dumps(r))

    def test_a_model_name_that_contains_the_key_is_masked_on_the_ok_path_and_in_the_model_list(self):
        """A provider that answers the model list with an id that repeats the key (connect ok path and /api/chat/models)."""
        import types
        from hypnomix.app import setup as SU
        fake = types.SimpleNamespace(models=types.SimpleNamespace(
            list=lambda: [types.SimpleNamespace(id="model-" + self.KEY), types.SimpleNamespace(id="plain")]))
        with mock.patch("openai.OpenAI", return_value=fake):
            code, r = SU.connect({"provider": "openai", "key": self.KEY, "model": ""})
            self.assertEqual((code, r["ok"]), (200, True))
            self.assertNotIn(self.KEY, json.dumps(r))
            self.assertIn("plain", r["models"])
            code, r = self.CH.handle_post("/api/chat/models", {})
            self.assertEqual(code, 200)
            self.assertNotIn(self.KEY, json.dumps(r))


class AssistantHomeShortening(unittest.TestCase):
    def setUp(self):
        from hypnomix.app import chat as CH
        self.CH = CH
        _isolate.fresh_chat()
        self.home = os.path.expanduser("~")
        self.assertGreater(len(self.home), 3)

    def tearDown(self):
        _isolate.fresh_chat()

    def test_run_hypnomix_results_and_not_run_messages_shorten_the_home_folder(self):
        from hypnomix.app import server as S
        out = f"wrote {self.home}/Music/Song/x.wav and /Users/somebody/Documents/y.wav"
        with mock.patch.object(S, "run_job"), mock.patch.object(self.CH, "wait_job", return_value=("done", out)):
            r = self.CH.run_cli("measure", [])
            self.assertNotIn(self.home, r)
            self.assertNotIn("somebody", r)
            self.assertIn("~/Music/Song/x.wav", r)
        with mock.patch.object(S, "run_job", side_effect=RuntimeError(f"busy with {self.home}/Music/a.wav")):
            r = self.CH.run_cli("measure", [])
            self.assertTrue(r.startswith("not run: "))
            self.assertNotIn(self.home, r)

    def test_through_the_tool_the_model_calls(self):
        with mock.patch.object(self.CH, "needs_ok", return_value=False), \
                mock.patch.object(self.CH, "run_cli", return_value=f"[done]\nin {self.home}/x"):
            r = self.CH.tool("run_hypnomix", {"command": "measure", "args": []})
        self.assertNotIn(self.home, r)
        self.assertIn("~/x", r)


def call(base, path, body=None, token=None, headers=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    if token:
        h["X-Hypnomix"] = token
    host, port = base
    c = http.client.HTTPConnection(host, port, timeout=10)
    try:
        c.request("POST" if body is not None else "GET", path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        raw = r.read()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, raw
    finally:
        c.close()


class AppRoutes(unittest.TestCase):
    """A private app instance on a free loopback port (never the real ports)."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.env = mock.patch.dict(os.environ, {"HYPNOMIX_APP_HOME": cls.td.name})
        cls.env.start()
        from hypnomix.app import server as S
        cls.S = S
        cls.d = Path(cls.td.name) / "scan" / "Song"
        (cls.d / "ab").mkdir(parents=True)
        (cls.d / "findings.json").write_text(json.dumps(dict(set="/nowhere/Song.als", findings=[], notes=[])), encoding="utf-8")
        sf.write(str(cls.d / "ab" / "own.wav"), np.zeros(4410, dtype=np.float32), 44100)
        cls.outside = Path(cls.td.name) / "outside"
        cls.outside.mkdir()
        sf.write(str(cls.outside / "leak.wav"), np.ones(4410, dtype=np.float32) * 0.1, 44100)
        os.symlink(cls.outside / "leak.wav", cls.d / "ab" / "sym.wav")
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(0))
        port = cls.srv.server_address[1]
        cls.srv.RequestHandlerClass = S.make_handler(port)
        cls.base = ("127.0.0.1", port)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.env.stop()
        cls.td.cleanup()

    def audio(self, name):
        from urllib.parse import quote
        return call(self.base, f"/audio?dir={quote(str(self.d))}&f={quote(name)}")

    # ---- (3) /audio and a link
    def test_audio_serves_a_clip_but_not_a_link_that_leaves_the_scan_folder(self):
        code, raw = self.audio("own.wav")
        self.assertEqual(code, 200)
        self.assertEqual(self.audio("sym.wav")[0], 404)
        self.assertEqual(self.audio("../outside/leak.wav")[0], 404)

    def test_a_link_to_another_clip_inside_the_same_scan_folder_is_fine(self):
        os.symlink(self.d / "ab" / "own.wav", self.d / "ab" / "inside.wav")
        try:
            self.assertEqual(self.audio("inside.wav")[0], 200)
        finally:
            (self.d / "ab" / "inside.wav").unlink()

    # ---- (4) over-long names
    def test_over_long_names_are_answered_with_a_sentence_not_a_dropped_connection(self):
        code, r = self.audio("a" * 5000 + ".wav")
        self.assertEqual(code, 400)
        self.assertIn("longer than", r["error"])
        for path, body in (("/api/scan", {"source": "/" + "b" * 6000}), ("/api/reveal", {"path": "/" + "c" * 6000})):
            code, r = call(self.base, path, body, self.S.TOKEN)
            self.assertEqual(code, 400, path)
            self.assertIn("longer than", r["error"], path)

    def test_name_too_long_recognises_the_two_system_codes(self):
        import errno
        self.assertTrue(self.S.name_too_long(OSError(errno.ENAMETOOLONG, "File name too long")))
        e = OSError(2, "x")
        e.winerror = 206
        self.assertTrue(self.S.name_too_long(e))
        self.assertFalse(self.S.name_too_long(OSError(errno.ENOENT, "No such file")))

    def test_a_name_over_255_characters_is_named_before_the_system_is_asked(self):
        """Windows answers a stat of such a name with "not found", so the sentence cannot depend on the system's own error."""
        for bad in ("a" * 300, "/x/" + "b" * 256 + "/y.wav", "C:\\x\\" + "c" * 256):
            with self.assertRaises(ValueError) as cm:
                self.S.long_name("fine", bad)
            self.assertIn("longer than", str(cm.exception))
        self.S.long_name("a" * 255, "/x/" + "b" * 255 + "/y.wav", None, 5, "")            # as long as a name may be: nothing said

    # ---- (6) the token on the routes the app's own page calls
    def test_the_probe_start_and_stop_the_page_calls_need_its_token(self):
        for path, body in (("/api/probe/start", {"label": ""}), ("/api/probe/stop", {"song": ""})):
            self.assertEqual(call(self.base, path, body)[0], 403, path)
            self.assertEqual(call(self.base, path, body, headers={"Origin": "http://evil.example"})[0], 403, path)
        with mock.patch.object(self.S, "probe_hub", return_value=None), mock.patch.dict(self.S.PROBE, {"hub": None}):
            code, r = call(self.base, "/api/probe/start", {"label": ""}, self.S.TOKEN)
            self.assertEqual(code, 409)                       # past the token check: the receiver is simply not running here
            code, r = call(self.base, "/api/probe/stop", {"song": ""}, self.S.TOKEN)
            self.assertEqual(code, 409)

    def test_the_page_sends_the_token_with_those_two_calls_and_the_device_routes_say_why_they_do_not(self):
        ui = read("hypnomix/app/ui.py")
        self.assertIn("'X-Hypnomix':TOKEN", ui)
        self.assertIn("post('/api/probe/start'", ui)
        src = read("hypnomix/app/server.py")
        self.assertIn("THE ROUTES BELOW TAKE NO TOKEN, on purpose", src)
        self.assertIn("Max for Live devices", src)

    def test_the_command_line_probe_sends_the_token_to_the_two_routes(self):
        from hypnomix.app import probe as P
        seen = []

        class R:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self.body

        def fake(req, timeout=0):
            seen.append((req.full_url, req.get_method(), {k.lower(): v for k, v in req.header_items()}))
            return R(b'const TOKEN = "tok-123";' if req.get_method() == "GET" else b'{"recording": true}')

        with mock.patch("hypnomix.core.loopback.urlopen", fake), mock.patch.object(P, "app_port", return_value=8799):
            self.assertEqual(P.app_call("/api/probe/start", {"label": "x"}), {"recording": True})
            self.assertEqual(P.app_call("/api/probe/stop", {"song": "x"}), {"recording": True})
        posts = [h for u, m, h in seen if m == "POST"]
        self.assertEqual(len(posts), 2)
        self.assertTrue(all(h.get("x-hypnomix") == "tok-123" for h in posts), posts)


class DawNewWithoutEngine(unittest.TestCase):
    def setUp(self):
        from hypnomix.app import daw as DW
        self.DW = DW
        self.td = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(DW.Engine, "binary", lambda self: None)
        self.p.start()
        self.eng = DW.Engine(binary=None, attach_url="http://127.0.0.1:9/mcp")

    def tearDown(self):
        self.p.stop()
        self.td.cleanup()

    def test_with_nothing_installed_and_nothing_listening_it_says_no_engine_is_installed(self):
        with self.assertRaises(RuntimeError) as cm:
            self.eng.new_session(self.td.name, "Song")
        msg = str(cm.exception)
        self.assertIn("no engine is installed", msg)
        self.assertNotIn("attached to a HypnoMix Studio window", msg)

    def test_with_a_window_already_open_it_still_says_to_use_that_window(self):
        with mock.patch.object(self.DW, "is_engine", return_value=True):
            with self.assertRaises(RuntimeError) as cm:
                self.eng.new_session(self.td.name, "Song")
        self.assertIn("attached to a HypnoMix Studio window", str(cm.exception))


class ChatStateBetweenModules(unittest.TestCase):
    """tests.test_chat then tests.test_daw_assistant in one process failed on a conversation left behind."""

    def pollute(self, pending=True):
        from hypnomix.app import chat as CH
        CH.CHAT.update(id="z", items=[{"kind": "user", "text": "go"}], history=[{"role": "user", "content": "go"}],
                       provider="anthropic", pending={"id": "p", "event": threading.Event()} if pending else None, error="boom", view="mixer", daw_groups={"x"},
                       foreign_said=True, daw_tools={"a": {}}, engine_mark="m", elided_at=4)
        CH.CHAT["usage"]["input"] = 90_000
        CH.CHAT["msg"] = dict(read0=0, cost0=0.0, listen0=0.0, allow=50_000)
        CH.PREVIEW.update(id="k1", title="t")
        return CH

    def assert_fresh(self, CH):
        c = CH.CHAT
        self.assertEqual((c["items"], c["history"], c["provider"], c["pending"], c["error"], c["busy"], c["stop"]),
                         ([], [], None, None, "", False, False))
        self.assertEqual((c["usage"]["input"], c["msg"], c["elided_at"], c["view"], c["daw_groups"], c["foreign_said"],
                          c["daw_tools"], c["engine_mark"]), (0, {}, 0, None, set(), False, {}, None))
        self.assertEqual((CH.PREVIEW["id"], CH.PREVIEW["title"]), (None, ""))

    def test_the_shared_helper_makes_a_new_conversation(self):
        CH = self.pollute()
        _isolate.fresh_chat()
        self.assert_fresh(CH)

    def test_both_modules_start_every_test_from_a_new_conversation(self):
        from tests import test_chat, test_daw_assistant
        for cls, name in ((test_chat.Chat, "test_key_is_kept_private_and_masked"),
                          (test_daw_assistant.Flow, "approve")):
            CH = self.pollute()
            case = cls(name)
            case.setUp()
            try:
                self.assert_fresh(CH)
                self.pollute(pending=False)
            finally:
                case.tearDown()
            self.assert_fresh(CH)                         # and none is left for the next module


# ================================================================ PACKAGING
NO_BASH = "SKIPPED: no bash here (Windows' own System32 bash.exe is the WSL launcher, not a shell), so this test was NOT run"
BASH = _isolate.find_bash()


class Packaging(unittest.TestCase):
    def pyproject_version(self):
        return re.search(r'^version = "([^"]+)"', read("pyproject.toml"), re.M).group(1)

    def test_the_hand_built_mac_app_takes_its_version_from_pyproject(self):
        if not BASH:
            self.skipTest(NO_BASH)
        sh = read("macapp/build.sh")
        self.assertNotIn("0.1.0", sh)
        self.assertIn("<key>CFBundleShortVersionString</key><string>$version</string>", sh)
        line = next(l for l in sh.splitlines() if l.startswith("version="))
        got = subprocess.run([BASH, "-c", f'repo="{ROOT.as_posix()}"\n{line}\nprintf %s "$version"'], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(got.stdout, self.pyproject_version())

    def test_the_daw_pages_client_version_is_the_apps_own(self):
        js = read("hypnomix/app/daw/js/mcp.js")
        self.assertNotRegex(js, r"version: '\d")
        self.assertIn("version: clientVersion", js)
        from hypnomix.app import daw as DW, update as UP
        html = DW.page("tok", "nonce").decode("utf-8")
        self.assertIn(f'window.HX_VERSION = "{UP.current()}"', html)
        self.assertNotIn("__VERSION__", html)
        self.assertEqual(UP.current(), self.pyproject_version())

    def stable_names(self, files):
        """Run the workflow's own 'Stable names' loops in a folder holding these files; -> the names that exist after."""
        if not BASH:
            self.skipTest(NO_BASH)
        yml = read(".github/workflows/installers.yml")
        step = yml[yml.index("- name: Stable names"):yml.index("- name: Build provenance")]
        loops = [l.strip() for l in step.splitlines() if l.strip().startswith("for f in")]
        self.assertEqual(len(loops), 3)
        with tempfile.TemporaryDirectory() as td:
            for name, content in files.items():
                (Path(td) / name).write_text(content, encoding="utf-8")
            r = subprocess.run([BASH, "-c", "shopt -s nullglob\n" + "\n".join(loops)], cwd=td, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            return {p.name: p.read_text(encoding="utf-8") for p in Path(td).iterdir()}

    def test_the_stable_names_point_at_the_one_installer_of_each_platform(self):
        after = self.stable_names({
            "Hypnomix-0.3.0-mac-arm64.dmg": "ARM", "Hypnomix-0.3.0-mac-x86_64.dmg": "INTEL",
            "Hypnomix-0.3.0-windows-x64-setup.exe": "WIN"})
        self.assertEqual(after["Hypnomix-mac-arm64.dmg"], "ARM")
        self.assertEqual(after["Hypnomix-mac-intel.dmg"], "INTEL")
        self.assertEqual(after["Hypnomix-windows-setup.exe"], "WIN")
        self.assertNotIn("-full-", read(".github/workflows/installers.yml"))        # there is no second image to skip


if __name__ == "__main__":
    unittest.main()
