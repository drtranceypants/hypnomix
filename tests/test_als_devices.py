"""als2ardour / import: EQ Eight, Glue Compressor and Saturator carried as ACE EQ (with its High Pass / Low Pass
bands), ACE Compressor (stereo) (with Range, Auto Release, Mix) and Hypnomix Saturator; what they cannot take listed,
never guessed. Small XML fixtures; one set converted and read back with the session reader."""
import itertools
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from tests import _isolate  # noqa: F401  (the test home)
from hypnomix.project import als_devices as AD
from tests.test_als2ardour import make_set


IDS = itertools.count(5000)


def m(tag, v):
    return f"<{tag}><Manual Value=\"{v}\"/><AutomationTarget Id=\"{next(IDS)}\"/></{tag}>"


def band(i, mode, freq, gain=0.0, q=0.71, on=True):
    return (f'<Bands.{i}><ParameterA>{m("IsOn", "true" if on else "false")}{m("Mode", mode)}{m("Freq", freq)}'
            f'{m("Gain", gain)}{m("Q", q)}</ParameterA></Bands.{i}>')


def eq8(bands, mode=0, scale=1, gain=0, adaptive="false", on="true"):
    return (f'<Eq8 Id="0">{m("On", on)}<Mode Value="{mode}"/>{m("GlobalGain", gain)}{m("Scale", scale)}'
            f'{"".join(bands)}<AdaptiveQ Value="{adaptive}"/>{m("AdaptiveQ", adaptive)}</Eq8>')


def glue_xml(thr=-20, ratio=1, attack=5, release=6, rng=3, makeup=2, dry_wet=0.6, clip="false", sc="false",
             sceq="false"):
    return (f'<GlueCompressor Id="1">{m("On", "true")}{m("Threshold", thr)}{m("Range", rng)}{m("Makeup", makeup)}'
            f'{m("Attack", attack)}{m("Ratio", ratio)}{m("Release", release)}{m("DryWet", dry_wet)}{m("PeakClipIn", clip)}'
            f'<SideChain>{m("OnOff", sc)}</SideChain><SideChainEq>{m("On", sceq)}</SideChainEq></GlueCompressor>')


def sat_xml(typ=0, drive=6, out=-3, dry_wet=0.5, color="true", base=0, depth=0, post_clip=0):
    return (f'<Saturator Id="2">{m("On", "true")}{m("PreDrive", drive)}{m("Type", typ)}{m("ColorOn", color)}'
            f'{m("BaseDrive", base)}{m("ColorFrequency", 1000)}{m("ColorDepth", depth)}{m("PostClip", post_clip)}'
            f'{m("PostDrive", out)}{m("DryWet", dry_wet)}</Saturator>')


def el(xml):
    return ET.fromstring(xml)


