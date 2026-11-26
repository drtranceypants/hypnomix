"""Bug-hunt fixes in the Assistant (chat.py, chat.js, prices.py and its Setup side): every tool call gets a result, a
damaged conversation is mended before it is sent, Stop is heard while the model answers, the cost line is worded for the
right provider, the Gemini price follows its dates. Stand-in clients only: no model is ever called."""
import copy, datetime, json, os, subprocess, sys, tempfile, threading, time, types, unittest
from pathlib import Path
from unittest import mock

from hypnomix.app import chat as CH
from hypnomix.core import prices as P

REPO = Path(__file__).resolve().parents[1]


def wait_idle(timeout=10):
    t = time.time()
    while CH.state()["busy"] and time.time() - t < timeout:
        time.sleep(0.02)


class Blk(dict):
    __getattr__ = dict.__getitem__

    def model_dump(self, **k):
        return dict(self)


# ---------------------------------------------------------------- stand-in providers that refuse what the real ones refuse
def check_claude(messages):
    """Anthropic's documented rules: every tool_use is answered by a tool_result in the NEXT user message, and no message
    before the last is empty."""
    for i, m in enumerate(messages):
        c = m["content"]
        if not c and not (i == len(messages) - 1 and m["role"] == "assistant"):
            raise Exception(f"400 invalid_request_error: messages.{i}: all messages must have non-empty content except the optional final assistant message")
        if isinstance(c, list):
            for b in c:
                if b.get("type") == "text" and not b.get("text", "").strip():
                    raise Exception(f"400 invalid_request_error: messages.{i}: text content blocks must contain non-whitespace text")
        if m["role"] == "assistant" and isinstance(c, list):
            ids = [b["id"] for b in c if b.get("type") == "tool_use"]
            if ids:
                nxt = messages[i + 1]["content"] if i + 1 < len(messages) and messages[i + 1]["role"] == "user" else []
                got = [b["tool_use_id"] for b in nxt if isinstance(nxt, list) and b.get("type") == "tool_result"]
                if sorted(got) != sorted(ids):
                    raise Exception(f"400 invalid_request_error: tool_use ids {ids} without tool_result blocks immediately after (got {got})")


def check_openai(messages):
    for i, m in enumerate(messages):
        if m["role"] == "assistant" and m.get("tool_calls"):
            ids = [tc["id"] for tc in m["tool_calls"]]
            got = []
            for x in messages[i + 1:]:
                if x["role"] != "tool":
                    break
                got.append(x["tool_call_id"])
            if sorted(got) != sorted(ids):
                raise Exception(f"400 tool_calls {ids} must be followed by tool messages (got {got})")
        if m["role"] == "tool" and not (messages[i - 1]["role"] == "tool" or messages[i - 1].get("tool_calls")):
            raise Exception("400 a tool message must follow an assistant message with tool_calls")


def claude_fake(steps, seen=None):
    """steps(i, messages) -> a response (i counts from 1). Every request is checked against Anthropic's rules first."""
    seen = [] if seen is None else seen

    class Msgs:
        def create(self, **p):
            msgs = copy.deepcopy(p["messages"])
            check_claude(msgs)
            seen.append(msgs)
            return steps(len(seen), msgs)

    class Fake:
        def __init__(self, **k):
            self.messages = Msgs()
            self.beta = types.SimpleNamespace(messages=Msgs())
    return Fake, seen


def cresp(stop, content, **extra):
    use = types.SimpleNamespace(input_tokens=100, cache_creation_input_tokens=0, cache_read_input_tokens=0, output_tokens=10)
    return types.SimpleNamespace(stop_reason=stop, usage=use, content=content, **extra)


def oresp(content=None, calls=None, finish="stop", tokens=100):
    m = types.SimpleNamespace(content=content, tool_calls=calls or None)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=m, finish_reason=finish)], usage=types.SimpleNamespace(
        prompt_tokens=tokens, completion_tokens=10, prompt_tokens_details=None))


def ocall(i, name, args):
    return types.SimpleNamespace(id=i, function=types.SimpleNamespace(name=name, arguments=json.dumps(args)))


def openai_fake(steps, seen=None):
    seen = [] if seen is None else seen

    class Fake:
        def __init__(self, **k):
            self.chat = types.SimpleNamespace(completions=self)

        def create(self, model, tools, messages):
            msgs = copy.deepcopy(messages[1:])                 # without the system prompt
            check_openai(msgs)
            seen.append(msgs)
            return steps(len(seen), msgs)
    return Fake, seen


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.work = Path(self.d.name) / "work"
        self.p = [mock.patch.object(CH, "CONF", Path(self.d.name) / "ai.json"),
                  mock.patch.dict(os.environ, {"HYPNOMIX_APP_HOME": str(self.work)})]
        for p in self.p:
            p.start()
        CH.CHAT.update(items=[], history=[], provider=None, busy=False, pending=None, stop=False, usage=CH.new_usage(),
                       msg={}, elided_at=0, error="", engine_mark=None)

    def tearDown(self):
        CH.stop()
        wait_idle(5)
        for p in self.p:
            p.stop()
        self.d.cleanup()

    def notes(self):
        return [i["text"] for i in CH.state()["items"] if i["kind"] in ("note", "error")]

    def errors(self):
        return [i["text"] for i in CH.state()["items"] if i["kind"] == "error"]

    def converse(self, text):
        CH.send(text)
        wait_idle()


