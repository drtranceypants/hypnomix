"""unroll: a looped clip becomes one copy per pass and renders sample for sample the same."""
import tempfile, unittest
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
import soundfile as sf
from hypnomix.session import unroll as U
from hypnomix.session.render import render_track

CLIP = """<AudioClip Id="3"><CurrentStart Value="{cs}"/><CurrentEnd Value="{ce}"/>
<Loop><LoopStart Value="{ls}"/><LoopEnd Value="{le}"/><StartRelative Value="{rel}"/><LoopOn Value="true"/>
<OutMarker Value="{le}"/><HiddenLoopStart Value="{ls}"/><HiddenLoopEnd Value="{le}"/></Loop>
<Name Value="loop"/><Disabled Value="false"/><IsWarped Value="true"/><SampleVolume Value="0.8"/>
<Fades><FadeInLength Value="0"/><FadeOutLength Value="0"/><IsDefaultFadeIn Value="true"/><IsDefaultFadeOut Value="true"/></Fades>
<WarpMarkers><WarpMarker Id="0" SecTime="0" BeatTime="0"/><WarpMarker Id="1" SecTime="4" BeatTime="8"/></WarpMarkers>
<SampleRef><FileRef><Path Value="{wav}"/><RelativePath Value=""/></FileRef></SampleRef></AudioClip>"""


def track(clip_xml):
    return ET.fromstring("<AudioTrack><Name><EffectiveName Value='t'/></Name><DeviceChain><MainSequencer><Sample>"
                         "<ArrangerAutomation><Events>" + clip_xml + "</Events></ArrangerAutomation></Sample>"
                         "</MainSequencer></DeviceChain></AudioTrack>")


class Unroll(unittest.TestCase):
    def test_wrapping_loop_unrolls_and_plays_the_same(self):
        sr, spb = 22050, 0.5                                  # 120 BPM; source plays at its own speed (8 beats = 4 s)
        rng = np.random.default_rng(3)
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "s.wav"
            sf.write(str(wav), rng.standard_normal(5 * sr).astype(np.float32) * 0.1, sr, subtype="FLOAT")
            # plays 22 beats from the 3rd beat of a 8-beat loop region: passes of 6, 8, 8 beats
            t = track(CLIP.format(cs=4, ce=26, ls=0, le=8, rel=2, wav=wav))
            N = int(30 * spb * sr)
            before = render_track(t, Path(td) / "x.als", spb, N, sr, None, 0, [])
            lane, cl = U.looped_clips(t)
            new = U.unroll_clip(lane, cl[0], 120.0)
            self.assertEqual(len(new), 3)
            self.assertEqual(len({x.get("Id") for x in new}), 3)
            after = render_track(t, Path(td) / "x.als", spb, N, sr, None, 0, [])
            inner = slice(int(4 * spb * sr) + 200, int(26 * spb * sr) - 200)   # outer edges keep their own fades
            self.assertLess(float(np.abs(before[inner] - after[inner]).max()), 1e-6)

    def test_a_loop_that_never_wraps_becomes_one_copy(self):
        c = ET.fromstring(CLIP.format(cs=80, ce=96, ls=0, le=72, rel=16, wav="x"))
        self.assertEqual(U.passes(c, 120.0), [(80.0, 96.0, 16.0, 32.0)])


if __name__ == "__main__":
    unittest.main()
