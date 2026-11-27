"""MPE: the strict .mid reader, the session checks (one clean clip, one fixture per defect), the presets' bytes, and
the glide fix written into a new snapshot with the original left byte for byte as it was."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from hypnomix import project as PJ
from hypnomix.project import mpe as MP
from hypnomix.project import mpe_presets as PR

PPQ = 480
ALL_DISCRETE = "".join(f'<InterpolationStyle parameter="{pat.format(c=c)}" style="Discrete"/>'
                       for c in range(16) for _, pat in MP.INTERP)
MPE_ON = '<MPE zone="lower" members="15" member-bend-range="48" global-bend-range="2"/>'


def vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.insert(0, 0x80 | (n & 0x7F))
        n >>= 7
    return bytes(out)


def smf(events, ppq=PPQ):
    """[(tick, bytes)] -> a format-0 file (sorted by tick, ties in the given order)."""
    body, last = b"", 0
    for t, msg in sorted(events, key=lambda e: e[0]):
        body += vlq(t - last) + msg
        last = t
    body += vlq(0) + b"\xff\x2f\x00"
    return b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") + (1).to_bytes(2, "big") + \
        ppq.to_bytes(2, "big") + b"MTrk" + len(body).to_bytes(4, "big") + body


def bend(ch, v):
    return bytes((0xE0 | ch, v & 0x7F, v >> 7))


def note(ch, key, at, off, init=True, bend_to=9000, reset=True, top=None):
    ev = []
    if init:
        ev += [(at, bend(ch, 8192)), (at, bytes((0xB0 | ch, 74, 64))), (at, bytes((0xD0 | ch, 0)))]
    ev += [(at, bytes((0x90 | ch, key, 100))), (at + 60, bend(ch, bend_to if top is None else top)),
           (at + 60, bytes((0xD0 | ch, 80))), (at + 90, bytes((0xB0 | ch, 74, 90))), (off, bytes((0x80 | ch, key, 0)))]
    if reset:
        ev += [(off, bend(ch, 8192)), (off, bytes((0xD0 | ch, 0)))]
    return ev


def chord(**kw):
    """Three notes, one per member channel (2, 3 and 4), held together from beat 1."""
    ev = []
    for i, ch in enumerate((1, 2, 3)):
        ev += note(ch, 60 + 4 * i, kw.get("at", PPQ), kw.get("at", PPQ) + 4 * PPQ, **kw.get("each", {}).get(ch, {}))
    return ev


SESSION = """<?xml version="1.0" encoding="UTF-8"?>
<Session version="7003" name="Song" sample-rate="48000">
  <Sources>
    <Source name="take.mid" type="midi" flags="Writable" id="14" origin="">{styles}</Source>
  </Sources>
  <Routes>
    <Route version="7003" id="100" name="Master" default-type="audio">
      <PresentationInfo order="0" flags="MasterOut,OrderSet"/>
      <Processor id="101" name="Amp" active="1" type="amp"><Controllable name="gaincontrol" value="1"/></Processor>
    </Route>
    <Route version="7003" id="700" name="Keys" default-type="midi" midi-playlist="502" {modes}>
      <PresentationInfo order="1" flags="MidiTrack,OrderSet"/>
      {mpe}
    </Route>
  </Routes>
  <Playlists>
    <Playlist id="502" name="Keys" type="midi">
      <Region name="take.1" muted="0" opaque="1" start="b0" length="b15360@b0" layering-index="0" type="midi"
              source-0="14"/>
    </Playlist>
  </Playlists>
  <TempoMap superclocks-per-second="282240000">
    <Tempos><Tempo npm="120" enpm="120" note-type="4" type="Constant" sclock="0" quarters="0:0" bbt="1|1|0"/></Tempos>
    <Meters><Meter note-value="4" divisions-per-bar="4" sclock="0" quarters="0:0" bbt="1|1|0"/></Meters>
  </TempoMap>
