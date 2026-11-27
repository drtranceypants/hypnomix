"""The DAW view's automation lanes and tempo track (js/automation.js): wired into the page and the Arrangement, every
gesture one engine call (one undo step), level moves kept to the smooth-automation rules by the drag itself, and what the
page would send accepted by the rules the app enforces (engineer/automation_rules.py)."""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from hypnomix.engineer import automation_rules as AR

DAW = Path(__file__).resolve().parents[1] / "hypnomix" / "app" / "daw"

STANDINS = r"""
var window = (typeof globalThis !== 'undefined') ? globalThis : this;
var handlers = {}, located = [], commits = [], toasts = [];
var tr = { id: 't1', name: 'Lead Vocal', kind: 'audio', role: 'vocal', real: true, color: '#c84', faderDb: 0, pan: 0, clips: [] };
var HX = window.HX = {
  S: { session: { name: 'Demo', tempo: 120, sampleRate: 48000, tracks: [tr], returns: [], master: null }, ui: { zoom: 10 } },
  h: function () { return { classList: { toggle: function () {} }, setAttribute: function () {}, append: function () {} }; },
  on: function (ev, f) { (handlers[ev] = handlers[ev] || []).push(f); }, emit: function () {}, log: function () {},
  mcp: { connected: false, tools: [], has: function () { return true; } }, arrange: {},
  track: function (id) { return id === 't1' ? tr : null; }, allTracks: function () { return [tr]; },
  select: function () {}, locate: function (b) { located.push(b); }, pos: function () { return 8; },
  toast: function (m) { toasts.push(m); }, modalOpen: function () { return false; }, renderArrangeHeaders: function () {},
  clamp: function (v, a, b) { return v < a ? a : v > b ? b : v; },
  dbToGain: function (db) { return db <= -192 ? 0 : Math.pow(10, db / 20); },
  secToBeats: function (s) { return s * 2; }, beatsToSec: function (b) { return b / 2; },
  fmtDb: function (d) { return (Math.round(d * 10) / 10).toFixed(1); }, fmtPan: function (p) { return String(p); },
  commit: function (label, ops) { commits.push({ label: label, op: ops[0] }); return Promise.resolve(); }
};
HX.dbToPos = function (db) { var g = HX.dbToGain(db); return g === 0 ? 0 : Math.pow((6 * Math.log2(g) + 192) / 198, 8); };
HX.posToDb = function (pos) { if (pos <= 0) return -193; var g = Math.pow(2, (Math.pow(pos, 1 / 8) * 198 - 192) / 6); return 20 * Math.log10(g); };
"""


def run_js(case, body):
    from tests import _jscheck
    cmd = _jscheck.need_runner(case)
    src = STANDINS + (DAW / "js" / "automation.js").read_text(encoding="utf-8") + "\n" + body
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "t.js"
        f.write_text(src, encoding="utf-8")
        r = subprocess.run(cmd + [str(f)], capture_output=True, text=True, timeout=60, encoding="utf-8")
    case.assertEqual(r.returncode, 0, r.stdout + r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])


# the mock vocal's fader lane: flat at 0 dB with points at 10 s and 20 s, a ride in between written as S-curves
SETUP = r"""
var A = HX.auto;
handlers.session.forEach(function (f) { f(); });
var d = A.data.t1;
d.lanes.gain = { points: [{ t: 10, v: 0 }, { t: 14, v: 0 }, { t: 20, v: 0 }], state: 'play' };
"""


