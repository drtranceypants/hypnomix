"""The smooth-automation rules (engineer/automation_rules.py): S-curves, line moves <= 3 dB, trims <= 4 dB, the steepest
point under 7 dB/s, on the line at both ends, and never a bus or group that carries a track that is not a vocal (its
level or, the one rule for them, its plug-in parameters)."""
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


_ON = object()


def check(w, facts=None, line=_ON, **kw):
    """AR.check with a line as heard that meets the write at both ends (straight from its first value to its last), for
    the rules other than its edges."""
    if line is _ON:
        pts = [p for p in AR.points_of(w.get("points")) if p[1] is not None] or [(0.0, 0.0)]
        line = AR.line_from({"pointList": [{"time": t, "value": v} for t, v in (pts[0], pts[-1])]})
    return AR.check(w, facts, line, **kw)


class Rules(unittest.TestCase):
    def test_a_gentle_ride_passes(self):
        ride = write([(10, -2), (11.2, -4.5), (14, -4.5), (15.2, -2)])
        self.assertEqual(check(ride), [])
        self.assertEqual(check(ride, VOCAL_BUS), [])

    def test_kinds(self):
        self.assertEqual([AR.kind(c) for c in ("gain", "fader", "trim", "send:77", "pan_azimuth", "mute", "plugin:9:2", "x")],
                         ["gain", "gain", "trim", "send", "pan", "mute", "plugin", "other"])
        self.assertEqual(AR.kind("volume"), "gain")          # the engine takes volume for the fader too

    def test_force_as_the_engine_reads_it(self):
        for f in (True, "true", 1, "1"):
            self.assertTrue(any("force" in p for p in check(write([(0, 0), (2, -2)], force=f))), f)
        for f in (False, "false", 0, None):
            self.assertEqual(check(write([(0, 0), (2, -2)], force=f)), [], f)

    def test_a_bus_is_judged_by_what_it_carries_not_its_name(self):
        # a bus named like vocals that feeds this one also carries the strings: read in turn, it is not only vocals
        outer = {"trackId": "10", "trackName": "Vox Master", "isBus": True, "busOfGroup": None, "feeders": [
            {"trackId": "11", "name": "Vocals 2", "routeType": "bus"},
            {"trackId": "2", "name": "Lead Vocal", "routeType": "audio_track"}]}
        inner = {"trackId": "11", "trackName": "Vocals 2", "isBus": True, "busOfGroup": None, "feeders": [
            {"trackId": "3", "name": "Harmony 1", "routeType": "audio_track"},
            {"trackId": "5", "name": "Strings", "routeType": "audio_track"}]}
        reads = lambda tool, args: inner if (tool, args.get("track_id")) == ("automation_list", "11") else None
        self.assertEqual(AR.non_vocal(outer, reads), ["Strings"])
        self.assertTrue(any("Strings" in p for p in check(write([(10, -2), (11.2, -4.5)]), outer, read=reads)))
        self.assertEqual(AR.non_vocal(outer), ["Vocals 2"])        # not read: a bus counts as not only vocals
        only = dict(inner, feeders=inner["feeders"][:1])
        self.assertEqual(AR.non_vocal(outer, lambda tool, args: only), [])

    def test_line_and_trim_caps(self):
        o = AR.flat(0.0)                                   # the original line: 0 dB
        self.assertTrue(any("at most 3 dB" in p for p in check(write([(0, 0), (3, -3.5)]), original=o)))
        self.assertEqual(check(write([(0, 0), (3, -3.5)], control="trim"), original=o), [])
        self.assertTrue(any("at most 4 dB" in p for p in check(write([(0, 0), (3, -4.5)], control="trim"), original=o)))
        self.assertTrue(any("at most 3 dB" in p for p in check(write([(0, 0), (3, 3.2)], control="send:12"), original=o)))

    def test_the_steepest_point_of_an_s_curve(self):
        # 3 dB over 0.6 s: average 5 dB/s, an S-curve peaks at pi/2 times that = 7.85 dB/s
        bad = check(write([(0, 0), (0.6, -3)]))
        self.assertTrue(any("dB/s" in p and "needs at least" in p for p in bad), bad)
        need = AR.shortest(-3)
        self.assertAlmostEqual(need, math.pi / 2 * 3 / 7)
        self.assertEqual(check(write([(0, 0), (need + 0.02, -3)])), [])
        self.assertAlmostEqual(AR.steepest([(0, 0), (1.2, -3)]), math.pi / 2 * 2.5, places=6)

    def test_s_curves_only_never_force_never_silence_never_a_jump(self):
        self.assertTrue(any("S-curves" in p for p in check(write([(0, 0), (2, -2)], curve="linear"))))
        self.assertTrue(any("force" in p for p in check(write([(0, 0), (2, -2)], force=True))))
        self.assertTrue(any("silence" in p for p in check(write([(0, 0), (2, None)]))))
        self.assertTrue(any("time order" in p for p in check(write([(0, 0), (0, -2)]))))
        self.assertTrue(any("at least two points" in p for p in check(write([(1, -2)]), line=AR.flat(0.0))))

    def test_on_the_line_at_both_ends(self):
        line = AR.line_from({"pointList": [{"time": 0, "value": -2.0}, {"time": 20, "value": -2.0}]})
        self.assertEqual(check(write([(5, -2), (6.2, -4), (8, -4), (9.2, -2)]), line=line), [])
        bad = check(write([(5, 0), (6.2, -2)]), line=line)
        self.assertTrue(any("starts at 0.0 dB" in p for p in bad), bad)
        self.assertTrue(check(write([(5, 0), (6.2, -2)], mode="replace-all"), line=line))   # replace-all too
        flat = AR.line_from({"pointList": []}, current=-6.0)
        self.assertEqual(flat(3), -6.0)
        self.assertIsNone(AR.line_from({}, None))

    def test_one_point_on_the_line_may_be_added_and_the_range_is_the_points(self):
        line = AR.line_from({"pointList": [{"time": 0, "value": -2.0}, {"time": 20, "value": -2.0}]})
        self.assertEqual(check(write([(5, -2.0)], start=5, end=5), line=line), [])
        self.assertTrue(check(write([(5, -3.0)]), line=line))                     # off the line: a jump
        self.assertTrue(check(write([(5, -2.0)]), line=None))                      # the line unknown: not allowed
        wide = check(write([(5, -2.0)], start=0, end=20), line=line)               # would wipe the rides around it
        self.assertTrue(any("start must be the first point's time" in p for p in wide), wide)
        ride = write([(5, -2), (6.2, -4), (8, -4), (9.2, -2)], start=1)
        self.assertTrue(any("start must be" in p for p in check(ride, line=line)))
        self.assertEqual(check(dict(ride, start=5, end=9.2), line=line), [])
        self.assertTrue(check(write([(5, -2.0)], mode="replace-all"), line=line))  # replace-all: never a lone point

    def test_never_a_bus_that_carries_non_vocals(self):
        bad = check(write([(0, 0), (2, -2)]), MIXED_BUS)
        self.assertTrue(any("Band carries Drums, Strings" in p for p in bad), bad)
        self.assertEqual(AR.non_vocal(MIXED_BUS), ["Drums", "Strings"])
        self.assertEqual(AR.non_vocal(VOCAL_BUS), [])
        self.assertEqual(AR.non_vocal({"isBus": False}), [])
        midi = dict(VOCAL_BUS, feeders=[{"trackId": "9", "name": "Vocal Synth", "routeType": "midi_track"}])
        self.assertEqual(AR.non_vocal(midi), ["Vocal Synth"])          # an instrument is never a vocal
        master = {"trackName": "Master", "isMaster": True, "feeders": [{"trackId": "4", "name": "Drums"}]}
        self.assertTrue(check(write([(0, 0), (2, -1)]), master))

    def test_other_controls_are_not_level_moves(self):
        self.assertEqual(check(write([(0, -1), (0.1, 1)], control="pan_azimuth", curve="linear"), MIXED_BUS), [])
        self.assertEqual(check(write([(0, 0), (0.01, 1)], control="plugin:7:3", curve="linear")), [])
        self.assertEqual([AR.checked(c) for c in ("gain", "trim", "send:3", "plugin:7:3", "pan_azimuth", "mute", "x")],
                         [True, True, True, True, False, False, False])

    def test_plug_in_automation_never_on_a_bus_that_carries_non_vocals(self):
        sweep = write([(0, 16000.0), (8, 400.0)], control="plugin:7:3", curve="linear")
        bad = check(sweep, MIXED_BUS)
        self.assertEqual(len(bad), 1, bad)                               # the mixed-bus rule only
        self.assertIn("Band carries Drums, Strings, not only vocals: its plug-in automation is never written", bad[0])
        self.assertIn("automate a vocal track's plug-in instead", bad[0])
        self.assertEqual(check(sweep, VOCAL_BUS), [])                 # a bus of vocals only
        self.assertEqual(check(sweep, {"trackName": "Drums", "isBus": False}), [])   # a plain track
        master = {"trackName": "Master", "isMaster": True, "feeders": [{"trackId": "4", "name": "Drums"}]}
        self.assertTrue(check(sweep, master))

    def test_a_feeding_bus_that_cannot_be_read_counts_as_not_only_vocals_for_plug_ins_too(self):
        outer = {"trackId": "10", "trackName": "Vox Master", "isBus": True, "busOfGroup": None, "feeders": [
            {"trackId": "11", "name": "Vocals 2", "routeType": "bus"},
            {"trackId": "2", "name": "Lead Vocal", "routeType": "audio_track"}]}
        sweep = write([(0, 16000.0), (8, 400.0)], control="plugin:7:3", curve="linear")
        bad = check(sweep, outer, read=lambda tool, args: None)
        self.assertTrue(bad and "Vox Master carries Vocals 2" in bad[0], bad)
        inner = {"trackId": "11", "trackName": "Vocals 2", "isBus": True, "feeders": [
            {"trackId": "3", "name": "Harmony 1", "routeType": "audio_track"}]}
        self.assertEqual(check(sweep, outer, read=lambda tool, args: inner), [])

    def test_the_level_rules_are_not_applied_to_plug_in_values(self):
        # a jump of thousands (Hz), linear, one point, force, start/end off the points, silence: all fine on a track
        for w in (write([(0, 16000.0), (0.01, 200.0)], control="plugin:7:3", curve="linear"),
                  write([(5, 0.3)], control="plugin:7:3", curve="linear", start=0, end=20),
                  write([(0, 1.0), (1, None)], control="plugin:7:3", force=True)):
            self.assertEqual(check(w, VOCAL_BUS, line=lambda t: 0.0), [], w)

    def test_a_plug_in_lane_may_be_cleared_anywhere(self):
        lane = {"pointList": [{"time": 0, "value": 16000.0}, {"time": 8, "value": 400.0}, {"time": 9, "value": 9000.0}]}
        self.assertEqual(AR.check_clear({"control": "plugin:7:3", "start": 1, "end": 8.5}, lane), [])
        self.assertEqual(AR.check_clear({"control": "plugin:7:3"}, lane), [])

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


