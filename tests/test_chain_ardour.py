"""`chain --ardour`: which ACE / HypnoMix plug-ins, in which order, set to what. A fake HypnoMix MCP server (real
HTTP, JSON-RPC tools/call, the tool names and replies of HypnoMix's mcp_http surface) records every call."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from hypnomix.engineer import chain_ardour as CA

# the controls each plug-in shows (labels, ranges), as plugin_get_description reports them
PARAMS = {
    "ACE High/Low Pass Filter": [("High Pass Steepness", 0, 4), ("High Pass Cut off frequency", 5, 20000),
                                 ("High Pass Resonance", 0.1, 6), ("Low Pass Steepness", 0, 4),
                                 ("Low Pass Cut off frequency", 20, 20000), ("Low Pass Resonance", 0.1, 6)],
    "ACE EQ": [("Frequency L", 20, 20000), ("Gain L", -20, 20)] +
              [x for n in range(1, 5) for x in ((f"Frequency {n}", 20, 20000), (f"Gain {n}", -20, 20),
                                                (f"Bandwidth {n}", 0.1, 4))] +
              [("Frequency H", 20, 20000), ("Gain H", -20, 20), ("Master Gain", -20, 20)] +
              [(f"Filter {k}", 0, 1) for k in ("L", "1", "2", "3", "4", "H")],
    "ACE Compressor (stereo)": [("Attack", 0.1, 100), ("Release", 1, 2000), ("Knee", 0, 8), ("Ratio", 1, 20),
                                ("Threshold", -60, 0), ("Makeup", 0, 30), ("Sidechain", 0, 1)],
    "Hypnomix Utility": [("Gain", -70, 35), ("Width", 0, 200), ("Mono", 0, 1), ("Bass Mono", 0, 1),
                         ("Bass Mono Frequency", 20, 500), ("Phase Invert L", 0, 1), ("Phase Invert R", 0, 1),
                         ("DC Filter", 0, 1), ("Mute", 0, 1), ("Balance", -100, 100)],
    "Hypnomix Limiter": [("Gain", -12, 24), ("Ceiling", -12, 0), ("Release", 5, 1000), ("Lookahead", 0.5, 10),
                         ("True Peak", 0, 1)],
}
UNIQUE = {"urn:ardour:a-eq": "ACE EQ", "urn:ardour:a-comp#stereo": "ACE Compressor (stereo)",
          "urn:hypnomix:utility": "Hypnomix Utility", "urn:hypnomix:limiter": "Hypnomix Limiter"}


class FakeHypnomix:
    """The master bus's processor list and every tool call, behind a real HTTP MCP endpoint."""

    def __init__(self, master_plugins=(), known=None):
        self.plugins = [dict(name=n, enabled=True) for n in master_plugins]
        self.calls, self.values = [], {}
        self.known = set(UNIQUE) if known is None else set(known)

    def tool(self, name, a):
        self.calls.append((name, a))
        if name == "session_get_info":
            return {"name": "Harbor", "sampleRate": 48000}
        if name == "tracks_list":
            return {"tracks": [{"id": "11", "name": "Vocals", "type": "audio"},
                               {"id": "99", "name": "Master", "type": "master"}]}
        if name == "track_get_info":
            return {"id": a["id"], "plugins": [dict(index=i, **p) for i, p in enumerate(self.plugins)]}
        if name == "plugin_list_available":
            return {"count": 1, "plugins": [{"pluginId": "lua:c9a4d2f1", "type": "lua", "name": "ACE High/Low Pass Filter"}]}
        if name in ("plugin_add_by_unique_id", "plugin_add_by_plugin_id"):
            if name == "plugin_add_by_unique_id":
                if a["uniqueId"] not in self.known:
                    raise LookupError("Plugin not found")
                shown = UNIQUE[a["uniqueId"]]
            else:
                shown = "ACE High/Low Pass Filter"
            pos = a.get("position", len([p for p in self.plugins]))
            self.plugins.insert(pos, dict(name=shown, enabled=True))
            return {"id": a["id"], "pluginIndex": pos, "plugins": []}
        if name == "plugin_get_description":
            p = self.plugins[a["pluginIndex"]]
            ps = [dict(index=i, controlId=100 + i, label=lab, lower=lo, upper=hi, isInput=True, isOutput=False)
                  for i, (lab, lo, hi) in enumerate(PARAMS.get(p["name"], []))]
            ps.append(dict(index=len(ps), controlId=999, label="Gain Reduction", lower=0, upper=40, isInput=False,
                           isOutput=True))
            return {"plugin": {"index": a["pluginIndex"], "name": p["name"]}, "parameters": ps}
        if name == "plugin_set_parameter_by_control_value":
            p = self.plugins[a["pluginIndex"]]
            lab = PARAMS[p["name"]][a["controlId"] - 100][0]
            self.values[(a["pluginIndex"], lab)] = a["value"]
            return {"id": a["id"], "pluginIndex": a["pluginIndex"], "parameterIndex": a["controlId"] - 100,
                    "controlId": a["controlId"], "value": a["value"], "interface": 0}
        if name == "plugin_set_enabled":
            self.plugins[a["pluginIndex"]]["enabled"] = a["enabled"]
            return {"ok": True}
        if name == "plugin_remove":
            self.plugins.pop(a["pluginIndex"])
            return {"removed": True, "id": a["id"], "pluginIndex": a["pluginIndex"], "plugins": []}
        raise LookupError(f"unknown tool {name}")

    def value(self, shown, label, nth=0):
        idx = [i for i, p in enumerate(self.plugins) if p["name"] == shown][nth]
        return self.values.get((idx, label))


