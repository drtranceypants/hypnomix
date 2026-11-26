"""Vocal level consistency: a line that drops away is raised (at most 3 dB), an upper part over the melody is lowered
(at most 4 dB), lines where the melody rests are judged on the whole stack, the automation written is smooth S-curves
that keep the existing curve with unique envelope Ids, and a group holding non-vocals is never automated."""
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
        y[int(7.0 * SR):int(10.0 * SR)] *= 10 ** (-2.5 / 20)  # one line 2.5 dB down
        rows, findings, gains = VL.plan({"Lead": y}, SR, melody="Lead", order=["Lead"], jump=1.5, keep_ending=0)
        jumps = [f for f in findings if f["kind"] == "vocal-line-jump"]
        self.assertEqual(len(jumps), 1)
        self.assertAlmostEqual(jumps[0]["t0"], 7.0, delta=0.1)
        self.assertAlmostEqual(jumps[0]["change_db"], 2.5, delta=0.3)

    def test_line_moves_are_capped_at_3_db(self):
        y = tone(220, 20.5, -20, GAPS)
        y[int(7.0 * SR):int(10.0 * SR)] *= 10 ** (-8 / 20)    # 8 dB down: raised 3, the rest by ear
        _, findings, gains = VL.plan({"Lead": y}, SR, melody="Lead", order=["Lead"], jump=1.5, keep_ending=0)
        self.assertTrue(all(abs(g) <= 3.0 + 1e-9 for _, _, g in gains["__group__"]))
        j = [f for f in findings if f["kind"] == "vocal-line-jump" and f["change_db"] > 0]
        self.assertEqual(j[0]["change_db"], 3.0)
        self.assertIn("capped", j[0]["fix"])

    def test_upper_trims_are_capped_at_4_db(self):
        sig = {"Low": tone(220, 20.5, -24, GAPS), "High": tone(440, 20.5, -16, GAPS)}   # 8 dB over, 9.5 to fix
        _, _, gains = VL.plan(sig, SR, melody="Low", order=["Low", "High"], jump=9)
        self.assertTrue(all(g == -4.0 for _, _, g in gains["High"]))

    def test_harmony_only_line_is_measured_on_the_stack(self):
        """Melody lowest by --order, silent on one line the harmonies sing: that line is a line, at the harmonies'
        level; it is neither read as 13 dB quiet nor boosted, and the harmonies are not trimmed against silence."""
        mel = tone(220, 20.5, -20, GAPS)
        mel[int(7.0 * SR):int(10.0 * SR)] = 0
        h1, h2 = tone(330, 20.5, -23, GAPS), tone(440, 20.5, -23, GAPS)
        h1[int(7.0 * SR):int(10.0 * SR)] *= 10 ** (2.5 / 20)
        h2[int(7.0 * SR):int(10.0 * SR)] *= 10 ** (2.5 / 20)   # the harmonies carry that line at the stack's level
        rows, findings, gains = VL.plan({"Mel": mel, "H1": h1, "H2": h2}, SR, melody="Mel",
                                        order=["Mel", "H1", "H2"], jump=1.5, keep_ending=0)
        r = next(r for r in rows if abs(r["t0"] - 7.0) < 0.1)
        self.assertTrue(r["melody_resting"])
        self.assertFalse(r["gain"])
        self.assertLess(abs(r["vs_neighbours"] or 0), 1.5)
        self.assertTrue(all(abs(g) < 1e-9 for a, _, g in gains["__group__"] if abs(a - 7.0) < 0.1))
        self.assertTrue(all(abs(g) <= 3 for _, _, g in gains["__group__"]))

    def test_upper_rule_skipped_where_the_melody_is_far_under_its_usual_level(self):
        mel = tone(220, 20.5, -20, GAPS)
        mel[int(7.0 * SR):int(10.0 * SR)] *= 10 ** (-9 / 20)    # 9 dB under its median: the harmony carries it
        hi = tone(440, 20.5, -23, GAPS)
        rows, findings, gains = VL.plan({"Mel": mel, "Hi": hi}, SR, melody="Mel", order=["Mel", "Hi"], jump=9)
        self.assertTrue(all(g == 0 for a, _, g in gains["Hi"]))
        self.assertFalse([f for f in findings if f["kind"] == "upper-over-melody"])
        self.assertTrue(next(r for r in rows if abs(r["t0"] - 7.0) < 0.1)["melody_resting"])

    def test_lines_come_from_the_whole_stack(self):
        a = tone(220, 10, -20, [(4.0, 10)])
        b = tone(330, 10, -20, [(0, 4.5)])                       # the melody sings, then only the harmony
        rows, _, _ = VL.plan({"A": a, "B": b}, SR, melody="A", order=["A", "B"], jump=9)
        self.assertEqual([round(r["t0"], 1) for r in rows], [0.0, 4.5])

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


def env_points(x, pointee="77"):
    env = re.search(r'<PointeeId Value="%s" />.*?</AutomationEnvelope>' % pointee, x, re.S).group(0)
    return [(float(a) / 2, float(b)) for a, b in re.findall(r'Time="([^"]+)" Value="([^"]+)"', env) if float(a) >= 0]


def db(v):
    return 20 * np.log10(v)


def db_at(x, t, pointee="77"):
    pts = env_points(x, pointee)
    return db(float(np.interp(t, [p[0] for p in pts], [p[1] for p in pts])))


