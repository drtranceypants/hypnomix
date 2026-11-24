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