class Server:
    def __init__(self, fake):
        fake_ = fake

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                p = req["params"]
                try:
                    out = fake_.tool(p["name"], p.get("arguments", {}))
                    res = {"content": [{"type": "text", "text": json.dumps(out)}], "structuredContent": out}
                except LookupError as e:
                    res = {"content": [{"type": "text", "text": str(e)}], "isError": True}
                body = json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": res}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/mcp"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


PLAN = [dict(device="EQ Eight", bands=[dict(type="lowcut12", freq=22, gain=0, q=0.71),
                                       dict(type="lowshelf", freq=90, gain=0.8, q=0.71),
                                       dict(type="bell", freq=550, gain=-1.2, q=0.9),
                                       dict(type="highshelf", freq=9000, gain=1.1, q=0.71)], why=""),
        dict(device="Glue Compressor", threshold_db=-12.5, ratio=2, attack_ms=30, release_s=0.2, makeup_db=0, why=""),
        dict(device="Utility", bass_mono_hz=120, width_pct=100, why=""),
        dict(device="Saturator", drive_db=2.0, dry_wet_pct=35, why=""),
        dict(device="Limiter", gain_db=3.0, ceiling_db=-1.0, release_ms=80, why="")]


class ChainArdour(unittest.TestCase):
    def run_chain(self, fake, plan=PLAN, existing="refuse"):
        srv = Server(fake)
        try:
            m = CA.MCP(srv.url, timeout=5)
            return CA.build_master(m, [dict(s) for s in plan], existing)
        finally:
            srv.close()

    def test_master_chain_order_and_values(self):
        f = FakeHypnomix()
        rows, notes = self.run_chain(f)
        self.assertEqual([p["name"] for p in f.plugins], ["ACE High/Low Pass Filter", "ACE EQ",
                         "ACE Compressor (stereo)", "Hypnomix Utility", "Hypnomix Limiter"])
        v = f.value
        self.assertEqual(v("ACE High/Low Pass Filter", "High Pass Steepness"), 1)       # 12 dB/oct
        self.assertEqual(v("ACE High/Low Pass Filter", "High Pass Cut off frequency"), 22)
        self.assertEqual(v("ACE High/Low Pass Filter", "Low Pass Steepness"), 0)        # no low-pass
        self.assertEqual(v("ACE EQ", "Gain L"), 0.8)
        self.assertEqual(v("ACE EQ", "Frequency 1"), 550)
        self.assertAlmostEqual(v("ACE EQ", "Bandwidth 1"), 1.53, places=2)             # Q 0.9 in octaves
        self.assertEqual(v("ACE EQ", "Filter 2"), 0)                                   # unused bells off
        self.assertEqual(v("ACE EQ", "Gain H"), 1.1)
        self.assertEqual(v("ACE Compressor (stereo)", "Release"), 200)
        self.assertEqual(v("ACE Compressor (stereo)", "Ratio"), 2)
        self.assertEqual(v("Hypnomix Utility", "Bass Mono"), 1)
        self.assertEqual(v("Hypnomix Utility", "Bass Mono Frequency"), 120)
        self.assertEqual(v("Hypnomix Limiter", "Gain"), 3.0)
        self.assertEqual(v("Hypnomix Limiter", "Ceiling"), -1.0)
        self.assertEqual(v("Hypnomix Limiter", "True Peak"), 1)
        self.assertEqual(v("Hypnomix Limiter", "Release"), 80)
        self.assertTrue(any("Saturator" in n for n in notes))                          # said, not faked
        self.assertNotIn("ReaLimit", json.dumps(rows))
        # the LV2 devices are added by uniqueId, the Lua filter through the catalogue
        adds = [(n, a.get("uniqueId") or a.get("pluginId")) for n, a in f.calls if n.startswith("plugin_add")]
        self.assertEqual(adds[0], ("plugin_add_by_plugin_id", "lua:c9a4d2f1"))
        self.assertIn(("plugin_add_by_unique_id", "urn:hypnomix:limiter"), adds)

    def test_values_are_clamped_and_noted(self):
        f = FakeHypnomix()
        plan = [dict(device="Limiter", gain_db=30.0, ceiling_db=-1.0, release_ms=80, why="")]
        rows, notes = self.run_chain(f, plan)
        self.assertEqual(f.value("Hypnomix Limiter", "Gain"), 24)
        self.assertTrue(any("outside" in n for n in notes))

    def test_chain_goes_before_hypnomix_main(self):
        f = FakeHypnomix(master_plugins=["Hypnomix Main"])
        self.run_chain(f)
        self.assertEqual(f.plugins[-1]["name"], "Hypnomix Main")
        self.assertEqual(f.plugins[0]["name"], "ACE High/Low Pass Filter")
        self.assertTrue(f.plugins[-1]["enabled"])                                      # meters never bypassed

    def test_existing_plugins_refuse_bypass_keep(self):
        with self.assertRaises(SystemExit):
            self.run_chain(FakeHypnomix(master_plugins=["Some Limiter"]))
        f = FakeHypnomix(master_plugins=["Some Limiter"])
        self.run_chain(f, existing="bypass")
        self.assertFalse(f.plugins[0]["enabled"])
        self.assertEqual(f.plugins[0]["name"], "Some Limiter")                         # never deleted
        f = FakeHypnomix(master_plugins=["Some Limiter"])
        self.run_chain(f, existing="keep")
        self.assertTrue(f.plugins[0]["enabled"])

    def test_old_hypnomix_without_the_devices_says_so(self):
        f = FakeHypnomix(known={"urn:ardour:a-eq", "urn:ardour:a-comp#stereo"})
        rows, notes = self.run_chain(f)
        self.assertTrue(any("Hypnomix Limiter" in n and "could not be added" in n for n in notes))
        self.assertNotIn("Hypnomix Limiter", [p["name"] for p in f.plugins])

    def test_more_than_four_bells_use_a_second_eq(self):
        f = FakeHypnomix()
        bands = [dict(type="bell", freq=100 * (k + 1), gain=-1, q=1) for k in range(6)]
        self.run_chain(f, [dict(device="EQ Eight", bands=bands, why="")])
        self.assertEqual([p["name"] for p in f.plugins], ["ACE EQ", "ACE EQ"])
        self.assertEqual(f.value("ACE EQ", "Frequency 1", nth=1), 500)
        self.assertEqual(f.value("ACE EQ", "Filter 3", nth=1), 0)

    def test_dry_run_touches_nothing(self):
        rows, notes = CA.build_master(None, [dict(s) for s in PLAN], dry=True)
        self.assertEqual([r[0] for r in rows], ["ACE High/Low Pass Filter", "ACE EQ", "ACE Compressor (stereo)",
                                                "Hypnomix Utility", "(left out)", "Hypnomix Limiter"])

    def test_cli_plans_and_builds_over_mcp(self):
        """`hypnomix chain master BOUNCE --ardour --mcp-url URL`: the offline plan, then the chain in the session."""
        import os, subprocess, sys, tempfile
        import numpy as np
        import soundfile as sf
        r = np.random.default_rng(3)
        sr = 44100
        n = sr * 12
        t = np.arange(n) / sr
        mono = 0.25 * np.sin(2 * np.pi * 55 * t) * (1 + 0.5 * np.sin(2 * np.pi * 2 * t))
        y = np.stack([mono + 0.05 * r.standard_normal(n), mono + 0.05 * r.standard_normal(n)], 1)
        f = FakeHypnomix(master_plugins=["Hypnomix Main"])
        srv = Server(f)
        try:
            with tempfile.TemporaryDirectory() as td:
                wav = os.path.join(td, "bounce.wav")
                sf.write(wav, y, sr)
                out = subprocess.run([sys.executable, "-m", "hypnomix.cli", "chain", "master", wav, "--ardour",
                                      "--mcp-url", srv.url], capture_output=True, text=True, timeout=300)
        finally:
            srv.close()
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        self.assertIn("Hypnomix Limiter", out.stdout)
        names = [p["name"] for p in f.plugins]
        self.assertEqual(names[-2:], ["Hypnomix Limiter", "Hypnomix Main"])
        self.assertEqual(f.value("Hypnomix Limiter", "True Peak"), 1)
        self.assertLessEqual(f.value("Hypnomix Limiter", "Ceiling"), -1.0)

    def test_no_engine_is_a_clear_error(self):
        m = CA.MCP("http://127.0.0.1:9/mcp", timeout=1)
        with self.assertRaises(CA.MCPError):
            m.ping()

    def test_master_is_the_bus_named_master(self):
        """HypnoMix's real tracks_list reports the master as type "bus" (route_type_string has no "master")."""
        class Stub:
            def __init__(self, tracks):
                self.tracks = tracks

            def call(self, name, **a):
                return {"tracks": self.tracks}
        real = [{"id": "11", "name": "Master Vocals", "type": "audio_track"},
                {"id": "12", "name": "Drums", "type": "bus"}, {"id": "23", "name": "Master", "type": "bus"}]
        self.assertEqual(CA.master_route(Stub(real))["id"], "23")
        self.assertEqual(CA.master_route(Stub([{"id": "5", "name": "Main", "type": "master"}]))["id"], "5")
        with self.assertRaises(CA.MCPError):
            CA.master_route(Stub([{"id": "12", "name": "Drums", "type": "bus"}]))


