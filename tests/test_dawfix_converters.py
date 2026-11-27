"""Converters group (review of the DAW branch): the timing fix for HypnoMix Studio and Live projects is by hand, not an edit."""
import unittest
from unittest import mock

from hypnomix import project
from tests import test_rpp


class TimingByHand(unittest.TestCase):
    """A nudge hypnomix writes only into REAPER projects: in a HypnoMix Studio or Live project the finding is `applies:
    manual` with no edit attached (fix skips edits; the hand-off checklist lists approved manual items)."""

    def setUp(self):                      # the same small REAPER project the REAPER tests use
        test_rpp.Reaper.setUp(self)

    def tearDown(self):
        test_rpp.Reaper.tearDown(self)

    def _finding(self, daw):
        from hypnomix.session import timing as TM
        from hypnomix.workflow import timing_project as TP
        p = project.load(self.song)
        lead = p.tracks[1]
        c = lead.clips[0]
        kind = next(iter(TM.SLOTS))
        hit = dict(clip=c, src=0.5, beat=2.0, t=0.5, track=lead.name)
        issue = dict(id="timing-1", hit=hit, kind=kind, off=0.03, move=-0.02, track=lead.name, ref="band", beat=2.0)
        notes = {"looseness": 0.01, "all_onsets": {id(c): [0.2, 0.5, 0.9]}}
        p.daw = daw
        with mock.patch.object(TP, "fixable", return_value=None):
            return TP.findings(p, [(lead.name, lead, [hit])], [dict(issue)], notes)[0]

    def test_reaper_writes_it_ardour_and_live_do_not(self):
        f = self._finding("reaper")
        self.assertEqual(f["applies"], "set")
        self.assertIn("edit", f)
        for daw in ("ardour", "live"):
            f = self._finding(daw)
            self.assertEqual(f["applies"], "manual", daw)
            self.assertNotIn("edit", f, daw)
            self.assertIn("by hand in", f["fix"])

    def test_an_optional_nudge_keeps_its_wording_when_by_hand(self):
        from hypnomix.session import timing as TM
        from hypnomix.workflow import timing_project as TP
        p = project.load(self.song)
        lead = p.tracks[1]
        c = lead.clips[0]
        hit = dict(clip=c, src=0.5, beat=2.0, t=0.5, track=lead.name)
        issue = dict(id="timing-1", hit=hit, kind=next(iter(TM.SLOTS)), off=0.03, move=-0.02, track=lead.name,
                     ref="band", beat=2.0, optional=True)
        p.daw = "ardour"
        with mock.patch.object(TP, "fixable", return_value=None):
            f = TP.findings(p, [(lead.name, lead, [hit])], [issue], {"looseness": 0.01,
                                                                       "all_onsets": {id(c): [0.2, 0.5, 0.9]}})[0]
        self.assertIn("a gentle partial move", f["fix"])
        self.assertEqual(f["applies"], "manual")


if __name__ == "__main__":
    unittest.main()
