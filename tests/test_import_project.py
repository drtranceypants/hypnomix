"""hypnomix import: projects from other DAWs become a new session that the session reader (hypnomix.project.ardour)
reads back.

Covered without any other DAW installed: .dawproject files (made here), a .logicx package built here record by record
in the layout import_logic reads (a round trip of that layout, not a check against real files), .ptx sessions and .aaf
through stand-in readers that print what the engine's readers print, format detection, the shared writer's checks and
limits, the DAW view's import job and its route, and one test or more for each finding of the review.
"""
import json
import math
import os
import shutil
import stat
import struct
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from unittest import mock
from pathlib import Path

import numpy as np
import soundfile as sf

from hypnomix.project import ardour, importer, import_logic, import_project
from tests import _isolate

SR = 48000

# Hard caps, set before any test runs (the review's rule after two near misses): every file this process and its
# children write is limited by the OS (RLIMIT_FSIZE), and a watchdog stops the run if this process grows past
# MEMORY_CAP over what it used at the start (macOS does not enforce RLIMIT_AS, so memory is watched instead).
FILE_CAP = 1 << 30
MEMORY_CAP = 3 << 30
_saved_fsize = None
_watch = {"on": False}


def setUpModule():
    global _saved_fsize
    try:
        import resource
        _saved_fsize = resource.getrlimit(resource.RLIMIT_FSIZE)
        hard = _saved_fsize[1]
        resource.setrlimit(resource.RLIMIT_FSIZE, (min(FILE_CAP, hard) if hard != resource.RLIM_INFINITY else FILE_CAP, hard))
        unit = 1 if sys.platform == "darwin" else 1024         # ru_maxrss: bytes on macOS, kilobytes elsewhere
        base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * unit
    except (ImportError, ValueError, OSError):
        return
    _watch["on"] = True

    def watch():
        while _watch["on"]:
            if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * unit - base > MEMORY_CAP:
                sys.stderr.write(f"test_import_project: memory grew past {MEMORY_CAP >> 30} GB: stopped\n")
                os._exit(3)
            time.sleep(0.25)
    threading.Thread(target=watch, daemon=True, name="memory-watchdog").start()


def tearDownModule():
    _watch["on"] = False
    if _saved_fsize is not None:
        import resource
        resource.setrlimit(resource.RLIMIT_FSIZE, _saved_fsize)


def tone(path, seconds=4.0, sr=SR, channels=2, f=110.0):
    t = np.arange(int(seconds * sr)) / sr
    y = 0.3 * np.sin(2 * np.pi * f * t)
    sf.write(str(path), np.stack([y] * channels, 1) if channels > 1 else y, sr)
    return path


def route_by_name(session):
    import xml.etree.ElementTree as ET
    root = ET.parse(session).getroot()
    return root, {r.get("name"): r for r in root.iter("Route")}


def gain_of(route):
    for p in route.iter("Processor"):
        if p.get("type") == "amp":
            for c in p.iter("Controllable"):
                if c.get("name") == "gaincontrol":
                    return float(c.get("value"))
    return None


# ---------------------------------------------------------------- DAWproject
DP_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<Project version="1.0"><Application name="Test Host" version="1.0"/>
<Transport><Tempo unit="bpm" value="100" min="20" max="999"/><TimeSignature numerator="3" denominator="4"/></Transport>
<Structure>
 <Track contentType="tracks" name="Drums" id="f1" color="#ff0000">
   <Channel role="submix" id="c_f1" destination="c_m"><Volume unit="linear" value="0.5" min="0" max="2"/></Channel>
   <Track contentType="audio" name="Kick" id="t1" color="#00ff00"><Channel role="regular" id="c1" destination="c_f1">
     <Devices><Vst3Plugin deviceName="Some EQ" deviceRole="audioFX"/></Devices>
     <Mute value="false"/><Pan unit="normalized" value="0.25" min="0" max="1"/>
     <Sends><Send destination="c_fx" type="post"><Volume unit="linear" value="0.25" min="0" max="2"/></Send></Sends>
     <Volume unit="decibel" value="-6" min="-60" max="6"/></Channel></Track>
 </Track>
 <Track contentType="audio" name="Vox" id="t2"><Channel role="regular" id="c2" destination="c_m" solo="true"><Mute value="true"/></Channel></Track>
 <Track contentType="notes" name="Keys" id="t3"><Channel role="regular" id="c3" destination="c_m"/></Track>
 <Track contentType="audio" name="Verb" id="t4"><Channel role="effect" id="c_fx" destination="c_m"/></Track>
 <Channel role="master" id="c_m"><Volume unit="linear" value="0.5" min="0" max="2"/></Channel>
</Structure>
<Arrangement id="a1">
 <TempoAutomation unit="bpm" timeUnit="beats"><Target/><RealPoint time="0" value="100" interpolation="hold"/><RealPoint time="8" value="120" interpolation="hold"/></TempoAutomation>
 <Markers><Marker time="0" name="Intro"/><Marker time="8" name="Verse"/></Markers>
 <Lanes timeUnit="beats">
  <Lanes track="t1"><Clips>
    <Clip time="0" duration="4" playStart="0" fadeTimeUnit="seconds" fadeInTime="0.01" fadeOutTime="0.05"><Audio channels="2" sampleRate="48000" duration="4"><File path="audio/kick.wav"/></Audio></Clip>
    <Clip time="8" duration="2" contentTimeUnit="seconds" playStart="1.0"><Audio channels="2" sampleRate="48000" duration="4"><File path="audio/kick.wav"/></Audio></Clip>
  </Clips></Lanes>
  <Lanes track="t2"><Clips><Clip time="4" duration="4" enable="false"><Clips><Clip time="0" duration="4" contentTimeUnit="beats" playStart="0"><Warps contentTimeUnit="seconds" timeUnit="beats"><Audio channels="1" sampleRate="44100" duration="4"><File path="audio/vox.wav"/></Audio><Warp time="0" contentTime="0"/><Warp time="4" contentTime="2.4"/></Warps></Clip></Clips></Clip></Clips></Lanes>
  <Lanes track="t3"><Clips><Clip time="0" duration="8" playStart="0" loopStart="0" loopEnd="2"><Notes><Note time="0" duration="0.5" channel="0" key="60" vel="0.787402"/><Note time="1" duration="1.5" channel="0" key="64" vel="0.5"/></Notes></Clip></Clips></Lanes>
 </Lanes>
