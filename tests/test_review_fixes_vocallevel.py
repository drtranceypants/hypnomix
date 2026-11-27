"""Review fixes for `hypnomix vocallevel` on REAPER projects: a MIDI track inside the vocal folder keeps the folder
from being automated; curved or square envelope points in a change window are refused, not split; a vocal folder with
its own trims gets them plus the evening once; track names never bind to another track by prefix. Synthetic only."""
import unittest
from argparse import Namespace

import numpy as np
import soundfile as sf

from hypnomix import project
from tests.test_vocallevel_reaper import Base, LEN, SR, env_db, g, item, tone, track
from hypnomix.workflow import vocallevel_project as VP


def midi_track(name):
    return (f"  <TRACK {g()}\n    NAME \"{name}\"\n    VOLPAN 1 0 -1 -1 1\n    ISBUS 2 -1\n    <ITEM\n      POSITION 0\n"
            f"      LENGTH {LEN}\n      IGUID {g()}\n      <SOURCE MIDI\n        HASDATA 1 960 QN\n        E 0 90 3c 60\n"
            f"        E 960 80 3c 00\n      >\n    >\n  >")


class MidiInFolder(Base):
    def song_with_midi(self):
        lead = self.wav("lead.wav", tone(220, -20, (7.0, 10.0, -3.5)))
        harm = self.wav("harm.wav", tone(440, -19))
        parts = ['<REAPER_PROJECT 0.1 "7.86/macOS-arm64" 1', "  TEMPO 120 4 4", "  SAMPLERATE 44100 0 0",
                 track("Vocals", "1 1"), track("Lead Vocal", "0 0", 1.0, lead), track("Harmony", "0 0", 1.0, harm),
                 midi_track("Pad Synth")]
        path = self.dir / "Song.rpp"
        path.write_text("\n".join(parts + [">", ""]), encoding="utf-8")
        return path

    def test_midi_track_counts_as_non_vocal(self):
        path = self.song_with_midi()
        p = project.load(path)
        self.assertEqual(p.track("Pad Synth").parent.name, "Vocals")
        self.assertEqual(VP.non_vocal_members(p, "Vocals", ["Lead Vocal", "Harmony"]), ["Pad Synth"])

    def test_folder_with_midi_is_never_automated(self):
        path = self.song_with_midi()
        out = self.dir / "new.rpp"
        code, text = self.run_cli(path, "--tracks", "Lead Vocal", "Harmony", "--apply", out)
        self.assertEqual(code, 0, text)
        self.assertIn("also holds Pad Synth", text)
        self.assertIsNone(env_db(out, "Vocals"))
        self.assertIsNone(env_db(out, "Pad Synth"))
        lead = env_db(out, "Lead Vocal")
        self.assertIsNotNone(lead)
        self.assertGreater(max(v for _, v in lead), 1.5)


class CurvedPoints(Base):
    def shaped(self, shape, at=(5.0, 0.7)):
        path = self.song(lead_env=[(0, 1.0), at, (18.5, 0.6)], harmony_db=-40)
        txt = path.read_text(encoding="utf-8").replace(f"PT {at[0]} {at[1]} 0", f"PT {at[0]} {at[1]} {shape}")
        path.write_text(txt, encoding="utf-8")
        return path

    def test_square_point_in_window_is_refused(self):
        path = self.shaped(1)                              # 5.0 -> 18.5 segment, square, spans the change at 7 s
        p = project.load(path)
        lead = p.track("Lead Vocal")
        before = [ln.tokens[:] for ln in lead.native.chunk("VOLENV2").lines("PT")]
        with self.assertRaises(ValueError) as cm:
            VP.write_gains(lead, [(7.0, 10.0, 2.0)])
        self.assertIn("by hand", str(cm.exception))
        self.assertEqual([ln.tokens for ln in lead.native.chunk("VOLENV2").lines("PT")], before)   # untouched

    def test_refused_track_is_listed(self):
        path = self.shaped(5)
        p = project.load(path)
        done, _, refused = VP.apply_gains(p, {"Lead Vocal": [(7.0, 10.0, 2.0)]}, None, ["Lead Vocal"], log=lambda *_: 0)
        self.assertEqual(done, [])
        self.assertEqual(len(refused), 1)
        self.assertIn("Lead Vocal", refused[0])

    def test_shaped_point_outside_window_or_linear_is_kept(self):
        for shape, at in ((0, (5.0, 0.7)), (2, (18.0, 0.7))):     # linear; or a curve far from the change
            with self.subTest(shape=shape):
                path = self.shaped(shape, at)
                p = project.load(path)
                self.assertEqual(VP.write_gains(p.track("Lead Vocal"), [(7.0, 10.0, 2.0)]), 1)

    def test_square_hold_between_equal_values_is_fine(self):
        path = self.song(lead_env=[(0, 1.0), (5.0, 0.7), (12.0, 0.7)], harmony_db=-40)
        path.write_text(path.read_text(encoding="utf-8").replace("PT 5.0 0.7 0", "PT 5.0 0.7 1"), encoding="utf-8")
        p = project.load(path)
        self.assertEqual(VP.write_gains(p.track("Lead Vocal"), [(7.0, 10.0, 2.0)]), 1)


