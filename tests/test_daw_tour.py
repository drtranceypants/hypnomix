"""The guided tours inside the HypnoMix DAW (hypnomix/app/daw/js/tours.js: the data, tour.js: the engine, css/tour.css).

The repo has no JS runner, so: the data is read by running tours.js in macOS's JavaScriptCore (or Node when there is one)
and checked in Python; the engine (tour.js) runs there too, with a small stand-in for the page (the same way
tests/test_daw_assistant.py runs assistant.js). A test that needs a JS engine SKIPS, with a sentence, when there is none.
Driving the tours on a real page is done by hand (see the wiki article); these tests keep the parts that can break quietly:
a renamed control, a tour step with no target, a key that leaks into a DAW shortcut, a "Not now" that is forgotten.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hypnomix.app import daw as DW
from hypnomix.app import teacher as TE

ROOT = Path(DW.ROOT)
from tests import _jscheck


def js_runner():
    return _jscheck.runner()


# A page just big enough for the engine: an event bus (the real util.js), a session, and recorders for what it says and sends.
STANDINS = r"""
var print = (typeof print === 'function') ? print : function (s) { console.log(s); };
var window = (typeof globalThis !== 'undefined') ? globalThis : this;
var timers = [];
function setTimeout(f, ms) { timers.push(f); return timers.length; }
function clearTimeout() {}
function setInterval() { return 1; } function clearInterval() {}
var store = {};
var localStorage = { getItem: function (k) { return k in store ? store[k] : null; }, setItem: function (k, v) { store[k] = String(v); }, removeItem: function (k) { delete store[k]; } };
var navigator = { platform: 'MacIntel', userAgent: '' };
var location = { hash: '', pathname: '/daw/', search: '' };
var posts = [], gets = [], toasts = [];
var document = { activeElement: null, body: {}, querySelector: function () { return null; }, addEventListener: function () {}, removeEventListener: function () {},
                 createElement: function () { return {}; }, contains: function () { return true; } };
window.addEventListener = function () {}; window.removeEventListener = function () {};
"""

LOAD = r"""
window.HX = {};
%UTIL%
HX.tourManual = true;
HX.S = { ui: { view: 'arrange', clipId: null, trackId: 't1' }, session: { tracks: [], returns: [], master: null } };
HX.T = { playing: false };
HX.mode = 'demo';
HX.api = { inApp: true, get: function (u) { gets.push(u); return Promise.resolve({}); }, post: function (u, b) { posts.push([u, JSON.parse(JSON.stringify(b))]); return Promise.resolve({}); } };
HX.toast = function (t) { toasts.push(t); };
HX.setView = function (v) { HX.S.ui.view = v; HX.emit('view', v); };
HX.track = function () { return null; };
HX.allTracks = function () { return HX._tracks || []; };
%TOURS%
%TOUR%
var TR = HX.tour, K = TR._core;
// every target is on screen, with a box, unless a test says otherwise
var hidden = {};
K.env.find = function (sel) { return hidden[sel] ? null : { sel: sel }; };
var visibleReal = K.env.visible;
K.env.visible = function () { return true; };
K.env.rect = function () { return { left: 10, top: 10, right: 110, bottom: 60, width: 100, height: 50 }; };
var models = [], closed = 0, opened = 0;
TR._setUI({ open: function () { opened++; }, close: function () { closed++; }, cardEl: function () { return { contains: function () { return false; } }; },
            render: function (m, t) { models.push({ m: m, t: t }); } });
