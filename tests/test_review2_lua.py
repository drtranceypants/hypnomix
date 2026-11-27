"""Second review: the REAPER bridge (bridge.lua, client.py) and the HypnoMix windows (ui.lua, the JSFX).

The Python side of the bridge runs here against a folder the test makes. The Lua and the JSFX are checked in the source
(no REAPER and no Lua run here)."""
import os
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from hypnomix.reaper import client as C

REAPER = Path(__file__).resolve().parent.parent / "hypnomix" / "reaper"
BRIDGE = (REAPER / "bridge.lua").read_text(encoding="utf-8")
UI = (REAPER / "ui.lua").read_text(encoding="utf-8")
JSFX = REAPER / "jsfx"
PROBE = (JSFX / "hypnomix_probe.jsfx").read_text(encoding="utf-8")
MAIN = (JSFX / "hypnomix_main.jsfx").read_text(encoding="utf-8")
UIINC = (JSFX / "hypnomix_ui.jsfx-inc").read_text(encoding="utf-8")


def body(src, start):
    """The text of the function that starts with `start`, up to the next top-level `end`."""
    i = src.index(start)
    j = src.index("\nend", i)
    return src[i:j]


def age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


# ---------------------------------------------------------------- 7: a long command is not a stopped bridge
class BusyBridge(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)
        self.r = C.Reaper(folder=self.d, timeout=1.0)
        running = mock.patch.object(C, "reaper_running", return_value=True)   # a REAPER is open (whatever this machine runs)
        running.start(); self.addCleanup(running.stop)

    def tearDown(self):
        self.td.cleanup()

    def test_stale_alive_with_busy_is_alive(self):
        (self.d / "alive").write_text("1", encoding="utf-8"); age(self.d / "alive", 30)
        self.assertFalse(self.r.alive())
        (self.d / "busy").write_text("abc\nmixer_solo_render\n", encoding="utf-8"); age(self.d / "busy", 30)
        from unittest import mock
        from hypnomix.reaper import client as CL
        with mock.patch.object(CL, "reaper_running", return_value=True):
            self.assertTrue(self.r.alive())
        with mock.patch.object(CL, "reaper_running", return_value=None):     # cannot tell: trust the busy file
            self.assertTrue(self.r.alive())
        with mock.patch.object(CL, "reaper_running", return_value=False):    # REAPER crashed mid-render
            self.assertFalse(self.r.alive())
        self.assertEqual(self.r.busy(), ("abc", "mixer_solo_render"))

    def test_busy_left_over_from_a_closed_reaper_does_not_count(self):
        (self.d / "alive").write_text("1", encoding="utf-8"); age(self.d / "alive", 2000)
        (self.d / "busy").write_text("abc\nmixer_solo_render\n", encoding="utf-8"); age(self.d / "busy", 700)
        self.assertIsNone(self.r.busy())
        self.assertFalse(self.r.alive())
        (self.d / "busy").write_text("abc\nfx_list\n", encoding="utf-8"); age(self.d / "busy", 130)   # a short command
        self.assertFalse(self.r.alive())

    def test_no_alive_file_is_not_running_even_with_busy(self):
        (self.d / "busy").write_text("abc\nrender_master\n", encoding="utf-8")
        self.assertFalse(self.r.alive())

    def test_start_leaves_a_busy_bridge_and_its_files_alone(self):
        (self.d / "alive").write_text("1", encoding="utf-8"); age(self.d / "alive", 30)
        (self.d / "busy").write_text("abc\nrender_master\n", encoding="utf-8")
        (self.d / "req-other.txt").write_text("ping\n", encoding="utf-8")
        with mock.patch.object(C.subprocess, "Popen") as pop, mock.patch.object(C, "reaper_executable", return_value="reaper"):
            self.assertTrue(self.r.start(wait=0.5))
        pop.assert_not_called()                                              # no second bridge
        self.assertTrue((self.d / "req-other.txt").exists())                 # the queued request is kept

    def test_call_waits_while_another_command_runs(self):
        (self.d / "alive").write_text("1", encoding="utf-8"); age(self.d / "alive", 30)
        (self.d / "busy").write_text("someone-else\nmixer_solo_render\nT\n4242\n", encoding="utf-8")
        at_work = mock.patch.object(C, "pid_running", return_value=True)     # its REAPER (4242) is at work
        at_work.start(); self.addCleanup(at_work.stop)

        def bridge():                                    # answers after the 1 s timeout, once the long command ends
            time.sleep(1.8)
            (self.d / "busy").unlink()
            for f in self.d.glob("req-*.txt"):
                (self.d / f.name.replace("req-", "res-").replace(".txt", ".json")).write_bytes(b'{"ok": true, "result": 7}')
                f.unlink()

        t = threading.Thread(target=bridge, daemon=True); t.start()
        self.assertEqual(self.r.call("ping"), 7)
        t.join()

    def test_call_still_times_out_when_nothing_is_busy(self):
        (self.d / "alive").write_text("1", encoding="utf-8")
        t0 = time.time()
        with self.assertRaises(C.ReaperError):
            self.r.call("ping")
        self.assertLess(time.time() - t0, 3)
        self.assertEqual(list(self.d.glob("req-*.txt")), [])                 # the unread request is taken back

    def test_long_command_timeouts_kept(self):
        self.assertEqual(C.LONG["render_master"], 600.0)
        self.assertEqual(C.LONG["mixer_solo_render"], 600.0)
        self.assertEqual(C.LONG["mixer_snapshot"], 120.0)


