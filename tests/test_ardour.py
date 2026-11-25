"""Ardour sessions: the reader builds the right model (Ardour 7+ superclock / beat times and older sample
times), and the renderer plays regions as Ardour layers them."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix import project

SR = 48000
SC = 282240000            # superclocks per second (Ardour 7.2+)


def a(sec):
    return f"a{int(round(sec * SC))}"


FADE = "\n".join(f"{a(t)} {g}" for t, g in [(0, 0.0), (0.05, 0.5), (0.1, 1.0)])

SESSION = f"""<?xml version="1.0" encoding="UTF-8"?>
<Session version="7003" name="Song" sample-rate="{SR}">
  <Sources>
    <Source name="lead.wav" type="audio" flags="" id="10" captured-for="Lead" channel="0" origin=""/>
    <Source name="comp.wav" type="audio" flags="" id="11" captured-for="Lead" channel="0" origin=""/>
    <Source name="gtr-L.wav" type="audio" flags="" id="12" channel="0" origin=""/>
    <Source name="gtr-R.wav" type="audio" flags="" id="13" channel="1" origin=""/>
    <Source name="keys.mid" type="midi" flags="" id="14" origin=""/>
  </Sources>
  <VCAManager/>
  <Routes>
    <Route version="7003" id="100" name="Master" default-type="audio">
      <PresentationInfo order="0" flags="MasterOut,OrderSet"/>
      <Processor id="101" name="Amp" active="1" type="amp"><Controllable name="gaincontrol" value="1"/></Processor>
    </Route>
    <Route version="7003" id="200" name="Lead" default-type="audio" audio-playlist="500">
      <PresentationInfo order="1" flags="AudioTrack,OrderSet"/>
      <Controllable name="solo" value="0" self-solo="0"/>
      <IO name="Lead" direction="Output"><Port name="Lead/audio_out 1"><Connection other="Vocals/audio_in 1"/></Port>
        <Port name="Lead/audio_out 2"><Connection other="Vocals/audio_in 2"/></Port></IO>
      <MuteMaster muted="0"/>
      <Controllable name="mute" value="0"/>
      <Controllable name="phase" value="0" phase-invert="11"/>
      <Automation>
        <AutomationList automation-id="mute" state="Off"><events>{a(0)} 1</events></AutomationList>
      </Automation>
      <Pannable>
        <Controllable name="pan-azimuth" value="0.25"/>
        <Automation><AutomationList automation-id="pan-azimuth" state="Play"><events>{a(0)} 0.5
{a(2)} 1</events></AutomationList></Automation>
      </Pannable>
      <Processor id="201" name="Trim" active="1" type="trim"><Controllable name="trimcontrol" value="2"/></Processor>
      <Processor id="202" name="ACE Compressor" active="1" type="lv2" unique-id="urn:ardour:a-comp">
        <Automation><AutomationList automation-id="parameter-1" state="Play"><events>{a(0)} 4
{a(1)} 8</events></AutomationList></Automation>
        <lv2 last-preset-label="Vocal"/>
        <Controllable name="Attack" value="10" parameter="0"/>
        <Controllable name="Ratio" value="4" parameter="1"/>
      </Processor>
      <Processor id="203" name="ACE EQ" active="0" type="lv2" unique-id="urn:ardour:a-eq"/>
      <Processor id="204" name="Amp" active="1" type="amp">
        <Automation><AutomationList automation-id="gain" state="Play"><events>{a(0)} 1
{a(2)} 0.5</events></AutomationList></Automation>
        <Controllable name="gaincontrol" value="0.5"/>
      </Processor>
      <Processor id="205" name="send" active="1" type="intsend" target="400"/>
    </Route>
    <Route version="7003" id="300" name="Vocals" default-type="audio">
      <PresentationInfo order="2" flags="AudioBus,OrderSet"/>
      <Controllable name="mute" value="0"/>
      <Processor id="301" name="Amp" active="1" type="amp"><Controllable name="gaincontrol" value="0.5"/></Processor>
    </Route>
    <Route version="7003" id="400" name="Reverb" default-type="audio">
      <PresentationInfo order="3" flags="AudioBus,OrderSet"/>
      <Processor id="401" name="Amp" active="1" type="amp"><Controllable name="gaincontrol" value="1"/></Processor>
    </Route>
    <Route version="7003" id="600" name="Guitar" default-type="audio" audio-playlist="501">
      <PresentationInfo order="4" flags="AudioTrack,OrderSet"/>
      <Controllable name="mute" value="1"/>
      <Controllable name="phase" value="0" phase-invert="01"/>
      <Processor id="601" name="Amp" active="1" type="amp"><Controllable name="gaincontrol" value="1"/></Processor>
    </Route>
    <Route version="7003" id="700" name="Keys" default-type="midi" midi-playlist="502">
      <PresentationInfo order="5" flags="MidiTrack,OrderSet"/>
    </Route>
  </Routes>
  <Playlists>
    <Playlist id="500" name="Lead" type="audio">
      <Region name="lead.1" muted="0" opaque="1" start="{a(0)}" length="{a(2)}@{a(1)}" layering-index="0"
              scale-amplitude="1" envelope-active="1" fade-in-active="1" fade-out-active="0" type="audio" source-0="10">
        <Envelope><AutomationList automation-id="envelope" state="Off"><events>{a(0)} 1
{a(1)} 1
{a(2)} 0</events></AutomationList></Envelope>
        <FadeIn><AutomationList automation-id="fadein" state="Off"><events>{FADE}</events></AutomationList></FadeIn>
        <FadeOut default="yes"/>
      </Region>
      <Region name="comp.1" muted="0" opaque="1" start="{a(0.5)}" length="{a(0.5)}@{a(2)}" layering-index="1"
              scale-amplitude="2" envelope-active="0" fade-in-active="0" fade-out-active="0" type="audio" source-0="11">
        <Envelope default="yes"/><FadeIn default="yes"/><FadeOut default="yes"/>
      </Region>
    </Playlist>
    <Playlist id="501" name="Guitar" type="audio">
      <Region name="gtr.1" muted="0" opaque="1" start="{a(0)}" length="{a(1)}@{a(0)}" layering-index="0"
              scale-amplitude="1" fade-in-active="0" fade-out-active="0" type="audio" source-0="12" source-1="13"/>
    </Playlist>
    <Playlist id="502" name="Keys" type="midi">
      <Region name="keys.1" muted="0" opaque="0" start="b0" length="b3840@b1920" layering-index="0" type="midi"
              source-0="14"/>
    </Playlist>
  </Playlists>
  <TempoMap superclocks-per-second="{SC}">
    <Tempos><Tempo npm="85" enpm="85" note-type="4" type="Constant" sclock="0" quarters="0:0" bbt="1|1|0"/></Tempos>
    <Meters><Meter note-value="4" divisions-per-bar="3" sclock="0" quarters="0:0" bbt="1|1|0"/></Meters>
  </TempoMap>