# ---------------------------------------------------------------- the review's findings (converters)
class Direct:
    """The fake, called in-process like an MCP client, with one call that fails: `mode` "before" (the engine never saw
    it) or "after" (the engine did it, and its answer was lost)."""

    def __init__(self, fake, fail_at=None, mode="before"):
        self.fake, self.fail_at, self.mode, self.n = fake, fail_at, mode, 0

    def call(self, name, **a):
        self.n += 1
        hit = self.n == self.fail_at
        if hit and self.mode == "before":
            raise CA.MCPError(f"{name}: no answer from the engine (test)")
        try:
            out = self.fake.tool(name, a)
        except LookupError as e:
            raise CA.MCPToolError(f"{name}: {e}")
        if hit:
            raise CA.MCPError(f"{name}: the connection dropped (test)")
        return out


def state(f):
    return [(p["name"], p["enabled"]) for p in f.plugins]


MINI = [dict(device="Limiter", gain_db=3.0, ceiling_db=-1.0, release_ms=80, why=""),
        dict(device="Utility", bass_mono_hz=120, width_pct=100, why="")]


class FailsPartWay(unittest.TestCase):
    """A call that fails in the middle of the build never leaves the master half built or the person's own plug-ins
    switched off: what this run added is removed and theirs are switched back on."""

    def sweep(self, master, plan, existing="bypass"):
        total = 0
        for mode in ("before", "after"):
            n = 1
            while True:
                f = FakeHypnomix(master_plugins=master)
                before = state(f)
                client = Direct(f, fail_at=n, mode=mode)
                try:
                    rows, notes = CA.build_master(client, [dict(s) for s in plan], existing)
                except CA.MCPError as e:
                    self.assertEqual(state(f), before, f"call {n} ({mode}): {e}")        # exactly as it was
                    self.assertTrue("NOT built" in str(e) or "Nothing was changed" in str(e), str(e))
                    n += 1
                    continue
                self.assertGreater(n, 5)                    # past the last call: the chain was built whole
                self.assertFalse(CA.incomplete(rows))
                break
            total = max(total, n)
        return total

    def test_every_call_can_fail_and_the_master_comes_back(self):
        total = self.sweep(["Some Limiter", "Hypnomix Main"], PLAN)
        self.assertGreater(total, 40)                        # it really went through the whole chain

    def test_with_nothing_else_on_the_master(self):
        self.sweep([], MINI, existing="refuse")

    def test_a_plugin_that_was_already_off_stays_off(self):
        f = FakeHypnomix(master_plugins=["Old Comp", "Some Limiter"])
        f.plugins[0]["enabled"] = False
        before = state(f)
        pf = FakeHypnomix(master_plugins=["Old Comp", "Some Limiter"])
        pf.plugins[0]["enabled"] = False
        probe = Direct(pf)
        CA.build_master(probe, [dict(s) for s in PLAN], "bypass")
        with self.assertRaises(CA.MCPError):               # the very last call (bypassing Some Limiter) is applied, its answer lost
            CA.build_master(Direct(f, fail_at=probe.n, mode="after"), [dict(s) for s in PLAN], "bypass")
        self.assertEqual(state(f), before)
        CA.build_master(Direct(f), [dict(s) for s in PLAN], "bypass")
        self.assertEqual([e for n, e in state(f) if n in ("Old Comp", "Some Limiter")], [False, False])

    def test_the_persons_plugins_are_bypassed_only_after_the_chain_is_in(self):
        f = FakeHypnomix(master_plugins=["Some Limiter"])
        CA.build_master(Direct(f), [dict(s) for s in PLAN], "bypass")
        calls = [n for n, a in f.calls]
        self.assertEqual(calls.count("plugin_set_enabled"), 1)
        last_set = max(i for i, n in enumerate(calls) if n.startswith("plugin_set_param"))
        self.assertGreater(calls.index("plugin_set_enabled"), last_set)
        self.assertEqual(state(f)[0], ("Some Limiter", False))

    def test_a_rollback_that_cannot_finish_says_exactly_what_is_left(self):
        f = FakeHypnomix(master_plugins=["Some Limiter"])

        class Dies(Direct):
            def call(s, name, **a):
                if s.n >= 30 and name in ("plugin_remove", "plugin_set_enabled"):
                    s.n += 1
                    raise CA.MCPError(f"{name}: no answer (test)")
                return super().call(name, **a)
        with self.assertRaises(CA.MCPError) as cm:
            CA.build_master(Dies(f, fail_at=31), [dict(s) for s in PLAN], "bypass")
        msg = str(cm.exception)
        self.assertIn("NOT built", msg)
        self.assertIn("could not take everything back out", msg)
        self.assertIn("could not remove", msg)

    def test_a_missing_device_is_marked_and_the_persons_plugins_are_left_on(self):
        f = FakeHypnomix(master_plugins=["Some Limiter"], known={"urn:ardour:a-eq", "urn:ardour:a-comp#stereo"})
        rows, notes = CA.build_master(Direct(f), [dict(s) for s in PLAN], "bypass")
        by = {r[0]: r for r in rows}
        self.assertIn("NOT BUILT: Hypnomix Limiter", by)
        self.assertIn("NOT BUILT: Hypnomix Utility", by)
        self.assertNotIn("Hypnomix Limiter", by)                 # no row claims it
        self.assertTrue(CA.incomplete(rows))
        self.assertEqual(state(f)[0], ("Some Limiter", True))     # an incomplete chain never switches theirs off
        self.assertTrue(any("NOT bypassed" in n for n in notes))

    def test_a_control_that_is_not_there_is_not_set_and_the_command_fails(self):
        import contextlib
        import io
        from unittest import mock
        params = dict(PARAMS)
        params["Hypnomix Limiter"] = [x for x in PARAMS["Hypnomix Limiter"] if x[0] != "Ceiling"]
        with mock.patch.dict(PARAMS, params, clear=True):
            rows, notes = CA.build_master(Direct(FakeHypnomix()), [dict(s) for s in PLAN])
        lim = next(r for r in rows if r[0] == "Hypnomix Limiter")
        self.assertIn("NOT SET: Ceiling", lim[1])
        self.assertTrue(CA.incomplete(rows))
        srv = Server(FakeHypnomix())                             # and the command exits with an error after the table
        a = type("A", (), dict(cmd="master", dry_run=False, mcp_url=srv.url, bounce="b.wav", target=-14, ceiling=-1,
                               reference=None, match=0.6, warmth=0.0, width=1.0, existing="refuse", verify=False))()
        out = io.StringIO()
        try:
            with mock.patch.dict(PARAMS, params, clear=True), contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    CA.main_ardour(a, lambda *x: ([dict(s) for s in PLAN], None))
        finally:
            srv.close()
        self.assertIn("NOT SET: Ceiling", out.getvalue())
        self.assertIn("incomplete", str(cm.exception))

    def test_the_command_says_it_in_one_sentence_not_a_traceback(self):
        import contextlib
        import io
        f = FakeHypnomix(master_plugins=["Some Limiter"])
        srv = Canned(f, fail_at=14, how="500")
        a = type("A", (), dict(cmd="master", dry_run=False, mcp_url=srv.url, bounce="b.wav", target=-14, ceiling=-1,
                               reference=None, match=0.6, warmth=0.0, width=1.0, existing="bypass", verify=False))()
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    CA.main_ardour(a, lambda *x: ([dict(s) for s in PLAN], None))
        finally:
            srv.close()
        msg = str(cm.exception)
        self.assertIn("NOT built", msg)
        self.assertIn("HTTP 500", msg)
        self.assertNotIn("Traceback", msg)
        self.assertEqual(state(f), [("Some Limiter", True)])


