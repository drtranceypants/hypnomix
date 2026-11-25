"""REAPER projects: the .rpp parser round-trips, the reader builds the right model, the renderer places audio."""
import math

import numpy as np
import tempfile
import unittest
from pathlib import Path
import soundfile as sf

from hypnomix import project
from hypnomix.project import rpp

SR = 44100

RPP = """<REAPER_PROJECT 0.1 "7.27/macOS-arm64" 1764000000
  <NOTES 0 2
  >
  RIPPLE 0
  TEMPO 100 4 4
  PLAYRATE 1 0 0.25 4
  SAMPLERATE 44100 0 0
  RECORD_PATH "Audio" ""
  <TEMPOENVEX
    EGUIDSTATE {00000000-0000-0000-0000-000000000000}
    ACT 0 -1
  >
  <TRACK {11111111-1111-1111-1111-111111111111}
    NAME Vocals
    PEAKCOL 16576
    VOLPAN 0.5 0 -1 -1 1
    MUTESOLO 0 0 0
    IPHASE 0
    ISBUS 1 1
    FX 1
  >
  <TRACK {22222222-2222-2222-2222-222222222222}
    NAME "Lead Vocal"
    VOLPAN 1 -0.25 -1 -1 1
    MUTESOLO 0 0 0
    IPHASE 0
    ISBUS 0 0
    FX 1
    <FXCHAIN
      WNDRECT 0 0 0 0
      SHOW 0
      LASTSEL 0
      DOCKED 0
      BYPASS 0 0 0
      <VST "VST: ReaEQ (Cockos)" reaeq.vst.dylib 0 "" 1919247729<56535472656571726561657100000000> ""
        cWVlcu5e7f4CAAAAAQAAAAAAAAACAAAAAAAAAAIAAAABAAAAAAAAAAIAAAAAAAAAXAAAAAEAAAAAAAAA
        AFJlYUVRAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==
      >
      PRESETNAME "Vocal low cut"
      FLOATPOS 0 0 0 0
      FXID {33333333-3333-3333-3333-333333333333}
      WAK 0 0
      BYPASS 1 0 0
      <JS "loser/3BandEQ" ""
        0 200 2000 0 - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
      >
      FLOATPOS 0 0 0 0
      FXID {44444444-4444-4444-4444-444444444444}
      WAK 0 0
    >
    <VOLENV2
      EGUIDSTATE {55555555-5555-5555-5555-555555555555}
      ACT 1 -1
      VIS 1 1 1
      LANEHEIGHT 0 0
      ARM 0
      DEFSHAPE 0 -1 -1
      PT 0 1 0
      PT 2 0.5 0
    >
    <ITEM
      POSITION 1
      SNAPOFFS 0
      LENGTH 1
      LOOP 0
      ALLTAKES 0
      FADEIN 1 0.01 0 1 0 0 0
      FADEOUT 1 0.1 0 1 0 0 0
      MUTE 0 0
      SEL 0
      IGUID {66666666-6666-6666-6666-666666666666}
      IID 1
      NAME "take one"
      VOLPAN 0.5 0 1 -1
      SOFFS 0.5
      PLAYRATE 1 1 0 -1 0 0.0025
      CHANMODE 0
      GUID {77777777-7777-7777-7777-777777777777}
      <SOURCE WAVE
        FILE "Audio/lead.wav"
      >
      TAKE SEL
      NAME "take two"
      TAKEVOLPAN 0 2 -1
      SOFFS 0
      PLAYRATE 1 1 0 -1 0 0.0025
      CHANMODE 0
      GUID {88888888-8888-8888-8888-888888888888}
      <SOURCE WAVE
        FILE "Audio/lead.wav"
      >
    >
  >
  <TRACK {99999999-9999-9999-9999-999999999999}
    NAME Harmony
    VOLPAN 1 0 -1 -1 1
    MUTESOLO 1 0 0
    IPHASE 0
    ISBUS 2 -1
    FX 1
    <ITEM
      POSITION 0
      LENGTH 2.5
      LOOP 1
      FADEIN 1 0 0 1 0 0 0
      FADEOUT 1 0 0 1 0 0 0
      MUTE 0 0
      NAME loop
      VOLPAN 1 0 1 -1
      SOFFS 0
      PLAYRATE 1 1 0 -1 0 0.0025
      <SOURCE SECTION
        LENGTH 1
        STARTPOS 0
        OVERLAP 0
        <SOURCE WAVE
          FILE "lead.wav"
        >
      >
    >
  >
  <TRACK {aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}
    NAME Guitar
    VOLPAN 1 1 -1 -1 1
    MUTESOLO 0 0 0
    ISBUS 0 0
    <ITEM
      POSITION 0.5
      LENGTH 0.5
      LOOP 0
      FADEIN 1 0 0 1 0 0 0
      FADEOUT 1 0 0 1 0 0 0
      MUTE 0 0
      NAME gone.wav
      VOLPAN 1 0 1 -1
      SOFFS 0
      PLAYRATE 1 1 0 -1 0 0.0025
      <SOURCE WAVE
        FILE "/nowhere/gone.wav"
      >
    >
  >
>
"""


