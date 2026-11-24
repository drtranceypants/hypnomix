"""motion: move shapes, learning from drawn automation, stutter slicing keeps the rest of the clip in place."""
import unittest
import xml.etree.ElementTree as ET
from hypnomix.session import motion as M


def tg(scale="lin", lo=0.0, hi=127.0, base=100.0, kind="filter"):
    return dict(track="T", label="x", el=None, pid="1", kind=kind, scale=scale, lo=lo, hi=hi, base=base)


class Shapes(unittest.TestCase):
    def test_dj_riser_snaps_back_on_the_one(self):
        pts = M.points("riser", tg("dj", -1, 1, 0.0), 0, 64, dict(bars=8, depth=0.4))
        self.assertEqual(pts[0], (32, 0.0))
        self.assertAlmostEqual(pts[1][1], 0.4)
        self.assertEqual(pts[-1], (64, 0.0))

    def test_dip_goes_down_and_comes_back(self):
        pts = M.points("dip", tg(), 0, 64, dict(bars=8, depth=0.5))
        self.assertEqual(pts[0][1], 100.0); self.assertEqual(pts[-1][1], 100.0)
        self.assertLess(min(x for _, x in pts), 100.0 - 0.4 * 127)

    def test_gate_ends_open_and_only_chops_the_last_bar(self):
        pts = M.points("gate", tg("send", 0.0003, 1.99, 1.0, "volume"), 0, 16, dict(bars=1, pattern="16ths", dB=24))
        self.assertTrue(all(t >= 12 - 1e-9 for t, _ in pts))
        self.assertEqual(pts[-1], (16, 1.0))
        self.assertLess(min(x for _, x in pts), 0.1)

    def test_dropout_is_one_beat(self):
        pts = M.points("dropout", tg("send", 0.0003, 1.99, 1.0, "volume"), 0, 16, dict(beats=1))
        silent = [t for t, x in pts if x < 0.01]
        self.assertAlmostEqual(min(silent), 15.0); self.assertGreater(max(silent), 15.9)


class Learn(unittest.TestCase):
    def test_riser_then_dip_on_one_envelope_are_two_moves(self):
        # a DJ filter: up over ~8 bars, snap back on bar 65; later a low-pass dip and back
        pts = [(224.8, 0.0), (255.6, 0.43), (256.0, 0.0), (368.0, 0.0), (388.0, -0.52), (396.0, -0.5), (404.0, 0.0)]
        moves = [M.classify_envelope(sg, -1, 1, 620) for sg in M.segments(pts, -1, 1)]
        self.assertEqual([m["move"] for m in moves], ["riser", "dip"])
        self.assertAlmostEqual(moves[0]["depth"], 0.43, places=2)

    def test_slow_wander_is_a_drift(self):
        pts = [(172.0, 65.0), (240.0, 73.0), (352.0, 63.0), (448.0, 125.0), (544.0, 45.0)]
        m = [M.classify_envelope(sg, 0, 127, 620) for sg in M.segments(pts, 0, 127)]
        self.assertEqual([x["move"] for x in m], ["drift"])


CLIP = """<Events><MidiClip Id="4"><CurrentStart Value="24"/><CurrentEnd Value="200"/>
<Loop><LoopStart Value="0"/><LoopEnd Value="16"/><StartRelative Value="0"/><LoopOn Value="true"/>
<OutMarker Value="16"/><HiddenLoopStart Value="0"/><HiddenLoopEnd Value="16"/></Loop>
<Name Value="beat"/><Disabled Value="false"/></MidiClip></Events>"""


class Stutter(unittest.TestCase):
    def test_slices_and_the_rest_plays_on_time(self):
        track = ET.fromstring("<MidiTrack><DeviceChain><MainSequencer><ClipTimeable><ArrangerAutomation>"
                              + CLIP + "</ArrangerAutomation></ClipTimeable></MainSequencer></DeviceChain></MidiTrack>")
        orig = ET.fromstring(CLIP).find("MidiClip")
        self.assertIsNone(M.stutter(track, 60.0, dict(beats=2)))
        clips = track.findall(".//Events/MidiClip")
        self.assertEqual(len(clips), 8)
        tail = clips[-1]
        for x in (60.0, 75.5, 199.0):            # after the roll, the clip plays exactly what it played before
            self.assertAlmostEqual(M.content_at(tail, x), M.content_at(orig, x))
        self.assertEqual(len({c.get("Id") for c in clips}), 8)


if __name__ == "__main__":
    unittest.main()
