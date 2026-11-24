"""Tempo tools: tempomap, loops, tighten, breathe, variations. Synthetic audio and a minimal Live-shaped set."""
import gzip, json, subprocess, sys, tempfile, unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 22050


def hx(*args):
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def drums(path, bars=16, bpm=100.0, wander=0.0, jitter=0.0, lead=0.0, seed=1, vary=False):
    """Kick on 1 and 3, snare on 2 and 4, hats on 8ths. Returns the bar-line times."""
    rng = np.random.default_rng(seed)
    t, ev, lines = lead, [], []
    for bar in range(bars):
        spb = 60.0 / (bpm * (1 + wander * np.sin(2 * np.pi * bar / 11)))
        lines.append(t)
        for b in range(4):
            for e in range(2):
                tt = t + e * spb / 2 + (rng.standard_normal() * jitter if (b or e) else 0.0)
                ev.append((tt, "h"))
                if e == 0:
                    ev.append((tt, "k" if b in (0, 2) else "s"))
                if vary and e == 1 and b in (1, 3):
                    ev.append((tt, "k"))
            t += spb
    lines.append(t)
    y = np.zeros(int((t + 1.0) * SR))
    for tt, k in ev:
        n = np.arange(int({"k": 0.2, "s": 0.15, "h": 0.04}[k] * SR)) / SR
        s = {"k": np.sin(2 * np.pi * (50 + 90 * np.exp(-n * 30)) * n) * np.exp(-n * 14),
             "s": rng.standard_normal(len(n)) * np.exp(-n * 25) * 0.6,
             "h": np.diff(rng.standard_normal(len(n)), prepend=0) * np.exp(-n * 90) * 0.2}[k]
        i = int(max(0, tt) * SR)
        y[i:i + len(s)] += s[: len(y) - i]
    sf.write(str(path), (y / np.abs(y).max() * 0.7).astype(np.float32), SR)
    return np.array(lines)


def clip_xml(cid, at, end, f0, f1, rel, warped, loop=False, tempo=100.0):
    k = tempo / 60.0
    a, b = (f0 * k, f1 * k) if warped else (f0, f1)
    return f'''<AudioClip Id="{cid}" Time="{at}"><CurrentStart Value="{at}"/><CurrentEnd Value="{end}"/>
 <Loop><LoopStart Value="{a}"/><LoopEnd Value="{b}"/><StartRelative Value="0"/><LoopOn Value="{str(loop).lower()}"/>
  <OutMarker Value="{b}"/><HiddenLoopStart Value="{a}"/><HiddenLoopEnd Value="{b}"/></Loop>
 <Name Value="take"/><Disabled Value="false"/><IsWarped Value="{str(warped).lower()}"/>
 <SampleRef><FileRef><RelativePath Value="{rel}"/><Path Value=""/><OriginalFileSize Value="0"/><OriginalCrc Value="0"/></FileRef>
  <LastModDate Value="0"/><DefaultDuration Value="0"/><DefaultSampleRate Value="{SR}"/></SampleRef>
 <WarpMode Value="0"/><Fades><FadeInLength Value="0"/><FadeOutLength Value="0"/></Fades><SampleVolume Value="1"/>
 <WarpMarkers><WarpMarker Id="0" SecTime="0" BeatTime="0"/><WarpMarker Id="1" SecTime="{0.03125 / k}" BeatTime="0.03125"/></WarpMarkers>
</AudioClip>'''


def make_set(path, clips, tempo=100.0, name="Drums"):
    slots = "".join(f'<ClipSlot Id="{i}"><ClipSlot><Value/></ClipSlot></ClipSlot>' for i in range(4))
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0_12049" Creator="Ableton Live 12.0"><LiveSet>
<NextPointeeId Value="100"/>
<Tracks><AudioTrack Id="7"><Name><EffectiveName Value="{name}"/><UserName Value="{name}"/></Name><TrackGroupId Value="-1"/>
 <AutomationEnvelopes><Envelopes/></AutomationEnvelopes>
 <DeviceChain><Mixer><Volume><Manual Value="1"/><AutomationTarget Id="10"/></Volume>
   <Pan><Manual Value="0"/><AutomationTarget Id="11"/></Pan>
   <Speaker><Manual Value="true"/><AutomationTarget Id="12"/></Speaker><Sends/></Mixer>
  <MainSequencer><ClipSlotList>{slots}</ClipSlotList>
   <Sample><ArrangerAutomation><Events>{"".join(clips)}</Events></ArrangerAutomation></Sample></MainSequencer>
  <DeviceChain><Devices/></DeviceChain></DeviceChain></AudioTrack></Tracks>
<MainTrack><Name><EffectiveName Value="Main"/></Name>
 <AutomationEnvelopes><Envelopes/></AutomationEnvelopes>
 <DeviceChain><Mixer><Volume><Manual Value="1"/><AutomationTarget Id="30"/></Volume>
   <Pan><Manual Value="0"/><AutomationTarget Id="31"/></Pan><Sends/>
   <Tempo><Manual Value="{tempo}"/><AutomationTarget Id="8"/></Tempo></Mixer><DeviceChain><Devices/></DeviceChain></DeviceChain>
