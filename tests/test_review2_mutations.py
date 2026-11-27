"""Second review of reaper-parity-031, finding 17: tests for the deliberate breaks that no test noticed in the first
mutation exercise. Each class names the break it is there to catch.

  EnvelopeTiming      new envelope points written late (0.05 s, 0.5 s); the 3 dB line-evening cap on the
                      per-track route
  EnvelopeTop         the +6 dB volume envelope top (MAX_LIN) raised
  CompressorJudging   the squash, release, drum-attack and usual-range limits loosened (one signal level or setting
                      just on each side of each limit)
  MixerFields         a message field renamed on one side only (mixer.py sends `file`, mixer.lua reads `a.path`)
  MixerLuaText        restore writing 0, solos not put back, the bar times shifted by one bar
  OverwriteGuards     each of the two "never overwrite" guards on its own (vocallevel's early check, rpp.save)

No Lua interpreter is used: MixerFields and MixerLuaText read mixer.lua and bridge.lua as text, which shows the code
says the right thing, not that it runs in REAPER."""
import ast
import contextlib
import io
import json
import re
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

import numpy as np

from hypnomix import project
from hypnomix.engineer import devices as D
from hypnomix.project import rpp
from hypnomix.project import rpp_edit as E
from hypnomix.session import vocallevel as VL
from hypnomix.workflow import vocallevel_project as VP
from tests.test_vocallevel_reaper import Base

REAPER = Path(__file__).resolve().parents[1] / "hypnomix" / "reaper"


def env_points(path, name):
    p = project.load(path)
    env = p.track(name).native.chunk("VOLENV2")
    return None if env is None else (E.points(env), E.is_fader(env))


