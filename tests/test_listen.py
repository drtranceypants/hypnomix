"""Listening: which key and model a listen uses, that it is off by default, and that audio waits for a click."""
import json, os, subprocess, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock

from hypnomix.app import chat as CH
from hypnomix.ears import critique as L


class Listener(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.conf = Path(self.d.name) / "ai.json"
        self.p = [mock.patch.object(CH, "CONF", self.conf), mock.patch.object(L, "CONF", self.conf),
                  mock.patch.dict(os.environ, {"HYPNOMIX_APP_HOME": self.d.name}, clear=False)]
        for p in self.p:
            p.start()
        for k in ("GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            os.environ.pop(k, None)
        CH.CHAT.update(items=[], history=[], provider=None, busy=False, pending=None, stop=False, usage=CH.new_usage())

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.d.cleanup()

    def test_which_key_and_model(self):
        self.assertEqual(L.listener()[0], "openrouter")                 # nothing set: OpenRouter, no key
        self.assertEqual(L.listener()[3], "")
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "g-env"}):
            p, base, model, key = L.listener()
            self.assertEqual((p, model, key), ("gemini", "gemini-4-carbon", "g-env"))
        CH.update_settings({"provider": "openrouter", "key": "sk-or-12345678"})
        CH.update_settings({"listen_provider": "openrouter", "listen_model": "google/gemini-3.5-flash-lite"})
        self.assertEqual(L.listener()[2:], ("google/gemini-3.5-flash-lite", "sk-or-12345678"))
        self.assertEqual(L.listener("gemini")[2], "gemini-4-carbon")

    def test_settings_show_listening_without_keys(self):
        CH.update_settings({"provider": "gemini", "key": "AIza-secret-98765432"})
        v = CH.settings_view()
        self.assertEqual(v["listen"]["provider"], "")                     # off by default
        self.assertTrue(next(o for o in v["listen"]["options"] if o["id"] == "gemini")["has_key"])
        self.assertNotIn("secret", json.dumps(v))
        with self.assertRaises(ValueError):
            CH.update_settings({"listen_provider": "anthropic"})
        CH.update_settings({"listen_provider": "gemini"})
        self.assertEqual(CH.settings_view()["listen"]["provider"], "gemini")
        CH.update_settings({"listen_provider": ""})
        self.assertEqual(CH.settings_view()["listen"]["provider"], "")

    def _song(self):
        f = Path(self.d.name) / "Song.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=4",
                        str(f)], check=True)
        return f

    def test_off_means_no_audio_goes_anywhere(self):
        with mock.patch.object(L, "listen") as sent:
            out = CH.listen_tool({"audio": str(self._song()), "question": "", "dir": ""})
        self.assertIn("Listening is off", out)
        sent.assert_not_called()

    def test_audio_waits_for_the_click(self):
        CH.update_settings({"provider": "gemini", "key": "AIza-12345678", "listen_provider": "gemini"})
        song = self._song()
        for click, expect in ((False, "chose not to send"), (True, "sounds fine")):
            def answer():
                for _ in range(100):
                    p = CH.CHAT.get("pending")
                    if p:
                        self.assertEqual(p["what"], "listen")
                        CH.answer(p["id"], click)
                        return
                    time.sleep(0.02)
            threading.Thread(target=answer).start()
            with mock.patch.object(L, "listen", return_value=("sounds fine", {"cost": None})) as sent:
                out = CH.listen_tool({"audio": str(song), "question": "vocal level?", "dir": ""})
            self.assertIn(expect, out)
            self.assertEqual(sent.called, click)
        ask = [i for i in CH.CHAT["items"] if i.get("kind") == "ask"]
        self.assertIn("0.1 min", ask[0]["text"])
        self.assertIn("vocal level?", ask[0]["text"])

    def test_a_wrong_folder_for_the_scans_own_bounce_is_forgiven(self):
        """The model rebuilt ~ from another home: the file name matches the scan's bounce, so that one is used."""
        song = self._song()
        scan = Path(self.d.name) / "scan"; scan.mkdir()
        (scan / "scan.json").write_text(json.dumps({"mix": str(song)}))
        with mock.patch("hypnomix.app.server.scan_dir", return_value=scan):
            self.assertEqual(CH.scan_bounce("scan", Path("/elsewhere/Song.wav")), song)
            self.assertIsNone(CH.scan_bounce("scan", Path("/elsewhere/Other.wav")))

    def test_estimate(self):
        e = L.estimate(self._song(), "gemini", "gemini-4-carbon")
        self.assertAlmostEqual(e["seconds"], 4.0, delta=0.1)
        self.assertEqual(e["tokens"], 4 * 25 + 1500)

    def test_listener_has_its_own_key(self):
        """The chat can be Claude while the listener is Google, each with its own key; keys never show in full."""
        CH.update_settings({"provider": "anthropic", "key": "sk-ant-chat-11112222"})
        CH.update_settings({"listen_provider": "gemini", "listen_key": "AIza-listen-33334444",
                            "listen_model": "gemini-4-hydrogen"})
        c = json.loads(self.conf.read_text())
        self.assertEqual((c["provider"], c["keys"]["anthropic"], c["keys"]["gemini"]),
                         ("anthropic", "sk-ant-chat-11112222", "AIza-listen-33334444"))
        self.assertEqual(L.listener()[2:], ("gemini-4-hydrogen", "AIza-listen-33334444"))
        v = json.dumps(CH.settings_view(), ensure_ascii=False)
        self.assertNotIn("listen-3333", v)
        self.assertIn("…4444", v)
        CH.update_settings({"listen_provider": "gemini", "listen_forget": True})
        self.assertNotIn("gemini", json.loads(self.conf.read_text())["keys"])
        self.assertEqual(json.loads(self.conf.read_text())["keys"]["anthropic"], "sk-ant-chat-11112222")

    def test_audio_models_best_first_and_no_tts(self):
        names = ["gemini-3.5-flash", "gemini-3.8-flash-tts", "gemini-4-carbon", "gemini-2.5-flash-image",
                 "gemini-4-hydrogen", "gemini-3.5-transcribe", "gemma-3", "gemini-4-neon"]
        body = json.dumps({"models": [{"name": "models/" + n, "supportedGenerationMethods": ["generateContent"]}
                                      for n in names]}).encode()

        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, *a): return body
        with mock.patch.object(L.urllib.request, "urlopen", return_value=R()):
            got = L.audio_models("gemini", key="k")
        self.assertEqual(got, ["gemini-4-carbon", "gemini-4-hydrogen", "gemini-3.5-flash", "gemini-4-neon"])

    def test_gemini_thought_signature_goes_back(self):
        """Gemini refuses the call after a tool use unless each tool call's extra_content comes back as it was."""
        from openai.types.chat import ChatCompletion
        sent = []

        def reply(i):
            msg = ({"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
                    "function": {"name": "list_songs", "arguments": "{}"},
                    "extra_content": {"google": {"thought_signature": "SIG"}}}]} if i == 0
                   else {"role": "assistant", "content": "done"})
            return ChatCompletion.model_validate({"id": "x", "object": "chat.completion", "created": 0, "model": "m",
                                                  "choices": [{"index": 0, "finish_reason": "stop", "message": msg}]})

        class Fake:
            def __init__(self, **k):
                self.chat = self
                self.completions = self

            def create(self, **k):
                sent.append(json.loads(json.dumps(k["messages"])))
                return reply(len(sent) - 1)
        CH.CHAT["provider"] = "gemini"
        CH.CHAT["history"] = [{"role": "user", "content": "hi"}]
        with mock.patch("openai.OpenAI", Fake), mock.patch.object(CH, "tool", return_value="[]"):
            CH._openai_turn("m", "k", "")
        tc = sent[1][-2]["tool_calls"][0]
        self.assertEqual(tc["extra_content"], {"google": {"thought_signature": "SIG"}})


