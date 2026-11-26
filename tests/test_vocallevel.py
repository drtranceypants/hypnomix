"""Vocal level consistency: a line that drops away is raised on the group, an upper part over the melody is lowered,
and the volume automation written keeps the existing curve with unique envelope Ids."""
import re
import unittest

import numpy as np

from hypnomix.session import vocallevel as VL

SR = 8000


def tone(f, secs, db, gaps):
    """A sung part: a tone at `db` dBFS with silences at the (t0, t1) gaps."""
    t = np.arange(int(secs * SR)) / SR
    y = (10 ** (db / 20) * np.sqrt(2) * np.sin(2 * np.pi * f * t)).astype(np.float32)
    for a, b in gaps:
        y[int(a * SR):int(b * SR)] = 0
    return y


GAPS = [(3.0, 3.5), (6.5, 7.0), (10.0, 10.5), (13.5, 14.0), (17.0, 17.5)]


class Plan(unittest.TestCase):
    def test_upper_part_over_the_melody_is_lowered(self):
        sig = {"Low": tone(220, 20.5, -20, GAPS), "High": tone(440, 20.5, -18, GAPS)}
        rows, findings, gains = VL.plan(sig, SR, melody="Low", order=["Low", "High"], jump=9, upper_under=1.5)
        self.assertTrue(rows)
        ups = [f for f in findings if f["kind"] == "upper-over-melody"]
        self.assertEqual(len(ups), len(rows))
        for _, _, g in gains["High"]:
            self.assertAlmostEqual(g, -3.5, delta=0.3)       # -18 -> 1.5 under -20

    def test_parts_below_the_melody_are_never_lowered(self):
        sig = {"Low": tone(220, 20.5, -15, GAPS), "Mel": tone(330, 20.5, -20, GAPS)}
        _, findings, gains = VL.plan(sig, SR, melody="Mel", order=["Low", "Mel"], jump=9)
        self.assertFalse([f for f in findings if f["kind"] == "upper-over-melody"])
        self.assertNotIn("Low", gains)

    def test_a_quiet_line_is_raised_on_the_group(self):
        y = tone(220, 20.5, -20, GAPS)
        y[int(7.0 * SR):int(10.0 * SR)] *= 10 ** (-4 / 20)  # one line 4 dB down
        rows, findings, gains = VL.plan({"Lead": y}, SR, melody="Lead", order=["Lead"], jump=1.5, keep_ending=0)
        jumps = [f for f in findings if f["kind"] == "vocal-line-jump"]
        self.assertEqual(len(jumps), 1)
        self.assertAlmostEqual(jumps[0]["t0"], 7.0, delta=0.1)
        self.assertAlmostEqual(jumps[0]["change_db"], 4.0, delta=0.4)

    def test_the_ending_is_not_raised(self):
        y = tone(220, 20.5, -20, GAPS)
        y[int(17.5 * SR):] *= 10 ** (-6 / 20)
        _, findings, gains = VL.plan({"Lead": y}, SR, melody="Lead", order=["Lead"], jump=1.5, keep_ending=1)
        self.assertTrue(all(g == 0 for _, _, g in gains["__group__"]))

    def test_long_phrases_are_cut_into_lines(self):
        y = tone(220, 30, -20, [])
        ls = VL.lines(y, SR, max_s=9.0)
        self.assertGreater(len(ls), 3)
        self.assertTrue(all(b - a <= 9.0 for a, b in ls))


SET = ('<Ableton><LiveSet><MasterTrack><DeviceChain><Mixer><Tempo><Manual Value="120" /></Tempo></Mixer></DeviceChain>'
       '</MasterTrack><Tracks>'
       '<AudioTrack Id="1"><Name><EffectiveName Value="Vox" /></Name><TrackGroupId Value="-1" />'
       '<AutomationEnvelopes><Envelopes>'
       '<AutomationEnvelope Id="0"><EnvelopeTarget><PointeeId Value="999" /></EnvelopeTarget><Automation><Events>'
       '<FloatEvent Id="0" Time="0" Value="0.5" /></Events></Automation></AutomationEnvelope>'
       '</Envelopes></AutomationEnvelopes>'
       '<DeviceChain><Mixer><Volume><Manual Value="1" /><AutomationTarget Id="77" /></Volume></Mixer></DeviceChain>'
       '</AudioTrack></Tracks></LiveSet></Ableton>')


class Write(unittest.TestCase):
    def test_new_envelope_gets_its_own_id_and_the_gain(self):
        x, k = VL.write_gains(SET, "Vox", [(1.0, 2.0, -6.0)])
        self.assertEqual(k, 1)
        ids = re.findall(r'<AutomationEnvelope Id="(\d+)"', x)
        self.assertEqual(len(ids), len(set(ids)))
        env = re.search(r'<PointeeId Value="77" />.*?</AutomationEnvelope>', x, re.S).group(0)
        pts = [(float(a) / 2, float(b)) for a, b in re.findall(r'Time="([^"]+)" Value="([^"]+)"', env) if float(a) >= 0]
        mid = [v for t, v in pts if 1.0 <= t <= 2.0]
        self.assertTrue(mid and all(abs(v - 10 ** (-6 / 20)) < 1e-3 for v in mid))
        self.assertTrue(all(abs(v - 1.0) < 1e-6 for t, v in pts if t < 0.8 or t > 2.2))

    def test_no_change_writes_nothing(self):
        x, k = VL.write_gains(SET, "Vox", [(1.0, 2.0, 0.0)])
        self.assertEqual((x, k), (SET, 0))


if __name__ == "__main__":
    unittest.main()
