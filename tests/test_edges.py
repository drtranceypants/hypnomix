"""edges: grouping of findings, applying only approved fades; unroll keeps a clip's Time with its start."""
import unittest
import xml.etree.ElementTree as ET

from hypnomix.session import edges as E
from hypnomix.session import unroll as U


def f(kind, beat, clip, sure=False, edge="in", off=False):
    d = dict(kind=kind, beat=beat, clip=clip, edge=edge, track="Harmony 4", off=off, sure=sure)
    if kind.startswith("fade"):
        d.update(fade_ms=507, at_ms=130, duck=12, thump=False)
    else:
        d.update(level=-6, quiet_ms=-89, quiet_db=-37)
    return d


class Group(unittest.TestCase):
    def test_clear_cut_fades_alone_rest_grouped(self):
        found = [f("fade-in", 95, "3", sure=True), f("start-cut", 95, "3"), f("fade-in", 159, "7"),
                 f("fade-out", 200, "9", edge="out"), f("end-cut", 210, "9", edge="out")]
        fs = E.findings(found)
        kinds = [x["kind"] for x in fs]
        self.assertEqual(kinds, ["fade-in", "cuts", "fades"])
        self.assertEqual(fs[0]["targets"], [["3", "in"]])
        self.assertTrue(fs[0]["recommended"])
        self.assertEqual(fs[2]["targets"], [["7", "in"], ["9", "out"]])
        self.assertEqual(fs[1]["applies"], "manual")

    def test_apply_shortens_only_the_targets(self):
        root = ET.fromstring(
            '<Ableton><LiveSet><Tempo><Manual Value="60"/></Tempo><Tracks><AudioTrack Id="1">'
            '<Name><EffectiveName Value="Harmony 4"/></Name><DeviceChain><MainSequencer><Sample><ArrangerAutomation>'
            '<Events>' + "".join(
                f'<AudioClip Id="{i}"><Fades><FadeInLength Value="0.5"/><FadeOutLength Value="0.5"/>'
                f'<IsDefaultFadeIn Value="true"/><IsDefaultFadeOut Value="true"/></Fades></AudioClip>' for i in (3, 4))
            + '</Events></ArrangerAutomation></Sample></MainSequencer></DeviceChain></AudioTrack></Tracks></LiveSet></Ableton>')
        n = E.apply(root, [dict(applies="set", track="Harmony 4", targets=[["3", "in"]])], fix_fade_ms=10)
        self.assertEqual(n, 1)
        c3, c4 = root.iter("AudioClip")
        self.assertAlmostEqual(float(c3.find("./Fades/FadeInLength").get("Value")), 0.01)
        self.assertEqual(c3.find("./Fades/FadeOutLength").get("Value"), "0.5")
        self.assertEqual(c4.find("./Fades/FadeInLength").get("Value"), "0.5")


class UnrollTime(unittest.TestCase):
    def test_copies_keep_time_equal_to_start(self):
        ev = ET.fromstring(
            '<Events><AudioClip Id="0" Time="8"><CurrentStart Value="8"/><CurrentEnd Value="24"/><IsWarped Value="true"/>'
            '<Loop><LoopStart Value="0"/><LoopEnd Value="4"/><StartRelative Value="0"/><LoopOn Value="true"/>'
            '<OutMarker Value="4"/><HiddenLoopStart Value="0"/><HiddenLoopEnd Value="4"/></Loop></AudioClip></Events>')
        new = U.unroll_clip(ev, ev[0], 120)
        self.assertEqual(len(new), 4)
        for c in new:
            self.assertEqual(float(c.get("Time")), float(c.find("./CurrentStart").get("Value")))


if __name__ == "__main__":
    unittest.main()
