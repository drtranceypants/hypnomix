"""The command-line writers into the open HypnoMix engine (tidy / order / duck --engine --ids, loops / variations
--cues): each checks, before any write, that the engine has THIS session file open by its full path (a copy of the
same name in another folder, another session or an engine that names no file is refused: fails closed), that the
route ids and plug-in still are what the scan saw (duck), and engine and file errors end in one sentence."""
import io
import json
import shutil
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from hypnomix.engineer import duck_ardour as DA
from hypnomix.project import ardour_cues as AC
from hypnomix.project import ardour_groups as AG
from tests.test_ardour_groups import FakeEngine, Fixture


def duck_args(eng, ids="duck-1", **kw):
    return SimpleNamespace(**dict(dict(engine=eng.url, ids=ids, depth=3.0, names=None, json=None, apply=None), **kw))


class OpenSession(unittest.TestCase):
    def test_the_full_path_decides_and_it_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "A" / "Song" / "Song.ardour"
            b = Path(td) / "B" / "Song" / "Song.ardour"
            snaps = lambda f: dict(dirty=False, snapshots=[dict(name="x", file=str(f), current=True)])
            self.assertIsNone(AG.open_problem(snaps(a), a))
            same = AG.open_problem(snaps(b), a)
            self.assertIn(str(b.resolve()), same)                  # same name: the folders are told apart
            self.assertIn("nothing was written", same)
            self.assertIn("Other.ardour open, not Song.ardour", AG.open_problem(snaps(Path(td) / "Other.ardour"), a))
            for bad in ({}, None, [], dict(snapshots=[]), dict(snapshots=[dict(current=True)]),
                        dict(snapshots=[dict(file=str(a), current=False)]), dict(snapshots="x")):
                self.assertIn("could not tell which session", AG.open_problem(bad, a), bad)


