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

    def test_reaper_786_lines(self):
        """Lines exactly as REAPER 7.86 saves them (checked against its own renders)."""
        txt = """<REAPER_PROJECT 0.1 "7.86/macOS-arm64" 1764000000
  TEMPO 100 4 4
  SAMPLERATE 44100 1 0
  <TRACK
    NAME X
    VOLPAN 1 0 -1 -1 1
    <VOLENV2
      ACT 1 -1
      VOLTYPE 1
      PT 0 1 1
      PT 0.5 0.5 1
    >
    <ITEM
      POSITION 0
      LENGTH 2
      FADEIN 5.1 0.5 0 5.1 0 0 0 1 0 0 1 0 0
      FADEOUT 1.1 0 0.2 1 1 0 0 1 0 0 1 0 0
      VOLPAN 1 0 1 -1
      SOFFS 0
      PLAYRATE 1 1 0 -1 0 0.0025
      SM 0.5 0.5 + 1.5 1.2
      <SOURCE WAVE
        FILE "Audio/lead.wav"
      >
    >
  >
>
"""
        (self.dir / "x.rpp").write_text(txt)
        p = project.load(self.dir / "x.rpp")
        c = p.tracks[0].clips[0]
        self.assertEqual(c.fade_in_shape, 6)              # shape 6 is saved as 5.1
        self.assertEqual((c.fade_out, c.fade_out_shape), (0.2, 7))   # auto-crossfade length, equal power
        self.assertEqual(c.stretch_markers, 2)            # one SM line, markers joined by "+"
        self.assertEqual(p.tracks[0].envelopes["Volume"], [(0.0, 1.0), (0.5, 0.5)])  # amplitudes even with VOLTYPE 1

    def test_fade_shapes_match_reaper(self):
        """Values read off REAPER 7.86 renders of a constant 0.5 source, fade in, at x = 0.1 .. 0.9."""
        from hypnomix.project.model import fade_curve
        measured = {1: [0.19, 0.36, 0.51], 2: [0.01, 0.04, 0.09], 3: [0.344, 0.59, 0.76], 4: [0.0, 0.002, 0.008],
                    5: [0.028, 0.104, 0.216], 6: [0.001, 0.013, 0.065], 7: [0.156, 0.309, 0.454]}
        for shape, want in measured.items():
            y = fade_curve(1000, shape)
            for x, v in zip((0.1, 0.2, 0.3), want):
                self.assertAlmostEqual(y[int(x * 1000)], v, delta=0.002, msg=f"shape {shape} at {x}")

    def test_edits_write_a_new_project(self):
        from hypnomix.project import rpp_edit as E
        from hypnomix.project.model import envelope_at
        p = project.load(self.song)
        lead = p.tracks[1]
        c = lead.clips[0]
        self.assertTrue(E.fade(c, "in", 0.05))            # 0.01 -> 0.05
        self.assertFalse(E.fade(c, "out", 0.05))          # 0.1 is already longer: never shortened
        E.item_volume(c, -6.0206)
        E.dip(lead, 1.0, 1.5, 6.0206, ramp=0.02)          # the existing envelope (1.0 -> 0.5 over 2 s) is scaled
        harm = p.tracks[2]
        E.ease(harm, 1.0, 6.0, amount=0.5, ease_s=0.3)    # no envelope yet: one is made, starting at 1.0
        E.add_take(harm.clips[0], self.dir / "Audio" / "lead.wav", "tuned")
        out = self.dir / "Song (fixed).rpp"
        E.save(p, out)
        self.assertEqual(E.check(self.song, out), [])
        q = project.load(out)
        c2 = q.tracks[1].clips[0]
        self.assertEqual(c2.fade_in, 0.05)
        self.assertAlmostEqual(c2.gain, 0.25, places=4)
        env = q.tracks[1].envelopes["Volume"]
        self.assertAlmostEqual(float(envelope_at(env, 1.25)), 0.5 * (1 - 0.5 * 1.25 / 2), places=3)    # dipped by half
        self.assertAlmostEqual(float(envelope_at(env, 1.9)), 1 - 0.5 * 1.9 / 2, places=3)           # ride kept outside
        h = q.tracks[2]
        self.assertAlmostEqual(float(envelope_at(h.envelopes["Volume"], 1.0)), 10 ** (-3 / 20), places=4)
        self.assertEqual(float(envelope_at(h.envelopes["Volume"], 2.0)), 1.0)
        hc = h.clips[0]
        self.assertEqual((len(hc.takes), hc.active, hc.take.name), (2, 1, "tuned"))
        self.assertIn('FILE "Audio/lead.wav"', rpp.dumps(q.native))     # new files are written relative

    def test_fader_curve_is_reapers(self):
        from hypnomix.project.model import from_fader, to_fader
        # ScaleToEnvelopeMode(1, amp) as REAPER 7.86 returned it
        for amp, f in ((1.0, 716.21785031261), (0.5, 592.44867591629), (0.25, 483.25551068857), (2.0, 852.77445440699)):
            self.assertAlmostEqual(float(to_fader(amp)), f, delta=0.6)
            self.assertAlmostEqual(float(from_fader(f)), amp, delta=amp * 0.01)

    def test_one_burst_is_not_a_drum_track(self):
        from hypnomix.workflow.scan_project import spikes
        lv = np.full(1000, -20.0)
        lv[500:506] = 0.0                                  # one 60 ms burst, 20 dB over a steady part
        found = spikes(lv, 0.01, 9.0)
        self.assertEqual(len(found), 1)
        self.assertGreater(found[0][3], 12)
        self.assertFalse(found[0][4])                      # sound right before it: not a phrase-opening consonant

    def test_stretch_markers_follow_reaper(self):
        """Source positions REAPER 7.86 plays (read off a ramp render), item time -> source seconds."""
        from hypnomix.project.model import Take, stretch_map
        cases = [(Take("a", offset=0.0, rate=1.0, stretch=[(0.5, 0.5), (1.5, 1.2)]),
                  [(0.25, 0.25), (0.75, 0.675), (1.25, 1.025), (2.0, 1.7)]),
                 (Take("b", offset=0.3, rate=1.0, stretch=[(0.5, 0.8), (1.5, 1.2)]),
                  [(0.01, 0.31), (0.75, 0.9), (1.75, 1.45)]),
                 (Take("c", offset=0.3, rate=1.25, stretch=[(0.5, 0.8), (1.5, 1.2)]),
                  [(0.25, 0.6125), (0.5, 0.85), (1.0, 1.1), (1.5, 1.575), (2.25, 2.5125)])]
        for tk, pts in cases:
            for x, want in pts:
                self.assertAlmostEqual(float(stretch_map(tk, np.array([x * tk.rate]))[0]), want, places=3, msg=tk.name)

    def test_reorder_keeps_folders_and_sends(self):
        from hypnomix.project import rpp_edit as E
        txt = RPP.replace("  <TRACK {aaaaaaaa", "  <TRACK {aaaaaaaa", 1)
        root = rpp.parse(txt)
        guitar = root.chunks("TRACK")[3]
        guitar.add(rpp.Line(["AUXRECV", 1, 0, 0.5, 0, 0, 0, 0, 0, 0, "-1:U", 0, -1, "''"]))   # a send from Lead Vocal
        (self.dir / "S.rpp").write_text(rpp.dumps(root))
        p = project.load(self.dir / "S.rpp")
        E.reorder(p, [3, 0, 1, 2])                          # Guitar to the top; the folder block keeps its tracks
        out = self.dir / "S (fixed).rpp"
        E.save(p, out)
        self.assertEqual(E.check(self.dir / "S.rpp", out), [])
        q = project.load(out)
        self.assertEqual([t.name for t in q.tracks], ["Guitar", "Vocals", "Lead Vocal", "Harmony"])
        self.assertIs(q.tracks[2].parent, q.tracks[1])
        self.assertIs(q.tracks[3].parent, q.tracks[1])
        src = int(q.tracks[0].native.line("AUXRECV").tokens[1])
        self.assertEqual(q.tracks[src].name, "Lead Vocal")  # the send still comes from the same track
        with self.assertRaises(ValueError):
            E.reorder(project.load(self.dir / "S.rpp"), [1, 0, 2, 3])   # a track above its own folder

    def test_edge_trim_keeps_audio_in_place(self):
        from hypnomix.project import rpp_edit as E
        from hypnomix.workflow import edges_project as EP
        p = project.load(self.song)
        soffs = next(l for l in p.tracks[1].clips[0].take.native if isinstance(l, rpp.Line) and l.key == "SOFFS")
        soffs.set(0.5)                                      # the take starts 0.5 s into its file: room to open the edge
        base = self.dir / "Base.rpp"
        E.save(p, base)
        p = project.load(base)
        lead = p.tracks[1]
        c = lead.clips[0]
        before = c.start - c.take.offset
        self.assertAlmostEqual(EP.move_start(lead, c, 0.06), 0.06)
        EP.set_fade_exact(c, "in", 0.01)
        out = self.dir / "Song (fixed).rpp"
        E.save(p, out)
        self.assertNotEqual(E.check(base, out), [])                  # a moved edge is refused by default
        self.assertEqual(E.check(base, out, trims=True), [])         # allowed for approved edge fixes
        d = project.load(out).tracks[1].clips[0]
        self.assertAlmostEqual(d.start, 0.94, places=6)
        self.assertAlmostEqual(d.start - d.take.offset, before, places=6)                     # audio anchored
        self.assertEqual(d.fade_in, 0.01)

    def _stack(self, lanes=False):
        """A folder of three vocal tracks; in the last section Harmony 1 sings the top part and Harmony 2 the middle."""
        import uuid
        for f0 in (196, 247, 294):
            t = np.arange(int(2.0 * SR)) / SR
            ph = 2 * np.pi * f0 * t
            env = np.minimum(1, np.minimum(t / 0.05, (2.0 - t) / 0.1))
            sf.write(self.dir / "Audio" / f"v{f0}.wav", (0.25 * env * (np.sin(ph) + 0.4 * np.sin(2 * ph))).astype(np.float32),
                     SR, subtype="FLOAT")
        g = lambda: "{" + str(uuid.uuid4()).upper() + "}"
        item = lambda pos, f0: (f"    <ITEM\n      POSITION {pos}\n      LENGTH 2\n      LOOP 0\n      IGUID {g()}\n"
                                f"      VOLPAN 1 0 1 -1\n      SOFFS 0\n      PLAYRATE 1 1 0 -1 0 0.0025\n"
                                f"      <SOURCE WAVE\n        FILE \"Audio/v{f0}.wav\"\n      >\n    >")
        track = lambda name, bus, vol, ps, extra="": (f"  <TRACK {g()}\n    NAME \"{name}\"\n    VOLPAN {vol} 0 -1 -1 1\n"
                                                      f"    ISBUS {bus}\n{extra}" + "\n".join(item(3 * k, f) for k, f in enumerate(ps)) + "\n  >")
        txt = "\n".join(['<REAPER_PROJECT 0.1 "7.86/macOS-arm64" 1', "  TEMPO 120 4 4", f"  <TRACK {g()}\n    NAME Vocals\n    ISBUS 1 1\n  >",
                         track("Lead Vocal", "0 0", 1.0, [196, 196, 196]),
                         track("Harmony 1", "0 0", 0.5, [247, 247, 294], "    FREEMODE 2\n" if lanes else ""),
                         track("Harmony 2", "2 -1", 1.0, [294, 294, 247]), ">", ""])
        path = self.dir / ("Stack lanes.rpp" if lanes else "Stack.rpp")
        path.write_text(txt)
        p = project.load(path)
        orow = [dict(id=str(t.index), kind="Group" if t.kind == "folder" else "Audio", cat=3,
                     parent=str(t.parent.index) if t.parent else None) for t in p.tracks]
        return path, p, orow

    def test_vocal_stack_moves(self):
        from hypnomix.project import rpp_edit as E
        from hypnomix.workflow.scan_project import stack_moves
        path, p, orow = self._stack()
        st = stack_moves(p, orow)
        self.assertEqual(len(st), 1)
        mv = st[0]["moves"]
        self.assertEqual(sorted((m["src_name"], m["dst_name"]) for m in mv),
                         [("Harmony 1", "Harmony 2"), ("Harmony 2", "Harmony 1")])
        self.assertEqual(st[0]["hand"], [])
        for m in mv:                                        # Harmony 1's fader is 6 dB lower: same level in the mix
            self.assertAlmostEqual(abs(m["gain_db"]), 6.02, places=2)
            hit = E.locate(p, m["item"])
            E.move_item(hit[0], hit[1], p.tracks[m["dst"]], m["gain_db"])
        out = self.dir / "Stack (fixed).rpp"
        E.save(p, out)
        guids = {m["item"]["guid"] for m in mv}
        self.assertEqual(E.check(path, out, moved=guids), [])
        self.assertNotEqual(E.check(path, out), [])         # moves are refused unless they were approved
        q = project.load(out)
        self.assertEqual([c.path.stem for c in q.tracks[2].clips], ["v247"] * 3)
        self.assertEqual([c.path.stem for c in q.tracks[3].clips], ["v294"] * 3)

    def test_vocal_stack_lanes_are_by_hand(self):
        from hypnomix.workflow.scan_project import stack_moves
        _, p, orow = self._stack(lanes=True)
        st = stack_moves(p, orow)
        self.assertEqual(st[0]["moves"], [])
        self.assertTrue(all("lanes" in h["why"] for h in st[0]["hand"]))

    def test_unsupported_suffix(self):
        with self.assertRaises(SystemExit):
            project.load(self.dir / "x.ptx")


if __name__ == "__main__":
    unittest.main()
