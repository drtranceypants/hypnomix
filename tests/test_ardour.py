"""Ardour sessions: the reader builds the right model (Ardour 7+ superclock / beat times and older sample
times), and the renderer plays regions as Ardour layers them."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix import project
from hypnomix.project import ardour_edit as AE

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
        (self.dir / "Song.ardour").write_text(SESSION, encoding="utf-8")

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

    def test_take_playlists_are_take_lanes(self):
        """A track's playlists named "<track>.take N" (HypnoMix Studio records each pass into one and comps from them)
        are its take lanes, in take order; the active playlist stays the comp and is what plays."""
        takes = f"""
    <Playlist id="510" name="Lead.take 2" type="audio" orig-track-id="200">
      <Region name="t2" muted="0" opaque="1" start="{a(0)}" length="{a(3)}@{a(0)}" layering-index="0"
              scale-amplitude="0.5" fade-in-active="0" fade-out-active="0" type="audio" source-0="11"/>
    </Playlist>
    <Playlist id="511" name="Lead.take 1" type="audio" orig-track-id="200">
      <Region name="t1" muted="0" opaque="1" start="{a(0)}" length="{a(3)}@{a(0)}" layering-index="0"
              scale-amplitude="1" fade-in-active="0" fade-out-active="0" type="audio" source-0="10"/>
    </Playlist>
    <Playlist id="512" name="Lead.2" type="audio" orig-track-id="200"/>
    <Playlist id="513" name="Guitar.take 1" type="audio" orig-track-id="999"/>
  </Playlists>"""
        f = self.dir / "Song.ardour"
        f.write_text(SESSION.replace("\n  </Playlists>", takes, 1), encoding="utf-8")
        p = project.load(self.dir)
        lead, gtr = p.tracks[0], p.tracks[3]
        self.assertEqual([(k.name, k.number) for k in lead.take_lanes], [("Lead.take 1", 1), ("Lead.take 2", 2)])
        self.assertTrue(lead.comped); self.assertFalse(gtr.comped); self.assertEqual(gtr.take_lanes, [])
        t2 = lead.take_lanes[1].clips[0]
        self.assertAlmostEqual(t2.start, 0.0); self.assertAlmostEqual(t2.length, 3.0)
        self.assertAlmostEqual(t2.take.gain, 0.5); self.assertEqual(t2.path.name, "comp.wav")
        self.assertEqual(len(lead.clips), 2)                          # the comp is unchanged by the takes
        y0 = project.load(self.dir).render(lead, SR, length=3)
        f.write_text(SESSION, encoding="utf-8")
        y1 = project.load(self.dir).render(lead, SR, length=3)
        self.assertTrue(np.array_equal(y0, y1))                       # takes are not heard
        (self.dir / "interchange" / "Song" / "audiofiles" / "comp.wav").unlink()
        f.write_text(SESSION.replace("\n  </Playlists>", takes, 1), encoding="utf-8")
        p = project.load(self.dir)
        self.assertEqual([(t.name, c.name) for t, c, _ in p.missing()], [("Lead", "comp.1")])   # heard clips only
        self.assertEqual(p.missing_takes(), [])                      # the comp's own file: said once, above

    def test_missing_files_count_take_lanes_apart(self):
        from hypnomix.workflow import scan_project as SP
        takes = f"""
    <Playlist id="510" name="Lead.take 1" type="audio" orig-track-id="200">
      <Region name="t1" muted="0" opaque="1" start="{a(0)}" length="{a(3)}@{a(0)}" layering-index="0"
              scale-amplitude="1" fade-in-active="0" fade-out-active="0" type="audio" source-0="11"/>
    </Playlist>
    <Playlist id="511" name="Lead.take 2" type="audio" orig-track-id="200">
      <Region name="t2" muted="0" opaque="1" start="{a(0)}" length="{a(3)}@{a(0)}" layering-index="0"
              scale-amplitude="1" fade-in-active="0" fade-out-active="0" type="audio" source-0="11"/>
      <Region name="t2b" muted="0" opaque="1" start="{a(0)}" length="{a(1)}@{a(0)}" layering-index="1"
              scale-amplitude="1" fade-in-active="0" fade-out-active="0" type="audio" source-0="12"/>
    </Playlist>
  </Playlists>"""
        (self.dir / "Song.ardour").write_text(SESSION.replace("\n  </Playlists>", takes, 1), encoding="utf-8")
        af = self.dir / "interchange" / "Song" / "audiofiles"
        (af / "comp.wav").unlink()                                   # the comp and both takes use it
        SP.W.update(SP.WORDS["ardour"])
        fs, notes = SP.g_files(project.load(self.dir), None, None, None)
        self.assertEqual([(f["kind"], f["severity"]) for f in fs], [("missing-audio", "high")])   # one finding, not three
        self.assertIn("comp.1", fs[0]["problem"])
        self.assertEqual(notes[0], "files: 7 items checked (3 on take lanes), 1 missing")
        (af / "gtr-L.wav").unlink()                                  # Guitar's file: heard, and take 2 uses it too
        fs, _ = SP.g_files(project.load(self.dir), None, None, None)
        self.assertEqual([f["kind"] for f in fs], ["missing-audio", "missing-audio"])
        only = SESSION.replace("\n  </Playlists>", takes.replace('source-0="12"', 'source-0="15"'), 1).replace(
            "</Sources>", '<Source name="take.wav" type="audio" flags="" id="15" channel="0" origin=""/></Sources>', 1)
        (self.dir / "Song.ardour").write_text(only, encoding="utf-8")                  # a file only take 2 uses (it was never there)
        fs, notes = SP.g_files(project.load(self.dir), None, None, None)
        self.assertEqual([(f["kind"], f["severity"]) for f in fs],
                         [("missing-audio", "high"), ("missing-audio", "high"), ("missing-take-audio", "medium")])
        self.assertIn("take 2 of Lead uses", fs[2]["problem"])
        self.assertNotIn("plays", fs[2]["problem"])
        self.assertIn("1 more file only takes use", notes[0])

    def test_bars_count_quarter_notes_for_any_meter(self):
        m34 = '<Meters><Meter note-value="4" divisions-per-bar="3" sclock="0" quarters="0:0" bbt="1|1|0"/></Meters>'
        self.assertIn(m34, SESSION)
        f = self.dir / "Song.ardour"
        for meter, at, bar in (('note-value="8" divisions-per-bar="6"', 60 / 85 * 6, 3.0),   # 6/8: 3 quarters a bar
                               ('note-value="8" divisions-per-bar="5"', 60 / 85 * 2.5, 2.0),  # 5/8: 2.5
                               ('divisions-per-bar="7"', 60 / 85 * 7, 2.0)):                 # no note value: x/4
            f.write_text(SESSION.replace('note-value="4" divisions-per-bar="3"', meter, 1), encoding="utf-8")
            p = project.load(self.dir)
            self.assertAlmostEqual(p.bar(at), bar, places=6, msg=meter)
            self.assertEqual(p.meter_changes, 0)
            self.assertFalse(any("meter" in w for w in p.warnings))
        self.assertEqual(project.load(self.dir).meter_text, "7/4")
        f.write_text(SESSION.replace('note-value="4" divisions-per-bar="3"', 'note-value="8" divisions-per-bar="6"', 1), encoding="utf-8")
        p = project.load(self.dir)
        self.assertEqual((p.beats_per_bar, p.meter_text, p.where(60 / 85 * 3)), (3, "6/8", "2.1.01"))
        two = m34.replace("</Meters>", '<Meter note-value="4" divisions-per-bar="4" sclock="1411200000" quarters="5:0" bbt="3|1|0"/></Meters>')
        f.write_text(SESSION.replace(m34, two, 1), encoding="utf-8")
        p = project.load(self.dir)
        self.assertEqual(p.meter_changes, 1)
        self.assertTrue(any("meter changes (3/4, 4/4)" in w for w in p.warnings), p.warnings)

    def test_reaper_bars_count_quarter_notes_and_the_ab_span_distrusts_bars(self):
        from hypnomix.project import reaper
        from hypnomix.workflow import abset_ardour as AA
        f = Path(self._td.name) / "x.rpp"
        f.write_text('<REAPER_PROJECT 0.1 "7.27/macOS-arm64" 1\n  TEMPO 120 6 8\n  SAMPLERATE 44100 0 0\n>\n', encoding="utf-8")
        p = reaper.read(f)
        self.assertEqual((p.beats_per_bar, p.meter_text, p.bar(3.0)), (3, "6/8", 3.0))
        self.assertEqual(AA._span(dict(where="bar 3"), 120, 4, 30.0), (3.0, 5.5))
        self.assertEqual(AA._span(dict(where="bar 3"), 120, 4, 30.0, bars_ok=False), (0.0, 30.0))
        self.assertEqual(AA._span(dict(where="bar 3 (7.0 s)"), 120, 4, 30.0, bars_ok=False), (6.0, 8.5))

    def test_variations_refuses_a_session_whose_meter_changes(self):
        import sys
        from unittest import mock
        from hypnomix.session import variations as V
        p = project.load(self.dir)
        p.meter_changes = 1
        with mock.patch.object(sys, "argv", ["variations", str(self.dir / "Song.ardour")]), \
                mock.patch.object(project, "load", lambda src: p), self.assertRaises(SystemExit) as e:
            V.main()
        self.assertIn("time signature changes", str(e.exception))

    def test_take_number(self):
        from hypnomix.project.ardour import take_number
        self.assertEqual(take_number("Lead Vocal.take 12"), 12)
        for n in ("Lead.1", "Lead.take", "Lead.take 0", ".take 3", "Lead.take 3 (copy)", None):
            self.assertIsNone(take_number(n), n)

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
        (d / "Old.ardour").write_text(OLD, encoding="utf-8")
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
        bad.write_text("<NotASession/>", encoding="utf-8")
        with self.assertRaises(SystemExit):
            project.load(bad)


class TempoRampTest(unittest.TestCase):
    """A tempo ramp is read as HypnoMix Studio plays it (linear per quarter note), not as its start tempo."""

    def test_a_ramp_and_what_follows_it(self):
        import xml.etree.ElementTree as ET
        from hypnomix.project import ardour as AR
        root = ET.fromstring(f"""<Session version="7003"><TempoMap superclocks-per-second="{SC}"><Tempos>
          <Tempo npm="100" enpm="140" note-type="4" type="Ramped" sclock="0" quarters="0:0" bbt="1|1|0" omega="1.4762849584278155e-10"/>
          <Tempo npm="140" enpm="140" note-type="4" type="Constant" sclock="2279182178" quarters="16:0" bbt="5|1|0" omega="0"/>
          </Tempos><Meters><Meter note-value="4" divisions-per-bar="4" sclock="0" quarters="0:0" bbt="1|1|0"/></Meters></TempoMap></Session>""")
        warn = []
        clock, bpm, bpb, n = AR.tempo_map(root, SR, 7003, warn)
        self.assertEqual((bpm, bpb, n, warn), (100.0, 4, 2, []))
        self.assertAlmostEqual(clock.beats_to_s(16), 2279182178 / SC, places=7)     # where the engine put bar 5
        self.assertAlmostEqual(clock.beats_to_s(20), 2279182178 / SC + 4 * 60 / 140, places=7)
        self.assertAlmostEqual(clock.s_to_beats(clock.beats_to_s(5.5)), 5.5, places=9)
        self.assertAlmostEqual(clock.qpm_at(4), 110.0)

    def test_a_continuing_ramp_ends_at_the_next_points_tempo(self):
        # continuing: the engine ramps to the next point's start tempo, whatever this point's own end tempo says
        import xml.etree.ElementTree as ET
        from hypnomix.project import ardour as AR
        root = ET.fromstring(f"""<Session version="7003"><TempoMap superclocks-per-second="{SC}"><Tempos>
          <Tempo npm="100" enpm="120" note-type="4" type="Ramped" continuing="1" sclock="0" quarters="0:0" bbt="1|1|0"/>
          <Tempo npm="140" enpm="140" note-type="4" type="Constant" sclock="2279182178" quarters="16:0" bbt="5|1|0"/>
          </Tempos><Meters><Meter note-value="4" divisions-per-bar="4" sclock="0" quarters="0:0" bbt="1|1|0"/></Meters></TempoMap></Session>""")
        clock, *_ = AR.tempo_map(root, SR, 7003, [])
        self.assertAlmostEqual(clock.qpm_at(8), 120.0)
        self.assertAlmostEqual(clock.beats_to_s(16), 2279182178 / SC, places=6)


class ArdourWriteTest(unittest.TestCase):
    """`fix` writes a NEW .ardour: approved fades, gain, dips and mixer moves land, and nothing else does."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        base = Path(self._td.name)
        self.new = base / "Song"
        self.old = base / "Old"
        with_pan = SESSION.replace('<Controllable name="mute" value="1"/>',
                                   '<Controllable name="mute" value="1"/>\n      <Pannable><Controllable name="pan-azimuth" '
                                   'value="0.5"/></Pannable>')
        for d, name, xml in ((self.new, "Song", with_pan), (self.old, "Old", OLD)):
            af = d / "interchange" / name / "audiofiles"
            af.mkdir(parents=True)
            for fn in ("lead.wav", "comp.wav", "gtr-L.wav", "gtr-R.wav"):
                sf.write(af / fn, np.full(3 * SR, 0.1), SR, subtype="FLOAT")
            (d / f"{name}.ardour").write_text(xml, encoding="utf-8")

    def tearDown(self):
        self._td.cleanup()

    def edit(self, d, name, fn):
        src = d / f"{name}.ardour"
        p = project.load(src)
        fn(p)
        out = d / f"{name} (fixed).ardour"
        AE.save(p, out)
        return src, out

    def test_new_format_all_edits(self):
        def go(p):
            lead = p.track("Lead")
            c, comp = lead.clips
            self.assertTrue(AE.fade(p, c, "out", 0.02, "power"))          # a new fade out with a curve
            self.assertFalse(AE.fade(p, c, "in", 0.01))                   # 0.1 s fade in is already longer
            AE.region_gain(comp, -6.0)
            self.assertEqual(AE.dip(p, lead, 1.5, 1.6, 9.0, 0.02), 1)     # 1.5 s is inside the first region only
            AE.fader(p.track("Vocals"), -3.0)
            AE.pan(p.track("Guitar"), 0.5)
            AE.mute(p.track("Guitar"), False)
        src, out = self.edit(self.new, "Song", go)
        self.assertEqual(AE.check(src, out), [])
        changes = AE.diff(src, out)
        self.assertEqual(len(changes), 6, changes)
        q = project.load(out)
        c, comp = q.track("Lead").clips
        self.assertAlmostEqual(c.fade_out, 0.02, places=6)
        self.assertAlmostEqual(c.fade_in, 0.1, places=6)
        self.assertEqual(c.fade_out_curve[0], (0.0, 1.0))
        self.assertAlmostEqual(c.fade_out_curve[-1][1], 0.0, places=9)
        self.assertAlmostEqual(comp.take.gain, 2 * 10 ** (-6 / 20), places=9)
        low = min(v for t, v in c.envelope if 0.49 < t < 0.61)            # the 1.5 s dip is 0.5 s into the region
        self.assertAlmostEqual(low, 10 ** (-9 / 20), places=6)
        self.assertAlmostEqual(q.track("Vocals").volume, 0.5 * 10 ** (-3 / 20), places=9)
        self.assertAlmostEqual(q.track("Guitar").pan, 0.5)
        self.assertFalse(q.track("Guitar").muted)
        # the old envelope's other points are still there (1 at 1 s and 0 at 2 s, region-relative)
        self.assertTrue(any(abs(t - 1.0) < 1e-6 and abs(v - 1) < 1e-6 for t, v in c.envelope))
        self.assertTrue(any(abs(t - 2.0) < 1e-6 and v == 0 for t, v in c.envelope))
        self.assertIn('length="a', out.read_text(encoding="utf-8"))                       # the times keep Ardour 7's format
        self.assertEqual(q.path.name, "Song (fixed).ardour")
        self.assertEqual(ET_name(out), "Song (fixed)")

    def test_old_format_in_samples(self):
        def go(p):
            tr = p.track("Audio 1")
            AE.fade(p, tr.clips[0], "in", 0.01)
            AE.fade(p, tr.clips[0], "out", 0.02)
            AE.region_gain(tr.clips[0], 3.0)
            self.assertEqual(AE.dip(p, tr, 1.2, 1.3, 6.0, 0.02), 1)
            AE.fader(tr, -6.0)
        src, out = self.edit(self.old, "Old", go)
        self.assertEqual(AE.check(src, out), [])
        text = out.read_text(encoding="utf-8")
        self.assertRegex(text, r"\n480 1\n")                              # fade in: 0.01 s = 480 samples, no 'a' times
        q = project.load(out)
        c = q.track("Audio 1").clips[0]
        self.assertAlmostEqual(c.fade_in, 0.01, places=6)
        self.assertAlmostEqual(c.fade_out, 0.02, places=6)
        self.assertAlmostEqual(c.take.gain, 10 ** (3 / 20), places=9)
        self.assertAlmostEqual(min(v for _, v in c.envelope), 10 ** (-6 / 20), places=6)
        self.assertAlmostEqual(q.track("Audio 1").volume, 0.25 * 10 ** (-6 / 20), places=9)
        self.assertEqual(len(AE.diff(src, out)), 5)
        # (c.start, length, offset unchanged is enforced by check(): nothing but the approved edits differs)
        self.assertEqual((c.start, c.length, c.take.offset), (1.0, 0.5, 0.25))

    def test_ease_and_untouched_parts_identical(self):
        def go(p):
            c = p.track("Lead").clips[1]
            AE.ease(p, c, -4.0, 0.3)
        src, out = self.edit(self.new, "Song", go)
        self.assertEqual(AE.check(src, out), [])
        a = AE._stripped(project.load(src).native)
        b = AE._stripped(project.load(out).native)
        self.assertEqual(AE._same(a, b), [])                                 # everything that is not an edit: identical
        c = project.load(out).track("Lead").clips[1]
        self.assertAlmostEqual(c.envelope[0][1], 10 ** (-4 / 20), places=6)
        self.assertAlmostEqual(c.envelope[-1][1], 1.0)

    def test_check_catches_a_moved_region_and_new_duplicate_ids(self):
        p = project.load(self.new / "Song.ardour")
        p.track("Lead").clips[0].native.set("start", a(0.25))               # not an edit hypnomix makes
        out = self.new / "bad.ardour"
        AE.save(p, out)
        errs = AE.check(self.new / "Song.ardour", out)
        self.assertTrue(errs and any("differs" in e or "moved" in e for e in errs), errs)
        p = project.load(self.new / "Song.ardour")
        p.native.find("Routes").findall("Route")[1].set("id", "100")        # a second id 100
        out2 = self.new / "bad2.ardour"
        AE.save(p, out2)
        self.assertTrue(any("used 2 times" in e for e in AE.check(self.new / "Song.ardour", out2)))

    def test_refusals(self):
        p = project.load(self.new / "Song.ardour")
        with self.assertRaises(ValueError):                                   # this fader plays automation
            AE.fader(p.track("Lead"), -3.0)
        with self.assertRaises(ValueError):
            AE.fade(p, p.track("Keys").clips[0], "in", 0.01)                 # a MIDI region has no fades
        with self.assertRaises(ValueError):
            AE.fade(p, p.track("Lead").clips[0], "in", 0.5, "bouncy")

    def test_fix_run_writes_one_snapshot(self):
        from hypnomix.workflow import fix_ardour as FA
        p = project.load(self.new / "Song.ardour")
        lead = p.track("Lead")
        loc = AE.locator(lead, lead.clips[1])
        items = [
            dict(id="clips-1", tool="clips", track="Lead", where="", edit=dict(op="fade", which="in", seconds=0.01, item=loc)),
            dict(id="clips-2", tool="clips", track="Lead", where="",
                 edit=dict(op="dip", t0=1.5, t1=1.6, db=6.0, ramp=0.02)),
            dict(id="clips-3", tool="clips", track="Lead", where="",
                 edit=dict(op="fade", which="in", seconds=0.01, item=dict(loc, guid="nope", start=99.0))),
            dict(id="names-1", tool="name", track="Lead", where="", edit=dict(op="rename", index=1)),
        ]
        out = self.new / "Song (fixed).ardour"
        wrote, log, failed, skipped = FA.run(Path(self._td.name), {}, self.new / "Song.ardour", out, items, {}, verify=False)
        self.assertEqual(wrote, out)
        self.assertEqual(failed, [])
        self.assertEqual({f["id"] for f, _ in skipped}, {"clips-3", "names-1"})
        self.assertTrue(any("structure check: OK" in l for l in log))
        self.assertEqual(sorted(x.name for x in self.new.glob("*.ardour")), ["Song (fixed).ardour", "Song.ardour"])
        self.assertNotIn("(fixed)", (self.new / "Song.ardour").read_text(encoding="utf-8"))     # the original is untouched


def ET_name(path):
    import xml.etree.ElementTree as ET
    return ET.parse(path).getroot().get("name")


if __name__ == "__main__":
    unittest.main()
