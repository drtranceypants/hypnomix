"""als2ardour: a Live set becomes a new Ardour session that the Ardour reader reads back and renders the same."""
import gzip
import math
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 48000
BPM = 120.0
SPB = 60.0 / BPM


def _mixer(base, vol=1.0, pan=0.0, on=True, sends=()):
    s = "".join(f'<TrackSendHolder Id="{i}"><Send><Manual Value="{v}"/><AutomationTarget Id="{base + 10 + i}"/></Send>'
                f'<EnabledByUser Value="true"/></TrackSendHolder>' for i, v in enumerate(sends))
    return (f'<Mixer><Volume><Manual Value="{vol}"/><AutomationTarget Id="{base}"/><ModulationTarget Id="{base + 5}"/>'
            f'</Volume><Pan><Manual Value="{pan}"/><AutomationTarget Id="{base + 1}"/></Pan>'
            f'<Speaker><Manual Value="{"true" if on else "false"}"/><AutomationTarget Id="{base + 2}"/></Speaker>'
            f'<SoloSink Value="false"/><Sends>{s}</Sends></Mixer>')


def _clip(cid, start, end, path, ls=0.0, le=None, loop=False, rel=0.0, warped=False, markers=(), gain=1.0, fi=0.0,
          fo=0.0, disabled=False, env=""):
    le = le if le is not None else ls + (end - start) * (1 if warped else SPB)
    wm = "".join(f'<WarpMarker Id="{i}" SecTime="{s}" BeatTime="{b}"/>' for i, (b, s) in enumerate(markers))
    return (f'<AudioClip Id="{cid}" Time="{start}"><Name Value="c{cid}"/><CurrentStart Value="{start}"/>'
            f'<CurrentEnd Value="{end}"/><Loop><LoopStart Value="{ls}"/><LoopEnd Value="{le}"/>'
            f'<StartRelative Value="{rel}"/><LoopOn Value="{"true" if loop else "false"}"/></Loop>'
            f'<Envelopes><Envelopes>{env}</Envelopes></Envelopes>'
            f'<IsWarped Value="{"true" if warped else "false"}"/><WarpMarkers>{wm}</WarpMarkers>'
            f'<SampleVolume Value="{gain}"/><Disabled Value="{"true" if disabled else "false"}"/>'
            f'<Fades><FadeInLength Value="{fi}"/><FadeOutLength Value="{fo}"/><IsDefaultFadeIn Value="false"/>'
            f'<IsDefaultFadeOut Value="false"/></Fades>'
            f'<SampleRef><FileRef><Path Value="{path}"/><RelativePath Value="{Path(path).name}"/></FileRef></SampleRef></AudioClip>')


def _audio_track(tid, name, clips, base, group=-1, colour=14, vol=1.0, pan=0.0, on=True, sends=(), auto="",
                 devices="", out="AudioOut/GroupTrack"):
    return (f'<AudioTrack Id="{tid}"><Name><EffectiveName Value="{name}"/></Name><Color Value="{colour}"/>'
            f'<TrackGroupId Value="{group}"/><AutomationEnvelopes><Envelopes>{auto}</Envelopes></AutomationEnvelopes>'
            f'<DeviceChain><AudioOutputRouting><Target Value="{out}"/></AudioOutputRouting>'
            f'{_mixer(base, vol, pan, on, sends)}<MainSequencer><Sample><ArrangerAutomation><Events>{clips}'
            f'</Events></ArrangerAutomation></Sample></MainSequencer><DeviceChain><Devices>{devices}</Devices>'
            f'</DeviceChain></DeviceChain></AudioTrack>')


def _env(eid, target, pts):
    ev = "".join(f'<FloatEvent Id="{i}" Time="{t}" Value="{v}"/>' for i, (t, v) in enumerate(pts))
    return (f'<AutomationEnvelope Id="{eid}"><EnvelopeTarget><PointeeId Value="{target}"/></EnvelopeTarget>'
            f'<Automation><Events>{ev}</Events></Automation></AutomationEnvelope>')


