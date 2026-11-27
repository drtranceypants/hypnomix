"""The Review view's A/B flip on the engine (review.js): B is never left in the engine behind the person's back.

The flip changes a track's fader / pan / mute (or its active playlist) and turns the master down by the measured
difference. These tests RUN util.js and review.js in macOS's JavaScriptCore (or Node.js) against a stand-in engine
that records every call, and check that A is put back before a Save or a scan (HX.endAuditions), when the view leaves
Review and when the page closes (kept-alive calls); that the master's level to come back to is read from the engine,
not from the view's own copy (which a refresh can fill with the turned-down value); that fast presses never overlap;
and that a switch that fails half-way puts A back. A real engine with a real A/B session was not used here."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import _jscheck

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "hypnomix" / "app" / "daw" / "js"

STAGE = r"""
var window = globalThis;
function setTimeout() { return 1; } function clearTimeout() {}
var performance = { now: function () { return 0; } };
var winL = {}; window.addEventListener = function (t, f) { (winL[t] = winL[t] || []).push(f); };
var document = { addEventListener: function () {}, querySelector: function () { return null; }, querySelectorAll: function () { return []; },
  activeElement: { tagName: 'BODY' }, createElement: function () { return { setAttribute: function () {}, append: function () {}, classList: { add: function () {} }, style: {} }; } };
"""

ENGINE = r"""
var log = [], beacons = [], toasts = [], masterDb = -2, failMute = false;
HX.S = { session: { name: 'Demo', master: { id: 'm', faderDb: -2 }, tracks: [] }, ui: { view: 'review' }, findings: [] };
HX.trackByName = function () { return null; }; HX.secToBeats = function (s) { return s; }; HX.bbtStr = function () { return ''; };
HX.toast = function (t) { toasts.push(t); }; HX.locate = function () {}; HX.select = function () {}; HX.liveEngine = { touch: function () {} };
HX.mcp = { connected: true, has: function () { return true; },
  call: function (name, args) {
    if (name === 'track_set_mute' && failMute && args.value === false && log.some(function (l) { return l.indexOf('track_set_fader_db t1 -3') === 0; }) && !log.some(function (l) { return l === 'FAILED'; })) { log.push('FAILED'); return Promise.reject(new Error('engine refused')); }
    log.push(name + ' ' + args.id + ' ' + (args.db != null ? args.db : args.position != null ? args.position : args.value));
    return Promise.resolve({}); },
  setFaderDb: function (id, db) { if (id === 'm') masterDb = db; log.push('master ' + db); return Promise.resolve({}); },
  trackInfo: function (id) { return Promise.resolve({ fader: { db: masterDb } }); },
  beacon: function (name, args) { if (args.id === 'm') masterDb = args.db; beacons.push(name + ' ' + args.id + ' ' + (args.db != null ? args.db : args.position != null ? args.position : args.value)); } };
HX.api = { inApp: true, post: function () { return Promise.resolve({}); }, get: function (u) {
  if (u.indexOf('/api/dawreview/state') === 0) return Promise.resolve({ connected: true, scanned: true, dir: 'd' });
  if (u.indexOf('/api/dawreview/findings') === 0) return Promise.resolve({ findings: [{ id: 'f1', at_s: null }, { id: 'f2', at_s: null }], decisions: {}, applied: [] });
  if (u.indexOf('/api/dawreview/abstate') === 0) return Promise.resolve({ built: true, open: true, items: {
    f1: { kind: 'mixer', trackId: 't1', match_db: 1.5, a: { fader_db: 0, pan: 0, mute: false }, b: { fader_db: -3, pan: 0, mute: false } },
    f2: { kind: 'mixer', trackId: 't2', match_db: 0, a: { fader_db: 0, pan: 0, mute: false }, b: { fader_db: 2, pan: 0, mute: false } } } });
  return Promise.resolve({}); } };
