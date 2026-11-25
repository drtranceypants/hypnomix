"""abset: each fix lands next to the original as a switched-off B (device copy or muted track copy)."""
import copy, unittest
import xml.etree.ElementTree as ET

from hypnomix.workflow import abset as A


def dev(tag, thr="0.5", on="true", did="0", tgt="100"):
    return (f'<{tag} Id="{did}"><On><Manual Value="{on}"/><AutomationTarget Id="{tgt}"/></On>'
            f'<Threshold><Manual Value="{thr}"/><AutomationTarget Id="{int(tgt) + 1}"/></Threshold></{tag}>')


def track(tid, name, devs="", clip_gain="1", speaker="true"):
    return (f'<AudioTrack Id="{tid}"><Name><EffectiveName Value="{name}"/><UserName Value="{name}"/></Name>'
            f'<DeviceChain><Mixer><Speaker><Manual Value="{speaker}"/><AutomationTarget Id="{tid}9"/></Speaker></Mixer>'
            f'<MainSequencer><Sample><ArrangerAutomation><Events><AudioClip Id="0"><SampleVolume Value="{clip_gain}"/>'
            f'</AudioClip></Events></ArrangerAutomation></Sample></MainSequencer>'
            f'<DeviceChain><Devices>{devs}</Devices></DeviceChain></DeviceChain></AudioTrack>')


def song(*tracks, main_devs=""):
    return ET.fromstring(f'<Ableton><LiveSet><NextPointeeId Value="1000"/><Tracks>{"".join(tracks)}</Tracks>'
                         f'<MainTrack><DeviceChain><Mixer/><DeviceChain><Devices>{main_devs}</Devices></DeviceChain>'
                         f'</DeviceChain></MainTrack></LiveSet></Ableton>')


class Diff(unittest.TestCase):
    def test_device_ops(self):
        a = [ET.fromstring(dev("Eq8")), ET.fromstring(dev("Compressor2"))]
        b = [ET.fromstring(dev("Eq8")), ET.fromstring(dev("Compressor2", thr="0.3"))]
        self.assertEqual(A.device_diff(a, b), [("changed", 1, 1)])
        c = b + [ET.fromstring(dev("Limiter"))]
        self.assertEqual(A.device_diff(a[:1], c[:1] + c[2:]), [("added", 0, 1)])
        self.assertEqual(A.device_diff(a, a[:1]), [("removed", 1, None)])


class Build(unittest.TestCase):
    def run_one(self, orig, fixed, fid="x-1"):
        ab = copy.deepcopy(orig)
        items, refs = {}, {}
        parts, notes = A.build_one(ab, orig, fixed, fid, A.Ids(ab), refs)
        items[fid] = dict(parts=parts, note="; ".join(notes))
        A.finalize(ab, items)
        return ab, items[fid]

    def test_changed_device_is_copied_in_after_the_original_and_switched_off(self):
        orig = song(track(1, "Vox", dev("Eq8", tgt="100") + dev("Compressor2", tgt="200", did="1")))
        fixed = song(track(1, "Vox", dev("Eq8", tgt="100") + dev("Compressor2", thr="0.3", tgt="200", did="1")))
        ab, it = self.run_one(orig, fixed)
        devs = list(A.devices(A.all_tracks(ab)["1"]))
        self.assertEqual([d.tag for d in devs], ["Eq8", "Compressor2", "Compressor2"])
        p = it["parts"][0]
        self.assertEqual((p["mode"], p["track"], p["a"], p["b"], p["b_on"]), ("devices", "Vox", [1], [2], [True]))
        self.assertFalse(A.is_on(devs[2]))
        self.assertEqual(devs[2].find("./Threshold/Manual").get("Value"), "0.3")
        tg = [e.get("Id") for e in ab.iter() if e.tag.endswith("Target")]
        self.assertEqual(len(tg), len(set(tg)))                       # fresh ids for the copy

    def test_clip_change_copies_the_track_muted(self):
        orig = song(track(1, "Vox"), track(2, "Gtr"))
        fixed = song(track(1, "Vox", clip_gain="0.5"), track(2, "Gtr"))
        ab, it = self.run_one(orig, fixed, "smooth-3")
        names = [A.tname(t) for t in ab.find(".//LiveSet/Tracks")]
        self.assertEqual(names, ["Vox", "Vox · B smooth-3", "Gtr"])
        b = ab.find(".//LiveSet/Tracks")[1]
        self.assertEqual(b.find("./DeviceChain/Mixer/Speaker/Manual").get("Value"), "false")
        self.assertEqual(it["parts"][0], dict(mode="tracks", a=["Vox"], b=["Vox · B smooth-3"], a_on=[True], b_on=[True]))

    def test_added_device_on_main_and_untouched_tracks_left_alone(self):
        orig = song(track(1, "Vox"), main_devs=dev("Eq8"))
        fixed = song(track(1, "Vox"), main_devs=dev("Eq8") + dev("Limiter", tgt="300"))
        ab, it = self.run_one(orig, fixed)
        p = it["parts"][0]
        self.assertTrue(p["main"])
        self.assertEqual((p["a"], p["b"]), ([], [1]))
        self.assertEqual(ET.tostring(A.all_tracks(ab)["1"]), ET.tostring(A.all_tracks(orig)["1"]))

    def test_two_fixes_on_one_track_keep_their_own_indices(self):
        orig = song(track(1, "Vox", dev("Eq8", tgt="100") + dev("Compressor2", tgt="200", did="1")))
        f1 = song(track(1, "Vox", dev("Eq8", thr="0.1", tgt="100") + dev("Compressor2", tgt="200", did="1")))
        f2 = song(track(1, "Vox", dev("Eq8", tgt="100") + dev("Compressor2", thr="0.2", tgt="200", did="1")))
        ab = copy.deepcopy(orig)
        ids, refs, items = A.Ids(ab), {}, {}
        for fid, fx in (("a", f1), ("b", f2)):
            items[fid] = dict(parts=A.build_one(ab, orig, fx, fid, ids, refs)[0])
        A.finalize(ab, items)
        devs = list(A.devices(A.all_tracks(ab)["1"]))
        pa, pb = items["a"]["parts"][0], items["b"]["parts"][0]
        self.assertEqual(devs[pa["a"][0]].tag, "Eq8")
        self.assertEqual(devs[pa["b"][0]].find("./UserName").get("Value"), "B · a")
        self.assertEqual(devs[pb["a"][0]].tag, "Compressor2")
        self.assertEqual(devs[pb["b"][0]].find("./UserName").get("Value"), "B · b")


if __name__ == "__main__":
    unittest.main()