def lane(points=(), state="play"):
    return {"pointList": [{"time": t, "value": v} for t, v in points], "state": state}


def facts(current=0.0, state="manual", control="gain"):
    return {"trackName": "Lead Vocal", "isBus": False, "controls": [{"control": control, "current": current, "state": state}]}


class RoundThreeFixes(unittest.TestCase):
    """The round-3 review: replace-all, an unknown line, a lane that is Off, string numbers, recording states, the
    original line (the owner's ruling: 3 dB means the distance from the original line), and the engine's spellings."""

    def test_replace_all_starts_and_ends_on_the_controls_value(self):
        # the review's example: a fader at 0 dB with no points, replace-all from -20 dB: on Play it would jump
        w = write([(0, -20), (5, -17)], mode="replace-all")
        bad = AR.judge(w, facts(0.0), lane([], "manual"))
        self.assertTrue(any("starts at -20.0 dB" in p for p in bad), bad)
        self.assertTrue(AR.judge(dict(w, mode="replace_all"), facts(0.0), lane([], "manual")))   # the engine's spelling
        ok = write([(5, 0), (6.2, -2), (9, -2), (10.2, 0)], mode="replace-all")
        self.assertEqual(AR.judge(ok, facts(0.0), lane([], "manual")), [])

    def test_an_unknown_line_refuses_and_never_assumes_0_db(self):
        ride = write([(5, 0), (6.2, -2), (9, -2), (10.2, 0)])
        for f in (facts(None), {"controls": []}, None):                     # -inf (null), not listed, not read
            bad = AR.judge(ride, f, lane([], "manual"))
            self.assertTrue(any("never assumes 0 dB" in p for p in bad), (f, bad))
        self.assertTrue(any("never assumes 0 dB" in p for p in AR.check(ride)))   # check() itself refuses
        self.assertIsNone(AR.heard(lane([], "manual"), None))
        self.assertTrue(AR.judge_state({"control": "gain", "state": "play"}, facts(None),
                                       lane([(0, 0), (5, 0)], "manual")))

    def test_a_lane_that_is_off_is_judged_against_the_controls_value(self):
        # an old -6 dB ride on a lane switched Off, the fader at 0 dB: a gentle ride on 0 dB would switch it to play
        old = lane([(20, -6), (30, -6)], "manual")
        ride = write([(5, 0), (6.2, -1), (8, -1), (9.2, 0)], start=5, end=9.2)
        bad = AR.judge(ride, facts(0.0), old)
        self.assertTrue(bad and any("-6.0 dB" in p for p in bad), bad)
        on_points = write([(5, -6), (6.2, -7), (8, -7), (9.2, -6)], start=5, end=9.2)
        bad = AR.judge(on_points, facts(0.0), old)                          # on the old points: not on what is heard
        self.assertTrue(any("line there is 0.0 dB" in p for p in bad), bad)
        self.assertEqual(AR.judge(dict(ride, state="manual"), facts(0.0), old), [])   # stays off: the old points stay unheard
        played = lane([(20, -6), (30, -6)], "play")                         # the same points playing: judged on them
        self.assertEqual(AR.judge(write([(21, -6), (22.2, -7), (25, -7), (26.2, -6)], start=21, end=26.2),
                                  facts(0.0), played, original=AR.flat(-6.0)), [])

    def test_switching_a_lane_to_play_is_checked_the_same_way(self):
        st = {"control": "gain", "state": "play"}
        self.assertTrue(AR.judge_state(st, facts(0.0), lane([(20, -6), (30, -6)], "manual")))          # a jump to -6
        ok = lane([(5, 0), (6.2, -1), (8, -1), (9.2, 0)], "manual")
        self.assertEqual(AR.judge_state(st, facts(0.0), AR.normal(ok)), [])
        steep = lane([(5, 0), (5.1, -2), (6, 0)], "manual")
        self.assertTrue(any("dB/s" in p for p in AR.judge_state(st, facts(0.0), steep)))
        far = lane([(5, 0), (8, -3.5), (12, 0)], "manual")
        self.assertTrue(any("original line" in p for p in AR.judge_state(st, facts(0.0), far)))
        self.assertEqual(AR.judge_state({"control": "gain", "state": "manual"}, facts(0.0), far), [])  # off: allowed
        self.assertEqual(AR.judge_state(st, facts(0.0), lane([(5, 0), (8, -6)], "play")), [])         # already playing
        bus = dict(MIXED_BUS, controls=[{"control": "plugin:7:3", "current": 1.0}])
        self.assertTrue(AR.judge_state({"control": "plugin:7:3", "state": "play"}, bus, lane([(0, 1), (2, 5)], "manual")))

    def test_recording_states_are_never_set(self):
        for s in ("write", "touch", "latch"):
            for ctl in ("gain", "trim", "send:3", "plugin:7:3"):
                bad = AR.judge(write([(5, 0), (6.2, -1)], control=ctl, state=s, curve="s_curve" if ctl != "plugin:7:3" else "linear"),
                               facts(0.0, control=ctl), lane([], "manual"))
                self.assertTrue(any("recording mode" in p for p in bad), (s, ctl, bad))
                self.assertTrue(AR.judge_state({"control": ctl, "state": s}, facts(0.0, control=ctl), lane([], "manual")))
            self.assertEqual(AR.judge_state({"control": "pan_azimuth", "state": s}), [])          # not held to the rules
        keep = AR.judge(write([(5, 0), (6.2, -1), (8, -1), (9.2, 0)], state="keep"), facts(0.0), lane([], "touch"))
        self.assertTrue(any("keep would leave it there" in p for p in keep), keep)

    def test_start_and_end_are_numbers_as_the_engine_reads_them(self):
        ride = write([(5, 0), (6.2, -1), (8, -1), (9.2, 0)])
        for v in ("5", "", True, [5]):
            bad = AR.judge(dict(ride, start=v, end=9.2), facts(0.0), lane([], "manual"))
            self.assertTrue(any("must be a number of seconds" in p for p in bad), (v, bad))
        lanes = lane([(0, 0), (5, 0), (6.2, -2.5), (9, -2.5), (10.2, 0)])
        self.assertTrue(any("number" in p for p in AR.check_clear({"control": "gain", "start": "5", "end": "8"}, lanes)))

    def test_a_clear_from_one_edge_only_is_refused_on_a_level_lane(self):
        lanes = lane([(0, 0), (5, 0), (6.2, -2.5), (9, -2.5)])
        for a in ({"start": 7}, {"end": 7}):
            self.assertTrue(AR.check_clear(dict(a, control="gain"), lanes), a)
        self.assertEqual(AR.check_clear({"control": "plugin:7:3", "start": 7}, lanes), [])

    def test_three_db_is_the_distance_from_the_original_line(self):
        # the owner's ruling: 0 -> +3 -> +6 -> +3 -> 0 dB in one write is refused (each step is 3 dB, +6 is 6 from it)
        climb = write([(10, 0), (12, 3), (14, 6), (16, 3), (18, 0)])
        bad = AR.judge(climb, facts(0.0), lane([], "manual"))
        self.assertTrue(any("from the original line" in p and "at most 3 dB" in p for p in bad), bad)
        once = write([(10, 0), (12, 3), (16, 3), (18, 0)], start=10, end=18)
        self.assertEqual(AR.judge(once, facts(0.0), lane([], "manual")), [])
        # written (the lane now plays it): a second +3 dB on top is 6 dB from the original line, refused
        after = lane(AR.s_points([(10, 0), (12, 3), (16, 3), (18, 0)]), "play")
        again = write([(12, 3), (13.2, 6), (15, 6), (16, 3)], start=12, end=16)
        self.assertEqual(AR.judge(again, facts(0.0), after, original=None), [])     # without the original it would pass
        bad = AR.judge(again, facts(0.0), after, original=AR.flat(0.0))
        self.assertTrue(any("from the original line" in p for p in bad), bad)
        back = write([(12, 3), (13.2, 0), (15, 0), (16, 3)], start=12, end=16)      # +3 and back to 0: allowed
        self.assertEqual(AR.judge(back, facts(0.0), after, original=AR.flat(0.0)), [])
        trim = write([(10, 0), (12, 4), (16, 4), (18, 0)], control="trim")          # a trim: 4 dB from it
        self.assertEqual(AR.judge(trim, facts(0.0, control="trim"), lane([], "manual")), [])
        self.assertTrue(AR.judge(write([(10, 0), (12, 4.5), (16, 4.5), (18, 0)], control="trim"),
                                 facts(0.0, control="trim"), lane([], "manual")))
        # the S between two points is looked at against the original's own points (a dip in it between them)
        dip = AR.line_from(lane([(10, 0), (12, -3), (14, 0)]))
        flat_hi = write([(9, 0), (9.8, 2.9), (14.2, 2.9), (15, 0)])
        self.assertTrue(AR.check(flat_hi, None, AR.flat(0.0), original=dip))

    def test_the_engines_spellings(self):
        a = AR.normal({"mode": "replace_all", "curve": "s-curve"})
        self.assertEqual((a["mode"], a["curve"]), ("replace-all", "s_curve"))
        ride = write([(5, 0), (6.2, -1), (8, -1), (9.2, 0)], curve="s-curve")
        self.assertEqual(AR.judge(ride, facts(0.0), lane([], "manual")), [])


