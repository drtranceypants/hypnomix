"""Takes and comping: Live take lanes read into the model like HypnoMix DAW take playlists (`Track.take_lanes`, not heard),
the scan names comped tracks, the DAW view's take lanes are wired in, and the Assistant reads takes at once and
shows a comp as one proposal."""
import gzip
import re
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from tests.test_als2ardour import _audio_track, _clip, make_set

SR = 44100
DAW = Path(__file__).resolve().parents[1] / "hypnomix" / "app" / "daw"


def lanes_track(d):
    """An audio track "Choir" whose comp is one clip, with two take lanes of two clips each."""
    take = lambda cid, s, e: _clip(cid, s, e, d / "vox.wav")
    lanes = ('<TakeLanes><TakeLanes>'
             f'<TakeLane Id="0"><Name Value="Take A"/><ClipAutomation><Events>{take(31, 4, 8)}{take(32, 8, 12)}'
             '</Events></ClipAutomation></TakeLane>'
             f'<TakeLane Id="1"><Name Value=""/><ClipAutomation><Events>{take(33, 4, 12)}</Events></ClipAutomation>'
             '</TakeLane></TakeLanes></TakeLanes>')
    t = _audio_track(20, "Choir", take(30, 4, 12), 400, out="AudioOut/Main")
    return t.replace("</AudioTrack>", lanes + "</AudioTrack>")


class LiveTakeLanes(unittest.TestCase):
    def test_take_lanes_are_lanes_not_clips(self):
        from hypnomix.project import als
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = make_set(d, lanes_track(d))
            proj = als.read(p)
            vox = proj.track("Choir")
            self.assertEqual(len(vox.clips), 1)                      # only the comp plays
            self.assertEqual([(k.name, k.number, len(k.clips)) for k in vox.take_lanes],
                             [("Take A", 1, 2), ("Take 2", 2, 1)])
            self.assertTrue(vox.comped)
            self.assertFalse(proj.track("Lead").comped)
            spb = 60.0 / proj.tempo
            self.assertAlmostEqual(vox.take_lanes[0].clips[1].start, 8 * spb)
            self.assertEqual(vox.take_lanes[1].clips[0].path.name, "vox.wav")


class ScanNote(unittest.TestCase):
    def test_comped_tracks_are_named(self):
        from hypnomix.project.model import Clip, Project, TakeLane, Take, Track
        from hypnomix.workflow import scan_project as SP
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "v.wav"
            sf.write(f, np.zeros(SR), SR)
            c = Clip(name="c", start=0.0, length=1.0, takes=[Take(name="c", path=f)], fade_in=0.01, fade_out=0.01)
            t = Track(name="Vox", index=0, clips=[c], take_lanes=[TakeLane(name="Vox.take 1", number=1, clips=[c])])
            p = Project(path=Path(td) / "S.ardour", daw="ardour", tracks=[t], sample_rate=SR)
            SP.W.update(SP.WORDS["ardour"])
            from types import SimpleNamespace
            _, notes = SP.g_clips(p, SimpleNamespace(files={}), Path(td), SimpleNamespace())
        self.assertTrue(any("comped from takes: Vox (1 take)" in n for n in notes), notes)


class DawView(unittest.TestCase):
    def test_takes_js_is_loaded_and_hooked(self):
        html = (DAW / "index.html").read_text(encoding="utf-8")
        scripts = re.findall(r'<script src="(js/[^"]+)"', html)
        self.assertIn("js/takes.js", scripts)
        self.assertGreater(scripts.index("js/takes.js"), scripts.index("js/arrange.js"))
        js = (DAW / "js" / "takes.js").read_text(encoding="utf-8")
        for needle in ("comp_range", "take_list", "undo: 'comp range'", "xfade_ms"):
            self.assertIn(needle, js)
        arr = (DAW / "js" / "arrange.js").read_text(encoding="utf-8")
        for needle in ("HX.takes.rows", "HX.takes.headers", "HX.takes.toggle", "HX.takes.drawLane", "HX.takes.pointerDown"):
            self.assertIn(needle, arr)
        self.assertIn("HX.takes.findClip", (DAW / "js" / "store.js").read_text(encoding="utf-8"))
        self.assertIn("HX.loadClipPeaks", (DAW / "js" / "regions.js").read_text(encoding="utf-8"))
        self.assertIsNone(re.search(r"""['"<]\s*\w*\s+on[a-z]+=["']""", js))   # no handler attributes