class FollowUp(unittest.TestCase):
    """The independent check's findings: a plug-in of the person's named like ours, clamped values in the table,
    and the advice after an incomplete chain."""
    sweep = FailsPartWay.sweep

    def test_the_persons_plugin_named_like_ours_survives_a_lost_reply(self):
        self.assertGreater(self.sweep(["Hypnomix Main", "ACE EQ", "Some Limiter"], PLAN), 40)
        self.assertGreater(self.sweep(["Hypnomix Main", "Hypnomix Limiter"], PLAN), 40)

    def test_what_cannot_be_told_apart_is_not_removed_and_is_reported(self):
        plan = [dict(device="EQ Eight", bands=[dict(type="lowshelf", freq=90, gain=0.8, q=0.71)], why="")]
        f = FakeHypnomix(master_plugins=["ACE EQ"])            # theirs, and the engine appends ours: two ACE EQs
        with self.assertRaises(CA.MCPError) as cm:
            CA.build_master(Direct(f, fail_at=3, mode="after"), plan, "keep")       # call 3 = the add, answer lost
        self.assertEqual(len(f.plugins), 2)                    # nothing was removed: no guess between the two
        self.assertIn("cannot be told which", str(cm.exception))

    def test_a_clamped_value_is_shown_as_it_was_set(self):
        f = FakeHypnomix()
        plan = [dict(device="Limiter", gain_db=30.0, ceiling_db=-14.0, release_ms=80, why="")]
        rows, notes = CA.build_master(Direct(f), plan)
        self.assertEqual(f.value("Hypnomix Limiter", "Ceiling"), -12)
        text = rows[0][1]
        self.assertIn("NOT SET: Ceiling, Gain", text)
        self.assertIn("Ceiling -14 -> -12", text)
        self.assertIn("Gain 30 -> 24", text)
        self.assertTrue(CA.incomplete(rows))

    def test_a_clamp_that_does_not_change_the_level_is_shown_but_does_not_fail(self):
        f = FakeHypnomix()
        plan = [dict(device="Limiter", gain_db=3.0, ceiling_db=-1.0, release_ms=2000, why="")]    # release range is 5..1000
        rows, notes = CA.build_master(Direct(f), plan)
        self.assertIn("Release 2000 -> 1000", rows[0][1])
        self.assertFalse(CA.incomplete(rows))

    def test_the_advice_after_an_incomplete_chain_does_not_double_the_chain(self):
        import contextlib
        import io
        from unittest import mock
        f = FakeHypnomix(master_plugins=["Some Limiter"], known={"urn:ardour:a-eq", "urn:ardour:a-comp#stereo",
                                                                  "urn:hypnomix:utility"})       # an older engine: no Limiter
        srv = Server(f)
        a = type("A", (), dict(cmd="master", dry_run=False, mcp_url=srv.url, bounce="b.wav", target=-14, ceiling=-1,
                               reference=None, match=0.6, warmth=0.0, width=1.0, existing="bypass", verify=False))()
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    CA.main_ardour(a, lambda *x: ([dict(s) for s in PLAN], None))
            msg = str(cm.exception)
            self.assertNotIn("--existing keep", msg)                      # the old advice built the chain twice
            self.assertIn("remove the plug-ins this run added", msg)
            built = [p["name"] for p in f.plugins]
            self.assertEqual(built[0], "Some Limiter")
            self.assertTrue(f.plugins[0]["enabled"])                      # theirs stay on in an incomplete chain
            f.known.add("urn:hypnomix:limiter")                           # the cause is fixed
            a.existing = "refuse"
            with self.assertRaises(SystemExit) as again:                  # running it on top is refused, not doubled
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    CA.main_ardour(a, lambda *x: ([dict(s) for s in PLAN], None))
            self.assertIn("already has plug-ins", str(again.exception))
            self.assertEqual([p["name"] for p in f.plugins], built)
            f.plugins[1:] = []                                            # the advised step: take the built plug-ins out
            a.existing = "bypass"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                CA.main_ardour(a, lambda *x: ([dict(s) for s in PLAN], None))
        finally:
            srv.close()
        names = [p["name"] for p in f.plugins]
        self.assertEqual(names.count("Hypnomix Limiter"), 1)
        self.assertEqual(names.count("ACE Compressor (stereo)"), 1)
        self.assertFalse(f.plugins[0]["enabled"])                         # complete now: theirs is bypassed