class EqEight(unittest.TestCase):
    def test_cuts_go_on_the_high_and_low_pass_bands_with_their_slope(self):
        ps, summary, notes = AD.eq8(el(eq8([band(0, 1, 90), band(7, 7, 15000)])))
        self.assertEqual(len(ps), 1)
        v = ps[0].values
        self.assertEqual((v["High Pass"], v["High Pass Frequency"], v["High Pass Slope"]), (1, 90.0, 12))
        self.assertEqual((v["Low Pass"], v["Low Pass Frequency"], v["Low Pass Slope"]), (1, 15000.0, 48))
        self.assertEqual(ps[0].uses_new, ["High Pass", "High Pass Frequency", "High Pass Slope", "Low Pass",
                                          "Low Pass Frequency", "Low Pass Slope"])
        self.assertIn("low cut 90 Hz 12 dB/oct", summary)
        self.assertFalse(notes, notes)
        ps, _, _ = AD.eq8(el(eq8([band(0, 0, 40)])))
        self.assertEqual(ps[0].values["High Pass Slope"], 48)                  # Live's mode 0 is the 48 dB/oct cut

    def test_shelves_bells_scale_and_gain(self):
        ps, _, notes = AD.eq8(el(eq8([band(0, 2, 100, 4), band(1, 3, 400, -3, q=2.0), band(2, 5, 8000, 2)],
                                     scale=0.5, gain=-1.5)))
        v = ps[0].values
        self.assertEqual((v["Filter L"], v["Frequency L"], v["Gain L"]), (1, 100.0, 2.0))      # Scale halves the gains
        self.assertEqual((v["Filter 1"], v["Frequency 1"], v["Gain 1"]), (1, 400.0, -1.5))
        self.assertAlmostEqual(v["Bandwidth 1"], AD.q_to_octaves(2.0), places=3)
        self.assertEqual((v["Filter H"], v["Gain H"], v["Master Gain"]), (1, 1.0, -1.5))
        self.assertEqual([v[f"Filter {n}"] for n in (2, 3, 4)], [0, 0, 0])
        self.assertNotIn("High Pass", v)                                         # no cut: no new control asked for
        self.assertFalse(notes, notes)

    def test_what_ace_eq_cannot_do_is_listed(self):
        ps, _, notes = AD.eq8(el(eq8([band(0, 1, 30, q=2.5), band(1, 4, 1000), band(2, 1, 60), band(3, 3, 500, 3),
                                      band(4, 3, 900, 1, on=False)], adaptive="true")))
        text = "\n".join(notes)
        self.assertIn("notch at 1000 Hz, is not carried", text)
        self.assertIn("a second low cut at 60 Hz", text)
        self.assertIn("Q 2.50 is not carried", text)
        self.assertIn("Adaptive Q is not carried", text)
        self.assertIn("1 switched-off band(s) left out", text)
        self.assertEqual(ps[0].values["High Pass Frequency"], 30.0)

    def test_more_than_four_bells_take_a_second_eq(self):
        ps, _, notes = AD.eq8(el(eq8([band(i, 3, 200 * (i + 1), 2) for i in range(6)])))
        self.assertEqual([p.name for p in ps], ["ACE EQ", "ACE EQ"])
        self.assertEqual([ps[1].values[f"Filter {n}"] for n in (1, 2, 3, 4)], [1, 1, 0, 0])
        self.assertEqual(ps[1].values["Frequency 2"], 1200.0)
        self.assertTrue(any("second ACE EQ" in x for x in notes))

    def test_out_of_range_values_are_set_to_the_nearest_and_listed(self):
        ps, _, notes = AD.eq8(el(eq8([band(0, 3, 22000, 15, q=18)], scale=2)))
        v = ps[0].values
        self.assertEqual((v["Frequency 1"], v["Gain 1"], v["Bandwidth 1"]), (20000.0, 20.0, 0.1))
        self.assertEqual(len([x for x in notes if "outside the plug-in's range" in x]), 3, notes)

    def test_lr_and_ms_modes_are_not_carried(self):
        for mode in (1, 2):
            ps, _, why = AD.eq8(el(eq8([band(0, 1, 90)], mode=mode)))
            self.assertIsNone(ps)
            self.assertIn("mode", why[0])


class Glue(unittest.TestCase):
    def test_range_auto_release_and_dry_wet(self):
        ps, summary, notes = AD.glue(el(glue_xml(ratio=1, attack=5, release=6, rng=3, dry_wet=0.6)))
        v = ps[0].values
        self.assertEqual((v["Ratio"], v["Attack"], v["Auto Release"], v["Range"], v["Mix"]), (4.0, 10.0, 1, 3.0, 60.0))
        self.assertEqual((v["Threshold"], v["Makeup"], v["Sidechain"]), (-20.0, 2.0, 0))
        self.assertAlmostEqual(v["Knee"], 4 / 6, places=3)
        self.assertIn("release Auto", summary)
        self.assertFalse(notes, notes)

    def test_a_plain_glue_asks_for_no_new_control(self):
        ps, _, _ = AD.glue(el(glue_xml(release=2, rng=70, dry_wet=1)))
        self.assertEqual(ps[0].values["Release"], 400.0)
        self.assertEqual(ps[0].uses_new, [])                                    # loads on an older plug-in as it is

    def test_what_it_cannot_take_is_listed_and_a_keyed_glue_is_not_carried(self):
        ps, _, notes = AD.glue(el(glue_xml(attack=0, clip="true", sceq="true")))
        text = "\n".join(notes)
        self.assertIn("Soft clip is not carried", text)
        self.assertIn("sidechain EQ is not carried", text)
        self.assertIn("Attack 0.01 ms is outside", text)
        self.assertEqual(ps[0].values["Attack"], 0.1)
        ps, _, why = AD.glue(el(glue_xml(sc="true")))
        self.assertIsNone(ps)
        self.assertIn("external sidechain", why[0])