</Session>
"""


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name) / "Song"
        (self.dir / "interchange" / "Song" / "midifiles").mkdir(parents=True)

    def tearDown(self):
        self._td.cleanup()

    def session(self, events, styles=ALL_DISCRETE, mpe=MPE_ON, modes=""):
        (self.dir / "interchange" / "Song" / "midifiles" / "take.mid").write_bytes(smf(events))
        path = self.dir / "Song.ardour"
        path.write_text(SESSION.format(styles=styles, mpe=mpe, modes=modes), encoding="utf-8")
        return path

    def kinds(self, events, **kw):
        f, notes = MP.checks(PJ.load(self.session(events, **kw)))
        return sorted(x["kind"] for x in f), f


class Reader(unittest.TestCase):
    def test_reads_running_status_sysex_and_merges(self):
        body = vlq(0) + b"\xf0" + vlq(3) + b"\x7e\x00\xf7" + vlq(0) + b"\x91\x3c\x64" + vlq(10) + b"\x3c\x00" \
            + vlq(0) + b"\xe1\x00\x40" + vlq(0) + b"\xff\x2f\x00"
        data = b"MThd" + bytes((0, 0, 0, 6, 0, 0, 0, 1, 1, 0xE0)) + b"MTrk" + len(body).to_bytes(4, "big") + body
        s = MP.read_smf(data)
        self.assertEqual(s.ppq, 480)
        self.assertEqual([e[1] for e in s.events], ["sysex", "on", "off", "bend"])
        self.assertEqual(s.events[3][3], 8192)

    def test_refuses_truncated_and_oversized_in_one_sentence(self):
        good = smf(chord())
        for cut in (good[:10], good[:30], good[:-3]):
            with self.assertRaises(ValueError) as e:
                MP.read_smf(cut)
            self.assertEqual(str(e.exception).count("."), 0, str(e.exception))
        with self.assertRaises(ValueError):
            MP.read_smf(b"RIFF" + bytes(20))
        old = MP.MAX_BYTES
        try:
            MP.MAX_BYTES = 100
            with self.assertRaises(ValueError) as e:
                MP.read_smf(good)
            self.assertIn("larger than", str(e.exception))
        finally:
            MP.MAX_BYTES = old
        old = MP.MAX_EVENTS
        try:
            MP.MAX_EVENTS = 10
            with self.assertRaises(ValueError) as e:
                MP.read_smf(good)
            self.assertIn("more than", str(e.exception))
        finally:
            MP.MAX_EVENTS = old

    def test_looks_like_mpe(self):
        self.assertTrue(MP.looks_like_mpe(smf(chord())))
        plain = [(PPQ, bytes((0x90, 60 + k, 100))) for k in range(3)] + [(PPQ * 2, bytes((0x80, 60 + k, 0))) for k in range(3)]
        self.assertFalse(MP.looks_like_mpe(smf(plain)))

    def test_rpn_values(self):
        ev = [(0, bytes(PR.setup_bytes("lower-15")[i:i + 3])) for i in range(0, len(PR.setup_bytes("lower-15")), 3)]
        f = MP.Facts(MP.read_smf(smf(ev)))
        self.assertEqual(f.rpn6, {0: 15})
        self.assertEqual((f.rpn0[0], f.rpn0[1], f.rpn0[15]), (2, 48, 48))


class Checks(Base):
    def test_clean_clip_has_no_findings(self):
        self.assertEqual(self.kinds(chord())[0], [])

    def test_a_plain_midi_clip_is_not_checked(self):
        plain = [(PPQ, bytes((0x90, 60 + k, 100))) for k in range(3)] + [(PPQ * 2, bytes((0x80, 60 + k, 0))) for k in range(3)]
        self.assertEqual(self.kinds(plain, styles="", mpe="")[0], [])

    def test_each_defect_gives_exactly_its_finding(self):
        cases = {
            "mpe-off": dict(events=chord(), mpe=""),
            "channels-forced": dict(events=chord(), modes='playback-channel-mode="ForceChannel" playback-channel-mask="0x1"'),
            "channels-filtered": dict(events=chord(), modes='capture-channel-mode="FilterChannels" capture-channel-mask="0x6"'),
            "too-many-notes": dict(events=chord(), mpe=MPE_ON.replace('members="15"', 'members="2"')),
            "bend-range": dict(events=chord(each={2: dict(top=16383)})),
            "no-initial-value": dict(events=chord(each={3: dict(init=False)})),
            "clip-start": dict(events=chord(at=0)),
            "glide": dict(events=chord(), styles=""),
        }
        ev = chord(each={1: dict(reset=False)}) + note(1, 72, 6 * PPQ, 7 * PPQ, init=False)
        cases["not-neutral"] = dict(events=ev)
        for want, kw in cases.items():
            with self.subTest(want):
                got, f = self.kinds(kw.pop("events"), **kw)
                self.assertEqual(got, [want], [x["problem"] for x in f])
                self.assertTrue(all(x["tool"] == "mpe" and x["problem"] and x["fix"] for x in f))
                self.assertNotIn("Ard" + "our", f[0]["problem"] + f[0]["fix"])      # the visible name is HypnoMix DAW

    def test_bend_range_says_where_the_range_came_from(self):
        _, f = self.kinds(chord(each={2: dict(top=0)}))
        self.assertIn("track's MPE setting", f[0]["problem"])
        rpn = [(0, bytes((0xB2, 0x64, 0))), (0, bytes((0xB2, 0x65, 0))), (0, bytes((0xB2, 6, 24)))]
        _, f = self.kinds(chord(each={2: dict(top=0)}) + [(t + 1, m) for t, m in rpn])
        self.assertEqual([x["kind"] for x in f], ["bend-range"])
        self.assertIn("24-semitone", f[0]["problem"])
        self.assertIn("RPN 0", f[0]["problem"])

    def test_scan_lists_the_findings_under_mpe(self):
        from hypnomix.workflow import scan_project as SP
        self.assertIn("mpe", SP.GROUPS)
        path = self.session(chord(at=0), styles="", mpe="")
        f, notes = SP.g_mpe(PJ.load(path), None, None, None)
        self.assertEqual(sorted(x["kind"] for x in f), ["clip-start", "glide", "mpe-off"])
        self.assertTrue(any("nothing was played" in n for n in notes))

    def test_checks_change_nothing(self):
        path = self.session(chord(at=0), styles="", mpe="")
        before = path.read_bytes(), (self.dir / "interchange" / "Song" / "midifiles" / "take.mid").read_bytes()
        MP.checks(PJ.load(path))
        self.assertEqual(before, (path.read_bytes(), (self.dir / "interchange" / "Song" / "midifiles" / "take.mid").read_bytes()))


class GlideFix(Base):
    def test_fix_writes_a_new_snapshot_and_leaves_the_original(self):
        from hypnomix.workflow import fix_ardour as FA
        src = self.session(chord(), styles='<InterpolationStyle parameter="midi-pitch-bender-1" style="Linear"/>')
        orig = src.read_bytes()
        f, _ = MP.checks(PJ.load(src))
        self.assertEqual([x["kind"] for x in f], ["glide"])
        self.assertEqual(f[0]["applies"], "set")
        out = src.with_name("Song (fixed).ardour")
        with redirect_stdout(io.StringIO()):
            wrote, log, failed, skipped = FA.run(self.dir, {}, src, out, f, {}, verify=False)
        self.assertEqual((wrote, failed, skipped), (out, [], []))
        self.assertEqual(src.read_bytes(), orig)
        self.assertTrue(any("set to Discrete" in line for line in log), log)
        p = PJ.load(out)                                            # read back by the project's own reader
        s = next(x for x in p.native.iter("Source") if x.get("id") == "14")
        st = MP.styles(s)
        self.assertEqual(len(st), 48)
        self.assertTrue(all(v == "Discrete" for v in st.values()))
        self.assertEqual(MP.checks(p)[0], [])

    def test_fix_skips_a_source_that_is_gone(self):
        from hypnomix.workflow import fix_ardour as FA
        src = self.session(chord(), styles="")
        f, _ = MP.checks(PJ.load(src))
        f[0]["edit"]["source"] = "999"
        with redirect_stdout(io.StringIO()):
            wrote, _, failed, skipped = FA.run(self.dir, {}, src, src.with_name("x.ardour"), f, {}, verify=False)
        self.assertIsNone(wrote)
        self.assertEqual(len(skipped), 1)
        self.assertFalse(src.with_name("x.ardour").exists())


class Presets(unittest.TestCase):
    def test_specification_bytes(self):
        b = PR.setup_bytes("lower-15")
        self.assertEqual(b[:12], bytes.fromhex("B07900 B06406 B06500 B0060F"))
        self.assertEqual(b[12:24], bytes.fromhex("B06400 B06500 B00602 B02600"))       # global channel: 2 semitones
        self.assertEqual(b[24:36], bytes.fromhex("B16400 B16500 B10630 B12600"))       # first member: 48
        self.assertEqual(len(b), 12 + 12 + 15 * 12)
        seven = dict(PR.get("lower-15"), members=7)
        self.assertEqual(PR.configuration_bytes(seven), bytes.fromhex("B07900 B06406 B06500 B00607"))
        up = PR.setup_bytes("upper-15")
        self.assertEqual(up[:12], bytes.fromhex("BF7900 BF6406 BF6500 BF060F"))
        self.assertEqual(up[24:27], bytes.fromhex("BE6400"))                           # members from 15 down
        self.assertEqual(PR.setup_bytes("lower-15-bend24")[24:36], bytes.fromhex("B16400 B16500 B10618 B12600"))
        self.assertEqual(PR.setup_bytes("lower-15-bend12")[24:36], bytes.fromhex("B16400 B16500 B1060C B12600"))

    def test_element_and_refusals(self):
        self.assertEqual(PR.mpe_element("lower-15"), {"zone": "lower", "members": "15", "member-bend-range": "48",
                                                      "global-bend-range": "2"})
        with self.assertRaises(ValueError):
            PR.setup_bytes(dict(PR.get("lower-15"), members=16))
        with self.assertRaises(ValueError):
            PR.get("nope")


if __name__ == "__main__":
    unittest.main()