class Wiring(unittest.TestCase):
    def test_the_page_loads_it_and_the_arrangement_hooks_it(self):
        html = (DAW / "index.html").read_text(encoding="utf-8")
        scripts = re.findall(r'<script src="(js/[^"]+)"', html)
        self.assertIn("js/automation.js", scripts)
        self.assertGreater(scripts.index("js/automation.js"), scripts.index("js/takes.js"))
        self.assertGreater(scripts.index("js/automation.js"), scripts.index("js/regions.js"))
        arr = (DAW / "js" / "arrange.js").read_text(encoding="utf-8")
        for needle in ("HX.auto.rows", "HX.auto.headers", "HX.auto.toggle", "HX.auto.drawLane", "HX.auto.drawTempo",
                       "HX.auto.pointerDown", "HX.auto.dblclick", "HX.auto.tempoRows", "HX.auto.tempoHeader", "#tempoBtn"):
            self.assertIn(needle, arr)
        for keep in ("#followBtn", "#importBtn", "data-hk", "'tk'"):      # the tours' ids and classes stay
            self.assertIn(keep, arr)
        reg = (DAW / "js" / "regions.js").read_text(encoding="utf-8")
        self.assertIn("if (h.done) await h.done(op, value, r);", reg)
        js = (DAW / "js" / "automation.js").read_text(encoding="utf-8")
        for needle in ("automation_list", "automation_get", "automation_write", "automation_clear", "automation_set_state",
                       "tempo_get_map", "'write automation'", "'clear automation'", "s_curve"):
            self.assertIn(needle, js)
        self.assertIsNone(re.search(r"""['"<]\s*\w*\s+on[a-z]+=["']""", js))      # no handler attributes
        self.assertNotIn("innerHTML", js)
        for line in js.splitlines():                                              # nothing after a // comment
            if "//" in line and "://" not in line:
                self.assertNotRegex(line.split("//", 1)[1], r"(;|\)\s*\{|=>)\s*$", line)
        css = (DAW / "css" / "app.css").read_text(encoding="utf-8")
        for sel in (".th.auto", ".th.tempo", ".tog.au.on", ".auto-state"):
            self.assertIn(sel, css)


