"""Third review of reaper-parity-031: the REAPER mixer tools and the devices / vocallevel thresholds.

`reaper snapshot OUT.json` asks REAPER before it makes any folder and never replaces a file that appears while it
waits; `reaper diagnose` gives every run its own numbered folder; a track reference is a number only when it is
plain digits; and the ReaComp Dry/Wet limits and the vocallevel hot-point check are pinned by tests that fail if
they change. Fake bridge and synthetic projects only; nothing here opens REAPER.

Run from the repo root:  python -m unittest tests.test_review3_mixer
"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hypnomix import project
from hypnomix.reaper import mixer as MX
from hypnomix.reaper.client import ReaperError
from hypnomix.workflow import devices_project as DP
from hypnomix.workflow import vocallevel_project as VP
from tests.test_reaper_devices import Isolated, g_devices, lead_project, reacomp, set_comp
from tests.test_reaper_mixer import FakeBridge, snap
from tests.test_vocallevel_reaper import Base as VocalBase


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


class Temp(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()


# ------------------------------------------------------------------ snapshot
class Unreachable(FakeBridge):
    def call(self, cmd, **k):
        raise ReaperError("REAPER is not running")


class RacingBridge(FakeBridge):
    """Someone writes OUT while REAPER is taking the snapshot."""
    def __init__(self, folder, out):
        super().__init__(folder)
        self.out = Path(out)

    def call(self, cmd, **k):
        if cmd == "mixer_snapshot":
            self.out.write_text("written meanwhile", encoding="utf-8")
        return super().call(cmd, **k)


class SnapshotOrder(Temp):
    def test_no_folder_is_made_when_reaper_cannot_be_reached(self):
        out = self.dir / "typo" / "deeper" / "s.json"
        with self.assertRaises(ReaperError):
            MX.main_snapshot([str(out)], r=Unreachable(self.dir))
        self.assertFalse((self.dir / "typo").exists())

    def test_a_missing_folder_is_still_made_after_the_snapshot(self):
        out = self.dir / "new" / "s.json"
        with quiet():
            MX.main_snapshot([str(out)], r=FakeBridge(self.dir))
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["tracks"][0]["name"], "MASTER")

    def test_a_file_that_appears_while_reaper_answers_is_not_replaced(self):
        out = self.dir / "s.json"
        with self.assertRaises(SystemExit) as cm:
            MX.main_snapshot([str(out)], r=RacingBridge(self.dir, out))
        self.assertIn("already exists", str(cm.exception.code))
        self.assertEqual(out.read_text(encoding="utf-8"), "written meanwhile")


# ------------------------------------------------------------------ diagnose
class PingBridge(FakeBridge):
    def ping(self):
        return self.call("ping")


class DiagnoseRuns(Temp):
    def run_once(self, b):
        buf = io.StringIO()
        with mock.patch.object(MX, "_out", lambda *parts: self.dir.joinpath(*parts)), \
                contextlib.redirect_stdout(buf):
            MX.main_diagnose(["--bars", "2"], r=b)
        return buf.getvalue()

    def test_each_run_gets_its_own_folder_and_an_earlier_run_is_kept(self):
        base = self.dir / "diagnose" / "reaper-Song"
        first = self.run_once(PingBridge(self.dir))
        run1 = base / "run-001"
        self.assertIn(f"are in {run1}", first)
        before = {p.name: p.read_bytes() for p in run1.iterdir()}
        self.assertIn("diagnose.json", before)
        self.assertIn("whole.wav", before)
        second = self.run_once(PingBridge(self.dir))
        self.assertIn(f"are in {base / 'run-002'}", second)
        self.assertTrue((base / "run-002" / "diagnose.json").is_file())
        self.assertEqual({p.name: p.read_bytes() for p in run1.iterdir()}, before)
        self.assertFalse((base / "diagnose.json").exists())

    def test_the_next_number_follows_the_highest_one(self):
        base = self.dir / "b"
        (base / "run-005").mkdir(parents=True)
        (base / "run-005" / "keep.txt").write_text("keep", encoding="utf-8")
        self.assertEqual(MX.run_folder(base).name, "run-006")
        self.assertEqual(MX.run_folder(base).name, "run-007")
        self.assertEqual((base / "run-005" / "keep.txt").read_text(encoding="utf-8"), "keep")

    def test_the_help_says_each_run_gets_its_own_folder(self):
        self.assertIn("run-001, run-002", MX.__doc__)


# ------------------------------------------------------------------ track references
class OddNames(unittest.TestCase):
    def odd(self):
        s = snap()
        for t, name in zip([t for t in s["tracks"] if not t.get("master")], ("1_0", "0x10", "nan", "inf")):
            t["name"] = name
        return s

    def test_odd_names_are_names_not_numbers(self):
        s = self.odd()
        for name, index in (("1_0", 0), ("0x10", 1), ("nan", 2), ("inf", 3)):
            self.assertEqual(MX._find(s, name)["index"], index, name)

    def test_plain_digits_are_an_index(self):
        s = snap()
        self.assertEqual(MX._find(s, "1")["name"], "Kick")
        self.assertEqual(MX._find(s, "1.0")["name"], "Kick")
        self.assertEqual(MX._find(s, " 2 ")["name"], "Lead Vocal")
        self.assertEqual(MX._find(s, "-0")["name"], "Drums")
        self.assertIsNone(MX._find(s, "1.5"))
        self.assertIsNone(MX._find(s, "-1"))                 # the master is only ever "master"
        self.assertTrue(MX._find(s, "master")["master"])

    def test_nudge_on_an_odd_name_changes_that_same_track_by_its_index(self):
        b = FakeBridge(".")
        b.snap = self.odd()
        MX.apply_change(b, "nudge 0x10 -1")
        self.assertEqual(b.calls[-1][0], "set_track")
        self.assertEqual(b.calls[-1][1]["track"], "1")       # the track named 0x10, never track 16
        self.assertAlmostEqual(b.calls[-1][1]["volume_db"], MX.db(0.5) - 1, 6)


# ------------------------------------------------------------------ devices: ReaComp Dry/Wet limits
def vals(dry, wet):
    v = [0.0] * 17
    v[10], v[11] = dry, wet
    return v


def amp(db):
    return 10 ** (db / 20)


class DryWetLimits(unittest.TestCase):
    def test_dry_at_minus_20_db_with_full_wet_is_parallel(self):        # FULL_DRY is -30 dB
        self.assertEqual(DP.mix(vals(amp(-20), 1.0))[0], "parallel")
        self.assertEqual(DP.mix(vals(amp(-31), 1.0))[0], "wet")

    def test_wet_at_minus_80_db_is_dry(self):                            # NO_WET is -60 dB
        self.assertEqual(DP.mix(vals(1.0, amp(-80)))[0], "dry")
        self.assertEqual(DP.mix(vals(1.0, amp(-59)))[0], "parallel")

    def test_wet_at_minus_3_db_with_no_dry_is_parallel(self):            # FULL_WET is -1 dB
        self.assertEqual(DP.mix(vals(0.0, 0.7))[0], "parallel")
        self.assertEqual(DP.mix(vals(0.0, amp(-0.5)))[0], "wet")

    def test_the_limits_are_as_documented(self):
        self.assertAlmostEqual(DP.FULL_DRY, amp(-30), 12)
        self.assertAlmostEqual(DP.FULL_WET, amp(-1), 12)
        self.assertAlmostEqual(DP.NO_WET, amp(-60), 12)


class AfterAQuietDryPath(Isolated):
    def test_wet_at_zero_and_dry_at_half_leaves_the_next_reacomp_unjudged(self):
        path = lead_project(self.dir / "p", reacomp("Off"), reacomp("Second"))
        set_comp(path, "Lead Vocal", 0, thresh=0.05, detector=0.0, dry=0.5, wet=0.0)
        set_comp(path, "Lead Vocal", 1, thresh=0.05, detector=0.0)
        out, _ = g_devices(path, self.dir / "scan")
        self.assertEqual([f["kind"] for f in out], ["reacomp-dry", "unknown-level"])
        self.assertIn("level reaching 'Second' is unknown", out[1]["problem"])
        self.assertFalse(any(f["applies"] == "set" for f in out))

    def test_wet_at_zero_and_dry_at_unity_still_judges_the_next_one(self):
        path = lead_project(self.dir / "p", reacomp("Off"), reacomp("Second"))
        set_comp(path, "Lead Vocal", 0, thresh=0.05, detector=0.0, dry=1.0, wet=0.0)
        set_comp(path, "Lead Vocal", 1, thresh=0.05, detector=0.0)
        out, _ = g_devices(path, self.dir / "scan")
        self.assertEqual([f["kind"] for f in out], ["reacomp-dry", "compressor"])


# ------------------------------------------------------------------ vocallevel: a hot point the plan does not move
class HotPointInTheWindow(VocalBase):
    def test_a_narrow_hot_point_inside_the_window_is_refused(self):
        """A +8 dB point at 5.75 s sits in the first change window (5.7-7.1 s for a change at 7-10 s), where the
        curve has not started yet, between two points at 0 dB: it is not moved and no new point reads it, so only
        the window check sees it."""
        path = self.song(lead_env=[(0, 1.0), (5.72, 1.0), (5.75, 2.5), (5.78, 1.0), (20.0, 1.0)])
        p = project.load(path)
        with self.assertRaises(ValueError) as cm:
            VP.write_gains(p.track("Lead Vocal"), [(7.0, 10.0, 2.0)])
        self.assertIn("above +6 dB in the change window (at 5.75 s)", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