</Session>
"""

OLD = f"""<?xml version="1.0" encoding="UTF-8"?>
<Session version="3001" name="Old" sample-rate="{SR}">
  <Sources><Source name="lead.wav" type="audio" flags="" id="10" origin=""/></Sources>
  <Routes>
    <Route id="1" name="master" default-type="audio" flags="MasterOut" phase-invert="00" order-keys="editor=0">
      <Processor id="2" name="Amp" active="yes" type="amp"><Controllable name="gaincontrol" value="1.0"/></Processor>
    </Route>
    <Route id="3" name="Audio 1" default-type="audio" phase-invert="1" order-keys="editor=1">
      <MuteMaster muted="yes"/>
      <Processor id="4" name="Amp" active="yes" type="amp"><Controllable name="gaincontrol" value="0.25"/></Processor>
      <Diskstream playlist="Audio 1.1" name="Audio 1"/>
    </Route>
  </Routes>
  <Playlists>
    <Playlist id="9" name="Audio 1.1" type="audio">
      <Region name="r" position="{SR}" length="{SR // 2}" start="{SR // 4}" layering-index="0" scale-amplitude="1"
              fade-in-active="0" fade-out-active="0" type="audio" source-0="10"/>
    </Playlist>
  </Playlists>
  <TempoMap><Tempo start="1|1|0" beats-per-minute="100" note-type="4"/>
    <Meter start="1|1|0" note-type="4" divisions-per-bar="4"/></TempoMap>
