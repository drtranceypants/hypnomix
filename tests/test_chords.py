"""The chord check before pitch correction: a target that clashes with the chord underneath is asked, not moved."""
import types
import unittest
import xml.etree.ElementTree as ET

import numpy as np

from hypnomix.studio import chords as CH
from hypnomix.studio import tune
from hypnomix.session import sources as SRC


def chord_frames(pcs_by_second, seconds):
    """Chroma with the given pitch classes sounding in each whole second."""
    n = int(seconds / CH.HOP_S) + 1
    ch = np.zeros((12, n))
    for k in range(n):
        for pc, w in pcs_by_second(int(k * CH.HOP_S)).items():
            ch[pc, k] = w
    return ch


C_MAJOR = {0: 1.0, 4: 0.6, 7: 0.5}          # C E G
G_MAJOR = {7: 1.0, 11: 0.6, 2: 0.5}         # G B D


def args(**kw):
    a = types.SimpleNamespace(tolerance=20.0, max=25.0, amount=0.35, _scales=None, _chords=None, _note_answers=[])
    a.__dict__.update(kw)
    return a


def note(midi_centre, t0=1.1, t1=1.9):
    return dict(centre=midi_centre, t0=t0, t1=t1, k0=0, k1=1)


class Tones(unittest.TestCase):
    def test_reads_the_chord(self):
        ch = chord_frames(lambda s: C_MAJOR if s < 2 else G_MAJOR, 4)
        self.assertEqual(set(CH.tones(ch, 0.2, 1.8)), {0, 4, 7})
        self.assertEqual(set(CH.tones(ch, 2.2, 3.8)), {7, 11, 2})

    def test_silence_says_nothing(self):
        ch = np.zeros((12, 100))
        self.assertEqual(CH.tones(ch, 0.1, 0.5), [])
        self.assertEqual(CH.verdict(59, 60, ch, 0.1, 0.5)[0], "ok")

    def test_verdict(self):
        ch = chord_frames(lambda s: C_MAJOR, 3)
        self.assertEqual(CH.verdict(60, 59, ch, 1, 2)[0], "ok")            # C over C: fine
        v, pcs, sug = CH.verdict(59, 60, ch, 1, 2)                          # B over C, C is the other neighbour
        self.assertEqual((v, sug), ("ask", 60))
        self.assertEqual(CH.verdict(62, 61, ch, 1, 2)[0], "colour")        # D over C, C# not in it either


class Targets(unittest.TestCase):
    key = (7, "major")                                                      # G major: B and C are both in key

    def test_small_fix_toward_a_clashing_note_is_asked(self):
        ch = chord_frames(lambda s: C_MAJOR, 3)
        n = note(59.22)                                                     # B3 +22 cents, over a C chord
        tune.choose_targets([n], 0.0, self.key, None, args(_chords=ch))
        self.assertEqual(n["action"], "ask")
        self.assertEqual(n["shift"], 0.0)
        self.assertEqual(int(round(n["suggest"])), 60)

    def test_fix_that_fits_the_chord_is_applied(self):
        ch = chord_frames(lambda s: G_MAJOR, 3)
        n = note(59.22)                                                     # B3 +22 over G: B is the third
        tune.choose_targets([n], 0.0, self.key, None, args(_chords=ch))
        self.assertEqual(n["action"], "fix")
        self.assertLess(n["shift"], 0)

    def test_far_note_is_flagged_with_the_chord_suggestion(self):
        ch = chord_frames(lambda s: C_MAJOR, 3)
        n = note(59.41)                                                     # B3 +41: past --max, left alone
        tune.choose_targets([n], 0.0, self.key, None, args(_chords=ch))
        self.assertEqual(n["action"], "flag")
        self.assertEqual(int(round(n["suggest"])), 60)

    def test_the_persons_answer_wins(self):
        ch = chord_frames(lambda s: C_MAJOR, 3)
        n = note(59.41)
        tune.choose_targets([n], 0.0, self.key, None,
                            args(_chords=ch, _note_answers=tune.parse_note_answers(["0:01.10=C"])))
        self.assertEqual(n["action"], "fix")
        self.assertEqual(int(round(n["target"])), 60)
        self.assertGreater(n["shift"], 0)

    def test_without_chords_nothing_changes(self):
        n = note(59.22)
        tune.choose_targets([n], 0.0, self.key, None, args())
        self.assertEqual(n["action"], "fix")


class TakeTime(unittest.TestCase):
    def test_song_chords_follow_the_clip_into_the_take(self):
        song = chord_frames(lambda s: C_MAJOR if s < 10 else G_MAJOR, 20)
        # the clip plays take seconds 0-5 at song time 10-15 (G), so the take's first seconds read G
        tk = CH.take_time(song, [(10.0, 15.0, 0.0, 5.0)], int(8 / CH.HOP_S))
        self.assertEqual(set(CH.tones(tk, 1, 4)), {7, 11, 2})
        self.assertEqual(CH.tones(tk, 6, 7.5), [])                         # never played: no chord

    def test_unwarped_clip_spans(self):
        x = ('<AudioClip Time="16"><CurrentStart Value="16" /><CurrentEnd Value="24" /><IsWarped Value="false" />'
             '<Loop><LoopStart Value="3" /><StartRelative Value="0" /></Loop></AudioClip>')
        sp = SRC.song_spans(ET.fromstring(x), 120.0)
        self.assertEqual(len(sp), 1)
        s0, s1, r0, r1 = sp[0]
        self.assertAlmostEqual(s0, 8.0)
        self.assertAlmostEqual(s1, 12.0)
        self.assertAlmostEqual(r0, 3.0)
        self.assertAlmostEqual(r1, 7.0)

    def test_warped_clip_spans_follow_markers(self):
        x = ('<AudioClip Time="0"><CurrentStart Value="0" /><CurrentEnd Value="4" /><IsWarped Value="true" />'
             '<Loop><LoopStart Value="0" /><StartRelative Value="0" /></Loop><WarpMarkers>'
             '<WarpMarker Id="0" SecTime="0" BeatTime="0" /><WarpMarker Id="1" SecTime="4" BeatTime="4" />'
             '</WarpMarkers></AudioClip>')
        sp = SRC.song_spans(ET.fromstring(x), 120.0)                       # 4 beats = 2 s of song, 4 s of take
        self.assertAlmostEqual(sp[0][0], 0.0)
        self.assertAlmostEqual(sp[-1][1], 2.0)
        self.assertAlmostEqual(sp[-1][3], 4.0)

    def test_saved_marker_list_is_ignored(self):
        x = ('<AudioClip Time="0"><CurrentStart Value="0" /><CurrentEnd Value="4" /><IsWarped Value="true" />'
             '<Loop><LoopStart Value="0" /><StartRelative Value="0" /></Loop><WarpMarkers>'
             '<WarpMarker Id="0" SecTime="0" BeatTime="0" /><WarpMarker Id="1" SecTime="4" BeatTime="4" />'
             '</WarpMarkers><SavedWarpMarkersForStretched>'
             '<WarpMarker Id="0" SecTime="0" BeatTime="0" /><WarpMarker Id="1" SecTime="9" BeatTime="2" />'
             '</SavedWarpMarkersForStretched></AudioClip>')
        sp = SRC.song_spans(ET.fromstring(x), 120.0)
        self.assertAlmostEqual(sp[-1][3], 4.0)                              # the clip's own markers, not the saved list


if __name__ == "__main__":
    unittest.main()