class Reaper(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)
        (self.dir / "Audio").mkdir()
        # 3 s ramp, so every sample says where in the file it came from
        y = (np.arange(3 * SR) / (3 * SR)).astype(np.float32)
        sf.write(self.dir / "Audio" / "lead.wav", y, SR, subtype="FLOAT")
        self.song = self.dir / "Song.rpp"
        self.song.write_text(RPP)

    def tearDown(self):
        self._td.cleanup()

    def test_split_quotes(self):
        self.assertEqual(rpp.split('NAME "Lead Vocal"'), ["NAME", "Lead Vocal"])
        self.assertEqual(rpp.split("NAME 'say \"hi\"'"), ["NAME", 'say "hi"'])
        self.assertEqual(rpp.split("PT 0 1 0"), ["PT", "0", "1", "0"])
        self.assertEqual(rpp.quote("a b"), '"a b"')
        self.assertEqual(rpp.quote('say "hi"'), "'say \"hi\"'")

    def test_roundtrip_is_identical(self):
        root = rpp.load(self.song)
        self.assertEqual(rpp.dumps(root), RPP)
        with self.assertRaises(SystemExit):
            rpp.save(root, self.song)          # never over the original
        root.chunks("TRACK")[1].set("VOLPAN", 0.7, -0.25, -1, -1, 1)
        txt = rpp.save(root, self.dir / "Song (fixed).rpp").read_text()
        self.assertIn("    VOLPAN 0.7 -0.25 -1 -1 1", txt)
        self.assertEqual(txt.count("\n"), RPP.count("\n"))

    def test_reader(self):
        p = project.load(self.song)
        self.assertEqual((p.daw, p.tempo, p.beats_per_bar), ("reaper", 100, 4))
        self.assertEqual([t.name for t in p.tracks], ["Vocals", "Lead Vocal", "Harmony", "Guitar"])
        folder, lead, harm, gtr = p.tracks
        self.assertEqual(folder.kind, "folder")
        self.assertIs(lead.parent, folder); self.assertIs(harm.parent, folder); self.assertIsNone(gtr.parent)
        self.assertTrue(harm.muted); self.assertFalse(harm.on); self.assertTrue(lead.on)
        self.assertEqual(lead.pan, -0.25)
        self.assertAlmostEqual(folder.volume_db, -6.02, places=2)
        self.assertEqual([(d.name, d.kind, d.on, d.preset) for d in lead.devices],
                         [("ReaEQ (Cockos)", "VST", True, "Vocal low cut"), ("3BandEQ", "JS", False, "")])
        self.assertEqual(lead.devices[1].params["slider2"], 200)
        self.assertEqual(lead.envelopes["Volume"], [(0.0, 1.0), (2.0, 0.5)])
        c = lead.clips[0]
        self.assertEqual((len(c.takes), c.active, c.take.name), (2, 1, "take two"))
        self.assertAlmostEqual(c.level, 0.5 * 2)                 # item volume x active take volume
        self.assertEqual(c.fade_out, 0.1); self.assertEqual(c.path.name, "lead.wav")
        loop = harm.clips[0]
        self.assertTrue(loop.loop); self.assertEqual(loop.take.section, (0.0, 1.0)); self.assertTrue(loop.path.exists())
        self.assertEqual([x[2].name for x in p.missing()], ["gone.wav"])
        self.assertAlmostEqual(p.bar(2.4), 2.0)                  # 100 BPM, 4/4: a bar is 2.4 s

    def test_render_places_and_gains(self):
        p = project.load(self.song)
        lead, harm = p.tracks[1], p.tracks[2]
        y = p.render(lead, SR, length=3)
        self.assertTrue(np.all(y[: SR - 1] == 0))                # nothing before the item at 1 s
        # 0.5 s into the item: take two (SOFFS 0) at 0.5 s of the ramp, item 0.5 x take 2.0
        self.assertAlmostEqual(y[int(1.5 * SR)], 0.5 / 3 * 1.0, places=4)
        self.assertLess(y[int(1.95 * SR)], 0.95 / 3)              # inside the 0.1 s fade out
        h = p.render(harm, SR, length=3)
        # looped 1 s section: 1.25 s plays the source at 0.25 s
        self.assertAlmostEqual(h[int(1.25 * SR)], 0.25 / 3, places=4)

    def test_unsupported_suffix(self):
        with self.assertRaises(SystemExit):
            project.load(self.dir / "x.ptx")


if __name__ == "__main__":
    unittest.main()