def make_set(d, extra=""):
    """A small Live 12 set exercising what als2ardour carries, and what it must only list."""
    d = Path(d)
    t = np.arange(SR * 8) / SR
    mono = (0.3 * np.sin(2 * np.pi * 220 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.7 * t))).astype(np.float32)
    stereo = np.stack([mono, 0.5 * mono], axis=1)
    sf.write(d / "vox.wav", mono, SR, subtype="PCM_24")
    sf.write(d / "gtr.wav", stereo, SR, subtype="FLOAT")
    sf.write(d / "slow.wav", mono[: SR * 4], 44100, subtype="PCM_16")      # another rate: resampled on import
    cenv = ('<ClipEnvelope Id="0"><EnvelopeTarget><PointeeId Value="105"/></EnvelopeTarget><Automation><Events>'
            '<FloatEvent Id="0" Time="0" Value="1"/><FloatEvent Id="1" Time="2" Value="0.5"/></Events></Automation>'
            '</ClipEnvelope>')
    lead = _audio_track(
        10, "Lead", _clip(1, 4, 12, d / "vox.wav", ls=0.5, gain=0.5, fi=0.5, fo=1.0, env=cenv)
        + _clip(2, 14, 15, d / "vox.wav", disabled=True), 100, group=50, colour=14, vol=0.5, pan=0.25, sends=(0.5,),
        devices='<Compressor2 Id="0"><On><Manual Value="true"/></On></Compressor2>')
    gtr = _audio_track(
        11, "Gtr | DI", _clip(3, 0, 8, d / "gtr.wav", ls=0, le=4, loop=True, warped=True, markers=((0, 0), (4, 2.0)))
        + _clip(4, 16, 18, d / "missing.wav"), 120, group=51, colour=3,
        auto=_env(1, 122, [(-63072000, 1), (0, 1), (8, 0), (12, 1)]))
    bent = _audio_track(
        12, "Bent", _clip(5, 0, 8, d / "vox.wav", warped=True, markers=((0, 0), (4, 1.8), (8, 4.0)), le=8), 140,
        out="AudioOut/Main")
    slow = _audio_track(13, "Slow", _clip(6, 2, 4, d / "slow.wav"), 160, out="AudioOut/Main")
    notes = "".join(f'<MidiNoteEvent Time="{b}" Duration="0.5" Velocity="100" OffVelocity="0" NoteId="{i}"/>'
                    for i, b in enumerate((0, 1, 2, 3)))
    midi = (f'<MidiTrack Id="14"><Name><EffectiveName Value="Keys"/></Name><Color Value="20"/>'
            f'<TrackGroupId Value="-1"/><AutomationEnvelopes><Envelopes/></AutomationEnvelopes><DeviceChain>'
            f'<MidiOutputRouting><Target Value="MidiOut/None"/></MidiOutputRouting>{_mixer(180)}'
            f'<MainSequencer><ClipTimeable><ArrangerAutomation><Events><MidiClip Id="7" Time="8">'
            f'<CurrentStart Value="8"/><CurrentEnd Value="16"/><Loop><LoopStart Value="0"/><LoopEnd Value="4"/>'
            f'<StartRelative Value="0"/><LoopOn Value="true"/></Loop><Name Value="riff"/><Disabled Value="false"/>'
            f'<Notes><KeyTracks><KeyTrack Id="0"><Notes>{notes}</Notes><MidiKey Value="60"/></KeyTrack></KeyTracks>'
            f'</Notes></MidiClip></Events></ArrangerAutomation></ClipTimeable></MainSequencer>'
            f'<DeviceChain><Devices><OriginalSimpler Id="0"/></Devices></DeviceChain></DeviceChain></MidiTrack>')
    group = (f'<GroupTrack Id="50"><Name><EffectiveName Value="Vox"/></Name><Color Value="14"/>'
             f'<TrackGroupId Value="-1"/><AutomationEnvelopes><Envelopes/></AutomationEnvelopes><DeviceChain>'
             f'<AudioOutputRouting><Target Value="AudioOut/Main"/></AudioOutputRouting>{_mixer(200, vol=0.5)}'
             f'<DeviceChain><Devices><Eq8 Id="0"><On><Manual Value="true"/></On></Eq8></Devices></DeviceChain>'
             f'</DeviceChain></GroupTrack>')
    plain = (f'<GroupTrack Id="51"><Name><EffectiveName Value="Plain"/></Name><Color Value="3"/>'
             f'<TrackGroupId Value="-1"/><AutomationEnvelopes><Envelopes/></AutomationEnvelopes><DeviceChain>'
             f'<AudioOutputRouting><Target Value="AudioOut/Main"/></AudioOutputRouting>{_mixer(220)}'
             f'<DeviceChain><Devices/></DeviceChain></DeviceChain></GroupTrack>')
    ret = (f'<ReturnTrack Id="60"><Name><EffectiveName Value="Verb"/></Name><Color Value="1"/>'
           f'<TrackGroupId Value="-1"/><AutomationEnvelopes><Envelopes/></AutomationEnvelopes><DeviceChain>'
           f'<AudioOutputRouting><Target Value="AudioOut/Main"/></AudioOutputRouting>{_mixer(240, vol=0.7)}'
           f'<DeviceChain><Devices><Reverb Id="0"><On><Manual Value="true"/></On></Reverb></Devices></DeviceChain>'
           f'</DeviceChain></ReturnTrack>')
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><Ableton MajorVersion="5" MinorVersion="12.0_12402" '
           f'Creator="Ableton Live 12.4"><LiveSet><Tracks>{group}{lead}{plain}{gtr}{bent}{slow}{extra}{midi}{ret}</Tracks>'
           f'<MainTrack><Name><EffectiveName Value="Main"/></Name><AutomationEnvelopes><Envelopes>'
           f'{_env(2, 300, [(-63072000, BPM), (16, BPM), (16, 90.0)])}</Envelopes></AutomationEnvelopes>'
           f'<DeviceChain><Mixer><Volume><Manual Value="0.9"/><AutomationTarget Id="290"/></Volume>'
           f'<Pan><Manual Value="0"/><AutomationTarget Id="291"/></Pan>'
           f'<Speaker><Manual Value="true"/><AutomationTarget Id="292"/></Speaker><Sends/>'
           f'<Tempo><Manual Value="{BPM}"/><AutomationTarget Id="300"/></Tempo>'
           f'<TimeSignature><Manual Value="201"/></TimeSignature></Mixer>'
           f'<DeviceChain><Devices><Limiter Id="0"/></Devices></DeviceChain></DeviceChain></MainTrack>'
           f'<SendsPre><SendPreBool Id="0" Value="false"/></SendsPre></LiveSet></Ableton>')
    p = d / "Song Project" / "Song.als"
    p.parent.mkdir()
    with gzip.open(p, "wb") as f:
        f.write(xml.encode())
    return p


def smf_notes(path):
    """[(tick, key)] of the note-ons in a type-0 file as write_smf writes it (no running status)."""
    b = Path(path).read_bytes()
    assert b[:4] == b"MThd" and b[14:18] == b"MTrk"
    i, end, tick, out = 22, 22 + int.from_bytes(b[18:22], "big"), 0, []
    while i < end:
        d = 0
        while True:
            d = (d << 7) | (b[i] & 0x7F)
            i += 1
            if not b[i - 1] & 0x80:
                break
        tick += d
        if b[i] == 0xFF:
            i += 3 + b[i + 2]
            continue
        if b[i] & 0xF0 == 0x90:
            out.append((tick, b[i + 1]))
        i += 3
    return out


class ConstantRatio(unittest.TestCase):
    @unittest.skipUnless(shutil.which("rubberband"), "needs the rubberband command")
    def test_constant_ratio_is_a_stretched_copy_in_time(self):
        from hypnomix.project import als, ardour, als2ardour as X
        td = Path(tempfile.mkdtemp())
        try:
            # 4 beats of the clip hold 2.5 s of the file: it plays 1.25x faster than recorded
            fast = _audio_track(15, "Fast", _clip(8, 0, 8, td / "vox.wav", warped=True, markers=((0, 0), (4, 2.5)),
                                                  le=8), 260, out="AudioOut/Main")
            p = make_set(td, extra=fast)
            f, rep, w = X.convert(p, td / "S", log=lambda *a: None)
            self.assertEqual(len(w.report["warped"]), 1)
            self.assertIn("Plain constant ratio (1)", rep.read_text())
            s = ardour.read(f)
            c = s.track("Fast").clips[0]
            self.assertIn("(x1.2500)", c.take.path.name)
            self.assertAlmostEqual(c.length, 8 * SPB, places=4)
            live = als.read(p)
            a = live.render(live.track("Fast"), SR, length=5.0)
            b = s.render(s.track("Fast"), SR, length=5.0)
            n = min(len(a), len(b))
            a, b = a[:n], b[:n]
            lag = int(np.argmax(np.correlate(b[SR:2 * SR], a[SR - 200:2 * SR + 200], "valid"))) - 200
            self.assertLessEqual(abs(lag), 2)
            rms = lambda y: math.sqrt(float(np.mean(y ** 2))) + 1e-12
            self.assertLess(abs(20 * math.log10(rms(b) / rms(a))), 0.5)
        finally:
            shutil.rmtree(td, ignore_errors=True)


