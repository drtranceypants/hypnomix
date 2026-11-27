"""Review fixes for the REAPER `devices` group (hypnomix/workflow/devices_project.py)."""
import unittest
from unittest import mock

from hypnomix import project as PJ
from hypnomix.workflow import devices_project as DP
from hypnomix.workflow import sidechain_project as SCP
from tests.test_reaper_devices import (Isolated, chain, g_devices, item, lead_project, no_highpass, reacomp, reaeq,
                                       set_comp, track, write_project)


def cur(ratio):
    return dict(threshold_db=-10.0, ratio=ratio, attack=10.0, release=100.0)


class Blend(unittest.TestCase):
    def test_a_partial_approval_from_inf_stays_partial(self):
        out = DP.blend(cur(1000.0), cur(4.0), 0.1)
        self.assertAlmostEqual(out["ratio"], 1 + (0.9 + 0.1 * 3 / 99) * 99, places=6)    # about 90:1
        self.assertTrue(80 < out["ratio"] < 100)

    def test_no_share_keeps_inf_and_a_full_share_reaches_the_suggestion(self):
        self.assertGreaterEqual(DP.blend(cur(1000.0), cur(4.0), 0.0)["ratio"], 999)
        self.assertEqual(DP.blend(cur(1000.0), cur(4.0), 1.0)["ratio"], 4.0)

    def test_finite_ratios_blend_linearly(self):
        self.assertAlmostEqual(DP.blend(cur(2.0), cur(4.0), 0.5)["ratio"], 3.0)

    def test_towards_inf_is_partial_too(self):
        r = DP.blend(cur(4.0), cur(1000.0), 0.5)["ratio"]
        self.assertTrue(4 < r < 999, r)


def two_leads(folder):
    body = item("Audio/vox.wav")
    return write_project(folder, [track("AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA", "Lead Vocal", body, extra=chain(reacomp())),
                                  track("CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC", "Lead Vocal", body, extra=chain(reacomp()))])


class Apply(Isolated):
    def edit_for(self, p, t):
        st = SCP.State(t.devices[0].native)
        return dict(op="reacomp", track=t.name, index=t.index, fx=0, cur=[float(v) for v in st.vals],
                    settings=dict(threshold_db=-20.0, ratio=4.0, attack=10.0, release=100.0))

    def test_the_recorded_index_picks_the_right_one_of_two_same_named_tracks(self):
        p = PJ.load(two_leads(self.dir / "p"))
        first, second = p.tracks[0], p.tracks[1]
        before = [float(v) for v in SCP.State(first.devices[0].native).vals]
        DP.apply(p, dict(id="devices-1"), self.edit_for(p, second))
        self.assertAlmostEqual(SCP.settings(SCP.State(second.devices[0].native).vals)["threshold_db"], -20.0, places=3)
        self.assertEqual([float(v) for v in SCP.State(first.devices[0].native).vals], before)

    def test_a_shared_name_with_no_index_match_is_refused(self):
        p = PJ.load(two_leads(self.dir / "p"))
        ed = self.edit_for(p, p.tracks[1])
        ed["index"] = 999
        with self.assertRaisesRegex(ValueError, "two tracks"):
            DP.apply(p, dict(id="devices-1"), ed)

    def test_a_reacomp_whose_knee_changed_since_the_scan_is_refused(self):
        path = lead_project(self.dir / "p", reacomp())
        p = PJ.load(path)
        ed = self.edit_for(p, p.tracks[0])
        set_comp(path, "Lead Vocal", 0, knee=0.5)
        p = PJ.load(path)
        with self.assertRaisesRegex(ValueError, "changed since the scan"):
            DP.apply(p, dict(id="devices-1"), ed)


class Review(Isolated):
    def test_same_named_tracks_are_not_judged_and_get_a_note(self):
        out, notes = g_devices(two_leads(self.dir / "p"), self.dir / "scan")
        self.assertFalse([f for f in out if f["kind"] == "compressor"], out)
        self.assertTrue(any("more than one track is called 'Lead Vocal'" in n for n in notes), notes)

    def test_an_unreadable_reaeq_does_not_produce_a_low_cut_finding(self):
        path = lead_project(self.dir / "p", reaeq())
        no_highpass(path, "Lead Vocal", 0)
        out, _ = g_devices(path, self.dir / "s1")
        self.assertTrue([f for f in out if f["kind"] == "eq-lowcut"], out)         # readable: suggested
        with mock.patch.object(DP.E, "ReaEQ", side_effect=ValueError("bad state")):
            out, notes = g_devices(path, self.dir / "s2")
        self.assertFalse([f for f in out if f["kind"] == "eq-lowcut"], out)
        self.assertTrue(any("not in a layout this check reads" in n for n in notes), notes)


if __name__ == "__main__":
    unittest.main()