def quiet(fn, *args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            return fn(*args), buf.getvalue()
        except SystemExit as e:
            return e.code, buf.getvalue()


# ---------------------------------------------------------------- envelope timing (1b, 1d, 2b)
class EnvelopeTiming(Base):
    def apply(self, *extra, strings=False, quiet_line=(7.0, 10.0, -3.5)):
        path = self.song(strings=strings, quiet=quiet_line)
        out, j = self.dir / "new.rpp", self.dir / "plan.json"
        code, text = quiet(VL.main, [str(path), *map(str, extra), "--apply", str(out), "--json", str(j)])
        self.assertEqual(code, 0, text)
        return path, out, json.loads(j.read_text(encoding="utf-8"))["gains"]

    def assert_follows_plan(self, out, name, segs):
        pts, fader = env_points(out, name)
        segs = [tuple(s) for s in segs]
        self.assertTrue(any(abs(g) > 1e-3 for _, _, g in segs), name)
        # every point written sits where the plan puts it: its value is the planned S-curve at its own time
        times = [t for t, _, _ in pts]
        want = VL.smooth_db(segs, times)
        for (t, v, _), d in zip(pts, want):
            self.assertAlmostEqual(20 * np.log10(max(v, 1e-12)), d, delta=1e-3, msg=f"{name} at {t:.2f} s")
        # and between points too: the envelope as REAPER plays it follows the plan on a fine grid
        grid = np.arange(0.0, 20.0, 0.025)
        got = np.array([20 * np.log10(max(E.value_at(pts, q, fader), 1e-12)) for q in grid])
        err = np.abs(got - VL.smooth_db(segs, grid))
        self.assertLess(float(err.max()), 0.05, f"{name}: off the plan by {err.max():.2f} dB at "
                                                f"{grid[int(err.argmax())]:.2f} s")
        # every new point is on the 0.1 s spacing of its change and inside a change window
        windows = [(e - VL.RAMP_S / 2 - VL.STEP_S - 1e-6, e + VL.RAMP_S / 2 + VL.STEP_S + 1e-6)
                   for a, b, _ in VL._steps(sorted(segs)) for e in (a, b)]
        for t in times[1:]:
            self.assertTrue(any(w0 <= t <= w1 for w0, w1 in windows), f"{name}: a point at {t:.2f} s is outside "
                                                                       f"every change")
        return pts

    def test_points_sit_on_the_plan_in_time(self):
        _, out, gains = self.apply()
        self.assert_follows_plan(out, "Harmony", gains["Harmony"])
        self.assert_follows_plan(out, "Vocals", gains["__group__"])

    def test_points_are_spaced_by_the_step(self):
        _, out, gains = self.apply()
        pts, _ = env_points(out, "Harmony")
        times = [t for t, _, _ in pts][1:]                     # the first is the envelope's own point at 0
        gaps = np.diff(times)
        inside = gaps[gaps < 0.5]                              # within one S-curve
        self.assertTrue(len(inside))
        self.assertTrue(np.allclose(inside, VL.STEP_S, atol=1e-6), inside)

    def test_line_evening_on_each_track_stays_within_3_db(self):
        _, out, gains = self.apply("--tracks", "Lead Vocal", "Harmony", strings=True, quiet_line=(7.0, 10.0, -5.5))
        pts, _ = env_points(out, "Lead Vocal")                 # the per-track route: the folder also holds Strings
        dbs = [20 * np.log10(max(v, 1e-12)) for _, v, _ in pts]
        self.assertLessEqual(max(abs(d) for d in dbs), VL.MAX_LINE_DB + 1e-6)
        self.assertGreater(max(dbs), VL.MAX_LINE_DB - 0.05)    # the 5.5 dB quiet line is held at the 3 dB cap
        self.assertEqual(VL.MAX_LINE_DB, 3.0)
        self.assert_follows_plan(out, "Lead Vocal", gains["__group__"])  # the evening, on the lead itself


# ---------------------------------------------------------------- envelope top (2d)
class EnvelopeTop(Base):
    def test_the_top_is_six_db(self):
        self.assertEqual(E.MAX_LIN, 2.0)
        self.assertAlmostEqual(20 * np.log10(E.MAX_LIN), 6.02, places=2)

    def test_a_point_is_never_set_above_the_top(self):
        path = self.song()
        t = project.load(path).track("Harmony")
        env = E.volume_envelope(t)
        E._set_point(env, 5.0, 5.0)                            # asked for +14 dB
        self.assertLessEqual(max(v for _, v, _ in E.points(env)), 2.0)

    def test_a_ride_between_six_and_eighteen_db_is_refused(self):
        path = self.song(lead_env=[(0, 1.0), (6.0, 3.0), (11.0, 3.0), (15.0, 1.0)])     # +9.5 dB in the window
        t = project.load(path).track("Lead Vocal")
        with self.assertRaises(ValueError) as cm:
            VP.write_gains(t, [(0.0, 6.75, 0.0), (6.75, 10.25, 2.0), (10.25, 20.0, 0.0)])
        self.assertIn("above +6 dB", str(cm.exception))


# ---------------------------------------------------------------- compressor judging (5b, 5c, 5d, 5e)
class CompressorJudging(unittest.TestCase):
    def judge(self, role="lead", median=4.0, f0=None, **c):
        comp = dict(attack=10.0, release=100.0, ratio=4.0, threshold=-20.0)
        comp.update(c)
        m = {"median": median, "loud": median + 2}
        x, act = np.zeros(4410, np.float32), np.ones(4410, bool)
        with mock.patch.object(D, "measure_comp", return_value=(np.zeros(4410), m)), \
                mock.patch.object(D, "fit_threshold", side_effect=lambda x, act, new, target: new):
            return D.judge_compressor(x, act, comp, role, 120.0, f0)[4]

    def has(self, problems, words):
        return any(words in p for p in problems)

    def test_squash_limit_is_one_and_a_half_times_the_top(self):
        lo, hi = D.TARGET["lead"]
        self.assertTrue(self.has(self.judge(median=1.5 * hi + 0.1), "squashes"))
        self.assertFalse(self.has(self.judge(median=1.5 * hi - 0.1), "squashes"))

    def test_barely_works_limit_is_half_the_bottom(self):
        lo, hi = D.TARGET["lead"]
        self.assertTrue(self.has(self.judge(median=0.5 * lo - 0.1), "barely works"))
        self.assertFalse(self.has(self.judge(median=0.5 * lo + 0.1), "barely works"))

    def test_release_under_two_cycles_of_the_lowest_note(self):
        f0 = 50.0                                              # two cycles: 40 ms
        self.assertTrue(self.has(self.judge("bass", f0=f0, release=39.0), "faster than two cycles"))
        self.assertFalse(self.has(self.judge("bass", f0=f0, release=41.0), "faster than two cycles"))
        self.assertTrue(self.has(self.judge("bass", f0=f0, release=10.0), "faster than two cycles"))

    def test_drum_attack_under_three_ms(self):
        self.assertTrue(self.has(self.judge("drums", median=3.0, attack=2.9), "clamps every transient"))
        self.assertFalse(self.has(self.judge("drums", median=3.0, attack=3.1), "clamps every transient"))
        self.assertFalse(self.has(self.judge("drums", median=0.9, attack=2.0), "clamps every transient"))

    def test_attack_outside_the_usual_range(self):
        (alo, ahi), _ = D.RANGES["lead"]
        self.assertTrue(self.has(self.judge(attack=alo - 0.5), "attack"))
        self.assertTrue(self.has(self.judge(attack=ahi + 0.5), "outside the usual"))
        self.assertFalse(self.has(self.judge(attack=(alo + ahi) / 2), "outside the usual"))

    def test_release_outside_the_usual_range(self):
        _, (rlo, rhi) = D.RANGES["lead"]
        self.assertTrue(self.has(self.judge(release=rlo - 1), "outside the usual"))
        self.assertTrue(self.has(self.judge(release=rhi + 1), "outside the usual"))
        self.assertFalse(self.has(self.judge(release=(rlo + rhi) / 2), "outside the usual"))
        self.assertFalse(self.has(self.judge(release=rhi + 1, auto_release=True), "outside the usual"))

    def test_the_ranges_and_targets_are_as_documented(self):
        self.assertEqual(D.RANGES["lead"], ((3, 30), (40, 300)))
        self.assertEqual(D.RANGES["drums"], ((5, 40), (40, 250)))
        self.assertEqual(D.TARGET["lead"], (3, 6))


# ---------------------------------------------------------------- mixer message fields (6d, 6e, 6f)
def lua_function(text, name):
    """The body of `function C.<name>(` up to its closing `end` at the same indent."""
    m = re.search(rf"^([ \t]*)function C\.{re.escape(name)}\(", text, re.M)
    if not m:
        return None
    ind = m.group(1)
    end = re.compile(rf"^{re.escape(ind)}end\b", re.M).search(text, m.end())
    return text[m.start():end.end() if end else len(text)]


def lua_fields(body):
    return set(re.findall(r"\ba\.(\w+)", body)) | set(re.findall(r"\ba\[\"(\w+)\"\]", body))


class MixerFields(unittest.TestCase):
    LUA = (REAPER / "mixer.lua").read_text(encoding="utf-8")
    BRIDGE = (REAPER / "bridge.lua").read_text(encoding="utf-8")

    def calls(self):
        """{command: set of keyword names} for every r.call("mixer_...", key=...) in mixer.py."""
        tree = ast.parse((REAPER / "mixer.py").read_text(encoding="utf-8"))
        out = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "call" and n.args \
                    and isinstance(n.args[0], ast.Constant) and str(n.args[0].value).startswith("mixer_"):
                out.setdefault(n.args[0].value, set()).update(k.arg for k in n.keywords if k.arg)
        return out

    def fields_read(self, name):
        body = lua_function(self.LUA, name)
        self.assertIsNotNone(body, name)
        fields = lua_fields(body)
        for other in re.findall(r"\bC\.(\w+)\s*,\s*a\b|\bC\.(\w+)\(a\)", body):     # a handed on: pcall(C.x, a)
            for o in other:
                if o:
                    sub = lua_function(self.LUA, o) or lua_function(self.BRIDGE, o)
                    self.assertIsNotNone(sub, o)
                    fields |= lua_fields(sub)
        return fields

    def test_every_field_python_sends_is_read_by_lua(self):
        calls = self.calls()
        self.assertGreaterEqual(set(calls), {"mixer_snapshot", "mixer_restore", "mixer_send", "mixer_solo_render"})
        for cmd, keys in calls.items():
            missing = keys - self.fields_read(cmd)
            self.assertFalse(missing, f"mixer.py sends {sorted(missing)} to {cmd}, which mixer.lua never reads")

    def test_the_known_fields(self):
        self.assertIn("file", self.fields_read("mixer_restore"))
        self.assertIn("tracks", self.fields_read("mixer_solo_render"))
        self.assertTrue({"start", "end", "path"} <= self.fields_read("mixer_solo_render"))
        self.assertIn("max_params", self.fields_read("mixer_snapshot"))


# ---------------------------------------------------------------- mixer.lua behaviour, as text (6i, 6j, 6k)
class MixerLuaText(unittest.TestCase):
    LUA = (REAPER / "mixer.lua").read_text(encoding="utf-8")

    def local_function(self, name):
        m = re.search(rf"^local function {name}\(", self.LUA, re.M)
        self.assertIsNotNone(m, name)
        end = re.compile(r"^end\b", re.M).search(self.LUA, m.end())
        return self.LUA[m.start():end.end()]

    def test_restore_writes_the_stored_values(self):
        body = self.local_function("restore_file")
        for call in ('reaper.SetMediaTrackInfo_Value(tr, p[2], v)', 'reaper.SetTrackSendInfo_Value(tr, 0, s, p[4], v)',
                     'reaper.TrackFX_SetParamNormalized(tr, fx, i, v)', 'reaper.TrackFX_SetEnabled(tr, fx, on)'):
            self.assertIn(call, body)
        self.assertIn("local v = tonumber(p[3])", body)                # info <KEY> <value>
        self.assertIn("local s, v = tonumber(p[2]), tonumber(p[5])", body)
        self.assertIn("local i, v = tonumber(p[2]), tonumber(p[3])", body)
        self.assertIn('local on = p[2] == "1"', body)
        for setter in re.findall(r"reaper\.(?:Set\w+|TrackFX_Set\w+)\(([^)]*)\)", body):
            self.assertRegex(setter, r",\s*(v|on)$", setter)           # never a constant

    def test_solo_render_puts_every_solo_back(self):
        body = lua_function(self.LUA, "mixer_solo_render")
        keep = body.index('keep[i] = reaper.GetMediaTrackInfo_Value(tr, "I_SOLO")')
        solo = body.index('"I_SOLO", want[guid_of(tr)] and 2 or 0')
        render = body.index("pcall(C.render_master, a)")
        back = body.index('reaper.SetMediaTrackInfo_Value(reaper.GetTrack(0, i), "I_SOLO", keep[i])')
        self.assertLess(keep, solo)
        self.assertLess(solo, render)
        self.assertLess(render, back)
        self.assertNotIn("return", body[render:back])                 # put back even when the render failed
        loop = body.rindex("for i = 0, reaper.CountTracks(0) - 1 do", 0, back)
        self.assertLess(render, loop)                                  # every track, after the render

    def test_bar_times_start_at_bar_one(self):
        body = lua_function(self.LUA, "mixer_timemap")
        self.assertIn("local bars, m = {}, 0", body)
        self.assertIn("reaper.TimeMap2_beatsToTime(0, 0, m)", body)    # measure m from 0: bars[1] is bar 1's start
        self.assertNotRegex(body, r"TimeMap2_beatsToTime\(0,\s*0,\s*m\s*[+-]")


# ---------------------------------------------------------------- the two overwrite guards, each alone (4a, 4b)
class OverwriteGuards(Base):
    def test_vocallevel_refuses_before_measuring(self):
        path = self.song()
        out = self.dir / "precious.rpp"
        out.write_text("precious", encoding="utf-8")
        a = Namespace(als=str(path), apply=str(out), json=None, renders=None, heard=None, tracks=None, melody=None,
                      order=None, lines_from=None, jump=1.5, upper_under=1.5, keep_ending=2, group=None)
        with mock.patch.object(VP, "signals", side_effect=AssertionError("measured before the check")), \
                mock.patch.object(rpp, "save", side_effect=AssertionError("reached rpp.save")):
            code, _ = quiet(VP.run, a)
        self.assertEqual(code, "--apply: precious.rpp already exists: choose a new name (nothing is ever overwritten)")
        self.assertEqual(out.read_text(encoding="utf-8"), "precious")

    def test_vocallevel_refuses_the_original_before_measuring(self):
        path = self.song()
        a = Namespace(als=str(path), apply=str(path), json=None, renders=None, heard=None, tracks=None, melody=None,
                      order=None, lines_from=None, jump=1.5, upper_under=1.5, keep_ending=2, group=None)
        with mock.patch.object(VP, "signals", side_effect=AssertionError("measured before the check")):
            code, _ = quiet(VP.run, a)
        self.assertIn("refusing to overwrite the original", str(code))

    def test_rpp_save_alone_refuses_the_original_and_a_missing_folder(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "Song.rpp"
            src.write_text('<REAPER_PROJECT 0.1 "7.86/macOS-arm64" 1\n  TEMPO 120 4 4\n>\n', encoding="utf-8")
            before = src.read_bytes()
            root = rpp.load(src)
            with self.assertRaises(SystemExit) as cm:
                rpp.save(root, src)
            self.assertIn("refusing to overwrite the original", str(cm.exception.code))
            self.assertEqual(src.read_bytes(), before)
            with self.assertRaises(SystemExit) as cm:
                rpp.save(root, Path(td) / "nowhere" / "new.rpp")
            self.assertIn("no such folder", str(cm.exception.code))
            other = Path(td) / "other.rpp"
            other.write_text("keep", encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                rpp.save(root, other)
            self.assertIn("already exists", str(cm.exception.code))
            self.assertEqual(other.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