# ================================================================ a call is always answered
class EveryCallIsAnswered(Base):
    def test_a_tool_that_raises_still_gets_a_result_and_the_conversation_goes_on(self):
        CH.update_settings({"provider": "ollama", "model": "m"})
        steps = lambda i, msgs: (oresp(calls=[ocall("c1", "read_file", {"path": 5})]) if i == 1 else oresp("fine."))
        Fake, seen = openai_fake(steps)
        with mock.patch("openai.OpenAI", Fake):
            self.converse("read it")
            self.assertEqual(self.errors(), [])
            self.converse("hello again")                       # the stand-in refuses a history with an unanswered call
        self.assertEqual(self.errors(), [])
        tool_msg = [m for m in seen[1] if m["role"] == "tool"][0]
        self.assertEqual(tool_msg["tool_call_id"], "c1")
        self.assertTrue(tool_msg["content"].startswith("error:"), tool_msg["content"])

    def test_claude_two_calls_one_raising_both_answered(self):
        CH.update_settings({"provider": "anthropic", "key": "sk-test-0000"})
        steps = lambda i, msgs: (cresp("tool_use", [Blk(type="tool_use", id="t1", name="read_review", input={"dir": ["a"]}),
                                                    Blk(type="tool_use", id="t2", name="list_songs", input={})])
                                 if i == 1 else cresp("end_turn", [Blk(type="text", text="ok")]))
        Fake, seen = claude_fake(steps)
        with mock.patch("anthropic.Anthropic", Fake), mock.patch("hypnomix.app.server.scans", lambda: []):
            self.converse("review")
            self.converse("again")
        self.assertEqual(self.errors(), [])
        res = {b["tool_use_id"]: b["content"] for b in seen[1][2]["content"]}
        self.assertEqual(sorted(res), ["t1", "t2"])
        self.assertTrue(res["t1"].startswith("error:"))

    def test_each_tool_answers_in_words_when_its_arguments_are_the_wrong_type(self):
        for name, inp in (("read_file", {"path": 5}), ("read_file", {"path": ["a"], "offset": "x"}),
                          ("show_in_live", {"dir": 5, "id": "x"}), ("read_review", {"dir": ["a"]}),
                          ("run_hypnomix", {"command": "measure", "args": 5}), ("run_hypnomix", {"command": ["x"]}),
                          ("listen", {"audio": 5}), ("nope", {})):
            out = CH.tool(name, inp)
            self.assertIsInstance(out, str, (name, inp))
            self.assertTrue(out, (name, inp))
        self.assertTrue(CH.tool("read_file", {"path": 5}).startswith("error:"))
        self.assertTrue(CH.tool("read_file", [1]).startswith("error:"))                    # not even an object
        for odd in ({"command": "x", "args": 5}, {"command": "x", "args": "abc"}, {"dir": ["a"]}, None, [1]):
            for name in ("run_hypnomix", "read_review", "daw_x"):
                self.assertIsInstance(CH._label(name, odd), str)                            # the chat line never raises

    def test_a_reply_cut_off_in_a_tool_call_is_answered_not_run_and_the_chat_goes_on(self):
        CH.update_settings({"provider": "anthropic", "key": "sk-test-0000"})
        ran = []
        steps = lambda i, msgs: (cresp("max_tokens", [Blk(type="text", text="Running"), Blk(type="tool_use", id="t1", name="run_hypnomix",
                                                                                           input={"command": "scan", "args": ["/s"]})])
                                 if i == 1 else cresp("end_turn", [Blk(type="text", text="Carrying on.")]))
        Fake, seen = claude_fake(steps)
        with mock.patch("anthropic.Anthropic", Fake), mock.patch.object(CH, "tool", lambda n, i: ran.append(n) or "x"):
            self.converse("scan it")
            self.assertTrue(any("cut off" in n for n in self.notes()))
            self.converse("continue")                         # what the note tells the person to do
        self.assertEqual((ran, self.errors()), ([], []))
        self.assertEqual(CH.state()["items"][-1]["text"], "Carrying on.")
        res = seen[1][2]["content"][0]
        self.assertEqual((res["tool_use_id"], res.get("is_error")), ("t1", True))

    def test_an_openai_reply_cut_off_in_its_calls_is_answered_too(self):
        CH.update_settings({"provider": "ollama", "model": "m"})
        ran = []
        steps = lambda i, msgs: (oresp("part", [ocall("c1", "list_songs", {})], finish="length") if i == 1 else oresp("ok"))
        Fake, seen = openai_fake(steps)
        with mock.patch("openai.OpenAI", Fake), mock.patch.object(CH, "tool", lambda n, i: ran.append(n) or "x"):
            self.converse("go")
            self.converse("continue")
        self.assertEqual((ran, self.errors()), ([], []))

    def test_three_identical_calls_in_one_step_are_one_call_not_a_loop(self):
        CH.update_settings({"provider": "anthropic", "key": "sk-test-0000"})
        ran = []
        three = [Blk(type="tool_use", id=f"t{k}", name="list_songs", input={}) for k in range(3)]
        steps = lambda i, msgs: cresp("tool_use", three) if i == 1 else cresp("end_turn", [Blk(type="text", text="three songs")])
        Fake, seen = claude_fake(steps)
        with mock.patch("anthropic.Anthropic", Fake), mock.patch.object(CH, "tool", lambda n, i: ran.append(n) or "[songs]"):
            self.converse("list")
        self.assertEqual(len(seen), 2)                                   # the model got to answer
        self.assertEqual(ran, ["list_songs"])                            # the same call once
        self.assertEqual([b["content"] for b in seen[1][2]["content"]], ["[songs]"] * 3)
        self.assertFalse(any("going round in circles" in n for n in self.notes()))
        self.assertEqual(CH.state()["items"][-1]["text"], "three songs")

    def test_the_same_call_over_several_steps_still_stops(self):
        CH.update_settings({"provider": "ollama", "model": "m"})
        steps = lambda i, msgs: oresp(calls=[ocall(f"c{i}", "list_songs", {}), ocall(f"d{i}", "list_songs", {})])
        Fake, seen = openai_fake(steps)
        with mock.patch("openai.OpenAI", Fake), mock.patch.object(CH, "tool", lambda n, i: "[]"):
            self.converse("go")
        self.assertEqual(len(seen), 3)
        self.assertTrue(any("same arguments 3 times in a row" in n for n in self.notes()))

    def test_args_given_as_one_string_are_refused_not_split_into_letters(self):
        with mock.patch.object(CH, "run_cli") as run, mock.patch.object(CH, "ask_ok") as ask:
            out = CH.tool("run_hypnomix", {"command": "measure", "args": "/songs/Mix.wav"})
            self.assertIn("args must be a list", out)
            run.assert_not_called()
            ask.assert_not_called()
            self.assertIn("args must be a list", CH.tool("run_hypnomix", {"command": "scan", "args": {"a": 1}}))
        with mock.patch.object(CH, "run_cli", return_value="[done]") as run:                  # no args at all is fine
            CH.tool("run_hypnomix", {"command": "doctor"})
            CH.tool("run_hypnomix", {"command": "doctor", "args": None})
        self.assertEqual(run.call_count, 2)
        self.assertEqual(CH._label("run_hypnomix", {"command": "measure", "args": "/s/Mix.wav"}), "hypnomix measure /s/Mix.wav")