class Als2Ardour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from hypnomix.project import als2ardour as X
        cls.X = X
        cls.td = Path(tempfile.mkdtemp())
        cls.als = make_set(cls.td)
        cls.out = cls.td / "Imported"
        cls.f, cls.rep, cls.w = X.convert(cls.als, cls.out, log=lambda *a: None)
        from hypnomix.project import ardour
        cls.p = ardour.read(cls.f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.td, ignore_errors=True)

    def test_session_folder_and_copies(self):
        self.assertEqual(self.f, (self.out / "Imported.ardour").resolve())
        audio = self.out / "interchange" / "Imported" / "audiofiles"
        names = sorted(x.name for x in audio.iterdir())
        self.assertIn("vox.wav", names)
        self.assertIn("gtr%L.wav", names)
        self.assertIn("gtr%R.wav", names)
        y, sr = sf.read(audio / "vox.wav")
        self.assertEqual(sr, SR)
        np.testing.assert_allclose(y, sf.read(self.td / "vox.wav")[0], atol=1e-6)    # a copy, sample for sample
        self.assertEqual(sf.info(str(audio / "vox.wav")).subtype, "PCM_24")
        self.assertEqual(sf.info(str(audio / "slow.wav")).samplerate, SR)              # resampled
        self.assertFalse(self.p.missing())
        self.assertEqual(sorted(x.name for x in self.als.parent.iterdir()), ["Song.als"])   # nothing next to the set

    def test_tracks_order_kinds_and_routing(self):
        names = [(t.name, t.kind) for t in self.p.tracks]
        self.assertEqual(names, [("Vox", "folder"), ("Lead", "audio"), ("Gtr _ DI", "audio"), ("Bent", "audio"),
                                 ("Slow", "audio"), ("Keys", "midi"), ("Verb", "return"), ("Master", "master")])
        t = {x.name: x for x in self.p.tracks}
        self.assertIs(t["Lead"].parent, t["Vox"])                 # the group with an EQ is a bus its tracks feed
        self.assertIsNone(t["Gtr _ DI"].parent)                   # the plain group: a route group only
        self.assertAlmostEqual(t["Lead"].volume, 0.5)
        self.assertAlmostEqual(t["Lead"].pan, 0.25)
        self.assertAlmostEqual(t["Vox"].volume, 0.5)
        self.assertAlmostEqual(t["Verb"].volume, 0.7)
        self.assertAlmostEqual(t["Master"].volume, 0.9)
        root = ET.parse(self.f).getroot()
        groups = {g.get("name"): g for g in root.iter("RouteGroup")}
        self.assertEqual(set(groups), {"Vox", "Plain"})
        rid = {r.get("name"): r.get("id") for r in root.iter("Route")}
        self.assertEqual(groups["Vox"].get("subgroup-bus"), rid["Vox"])
        self.assertEqual(groups["Plain"].get("routes").split(), [rid["Gtr _ DI"]])
        self.assertIsNone(groups["Plain"].get("subgroup-bus"))
        lead = next(r for r in root.iter("Route") if r.get("name") == "Lead")
        pi = lead.find("PresentationInfo")
        self.assertEqual(int(pi.get("color")), 0xFF3636FF)        # Live colour 14
        send = next(p for p in lead.findall("Processor") if p.get("type") == "intsend")
        self.assertEqual(send.get("target"), rid["Verb"])
        gain = next(c for c in send.findall("Controllable") if c.get("name") == "gaincontrol")
        self.assertAlmostEqual(float(gain.get("value")), 0.5)
        kinds = [p.get("type") for p in lead.findall("Processor")]
        self.assertLess(kinds.index("amp"), kinds.index("intsend"))   # post-fader, as Live's default
        verb = next(r for r in root.iter("Route") if r.get("name") == "Verb")
        self.assertIn("intreturn", [p.get("type") for p in verb.findall("Processor")])

    def test_regions(self):
        t = {x.name: x for x in self.p.tracks}
        lead = sorted(t["Lead"].clips, key=lambda c: c.start)
        self.assertEqual(len(lead), 2)
        c = lead[0]
        self.assertAlmostEqual(c.start, 4 * SPB, places=4)
        self.assertAlmostEqual(c.length, 8 * SPB, places=4)
        self.assertAlmostEqual(c.take.offset, 0.5, places=4)      # unwarped: the start marker is in seconds
        self.assertAlmostEqual(c.level, 0.5, places=6)
        self.assertAlmostEqual(c.fade_in, 0.5 * SPB, places=3)
        self.assertAlmostEqual(c.fade_out, 1.0 * SPB, places=3)
        self.assertEqual(c.take.extra_paths, [c.take.path])       # mono file on both sides of the stereo track
        env = c.envelope
        self.assertAlmostEqual(np.interp(1 * SPB, [p[0] for p in env], [p[1] for p in env]), 0.75, places=3)
        self.assertTrue(lead[1].muted)                            # a switched-off clip
        gtr = sorted(t["Gtr _ DI"].clips, key=lambda c: c.start)
        self.assertEqual(len(gtr), 2)                             # looped clip: one region per pass
        self.assertAlmostEqual(gtr[1].start, 4 * SPB, places=4)
        self.assertAlmostEqual(gtr[1].take.offset, 0.0, places=4)
        self.assertEqual(gtr[0].fade_out, 0.0)                    # no fades at the loop seam
        self.assertEqual(gtr[1].fade_in, 0.0)
        self.assertNotIn("Volume", t["Lead"].envelopes)           # clip envelope is a region envelope, not track
        mute = t["Gtr _ DI"].envelopes.get("Mute")
        self.assertEqual([round(v) for _, v in mute], [0, 0, 1, 0])   # track on/off automation -> mute

    def test_renders_match_live(self):
        from hypnomix.project import als
        live = als.read(self.als)
        # (Lead has a clip envelope, which `hypnomix render` leaves out: compared in test_regions instead)
        for name, here in (("Gtr | DI", "Gtr _ DI"), ("Slow", "Slow")):
            a = live.render(live.track(name), SR, length=10.0)
            b = self.p.render(self.p.track(here), SR, length=10.0)
            n = min(len(a), len(b))
            a, b = a[:n], b[:n]
            rms = lambda y: math.sqrt(float(np.mean(y ** 2))) + 1e-12
            self.assertLess(abs(20 * math.log10(rms(b) / rms(a))), 0.05, name)
            self.assertLess(20 * math.log10(rms(a - b) / rms(a)), -40, name)

    def test_midi_notes(self):
        keys = self.p.track("Keys")
        self.assertEqual(len(keys.clips), 1)
        self.assertAlmostEqual(keys.clips[0].start, 8 * SPB, places=4)
        mid = list((self.out / "interchange" / "Imported" / "midifiles").glob("*.mid"))
        self.assertEqual(len(mid), 1)
        self.assertNotRegex(mid[0].name, r"-\d+\.mid$")              # never Ardour's own capture-file names
        self.assertEqual(smf_notes(mid[0]), [(b * 1920, 60) for b in range(8)])   # the loop played twice

    def test_tempo(self):
        root = ET.parse(self.f).getroot()
        tempos = [(float(t.get("npm")), int(t.get("sclock"))) for t in root.iter("Tempo")]
        self.assertEqual(tempos, [(120.0, 0), (90.0, int(round(16 * SPB * 282240000)))])
        meter = root.find(".//Meter")
        self.assertEqual((meter.get("divisions-per-bar"), meter.get("note-value")), ("4", "4"))
        tp = self.X.Tempo(120, [(0, 120), (16, 120), (16, 90)])
        self.assertAlmostEqual(tp.seconds(20), 8 + 4 * 60 / 90)
        ramp = self.X.Tempo(120, [(0, 120), (4, 60)])
        self.assertAlmostEqual(ramp.seconds(4), 60 / 15 * math.log(2), places=9)   # integral of 60/bpm over a ramp

    def test_report_lists_what_is_not_carried(self):
        r = self.rep.read_text()
        self.assertIn("Compressor", r)                          # the Lead's device, listed
        self.assertIn("EQ Eight", r)
        self.assertIn("Limiter", r)                             # the main track's
        self.assertIn("Simpler", r)
        self.assertIn("Real warp markers: NOT carried (1)", r)
        self.assertIn("Bent / c5", r)
        self.assertIn("missing.wav", r)
        self.assertIn("44100 Hz, resampled", r)
        self.assertIn("Gtr \\| DI (here: Gtr _ DI)", r)
        self.assertIn("COPIED", r)

    def test_refusals(self):
        with self.assertRaises(SystemExit):
            self.X.convert(self.als, self.out)                            # exists, not empty
        with self.assertRaises(SystemExit):
            self.X.convert(self.als, self.als.parent / "Inside")          # inside the Live project
        self.assertFalse((self.als.parent / "Inside").exists())

    def test_constant_ratio_and_bent_warps(self):
        X = self.X
        c = ET.fromstring(_clip(9, 0, 4, "x.wav", warped=True, markers=((0, 0), (4, 2.5)), le=4))
        pieces, info = X.clip_pieces(c, X.Tempo(BPM))
        self.assertEqual(info["kind"], "straight")
        self.assertAlmostEqual(info["rate"], 1.25)
        c = ET.fromstring(_clip(9, 0, 8, "x.wav", warped=True, markers=((0, 0), (4, 1.8), (8, 4.0)), le=8))
        pieces, info = X.clip_pieces(c, X.Tempo(BPM))
        self.assertEqual(info["kind"], "bent")
        self.assertAlmostEqual(info["drift_ms"], 200.0, places=6)


