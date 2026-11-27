"""plugrender: plug-in state blobs round-trip in the formats pedalboard reads, chains are read from the set's XML,
and plug-ins are skipped (not fatal) when pedalboard is missing."""
import plistlib, struct, sys, unittest
import xml.etree.ElementTree as ET
from unittest import mock

import numpy as np

from hypnomix.session import plugrender as P
from hypnomix.session import render as R

CC = lambda b: struct.unpack(">I", b)[0]
PROC = bytes(range(40)) + b"settings"
CTRL = b"\x01\x02\x03"
AU_PLIST = plistlib.dumps({"type": 1635083896, "subtype": 1, "manufacturer": 2, "version": 0, "name": "Untitled",
                           "data": b"\x00\x01\x02"}, fmt=plistlib.FMT_XML)

TRACK = f"""
<AudioTrack Id="7">
  <Name><EffectiveName Value="Lead" /></Name>
  <DeviceChain>
    <Mixer><Volume><Manual Value="0.5" /></Volume><Pan><Manual Value="0" /></Pan></Mixer>
    <DeviceChain><Devices>
      <PluginDevice Id="1">
        <On><Manual Value="true" /></On>
        <UserName Value="My EQ" />
        <PluginDesc><Vst3PluginInfo Id="0">
          <Preset><Vst3Preset Id="2">
            <Uid><Fields.0 Value="-1" /><Fields.1 Value="0" /><Fields.2 Value="1" /><Fields.3 Value="2" /></Uid>
            <ProcessorState>
              {PROC.hex().upper()}
            </ProcessorState>
            <ControllerState>{CTRL.hex().upper()}</ControllerState>
          </Vst3Preset></Preset>
          <Name Value="Some EQ" />
        </Vst3PluginInfo></PluginDesc>
        <ParameterList>
          <PluginFloatParameter Id="0"><ParameterName Value="Gain" />
            <ParameterValue><Manual Value="0.25" /></ParameterValue></PluginFloatParameter>
          <PluginFloatParameter Id="1"><ParameterName Value="Unread" />
            <ParameterValue><Manual Value="0.1234567687" /></ParameterValue></PluginFloatParameter>
        </ParameterList>
      </PluginDevice>
      <AuPluginDevice Id="3">
        <On><Manual Value="false" /></On>
        <PluginDesc><AuPluginInfo Id="0">
          <ComponentType Value="{CC(b'aufx')}" /><ComponentSubType Value="{CC(b'Abcd')}" />
          <ComponentManufacturer Value="{CC(b'Mfgr')}" />
          <Name Value="Some Reverb" /><Manufacturer Value="Maker" />
          <Preset><AuPreset Id="4"><Buffer>{AU_PLIST.hex().upper()}</Buffer></AuPreset></Preset>
        </AuPluginInfo></PluginDesc>
      </AuPluginDevice>
      <PluginDevice Id="5">
        <On><Manual Value="true" /></On>
        <PluginDesc><VstPluginInfo Id="0"><PlugName Value="Old Clipper" />
          <Preset><VstPreset Id="6"><Buffer>00FF</Buffer></VstPreset></Preset></VstPluginInfo></PluginDesc>
      </PluginDevice>
      <StereoGain Id="8"><On><Manual Value="true" /></On><Gain><Manual Value="0.5" /></Gain></StereoGain>
      <Eq8 Id="9"><On><Manual Value="true" /></On></Eq8>
      <Saturator Id="12"><On><Manual Value="true" /></On></Saturator>
      <MxDeviceAudioEffect Id="10"><On><Manual Value="true" /></On><UserName Value="Tool" /></MxDeviceAudioEffect>
      <AudioEffectGroupDevice Id="11"><On><Manual Value="true" /></On></AudioEffectGroupDevice>
    </Devices></DeviceChain>
  </DeviceChain>
</AudioTrack>"""


class StateBlobs(unittest.TestCase):
    def test_juce_base64_round_trip(self):
        rng = np.random.default_rng(3)
        for n in (0, 1, 2, 3, 4, 5, 64, 1001):
            b = bytes(rng.integers(0, 256, n, dtype=np.uint8))
            s = P.juce_b64encode(b)
            self.assertTrue(s.startswith(f"{n}."))
            self.assertTrue(set(s.split(".", 1)[1]) <= set(P.JUCE_B64))
            self.assertEqual(P.juce_b64decode(s), b)

    def test_juce_base64_bit_order(self):
        # JUCE packs the lowest bits first: 0xFF -> 63 ('+') then the top two bits (3 -> 'C')
        self.assertEqual(P.juce_b64encode(b"\xff"), "1.+C")
        self.assertEqual(P.juce_b64decode("1.+C"), b"\xff")

    def test_vst3_blob_round_trip(self):
        blob = P.vst3_state(PROC, CTRL)
        magic, size = struct.unpack("<II", blob[:8])
        self.assertEqual(magic, 0x21324356)
        self.assertEqual(size, len(blob) - 9)          # JUCE copyXmlToBinary: size excludes header and the NUL
        self.assertEqual(blob[-1:], b"\0")
        self.assertIn(b"<VST3PluginState><IComponent>", blob)
        self.assertEqual(P.vst3_parts(blob), (PROC, CTRL))
        self.assertEqual(P.vst3_parts(P.vst3_state(PROC)), (PROC, None))

    def test_bad_blobs_are_refused(self):
        with self.assertRaises(ValueError):
            P.binary_to_xml(b"\x00" * 16)
        with self.assertRaises(ValueError):
            P.juce_b64decode("abc")

    def test_au_state_is_the_same_plist_in_binary(self):
        out = P.au_state(AU_PLIST)
        self.assertTrue(out.startswith(b"bplist00"))
        self.assertEqual(plistlib.loads(out), plistlib.loads(AU_PLIST))

    def test_juce_settings_compare(self):
        def state(xml):
            inner = P.xml_to_binary(xml)
            return P.vst3_state(b"VstW\x00\x00\x00\x08" + inner)
        a = state('<P gain="1.5" freq="4150.0" mode="2"/>')
        b = state('<P gain="1.5" freq="4100.0" mode="2"/>')
        m = P.settings_match(a, b)
        self.assertEqual((m["matched"], m["compared"]), (2, 3))
        self.assertIn("freq", m["differ"][0])
        self.assertIsNone(P.settings_match(P.vst3_state(b"opaque"), b))