class CliWriters(Fixture):
    def setUp(self):
        super().setUp()
        self.file = self.dir / "Song.ardour"
        self.eng = FakeEngine({t.name: t.route_id for t in self.p.tracks}, session=self.file)
        self.other = Path(self.td.name) / "copy" / "Song"
        self.other.mkdir(parents=True)
        shutil.copy(self.file, self.other / "Song.ardour")

    def tearDown(self):
        self.eng.close()
        super().tearDown()

    def writes(self):
        return [c for c in self.eng.calls if c[0].startswith(("group_create", "group_add", "group_set",
                                                               "plugin_add", "plugin_set"))]

    def refused(self, fn, *args):
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as e:
            fn(*args)
        self.assertEqual(self.writes(), [])
        return str(e.exception)

    def test_tidy_order_and_duck_refuse_another_session(self):
        cases = [("same name, other folder", self.other / "Song.ardour"),
                 ("other name", Path(self.td.name) / "Other" / "Other.ardour"), ("no file", None)]
        for what, open_file in cases:
            with self.subTest(what):
                self.eng.session = open_file
                for tool, plans in (("order", AG.plan_families), ("tidy", AG.plan_old_takes)):
                    msg = self.refused(AG.run_cli, tool, self.dir, SimpleNamespace(json=None, engine=self.eng.url,
                                                                                    ids="group-1"), plans)
                    self.assertIn("nothing was written", msg)
                msg = self.refused(DA.main, self.file, duck_args(self.eng))
                self.assertIn("nothing was written", msg)
                self.assertNotIn("\n", msg)

    def test_pointed_at_the_open_session_they_write(self):
        with redirect_stdout(io.StringIO()) as out:
            rc = AG.run_cli("order", self.dir, SimpleNamespace(json=None, engine=self.eng.url, ids="group-1"),
                            AG.plan_families)
        self.assertEqual(rc, 0, out.getvalue())
        self.assertIn("HypnoMix sees the change", out.getvalue())
        with redirect_stdout(io.StringIO()) as out:
            rc = DA.main(self.file, duck_args(self.eng))
        self.assertEqual(rc, 0, out.getvalue())
        self.assertTrue([c for c in self.eng.calls if c[0] == "plugin_add_by_plugin_id"])

    def test_an_id_that_is_not_an_option_is_refused_before_the_engine_is_asked(self):
        for tool, plans in (("order", AG.plan_families), ("tidy", lambda p: [])):
            msg = self.refused(AG.run_cli, tool, self.dir, SimpleNamespace(json=None, engine=self.eng.url,
                                                                            ids="group-9"), plans)
            self.assertIn("group-9 is not among the options listed", msg)
        msg = self.refused(DA.main, self.file, duck_args(self.eng, ids="duck-1,duck-7"))
        self.assertIn("duck-7 is not among the options listed (duck-1)", msg)
        self.assertNotIn("\n", msg)
        self.assertFalse([c for c in self.eng.calls if c[0] != "tools/list"], self.eng.calls)

    def test_an_unsaved_engine_is_said(self):
        self.eng.dirty = True
        with redirect_stdout(io.StringIO()) as out:
            rc = AG.run_cli("order", self.dir, SimpleNamespace(json=None, engine=self.eng.url, ids="group-1"),
                            AG.plan_families)
        self.assertEqual(rc, 0)
        self.assertIn("unsaved changes", out.getvalue())

    def test_duck_checks_route_ids_and_the_tuned_plug_in(self):
        self.eng.tracks = {("Room" if n == "Reverb" else n): i for n, i in self.eng.tracks.items()}
        with redirect_stdout(io.StringIO()) as out:
            rc = DA.main(self.file, duck_args(self.eng))
        self.assertEqual(rc, 1)
        self.assertIn("route 700 is 'Room' in the engine, not 'Reverb'", out.getvalue())
        self.assertEqual(self.writes(), [])
        tune = [dict(id="duck-1", track="Bass", ardour=dict(op="tune", ret_id="150", plugin_index=0, values={}))]
        self.eng.tracks = {"Bass": "150"}
        bad = DA.check_targets(AG.Engine(self.eng.url), tune, ["duck-1"])
        self.assertIn("is not the ACE Compressor", bad["duck-1"])
        ace = self.eng.answer
        self.eng.answer = lambda n, a: dict(ace(n, a), plugin=dict(index=0, name="ACE Compressor (stereo)",
                                                                   uniqueId="urn:ardour:a-comp#stereo")) \
            if n == "plugin_get_description" else ace(n, a)               # as the engine answers it
        self.assertEqual(DA.check_targets(AG.Engine(self.eng.url), tune, ["duck-1"]), {})

    def test_flags_a_daw_session_does_not_take(self):
        msg = self.refused(AG.run_cli, "tidy", self.dir, SimpleNamespace(json=None, engine=None, ids=None,
                                                                         apply="New.als"), AG.plan_old_takes)
        self.assertIn("not written to a new file", msg)
        msg = self.refused(AG.run_cli, "order", self.dir, SimpleNamespace(json=None, engine=None, ids="group-1"),
                           AG.plan_families)
        self.assertIn("--ids needs --engine", msg)
        msg = self.refused(DA.main, self.file, duck_args(self.eng, engine=None))
        self.assertIn("--ids needs --engine", msg)