def _midi(tid, name, base):
    return (f'<MidiTrack Id="{tid}"><Name><EffectiveName Value="{name}"/></Name><Color Value="20"/>'
            f'<TrackGroupId Value="-1"/><AutomationEnvelopes><Envelopes/></AutomationEnvelopes><DeviceChain>'
            f'<MidiOutputRouting><Target Value="MidiOut/None"/></MidiOutputRouting>{_mixer(base)}'
            f'<MainSequencer><ClipTimeable><ArrangerAutomation><Events><MidiClip Id="1" Time="0">'
            f'<CurrentStart Value="0"/><CurrentEnd Value="4"/><Loop><LoopStart Value="0"/><LoopEnd Value="4"/>'
            f'<StartRelative Value="0"/><LoopOn Value="false"/></Loop><Name Value="m"/><Disabled Value="false"/>'
            f'<Notes><KeyTracks><KeyTrack Id="0"><Notes><MidiNoteEvent Time="0" Duration="1" Velocity="100"/>'
            f'</Notes><MidiKey Value="60"/></KeyTrack></KeyTracks></Notes></MidiClip></Events></ArrangerAutomation>'
            f'</ClipTimeable></MainSequencer><DeviceChain><Devices/></DeviceChain></DeviceChain></MidiTrack>')


class NoClobber(unittest.TestCase):
    """Files that would share a name on a case-insensitive disk, or tracks whose names clean to the same text,
    each keep their own file; a grouped track Live sends to the Main track skips the group bus."""

    def test_names_and_direct_out(self):
        from hypnomix.project import als2ardour as X
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (d / "a").mkdir()
        (d / "b").mkdir()
        sf.write(d / "a" / "Take.wav", np.full(SR, 0.1, np.float32), SR)
        sf.write(d / "b" / "take.wav", np.full(SR, 0.5, np.float32), SR)
        extra = (_audio_track(80, "A", _clip(81, 0, 2, d / "a" / "Take.wav"), 500, out="AudioOut/Main")
                 + _audio_track(82, "B", _clip(83, 0, 2, d / "b" / "take.wav"), 520, out="AudioOut/Main")
                 + _audio_track(84, "Direct", _clip(85, 0, 2, d / "a" / "Take.wav"), 540, group=50,
                                out="AudioOut/Main")
                 + _midi(90, "\u30d9\u30fc\u30b9", 560) + _midi(91, "\u30c9\u30e9\u30e0", 580))
        als = make_set(d, extra)
        out = d / "out" / "S"
        f, _, _ = X.convert(als, out, log=lambda *a: None)
        root = ET.parse(f).getroot()
        names = [s.get("name") for s in root.iter("Source")]
        self.assertEqual(len({n.lower() for n in names}), len(names))
        audio = out / "interchange" / "S" / "audiofiles"
        levels = sorted(round(float(np.abs(sf.read(audio / n)[0]).max()), 3) for n in names
                        if n.lower().startswith("take"))
        self.assertEqual(levels, [0.1, 0.5])
        midi = list((out / "interchange" / "S" / "midifiles").glob("*.mid"))
        self.assertEqual(len(midi), 3)
        rt = [r for r in root.iter("Route") if r.get("name") == "Direct"][0]
        outs = [c.get("other") for io in rt.findall("IO") if io.get("direction") == "Output"
                for c in io.iter("Connection")]
        self.assertEqual(outs, ["Master/audio_in 1", "Master/audio_in 2"])

    def test_bad_inputs_stop_with_a_message(self):
        from hypnomix.project import als2ardour as X
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (d / "junk.als").write_bytes(b"not a set")
        (d / "afile").write_text("x")
        with self.assertRaises(SystemExit):
            X.convert(d / "junk.als", d / "o" / "S")
        self.assertFalse((d / "o").exists())
        (d / "p").mkdir()
        (d / "p" / "plain.als").write_text('<?xml version="1.0"?><Ableton><LiveSet><Tracks/></LiveSet></Ableton>')
        with self.assertRaises(SystemExit):
            X.convert(d / "p" / "plain.als", d / "afile")
        f, _, _ = X.convert(d / "p" / "plain.als", d / "o" / "S")
        self.assertTrue(f.exists())