function last() { return models[models.length - 1]; }
"""


def page_src(body):
    util = (ROOT / "js" / "util.js").read_text(encoding="utf-8")
    tours = (ROOT / "js" / "tours.js").read_text(encoding="utf-8")
    tour = (ROOT / "js" / "tour.js").read_text(encoding="utf-8")
    return STANDINS + LOAD.replace("%UTIL%", util).replace("%TOURS%", tours).replace("%TOUR%", tour) + "\n" + body


def run_js(body):
    cmd = js_runner()
    if not cmd:
        raise unittest.SkipTest(_jscheck.NO_RUNNER)
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "t.js"
        f.write_text(page_src(body), encoding="utf-8")
        r = subprocess.run(cmd + [str(f)], capture_output=True, text=True, timeout=60, encoding="utf-8")
    if r.returncode:
        raise AssertionError(r.stdout + r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])


_DATA = None


def tours_data():
    """HX.TOURS (and the names of the engine's checks and resolvers) as JSON, from running the scripts."""
    global _DATA
    if _DATA is None:
        _DATA = run_js("print(JSON.stringify({ d: HX.TOURS, checks: Object.keys(TR.checks), resolvers: Object.keys(TR.resolvers) }));")
    return _DATA


class TheData(unittest.TestCase):
    def setUp(self):
        self.x = tours_data()
        self.d = self.x["d"]

    def test_every_target_is_a_control_that_is_in_the_page_or_made_by_a_named_function(self):
        """The manifest: each target says which file makes it and a piece of text that file must contain, so renaming a
        control (an id, a class, the function that builds it) fails here, not for a person in the middle of a tour."""
        problems = []
        for key, t in self.d["targets"].items():
            f = ROOT / t["file"]
            if not f.is_file():
                problems.append(f"{key}: no file {t['file']}")
                continue
            text = f.read_text(encoding="utf-8")
            if t["needle"] not in text:
                problems.append(f"{key}: {t['file']} no longer contains {t['needle']!r}")
            if "made" in t:
                fn = t["made"].split(".")[-1]
                if not re.search(r"(function\s+%s\b|%s\s*=\s*function|%s\s*=\s*\(|HX\.%s\s*=)" % ((re.escape(fn),) * 4), text):
                    problems.append(f"{key}: {t['file']} has no function {t['made']}")
            elif t["file"] != "index.html":
                problems.append(f"{key}: a control made by a script must say which function makes it (made)")
            if "resolver" in t and t["resolver"] not in self.x["resolvers"]:
                problems.append(f"{key}: no resolver {t['resolver']}")
            sel = t["sel"]
            m = re.match(r"^#([\w-]+)", sel)
            if t["file"] == "index.html" and m and f'id="{m.group(1)}"' not in text:
                problems.append(f"{key}: index.html has no id {m.group(1)}")
        self.assertEqual(problems, [])

    def test_every_target_is_used_and_every_step_names_a_target_that_exists(self):
        used = set()
        for tour in self.d["tours"]:
            for st in tour["steps"]:
                for k in ([] if not st.get("target") else st["target"] if isinstance(st["target"], list) else [st["target"]]):
                    self.assertIn(k, self.d["targets"], f"{tour['id']}/{st['id']}: unknown target {k}")
                    used.add(k)
                for k in ([] if not st.get("then") else st["then"] if isinstance(st["then"], list) else [st["then"]]):
                    self.assertIn(k, self.d["targets"], f"{tour['id']}/{st['id']}: unknown 'then' target {k}")
                    self.assertTrue(st.get("wait"), f"{tour['id']}/{st['id']}: 'then' is where a step points once its wait is done")
                    used.add(k)
        self.assertEqual(sorted(set(self.d["targets"]) - used - {"gate", "engine"}), [], "targets no step points at (the gate and the engine button are the pause screens')")

    def test_tours_and_steps_are_well_formed(self):
        ids = [t["id"] for t in self.d["tours"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[:6], ["first-look", "edit-region", "mix", "scan-review", "ask-assistant", "save-export"])
        self.assertTrue(all(re.match(r"^[a-z0-9][a-z0-9-]{0,39}$", i) for i in ids), "the server keeps only ids of this shape")
        first = self.d["tours"][0]
        self.assertIn(len(first["steps"]), (9, 10, 11), "the first look is about ten steps")
        for tour in self.d["tours"]:
            self.assertTrue(3 <= len(tour["title"]) <= 30)
            self.assertTrue(20 <= len(tour["blurb"]) <= 200, tour["id"])
            self.assertTrue(1 <= tour["minutes"] <= 10)
            sids = [s["id"] for s in tour["steps"]]
            self.assertEqual(len(sids), len(set(sids)), f"{tour['id']}: step ids repeat")
            self.assertTrue(5 <= len(sids) <= 12, tour["id"])
            for st in tour["steps"]:
                where = f"{tour['id']}/{st['id']}"
                self.assertTrue(4 <= len(st["title"]) <= 50, where)
                self.assertTrue(1 <= len(st["say"]) <= 2, f"{where}: one or two sentences' worth, short")
                self.assertTrue(all(10 <= len(p) <= 260 for p in st["say"]), where)
                self.assertTrue(sum(len(p) for p in st["say"]) <= 400, where)
                if st.get("target"):
                    self.assertTrue(st.get("missing") and 20 <= len(st["missing"]) <= 220, f"{where}: a target needs 'missing': what to open when it is not there")
                else:
                    self.assertTrue(st.get("reason"), f"{where}: no target and no reason")
                    self.assertNotIn("wait", st, f"{where}: a step that points at nothing cannot wait for a control")
                if st.get("wait"):
                    self.assertIn(st["wait"], self.x["checks"], f"{where}: waits for a check the engine does not have")
                    self.assertTrue(st.get("doing") and len(st["doing"]) <= 160, f"{where}: a waiting step says what to do")
                    self.assertLessEqual(len(st.get("done", "")), 200, where)
                if st.get("view"):
                    self.assertIn(st["view"], ("arrange", "session", "mixer", "review"), where)
                if st.get("busy"):
                    self.assertIn(st["busy"], st["target"], f"{where}: 'busy' names one of the step's own targets")
                if st.get("demoSay"):
                    self.assertTrue(1 <= len(st["demoSay"]) <= 2 and all(10 <= len(p) <= 260 for p in st["demoSay"]), where)
                    self.assertTrue(sum(len(p) for p in st["demoSay"]) <= 400, where)
                    self.assertEqual(st["demoSay"][0].count("**") % 2, 0, where)
                if st.get("chords"):
                    self.assertTrue(st.get("wait"), f"{where}: a chord is for a step that waits for something to be done")
                    self.assertTrue(all(isinstance(c, str) and re.match(r"^[a-z0-9]$", c) for c in st["chords"]), where)
                    self.assertIn("{mod}", st["doing"], f"{where}: the line that asks for the chord names it")
            last = tour["steps"][-1]
            if tour["id"] in ("edit-region", "mix", "scan-review"):
                self.assertFalse(last.get("target"), "these end on a closing step")

    def test_every_check_is_used_and_nothing_else_is_named(self):
        used = {st["wait"] for t in self.d["tours"] for st in t["steps"] if st.get("wait")}
        self.assertEqual(sorted(set(self.x["checks"]) - used), [], "a check no step waits for")

    def test_words(self):
        """House voice: plain, no em dashes, the product is HypnoMix and the DAW is the HypnoMix DAW, no other product named."""
        text = json.dumps(self.d, ensure_ascii=False)
        self.assertNotIn("—", text)
        self.assertNotIn("Hypnomix", text.replace("hypnomix.", ""), "visible text spells the product HypnoMix")
        self.assertIn("HypnoMix DAW", text)
        from tests.test_repo_rules import names_in          # the repository's own list of names that must not appear (kept as fingerprints)
        self.assertEqual(names_in(text), set(), "a product, hardware, artist or song name is in the tour text")
        # the first time a term shows in bold it is explained in the same step: every bold word is followed by sentence text
        for t in self.d["tours"]:
            for st in t["steps"]:
                for p in st["say"]:
                    self.assertEqual(p.count("**") % 2, 0, f"{t['id']}/{st['id']}: unbalanced **")

    def test_the_first_offer_and_the_toasts_do_not_send_people_to_a_button_that_may_be_off_screen(self):
        """A narrow window scrolls the top bar sideways: the words name the ? key (which opens the list with a Take a tour
        button) as well as the Tour button, never only 'at the top right'."""
        ui = self.d["ui"]
        for k in ("offerText", "declined", "finished"):
            self.assertIn("?", ui[k], k)
            self.assertNotIn("top right", ui[k], k)

    def test_the_teacher_glossary_words_are_used_the_same_way(self):
        """The tours reuse the lessons' words: the plain meanings of these terms must still be the ones the tours rely on."""
        g = {x["term"].lower(): x["entries"][0]["meaning"] for x in TE.glossary("live")}
        for term, hint in (("track", "one lane"), ("region", "piece of recording"), ("fader", "volume"), ("pan", "left and right"),
                           ("fade", "level"), ("send", "return"), ("snapshot", None)):
            if term in g and hint:
                self.assertIn(hint, g[term].lower(), term)


class TheEngine(unittest.TestCase):
    def test_next_back_skip_and_the_progress_that_follows(self):
        r = run_js(r"""
var out = {};
TR.start('first-look');
out.first = { i: last().m.i, n: last().m.n, back: last().m.canBack, label: last().m.nextLabel };
TR.next(); TR.next();
out.third = { i: last().m.i, title: last().m.title, view: HX.S.ui.view };
TR.back();
out.backTo = last().m.i;
out.at = TR.state().at['first-look'];
TR.end('skipped');
out.afterSkip = { open: TR.isOpen(), active: TR.state().active, at: TR.state().at['first-look'], done: TR.state().done.slice(), closed: closed };
// walk a whole tour: the last step says Finish, and finishing marks it done and forgets where it was
TR.start('edit-region'); var n = last().m.n; for (var i = 0; i < n - 1; i++) TR.next();
out.lastLabel = last().m.nextLabel; TR.next();
out.finished = { open: TR.isOpen(), done: TR.state().done, at: TR.state().at['edit-region'], toast: toasts[toasts.length - 1] };
print(JSON.stringify(out));
""")
        self.assertEqual(r["first"], {"i": 0, "n": 10, "back": False, "label": "I’ll do it later"})
        self.assertEqual((r["third"]["i"], r["third"]["title"]), (2, "The timeline and its regions"))
        self.assertEqual(r["backTo"], 1)
        self.assertEqual(r["at"], 1)
        self.assertEqual(r["afterSkip"], {"open": False, "active": "", "at": 1, "done": [], "closed": 1})
        self.assertEqual(r["lastLabel"], "Finish")
        self.assertEqual(r["finished"]["open"], False)
        self.assertEqual(r["finished"]["done"], ["edit-region"])
        self.assertIsNone(r["finished"].get("at"))
        self.assertIn("Tour finished: Edit a region", r["finished"]["toast"])

    def test_a_step_waits_for_the_thing_to_be_done_and_next_is_always_there(self):
        r = run_js(r"""
var out = {};
TR.start('first-look');
out.waiting = { status: last().m.status, next: last().m.nextLabel, canNext: last().m.canNext, doing: last().m.doing };
HX.emit('transport');                                   // nothing is playing yet: not it
out.stillWaiting = last().m.status;
HX.T.playing = true; HX.emit('transport');
out.done = { status: last().m.status, next: last().m.nextLabel };
// an action step: only the right kind of edit counts
TR.end('x'); TR.start('edit-region'); TR.next(); TR.next(); TR.next();   // select, move, trim, split
out.split = last().m.title; out.splitStatus = last().m.status;
HX.emit('edit', { ops: [{ param: 'regionMove' }] }); out.afterMove = last().m.status;
HX.emit('edit', { ops: [{ param: 'regionSplit' }] }); out.afterSplit = last().m.status;
// "I'll do it later": Next moves on without it
TR.next(); out.moved = { title: last().m.title, status: last().m.status };
// a state check counts when it is already so (the mixer is open)
TR.end('x'); HX.S.ui.view = 'mixer'; TR.start('mix');
out.alreadyMixer = last().m.status;
print(JSON.stringify(out));
""")
        self.assertEqual(r["waiting"], {"status": "waiting", "next": "I’ll do it later", "canNext": True, "doing": r["waiting"]["doing"]})
        self.assertIn("Press play", r["waiting"]["doing"])
        self.assertEqual(r["stillWaiting"], "waiting")
        self.assertEqual(r["done"], {"status": "done", "next": "Next"})
        self.assertEqual((r["split"], r["splitStatus"]), ("Split it in two", "waiting"))
        self.assertEqual((r["afterMove"], r["afterSplit"]), ("waiting", "done"))
        self.assertEqual(r["moved"], {"title": "Fade the edges", "status": "waiting"})
        self.assertEqual(r["alreadyMixer"], "done")

    def test_a_device_added_is_noticed_by_counting_devices_and_an_edit_of_a_knob_by_its_kind(self):
        r = run_js(r"""
var out = {}, tracks = [{ devices: [1, 2] }];
HX._tracks = tracks;
TR.start('mix'); for (var i = 0; i < 5; i++) TR.next();             // open, fader, pan, mute-solo, send, add-device
out.step = last().m.title;
HX.emit('devices'); out.same = last().m.status;                      // the chain was drawn again, nothing added
tracks[0].devices.push(3); HX.emit('devices'); out.added = last().m.status;
TR.next(); out.knob = last().m.title; HX.emit('edit', { ops: [{ param: 'fader' }] }); out.faderIsNotAKnob = last().m.status;
HX.emit('edit', { ops: [{ param: 'devParam' }] }); out.turned = last().m.status;
print(JSON.stringify(out));
""")
        self.assertEqual((r["step"], r["same"], r["added"]), ("Add an effect", "waiting", "done"))
        self.assertEqual((r["knob"], r["faderIsNotAKnob"], r["turned"]), ("Turn a knob", "waiting", "done"))

    def test_the_view_is_switched_for_a_step_and_the_card_says_so(self):
        r = run_js(r"""
var out = {};
TR.start('first-look'); TR.next(); TR.next(); TR.next();             // transport, tracks, timeline, mixer
out.mixer = { view: HX.S.ui.view, note: last().m.note };
TR.next(); TR.next(); TR.next();                                     // devices, browser, review
out.review = { view: HX.S.ui.view, note: last().m.note };
print(JSON.stringify(out));
""")
        self.assertEqual(r["mixer"], {"view": "mixer", "note": "Switched to the Mixer view for this step."})
        self.assertEqual(r["review"], {"view": "review", "note": "Switched to the Review view for this step."})

    def test_a_target_that_cannot_be_found_says_what_to_open(self):
        r = run_js(r"""
var out = {};
hidden['#browser'] = true;
TR.start('first-look'); for (var i = 0; i < 5; i++) TR.next();       // the browser
out.missing = { kind: last().t.kind, rect: last().t.rect, note: last().m.note };
hidden['#browser'] = false; K.refresh(true);
out.found = { kind: last().t.kind, note: last().m.note };
// a view-bound target that is in another view also says to open it
TR.end('x'); hidden['#viewReview .rv-empty .btn.ai'] = true; hidden['#viewReview .rv-empty .rv-actions .btn.primary'] = true; hidden['#viewReview .rv-empty:has(.scanbar)'] = true;
TR.start('scan-review'); TR.next(); HX.S.ui.view = 'mixer';          // the scan step wants Review; the person went away
HX.S.ui.view = 'mixer'; K.refresh(true);
out.otherView = last().m.note;
print(JSON.stringify(out));
""")
        self.assertEqual(r["missing"]["kind"], "missing")
        self.assertIsNone(r["missing"]["rect"])
        self.assertIn("hidden because this window is narrow", r["missing"]["note"])
        self.assertIn("⌘Alt+B", r["missing"]["note"])
        self.assertEqual(r["found"], {"kind": "ok", "note": ""})
        self.assertIn("Open the Review view", r["otherView"])

    def test_resume_from_stored_progress_and_not_now_is_remembered(self):
        r = run_js(r"""
var out = {};
// a tour was open on step 4 of the mix when the page was left
store['hx.tour'] = JSON.stringify({ offered: 'accepted', done: ['first-look'], at: { mix: 3 }, active: 'mix' });
K.setPage(K.readLocal());
out.decision = K.decide(false);
K.act(K.decide(false));
out.resumed = { tour: TR.current().tour, step: TR.current().step, spoken: null };
TR.end('x');
// never answered: the offer. "Not now" is kept in this browser at once, and sent to the app at once
K.setPage(K.sane(null)); out.fresh = K.decide(false);
posts.length = 0;
K.answer('declined');
out.saved = JSON.parse(store['hx.tour']).offered;
out.posted = posts.filter(function (p) { return p[0] === '/api/teach/tour'; }).map(function (p) { return p[1].offered; });
K.setPage(K.readLocal()); out.next = K.decide(false);          // the next visit
out.asked = K.decide(true);                                     // #tour in the address: the list
// the server's copy joins the browser's: an answer on either side is kept
K.setPage(K.sane({ offered: '', done: ['mix'], at: {} }));
K.merge(K.sane({ offered: 'declined', done: ['first-look'], at: { 'scan-review': 2 } }));
out.merged = TR.state();
// garbage is dropped
out.clean = K.sane({ offered: 'maybe', done: ['nope', 'mix', 5], at: { mix: -1, 'edit-region': 3, ghost: 2 }, active: 'ghost' });
print(JSON.stringify(out));
""")
        self.assertEqual(r["decision"], "resume")
        self.assertEqual((r["resumed"]["tour"], r["resumed"]["step"]), ("mix", 3))
        self.assertEqual(r["fresh"], "offer")
        self.assertEqual(r["saved"], "declined")
        self.assertEqual(r["posted"], ["declined"])
        self.assertEqual((r["next"], r["asked"]), ("none", "list"))
        self.assertEqual(r["merged"]["offered"], "declined")
        self.assertEqual(sorted(r["merged"]["done"]), ["first-look", "mix"])
        self.assertEqual(r["merged"]["at"], {"scan-review": 2})
        self.assertEqual(r["clean"], {"offered": "", "done": ["mix"], "at": {"edit-region": 3}, "active": ""})

    def test_it_pauses_without_a_session_or_an_engine_and_carries_on_by_itself(self):
        r = run_js(r"""
var out = {};
HX.mode = 'noengine';
TR.start('first-look');
out.gate = { status: last().m.status, title: last().m.title, note: last().m.note, kind: last().t.kind, canNext: last().m.canNext, view: HX.S.ui.view };
TR.next(); out.stuck = last().m.i;                                // Next does nothing while there is nothing to point at
HX.mode = 'demo'; HX.emit('mode', 'demo'); K.refresh(false);
out.resumed = { status: last().m.status, title: last().m.title };
// the engine stops answering mid-tour
HX.emit('engine', 'lost'); K.refresh(false);
out.lost = { status: last().m.status, note: last().m.note };
HX.emit('engine', 'ok'); K.refresh(false);
out.back = last().m.status;
HX.engineLost = true; K.refresh(false); out.engineLost = last().m.status;
print(JSON.stringify(out));
""")
        self.assertEqual(r["gate"]["status"], "paused")
        self.assertEqual(r["gate"]["kind"], "paused")
        self.assertIn("Practice with the demo song", r["gate"]["note"])
        self.assertFalse(r["gate"]["canNext"])
        self.assertEqual(r["stuck"], 0)
        self.assertEqual(r["resumed"], {"status": "waiting", "title": "The transport"})
        self.assertEqual(r["lost"]["status"], "paused")
        self.assertIn("carries on by itself", r["lost"]["note"])
        self.assertEqual(r["back"], "waiting")
        self.assertEqual(r["engineLost"], "paused")

    def test_the_tour_never_changes_the_session_or_calls_the_engine(self):
        r = run_js(r"""
var out = {}, commits = 0, edits = 0;
HX.commit = function () { commits++; }; HX.edit = function () { edits++; };
HX.mcp = { call: function () { commits++; } };
var before = JSON.stringify(HX.S);
TR.start('first-look'); for (var i = 0; i < 12; i++) TR.next();
TR.start('mix'); for (var i = 0; i < 12; i++) TR.next();
out.calls = [commits, edits]; out.posts = posts.map(function (p) { return p[0]; }).filter(function (u, i, a) { return a.indexOf(u) === i; });
out.session = JSON.stringify(HX.S.session) === JSON.stringify(JSON.parse(before).session);
print(JSON.stringify(out));
""")
        self.assertEqual(r["calls"], [0, 0])
        self.assertEqual(r["posts"], ["/api/teach/tour"], "the only call is its own progress")
        self.assertTrue(r["session"])

    def test_escape_ends_it_arrows_move_it_and_a_key_in_the_card_never_reaches_a_shortcut(self):
        r = run_js(r"""
var out = {};
function key(k, inCard, extra) {
  var e = Object.assign({ key: k, target: {}, stopped: false, prevented: false, shiftKey: false,
    preventDefault: function () { this.prevented = true; }, stopPropagation: function () { this.stopped = true; } }, extra || {});
  TR._setUI({ open: function () {}, close: function () { closed++; }, cardEl: function () { return { contains: function () { return inCard; } }; },
              render: function (m, t) { models.push({ m: m, t: t }); } });
  K.onKey(e); return e;
}
TR.start('first-look');
var e1 = key('ArrowRight', true); out.right = { step: TR.current().step, stopped: e1.stopped };
var e2 = key('ArrowLeft', true); out.left = TR.current().step;
var e3 = key('m', true); out.letter = { stopped: e3.stopped, prevented: e3.prevented };        // never a DAW shortcut; Enter and Space still press the button
var e4 = key('ArrowRight', false); out.outside = { step: TR.current().step, stopped: e4.stopped };   // out in the DAW the arrows are the DAW's
var e5 = key('Escape', true); out.escape = { open: TR.isOpen(), stopped: e5.stopped };
TR.start('mix');
HX.modalOpen = function () { return true; };
var e6 = key('Escape', false); out.dialog = TR.isOpen();                                       // a dialog that is open keeps its own Escape
print(JSON.stringify(out));
""")
        self.assertEqual(r["right"], {"step": 1, "stopped": True})
        self.assertEqual(r["left"], 0)
        self.assertEqual(r["letter"], {"stopped": True, "prevented": False})
        self.assertEqual(r["outside"], {"step": 0, "stopped": False})
        self.assertEqual(r["escape"], {"open": False, "stopped": True})
        self.assertTrue(r["dialog"])

    def test_a_shortcut_the_step_asks_for_passes_out_of_the_card_and_nothing_else_does(self):
        r = run_js(r"""
var out = {};
function key(k, extra) {
  var e = Object.assign({ key: k, target: {}, stopped: false, prevented: false, shiftKey: false, metaKey: false, ctrlKey: false, altKey: false,
    preventDefault: function () { this.prevented = true; }, stopPropagation: function () { this.stopped = true; } }, extra || {});
  TR._setUI({ open: function () {}, close: function () {}, cardEl: function () { return { contains: function () { return true; } }; }, render: function (m, t) { models.push({ m: m, t: t }); } });
  K.onKey(e); return e.stopped;
}
TR.start('edit-region'); for (var i = 0; i < 5; i++) TR.next();            // select, move, trim, split, fade, undo
out.step = last().m.title;
out.undoMeta = key('z', { metaKey: true }); out.undoCtrl = key('Z', { ctrlKey: true, shiftKey: true });
out.otherChord = key('s', { metaKey: true }); out.plainZ = key('z'); out.altChord = key('z', { metaKey: true, altKey: true });
TR.back(); TR.back();                                                      // the split step asks for {mod}E, not for {mod}Z
out.splitStep = last().m.title; out.splitE = key('e', { metaKey: true }); out.splitZ = key('z', { metaKey: true });
print(JSON.stringify(out));
""")
        self.assertEqual(r["step"], "Undo anything")
        self.assertFalse(r["undoMeta"])
        self.assertFalse(r["undoCtrl"])
        self.assertTrue(r["otherChord"])
        self.assertTrue(r["plainZ"])
        self.assertTrue(r["altChord"])
        self.assertEqual(r["splitStep"], "Split it in two")
        self.assertFalse(r["splitE"])
        self.assertTrue(r["splitZ"])

    def test_a_target_squeezed_to_nothing_is_not_visible(self):
        r = run_js(r"""
var out = {};
window.getComputedStyle = function () { return { visibility: 'visible', display: 'block' }; };
function el(w, h) { return { getClientRects: function () { return [1]; }, getBoundingClientRect: function () { return { width: w, height: h }; } }; }
out.zero = visibleReal(el(0, 20)); out.thin = visibleReal(el(2, 20)); out.ok = visibleReal(el(60, 20)); out.none = visibleReal(null);
print(JSON.stringify(out));
""")
        self.assertEqual(r, {"zero": False, "thin": False, "ok": True, "none": False})

    def test_a_scan_that_is_running_says_so_and_a_finished_step_drops_its_stale_notes(self):
        r = run_js(r"""
var out = {};
// the scan's own start buttons are gone and its progress bar is there
hidden['#viewReview .rv-empty .btn.ai'] = true; hidden['#viewReview .rv-empty .rv-actions .btn.primary'] = true;
HX.S.ui.view = 'mixer';
TR.start('scan-review'); TR.next();                                  // open Review, then the scan step
out.step = last().m.title; out.view = HX.S.ui.view;
out.running = { key: last().t.key, note: last().m.note };
// nothing running and the findings already there: the old "already has findings" note
hidden['#viewReview .rv-empty:has(.scanbar)'] = true; K.refresh(true);
out.already = last().m.note;
// the scan finishes: the findings are lit, and the card has no note at all
hidden['#viewReview .rv-empty:has(.scanbar)'] = false; K.refresh(true);
HX.emit('review', { what: 'scanned' });
out.done = { status: last().m.status, key: last().t.key, note: last().m.note };
print(JSON.stringify(out));
""")
        self.assertEqual(r["step"], "Save and scan")
        self.assertEqual(r["running"]["key"], "scanning")
        self.assertIn("scan is running", r["running"]["note"])
        self.assertNotIn("already has findings", r["running"]["note"])
        self.assertIn("already has findings", r["already"])
        self.assertEqual(r["done"], {"status": "done", "key": "findings", "note": ""})

    def test_hearing_before_and_after_needs_both_sides(self):
        r = run_js(r"""
var out = {};
TR.start('scan-review'); TR.next(); TR.next(); TR.next();     // open, scan, read, hear
out.step = last().m.title;
HX.emit('review', { what: 'ab', side: 'B' }); out.afterB = last().m.status;
HX.emit('review', { what: 'ab', side: 'B' }); out.afterB2 = last().m.status;
HX.emit('review', { what: 'ab', side: 'A' }); out.afterBoth = last().m.status;
// a fresh visit to the step starts again
TR.back(); TR.next(); out.fresh = last().m.status; HX.emit('review', { what: 'ab', side: 'A' }); out.freshA = last().m.status;
print(JSON.stringify(out));
""")
        self.assertEqual(r["step"], "Hear before and after")
        self.assertEqual((r["afterB"], r["afterB2"], r["afterBoth"]), ("waiting", "waiting", "done"))
        self.assertEqual((r["fresh"], r["freshA"]), ("waiting", "waiting"))

    def test_a_new_window_size_scrolls_the_target_back_into_view(self):
        r = run_js(r"""
var out = {}, handlers = {};
window.addEventListener = function (n, f) { handlers[n] = f; };
window.removeEventListener = function (n) { delete handlers[n]; };
TR.start('first-look');
out.listening = typeof handlers.resize;
K.C.scrolled = true; handlers.resize();
out.afterResize = K.C.scrolled;
TR.end('x'); out.removed = typeof handlers.resize;
print(JSON.stringify(out));
""")
        self.assertEqual(r, {"listening": "function", "afterResize": False, "removed": "undefined"})

    def test_ending_on_the_closing_step_counts_as_done_and_the_demo_says_what_the_demo_shows(self):
        r = run_js(r"""
var out = {};
TR.start('mix'); var n = last().m.n; for (var i = 0; i < n - 1; i++) TR.next();
out.last = last().m.title; TR.end('escape');
out.done = TR.state().done.slice(); out.at = TR.state().at.mix;
// a tour left half way is still "left at"
TR.start('edit-region'); TR.next(); TR.next(); TR.end('escape');
out.half = { at: TR.state().at['edit-region'], done: TR.state().done.indexOf('edit-region') };
// the demo song has its own words where the real thing is not on screen
HX.mode = 'demo'; TR.start('save-export'); out.demo = last().m.say[0];
TR.end('x'); HX.mode = 'engine'; TR.start('save-export'); out.real = last().m.say[0];
print(JSON.stringify(out));
""")
        self.assertEqual(r["last"], "That is mixing")
        self.assertEqual(r["done"], ["mix"])
        self.assertIsNone(r.get("at"))
        self.assertEqual(r["half"], {"at": 2, "done": -1})
        self.assertIn("demo song shows a badge", r["demo"])
        self.assertIn("This is the name of the open session", r["real"])

    def test_the_region_resolver_points_at_the_selected_region(self):
        r = run_js(r"""
var clip = { id: 'c1', start: 8, len: 16, kind: 'audio' }, t1 = { id: 't1', height: 50, clips: [] }, t2 = { id: 't2', height: 50, clips: [clip] };
HX.S.session = { tracks: [t1, t2], returns: [], master: { id: 'm', height: 50, clips: [] } };
HX.S.ui.zoom = 2; HX.S.ui.scrollX = 0; HX.S.ui.clipId = 'c1';
HX.findClip = function () { return { track: t2, clip: clip }; }; HX.track = function () { return t1; };
K.env.rect = function () { return { left: 100, top: 40, right: 900, bottom: 400, width: 800, height: 360 }; };
var lanes = { parentElement: null };
print(JSON.stringify(TR.resolvers.clip(lanes)));
""")
        self.assertEqual((r["left"], r["right"], r["top"], r["bottom"]), (116, 148, 91, 139))


class TheRules(unittest.TestCase):
    def test_no_inline_handler_or_inline_script_comes_from_the_tour_files(self):
        for name in ("js/tours.js", "js/tour.js", "css/tour.css"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\bon(click|load|error|input|change|keydown)\s*=\s*[\"']", name)
            self.assertNotIn("eval(", text)
            self.assertNotIn("new Function", text)
            self.assertNotIn("innerHTML", text, f"{name}: text goes in with textContent or the page's builder")
            self.assertNotIn("insertAdjacentHTML", text)
            self.assertNotRegex(text, r"https?://", f"{name}: no address but the app's own routes")
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"<script(?![^>]*\bsrc=)", page)), 2, "the page's two inline scripts (token, theme) are the only ones")
        self.assertNotRegex(page, r"\son\w+=\"", "no inline handler in the page")
        self.assertIn('<link rel="stylesheet" href="css/tour.css">', page)
        self.assertLess(page.index('src="js/tours.js"'), page.index('src="js/tour.js"'))
        self.assertGreater(page.index('src="js/tours.js"'), page.index('src="js/app.js"'), "the tours start after the page has booted")
        self.assertIn('id="btnTour"', page)
        css = (ROOT / "css" / "tour.css").read_text(encoding="utf-8")
        self.assertIn(".tour-card.dock.top", css, "a docked card moves to the top when it would cover a low target")
        self.assertIn(".topbar .cpu", css, "the top bar gives way so the Tour button is on screen at laptop widths")

    def test_the_page_scripts_still_parse(self):
        from tests import _jscheck
        with tempfile.TemporaryDirectory() as td:
            found = _jscheck.scripts(td)
            self.assertIn("daw/js/tour.js", found)
            self.assertIn("daw/js/tours.js", found)
            try:
                problems = _jscheck.parse(found)
            except _jscheck.Missing as e:
                self.skipTest(str(e))
        self.assertEqual(problems, [])

    def test_the_events_the_tours_wait_for_are_sent_by_the_page(self):
        """Each wait names an event the page must send; if someone removes one, the step would wait for nothing."""
        want = {
            "js/store.js": ["HX.emit('edit', entry)", "HX.emit('undone', h)"],
            "js/app.js": ["HX.emit('saved')", "HX.emit('mode', m)", "HX.emit('help', o)"],
            "js/review.js": ["what: 'scanned'", "what: 'decided'", "what: 'ab'", "what: 'applied'"],
            "js/assistant.js": ["what: 'asked'", "what: 'card'", "what: 'hear'", "what: 'answered'"],
            "js/transport.js": ["HX.emit('transport')"],
            "js/arrange.js": ["'regionSplit'", "'regionMove'", "'regionTrim'", "'regionFades'"],
        }
        for rel, needles in want.items():
            text = (ROOT / rel).read_text(encoding="utf-8")
            for n in needles:
                self.assertIn(n, text, f"{rel} no longer has {n}")