# ================================================================ empty replies are never stored
class EmptyReplies(Base):
    def test_a_refusal_with_no_content_is_not_stored_as_an_empty_message(self):
        CH.update_settings({"provider": "anthropic", "key": "sk-test-0000"})
        steps = lambda i, msgs: cresp("refusal", []) if i == 1 else cresp("end_turn", [Blk(type="text", text="ok")])
        Fake, seen = claude_fake(steps)
        with mock.patch("anthropic.Anthropic", Fake):
            self.converse("something")
            self.assertIn("The model declined this request.", self.notes())
            self.assertTrue(all(m["content"] for m in CH.CHAT["history"]))
            self.converse("something else")
        self.assertEqual(self.errors(), [])

    def test_an_empty_end_turn_after_a_tool_result_is_said_and_not_stored(self):
        CH.update_settings({"provider": "anthropic", "key": "sk-test-0000"})
        steps = lambda i, msgs: {1: cresp("tool_use", [Blk(type="tool_use", id="t1", name="list_songs", input={})]),
                                 2: cresp("end_turn", [])}.get(i) or cresp("end_turn", [Blk(type="text", text="ok")])
        Fake, seen = claude_fake(steps)
        with mock.patch("anthropic.Anthropic", Fake), mock.patch.object(CH, "tool", return_value="[]"):
            self.converse("list")
            self.assertTrue(any("empty reply" in n for n in self.notes()), self.notes())
            self.converse("again")
        self.assertEqual(self.errors(), [])

    def test_a_blank_text_block_is_not_kept(self):
        CH.update_settings({"provider": "anthropic", "key": "sk-test-0000"})
        steps = lambda i, msgs: (cresp("tool_use", [Blk(type="text", text="  "), Blk(type="tool_use", id="t1", name="list_songs", input={})])
                                 if i == 1 else cresp("end_turn", [Blk(type="text", text="ok")]))
        Fake, seen = claude_fake(steps)
        with mock.patch("anthropic.Anthropic", Fake), mock.patch.object(CH, "tool", return_value="[]"):
            self.converse("list")
        self.assertEqual(self.errors(), [])
        self.assertEqual([b["type"] for b in CH.CHAT["history"][1]["content"]], ["tool_use"])

    def test_an_openai_reply_with_nothing_in_it_is_not_stored(self):
        CH.update_settings({"provider": "ollama", "model": "m"})
        Fake, seen = openai_fake(lambda i, msgs: oresp(None))
        with mock.patch("openai.OpenAI", Fake):
            self.converse("hi")
        self.assertEqual([m["role"] for m in CH.CHAT["history"]], ["user"])
        self.assertTrue(any("empty reply" in n for n in self.notes()))


# ================================================================ a damaged history is mended, not sent
class RepairedHistory(Base):
    CALL = {"role": "assistant", "content": [{"type": "text", "text": "x"}, {"type": "tool_use", "id": "t1", "name": "list_songs", "input": {}}]}

    def test_claude_format(self):
        h = [{"role": "user", "content": "hi"}, self.CALL, {"role": "user", "content": "and then?"}]
        new, n = CH.repair_history(h)
        check_claude(new)
        self.assertEqual(n, 1)
        self.assertEqual([b["type"] for b in new[2]["content"]], ["tool_result", "text"])     # results first, the person's words kept
        self.assertTrue(new[2]["content"][0]["is_error"])
        # nothing after the call at all
        new, n = CH.repair_history(h[:2])
        check_claude(new)
        self.assertEqual((n, new[-1]["role"]), (1, "user"))
        # a complete history is left exactly as it is, and an answer to no call is dropped
        ok = [h[0], self.CALL, {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "[]"}]},
              {"role": "assistant", "content": [{"type": "text", "text": "done"}]}]
        self.assertEqual(CH.repair_history(ok), (ok, 0))
        stray = ok + [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "zz", "content": "?"}]}]
        new, n = CH.repair_history(stray)
        self.assertEqual((new, n), (ok, 1))

    def test_openai_format(self):
        call = {"role": "assistant", "content": "", "tool_calls": [{"id": "a", "type": "function", "function": {"name": "x", "arguments": "{}"}},
                                                                     {"id": "b", "type": "function", "function": {"name": "x", "arguments": "{}"}}]}
        h = [{"role": "user", "content": "hi"}, call, {"role": "tool", "tool_call_id": "b", "content": "[]"},
             {"role": "tool", "tool_call_id": "ghost", "content": "?"}, {"role": "user", "content": "next"}]
        new, n = CH.repair_history(h)
        check_openai(new)
        self.assertEqual(n, 2)
        self.assertEqual(sorted(m["tool_call_id"] for m in new if m["role"] == "tool"), ["a", "b"])
        self.assertEqual(new[-1], {"role": "user", "content": "next"})

    def test_empty_and_odd_entries_are_dropped(self):
        h = ["junk", None, {"role": "assistant", "content": []}, {"role": "assistant", "content": ""}, {"role": "user", "content": "hi"},
             {"role": "assistant", "content": [{"type": "text", "text": " "}]}, {"role": "system", "content": "x"},
             {"role": "assistant", "content": "hello"}]
        new, n = CH.repair_history(h)
        self.assertEqual(new, [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}])
        self.assertGreaterEqual(n, 6)

    def test_a_conversation_saved_in_the_middle_of_a_turn_is_mended_on_load(self):
        conv = self.work / "assistant" / "conversation.json"
        conv.parent.mkdir(parents=True)
        conv.write_text(json.dumps(dict(id="abc", provider="anthropic", items=[
            {"kind": "user", "text": "tidy"}, {"kind": "ask", "id": "q", "what": "write", "text": "hypnomix tidy"}],
            history=[{"role": "user", "content": "tidy"}, self.CALL],
            usage={"calls": 1, "input": 5})))
        CH._load()
        check_claude(CH.CHAT["history"])
        self.assertEqual(CH.CHAT["history"][-1]["role"], "user")
        self.assertEqual([i for i in CH.CHAT["items"] if i["kind"] == "ask"][0]["answer"], "expired")      # nobody can answer it now
        self.assertTrue(any("interrupted" in n for n in self.notes()))
        self.assertEqual(CH.CHAT["usage"]["calls"], 1)
        self.assertEqual(CH.CHAT["usage"]["listen_cost"], 0.0)                                  # an older file lacks the newer counters

    def test_a_turn_that_ends_with_a_call_unanswered_is_closed_before_it_is_saved(self):
        CH.update_settings({"provider": "ollama", "model": "m"})
        Fake, seen = openai_fake(lambda i, msgs: oresp(calls=[ocall("c1", "list_songs", {})]))
        with mock.patch("openai.OpenAI", Fake), mock.patch.object(CH, "say", side_effect=[None, None, RuntimeError("boom")] + [None] * 9):
            self.converse("go")                                             # the chat line for the tool fails: the turn dies mid-step
        check_openai(CH.CHAT["history"])
        check_openai(json.loads((self.work / "assistant" / "conversation.json").read_text())["history"])