</Arrangement></Project>'''


def make_dawproject(d):
    d = Path(d)
    tone(d / "kick.wav")
    tone(d / "vox.wav", sr=44100, channels=1)
    p = d / "song.dawproject"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("project.xml", DP_XML)
        z.write(d / "kick.wav", "audio/kick.wav")
        z.write(d / "vox.wav", "audio/vox.wav")
    return p


class DAWprojectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="hx-imp-dp-"))
        cls.src = make_dawproject(cls.tmp)
        cls.f, cls.rep, cls.summary = import_project.convert(cls.src, cls.tmp / "out", log=lambda *a: None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_detected_and_summary(self):
        self.assertEqual(import_project.kind_of(self.src), "dawproject")
        self.assertIn("DAWproject", self.summary)
        self.assertTrue(self.f.is_file())
        self.assertFalse(any(p.name.startswith(".out.media") for p in self.tmp.iterdir()))   # extracted audio removed

    def test_tracks_mixer_and_routing(self):
        root, routes = route_by_name(self.f)
        self.assertEqual([n for n in routes], ["Master", "Drums", "Kick", "Vox", "Keys", "Verb"])
        self.assertAlmostEqual(gain_of(routes["Kick"]), 10 ** (-6 / 20), places=6)
        self.assertAlmostEqual(gain_of(routes["Drums"]), 0.5, places=6)
        pan = [c for c in routes["Kick"].iter("Controllable") if c.get("name") == "pan-azimuth"][0]
        self.assertAlmostEqual(float(pan.get("value")), 0.25, places=6)
        kick_out = [io for io in routes["Kick"].iter("IO") if io.get("direction") == "Output"][0]
        self.assertIn("Drums/audio_in 1", [c.get("other") for c in kick_out.iter("Connection")])
        sends = [p for p in routes["Kick"].iter("Processor") if p.get("type") == "intsend"]
        self.assertEqual([s.get("target") for s in sends], [routes["Verb"].get("id")])
        vox = routes["Vox"]
        self.assertEqual([c.get("value") for c in vox.iter("Controllable") if c.get("name") == "mute"], ["1"])

    def test_regions_tempo_notes_markers(self):
        p = ardour.read(self.f)
        kick = p.track("Kick")
        self.assertEqual(len(kick.clips), 2)
        self.assertAlmostEqual(kick.clips[0].start, 0.0, places=4)
        self.assertAlmostEqual(kick.clips[1].start, 8 * 0.6, places=3)               # beat 8 at 100 BPM
        self.assertAlmostEqual(kick.clips[1].take.offset, 1.0, places=3)             # playStart in seconds
        vox = p.track("Vox")
        self.assertTrue(vox.clips[0].muted)
        rep = self.rep.read_text(encoding="utf-8")
        self.assertIn("Some EQ (VST3)", rep)
        self.assertIn("resampled", rep)
        mid = list((self.f.parent / "interchange" / "out" / "midifiles").glob("*.mid"))
        self.assertEqual(len(mid), 1)
        import xml.etree.ElementTree as ET
        locs = [l.get("name") for l in ET.parse(self.f).getroot().iter("Location") if l.get("flags") == "IsMark"]
        self.assertEqual(locs, ["Intro", "Verse"])
        self.assertIn("8 notes", rep)                                               # 2 notes x 4 loop passes

    def test_tempo_step_written(self):
        import xml.etree.ElementTree as ET
        tempos = [float(t.get("npm")) for t in ET.parse(self.f).getroot().iter("Tempo")]
        self.assertEqual(tempos, [100.0, 120.0])

    def test_bad_input(self):
        bad = self.tmp / "bad.dawproject"
        bad.write_bytes(b"PK\x03\x04 not a zip")
        with self.assertRaises(SystemExit):
            import_project.convert(bad, self.tmp / "bad-out", kind="dawproject", log=lambda *a: None)
        self.assertFalse((self.tmp / "bad-out").exists())


# ---------------------------------------------------------------- Logic, built record by record
MAGIC = b"#G\xc0\xab"


def rec(tag, data, cls=0, group=0, index=0, sub=0):
    h = bytearray(36)
    h[0:4] = tag[::-1].encode("latin1")
    struct.pack_into("<H", h, 4, 1)
    struct.pack_into("<H", h, 6, cls)
    struct.pack_into("<H", h, 0x0a, group)
    struct.pack_into("<I", h, 0x0e, index)
    struct.pack_into("<I", h, 0x12, sub)
    struct.pack_into("<Q", h, 0x1c, len(data))
    return bytes(h) + data


def envi(name, channel):
    d = bytearray(0xa0)
    struct.pack_into("<H", d, 0x9e, len(name))
    d += name.encode() + (b"\0" if len(name) & 1 else b"") + bytes([channel]) + bytes(40)
    return bytes(d)


def auco(name, fader, pan=64, mute=0):
    d = bytearray(0x98)
    d[0x3d:0x3d + len(name)] = name.encode()
    d[0x59], d[0x5a] = pan, mute
    struct.pack_into("<I", d, 0x74, int(fader * 2 ** 24))
    return bytes(d)


def aufl(name):
    n = name.encode("utf-16-le")
    d = bytearray(10)
    struct.pack_into("<H", d, 8, len(name))
    return bytes(d) + n + bytes(32)


def aurg(start, length, name):
    d = bytearray(0x4c)
    struct.pack_into("<Q", d, 6, start)
    struct.pack_into("<Q", d, 0x16, length)
    struct.pack_into("<H", d, 0x4a, len(name))
    return bytes(d) + name.encode() + bytes(64)


def place(tick, row, group, index, loop=0x3FFFFFFF):
    e = bytearray(80)
    e[0] = 0x24
    struct.pack_into("<I", e, 4, 34560 + tick)
    e[0x14] = row
    e[0x17] = 0x89
    struct.pack_into("<I", e, 0x1c, loop)
    struct.pack_into("<I", e, 0x28, index)
    struct.pack_into("<I", e, 0x2c, group)
    return bytes(e)


END = bytes([0xF1, 0, 0, 0, 0xFF, 0xFF, 0xFF, 0x3F]) + bytes(8)


def tempo_ev(bpm, *more):
    """Tempo events: `bpm` at beat 0, then (beat, bpm) pairs."""
    out = b""
    for beat, v in ((0, bpm),) + more:
        e = bytearray(32)
        e[0] = 0x60
        struct.pack_into("<I", e, 4, 38400 + int(beat * 960))
        struct.pack_into("<I", e, 0x10, int(v * 10000))
        out += bytes(e)
    return out + END


def plugin(name, position):
    d = bytearray(16)
    d[0], d[1], d[4] = 0x08, 0x01, 0x01
    struct.pack_into("<H", d, 6, position)
    return bytes(d) + name.encode() + bytes(40)


def make_logic(d, name="Song", tempos=(), places=None, regions=None, saved="test", audio=True, lead_row=False,
               extra=()):
    """Two tracks: "Bass" (-6 dB, panned left, a region at bar 2 and a looped one), "Pad" (muted), 100 BPM, 3/4.
    `tempos`: more (beat, bpm) changes; `places`: other placement events; `regions`: other AuRg records."""
    b = Path(d) / f"{name}.logicx"
    (b / "Media" / "Audio Files").mkdir(parents=True)
    alt = b / "Alternatives" / "000"
    alt.mkdir(parents=True)
    if audio:
        tone(b / "Media" / "Audio Files" / "bass.wav", seconds=6.0)
        tone(b / "Media" / "Audio Files" / "pad.wav", seconds=2.0)
    meter = bytearray(0x30)
    meter[0x0b], meter[0x0c] = 2, 3
    vbass = 90 * 10 ** (-6 / 40)
    body = b"".join([
        rec("MSeq", b"Tempo\0" + bytes(40), cls=3), rec("EvSq", tempo_ev(100.0, *tempos), cls=3),
        rec("EvSq", bytes(meter) + END, cls=1),
        rec("Envi", envi("Bass", 1), group=0x58), rec("Envi", envi("Pad", 2), group=0x5c),
        rec("AuCO", auco("Audio 1", vbass, pan=0), group=0x24, index=0),
        rec("AuCO", auco("Audio 2", 90.0, mute=1), group=0x24, index=1),
        rec("AuCU", plugin("Channel EQ", 0), group=0x24, index=0, sub=4),
        rec("AuCU", plugin("Compressor", 1), group=0x24, index=0, sub=5),
        rec("AuFl", aufl("bass.wav"), group=0), rec("AuRg", aurg(0, 6 * SR, "bass"), group=0, index=0),
        rec("AuRg", aurg(SR, 2 * SR, "bass.1"), group=0, index=1),
        rec("AuFl", aufl("pad.wav"), group=4), rec("AuRg", aurg(0, 2 * SR, "pad"), group=4, index=0),
        *(regions or []),
        rec("MSeq", b"TRASH\0" + bytes(40), cls=0x17, group=0),
        rec("MSeq", f"{name}\0".encode() + bytes(40), cls=0x17, group=4),
        *([rec("Trak", bytes([3]) + bytes(7) + struct.pack("<I", 0x50) + bytes(45))] if lead_row else []),
        rec("Trak", bytes([1]) + bytes(7) + struct.pack("<I", 0x58) + bytes(45)),
        rec("Trak", bytes([1]) + bytes(7) + struct.pack("<I", 0x5c) + bytes(45)),
        rec("Trak", bytes([3]) + bytes(7) + struct.pack("<I", 0x50) + bytes(45)),
        rec("EvSq", (places if places is not None else place(2880, 1, 0, 1) + place(4 * 2880, 1, 0, 0)
                     + place(0, 2, 4, 0, loop=8 * 960)) + END, cls=0x17, group=4),
        *extra,
    ])
    head = bytearray(24)
    head[0:4] = MAGIC
    struct.pack_into("<I", head, 0x10, len(body))
    (alt / "ProjectData").write_bytes(bytes(head) + body)
    import plistlib
    (alt / "MetaData.plist").write_bytes(plistlib.dumps(dict(SampleRate=SR, BeatsPerMinute=100,
                                                             SongSignatureNumerator=3, SongSignatureDenominator=4)))
    (b / "Resources").mkdir()
    (b / "Resources" / "ProjectInformation.plist").write_bytes(plistlib.dumps(dict(LastSavedFrom=saved)))
    return b


class LogicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="hx-imp-logic-"))
        cls.src = make_logic(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_fader_curve(self):
        self.assertAlmostEqual(20 * math.log10(import_logic.fader_gain(90)), 0.0)
        self.assertAlmostEqual(20 * math.log10(import_logic.fader_gain(127)), 5.98, places=2)
        self.assertAlmostEqual(20 * math.log10(import_logic.fader_gain(16.953)), -29.0, places=1)
        self.assertEqual(import_logic.fader_gain(0), 0.0)

    def test_reader(self):
        m = import_logic.read(self.src)
        self.assertEqual((m["bpm"], m["num"], m["den"], m["rate"]), (100.0, 3, 4, SR))
        bass, pad = m["tracks"]
        self.assertEqual((bass["name"], pad["name"]), ("Bass", "Pad"))
        self.assertAlmostEqual(20 * math.log10(bass["volume"]), -6.0, places=3)
        self.assertEqual(bass["pan"], -1.0)                                         # Logic's pan 0 = hard left
        self.assertTrue(pad["muted"])
        self.assertEqual(bass["plugins"], ["Channel EQ", "Compressor"])
        r = sorted(bass["regions"], key=lambda x: x["position"])
        self.assertAlmostEqual(r[0]["position"], 3 * 0.6, places=6)                 # beat 3 at 100 BPM
        self.assertAlmostEqual(r[0]["start"], 1.0)
        self.assertAlmostEqual(r[0]["length"], 2.0)
        self.assertAlmostEqual(r[1]["position"], 12 * 0.6, places=6)
        # the pad's 2 s region looped to 8 beats (4.8 s): passes at 0, 2, 4 s, the last cut to 0.8 s
        pr = sorted(pad["regions"], key=lambda x: x["position"])
        self.assertEqual([round(x["position"], 6) for x in pr], [0.0, 2.0, 4.0])
        self.assertAlmostEqual(pr[-1]["length"], 0.8, places=6)

    def test_full_import_reads_back(self):
        f, rep, summary = import_project.convert(self.src, self.tmp / "Song (HypnoMix)", log=lambda *a: None)
        self.assertIn(".logicx", summary)
        p = ardour.read(f)
        self.assertEqual([t.name for t in p.tracks if t.kind == "audio"], ["Bass", "Pad"])
        self.assertEqual(len(p.track("Pad").clips), 3)
        self.assertIn("Channel EQ, Compressor", rep.read_text(encoding="utf-8"))
        self.assertIn("looped region", rep.read_text(encoding="utf-8"))

    def test_refuses_damaged_data(self):
        bad = make_logic(self.tmp / "bad", "Bad")
        pd = bad / "Alternatives" / "000" / "ProjectData"
        pd.write_bytes(pd.read_bytes()[:-7])
        with self.assertRaises(SystemExit):
            import_logic.read(bad)
        with self.assertRaises(SystemExit):
            import_project.convert(bad, self.tmp / "bad-out", log=lambda *a: None)
        self.assertFalse((self.tmp / "bad-out").exists())

    def test_never_inside_the_project(self):
        with self.assertRaises(SystemExit):
            import_project.convert(self.src, self.src / "inside", log=lambda *a: None)


# ---------------------------------------------------------------- .ptx sessions and AAF, through stand-in readers
STAND_IN_CAP = 16 << 20         # what a stand-in reader may write to any one file (the OS stops it past this)


def stand_in(d, name, payload=None, body=None):
    """A program printing `payload` (what the engine's reader prints) in place of the real reader, or running
    `body`. Its first line caps every file it writes at STAND_IN_CAP (RLIMIT_FSIZE), before anything else runs."""
    p = Path(d) / name
    code = body if body is not None else f"sys.stdout.write({json.dumps(json.dumps(payload))})"
    if os.name == "nt":
        # Windows starts no file by its #! line and has no rlimits: the stand-in is a .py that this Python runs from a
        # .cmd beside it (what the reader's path names), and the bodies here are small and known
        py = p.with_name(name + ".py")
        py.write_text(f"import sys, os, json, time\n{code}\n", encoding="utf-8")
        cmd = p.with_name(name + ".cmd")
        cmd.write_bytes(f'@"{sys.executable}" "{py}" %*\r\n@exit /b %ERRORLEVEL%\r\n'.encode("utf-8"))
        return cmd
    p.write_text(f"#!{sys.executable}\nimport resource, sys, os, json, time\n"
                 f"resource.setrlimit(resource.RLIMIT_FSIZE, ({STAND_IN_CAP}, {STAND_IN_CAP}))\n{code}\n", encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


class EngineReadersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hx-imp-pt-"))
        self.env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ptx(self):
        sess = self.tmp / "Song"
        (sess / "Audio Files").mkdir(parents=True)
        tone(sess / "Audio Files" / "Gtr_01.L.wav", channels=1)
        tone(sess / "Audio Files" / "Gtr_01.R.wav", channels=1)
        tone(sess / "Audio Files" / "Vox_01.wav", channels=1)
        ptx = sess / "Song.ptx"
        ptx.write_bytes(b"\x03" + bytes(63))
        reg = lambda f, s: dict(name=f[:-4], index=0, start=s, offset=SR // 2, length=SR, file=f, file_index=0)
        os.environ["HYPNOMIX_PTDUMP"] = str(stand_in(self.tmp, "ptdump", dict(
            format="ptx", version=12, rate=SR, audiofiles=[], miditracks=[
                dict(name="Keys", index=3, playlist=0, region=dict(name="k", index=0, start=1920000, offset=0,
                                                                   length=960000, notes=[[0, 480000, 60, 100]]))],
            tracks=[dict(name="Gtr.L", index=0, playlist=0, region=reg("Gtr_01.L.wav", SR)),
                    dict(name="Gtr.R", index=1, playlist=0, region=reg("Gtr_01.R.wav", SR)),
                    dict(name="Vox", index=2, playlist=0, region=reg("Vox_01.wav", 2 * SR))])))
        self.assertEqual(import_project.kind_of(ptx), "ptx")
        f, rep, summary = import_project.convert(ptx, self.tmp / "out", log=lambda *a: None)
        p = ardour.read(f)
        gtr = p.track("Gtr")
        self.assertEqual(len(gtr.clips), 1)                                   # the .L / .R halves are one region
        self.assertEqual(len(gtr.clips[0].take.extra_paths), 1)
        self.assertAlmostEqual(gtr.clips[0].start, 1.0, places=4)
        self.assertAlmostEqual(gtr.clips[0].take.offset, 0.5, places=4)
        self.assertAlmostEqual(p.track("Vox").clips[0].start, 2.0, places=4)
        self.assertIn("MIDI", summary)
        self.assertIn("fader, pan, mute", rep.read_text(encoding="utf-8"))

    def test_ptx_reader_error_is_plain(self):
        (self.tmp / "Bad").mkdir()
        ptx = self.tmp / "Bad" / "Bad.ptx"
        ptx.write_bytes(b"\x03" + bytes(63))
        os.environ["HYPNOMIX_PTDUMP"] = str(stand_in(self.tmp, "ptdump", dict(error="could not decrypt the session")))
        with self.assertRaises(SystemExit) as cm:
            import_project.convert(ptx, self.tmp / "out", log=lambda *a: None)
        self.assertIn("could not decrypt", str(cm.exception))

    def test_reader_missing(self):
        from hypnomix.project import engine_tools
        os.environ["HYPNOMIX_PTDUMP"] = str(self.tmp / "nothing-here")
        os.environ.pop("HYPNOMIX_ENGINE_SRC", None)
        os.environ["PATH"] = str(self.tmp)
        os.environ["HYPNOMIX_ENGINE"] = str(self.tmp / "no-engine")
        with self.assertRaises(engine_tools.ToolMissing):
            engine_tools.find("hypnomix-ptdump")

    def test_aaf(self):
        a = self.tmp / "Mix.aaf"
        a.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(56))
        l, r = tone(self.tmp / "a_L.wav", channels=1), tone(self.tmp / "a_R.wav", channels=1)
        mono = tone(self.tmp / "b.wav", channels=1)
        os.environ["HYPNOMIX_AAFDUMP"] = str(stand_in(self.tmp, "aafdump", dict(
            format="aaf", rate=SR, name="Mix", product="Some Editor", markers=[dict(name="Chorus", start=SR, length=0)],
            tracks=[dict(name="Music", number=1, channels=2, mute=0, solo=0, gain=dict(value=0.5), pan=dict(value=0.0),
                         clips=[dict(position=SR, length=SR, offset=0, mute=0, name="m", gain=dict(value=2.0),
                                     envelope=None, fade_in=dict(length=4800, shape="linear"),
                                     files=[dict(path=str(l), channel=0), dict(path=str(r), channel=0)])]),
                    dict(name="Dialog", number=2, channels=1, mute=1, solo=0, gain=None, pan=None,
                         clips=[dict(position=0, length=SR // 2, offset=SR, mute=1, name="d", gain=None,
                                     envelope=dict(points=[[0, 1.0], [1, 0.5]]), files=[dict(path=str(mono))])])])))
        self.assertEqual(import_project.kind_of(a), "aaf")
        f, rep, summary = import_project.convert(a, self.tmp / "out", log=lambda *a: None)
        root, routes = route_by_name(f)
        self.assertAlmostEqual(gain_of(routes["Music"]), 0.5)
        pan = [c for c in routes["Music"].iter("Controllable") if c.get("name") == "pan-azimuth"][0]
        self.assertAlmostEqual(float(pan.get("value")), 0.0)
        p = ardour.read(f)
        m = p.track("Music").clips[0]
        self.assertAlmostEqual(m.start, 1.0, places=4)
        self.assertAlmostEqual(m.level, 2.0, places=4)
        self.assertAlmostEqual(m.fade_in, 0.1, places=3)
        d = p.track("Dialog").clips[0]
        self.assertTrue(d.muted)
        self.assertAlmostEqual(d.take.offset, 1.0, places=4)
        self.assertTrue(d.envelope)
        self.assertIn("Some Editor (AAF)", summary)


# ---------------------------------------------------------------- detection, the writer's checks, the app's job
class ShapeTest(unittest.TestCase):
    def test_kind_of(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "x.rpp").write_text("<REAPER_PROJECT 0.1\n>\n", encoding="utf-8")
            self.assertEqual(import_project.kind_of(d / "x.rpp"), "reaper")
            (d / "renamed.txt").write_text("<REAPER_PROJECT 0.1\n>\n", encoding="utf-8")
            self.assertEqual(import_project.kind_of(d / "renamed.txt"), "reaper")
            (d / "Y.logicx" / "Alternatives").mkdir(parents=True)
            self.assertEqual(import_project.kind_of(d / "Y.logicx"), "logicx")
            (d / "z.bin").write_bytes(b"nothing")
            self.assertIsNone(import_project.kind_of(d / "z.bin"))
            with self.assertRaises(SystemExit):
                import_project.convert(d / "z.bin", d / "out", log=lambda *a: None)

    def test_tempo_points(self):
        self.assertEqual(importer.tempo_points(120, []), [(0.0, 120.0)])
        self.assertEqual(importer.tempo_points(120, [(0, 100), (4, 140)]), [(0.0, 100.0), (4.0, 100.0), (4.0, 140.0)])

    def test_out_must_be_empty(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src = make_dawproject(d)
            (d / "full").mkdir()
            (d / "full" / "keep.txt").write_text("mine", encoding="utf-8")
            with self.assertRaises(SystemExit):
                import_project.convert(src, d / "full", log=lambda *a: None)
            self.assertEqual((d / "full" / "keep.txt").read_text(encoding="utf-8"), "mine")


class AppJobTest(unittest.TestCase):
    def test_import_job(self):
        from hypnomix.app import daw
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src = make_dawproject(d)
            self.assertEqual(daw.import_out(src), d / "song (HypnoMix)")
            st = daw.import_start(str(src))
            for _ in range(600):
                cur = daw.import_status(st["job"])
                if cur["state"] != "running":
                    break
                time.sleep(0.1)
            self.assertEqual(cur["state"], "done", cur.get("error"))
            self.assertTrue(Path(cur["session"]).is_file())
            self.assertIn("Import report", cur["report"])
            self.assertEqual(daw.import_status("nope")["state"], "unknown")
            with self.assertRaises(ValueError):
                daw.import_start(str(d / "missing.als"))


class ReaperTest(unittest.TestCase):
    def test_reaper(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            proj = d / "proj"
            proj.mkdir()
            tone(proj / "gtr.wav", seconds=4.0)
            item = lambda pos, soffs, mute: (f"    <ITEM\n      POSITION {pos}\n      LENGTH 1.5\n      LOOP 0\n"
                                             f"      FADEIN 1 0.2 0 1 0 0 0\n      FADEOUT 1 0 0 1 0 0 0\n      MUTE {mute} 0\n"
                                             f"      NAME gtr\n      VOLPAN 0.5 0 1 -1\n      SOFFS {soffs}\n"
                                             f"      PLAYRATE 1 1 0 -1 0 0.0025\n      <SOURCE WAVE\n        FILE \"gtr.wav\"\n      >\n    >\n")
            (proj / "song.rpp").write_text(
                "<REAPER_PROJECT 0.1 \"7.86/macOS-arm64\" 1764000000\n  TEMPO 90 4 4\n  SAMPLERATE 48000 0 0\n"
                "  <TRACK\n    NAME \"Group\"\n    VOLPAN 0.5 0 -1 -1 1\n    MUTESOLO 0 0 0\n    ISBUS 1 1\n  >\n"
                "  <TRACK\n    NAME \"Gtr\"\n    VOLPAN 1 -0.5 -1 -1 1\n    MUTESOLO 1 0 0\n    ISBUS 2 -1\n"
                + item(1.0, 0.5, 0) + item(3.0, 0, 1) + "  >\n>\n", encoding="utf-8")
            f, rep, summary = import_project.convert(proj / "song.rpp", d / "out", log=lambda *a: None)
            root, routes = route_by_name(f)
            self.assertEqual(list(routes), ["Master", "Group", "Gtr"])
            out = [io for io in routes["Gtr"].iter("IO") if io.get("direction") == "Output"][0]
            self.assertIn("Group/audio_in 1", [c.get("other") for c in out.iter("Connection")])
            self.assertAlmostEqual(gain_of(routes["Group"]), 0.5)
            p = ardour.read(f)
            c = p.track("Gtr").clips
            self.assertEqual([round(x.start, 4) for x in c], [1.0, 3.0])
            self.assertAlmostEqual(c[0].take.offset, 0.5, places=4)
            self.assertAlmostEqual(c[0].level, 0.5, places=4)
            self.assertAlmostEqual(c[0].fade_in, 0.2, places=3)
            self.assertTrue(c[1].muted)
            self.assertIn(".rpp project", summary)


# ---------------------------------------------------------------- the review's findings, one test (or more) each
# Bounded inputs: every input a test builds here is small and built directly (no string doubled per level, no
# repeated growth). INPUT_CAP is checked by the builders below, so a mistake fails at once instead of filling memory.
INPUT_CAP = 8 << 20


def capped(data):
    assert len(data) < INPUT_CAP, f"a test input of {len(data)} bytes: keep test inputs under {INPUT_CAP >> 20} MB"
    return data


def dp_zip(d, xml, files=None, name="t.dawproject", deflate=False):
    """A .dawproject at d/name holding `xml` and {member: source file or bytes} (each under INPUT_CAP)."""
    p = Path(d) / name
    kind = zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED
    with zipfile.ZipFile(p, "w", compression=kind) as z:
        z.writestr("project.xml", capped(xml))
        for member, src in (files or {}).items():
            if isinstance(src, bytes):
                z.writestr(member, capped(src))
            else:
                z.write(src, member)
    return p


def dp_xml(structure, lanes, tempo=120, arr=""):
    return (f'<?xml version="1.0" encoding="UTF-8"?><Project version="1.0"><Application name="Test Host" version="1"/>'
            f'<Transport><Tempo unit="bpm" value="{tempo}"/><TimeSignature numerator="4" denominator="4"/></Transport>'
            f'<Structure>{structure}<Channel role="master" id="cm"><Volume unit="linear" value="1"/></Channel>'
            f'</Structure><Arrangement>{arr}<Lanes timeUnit="beats">{lanes}</Lanes></Arrangement></Project>')


def dp_track(name, tid, kind="audio", channel="", dest="cm", role="regular", kids=""):
    return (f'<Track contentType="{kind}" name="{name}" id="{tid}"><Channel role="{role}" id="c{tid}" '
            f'destination="{dest}">{channel}</Channel>{kids}</Track>')


AUDIO = '<Audio channels="2" sampleRate="48000" duration="4"><File path="audio/a.wav"/></Audio>'


def quiet(*a):
    pass


class DAWprojectFindingsTest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="hx-imp-dp2-"))
        self.wav = tone(self.d / "a.wav")
        from hypnomix.project import import_dawproject
        self.M = import_dawproject

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def model(self, xml, files=None):
        p = dp_zip(self.d, xml, {"audio/a.wav": self.wav} if files is None else files)
        return self.M.read(p, self.d / "media")

    def lanes(self, clips, tid="t1"):
        return f'<Lanes track="{tid}"><Clips>{clips}</Clips></Lanes>'

    def test_loop_with_content_in_seconds(self):                 # finding 4
        m = self.model(dp_xml(dp_track("A", "t1"), self.lanes(
            f'<Clip time="0" duration="4" contentTimeUnit="seconds" playStart="0" loopStart="0" loopEnd="1">{AUDIO}</Clip>')))
        r = m["tracks"][0]["regions"]
        self.assertEqual([(round(x["position"], 6), round(x["length"], 6), round(x["start"], 6)) for x in r],
                         [(0.0, 1.0, 0.0), (1.0, 1.0, 0.0)])          # 4 beats at 120 = 2 s: two 1 s passes

    def test_clips_time_unit_and_notes_in_seconds(self):          # finding 5
        m = self.model(dp_xml(dp_track("A", "t1") + dp_track("K", "t2", "notes"),
                              '<Lanes track="t1"><Clips timeUnit="seconds"><Clip time="3" duration="1">'
                              f'{AUDIO}</Clip></Clips></Lanes>' + self.lanes(
                                  '<Clip time="0" duration="8" contentTimeUnit="seconds"><Notes><Note time="1" '
                                  'duration="0.5" key="60" vel="0.5"/></Notes></Clip>', "t2")))
        a, k = m["tracks"]
        self.assertAlmostEqual(a["regions"][0]["position"], 3.0)
        n = k["midi"][0]["notes"][0]
        self.assertAlmostEqual(n[0], 2.0, places=4)                  # 1 s at 120 BPM = beat 2
        self.assertAlmostEqual(n[1], 1.0, places=4)

    def test_warps_after_a_tempo_change(self):                    # finding 6
        arr = ('<TempoAutomation unit="bpm" timeUnit="beats"><RealPoint time="0" value="120" interpolation="hold"/>'
               '<RealPoint time="4" value="60" interpolation="hold"/></TempoAutomation>')
        m = self.model(dp_xml(dp_track("A", "t1"), self.lanes(
            '<Clip time="8" duration="4" contentTimeUnit="beats"><Warps timeUnit="beats" contentTimeUnit="seconds">'
            f'{AUDIO}<Warp time="0" contentTime="0"/><Warp time="4" contentTime="4"/></Warps></Clip>'), arr=arr))
        self.assertFalse([x for x in m["not_carried"] if "speed" in x], m["not_carried"])
        self.assertAlmostEqual(m["tracks"][0]["regions"][0]["position"], 2.0 + 4.0)

    def test_audio_and_notes_on_one_track(self):                  # finding 26a
        p = dp_zip(self.d, dp_xml(dp_track("Kick", "t1", "audio notes"), self.lanes(
            f'<Clip time="0" duration="4">{AUDIO}</Clip><Clip time="4" duration="4"><Notes><Note time="0" '
            'duration="1" key="36" vel="1"/></Notes></Clip>')), {"audio/a.wav": self.wav})
        f, rep, _ = import_project.convert(p, self.d / "out", log=quiet)
        root, routes = route_by_name(f)
        self.assertIn("Kick", routes)
        self.assertIn("Kick (MIDI)", routes)
        self.assertEqual(len(ardour.read(f).track("Kick").clips), 1)

    def test_two_buses_of_one_name(self):                         # finding 10
        kid = lambda n, i, dest: dp_track(n, i, dest=dest)            # noqa: E731
        st = (dp_track("Group", "g1", "tracks", role="submix", kids=kid("A", "a", "cg1"))
              + dp_track("Group", "g2", "tracks", role="submix", kids=kid("B", "b", "cg2")))
        p = dp_zip(self.d, dp_xml(st, self.lanes(f'<Clip time="0" duration="2">{AUDIO}</Clip>', "a")
                                  + self.lanes(f'<Clip time="0" duration="2">{AUDIO}</Clip>', "b")),
                   {"audio/a.wav": self.wav})
        f, _, _ = import_project.convert(p, self.d / "out", log=quiet)
        root, routes = route_by_name(f)
        outs = {n: [c.get("other") for io in routes[n].iter("IO") if io.get("direction") == "Output"
                    for c in io.iter("Connection")] for n in ("A", "B")}
        self.assertIn("Group/audio_in 1", outs["A"])
        self.assertIn("Group 2/audio_in 1", outs["B"])

    def test_zip_names(self):                                     # finding 13
        z = self.M.zip_name
        self.assertEqual(z("audio/a.wav"), "audio/a.wav")
        for bad in ("D:/x.wav", "\\\\server\\share\\x.wav", "\\Windows\\x.wav", "../x.wav", "a/../../x.wav", ""):
            self.assertIsNone(z(bad), bad)

    def test_zip_slip_member_is_left_out(self):                   # findings 13, 34
        xml = dp_xml(dp_track("A", "t1"), self.lanes(
            '<Clip time="0" duration="2"><Audio channels="2" sampleRate="48000" duration="4">'
            '<File path="../../zipslip.wav"/></Audio></Clip>'))
        p = dp_zip(self.d, xml, {"../../zipslip.wav": self.wav})
        f, rep, _ = import_project.convert(p, self.d / "sub" / "out", log=quiet)
        self.assertFalse(list(self.d.parent.glob("zipslip.wav")) + list(self.d.glob("zipslip.wav")))
        self.assertIn("not a plain zip path", rep.read_text(encoding="utf-8"))

    def test_not_audio_member_is_not_unpacked(self):              # finding 18
        m = self.model(dp_xml(dp_track("A", "t1"), self.lanes(f'<Clip time="0" duration="2">{AUDIO}</Clip>')),
                       {"audio/a.wav": b"#!/bin/sh\necho not audio\n" * 100})
        self.assertTrue(any("not an audio file" in x for x in m["not_carried"]))
        self.assertFalse((self.d / "media" / "audio" / "a.wav").exists())

    def test_zip_ratio_refused(self):                             # finding 18
        zeros = b"RIFF" + bytes(1 << 20)                            # 1 MB that deflates to about 1 KB (over 200x)
        p = dp_zip(self.d, dp_xml(dp_track("A", "t1"), self.lanes(f'<Clip time="0" duration="2">{AUDIO}</Clip>')),
                   {"audio/a.wav": zeros}, deflate=True)
        with mock.patch.object(self.M, "RATIO_FLOOR", 0):
            m = self.M.read(p, self.d / "media")                     # that file is left out, not the project
        self.assertTrue(any("its packed size" in x for x in m["not_carried"]), m["not_carried"])
        self.assertFalse((self.d / "media" / "audio" / "a.wav").exists())

    def test_doctype_refused(self):                               # finding 17
        xml = ('<?xml version="1.0"?><!DOCTYPE p [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
               '<Project><Structure/></Project>')
        with self.assertRaises(SystemExit) as cm:
            self.model(xml, {})
        self.assertIn("DTD", str(cm.exception))

    def test_deeply_nested_clips_stop_quickly(self):              # finding 14
        def nest(n):                    # one clip in another, n deep (linear size: about 120 bytes a level); the
            #                             old walk of every clip below cost 2^n time, never the input itself
            inner = f'<Clip time="0" duration="4">{AUDIO}</Clip>'
            for _ in range(n):
                inner = f'<Clip time="0" duration="4"><Lanes><Clips>{inner}</Clips></Lanes></Clip>'
            return inner
        t0 = time.monotonic()
        m = self.model(dp_xml(dp_track("A", "t1"), self.lanes(nest(30))))
        self.assertEqual(len(m["tracks"][0]["regions"]), 1)
        self.assertLess(time.monotonic() - t0, 10)
        with self.assertRaises(SystemExit):
            self.model(dp_xml(dp_track("A", "t1"), self.lanes(nest(40))))

    def test_tiny_loop_placed_once(self):                         # finding 16
        m = self.model(dp_xml(dp_track("A", "t1"), self.lanes(
            '<Clip time="0" duration="64" contentTimeUnit="seconds" playStart="0" loopStart="0" loopEnd="0.001">'
            f'{AUDIO}</Clip>')))
        self.assertEqual(len(m["tracks"][0]["regions"]), 1)
        self.assertTrue(any("placed once" in x for x in m["not_carried"]))

    def test_not_numbers_are_limited(self):                       # finding 21
        xml = dp_xml(dp_track("A", "t1", channel='<Volume unit="linear" value="nan"/><Pan unit="normalized" '
                                                  'value="7"/>'), self.lanes(f'<Clip time="0" duration="2">{AUDIO}</Clip>'),
                     tempo="inf")
        p = dp_zip(self.d, xml, {"audio/a.wav": self.wav})
        f, rep, _ = import_project.convert(p, self.d / "out", log=quiet)
        text = f.read_text(encoding="utf-8")
        self.assertNotIn('"nan"', text.lower())
        self.assertNotIn('"inf"', text.lower())
        self.assertIn("limited", rep.read_text(encoding="utf-8"))

    def test_loud_fader_is_said(self):                            # finding 7
        p = dp_zip(self.d, dp_xml(dp_track("A", "t1", channel='<Volume unit="decibel" value="12"/>'),
                                  self.lanes(f'<Clip time="0" duration="2">{AUDIO}</Clip>')), {"audio/a.wav": self.wav})
        f, rep, _ = import_project.convert(p, self.d / "out", log=quiet)
        root, routes = route_by_name(f)
        self.assertAlmostEqual(gain_of(routes["A"]), 2.0)
        self.assertIn("was +12.00 dB in the project: set to +6.02 dB", rep.read_text(encoding="utf-8"))

    def test_line_breaks_in_names(self):                          # finding 22 (XML itself refuses &#1;)
        p = dp_zip(self.d, dp_xml(dp_track("Bad&#9;Name&#10;## Fake heading | x", "t1"),
                                  self.lanes(f'<Clip time="0" duration="2">{AUDIO}</Clip>')), {"audio/a.wav": self.wav})
        f, rep, _ = import_project.convert(p, self.d / "out", log=quiet)
        import xml.etree.ElementTree as ET
        ET.parse(f)
        self.assertFalse([ln for ln in rep.read_text(encoding="utf-8").splitlines() if ln.startswith("## Fake")])
        self.assertIn("Bad Name ## Fake heading \\| x", rep.read_text(encoding="utf-8"))

    def test_too_many_tracks_refused(self):                       # finding 23
        st = "".join(dp_track(f"T{i}", f"t{i}") for i in range(importer.MAX_TRACKS + 1))   # about 250 KB
        p = dp_zip(self.d, dp_xml(st, ""), {})
        with self.assertRaises(SystemExit) as cm:
            import_project.convert(p, self.d / "out", log=quiet)
        self.assertIn("tracks", str(cm.exception))
        self.assertFalse((self.d / "out").exists())

    def test_missing_and_past_the_end(self):                      # findings 9, 34 (left-out report)
        xml = dp_xml(dp_track("A", "t1"), self.lanes(
            '<Clip time="0" duration="2"><Audio channels="2" sampleRate="48000" duration="4"><File path="audio/gone.wav"/>'
            '</Audio></Clip>'
            '<Clip time="4" duration="2" contentTimeUnit="seconds" playStart="10">' + AUDIO + '</Clip>'
            '<Clip time="8" duration="8" contentTimeUnit="seconds" playStart="3">' + AUDIO + '</Clip>'))
        p = dp_zip(self.d, xml, {"audio/a.wav": self.wav})
        f, rep, summary = import_project.convert(p, self.d / "out", log=quiet)
        text = rep.read_text(encoding="utf-8")
        self.assertIn("## Left out: audio not found or not usable", text)
        self.assertIn("gone.wav", text)
        self.assertIn("starts 10.00 s into", text)
        self.assertIn("shortened to the file", text)
        self.assertIn("## Track notes", text)
        self.assertIn("2 left out", summary)
        self.assertIn("## Not checked", text)

    def test_overlong_files_are_left_out_only_when_converted(self):   # findings 19, n14
        from hypnomix.project import als2ardour as A
        slow = tone(self.d / "slow.wav", sr=44100)
        xml = dp_xml(dp_track("A", "t1"), self.lanes(f'<Clip time="0" duration="2">{AUDIO}</Clip>'
                                                     '<Clip time="4" duration="2"><Audio channels="2" sampleRate="44100" '
                                                     'duration="4"><File path="audio/slow.wav"/></Audio></Clip>'))
        p = dp_zip(self.d, xml, {"audio/a.wav": self.wav, "audio/slow.wav": slow})
        with mock.patch.object(A, "MAX_FILE_SECONDS", 1):
            f, rep, _ = import_project.convert(p, self.d / "out", sr=48000, log=quiet)
        text = rep.read_text(encoding="utf-8")
        self.assertIn("slow.wav", text)
        self.assertIn("hours long", text)                           # converted: the cap applies
        self.assertEqual(len(ardour.read(f).track("A").clips), 1)   # same rate: copied in blocks, any length

    def test_master_solo_fades_meter_sends(self):                 # finding 34 (DAWproject asserts)
        src = make_dawproject(self.d)
        f, rep, _ = import_project.convert(src, self.d / "out", log=quiet)
        root, routes = route_by_name(f)
        self.assertAlmostEqual(gain_of(routes["Master"]), 0.5)
        p = ardour.read(f)
        self.assertTrue(p.track("Vox").solo)
        k = p.track("Kick").clips[0]
        self.assertAlmostEqual(k.fade_in, 0.01, places=3)
        self.assertAlmostEqual(k.fade_out, 0.05, places=3)
        self.assertEqual(p.beats_per_bar, 3)
        send = [pr for pr in routes["Kick"].iter("Processor") if pr.get("type") == "intsend"][0]
        self.assertTrue(any(abs(float(c.get("value")) - 0.25) < 1e-6 for c in send.iter("Controllable")
                            if c.get("name") == "gaincontrol"))


def rpp(proj, body, head=""):
    (proj / "song.rpp").write_text('<REAPER_PROJECT 0.1 "7.86/macOS-arm64" 1764000000\n' + head + body + ">\n", encoding="utf-8")
    return proj / "song.rpp"


def rpp_item(pos, file="gtr.wav", length=1.5, extra="", takes=""):
    return (f"    <ITEM\n      POSITION {pos}\n      LENGTH {length}\n{extra}      NAME it\n"
            f"      <SOURCE WAVE\n        FILE \"{file}\"\n      >\n{takes}    >\n")


class ReaperFindingsTest(unittest.TestCase):                    # findings 8, 15, 20, 34
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="hx-imp-rpp-"))
        self.proj = self.d / "proj"
        self.proj.mkdir()
        tone(self.proj / "gtr.wav", seconds=4.0)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_markers_master_meter_tempo_takes_folders(self):
        other = '      TAKE\n      NAME b\n      <SOURCE WAVE\n        FILE "gtr.wav"\n      >\n'
        src = rpp(self.proj,
                  '  <TRACK\n    NAME "Group"\n    ISBUS 1 1\n' + rpp_item(5.0) + "  >\n"
                  '  <TRACK\n    NAME "Gtr"\n    VOLPAN 1 -0.5 -1 -1 1\n    MUTESOLO 1 2 0\n    ISBUS 2 -1\n'
                  + rpp_item(1.0, extra="      LOOP 1\n      FADEOUT 0 0.3 0 1 0 0 0\n", takes=other) + "  >\n",
                  head="  TEMPO 90 6 8\n  SAMPLERATE 48000 0 0\n  MASTER_VOLUME 0.5 0 -1 -1 1\n"
                       "  <TEMPOENVEX\n    ACT 1 -1\n    PT 0 90 1\n    PT 4 120 1\n  >\n"
                       '  MARKER 1 2.5 "Verse" 0 0 1\n  MARKER 2 4 "Chorus" 1 0 1\n  MARKER 2 8 "" 1 0 1\n')
        from hypnomix.project import import_reaper
        m = import_reaper.read(src)
        gtr = [t for t in m["tracks"] if t["name"] == "Gtr"][0]
        self.assertEqual((gtr["pan"], gtr["muted"], gtr["solo"]), (-0.5, True, True))
        f, rep, _ = import_project.convert(src, self.d / "out", log=quiet)
        text = rep.read_text(encoding="utf-8")
        root, routes = route_by_name(f)
        self.assertAlmostEqual(gain_of(routes["Master"]), 0.5)
        self.assertIn("Group (items)", routes)
        out = [c.get("other") for io in routes["Group (items)"].iter("IO") if io.get("direction") == "Output"
               for c in io.iter("Connection")]
        self.assertIn("Group/audio_in 1", out)
        import xml.etree.ElementTree as ET
        locs = {l.get("name"): l.get("flags") for l in root.iter("Location")}
        self.assertEqual((locs.get("Verse"), locs.get("Chorus")), ("IsMark", "IsRangeMarker"))
        self.assertEqual([float(t.get("npm")) for t in root.iter("Tempo")], [90.0, 120.0])
        self.assertIn("time signature 6/8", text)
        self.assertIn("1 other take(s)", text)
        self.assertNotIn("looped item", text)                       # LOOP 1 on an item shorter than its file
        pan = [c for c in routes["Gtr"].iter("Controllable") if c.get("name") == "pan-azimuth"][0]
        self.assertAlmostEqual(float(pan.get("value")), 0.25, places=6)
        self.assertAlmostEqual(ardour.read(f).track("Gtr").clips[0].fade_out, 0.3, places=3)

    def test_control_characters_in_names(self):                   # finding 22
        src = rpp(self.proj, '  <TRACK\n    NAME "Bad\x01Name\x1b"\n' + rpp_item(0) + "  >\n")
        f, rep, _ = import_project.convert(src, self.d / "out", log=quiet)
        import xml.etree.ElementTree as ET
        ET.parse(f)                                                  # well-formed
        self.assertIn("BadName", rep.read_text(encoding="utf-8"))

    def test_unreal_sample_rate(self):
        src = rpp(self.proj, '  <TRACK\n    NAME "Gtr"\n' + rpp_item(0) + "  >\n", head="  SAMPLERATE 1 0 0\n")
        f, rep, _ = import_project.convert(src, self.d / "out", log=quiet)
        self.assertIn("not a real one", rep.read_text(encoding="utf-8"))
        self.assertIn('sample-rate="48000"', f.read_text(encoding="utf-8"))
        with self.assertRaises(SystemExit):
            import_project.convert(src, self.d / "out2", sr=5, log=quiet)
        self.assertFalse((self.d / "out2").exists())

    def test_audio_outside_the_project(self):
        elsewhere = Path(tempfile.mkdtemp(prefix="hx-imp-else-"))
        try:
            secret = tone(elsewhere / "private.wav")
            src = rpp(self.proj, '  <TRACK\n    NAME "Gtr"\n' + rpp_item(0, file=str(secret)) + "  >\n")
            f, rep, _ = import_project.convert(src, self.d / "out", log=quiet)
            self.assertIn("## Left out: audio from outside the project", rep.read_text(encoding="utf-8"))
            self.assertIn("private.wav", rep.read_text(encoding="utf-8"))
            self.assertEqual(ardour.read(f).track("Gtr").clips, [])
            f, rep, _ = import_project.convert(src, self.d / "out2", allow_outside=True, log=quiet)
            self.assertEqual(len(ardour.read(f).track("Gtr").clips), 1)
        finally:
            shutil.rmtree(elsewhere, ignore_errors=True)

    def test_default_folder_and_the_job(self):                    # finding 1 (the blocker)
        from hypnomix.app import daw
        src = rpp(self.proj, '  <TRACK\n    NAME "Gtr"\n' + rpp_item(0) + "  >\n")
        self.assertEqual(daw.import_out(src), self.d / "song (HypnoMix)")
        st = daw.import_start(str(src))
        for _ in range(600):
            cur = daw.import_status(st["job"])
            if cur["state"] != "running":
                break
            time.sleep(0.1)
        self.assertEqual(cur["state"], "done", cur.get("error"))
        self.assertTrue(Path(cur["session"]).is_file())

    def test_inside_the_project_refused(self):
        src = rpp(self.proj, '  <TRACK\n    NAME "Gtr"\n' + rpp_item(0) + "  >\n")
        with self.assertRaises(SystemExit) as cm:
            import_project.convert(src, self.proj / "out", log=quiet)
        self.assertIn("inside the project", str(cm.exception))


class LogicFindingsTest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="hx-imp-lg-"))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_tempo_change_places_audio_on_the_written_map(self):  # finding 2
        b = make_logic(self.d, tempos=((8, 200.0),), places=place(12 * 960, 1, 0, 0))
        m = import_logic.read(b)
        self.assertAlmostEqual(m["tracks"][0]["regions"][0]["position"], 8 * 0.6 + 4 * 0.3, places=6)
        f, rep, _ = import_project.convert(b, self.d / "out", log=quiet)
        import xml.etree.ElementTree as ET
        self.assertEqual([float(t.get("npm")) for t in ET.parse(f).getroot().iter("Tempo")], [100.0, 200.0])
        self.assertAlmostEqual(ardour.read(f).track("Bass").clips[0].start, 6.0, places=4)

    def test_missing_file_never_taken_from_the_current_folder(self):   # finding 11
        b = make_logic(self.d, audio=False)
        cwd = Path(tempfile.mkdtemp(prefix="hx-imp-cwd-"))
        here = os.getcwd()
        try:
            tone(cwd / "bass.wav")
            os.chdir(cwd)
            f, rep, _ = import_project.convert(b, self.d / "out", log=quiet)
        finally:
            os.chdir(here)
            shutil.rmtree(cwd, ignore_errors=True)
        self.assertEqual(ardour.read(f).track("Bass").clips, [])
        self.assertIn("bass.wav", rep.read_text(encoding="utf-8"))

    def test_tiny_loop_and_report_lines(self):                     # findings 16, 26c, 26d, 32
        b = make_logic(self.d, regions=[rec("AuRg", aurg(0, 10, "tiny"), group=0, index=2)],
                       places=place(0, 1, 0, 2, loop=8 * 960))
        m = import_logic.read(b)
        self.assertEqual(len(m["tracks"][0]["regions"]), 1)
        text = " ".join(m["not_carried"] + m["warnings"])
        self.assertIn("placed once", text)
        self.assertIn("track row(s) of another kind", text)
        self.assertIn("markers: not read", text)
        self.assertIn("checked on packages saved by version 10.7", text)
        ok = make_logic(self.d / "ok", saved="X 10.7.4 (5762)")
        self.assertFalse([w for w in import_logic.read(ok)["warnings"] if "checked on" in w])


class EngineReaderFindingsTest(unittest.TestCase):               # findings 3, 12, 24, 25, 27, 34
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hx-imp-pt2-"))
        self.env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def no_engine(self):
        os.environ["HYPNOMIX_PTDUMP"] = str(self.tmp / "nothing-here")
        os.environ["HYPNOMIX_AAFDUMP"] = str(self.tmp / "nothing-here")
        os.environ.pop("HYPNOMIX_ENGINE_SRC", None)
        os.environ["PATH"] = str(self.tmp)
        os.environ["HYPNOMIX_ENGINE"] = str(self.tmp / "no-engine")

    def test_no_reader_is_one_sentence(self):
        self.no_engine()
        (self.tmp / "S").mkdir()
        ptx = self.tmp / "S" / "S.ptx"
        ptx.write_bytes(b"\x03" + bytes(63))
        with self.assertRaises(SystemExit) as cm:
            import_project.convert(ptx, self.tmp / "out", log=quiet)
        self.assertIn("HypnoMix DAW add-on", str(cm.exception))
        with self.assertRaises(SystemExit):
            import_project.convert(self.tmp / "S", self.tmp / "out", kind="reaper", log=quiet)

    def test_ptx_midi_and_report_wording(self):
        sess = self.tmp / "Song"
        (sess / "Audio Files").mkdir(parents=True)
        tone(sess / "Audio Files" / "Vox_01.wav", channels=1)
        ptx = sess / "Song.ptx"
        ptx.write_bytes(b"\x03" + bytes(63))
        os.environ["HYPNOMIX_PTDUMP"] = str(stand_in(self.tmp, "ptdump", dict(
            format="ptx", version=12, rate=SR, audiofiles=[], miditracks=[
                dict(name="Keys", index=1, playlist=0, region=dict(name="k", index=0, start=1920000, offset=0,
                                                                   length=960000, notes=[[0, 480000, 60, 100]]))],
            tracks=[dict(name="Vox", index=0, playlist=0, region=dict(name="v", index=0, start=SR, offset=0,
                                                                      length=SR, file="Vox_01.wav", file_index=0)),
                    dict(name="Gone", index=2, playlist=0, region=dict(name="g", index=0, start=0, offset=0,
                                                                       length=SR, file="Gone_01.wav", file_index=1))])))
        from hypnomix.project import import_ptx
        m = import_ptx.read(ptx)
        keys = [t for t in m["tracks"] if t["name"] == "Keys"][0]["midi"][0]
        self.assertAlmostEqual(keys["position"], 2.0)
        self.assertEqual(keys["notes"], [(0.0, 0.5, 60, 100)])
        f, rep, _ = import_project.convert(ptx, self.tmp / "out", log=quiet)
        text = rep.read_text(encoding="utf-8")
        for typo in (" a a ", "session session", "Logicject", "session' "):
            self.assertNotIn(typo, text)
        self.assertIn("assumed", text)
        self.assertIn("Gone_01.wav", text)                          # a missing file is named
        self.assertEqual(len(list((f.parent / "interchange" / "out" / "midifiles").glob("*.mid"))), 1)
        with self.assertRaises(SystemExit):
            import_project.convert(ptx, sess / "inside", log=quiet)

    def test_aaf_one_file_two_channels_and_more(self):
        a = self.tmp / "Mix.aaf"
        a.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(56))
        st = tone(self.tmp / "st.wav", channels=2)
        os.environ["HYPNOMIX_AAFDUMP"] = str(stand_in(self.tmp, "aafdump", dict(
            format="aaf", rate=SR, name="Mix", product="Some Editor", markers=[dict(name="Chorus", start=SR, length=0)],
            tracks=[dict(name="Music", number=1, mute=1, solo=0, gain=dict(value=1.0), pan=dict(value=0.5),
                         clips=[dict(position=0, length=SR, offset=0, mute=0, name="m",
                                     fade_out=dict(length=4800, shape="linear"),
                                     files=[dict(path=str(st), channel=1), dict(path=str(st), channel=2)])])])))
        from hypnomix.project import import_aaf
        m = import_aaf.read(a, self.tmp / "media")
        r = m["tracks"][0]["regions"][0]
        self.assertEqual((r["file"], r["channels"]), (st, [0, 1]))
        self.assertNotIn("files", r)
        f, rep, _ = import_project.convert(a, self.tmp / "out", log=quiet)
        root, routes = route_by_name(f)
        self.assertEqual([c.get("value") for c in routes["Music"].iter("Controllable") if c.get("name") == "mute"], ["1"])
        self.assertIn("Chorus", [l.get("name") for l in root.iter("Location")])
        self.assertAlmostEqual(ardour.read(f).track("Music").clips[0].fade_out, 0.1, places=3)

    def test_reader_output_capped_and_exit_status(self):
        from hypnomix.project import engine_tools
        os.environ["HYPNOMIX_SECRET_TEST"] = "x"
        # prints 5 KB, against a cap patched down to 1 KB
        big = stand_in(self.tmp, "big", body="sys.stdout.write(json.dumps(dict(a='x' * 5000)))")
        os.environ["HYPNOMIX_PTDUMP"] = str(big)
        with mock.patch.object(engine_tools, "MAX_JSON", 1000):
            with self.assertRaises(SystemExit) as cm:
                engine_tools.run("hypnomix-ptdump", self.tmp / "x.ptx")
        self.assertIn("too big", str(cm.exception))
        bad = stand_in(self.tmp, "bad", body="print(json.dumps(dict(env=sorted(os.environ))))\nsys.exit(3)")
        os.environ["HYPNOMIX_PTDUMP"] = str(bad)
        with self.assertRaises(SystemExit) as cm:
            engine_tools.run("hypnomix-ptdump", self.tmp / "x.ptx")
        self.assertIn("exit status 3", str(cm.exception))
        ok = stand_in(self.tmp, "ok", body="print(json.dumps(dict(env=sorted(os.environ))))")
        os.environ["HYPNOMIX_PTDUMP"] = str(ok)
        self.assertNotIn("HYPNOMIX_SECRET_TEST", engine_tools.run("hypnomix-ptdump", self.tmp / "x.ptx")["env"])


class ConvertFindingsTest(unittest.TestCase):                    # findings 33, 34 (detection, main, the route)
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="hx-imp-cv-"))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_kinds(self):
        import gzip
        with gzip.open(self.d / "x.als", "wb") as fh:
            fh.write(b"<Ableton/>")
        self.assertEqual(import_project.kind_of(self.d / "x.als"), "live")
        (self.d / "B.band").mkdir()
        self.assertEqual(import_project.kind_of(self.d / "B.band"), "logicx")
        if hasattr(os, "mkfifo"):
            os.mkfifo(self.d / "pipe.rpp")
            self.assertIsNone(import_project.kind_of(self.d / "pipe.rpp"))

    def test_checks_before_reading(self):
        src = make_dawproject(self.d)
        (self.d / "file").write_text("x", encoding="utf-8")
        with self.assertRaises(SystemExit):
            import_project.convert(src, self.d / "file", log=quiet)
        with self.assertRaises(SystemExit):
            import_project.convert(src, self.d / "new" / "deeper", sr=5, log=quiet)
        self.assertFalse((self.d / "new").exists())
        with self.assertRaises(SystemExit):
            import_project.convert(src, src / "x", log=quiet)

    def test_main_from_and_sr(self):
        src = make_dawproject(self.d)
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            import_project.main([str(src), str(self.d / "out"), "--from", "dawproject", "--sr", "44100"])
        f = next((self.d / "out").glob("*.ardour"))
        self.assertIn('sample-rate="44100"', f.read_text(encoding="utf-8"))

    def test_live_through_import(self):
        sys.path.insert(0, str(Path(__file__).parent))
        try:
            import test_als2ardour as T
        except Exception as e:                                       # its own needs are its own test's business
            self.skipTest(f"test_als2ardour not importable: {e}")
        finally:
            sys.path.pop(0)
        (self.d / "set").mkdir()
        als = T.make_set(self.d / "set")
        self.assertEqual(import_project.kind_of(als), "live")
        f, rep, summary = import_project.convert(als, self.d / "out", log=quiet)
        self.assertTrue(f.is_file())
        self.assertIn(".als set", summary)
        text = rep.read_text(encoding="utf-8")
        self.assertIn("Read back by HypnoMix's own session reader", text)      # the .als route is read back too
        for live in ("Live project folder", "Live devices", "Live's"):
            self.assertNotIn(live, text)

    def test_route_over_http_and_one_job_at_a_time(self):
        from http.server import ThreadingHTTPServer
        import urllib.request
        from hypnomix.app import daw, server as S
        src = make_dawproject(self.d)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(0))
        port = srv.server_address[1]
        srv.RequestHandlerClass = S.make_handler(port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base, tok = f"http://127.0.0.1:{port}", {"X-Hypnomix": S.TOKEN, "Content-Type": "application/json"}
        try:
            req = urllib.request.Request(base + "/api/daw/import", data=json.dumps(dict(path=str(src))).encode(),
                                         headers=tok, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                job = json.loads(r.read())["job"]
            for _ in range(600):
                with urllib.request.urlopen(urllib.request.Request(f"{base}/api/daw/import?job={job}", headers=tok),
                                            timeout=10) as r:
                    st = json.loads(r.read())
                if st["state"] != "running":
                    break
                time.sleep(0.1)
            self.assertEqual(st["state"], "done", st.get("error"))
        finally:
            srv.shutdown()
            srv.server_close()
        with mock.patch.dict(daw.IMPORT_JOBS, {"busy": dict(state="running", started=time.time())}):
            with self.assertRaises(ValueError):
                daw.import_start(str(src))
        with mock.patch.dict(daw.IMPORT_JOBS, {"stuck": dict(state="running", started=time.time() - 2 * 3600)}, clear=True):
            (self.d / "full").mkdir()
            (self.d / "full" / "keep").write_text("x", encoding="utf-8")
            st = daw.import_start(str(src), str(self.d / "full"))
            self.assertEqual(daw.IMPORT_JOBS["stuck"]["state"], "failed")
            for _ in range(600):
                cur = daw.import_status(st["job"])
                if cur["state"] != "running":
                    break
                time.sleep(0.1)
            self.assertEqual(cur["state"], "failed")
            self.assertIn("not empty", cur["error"])


# ---------------------------------------------------------------- the re-check's findings (O = earlier, N = new)
def note_ev(tick, key, vel, length):
    e = bytearray(32)
    e[0] = 0x90
    struct.pack_into("<I", e, 4, 38400 + tick)
    e[0x0b], e[0x0c] = vel, key
    struct.pack_into("<I", e, 0x1c, length)
    return bytes(e)


def place20(tick, row, group):
    e = bytearray(80)
    e[0] = 0x20
    struct.pack_into("<I", e, 4, 34560 + tick)
    e[0x14] = row
    struct.pack_into("<I", e, 0x20, group)
    return bytes(e)


class RecheckTest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="hx-imp-rc-"))
        self.wav = tone(self.d / "a.wav")
        self.env = dict(os.environ)
        from hypnomix.project import import_dawproject, import_reaper
        self.DP, self.RP = import_dawproject, import_reaper

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        shutil.rmtree(self.d, ignore_errors=True)

    def lanes(self, clips, tid="t1"):
        return f'<Lanes track="{tid}"><Clips>{clips}</Clips></Lanes>'

    def one_clip(self):
        return self.lanes(f'<Clip time="0" duration="2">{AUDIO}</Clip>')

    def rpp_project(self, body, head=""):
        proj = self.d / "proj"
        proj.mkdir(exist_ok=True)
        tone(proj / "gtr.wav", seconds=4.0)
        return rpp(proj, body, head)

    # ---- fixes that broke a normal project
    def test_N7_O4_silent_file_is_left_out_not_the_project(self):
        silent = b"RIFF" + bytes(1 << 20)                         # 1 MB that packs to about 1 KB
        xml = dp_xml(dp_track("A", "t1"), self.lanes(
            f'<Clip time="0" duration="2">{AUDIO}</Clip><Clip time="4" duration="2"><Audio channels="2" '
            'sampleRate="48000" duration="4"><File path="audio/silent.wav"/></Audio></Clip>'))
        p = dp_zip(self.d, xml, {"audio/a.wav": self.wav, "audio/silent.wav": silent}, deflate=True)
        with mock.patch.object(self.DP, "RATIO_FLOOR", 0):
            f, rep, _ = import_project.convert(p, self.d / "out", log=quiet)
        self.assertIn("silent.wav: unpacks to", rep.read_text(encoding="utf-8"))
        self.assertEqual(len(ardour.read(f).track("A").clips), 1)

    def test_N7_split_files_meet_the_total_ratio(self):
        import io
        buf = io.BytesIO()
        sf.write(buf, np.zeros(150_000, dtype=np.int16), SR, format="WAV", subtype="PCM_16")   # 300 KB of silence
        files = {f"audio/s{i}.wav": buf.getvalue() for i in range(4)}
        clips = "".join(f'<Clip time="{2 * i}" duration="2"><Audio channels="2" sampleRate="48000" duration="4">'
                        f'<File path="audio/s{i}.wav"/></Audio></Clip>' for i in range(4))
        p = dp_zip(self.d, dp_xml(dp_track("A", "t1"), self.lanes(clips)), files, deflate=True)
        with mock.patch.object(self.DP, "RATIO_FLOOR", 512 << 10):
            m = self.DP.read(p, self.d / "media")
        self.assertTrue(any("unpacked so far is more than" in x for x in m["not_carried"]), m["not_carried"])

    def test_n5_media_over_the_budget_is_left_out_not_refused(self):
        p = dp_zip(self.d, dp_xml(dp_track("A", "t1"), self.one_clip()), {"audio/a.wav": self.wav})
        with mock.patch.object(self.DP, "MAX_MEDIA_TOTAL", 1000):
            m = self.DP.read(p, self.d / "media")
        self.assertTrue(any("the disk's room for it" in x for x in m["not_carried"]))
        with mock.patch.object(self.DP, "MAX_MEDIA", 1000):
            m = self.DP.read(p, self.d / "media2")
        self.assertTrue(any("more than 0 GB; left out" in x or "left out" in x for x in m["not_carried"]))

    def test_O13_N9_session_is_read_back(self):
        p = dp_zip(self.d, dp_xml(dp_track("A", "t1"), self.one_clip()), {"audio/a.wav": self.wav})
        f, rep, _ = import_project.convert(p, self.d / "out", log=quiet)
        self.assertIn("Read back by HypnoMix's own session reader after writing: 1 track(s) and 1 region(s)",
                      rep.read_text(encoding="utf-8"))
        with mock.patch.object(ardour, "read", side_effect=ValueError("boom")):
            with self.assertRaises(SystemExit) as cm:
                import_project.convert(p, self.d / "out2", log=quiet)
        self.assertIn("could not be read back", str(cm.exception))
        self.assertFalse((self.d / "out2").exists())

    # ---- wrong results
    def test_N1_reaper_ramp_beats_agree_with_the_audio(self):
        src = self.rpp_project('  <TRACK\n    NAME "Gtr"\n' + rpp_item(0) + "  >\n",
                               head="  TEMPO 60 4 4\n  <TEMPOENVEX\n    ACT 1 -1\n    PT 0 60 0\n    PT 4 120 1\n  >\n")
        from hypnomix.project import als2ardour as A, rpp as R
        pts, _, ramps = self.RP.tempo_map(R.load(src), 60.0)
        self.assertEqual(ramps, 1)
        tempo = A.Tempo(60.0, pts)
        self.assertAlmostEqual(tempo.seconds(6.0), 4.0, places=2)   # (60 + 120) / 2 x 4 s = 6 beats in 4 s
        f, rep, _ = import_project.convert(src, self.d / "out", log=quiet)
        self.assertIn("tempo ramp(s)", rep.read_text(encoding="utf-8"))
        self.assertNotIn("bar numbers assume", rep.read_text(encoding="utf-8"))     # N3

    def test_N14_leading_row_and_odd_events(self):
        odd = bytearray(48)
        odd[0] = 0x30
        b = make_logic(self.d, lead_row=True, places=place(0, 2, 0, 0) + bytes(odd) + place(0, 1, 0, 0))
        m = import_logic.read(b)
        bass = m["tracks"][0]
        self.assertEqual(bass["name"], "Bass")
        self.assertEqual(len(bass["regions"]), 1)                   # row 2 counts every row: the Bass row
        text = " ".join(m["warnings"] + m["not_carried"])
        self.assertIn("folder or other row before", text)
        self.assertIn("placement(s) on a row that is not an audio track", text)
        self.assertIn("event(s) of a type this reader does not know", text)

    # ---- hostile input
    def test_N4_many_tempo_points_are_capped_and_fast(self):
        pts = "".join(f'<RealPoint time="{i}" value="{100 + i % 50}" interpolation="hold"/>' for i in range(6000))
        arr = f'<TempoAutomation unit="bpm" timeUnit="beats">{pts}</TempoAutomation>'
        p = dp_zip(self.d, dp_xml(dp_track("A", "t1"), self.one_clip(), arr=arr), {"audio/a.wav": self.wav})
        t0 = time.monotonic()
        f, rep, _ = import_project.convert(p, self.d / "out", log=quiet)
        self.assertLess(time.monotonic() - t0, 60)
        self.assertIn("tempo map has", rep.read_text(encoding="utf-8"))

    def test_N5_O2_budgets_counted_while_reading(self):
        b = make_logic(self.d, places=b"".join(place20(0, 1, 0x40) for _ in range(20)),
                       extra=[rec("EvSq", b"".join(note_ev(i * 96, 60, 100, 96) for i in range(10)) + END, cls=0x17,
                                  group=0x40)])
        with mock.patch.object(importer, "MAX_NOTES", 100):
            with self.assertRaises(SystemExit) as cm:
                import_logic.read(b)
        self.assertIn("MIDI notes", str(cm.exception))
        p = dp_zip(self.d, dp_xml(dp_track("A", "t1"), self.lanes(
            f'<Clip time="0" duration="400" contentTimeUnit="seconds" loopStart="0" loopEnd="1">{AUDIO}</Clip>')),
                   {"audio/a.wav": self.wav})
        with mock.patch.object(importer, "MAX_REGIONS", 50):
            with self.assertRaises(SystemExit) as cm:
                self.DP.read(p, self.d / "media")
        self.assertIn("regions", str(cm.exception))

    def test_N6_O3_utf16_dtd_refused(self):
        xml = ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE p [<!ENTITY x "hello">]>'
               '<Project><Application name="&x;"/><Structure/></Project>')
        p = self.d / "u.dawproject"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("project.xml", capped(xml.encode("utf-16")))
        with self.assertRaises(SystemExit) as cm:
            self.DP.read(p, self.d / "media")
        self.assertIn("DTD", str(cm.exception))
        import gzip
        als = self.d / "x.als"
        with gzip.open(als, "wb") as fh:
            fh.write(('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE a [<!ENTITY x "y">]><Ableton/>').encode("utf-16"))
        from hypnomix.project import als2ardour as A
        with self.assertRaises(SystemExit):
            A.load_xml(als)

    def test_O5_in_memory_conversion_has_a_budget(self):
        from hypnomix.project import als2ardour as A
        slow = tone(self.d / "slow.wav", sr=44100)
        p = dp_zip(self.d, dp_xml(dp_track("A", "t1"), self.lanes(
            '<Clip time="0" duration="2"><Audio channels="2" sampleRate="44100" duration="4"><File path="audio/s.wav"/>'
            '</Audio></Clip>')), {"audio/s.wav": slow})
        real_which = shutil.which
        with mock.patch.object(A, "MAX_MEMORY_SAMPLES", 1000), \
                mock.patch.object(A.shutil, "which", lambda n: None if n == "ffmpeg" else real_which(n)):
            f, rep, _ = import_project.convert(p, self.d / "out", sr=48000, log=quiet)
        self.assertIn("too long to convert in memory", rep.read_text(encoding="utf-8"))
        if real_which("ffmpeg"):                                    # streamed through ffmpeg when it is there
            f, rep, _ = import_project.convert(p, self.d / "out2", sr=48000, log=quiet)
            self.assertIn("file to file, by ffmpeg", rep.read_text(encoding="utf-8"))
            self.assertEqual(len(ardour.read(f).track("A").clips), 1)

    def test_O6_xml_illegal_characters_and_the_note(self):
        src = self.rpp_project('  <TRACK\n    NAME "Odd￾Name￿"\n' + rpp_item(0) + "  >\n")
        f, rep, _ = import_project.convert(src, self.d / "out", log=quiet)
        import xml.etree.ElementTree as ET
        ET.parse(f)
        self.assertIn("its name held characters a session cannot hold", rep.read_text(encoding="utf-8"))

    def test_O7_reader_error_output_is_capped(self):
        from hypnomix.project import engine_tools
        # writes 4 MB of error output at most (and its own OS cap is 16 MB), against a cap patched to 1 MB
        os.environ["HYPNOMIX_PTDUMP"] = str(stand_in(self.d, "noisy", body=(
            "for _ in range(64):\n    sys.stderr.write('e' * 65536)\n    sys.stderr.flush()\n    time.sleep(0.02)\n"
            "print('{}')")))
        with mock.patch.object(engine_tools, "MAX_ERR_DISK", 1 << 20):
            with self.assertRaises(SystemExit) as cm:
                engine_tools.run("hypnomix-ptdump", self.d / "x.ptx")
        self.assertIn("error output", str(cm.exception))

    def test_n9_reader_timeout(self):
        from hypnomix.project import engine_tools
        os.environ["HYPNOMIX_PTDUMP"] = str(stand_in(self.d, "slow", body="time.sleep(5)\nprint('{}')"))
        with mock.patch.object(engine_tools, "TIMEOUT", 0.5):
            with self.assertRaises(SystemExit) as cm:
                engine_tools.run("hypnomix-ptdump", self.d / "x.ptx")
        self.assertIn("took longer", str(cm.exception))

    def test_windows_path_watches_the_extracted_files(self):
        """Windows has no rlimits: the reader runs without one (HAVE_RLIMIT off, as there) and a file it extracts past
        the one-file limit is still caught, by the watch on its folder."""
        from hypnomix.project import engine_tools
        media = self.d / "media"
        media.mkdir()
        os.environ["HYPNOMIX_AAFDUMP"] = str(stand_in(self.d, "extracts", body=(
            "open(os.path.join(sys.argv[2], 'a.wav'), 'wb').write(b'0' * (2 << 20))\ntime.sleep(3)\nprint('{}')")))
        seen = []
        real_popen = engine_tools.subprocess.Popen

        def popen(*a, **k):
            seen.append(k.get("preexec_fn"))
            return real_popen(*a, **k)
        with mock.patch.object(engine_tools, "HAVE_RLIMIT", False), \
                mock.patch.dict(engine_tools.MAX_FILE, {"hypnomix-aafdump": 1 << 20}), \
                mock.patch.object(engine_tools.subprocess, "Popen", popen):
            t0 = time.monotonic()
            with self.assertRaises(SystemExit) as cm:
                engine_tools.run("hypnomix-aafdump", self.d / "x.aaf", media, watch=media)
        self.assertEqual(seen, [None])                                   # no preexec_fn, as on Windows
        self.assertIn("wrote a file larger than 1 MB (a.wav)", str(cm.exception))
        self.assertLess(time.monotonic() - t0, 2.9)                       # stopped by the watch, not at its end

    def test_windows_readers_get_what_a_windows_program_needs(self):
        from hypnomix.project import engine_tools
        env = {"SYSTEMROOT": r"C:\Windows", "TEMP": r"C:\Users\X\AppData\Local\Temp", "HYPNOMIX_SECRET_TEST": "x",
               "PATH": r"C:\Users\X\bin"}
        with mock.patch.dict(os.environ, env, clear=True):
            got = engine_tools.reader_env(windows=True)
        self.assertEqual(got["SYSTEMROOT"], r"C:\Windows")               # without it a Windows program may not start
        self.assertIn(r"C:\Windows\System32", got["PATH"])
        self.assertNotIn(r"C:\Users\X\bin", got["PATH"])
        self.assertEqual(got["TEMP"], env["TEMP"])
        self.assertNotIn("HYPNOMIX_SECRET_TEST", got)
        with mock.patch.dict(os.environ, {"HOME": "/Users/x", "HYPNOMIX_SECRET_TEST": "x"}, clear=True):
            self.assertEqual(engine_tools.reader_env(windows=False), {"PATH": "/usr/bin:/bin", "HOME": "/Users/x"})

    def test_n9_xml_caps(self):
        p = dp_zip(self.d, dp_xml(dp_track("A", "t1"), self.one_clip()), {"audio/a.wav": self.wav})
        with mock.patch.object(self.DP, "MAX_XML", 100):
            with self.assertRaises(SystemExit) as cm:
                self.DP.read(p, self.d / "m1")
        self.assertIn("too big", str(cm.exception))
        with mock.patch.object(self.DP, "MAX_ELEMENTS", 5):
            with self.assertRaises(SystemExit) as cm:
                self.DP.read(p, self.d / "m2")
        self.assertIn("elements", str(cm.exception))

    def test_N8_paths_elsewhere_are_never_touched(self):
        src = self.rpp_project('  <TRACK\n    NAME "Gtr"\n' + rpp_item(0, file="/hypnomix-no-such-mount/x.wav") + "  >\n")
        f, rep, _ = import_project.convert(src, self.d / "out", log=quiet)
        text = rep.read_text(encoding="utf-8")
        self.assertIn("## Left out: audio from outside the project", text)   # decided from the text: never opened
        self.assertIn("x.wav", text)

    # ---- honesty
    def test_N10_O9_skips_are_counted(self):
        st = (dp_track("A", "t1", channel='<Sends><Send destination="c_nobus" type="post"><Volume unit="linear" '
                                          'value="1"/></Send><Send destination="ct2"><Enable value="false"/>'
                                          '<Volume unit="linear" value="1"/></Send></Sends>')
              + dp_track("B", "t2", role="effect")
              + '<Track contentType="video" name="Film" id="tv"/>')
        lanes = (self.lanes(f'<Clip time="0" duration="2">{AUDIO}</Clip><Clip time="3" duration="0">{AUDIO}</Clip>'
                            '<Clip time="4" duration="2"><Video/></Clip>')
                 + self.lanes(f'<Clip time="0" duration="2">{AUDIO}</Clip>', "nope")
                 + self.lanes(f'<Clip time="0" duration="2">{AUDIO}</Clip>', "tv"))
        m = self.DP.read(dp_zip(self.d, dp_xml(st, lanes), {"audio/a.wav": self.wav}), self.d / "media")
        text = " ".join(m["not_carried"])
        for want in ("not in the project", "zero length", "Video content", "switched-off send", "not a bus here",
                     "video track"):
            self.assertIn(want, text)
        src = self.rpp_project('  <TRACK\n    NAME "Gtr"\n' + rpp_item(0) + "  >\n",
                               head='  <MASTERFXLIST\n    <VST "VST: Some Limiter (Maker)" x.vst 0\n    >\n  >\n')
        self.assertIn("the master's plug-ins: Some Limiter", " ".join(self.RP.read(src)["not_carried"]))

    def test_N11_N12_wording(self):
        src = self.rpp_project('  <TRACK\n    NAME "Gtr"\n' + rpp_item(0, extra="      PLAYRATE 1.5 1 0 -1 0 0.0025\n")
                               + "  >\n")
        f, rep, summary = import_project.convert(src, self.d / "out", log=quiet)
        text = rep.read_text(encoding="utf-8")
        self.assertNotIn("REAPER", text + summary)
        self.assertNotIn("never guessed", text)
        for word in ("Live set", "REAPER project", "never guessed"):
            self.assertNotIn(word, import_project.__doc__)
        self.assertIn("1 track,", summary)                          # n9: singular
        m = import_logic.read(make_logic(self.d / "lg"))
        self.assertIn("may be wrong", " ".join(m["not_carried"]))

    def test_N2_reports_names_not_keys(self):
        p = dp_zip(self.d, dp_xml(dp_track("A", "t1", channel='<Sends><Send destination="cct" type="post"><Volume '
                                           'unit="decibel" value="12"/></Send></Sends>') +
                                  '<Track contentType="audio" name="Verb" id="ct"><Channel role="effect" id="cct" '
                                  'destination="cm"/></Track>', self.one_clip()), {"audio/a.wav": self.wav})
        f, rep, _ = import_project.convert(p, self.d / "out", log=quiet)
        text = rep.read_text(encoding="utf-8")
        self.assertIn("its send to 'Verb' was +12.00 dB", text)
        self.assertNotIn("'k", text)

    def test_N16_N17_allow_outside(self):
        elsewhere = Path(tempfile.mkdtemp(prefix="hx-imp-else2-"))
        try:
            secret = tone(elsewhere / "shared.wav")
            src = self.rpp_project('  <TRACK\n    NAME "Gtr"\n' + rpp_item(0, file=str(secret)) + "  >\n")
            f, rep, _ = import_project.convert(src, self.d / "out", log=quiet)
            self.assertIn("'Also copy audio from outside the project' ticked", rep.read_text(encoding="utf-8"))
            from hypnomix.app import daw
            st = daw.import_start(str(src), str(self.d / "out2"), allow_outside=True)
            for _ in range(600):
                cur = daw.import_status(st["job"])
                if cur["state"] != "running":
                    break
                time.sleep(0.1)
            self.assertEqual(cur["state"], "done", cur.get("error"))
            self.assertEqual(len(ardour.read(Path(cur["session"])).track("Gtr").clips), 1)
        finally:
            shutil.rmtree(elsewhere, ignore_errors=True)

    def test_O19_tool_missing_is_one_plain_sentence(self):
        os.environ["HYPNOMIX_PTDUMP"] = str(self.d / "nothing")
        os.environ.pop("HYPNOMIX_ENGINE_SRC", None)
        os.environ["PATH"] = str(self.d)
        os.environ["HYPNOMIX_ENGINE"] = str(self.d / "no-engine")
        (self.d / "S").mkdir()
        (self.d / "S" / "S.ptx").write_bytes(b"\x03" + bytes(63))
        with self.assertRaises(SystemExit) as cm:
            import_project.convert(self.d / "S" / "S.ptx", self.d / "out", log=quiet)
        self.assertTrue(str(cm.exception).startswith("this kind of project is read by hypnomix-ptdump"))
        self.assertNotIn("ToolMissing", str(cm.exception))

    # ---- smaller items
    def test_n2_aaf_channels_per_file(self):
        a = self.d / "Mix.aaf"
        a.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(56))
        x, y = tone(self.d / "x.wav", channels=2), tone(self.d / "y.wav", channels=2)
        os.environ["HYPNOMIX_AAFDUMP"] = str(stand_in(self.d, "aafdump", dict(
            format="aaf", rate=SR, name="Mix", product="Some Editor", markers=[],
            tracks=[dict(name="M", number=1, clips=[dict(position=0, length=SR, offset=0, name="m",
                                                         files=[dict(path=str(x), channel=2), dict(path=str(y), channel=1)]),
                                                    dict(position=SR, length=0, offset=0, name="z", files=[])])])))
        f, rep, _ = import_project.convert(a, self.d / "out", log=quiet)
        clip = ardour.read(f).track("M").clips[0]
        self.assertEqual(len(clip.take.extra_paths), 1)            # two channels, not four
        self.assertIn("zero length", rep.read_text(encoding="utf-8"))

    def test_n3_later_tempo_on_one_beat_wins(self):
        self.assertEqual(importer.tempo_points(120, [(4, 140), (4, 90)])[-1], (4.0, 90.0))

    @_isolate.POSIX_MODES
    def test_n4_unwritable_place_falls_back(self):
        top = self.d / "top"
        (top / "proj").mkdir(parents=True)
        src = rpp(top / "proj", '  <TRACK\n    NAME "Gtr"\n  >\n')
        top.chmod(0o555)
        try:
            out = import_project.default_out(src)
        finally:
            top.chmod(0o755)
        self.assertEqual(out.parent, Path.home() / "Documents" / "HypnoMix" / "Imported")

    def test_n4_a_folder_that_only_says_it_is_writable_is_tried(self):
        """Windows: os.access calls every folder writable (it reads only the read-only flag), so there a folder is
        tried with a small file, made and removed. Here that path is taken on purpose (ACCESS_SEES_FOLDERS off)."""
        top = self.d / "top"
        (top / "proj").mkdir(parents=True)
        src = rpp(top / "proj", '  <TRACK\n    NAME "Gtr"\n  >\n')
        with mock.patch.object(import_project, "ACCESS_SEES_FOLDERS", False):
            self.assertEqual(import_project.default_out(src).parent, top.resolve())   # it can be written: beside the project
            self.assertEqual(sorted(p.name for p in top.iterdir()), ["proj"])  # and the trial file is gone
            refuse = PermissionError(13, "Access is denied")
            with mock.patch.object(import_project.tempfile, "mkstemp", side_effect=refuse):
                out = import_project.default_out(src)
        self.assertEqual(out.parent, Path.home() / "Documents" / "HypnoMix" / "Imported")

    def test_n7_long_folder_name_is_a_sentence(self):
        p = dp_zip(self.d, dp_xml(dp_track("A", "t1"), self.one_clip()), {"audio/a.wav": self.wav})
        with self.assertRaises(SystemExit) as cm:
            import_project.convert(p, self.d / ("x" * 300), log=quiet)
        self.assertIn("cannot be used", str(cm.exception))
        # Windows' pathlib answers "does it exist" for a too-long name with a plain no (it takes the invalid-name error
        # for one), so the length itself is checked first: the same sentence there
        with mock.patch.object(importer.Path, "exists", return_value=False):
            with self.assertRaises(SystemExit) as cm:
                importer.check_out(self.d / ("y" * 300), None)
        self.assertIn("cannot be used", str(cm.exception))
        self.assertIn("longer than 255 characters", str(cm.exception))

    def test_n8_n13_als_sr_checked_first(self):
        import gzip
        with gzip.open(self.d / "x.als", "wb") as fh:
            fh.write(b"<Ableton/>")
        with self.assertRaises(SystemExit) as cm:
            import_project.convert(self.d / "x.als", self.d / "out", sr=5, log=quiet)
        self.assertIn("--sr 5", str(cm.exception))

    def test_n10_decode_timeout_is_said(self):
        import subprocess
        from hypnomix.core import dsp
        f = self.d / "x.m4a"
        f.write_bytes(b"\0\0\0\x20ftypM4A " + bytes(64))
        with mock.patch("shutil.which", lambda n: "/usr/bin/true"), \
                mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 1)):
            with self.assertRaises(dsp.AudioReadError) as cm:
                dsp.read(f)
        self.assertIn("took longer than", str(cm.exception))

    def test_O14_misses(self):
        sess = self.d / "Song"
        (sess / "Audio Files").mkdir(parents=True)
        ptx = sess / "Song.ptx"
        ptx.write_bytes(b"\x03" + bytes(63))
        os.environ["HYPNOMIX_PTDUMP"] = str(stand_in(self.d, "ptdump", dict(
            format="ptx", version=12, rate=SR, audiofiles=[], tracks=[], miditracks=[
                dict(name="Keys", index=0, playlist=0, region=dict(name="k", index=0, start=0, offset=0, length=1920000,
                                                                   notes=[[960000, 480000, 62, 90]]))])))
        from hypnomix.project import import_ptx
        self.assertEqual(import_ptx.read(ptx)["tracks"][0]["midi"][0]["notes"], [(1.0, 0.5, 62, 90)])
        src = make_dawproject(self.d)
        with self.assertRaises(SystemExit):                         # --from is used: a .dawproject is no .rpp
            import_project.main([str(src), str(self.d / "o1"), "--from", "reaper"])
        from hypnomix.app import daw
        (self.d / "z.bin").write_bytes(b"nothing")
        with self.assertRaises(ValueError):
            daw.import_start(str(self.d / "z.bin"))
        (self.d / "full").mkdir()
        (self.d / "full" / "keep").write_text("x", encoding="utf-8")
        with mock.patch.object(import_project, "read", side_effect=RuntimeError("read too early")):
            with self.assertRaises(SystemExit) as cm:
                import_project.convert(src, self.d / "full", log=quiet)
        self.assertIn("not empty", str(cm.exception))


# ---------------------------------------------------------------- the last list
class LastListTest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="hx-imp-ll-"))
        self.wav = tone(self.d / "a.wav")
        self.env = dict(os.environ)
        from hypnomix.project import import_dawproject, import_reaper
        self.DP, self.RP = import_dawproject, import_reaper

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        shutil.rmtree(self.d, ignore_errors=True)

    def rpp_project(self, body, head=""):
        proj = self.d / "proj"
        proj.mkdir(exist_ok=True)
        tone(proj / "gtr.wav", seconds=4.0)
        return rpp(proj, body, head)

    def dp(self, structure, clips='<Clip time="0" duration="2">' + AUDIO + '</Clip>', tid="t1"):
        return dp_zip(self.d, dp_xml(structure, f'<Lanes track="{tid}"><Clips>{clips}</Clips></Lanes>'),
                      {"audio/a.wav": self.wav})

    def test_1_far_apart_ramp_is_capped_while_expanding(self):
        from hypnomix.project import rpp as R
        src = self.rpp_project('  <TRACK\n    NAME "Gtr"\n  >\n',
                               head="  <TEMPOENVEX\n    PT 0 60 0\n    PT 1000000 120 1\n  >\n")
        t0 = time.monotonic()
        pts, _, _ = self.RP.tempo_map(R.load(src), 60.0)
        self.assertLessEqual(len(pts), importer.MAX_TEMPO_POINTS + 4)
        self.assertLess(time.monotonic() - t0, 5)

    def test_2_tracks_and_rpp_text_counted_first(self):
        st = "".join(dp_track(f"T{i}", f"t{i}") for i in range(5))
        with mock.patch.object(importer, "MAX_TRACKS", 3):
            with self.assertRaises(SystemExit) as cm:
                self.DP.read(self.dp(st), self.d / "media")
        self.assertIn("tracks", str(cm.exception))
        src = self.rpp_project('  <TRACK\n    NAME "Gtr"\n' + rpp_item(0) + "  >\n")
        with mock.patch.object(self.RP, "MAX_RPP_BYTES", 10):
            with self.assertRaises(SystemExit):
                self.RP.read(src)
        with mock.patch.object(importer, "MAX_REGIONS", 0):
            with self.assertRaises(SystemExit) as cm:
                self.RP.read(src)
        self.assertIn("items", str(cm.exception))

    def test_3_ramp_error_fast_and_set_element_cap(self):
        from hypnomix.project import als2ardour as A
        tempo = A.Tempo(100.0, [(i * 0.5, 100.0 + (i % 2) * 20) for i in range(8000)])
        t0 = time.monotonic()
        tempo.ramp_error()
        self.assertLess(time.monotonic() - t0, 10)
        import gzip
        with gzip.open(self.d / "x.als", "wb") as fh:
            fh.write(b"<Ableton><a/><b/><c/><d/></Ableton>")
        with mock.patch.object(A, "MAX_SET_ELEMENTS", 3):
            with self.assertRaises(SystemExit):
                A.load_xml(self.d / "x.als")

    def test_4_compressed_same_rate_copy_has_the_budget(self):
        from hypnomix.project import als2ardour as A
        flac = self.d / "f.flac"
        sf.write(str(flac), np.zeros((SR * 2, 2)), SR, format="FLAC")
        clips = '<Clip time="0" duration="2"><Audio channels="2" sampleRate="48000" duration="2"><File path="audio/f.flac"/></Audio></Clip>'
        p = dp_zip(self.d, dp_xml(dp_track("A", "t1"), f'<Lanes track="t1"><Clips>{clips}</Clips></Lanes>'),
                   {"audio/f.flac": flac})
        with mock.patch.object(A, "MAX_FILE_SECONDS", 1):
            f, rep, _ = import_project.convert(p, self.d / "out", log=quiet)
        self.assertIn("a compressed file is taken up to", rep.read_text(encoding="utf-8"))

    def test_6_reaper_dotdot_is_checked_from_the_text(self):
        tone(self.d / "outside.wav")
        src = self.rpp_project('  <TRACK\n    NAME "Gtr"\n' + rpp_item(0, file="../outside.wav") + "  >\n")
        f, rep, _ = import_project.convert(src, self.d / "out", log=quiet)
        self.assertIn("## Left out: audio from outside the project", rep.read_text(encoding="utf-8"))

    def test_7_ffmpeg_that_cannot_start_is_one_sentence(self):
        import subprocess
        from hypnomix.project import als2ardour as A
        srcs = A.Sources(self.d, 48000, [])
        with mock.patch.object(A.shutil, "which", lambda n: "/usr/bin/true"), \
                mock.patch("subprocess.run", side_effect=subprocess.SubprocessError("preexec")):
            with self.assertRaises(ValueError) as cm:
                srcs._ffmpeg(self.wav, "a", [], "a.wav", 44100)
        self.assertIn("could not be started", str(cm.exception))

    def test_8_read_back_count_check(self):
        p = self.dp(dp_track("A", "t1"))

        class Empty:
            tracks = []
        with mock.patch.object(ardour, "read", return_value=Empty()):
            with self.assertRaises(SystemExit) as cm:
                import_project.convert(p, self.d / "out", log=quiet)
        self.assertIn("reads back with 0 track(s)", str(cm.exception))
        self.assertFalse((self.d / "out").exists())

    def test_8_allow_outside_is_off_by_default(self):
        from hypnomix.app import daw
        with mock.patch.object(daw, "import_start", return_value={}) as start:
            daw.handle_post("/api/daw/import", {"path": "/x.rpp"})
        self.assertIs(start.call_args.kwargs["allow_outside"], False)
        root = Path(__file__).resolve().parents[1]
        js = (root / "hypnomix" / "app" / "daw" / "js" / "app.js").read_text(encoding="utf-8")
        box = [ln for ln in js.splitlines() if "const outside = h('input'" in ln]
        self.assertEqual(len(box), 1)
        self.assertNotIn("checked", box[0])
        self.assertIn("outside.state = .off", (root / "macapp" / "Hypnomix.swift").read_text(encoding="utf-8"))

    def test_8_fffe_alone(self):
        src = self.rpp_project('  <TRACK\n    NAME "A￾"\n' + rpp_item(0) + "  >\n")
        f, rep, _ = import_project.convert(src, self.d / "out", log=quiet)
        import xml.etree.ElementTree as ET
        names = [r.get("name") for r in ET.parse(f).getroot().iter("Route")]
        self.assertIn("A", names)

    def test_8_ptx_zero_length_and_video_track_lines(self):
        sess = self.d / "Song"
        (sess / "Audio Files").mkdir(parents=True)
        ptx = sess / "Song.ptx"
        ptx.write_bytes(b"\x03" + bytes(63))
        os.environ["HYPNOMIX_PTDUMP"] = str(stand_in(self.d, "ptdump", dict(
            format="ptx", version=12, rate=SR, audiofiles=[], miditracks=[], tracks=[
                dict(name="Z", index=0, playlist=0, region=dict(name="z", index=0, start=0, offset=0, length=0,
                                                                file="z.wav", file_index=0))])))
        f, rep, _ = import_project.convert(ptx, self.d / "out", log=quiet)
        self.assertIn("1 region(s) of zero length: not carried", rep.read_text(encoding="utf-8"))
        m = self.DP.read(self.dp(dp_track("A", "t1") + '<Track contentType="video" name="Film" id="tv"/>'),
                         self.d / "media")
        self.assertIn("1 video track(s): not carried", m["not_carried"])


if __name__ == "__main__":
    unittest.main()
