"""vocalign extras: presets, protected areas, sync points, pitch matching, formant; alignset's warp markers; the Align
device and its app endpoints."""
import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hypnomix.studio import alignopts as AO

SR = 44100


def voice(notes, sr=SR, delay=0.0, cents=0.0, vib=5.5, seed=0, length=8.0):
    """A sung-like tone per note (harmonics, vibrato, a consonant burst at the start), mono (n, 1)."""
    rng = np.random.default_rng(seed)
    y = np.zeros(int(sr * length))
    for t0, dur, m in notes:
        n = int(dur * sr)
        t = np.arange(n) / sr
        f = 440 * 2 ** ((m - 69 + cents / 100) / 12) * (1 + 0.004 * np.sin(2 * np.pi * vib * t))
        ph = 2 * np.pi * np.cumsum(f) / sr
        s = sum(np.sin(k * ph) / k ** 1.2 for k in range(1, 10))
        env = np.minimum(1, t / 0.03) * np.minimum(1, (dur - t) / 0.06)
        i = int((t0 + delay) * sr)
        y[i:i + n] += 0.2 * (s * env + rng.normal(0, 0.3, n) * np.exp(-t / 0.015))
    return y[:, None]


NOTES = [(0.5 + 0.6 * i, 0.45, [60, 62, 64, 65, 67, 65, 64, 62][i % 8]) for i in range(11)]