# ================================================================ a conversation file of the wrong shape
class BadConversationFile(Base):
    def conv(self, text):
        f = self.work / "assistant" / "conversation.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        return f

    def test_each_wrong_shape_starts_an_empty_chat_and_keeps_the_file_aside(self):
        for text in ("null", "5", '"s"', "[1]", '{"items": {"a": 1}}', '{"history": "x"}', "{broken"):
            CH.CHAT.update(items=[], history=[], usage=CH.new_usage(), provider=None)
            f = self.conv(text)
            CH._load()
            self.assertFalse(f.exists(), text)
            self.assertTrue(any(p.name.startswith("conversation.json.bad") for p in f.parent.iterdir()), text)
            CH.state()                                                       # does not raise
            self.assertTrue(any("could not be read" in n for n in self.notes()), text)
        bads = sorted(p.name for p in f.parent.iterdir() if ".bad" in p.name)
        self.assertEqual(len(bads), 7)                                       # none of them overwritten by the next

    def test_a_usage_that_is_null_or_wrong_is_replaced_and_a_valid_file_loads(self):
        self.conv(json.dumps(dict(id="x1", items=[{"kind": "user", "text": "hi"}, "junk"], history=[{"role": "user", "content": "hi"}, 7],
                                  usage=None)))
        CH._load()
        self.assertEqual((CH.CHAT["id"], len(CH.CHAT["items"]), len(CH.CHAT["history"])), ("x1", 1, 1))
        self.assertEqual(CH.state()["usage"]["calls"], 0)
        self.conv(json.dumps(dict(usage={"calls": "many", "cost": 1.5, "priced": False, "bogus": 1})))
        CH._load()
        self.assertEqual((CH.CHAT["usage"]["calls"], CH.CHAT["usage"]["cost"], CH.CHAT["usage"]["priced"]), (0, 1.5, False))

    def test_importing_chat_with_a_null_file_does_not_crash(self):
        self.conv("null")
        env = dict(os.environ, HYPNOMIX_APP_HOME=str(self.work), HYPNOMIX_HOME=str(Path(self.d.name) / "h"),
                   HOME=str(Path(self.d.name) / "fk"))
        r = subprocess.run([sys.executable, "-c", "from hypnomix.app import chat; print(chat.state()['total'])"], cwd=REPO, env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "1")                              # the note that it started empty


# ================================================================ saved as it goes
class SavedAsItGoes(Base):
    def test_the_message_and_the_waiting_card_are_on_disk_before_the_turn_ends(self):
        CH.update_settings({"provider": "ollama", "model": "m"})
        conv = self.work / "assistant" / "conversation.json"
        steps = lambda i, msgs: oresp(calls=[ocall("c1", "run_hypnomix", {"command": "tidy", "args": ["a.als", "--apply", "b.als"]})]) if i == 1 else oresp("ok")
        Fake, seen = openai_fake(steps)
        with mock.patch("openai.OpenAI", Fake):
            CH.send("tidy my song")
            saved = json.loads(conv.read_text())                            # at once: just the person's words
            self.assertEqual([m["content"] for m in saved["history"]], ["tidy my song"])
            for _ in range(200):
                if CH.state()["pending"]:
                    break
                time.sleep(0.02)
            self.assertTrue(CH.state()["pending"])
            for _ in range(200):                                            # the card shows first, the save follows at once
                saved = json.loads(conv.read_text())                        # the card is waiting: it is kept with its call
                if any(i.get("kind") == "ask" for i in saved["items"]):
                    break
                time.sleep(0.02)
            self.assertTrue(any(i.get("kind") == "ask" for i in saved["items"]))
            self.assertEqual(len(saved["history"]), 2)
            CH.answer(CH.state()["pending"]["id"], False)
            wait_idle()
        self.assertEqual(len(json.loads(conv.read_text())["history"]), 4)


