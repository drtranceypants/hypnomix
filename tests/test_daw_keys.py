"""The DAW view by keyboard and by modifier-click: the Session view's clip slots (one Tab stop, arrows, Enter / Space,
Delete) and selecting more than one track (shift-click a range, Cmd/Ctrl-click one more), which Group... ticks.

The behaviour is checked by RUNNING the page scripts (store.js, clips.js, groups.js) in macOS's JavaScriptCore or
Node.js against stand-ins for the page (a small fake DOM: elements, classes, attributes, listeners, focus); when neither
is here the test skips and says so. What a real browser does with the focus ring was looked at in a browser when this
was made; the static checks below hold the CSS to what was looked at."""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import _jscheck

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "hypnomix" / "app" / "daw" / "js"
CSS = ROOT / "hypnomix" / "app" / "daw" / "css" / "app.css"

FAKE_DOM = r"""
var print = (typeof print === 'function') ? print : function (s) { console.log(s); };
var window = (typeof globalThis !== 'undefined') ? globalThis : this;
function setTimeout(f, ms) { return 1; } function clearTimeout() {}
var performance = { now: function () { return 0; } };
var document = window.document = { activeElement: null, body: null,
  createElement: function (tag) { return new El(tag); }, createTextNode: function (t) { var n = new El('#text'); n.text = String(t); n.nodeType = 3; return n; },
  addEventListener: function (type, f) { (docL[type] = docL[type] || []).push(f); } };
var docL = {};
function El(tag) { this.tag = tag; this.nodeType = 1; this.cls = []; this.attrs = {}; this.dataset = {}; this.kids = []; this.parent = null; this.L = {};
  this.tabIndex = -1; this.hidden = false; var self = this;
  this.style = { setProperty: function (k, v) { self.style[k] = v; } };
  this.classList = { add: function () { for (var i = 0; i < arguments.length; i++) if (self.cls.indexOf(arguments[i]) < 0) self.cls.push(arguments[i]); },
    remove: function () { for (var i = 0; i < arguments.length; i++) { var j = self.cls.indexOf(arguments[i]); if (j >= 0) self.cls.splice(j, 1); } },
    contains: function (c) { return self.cls.indexOf(c) >= 0; },
    toggle: function (c, on) { if (on === undefined) on = !this.contains(c); if (on) this.add(c); else this.remove(c); return on; } }; }
El.prototype.append = function () { for (var i = 0; i < arguments.length; i++) { var k = arguments[i]; if (k == null) continue; if (typeof k === 'string') k = document.createTextNode(k); k.parent = this; this.kids.push(k); } };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); if (k === 'tabindex') this.tabIndex = +v; };
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.addEventListener = function (t, f) { (this.L[t] = this.L[t] || []).push(f); };
El.prototype.fire = function (t, e) { e = e || {}; e.target = e.target || this; e.type = t; var stop = false;
  e.stopPropagation = function () { stop = true; }; e.preventDefault = function () { e.defaultPrevented = true; };
  for (var n = this; n && !stop; n = n.parent) (n.L[t] || []).forEach(function (f) { f(e); });
  if (!stop) (docL[t] || []).forEach(function (f) { f(e); }); return e; };
El.prototype.click = function () { this.fire('click', {}); };
El.prototype.focus = function () { document.activeElement = this; this.fire('focusin', {}); };
El.prototype.scrollIntoView = function () {};
El.prototype.contains = function (n) { for (; n; n = n.parent) if (n === this) return true; return false; };
function matches(n, sel) { return sel.split(',').some(function (s) { s = s.trim(); if (s[0] === '.') return n.cls.indexOf(s.slice(1)) >= 0; return n.tag === s; }); }
El.prototype.closest = function (sel) { for (var n = this; n; n = n.parent) if (n.nodeType === 1 && matches(n, sel)) return n; return null; };
El.prototype.all = function (f, out) { out = out || []; this.kids.forEach(function (k) { if (k.nodeType === 1) { if (f(k)) out.push(k); k.all(f, out); } }); return out; };
El.prototype.querySelectorAll = function (sel) { return this.all(function (k) { return matches(k, sel); }); };
El.prototype.querySelector = function (sel) { return this.all(function (k) { return matches(k, sel); })[0] || null; };
Object.defineProperty(El.prototype, 'innerHTML', { set: function () { this.kids = []; }, get: function () { return ''; } });
Object.defineProperty(El.prototype, 'lastChild', { get: function () { return this.kids[this.kids.length - 1] || null; } });
document.body = new El('body');
var viewSession = new El('div'); document.body.append(viewSession);
var subs = {}, calls = [], toasts = [], confirmBody = null, keyboard = true;
var HX = window.HX = {
  h: function (sel, attrs) {
    var m = sel.match(/^([a-z0-9]+)?((?:[.#][\w-]+)*)$/i), el = document.createElement((m && m[1]) || 'div');
    if (m && m[2]) m[2].replace(/([.#])([\w-]+)/g, function (_, t, n) { if (t === '.') el.classList.add(n); else el.id = n; });
    if (attrs) for (var k in attrs) { var v = attrs[k]; if (v == null || v === false) continue;
      if (k === 'style') continue; else if (k.indexOf('on') === 0) el.addEventListener(k.slice(2), v); else el.setAttribute(k, v === true ? '' : v); }
    for (var i = 2; i < arguments.length; i++) { var a = [].concat(arguments[i]); a.forEach(function (x) { if (x != null && x !== false) el.append(x); }); }
    return el; },
  $: function (s) { return s === '#viewSession' ? viewSession : null; },
  $$: function (s, r) { return r ? r.all(function (k) { return k.cls.indexOf('col-h') >= 0 && k.attrs['data-tid']; }) : []; },
  on: function (ev, f) { (subs[ev] = subs[ev] || []).push(f); }, emit: function (ev, d) { (subs[ev] || []).forEach(function (f) { f(d); }); },
  onFrame: function () {}, bindDrag: function () {}, dragY: function () {}, fmtDb: function () { return '0'; }, fmtPan: function () { return 'C'; },
  dbToPos: function () { return 0; }, posToDb: function () { return 0; }, watchVisible: function () {}, toast: function (t) { toasts.push(t); },
  log: function () {}, keyboardFocus: function () { return keyboard; },
  modalOpen: function () { return false; }, editBlocked: function () { return ''; },
  confirm: function (title, body) { confirmBody = body; return Promise.resolve(false); },
  mcp: { connected: true, has: function () { return true; } }
};
HX.launch = function (tid, n) { calls.push('launch ' + tid + ' ' + n); };
HX.stopTrackClip = function (tid) { calls.push('stop ' + tid); };
HX.launchScene = function (n) { calls.push('scene ' + n); };
HX.cueClear = function (tid, n) { calls.push('clear ' + tid + ' ' + n); };
HX.cueDrop = function () {};
"""

