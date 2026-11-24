"""borrow: the MIDI window that already sits in the groove wins, and its nudge lands the first note on the song's
downbeat; imported tracks are off, ungrouped, routed to Main, with one send per return."""
import unittest
import xml.etree.ElementTree as ET
import numpy as np
from hypnomix.session import borrow as B


class Window(unittest.TestCase):
    def test_tight_window_preferred_and_nudged_to_the_downbeat(self):
        tempo = 120.0
        tmpl = np.zeros(16); d_off = -0.02               # the song lands 10 ms early on its downbeats
        loose = [(0.0 + 0.09, 40, 0.5, 100), (1.0 - 0.08, 43, 0.5, 100), (2.0 + 0.1, 45, 0.5, 100), (3.0, 47, 0.5, 100)]
        tight = [(4.0 + 0.01, 40, 0.5, 100), (5.0, 43, 0.5, 100), (6.0 + 0.005, 45, 0.5, 100), (7.0, 47, 0.5, 100)]
        w = B.best_window(loose + tight, 8.0, tmpl, d_off, tempo)
        self.assertEqual(w["w0"], 4.0)
        self.assertAlmostEqual(w["w0"] + 0.01 + w["nudge"], 4.0 + d_off, places=6)   # first note lands on the song's one

    def test_too_far_off_is_not_offered(self):
        notes = [(0.1, 40, 0.5, 100), (1.1, 43, 0.5, 100), (2.1, 45, 0.5, 100), (3.1, 47, 0.5, 100)]   # 50 ms late
        self.assertIsNone(B.best_window(notes, 4.0, np.zeros(16), 0.0, 120.0))


SET = """<Ableton><LiveSet><NextPointeeId Value="100"/><Tracks>
<AudioTrack Id="1"><Name><EffectiveName Value="Gtr"/><UserName Value=""/></Name><TrackGroupId Value="-1"/>
<AutomationEnvelopes><Envelopes/></AutomationEnvelopes>
<DeviceChain><AudioOutputRouting><Target Value="AudioOut/Main"/></AudioOutputRouting>
<Mixer><Speaker><Manual Value="true"/></Speaker><Sends><TrackSendHolder><Send><Manual Value="0.5"/>
<AutomationTarget Id="10"/></Send></TrackSendHolder></Sends></Mixer>
<MainSequencer><Sample><ArrangerAutomation><Events/></ArrangerAutomation></Sample></MainSequencer></DeviceChain></AudioTrack>
<ReturnTrack Id="2"/><ReturnTrack Id="3"/></Tracks></LiveSet></Ableton>"""
SRC = """<MidiTrack Id="7"><Name><EffectiveName Value="Riff"/><UserName Value=""/></Name><TrackGroupId Value="33"/>
<AutomationEnvelopes><Envelopes><AutomationEnvelope/></Envelopes></AutomationEnvelopes>
<DeviceChain><AudioOutputRouting><Target Value="AudioOut/GroupTrack"/><UpperDisplayString Value="Group"/></AudioOutputRouting>
<Mixer><Speaker><Manual Value="true"/></Speaker><Sends>
<TrackSendHolder><Send><Manual Value="0.7"/><MidiControllerRange><Min Value="0.0003"/></MidiControllerRange><AutomationTarget Id="55"/></Send></TrackSendHolder>
<TrackSendHolder><Send><Manual Value="0.7"/><AutomationTarget Id="56"/></Send></TrackSendHolder>
<TrackSendHolder><Send><Manual Value="0.7"/><AutomationTarget Id="57"/></Send></TrackSendHolder></Sends></Mixer>
<MainSequencer><ClipTimeable><ArrangerAutomation><Events><MidiClip Id="1"/></Events></ArrangerAutomation></ClipTimeable></MainSequencer>
</DeviceChain></MidiTrack>"""


class Import(unittest.TestCase):
    def test_imported_track_is_off_ungrouped_to_main_with_matching_sends(self):
        root = ET.fromstring(SET)
        new = B.import_track(root, ET.fromstring(SRC), "Riff (from original)", 2)
        self.assertEqual(new.find("./DeviceChain/Mixer/Speaker/Manual").get("Value"), "false")
        self.assertEqual(new.find("./TrackGroupId").get("Value"), "-1")
        self.assertEqual(new.find("./DeviceChain/AudioOutputRouting/Target").get("Value"), "AudioOut/Main")
        self.assertEqual(len(new.findall("./DeviceChain/Mixer/Sends/TrackSendHolder")), 2)
        ids = [e.get("Id") for e in root.iter() if e.tag.endswith("Target") and e.get("Id")]
        self.assertEqual(len(ids), len(set(ids)))                     # no id collides
        self.assertEqual(len(new.findall(".//Events/MidiClip")), 0)   # clips come only from the approved loops
        tracks = list(root.find(".//Tracks"))
        self.assertEqual(tracks.index(new), 1)                        # before the returns


if __name__ == "__main__":
    unittest.main()