# ---------------------------------------------------------------- the review's findings (converters)
def _edit_set(als, fn):
    """Rewrite a set's XML text (gzip) with `fn(text) -> text`."""
    with gzip.open(als, "rb") as f:
        xml = f.read().decode()
    out = fn(xml)
    assert out != xml, "the edit changed nothing"
    with gzip.open(als, "wb") as f:
        f.write(out.encode())


def _convert(als, out, sr=None):
    from hypnomix.project import als2ardour as X
    return X.convert(als, out, sr, log=lambda *a: None)


class DroppedFeaturesAreListed(unittest.TestCase):
    """Every Live setting that changes what you hear, and that the session does not carry, is named in the report."""

    @classmethod
    def setUpClass(cls):
        cls.td = Path(tempfile.mkdtemp())
        d = cls.td
        extra = (_audio_track(30, "Trans", _clip(21, 0, 4, d / "vox.wav").replace(
            "<SampleVolume", '<PitchCoarse Value="7"/><PitchFine Value="25"/><SampleVolume'), 600, out="AudioOut/Main")
            + _audio_track(31, "Repitch", _clip(22, 0, 8, d / "vox.wav", warped=True, markers=((0, 0), (4, 2.5)),
                                                le=8).replace('<IsWarped Value="true"/>',
                                                              '<IsWarped Value="true"/><WarpMode Value="3"/>'),
                           620, out="AudioOut/Main")
            + _audio_track(32, "Shaped", _clip(23, 0, 4, d / "vox.wav").replace(
                '<IsDefaultFadeIn', '<FadeInCurveSkew Value="0.4"/><CrossfadeInState Value="1"/><IsDefaultFadeIn'),
                           640, out="AudioOut/Main"))
        als = make_set(d, extra)
        _edit_set(als, lambda x: x.replace('<TrackGroupId Value="-1"/>', '<TrackGroupId Value="-1"/><TrackDelay>'
                                           '<Value Value="-35"/><IsValueSampleBased Value="false"/></TrackDelay>', 1)
                  .replace("</LiveSet>", '<Locators><Locators><Locator Id="0"><Time Value="16"/><Name Value="Verse"/>'
                           '</Locator><Locator Id="1"><Time Value="32"/><Name Value="Chorus"/></Locator></Locators>'
                           '</Locators></LiveSet>')
                  .replace('<TimeSignature><Manual Value="201"/></TimeSignature>', '<TimeSignature><Manual Value="201"/>'
                           '<AutomationTarget Id="301"/></TimeSignature>')
                  .replace('</Envelopes></AutomationEnvelopes><DeviceChain><Mixer><Volume><Manual Value="0.9"/>',
                           _env(3, 301, [(-63072000, 201), (32, 200)]) +
                           '</Envelopes></AutomationEnvelopes><DeviceChain><Mixer><Volume><Manual Value="0.9"/>')
                  .replace("<Notes><KeyTracks>", '<Envelopes><Envelopes><ClipEnvelope Id="0"><EnvelopeTarget>'
                           '<PointeeId Value="9"/></EnvelopeTarget></ClipEnvelope></Envelopes></Envelopes>'
                           "<Notes><KeyTracks>", 1)
                  .replace('<MidiNoteEvent Time="0" Duration="0.5"', '<MidiNoteEvent Probability="0.5" Time="0" '
                           'Duration="0.5"', 1))
        cls.f, cls.rep, cls.w = _convert(als, d / "Out")
        cls.text = cls.rep.read_text()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.td, ignore_errors=True)

    def test_clip_transpose(self):
        self.assertIn("Clip transpose / detune is NOT carried (1)", self.text)
        self.assertIn("Trans / c21", self.text)
        self.assertIn("+7 semitones, detune +25 cents", self.text)

    def test_repitch_clip(self):
        self.assertIn("Re-Pitch warp mode is NOT carried (1)", self.text)
        self.assertIn("Repitch / c22", self.text)
        self.assertIn("pitch moving +3.86 semitones", self.text)          # 12 * log2(1.25)

    def test_track_delay(self):
        self.assertIn("Track delay is NOT carried (1)", self.text)
        self.assertIn("-35 ms (earlier", self.text)

    def test_fade_shapes_and_crossfades(self):
        self.assertIn("Fade curve shapes and crossfades are approximated (2)", self.text)
        self.assertIn("Shaped / c23", self.text)

    def test_time_signature_changes(self):
        self.assertIn("Time-signature changes are NOT carried (1)", self.text)
        self.assertIn("3/4", self.text)
        self.assertIn("beat 32", self.text)

    def test_locators(self):
        self.assertIn("Locators are NOT carried (2)", self.text)
        self.assertIn("Verse (bar 5)", self.text)
        self.assertIn("Chorus (bar 9)", self.text)

    def test_midi_settings(self):
        self.assertIn("MIDI clip settings NOT carried (1)", self.text)
        self.assertIn("note probabilities below 100%", self.text)
        self.assertIn("1 controller envelope(s)", self.text)

    def test_the_command_line_says_so_too(self):
        import contextlib
        import io
        from hypnomix.project import als2ardour as X
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            X.main([str(self.td / "Song Project" / "Song.als"), str(self.td / "Out2")])
        out = buf.getvalue()
        for word in ("transposed clips", "Re-Pitch", "track delay", "time-signature changes", "locators"):
            self.assertIn(word, out)

    def test_what_is_carried_is_still_where_live_has_it(self):
        from hypnomix.project import ardour
        p = ardour.read(self.f)
        for name, start in (("Trans", 0.0), ("Shaped", 0.0)):
            c = p.track(name).clips[0]
            self.assertAlmostEqual(c.start, start, places=4)
            self.assertAlmostEqual(c.length, 4 * SPB, places=4)