class TheServer(unittest.TestCase):
    """The progress the page keeps on the server: its own key in teacher.json, sane or dropped."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(TE, "progress_file", return_value=Path(self.td.name) / "teacher.json")
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.td.cleanup()

    def test_nothing_saved_is_an_empty_answer(self):
        self.assertEqual(TE.handle_get("/api/teach/tour", {}), (200, {"offered": "", "done": [], "at": {}}))

    def test_what_the_page_sends_is_kept_and_read_back(self):
        code, body = TE.handle_post("/api/teach/tour", {"offered": "declined", "done": ["mix", "first-look"], "at": {"scan-review": 3}})
        self.assertEqual(code, 200)
        self.assertEqual(TE.handle_get("/api/teach/tour", {})[1], {"offered": "declined", "done": ["first-look", "mix"], "at": {"scan-review": 3}})

    def test_junk_is_dropped_and_the_courses_own_progress_is_left_alone(self):
        TE.mark("live", "step-a")
        TE.handle_post("/api/teach/tour", {"offered": "yes please", "done": ["ok", "Bad Id", 7, "../x"], "at": {"mix": "2", "ok": 500, "good": 4, "x" * 60: 1}})
        self.assertEqual(TE.tour_state(), {"offered": "", "done": ["ok"], "at": {"good": 4}})
        self.assertEqual(TE.load_progress()["live"]["done"], ["step-a"])
        for bad in (None, [], "text", 5):
            self.assertEqual(TE.tour_clean(bad), {"offered": "", "done": [], "at": {}})

    def test_the_teacher_tab_card_and_the_route_are_there(self):
        js = Path(TE.__file__).with_name("teacher.js").read_text(encoding="utf-8")
        self.assertIn("Take the tour inside the HypnoMix DAW", js)
        self.assertIn("/daw/#tour", js)
        self.assertIn("dawTourCard", js)
        self.assertIn("/api/daw/state", js, "the card is shown only where the DAW view is available")
        from hypnomix.app import chat
        with mock.patch.dict(chat.CHAT, {"daw_tools": True}):
            self.assertIn("suggest a guided tour by name", chat._daw_note())


if __name__ == "__main__":
    unittest.main()
