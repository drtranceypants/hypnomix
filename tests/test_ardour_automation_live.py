"""Automation and the tempo map against a real HypnoMix engine on its silent test backend (Dummy): the writers of
project/ardour_automation.py into the open engine and into a new snapshot (opened again by a second engine), the
app's engine connection refusing what the smooth-automation rules refuse, vocallevel's and motion's writers, and the
tempo map read back exactly.

Needs an engine build with the automation and tempo tools: set HYPNOMIX_LIVE_ENGINE to its program (a source build's
hypnomix/engine/engine-dev). Without it every test here SKIPS, saying so. New neutral "Demo" sessions in a scratch
folder; nothing else is touched."""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace

ENGINE = os.environ.get("HYPNOMIX_LIVE_ENGINE", "")
NO_ENGINE = ("SKIPPED: no HypnoMix engine to run, so these were NOT run against one: set HYPNOMIX_LIVE_ENGINE to an "
             "engine build with the automation tools (a source build's hypnomix/engine/engine-dev)")
FILTER_ID = "lua:cbf2433c611d0849cbb198719a5ad05d2f69d24a"       # the engine's bundled high/low-pass filter script


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(args, port, log):
    p = subprocess.Popen([ENGINE, "--backend", "None (Dummy)", "--port", str(port), "--no-websockets"] + args,
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    url = f"http://127.0.0.1:{port}/mcp"
    t0 = time.time()
    while time.time() - t0 < 120:
        if p.poll() is not None:
            raise RuntimeError(f"the engine stopped (status {p.returncode})")
        try:
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
            with urllib.request.urlopen(urllib.request.Request(url, body, {"Content-Type": "application/json"}), timeout=2) as r:
                if json.loads(r.read()).get("result", {}).get("tools"):
                    return p, url
        except OSError:
            time.sleep(0.5)
    p.kill()
    raise RuntimeError("the engine did not answer within 120 s")


def stop(p):
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(15)
        except subprocess.TimeoutExpired:
            p.kill()


@unittest.skipUnless(ENGINE and os.access(ENGINE, os.X_OK), NO_ENGINE)
class LiveEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from hypnomix.project import ardour_groups as AG
        cls.td = Path(tempfile.mkdtemp(prefix="hx-auto-live-"))
        cls.log = open(cls.td / "engine.log", "wb")
        cls.port = free_port()
        cls.proc, cls.url = start(["--new", str(cls.td / "Demo"), "Demo"], cls.port, cls.log)
        cls.eng = AG.Engine(cls.url, timeout=120)
        e = cls.eng
        if not e.has("automation_write", "tempo_set_points"):
            stop(cls.proc)
            raise unittest.SkipTest("SKIPPED: this engine build has no automation or tempo map tools")
        for name in ("Lead Vocal", "Harmony", "Drums", "Strings"):
            e.call("tracks_add", {"type": "audio", "name": name})
        ids = {t["name"]: t["id"] for t in e.call("tracks_list", {})["tracks"]}
        e.call("group_create", {"name": "Vox", "track_ids": [ids["Lead Vocal"], ids["Harmony"]]})
        e.call("group_create", {"name": "Band", "track_ids": [ids["Drums"], ids["Strings"]]})
        e.call("plugin_add_by_plugin_id", {"id": ids["Drums"], "pluginId": FILTER_ID})
        e.call("session_save", {})
        cls.ids = {t["name"]: t["id"] for t in e.call("tracks_list", {})["tracks"]}
        cls.session = cls.td / "Demo" / "Demo.ardour"

    @classmethod
    def tearDownClass(cls):
        stop(getattr(cls, "proc", None))
        try:
            cls.log.close()
        except Exception:
            pass
        shutil.rmtree(cls.td, ignore_errors=True)

    def get(self, name, control):
        return self.eng.call("automation_get", {"track_id": self.ids[name], "control": control})

    def test_1_a_gentle_ride_into_the_open_engine(self):
        from hypnomix.project import ardour_automation as AA
        pts = AA.edge_points([(2.0, 5.0, 0.0), (5.6, 8.0, -2.5), (8.6, 11.0, 0.0)], 0.0)
        r = AA.write_engine(self.eng, self.ids["Harmony"], "gain", pts)
        self.assertLess(AA.steepest_of(r), 7.0)
        got = self.get("Harmony", "gain")
        self.assertGreaterEqual(len(got["pointList"]), 16)               # the engine's cosine between the points
        self.assertAlmostEqual(min(p["value"] for p in got["pointList"]), -2.5, places=2)
        self.assertEqual(got["state"], "play")
        with self.assertRaises(ValueError) as e:                         # it plays automation now
            AA.write_engine(self.eng, self.ids["Harmony"], "gain", pts)
        self.assertIn("already has automation", str(e.exception))

    def test_2_never_the_bus_that_carries_non_vocals(self):
        from hypnomix.project import ardour_automation as AA
        pts = AA.edge_points([(2.0, 5.0, -2.0)], 0.0)
        with self.assertRaises(ValueError) as e:
            AA.write_engine(self.eng, self.ids["Band"], "gain", pts)
        self.assertIn("Band carries Drums, Strings", str(e.exception))
        self.assertEqual(self.get("Band", "gain")["pointList"], [])
        r = AA.write_engine(self.eng, self.ids["Vox"], "trim", AA.edge_points([(2.0, 5.0, -2.0)], 0.0, cap=4))
        self.assertLess(AA.steepest_of(r), 7.0)                        # the vocal bus may be ridden

    def test_3_the_apps_engine_connection_refuses_before_sending(self):
        from hypnomix.app import daw as DW
        eng = DW.Engine()
        eng.mode, eng.port, eng.state = "engine", self.port, "running"
        bad = {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "automation_write", "arguments": {
            "track_id": self.ids["Lead Vocal"], "control": "gain", "curve": "s_curve",
            "points": [{"time": 1, "value": 0}, {"time": 1.3, "value": -3}]}}}
        code, raw = eng.rpc(json.dumps(bad).encode())
        reply = json.loads(raw)
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("dB/s", reply["result"]["content"][0]["text"])
        self.assertEqual(self.get("Lead Vocal", "gain")["pointList"], [])     # never reached the engine
        good = json.loads(json.dumps(bad))
        good["params"]["arguments"]["points"] = [{"time": 1, "value": 0}, {"time": 2.2, "value": -2}, {"time": 4, "value": -2},
                                                 {"time": 5.2, "value": 0}]
        code, raw = eng.rpc(json.dumps(good).encode())
        self.assertNotIn("isError", json.loads(raw)["result"])
        self.assertGreater(len(self.get("Lead Vocal", "gain")["pointList"]), 8)
        undo = self.eng.call("session_undo", {"count": 1})
        self.assertEqual(str(undo.get("nextRedo")).lower(), "write automation")   # one undo step, the name the view checks
        self.assertEqual(self.get("Lead Vocal", "gain")["pointList"], [])

    def test_4_a_tempo_map_with_a_ramp(self):
        from hypnomix import project as PJ
        from hypnomix.project import ardour as AR
        from hypnomix.project import ardour_automation as AA
        pts = AA.from_beats([(0, 100), (16, 140), (32, 140)])
        AA.write_tempo_engine(self.eng, pts)
        m = self.eng.call("tempo_get_map", {})
        self.assertEqual([(t["bbt"]["bar"], t["bpm"], t["bpmEnd"], t["ramped"]) for t in m["tempos"]],
                         [(1, 100, 140, True), (5, 140, 140, False)])
        self.assertAlmostEqual(m["tempos"][1]["time"], AA.seconds(pts, [16])[0], places=4)
        self.eng.call("session_save", {})
        p = PJ.load(self.session)
        self.assertFalse([w for w in p.warnings if "ramp" in w])
        clock, *_ = AR.tempo_map(p.native, p.sample_rate, AR.session_version(p.native), [])
        self.assertAlmostEqual(clock.beats_to_s(16), m["tempos"][1]["time"], places=5)
        self.eng.call("session_undo", {"count": 1})
        self.eng.call("session_save", {})

    def test_5_a_snapshot_written_from_the_file_opens_in_the_engine_as_written(self):
        from hypnomix import project as PJ
        from hypnomix.project import ardour_automation as AA
        from hypnomix.project import ardour_edit as AE
        self.eng.call("session_save", {})
        p = PJ.load(self.session)
        lead = p.track("Lead Vocal")
        AA.write_file(p, lead, "gain", AA.edge_points([(3.0, 6.0, -2.0)], 0.0))
        AA.write_tempo_file(p, AA.from_beats([(0, 96), (8, 120), (16, 120)]))
        out = self.session.with_name("Demo (written).ardour")
        AE.save(p, out)
        self.assertEqual(AE.check(self.session, out, automation=True, tempo=True), [])
        copy = self.td / "copy" / "Demo"                                   # its own folder: never two engines on one
        shutil.copytree(self.session.parent, copy, ignore=shutil.ignore_patterns("*.pending", "*.history", "instant.xml"))
        port = free_port()
        proc, url = start(["--", str(copy), "Demo (written)"], port, self.log)
        try:
            from hypnomix.project import ardour_groups as AG
            e2 = AG.Engine(url, timeout=120)
            ids = {t["name"]: t["id"] for t in e2.call("tracks_list", {})["tracks"]}
            got = e2.call("automation_get", {"track_id": ids["Lead Vocal"], "control": "gain"})
            self.assertEqual(got["state"], "play")
            self.assertAlmostEqual(min(x["value"] for x in got["pointList"]), -2.0, places=2)
            self.assertLess(AA.steepest_of(got), 7.0)
            m = e2.call("tempo_get_map", {})
            self.assertEqual([(t["bbt"]["bar"], t["ramped"]) for t in m["tempos"]], [(1, True), (3, False)])
            self.assertAlmostEqual(m["tempos"][1]["time"], AA.seconds(AA.from_beats([(0, 96), (8, 120), (16, 120)]), [8])[0], places=4)
        finally:
            stop(proc)

    def test_6_vocallevel_and_motion_write_into_the_open_engine(self):
        from hypnomix import project as PJ
        from hypnomix.session import motion_ardour as MA
        from hypnomix.workflow import vocallevel_ardour as VA
        self.eng.call("session_save", {})
        p = PJ.load(self.session)
        gains = {"Harmony": [(1, 3, 0.0), (3.5, 6, 0.0)],
                 "__group__": [(1, 3, 0.0), (3.5, 6, 1.5), (6.5, 9, 0.0)]}
        a = SimpleNamespace(engine=self.url, apply=None, group="Vox")
        self.assertEqual(VA.run(p, self.session, a, gains, ["Lead Vocal", "Harmony"], "Lead Vocal"), 0)
        vox = self.get("Vox", "gain")
        self.assertAlmostEqual(max(x["value"] for x in vox["pointList"]), 1.5, places=2)
        tg = MA.targets_engine(self.eng)
        self.assertTrue(any(t["track"] == "Drums" and t["label"].endswith("Low Pass Cut off frequency") and not t["high"] for t in tg), tg)
        low = [t for t in tg if t["label"].endswith("Low Pass Cut off frequency")]
        from hypnomix.project import ardour_automation as AA
        pts = MA.points("riser", low[0], 0.0, 8.0, dict(bars=2, depth=0.4, bar=2.0))   # a riser into 8 s
        AA.write_engine(self.eng, low[0]["route"], low[0]["control"], pts)
        got = self.eng.call("automation_get", {"track_id": self.ids["Drums"], "control": low[0]["control"]})
        self.assertGreaterEqual(len(got["pointList"]), 2)
        self.assertAlmostEqual(got["pointList"][0]["value"], low[0]["base"] * 2 ** -3.2, delta=1.0)
        self.assertAlmostEqual(got["pointList"][-1]["value"], low[0]["base"], delta=1.0)
        self.assertEqual(MA.targets_engine(self.eng), [t for t in tg if t is not low[0] and t["control"] != low[0]["control"]]
                         or MA.targets_engine(self.eng))                     # an automated filter is not offered again
        self.assertNotIn(low[0]["control"], [t["control"] for t in MA.targets_engine(self.eng)])

if __name__ == "__main__":
    unittest.main()
