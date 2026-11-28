import gzip, tempfile, unittest, io, contextlib
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import soundfile as sf

from hypnomix.session import loopset as LS

SR = 44100
BPM = 120.0
BAR = 4 * 60.0 / BPM          # 2 s
NB = 16


def hit(n, at, freq, rng, dur=0.08, amp=0.7):
    y = np.zeros(n)
    k = int(dur * SR)
    t = np.arange(k) / SR
    y[at:at + k] += amp * np.exp(-t * 50) * (np.sin(2 * np.pi * freq * t) + 0.4 * rng.standard_normal(k))
    return y


def drums(varied_from=8):
    """Bars 1-8: the same kick/snare/hat bar. Bars 9-16: a different random pattern each bar."""
    n = int(NB * BAR * SR) + SR // 2
    y = np.zeros(n)
    rng = np.random.default_rng(3)
    step = BAR / 16
    for bar in range(NB):
        r = np.random.default_rng(100 + bar)
        for s in range(16):
            at = int((bar * BAR + s * step) * SR)
            if bar < varied_from:
                if s in (0, 8):
                    y += hit(n, at, 60, rng, amp=0.9)
                if s in (4, 12):
                    y += hit(n, at, 220, rng)
                if s % 2 == 0:
                    y += hit(n, at, 5000, rng, dur=0.02, amp=0.3)
            else:
                if r.random() < 0.5:
                    y += hit(n, at, float(r.choice([60, 90, 220, 400, 3000])), rng, amp=0.5 + 0.4 * r.random())
    return y


def stems_dir(d):
    d = Path(d)
    n = int(NB * BAR * SR) + SR // 2
    t = np.arange(n) / SR
    pad = 0.15 * (np.sin(2 * np.pi * 220 * t) + np.sin(2 * np.pi * 330 * t))
    sf.write(d / "Drums.wav", np.stack([drums()] * 2, 1), SR, subtype="PCM_24")
    sf.write(d / "Pad.wav", np.stack([pad, pad], 1), SR, subtype="PCM_24")
    sf.write(d / "Silent.wav", np.zeros((n, 2)), SR, subtype="PCM_24")
    return d