class RampsAndMidi(unittest.TestCase):
    """A tempo ramp followed by a MIDI clip: the written tempo map is consistent, so beats and seconds agree."""

    def test_the_map_agrees_with_itself_and_with_live(self):
        from hypnomix.project import als2ardour as X
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        als = make_set(td)
        pts = [(-63072000, 100), (16, 100), (16, 140), (32, 140), (48, 70)]
        _edit_set(als, lambda x: x.replace(_env(2, 300, [(-63072000, BPM), (16, BPM), (16, 90.0)]), _env(2, 300, pts)))
        f, rep, w = _convert(als, td / "S")
        root = ET.parse(f).getroot()
        tp = [(float(t.get("npm")), int(t.get("sclock")), t.get("quarters")) for t in root.iter("Tempo")]
        self.assertGreater(len(tp), 40)                                  # the ramp is a run of steps, not one jump
        q = lambda s_: int(s_.split(":")[0]) + int(s_.split(":")[1]) / 1920
        # Ardour recomputes each point's time from its beat position and the tempo before it
        t_ard = 0.0
        for (v0, sc0, q0), (v1, sc1, q1) in zip(tp, tp[1:]):
            t_ard += (q(q1) - q(q0)) * 60.0 / v0
            self.assertAlmostEqual(sc1 / 282240000, t_ard, delta=2e-6)    # what is written is what Ardour computes
        live = X.Tempo(BPM, [(0, 100), (16, 100), (16, 140), (32, 140), (48, 70)])
        self.assertAlmostEqual(t_ard, live.seconds(q(tp[-1][2])), delta=2e-4)    # and Live's own seconds
        text = rep.read_text()
        self.assertIn("Tempo ramps (bar 9 to bar 13 (140 to 70 BPM))", text)     # the bars are named
        err = float(text.split("up to ")[1].split(" ms")[0])
        self.assertLess(err, 1.0)
        # the bound the report states is the real worst case
        segs = live.segments()
        worst = max(abs(live.seconds(b0) + (x - b0) * 60 / v0 - live.seconds(x)) * 1000
                    for (b0, v0), nxt in zip(segs, segs[1:]) for x in (b0 + (nxt[0] - b0) * k / 16 for k in range(17)))
        self.assertLessEqual(worst, err + 0.01)

    def test_steps_stay_steps(self):
        from hypnomix.project import als2ardour as X
        self.assertEqual(X.Tempo(120, [(0, 120), (16, 120), (16, 90)]).segments(), [(0, 120), (16, 90)])
        segs = X.Tempo(100, [(0, 100), (4, 100), (4, 200)]).segments()
        self.assertEqual(segs, [(0, 100), (4, 200)])