</Session>
"""


class ArdourTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name) / "Song"
        af = self.dir / "interchange" / "Song" / "audiofiles"
        af.mkdir(parents=True)
        ramp = np.linspace(0, 1, 3 * SR, endpoint=False)
        sf.write(af / "lead.wav", ramp, SR, subtype="FLOAT")
        sf.write(af / "comp.wav", np.full(3 * SR, 0.1), SR, subtype="FLOAT")
        sf.write(af / "gtr-L.wav", np.full(SR, 0.2), SR, subtype="FLOAT")
        sf.write(af / "gtr-R.wav", np.full(SR, 0.6), SR, subtype="FLOAT")
        (self.dir / "Song.ardour").write_text(SESSION)

    def tearDown(self):
        self._td.cleanup()

    def test_reader(self):
        p = project.load(self.dir)                                   # the session folder works too
        self.assertEqual((p.daw, p.tempo, p.beats_per_bar, p.sample_rate), ("ardour", 85, 3, SR))
        self.assertEqual([t.name for t in p.tracks], ["Lead", "Vocals", "Reverb", "Guitar", "Keys", "Master"])
        lead, vocals, reverb, gtr, keys, master = p.tracks
        self.assertEqual([t.kind for t in p.tracks], ["audio", "folder", "return", "audio", "midi", "master"])
        self.assertIs(lead.parent, vocals); self.assertIsNone(gtr.parent)
        self.assertAlmostEqual(lead.volume, 0.5 * 2)                 # fader x trim
        self.assertAlmostEqual(lead.pan, -0.5)                       # azimuth 0.25: halfway left
        self.assertTrue(lead.polarity); self.assertFalse(gtr.polarity)
        self.assertTrue(gtr.muted); self.assertFalse(gtr.on)
        self.assertTrue(any("some channels only" in w for w in p.warnings))
        self.assertEqual([(d.name, d.kind, d.on, d.preset) for d in lead.devices],
                         [("ACE Compressor", "LV2", True, "Vocal"), ("ACE EQ", "LV2", False, "")])
        self.assertEqual(lead.devices[0].params, {"Attack": 10.0, "Ratio": 4.0})
        self.assertEqual(sorted(lead.envelopes), ["ACE Compressor/Ratio", "Pan", "Volume"])  # mute list is Off
        self.assertEqual(lead.envelopes["Pan"], [(0.0, 0.0), (2.0, 1.0)])
        self.assertAlmostEqual(lead.envelopes["Volume"][1][0], 2.0)
        c, comp = lead.clips
        self.assertAlmostEqual(c.start, 1.0); self.assertAlmostEqual(c.length, 2.0)
        self.assertAlmostEqual(comp.take.offset, 0.5); self.assertEqual(comp.layer, 1)
        self.assertAlmostEqual(c.fade_in, 0.1); self.assertEqual(c.fade_out, 0.0)
        self.assertEqual(c.path.name, "lead.wav")
        self.assertEqual([x.name for x in [gtr.clips[0].take.path] + gtr.clips[0].take.extra_paths],
                         ["gtr-L.wav", "gtr-R.wav"])
        k = keys.clips[0]                                            # music time: beat 1, two beats long
        self.assertEqual(k.kind, "midi")
        self.assertAlmostEqual(k.start, 60 / 85); self.assertAlmostEqual(k.length, 2 * 60 / 85)
        self.assertEqual(k.fade_in, 0.0)

    def test_render_layers_fades_envelope(self):
        p = project.load(self.dir / "Song.ardour")
        lead, gtr = p.tracks[0], p.tracks[3]
        y = p.render(lead, SR, length=3)
        self.assertTrue(np.all(y[: SR - 1] == 0))                    # nothing before 1 s
        self.assertAlmostEqual(y[int(1.025 * SR)], 0.25 * (0.025 / 3), places=3)   # stored fade-in curve
        self.assertAlmostEqual(y[int(1.5 * SR)], 0.5 / 3, places=4)  # ramp at 0.5 s, envelope at 1
        # 2.0-2.5 s: the upper opaque region covers the lower one (0.1 x scale 2), no mixing
        self.assertAlmostEqual(y[int(2.25 * SR)], 0.2, places=4)
        # 2.75 s: back on the lower region, envelope falling 1 -> 0 over 1..2 s of the region
        self.assertAlmostEqual(y[int(2.75 * SR)], (1.75 / 3) * 0.25, places=3)
        g = p.render(gtr, SR, length=1)
        self.assertAlmostEqual(g[SR // 2], 0.4, places=4)            # two channel files, averaged to mono

    def test_old_session_in_samples(self):
        d = Path(self._td.name) / "Old"
        (d / "interchange" / "Old" / "audiofiles").mkdir(parents=True)
        sf.write(d / "interchange" / "Old" / "audiofiles" / "lead.wav", np.linspace(0, 1, 2 * SR, endpoint=False),
                 SR, subtype="FLOAT")
        (d / "Old.ardour").write_text(OLD)
        p = project.load(d / "Old.ardour")
        self.assertEqual((p.tempo, p.beats_per_bar), (100, 4))
        tr = p.tracks[0]
        self.assertEqual((tr.name, tr.kind, tr.muted, tr.polarity), ("Audio 1", "audio", True, True))
        self.assertEqual(p.tracks[1].kind, "master")
        c = tr.clips[0]
        self.assertEqual((c.start, c.length, c.take.offset), (1.0, 0.5, 0.25))
        y = p.render(tr, SR, length=2)
        self.assertAlmostEqual(y[int(1.25 * SR)], 0.5 / 2, places=4)  # source at 0.25 + 0.25 s

    def test_not_a_session(self):
        bad = Path(self._td.name) / "x.ardour"
        bad.write_text("<NotASession/>")
        with self.assertRaises(SystemExit):
            project.load(bad)


if __name__ == "__main__":
    unittest.main()