TRACKS = r"""
function trk(id, name) { return { id: id, name: name, color: '#888', kind: 'audio', real: true, clips: [], devices: [], sends: [], faderDb: 0, pan: 0 }; }
HX.S.session = { tracks: [trk('a', 'Drums'), trk('b', 'Bass'), trk('c', 'Keys'), trk('d', 'Pad')], returns: [trk('r', 'Verb')], master: trk('m', 'Master') };
HX.S.session.master.isMaster = true; HX.S.session.returns[0].isReturn = true;
"""

ENGINE_CUES = r"""
/* the engine's cue slots: Drums has clips in slots 1 and 2, Bass in slot 1 */
var slots = { a: { 0: { slot: 0, name: 'Loop A', state: 'stopped' }, 1: { slot: 1, name: 'Loop B', state: 'running' } }, b: { 0: { slot: 0, name: 'Line', state: 'stopped' } } };
HX.cues = { rows: 3, error: '', available: function () { return true; }, columns: function () { return HX.S.session.tracks.slice(0, 3); },
  slot: function (tid, n) { return slots[tid] && slots[tid][n]; }, fraction: function () { return null; } };
"""


def run_js(case, body, files):
    cmd = _jscheck.need_runner(case)
    src = FAKE_DOM + "".join((JS / f).read_text(encoding="utf-8") + "\n" for f in files) + body
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "t.js"
        f.write_text(src, encoding="utf-8")
        r = subprocess.run(cmd + [str(f)], capture_output=True, text=True, timeout=60, encoding="utf-8")
    case.assertEqual(r.returncode, 0, r.stdout + r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])