class Hostile(unittest.TestCase):
    """Damaged or odd sets and files: a plain message, never a half-made session, never audio that is not audio."""

    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)

    def _siblings(self, out):
        return sorted(x.name for x in Path(out).parent.iterdir()) if Path(out).parent.exists() else []   # (folders a failed run made are taken away again)

    def test_a_crash_leaves_nothing_behind_and_the_rerun_works(self):
        from unittest import mock
        from hypnomix.project import als2ardour as X
        als = make_set(self.td)
        out = self.td / "o" / "S"
        with mock.patch.object(X.Writer, "midi_regions", side_effect=TypeError("boom")):
            with self.assertRaises(SystemExit) as cm:
                X.convert(als, out, log=lambda *a: None)
        msg = str(cm.exception)
        self.assertIn("could not be converted", msg)
        self.assertIn("Keys", msg)                                       # it says where (the track being built)
        self.assertIn("run it again", msg)
        self.assertFalse(out.exists())
        self.assertEqual(self._siblings(out), [])                        # no hidden temporary folder either
        f, _, _ = X.convert(als, out, log=lambda *a: None)               # and the same folder can be used now
        self.assertTrue(f.exists())

    def test_ctrl_c_leaves_nothing_behind(self):
        from unittest import mock
        from hypnomix.project import als2ardour as X
        als = make_set(self.td)
        out = self.td / "o" / "S"
        with mock.patch.object(X.Writer, "midi_regions", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                X.convert(als, out, log=lambda *a: None)
        self.assertEqual(self._siblings(out), [])

    def test_a_folder_that_exists_empty_is_filled_in_place(self):
        als = make_set(self.td)
        out = self.td / "o" / "S"
        out.mkdir(parents=True)
        f, _, _ = _convert(als, out)
        self.assertTrue(f.exists())
        self.assertEqual(self._siblings(out), ["S"])

    def test_sample_rate_must_be_positive(self):
        from hypnomix.project import als2ardour as X
        als = make_set(self.td)
        for bad in (0, -48000):
            with self.assertRaises(SystemExit) as cm:
                X.main([str(als), str(self.td / "o" / "S"), "--sr", str(bad)])
            self.assertIn("positive", str(cm.exception))
        self.assertFalse((self.td / "o").exists())

    def test_clip_without_an_end_is_left_out_with_a_note(self):
        als = make_set(self.td)
        import re
        _edit_set(als, lambda x: re.sub(r'<CurrentEnd Value="[^"]*"/>', "", x, count=1))
        f, rep, w = _convert(als, self.td / "S")
        self.assertIn("no readable start or end", rep.read_text())

    def test_not_a_number_is_never_written(self):
        als = make_set(self.td)
        _edit_set(als, lambda x: x.replace('<SampleVolume Value="0.5"/>', '<SampleVolume Value="nan"/>', 1))
        f, _, _ = _convert(als, self.td / "S")
        txt = f.read_text()
        self.assertNotIn("nan", txt.lower().replace("name", "").replace("nano", ""))
        self.assertNotIn("inf", txt.lower().replace("info", "").replace("inform", ""))

    def test_a_plain_xml_set_over_the_size_cap_is_refused(self):
        from unittest import mock
        from hypnomix.core import gz
        from hypnomix.project import als2ardour as X
        p = self.td / "big.als"
        p.write_text('<?xml version="1.0"?><Ableton><LiveSet><Tracks/></LiveSet></Ableton>' + " " * 5000)
        with mock.patch.object(gz, "CAP", 1000):
            with self.assertRaises(SystemExit) as cm:
                X.load_xml(p)
        self.assertIn("not a readable Live set", str(cm.exception))
        self.assertIn("larger", str(cm.exception))
        self.assertEqual(X.load_xml(p).tag, "Ableton")                    # under the real cap it opens

    def test_a_set_from_a_newer_live_warns_and_converts(self):
        import contextlib
        import io
        from hypnomix.session import liveversion as LV
        als = make_set(self.td)
        _edit_set(als, lambda x: x.replace('Creator="Ableton Live 12.4"', 'Creator="Ableton Live 99.1"')
                  .replace('MinorVersion="12.0_12402"', 'MinorVersion="99.0_1"'))
        LV._warned.clear()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            f, rep, w = _convert(als, self.td / "S")
        self.assertIn("Live 99.1", err.getvalue())
        self.assertTrue(f.exists())
        self.assertIn("saved by Live 99.1", rep.read_text())

    def test_a_text_file_with_a_raw_audio_name_is_not_copied(self):
        secret = self.td / "secret"
        secret.mkdir()
        (secret / "hist.sw").write_text("password=hunter2 api_key=abc123 ssh-rsa AAAAB3Nza\n" * 400)
        als = make_set(self.td, _audio_track(40, "Sneaky", _clip(41, 0, 2, secret / "hist.sw"), 700,
                                             out="AudioOut/Main"))
        f, rep, w = _convert(als, self.td / "S", 44100)
        audio = self.td / "S" / "interchange" / "S" / "audiofiles"
        self.assertNotIn("hist.wav", [x.name for x in audio.iterdir()])
        self.assertEqual([x for x in audio.iterdir() if b"hunter2" in x.read_bytes()[:200000]
                          or b"password" in x.read_bytes()], [])
        self.assertIn("hist.sw", rep.read_text())                          # listed as unreadable
        self.assertIn("not an audio file", rep.read_text())

    def test_container_check_goes_by_the_contents(self):
        from hypnomix.project import als2ardour as X
        p = self.td / "t"
        for name, data, want in (("a.wav", b"RIFF\x00\x00\x00\x00WAVEfmt ", "wav"), ("b.bin", b"fLaC\x00\x00", "flac"),
                                 ("c.mp3", b"ID3\x03\x00", "mp3"), ("d.m4a", b"\x00\x00\x00\x20ftypM4A ", "m4a"),
                                 ("e.mp3", b"\xff\xfb\x90\x00" + b"\x00" * 12, "mp3"),
                                 ("f.mp3", b"\xff\xfe\x00\x00" + b"\x00" * 12, None),       # a UTF-16 text BOM
                                 ("g.sw", b"password=hunter2", None), ("h.wav", b"not really a wav file", None),
                                 ("i.raw", b"\x00" * 64, None), ("j.txt", b"", None)):
            p.write_bytes(data)
            q = self.td / name
            q.write_bytes(data)
            self.assertEqual(X.audio_container(q), want, name)
        self.assertIsNone(X.audio_container(self.td / "missing.wav"))
        self.assertIsNone(X.audio_container("/dev/null"))

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_a_real_compressed_file_still_comes_across(self):
        import subprocess
        t = np.arange(SR * 2) / SR
        sf.write(self.td / "tone.wav", (0.3 * np.sin(2 * np.pi * 330 * t)).astype(np.float32), SR)
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(self.td / "tone.wav"), "-c:a", "aac",
                            str(self.td / "tone.m4a")], capture_output=True)
        if r.returncode:
            self.skipTest("this ffmpeg has no aac encoder")
        als = make_set(self.td, _audio_track(50, "Comp", _clip(51, 0, 4, self.td / "tone.m4a"), 720, out="AudioOut/Main"))
        f, rep, w = _convert(als, self.td / "S")
        self.assertIn("tone.wav", [x.name for x in (self.td / "S" / "interchange" / "S" / "audiofiles").iterdir()])

    def test_samples_outside_the_project_folder_are_listed(self):
        als = make_set(self.td)                       # make_set keeps its audio next to the project folder, not in it
        f, rep, w = _convert(als, self.td / "S")
        text = rep.read_text()
        self.assertIn("Samples from outside the Live project folder", text)
        self.assertIn("vox.wav", text)
        inside = self.td / "Song Project" / "Samples"
        inside.mkdir(parents=True)
        shutil.copy(self.td / "vox.wav", inside / "inner.wav")
        als2 = self.td / "Song Project" / "Song.als"
        _edit_set(als2, lambda x: x.replace(str(self.td / "vox.wav"), str(inside / "inner.wav")).replace(
            str(self.td / "gtr.wav"), str(inside / "inner.wav")).replace(str(self.td / "slow.wav"), str(inside / "inner.wav")))
        f, rep, w = _convert(als2, self.td / "S2")
        self.assertNotIn("Samples from outside the Live project folder", rep.read_text())

    def test_long_names_are_cut(self):
        long_ = "a" * 200
        sf.write(self.td / f"{long_}.wav", np.full(SR, 0.2, np.float32), SR)
        names = ["\u30d9" * 150, "B" * 300]
        extra = (_audio_track(60, long_, _clip(61, 0, 2, self.td / f"{long_}.wav"), 740, out="AudioOut/Main")
                 + _midi(62, names[0], 760) + _midi(63, names[1], 780))
        als = make_set(self.td, extra)
        f, rep, w = _convert(als, self.td / "S")
        root = ET.parse(f).getroot()
        for r in root.iter("Route"):
            self.assertLessEqual(len(r.get("name")), 80)
        for sub_ in ("audiofiles", "midifiles"):
            for x in (self.td / "S" / "interchange" / "S" / sub_).iterdir():
                self.assertLessEqual(len(x.name.encode()), 140, x.name)
        self.assertIn("(here: ", rep.read_text())                              # the full Live name stays in the report

    def test_memory_stays_small_for_a_long_file(self):
        import tracemalloc
        n = SR * 40
        y = np.clip(0.2 * np.random.default_rng(1).standard_normal((n, 2)), -0.99, 0.99).astype(np.float32)
        sf.write(self.td / "long.wav", y, SR, subtype="PCM_16")               # 40 s stereo
        sf.write(self.td / "long44.wav", y[: 44100 * 40], 44100, subtype="PCM_16")
        for fn, ceiling in (("long.wav", 12e6), ("long44.wav", 60e6)):
            als = make_set(self.td, _audio_track(
                70, "Long", _clip(71, 0, 80, self.td / fn), 800, out="AudioOut/Main"))
            tracemalloc.start()
            try:
                _convert(als, self.td / ("o_" + fn))
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
            self.assertLess(peak, ceiling, f"{fn}: peak {peak / 1e6:.0f} MB")
            shutil.rmtree(als.parent)
        # the copy is still sample for sample
        got, sr_ = sf.read(self.td / "o_long.wav" / "interchange" / "o_long.wav" / "audiofiles" / "long%L.wav", dtype="float32")
        np.testing.assert_allclose(got, y[:, 0], atol=1.5e-4)


