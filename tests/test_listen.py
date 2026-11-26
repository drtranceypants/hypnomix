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


if __name__ == "__main__":
    unittest.main()