GRID = r"""
var grid = viewSession.kids[0].kids[0];
function slots_() { return grid.all(function (k) { return k.cls.indexOf('slot') >= 0; }); }
function slot(key) { return slots_().filter(function (s) { return s.dataset.key === key; })[0]; }
function stops() { return slots_().filter(function (s) { return s.tabIndex === 0; }).map(function (s) { return s.dataset.key; }); }
function key(k, extra) { var e = Object.assign({ key: k, target: document.activeElement }, extra || {}); document.activeElement.fire('keydown', e); return e; }
"""


class CueSlotKeys(unittest.TestCase):
    FILES = ["store.js", "clips.js"]

    def test_one_tab_stop_arrows_follow_the_grid_enter_launches_delete_clears(self):
        r = run_js(self, TRACKS + ENGINE_CUES + r"""
HX.mountSession();
""" + GRID + r"""
var out = { n: slots_().length, firstStops: stops(), group: grid.attrs.role, gridName: grid.attrs['aria-label'] };
out.labels = [slot('a:0').attrs['aria-label'], slot('b:2').attrs['aria-label'], slot('a:1').attrs['aria-label']];
out.roles = slots_().every(function (s) { return s.attrs.role === 'button'; });
out.xOutOfTab = slot('a:0').querySelector('.cue-x').tabIndex;
slot('a:0').focus();
var moves = [];
key('ArrowRight'); moves.push(document.activeElement.dataset.key);         /* Bass, slot 1 */
key('ArrowDown'); moves.push(document.activeElement.dataset.key);          /* Bass, slot 2 */
key('ArrowRight'); key('ArrowRight'); moves.push(document.activeElement.dataset.key);   /* past Keys: the row's scene */
key('ArrowDown'); key('ArrowDown'); moves.push(document.activeElement.dataset.key);     /* under the last row: Stop all */
key('Home'); moves.push(document.activeElement.dataset.key);
key('PageUp'); moves.push(document.activeElement.dataset.key);
out.moves = moves; out.stopsAfter = stops();
var arrow = key('ArrowLeft'); out.arrowStopped = arrow.defaultPrevented;
slot('a:0').focus(); key('Enter'); key(' ');
key('Enter', { repeat: true });
slot('a:2').focus(); key('Enter');                                          /* empty: stops the track, as a click does */
slot('a:1').focus(); key('Delete');
slot('a:2').focus(); key('Backspace');                                      /* empty: nothing to clear */
out.calls = calls;
var pass = key('5'); out.digitPassed = !pass.defaultPrevented;
keyboard = false; calls = []; slot('a:0').focus(); var sp = key(' '); out.mouseSpace = { calls: calls.length, prevented: !!sp.defaultPrevented };
keyboard = true;
/* a poll that changes the grid draws it again: the focus and the Tab stop stay on the same slot */
slot('b:1').focus(); slots.c = { 1: { slot: 1, name: 'Chords', state: 'stopped' } }; HX.emit('cues-structure');
out.afterRedraw = { focus: document.activeElement.dataset.key, stops: stops(), inGrid: viewSession.kids[0].kids[0].contains(document.activeElement) };
print(JSON.stringify(out));
""", self.FILES)
        self.assertEqual(r["n"], 9)
        self.assertEqual(r["firstStops"], ["a:0"])
        self.assertEqual(r["group"], "group")
        self.assertIn("arrow keys", r["gridName"])
        self.assertEqual(r["labels"], ["Drums, slot 1, Loop A", "Bass, slot 3, empty", "Drums, slot 2, Loop B, playing"])
        self.assertTrue(r["roles"])
        self.assertEqual(r["xOutOfTab"], -1)
        self.assertEqual(r["moves"], ["b:0", "b:1", "scene:1", "stop:all", "stop:a", "a:0"])
        self.assertEqual(r["stopsAfter"], ["a:0"])
        self.assertTrue(r["arrowStopped"])
        self.assertEqual(r["calls"], ["launch a 0", "launch a 0", "stop a", "clear a 1"])
        self.assertTrue(r["digitPassed"])
        self.assertEqual(r["mouseSpace"], {"calls": 0, "prevented": False})
        self.assertEqual(r["afterRedraw"], {"focus": "b:1", "stops": ["b:1"], "inGrid": True})

    def test_scenes_stops_and_region_chips_by_keyboard(self):
        r = run_js(self, TRACKS + ENGINE_CUES + r"""
HX.S.session.tracks[1].clips = [{ id: 'rg1', name: 'Bass riff', real: true, kind: 'audio' }];
var puts = []; HX.cuePut = function (tid, n, rid) { puts.push(tid + ' ' + n + ' ' + rid); };
HX.stopAllClips = function () { calls.push('stop all'); };
HX.track = function (id) { return HX.S.session.tracks.filter(function (t) { return t.id === id; })[0]; };
HX.mountSession();
""" + GRID + r"""
function cellK(key) { return grid.all(function (k) { return k.dataset.key === key; })[0]; }
var out = {};
out.names = ['scene:0', 'stop:a', 'stop:all'].map(function (k) { var c = cellK(k); return [c.attrs.role, c.attrs['aria-label'], c.tabIndex]; });
cellK('scene:0').focus(); key('Enter');                       /* the row's scene */
cellK('stop:b').focus(); key(' ');                            /* Bass's stop button */
cellK('stop:all').focus(); key('Enter');
out.calls = calls.slice();
/* moving onto a track's slot selects the track, so the strip shows its regions */
slot('a:0').focus(); key('ArrowRight'); out.selected = HX.S.ui.trackId;
var strip = viewSession.kids[1];
var chip = strip.all(function (k) { return k.cls.indexOf('cue-chip') >= 0; })[0];
out.chip = [chip.tag, chip.attrs['aria-pressed'], chip.attrs['aria-label']];
chip.click();                                                 /* Enter on the chip: picked, and the focus goes back to the grid */
out.picked = chip.attrs['aria-pressed']; out.back = document.activeElement.dataset.key;
key('ArrowDown'); key('ArrowDown'); out.at = document.activeElement.dataset.key;
calls = []; key('Enter');                                     /* Enter on a slot with a region picked: put it there */
out.puts = puts; out.afterPut = calls;
print(JSON.stringify(out));
""", self.FILES)
        self.assertEqual(r["names"], [["button", "Launch scene 1, 2 clips", -1], ["button", "Stop the clip of Drums", -1], ["button", "Stop all clips", -1]])
        self.assertEqual(r["calls"], ["scene 0", "stop b", "stop all"])
        self.assertEqual(r["selected"], "b")
        self.assertEqual(r["chip"][0], "button")
        self.assertEqual(r["chip"][1], "false")
        self.assertIn("Enter picks it", r["chip"][2])
        self.assertEqual(r["picked"], "true")
        self.assertEqual(r["back"], "b:0")
        self.assertEqual(r["at"], "b:2")
        self.assertEqual(r["puts"], ["b 2 rg1"])
        self.assertEqual(r["afterPut"], [])                         # it put the region in; it did not launch or stop

    def test_the_demo_grid_answers_the_same_keys(self):
        r = run_js(self, TRACKS + r"""
HX.cues = { available: function () { return false; } };
HX.S.scenes = [{ name: 'Intro', len: 16, slots: [{ name: 'Beat', clipId: 'x1' }, null, null, null] }, { name: 'Verse', len: 16, slots: [null, { name: 'Line', clipId: 'x2' }, null, null] }];
HX.mountSession();
""" + GRID + r"""
var out = { stops: stops(), label: slot('a:0').attrs['aria-label'] };
slot('a:0').focus(); key('ArrowDown'); key('ArrowRight'); out.at = document.activeElement.dataset.key;
key('Enter'); key('Delete'); out.calls = calls; out.toasts = toasts;
print(JSON.stringify(out));
""", self.FILES)
        self.assertEqual(r["stops"], ["a:0"])
        self.assertEqual(r["label"], "Drums, slot 1 (Intro), Beat")
        self.assertEqual(r["at"], "b:1")
        self.assertEqual(r["calls"], ["launch b 1"])
        self.assertEqual(len(r["toasts"]), 1)

    def test_the_focus_ring_and_the_words(self):
        css = CSS.read_text(encoding="utf-8")
        m = re.search(r"\.slot:focus-visible\s*\{([^}]*)\}", css)
        self.assertIsNotNone(m, "the focused slot has its own ring")
        self.assertIn("outline: 2px solid var(--tx0)", m.group(1))      # the text colour: ~15:1 on the page in both themes
        self.assertIn("var(--bg0)", m.group(1))                          # a band of the page colour inside it, on any clip
        self.assertRegex(css, r"\.slot\.clip:focus-visible \.cue-x")
        wiki = (ROOT / "hypnomix" / "app" / "wiki" / "articles" / "18-daw.html").read_text(encoding="utf-8")
        app_md = (ROOT / "docs" / "APP.md").read_text(encoding="utf-8")
        self.assertIn("By keyboard:", wiki)
        self.assertIn("**By keyboard** the slots are one Tab stop", app_md)
        keys = (JS / "app.js").read_text(encoding="utf-8")
        self.assertIn("['Clear the focused slot', '⌫']", keys)


