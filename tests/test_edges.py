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


def clip(i, a, b, ls, warped=True, disabled=False, fi=0.5, fo=0.5):
    return ET.fromstring(
        f'<AudioClip Id="{i}" Time="{a}"><CurrentStart Value="{a}"/><CurrentEnd Value="{b}"/>'
        f'<IsWarped Value="{"true" if warped else "false"}"/><Disabled Value="{"true" if disabled else "false"}"/>'
        f'<Loop><LoopStart Value="{ls}"/><LoopEnd Value="{ls + (b - a) * (1 if warped else 0.5)}"/>'
        f'<StartRelative Value="0"/><LoopOn Value="false"/></Loop>'
        f'<Fades><FadeInLength Value="{fi}"/><FadeOutLength Value="{fo}"/><IsDefaultFadeIn Value="true"/>'
        f'<IsDefaultFadeOut Value="true"/></Fades></AudioClip>')


class Consonant(unittest.TestCase):
    spb = 0.5                                     # 120 BPM

    def test_start_moves_earlier_and_trims_the_clip_before(self):
        lane = ET.Element("Events")
        prev, cur, mute = clip(1, 0, 8, 0), clip(2, 8, 16, 20), clip(3, 6, 8, 40, disabled=True)
        lane.extend([prev, mute, cur])
        what, touched = E.fix_consonant(lane, cur, "in", -0.05, self.spb)      # consonant 40 ms before + 10 ms
        self.assertIn("start moved 50 ms earlier", what)
        self.assertAlmostEqual(float(cur.get("Time")), 7.9)
        self.assertAlmostEqual(float(cur.find("./CurrentStart").get("Value")), 7.9)
        self.assertAlmostEqual(float(cur.find("./Loop/LoopStart").get("Value")), 19.9)   # content moves the same
        self.assertEqual(cur.find("./Loop/StartRelative").get("Value"), "0")            # never double-shifted
        self.assertAlmostEqual(float(prev.find("./CurrentEnd").get("Value")), 7.9)
        self.assertAlmostEqual(float(prev.find("./Loop/LoopEnd").get("Value")), 7.9)
        self.assertAlmostEqual(float(mute.find("./CurrentEnd").get("Value")), 7.9)
        self.assertAlmostEqual(float(cur.find("./Fades/FadeInLength").get("Value")), 0.02)

    def test_unwarped_start_moves_in_seconds(self):
        lane = ET.Element("Events")
        cur = clip(2, 8, 16, 20, warped=False)
        lane.append(cur)
        E.fix_consonant(lane, cur, "in", -0.05, self.spb)
        self.assertAlmostEqual(float(cur.find("./Loop/LoopStart").get("Value")), 19.95)  # 50 ms, not 0.1 s

    def test_comp_switch_moves_later_when_the_next_take_starts_after(self):
        lane = ET.Element("Events")
        a, b = clip(1, 0, 8, 0, fo=0), clip(2, 8, 16, 30)
        lane.extend([a, b])
        what, touched = E.fix_consonant(lane, a, "out", 0.05, self.spb)
        self.assertIn("comp switch moved", what)
        self.assertAlmostEqual(float(a.find("./CurrentEnd").get("Value")), 8.1)
        self.assertAlmostEqual(float(b.find("./CurrentStart").get("Value")), 8.1)
        self.assertAlmostEqual(float(b.get("Time")), 8.1)
        self.assertAlmostEqual(float(b.find("./Loop/LoopStart").get("Value")), 30.1)

    def test_start_is_not_moved_over_a_clip_that_keeps_playing(self):
        lane = ET.Element("Events")
        over, cur = clip(1, 0, 9, 0), clip(2, 8, 16, 20)
        lane.extend([over, cur])
        what, _ = E.fix_consonant(lane, cur, "in", -0.05, self.spb)
        self.assertIn("NOT moved", what)
        self.assertAlmostEqual(float(cur.find("./CurrentStart").get("Value")), 8.0)
