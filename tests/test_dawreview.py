"""The DAW view's Review on the engine's session (hypnomix/app/dawreview.py): where findings are, which engine track
they are on, what Apply does with each, decisions, the scan's save + bounce + scan steps, and Apply's new snapshot."""
import json, tempfile, types, unittest
from pathlib import Path
from unittest import mock

from hypnomix.app import dawreview as DR
from hypnomix.app import server as SV


class Where(unittest.TestCase):
    def test_seconds(self):
        s = DR.seconds_of
        self.assertEqual(s({"edit": {"op": "dip", "t0": 162.66, "t1": 163.0}}, 120, 4), 162.66)
        self.assertEqual(s({"where": "82.2.03 (162.79 s)"}, 120, 4), 162.79)
        self.assertEqual(s({"where": "3.2.11"}, 120, 4), 4.5)                 # bar 3 beat 2 at 120 bpm: 9 beats
        self.assertEqual(s({"where": "bars 9-16, 45-52"}, 120, 4), 16.0)
        self.assertEqual(s({"where": "5:42"}, 120, 4), 342.0)                 # a clock time (sections), not bar 5
        self.assertAlmostEqual(s({"where": "1:02:03.5"}, 120, 4), 3723.5)
        self.assertAlmostEqual(s({"where": "whole take", "flagged_notes": [{"time": "0:22.37"}]}, 120, 4), 22.37)
        self.assertIsNone(s({"where": ""}, 120, 4))
        self.assertIsNone(s({"where": "whole take"}, 120, 4))

    def test_engine_track(self):
        names = ["Bass", "Drums", "Other", "Vocals"]
        self.assertEqual(DR.engine_track("Vocals%L.wav", names), "Vocals")
        self.assertEqual(DR.engine_track("other", names), "Other")
        self.assertIsNone(DR.engine_track("mix", names))

    def test_handling(self):
        self.assertEqual(DR.handling({"applies": "set", "edit": {"op": "dip"}})[0], "written")
        self.assertEqual(DR.handling({"applies": "set", "track_order": ["0"]})[0], "manual")
        self.assertEqual(DR.handling({"applies": "audio", "tool": "tune"})[0], "blocked")
        self.assertEqual(DR.handling({"applies": "audio", "tool": "deess", "run": ["deess"]})[0], "file")
        self.assertEqual(DR.handling({"applies": "answer"})[0], "question")
        self.assertEqual(DR.handling({"applies": "manual"})[0], "manual")

    def test_out_is_new_and_numbered(self):
        with tempfile.TemporaryDirectory() as td:
            s = Path(td) / "Song.ardour"
            s.write_text("<Session/>", encoding="utf-8")
            self.assertEqual(DR.out_for(s).name, "Song (hypnomix).ardour")
            (Path(td) / "Song (hypnomix).ardour").write_text("x", encoding="utf-8")
            self.assertEqual(DR.out_for(s).name, "Song (hypnomix 2).ardour")
            self.assertEqual(DR.out_for(Path(td) / "Song (hypnomix).ardour").name, "Song (hypnomix 2).ardour")

    def test_applied_ids_from_the_fix_log(self):
        log = ("## fix run 2026-11-26 04:08\n\napproved: clips-1, order-1\n\n- clips-1: Other 1-2 s: gain dip\n"
               "### skipped (not applied)\n\n- order-1 (all tracks) : by hand\n")
        self.assertEqual(DR.applied_ids(log), ["clips-1"])


class FakeEngine:
    def __init__(self, session):
        self.session, self.calls, self.polls = str(session), [], 0
        self.reported_dirty = True                 # what session_list_snapshots says
        self._edits = 0                            # as daw.Engine counts the changes that went through
        self.edit_while_bouncing = False

    def connected(self):
        return True

    def call(self, method, params=None, timeout=8.0):
        name, args = params["name"], params.get("arguments", {})
        self.calls.append(name)
        if name == "session_list_snapshots":
            out = dict(dirty=self.reported_dirty, snapshots=[dict(name="Song", file=self.session, current=True)])
        elif name == "session_save":
            out = {}
        elif name == "session_export_mix":
            Path(args["path"]).write_bytes(b"RIFF")
            out = dict(jobId="export-1", state="running", progress=0.2)
        elif name == "export_status":
            self.polls += 1
            if self.edit_while_bouncing:
                self._edits += 1
            out = dict(jobId="export-1", state="done", progress=1, elapsedSeconds=3, analysis={"truePeakDb": -1.0})
        else:
            raise AssertionError(name)
        return {"structuredContent": out}