class Gestures(unittest.TestCase):
    def test_the_s_curve_and_the_points_a_drag_takes(self):
        r = run_js(self, SETUP + r"""
var s = A.sCurve([{ t: 0, v: 0 }, { t: 1.2, v: -3 }]);
var dense = [{ t: 0, v: 0 }].concat(A.sCurve([{ t: 5, v: 0 }, { t: 6.2, v: -2.5 }])).concat([{ t: 9, v: -2.5 }, { t: 12, v: 0 }]);
var hair = [{ t: 7.7, v: 0 }, { t: 8.985, v: -3 }, { t: 9.034, v: -3 }, { t: 10, v: -2.8 }, { t: 11.65, v: -2.5 }, { t: 11.7, v: -2.5 }, { t: 12.9, v: 0 }];
var hairAn = A.anchors('gain', hair).map(function (i) { return hair[i].t; });
print(JSON.stringify({ hair: hairAn, n: s.length, mid: s[Math.floor(s.length / 2)].v, last: s[s.length - 1].v,
  an: A.anchors('gain', dense).map(function (i) { return dense[i].t; }), pan: A.anchors('pan_azimuth', dense).length, total: dense.length }));
""")
        self.assertEqual(r["n"], 25)                                  # 24 points over 1.2 s (one every 50 ms) plus the start
        self.assertAlmostEqual(r["mid"], -1.5, places=6)
        self.assertEqual(r["last"], -3)
        self.assertEqual(r["an"], [0, 5, 6.2, 9, 12])                 # where the line turns or is flat; not the S's own points
        self.assertEqual(r["pan"], r["total"])                        # any other lane: every point
        self.assertEqual(r["hair"], [7.7, 8.985, 11.65, 12.9])        # an S-curve's hair-thin ends are one handle

    def test_a_drag_stops_at_the_rules_and_sends_one_s_curve_write(self):
        r = run_js(self, SETUP + r"""
var far = A.propose(tr, 'gain', 1, 14, -9);
var steep = A.propose(tr, 'gain', 1, 10.4, -2);
var edge = A.propose(tr, 'gain', 0, 9, -4);
var trim = A.rules.reach('trim', 100);
print(JSON.stringify({ far: far, steep: steep, edge: edge, trim: trim }));
""")
        far = r["far"]
        self.assertAlmostEqual(far["v"], -3, places=6)                # held to 3 dB from both neighbours
        self.assertIn("at most 3 dB", far["held"])
        a = far["call"]["args"]
        self.assertEqual((far["call"]["tool"], a["curve"], a["mode"], a["start"], a["end"], a["guard"]),
                         ("automation_write", "s_curve", "replace-range", 9.9999, 20.0001, False))   # a hair past the outer points
        self.assertEqual([p["time"] for p in a["points"]], [10, 14, 20])
        steep = r["steep"]                                            # 0.4 s from the point before: under 7 dB/s at the S's peak
        self.assertLess(AR.rate(10, 10.4, steep["v"]), AR.MAX_SLOPE)
        self.assertLessEqual(abs(steep["v"]), 7 * 0.4 / (3.14159 / 2))
        self.assertEqual(r["edge"]["v"], 0)                            # the first point keeps its value (time only)
        self.assertIn("stay on the line", r["edge"]["held"])
        self.assertEqual(r["trim"], 4)
        line = AR.line_from({"pointList": [{"time": 10, "value": 0}, {"time": 14, "value": 0}, {"time": 20, "value": 0}]})
        self.assertEqual(AR.check(a, None, line), [])                  # what the page sends, the app's rules accept

    def test_add_remove_and_one_undo_step_each(self):
        r = run_js(self, SETUP + r"""
A.add(tr, 'gain', 12);
var add = commits[commits.length - 1];
d.lanes.gain = { points: [{ t: 10, v: 0 }, { t: 12, v: -2.5 }, { t: 14, v: 0 }, { t: 20, v: 0 }], state: 'play' };
A.remove(tr, 'gain', 1);
var rm = commits[commits.length - 1];
d.lanes.gain = { points: [{ t: 10, v: 0 }, { t: 12, v: 2 }, { t: 14, v: -3.5 }, { t: 20, v: -3.5 }], state: 'play' };
var n = commits.length;
A.remove(tr, 'gain', 1);
var refused = commits.length === n ? toasts[toasts.length - 1] : 'sent';
d.lanes.gain = { points: [{ t: 10, v: 0 }].concat(A.sCurve([{ t: 12, v: 0 }, { t: 13.2, v: -2 }])), state: 'play' };
A.remove(tr, 'gain', 3);
var inner = commits.length === n ? toasts[toasts.length - 1] : 'sent';
d.lanes.pan_azimuth = { points: [{ t: 3, v: -0.5 }], state: 'play' };
A.remove(tr, 'pan_azimuth', 0);
var pan = commits[commits.length - 1];
var H = HX.opHandlers.autoPoints;
H.apply(add.op, add.op.after);
print(JSON.stringify({ add: add, rm: rm, refused: refused, inner: inner, pan: pan.op.after.call,
  undo: [H.undo(add.op, add.op.after), H.undo(pan.op, pan.op.after)], state: HX.opHandlers.autoState.call({ trackId: 't1', key: 'gain' }, 'manual'),
  applied: d.lanes.gain.points.length }));
""")
        a = r["add"]["op"]["after"]["call"]["args"]
        self.assertEqual((a["points"], a["start"], a["end"], a["guard"]), ([{"time": 12, "value": 0}], 12, 12, False))
        line = AR.line_from({"pointList": [{"time": 10, "value": 0}, {"time": 20, "value": 0}]})
        self.assertEqual(AR.check(a, None, line), [])                  # one point on the line: allowed
        self.assertEqual(r["add"]["op"]["param"], "autoPoints")
        rm = r["rm"]["op"]["after"]["call"]["args"]
        self.assertEqual(([p["time"] for p in rm["points"]], rm["curve"], rm["start"], rm["end"], rm["guard"]),
                         ([10, 14], "s_curve", 9.9999, 14.0001, False))
        self.assertIn("at most 3 dB", r["refused"])                    # without the middle point the move would be 5.5 dB
        self.assertIn("where the line turns", r["inner"])               # a point inside an S-curve is not one to remove
        self.assertEqual(r["pan"]["tool"], "automation_clear")
        self.assertEqual(r["undo"], ["write automation", "clear automation"])
        self.assertEqual(r["state"], {"tool": "automation_set_state", "args": {"track_id": "t1", "control": "gain", "state": "manual"}})
        self.assertEqual(r["applied"], 4)

    def test_the_keyboard_picks_moves_adds_and_removes(self):
        r = run_js(self, SETUP + r"""
var ev = function (key, shift) { return { key: key, shiftKey: !!shift, target: 1, currentTarget: 1, preventDefault: function () {}, stopPropagation: function () {} }; };
A.keys(ev('ArrowRight'), tr, 'gain');
var sel1 = A.sel.i;
A.keys(ev('ArrowLeft'), tr, 'gain');
var sel0 = A.sel.i;
A.keys(ev('ArrowRight'), tr, 'gain');
A.keys(ev('ArrowDown'), tr, 'gain');
var down = commits[commits.length - 1].op.after.call.args;
A.keys(ev('a'), tr, 'gain');
var add = commits[commits.length - 1].op.after.call.args;
A.keys(ev('p'), tr, 'gain');
var st = commits[commits.length - 1].op;
print(JSON.stringify({ sel1: sel1, sel0: sel0, down: down, add: add, st: [st.param, st.after], located: located }));
""")
        self.assertEqual((r["sel1"], r["sel0"]), (0, 0))               # from the playhead (4 s here): the first point is next
        self.assertEqual([p["value"] for p in r["down"]["points"]], [0, -0.5, 0])
        self.assertEqual(r["add"]["points"][0]["time"], 4)            # at the playhead (beat 8 = 4 s)
        self.assertEqual(r["st"], ["autoState", "manual"])


