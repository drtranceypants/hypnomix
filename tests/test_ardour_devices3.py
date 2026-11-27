"""HypnoMix Studio sessions with the newer devices: ACE Compressor's Range / Auto Release / Mix, ACE EQ's High Pass
band and Hypnomix Saturator, read from the session file and used by the compressor maths (`sidechain`), the devices
check, the sidechain check and the duck check. Small session fixtures, no engine."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from hypnomix import project
from hypnomix.engineer import devices as DV
from hypnomix.engineer import duck_ardour as DA
from hypnomix.engineer import sidechain as SC
from hypnomix.workflow import devices_project as DP
from hypnomix.workflow import sidechain_project as SCP
from tests.test_ardour_groups import ACE, Fixture, SR, a, region, route

EXTRAS = ('<Controllable name="Range" value="{rng}" parameter="16"/>'
          '<Controllable name="Auto Release" value="{auto}" parameter="17"/>'
          '<Controllable name="Mix" value="{mix}" parameter="18"/>')


def ctl(name, value, n):
    return f'<Controllable name="{name}" value="{value}" parameter="{n}"/>'


def comp(pid, thr=-30, ratio=4, attack=10, release=120, knee=1, makeup=0, sidechain=0, extras=None):
    """An ACE Compressor (stereo) on its own track; `extras` = dict(rng, auto, mix) or None (a session saved before)."""
    body = (ctl("Attack", attack, 0) + ctl("Release", release, 1) + ctl("Knee", knee, 2) + ctl("Ratio", ratio, 3)
            + ctl("Threshold", thr, 4) + ctl("Makeup", makeup, 5) + ctl("Sidechain", sidechain, 9) + ctl("Enable", 1, 10)
            + (EXTRAS.format(**extras) if extras else ""))
    return (f'<Processor id="{pid}" name="ACE Compressor (stereo)" active="1" type="lv2" '
            f'unique-id="urn:ardour:a-comp#stereo"><lv2/>{body}</Processor>')


def eq(pid, hp=None):
    """An ACE EQ, its tone bands flat; `hp` = None (an older session: no cut controls), 0 (band off) or 1 (on)."""
    body = "".join(ctl(f"Filter {k}", 0, 17 + i) for i, k in enumerate(("L", "1", "2", "3", "4", "H")))
    if hp is not None:
        body += ctl("High Pass", hp, 26) + ctl("High Pass Frequency", 90, 27) + ctl("High Pass Slope", 24, 28)
    return f'<Processor id="{pid}" name="ACE EQ" active="1" type="lv2" unique-id="urn:ardour:a-eq"><lv2/>{body}</Processor>'


def saturator(pid, drive, curve=1, mix=100, output=0):
    body = ctl("Drive", drive, 0) + ctl("Curve", curve, 1) + ctl("Output", output, 2) + ctl("Mix", mix, 3) + ctl("Enable", 1, 4)
    return (f'<Processor id="{pid}" name="Hypnomix Saturator" active="1" type="lv2" '
            f'unique-id="urn:hypnomix:saturator"><lv2/>{body}</Processor>')


def one_track_session(procs):
    routes = route(10, "Master", 0, "MasterOut", outs=None) + route(100, "Keys", 1, "AudioTrack", procs=procs, playlist=901)
    return (f'<?xml version="1.0" encoding="UTF-8"?><Session version="7004" name="Demo" sample-rate="{SR}">'
            f'<Sources><Source name="s1.wav" type="audio" id="601"/></Sources><Routes>{routes}</Routes>'
            f'<Playlists><Playlist id="901" name="p1" type="audio">{region(801, 601, 8.0)}</Playlist></Playlists>'
            f'<TempoMap superclocks-per-second="282240000"><Tempos><Tempo npm="120" enpm="120" note-type="4" '
            f'type="Constant" quarters="0:0" sclock="0"/></Tempos><Meters><Meter divisions-per-bar="4" note-value="4"/>'
            f'</Meters></TempoMap></Session>')


def keys_audio(level=0.5):
    """Chords in phrases (a part that compresses), with real energy at 50 Hz (rumble a low cut is for)."""
    t = np.arange(int(8 * SR)) / SR
    env = 0.4 + 0.6 * ((t % 1.0) < 0.6)
    y = (np.sin(2 * np.pi * 330 * t) + 0.7 * np.sin(2 * np.pi * 415 * t) + 0.8 * np.sin(2 * np.pi * 50 * t)) * env
    return level * y / np.abs(y).max()


class Maths(unittest.TestCase):
    def test_mix_is_heard_as_the_dry_signal_mixed_back_in(self):
        gr = np.array([0.0, -10.0, -60.0])
        self.assertTrue(np.array_equal(SC.heard(gr, dict(dry_wet=1.0)), gr))
        h = SC.heard(gr, dict(dry_wet=0.5))
        self.assertAlmostEqual(h[1], 20 * np.log10(0.5 + 0.5 * 10 ** -0.5), places=9)      # -3.6 dB
        self.assertGreater(h[2], -6.03)                                                       # never past the dry half
        self.assertTrue(np.all(SC.heard(gr, dict(dry_wet=0.0)) == 0))

    def test_range_caps_the_reduction(self):
        lvl = np.full(SR // 2, -6.0)
        c = dict(threshold_db=-30, ratio=10, knee=0, attack=1, release=50, range_db=3.0)
        self.assertGreaterEqual(SC.gain_reduction(lvl, c).min(), -3.0 - 1e-9)
        self.assertLess(SC.gain_reduction(lvl, dict(c, range_db=None)).min(), -20)

    def test_ace_auto_release_lets_a_short_peak_go_faster_than_a_long_passage(self):
        def recovery_ms(hold_s):
            n_hold, n_after = int(hold_s * SC.SR), int(3 * SC.SR)
            lvl = np.concatenate([np.full(n_hold, 0.0), np.full(n_after, -80.0)])
            c = dict(threshold_db=-20, ratio=20, knee=0, attack=1, release=150, release_model="ace-auto")
            g = SC.gain_reduction(lvl, c)
            depth = g[n_hold - 1]
            back = np.argmax(g[n_hold:] > 0.25 * depth)                  # 75 % of the reduction recovered
            return 1000 * back / SC.SR
        fast, slow = recovery_ms(0.03), recovery_ms(2.0)
        self.assertLess(fast, 150)                                         # the plug-in: about 70 ms
        self.assertGreater(slow, 600)                                      # the plug-in: about 1.3 s
        manual = dict(threshold_db=-20, ratio=20, knee=0, attack=1, release=150)
        lvl = np.concatenate([np.full(SC.SR * 2, 0.0), np.full(SC.SR, -80.0)])
        self.assertFalse(np.allclose(SC.gain_reduction(lvl, manual), SC.gain_reduction(lvl, dict(manual, release_model="ace-auto"))))


class AceSettings(unittest.TestCase):
    def device(self, xml):
        from hypnomix.project.ardour import plugin_devices
        import xml.etree.ElementTree as ET
        return plugin_devices(ET.fromstring(f"<Route>{xml}</Route>"))[0]

    def test_range_auto_release_and_mix_are_read(self):
        c = SCP.ace_settings(self.device(comp(1, extras=dict(rng=4, auto=1, mix=70))))
        self.assertEqual((c["range_db"], c["auto_release"], c["release_model"], c["dry_wet"]), (4.0, True, "ace-auto", 0.7))
        self.assertEqual(c["knee"], 6.0)
        v = SCP.ace_values(c)
        self.assertEqual((v["Range"], v["Auto Release"], v["Mix"]), (4.0, 1, 70.0))
        self.assertIn("Auto Release", SCP.describe_ace(c))
        self.assertIn("Range 4 dB", SCP.describe_ace(c))
        self.assertIn("Mix 70%", SCP.describe_ace(c))

    def test_a_session_saved_before_the_new_controls_reads_as_the_plugin_defaults(self):
        for extras in (None, dict(rng=60, auto=0, mix=100)):
            c = SCP.ace_settings(self.device(comp(1, extras=extras)))
            self.assertEqual((c["range_db"], c["auto_release"], c["release_model"], c["dry_wet"]), (None, False, None, 1.0))
            v = SCP.ace_values(c)
            self.assertFalse({"Range", "Auto Release", "Mix"} & set(v), v)       # nothing asked of an older plug-in


class DevicesCheck(unittest.TestCase):
    """`scan`'s devices group on a HypnoMix Studio session."""

    def run_check(self, procs, level=0.5):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "Demo"
            audio = d / "interchange" / "Demo" / "audiofiles"
            audio.mkdir(parents=True)
            sf.write(audio / "s1.wav", keys_audio(level), SR)
            (d / "Demo.ardour").write_text(one_track_session(procs), encoding="utf-8")
            p = project.load(d)
            render = Path(td) / "Keys.wav"
            sf.write(render, keys_audio(level), SR)
            fs, notes = DP.g_devices(p, SimpleNamespace(files={"Keys": render}), Path(td), None, {"Keys": "keys"})
        return fs, notes

    def test_an_ace_compressor_is_judged_and_its_settings_listed(self):
        fs, notes = self.run_check(eq(1, hp=1) + comp(2, thr=-2, ratio=2))
        c = [f for f in fs if f["kind"] == "compressor"]
        self.assertEqual(len(c), 1, fs)
        self.assertIn("ACE Compressor 'ACE Compressor (stereo)'", c[0]["problem"])
        self.assertIn("barely works", c[0]["problem"])                           # its threshold is over the part
        self.assertEqual(c[0]["applies"], "manual")
        self.assertNotIn("Sidechain", c[0]["ace"]["values"])
        self.assertLess(c[0]["ace"]["values"]["Threshold"], -2)
        self.assertIn("Set these in the device in HypnoMix Studio", c[0]["fix"])
        self.assertFalse([f for f in fs if f["kind"] == "eq-lowcut"])           # the EQ's High Pass band is on
        self.assertTrue(any("ACE Compressor(s) judged" in n for n in notes))

    def test_no_high_pass_on_the_eq_gets_the_low_cut_suggestion(self):
        for hp in (0, None):                                                       # band off, or a session from before
            fs, _ = self.run_check(eq(1, hp=hp))
            lc = [f for f in fs if f["kind"] == "eq-lowcut"]
            self.assertEqual(len(lc), 1, fs)
            self.assertIn("High Pass band", lc[0]["fix"])

    def test_range_is_simulated(self):
        free, _ = self.run_check(comp(2, thr=-40, ratio=10, extras=dict(rng=60, auto=0, mix=100)))
        capped, _ = self.run_check(comp(2, thr=-40, ratio=10, extras=dict(rng=2, auto=0, mix=100)))
        med = lambda fs: float(fs[0]["problem"].split("turns the part down ")[1].split(" dB")[0])
        self.assertGreater(med(free), 10)
        self.assertLessEqual(med(capped), 2.05)

    def test_a_parallel_compressor_is_listed_with_what_is_heard_not_judged(self):
        fs, _ = self.run_check(comp(2, thr=-40, ratio=10, extras=dict(rng=60, auto=0, mix=50)))
        self.assertEqual([f["kind"] for f in fs], ["ace-parallel"], fs)
        self.assertIn("parallel compression", fs[0]["problem"])
        self.assertIn("isn't judged", fs[0]["problem"])

    def test_the_level_after_a_parallel_compressor_is_modelled(self):
        # a second compressor after it is judged (not "the level reaching it is unknown")
        fs, _ = self.run_check(comp(2, thr=-40, ratio=10, extras=dict(rng=60, auto=0, mix=50)) + comp(3, thr=-20))
        self.assertEqual([f["kind"] for f in fs], ["ace-parallel", "compressor"], fs)

    def test_a_hard_driven_saturator_is_flagged_and_the_chain_after_it_still_judged(self):
        fs, _ = self.run_check(saturator(1, drive=24, curve=2) + comp(2, thr=-20))
        sat = [f for f in fs if f["kind"] == "saturator-drive"]
        self.assertEqual(len(sat), 1, fs)
        self.assertIn("Hard Clip", sat[0]["problem"])
        self.assertLess(sat[0]["settings"]["Drive"], 24)
        self.assertIn("compressor", [f["kind"] for f in fs])                     # the level after it is modelled
        fs, _ = self.run_check(saturator(1, drive=3, curve=0))
        self.assertFalse([f for f in fs if f["kind"] == "saturator-drive"])      # a touch of Soft Sine: fine

    def test_a_compressor_with_its_sidechain_on_and_no_key_does_nothing(self):
        fs, notes = self.run_check(comp(2, sidechain=1))
        self.assertFalse([f for f in fs if f["kind"] == "compressor"])
        self.assertTrue(any("nothing keys it" in n for n in notes), notes)

    def test_after_an_unmodelled_plugin_it_is_not_judged(self):
        lim = '<Processor id="9" name="Hypnomix Limiter" active="1" type="lv2" unique-id="urn:hypnomix:limiter"><lv2/></Processor>'
        fs, _ = self.run_check(lim + comp(2))
        self.assertEqual([f["kind"] for f in fs], ["unknown-level"], fs)


