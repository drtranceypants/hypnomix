"""Clean-up: retiring switched-off tracks, consolidating one instrument's tracks, and check's id matching."""
import gzip, tempfile, unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from hypnomix.session import tidy as C
from hypnomix.session import check as K


def track(tid, name, on=True, group="-1", clips=(), fader="1", devices="<Eq8><On><Manual Value=\"true\"/></On></Eq8>",
          sidechain_from=None, kind="AudioTrack"):
    cl = "".join(f'<AudioClip Id="{k}"><CurrentStart Value="{a}"/><CurrentEnd Value="{b}"/>'
                 f'<SampleVolume Value="1"/></AudioClip>' for k, (a, b) in enumerate(clips))
    sc = f'<Routing><Target Value="AudioIn/Track.{sidechain_from}/PostFxOut"/></Routing>' if sidechain_from else ""
    return (f'<{kind} Id="{tid}"><Name><EffectiveName Value="{name}"/><UserName Value="{name}"/></Name>'
            f'<TrackGroupId Value="{group}"/>'
            f'<DeviceChain><AudioOutputRouting><Target Value="AudioOut/Main"/></AudioOutputRouting>'
            f'<Mixer><Speaker><Manual Value="{"true" if on else "false"}"/><AutomationTarget Id="{tid}00"/></Speaker>'
            f'<Volume><Manual Value="{fader}"/></Volume><Pan><Manual Value="0"/></Pan><Sends/></Mixer>'
            f'<MainSequencer><Sample><ArrangerAutomation><Events>{cl}</Events></ArrangerAutomation></Sample></MainSequencer>'
            f'<DeviceChain><Devices>{devices}{sc}</Devices></DeviceChain></DeviceChain>'
            f'<AutomationEnvelopes><Envelopes/></AutomationEnvelopes></{kind}>')


def song(*tracks):
    return ET.fromstring(f'<Ableton Creator="Ableton Live 12" MinorVersion="12.0"><LiveSet><NextPointeeId Value="9999"/>'
                         f'<Tracks>{"".join(tracks)}</Tracks></LiveSet></Ableton>')


class Retire(unittest.TestCase):
    def test_off_tracks_go_unless_something_listens_or_kept(self):
        r = song(track(1, "Gtr"), track(2, "Gtr old", on=False), track(3, "Vox take", on=False),
                 track(4, "Comp", devices="", sidechain_from=3), track(5, "Keys copy", on=False))
        plan = C.retire_plan(r, keep=["Keys copy"])
        why = {C.name(t): w for t, w in plan}
        self.assertIsNone(why["Gtr old"])
        self.assertIn("Comp", why["Vox take"])
        self.assertEqual(why["Keys copy"], "you said keep it")
        self.assertEqual(C.retire(r, plan), ["Gtr old"])
        self.assertEqual([C.name(t) for t in r.find(".//Tracks")], ["Gtr", "Vox take", "Comp", "Keys copy"])

    def test_bottom_mode_keeps_group_blocks_together(self):
        r = song(track(10, "Vox", kind="GroupTrack"), track(11, "Old vox", on=False, group="10"), track(12, "Lead", group="10"),
                 track(13, "Bass"))
        C.retire(r, C.retire_plan(r), mode="bottom")
        self.assertEqual([C.name(t) for t in r.find(".//Tracks")], ["Vox", "Lead", "old: Old vox", "Bass"])


class Consolidate(unittest.TestCase):
    def test_same_sound_no_overlap_merges_and_removes_empty_track(self):
        r = song(track(1, "Gtr A", clips=[(0, 16), (32, 48)]), track(2, "Gtr B", clips=[(16, 32)]))
        plan = C.merge_plan(r, {"Gtr A": "Guitar 1", "Gtr B": "Guitar 2"})
        self.assertEqual(len(plan), 1)
        self.assertEqual(C.merge(r, plan[0]), 1)
        ts = list(r.find(".//Tracks"))
        self.assertEqual([C.name(t) for t in ts], ["Gtr A"])
        self.assertEqual([C.span(c) for c in C.clips(ts[0])], [(0, 16), (16, 32), (32, 48)])
        self.assertEqual(len({c.get("Id") for c in C.clips(ts[0])}), 3)

    def test_overlap_stays_and_fader_difference_goes_to_clip_gain(self):
        r = song(track(1, "Gtr A", clips=[(0, 16), (32, 48)]), track(2, "Gtr B", clips=[(16, 32), (40, 44)], fader="0.5"))
        m = C.merge_plan(r, {"Gtr A": "Guitar", "Gtr B": "Guitar"})[0]
        self.assertEqual(len(m["stay"]), 1)
        C.merge(r, m)
        a, b = list(r.find(".//Tracks"))
        moved = [c for c in C.clips(a) if C.span(c) == (16, 32)][0]
        self.assertAlmostEqual(float(moved.find("./SampleVolume").get("Value")), 0.5, places=4)
        self.assertEqual([C.span(c) for c in C.clips(b)], [(40, 44)])     # the overlapping clip stays

    def test_different_sound_or_instrument_is_left_alone(self):
        r = song(track(1, "Gtr A", clips=[(0, 4)]), track(2, "Gtr B", clips=[(8, 12)], devices=""))
        self.assertEqual(C.merge_plan(r, {"Gtr A": "Guitar", "Gtr B": "Guitar"}), [])
        r = song(track(1, "A", clips=[(0, 4)]), track(2, "B", clips=[(8, 12)]))
        self.assertEqual(C.merge_plan(r, {"A": "Guitar", "B": "Piano"}), [])


class CheckById(unittest.TestCase):
    def write(self, root, d, n):
        p = Path(d) / n
        with gzip.open(p, "wb") as fh:
            fh.write(ET.tostring(root))
        return p

    def test_reorder_and_rename_are_info_removal_needs_allowing(self):
        with tempfile.TemporaryDirectory() as d:
            old = self.write(song(track(1, "1-Audio"), track(2, "2-Audio"), track(3, "3-Audio", on=False)), d, "a.als")
            new = self.write(song(track(2, "Bass"), track(1, "Drums")), d, "b.als")
            err, _, facts = K.check(new, old)
            self.assertEqual(len(err), 1)
            self.assertIn("3-Audio", err[0])
            err, _, facts = K.check(new, old, allow_removed=True)
            self.assertEqual(err, [])
            ch = " ".join(facts["changes"])
            self.assertIn("renamed", ch); self.assertIn("order changed", ch); self.assertIn("removed", ch)


if __name__ == "__main__":
    unittest.main()
