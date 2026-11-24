"""vocalign's independent timing check, grid lag, refusal of results that aren't tighter; render's song end."""
import unittest
import xml.etree.ElementTree as ET
import numpy as np
from hypnomix.studio import vocalign as V
from hypnomix.session.render import song_end


def clicks(sr, n_s, every_s, shift_s=0.0):
    y = np.zeros(int(n_s * sr))
    for t in np.arange(0.5, n_s - 0.5, every_s):
        i = int((t + shift_s) * sr)
        y[i:i + 200] = np.hanning(200)
    return y[:, None]


class Checks(unittest.TestCase):
    def test_onset_lag_sees_a_shift(self):
        sr = 22050
        a, b = clicks(sr, 12, 0.37), clicks(sr, 12, 0.37, 0.03)
        self.assertLess(V.onset_lag_ms(a, a, sr), 3)
        self.assertGreater(V.onset_lag_ms(a, b, sr), 20)

    def test_grid_lag_finds_a_late_stack(self):
        bpm = 120.0
        n = int(16 * 2.0 / V.FR_S)                         # 16 bars at 120 BPM in 10 ms frames
        env = np.zeros(n)
        step = 60 / bpm / 2 / V.FR_S                        # an 8th = 25 frames
        for k in np.arange(0, n, step):
            j = int(round(k)) + 3                           # every 8th, 30 ms late
            if j < n:
                env[j] = 1.0
        g = V.grid_lag(env, n, bpm)
        self.assertAlmostEqual(float(np.median(g)), 3.0, delta=1.0)


SET = """<Ableton><LiveSet><Tracks>
<AudioTrack><Name><EffectiveName Value="a"/></Name><DeviceChain><Mixer><Speaker><Manual Value="true"/></Speaker></Mixer>
<MainSequencer><Sample><ArrangerAutomation><Events>{clips}</Events></ArrangerAutomation></Sample></MainSequencer></DeviceChain></AudioTrack>
</Tracks></LiveSet></Ableton>"""
CLIP = '<AudioClip><CurrentStart Value="{s}"/><CurrentEnd Value="{e}"/><Disabled Value="false"/></AudioClip>'


class SongEnd(unittest.TestCase):
    def test_a_stray_clip_far_past_the_song_is_not_the_end(self):
        clips = "".join(CLIP.format(s=i * 16, e=i * 16 + 16) for i in range(30)) + CLIP.format(s=4000, e=4064)
        end, strays = song_end(ET.fromstring(SET.format(clips=clips)))
        self.assertEqual(end, 480.0)
        self.assertEqual(len(strays), 1)


if __name__ == "__main__":
    unittest.main()


class SameWords(unittest.TestCase):
    def test_only_parts_singing_together_are_marked(self):
        rng = np.random.default_rng(1)
        n = 1000
        words = np.zeros(n); words[rng.choice(n, 80, replace=False)] = 1.0
        own = np.zeros(n); own[rng.choice(n, 80, replace=False)] = 1.0
        m = V.sharing_mask({"a": words, "b": np.roll(words, 3), "c": own}, n, thr=0.6)
        self.assertGreater(m["a"].mean(), 0.8)
        self.assertGreater(m["b"].mean(), 0.8)       # same words, 30 ms apart
        self.assertLess(m["c"].mean(), 0.2)          # its own line: left alone

    def test_still_parts_keep_the_original_audio(self):
        sr = 22050
        orig = np.random.default_rng(2).standard_normal((sr, 1))
        warped = orig * 0.5
        out, frac = V.keep_original_where_still(orig, warped, np.zeros(int(1 / V.FR_S)), sr)
        self.assertEqual(frac, 0.0)
        self.assertTrue(np.array_equal(out, orig))


class Words(unittest.TestCase):
    def test_a_late_word_is_measured_and_only_it_is_fixed(self):
        n = 600
        env = np.zeros(n); others = np.zeros(n)
        starts = [50, 150, 250, 350, 450]
        for s0 in starts:                                     # each word: a few onset bumps
            for k in (0, 7, 15):
                others[s0 + k] = 1.0
                env[s0 + k + (6 if s0 == 150 else 0)] = 1.0     # the 2nd word is 60 ms late, the rest on time
        spans = [(s0, s0 + 40) for s0 in starts]
        errs = V.word_errors(env, others, spans)
        self.assertAlmostEqual(errs[1], 6.0, delta=1.0)
        self.assertTrue(all(abs(e) < 1.0 for i, e in enumerate(errs) if i != 1))
        o, words = V.word_plan(np.zeros(n), spans, np.ones(n), 3.0, 0.8, 0.1, 6.0, errs)
        moves = {a: mv for a, b, err, mv in words}
        self.assertAlmostEqual(moves[150], 4.8, delta=0.8)    # fixed: 80% of the way
        self.assertTrue(all(abs(moves[a]) < 0.2 for a in moves if a != 150))   # the rest: barely touched