# ================================================================ Stop is heard while the model answers
class StopWhileAnswering(Base):
    def _run(self, kind):
        gate, entered = threading.Event(), threading.Event()
        if kind == "openai":
            CH.update_settings({"provider": "ollama", "model": "m"})

            class Fake:
                def __init__(self, **k):
                    self.chat = types.SimpleNamespace(completions=self)

                def create(self, model, tools, messages):
                    entered.set()
                    gate.wait(15)
                    return oresp("LATE ANSWER")
            target = "openai.OpenAI"
        else:
            CH.update_settings({"provider": "anthropic", "key": "sk-test-0000"})

            class Msgs:
                def create(self, **p):
                    entered.set()
                    gate.wait(15)
                    return cresp("end_turn", [Blk(type="text", text="LATE ANSWER")])

            class Fake:
                def __init__(self, **k):
                    self.messages = Msgs()
                    self.beta = types.SimpleNamespace(messages=Msgs())
            target = "anthropic.Anthropic"
        try:
            with mock.patch(target, Fake):
                CH.send("hello")
                self.assertTrue(entered.wait(5))
                t = time.time()
                CH.stop()
                wait_idle(3)
                self.assertFalse(CH.state()["busy"], "Stop did nothing while the model was answering")
                self.assertLess(time.time() - t, 2)
                CH.reset()                                                   # no longer refused
                gate.set()                                                   # the model answers at last
                time.sleep(0.5)
            self.assertEqual([i["text"] for i in CH.state()["items"] if i["kind"] == "assistant"], [])
            self.assertEqual(CH.CHAT["history"], [])
        finally:
            gate.set()

    def test_openai_format(self):
        self._run("openai")

    def test_claude(self):
        self._run("claude")

    def test_the_stopped_chat_says_so_and_the_late_answer_is_not_used(self):
        gate, entered = threading.Event(), threading.Event()
        CH.update_settings({"provider": "ollama", "model": "m"})

        class Fake:
            def __init__(self, **k):
                self.chat = types.SimpleNamespace(completions=self)

            def create(self, model, tools, messages):
                entered.set()
                gate.wait(15)
                return oresp("LATE")
        try:
            with mock.patch("openai.OpenAI", Fake):
                CH.send("hello")
                entered.wait(5)
                CH.stop()
                wait_idle(3)
                gate.set()
                time.sleep(0.4)
            self.assertTrue(any(n.startswith("Stopped") for n in self.notes()))
            self.assertEqual([m["role"] for m in CH.CHAT["history"]], ["user"])
        finally:
            gate.set()

    def test_the_stop_button_shows_that_it_is_stopping(self):
        js = (REPO / "hypnomix/app/chat.js").read_text()
        self.assertIn("Stopping…", js)


# ================================================================ results the model has not read are never cleared
class FreshResults(Base):
    def test_a_step_with_more_than_six_results_keeps_all_of_them(self):
        big = lambda n: CH.data("z" * n)
        h = [{"role": "user", "content": "go"}]
        for k in range(2):                                               # two older steps, one call each
            h.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"o{k}", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": f"/s/{k}.txt"})}}]})
            h.append({"role": "tool", "tool_call_id": f"o{k}", "content": big(5000)})
        h.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"n{k}", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": f"/s/n{k}.txt"})}} for k in range(8)]})
        h.extend({"role": "tool", "tool_call_id": f"n{k}", "content": big(5000)} for k in range(8))
        self.assertEqual(CH.elide_results(h), 2)                           # only the two older ones
        self.assertTrue(all(not m["content"].startswith(CH.STUB) for m in h[-8:]))
        self.assertTrue(h[2]["content"].startswith(CH.STUB))
        # Claude's format: eight results in one user message
        c = [{"role": "user", "content": "go"}, {"role": "assistant", "content": [{"type": "tool_use", "id": "old", "name": "read_file", "input": {"path": "/s/o.txt"}}]},
             {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "old", "content": big(5000)}]},
             {"role": "assistant", "content": [{"type": "tool_use", "id": f"n{k}", "name": "read_file", "input": {"path": f"/s/{k}"}} for k in range(8)]},
             {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"n{k}", "content": big(5000)} for k in range(8)]}]
        self.assertEqual(CH.elide_results(c), 1)
        self.assertTrue(all(not b["content"].startswith(CH.STUB) for b in c[-1]["content"]))
        # and once the model has read them, the next step clears the oldest as before
        c.append({"role": "assistant", "content": [{"type": "text", "text": "done"}]})
        self.assertEqual(CH.elide_results(c), 2)

    def test_the_request_that_carries_eight_fresh_results_has_none_cleared(self):
        CH.update_settings({"provider": "ollama", "model": "m"})
        calls = [ocall(f"c{k}", "read_file", {"path": f"/s/r{k}.txt"}) for k in range(8)]
        steps = lambda i, msgs: oresp(calls=calls) if i == 1 else oresp("read them")
        Fake, seen = openai_fake(steps)
        with mock.patch("openai.OpenAI", Fake), mock.patch.object(CH, "tool", lambda n, i: CH.data("q" * 5000)):
            self.converse("read them all")
        carried = [m for m in seen[1] if m["role"] == "tool"]
        self.assertEqual(len(carried), 8)
        self.assertTrue(all(not m["content"].startswith(CH.STUB) for m in carried))