class BridgeLoop(unittest.TestCase):
    def test_busy_is_written_around_every_command(self):
        run = body(BRIDGE, "local function run(")
        self.assertLess(run.index("busy(id, cmd)"), run.index("pcall(fn, args)"))
        self.assertLess(run.index("pcall(fn, args)"), run.index("busy(nil)"))
        self.assertIn("beat(true)", run)                                     # alive fresh at once after a long one
        self.assertIn('io.open(DIR .. "/busy", "w")', BRIDGE)

    def test_one_bridge_per_reaper(self):
        self.assertIn('reaper.SetExtState("hypnomix", "bridge_token", TOKEN, false)', BRIDGE)
        loop = body(BRIDGE, "local function loop()")
        self.assertIn('reaper.GetExtState("hypnomix", "bridge_token") ~= TOKEN', loop.splitlines()[1])
        atexit = BRIDGE[BRIDGE.index("reaper.atexit(function()"):]
        self.assertIn("if replaced then return end", atexit)                # the newer bridge keeps its alive file

    def test_request_handling_is_protected(self):
        loop = body(BRIDGE, "local function loop()")
        self.assertIn("pcall(requests)", loop)
        self.assertNotIn("EnumerateFiles", loop)                             # the listing runs inside the pcall
        self.assertIn("if running then reaper.defer(loop)", loop)

    def test_answer_checks_the_file_opened(self):
        ans = body(BRIDGE, "local function answer(")
        self.assertIn("if not f then", ans)
        self.assertLess(ans.index("if not f then"), ans.index("f:write"))


# ---------------------------------------------------------------- nits: keyboard, jump, wrap, guide card
class PanelKeys(unittest.TestCase):
    def test_space_plays_and_esc_closes(self):
        keys = body(BRIDGE, "local function panel_keys()")
        self.assertIn("if ch == 32 then space = true", keys)
        self.assertIn("if space and not space_held then reaper.Main_OnCommand(40044, 0) end", keys)   # once per press
        self.assertIn("ch == 27", keys)
        self.assertIn("U.tour_esc = true", keys)
        self.assertIn("gfx.quit(); return false", keys)
        for draw in ("local function panel_draw()", "local function align_draw()"):
            self.assertIn("if not panel_keys() then", body(BRIDGE, draw).splitlines()[1])
        self.assertIn("if hit or U.tour_esc then result = \"done\" end", UI)

    def test_only_the_used_keys_are_taken(self):
        keys = body(BRIDGE, "local function panel_keys()")
        self.assertEqual(sorted(set(re.findall(r"ch == (\d+)", keys))), ["0", "27", "32"])   # 0: no key waiting


class JumpWithoutTrack(unittest.TestCase):
    def test_no_track_leaves_the_selection(self):
        jump = body(BRIDGE, "function C.jump(a)")
        self.assertIn('local tr = (a.track and a.track ~= "") and track_of(a.track) or nil', jump)


class WrapEveryLine(unittest.TestCase):
    def test_a_lone_long_word_is_cut_on_any_line(self):
        wrap = body(UI, "function U.wrap(")
        tail = wrap[wrap.index("for i, l in ipairs(lines) do\n    if gfx.measurestr(l)"):]
        self.assertIn("cut(", tail)
        self.assertLess(wrap.index("for i, l in ipairs(lines) do\n    if gfx.measurestr(l)"),
                        wrap.index("if not measure then"))                   # before anything is drawn