class MoreDroppedFeatures(unittest.TestCase):
    """Split stereo pan, grooves and the crossfader's A / B side change what you hear and are not carried: listed."""

    @staticmethod
    def _make(td, groove_amount=100):
        als = make_set(td)
        _edit_set(als, lambda x: x
                  .replace('<SoloSink Value="false"/><Sends><TrackSendHolder', '<SoloSink Value="false"/><PanMode Value="1"/>'
                           '<SplitStereoPanL><Manual Value="-0.5"/></SplitStereoPanL><SplitStereoPanR><Manual Value="0.75"/>'
                           '</SplitStereoPanR><CrossFadeState><Manual Value="2"/></CrossFadeState><Sends><TrackSendHolder', 1)
                  .replace('<Name Value="c1"/>', '<Name Value="c1"/><GrooveSettings><GrooveId Value="4"/></GrooveSettings>', 1)
                  .replace('<Name Value="riff"/>', '<Name Value="riff"/><GrooveSettings><GrooveId Value="4"/></GrooveSettings>', 1)
                  .replace("<Tracks>", '<GroovePool><Grooves><Groove Id="4"><Name Value="Swing 16ths 66"/>'
                           '<TimingAmount Value="100"/></Groove></Grooves></GroovePool><Tracks>', 1)
                  .replace('<TimeSignature><Manual Value="201"/></TimeSignature></Mixer>', '<TimeSignature><Manual Value="201"/>'
                           f'</TimeSignature><GlobalGrooveAmount><Manual Value="{groove_amount}"/></GlobalGrooveAmount>'
                           '<CrossFade><Manual Value="0.5"/></CrossFade></Mixer>'))
        return als

    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)

    def test_all_three_are_in_the_report_and_on_the_command_line(self):
        import contextlib
        import io
        from hypnomix.project import als2ardour as X
        als = self._make(self.td)
        f, rep, w = _convert(als, self.td / "Out")
        text = rep.read_text()
        self.assertIn("Split stereo pan is NOT carried (1)", text)
        self.assertIn("Lead: left channel panned -0.50, right channel +0.75", text)
        self.assertIn("Grooves are NOT carried (2)", text)
        self.assertIn("Lead / c1", text)
        self.assertIn("Keys / MIDI clip 1: groove 'Swing 16ths 66'", text)
        self.assertIn("Crossfader A/B assignments are NOT carried (1)", text)
        self.assertIn("assigned to crossfader side B", text)
        self.assertIn("+0.50", text)                                   # where the crossfader sits in this set
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            X.main([str(als), str(self.td / "Out2")])
        for word in ("split stereo pan", "with a groove", "crossfader"):
            self.assertIn(word, buf.getvalue())

    def test_a_groove_the_set_does_not_play_is_not_listed(self):
        _, rep, _ = _convert(self._make(self.td, groove_amount=0), self.td / "Out")      # the global groove amount is 0
        text = rep.read_text()
        self.assertNotIn("Grooves are NOT carried", text)
        self.assertIn("Split stereo pan is NOT carried", text)


class AdtsAndOutdir(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)

    def test_a_raw_aac_stream_is_audio_but_the_same_bytes_named_mp3_are_not(self):
        from hypnomix.project import als2ardour as X
        head = b"\xff\xf1\x50\x80\x00\x1f\xfc" + b"\x00" * 9               # ADTS: sync, layer 00, 44.1 kHz
        for name, want in (("a.aac", "aac"), ("b.mp3", None), ("c.txt", None)):
            (self.td / name).write_bytes(head)
            self.assertEqual(X.audio_container(self.td / name), want, name)
        (self.td / "d.aac").write_bytes(b"\xff\xf1\x3c\x80" + b"\x00" * 12)       # sample-rate index 15 does not exist
        self.assertIsNone(X.audio_container(self.td / "d.aac"))

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_an_ffmpeg_made_aac_file_is_recognised(self):
        import subprocess
        t = np.arange(SR * 2) / SR
        sf.write(self.td / "tone.wav", (0.3 * np.sin(2 * np.pi * 330 * t)).astype(np.float32), SR)
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(self.td / "tone.wav"), "-c:a", "aac",
                            "-f", "adts", str(self.td / "tone.aac")], capture_output=True)
        if r.returncode:
            self.skipTest("this ffmpeg has no aac encoder")
        from hypnomix.project import als2ardour as X
        self.assertEqual(X.audio_container(self.td / "tone.aac"), "aac")

    def test_the_current_empty_folder_stays_the_same_folder(self):
        import os
        als = make_set(self.td)
        out = self.td / "Here"
        out.mkdir()
        before = os.stat(out).st_ino
        cwd = os.getcwd()
        os.chdir(out)
        try:
            f, _, _ = _convert(als, ".")
            self.assertEqual(os.getcwd(), str(out.resolve()))            # the shell is not left in a dead folder
            self.assertTrue((Path(".") / "IMPORT-REPORT.md").exists())
        finally:
            os.chdir(cwd)
        self.assertEqual(os.stat(out).st_ino, before)
        self.assertEqual(sorted(x.name for x in out.iterdir() if x.name.startswith(".")), [])   # no temporary folder left

    def test_an_empty_folder_in_a_read_only_parent_still_works(self):
        import os
        if os.geteuid() == 0:
            self.skipTest("root can write anywhere")
        als = make_set(self.td)
        ro = self.td / "ro"
        (ro / "Sess").mkdir(parents=True)
        os.chmod(ro, 0o555)
        try:
            f, _, _ = _convert(als, ro / "Sess")
            self.assertTrue(f.exists())
        finally:
            os.chmod(ro, 0o755)

    def test_a_new_folder_in_a_read_only_parent_is_one_sentence(self):
        import os
        if os.geteuid() == 0:
            self.skipTest("root can write anywhere")
        als = make_set(self.td)
        ro = self.td / "ro"
        ro.mkdir()
        os.chmod(ro, 0o555)
        try:
            with self.assertRaises(SystemExit) as cm:
                _convert(als, ro / "Sess")
        finally:
            os.chmod(ro, 0o755)
        self.assertIn("cannot be created here", str(cm.exception))

    def test_a_failed_run_takes_the_parent_folders_it_made_away_again(self):
        from unittest import mock
        from hypnomix.project import als2ardour as X
        als = make_set(self.td)
        out = self.td / "nope" / "deeper" / "Sess"
        with mock.patch.object(X.Writer, "midi_regions", side_effect=TypeError("boom")):
            with self.assertRaises(SystemExit):
                X.convert(als, out, log=lambda *a: None)
        self.assertFalse((self.td / "nope").exists())
        self.assertFalse(any(x.name in ("nope", ".Sess.tmp") for x in self.td.iterdir()))

    def test_a_failed_run_into_an_empty_folder_leaves_it_empty(self):
        from unittest import mock
        from hypnomix.project import als2ardour as X
        als = make_set(self.td)
        out = self.td / "Sess"
        out.mkdir()
        with mock.patch.object(X.Writer, "midi_regions", side_effect=TypeError("boom")):
            with self.assertRaises(SystemExit) as cm:
                X.convert(als, out, log=lambda *a: None)
        self.assertEqual(list(out.iterdir()), [])
        self.assertIn("is as it was", str(cm.exception))


class Meters(unittest.TestCase):
    def test_six_eight_and_three_four(self):
        for value, num, den, bbt in ((302, "6", "8", "6|3|0"), (200, "3", "4", "6|2|0")):
            td = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, td, ignore_errors=True)
            als = make_set(td)
            _edit_set(als, lambda x: x.replace('<TimeSignature><Manual Value="201"/>', f'<TimeSignature><Manual Value="{value}"/>'))
            f, rep, w = _convert(als, td / "S")
            root = ET.parse(f).getroot()
            m = root.find(".//Meter")
            self.assertEqual((m.get("divisions-per-bar"), m.get("note-value")), (num, den))
            self.assertEqual([t.get("bbt") for t in root.iter("Tempo")][1], bbt)         # the step at beat 16
            self.assertIn(f"{num}/{den}", rep.read_text())


if __name__ == "__main__":
    unittest.main()