class TidyIsSaidOncePerMessage(Base):
    def test_a_local_model_is_not_told_every_few_steps(self):
        CH.update_settings({"provider": "ollama", "model": "m"})
        CH.begin_message()
        big = lambda k: [{"role": "assistant", "content": "", "tool_calls": [{"id": f"c{k}", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": f"/s/{k}.txt"})}}]},
                         {"role": "tool", "tool_call_id": f"c{k}", "content": CH.data("z" * 3000)}]
        CH.CHAT["history"] = [{"role": "user", "content": "go"}]
        fired = 0
        for k in range(40):
            CH.CHAT["history"].extend(big(k))
            fired += 1 if CH.tidy("m", "ollama") else 0
        said = [n for n in self.notes() if n.startswith("Tidied")]
        self.assertGreater(fired, 2)                                       # the clearing still happens as often as it must
        self.assertEqual(len(said), 1)
        CH.begin_message()                                                 # the next message may say it once more
        CH.CHAT["history"].extend(big(99) + big(98) + big(97))
        CH.tidy("m", "ollama")
        CH.CHAT["history"].extend(big(96) * 1 + big(95) + big(94))
        CH.tidy("m", "ollama")
        self.assertLessEqual(len([n for n in self.notes() if n.startswith("Tidied")]), 2)


# ================================================================ the cost line
class CostLine(Base):
    def test_an_ollama_chat_with_a_paid_listen_is_not_called_free(self):
        u = CH.new_usage()
        u.update(calls=3, input=4000, output=300, listen_cost=0.236, listen_estimated=True)
        text = CH.cost_text(u, "ollama")
        self.assertTrue(text.startswith("free (on this computer), plus about $0.24 for listening"), text)
        self.assertIn("an estimate at Gemini", text)

    def test_the_gemini_wording_is_only_on_the_listening_part(self):
        u = CH.new_usage()
        u.update(calls=2, cost=1.5, listen_cost=0.24, listen_estimated=True)
        text = CH.cost_text(u, "anthropic")
        self.assertTrue(text.startswith("about $1.50, plus about $0.24 for listening"), text)
        self.assertEqual(text.count("Gemini"), 1)
        self.assertNotIn("Gemini", CH.cost_text(dict(u, listen_cost=0.0, listen_estimated=False), "anthropic"))
        self.assertIn("(an estimate at Gemini", CH.cost_text(dict(u, listen_cost=0.0, estimated=True), "gemini"))   # a Gemini chat
        self.assertEqual(CH.cost_text(dict(u, listen_cost=0.5), "anthropic").count("Gemini"), 1)
        self.assertIn("not reported", CH.cost_text(dict(u, listen_cost=0.0, listen_unpriced=True), "anthropic"))
        self.assertEqual(CH.cost_text(CH.new_usage(), "ollama"), "free (on this computer)")
        self.assertIn("price list", CH.cost_text(dict(CH.new_usage(), priced=False), "openai"))

    def test_the_state_words_it_by_the_conversations_provider_not_the_dropdown(self):
        CH.update_settings({"provider": "ollama", "model": "m"})
        CH.CHAT.update(provider="anthropic", usage=dict(CH.new_usage(), calls=1, cost=0.02))
        CH.update_settings({"provider": "ollama"})                           # the dropdown now says Ollama
        self.assertEqual(CH.state()["usage"]["cost_text"], "about $0.020")
        self.assertIn("cost_text", (REPO / "hypnomix/app/chat.js").read_text())

    def test_a_listen_adds_to_the_listening_cost_and_leaves_the_chats_alone(self):
        from hypnomix.ears import critique as L
        CH.update_settings({"provider": "anthropic", "key": "sk-test-0000", "listen_provider": "gemini", "listen_key": "AIza-test-0000"})
        song = Path(self.d.name) / "Mix.wav"
        song.write_bytes(b"x")
        est = dict(seconds=18, full_seconds=18, tokens_in=700, tokens_out=300, tokens=700, cost=0.01, basis="test")
        CH.CHAT["usage"] = dict(CH.new_usage(), calls=1, cost=1.0)
        with mock.patch.object(L, "estimate", return_value=est), mock.patch.object(L, "context", return_value=""), \
                mock.patch.dict(os.environ, {"GEMINI_API_KEY": "AIza-test-0000"}), \
                mock.patch.object(L, "cached", return_value=None), mock.patch.object(CH, "ask_ok", return_value=True), \
                mock.patch.object(L, "listen", return_value=("notes", {"input": 1_000_000, "output": 0, "cost": None})):
            CH.listen_tool({"audio": str(song), "question": "", "dir": ""})
        u = CH.CHAT["usage"]
        self.assertEqual((u["cost"], u["estimated"]), (1.0, False))
        self.assertTrue(u["listen_estimated"])
        self.assertAlmostEqual(u["listen_cost"], P.gemini_cost(1_000_000, 0))
        self.assertTrue(CH.state()["usage"]["cost_text"].startswith("about $1.00, plus about $"))

    def test_the_budget_question_says_what_listening_cost_too(self):
        CH.CHAT["usage"] = dict(CH.new_usage(), input=500_000, listen_cost=0.3, listen_estimated=True)
        CH.CHAT["msg"] = dict(read0=0, cost0=0.0, listen0=0.0, allow=100_000)
        asked = []
        with mock.patch.object(CH, "ask_ok", lambda c, a, text=None, **k: asked.append(text) or False):
            CH.budget_ok("ollama")
        self.assertIn("free, it runs on this computer, plus roughly $0.30 for listening, an estimate", asked[0])


# ================================================================ the listen card says where the file is
class ListenCard(Base):
    def test_the_card_shows_the_full_path_of_the_file_that_would_be_sent(self):
        from hypnomix.ears import critique as L
        CH.update_settings({"provider": "gemini", "key": "AIza-test-0000", "listen_provider": "gemini"})
        folder = Path(self.d.name) / "Voice Memos"
        folder.mkdir()
        real = folder / "take.wav"
        real.write_bytes(b"x")
        (Path(self.d.name) / "songs").mkdir()
        link = Path(self.d.name) / "songs" / "Mix.wav"
        link.symlink_to(real)
        est = dict(seconds=18, full_seconds=18, tokens_in=700, tokens_out=300, tokens=700, cost=0.01, basis="test")
        seen = []
        with mock.patch.object(L, "estimate", return_value=est), mock.patch.object(L, "context", return_value=""), \
                mock.patch.dict(os.environ, {"GEMINI_API_KEY": "AIza-test-0000"}), \
                mock.patch.object(L, "cached", return_value=None), \
                mock.patch.object(CH, "ask_ok", lambda c, a, text=None, **k: seen.append((a, text)) or False):
            CH.listen_tool({"audio": str(link), "question": "", "dir": ""})
        args, text = seen[0]
        self.assertEqual(args, [str(real.resolve())])
        self.assertTrue(text.startswith(str(real.resolve()) + ": "), text)


# ================================================================ the placeholder key is not a secret
class PlaceholderKey(Base):
    def setUp(self):
        super().setUp()
        CH.update_settings({"provider": "custom", "base_url": "http://127.0.0.1:1234/v1", "key": "lm-studio", "model": "m"})

    def test_the_persons_words_and_paths_are_left_alone(self):
        self.assertEqual(CH.scrub("what is lm-studio?"), "what is lm-studio?")
        self.assertEqual(CH.scrub("/Models/lm-studio-community/x"), "/Models/lm-studio-community/x")
        fake = Fake = None
        seen = []
        Fake, seen = openai_fake(lambda i, msgs: oresp("ok"))
        with mock.patch("openai.OpenAI", Fake):
            self.converse("what is lm-studio?")
        self.assertEqual(seen[0][0]["content"], "what is lm-studio?")
        self.assertEqual([i["text"] for i in CH.state()["items"] if i["kind"] == "user"], ["what is lm-studio?"])

    def test_the_click_card_shows_the_command_that_runs(self):
        args = ["/Models/lm-studio-community/Song.als", "--out", "/tmp/x"]
        with mock.patch.object(CH, "ask_ok", wraps=CH.ask_ok) as ask, mock.patch.object(CH, "run_cli", return_value="[done]"):
            t = threading.Thread(target=lambda: [time.sleep(0.1), CH.answer(CH.CHAT["pending"]["id"], True)])
            t.start()
            CH.tool("run_hypnomix", {"command": "scan", "args": args})
            t.join()
        card = [i for i in CH.CHAT["items"] if i["kind"] == "ask"][0]
        self.assertIn("/Models/lm-studio-community/Song.als", card["text"])

    def test_a_real_key_is_still_masked(self):
        CH.update_settings({"provider": "openai", "key": "sk-real-secret-12345678"})
        self.assertNotIn("secret", CH.scrub("my key is sk-real-secret-12345678"))


# ================================================================ LM Studio: an empty model name
class LocalModelName(Base):
    def _connect(self, body, models=("model-a", "model-b")):
        from hypnomix.app import setup as SU
        with mock.patch.object(CH, "list_models", return_value=list(models)):
            return SU.connect(body)

    def test_lm_studio_with_no_name_uses_the_first_model_it_lists_and_says_so(self):
        code, r = self._connect({"provider": "custom", "base_url": "http://localhost:1234/v1", "key": "lm-studio", "model": ""})
        self.assertEqual((code, r["ok"], r["count"], r["model"]), (200, True, 2, "model-a"))
        self.assertEqual(CH.active()[2], "model-a")
        Fake, seen = openai_fake(lambda i, msgs: oresp("hello"))
        with mock.patch("openai.OpenAI", Fake):
            self.converse("hi")                                             # used to refuse: "choose a model in the settings"
        self.assertEqual(self.errors(), [])
        view = {p["id"]: p for p in r["settings"]["providers"]}["custom"]
        self.assertEqual(view["model"], "model-a")

    def test_a_name_the_person_typed_is_kept_and_a_remote_address_is_not_guessed(self):
        code, r = self._connect({"provider": "custom", "base_url": "http://localhost:1234/v1", "key": "lm-studio", "model": "mine"})
        self.assertEqual((r["model"], CH.active()[2]), ("", "mine"))
        code, r = self._connect({"provider": "custom", "base_url": "https://models.example.com/v1", "key": "k-1234567", "model": ""})
        self.assertEqual((r["ok"], r["model"], CH.active()[2]), (True, "", ""))

    def test_the_label_matches_what_happens(self):
        js = (REPO / "hypnomix/app/setup.js").read_text()
        self.assertNotIn("empty = the loaded one", js)
        self.assertIn("empty = the first model it lists", js)


# ================================================================ the Gemini price follows its dates
class GeminiPriceDates(unittest.TestCase):
    def test_the_price_of_a_day_is_the_price_in_force_that_day(self):
        self.assertEqual(P.gemini_price("2026-12-31"), (0.75, 3.75))
        self.assertEqual(P.gemini_price("2027-01-01"), (1.5, 7.5))
        self.assertEqual(P.gemini_price(datetime.date(2027, 6, 1)), (1.5, 7.5))
        self.assertEqual(P.gemini_price(datetime.datetime(2026, 5, 1, 12, 0)), (0.75, 3.75))
        self.assertEqual(P.gemini_price("1999-01-01"), (0.75, 3.75))
        self.assertAlmostEqual(P.gemini_cost(1_000_000, 1_000_000, "2026-12-31"), 4.5)
        self.assertAlmostEqual(P.gemini_cost(1_000_000, 1_000_000, "2027-01-15"), 9.0)

    def test_the_table_is_ordered_and_its_note_says_the_same_dates(self):
        days = [r[0] for r in P.GEMINI_FROM]
        self.assertEqual(days, sorted(set(days)))
        self.assertIn("2026-12-31", P.GEMINI["note"])
        self.assertIn("$1.50 / $7.50 from 2027-01-01", P.GEMINI["note"])

    def test_everything_that_prices_gemini_uses_todays_price(self):
        from hypnomix.app import setup as SU
        CH.CHAT["usage"] = CH.new_usage()
        with mock.patch.object(P, "today", lambda: datetime.date(2027, 1, 15)):
            CH.count("gemini-flash-latest", "gemini", 1_000_000, 1_000_000)
            self.assertAlmostEqual(CH.CHAT["usage"]["cost"], 9.0)
            self.assertAlmostEqual(SU.song_cost("gemini-flash"), 1.2 * 1.5 + 0.02 * 7.5)
            self.assertEqual(SU.PRICES["gemini-flash"]["inp"], 1.5)
            self.assertEqual(SU.money(SU.song_cost("gemini-flash")), "about $1.95")
        with mock.patch.object(P, "today", lambda: datetime.date(2026, 12, 31)):
            self.assertEqual(SU.money(SU.song_cost("gemini-flash")), "about $0.97")
        CH.CHAT["usage"] = CH.new_usage()


# ================================================================ the fallback model that answered is the one priced
class FallbackCost(Base):
    def test_a_step_served_by_another_model_is_priced_as_that_model(self):
        CH.update_settings({"provider": "anthropic", "key": "sk-test-0000", "model": "claude-sonnet-5-5"})
        it = types.SimpleNamespace(type="fallback_message", model="claude-opus-5-5")
        use = types.SimpleNamespace(input_tokens=1_000_000, cache_creation_input_tokens=0, cache_read_input_tokens=0,
                                    output_tokens=0, iterations=[types.SimpleNamespace(type="message", model="claude-sonnet-5-5"), it])
        Fake, seen = claude_fake(lambda i, msgs: types.SimpleNamespace(stop_reason="end_turn", usage=use, content=[Blk(type="text", text="ok")]))
        with mock.patch("anthropic.Anthropic", Fake):
            self.converse("hi")
        self.assertAlmostEqual(CH.CHAT["usage"]["cost"], P.claude_cost("claude-opus-5-5", 1_000_000))
        self.assertTrue(any("claude-opus-5-5 answered" in n for n in self.notes()))

    def test_without_a_fallback_it_is_the_model_asked_for(self):
        r = types.SimpleNamespace(usage=types.SimpleNamespace(iterations=None), model="claude-sonnet-5-5")
        self.assertEqual(CH._served_model(r, "claude-sonnet-5-5"), "claude-sonnet-5-5")
        self.assertEqual(CH._served_model(types.SimpleNamespace(usage=types.SimpleNamespace()), "x"), "x")

    def test_a_dated_snapshot_of_the_model_asked_for_is_no_fallback_and_is_priced_as_asked(self):
        CH.update_settings({"provider": "anthropic", "key": "sk-test-0000", "model": "claude-haiku-4-5"})
        use = types.SimpleNamespace(input_tokens=1_000_000, cache_creation_input_tokens=0, cache_read_input_tokens=0,
                                    output_tokens=0, iterations=None)
        Fake, seen = claude_fake(lambda i, msgs: types.SimpleNamespace(
            stop_reason="end_turn", usage=use, content=[Blk(type="text", text="ok")], model="claude-haiku-4-5-20251001"))
        with mock.patch("anthropic.Anthropic", Fake):
            self.converse("hi")
        self.assertFalse(any("answered this step instead" in n for n in self.notes()))
        self.assertTrue(CH.state()["usage"]["priced"])
        self.assertAlmostEqual(CH.CHAT["usage"]["cost"], P.claude_cost("claude-haiku-4-5", 1_000_000))
        r = types.SimpleNamespace(usage=types.SimpleNamespace(iterations=None), model="claude-haiku-4-5-20251001")
        self.assertEqual(CH._served_model(r, "claude-haiku-4-5"), "claude-haiku-4-5")
        self.assertEqual(CH._served_model(types.SimpleNamespace(usage=None, model="claude-opus-5-5"), "claude-haiku-4-5"), "claude-opus-5-5")


class NotUtf8File(Base):
    def test_a_conversation_file_that_is_not_text_is_kept_aside_not_overwritten(self):
        f = self.work / "assistant" / "conversation.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"\xff\xfe\x00bad")
        CH._load()
        self.assertFalse(f.exists())
        self.assertEqual((f.parent / "conversation.json.bad").read_bytes(), b"\xff\xfe\x00bad")
        self.assertTrue(any("could not be read" in n for n in self.notes()))


class ResetAfterStop(Base):
    def test_a_new_conversation_is_not_refused_right_after_stop(self):
        gate, entered = threading.Event(), threading.Event()
        CH.update_settings({"provider": "ollama", "model": "m"})

        class Fake:
            def __init__(self, **k):
                self.chat = types.SimpleNamespace(completions=self)

            def create(self, model, tools, messages):
                entered.set()
                gate.wait(15)
                return oresp("LATE")
        try:
            with mock.patch("openai.OpenAI", Fake):
                CH.send("hello")
                self.assertTrue(entered.wait(5))
                CH.stop()
                CH.reset()                                                   # at once: waits for the turn to let go
                self.assertFalse(CH.state()["busy"])
                gate.set()
                time.sleep(0.3)
        finally:
            gate.set()

    def test_without_stop_a_busy_chat_still_refuses(self):
        CH.CHAT["busy"] = True
        try:
            with self.assertRaises(RuntimeError):
                CH.reset()
        finally:
            CH.CHAT["busy"] = False


# ================================================================ a missing library
class MissingLibrary(Base):
    def test_it_says_what_to_do(self):
        CH.update_settings({"provider": "anthropic", "key": "sk-test-0000"})
        with mock.patch.dict(sys.modules, {"anthropic": None}):
            self.converse("hi")
        text = self.errors()[0]
        self.assertIn("Setup, then Extras", text)
        self.assertIn(".[assistant]", text)
        self.assertNotIn("halted", text)
        self.assertIn("Setup, then Extras", CH._friendly(ModuleNotFoundError("No module named 'openai'"), "OpenAI"))
        for name in ("soundfile", "numpy.core", "google"):                   # another library is not the Assistant's
            text = CH._friendly(ModuleNotFoundError(f"No module named '{name}'", name=name), "Google Gemini")
            self.assertNotIn("Assistant's library", text, name)
            self.assertIn(name, text)
        self.assertNotIn("Assistant's library", CH._friendly(ImportError("cannot import name x"), "Google Gemini"))
        self.assertIn("Setup, then Extras", CH._friendly(ModuleNotFoundError("x", name="openai.types"), "OpenAI"))


if __name__ == "__main__":
    unittest.main()
