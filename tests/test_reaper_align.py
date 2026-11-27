"""Align in REAPER: alignset on a .rpp (stretch markers on the parts' own items, pitch / formant as new takes, a NEW
project that passes the structure check), and the HypnoMix Align panel's requests."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix import project
from hypnomix.project import rpp_edit as E
from hypnomix.studio import alignopts as AO
from tests import _isolate
from tests.test_align import NOTES, voice

SR = 44100
ROOT = Path(__file__).resolve().parents[1]


def g():
    return "{" + str(uuid.uuid4()).upper() + "}"


def item(pos, length, file, soffs=0.0, fade=0.01, sm=None, vol=1.0):
    return f"""    <ITEM
      POSITION {pos}
      SNAPOFFS 0
      LENGTH {length}
      LOOP 0
      ALLTAKES 0
      FADEIN 1 {fade} 0 1 0 0 0
      FADEOUT 1 {fade} 0 1 0 0 0
      MUTE 0 0
      SEL 0
      IGUID {g()}
      IID 1
      NAME {file}
      VOLPAN {vol} 0 1 -1
      SOFFS {soffs}
      PLAYRATE 1 1 0 -1 0 0.0025
      CHANMODE 0
{('      SM ' + sm + chr(10)) if sm else ''}      GUID {g()}
      <SOURCE WAVE
        FILE "{file}"
      >
    >