class Context(unittest.TestCase):
    """F3: what `critique` may read as text for a cloud model, and that the Assistant cannot run it."""

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = Path(self.d.name)
        self.p = mock.patch.object(L, "CONF", self.root / "home" / ".hypnomix" / "ai.json")
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.d.cleanup()

    def _file(self, rel, text="hello"):
        f = self.root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        return f

    def test_normal_command_line_use_still_works(self):
        prof = self._file("PROFILE.md", "my style")
        meas = self._file("song.json", '{"lufs": -14}')
        note = self._file("notes.txt", "n")
        scan = self.root / "scan"
        self._file("scan/REVIEW.md", "findings here")
        out = L.context(scan=scan, measure=meas, profile=prof)
        for want in ("my style", '{"lufs": -14}', "findings here"):
            self.assertIn(want, out)
        self.assertIn("n", L.context(profile=note))
        (self.root / "scan2").mkdir()
        self._file("scan2/findings.json", "{}")                       # a scan folder without a review: nothing to add
        self.assertEqual(L.context(scan=self.root / "scan2"), "")
        self.assertEqual(L.context(), "")

    def test_profile_and_measure_take_only_plain_reports(self):
        secret = self._file("home/.hypnomix/ai.json", '{"keys": {"openrouter": "sk-or-SECRET"}}')
        cases = [secret,                                              # in a dot-directory (and the keys file itself)
                 self._file("home/.hypnomix/preferences.json", "{}"),
                 self._file("home/.zshrc", "export TOKEN=abc"),         # a dotfile, and not .md/.json/.txt
                 self._file("notes/.hidden.md", "x"),                  # a dotfile with an allowed suffix
                 self._file(".config/profile.md", "x"),                # in a dot-directory
                 self._file("id_rsa", "-----BEGIN"),                    # not a report suffix
                 self._file("script.py", "x"),
                 self.root / "missing.md", self.root]                  # not there / a folder
        for f in cases:
            for kw in ("profile", "measure"):
                with self.assertRaises(ValueError, msg=(kw, f)) as cm:
                    L.context(**{kw: f})
                self.assertNotIn("SECRET", str(cm.exception))
        link = self.root / "innocent.json"                              # a link pointing at the keys file
        link.symlink_to(secret)
        with self.assertRaises(ValueError):
            L.context(measure=link)
        hidden_link = self.root / "x.md"
        hidden_link.symlink_to(self.root / "home" / ".zshrc")
        with self.assertRaises(ValueError):
            L.context(profile=hidden_link)

    def test_a_hard_link_to_the_keys_file_is_refused(self):
        secret = self._file("home/.hypnomix/ai.json", '{"keys": {"openrouter": "sk-or-SECRET"}}')
        hard = self.root / "ok" / "hard.json"
        hard.parent.mkdir()
        os.link(secret, hard)
        for kw in ("profile", "measure"):
            with self.assertRaises(ValueError) as cm:
                L.context(**{kw: hard})
            self.assertNotIn("SECRET", str(cm.exception))

    def test_a_huge_file_is_refused_and_a_big_one_is_cut(self):
        big = self._file("big.json", "x" * (L.MAX_CONTEXT_FILE + 1))
        with self.assertRaises(ValueError) as cm:
            L.context(measure=big)
        self.assertIn("smaller", str(cm.exception))
        ok = self._file("ok.txt", "y" * 50000)
        self.assertEqual(len(L.context(profile=ok).split(":\n", 1)[1]), 6000)

    def test_scan_takes_only_a_scan_folder(self):
        self._file("docs/readme.md", "not a scan")
        self._file("home/.ssh/config", "Host *")
        for d in (self.root / "docs", self.root / "home", self.root, self.root / "nope", self._file("afile.md")):
            with self.assertRaises(ValueError, msg=str(d)):
                L.context(scan=d)
        outside = self._file("elsewhere/secret.md", "TOP SECRET")      # a REVIEW.md that is a link out of the folder
        scan = self.root / "linked"
        scan.mkdir()
        (scan / "REVIEW.md").symlink_to(outside)
        with self.assertRaises(ValueError):
            L.context(scan=scan)

    def test_the_command_line_says_why_it_refuses(self):
        with mock.patch("sys.argv", ["critique", str(self._file("a.wav")), "--profile",
                                     str(self._file("home/.hypnomix/ai.json", "{}"))]), \
                mock.patch.object(L, "estimate", return_value=dict(seconds=1.0, tokens=1, cost=None)), \
                mock.patch.object(L, "listen") as sent:
            with self.assertRaises(SystemExit) as cm:
                L.main()
        self.assertIn("hidden", str(cm.exception))
        sent.assert_not_called()

    def test_the_assistant_cannot_run_critique_even_with_listening_off(self):
        CH.CHAT.update(items=[], pending=None)
        with mock.patch.object(L, "listen") as sent, mock.patch.object(CH, "run_cli") as run:
            out = CH.tool("run_hypnomix", {"command": "critique", "args": ["a.wav", "--profile", "/Users/x/notes.md"]})
        self.assertIn("listen tool", out)
        sent.assert_not_called()
        run.assert_not_called()
        self.assertTrue(CH.needs_ok("critique", ["a.wav"]))


if __name__ == "__main__":
    unittest.main()