class Saturator(unittest.TestCase):
    def test_curves_by_live_version(self):
        for typ, live, curve in ((0, 12, 1), (1, 12, 0), (6, 12, 2), (0, 11, 1), (1, 11, 0)):
            ps, _, _ = AD.saturator(el(sat_xml(typ=typ)), live)
            self.assertEqual(ps[0].values["Curve"], curve, (typ, live))
        for typ, live in ((2, 12), (3, 12), (5, 12), (7, 12), (5, 11), (6, 11)):
            ps, _, why = AD.saturator(el(sat_xml(typ=typ)), live)
            self.assertIsNone(ps, (typ, live))
            self.assertIn("is not one Hypnomix Saturator has", why[0])

    def test_drive_output_mix_and_what_is_left_out(self):
        ps, summary, notes = AD.saturator(el(sat_xml(drive=-20, out=-3, dry_wet=0.5, base=2, post_clip=1)), 12)
        v = ps[0].values
        self.assertEqual((v["Drive"], v["Output"], v["Mix"]), (-12.0, -3.0, 50.0))
        text = "\n".join(notes)
        self.assertIn("Drive -20.0 dB is outside", text)
        self.assertIn("Color filter", text)
        self.assertIn("Soft Clip is not carried", text)
        self.assertIn("not the same sound", text)
        self.assertIn("Analog Clip", summary)


class Written(unittest.TestCase):
    def test_the_processor_xml(self):
        ps, _, _ = AD.glue(el(glue_xml()))
        rt = ET.Element("Route")
        n = iter(range(1000, 2000))
        p = AD.write(rt, ps[0], lambda: str(next(n)))
        self.assertEqual((p.get("type"), p.get("unique-id"), p.get("count"), p.get("active")),
                         ("lv2", "urn:ardour:a-comp#stereo", "1", "1"))
        ports = {x.get("symbol"): x.get("value") for x in p.find("lv2")}
        self.assertEqual((ports["range"], ports["autorel"], ports["mix"], ports["rat"]), ("3", "1", "60", "4"))
        ctl = {c.get("name"): (c.get("parameter"), c.get("value")) for c in p.findall("Controllable")}
        self.assertEqual(ctl["Range"], ("16", "3"))
        self.assertEqual(ctl["Mix"], ("18", "60"))
        eq, _, _ = AD.eq8(el(eq8([band(0, 2, 100, 1)])))
        q = AD.write(rt, eq[0], lambda: str(next(n)))
        self.assertEqual(q.get("count"), "2")                                  # ACE EQ is mono: one per channel
        self.assertNotIn("hpon", {x.get("symbol") for x in q.find("lv2")})


GLUE_ON_LEAD = glue_xml(release=6, rng=3, dry_wet=0.6)