class Canned:
    """A real HTTP endpoint that answers like the fake, except for one call (number `fail_at`, or every call with
    `always`), which gets `how`: "500", "html" (200, not JSON), "sse" (a notification event, then the answer: fine),
    "text" (a reply with no structured content), "hang up" (no answer at all)."""

    def __init__(self, fake, fail_at=None, how="500", always=None):
        self.n = 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.n += 1
                p = req["params"]
                mode = always or (how if outer.n == fail_at else None)
                if mode == "hang up":
                    self.connection.close()
                    return
                if mode == "500":
                    self._send(500, "text/plain", b"boom")
                    return
                if mode == "html":
                    self._send(200, "text/html", b"<html>a captive portal</html>")
                    return
                try:
                    out = fake.tool(p["name"], p.get("arguments", {}))
                    res = {"content": [{"type": "text", "text": json.dumps(out)}], "structuredContent": out}
                    if mode == "text":
                        res = {"content": [{"type": "text", "text": "just words"}]}
                    if mode == "content object":
                        res = {"content": {"a": 1}}
                    if mode == "refused, no words":
                        res = {"isError": True}
                except LookupError as e:
                    res = {"content": [{"type": "text", "text": str(e)}], "isError": True}
                msg = {"jsonrpc": "2.0", "id": req["id"], "result": res}
                if mode == "empty error":
                    msg = {"jsonrpc": "2.0", "id": req["id"], "error": {}}
                if mode == "wrong id":
                    msg["id"] = req["id"] + 6
                if mode == "wrong id event":
                    body = f"id: 7\nevent: message\ndata: {json.dumps(dict(msg, id=req['id'] + 6))}\n\n"
                    self._send(200, "text/event-stream", body.encode())
                    return
                if mode == "no id":
                    msg.pop("id")
                if mode == "sse":
                    note = {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 1}}
                    body = f"event: message\ndata: {json.dumps(note)}\n\nevent: message\ndata: {json.dumps(msg)}\n\n"
                    self._send(200, "text/event-stream", body.encode())
                    return
                self._send(200, "application/json", json.dumps(msg).encode())

            def _send(self, code, ctype, body):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/mcp"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class ClientRefusesOddReplies(unittest.TestCase):
    def ask(self, how):
        srv = Canned(FakeHypnomix(), always=how)
        try:
            return CA.MCP(srv.url, timeout=3).ping()
        finally:
            srv.close()

    def test_http_error_says_the_status(self):
        with self.assertRaises(CA.MCPError) as cm:
            self.ask("500")
        self.assertIn("HTTP 500", str(cm.exception))
        self.assertNotIn("no answer from", str(cm.exception))

    def test_a_reply_that_is_not_json(self):
        with self.assertRaises(CA.MCPError) as cm:
            self.ask("html")
        self.assertIn("not MCP", str(cm.exception))

    def test_a_dropped_connection(self):
        with self.assertRaises(CA.MCPError) as cm:
            self.ask("hang up")
        self.assertIn("no answer", str(cm.exception))

    def test_an_event_stream_with_a_notification_before_the_answer(self):
        self.assertEqual(self.ask("sse")["name"], "Harbor")

    def test_an_answer_without_structured_content_is_an_error_not_a_crash(self):
        srv = Canned(FakeHypnomix(master_plugins=["Some Limiter"]), always="text")
        try:
            with self.assertRaises(CA.MCPError):
                CA.build_master(CA.MCP(srv.url, timeout=3), [dict(s) for s in PLAN], "bypass", route_id="99")
        finally:
            srv.close()

    def test_odd_but_json_replies_are_one_sentence_not_a_traceback(self):
        for how, words in (("content object", None), ("empty error", "without saying"),
                           ("refused, no words", "without saying"), ("wrong id", "no answer to the call"),
                           ("wrong id event", "no answer to the call")):
            srv = Canned(FakeHypnomix(), always=how)
            try:
                m = CA.MCP(srv.url, timeout=3)
                if words is None:
                    self.assertEqual(m.call("session_get_info"), "")          # no text: an empty answer, never a KeyError
                    continue
                with self.assertRaises(CA.MCPError, msg=how) as cm:
                    m.ping()
                self.assertIn(words, str(cm.exception), how)
            finally:
                srv.close()

    def test_an_answer_without_any_id_is_taken_only_when_it_is_the_only_one(self):
        self.assertEqual(self.ask("no id")["name"], "Harbor")

    def test_only_this_computer_is_ever_called(self):
        for url in ("http://example.com/mcp", "https://127.0.0.1:4820/mcp", "file:///etc/passwd",
                    "http://192.168.1.5:4820/mcp", "ftp://127.0.0.1/mcp", ""):
            with self.assertRaises(CA.MCPError, msg=url):
                CA.MCP(url)
        for url in ("http://127.0.0.1:4820/mcp", "http://localhost:4820/mcp", "http://[::1]:4820/mcp"):
            CA.MCP(url)

    def test_a_proxy_in_the_environment_is_never_used(self):
        import os
        import socket
        from unittest import mock
        stub = socket.socket()
        stub.bind(("127.0.0.1", 0))
        stub.listen(5)
        stub.settimeout(0.5)
        port = stub.getsockname()[1]
        env = {"HTTP_PROXY": f"http://127.0.0.1:{port}", "http_proxy": f"http://127.0.0.1:{port}"}
        try:
            with mock.patch.dict(os.environ, env):
                with self.assertRaises(CA.MCPError):
                    CA.MCP("http://127.0.0.1:9/mcp", timeout=2).ping()           # nothing listens on 9
            with self.assertRaises(socket.timeout):
                stub.accept()                                                    # the proxy was never contacted
        finally:
            stub.close()

    def test_a_bad_address_in_the_command_is_one_sentence(self):
        import contextlib
        import io
        a = type("A", (), dict(cmd="master", dry_run=False, mcp_url="http://example.com/mcp", bounce="b.wav"))()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                CA.main_ardour(a, lambda *x: ([], None))
        self.assertIn("on this computer", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
