"""colour: where a part repeats itself, the chains proposed there, and the sets written from them. Synthetic audio, a
minimal Live-shaped set, and a tiny stand-in for Live's preset library."""
import gzip, json, subprocess, sys, tempfile, unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix.session import colour as C

SR = 22050
TEMPO = 160.0                       # a 1.5 s bar
BAR = 4 * 60.0 / TEMPO
BARS = 32                           # A B A B, eight bars each


def hx(*args):
    r = subprocess.run([sys.executable, "-m", "hypnomix.cli", *map(str, args)], capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout + r.stderr


def seconds(n):
    return np.arange(int(n * SR)) / SR


def pad(rng):
    t = seconds(BARS * BAR)
    y = sum(np.sin(2 * np.pi * f * t) for f in (220.0, 277.2, 329.6)) * 0.12
    return y * (0.9 + 0.1 * np.sin(2 * np.pi * 0.2 * t))


def bass():
    t = seconds(BARS * BAR)
    beat = (t % (BAR / 4)) / (BAR / 4)
    return np.sin(2 * np.pi * 55 * t) * np.exp(-3 * beat) * 0.5


def lead(rng):
    """Section A: a soft sine melody (2 notes a bar). Section B: bright, busy and noisy."""
    t = seconds(BARS * BAR)
    y = np.zeros_like(t)
    for sec in range(4):
        a, b = int(sec * 8 * BAR * SR), int((sec + 1) * 8 * BAR * SR)
        tt = t[a:b]
        if sec % 2 == 0:
            note = (tt % (BAR / 2)) / (BAR / 2)
            y[a:b] = np.sin(2 * np.pi * 440 * tt) * np.exp(-2 * note) * 0.3
        else:
            note = (tt % (BAR / 8)) / (BAR / 8)
            y[a:b] = (np.sign(np.sin(2 * np.pi * 1760 * tt)) * 0.15 + rng.standard_normal(len(tt)) * 0.05) * np.exp(-4 * note)
    return y


def drums(rng):
    t = seconds(BARS * BAR)
    y = np.zeros_like(t)
    for sec in (1, 3):
        a, b = int(sec * 8 * BAR * SR), int((sec + 1) * 8 * BAR * SR)
        step = (t[a:b] % (BAR / 8)) / (BAR / 8)
        y[a:b] = rng.standard_normal(b - a) * np.exp(-12 * step) * 0.4
    return y


def clip_xml(rel, end):
    return f'''<AudioClip Id="0" Time="0"><CurrentStart Value="0"/><CurrentEnd Value="{end}"/>
 <Loop><LoopStart Value="0"/><LoopEnd Value="{end * 60 / TEMPO}"/><StartRelative Value="0"/><LoopOn Value="false"/>
  <OutMarker Value="{end * 60 / TEMPO}"/><HiddenLoopStart Value="0"/><HiddenLoopEnd Value="{end * 60 / TEMPO}"/></Loop>
 <Name Value="take"/><Disabled Value="false"/><IsWarped Value="false"/>
 <SampleRef><FileRef><RelativePath Value="{rel}"/><Path Value=""/><OriginalFileSize Value="0"/><OriginalCrc Value="0"/></FileRef>
  <LastModDate Value="0"/><DefaultDuration Value="0"/><DefaultSampleRate Value="{SR}"/></SampleRef>
 <WarpMode Value="0"/><Fades><FadeInLength Value="0"/><FadeOutLength Value="0"/></Fades><SampleVolume Value="1"/>
 <WarpMarkers><WarpMarker Id="0" SecTime="0" BeatTime="0"/><WarpMarker Id="1" SecTime="0.01875" BeatTime="0.03125"/></WarpMarkers>
</AudioClip>'''


def make_song(td, names=("Pad", "Bass", "Lead", "Drums")):
    td = Path(td)
    rng = np.random.default_rng(3)
    audio = dict(Pad=pad(rng), Bass=bass(), Lead=lead(rng), Drums=drums(rng))
    end = BARS * 4
    tracks = ""
    for i, n in enumerate(names):
        sf.write(str(td / f"{n}.wav"), audio[n].astype(np.float32), SR)
        slots = "".join(f'<ClipSlot Id="{k}"><ClipSlot><Value/></ClipSlot></ClipSlot>' for k in range(2))
        b = 100 + i * 20
        tracks += f'''<AudioTrack Id="{i + 1}"><Name><EffectiveName Value="{n}"/><UserName Value="{n}"/></Name><TrackGroupId Value="-1"/>
 <AutomationEnvelopes><Envelopes/></AutomationEnvelopes>
 <DeviceChain><Mixer><Volume><Manual Value="1"/><AutomationTarget Id="{b}"/></Volume>
   <Pan><Manual Value="0"/><AutomationTarget Id="{b + 1}"/></Pan>
   <Speaker><Manual Value="true"/><AutomationTarget Id="{b + 2}"/></Speaker><Sends/></Mixer>
  <MainSequencer><ClipSlotList>{slots}</ClipSlotList>
   <Sample><ArrangerAutomation><Events>{clip_xml(f"{n}.wav", end)}</Events></ArrangerAutomation></Sample></MainSequencer>
  <DeviceChain><Devices/></DeviceChain></DeviceChain></AudioTrack>'''
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0_12049" Creator="Ableton Live 12.0"><LiveSet>
<NextPointeeId Value="1000"/>
<Tracks>{tracks}</Tracks>
<MainTrack><Name><EffectiveName Value="Main"/></Name>
 <AutomationEnvelopes><Envelopes/></AutomationEnvelopes>
 <DeviceChain><Mixer><Volume><Manual Value="1"/><AutomationTarget Id="30"/></Volume>
   <Pan><Manual Value="0"/><AutomationTarget Id="31"/></Pan><Sends/>
   <Tempo><Manual Value="{TEMPO}"/><AutomationTarget Id="8"/></Tempo></Mixer><DeviceChain><Devices/></DeviceChain></DeviceChain>
</MainTrack></LiveSet></Ableton>'''
    p = td / "Song.als"
    with gzip.open(p, "wb") as f:
        f.write(xml.encode())
    return p


def make_library(td, skip=()):
    """A stand-in for 'Core Library/Devices/Audio Effects' holding the presets the recipes ask for."""
    lib = Path(td) / "Core Library/Devices/Audio Effects"
    seen = set()
    for fam in C.FAMILIES:
        for role, tr in (("tonal", dict(centroid=900, density=1.0)), ("busy", dict(centroid=3000, density=6.0))):
            for st in C.recipe(fam, tr, role, 0.5):
                if st["preset"] in seen or st["tag"] in skip:
                    continue
                seen.add(st["preset"])
                body = "".join(f'<{k}><LomId Value="0"/><Manual Value="0"/><AutomationTarget Id="0"/></{k}>' for k in st["set"])
                xml = (f'<Ableton><{st["tag"]}><LomId Value="0"/><On><LomId Value="0"/><Manual Value="false"/>'
                       f'<AutomationTarget Id="0"/></On><Pointee Id="0"/><LastPresetRef><Value><FilePresetRef Id="0"/></Value></LastPresetRef>'
                       f'<UserName Value="preset"/>{body}</{st["tag"]}></Ableton>')
                f = lib / (st["preset"] + ".adv")
                f.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(f, "wb") as fh:
                    fh.write(xml.encode())
    return Path(td) / "Core Library"


def root_of(p):
    return ET.fromstring(gzip.open(p).read())


def tracks_of(root):
    return [t.find("./Name/EffectiveName").get("Value") for t in root.find(".//Tracks")]


class Measuring(unittest.TestCase):
    def test_change_separates_tone_and_texture(self):
        a = dict(bands=[-10, -10, -10, -10, -10, -10], density=2.0)
        same = C.change(a, dict(a))
        self.assertEqual((same["tone"], same["texture"], same["total"]), (0.0, 0.0, 0.0))
        d = C.change(a, dict(bands=[-12, -10, -10, -10, -10, -8], density=4.0))
        self.assertAlmostEqual(d["tone"], 4 / 6, places=2)
        self.assertAlmostEqual(d["texture"], np.log2(4.25 / 2.25), places=2)
        self.assertAlmostEqual(d["total"], d["tone"] + 3 * d["texture"], places=1)

    def test_sections_fixed_blocks(self):
        secs, how = C.sections_of(np.zeros(10), 20, 0.5, block=8)
        self.assertEqual([(a, b) for a, b, _ in secs], [(0, 8), (8, 16), (16, 20)])
        self.assertIn("fixed", how)

    def test_family_never_width_for_bass_or_octave_for_drums(self):
        tr = dict(centroid=120, density=2.0)
        fam, role = C.pick_family("Bass", tr, list(C.FAMILIES), set())
        self.assertEqual(role, "bass")
        self.assertNotEqual(fam, "width")
        self.assertIsNone(C.pick_family("Bass", tr, ["width"], set())[0])
        self.assertIsNone(C.pick_family("Drums", dict(centroid=2000, density=6), ["octave"], set())[0])

    def test_each_family_has_a_chain_and_a_preview(self):
        y = np.sin(2 * np.pi * 220 * np.arange(SR * 2) / SR).astype(np.float32) * 0.3
        tr = dict(centroid=900, density=1.0)
        for fam in C.FAMILIES:
            steps = C.recipe(fam, tr, "tonal", 0.5)
            self.assertTrue(steps)
            out = C.preview_model(y, fam, steps, tr)
            self.assertEqual(out.shape[1], 2, fam)
            self.assertTrue(np.isfinite(out).all(), fam)
            self.assertGreater(float(np.abs(out).max()), 0.01, fam)
            self.assertGreater(float(np.max(np.abs(out[:, 0] - y[: len(out)]))), 1e-3, fam)   # B differs from A

    def test_amount_scales_the_wet_level(self):
        tr = dict(centroid=900, density=1.0)
        lo, hi = (C.recipe("grit", tr, "tonal", x)[0]["set"]["DryWet"] for x in (0.1, 0.9))
        self.assertLess(lo, hi)


class Song(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.td.name)
        cls.set = make_song(cls.dir)
        cls.lib = make_library(cls.dir)
        cls.home = cls.dir / "home"
        cls.home.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def run_colour(self, *args):
        return hx("colour", self.set, "--library", self.lib, "--out", self.dir / "report", *args)

    def test_report_finds_the_part_that_never_changes(self):
        code, out = self.run_colour("--block", "8", "--no-clips", "--json", self.dir / "r.json")
        self.assertEqual(code, 0, out)
        doc = json.loads((self.dir / "r.json").read_text(encoding="utf-8"))
        pad_ = doc["parts"]["Pad"]
        self.assertTrue(pad_["static"], doc["parts"])
        self.assertLess(pad_["mean_change"], doc["parts"]["Lead"]["mean_change"])
        self.assertIn("sounds the same throughout", out)
        self.assertTrue((self.dir / "report" / "COLOUR.md").exists())
        for f in doc["findings"]:
            self.assertEqual((f["tool"], f["applies"], f["severity"]), ("colour", "set", "info"))
            self.assertRegex(f["where"], r"^bars \d+-\d+$")
            self.assertIn("measured", f["problem"])

    def test_options_choose_part_family_and_count(self):
        code, out = self.run_colour("--block", "8", "--no-clips", "--part", "Pad", "--family", "grit", "--max", "2",
                                    "--per-part", "2", "--json", self.dir / "r2.json")
        self.assertEqual(code, 0, out)
        fs = json.loads((self.dir / "r2.json").read_text(encoding="utf-8"))["findings"]
        self.assertEqual(len(fs), 2)
        self.assertEqual({f["track"] for f in fs}, {"Pad"})
        self.assertEqual({f["kind"] for f in fs}, {"colour-grit"})
        code, out = self.run_colour("--block", "8", "--no-clips", "--max", "1", "--json", self.dir / "r3.json")
        self.assertEqual(len(json.loads((self.dir / "r3.json").read_text(encoding="utf-8"))["findings"]), 1)

    def test_the_first_time_through_is_never_proposed(self):
        self.run_colour("--block", "8", "--no-clips", "--per-part", "3", "--max", "9", "--json", self.dir / "r4.json")
        for f in json.loads((self.dir / "r4.json").read_text(encoding="utf-8"))["findings"]:
            self.assertGreater(int(f["where"].split()[1].split("-")[0]), 1, f)

    def test_before_after_clips_are_level_matched_and_differ(self):
        code, out = self.run_colour("--block", "8", "--part", "Pad", "--max", "1", "--json", self.dir / "r5.json")
        self.assertEqual(code, 0, out)
        ab = json.loads((self.dir / "r5.json").read_text(encoding="utf-8"))["ab"]["colour-1"]
        a, sr = sf.read(str(self.dir / "report" / "clips" / ab["a"]))
        b, _ = sf.read(str(self.dir / "report" / "clips" / ab["b"]))
        self.assertAlmostEqual(len(a) / sr, 6.0, delta=0.1)           # four bars of 1.5 s
        self.assertLessEqual(abs(ab["matched_db"]), 3.0)
        self.assertGreater(float(np.max(np.abs(a - b))), 1e-3)

    def test_nothing_is_written_without_apply(self):
        before, files = self.set.read_bytes(), sorted(p.name for p in self.dir.glob("*.als"))
        self.run_colour("--block", "8", "--no-clips")
        self.assertEqual(self.set.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.dir.glob("*.als")), files)

    def test_apply_writes_a_switched_off_track_beside_its_parent(self):
        out = self.dir / "Song (colour).als"
        code, txt = self.run_colour("--block", "8", "--no-clips", "--part", "Pad", "--family", "grit", "--max", "1",
                                    "--apply", out, "--ids", "colour-1")
        self.assertEqual(code, 0, txt)
        self.assertIn("structure OK", txt)
        names = tracks_of(root_of(out))
        i = names.index("Pad")
        self.assertTrue(names[i + 1].startswith("Pad (colour: grit"), names)
        self.assertEqual(len(names), 5)
        r = root_of(out)
        new = list(r.find(".//Tracks"))[i + 1]
        self.assertEqual(new.find("./DeviceChain/Mixer/Speaker/Manual").get("Value"), "false")
        dev = new.find("./DeviceChain/DeviceChain/Devices/Saturator")
        self.assertIsNotNone(dev)
        self.assertEqual(dev.find("./UserName").get("Value"), "colour: grit")
        self.assertEqual(dev.find("./On/Manual").get("Value"), "true")
        self.assertGreater(float(dev.find("./PreDrive/Manual").get("Value")), 4.0)
        clips = new.findall("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events/AudioClip")
        self.assertEqual(len(clips), 1)
        start, end = (float(clips[0].find(f"./{x}").get("Value")) for x in ("CurrentStart", "CurrentEnd"))
        self.assertEqual((end - start) % 4, 0)                          # whole bars
        self.assertEqual(start % 4, 0)
        ids = [e.get("Id") for e in r.iter() if e.tag in ("AutomationTarget", "ModulationTarget", "Pointee") and e.get("Id")]
        dup = {x for x in ids if ids.count(x) > 1 and x != "0"}
        self.assertFalse(dup, dup)
        orig = root_of(self.set)
        self.assertEqual(len(orig.find(".//Tracks")), 4)                # the original set is untouched
        code, txt = hx("check", out)
        self.assertEqual(code, 0, txt)

    def test_apply_needs_ids_and_refuses_to_overwrite(self):
        out = self.dir / "Song (nope).als"
        code, txt = self.run_colour("--block", "8", "--no-clips", "--apply", out)
        self.assertNotEqual(code, 0)
        self.assertIn("--ids", txt)
        self.assertFalse(out.exists())
        code, txt = self.run_colour("--block", "8", "--no-clips", "--apply", self.set, "--ids", "colour-1")
        self.assertNotEqual(code, 0)
        self.assertIn("overwrite", txt)

    def test_two_families_make_two_chains(self):
        out = self.dir / "Song (two).als"
        code, txt = self.run_colour("--block", "8", "--no-clips", "--part", "Pad", "--family", "width", "--max", "1",
                                    "--apply", out, "--ids", "colour-1")
        self.assertEqual(code, 0, txt)
        r = root_of(out)
        new = [t for t in r.find(".//Tracks") if "colour" in t.find("./Name/EffectiveName").get("Value")][0]
        tags = [d.tag for d in new.find("./DeviceChain/DeviceChain/Devices")]
        self.assertEqual(tags, ["Chorus2", "StereoGain"])
        self.assertEqual([d.get("Id") for d in new.find("./DeviceChain/DeviceChain/Devices")], ["0", "1"])

    def test_without_live_library_it_says_so_and_writes_nothing(self):
        out = self.dir / "Song (nolib).als"
        empty = self.dir / "empty"
        empty.mkdir()
        code, txt = hx("colour", self.set, "--library", empty, "--out", self.dir / "report2", "--block", "8", "--no-clips",
                       "--part", "Pad", "--family", "grit", "--max", "1", "--apply", out, "--ids", "colour-1")
        self.assertNotEqual(code, 0)
        self.assertFalse(out.exists())
        self.assertIn("not found", txt)

    def test_plan_makes_findings_for_the_review(self):
        sd = self.dir / "scan-colour"
        code, txt = self.run_colour("--block", "8", "--part", "Pad", "--max", "2", "--per-part", "2", "--plan", sd)
        self.assertEqual(code, 0, txt)
        data = json.loads((sd / "findings.json").read_text(encoding="utf-8"))
        self.assertEqual({f["tool"] for f in data["findings"]}, {"colour"})
        self.assertEqual(len(data["findings"]), 2)
        scan = json.loads((sd / "scan.json").read_text(encoding="utf-8"))
        self.assertIn("--block", scan["colour_args"])
        self.assertTrue((sd / "ab" / "ab.json").exists())
        self.assertTrue(list((sd / "ab").glob("colour-1 A*.wav")))

    def test_fix_applies_only_the_approved_proposal(self):
        sd = self.dir / "scan-fix"
        code, txt = self.run_colour("--block", "8", "--no-clips", "--part", "Pad", "--family", "grit", "--max", "2",
                                    "--per-part", "2", "--plan", sd)
        self.assertEqual(code, 0, txt)
        hx("fix", sd, "--decide", "colour-1=skip")
        code, txt = hx("fix", sd, "--decide", "colour-2=approve", "--note", "amount=0.9")
        self.assertEqual(code, 0, txt)
        out = self.dir / "Song (fixed colour).als"
        code, txt = hx("fix", sd, "--approved", "--out", out)
        self.assertEqual(code, 0, txt)
        names = tracks_of(root_of(out))
        self.assertEqual(len([n for n in names if "colour" in n]), 1, names)
        self.assertIn("structure OK", txt)
        dev = next(root_of(out).iter("Saturator"))
        self.assertAlmostEqual(float(dev.find("./PreDrive/Manual").get("Value")), 13.0, places=1)   # amount 0.9, not 0.5

    def test_installed_free_plugins_are_named_never_invented(self):
        prefs = self.dir / "prefs.json"
        prefs.write_text(json.dumps({"tools": {"plugins": ["DragonflyHallReverb"]}}), encoding="utf-8")
        self.run_colour("--block", "8", "--no-clips", "--part", "Pad", "--family", "space", "--max", "1",
                        "--prefs-file", prefs, "--json", self.dir / "r6.json")
        fix = json.loads((self.dir / "r6.json").read_text(encoding="utf-8"))["findings"][0]["fix"]
        self.assertIn("DragonflyHallReverb", fix)
        self.run_colour("--block", "8", "--no-clips", "--part", "Pad", "--family", "space", "--max", "1",
                        "--prefs-file", self.dir / "nothing.json", "--json", self.dir / "r7.json")
        fix = json.loads((self.dir / "r7.json").read_text(encoding="utf-8"))["findings"][0]["fix"]
        self.assertNotIn("Dragonfly", fix)
        self.assertNotIn("plug-ins you have", fix)

    def test_rpp_is_refused_politely(self):
        p = self.dir / "x.rpp"
        p.write_text("", encoding="utf-8")
        code, txt = hx("colour", p)
        self.assertNotEqual(code, 0)
        self.assertIn("REAPER", txt)

    def test_auto_sections_run(self):
        code, out = self.run_colour("--no-clips", "--json", self.dir / "r8.json")
        self.assertEqual(code, 0, out)
        self.assertGreaterEqual(len(json.loads((self.dir / "r8.json").read_text(encoding="utf-8"))["sections"]), 2)


if __name__ == "__main__":
    unittest.main()
