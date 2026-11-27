"""Second review: the REAPER `devices` check and ReaComp's Dry/Wet mix, and the master-track note.

A ReaComp with Wet at 0 compresses nothing heard; one mixing dry and wet is parallel compression. Neither is judged
against the fully-wet targets, and neither gets a `set` fix. Synthetic projects only; nothing here opens REAPER.

Run from the repo root:  python -m unittest tests.test_review2_devices
"""
import unittest
from pathlib import Path

from hypnomix.workflow import devices_project as DP
from tests.test_reaper_devices import Isolated, g_devices, lead_project, reacomp, set_comp

ROOT = Path(__file__).resolve().parents[1]


class Mix(unittest.TestCase):
    def vals(self, dry, wet):
        v = [0.0] * 17
        v[10], v[11] = dry, wet
        return v

    def test_reapers_default_is_fully_wet(self):
        self.assertEqual(DP.mix(self.vals(3.16e-8, 1.0))[0], "wet")

    def test_wet_at_zero_is_dry(self):
        self.assertEqual(DP.mix(self.vals(1.0, 0.0))[0], "dry")

    def test_dry_and_wet_together_is_parallel(self):
        self.assertEqual(DP.mix(self.vals(1.0, 0.5))[0], "parallel")
        self.assertEqual(DP.mix(self.vals(3.16e-8, 0.5))[0], "parallel")   # wet turned down is a mix too

    def test_short_state_counts_as_wet(self):
        self.assertEqual(DP.mix([0.0] * 5)[0], "wet")


class DryWet(Isolated):
    def run_with(self, dry, wet):
        path = lead_project(self.dir / "p", reacomp("Vox comp"))
        set_comp(path, "Lead Vocal", 0, thresh=0.05, detector=0.0, dry=dry, wet=wet)
        return g_devices(path, self.dir / "scan")

    def test_a_fully_wet_reacomp_is_still_judged(self):
        out, _ = self.run_with(3.16e-8, 1.0)
        self.assertEqual([f["kind"] for f in out], ["compressor"])
        self.assertEqual(out[0]["applies"], "set")

    def test_wet_at_zero_is_not_judged_and_gets_no_fix(self):
        out, _ = self.run_with(1.0, 0.0)
        self.assertEqual([(f["kind"], f["applies"]) for f in out], [("reacomp-dry", "info")])
        self.assertNotIn("edit", out[0])
        self.assertIn("Wet at -inf dB", out[0]["problem"])
        self.assertNotIn("turns the part down", out[0]["problem"])

    def test_a_parallel_reacomp_is_listed_as_parallel_and_not_fixed(self):
        out, _ = self.run_with(1.0, 0.5)
        self.assertEqual([(f["kind"], f["applies"]) for f in out], [("reacomp-parallel", "info")])
        self.assertNotIn("edit", out[0])
        self.assertIn("parallel compression", out[0]["problem"])
        self.assertIn("dry (0 dB) and wet (-6 dB)", out[0]["problem"])

    def test_after_a_parallel_reacomp_a_second_one_is_not_judged(self):
        path = lead_project(self.dir / "p", reacomp("Par"), reacomp("Second"))
        set_comp(path, "Lead Vocal", 0, thresh=0.05, detector=0.0, dry=1.0, wet=0.5)
        set_comp(path, "Lead Vocal", 1, thresh=0.05, detector=0.0)
        out, _ = g_devices(path, self.dir / "scan")
        self.assertEqual([f["kind"] for f in out], ["reacomp-parallel", "unknown-level"])
        self.assertFalse(any(f["applies"] == "set" for f in out))


class MasterNote(Isolated):
    def test_the_notes_and_docstrings_say_the_master_is_not_read(self):
        path = lead_project(self.dir / "p", reacomp())
        _, notes = g_devices(path, self.dir / "scan")
        self.assertIn("the master track's plug-ins are not read", notes[0])
        self.assertIn("master track's plug-ins", DP.__doc__)
        scan = (ROOT / "hypnomix" / "workflow" / "scan_project.py").read_text(encoding="utf-8")
        self.assertIn("the master track's plug-ins are not read", scan)


if __name__ == "__main__":
    unittest.main()