class Tempo(unittest.TestCase):
    def test_the_tempo_track_shows_ramps(self):
        r = run_js(self, r"""
var A = HX.auto;
handlers.session.forEach(function (f) { f(); });
HX.mcp.connected = true; HX.mcp.tools = ['tempo_get_map'];
HX.mcp.call = function () { return Promise.resolve({ tempos: [
  { time: 0, bbt: { bar: 1 }, bpm: 100, bpmEnd: 140, ramped: true }, { time: 8.075, bbt: { bar: 5 }, bpm: 140, bpmEnd: 140, ramped: false }] }); };
A.tempo.shown = true;
A.loadTempo().then(function () {
  var rows = A.tempoRows();
  print(JSON.stringify({ pts: A.tempo.points, rows: rows.length, avail: A.tempoAvailable(), hgt: rows[0].hgt }));
});
""")
        self.assertEqual(r["rows"], 1)
        self.assertTrue(r["avail"])
        self.assertEqual([(p["bar"], p["bpm"], p["bpmEnd"], p["ramped"]) for p in r["pts"]], [(1, 100, 140, True), (5, 140, 140, False)])


class Proxy(unittest.TestCase):
    """The app's engine connection refuses a write the rules refuse under every name the engine takes for the tool."""

    def facts(self):
        return {"trackId": "9", "trackName": "Band", "isBus": True, "busOfGroup": None,
                "controls": [{"control": "gain", "current": 0.0}],
                "feeders": [{"trackId": "2", "name": "Lead Vocal", "routeType": "audio_track"},
                            {"trackId": "4", "name": "Drums", "routeType": "audio_track"}]}

    def refusal(self, name, control="gain"):
        from types import SimpleNamespace
        from hypnomix.app import daw as D
        reads = lambda url, tool, args: self.facts() if tool == "automation_list" else {"pointList": []}
        eng = SimpleNamespace(_read_tool=reads)
        body = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": name, "arguments": {
            "track_id": "9", "control": control, "curve": "s_curve",
            "points": [{"time": 1, "value": 0}, {"time": 2.2, "value": -2}]}}}).encode()
        return D.Engine.automation_refusal(eng, body, "http://127.0.0.1:1/mcp")

    def test_every_name_and_alias_is_checked(self):
        for name in ("automation_write", "automation/write", "automation.write"):
            self.assertIn("Drums", self.refusal(name), name)
        self.assertIn("Drums", self.refusal("automation_write", control="volume"))
        escaped = json.dumps({"method": "tools/call", "params": {"name": "automation_write"}}).replace("automation", "\\u0061utomation")
        from hypnomix.app import daw as D
        self.assertEqual(len(D._auto_writes(escaped.encode())), 1)
        self.assertEqual(self.refusal("automation_get"), "")


if __name__ == "__main__":
    unittest.main()
