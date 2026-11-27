"""The DAW page's keyboard, focus and honesty fixes (review of the round-2 port): the Group dialog by keyboard, the focus
after a header is drawn again, the arrows never selecting a track folded away, the take Comp button, and the smaller
things (the loudness readout when the stream drops, cue launches not marking unsaved, the cue error shown, no poll
outside the Session view, still lights when less motion is asked for, names for the Ungroup button and take headers).

Where the behaviour can run without a browser (groups.js on the stand-in page of test_daw_keys) it is RUN; the rest is
held to the source here and was looked at in a browser when it was made."""
import re
import unittest
from pathlib import Path

from tests.test_daw_keys import FAKE_DOM, TRACKS, run_js  # noqa: F401  (the same stand-in page)

ROOT = Path(__file__).resolve().parent.parent
DAW = ROOT / "hypnomix" / "app" / "daw"
JS = DAW / "js"


def read(name):
    return (JS / name).read_text(encoding="utf-8")


class FoldedTracksAreNeverSelected(unittest.TestCase):
    def test_a_fold_moves_the_selection_to_the_group_header(self):
        r = run_js(self, TRACKS + r"""
HX.S.session.returns.push({ id: 'g1', name: 'Vox', kind: 'bus', real: true, clips: [], devices: [], sends: [], isReturn: true });
var folded = true;
HX.liveEngine = { quiet: function () { return Promise.resolve({ groups: [{ groupId: 'G', name: 'Vox', busId: 'g1', folded: folded, members: [{ trackId: 'b' }, { trackId: 'c' }] }] }); } };
HX.mcp.call = function () { return Promise.resolve({ group: { folded: false } }); };
HX.select('c');
var out = {};
HX.groups.read().then(function () {
  out.afterRead = HX.S.ui.trackId;                          /* c is folded away: its group's header is selected */
  out.hidden = HX.groups.hidden(HX.track('c'));
  HX.select('a');
  out.keepsVisible = HX.S.ui.trackId;                       /* a visible track stays selected */
  print(JSON.stringify(out));
});
""", ["store.js", "groups.js"])
        self.assertEqual(r["afterRead"], "g1")
        self.assertTrue(r["hidden"])
        self.assertEqual(r["keepsVisible"], "a")

    def test_the_arrows_skip_folded_tracks_and_m_s_ignore_a_hidden_one(self):
        app = read("app.js")
        self.assertIn("const list = HX.allTracks().filter((t) => t === sel0 || !hidden(t));", app)
        self.assertIn("sel = hidden(sel0) ? null : sel0", app)
        self.assertIn("list.indexOf(sel0)", app)
        g = read("groups.js")
        self.assertIn("if (folded) G.keepVisible();", g)


class GroupDialogByKeyboard(unittest.TestCase):
    def test_tab_goes_round_every_control_and_space_types(self):
        util = read("util.js")
        dlg = util[util.index("HX.dialog = function"):util.index("HX.modalOpen = ")]
        self.assertIn("ov.querySelectorAll('button, input, select, textarea, a[href], [tabindex]')", dlg)
        self.assertIn("const list = ring()", dlg)
        self.assertNotIn("btns.filter((b) => !b.disabled)", dlg)          # Tab is no longer the buttons only
        self.assertIn("e.key === ' ' && t && ov.contains(t) && t.matches && t.matches('input, textarea, select')", dlg)
        self.assertIn("btns.includes(document.activeElement)", dlg)       # Enter still only presses a focused button

    def test_group_errors_say_what_happened(self):
        g = read("groups.js")
        self.assertIn("but the view could not read the session again", g)
        self.assertIn("'aria-label': 'Ungroup ' + g.name", g)
        self.assertIn("if (!G.available()) return HX.toast('Groups need the engine", g)


class FocusAfterHeadersAreDrawnAgain(unittest.TestCase):
    def test_the_focused_control_gets_the_focus_back(self):
        a = read("arrange.js")
        body = a[a.index("function renderHeaders()"):a.index("HX.renderArrangeHeaders = renderHeaders;")]
        self.assertIn("const hadFocus = focusedHeaderKey();", body)
        self.assertIn("restoreHeaderFocus(hadFocus);", body)
        self.assertIn("'data-hk': t.id", a)
        for kind in ("'tk'", "'grp-fold'", "'grp-x'", "'take-comp'"):
            self.assertIn(kind, a)
        t = read("takes.js")
        self.assertIn("'data-hk': 'take:' + t.id + ':' + k.id", t)


class TakesByKeyboard(unittest.TestCase):
    def test_comp_button_header_names_and_the_drag_guard(self):
        t = read("takes.js")
        self.assertIn("h('button.take-comp'", t)
        self.assertIn("T.compAsk = async function (t, k)", t)
        self.assertIn("return T.comp(t, k, a, b);", t)                   # the same one-undo-step comp as a drag
        self.assertIn("role: 'group', 'aria-label': 'Take ' + k.n + ' of ' + t.name", t)
        self.assertIn("if (!T.drag) return;", t)
        self.assertIn("if (!d) return;", t)


class SmallerThings(unittest.TestCase):
    def test_loudness_goes_when_the_stream_drops(self):
        live = read("live.js")
        close = live[live.index("ws.onclose = () => {"):live.index("function closeStream()")]
        self.assertIn("L.master = null; showLoudness(null);", close)
        self.assertIn("expReading", live)                                # one export_status at a time
        self.assertIn("now - expAskedAt > 1000", live)

    def test_launching_is_not_a_change(self):
        reads = re.search(r"const READS = (/.*/);", read("mcp.js")).group(1)
        for tool in ("cue_launch", "cue_stop", "scene_launch"):
            self.assertIn(tool, reads)
        self.assertNotIn("cue_set_clip", reads)

    def test_cue_errors_show_and_no_poll_outside_the_session_view(self):
        c = read("cues.js")
        self.assertIn("HX.emit('cues-error'", c)
        self.assertIn("if (ms == null && !view) { if (timer) clearTimeout(timer); timer = 0; return; }", c)
        self.assertIn("if (timer && due <= at) return;", c)             # a read due sooner is never put off (starved poll)
        self.assertIn("const run = !C.error && C.rolling", c)
        self.assertIn("HX.on('cues-error'", read("clips.js"))

    def test_still_lights_and_names(self):
        css = (DAW / "css" / "app.css").read_text(encoding="utf-8")
        m = re.search(r"@media \(prefers-reduced-motion: reduce\) \{\s*\.slot\.clip\.playing \.tri[^}]*animation: none", css)
        self.assertIsNotNone(m, "the slots' blinking stops when less motion is asked for")
        self.assertRegex(css, r"\.slot\.clip \.cue-x:focus-visible")
        self.assertRegex(css, r"\.scene:focus-visible, \.stoprow:focus-visible")
        html = (DAW / "index.html").read_text(encoding="utf-8")
        self.assertIn('<span class="sr-only">Master loudness, short-term: </span>', html)
        self.assertIn('id="toast" role="status" aria-live="polite"', html)

    def test_page_comments_do_not_name_the_old_product(self):
        for f in ("cues.js", "groups.js"):
            head = read(f).split("*/", 1)[0]
            self.assertNotIn("ardour", head.lower(), f)
            self.assertIn("HypnoMix", head, f)


if __name__ == "__main__":
    unittest.main()
