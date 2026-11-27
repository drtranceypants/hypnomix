"""HypnoMix Studio sessions: tempo ramps read exactly, tempo maps written (file and engine form), level automation
written under the smooth-automation rules (file form), and vocallevel / tempomap --follow / breathe choosing where
their moves go. The same against the real engine: tests/test_ardour_automation_live.py."""
import math
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from hypnomix import project as PJ
from hypnomix.engineer import automation_rules as RULES
from hypnomix.project import ardour as AR
from hypnomix.project import ardour_automation as AA
from hypnomix.project import ardour_edit as AE

SR = 48000
SC = 282240000


def a(sec):
    return f"a{int(round(sec * SC))}"


def session(tempos='<Tempo npm="120" enpm="120" note-type="4" type="Constant" sclock="0" quarters="0:0" bbt="1|1|0" omega="0"/>',
            bus_members=("Lead Vocal", "Harmony"), extra=""):
    """A small session: Lead Vocal, Harmony and Drums; the vocals (and `bus_members`) feed the Vox bus."""
    def route(rid, name, order, pl, to):
        out = (f'<IO name="{name}" direction="Output"><Port name="{name}/audio_out 1"><Connection other="{to}/audio_in 1"/>'
               f'</Port></IO>') if to else ""
        return f"""
    <Route version="7003" id="{rid}" name="{name}" default-type="audio" audio-playlist="{pl}">
      <PresentationInfo order="{order}" flags="AudioTrack,OrderSet"/>
      {out}
      <Controllable name="mute" value="0"/>
      <Processor id="{rid}1" name="Trim" active="1" type="trim"><Automation><AutomationList automation-id="trim" id="{rid}5" state="Off"/></Automation><Controllable name="trimcontrol" value="1"/></Processor>
      <Processor id="{rid}2" name="Amp" active="1" type="amp"><Automation><AutomationList automation-id="gain" id="{rid}6" state="Off"/></Automation><Controllable name="gaincontrol" value="0.5"/></Processor>
    </Route>"""
    routes = "".join(route(rid, n, i + 1, 500 + i, "Vox" if n in bus_members else None)
                     for i, (rid, n) in enumerate(((200, "Lead Vocal"), (210, "Harmony"), (220, "Drums"))))
    regions = "".join(f"""
    <Playlist id="{500 + i}" name="{n}" type="audio">
      <Region name="{n}.1" muted="0" opaque="1" start="{a(0)}" length="{a(20)}@{a(0)}" layering-index="0" scale-amplitude="1"
              fade-in-active="0" fade-out-active="0" type="audio" source-0="{10 + i}"/>
    </Playlist>""" for i, n in enumerate(("Lead Vocal", "Harmony", "Drums")))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Session version="7003" name="Demo" sample-rate="{SR}">
  <Sources>
    <Source name="lead.wav" type="audio" flags="" id="10" channel="0" origin=""/>
    <Source name="harm.wav" type="audio" flags="" id="11" channel="0" origin=""/>
    <Source name="drums.wav" type="audio" flags="" id="12" channel="0" origin=""/>
  </Sources>
  <Routes>
    <Route version="7003" id="100" name="Master" default-type="audio">
      <PresentationInfo order="0" flags="MasterOut,OrderSet"/>
      <Processor id="101" name="Amp" active="1" type="amp"><Controllable name="gaincontrol" value="1"/></Processor>
    </Route>{routes}
    <Route version="7003" id="300" name="Vox" default-type="audio">
      <PresentationInfo order="4" flags="AudioBus,OrderSet"/>
      <Controllable name="mute" value="0"/>
      <Processor id="3012" name="Amp" active="1" type="amp"><Automation><AutomationList automation-id="gain" id="3016" state="Off"/></Automation><Controllable name="gaincontrol" value="1"/></Processor>
    </Route>
  </Routes>
  <Playlists>{regions}{extra}
  </Playlists>
  <TempoMap superclocks-per-second="{SC}">
    <Tempos>{tempos}</Tempos>
    <Meters><Meter note-value="4" divisions-per-bar="4" sclock="0" quarters="0:0" bbt="1|1|0"/></Meters>
    <MusicTimes/>
  </TempoMap>