class Options(unittest.TestCase):
    def test_times_ranges_and_syncs(self):
        self.assertEqual(AO.seconds("1:02.5"), 62.5)
        self.assertEqual(AO.ranges(["70-75", "62-71", "1:30-1:31"]), [(62.0, 75.0), (90.0, 91.0)])
        self.assertEqual(AO.syncs(["70.1=70.02", "62.4"]), [(62.4, None), (70.1, 70.02)])
        with self.assertRaises(SystemExit):
            AO.ranges(["10-5"])

    def test_protect_zeroes_inside_and_ramps_outside(self):
        o = np.full(1000, 5.0)
        p, mask = AO.protect_plan(o, [(4.0, 5.0)], ramp_s=0.3)
        self.assertTrue(np.all(p[400:500] == 0) and mask[400:500].all() and not mask[:400].any())
        self.assertEqual(p[369], 5.0)
        self.assertTrue(0 < p[385] < 5.0)                                 # fading out before the range
        self.assertEqual(p[100], 5.0)                                    # far away: untouched
        self.assertTrue(0 < p[510] < 5.0)

    def test_preset_fills_only_what_was_not_given(self):
        a = SimpleNamespace(strength=0.5, to_lead=False, mode="tight", max_ms=150, trim_tails=False, pitch=0.0, vibrato=0.0)
        d = dict(strength=1.0, to_lead=False, mode="tight", max_ms=150, trim_tails=False, pitch=0.0, vibrato=0.0)
        AO.apply_preset(a, "tight-pop", d)
        self.assertEqual(a.strength, 0.5)               # given on the command line: kept
        self.assertTrue(a.to_lead and a.trim_tails)
        self.assertEqual(a.pitch, 0.35)

    def test_sync_point_measures_the_offset_to_the_millisecond(self):
        g, p = voice(NOTES), voice(NOTES, delay=0.037, seed=1)
        lag = AO.precise_lag(g, p, SR, 2.3)
        self.assertAlmostEqual(lag, 0.037, delta=0.002)
        h = voice([(t, d, m + 4) for t, d, m in NOTES], delay=-0.021, seed=2)       # a harmony a third up
        self.assertAlmostEqual(AO.precise_lag(g, h, SR, 2.3), -0.021, delta=0.003)
        plan, done = AO.sync_plan(np.zeros(800), [(2.3, None)], g, p, SR, cap_frames=15)
        self.assertAlmostEqual(plan[230] * 10, 37, delta=2)                           # frames -> ms at the point
        self.assertLess(abs(plan[0]), 1e-6)

    def test_protected_audio_is_sample_exact(self):
        orig = np.random.default_rng(0).normal(size=(SR * 3, 1))
        out = orig * 0.5
        mask = np.zeros(300, bool); mask[100:200] = True
        r = AO.splice_protected(orig, out, mask, SR)
        self.assertTrue(np.array_equal(r[SR:2 * SR], orig[SR:2 * SR]))
        self.assertTrue(np.allclose(r[:SR // 2], out[:SR // 2]))


@unittest.skipUnless(shutil.which("rubberband"), "needs Rubber Band")
class Pitch(unittest.TestCase):
    def test_double_moves_toward_guide_and_harmony_keeps_its_interval(self):
        from hypnomix.studio import pitchmatch as PM
        g = voice(NOTES)
        d = voice(NOTES, cents=-30, seed=1)
        h = voice([(t, dd, m + 4) for t, dd, m in NOTES], cents=26, seed=2)
        _, nd = PM.plan(g, d, SR, amount=0.35)
        _, nh = PM.plan(g, h, SR, amount=0.35)
        fd = [r for r in nd if r["action"] == "fix"]
        fh = [r for r in nh if r["action"] == "fix"]
        self.assertGreater(len(fd), 6)
        self.assertTrue(all(r["kind"] == "double" for r in fd))
        self.assertAlmostEqual(np.median([r["shift"] for r in fd]), 0.105, delta=0.02)      # 35% of 30 cents, upward
        self.assertTrue(all(r["kind"] == "harmony" and r["interval"] == 4 for r in fh))      # still a major third
        self.assertLess(np.median([r["shift"] for r in fh]), 0)                               # pulled down onto it

    def test_chord_clash_is_asked_not_moved(self):
        from hypnomix.studio import pitchmatch as PM, chords as CH
        g, d = voice(NOTES), voice(NOTES, cents=-30, seed=1)
        ch = np.zeros((12, int(8 / CH.HOP_S) + 1)); ch[11] = 1.0; ch[3] = 0.9; ch[6] = 0.9   # B major under everything
        _, notes = PM.plan(g, d, SR, amount=0.35, chords=ch)
        cs = [r for r in notes if r["centre"] % 12 > 11.5]          # C sung flat: pulling it up to C clashes, B fits
        self.assertTrue(cs and all(r["action"] == "ask" and r["suggest"] == "B" for r in cs))
        self.assertTrue(all(r["shift"] == 0 for r in cs))

    def test_formant_keeps_length_and_alignment(self):
        from hypnomix.studio import formant as FM
        y = voice(NOTES)
        out = FM.shift(y, SR, formant=0.5)
        self.assertEqual(out.shape, y.shape)
        self.assertAlmostEqual(AO.precise_lag(y, out, SR, 2.3), 0.0, delta=0.002)
        part = FM.shift(y, SR, formant=0.5, ranges=[(1.0, 2.0)])
        self.assertTrue(np.array_equal(part[int(3 * SR):], y[int(3 * SR):]))


class SetMarkers(unittest.TestCase):
    def test_warp_markers_play_the_planned_audio(self):
        import xml.etree.ElementTree as ET
        from hypnomix.studio import alignset as A
        from hypnomix.session import smooth as sm
        tempo = 120.0
        c = ET.fromstring('<AudioClip><WarpMarkers><WarpMarker Id="0" SecTime="0" BeatTime="0"/>'
                          '<WarpMarker Id="1" SecTime="20" BeatTime="40"/></WarpMarkers></AudioClip>')
        ci = dict(el=c, name="take", start=8.0, end=24.0, loop_on=False, ls=0.0, le=40.0, rel=0.0, warped=True,
                  markers=[(0.0, 0.0), (40.0, 20.0)])
        plan = np.zeros(1500)
        plan[500:900] = 4.0                                       # pull 40 ms earlier between 5 s and 9 s
        plan[480:500] = np.linspace(0, 4, 20); plan[900:920] = np.linspace(4, 0, 20)
        before = dict(ci)
        pairs, err = A.markers_for_clip(ci, plan, tempo)
        self.assertIsNotNone(pairs)
        self.assertLess(err, 0.6)
        A.write_markers(ci, pairs)
        T = np.array([4.5, 6.0, 8.0, 11.0])
        now = sm.file_seconds(ci, T / 0.5, tempo)
        was = sm.file_seconds(before, (T + np.interp(T, np.arange(1500) * 0.01, plan * 0.01)) / 0.5, tempo)
        self.assertTrue(np.allclose(now, was, atol=0.0006))
        self.assertAlmostEqual(now[1] - sm.file_seconds(before, np.array([12.0]), tempo)[0], 0.04, delta=0.001)
        self.assertEqual(len(c.findall("./WarpMarkers/WarpMarker")), len(pairs))

    def test_opposite_moves_across_a_short_gap_are_eased_not_skipped(self):
        # gentle stack mode moves each word whole and changes the move linearly between words: here one word plays
        # 30 ms later audio and the next 30 ms earlier, across a 50 ms gap, so the plan would play the gap backwards
        import xml.etree.ElementTree as ET
        from hypnomix.studio import alignset as A
        from hypnomix.session import smooth as sm
        tempo = 120.0
        c = ET.fromstring('<AudioClip><WarpMarkers><WarpMarker Id="0" SecTime="0" BeatTime="0"/>'
                          '<WarpMarker Id="1" SecTime="20" BeatTime="40"/></WarpMarkers></AudioClip>')
        ci = dict(el=c, name="harmony", start=8.0, end=24.0, loop_on=False, ls=0.0, le=40.0, rel=0.0, warped=True,
                  markers=[(0.0, 0.0), (40.0, 20.0)])
        plan = np.zeros(1500)
        plan[500:600] = 3.0                                       # word one, 5.00-6.00 s: +30 ms
        plan[600:605] = np.linspace(3, -3, 5)                     # the 50 ms gap
        plan[605:700] = -3.0                                      # word two, 6.05-7.00 s: -30 ms
        plan[480:500] = np.linspace(0, 3, 20); plan[700:720] = np.linspace(-3, 0, 20)
        before = dict(ci)
        T = np.arange(4.0, 12.0, 0.005)
        was = sm.file_seconds(before, (T + np.interp(T, np.arange(1500) * 0.01, plan * 0.01)) / 0.5, tempo)
        self.assertTrue(np.any(np.diff(was) <= 0))                # the plan as it stands runs backwards
        pairs, err = A.markers_for_clip(ci, plan, tempo)
        self.assertIsNotNone(pairs, err)
        self.assertLess(err, 0.6)
        self.assertGreater(A.markers_for_clip.eased, 5.0)         # eased, and says by how much
        self.assertLess(A.markers_for_clip.eased, 40.0)
        A.write_markers(ci, pairs)
        secs = [s for b, s in ci["markers"]]
        self.assertTrue(all(b > a for a, b in zip(secs, secs[1:])))
        now = sm.file_seconds(ci, T / 0.5, tempo)
        self.assertTrue(np.all(np.diff(now) >= A.MIN_SPEED * 0.005 - 0.0006))  # never backwards, never below 0.25x
        far = np.abs(T - 6.025) > 0.15                            # away from the gap the words land on the plan
        self.assertTrue(np.allclose(now[far], was[far], atol=0.0006))
        plain = np.zeros(1500); plain[500:700] = 2.0
        plain[480:500] = np.linspace(0, 2, 20); plain[700:720] = np.linspace(2, 0, 20)
        A.markers_for_clip(dict(before, el=ET.fromstring("<AudioClip><WarpMarkers/></AudioClip>")), plain, tempo)
        self.assertEqual(A.markers_for_clip.eased, 0.0)           # a gentle plan is not eased


class AppAndDevice(unittest.TestCase):
    def test_device_request_becomes_an_alignset_command(self):
        from hypnomix.app import align as AL
        argv = AL.argv_for(dict(guide="Lead", parts=["Lead", "Dbl", "Harm"], start_s=10, end_s=30, protect=[[12, 14]],
                                sync=[20.5], preset="tight-pop", tightness=0.5, pitch=0.3, formant=0.4, apply=True),
                           "/x/Song.als", "/tmp/o")
        s = " ".join(argv)
        self.assertEqual(argv[:6], ["alignset", "/x/Song.als", "--guide", "Lead", "--parts", "Dbl"])
        for bit in ("--range 10.000-30.000", "--protect 12.000-14.000", "--sync 20.500", "--preset tight-pop",
                    "--pitch 0.3", "--formant 0.4", "--apply", "--strength 0.50"):
            self.assertIn(bit, s)
        self.assertNotIn("--no-chord-check", s)                    # the chord check stays on unless asked
        with self.assertRaises(ValueError):
            AL.argv_for(dict(guide="Lead", parts=["Lead"]), "/x.als", "/tmp")
        with self.assertRaises(ValueError):
            AL.argv_for(dict(guide="Lead", parts=["B"], pitch=4), "/x.als", "/tmp")

    def test_builds_the_align_device(self):
        from hypnomix.app import device as D, aligndevice as AD
        blank = {"patcher": {"boxes": [{"box": {"id": "obj-1", "maxclass": "newobj", "text": "plugin~"}},
                                       {"box": {"id": "obj-2", "maxclass": "newobj", "text": "plugout~"}}],
                             "lines": [{"patchline": {"destination": ["obj-2", 0], "source": ["obj-1", 0]}}],
                             "openinpresentation": 0, "devicewidth": 0.0}}
        with tempfile.TemporaryDirectory() as td:
            tpl = Path(td) / "Max Audio Effect.amxd"
            D.write_amxd(tpl, b"ampf\x04\x00\x00\x00aaaameta\x04\x00\x00\x00\x00\x00\x00\x00", blank)
            out = AD.build(Path(td) / "out", tpl)
            _, patch = D.read_amxd(out / "Hypnomix Align.amxd")
            js_box = [b["box"] for b in patch["patcher"]["boxes"] if b["box"].get("maxclass") == "jsui"][0]
            self.assertEqual(js_box["filename"], "hypnomix_align.js")
            self.assertEqual(patch["patcher"]["devicewidth"], float(AD.W))
            js = (out / "hypnomix_align.js").read_text()
            self.assertNotIn("__", js)

    @unittest.skipUnless(sys.platform == "darwin", "runs the device script in macOS's JavaScript engine")
    def test_device_script_in_a_simulated_live(self):
        from hypnomix.app import aligndevice as AD
        js = AD.JS.replace("__PORT__", "8791").replace("__W__", str(AD.W)).replace("__H__", str(AD.H))
        stubs = r"""
var SENT = [], CALLS = [], SET = {tempo: 120, loop_start: 32, loop_length: 16, current_song_time: 40};
var TRACKS = ["Lead", "Double", "Harmony"], SELECTED = 0;
function noop() {}
var mgraphics = {init: noop, redraw: noop, set_source_rgba: noop, rectangle: noop, rectangle_rounded: noop, fill: noop,
  stroke: noop, move_to: noop, line_to: noop, set_line_width: noop, select_font_face: noop, set_font_size: noop,
  show_text: noop, text_measure: function (s) { return [String(s).length * 5, 10]; }};
function Task() { this.repeat = noop; this.cancel = noop; }
var max = {launchbrowser: noop};
function LiveAPI(path) {
  this.path = path; this.id = 1;
  var m = /tracks (\d+)/.exec(path);
  this.idx = m ? +m[1] : (path == "live_set view selected_track" ? SELECTED : -1);
  this.get = function (k) {
    if (k == "name") return [TRACKS[this.idx]];
    return [SET[k]];
  };
  this.getcount = function () { return TRACKS.length; };
  this.set = function (k, v) { CALLS.push(["set", this.path, k, v]); };
  this.call = function (f, a, b) { CALLS.push(["call", this.path, f, a, b]); };
}
function XMLHttpRequest() {
  var self = this;
  this.open = function (m, u) { self.m = m; self.u = u; };
  this.send = function (b) {
    SENT.push([self.m, self.u.replace("http://127.0.0.1:8791", ""), b ? JSON.parse(b) : null]);
    self.readyState = 4;
    self.responseText = JSON.stringify(self.u.indexOf("/state") > 0 ?
      {set: "/x/Song.als", set_name: "Song.als", status: "done", running: false,
       result: {out_set: "/x/Song (aligned).als", parts: [{markers: 12}], rendered: {"Double": "/o/Double (pitch).wav"},
                energy: {t0: 0, t1: 8, tracks: [{name: "Lead", before: [-10, -20], after: null},
                                                {name: "Double", before: [-12, -30], after: [-11, -28]}]}}} : {job: 1});
    self.onreadystatechange();
  };
}
"""
        driver = r"""
bang(); tick(); paint();
SELECTED = 0; act("guide");
SELECTED = 1; act("part"); SELECTED = 2; act("part"); SELECTED = 0; act("part");
act("protect"); act("sync"); act("preset"); act("write");
st.pitch = 0.3;
act("align"); paint(); act("place"); paint();
var run = SENT.filter(function (x) { return x[1] == "/api/align/run"; })[0];
JSON.stringify({run: run && run[2], calls: CALLS.filter(function (c) { return c[0] == "call"; })});
"""
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "sim.js"
            f.write_text(stubs + js + driver)
            r = subprocess.run(["osascript", "-l", "JavaScript", str(f)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = json.loads(r.stdout)
        body = res["run"]
        self.assertEqual(body["guide"], "Lead")
        self.assertEqual(body["parts"], ["Double", "Harmony"])          # the guide is never a part
        self.assertAlmostEqual(body["start_s"], 16.0)                   # 32 beats at 120 BPM
        self.assertAlmostEqual(body["end_s"], 24.0)
        self.assertEqual(body["protect"], [[16.0, 24.0]])
        self.assertEqual(body["sync"], [20.0])
        self.assertEqual(body["preset"], "gentle-stack")
        self.assertTrue(body["apply"])
        self.assertAlmostEqual(body["pitch"], 0.3)
        made = [c for c in res["calls"] if c[2] in ("create_audio_track", "create_audio_clip")]
        self.assertEqual(made[0][2:4], ["create_audio_track", 2])           # under the Double track
        self.assertEqual(made[1][2:4], ["create_audio_clip", "/o/Double (pitch).wav"])


if __name__ == "__main__":
    unittest.main()
