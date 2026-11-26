"""Listening: which key and model a listen uses, that it is off by default, and that audio waits for a click."""
import io, json, os, re, subprocess, sys, tempfile, threading, time, types, unittest
from pathlib import Path
from unittest import mock

from hypnomix.app import chat as CH
from hypnomix.ears import critique as L


class Listener(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.conf = Path(self.d.name) / "ai.json"
        self.p = [mock.patch.object(CH, "CONF", self.conf), mock.patch.object(L, "CONF", self.conf),
                  mock.patch.object(L, "CACHE_DIR", Path(self.d.name) / "cache" / "listen"),
                  mock.patch.dict(L._OR, {"data": None, "failed": 0.0}),
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
        song = self._song()
        e = L.estimate(song, "gemini", "gemini-4-carbon")
        self.assertAlmostEqual(e["seconds"], 4.0, delta=0.1)
        text = len(L.PROMPT) // 4                                          # the prompt goes along too
        self.assertEqual(e["tokens_in"], 4 * 25 + text)
        self.assertEqual(e["tokens"], e["tokens_in"] + L.NOTES_TOKENS)
        self.assertAlmostEqual(e["cost"], (e["tokens_in"] * 0.75 + L.NOTES_TOKENS * 3.75) / 1e6, places=4)   # from the price table
        self.assertIn("free tier", e["basis"])
        # the review, the measurements and the question are counted: 10,000 characters is 2,500 tokens
        e2 = L.estimate(song, "gemini", "gemini-4-carbon", context="r" * 10_000, question="q" * 400)
        self.assertEqual(e2["tokens_in"], e["tokens_in"] + 2500 + 100)
        self.assertEqual(e2["context_tokens"], text + 2600)
        # only the first seconds, when asked
        self.assertAlmostEqual(L.estimate(song, "gemini", "m", seconds_limit=2)["seconds"], 2.0)
        self.assertAlmostEqual(L.estimate(song, "gemini", "m", seconds_limit=2)["full_seconds"], 4.0, delta=0.1)
        # OpenRouter: its own listed price
        with mock.patch.object(L, "openrouter_price", return_value=(2e-6, 1e-5)):
            o = L.estimate(song, "openrouter", "google/gemini-4-carbon")
        self.assertAlmostEqual(o["cost"], o["tokens_in"] * 2e-6 + L.NOTES_TOKENS * 1e-5, places=4)
        with mock.patch.object(L, "openrouter_price", return_value=None):
            self.assertIsNone(L.estimate(song, "openrouter", "x")["cost"])
        card = L.describe(e2, "gemini", "gemini-4-carbon", "Song.wav", "vocal?")
        for want in ("Song.wav", "mono", "Google Gemini", "generativelanguage.googleapis.com", "gemini-4-carbon", "tokens in", "estimate", "$"):
            self.assertIn(want, card)

    def test_openrouters_model_list_is_fetched_once_per_session(self):
        body = json.dumps({"data": [{"id": "a/m1", "pricing": {"prompt": "0.000001", "completion": "0.000004", "input_audio": "0.000002"}},
                                    {"id": "a/m2", "pricing": {"prompt": "0.5", "completion": "0.6"}}]}).encode()
        n = {"i": 0}

        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, *a): return body
        def opener(*a, **k):
            n["i"] += 1
            return R()
        with mock.patch.object(L.urllib.request, "urlopen", opener):
            self.assertEqual(L.openrouter_price("a/m1"), (2e-6, 4e-6))
            self.assertEqual(L.openrouter_price("a/m2"), (0.5, 0.6))
            self.assertIsNone(L.openrouter_price("a/none"))
            L.estimate(self._song(), "openrouter", "a/m1")
        self.assertEqual(n["i"], 1)
        L._OR.update(data=None, failed=0.0)
        n["i"] = 0

        def broken(*a, **k):
            n["i"] += 1
            raise OSError("offline")
        with mock.patch.object(L.urllib.request, "urlopen", broken):
            self.assertIsNone(L.openrouter_price("a/m1"))
            self.assertIsNone(L.openrouter_price("a/m1"))                  # not retried at once: no wait for a timeout each time
        self.assertEqual(n["i"], 1)

    # ------------------------------------------------------------ saved notes, the card, long songs
    def _scan_with_review(self, chars=10_000):
        scan = Path(self.d.name) / "scan" / "Song"
        scan.mkdir(parents=True)
        (scan / "findings.json").write_text("{}")
        (scan / "REVIEW.md").write_text("r" * chars)
        return scan

    def _clicks(self, *answers):
        """A thread that answers each question the chat asks, in turn: (yes, choice) pairs."""
        def run():
            for yes, choice in answers:
                for _ in range(300):
                    p = CH.CHAT.get("pending")
                    if p:
                        CH.answer(p["id"], yes, choice)
                        break
                    time.sleep(0.02)
        t = threading.Thread(target=run)
        t.start()
        return t

    def _fake_openai(self):
        calls = []

        class Fake:
            def __init__(self, **k):
                self.chat = types.SimpleNamespace(completions=self)

            def create(self, model, messages):
                calls.append(model)
                return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="the vocal sits well"))],
                                             usage=types.SimpleNamespace(prompt_tokens=7000, completion_tokens=900, cost=None))
        return Fake, calls

    def test_the_card_counts_the_review_and_shows_an_estimate_in_dollars(self):
        CH.update_settings({"provider": "gemini", "key": "AIza-12345678", "listen_provider": "gemini"})
        song, scan = self._song(), self._scan_with_review()
        seen = []
        for d in ("", str(scan)):
            t = self._clicks((False, None))
            with mock.patch("hypnomix.app.server.scan_dir", return_value=scan), mock.patch.object(L, "listen") as sent:
                CH.listen_tool({"audio": str(song), "question": "", "dir": d, "again": False, "minutes": 0})
            t.join()
            sent.assert_not_called()
            seen.append([i for i in CH.CHAT["items"] if i.get("kind") == "ask"][-1]["text"])
        tokens = [int(re.search(r"About ([\d,]+) tokens in", x).group(1).replace(",", "")) for x in seen]
        self.assertTrue(2500 <= tokens[1] - tokens[0] <= 2600, tokens)      # the 10,000-character review (and its label) is in the estimate
        self.assertIn("the review", seen[1])
        for x in seen:
            self.assertRegex(x, r"roughly \$0\.\d+ \(an estimate")           # a dollar figure, labelled
            self.assertIn("generativelanguage.googleapis.com", x)           # where it goes

    def test_notes_already_heard_come_back_free_before_any_card(self):
        CH.update_settings({"provider": "gemini", "key": "AIza-12345678", "listen_provider": "gemini"})
        song, scan = self._song(), self._scan_with_review(2000)
        Fake, calls = self._fake_openai()
        listen = lambda **k: CH.listen_tool(dict(dict(audio=str(song), question="vocal?", dir=str(scan), again=False, minutes=0), **k))
        with mock.patch("hypnomix.app.server.scan_dir", return_value=scan), mock.patch("openai.OpenAI", Fake):
            t = self._clicks((True, None))
            first = listen()
            t.join()
            self.assertIn("the vocal sits well", first)
            self.assertEqual(len(calls), 1)
            asks = lambda: len([i for i in CH.CHAT["items"] if i.get("kind") == "ask"])
            self.assertEqual(asks(), 1)
            again = listen()                                              # same song, model, question, context
            self.assertIn("the vocal sits well", again)
            self.assertIn("nothing was sent now", again)
            self.assertEqual((len(calls), asks()), (1, 1))                  # no upload and no card
            note = [i for i in CH.CHAT["items"] if i.get("kind") == "note"][-1]
            self.assertEqual(note["text"], "Already heard with this model and question: showing the saved notes (free).")
            self.assertIn("again", note)                                    # the "Listen again" button's text
            # anything that changes what is heard is a new listen, with its card
            for change in (dict(question="and the bass?"), dict(again=True), dict(minutes=1)):
                before = asks()
                t = self._clicks((True, None))
                listen(**change)
                t.join()
                self.assertEqual(asks(), before + 1, change)
            (scan / "REVIEW.md").write_text("changed review")               # a new review is new context
            t = self._clicks((True, None))
            listen()
            t.join()
            self.assertEqual(len(calls), 5)
            CH.update_settings({"listen_provider": "gemini", "listen_model": "gemini-4-hydrogen"})   # another model
            t = self._clicks((True, None))
            listen()
            t.join()
            self.assertEqual(len(calls), 6)

    def test_the_saved_notes_are_private_and_keyed_on_the_file(self):
        CH.update_settings({"provider": "gemini", "key": "AIza-12345678", "listen_provider": "gemini"})
        song = self._song()
        k = lambda f, **kw: L.cache_key(f, **dict(dict(provider="gemini", model="m", question="q", context="c"), **kw))
        copy = Path(self.d.name) / "elsewhere" / "Renamed.wav"
        copy.parent.mkdir()
        copy.write_bytes(song.read_bytes())
        self.assertEqual(k(song), k(copy))                                   # the same bounce under another name
        copy.write_bytes(song.read_bytes() + b"x")                           # size and the last megabyte changed
        self.assertNotEqual(k(song), k(copy))
        for kw in (dict(model="n"), dict(question="r"), dict(context="d"), dict(provider="openrouter"), dict(seconds_limit=60)):
            self.assertNotEqual(k(song), k(song, **kw), kw)
        big = Path(self.d.name) / "big.bin"                                  # first and last megabyte decide, not a full read
        big.write_bytes(b"a" * (3 << 20))
        key = k(big)
        big.write_bytes(b"a" * (1 << 20) + b"b" + b"a" * ((2 << 20) - 1))      # a change in the middle: same size, same ends
        self.assertEqual(key, k(big))
        big.write_bytes(b"c" + b"a" * ((3 << 20) - 1))
        self.assertNotEqual(key, k(big))
        L.remember(song, "gemini", "m", "q", "c", None, "notes here", dict(input=5, output=6, cost=None))
        f = next(L.CACHE_DIR.glob("*.json"))
        self.assertEqual(oct(f.stat().st_mode)[-3:], "600")
        self.assertNotIn("AIza", f.read_text())                              # no key in it
        self.assertEqual(L.cached(song, "gemini", "m", "q", "c")["notes"], "notes here")
        self.assertIsNone(L.cached(song, "gemini", "m", "other question", "c"))

    def test_a_long_song_asks_whole_or_the_first_twelve_minutes(self):
        CH.update_settings({"provider": "gemini", "key": "AIza-12345678", "listen_provider": "gemini"})
        song = self._song()
        got = []
        with mock.patch.object(L, "duration", return_value=1500.0), \
                mock.patch.object(L, "listen", side_effect=lambda *a: (got.append(a[-1]), ("notes", {"cost": None}))[1]):
            for answer, expect in (((True, "first"), 720), ((True, "whole"), None)):
                t = self._clicks(answer)
                out = CH.listen_tool({"audio": str(song), "question": "", "dir": "", "again": False, "minutes": 0})
                t.join()
                self.assertIn("notes", out)
                self.assertEqual(got[-1], expect)
            card = [i for i in CH.CHAT["items"] if i.get("kind") == "ask"][-1]
            self.assertEqual([o["value"] for o in card["options"]], ["whole", "first"])
            self.assertIn("25 minutes, more than 12", card["text"])
            self.assertRegex(card["text"], r"all of it is about [\d,]+ tokens, roughly \$[\d.]+; the first 12 minutes are [\d,]+")
            self.assertEqual(card["answer"], "whole")
            n = len(got)
            t = self._clicks((False, None))                                  # no
            self.assertIn("chose not to send", CH.listen_tool({"audio": str(song), "question": "", "dir": "", "again": False, "minutes": 0}))
            t.join()
            self.assertEqual(len(got), n)
            t = self._clicks((True, "bogus"))                                # a yes that names nothing offered is a no
            self.assertIn("chose not to send", CH.listen_tool({"audio": str(song), "question": "x", "dir": "", "again": False, "minutes": 0}))
            t.join()
            self.assertEqual(len(got), n)
            before = len(CH.CHAT["items"])                                    # the person asked for the first 5 minutes: no choice to make
            t = self._clicks((True, None))
            CH.listen_tool({"audio": str(song), "question": "y", "dir": "", "again": False, "minutes": 5})
            t.join()
            self.assertEqual(got[-1], 300)
            self.assertIsNone([i for i in CH.CHAT["items"][before:] if i.get("kind") == "ask"][0]["options"] or None)

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
        self.p2 = mock.patch.object(L, "CACHE_DIR", self.root / "cache" / "listen")
        self.p2.start()

    def tearDown(self):
        self.p.stop()
        self.p2.stop()
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


