"""The Assistant tab: both provider loops (with stand-in clients), the click-to-run gate, and the key's safety."""
import json, os, tempfile, time, types, unittest
from pathlib import Path
from unittest import mock

from hypnomix.app import chat as CH


def wait_idle(timeout=10):
    t = time.time()
    while CH.state()["busy"] and time.time() - t < timeout:
        time.sleep(0.05)


class Blk(dict):
    __getattr__ = dict.__getitem__

    def model_dump(self, **k):
        return dict(self)


import importlib.util
HAVE_SDKS = all(importlib.util.find_spec(m) for m in ("anthropic", "openai"))


@unittest.skipUnless(HAVE_SDKS, "pip install 'hypnomix[assistant]' for the Assistant tab")
class Chat(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.p = [mock.patch.object(CH, "CONF", Path(self.d.name) / "ai.json"),
                  mock.patch.dict(os.environ, {"HYPNOMIX_APP_HOME": self.d.name})]
        for p in self.p:
            p.start()
        CH.CHAT.update(items=[], history=[], provider=None, busy=False, pending=None, stop=False)

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.d.cleanup()

    def test_key_is_kept_private_and_masked(self):
        CH.update_settings({"provider": "anthropic", "key": "sk-ant-secret-12345678"})
        self.assertEqual(oct(CH.CONF.stat().st_mode)[-3:], "600")
        view = json.dumps(CH.settings_view(), ensure_ascii=False)
        self.assertNotIn("secret", view)
        self.assertIn("…5678", view)
        CH.update_settings({"provider": "anthropic", "forget": True})
        self.assertNotIn("anthropic", json.loads(CH.CONF.read_text()).get("keys", {}))

    def test_what_waits_for_a_click(self):
        self.assertFalse(CH.needs_ok("fix", ["DIR", "--list"]))
        self.assertFalse(CH.needs_ok("scan", ["Song.als", "--out", "scan dir"]))
        self.assertTrue(CH.needs_ok("fix", ["DIR", "--approved", "--out", "Song (fixed).als"]))
        self.assertTrue(CH.needs_ok("edges", ["Song.als", "--apply", "Song (edges).als", "--ids", "edges-1"]))
        self.assertTrue(CH.needs_ok("automation", ["offset", "a.als", "--out", "b.als"]))

    def test_openai_compatible_loop_and_a_declined_write(self):
        n = {"i": 0}

        class Fake:
            def __init__(self, **k):
                self.chat = types.SimpleNamespace(completions=self)

            def create(self, model, tools, messages):
                n["i"] += 1
                call = lambda i, name, a: types.SimpleNamespace(id=i, function=types.SimpleNamespace(name=name, arguments=json.dumps(a)))
                if n["i"] == 1:
                    m = types.SimpleNamespace(content="Looking.", tool_calls=[call("c1", "list_songs", {})])
                elif n["i"] == 2:
                    assert messages[-1] == {"role": "tool", "tool_call_id": "c1", "content": "[]"}
                    m = types.SimpleNamespace(content=None, tool_calls=[call("c2", "run_hypnomix",
                                              {"command": "tidy", "args": ["a.als", "--apply", "b.als"]})])
                else:
                    assert "chose not to run" in messages[-1]["content"]
                    m = types.SimpleNamespace(content="Nothing changed.", tool_calls=None)
                return types.SimpleNamespace(choices=[types.SimpleNamespace(message=m)])

        CH.update_settings({"provider": "ollama", "model": "m"})
        with mock.patch("openai.OpenAI", Fake):
            CH.send("tidy my song")
            for _ in range(100):
                if CH.state()["pending"]:
                    break
                time.sleep(0.05)
            pend = CH.state()["pending"]
            self.assertEqual(pend["command"], "tidy")
            CH.answer(pend["id"], False)
            wait_idle()
        kinds = [(i["kind"], i.get("answer")) for i in CH.state()["items"]]
        self.assertIn(("ask", "declined"), kinds)
        self.assertEqual(CH.state()["items"][-1]["text"], "Nothing changed.")

    def test_claude_loop_with_fallbacks_and_cached_system(self):
        n = {"i": 0}
        use = lambda i, cw, cr, o: types.SimpleNamespace(input_tokens=i, cache_creation_input_tokens=cw,
                                                         cache_read_input_tokens=cr, output_tokens=o)

        class Msgs:
            def create(self, **p):
                n["i"] += 1
                assert p["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
                assert p["cache_control"] == {"type": "ephemeral", "ttl": "1h"}     # the whole conversation cached
                assert all(t["strict"] for t in p["tools"])
                if n["i"] == 1:
                    assert p["fallbacks"] == "default" and p["betas"] == ["server-side-fallback-2026-07-01"]
                    return types.SimpleNamespace(stop_reason="tool_use", usage=use(8000, 0, 0, 200), content=[
                        Blk(type="text", text="Checking."), Blk(type="tool_use", id="t1", name="list_songs", input={})])
                res = p["messages"][-1]["content"][0]
                assert res["type"] == "tool_result" and res["tool_use_id"] == "t1"
                return types.SimpleNamespace(stop_reason="end_turn", usage=use(50, 1000, 8000, 100),
                                             content=[Blk(type="text", text="No songs yet.")])

        class Fake:
            def __init__(self, **k):
                self.messages = Msgs()
                self.beta = types.SimpleNamespace(messages=Msgs())

        CH.update_settings({"provider": "anthropic", "key": "sk-test-0000"})
        with mock.patch("anthropic.Anthropic", Fake):
            CH.send("what songs do I have?")
            wait_idle()
        self.assertEqual([i["text"] for i in CH.state()["items"] if i["kind"] == "assistant"], ["Checking.", "No songs yet."])
        u = CH.state()["usage"]
        self.assertEqual((u["calls"], u["input"], u["cache_write"], u["cache_read"], u["output"]), (2, 8050, 1000, 8000, 300))
        # Opus 5.5: $4 in, $20 out, $0.20 cache read, 1 h cache write at 2x input
        self.assertAlmostEqual(u["cost"], (8050 * 4 + 1000 * 8 + 8000 * 0.2 + 300 * 20) / 1e6)

    def test_review_comes_in_pages_never_cut_off(self):
        fs = [dict(id=f"edges-{i}", tool="edges" if i % 2 else "smooth", track="Vox", problem="p" * 900, fix="f")
              for i in range(1, 101)]
        with mock.patch("hypnomix.app.server.scan_dir", lambda d: Path(d)), \
                mock.patch("hypnomix.app.server.review_payload", lambda d: {"findings": fs, "decisions": {"edges-1": "approve"}}):
            p1 = json.loads(CH.tool("read_review", {"dir": "/x", "page": 1, "tool": ""}))
            p3 = json.loads(CH.tool("read_review", {"dir": "/x", "page": 3, "tool": ""}))
            e2 = json.loads(CH.tool("read_review", {"dir": "/x", "page": 2, "tool": "edges"}))
        self.assertEqual((p1["total"], len(p1["findings"]), p1["shown"]), (100, CH.REVIEW_PAGE, "all: page 1 of 3"))
        self.assertEqual(len(p3["findings"]), 100 - 2 * CH.REVIEW_PAGE)                  # nothing lost at the end
        self.assertEqual(p1["per_tool"], {"edges": 50, "smooth": 50})
        self.assertEqual(p1["findings"][0]["decision"], "approve")
        self.assertTrue(p1["findings"][0]["problem"].endswith("…"))
        self.assertEqual({f["id"] for f in e2["findings"]}, {f"edges-{i}" for i in range(81, 101, 2)})

    def test_a_refused_key_is_said_plainly(self):
        e = type("AuthenticationError", (Exception,), {})("401")
        self.assertIn("refused the key", CH._friendly(e, "OpenAI"))

    def test_reports_only_from_the_songs_folder(self):
        self.assertIn("only text reports", CH.tool("read_file", {"path": "/etc/passwd"}))
        f = Path(self.d.name) / "REVIEW.md"
        f.write_text("hello")
        self.assertEqual(CH.tool("read_file", {"path": str(f)}), "hello")


if __name__ == "__main__":
    unittest.main()