class SidechainAndDuck(Fixture):
    def test_a_keyed_compressor_with_mix_under_100_is_not_judged(self):
        t = (self.dir / "Song.ardour").read_text(encoding="utf-8")
        t = t.replace('<Controllable name="Enable" value="1" parameter="10"/>',
                      '<Controllable name="Enable" value="1" parameter="10"/>' + EXTRAS.format(rng=60, auto=0, mix=40), 1)
        (self.dir / "Song.ardour").write_text(t, encoding="utf-8")
        res = SCP.analyse(project.load(self.dir))
        self.assertIsNone(res[0][1])
        self.assertIn("Mix is at 40 %", res[0][2])

    def test_the_sidechain_suggestion_turns_auto_release_off_and_lifts_a_short_range(self):
        t = (self.dir / "Song.ardour").read_text(encoding="utf-8")
        t = t.replace('<Controllable name="Enable" value="1" parameter="10"/>',
                      '<Controllable name="Enable" value="1" parameter="10"/>' + EXTRAS.format(rng=1, auto=1, mix=100), 1)
        (self.dir / "Song.ardour").write_text(t, encoding="utf-8")
        p = project.load(self.dir)
        fs = SCP.findings(p, SCP.analyse(p), None)
        v = fs[0]["ace"]["values"]
        self.assertEqual((v.get("Auto Release"), v.get("Range")), (0, 60.0), v)
        self.assertIn("Range 1 dB", fs[0]["problem"])                            # what it is now, said

    def test_duck_tune_sets_mix_to_100_and_range_off(self):
        from tests.test_ardour_groups import DuckTest
        DuckTest.tune_session(self, active="1", enable="1")
        t = (self.dir / "Song.ardour").read_text(encoding="utf-8")
        t = t.replace('<Controllable name="Enable" value="1" parameter="10"/><Processor id="7502"',
                      '<Controllable name="Enable" value="1" parameter="10"/>' + EXTRAS.format(rng=1, auto=0, mix=30)
                      + '<Processor id="7502"', 1)
        (self.dir / "Song.ardour").write_text(t, encoding="utf-8")
        p = project.load(self.dir)
        props, _ = DA.propose(p)
        tune = [x for x in props if x["kind"] == "tune"]
        self.assertEqual(len(tune), 1, props)
        self.assertTrue(any("Mix is at 30 %" in x for x in tune[0]["problems"]), tune[0]["problems"])
        self.assertTrue(any("Range (1 dB)" in x for x in tune[0]["problems"]), tune[0]["problems"])
        v = DA.findings(tune)[0]["ardour"]["values"]
        self.assertEqual((v["Mix"], v["Range"]), (100.0, 60.0), v)


class LiveDryWet(unittest.TestCase):
    """The same maths in a Live set's devices check: Glue's Dry/Wet is heard, a parallel one is listed, not judged."""

    def test_glue_at_half_wet_is_parallel(self):
        import xml.etree.ElementTree as ET
        m = lambda tag, v: f"<{tag}><Manual Value=\"{v}\"/></{tag}>"
        glue = (f'<GlueCompressor Id="1">{m("On", "true")}{m("Threshold", -30)}{m("Ratio", 1)}{m("Attack", 3)}'
                f'{m("Release", 1)}{m("Range", 70)}{m("Makeup", 0)}{m("DryWet", 0.5)}</GlueCompressor>')
        t = ET.fromstring(f'<AudioTrack><DeviceChain><DeviceChain><Devices>{glue}</Devices></DeviceChain></DeviceChain>'
                          f'</AudioTrack>')
        x = keys_audio()[:: SR // SC.SR] if SR != SC.SR else keys_audio()
        out, _ = DV.review_track("Keys", "other", t, x, 120)
        self.assertEqual([o["kind"] for o in out], ["unknown"], out)
        self.assertIn("Dry/Wet 50 %", out[0]["problem"])


if __name__ == "__main__":
    unittest.main()
