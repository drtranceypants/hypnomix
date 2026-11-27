"""In-Live A/B: the device script switches a simulated Live set, and the app matches loudness from the Main probe."""
import json, os, shutil, subprocess, tempfile, threading, time, unittest, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from tests import _jscheck

FAKE_LIVE = r"""
var SET = {tracks: [{name: "Vox", mute: 0, devices: [{name: "EQ Eight", on: 1}, {name: "Compressor", on: 1}, {name: "B · dev-1", on: 0}]},
                    {name: "Gtr", mute: 0, devices: []}, {name: "Gtr · B smooth-2", mute: 1, devices: []}],
           returns: [], main: {name: "Main", mute: 0, devices: []}};
function node(path) {
    var p = path.split(" "), t;
    if (p[0] == "live_set" && p.length == 1) return {kind: "song"};
    if (p[1] == "master_track") t = SET.main; else if (p[1] == "tracks") t = SET.tracks[parseInt(p[2])];
    else if (p[1] == "return_tracks") t = SET.returns[parseInt(p[2])];
    var rest = p[1] == "master_track" ? p.slice(2) : p.slice(3);
    if (!t) return null;
    if (!rest.length) return {kind: "track", t: t};
    var d = t.devices[parseInt(rest[1])];
    if (!d) return null;
    if (rest.length == 2) return {kind: "device", d: d};
    return {kind: "param", d: d};
}
function LiveAPI(path) {
    this.unquotedpath = path; this.n = node(path); this.id = this.n ? "1" : "0";
    this.getcount = function (what) { return what == "tracks" ? SET.tracks.length : SET.returns.length; };
    this.get = function (k) {
        if (k == "name") return [this.n.kind == "track" ? this.n.t.name : this.n.d.name];
        if (k == "value") return [this.n.d.on];
        if (k == "mute") return [this.n.t.mute];
    };
    this.set = function (k, v) { if (k == "value") this.n.d.on = v; if (k == "mute") this.n.t.mute = v; };
}
var mgraphics = {init: function () {}, redraw: function () {}};
function Task() { this.repeat = function () {}; this.cancel = function () {}; }
var posted = [];
function XMLHttpRequest() { this.open = function (m, u) { this.u = u; }; this.send = function (b) { posted.push([this.u, b]); }; }
"""

SPEC = {"id": "dev-1", "ab": {"set": "Song (A-B).als", "parts": [
    {"mode": "devices", "track": "Vox", "main": False, "a": [1], "a_on": [True], "b": [2], "b_on": [True]},
    {"mode": "tracks", "a": ["Gtr"], "b": ["Gtr · B smooth-2"], "a_on": [True], "b_on": [True]}]}}


class DeviceScript(unittest.TestCase):
    def run_js(self, body):
        runner = _jscheck.need_runner(self)
        from hypnomix.app import device as D
        js = FAKE_LIVE + D.JS.replace("__PORT__", "8791").replace("__W__", "430").replace("__H__", "169") + body
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.js"
            f.write_text(js, encoding="utf-8")
            r = subprocess.run(runner + [str(f)], capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_b_then_a_and_moving_on_restores_a(self):
        out = self.run_js("st.ready = true; st.cur = %s; setAB('B'); var b = JSON.stringify(SET);"
                          "setAB('A'); var a = JSON.stringify(SET); setAB('B'); st.cur = {id: 'other'}; abFollow();"
                          "print(JSON.stringify({b: JSON.parse(b), a: JSON.parse(a), after: SET, flash: st.flash}));" % json.dumps(SPEC))
        vox = lambda s: [d["on"] for d in s["tracks"][0]["devices"]]
        mutes = lambda s: [t["mute"] for t in s["tracks"]]
        self.assertEqual(vox(out["b"]), [1, 0, 1])          # EQ untouched, yours off, the B copy on
        self.assertEqual(mutes(out["b"]), [0, 1, 0])
        self.assertEqual(vox(out["a"]), [1, 1, 0])
        self.assertEqual(mutes(out["a"]), [0, 0, 1])
        self.assertEqual(vox(out["after"]), [1, 1, 0])     # leaving the finding puts A back
        self.assertEqual(mutes(out["after"]), [0, 0, 1])

    def test_refuses_a_set_that_is_not_the_ab_set(self):
        out = self.run_js("SET.tracks[0].devices[2].name = 'Limiter'; st.ready = true; st.cur = %s; setAB('B');"
                          "print(JSON.stringify({flash: st.flash, vox: SET.tracks[0].devices.map(function (d) { return d.on; })}));"
                          % json.dumps(SPEC))
        self.assertIn("not the A/B set", out["flash"])

    def test_blind_choice_is_posted_with_the_real_side(self):
        out = self.run_js("st.ready = true; st.cur = %s; Math.random = function () { return 0.9; }; blind(); choose('X');"
                          "print(JSON.stringify({posted: posted.map(function (p) { return [p[0], JSON.parse(p[1] || 'null')]; })}));"
                          % json.dumps(SPEC))
        blinds = [b for u, b in out["posted"] if u.endswith("/api/ab/blind")]
        self.assertEqual(blinds[0]["chose"], "B")          # random 0.9 → X is B
        self.assertEqual(blinds[0]["x"], "B")


class LoudnessMatch(unittest.TestCase):
    def test_b_is_matched_to_a_from_the_main_probe(self):
        from hypnomix.app import server as S
        from hypnomix.app.probe import Hub
        hub = Hub()
        S.PROBE["hub"] = hub
        try:
            S.AB.update(id="", state="A", acc={}, skip=0.0)
            S.ab_set_state("dev-1", "A")
            def feed(k, n):
                for i in range(n):
                    hub.on_block(1, "Main", 1, float(i), 1, 0.0, 0.0, 48000.0, *([k, k, k, k, k, k, k, 0, k * k, 0, 0, 0] + [0] * 8))
            feed(0.1, 40)
            S.ab_gain()
            time.sleep(0.01)
            S.ab_set_state("dev-1", "B")
            time.sleep(0.01)
            feed(0.2, 40)                                   # B is 6 dB louder
            g, diff = S.ab_gain()
            self.assertAlmostEqual(diff, -6.02, places=1)
            self.assertAlmostEqual(g, -6.02, places=1)     # turned down while B plays
            S.ab_set_state("dev-1", "A")
            self.assertEqual(S.ab_gain()[0], 0.0)           # A is never changed
            S.ab_set_state("dev-1", "B", match=False)
            self.assertEqual(S.ab_gain()[0], 0.0)
        finally:
            S.PROBE["hub"] = None
            S.AB.update(id="", state="A", acc={}, match=True, skip=0.6)


if __name__ == "__main__":
    unittest.main()