</Session>
"""


RAMP = ('<Tempo npm="100" enpm="140" note-type="4" type="Ramped" locked-to-meter="0" continuing="0" active="1" sclock="0" '
        'quarters="0:0" bbt="1|1|0" omega="1.4762849584278155e-10"/>'
        '<Tempo npm="140" enpm="140" note-type="4" type="Constant" locked-to-meter="0" continuing="0" active="1" '
        'sclock="2279182178" quarters="16:0" bbt="5|1|0" omega="0"/>')


class Base(unittest.TestCase):
    def make(self, text=None):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        d = Path(self._td.name) / "Demo"
        af = d / "interchange" / "Demo" / "audiofiles"
        af.mkdir(parents=True)
        for f in ("lead.wav", "harm.wav", "drums.wav"):
            sf.write(af / f, np.zeros(20 * SR, dtype=np.float32), SR, subtype="FLOAT")
        (d / "Demo.ardour").write_text(text or session(), encoding="utf-8")
        return d


class TempoRamps(Base):
    def test_a_ramp_is_read_exactly(self):
        midi = '<Playlist id="590" name="Keys" type="midi"><Region name="k" start="b0" length="b1920@b46080" type="midi"/></Playlist>'
        d = self.make(session(RAMP, extra=midi))
        p = PJ.load(d)
        self.assertFalse([w for w in p.warnings if "ramp" in w], p.warnings)          # no "read as a steady" any more
        root = p.native
        clock, bpm, bpb, n = AR.tempo_map(root, SR, 7003, [])
        self.assertEqual((bpm, n), (100.0, 2))
        self.assertAlmostEqual(clock.beats_to_s(16), 2279182178 / SC, places=7)        # the engine's own sclock
        self.assertAlmostEqual(clock.beats_to_s(8), 60 / (100 * 0.025) * math.log1p(0.025 * 8), places=9)
        self.assertAlmostEqual(clock.s_to_beats(clock.beats_to_s(11.3)), 11.3, places=9)
        self.assertAlmostEqual(clock.qpm_at(8), 120.0)
        # a region at quarter 24 (bar 7): the ramp, then 8 quarters at 140
        self.assertAlmostEqual(clock.pos("b46080"), 2279182178 / SC + 8 * 60 / 140, places=6)

    def test_points_from_a_tempo_line_steps_and_glides(self):
        line = [(0, 120), (14, 120), (16, 126), (30, 126), (32, 120), (64, 120)]       # glides of two beats
        pts = AA.from_beats(line)
        self.assertEqual([(x["beat"], x["bpm"], x["bpm_end"]) for x in pts],
                         [(0, 120, 120), (14, 120, 126), (16, 126, 126), (30, 126, 120), (32, 120, 120)])
        step = AA.from_beats([(0, 100), (8, 100), (8, 110), (16, 110), (16, 105), (24, 105)])
        self.assertEqual([(x["beat"], x["bpm"], x["bpm_end"]) for x in step], [(0, 100, 100), (8, 110, 110), (16, 105, 105)])
        self.assertEqual(AA.engine_points(pts)[1], {"bar": 4, "beat": 3, "bpm": 120, "bpm_end": 126})
        ramp = AA.from_beats([(0, 100), (16, 140)])
        self.assertAlmostEqual(AA.seconds(ramp, [16])[0], 2279182178 / SC, places=6)
        with self.assertRaises(ValueError):
            AA.from_beats([(0, 500)])

    def test_a_tempo_map_written_to_a_new_snapshot_reads_back_the_same(self):
        d = self.make()
        p = PJ.load(d)
        pts = AA.from_beats([(0, 100), (16, 140), (32, 140)])
        AA.write_tempo_file(p, pts)
        out = d / "Demo (tempo).ardour"
        AE.save(p, out)
        self.assertEqual(AE.check(d / "Demo.ardour", out, tempo=True), [])
        self.assertTrue(AE.check(d / "Demo.ardour", out))                              # without tempo=True: refused
        root = ET.parse(out).getroot()
        t = root.find("TempoMap/Tempos").findall("Tempo")
        self.assertEqual([(x.get("type"), x.get("sclock"), x.get("bbt")) for x in t],
                         [("Ramped", "0", "1|1|0"), ("Constant", "2279182178", "5|1|0")])
        self.assertAlmostEqual(float(t[0].get("omega")), 1.4762849584278155e-10, delta=1e-21)   # as the engine writes it
        q = PJ.load(out)
        self.assertEqual(q.tempo_changes, 2)
        self.assertEqual([c.start for c in q.tracks[0].clips], [0.0])                   # audio keeps its time

    def test_meter_changes_and_old_sessions_are_refused(self):
        d = self.make(session().replace('<Meters><Meter note-value="4" divisions-per-bar="4"', '<Meters><Meter note-value="4" divisions-per-bar="3"'))
        p = PJ.load(d)
        with self.assertRaises(ValueError) as e:
            AA.write_tempo_file(p, AA.from_beats([(0, 100)]))
        self.assertIn("3/4", str(e.exception))


class LevelAutomation(Base):
    def test_edge_points_are_gentle_s_curves(self):
        segs = [(2.0, 5.0, 0.0), (5.6, 8.0, -2.5), (8.6, 11.0, 0.0)]
        pts = AA.edge_points(segs, -6.0)
        self.assertEqual(pts[0][1], -6.0)
        self.assertEqual(min(v for _, v in pts), -8.5)
        args = {"track_id": "1", "control": "gain", "curve": "s_curve", "points": [{"time": t, "value": v} for t, v in pts],
                "start": pts[0][0], "end": pts[-1][0]}
        self.assertEqual(RULES.check(args, None, RULES.line_from(None, -6.0)), [])
        self.assertLess(RULES.steepest(pts), 7)
        with self.assertRaises(ValueError):                                             # over the 3 dB a line may move
            AA.edge_points([(0, 2, -3.0), (2.4, 4, 3.0)])
        self.assertEqual(AA.edge_points([(0, 2, 0.0)]), [])

    def test_written_into_a_new_snapshot_under_the_rules(self):
        d = self.make()
        p = PJ.load(d)
        lead = p.track("Lead Vocal")
        pts = AA.edge_points([(2.0, 5.0, 0.0), (5.6, 8.0, -2.0), (8.6, 11.0, 0.0)], -6.0206)
        n = AA.write_file(p, lead, "gain", pts)
        self.assertGreater(n, 20)
        out = d / "Demo (levels).ardour"
        AE.save(p, out)
        self.assertEqual(AE.check(d / "Demo.ardour", out, automation=True), [])
        q = PJ.load(out)
        env = q.track("Lead Vocal").envelopes["Volume"]
        self.assertAlmostEqual(min(v for _, v in env), 0.5 * 10 ** (-2 / 20), places=3)
        with self.assertRaises(ValueError) as e:                                        # it plays automation now
            AA.write_file(p, lead, "gain", pts)
        self.assertIn("already has automation", str(e.exception))

    def test_never_a_bus_that_carries_non_vocals(self):
        d = self.make(session(bus_members=("Lead Vocal", "Harmony", "Drums")))
        p = PJ.load(d)
        vox = p.track("Vox")
        self.assertEqual(RULES.non_vocal(AA.facts_of(p, vox)), ["Drums"])
        with self.assertRaises(ValueError) as e:
            AA.write_file(p, vox, "gain", AA.edge_points([(2.0, 5.0, -2.0)], 0.0))
        self.assertIn("Vox carries Drums", str(e.exception))

    def test_vocallevel_puts_trims_on_trim_and_the_evening_on_the_vocal_bus(self):
        from hypnomix.workflow import vocallevel_ardour as VA
        gains = {"Harmony": [(1, 3, -2.0), (3.5, 6, 0.0)], "__group__": [(1, 3, 0.0), (3.5, 6, 1.5)]}
        p = PJ.load(self.make())
        todo, notes = VA.plan_controls(p, gains, "Vox", ["Lead Vocal", "Harmony"])
        self.assertEqual([(n, c) for n, c, _ in todo], [("Harmony", "trim"), ("Vox", "gain")])
        p = PJ.load(self.make(session(bus_members=("Lead Vocal", "Harmony", "Drums"))))
        todo, notes = VA.plan_controls(p, gains, "Vox", ["Lead Vocal", "Harmony"])
        self.assertEqual([(n, c) for n, c, _ in todo], [("Harmony", "trim"), ("Lead Vocal", "gain"), ("Harmony", "gain")])
        self.assertIn("also carries Drums", notes[0])


FILTER = ('<Processor id="2209" name="ACE High/Low Pass Filter" active="1" type="luaproc"><Automation>'
          '<AutomationList automation-id="parameter-4" id="2210" interpolation-style="Logarithmic" state="Off"/>'
          '</Automation><Controllable name="Low Pass Cut off frequency" id="2211" flags="" value="16000" parameter="4"/>'
          '</Processor>')


class MotionSweeps(Base):
    def test_filter_risers_are_options_written_into_a_new_snapshot(self):
        from hypnomix.session import motion_ardour as MA
        text = session().replace('<Processor id="2202" name="Amp"', FILTER + '<Processor id="2202" name="Amp"')
        text = text.replace(f'length="{a(20)}@{a(0)}"', f'length="{a(80)}@{a(0)}"')
        d = self.make(text)
        for f in ("lead.wav", "harm.wav", "drums.wav"):
            sf.write(d / "interchange" / "Demo" / "audiofiles" / f, np.zeros(80 * SR, dtype=np.float32), SR, subtype="FLOAT")
        p = PJ.load(d)
        tg = MA.targets_file(p)
        self.assertEqual([(t["track"], t["control"], t["base"], t["high"]) for t in tg], [("Drums", "plugin:2209:4", 16000.0, False)])
        fs, meta = MA.propose(p, tg)
        self.assertEqual([f["where"] for f in fs], ["into bar 9", "into bar 17", "into bar 25", "into bar 33"])
        pts = fs[1]["move"]["points"]
        self.assertAlmostEqual(pts[0][0], 16 * 2.0 - 8 * 2.0)            # 8 bars of 2 s before bar 17
        self.assertAlmostEqual(pts[0][1], 16000 * 2 ** -3.2, places=1)    # 3.2 octaves under where it sits
        self.assertEqual(pts[-1], [32.0, 16000.0])                         # open again on the downbeat
        ns = SimpleNamespace(als=str(d), mix=None, style=str(d / "none.json"), json=None, engine=None,
                             apply="Demo (motion).ardour", ids="motion-2,motion-4")
        self.assertEqual(MA.main(ns), 0)
        q = PJ.load(d / "Demo (motion).ardour")
        al = next(x for x in q.native.iter("AutomationList") if x.get("automation-id") == "parameter-4")
        self.assertEqual((al.get("state"), len(al.findtext("events").split())), ("Play", 8))
        with self.assertRaises(SystemExit):                                # nothing by default: --ids
            MA.main(SimpleNamespace(**dict(vars(ns), ids=None, apply="Demo (m2).ardour")))


class TempoCommands(Base):
    def args(self, **kw):
        base = dict(conform=False, follow=True, anyway=False, replace_tempo=False, bpb=4, per="bar", engine=None,
                    apply=None)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_follow_makes_the_grid_follow_the_take(self):
        from hypnomix.session import tempo_ardour as TA
        d = self.make()
        p = PJ.load(d)
        t = p.track("Drums")
        clip = t.clips[0]
        # a take that speeds up a little: beats from 1.0 s, 0.5 s apart, getting 1% shorter each bar
        beats, x, period = [], 1.0, 0.5
        for bar in range(8):
            for _ in range(4):
                beats.append(x)
                x += period
            period *= 0.99
        m = dict(beats=beats, down=0, snapped=0.9)
        a = self.args(apply="Demo (tempo map).ardour")
        self.assertEqual(TA.follow(a, p, t, clip, m), 0)
        out = d / "Demo (tempo map).ardour"
        q = PJ.load(out)
        clock, *_ = AR.tempo_map(q.native, SR, 7003, [])
        for k in range(8):                                                           # bar lines land on the take's
            self.assertAlmostEqual(clock.beats_to_s(4 + 4 * k), beats[4 * k], delta=0.002)
        self.assertEqual(q.tracks[2].clips[0].start, 0.0)                             # the take stays as played
        with self.assertRaises(SystemExit):
            TA.follow(self.args(conform=True, follow=False, apply="x.ardour"), p, t, clip, m)

    def test_breathe_needs_grid_only_when_the_session_has_audio(self):
        from hypnomix.session import tempo_ardour as TA
        d = self.make()
        a = SimpleNamespace(sections="3-4:+2", mix=None, amount=1.0, glide=2.0, ritard=0.0, preview=None,
                            replace_tempo=False, engine=None, apply="Demo (breathing).ardour", grid_only=False)
        with self.assertRaises(SystemExit) as e:
            TA.breathe(a, d)
        self.assertIn("--grid-only", str(e.exception))
        a.grid_only = True
        self.assertEqual(TA.breathe(a, d), 0)
        q = PJ.load(d / "Demo (breathing).ardour")
        tempos = q.native.find("TempoMap/Tempos").findall("Tempo")
        self.assertEqual([(x.get("bbt"), x.get("type")) for x in tempos][:3],
                         [("1|1|0", "Constant"), ("2|3|0", "Ramped"), ("3|1|0", "Constant")])
        self.assertAlmostEqual(float(tempos[2].get("npm")), 122.4)


if __name__ == "__main__":
    unittest.main()