class ErrorEngine:
    """Answers tools/list with the group and sidechain tools, and every tools/call with an engine error, or
    (html=True) every POST with a web page."""

    def __init__(self, html=False):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if html:
                    out = b"<html>hello</html>"
                elif body["method"] == "tools/list":
                    names = ["group_create", "group_add", "group_set", "group_list", "plugin_set_sidechain",
                             "plugin_get_sidechain", "cue_set_clip"]
                    out = json.dumps({"jsonrpc": "2.0", "id": body["id"],
                                      "result": {"tools": [{"name": n} for n in names]}}).encode()
                else:
                    out = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {
                        "isError": True, "content": [{"type": "text", "text": "engine busy"}]}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}/mcp"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class OneSentence(Fixture):
    def test_engine_errors_are_said_not_crashed(self):
        e = ErrorEngine()
        try:
            for run in (lambda: AG.run_cli("order", self.dir, SimpleNamespace(json=None, engine=e.url, ids="group-1"),
                                           AG.plan_families),
                        lambda: DA.main(self.dir / "Song.ardour", duck_args(e))):
                with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as x:
                    run()
                self.assertIn("engine busy", str(x.exception))
            # the open-session check passes, then the engine fails: "not done", exit 1, no traceback
            good = AG.Engine(e.url)
            with mock.patch.object(AG, "require_open", lambda eng, path: False), redirect_stdout(io.StringIO()) as out:
                rc = AG.run_cli("order", self.dir, SimpleNamespace(json=None, engine=e.url, ids="group-1"),
                                AG.plan_families)
            self.assertEqual(rc, 1)
            self.assertIn("not done: tracks_list: engine busy", out.getvalue())
            self.assertTrue(good.url)
        finally:
            e.close()

    def test_a_non_mcp_answer_is_said(self):
        e = ErrorEngine(html=True)
        try:
            with self.assertRaisesRegex(RuntimeError, "not an MCP reply"):
                AC.connect(e.url)
            with self.assertRaisesRegex(AG.EngineError, "not an MCP reply|did not answer"):
                AG.Engine(e.url).call("tracks_list")
        finally:
            e.close()

    def test_bad_names_files_are_one_sentence(self):
        d = Path(self.td.name)
        (d / "bad.json").write_text("{bad", encoding="utf-8")
        (d / "arr.json").write_text("[]", encoding="utf-8")
        (d / "rows.json").write_text(json.dumps({"tracks": [1, {"old": "Kick", "label": "kick"}]}), encoding="utf-8")
        for f in (d / "missing.json", d / "bad.json", d / "arr.json"):
            with self.assertRaises(SystemExit) as x:
                AG.labels_from(str(f))
            self.assertIn("--names expects", str(x.exception))
        self.assertEqual(list(AG.labels_from(str(d / "rows.json"))), ["Kick"])

    def test_a_cut_session_stops_with_the_readers_sentence(self):
        from hypnomix import project as PJ
        from hypnomix.workflow import abset_ardour as AA
        f = self.dir / "Song.ardour"
        f.write_text(f.read_text(encoding="utf-8")[:3000], encoding="utf-8")
        sd = Path(self.td.name) / "scan"
        sd.mkdir()
        (sd / "findings.json").write_text(json.dumps(dict(set=str(f), notes=[], findings=[
            dict(id="mix-1", tool="balance", severity="low", track="Kick", where="whole song", applies="set",
                 edit=dict(op="mixer", fader_db=-3.0), problem="loud", fix="3 dB down")])), encoding="utf-8")
        with self.assertRaises(PJ.ProjectReadError):
            AA.build(sd, "mix-1")


class CueSlots(unittest.TestCase):
    def test_a_clip_left_out_is_said_without_a_fixed_count(self):
        placed = [(dict(name="A"), 0, None), (dict(name="B"), None, "no empty slot left on this track")]
        self.assertEqual(AC.not_placed(placed), 1)
        self.assertNotIn("16", AC.report(placed, "Drums loops"))
        self.assertIn("HypnoMix sees the change", AC.report(placed, "Drums loops"))
        self.assertNotIn("HypnoMix sees the change", AC.report(placed[1:], "Drums loops"))


class SidechainFlags(Fixture):
    def run_main(self, *argv):
        from hypnomix.engineer import sidechain as SC
        with mock.patch.object(sys, "argv", ["hypnomix sidechain", *argv]), redirect_stdout(io.StringIO()) as out:
            try:
                SC.main()
            except SystemExit as e:
                return str(e), out.getvalue()
        return None, out.getvalue()

    def test_host_filters_and_live_only_flags_are_refused(self):
        f = str(self.dir / "Song.ardour")
        err, out = self.run_main(f, "--host", "nothing")
        self.assertIsNone(err)
        self.assertIn("0 sidechained compressor(s)", out)
        err, out = self.run_main(f, "--host", "bas")
        self.assertIn("1 sidechained compressor(s)", out)
        err, _ = self.run_main(f, "--use", "Drums=x.wav")
        self.assertIn("are for Live sets", err)


if __name__ == "__main__":
    unittest.main()