class GroupOwnTrims(Base):
    def song_folder_vocal(self):
        """"Harmony" is a folder with its own vocal item, holding "Harmony Double"; the melody sits outside."""
        lead = self.wav("lead.wav", tone(220, -20))
        harm = self.wav("harm.wav", tone(440, -19))
        dbl = self.wav("dbl.wav", tone(445, -25))
        parts = ['<REAPER_PROJECT 0.1 "7.86/macOS-arm64" 1', "  TEMPO 120 4 4", "  SAMPLERATE 44100 0 0",
                 track("Lead Vocal", "0 0", 1.0, lead), track("Harmony", "1 1", 1.0, harm),
                 track("Harmony Double", "2 -1", 1.0, dbl)]
        path = self.dir / "Song.rpp"
        path.write_text("\n".join(parts + [">", ""]), encoding="utf-8")
        return path

    def test_group_own_trims_are_kept_and_evening_once(self):
        path = self.song_folder_vocal()
        p = project.load(path)
        vocals = ["Harmony", "Harmony Double"]
        gains = {"Harmony": [(0.0, 7.0, 0.0), (7.0, 10.0, -2.0), (10.0, LEN, 0.0)],
                 "__group__": [(0.0, 7.0, 0.0), (7.0, 10.0, 1.0), (10.0, LEN, 0.0)]}
        logs = []
        done, _, refused = VP.apply_gains(p, gains, "Harmony", vocals, log=logs.append)
        self.assertEqual(refused, [])
        self.assertTrue(any("own trims" in m for m in logs), logs)
        h = {round(t, 2): 20 * np.log10(v) for t, v, _ in VP_points(p, "Harmony")}
        self.assertAlmostEqual(h[min(h, key=lambda t: abs(t - 8.5))], -1.0, delta=0.05)    # -2 own + 1 evening
        self.assertIsNone(p.track("Harmony Double").native.chunk("VOLENV2"))              # gets it via the folder


def VP_points(p, name):
    from hypnomix.project import rpp_edit as E
    return E.points(p.track(name).native.chunk("VOLENV2"))


class FindTrack(Base):
    def test_no_prefix_binding_for_file_stems(self):
        path = self.song()
        p = project.load(path)
        self.assertIsNone(VP.find_track(p, "Lead"))
        self.assertIsNone(VP.find_track(p, "Harm"))
        self.assertEqual(VP.find_track(p, "lead vocal").name, "Lead Vocal")
        self.assertEqual(VP.find_track(p, "Harm", prefix=True).name, "Harmony")
        self.assertIsNone(VP.find_track(p, "", prefix=True))                    # ambiguous: every track begins so

    def test_unmatched_render_is_not_put_on_another_track(self):
        path = self.song()
        p = project.load(path)
        rd = self.dir / "renders"
        rd.mkdir()
        y = p.render(p.track("Lead Vocal"), SR).astype(np.float32)
        sf.write(rd / "Lead.wav", y, SR, subtype="FLOAT")
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sig, _, _ = VP.signals(p, Namespace(renders=str(rd), heard=None, tracks=None))
        self.assertIn("Lead", sig)
        self.assertNotIn("Lead Vocal", sig)
        self.assertIn("no such track", buf.getvalue())


class MisspeltNames(Base):
    """A --melody or --lines-from that names no vocal track stops, as it does for a Live set (it was measured as
    silence before)."""
    def test_misspelt_melody_stops(self):
        path = self.song()
        with self.assertRaises(SystemExit) as cm:
            self.run_cli(path, "--melody", "Leed Vocal")
        self.assertIn("no track called 'Leed Vocal'", str(cm.exception))

    def test_misspelt_lines_from_stops(self):
        path = self.song()
        with self.assertRaises(SystemExit) as cm:
            self.run_cli(path, "--lines-from", "Harmny")
        self.assertIn("--lines-from: no track called 'Harmny'", str(cm.exception))

    def test_a_prefix_of_the_melody_still_works(self):
        code, out = self.run_cli(self.song(), "--melody", "Lead")
        self.assertIn(code, (0, None))


if __name__ == "__main__":
    unittest.main()