class Converted(unittest.TestCase):
    """A Live 12 set with the three devices, converted and read back with the session reader."""

    def test_the_session_has_the_plugins_and_the_report_says_what_came_across(self):
        from hypnomix import project
        from hypnomix.project import als2ardour as A
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            devs = (eq8([band(0, 1, 90), band(1, 4, 1000)]) + '<Reverb Id="5">' + m("On", "true") + '</Reverb>'
                    + GLUE_ON_LEAD + sat_xml(typ=1, drive=4))
            extra = A_TRACK.format(devs=devs, path=d / "vox.wav")
            als = make_set(d, extra=extra)
            out = d / "Demo (HypnoMix)"
            A.convert(als, out, log=lambda *x: None)
            sess = next(out.glob("*.ardour"))
            p = project.load(sess)
            t = p.track("Extra")
            self.assertEqual([x.name for x in t.devices], ["ACE EQ", "ACE Compressor (stereo)", "Hypnomix Saturator"])
            eqd, comp, sat = t.devices
            self.assertEqual((eqd.uid, eqd.params["High Pass"], eqd.params["High Pass Frequency"]), ("urn:ardour:a-eq", 1, 90))
            self.assertEqual((comp.params["Range"], comp.params["Auto Release"], comp.params["Mix"]), (3, 1, 60))
            self.assertEqual((sat.params["Curve"], sat.params["Drive"], sat.params["Mix"]), (0, 4, 50))
            from hypnomix.workflow import sidechain_project as SCP
            c = SCP.ace_settings(comp)
            self.assertEqual((c["range_db"], c["release_model"], c["dry_wet"]), (3.0, "ace-auto", 0.6))
            # the plug-ins sit after the trim and before the fader, as Live's devices sit before its mixer
            rt = next(r for r in ET.parse(sess).getroot().iter("Route") if r.get("name") == "Extra")
            kinds = [pr.get("type") for pr in rt.findall("Processor")]
            self.assertLess(kinds.index("trim"), kinds.index("lv2"))
            self.assertLess(len(kinds) - kinds[::-1].index("lv2"), kinds.index("amp") + 1)
            rep = (out / "IMPORT-REPORT.md").read_text(encoding="utf-8")
            self.assertIn("## Devices carried", rep)
            self.assertIn("EQ Eight -> ACE EQ (low cut 90 Hz 12 dB/oct)", rep)
            self.assertIn("notch at 1000 Hz, is not carried", rep)
            self.assertIn("Glue Compressor -> ACE Compressor (stereo)", rep)
            self.assertIn("Saturator -> Hypnomix Saturator (Soft Sine", rep)
            self.assertIn("Reverb", rep)                                         # still listed, not carried
            self.assertIn("EQ Eight -> ACE EQ, Reverb, Glue Compressor", rep)


A_TRACK = ('<AudioTrack Id="15"><Name><EffectiveName Value="Extra"/></Name><Color Value="2"/>'
           '<TrackGroupId Value="-1"/><AutomationEnvelopes><Envelopes/></AutomationEnvelopes>'
           '<DeviceChain><AudioOutputRouting><Target Value="AudioOut/Main"/></AudioOutputRouting>'
           '<Mixer><Volume><Manual Value="1"/><AutomationTarget Id="400"/></Volume><Pan><Manual Value="0"/>'
           '<AutomationTarget Id="401"/></Pan><Speaker><Manual Value="true"/><AutomationTarget Id="402"/></Speaker>'
           '<SoloSink Value="false"/><Sends/></Mixer><MainSequencer><Sample><ArrangerAutomation><Events>'
           '<AudioClip Id="20" Time="0"><Name Value="c20"/><CurrentStart Value="0"/><CurrentEnd Value="4"/>'
           '<Loop><LoopStart Value="0"/><LoopEnd Value="2"/><StartRelative Value="0"/><LoopOn Value="false"/></Loop>'
           '<Envelopes><Envelopes/></Envelopes><IsWarped Value="false"/><WarpMarkers/><SampleVolume Value="1"/>'
           '<Disabled Value="false"/><Fades><FadeInLength Value="0"/><FadeOutLength Value="0"/>'
           '<IsDefaultFadeIn Value="false"/><IsDefaultFadeOut Value="false"/></Fades><SampleRef><FileRef>'
           '<Path Value="{path}"/><RelativePath Value="vox.wav"/></FileRef></SampleRef></AudioClip>'
           '</Events></ArrangerAutomation></Sample></MainSequencer><DeviceChain><Devices>{devs}</Devices>'
           '</DeviceChain></DeviceChain></AudioTrack>')


if __name__ == "__main__":
    unittest.main()