class Routes(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.home = Path(self.td.name).resolve()
        self.sess = self.home / "Song" / "Song.ardour"
        self.sess.parent.mkdir()
        self.sess.write_text("<Session/>", encoding="utf-8")
        self.env = mock.patch.dict("os.environ", {"HYPNOMIX_APP_HOME": str(self.home / "app")})
        self.env.start()
        self.eng = FakeEngine(self.sess)
        self.p = mock.patch.object(DR, "_engine", lambda: self.eng)
        self.p.start()
        self.runs = []
        self.rj = mock.patch.object(SV, "run_job", lambda kind, title, steps, d="", watch=(): self.runs.append((kind, steps, d)))
        self.rj.start()

    def tearDown(self):
        self.rj.stop(); self.p.stop(); self.env.stop(); self.td.cleanup()

    def test_scan_saves_bounces_then_scans_with_the_mix(self):
        st = DR.handle_get(SV, "/api/dawreview/state", {})[1]
        self.assertTrue(st["connected"] and st["dirty"] and not st["scanned"])
        self.assertEqual(st["out"], "Song (hypnomix).ardour")
        code, body = DR.handle_post(SV, "/api/dawreview/scan", {})            # unsaved changes: nothing is saved for them
        self.assertEqual((code, body), (409, {"error": "unsaved", "dirty": True}))
        self.assertEqual((self.runs, self.eng.calls.count("session_save")), ([], 0))
        code, body = DR.handle_post(SV, "/api/dawreview/scan", {"save": "yes"})   # only a real true is the person's click
        self.assertEqual(code, 409)
        r = DR.handle_post(SV, "/api/dawreview/scan", {"save": True})[1]
        kind, steps, d = self.runs[-1]
        self.assertEqual(kind, "scan")
        SV.JOB["log"] = log = []                  # the steps write into the job's own log (main's job runner calls them bare)
        with mock.patch.object(DR.time, "sleep", lambda s: None):
            steps[0][1]()                         # save
            steps[1][1]()                         # bounce, polled until done
        self.assertTrue(any("saved Song.ardour" in x for x in log))
        self.assertEqual(self.eng.calls[-3:], ["session_save", "session_export_mix", "export_status"])
        self.assertEqual(self.eng.polls, 1)
        mix = Path(r["dir"]) / DR.MIX_NAME
        self.assertTrue(mix.exists())
        self.assertEqual(steps[2][1], ["scan", str(self.sess), "--out", r["dir"], "--mix", str(mix)])
        self.assertEqual(json.loads((Path(r["dir"]) / "daw-session.json").read_text(encoding="utf-8"))["session"], str(self.sess))

    def test_a_scan_of_a_saved_session_saves_nothing(self):
        self.eng.reported_dirty = False
        r = DR.handle_post(SV, "/api/dawreview/scan", {})[1]                 # nothing unsaved: no save, no question
        steps = self.runs[-1][1]
        self.assertEqual([x[0] for x in steps], ["Bouncing the mix", "Scanning (changes nothing)"])
        SV.JOB["log"] = []
        with mock.patch.object(DR.time, "sleep", lambda s: None):
            steps[0][1]()
        self.assertNotIn("session_save", self.eng.calls)
        self.assertTrue((Path(r["dir"]) / DR.MIX_NAME).exists())

    def test_a_scan_stops_when_the_session_changes_while_it_bounces(self):
        self.eng.edit_while_bouncing = True
        DR.handle_post(SV, "/api/dawreview/scan", {"save": True})
        steps = self.runs[-1][1]
        SV.JOB["log"] = []
        with mock.patch.object(DR.time, "sleep", lambda s: None):
            steps[0][1]()
            with self.assertRaises(RuntimeError) as cm:
                steps[1][1]()
        self.assertIn("changed while the mix was bounced", str(cm.exception))
        self.assertFalse(any((SV.work() / "scan").glob("*/daw-session.json")))   # nothing says this bounce belongs to the scan

    def _scan(self):
        d = SV.work() / "scan" / "Song (DAW)"
        d.mkdir(parents=True)
        fs = [dict(id="clips-1", tool="clips", kind="spike", severity="low", track="Other", where="2.1.01 (2.00 s)",
                   applies="set", edit=dict(op="dip", t0=2.0, t1=2.3, db=6.0), problem="a burst", fix="a dip"),
              dict(id="tune-Vocals", tool="tune", severity="medium", track="Vocals", where="whole take", applies="audio",
                   problem="off", fix="tune")]
        (d / "findings.json").write_text(json.dumps(dict(set=str(self.sess), notes=[], findings=fs)), encoding="utf-8")
        return d

    def test_decide_apply_and_refusals(self):
        d = self._scan()
        post = lambda path, body: DR.handle_post(SV, path, dict(body, dir=str(d)))[1]
        post("/api/dawreview/decide", dict(id="clips-1", decision="approve"))
        post("/api/dawreview/decide", dict(id="tune-Vocals", decision="change", note="gentler"))
        dec = json.loads((d / "decisions.json").read_text(encoding="utf-8"))
        self.assertEqual(dec["clips-1"]["decision"], "approve")
        self.assertEqual(dec["tune-Vocals"]["note"], "gentler")
        with self.assertRaises(ValueError):           # tuning is not written into an Ardour session: no Approve
            post("/api/dawreview/decide", dict(id="tune-Vocals", decision="approve"))
        post("/api/dawreview/decide", dict(id="tune-Vocals", decision="clear"))
        self.assertNotIn("tune-Vocals", json.loads((d / "decisions.json").read_text(encoding="utf-8")))
        r = post("/api/dawreview/apply", {})
        kind, steps, _ = self.runs[-1]
        self.assertEqual(kind, "fix")
        self.assertEqual(steps[0][1], ["fix", str(d), "--approved", "--out", str(self.sess.parent / "Song (hypnomix).ardour")])
        self.assertTrue(r["out"].endswith("Song (hypnomix).ardour"))
        post("/api/dawreview/ab", dict(id="clips-1"))
        self.assertEqual(self.runs[-1][1][0][1], ["ab", str(d), "--ids", "clips-1"])


class SnapshotWrite(unittest.TestCase):
    """Apply writes its new snapshot whole or not at all (a cut-off .ardour in the session folder would be listed by the
    engine as a snapshot)."""
    def test_a_failed_write_leaves_no_snapshot_and_no_leftover(self):
        import xml.etree.ElementTree as ET
        from hypnomix.project import ardour_edit as AE
        p = types.SimpleNamespace(native=ET.Element("Session"))
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "Song (hypnomix).ardour"
            real = ET.ElementTree.write

            def half(self, path, *a, **k):
                Path(path).write_text("<?xml version='1.0'?><Session", encoding="utf-8")      # cut off, then the disk is full
                raise OSError(28, "No space left on device")
            with mock.patch.object(ET.ElementTree, "write", half):
                with self.assertRaises(OSError):
                    AE.save(p, out)
            self.assertEqual(list(Path(td).iterdir()), [])
            AE.save(p, out)
            self.assertEqual([f.name for f in Path(td).iterdir()], [out.name])
            self.assertEqual(ET.parse(out).getroot().get("name"), "Song (hypnomix)")


class JobSteps(unittest.TestCase):
    def test_a_step_can_be_a_function(self):
        done = []
        SV.JOB.update(status="idle")
        SV.run_job("t", "t", [("first", lambda: done.append(1) or SV.JOB["log"].append("one"), True),
                              ("broken", lambda: 1 / 0, True),
                              ("never", lambda: done.append(2), True)])
        for _ in range(200):
            if SV.JOB["status"] != "running":
                break
            import time
            time.sleep(0.01)
        self.assertEqual(SV.JOB["status"], "failed")
        self.assertEqual(done, [1])
        self.assertIn("one", SV.JOB["log"])
        self.assertTrue(any("division by zero" in x for x in SV.JOB["log"]))


if __name__ == "__main__":
    unittest.main()