class GuideCardPlace(unittest.TestCase):
    def test_lua_card_goes_beside_the_spot(self):
        place = body(UI, "function U.tour_place(")
        self.assertIn("U.w - (x + w + 14) - 6, x - 14 - 6", place)
        self.assertIn("sw >= U.CARD_MIN", place)
        self.assertIn("over_bottom < over_top", place)
        self.assertIn("U.tour_place(x, y, w, h, body)", body(UI, "function U.tour("))

    def test_jsfx_card_goes_beside_the_spot(self):
        tour = UIINC[UIINC.index("function ui_tour()"):]
        self.assertIn("room_r = ui_w - (tour_x + tour_w + 14) - 6; room_l = tour_x - 14 - 6;", tour)
        self.assertIn("sw >= 240 && sh <= ui_h - 12", tour)
        self.assertIn("cy = ov_b < ov_t ? bot : top;", tour)
        local = re.match(r"function ui_tour\(\) local\(([^)]*)\)", tour).group(1).replace(" ", "").split(",")
        for name in ("room_r", "room_l", "sw", "sh", "top", "bot", "ov_t", "ov_b"):
            self.assertIn(name, local)                                       # declared local, not a global the audio shares

    def test_lua_model_of_the_probe_width_step(self):
        """A Python copy of U.tour_place with a fixed text width (7 points a character): the Probe's Width step (the
        card on the right edge, full height) gets its card to the left, not over the card."""
        def place(x, y, w, h, n_chars, W=520, H=236, cpp=7.0):
            def size(cw):
                per = max(1, int((cw - 28) // cpp)); lines = -(-n_chars // per); return 43 + lines * 15 + 40
            cw = min(400, W - 24); ch = size(cw)
            cx = max(12, min(W - cw - 12, x + w / 2 - cw / 2))
            if y + h + 14 + ch <= H - 6: return cw, cx, y + h + 14, ch
            if y - ch - 14 >= 6: return cw, cx, y - ch - 14, ch
            right, left = W - (x + w + 14) - 6, x - 14 - 6
            sw = min(400, max(right, left))
            if sw >= 240 and size(sw) <= H - 12:
                sh = size(sw); sx = x + w + 14 if right >= left else x - 14 - sw
                return sw, sx, max(6, min(H - sh - 6, y + h / 2 - sh / 2)), sh
            top, bottom = 6, max(6, H - ch - 6)
            ot = max(0, min(top + ch, y + h) - max(top, y)); ob = max(0, min(bottom + ch, y + h) - max(bottom, y))
            return cw, cx, bottom if ob < ot else top, ch
        cw, cx, cy, ch = place(388, 92, 122, 134, 170)
        self.assertLessEqual(cx + cw, 388)                                    # left of the spot
        self.assertIn("x - 14 - sw", body(UI, "function U.tour_place("))


# ---------------------------------------------------------------- nit 20: Probe labels fit their card
class ProbeLabels(unittest.TestCase):
    def test_short_labels(self):
        self.assertIn('"WIDTH  (L/R)"', PROBE)
        self.assertIn('"LOW END  (<120 Hz)"', PROBE)
        self.assertNotIn("L/R correlation", PROBE)
        self.assertNotIn("under 120 Hz", PROBE)
        self.assertIn('"app hears this track"', PROBE)
        for s in ("WIDTH  (L/R)", "LOW END  (<120 Hz)", "app hears this track", "slot set: open the app"):
            self.assertLessEqual(len(s), 22, s)                              # about 110 points of room at Arial 11


# ---------------------------------------------------------------- nit 22 and the guide texts
class GuideTexts(unittest.TestCase):
    def test_review_step_one_says_what_happens(self):
        self.assertNotIn("Clicking a finding", BRIDGE)
        self.assertNotIn("Nothing in your project changes here", BRIDGE)
        self.assertIn("Prev, Next and Next open here, or Show in REAPER in the app", BRIDGE)
        self.assertIn("nothing is saved until you save", BRIDGE)
        self.assertIn("A, B and Blind switch which plug-ins and tracks play", BRIDGE)

    def test_main_passes_audio_except_match(self):
        self.assertNotIn("Audio passes through untouched", MAIN)
        self.assertIn("except while Match is on in an A/B review", MAIN)
        self.assertIn("match_g", (JSFX / "hypnomix_meter.jsfx-inc").read_text(encoding="utf-8"))

    def test_probe_record_step_names_the_button(self):
        self.assertNotIn("Press Record on HypnoMix Main and play", PROBE)
        self.assertIn("Press Record and review on HypnoMix Main: REAPER plays from the edit cursor", PROBE)
        self.assertIn('"Record and review"', MAIN)                          # the button's own name

    def test_space_and_esc_are_in_the_guides(self):
        self.assertIn("Press space to play the selection", BRIDGE)
        self.assertEqual(BRIDGE.count("space plays and stops REAPER, and Esc closes the guide"), 2)


if __name__ == "__main__":
    unittest.main()
