"""Regression tests: a timing nudge must not move the rest of the clip; one lead rule everywhere."""
import unittest
import numpy as np
from hypnomix.session import timing as T
from hypnomix.engineer.roles import choose_lead


class _El:
    """Just enough of a clip's <WarpMarkers> element for add_marker / restore."""
    def __init__(self, markers):
        self.kids = [self._m(i, s, b) for i, (b, s) in enumerate(markers)]

    @staticmethod
    def _m(i, s, b):
        class M(dict):
            def get(self, k, d=None): return dict.get(self, k, d)
            def set(self, k, v): self[k] = v
        return M(Id=str(i), SecTime=repr(s), BeatTime=repr(b))

    def find(self, _): return self
    def findall(self, _): return list(self.kids)
    def __iter__(self): return iter(self.kids)
    def __len__(self): return len(self.kids)
    def makeelement(self, tag, attrs): return self._m(attrs["Id"], float(attrs["SecTime"]), float(attrs["BeatTime"]))
    def insert(self, i, e): self.kids.insert(i, e)
    def remove(self, e): self.kids.remove(e)
    def append(self, e): self.kids.append(e)


def clip(markers):
    return dict(el=_El(markers), markers=list(markers), warped=True, start=0.0, end=400.0, ls=0.0, rel=0.0,
                loop_on=False)


class TimingDrift(unittest.TestCase):
    def test_nudge_past_last_marker_keeps_the_rest_of_the_clip(self):
        tempo = 120.0
        ci = clip([(0.0, 0.0), (0.03125, 0.015625)])       # Live's usual 2 markers near the start
        hits = [dict(sec=s, clip=ci) for s in (10.0, 10.5, 11.0)]
        issue = dict(hit=hits[1], move=0.02)
        before = list(ci["markers"])
        done, skipped = T.apply([issue], [("t", None, hits)], tempo, 1.0)
        self.assertEqual(len(done), 1, skipped)
        grid = np.arange(11.0, 300.0, 0.01)
        old = dict(ci); old["markers"] = before
        dev = np.abs(T.file_to_arr(ci, grid, tempo) - T.file_to_arr(old, grid, tempo)).max() * 60 / tempo * 1000
        self.assertLess(dev, 0.5, "audio after the nudged hit moved")


class Lead(unittest.TestCase):
    def test_clear_vowel_lead_wins(self):
        self.assertEqual(choose_lead([("a", 18, 30), ("b", 14, 90)]), "a")

    def test_close_vowels_fall_back_to_singing_time(self):
        # a real remix: cleaned copies 14.8 / 15.8 / 15.2; the lead (12) sings longest
        self.assertEqual(choose_lead([("12", 14.8, 45.3), ("13", 15.8, 34.9), ("14", 15.2, 31.6)]), "12")


if __name__ == "__main__":
    unittest.main()


class ExistingMarkers(unittest.TestCase):
    def test_a_marker_at_the_hit_is_moved_and_markers_around_it_anchor(self):
        tempo = 120.0
        # a transient-warped loop: a marker on every half beat (0.25 s), playing straight
        ms = [(b * 0.5, b * 0.25) for b in range(0, 41)]
        ci = clip(ms)
        hits = [dict(sec=s, clip=ci) for s in (2.0, 2.5, 3.0)]
        issue = dict(hit=hits[1], move=0.02)
        before = list(ci["markers"])
        done, skipped = T.apply([issue], [("t", None, hits)], tempo, 1.0)
        self.assertEqual(len(done), 1, skipped)
        self.assertEqual(len(ci["markers"]), len(before))          # no marker added: the one at the hit moved
        moved = [(b0, b1) for (b0, s0), (b1, s1) in zip(before, ci["markers"]) if abs(b0 - b1) > 1e-9]
        self.assertEqual(len(moved), 1)


class WarpOn(unittest.TestCase):
    def test_switching_warp_on_keeps_the_playback(self):
        import xml.etree.ElementTree as ET
        tempo = 100.0
        el = ET.fromstring('<AudioClip><IsWarped Value="false"/><Loop><LoopStart Value="2.0"/><LoopEnd Value="30.0"/>'
                           '<StartRelative Value="0"/><OutMarker Value="30.0"/><HiddenLoopStart Value="2.0"/>'
                           '<HiddenLoopEnd Value="30.0"/></Loop><WarpMarkers/></AudioClip>')
        ci = dict(el=el, warped=False, loop_on=False, ls=2.0, le=30.0, rel=0.0, start=16.0, end=40.0, markers=[])
        secs = np.array([3.0, 7.5, 12.25])
        before = T.file_to_arr(dict(ci), secs, tempo)
        self.assertTrue(T.warp_on(ci, tempo))
        after = T.file_to_arr(ci, secs, tempo)
        self.assertTrue(np.allclose(before, after))
        self.assertEqual(el.find("./IsWarped").get("Value"), "true")


class MidiHits(unittest.TestCase):
    def test_a_looped_note_is_heard_on_every_pass(self):
        import xml.etree.ElementTree as ET
        t = ET.fromstring(
            '<MidiTrack><DeviceChain><MainSequencer><ClipTimeable><ArrangerAutomation><Events>'
            '<MidiClip Id="0"><CurrentStart Value="16"/><CurrentEnd Value="32"/><Disabled Value="false"/>'
            '<Loop><LoopStart Value="0"/><LoopEnd Value="4"/><StartRelative Value="0"/><LoopOn Value="true"/></Loop>'
            '<Notes><KeyTracks><KeyTrack><Notes><MidiNoteEvent Time="1.05" Duration="0.5" Velocity="100" IsEnabled="true"/>'
            '</Notes><MidiKey Value="36"/></KeyTrack></KeyTracks></Notes></MidiClip>'
            '</Events></ArrangerAutomation></ClipTimeable></MainSequencer></DeviceChain></MidiTrack>')
        hs = T.midi_hits(t)
        self.assertEqual([round(h["beat"], 2) for h in hs], [17.05, 21.05, 25.05, 29.05])
        self.assertTrue(all(h["note"] is hs[0]["note"] for h in hs))   # one note, four passes