class Write(unittest.TestCase):
    def test_new_envelope_gets_its_own_id_and_the_gain(self):
        x, k = VL.write_gains(SET, "Vox", [(1.0, 5.0, -3.0)])
        self.assertEqual(k, 1)
        ids = re.findall(r'<AutomationEnvelope Id="(\d+)"', x)
        self.assertEqual(len(ids), len(set(ids)))
        pts = env_points(x)
        for t in (1.0, 2.0, 3.0, 4.0, 5.0):                      # the whole line sits at the gain
            self.assertAlmostEqual(db_at(x, t), -3.0, delta=0.05)
        self.assertTrue(all(abs(v - 1.0) < 1e-3 for t, v in pts if t > 6.3 or t < -0.3))

    def test_changes_are_smooth_s_curves_not_steps(self):
        x, _ = VL.write_gains(SET, "Vox", [(1.0, 5.0, -3.0), (5.3, 9.0, 3.0), (9.3, 12.0, -3.0)])
        pts = env_points(x)
        ts = np.array([t for t, _ in pts])
        self.assertLessEqual(np.diff(ts).max(), 4.0)
        moving = [(a, b) for a, b in zip(pts, pts[1:]) if abs(db(a[1]) - db(b[1])) > 1e-3]
        self.assertTrue(all(b[0] - a[0] <= 0.1 + 1e-6 for a, b in moving))   # a point every 0.1 s while it moves
        d = np.array([db(v) for _, v in pts])
        rate = np.abs(np.diff(d)) / np.diff(ts)
        self.assertLess(rate.max(), 2 * 6 / VL.RAMP_S + 0.1)                   # a 6 dB move, Hann-smoothed over 1.2 s
        self.assertLess(np.abs(np.diff(d)).max(), 1.05)                         # at most ~1 dB per 0.1 s point
        self.assertAlmostEqual(VL.steepest([(1.0, 5.0, -3.0), (5.3, 9.0, 3.0)]), 2 * 6 / VL.RAMP_S, delta=0.2)

    def test_close_lines_blend(self):
        """Two lines with the same trim and a short gap: the curve stays down across the gap, no dip to 0."""
        x, _ = VL.write_gains(SET, "Vox", [(1.0, 4.0, -3.0), (4.2, 8.0, -3.0)])
        gap = [db(v) for t, v in env_points(x) if 3.5 <= t <= 4.7]
        self.assertTrue(gap and all(abs(g + 3.0) < 0.05 for g in gap))

    def test_no_change_writes_nothing(self):
        x, k = VL.write_gains(SET, "Vox", [(1.0, 2.0, 0.0)])
        self.assertEqual((x, k), (SET, 0))


def track(kind, tid, name, group, pointee):
    return ('<%s Id="%s"><Name><EffectiveName Value="%s" /></Name><TrackGroupId Value="%s" />'
            '<AutomationEnvelopes><Envelopes /></AutomationEnvelopes>'
            '<DeviceChain><Mixer><Volume><Manual Value="1" /><AutomationTarget Id="%s" /></Volume></Mixer>'
            '</DeviceChain></%s>') % (kind, tid, name, group, pointee, kind)


def grouped_set(extra):
    return ('<Ableton><LiveSet><MasterTrack><DeviceChain><Mixer><Tempo><Manual Value="120" /></Tempo></Mixer>'
            '</DeviceChain></MasterTrack><Tracks>' + track("GroupTrack", 10, "Vocals 2", -1, 100) +
            track("AudioTrack", 11, "Lead", 10, 111) + track("AudioTrack", 12, "Harmony", 10, 112) + extra +
            '</Tracks></LiveSet></Ableton>')


class Groups(unittest.TestCase):
    GAINS = {"Harmony": [(1.0, 4.0, -2.0), (4.5, 8.0, 0.0)], "__group__": [(1.0, 4.0, 0.0), (4.5, 8.0, 2.5)]}

    def test_a_vocal_only_group_is_automated(self):
        x, done, worst = VL.apply_gains(grouped_set(""), self.GAINS, "Vocals 2", ["Lead", "Harmony"], log=lambda m: 0)
        self.assertIn("100", re.findall(r'<PointeeId Value="(\d+)"', x))
        self.assertNotIn("111", re.findall(r'<PointeeId Value="(\d+)"', x))
        self.assertGreater(worst, 0)

    def test_a_group_holding_strings_is_never_automated(self):
        msgs = []
        s = grouped_set(track("AudioTrack", 13, "Strings", 10, 113))
        self.assertEqual(VL.non_vocal_members(s, "Vocals 2", ["Lead", "Harmony"]), ["Strings"])
        x, done, _ = VL.apply_gains(s, self.GAINS, "Vocals 2", ["Lead", "Harmony"], log=msgs.append)
        targets = re.findall(r'<PointeeId Value="(\d+)"', x)
        self.assertNotIn("100", targets)                         # the group: untouched
        self.assertNotIn("113", targets)                         # the strings: untouched
        self.assertIn("111", targets)
        self.assertTrue(msgs and "Strings" in msgs[0])
        self.assertAlmostEqual(db_at(x, 6.5, "111"), 2.5, delta=0.05)    # the line evening, on the vocal track
        self.assertAlmostEqual(db_at(x, 2.0, "112"), -2.0, delta=0.05)   # its own trim
        self.assertAlmostEqual(db_at(x, 6.5, "112"), 2.5, delta=0.05)    # plus the evening

    def test_nested_non_vocal_tracks_count(self):
        s = grouped_set(track("GroupTrack", 14, "Pads", 10, 114) + track("AudioTrack", 15, "Pad", 14, 115))
        self.assertEqual(VL.non_vocal_members(s, "Vocals 2", ["Lead", "Harmony"]), ["Pad"])


if __name__ == "__main__":
    unittest.main()