class Tty(io.StringIO):
    def isatty(self):
        return True


class CommandLine(unittest.TestCase):
    """`hypnomix critique FILE` asks before it uploads: y/N in a terminal, --yes elsewhere, --estimate only prints."""

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = Path(self.d.name)
        conf = self.root / "ai.json"
        conf.write_text(json.dumps({"keys": {"gemini": "AIza-12345678"}, "listen": {"provider": "gemini"}}))
        self.p = [mock.patch.object(L, "CONF", conf), mock.patch.object(L, "CACHE_DIR", self.root / "cache" / "listen")]
        for p in self.p:
            p.start()
        self.song = self.root / "Song.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=3", str(self.song)], check=True)
        self.calls = []
        calls = self.calls

        class Fake:
            def __init__(self, **k):
                self.chat = types.SimpleNamespace(completions=self)

            def create(self, model, messages):
                calls.append(model)
                return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="good low end"))],
                                             usage=types.SimpleNamespace(prompt_tokens=100, completion_tokens=20, cost=None))
        self.p.append(mock.patch("openai.OpenAI", Fake))
        self.p[-1].start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.d.cleanup()

    def run_main(self, *args, tty=False, typed=()):
        err = Tty() if tty else io.StringIO()
        argv = ["critique", str(self.song), "--out", str(self.root / "out"), *args]
        with mock.patch("sys.argv", argv), mock.patch("sys.stderr", err), \
                mock.patch("sys.stdin", Tty() if tty else io.StringIO()), \
                mock.patch("builtins.input", side_effect=list(typed)) as ask, mock.patch("builtins.print") as shown:
            try:
                L.main()
                code = None
            except SystemExit as e:
                code = str(e.code)
        printed = [str(c.args[0]) for c in shown.call_args_list if c.args]
        return code, err.getvalue() + "\n".join(printed), ask.call_count

    def test_not_a_terminal_and_no_yes_sends_nothing(self):
        code, text, asked = self.run_main()
        self.assertIn("not a terminal", code)
        self.assertIn("--yes", code)
        self.assertEqual((self.calls, asked), ([], 0))
        self.assertIn("Google Gemini", text)                       # it still said what it would have sent
        self.assertFalse((self.root / "out").exists())

    def test_estimate_only_prints_and_sends_nothing(self):
        code, text, asked = self.run_main("--estimate")
        self.assertIsNone(code)
        self.assertEqual((self.calls, asked), ([], 0))
        for want in ("0.1 min", "Google Gemini", "gemini-4-carbon", "tokens in", "estimate", "generativelanguage.googleapis.com"):
            self.assertIn(want, text)

    def test_yes_sends_and_writes_the_notes(self):
        code, text, asked = self.run_main("--yes")
        self.assertIsNone(code)
        self.assertEqual((self.calls, asked), (["gemini-4-carbon"], 0))
        out = (self.root / "out" / "Song.md").read_text()
        self.assertIn("good low end", out)
        self.assertIn("100 tokens in", out)

    def test_in_a_terminal_it_prints_what_it_will_send_and_asks(self):
        code, text, asked = self.run_main(tty=True, typed=["n"])
        self.assertIn("nothing was sent", code)
        self.assertEqual((self.calls, asked), ([], 1))
        for want in ("Song.wav", "Google Gemini", "estimate"):
            self.assertIn(want, text)
        code, text, asked = self.run_main(tty=True, typed=[""])               # just Enter is a no
        self.assertIn("nothing was sent", code)
        self.assertEqual(self.calls, [])
        code, text, asked = self.run_main(tty=True, typed=["y"])
        self.assertIsNone(code)
        self.assertEqual(self.calls, ["gemini-4-carbon"])

    def test_the_same_listen_again_is_free_and_again_pays_again(self):
        self.run_main("--yes")
        self.assertEqual(len(self.calls), 1)
        code, text, asked = self.run_main()                                     # no --yes, not a terminal: needs no yes, nothing is sent
        self.assertIsNone(code)
        self.assertIn("showing the saved notes (free)", text)
        self.assertEqual((len(self.calls), asked), (1, 0))
        self.assertIn("saved notes, nothing sent", (self.root / "out" / "Song.md").read_text())
        code, text, asked = self.run_main("--estimate")
        self.assertIn("saved notes would be shown, free", text)
        code, text, asked = self.run_main("--again")                             # a fresh listen is a new send: it asks
        self.assertIn("not a terminal", code)
        self.run_main("--again", "--yes")
        self.assertEqual(len(self.calls), 2)
        self.run_main("--question", "is the kick loud?", "--yes")               # another question: another listen
        self.assertEqual(len(self.calls), 3)

    def test_a_song_over_twelve_minutes_warns_and_the_person_chooses(self):
        with mock.patch.object(L, "duration", return_value=1500.0):
            code, text, asked = self.run_main()
            self.assertIn("not a terminal", code)
            self.assertIn("WARNING: this is 25 minutes, longer than 12", text)
            self.assertRegex(text, r"whole file is about [\d,]+ tokens; its first 12 minutes would be [\d,]+")
            code, text, asked = self.run_main(tty=True, typed=["n"])
            self.assertIn("nothing was sent", code)
            self.assertEqual(self.calls, [])
            sent = []
            real = L.listen
            with mock.patch.object(L, "listen", side_effect=lambda *a: (sent.append(a[-1]), real(*a))[1]):
                self.run_main(tty=True, typed=["f"])                              # the first 12 minutes (one answer is the yes)
                self.assertEqual((sent, len(self.calls)), ([720], 1))
                self.run_main(tty=True, typed=["w"])                              # the whole file
                self.assertEqual(sent, [720, None])
                self.run_main("--minutes", "5", "--yes")                          # chosen on the command line: no warning
                self.assertEqual(sent[-1], 300)
                code, text, asked = self.run_main("--again", "--yes")
                self.assertEqual(sent[-1], None)
                self.assertIn("WARNING", text)                                    # --yes still says what it sent
        code, text, asked = self.run_main("--minutes", "0")
        self.assertIn("more than 0", code)

    def test_estimate_warns_about_a_long_song_too(self):
        with mock.patch.object(L, "duration", return_value=800.0):                 # 13.3 minutes
            code, text, asked = self.run_main("--estimate")
            self.assertIsNone(code)
            self.assertEqual((self.calls, asked), ([], 0))
            self.assertIn("WARNING: this is 13 minutes, longer than 12", text)
            self.assertRegex(text, r"whole file is about [\d,]+ tokens; its first 12 minutes would be [\d,]+")
            self.assertIn("--minutes 12", text)
            code, text, asked = self.run_main("--estimate", "--minutes", "5")         # already chosen: no warning
            self.assertNotIn("WARNING", text)
        code, text, asked = self.run_main("--estimate")                              # a short song: no warning
        self.assertNotIn("WARNING", text)

    def test_the_help_says_so(self):
        out = io.StringIO()
        with mock.patch("sys.argv", ["critique", "-h"]), mock.patch("sys.stdout", out):
            with self.assertRaises(SystemExit):
                L.main()
        h = out.getvalue()
        for want in ("--yes", "--estimate", "--minutes", "--again", "person has said yes", "asks"):
            self.assertIn(want, h)
        self.assertIn("y/N", L.__doc__)
        self.assertIn("--yes", (Path(L.__file__).resolve().parents[2] / "AGENTS.md").read_text())


if __name__ == "__main__":
    unittest.main()