class Chains(unittest.TestCase):
    def setUp(self):
        self.track = ET.fromstring(TRACK)
        self.chain = P.chain_of(self.track)

    def test_kinds_and_states(self):
        kinds = [d["kind"] for d in self.chain]
        self.assertEqual(kinds, ["vst3", "au", "vst2", "stock", "stock", "live", "m4l", "rack"])
        v3, au, v2 = self.chain[:3]
        self.assertEqual((v3["name"], v3["label"], v3["on"]), ("Some EQ", "My EQ", True))
        self.assertEqual((v3["processor"], v3["controller"]), (PROC, CTRL))
        self.assertEqual(v3["uid"], "FFFFFFFF0000000000000001" + "00000002")
        self.assertEqual(v3["saved_params"], {"Gain": 0.25})        # Live's placeholder value is left out
        self.assertEqual(P.vst3_parts(P.plugin_state(v3)), (PROC, CTRL))
        self.assertFalse(au["on"])
        self.assertEqual(au["codes"], ("aufx", "Abcd", "Mfgr"))
        self.assertEqual(plistlib.loads(P.plugin_state(au))["name"], "Untitled")
        self.assertEqual((v2["name"], v2["chunk"]), ("Old Clipper", b"\x00\xff"))

    def test_list_lines(self):
        lines = dict(P.describe(d) for d in self.chain)
        self.assertEqual(lines["Some Reverb"], "off: skipped")
        self.assertEqual(lines["Old Clipper"], "VST2: not supported")
        self.assertEqual(lines["Utility (gain)"], "Live device: HypnoMix model")
        self.assertEqual(lines["EQ Eight"], "Live device: HypnoMix model")
        self.assertIn("no model", lines["Saturator"])

    def test_vst2_is_refused_with_a_reason(self):
        plan = P.prepare(self.chain[2], do_probe=False)
        self.assertFalse(plan["ok"])
        self.assertIn("VST2", plan["error"])


class WithoutPedalboard(unittest.TestCase):
    def renderer(self):
        r = P.SetRenderer.__new__(P.SetRenderer)
        r.R, r.sr, r.no_stock, r.do_probe = R, 44100, False, True
        r.report, r.warn, r.cache, r._busy = {}, [], {}, set()
        return r

    def test_plugins_skipped_track_still_renders(self):
        t = ET.fromstring(TRACK)
        y = np.ones((1000, 2)) * 0.5
        with mock.patch.dict(sys.modules, {"pedalboard": None}):
            self.assertFalse(P.have_pedalboard())
            r = self.renderer()
            out = r.run_chain(t, y)
        np.testing.assert_allclose(out, y * 0.5)                    # Utility gain 0.5 still applied
        st = {d["device"]: d["status"] for d in r.report["Lead"]["devices"]}
        self.assertIn("pedalboard is not installed", st["Some EQ"])
        self.assertEqual(st["Some Reverb"], "skipped: switched off")
        self.assertTrue(st["EQ Eight"].startswith("rendered"))
        self.assertIn("no HypnoMix model", st["Saturator"])
        self.assertIn("Max for Live", st["Tool"])
        self.assertTrue(st["Utility (gain)"].startswith("rendered"))

    def test_no_stock(self):
        t = ET.fromstring(TRACK)
        r = self.renderer()
        r.no_stock = True
        with mock.patch.dict(sys.modules, {"pedalboard": None}):
            out = r.run_chain(t, np.ones((10, 2)))
        np.testing.assert_allclose(out, 1.0)
        self.assertIn("--no-stock", {d["device"]: d["status"] for d in r.report["Lead"]["devices"]}["Utility (gain)"])

    def test_mixer_fader_and_centre_pan(self):
        t = ET.fromstring(TRACK)
        r = self.renderer()
        r.aa = mock.Mock(envelopes=mock.Mock(return_value=([], {})))
        out = r.mixer(t, np.ones((10, 2)))
        np.testing.assert_allclose(out, 0.5)                        # fader 0.5, centre pan is unity on both sides


if __name__ == "__main__":
    unittest.main()