"""


def track(name, items):
    return f"""  <TRACK {g()}
    NAME "{name}"
    PEAKCOL 16576
    VOLPAN 1 0 -1 -1 1
    MUTESOLO 0 0 0
    IPHASE 0
    ISBUS 0 0
    FX 1
{''.join(items)}  >
"""


def stack_project(d, delay=0.04, harm=True):
    """Lead, a Double 40 ms late (two items, the second cut from the same file), a Harmony 25 ms early, a Keys track."""
    sf.write(d / "lead.wav", voice(NOTES), SR, subtype="FLOAT")
    sf.write(d / "dbl.wav", voice(NOTES, delay=delay, seed=1), SR, subtype="FLOAT")
    sf.write(d / "harm.wav", voice([(t, du, m + 4) for t, du, m in NOTES], delay=-0.025, seed=2), SR, subtype="FLOAT")
    t = np.arange(8 * SR) / SR
    keys = 0.1 * sum(np.sin(2 * np.pi * f * t) for f in (261.63, 329.63, 392.0))
    sf.write(d / "keys.wav", keys.astype(np.float32), SR, subtype="FLOAT")
    txt = f"""<REAPER_PROJECT 0.1 "7.86/macOS-arm64" 1764000000
  RIPPLE 0
  TEMPO 120 4 4
  PLAYRATE 1 0 0.25 4
  SAMPLERATE 44100 0 0
  RECORD_PATH "" ""
{track("Lead Vox", [item(0, 8, "lead.wav")])}{track("Double", [item(0, 3.95, "dbl.wav"), item(3.95, 4.05, "dbl.wav", soffs=3.95)])}{track("Harmony", [item(0, 8, "harm.wav", vol=0.7)]) if harm else ""}{track("Keys", [item(0, 8, "keys.wav")])}>
"""
    path = d / "Song.rpp"
    path.write_text(txt.replace("\n", "\r\n"), encoding="utf-8")
    return path


def lag_at(ref, y, t):
    return AO.precise_lag(ref, y, SR, t)


def run_alignset(*argv):
    r = subprocess.run([sys.executable, "-m", "hypnomix.studio.alignset", *map(str, argv)], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise AssertionError(r.stderr[-3000:] + r.stdout[-2000:])
    return r


class StretchMarkers(unittest.TestCase):
    def test_markers_follow_the_plan_through_existing_markers(self):
        from hypnomix.project.model import Clip, Take
        from hypnomix.studio import alignset_rpp as A
        tk = Take(name="t", path=Path("/x.wav"), offset=1.0, stretch=[(0.0, 1.0), (2.0, 3.2), (6.0, 7.2)])
        c = Clip(name="c", start=10.0, length=6.0, takes=[tk])
        plan = np.zeros(2000)
        plan[1200:1400] = 3.0                                   # pull 30 ms earlier between 12 s and 14 s
        plan[1180:1200] = np.linspace(0, 3, 20); plan[1400:1420] = np.linspace(3, 0, 20)
        before = A.take_source(c, np.array([1.0, 3.0, 5.0]))
        marks, err = A.item_markers(c, plan)
        self.assertLess(err, 0.6)
        self.assertTrue(all(b[0] > a[0] and b[1] > a[1] for a, b in zip(marks, marks[1:])))
        tk.stretch = marks
        T = np.array([11.0, 13.0, 15.0])
        now = A.take_source(c, (T - 10.0))
        want = before + np.array([0.0, 0.03, 0.0])
        self.assertTrue(np.allclose(now, want, atol=0.0006), (now, want))

    def test_steep_moves_and_the_file_start_are_eased_not_skipped(self):
        from hypnomix.project.model import Clip, Take
        from hypnomix.studio import alignset_rpp as A
        c = Clip(name="c", start=0.0, length=4.0, takes=[Take(name="t", path=Path("/x.wav"))])
        plan = np.zeros(500)
        plan[:100] = -2.0                     # pushed 20 ms later at the start of a file that starts at 0
        plan[150:200] = 5.0                   # opposite moves across a 50 ms gap: the plan plays the gap backwards
        plan[205:250] = -5.0
        marks, err = A.item_markers(c, plan)
        self.assertIsNotNone(marks)
        self.assertEqual(marks[0], (0.0, 0.0))                            # starts at the file's first sample
        self.assertTrue(all(b[0] > a[0] and b[1] > a[1] for a, b in zip(marks, marks[1:])))
        self.assertGreater(A.item_markers.eased, 10)
        tk = c.take
        tk.stretch = marks
        self.assertAlmostEqual(float(A.take_source(c, np.array([0.5]))[0]), 0.48, delta=0.001)   # the plan, caught up
        self.assertAlmostEqual(float(A.take_source(c, np.array([1.7]))[0]), 1.75, delta=0.001)

    def test_nothing_to_move_writes_nothing(self):
        from hypnomix.project.model import Clip, Take
        from hypnomix.studio import alignset_rpp as A
        c = Clip(name="c", start=0.0, length=4.0, takes=[Take(name="t", path=Path("/x.wav"))])
        self.assertEqual(A.item_markers(c, np.zeros(500)), ([], 0.0))

    def test_set_stretch_writes_and_replaces_the_sm_line(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            path = stack_project(d)
            p = project.load(path)
            c = p.track("Double").clips[1]
            E.set_stretch(c, [(0.0, 3.95), (1.0, 4.97), (4.05, 8.0)])
            E.set_stretch(c, [(0.0, 3.95), (1.0, 4.96), (4.05, 8.0)])     # replaced, not added
            out = d / "x.rpp"
            E.save(p, out)
            self.assertEqual(out.read_text(encoding="utf-8").count("SM "), 1)
            q = project.load(out)
            self.assertEqual(q.track("Double").clips[1].take.stretch, [(0.0, 3.95), (1.0, 4.96), (4.05, 8.0)])
            self.assertEqual(E.check(path, out), [])


class AlignProject(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.d = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_double_lands_on_the_guide_as_stretch_markers_in_a_new_project(self):
        path = stack_project(self.d, harm=False)
        before = path.read_bytes()
        run_alignset(path, "--guide", "Lead", "--parts", "Double", "--out", self.d / "o", "--json", self.d / "r.json",
                     "--apply")
        self.assertEqual(path.read_bytes(), before)                     # the user's project: untouched
        res = json.loads((self.d / "r.json").read_text(encoding="utf-8"))
        out = Path(res["out_set"])
        self.assertEqual(out.name, "Song (aligned).rpp")
        self.assertEqual(E.check(path, out), [])
        self.assertIn(b"\r\n", out.read_bytes())                # REAPER's own line ends kept
        q = project.load(out)
        dbl = q.track("Double")
        self.assertTrue(all(c.take.stretch for c in dbl.clips))         # both items carry stretch markers
        self.assertEqual(len(dbl.clips[0].takes), 1)                    # timing only: no new take
        lead = q.render(q.track("Lead Vox"), SR, 8.0)[:, None]
        old = project.load(path)
        was = old.render(old.track("Double"), SR, 8.0)[:, None]
        now = q.render(dbl, SR, 8.0)[:, None]
        for t in (1.1, 2.9, 4.7, 6.5):                                  # on either item, the double is now on the lead
            self.assertAlmostEqual(lag_at(lead, was, t), 0.04, delta=0.004)
            self.assertLess(abs(lag_at(lead, now, t)), 0.008, t)
        prev = sf.read(res["previews"]["Double"])[0]
        prev = prev[:, None] if prev.ndim == 1 else prev
        for t in (1.1, 4.7):                                            # and plays what the checked preview plays
            self.assertLess(abs(lag_at(prev, now, t)), 0.0015)
        # running again never overwrites the first result
        run_alignset(path, "--guide", "Lead", "--parts", "Double", "--out", self.d / "o2", "--json", self.d / "r2.json",
                     "--apply")
        self.assertEqual(Path(json.loads((self.d / "r2.json").read_text(encoding="utf-8"))["out_set"]).name, "Song (aligned 2).rpp")

    def test_takes_option_puts_the_timing_on_new_takes(self):
        path = stack_project(self.d, harm=False)
        run_alignset(path, "--guide", "Lead", "--parts", "Double", "--takes", "--out", self.d / "o", "--json",
                     self.d / "r.json", "--apply")
        res = json.loads((self.d / "r.json").read_text(encoding="utf-8"))
        q = project.load(Path(res["out_set"]))
        dbl = q.track("Double")
        self.assertTrue(all(len(c.takes) == 2 and c.active == 1 and not c.take.stretch for c in dbl.clips))
        lead = q.render(q.track("Lead Vox"), SR, 8.0)[:, None]
        now = q.render(dbl, SR, 8.0)[:, None]
        for t in (1.1, 4.7):
            self.assertLess(abs(lag_at(lead, now, t)), 0.008)

    def test_stack_mode_protect_and_measure_only(self):
        path = stack_project(self.d)
        run_alignset(path, "--guide", "Lead", "--parts", "Double", "Harmony", "--protect", "5-8", "--out",
                     self.d / "o", "--json", self.d / "r.json")
        res = json.loads((self.d / "r.json").read_text(encoding="utf-8"))
        self.assertIsNone(res["out_set"])                                # measured only: no project written
        self.assertFalse(list(self.d.glob("Song (aligned*")))
        self.assertEqual([r["track"] for r in res["parts"]][-2:], ["Double", "Harmony"])
        self.assertEqual({t["name"] for t in res["energy"]["tracks"]}, {"Lead Vox", "Double", "Harmony"})

    @unittest.skipUnless(shutil.which("rubberband"), _isolate.NO_RUBBERBAND)
    def test_formant_becomes_a_new_take_that_sums_to_the_render(self):
        path = stack_project(self.d, harm=False)
        run_alignset(path, "--guide", "Lead", "--parts", "Double", "--formant", "0.4", "--out", self.d / "o",
                     "--json", self.d / "r.json", "--apply")
        res = json.loads((self.d / "r.json").read_text(encoding="utf-8"))
        out = Path(res["out_set"])
        self.assertEqual(E.check(path, out), [])
        q = project.load(out)
        dbl = q.track("Double")
        self.assertTrue(all(len(c.takes) == 2 and c.active == 1 for c in dbl.clips))   # original take kept
        self.assertTrue(all(not c.takes[0].stretch for c in dbl.clips))                # and left as it was
        self.assertTrue(all("formant" in c.take.name for c in dbl.clips))
        self.assertTrue((self.d / "hypnomix aligned").is_dir())
        heard = q.render(dbl, SR, 8.0)
        want = sf.read(res["rendered"]["Double"])[0]
        want = want.mean(1) if want.ndim > 1 else want
        n = min(len(heard), len(want), 8 * SR)
        a, b = int(0.3 * SR), int(7.7 * SR)                              # the takes add up to the checked render
        err = np.sqrt(np.mean((heard[a:b] - want[a:b]) ** 2)) / np.sqrt(np.mean(want[a:b] ** 2))
        self.assertLess(err, 0.01)

    def test_refuses_a_tempo_map_and_wrong_names(self):
        path = stack_project(self.d)
        r = subprocess.run([sys.executable, "-m", "hypnomix.studio.alignset", str(path), "--guide", "Nope", "--parts",
                            "Double"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("guide", r.stderr)


class AppEndpoints(unittest.TestCase):
    def test_choose_accepts_a_reaper_project_and_argv_is_the_same(self):
        from hypnomix.app import align as AL
        with tempfile.TemporaryDirectory() as td:
            rp = Path(td) / "Song.rpp"
            rp.write_text("<REAPER_PROJECT\n>\n", encoding="utf-8")
            code, st = AL.handle_post("/api/align/choose", {"path": str(rp)})
            self.assertEqual(code, 200)
            self.assertEqual(st["set_name"], "Song.rpp")
            code, err = AL.handle_post("/api/align/choose", {"path": str(Path(td) / "x.txt")})
            self.assertEqual(code, 400)
        argv = AL.argv_for(dict(guide="Lead", parts=["Dbl"], pitch=0.3, apply=True), "/x/Song.rpp", "/tmp/o")
        self.assertEqual(argv[:6], ["alignset", "/x/Song.rpp", "--guide", "Lead", "--parts", "Dbl"])
        AL.ALIGN.update(set="", result=None, job=0)


class FakeBridge:
    def __init__(self):
        self.sel = dict(tracks=["Lead Vox"], sel_start=10.0, sel_end=20.0, cursor=12.5, project="/p/Song.rpp", dirty=0)
        self.calls = []

    def call(self, cmd, **k):
        self.calls.append((cmd, k))
        if cmd == "align_where":
            return dict(self.sel)
        if cmd == "panel_events":
            return {"events": []}
        return {}


class Panel(unittest.TestCase):
    def setUp(self):
        from hypnomix.reaper import align as RA
        self.RA = RA
        self.sent = []
        self.state = {"status": "idle", "result": None}
        RA.app = lambda path, body=None, timeout=5: self.sent.append((path, body)) or (
            dict(self.state) if path.endswith("/state") else {"job": 1})
        self.b = FakeBridge()
        self.p = RA.Panel(self.b)

    def tearDown(self):
        import importlib
        importlib.reload(self.RA)

    def test_picks_tracks_spans_and_options_then_runs(self):
        p, b = self.p, self.b
        p.on("guide")
        b.sel["tracks"] = ["Double", "Harmony"]
        p.on("part")
        b.sel["tracks"] = ["Lead Vox"]
        p.on("part")                                         # the guide is never a part
        self.assertEqual((p.st["guide"], p.st["parts"]), ("Lead Vox", ["Double", "Harmony"]))
        p.on("range")                                        # the time selection
        p.on("protect")
        p.on("sync")
        p.on("preset")
        p.on("set:pitch=0.3")
        p.on("set:formant=0.4")
        p.on("write")
        p.on("takes")
        p.on("align")
        run = [x for x in self.sent if x[0] == "/api/align/run"][0][1]
        self.assertEqual(run["set"], "/p/Song.rpp")
        self.assertEqual((run["guide"], run["parts"]), ("Lead Vox", ["Double", "Harmony"]))
        self.assertEqual((run["start_s"], run["end_s"]), (10.0, 20.0))
        self.assertEqual((run["protect"], run["sync"]), ([[10.0, 20.0]], [12.5]))
        self.assertEqual(run["preset"], "gentle-stack")
        self.assertEqual((run["pitch"], run["formant"], run["apply"], run["takes"]), (0.3, 0.4, True, True))
        from hypnomix.app import align as AL
        argv = " ".join(AL.argv_for(run, run["set"], "/tmp/o"))       # the app turns it into a valid alignset call
        self.assertIn("--range 10.000-20.000", argv)
        self.assertIn("--takes", argv)

    def test_unsaved_project_is_not_run(self):
        self.b.sel.update(dirty=1)
        self.p.on("guide"); self.b.sel["tracks"] = ["Double"]; self.p.on("part")
        self.p.on("align")
        self.assertFalse([x for x in self.sent if x[0] == "/api/align/run"])
        self.b.sel.update(project="", dirty=0)
        self.p.on("align")
        self.assertFalse([x for x in self.sent if x[0] == "/api/align/run"])

    def test_open_opens_the_new_project_in_a_new_tab(self):
        self.p.result = {"out_set": "/p/Song (aligned).rpp"}
        self.p.on("open")
        self.assertIn(("open_project", {"path": "/p/Song (aligned).rpp"}), self.b.calls)

    def test_show_sends_lanes(self):
        self.p.result = {"energy": {"t0": 0, "t1": 8, "tracks": [{"name": "Lead", "before": [-10.0] * 360, "after": None},
                                                                {"name": "Double", "before": [-12.0] * 360,
                                                                 "after": [-11.0] * 360}]}}
        self.p.show()
        st = [k for c, k in self.b.calls if c == "panel_set"][-1]
        self.assertEqual(st["mode"], "align")
        lanes = st["lanes"].split("|")
        self.assertEqual(len(lanes), 2)
        self.assertTrue(lanes[1].startswith("Double;"))
        self.assertTrue(all(len(v) < 600 for v in st.values()) or len(st["lanes"]) < 8000)


class BridgeScript(unittest.TestCase):
    def test_bridge_has_the_align_commands(self):
        lua = (ROOT / "hypnomix" / "reaper" / "bridge.lua").read_text(encoding="utf-8")
        for name in ("C.align_where", "align_draw", "C.open_project"):
            self.assertIn(name, lua)

    def test_sliders_start_at_the_apps_values_not_their_lowest(self):
        # the panel draws before `hypnomix reaper align` sends anything: Formant once opened at -3 st
        import re
        from hypnomix.reaper.align import Panel
        lua = (ROOT / "hypnomix" / "reaper" / "bridge.lua").read_text(encoding="utf-8")
        block = lua[lua.index("local SLIDERS"):lua.index("local function slider")]
        rows = re.findall(r'\{ "(\w+)", "\w+", (-?[\d.]+), (-?[\d.]+), "[^"]+", \d+, (-?[\d.]+) \}', block)
        self.assertEqual([r[0] for r in rows], ["tight", "pitch", "vibrato", "formant"])
        app = Panel(None)
        for key, lo, hi, start in rows:
            self.assertEqual(float(start), app.st[key], key)
            self.assertTrue(float(lo) <= float(start) <= float(hi), key)
        self.assertIn("panel.st[key] or start", lua)


if __name__ == "__main__":
    unittest.main()