TAKES_STANDINS = r"""
var window = (typeof globalThis !== 'undefined') ? globalThis : this;
var handlers = {}, located = [], commits = [];
var tr = { id: 't1', name: 'Vox', kind: 'audio', clips: [{ id: 'c1', start: 0, len: 16, offs: 0, fadeIn: 0, fadeOut: 0, take: 1 }] };
var HX = window.HX = {
  S: { session: { name: 'Demo', tempo: 120, sampleRate: 48000, tracks: [tr] }, ui: { zoom: 10 } },
  h: function () { return {}; }, on: function (ev, f) { handlers[ev] = f; }, emit: function () {}, log: function () {},
  mcp: { connected: false, has: function () { return false; } }, arrange: {},
  track: function (id) { return id === 't1' ? tr : null; }, select: function () {}, locate: function (b) { located.push(b); },
  bbtStr: function (b) { return String(b); }, beatsToSamples: function (b) { return Math.round(b * 24000); },
  commit: function (label, ops) { commits.push(ops[0]); return Promise.resolve(); }
};
"""


class TakesScript(unittest.TestCase):
    """takes.js run against stand-ins: every comp is crossfaded (never a hard cut), and a tiny drag is a click."""

    def run_js(self, body):
        import json, subprocess
        from tests import _jscheck
        cmd = _jscheck.need_runner(self)
        src = TAKES_STANDINS + (DAW / "js" / "takes.js").read_text(encoding="utf-8") + "\n" + body
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "t.js"
            f.write_text(src, encoding="utf-8")
            r = subprocess.run(cmd + [str(f)], capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_comp_is_crossfaded_and_a_tiny_drag_is_a_click(self):
        r = self.run_js(r"""
var T = HX.takes, H = HX.opHandlers.takeComp;
var call = H.call({ trackId: 't1' }, { take: 2, takeId: 'k2', start: 4, end: 8 });
T.data.t1 = { takes: [{ id: 'k2', n: 2, clips: [{ id: 'k2c', start: 0, len: 16, offs: 0, fadeIn: 0, fadeOut: 0 }] }] };
H.apply({ trackId: 't1' }, { take: 2, takeId: 'k2', start: 4, end: 8 });
var comp = tr.clips.filter(function (c) { return c.take === 2; })[0];
var kept = tr.clips.filter(function (c) { return c.take !== 2; });
var lis = {}, wrap = { setPointerCapture: function () {}, addEventListener: function (k, f) { lis[k] = f; }, removeEventListener: function () {} };
var g = { rect: { left: 0 }, B: function (x) { return x / 10; }, snap: function (b) { return b; }, lanesWrap: wrap };
var hit = { beat: 4, row: { t: tr, take: T.data.t1.takes[0] } };
T.pointerDown({ pointerId: 1, metaKey: true }, hit, g);
lis.pointermove({ clientX: 40.1, metaKey: true }); lis.pointerup();              // 0.01 beat: a click
var clickOnly = located.length === 1 && commits.length === 0;
T.pointerDown({ pointerId: 1, metaKey: true }, hit, g);
lis.pointermove({ clientX: 80, metaKey: true }); lis.pointerup();                // 4 beats: a comp
print(JSON.stringify({ tool: call.tool, xfade: call.args.xfade_ms, constant: T.XFADE_MS,
  compIn: comp.fadeIn, compOut: comp.fadeOut, kept: kept.map(function (c) { return [c.fadeIn || 0, c.fadeOut || 0]; }),
  clickOnly: clickOnly, comps: commits.length, compArgs: commits.length ? [commits[0].after.start, commits[0].after.end] : null }));
""")
        self.assertEqual(r["tool"], "comp_range")
        self.assertGreaterEqual(r["xfade"], 5)                             # a crossfade at every join, never a hard cut
        self.assertEqual(r["xfade"], r["constant"])
        beat = 0.5                                                          # 120 BPM: a beat is half a second
        self.assertAlmostEqual(r["compIn"], r["xfade"] / 1000 / beat, places=6)    # the comp's own crossfades, in beats
        self.assertAlmostEqual(r["compOut"], r["xfade"] / 1000 / beat, places=6)
        self.assertEqual(len(r["kept"]), 2)
        self.assertGreater(r["kept"][0][1], 0)                              # the kept part before fades out under it
        self.assertGreater(r["kept"][1][0], 0)                              # and the part after fades in
        self.assertTrue(r["clickOnly"])
        self.assertEqual((r["comps"], r["compArgs"]), (1, [4, 8]))


class Assistant(unittest.TestCase):
    def test_takes_are_reads_and_a_comp_is_one_proposal(self):
        from hypnomix.app import daw_assist as DA
        self.assertTrue(DA.read_only({"name": "take_list"}))
        self.assertTrue(DA.read_only({"name": "playlist_list"}))
        for w in ("comp_range", "playlist_new", "playlist_select"):
            self.assertFalse(DA.read_only({"name": w}))

        def read(tool, args):
            return {"track_get_info": {"name": "Vocals"}, "session_get_info": {"sampleRate": 48000}}.get(tool)
        rows = DA.preview("comp_range", {"track_id": "454", "take": 2, "start_sample": 480000, "end_sample": 672000,
                                         "xfade_ms": 10}, read)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["what"], "Vocals · comp 10–14 s")
        self.assertIn("take 2, 10 ms crossfades (one undo step)", rows[0]["after"])


if __name__ == "__main__":
    unittest.main()