class TrackSelection(unittest.TestCase):
    FILES = ["store.js", "groups.js"]

    def test_shift_click_picks_a_range_cmd_click_toggles_and_group_ticks_them(self):
        r = run_js(self, TRACKS + r"""
var S = HX.S, out = {};
function ids() { return HX.selectedTrackIds().join(','); }
HX.select('a'); out.one = ids();
HX.selectClick({ shiftKey: true }, 'c'); out.range = ids(); out.focused = S.ui.trackId;
HX.selectClick({ shiftKey: true }, 'b'); out.shrink = ids();                       /* the range is from the last plain click */
HX.selectClick({ metaKey: true }, 'd'); out.add = ids();
HX.selectClick({ ctrlKey: true }, 'a'); out.toggleOff = ids();
HX.selectClick({ metaKey: true, shiftKey: true }, 'r'); out.addRange = ids();     /* ⌘⇧ adds the range from the anchor */
HX.selectClick({}, 'b'); out.plain = ids();
HX.selectClick({ metaKey: true }, 'b'); out.lastStays = ids();
HX.selectClick({ shiftKey: true }, 'm'); out.master = ids();                      /* the master is not in a range */
/* a press on a button or a value inside a header keeps a selection it is in (shift-drag on a fader is the fine drag) */
HX.select('a'); HX.selectClick({ shiftKey: true }, 'c');
var val = new El('span'); val.classList.add('val');
HX.selectPress({ shiftKey: true, target: val }, 'b'); out.pressKeeps = ids();
HX.selectPress({ shiftKey: true, target: val }, 'd'); out.pressOutside = ids();
/* the Mixer's fader and its pan / send knobs are drag controls too (shift = fine): a shift-press keeps the selection */
HX.select('a'); HX.selectClick({ shiftKey: true }, 'c');
var fader = new El('div'); fader.classList.add('fader'); var cap = new El('div'); fader.append(cap);
HX.selectPress({ shiftKey: true, target: cap }, 'b'); out.faderKeeps = ids();
var knob = new El('div'); knob.classList.add('knob');
HX.selectPress({ shiftKey: true, target: knob }, 'c'); out.knobKeeps = ids();
/* Group… ticks every selected track */
HX.select('b'); HX.selectClick({ metaKey: true }, 'd');
HX.groups.create();
var ticked = confirmBody.all(function (k) { return k.tag === 'input' && k.attrs.type === 'checkbox'; }).filter(function (k) { return k.checked; }).map(function (k) { return k.attrs.value; });
out.ticked = ticked.join(',');
HX.loadMock = null;
print(JSON.stringify(out));
""", self.FILES)
        self.assertEqual(r["one"], "a")
        self.assertEqual(r["range"], "a,b,c")
        self.assertEqual(r["focused"], "c")
        self.assertEqual(r["shrink"], "a,b")
        self.assertEqual(r["add"], "a,b,d")
        self.assertEqual(r["toggleOff"], "b,d")
        self.assertEqual(r["addRange"], "b,d,a,c,r")
        self.assertEqual(r["plain"], "b")
        self.assertEqual(r["lastStays"], "b")
        self.assertEqual(r["master"], "m")                 # not in a range: the master alone
        self.assertEqual(r["pressKeeps"], "a,b,c")
        self.assertEqual(r["pressOutside"], "d")
        self.assertEqual(r["faderKeeps"], "a,b,c")
        self.assertEqual(r["knobKeeps"], "a,b,c")
        self.assertEqual(r["ticked"], "b,d")

    def test_headers_strips_and_columns_use_it(self):
        for f, want in (("arrange.js", "HX.selectPress(e, t.id)"), ("mixer.js", "HX.selectPress(e, t.id)"), ("clips.js", "HX.selectClick(e, t.id)")):
            src = (JS / f).read_text(encoding="utf-8")
            self.assertIn(want, src, f)
            self.assertIn("HX.isTrackSelected(", src, f)
        self.assertIn("preselect || HX.selectedTrackIds()", (JS / "groups.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