def make_set(path, wav):
    slots = "".join(f'<ClipSlot Id="{i}"><LomId Value="0"/><ClipSlot><Value/></ClipSlot></ClipSlot>' for i in range(12))
    clip = ('<AudioClip Id="1" Time="0"><LomId Value="0"/><CurrentStart Value="0"/><CurrentEnd Value="4"/>'
            '<Loop><LoopStart Value="0"/><LoopEnd Value="4"/><StartRelative Value="0"/><LoopOn Value="false"/>'
            '<OutMarker Value="4"/><HiddenLoopStart Value="0"/><HiddenLoopEnd Value="4"/></Loop>'
            '<Name Value="take"/><Disabled Value="false"/><IsWarped Value="false"/><WarpMode Value="0"/>'
            '<SampleVolume Value="1"/><WarpMarkers><WarpMarker Id="0" SecTime="0" BeatTime="0"/></WarpMarkers>'
            '<Fades><FadeInLength Value="0"/><FadeOutLength Value="0"/></Fades>'
            f'<SampleRef><FileRef><Path Value="{wav}"/><RelativePath Value="{wav.name}"/><OriginalFileSize Value="1"/>'
            '<OriginalCrc Value="0"/></FileRef><LastModDate Value="0"/><DefaultDuration Value="1"/>'
            '<DefaultSampleRate Value="44100"/></SampleRef></AudioClip>')

    def track(tid, name, base, with_clip):
        return (f'<AudioTrack Id="{tid}"><Name><EffectiveName Value="{name}"/><UserName Value="{name}"/></Name>'
                f'<TrackGroupId Value="-1"/><AutomationEnvelopes><Envelopes/></AutomationEnvelopes><DeviceChain>'
                f'<AudioOutputRouting><Target Value="AudioOut/Main"/></AudioOutputRouting>'
                f'<Mixer><Volume><Manual Value="1"/><AutomationTarget Id="{base}"/></Volume>'
                f'<Pan><Manual Value="0"/><AutomationTarget Id="{base + 1}"/></Pan>'
                f'<Speaker><Manual Value="true"/><AutomationTarget Id="{base + 2}"/></Speaker><Sends/></Mixer>'
                f'<MainSequencer><Sample><ArrangerAutomation><Events>{clip if with_clip else ""}</Events></ArrangerAutomation></Sample>'
                f'<ClipSlotList>{slots}</ClipSlotList></MainSequencer>'
                f'<DeviceChain><Devices/></DeviceChain></DeviceChain></AudioTrack>')
    xml = ('<?xml version="1.0" encoding="UTF-8"?><Ableton MajorVersion="5" MinorVersion="12.0_12000" Creator="Ableton Live 12.0">'
           f'<LiveSet><NextPointeeId Value="1000"/><Tracks>{track(10, "Drums", 100, True)}{track(11, "Bass", 120, True)}</Tracks>'
           f'<MainTrack><Name><EffectiveName Value="Main"/></Name><AutomationEnvelopes><Envelopes/></AutomationEnvelopes><DeviceChain>'
           f'<Mixer><Volume><Manual Value="1"/><AutomationTarget Id="900"/></Volume><Pan><Manual Value="0"/><AutomationTarget Id="901"/></Pan>'
           f'<Speaker><Manual Value="true"/><AutomationTarget Id="902"/></Speaker><Sends/>'
           f'<Tempo><Manual Value="{BPM}"/><AutomationTarget Id="903"/></Tempo></Mixer>'
           f'<DeviceChain><Devices/></DeviceChain></DeviceChain></MainTrack></LiveSet></Ableton>')
    with gzip.open(path, "wb") as f:
        f.write(xml.encode())


class LoopSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        d = Path(cls.td.name)
        (d / "stems").mkdir()
        stems_dir(d / "stems")
        cls.stems = d / "stems"
        with contextlib.redirect_stdout(io.StringIO()):
            cls.res, cls.out = LS.run(cls.stems, bpm=BPM, downbeat=0.0, bars=(4,), top=2, variations=4,
                                      out=d / "out", seed=7, log=lambda *a: None)
        cls.d = d

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_picks_on_bar_lines_and_clean_section_first(self):
        picks = self.res["picks"]
        self.assertEqual(len(picks), 2)
        for c in picks:
            self.assertEqual((c["bar"] - 1) % 1, 0)
            self.assertLess(abs(c["start_s"] - (c["bar"] - 1) * BAR), 0.045)
            self.assertLess(abs(c["length_ms"] / 1000 - c["bars"] * BAR), 0.05)
        self.assertEqual(picks[0]["rank"], 1)
        self.assertLessEqual(picks[0]["bar"] + picks[0]["bars"] - 1, 8)       # the clean repeated bars
        self.assertGreaterEqual(picks[0]["score"], picks[1]["score"])
        a, b = picks
        self.assertTrue(a["bar"] + a["bars"] <= b["bar"] or b["bar"] + b["bars"] <= a["bar"])

    def test_stems_share_bounds_and_silent_stem_is_cut(self):
        for c in self.res["picks"]:
            lens = {k: sf.info(f).frames for k, f in c["files"].items()}
            self.assertEqual(set(lens), {"Drums", "Pad", "Silent"})
            self.assertEqual(len(set(lens.values())), 1)
            self.assertEqual(c["offsets_ms"].keys(), {"Drums", "Pad"})          # silent stem not reported

    def test_output_files(self):
        self.assertTrue((self.out / "LOOPSET.md").is_file())
        self.assertTrue((self.out / "loopset.json").is_file())
        c = self.res["picks"][0]
        self.assertTrue((self.out / c["folder"] / "Drums.wav").is_file())
        self.assertEqual(len(c["variations"]), 4)
        self.assertEqual([v["kind"] for v in c["variations"]], ["slices", "fill", "slices", "fill"])
        for v in c["variations"]:
            self.assertTrue(Path(v["file"]).is_file())
            self.assertEqual(sf.info(v["file"]).frames, sf.info(c["files"]["Drums"]).frames)
        import json
        j = json.loads((self.out / "loopset.json").read_text())
        self.assertEqual(j["bpm"], BPM)
        self.assertEqual(len(j["picks"]), 2)

    def test_mutate_deterministic_and_first_slice_untouched(self):
        rng = np.random.default_rng(0)
        y = rng.standard_normal((SR * 4, 2)).astype(np.float32)
        for cx in ("subtle", "normal", "complex"):
            a, ops = LS.mutate(y, SR, 2, 5, cx)
            b, ops2 = LS.mutate(y, SR, 2, 5, cx)
            self.assertTrue(np.array_equal(a, b))
            self.assertEqual(ops, ops2)
            lo, hi = LS.CHANGES[cx]
            self.assertTrue(lo <= len(ops) <= hi * 2)
            first = int(round(len(y) / 32))
            self.assertTrue(np.array_equal(a[:first], y[:first]))
            self.assertFalse(np.array_equal(a, y))
            self.assertTrue(all(o["slice"] != 0 for o in ops))
            c, _ = LS.mutate(y, SR, 2, 6, cx)
            self.assertFalse(np.array_equal(a, c))

    def test_fill_variant_leaves_start_alone(self):
        c = self.res["picks"][0]
        y0, _ = sf.read(c["files"]["Drums"], always_2d=True, dtype="float32")
        fv = [v for v in c["variations"] if v["kind"] == "fill"][0]
        y1, _ = sf.read(fv["file"], always_2d=True, dtype="float32")
        half = len(y0) // 2
        self.assertLess(float(np.abs(y0[:half] - y1[:half]).max()), 1e-4)

    def test_apply_writes_set(self):
        d = self.d
        wav = self.out / self.res["picks"][0]["folder"] / "Drums.wav"
        src = d / "Song.als"
        make_set(src, wav)
        before = src.read_bytes()
        dst = d / "Song (loopset).als"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            LS.main([str(self.stems), "--bpm", str(BPM), "--downbeat", "0", "--bars", "4", "--top", "2",
                     "--out", str(d / "out2"), "--set", str(src), "--apply", str(dst)])
        self.assertEqual(src.read_bytes(), before)
        root = ET.fromstring(gzip.open(dst).read())
        names = [t.find("./Name/EffectiveName").get("Value") for t in root.find(".//Tracks")]
        self.assertIn("Drums loops", names)
        self.assertEqual(names.index("Drums loops"), names.index("Drums") + 1)
        self.assertNotIn("Pad loops", names)              # no track named Pad: skipped with a note
        self.assertIn("no audio track of that name", buf.getvalue())
        tr = [t for t in root.find(".//Tracks") if t.find("./Name/EffectiveName").get("Value") == "Drums loops"][0]
        clips = tr.findall("./DeviceChain/MainSequencer/ClipSlotList/ClipSlot/ClipSlot/Value/AudioClip")
        self.assertEqual(len(clips), 2 + 2 * 4)             # two picks, four variations each on the anchor
        self.assertEqual(clips[0].find("./Name").get("Value").split()[0], "Loop")
        self.assertEqual(clips[0].find("./Loop/LoopOn").get("Value"), "true")
        self.assertEqual(clips[0].find("./IsWarped").get("Value"), "true")
        self.assertEqual(clips[0].find("./CurrentEnd").get("Value"), "16.0")
        with self.assertRaises(SystemExit):                 # never overwrites
            LS.main([str(self.stems), "--set", str(src), "--apply", str(dst)])


if __name__ == "__main__":
    unittest.main()