</MainTrack></LiveSet></Ableton>'''
    with gzip.open(path, "wb") as f:
        f.write(xml.encode())
    return path


def root_of(p):
    return ET.fromstring(gzip.open(p).read())


class Maths(unittest.TestCase):
    def test_beat_seconds(self):
        from hypnomix.session import beats as B
        t = B.beat_seconds([(0, 120), (4, 120), (4, 60), (8, 60)], 100, [0, 4, 8, 12])
        np.testing.assert_allclose(t, [0, 2, 6, 10], atol=1e-9)
        ramp = B.beat_seconds([(0, 120), (4, 60)], 100, [4])[0]
        self.assertAlmostEqual(ramp, 4 * np.log(2), places=6)

    def test_warp_render_moves_hits(self):
        from hypnomix.session import beats as B
        y = np.zeros((SR * 4, 1), dtype=np.float32)
        for s in (1.0, 2.0, 3.0):
            y[int(s * SR): int(s * SR) + 200, 0] = np.hanning(200) * 0.8
        out = B.warp_render(y, SR, [(0, 0), (1.0, 1.0), (2.0, 2.2), (3.0, 3.2), (4.0, 4.2)])
        self.assertAlmostEqual(len(out) / SR, 4.2, delta=0.05)
        env = np.abs(out[:, 0])
        peak = (int(1.7 * SR) + int(np.argmax(env[int(1.7 * SR): int(2.7 * SR)]))) / SR
        self.assertAlmostEqual(peak, 2.2, delta=0.03)


class TempoMap(unittest.TestCase):
    def test_follows_a_wandering_take(self):
        from hypnomix.session import beats as B
        with tempfile.TemporaryDirectory() as td:
            lines = drums(Path(td) / "free.wav", bars=20, bpm=96, wander=0.05, lead=0.8)
            m = B.track(Path(td) / "free.wav")
            self.assertAlmostEqual(m["bpm"], 96, delta=4)
            self.assertGreater(m["wander_pct"], 3)
            err = [np.abs(m["bars"] - x).min() for x in lines[1:-2]]
            self.assertLess(np.median(err), 0.02)

    def test_conform_and_follow_write_sound_sets(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            lines = drums(td / "free.wav", bars=16, bpm=96, wander=0.04, lead=0.6)
            dur = sf.info(str(td / "free.wav")).duration
            s = make_set(td / "Song.als", [clip_xml(0, 0, dur * 100 / 60, 0, dur, "free.wav", False)])
            code, out = hx("tempomap", s, "--track", "Drums", "--conform", "--apply", td / "Song (conformed).als")
            self.assertEqual(code, 0, out)
            self.assertIn("structure OK", out)
            c = root_of(td / "Song (conformed).als").find(".//AudioClip")
            self.assertEqual(c.find("IsWarped").get("Value"), "true")
            self.assertGreaterEqual(len(c.find("WarpMarkers")), 12)
            self.assertEqual(float(c.find("CurrentStart").get("Value")) % 4, 0)
            code, out = hx("tempomap", s, "--track", "Drums", "--follow", "--apply", td / "Song (follow).als")
            self.assertEqual(code, 0, out)
            r = root_of(td / "Song (follow).als")
            ev = r.find(".//MainTrack/AutomationEnvelopes/Envelopes/AutomationEnvelope/Automation/Events")
            vals = [float(e.get("Value")) for e in ev]
            self.assertGreater(len(vals), 20)
            self.assertTrue(85 < min(vals) and max(vals) < 108, (min(vals), max(vals)))
            self.assertEqual(r.find(".//AudioClip/IsWarped").get("Value"), "false")
            code, out = hx("tempomap", s, "--track", "Drums", "--follow", "--apply", td / "Song (follow).als")
            self.assertNotEqual(code, 0)                     # never overwrites


class Loops(unittest.TestCase):
    def test_loops_into_session_slots(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            drums(td / "free.wav", bars=16, bpm=96, wander=0.02, lead=0.5)
            dur = sf.info(str(td / "free.wav")).duration
            s = make_set(td / "Song.als", [clip_xml(0, 0, dur * 100 / 60, 0, dur, "free.wav", False)])
            code, out = hx("loops", s, "--track", "Drums", "--out", td / "loops", "--top", "6", "--apply", td / "Song (loops).als")
            self.assertEqual(code, 0, out)
            self.assertTrue(list((td / "loops").glob("*.wav")))
            r = root_of(td / "Song (loops).als")
            placed = r.findall(".//ClipSlotList/ClipSlot/ClipSlot/Value/AudioClip")
            self.assertEqual(len(placed), 4)                 # only four empty slots
            for c in placed:
                self.assertEqual(c.find("Loop/LoopOn").get("Value"), "true")
                span = float(c.find("Loop/LoopEnd").get("Value")) - float(c.find("Loop/LoopStart").get("Value"))
                self.assertEqual(span % 4, 0)
            self.assertEqual(len(r.findall(".//ArrangerAutomation/Events/AudioClip")), 1)   # arrangement untouched


class Tighten(unittest.TestCase):
    def test_moves_hits_part_way(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            drums(td / "click.wav", bars=12, bpm=100, jitter=0.02)
            dur = sf.info(str(td / "click.wav")).duration
            s = make_set(td / "Song.als", [clip_xml(0, 0, 48, 0, 48 * 0.6, "click.wav", False)])
            code, out = hx("tighten", s, "--track", "Drums", "--grid", "8", "--apply", td / "Song (tighter).als")
            self.assertEqual(code, 0, out)
            self.assertIn("structure OK", out)
            import re
            m = re.search(r"median (\d+) ms → (\d+) ms", out)
            self.assertLess(int(m[2]), int(m[1]))
            self.assertGreater(len(root_of(td / "Song (tighter).als").find(".//AudioClip/WarpMarkers")), 20)
            code, out = hx("tighten", s, "--track", "Drums", "--strength", "1.0")
            self.assertNotEqual(code, 0)                     # a full snap is refused


class Breathe(unittest.TestCase):
    def test_sections_to_tempo_points(self):
        from hypnomix.session import breathe as Br, beats as B
        pts = Br.build_points([(32, 64, 2.0, "chorus")], 100.0, 96.0, 2.0, 0.0, 4)
        self.assertEqual(pts[0], (0.0, 100.0))
        self.assertIn((32.0, 102.0), pts)
        self.assertIn((30.0, 100.0), pts)
        self.assertLess(B.beat_seconds(pts, 100, [96])[0], 96 * 0.6)

    def test_unwarped_clips_block_the_write(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            drums(td / "click.wav", bars=12, bpm=100)
            s = make_set(td / "Song.als", [clip_xml(0, 0, 48, 0, 48 * 0.6, "click.wav", False)])
            code, out = hx("breathe", s, "--sections", "5-8:+2", "--apply", td / "Song (b).als")
            self.assertNotEqual(code, 0)
            self.assertIn("NOT warped", out)
            self.assertFalse((td / "Song (b).als").exists())
            code, out = hx("breathe", s, "--sections", "5-8:+2", "--warp-clips", "--apply", td / "Song (b).als")
            self.assertEqual(code, 0, out)
            r = root_of(td / "Song (b).als")
            c = r.find(".//AudioClip")
            self.assertEqual(c.find("IsWarped").get("Value"), "true")
            self.assertAlmostEqual(float(c.find("Loop/LoopEnd").get("Value")), 48.0, places=4)   # seconds became beats
            self.assertGreater(len(r.findall(".//MainTrack//FloatEvent")), 3)


class Variations(unittest.TestCase):
    def test_spare_take_goes_on_a_new_track_switched_off(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            rec = td / "Samples" / "Recorded"
            rec.mkdir(parents=True)
            drums(rec / "1-Drums 0001 [2026-01-01 000000].wav", bars=2, bpm=100, seed=1)
            drums(rec / "1-Drums 0002 [2026-01-01 000100].wav", bars=12, bpm=100, seed=2, vary=True)
            rel = "Samples/Recorded/1-Drums 0001 [2026-01-01 000000].wav"
            clips = [clip_xml(i, i * 8, i * 8 + 8, 0, 4.8, rel, False) for i in range(8)]
            s = make_set(td / "Song.als", clips)
            code, out = hx("variations", s, "--out", td / "v", "--apply", td / "Song (variations).als")
            self.assertEqual(code, 0, out)
            self.assertIn("structure OK", out)
            j = json.loads((td / "v" / "variations.json").read_text())
            self.assertEqual(len(j["findings"]), 2)          # every 4th of 8 repeats
            self.assertTrue(list((td / "v").glob("* B (unused take).wav")))
            r = root_of(td / "Song (variations).als")
            tr = list(r.find(".//Tracks"))
            self.assertEqual([t.find("Name/EffectiveName").get("Value") for t in tr], ["Drums", "Drums (variation)"])
            new = tr[1]
            self.assertEqual(new.find("DeviceChain/Mixer/Speaker/Manual").get("Value"), "false")
            self.assertEqual(tr[0].find("DeviceChain/Mixer/Speaker/Manual").get("Value"), "true")
            got = new.findall(".//ArrangerAutomation/Events/AudioClip")
            self.assertEqual([float(c.get("Time")) for c in got], [24.0, 56.0])
            self.assertIn("0002", got[0].find("SampleRef/FileRef/RelativePath").get("Value"))
            ids = [e.get("Id") for e in r.iter() if e.tag.endswith("Target")]
            self.assertEqual(len(ids), len(set(ids)))        # fresh ids on the copy
            self.assertEqual(len(tr[0].findall(".//ArrangerAutomation/Events/AudioClip")), 8)


if __name__ == "__main__":
    unittest.main()