class Checker(unittest.TestCase):
    """The checker's pass on the round-3 fixes: names as the engine reads them, and the original line after a clear."""

    def test_names_and_words_as_the_engine_reads_them(self):
        n = AR.normal({"control": "volume", "track_id": "007", "mode": "replace_all", "curve": "s-curve"})
        self.assertEqual((n["control"], n["track_id"], n["mode"], n["curve"]), ("gain", "7", "replace-all", "s_curve"))
        self.assertEqual(AR.canon_route("２"), "２")            # not the engine's digits: left as given (it refuses it)
        self.assertEqual(AR.normal({"control": "fader", "track_id": 3})["track_id"], "3")
        for key in ("state", "mode", "curve"):
            self.assertTrue(any(key + " must be a word" in p for p in AR.arg_problems({key: ["x"]})), key)
            self.assertEqual(AR.arg_problems({key: None}), [])

    def test_a_kept_original_outlives_a_clear_and_an_alias(self):
        import tempfile
        from hypnomix.engineer import automation_original as AO
        with tempfile.TemporaryDirectory() as td:
            AO.keep(td, "02", "fader", {"value": 0.0})
            self.assertEqual(AO.key("02", "fader"), "2|gain")
            line, entry, why = AO.pick(td, "2", "gain", {"pointList": [], "state": "manual"}, 3.0)
            self.assertEqual((line(5.0), entry, why), (0.0, None, ""))   # a cleared lane: the kept line, not the +3 held
            line, entry, why = AO.pick(td, "4", "gain", {"pointList": [], "state": "manual"}, 3.0)
            self.assertEqual((line(5.0), entry), (3.0, {"value": 3.0}))  # nothing kept: the control's value


if __name__ == "__main__":
    unittest.main()
