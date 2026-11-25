"""Pointing comp clips at a processed take: only that track's clips, everything else on the clip kept."""
import tempfile, unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from hypnomix.session import sources as S


def song(take):
    clip = lambda i, a: (f'<AudioClip Id="{i}" Time="{a}"><CurrentStart Value="{a}"/><CurrentEnd Value="{a + 4}"/>'
                         f'<Disabled Value="false"/><SampleRef><FileRef><Path Value="{take}"/>'
                         f'<RelativePath Value="Samples/take.wav"/><OriginalFileSize Value="1"/>'
                         f'<OriginalCrc Value="5"/></FileRef><LastModDate Value="1"/></SampleRef>'
                         f'<Fades><FadeInLength Value="0.3"/></Fades></AudioClip>')
    trk = lambda i, n, cl: (f'<AudioTrack Id="{i}"><Name><EffectiveName Value="{n}"/></Name><DeviceChain><MainSequencer>'
                            f'<Sample><ArrangerAutomation><Events>{cl}</Events></ArrangerAutomation></Sample>'
                            f'</MainSequencer></DeviceChain></AudioTrack>')
    return ET.fromstring(f'<Ableton><LiveSet><Tracks>{trk(1, "Harmony 4", clip(0, 0) + clip(1, 8))}'
                         f'{trk(2, "Harmony 5", clip(0, 0))}</Tracks></LiveSet></Ableton>')


class Repoint(unittest.TestCase):
    def test_only_that_tracks_clips_play_the_new_take(self):
        with tempfile.TemporaryDirectory() as d:
            take = Path(d) / "Samples" / "take.wav"; take.parent.mkdir(); take.write_bytes(b"x" * 10)
            tuned = Path(d) / "Samples" / "Tuned" / "take (tuned).wav"; tuned.parent.mkdir(); tuned.write_bytes(b"y" * 20)
            root = song(take)
            srcs = S.track_sources(root, "Harmony 4", Path(d) / "song.als")
            self.assertEqual(list(srcs), [take.resolve()])
            self.assertEqual(S.repoint(srcs[take.resolve()], tuned, d), 2)
            h4, h5 = list(root.find(".//Tracks"))
            for c in h4.iter("AudioClip"):
                self.assertEqual(c.find("./SampleRef/FileRef/Path").get("Value"), str(tuned.resolve()))
                self.assertEqual(c.find("./SampleRef/FileRef/RelativePath").get("Value"), "Samples/Tuned/take (tuned).wav")
                self.assertEqual(c.find("./SampleRef/FileRef/OriginalFileSize").get("Value"), "20")
                self.assertEqual(c.find("./Fades/FadeInLength").get("Value"), "0.3")      # the comp edit stays
            self.assertEqual(next(h5.iter("AudioClip")).find("./SampleRef/FileRef/Path").get("Value"), str(take))


if __name__ == "__main__":
    unittest.main()