"""

BODY = r"""
var RR = HX.realReview;
function press(k) { RR.key({ key: k, preventDefault: function () {}, stopImmediatePropagation: function () {} }); }
async function settle() { for (var i = 0; i < 60; i++) await null; }
var out = {};
(async function () {
  await RR.refresh(true);
  /* 1. B, then a Save at once: A is back before the save goes on */
  press('b'); await HX.endAuditions('saving');
  out.save = log.slice(); out.saveMaster = masterDb; log = [];
  /* 2. the view's copy of the master was refreshed with the turned-down value: the base still comes from the engine */
  press('b'); await settle(); HX.S.session.master.faderDb = masterDb; log = [];
  press('j'); await settle();                       /* the next finding: A comes back on f1 */
  press('b'); await settle();                       /* f2's B: no trim; the master stays at the engine's base */
  out.stale = log.slice(); out.staleMaster = masterDb; log = [];
  await HX.endAuditions('saving'); log = [];
  /* 3. leaving Review puts A back */
  press('k'); await settle(); press('b'); await settle(); log = [];
  HX.emit('view', 'arrange'); await settle();
  out.leave = log.slice(); log = [];
  HX.S.ui.view = 'review';
  /* 4. fast presses never overlap: each switch ends before the next starts */
  press('b'); press('b'); press('b'); await settle();
  out.fast = log.slice(); log = [];
  /* 5. the page closes on B: the calls that put A back go out kept alive */
  (winL.pagehide || []).forEach(function (f) { f({}); });
  out.close = beacons.slice(); await settle(); log = [];
  /* 6. a switch that fails half-way puts A back */
  failMute = true; press('b'); await settle();
  out.fail = log.slice(); out.failToast = toasts[toasts.length - 1] || ''; out.failMaster = masterDb;
  print(JSON.stringify(out));
})().catch(function (e) { print(JSON.stringify({ error: String(e && e.stack || e) })); });
"""


def run_js(case, src):
    cmd = _jscheck.need_runner(case)
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "t.js"
        f.write_text(src, encoding="utf-8")
        r = subprocess.run(cmd + [str(f)], capture_output=True, text=True, timeout=60, encoding="utf-8")
    case.assertEqual(r.returncode, 0, r.stdout + r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])


class ABFlipIsPutBack(unittest.TestCase):
    def test_save_view_leave_page_close_base_and_overlap(self):
        src = STAGE + (JS / "util.js").read_text(encoding="utf-8") + "\n" + ENGINE + (JS / "review.js").read_text(encoding="utf-8") + "\n" + BODY
        r = run_js(self, src)
        self.assertNotIn("error", r, r.get("error"))
        A1 = ["track_set_fader_db t1 0", "track_set_pan t1 0.5", "track_set_mute t1 false"]
        B1 = ["track_set_fader_db t1 -3", "track_set_pan t1 0.5", "track_set_mute t1 false"]
        # 1. Save: B went in, then A came back (and the master to its base) before the save went on
        self.assertEqual(r["save"], B1 + ["master -3.5"] + A1 + ["master -2"])
        self.assertEqual(r["saveMaster"], -2)
        # 2. a stale view copy (-3.5) is never the base: f2's B leaves the master at the engine's -2
        self.assertEqual(r["stale"], A1 + ["master -2", "track_set_fader_db t2 2", "track_set_pan t2 0.5", "track_set_mute t2 false", "master -2"])
        self.assertEqual(r["staleMaster"], -2)
        # 3. leaving Review: A is put back
        self.assertEqual(r["leave"], A1 + ["master -2"])
        # 4. B, A, B pressed at once: three whole switches, one after another
        self.assertEqual(r["fast"], B1 + ["master -3.5"] + A1 + ["master -2"] + B1 + ["master -3.5"])
        # 5. the page closes while B plays: A goes out kept alive, the master to its base
        self.assertEqual(r["close"], A1 + ["track_set_fader_db m -2"])
        # 6. B fails half-way: A is put back and the person is told
        self.assertEqual(r["fail"], ["track_set_fader_db t1 -3", "track_set_pan t1 0.5", "FAILED"] + A1 + ["master -2"])
        self.assertIn("A is put back", r["failToast"])
        self.assertEqual(r["failMaster"], -2)

    def test_a_capped_match_says_the_measured_difference(self):
        body = r"""
var out = {
  plain: HX.abLevelText({ match_db: -3.25 }),
  louder: HX.abLevelText({ match_db: 1.5 }),
  capped: HX.abLevelText({ match_db: -12, level_db: -57.94, match_capped: true }) };
print(JSON.stringify(out));
"""
        src = STAGE + (JS / "util.js").read_text(encoding="utf-8") + "\n" + ENGINE + (JS / "review.js").read_text(encoding="utf-8") + "\n" + body
        r = run_js(self, src)
        self.assertTrue(r["plain"].startswith("A is 3.3 dB louder"), r)
        self.assertTrue(r["louder"].startswith("B is 1.5 dB louder"), r)
        self.assertTrue(r["capped"].startswith("A is 57.9 dB louder"), r)        # not "12 dB": that is only the cap
        self.assertIn("by 12 dB, the most it is", r["capped"])

    def test_the_hooks_are_one_list(self):
        util = (JS / "util.js").read_text(encoding="utf-8")
        self.assertIn("HX.onEnd = ", util)
        for f in ("assistant.js", "review.js"):
            src = (JS / f).read_text(encoding="utf-8")
            self.assertIn("HX.onEnd(", src, f)
            self.assertNotIn("HX.endAuditions = ", src, f)    # nobody replaces the list (load order would pick the winner)


if __name__ == "__main__":
    unittest.main()
