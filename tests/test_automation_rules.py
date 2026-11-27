"""The smooth-automation rules (engineer/automation_rules.py): S-curves, line moves <= 3 dB, trims <= 4 dB, the steepest
point under 7 dB/s, on the line at both ends, and never a bus or group that carries a track that is not a vocal."""
import math
import unittest

from hypnomix.engineer import automation_rules as AR


def write(points, control="gain", curve="s_curve", **kw):
    return dict(track_id="1", control=control, curve=curve, points=[{"time": t, "value": v} for t, v in points], **kw)


VOCAL_BUS = {"trackName": "Vox", "isBus": True, "busOfGroup": {"members": [
    {"trackId": "2", "name": "Lead Vocal", "routeType": "audio_track"},
    {"trackId": "3", "name": "Harmony 1", "routeType": "audio_track"}]}, "feeders": []}
MIXED_BUS = {"trackName": "Band", "isBus": True, "busOfGroup": None, "feeders": [
    {"trackId": "2", "name": "Lead Vocal", "routeType": "audio_track"},
    {"trackId": "4", "name": "Drums", "routeType": "audio_track"},
    {"trackId": "5", "name": "Strings", "routeType": "audio_track"}]}


class Rules(unittest.TestCase):
    def test_a_gentle_ride_passes(self):
        ride = write([(10, -2), (11.2, -4.5), (14, -4.5), (15.2, -2)])
        self.assertEqual(AR.check(ride), [])
        self.assertEqual(AR.check(ride, VOCAL_BUS), [])

    def test_kinds(self):
        self.assertEqual([AR.kind(c) for c in ("gain", "fader", "trim", "send:77", "pan_azimuth", "mute", "plugin:9:2", "x")],
                         ["gain", "gain", "trim", "send", "pan", "mute", "plugin", "other"])

    def test_line_and_trim_caps(self):
        self.assertTrue(any("at most 3 dB" in p for p in AR.check(write([(0, 0), (3, -3.5)]))))
        self.assertEqual(AR.check(write([(0, 0), (3, -3.5)], control="trim")), [])
        self.assertTrue(any("at most 4 dB" in p for p in AR.check(write([(0, 0), (3, -4.5)], control="trim"))))
        self.assertTrue(any("at most 3 dB" in p for p in AR.check(write([(0, 0), (3, 3.2)], control="send:12"))))

    def test_the_steepest_point_of_an_s_curve(self):
        # 3 dB over 0.6 s: average 5 dB/s, an S-curve peaks at pi/2 times that = 7.85 dB/s
        bad = AR.check(write([(0, 0), (0.6, -3)]))
        self.assertTrue(any("dB/s" in p and "needs at least" in p for p in bad), bad)
        need = AR.shortest(-3)
        self.assertAlmostEqual(need, math.pi / 2 * 3 / 7)
        self.assertEqual(AR.check(write([(0, 0), (need + 0.02, -3)])), [])
        self.assertAlmostEqual(AR.steepest([(0, 0), (1.2, -3)]), math.pi / 2 * 2.5, places=6)

    def test_s_curves_only_never_force_never_silence_never_a_jump(self):
        self.assertTrue(any("S-curves" in p for p in AR.check(write([(0, 0), (2, -2)], curve="linear"))))
        self.assertTrue(any("force" in p for p in AR.check(write([(0, 0), (2, -2)], force=True))))
        self.assertTrue(any("silence" in p for p in AR.check(write([(0, 0), (2, None)]))))
        self.assertTrue(any("time order" in p for p in AR.check(write([(0, 0), (0, -2)]))))
        self.assertTrue(any("at least two points" in p for p in AR.check(write([(1, -2)]))))

    def test_on_the_line_at_both_ends(self):
        line = AR.line_from({"pointList": [{"time": 0, "value": -2.0}, {"time": 20, "value": -2.0}]})
        self.assertEqual(AR.check(write([(5, -2), (6.2, -4), (8, -4), (9.2, -2)]), line=line), [])
        bad = AR.check(write([(5, 0), (6.2, -2)]), line=line)
        self.assertTrue(any("starts at 0.0 dB" in p for p in bad), bad)
        self.assertEqual(AR.check(write([(5, 0), (6.2, -2)], mode="replace-all"), line=line), [])
        flat = AR.line_from({"pointList": []}, current=-6.0)
        self.assertEqual(flat(3), -6.0)
        self.assertIsNone(AR.line_from({}, None))

    def test_one_point_on_the_line_may_be_added_and_the_range_is_the_points(self):
        line = AR.line_from({"pointList": [{"time": 0, "value": -2.0}, {"time": 20, "value": -2.0}]})
        self.assertEqual(AR.check(write([(5, -2.0)], start=5, end=5), line=line), [])
        self.assertTrue(AR.check(write([(5, -3.0)]), line=line))                     # off the line: a jump
        self.assertTrue(AR.check(write([(5, -2.0)]), line=None))                      # the line unknown: not allowed
        wide = AR.check(write([(5, -2.0)], start=0, end=20), line=line)               # would wipe the rides around it
        self.assertTrue(any("start must be the first point's time" in p for p in wide), wide)
        ride = write([(5, -2), (6.2, -4), (8, -4), (9.2, -2)], start=1)
        self.assertTrue(any("start must be" in p for p in AR.check(ride, line=line)))
        self.assertEqual(AR.check(dict(ride, start=5, end=9.2), line=line), [])
        self.assertTrue(AR.check(write([(5, -2.0)], mode="replace-all"), line=line))  # replace-all: never a lone point

    def test_never_a_bus_that_carries_non_vocals(self):
        bad = AR.check(write([(0, 0), (2, -2)]), MIXED_BUS)
        self.assertTrue(any("Band carries Drums, Strings" in p for p in bad), bad)
        self.assertEqual(AR.non_vocal(MIXED_BUS), ["Drums", "Strings"])
        self.assertEqual(AR.non_vocal(VOCAL_BUS), [])
        self.assertEqual(AR.non_vocal({"isBus": False}), [])
        midi = dict(VOCAL_BUS, feeders=[{"trackId": "9", "name": "Vocal Synth", "routeType": "midi_track"}])
        self.assertEqual(AR.non_vocal(midi), ["Vocal Synth"])          # an instrument is never a vocal
        master = {"trackName": "Master", "isMaster": True, "feeders": [{"trackId": "4", "name": "Drums"}]}
        self.assertTrue(AR.check(write([(0, 0), (2, -1)]), master))

    def test_other_controls_are_not_level_moves(self):
        self.assertEqual(AR.check(write([(0, -1), (0.1, 1)], control="pan_azimuth", curve="linear"), MIXED_BUS), [])
        self.assertEqual(AR.check(write([(0, 0), (0.01, 1)], control="plugin:7:3", curve="linear")), [])

    def test_s_points_follow_a_raised_cosine(self):
        pts = AR.s_points([(0, 0.0), (1.2, -3.0)])
        self.assertEqual(pts[0], (0, 0.0))
        self.assertAlmostEqual(pts[-1][1], -3.0)
        mid = min(pts, key=lambda p: abs(p[0] - 0.6))
        self.assertAlmostEqual(mid[1], -1.5, places=6)
        self.assertTrue(all(b[0] > a[0] for a, b in zip(pts, pts[1:])))

    def test_a_ranged_clear_never_leaves_a_straight_move(self):
        lane = {"pointList": [{"time": 0, "value": 0.0}, {"time": 5, "value": 0.0}, {"time": 6.2, "value": -2.5},
                              {"time": 9, "value": -2.5}, {"time": 10.2, "value": 0.0}]}
        bad = AR.check_clear({"control": "gain", "start": 5.5, "end": 8}, lane)      # 0 dB at 5 s to -2.5 dB at 9 s
        self.assertTrue(bad and "straight move" in bad[0], bad)
        self.assertEqual(AR.check_clear({"control": "gain", "start": 5.5, "end": 9.5}, lane), [])    # level either side
        self.assertEqual(AR.check_clear({"control": "gain"}, lane), [])                              # the whole lane
        self.assertEqual(AR.check_clear({"control": "pan_azimuth", "start": 5.5, "end": 9.5}, lane), [])

    def test_one_sentence(self):
        s = AR.sentence(["a", "b"])
        self.assertTrue(s.startswith("not written (HypnoMix's smooth-automation rules): a; b"))


if __name__ == "__main__":
    unittest.main()
